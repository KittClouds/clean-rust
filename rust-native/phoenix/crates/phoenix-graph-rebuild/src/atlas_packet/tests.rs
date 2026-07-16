use super::*;
use crate::types::{
    GraphCounters, GraphDiscourseSpineBridge, GraphDiscourseSpineCluster,
    GraphDiscourseSpineSummary, GraphDocumentReviewRow, GraphDocumentReviewSummary,
    GraphDropReasons,
};

#[test]
fn packet_binds_entity_targets_to_registry_objects() {
    let snapshot = sample_snapshot();
    let packet = build_atlas_packet(&snapshot);

    assert_eq!(packet.source_contract.authority, "rust-atlas-packet");
    assert_eq!(
        packet.source_contract.ts_graph_builder_role,
        "native-atlas-packet-authority"
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
    assert!(packet
        .objects
        .iter()
        .any(|object| object.id == "atlas:review:review-row-1"
            && object.family == GraphFamily::Review
            && object.status == AtlasObjectStatus::Proposed
            && object.lane.as_deref() == Some("review_state")));
    assert!(packet
        .objects
        .iter()
        .any(|object| object.id == "atlas:discourse-cluster:cluster-1"
            && object.family == GraphFamily::Discourse
            && object.kind == "domain_region"
            && object.lane.as_deref() == Some("discourse_cluster")));
    assert!(packet
        .objects
        .iter()
        .any(|object| object.id == "atlas:discourse-bridge:bridge-1"
            && object.family == GraphFamily::Discourse
            && object.status == AtlasObjectStatus::Proposed
            && object
                .target_ids
                .iter()
                .map(|id| id.as_str())
                .collect::<Vec<_>>()
                == ["embed:chunk:a", "embed:chunk:b"]));
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
        entity_anchors: vec![anchor.clone()],
        relationships: vec![relationship],
        events: Vec::new(),
        episodes: Vec::new(),
        episode_projection_edges: Vec::new(),
        temporal_edges: Vec::new(),
        causal_edges: Vec::new(),
        memory_state: vec![memory],
        memory_governance_candidates: Vec::new(),
        embedding_targets,
        embedding_vectors: Vec::new(),
        projection_refs: Vec::new(),
        nodes: vec![node],
        edges: Vec::new(),
        calendar_registry_summary: None,
        document_sidecar_summary: None,
        document_review_summary: Some(GraphDocumentReviewSummary {
            rows: vec![GraphDocumentReviewRow {
                id: "review-row-1".into(),
                object_id: "fact:candidate-1".into(),
                object_kind: "graph_fact_candidate".into(),
                state: "proposed".into(),
                title: "Candidate needs review".into(),
                subtitle: "bounded packet row".into(),
                detail: CompactString::default(),
                note_id: "note-a".into(),
                source_start: 0,
                source_end: 4,
                confidence: 0.67,
                detector: "test".into(),
                parent_unit_ids: vec!["unit-parent".into()],
                child_unit_ids: Vec::new(),
                evidence_span_ids: vec![anchor.id.clone()],
                related_object_ids: vec!["fact:candidate-1".into()],
                why: Vec::new(),
            }],
        }),
        document_compiler_summary: None,
        discourse_spine_summary: Some(GraphDiscourseSpineSummary {
            targets: Vec::new(),
            clusters: vec![GraphDiscourseSpineCluster {
                id: "cluster-1".into(),
                kind: "domain_region".into(),
                label: "Shared domain".into(),
                target_ids: vec!["embed:chunk:a".into(), "embed:chunk:b".into()],
                score: 0.88,
            }],
            bridges: vec![GraphDiscourseSpineBridge {
                id: "bridge-1".into(),
                kind: "resonance".into(),
                status: "proposed".into(),
                source_target_id: "embed:chunk:a".into(),
                target_target_id: "embed:chunk:b".into(),
                label: "A echoes B".into(),
                evidence_target_ids: vec!["embed:chunk:a".into(), "embed:chunk:b".into()],
                shared_label_ids: vec!["label:shared".into()],
                shared_entity_ids: vec![entity_id.0.as_str().into()],
            }],
        }),
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
