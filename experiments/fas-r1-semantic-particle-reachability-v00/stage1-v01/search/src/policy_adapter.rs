//! Composition of independently frozen proposal/value and terminal-selector heads.

use crate::{
    Edit, FrozenProposalValueV01, InferenceError, PolicyCosts, PolicyError, PolicyLatentUpdate,
    PolicyScores, PolicyValue, SearchPolicy, SelectorInput, TransitionInput, ValueInput,
};

/// Terminal recognition is a separate interface so planner heads cannot leak
/// latent state or remaining budget into final assignment selection.
pub trait TerminalScorer {
    fn q_terminal(&mut self, input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError>;
}

/// Frozen v01 planner heads paired with an explicit common terminal scorer.
pub struct FrozenProposalPolicyV01<Q> {
    heads: FrozenProposalValueV01,
    terminal: Q,
}

impl<Q> FrozenProposalPolicyV01<Q> {
    pub fn new(heads: FrozenProposalValueV01, terminal: Q) -> Self {
        Self { heads, terminal }
    }

    pub fn heads(&self) -> &FrozenProposalValueV01 {
        &self.heads
    }

    pub fn terminal(&self) -> &Q {
        &self.terminal
    }

    pub fn terminal_mut(&mut self) -> &mut Q {
        &mut self.terminal
    }
}

impl<Q: TerminalScorer> SearchPolicy for FrozenProposalPolicyV01<Q> {
    fn score_edits(
        &mut self,
        input: TransitionInput<'_>,
        candidates: &[Edit],
    ) -> Result<PolicyScores, PolicyError> {
        let logits = self
            .heads
            .score_edits(input.task, input.features, input.assignment, candidates)
            .map_err(inference_error)?;
        Ok(PolicyScores {
            logits,
            costs: PolicyCosts {
                logits_scored: candidates.len() as u64,
                ..PolicyCosts::default()
            },
        })
    }

    fn advance_latent(
        &mut self,
        input: TransitionInput<'_>,
        selected: Edit,
    ) -> Result<PolicyLatentUpdate, PolicyError> {
        Ok(PolicyLatentUpdate {
            next_state: FrozenProposalValueV01::advance_latent_v01(
                input.latent_state,
                selected.entity,
                selected.new_role,
            ),
            costs: PolicyCosts::default(),
        })
    }

    fn q_terminal(&mut self, input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError> {
        self.terminal.q_terminal(input)
    }

    fn v_reach(&mut self, input: ValueInput<'_>) -> Result<PolicyValue, PolicyError> {
        let probability = self
            .heads
            .v_reach(
                input.task,
                input.features,
                input.assignment,
                input.latent_state,
                input.remaining_budget,
            )
            .map_err(inference_error)?;
        Ok(PolicyValue {
            value: probability,
            selection_score: None,
            costs: PolicyCosts::default(),
        })
    }
}

fn inference_error(error: InferenceError) -> PolicyError {
    PolicyError(error.to_string())
}
