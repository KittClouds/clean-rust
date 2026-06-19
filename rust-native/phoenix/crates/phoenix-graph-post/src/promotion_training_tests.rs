use std::fs;
use std::path::PathBuf;

use phoenix_graph_kernel::{
    GraphProposalBatchReceipt, GraphProposalFeatures, GraphProposalObservation,
    GraphProposalOutcomeKind, GraphProposalStatus, GraphTruthAtomKey, GraphTruthCommit, KernelEdge,
    KernelEdgeType, KernelGraphLayer, KernelMutationBatch, KernelMutationScope,
    KernelRelationClass, KernelVertexId, GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
};
use phoenix_store_native_core::{PhoenixGraphKernelStoreV2, PhoenixGraphLearningStore};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{
    GraphTruthCommitHeader, GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthDigest,
    GraphTruthKind, GraphTruthOperation, GraphTruthPlane, GraphTruthSourceGenerationRef,
};

use crate::promotion_learner::GraphPromotionTrainingConfig;
use crate::promotion_training::{
    build_outcome_backed_training_examples, fit_shadow_promotion_model_from_history,
    fixed_width_training_examples,
};

#[test]
fn outcome_training_examples_are_deterministic_after_restart_replay() {
    let path = temp_store_path("outcome-training");
    let store = PhoenixOvergraphStore::open(&path).expect("open store");
    store.init_graph_kernel_schema().expect("init kernel");
    let receipts = [
        receipt("receipt-active", "proposal-active", "state:active", 1, 910),
        receipt(
            "receipt-superseded",
            "proposal-superseded",
            "state:superseded",
            2,
            870,
        ),
        receipt(
            "receipt-retracted",
            "proposal-retracted",
            "state:retracted",
            4,
            810,
        ),
        receipt(
            "receipt-reverted",
            "proposal-reverted",
            "state:reverted",
            6,
            760,
        ),
        receipt(
            "receipt-uncommitted",
            "proposal-uncommitted",
            "state:uncommitted",
            8,
            520,
        ),
    ];
    for receipt in &receipts {
        store
            .append_graph_proposal_receipt(receipt)
            .expect("append receipt");
    }
    let commits = vec![
        commit(
            "commit-active",
            1,
            GraphTruthOperation::Assert,
            "state:active",
            Some("receipt-active"),
            None,
            None,
        ),
        commit(
            "commit-superseded-old",
            2,
            GraphTruthOperation::Assert,
            "state:superseded",
            Some("receipt-superseded"),
            None,
            None,
        ),
        commit(
            "commit-superseded-new",
            3,
            GraphTruthOperation::Supersede,
            "state:superseded",
            None,
            Some("commit-superseded-old"),
            None,
        ),
        commit(
            "commit-retracted-old",
            4,
            GraphTruthOperation::Assert,
            "state:retracted",
            Some("receipt-retracted"),
            None,
            None,
        ),
        empty_commit(
            "commit-retract",
            5,
            GraphTruthOperation::Retract,
            Some("commit-retracted-old"),
            None,
        ),
        commit(
            "commit-reverted-old",
            6,
            GraphTruthOperation::Assert,
            "state:reverted",
            Some("receipt-reverted"),
            None,
            None,
        ),
        empty_commit(
            "commit-revert",
            7,
            GraphTruthOperation::Revert,
            None,
            Some("commit-reverted-old"),
        ),
    ];
    for commit in &commits {
        store
            .append_graph_truth_commit(commit)
            .expect("append commit");
    }
    let first = build_outcome_backed_training_examples(
        &store.load_graph_proposal_receipts().expect("load receipts"),
        &store.load_graph_truth_commits().expect("load commits"),
    )
    .expect("build examples");
    store.close_fast().expect("close store");

    let reopened = PhoenixOvergraphStore::open(&path).expect("reopen store");
    let second = build_outcome_backed_training_examples(
        &reopened
            .load_graph_proposal_receipts()
            .expect("reload receipts"),
        &reopened.load_graph_truth_commits().expect("reload commits"),
    )
    .expect("rebuild examples");

    assert_eq!(outcomes(&first), outcomes(&second));
    assert_eq!(
        outcomes(&second),
        vec![
            (
                "proposal-active".to_owned(),
                GraphProposalOutcomeKind::Active
            ),
            (
                "proposal-retracted".to_owned(),
                GraphProposalOutcomeKind::Retracted,
            ),
            (
                "proposal-reverted".to_owned(),
                GraphProposalOutcomeKind::Reverted
            ),
            (
                "proposal-superseded".to_owned(),
                GraphProposalOutcomeKind::Superseded,
            ),
            (
                "proposal-uncommitted".to_owned(),
                GraphProposalOutcomeKind::Uncommitted,
            ),
        ]
    );
    let fixed = fixed_width_training_examples(&second);
    assert_eq!(fixed.len(), 5);
    assert_eq!(fixed[0].features.0.len(), 16);
    assert!(fixed[0].label);
    assert!(fixed[1..].iter().all(|value| !value.label));
    let shadow_model = fit_shadow_promotion_model_from_history(
        "real-history-shadow-test",
        &reopened
            .load_graph_proposal_receipts()
            .expect("reload receipts for shadow training"),
        &reopened
            .load_graph_truth_commits()
            .expect("reload commits for shadow training"),
        GraphPromotionTrainingConfig::default(),
    )
    .expect("fit shadow promotion model from real outcome history");
    assert_eq!(shadow_model.outcome_examples.len(), 5);

    reopened.close_fast().expect("close reopened");
    let _ = fs::remove_dir_all(path);
}

fn outcomes(
    rows: &[crate::promotion_training::GraphPromotionOutcomeTrainingExample],
) -> Vec<(String, GraphProposalOutcomeKind)> {
    rows.iter()
        .map(|row| (row.proposal_id.to_string(), row.outcome))
        .collect()
}

fn receipt(
    id: &str,
    proposal_id: &str,
    state_id: &str,
    generation: u64,
    score: i16,
) -> GraphProposalBatchReceipt {
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
        proposals: vec![GraphProposalObservation {
            proposal_id: proposal_id.into(),
            atom: atom(state_id),
            family: "stateSupport".into(),
            source_kind: "entity".into(),
            target_kind: "state".into(),
            truth: GraphTruthDescriptor {
                kind: GraphTruthKind::Semantic,
                plane: Some(GraphTruthPlane::WorldState),
            },
            status: GraphProposalStatus::ReviewedSupport,
            evidence_refs: Default::default(),
            features: features(score),
            shadow_score_millis: None,
        }],
    }
}

fn commit(
    id: &str,
    generation: u64,
    operation: GraphTruthOperation,
    state_id: &str,
    receipt_id: Option<&str>,
    predecessor: Option<&str>,
    reverses: Option<&str>,
) -> GraphTruthCommit {
    let mut header = header(id, generation, operation, receipt_id, predecessor, reverses);
    GraphTruthCommit {
        header: {
            if operation == GraphTruthOperation::Supersede {
                header.receipt_ids.clear();
            }
            header
        },
        batch: KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Projection {
                scope_key: "scope:test".to_owned(),
            },
            recorded_at: Some(generation as i64),
            vertices: Vec::new(),
            edges: vec![edge(state_id)],
        },
    }
}

fn empty_commit(
    id: &str,
    generation: u64,
    operation: GraphTruthOperation,
    predecessor: Option<&str>,
    reverses: Option<&str>,
) -> GraphTruthCommit {
    GraphTruthCommit {
        header: header(id, generation, operation, None, predecessor, reverses),
        batch: KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Projection {
                scope_key: "scope:test".to_owned(),
            },
            recorded_at: Some(generation as i64),
            vertices: Vec::new(),
            edges: Vec::new(),
        },
    }
}

fn header(
    id: &str,
    generation: u64,
    operation: GraphTruthOperation,
    receipt_id: Option<&str>,
    predecessor: Option<&str>,
    reverses: Option<&str>,
) -> GraphTruthCommitHeader {
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
    header
}

fn policy() -> GraphTruthCompilerPolicy {
    GraphTruthCompilerPolicy {
        compiler_id: "phoenix-graph-post".into(),
        compiler_version: "0.1.1".into(),
        policy_id: "graph-post-promotion:semantic-phase5-world-state".into(),
        policy_version: "1".into(),
    }
}

fn edge(state_id: &str) -> KernelEdge {
    KernelEdge {
        source_id: KernelVertexId("entity:a".to_owned()),
        target_id: KernelVertexId(state_id.to_owned()),
        edge_type: KernelEdgeType("semantic::state_support".to_owned()),
        relation_class: KernelRelationClass::Semantic,
        layer: KernelGraphLayer::Asserted,
        ..KernelEdge::default()
    }
}

fn atom(state_id: &str) -> GraphTruthAtomKey {
    GraphTruthAtomKey::edge("entity:a", state_id, "semantic::state_support")
}

fn features(score: i16) -> GraphProposalFeatures {
    GraphProposalFeatures([
        score,
        score,
        score,
        0,
        score,
        400,
        250,
        score.saturating_sub(540),
        1000,
        1000,
        0,
        1000,
        0,
        0,
        0,
        1000,
    ])
}

fn temp_store_path(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "phoenix-{name}-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ))
}
