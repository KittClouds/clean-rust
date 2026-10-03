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

const PROTOCOL: &str = "Q10-PF2";
const SEEDS: &[u64] = &[9661, 9662];
const TAUS: &[f32] = &[4.0, 16.0];
const SIDES: &[&str] = &["R", "L"];
const SAMPLE_TRIALS: &[usize] = &[128];
const PAIRS_PER_CATEGORY: usize = 12;
const PREFIX_STEPS: &[usize] = &[1, 2, 4, 8, 16];
const PARENT_PLAN: &str = "8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D";
const PARENT_CONTRACT: &str = "5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF";
const PARENT_RESULT: &str = "68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337";
const PARENT_STATUS: &str = "D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4";

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Config { protocol: String, seeds: Vec<u64>, taus: Vec<f32>, sides: Vec<String>, trials: Vec<usize>, observe: bool, cues: usize, delay_steps: usize, total_trials: usize, eta: f32, glut_sign: f32, input_salt: u64, threads: usize }

#[derive(Serialize)]
struct PairResult {
    category: &'static str,
    coordinate_a: usize,
    coordinate_b: usize,
    direction_a: &'static str,
    direction_b: &'static str,
    step_a: usize,
    step_b: usize,
    shared_rows: usize,
    isolated_a_norm: f64,
    isolated_b_norm: f64,
    additive_norm: f64,
    joint_norm: f64,
    interaction_norm: f64,
    interaction_ratio_error: f64,
    interaction_ratio_joint: f64,
    interaction_max_abs: f64,
    interaction_nonzero_rows: usize,
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
    pair_count: usize,
    shared_pair_count: usize,
    disjoint_pair_count: usize,
    max_interaction_ratio_error: f64,
    mean_interaction_ratio_error: f64,
    pairs: Vec<PairResult>,
}

type PairCandidate = (usize, usize, usize);

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
    let mut paths = vec![PathBuf::from("Cargo.toml"), PathBuf::from("Cargo.lock"), PathBuf::from("PLAN.md"), PathBuf::from("CONTRACT.json"), PathBuf::from("pf2-config.json")];
    visit_files(root, &root.join("src"), &mut paths)?;
    paths.push(PathBuf::from("scripts/review_q10_pf2.py"));
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
        "sample_trials": SAMPLE_TRIALS, "pairs_per_category": PAIRS_PER_CATEGORY, "prefix_steps": PREFIX_STEPS,
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

fn select_pairs(coords: &[usize], rows: &[Vec<usize>]) -> (Vec<PairCandidate>, Vec<PairCandidate>) {
    let mut shared = Vec::with_capacity(PAIRS_PER_CATEGORY);
    let mut disjoint = Vec::with_capacity(PAIRS_PER_CATEGORY);
    let max_offset = coords.len().saturating_sub(1).min(1024);
    for offset in 1..=max_offset {
        for i in 0..coords.len() {
            if shared.len() >= PAIRS_PER_CATEGORY && disjoint.len() >= PAIRS_PER_CATEGORY { return (shared, disjoint); }
            let j = (i + offset) % coords.len();
            if i == j || coords[i] >= coords[j] { continue; }
            let overlap = shared_count(&rows[coords[i]], &rows[coords[j]]);
            if overlap > 0 && shared.len() < PAIRS_PER_CATEGORY { shared.push((coords[i], coords[j], overlap)); }
            if overlap == 0 && disjoint.len() < PAIRS_PER_CATEGORY { disjoint.push((coords[i], coords[j], 0)); }
        }
    }
    (shared, disjoint)
}

fn replacement(weights: &[f32], coordinate: usize, direction_down: bool, steps: usize) -> Option<f32> {
    let mut value = weights[coordinate];
    for _ in 0..steps { value = readout::nextafter32(value, direction_down)?; }
    (value.is_finite() && value > 0.0 && value < 2.0 && readout::interior_steps(value, true, bank::FINAL_RESERVE) >= bank::FINAL_RESERVE && readout::interior_steps(value, false, bank::FINAL_RESERVE) >= bank::FINAL_RESERVE).then_some(value)
}

fn changed(weights: &[f32], a: usize, a_value: f32, b: Option<(usize, f32)>) -> Vec<f32> {
    let mut out = weights.to_vec();
    out[a] = a_value;
    if let Some((coordinate, value)) = b { out[coordinate] = value; }
    out
}

fn effect(actual: &[f32], changed: &[f32], op: &DriveOperator) -> Vec<f64> {
    actual.iter().zip(op.sequential(changed)).map(|(&base, value)| f64::from(value) - f64::from(base)).collect()
}

fn norm(values: &[f64]) -> f64 { values.iter().map(|value| value * value).sum::<f64>().sqrt() }

fn analyze_event(op: &DriveOperator, snapshot: &crate::capture::Snapshot, seed: u64, side: &str, tau: f32) -> Result<EventResult> {
    let parent = q10::analyze_event(op, snapshot, seed ^ u64::from(tau.to_bits()) ^ snapshot.trial as u64)?;
    if parent.event.status != "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT" {
        return Ok(EventResult { seed, side: side.to_owned(), tau, trial: snapshot.trial, parent_status: parent.event.status, status: "PARENT_CONSTRUCTOR_INELIGIBLE", initial_mismatch_count: 0, base_error_norm: 0.0, pair_count: 0, shared_pair_count: 0, disjoint_pair_count: 0, max_interaction_ratio_error: 0.0, mean_interaction_ratio_error: 0.0, pairs: Vec::new() });
    }
    let weights = parent.committed_alternate(snapshot);
    let actual = readout::sequential(op, &weights);
    let target = readout::sequential(op, &snapshot.target);
    let base_error: Vec<f64> = actual.iter().zip(&target).map(|(&a, &b)| f64::from(a) - f64::from(b)).collect();
    let base_error_norm = norm(&base_error);
    let coordinate_rows = bank::coordinate_rows(op);
    let coords: Vec<usize> = parent.interior_indices.iter().copied().filter(|&coordinate| !coordinate_rows[coordinate].is_empty()).collect();
    let (shared, disjoint) = select_pairs(&coords, &coordinate_rows);
    let mut pairs = Vec::with_capacity(shared.len() + disjoint.len());
    for (category, candidates) in [("shared", shared), ("disjoint", disjoint)] {
        for (pair_index, (a, b, shared_rows)) in candidates.into_iter().enumerate() {
            let key = mix(seed ^ u64::from(tau.to_bits()) ^ snapshot.trial as u64 ^ (pair_index as u64).wrapping_mul(0x517cc1b727220a95) ^ (a as u64).wrapping_mul(0x9e3779b1) ^ (b as u64).wrapping_mul(0xbf58476d));
            let down_a = key & 1 == 0;
            let down_b = key & 2 == 0;
            let step_a = PREFIX_STEPS[((key >> 3) as usize) % PREFIX_STEPS.len()];
            let step_b = PREFIX_STEPS[((key >> 7) as usize) % PREFIX_STEPS.len()];
            let Some(value_a) = replacement(&weights, a, down_a, step_a) else { continue; };
            let Some(value_b) = replacement(&weights, b, down_b, step_b) else { continue; };
            let isolated_a = effect(&actual, &changed(&weights, a, value_a, None), op);
            let isolated_b = effect(&actual, &changed(&weights, b, value_b, None), op);
            let joint = effect(&actual, &changed(&weights, a, value_a, Some((b, value_b))), op);
            let additive: Vec<f64> = isolated_a.iter().zip(&isolated_b).map(|(a, b)| a + b).collect();
            let interaction: Vec<f64> = joint.iter().zip(&additive).map(|(joint, additive)| joint - additive).collect();
            let interaction_norm = norm(&interaction);
            pairs.push(PairResult { category, coordinate_a: a, coordinate_b: b, direction_a: if down_a { "down" } else { "up" }, direction_b: if down_b { "down" } else { "up" }, step_a, step_b, shared_rows, isolated_a_norm: norm(&isolated_a), isolated_b_norm: norm(&isolated_b), additive_norm: norm(&additive), joint_norm: norm(&joint), interaction_norm, interaction_ratio_error: interaction_norm / base_error_norm.max(1.0e-12), interaction_ratio_joint: interaction_norm / norm(&joint).max(1.0e-12), interaction_max_abs: interaction.iter().map(|value| value.abs()).fold(0.0, f64::max), interaction_nonzero_rows: interaction.iter().filter(|&&value| value != 0.0).count() });
        }
    }
    let shared_pair_count = pairs.iter().filter(|pair| pair.category == "shared").count();
    let disjoint_pair_count = pairs.iter().filter(|pair| pair.category == "disjoint").count();
    let max_interaction_ratio_error = pairs.iter().map(|pair| pair.interaction_ratio_error).fold(0.0, f64::max);
    let mean_interaction_ratio_error = if pairs.is_empty() { 0.0 } else { pairs.iter().map(|pair| pair.interaction_ratio_error).sum::<f64>() / pairs.len() as f64 };
    let status = if shared_pair_count >= PAIRS_PER_CATEGORY && disjoint_pair_count >= PAIRS_PER_CATEGORY { "INTERACTION_AUDIT_COMPLETE" } else { "PAIR_CAPACITY_PARTIAL" };
    Ok(EventResult { seed, side: side.to_owned(), tau, trial: snapshot.trial, parent_status: parent.event.status, status, initial_mismatch_count: actual.iter().zip(&target).filter(|(a, b)| a.to_bits() != b.to_bits()).count(), base_error_norm, pair_count: pairs.len(), shared_pair_count, disjoint_pair_count, max_interaction_ratio_error, mean_interaction_ratio_error, pairs })
}

fn run(args: &[String], root: &Path) -> Result<()> {
    ensure!(args.len() == 4, "usage: q10-prefix-feasibility CONFIG ANATOMY OUTPUT");
    verify_parent(root)?; contract_and_plan(root)?; let seal = verify_seal(root)?;
    let config: Config = serde_json::from_reader(File::open(&args[1])?)?; validate(&config)?;
    let expected = root.join("qualification/sample-9661-9662"); let out = root.join(&args[3]); ensure!(out == expected, "noncanonical Q10-PF2 output path"); std::fs::create_dir_all(&out)?; write_json(&out.join("pre-execution.json"), &seal)?;
    let mut total = 0;
    for &seed in SEEDS { for side in SIDES { for &tau in TAUS {
        let graph = Graph::load(Path::new(&args[2]), side, config.glut_sign)?; let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733); ensure!(rewire.accepted > 0 && rewire.degree_preserved);
        let task = Task::new(&graph, seed ^ config.input_salt, 16, 12, 512); let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())?;
        let mut sim = Simulator::new(&graph, &graph.route, seed, tau, config.eta, "E"); sim.capture = Some(crate::capture::Capture::new(sim.weights.len())); sim.policy = Some(Policy::new(sim.weights.len()));
        let run = sim.run_dh07(&task, Dh07Condition::TruePerpendicular, &shuffled, config.observe, 0).context("Q10-PF2 frozen simulation")?; ensure!(run.result.outcome.hot_allocations == 0);
        let policy = sim.policy.take().context("missing Q10-PF2 policy capture")?; ensure!(policy.count == 256);
        let selected = policy.snapshots[..policy.count].iter().filter(|snapshot| SAMPLE_TRIALS.contains(&snapshot.trial)).collect::<Vec<_>>(); ensure!(selected.len() == SAMPLE_TRIALS.len());
        let analyzed = selected.iter().map(|snapshot| analyze_event(&op, snapshot, seed, side, tau)).collect::<Result<Vec<_>>>()?;
        total += analyzed.len(); write_json(&out.join(format!("seed{seed}-{side}-tau{tau}.json")), &json!({"protocol": PROTOCOL, "seed": seed, "side": side, "tau": tau, "events": analyzed, "scientific_seed_bundles": 0, "behavioral_inference": false, "dh08b_authorized": false}))?;
        println!("Q10-PF2 complete seed={seed} {side} tau={tau}");
    } } }
    ensure!(total == 8); write_json(&out.join("execution.json"), &json!({"protocol": PROTOCOL, "complete": true, "audited_events": total, "scientific_seed_bundles": 0, "behavioral_inference": false, "dh08b_authorized": false}))?; Ok(())
}

pub fn main() -> Result<()> { let args: Vec<_> = std::env::args().collect(); let root = Path::new(env!("CARGO_MANIFEST_DIR")); if args.len() == 2 && args[1] == "seal" { seal(root) } else { run(&args, root) } }
