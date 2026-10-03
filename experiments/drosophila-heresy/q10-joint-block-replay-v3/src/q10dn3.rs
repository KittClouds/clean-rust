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
use nalgebra::{DMatrix, DVector, linalg::SVD};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
};

const PROTOCOL: &str = "Q10-DN3";
const SEEDS: &[u64] = &[9631, 9632];
const TAUS: &[f32] = &[4.0, 16.0];
const SIDES: &[&str] = &["R", "L"];
const SAMPLE_TRIALS: &[usize] = &[1, 64, 128, 256];
const STEPS: usize = 16;
const STEP_CURVE: &[usize] = &[1, 2, 4, 8, 16];
const RANK_MULTIPLIER: f64 = 1_000_000.0;
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
struct CurvePoint { steps: usize, rank: usize, active_rows: usize, residual_ratio: f64 }

#[derive(Serialize)]
struct StepMetric {
    step: usize,
    effect_count: usize,
    mean_novelty_fraction: f64,
    max_novelty_fraction: f64,
    mean_error_alignment: f64,
    max_abs_error_alignment: f64,
}

#[derive(Serialize)]
struct EventResult {
    seed: u64,
    side: String,
    tau: f32,
    trial: usize,
    parent_status: &'static str,
    status: &'static str,
    initial_mismatch_count: usize,
    one_step_effects: usize,
    sixteen_step_effects: usize,
    one_step_authority_rows: usize,
    sixteen_step_authority_rows: usize,
    newly_authorized_rows: usize,
    unreachable_error_ratio_at_one_step: f64,
    unreachable_error_norm_at_one_step: f64,
    unreachable_error_outside_one_step_rows_fraction: f64,
    curve: Vec<CurvePoint>,
    step_metrics: Vec<StepMetric>,
}

#[derive(Clone)]
struct SparseColumn { step: usize, effects: Vec<(usize, f64)> }

struct Basis { vectors: DMatrix<f64>, active: Vec<bool>, rank: usize }

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
    let mut paths = vec![
        PathBuf::from("Cargo.toml"), PathBuf::from("Cargo.lock"),
        PathBuf::from("PLAN.md"), PathBuf::from("CONTRACT.json"),
        PathBuf::from("dn-config.json"),
    ];
    visit_files(root, &root.join("src"), &mut paths)?;
    paths.push(PathBuf::from("scripts/review_q10_dn.py"));
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
        "sample_trials": SAMPLE_TRIALS, "steps": STEPS, "step_curve": STEP_CURVE,
        "factorization": "direct active-row f64 SVD", "rank_multiplier": RANK_MULTIPLIER,
        "scientific_seed_bundles": 0, "behavior": false, "dh08b": false
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

fn basis(matrix: DMatrix<f64>) -> Result<Basis> {
    if matrix.nrows() == 0 || matrix.ncols() == 0 {
        return Ok(Basis { vectors: DMatrix::zeros(matrix.nrows(), 0), active: Vec::new(), rank: 0 });
    }
    let svd = SVD::new(matrix, true, false);
    let vectors = svd.u.context("direct SVD did not return active-row vectors")?;
    let sigma_max = svd.singular_values.iter().copied().fold(0.0, f64::max);
    let cutoff = sigma_max * vectors.nrows().max(svd.singular_values.len()) as f64 * f64::EPSILON * RANK_MULTIPLIER;
    let active = svd.singular_values.iter().map(|&value| value > cutoff && value.is_finite()).collect::<Vec<_>>();
    let rank = active.iter().filter(|&&value| value).count();
    Ok(Basis { vectors, active, rank })
}

fn project(basis: &Basis, value: &DVector<f64>) -> DVector<f64> {
    let mut out = DVector::zeros(value.len());
    for (index, &active) in basis.active.iter().enumerate() {
        if active {
            let coefficient = basis.vectors.column(index).dot(value);
            out += basis.vectors.column(index) * coefficient;
        }
    }
    out
}

fn active_rows(columns: &[SparseColumn], limit: usize, total_rows: usize) -> Vec<usize> {
    let mut active = vec![false; total_rows];
    for column in columns.iter().filter(|column| column.step <= limit) {
        for &(row, _) in &column.effects { active[row] = true; }
    }
    active.into_iter().enumerate().filter_map(|(row, value)| value.then_some(row)).collect()
}

fn materialize(columns: &[SparseColumn], limit: usize, rows: &[usize], total_rows: usize) -> DMatrix<f64> {
    let mut row_map = vec![usize::MAX; total_rows];
    for (index, &row) in rows.iter().enumerate() { row_map[row] = index; }
    let selected = columns.iter().filter(|column| column.step <= limit).collect::<Vec<_>>();
    let mut matrix = DMatrix::<f64>::zeros(rows.len(), selected.len());
    for (column_index, column) in selected.into_iter().enumerate() {
        for &(row, value) in &column.effects { matrix[(row_map[row], column_index)] = value; }
    }
    matrix
}

fn sparse_metrics(
    column: &SparseColumn,
    one_rows: &[usize],
    one_map: &[usize],
    one_basis: &Basis,
    unreachable: &DVector<f64>,
    total_rows: usize,
) -> (f64, f64) {
    let mut one_values = DVector::zeros(one_rows.len());
    let mut outside_norm_sq = 0.0;
    let mut outside_dot = 0.0;
    for &(row, value) in &column.effects {
        let local = one_map[row];
        if local == usize::MAX {
            outside_norm_sq += value * value;
            outside_dot += value * unreachable[row];
        } else {
            one_values[local] = value;
        }
    }
    let norm = (one_values.norm_squared() + outside_norm_sq).sqrt();
    if norm == 0.0 { return (0.0, 0.0); }
    let residual = &one_values - project(one_basis, &one_values);
    let novel_norm = (residual.norm_squared() + outside_norm_sq).sqrt();
    let dot = residual.dot(&DVector::from_iterator(one_rows.len(), one_rows.iter().map(|&row| unreachable[row]))) + outside_dot;
    let alignment = if novel_norm > 0.0 && unreachable.norm() > 0.0 { dot / (novel_norm * unreachable.norm()) } else { 0.0 };
    let _ = total_rows;
    (novel_norm / norm, alignment)
}

fn analyze_event(op: &DriveOperator, snapshot: &crate::capture::Snapshot, seed: u64, side: &str, tau: f32) -> Result<EventResult> {
    let parent = q10::analyze_event(op, snapshot, seed ^ u64::from(tau.to_bits()) ^ snapshot.trial as u64)?;
    if parent.event.status != "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT" {
        return Ok(EventResult { seed, side: side.to_owned(), tau, trial: snapshot.trial, parent_status: parent.event.status, status: "PARENT_CONSTRUCTOR_INELIGIBLE", initial_mismatch_count: 0, one_step_effects: 0, sixteen_step_effects: 0, one_step_authority_rows: 0, sixteen_step_authority_rows: 0, newly_authorized_rows: 0, unreachable_error_ratio_at_one_step: 0.0, unreachable_error_norm_at_one_step: 0.0, unreachable_error_outside_one_step_rows_fraction: 0.0, curve: Vec::new(), step_metrics: Vec::new() });
    }
    let weights = parent.committed_alternate(snapshot);
    let actual = readout::sequential(op, &weights);
    let target = readout::sequential(op, &snapshot.target);
    let error = DVector::from_iterator(actual.len(), actual.iter().zip(&target).map(|(&a, &b)| f64::from(a) - f64::from(b)));
    let error_norm = error.norm();
    let coordinate_rows = bank::coordinate_rows(op);
    let mut columns = Vec::with_capacity(parent.interior_indices.len() * 2 * STEPS);
    let mut step_effect_counts = [0usize; STEPS];
    let mut one_rows = vec![false; op.rows.len()];
    let mut all_rows = vec![false; op.rows.len()];
    for &coordinate in &parent.interior_indices {
        if coordinate_rows[coordinate].is_empty() { continue; }
        for direction in [bank::Direction::Down, bank::Direction::Up] {
            let mut replacement = weights[coordinate];
            for step in 1..=STEPS {
                let Some(next) = readout::nextafter32(replacement, direction.downward()) else { break; };
                replacement = next;
                if !replacement.is_finite() || replacement <= 0.0 || replacement >= 2.0 || readout::interior_steps(replacement, true, bank::FINAL_RESERVE) < bank::FINAL_RESERVE || readout::interior_steps(replacement, false, bank::FINAL_RESERVE) < bank::FINAL_RESERVE { break; }
                let effects = coordinate_rows[coordinate].iter().filter_map(|&row| {
                    let committed = readout::replay_row_with_move(op, row, &weights, coordinate, replacement);
                    (committed.to_bits() != actual[row].to_bits()).then_some((row, f64::from(committed) - f64::from(actual[row])))
                }).collect::<Vec<_>>();
                if effects.is_empty() { continue; }
                step_effect_counts[step - 1] += 1;
                for &(row, _) in &effects { all_rows[row] = true; if step == 1 { one_rows[row] = true; } }
                columns.push(SparseColumn { step, effects });
            }
        }
    }
    let one_rows = one_rows.into_iter().enumerate().filter_map(|(row, value)| value.then_some(row)).collect::<Vec<_>>();
    let all_rows = all_rows.into_iter().enumerate().filter_map(|(row, value)| value.then_some(row)).collect::<Vec<_>>();
    let mut one_map = vec![usize::MAX; op.rows.len()];
    for (index, &row) in one_rows.iter().enumerate() { one_map[row] = index; }
    let one_error = DVector::from_iterator(one_rows.len(), one_rows.iter().map(|&row| error[row]));
    let one_basis = basis(materialize(&columns, 1, &one_rows, op.rows.len()))?;
    let one_reachable = project(&one_basis, &one_error);
    let one_residual = &one_error - &one_reachable;
    let outside_error_sq = error.iter().enumerate().filter(|(row, _)| one_map[*row] == usize::MAX).map(|(_, value)| value * value).sum::<f64>();
    let unreachable_norm = (one_residual.norm_squared() + outside_error_sq).sqrt();
    let unreachable = &error - DVector::from_iterator(error.len(), error.iter().enumerate().map(|(row, _)| if one_map[row] == usize::MAX { 0.0 } else { one_reachable[one_map[row]] }));
    let mut curve = Vec::with_capacity(STEP_CURVE.len());
    let mut bases = Vec::with_capacity(STEP_CURVE.len());
    for &limit in STEP_CURVE {
        let rows = active_rows(&columns, limit, op.rows.len());
        let local_error = DVector::from_iterator(rows.len(), rows.iter().map(|&row| error[row]));
        let b = basis(materialize(&columns, limit, &rows, op.rows.len()))?;
        let residual = &local_error - project(&b, &local_error);
        let row_map = rows.to_vec();
        let outside = error.iter().enumerate().filter(|(row, _)| !row_map.contains(row)).map(|(_, value)| value * value).sum::<f64>();
        curve.push(CurvePoint { steps: limit, rank: b.rank, active_rows: rows.len(), residual_ratio: (residual.norm_squared() + outside).sqrt() / error_norm.max(1.0e-12) });
        bases.push((b, rows));
    }
    let mut sums_novelty = [0.0f64; STEPS];
    let mut max_novelty = [0.0f64; STEPS];
    let mut sums_alignment = [0.0f64; STEPS];
    let mut max_alignment = [0.0f64; STEPS];
    for column in &columns {
        let (eta, alignment) = sparse_metrics(column, &one_rows, &one_map, &one_basis, &unreachable, op.rows.len());
        let index = column.step - 1;
        sums_novelty[index] += eta;
        max_novelty[index] = max_novelty[index].max(eta);
        sums_alignment[index] += alignment;
        max_alignment[index] = max_alignment[index].max(alignment.abs());
    }
    let step_metrics = (0..STEPS).map(|index| StepMetric { step: index + 1, effect_count: step_effect_counts[index], mean_novelty_fraction: sums_novelty[index] / step_effect_counts[index].max(1) as f64, max_novelty_fraction: max_novelty[index], mean_error_alignment: sums_alignment[index] / step_effect_counts[index].max(1) as f64, max_abs_error_alignment: max_alignment[index] }).collect();
    let _ = bases;
    let _ = all_rows;
    Ok(EventResult { seed, side: side.to_owned(), tau, trial: snapshot.trial, parent_status: parent.event.status, status: "ANALYZED", initial_mismatch_count: actual.iter().zip(&target).filter(|(a, b)| a.to_bits() != b.to_bits()).count(), one_step_effects: step_effect_counts[0], sixteen_step_effects: step_effect_counts.iter().sum(), one_step_authority_rows: one_rows.len(), sixteen_step_authority_rows: curve.last().map_or(0, |point| point.active_rows), newly_authorized_rows: curve.last().map_or(0, |point| point.active_rows.saturating_sub(one_rows.len())), unreachable_error_ratio_at_one_step: curve[0].residual_ratio, unreachable_error_norm_at_one_step: unreachable_norm, unreachable_error_outside_one_step_rows_fraction: outside_error_sq.sqrt() / unreachable_norm.max(1.0e-12), curve, step_metrics })
}

fn run(args: &[String], root: &Path) -> Result<()> {
    ensure!(args.len() == 4, "usage: q10-direction-novelty CONFIG ANATOMY OUTPUT");
    verify_parent(root)?; contract_and_plan(root)?; let seal = verify_seal(root)?;
    let config: Config = serde_json::from_reader(File::open(&args[1])?)?; validate(&config)?;
    let expected = root.join("qualification/sample-9631-9632"); let out = root.join(&args[3]); ensure!(out == expected, "noncanonical Q10-DN output path"); std::fs::create_dir_all(&out)?; write_json(&out.join("pre-execution.json"), &seal)?;
    let pool = rayon::ThreadPoolBuilder::new().num_threads(config.threads).build()?; let mut total = 0;
    for &seed in SEEDS { for side in SIDES { for &tau in TAUS {
        let graph = Graph::load(Path::new(&args[2]), side, config.glut_sign)?; let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733); ensure!(rewire.accepted > 0 && rewire.degree_preserved);
        let task = Task::new(&graph, seed ^ config.input_salt, 16, 12, 512); let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())?;
        let mut sim = Simulator::new(&graph, &graph.route, seed, tau, config.eta, "E"); sim.capture = Some(crate::capture::Capture::new(sim.weights.len())); sim.policy = Some(Policy::new(sim.weights.len()));
        let run = sim.run_dh07(&task, Dh07Condition::TruePerpendicular, &shuffled, config.observe, 0).context("Q10-DN3 frozen Q10-SM simulation")?; ensure!(run.result.outcome.hot_allocations == 0);
        let policy = sim.policy.take().context("missing Q10-DN3 policy capture")?; ensure!(policy.count == 256);
        let selected = policy.snapshots[..policy.count].iter().filter(|s| SAMPLE_TRIALS.contains(&s.trial)).collect::<Vec<_>>(); ensure!(selected.len() == SAMPLE_TRIALS.len());
        let analyzed = pool.install(|| selected.par_iter().map(|snapshot| analyze_event(&op, snapshot, seed, side, tau)).collect::<Result<Vec<_>>>())?;
        total += analyzed.len(); write_json(&out.join(format!("seed{seed}-{side}-tau{tau}.json")), &json!({"protocol": PROTOCOL, "seed": seed, "side": side, "tau": tau, "events": analyzed, "scientific_seed_bundles": 0, "behavioral_inference": false, "dh08b_authorized": false}))?;
        println!("Q10-DN3 complete seed={seed} {side} tau={tau}");
    } } }
    ensure!(total == 32); write_json(&out.join("execution.json"), &json!({"protocol": PROTOCOL, "complete": true, "audited_events": total, "scientific_seed_bundles": 0, "behavioral_inference": false, "dh08b_authorized": false}))?; Ok(())
}

pub fn main() -> Result<()> { let args: Vec<_> = std::env::args().collect(); let root = Path::new(env!("CARGO_MANIFEST_DIR")); if args.len() == 2 && args[1] == "seal" { seal(root) } else { run(&args, root) } }
