use phoenix_types::{
    GraphTruthCommitHeader, GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthDigest,
    GraphTruthKind, GraphTruthOperation, GraphTruthPlane, GraphTruthSourceGenerationRef,
};

use crate::{
    project_graph_proposal_outcomes, DiscoveryPathProposalOrigin, GraphProposalBatchReceipt,
    GraphProposalFeatures, GraphProposalObservation, GraphProposalOutcomeKind,
    GraphProposalReceiptError, GraphProposalStatus, GraphTruthAtomKey, GraphTruthCommit,
    KernelEdge, KernelEdgeType, KernelGraphLayer, KernelMutationBatch, KernelMutationScope,
    KernelRelationClass, KernelVertexId, GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
};

#[test]
fn proposal_outcomes_follow_canonical_commit_lineage() {
    let old_receipt = receipt("receipt-old", "proposal-old", 1);
    let new_receipt = receipt("receipt-new", "proposal-new", 2);
    let commits = vec![
        commit(
            "commit-old",
            1,
            GraphTruthOperation::Assert,
            Some("receipt-old"),
            None,
            None,
        ),
        commit(
            "commit-new",
            2,
            GraphTruthOperation::Supersede,
            Some("receipt-new"),
            Some("commit-old"),
            None,
        ),
    ];
    let outcomes = project_graph_proposal_outcomes(&[old_receipt, new_receipt], &commits)
        .expect("project outcomes");
    assert_eq!(outcomes[0].outcome, GraphProposalOutcomeKind::Active);
    assert_eq!(outcomes[1].outcome, GraphProposalOutcomeKind::Superseded);
    assert_eq!(outcomes[1].commit_id.as_deref(), Some("commit-old"));
}

#[test]
fn uncommitted_and_reverted_proposals_remain_distinct() {
    let committed = receipt("receipt-committed", "proposal-committed", 1);
    let uncommitted = receipt("receipt-uncommitted", "proposal-uncommitted", 2);
    let commits = vec![
        commit(
            "commit-1",
            1,
            GraphTruthOperation::Assert,
            Some("receipt-committed"),
            None,
            None,
        ),
        commit(
            "commit-revert",
            2,
            GraphTruthOperation::Revert,
            None,
            None,
            Some("commit-1"),
        ),
    ];
    let outcomes = project_graph_proposal_outcomes(&[committed, uncommitted], &commits)
        .expect("project outcomes");
    assert_eq!(outcomes[0].outcome, GraphProposalOutcomeKind::Reverted);
    assert_eq!(outcomes[1].outcome, GraphProposalOutcomeKind::Uncommitted);
}

#[test]
fn discovery_origin_can_name_one_atom_but_never_promote_a_path() {
    let mut value = receipt("a".repeat(64).as_str(), "proposal-1", 3);
    value.proposals[0].status = GraphProposalStatus::Generated;
    value.proposals[0].evidence_refs.push("evidence-1".into());
    value.discovery_origin = Some(DiscoveryPathProposalOrigin {
        source_path_receipt_id: "b".repeat(64).into(),
        identified_by_user_id: "human-1".into(),
        identification_rationale: "one missing atom".into(),
        supporting_path_node_indices: [0, 1].into_iter().collect(),
        supporting_path_edge_indices: [0].into_iter().collect(),
    });
    value.validate().expect("one explicit atom is valid");

    let mut second = value.proposals[0].clone();
    second.proposal_id = "proposal-2".into();
    second.atom = GraphTruthAtomKey::edge("entity:a", "state:c", "semantic::state_support");
    value.proposals.push(second);
    assert_eq!(
        value.validate(),
        Err(GraphProposalReceiptError::DiscoveryProposalMustNameOneAtom(
            2
        ))
    );
}

fn receipt(id: &str, proposal_id: &str, generation: u64) -> GraphProposalBatchReceipt {
    GraphProposalBatchReceipt {
        schema_version: GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
        receipt_id: id.into(),
        scope_key: "scope:test".into(),
        generation,
        created_at: generation as i64,
        compiler_policy: policy(),
        source_generations: [GraphTruthSourceGenerationRef {
            source_id: "semantic-graph:scope:test".into(),
            generation,
        }]
        .into_iter()
        .collect(),
        model_id: None,
        discovery_origin: None,
        proposals: vec![GraphProposalObservation {
            proposal_id: proposal_id.into(),
            atom: GraphTruthAtomKey::edge("entity:a", "state:b", "semantic::state_support"),
            family: "stateSupport".into(),
            source_kind: "entity".into(),
            target_kind: "state".into(),
            truth: GraphTruthDescriptor {
                kind: GraphTruthKind::Semantic,
                plane: Some(GraphTruthPlane::WorldState),
            },
            status: GraphProposalStatus::ReviewedSupport,
            evidence_refs: Default::default(),
            features: GraphProposalFeatures::default(),
            shadow_score_millis: None,
        }],
    }
}

fn commit(
    id: &str,
    generation: u64,
    operation: GraphTruthOperation,
    receipt_id: Option<&str>,
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
            generation,
        });
    if let Some(receipt_id) = receipt_id {
        header.receipt_ids.push(receipt_id.into());
    }
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

fn policy() -> GraphTruthCompilerPolicy {
    GraphTruthCompilerPolicy {
        compiler_id: "phoenix-graph-post".into(),
        compiler_version: "0.1.1".into(),
        policy_id: "graph-post-promotion:semantic-phase5-world-state".into(),
        policy_version: "1".into(),
    }
}
