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
    I0Exact,
    I1Additive,
    I2AnchorCrossTerm,
    I3ConditionalBeam,
    I4CartesianBeam,
    I5Sampled,
}

impl Arm {
    pub const ALL: [Self; 6] = [
        Self::I0Exact,
        Self::I1Additive,
        Self::I2AnchorCrossTerm,
        Self::I3ConditionalBeam,
        Self::I4CartesianBeam,
        Self::I5Sampled,
    ];

    pub const fn label(self) -> &'static str {
        match self {
            Self::I0Exact => "I0-exact",
            Self::I1Additive => "I1-additive",
            Self::I2AnchorCrossTerm => "I2-anchor-cross-term",
            Self::I3ConditionalBeam => "I3-conditional-beam",
            Self::I4CartesianBeam => "I4-cartesian-beam",
            Self::I5Sampled => "I5-sampled",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Telemetry {
    pub selected_primitives: u64,
    pub programs: u64,
    pub utility_evaluations: u64,
    pub predicted_utility: f32,
    pub realized_utility: f32,
    pub pair_events: u64,
}

impl Telemetry {
    fn absorb(&mut self, other: Self) {
        self.selected_primitives += other.selected_primitives;
        self.programs += other.programs;
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
) -> (Option<Program>, u64) {
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
            evaluations,
        )
    } else {
        (None, evaluations)
    }
}

#[allow(clippy::needless_range_loop)]
fn exact_pair_program(
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
) -> (Option<Program>, u64) {
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
        (Some(best), evaluations)
    } else {
        (None, evaluations)
    }
}

fn ordered_top(actions: &[Action; 11], count: usize) -> [usize; 3] {
    let mut order = [0usize; 11];
    for (index, value) in order.iter_mut().enumerate() {
        *value = index;
    }
    order.sort_by(|left, right| actions[*right].utility.total_cmp(&actions[*left].utility));
    [
        order[0],
        order[1.min(count.saturating_sub(1))],
        order[2.min(count.saturating_sub(1))],
    ]
}

#[allow(clippy::needless_range_loop)]
fn approximate_pair_program(
    arm: Arm,
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
) -> (Option<Program>, u64) {
    let (left_actions, left_evaluations) =
        singleton_actions(model, samples, baseline, group.indices[0]);
    let (right_actions, right_evaluations) =
        singleton_actions(model, samples, baseline, group.indices[1]);
    let singleton_evaluations = left_evaluations + right_evaluations;
    let top_left = ordered_top(&left_actions, 3);
    let top_right = ordered_top(&right_actions, 3);
    let mut best = Program {
        indices: group.indices,
        len: 2,
        ..Program::default()
    };
    let mut evaluations = singleton_evaluations;

    match arm {
        Arm::I1Additive => {
            for left in 0..11 {
                for right in 0..11 {
                    let utility = left_actions[left].utility + right_actions[right].utility;
                    if utility > best.utility {
                        best = make_pair(group, left, right, utility);
                    }
                }
            }
        }
        Arm::I2AnchorCrossTerm => {
            let anchor_left = top_left[0];
            let anchor_right = top_right[0];
            let anchor = exact_pair_utility(
                model,
                samples,
                baseline,
                group.indices[0],
                group.indices[1],
                ACTION_VALUES[anchor_left],
                ACTION_VALUES[anchor_right],
            );
            evaluations += 1;
            let product = ACTION_VALUES[anchor_left] * ACTION_VALUES[anchor_right];
            let coefficient = if product.abs() > f32::EPSILON {
                (anchor - left_actions[anchor_left].utility - right_actions[anchor_right].utility)
                    / product
            } else {
                0.0
            };
            for left in 0..11 {
                for right in 0..11 {
                    let utility = left_actions[left].utility
                        + right_actions[right].utility
                        + coefficient * ACTION_VALUES[left] * ACTION_VALUES[right];
                    if utility > best.utility {
                        best = make_pair(group, left, right, utility);
                    }
                }
            }
        }
        Arm::I3ConditionalBeam => {
            let mut seen = [[false; 11]; 11];
            for &left in &top_left {
                for right in 0..11 {
                    seen[left][right] = true;
                }
            }
            for left in 0..11 {
                for &right in &top_right {
                    seen[left][right] = true;
                }
            }
            for left in 0..11 {
                for right in 0..11 {
                    if seen[left][right] {
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
            }
        }
        Arm::I4CartesianBeam => {
            for &left in &top_left {
                for &right in &top_right {
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
        }
        Arm::I5Sampled => {
            const FIXED: [(usize, usize); 17] = [
                (0, 0),
                (1, 0),
                (2, 0),
                (3, 0),
                (4, 0),
                (9, 0),
                (10, 0),
                (0, 1),
                (0, 2),
                (0, 3),
                (0, 4),
                (0, 9),
                (0, 10),
                (1, 1),
                (2, 2),
                (9, 10),
                (10, 9),
            ];
            let mut seen = [[false; 11]; 11];
            for &(left, right) in &FIXED {
                seen[left][right] = true;
            }
            for &left in &top_left {
                for &right in &top_right {
                    seen[left][right] = true;
                }
            }
            for left in 0..11 {
                for right in 0..11 {
                    if seen[left][right] {
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
            }
        }
        Arm::I0Exact => unreachable!("I0 uses the exact pair path"),
    }
    if best.utility > 0.0 {
        (Some(best), evaluations)
    } else {
        (None, evaluations)
    }
}

fn best_program(
    arm: Arm,
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
) -> (Option<Program>, u64) {
    if group.len == 1 {
        return best_singleton_program(model, samples, baseline, group);
    }
    if arm == Arm::I0Exact {
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
            telemetry.utility_evaluations += evaluations;
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
    model: Model,
    schedule_index: usize,
}

fn exact_snapshots(samples: &[Sample], seed: u64) -> Vec<Snapshot> {
    let schedule = build_schedule(seed);
    let capture = [0usize, 10, 50, 100, 250, 500, 1_000, 2_000];
    let mut snapshots = Vec::with_capacity(capture.len());
    let mut schedule_index = 0;
    let mut coverage = [[0u32; PARAMS]; PARAMS];
    let mut model = Model::initial();
    for epoch in 0..EPOCHS {
        if capture.contains(&epoch) {
            snapshots.push(Snapshot {
                model,
                schedule_index,
            });
        }
        let _ = advance_epoch(
            &mut model,
            samples,
            Arm::I0Exact,
            &schedule,
            &mut schedule_index,
            &mut coverage,
        );
    }
    snapshots
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ShadowSummary {
    pub arm: Arm,
    pub seed: u64,
    pub groups: u64,
    pub top_choice_agreement: f32,
    pub improving_fraction: f32,
    pub mean_exact_regret: f32,
    pub max_exact_regret: f32,
    pub utility_evaluations: u64,
}

pub fn shadow_audit(samples: &[Sample]) -> Vec<ShadowSummary> {
    let mut summaries = Vec::with_capacity(Arm::ALL.len() * SEEDS.len());
    for seed in SEEDS {
        let schedule = build_schedule(seed);
        for arm in Arm::ALL {
            let mut groups = 0_u64;
            let mut agreements = 0_u64;
            let mut improving = 0_u64;
            let mut regret = 0.0_f32;
            let mut max_regret = 0.0_f32;
            let mut evaluations = 0_u64;
            for snapshot in exact_snapshots(samples, seed) {
                let partition = schedule[snapshot.schedule_index % schedule.len()];
                let baseline = snapshot.model.loss_and_gradient(samples).0;
                for group in partition.groups[..partition.group_count]
                    .iter()
                    .copied()
                    .filter(|group| group.len == 2)
                {
                    let (exact, _) = exact_pair_program(&snapshot.model, samples, baseline, group);
                    let (approx, approximate_evaluations) =
                        best_program(arm, &snapshot.model, samples, baseline, group);
                    evaluations += approximate_evaluations;
                    let exact_utility = exact.map_or(0.0, |program| program.utility);
                    let approximate_utility = approx.map_or(0.0, |program| {
                        exact_pair_utility(
                            &snapshot.model,
                            samples,
                            baseline,
                            group.indices[0],
                            group.indices[1],
                            program.deltas[0],
                            program.deltas[1],
                        )
                    });
                    if approximate_utility > 0.0 {
                        improving += 1;
                    }
                    if let (Some(exact), Some(approx)) = (exact, approx) {
                        if exact.deltas == approx.deltas {
                            agreements += 1;
                        }
                    } else if exact.is_none() && approx.is_none() {
                        agreements += 1;
                    }
                    let current_regret = (exact_utility - approximate_utility).max(0.0);
                    regret += current_regret;
                    max_regret = max_regret.max(current_regret);
                    groups += 1;
                }
            }
            summaries.push(ShadowSummary {
                arm,
                seed,
                groups,
                top_choice_agreement: agreements as f32 / groups.max(1) as f32,
                improving_fraction: improving as f32 / groups.max(1) as f32,
                mean_exact_regret: regret / groups.max(1) as f32,
                max_exact_regret: max_regret,
                utility_evaluations: evaluations,
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
        let result = run(&xor_samples(), Arm::I4CartesianBeam, SEEDS[0]);
        assert!(result.telemetry.selected_primitives > 0);
        assert!(result.telemetry.utility_evaluations > 0);
    }
}
