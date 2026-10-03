use crate::SemanticFeatures;
use r1_world::InferenceTask;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Edit {
    pub entity: u16,
    pub new_role: u8,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProposalStrategy {
    Greedy,
    LearnedSample,
    UniformSample,
}

/// Proposal surface includes semantic features, public task, state, latent
/// state, and remaining compute.
pub struct TransitionInput<'a> {
    pub features: &'a SemanticFeatures,
    pub task: &'a InferenceTask,
    pub assignment: &'a [u8],
    pub latent_state: &'a [f32],
    pub remaining_budget: u64,
    pub strategy: ProposalStrategy,
}

/// Strict terminal-selector surface: frozen (H,h_global) and assignment only.
/// Latent state and budget are absent by type. Implementations return the
/// calibrated validity probability, applying sigmoid/calibration in an
/// artifact adapter when the checkpoint emits logits.
pub struct SelectorInput<'a> {
    pub task_id: &'a str,
    pub features: &'a SemanticFeatures,
    pub assignment: &'a [u8],
}

/// Reachability value may use the latent computational state and remaining
/// budget; it is never used to choose the final assignment.
pub struct ValueInput<'a> {
    pub features: &'a SemanticFeatures,
    pub task: &'a InferenceTask,
    pub assignment: &'a [u8],
    pub latent_state: &'a [f32],
    pub remaining_budget: u64,
    pub depth: u32,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct PolicyCosts {
    pub logits_scored: u64,
    pub encoder_forward_calls: u64,
    pub encoder_tokens: u64,
    pub gpu_active_ns: u64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PolicyScores {
    /// One logit per candidate in the order supplied to score_edits.
    pub logits: Vec<f32>,
    pub costs: PolicyCosts,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PolicyLatentUpdate {
    /// Recurrent state after applying the selected edit.
    pub next_state: Vec<f32>,
    pub costs: PolicyCosts,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct PolicyValue {
    /// Q_terminal returns calibrated P(valid); V_reach returns a continuation
    /// probability under the frozen proposal policy.
    pub value: f32,
    /// Optional ordering signal for terminal selection. Q may use the raw
    /// factorized semantic log score while `value` retains calibrated
    /// confidence. Negative infinity is allowed internally and is normalized
    /// before artifact serialization.
    pub selection_score: Option<f64>,
    pub costs: PolicyCosts,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicyError(pub String);

impl std::fmt::Display for PolicyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for PolicyError {}

/// Deterministic SplitMix64 stream, with state recorded per transition.
#[derive(Clone, Copy, Debug)]
pub struct DeterministicRng {
    pub state: u64,
}

impl DeterministicRng {
    pub fn new(state: u64) -> Self {
        Self { state }
    }

    pub fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        value ^ (value >> 31)
    }

    pub fn bounded(&mut self, bound: u64) -> u64 {
        assert!(bound > 0, "bounded RNG requires a nonzero bound");
        let threshold = bound.wrapping_neg() % bound;
        loop {
            let value = self.next_u64();
            if value >= threshold {
                return value % bound;
            }
        }
    }

    fn unit_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / ((1u64 << 53) as f64))
    }
}

/// Shared callbacks across the actual arm set. Uniform-width skips learned
/// logits and latent updates; every arm uses the same Q selector, while only
/// PARTICLE evaluates V_reach for allocation.
pub trait SearchPolicy {
    fn score_edits(
        &mut self,
        input: TransitionInput<'_>,
        candidates: &[Edit],
    ) -> Result<PolicyScores, PolicyError>;

    /// Advance latent control state only after the scheduler has sampled an
    /// edit. This preserves the proposal rollout contract: s' may depend on
    /// the selected action, not merely on the candidate set.
    fn advance_latent(
        &mut self,
        input: TransitionInput<'_>,
        selected: Edit,
    ) -> Result<PolicyLatentUpdate, PolicyError>;

    /// Common final selector. Must depend only on SelectorInput.
    fn q_terminal(&mut self, input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError>;

    /// Continuation value for particle allocation; never used for final choice.
    fn v_reach(&mut self, input: ValueInput<'_>) -> Result<PolicyValue, PolicyError>;
}

pub(crate) fn sample_action(
    strategy: ProposalStrategy,
    logits: &[f32],
    learned_sample_temperature: f64,
    rng: &mut DeterministicRng,
) -> Result<(usize, f32), PolicyError> {
    if logits.is_empty() {
        return Err(PolicyError("proposal has no legal candidates".to_owned()));
    }
    match strategy {
        ProposalStrategy::Greedy => {
            let mut best = 0usize;
            for index in 1..logits.len() {
                if logits[index].total_cmp(&logits[best]).is_gt() {
                    best = index;
                }
            }
            Ok((best, 0.0))
        }
        ProposalStrategy::UniformSample => {
            let selected = rng.bounded(logits.len() as u64) as usize;
            Ok((selected, -(logits.len() as f32).ln()))
        }
        ProposalStrategy::LearnedSample => {
            if logits.iter().any(|value| !value.is_finite()) {
                return Err(PolicyError("proposal logits must be finite".to_owned()));
            }
            if !learned_sample_temperature.is_finite() || learned_sample_temperature <= 0.0 {
                return Err(PolicyError(
                    "learned-sample temperature must be finite and positive".to_owned(),
                ));
            }
            // Keep the frozen temperature-1 path bit-for-bit compatible with
            // its former f32 subtraction followed by f64 accumulation. Other
            // temperatures scale logits in f64 after reading the untouched
            // f32 model outputs.
            let legacy_max = (learned_sample_temperature == 1.0)
                .then(|| logits.iter().copied().fold(f32::NEG_INFINITY, f32::max));
            let raw_max = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
            let max = f64::from(raw_max);
            let weight = |value: f32| {
                if let Some(legacy_max) = legacy_max {
                    f64::from((value - legacy_max).exp())
                } else {
                    ((f64::from(value) - max) / learned_sample_temperature).exp()
                }
            };
            let total = logits.iter().map(|value| weight(*value)).sum::<f64>();
            if !total.is_finite() || total <= 0.0 {
                return Err(PolicyError(
                    "proposal softmax is not normalizable".to_owned(),
                ));
            }
            let draw = rng.unit_f64() * total;
            let mut cumulative = 0.0;
            let mut selected = logits.len() - 1;
            for (index, value) in logits.iter().enumerate() {
                cumulative += weight(*value);
                if draw < cumulative {
                    selected = index;
                    break;
                }
            }
            let probability = (weight(logits[selected]) / total) as f32;
            Ok((selected, probability.ln()))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{sample_action, DeterministicRng, ProposalStrategy};

    #[test]
    fn greedy_ignores_learned_sampling_temperature() {
        let logits = [0.0, 1.0, -2.0];
        let mut cold_rng = DeterministicRng::new(19);
        let mut hot_rng = DeterministicRng::new(19);
        assert_eq!(
            sample_action(ProposalStrategy::Greedy, &logits, 1.0, &mut cold_rng).unwrap(),
            sample_action(ProposalStrategy::Greedy, &logits, 0.2, &mut hot_rng).unwrap()
        );
        assert_eq!(cold_rng.state, hot_rng.state);
    }

    #[test]
    fn lower_temperature_concentrates_learned_samples_on_high_logit() {
        let logits = [0.0, 1.0];
        let mut ordinary_rng = DeterministicRng::new(0xA11C_E5EED);
        let mut cold_rng = DeterministicRng::new(0xA11C_E5EED);
        let mut ordinary_top = 0;
        let mut cold_top = 0;
        for _ in 0..4096 {
            ordinary_top += usize::from(
                sample_action(
                    ProposalStrategy::LearnedSample,
                    &logits,
                    1.0,
                    &mut ordinary_rng,
                )
                .unwrap()
                .0 == 1,
            );
            cold_top += usize::from(
                sample_action(ProposalStrategy::LearnedSample, &logits, 0.5, &mut cold_rng)
                    .unwrap()
                    .0
                    == 1,
            );
        }
        assert!(cold_top > ordinary_top + 500);
    }

    #[test]
    fn learned_sampler_rejects_nonpositive_or_nonfinite_temperature() {
        for temperature in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            let error = sample_action(
                ProposalStrategy::LearnedSample,
                &[0.0, 1.0],
                temperature,
                &mut DeterministicRng::new(7),
            )
            .unwrap_err();
            assert!(error.0.contains("finite and positive"));
        }
    }

    #[test]
    fn learned_sampler_handles_the_smallest_positive_temperature() {
        let (choice, log_probability) = sample_action(
            ProposalStrategy::LearnedSample,
            &[0.0, 1.0],
            f64::from_bits(1),
            &mut DeterministicRng::new(7),
        )
        .unwrap();
        assert_eq!(choice, 1);
        assert_eq!(log_probability, 0.0);
    }

    #[test]
    fn temperature_one_matches_the_legacy_sampler_exactly() {
        fn legacy(logits: &[f32], rng: &mut DeterministicRng) -> (usize, f32) {
            let max = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
            let weights = logits
                .iter()
                .map(|value| f64::from((*value - max).exp()))
                .collect::<Vec<_>>();
            let total = weights.iter().sum::<f64>();
            let draw = rng.unit_f64() * total;
            let mut cumulative = 0.0;
            let mut selected = weights.len() - 1;
            for (index, weight) in weights.iter().enumerate() {
                cumulative += *weight;
                if draw < cumulative {
                    selected = index;
                    break;
                }
            }
            let probability = (weights[selected] / total) as f32;
            (selected, probability.ln())
        }

        let logits = [0.125, -1.75, 0.875, 0.0, -2.5];
        let mut actual_rng = DeterministicRng::new(0x007E_571E);
        let mut legacy_rng = DeterministicRng::new(0x007E_571E);
        for _ in 0..1024 {
            let actual = sample_action(
                ProposalStrategy::LearnedSample,
                &logits,
                1.0,
                &mut actual_rng,
            )
            .unwrap();
            let expected = legacy(&logits, &mut legacy_rng);
            assert_eq!(actual.0, expected.0);
            assert_eq!(actual.1.to_bits(), expected.1.to_bits());
            assert_eq!(actual_rng.state, legacy_rng.state);
        }
    }

    #[test]
    fn uniform_sampling_ignores_learned_temperature() {
        let logits = [0.0, 1.0, -2.0];
        let mut default_rng = DeterministicRng::new(73);
        let mut changed_rng = DeterministicRng::new(73);
        for _ in 0..128 {
            assert_eq!(
                sample_action(
                    ProposalStrategy::UniformSample,
                    &logits,
                    1.0,
                    &mut default_rng
                )
                .unwrap(),
                sample_action(
                    ProposalStrategy::UniformSample,
                    &logits,
                    0.17,
                    &mut changed_rng
                )
                .unwrap()
            );
        }
        assert_eq!(default_rng.state, changed_rng.state);
    }
}
