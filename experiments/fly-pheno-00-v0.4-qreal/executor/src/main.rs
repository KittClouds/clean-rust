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
use task::{Pattern, Task};

const TAU: f32 = 16.0;
const ETA: f32 = 0.05;
const GLUT_SIGN: f32 = -1.0;
const THRESHOLD: f64 = 0.25;
const PRETRAIN_TRIALS: usize = 8192;
const ORACLE_STEPS: usize = 128;
const ORACLE_LR: f64 = 0.5;
const RUNS: [&str; 2] = ["four_cue", "two_cue_sanity"];
const SUBSTRATES: [&str; 9] = ["fly", "g001", "g002", "g003", "g004", "g005", "g006", "g007", "g008"];
const SIDES: [&str; 2] = ["L", "R"];
const BLOCKS: [u64; 12] = [42000, 42001, 42002, 42003, 42004, 42005, 42006, 42007, 42008, 42009, 42010, 42011];

#[derive(Deserialize)]
struct TrainBlock { task_seed: u64, labels: Vec<bool>, schedule: Vec<Vec<usize>>, cue_count: usize }
#[derive(Deserialize)]
struct TrainBank { blocks: BTreeMap<String, BTreeMap<String, TrainBlock>> }
#[derive(Deserialize)]
struct EvalBank { response_draws_u64: Vec<Vec<u64>> }
#[derive(Clone, Copy)] struct Job { task: &'static str, substrate: &'static str, side: &'static str, block: u64 }

#[derive(Serialize)]
struct DiagnosticRow<'a> {
    task: &'a str, cues: usize, substrate: &'a str, side: &'a str, block: u64,
    representation_error: f64, representation_logloss: f64,
    weight_oracle_expected_error: f64, weight_oracle_logloss: f64,
    weight_oracle_error_256: f64, weight_oracle_error_large: f64,
    native_error_256: f64, native_error_large: f64, native_competent: bool,
    weight_oracle_finite: bool, native_finite: bool, native_state_digest: String,
}

fn hash_file(path: &Path) -> Result<String> {
    let mut file = File::open(path).with_context(|| path.display().to_string())?;
    let mut hash = Sha256::new(); let mut buf = [0u8; 65_536];
    loop { let n = file.read(&mut buf)?; if n == 0 { break; } hash.update(&buf[..n]); }
    Ok(format!("{:x}", hash.finalize()))
}

fn sigmoid(x: f64) -> f64 { 1.0 / (1.0 + (-x.clamp(-40.0, 40.0)).exp()) }

fn verify_contract(study: &Path) -> Result<Value> {
    let path = study.join("manifests/QREAL-CONTRACT.json");
    let expected = fs::read_to_string(study.join("manifests/QREAL-CONTRACT.sha256"))?.split_whitespace().next().context("contract sidecar")?.to_string();
    ensure!(hash_file(&path)? == expected, "QREAL contract checksum mismatch");
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

fn feature_matrix(graph: &graph::Graph, sim: &Sim<'_>, task: &Task) -> Vec<Vec<f64>> {
    let mut matrix = Vec::with_capacity(task.cues);
    for cue in 0..task.cues {
        let pattern = &task.patterns[cue];
        let mut row = vec![0.0; graph.kc_mb.n_post];
        for j in 0..graph.kc_mb.n_post {
            let mut count = 0.0;
            for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] { count += 1.0; let _ = ix; }
            row[j] = count / f64::from(sim.denom[j]);
        }
        matrix.push(row);
    }
    matrix
}

fn binary_metrics(scores: &[f64], labels: &[bool]) -> (f64, f64) {
    let mut errors = 0.0; let mut loss = 0.0;
    for (&score, &label) in scores.iter().zip(labels) {
        let y = if label { 1.0 } else { 0.0 }; let p = sigmoid(score);
        if (score >= 0.0) != label { errors += 1.0; }
        loss += -(y * p.max(1e-12).ln() + (1.0 - y) * (1.0 - p).max(1e-12).ln());
    }
    (errors / scores.len() as f64, loss / scores.len() as f64)
}

fn representation_oracle(features: &[Vec<f64>], labels: &[bool]) -> (f64, f64) {
    let n = features[0].len(); let mut w = vec![0.0_f64; n + 1];
    for _ in 0..2048 {
        let mut grad = vec![0.0; n + 1];
        for (x, &label) in features.iter().zip(labels) {
            let score = w[0] + x.iter().enumerate().map(|(j, v)| w[j + 1] * v).sum::<f64>();
            let err = sigmoid(score) - f64::from(label);
            grad[0] += err; for (j, &v) in x.iter().enumerate() { grad[j + 1] += err * v; }
        }
        for j in 0..=n { w[j] -= 0.5 * grad[j] / features.len() as f64; }
    }
    let scores: Vec<f64> = features.iter().map(|x| w[0] + x.iter().enumerate().map(|(j, v)| w[j + 1] * v).sum::<f64>()).collect();
    binary_metrics(&scores, labels)
}

fn expected_score(weights: &[f32], sim: &Sim<'_>, pattern: &Pattern) -> f64 {
    let mut score = 0.0;
    for j in 0..sim.post.len() {
        let mut drive = 0.0_f64;
        for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] { drive += f64::from(weights[ix]); }
        let p = sigmoid(2.0 * (drive / f64::from(sim.denom[j]) - f64::from(sim.bias[j])));
        score += f64::from(sim.action_sign[j]) * (p - 0.5);
    }
    score
}

fn weight_oracle(sim: &Sim<'_>, task: &Task) -> (Vec<f32>, f64, f64, bool) {
    let mut weights = sim.weights.clone();
    for _ in 0..ORACLE_STEPS {
        let mut grad = vec![0.0_f64; weights.len()];
        for (pattern, &label) in task.patterns[..task.cues].iter().zip(&task.labels) {
            let score = expected_score(&weights, sim, pattern);
            let y = if label { 1.0 } else { -1.0 };
            let coeff = -y * 4.0 * sigmoid(-y * 4.0 * score);
            for j in 0..sim.post.len() {
                let mut drive = 0.0_f64;
                for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] { drive += f64::from(weights[ix]); }
                let p = sigmoid(2.0 * (drive / f64::from(sim.denom[j]) - f64::from(sim.bias[j])));
                let derivative = f64::from(sim.action_sign[j]) * 2.0 * p * (1.0 - p) / f64::from(sim.denom[j]);
                for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] { grad[ix] += coeff * derivative; }
            }
        }
        for (w, g) in weights.iter_mut().zip(grad) { *w = (*w - (ORACLE_LR * g / task.cues as f64) as f32).clamp(0.0, 2.0); }
    }
    let scores: Vec<f64> = task.patterns[..task.cues].iter().map(|p| expected_score(&weights, sim, p)).collect();
    let metrics = binary_metrics(&scores, &task.labels);
    let finite = weights.iter().all(|x| x.is_finite());
    (weights, metrics.0, metrics.1, finite)
}

fn run_job(graph: Arc<graph::Graph>, job: Job, train: &TrainBlock, eval: &EvalBank, large: &EvalBank) -> Result<String> {
    ensure!(train.schedule.len() >= PRETRAIN_TRIALS);
    let task = Task::new(&graph, train.task_seed, train.labels.clone(), train.schedule.clone());
    let initial = Sim::new(&graph, train.task_seed, TAU, ETA);
    let features = feature_matrix(&graph, &initial, &task);
    let (rep_error, rep_logloss) = representation_oracle(&features, &task.labels);
    let (oracle_weights, oracle_error, oracle_logloss, oracle_finite) = weight_oracle(&initial, &task);
    let mut oracle_sim = initial.clone(); oracle_sim.weights = oracle_weights;
    let oracle_error_256 = oracle_sim.loss(&task, &eval.response_draws_u64);
    let oracle_error_large = oracle_sim.loss(&task, &large.response_draws_u64);
    let mut native = initial;
    for trial in 0..PRETRAIN_TRIALS { native.trial(&task, trial); }
    let native_error_256 = native.loss(&task, &eval.response_draws_u64);
    let native_error_large = native.loss(&task, &large.response_draws_u64);
    let row = DiagnosticRow { task: job.task, cues: train.cue_count, substrate: job.substrate, side: job.side, block: job.block, representation_error: rep_error, representation_logloss: rep_logloss, weight_oracle_expected_error: oracle_error, weight_oracle_logloss: oracle_logloss, weight_oracle_error_256: oracle_error_256, weight_oracle_error_large: oracle_error_large, native_error_256, native_error_large, native_competent: native_error_256 <= THRESHOLD, weight_oracle_finite: oracle_finite, native_finite: native.finite(), native_state_digest: native.digest() };
    let mut bytes = Vec::new(); serde_json::to_writer(&mut bytes, &row)?; bytes.push(b'\n'); Ok(String::from_utf8(bytes).unwrap())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect(); ensure!(args.len() == 3, "usage: qreal-executor STUDY_ROOT RUN_ROOT");
    let study = fs::canonicalize(&args[1])?; let run_root = PathBuf::from(&args[2]); fs::create_dir_all(&run_root)?; let started = Instant::now();
    eprintln!("qreal_preflight_start"); let contract = verify_contract(&study)?; ensure!(contract["primary_task"] == "four_cue");
    let train: TrainBank = serde_json::from_reader(File::open(study.join("inputs/banks/training.json"))?)?;
    let eval: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/competence.json"))?)?;
    let large: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/evaluator-large.json"))?)?;
    ensure!(eval.response_draws_u64.len() == 256 && large.response_draws_u64.len() == 4096);
    let mut graphs: BTreeMap<(String, String), Arc<graph::Graph>> = BTreeMap::new();
    for &s in &SUBSTRATES { for &side in &SIDES { graphs.insert((s.to_string(), side.to_string()), Arc::new(graph::load(&study, s, side, GLUT_SIGN)?)); } }
    let jobs: Vec<Job> = RUNS.iter().flat_map(|&task| SUBSTRATES.iter().flat_map(move |&s| SIDES.iter().flat_map(move |&side| BLOCKS.iter().map(move |&b| Job { task, substrate:s, side, block:b })))).collect();
    ensure!(jobs.len() == 2 * 9 * 2 * 12); eprintln!("qreal_collection_start blocks={}", jobs.len());
    let results: Vec<Result<String>> = jobs.par_iter().map(|job| { let graph = graphs.get(&(job.substrate.to_string(), job.side.to_string())).unwrap().clone(); run_job(graph, *job, train.blocks.get(job.task).unwrap().get(&job.block.to_string()).unwrap(), &eval, &large) }).collect();
    let mut writer = BufWriter::new(OpenOptions::new().create_new(true).write(true).open(run_root.join("diagnostics.jsonl"))?); let mut rows = 0;
    for result in results { writer.write_all(result?.as_bytes())?; rows += 1; } writer.flush()?; ensure!(rows == jobs.len());
    let receipt = serde_json::json!({"schema":"FLY-PHENO-00-v0.4-QREAL-collection-receipt-v1","study_id":"FLY-PHENO-00-v0.4-QREAL","status":"QUALIFICATION_COMPLETE","qualification_only":true,"no_lesions":true,"no_recovery_comparison":true,"completed_blocks":rows,"expected_rows":rows,"oracle_steps":ORACLE_STEPS,"primary_task":"four_cue","sanity_task":"two_cue_sanity","threshold":THRESHOLD,"contract_sha256":hash_file(&study.join("manifests/QREAL-CONTRACT.json"))?,"wall_seconds":started.elapsed().as_secs_f64()});
    let mut f = OpenOptions::new().create_new(true).write(true).open(run_root.join("collection-receipt.json"))?; serde_json::to_writer_pretty(&mut f, &receipt)?; f.write_all(b"\n")?; eprintln!("qreal_collection_complete rows={rows}"); Ok(())
}

#[cfg(test)]
mod tests { use super::*; #[test] fn qreal_contract_constants() { assert_eq!(RUNS, ["four_cue", "two_cue_sanity"]); assert_eq!(PRETRAIN_TRIALS, 8192); assert_eq!(THRESHOLD, 0.25); } }
