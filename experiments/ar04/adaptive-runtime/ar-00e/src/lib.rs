use adaptive_runtime_ar_00::{Model, PARAMS, Sample, xor_samples};
use adaptive_runtime_ar_00d::{Policy as DPolicy, run as run_d_policy};

pub const EPOCHS: usize = 3_000;
pub const PRIMITIVE_BUDGET: usize = PARAMS;
pub const ACTION_LEVELS: usize = 5;
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
pub enum Policy {
    E0GlobalSingleton,
    E1SingletonOrPair,
    E2StructuralGroups,
    E3RandomizedGroups,
}

impl Policy {
    pub const fn label(self) -> &'static str {
        match self {
            Self::E0GlobalSingleton => "E0-global-singleton",
            Self::E1SingletonOrPair => "E1-singleton-or-pair",
            Self::E2StructuralGroups => "E2-structural-groups",
            Self::E3RandomizedGroups => "E3-randomized-groups",
        }
    }

    pub const fn all() -> [Self; 4] {
        [
            Self::E0GlobalSingleton,
            Self::E1SingletonOrPair,
            Self::E2StructuralGroups,
            Self::E3RandomizedGroups,
        ]
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Telemetry {
    pub selected_primitives: u64,
    pub programs: u64,
    pub pair_programs: u64,
    pub group_programs: u64,
    pub utility_evaluations: u64,
    pub predicted_utility: f32,
    pub realized_utility: f32,
}

impl Telemetry {
    fn absorb(&mut self, other: Self) {
        self.selected_primitives += other.selected_primitives;
        self.programs += other.programs;
        self.pair_programs += other.pair_programs;
        self.group_programs += other.group_programs;
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
    pub pair_programs: u64,
    pub group_programs: u64,
    pub utility_evaluations: u64,
    pub predicted_utility: f32,
    pub realized_utility: f32,
}

#[derive(Clone, Debug)]
pub struct ResultSummary {
    pub policy: Policy,
    pub final_loss: f32,
    pub final_accuracy: f32,
    pub final_mse: f32,
    pub final_probabilities: [f32; 4],
    pub final_logits: [f32; 4],
    pub final_margins: [f32; 4],
    pub telemetry: Telemetry,
    pub curve: Vec<CurvePoint>,
}

#[derive(Clone, Copy, Debug, Default)]
struct PrimitiveAction {
    index: usize,
    delta: f32,
    utility: f32,
}

#[derive(Clone, Copy, Debug, Default)]
struct Program {
    indices: [usize; 3],
    deltas: [f32; 3],
    len: usize,
    utility: f32,
}

#[derive(Clone, Copy, Debug, Default)]
struct Group {
    indices: [usize; 3],
    len: usize,
}

fn final_metrics(model: &Model, samples: &[Sample]) -> ([f32; 4], [f32; 4], [f32; 4]) {
    let mut probabilities = [0.0; 4];
    let mut logits = [0.0; 4];
    let mut margins = [0.0; 4];
    for (index, &sample) in samples.iter().enumerate() {
        let probability = model.predict(sample).clamp(1e-6, 1.0 - 1e-6);
        let logit = (probability / (1.0 - probability)).ln();
        probabilities[index] = probability;
        logits[index] = logit;
        margins[index] = if sample.target >= 0.5 { logit } else { -logit };
    }
    (probabilities, logits, margins)
}

fn make_result(
    policy: Policy,
    model: &Model,
    samples: &[Sample],
    telemetry: Telemetry,
    curve: Vec<CurvePoint>,
) -> ResultSummary {
    let final_loss = model.loss_and_gradient(samples).0;
    let (final_probabilities, final_logits, final_margins) = final_metrics(model, samples);
    ResultSummary {
        policy,
        final_loss,
        final_accuracy: model.accuracy(samples),
        final_mse: model.simd_mean_squared_error(samples),
        final_probabilities,
        final_logits,
        final_margins,
        telemetry,
        curve,
    }
}

fn best_singletons(
    model: &Model,
    samples: &[Sample],
    baseline_loss: f32,
) -> ([Option<PrimitiveAction>; PARAMS], u64) {
    let mut actions = [None; PARAMS];
    let mut evaluations = 0;
    for (index, output) in actions.iter_mut().enumerate() {
        let current = model.parameters[index];
        let mut best = PrimitiveAction {
            index,
            ..PrimitiveAction::default()
        };
        for &magnitude in &ACTION_VALUES[1..] {
            let candidate = current + magnitude;
            if !(LOWER_BOUND..=UPPER_BOUND).contains(&candidate) {
                continue;
            }
            evaluations += 1;
            let mut candidate_model = *model;
            candidate_model.parameters[index] = candidate;
            let utility = baseline_loss - candidate_model.loss_and_gradient(samples).0;
            if utility > best.utility {
                best = PrimitiveAction {
                    index,
                    delta: magnitude,
                    utility,
                };
            }
        }
        if best.utility > 0.0 {
            *output = Some(best);
        }
    }
    (actions, evaluations)
}

fn program_from_single(action: PrimitiveAction) -> Program {
    Program {
        indices: [action.index, 0, 0],
        deltas: [action.delta, 0.0, 0.0],
        len: 1,
        utility: action.utility,
    }
}

fn program_from_pair(first: PrimitiveAction, second: PrimitiveAction, utility: f32) -> Program {
    Program {
        indices: [first.index, second.index, 0],
        deltas: [first.delta, second.delta, 0.0],
        len: 2,
        utility,
    }
}

fn commit_program(
    model: &mut Model,
    samples: &[Sample],
    baseline_loss: f32,
    program: Program,
    pair: bool,
    group: bool,
) -> Telemetry {
    let mut telemetry = Telemetry {
        selected_primitives: program.len as u64,
        programs: 1,
        pair_programs: u64::from(pair),
        group_programs: u64::from(group),
        predicted_utility: program.utility,
        ..Telemetry::default()
    };
    for slot in 0..program.len {
        model.parameters[program.indices[slot]] += program.deltas[slot];
    }
    let realized_loss = model.loss_and_gradient(samples).0;
    telemetry.realized_utility = baseline_loss - realized_loss;
    telemetry
}

fn best_pair_program(
    model: &Model,
    samples: &[Sample],
    baseline_loss: f32,
    actions: &[Option<PrimitiveAction>; PARAMS],
) -> (Option<Program>, u64) {
    let mut best = None;
    let mut evaluations = 0;
    for first in 0..PARAMS {
        let Some(first_action) = actions[first] else {
            continue;
        };
        for (_second, second_action) in actions.iter().enumerate().skip(first + 1) {
            let Some(second_action) = *second_action else {
                continue;
            };
            let mut candidate_model = *model;
            candidate_model.parameters[first_action.index] += first_action.delta;
            candidate_model.parameters[second_action.index] += second_action.delta;
            let utility = baseline_loss - candidate_model.loss_and_gradient(samples).0;
            evaluations += 1;
            if utility > best.map_or(0.0, |program: Program| program.utility) {
                best = Some(program_from_pair(first_action, second_action, utility));
            }
        }
    }
    (best, evaluations)
}

fn run_singleton_or_pair(samples: &[Sample], epochs: usize) -> ResultSummary {
    let policy = Policy::E1SingletonOrPair;
    let mut model = Model::initial();
    let mut total = Telemetry::default();
    let mut curve = Vec::with_capacity(epochs);
    for epoch in 0..epochs {
        let loss_before = model.loss_and_gradient(samples).0;
        let mut epoch_telemetry = Telemetry::default();
        let mut remaining = PRIMITIVE_BUDGET;
        while remaining > 0 {
            let baseline_loss = model.loss_and_gradient(samples).0;
            let (actions, singleton_evaluations) = best_singletons(&model, samples, baseline_loss);
            epoch_telemetry.utility_evaluations += singleton_evaluations;
            let mut best_single = None;
            for action in actions.into_iter().flatten() {
                if best_single
                    .is_none_or(|current: PrimitiveAction| action.utility > current.utility)
                {
                    best_single = Some(action);
                }
            }
            let (best_pair, pair_evaluations) = if remaining >= 2 {
                best_pair_program(&model, samples, baseline_loss, &actions)
            } else {
                (None, 0)
            };
            epoch_telemetry.utility_evaluations += pair_evaluations;
            let Some(single) = best_single else {
                break;
            };
            let single_program = program_from_single(single);
            let use_pair = best_pair.is_some_and(|pair| pair.utility > single_program.utility);
            let program = if use_pair {
                best_pair.expect("pair selected by predicate")
            } else {
                single_program
            };
            epoch_telemetry.absorb(commit_program(
                &mut model,
                samples,
                baseline_loss,
                program,
                use_pair,
                false,
            ));
            remaining -= program.len;
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
            pair_programs: epoch_telemetry.pair_programs,
            group_programs: epoch_telemetry.group_programs,
            utility_evaluations: epoch_telemetry.utility_evaluations,
            predicted_utility: epoch_telemetry.predicted_utility,
            realized_utility: epoch_telemetry.realized_utility,
        });
    }
    make_result(policy, &model, samples, total, curve)
}

fn run_singleton_only(samples: &[Sample], epochs: usize) -> ResultSummary {
    let policy = Policy::E0GlobalSingleton;
    let mut model = Model::initial();
    let mut total = Telemetry::default();
    let mut curve = Vec::with_capacity(epochs);
    for epoch in 0..epochs {
        let loss_before = model.loss_and_gradient(samples).0;
        let mut epoch_telemetry = Telemetry::default();
        let mut remaining = PRIMITIVE_BUDGET;
        while remaining > 0 {
            let baseline_loss = model.loss_and_gradient(samples).0;
            let (actions, evaluations) = best_singletons(&model, samples, baseline_loss);
            epoch_telemetry.utility_evaluations += evaluations;
            let Some(action) = actions
                .into_iter()
                .flatten()
                .max_by(|left, right| left.utility.total_cmp(&right.utility))
            else {
                break;
            };
            epoch_telemetry.absorb(commit_program(
                &mut model,
                samples,
                baseline_loss,
                program_from_single(action),
                false,
                false,
            ));
            remaining -= 1;
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
            pair_programs: epoch_telemetry.pair_programs,
            group_programs: epoch_telemetry.group_programs,
            utility_evaluations: epoch_telemetry.utility_evaluations,
            predicted_utility: epoch_telemetry.predicted_utility,
            realized_utility: epoch_telemetry.realized_utility,
        });
    }
    make_result(policy, &model, samples, total, curve)
}

const STRUCTURAL_GROUPS: [Group; 9] = [
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
];

#[derive(Clone, Copy, Debug)]
struct GroupRng {
    state: u64,
}

impl GroupRng {
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

    fn groups_for_epoch(&mut self) -> [Group; 9] {
        let mut indices = [0usize; PARAMS];
        for (index, value) in indices.iter_mut().enumerate() {
            *value = index;
        }
        for index in (1..PARAMS).rev() {
            indices.swap(index, (self.next() as usize) % (index + 1));
        }
        let mut groups = [Group::default(); 9];
        let mut cursor = 0;
        for (group_index, group) in groups.iter_mut().enumerate() {
            let len = if group_index < 4 { 3 } else { 1 };
            group.len = len;
            group.indices[..len].copy_from_slice(&indices[cursor..cursor + len]);
            cursor += len;
        }
        groups
    }
}

fn best_group_program(
    model: &Model,
    samples: &[Sample],
    baseline_loss: f32,
    group: Group,
) -> (Option<Program>, u64) {
    let mut best = None;
    let mut evaluations = 0;
    match group.len {
        1 => {
            for &delta in &ACTION_VALUES {
                let index = group.indices[0];
                if !(LOWER_BOUND..=UPPER_BOUND).contains(&(model.parameters[index] + delta)) {
                    continue;
                }
                let mut candidate_model = *model;
                candidate_model.parameters[index] += delta;
                let utility = baseline_loss - candidate_model.loss_and_gradient(samples).0;
                evaluations += 1;
                if utility > best.map_or(0.0, |program: Program| program.utility) {
                    best = Some(Program {
                        indices: [index, 0, 0],
                        deltas: [delta, 0.0, 0.0],
                        len: 1,
                        utility,
                    });
                }
            }
        }
        3 => {
            for &first_delta in &ACTION_VALUES {
                for &second_delta in &ACTION_VALUES {
                    for &third_delta in &ACTION_VALUES {
                        let deltas = [first_delta, second_delta, third_delta];
                        let valid = (0..3).all(|slot| {
                            (LOWER_BOUND..=UPPER_BOUND)
                                .contains(&(model.parameters[group.indices[slot]] + deltas[slot]))
                        });
                        if !valid {
                            continue;
                        }
                        let mut candidate_model = *model;
                        for (slot, delta) in deltas.iter().enumerate() {
                            candidate_model.parameters[group.indices[slot]] += *delta;
                        }
                        let utility = baseline_loss - candidate_model.loss_and_gradient(samples).0;
                        evaluations += 1;
                        if utility > best.map_or(0.0, |program: Program| program.utility) {
                            best = Some(Program {
                                indices: group.indices,
                                deltas,
                                len: 3,
                                utility,
                            });
                        }
                    }
                }
            }
        }
        _ => unreachable!("AR-00E groups have size one or three"),
    }
    (best.filter(|program| program.utility > 0.0), evaluations)
}

fn run_group_policy(samples: &[Sample], policy: Policy, epochs: usize) -> ResultSummary {
    let mut model = Model::initial();
    let mut total = Telemetry::default();
    let mut curve = Vec::with_capacity(epochs);
    let mut rng = GroupRng::new(0x2b7e_1516_28ae_d2a6);
    for epoch in 0..epochs {
        let loss_before = model.loss_and_gradient(samples).0;
        let groups = if policy == Policy::E2StructuralGroups {
            STRUCTURAL_GROUPS
        } else {
            rng.groups_for_epoch()
        };
        let mut epoch_telemetry = Telemetry::default();
        let mut remaining = PRIMITIVE_BUDGET;
        while remaining > 0 {
            let baseline_loss = model.loss_and_gradient(samples).0;
            let mut best = None;
            for group in groups {
                if group.len > remaining {
                    continue;
                }
                let (program, evaluations) =
                    best_group_program(&model, samples, baseline_loss, group);
                epoch_telemetry.utility_evaluations += evaluations;
                if let Some(program) = program
                    && best.is_none_or(|current: Program| program.utility > current.utility)
                {
                    best = Some(program);
                }
            }
            let Some(program) = best else {
                break;
            };
            epoch_telemetry.absorb(commit_program(
                &mut model,
                samples,
                baseline_loss,
                program,
                false,
                true,
            ));
            remaining -= program.len;
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
            pair_programs: epoch_telemetry.pair_programs,
            group_programs: epoch_telemetry.group_programs,
            utility_evaluations: epoch_telemetry.utility_evaluations,
            predicted_utility: epoch_telemetry.predicted_utility,
            realized_utility: epoch_telemetry.realized_utility,
        });
    }
    make_result(policy, &model, samples, total, curve)
}

fn from_d5_result(d5: adaptive_runtime_ar_00d::ResultSummary) -> ResultSummary {
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
            utility_evaluations: 0,
            predicted_utility: point.predicted_utility,
            realized_utility: point.realized_utility,
            ..CurvePoint::default()
        })
        .collect();
    let telemetry = d5.telemetry;
    ResultSummary {
        policy: Policy::E0GlobalSingleton,
        final_loss: d5.final_loss,
        final_accuracy: d5.final_accuracy,
        final_mse: d5.final_mse,
        final_probabilities: d5.final_probabilities,
        final_logits: d5.final_logits,
        final_margins: d5.final_margins,
        telemetry: Telemetry {
            selected_primitives: telemetry.selected,
            programs: telemetry.batches,
            utility_evaluations: telemetry.utility_evaluations,
            predicted_utility: telemetry.predicted_utility,
            realized_utility: telemetry.realized_utility,
            ..Telemetry::default()
        },
        curve,
    }
}

pub fn run_for_epochs(samples: &[Sample], policy: Policy, epochs: usize) -> ResultSummary {
    match policy {
        Policy::E0GlobalSingleton if epochs == EPOCHS => {
            from_d5_result(run_d_policy(samples, DPolicy::D5GlobalGreedy))
        }
        Policy::E0GlobalSingleton => run_singleton_only(samples, epochs),
        Policy::E1SingletonOrPair => run_singleton_or_pair(samples, epochs),
        Policy::E2StructuralGroups | Policy::E3RandomizedGroups => {
            run_group_policy(samples, policy, epochs)
        }
    }
}

pub fn run(samples: &[Sample], policy: Policy) -> ResultSummary {
    run_for_epochs(samples, policy, EPOCHS)
}

pub fn run_all(samples: &[Sample]) -> [ResultSummary; 4] {
    [
        run(samples, Policy::E0GlobalSingleton),
        run(samples, Policy::E1SingletonOrPair),
        run(samples, Policy::E2StructuralGroups),
        run(samples, Policy::E3RandomizedGroups),
    ]
}

pub fn xor_samples_for_tests() -> [Sample; 4] {
    xor_samples()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn e0_is_the_frozen_d5_control() {
        let result = run(&xor_samples(), Policy::E0GlobalSingleton);
        assert_eq!(result.final_accuracy, 1.0);
        assert!((result.final_loss - 0.18534479).abs() < 0.00001);
    }

    #[test]
    fn short_structural_arms_produce_actions() {
        let samples = xor_samples();
        for policy in [
            Policy::E1SingletonOrPair,
            Policy::E2StructuralGroups,
            Policy::E3RandomizedGroups,
        ] {
            let result = run_for_epochs(&samples, policy, 2);
            assert_eq!(result.curve.len(), 2);
            assert!(result.telemetry.selected_primitives > 0);
            assert!(result.telemetry.utility_evaluations > 0);
        }
    }
}
