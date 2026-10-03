use crate::{
    capture::Snapshot,
    graph::Graph,
    linear::DriveOperator,
    pi_core,
    pi_types::{self, EventFailure, OverlayEvent, OverlayFixtureEvent, OverlayFixtureFile,
        PairMapFile, ReplayFixtureEvent, ReplayFixtureFile},
    policy::Policy,
    q10,
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

const PROTOCOL: &str = "Q10-PI1";
const SEEDS: &[u64] = &[9721, 9722];
const TAUS: &[f32] = &[4.0, 16.0];
const SIDES: &[&str] = &["R", "L"];
const TRIAL: usize = 128;
const PARENT_PLAN: &str = "8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D";
const PARENT_CONTRACT: &str = "5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF";
const PARENT_RESULT: &str = "68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337";
const PARENT_STATUS: &str = "D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4";
const CANONICAL_ANATOMY_REL: &str = "dh06/artifacts/runs/20260915T201008Z/sealed/anatomy";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    protocol: String,
    seeds: Vec<u64>,
    sides: Vec<String>,
    taus: Vec<f32>,
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

#[derive(Clone)]
struct EventContext {
    fixture: ReplayFixtureEvent,
    target_committed_bits: Vec<u32>,
    target_readout_bits: Vec<u32>,
    eligible_coordinates: Vec<usize>,
    parent_status: String,
}

fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.flush()?;
    Ok(())
}

fn json_bytes(value: &impl Serialize) -> Result<Vec<u8>> {
    let mut bytes = serde_json::to_vec_pretty(value)?;
    bytes.push(b'\n');
    Ok(bytes)
}

fn write_json_new(path: &Path, value: &impl Serialize) -> Result<Vec<u8>> {
    let bytes = json_bytes(value)?;
    write_new(path, &bytes)?;
    Ok(bytes)
}

fn visit_files(root: &Path, dir: &Path, paths: &mut Vec<PathBuf>) -> Result<()> {
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
        PathBuf::from("q10-pi-config.json"),
        PathBuf::from("scripts/review_q10_pi.py"),
    ];
    visit_files(root, &root.join("src"), &mut paths)?;
    paths.sort();
    paths.dedup();
    paths.into_iter()
        .map(|path| Ok(json!({"path": path, "sha256": hash_bytes(&std::fs::read(root.join(&path))?)})))
        .collect()
}

fn anatomy_manifest(root: &Path) -> Result<Vec<Value>> {
    let mut paths = Vec::new();
    visit_files(root, root, &mut paths)?;
    paths.sort();
    paths.into_iter()
        .map(|path| {
            let relative = path.to_string_lossy().replace('\\', "/");
            Ok(json!({"path": relative, "sha256": hash_bytes(&std::fs::read(root.join(&path))?)}))
        })
        .collect()
}

fn canonical_anatomy(root: &Path) -> Result<PathBuf> {
    Ok(std::fs::canonicalize(root.parent().context("missing experiment parent")?.join(CANONICAL_ANATOMY_REL))?)
}

fn verify_parent(root: &Path) -> Result<()> {
    let parent = root.parent().context("missing experiment parent")?.join("q10-safety-margin-v1");
    for (name, expected) in [("PLAN.md", PARENT_PLAN), ("CONTRACT.json", PARENT_CONTRACT),
        ("RESULT.md", PARENT_RESULT), ("STATUS.json", PARENT_STATUS)] {
        ensure!(hash_bytes(&std::fs::read(parent.join(name))?).eq_ignore_ascii_case(expected), "parent {name} hash mismatch");
    }
    let status: Value = serde_json::from_reader(File::open(parent.join("STATUS.json"))?)?;
    ensure!(status["scientific_seed_bundles_used"] == 0 && status["future_dh08b_authorized"] == false);
    Ok(())
}

fn contract_hashes(root: &Path) -> Result<(String, String)> {
    let plan = hash_bytes(&std::fs::read(root.join("PLAN.md"))?);
    let contract_bytes = std::fs::read(root.join("CONTRACT.json"))?;
    let contract: Value = serde_json::from_slice(&contract_bytes)?;
    ensure!(contract["protocol"] == PROTOCOL);
    ensure!(contract["plan_sha256"].as_str().is_some_and(|value| value.eq_ignore_ascii_case(&plan)));
    Ok((plan, hash_bytes(&contract_bytes)))
}

fn seal(root: &Path) -> Result<()> {
    verify_parent(root)?;
    let (plan, contract) = contract_hashes(root)?;
    let anatomy = canonical_anatomy(root)?;
    let executable = std::env::current_exe()?;
    let seal = json!({
        "protocol": PROTOCOL,
        "status": "FROZEN_PRE_EXECUTION",
        "source_manifest": source_manifest(root)?,
        "executable": executable,
        "executable_sha256": hash_bytes(&std::fs::read(&executable)?),
        "plan_sha256": plan,
        "contract_sha256": contract,
        "canonical_anatomy_dir": anatomy,
        "anatomy_manifest": anatomy_manifest(&anatomy)?,
        "parent_hashes": {"plan": PARENT_PLAN, "contract": PARENT_CONTRACT, "result": PARENT_RESULT, "status": PARENT_STATUS},
        "shared_pairs_per_event": pi_types::SHARED_PAIRS_PER_EVENT,
        "disjoint_pairs_per_event": pi_types::DISJOINT_PAIRS_PER_EVENT,
        "signed_steps": pi_types::SIGNED_STEPS,
        "target_blind_map_before_overlay": true,
        "scientific_seed_bundles": 0,
        "behavioral_inference": false,
        "dh08b_authorized": false
    });
    write_json_new(&root.join("PREEXECUTION.json"), &seal)?;
    Ok(())
}

fn verify_seal(root: &Path) -> Result<Value> {
    let seal: Value = serde_json::from_reader(File::open(root.join("PREEXECUTION.json"))?)?;
    ensure!(seal["protocol"] == PROTOCOL && seal["status"] == "FROZEN_PRE_EXECUTION");
    ensure!(seal["source_manifest"] == serde_json::to_value(source_manifest(root)?)?);
    let anatomy = canonical_anatomy(root)?;
    ensure!(seal["canonical_anatomy_dir"] == serde_json::to_value(&anatomy)?);
    ensure!(seal["anatomy_manifest"] == serde_json::to_value(anatomy_manifest(&anatomy)?)?);
    let executable = std::env::current_exe()?;
    let executable_hash = hash_bytes(&std::fs::read(executable)?);
    ensure!(seal["executable_sha256"].as_str().is_some_and(|v| v.eq_ignore_ascii_case(&executable_hash)));
    Ok(seal)
}

fn validate(config: &Config) -> Result<()> {
    ensure!(config.protocol == PROTOCOL && config.seeds == SEEDS && config.taus == TAUS);
    ensure!(config.sides == SIDES.iter().map(|x| (*x).to_owned()).collect::<Vec<_>>() && config.trials == [TRIAL]);
    ensure!(config.observe && config.cues == 16 && config.delay_steps == 12 && config.total_trials == 512);
    ensure!(config.eta == 0.05 && config.glut_sign == -1.0 && config.input_salt == 858980352 && config.threads == 1);
    Ok(())
}

fn bits(values: &[f32]) -> Vec<u32> { values.iter().map(|value| value.to_bits()).collect() }

fn event_context(operator: &DriveOperator, snapshot: &Snapshot, seed: u64, side: &str, tau: f32) -> Result<EventContext> {
    let parent = q10::analyze_event(operator, snapshot, seed ^ u64::from(tau.to_bits()) ^ snapshot.trial as u64)?;
    let key = format!("seed{seed}-{side}-tau{tau}-trial{}", snapshot.trial);
    let initial = parent.committed_alternate(snapshot);
    let fixture = pi_core::fixture_event(key.clone(), seed, side, tau, snapshot.trial,
        operator.rows.iter().map(|row| row.iter().map(|&id| id as u32).collect()).collect(), bits(&initial));
    let target = bits(&snapshot.target);
    let target_readout = pi_core::full_readout(&operator.rows.iter().map(|row| row.iter().map(|&id| id as u32).collect()).collect::<Vec<Vec<u32>>>(), &snapshot.target);
    let target_readout_bits = target_readout.iter().map(|value| value.to_bits()).collect();
    let eligible = parent.interior_indices.iter().copied().filter(|&i| operator.rows.iter().any(|row| row.contains(&i))).collect();
    Ok(EventContext { fixture, target_committed_bits: target, target_readout_bits, eligible_coordinates: eligible, parent_status: parent.event.status.to_owned() })
}

fn run(args: &[String], root: &Path) -> Result<()> {
    ensure!(args.len() == 4, "usage: q10-pair-interaction CONFIG ANATOMY OUTPUT");
    verify_parent(root)?;
    let seal = verify_seal(root)?;
    let config: Config = serde_json::from_reader(File::open(&args[1])?)?;
    validate(&config)?;
    let anatomy = canonical_anatomy(root)?;
    ensure!(std::fs::canonicalize(&args[2])? == anatomy, "anatomy path is not the sealed canonical input");
    let output = root.join("qualification/sample-9721-9722");
    ensure!(Path::new(&args[3]) == Path::new("qualification/sample-9721-9722") || std::fs::canonicalize(&args[3]).unwrap_or_default() == output, "noncanonical output");
    std::fs::create_dir_all(&output)?;
    write_json_new(&output.join("pre-execution.json"), &seal)?;
    let mut contexts = Vec::new();
    let mut failures = Vec::new();
    for &seed in SEEDS {
        for side in SIDES {
            for &tau in TAUS {
                let graph = Graph::load(&anatomy, side, config.glut_sign)?;
                let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733);
                ensure!(rewire.accepted > 0 && rewire.degree_preserved);
                let task = Task::new(&graph, seed ^ config.input_salt, 16, 12, 512);
                let operator = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())?;
                let mut simulator = Simulator::new(&graph, &graph.route, seed, tau, config.eta, "E");
                simulator.capture = Some(crate::capture::Capture::new(simulator.weights.len()));
                simulator.policy = Some(Policy::new(simulator.weights.len()));
                let run = simulator.run_dh07(&task, Dh07Condition::TruePerpendicular, &shuffled, config.observe, 0)?;
                ensure!(run.result.outcome.hot_allocations == 0);
                let policy = simulator.policy.take().context("missing policy")?;
                let snapshot = policy.snapshots[..policy.count].iter().find(|s| s.trial == TRIAL).context("missing trial")?;
                let parent = q10::analyze_event(&operator, snapshot, seed ^ u64::from(tau.to_bits()) ^ TRIAL as u64)?;
                if parent.event.status != "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT" {
                    failures.push(EventFailure { event_key: format!("seed{seed}-{side}-tau{tau}-trial{TRIAL}"), seed, side: (*side).to_owned(), tau, trial: TRIAL, status: "PARENT_CONSTRUCTOR_INELIGIBLE".to_owned(), parent_status: Some(parent.event.status.to_owned()), baseline_readout_l2: None, reason: "parent Q10-SM event unavailable; no resampling".to_owned() });
                } else {
                    contexts.push(event_context(&operator, snapshot, seed, side, tau)?);
                }
            }
        }
    }
    ensure!(contexts.len() + failures.len() == 8);
    let fixture_file = ReplayFixtureFile { protocol: PROTOCOL.to_owned(), schema_version: 1, events: contexts.iter().map(|c| c.fixture.clone()).collect() };
    let fixture_bytes = write_json_new(&output.join("replay-fixture.json"), &fixture_file)?;
    let mut maps = Vec::new();
    for context in &contexts {
        let map = pi_core::build_event_map(pi_types::MapInput { fixture: &context.fixture, eligible_coordinates: &context.eligible_coordinates, shared_pair_count: pi_types::SHARED_PAIRS_PER_EVENT, disjoint_pair_count: pi_types::DISJOINT_PAIRS_PER_EVENT })?;
        pi_core::assert_full_oracle_parity(&context.fixture)?;
        pi_core::assert_representative_pair_parity(&context.fixture, &map)?;
        maps.push(map);
    }
    let map_file = PairMapFile { protocol: PROTOCOL.to_owned(), schema_version: 1, normalization_floor: pi_types::NORMALIZATION_FLOOR, signed_steps: pi_types::SIGNED_STEPS.to_vec(), fixture_sha256: hash_bytes(&fixture_bytes), events: maps.clone(), failures: failures.clone() };
    let map_bytes = write_json_new(&output.join("pair-map.json"), &map_file)?;
    let _map_hash = hash_bytes(&map_bytes);
    let overlays_fixture = OverlayFixtureFile { protocol: PROTOCOL.to_owned(), schema_version: 1, events: contexts.iter().map(|c| OverlayFixtureEvent { event_key: c.fixture.event_key.clone(), target_committed_bits: c.target_committed_bits.clone(), target_readout_bits: c.target_readout_bits.clone() }).collect() };
    write_json_new(&output.join("overlay-fixture.json"), &overlays_fixture)?;
    let mut overlays: Vec<OverlayEvent> = Vec::new();
    for (map, context) in maps.iter().zip(&contexts) {
        overlays.push(pi_core::overlay_event(pi_types::OverlayInput { map, fixture: &context.fixture, target_readout_bits: &context.target_readout_bits })?);
    }
    write_json_new(&output.join("overlay-results.json"), &json!({"protocol": PROTOCOL, "map_sha256": hash_bytes(&map_bytes), "events": overlays}))?;
    write_json_new(&output.join("execution.json"), &json!({"protocol": PROTOCOL, "complete": true, "declared_events": 8, "available_events": contexts.len(), "unavailable_events": failures.len(), "map_before_overlay": true, "scientific_seed_bundles": 0, "behavioral_inference": false, "dh08b_authorized": false}))?;
    Ok(())
}

pub fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    if args.len() == 2 && args[1] == "seal" { seal(root) } else { run(&args, root) }
}
