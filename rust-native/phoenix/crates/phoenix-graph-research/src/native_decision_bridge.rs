use compact_str::CompactString;
use hashbrown::HashMap;
use phoenix_types::{
    resolve_complete_native_decision_outcomes, NativeDecisionCounterfactualRole,
    NativeDecisionOutcomeReceipt, NativeDecisionReceipt,
};

use crate::{
    freeze_counterfactual_candidate_groups, CounterfactualCandidateGroupInput,
    CounterfactualCandidateGroupsError, CounterfactualCandidateOutcome,
    CounterfactualCandidateRole, FrozenCounterfactualCandidateGroups,
    FrozenDecisionTrajectoryTables,
};

pub fn freeze_counterfactual_groups_from_native_receipts(
    source_trajectory_id: CompactString,
    source: &FrozenDecisionTrajectoryTables,
    frozen_at: i64,
    decisions: &[NativeDecisionReceipt],
    outcomes: &[NativeDecisionOutcomeReceipt],
) -> Result<FrozenCounterfactualCandidateGroups, CounterfactualCandidateGroupsError> {
    let inputs =
        counterfactual_inputs_from_native_receipts(source, frozen_at, decisions, outcomes)?;
    freeze_counterfactual_candidate_groups(source_trajectory_id, source, frozen_at, inputs)
}

pub fn counterfactual_inputs_from_native_receipts(
    source: &FrozenDecisionTrajectoryTables,
    frozen_at: i64,
    decisions: &[NativeDecisionReceipt],
    outcomes: &[NativeDecisionOutcomeReceipt],
) -> Result<Vec<CounterfactualCandidateGroupInput>, CounterfactualCandidateGroupsError> {
    if frozen_at <= 0 || decisions.len() != source.decisions.len() {
        return Err(CounterfactualCandidateGroupsError::InvalidInput(
            "native decision population",
        ));
    }
    let mut by_decision = HashMap::with_capacity(decisions.len());
    for decision in decisions {
        decision.validate()?;
        if !decision.counterfactual_complete()
            || by_decision
                .insert(decision.decision_id.as_str(), decision)
                .is_some()
        {
            return Err(CounterfactualCandidateGroupsError::InvalidInput(
                "native counterfactual decision receipt",
            ));
        }
    }
    let mut inputs = Vec::with_capacity(source.decisions.len());
    for record in &source.decisions {
        let decision = by_decision.remove(record.decision_id.as_str()).ok_or(
            CounterfactualCandidateGroupsError::InvalidInput("missing native decision receipt"),
        )?;
        let state = source.states.get(record.state_ordinal as usize).ok_or(
            CounterfactualCandidateGroupsError::CorruptArtifact("source state ordinal"),
        )?;
        let selected = source
            .selected_actions
            .get(record.selected_label_ordinal as usize)
            .ok_or(CounterfactualCandidateGroupsError::CorruptArtifact(
                "source selected ordinal",
            ))?;
        let chosen = decision
            .candidates
            .get(decision.chosen_candidate_ordinal as usize)
            .ok_or(CounterfactualCandidateGroupsError::InvalidInput(
                "native chosen candidate",
            ))?;
        if decision.observed_at != record.observation_cutoff
            || decision.pre_state_snapshot_id != state.pre_state_snapshot_id
            || chosen.action_identity != selected.selected_action_identity
            || chosen.counterfactual_role != Some(NativeDecisionCounterfactualRole::RecordedAction)
        {
            return Err(CounterfactualCandidateGroupsError::InvalidInput(
                "native decision trajectory binding",
            ));
        }
        let resolved = resolve_complete_native_decision_outcomes(decision, outcomes, frozen_at)?;
        let candidates = resolved
            .into_iter()
            .map(|row| {
                let reward_vector = row.outcome.reward_vector.ok_or(
                    CounterfactualCandidateGroupsError::InvalidInput(
                        "retracted native candidate outcome",
                    ),
                )?;
                Ok(CounterfactualCandidateOutcome {
                    role: map_role(row.candidate.counterfactual_role.ok_or(
                        CounterfactualCandidateGroupsError::InvalidInput(
                            "native counterfactual role",
                        ),
                    )?),
                    action_identity: row.candidate.action_identity,
                    action: row.candidate.action,
                    reward_vector,
                    hard_constraints: row.outcome.hard_constraints,
                    outcome_authority_id: row.outcome.outcome_authority_id,
                    outcome_available_at: row.outcome.observed_at,
                    outcome_used_as_feature: false,
                })
            })
            .collect::<Result<Vec<_>, CounterfactualCandidateGroupsError>>()?;
        inputs.push(CounterfactualCandidateGroupInput {
            decision_id: record.decision_id.clone(),
            behavior_policy_id: decision.authority.policy_id.clone(),
            candidates,
        });
    }
    if !by_decision.is_empty() {
        return Err(CounterfactualCandidateGroupsError::InvalidInput(
            "extra native decision receipt",
        ));
    }
    Ok(inputs)
}

const fn map_role(role: NativeDecisionCounterfactualRole) -> CounterfactualCandidateRole {
    match role {
        NativeDecisionCounterfactualRole::RecordedAction => {
            CounterfactualCandidateRole::RecordedAction
        }
        NativeDecisionCounterfactualRole::HardPlausibleAlternative => {
            CounterfactualCandidateRole::HardPlausibleAlternative
        }
        NativeDecisionCounterfactualRole::SafeAbstention => {
            CounterfactualCandidateRole::SafeAbstention
        }
        NativeDecisionCounterfactualRole::MinimalRepair => {
            CounterfactualCandidateRole::MinimalRepair
        }
        NativeDecisionCounterfactualRole::AggressiveRepair => {
            CounterfactualCandidateRole::AggressiveRepair
        }
        NativeDecisionCounterfactualRole::EvidenceRichAlternative => {
            CounterfactualCandidateRole::EvidenceRichAlternative
        }
        NativeDecisionCounterfactualRole::TemporallyAttractiveInvalidAlternative => {
            CounterfactualCandidateRole::TemporallyAttractiveInvalidAlternative
        }
    }
}
