use adaptive_runtime_ar_00::{Model, PARAMS, Sample, xor_samples};
use adaptive_runtime_ar_00c_int1::run as run_int1;
use adaptive_runtime_ar_00d::{Policy as DPolicy, run as run_d_policy};

pub const EPOCHS: usize = 3_000;
pub const PRIMITIVE_BUDGET: usize = PARAMS;
pub const MAX_GROUP_SIZE: usize = 4;
pub const RANDOM_PARTITIONS: usize = 16;
pub const ACTION_STEP: f32 = 0.02;
pub const LOWER_BOUND: f32 = -3.0;
pub const UPPER_BOUND: f32 = 3.0;

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
pub enum RunKind {
    F0GlobalSingleton,
    F1RandomFixed,
    F2AntiTopology,
    F3TopologyMax,
    F4DynamicRandom,
    F5StructuralSingletonScore,
    F6StructuralCompoundScore,
    Width(usize),
}

impl RunKind {
    pub const fn label(self) -> &'static str {
        match self {
            Self::F0GlobalSingleton => "F0-global-singleton",
            Self::F1RandomFixed => "F1-random-fixed",
            Self::F2AntiTopology => "F2-anti-topology",
            Self::F3TopologyMax => "F3-topology-max",
            Self::F4DynamicRandom => "F4-dynamic-random",
            Self::F5StructuralSingletonScore => "F5-structural-singleton-score",
            Self::F6StructuralCompoundScore => "F6-structural-compound-score",
            Self::Width(1) => "W1-width-1",
            Self::Width(2) => "W2-width-2",
            Self::Width(3) => "W3-width-3",
            Self::Width(4) => "W4-width-4",
            Self::Width(_) => "width-out-of-range",
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

#[derive(Clone, Debug)]
pub struct RunSummary {
    pub kind: RunKind,
    pub variant: usize,
    pub final_loss: f32,
    pub final_accuracy: f32,
    pub final_mse: f32,
    pub telemetry: Telemetry,
    pub partition_objective: Option<f32>,
    pub curve: Vec<CurvePoint>,
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

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Group {
    pub indices: [usize; MAX_GROUP_SIZE],
    pub len: usize,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Partition {
    pub groups: [Group; PARAMS],
    pub count: usize,
}

const EMPTY_GROUP: Group = Group {
    indices: [0; MAX_GROUP_SIZE],
    len: 0,
};

#[derive(Clone, Copy, Debug, Default)]
struct Program {
    indices: [usize; MAX_GROUP_SIZE],
    deltas: [f32; MAX_GROUP_SIZE],
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

pub const STRUCTURAL_PARTITION: Partition = Partition {
    groups: [
        Group {
            indices: [0, 1, 8, 0],
            len: 3,
        },
        Group {
            indices: [2, 3, 9, 0],
            len: 3,
        },
        Group {
            indices: [4, 5, 10, 0],
            len: 3,
        },
        Group {
            indices: [6, 7, 11, 0],
            len: 3,
        },
        Group {
            indices: [12, 0, 0, 0],
            len: 1,
        },
        Group {
            indices: [13, 0, 0, 0],
            len: 1,
        },
        Group {
            indices: [14, 0, 0, 0],
            len: 1,
        },
        Group {
            indices: [15, 0, 0, 0],
            len: 1,
        },
        Group {
            indices: [16, 0, 0, 0],
            len: 1,
        },
        EMPTY_GROUP,
        EMPTY_GROUP,
        EMPTY_GROUP,
        EMPTY_GROUP,
        EMPTY_GROUP,
        EMPTY_GROUP,
        EMPTY_GROUP,
        EMPTY_GROUP,
    ],
    count: 9,
};

pub fn partition_from_sizes(sizes: &[usize], seed: u64) -> Partition {
    let mut indices = [0usize; PARAMS];
    for (index, value) in indices.iter_mut().enumerate() {
        *value = index;
    }
    let mut rng = Rng::new(seed);
    rng.shuffle(&mut indices);
    let mut partition = Partition::default();
    let mut cursor = 0;
    for &len in sizes {
        if len == 0 || len > MAX_GROUP_SIZE || cursor + len > PARAMS {
            break;
        }
        let group = &mut partition.groups[partition.count];
        group.len = len;
        group.indices[..len].copy_from_slice(&indices[cursor..cursor + len]);
        partition.count += 1;
        cursor += len;
    }
    partition
}

pub fn random_e2_partition(seed: u64) -> Partition {
    partition_from_sizes(&[3, 3, 3, 3, 1, 1, 1, 1, 1], seed)
}

fn final_metrics(model: &Model, samples: &[Sample]) -> (f32, f32, f32) {
    (
        model.loss_and_gradient(samples).0,
        model.accuracy(samples),
        model.simd_mean_squared_error(samples),
    )
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

fn best_compound_group(
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

fn best_singleton_batch(
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
) -> (Option<Program>, u64) {
    let mut program = Program {
        indices: group.indices,
        len: group.len,
        ..Program::default()
    };
    let mut evaluations = 0;
    let mut any_positive = false;
    for slot in 0..group.len {
        let index = group.indices[slot];
        let current = model.parameters[index];
        let mut best_delta = 0.0;
        let mut best_utility = 0.0;
        for &delta in &ACTION_VALUES[1..] {
            if !(LOWER_BOUND..=UPPER_BOUND).contains(&(current + delta)) {
                continue;
            }
            let mut candidate = *model;
            candidate.parameters[index] += delta;
            let utility = baseline - candidate.loss_and_gradient(samples).0;
            evaluations += 1;
            if utility > best_utility {
                best_utility = utility;
                best_delta = delta;
            }
        }
        program.deltas[slot] = best_delta;
        program.utility += best_utility;
        any_positive |= best_utility > 0.0;
    }
    if any_positive {
        (Some(program), evaluations)
    } else {
        (None, evaluations)
    }
}

fn run_partition_policy(
    samples: &[Sample],
    kind: RunKind,
    epochs: usize,
    fixed_partition: Option<Partition>,
    singleton_scoring: bool,
    dynamic_random: bool,
) -> RunSummary {
    let mut model = Model::initial();
    let mut total = Telemetry::default();
    let mut curve = Vec::with_capacity(epochs);
    let mut rng = Rng::new(0x2b7e_1516_28ae_d2a6);
    for epoch in 0..epochs {
        let loss_before = model.loss_and_gradient(samples).0;
        let mut epoch_telemetry = Telemetry::default();
        let mut remaining = PRIMITIVE_BUDGET;
        while remaining > 0 {
            let partition = if dynamic_random {
                random_e2_partition(rng.next())
            } else {
                fixed_partition.expect("fixed group policy requires a partition")
            };
            let baseline = model.loss_and_gradient(samples).0;
            let mut best = None;
            for group in partition.groups[..partition.count].iter().copied() {
                if group.len > remaining {
                    continue;
                }
                let (candidate, evaluations) = if singleton_scoring {
                    best_singleton_batch(&model, samples, baseline, group)
                } else {
                    best_compound_group(&model, samples, baseline, group)
                };
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
            if !dynamic_random && fixed_partition.is_none() {
                break;
            }
        }
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
    make_summary(kind, &model, samples, total, curve, None)
}

fn make_summary(
    kind: RunKind,
    model: &Model,
    samples: &[Sample],
    telemetry: Telemetry,
    curve: Vec<CurvePoint>,
    partition_objective: Option<f32>,
) -> RunSummary {
    let (final_loss, final_accuracy, final_mse) = final_metrics(model, samples);
    RunSummary {
        kind,
        variant: 0,
        final_loss,
        final_accuracy,
        final_mse,
        telemetry,
        partition_objective,
        curve,
    }
}

fn from_d5_result(d5: adaptive_runtime_ar_00d::ResultSummary) -> RunSummary {
    let curve = d5
        .curve
        .into_iter()
        .map(|point| CurvePoint {
            epoch: point.epoch,
            loss_before: point.loss_before,
            loss_after: point.loss_after,
            accuracy_after: point.accuracy_after,
            selected_primitives: point.selected,
            programs: point.batches,
            utility_evaluations: point.batches,
        })
        .collect();
    RunSummary {
        kind: RunKind::F0GlobalSingleton,
        variant: 0,
        final_loss: d5.final_loss,
        final_accuracy: d5.final_accuracy,
        final_mse: d5.final_mse,
        telemetry: Telemetry {
            selected_primitives: d5.telemetry.selected,
            programs: d5.telemetry.batches,
            utility_evaluations: d5.telemetry.utility_evaluations,
            predicted_utility: d5.telemetry.predicted_utility,
            realized_utility: d5.telemetry.realized_utility,
        },
        partition_objective: None,
        curve,
    }
}

fn interaction_weights(samples: &[Sample]) -> [[f32; PARAMS]; PARAMS] {
    let map = run_int1(samples);
    let mut weights = [[0.0; PARAMS]; PARAMS];
    for pair in map.pairs {
        let weight = pair.interaction.abs();
        weights[pair.first][pair.second] += weight;
        weights[pair.second][pair.first] += weight;
    }
    weights
}

fn partition_objective(partition: Partition, weights: &[[f32; PARAMS]; PARAMS]) -> f32 {
    let mut total = 0.0;
    for group in partition.groups[..partition.count].iter().copied() {
        for first in 0..group.len {
            for second in first + 1..group.len {
                total += weights[group.indices[first]][group.indices[second]];
            }
        }
    }
    total
}

fn locate(partition: Partition, index: usize) -> Option<(usize, usize)> {
    for (group_index, group) in partition.groups[..partition.count].iter().enumerate() {
        for slot in 0..group.len {
            if group.indices[slot] == index {
                return Some((group_index, slot));
            }
        }
    }
    None
}

fn swap_partition_indices(mut partition: Partition, first: usize, second: usize) -> Partition {
    let Some((first_group, first_slot)) = locate(partition, first) else {
        return partition;
    };
    let Some((second_group, second_slot)) = locate(partition, second) else {
        return partition;
    };
    partition.groups[first_group].indices[first_slot] = second;
    partition.groups[second_group].indices[second_slot] = first;
    partition
}

fn optimize_partition(samples: &[Sample], maximize: bool) -> (Partition, f32) {
    let weights = interaction_weights(samples);
    let mut rng = Rng::new(if maximize {
        0x9e37_79b9_7f4a_7c15
    } else {
        0x517c_c1b7_2722_0a95
    });
    let mut global = random_e2_partition(rng.next());
    let mut global_value = partition_objective(global, &weights);
    for _ in 0..128 {
        let mut current = random_e2_partition(rng.next());
        let mut current_value = partition_objective(current, &weights);
        for _ in 0..2_000 {
            let first = (rng.next() as usize) % PARAMS;
            let second = (rng.next() as usize) % PARAMS;
            if first == second {
                continue;
            }
            let candidate = swap_partition_indices(current, first, second);
            let candidate_value = partition_objective(candidate, &weights);
            let improves = if maximize {
                candidate_value > current_value
            } else {
                candidate_value < current_value
            };
            if improves {
                current = candidate;
                current_value = candidate_value;
            }
        }
        let improves = if maximize {
            current_value > global_value
        } else {
            current_value < global_value
        };
        if improves {
            global = current;
            global_value = current_value;
        }
    }
    (global, global_value)
}

fn set_variant(mut summary: RunSummary, variant: usize) -> RunSummary {
    summary.variant = variant;
    summary
}

pub fn run_kind(samples: &[Sample], kind: RunKind) -> RunSummary {
    match kind {
        RunKind::F0GlobalSingleton => {
            from_d5_result(run_d_policy(samples, DPolicy::D5GlobalGreedy))
        }
        RunKind::F1RandomFixed => {
            let partition = random_e2_partition(0x1000_0000_0000_0001);
            run_partition_policy(samples, kind, EPOCHS, Some(partition), false, false)
        }
        RunKind::F2AntiTopology => {
            let (partition, objective) = optimize_partition(samples, false);
            let mut result =
                run_partition_policy(samples, kind, EPOCHS, Some(partition), false, false);
            result.partition_objective = Some(objective);
            result
        }
        RunKind::F3TopologyMax => {
            let (partition, objective) = optimize_partition(samples, true);
            let mut result =
                run_partition_policy(samples, kind, EPOCHS, Some(partition), false, false);
            result.partition_objective = Some(objective);
            result
        }
        RunKind::F4DynamicRandom => run_partition_policy(samples, kind, EPOCHS, None, false, true),
        RunKind::F5StructuralSingletonScore => run_partition_policy(
            samples,
            kind,
            EPOCHS,
            Some(STRUCTURAL_PARTITION),
            true,
            false,
        ),
        RunKind::F6StructuralCompoundScore => run_partition_policy(
            samples,
            kind,
            EPOCHS,
            Some(STRUCTURAL_PARTITION),
            false,
            false,
        ),
        RunKind::Width(width) => {
            let sizes = width_sizes(width);
            let partition = partition_from_sizes(&sizes, 0x4000_0000_0000_0000 + width as u64);
            run_partition_policy(samples, kind, EPOCHS, Some(partition), false, false)
        }
    }
}

fn width_sizes(width: usize) -> [usize; PARAMS] {
    let mut sizes = [0; PARAMS];
    let mut remaining = PARAMS;
    let mut count = 0;
    while remaining > 0 {
        let len = remaining.min(width);
        sizes[count] = len;
        count += 1;
        remaining -= len;
    }
    sizes
}

pub fn run_random_fixed(samples: &[Sample], variant: usize) -> RunSummary {
    let partition = random_e2_partition(0x1000_0000_0000_0001 + variant as u64);
    set_variant(
        run_partition_policy(
            samples,
            RunKind::F1RandomFixed,
            EPOCHS,
            Some(partition),
            false,
            false,
        ),
        variant,
    )
}

pub fn run_all(samples: &[Sample]) -> Vec<RunSummary> {
    let mut results = Vec::with_capacity(8 + RANDOM_PARTITIONS + 4);
    results.push(run_kind(samples, RunKind::F0GlobalSingleton));
    for variant in 0..RANDOM_PARTITIONS {
        results.push(run_random_fixed(samples, variant));
    }
    results.push(run_kind(samples, RunKind::F2AntiTopology));
    results.push(run_kind(samples, RunKind::F3TopologyMax));
    results.push(run_kind(samples, RunKind::F4DynamicRandom));
    results.push(run_kind(samples, RunKind::F5StructuralSingletonScore));
    results.push(run_kind(samples, RunKind::F6StructuralCompoundScore));
    for width in 1..=4 {
        results.push(run_kind(samples, RunKind::Width(width)));
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
    fn structural_partition_has_expected_shape() {
        assert_eq!(STRUCTURAL_PARTITION.count, 9);
        assert_eq!(
            STRUCTURAL_PARTITION.groups[..4]
                .iter()
                .map(|group| group.len)
                .sum::<usize>(),
            12
        );
    }

    #[test]
    fn short_controls_evaluate_and_commit() {
        let samples = xor_samples();
        for kind in [
            RunKind::F1RandomFixed,
            RunKind::F2AntiTopology,
            RunKind::F3TopologyMax,
            RunKind::F4DynamicRandom,
            RunKind::F5StructuralSingletonScore,
            RunKind::F6StructuralCompoundScore,
            RunKind::Width(1),
            RunKind::Width(2),
        ] {
            let result = match kind {
                RunKind::F2AntiTopology => {
                    let (partition, _) = optimize_partition(&samples, false);
                    run_partition_policy(&samples, kind, 1, Some(partition), false, false)
                }
                RunKind::F3TopologyMax => {
                    let (partition, _) = optimize_partition(&samples, true);
                    run_partition_policy(&samples, kind, 1, Some(partition), false, false)
                }
                RunKind::F4DynamicRandom => {
                    run_partition_policy(&samples, kind, 1, None, false, true)
                }
                RunKind::F5StructuralSingletonScore => {
                    run_partition_policy(&samples, kind, 1, Some(STRUCTURAL_PARTITION), true, false)
                }
                RunKind::F6StructuralCompoundScore => run_partition_policy(
                    &samples,
                    kind,
                    1,
                    Some(STRUCTURAL_PARTITION),
                    false,
                    false,
                ),
                RunKind::Width(width) => run_partition_policy(
                    &samples,
                    kind,
                    1,
                    Some(partition_from_sizes(&width_sizes(width), 9)),
                    false,
                    false,
                ),
                RunKind::F1RandomFixed => run_partition_policy(
                    &samples,
                    kind,
                    1,
                    Some(random_e2_partition(9)),
                    false,
                    false,
                ),
                RunKind::F0GlobalSingleton => unreachable!(),
            };
            assert!(result.telemetry.utility_evaluations > 0);
            assert!(result.telemetry.selected_primitives > 0);
        }
    }
}
