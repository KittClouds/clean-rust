//! Proposal-only composition for the frozen V05 Q-terminal ΔC scorer.

use crate::{
    Edit, FrozenQTerminalDeltaV05, PolicyCosts, PolicyError, PolicyLatentUpdate, PolicyScores,
    PolicyValue, SearchPolicy, SelectorInput, TransitionInput, ValueInput,
};

/// Replaces proposal logits with β·ΔC while preserving the wrapped latent,
/// terminal-selector, and continuation-value behavior.
pub struct QDeltaProposalPolicy<P> {
    inner: P,
    scorer: Option<FrozenQTerminalDeltaV05>,
    beta: f32,
}

impl<P> QDeltaProposalPolicy<P> {
    pub fn new(inner: P, scorer: FrozenQTerminalDeltaV05, beta: f64) -> Result<Self, PolicyError> {
        if !beta.is_finite() || beta <= 0.0 || !(beta as f32).is_finite() {
            return Err(PolicyError(
                "Q-delta proposal beta must be finite and positive".to_owned(),
            ));
        }
        Ok(Self {
            inner,
            scorer: Some(scorer),
            beta: beta as f32,
        })
    }

    /// Preserve the original policy unchanged when no Q-delta override is configured.
    pub fn baseline(inner: P) -> Self {
        Self {
            inner,
            scorer: None,
            beta: 1.0,
        }
    }

    pub fn beta(&self) -> f32 {
        self.beta
    }

    pub fn inner(&self) -> &P {
        &self.inner
    }

    pub fn inner_mut(&mut self) -> &mut P {
        &mut self.inner
    }

    pub fn scorer(&self) -> &FrozenQTerminalDeltaV05 {
        self.scorer
            .as_ref()
            .expect("Q-delta scorer requested from baseline policy")
    }

    pub fn has_qdelta(&self) -> bool {
        self.scorer.is_some()
    }

    pub fn qdelta_beta(&self) -> Option<f32> {
        self.scorer.as_ref().map(|_| self.beta)
    }

    pub fn prepare_qdelta_task(
        &mut self,
        task: &r1_world::InferenceTask,
        features: &crate::SemanticFeatures,
    ) -> Result<(), PolicyError> {
        if let Some(scorer) = &mut self.scorer {
            scorer
                .prepare_task(task, features)
                .map_err(|error| PolicyError(error.to_string()))?;
        }
        Ok(())
    }
}

impl<P: SearchPolicy> SearchPolicy for QDeltaProposalPolicy<P> {
    fn score_edits(
        &mut self,
        input: TransitionInput<'_>,
        candidates: &[Edit],
    ) -> Result<PolicyScores, PolicyError> {
        let Some(scorer) = &mut self.scorer else {
            return self.inner.score_edits(input, candidates);
        };
        let batch = scorer
            .score_deltas_with_costs(input.task, input.features, input.assignment, candidates)
            .map_err(|error| PolicyError(error.to_string()))?;
        let logits = batch
            .deltas
            .into_iter()
            .map(|delta| delta * self.beta)
            .collect::<Vec<_>>();
        if logits.iter().any(|logit| !logit.is_finite()) {
            return Err(PolicyError(
                "Q-delta proposal produced a non-finite logit".to_owned(),
            ));
        }
        Ok(PolicyScores {
            logits,
            costs: PolicyCosts {
                logits_scored: batch.clause_logits_scored,
                ..PolicyCosts::default()
            },
        })
    }

    fn advance_latent(
        &mut self,
        input: TransitionInput<'_>,
        selected: Edit,
    ) -> Result<PolicyLatentUpdate, PolicyError> {
        self.inner.advance_latent(input, selected)
    }

    fn q_terminal(&mut self, input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError> {
        self.inner.q_terminal(input)
    }

    fn v_reach(&mut self, input: ValueInput<'_>) -> Result<PolicyValue, PolicyError> {
        self.inner.v_reach(input)
    }
}
