use adaptive_runtime_ar_00::{Model, PARAMS, RunResult, Sample, xor_samples};

pub const EPOCHS: usize = 3_000;
pub const ACTION_STEP: f32 = 0.02;
pub const LOWER_BOUND: f32 = -3.0;
pub const UPPER_BOUND: f32 = 3.0;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct SignStats {
    pub selected: u64,
    pub no_op: u64,
    pub blocked: u64,
    pub positive: u64,
    pub negative: u64,
}

pub struct SignRuntime {
    pub stats: SignStats,
}

impl Default for SignRuntime {
    fn default() -> Self {
        Self::new()
    }
}

impl SignRuntime {
    pub const fn new() -> Self {
        Self {
            stats: SignStats {
                selected: 0,
                no_op: 0,
                blocked: 0,
                positive: 0,
                negative: 0,
            },
        }
    }

    pub fn apply(&mut self, model: &mut Model, gradient: &[f32; PARAMS]) {
        let previous = model.parameters;
        for (index, &gradient_value) in gradient.iter().enumerate() {
            let delta = if gradient_value > 0.0 {
                -ACTION_STEP
            } else if gradient_value < 0.0 {
                ACTION_STEP
            } else {
                0.0
            };
            if delta == 0.0 {
                self.stats.no_op += 1;
                continue;
            }
            let candidate = previous[index] + delta;
            if !(LOWER_BOUND..=UPPER_BOUND).contains(&candidate) {
                self.stats.blocked += 1;
                continue;
            }
            model.parameters[index] = candidate;
            self.stats.selected += 1;
            if delta > 0.0 {
                self.stats.positive += 1;
            } else {
                self.stats.negative += 1;
            }
        }
    }
}

pub fn run_sign_only(samples: &[Sample]) -> RunResult {
    let mut model = Model::initial();
    let mut runtime = SignRuntime::new();
    for _ in 0..EPOCHS {
        let (_, gradient) = model.loss_and_gradient(samples);
        runtime.apply(&mut model, &gradient);
    }
    let (final_loss, _) = model.loss_and_gradient(samples);
    RunResult {
        epochs: EPOCHS,
        final_loss,
        final_accuracy: model.accuracy(samples),
        final_mse: model.simd_mean_squared_error(samples),
        action_stats: adaptive_runtime_ar_00::ActionStats {
            selected: runtime.stats.selected,
            no_op: runtime.stats.no_op,
            blocked: runtime.stats.blocked,
        },
    }
}

pub fn xor_samples_for_tests() -> [Sample; 4] {
    xor_samples()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sign_only_matches_ar00_final_state_metrics() {
        let samples = xor_samples();
        let ar00 = adaptive_runtime_ar_00::run_interposed(&samples, EPOCHS);
        let sign_only = run_sign_only(&samples);
        assert!((ar00.final_loss - sign_only.final_loss).abs() < 1e-7);
        assert_eq!(ar00.final_accuracy, sign_only.final_accuracy);
        assert_eq!(ar00.final_mse, sign_only.final_mse);
        assert_eq!(ar00.action_stats.selected, sign_only.action_stats.selected);
        // The final parameter transition is equivalent. Telemetry differs at
        // bounds: AR-00 records a blocked preferred move as a no-op after
        // ranking both candidates; sign-only records it only as blocked.
        assert_ne!(ar00.action_stats.no_op, sign_only.action_stats.no_op);
    }

    #[test]
    fn sign_only_learns_xor() {
        let result = run_sign_only(&xor_samples());
        assert_eq!(result.final_accuracy, 1.0);
        assert!(result.action_stats.selected > 0);
    }
}
