use phoenix_graph_kernel::{
    GraphTruthCommit, KernelGraphLayer, KernelMutationBatch, KernelMutationScope, KernelVertex,
    KernelVertexId,
};
use phoenix_store_native_core::{PhoenixGraphKernelStoreV2, PhoenixNativeDecisionStore};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{
    GraphDecisionEvidenceRef, GraphTruthCommitHeader, GraphTruthCompilerPolicy,
    GraphTruthDescriptor, GraphTruthDigest, GraphTruthKind, GraphTruthOperation, GraphTruthPlane,
    GraphTruthSourceGenerationRef, CANONICAL_REWARD_STABILITY_HORIZON_MS,
};
use serde_json::json;
use tempfile::tempdir;

use super::*;
use crate::{
    begin_native_operator_decision, certify_native_decision_graph_truth_link,
    complete_native_operator_decision, NativeOperatorDecisionBeginRequest,
    NativeOperatorDecisionCompleteRequest, NativeOperatorReviewDecision,
    NATIVE_DECISION_TRUTH_LINK_SCHEMA, NATIVE_OPERATOR_DECISION_BEGIN_SCHEMA,
    NATIVE_OPERATOR_DECISION_COMPLETE_SCHEMA,
};

#[test]
fn dimension_observations_require_exact_truth_authority_and_remain_partial() {
    let root = tempdir().expect("store root");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    let begin = begin_native_operator_decision(&store, begin_request()).expect("begin decision");
    complete_native_operator_decision(&store, complete_request(&begin)).expect("complete decision");
    let commit = truth_commit(&begin.decision_receipt_id, 202);
    store
        .append_graph_truth_commit(&commit)
        .expect("append graph truth");
    let link_request = NativeDecisionGraphTruthLinkRequest {
        schema_version: NATIVE_DECISION_TRUTH_LINK_SCHEMA.to_owned(),
        decision_receipt_id: begin.decision_receipt_id.clone(),
        operator_mutation_receipt_id: "operator-receipt:reward:1".to_owned(),
        graph_truth_commit_id: commit.header.commit_id.to_string(),
        linked_at: 202,
        stability_horizon_ms: CANONICAL_REWARD_STABILITY_HORIZON_MS,
    };
    let link = certify_native_decision_graph_truth_link(&store, link_request.clone())
        .expect("certify truth link");

    let human = store
        .load_native_decision_reward_observations(&begin.decision_receipt_id)
        .expect("load canonical human observation")
        .into_iter()
        .find(|row| row.dimension == GraphDecisionRewardDimension::HumanAcceptance)
        .expect("canonical human observation");

    let mut early_stability = observation_request(
        link_request.clone(),
        &link.link_id,
        GraphDecisionRewardDimension::FutureStability,
        NativeDecisionRewardObservationOperation::Observe,
        Some(1_000_000),
        link.stability_eligible_at - 1,
        NativeDecisionAuthorityClass::AuthoritativeGraphOutcome,
        "stability-observation:early",
        None,
    );
    early_stability.evidence_anchors[0].available_at = link.stability_eligible_at - 1;
    assert!(record_native_reward_observation(&store, early_stability).is_err());

    store
        .reconcile_canonical_reward_producers(link.stability_eligible_at)
        .expect("record mature stability");
    let stability = store
        .load_native_decision_reward_observations(&begin.decision_receipt_id)
        .expect("load stability observation")
        .into_iter()
        .find(|row| row.dimension == GraphDecisionRewardDimension::FutureStability)
        .expect("future stability observation");

    let census = native_reward_observation_census(&store).expect("reward census");
    assert_eq!(census.observation_receipts, 2);
    assert_eq!(census.active_human_acceptance, 1);
    assert_eq!(census.active_future_stability, 1);
    assert_eq!(census.partially_observed_decisions, 1);
    assert_eq!(census.fully_observed_decisions, 0);

    drop(store);
    let reopened = PhoenixOvergraphStore::open(root.path()).expect("reopen store");
    let observations = reopened
        .load_native_decision_reward_observations(&begin.decision_receipt_id)
        .expect("reopen observations");
    assert_eq!(observations.len(), 2);
    assert_eq!(observations[0].receipt_id, human.receipt_id);
    assert_eq!(observations[1].receipt_id, stability.receipt_id);
}

#[test]
fn revision_lineage_and_same_link_identity_fail_closed() {
    let root = tempdir().expect("store root");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    let begin = begin_native_operator_decision(&store, begin_request()).expect("begin decision");
    complete_native_operator_decision(&store, complete_request(&begin)).expect("complete decision");
    let commit = truth_commit(&begin.decision_receipt_id, 202);
    store
        .append_graph_truth_commit(&commit)
        .expect("append graph truth");
    let link_request = NativeDecisionGraphTruthLinkRequest {
        schema_version: NATIVE_DECISION_TRUTH_LINK_SCHEMA.to_owned(),
        decision_receipt_id: begin.decision_receipt_id,
        operator_mutation_receipt_id: "operator-receipt:reward:1".to_owned(),
        graph_truth_commit_id: commit.header.commit_id.to_string(),
        linked_at: 202,
        stability_horizon_ms: CANONICAL_REWARD_STABILITY_HORIZON_MS,
    };
    let link = certify_native_decision_graph_truth_link(&store, link_request.clone())
        .expect("certify truth link");
    let mut wrong_link = observation_request(
        link_request.clone(),
        &link.link_id,
        GraphDecisionRewardDimension::HumanAcceptance,
        NativeDecisionRewardObservationOperation::Observe,
        Some(1_000_000),
        204,
        NativeDecisionAuthorityClass::OperatorPreference,
        "operator-evaluation:wrong",
        None,
    );
    wrong_link.truth_link_id = format!("b3-{}", "0".repeat(64));
    assert!(record_native_reward_observation(&store, wrong_link).is_err());

    let first = store
        .load_native_decision_reward_observations(&link_request.decision_receipt_id)
        .expect("load canonical human observation")
        .into_iter()
        .find(|row| row.dimension == GraphDecisionRewardDimension::HumanAcceptance)
        .expect("canonical human observation");
    let revision = record_native_reward_observation(
        &store,
        observation_request(
            link_request,
            &link.link_id,
            GraphDecisionRewardDimension::HumanAcceptance,
            NativeDecisionRewardObservationOperation::Revise,
            Some(-1_000_000),
            205,
            NativeDecisionAuthorityClass::OperatorPreference,
            "operator-evaluation:2",
            Some(first.receipt_id.to_string()),
        ),
    )
    .expect("revision");
    assert_ne!(revision.receipt_id, first.receipt_id);
    let census = native_reward_observation_census(&store).expect("revised census");
    assert_eq!(census.observation_receipts, 2);
    assert_eq!(census.active_human_acceptance, 1);
}

fn observation_request(
    truth_link: NativeDecisionGraphTruthLinkRequest,
    truth_link_id: &str,
    dimension: GraphDecisionRewardDimension,
    operation: NativeDecisionRewardObservationOperation,
    score_micros: Option<i32>,
    observed_at: i64,
    authority_class: NativeDecisionAuthorityClass,
    evidence_id: &str,
    predecessor_observation_receipt_id: Option<String>,
) -> NativeRewardObservationRequest {
    NativeRewardObservationRequest {
        schema_version: NATIVE_REWARD_OBSERVATION_SCHEMA.to_owned(),
        truth_link,
        truth_link_id: truth_link_id.to_owned(),
        dimension,
        operation,
        score_micros,
        observed_at,
        authority_class,
        authority_id: match authority_class {
            NativeDecisionAuthorityClass::OperatorPreference => "operator:local-user",
            NativeDecisionAuthorityClass::AuthoritativeGraphOutcome => "graph:stability-auditor",
            NativeDecisionAuthorityClass::CompilerInference => "compiler:invalid",
        }
        .to_owned(),
        predecessor_observation_receipt_id,
        evidence_anchors: vec![GraphDecisionEvidenceRef {
            evidence_id: evidence_id.into(),
            authority_id: "native-reward-producer".into(),
            available_at: observed_at,
        }],
    }
}

fn begin_request() -> NativeOperatorDecisionBeginRequest {
    NativeOperatorDecisionBeginRequest {
        schema_version: NATIVE_OPERATOR_DECISION_BEGIN_SCHEMA.to_owned(),
        scope_key: "scope:reward".to_owned(),
        source_snapshot_id: "snapshot:reward:1".to_owned(),
        source_snapshot_built_at: 100,
        source_authority_content_hash: "authority:reward:1".to_owned(),
        target_object_id: "fact:reward:1".to_owned(),
        target_object_kind: "graph_fact_candidate".to_owned(),
        source_fingerprint: "fingerprint:reward:1".to_owned(),
        source_receipt_ids: vec!["source:reward:1".to_owned()],
        previous_state: "proposed".to_owned(),
        available_decisions: vec![
            NativeOperatorReviewDecision::Accepted,
            NativeOperatorReviewDecision::Rejected,
        ],
        selected_decision: NativeOperatorReviewDecision::Accepted,
        decided_at: 200,
        operator_id: "operator:local-user".to_owned(),
    }
}

fn complete_request(
    begin: &crate::NativeOperatorDecisionBeginResponse,
) -> NativeOperatorDecisionCompleteRequest {
    NativeOperatorDecisionCompleteRequest {
        schema_version: NATIVE_OPERATOR_DECISION_COMPLETE_SCHEMA.to_owned(),
        decision_id: begin.decision_id.clone(),
        decision_receipt_id: begin.decision_receipt_id.clone(),
        post_snapshot_id: "snapshot:reward:2".to_owned(),
        post_snapshot_built_at: 201,
        post_authority_content_hash: "authority:reward:2".to_owned(),
        operator_mutation_receipt_id: "operator-receipt:reward:1".to_owned(),
        completed_at: 201,
        outcome_authority_id: "operator:local-user".to_owned(),
        applied: true,
    }
}

fn truth_commit(decision_receipt_id: &str, committed_at: i64) -> GraphTruthCommit {
    GraphTruthCommit {
        header: GraphTruthCommitHeader {
            commit_id: "commit:reward:linked".into(),
            generation: 1,
            operation: GraphTruthOperation::Assert,
            truth: GraphTruthDescriptor {
                kind: GraphTruthKind::Assertion,
                plane: Some(GraphTruthPlane::WorldState),
            },
            source_generations: [GraphTruthSourceGenerationRef {
                source_id: "scope:reward".into(),
                generation: 1,
            }]
            .into_iter()
            .collect(),
            receipt_ids: [
                decision_receipt_id.into(),
                "operator-receipt:reward:1".into(),
            ]
            .into_iter()
            .collect(),
            compiler_policy: GraphTruthCompilerPolicy {
                compiler_id: "atlas-control".into(),
                compiler_version: "1".into(),
                policy_id: "native-reward-observation-v1".into(),
                policy_version: "1".into(),
            },
            idempotency_hash: GraphTruthDigest([7; 32]),
            committed_at,
            ..GraphTruthCommitHeader::default()
        },
        batch: KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Projection {
                scope_key: "scope:reward".to_owned(),
            },
            recorded_at: Some(committed_at),
            vertices: vec![KernelVertex {
                id: KernelVertexId("fact:reward:1".to_owned()),
                kind: "claim".to_owned(),
                value: json!({"status": "accepted"}),
                ..KernelVertex::default()
            }],
            edges: Vec::new(),
        },
    }
}
