use super::*;
use crate::types::{GraphCounters, GraphDropReasons};

#[test]
fn packet_binds_entity_targets_to_registry_objects() {
    let snapshot = sample_snapshot();
    let packet = build_atlas_packet(&snapshot);

    assert_eq!(packet.source_contract.authority, "rust-atlas-packet");
    assert_eq!(
        packet.source_contract.ts_graph_builder_role,
        "compatibility-only"
    );
    assert!(packet
        .objects
        .iter()
        .any(|object| object.id == "character:rift"
            && object.family == GraphFamily::Registry
            && object.status == AtlasObjectStatus::Accepted));
    assert!(packet.manifold_targets.iter().any(|target| target.id
        == "embed:entity:character:rift"
        && target.object_id == "character:rift"
        && target.family == GraphFamily::Registry
        && target.vector_status == AtlasVectorStatus::Missing
        && target.style_key.as_deref() == Some("character")
        && target.lane.as_deref() == Some("entity_anchor")));
    assert!(packet
        .manifold_targets
        .iter()
        .any(|target| target.id == "embed:graph-fact:rel-1"
            && target.style_key.as_deref() == Some("cooccurrence")
            && target.lane.as_deref() == Some("relationship_fact")
            && target.admission == ManifoldAdmission::Candidate
            && target.status == AtlasObjectStatus::Proposed));
    assert!(packet
        .manifold_targets
        .iter()
        .any(|target| target.id == "embed:memory:mem-1"
            && target.object_id == "atlas:memory:mem-1"
            && target.family == GraphFamily::Memory
            && target.registry_entity_id.as_ref().map(|id| id.0.as_str())
                == Some("character:rift")));
    assert!(packet
        .objects
        .iter()
        .any(|object| object.family == GraphFamily::Structure && object.kind == "chunk"));
    assert!(packet
        .objects
        .iter()
        .any(|object| object.family == GraphFamily::Fact && object.kind == "co_occurs_with"));
    assert!(packet
        .objects
        .iter()
        .any(|object| object.family == GraphFamily::Evidence && object.kind == "entityAnchor"));
    assert_eq!(packet.counters.model_vectors, 0);
}

fn sample_snapshot() -> GraphRebuildSnapshot {
    let entity_id = EntityId("character:rift".to_owned());
    let chunk = GraphChunk {
        id: "note-a:chunk:0".into(),
        note_id: "note-a".into(),
        start: 0,
        end: 12,
        ordinal: 0,
        source: "test".into(),
    };
    let anchor = GraphAnchor {
        id: "anchor-1".into(),
        entity_id: entity_id.clone(),
        note_id: "note-a".into(),
        chunk_id: Some(chunk.id.clone()),
        surface: "Rift".into(),
        source_start: 0,
        source_end: 4,
        source: "test".into(),
        confidence: 1.0,
        generation: 7,
    };
    let memory = GraphMemoryState {
        id: "mem-1".into(),
        entity_id: entity_id.clone(),
        note_id: Some("note-a".into()),
        key: "rank".into(),
        value: "captain".into(),
        evidence_ids: vec![anchor.id.clone()],
    };
    let node = GraphNode {
        id: entity_id.clone(),
        entity_id: entity_id.clone(),
        label: "Rift".into(),
        kind: "character".into(),
        aliases: Vec::new(),
        anchor_ids: vec![anchor.id.clone()],
        note_ids: vec!["note-a".into()],
        total_mentions: 1,
    };
    let relationship = GraphRelationship {
        id: "rel-1".into(),
        source_entity_id: entity_id.clone(),
        target_entity_id: entity_id.clone(),
        relation_type: "co_occurs_with".into(),
        evidence_anchor_ids: vec![anchor.id.clone()],
        confidence: 0.9,
        status: "accepted".into(),
        adjudication_source: "test".into(),
        adjudication_score: 0.9,
        rationale: "test".into(),
        decision_evidence: Vec::new(),
    };
    let embedding_targets = vec![
        GraphEmbeddingTarget {
            id: "embed:entity:character:rift".into(),
            kind: "entity".into(),
            source_id: "character:rift".into(),
            note_id: None,
            chunk_id: None,
            entity_id: Some(entity_id.clone()),
            label: "Rift".into(),
            text: "Rift".into(),
            evidence_ids: vec![anchor.id.clone()],
            parent_ids: Vec::new(),
            ..GraphEmbeddingTarget::default()
        },
        GraphEmbeddingTarget {
            id: "embed:graph-fact:rel-1".into(),
            kind: "graphFact".into(),
            source_id: "rel-1".into(),
            note_id: None,
            chunk_id: None,
            entity_id: None,
            label: "Rift co_occurs_with Rift".into(),
            text: "Rift co_occurs_with Rift".into(),
            evidence_ids: vec![anchor.id.clone()],
            parent_ids: Vec::new(),
            ..GraphEmbeddingTarget::default()
        },
        GraphEmbeddingTarget {
            id: "embed:memory:mem-1".into(),
            kind: "memoryState".into(),
            source_id: "mem-1".into(),
            note_id: Some("note-a".into()),
            chunk_id: None,
            entity_id: Some(entity_id.clone()),
            label: "rank".into(),
            text: "rank captain".into(),
            evidence_ids: vec![anchor.id.clone()],
            parent_ids: Vec::new(),
            ..GraphEmbeddingTarget::default()
        },
    ];
    GraphRebuildSnapshot {
        schema_version: "phoenix-graph-rebuild/v1".into(),
        id: "snapshot-1".into(),
        source: "phoenix-graph-rebuild".into(),
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:note-a".into(),
        note_ids: vec!["note-a".into()],
        built_at: 7,
        chunks: vec![chunk],
        mentions: Vec::new(),
        entity_anchors: vec![anchor],
        relationships: vec![relationship],
        events: Vec::new(),
        episodes: Vec::new(),
        temporal_edges: Vec::new(),
        causal_edges: Vec::new(),
        memory_state: vec![memory],
        embedding_targets,
        embedding_vectors: Vec::new(),
        projection_refs: Vec::new(),
        nodes: vec![node],
        edges: Vec::new(),
        calendar_registry_summary: None,
        document_sidecar_summary: None,
        document_review_summary: None,
        document_compiler_summary: None,
        discourse_spine_summary: None,
        counters: GraphCounters {
            entities: 1,
            accepted_anchors: 1,
            embedding_targets: 3,
            nodes: 1,
            drop_reasons: GraphDropReasons::default(),
            ..GraphCounters::default()
        },
    }
}
