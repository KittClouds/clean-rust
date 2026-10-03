mod capacity;
mod readout;
mod types;

use crate::{
    capture::Snapshot,
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
use types::{BundleHeader, CapacityReceipt, EventReceipt, StageCounters, StateHashes};

const PROTOCOL: &str = "Q10-RC";
const SEED_A: &[u64] = &[9601];
const SEEDS_B: &[u64] = &[9602, 9603, 9604, 9605];
const STAGE_A_STATES: usize = 1024;
const STAGE_B_STATES: usize = 4096;
const PARENT_PLAN: &str = "8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D";
const PARENT_CONTRACT: &str = "5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF";
const PARENT_STATUS: &str = "D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4";
const PARENT_RESULT: &str = "68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337";
const PARENT_SUMMARY: &str = "2B64FF590E226CD393EBCFF6A5147728BAC931F395D76970567EBD6061EDA113";

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
    reserve_ulps: u32,
    post_move_reserve_ulps: u32,
    rank_multiplier: f64,
    svd_epsilon: f64,
    svd_max_iterations: usize,
    integrity_tolerance: f64,
    coefficient_reporting_floor: f64,
}

#[derive(Serialize)]
struct Replay {
    protocol: &'static str,
    schema_version: u32,
    seed: u64,
    side: String,
    tau: f32,
    snapshot: Snapshot,
    operator: DriveOperator,
    interior_indices: Vec<usize>,
    alternate_state: Vec<f32>,
    event: EventReceipt,
}

fn validate_config(config: &Config) -> Result<&'static [u64]> {
    ensure!(config.stage == "stage-a" || config.stage == "stage-b");
    let seeds = if config.stage == "stage-a" {
        SEED_A
    } else {
        SEEDS_B
    };
    ensure!(
        config.seeds == seeds,
        "unauthorized Q10-RC engineering seeds"
    );
    ensure!(config.observe && config.taus == [4.0, 16.0] && config.sides == ["R", "L"]);
    ensure!(config.conditions == ["true_perpendicular"] && config.arms == ["E", "Z"]);
    ensure!(config.cues == 16 && config.delay_steps == 12 && config.trials == 512);
    ensure!(config.eta == 0.05 && config.glut_sign == -1.0 && config.input_salt == 858980352);
    ensure!(config.threads == 8);
    ensure!(config.reserve_ulps == 32 && config.post_move_reserve_ulps == 31);
    ensure!(config.rank_multiplier == 1000.0);
    ensure!(config.svd_epsilon == 1.0e-14 && config.svd_max_iterations == 100_000);
    ensure!(config.integrity_tolerance == 2.0e-10);
    ensure!(config.coefficient_reporting_floor == 1.0e-12);
    Ok(seeds)
}

fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn hash_file(path: &Path) -> Result<String> {
    Ok(hash_bytes(&std::fs::read(path)?))
}

fn hash_f32(values: &[f32]) -> String {
    let mut hash = Sha256::new();
    for value in values {
        hash.update(value.to_bits().to_le_bytes());
    }
    format!("{:x}", hash.finalize())
}

fn hash_bool(values: &[bool]) -> String {
    let mut hash = Sha256::new();
    for &value in values {
        hash.update([u8::from(value)]);
    }
    format!("{:x}", hash.finalize())
}

fn hash_rows(op: &DriveOperator) -> String {
    let mut hash = Sha256::new();
    hash.update((op.cues as u64).to_le_bytes());
    hash.update((op.posts as u64).to_le_bytes());
    hash.update((op.coordinates as u64).to_le_bytes());
    for row in &op.rows {
        hash.update((row.len() as u64).to_le_bytes());
        for &coordinate in row {
            hash.update((coordinate as u64).to_le_bytes());
        }
    }
    format!("{:x}", hash.finalize())
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let mut writer = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(path)?);
    serde_json::to_writer_pretty(&mut writer, value)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

fn write_bundle(path: &Path, header: &BundleHeader, events: &[EventReceipt]) -> Result<()> {
    let mut writer = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(path)?);
    serde_json::to_writer(&mut writer, header)?;
    writer.write_all(b"\n")?;
    for event in events {
        serde_json::to_writer(&mut writer, event)?;
        writer.write_all(b"\n")?;
    }
    writer.flush()?;
    Ok(())
}

fn source_manifest(root: &Path) -> Result<Vec<Value>> {
    fn visit(root: &Path, dir: &Path, paths: &mut Vec<PathBuf>) -> Result<()> {
        for entry in std::fs::read_dir(dir)? {
            let path = entry?.path();
            if path.is_dir() {
                visit(root, &path, paths)?;
            } else if path.extension().is_some_and(|x| x == "rs") {
                paths.push(path.strip_prefix(root)?.to_owned());
            }
        }
        Ok(())
    }
    let mut paths = vec![
        PathBuf::from("Cargo.toml"),
        PathBuf::from("Cargo.lock"),
        PathBuf::from("PLAN.md"),
        PathBuf::from("CONTRACT.json"),
        PathBuf::from("stage-a-config.json"),
        PathBuf::from("stage-b-config.json"),
        PathBuf::from("scripts/review_q10_rc.py"),
    ];
    visit(root, &root.join("src"), &mut paths)?;
    paths.sort();
    paths
        .into_iter()
        .map(|path| {
            Ok(json!({
                "path":path,
                "sha256":hash_file(&root.join(&path))?
            }))
        })
        .collect()
}

fn verify_lineage(root: &Path) -> Result<()> {
    let parent = root
        .parent()
        .context("Q10-RC root has no parent")?
        .join("q10-safety-margin-v1");
    for (name, expected) in [
        ("PLAN.md", PARENT_PLAN),
        ("CONTRACT.json", PARENT_CONTRACT),
        ("STATUS.json", PARENT_STATUS),
        ("RESULT.md", PARENT_RESULT),
        ("Q10-SM-SUMMARY.json", PARENT_SUMMARY),
    ] {
        ensure!(
            hash_file(&parent.join(name))?.eq_ignore_ascii_case(expected),
            "Q10-SM lineage mismatch: {name}"
        );
    }
    let status: Value = serde_json::from_reader(File::open(parent.join("STATUS.json"))?)?;
    ensure!(status["status"] == "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT");
    ensure!(status["stage"] == "STAGE1_COMPLETE");
    ensure!(status["cumulative_audited_states"] == 5120);
    ensure!(status["accepted_nonidentity_events"] == 5026);
    ensure!(status["safety_margin_dominated_events"] == 94);
    ensure!(status["sequential_f32_readout"] == "NOT_RUN");
    ensure!(status["ulp_repair"] == "NOT_RUN");
    Ok(())
}

fn stage_expected(stage: &str) -> usize {
    if stage == "stage-a" {
        STAGE_A_STATES
    } else {
        STAGE_B_STATES
    }
}

fn verify_stage_b_gate(root: &Path) -> Result<()> {
    let receipt_path = root.join("qualification/stage-a-9601/reviewer-receipt.json");
    let receipt: Value = serde_json::from_reader(
        File::open(&receipt_path).context("Stage B requires Stage A reviewer receipt")?,
    )?;
    ensure!(receipt["protocol"] == PROTOCOL);
    ensure!(receipt["stage"] == "stage-a");
    ensure!(receipt["status"] == "VERIFIED");
    ensure!(receipt["audited_states"] == STAGE_A_STATES);
    ensure!(receipt["contract_sha256"] == hash_file(&root.join("CONTRACT.json"))?);
    Ok(())
}

fn alternate_state(snapshot: &Snapshot, analysis: &q10::Analysis) -> Vec<f32> {
    snapshot
        .base
        .iter()
        .zip(&analysis.constrained_displacement)
        .zip(&analysis.alternate_null)
        .map(|((&base, &constrained), &null)| (f64::from(base) + constrained + null) as f32)
        .collect()
}

fn build_event(
    op: &DriveOperator,
    index: &readout::ReadoutIndex,
    snapshot: &Snapshot,
    key: u64,
    row_hash: &str,
) -> Result<(EventReceipt, Option<Vec<f32>>, Vec<usize>)> {
    let analysis = q10::analyze_event(op, snapshot, key)?;
    let endpoint_status = analysis.event.status;
    let accepted = endpoint_status == "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT";
    let alternate = accepted.then(|| alternate_state(snapshot, &analysis));
    let hashes = StateHashes {
        base_sha256: hash_f32(&snapshot.base),
        true_sha256: hash_f32(&snapshot.target),
        alternate_sha256: alternate.as_deref().map(hash_f32),
        support_sha256: hash_bool(&snapshot.permitted),
        row_order_sha256: row_hash.to_owned(),
    };
    let capacity = if let Some(alternate) = &alternate {
        let moves =
            readout::audit_moves(op, index, snapshot, alternate, &analysis.interior_indices)?;
        let geometry = capacity::analyze(&moves.columns_by_post, &moves.baseline.error)?;
        ensure!(geometry.rank.active_columns == moves.bank.active_moves);
        ensure!(moves.bank.minimum_remaining_down_steps_capped >= 31);
        ensure!(moves.bank.minimum_remaining_up_steps_capped >= 31);
        let status = if moves.baseline.bitwise_mismatch_count == 0 {
            "ALREADY_EQUAL"
        } else {
            "CAPACITY_CHARACTERIZED"
        };
        Some(CapacityReceipt {
            status,
            baseline: moves.baseline,
            move_bank: moves.bank,
            rank_projection: geometry.rank,
            relaxed_budget: geometry.relaxed,
            rows: moves.rows,
            collateral: moves.collateral,
            learner_mutation: false,
            simulation_rng_consumed_by_audit: false,
            repairs_applied: 0,
            multi_move_evaluations: 0,
        })
    } else {
        None
    };
    let receipt = EventReceipt {
        trial: snapshot.trial,
        endpoint_status,
        state_hashes: hashes,
        q10_sm_event: analysis.event,
        capacity,
    };
    Ok((receipt, alternate, analysis.interior_indices))
}

fn write_replay(
    path: &Path,
    seed: u64,
    side: &str,
    tau: f32,
    snapshot: &Snapshot,
    op: &DriveOperator,
    index: &readout::ReadoutIndex,
    key: u64,
    row_hash: &str,
) -> Result<()> {
    let (event, alternate, interior_indices) = build_event(op, index, snapshot, key, row_hash)?;
    let alternate_state = alternate.context("replay event must have a safe endpoint")?;
    write_json(
        path,
        &Replay {
            protocol: PROTOCOL,
            schema_version: 1,
            seed,
            side: side.to_owned(),
            tau,
            snapshot: snapshot.clone(),
            operator: op.clone(),
            interior_indices,
            alternate_state,
            event,
        },
    )
}

pub fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(
        args.len() == 5,
        "usage: q10-repair-capacity stage-a|stage-b CONFIG ANATOMY OUTPUT"
    );
    let config: Config = serde_json::from_reader(File::open(&args[2])?)?;
    ensure!(args[1] == config.stage);
    let seeds = validate_config(&config)?;
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    verify_lineage(root)?;
    let contract: Value = serde_json::from_reader(File::open(root.join("CONTRACT.json"))?)?;
    ensure!(contract["protocol"] == PROTOCOL);
    let plan_hash = hash_file(&root.join("PLAN.md"))?;
    ensure!(
        contract["plan_sha256"]
            .as_str()
            .is_some_and(|hash| hash.eq_ignore_ascii_case(&plan_hash))
    );
    if config.stage == "stage-b" {
        verify_stage_b_gate(root)?;
    }
    let out = Path::new(&args[4]);
    ensure!(!out.exists(), "refusing to reuse Q10-RC output directory");
    std::fs::create_dir_all(out)?;
    let executable = std::env::current_exe()?;
    write_json(
        &out.join("pre-execution.json"),
        &json!({
            "protocol":PROTOCOL,
            "schema_version":1,
            "stage":config.stage,
            "source":source_manifest(root)?,
            "executable":executable,
            "executable_sha256":hash_file(&executable)?,
            "config_sha256":hash_file(Path::new(&args[2]))?,
            "contract_sha256":hash_file(&root.join("CONTRACT.json"))?,
            "plan_sha256":plan_hash,
            "parent_hashes":{
                "plan":PARENT_PLAN,
                "contract":PARENT_CONTRACT,
                "status":PARENT_STATUS,
                "result":PARENT_RESULT,
                "summary":PARENT_SUMMARY
            },
            "seeds":seeds,
            "scientific_seed_bundles":0,
            "behavioral_inference":false,
            "actions_rewards_accuracy_recorded":false,
            "repairs_applied":0,
            "multi_move_evaluations":0,
            "execution_authorized_by_user_after_contract_freeze":true
        }),
    )?;

    let anatomy = Path::new(&args[3]);
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(config.threads)
        .build()?;
    let mut counters = StageCounters::default();
    let mut replay_written = false;
    for &seed in seeds {
        for side in &config.sides {
            for &tau in &config.taus {
                let graph = Graph::load(anatomy, side, config.glut_sign)?;
                let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733);
                ensure!(rewire.accepted > 0 && rewire.degree_preserved);
                let task = Task::new(&graph, seed ^ config.input_salt, 16, 12, 512);
                let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())?;
                let index = readout::ReadoutIndex::new(&op)?;
                ensure!(
                    readout::sequential(&op, &vec![0.0; op.coordinates])
                        == op.sequential(&vec![0.0; op.coordinates])
                );
                let row_hash = hash_rows(&op);
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
                    .context("Q10-RC capture simulator")?;
                ensure!(run.result.outcome.hot_allocations == 0);
                let policy = sim.policy.take().context("missing Q10-RC policy capture")?;
                ensure!(policy.count == 256);
                let events = pool.install(|| {
                    policy.snapshots[..policy.count]
                        .par_iter()
                        .map(|snapshot| {
                            build_event(
                                &op,
                                &index,
                                snapshot,
                                seed ^ (tau.to_bits() as u64) ^ snapshot.trial as u64,
                                &row_hash,
                            )
                            .map(|result| result.0)
                        })
                        .collect::<Result<Vec<_>>>()
                })?;
                for event in &events {
                    counters.add(event);
                }
                if !replay_written {
                    if let Some(index_of_replay) =
                        events.iter().position(|event| event.capacity.is_some())
                    {
                        let snapshot = &policy.snapshots[index_of_replay];
                        write_replay(
                            &out.join("replay-first-applicable.json"),
                            seed,
                            side,
                            tau,
                            snapshot,
                            &op,
                            &index,
                            seed ^ (tau.to_bits() as u64) ^ snapshot.trial as u64,
                            &row_hash,
                        )?;
                        replay_written = true;
                    }
                }
                write_bundle(
                    &out.join(format!("seed{seed}-{side}-tau{tau}.jsonl")),
                    &BundleHeader {
                        protocol: PROTOCOL,
                        schema_version: 1,
                        seed,
                        side: side.clone(),
                        tau,
                        post_len: graph.kc_mb.n_post,
                        drive_rows: op.rows.len(),
                        events: events.len(),
                    },
                    &events,
                )?;
                println!("Q10-RC complete seed={seed} side={side} tau={tau}");
            }
        }
    }
    ensure!(counters.states == stage_expected(&config.stage));
    ensure!(replay_written || counters.applicable == 0);
    let status = if counters.applicable > 0 {
        "Q10_RC_VALID__CAPACITY_CHARACTERIZED"
    } else {
        "Q10_RC_VALID__NO_APPLICABLE_SAFE_ENDPOINTS"
    };
    let cumulative = if config.stage == "stage-b" {
        counters.states + STAGE_A_STATES
    } else {
        counters.states
    };
    write_json(
        &out.join("execution.json"),
        &json!({
            "protocol":PROTOCOL,
            "schema_version":1,
            "stage":config.stage,
            "status":status,
            "complete":true,
            "audited_states":counters.states,
            "applicable_safe_endpoints":counters.applicable,
            "safety_margin_dominated_events":counters.dominated,
            "already_equal_events":counters.already_equal,
            "legal_isolated_moves":counters.legal_moves,
            "active_isolated_moves":counters.active_moves,
            "zero_capacity_rows":counters.zero_capacity_rows,
            "no_helpful_rows":counters.no_helpful_rows,
            "rank_sum":counters.rank_sum,
            "cumulative_audited_states":cumulative,
            "scientific_seed_bundles":0,
            "behavioral_inference":false,
            "actions_rewards_accuracy_recorded":false,
            "repairs_applied":0,
            "multi_move_evaluations":0,
            "future_gates_set":false,
            "stage_b_authorized_by_this_receipt":false,
            "dh08b_authorized":false
        }),
    )?;
    Ok(())
}
