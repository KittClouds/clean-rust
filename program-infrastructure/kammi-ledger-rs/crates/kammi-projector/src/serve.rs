//! `kammi-projector serve`: the supervised projection process.
//!
//! JSON lines on stdin/stdout. Between requests it follows both journals; a retrieval request
//! first catches up to the memory position the caller committed (read-your-writes). When
//! stdin closes (the daemon exited) the process exits, so it never outlives its supervisor.
//!
//! ```text
//! {"id":1,"op":"status"}
//! {"id":2,"op":"fts","query":"...","count":32,"memory_seq":7}
//! {"id":3,"op":"vector","vector_b64":"<f32 LE>","count":32,"memory_seq":7}
//! {"id":4,"op":"neighbors","memory_id":"sha256:...","memory_seq":7}
//! -> {"id":1,"ok":true,"result":{...}}  |  {"id":1,"ok":false,"error":"..."}
//! ```

use std::io::{BufRead, Write};
use std::path::Path;
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::{Duration, Instant};

use base64::Engine;
use kammi_jcs::Value as Json;
use kammi_store::{JournalFollower, ObjectReader};

use super::{Error, Graph, Health};

const CATCH_UP_LIMIT: Duration = Duration::from_secs(60);

pub struct Server<'g, 'db> {
    pub graph: &'g Graph<'db>,
    pub main: JournalFollower,
    pub memory: JournalFollower,
    pub objects: ObjectReader,
    pub health: Health,
    pub started: Instant,
}

impl Server<'_, '_> {
    fn step(&mut self) -> Result<usize, Error> {
        let custody = self.graph.step(&mut self.main, 256)?;
        let memory = self
            .graph
            .step_memory(&mut self.memory, &mut self.objects, 256)?;
        Ok(custody + memory)
    }

    fn catch_up(&mut self, memory_seq: u64) -> Result<(), Error> {
        let deadline = Instant::now() + CATCH_UP_LIMIT;
        while self.memory.seq() < memory_seq {
            if self
                .graph
                .step_memory(&mut self.memory, &mut self.objects, 4096)?
                == 0
            {
                if Instant::now() > deadline {
                    return Err(format!(
                        "memory journal did not reach seq {memory_seq} (at {})",
                        self.memory.seq()
                    )
                    .into());
                }
                std::thread::sleep(Duration::from_millis(5));
            }
        }
        Ok(())
    }

    fn status(&self) -> Result<Json, Error> {
        Ok(kammi_core::obj! {
            "pid" => std::process::id(),
            "uptime_seconds" => self.started.elapsed().as_secs_f64(),
            "projection_seq" => self.main.seq(),
            "projection_head" => self.main.head().to_string(),
            "memory_seq" => self.memory.seq(),
            "memory_head" => self.memory.head().to_string(),
            "counts" => self.graph.counts()?,
            "memory" => self.graph.memory_counts()?,
            "last_verify" => self.health.last_verify.clone(),
            "last_quarantine" => self.health.last_quarantine.clone(),
        })
    }

    fn handle(&mut self, request: &Json) -> Result<Json, Error> {
        let op = request["op"].as_str().ok_or("request op missing")?;
        let count = || {
            request["count"]
                .as_u64()
                .map(|c| c as usize)
                .ok_or("count missing")
        };
        if let Some(seq) = request["memory_seq"].as_u64() {
            self.catch_up(seq)?;
        }
        match op {
            "status" => self.status(),
            "fts" => {
                let rows = self
                    .graph
                    .memory_fts(request["query"].as_str().ok_or("query missing")?, count()?)?;
                Ok(Json::Array(
                    rows.into_iter()
                        .map(|(id, score)| Json::Array(vec![Json::from(id), Json::from(score)]))
                        .collect(),
                ))
            }
            "vector" => {
                let raw = base64::engine::general_purpose::STANDARD
                    .decode(request["vector_b64"].as_str().ok_or("vector missing")?)?;
                let vector: Vec<f32> = raw
                    .chunks_exact(4)
                    .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
                    .collect();
                let rows = self.graph.memory_vector(&vector, count()?)?;
                Ok(Json::Array(
                    rows.into_iter()
                        .map(|(id, score)| Json::Array(vec![Json::from(id), Json::from(score)]))
                        .collect(),
                ))
            }
            "neighbors" => {
                let ids = self
                    .graph
                    .memory_neighbors(request["memory_id"].as_str().ok_or("memory_id missing")?)?;
                Ok(Json::from(ids))
            }
            other => Err(format!("unknown op {other}").into()),
        }
    }

    /// Runs until stdin closes.
    pub fn run(&mut self) -> Result<(), Error> {
        let (lines, requests) = mpsc::channel::<String>();
        std::thread::spawn(move || {
            for line in std::io::stdin().lock().lines() {
                let Ok(line) = line else { break };
                if lines.send(line).is_err() {
                    break;
                }
            }
        });
        let mut idle = false;
        loop {
            let wait = if idle {
                Duration::from_millis(50)
            } else {
                Duration::ZERO
            };
            match requests.recv_timeout(wait) {
                Ok(line) => {
                    let request: Json = serde_json::from_str(&line).unwrap_or(Json::Null);
                    let id = request["id"].clone();
                    let reply = match self.handle(&request) {
                        Ok(result) => {
                            kammi_core::obj! {"id" => id, "ok" => true, "result" => result}
                        }
                        Err(e) => {
                            kammi_core::obj! {"id" => id, "ok" => false, "error" => e.to_string()}
                        }
                    };
                    let mut out = std::io::stdout().lock();
                    writeln!(out, "{reply}")?;
                    out.flush()?;
                    idle = false;
                }
                Err(RecvTimeoutError::Timeout) => idle = self.step()? == 0,
                Err(RecvTimeoutError::Disconnected) => return Ok(()),
            }
        }
    }
}

/// Opens the followers at the projection's stored positions.
pub fn followers(graph: &Graph, store: &Path) -> Result<(JournalFollower, JournalFollower), Error> {
    let (seq, head) = graph.position()?;
    let (memory_seq, memory_head) = graph.memory_position()?;
    Ok((
        JournalFollower::resume(store, "main", seq, head),
        JournalFollower::resume(store, "memory", memory_seq, memory_head),
    ))
}
