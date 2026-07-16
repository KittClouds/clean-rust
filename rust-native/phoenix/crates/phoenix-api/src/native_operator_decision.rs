use std::time::Instant;

use phoenix_graph_kernel::GraphTruthCommit;
use phoenix_store_native_core::{
    NativeDecisionReceiptAppend, PhoenixGraphKernelStoreV2, PhoenixNativeDecisionStore, StoreError,
};
use phoenix_types::{
    certify_graph_decision_hard_constraints, certify_native_decision_outcome_receipt,
    certify_native_decision_receipt, content_address_native_decision_graph_truth_link,
    graph_decision_action_identity, AbstainAction, AcceptDeltaAction, DeferDeltaAction,
    GraphDecisionAbstentionReason, GraphDecisionAction, GraphDecisionAuthority,
    GraphDecisionAuthorityKind, GraphDecisionEvidence, GraphDecisionEvidenceRef,
    GraphDecisionHardConstraintReceipt, GraphDecisionHardConstraintViolation, GraphDecisionHeader,
    GraphDeltaDeferralReason, GraphDeltaRejectionReason, NativeDecisionAuthorityBridge,
    NativeDecisionAuthorityClass, NativeDecisionCandidateDisposition,
    NativeDecisionCandidateReceipt, NativeDecisionCounterfactualRole, NativeDecisionEffect,
    NativeDecisionOutcomeOperation, NativeDecisionOutcomeReceipt, NativeDecisionReceipt,
    NativeDecisionReceiptError, NativeDecisionTaskFamily, RejectDeltaAction,
    GRAPH_DECISION_HARD_CONSTRAINT_SCHEMA_VERSION, NATIVE_DECISION_OUTCOME_SCHEMA_VERSION,
    NATIVE_DECISION_RECEIPT_SCHEMA_VERSION,
};
use serde::{Deserialize, Serialize};

pub const NATIVE_OPERATOR_DECISION_BEGIN_SCHEMA: &str = "phoenix-native-operator-decision-begin/v1";
pub const NATIVE_OPERATOR_DECISION_COMPLETE_SCHEMA: &str =
    "phoenix-native-operator-decision-complete/v1";
pub const NATIVE_DECISION_CENSUS_SCHEMA: &str = "phoenix-native-decision-census/v1";
pub use phoenix_types::{
    NativeDecisionGraphTruthLink, NativeDecisionGraphTruthLinkRequest,
    NATIVE_DECISION_TRUTH_LINK_SCHEMA,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeOperatorReviewDecision {
    Accepted,
    Rejected,
    Deferred,
    Muted,
    PromotedToAnchor,
    CompiledToGraph,
    LedgerOnly,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeOperatorDecisionBeginRequest {
    pub schema_version: String,
    pub scope_key: String,
    pub source_snapshot_id: String,
    pub source_snapshot_built_at: i64,
    pub source_authority_content_hash: String,
    pub target_object_id: String,
    pub target_object_kind: String,
    pub source_fingerprint: String,
    pub source_receipt_ids: Vec<String>,
    pub previous_state: String,
    pub available_decisions: Vec<NativeOperatorReviewDecision>,
    pub selected_decision: NativeOperatorReviewDecision,
    pub decided_at: i64,
    pub operator_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeOperatorDecisionBeginResponse {
    pub schema_version: String,
    pub decision_id: String,
    pub decision_receipt_id: String,
    pub pre_state_snapshot_id: String,
    pub candidate_set_id: String,
    pub chosen_action_identity: String,
    pub candidate_count: u32,
    pub appended: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeOperatorDecisionCompleteRequest {
    pub schema_version: String,
    pub decision_id: String,
    pub decision_receipt_id: String,
    pub post_snapshot_id: String,
    pub post_snapshot_built_at: i64,
    pub post_authority_content_hash: String,
    pub operator_mutation_receipt_id: String,
    pub completed_at: i64,
    pub outcome_authority_id: String,
    pub applied: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeOperatorDecisionCompleteResponse {
    pub schema_version: String,
    pub decision_id: String,
    pub decision_receipt_id: String,
    pub outcome_receipt_id: String,
    pub post_state_snapshot_id: String,
    pub reward_ready: bool,
    pub appended: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeDecisionCensus {
    pub schema_version: String,
    pub behavior_labels: u64,
    pub canonical_episode_assignment_labels: u64,
    pub canonical_episode_attach_labels: u64,
    pub canonical_episode_create_labels: u64,
    pub canonical_episode_abstain_labels: u64,
    pub canonical_episode_first_observed_at: Option<i64>,
    pub canonical_episode_last_observed_at: Option<i64>,
    pub canonical_episode_candidate_count_total: u64,
    pub canonical_episode_candidate_count_min: u64,
    pub canonical_episode_candidate_count_max: u64,
    pub operator_preference_labels: u64,
    pub execution_outcomes: u64,
    pub reward_complete_outcomes: u64,
    pub reward_censored_outcomes: u64,
    pub counterfactual_ready_decisions: u64,
    pub graph_truth_linked_decisions: u64,
}

#[derive(Debug, thiserror::Error)]
pub enum NativeOperatorDecisionError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Receipt(#[from] NativeDecisionReceiptError),
    #[error("invalid native operator decision: {0}")]
    Invalid(&'static str),
    #[error("native operator decision serialization failed: {0}")]
    Serialization(String),
}

pub fn begin_native_operator_decision<S: PhoenixNativeDecisionStore + ?Sized>(
    store: &S,
    mut request: NativeOperatorDecisionBeginRequest,
) -> Result<NativeOperatorDecisionBeginResponse, NativeOperatorDecisionError> {
    validate_begin_request(&request)?;
    request.available_decisions.sort_unstable();
    request.available_decisions.dedup();
    if !request
        .available_decisions
        .contains(&request.selected_decision)
    {
        return Err(NativeOperatorDecisionError::Invalid(
            "selected decision is not an available action",
        ));
    }

    let pre_state_snapshot_id = content_id(&(
        "phoenix-native-operator-prestate/v1",
        request.scope_key.as_str(),
        request.source_snapshot_id.as_str(),
        request.source_snapshot_built_at,
        request.source_authority_content_hash.as_str(),
        request.target_object_id.as_str(),
        request.target_object_kind.as_str(),
        request.source_fingerprint.as_str(),
        request.previous_state.as_str(),
    ))?;
    let generator_input_id = content_id(&(
        "phoenix-native-operator-candidates/v1",
        pre_state_snapshot_id.as_str(),
        request.target_object_id.as_str(),
        &request.available_decisions,
        &request.source_receipt_ids,
    ))?;
    let decision_id = format!(
        "operator:{}",
        content_digest(&(
            "phoenix-native-operator-choice/v1",
            generator_input_id.as_str(),
            request.selected_decision,
            request.decided_at,
            request.operator_id.as_str(),
        ))?
    );
    if let Some(existing) = store.load_native_decision_receipt_by_decision_id(&decision_id)? {
        return begin_response(&existing, false);
    }

    let started = Instant::now();
    let authority = GraphDecisionAuthority {
        authority_id: request.operator_id.as_str().into(),
        kind: GraphDecisionAuthorityKind::Operator,
        policy_id: "atlas-control-operator-review/v1".into(),
        issued_at: request.decided_at,
    };
    let evidence = decision_evidence(&request);
    let header = GraphDecisionHeader {
        schema_version: 1,
        decision_id: decision_id.as_str().into(),
        pre_state_id: pre_state_snapshot_id.as_str().into(),
        decided_at: request.decided_at,
        authority: authority.clone(),
        approval: None,
    };
    let mut candidates = Vec::<NativeDecisionCandidateReceipt>::new();
    let mut chosen_ordinal = None;
    for decision in request.available_decisions.iter().copied() {
        let action = operator_action(
            decision,
            &request.target_object_id,
            header.clone(),
            evidence.clone(),
        );
        let identity = graph_decision_action_identity(&action)?;
        if let Some((index, prior)) = candidates
            .iter_mut()
            .enumerate()
            .find(|(_, candidate)| candidate.action_identity == identity)
        {
            prior
                .source_labels
                .push(operator_source_label(decision).into());
            if decision == request.selected_decision {
                chosen_ordinal = Some(index);
            }
            continue;
        }
        if decision == request.selected_decision {
            chosen_ordinal = Some(candidates.len());
        }
        candidates.push(NativeDecisionCandidateReceipt {
            action_identity: identity,
            action,
            disposition: NativeDecisionCandidateDisposition::Unselected,
            counterfactual_role: None,
            source_labels: vec![operator_source_label(decision).into()],
        });
    }
    let abstain = GraphDecisionAction::Abstain(AbstainAction {
        header,
        task_id: request.target_object_id.as_str().into(),
        candidate_set_id: None,
        reason: GraphDecisionAbstentionReason::AmbiguousCandidates,
        evidence: evidence.clone(),
    });
    candidates.push(NativeDecisionCandidateReceipt {
        action_identity: graph_decision_action_identity(&abstain)?,
        action: abstain,
        disposition: NativeDecisionCandidateDisposition::Unselected,
        counterfactual_role: Some(NativeDecisionCounterfactualRole::SafeAbstention),
        source_labels: vec!["atlas-control:safe-abstention".into()],
    });
    let chosen_ordinal = chosen_ordinal.ok_or(NativeOperatorDecisionError::Invalid(
        "selected action was removed during candidate normalization",
    ))?;
    candidates[chosen_ordinal].disposition = NativeDecisionCandidateDisposition::Chosen;
    candidates[chosen_ordinal].counterfactual_role =
        Some(NativeDecisionCounterfactualRole::RecordedAction);

    let receipt = certify_native_decision_receipt(NativeDecisionReceipt {
        schema_version: NATIVE_DECISION_RECEIPT_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        decision_id: decision_id.into(),
        task_family: NativeDecisionTaskFamily::DeltaAdjudication,
        scope_key: request.scope_key.as_str().into(),
        lineage_ids: vec![request.source_snapshot_id.as_str().into()],
        observed_at: request.decided_at,
        label_available_at: request.decided_at,
        pre_state_snapshot_id: pre_state_snapshot_id.as_str().into(),
        candidate_set_id: "pending".into(),
        generator_id: "atlas-control-review-actions".into(),
        generator_version: "1".into(),
        generator_input_id: generator_input_id.into(),
        invalid_candidates_rejected: request
            .available_decisions
            .len()
            .saturating_add(1)
            .saturating_sub(candidates.len()) as u32,
        generation_latency_ns: started.elapsed().as_nanos().max(1) as u64,
        allocation_volume_bytes: 0,
        candidates,
        chosen_candidate_ordinal: chosen_ordinal as u32,
        authority,
        authority_class: NativeDecisionAuthorityClass::OperatorPreference,
        evidence_anchors: evidence.into_iter().collect(),
        bridge: NativeDecisionAuthorityBridge {
            source_authority_id: "graph_rebuild_live_contract".into(),
            research_authority_id: "phoenix-native-overgraph".into(),
            source_state_receipt_id: pre_state_snapshot_id.as_str().into(),
            bridged_at: request.decided_at,
        },
    })?;
    let appended = matches!(
        store.append_native_decision_receipt(&receipt)?,
        NativeDecisionReceiptAppend::Appended { .. }
    );
    begin_response(&receipt, appended)
}

pub fn complete_native_operator_decision<S: PhoenixNativeDecisionStore + ?Sized>(
    store: &S,
    request: NativeOperatorDecisionCompleteRequest,
) -> Result<NativeOperatorDecisionCompleteResponse, NativeOperatorDecisionError> {
    validate_complete_request(&request)?;
    let decision = store
        .load_native_decision_receipt(&request.decision_receipt_id)?
        .ok_or(NativeOperatorDecisionError::Invalid(
            "decision receipt missing",
        ))?;
    if decision.decision_id != request.decision_id {
        return Err(NativeOperatorDecisionError::Invalid(
            "decision completion identity mismatch",
        ));
    }
    let chosen = decision
        .candidates
        .get(decision.chosen_candidate_ordinal as usize)
        .ok_or(NativeOperatorDecisionError::Invalid(
            "chosen candidate missing",
        ))?;
    let post_state_snapshot_id = content_id(&(
        "phoenix-native-operator-poststate/v1",
        request.decision_id.as_str(),
        request.post_snapshot_id.as_str(),
        request.post_snapshot_built_at,
        request.post_authority_content_hash.as_str(),
        request.operator_mutation_receipt_id.as_str(),
        request.applied,
    ))?;
    let evidence = vec![GraphDecisionEvidenceRef {
        evidence_id: request.operator_mutation_receipt_id.as_str().into(),
        authority_id: request.outcome_authority_id.as_str().into(),
        available_at: request.completed_at,
    }];
    let hard_constraints =
        certify_graph_decision_hard_constraints(GraphDecisionHardConstraintReceipt {
            schema_version: GRAPH_DECISION_HARD_CONSTRAINT_SCHEMA_VERSION,
            receipt_id: "pending".into(),
            policy_id: "atlas-control-review-application/v1".into(),
            evaluated_at: request.completed_at,
            passed: request.applied,
            violations: if request.applied {
                Vec::new()
            } else {
                vec![GraphDecisionHardConstraintViolation::IllegalPrecondition]
            },
        })?;
    let outcome = certify_native_decision_outcome_receipt(NativeDecisionOutcomeReceipt {
        schema_version: NATIVE_DECISION_OUTCOME_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        decision_receipt_id: decision.receipt_id.clone(),
        decision_id: decision.decision_id.clone(),
        candidate_action_identity: chosen.action_identity.clone(),
        operation: NativeDecisionOutcomeOperation::Observe,
        observed_at: request.completed_at,
        authority_class: NativeDecisionAuthorityClass::OperatorPreference,
        outcome_authority_id: request.outcome_authority_id.as_str().into(),
        reward_vector: None,
        hard_constraints,
        effect: Some(NativeDecisionEffect::NoChange {
            post_state_snapshot_id: post_state_snapshot_id.as_str().into(),
        }),
        predecessor_outcome_receipt_id: None,
        evidence_anchors: evidence,
    })?;
    let appended = matches!(
        store.append_native_decision_outcome_receipt(&outcome)?,
        NativeDecisionReceiptAppend::Appended { .. }
    );
    Ok(NativeOperatorDecisionCompleteResponse {
        schema_version: NATIVE_OPERATOR_DECISION_COMPLETE_SCHEMA.to_owned(),
        decision_id: decision.decision_id.to_string(),
        decision_receipt_id: decision.receipt_id.to_string(),
        outcome_receipt_id: outcome.receipt_id.to_string(),
        post_state_snapshot_id,
        reward_ready: false,
        appended,
    })
}

pub fn certify_native_decision_graph_truth_link<S>(
    store: &S,
    request: NativeDecisionGraphTruthLinkRequest,
) -> Result<NativeDecisionGraphTruthLink, NativeOperatorDecisionError>
where
    S: PhoenixNativeDecisionStore + PhoenixGraphKernelStoreV2 + ?Sized,
{
    if request.schema_version != NATIVE_DECISION_TRUTH_LINK_SCHEMA
        || request.decision_receipt_id.trim().is_empty()
        || request.operator_mutation_receipt_id.trim().is_empty()
        || request.graph_truth_commit_id.trim().is_empty()
        || request.linked_at <= 0
        || request.stability_horizon_ms <= 0
    {
        return Err(NativeOperatorDecisionError::Invalid(
            "invalid decision-to-truth link request",
        ));
    }
    let decision = store
        .load_native_decision_receipt(&request.decision_receipt_id)?
        .ok_or(NativeOperatorDecisionError::Invalid(
            "decision receipt missing",
        ))?;
    let chosen = decision
        .candidates
        .get(decision.chosen_candidate_ordinal as usize)
        .ok_or(NativeOperatorDecisionError::Invalid(
            "chosen candidate missing",
        ))?;
    let outcomes = store.load_native_decision_outcome_receipts(&decision.receipt_id)?;
    let application = outcomes
        .iter()
        .filter(|outcome| outcome.candidate_action_identity == chosen.action_identity)
        .max_by_key(|outcome| outcome.observed_at)
        .ok_or(NativeOperatorDecisionError::Invalid(
            "operator application outcome missing",
        ))?;
    if !application
        .evidence_anchors
        .iter()
        .any(|evidence| evidence.evidence_id == request.operator_mutation_receipt_id)
    {
        return Err(NativeOperatorDecisionError::Invalid(
            "operator mutation receipt is not bound to the chosen outcome",
        ));
    }
    let commits = store.load_graph_truth_commits()?;
    let commit = commits
        .iter()
        .find(|commit| commit.header.commit_id == request.graph_truth_commit_id)
        .ok_or(NativeOperatorDecisionError::Invalid(
            "graph truth commit missing",
        ))?;
    validate_truth_link_receipts(
        commit,
        &decision.receipt_id,
        &request.operator_mutation_receipt_id,
    )?;
    if commit.header.committed_at < decision.observed_at
        || commit.header.committed_at < application.observed_at
        || commit.header.committed_at > request.linked_at
    {
        return Err(NativeOperatorDecisionError::Invalid(
            "graph truth commit is outside the decision outcome timeline",
        ));
    }
    let stability_eligible_at = commit
        .header
        .committed_at
        .checked_add(request.stability_horizon_ms)
        .ok_or(NativeOperatorDecisionError::Invalid(
            "stability horizon overflow",
        ))?;
    let link = NativeDecisionGraphTruthLink {
        schema_version: NATIVE_DECISION_TRUTH_LINK_SCHEMA.to_owned(),
        link_id: "pending".to_owned(),
        decision_id: decision.decision_id.to_string(),
        decision_receipt_id: decision.receipt_id.to_string(),
        chosen_action_identity: chosen.action_identity.to_string(),
        operator_mutation_receipt_id: request.operator_mutation_receipt_id,
        graph_truth_commit_id: commit.header.commit_id.to_string(),
        committed_at: commit.header.committed_at,
        linked_at: request.linked_at,
        stability_eligible_at,
        reward_complete: false,
    };
    content_address_native_decision_graph_truth_link(link)
        .map_err(|_| NativeOperatorDecisionError::Invalid("truth link identity"))
}

pub fn native_decision_census<S>(
    store: &S,
) -> Result<NativeDecisionCensus, NativeOperatorDecisionError>
where
    S: PhoenixNativeDecisionStore + PhoenixGraphKernelStoreV2 + ?Sized,
{
    let decisions = store.load_native_decision_receipts()?;
    let commits = store.load_graph_truth_commits()?;
    let mut census = NativeDecisionCensus {
        schema_version: NATIVE_DECISION_CENSUS_SCHEMA.to_owned(),
        behavior_labels: decisions.len() as u64,
        canonical_episode_assignment_labels: decisions
            .iter()
            .filter(|decision| {
                decision.task_family == NativeDecisionTaskFamily::CanonicalEpisodeAssignment
            })
            .count() as u64,
        operator_preference_labels: decisions
            .iter()
            .filter(|decision| {
                decision.authority_class == NativeDecisionAuthorityClass::OperatorPreference
            })
            .count() as u64,
        ..NativeDecisionCensus::default()
    };
    for decision in &decisions {
        let outcomes = store.load_native_decision_outcome_receipts(&decision.receipt_id)?;
        let chosen = &decision.candidates[decision.chosen_candidate_ordinal as usize];
        if decision.task_family == NativeDecisionTaskFamily::CanonicalEpisodeAssignment {
            census.canonical_episode_first_observed_at = Some(
                census
                    .canonical_episode_first_observed_at
                    .map_or(decision.observed_at, |prior| {
                        prior.min(decision.observed_at)
                    }),
            );
            census.canonical_episode_last_observed_at = Some(
                census
                    .canonical_episode_last_observed_at
                    .map_or(decision.observed_at, |prior| {
                        prior.max(decision.observed_at)
                    }),
            );
            let candidate_count = decision.candidates.len() as u64;
            census.canonical_episode_candidate_count_total = census
                .canonical_episode_candidate_count_total
                .saturating_add(candidate_count);
            census.canonical_episode_candidate_count_min =
                if census.canonical_episode_candidate_count_min == 0 {
                    candidate_count
                } else {
                    census
                        .canonical_episode_candidate_count_min
                        .min(candidate_count)
                };
            census.canonical_episode_candidate_count_max = census
                .canonical_episode_candidate_count_max
                .max(candidate_count);
            match &chosen.action {
                GraphDecisionAction::AttachToEpisode(_) => {
                    census.canonical_episode_attach_labels += 1
                }
                GraphDecisionAction::CreateEpisode(_) => {
                    census.canonical_episode_create_labels += 1
                }
                GraphDecisionAction::Abstain(_) => census.canonical_episode_abstain_labels += 1,
                _ => {}
            }
        }
        let chosen_terminal = outcomes
            .iter()
            .filter(|outcome| outcome.candidate_action_identity == chosen.action_identity)
            .max_by_key(|outcome| outcome.observed_at);
        if let Some(outcome) = chosen_terminal {
            census.execution_outcomes += 1;
            if outcome.reward_vector.is_some() {
                census.reward_complete_outcomes += 1;
            } else {
                census.reward_censored_outcomes += 1;
            }
            if commits.iter().any(|commit| {
                commit.header.receipt_ids.contains(&decision.receipt_id)
                    && outcomes.iter().any(|candidate_outcome| {
                        candidate_outcome.candidate_action_identity == chosen.action_identity
                            && candidate_outcome.evidence_anchors.iter().any(|evidence| {
                                commit.header.receipt_ids.contains(&evidence.evidence_id)
                            })
                    })
            }) {
                census.graph_truth_linked_decisions += 1;
            }
        }
        if decision.counterfactual_complete()
            && decision.candidates.iter().all(|candidate| {
                outcomes
                    .iter()
                    .filter(|outcome| {
                        outcome.candidate_action_identity == candidate.action_identity
                    })
                    .max_by_key(|outcome| outcome.observed_at)
                    .is_some_and(|outcome| outcome.reward_vector.is_some())
            })
        {
            census.counterfactual_ready_decisions += 1;
        }
    }
    Ok(census)
}

fn validate_truth_link_receipts(
    commit: &GraphTruthCommit,
    decision_receipt_id: &str,
    operator_mutation_receipt_id: &str,
) -> Result<(), NativeOperatorDecisionError> {
    let has = |expected: &str| {
        commit
            .header
            .receipt_ids
            .iter()
            .any(|receipt| receipt == expected)
    };
    if !has(decision_receipt_id) || !has(operator_mutation_receipt_id) {
        return Err(NativeOperatorDecisionError::Invalid(
            "graph truth commit does not carry both decision authority receipts",
        ));
    }
    Ok(())
}

fn begin_response(
    receipt: &NativeDecisionReceipt,
    appended: bool,
) -> Result<NativeOperatorDecisionBeginResponse, NativeOperatorDecisionError> {
    let chosen = receipt
        .candidates
        .get(receipt.chosen_candidate_ordinal as usize)
        .ok_or(NativeOperatorDecisionError::Invalid(
            "chosen candidate missing",
        ))?;
    Ok(NativeOperatorDecisionBeginResponse {
        schema_version: NATIVE_OPERATOR_DECISION_BEGIN_SCHEMA.to_owned(),
        decision_id: receipt.decision_id.to_string(),
        decision_receipt_id: receipt.receipt_id.to_string(),
        pre_state_snapshot_id: receipt.pre_state_snapshot_id.to_string(),
        candidate_set_id: receipt.candidate_set_id.to_string(),
        chosen_action_identity: chosen.action_identity.to_string(),
        candidate_count: receipt.candidates.len() as u32,
        appended,
    })
}

fn decision_evidence(request: &NativeOperatorDecisionBeginRequest) -> GraphDecisionEvidence {
    let ids = if request.source_receipt_ids.is_empty() {
        vec![format!("graph-review-row:{}", request.source_fingerprint)]
    } else {
        request.source_receipt_ids.clone()
    };
    ids.into_iter()
        .map(|evidence_id| GraphDecisionEvidenceRef {
            evidence_id: evidence_id.into(),
            authority_id: "graph_rebuild_live_contract".into(),
            available_at: request.source_snapshot_built_at,
        })
        .collect()
}

fn operator_action(
    decision: NativeOperatorReviewDecision,
    target_id: &str,
    header: GraphDecisionHeader,
    evidence: GraphDecisionEvidence,
) -> GraphDecisionAction {
    match decision {
        NativeOperatorReviewDecision::Accepted
        | NativeOperatorReviewDecision::PromotedToAnchor
        | NativeOperatorReviewDecision::CompiledToGraph => {
            GraphDecisionAction::AcceptDelta(AcceptDeltaAction {
                header,
                delta_id: target_id.into(),
                evidence,
            })
        }
        NativeOperatorReviewDecision::Rejected => {
            GraphDecisionAction::RejectDelta(RejectDeltaAction {
                header,
                delta_id: target_id.into(),
                reason: GraphDeltaRejectionReason::UnsupportedByEvidence,
                evidence,
            })
        }
        NativeOperatorReviewDecision::Deferred
        | NativeOperatorReviewDecision::Muted
        | NativeOperatorReviewDecision::LedgerOnly => {
            let reason = match decision {
                NativeOperatorReviewDecision::Muted => {
                    GraphDeltaDeferralReason::ConflictingAuthority
                }
                NativeOperatorReviewDecision::LedgerOnly => {
                    GraphDeltaDeferralReason::AwaitingHumanApproval
                }
                _ => GraphDeltaDeferralReason::InsufficientEvidence,
            };
            GraphDecisionAction::DeferDelta(DeferDeltaAction {
                header,
                delta_id: target_id.into(),
                reason,
                resume_after: None,
                evidence,
            })
        }
    }
}

fn operator_source_label(decision: NativeOperatorReviewDecision) -> &'static str {
    match decision {
        NativeOperatorReviewDecision::Accepted => "atlas-control:accepted",
        NativeOperatorReviewDecision::Rejected => "atlas-control:rejected",
        NativeOperatorReviewDecision::Deferred => "atlas-control:deferred",
        NativeOperatorReviewDecision::Muted => "atlas-control:muted",
        NativeOperatorReviewDecision::PromotedToAnchor => "atlas-control:promoted-to-anchor",
        NativeOperatorReviewDecision::CompiledToGraph => "atlas-control:compiled-to-graph",
        NativeOperatorReviewDecision::LedgerOnly => "atlas-control:ledger-only",
    }
}

fn validate_begin_request(
    request: &NativeOperatorDecisionBeginRequest,
) -> Result<(), NativeOperatorDecisionError> {
    if request.schema_version != NATIVE_OPERATOR_DECISION_BEGIN_SCHEMA
        || request.scope_key.trim().is_empty()
        || request.source_snapshot_id.trim().is_empty()
        || request.source_snapshot_built_at <= 0
        || request.source_snapshot_built_at > request.decided_at
        || request.source_authority_content_hash.trim().is_empty()
        || request.target_object_id.trim().is_empty()
        || request.target_object_kind.trim().is_empty()
        || request.source_fingerprint.trim().is_empty()
        || request.previous_state.trim().is_empty()
        || request.available_decisions.is_empty()
        || request.decided_at <= 0
        || request.operator_id.trim().is_empty()
    {
        return Err(NativeOperatorDecisionError::Invalid("begin contract"));
    }
    Ok(())
}

fn validate_complete_request(
    request: &NativeOperatorDecisionCompleteRequest,
) -> Result<(), NativeOperatorDecisionError> {
    if request.schema_version != NATIVE_OPERATOR_DECISION_COMPLETE_SCHEMA
        || request.decision_id.trim().is_empty()
        || request.decision_receipt_id.trim().is_empty()
        || request.post_snapshot_id.trim().is_empty()
        || request.post_snapshot_built_at <= 0
        || request.post_snapshot_built_at > request.completed_at
        || request.post_authority_content_hash.trim().is_empty()
        || request.operator_mutation_receipt_id.trim().is_empty()
        || request.completed_at <= 0
        || request.outcome_authority_id.trim().is_empty()
    {
        return Err(NativeOperatorDecisionError::Invalid("completion contract"));
    }
    Ok(())
}

fn content_id<T: Serialize>(value: &T) -> Result<String, NativeOperatorDecisionError> {
    Ok(format!("b3-{}", content_digest(value)?))
}

fn content_digest<T: Serialize>(value: &T) -> Result<String, NativeOperatorDecisionError> {
    let bytes = serde_json::to_vec(value)
        .map_err(|error| NativeOperatorDecisionError::Serialization(error.to_string()))?;
    Ok(blake3::hash(&bytes).to_hex().to_string())
}

#[cfg(test)]
#[path = "native_operator_decision_tests.rs"]
mod tests;
