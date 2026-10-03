mod bank;
mod capacity;
mod gates;
mod readout;
mod repair;

use crate::{
    graph::Graph,
    linear::DriveOperator,
    policy::Policy,
    q10,
    simulation::{Dh07Condition, Simulator},
    task::Task,
};
use anyhow::{Context, Result, ensure};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
};

const PROTOCOL: &str = "Q10-SR4";
const SEED_A: &[u64] = &[9531];
const SEEDS_B: &[u64] = &[9532, 9533, 9534, 9535];
const STAGE_A_STATES: usize = 1024;
const STAGE_B_STATES: usize = 4096;
const PARENT_PLAN: &str = "8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D";
const PARENT_CONTRACT: &str = "5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF";
const PARENT_RESULT: &str = "68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337";
const PARENT_STATUS: &str = "D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    stage: String,
    observe: bool,
    seeds: Vec<u64>,
    taus: Vec<f32>,
    sides: Vec<String>,
    conditions: Vec<String>,
    arms: Vec<String>,
    cues: usize,
    delay_steps: usize,
    trials: usize,
    eta: f32,
    glut_sign: f32,
    input_salt: u64,
    threads: usize,
    candidate_directions: usize,
    angle_bisections: usize,
    reserve_ulps: u32,
    final_reserve_ulps: u32,
    beam_width: usize,
    branch_width: usize,
    maximum_moves: usize,
    maximum_moves_per_coordinate: usize,
}

fn validate_config(config: &Config) -> Result<&'static [u64]> {
    ensure!(config.stage == "stage1-a" || config.stage == "stage1-b");
    let seeds = if config.stage == "stage1-a" {
        SEED_A
    } else {
        SEEDS_B
    };
    ensure!(
        config.seeds == seeds,
        "unauthorized Q10-SR4 engineering seeds"
    );
    ensure!(config.observe && config.taus == [4.0, 16.0] && config.sides == ["R", "L"]);
    ensure!(config.conditions == ["true_perpendicular"] && config.arms == ["E", "Z"]);
    ensure!(config.cues == 16 && config.delay_steps == 12 && config.trials == 512);
    ensure!(config.eta == 0.05 && config.glut_sign == -1.0 && config.input_salt == 858980352);
    ensure!(config.threads == 8);
    ensure!(config.candidate_directions == 8 && config.angle_bisections == 32);
    ensure!(config.reserve_ulps == 32 && config.final_reserve_ulps == 16);
    ensure!(config.beam_width == 64 && config.branch_width == 64);
    ensure!(config.maximum_moves == 64 && config.maximum_moves_per_coordinate == 16);
    Ok(seeds)
}

fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn hash_f32(values: &[f32]) -> String {
    let mut hasher = Sha256::new();
    for value in values {
        hasher.update(value.to_bits().to_le_bytes());
    }
    format!("{:x}", hasher.finalize())
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let mut writer = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(path)?);
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
        PathBuf::from("stage1-a-config.json"),
        PathBuf::from("stage1-b-config.json"),
    ];
    visit_files(root, &root.join("src"), &mut paths)?;
    paths.push(PathBuf::from("scripts/review_q10_sr.py"));
    paths.sort();
    paths.dedup();
    paths
        .iter()
        .map(|path| {
            Ok(json!({
                "path":path,
                "sha256":hash_bytes(&std::fs::read(root.join(path))?)
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
        let actual = hash_bytes(&std::fs::read(parent.join(name))?);
        ensure!(
            actual.eq_ignore_ascii_case(expected),
            "Q10-SM {name} lineage mismatch"
        );
    }
    let status: Value = serde_json::from_reader(File::open(parent.join("STATUS.json"))?)?;
    ensure!(status["status"] == "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT");
    ensure!(status["cumulative_audited_states"] == 5120);
    ensure!(status["accepted_nonidentity_events"] == 5026);
    ensure!(status["scientific_seed_bundles_used"] == 0);
    ensure!(status["sequential_f32_readout"] == "NOT_RUN");
    ensure!(status["ulp_repair"] == "NOT_RUN");
    ensure!(status["future_dh08b_authorized"] == false);
    Ok(())
}

fn contract_and_plan(root: &Path) -> Result<(String, String)> {
    let plan_hash = hash_bytes(&std::fs::read(root.join("PLAN.md"))?);
    let contract_hash = hash_bytes(&std::fs::read(root.join("CONTRACT.json"))?);
    let contract: Value = serde_json::from_reader(File::open(root.join("CONTRACT.json"))?)?;
    ensure!(contract["protocol"] == PROTOCOL);
    ensure!(
        contract["plan_sha256"]
            .as_str()
            .is_some_and(|value| value.eq_ignore_ascii_case(&plan_hash))
    );
    Ok((plan_hash, contract_hash))
}

fn seal(root: &Path) -> Result<()> {
    verify_parent(root)?;
    let (plan_hash, contract_hash) = contract_and_plan(root)?;
    let executable = std::env::current_exe()?;
    write_json(
        &root.join("PREEXECUTION.json"),
        &json!({
            "protocol":PROTOCOL,
            "status":"FROZEN_PRE_EXECUTION",
            "source_manifest":source_manifest(root)?,
            "executable":executable,
            "executable_sha256":hash_bytes(&std::fs::read(&executable)?),
            "plan_sha256":plan_hash,
            "contract_sha256":contract_hash,
            "parent_hashes":{"plan":PARENT_PLAN,"contract":PARENT_CONTRACT,"result":PARENT_RESULT,"status":PARENT_STATUS},
            "production_readout":"DriveOperator::sequential using canonical rows and f32 Iterator::sum",
            "arithmetic":{"ordered_key":"negative=!bits; nonnegative=bits xor 0x80000000","nextafter32":"adjacent IEEE-754 binary32","nonfinite":"fail_closed"},
            "capacity":{"factorization":"sparse-effect Gram matrix with deterministic f64 symmetric eigendecomposition","rank_multiplier":1000.0,"projection_tolerance":2.0e-10,"coefficient_resolution":1.0e-12},
            "search":{"beam_width":64,"branch_width":64,"maximum_moves":64,"maximum_coordinate_steps":16,"minimum_final_reserve":16},
            "final_tolerances":{"cue":2.0e-6,"axis":2.0e-6,"norm":2.0e-7},
            "scientific_seeds":0,"behavior":false,"dh08b":false
        }),
    )
}

fn verify_seal(root: &Path) -> Result<Value> {
    let seal: Value = serde_json::from_reader(File::open(root.join("PREEXECUTION.json"))?)?;
    ensure!(seal["protocol"] == PROTOCOL && seal["status"] == "FROZEN_PRE_EXECUTION");
    ensure!(seal["source_manifest"] == serde_json::to_value(source_manifest(root)?)?);
    let executable = std::env::current_exe()?;
    ensure!(seal["executable_sha256"].as_str().is_some_and(|value| {
        value.eq_ignore_ascii_case(&hash_bytes(&std::fs::read(executable).unwrap_or_default()))
    }));
    Ok(seal)
}

#[derive(Serialize)]
struct EventReceipt {
    trial: usize,
    parent_status: &'static str,
    mismatch_status: &'static str,
    initial_mismatch: Option<readout::Mismatch>,
    bank: Option<bank::BankDiagnostics>,
    capacity: Option<capacity::Capacity>,
    search: Option<repair::SearchDiagnostics>,
    final_gates: Option<gates::FinalGates>,
    repair_status: &'static str,
    initial_alternate_sha256: Option<String>,
    final_weights_sha256: Option<String>,
    target_readout_sha256: Option<String>,
    final_readout_sha256: Option<String>,
}

#[derive(Serialize)]
struct Replay<'a> {
    snapshot: &'a crate::capture::Snapshot,
    operator: &'a DriveOperator,
    interior_indices: &'a [usize],
    true_displacement: &'a [f64],
    initial_alternate: &'a [f32],
    target_readout: &'a [f32],
    final_weights: Option<&'a [f32]>,
    final_readout: Option<&'a [f32]>,
    path: &'a [repair::AppliedMove],
    receipt: &'a EventReceipt,
}

struct Analyzed {
    receipt: EventReceipt,
    interior: Vec<usize>,
    true_displacement: Vec<f64>,
    initial_alternate: Vec<f32>,
    target_readout: Vec<f32>,
    final_weights: Option<Vec<f32>>,
    final_readout: Option<Vec<f32>>,
    path: Vec<repair::AppliedMove>,
}

fn analyze_event(
    op: &DriveOperator,
    snapshot: &crate::capture::Snapshot,
    key: u64,
) -> Result<Analyzed> {
    let parent = q10::analyze_event(op, snapshot, key)?;
    let parent_status = parent.event.status;
    if parent_status != "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT" {
        return Ok(Analyzed {
            receipt: EventReceipt {
                trial: snapshot.trial,
                parent_status,
                mismatch_status: "NOT_ENTERED_PARENT_CONSTRUCTOR_INELIGIBLE",
                initial_mismatch: None,
                bank: None,
                capacity: None,
                search: None,
                final_gates: None,
                repair_status: "PARENT_CONSTRUCTOR_INELIGIBLE",
                initial_alternate_sha256: None,
                final_weights_sha256: None,
                target_readout_sha256: None,
                final_readout_sha256: None,
            },
            interior: parent.interior_indices,
            true_displacement: parent.true_displacement,
            initial_alternate: Vec::new(),
            target_readout: Vec::new(),
            final_weights: None,
            final_readout: None,
            path: Vec::new(),
        });
    }
    let initial = parent.committed_alternate(snapshot);
    let target_readout = readout::sequential(op, &snapshot.target);
    let initial_readout = readout::sequential(op, &initial);
    let initial_mismatch = readout::mismatch(op, &initial_readout, &target_readout)?;
    let mismatch_status = if initial_mismatch.bitwise_mismatch_count == 0 {
        "READOUT_ALREADY_EQUAL"
    } else {
        "READOUT_MISMATCHED"
    };
    let (bank_diagnostics, capacity_diagnostics) = if initial_mismatch.bitwise_mismatch_count == 0 {
        (None, None)
    } else {
        let move_bank = bank::build(op, &initial, &initial_readout, &parent.interior_indices)?;
        let capacity = capacity::analyze(&move_bank.moves, &initial_readout, &target_readout)?;
        (Some(move_bank.diagnostics), Some(capacity))
    };
    let capacity_status = capacity_diagnostics.as_ref().map(|value| value.status);
    let search = if initial_mismatch.bitwise_mismatch_count == 0
        || capacity_status != Some("CAPACITY_EXACT_WITHIN_TOLERANCE")
    {
        None
    } else {
        Some(repair::search(
            op,
            &initial,
            &initial_readout,
            &target_readout,
            &parent.interior_indices,
        )?)
    };
    let path = search
        .as_ref()
        .map_or_else(Vec::new, |value| value.diagnostics.path.clone());
    let (final_weights, final_readout) = match &search {
        Some(value) => (value.weights.clone(), value.readout.clone()),
        None if initial_mismatch.bitwise_mismatch_count == 0 =>
            (Some(initial.clone()), Some(initial_readout.clone())),
        None => (None, None),
    };
    let final_gates = match (&final_weights, &final_readout) {
        (Some(weights), Some(output)) => Some(gates::audit(
            snapshot,
            op,
            &initial,
            weights,
            output,
            &target_readout,
            &parent.true_displacement,
            &parent.interior_indices,
            &path,
        )?),
        _ => None,
    };
    let repair_status = if initial_mismatch.bitwise_mismatch_count == 0 {
        if final_gates.as_ref().is_some_and(|gate| gate.passed) {
            "READOUT_ALREADY_EQUAL__FINAL_GATES_PASS"
        } else {
            "EXACT_READOUT_FOUND__FINAL_GATE_FAILURE"
        }
    } else if capacity_status == Some("CAPACITY_NUMERICALLY_AMBIGUOUS") {
        "SEARCH_NUMERICALLY_AMBIGUOUS"
    } else if capacity_status != Some("CAPACITY_EXACT_WITHIN_TOLERANCE") {
        "CAPACITY_GATE_SKIPPED__PARTIAL_OR_EMPTY"
    } else if search
        .as_ref()
        .is_some_and(|value| value.diagnostics.exact_readout_found)
    {
        if final_gates.as_ref().is_some_and(|gate| gate.passed) {
            "REPAIR_VALID"
        } else {
            "EXACT_READOUT_FOUND__FINAL_GATE_FAILURE"
        }
    } else {
        "SEARCH_EXHAUSTED__CAPACITY_PRESENT"
    };
    let receipt = EventReceipt {
        trial: snapshot.trial,
        parent_status,
        mismatch_status,
        initial_mismatch: Some(initial_mismatch),
        bank: bank_diagnostics,
        capacity: capacity_diagnostics,
        search: search.as_ref().map(|value| value.diagnostics.clone()),
        final_gates,
        repair_status,
        initial_alternate_sha256: Some(hash_f32(&initial)),
        final_weights_sha256: final_weights.as_deref().map(hash_f32),
        target_readout_sha256: Some(hash_f32(&target_readout)),
        final_readout_sha256: final_readout.as_deref().map(hash_f32),
    };
    Ok(Analyzed {
        receipt,
        interior: parent.interior_indices,
        true_displacement: parent.true_displacement,
        initial_alternate: initial,
        target_readout,
        final_weights,
        final_readout,
        path,
    })
}

fn expected(stage: &str) -> usize {
    if stage == "stage1-a" {
        STAGE_A_STATES
    } else {
        STAGE_B_STATES
    }
}

fn require_stage_a_review(root: &Path) -> Result<()> {
    let path = root.join("qualification/stage1-a-9531/reviewer-receipt.json");
    let receipt: Value = serde_json::from_reader(File::open(path)?)?;
    ensure!(receipt["protocol"] == PROTOCOL && receipt["status"] == "VERIFIED");
    ensure!(receipt["stage"] == "stage1-a" && receipt["audited_states"] == STAGE_A_STATES);
    Ok(())
}

fn run_stage(args: &[String], root: &Path) -> Result<()> {
    ensure!(
        args.len() == 5,
        "usage: q10-sequential-repair stage1-a|stage1-b CONFIG ANATOMY OUTPUT"
    );
    verify_parent(root)?;
    contract_and_plan(root)?;
    let seal = verify_seal(root)?;
    let config: Config = serde_json::from_reader(File::open(&args[2])?)?;
    let seeds = validate_config(&config)?;
    if config.stage == "stage1-b" {
        require_stage_a_review(root)?;
    }
    let expected_output = root.join(format!(
        "qualification/{}-{}",
        config.stage,
        if config.stage == "stage1-a" {
            "9531"
        } else {
            "9532-9535"
        }
    ));
    let supplied_output = Path::new(&args[4]);
    let out = if supplied_output.is_absolute() {
        supplied_output.to_owned()
    } else {
        root.join(supplied_output)
    };
    ensure!(out == expected_output, "noncanonical Q10-SR4 output path");
    std::fs::create_dir_all(&out)?;
    write_json(&out.join("pre-execution.json"), &seal)?;
    let anatomy = Path::new(&args[3]);
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(config.threads)
        .build()?;
    let mut total = 0;
    let mut eligible = 0;
    let mut initially_equal = 0;
    let mut mismatched = 0;
    let mut repaired = 0;
    let mut exhausted = 0;
    let mut final_gate_failures = 0;
    let mut ambiguous = 0;
    let mut capacity_exact = 0;
    let mut capacity_gated = 0;
    let mut search_entered = 0;
    for &seed in seeds {
        for side in &config.sides {
            for &tau in &config.taus {
                let graph = Graph::load(anatomy, side, config.glut_sign)?;
                let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733);
                ensure!(rewire.accepted > 0 && rewire.degree_preserved);
                let task = Task::new(&graph, seed ^ config.input_salt, 16, 12, 512);
                let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())?;
                let mut sim = Simulator::new(&graph, &graph.route, seed, tau, config.eta, "E");
                sim.capture = Some(crate::capture::Capture::new(sim.weights.len()));
                sim.policy = Some(Policy::new(sim.weights.len()));
                let run = sim
                    .run_dh07(
                        &task,
                        Dh07Condition::TruePerpendicular,
                        &shuffled,
                        config.observe,
                        0,
                    )
                    .context("Q10-SR4 frozen Q10-SM constructor simulation")?;
                ensure!(run.result.outcome.hot_allocations == 0);
                let policy = sim.policy.take().context("missing Q10-SR4 policy capture")?;
                ensure!(policy.count == 256);
                let analyzed = pool.install(|| {
                    policy.snapshots[..policy.count]
                        .par_iter()
                        .map(|snapshot| {
                            analyze_event(
                                &op,
                                snapshot,
                                seed ^ u64::from(tau.to_bits()) ^ snapshot.trial as u64,
                            )
                        })
                        .collect::<Result<Vec<_>>>()
                })?;
                let mut receipts = Vec::with_capacity(analyzed.len());
                let replay_index = analyzed
                    .iter()
                    .position(|value| {
                        value.receipt.repair_status != "PARENT_CONSTRUCTOR_INELIGIBLE"
                    })
                    .unwrap_or(0);
                for (index, value) in analyzed.into_iter().enumerate() {
                    total += 1;
                    eligible +=
                        usize::from(value.receipt.repair_status != "PARENT_CONSTRUCTOR_INELIGIBLE");
                    initially_equal += usize::from(
                        value.receipt.repair_status == "READOUT_ALREADY_EQUAL__FINAL_GATES_PASS",
                    );
                    mismatched +=
                        usize::from(value.receipt.mismatch_status == "READOUT_MISMATCHED");
                    repaired += usize::from(value.receipt.repair_status == "REPAIR_VALID");
                    exhausted +=
                        usize::from(value.receipt.repair_status.starts_with("SEARCH_EXHAUSTED"));
                    final_gate_failures += usize::from(
                        value.receipt.repair_status == "EXACT_READOUT_FOUND__FINAL_GATE_FAILURE",
                    );
                    ambiguous +=
                        usize::from(value.receipt.repair_status == "SEARCH_NUMERICALLY_AMBIGUOUS");
                    capacity_exact += usize::from(
                        value.receipt.capacity.as_ref().is_some_and(|capacity| {
                            capacity.status == "CAPACITY_EXACT_WITHIN_TOLERANCE"
                        }),
                    );
                    capacity_gated += usize::from(
                        value.receipt.repair_status
                            == "CAPACITY_GATE_SKIPPED__PARTIAL_OR_EMPTY",
                    );
                    search_entered += usize::from(value.receipt.search.is_some());
                    if index == replay_index {
                        write_json(
                            &out.join(format!(
                                "replay-seed{seed}-{side}-tau{tau}-trial{}.json",
                                value.receipt.trial
                            )),
                            &Replay {
                                snapshot: &policy.snapshots[index],
                                operator: &op,
                                interior_indices: &value.interior,
                                true_displacement: &value.true_displacement,
                                initial_alternate: &value.initial_alternate,
                                target_readout: &value.target_readout,
                                final_weights: value.final_weights.as_deref(),
                                final_readout: value.final_readout.as_deref(),
                                path: &value.path,
                                receipt: &value.receipt,
                            },
                        )?;
                    }
                    receipts.push(value.receipt);
                }
                write_json(
                    &out.join(format!("seed{seed}-{side}-tau{tau}.json")),
                    &json!({"protocol":PROTOCOL,"schema_version":1,"seed":seed,"side":side,"tau":tau,"post_len":graph.kc_mb.n_post,"drive_rows":op.rows.len(),"events":receipts,"scientific_seed_bundles":0,"behavioral_inference":false}),
                )?;
                println!("Q10-SR4 complete seed={seed} {side} tau={tau}");
            }
        }
    }
    ensure!(total == expected(&config.stage));
    let status = if ambiguous > 0 {
        "Q10_SR4_STAGE2A_NUMERICALLY_AMBIGUOUS"
    } else if repaired > 0 {
        "Q10_SR4_STAGE2A_VALID__REPAIR_FOUND"
    } else if eligible > 0 && initially_equal == eligible {
        "Q10_SR4_STAGE2A_VALID__READOUTS_ALREADY_EQUAL"
    } else if capacity_gated > 0 {
        "Q10_SR4_STAGE2A_VALID__CAPACITY_GATED_MIXTURE"
    } else if mismatched > 0 && repaired == 0 && final_gate_failures == 0 {
        "Q10_SR4_STAGE2A_VALID__NO_REPAIR_WITHIN_FROZEN_SEARCH"
    } else {
        "Q10_SR4_STAGE2A_VALID__CAPACITY_GATED_MIXTURE"
    };
    write_json(
        &out.join("execution.json"),
        &json!({
            "protocol":PROTOCOL,"schema_version":1,"stage":config.stage,"status":status,"complete":true,
            "audited_states":total,"eligible_states":eligible,"parent_constructor_ineligible":total-eligible,
            "initially_equal":initially_equal,"initially_mismatched":mismatched,"repair_valid":repaired,
            "search_exhausted":exhausted,"final_gate_failures":final_gate_failures,"numerically_ambiguous":ambiguous,
            "capacity_exact":capacity_exact,"capacity_gated":capacity_gated,"search_entered":search_entered,
            "cumulative_audited_states":if config.stage=="stage1-b"{total+STAGE_A_STATES}else{total},
            "scientific_seed_bundles":0,"behavioral_inference":false,"dh08b_authorized":false
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
        run_stage(&args, root)
    }
}

#[cfg(test)]
mod engineering_profile_tests {
    use super::*;
    use std::time::Instant;

    #[test]
    #[ignore = "single-event Q10-SR4 engineering profiler; never a qualification receipt"]
    fn profile_one_real_anatomy_event() {
        let anatomy = Path::new(env!("CARGO_MANIFEST_DIR")).join("..\\artifacts\\anatomy");
        let seed = 20001_u64;
        let side = "R";
        let tau = 4.0_f32;
        let graph = Graph::load(&anatomy, side, -1.0).unwrap();
        let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733);
        assert!(rewire.accepted > 0 && rewire.degree_preserved);
        let task = Task::new(&graph, seed ^ 858980352, 16, 12, 512);
        let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len()).unwrap();
        let mut sim = Simulator::new(&graph, &graph.route, seed, tau, 0.05, "E");
        sim.capture = Some(crate::capture::Capture::new(sim.weights.len()));
        sim.policy = Some(Policy::new(sim.weights.len()));
        let t_sim = Instant::now();
        let run = sim
            .run_dh07(
                &task,
                Dh07Condition::TruePerpendicular,
                &shuffled,
                true,
                0,
            )
            .unwrap();
        let simulation_seconds = t_sim.elapsed().as_secs_f64();
        let policy = sim.policy.take().unwrap();
        let snapshot = &policy.snapshots[0];

        let t_parent = Instant::now();
        let parent = q10::analyze_event(&op, snapshot, seed ^ u64::from(tau.to_bits())).unwrap();
        let parent_seconds = t_parent.elapsed().as_secs_f64();
        let initial = parent.committed_alternate(snapshot);
        let target_readout = readout::sequential(&op, &snapshot.target);
        let initial_readout = readout::sequential(&op, &initial);
        let initial_mismatch = readout::mismatch(&op, &initial_readout, &target_readout).unwrap();
        if initial_mismatch.bitwise_mismatch_count == 0 {
            println!(
                "Q10-SR4 profiler seed={seed} event={} simulation_seconds={simulation_seconds} parent_seconds={parent_seconds} initial_readout_equal=true",
                snapshot.trial
            );
            return;
        }

        let t_bank = Instant::now();
        let move_bank = bank::build(&op, &initial, &initial_readout, &parent.interior_indices).unwrap();
        let bank_seconds = t_bank.elapsed().as_secs_f64();
        let t_capacity = Instant::now();
        let capacity = capacity::analyze(&move_bank.moves, &initial_readout, &target_readout).unwrap();
        let capacity_seconds = t_capacity.elapsed().as_secs_f64();
        let t_search = Instant::now();
        let search = repair::search(
            &op,
            &initial,
            &initial_readout,
            &target_readout,
            &parent.interior_indices,
        )
        .unwrap();
        let search_seconds = t_search.elapsed().as_secs_f64();
        println!(
            "Q10-SR4 profiler seed={seed} event={} simulation_seconds={simulation_seconds} parent_seconds={parent_seconds} bank_seconds={bank_seconds} capacity_seconds={capacity_seconds} search_seconds={search_seconds} coordinates={} rows={} interior={} legal_moves={} mismatch={} capacity_status={} search_states={} search_successors={} search_exact={}",
            snapshot.trial,
            op.coordinates,
            op.rows.len(),
            parent.interior_indices.len(),
            move_bank.moves.len(),
            initial_mismatch.bitwise_mismatch_count,
            capacity.status,
            search.diagnostics.states_expanded,
            search.diagnostics.legal_successors_enumerated,
            search.diagnostics.exact_readout_found
        );
        assert!(run.result.outcome.hot_allocations == 0);
    }
}
