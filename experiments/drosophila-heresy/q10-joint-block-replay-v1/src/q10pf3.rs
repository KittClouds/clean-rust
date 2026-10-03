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
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{fs::{File, OpenOptions}, io::{BufWriter, Write}, path::{Path, PathBuf}};

const PROTOCOL: &str = "Q10-PF4";
const SEEDS: &[u64] = &[9681, 9682];
const TAUS: &[f32] = &[4.0, 16.0];
const SIDES: &[&str] = &["R", "L"];
const SAMPLE_TRIALS: &[usize] = &[128];
const BUNDLES_PER_CATEGORY: usize = 3;
const PREFIX_STEPS: [usize; 5] = [1, 2, 4, 8, 16];
const PARENT_PLAN: &str = "8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D";
const PARENT_CONTRACT: &str = "5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF";
const PARENT_RESULT: &str = "68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337";
const PARENT_STATUS: &str = "D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4";

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Config { protocol: String, seeds: Vec<u64>, taus: Vec<f32>, sides: Vec<String>, trials: Vec<usize>, observe: bool, cues: usize, delay_steps: usize, total_trials: usize, eta: f32, glut_sign: f32, input_salt: u64, threads: usize }

#[derive(Serialize)]
struct BundleResult {
    category: &'static str,
    coordinate_a: usize,
    coordinate_b: usize,
    coordinate_c: usize,
    shared_rows: usize,
    direction_a: &'static str,
    direction_b: &'static str,
    direction_c: &'static str,
    valid_grid: usize,
    max_i3_ratio_error: f64,
    mean_i3_ratio_error: f64,
    nonzero_i3_cases: usize,
    max_i3_nonzero_rows: usize,
    max_pair_interaction_ratio_error: f64,
    max_case_steps: [usize; 3],
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
    base_error_norm: f64,
    bundle_count: usize,
    shared_bundle_count: usize,
    disjoint_bundle_count: usize,
    max_i3_ratio_error: f64,
    mean_i3_ratio_error: f64,
    bundles: Vec<BundleResult>,
}

type TripleCandidate = (usize, usize, usize, usize);

struct BundleContext { seed: u64, tau: f32, trial: usize }

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
        if path.is_dir() { visit_files(root, &path, paths)?; } else { paths.push(path.strip_prefix(root)?.to_owned()); }
    }
    Ok(())
}

fn source_manifest(root: &Path) -> Result<Vec<Value>> {
    let mut paths = vec![PathBuf::from("Cargo.toml"), PathBuf::from("Cargo.lock"), PathBuf::from("PLAN.md"), PathBuf::from("CONTRACT.json"), PathBuf::from("pf4-config.json")];
    visit_files(root, &root.join("src"), &mut paths)?;
    paths.push(PathBuf::from("scripts/review_q10_pf4.py"));
    paths.sort(); paths.dedup();
    paths.iter().map(|path| Ok(json!({"path": path, "sha256": hash_bytes(&std::fs::read(root.join(path))?)}))).collect()
}

fn verify_parent(root: &Path) -> Result<()> {
    let parent = root.parent().context("missing experiment parent")?.join("q10-safety-margin-v1");
    for (name, expected) in [("PLAN.md", PARENT_PLAN), ("CONTRACT.json", PARENT_CONTRACT), ("RESULT.md", PARENT_RESULT), ("STATUS.json", PARENT_STATUS)] {
        ensure!(hash_bytes(&std::fs::read(parent.join(name))?).eq_ignore_ascii_case(expected), "Q10-SM {name} lineage mismatch");
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
    ensure!(contract["protocol"] == PROTOCOL && contract["plan_sha256"].as_str().is_some_and(|value| value.eq_ignore_ascii_case(&plan)));
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
        "sample_trials": SAMPLE_TRIALS, "bundles_per_category": BUNDLES_PER_CATEGORY, "prefix_steps": PREFIX_STEPS,
        "scientific_seed_bundles": 0, "behavioral_inference": false, "dh08b_authorized": false
    }))
}

fn verify_seal(root: &Path) -> Result<Value> {
    let seal: Value = serde_json::from_reader(File::open(root.join("PREEXECUTION.json"))?)?;
    ensure!(seal["protocol"] == PROTOCOL && seal["status"] == "FROZEN_PRE_EXECUTION");
    ensure!(seal["source_manifest"] == serde_json::to_value(source_manifest(root)?)?);
    let executable = std::env::current_exe()?;
    let executable_hash = hash_bytes(&std::fs::read(executable)?);
    ensure!(seal["executable_sha256"].as_str().is_some_and(|value| value.eq_ignore_ascii_case(&executable_hash)));
    Ok(seal)
}

fn validate(config: &Config) -> Result<()> {
    ensure!(config.protocol == PROTOCOL && config.seeds == SEEDS && config.taus == TAUS);
    ensure!(config.sides == SIDES.iter().map(|side| (*side).to_owned()).collect::<Vec<_>>());
    ensure!(config.trials == SAMPLE_TRIALS && config.observe);
    ensure!(config.cues == 16 && config.delay_steps == 12 && config.total_trials == 512);
    ensure!(config.eta == 0.05 && config.glut_sign == -1.0 && config.input_salt == 858980352 && config.threads == 1);
    Ok(())
}

fn mix(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e3779b97f4a7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
    value ^ (value >> 31)
}

fn shared_count(a: &[usize], b: &[usize]) -> usize {
    let (mut i, mut j, mut count) = (0, 0, 0);
    while i < a.len() && j < b.len() {
        match a[i].cmp(&b[j]) { std::cmp::Ordering::Less => i += 1, std::cmp::Ordering::Greater => j += 1, std::cmp::Ordering::Equal => { count += 1; i += 1; j += 1; } }
    }
    count
}

fn shared_three(a: &[usize], b: &[usize], c: &[usize]) -> usize { a.iter().filter(|row| b.binary_search(row).is_ok() && c.binary_search(row).is_ok()).count() }

fn select_triples(coords: &[usize], rows: &[Vec<usize>], seed: u64, tau: f32) -> (Vec<TripleCandidate>, Vec<TripleCandidate>) {
    let mut shared: Vec<TripleCandidate> = Vec::with_capacity(BUNDLES_PER_CATEGORY);
    let mut disjoint: Vec<TripleCandidate> = Vec::with_capacity(BUNDLES_PER_CATEGORY);
    let mut attempt = 0u64;
    while (shared.len() < BUNDLES_PER_CATEGORY || disjoint.len() < BUNDLES_PER_CATEGORY) && attempt < 500_000 {
        let a_index = (mix(seed ^ u64::from(tau.to_bits()) ^ attempt) as usize) % coords.len();
        let b_index = (mix(seed ^ u64::from(tau.to_bits()) ^ attempt.wrapping_add(1)) as usize) % coords.len();
        let c_index = (mix(seed ^ u64::from(tau.to_bits()) ^ attempt.wrapping_add(2)) as usize) % coords.len();
        attempt += 3;
        if a_index == b_index || a_index == c_index || b_index == c_index { continue; }
        let mut ids = [coords[a_index], coords[b_index], coords[c_index]];
        ids.sort_unstable();
        if ids[0] == ids[1] || ids[1] == ids[2] || rows[ids[0]].is_empty() || rows[ids[1]].is_empty() || rows[ids[2]].is_empty() { continue; }
        let ab = shared_count(&rows[ids[0]], &rows[ids[1]]);
        let ac = shared_count(&rows[ids[0]], &rows[ids[2]]);
        let bc = shared_count(&rows[ids[1]], &rows[ids[2]]);
        let abc = shared_three(&rows[ids[0]], &rows[ids[1]], &rows[ids[2]]);
        if abc > 0 && shared.len() < BUNDLES_PER_CATEGORY && !shared.iter().any(|candidate| candidate.0 == ids[0] && candidate.1 == ids[1] && candidate.2 == ids[2]) { shared.push((ids[0], ids[1], ids[2], abc)); }
        if ab == 0 && ac == 0 && bc == 0 && disjoint.len() < BUNDLES_PER_CATEGORY && !disjoint.iter().any(|candidate| candidate.0 == ids[0] && candidate.1 == ids[1] && candidate.2 == ids[2]) { disjoint.push((ids[0], ids[1], ids[2], 0)); }
    }
    (shared, disjoint)
}

fn replacements(weights: &[f32], coordinate: usize, direction_down: bool) -> Option<Vec<f32>> {
    let mut value = weights[coordinate];
    let mut out = Vec::with_capacity(PREFIX_STEPS.len());
    let mut previous_step = 0;
    for &step in &PREFIX_STEPS {
        for _ in previous_step..step { value = readout::nextafter32(value, direction_down)?; }
        previous_step = step;
        if !value.is_finite() || value <= 0.0 || value >= 2.0 || readout::interior_steps(value, true, bank::FINAL_RESERVE) < bank::FINAL_RESERVE || readout::interior_steps(value, false, bank::FINAL_RESERVE) < bank::FINAL_RESERVE { return None; }
        out.push(value);
    }
    Some(out)
}

fn changed(weights: &[f32], coordinates: [usize; 3], values: [f32; 3]) -> Vec<f32> {
    let mut out = weights.to_vec();
    out[coordinates[0]] = values[0]; out[coordinates[1]] = values[1]; out[coordinates[2]] = values[2]; out
}

fn effect(actual: &[f32], changed: &[f32], op: &DriveOperator) -> Vec<f64> { actual.iter().zip(op.sequential(changed)).map(|(&base, value)| f64::from(value) - f64::from(base)).collect() }
fn norm(values: &[f64]) -> f64 { values.iter().map(|value| value * value).sum::<f64>().sqrt() }

fn analyze_bundle(op: &DriveOperator, weights: &[f32], actual: &[f32], base_error_norm: f64, candidate: TripleCandidate, category: &'static str, context: &BundleContext) -> Result<BundleResult> {
    let coordinates = [candidate.0, candidate.1, candidate.2];
    let key = mix(context.seed ^ u64::from(context.tau.to_bits()) ^ context.trial as u64 ^ (candidate.0 as u64).wrapping_mul(0x9e3779b1) ^ (candidate.1 as u64).wrapping_mul(0xbf58476d) ^ (candidate.2 as u64).wrapping_mul(0x94d049bb));
    let downs = [(key & 1) == 0, (key & 2) == 0, (key & 4) == 0];
    let values = [replacements(weights, coordinates[0], downs[0]), replacements(weights, coordinates[1], downs[1]), replacements(weights, coordinates[2], downs[2])];
    ensure!(values.iter().all(Option::is_some), "bundle lacks all legal prefix endpoints");
    let values = [values[0].as_ref().unwrap(), values[1].as_ref().unwrap(), values[2].as_ref().unwrap()];
    let mut singles = vec![vec![Vec::<f64>::new(); PREFIX_STEPS.len()]; 3];
    for coordinate in 0..3 { for step in 0..PREFIX_STEPS.len() { let mut one = weights.to_vec(); one[coordinates[coordinate]] = values[coordinate][step]; singles[coordinate][step] = effect(actual, &one, op); } }
    let mut pairs = vec![vec![vec![Vec::<f64>::new(); PREFIX_STEPS.len()]; PREFIX_STEPS.len()]; 3];
    let pair_indices = [(0usize, 1usize), (0, 2), (1, 2)];
    for (pair_index, &(a, b)) in pair_indices.iter().enumerate() { for step_a in 0..PREFIX_STEPS.len() { for step_b in 0..PREFIX_STEPS.len() { let mut two = weights.to_vec(); two[coordinates[a]] = values[a][step_a]; two[coordinates[b]] = values[b][step_b]; pairs[pair_index][step_a][step_b] = effect(actual, &two, op); } } }
    let mut max_i3_ratio_error = 0.0;
    let mut mean_i3_ratio_error = 0.0;
    let mut nonzero_i3_cases = 0;
    let mut max_i3_nonzero_rows = 0;
    let mut max_pair_interaction_ratio_error: f64 = 0.0;
    let mut max_case_steps = [0usize; 3];
    for step_a in 0..PREFIX_STEPS.len() { for step_b in 0..PREFIX_STEPS.len() { for step_c in 0..PREFIX_STEPS.len() {
        let triple = effect(actual, &changed(weights, coordinates, [values[0][step_a], values[1][step_b], values[2][step_c]]), op);
        let mut i3 = vec![0.0; triple.len()];
        for row in 0..triple.len() { i3[row] = triple[row] - pairs[0][step_a][step_b][row] - pairs[1][step_a][step_c][row] - pairs[2][step_b][step_c][row] + singles[0][step_a][row] + singles[1][step_b][row] + singles[2][step_c][row]; }
        let ratio = norm(&i3) / base_error_norm.max(1.0e-12);
        mean_i3_ratio_error += ratio;
        if ratio > 0.0 { nonzero_i3_cases += 1; }
        let nonzero_rows = i3.iter().filter(|&&value| value != 0.0).count();
        max_i3_nonzero_rows = max_i3_nonzero_rows.max(nonzero_rows);
        if ratio > max_i3_ratio_error { max_i3_ratio_error = ratio; max_case_steps = [PREFIX_STEPS[step_a], PREFIX_STEPS[step_b], PREFIX_STEPS[step_c]]; }
        for (pair_index, &(a, b)) in pair_indices.iter().enumerate() { let mut interaction = vec![0.0; triple.len()]; let pair = &pairs[pair_index][if a == 0 { step_a } else { step_b }][if b == 1 { step_b } else { step_c }]; for row in 0..triple.len() { interaction[row] = pair[row] - singles[a][if a == 0 { step_a } else { step_b }][row] - singles[b][if b == 1 { step_b } else { step_c }][row]; } max_pair_interaction_ratio_error = max_pair_interaction_ratio_error.max(norm(&interaction) / base_error_norm.max(1.0e-12)); }
    } } }
    mean_i3_ratio_error /= (PREFIX_STEPS.len() * PREFIX_STEPS.len() * PREFIX_STEPS.len()) as f64;
    Ok(BundleResult { category, coordinate_a: coordinates[0], coordinate_b: coordinates[1], coordinate_c: coordinates[2], shared_rows: candidate.3, direction_a: if downs[0] { "down" } else { "up" }, direction_b: if downs[1] { "down" } else { "up" }, direction_c: if downs[2] { "down" } else { "up" }, valid_grid: 125, max_i3_ratio_error, mean_i3_ratio_error, nonzero_i3_cases, max_i3_nonzero_rows, max_pair_interaction_ratio_error, max_case_steps })
}

fn analyze_event(op: &DriveOperator, snapshot: &crate::capture::Snapshot, seed: u64, side: &str, tau: f32) -> Result<EventResult> {
    let parent = q10::analyze_event(op, snapshot, seed ^ u64::from(tau.to_bits()) ^ snapshot.trial as u64)?;
    if parent.event.status != "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT" { return Ok(EventResult { seed, side: side.to_owned(), tau, trial: snapshot.trial, parent_status: parent.event.status, status: "PARENT_CONSTRUCTOR_INELIGIBLE", initial_mismatch_count: 0, base_error_norm: 0.0, bundle_count: 0, shared_bundle_count: 0, disjoint_bundle_count: 0, max_i3_ratio_error: 0.0, mean_i3_ratio_error: 0.0, bundles: Vec::new() }); }
    let weights = parent.committed_alternate(snapshot);
    let actual = readout::sequential(op, &weights);
    let target = readout::sequential(op, &snapshot.target);
    let base_error: Vec<f64> = actual.iter().zip(&target).map(|(&a, &b)| f64::from(a) - f64::from(b)).collect();
    let base_error_norm = norm(&base_error);
    let coordinate_rows = bank::coordinate_rows(op);
    let coords: Vec<usize> = parent.interior_indices.iter().copied().filter(|&coordinate| !coordinate_rows[coordinate].is_empty()).collect();
    ensure!(!coords.is_empty(), "empty eligible coordinate set");
    let (shared, disjoint) = select_triples(&coords, &coordinate_rows, seed, tau);
    let context = BundleContext { seed, tau, trial: snapshot.trial };
    let mut bundles = Vec::with_capacity(shared.len() + disjoint.len());
    for candidate in shared { bundles.push(analyze_bundle(op, &weights, &actual, base_error_norm, candidate, "shared", &context)?); }
    for candidate in disjoint { bundles.push(analyze_bundle(op, &weights, &actual, base_error_norm, candidate, "disjoint", &context)?); }
    let shared_bundle_count = bundles.iter().filter(|bundle| bundle.category == "shared").count();
    let disjoint_bundle_count = bundles.iter().filter(|bundle| bundle.category == "disjoint").count();
    let max_i3_ratio_error = bundles.iter().map(|bundle| bundle.max_i3_ratio_error).fold(0.0, f64::max);
    let mean_i3_ratio_error = if bundles.is_empty() { 0.0 } else { bundles.iter().map(|bundle| bundle.mean_i3_ratio_error).sum::<f64>() / bundles.len() as f64 };
    let status = if shared_bundle_count == BUNDLES_PER_CATEGORY && disjoint_bundle_count == BUNDLES_PER_CATEGORY { "BUNDLE_ORDER_AUDIT_COMPLETE" } else { "BUNDLE_CAPACITY_PARTIAL" };
    Ok(EventResult { seed, side: side.to_owned(), tau, trial: snapshot.trial, parent_status: parent.event.status, status, initial_mismatch_count: actual.iter().zip(&target).filter(|(a, b)| a.to_bits() != b.to_bits()).count(), base_error_norm, bundle_count: bundles.len(), shared_bundle_count, disjoint_bundle_count, max_i3_ratio_error, mean_i3_ratio_error, bundles })
}

fn run(args: &[String], root: &Path) -> Result<()> {
    ensure!(args.len() == 4, "usage: q10-prefix-feasibility CONFIG ANATOMY OUTPUT");
    verify_parent(root)?; contract_and_plan(root)?; let seal = verify_seal(root)?;
    let config: Config = serde_json::from_reader(File::open(&args[1])?)?; validate(&config)?;
    let expected = root.join("qualification/sample-9681-9682"); let out = root.join(&args[3]); ensure!(out == expected, "noncanonical Q10-PF4 output path"); std::fs::create_dir_all(&out)?; write_json(&out.join("pre-execution.json"), &seal)?;
    let mut total = 0;
    for &seed in SEEDS { for side in SIDES { for &tau in TAUS {
        let graph = Graph::load(Path::new(&args[2]), side, config.glut_sign)?; let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733); ensure!(rewire.accepted > 0 && rewire.degree_preserved);
        let task = Task::new(&graph, seed ^ config.input_salt, 16, 12, 512); let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())?;
        let mut sim = Simulator::new(&graph, &graph.route, seed, tau, config.eta, "E"); sim.capture = Some(crate::capture::Capture::new(sim.weights.len())); sim.policy = Some(Policy::new(sim.weights.len()));
        let run = sim.run_dh07(&task, Dh07Condition::TruePerpendicular, &shuffled, config.observe, 0).context("Q10-PF3 frozen simulation")?; ensure!(run.result.outcome.hot_allocations == 0);
        let policy = sim.policy.take().context("missing Q10-PF3 policy capture")?; ensure!(policy.count == 256);
        let selected = policy.snapshots[..policy.count].iter().filter(|snapshot| SAMPLE_TRIALS.contains(&snapshot.trial)).collect::<Vec<_>>(); ensure!(selected.len() == SAMPLE_TRIALS.len());
        let analyzed = selected.iter().map(|snapshot| analyze_event(&op, snapshot, seed, side, tau)).collect::<Result<Vec<_>>>()?;
        total += analyzed.len(); write_json(&out.join(format!("seed{seed}-{side}-tau{tau}.json")), &json!({"protocol": PROTOCOL, "seed": seed, "side": side, "tau": tau, "events": analyzed, "scientific_seed_bundles": 0, "behavioral_inference": false, "dh08b_authorized": false}))?;
        println!("Q10-PF3 complete seed={seed} {side} tau={tau}");
    } } }
    ensure!(total == 8); write_json(&out.join("execution.json"), &json!({"protocol": PROTOCOL, "complete": true, "audited_events": total, "scientific_seed_bundles": 0, "behavioral_inference": false, "dh08b_authorized": false}))?; Ok(())
}

pub fn main() -> Result<()> { let args: Vec<_> = std::env::args().collect(); let root = Path::new(env!("CARGO_MANIFEST_DIR")); if args.len() == 2 && args[1] == "seal" { seal(root) } else { run(&args, root) } }
