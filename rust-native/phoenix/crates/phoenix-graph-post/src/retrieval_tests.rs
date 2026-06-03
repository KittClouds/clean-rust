use phoenix_graph_kernel::{
    KernelBiTemporal, KernelEdge, KernelEdgeType, KernelGraphLayer, KernelGraphSnapshot,
    KernelProvenance, KernelRegionProfile, KernelRelationClass, KernelVertex, KernelVertexClass,
    KernelVertexId,
};
use serde_json::json;

use crate::retrieval::{
    GraphRetrievedCausalExplanationQueryRequest, GraphRetrievedHistoryQueryRequest,
    GraphRetrievedSeed, GraphRetrievedWorldStateQueryRequest,
};
use crate::retrieval_causal::build_causal_region;
use crate::retrieval_common::{
    build_region_from_view_profile, graph_local_entity_slot_seeds, graph_local_target_seeds,
    kernel_from_snapshot, score_from_distance,
};
use crate::retrieval_history::build_history_region;
use crate::retrieval_history::history_seed_surface;
use crate::retrieval_receipts::GraphNativeRetrievalStrategy;
use crate::retrieval_world::build_world_state_region;
use crate::retrieval_world::world_seed_surface;
use phoenix_types::ScopeKey;

fn vertex(id: &str, kind: &str, entity_id: Option<&str>, slot_key: Option<&str>) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(id.to_owned()),
        kind: kind.to_owned(),
        class: match kind {
            "state" => KernelVertexClass::State,
            "entity" => KernelVertexClass::Entity,
            _ => KernelVertexClass::Generic,
        },
        labels: Vec::new(),
        weight: 1,
        value: json!({"slotKey": slot_key}),
        attributes: json!({}),
        temporal: KernelBiTemporal::default(),
        provenance: KernelProvenance::default(),
        entity_id: entity_id.map(str::to_owned),
        search_chunk_id: None,
        document_id: None,
        note_id: None,
        narrative_id: None,
        folder_id: None,
        folder_path: None,
        chapter_id: None,
        chapters: Vec::new(),
        boundary_id: None,
        boundary_ordinal: None,
        boundary_kind: None,
        boundary_ordinals: Vec::new(),
        entity_facet: None,
        calendar_facet: None,
    }
}

fn edge(source: &str, target: &str, edge_type: &str) -> KernelEdge {
    KernelEdge {
        source_id: KernelVertexId(source.to_owned()),
        target_id: KernelVertexId(target.to_owned()),
        edge_type: KernelEdgeType(edge_type.to_owned()),
        relation_class: KernelRelationClass::Memory,
        weight: 1,
        attributes: json!({}),
        data: None,
        document_id: None,
        note_id: None,
        narrative_id: None,
        folder_id: None,
        folder_path: None,
        layer: KernelGraphLayer::Asserted,
        temporal: KernelBiTemporal::default(),
        provenance: KernelProvenance::default(),
        resolution_facet: None,
    }
}

#[test]
fn world_state_region_keeps_entity_slot_anchor_and_support_chain() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex("graph::entity::alice", "entity", Some("alice"), None),
            vertex(
                "graph::state::1",
                "state",
                Some("alice"),
                Some("entity.employer"),
            ),
            vertex(
                "graph::claim::1",
                "claim",
                Some("alice"),
                Some("entity.employer"),
            ),
            vertex(
                "graph::claim::2",
                "claim",
                Some("alice"),
                Some("entity.location"),
            ),
            vertex("graph::chunk::1", "chunk", None, None),
        ],
        asserted_edges: vec![
            edge("graph::state::1", "graph::entity::alice", "state_of"),
            edge("graph::state::1", "graph::claim::1", "supported_by"),
            edge(
                "graph::claim::1",
                "graph::chunk::1",
                "semantic::chunk_neighbor",
            ),
            edge("graph::claim::2", "graph::entity::alice", "subject"),
        ],
        candidate_edges: Vec::new(),
    };
    let request = GraphRetrievedWorldStateQueryRequest {
        query_text: "where does alice work".to_owned(),
        entity_id: "alice".to_owned(),
        slot_key: "entity.employer".to_owned(),
        valid_at: None,
        recorded_at: None,
        include_candidate_graph: true,
        seed_limit: 6,
        oversample: 12,
        expansion_hops: 2,
        region_node_limit: 12,
    };
    let seeds = vec![GraphRetrievedSeed {
        node_id: "graph::claim::1".to_owned(),
        node_kind: "claim".to_owned(),
        score_millis: 930,
        distance_millis: 70,
        document_id: None,
        narrative_id: None,
        evidence_refs: Vec::new(),
    }];

    let (_, region) = build_world_state_region(&snapshot, &request, &seeds);

    assert!(region
        .included_vertex_ids
        .contains(&"graph::state::1".to_owned()));
    assert!(region
        .included_vertex_ids
        .contains(&"graph::claim::1".to_owned()));
    assert!(region
        .included_vertex_ids
        .contains(&"graph::entity::alice".to_owned()));
    assert!(!region
        .included_vertex_ids
        .contains(&"graph::claim::2".to_owned()));
    assert!(!region.truncated);
    let receipt = region
        .native_retrieval_receipt
        .as_ref()
        .expect("simple region receipt");
    assert_eq!(
        receipt.strategy,
        GraphNativeRetrievalStrategy::SimpleRegionExpansion
    );
    assert_eq!(receipt.region.vertex_count, region.vertex_count);
}

#[test]
fn bounded_view_region_records_walk_and_pcst_receipt() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex("graph::entity::alice", "entity", Some("alice"), None),
            vertex(
                "graph::state::1",
                "state",
                Some("alice"),
                Some("entity.employer"),
            ),
            vertex(
                "graph::claim::1",
                "claim",
                Some("alice"),
                Some("entity.employer"),
            ),
        ],
        asserted_edges: vec![
            edge("graph::state::1", "graph::entity::alice", "state_of"),
            edge("graph::state::1", "graph::claim::1", "supported_by"),
        ],
        candidate_edges: Vec::new(),
    };
    let kernel = kernel_from_snapshot(&ScopeKey::default(), &snapshot).expect("region kernel");
    let view = kernel.query_view(phoenix_graph_kernel::KernelViewRequest {
        valid_at: None,
        recorded_at: None,
        include_candidate_graph: true,
    });

    let (_, region) = build_region_from_view_profile(
        &view,
        vec!["graph::entity::alice".to_owned()],
        &[],
        12,
        2,
        |_| true,
        KernelRegionProfile::WorldState,
    );

    let receipt = region
        .native_retrieval_receipt
        .as_ref()
        .expect("bounded walk receipt");
    assert_eq!(
        receipt.strategy,
        GraphNativeRetrievalStrategy::BoundedWalkPcst
    );
    assert!(receipt
        .walk
        .as_ref()
        .is_some_and(|walk| walk.pcst_compacted));
}

#[test]
fn world_state_region_expands_through_same_slot_family_candidate_edges() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex("graph::entity::alice", "entity", Some("alice"), None),
            vertex(
                "graph::state::1",
                "state",
                Some("alice"),
                Some("entity.employer"),
            ),
            vertex(
                "graph::claim::1",
                "claim",
                Some("alice"),
                Some("entity.employer"),
            ),
        ],
        asserted_edges: vec![edge("graph::state::1", "graph::entity::alice", "state_of")],
        candidate_edges: vec![KernelEdge {
            layer: KernelGraphLayer::Candidate,
            relation_class: KernelRelationClass::Candidate,
            ..edge(
                "graph::claim::1",
                "graph::state::1",
                "semantic::same_slot_family",
            )
        }],
    };
    let request = GraphRetrievedWorldStateQueryRequest {
        query_text: "who employs alice".to_owned(),
        entity_id: "alice".to_owned(),
        slot_key: "entity.employer".to_owned(),
        valid_at: None,
        recorded_at: None,
        include_candidate_graph: true,
        seed_limit: 6,
        oversample: 12,
        expansion_hops: 2,
        region_node_limit: 12,
    };

    let (_, region) = build_world_state_region(&snapshot, &request, &[]);

    assert!(region
        .included_vertex_ids
        .contains(&"graph::claim::1".to_owned()));
    assert_eq!(region.candidate_edge_count, 1);
}

#[test]
fn semantic_score_from_distance_is_monotonic() {
    assert!(score_from_distance(0.0) > score_from_distance(0.5));
    assert!(score_from_distance(0.5) > score_from_distance(1.5));
}

#[test]
fn history_region_keeps_state_changes_and_issues_for_same_entity_slot() {
    let mut state_old = vertex(
        "graph::state::old",
        "state",
        Some("alice"),
        Some("entity.employer"),
    );
    state_old.temporal.valid_from = Some(10);
    let mut state_new = vertex(
        "graph::state::new",
        "state",
        Some("alice"),
        Some("entity.employer"),
    );
    state_new.temporal.valid_from = Some(20);
    let conflict = KernelVertex {
        value: json!({"kind": "contradiction", "status": "open", "slotKey": "entity.employer"}),
        attributes: json!({"claimIds": ["claim-1"], "reason": "conflict", "preferredClaimId": "claim-1"}),
        ..vertex(
            "graph::conflict::1",
            "conflict",
            Some("alice"),
            Some("entity.employer"),
        )
    };
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex("graph::entity::alice", "entity", Some("alice"), None),
            state_old,
            state_new,
            conflict,
            vertex(
                "graph::state::other",
                "state",
                Some("alice"),
                Some("entity.location"),
            ),
        ],
        asserted_edges: vec![
            edge("graph::state::old", "graph::entity::alice", "state_of"),
            edge("graph::state::new", "graph::entity::alice", "state_of"),
            edge("graph::conflict::1", "graph::state::new", "about"),
        ],
        candidate_edges: Vec::new(),
    };
    let request = GraphRetrievedHistoryQueryRequest {
        query_text: "employment history for alice".to_owned(),
        entity_id: "alice".to_owned(),
        slot_key: Some("entity.employer".to_owned()),
        since_valid_at: 0,
        ..GraphRetrievedHistoryQueryRequest::default()
    };
    let seeds = vec![GraphRetrievedSeed {
        node_id: "graph::state::new".to_owned(),
        node_kind: "state".to_owned(),
        score_millis: 900,
        distance_millis: 100,
        document_id: None,
        narrative_id: None,
        evidence_refs: Vec::new(),
    }];

    let (_, region) = build_history_region(&snapshot, &request, &seeds);

    assert!(region
        .included_vertex_ids
        .contains(&"graph::state::old".to_owned()));
    assert!(region
        .included_vertex_ids
        .contains(&"graph::state::new".to_owned()));
    assert!(region
        .included_vertex_ids
        .contains(&"graph::conflict::1".to_owned()));
    assert!(!region
        .included_vertex_ids
        .contains(&"graph::state::other".to_owned()));
}

#[test]
fn causal_region_keeps_target_support_and_semantic_neighbors() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex(
                "graph::event::1",
                "event",
                Some("alice"),
                Some("entity.employer"),
            ),
            vertex(
                "graph::claim::1",
                "claim",
                Some("alice"),
                Some("entity.employer"),
            ),
            vertex(
                "graph::event::2",
                "event",
                Some("alice"),
                Some("entity.employer"),
            ),
            vertex("graph::entity::alice", "entity", Some("alice"), None),
            vertex("graph::chunk::1", "chunk", None, None),
        ],
        asserted_edges: vec![
            edge("graph::event::2", "graph::event::1", "causal_link"),
            edge("graph::claim::1", "graph::event::1", "supported_by"),
            edge("graph::event::1", "graph::entity::alice", "subject"),
            edge(
                "graph::claim::1",
                "graph::chunk::1",
                "semantic::claim_support",
            ),
        ],
        candidate_edges: Vec::new(),
    };
    let request = GraphRetrievedCausalExplanationQueryRequest {
        query_text: "what led to alice employer change".to_owned(),
        target_vertex_id: "graph::event::1".to_owned(),
        ..GraphRetrievedCausalExplanationQueryRequest::default()
    };
    let seeds = vec![GraphRetrievedSeed {
        node_id: "graph::claim::1".to_owned(),
        node_kind: "claim".to_owned(),
        score_millis: 880,
        distance_millis: 120,
        document_id: None,
        narrative_id: None,
        evidence_refs: Vec::new(),
    }];

    let (_, region) = build_causal_region(&snapshot, &request, &seeds);

    assert!(region
        .included_vertex_ids
        .contains(&"graph::event::1".to_owned()));
    assert!(region
        .included_vertex_ids
        .contains(&"graph::event::2".to_owned()));
    assert!(region
        .included_vertex_ids
        .contains(&"graph::claim::1".to_owned()));
    assert!(region
        .included_vertex_ids
        .contains(&"graph::entity::alice".to_owned()));
}

#[test]
fn causal_region_expands_through_same_process_candidate_edges() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex(
                "graph::event::1",
                "event",
                Some("alice"),
                Some("entity.location"),
            ),
            vertex(
                "graph::event::2",
                "event",
                Some("alice"),
                Some("entity.location"),
            ),
            vertex("graph::entity::alice", "entity", Some("alice"), None),
        ],
        asserted_edges: vec![edge("graph::event::1", "graph::entity::alice", "subject")],
        candidate_edges: vec![KernelEdge {
            layer: KernelGraphLayer::Candidate,
            relation_class: KernelRelationClass::Candidate,
            ..edge(
                "graph::event::1",
                "graph::event::2",
                "semantic::same_process",
            )
        }],
    };
    let request = GraphRetrievedCausalExplanationQueryRequest {
        query_text: "what is in the same process as alice location change".to_owned(),
        target_vertex_id: "graph::event::1".to_owned(),
        ..GraphRetrievedCausalExplanationQueryRequest::default()
    };

    let (_, region) = build_causal_region(&snapshot, &request, &[]);

    assert!(region
        .included_vertex_ids
        .contains(&"graph::event::2".to_owned()));
    assert_eq!(region.candidate_edge_count, 1);
}

#[test]
fn world_state_region_does_not_expand_through_related_event() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex("graph::entity::alice", "entity", Some("alice"), None),
            vertex(
                "graph::state::1",
                "state",
                Some("alice"),
                Some("entity.location"),
            ),
            vertex(
                "graph::event::1",
                "event",
                Some("alice"),
                Some("entity.location"),
            ),
            vertex(
                "graph::event::2",
                "event",
                Some("bob"),
                Some("entity.employer"),
            ),
        ],
        asserted_edges: vec![edge("graph::state::1", "graph::entity::alice", "state_of")],
        candidate_edges: vec![KernelEdge {
            layer: KernelGraphLayer::Candidate,
            relation_class: KernelRelationClass::Candidate,
            ..edge(
                "graph::event::1",
                "graph::event::2",
                "semantic::related_event",
            )
        }],
    };
    let request = GraphRetrievedWorldStateQueryRequest {
        query_text: "where is alice".to_owned(),
        entity_id: "alice".to_owned(),
        slot_key: "entity.location".to_owned(),
        valid_at: None,
        recorded_at: None,
        include_candidate_graph: true,
        seed_limit: 6,
        oversample: 12,
        expansion_hops: 2,
        region_node_limit: 12,
    };

    let (_, region) = build_world_state_region(&snapshot, &request, &[]);

    assert!(!region
        .included_vertex_ids
        .contains(&"graph::event::2".to_owned()));
    assert_eq!(region.candidate_edge_count, 0);
}

#[test]
fn history_region_expands_through_related_event_candidate_edges() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex("graph::entity::alice", "entity", Some("alice"), None),
            vertex(
                "graph::state::1",
                "state",
                Some("alice"),
                Some("entity.location"),
            ),
            vertex(
                "graph::event::1",
                "event",
                Some("alice"),
                Some("entity.location"),
            ),
            vertex(
                "graph::event::2",
                "event",
                Some("bob"),
                Some("entity.employer"),
            ),
        ],
        asserted_edges: vec![edge("graph::state::1", "graph::entity::alice", "state_of")],
        candidate_edges: vec![KernelEdge {
            layer: KernelGraphLayer::Candidate,
            relation_class: KernelRelationClass::Candidate,
            ..edge(
                "graph::event::1",
                "graph::event::2",
                "semantic::related_event",
            )
        }],
    };
    let request = GraphRetrievedHistoryQueryRequest {
        query_text: "history around alice location".to_owned(),
        entity_id: "alice".to_owned(),
        slot_key: Some("entity.location".to_owned()),
        since_valid_at: 0,
        ..GraphRetrievedHistoryQueryRequest::default()
    };
    let seeds = vec![GraphRetrievedSeed {
        node_id: "graph::event::1".to_owned(),
        node_kind: "event".to_owned(),
        score_millis: 880,
        distance_millis: 120,
        document_id: None,
        narrative_id: None,
        evidence_refs: Vec::new(),
    }];

    let (_, region) = build_history_region(&snapshot, &request, &seeds);

    assert!(region
        .included_vertex_ids
        .contains(&"graph::event::2".to_owned()));
    assert_eq!(region.candidate_edge_count, 1);
}

#[test]
fn causal_region_expands_through_related_event_candidate_edges() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex(
                "graph::event::1",
                "event",
                Some("alice"),
                Some("entity.location"),
            ),
            vertex(
                "graph::event::2",
                "event",
                Some("bob"),
                Some("entity.employer"),
            ),
        ],
        asserted_edges: Vec::new(),
        candidate_edges: vec![KernelEdge {
            layer: KernelGraphLayer::Candidate,
            relation_class: KernelRelationClass::Candidate,
            ..edge(
                "graph::event::1",
                "graph::event::2",
                "semantic::related_event",
            )
        }],
    };
    let request = GraphRetrievedCausalExplanationQueryRequest {
        query_text: "what event is nearby".to_owned(),
        target_vertex_id: "graph::event::1".to_owned(),
        ..GraphRetrievedCausalExplanationQueryRequest::default()
    };

    let (_, region) = build_causal_region(&snapshot, &request, &[]);

    assert!(region
        .included_vertex_ids
        .contains(&"graph::event::2".to_owned()));
    assert_eq!(region.candidate_edge_count, 1);
}

#[test]
fn kernel_from_snapshot_accepts_candidate_edges_for_region_rebuilds() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex(
                "graph::claim::1",
                "claim",
                Some("alice"),
                Some("entity.employer"),
            ),
            vertex(
                "graph::claim::2",
                "claim",
                Some("alice"),
                Some("entity.employer"),
            ),
        ],
        asserted_edges: Vec::new(),
        candidate_edges: vec![KernelEdge {
            layer: KernelGraphLayer::Candidate,
            ..edge(
                "graph::claim::1",
                "graph::claim::2",
                "semantic::claim_support",
            )
        }],
    };

    let kernel = kernel_from_snapshot(&ScopeKey::default(), &snapshot).expect("region kernel");
    let view = kernel.view_as_of(phoenix_graph_kernel::KernelViewRequest {
        valid_at: None,
        recorded_at: None,
        include_candidate_graph: true,
    });

    assert_eq!(view.candidate_edges.len(), 1);
}

#[test]
fn world_and_slot_history_share_the_same_seed_surface() {
    let world = GraphRetrievedWorldStateQueryRequest {
        query_text: "current entity.employer for alice".to_owned(),
        entity_id: "alice".to_owned(),
        slot_key: "entity.employer".to_owned(),
        ..GraphRetrievedWorldStateQueryRequest::default()
    };
    let history = GraphRetrievedHistoryQueryRequest {
        query_text: "history of entity.employer for alice".to_owned(),
        entity_id: "alice".to_owned(),
        slot_key: Some("entity.employer".to_owned()),
        since_valid_at: 0,
        ..GraphRetrievedHistoryQueryRequest::default()
    };

    assert_eq!(world_seed_surface(&world), history_seed_surface(&history));
}

#[test]
fn entity_slot_seed_surface_uses_retained_query_view() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex("graph::entity::alice", "entity", Some("alice"), None),
            vertex(
                "graph::state::alice::employer",
                "state",
                Some("alice"),
                Some("entity.employer"),
            ),
            vertex(
                "graph::state::alice::location",
                "state",
                Some("alice"),
                Some("entity.location"),
            ),
            vertex("graph::entity::bob", "entity", Some("bob"), None),
        ],
        asserted_edges: Vec::new(),
        candidate_edges: Vec::new(),
    };
    let kernel = kernel_from_snapshot(&ScopeKey::default(), &snapshot).expect("region kernel");
    let view = kernel.query_view(phoenix_graph_kernel::KernelViewRequest {
        valid_at: None,
        recorded_at: None,
        include_candidate_graph: true,
    });

    let seeds = graph_local_entity_slot_seeds(&view, "alice", "entity.employer", 8);
    let seed_ids = seeds
        .iter()
        .map(|seed| seed.node_id.as_str())
        .collect::<Vec<_>>();

    assert_eq!(
        seed_ids,
        vec!["graph::entity::alice", "graph::state::alice::employer"]
    );
}

#[test]
fn target_seed_surface_uses_retained_query_view_neighbors() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            vertex("graph::entity::alice", "entity", Some("alice"), None),
            vertex("graph::event::launch", "event", Some("alice"), None),
            vertex("graph::claim::launch", "claim", None, None),
            vertex("graph::event::other", "event", Some("bob"), None),
        ],
        asserted_edges: vec![edge(
            "graph::event::launch",
            "graph::claim::launch",
            "supported_by",
        )],
        candidate_edges: Vec::new(),
    };
    let kernel = kernel_from_snapshot(&ScopeKey::default(), &snapshot).expect("region kernel");
    let view = kernel.query_view(phoenix_graph_kernel::KernelViewRequest {
        valid_at: None,
        recorded_at: None,
        include_candidate_graph: true,
    });

    let seeds = graph_local_target_seeds(&view, "graph::event::launch", 8);
    let seed_ids = seeds
        .iter()
        .map(|seed| seed.node_id.as_str())
        .collect::<Vec<_>>();

    assert_eq!(
        seed_ids,
        vec![
            "graph::event::launch",
            "graph::entity::alice",
            "graph::claim::launch"
        ]
    );
}
