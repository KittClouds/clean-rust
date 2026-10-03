use crate::{
    graph::Graph,
    linear::DriveOperator,
    policy::Policy,
    q10,
    q10sr::{bank, readout},
    simulation::{Dh07Condition, Simulator},
    task::Task,
};
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
};

const PROTOCOL: &str = "Q10-PF1";
const SEEDS: &[u64] = &[9651, 9652];
const TAUS: &[f32] = &[4.0, 16.0];
const SIDES: &[&str] = &["R", "L"];
const SAMPLE_TRIALS: &[usize] = &[128];
const PREFIX_STEPS: usize = 16;
const PASSES: usize = 12;
const RELAX_TOLERANCE: f64 = 1.0e-6;
const PARENT_PLAN: &str = "8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D";
const PARENT_CONTRACT: &str = "5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF";
const PARENT_RESULT: &str = "68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337";
const PARENT_STATUS: &str = "D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    protocol: String,
    seeds: Vec<u64>,
    taus: Vec<f32>,
    sides: Vec<String>,
    trials: Vec<usize>,
    observe: bool,
    cues: usize,
    delay_steps: usize,
    total_trials: usize,
    eta: f32,
    glut_sign: f32,
    input_salt: u64,
    threads: usize,
}

#[derive(Serialize)]
struct PassPoint { pass: usize, residual_norm: f64, residual_ratio: f64 }

#[derive(Serialize)]
struct EventResult {
    seed: u64,
    side: String,
    tau: f32,
    trial: usize,
    parent_status: &'static str,
    status: &'static str,
    initial_mismatch_count: usize,
    error_norm: f64,
    relaxed_residual_norm: f64,
    relaxed_residual_ratio: f64,
    endpoint_coordinates: usize,
    endpoint_count: usize,
    nonzero_endpoint_count: usize,
    prefix_passes: usize,
    prefix_curve: Vec<PassPoint>,
}

struct Endpoint { effects: Vec<(usize, f64)>, norm_sq: f64 }

struct CoordinateHull { endpoints: Vec<Endpoint>, current: Vec<f64>, current_norm_sq: f64 }

fn hash_bytes(bytes: &[u8]) -> String { format!("{:x}", Sha256::digest(bytes)) }

fn write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let mut writer = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(path)?);
    serde_json::to_writer_pretty(&mut writer, value)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

fn visit_files(root: &Path, dir: &Path, paths: &mut Vec<PathBuf>) -> Result<()> {
    if !dir.exists() { return Ok(()); }
    for entry in std::fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() { visit_files(root, &path, paths)?; }
        else { paths.push(path.strip_prefix(root)?.to_owned()); }
    }
    Ok(())
}

fn source_manifest(root: &Path) -> Result<Vec<Value>> {
    let mut paths = vec![PathBuf::from("Cargo.toml"), PathBuf::from("Cargo.lock"), PathBuf::from("PLAN.md"), PathBuf::from("CONTRACT.json"), PathBuf::from("pf-config.json")];
    visit_files(root, &root.join("src"), &mut paths)?;
    paths.push(PathBuf::from("scripts/review_q10_pf.py"));
    paths.sort(); paths.dedup();
    paths.iter().map(|path| Ok(json!({"path": path, "sha256": hash_bytes(&std::fs::read(root.join(path))?)}))).collect()
}

fn verify_parent(root: &Path) -> Result<()> {
    let parent = root.parent().context("missing experiment parent")?.join("q10-safety-margin-v1");
    for (name, expected) in [("PLAN.md", PARENT_PLAN), ("CONTRACT.json", PARENT_CONTRACT), ("RESULT.md", PARENT_RESULT), ("STATUS.json", PARENT_STATUS)] {
        let actual = hash_bytes(&std::fs::read(parent.join(name))?);
        ensure!(actual.eq_ignore_ascii_case(expected), "Q10-SM {name} lineage mismatch actual={actual} expected={expected}");
    }
    let status: Value = serde_json::from_reader(File::open(parent.join("STATUS.json"))?)?;
    ensure!(status["status"] == "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT");
    ensure!(status["scientific_seed_bundles_used"] == 0 && status["future_dh08b_authorized"] == false);
    Ok(())
}

fn contract_and_plan(root: &Path) -> Result<(String, String)> {
    let plan = hash_bytes(&std::fs::read(root.join("PLAN.md"))?);
    let contract_hash = hash_bytes(&std::fs::read(root.join("CONTRACT.json"))?);
    let contract: Value = serde_json::from_reader(File::open(root.join("CONTRACT.json"))?)?;
    ensure!(contract["protocol"] == PROTOCOL && contract["plan_sha256"].as_str().is_some_and(|v| v.eq_ignore_ascii_case(&plan)));
    Ok((plan, contract_hash))
}

fn seal(root: &Path) -> Result<()> {
    verify_parent(root)?;
    let (plan, contract) = contract_and_plan(root)?;
    let executable = std::env::current_exe()?;
    write_json(&root.join("PREEXECUTION.json"), &json!({
        "protocol": PROTOCOL, "status": "FROZEN_PRE_EXECUTION", "source_manifest": source_manifest(root)?,
        "executable": executable, "executable_sha256": hash_bytes(&std::fs::read(&executable)?),
        "plan_sha256": plan, "contract_sha256": contract,
        "parent_hashes": {"plan": PARENT_PLAN, "contract": PARENT_CONTRACT, "result": PARENT_RESULT, "status": PARENT_STATUS},
        "sample_trials": SAMPLE_TRIALS, "prefix_steps": PREFIX_STEPS, "passes": PASSES,
        "relaxation_tolerance": RELAX_TOLERANCE, "scientific_seed_bundles": 0, "behavioral_inference": false, "dh08b_authorized": false
    }))
}

fn verify_seal(root: &Path) -> Result<Value> {
    let seal: Value = serde_json::from_reader(File::open(root.join("PREEXECUTION.json"))?)?;
    ensure!(seal["protocol"] == PROTOCOL && seal["status"] == "FROZEN_PRE_EXECUTION");
    ensure!(seal["source_manifest"] == serde_json::to_value(source_manifest(root)?)?);
    let executable = std::env::current_exe()?;
    let executable_hash = hash_bytes(&std::fs::read(executable)?);
    ensure!(seal["executable_sha256"].as_str().is_some_and(|v| v.eq_ignore_ascii_case(&executable_hash)));
    Ok(seal)
}

fn validate(config: &Config) -> Result<()> {
    ensure!(config.protocol == PROTOCOL && config.seeds == SEEDS && config.taus == TAUS);
    ensure!(config.sides == SIDES.iter().map(|s| (*s).to_owned()).collect::<Vec<_>>());
    ensure!(config.trials == SAMPLE_TRIALS && config.observe);
    ensure!(config.cues == 16 && config.delay_steps == 12 && config.total_trials == 512);
    ensure!(config.eta == 0.05 && config.glut_sign == -1.0 && config.input_salt == 858980352 && config.threads == 1);
    Ok(())
}

fn endpoint(op: &DriveOperator, weights: &[f32], actual: &[f32], coordinate: usize, replacement: f32, rows: &[usize]) -> Endpoint {
    let effects = rows.iter().filter_map(|&row| {
        let committed = readout::replay_row_with_move(op, row, weights, coordinate, replacement);
        (committed.to_bits() != actual[row].to_bits()).then_some((row, f64::from(committed) - f64::from(actual[row])))
    }).collect::<Vec<_>>();
    let norm_sq = effects.iter().map(|&(_, value)| value * value).sum();
    Endpoint { effects, norm_sq }
}

fn hull_for_coordinate(op: &DriveOperator, weights: &[f32], actual: &[f32], coordinate: usize, rows: &[usize]) -> CoordinateHull {
    let mut endpoints = vec![Endpoint { effects: Vec::new(), norm_sq: 0.0 }];
    for direction in [bank::Direction::Down, bank::Direction::Up] {
        let mut replacement = weights[coordinate];
        for _step in 1..=PREFIX_STEPS {
            let Some(next) = readout::nextafter32(replacement, direction.downward()) else { break; };
            replacement = next;
            if !replacement.is_finite() || replacement <= 0.0 || replacement >= 2.0 || readout::interior_steps(replacement, true, bank::FINAL_RESERVE) < bank::FINAL_RESERVE || readout::interior_steps(replacement, false, bank::FINAL_RESERVE) < bank::FINAL_RESERVE { break; }
            endpoints.push(endpoint(op, weights, actual, coordinate, replacement, rows));
        }
    }
    CoordinateHull { endpoints, current: vec![0.0; op.rows.len()], current_norm_sq: 0.0 }
}

fn relax(hulls: &mut [CoordinateHull], target: &[f64], passes: usize) -> Vec<PassPoint> {
    let mut residual = target.to_vec();
    let target_norm = target.iter().map(|value| value * value).sum::<f64>().sqrt();
    let mut curve = Vec::with_capacity(passes);
    for pass in 1..=passes {
        for hull in hulls.iter_mut() {
            let local_norm_sq = hull.current_norm_sq;
            let mut best_score = f64::INFINITY;
            let mut best = 0;
            for (index, candidate) in hull.endpoints.iter().enumerate() {
                let mut dot_local = 0.0;
                for &(row, value) in &candidate.effects { dot_local += value * (residual[row] + hull.current[row]); }
                let score = candidate.norm_sq - 2.0 * dot_local;
                if score < best_score { best_score = score; best = index; }
            }
            let candidate = &hull.endpoints[best];
            let mut residual_dot_delta = 0.0;
            let mut current_dot_candidate = 0.0;
            for &(row, value) in &candidate.effects { residual_dot_delta += residual[row] * value; current_dot_candidate += hull.current[row] * value; }
            let delta_norm_sq = candidate.norm_sq + local_norm_sq - 2.0 * current_dot_candidate;
            residual_dot_delta -= hull.current.iter().zip(residual.iter()).map(|(&current, &value)| current * value).sum::<f64>();
            if delta_norm_sq <= f64::EPSILON { continue; }
            let alpha = (residual_dot_delta / delta_norm_sq).clamp(0.0, 1.0);
            if alpha <= 0.0 { continue; }
            for (current, residual_value) in hull.current.iter_mut().zip(residual.iter_mut()) {
                let old = *current;
                *current = old * (1.0 - alpha);
                *residual_value += alpha * old;
            }
            for &(row, value) in &candidate.effects {
                hull.current[row] += alpha * value;
                residual[row] -= alpha * value;
            }
            hull.current_norm_sq = hull.current.iter().map(|value| value * value).sum();
        }
        let norm = residual.iter().map(|value| value * value).sum::<f64>().sqrt();
        curve.push(PassPoint { pass, residual_norm: norm, residual_ratio: norm / target_norm.max(1.0e-12) });
    }
    curve
}

fn analyze_event(op: &DriveOperator, snapshot: &crate::capture::Snapshot, seed: u64, side: &str, tau: f32) -> Result<EventResult> {
    let parent = q10::analyze_event(op, snapshot, seed ^ u64::from(tau.to_bits()) ^ snapshot.trial as u64)?;
    if parent.event.status != "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT" {
        return Ok(EventResult { seed, side: side.to_owned(), tau, trial: snapshot.trial, parent_status: parent.event.status, status: "PARENT_CONSTRUCTOR_INELIGIBLE", initial_mismatch_count: 0, error_norm: 0.0, relaxed_residual_norm: 0.0, relaxed_residual_ratio: 0.0, endpoint_coordinates: 0, endpoint_count: 0, nonzero_endpoint_count: 0, prefix_passes: 0, prefix_curve: Vec::new() });
    }
    let weights = parent.committed_alternate(snapshot);
    let actual = readout::sequential(op, &weights);
    let target_readout = readout::sequential(op, &snapshot.target);
    let target = actual.iter().zip(&target_readout).map(|(&a, &b)| f64::from(b) - f64::from(a)).collect::<Vec<_>>();
    let error_norm = target.iter().map(|value| value * value).sum::<f64>().sqrt();
    let coordinate_rows = bank::coordinate_rows(op);
    let mut hulls = Vec::with_capacity(parent.interior_indices.len());
    for &coordinate in &parent.interior_indices {
        if !coordinate_rows[coordinate].is_empty() { hulls.push(hull_for_coordinate(op, &weights, &actual, coordinate, &coordinate_rows[coordinate])); }
    }
    let endpoint_count = hulls.iter().map(|hull| hull.endpoints.len()).sum();
    let nonzero_endpoint_count = hulls.iter().flat_map(|hull| &hull.endpoints).filter(|endpoint| !endpoint.effects.is_empty()).count();
    let prefix_curve = relax(&mut hulls, &target, PASSES);
    let relaxed_residual_norm = prefix_curve.last().map_or(error_norm, |point| point.residual_norm);
    let relaxed_residual_ratio = relaxed_residual_norm / error_norm.max(1.0e-12);
    let status = if relaxed_residual_ratio <= RELAX_TOLERANCE { "RELAXATION_FIT" } else { "RELAXATION_PARTIAL" };
    Ok(EventResult { seed, side: side.to_owned(), tau, trial: snapshot.trial, parent_status: parent.event.status, status, initial_mismatch_count: actual.iter().zip(&target_readout).filter(|(a, b)| a.to_bits() != b.to_bits()).count(), error_norm, relaxed_residual_norm, relaxed_residual_ratio, endpoint_coordinates: hulls.len(), endpoint_count, nonzero_endpoint_count, prefix_passes: PASSES, prefix_curve })
}

fn run(args: &[String], root: &Path) -> Result<()> {
    ensure!(args.len() == 4, "usage: q10-prefix-feasibility CONFIG ANATOMY OUTPUT");
    verify_parent(root)?; contract_and_plan(root)?; let seal = verify_seal(root)?;
    let config: Config = serde_json::from_reader(File::open(&args[1])?)?; validate(&config)?;
    let expected = root.join("qualification/sample-9651-9652"); let out = root.join(&args[3]); ensure!(out == expected, "noncanonical Q10-PF output path"); std::fs::create_dir_all(&out)?; write_json(&out.join("pre-execution.json"), &seal)?;
    let mut total = 0;
    for &seed in SEEDS { for side in SIDES { for &tau in TAUS {
        let graph = Graph::load(Path::new(&args[2]), side, config.glut_sign)?; let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733); ensure!(rewire.accepted > 0 && rewire.degree_preserved);
        let task = Task::new(&graph, seed ^ config.input_salt, 16, 12, 512); let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())?;
        let mut sim = Simulator::new(&graph, &graph.route, seed, tau, config.eta, "E"); sim.capture = Some(crate::capture::Capture::new(sim.weights.len())); sim.policy = Some(Policy::new(sim.weights.len()));
        let run = sim.run_dh07(&task, Dh07Condition::TruePerpendicular, &shuffled, config.observe, 0).context("Q10-PF frozen Q10-SM simulation")?; ensure!(run.result.outcome.hot_allocations == 0);
        let policy = sim.policy.take().context("missing Q10-PF policy capture")?; ensure!(policy.count == 256);
        let selected = policy.snapshots[..policy.count].iter().filter(|s| SAMPLE_TRIALS.contains(&s.trial)).collect::<Vec<_>>(); ensure!(selected.len() == SAMPLE_TRIALS.len());
        let analyzed = selected.iter().map(|snapshot| analyze_event(&op, snapshot, seed, side, tau)).collect::<Result<Vec<_>>>()?;
        total += analyzed.len(); write_json(&out.join(format!("seed{seed}-{side}-tau{tau}.json")), &json!({"protocol": PROTOCOL, "seed": seed, "side": side, "tau": tau, "events": analyzed, "scientific_seed_bundles": 0, "behavioral_inference": false, "dh08b_authorized": false}))?;
        println!("Q10-PF complete seed={seed} {side} tau={tau}");
    } } }
    ensure!(total == 8); write_json(&out.join("execution.json"), &json!({"protocol": PROTOCOL, "complete": true, "audited_events": total, "scientific_seed_bundles": 0, "behavioral_inference": false, "dh08b_authorized": false}))?; Ok(())
}

pub fn main() -> Result<()> { let args: Vec<_> = std::env::args().collect(); let root = Path::new(env!("CARGO_MANIFEST_DIR")); if args.len() == 2 && args[1] == "seal" { seal(root) } else { run(&args, root) } }
