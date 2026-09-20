use adaptive_runtime_ar_00::{Model, PARAMS, Sample, xor_samples};

pub const EPOCHS: usize = 3_000;
pub const PRIMITIVE_BUDGET: usize = PARAMS;
pub const ACTION_VALUES: [f32; 11] = [
    0.0, -0.02, 0.02, -0.01, 0.01, -0.005, 0.005, -0.0025, 0.0025, -0.00125, 0.00125,
];
pub const LOWER_BOUND: f32 = -3.0;
pub const UPPER_BOUND: f32 = 3.0;
pub const MAX_GROUP_SIZE: usize = 2;
pub const SEEDS: [u64; 3] = [
    0x2b7e_1516_28ae_d2a6,
    0x77a1_9d3c_4e28_0b51,
    0x1111_2222_3333_4444,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Arm {
    K0Exact,
    K1Beam1,
    K2Beam2,
    K3Beam3,
    K4Beam4,
    K5Beam5,
}

impl Arm {
    pub const ALL: [Self; 6] = [
        Self::K0Exact,
        Self::K1Beam1,
        Self::K2Beam2,
        Self::K3Beam3,
        Self::K4Beam4,
        Self::K5Beam5,
    ];

    pub const fn label(self) -> &'static str {
        match self {
            Self::K0Exact => "K0-exact-11x11",
            Self::K1Beam1 => "K1-beam-1x1",
            Self::K2Beam2 => "K2-beam-2x2",
            Self::K3Beam3 => "K3-beam-3x3",
            Self::K4Beam4 => "K4-beam-4x4",
            Self::K5Beam5 => "K5-beam-5x5",
        }
    }

    pub const fn beam_width(self) -> Option<usize> {
        match self {
            Self::K0Exact => None,
            Self::K1Beam1 => Some(1),
            Self::K2Beam2 => Some(2),
            Self::K3Beam3 => Some(3),
            Self::K4Beam4 => Some(4),
            Self::K5Beam5 => Some(5),
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Telemetry {
    pub selected_primitives: u64,
    pub programs: u64,
    pub proposal_evaluations: u64,
    pub compound_evaluations: u64,
    pub utility_evaluations: u64,
    pub predicted_utility: f32,
    pub realized_utility: f32,
    pub pair_events: u64,
}

impl Telemetry {
    fn absorb(&mut self, other: Self) {
        self.selected_primitives += other.selected_primitives;
        self.programs += other.programs;
        self.proposal_evaluations += other.proposal_evaluations;
        self.compound_evaluations += other.compound_evaluations;
        self.utility_evaluations += other.utility_evaluations;
        self.predicted_utility += other.predicted_utility;
        self.realized_utility += other.realized_utility;
        self.pair_events += other.pair_events;
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct CurvePoint {
    pub epoch: usize,
    pub loss_before: f32,
    pub loss_after: f32,
    pub accuracy_after: f32,
    pub selected_primitives: u64,
    pub programs: u64,
    pub proposal_evaluations: u64,
    pub compound_evaluations: u64,
    pub utility_evaluations: u64,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct CoverageMetrics {
    pub ever_covered_fraction: f32,
    pub min_pair_coverage: u32,
    pub max_pair_coverage: u32,
    pub planning_steps: u64,
    pub pair_events: u64,
    pub time_to_full_coverage: Option<u64>,
}

#[derive(Clone, Debug)]
pub struct RunSummary {
    pub arm: Arm,
    pub seed: u64,
    pub final_loss: f32,
    pub final_accuracy: f32,
    pub final_mse: f32,
    pub telemetry: Telemetry,
    pub coverage: CoverageMetrics,
    pub coverage_matrix: [[u32; PARAMS]; PARAMS],
    pub curve: Vec<CurvePoint>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Group {
    pub indices: [usize; MAX_GROUP_SIZE],
    pub len: usize,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Partition {
    pub groups: [Group; PARAMS],
    pub group_count: usize,
}

#[derive(Clone, Copy, Debug, Default)]
struct Program {
    indices: [usize; MAX_GROUP_SIZE],
    deltas: [f32; MAX_GROUP_SIZE],
    len: usize,
    utility: f32,
}

#[derive(Clone, Copy, Debug, Default)]
struct Action {
    delta: f32,
    utility: f32,
}

#[derive(Clone, Copy, Debug)]
struct Rng {
    state: u64,
}

impl Rng {
    const fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    fn next(&mut self) -> u64 {
        let mut value = self.state;
        value ^= value << 7;
        value ^= value >> 9;
        value ^= value << 8;
        self.state = value;
        value
    }

    fn shuffle<const N: usize>(&mut self, values: &mut [usize; N]) {
        for index in (1..N).rev() {
            values.swap(index, (self.next() as usize) % (index + 1));
        }
    }
}

const EMPTY_GROUP: Group = Group {
    indices: [0; MAX_GROUP_SIZE],
    len: 0,
};

fn random_partition(rng: &mut Rng) -> Partition {
    let mut order = [0usize; PARAMS];
    for (index, value) in order.iter_mut().enumerate() {
        *value = index;
    }
    rng.shuffle(&mut order);
    let mut partition = Partition {
        groups: [EMPTY_GROUP; PARAMS],
        group_count: 0,
    };
    for chunk in order.chunks_exact(2) {
        partition.groups[partition.group_count] = Group {
            indices: [chunk[0], chunk[1]],
            len: 2,
        };
        partition.group_count += 1;
    }
    partition.groups[partition.group_count] = Group {
        indices: [order[16], order[16]],
        len: 1,
    };
    partition.group_count += 1;
    partition
}

fn co_grouped(partition: Partition, first: usize, second: usize) -> bool {
    partition.groups[..partition.group_count]
        .iter()
        .any(|group| {
            group.indices[..group.len].contains(&first)
                && group.indices[..group.len].contains(&second)
        })
}

#[allow(clippy::needless_range_loop)]
fn uncovered_score(partition: Partition, covered: &[[bool; PARAMS]; PARAMS]) -> usize {
    let mut score = 0;
    for first in 0..PARAMS {
        for second in first + 1..PARAMS {
            score += usize::from(co_grouped(partition, first, second) && !covered[first][second]);
        }
    }
    score
}

fn build_schedule(seed: u64) -> Vec<Partition> {
    let mut rng = Rng::new(seed);
    let mut covered = [[false; PARAMS]; PARAMS];
    let mut schedule = Vec::with_capacity(32);
    for _ in 0..64 {
        let mut best = random_partition(&mut rng);
        let mut best_score = uncovered_score(best, &covered);
        for _ in 0..256 {
            let candidate = random_partition(&mut rng);
            let score = uncovered_score(candidate, &covered);
            if score > best_score {
                best = candidate;
                best_score = score;
            }
        }
        for group in best.groups[..best.group_count]
            .iter()
            .filter(|group| group.len == 2)
        {
            let left = group.indices[0];
            let right = group.indices[1];
            covered[left][right] = true;
            covered[right][left] = true;
        }
        schedule.push(best);
        if (0..PARAMS).all(|first| (first + 1..PARAMS).all(|second| covered[first][second])) {
            break;
        }
    }
    schedule
}

fn record_coverage(coverage: &mut [[u32; PARAMS]; PARAMS], partition: Partition) -> u64 {
    let mut events = 0;
    for group in partition.groups[..partition.group_count]
        .iter()
        .filter(|group| group.len == 2)
    {
        let left = group.indices[0];
        let right = group.indices[1];
        coverage[left][right] = coverage[left][right].saturating_add(1);
        coverage[right][left] = coverage[left][right];
        events += 1;
    }
    events
}

fn singleton_actions(
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    index: usize,
) -> ([Action; 11], u64) {
    let mut actions = [Action::default(); 11];
    for (action_index, &delta) in ACTION_VALUES.iter().enumerate() {
        let candidate_value = model.parameters[index] + delta;
        if !(LOWER_BOUND..=UPPER_BOUND).contains(&candidate_value) {
            continue;
        }
        let mut candidate = *model;
        candidate.parameters[index] = candidate_value;
        actions[action_index] = Action {
            delta,
            utility: baseline - candidate.loss_and_gradient(samples).0,
        };
    }
    (actions, ACTION_VALUES.len() as u64)
}

fn exact_pair_utility(
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    left: usize,
    right: usize,
    left_delta: f32,
    right_delta: f32,
) -> f32 {
    let left_value = model.parameters[left] + left_delta;
    let right_value = model.parameters[right] + right_delta;
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&left_value)
        || !(LOWER_BOUND..=UPPER_BOUND).contains(&right_value)
    {
        return f32::NEG_INFINITY;
    }
    let mut candidate = *model;
    candidate.parameters[left] = left_value;
    candidate.parameters[right] = right_value;
    baseline - candidate.loss_and_gradient(samples).0
}

fn make_pair(group: Group, left_index: usize, right_index: usize, utility: f32) -> Program {
    Program {
        indices: group.indices,
        deltas: [ACTION_VALUES[left_index], ACTION_VALUES[right_index]],
        len: 2,
        utility,
    }
}

fn best_singleton_program(
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
) -> (Option<Program>, Telemetry) {
    let (actions, evaluations) = singleton_actions(model, samples, baseline, group.indices[0]);
    let mut best = Action::default();
    for action in actions {
        if action.utility > best.utility {
            best = action;
        }
    }
    if best.utility > 0.0 {
        (
            Some(Program {
                indices: group.indices,
                deltas: [best.delta, 0.0],
                len: 1,
                utility: best.utility,
            }),
            Telemetry {
                proposal_evaluations: evaluations,
                utility_evaluations: evaluations,
                ..Telemetry::default()
            },
        )
    } else {
        (
            None,
            Telemetry {
                proposal_evaluations: evaluations,
                utility_evaluations: evaluations,
                ..Telemetry::default()
            },
        )
    }
}

#[allow(clippy::needless_range_loop)]
fn exact_pair_program(
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
) -> (Option<Program>, Telemetry) {
    let mut best = Program {
        indices: group.indices,
        len: 2,
        utility: 0.0,
        ..Program::default()
    };
    let mut evaluations = 0;
    for left in 0..ACTION_VALUES.len() {
        for right in 0..ACTION_VALUES.len() {
            let utility = exact_pair_utility(
                model,
                samples,
                baseline,
                group.indices[0],
                group.indices[1],
                ACTION_VALUES[left],
                ACTION_VALUES[right],
            );
            evaluations += 1;
            if utility > best.utility {
                best = make_pair(group, left, right, utility);
            }
        }
    }
    if best.utility > 0.0 {
        (
            Some(best),
            Telemetry {
                compound_evaluations: evaluations,
                utility_evaluations: evaluations,
                ..Telemetry::default()
            },
        )
    } else {
        (
            None,
            Telemetry {
                compound_evaluations: evaluations,
                utility_evaluations: evaluations,
                ..Telemetry::default()
            },
        )
    }
}

fn ordered_top(actions: &[Action; 11], count: usize) -> [usize; 5] {
    let mut order = [0usize; 11];
    for (index, value) in order.iter_mut().enumerate() {
        *value = index;
    }
    order.sort_by(|left, right| actions[*right].utility.total_cmp(&actions[*left].utility));
    let mut top = [0usize; 5];
    for index in 0..5 {
        top[index] = order[index.min(count.saturating_sub(1))];
    }
    top
}

#[allow(clippy::needless_range_loop)]
fn approximate_pair_program(
    arm: Arm,
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
) -> (Option<Program>, Telemetry) {
    let (left_actions, left_evaluations) =
        singleton_actions(model, samples, baseline, group.indices[0]);
    let (right_actions, right_evaluations) =
        singleton_actions(model, samples, baseline, group.indices[1]);
    let singleton_evaluations = left_evaluations + right_evaluations;
    let width = arm.beam_width().expect("K0 uses the exact pair path");
    let top_left = ordered_top(&left_actions, width);
    let top_right = ordered_top(&right_actions, width);
    let mut best = Program {
        indices: group.indices,
        len: 2,
        ..Program::default()
    };
    let mut telemetry = Telemetry {
        proposal_evaluations: singleton_evaluations,
        utility_evaluations: singleton_evaluations,
        ..Telemetry::default()
    };
    for &left in &top_left[..width] {
        for &right in &top_right[..width] {
            let utility = exact_pair_utility(
                model,
                samples,
                baseline,
                group.indices[0],
                group.indices[1],
                ACTION_VALUES[left],
                ACTION_VALUES[right],
            );
            telemetry.compound_evaluations += 1;
            telemetry.utility_evaluations += 1;
            if utility > best.utility {
                best = make_pair(group, left, right, utility);
            }
        }
    }
    if best.utility > 0.0 {
        (Some(best), telemetry)
    } else {
        (None, telemetry)
    }
}

fn best_program(
    arm: Arm,
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
) -> (Option<Program>, Telemetry) {
    if group.len == 1 {
        return best_singleton_program(model, samples, baseline, group);
    }
    if arm == Arm::K0Exact {
        exact_pair_program(model, samples, baseline, group)
    } else {
        approximate_pair_program(arm, model, samples, baseline, group)
    }
}

fn commit(model: &mut Model, samples: &[Sample], baseline: f32, program: Program) -> Telemetry {
    for slot in 0..program.len {
        model.parameters[program.indices[slot]] += program.deltas[slot];
    }
    let realized = baseline - model.loss_and_gradient(samples).0;
    Telemetry {
        selected_primitives: program.len as u64,
        programs: 1,
        predicted_utility: program.utility,
        realized_utility: realized,
        ..Telemetry::default()
    }
}

fn advance_epoch(
    model: &mut Model,
    samples: &[Sample],
    arm: Arm,
    schedule: &[Partition],
    schedule_index: &mut usize,
    coverage: &mut [[u32; PARAMS]; PARAMS],
) -> Telemetry {
    let mut telemetry = Telemetry::default();
    let mut remaining = PRIMITIVE_BUDGET;
    while remaining > 0 {
        let partition = schedule[*schedule_index % schedule.len()];
        *schedule_index += 1;
        telemetry.pair_events += record_coverage(coverage, partition);
        let baseline = model.loss_and_gradient(samples).0;
        let mut best = None;
        for group in partition.groups[..partition.group_count].iter().copied() {
            if group.len > remaining {
                continue;
            }
            let (candidate, evaluations) = best_program(arm, model, samples, baseline, group);
            telemetry.absorb(evaluations);
            if let Some(candidate) = candidate
                && best.is_none_or(|current: Program| candidate.utility > current.utility)
            {
                best = Some(candidate);
            }
        }
        let Some(program) = best else {
            break;
        };
        telemetry.absorb(commit(model, samples, baseline, program));
        remaining -= program.len;
    }
    telemetry
}

#[allow(clippy::needless_range_loop)]
fn coverage_metrics(
    coverage: &[[u32; PARAMS]; PARAMS],
    planning_steps: u64,
    pair_events: u64,
    full_coverage_time: Option<u64>,
) -> CoverageMetrics {
    let mut values = Vec::with_capacity(PARAMS * (PARAMS - 1) / 2);
    let mut ever = 0;
    for first in 0..PARAMS {
        for second in first + 1..PARAMS {
            let value = coverage[first][second];
            values.push(value);
            ever += usize::from(value > 0);
        }
    }
    CoverageMetrics {
        ever_covered_fraction: ever as f32 / values.len() as f32,
        min_pair_coverage: values.iter().copied().min().unwrap_or(0),
        max_pair_coverage: values.iter().copied().max().unwrap_or(0),
        planning_steps,
        pair_events,
        time_to_full_coverage: full_coverage_time,
    }
}

pub fn run(samples: &[Sample], arm: Arm, seed: u64) -> RunSummary {
    let schedule = build_schedule(seed);
    let mut schedule_index = 0;
    let mut coverage = [[0u32; PARAMS]; PARAMS];
    let mut full_coverage_time = None;
    let mut model = Model::initial();
    let mut total = Telemetry::default();
    let mut curve = Vec::with_capacity(EPOCHS);
    let mut planning_steps = 0;
    for epoch in 0..EPOCHS {
        let loss_before = model.loss_and_gradient(samples).0;
        let before_steps = schedule_index;
        let epoch_telemetry = advance_epoch(
            &mut model,
            samples,
            arm,
            &schedule,
            &mut schedule_index,
            &mut coverage,
        );
        planning_steps += (schedule_index - before_steps) as u64;
        if full_coverage_time.is_none()
            && (0..PARAMS)
                .all(|first| (first + 1..PARAMS).all(|second| coverage[first][second] > 0))
        {
            full_coverage_time = Some(planning_steps);
        }
        total.absorb(epoch_telemetry);
        curve.push(CurvePoint {
            epoch,
            loss_before,
            loss_after: model.loss_and_gradient(samples).0,
            accuracy_after: model.accuracy(samples),
            selected_primitives: epoch_telemetry.selected_primitives,
            programs: epoch_telemetry.programs,
            proposal_evaluations: epoch_telemetry.proposal_evaluations,
            compound_evaluations: epoch_telemetry.compound_evaluations,
            utility_evaluations: epoch_telemetry.utility_evaluations,
        });
    }
    let (final_loss, _) = model.loss_and_gradient(samples);
    RunSummary {
        arm,
        seed,
        final_loss,
        final_accuracy: model.accuracy(samples),
        final_mse: model.simd_mean_squared_error(samples),
        telemetry: total,
        coverage: coverage_metrics(
            &coverage,
            planning_steps,
            total.pair_events,
            full_coverage_time,
        ),
        coverage_matrix: coverage,
        curve,
    }
}

pub fn run_all(samples: &[Sample]) -> Vec<RunSummary> {
    let mut results = Vec::with_capacity(Arm::ALL.len() * SEEDS.len());
    for arm in Arm::ALL {
        for seed in SEEDS {
            results.push(run(samples, arm, seed));
        }
    }
    results
}

#[derive(Clone, Debug)]
struct Snapshot {
    epoch: usize,
    model: Model,
    schedule_index: usize,
}

fn trajectory_snapshots(samples: &[Sample], seed: u64, arm: Arm) -> Vec<Snapshot> {
    let schedule = build_schedule(seed);
    let capture = [0usize, 10, 50, 100, 250, 500, 1_000, 2_000];
    let mut snapshots = Vec::with_capacity(capture.len());
    let mut schedule_index = 0;
    let mut coverage = [[0u32; PARAMS]; PARAMS];
    let mut model = Model::initial();
    for epoch in 0..EPOCHS {
        if capture.contains(&epoch) {
            snapshots.push(Snapshot {
                epoch,
                model,
                schedule_index,
            });
        }
        let _ = advance_epoch(
            &mut model,
            samples,
            arm,
            &schedule,
            &mut schedule_index,
            &mut coverage,
        );
    }
    snapshots
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct AuditRow {
    pub arm: Arm,
    pub seed: u64,
    pub epoch: usize,
    pub left: usize,
    pub right: usize,
    pub exact_block_value: f32,
    pub selected_block_value: f32,
    pub exact_regret: f32,
    pub shortlist_recall: bool,
    pub compound_agreement: bool,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct AuditSummary {
    pub arm: Arm,
    pub seed: u64,
    pub groups: u64,
    pub top_compound_agreement: f32,
    pub shortlist_recall: f32,
    pub mean_exact_regret: f32,
    pub max_exact_regret: f32,
    pub cumulative_exact_regret: f32,
    pub mean_block_value_error: f32,
    pub cross_block_order_accuracy: f32,
    pub inversion_count: u64,
    pub margin_weighted_order_regret: f32,
    pub near_tie_inversion_fraction: f32,
    pub shortlist_failures: u64,
    pub scheduler_failures: u64,
    pub first_divergence_epoch: Option<usize>,
}

fn action_index(delta: f32) -> Option<usize> {
    ACTION_VALUES
        .iter()
        .position(|candidate| (*candidate - delta).abs() < 1e-7)
}

fn shortlist_contains(
    arm: Arm,
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
    exact: Option<Program>,
) -> bool {
    let Some(exact) = exact else {
        return true;
    };
    let Some(width) = arm.beam_width() else {
        return true;
    };
    let (left, _) = singleton_actions(model, samples, baseline, group.indices[0]);
    let (right, _) = singleton_actions(model, samples, baseline, group.indices[1]);
    let top_left = ordered_top(&left, width);
    let top_right = ordered_top(&right, width);
    let Some(left_index) = action_index(exact.deltas[0]) else {
        return false;
    };
    let Some(right_index) = action_index(exact.deltas[1]) else {
        return false;
    };
    top_left[..width].contains(&left_index) && top_right[..width].contains(&right_index)
}

fn same_program(left: Option<Program>, right: Option<Program>) -> bool {
    match (left, right) {
        (Some(left), Some(right)) => left.indices == right.indices && left.deltas == right.deltas,
        (None, None) => true,
        _ => false,
    }
}

fn ordering_matches(exact_delta: f32, approximate_delta: f32) -> bool {
    exact_delta.signum() == approximate_delta.signum()
}

pub fn audit_all(samples: &[Sample]) -> Vec<AuditSummary> {
    let mut summaries = Vec::with_capacity(Arm::ALL.len() * SEEDS.len());
    for arm in Arm::ALL {
        for seed in SEEDS {
            let schedule = build_schedule(seed);
            let mut rows = Vec::with_capacity(8 * (PARAMS / 2));
            let mut groups = 0_u64;
            let mut agreements = 0_u64;
            let mut recalled = 0_u64;
            let mut regret_sum = 0.0_f32;
            let mut max_regret = 0.0_f32;
            let mut block_error_sum = 0.0_f32;
            let mut order_total = 0_u64;
            let mut order_correct = 0_u64;
            let mut inversion_count = 0_u64;
            let mut margin_weighted_regret = 0.0_f32;
            let mut near_tie_inversions = 0_u64;
            let mut shortlist_failures = 0_u64;
            let mut scheduler_failures = 0_u64;
            let mut cumulative_regret = 0.0_f32;
            let mut first_divergence_epoch = None;

            for snapshot in trajectory_snapshots(samples, seed, arm) {
                let partition = schedule[snapshot.schedule_index % schedule.len()];
                let baseline = snapshot.model.loss_and_gradient(samples).0;
                let mut blocks = Vec::with_capacity(partition.group_count);
                for group in partition.groups[..partition.group_count]
                    .iter()
                    .copied()
                    .filter(|group| group.len == 2)
                {
                    let (exact, _) = exact_pair_program(&snapshot.model, samples, baseline, group);
                    let (selected, _) =
                        best_program(arm, &snapshot.model, samples, baseline, group);
                    let exact_value = exact.map_or(0.0, |program| program.utility);
                    let selected_value = selected.map_or(0.0, |program| program.utility);
                    let exact_regret = (exact_value - selected_value).max(0.0);
                    let shortlist_recall_value =
                        shortlist_contains(arm, &snapshot.model, samples, baseline, group, exact);
                    let compound_agreement = same_program(exact, selected);
                    rows.push(AuditRow {
                        arm,
                        seed,
                        epoch: snapshot.epoch,
                        left: group.indices[0],
                        right: group.indices[1],
                        exact_block_value: exact_value,
                        selected_block_value: selected_value,
                        exact_regret,
                        shortlist_recall: shortlist_recall_value,
                        compound_agreement,
                    });
                    groups += 1;
                    agreements += u64::from(compound_agreement);
                    recalled += u64::from(shortlist_recall_value);
                    regret_sum += exact_regret;
                    max_regret = max_regret.max(exact_regret);
                    block_error_sum += exact_regret;
                    if !compound_agreement && first_divergence_epoch.is_none() {
                        first_divergence_epoch = Some(snapshot.epoch);
                    }
                    blocks.push((
                        group,
                        exact,
                        selected,
                        exact_value,
                        selected_value,
                        shortlist_recall_value,
                    ));
                }

                for first in 0..blocks.len() {
                    for second in first + 1..blocks.len() {
                        let exact_delta = blocks[first].3 - blocks[second].3;
                        let approximate_delta = blocks[first].4 - blocks[second].4;
                        order_total += 1;
                        if ordering_matches(exact_delta, approximate_delta) {
                            order_correct += 1;
                        } else {
                            inversion_count += 1;
                            let margin = exact_delta.abs();
                            margin_weighted_regret += margin;
                            if margin <= 1e-5 {
                                near_tie_inversions += 1;
                            }
                        }
                    }
                }

                let exact_best = blocks
                    .iter()
                    .enumerate()
                    .max_by(|left, right| left.1.3.total_cmp(&right.1.3))
                    .map(|(index, block)| (index, block.3));
                let selected_best = blocks
                    .iter()
                    .enumerate()
                    .max_by(|left, right| left.1.4.total_cmp(&right.1.4))
                    .map(|(index, block)| (index, block.4));
                if let (Some((exact_index, exact_value)), Some((selected_index, selected_value))) =
                    (exact_best, selected_best)
                {
                    cumulative_regret += (exact_value - selected_value).max(0.0);
                    if exact_index != selected_index {
                        if blocks[exact_index].5 {
                            scheduler_failures += 1;
                        } else {
                            shortlist_failures += 1;
                        }
                    }
                }
            }
            summaries.push(AuditSummary {
                arm,
                seed,
                groups,
                top_compound_agreement: agreements as f32 / groups.max(1) as f32,
                shortlist_recall: recalled as f32 / groups.max(1) as f32,
                mean_exact_regret: regret_sum / groups.max(1) as f32,
                max_exact_regret: max_regret,
                cumulative_exact_regret: cumulative_regret,
                mean_block_value_error: block_error_sum / groups.max(1) as f32,
                cross_block_order_accuracy: order_correct as f32 / order_total.max(1) as f32,
                inversion_count,
                margin_weighted_order_regret: margin_weighted_regret,
                near_tie_inversion_fraction: near_tie_inversions as f32
                    / inversion_count.max(1) as f32,
                shortlist_failures,
                scheduler_failures,
                first_divergence_epoch,
            });
        }
    }
    summaries
}

pub fn xor_samples_for_tests() -> [Sample; 4] {
    xor_samples()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn schedule_reaches_full_pair_coverage() {
        let schedule = build_schedule(SEEDS[0]);
        let mut coverage = [[false; PARAMS]; PARAMS];
        for partition in schedule {
            for group in partition.groups[..partition.group_count]
                .iter()
                .filter(|group| group.len == 2)
            {
                coverage[group.indices[0]][group.indices[1]] = true;
                coverage[group.indices[1]][group.indices[0]] = true;
            }
        }
        assert!((0..PARAMS).all(|first| (first + 1..PARAMS).all(|second| coverage[first][second])));
    }

    #[test]
    fn short_approximation_run_produces_actions() {
        let result = run(&xor_samples(), Arm::K3Beam3, SEEDS[0]);
        assert!(result.telemetry.selected_primitives > 0);
        assert!(result.telemetry.utility_evaluations > 0);
        assert!(result.telemetry.proposal_evaluations > 0);
        assert!(result.telemetry.compound_evaluations > 0);
    }
}
