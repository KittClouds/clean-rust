use phoenix_graph_kernel::{
    GraphTruthCommit, KernelGraphLayer, KernelMutationBatch, KernelMutationScope, KernelVertex,
    KernelVertexId,
};
use phoenix_store_native_core::{PhoenixGraphKernelStoreV2, PhoenixNativeDecisionStore};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{
    GraphTruthCommitHeader, GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthDigest,
    GraphTruthKind, GraphTruthOperation, GraphTruthPlane, GraphTruthSourceGenerationRef,
};
use serde_json::json;
use tempfile::tempdir;

use super::*;

fn begin_request(selected: NativeOperatorReviewDecision) -> NativeOperatorDecisionBeginRequest {
    NativeOperatorDecisionBeginRequest {
        schema_version: NATIVE_OPERATOR_DECISION_BEGIN_SCHEMA.to_owned(),
        scope_key: "scope:global".to_owned(),
        source_snapshot_id: "snapshot:42".to_owned(),
        source_snapshot_built_at: 100,
        source_authority_content_hash: "fnv64-authority".to_owned(),
        target_object_id: "fact:iris-lives-in-arcadia".to_owned(),
        target_object_kind: "graph_fact_candidate".to_owned(),
        source_fingerprint: "fact-fingerprint-42".to_owned(),
        source_receipt_ids: vec!["source-receipt-42".to_owned()],
        previous_state: "proposed".to_owned(),
        available_decisions: vec![
            NativeOperatorReviewDecision::Deferred,
            NativeOperatorReviewDecision::Rejected,
            NativeOperatorReviewDecision::Accepted,
        ],
        selected_decision: selected,
        decided_at: 200,
        operator_id: "operator:local-user".to_owned(),
    }
}

fn complete_request(
    begin: &NativeOperatorDecisionBeginResponse,
) -> NativeOperatorDecisionCompleteRequest {
    NativeOperatorDecisionCompleteRequest {
        schema_version: NATIVE_OPERATOR_DECISION_COMPLETE_SCHEMA.to_owned(),
        decision_id: begin.decision_id.clone(),
        decision_receipt_id: begin.decision_receipt_id.clone(),
        post_snapshot_id: "snapshot:42".to_owned(),
        post_snapshot_built_at: 100,
        post_authority_content_hash: "fnv64-authority".to_owned(),
        operator_mutation_receipt_id: "operator-receipt:42".to_owned(),
        completed_at: 201,
        outcome_authority_id: "operator:local-user".to_owned(),
        applied: true,
    }
}

#[test]
fn operator_review_is_captured_before_effect_and_reopens_as_a_real_behavior_label() {
    let root = tempdir().expect("store root");
    let begin;
    let complete;
    {
        let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
        begin = begin_native_operator_decision(
            &store,
            begin_request(NativeOperatorReviewDecision::Accepted),
        )
        .expect("begin decision");
        assert!(begin.appended);
        assert_eq!(begin.candidate_count, 4);
        let retry = begin_native_operator_decision(
            &store,
            begin_request(NativeOperatorReviewDecision::Accepted),
        )
        .expect("retry decision");
        assert!(!retry.appended);
        assert_eq!(retry.decision_receipt_id, begin.decision_receipt_id);

        complete = complete_native_operator_decision(&store, complete_request(&begin))
            .expect("complete decision");
        assert!(complete.appended);
        assert!(!complete.reward_ready);
        let retry = complete_native_operator_decision(&store, complete_request(&begin))
            .expect("retry completion");
        assert!(!retry.appended);
        assert_eq!(retry.outcome_receipt_id, complete.outcome_receipt_id);
    }

    let store = PhoenixOvergraphStore::open(root.path()).expect("reopen store");
    let decision = store
        .load_native_decision_receipt(&begin.decision_receipt_id)
        .expect("load decision")
        .expect("decision exists");
    assert_eq!(decision.decision_id, begin.decision_id);
    assert_eq!(decision.chosen_candidate_ordinal, 0);
    let outcomes = store
        .load_native_decision_outcome_receipts(&begin.decision_receipt_id)
        .expect("load outcomes");
    assert_eq!(outcomes.len(), 1);
    assert_eq!(outcomes[0].receipt_id, complete.outcome_receipt_id);
    assert!(outcomes[0].reward_vector.is_none());

    let census = native_decision_census(&store).expect("decision census");
    assert_eq!(census.behavior_labels, 1);
    assert_eq!(census.operator_preference_labels, 1);
    assert_eq!(census.execution_outcomes, 1);
    assert_eq!(census.reward_censored_outcomes, 1);
    assert_eq!(census.reward_complete_outcomes, 0);
    assert_eq!(census.counterfactual_ready_decisions, 0);
}

#[test]
fn unavailable_hidden_choice_and_mismatched_completion_fail_before_append() {
    let root = tempdir().expect("store root");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    let mut invalid = begin_request(NativeOperatorReviewDecision::Accepted);
    invalid.available_decisions = vec![NativeOperatorReviewDecision::Rejected];
    assert!(matches!(
        begin_native_operator_decision(&store, invalid),
        Err(NativeOperatorDecisionError::Invalid(_))
    ));
    assert!(store
        .load_native_decision_receipts()
        .expect("load empty decisions")
        .is_empty());

    let begin = begin_native_operator_decision(
        &store,
        begin_request(NativeOperatorReviewDecision::Rejected),
    )
    .expect("begin valid decision");
    let mut completion = complete_request(&begin);
    completion.decision_id = "operator:wrong".to_owned();
    assert!(matches!(
        complete_native_operator_decision(&store, completion),
        Err(NativeOperatorDecisionError::Invalid(_))
    ));
    assert!(store
        .load_native_decision_outcome_receipts(&begin.decision_receipt_id)
        .expect("load empty outcomes")
        .is_empty());
}

#[test]
fn candidate_generator_input_is_independent_of_the_selected_label() {
    let left = tempdir().expect("left store");
    let right = tempdir().expect("right store");
    let left_store = PhoenixOvergraphStore::open(left.path()).expect("open left");
    let right_store = PhoenixOvergraphStore::open(right.path()).expect("open right");
    let left_begin = begin_native_operator_decision(
        &left_store,
        begin_request(NativeOperatorReviewDecision::Accepted),
    )
    .expect("accepted decision");
    let right_begin = begin_native_operator_decision(
        &right_store,
        begin_request(NativeOperatorReviewDecision::Rejected),
    )
    .expect("rejected decision");
    let left_receipt = left_store
        .load_native_decision_receipt(&left_begin.decision_receipt_id)
        .unwrap()
        .unwrap();
    let right_receipt = right_store
        .load_native_decision_receipt(&right_begin.decision_receipt_id)
        .unwrap()
        .unwrap();
    assert_eq!(
        left_receipt.generator_input_id,
        right_receipt.generator_input_id
    );
    assert_ne!(left_receipt.decision_id, right_receipt.decision_id);
}

#[test]
fn graph_truth_link_requires_both_immutable_authority_receipts_and_never_completes_reward() {
    let root = tempdir().expect("store root");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    let begin = begin_native_operator_decision(
        &store,
        begin_request(NativeOperatorReviewDecision::Accepted),
    )
    .expect("begin decision");
    complete_native_operator_decision(&store, complete_request(&begin)).expect("complete decision");

    let operator_receipt = "operator-receipt:42";
    let commit = truth_commit(&begin.decision_receipt_id, operator_receipt, 202);
    store
        .append_graph_truth_commit(&commit)
        .expect("append linked truth");
    let link = certify_native_decision_graph_truth_link(
        &store,
        NativeDecisionGraphTruthLinkRequest {
            schema_version: NATIVE_DECISION_TRUTH_LINK_SCHEMA.to_owned(),
            decision_receipt_id: begin.decision_receipt_id.clone(),
            operator_mutation_receipt_id: operator_receipt.to_owned(),
            graph_truth_commit_id: commit.header.commit_id.to_string(),
            linked_at: 203,
            stability_horizon_ms: 86_400_000,
        },
    )
    .expect("certify link");
    assert!(link.link_id.starts_with("b3-"));
    assert_eq!(link.stability_eligible_at, 86_400_202);
    assert!(!link.reward_complete);

    let census = native_decision_census(&store).expect("linked census");
    assert_eq!(census.graph_truth_linked_decisions, 1);
    assert_eq!(census.reward_complete_outcomes, 0);

    let mut unlinked = truth_commit(&begin.decision_receipt_id, "wrong-receipt", 204);
    unlinked.header.commit_id = "commit:unlinked".into();
    unlinked.header.generation = 2;
    unlinked.header.idempotency_hash = GraphTruthDigest([2; 32]);
    assert!(store.append_graph_truth_commit(&unlinked).is_err());
    assert!(store
        .load_graph_truth_commit(&unlinked.header.commit_id)
        .expect("load durable unlinked truth")
        .is_some());
    assert!(certify_native_decision_graph_truth_link(
        &store,
        NativeDecisionGraphTruthLinkRequest {
            schema_version: NATIVE_DECISION_TRUTH_LINK_SCHEMA.to_owned(),
            decision_receipt_id: begin.decision_receipt_id,
            operator_mutation_receipt_id: operator_receipt.to_owned(),
            graph_truth_commit_id: unlinked.header.commit_id.to_string(),
            linked_at: 205,
            stability_horizon_ms: 86_400_000,
        },
    )
    .is_err());
}

fn truth_commit(
    decision_receipt_id: &str,
    operator_receipt_id: &str,
    committed_at: i64,
) -> GraphTruthCommit {
    GraphTruthCommit {
        header: GraphTruthCommitHeader {
            commit_id: "commit:linked".into(),
            generation: 1,
            operation: GraphTruthOperation::Assert,
            truth: GraphTruthDescriptor {
                kind: GraphTruthKind::Assertion,
                plane: Some(GraphTruthPlane::WorldState),
            },
            source_generations: [GraphTruthSourceGenerationRef {
                source_id: "scope:global".into(),
                generation: 1,
            }]
            .into_iter()
            .collect(),
            receipt_ids: [decision_receipt_id.into(), operator_receipt_id.into()]
                .into_iter()
                .collect(),
            compiler_policy: GraphTruthCompilerPolicy {
                compiler_id: "atlas-control".into(),
                compiler_version: "1".into(),
                policy_id: "decision-truth-link-v1".into(),
                policy_version: "1".into(),
            },
            idempotency_hash: GraphTruthDigest([1; 32]),
            committed_at,
            ..GraphTruthCommitHeader::default()
        },
        batch: KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Projection {
                scope_key: "scope:global".to_owned(),
            },
            recorded_at: Some(committed_at),
            vertices: vec![KernelVertex {
                id: KernelVertexId("fact:iris-lives-in-arcadia".to_owned()),
                kind: "claim".to_owned(),
                value: json!({"status": "accepted"}),
                ..KernelVertex::default()
            }],
            edges: Vec::new(),
        },
    }
}
