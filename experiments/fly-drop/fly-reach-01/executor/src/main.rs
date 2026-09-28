mod graph;
mod reach_sim;
mod rng;
mod task;

use anyhow::{Context, Result, ensure};
use rayon::prelude::*;
use reach_sim::Sim;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::{BufWriter, Read, Write},
    path::{Path, PathBuf},
    sync::Arc,
    time::Instant,
};
use task::{Pattern, Task};

const TAU: f32 = 16.0;
const ETA: f32 = 0.05;
const REFERENCE_LR: f64 = 0.05;
const ORACLE_LR: f64 = 0.5;
const ORACLE_STEPS: usize = 128;
const PRETRAIN_TRIALS: usize = 8192;
const THRESHOLD: f64 = 0.25;
const GLUT_SIGN: f32 = -1.0;
const SUBSTRATES: [&str; 9] = ["fly", "g001", "g002", "g003", "g004", "g005", "g006", "g007", "g008"];
const SIDES: [&str; 2] = ["L", "R"];
const BLOCKS: [u64; 12] = [62000, 62001, 62002, 62003, 62004, 62005, 62006, 62007, 62008, 62009, 62010, 62011];
const CHECKPOINTS: [usize; 6] = [0, 512, 1024, 2048, 4096, 8192];
const ARMS: [&str; 6] = [
    "native",
    "sign_ref_native_mag",
    "mag_ref_native_sign",
    "reference_direction_native_support",
    "reference_direction_full_support",
    "weight_oracle",
];

#[derive(Deserialize)]
struct TrainBlock { task_seed: u64, labels: Vec<bool>, schedule: Vec<Vec<usize>>, cue_count: usize }
#[derive(Deserialize)]
struct TrainBank { blocks: BTreeMap<String, TrainBlock> }
#[derive(Deserialize)]
struct EvalBank { response_draws_u64: Vec<Vec<u64>> }
#[derive(Clone, Copy)]
struct Job { substrate: &'static str, side: &'static str, block: u64 }

#[derive(Serialize)]
struct Outcome<'a> {
    substrate: &'a str, side: &'a str, block: u64, arm: &'a str, checkpoint: usize,
    loss_256: f64, loss_large: f64, oracle_large: f64, excess_large: f64,
    competent: bool, finite: bool, state_digest: String,
}
#[derive(Serialize)]
struct Diagnostics<'a> {
    substrate: &'a str, side: &'a str, block: u64, arm: &'a str,
    eligibility_cosine_mean: f64, modulation_cosine_mean: f64,
    aggregation_cosine_mean: f64, delivered_cosine_mean: f64,
    native_reference_norm_ratio_mean: f64, native_support_fraction_mean: f64,
    reference_mass_on_native_support_mean: f64, sign_agreement_mean: f64,
    magnitude_pearson_mean: f64, bound_clip_fraction: f64,
    cumulative_delivered_l2: f64, finite: bool,
}
#[derive(Serialize)]
struct Trajectory<'a> {
    substrate: &'a str, side: &'a str, block: u64, checkpoint: usize,
    eligibility_cosine: f64, modulation_cosine: f64,
    aggregation_cosine: f64, delivered_cosine: f64,
    native_support_fraction: f64, reference_mass_on_native_support: f64,
    sign_agreement: f64, magnitude_pearson: f64,
}

fn hash_file(path: &Path) -> Result<String> {
    let mut file = File::open(path).with_context(|| path.display().to_string())?;
    let mut hash = Sha256::new();
    let mut buffer = [0_u8; 65536];
    loop { let n = file.read(&mut buffer)?; if n == 0 { break; } hash.update(&buffer[..n]); }
    Ok(format!("{:x}", hash.finalize()))
}

fn sigmoid(x: f64) -> f64 { 1.0 / (1.0 + (-x.clamp(-40.0, 40.0)).exp()) }

fn verify_contract(study: &Path) -> Result<Value> {
    let path = study.join("manifests/REACH01-CONTRACT.json");
    let expected = fs::read_to_string(study.join("manifests/REACH01-CONTRACT.sha256"))?
        .split_whitespace().next().context("contract sidecar")?.to_string();
    ensure!(hash_file(&path)? == expected, "REACH01 contract checksum mismatch");
    let contract: Value = serde_json::from_reader(File::open(&path)?)?;
    ensure!(contract["status"] == "SEALED_ENGINEERING_ONLY");
    ensure!(contract["no_lesions"] == true && contract["no_biological_promotion"] == true);
    for entry in contract["input_hashes"].as_array().context("input hashes")? {
        let relative = entry["path"].as_str().context("input path")?;
        ensure!(hash_file(&study.join(relative))? == entry["sha256"].as_str().unwrap(), "input hash mismatch: {relative}");
    }
    Ok(contract)
}

fn expected_score(weights: &[f32], sim: &Sim<'_>, pattern: &Pattern) -> f64 {
    let mut score = 0.0;
    for j in 0..sim.post.len() {
        let mut drive = 0.0;
        for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] { drive += f64::from(weights[ix]); }
        let p = sigmoid(2.0 * (drive / f64::from(sim.denom[j]) - f64::from(sim.bias[j])));
        score += f64::from(sim.action_sign[j]) * (p - 0.5);
    }
    score
}

fn reference_delta_into(sim: &Sim<'_>, task: &Task, lr: f64, out: &mut [f32], grad: &mut [f64]) {
    grad.fill(0.0);
    for (pattern, &label) in task.patterns[..task.cues].iter().zip(&task.labels) {
        let score = expected_score(&sim.weights, sim, pattern);
        let y = if label { 1.0 } else { -1.0 };
        let coeff = -y * 4.0 * sigmoid(-y * 4.0 * score);
        for j in 0..sim.post.len() {
            let mut drive = 0.0;
            for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] { drive += f64::from(sim.weights[ix]); }
            let p = sigmoid(2.0 * (drive / f64::from(sim.denom[j]) - f64::from(sim.bias[j])));
            let derivative = f64::from(sim.action_sign[j]) * 2.0 * p * (1.0 - p) / f64::from(sim.denom[j]);
            for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] { grad[ix] += coeff * derivative / task.cues as f64; }
        }
    }
    for (value, &g) in out.iter_mut().zip(grad.iter()) { *value = (-lr * g) as f32; }
}

fn norm(values: &[f32]) -> f64 { values.iter().map(|x| f64::from(*x).powi(2)).sum::<f64>().sqrt() }
fn dot(a: &[f32], b: &[f32]) -> f64 { a.iter().zip(b).map(|(x, y)| f64::from(*x) * f64::from(*y)).sum() }
fn cosine(a: &[f32], b: &[f32]) -> f64 { let na = norm(a); let nb = norm(b); if na == 0.0 || nb == 0.0 { 0.0 } else { dot(a, b) / (na * nb) } }

fn rescale(source: &[f32], target: f64, output: &mut [f32]) {
    let source_norm = norm(source);
    if source_norm == 0.0 { output.fill(0.0); return; }
    let factor = (target / source_norm) as f32;
    for (out, &value) in output.iter_mut().zip(source) { *out = value * factor; }
}

fn rescale_in_place(values: &mut [f32], target: f64) {
    let value_norm = norm(values);
    if value_norm == 0.0 { values.fill(0.0); return; }
    let factor = (target / value_norm) as f32;
    for value in values { *value *= factor; }
}

fn masked_rescale(source: &[f32], mask: &[f32], target: f64, output: &mut [f32]) {
    for ((out, &value), &allowed) in output.iter_mut().zip(source).zip(mask) { *out = if allowed.abs() > 1e-12 { value } else { 0.0 }; }
    rescale_in_place(output, target);
}

fn sign_ref_native_mag(native: &[f32], reference: &[f32], target: f64, output: &mut [f32]) {
    for ((out, &n), &r) in output.iter_mut().zip(native).zip(reference) { *out = if n.abs() > 1e-12 { n.abs() * r.signum() } else { 0.0 }; }
    rescale_in_place(output, target);
}

fn mag_ref_native_sign(native: &[f32], reference: &[f32], target: f64, output: &mut [f32]) {
    for ((out, &n), &r) in output.iter_mut().zip(native).zip(reference) { *out = if n.abs() > 1e-12 { r.abs() * n.signum() } else { 0.0 }; }
    rescale_in_place(output, target);
}

fn pearson_magnitude(a: &[f32], b: &[f32]) -> f64 {
    let mut count = 0.0; let mut sx = 0.0; let mut sy = 0.0;
    for (&x, &y) in a.iter().zip(b) { if x.abs() > 1e-12 || y.abs() > 1e-12 { count += 1.0; sx += f64::from(x.abs()); sy += f64::from(y.abs()); } }
    if count < 2.0 { return 0.0; }
    let mx = sx / count; let my = sy / count; let mut xx = 0.0; let mut yy = 0.0; let mut xy = 0.0;
    for (&x, &y) in a.iter().zip(b) { if x.abs() > 1e-12 || y.abs() > 1e-12 { let dx = f64::from(x.abs()) - mx; let dy = f64::from(y.abs()) - my; xx += dx * dx; yy += dy * dy; xy += dx * dy; } }
    if xx == 0.0 || yy == 0.0 { 0.0 } else { xy / (xx * yy).sqrt() }
}

fn sign_agreement(a: &[f32], b: &[f32]) -> f64 {
    let mut same = 0_usize; let mut total = 0_usize;
    for (&x, &y) in a.iter().zip(b) { if x.abs() > 1e-12 { total += 1; if x.signum() == y.signum() { same += 1; } } }
    if total == 0 { 0.0 } else { same as f64 / total as f64 }
}

fn reference_capture(native: &[f32], reference: &[f32]) -> f64 {
    let total: f64 = reference.iter().map(|x| f64::from(x.abs())).sum();
    if total == 0.0 { return 0.0; }
    reference.iter().zip(native).filter(|(_, n)| n.abs() > 1e-12).map(|(r, _)| f64::from(r.abs())).sum::<f64>() / total
}

fn oracle<'a>(initial: &Sim<'a>, task: &Task) -> Sim<'a> {
    let mut sim = initial.clone();
    let mut delta = vec![0.0; sim.weights.len()]; let mut grad = vec![0.0; sim.weights.len()];
    for _ in 0..ORACLE_STEPS { reference_delta_into(&sim, task, ORACLE_LR, &mut delta, &mut grad); sim.apply_delta(&delta); }
    sim
}

fn make_trajectory<'a>(job: Job, checkpoint: usize, sums: &[f64; 8], count: usize) -> String {
    let div = count.max(1) as f64;
    serde_json::to_string(&Trajectory {
        substrate: job.substrate, side: job.side, block: job.block, checkpoint,
        eligibility_cosine: sums[0] / div, modulation_cosine: sums[1] / div,
        aggregation_cosine: sums[2] / div, delivered_cosine: sums[3] / div,
        native_support_fraction: sums[4] / div, reference_mass_on_native_support: sums[5] / div,
        sign_agreement: sums[6] / div, magnitude_pearson: sums[7] / div,
    }).unwrap() + "\n"
}

fn run_job(graph: Arc<graph::Graph>, job: Job, train: &TrainBlock, eval: &EvalBank, large: &EvalBank) -> Result<(Vec<String>, Vec<String>, Vec<String>)> {
    ensure!(train.cue_count == 4 && train.schedule.len() >= PRETRAIN_TRIALS);
    let task = Task::new(&graph, train.task_seed, train.labels.clone(), train.schedule.clone());
    let initial = Sim::new(&graph, train.task_seed, TAU, ETA);
    let oracle_state = oracle(&initial, &task);
    let oracle_large = oracle_state.loss(&task, &large.response_draws_u64);
    let mut outcomes = Vec::new(); let mut diagnostics = Vec::new(); let mut trajectories = Vec::new();
    for &arm in &ARMS {
        let mut sim = initial.clone();
        let mut native_delta = vec![0.0; sim.weights.len()]; let mut reference_delta = vec![0.0; sim.weights.len()];
        let mut custom_delta = vec![0.0; sim.weights.len()]; let mut grad = vec![0.0; sim.weights.len()];
        let mut eligibility_delta = vec![0.0; sim.weights.len()]; let mut modulation_delta = vec![0.0; sim.weights.len()];
        let mut before = vec![0.0; sim.weights.len()]; let mut delivered = vec![0.0; sim.weights.len()];
        if arm == "weight_oracle" {
            let l256 = sim.loss(&task, &eval.response_draws_u64); let ll = sim.loss(&task, &large.response_draws_u64);
            outcomes.push(serde_json::to_string(&Outcome { substrate: job.substrate, side: job.side, block: job.block, arm, checkpoint: 0, loss_256: l256, loss_large: ll, oracle_large, excess_large: ll - oracle_large, competent: l256 <= THRESHOLD, finite: sim.finite(), state_digest: sim.digest() })? + "\n");
            let final_state = oracle_state.clone(); let l256 = final_state.loss(&task, &eval.response_draws_u64); let ll = final_state.loss(&task, &large.response_draws_u64);
            outcomes.push(serde_json::to_string(&Outcome { substrate: job.substrate, side: job.side, block: job.block, arm, checkpoint: PRETRAIN_TRIALS, loss_256: l256, loss_large: ll, oracle_large, excess_large: ll - oracle_large, competent: l256 <= THRESHOLD, finite: final_state.finite(), state_digest: final_state.digest() })? + "\n");
            diagnostics.push(serde_json::to_string(&Diagnostics { substrate: job.substrate, side: job.side, block: job.block, arm, eligibility_cosine_mean: 0.0, modulation_cosine_mean: 0.0, aggregation_cosine_mean: 0.0, delivered_cosine_mean: 0.0, native_reference_norm_ratio_mean: 0.0, native_support_fraction_mean: 0.0, reference_mass_on_native_support_mean: 0.0, sign_agreement_mean: 0.0, magnitude_pearson_mean: 0.0, bound_clip_fraction: 0.0, cumulative_delivered_l2: 0.0, finite: final_state.finite() })? + "\n");
            continue;
        }
        let l256 = sim.loss(&task, &eval.response_draws_u64); let ll = sim.loss(&task, &large.response_draws_u64);
        outcomes.push(serde_json::to_string(&Outcome { substrate: job.substrate, side: job.side, block: job.block, arm, checkpoint: 0, loss_256: l256, loss_large: ll, oracle_large, excess_large: ll - oracle_large, competent: l256 <= THRESHOLD, finite: sim.finite(), state_digest: sim.digest() })? + "\n");
        let mut sums = [0.0_f64; 8]; let mut count = 0_usize; let mut sum_ratio = 0.0; let mut clip_count = 0_usize; let mut touched = 0_usize; let mut cumulative_sq = 0.0;
        for trial in 0..PRETRAIN_TRIALS {
            let (_correct, reward) = sim.begin_trial(&task, trial);
            for (out, &e) in eligibility_delta.iter_mut().zip(&sim.eligibility) { *out = ETA * reward * sim.scale * e; }
            sim.proposed_delta_into(reward, &mut native_delta);
            reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference_delta, &mut grad);
            modulation_delta.fill(0.0);
            for j in 0..sim.gain.len() { let row = sim.graph.kc_mb.row(j); let step = ETA * reward * sim.gain[j] * sim.scale; for ix in row { if sim.active[ix] { modulation_delta[ix] = step * sim.eligibility[ix]; } } }
            let rn = norm(&native_delta); let rr = norm(&reference_delta);
            sums[0] += cosine(&eligibility_delta, &reference_delta); sums[1] += cosine(&modulation_delta, &reference_delta); sums[2] += cosine(&native_delta, &reference_delta);
            sum_ratio += if rr == 0.0 { 0.0 } else { rn / rr };
            sums[4] += native_delta.iter().filter(|x| x.abs() > 1e-12).count() as f64 / native_delta.len() as f64;
            sums[5] += reference_capture(&native_delta, &reference_delta); sums[6] += sign_agreement(&native_delta, &reference_delta); sums[7] += pearson_magnitude(&native_delta, &reference_delta);
            let target = rr;
            match arm {
                "native" => custom_delta.copy_from_slice(&native_delta),
                "sign_ref_native_mag" => sign_ref_native_mag(&native_delta, &reference_delta, target, &mut custom_delta),
                "mag_ref_native_sign" => mag_ref_native_sign(&native_delta, &reference_delta, target, &mut custom_delta),
                "reference_direction_native_support" => masked_rescale(&reference_delta, &native_delta, target, &mut custom_delta),
                "reference_direction_full_support" => custom_delta.copy_from_slice(&reference_delta),
                _ => unreachable!(),
            }
            before.copy_from_slice(&sim.weights);
            sim.apply_delta(&custom_delta);
            for (out, (&after, &old)) in delivered.iter_mut().zip(sim.weights.iter().zip(&before)) { *out = after - old; }
            sums[3] += cosine(&delivered, &reference_delta);
            cumulative_sq += norm(&delivered).powi(2);
            for (&requested, &actual) in custom_delta.iter().zip(&delivered) { if requested.abs() > 1e-12 { touched += 1; if f64::from(requested - actual).abs() > 1e-6 { clip_count += 1; } } }
            count += 1;
            if arm == "native" && CHECKPOINTS.contains(&(trial + 1)) { trajectories.push(make_trajectory(job, trial + 1, &sums, count)); }
            if CHECKPOINTS.contains(&(trial + 1)) {
                let l256 = sim.loss(&task, &eval.response_draws_u64); let ll = sim.loss(&task, &large.response_draws_u64);
                outcomes.push(serde_json::to_string(&Outcome { substrate: job.substrate, side: job.side, block: job.block, arm, checkpoint: trial + 1, loss_256: l256, loss_large: ll, oracle_large, excess_large: ll - oracle_large, competent: l256 <= THRESHOLD, finite: sim.finite(), state_digest: sim.digest() })? + "\n");
            }
        }
        diagnostics.push(serde_json::to_string(&Diagnostics { substrate: job.substrate, side: job.side, block: job.block, arm, eligibility_cosine_mean: sums[0] / count as f64, modulation_cosine_mean: sums[1] / count as f64, aggregation_cosine_mean: sums[2] / count as f64, delivered_cosine_mean: sums[3] / count as f64, native_reference_norm_ratio_mean: sum_ratio / count as f64, native_support_fraction_mean: sums[4] / count as f64, reference_mass_on_native_support_mean: sums[5] / count as f64, sign_agreement_mean: sums[6] / count as f64, magnitude_pearson_mean: sums[7] / count as f64, bound_clip_fraction: if touched == 0 { 0.0 } else { clip_count as f64 / touched as f64 }, cumulative_delivered_l2: cumulative_sq.sqrt(), finite: sim.finite() })? + "\n");
    }
    Ok((outcomes, diagnostics, trajectories))
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    ensure!(args.len() == 3, "usage: fly-reach-01-executor STUDY_ROOT RUN_ROOT");
    let study = fs::canonicalize(&args[1])?; let run = PathBuf::from(&args[2]); fs::create_dir_all(&run)?;
    let started = Instant::now(); eprintln!("reach01_preflight_start"); let contract = verify_contract(&study)?;
    ensure!(contract["primary_task"] == "four_cue");
    let train: TrainBank = serde_json::from_reader(File::open(study.join("inputs/banks/training.json"))?)?;
    let eval: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/competence.json"))?)?;
    let large: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/evaluator-large.json"))?)?;
    ensure!(train.blocks.len() == 12 && eval.response_draws_u64.len() == 256 && large.response_draws_u64.len() == 4096);
    let mut graphs: BTreeMap<(String, String), Arc<graph::Graph>> = BTreeMap::new();
    for &substrate in &SUBSTRATES { for &side in &SIDES { graphs.insert((substrate.to_string(), side.to_string()), Arc::new(graph::load(&study, substrate, side, GLUT_SIGN)?)); } }
    let jobs: Vec<Job> = SUBSTRATES.iter().flat_map(|&substrate| SIDES.iter().flat_map(move |&side| BLOCKS.iter().map(move |&block| Job { substrate, side, block }))).collect();
    ensure!(jobs.len() == 216); eprintln!("reach01_collection_start blocks={}", jobs.len());
    let results: Vec<Result<(Vec<String>, Vec<String>, Vec<String>)>> = jobs.par_iter().map(|job| {
        let graph = graphs.get(&(job.substrate.to_string(), job.side.to_string())).unwrap().clone();
        run_job(graph, *job, train.blocks.get(&job.block.to_string()).unwrap(), &eval, &large)
    }).collect();
    let mut outcomes = BufWriter::new(OpenOptions::new().create_new(true).write(true).open(run.join("outcomes.jsonl"))?);
    let mut diagnostics = BufWriter::new(OpenOptions::new().create_new(true).write(true).open(run.join("diagnostics.jsonl"))?);
    let mut trajectories = BufWriter::new(OpenOptions::new().create_new(true).write(true).open(run.join("trajectories.jsonl"))?);
    let mut outcome_rows = 0_usize; let mut diagnostic_rows = 0_usize; let mut trajectory_rows = 0_usize;
    for result in results { let (a, b, c) = result?; for row in a { outcomes.write_all(row.as_bytes())?; outcome_rows += 1; } for row in b { diagnostics.write_all(row.as_bytes())?; diagnostic_rows += 1; } for row in c { trajectories.write_all(row.as_bytes())?; trajectory_rows += 1; } }
    outcomes.flush()?; diagnostics.flush()?; trajectories.flush()?;
    let receipt = serde_json::json!({
        "schema":"FLY-REACH-01-collection-receipt-v1", "study_id":"FLY-REACH-01", "status":"COLLECTION_COMPLETE", "engineering_only":true,
        "completed_blocks":jobs.len(), "outcome_rows":outcome_rows, "diagnostic_rows":diagnostic_rows, "trajectory_rows":trajectory_rows,
        "arms":ARMS, "checkpoints":CHECKPOINTS, "threshold":THRESHOLD, "reference_lr":REFERENCE_LR, "oracle_steps":ORACLE_STEPS,
        "wall_seconds":started.elapsed().as_secs_f64(), "contract_sha256":hash_file(&study.join("manifests/REACH01-CONTRACT.json"))?
    });
    let mut receipt_file = OpenOptions::new().create_new(true).write(true).open(run.join("collection-receipt.json"))?;
    serde_json::to_writer_pretty(&mut receipt_file, &receipt)?; receipt_file.write_all(b"\n")?;
    eprintln!("reach01_collection_complete blocks={} outcomes={} diagnostics={} trajectories={}", jobs.len(), outcome_rows, diagnostic_rows, trajectory_rows);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn frozen_contract() { assert_eq!(ARMS.len(), 6); assert_eq!(CHECKPOINTS, [0, 512, 1024, 2048, 4096, 8192]); assert_eq!(THRESHOLD, 0.25); }
    #[test] fn hybrid_support_is_preserved() { let n = [1.0_f32, 0.0, -2.0]; let r = [3.0_f32, 4.0, 5.0]; let mut out = [0.0; 3]; sign_ref_native_mag(&n, &r, norm(&r), &mut out); assert_eq!(out[1], 0.0); assert!((norm(&out) - norm(&r)).abs() < 1e-5); }
}
