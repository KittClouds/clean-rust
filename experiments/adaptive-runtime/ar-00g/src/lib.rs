use adaptive_runtime_ar_00::{Model, PARAMS, Sample, xor_samples};
use adaptive_runtime_ar_00c_int1::run as run_int1;

pub const EPOCHS: usize = 3_000;
pub const PRIMITIVE_BUDGET: usize = PARAMS;
pub const REFRESH_EPOCHS: usize = 100;
pub const MAX_GROUP_SIZE: usize = 3;
pub const CANDIDATE_PARTITIONS: usize = 128;

const ACTION_STEP: f32 = 0.02;
const LOWER_BOUND: f32 = -3.0;
const UPPER_BOUND: f32 = 3.0;
const ACTION_VALUES: [f32; 11] = [
    0.0,
    -ACTION_STEP,
    ACTION_STEP,
    -ACTION_STEP * 0.5,
    ACTION_STEP * 0.5,
    -ACTION_STEP * 0.25,
    ACTION_STEP * 0.25,
    -ACTION_STEP * 0.125,
    ACTION_STEP * 0.125,
    -ACTION_STEP * 0.0625,
    ACTION_STEP * 0.0625,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Policy {
    G0DynamicRandom,
    G1RoundRobin,
    G2LowCoverage,
    G3NoRepeat,
    G4ForbiddenHotPairs,
    G5FreshTopology,
}

impl Policy {
    pub const fn label(self) -> &'static str {
        match self {
            Self::G0DynamicRandom => "G0-dynamic-random",
            Self::G1RoundRobin => "G1-round-robin",
            Self::G2LowCoverage => "G2-low-coverage",
            Self::G3NoRepeat => "G3-no-repeat",
            Self::G4ForbiddenHotPairs => "G4-forbidden-hot-pairs",
            Self::G5FreshTopology => "G5-fresh-topology",
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
    pub frozen_hot_pairs: usize,
    pub frozen_hot_pairs_covered: usize,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Telemetry {
    pub selected_primitives: u64,
    pub programs: u64,
    pub utility_evaluations: u64,
    pub predicted_utility: f32,
    pub realized_utility: f32,
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
}

#[derive(Clone, Debug)]
pub struct RunSummary {
    pub policy: Policy,
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
    pub groups: [Group; 9],
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

pub const STRUCTURAL_PARTITION: Partition = Partition {
    groups: [
        Group {
            indices: [0, 1, 8],
            len: 3,
        },
        Group {
            indices: [2, 3, 9],
            len: 3,
        },
        Group {
            indices: [4, 5, 10],
            len: 3,
        },
        Group {
            indices: [6, 7, 11],
            len: 3,
        },
        Group {
            indices: [12, 0, 0],
            len: 1,
        },
        Group {
            indices: [13, 0, 0],
            len: 1,
        },
        Group {
            indices: [14, 0, 0],
            len: 1,
        },
        Group {
            indices: [15, 0, 0],
            len: 1,
        },
        Group {
            indices: [16, 0, 0],
            len: 1,
        },
    ],
};

fn random_partition(rng: &mut Rng) -> Partition {
    let mut order = [0usize; PARAMS];
    for (index, value) in order.iter_mut().enumerate() {
        *value = index;
    }
    rng.shuffle(&mut order);
    let mut partition = Partition {
        groups: [EMPTY_GROUP; 9],
    };
    let mut cursor = 0;
    for group in &mut partition.groups {
        let len = if cursor < 12 { 3 } else { 1 };
        group.len = len;
        group.indices[..len].copy_from_slice(&order[cursor..cursor + len]);
        cursor += len;
    }
    partition
}

fn co_grouped(partition: Partition, first: usize, second: usize) -> bool {
    partition.groups.iter().any(|group| {
        group.indices[..group.len].contains(&first) && group.indices[..group.len].contains(&second)
    })
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
        deltas: [f32; MAX_GROUP_SIZE],
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
                for (offset, delta) in self.deltas.iter().enumerate().take(self.group.len) {
                    candidate.parameters[self.group.indices[offset]] += *delta;
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
        deltas: [0.0; MAX_GROUP_SIZE],
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

fn record_coverage(coverage: &mut [[u32; PARAMS]; PARAMS], partition: Partition) {
    for group in partition.groups {
        for first in 0..group.len {
            for second in first + 1..group.len {
                let left = group.indices[first];
                let right = group.indices[second];
                coverage[left][right] = coverage[left][right].saturating_add(1);
                coverage[right][left] = coverage[left][right];
            }
        }
    }
}

#[allow(clippy::needless_range_loop)]
fn coverage_metrics(
    coverage: &[[u32; PARAMS]; PARAMS],
    frozen_hot_pairs: &[(usize, usize)],
    full_coverage_time: Option<u64>,
) -> CoverageMetrics {
    let mut values = Vec::with_capacity(PARAMS * (PARAMS - 1) / 2);
    let mut ever = 0;
    let mut hot_covered = 0;
    for first in 0..PARAMS {
        for second in first + 1..PARAMS {
            let value = coverage[first][second];
            values.push(value);
            ever += usize::from(value > 0);
        }
    }
    for &(first, second) in frozen_hot_pairs {
        if coverage[first][second] > 0 {
            hot_covered += 1;
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
        frozen_hot_pairs: frozen_hot_pairs.len(),
        frozen_hot_pairs_covered: hot_covered,
    }
}

#[allow(clippy::needless_range_loop)]
fn final_hot_pairs(samples: &[Sample]) -> Vec<(usize, usize)> {
    let map = run_int1(samples);
    let mut weights = [[0.0; PARAMS]; PARAMS];
    for pair in map.pairs {
        weights[pair.first][pair.second] += pair.interaction.abs();
        weights[pair.second][pair.first] = weights[pair.first][pair.second];
    }
    let mut pairs = Vec::with_capacity(PARAMS * (PARAMS - 1) / 2);
    for first in 0..PARAMS {
        for second in first + 1..PARAMS {
            pairs.push((weights[first][second], first, second));
        }
    }
    pairs.sort_by(|left, right| right.0.total_cmp(&left.0));
    pairs
        .into_iter()
        .take(12)
        .map(|(_, first, second)| (first, second))
        .collect()
}

fn build_round_robin_schedule() -> Vec<Partition> {
    let mut covered = [[false; PARAMS]; PARAMS];
    let mut schedule = Vec::new();
    for _round in 0..64 {
        let mut partition = Partition {
            groups: [EMPTY_GROUP; 9],
        };
        let mut used = [false; PARAMS];
        for group_index in 0..4 {
            let mut best = (0usize, 1usize, 2usize, -1_i32);
            for first in 0..PARAMS {
                if used[first] {
                    continue;
                }
                for second in first + 1..PARAMS {
                    if used[second] {
                        continue;
                    }
                    for third in second + 1..PARAMS {
                        if used[third] {
                            continue;
                        }
                        let score = (usize::from(!covered[first][second])
                            + usize::from(!covered[first][third])
                            + usize::from(!covered[second][third]))
                            as i32;
                        if score > best.3 {
                            best = (first, second, third, score);
                        }
                    }
                }
            }
            let group = &mut partition.groups[group_index];
            group.indices = [best.0, best.1, best.2];
            group.len = 3;
            used[best.0] = true;
            used[best.1] = true;
            used[best.2] = true;
            covered[best.0][best.1] = true;
            covered[best.1][best.0] = true;
            covered[best.0][best.2] = true;
            covered[best.2][best.0] = true;
            covered[best.1][best.2] = true;
            covered[best.2][best.1] = true;
        }
        for (slot, index) in (0..PARAMS).filter(|index| !used[*index]).enumerate() {
            partition.groups[4 + slot] = Group {
                indices: [index; MAX_GROUP_SIZE],
                len: 1,
            };
        }
        schedule.push(partition);
        let complete =
            (0..PARAMS).all(|first| (first + 1..PARAMS).all(|second| covered[first][second]));
        if complete {
            break;
        }
    }
    schedule
}

#[allow(clippy::needless_range_loop)]
fn choose_uncovered_partition(
    candidates: &[Partition],
    coverage: &[[u32; PARAMS]; PARAMS],
) -> Partition {
    let mut best = candidates[0];
    let mut best_score = 0usize;
    for &candidate in candidates {
        let mut score = 0;
        for first in 0..PARAMS {
            for second in first + 1..PARAMS {
                if co_grouped(candidate, first, second) && coverage[first][second] == 0 {
                    score += 1;
                }
            }
        }
        if score > best_score {
            best = candidate;
            best_score = score;
        }
    }
    best
}

fn forbidden_partition(rng: &mut Rng, forbidden: &[(usize, usize)]) -> Partition {
    for _ in 0..256 {
        let candidate = random_partition(rng);
        let valid = forbidden
            .iter()
            .all(|&(first, second)| !co_grouped(candidate, first, second));
        if valid {
            return candidate;
        }
    }
    let mut candidate = STRUCTURAL_PARTITION;
    for group in &mut candidate.groups {
        if group.len > 1 {
            for first in 0..group.len {
                for second in first + 1..group.len {
                    if forbidden.contains(&(
                        group.indices[first].min(group.indices[second]),
                        group.indices[first].max(group.indices[second]),
                    )) {
                        group.indices.swap(first, second);
                    }
                }
            }
        }
    }
    candidate
}

fn singleton_action(model: &Model, samples: &[Sample], index: usize, baseline: f32) -> Action {
    let current = model.parameters[index];
    let mut best = Action::default();
    for &delta in &ACTION_VALUES[1..] {
        if !(LOWER_BOUND..=UPPER_BOUND).contains(&(current + delta)) {
            continue;
        }
        let mut candidate = *model;
        candidate.parameters[index] += delta;
        let utility = baseline - candidate.loss_and_gradient(samples).0;
        if utility > best.utility {
            best = Action { delta, utility };
        }
    }
    best
}

fn current_topology_partition(model: &Model, samples: &[Sample]) -> Partition {
    let baseline = model.loss_and_gradient(samples).0;
    let actions: [Action; PARAMS] =
        std::array::from_fn(|index| singleton_action(model, samples, index, baseline));
    let mut weights = [[0.0; PARAMS]; PARAMS];
    for first in 0..PARAMS {
        for second in first + 1..PARAMS {
            let mut candidate = *model;
            candidate.parameters[first] += actions[first].delta;
            candidate.parameters[second] += actions[second].delta;
            let pair_effect = candidate.loss_and_gradient(samples).0 - baseline;
            let first_effect = -actions[first].utility;
            let second_effect = -actions[second].utility;
            let interaction = pair_effect - (first_effect + second_effect);
            weights[first][second] = interaction.abs();
            weights[second][first] = weights[first][second];
        }
    }
    let mut remaining = [true; PARAMS];
    let mut partition = Partition {
        groups: [EMPTY_GROUP; 9],
    };
    for group_index in 0..4 {
        let mut best = (0usize, 1usize, 2usize, -1.0_f32);
        for first in 0..PARAMS {
            if !remaining[first] {
                continue;
            }
            for second in first + 1..PARAMS {
                if !remaining[second] {
                    continue;
                }
                for third in second + 1..PARAMS {
                    if !remaining[third] {
                        continue;
                    }
                    let score =
                        weights[first][second] + weights[first][third] + weights[second][third];
                    if score > best.3 {
                        best = (first, second, third, score);
                    }
                }
            }
        }
        partition.groups[group_index] = Group {
            indices: [best.0, best.1, best.2],
            len: 3,
        };
        remaining[best.0] = false;
        remaining[best.1] = false;
        remaining[best.2] = false;
    }
    for (slot, index) in (0..PARAMS).filter(|index| remaining[*index]).enumerate() {
        partition.groups[4 + slot] = Group {
            indices: [index; MAX_GROUP_SIZE],
            len: 1,
        };
    }
    partition
}

#[derive(Clone, Debug)]
struct ScheduleState {
    policy: Policy,
    rng: Rng,
    round_robin: Vec<Partition>,
    candidates: Vec<Partition>,
    low_pool: [Partition; 2],
    forbidden: Vec<(usize, usize)>,
    schedule_index: usize,
    current_partition: Partition,
}

impl ScheduleState {
    fn new(policy: Policy, samples: &[Sample]) -> Self {
        let round_robin = build_round_robin_schedule();
        let mut candidate_rng = Rng::new(0x77a1_9d3c_4e28_0b51);
        let candidates = (0..CANDIDATE_PARTITIONS)
            .map(|_| random_partition(&mut candidate_rng))
            .collect();
        let mut low_rng = Rng::new(0x1111_2222_3333_4444);
        let low_pool = [
            random_partition(&mut low_rng),
            random_partition(&mut low_rng),
        ];
        let forbidden = final_hot_pairs(samples);
        Self {
            policy,
            rng: Rng::new(0x2b7e_1516_28ae_d2a6),
            round_robin,
            candidates,
            low_pool,
            forbidden,
            schedule_index: 0,
            current_partition: STRUCTURAL_PARTITION,
        }
    }

    fn partition(
        &mut self,
        model: &Model,
        samples: &[Sample],
        coverage: &[[u32; PARAMS]; PARAMS],
        epoch: usize,
    ) -> Partition {
        match self.policy {
            Policy::G0DynamicRandom => {
                let mut local = Rng::new(self.rng.next());
                random_partition(&mut local)
            }
            Policy::G1RoundRobin => {
                let partition = self.round_robin[self.schedule_index % self.round_robin.len()];
                self.schedule_index += 1;
                partition
            }
            Policy::G2LowCoverage => {
                let partition = self.low_pool[self.schedule_index % self.low_pool.len()];
                self.schedule_index += 1;
                partition
            }
            Policy::G3NoRepeat => {
                let partition = choose_uncovered_partition(&self.candidates, coverage);
                self.schedule_index += 1;
                partition
            }
            Policy::G4ForbiddenHotPairs => forbidden_partition(&mut self.rng, &self.forbidden),
            Policy::G5FreshTopology => {
                if epoch.is_multiple_of(REFRESH_EPOCHS) && self.schedule_index == 0 {
                    self.current_partition = current_topology_partition(model, samples);
                }
                self.schedule_index += 1;
                self.current_partition
            }
        }
    }

    fn end_epoch(&mut self) {
        if self.policy == Policy::G5FreshTopology {
            self.schedule_index = 0;
        }
    }
}

#[allow(clippy::needless_range_loop)]
fn run_policy(samples: &[Sample], policy: Policy, epochs: usize) -> RunSummary {
    let frozen_hot_pairs = final_hot_pairs(samples);
    let mut schedule = ScheduleState::new(policy, samples);
    let mut coverage = [[0u32; PARAMS]; PARAMS];
    let mut full_coverage_time = None;
    let mut model = Model::initial();
    let mut total = Telemetry::default();
    let mut curve = Vec::with_capacity(epochs);
    let mut planning_cycle = 0_u64;
    for epoch in 0..epochs {
        let loss_before = model.loss_and_gradient(samples).0;
        let mut epoch_telemetry = Telemetry::default();
        let mut remaining = PRIMITIVE_BUDGET;
        while remaining > 0 {
            let partition = schedule.partition(&model, samples, &coverage, epoch);
            record_coverage(&mut coverage, partition);
            planning_cycle += 1;
            if full_coverage_time.is_none()
                && (0..PARAMS)
                    .all(|first| (first + 1..PARAMS).all(|second| coverage[first][second] > 0))
            {
                full_coverage_time = Some(planning_cycle);
            }
            let baseline = model.loss_and_gradient(samples).0;
            let mut best = None;
            for group in partition.groups {
                if group.len > remaining {
                    continue;
                }
                let (candidate, evaluations) = best_group_program(&model, samples, baseline, group);
                epoch_telemetry.utility_evaluations += evaluations;
                if let Some(candidate) = candidate
                    && best.is_none_or(|current: Program| candidate.utility > current.utility)
                {
                    best = Some(candidate);
                }
            }
            let Some(program) = best else {
                break;
            };
            epoch_telemetry.absorb(commit(&mut model, samples, baseline, program));
            remaining -= program.len;
        }
        schedule.end_epoch();
        total.absorb(epoch_telemetry);
        let loss_after = model.loss_and_gradient(samples).0;
        curve.push(CurvePoint {
            epoch,
            loss_before,
            loss_after,
            accuracy_after: model.accuracy(samples),
            selected_primitives: epoch_telemetry.selected_primitives,
            programs: epoch_telemetry.programs,
            utility_evaluations: epoch_telemetry.utility_evaluations,
        });
    }
    let final_loss = model.loss_and_gradient(samples).0;
    RunSummary {
        policy,
        final_loss,
        final_accuracy: model.accuracy(samples),
        final_mse: model.simd_mean_squared_error(samples),
        telemetry: total,
        coverage: coverage_metrics(&coverage, &frozen_hot_pairs, full_coverage_time),
        coverage_matrix: coverage,
        curve,
    }
}

pub fn run(samples: &[Sample], policy: Policy) -> RunSummary {
    run_policy(samples, policy, EPOCHS)
}

pub fn run_all(samples: &[Sample]) -> [RunSummary; 6] {
    [
        run(samples, Policy::G0DynamicRandom),
        run(samples, Policy::G1RoundRobin),
        run(samples, Policy::G2LowCoverage),
        run(samples, Policy::G3NoRepeat),
        run(samples, Policy::G4ForbiddenHotPairs),
        run(samples, Policy::G5FreshTopology),
    ]
}

pub fn xor_samples_for_tests() -> [Sample; 4] {
    xor_samples()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_robin_reaches_full_pair_coverage() {
        let schedule = build_round_robin_schedule();
        let mut coverage = [[0u32; PARAMS]; PARAMS];
        for partition in schedule {
            record_coverage(&mut coverage, partition);
        }
        assert!(
            (0..PARAMS).all(|first| (first + 1..PARAMS).all(|second| coverage[first][second] > 0))
        );
    }

    #[test]
    fn short_policy_runs_produce_coverage_and_actions() {
        let samples = xor_samples();
        for policy in [
            Policy::G0DynamicRandom,
            Policy::G1RoundRobin,
            Policy::G2LowCoverage,
            Policy::G3NoRepeat,
            Policy::G4ForbiddenHotPairs,
            Policy::G5FreshTopology,
        ] {
            let result = run_policy(&samples, policy, 2);
            assert!(result.telemetry.selected_primitives > 0);
            assert!(result.coverage.ever_covered_pairs > 0);
        }
    }
}
