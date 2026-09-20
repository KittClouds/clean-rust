use adaptive_runtime_ar_00::{Model, PARAMS, Sample, xor_samples};

pub const EPOCHS: usize = 3_000;
pub const PRIMITIVE_BUDGET: usize = PARAMS;
pub const MAX_WIDTH: usize = 4;
pub const ACTION_VALUES: [f32; 11] = [
    0.0, -0.02, 0.02, -0.01, 0.01, -0.005, 0.005, -0.0025, 0.0025, -0.00125, 0.00125,
];
pub const LOWER_BOUND: f32 = -3.0;
pub const UPPER_BOUND: f32 = 3.0;
pub const EVALUATION_BUDGET: u64 = 10_000_000;
pub const PAIR_EVENT_BUDGET: u64 = 4_096;
pub const SEEDS: [u64; 3] = [
    0x2b7e_1516_28ae_d2a6,
    0x77a1_9d3c_4e28_0b51,
    0x1111_2222_3333_4444,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BudgetMode {
    EqualSteps,
    EqualEvaluations,
    EqualPairEvents,
}

impl BudgetMode {
    pub const fn label(self) -> &'static str {
        match self {
            Self::EqualSteps => "equal-steps",
            Self::EqualEvaluations => "equal-evaluations",
            Self::EqualPairEvents => "equal-pair-events",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct CoverageMetrics {
    pub pair_count: usize,
    pub ever_covered_pairs: usize,
    pub ever_covered_fraction: f32,
    pub min_pair_coverage: u32,
    pub max_pair_coverage: u32,
    pub mean_pair_coverage: f32,
    pub coverage_entropy: f32,
    pub time_to_full_coverage: Option<u64>,
    pub planning_steps: u64,
    pub pair_events: u64,
    pub pair_events_per_step: f32,
    pub pair_events_per_evaluation: f32,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Telemetry {
    pub selected_primitives: u64,
    pub programs: u64,
    pub utility_evaluations: u64,
    pub predicted_utility: f32,
    pub realized_utility: f32,
    pub completed_epochs: usize,
    pub budget_exhausted: bool,
}

impl Telemetry {
    fn absorb(&mut self, other: Self) {
        self.selected_primitives += other.selected_primitives;
        self.programs += other.programs;
        self.utility_evaluations += other.utility_evaluations;
        self.predicted_utility += other.predicted_utility;
        self.realized_utility += other.realized_utility;
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
    pub pair_events: u64,
}

#[derive(Clone, Debug)]
pub struct RunSummary {
    pub mode: BudgetMode,
    pub width: usize,
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
    pub indices: [usize; MAX_WIDTH],
    pub len: usize,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Partition {
    pub groups: [Group; PARAMS],
    pub group_count: usize,
}

#[derive(Clone, Copy, Debug, Default)]
struct Program {
    indices: [usize; MAX_WIDTH],
    deltas: [f32; MAX_WIDTH],
    len: usize,
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
    indices: [0; MAX_WIDTH],
    len: 0,
};

fn random_partition(width: usize, rng: &mut Rng) -> Partition {
    let mut order = [0usize; PARAMS];
    for (index, value) in order.iter_mut().enumerate() {
        *value = index;
    }
    rng.shuffle(&mut order);
    let mut partition = Partition {
        groups: [EMPTY_GROUP; PARAMS],
        group_count: 0,
    };
    let mut cursor = 0;
    while cursor < PARAMS {
        let len = width.min(PARAMS - cursor);
        let mut group = EMPTY_GROUP;
        group.len = len;
        group.indices[..len].copy_from_slice(&order[cursor..cursor + len]);
        partition.groups[partition.group_count] = group;
        partition.group_count += 1;
        cursor += len;
    }
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

fn build_coverage_schedule(width: usize, seed: u64) -> Vec<Partition> {
    assert!((1..=MAX_WIDTH).contains(&width));
    let mut rng = Rng::new(seed);
    if width == 1 {
        return vec![random_partition(width, &mut rng)];
    }
    let mut covered = [[false; PARAMS]; PARAMS];
    let mut schedule = Vec::with_capacity(64);
    for _ in 0..64 {
        let mut best = random_partition(width, &mut rng);
        let mut best_score = uncovered_score(best, &covered);
        for _ in 0..256 {
            let candidate = random_partition(width, &mut rng);
            let score = uncovered_score(candidate, &covered);
            if score > best_score {
                best = candidate;
                best_score = score;
            }
        }
        for group in best.groups[..best.group_count].iter() {
            for first in 0..group.len {
                for second in first + 1..group.len {
                    let left = group.indices[first];
                    let right = group.indices[second];
                    covered[left][right] = true;
                    covered[right][left] = true;
                }
            }
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
    for group in partition.groups[..partition.group_count].iter() {
        for first in 0..group.len {
            for second in first + 1..group.len {
                let left = group.indices[first];
                let right = group.indices[second];
                coverage[left][right] = coverage[left][right].saturating_add(1);
                coverage[right][left] = coverage[left][right];
                events += 1;
            }
        }
    }
    events
}

#[allow(clippy::needless_range_loop)]
fn coverage_metrics(
    coverage: &[[u32; PARAMS]; PARAMS],
    planning_steps: u64,
    pair_events: u64,
    evaluations: u64,
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
    let total = values.len();
    let mean = values.iter().map(|&value| value as f32).sum::<f32>() / total as f32;
    let min = values.iter().copied().min().unwrap_or(0);
    let max = values.iter().copied().max().unwrap_or(0);
    let total_events = values.iter().map(|&value| value as f32).sum::<f32>();
    let mut entropy = 0.0;
    if total_events > 0.0 {
        for value in values {
            if value > 0 {
                let probability = value as f32 / total_events;
                entropy -= probability * probability.ln();
            }
        }
    }
    CoverageMetrics {
        pair_count: total,
        ever_covered_pairs: ever,
        ever_covered_fraction: ever as f32 / total as f32,
        min_pair_coverage: min,
        max_pair_coverage: max,
        mean_pair_coverage: mean,
        coverage_entropy: entropy,
        time_to_full_coverage: full_coverage_time,
        planning_steps,
        pair_events,
        pair_events_per_step: pair_events as f32 / planning_steps.max(1) as f32,
        pair_events_per_evaluation: pair_events as f32 / evaluations.max(1) as f32,
    }
}

fn action_count(len: usize) -> u64 {
    (ACTION_VALUES.len() as u64).pow(len as u32)
}

fn best_group_program(
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
) -> (Option<Program>, u64) {
    struct Search<'a> {
        model: &'a Model,
        samples: &'a [Sample],
        baseline: f32,
        group: Group,
        deltas: [f32; MAX_WIDTH],
        best: Program,
        evaluations: u64,
    }
    impl Search<'_> {
        fn recurse(&mut self, slot: usize) {
            if slot == self.group.len {
                let valid = (0..self.group.len).all(|offset| {
                    (LOWER_BOUND..=UPPER_BOUND).contains(
                        &(self.model.parameters[self.group.indices[offset]] + self.deltas[offset]),
                    )
                });
                if !valid {
                    return;
                }
                let mut candidate = *self.model;
                for offset in 0..self.group.len {
                    candidate.parameters[self.group.indices[offset]] += self.deltas[offset];
                }
                let utility = self.baseline - candidate.loss_and_gradient(self.samples).0;
                self.evaluations += 1;
                if utility > self.best.utility {
                    self.best.deltas = self.deltas;
                    self.best.utility = utility;
                }
                return;
            }
            for &delta in &ACTION_VALUES {
                self.deltas[slot] = delta;
                self.recurse(slot + 1);
            }
        }
    }
    let mut search = Search {
        model,
        samples,
        baseline,
        group,
        deltas: [0.0; MAX_WIDTH],
        best: Program {
            indices: group.indices,
            len: group.len,
            ..Program::default()
        },
        evaluations: 0,
    };
    search.recurse(0);
    if search.best.utility > 0.0 {
        (Some(search.best), search.evaluations)
    } else {
        (None, search.evaluations)
    }
}

fn commit(
    model: &mut Model,
    samples: &[Sample],
    baseline: f32,
    program: Program,
) -> (u64, f32, f32) {
    for slot in 0..program.len {
        model.parameters[program.indices[slot]] += program.deltas[slot];
    }
    let realized = baseline - model.loss_and_gradient(samples).0;
    (program.len as u64, program.utility, realized)
}

fn budget_reached(mode: BudgetMode, evaluations: u64, pair_events: u64) -> bool {
    match mode {
        BudgetMode::EqualSteps => false,
        BudgetMode::EqualEvaluations => evaluations >= EVALUATION_BUDGET,
        BudgetMode::EqualPairEvents => pair_events >= PAIR_EVENT_BUDGET,
    }
}

fn enough_budget(mode: BudgetMode, evaluations: u64, pair_events: u64, cost: u64) -> bool {
    match mode {
        BudgetMode::EqualSteps | BudgetMode::EqualPairEvents => {
            let _ = pair_events;
            evaluations.saturating_add(cost) <= EVALUATION_BUDGET.max(evaluations + cost)
        }
        BudgetMode::EqualEvaluations => evaluations.saturating_add(cost) <= EVALUATION_BUDGET,
    }
}

fn run_arm(samples: &[Sample], width: usize, seed: u64, mode: BudgetMode) -> RunSummary {
    let schedule = build_coverage_schedule(width, seed);
    let mut schedule_index = 0;
    let mut coverage = [[0u32; PARAMS]; PARAMS];
    let mut full_coverage_time = None;
    let mut model = Model::initial();
    let mut total = Telemetry::default();
    let mut curve = Vec::with_capacity(EPOCHS);
    let mut planning_steps = 0_u64;
    let mut pair_events = 0_u64;
    let mut evaluations = 0_u64;
    let mut stopped = false;

    let max_epochs = match mode {
        BudgetMode::EqualSteps => EPOCHS,
        BudgetMode::EqualEvaluations | BudgetMode::EqualPairEvents => 100_000,
    };
    for epoch in 0..max_epochs {
        if budget_reached(mode, evaluations, pair_events) {
            stopped = true;
            break;
        }
        let loss_before = model.loss_and_gradient(samples).0;
        let mut epoch_telemetry = Telemetry::default();
        let mut remaining = PRIMITIVE_BUDGET;
        while remaining > 0 {
            if budget_reached(mode, evaluations, pair_events) {
                stopped = true;
                break;
            }
            let partition = schedule[schedule_index % schedule.len()];
            schedule_index += 1;
            let required = partition.groups[..partition.group_count]
                .iter()
                .filter(|group| group.len <= remaining)
                .map(|group| action_count(group.len))
                .sum::<u64>();
            if mode == BudgetMode::EqualEvaluations
                && !enough_budget(mode, evaluations, pair_events, required)
            {
                stopped = true;
                break;
            }
            let events = record_coverage(&mut coverage, partition);
            pair_events += events;
            planning_steps += 1;
            if full_coverage_time.is_none()
                && (0..PARAMS)
                    .all(|first| (first + 1..PARAMS).all(|second| coverage[first][second] > 0))
            {
                full_coverage_time = Some(planning_steps);
            }
            let baseline = model.loss_and_gradient(samples).0;
            let mut best = None;
            for group in partition.groups[..partition.group_count].iter().copied() {
                if group.len > remaining {
                    continue;
                }
                let (candidate, group_evaluations) =
                    best_group_program(&model, samples, baseline, group);
                evaluations += group_evaluations;
                epoch_telemetry.utility_evaluations += group_evaluations;
                if let Some(candidate) = candidate
                    && best.is_none_or(|current: Program| candidate.utility > current.utility)
                {
                    best = Some(candidate);
                }
            }
            let Some(program) = best else {
                break;
            };
            let (selected, predicted, realized) = commit(&mut model, samples, baseline, program);
            epoch_telemetry.selected_primitives += selected;
            epoch_telemetry.programs += 1;
            epoch_telemetry.predicted_utility += predicted;
            epoch_telemetry.realized_utility += realized;
            remaining -= selected as usize;
            if mode == BudgetMode::EqualPairEvents && pair_events >= PAIR_EVENT_BUDGET {
                stopped = true;
                break;
            }
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
            pair_events,
        });
        total.completed_epochs = epoch + 1;
        if stopped {
            break;
        }
    }
    total.budget_exhausted = stopped;
    let (final_loss, _) = model.loss_and_gradient(samples);
    RunSummary {
        mode,
        width,
        seed,
        final_loss,
        final_accuracy: model.accuracy(samples),
        final_mse: model.simd_mean_squared_error(samples),
        telemetry: total,
        coverage: coverage_metrics(
            &coverage,
            planning_steps,
            pair_events,
            evaluations,
            full_coverage_time,
        ),
        coverage_matrix: coverage,
        curve,
    }
}

pub fn run(samples: &[Sample], width: usize, seed: u64, mode: BudgetMode) -> RunSummary {
    run_arm(samples, width, seed, mode)
}

pub fn run_all(samples: &[Sample]) -> Vec<RunSummary> {
    let mut results = Vec::with_capacity(30);
    for mode in [BudgetMode::EqualSteps, BudgetMode::EqualEvaluations] {
        for width in 1..=MAX_WIDTH {
            for seed in SEEDS {
                results.push(run(samples, width, seed, mode));
            }
        }
    }
    for width in 2..=MAX_WIDTH {
        for seed in SEEDS {
            results.push(run(samples, width, seed, BudgetMode::EqualPairEvents));
        }
    }
    results
}

pub fn xor_samples_for_tests() -> [Sample; 4] {
    xor_samples()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn coverage_schedules_reach_all_pairs() {
        for width in 2..=MAX_WIDTH {
            let schedule = build_coverage_schedule(width, SEEDS[0]);
            let mut coverage = [[false; PARAMS]; PARAMS];
            for partition in schedule {
                for group in partition.groups[..partition.group_count].iter() {
                    for first in 0..group.len {
                        for second in first + 1..group.len {
                            coverage[group.indices[first]][group.indices[second]] = true;
                            coverage[group.indices[second]][group.indices[first]] = true;
                        }
                    }
                }
            }
            assert!(
                (0..PARAMS).all(|first| (first + 1..PARAMS).all(|second| coverage[first][second]))
            );
        }
    }

    #[test]
    fn short_runs_emit_width_and_budget_telemetry() {
        let result = run(&xor_samples(), 2, SEEDS[0], BudgetMode::EqualPairEvents);
        assert_eq!(result.width, 2);
        assert!(result.coverage.pair_events > 0);
        assert!(result.telemetry.selected_primitives > 0);
    }
}
