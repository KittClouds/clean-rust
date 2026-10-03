//! Q10-DA1 runner: target-blind distributed additive readout diagnostics.
//!
//! Support sets are chosen before target/error metrics are inspected. Each
//! coordinate is then optimized independently on its complete structural row
//! support. The combined endpoint is assembled sparsely and checked against a
//! fresh full sequential f32 replay. This module does not search interactions
//! or claim a geometric endpoint from readout authority alone.

use crate::{
    capture::Snapshot,
    da_core::{
        self, CoordinateChoice, GreedySelection, SupportIncidence,
    },
    graph::Graph,
    linear::DriveOperator,
    policy::Policy,
    q10,
    q10sr::{bank, gates, readout, repair},
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

const PROTOCOL: &str = "Q10-DA1";
const SEEDS: &[u64] = &[9731, 9732];
const TAUS: &[f32] = &[4.0, 16.0];
const SIDES: &[&str] = &["R", "L"];
const SAMPLE_TRIALS: &[usize] = &[128];
const EXPECTED_EVENTS: usize = 8;
const PARENT_PLAN: &str = "8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D";
const PARENT_CONTRACT: &str = "5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF";
const PARENT_RESULT: &str = "68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337";
const PARENT_STATUS: &str = "D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4";
const COALITION_POLICY: &str =
    "all eligible nonempty-support coordinates; greedy maximal under fixed stable order; no size cap";
const CANONICAL_ANATOMY_REL: &str =
    "dh06/artifacts/runs/20260915T201008Z/sealed/anatomy";

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
struct OperatorFixture {
    cues: usize,
    posts: usize,
    coordinates: usize,
    rows: Vec<Vec<usize>>,
}

#[derive(Serialize)]
struct ReplayFixture {
    operator: OperatorFixture,
    snapshot_base_bits: Vec<u32>,
    acquisition_axis: Vec<f64>,
    permitted: Vec<bool>,
    interior_indices: Vec<usize>,
    initial_weight_bits: Vec<u32>,
    target_weight_bits: Vec<u32>,
    initial_readout_bits: Vec<u32>,
    target_readout_bits: Vec<u32>,
}

#[derive(Serialize)]
struct ReadoutMetric {
    mismatch_count: usize,
    squared_error: f64,
    l2: f64,
}

#[derive(Serialize)]
struct UncoveredMetric {
    row_count: usize,
    mismatch_count: usize,
    squared_error: f64,
    l2: f64,
}

#[derive(Serialize)]
struct PrefixPoint {
    requested: String,
    requested_coordinates: Option<usize>,
    applied_coordinates: usize,
    available: bool,
    mismatch_count: usize,
    squared_error: f64,
    l2: f64,
    mismatch_reduction_vs_initial: isize,
    squared_error_reduction_vs_initial: f64,
    pareto_improvement_vs_initial: bool,
    l2_increased_vs_initial: bool,
}

#[derive(Serialize)]
struct WeightChange {
    coordinate: usize,
    selected_step: i8,
    before_bits: u32,
    after_bits: u32,
}

#[derive(Serialize)]
struct EndpointResidual {
    l2_distance_to_true_endpoint: f64,
    cosine_of_residual_to_true_displacement: Option<f64>,
    cosine_of_final_displacement_to_true_displacement: Option<f64>,
    cosine_of_final_vs_true_acquisition_orthogonal_displacements: Option<f64>,
}

#[derive(Serialize)]
struct SetResult {
    set_index: usize,
    selector_salt: u64,
    coalition_policy: &'static str,
    ordered_coordinates: Vec<usize>,
    selected_coordinates: Vec<usize>,
    excluded_coordinates: Vec<usize>,
    covered_rows: Vec<usize>,
    candidate_coordinate_count: usize,
    selected_coordinate_count: usize,
    excluded_coordinate_count: usize,
    support_disjoint_over_all_rows: bool,
    one_post_grouping_status: &'static str,
    support_cue_mask_cardinalities: Vec<usize>,
    initial: ReadoutMetric,
    final_readout: ReadoutMetric,
    covered_initial: ReadoutMetric,
    covered_final: ReadoutMetric,
    uncovered_error: UncoveredMetric,
    coordinates: Vec<CoordinateChoice>,
    nested_prefix_curve: Vec<PrefixPoint>,
    final_weight_changes: Vec<WeightChange>,
    final_readout_bits: Vec<u32>,
    assembled_full_replay_bitwise_equal: bool,
    replay_implementation_status: &'static str,
    legacy_gate_path_length: usize,
    legacy_64_move_gate_diagnostic: &'static str,
    legacy_gates: gates::FinalGates,
    geometry_gates_pass_without_legacy_path_cap: bool,
    geometry_gate_outcome: &'static str,
    endpoint_residual: EndpointResidual,
    readout_authority: &'static str,
    endpoint_status: &'static str,
}

#[derive(Serialize)]
struct EventResult {
    protocol: &'static str,
    seed: u64,
    side: String,
    tau: f32,
    trial: usize,
    parent_status: &'static str,
    declared_event: bool,
    parent_constructor_available: bool,
    status: &'static str,
    coalition_policy: &'static str,
    candidate_steps: [i8; 11],
    final_reserve_ulps: u32,
    initial: Option<ReadoutMetric>,
    fixture: Option<ReplayFixture>,
    sets: Vec<SetResult>,
}

fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn hash_f32(values: &[f32]) -> String {
    let mut hash = Sha256::new();
    for value in values {
        hash.update(value.to_bits().to_le_bytes());
    }
    format!("{:x}", hash.finalize())
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
        PathBuf::from("q10-da-config.json"),
    ];
    visit_files(root, &root.join("src"), &mut paths)?;
    paths.push(PathBuf::from("scripts/review_q10_da.py"));
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

fn canonical_anatomy(root: &Path) -> Result<PathBuf> {
    let experiment = root.parent().context("missing experiment parent")?;
    Ok(std::fs::canonicalize(experiment.join(CANONICAL_ANATOMY_REL))?)
}

fn anatomy_manifest(root: &Path) -> Result<Vec<Value>> {
    let mut paths = Vec::new();
    visit_files(root, root, &mut paths)?;
    paths.sort();
    paths
        .into_iter()
        .map(|path| {
            let relative = path.to_string_lossy().replace('\\', "/");
            Ok(json!({
                "path": relative,
                "sha256": hash_bytes(&std::fs::read(root.join(&path))?)
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
    let anatomy = canonical_anatomy(root)?;
    let anatomy_files = anatomy_manifest(&anatomy)?;
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
            "canonical_anatomy_dir": anatomy,
            "anatomy_manifest": anatomy_files,
            "parent_hashes": {
                "plan": PARENT_PLAN,
                "contract": PARENT_CONTRACT,
                "result": PARENT_RESULT,
                "status": PARENT_STATUS
            },
            "coalition_policy": COALITION_POLICY,
            "selector_count": 4,
            "candidate_steps": da_core::STEP_VOCABULARY,
            "minimum_final_reserve_ulps": bank::FINAL_RESERVE,
            "legacy_path_gate": "diagnostic_only",
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
    let anatomy = canonical_anatomy(root)?;
    ensure!(
        seal["canonical_anatomy_dir"] == serde_json::to_value(&anatomy)?
    );
    ensure!(seal["anatomy_manifest"] == serde_json::to_value(anatomy_manifest(&anatomy)?)?);
    let executable = std::env::current_exe()?;
    let executable_sha256 = hash_bytes(&std::fs::read(&executable)?);
    ensure!(
        seal["executable_sha256"]
            .as_str()
            .is_some_and(|value| value.eq_ignore_ascii_case(&executable_sha256))
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

fn bits(values: &[f32]) -> Vec<u32> {
    values.iter().map(|value| value.to_bits()).collect()
}

fn metric(actual: &[f32], target: &[f32]) -> ReadoutMetric {
    let mut squared_error = 0.0;
    let mut mismatch_count = 0;
    for (&value, &goal) in actual.iter().zip(target) {
        mismatch_count += usize::from(value.to_bits() != goal.to_bits());
        let error = f64::from(value) - f64::from(goal);
        squared_error += error * error;
    }
    ReadoutMetric {
        mismatch_count,
        squared_error,
        l2: squared_error.sqrt(),
    }
}

fn norm(values: &[f64]) -> f64 {
    values.iter().map(|value| value * value).sum::<f64>().sqrt()
}

fn cosine(a: &[f64], b: &[f64]) -> Option<f64> {
    let a_norm = norm(a);
    let b_norm = norm(b);
    if a_norm == 0.0 || b_norm == 0.0 {
        None
    } else {
        Some(a.iter().zip(b).map(|(x, y)| x * y).sum::<f64>() / (a_norm * b_norm))
    }
}

fn acquisition_orthogonal(value: &[f64], acquisition_axis: &[f64]) -> Option<Vec<f64>> {
    let axis_norm_sq = acquisition_axis
        .iter()
        .map(|component| component * component)
        .sum::<f64>();
    if axis_norm_sq == 0.0 {
        return None;
    }
    let projection = value
        .iter()
        .zip(acquisition_axis)
        .map(|(component, axis)| component * axis)
        .sum::<f64>()
        / axis_norm_sq;
    Some(
        value
            .iter()
            .zip(acquisition_axis)
            .map(|(component, axis)| component - projection * axis)
            .collect(),
    )
}

fn uncovered_metric(
    actual: &[f32],
    target: &[f32],
    covered: &[usize],
) -> UncoveredMetric {
    let mut covered_mask = vec![false; actual.len()];
    for &row in covered {
        covered_mask[row] = true;
    }
    let mut mismatch_count = 0;
    let mut squared_error = 0.0;
    let mut row_count = 0;
    for (row, (&value, &goal)) in actual.iter().zip(target).enumerate() {
        if covered_mask[row] {
            continue;
        }
        row_count += 1;
        mismatch_count += usize::from(value.to_bits() != goal.to_bits());
        let error = f64::from(value) - f64::from(goal);
        squared_error += error * error;
    }
    UncoveredMetric {
        row_count,
        mismatch_count,
        squared_error,
        l2: squared_error.sqrt(),
    }
}

fn covered_metric(actual: &[f32], target: &[f32], covered: &[usize]) -> ReadoutMetric {
    let mut mismatch_count = 0;
    let mut squared_error = 0.0;
    for &row in covered {
        mismatch_count += usize::from(actual[row].to_bits() != target[row].to_bits());
        let error = f64::from(actual[row]) - f64::from(target[row]);
        squared_error += error * error;
    }
    ReadoutMetric {
        mismatch_count,
        squared_error,
        l2: squared_error.sqrt(),
    }
}

fn geometry_without_legacy_path_cap(gate: &gates::FinalGates) -> bool {
    gate.outside_support_changes == 0
        && gate.changed_outside_interior == 0
        && gate.lower_boundary_membership_difference == 0
        && gate.upper_boundary_membership_difference == 0
        && gate.new_boundary_memberships == 0
        && gate.nonfinite_or_bounds_violations == 0
        && gate.minimum_down_steps_capped >= bank::FINAL_RESERVE
        && gate.minimum_up_steps_capped >= bank::FINAL_RESERVE
        && gate.maximum_coordinate_steps_from_initial <= 16
        && gate.cue_linear_normalized_error <= gate.cue_tolerance
        && gate.axis_normalized_error <= gate.axis_tolerance
        && gate.norm_normalized_error <= gate.norm_tolerance
}

fn prefix_point(
    requested: String,
    requested_coordinates: Option<usize>,
    choices: &[CoordinateChoice],
    operator: &DriveOperator,
    incidence: &SupportIncidence,
    initial_weights: &[f32],
    initial_readout: &[f32],
    target_readout: &[f32],
    initial: &ReadoutMetric,
) -> Result<PrefixPoint> {
    let requested_count = requested_coordinates.unwrap_or(choices.len());
    let applied = requested_count.min(choices.len());
    let replay = da_core::assemble_and_replay(
        operator,
        incidence,
        initial_weights,
        initial_readout,
        &choices[..applied],
    )
    .map_err(anyhow::Error::msg)?;
    ensure!(replay.bitwise_equal, "prefix assembled/full replay mismatch");
    let current = metric(&replay.full_replay, target_readout);
    let pareto = current.mismatch_count <= initial.mismatch_count
        && current.squared_error <= initial.squared_error
        && (current.mismatch_count < initial.mismatch_count
            || current.squared_error < initial.squared_error);
    Ok(PrefixPoint {
        requested,
        requested_coordinates,
        applied_coordinates: applied,
        available: requested_count <= choices.len(),
        mismatch_count: current.mismatch_count,
        squared_error: current.squared_error,
        l2: current.l2,
        mismatch_reduction_vs_initial: initial.mismatch_count as isize
            - current.mismatch_count as isize,
        squared_error_reduction_vs_initial: initial.squared_error - current.squared_error,
        pareto_improvement_vs_initial: pareto,
        l2_increased_vs_initial: current.squared_error > initial.squared_error,
    })
}

fn endpoint_residual(
    snapshot: &Snapshot,
    final_weights: &[f32],
    true_displacement: &[f64],
) -> EndpointResidual {
    let mut residual = Vec::with_capacity(final_weights.len());
    let mut final_displacement = Vec::with_capacity(final_weights.len());
    for ((&final_value, &target), &base) in final_weights
        .iter()
        .zip(&snapshot.target)
        .zip(&snapshot.base)
    {
        residual.push(f64::from(final_value) - f64::from(target));
        final_displacement.push(f64::from(final_value) - f64::from(base));
    }
    let orthogonal_final = acquisition_orthogonal(&final_displacement, &snapshot.axis);
    let orthogonal_true = acquisition_orthogonal(true_displacement, &snapshot.axis);
    let orthogonal_cosine = orthogonal_final
        .as_deref()
        .zip(orthogonal_true.as_deref())
        .and_then(|(final_direction, true_direction)| cosine(final_direction, true_direction));
    EndpointResidual {
        l2_distance_to_true_endpoint: norm(&residual),
        cosine_of_residual_to_true_displacement: cosine(&residual, true_displacement),
        cosine_of_final_displacement_to_true_displacement:
            cosine(&final_displacement, true_displacement),
        cosine_of_final_vs_true_acquisition_orthogonal_displacements: orthogonal_cosine,
    }
}

fn build_path(choices: &[CoordinateChoice]) -> Vec<repair::AppliedMove> {
    choices
        .iter()
        .filter(|choice| choice.selected_step != 0)
        .map(|choice| repair::AppliedMove {
            coordinate: choice.coordinate,
            direction: if choice.selected_step < 0 {
                bank::Direction::Down
            } else {
                bank::Direction::Up
            },
            before_bits: choice.before_bits,
            after_bits: choice.after_bits,
        })
        .collect()
}

fn side_key(side: &str) -> u64 {
    match side {
        "R" => 0x525F5349_44455F52,
        "L" => 0x525F5349_44455F4C,
        _ => 0x525F5349_44455F3F,
    }
}

fn analyze_set(
    operator: &DriveOperator,
    snapshot: &Snapshot,
    parent: &q10::Analysis,
    initial_weights: &[f32],
    initial_readout: &[f32],
    target_readout: &[f32],
    initial: &ReadoutMetric,
    incidence: &SupportIncidence,
    selection: GreedySelection,
    set_index: usize,
) -> Result<SetResult> {
    let mut choices = Vec::with_capacity(selection.selected_coordinates.len());
    for coordinate in &selection.selected_coordinates {
        choices.push(da_core::optimize_coordinate(
            operator,
            incidence,
            initial_weights,
            initial_readout,
            target_readout,
            *coordinate,
        ));
    }
    let replay = da_core::assemble_and_replay(
        operator,
        incidence,
        initial_weights,
        initial_readout,
        &choices,
    )
    .map_err(anyhow::Error::msg)?;
    ensure!(replay.bitwise_equal, "assembled replay differs from full f32 replay");
    let final_readout = metric(&replay.full_replay, target_readout);
    let covered_initial = covered_metric(initial_readout, target_readout, &selection.covered_rows);
    let covered_final = covered_metric(&replay.full_replay, target_readout, &selection.covered_rows);
    let uncovered_error = uncovered_metric(
        &replay.full_replay,
        target_readout,
        &selection.covered_rows,
    );
    let nested_prefix_curve = [
        ("1".to_owned(), Some(1)),
        ("3".to_owned(), Some(3)),
        ("8".to_owned(), Some(8)),
        ("16".to_owned(), Some(16)),
        ("32".to_owned(), Some(32)),
        ("all".to_owned(), None),
    ]
    .into_iter()
    .map(|(label, count)| {
        prefix_point(
            label,
            count,
            &choices,
            operator,
            incidence,
            initial_weights,
            initial_readout,
            target_readout,
            initial,
        )
    })
    .collect::<Result<Vec<_>>>()?;
    let path = build_path(&choices);
    let legacy_gates = gates::audit(
        snapshot,
        operator,
        initial_weights,
        &replay.final_weights,
        &replay.full_replay,
        target_readout,
        &parent.true_displacement,
        &parent.interior_indices,
        &path,
    )?;
    let geometry_pass = geometry_without_legacy_path_cap(&legacy_gates);
    let readout_authority = if legacy_gates.sequential_bitwise_equal {
        "FULL_ORACLE_BITWISE_PARITY"
    } else {
        "FULL_ORACLE_MISMATCHED"
    };
    let endpoint_status = if geometry_pass && legacy_gates.sequential_bitwise_equal {
        "READOUT_AND_LISTED_GEOMETRY_PASS__DIRECTION_UNQUALIFIED"
    } else {
        "REPAIR_READOUT_DIAGNOSTIC_ONLY"
    };
    let support_disjoint = choices.iter().enumerate().all(|(index, choice)| {
        choices[..index]
            .iter()
            .all(|previous| !incidence.overlaps(previous.coordinate, choice.coordinate))
    });
    ensure!(support_disjoint, "selected support overlap");
    let one_post = choices.iter().all(|choice| choice.one_post_support);
    let endpoint_residual = endpoint_residual(snapshot, &replay.final_weights, &parent.true_displacement);
    let final_weight_changes = choices
        .iter()
        .map(|choice| WeightChange {
            coordinate: choice.coordinate,
            selected_step: choice.selected_step,
            before_bits: choice.before_bits,
            after_bits: choice.after_bits,
        })
        .collect();
    let candidate_coordinate_count = selection.ordered_coordinates.len();
    let excluded_coordinate_count = selection.excluded_coordinates.len();
    let selected_coordinate_count = choices.len();
    Ok(SetResult {
        set_index,
        selector_salt: da_core::SELECTOR_SALTS[set_index],
        coalition_policy: COALITION_POLICY,
        ordered_coordinates: selection.ordered_coordinates,
        selected_coordinates: selection.selected_coordinates,
        excluded_coordinates: selection.excluded_coordinates,
        covered_rows: selection.covered_rows,
        candidate_coordinate_count,
        selected_coordinate_count,
        excluded_coordinate_count,
        support_disjoint_over_all_rows: support_disjoint,
        one_post_grouping_status: if one_post {
            "ALL_SELECTED_COORDINATES_SINGLE_POST"
        } else {
            "MULTI_POST_SUPPORT_DIAGNOSTIC"
        },
        support_cue_mask_cardinalities: choices
            .iter()
            .map(|choice| choice.support_cue_ids.len())
            .collect(),
        initial: ReadoutMetric {
            mismatch_count: initial.mismatch_count,
            squared_error: initial.squared_error,
            l2: initial.l2,
        },
        final_readout,
        covered_initial,
        covered_final,
        uncovered_error,
        coordinates: choices,
        nested_prefix_curve,
        final_weight_changes,
        final_readout_bits: bits(&replay.full_replay),
        assembled_full_replay_bitwise_equal: replay.bitwise_equal,
        replay_implementation_status: "ASSEMBLED_FULL_REPLAY_PARITY_PASS",
        legacy_gate_path_length: path.len(),
        legacy_64_move_gate_diagnostic: if path.len() > 64 {
            "LEGACY_64_MOVE_LIMIT_TRIGGERED_DIAGNOSTIC_ONLY"
        } else {
            "LEGACY_64_MOVE_LIMIT_NOT_TRIGGERED"
        },
        legacy_gates,
        geometry_gates_pass_without_legacy_path_cap: geometry_pass,
        geometry_gate_outcome: if geometry_pass {
            "ALL_GEOMETRY_GATES_PASS"
        } else {
            "GEOMETRY_GATE_FAILURE_DIAGNOSTIC"
        },
        endpoint_residual,
        readout_authority,
        endpoint_status,
    })
}

fn event_for_snapshot(
    operator: &DriveOperator,
    snapshot: &Snapshot,
    seed: u64,
    side: &str,
    tau: f32,
) -> Result<EventResult> {
    let parent = q10::analyze_event(
        operator,
        snapshot,
        seed ^ u64::from(tau.to_bits()) ^ snapshot.trial as u64,
    )?;
    if parent.event.status != "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT" {
        return Ok(EventResult {
            protocol: PROTOCOL,
            seed,
            side: side.to_owned(),
            tau,
            trial: snapshot.trial,
            parent_status: parent.event.status,
            declared_event: true,
            parent_constructor_available: false,
            status: "PARENT_CONSTRUCTOR_INELIGIBLE",
            coalition_policy: COALITION_POLICY,
            candidate_steps: da_core::STEP_VOCABULARY,
            final_reserve_ulps: bank::FINAL_RESERVE,
            initial: None,
            fixture: None,
            sets: Vec::new(),
        });
    }
    let initial_weights = parent.committed_alternate(snapshot);
    let initial_readout = readout::sequential(operator, &initial_weights);
    let target_readout = readout::sequential(operator, &snapshot.target);
    let initial = metric(&initial_readout, &target_readout);
    let incidence = SupportIncidence::from_operator(operator);
    let eligible = parent
        .interior_indices
        .iter()
        .copied()
        .filter(|&coordinate| !incidence.rows(coordinate).is_empty())
        .collect::<Vec<_>>();
    let event_key = u64::from(tau.to_bits())
        ^ snapshot.trial as u64
        ^ side_key(side)
        ^ 0xDA01_4556_454E_5431;
    let selections = da_core::four_greedy_maximal_sets(
        &eligible,
        &incidence,
        seed,
        event_key,
    );
    let mut sets = Vec::with_capacity(selections.len());
    for (set_index, selection) in selections.into_iter().enumerate() {
        sets.push(analyze_set(
            operator,
            snapshot,
            &parent,
            &initial_weights,
            &initial_readout,
            &target_readout,
            &initial,
            &incidence,
            selection,
            set_index,
        )?);
    }
    Ok(EventResult {
        protocol: PROTOCOL,
        seed,
        side: side.to_owned(),
        tau,
        trial: snapshot.trial,
        parent_status: parent.event.status,
        declared_event: true,
        parent_constructor_available: true,
        status: "DA1_EVENT_COMPLETE",
        coalition_policy: COALITION_POLICY,
        candidate_steps: da_core::STEP_VOCABULARY,
        final_reserve_ulps: bank::FINAL_RESERVE,
        initial: Some(initial),
        fixture: Some(ReplayFixture {
            operator: OperatorFixture {
                cues: operator.cues,
                posts: operator.posts,
                coordinates: operator.coordinates,
                rows: operator.rows.clone(),
            },
            snapshot_base_bits: bits(&snapshot.base),
            acquisition_axis: snapshot.axis.clone(),
            permitted: snapshot.permitted.clone(),
            interior_indices: parent.interior_indices.clone(),
            initial_weight_bits: bits(&initial_weights),
            target_weight_bits: bits(&snapshot.target),
            initial_readout_bits: bits(&initial_readout),
            target_readout_bits: bits(&target_readout),
        }),
        sets,
    })
}

fn run(args: &[String], root: &Path) -> Result<()> {
    ensure!(args.len() == 4, "usage: q10-distributed-additive CONFIG ANATOMY OUTPUT");
    verify_parent(root)?;
    contract_and_plan(root)?;
    let seal = verify_seal(root)?;
    let config: Config = serde_json::from_reader(File::open(&args[1])?)?;
    validate(&config)?;
    let expected_output = root.join("qualification/sample-9731-9732");
    let supplied_output = Path::new(&args[3]);
    let output = if supplied_output.is_absolute() {
        supplied_output.to_owned()
    } else {
        root.join(supplied_output)
    };
    ensure!(output == expected_output, "noncanonical Q10-DA1 output path");
    let anatomy = canonical_anatomy(root)?;
    ensure!(
        std::fs::canonicalize(&args[2])? == anatomy,
        "anatomy path is not the authorized sealed DH06 anatomy directory"
    );
    ensure!(
        seal["anatomy_manifest"] == serde_json::to_value(anatomy_manifest(&anatomy)?)?,
        "authorized DH06 anatomy input hash manifest changed"
    );
    std::fs::create_dir_all(&output)?;
    write_json(&output.join("pre-execution.json"), &seal)?;
    let mut total = 0;
    let mut available_events = 0;
    let mut unavailable_events = 0;
    for &seed in SEEDS {
        for side in &config.sides {
            for &tau in TAUS {
                let graph = Graph::load(&anatomy, side, config.glut_sign)?;
                let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733);
                ensure!(rewire.accepted > 0 && rewire.degree_preserved);
                let task = Task::new(&graph, seed ^ config.input_salt, 16, 12, 512);
                let operator = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())?;
                let mut simulator = Simulator::new(&graph, &graph.route, seed, tau, config.eta, "E");
                simulator.capture = Some(crate::capture::Capture::new(simulator.weights.len()));
                simulator.policy = Some(Policy::new(simulator.weights.len()));
                let run = simulator
                    .run_dh07(
                        &task,
                        Dh07Condition::TruePerpendicular,
                        &shuffled,
                        config.observe,
                        0,
                    )
                    .context("Q10-DA1 frozen engineering constructor")?;
                ensure!(run.result.outcome.hot_allocations == 0);
                let policy = simulator.policy.take().context("missing policy capture")?;
                ensure!(policy.count == 256);
                let snapshot = policy.snapshots[..policy.count]
                    .iter()
                    .find(|snapshot| SAMPLE_TRIALS.contains(&snapshot.trial))
                    .context("missing Q10-DA1 sample trial")?;
                let event = event_for_snapshot(&operator, snapshot, seed, side, tau)?;
                if event.parent_constructor_available {
                    available_events += 1;
                } else {
                    unavailable_events += 1;
                }
                write_json(
                    &output.join(format!("seed{seed}-{side}-tau{tau}.json")),
                    &event,
                )?;
                total += 1;
            }
        }
    }
    ensure!(total == EXPECTED_EVENTS);
    write_json(
        &output.join("execution.json"),
        &json!({
            "protocol": PROTOCOL,
            "complete": true,
            "audited_events": total,
            "declared_events": EXPECTED_EVENTS,
            "available_events": available_events,
            "unavailable_events": unavailable_events,
            "availability_denominator": "all declared seed/side/tau events; no resampling",
            "coalition_policy": COALITION_POLICY,
            "scientific_seed_bundles": 0,
            "behavioral_inference": false,
            "dh08b_authorized": false,
            "readout_authority": "FULL_SEQUENTIAL_F32_ORACLE_REQUIRED",
            "geometry_endpoint_claim": "ONLY_IF_ALL_GEOMETRY_GATES_PASS"
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
