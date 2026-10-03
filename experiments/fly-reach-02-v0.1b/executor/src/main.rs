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
use std::{collections::BTreeMap, fs::{self, File, OpenOptions}, io::{BufWriter, Read, Write}, path::{Path, PathBuf}, sync::Arc, time::Instant};
use task::{Pattern, Task};

const TAU: f32 = 16.0;
const ETA: f32 = 0.05;
const REFERENCE_LR: f64 = 0.05;
const ORACLE_LR: f64 = 0.5;
const ORACLE_STEPS: usize = 128;
const PRETRAIN_TRIALS: usize = 8192;
const THRESHOLD: f64 = 0.25;
const GLUT_SIGN: f32 = -1.0;
const EPS: f32 = 1e-12;
const MIN_OBSERVATIONS: usize = 128;
const MAX_INVERSION_AGREEMENT: f64 = 0.20;
const SUBSTRATES: [&str; 9] = ["fly", "g001", "g002", "g003", "g004", "g005", "g006", "g007", "g008"];
const SIDES: [&str; 2] = ["L", "R"];
const Q_BLOCKS: [u64; 4] = [92000, 92001, 92002, 92003];
const BLOCKS: [u64; 12] = [102000, 102001, 102002, 102003, 102004, 102005, 102006, 102007, 102008, 102009, 102010, 102011];
const CHECKPOINTS: [usize; 6] = [0, 512, 1024, 2048, 4096, 8192];
const ARMS: [&str; 5] = ["native", "sign_ref_native_mag", "stable_inversion_flip", "reference_direction_native_support", "weight_oracle"];

#[derive(Deserialize)] struct TrainBlock { task_seed: u64, labels: Vec<bool>, schedule: Vec<Vec<usize>>, cue_count: usize }
#[derive(Deserialize)] struct TrainBank { blocks: BTreeMap<String, TrainBlock> }
#[derive(Deserialize)] struct EvalBank { response_draws_u64: Vec<Vec<u64>> }
#[derive(Clone, Copy)] struct Job { substrate: &'static str, side: &'static str, block: u64 }

#[derive(Serialize)] struct QualificationRow<'a> { substrate: &'a str, side: &'a str, block: u64, observed: usize, aggregate_sign_agreement: f64, local_cancellation: f64 }
#[derive(Serialize)] struct Outcome<'a> { substrate: &'a str, side: &'a str, block: u64, arm: &'a str, checkpoint: usize, loss_256: f64, loss_large: f64, oracle_large: f64, excess_large: f64, competent: bool, finite: bool, state_digest: String }
#[derive(Serialize)] struct Diagnostics<'a> {
    substrate: &'a str, side: &'a str, block: u64, arm: &'a str,
    eligibility_cosine_mean: f64, modulation_cosine_mean: f64, aggregation_cosine_mean: f64, delivered_cosine_mean: f64,
    local_cancellation_mean: f64, local_sign_agreement_mean: f64, aggregate_sign_agreement_mean: f64,
    native_support_fraction_mean: f64, reference_mass_on_native_support_mean: f64,
    stable_correct_fraction: f64, stable_inverted_fraction: f64, unstable_fraction: f64,
    bound_clip_fraction: f64, cumulative_delivered_l2: f64, finite: bool,
}
#[derive(Serialize)] struct Trajectory<'a> {
    substrate: &'a str, side: &'a str, block: u64, checkpoint: usize,
    eligibility_cosine: f64, modulation_cosine: f64, aggregation_cosine: f64, delivered_cosine: f64,
    local_cancellation: f64, local_sign_agreement: f64, aggregate_sign_agreement: f64,
    stable_correct_fraction: f64, stable_inverted_fraction: f64, unstable_fraction: f64,
}

fn hash_file(path: &Path) -> Result<String> { let mut f = File::open(path).with_context(|| path.display().to_string())?; let mut h = Sha256::new(); let mut b = [0_u8; 65536]; loop { let n = f.read(&mut b)?; if n == 0 { break; } h.update(&b[..n]); } Ok(format!("{:x}", h.finalize())) }
fn sigmoid(x: f64) -> f64 { 1.0 / (1.0 + (-x.clamp(-40.0, 40.0)).exp()) }

fn verify_contract(study: &Path) -> Result<Value> {
    let path = study.join("manifests/REACH02-CONTRACT.json");
    let expected = fs::read_to_string(study.join("manifests/REACH02-CONTRACT.sha256"))?.split_whitespace().next().context("contract sidecar")?.to_string();
    ensure!(hash_file(&path)? == expected, "REACH02 contract checksum mismatch");
    let contract: Value = serde_json::from_reader(File::open(path)?)?;
    ensure!(contract["status"] == "SEALED_ENGINEERING_ONLY"); ensure!(contract["no_lesions"] == true && contract["no_biological_promotion"] == true);
    for entry in contract["input_hashes"].as_array().context("input hashes")? { let rel = entry["path"].as_str().context("input path")?; ensure!(hash_file(&study.join(rel))? == entry["sha256"].as_str().unwrap(), "input hash mismatch: {rel}"); }
    Ok(contract)
}

fn expected_score(weights: &[f32], sim: &Sim<'_>, pattern: &Pattern) -> f64 {
    let mut score = 0.0;
    for j in 0..sim.post.len() { let mut drive = 0.0; for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] { drive += f64::from(weights[ix]); } let p = sigmoid(2.0 * (drive / f64::from(sim.denom[j]) - f64::from(sim.bias[j]))); score += f64::from(sim.action_sign[j]) * (p - 0.5); }
    score
}

fn reference_delta_into(sim: &Sim<'_>, task: &Task, lr: f64, out: &mut [f32], grad: &mut [f64]) {
    grad.fill(0.0);
    for (pattern, &label) in task.patterns[..task.cues].iter().zip(&task.labels) {
        let score = expected_score(&sim.weights, sim, pattern); let y = if label { 1.0 } else { -1.0 }; let coeff = -y * 4.0 * sigmoid(-y * 4.0 * score);
        for j in 0..sim.post.len() { let mut drive = 0.0; for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] { drive += f64::from(sim.weights[ix]); } let p = sigmoid(2.0 * (drive / f64::from(sim.denom[j]) - f64::from(sim.bias[j]))); let d = f64::from(sim.action_sign[j]) * 2.0 * p * (1.0 - p) / f64::from(sim.denom[j]); for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] { grad[ix] += coeff * d / task.cues as f64; } }
    }
    for (value, &g) in out.iter_mut().zip(grad.iter()) { *value = (-lr * g) as f32; }
}

fn norm(v: &[f32]) -> f64 { v.iter().map(|x| f64::from(*x).powi(2)).sum::<f64>().sqrt() }
fn dot(a: &[f32], b: &[f32]) -> f64 { a.iter().zip(b).map(|(x, y)| f64::from(*x) * f64::from(*y)).sum() }
fn cosine(a: &[f32], b: &[f32]) -> f64 { let na = norm(a); let nb = norm(b); if na == 0.0 || nb == 0.0 { 0.0 } else { dot(a, b) / (na * nb) } }
fn rescale_in_place(values: &mut [f32], target: f64) { let n = norm(values); if n == 0.0 { values.fill(0.0); } else { let k = (target / n) as f32; for value in values { *value *= k; } } }
fn masked_rescale(source: &[f32], mask: &[f32], target: f64, out: &mut [f32]) { for ((o, &x), &m) in out.iter_mut().zip(source).zip(mask) { *o = if m.abs() > EPS { x } else { 0.0 }; } rescale_in_place(out, target); }
fn local_cancellation(local_abs: &[f32], local_signed: &[f32]) -> f64 { let mut total = 0.0; let mut n = 0_usize; for (&a, &s) in local_abs.iter().zip(local_signed) { if a > EPS { total += 1.0 - f64::from(s.abs()) / f64::from(a + EPS); n += 1; } } if n == 0 { 0.0 } else { total / n as f64 } }
fn sign_agreement(a: &[f32], b: &[f32]) -> f64 { let mut same = 0_usize; let mut total = 0_usize; for (&x, &y) in a.iter().zip(b) { if x.abs() > EPS && y.abs() > EPS { total += 1; if x.signum() == y.signum() { same += 1; } } } if total == 0 { 0.0 } else { same as f64 / total as f64 } }
fn reference_capture(native: &[f32], reference: &[f32]) -> f64 { let total: f64 = reference.iter().map(|x| f64::from(x.abs())).sum(); if total == 0.0 { 0.0 } else { reference.iter().zip(native).filter(|(_, n)| n.abs() > EPS).map(|(r, _)| f64::from(r.abs())).sum::<f64>() / total } }

fn oracle<'a>(initial: &Sim<'a>, task: &Task) -> Sim<'a> { let mut sim = initial.clone(); let mut delta = vec![0.0; sim.weights.len()]; let mut grad = vec![0.0; sim.weights.len()]; for _ in 0..ORACLE_STEPS { reference_delta_into(&sim, task, ORACLE_LR, &mut delta, &mut grad); sim.apply_delta(&delta); } sim }

struct QResult { substrate: &'static str, side: &'static str, block: u64, seen: Vec<usize>, matches: Vec<usize>, cancellation: f64, observations: usize }

fn qualification_cell(graph: Arc<graph::Graph>, job: Job, train: &TrainBlock) -> Result<QResult> {
    let task = Task::new(&graph, train.task_seed, train.labels.clone(), train.schedule.clone()); let mut sim = Sim::new(&graph, train.task_seed, TAU, ETA);
    let mut local_abs = vec![0.0; sim.weights.len()]; let mut local_signed = vec![0.0; sim.weights.len()]; let mut reference = vec![0.0; sim.weights.len()]; let mut grad = vec![0.0; sim.weights.len()];
    let mut seen = vec![0_usize; sim.weights.len()]; let mut matches = vec![0_usize; sim.weights.len()]; let mut cancellation = 0.0; let mut observations = 0_usize;
    for trial in 0..PRETRAIN_TRIALS { let (_correct, reward) = sim.begin_trial_with_local(&task, trial, &mut local_abs, &mut local_signed); sim.proposed_delta_into(reward, &mut reference); reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference, &mut grad); cancellation += local_cancellation(&local_abs, &local_signed); for ((&e, &r), seen_i) in sim.eligibility.iter().zip(&reference).zip(seen.iter_mut()) { if e.abs() > EPS && r.abs() > EPS { *seen_i += 1; observations += 1; } } for ((&e, &r), matches_i) in sim.eligibility.iter().zip(&reference).zip(matches.iter_mut()) { if e.abs() > EPS && r.abs() > EPS && e.signum() == r.signum() { *matches_i += 1; } } }
    Ok(QResult { substrate: job.substrate, side: job.side, block: job.block, seen, matches, cancellation: cancellation / PRETRAIN_TRIALS as f64, observations })
}

struct MaskInfo { mask: Arc<Vec<bool>>, stable_fraction: f64, qualification_rows: Vec<String> }

fn build_masks(graphs: &BTreeMap<(String, String), Arc<graph::Graph>>, qtrain: &TrainBank) -> Result<BTreeMap<(String, String), MaskInfo>> {
    let jobs: Vec<Job> = SUBSTRATES.iter().flat_map(|&s| SIDES.iter().flat_map(move |&side| Q_BLOCKS.iter().map(move |&block| Job { substrate: s, side, block }))).collect();
    let results: Vec<Result<QResult>> = jobs.par_iter().map(|job| qualification_cell(graphs.get(&(job.substrate.to_string(), job.side.to_string())).unwrap().clone(), *job, qtrain.blocks.get(&job.block.to_string()).unwrap())).collect();
    let mut grouped: BTreeMap<(String, String), Vec<QResult>> = BTreeMap::new(); for result in results { let value = result?; grouped.entry((value.substrate.to_string(), value.side.to_string())).or_default().push(value); }
    let mut output = BTreeMap::new();
    for ((substrate, side), rows) in grouped { let n = rows[0].seen.len(); let mut seen = vec![0_usize; n]; let mut matches = vec![0_usize; n]; let mut row_text = Vec::new(); let mut cancellation = 0.0; let mut observations = 0_usize; for row in rows { for i in 0..n { seen[i] += row.seen[i]; matches[i] += row.matches[i]; } cancellation += row.cancellation; observations += row.observations; row_text.push(serde_json::to_string(&QualificationRow { substrate: &substrate, side: &side, block: row.block, observed: row.observations, aggregate_sign_agreement: if row.observations == 0 { 0.0 } else { row.matches.iter().sum::<usize>() as f64 / row.observations as f64 }, local_cancellation: row.cancellation })? + "\n"); }
        let mask: Vec<bool> = seen.iter().zip(&matches).map(|(&count, &matched)| count >= MIN_OBSERVATIONS && (matched as f64 / count as f64) <= MAX_INVERSION_AGREEMENT).collect(); let stable_fraction = mask.iter().filter(|&&x| x).count() as f64 / mask.len() as f64;
        let _ = (cancellation, observations); output.insert((substrate, side), MaskInfo { mask: Arc::new(mask), stable_fraction, qualification_rows: row_text }); }
    Ok(output)
}

fn stable_fractions(seen: &[usize], matches: &[usize]) -> (f64, f64, f64) { let mut correct = 0_usize; let mut inverted = 0_usize; let mut unstable = 0_usize; for (&n, &m) in seen.iter().zip(matches) { if n < MIN_OBSERVATIONS { unstable += 1; } else { let p = m as f64 / n as f64; if p >= 0.80 { correct += 1; } else if p <= MAX_INVERSION_AGREEMENT { inverted += 1; } else { unstable += 1; } } } let total = (correct + inverted + unstable).max(1) as f64; (correct as f64 / total, inverted as f64 / total, unstable as f64 / total) }

fn run_job(graph: Arc<graph::Graph>, mask: Arc<Vec<bool>>, job: Job, train: &TrainBlock, eval: &EvalBank, large: &EvalBank) -> Result<(Vec<String>, Vec<String>, Vec<String>)> {
    ensure!(train.cue_count == 4 && train.schedule.len() >= PRETRAIN_TRIALS); let task = Task::new(&graph, train.task_seed, train.labels.clone(), train.schedule.clone()); let initial = Sim::new(&graph, train.task_seed, TAU, ETA); let oracle_state = oracle(&initial, &task); let oracle_large = oracle_state.loss(&task, &large.response_draws_u64);
    let mut outcomes = Vec::new(); let mut diagnostics = Vec::new(); let mut trajectories = Vec::new();
    for &arm in &ARMS {
        let mut sim = initial.clone(); let mut native_delta = vec![0.0; sim.weights.len()]; let mut reference = vec![0.0; sim.weights.len()]; let mut custom = vec![0.0; sim.weights.len()]; let mut grad = vec![0.0; sim.weights.len()]; let mut local_abs = vec![0.0; sim.weights.len()]; let mut local_signed = vec![0.0; sim.weights.len()]; let mut modulation = vec![0.0; sim.weights.len()]; let mut before = vec![0.0; sim.weights.len()]; let mut delivered = vec![0.0; sim.weights.len()]; let mut seen = vec![0_usize; sim.weights.len()]; let mut matches = vec![0_usize; sim.weights.len()];
        if arm == "weight_oracle" { let l = sim.loss(&task, &eval.response_draws_u64); let ll = sim.loss(&task, &large.response_draws_u64); outcomes.push(serde_json::to_string(&Outcome { substrate: job.substrate, side: job.side, block: job.block, arm, checkpoint: 0, loss_256: l, loss_large: ll, oracle_large, excess_large: ll - oracle_large, competent: l <= THRESHOLD, finite: sim.finite(), state_digest: sim.digest() })? + "\n"); let l = oracle_state.loss(&task, &eval.response_draws_u64); let ll = oracle_state.loss(&task, &large.response_draws_u64); outcomes.push(serde_json::to_string(&Outcome { substrate: job.substrate, side: job.side, block: job.block, arm, checkpoint: 8192, loss_256: l, loss_large: ll, oracle_large, excess_large: ll - oracle_large, competent: l <= THRESHOLD, finite: oracle_state.finite(), state_digest: oracle_state.digest() })? + "\n"); diagnostics.push(serde_json::to_string(&Diagnostics { substrate: job.substrate, side: job.side, block: job.block, arm, eligibility_cosine_mean: 0.0, modulation_cosine_mean: 0.0, aggregation_cosine_mean: 0.0, delivered_cosine_mean: 0.0, local_cancellation_mean: 0.0, local_sign_agreement_mean: 0.0, aggregate_sign_agreement_mean: 0.0, native_support_fraction_mean: 0.0, reference_mass_on_native_support_mean: 0.0, stable_correct_fraction: 0.0, stable_inverted_fraction: 0.0, unstable_fraction: 0.0, bound_clip_fraction: 0.0, cumulative_delivered_l2: 0.0, finite: oracle_state.finite() })? + "\n"); continue; }
        let l = sim.loss(&task, &eval.response_draws_u64); let ll = sim.loss(&task, &large.response_draws_u64); outcomes.push(serde_json::to_string(&Outcome { substrate: job.substrate, side: job.side, block: job.block, arm, checkpoint: 0, loss_256: l, loss_large: ll, oracle_large, excess_large: ll - oracle_large, competent: l <= THRESHOLD, finite: sim.finite(), state_digest: sim.digest() })? + "\n");
        let mut sums = [0.0_f64; 9]; let mut count = 0_usize; let mut clips = 0_usize; let mut touched = 0_usize; let mut cumulative = 0.0;
        for trial in 0..PRETRAIN_TRIALS {
            let (_correct, reward) = sim.begin_trial_with_local(&task, trial, &mut local_abs, &mut local_signed); reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference, &mut grad); sim.proposed_delta_into(reward, &mut native_delta);
            for j in 0..sim.gain.len() { let row = sim.graph.kc_mb.row(j); let step = ETA * reward * sim.gain[j] * sim.scale; for ix in row { if sim.active[ix] { modulation[ix] = step * sim.eligibility[ix]; } } }
            let local_sign = sign_agreement(&local_signed, &reference); let aggregate_sign = sign_agreement(&sim.eligibility, &reference); sums[0] += cosine(&sim.eligibility, &reference); sums[1] += cosine(&modulation, &reference); sums[2] += cosine(&native_delta, &reference); sums[4] += local_cancellation(&local_abs, &local_signed); sums[5] += local_sign; sums[6] += aggregate_sign; sums[7] += native_delta.iter().filter(|x| x.abs() > EPS).count() as f64 / native_delta.len() as f64; sums[8] += reference_capture(&native_delta, &reference);
            for ((&e, &r), seen_i) in sim.eligibility.iter().zip(&reference).zip(seen.iter_mut()) { if e.abs() > EPS && r.abs() > EPS { *seen_i += 1; } } for ((&e, &r), match_i) in sim.eligibility.iter().zip(&reference).zip(matches.iter_mut()) { if e.abs() > EPS && r.abs() > EPS && e.signum() == r.signum() { *match_i += 1; } }
            let target = norm(&reference); match arm { "native" => custom.copy_from_slice(&native_delta), "sign_ref_native_mag" => { for ((o, &n), &r) in custom.iter_mut().zip(&native_delta).zip(&reference) { let sign = if r.abs() > EPS { r.signum() } else { n.signum() }; *o = if n.abs() > EPS { n.abs() * sign } else { 0.0 }; } }, "stable_inversion_flip" => { custom.copy_from_slice(&native_delta); for (o, &flip) in custom.iter_mut().zip(mask.iter()) { if flip { *o = -*o; } } }, "reference_direction_native_support" => masked_rescale(&reference, &native_delta, target, &mut custom), _ => unreachable!() }
            before.copy_from_slice(&sim.weights); sim.apply_delta(&custom); for (o, (&after, &old)) in delivered.iter_mut().zip(sim.weights.iter().zip(&before)) { *o = after - old; } sums[3] += cosine(&delivered, &reference); cumulative += norm(&delivered).powi(2); for (&requested, &actual) in custom.iter().zip(&delivered) { if requested.abs() > EPS { touched += 1; if f64::from(requested - actual).abs() > 1e-6 { clips += 1; } } }
            count += 1; if arm == "native" && CHECKPOINTS.contains(&(trial + 1)) { let (correct, inverted, unstable) = stable_fractions(&seen, &matches); trajectories.push(serde_json::to_string(&Trajectory { substrate: job.substrate, side: job.side, block: job.block, checkpoint: trial + 1, eligibility_cosine: sums[0] / count as f64, modulation_cosine: sums[1] / count as f64, aggregation_cosine: sums[2] / count as f64, delivered_cosine: sums[3] / count as f64, local_cancellation: sums[4] / count as f64, local_sign_agreement: sums[5] / count as f64, aggregate_sign_agreement: sums[6] / count as f64, stable_correct_fraction: correct, stable_inverted_fraction: inverted, unstable_fraction: unstable })? + "\n"); }
            if CHECKPOINTS.contains(&(trial + 1)) { let l = sim.loss(&task, &eval.response_draws_u64); let ll = sim.loss(&task, &large.response_draws_u64); outcomes.push(serde_json::to_string(&Outcome { substrate: job.substrate, side: job.side, block: job.block, arm, checkpoint: trial + 1, loss_256: l, loss_large: ll, oracle_large, excess_large: ll - oracle_large, competent: l <= THRESHOLD, finite: sim.finite(), state_digest: sim.digest() })? + "\n"); }
        }
        let (correct, inverted, unstable) = stable_fractions(&seen, &matches); diagnostics.push(serde_json::to_string(&Diagnostics { substrate: job.substrate, side: job.side, block: job.block, arm, eligibility_cosine_mean: sums[0] / count as f64, modulation_cosine_mean: sums[1] / count as f64, aggregation_cosine_mean: sums[2] / count as f64, delivered_cosine_mean: sums[3] / count as f64, local_cancellation_mean: sums[4] / count as f64, local_sign_agreement_mean: sums[5] / count as f64, aggregate_sign_agreement_mean: sums[6] / count as f64, native_support_fraction_mean: sums[7] / count as f64, reference_mass_on_native_support_mean: sums[8] / count as f64, stable_correct_fraction: correct, stable_inverted_fraction: inverted, unstable_fraction: unstable, bound_clip_fraction: if touched == 0 { 0.0 } else { clips as f64 / touched as f64 }, cumulative_delivered_l2: cumulative.sqrt(), finite: sim.finite() })? + "\n");
    }
    Ok((outcomes, diagnostics, trajectories))
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect(); ensure!(args.len() == 3, "usage: fly-reach-02-executor STUDY_ROOT RUN_ROOT"); let study = fs::canonicalize(&args[1])?; let run = PathBuf::from(&args[2]); fs::create_dir_all(&run)?; let started = Instant::now(); eprintln!("reach02_preflight_start"); let contract = verify_contract(&study)?;
    let qtrain: TrainBank = serde_json::from_reader(File::open(study.join("inputs/banks/qualification-training.json"))?)?; let train: TrainBank = serde_json::from_reader(File::open(study.join("inputs/banks/measured-training.json"))?)?; let qeval: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/qualification-competence.json"))?)?; let _qlarge: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/qualification-large.json"))?)?; let eval: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/measured-competence.json"))?)?; let large: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/measured-large.json"))?)?;
    ensure!(qtrain.blocks.len() == 4 && train.blocks.len() == 12 && qeval.response_draws_u64.len() == 256 && eval.response_draws_u64.len() == 256 && large.response_draws_u64.len() == 4096); let mut graphs: BTreeMap<(String, String), Arc<graph::Graph>> = BTreeMap::new(); for &s in &SUBSTRATES { for &side in &SIDES { graphs.insert((s.to_string(), side.to_string()), Arc::new(graph::load(&study, s, side, GLUT_SIGN)?)); } }
    eprintln!("reach02_qualification_start"); let masks = build_masks(&graphs, &qtrain)?; let mut qfile = BufWriter::new(OpenOptions::new().create_new(true).write(true).open(run.join("qualification-diagnostics.jsonl"))?); let mut mask_manifest = Vec::new(); for ((s, side), info) in &masks { for row in &info.qualification_rows { qfile.write_all(row.as_bytes())?; } let mut h = Sha256::new(); for &value in info.mask.iter() { h.update([u8::from(value)]); } mask_manifest.push(serde_json::json!({"substrate":s,"side":side,"edge_count":info.mask.len(),"stable_inversion_fraction":info.stable_fraction,"mask_sha256":format!("{:x}",h.finalize())})); } qfile.flush()?; let mut mf = File::create(run.join("stable-inversion-masks.json"))?; serde_json::to_writer_pretty(&mut mf, &serde_json::json!({"schema":"FLY-REACH-02-derived-mask-v1","selection_rule":{"min_observations":MIN_OBSERVATIONS,"max_sign_agreement":MAX_INVERSION_AGREEMENT},"masks":mask_manifest}))?; mf.write_all(b"\n")?;
    let jobs: Vec<Job> = SUBSTRATES.iter().flat_map(|&s| SIDES.iter().flat_map(move |&side| BLOCKS.iter().map(move |&block| Job { substrate: s, side, block }))).collect(); ensure!(jobs.len() == 216); eprintln!("reach02_collection_start blocks={}", jobs.len()); let results: Vec<Result<(Vec<String>, Vec<String>, Vec<String>)>> = jobs.par_iter().map(|job| run_job(graphs.get(&(job.substrate.to_string(), job.side.to_string())).unwrap().clone(), masks.get(&(job.substrate.to_string(), job.side.to_string())).unwrap().mask.clone(), *job, train.blocks.get(&job.block.to_string()).unwrap(), &eval, &large)).collect();
    let mut outcomes = BufWriter::new(OpenOptions::new().create_new(true).write(true).open(run.join("outcomes.jsonl"))?); let mut diagnostics = BufWriter::new(OpenOptions::new().create_new(true).write(true).open(run.join("diagnostics.jsonl"))?); let mut trajectories = BufWriter::new(OpenOptions::new().create_new(true).write(true).open(run.join("trajectories.jsonl"))?); let mut oc = 0_usize; let mut dc = 0_usize; let mut tc = 0_usize; for result in results { let (a, b, c) = result?; for row in a { outcomes.write_all(row.as_bytes())?; oc += 1; } for row in b { diagnostics.write_all(row.as_bytes())?; dc += 1; } for row in c { trajectories.write_all(row.as_bytes())?; tc += 1; } } outcomes.flush()?; diagnostics.flush()?; trajectories.flush()?;
    let receipt = serde_json::json!({"schema":"FLY-REACH-02-v0.1b-collection-receipt-v1","study_id":"FLY-REACH-02-v0.1b","status":"COLLECTION_COMPLETE","engineering_only":true,"qualification_rows":72,"completed_blocks":216,"outcome_rows":oc,"diagnostic_rows":dc,"trajectory_rows":tc,"arms":ARMS,"checkpoints":CHECKPOINTS,"contract_sha256":hash_file(&study.join("manifests/REACH02-CONTRACT.json"))?,"wall_seconds":started.elapsed().as_secs_f64(),"qualification_response_bank_sha256":hash_file(&study.join("inputs/banks/qualification-competence.json"))?}); let mut f = OpenOptions::new().create_new(true).write(true).open(run.join("collection-receipt.json"))?; serde_json::to_writer_pretty(&mut f, &receipt)?; f.write_all(b"\n")?; eprintln!("reach02_collection_complete outcomes={} diagnostics={} trajectories={}", oc, dc, tc); Ok(())
}

#[cfg(test)] mod tests { use super::*; #[test] fn contract_constants() { assert_eq!(ARMS.len(), 5); assert_eq!(Q_BLOCKS.len(), 4); assert_eq!(BLOCKS.len(), 12); assert_eq!(MAX_INVERSION_AGREEMENT, 0.20); } }
