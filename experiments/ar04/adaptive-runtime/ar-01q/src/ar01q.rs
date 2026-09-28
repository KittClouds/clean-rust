use super::*;
use std::io::{self, Write};

const FUTURE_COMMITS: usize = 63;
const HORIZONS: [usize; 7] = [1, 2, 4, 8, 16, 32, 64];
const LOSS_TOLERANCE: f64 = 2.0e-6;

#[derive(Clone, Copy)]
struct Snapshot {
    model: Model,
    global_commit: usize,
    group: Group,
    g3_program: Program,
    g3_utility: f32,
    controls: [Option<MatchedControl>; MATCHED_CONTROLS],
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
enum PathSource {
    G3 = 0,
    Control = 1,
}

impl PathSource {
    fn label(self) -> &'static str {
        match self {
            Self::G3 => "P_G",
            Self::Control => "P_C",
        }
    }
}

struct FrozenPath {
    programs: Vec<Option<Program>>,
    invalid_source_step: usize,
}

#[derive(Clone, Copy, Debug, Default)]
struct HorizonPoint {
    horizon: usize,
    gap: Option<f64>,
    cumulative_j: Option<f64>,
    parameter_distance: Option<f64>,
}

#[derive(Clone, Copy, Debug, Default)]
struct PathResult {
    points: [HorizonPoint; HORIZONS.len()],
    initial_gap: f64,
    final_gap: f64,
    cumulative_j: f64,
    telescoping_residual: f64,
    parameter_distance_initial: f64,
    parameter_distance_final: f64,
    max_parameter_distance_drift: f64,
    generated_commits: usize,
    replayed_commits: usize,
    invalid_source_step: usize,
    invalid_replay_step: usize,
    complete: bool,
}

#[derive(Clone, Copy)]
struct Comparison {
    id: u64,
    seed: u64,
    control_slot: usize,
    snapshot: Snapshot,
    control: MatchedControl,
    path_g3: PathResult,
    path_control: PathResult,
}

#[derive(Clone, Copy, Debug, Default)]
struct HorizonAggregate {
    count: usize,
    delta_g_sum: f64,
    delta_c_sum: f64,
    source_interaction_sum: f64,
    j_g_sum: f64,
    j_c_sum: f64,
    distance_g_sum: f64,
    distance_c_sum: f64,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct QReport {
    pub seeds: usize,
    pub snapshots: usize,
    pub matched_controls: usize,
    pub comparisons: usize,
    pub generated_paths: usize,
    pub invalid_source_paths: usize,
    pub invalid_replay_paths: usize,
    pub invalid_replay_g3_paths: usize,
    pub invalid_replay_control_paths: usize,
    pub future_commits_replayed: usize,
    pub path_events: usize,
    pub complete_h64_crossovers: usize,
    pub max_telescoping_residual: f64,
    pub max_source_interaction_identity_residual: f64,
    pub max_parameter_distance_drift: f64,
    pub mean_delta_g_at_1: f64,
    pub mean_delta_g_at_64: f64,
    pub mean_delta_c_at_1: f64,
    pub mean_delta_c_at_64: f64,
    pub mean_source_interaction_at_64: f64,
    pub g3_favored_under_both_paths: usize,
    pub source_aligned_at_64: usize,
    pub g3_path_only_favors_g3: usize,
    pub control_path_only_favors_g3: usize,
    pub control_favored_under_both_paths: usize,
    pub neutral_or_tied_at_64: usize,
}

fn program_illegal_parameter(model: &Model, program: Option<Program>) -> Option<usize> {
    let program = program?;
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&(model.parameters[program.left] + program.deltas[0]))
    {
        return Some(program.left);
    }
    if program.len == 2
        && !(LOWER_BOUND..=UPPER_BOUND)
            .contains(&(model.parameters[program.right] + program.deltas[1]))
    {
        return Some(program.right);
    }
    None
}

fn collect_snapshots(train: &[Sample], seed: u64) -> Vec<Snapshot> {
    let mut model = Model::initial();
    let mut snapshots = Vec::with_capacity(TOTAL_COMMITS / SAME_BLOCK_EVERY);
    for global_commit in 0..TOTAL_COMMITS {
        let (proposal, _, _, selection) = g3_context(&model, train, seed, global_commit);
        if global_commit.is_multiple_of(SAME_BLOCK_EVERY)
            && let Some(program) = selection.program.filter(|program| program.len == 2)
        {
            let utility = exact_program_value(&model, train, model.loss(train), program);
            let controls = same_block_controls(
                &model,
                train,
                &proposal,
                selection.group,
                Some(program),
                utility,
                2,
                seed,
                global_commit,
            );
            snapshots.push(Snapshot {
                model,
                global_commit,
                group: selection.group,
                g3_program: program,
                g3_utility: utility,
                controls,
            });
        }
        commit_optional(&mut model, selection.program);
        if global_commit > 0 && global_commit.is_multiple_of(800) {
            eprintln!("AR-01Q seed {seed:016x}: base {global_commit}/{TOTAL_COMMITS}");
        }
    }
    snapshots
}

fn generate_frozen_path(
    mut source: Model,
    train: &[Sample],
    seed: u64,
    snapshot_commit: usize,
) -> FrozenPath {
    let spec = ContinuationSpec {
        family: 0,
        replicate: 0,
        evidence_seed: seed,
        schedule_phase: 0,
    };
    let mut programs = Vec::with_capacity(FUTURE_COMMITS);
    let mut invalid_source_step = 0;
    for offset in 1..=FUTURE_COMMITS {
        let selection = continuation_selection(&source, train, spec, snapshot_commit + offset);
        if program_illegal_parameter(&source, selection.program).is_some() {
            invalid_source_step = offset;
            break;
        }
        programs.push(selection.program);
        commit_optional(&mut source, selection.program);
    }
    FrozenPath {
        programs,
        invalid_source_step,
    }
}

fn point_index(horizon: usize) -> Option<usize> {
    HORIZONS.iter().position(|&candidate| candidate == horizon)
}

fn write_path_header(writer: &mut impl Write) -> io::Result<()> {
    writeln!(
        writer,
        "comparison_id,seed,path_source,control_slot,snapshot_commit,pair_left,pair_right,future_step,horizon,program_left,program_right,delta_left,delta_right,gap_before,gap_after,j_exact,cumulative_j,parameter_distance,valid_event,invalid_parameter,source_invalid_step"
    )
}

#[allow(clippy::too_many_arguments)]
fn write_path_event(
    writer: &mut impl Write,
    id: u64,
    seed: u64,
    source: PathSource,
    control_slot: usize,
    snapshot: Snapshot,
    future_step: usize,
    horizon: usize,
    program: Option<Program>,
    gap_before: f64,
    gap_after: f64,
    j: Option<f64>,
    cumulative_j: f64,
    distance: f64,
    valid: bool,
    invalid_parameter: Option<usize>,
    invalid_source_step: usize,
) -> io::Result<()> {
    let (left, right, delta_left, delta_right) = program.map_or((-1_i64, -1_i64, 0.0, 0.0), |p| {
        (
            p.left as i64,
            if p.len == 2 { p.right as i64 } else { -1_i64 },
            p.deltas[0],
            if p.len == 2 { p.deltas[1] } else { 0.0 },
        )
    });
    writeln!(
        writer,
        "{id},{seed:016x},{},{control_slot},{},{},{},{future_step},{horizon},{left},{right},{delta_left:.8},{delta_right:.8},{gap_before:.12e},{gap_after:.12e},{},{cumulative_j:.12e},{distance:.12e},{},{},{}",
        source.label(),
        snapshot.global_commit,
        snapshot.group.left,
        snapshot.group.right,
        j.map_or_else(String::new, |value| format!("{value:.12e}")),
        u8::from(valid),
        invalid_parameter.map_or(-1_i64, |value| value as i64),
        if invalid_source_step == 0 {
            -1_i64
        } else {
            invalid_source_step as i64
        }
    )
}

fn replay_frozen_path(
    writer: &mut impl Write,
    id: u64,
    seed: u64,
    source: PathSource,
    control_slot: usize,
    snapshot: Snapshot,
    control: MatchedControl,
    frozen: &FrozenPath,
    train: &[Sample],
) -> io::Result<PathResult> {
    let mut g3 = snapshot.model;
    let mut matched = snapshot.model;
    commit(&mut g3, snapshot.g3_program);
    commit(&mut matched, control.program);

    let initial_gap = f64::from(g3.loss(train) - matched.loss(train));
    let initial_distance = f64::from(parameter_distance(&g3, &matched));
    let mut result = PathResult {
        initial_gap,
        final_gap: initial_gap,
        parameter_distance_initial: initial_distance,
        parameter_distance_final: initial_distance,
        generated_commits: frozen.programs.len(),
        invalid_source_step: frozen.invalid_source_step,
        ..PathResult::default()
    };
    result.points = HORIZONS.map(|horizon| HorizonPoint {
        horizon,
        ..HorizonPoint::default()
    });
    if let Some(index) = point_index(1) {
        result.points[index] = HorizonPoint {
            horizon: 1,
            gap: Some(initial_gap),
            cumulative_j: Some(0.0),
            parameter_distance: Some(initial_distance),
        };
    }
    write_path_event(
        writer,
        id,
        seed,
        source,
        control_slot,
        snapshot,
        0,
        1,
        None,
        initial_gap,
        initial_gap,
        Some(0.0),
        0.0,
        initial_distance,
        true,
        None,
        frozen.invalid_source_step,
    )?;

    let mut gap = initial_gap;
    let mut cumulative_j = 0.0;
    let mut max_distance_drift = 0.0_f64;
    for (index, &program) in frozen.programs.iter().enumerate() {
        let future_step = index + 1;
        if let Some(parameter) = program_illegal_parameter(&g3, program)
            .or_else(|| program_illegal_parameter(&matched, program))
        {
            result.invalid_replay_step = future_step;
            let distance = f64::from(parameter_distance(&g3, &matched));
            write_path_event(
                writer,
                id,
                seed,
                source,
                control_slot,
                snapshot,
                future_step,
                future_step + 1,
                program,
                gap,
                gap,
                None,
                cumulative_j,
                distance,
                false,
                Some(parameter),
                frozen.invalid_source_step,
            )?;
            break;
        }

        let mut g3_after = g3;
        let mut matched_after = matched;
        commit_optional(&mut g3_after, program);
        commit_optional(&mut matched_after, program);
        let new_gap = f64::from(g3_after.loss(train) - matched_after.loss(train));
        let j = new_gap - gap;
        cumulative_j += j;
        let distance = f64::from(parameter_distance(&g3_after, &matched_after));
        max_distance_drift = max_distance_drift.max((distance - initial_distance).abs());
        let horizon = future_step + 1;
        if let Some(point) = point_index(horizon) {
            result.points[point] = HorizonPoint {
                horizon,
                gap: Some(new_gap),
                cumulative_j: Some(cumulative_j),
                parameter_distance: Some(distance),
            };
        }
        write_path_event(
            writer,
            id,
            seed,
            source,
            control_slot,
            snapshot,
            future_step,
            horizon,
            program,
            gap,
            new_gap,
            Some(j),
            cumulative_j,
            distance,
            true,
            None,
            frozen.invalid_source_step,
        )?;
        gap = new_gap;
        g3 = g3_after;
        matched = matched_after;
        result.replayed_commits += 1;
    }

    result.final_gap = gap;
    result.cumulative_j = cumulative_j;
    result.parameter_distance_final = f64::from(parameter_distance(&g3, &matched));
    result.max_parameter_distance_drift = max_distance_drift;
    result.telescoping_residual = (result.final_gap - initial_gap) - cumulative_j;
    result.complete = frozen.programs.len() == FUTURE_COMMITS
        && frozen.invalid_source_step == 0
        && result.invalid_replay_step == 0
        && result.replayed_commits == FUTURE_COMMITS;
    Ok(result)
}

mod output;
pub use output::run_path_source_crossover;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identical_initial_states_generate_identical_l0_frozen_paths() {
        let dataset = spiral_dataset();
        let train = &dataset.samples[..TRAIN_SAMPLES];
        let first = Model::initial();
        let second = first;
        let a = generate_frozen_path(first, train, SEEDS[0], 0);
        let b = generate_frozen_path(second, train, SEEDS[0], 0);
        assert_eq!(a.invalid_source_step, 0);
        assert_eq!(b.invalid_source_step, 0);
        assert_eq!(a.programs.len(), FUTURE_COMMITS);
        assert_eq!(a.programs.len(), b.programs.len());
        for (left, right) in a.programs.iter().zip(&b.programs) {
            assert!(same_program(*left, *right));
        }
    }

    #[test]
    fn source_interaction_is_difference_of_the_two_mixed_sums() {
        let initial_gap = 0.0007_f64;
        let j_g = -0.00031_f64;
        let j_c = 0.00002_f64;
        let delta_g = initial_gap + j_g;
        let delta_c = initial_gap + j_c;
        let source_interaction = delta_g - delta_c;
        assert!((source_interaction - (j_g - j_c)).abs() < 1.0e-12);
    }

    #[test]
    fn replay_bounds_check_does_not_clamp_invalid_programs() {
        let mut model = Model::initial();
        model.parameters[W1] = UPPER_BOUND;
        let program = Program {
            left: W1,
            deltas: [0.02, 0.0],
            len: 1,
            ..Program::default()
        };
        assert_eq!(program_illegal_parameter(&model, Some(program)), Some(W1));
        assert_eq!(model.parameters[W1], UPPER_BOUND);
    }
}
