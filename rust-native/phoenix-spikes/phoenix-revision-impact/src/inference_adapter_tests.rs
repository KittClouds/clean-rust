use phoenix_graph_rebuild::{
    build_graph_rebuild_snapshot, GraphEmbeddingTarget, GraphEpisodeProjectionEdge, GraphNode,
    GraphRebuildInput, GraphRelationship, GraphScopeKind,
};
use phoenix_types::{EntityId, ScopeKey};

use super::*;
use crate::{GraphGeneration, RevisionAnalysisViews};

fn snapshot() -> phoenix_graph_rebuild::GraphRebuildSnapshot {
    build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "phase-3-adapter",
        note_id: "note:phase-3",
        text: "Kai crossed the bridge. Hazel recorded the crossing.",
        scope: ScopeKey::default(),
        entities: &[],
        candidate_count: 0,
        built_at: Some(31),
    })
    .expect("graph rebuild snapshot")
}

fn graph_node(id: &str) -> GraphNode {
    let entity_id = EntityId(id.to_owned());
    GraphNode {
        id: entity_id.clone(),
        entity_id,
        label: id.into(),
        kind: "character".into(),
        aliases: Vec::new(),
        anchor_ids: Vec::new(),
        note_ids: vec!["note:phase-3".into()],
        total_mentions: 1,
    }
}

fn relationship(id: &str, status: &str) -> GraphRelationship {
    GraphRelationship {
        id: id.into(),
        source_entity_id: EntityId("kai".to_owned()),
        target_entity_id: EntityId("hazel".to_owned()),
        relation_type: "trusts".into(),
        evidence_anchor_ids: vec![format!("anchor:{id}").into()],
        confidence: 0.9,
        status: status.into(),
        adjudication_source: "phase-3-test".into(),
        adjudication_score: 0.9,
        rationale: "fixture".into(),
        decision_evidence: Vec::new(),
    }
}

#[test]
fn graph_rebuild_adapter_excludes_nonaccepted_semantic_relations() {
    let mut snapshot = snapshot();
    snapshot
        .nodes
        .extend([graph_node("kai"), graph_node("hazel")]);
    snapshot.relationships.extend([
        relationship("accepted", "accepted"),
        relationship("review", "review"),
        relationship("unknown", "mystery_status"),
        relationship("rejected", "rejected"),
    ]);
    snapshot
        .episode_projection_edges
        .push(GraphEpisodeProjectionEdge {
            id: "candidate:episode-overlay".into(),
            status: "candidate_overlay".into(),
            no_topology_commit: true,
            ..GraphEpisodeProjectionEdge::default()
        });
    snapshot.embedding_targets.push(GraphEmbeddingTarget {
        id: "candidate:embedding-target".into(),
        admission_status: Some("candidate".into()),
        ..GraphEmbeddingTarget::default()
    });
    let inference = graph_rebuild_asserted_inference_input(&snapshot);
    let views = RevisionAnalysisViews::project(GraphGeneration(31), Vec::new(), inference)
        .expect("asserted model projection");
    let receipt = views.inference_graph.receipt();

    assert_eq!(receipt.admitted_relations, 1);
    assert_eq!(receipt.excluded_candidate_edges, 2);
    assert_eq!(receipt.excluded_rejected_edges, 1);
    assert!(views
        .inference_graph
        .edge_metadata()
        .iter()
        .any(|edge| edge.edge_id.ends_with("accepted")));
    assert!(views.inference_graph.edge_metadata().iter().all(|edge| {
        !edge.edge_id.ends_with("review")
            && !edge.edge_id.ends_with("unknown")
            && !edge.edge_id.ends_with("rejected")
            && !edge.edge_id.contains("episode-overlay")
            && !edge.edge_id.contains("embedding-target")
    }));
}

#[test]
fn graph_rebuild_adapter_emits_model_node_types_and_memberships() {
    let mut snapshot = snapshot();
    snapshot.nodes.push(graph_node("kai"));
    let inference = graph_rebuild_asserted_inference_input(&snapshot);
    let views = RevisionAnalysisViews::project(GraphGeneration(31), Vec::new(), inference)
        .expect("model projection");
    let graph = &views.inference_graph;

    assert!(graph.node_types().iter().any(|kind| kind == "document"));
    assert!(graph.node_types().iter().any(|kind| kind == "chunk"));
    assert!(graph.receipt().admitted_memberships > 0);
    assert!(graph.edge_metadata().iter().any(|edge| {
        edge.edge_id
            .starts_with("inference:document_entity:note:phase-3:kai")
    }));
    assert_eq!(graph.incoming_offsets().len(), graph.nodes().len() + 1);
    assert_eq!(graph.source_ids().len(), graph.edge_metadata().len());
    assert_eq!(graph.relation_type_ids().len(), graph.edge_metadata().len());
}
