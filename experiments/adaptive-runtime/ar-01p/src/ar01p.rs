use super::*;
use std::collections::BTreeMap;
use std::io::{self, Write};

const FUTURE_COMMITS: usize = 63;
const BASE_PROGRAMS: usize = TOTAL_COMMITS + FUTURE_COMMITS + 1;
const LOSS_TOLERANCE: f64 = 2.0e-6;
const CLASS_EXAMPLES: usize = TRAIN_SAMPLES / CLASSES;
const EXAMPLES_PER_GEOMETRY_STRATUM: usize = CLASS_EXAMPLES / 8;

#[derive(Clone, Copy)]
struct Snapshot {
    model: Model,
    global_commit: usize,
    group: Group,
    g3_program: Program,
    g3_utility: f32,
    controls: [Option<MatchedControl>; MATCHED_CONTROLS],
}

#[derive(Clone, Copy)]
struct MixedMetric {
    loss: f32,
    relu_mask: u16,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
enum Stream {
    L0 = 0,
    L2 = 2,
}

impl Stream {
    fn label(self) -> &'static str {
        match self {
            Self::L0 => "L0-original-frozen",
            Self::L2 => "L2-phase17-frozen",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
#[repr(u8)]
enum ActionRelation {
    NoOp = 0,
    DirectOverlap = 1,
    SameHiddenUnit = 2,
    AdjacentLayer = 3,
    SameLayerUnrelated = 4,
    StructuralRemote = 5,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
enum MaskTransition {
    None = 0,
    New = 1,
    Expanding = 2,
    Contracting = 3,
    Turnover = 4,
    Stable = 5,
}

impl MaskTransition {
    fn label(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::New => "new",
            Self::Expanding => "expanding",
            Self::Contracting => "contracting",
            Self::Turnover => "turnover",
            Self::Stable => "stable-difference",
        }
    }
}

impl ActionRelation {
    fn label(self) -> &'static str {
        match self {
            Self::NoOp => "no-op",
            Self::DirectOverlap => "direct-overlap",
            Self::SameHiddenUnit => "same-hidden-unit",
            Self::AdjacentLayer => "adjacent-layer-coarse",
            Self::SameLayerUnrelated => "same-layer-unrelated",
            Self::StructuralRemote => "structural-remote",
        }
    }
}

#[derive(Clone, Copy, Default)]
struct Aggregate {
    events: u64,
    sum_j: f64,
    sum_abs_j: f64,
    positive_j: f64,
    negative_j: f64,
}

impl Aggregate {
    fn add(&mut self, value: f64) {
        self.events += 1;
        self.sum_j += value;
        self.sum_abs_j += value.abs();
        if value > 0.0 {
            self.positive_j += value;
        } else {
            self.negative_j += value;
        }
    }
}

#[derive(Clone, Copy)]
struct MaskEvent {
    abs_j: f64,
    diff_before: u16,
    diff_after: u16,
    newly_different: u16,
    resolved: u16,
    transition: MaskTransition,
}

#[derive(Clone, Debug)]
struct ComparisonSummary {
    id: u64,
    seed: u64,
    stream: Stream,
    control_slot: u8,
    global_commit: usize,
    group_left: usize,
    group_right: usize,
    initial_delta_left: f32,
    initial_delta_right: f32,
    control_delta_left: f32,
    control_delta_right: f32,
    initial_gap: f64,
    final_gap: f64,
    cumulative_j: f64,
    positive_j: f64,
    negative_j: f64,
    max_abs_j: f64,
    top1_favorable_share: f64,
    top5_favorable_share: f64,
    top10_favorable_share: f64,
    reversal_horizon: usize,
    valid_future_commits: usize,
    invalid_future_step: usize,
    invalid_parameter: usize,
    telescoping_residual: f64,
    max_event_decomposition_residual: f64,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct PReport {
    pub seeds: usize,
    pub snapshots: usize,
    pub matched_controls: usize,
    pub comparisons: usize,
    pub path_events: usize,
    pub invalid_paths: usize,
    pub max_telescoping_residual: f64,
    pub max_event_decomposition_residual: f64,
    pub l0_mean_final_gap: f64,
    pub l2_mean_final_gap: f64,
    pub l0_reversal_rate: f64,
    pub l2_reversal_rate: f64,
}

fn sample_metric(model: &Model, sample: Sample) -> MixedMetric {
    let (logits, hidden_1, hidden_2) = model.logits(sample);
    let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let normalizer = logits
        .iter()
        .map(|value| (*value - maximum).exp())
        .sum::<f32>();
    let loss = normalizer.ln() + maximum - logits[sample.target as usize];
    let mut relu_mask = 0_u16;
    for (unit, &value) in hidden_1.iter().enumerate() {
        relu_mask |= u16::from(value > 0.0) << unit;
    }
    for (unit, &value) in hidden_2.iter().enumerate() {
        relu_mask |= u16::from(value > 0.0) << (HIDDEN_1 + unit);
    }
    MixedMetric { loss, relu_mask }
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

fn geometry_slot(sample_index: usize) -> (usize, usize) {
    let class = sample_index / CLASS_EXAMPLES;
    let within_class = sample_index % CLASS_EXAMPLES;
    (class, within_class / EXAMPLES_PER_GEOMETRY_STRATUM)
}

fn parameter_layer(index: usize) -> usize {
    if index < W2 {
        0
    } else if index < W3 {
        1
    } else {
        2
    }
}

fn hidden_endpoints(index: usize) -> (u16, u16) {
    if index < B1 {
        (1 << (index / 2), 0)
    } else if index < W2 {
        (1 << (index - B1), 0)
    } else if index < B2 {
        let offset = index - W2;
        (1 << (offset % HIDDEN_1), 1 << (offset / HIDDEN_1))
    } else if index < W3 {
        (0, 1 << (index - B2))
    } else if index < B3 {
        (0, 1 << ((index - W3) % HIDDEN_2))
    } else {
        (0, 0)
    }
}

fn changed_indices(program: Option<Program>) -> [(usize, bool); 2] {
    let Some(program) = program else {
        return [(0, false); 2];
    };
    [
        (program.left, program.deltas[0] != 0.0),
        (program.right, program.len == 2 && program.deltas[1] != 0.0),
    ]
}

fn action_relation(delta_support: &[usize], future: Option<Program>) -> ActionRelation {
    let mut action = [0usize; 2];
    let mut action_count = 0;
    for (index, changes) in changed_indices(future) {
        if changes {
            action[action_count] = index;
            action_count += 1;
        }
    }
    if action_count == 0 {
        return ActionRelation::NoOp;
    }
    if action
        .iter()
        .take(action_count)
        .any(|index| delta_support.iter().any(|support| index == support))
    {
        return ActionRelation::DirectOverlap;
    }
    for &left in &action[..action_count] {
        let (left_h1, left_h2) = hidden_endpoints(left);
        for &right in delta_support {
            let (right_h1, right_h2) = hidden_endpoints(right);
            if (left_h1 & right_h1) != 0 || (left_h2 & right_h2) != 0 {
                return ActionRelation::SameHiddenUnit;
            }
        }
    }
    let mut same_layer = false;
    let mut adjacent_layer = false;
    for &left in &action[..action_count] {
        for &right in delta_support {
            match parameter_layer(left).abs_diff(parameter_layer(right)) {
                0 => same_layer = true,
                1 => adjacent_layer = true,
                _ => {}
            }
        }
    }
    if adjacent_layer {
        ActionRelation::AdjacentLayer
    } else if same_layer {
        ActionRelation::SameLayerUnrelated
    } else {
        ActionRelation::StructuralRemote
    }
}

fn action_fields(program: Option<Program>) -> (isize, isize, f32, f32) {
    program.map_or((-1, -1, 0.0, 0.0), |program| {
        (
            program.left as isize,
            if program.len == 2 {
                program.right as isize
            } else {
                -1
            },
            program.deltas[0],
            if program.len == 2 {
                program.deltas[1]
            } else {
                0.0
            },
        )
    })
}

fn mask_transition(before: u16, after: u16, newly_different: u16, resolved: u16) -> MaskTransition {
    if before == 0 && after == 0 {
        MaskTransition::None
    } else if before == 0 {
        MaskTransition::New
    } else if after > before {
        MaskTransition::Expanding
    } else if after < before {
        MaskTransition::Contracting
    } else if newly_different > 0 || resolved > 0 {
        MaskTransition::Turnover
    } else {
        MaskTransition::Stable
    }
}

fn shifted_frozen_stream(snapshot: Snapshot, train: &[Sample], seed: u64) -> Vec<Option<Program>> {
    let mut source = snapshot.model;
    commit(&mut source, snapshot.g3_program);
    let spec = ContinuationSpec {
        family: 2,
        replicate: 0,
        evidence_seed: seed,
        schedule_phase: CONTINUATION_SCHEDULE_PHASE,
    };
    let mut stream = Vec::with_capacity(FUTURE_COMMITS);
    for offset in 1..=FUTURE_COMMITS {
        let selection =
            continuation_selection(&source, train, spec, snapshot.global_commit + offset);
        stream.push(selection.program);
        commit_optional(&mut source, selection.program);
    }
    stream
}

fn base_snapshots(
    train: &[Sample],
    seed: u64,
    progress: bool,
) -> (Vec<Snapshot>, Vec<Option<Program>>, Model) {
    let mut model = Model::initial();
    let mut snapshots = Vec::with_capacity(TOTAL_COMMITS / SAME_BLOCK_EVERY);
    let mut programs = Vec::with_capacity(BASE_PROGRAMS);
    for global_commit in 0..BASE_PROGRAMS {
        let (proposal, _, _, selection) = g3_context(&model, train, seed, global_commit);
        if global_commit < TOTAL_COMMITS
            && global_commit.is_multiple_of(SAME_BLOCK_EVERY)
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
        programs.push(selection.program);
        commit_optional(&mut model, selection.program);
        if progress && global_commit > 0 && global_commit.is_multiple_of(800) {
            eprintln!("AR-01P seed {seed:016x}: base {global_commit}/{BASE_PROGRAMS}");
        }
    }
    (snapshots, programs, model)
}

#[allow(clippy::too_many_arguments)]
fn compare_path(
    writer: &mut impl Write,
    id: u64,
    seed: u64,
    snapshot: Snapshot,
    control_slot: usize,
    control: MatchedControl,
    stream_kind: Stream,
    stream: &[Option<Program>],
    train: &[Sample],
    structure: &mut BTreeMap<(u64, u8, u8, u8), Aggregate>,
    geometry: &mut BTreeMap<(u64, u8, u8, u8, u8), Aggregate>,
    masks: &mut Vec<MaskEvent>,
) -> io::Result<ComparisonSummary> {
    let mut g3 = snapshot.model;
    let mut matched = snapshot.model;
    commit(&mut g3, snapshot.g3_program);
    commit(&mut matched, control.program);
    let g3_delta_left =
        g3.parameters[snapshot.group.left] - snapshot.model.parameters[snapshot.group.left];
    let g3_delta_right =
        g3.parameters[snapshot.group.right] - snapshot.model.parameters[snapshot.group.right];
    let control_delta_left =
        matched.parameters[snapshot.group.left] - snapshot.model.parameters[snapshot.group.left];
    let control_delta_right =
        matched.parameters[snapshot.group.right] - snapshot.model.parameters[snapshot.group.right];
    let delta_support: Vec<usize> = (0..PARAMS)
        .filter(|&index| g3.parameters[index] != matched.parameters[index])
        .collect();
    let initial_gap = f64::from(g3.loss(train) - matched.loss(train));
    let mut gap = initial_gap;
    let mut cumulative_j = 0.0;
    let mut positive_j = 0.0;
    let mut negative_j = 0.0;
    let mut max_abs_j = 0.0_f64;
    let mut favorable = Vec::with_capacity(FUTURE_COMMITS);
    let mut reversal_horizon = 0;
    let mut valid_steps = 0;
    let mut invalid_future_step = 0;
    let mut invalid_parameter = usize::MAX;
    let mut max_event_decomposition_residual = 0.0_f64;

    for (step_index, &future) in stream.iter().take(FUTURE_COMMITS).enumerate() {
        if let Some(parameter) = program_illegal_parameter(&g3, future)
            .or_else(|| program_illegal_parameter(&matched, future))
        {
            invalid_future_step = step_index + 1;
            invalid_parameter = parameter;
            break;
        }
        let (action_left, action_right, action_delta_left, action_delta_right) =
            action_fields(future);
        let relation = action_relation(&delta_support, future);
        let mut class_sums = [0.0_f64; CLASSES];
        let mut geometry_sums = [0.0_f64; 8];
        let mut diff_before = 0_u16;
        let mut diff_after = 0_u16;
        let mut newly_different = 0_u16;
        let mut resolved = 0_u16;
        let mut sample_sum_j = 0.0_f64;

        let mut g3_after = g3;
        let mut control_after = matched;
        commit_optional(&mut g3_after, future);
        commit_optional(&mut control_after, future);
        for (sample_index, &sample) in train.iter().enumerate() {
            let g_before = sample_metric(&g3, sample);
            let c_before = sample_metric(&matched, sample);
            let g_after = sample_metric(&g3_after, sample);
            let c_after = sample_metric(&control_after, sample);
            let sample_j = f64::from(g_after.loss - c_after.loss - g_before.loss + c_before.loss);
            let (class, stratum) = geometry_slot(sample_index);
            class_sums[class] += sample_j;
            geometry_sums[stratum] += sample_j;
            sample_sum_j += sample_j;
            let before_differs = g_before.relu_mask != c_before.relu_mask;
            let after_differs = g_after.relu_mask != c_after.relu_mask;
            diff_before += u16::from(before_differs);
            diff_after += u16::from(after_differs);
            newly_different += u16::from(!before_differs && after_differs);
            resolved += u16::from(before_differs && !after_differs);
        }
        let new_gap = f64::from(g3_after.loss(train) - control_after.loss(train));
        let exact_j = new_gap - gap;
        let per_example_j = sample_sum_j / TRAIN_SAMPLES as f64;
        let event_residual = exact_j - per_example_j;
        max_event_decomposition_residual =
            max_event_decomposition_residual.max(event_residual.abs());
        let horizon = step_index + 2;
        if reversal_horizon == 0
            && ((initial_gap > 0.0 && new_gap <= 0.0) || (initial_gap < 0.0 && new_gap >= 0.0))
        {
            reversal_horizon = horizon;
        }
        cumulative_j += exact_j;
        if exact_j > 0.0 {
            positive_j += exact_j;
        } else {
            negative_j += exact_j;
            favorable.push(-exact_j);
        }
        max_abs_j = max_abs_j.max(exact_j.abs());
        valid_steps += 1;

        structure
            .entry((seed, stream_kind as u8, control_slot as u8, relation as u8))
            .or_default()
            .add(exact_j);
        for class in 0..CLASSES {
            geometry
                .entry((seed, stream_kind as u8, control_slot as u8, 0, class as u8))
                .or_default()
                .add(class_sums[class] / CLASS_EXAMPLES as f64);
        }
        for stratum in 0..8 {
            geometry
                .entry((
                    seed,
                    stream_kind as u8,
                    control_slot as u8,
                    1,
                    stratum as u8,
                ))
                .or_default()
                .add(geometry_sums[stratum] / (CLASSES * EXAMPLES_PER_GEOMETRY_STRATUM) as f64);
        }
        masks.push(MaskEvent {
            abs_j: exact_j.abs(),
            diff_before,
            diff_after,
            newly_different,
            resolved,
            transition: mask_transition(diff_before, diff_after, newly_different, resolved),
        });

        writeln!(
            writer,
            "{:016x},{id},{},{},{},{},{},{},{},{},{:.6},{:.6},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{},{},{},{},{},{}",
            seed,
            stream_kind.label(),
            control_slot,
            snapshot.global_commit,
            horizon,
            snapshot.group.left,
            snapshot.group.right,
            action_left,
            action_right,
            action_delta_left,
            action_delta_right,
            gap,
            new_gap,
            exact_j,
            per_example_j,
            event_residual,
            class_sums[0] / CLASS_EXAMPLES as f64,
            class_sums[1] / CLASS_EXAMPLES as f64,
            class_sums[2] / CLASS_EXAMPLES as f64,
            geometry_sums[0] / (CLASSES * EXAMPLES_PER_GEOMETRY_STRATUM) as f64,
            geometry_sums[1] / (CLASSES * EXAMPLES_PER_GEOMETRY_STRATUM) as f64,
            geometry_sums[2] / (CLASSES * EXAMPLES_PER_GEOMETRY_STRATUM) as f64,
            geometry_sums[3] / (CLASSES * EXAMPLES_PER_GEOMETRY_STRATUM) as f64,
            geometry_sums[4] / (CLASSES * EXAMPLES_PER_GEOMETRY_STRATUM) as f64,
            geometry_sums[5] / (CLASSES * EXAMPLES_PER_GEOMETRY_STRATUM) as f64,
            geometry_sums[6] / (CLASSES * EXAMPLES_PER_GEOMETRY_STRATUM) as f64,
            geometry_sums[7] / (CLASSES * EXAMPLES_PER_GEOMETRY_STRATUM) as f64,
            diff_before,
            diff_after,
            newly_different,
            resolved,
            relation.label(),
            mask_transition(diff_before, diff_after, newly_different, resolved).label(),
        )?;
        gap = new_gap;
        g3 = g3_after;
        matched = control_after;
    }

    favorable.sort_by(|left, right| right.total_cmp(left));
    let favorable_total = -negative_j;
    let share = |count: usize| -> f64 {
        if favorable_total == 0.0 {
            0.0
        } else {
            favorable.iter().take(count).sum::<f64>() / favorable_total
        }
    };
    let telescoping_residual = (gap - initial_gap) - cumulative_j;
    Ok(ComparisonSummary {
        id,
        seed,
        stream: stream_kind,
        control_slot: control_slot as u8,
        global_commit: snapshot.global_commit,
        group_left: snapshot.group.left,
        group_right: snapshot.group.right,
        initial_delta_left: g3_delta_left,
        initial_delta_right: g3_delta_right,
        control_delta_left,
        control_delta_right,
        initial_gap,
        final_gap: gap,
        cumulative_j,
        positive_j,
        negative_j,
        max_abs_j,
        top1_favorable_share: share(1),
        top5_favorable_share: share(5),
        top10_favorable_share: share(10),
        reversal_horizon,
        valid_future_commits: valid_steps,
        invalid_future_step,
        invalid_parameter,
        telescoping_residual,
        max_event_decomposition_residual,
    })
}

mod output;
pub use output::run_mixed_difference_ledger;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mixed_difference_matches_loss_gap_change_and_sample_decomposition() {
        let dataset = spiral_dataset();
        let train = &dataset.samples[..TRAIN_SAMPLES];
        let base = Model::initial();
        let mut g3 = base;
        let mut control = base;
        commit(
            &mut g3,
            Program {
                left: W1,
                right: W1 + 1,
                deltas: [0.01, -0.005],
                len: 2,
                ..Program::default()
            },
        );
        commit(
            &mut control,
            Program {
                left: W1,
                right: W1 + 1,
                deltas: [0.005, -0.005],
                len: 2,
                ..Program::default()
            },
        );
        let before = f64::from(g3.loss(train) - control.loss(train));
        let common = Program {
            left: W2,
            right: B2,
            deltas: [0.005, -0.005],
            len: 2,
            ..Program::default()
        };
        let mut g3_after = g3;
        let mut control_after = control;
        commit(&mut g3_after, common);
        commit(&mut control_after, common);
        let after = f64::from(g3_after.loss(train) - control_after.loss(train));
        let per_sample = train
            .iter()
            .map(|&sample| {
                f64::from(
                    sample_metric(&g3_after, sample).loss
                        - sample_metric(&control_after, sample).loss
                        - sample_metric(&g3, sample).loss
                        + sample_metric(&control, sample).loss,
                )
            })
            .sum::<f64>()
            / TRAIN_SAMPLES as f64;
        assert!(((after - before) - per_sample).abs() < 2.0e-6);
    }

    #[test]
    fn frozen_action_bounds_fail_closed() {
        let mut model = Model::initial();
        model.parameters[W1] = UPPER_BOUND;
        let illegal = Program {
            left: W1,
            deltas: [0.02, 0.0],
            len: 1,
            ..Program::default()
        };
        assert_eq!(program_illegal_parameter(&model, Some(illegal)), Some(W1));
        assert_eq!(program_illegal_parameter(&model, None), None);
    }

    #[test]
    fn action_relation_uses_explicit_layer_and_unit_boundaries() {
        let support = [W1];
        let program = |index| {
            Some(Program {
                left: index,
                deltas: [0.01, 0.0],
                len: 1,
                ..Program::default()
            })
        };
        assert_eq!(
            action_relation(&support, program(W1)),
            ActionRelation::DirectOverlap
        );
        assert_eq!(
            action_relation(&support, program(B1)),
            ActionRelation::SameHiddenUnit
        );
        assert_eq!(
            action_relation(&support, program(W1 + 2)),
            ActionRelation::SameLayerUnrelated
        );
        assert_eq!(
            action_relation(&support, program(B2)),
            ActionRelation::AdjacentLayer
        );
        assert_eq!(
            action_relation(&support, program(W3)),
            ActionRelation::StructuralRemote
        );
        assert_eq!(action_relation(&support, None), ActionRelation::NoOp);
    }

    #[test]
    fn stratification_matches_the_frozen_three_by_eight_layout() {
        assert_eq!(geometry_slot(0), (0, 0));
        assert_eq!(geometry_slot(4), (0, 1));
        assert_eq!(geometry_slot(CLASS_EXAMPLES), (1, 0));
        assert_eq!(geometry_slot(TRAIN_SAMPLES - 1), (CLASSES - 1, 7));
        assert_eq!(EXAMPLES_PER_GEOMETRY_STRATUM, 4);
    }

    #[test]
    fn relu_mask_transition_categories_are_exhaustive_and_ordered() {
        assert_eq!(mask_transition(0, 0, 0, 0), MaskTransition::None);
        assert_eq!(mask_transition(0, 2, 2, 0), MaskTransition::New);
        assert_eq!(mask_transition(2, 3, 1, 0), MaskTransition::Expanding);
        assert_eq!(mask_transition(3, 2, 0, 1), MaskTransition::Contracting);
        assert_eq!(mask_transition(2, 2, 1, 1), MaskTransition::Turnover);
        assert_eq!(mask_transition(2, 2, 0, 0), MaskTransition::Stable);
    }
}
