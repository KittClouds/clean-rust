use phoenix_graph_kernel::{
    GraphTruthCommit, KernelGraphLayer, KernelMutationBatch, KernelMutationScope, KernelVertex,
    KernelVertexId,
};
use phoenix_store_native_core::{PhoenixGraphKernelStoreV2, PhoenixNativeDecisionStore};
use phoenix_types::{
    certify_native_decision_outcome_receipt, GraphDecisionEvidenceRef, GraphTruthCommitHeader,
    GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthDigest, GraphTruthKind,
    GraphTruthOperation, GraphTruthSourceGenerationRef, NativeDecisionAuthorityClass,
    NativeDecisionEffect, NativeDecisionOutcomeOperation, NativeDecisionOutcomeReceipt,
    CANONICAL_REWARD_STABILITY_HORIZON_MS, NATIVE_DECISION_OUTCOME_SCHEMA_VERSION,
};
use serde_json::json;
use tempfile::tempdir;

use super::native_decision_persistence_tests::{decision, hard_constraints};
use super::PhoenixOvergraphStore;

#[test]
fn ordinary_graph_truth_commits_do_not_open_the_native_decision_log() {
    let root = tempdir().expect("ordinary commit store");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    let commit = truth_commit(
        "commit:ordinary:1",
        1,
        GraphTruthOperation::Assert,
        100,
        Some("claim:ordinary"),
        &[],
        &[],
    );
    store
        .append_graph_truth_commit(&commit)
        .expect("append ordinary commit");
    assert!(!store.native_decision_receipt_log_path().exists());
}

#[test]
fn canonical_commit_emits_human_evaluation_then_restart_observer_emits_stability() {
    let root = tempdir().expect("reward producer store");
    let decision = decision(1);
    let operator_receipt = "operator-mutation:1";
    let commit = truth_commit(
        "commit:canonical:1",
        1,
        GraphTruthOperation::Assert,
        200,
        Some("claim:1"),
        &[decision.receipt_id.as_str(), operator_receipt],
        &[],
    );
    {
        let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
        store
            .append_native_decision_receipt(&decision)
            .expect("append decision");
        store
            .append_native_decision_outcome_receipt(&operator_outcome(
                &decision,
                operator_receipt,
                150,
            ))
            .expect("append outcome");
        store
            .append_graph_truth_commit(&commit)
            .expect("append canonical commit");

        let evidence = store
            .load_native_decision_reward_evidence_for_decision(&decision.receipt_id)
            .expect("load evidence");
        let observations = store
            .load_native_decision_reward_observations(&decision.receipt_id)
            .expect("load observations");
        assert_eq!(evidence.len(), 1);
        assert_eq!(observations.len(), 1);
        assert_eq!(evidence[0].score_micros, 1_000_000);
        assert_eq!(
            observations[0].evidence_anchors[0].evidence_id,
            evidence[0].receipt_id
        );
    }

    let store = PhoenixOvergraphStore::open(root.path()).expect("restart store");
    let horizon = commit.header.committed_at + CANONICAL_REWARD_STABILITY_HORIZON_MS;
    let report = store
        .reconcile_canonical_reward_producers(horizon)
        .expect("observe horizon");
    assert_eq!(report.stability_evidence_appended, 1);
    assert_eq!(report.stability_observations_appended, 1);
    let evidence = store
        .load_native_decision_reward_evidence_for_decision(&decision.receipt_id)
        .expect("load restarted evidence");
    assert_eq!(evidence.len(), 2);
    assert_eq!(evidence[1].score_micros, 1_000_000);

    let retry = store
        .reconcile_canonical_reward_producers(horizon + 1_000)
        .expect("idempotent observer retry");
    assert_eq!(retry.stability_evidence_appended, 0);
    assert_eq!(retry.stability_observations_appended, 0);
}

#[test]
fn horizon_cut_scores_a_pre_horizon_retraction_as_unstable() {
    let root = tempdir().expect("reward retraction store");
    let decision = decision(2);
    let operator_receipt = "operator-mutation:2";
    let asserted = truth_commit(
        "commit:canonical:2",
        1,
        GraphTruthOperation::Assert,
        300,
        Some("claim:2"),
        &[decision.receipt_id.as_str(), operator_receipt],
        &[],
    );
    let retracted = truth_commit(
        "commit:canonical:2:retract",
        2,
        GraphTruthOperation::Retract,
        400,
        None,
        &[],
        &[asserted.header.commit_id.as_str()],
    );
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    store
        .append_native_decision_receipt(&decision)
        .expect("append decision");
    store
        .append_native_decision_outcome_receipt(&operator_outcome(&decision, operator_receipt, 250))
        .expect("append outcome");
    store
        .append_graph_truth_commit(&asserted)
        .expect("append asserted");
    store
        .append_graph_truth_commit(&retracted)
        .expect("append retraction");

    let horizon = asserted.header.committed_at + CANONICAL_REWARD_STABILITY_HORIZON_MS;
    store
        .reconcile_canonical_reward_producers(horizon)
        .expect("observe retracted horizon");
    let evidence = store
        .load_native_decision_reward_evidence_for_decision(&decision.receipt_id)
        .expect("load evidence");
    assert_eq!(evidence.len(), 2);
    assert_eq!(evidence[1].score_micros, -1_000_000);
    assert!(evidence[1]
        .source_receipt_ids
        .contains(&retracted.header.commit_id));
}

fn operator_outcome(
    decision: &phoenix_types::NativeDecisionReceipt,
    operator_receipt: &str,
    observed_at: i64,
) -> NativeDecisionOutcomeReceipt {
    certify_native_decision_outcome_receipt(NativeDecisionOutcomeReceipt {
        schema_version: NATIVE_DECISION_OUTCOME_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        decision_receipt_id: decision.receipt_id.clone(),
        decision_id: decision.decision_id.clone(),
        candidate_action_identity: decision.candidates[0].action_identity.clone(),
        operation: NativeDecisionOutcomeOperation::Observe,
        observed_at,
        authority_class: NativeDecisionAuthorityClass::OperatorPreference,
        outcome_authority_id: "operator".into(),
        reward_vector: None,
        hard_constraints: hard_constraints(observed_at),
        effect: Some(NativeDecisionEffect::NoChange {
            post_state_snapshot_id: digest('8').into(),
        }),
        predecessor_outcome_receipt_id: None,
        evidence_anchors: vec![GraphDecisionEvidenceRef {
            evidence_id: operator_receipt.into(),
            authority_id: "operator".into(),
            available_at: observed_at,
        }],
    })
    .expect("operator outcome")
}

fn truth_commit(
    id: &str,
    generation: u64,
    operation: GraphTruthOperation,
    committed_at: i64,
    vertex_id: Option<&str>,
    receipt_ids: &[&str],
    predecessors: &[&str],
) -> GraphTruthCommit {
    GraphTruthCommit {
        header: GraphTruthCommitHeader {
            commit_id: id.into(),
            generation,
            operation,
            truth: GraphTruthDescriptor {
                kind: GraphTruthKind::Structural,
                plane: None,
            },
            source_generations: vec![GraphTruthSourceGenerationRef {
                source_id: "source:canonical-reward".into(),
                generation,
            }]
            .into(),
            receipt_ids: receipt_ids.iter().copied().map(Into::into).collect(),
            compiler_policy: GraphTruthCompilerPolicy {
                compiler_id: "canonical-reward-test".into(),
                compiler_version: "1".into(),
                policy_id: "canonical-reward-test".into(),
                policy_version: "1".into(),
            },
            predecessor_commit_ids: predecessors.iter().copied().map(Into::into).collect(),
            reverses_commit_id: None,
            idempotency_hash: GraphTruthDigest([generation as u8; 32]),
            committed_at,
            ..GraphTruthCommitHeader::default()
        },
        batch: KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Full,
            recorded_at: Some(committed_at),
            vertices: vertex_id
                .into_iter()
                .map(|value| KernelVertex {
                    id: KernelVertexId(value.to_owned()),
                    kind: "claim".to_owned(),
                    value: json!({"id": value}),
                    attributes: json!({}),
                    ..KernelVertex::default()
                })
                .collect(),
            edges: Vec::new(),
        },
    }
}

fn digest(byte: char) -> String {
    format!("b3-{}", byte.to_string().repeat(64))
}
