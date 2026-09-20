use super::*;
mod output;
#[cfg(test)]
mod tests;
use output::{write_headers, write_report, write_seed_summary};
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;

const SNAPSHOT_STEPS: [usize; 3] = [600, 2_400, 4_200];
const FUTURE_COMMITS: usize = 63;
const HORIZONS: [usize; 7] = [1, 2, 4, 8, 16, 32, 64];
const MATCH_COUNT: usize = 2;
const MATCH_TOLERANCE: f32 = MATCHED_REGRET_TOLERANCE;
const LOSS_TOLERANCE: f64 = 2.0e-6;

#[derive(Clone, Copy)]
struct Snapshot {
    step: usize,
    model: Model,
}

#[derive(Clone, Copy)]
struct MatchedProgram {
    program: Program,
    utility: f32,
    utility_gap: f32,
}

struct FrozenPath {
    programs: Vec<Option<Program>>,
    invalid_source_step: usize,
}

#[derive(Clone, Copy)]
struct PathPoint {
    gap: f64,
    cumulative_mixed: f64,
    distance: f64,
}

struct PathReplay {
    points: [Option<PathPoint>; HORIZONS.len()],
    replayed_commits: usize,
    invalid_step: usize,
    telescoping_residual: f64,
    max_distance_drift: f64,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct PathSourceReport {
    pub seeds: usize,
    pub snapshots: usize,
    pub pair_program_snapshots: usize,
    pub pair_snapshots_without_controls: usize,
    pub matched_controls: usize,
    pub generated_paths: usize,
    pub complete_crossovers: usize,
    pub invalid_source_paths: usize,
    pub invalid_replay_paths: usize,
    pub max_telescoping_residual: f64,
    pub max_source_identity_residual: f64,
    pub max_parameter_distance_drift: f64,
    pub mean_delta_selected_path_h64: f64,
    pub mean_delta_matched_control_path_h64: f64,
    pub mean_source_interaction_h64: f64,
    pub g3_favored_under_both_paths: usize,
    pub source_aligned_at_64: usize,
    pub control_favored_under_both_paths: usize,
    pub mixed_or_tied_at_64: usize,
}

pub fn run_path_source_crossover(
    samples: &[Sample],
    output_dir: impl AsRef<Path>,
) -> io::Result<PathSourceReport> {
    run_path_source_crossover_with_seeds(samples, output_dir, &R1_SEEDS, "ar-02b")
}

pub fn run_path_source_crossover_with_seeds(
    samples: &[Sample],
    output_dir: impl AsRef<Path>,
    seeds: &[u64],
    artifact_stem: &str,
) -> io::Result<PathSourceReport> {
    if samples.len() != TOTAL_SAMPLES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "AR-02B dataset length mismatch",
        ));
    }
    if seeds.is_empty()
        || seeds
            .iter()
            .enumerate()
            .any(|(index, seed)| seeds[..index].contains(seed))
        || artifact_stem.is_empty()
        || !artifact_stem
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "AR-02B seed list or artifact stem is invalid",
        ));
    }
    let output_dir = output_dir.as_ref();
    std::fs::create_dir_all(output_dir)?;
    let train = &samples[..TRAIN_SAMPLES];
    let (class_index, cell_index, margin_index) = verifier_indices(train);
    let mut matches = BufWriter::new(File::create(
        output_dir.join(format!("{artifact_stem}-matches.csv")),
    )?);
    let mut crossovers = BufWriter::new(File::create(
        output_dir.join(format!("{artifact_stem}-crossovers.csv")),
    )?);
    let mut paths = BufWriter::new(File::create(
        output_dir.join(format!("{artifact_stem}-paths.csv")),
    )?);
    let mut checkpoints = BufWriter::new(File::create(
        output_dir.join(format!("{artifact_stem}-checkpoints.csv")),
    )?);
    write_headers(&mut matches, &mut crossovers, &mut paths, &mut checkpoints)?;

    let mut report = PathSourceReport {
        seeds: seeds.len(),
        ..PathSourceReport::default()
    };
    let mut complete_h64: Vec<(u64, f64, f64)> = Vec::new();
    for &seed in seeds {
        let snapshots =
            replay_cell_trajectory(train, seed, &class_index, &cell_index, &margin_index);
        report.snapshots += snapshots.len();
        for snapshot in snapshots {
            writeln!(
                checkpoints,
                "{seed:016x},{},{:.9},{:016x}",
                snapshot.step,
                snapshot.model.loss(train),
                parameter_fingerprint(&snapshot.model)
            )?;
            let selection = select_cell_program(
                &snapshot.model,
                train,
                seed,
                snapshot.step,
                &class_index,
                &cell_index,
                &margin_index,
            );
            let Some(g3_program) = selection.program.filter(|program| program.len == 2) else {
                report_control_miss_rows(&mut matches, seed, snapshot, selection.program)?;
                continue;
            };
            report.pair_program_snapshots += 1;
            let g3_utility = exact_program_value(
                &snapshot.model,
                train,
                snapshot.model.loss(train),
                g3_program,
            );
            let controls = matched_same_block_controls(
                &snapshot.model,
                train,
                selection.group,
                g3_program,
                g3_utility,
                seed,
                snapshot.step,
            );
            let valid_count = controls.iter().flatten().count();
            report.matched_controls += valid_count;
            report.pair_snapshots_without_controls += usize::from(valid_count == 0);
            report_control_rows(
                &mut matches,
                seed,
                snapshot,
                selection.group,
                g3_program,
                g3_utility,
                &controls,
            )?;
            if valid_count == 0 {
                continue;
            }

            let mut g3_source = snapshot.model;
            apply_checked(&mut g3_source, g3_program).expect("selected G3 program is legal");
            let path_g3 = generate_frozen_path(
                g3_source,
                train,
                seed,
                snapshot.step,
                &class_index,
                &cell_index,
                &margin_index,
            );
            report.generated_paths += 1;
            report.invalid_source_paths += usize::from(path_g3.invalid_source_step != 0);
            for (control_slot, maybe_control) in controls.into_iter().enumerate() {
                let Some(control) = maybe_control else {
                    continue;
                };
                let mut control_source = snapshot.model;
                apply_checked(&mut control_source, control.program)
                    .expect("matched control is legal in its source state");
                let path_control = generate_frozen_path(
                    control_source,
                    train,
                    seed,
                    snapshot.step,
                    &class_index,
                    &cell_index,
                    &margin_index,
                );
                report.generated_paths += 1;
                report.invalid_source_paths += usize::from(path_control.invalid_source_step != 0);

                let replay_g3 =
                    replay_path(snapshot.model, g3_program, control.program, &path_g3, train);
                let replay_control = replay_path(
                    snapshot.model,
                    g3_program,
                    control.program,
                    &path_control,
                    train,
                );
                report.invalid_replay_paths += usize::from(replay_g3.invalid_step != 0)
                    + usize::from(replay_control.invalid_step != 0);
                report.max_telescoping_residual = report
                    .max_telescoping_residual
                    .max(replay_g3.telescoping_residual.abs())
                    .max(replay_control.telescoping_residual.abs());
                report.max_parameter_distance_drift = report
                    .max_parameter_distance_drift
                    .max(replay_g3.max_distance_drift)
                    .max(replay_control.max_distance_drift);
                write_path_rows(
                    &mut paths,
                    seed,
                    snapshot,
                    control_slot,
                    "selected",
                    g3_program,
                    control.program,
                    &path_g3,
                    train,
                )?;
                write_path_rows(
                    &mut paths,
                    seed,
                    snapshot,
                    control_slot,
                    "matched_control",
                    g3_program,
                    control.program,
                    &path_control,
                    train,
                )?;

                let mut source_residual = 0.0_f64;
                for (horizon_index, &horizon) in HORIZONS.iter().enumerate() {
                    let g3_point = replay_g3.points[horizon_index];
                    let control_point = replay_control.points[horizon_index];
                    let source_interaction = match (g3_point, control_point) {
                        (Some(g3), Some(control)) => {
                            let residual = ((g3.gap - control.gap)
                                - (g3.cumulative_mixed - control.cumulative_mixed))
                                .abs();
                            source_residual = source_residual.max(residual);
                            Some(g3.gap - control.gap)
                        }
                        _ => None,
                    };
                    writeln!(
                        crossovers,
                        "{seed:016x},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
                        snapshot.step,
                        control_slot,
                        horizon,
                        bool_csv(g3_point.is_some()),
                        bool_csv(control_point.is_some()),
                        option_f64(g3_point.map(|point| point.gap)),
                        option_f64(control_point.map(|point| point.gap)),
                        option_f64(source_interaction),
                        option_f64(g3_point.map(|point| point.cumulative_mixed)),
                        option_f64(control_point.map(|point| point.cumulative_mixed)),
                        option_f64(g3_point.map(|point| point.distance)),
                        option_f64(control_point.map(|point| point.distance)),
                        replay_g3.invalid_step,
                        replay_control.invalid_step,
                    )?;
                }
                report.max_source_identity_residual =
                    report.max_source_identity_residual.max(source_residual);
                if replay_g3.telescoping_residual.abs() > LOSS_TOLERANCE
                    || replay_control.telescoping_residual.abs() > LOSS_TOLERANCE
                    || source_residual > LOSS_TOLERANCE
                {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        format!(
                            "AR-02B crossover identity exceeded tolerance at seed {seed:016x}, step {}",
                            snapshot.step
                        ),
                    ));
                }
                if let (Some(g3), Some(control)) = (
                    replay_g3.points[HORIZONS.len() - 1],
                    replay_control.points[HORIZONS.len() - 1],
                ) {
                    let delta_g3 = g3.gap;
                    let delta_control = control.gap;
                    complete_h64.push((seed, delta_g3, delta_control));
                    report.complete_crossovers += 1;
                    if delta_g3 < 0.0 && delta_control < 0.0 {
                        report.g3_favored_under_both_paths += 1;
                    } else if delta_g3 < 0.0 && delta_control > 0.0 {
                        report.source_aligned_at_64 += 1;
                    } else if delta_g3 > 0.0 && delta_control > 0.0 {
                        report.control_favored_under_both_paths += 1;
                    } else {
                        report.mixed_or_tied_at_64 += 1;
                    }
                }
            }
        }
        eprintln!(
            "{artifact_stem} seed {seed:016x}: replayed cell-V48 trajectory to commits {:?}",
            SNAPSHOT_STEPS
        );
    }
    for writer in [&mut matches, &mut crossovers, &mut paths, &mut checkpoints] {
        writer.flush()?;
    }
    if !complete_h64.is_empty() {
        let count = complete_h64.len() as f64;
        report.mean_delta_selected_path_h64 =
            complete_h64.iter().map(|value| value.1).sum::<f64>() / count;
        report.mean_delta_matched_control_path_h64 =
            complete_h64.iter().map(|value| value.2).sum::<f64>() / count;
        report.mean_source_interaction_h64 = complete_h64
            .iter()
            .map(|value| value.1 - value.2)
            .sum::<f64>()
            / count;
    }
    write_seed_summary(
        output_dir.join(format!("{artifact_stem}-seeds.csv")),
        &complete_h64,
        seeds,
    )?;
    write_report(
        output_dir.join(format!("{artifact_stem}-report.json")),
        report,
        artifact_stem,
    )?;
    Ok(report)
}

fn verifier_indices(train: &[Sample]) -> (StrataIndex, StrataIndex, StrataIndex) {
    let classes = std::array::from_fn(|index| train[index].target as u8);
    let cells = std::array::from_fn(|index| (index / TRAIN_PER_CELL) as u8);
    let margins = build_margin_strata(train);
    (
        StrataIndex::new(&classes, CLASSES),
        StrataIndex::new(&cells, CELLS),
        StrataIndex::new(&margins.ids, MARGIN_STRATA),
    )
}

fn replay_cell_trajectory(
    train: &[Sample],
    seed: u64,
    class_index: &StrataIndex,
    cell_index: &StrataIndex,
    margin_index: &StrataIndex,
) -> Vec<Snapshot> {
    let mut model = Model::initial();
    let mut snapshots = Vec::with_capacity(SNAPSHOT_STEPS.len());
    for global_commit in 0..SNAPSHOT_STEPS[SNAPSHOT_STEPS.len() - 1] {
        let selection = select_cell_program(
            &model,
            train,
            seed,
            global_commit,
            class_index,
            cell_index,
            margin_index,
        );
        if let Some(program) = selection.program {
            apply_checked(&mut model, program).expect("cell runtime selected legal action");
        }
        let step = global_commit + 1;
        if SNAPSHOT_STEPS.contains(&step) {
            snapshots.push(Snapshot { step, model });
        }
    }
    assert_eq!(snapshots.len(), SNAPSHOT_STEPS.len());
    snapshots
}

fn select_cell_program(
    model: &Model,
    train: &[Sample],
    seed: u64,
    global_commit: usize,
    class_index: &StrataIndex,
    cell_index: &StrataIndex,
    margin_index: &StrataIndex,
) -> Selection {
    let evidence_round = global_commit / COMMITS_PER_EVIDENCE;
    let proposal_ids = batch_indices(seed, evidence_round, PROPOSAL_STREAM);
    let proposal = indexed_samples(train, &proposal_ids);
    let verifier = make_verifier(
        train,
        VerifierKind::CellWeighted,
        48,
        seed,
        evidence_round,
        class_index,
        cell_index,
        margin_index,
    );
    let proposal_baseline = model.loss(&proposal);
    let verifier_baseline = verifier.loss(model);
    let (groups, group_count) = partition(global_commit % PARAMS);
    let mut selected = Selection::default();
    for &group in &groups[..group_count] {
        let (candidate, _) = select_group(
            model,
            &proposal,
            proposal_baseline,
            &verifier,
            verifier_baseline,
            group,
        );
        if let Some(candidate) = candidate
            && selected
                .program
                .is_none_or(|current| candidate.utility > current.utility)
        {
            selected.program = Some(candidate);
            selected.group = group;
        }
    }
    selected
}

fn matched_same_block_controls(
    model: &Model,
    train: &[Sample],
    group: Group,
    g3_program: Program,
    g3_utility: f32,
    seed: u64,
    global_commit: usize,
) -> [Option<MatchedProgram>; MATCH_COUNT] {
    let baseline = model.loss(train);
    let mut eligible = Vec::with_capacity(ACTION_VALUES.len() * ACTION_VALUES.len());
    let mut ordinal = 0;
    for &left_delta in &ACTION_VALUES {
        for &right_delta in &ACTION_VALUES {
            let program = Program {
                left: group.left,
                right: group.right,
                deltas: [left_delta, right_delta],
                len: 2,
                utility: 0.0,
            };
            let current_ordinal = ordinal;
            ordinal += 1;
            if same_program(Some(program), Some(g3_program)) || !program_is_legal(model, program) {
                continue;
            }
            let utility = exact_program_value(model, train, baseline, program);
            if utility_stratum(utility) != utility_stratum(g3_utility) {
                continue;
            }
            let utility_gap = (utility - g3_utility).abs();
            if utility_gap <= MATCH_TOLERANCE {
                eligible.push((
                    utility_gap,
                    deterministic_match_key(seed, global_commit, current_ordinal),
                    MatchedProgram {
                        program,
                        utility,
                        utility_gap,
                    },
                ));
            }
        }
    }
    eligible.sort_by(|left, right| {
        left.0
            .total_cmp(&right.0)
            .then_with(|| left.1.cmp(&right.1))
    });
    let mut result = [None; MATCH_COUNT];
    for (slot, (_, _, matched)) in eligible.into_iter().take(MATCH_COUNT).enumerate() {
        result[slot] = Some(matched);
    }
    result
}

fn generate_frozen_path(
    mut model: Model,
    train: &[Sample],
    seed: u64,
    initial_commit: usize,
    class_index: &StrataIndex,
    cell_index: &StrataIndex,
    margin_index: &StrataIndex,
) -> FrozenPath {
    let mut programs = Vec::with_capacity(FUTURE_COMMITS);
    let mut invalid_source_step = 0;
    for offset in 1..=FUTURE_COMMITS {
        let global_commit = initial_commit + offset;
        let selection = select_cell_program(
            &model,
            train,
            seed,
            global_commit,
            class_index,
            cell_index,
            margin_index,
        );
        if let Some(program) = selection.program {
            if !program_is_legal(&model, program) {
                invalid_source_step = offset;
                break;
            }
            apply_unclamped(&mut model, program);
            programs.push(Some(program));
        } else {
            programs.push(None);
        }
    }
    FrozenPath {
        programs,
        invalid_source_step,
    }
}

fn replay_path(
    base: Model,
    g3_program: Program,
    control_program: Program,
    path: &FrozenPath,
    train: &[Sample],
) -> PathReplay {
    let mut g3 = base;
    let mut control = base;
    assert!(apply_checked(&mut g3, g3_program).is_ok());
    assert!(apply_checked(&mut control, control_program).is_ok());
    let initial_gap = f64::from(g3.loss(train) - control.loss(train));
    let initial_distance = f64::from(parameter_distance(&g3, &control));
    let mut replay = PathReplay {
        points: std::array::from_fn(|_| None),
        replayed_commits: 0,
        invalid_step: 0,
        telescoping_residual: 0.0,
        max_distance_drift: 0.0,
    };
    replay.points[0] = Some(PathPoint {
        gap: initial_gap,
        cumulative_mixed: 0.0,
        distance: initial_distance,
    });
    let mut gap = initial_gap;
    let mut cumulative_mixed = 0.0;
    for (index, &maybe_program) in path.programs.iter().enumerate() {
        let future_step = index + 1;
        if let Some(program) = maybe_program {
            if !program_is_legal(&g3, program) || !program_is_legal(&control, program) {
                replay.invalid_step = future_step;
                break;
            }
            apply_unclamped(&mut g3, program);
            apply_unclamped(&mut control, program);
            let new_gap = f64::from(g3.loss(train) - control.loss(train));
            let mixed = new_gap - gap;
            cumulative_mixed += mixed;
            gap = new_gap;
            replay.replayed_commits += 1;
        }
        let horizon = future_step + 1;
        if let Some(point_index) = HORIZONS.iter().position(|&candidate| candidate == horizon) {
            let distance = f64::from(parameter_distance(&g3, &control));
            replay.max_distance_drift = replay
                .max_distance_drift
                .max((distance - initial_distance).abs());
            replay.points[point_index] = Some(PathPoint {
                gap,
                cumulative_mixed,
                distance,
            });
        }
    }
    replay.telescoping_residual = replay
        .points
        .iter()
        .rev()
        .find_map(|point| *point)
        .map_or(0.0, |last| (last.gap - initial_gap) - last.cumulative_mixed);
    replay
}

fn program_is_legal(model: &Model, program: Program) -> bool {
    if program.len == 0 {
        return true;
    }
    let left = model.parameters[program.left] + program.deltas[0];
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&left) {
        return false;
    }
    program.len != 2
        || (LOWER_BOUND..=UPPER_BOUND)
            .contains(&(model.parameters[program.right] + program.deltas[1]))
}

fn apply_checked(model: &mut Model, program: Program) -> Result<(), ()> {
    if !program_is_legal(model, program) {
        return Err(());
    }
    apply_unclamped(model, program);
    Ok(())
}

fn apply_unclamped(model: &mut Model, program: Program) {
    if program.len == 0 {
        return;
    }
    model.parameters[program.left] += program.deltas[0];
    if program.len == 2 {
        model.parameters[program.right] += program.deltas[1];
    }
}

fn parameter_distance(left: &Model, right: &Model) -> f32 {
    left.parameters
        .iter()
        .zip(right.parameters)
        .map(|(left, right)| {
            let delta = left - right;
            delta * delta
        })
        .sum::<f32>()
        .sqrt()
}

fn parameter_fingerprint(model: &Model) -> u64 {
    model
        .parameters
        .iter()
        .fold(0xcbf2_9ce4_8422_2325, |hash, value| {
            (hash ^ u64::from(value.to_bits())).wrapping_mul(0x100_0000_01b3)
        })
}

fn report_control_miss_rows(
    writer: &mut impl Write,
    seed: u64,
    snapshot: Snapshot,
    selected: Option<Program>,
) -> io::Result<()> {
    for slot in 0..MATCH_COUNT {
        writeln!(
            writer,
            "{seed:016x},{},false,{slot},-1,-1,0,0,0,0,0,0,0,0,0,0",
            snapshot.step,
        )?;
    }
    let _ = selected;
    Ok(())
}

fn report_control_rows(
    writer: &mut impl Write,
    seed: u64,
    snapshot: Snapshot,
    group: Group,
    g3_program: Program,
    g3_utility: f32,
    controls: &[Option<MatchedProgram>; MATCH_COUNT],
) -> io::Result<()> {
    for (slot, maybe_control) in controls.iter().enumerate() {
        let Some(control) = maybe_control else {
            writeln!(
                writer,
                "{seed:016x},{},false,{slot},{},{},{:.9},{:.9},{:.9},0,0,0,0,0,{},{}",
                snapshot.step,
                group.left,
                group.right,
                g3_program.deltas[0],
                g3_program.deltas[1],
                g3_utility,
                utility_stratum(g3_utility),
                MATCH_TOLERANCE
            )?;
            continue;
        };
        writeln!(
            writer,
            "{seed:016x},{},true,{slot},{},{},{:.9},{:.9},{:.9},{:.9},{:.9},{:.9},{:.9},{},{},{:.9}",
            snapshot.step,
            group.left,
            group.right,
            g3_program.deltas[0],
            g3_program.deltas[1],
            g3_utility,
            control.program.deltas[0],
            control.program.deltas[1],
            control.utility,
            control.utility_gap,
            utility_stratum(control.utility),
            utility_stratum(g3_utility),
            MATCH_TOLERANCE
        )?;
    }
    Ok(())
}

fn write_path_rows(
    writer: &mut impl Write,
    seed: u64,
    snapshot: Snapshot,
    control_slot: usize,
    source: &str,
    g3_program: Program,
    control_program: Program,
    path: &FrozenPath,
    train: &[Sample],
) -> io::Result<()> {
    let mut g3 = snapshot.model;
    let mut control = snapshot.model;
    apply_unclamped(&mut g3, g3_program);
    apply_unclamped(&mut control, control_program);
    let mut gap = f64::from(g3.loss(train) - control.loss(train));
    let mut cumulative_mixed = 0.0_f64;
    writeln!(
        writer,
        "{seed:016x},{},{control_slot},{source},0,1,initial,-1,-1,0,0,0,{gap:.12e},{gap:.12e},0,true,0",
        snapshot.step
    )?;
    for (index, &maybe_program) in path.programs.iter().enumerate() {
        let step = index + 1;
        let horizon = step + 1;
        let Some(program) = maybe_program else {
            writeln!(
                writer,
                "{seed:016x},{},{control_slot},{source},{step},{horizon},noop,-1,-1,0,0,0,{gap:.12e},{gap:.12e},{cumulative_mixed:.12e},true,0",
                snapshot.step
            )?;
            continue;
        };
        if !program_is_legal(&g3, program) || !program_is_legal(&control, program) {
            writeln!(
                writer,
                "{seed:016x},{},{control_slot},{source},{step},{horizon},invalid,{},{},{},{:.9},{:.9},{gap:.12e},,{cumulative_mixed:.12e},false,{step}",
                snapshot.step,
                program.left,
                program.right,
                program.len,
                program.deltas[0],
                program.deltas[1]
            )?;
            break;
        }
        apply_unclamped(&mut g3, program);
        apply_unclamped(&mut control, program);
        let new_gap = f64::from(g3.loss(train) - control.loss(train));
        let mixed = new_gap - gap;
        cumulative_mixed += mixed;
        writeln!(
            writer,
            "{seed:016x},{},{control_slot},{source},{step},{horizon},program,{},{},{},{:.9},{:.9},{gap:.12e},{new_gap:.12e},{cumulative_mixed:.12e},true,0",
            snapshot.step,
            program.left,
            program.right,
            program.len,
            program.deltas[0],
            program.deltas[1]
        )?;
        gap = new_gap;
    }
    Ok(())
}

fn bool_csv(value: bool) -> &'static str {
    if value { "true" } else { "false" }
}

fn option_f64(value: Option<f64>) -> String {
    value.map_or_else(String::new, |number| format!("{number:.12e}"))
}
