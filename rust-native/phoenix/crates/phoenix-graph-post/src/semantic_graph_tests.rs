use phoenix_graph_kernel::{
    KernelEdge, KernelEdgeType, KernelGraphLayer, KernelMutationBatch, KernelMutationScope,
    KernelProvenance, KernelRelationClass, KernelVertexClass, KernelVertexId,
};
use phoenix_semantic_v2::{
    DocumentArchive, DocumentCausalSubstrate, DocumentManifest, GraphScopeSidecar,
    SemanticCandidateStatus, SemanticEdgeFamily, SemanticGraphEdgeCandidate, SemanticGraphNodeKind,
    SemanticGraphNodeRecord,
};
use phoenix_types::{
    Argument, DocumentId, EntityId, EventId, EventRecord, PredicateFrame, Proposition,
    ProvenanceRef, ScopeKey, SourceRange,
};

use crate::semantic_graph::{
    compile_candidate_graph_batch, dedupe_embedding_texts, retain_configured_prototypes, summarize,
    SemanticGraphConfig,
};
use crate::semantic_graph_lifecycle::{
    default_candidate_lifecycle_policy, retain_live_candidates, SemanticCandidateLifecycleStats,
};
use crate::semantic_graph_support::{
    build_prototypes, Prototype, CHUNK_KIND, CLAIM_KIND, ENTITY_KIND, EVENT_KIND,
    SEMANTIC_UNIT_PREFIX, STATE_KIND,
};

fn prototype(node_id: &str, ann_kind: &'static str, node_kind: SemanticGraphNodeKind) -> Prototype {
    Prototype {
        node_id: node_id.to_owned(),
        ann_kind,
        node_kind,
        text_key: node_id.to_owned(),
        text: node_id.to_owned(),
        truth_plane: Some("world".to_owned()),
        document_id: None,
        note_id: None,
        narrative_id: None,
        folder_id: None,
        folder_path: None,
        evidence_refs: Vec::new(),
        semantic_node: SemanticGraphNodeRecord {
            node_id: node_id.to_owned(),
            node_kind,
            document_id: None,
            narrative_id: None,
            text_key: node_id.to_owned(),
            text_hash: 1,
            truth_plane: Some("world".to_owned()),
            evidence_refs: Vec::new(),
        },
        slot_key: Some("entity.employer".to_owned()),
        value_key: Some("acme".to_owned()),
        primary_entity_id: None,
        secondary_entity_id: None,
    }
}

#[test]
fn build_prototypes_surfaces_document_semantic_units() {
    let proposition = Proposition {
        proposition_id: "prop:0".into(),
        sentence_index: 0,
        predicate: PredicateFrame {
            predicate: "moved".into(),
            trigger_range: SourceRange::new(6, 11),
            relation_type: "relates_to".into(),
        },
        clause_range: Some(SourceRange::new(0, 29)),
        arguments: [
            Argument {
                role: "subject".into(),
                entity_id: Some(EntityId("luffy".to_owned())),
                range: Some(SourceRange::new(0, 5)),
                ..Default::default()
            },
            Argument {
                role: "object".into(),
                entity_id: Some(EntityId("harbor".to_owned())),
                range: Some(SourceRange::new(21, 27)),
                ..Default::default()
            },
        ]
        .into_iter()
        .collect(),
        evidence: [ProvenanceRef {
            document_id: Some(DocumentId("doc-1".to_owned())),
            label: "Luffy moved into the harbor.".into(),
            kind: Some("sentence".into()),
            range: SourceRange::new(0, 29),
            ..Default::default()
        }]
        .into_iter()
        .collect(),
        ..Default::default()
    };
    let archive = DocumentArchive {
        manifest: DocumentManifest {
            document_id: "doc-1".to_owned(),
            scope: ScopeKey {
                narrative_id: Some("arc-1".to_owned()),
                ..Default::default()
            },
            ..Default::default()
        },
        causal_substrate: Some(DocumentCausalSubstrate {
            propositions: vec![proposition],
            semantic_events: vec![EventRecord {
                event_id: Some(EventId("event:prop:0".to_owned())),
                label: "moved".into(),
                proposition_id: "prop:0".into(),
                ..Default::default()
            }],
            ..Default::default()
        }),
        ..Default::default()
    };

    let prototypes = build_prototypes(&[archive], None, None);
    let unit = prototypes
        .iter()
        .find(|prototype| prototype.node_id.starts_with(SEMANTIC_UNIT_PREFIX))
        .expect("semantic unit prototype");

    assert_eq!(unit.node_kind, SemanticGraphNodeKind::Event);
    assert_eq!(unit.ann_kind, EVENT_KIND);
    assert_eq!(unit.document_id.as_deref(), Some("doc-1"));
    assert_eq!(unit.primary_entity_id.as_deref(), Some("luffy"));
    assert_eq!(unit.secondary_entity_id.as_deref(), Some("harbor"));
    assert!(unit.text.contains("Luffy moved into the harbor"));
    assert!(unit
        .evidence_refs
        .iter()
        .any(|evidence| evidence == "document:doc-1#bytes:0-29"));
}

#[test]
fn dedupe_embedding_texts_maps_duplicate_rows_to_one_embedding() {
    let texts = vec!["alpha", "beta", "alpha", "gamma", "beta"];
    let (unique, row_map) = dedupe_embedding_texts(&texts);

    assert_eq!(unique, vec!["alpha", "beta", "gamma"]);
    assert_eq!(row_map, vec![0, 1, 0, 2, 1]);
}

#[test]
fn retain_configured_prototypes_can_stage_heavy_kinds_out() {
    let mut prototypes = vec![
        prototype("chunk::1", CHUNK_KIND, SemanticGraphNodeKind::Chunk),
        prototype("claim::1", CLAIM_KIND, SemanticGraphNodeKind::Claim),
        prototype("event::1", EVENT_KIND, SemanticGraphNodeKind::Event),
        prototype("state::1", STATE_KIND, SemanticGraphNodeKind::State),
    ];
    let config = SemanticGraphConfig {
        include_chunk_nodes: false,
        include_event_nodes: false,
        ..SemanticGraphConfig::default()
    };

    retain_configured_prototypes(&mut prototypes, &config);

    let node_kinds = prototypes
        .iter()
        .map(|prototype| prototype.node_kind)
        .collect::<Vec<_>>();
    assert_eq!(
        node_kinds,
        vec![SemanticGraphNodeKind::Claim, SemanticGraphNodeKind::State]
    );
}

#[test]
fn discourse_semantic_units_require_complete_situation_frame() {
    let proposition = Proposition {
        proposition_id: "prop:missing".into(),
        predicate: PredicateFrame {
            predicate: "moved".into(),
            trigger_range: SourceRange::new(6, 11),
            relation_type: "relates_to".into(),
        },
        ..Default::default()
    };
    let archive = DocumentArchive {
        manifest: DocumentManifest {
            document_id: "doc-1".to_owned(),
            ..Default::default()
        },
        causal_substrate: Some(DocumentCausalSubstrate {
            propositions: vec![proposition],
            semantic_events: vec![EventRecord {
                event_id: Some(EventId("event:missing".to_owned())),
                label: "moved".into(),
                proposition_id: "prop:missing".into(),
                ..Default::default()
            }],
            ..Default::default()
        }),
        ..Default::default()
    };

    let prototypes = build_prototypes(&[archive], None, None);

    assert!(!prototypes
        .iter()
        .any(|prototype| prototype.node_id.starts_with(SEMANTIC_UNIT_PREFIX)));
}

#[test]
fn compile_candidate_graph_batch_skips_rejected_edges() {
    let prototypes = vec![
        prototype("entity::alice", ENTITY_KIND, SemanticGraphNodeKind::Entity),
        prototype("graph::state::1", STATE_KIND, SemanticGraphNodeKind::State),
        prototype("graph::event::1", EVENT_KIND, SemanticGraphNodeKind::Event),
    ];
    let candidates = vec![
        SemanticGraphEdgeCandidate {
            edge_id: "edge-1".to_owned(),
            family: SemanticEdgeFamily::EntityStateSupport,
            source_node_id: "entity::alice".to_owned(),
            source_kind: SemanticGraphNodeKind::Entity,
            target_node_id: "graph::state::1".to_owned(),
            target_kind: SemanticGraphNodeKind::State,
            score_millis: 870,
            distance_millis: 120,
            candidate_status: SemanticCandidateStatus::ReviewedSupport,
            evidence_refs: Vec::new(),
            model_evidence: Vec::new(),
            nli_support_millis: Some(812),
            nli_contradiction_millis: Some(131),
        },
        SemanticGraphEdgeCandidate {
            edge_id: "edge-2".to_owned(),
            family: SemanticEdgeFamily::EntityEventSupport,
            source_node_id: "entity::alice".to_owned(),
            source_kind: SemanticGraphNodeKind::Entity,
            target_node_id: "graph::event::1".to_owned(),
            target_kind: SemanticGraphNodeKind::Event,
            score_millis: 410,
            distance_millis: 420,
            candidate_status: SemanticCandidateStatus::Rejected,
            evidence_refs: Vec::new(),
            model_evidence: Vec::new(),
            nli_support_millis: None,
            nli_contradiction_millis: None,
        },
    ];

    let batch =
        compile_candidate_graph_batch("scope-key", &prototypes, &candidates, 42, "test-model");

    assert_eq!(batch.edges.len(), 1);
    assert!(matches!(
        batch.scope,
        KernelMutationScope::Candidate { ref scope_key } if scope_key == "scope-key"
    ));
    assert_eq!(
        batch.edges[0]
            .attributes
            .get("nliSupportMillis")
            .and_then(serde_json::Value::as_u64),
        Some(812)
    );
}

#[test]
fn compile_candidate_graph_batch_materializes_semantic_unit_vertices() {
    let prototypes = vec![prototype(
        "semantic-unit::event::doc-1::event:prop:0",
        EVENT_KIND,
        SemanticGraphNodeKind::Event,
    )];
    let batch = compile_candidate_graph_batch("scope-key", &prototypes, &[], 42, "test-model");

    assert_eq!(batch.vertices.len(), 1);
    assert_eq!(batch.vertices[0].kind, "event");
    assert_eq!(batch.vertices[0].class, KernelVertexClass::Event);
}

#[test]
fn summarize_counts_reviewed_and_retained_edges() {
    let prototypes = vec![
        prototype("entity::alice", ENTITY_KIND, SemanticGraphNodeKind::Entity),
        prototype("graph::state::1", STATE_KIND, SemanticGraphNodeKind::State),
    ];
    let candidates = vec![
        SemanticGraphEdgeCandidate {
            edge_id: "edge-1".to_owned(),
            family: SemanticEdgeFamily::StateSupport,
            source_node_id: "graph::state::1".to_owned(),
            source_kind: SemanticGraphNodeKind::State,
            target_node_id: "graph::state::2".to_owned(),
            target_kind: SemanticGraphNodeKind::State,
            score_millis: 820,
            distance_millis: 140,
            candidate_status: SemanticCandidateStatus::ReviewedSupport,
            evidence_refs: Vec::new(),
            model_evidence: Vec::new(),
            nli_support_millis: Some(802),
            nli_contradiction_millis: Some(112),
        },
        SemanticGraphEdgeCandidate {
            edge_id: "edge-2".to_owned(),
            family: SemanticEdgeFamily::StateContradiction,
            source_node_id: "graph::state::1".to_owned(),
            source_kind: SemanticGraphNodeKind::State,
            target_node_id: "graph::state::3".to_owned(),
            target_kind: SemanticGraphNodeKind::State,
            score_millis: 600,
            distance_millis: 300,
            candidate_status: SemanticCandidateStatus::Rejected,
            evidence_refs: Vec::new(),
            model_evidence: Vec::new(),
            nli_support_millis: Some(220),
            nli_contradiction_millis: Some(230),
        },
    ];

    let summary = summarize(
        &prototypes,
        &candidates,
        &SemanticCandidateLifecycleStats::default(),
    );

    assert_eq!(summary.node_count, 2);
    assert_eq!(summary.edge_count, 1);
    assert_eq!(summary.reviewed_support_count, 1);
    assert_eq!(summary.reviewed_contradiction_count, 0);
}

#[test]
fn retain_live_candidates_prunes_dead_and_superseded_edges() {
    let graph_sidecar = GraphScopeSidecar {
        graph_batch: KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Projection {
                scope_key: "scope-key".to_owned(),
            },
            recorded_at: Some(42),
            vertices: Vec::new(),
            edges: vec![KernelEdge {
                source_id: KernelVertexId("graph::state::1".to_owned()),
                target_id: KernelVertexId("entity::alice".to_owned()),
                edge_type: KernelEdgeType("state_of".to_owned()),
                relation_class: KernelRelationClass::Memory,
                weight: 1,
                attributes: serde_json::json!({}),
                data: None,
                document_id: None,
                note_id: None,
                narrative_id: None,
                folder_id: None,
                folder_path: None,
                layer: KernelGraphLayer::Asserted,
                temporal: Default::default(),
                provenance: KernelProvenance::default(),
                resolution_facet: None,
            }],
        },
        ..GraphScopeSidecar::default()
    };
    let candidates = vec![
        SemanticGraphEdgeCandidate {
            edge_id: "semantic:entity_state_support:entity::alice:graph::state::1".to_owned(),
            family: SemanticEdgeFamily::EntityStateSupport,
            source_node_id: "entity::alice".to_owned(),
            source_kind: SemanticGraphNodeKind::Entity,
            target_node_id: "graph::state::1".to_owned(),
            target_kind: SemanticGraphNodeKind::State,
            score_millis: 910,
            distance_millis: 90,
            candidate_status: SemanticCandidateStatus::ReviewedSupport,
            evidence_refs: Vec::new(),
            model_evidence: Vec::new(),
            nli_support_millis: Some(880),
            nli_contradiction_millis: Some(10),
        },
        SemanticGraphEdgeCandidate {
            edge_id: "semantic:state_support:graph::state::2:graph::state::3".to_owned(),
            family: SemanticEdgeFamily::StateSupport,
            source_node_id: "graph::state::2".to_owned(),
            source_kind: SemanticGraphNodeKind::State,
            target_node_id: "graph::state::3".to_owned(),
            target_kind: SemanticGraphNodeKind::State,
            score_millis: 560,
            distance_millis: 440,
            candidate_status: SemanticCandidateStatus::Generated,
            evidence_refs: Vec::new(),
            model_evidence: Vec::new(),
            nli_support_millis: None,
            nli_contradiction_millis: None,
        },
        SemanticGraphEdgeCandidate {
            edge_id: "semantic:same_process:graph::event::1:graph::event::2".to_owned(),
            family: SemanticEdgeFamily::SameProcess,
            source_node_id: "graph::event::1".to_owned(),
            source_kind: SemanticGraphNodeKind::Event,
            target_node_id: "graph::event::2".to_owned(),
            target_kind: SemanticGraphNodeKind::Event,
            score_millis: 700,
            distance_millis: 300,
            candidate_status: SemanticCandidateStatus::Deferred,
            evidence_refs: Vec::new(),
            model_evidence: Vec::new(),
            nli_support_millis: Some(610),
            nli_contradiction_millis: Some(290),
        },
        SemanticGraphEdgeCandidate {
            edge_id: "semantic:state_contradiction:graph::state::4:graph::state::5".to_owned(),
            family: SemanticEdgeFamily::StateContradiction,
            source_node_id: "graph::state::4".to_owned(),
            source_kind: SemanticGraphNodeKind::State,
            target_node_id: "graph::state::5".to_owned(),
            target_kind: SemanticGraphNodeKind::State,
            score_millis: 820,
            distance_millis: 180,
            candidate_status: SemanticCandidateStatus::Rejected,
            evidence_refs: Vec::new(),
            model_evidence: Vec::new(),
            nli_support_millis: Some(120),
            nli_contradiction_millis: Some(180),
        },
    ];

    let (retained, stats) = retain_live_candidates(
        candidates,
        Some(&graph_sidecar),
        &default_candidate_lifecycle_policy(540),
    );

    assert_eq!(stats.superseded_asserted_count, 1);
    assert_eq!(stats.expired_count, 1);
    assert_eq!(stats.rejected_count, 1);
    assert_eq!(retained.len(), 1);
    assert_eq!(
        retained[0].edge_id,
        "semantic:same_process:graph::event::1:graph::event::2"
    );
}
