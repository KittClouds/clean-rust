use phoenix_graph_kernel::{
    KernelEdge, KernelEdgeType, KernelGraphLayer, KernelMutationBatch, KernelRelationClass,
    KernelVertex, KernelVertexClass, KernelVertexId,
};
use phoenix_semantic_v2::{
    SemanticCandidateStatus, SemanticEdgeFamily, SemanticGraphEdgeCandidate, SemanticGraphNodeKind,
    SemanticGraphNodeRecord, SemanticGraphScopeSidecar,
};
use phoenix_store_native_core::{PhoenixGraphKernelStoreV2, PhoenixGraphLearningStore};
use phoenix_store_overgraph::PhoenixOvergraphStore;

use crate::promotion_lanes::{append_semantic_phase5_promotion_commits, semantic_phase5_proposals};
use crate::promotion_receipts::build_semantic_proposal_receipt;

#[test]
fn semantic_phase5_promotes_only_reviewed_edges() {
    let sidecar = SemanticGraphScopeSidecar {
        scope_key: "scope-1".to_owned(),
        updated_at: 42,
        generation: 42,
        candidate_nodes: vec![
            semantic_node("semantic-unit::state::1"),
            semantic_node("semantic-unit::state::2"),
            semantic_node("semantic-unit::state::3"),
        ],
        candidate_edges: vec![
            candidate(
                "semantic-unit::state::1",
                "semantic-unit::state::2",
                SemanticCandidateStatus::ReviewedSupport,
            ),
            candidate(
                "semantic-unit::state::1",
                "semantic-unit::state::3",
                SemanticCandidateStatus::Generated,
            ),
        ],
        candidate_graph_batch: KernelMutationBatch {
            layer: KernelGraphLayer::Candidate,
            vertices: vec![
                vertex("semantic-unit::state::1"),
                vertex("semantic-unit::state::2"),
                vertex("semantic-unit::state::3"),
            ],
            edges: vec![
                edge("semantic-unit::state::1", "semantic-unit::state::2"),
                edge("semantic-unit::state::1", "semantic-unit::state::3"),
            ],
            ..Default::default()
        },
        ..Default::default()
    };

    let proposals = semantic_phase5_proposals(&sidecar);

    assert_eq!(proposals.len(), 1);
    assert_eq!(proposals[0].batch.layer, KernelGraphLayer::Asserted);
    assert_eq!(proposals[0].batch.edges.len(), 1);
    assert_eq!(
        proposals[0].batch.edges[0].target_id.0,
        "semantic-unit::state::2"
    );
    assert_eq!(
        proposals[0].batch.edges[0].relation_class,
        KernelRelationClass::Semantic
    );
    assert_eq!(
        proposals[0].batch.edges[0]
            .attributes
            .get("truthPlane")
            .and_then(serde_json::Value::as_str),
        Some("worldState")
    );
    assert!(proposals[0].batch.vertices.iter().all(|vertex| {
        vertex
            .attributes
            .get("truthPlane")
            .and_then(serde_json::Value::as_str)
            == Some("worldState")
    }));
}

#[test]
fn semantic_receipt_captures_promoted_and_uncommitted_candidates_once() {
    let sidecar = SemanticGraphScopeSidecar {
        scope_key: "scope-1".to_owned(),
        updated_at: 42,
        generation: 42,
        candidate_nodes: vec![
            semantic_node("semantic-unit::state::1"),
            semantic_node("semantic-unit::state::2"),
            semantic_node("semantic-unit::state::3"),
        ],
        candidate_edges: vec![
            candidate(
                "semantic-unit::state::1",
                "semantic-unit::state::2",
                SemanticCandidateStatus::ReviewedSupport,
            ),
            candidate(
                "semantic-unit::state::1",
                "semantic-unit::state::3",
                SemanticCandidateStatus::Generated,
            ),
        ],
        ..Default::default()
    };

    let receipt = build_semantic_proposal_receipt(&sidecar)
        .expect("build receipt")
        .expect("receipt present");

    assert_eq!(receipt.proposals.len(), 2);
    assert_eq!(receipt.source_generations[0].generation, 42);
    assert_eq!(
        receipt.proposals[0].proposal_id,
        "semantic-unit::state::1:semantic-unit::state::2"
    );
    assert_eq!(
        receipt.proposals[1].proposal_id,
        "semantic-unit::state::1:semantic-unit::state::3"
    );
}

#[test]
fn semantic_commit_references_the_durable_proposal_receipt() {
    let path = std::env::temp_dir().join(format!(
        "phoenix-semantic-receipt-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ));
    let store = PhoenixOvergraphStore::open(&path).expect("open store");
    let sidecar = SemanticGraphScopeSidecar {
        scope_key: "scope-1".to_owned(),
        updated_at: 42,
        generation: 42,
        candidate_nodes: vec![
            semantic_node("semantic-unit::state::1"),
            semantic_node("semantic-unit::state::2"),
        ],
        candidate_edges: vec![candidate(
            "semantic-unit::state::1",
            "semantic-unit::state::2",
            SemanticCandidateStatus::ReviewedSupport,
        )],
        candidate_graph_batch: KernelMutationBatch {
            layer: KernelGraphLayer::Candidate,
            vertices: vec![
                vertex("semantic-unit::state::1"),
                vertex("semantic-unit::state::2"),
            ],
            edges: vec![edge("semantic-unit::state::1", "semantic-unit::state::2")],
            ..Default::default()
        },
        ..Default::default()
    };

    append_semantic_phase5_promotion_commits(&store, &sidecar).expect("append promotion");
    let receipts = store.load_graph_proposal_receipts().expect("load receipts");
    let commits = store.load_graph_truth_commits().expect("load commits");
    assert_eq!(receipts.len(), 1);
    assert_eq!(commits.len(), 1);
    assert_eq!(
        commits[0].header.receipt_ids.as_slice(),
        &[receipts[0].receipt_id.clone()]
    );
    assert!(commits[0]
        .header
        .source_generations
        .iter()
        .any(|source| source.source_id == "semantic-graph:scope-1" && source.generation == 42));
    store.close_fast().expect("close store");
    let _ = std::fs::remove_dir_all(path);
}

fn semantic_node(node_id: &str) -> SemanticGraphNodeRecord {
    SemanticGraphNodeRecord {
        node_id: node_id.to_owned(),
        node_kind: SemanticGraphNodeKind::State,
        truth_plane: Some("world".to_owned()),
        ..Default::default()
    }
}

fn candidate(
    source: &str,
    target: &str,
    status: SemanticCandidateStatus,
) -> SemanticGraphEdgeCandidate {
    SemanticGraphEdgeCandidate {
        edge_id: format!("{source}:{target}"),
        family: SemanticEdgeFamily::StateSupport,
        source_node_id: source.to_owned(),
        source_kind: SemanticGraphNodeKind::State,
        target_node_id: target.to_owned(),
        target_kind: SemanticGraphNodeKind::State,
        candidate_status: status,
        ..Default::default()
    }
}

fn vertex(id: &str) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(id.to_owned()),
        kind: "state".to_owned(),
        class: KernelVertexClass::State,
        ..Default::default()
    }
}

fn edge(source: &str, target: &str) -> KernelEdge {
    KernelEdge {
        source_id: KernelVertexId(source.to_owned()),
        target_id: KernelVertexId(target.to_owned()),
        edge_type: KernelEdgeType("semantic::state_support".to_owned()),
        relation_class: KernelRelationClass::Candidate,
        layer: KernelGraphLayer::Candidate,
        ..Default::default()
    }
}
