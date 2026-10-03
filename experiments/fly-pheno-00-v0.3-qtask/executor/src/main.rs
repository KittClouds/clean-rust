mod graph;
mod rng;
mod sim;
mod task;

use anyhow::{Context, Result, ensure};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use sim::Sim;
use std::{collections::BTreeMap, fs::{self, File, OpenOptions}, io::{BufWriter, Read, Write}, path::{Path, PathBuf}, sync::Arc, time::Instant};
use task::Task;

const TAU: f32 = 16.0;
const ETA: f32 = 0.05;
const GLUT_SIGN: f32 = -1.0;
const THRESHOLD: f64 = 0.25;
const HORIZONS: [usize; 5] = [512, 1024, 2048, 4096, 8192];
const RUNGS: [&str; 4] = ["T1", "T2", "T3", "T4"];
const SUBSTRATES: [&str; 9] = ["fly", "g001", "g002", "g003", "g004", "g005", "g006", "g007", "g008"];
const SIDES: [&str; 2] = ["L", "R"];
const BLOCKS: [u64; 12] = [32000, 32001, 32002, 32003, 32004, 32005, 32006, 32007, 32008, 32009, 32010, 32011];

#[derive(Deserialize)]
struct TrainBlock { task_seed: u64, labels: Vec<bool>, schedule: Vec<Vec<usize>>, cue_count: usize }
#[derive(Deserialize)]
struct TrainBank { blocks: BTreeMap<String, BTreeMap<String, TrainBlock>> }
#[derive(Deserialize)]
struct EvalBank { response_draws_u64: Vec<Vec<u64>> }

#[derive(Clone, Copy)]
struct Job { rung: &'static str, substrate: &'static str, side: &'static str, block: u64 }

#[derive(Serialize)]
struct FrontierRow<'a> {
    rung: &'a str, cues: usize, substrate: &'a str, side: &'a str, block: u64, horizon: usize,
    loss: f64, competent: bool, state_digest: String, finite: bool,
}

fn hash_file(path: &Path) -> Result<String> {
    let mut file = File::open(path).with_context(|| path.display().to_string())?;
    let mut hash = Sha256::new(); let mut buf = [0u8; 65_536];
    loop { let n = file.read(&mut buf)?; if n == 0 { break; } hash.update(&buf[..n]); }
    Ok(format!("{:x}", hash.finalize()))
}

fn verify_contract(study: &Path) -> Result<Value> {
    let path = study.join("manifests/QTASK-CONTRACT.json");
    let expected = fs::read_to_string(study.join("manifests/QTASK-CONTRACT.sha256"))?.split_whitespace().next().context("contract sidecar")?.to_string();
    ensure!(hash_file(&path)? == expected, "QTASK contract checksum mismatch");
    let contract: Value = serde_json::from_reader(File::open(path)?)?;
    ensure!(contract["status"] == "SEALED_QUALIFICATION_ONLY");
    ensure!(contract["no_lesions"] == true && contract["no_recovery_comparison"] == true);
    for entry in contract["input_hashes"].as_array().context("input hashes")? {
        let rel = entry["path"].as_str().context("input path")?;
        ensure!(hash_file(&study.join(rel))? == entry["sha256"].as_str().unwrap(), "input hash mismatch: {rel}");
    }
    ensure!(contract["executable_sha256"].as_str().unwrap().len() == 64);
    Ok(contract)
}

fn run_job(graph: Arc<graph::Graph>, job: Job, train: &TrainBlock, eval: &EvalBank) -> Result<Vec<String>> {
    ensure!(train.schedule.len() >= *HORIZONS.last().unwrap());
    ensure!(train.labels.len() == train.cue_count);
    let task = Task::new(&graph, train.task_seed, train.labels.clone(), train.schedule.clone());
    let mut learner = Sim::new(&graph, train.task_seed, TAU, ETA);
    let mut output = Vec::with_capacity(HORIZONS.len());
    let mut next = 0usize;
    for trial in 0..=*HORIZONS.last().unwrap() {
        if next < HORIZONS.len() && trial == HORIZONS[next] {
            let loss = learner.loss(&task, &eval.response_draws_u64);
            let finite = learner.finite() && loss.is_finite();
            ensure!(finite, "nonfinite QTASK state at {}/{}/{}/{}", job.rung, job.substrate, job.side, job.block);
            let row = FrontierRow { rung: job.rung, cues: train.cue_count, substrate: job.substrate, side: job.side, block: job.block, horizon: trial, loss, competent: loss <= THRESHOLD, state_digest: learner.digest(), finite };
            let mut bytes = Vec::new(); serde_json::to_writer(&mut bytes, &row)?; bytes.push(b'\n');
            output.push(String::from_utf8(bytes).unwrap());
            next += 1;
        }
        if trial < *HORIZONS.last().unwrap() { learner.trial(&task, trial); }
    }
    ensure!(next == HORIZONS.len());
    Ok(output)
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    ensure!(args.len() == 3, "usage: qtask-executor STUDY_ROOT RUN_ROOT");
    let study = fs::canonicalize(&args[1])?;
    let run_root = PathBuf::from(&args[2]); fs::create_dir_all(&run_root)?;
    let started = Instant::now();
    eprintln!("qtask_preflight_start");
    let contract = verify_contract(&study)?;
    ensure!(contract["difficulty_axis"] == "cue_count");
    let train: TrainBank = serde_json::from_reader(File::open(study.join("inputs/banks/training.json"))?)?;
    let eval: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/competence.json"))?)?;
    ensure!(eval.response_draws_u64.len() == 256 && eval.response_draws_u64.iter().all(|r| r.len() == 16));
    ensure!(RUNGS.iter().all(|r| train.blocks.contains_key(*r)));
    ensure!(RUNGS.iter().all(|r| BLOCKS.iter().all(|b| train.blocks.get(*r).unwrap().contains_key(&b.to_string()))));
    let mut graphs: BTreeMap<(String, String), Arc<graph::Graph>> = BTreeMap::new();
    for &substrate in &SUBSTRATES { for &side in &SIDES { graphs.insert((substrate.to_string(), side.to_string()), Arc::new(graph::load(&study, substrate, side, GLUT_SIGN)?)); } }
    let jobs: Vec<Job> = RUNGS.iter().flat_map(|&r| SUBSTRATES.iter().flat_map(move |&s| SIDES.iter().flat_map(move |&side| BLOCKS.iter().map(move |&b| Job { rung: r, substrate: s, side, block: b })))).collect();
    ensure!(jobs.len() == 4 * 9 * 2 * 12);
    eprintln!("qtask_collection_start blocks={}", jobs.len());
    let results: Vec<Result<Vec<String>>> = jobs.par_iter().map(|job| {
        let graph = graphs.get(&(job.substrate.to_string(), job.side.to_string())).unwrap().clone();
        run_job(graph, *job, train.blocks[job.rung].get(&job.block.to_string()).unwrap(), &eval)
    }).collect();
    let out_path = run_root.join("task-frontier.jsonl");
    let mut writer = BufWriter::new(OpenOptions::new().create_new(true).write(true).open(&out_path)?);
    let mut rows = 0usize;
    for result in results { for line in result? { writer.write_all(line.as_bytes())?; rows += 1; } }
    writer.flush()?;
    ensure!(rows == 4 * 9 * 2 * 12 * 5);
    let receipt = serde_json::json!({
        "schema":"FLY-PHENO-00-v0.3-QTASK-collection-receipt-v1", "study_id":"FLY-PHENO-00-v0.3-QTASK",
        "status":"QUALIFICATION_COMPLETE", "qualification_only":true, "no_lesions":true,
        "no_recovery_comparison":true, "completed_blocks":jobs.len(), "expected_rows":rows,
        "rungs":RUNGS, "horizons":HORIZONS, "threshold":THRESHOLD,
        "contract_sha256":hash_file(&study.join("manifests/QTASK-CONTRACT.json"))?,
        "frontier_path":"task-frontier.jsonl", "wall_seconds":started.elapsed().as_secs_f64(), "nonfinite_rows":0,
    });
    let mut f = OpenOptions::new().create_new(true).write(true).open(run_root.join("collection-receipt.json"))?;
    serde_json::to_writer_pretty(&mut f, &receipt)?; f.write_all(b"\n")?;
    eprintln!("qtask_collection_complete blocks={} rows={}", jobs.len(), rows);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn frozen_ladder_contract() { assert_eq!(RUNGS, ["T1", "T2", "T3", "T4"]); assert_eq!(HORIZONS, [512,1024,2048,4096,8192]); }
}
