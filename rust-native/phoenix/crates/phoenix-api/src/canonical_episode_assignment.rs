use std::collections::BTreeSet;

use phoenix_graph_kernel::{GraphTruthCommit, GraphTruthLineage};
use phoenix_graph_research::{
    generate_episode_assignment_candidates, DecisionCandidateSourceKind,
    EpisodeCandidateGenerationRequest, EpisodeCandidateSeed, EPISODE_CANDIDATE_GENERATOR_ID,
    EPISODE_CANDIDATE_GENERATOR_VERSION,
};
use phoenix_store_native_core::{
    GraphTruthCommitAppend, NativeDecisionReceiptAppend, PhoenixGraphKernelStoreV2,
    PhoenixNativeDecisionStore, StoreError,
};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{
    certify_graph_decision_hard_constraints, certify_native_decision_outcome_receipt,
    certify_native_decision_receipt, GraphDecisionAction, GraphDecisionAuthority,
    GraphDecisionAuthorityKind, GraphDecisionEvidenceRef, GraphDecisionHardConstraintReceipt,
    GraphDecisionHeader, NativeDecisionAuthorityBridge, NativeDecisionAuthorityClass,
    NativeDecisionCandidateDisposition, NativeDecisionCandidateReceipt,
    NativeDecisionCounterfactualRole, NativeDecisionEffect, NativeDecisionOutcomeOperation,
    NativeDecisionOutcomeReceipt, NativeDecisionReceipt, NativeDecisionReceiptError,
    NativeDecisionTaskFamily, GRAPH_DECISION_HARD_CONSTRAINT_SCHEMA_VERSION,
    NATIVE_DECISION_OUTCOME_SCHEMA_VERSION, NATIVE_DECISION_RECEIPT_SCHEMA_VERSION,
};
use serde::{Deserialize, Serialize};

mod support;

use support::{build_commit, reject_conflicting_membership};

pub const CANONICAL_EPISODE_ASSIGNMENT_COMMIT_SCHEMA: &str =
    "phoenix-canonical-episode-assignment-commit/v1";
pub(super) const EPISODE_EDGE_TYPE: &str = "episode_contains_event";
pub(super) const EPISODE_ASSIGNMENT_POLICY: &str =
    "canonical-episode-assignment/operator-accept/v1";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeEpisodeAssignmentEvent {
    pub id: String,
    pub note_id: String,
    pub chunk_id: String,
    pub source_start: u32,
    pub source_end: u32,
    pub predicate: String,
    pub participant_entity_ids: Vec<String>,
    pub evidence_ids: Vec<String>,
    pub factuality: String,
    pub confidence_millis: u16,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeEpisodeAssignmentEpisode {
    pub id: String,
    pub note_id: String,
    pub label: String,
    pub source_start: u32,
    pub source_end: u32,
    pub chunk_ids: Vec<String>,
    pub event_ids: Vec<String>,
    pub entity_ids: Vec<String>,
    pub boundary_receipt_ids: Vec<String>,
    pub confidence_millis: u16,
    pub status: String,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CanonicalEpisodeAssignmentCommitRequest {
    pub schema_version: String,
    pub scope_key: String,
    pub source_snapshot_id: String,
    pub source_snapshot_built_at: i64,
    pub source_authority_content_hash: String,
    pub event: NativeEpisodeAssignmentEvent,
    pub episodes: Vec<NativeEpisodeAssignmentEpisode>,
    pub selected_action: CanonicalEpisodeAssignmentSelection,
    pub decided_at: i64,
    pub operator_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum CanonicalEpisodeAssignmentSelection {
    AttachToEpisode {
        #[serde(rename = "episodeId")]
        episode_id: String,
    },
    CreateEpisode,
    Abstain,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CanonicalEpisodeAssignmentCommitStatus {
    Appended,
    AlreadyPresent,
    AlreadyCanonical,
    NoChange,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CanonicalEpisodeAssignmentCommitResponse {
    pub schema_version: String,
    pub decision_id: String,
    pub decision_receipt_id: String,
    pub candidate_set_id: String,
    pub chosen_action_identity: String,
    pub chosen_action_kind: String,
    pub candidate_count: u32,
    pub outcome_receipt_id: String,
    pub operator_mutation_receipt_id: String,
    pub graph_truth_commit_id: Option<String>,
    pub graph_truth_generation: Option<u64>,
    pub commit_status: CanonicalEpisodeAssignmentCommitStatus,
    pub decision_appended: bool,
    pub outcome_appended: bool,
}

#[derive(Debug, thiserror::Error)]
pub enum CanonicalEpisodeAssignmentError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Receipt(#[from] NativeDecisionReceiptError),
    #[error("canonical episode candidate generation failed: {0}")]
    Candidate(String),
    #[error("invalid canonical episode assignment: {0}")]
    Invalid(&'static str),
    #[error("canonical episode assignment serialization failed: {0}")]
    Serialization(String),
}

pub fn commit_canonical_episode_assignment(
    store: &PhoenixOvergraphStore,
    mut request: CanonicalEpisodeAssignmentCommitRequest,
) -> Result<CanonicalEpisodeAssignmentCommitResponse, CanonicalEpisodeAssignmentError> {
    normalize_request(&mut request);
    validate_request(&request)?;
    let pre_state_snapshot_id = content_id(&(
        "phoenix-canonical-episode-assignment-prestate/v1",
        request.scope_key.as_str(),
        request.source_snapshot_id.as_str(),
        request.source_snapshot_built_at,
        request.source_authority_content_hash.as_str(),
        &request.event,
        &request.episodes,
    ))?;
    let new_episode_id = content_id(&(
        "phoenix-canonical-created-episode/v1",
        pre_state_snapshot_id.as_str(),
        request.event.id.as_str(),
    ))?;
    let selected = selected_episode(&request, &new_episode_id)?;
    let decision_id = format!(
        "episode-assignment:{}",
        content_digest(&(
            "phoenix-canonical-episode-assignment-decision/v1",
            pre_state_snapshot_id.as_str(),
            request.event.id.as_str(),
            request.operator_id.as_str(),
        ))?
    );
    let candidate_group_id = content_id(&(
        "phoenix-canonical-episode-assignment-candidate-group/v1",
        pre_state_snapshot_id.as_str(),
        request.event.id.as_str(),
    ))?;
    let lineage = GraphTruthLineage::build(store.load_graph_truth_commits()?)
        .map_err(|error| CanonicalEpisodeAssignmentError::Candidate(error.to_string()))?;
    if let Some(episode) = selected.as_ref() {
        reject_conflicting_membership(&lineage, episode.id.as_str(), request.event.id.as_str())?;
    }
    let already_canonical = selected.as_ref().is_some_and(|episode| {
        lineage
            .active_edge_commit(
                episode.id.as_str(),
                request.event.id.as_str(),
                EPISODE_EDGE_TYPE,
            )
            .is_some()
    });
    let authority = GraphDecisionAuthority {
        authority_id: request.operator_id.as_str().into(),
        kind: GraphDecisionAuthorityKind::Operator,
        policy_id: EPISODE_ASSIGNMENT_POLICY.into(),
        issued_at: request.decided_at,
    };
    let evidence = decision_evidence(&request);
    let (decision, decision_appended) = if let Some(existing) =
        store.load_native_decision_receipt_by_decision_id(&decision_id)?
    {
        validate_existing_decision(&existing, &request.selected_action)?;
        (existing, false)
    } else {
        let generation =
            generate_episode_assignment_candidates(&EpisodeCandidateGenerationRequest {
                candidate_group_id: candidate_group_id.as_str().into(),
                event_id: request.event.id.as_str().into(),
                new_episode_id: new_episode_id.as_str().into(),
                task_id: format!("canonical-episode-assignment:{}", request.event.id).into(),
                header: GraphDecisionHeader {
                    schema_version: 1,
                    decision_id: decision_id.as_str().into(),
                    pre_state_id: pre_state_snapshot_id.as_str().into(),
                    decided_at: request.decided_at,
                    authority: authority.clone(),
                    approval: None,
                },
                evidence: evidence.clone(),
                episode_seeds: candidate_seeds(&request),
            })
            .map_err(|error| CanonicalEpisodeAssignmentError::Candidate(error.to_string()))?;
        let chosen_ordinal = generation
            .group
            .candidates
            .iter()
            .position(|candidate| selection_matches(&request.selected_action, &candidate.action))
            .ok_or(CanonicalEpisodeAssignmentError::Invalid(
                "selected action was rejected by candidate generation",
            ))?;
        let candidates = generation
            .group
            .candidates
            .into_iter()
            .enumerate()
            .map(|(index, candidate)| {
                let abstain = matches!(&candidate.action, GraphDecisionAction::Abstain(_));
                NativeDecisionCandidateReceipt {
                    action_identity: candidate.action_identity,
                    action: candidate.action,
                    disposition: if index == chosen_ordinal {
                        NativeDecisionCandidateDisposition::Chosen
                    } else {
                        NativeDecisionCandidateDisposition::Unselected
                    },
                    counterfactual_role: if index == chosen_ordinal {
                        Some(NativeDecisionCounterfactualRole::RecordedAction)
                    } else if abstain {
                        Some(NativeDecisionCounterfactualRole::SafeAbstention)
                    } else {
                        Some(NativeDecisionCounterfactualRole::HardPlausibleAlternative)
                    },
                    source_labels: candidate
                        .sources
                        .into_iter()
                        .map(candidate_source_label)
                        .map(Into::into)
                        .collect(),
                }
            })
            .collect();
        let receipt = certify_native_decision_receipt(NativeDecisionReceipt {
            schema_version: NATIVE_DECISION_RECEIPT_SCHEMA_VERSION,
            receipt_id: "pending".into(),
            decision_id: decision_id.as_str().into(),
            task_family: NativeDecisionTaskFamily::CanonicalEpisodeAssignment,
            scope_key: request.scope_key.as_str().into(),
            lineage_ids: vec![request.source_snapshot_id.as_str().into()],
            observed_at: request.decided_at,
            label_available_at: request.decided_at,
            pre_state_snapshot_id: pre_state_snapshot_id.as_str().into(),
            candidate_set_id: "pending".into(),
            generator_id: EPISODE_CANDIDATE_GENERATOR_ID.into(),
            generator_version: EPISODE_CANDIDATE_GENERATOR_VERSION.into(),
            generator_input_id: generation.group.generation.generator_input_id,
            invalid_candidates_rejected: generation.group.generation.invalid_candidates_rejected,
            generation_latency_ns: generation.performance.generation_latency_ns,
            allocation_volume_bytes: generation.performance.allocation_volume_bytes,
            candidates,
            chosen_candidate_ordinal: chosen_ordinal as u32,
            authority: authority.clone(),
            authority_class: NativeDecisionAuthorityClass::OperatorPreference,
            evidence_anchors: evidence.clone(),
            bridge: NativeDecisionAuthorityBridge {
                source_authority_id: "rust-story-continuity-candidate-contract".into(),
                research_authority_id: "phoenix-native-overgraph".into(),
                source_state_receipt_id: pre_state_snapshot_id.as_str().into(),
                bridged_at: request.decided_at,
            },
        })?;
        let appended = matches!(
            store.append_native_decision_receipt(&receipt)?,
            NativeDecisionReceiptAppend::Appended { .. }
        );
        (receipt, appended)
    };
    request.decided_at = decision.observed_at;

    let chosen = &decision.candidates[decision.chosen_candidate_ordinal as usize];
    if matches!(chosen.action, GraphDecisionAction::Abstain(_)) {
        let operator_mutation_receipt_id = content_id(&(
            "phoenix-canonical-episode-assignment-operator-authorization/v1",
            decision.receipt_id.as_str(),
            chosen.action_identity.as_str(),
            decision.pre_state_snapshot_id.as_str(),
            request.operator_id.as_str(),
        ))?;
        let (outcome, outcome_appended) = append_outcome(
            store,
            &decision,
            &operator_mutation_receipt_id,
            None,
            request.decided_at,
            &request.operator_id,
        )?;
        return Ok(response(
            &decision,
            &outcome,
            operator_mutation_receipt_id,
            None,
            CanonicalEpisodeAssignmentCommitStatus::NoChange,
            decision_appended,
            outcome_appended,
        ));
    }
    let selected = selected.ok_or(CanonicalEpisodeAssignmentError::Invalid(
        "mutating selection is missing its episode",
    ))?;
    let commit_id = content_id(&(
        "phoenix-canonical-episode-assignment-commit-id/v1",
        decision.receipt_id.as_str(),
        chosen.action_identity.as_str(),
    ))?;
    let operator_mutation_receipt_id = content_id(&(
        "phoenix-canonical-episode-assignment-operator-authorization/v1",
        decision.receipt_id.as_str(),
        chosen.action_identity.as_str(),
        commit_id.as_str(),
        request.operator_id.as_str(),
    ))?;
    if let Some(existing) = store.load_graph_truth_commit(&commit_id)? {
        let (outcome, outcome_appended) = append_outcome(
            store,
            &decision,
            &operator_mutation_receipt_id,
            Some(&existing),
            request.decided_at,
            &request.operator_id,
        )?;
        store.reconcile_canonical_reward_producers(existing.header.committed_at)?;
        return Ok(response(
            &decision,
            &outcome,
            operator_mutation_receipt_id,
            Some(&existing),
            CanonicalEpisodeAssignmentCommitStatus::AlreadyPresent,
            decision_appended,
            outcome_appended,
        ));
    }

    if already_canonical {
        let (outcome, outcome_appended) = append_outcome(
            store,
            &decision,
            &operator_mutation_receipt_id,
            None,
            request.decided_at,
            &request.operator_id,
        )?;
        return Ok(response(
            &decision,
            &outcome,
            operator_mutation_receipt_id,
            None,
            CanonicalEpisodeAssignmentCommitStatus::AlreadyCanonical,
            decision_appended,
            outcome_appended,
        ));
    }

    let commit = build_commit(
        store,
        &lineage,
        &request,
        &selected,
        &decision,
        &operator_mutation_receipt_id,
        &commit_id,
    )?;
    let (outcome, outcome_appended) = append_outcome(
        store,
        &decision,
        &operator_mutation_receipt_id,
        Some(&commit),
        request.decided_at,
        &request.operator_id,
    )?;
    let status = match store.append_graph_truth_commit(&commit)? {
        GraphTruthCommitAppend::Appended => CanonicalEpisodeAssignmentCommitStatus::Appended,
        GraphTruthCommitAppend::AlreadyPresent { .. } => {
            CanonicalEpisodeAssignmentCommitStatus::AlreadyPresent
        }
    };
    Ok(response(
        &decision,
        &outcome,
        operator_mutation_receipt_id,
        Some(&commit),
        status,
        decision_appended,
        outcome_appended,
    ))
}

fn append_outcome(
    store: &PhoenixOvergraphStore,
    decision: &NativeDecisionReceipt,
    operator_receipt_id: &str,
    commit: Option<&GraphTruthCommit>,
    observed_at: i64,
    operator_id: &str,
) -> Result<(NativeDecisionOutcomeReceipt, bool), CanonicalEpisodeAssignmentError> {
    let chosen = &decision.candidates[decision.chosen_candidate_ordinal as usize];
    let hard_constraints =
        certify_graph_decision_hard_constraints(GraphDecisionHardConstraintReceipt {
            schema_version: GRAPH_DECISION_HARD_CONSTRAINT_SCHEMA_VERSION,
            receipt_id: "pending".into(),
            policy_id: EPISODE_ASSIGNMENT_POLICY.into(),
            evaluated_at: observed_at,
            passed: true,
            violations: Vec::new(),
        })?;
    let effect = if let Some(commit) = commit {
        NativeDecisionEffect::GraphMutation {
            post_state_snapshot_id: content_id(&(
                "phoenix-canonical-episode-assignment-poststate/v1",
                decision.pre_state_snapshot_id.as_str(),
                commit.header.commit_id.as_str(),
            ))?
            .into(),
            before_delta_id: decision.pre_state_snapshot_id.clone(),
            after_delta_id: commit.header.commit_id.clone(),
            graph_truth_commit_id: commit.header.commit_id.clone(),
        }
    } else {
        NativeDecisionEffect::NoChange {
            post_state_snapshot_id: decision.pre_state_snapshot_id.clone(),
        }
    };
    let outcome = certify_native_decision_outcome_receipt(NativeDecisionOutcomeReceipt {
        schema_version: NATIVE_DECISION_OUTCOME_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        decision_receipt_id: decision.receipt_id.clone(),
        decision_id: decision.decision_id.clone(),
        candidate_action_identity: chosen.action_identity.clone(),
        operation: NativeDecisionOutcomeOperation::Observe,
        observed_at,
        authority_class: NativeDecisionAuthorityClass::OperatorPreference,
        outcome_authority_id: operator_id.into(),
        reward_vector: None,
        hard_constraints,
        effect: Some(effect),
        predecessor_outcome_receipt_id: None,
        evidence_anchors: vec![GraphDecisionEvidenceRef {
            evidence_id: operator_receipt_id.into(),
            authority_id: operator_id.into(),
            available_at: observed_at,
        }],
    })?;
    let appended = matches!(
        store.append_native_decision_outcome_receipt(&outcome)?,
        NativeDecisionReceiptAppend::Appended { .. }
    );
    Ok((outcome, appended))
}

fn response(
    decision: &NativeDecisionReceipt,
    outcome: &NativeDecisionOutcomeReceipt,
    operator_mutation_receipt_id: String,
    commit: Option<&GraphTruthCommit>,
    commit_status: CanonicalEpisodeAssignmentCommitStatus,
    decision_appended: bool,
    outcome_appended: bool,
) -> CanonicalEpisodeAssignmentCommitResponse {
    let chosen = &decision.candidates[decision.chosen_candidate_ordinal as usize];
    CanonicalEpisodeAssignmentCommitResponse {
        schema_version: CANONICAL_EPISODE_ASSIGNMENT_COMMIT_SCHEMA.to_owned(),
        decision_id: decision.decision_id.to_string(),
        decision_receipt_id: decision.receipt_id.to_string(),
        candidate_set_id: decision.candidate_set_id.to_string(),
        chosen_action_identity: chosen.action_identity.to_string(),
        chosen_action_kind: action_kind(&chosen.action).to_owned(),
        candidate_count: decision.candidates.len() as u32,
        outcome_receipt_id: outcome.receipt_id.to_string(),
        operator_mutation_receipt_id,
        graph_truth_commit_id: commit.map(|value| value.header.commit_id.to_string()),
        graph_truth_generation: commit.map(|value| value.header.generation),
        commit_status,
        decision_appended,
        outcome_appended,
    }
}

fn decision_evidence(
    request: &CanonicalEpisodeAssignmentCommitRequest,
) -> Vec<GraphDecisionEvidenceRef> {
    let selected = match &request.selected_action {
        CanonicalEpisodeAssignmentSelection::AttachToEpisode { episode_id } => request
            .episodes
            .iter()
            .find(|episode| episode.id == *episode_id),
        CanonicalEpisodeAssignmentSelection::CreateEpisode
        | CanonicalEpisodeAssignmentSelection::Abstain => None,
    };
    let mut ids = BTreeSet::new();
    ids.extend(request.event.evidence_ids.iter().cloned());
    if let Some(episode) = selected {
        ids.extend(episode.boundary_receipt_ids.iter().cloned());
    }
    if ids.is_empty() {
        ids.insert(format!("story-continuity-event:{}", request.event.id));
    }
    ids.into_iter()
        .map(|evidence_id| GraphDecisionEvidenceRef {
            evidence_id: evidence_id.into(),
            authority_id: "rust-story-continuity-candidate-contract".into(),
            available_at: request.source_snapshot_built_at,
        })
        .collect()
}

fn candidate_seeds(request: &CanonicalEpisodeAssignmentCommitRequest) -> Vec<EpisodeCandidateSeed> {
    let participants = request
        .event
        .participant_entity_ids
        .iter()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    request
        .episodes
        .iter()
        .map(|episode| EpisodeCandidateSeed {
            episode_id: episode.id.as_str().into(),
            available_at: request.source_snapshot_built_at,
            active: episode.status != "blocked",
            scope_compatible: episode.note_id == request.event.note_id,
            temporally_plausible: episode.source_start <= request.event.source_end
                && episode.source_end >= request.event.source_start,
            same_entity: episode
                .entity_ids
                .iter()
                .any(|entity| participants.contains(entity.as_str())),
            related_entity: false,
            difficult_near_neighbor: !episode.event_ids.contains(&request.event.id)
                && episode.note_id == request.event.note_id,
        })
        .collect()
}

fn validate_existing_decision(
    decision: &NativeDecisionReceipt,
    selection: &CanonicalEpisodeAssignmentSelection,
) -> Result<(), CanonicalEpisodeAssignmentError> {
    if decision.task_family != NativeDecisionTaskFamily::CanonicalEpisodeAssignment {
        return Err(CanonicalEpisodeAssignmentError::Invalid(
            "existing decision belongs to another task",
        ));
    }
    let chosen = &decision.candidates[decision.chosen_candidate_ordinal as usize];
    if !selection_matches(selection, &chosen.action) {
        return Err(CanonicalEpisodeAssignmentError::Invalid(
            "existing decision selected a different action",
        ));
    }
    Ok(())
}

fn validate_request(
    request: &CanonicalEpisodeAssignmentCommitRequest,
) -> Result<(), CanonicalEpisodeAssignmentError> {
    if request.schema_version != CANONICAL_EPISODE_ASSIGNMENT_COMMIT_SCHEMA
        || request.scope_key.trim().is_empty()
        || request.source_snapshot_id.trim().is_empty()
        || request.source_authority_content_hash.trim().is_empty()
        || request.source_snapshot_built_at <= 0
        || request.source_snapshot_built_at > request.decided_at
        || request.decided_at <= 0
        || request.operator_id.trim().is_empty()
        || request.event.id.trim().is_empty()
        || request.event.note_id.trim().is_empty()
        || request.event.chunk_id.trim().is_empty()
        || request.event.predicate.trim().is_empty()
        || request.event.source_end < request.event.source_start
        || !request.event.no_topology_commit
    {
        return Err(CanonicalEpisodeAssignmentError::Invalid("request contract"));
    }
    let mut ids = BTreeSet::new();
    for episode in &request.episodes {
        if episode.id.trim().is_empty()
            || episode.note_id.trim().is_empty()
            || episode.label.trim().is_empty()
            || episode.source_end < episode.source_start
            || !episode.no_topology_commit
            || !ids.insert(episode.id.as_str())
        {
            return Err(CanonicalEpisodeAssignmentError::Invalid(
                "episode candidate contract",
            ));
        }
    }
    if let CanonicalEpisodeAssignmentSelection::AttachToEpisode { episode_id } =
        &request.selected_action
    {
        let selected = request
            .episodes
            .iter()
            .find(|episode| episode.id == *episode_id)
            .ok_or(CanonicalEpisodeAssignmentError::Invalid(
                "selected episode is absent",
            ))?;
        if selected.note_id != request.event.note_id || selected.status == "blocked" {
            return Err(CanonicalEpisodeAssignmentError::Invalid(
                "selected episode is not an active compatible candidate",
            ));
        }
    }
    Ok(())
}

fn selected_episode(
    request: &CanonicalEpisodeAssignmentCommitRequest,
    new_episode_id: &str,
) -> Result<Option<NativeEpisodeAssignmentEpisode>, CanonicalEpisodeAssignmentError> {
    match &request.selected_action {
        CanonicalEpisodeAssignmentSelection::AttachToEpisode { episode_id } => request
            .episodes
            .iter()
            .find(|episode| episode.id == *episode_id)
            .cloned()
            .map(Some)
            .ok_or(CanonicalEpisodeAssignmentError::Invalid(
                "selected episode is absent",
            )),
        CanonicalEpisodeAssignmentSelection::CreateEpisode => {
            Ok(Some(NativeEpisodeAssignmentEpisode {
                id: new_episode_id.to_owned(),
                note_id: request.event.note_id.clone(),
                label: request.event.predicate.clone(),
                source_start: request.event.source_start,
                source_end: request.event.source_end,
                chunk_ids: vec![request.event.chunk_id.clone()],
                event_ids: vec![request.event.id.clone()],
                entity_ids: request.event.participant_entity_ids.clone(),
                boundary_receipt_ids: request.event.evidence_ids.clone(),
                confidence_millis: request.event.confidence_millis,
                status: "active".to_owned(),
                no_topology_commit: true,
            }))
        }
        CanonicalEpisodeAssignmentSelection::Abstain => Ok(None),
    }
}

fn selection_matches(
    selection: &CanonicalEpisodeAssignmentSelection,
    action: &GraphDecisionAction,
) -> bool {
    match (selection, action) {
        (
            CanonicalEpisodeAssignmentSelection::AttachToEpisode { episode_id },
            GraphDecisionAction::AttachToEpisode(action),
        ) => action.episode_id == *episode_id,
        (
            CanonicalEpisodeAssignmentSelection::CreateEpisode,
            GraphDecisionAction::CreateEpisode(_),
        )
        | (CanonicalEpisodeAssignmentSelection::Abstain, GraphDecisionAction::Abstain(_)) => true,
        _ => false,
    }
}

const fn action_kind(action: &GraphDecisionAction) -> &'static str {
    match action {
        GraphDecisionAction::AttachToEpisode(_) => "attach_to_episode",
        GraphDecisionAction::CreateEpisode(_) => "create_episode",
        GraphDecisionAction::Abstain(_) => "abstain",
        _ => "unsupported",
    }
}

fn normalize_request(request: &mut CanonicalEpisodeAssignmentCommitRequest) {
    request
        .episodes
        .sort_unstable_by(|left, right| left.id.cmp(&right.id));
    for episode in &mut request.episodes {
        episode.chunk_ids.sort_unstable();
        episode.chunk_ids.dedup();
        episode.event_ids.sort_unstable();
        episode.event_ids.dedup();
        episode.entity_ids.sort_unstable();
        episode.entity_ids.dedup();
        episode.boundary_receipt_ids.sort_unstable();
        episode.boundary_receipt_ids.dedup();
    }
    request.event.participant_entity_ids.sort_unstable();
    request.event.participant_entity_ids.dedup();
    request.event.evidence_ids.sort_unstable();
    request.event.evidence_ids.dedup();
}

const fn candidate_source_label(source: DecisionCandidateSourceKind) -> &'static str {
    match source {
        DecisionCandidateSourceKind::ActiveCompatibleEpisode => "active_compatible_episode",
        DecisionCandidateSourceKind::TemporallyPlausibleEpisode => "temporally_plausible_episode",
        DecisionCandidateSourceKind::SameEntityEpisode => "same_entity_episode",
        DecisionCandidateSourceKind::RelatedEntityEpisode => "related_entity_episode",
        DecisionCandidateSourceKind::DifficultNearNeighborEpisode => {
            "difficult_near_neighbor_episode"
        }
        DecisionCandidateSourceKind::SameRelationHardNegative => "same_relation_hard_negative",
        DecisionCandidateSourceKind::EvidenceConfusableAlternative => {
            "evidence_confusable_alternative"
        }
        DecisionCandidateSourceKind::TemporallyPlausibleIncorrectAction => {
            "temporally_plausible_incorrect_action"
        }
        DecisionCandidateSourceKind::StructurallyValidSemanticNegative => {
            "structurally_valid_semantic_negative"
        }
        DecisionCandidateSourceKind::MinimalEditRepairAlternative => {
            "minimal_edit_repair_alternative"
        }
        DecisionCandidateSourceKind::ExplicitCreateEpisode => "explicit_create_episode",
        DecisionCandidateSourceKind::ExplicitAbstain => "explicit_abstain",
    }
}

fn content_id<T: Serialize>(value: &T) -> Result<String, CanonicalEpisodeAssignmentError> {
    Ok(format!("b3-{}", content_digest(value)?))
}

fn content_digest<T: Serialize>(value: &T) -> Result<String, CanonicalEpisodeAssignmentError> {
    let bytes = serde_json::to_vec(value)
        .map_err(|error| CanonicalEpisodeAssignmentError::Serialization(error.to_string()))?;
    Ok(blake3::hash(&bytes).to_hex().to_string())
}

#[cfg(test)]
#[path = "canonical_episode_assignment_tests.rs"]
mod tests;
