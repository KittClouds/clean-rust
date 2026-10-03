//! Q10-JBR1: exact local replay of jointly committed f32 endpoint blocks.
//!
//! Every candidate is applied simultaneously to a cloned committed weight
//! state and evaluated by the real sequential f32 readout. No additive or
//! interaction surrogate participates in candidate selection.

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
use std::{
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
};

const PROTOCOL: &str = "Q10-JBR1";
const SEEDS: &[u64] = &[9691, 9692];
const TAUS: &[f32] = &[4.0, 16.0];
const SIDES: &[&str] = &["R", "L"];
const SAMPLE_TRIALS: &[usize] = &[128];
const BLOCKS_PER_CATEGORY: usize = 3;
const PREFIX_STEPS: [usize; 5] = [1, 2, 4, 8, 16];
const PARENT_PLAN: &str = "8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D";
const PARENT_CONTRACT: &str = "5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF";
const PARENT_RESULT: &str = "68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337";
const PARENT_STATUS: &str = "D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4";

#[derive(serde::Deserialize)]
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
struct BlockResult {
    category: &'static str,
    coordinate_a: usize,
    coordinate_b: usize,
    coordinate_c: usize,
    shared_rows: usize,
    direction_a: &'static str,
    direction_b: &'static str,
    direction_c: &'static str,
    candidate_count: usize,
    base_error_norm: f64,
    best_residual_norm: f64,
    best_residual_ratio: f64,
    residual_reduction: f64,
    best_bitwise_mismatch_count: usize,
    best_steps: [usize; 3],
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
    block_count: usize,
    shared_block_count: usize,
    disjoint_block_count: usize,
    best_shared_residual_ratio: f64,
    best_disjoint_residual_ratio: f64,
    blocks: Vec<BlockResult>,
}

type TripleCandidate = (usize, usize, usize, usize);

struct BlockContext {
    seed: u64,
    tau: f32,
    trial: usize,
}

fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let mut writer = BufWriter::new(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)?,
    );
    serde_json::to_writer_pretty(&mut writer, value)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

fn visit_files(root: &Path, dir: &Path, paths: &mut Vec<PathBuf>) -> Result<()> {
    if !dir.exists() {
        return Ok(());
    }
    for entry in std::fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            visit_files(root, &path, paths)?;
        } else {
            paths.push(path.strip_prefix(root)?.to_owned());
        }
    }
    Ok(())
}

fn source_manifest(root: &Path) -> Result<Vec<Value>> {
    let mut paths = vec![
        PathBuf::from("Cargo.toml"),
        PathBuf::from("Cargo.lock"),
        PathBuf::from("PLAN.md"),
        PathBuf::from("CONTRACT.json"),
        PathBuf::from("q10-jbr-config.json"),
    ];
    visit_files(root, &root.join("src"), &mut paths)?;
    paths.push(PathBuf::from("scripts/review_q10_jbr.py"));
    paths.sort();
    paths.dedup();
    paths.iter()
        .map(|path| {
            Ok(json!({
                "path": path,
                "sha256": hash_bytes(&std::fs::read(root.join(path))?)
            }))
        })
        .collect()
}

fn verify_parent(root: &Path) -> Result<()> {
    let parent = root
        .parent()
        .context("missing experiment parent")?
        .join("q10-safety-margin-v1");
    for (name, expected) in [
        ("PLAN.md", PARENT_PLAN),
        ("CONTRACT.json", PARENT_CONTRACT),
        ("RESULT.md", PARENT_RESULT),
        ("STATUS.json", PARENT_STATUS),
    ] {
        ensure!(
            hash_bytes(&std::fs::read(parent.join(name))?).eq_ignore_ascii_case(expected),
            "Q10-SM {name} lineage mismatch"
        );
    }
    let status: Value = serde_json::from_reader(File::open(parent.join("STATUS.json"))?)?;
    ensure!(status["status"] == "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT");
    ensure!(status["scientific_seed_bundles_used"] == 0);
    ensure!(status["future_dh08b_authorized"] == false);
    Ok(())
}

fn contract_and_plan(root: &Path) -> Result<(String, String)> {
    let plan = hash_bytes(&std::fs::read(root.join("PLAN.md"))?);
    let contract_hash = hash_bytes(&std::fs::read(root.join("CONTRACT.json"))?);
    let contract: Value = serde_json::from_reader(File::open(root.join("CONTRACT.json"))?)?;
    ensure!(contract["protocol"] == PROTOCOL);
    ensure!(
        contract["plan_sha256"]
            .as_str()
            .is_some_and(|value| value.eq_ignore_ascii_case(&plan))
    );
    Ok((plan, contract_hash))
}

fn seal(root: &Path) -> Result<()> {
    verify_parent(root)?;
    let (plan, contract) = contract_and_plan(root)?;
    let executable = std::env::current_exe()?;
    write_json(
        &root.join("PREEXECUTION.json"),
        &json!({
            "protocol": PROTOCOL,
            "status": "FROZEN_PRE_EXECUTION",
            "source_manifest": source_manifest(root)?,
            "executable": executable,
            "executable_sha256": hash_bytes(&std::fs::read(&executable)?),
            "plan_sha256": plan,
            "contract_sha256": contract,
            "parent_hashes": {
                "plan": PARENT_PLAN,
                "contract": PARENT_CONTRACT,
                "result": PARENT_RESULT,
                "status": PARENT_STATUS
            },
            "sample_trials": SAMPLE_TRIALS,
            "blocks_per_category": BLOCKS_PER_CATEGORY,
            "prefix_steps": PREFIX_STEPS,
            "scientific_seed_bundles": 0,
            "behavioral_inference": false,
            "dh08b_authorized": false
        }),
    )
}

fn verify_seal(root: &Path) -> Result<Value> {
    let seal: Value = serde_json::from_reader(File::open(root.join("PREEXECUTION.json"))?)?;
    ensure!(seal["protocol"] == PROTOCOL);
    ensure!(seal["status"] == "FROZEN_PRE_EXECUTION");
    ensure!(seal["source_manifest"] == serde_json::to_value(source_manifest(root)?)?);
    let executable = std::env::current_exe()?;
    let executable_hash = hash_bytes(&std::fs::read(executable)?);
    ensure!(
        seal["executable_sha256"]
            .as_str()
            .is_some_and(|value| value.eq_ignore_ascii_case(&executable_hash))
    );
    Ok(seal)
}

fn validate(config: &Config) -> Result<()> {
    ensure!(config.protocol == PROTOCOL);
    ensure!(config.seeds == SEEDS && config.taus == TAUS);
    ensure!(config.sides == SIDES.iter().map(|side| (*side).to_owned()).collect::<Vec<_>>());
    ensure!(config.trials == SAMPLE_TRIALS && config.observe);
    ensure!(config.cues == 16 && config.delay_steps == 12 && config.total_trials == 512);
    ensure!(config.eta == 0.05 && config.glut_sign == -1.0);
    ensure!(config.input_salt == 858980352 && config.threads == 1);
    Ok(())
}

fn mix(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

fn shared_count(a: &[usize], b: &[usize]) -> usize {
    let (mut i, mut j, mut count) = (0, 0, 0);
    while i < a.len() && j < b.len() {
        match a[i].cmp(&b[j]) {
            std::cmp::Ordering::Less => i += 1,
            std::cmp::Ordering::Greater => j += 1,
            std::cmp::Ordering::Equal => {
                count += 1;
                i += 1;
                j += 1;
            }
        }
    }
    count
}

fn shared_three(a: &[usize], b: &[usize], c: &[usize]) -> usize {
    a.iter()
        .filter(|row| b.binary_search(row).is_ok() && c.binary_search(row).is_ok())
        .count()
}

fn select_triples(
    coords: &[usize],
    rows: &[Vec<usize>],
    seed: u64,
    tau: f32,
    trial: usize,
) -> (Vec<TripleCandidate>, Vec<TripleCandidate>) {
    let mut shared = Vec::with_capacity(BLOCKS_PER_CATEGORY);
    let mut disjoint = Vec::with_capacity(BLOCKS_PER_CATEGORY);
    let mut attempt = 0_u64;
    let key_base = seed ^ u64::from(tau.to_bits()) ^ trial as u64;
    while (shared.len() < BLOCKS_PER_CATEGORY || disjoint.len() < BLOCKS_PER_CATEGORY)
        && attempt < 500_000
    {
        let a = (mix(key_base ^ attempt) as usize) % coords.len();
        let b = (mix(key_base ^ attempt.wrapping_add(1)) as usize) % coords.len();
        let c = (mix(key_base ^ attempt.wrapping_add(2)) as usize) % coords.len();
        attempt += 3;
        if a == b || a == c || b == c {
            continue;
        }
        let mut ids = [coords[a], coords[b], coords[c]];
        ids.sort_unstable();
        if rows[ids[0]].is_empty() || rows[ids[1]].is_empty() || rows[ids[2]].is_empty() {
            continue;
        }
        let ab = shared_count(&rows[ids[0]], &rows[ids[1]]);
        let ac = shared_count(&rows[ids[0]], &rows[ids[2]]);
        let bc = shared_count(&rows[ids[1]], &rows[ids[2]]);
        let abc = shared_three(&rows[ids[0]], &rows[ids[1]], &rows[ids[2]]);
        let seen = |items: &[TripleCandidate]| {
            items.iter().any(|candidate| {
                candidate.0 == ids[0] && candidate.1 == ids[1] && candidate.2 == ids[2]
            })
        };
        if abc > 0 && shared.len() < BLOCKS_PER_CATEGORY && !seen(&shared) {
            shared.push((ids[0], ids[1], ids[2], abc));
        }
        if ab == 0
            && ac == 0
            && bc == 0
            && disjoint.len() < BLOCKS_PER_CATEGORY
            && !seen(&disjoint)
        {
            disjoint.push((ids[0], ids[1], ids[2], 0));
        }
    }
    (shared, disjoint)
}

fn replacements(weights: &[f32], coordinate: usize, downward: bool) -> Option<Vec<f32>> {
    let mut value = weights[coordinate];
    let mut out = Vec::with_capacity(PREFIX_STEPS.len());
    let mut previous = 0;
    for &step in &PREFIX_STEPS {
        for _ in previous..step {
            value = readout::nextafter32(value, downward)?;
        }
        previous = step;
        if !value.is_finite()
            || value <= 0.0
            || value >= 2.0
            || readout::interior_steps(value, true, bank::FINAL_RESERVE)
                < bank::FINAL_RESERVE
            || readout::interior_steps(value, false, bank::FINAL_RESERVE)
                < bank::FINAL_RESERVE
        {
            return None;
        }
        out.push(value);
    }
    Some(out)
}

fn norm(values: &[f64]) -> f64 {
    values.iter().map(|value| value * value).sum::<f64>().sqrt()
}

fn changed(weights: &[f32], coordinates: [usize; 3], values: [f32; 3]) -> Vec<f32> {
    let mut out = weights.to_vec();
    out[coordinates[0]] = values[0];
    out[coordinates[1]] = values[1];
    out[coordinates[2]] = values[2];
    out
}

fn analyze_block(
    op: &DriveOperator,
    weights: &[f32],
    target: &[f32],
    base_error_norm: f64,
    candidate: TripleCandidate,
    category: &'static str,
    context: &BlockContext,
) -> Result<BlockResult> {
    let coordinates = [candidate.0, candidate.1, candidate.2];
    let key = mix(
        context.seed
            ^ u64::from(context.tau.to_bits())
            ^ context.trial as u64
            ^ (candidate.0 as u64).wrapping_mul(0x9e37_79b1)
            ^ (candidate.1 as u64).wrapping_mul(0xbf58_476d)
            ^ (candidate.2 as u64).wrapping_mul(0x94d0_49bb),
    );
    let downward = [(key & 1) == 0, (key & 2) == 0, (key & 4) == 0];
    let values = [
        replacements(weights, coordinates[0], downward[0]),
        replacements(weights, coordinates[1], downward[1]),
        replacements(weights, coordinates[2], downward[2]),
    ];
    ensure!(values.iter().all(Option::is_some), "block lacks legal prefix endpoints");
    let values = [
        values[0].as_ref().expect("checked endpoint"),
        values[1].as_ref().expect("checked endpoint"),
        values[2].as_ref().expect("checked endpoint"),
    ];
    let mut best_residual_norm = f64::INFINITY;
    let mut best_steps = [0; 3];
    let mut best_bitwise_mismatch_count = usize::MAX;
    let mut candidate_count = 0;
    for a in 0..PREFIX_STEPS.len() {
        for b in 0..PREFIX_STEPS.len() {
            for c in 0..PREFIX_STEPS.len() {
                let endpoint = changed(
                    weights,
                    coordinates,
                    [values[0][a], values[1][b], values[2][c]],
                );
                let replay = op.sequential(&endpoint);
                let residual: Vec<f64> = replay
                    .iter()
                    .zip(target)
                    .map(|(&value, &goal)| f64::from(value) - f64::from(goal))
                    .collect();
                let residual_norm = norm(&residual);
                let mismatch_count = replay
                    .iter()
                    .zip(target)
                    .filter(|(value, goal)| value.to_bits() != goal.to_bits())
                    .count();
                candidate_count += 1;
                if residual_norm < best_residual_norm
                    || (residual_norm == best_residual_norm
                        && mismatch_count < best_bitwise_mismatch_count)
                {
                    best_residual_norm = residual_norm;
                    best_steps = [PREFIX_STEPS[a], PREFIX_STEPS[b], PREFIX_STEPS[c]];
                    best_bitwise_mismatch_count = mismatch_count;
                }
            }
        }
    }
    ensure!(candidate_count == 125);
    let ratio = best_residual_norm / base_error_norm.max(1.0e-12);
    Ok(BlockResult {
        category,
        coordinate_a: coordinates[0],
        coordinate_b: coordinates[1],
        coordinate_c: coordinates[2],
        shared_rows: candidate.3,
        direction_a: if downward[0] { "down" } else { "up" },
        direction_b: if downward[1] { "down" } else { "up" },
        direction_c: if downward[2] { "down" } else { "up" },
        candidate_count,
        base_error_norm,
        best_residual_norm,
        best_residual_ratio: ratio,
        residual_reduction: (1.0 - ratio).max(0.0),
        best_bitwise_mismatch_count,
        best_steps,
    })
}

fn analyze_event(
    op: &DriveOperator,
    snapshot: &crate::capture::Snapshot,
    seed: u64,
    side: &str,
    tau: f32,
) -> Result<EventResult> {
    let parent = q10::analyze_event(op, snapshot, seed ^ u64::from(tau.to_bits()) ^ snapshot.trial as u64)?;
    if parent.event.status != "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT" {
        return Ok(EventResult {
            seed,
            side: side.to_owned(),
            tau,
            trial: snapshot.trial,
            parent_status: parent.event.status,
            status: "PARENT_CONSTRUCTOR_INELIGIBLE",
            initial_mismatch_count: 0,
            base_error_norm: 0.0,
            block_count: 0,
            shared_block_count: 0,
            disjoint_block_count: 0,
            best_shared_residual_ratio: 0.0,
            best_disjoint_residual_ratio: 0.0,
            blocks: Vec::new(),
        });
    }
    let weights = parent.committed_alternate(snapshot);
    let actual = readout::sequential(op, &weights);
    let target = readout::sequential(op, &snapshot.target);
    let base_error: Vec<f64> = actual
        .iter()
        .zip(&target)
        .map(|(&value, &goal)| f64::from(value) - f64::from(goal))
        .collect();
    let base_error_norm = norm(&base_error);
    let coordinate_rows = bank::coordinate_rows(op);
    let coordinates: Vec<usize> = parent
        .interior_indices
        .iter()
        .copied()
        .filter(|&coordinate| !coordinate_rows[coordinate].is_empty())
        .collect();
    ensure!(!coordinates.is_empty(), "empty eligible coordinate set");
    let (shared, disjoint) = select_triples(&coordinates, &coordinate_rows, seed, tau, snapshot.trial);
    let context = BlockContext { seed, tau, trial: snapshot.trial };
    let mut blocks = Vec::with_capacity(shared.len() + disjoint.len());
    for candidate in shared {
        blocks.push(analyze_block(
            op,
            &weights,
            &target,
            base_error_norm,
            candidate,
            "shared",
            &context,
        )?);
    }
    for candidate in disjoint {
        blocks.push(analyze_block(
            op,
            &weights,
            &target,
            base_error_norm,
            candidate,
            "disjoint",
            &context,
        )?);
    }
    let shared_block_count = blocks.iter().filter(|block| block.category == "shared").count();
    let disjoint_block_count = blocks.iter().filter(|block| block.category == "disjoint").count();
    let best_shared_residual_ratio = blocks
        .iter()
        .filter(|block| block.category == "shared")
        .map(|block| block.best_residual_ratio)
        .fold(f64::INFINITY, f64::min);
    let best_disjoint_residual_ratio = blocks
        .iter()
        .filter(|block| block.category == "disjoint")
        .map(|block| block.best_residual_ratio)
        .fold(f64::INFINITY, f64::min);
    let status = if shared_block_count == BLOCKS_PER_CATEGORY
        && disjoint_block_count == BLOCKS_PER_CATEGORY
    {
        "BLOCK_ORDER_AUDIT_COMPLETE"
    } else {
        "BLOCK_CAPACITY_PARTIAL"
    };
    Ok(EventResult {
        seed,
        side: side.to_owned(),
        tau,
        trial: snapshot.trial,
        parent_status: parent.event.status,
        status,
        initial_mismatch_count: actual
            .iter()
            .zip(&target)
            .filter(|(value, goal)| value.to_bits() != goal.to_bits())
            .count(),
        base_error_norm,
        block_count: blocks.len(),
        shared_block_count,
        disjoint_block_count,
        best_shared_residual_ratio,
        best_disjoint_residual_ratio,
        blocks,
    })
}

fn run(args: &[String], root: &Path) -> Result<()> {
    ensure!(args.len() == 4, "usage: q10-jbr CONFIG ANATOMY OUTPUT");
    verify_parent(root)?;
    contract_and_plan(root)?;
    let seal = verify_seal(root)?;
    let config: Config = serde_json::from_reader(File::open(&args[1])?)?;
    validate(&config)?;
    let expected = root.join("qualification/sample-9691-9692");
    let out = root.join(&args[3]);
    ensure!(out == expected, "noncanonical Q10-JBR output path");
    std::fs::create_dir_all(&out)?;
    write_json(&out.join("pre-execution.json"), &seal)?;
    let mut total = 0;
    for &seed in SEEDS {
        for side in SIDES {
            for &tau in TAUS {
                let graph = Graph::load(Path::new(&args[2]), side, config.glut_sign)?;
                let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733);
                ensure!(rewire.accepted > 0 && rewire.degree_preserved);
                let task = Task::new(&graph, seed ^ config.input_salt, 16, 12, 512);
                let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())?;
                let mut sim = Simulator::new(&graph, &graph.route, seed, tau, config.eta, "E");
                sim.capture = Some(crate::capture::Capture::new(sim.weights.len()));
                sim.policy = Some(Policy::new(sim.weights.len()));
                let run = sim
                    .run_dh07(&task, Dh07Condition::TruePerpendicular, &shuffled, config.observe, 0)
                    .context("Q10-JBR frozen engineering simulation")?;
                ensure!(run.result.outcome.hot_allocations == 0);
                let policy = sim.policy.take().context("missing Q10-JBR policy capture")?;
                ensure!(policy.count == 256);
                let selected = policy.snapshots[..policy.count]
                    .iter()
                    .filter(|snapshot| SAMPLE_TRIALS.contains(&snapshot.trial))
                    .collect::<Vec<_>>();
                ensure!(selected.len() == SAMPLE_TRIALS.len());
                let analyzed = selected
                    .iter()
                    .map(|snapshot| analyze_event(&op, snapshot, seed, side, tau))
                    .collect::<Result<Vec<_>>>()?;
                total += analyzed.len();
                write_json(
                    &out.join(format!("seed{seed}-{side}-tau{tau}.json")),
                    &json!({
                        "protocol": PROTOCOL,
                        "seed": seed,
                        "side": side,
                        "tau": tau,
                        "events": analyzed,
                        "scientific_seed_bundles": 0,
                        "behavioral_inference": false,
                        "dh08b_authorized": false
                    }),
                )?;
                println!("Q10-JBR1 complete seed={seed} side={side} tau={tau}");
            }
        }
    }
    ensure!(total == 8);
    write_json(
        &out.join("execution.json"),
        &json!({
            "protocol": PROTOCOL,
            "complete": true,
            "audited_events": total,
            "blocks_per_event": BLOCKS_PER_CATEGORY * 2,
            "joint_candidates_per_block": PREFIX_STEPS.len().pow(3),
            "scientific_seed_bundles": 0,
            "behavioral_inference": false,
            "dh08b_authorized": false
        }),
    )?;
    Ok(())
}

pub fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    if args.len() == 2 && args[1] == "seal" {
        seal(root)
    } else {
        run(&args, root)
    }
}
