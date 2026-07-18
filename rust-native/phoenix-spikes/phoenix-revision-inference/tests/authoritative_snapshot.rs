use std::path::{Path, PathBuf};

use phoenix_graph_rebuild::{
    GraphRebuildInput, GraphRelationship, GraphScopeKind, build_graph_rebuild_snapshot,
};
use phoenix_revision_impact::{
    GraphGeneration, RevisionAnalysisViews, graph_rebuild_asserted_inference_input,
};
use phoenix_revision_inference::{project_gfm, project_reasoner};
use phoenix_types::{EntityId, EntityKind, GenderHint, LexiconEntry, ScopeKey};

#[test]
fn real_phoenix_snapshot_feeds_both_models_and_rejects_candidate_truth() {
    let root = repository_root();
    let text = std::fs::read_to_string(root.join("docs/shortrun.md")).unwrap();
    let excerpt = text.chars().take(1_200).collect::<String>();
    let entities = entities();
    let mut snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "phase6-test",
        note_id: "docs/shortrun.md#phase6-test",
        text: &excerpt,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 1,
        built_at: Some(600),
    })
    .unwrap();
    assert!(snapshot.nodes.len() >= 2);
    snapshot.relationships.push(GraphRelationship {
        id: "candidate:trap".into(),
        source_entity_id: snapshot.nodes[0].entity_id.clone(),
        target_entity_id: snapshot.nodes[1].entity_id.clone(),
        relation_type: "candidate_only_relation".into(),
        evidence_anchor_ids: Vec::new(),
        confidence: 0.5,
        status: "candidate".into(),
        adjudication_source: "phase6-test".into(),
        adjudication_score: 0.5,
        rationale: "candidate leakage trap".into(),
        decision_evidence: Vec::new(),
    });
    let second_snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "phase6-test",
        note_id: "docs/shortrun.md#phase6-test",
        text: &excerpt,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 1,
        built_at: Some(600),
    })
    .unwrap();
    assert_eq!(
        snapshot.edges, second_snapshot.edges,
        "authoritative structural edges must be deterministic"
    );
    let input = graph_rebuild_asserted_inference_input(&snapshot);
    let views = RevisionAnalysisViews::project(GraphGeneration(600), Vec::new(), input).unwrap();
    assert!(views.inference_graph.receipt().excluded_candidate_edges > 0);
    assert!(
        views
            .inference_graph
            .nodes()
            .iter()
            .all(|node| !node.embedding_text.is_empty())
    );
    let gfm = project_gfm(&views.inference_graph).unwrap();
    let reasoner = project_reasoner(&views.inference_graph).unwrap();
    assert!(gfm.view.graph.node_count() >= 2);
    assert!(gfm.view.graph.edge_count() > 0);
    assert!(!gfm.view.document_ids.is_empty());
    assert_eq!(gfm.authority.admitted_candidate_edges, 0);
    assert!(reasoner.view.graph.node_count() >= gfm.view.graph.node_count());
    assert!(reasoner.view.graph.edge_count() > 0);
    assert_eq!(reasoner.authority.admitted_candidate_edges, 0);
}

fn entities() -> Vec<LexiconEntry> {
    [
        ("ryan", "Ryan", EntityKind::Character),
        ("quicksave", "Quicksave", EntityKind::Character),
        ("new-rome", "New Rome", EntityKind::Location),
        ("dynamis", "Dynamis", EntityKind::Organization),
    ]
    .into_iter()
    .map(|(id, label, kind)| LexiconEntry {
        entity_id: EntityId(id.into()),
        label: label.into(),
        aliases: Vec::new(),
        kind: Some(kind),
        gender: Some(GenderHint::Unknown),
        number: None,
        scope: ScopeKey::default(),
    })
    .collect()
}

fn repository_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf()
}
