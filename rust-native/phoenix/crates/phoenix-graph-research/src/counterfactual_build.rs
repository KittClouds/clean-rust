use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};
use phoenix_types::{GraphDecisionAction, GraphDecisionRewardSignal, GraphDecisionRewardVector};
use serde::Serialize;

use crate::{
    graph_decision_candidate_identity, CounterfactualCandidateGroupInput,
    CounterfactualCandidateGroupsError, CounterfactualCandidateOutcome,
    CounterfactualCandidateRole, CounterfactualDatasetCertificate,
    CounterfactualHardConstraintResult, CounterfactualHardConstraintViolation, ExactRange,
    FrozenCounterfactualCandidateGroups, FrozenCounterfactualGroupRecord,
    FrozenDecisionTrajectoryTables, COUNTERFACTUAL_CANDIDATE_GROUPS_SCHEMA,
};

pub fn certify_counterfactual_constraint_result(
    result: CounterfactualHardConstraintResult,
) -> Result<CounterfactualHardConstraintResult, CounterfactualCandidateGroupsError> {
    phoenix_types::certify_graph_decision_hard_constraints(result)
        .map_err(|_| CounterfactualCandidateGroupsError::InvalidInput("hard constraint result"))
}

pub fn freeze_counterfactual_candidate_groups(
    source_trajectory_id: CompactString,
    source: &FrozenDecisionTrajectoryTables,
    frozen_at: i64,
    inputs: Vec<CounterfactualCandidateGroupInput>,
) -> Result<FrozenCounterfactualCandidateGroups, CounterfactualCandidateGroupsError> {
    if !is_blake3(&source_trajectory_id)
        || frozen_at <= 0
        || source.decisions.is_empty()
        || inputs.len() != source.decisions.len()
    {
        return Err(CounterfactualCandidateGroupsError::InvalidInput(
            "dataset authority",
        ));
    }
    let mut by_decision = HashMap::with_capacity(inputs.len());
    for input in inputs {
        if input.decision_id.trim().is_empty()
            || input.behavior_policy_id.trim().is_empty()
            || by_decision
                .insert(input.decision_id.clone(), input)
                .is_some()
        {
            return Err(CounterfactualCandidateGroupsError::InvalidInput(
                "decision group",
            ));
        }
    }

    let mut groups = Vec::with_capacity(source.decisions.len());
    let mut candidates =
        Vec::with_capacity(source.decisions.len() * CounterfactualCandidateRole::ALL.len());
    let mut certificate = CounterfactualDatasetCertificate {
        groups_checked: 0,
        candidates_checked: 0,
        complete_role_groups: 0,
        recorded_actions_covered: 0,
        fully_observed_reward_vectors: 0,
        hard_constraint_receipts: 0,
        labels_after_observation: 0,
        outcomes_used_as_features: 0,
        outcomes_after_freeze: 0,
        duplicate_action_identities: 0,
        invalid_temporal_sentinels: 0,
    };

    for record in &source.decisions {
        let Some(mut input) = by_decision.remove(&record.decision_id) else {
            return Err(CounterfactualCandidateGroupsError::InvalidInput(
                "missing decision group",
            ));
        };
        input.candidates.sort_unstable_by_key(|row| row.role as u8);
        validate_role_set(&input.candidates)?;
        certificate.complete_role_groups += 1;

        let state = source.states.get(record.state_ordinal as usize).ok_or(
            CounterfactualCandidateGroupsError::CorruptArtifact("source state ordinal"),
        )?;
        let selected = source
            .selected_actions
            .get(record.selected_label_ordinal as usize)
            .ok_or(CounterfactualCandidateGroupsError::CorruptArtifact(
                "source selected ordinal",
            ))?;
        let recorded_reward = source.rewards.get(record.reward_ordinal as usize).ok_or(
            CounterfactualCandidateGroupsError::CorruptArtifact("source reward ordinal"),
        )?;
        let selected_candidate = source
            .candidate_actions
            .get(selected.selected_candidate_ordinal as usize)
            .ok_or(CounterfactualCandidateGroupsError::CorruptArtifact(
                "source candidate ordinal",
            ))?;

        let offset = candidates.len() as u64;
        let mut action_ids = HashSet::with_capacity(input.candidates.len());
        for outcome in input.candidates {
            validate_outcome(
                &outcome,
                record.decision_id.as_str(),
                state.pre_state_snapshot_id.as_str(),
                record.observation_cutoff,
                &selected_candidate.action,
                frozen_at,
            )?;
            certificate.candidates_checked += 1;
            if !action_ids.insert(outcome.action_identity.clone()) {
                certificate.duplicate_action_identities += 1;
            }
            if reward_is_fully_observed(&outcome.reward_vector) {
                certificate.fully_observed_reward_vectors += 1;
            }
            if constraint_receipt_is_valid(&outcome.hard_constraints)? {
                certificate.hard_constraint_receipts += 1;
            }
            if outcome.outcome_available_at > record.observation_cutoff {
                certificate.labels_after_observation += 1;
            }
            if outcome.outcome_used_as_feature {
                certificate.outcomes_used_as_features += 1;
            }
            if outcome.outcome_available_at > frozen_at {
                certificate.outcomes_after_freeze += 1;
            }
            if outcome.role == CounterfactualCandidateRole::RecordedAction {
                if outcome.action_identity != selected.selected_action_identity
                    || outcome.reward_vector != *recorded_reward
                {
                    return Err(CounterfactualCandidateGroupsError::InvalidInput(
                        "recorded action authority",
                    ));
                }
                certificate.recorded_actions_covered += 1;
            }
            if outcome.role == CounterfactualCandidateRole::TemporallyAttractiveInvalidAlternative
                && (outcome.hard_constraints.passed
                    || !outcome
                        .hard_constraints
                        .violations
                        .contains(&CounterfactualHardConstraintViolation::FutureInformation))
            {
                certificate.invalid_temporal_sentinels += 1;
            }
            candidates.push(outcome);
        }

        let group_id = group_identity(
            record.decision_id.as_str(),
            input.behavior_policy_id.as_str(),
            &candidates[offset as usize..],
        )?;
        groups.push(FrozenCounterfactualGroupRecord {
            group_id,
            decision_id: record.decision_id.clone(),
            observation_cutoff: record.observation_cutoff,
            pre_state_snapshot_id: state.pre_state_snapshot_id.clone(),
            behavior_policy_id: input.behavior_policy_id,
            candidates: ExactRange {
                offset,
                length: CounterfactualCandidateRole::ALL.len() as u64,
            },
            recorded_candidate_ordinal: offset,
            split: record.split,
        });
        certificate.groups_checked += 1;
    }
    if !by_decision.is_empty() || !certificate.passes() {
        return Err(CounterfactualCandidateGroupsError::Leakage(
            "counterfactual dataset certificate",
        ));
    }

    let mut snapshot = FrozenCounterfactualCandidateGroups {
        schema_version: COUNTERFACTUAL_CANDIDATE_GROUPS_SCHEMA.into(),
        dataset_id: "pending".into(),
        source_trajectory_id,
        frozen_at,
        groups,
        candidates,
        certificate,
    };
    snapshot.dataset_id = content_id(&snapshot)?;
    Ok(snapshot)
}

pub fn validate_counterfactual_candidate_groups(
    snapshot: &FrozenCounterfactualCandidateGroups,
) -> Result<(), CounterfactualCandidateGroupsError> {
    if snapshot.schema_version != COUNTERFACTUAL_CANDIDATE_GROUPS_SCHEMA
        || !is_blake3(&snapshot.source_trajectory_id)
        || !snapshot.certificate.passes()
        || snapshot.groups.len() as u64 != snapshot.certificate.groups_checked
        || snapshot.candidates.len() as u64 != snapshot.certificate.candidates_checked
    {
        return Err(CounterfactualCandidateGroupsError::CorruptArtifact(
            "snapshot contract",
        ));
    }
    let mut candidate = snapshot.clone();
    let expected = candidate.dataset_id.clone();
    candidate.dataset_id = "pending".into();
    if content_id(&candidate)? != expected {
        return Err(CounterfactualCandidateGroupsError::Identity(
            "dataset identity",
        ));
    }
    let mut observed_rewards = 0_u64;
    let mut constraint_receipts = 0_u64;
    let mut labels_after_observation = 0_u64;
    for (group_index, group) in snapshot.groups.iter().enumerate() {
        let end =
            group
                .candidates
                .end()
                .ok_or(CounterfactualCandidateGroupsError::CorruptArtifact(
                    "candidate range overflow",
                ))? as usize;
        let start = group.candidates.offset as usize;
        if group.candidates.length != CounterfactualCandidateRole::ALL.len() as u64
            || start != group_index * CounterfactualCandidateRole::ALL.len()
            || end > snapshot.candidates.len()
            || group.recorded_candidate_ordinal != group.candidates.offset
            || snapshot.candidates[start].role != CounterfactualCandidateRole::RecordedAction
            || group_identity(
                group.decision_id.as_str(),
                group.behavior_policy_id.as_str(),
                &snapshot.candidates[start..end],
            )? != group.group_id
        {
            return Err(CounterfactualCandidateGroupsError::CorruptArtifact(
                "group range or identity",
            ));
        }
        validate_role_set(&snapshot.candidates[start..end])?;
        let mut action_ids = HashSet::with_capacity(CounterfactualCandidateRole::ALL.len());
        for outcome in &snapshot.candidates[start..end] {
            outcome.action.validate_candidate()?;
            outcome.reward_vector.validate()?;
            if outcome.action.header().decision_id != group.decision_id
                || outcome.action.header().pre_state_id != group.pre_state_snapshot_id
                || outcome.action.header().decided_at != group.observation_cutoff
                || outcome.action.header().approval.is_some()
                || graph_decision_candidate_identity(&outcome.action)? != outcome.action_identity
                || outcome.reward_vector.decision_id != group.decision_id
                || !action_ids.insert(outcome.action_identity.clone())
                || outcome.outcome_authority_id.trim().is_empty()
                || outcome.outcome_available_at <= 0
                || outcome.outcome_available_at > snapshot.frozen_at
                || outcome.outcome_used_as_feature
                || max_reward_observed_at(&outcome.reward_vector)? > outcome.outcome_available_at
                || outcome.hard_constraints.evaluated_at > outcome.outcome_available_at
            {
                return Err(CounterfactualCandidateGroupsError::CorruptArtifact(
                    "candidate outcome contract",
                ));
            }
            validate_role_semantics(outcome)?;
            observed_rewards += u64::from(reward_is_fully_observed(&outcome.reward_vector));
            constraint_receipts +=
                u64::from(constraint_receipt_is_valid(&outcome.hard_constraints)?);
            labels_after_observation +=
                u64::from(outcome.outcome_available_at > group.observation_cutoff);
        }
    }
    if observed_rewards != snapshot.certificate.fully_observed_reward_vectors
        || constraint_receipts != snapshot.certificate.hard_constraint_receipts
        || labels_after_observation != snapshot.certificate.labels_after_observation
    {
        return Err(CounterfactualCandidateGroupsError::CorruptArtifact(
            "certificate counters",
        ));
    }
    Ok(())
}

fn validate_outcome(
    outcome: &CounterfactualCandidateOutcome,
    decision_id: &str,
    pre_state_id: &str,
    cutoff: i64,
    recorded_action: &GraphDecisionAction,
    frozen_at: i64,
) -> Result<(), CounterfactualCandidateGroupsError> {
    outcome.action.validate_candidate()?;
    outcome.reward_vector.validate()?;
    let header = outcome.action.header();
    if header.decision_id != decision_id
        || header.pre_state_id != pre_state_id
        || header.decided_at != cutoff
        || header.approval.is_some()
        || header.authority != recorded_action.header().authority
        || graph_decision_candidate_identity(&outcome.action)? != outcome.action_identity
        || outcome.reward_vector.decision_id != decision_id
        || outcome.outcome_authority_id.trim().is_empty()
        || outcome.outcome_available_at <= 0
        || outcome.outcome_available_at > frozen_at
        || max_reward_observed_at(&outcome.reward_vector)? > outcome.outcome_available_at
        || outcome.hard_constraints.evaluated_at > outcome.outcome_available_at
        || outcome.outcome_used_as_feature
    {
        return Err(CounterfactualCandidateGroupsError::InvalidInput(
            "candidate outcome binding",
        ));
    }
    validate_role_semantics(outcome)
}

fn validate_role_semantics(
    outcome: &CounterfactualCandidateOutcome,
) -> Result<(), CounterfactualCandidateGroupsError> {
    match outcome.role {
        CounterfactualCandidateRole::SafeAbstention
            if !matches!(outcome.action, GraphDecisionAction::Abstain(_)) =>
        {
            return Err(CounterfactualCandidateGroupsError::InvalidInput(
                "safe abstention role",
            ));
        }
        CounterfactualCandidateRole::MinimalRepair
        | CounterfactualCandidateRole::AggressiveRepair
            if !matches!(outcome.action, GraphDecisionAction::RepairGraphRegion(_)) =>
        {
            return Err(CounterfactualCandidateGroupsError::InvalidInput(
                "repair role",
            ));
        }
        CounterfactualCandidateRole::EvidenceRichAlternative
            if outcome.action.evidence().is_empty() =>
        {
            return Err(CounterfactualCandidateGroupsError::InvalidInput(
                "evidence-rich role",
            ));
        }
        CounterfactualCandidateRole::TemporallyAttractiveInvalidAlternative
            if outcome.hard_constraints.passed
                || !outcome
                    .hard_constraints
                    .violations
                    .contains(&CounterfactualHardConstraintViolation::FutureInformation) =>
        {
            return Err(CounterfactualCandidateGroupsError::InvalidInput(
                "temporal invalid sentinel",
            ));
        }
        CounterfactualCandidateRole::TemporallyAttractiveInvalidAlternative => {}
        _ if !outcome.hard_constraints.passed => {
            return Err(CounterfactualCandidateGroupsError::InvalidInput(
                "valid role failed hard constraints",
            ));
        }
        _ => {}
    }
    Ok(())
}

fn validate_role_set(
    candidates: &[CounterfactualCandidateOutcome],
) -> Result<(), CounterfactualCandidateGroupsError> {
    if candidates.len() != CounterfactualCandidateRole::ALL.len()
        || candidates
            .iter()
            .zip(CounterfactualCandidateRole::ALL)
            .any(|(candidate, role)| candidate.role != role)
    {
        return Err(CounterfactualCandidateGroupsError::InvalidInput(
            "candidate role set",
        ));
    }
    Ok(())
}

fn constraint_receipt_is_valid(
    result: &CounterfactualHardConstraintResult,
) -> Result<bool, CounterfactualCandidateGroupsError> {
    Ok(result.validate().is_ok())
}

fn reward_is_fully_observed(reward: &GraphDecisionRewardVector) -> bool {
    reward
        .dimensions()
        .iter()
        .all(|(_, signal)| matches!(signal, GraphDecisionRewardSignal::Observed { .. }))
}

fn max_reward_observed_at(
    reward: &GraphDecisionRewardVector,
) -> Result<i64, CounterfactualCandidateGroupsError> {
    let mut latest = 0;
    for (_, signal) in reward.dimensions() {
        let GraphDecisionRewardSignal::Observed { observed_at, .. } = signal else {
            return Err(CounterfactualCandidateGroupsError::InvalidInput(
                "pending counterfactual reward",
            ));
        };
        latest = latest.max(*observed_at);
    }
    Ok(latest)
}

fn group_identity(
    decision_id: &str,
    behavior_policy_id: &str,
    candidates: &[CounterfactualCandidateOutcome],
) -> Result<CompactString, CounterfactualCandidateGroupsError> {
    content_id(&(decision_id, behavior_policy_id, candidates))
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value[3..].bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn content_id(value: &impl Serialize) -> Result<CompactString, CounterfactualCandidateGroupsError> {
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}
