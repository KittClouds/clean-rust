use adaptive_runtime_ar_00::{Model, PARAMS, Sample, xor_samples};

pub const EPOCHS: usize = 3_000;
pub const ACTION_STEP: f32 = 0.02;
pub const LOWER_BOUND: f32 = -3.0;
pub const UPPER_BOUND: f32 = 3.0;
pub const ACTION_LEVELS: usize = 5;
pub const ACTION_COST_LAMBDA: f32 = 0.002;
pub const QUADRATIC_CURVATURE: f32 = 1.0;

const MAGNITUDES: &[f32] = &[
    ACTION_STEP,
    ACTION_STEP * 0.5,
    ACTION_STEP * 0.25,
    ACTION_STEP * 0.125,
    ACTION_STEP * 0.0625,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UtilityArm {
    C0Linear,
    C1ActionCost,
    C2Quadratic,
    C3Oracle,
}

impl UtilityArm {
    pub const fn label(self) -> &'static str {
        match self {
            Self::C0Linear => "C0-linear",
            Self::C1ActionCost => "C1-action-cost",
            Self::C2Quadratic => "C2-quadratic",
            Self::C3Oracle => "C3-oracle",
        }
    }

    pub const fn all() -> [Self; 4] {
        [
            Self::C0Linear,
            Self::C1ActionCost,
            Self::C2Quadratic,
            Self::C3Oracle,
        ]
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Telemetry {
    pub selected: u64,
    pub no_op: u64,
    pub blocked: u64,
    pub selected_positive: u64,
    pub selected_negative: u64,
    pub sign_reversals: u64,
    pub min_selected_magnitude: f32,
    pub selected_by_level: [u64; ACTION_LEVELS],
    pub predicted_utility: f32,
    pub realized_utility: f32,
    pub composition_error: f32,
    pub absolute_composition_error: f32,
}

impl Telemetry {
    fn absorb(&mut self, step: Self) {
        self.selected += step.selected;
        self.no_op += step.no_op;
        self.blocked += step.blocked;
        self.selected_positive += step.selected_positive;
        self.selected_negative += step.selected_negative;
        self.sign_reversals += step.sign_reversals;
        if step.min_selected_magnitude > 0.0
            && (self.min_selected_magnitude == 0.0
                || step.min_selected_magnitude < self.min_selected_magnitude)
        {
            self.min_selected_magnitude = step.min_selected_magnitude;
        }
        for (total, value) in self
            .selected_by_level
            .iter_mut()
            .zip(step.selected_by_level)
        {
            *total += value;
        }
        self.predicted_utility += step.predicted_utility;
        self.realized_utility += step.realized_utility;
        self.composition_error += step.composition_error;
        self.absolute_composition_error += step.absolute_composition_error;
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct CurvePoint {
    pub epoch: usize,
    pub loss_before: f32,
    pub loss_after: f32,
    pub accuracy_after: f32,
    pub selected: u64,
    pub no_op: u64,
    pub blocked: u64,
    pub min_selected_magnitude: f32,
    pub predicted_utility: f32,
    pub realized_utility: f32,
    pub composition_error: f32,
    pub absolute_composition_error: f32,
}

#[derive(Clone, Debug)]
pub struct UtilityResult {
    pub arm: UtilityArm,
    pub final_loss: f32,
    pub final_accuracy: f32,
    pub final_mse: f32,
    pub final_probabilities: [f32; 4],
    pub final_logits: [f32; 4],
    pub final_margins: [f32; 4],
    pub telemetry: Telemetry,
    pub curve: Vec<CurvePoint>,
    pub choices: Vec<[i8; PARAMS]>,
}

struct UtilityRuntime {
    arm: UtilityArm,
    last_sign: [i8; PARAMS],
    telemetry: Telemetry,
}

impl UtilityRuntime {
    fn new(arm: UtilityArm) -> Self {
        Self {
            arm,
            last_sign: [0; PARAMS],
            telemetry: Telemetry::default(),
        }
    }

    fn apply(
        &mut self,
        model: &mut Model,
        samples: &[Sample],
        gradient: &[f32; PARAMS],
        loss_before: f32,
    ) -> (Telemetry, [i8; PARAMS]) {
        let previous = model.parameters;
        let mut step = Telemetry::default();
        let mut choices = [0_i8; PARAMS];
        for (index, &gradient_value) in gradient.iter().enumerate() {
            let current = previous[index];
            let mut best_delta = 0.0;
            let mut best_utility = 0.0;
            let mut best_level = 0;
            for (level, &magnitude) in MAGNITUDES.iter().enumerate() {
                for delta in [-magnitude, magnitude] {
                    let candidate = current + delta;
                    if !(LOWER_BOUND..=UPPER_BOUND).contains(&candidate) {
                        step.blocked += 1;
                        continue;
                    }
                    let utility = match self.arm {
                        UtilityArm::C0Linear => -gradient_value * delta,
                        UtilityArm::C1ActionCost => {
                            -gradient_value * delta - ACTION_COST_LAMBDA * delta.abs()
                        }
                        UtilityArm::C2Quadratic => {
                            -gradient_value * delta - 0.5 * QUADRATIC_CURVATURE * delta * delta
                        }
                        UtilityArm::C3Oracle => {
                            let mut candidate_model = *model;
                            candidate_model.parameters[index] = candidate;
                            let (candidate_loss, _) = candidate_model.loss_and_gradient(samples);
                            loss_before - candidate_loss
                        }
                    };
                    if utility > best_utility {
                        best_utility = utility;
                        best_delta = delta;
                        best_level = level;
                    }
                }
            }
            if best_delta == 0.0 {
                step.no_op += 1;
                continue;
            }
            choices[index] = if best_delta > 0.0 {
                (best_level + 1) as i8
            } else {
                -((best_level + 1) as i8)
            };
            model.parameters[index] = current + best_delta;
            step.selected += 1;
            step.predicted_utility += best_utility;
            if best_delta > 0.0 {
                step.selected_positive += 1;
            } else {
                step.selected_negative += 1;
            }
            let sign = if best_delta > 0.0 { 1 } else { -1 };
            if self.last_sign[index] != 0 && self.last_sign[index] != sign {
                step.sign_reversals += 1;
            }
            self.last_sign[index] = sign;
            step.selected_by_level[best_level] += 1;
            let magnitude = best_delta.abs();
            if step.min_selected_magnitude == 0.0 || magnitude < step.min_selected_magnitude {
                step.min_selected_magnitude = magnitude;
            }
        }
        let (loss_after, _) = model.loss_and_gradient(samples);
        step.realized_utility = loss_before - loss_after;
        step.composition_error = step.predicted_utility - step.realized_utility;
        step.absolute_composition_error = step.composition_error.abs();
        self.telemetry.absorb(step);
        (step, choices)
    }
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

pub fn run(samples: &[Sample], arm: UtilityArm) -> UtilityResult {
    let mut model = Model::initial();
    let mut runtime = UtilityRuntime::new(arm);
    let mut curve = Vec::with_capacity(EPOCHS);
    let mut choices = Vec::with_capacity(EPOCHS);
    for epoch in 0..EPOCHS {
        let (loss_before, gradient) = model.loss_and_gradient(samples);
        let (step, selected_choices) = runtime.apply(&mut model, samples, &gradient, loss_before);
        let (loss_after, _) = model.loss_and_gradient(samples);
        curve.push(CurvePoint {
            epoch,
            loss_before,
            loss_after,
            accuracy_after: model.accuracy(samples),
            selected: step.selected,
            no_op: step.no_op,
            blocked: step.blocked,
            min_selected_magnitude: step.min_selected_magnitude,
            predicted_utility: step.predicted_utility,
            realized_utility: step.realized_utility,
            composition_error: step.composition_error,
            absolute_composition_error: step.absolute_composition_error,
        });
        choices.push(selected_choices);
    }
    let (final_loss, _) = model.loss_and_gradient(samples);
    let (final_probabilities, final_logits, final_margins) = final_metrics(&model, samples);
    UtilityResult {
        arm,
        final_loss,
        final_accuracy: model.accuracy(samples),
        final_mse: model.simd_mean_squared_error(samples),
        final_probabilities,
        final_logits,
        final_margins,
        telemetry: runtime.telemetry,
        curve,
        choices,
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct ChoiceComparison {
    pub exact_fraction: f32,
    pub sign_fraction: f32,
    pub magnitude_fraction: f32,
}

pub fn compare_choices(candidate: &UtilityResult, oracle: &UtilityResult) -> ChoiceComparison {
    let total = (candidate.choices.len() * PARAMS) as f32;
    let mut exact = 0_u64;
    let mut sign = 0_u64;
    let mut magnitude = 0_u64;
    for (candidate_step, oracle_step) in candidate.choices.iter().zip(&oracle.choices) {
        for (&candidate_choice, &oracle_choice) in candidate_step.iter().zip(oracle_step) {
            if candidate_choice == oracle_choice {
                exact += 1;
            }
            if candidate_choice.signum() == oracle_choice.signum() {
                sign += 1;
            }
            if candidate_choice.unsigned_abs() == oracle_choice.unsigned_abs() {
                magnitude += 1;
            }
        }
    }
    ChoiceComparison {
        exact_fraction: exact as f32 / total,
        sign_fraction: sign as f32 / total,
        magnitude_fraction: magnitude as f32 / total,
    }
}

pub fn run_all(samples: &[Sample]) -> [UtilityResult; 4] {
    [
        run(samples, UtilityArm::C0Linear),
        run(samples, UtilityArm::C1ActionCost),
        run(samples, UtilityArm::C2Quadratic),
        run(samples, UtilityArm::C3Oracle),
    ]
}

pub fn xor_samples_for_tests() -> [Sample; 4] {
    xor_samples()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn analytic_utility_arms_learn_xor() {
        let samples = xor_samples();
        for arm in [
            UtilityArm::C0Linear,
            UtilityArm::C1ActionCost,
            UtilityArm::C2Quadratic,
        ] {
            let result = run(&samples, arm);
            assert_eq!(result.final_accuracy, 1.0);
            assert_eq!(result.curve.len(), EPOCHS);
        }
    }

    #[test]
    fn oracle_is_a_finite_effect_reference_even_when_commit_does_not_compose() {
        let result = run(&xor_samples(), UtilityArm::C3Oracle);
        assert!(result.telemetry.predicted_utility > 0.0);
        assert!(result.telemetry.realized_utility > 0.0);
        assert!(result.telemetry.absolute_composition_error > 1.0);
        assert!(result.telemetry.selected > 0);
    }

    #[test]
    fn oracle_records_composition_error() {
        let result = run(&xor_samples(), UtilityArm::C3Oracle);
        assert!(result.telemetry.predicted_utility > 0.0);
        assert!(result.telemetry.realized_utility > 0.0);
        assert!(result.telemetry.absolute_composition_error >= 0.0);
    }

    #[test]
    fn oracle_choice_comparison_is_reflexive() {
        let result = run(&xor_samples(), UtilityArm::C3Oracle);
        let comparison = compare_choices(&result, &result);
        assert_eq!(comparison.exact_fraction, 1.0);
        assert_eq!(comparison.sign_fraction, 1.0);
        assert_eq!(comparison.magnitude_fraction, 1.0);
    }
}
