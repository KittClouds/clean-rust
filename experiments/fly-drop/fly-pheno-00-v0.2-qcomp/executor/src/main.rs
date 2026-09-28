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
const BLOCKS: [u64; 12] = [22000, 22001, 22002, 22003, 22004, 22005, 22006, 22007, 22008, 22009, 22010, 22011];
const SUBSTRATES: [&str; 9] = ["fly", "g001", "g002", "g003", "g004", "g005", "g006", "g007", "g008"];
const SIDES: [&str; 2] = ["L", "R"];

#[derive(Deserialize)]
struct TrainBlock { task_seed: u64, labels: Vec<bool>, schedule: Vec<Vec<usize>> }
#[derive(Deserialize)]
struct TrainBank { blocks: BTreeMap<String, TrainBlock> }
#[derive(Deserialize)]
struct EvalBank { response_draws_u64: Vec<Vec<u64>> }

#[derive(Serialize)]
struct FrontierRow<'a> {
    substrate: &'a str, side: &'a str, block: u64, horizon: usize,
    loss: f64, competent: bool, state_digest: String, finite: bool,
}

fn hash_file(path: &Path) -> Result<String> {
    let mut file = File::open(path).with_context(|| path.display().to_string())?;
    let mut hash = Sha256::new();
    let mut buf = [0u8; 65_536];
    loop { let n = file.read(&mut buf)?; if n == 0 { break; } hash.update(&buf[..n]); }
    Ok(format!("{:x}", hash.finalize()))
}

fn verify_contract(study: &Path) -> Result<Value> {
    let contract_path = study.join("manifests/QCOMP-CONTRACT.json");
    let sidecar = fs::read_to_string(study.join("manifests/QCOMP-CONTRACT.sha256"))?;
    let expected = sidecar.split_whitespace().next().context("contract sidecar")?;
    ensure!(hash_file(&contract_path)? == expected, "QCOMP contract checksum mismatch");
    let contract: Value = serde_json::from_reader(File::open(&contract_path)?)?;
    ensure!(contract["status"] == "SEALED_QUALIFICATION_ONLY");
    ensure!(contract["no_lesions"] == true && contract["no_recovery_comparison"] == true);
    for entry in contract["input_hashes"].as_array().context("input hashes")? {
        let rel = entry["path"].as_str().context("input path")?;
        let path = study.join(rel);
        ensure!(hash_file(&path)? == entry["sha256"].as_str().unwrap(), "input hash mismatch: {rel}");
    }
    let exe_hash = contract["executable_sha256"].as_str().context("executable hash")?;
    ensure!(exe_hash.len() == 64, "missing executable hash");
    Ok(contract)
}

fn run_block(study: &Path, graph: Arc<graph::Graph>, side: &str, substrate: &str, block: u64, train: &TrainBlock, eval: &EvalBank) -> Result<Vec<String>> {
    ensure!(train.schedule.len() >= *HORIZONS.last().unwrap());
    let task = Task::new(&graph, train.task_seed, train.labels.clone(), train.schedule.clone());
    let mut learner = Sim::new(&graph, train.task_seed, TAU, ETA);
    let mut out = Vec::with_capacity(HORIZONS.len());
    let mut next = 0usize;
    for trial in 0..=*HORIZONS.last().unwrap() {
        if next < HORIZONS.len() && trial == HORIZONS[next] {
            let loss = learner.loss(&task, &eval.response_draws_u64);
            let finite = learner.finite() && loss.is_finite();
            ensure!(finite, "non-finite qualification state at {substrate}/{side}/{block}/{trial}");
            let row = FrontierRow { substrate, side, block, horizon: trial, loss, competent: loss <= THRESHOLD, state_digest: learner.digest(), finite };
            let mut bytes = Vec::new(); serde_json::to_writer(&mut bytes, &row)?; bytes.push(b'\n');
            out.push(String::from_utf8(bytes).unwrap());
            next += 1;
        }
        if trial < *HORIZONS.last().unwrap() { learner.trial(&task, trial); }
    }
    ensure!(next == HORIZONS.len());
    Ok(out)
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    ensure!(args.len() == 3, "usage: qcomp-executor STUDY_ROOT RUN_ROOT");
    let study = fs::canonicalize(&args[1])?;
    let run_root = PathBuf::from(&args[2]);
    fs::create_dir_all(&run_root)?;
    let started = Instant::now();
    eprintln!("qcomp_preflight_start");
    let contract = verify_contract(&study)?;
    ensure!(contract["horizons"].as_array().unwrap().len() == HORIZONS.len());
    let train: TrainBank = serde_json::from_reader(File::open(study.join("inputs/banks/training.json"))?)?;
    let eval: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/competence.json"))?)?;
    ensure!(eval.response_draws_u64.len() == 256 && eval.response_draws_u64.iter().all(|r| r.len() == 16));
    ensure!(BLOCKS.iter().all(|b| train.blocks.contains_key(&b.to_string())));
    let jobs: Vec<(&str, &str, u64)> = SUBSTRATES.iter().flat_map(|&s| SIDES.iter().map(move |&side| (s, side, 0))).collect();
    let mut writer = BufWriter::new(OpenOptions::new().create_new(true).write(true).open(run_root.join("competence-frontier.jsonl"))?);
    let mut completed = 0usize;
    eprintln!("qcomp_collection_start blocks={}", SUBSTRATES.len() * SIDES.len() * BLOCKS.len());
    for &(substrate, side, _) in &jobs {
        let graph = Arc::new(graph::load(&study, substrate, side, GLUT_SIGN)?);
        for &block in &BLOCKS {
            let rows = run_block(&study, graph.clone(), side, substrate, block, train.blocks.get(&block.to_string()).context("training block")?, &eval)?;
            for row in rows { writer.write_all(row.as_bytes())?; }
            completed += 1;
            if completed % 8 == 0 { eprintln!("qcomp_progress blocks={completed}/216"); }
        }
    }
    writer.flush()?;
    let receipt = serde_json::json!({
        "schema":"FLY-PHENO-00-v0.2-QCOMP-collection-receipt-v1",
        "study_id":"FLY-PHENO-00-v0.2-QCOMP", "status":"QUALIFICATION_COMPLETE",
        "qualification_only":true, "no_lesions":true, "no_recovery_comparison":true,
        "completed_blocks":completed, "expected_blocks":216, "expected_rows":1080,
        "horizons":HORIZONS, "threshold":THRESHOLD, "frontier_path":"competence-frontier.jsonl",
        "contract_sha256":hash_file(&study.join("manifests/QCOMP-CONTRACT.json"))?,
        "wall_seconds":started.elapsed().as_secs_f64(), "nonfinite_rows":0,
    });
    let mut receipt_file = OpenOptions::new().create_new(true).write(true).open(run_root.join("collection-receipt.json"))?;
    serde_json::to_writer_pretty(&mut receipt_file, &receipt)?; receipt_file.write_all(b"\n")?;
    eprintln!("qcomp_collection_complete blocks={completed}");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn frontier_is_fixed_and_qualification_only() {
        assert_eq!(HORIZONS, [512, 1024, 2048, 4096, 8192]);
        assert!(THRESHOLD > 0.0 && THRESHOLD < 0.5);
    }
}
