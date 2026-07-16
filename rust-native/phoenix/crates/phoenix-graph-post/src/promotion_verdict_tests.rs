use phoenix_graph_kernel::{
    GraphProposalBatchReceipt, GraphProposalFeatures, GraphProposalObservation,
    GraphProposalStatus, GraphTruthAtomKey, GraphTruthCommit, KernelEdge, KernelEdgeType,
    KernelGraphLayer, KernelMutationBatch, KernelMutationScope, KernelRelationClass,
    KernelVertexId, GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
};
use phoenix_types::{
    GraphTruthCommitHeader, GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthDigest,
    GraphTruthKind, GraphTruthOperation, GraphTruthPlane, GraphTruthSourceGenerationRef,
};

use crate::promotion_verdict::{
    build_graph_promotion_verdict_certificate, GraphPromotionGateKind, GraphPromotionGateStatus,
    GraphPromotionUserOverride, GraphPromotionUserOverrideKind, GraphPromotionVerdictStatus,
};

#[test]
fn reviewed_support_with_evidence_is_acceptable_without_writes() {
    let receipt = receipt(
        "receipt-1",
        "proposal-1",
        GraphProposalStatus::ReviewedSupport,
        820,
        40,
    );

    let certificate =
        build_graph_promotion_verdict_certificate(&[receipt], &[], &[]).expect("build verdict");

    assert!(certificate.no_topology_writes);
    assert_eq!(certificate.audit.acceptable, 1);
    assert_eq!(certificate.audit.blocked, 0);
    let row = &certificate.rows[0];
    assert_eq!(row.status, GraphPromotionVerdictStatus::Acceptable);
    assert_eq!(row.apply_plan.operation, Some(GraphTruthOperation::Assert));
    assert_eq!(
        row.rollback_plan.operation,
        Some(GraphTruthOperation::Revert)
    );
    assert!(row.rollback_plan.available_after_commit);
    assert_gate(
        row,
        GraphPromotionGateKind::Evidence,
        GraphPromotionGateStatus::Pass,
    );
    assert_gate(
        row,
        GraphPromotionGateKind::NliFit,
        GraphPromotionGateStatus::Pass,
    );
}

#[test]
fn contradiction_blocks_promotion_even_with_witnesses() {
    let receipt = receipt(
        "receipt-1",
        "proposal-1",
        GraphProposalStatus::ReviewedContradiction,
        120,
        910,
    );

    let certificate =
        build_graph_promotion_verdict_certificate(&[receipt], &[], &[]).expect("build verdict");

    assert_eq!(certificate.audit.blocked, 1);
    assert_eq!(certificate.audit.contradiction_blocked, 1);
    let row = &certificate.rows[0];
    assert_eq!(row.status, GraphPromotionVerdictStatus::Blocked);
    assert_eq!(row.apply_plan.operation, None);
    assert_gate(
        row,
        GraphPromotionGateKind::Contradiction,
        GraphPromotionGateStatus::Block,
    );
}

#[test]
fn user_approval_can_accept_generated_candidate_after_hard_gates_pass() {
    let receipt = receipt(
        "receipt-1",
        "proposal-1",
        GraphProposalStatus::Generated,
        780,
        30,
    );
    let override_row = GraphPromotionUserOverride {
        receipt_id: "receipt-1".into(),
        proposal_id: "proposal-1".into(),
        kind: GraphPromotionUserOverrideKind::Approve,
        user_id: "user:1".into(),
        rationale: "manual review accepted evidence".into(),
    };

    let certificate = build_graph_promotion_verdict_certificate(&[receipt], &[], &[override_row])
        .expect("build verdict");

    assert_eq!(certificate.audit.acceptable, 1);
    assert_eq!(certificate.audit.user_overrides, 1);
    let row = &certificate.rows[0];
    assert_eq!(row.status, GraphPromotionVerdictStatus::Acceptable);
    assert_eq!(
        row.user_override,
        Some(GraphPromotionUserOverrideKind::Approve)
    );
    assert_gate(
        row,
        GraphPromotionGateKind::UserOverride,
        GraphPromotionGateStatus::Override,
    );
}

#[test]
fn active_commit_reports_rollback_plan() {
    let receipt = receipt(
        "receipt-1",
        "proposal-1",
        GraphProposalStatus::ReviewedSupport,
        820,
        40,
    );
    let commit = commit(
        "commit-1",
        "receipt-1",
        2,
        GraphTruthOperation::Assert,
        None,
        None,
    );

    let certificate = build_graph_promotion_verdict_certificate(&[receipt], &[commit], &[])
        .expect("build verdict");

    assert_eq!(certificate.audit.already_committed, 1);
    assert_eq!(certificate.audit.rollback_available, 1);
    let row = &certificate.rows[0];
    assert_eq!(row.status, GraphPromotionVerdictStatus::AlreadyCommitted);
    assert_eq!(row.apply_plan.operation, None);
    assert_eq!(
        row.rollback_plan.operation,
        Some(GraphTruthOperation::Revert)
    );
    assert_eq!(
        row.rollback_plan.reverses_commit_id.as_deref(),
        Some("commit-1")
    );
    assert!(row.rollback_plan.available_now);
}

fn receipt(
    id: &str,
    proposal_id: &str,
    status: GraphProposalStatus,
    support_millis: i16,
    contradiction_millis: i16,
) -> GraphProposalBatchReceipt {
    GraphProposalBatchReceipt {
        schema_version: GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
        receipt_id: id.into(),
        scope_key: "scope:test".into(),
        generation: 1,
        created_at: 1,
        compiler_policy: policy(),
        source_generations: [GraphTruthSourceGenerationRef {
            source_id: "semantic-graph:scope:test".into(),
            generation: 1,
        }]
        .into_iter()
        .collect(),
        model_id: Some("modernbert-nli".into()),
        proposals: vec![GraphProposalObservation {
            proposal_id: proposal_id.into(),
            atom: atom(),
            family: "stateSupport".into(),
            source_kind: "entity".into(),
            target_kind: "state".into(),
            truth: GraphTruthDescriptor {
                kind: GraphTruthKind::Semantic,
                plane: Some(GraphTruthPlane::WorldState),
            },
            status,
            evidence_refs: ["chunk:1", "chunk:2"].into_iter().map(Into::into).collect(),
            features: GraphProposalFeatures([
                900,
                900,
                support_millis,
                contradiction_millis,
                support_millis.saturating_sub(contradiction_millis),
                31,
                16,
                200,
                1000,
                1000,
                0,
                i16::from(status == GraphProposalStatus::ReviewedSupport) * 1000,
                i16::from(status == GraphProposalStatus::ReviewedContradiction) * 1000,
                i16::from(status == GraphProposalStatus::Deferred) * 1000,
                i16::from(status == GraphProposalStatus::Generated) * 1000,
                1000,
            ]),
            shadow_score_millis: Some(910),
        }],
    }
}

fn commit(
    id: &str,
    receipt_id: &str,
    generation: u64,
    operation: GraphTruthOperation,
    predecessor: Option<&str>,
    reverses: Option<&str>,
) -> GraphTruthCommit {
    let mut header = GraphTruthCommitHeader {
        commit_id: id.into(),
        generation,
        operation,
        truth: GraphTruthDescriptor {
            kind: GraphTruthKind::Semantic,
            plane: Some(GraphTruthPlane::WorldState),
        },
        compiler_policy: policy(),
        idempotency_hash: GraphTruthDigest([generation as u8; 32]),
        committed_at: generation as i64,
        reverses_commit_id: reverses.map(Into::into),
        ..GraphTruthCommitHeader::default()
    };
    header
        .source_generations
        .push(GraphTruthSourceGenerationRef {
            source_id: "semantic-graph:scope:test".into(),
            generation: 1,
        });
    header.receipt_ids.push(receipt_id.into());
    if let Some(predecessor) = predecessor {
        header.predecessor_commit_ids.push(predecessor.into());
    }
    let has_batch = matches!(
        operation,
        GraphTruthOperation::Assert | GraphTruthOperation::Supersede
    );
    GraphTruthCommit {
        header,
        batch: KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Projection {
                scope_key: "scope:test".to_owned(),
            },
            recorded_at: Some(generation as i64),
            vertices: Vec::new(),
            edges: has_batch
                .then(|| KernelEdge {
                    source_id: KernelVertexId("entity:a".to_owned()),
                    target_id: KernelVertexId("state:b".to_owned()),
                    edge_type: KernelEdgeType("semantic::state_support".to_owned()),
                    relation_class: KernelRelationClass::Semantic,
                    layer: KernelGraphLayer::Asserted,
                    ..KernelEdge::default()
                })
                .into_iter()
                .collect(),
        },
    }
}

fn atom() -> GraphTruthAtomKey {
    GraphTruthAtomKey::edge("entity:a", "state:b", "semantic::state_support")
}

fn policy() -> GraphTruthCompilerPolicy {
    GraphTruthCompilerPolicy {
        compiler_id: "phoenix-graph-post".into(),
        compiler_version: "0.1.1".into(),
        policy_id: "graph-post-proposal:semantic-phase5".into(),
        policy_version: "1".into(),
    }
}

fn assert_gate(
    row: &crate::promotion_verdict::GraphPromotionVerdictRow,
    kind: GraphPromotionGateKind,
    status: GraphPromotionGateStatus,
) {
    assert!(
        row.gates
            .iter()
            .any(|gate| gate.kind == kind && gate.status == status),
        "missing gate {kind:?} with status {status:?}: {:?}",
        row.gates
    );
}
