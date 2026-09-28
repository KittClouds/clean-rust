//! Stage 1 SearchPolicy adapter for the frozen v02 proposal and V_reach heads.
//!
//! The v03 identity model supplies the raw six-class action feature used by
//! proposal-v02. A separate `TerminalScorer` remains the common final judge.

use crate::{
    Edit, FrozenProposalValueV02, IdentityCompositionV03, PolicyCosts, PolicyError,
    PolicyLatentUpdate, PolicyScores, PolicyValue, ProposalMixV03, SearchPolicy, SelectorInput,
    SemanticFeatures, TerminalScorer, TransitionInput, ValueInput,
};
use hashbrown::HashMap;
use r1_world::InferenceTask;
use serde::Serialize;

#[derive(Clone, Debug, Default, Serialize)]
pub struct ProposalScoreAuditV03 {
    pub score_calls: u64,
    pub candidate_scores: u64,
    pub base_spread_sum: f64,
    pub action_delta_spread_sum: f64,
    pub adapter_spread_sum: f64,
    pub adapter_to_base_spread_sum: f64,
    pub top1_changed_calls: u64,
}

impl ProposalScoreAuditV03 {
    fn observe(&mut self, scores: &crate::ProposalScoresV02, deltas: &[f32]) {
        let base_spread = standard_deviation(&scores.base_logits);
        let delta_spread = standard_deviation(deltas);
        let adapter_spread = standard_deviation(&scores.adapter_adjustments);
        self.score_calls += 1;
        self.candidate_scores += scores.logits.len() as u64;
        self.base_spread_sum += f64::from(base_spread);
        self.action_delta_spread_sum += f64::from(delta_spread);
        self.adapter_spread_sum += f64::from(adapter_spread);
        self.adapter_to_base_spread_sum += f64::from(if base_spread > 1e-8 {
            adapter_spread / base_spread
        } else {
            0.0
        });
        if argmax(&scores.base_logits) != argmax(&scores.logits) {
            self.top1_changed_calls += 1;
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct PreparedKey {
    global_ptr: usize,
    clauses_ptr: usize,
    entity_incidence_ptr: usize,
    role_incidence_ptr: usize,
    constraint_mask_ptr: usize,
    entity_mask_ptr: usize,
    role_mask_ptr: usize,
    hidden_dim: usize,
    clauses: usize,
    entities: usize,
    roles: usize,
    task_entities: u16,
    task_roles: u8,
}

/// Frozen v02 planner paired with the pinned v03 action identity source and a
/// separately supplied common terminal selector.
pub struct FrozenProposalPolicyV02<'identity, Q> {
    heads: FrozenProposalValueV02,
    identity: &'identity mut IdentityCompositionV03,
    terminal: Q,
    prepared: HashMap<String, PreparedKey>,
    proposal_mix: ProposalMixV03,
    score_audit: ProposalScoreAuditV03,
}

impl<'identity, Q> FrozenProposalPolicyV02<'identity, Q> {
    pub fn new(
        heads: FrozenProposalValueV02,
        identity: &'identity mut IdentityCompositionV03,
        terminal: Q,
    ) -> Self {
        Self {
            heads,
            identity,
            terminal,
            prepared: HashMap::new(),
            proposal_mix: ProposalMixV03::PinnedRawV02,
            score_audit: ProposalScoreAuditV03::default(),
        }
    }

    pub fn set_proposal_mix(&mut self, mix: ProposalMixV03) {
        self.proposal_mix = mix;
    }

    pub fn reset_score_audit(&mut self) {
        self.score_audit = ProposalScoreAuditV03::default();
    }

    pub fn score_audit(&self) -> &ProposalScoreAuditV03 {
        &self.score_audit
    }

    pub fn heads(&self) -> &FrozenProposalValueV02 {
        &self.heads
    }

    pub fn identity(&self) -> &IdentityCompositionV03 {
        self.identity
    }

    pub fn identity_mut(&mut self) -> &mut IdentityCompositionV03 {
        self.identity
    }

    pub fn terminal(&self) -> &Q {
        &self.terminal
    }

    pub fn terminal_mut(&mut self) -> &mut Q {
        &mut self.terminal
    }

    /// Prepare using the identity source already bound by `new`. This avoids
    /// borrowing the mutable identity through the same policy value at call
    /// sites that want explicit prewarming before multiple arms.
    pub fn prepare_bound_task(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
    ) -> Result<(), PolicyError> {
        let key = prepared_key(task, features);
        if self.prepared.get(&task.id).copied() != Some(key) {
            self.identity
                .prepare_task(&task.id, features)
                .map_err(|error| PolicyError(error.to_string()))?;
            self.heads
                .prepare_task(task, features)
                .map_err(inference_error)?;
            self.prepared.insert(task.id.clone(), key);
        }
        Ok(())
    }

    fn ensure_prepared(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
    ) -> Result<(), PolicyError> {
        self.prepare_bound_task(task, features)
    }
}

impl<Q: TerminalScorer> SearchPolicy for FrozenProposalPolicyV02<'_, Q> {
    fn score_edits(
        &mut self,
        input: TransitionInput<'_>,
        candidates: &[Edit],
    ) -> Result<PolicyScores, PolicyError> {
        self.ensure_prepared(input.task, input.features)?;
        let uses_action_signal = self.proposal_mix.uses_action_signal();
        let action_batch = if uses_action_signal {
            Some(
                self.identity
                    .expected_satisfaction_deltas_for_task(
                        &input.task.id,
                        input.features,
                        input.assignment,
                        candidates,
                        self.proposal_mix.uses_incidence_masked_signal(),
                    )
                    .map_err(|error| PolicyError(error.to_string()))?,
            )
        } else {
            None
        };
        let expected_delta = candidates
            .iter()
            .enumerate()
            .map(|(index, _)| {
                let delta = action_batch
                    .as_ref()
                    .map_or(0.0, |batch| batch.deltas[index]) as f32;
                if delta.is_finite() {
                    Ok(delta)
                } else {
                    Err(PolicyError(
                        "v03 action expected-delta is non-finite after float32 conversion".into(),
                    ))
                }
            })
            .collect::<Result<Vec<_>, _>>()?;
        let mut action_identity_logits = 0u64;
        if uses_action_signal {
            for &affected_clauses in &action_batch
                .as_ref()
                .expect("action signals have an action batch")
                .affected_clause_counts
            {
                action_identity_logits = action_identity_logits
                    .saturating_add(u64::from(affected_clauses).saturating_mul(6));
            }
        }
        let scores = self
            .heads
            .score_edits_detailed_with_mix(
                input.task,
                input.features,
                input.assignment,
                candidates,
                &expected_delta,
                self.proposal_mix,
            )
            .map_err(inference_error)?;
        self.score_audit.observe(&scores, &expected_delta);
        Ok(PolicyScores {
            logits: scores.logits,
            costs: PolicyCosts {
                logits_scored: (candidates.len() as u64).saturating_add(action_identity_logits),
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
            next_state: advance_latent_v01(input.latent_state, selected.entity, selected.new_role),
            costs: PolicyCosts::default(),
        })
    }

    fn q_terminal(&mut self, input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError> {
        self.terminal.q_terminal(input)
    }

    fn v_reach(&mut self, input: ValueInput<'_>) -> Result<PolicyValue, PolicyError> {
        self.ensure_prepared(input.task, input.features)?;
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

fn standard_deviation(values: &[f32]) -> f32 {
    if values.is_empty() {
        return 0.0;
    }
    let mean = values.iter().map(|value| f64::from(*value)).sum::<f64>() / values.len() as f64;
    let variance = values
        .iter()
        .map(|value| {
            let difference = f64::from(*value) - mean;
            difference * difference
        })
        .sum::<f64>()
        / values.len() as f64;
    variance.sqrt() as f32
}

fn argmax(values: &[f32]) -> Option<usize> {
    let mut best = None;
    for (index, value) in values.iter().enumerate() {
        if best.is_none_or(|current| value.total_cmp(&values[current]).is_gt()) {
            best = Some(index);
        }
    }
    best
}

fn prepared_key(task: &InferenceTask, features: &SemanticFeatures) -> PreparedKey {
    PreparedKey {
        global_ptr: features.global_embedding.as_ptr() as usize,
        clauses_ptr: features.constraint_embeddings.as_ptr() as usize,
        entity_incidence_ptr: features.entity_incidence.as_ptr() as usize,
        role_incidence_ptr: features.role_incidence.as_ptr() as usize,
        constraint_mask_ptr: features.constraint_mask.as_ptr() as usize,
        entity_mask_ptr: features.entity_mask.as_ptr() as usize,
        role_mask_ptr: features.role_mask.as_ptr() as usize,
        hidden_dim: features.hidden_dim,
        clauses: features.constraint_count,
        entities: features.entity_count,
        roles: features.role_count,
        task_entities: task.n,
        task_roles: task.k,
    }
}

fn advance_latent_v01(latent: &[f32], entity: u16, new_role: u8) -> Vec<f32> {
    let mut next = latent.to_vec();
    if next.is_empty() {
        return next;
    }
    let index = usize::from(entity) % next.len();
    let role_index = (usize::from(new_role) * 31 + index + 1) % next.len();
    next[index] = (0.875 * next[index] + 0.125 * (f32::from(new_role) - 0.5)).tanh();
    next[role_index] = (0.9 * next[role_index] + 0.1 * (f32::from(entity) + 1.0)).tanh();
    next
}

fn inference_error(error: crate::InferenceV02Error) -> PolicyError {
    PolicyError(error.to_string())
}
