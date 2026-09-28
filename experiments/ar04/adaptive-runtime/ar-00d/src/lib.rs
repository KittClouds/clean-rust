use adaptive_runtime_ar_00::{Model, PARAMS, Sample, xor_samples};

pub const EPOCHS: usize = 3_000;
pub const ACTION_STEP: f32 = 0.02;
pub const LOWER_BOUND: f32 = -3.0;
pub const UPPER_BOUND: f32 = 3.0;
pub const ACTION_LEVELS: usize = 5;

const MAGNITUDES: &[f32] = &[
    ACTION_STEP,
    ACTION_STEP * 0.5,
    ACTION_STEP * 0.25,
    ACTION_STEP * 0.125,
    ACTION_STEP * 0.0625,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Policy {
    D0All,
    D1Batch8,
    D2Batch4,
    D3Batch2,
    D4FixedSingleton,
    D5GlobalGreedy,
}

impl Policy {
    pub const fn label(self) -> &'static str {
        match self {
            Self::D0All => "D0-all",
            Self::D1Batch8 => "D1-batch8",
            Self::D2Batch4 => "D2-batch4",
            Self::D3Batch2 => "D3-batch2",
            Self::D4FixedSingleton => "D4-fixed1",
            Self::D5GlobalGreedy => "D5-global1",
        }
    }

    pub const fn batch_size(self) -> usize {
        match self {
            Self::D0All => PARAMS,
            Self::D1Batch8 => 8,
            Self::D2Batch4 => 4,
            Self::D3Batch2 => 2,
            Self::D4FixedSingleton | Self::D5GlobalGreedy => 1,
        }
    }

    pub const fn all() -> [Self; 6] {
        [
            Self::D0All,
            Self::D1Batch8,
            Self::D2Batch4,
            Self::D3Batch2,
            Self::D4FixedSingleton,
            Self::D5GlobalGreedy,
        ]
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Telemetry {
    pub selected: u64,
    pub no_op: u64,
    pub blocked: u64,
    pub batches: u64,
    pub refreshes: u64,
    pub utility_evaluations: u64,
    pub predicted_utility: f32,
    pub realized_utility: f32,
    pub composition_error: f32,
    pub absolute_composition_error: f32,
}

impl Telemetry {
    fn absorb(&mut self, other: Self) {
        self.selected += other.selected;
        self.no_op += other.no_op;
        self.blocked += other.blocked;
        self.batches += other.batches;
        self.refreshes += other.refreshes;
        self.utility_evaluations += other.utility_evaluations;
        self.predicted_utility += other.predicted_utility;
        self.realized_utility += other.realized_utility;
        self.composition_error += other.composition_error;
        self.absolute_composition_error += other.absolute_composition_error;
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct CurvePoint {
    pub epoch: usize,
    pub loss_before: f32,
    pub loss_after: f32,
    pub accuracy_after: f32,
    pub selected: u64,
    pub batches: u64,
    pub predicted_utility: f32,
    pub realized_utility: f32,
    pub composition_error: f32,
    pub absolute_composition_error: f32,
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
struct Action {
    index: usize,
    delta: f32,
    utility: f32,
}

fn best_singleton(
    model: &Model,
    samples: &[Sample],
    index: usize,
    baseline_loss: f32,
) -> (Option<Action>, u64, u64) {
    let current = model.parameters[index];
    let mut best = None;
    let mut blocked = 0;
    let mut evaluations = 0;
    for &magnitude in MAGNITUDES {
        for delta in [-magnitude, magnitude] {
            let candidate = current + delta;
            if !(LOWER_BOUND..=UPPER_BOUND).contains(&candidate) {
                blocked += 1;
                continue;
            }
            evaluations += 1;
            let mut candidate_model = *model;
            candidate_model.parameters[index] = candidate;
            let (candidate_loss, _) = candidate_model.loss_and_gradient(samples);
            let utility = baseline_loss - candidate_loss;
            if utility > best.map_or(0.0, |action: Action| action.utility) {
                best = Some(Action {
                    index,
                    delta,
                    utility,
                });
            }
        }
    }
    (best, blocked, evaluations)
}

fn commit_batch(model: &mut Model, samples: &[Sample], start: usize, end: usize) -> Telemetry {
    let baseline_loss = model.loss_and_gradient(samples).0;
    let mut actions = [Action::default(); PARAMS];
    let mut selected_count = 0;
    let mut telemetry = Telemetry {
        batches: 1,
        refreshes: 1,
        ..Telemetry::default()
    };
    for index in start..end {
        let (action, blocked, evaluations) = best_singleton(model, samples, index, baseline_loss);
        telemetry.blocked += blocked;
        telemetry.utility_evaluations += evaluations;
        if let Some(action) = action {
            actions[selected_count] = action;
            selected_count += 1;
            telemetry.predicted_utility += action.utility;
        } else {
            telemetry.no_op += 1;
        }
    }
    for action in actions.into_iter().take(selected_count) {
        model.parameters[action.index] += action.delta;
        telemetry.selected += 1;
    }
    let realized_loss = model.loss_and_gradient(samples).0;
    telemetry.realized_utility = baseline_loss - realized_loss;
    telemetry.composition_error = telemetry.predicted_utility - telemetry.realized_utility;
    telemetry.absolute_composition_error = telemetry.composition_error.abs();
    telemetry
}

fn commit_global_greedy(model: &mut Model, samples: &[Sample]) -> Telemetry {
    let mut telemetry = Telemetry::default();
    for _ in 0..PARAMS {
        let baseline_loss = model.loss_and_gradient(samples).0;
        let mut best = None;
        let mut blocked = 0;
        let mut evaluations = 0;
        for index in 0..PARAMS {
            let (action, action_blocked, action_evaluations) =
                best_singleton(model, samples, index, baseline_loss);
            blocked += action_blocked;
            evaluations += action_evaluations;
            if let Some(action) = action
                && best.is_none_or(|current: Action| action.utility > current.utility)
            {
                best = Some(action);
            }
        }
        telemetry.blocked += blocked;
        telemetry.utility_evaluations += evaluations;
        telemetry.batches += 1;
        telemetry.refreshes += 1;
        let Some(action) = best else {
            telemetry.no_op += 1;
            break;
        };
        model.parameters[action.index] += action.delta;
        let realized_loss = model.loss_and_gradient(samples).0;
        telemetry.selected += 1;
        telemetry.predicted_utility += action.utility;
        telemetry.realized_utility += baseline_loss - realized_loss;
    }
    telemetry.composition_error = telemetry.predicted_utility - telemetry.realized_utility;
    telemetry.absolute_composition_error = telemetry.composition_error.abs();
    telemetry
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

pub fn run(samples: &[Sample], policy: Policy) -> ResultSummary {
    let mut model = Model::initial();
    let mut total = Telemetry::default();
    let mut curve = Vec::with_capacity(EPOCHS);
    for epoch in 0..EPOCHS {
        let loss_before = model.loss_and_gradient(samples).0;
        let mut epoch_telemetry = Telemetry::default();
        if policy == Policy::D5GlobalGreedy {
            epoch_telemetry = commit_global_greedy(&mut model, samples);
        } else {
            let batch_size = policy.batch_size();
            for start in (0..PARAMS).step_by(batch_size) {
                let end = (start + batch_size).min(PARAMS);
                epoch_telemetry.absorb(commit_batch(&mut model, samples, start, end));
            }
        }
        total.absorb(epoch_telemetry);
        let loss_after = model.loss_and_gradient(samples).0;
        curve.push(CurvePoint {
            epoch,
            loss_before,
            loss_after,
            accuracy_after: model.accuracy(samples),
            selected: epoch_telemetry.selected,
            batches: epoch_telemetry.batches,
            predicted_utility: epoch_telemetry.predicted_utility,
            realized_utility: epoch_telemetry.realized_utility,
            composition_error: epoch_telemetry.composition_error,
            absolute_composition_error: epoch_telemetry.absolute_composition_error,
        });
    }
    let final_loss = model.loss_and_gradient(samples).0;
    let (final_probabilities, final_logits, final_margins) = final_metrics(&model, samples);
    ResultSummary {
        policy,
        final_loss,
        final_accuracy: model.accuracy(samples),
        final_mse: model.simd_mean_squared_error(samples),
        final_probabilities,
        final_logits,
        final_margins,
        telemetry: total,
        curve,
    }
}

pub fn run_all(samples: &[Sample]) -> [ResultSummary; 6] {
    [
        run(samples, Policy::D0All),
        run(samples, Policy::D1Batch8),
        run(samples, Policy::D2Batch4),
        run(samples, Policy::D3Batch2),
        run(samples, Policy::D4FixedSingleton),
        run(samples, Policy::D5GlobalGreedy),
    ]
}

pub fn xor_samples_for_tests() -> [Sample; 4] {
    xor_samples()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_policy_has_a_complete_curve() {
        let samples = xor_samples();
        for policy in Policy::all() {
            let result = run(&samples, policy);
            assert_eq!(result.curve.len(), EPOCHS);
            assert!(result.telemetry.utility_evaluations > 0);
        }
    }

    #[test]
    fn d0_reproduces_singleton_oracle_failure_shape() {
        let result = run(&xor_samples(), Policy::D0All);
        assert!(result.telemetry.predicted_utility > 0.0);
        assert!(result.final_accuracy < 1.0);
        assert!(result.final_loss > 0.3);
    }
}
