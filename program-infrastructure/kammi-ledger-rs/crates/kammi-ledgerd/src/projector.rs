//! Supervision of the `kammi-projector` child and its RPC client.
//!
//! Journal and CAS are authority; the projection is disposable. Nothing here can stop a
//! custody write: if the projector dies it is restarted with backoff and resumes from the
//! position stored in its own database; while it is down, memory retrieval answers 503 and
//! `/v1/status` reports the outage.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Arc};
use std::time::{Duration, Instant};

use base64::Engine;
use kammi_core::{LedgerError, MemoryIndex};
use kammi_jcs::Value;
use parking_lot::Mutex;

#[derive(Debug, Clone)]
pub struct ProjectorConfig {
    pub exe: PathBuf,
    pub store: PathBuf,
    pub db: PathBuf,
    pub memory_dims: usize,
    /// Deep-verify an existing projection on every (re)start.
    pub verify: bool,
    /// Prepended to the child's PATH (the Ladybug runtime DLLs).
    pub native_dir: Option<PathBuf>,
}

#[derive(Default)]
struct Process {
    state: &'static str,
    pid: Option<u32>,
    stdin: Option<ChildStdin>,
    restarts: u64,
    started: Option<Instant>,
    last_exit: Option<String>,
    last_status: Value,
    last_status_at: Option<Instant>,
}

type Reply = mpsc::Sender<Result<Value, String>>;

pub struct Projector {
    config: ProjectorConfig,
    process: Mutex<Process>,
    pending: Mutex<HashMap<u64, Reply>>,
    next_id: AtomicU64,
    stopping: std::sync::atomic::AtomicBool,
}

impl Projector {
    /// Starts supervising. The child is spawned on a background thread.
    pub fn start(config: ProjectorConfig) -> Arc<Projector> {
        let projector = Arc::new(Projector {
            config,
            process: Mutex::new(Process {
                state: "STARTING",
                last_status: Value::Null,
                ..Default::default()
            }),
            pending: Mutex::new(HashMap::new()),
            next_id: AtomicU64::new(1),
            stopping: Default::default(),
        });
        let supervisor = projector.clone();
        std::thread::Builder::new()
            .name("projector-supervisor".into())
            .spawn(move || supervisor.supervise())
            .expect("spawn supervisor");
        let poller = projector.clone();
        std::thread::Builder::new()
            .name("projector-health".into())
            .spawn(move || poller.poll_health())
            .expect("spawn health poller");
        projector
    }

    fn spawn(&self, reset: bool) -> std::io::Result<Child> {
        let c = &self.config;
        let mut command = Command::new(&c.exe);
        command
            .arg("serve")
            .arg("--store")
            .arg(&c.store)
            .arg("--db")
            .arg(&c.db)
            .arg("--memory-dims")
            .arg(c.memory_dims.to_string())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        if c.verify {
            command.arg("--verify");
        }
        if reset {
            command.arg("--reset"); // after the subcommand: the projector reads argv[1] as it
        }
        if let Some(dir) = &c.native_dir {
            let path = std::env::var_os("PATH").unwrap_or_default();
            let mut joined = std::ffi::OsString::from(dir.as_os_str());
            joined.push(";");
            joined.push(path);
            command.env("PATH", joined);
        }
        command.spawn()
    }

    fn supervise(self: Arc<Self>) {
        let mut backoff = Duration::from_millis(250);
        // Crash-loop breaker: abnormal exits soon after start. After three in a row the next
        // projector quarantines its database before opening (`--reset`) and rebuilds.
        let mut fast_crashes = 0u32;
        while !self.stopping.load(Ordering::Relaxed) {
            let reset = fast_crashes >= 3;
            if reset {
                eprintln!(
                    "kammi-ledgerd: projector crash loop; restarting with a fresh projection"
                );
                fast_crashes = 0;
            }
            match self.spawn(reset) {
                Ok(mut child) => {
                    let started = Instant::now();
                    let stdout = child.stdout.take().expect("piped stdout");
                    {
                        let mut process = self.process.lock();
                        process.state = "RUNNING";
                        process.pid = Some(child.id());
                        process.stdin = child.stdin.take();
                        process.started = Some(started);
                    }
                    let reader = self.clone();
                    let lines = std::thread::spawn(move || reader.read_replies(stdout));
                    let status = child.wait();
                    let clean = status.as_ref().is_ok_and(|s| s.success());
                    let exit = status
                        .map(|s| s.to_string())
                        .unwrap_or_else(|e| e.to_string());
                    if !clean && started.elapsed() < Duration::from_secs(30) {
                        fast_crashes += 1;
                    } else {
                        fast_crashes = 0;
                    }
                    let _ = lines.join();
                    {
                        let mut process = self.process.lock();
                        process.state = if self.stopping.load(Ordering::Relaxed) {
                            "STOPPED"
                        } else {
                            "RESTARTING"
                        };
                        process.pid = None;
                        process.stdin = None;
                        process.restarts += 1;
                        process.last_exit = Some(exit.clone());
                    }
                    for (_, reply) in self.pending.lock().drain() {
                        let _ = reply.send(Err(format!("projector exited ({exit})")));
                    }
                    eprintln!("kammi-ledgerd: projector exited ({exit}); restarting");
                    if started.elapsed() > Duration::from_secs(60) {
                        backoff = Duration::from_millis(250);
                    }
                }
                Err(e) => {
                    let mut process = self.process.lock();
                    process.state = "FAILED_TO_START";
                    process.last_exit = Some(e.to_string());
                    process.restarts += 1;
                }
            }
            std::thread::sleep(backoff);
            backoff = (backoff * 2).min(Duration::from_secs(30));
        }
    }

    fn read_replies(&self, stdout: std::process::ChildStdout) {
        for line in BufReader::new(stdout).lines() {
            let Ok(line) = line else { break };
            // Correctly rounded floats: serde_json's default float parser can be one ulp off.
            let Ok(reply) = kammi_jcs::strict_json(line.as_bytes()) else {
                continue;
            };
            let Some(id) = reply["id"].as_u64() else {
                continue;
            };
            if let Some(sender) = self.pending.lock().remove(&id) {
                let result = if reply["ok"] == true {
                    Ok(reply["result"].clone())
                } else {
                    Err(reply["error"]
                        .as_str()
                        .unwrap_or("projector error")
                        .to_string())
                };
                let _ = sender.send(result);
            }
        }
    }

    /// One request/response round trip.
    pub fn request(&self, mut request: Value, timeout: Duration) -> Result<Value, String> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        request["id"] = Value::from(id);
        let (reply, answer) = mpsc::channel();
        self.pending.lock().insert(id, reply);
        {
            let mut process = self.process.lock();
            let Some(stdin) = process.stdin.as_mut() else {
                self.pending.lock().remove(&id);
                return Err(format!("projector is {}", process.state));
            };
            if writeln!(stdin, "{request}")
                .and_then(|_| stdin.flush())
                .is_err()
            {
                self.pending.lock().remove(&id);
                return Err("projector pipe closed".into());
            }
        }
        match answer.recv_timeout(timeout) {
            Ok(result) => result,
            Err(_) => {
                self.pending.lock().remove(&id);
                Err(format!(
                    "projector did not answer within {}s",
                    timeout.as_secs()
                ))
            }
        }
    }

    fn poll_health(self: Arc<Self>) {
        while !self.stopping.load(Ordering::Relaxed) {
            if self.process.lock().stdin.is_some() {
                if let Ok(status) =
                    self.request(kammi_core::obj! {"op" => "status"}, Duration::from_secs(5))
                {
                    let mut process = self.process.lock();
                    process.last_status = status;
                    process.last_status_at = Some(Instant::now());
                }
            }
            std::thread::sleep(Duration::from_secs(1));
        }
    }

    /// Kills the child (for tests and `G2`); the supervisor restarts it.
    pub fn kill_child(&self) -> Option<u32> {
        let pid = self.process.lock().pid?;
        let _ = Command::new("taskkill")
            .args(["/F", "/PID", &pid.to_string()])
            .output();
        Some(pid)
    }

    pub fn stop(&self) {
        self.stopping.store(true, Ordering::Relaxed);
        self.process.lock().stdin = None; // EOF: the child exits
    }

    /// The `projection` block of `/v1/status`, plus the lag against the journal.
    pub fn status(&self, journal_seq: u64, journal_head: &str, memory_seq: u64) -> Value {
        let process = self.process.lock();
        let last = &process.last_status;
        let projection_seq = last["projection_seq"].as_u64();
        let memory_projected = last["memory_seq"].as_u64();
        kammi_core::obj! {
            "process" => process.state,
            "pid" => process.pid.map_or(Value::Null, Value::from),
            "restarts" => process.restarts,
            "uptime_seconds" => process.started.filter(|_| process.pid.is_some()).map_or(Value::Null, |s| Value::from(s.elapsed().as_secs_f64())),
            "last_exit" => process.last_exit.clone().map_or(Value::Null, Value::from),
            "status_age_seconds" => process.last_status_at.map_or(Value::Null, |t| Value::from(t.elapsed().as_secs_f64())),
            "journal_seq" => journal_seq,
            "journal_head" => journal_head,
            "projection_seq" => projection_seq.map_or(Value::Null, Value::from),
            "projection_head" => last["projection_head"].clone(),
            "lag" => projection_seq.map_or(Value::Null, |p| Value::from(journal_seq.saturating_sub(p))),
            "memory_journal_seq" => memory_seq,
            "memory_seq" => memory_projected.map_or(Value::Null, Value::from),
            "memory_lag" => memory_projected.map_or(Value::Null, |p| Value::from(memory_seq.saturating_sub(p))),
            "memory" => last["memory"].clone(),
            "last_verify" => last["last_verify"].clone(),
            "last_quarantine" => last["last_quarantine"].clone(),
        }
    }
}

const SEARCH_TIMEOUT: Duration = Duration::from_secs(90);

fn unavailable(detail: String) -> LedgerError {
    LedgerError::Unavailable(format!("memory projection unavailable: {detail}"))
}

fn scored(value: Value) -> kammi_core::Result<Vec<(String, f64)>> {
    let rows = value
        .as_array()
        .ok_or_else(|| unavailable("malformed reply".into()))?;
    rows.iter()
        .map(|row| match (row[0].as_str(), row[1].as_f64()) {
            (Some(id), Some(score)) => Ok((id.to_string(), score)),
            _ => Err(unavailable("malformed row".into())),
        })
        .collect()
}

impl MemoryIndex for Projector {
    fn fts(
        &self,
        query: &str,
        count: usize,
        memory_seq: u64,
    ) -> kammi_core::Result<Vec<(String, f64)>> {
        let request = kammi_core::obj! {"op" => "fts", "query" => query, "count" => count, "memory_seq" => memory_seq};
        scored(self.request(request, SEARCH_TIMEOUT).map_err(unavailable)?)
    }

    fn vector(
        &self,
        vector: &[f32],
        count: usize,
        memory_seq: u64,
    ) -> kammi_core::Result<Vec<(String, f64)>> {
        let bytes: Vec<u8> = vector.iter().flat_map(|v| v.to_le_bytes()).collect();
        let request = kammi_core::obj! {
            "op" => "vector", "vector_b64" => base64::engine::general_purpose::STANDARD.encode(bytes),
            "count" => count, "memory_seq" => memory_seq,
        };
        scored(self.request(request, SEARCH_TIMEOUT).map_err(unavailable)?)
    }

    fn neighbors(&self, identity: &str, memory_seq: u64) -> kammi_core::Result<Vec<String>> {
        let request = kammi_core::obj! {"op" => "neighbors", "memory_id" => identity, "memory_seq" => memory_seq};
        let value = self.request(request, SEARCH_TIMEOUT).map_err(unavailable)?;
        Ok(value
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default())
    }
}
