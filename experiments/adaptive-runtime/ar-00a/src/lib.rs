use adaptive_runtime_ar_00::{AdamW, Model, PARAMS, RunResult as Ar00Result, Sample, xor_samples};

pub const EPOCHS: usize = 3_000;
pub const ACTION_STEP: f32 = 0.02;
pub const LOWER_BOUND: f32 = -3.0;
pub const UPPER_BOUND: f32 = 3.0;
pub const MAX_ACTION_LEVELS: usize = 5;

const A0_MAGNITUDES: &[f32] = &[ACTION_STEP];
const A1_MAGNITUDES: &[f32] = &[ACTION_STEP, ACTION_STEP * 0.5];
const A2_MAGNITUDES: &[f32] = &[ACTION_STEP, ACTION_STEP * 0.5, ACTION_STEP * 0.25];
const A3_MAGNITUDES: &[f32] = &[
    ACTION_STEP,
    ACTION_STEP * 0.5,
    ACTION_STEP * 0.25,
    ACTION_STEP * 0.125,
    ACTION_STEP * 0.0625,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u8)]
pub enum Arm {
    A0 = 0,
    A1 = 1,
    A2 = 2,
    A3 = 3,
    A4Adamw = 4,
}

impl Arm {
    pub const fn label(self) -> &'static str {
        match self {
            Self::A0 => "A0",
            Self::A1 => "A1",
            Self::A2 => "A2",
            Self::A3 => "A3",
            Self::A4Adamw => "A4-AdamW",
        }
    }

    pub const fn magnitudes(self) -> &'static [f32] {
        match self {
            Self::A0 => A0_MAGNITUDES,
            Self::A1 => A1_MAGNITUDES,
            Self::A2 => A2_MAGNITUDES,
            Self::A3 => A3_MAGNITUDES,
            Self::A4Adamw => &[],
        }
    }

    pub const fn all() -> [Self; 5] {
        [Self::A0, Self::A1, Self::A2, Self::A3, Self::A4Adamw]
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct ActionTelemetry {
    pub selected: u64,
    pub no_op: u64,
    pub blocked: u64,
    pub selected_positive: u64,
    pub selected_negative: u64,
    pub sign_reversals: u64,
    pub both_sign_available: u64,
    pub one_sign_available: u64,
    pub no_legal_move: u64,
    pub min_selected_magnitude: f32,
    pub selected_by_level: [u64; MAX_ACTION_LEVELS],
}

impl ActionTelemetry {
    fn absorb(&mut self, step: Self) {
        self.selected += step.selected;
        self.no_op += step.no_op;
        self.blocked += step.blocked;
        self.selected_positive += step.selected_positive;
        self.selected_negative += step.selected_negative;
        self.sign_reversals += step.sign_reversals;
        self.both_sign_available += step.both_sign_available;
        self.one_sign_available += step.one_sign_available;
        self.no_legal_move += step.no_legal_move;
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
    pub sign_reversals: u64,
    pub both_sign_available: u64,
    pub one_sign_available: u64,
    pub no_legal_move: u64,
}

#[derive(Clone, Debug)]
pub struct GranularityResult {
    pub arm: Arm,
    pub epochs: usize,
    pub final_loss: f32,
    pub final_accuracy: f32,
    pub final_mse: f32,
    pub final_probabilities: [f32; 4],
    pub final_logits: [f32; 4],
    pub final_margins: [f32; 4],
    pub telemetry: ActionTelemetry,
    pub curve: Vec<CurvePoint>,
}

pub struct DiscreteRuntime {
    magnitudes: &'static [f32],
    last_sign: [i8; PARAMS],
    pub telemetry: ActionTelemetry,
}

impl DiscreteRuntime {
    pub const fn new(arm: Arm) -> Self {
        Self {
            magnitudes: arm.magnitudes(),
            last_sign: [0; PARAMS],
            telemetry: ActionTelemetry {
                selected: 0,
                no_op: 0,
                blocked: 0,
                selected_positive: 0,
                selected_negative: 0,
                sign_reversals: 0,
                both_sign_available: 0,
                one_sign_available: 0,
                no_legal_move: 0,
                min_selected_magnitude: 0.0,
                selected_by_level: [0; MAX_ACTION_LEVELS],
            },
        }
    }

    pub fn apply(&mut self, model: &mut Model, gradient: &[f32; PARAMS]) -> ActionTelemetry {
        let previous = model.parameters;
        let mut step = ActionTelemetry {
            min_selected_magnitude: 0.0,
            ..ActionTelemetry::default()
        };
        for (index, &gradient_value) in gradient.iter().enumerate() {
            let current = previous[index];
            let mut best_delta = 0.0;
            let mut best_utility = 0.0;
            let mut best_level = 0;
            let mut positive_available = false;
            let mut negative_available = false;
            for (level, &magnitude) in self.magnitudes.iter().enumerate() {
                for delta in [-magnitude, magnitude] {
                    let candidate = current + delta;
                    if !(LOWER_BOUND..=UPPER_BOUND).contains(&candidate) {
                        step.blocked += 1;
                        continue;
                    }
                    if delta.is_sign_positive() {
                        positive_available = true;
                    } else {
                        negative_available = true;
                    }
                    let utility = -gradient_value * delta;
                    if utility > best_utility {
                        best_utility = utility;
                        best_delta = delta;
                        best_level = level;
                    }
                }
            }
            match (positive_available, negative_available) {
                (true, true) => step.both_sign_available += 1,
                (true, false) | (false, true) => step.one_sign_available += 1,
                (false, false) => step.no_legal_move += 1,
            }
            if best_delta == 0.0 {
                step.no_op += 1;
                continue;
            }
            model.parameters[index] = current + best_delta;
            step.selected += 1;
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
        self.telemetry.absorb(step);
        step
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

pub fn run_discrete(samples: &[Sample], arm: Arm) -> GranularityResult {
    assert!(matches!(arm, Arm::A0 | Arm::A1 | Arm::A2 | Arm::A3));
    let mut model = Model::initial();
    let mut runtime = DiscreteRuntime::new(arm);
    let mut curve = Vec::with_capacity(EPOCHS);
    for epoch in 0..EPOCHS {
        let (loss_before, gradient) = model.loss_and_gradient(samples);
        let step = runtime.apply(&mut model, &gradient);
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
            sign_reversals: step.sign_reversals,
            both_sign_available: step.both_sign_available,
            one_sign_available: step.one_sign_available,
            no_legal_move: step.no_legal_move,
        });
    }
    let (final_loss, _) = model.loss_and_gradient(samples);
    let (final_probabilities, final_logits, final_margins) = final_metrics(&model, samples);
    GranularityResult {
        arm,
        epochs: EPOCHS,
        final_loss,
        final_accuracy: model.accuracy(samples),
        final_mse: model.simd_mean_squared_error(samples),
        final_probabilities,
        final_logits,
        final_margins,
        telemetry: runtime.telemetry,
        curve,
    }
}

pub fn run_adamw(samples: &[Sample]) -> GranularityResult {
    let mut model = Model::initial();
    let mut optimizer = AdamW::new(0.03);
    let mut curve = Vec::with_capacity(EPOCHS);
    for epoch in 0..EPOCHS {
        let (loss_before, gradient) = model.loss_and_gradient(samples);
        optimizer.step(&mut model, &gradient);
        let (loss_after, _) = model.loss_and_gradient(samples);
        curve.push(CurvePoint {
            epoch,
            loss_before,
            loss_after,
            accuracy_after: model.accuracy(samples),
            ..CurvePoint::default()
        });
    }
    let (final_loss, _) = model.loss_and_gradient(samples);
    let (final_probabilities, final_logits, final_margins) = final_metrics(&model, samples);
    GranularityResult {
        arm: Arm::A4Adamw,
        epochs: EPOCHS,
        final_loss,
        final_accuracy: model.accuracy(samples),
        final_mse: model.simd_mean_squared_error(samples),
        final_probabilities,
        final_logits,
        final_margins,
        telemetry: ActionTelemetry::default(),
        curve,
    }
}

pub fn run_all(samples: &[Sample]) -> [GranularityResult; 5] {
    [
        run_discrete(samples, Arm::A0),
        run_discrete(samples, Arm::A1),
        run_discrete(samples, Arm::A2),
        run_discrete(samples, Arm::A3),
        run_adamw(samples),
    ]
}

pub fn ar00_parity(samples: &[Sample]) -> (Ar00Result, GranularityResult) {
    (
        adaptive_runtime_ar_00::run_interposed(samples, EPOCHS),
        run_discrete(samples, Arm::A0),
    )
}

pub fn xor_samples_for_tests() -> [Sample; 4] {
    xor_samples()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a0_matches_frozen_ar00() {
        let samples = xor_samples();
        let (legacy, a0) = ar00_parity(&samples);
        assert!((legacy.final_loss - a0.final_loss).abs() < 1e-7);
        assert_eq!(legacy.final_accuracy, a0.final_accuracy);
        assert_eq!(legacy.action_stats.selected, a0.telemetry.selected);
        assert_eq!(legacy.action_stats.no_op, a0.telemetry.no_op);
        assert_eq!(legacy.action_stats.blocked, a0.telemetry.blocked);
    }

    #[test]
    fn finer_vocabularies_reach_xor_and_select_small_steps() {
        let samples = xor_samples();
        for arm in [Arm::A1, Arm::A2, Arm::A3] {
            let result = run_discrete(&samples, arm);
            assert_eq!(result.final_accuracy, 1.0);
            assert!(result.telemetry.selected > 0);
            assert!(result.telemetry.min_selected_magnitude < ACTION_STEP);
        }
    }

    #[test]
    fn every_curve_has_one_point_per_update() {
        let result = run_discrete(&xor_samples(), Arm::A3);
        assert_eq!(result.curve.len(), EPOCHS);
        assert_eq!(result.curve[0].epoch, 0);
        assert_eq!(result.curve[EPOCHS - 1].epoch, EPOCHS - 1);
    }
}
