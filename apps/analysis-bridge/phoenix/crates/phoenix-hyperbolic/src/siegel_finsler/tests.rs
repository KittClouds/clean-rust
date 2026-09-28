use super::*;

#[test]
fn matrix_cells_use_symmetric_siegel_storage() {
    assert_eq!(siegel_matrix_cells(1), 1);
    assert_eq!(siegel_matrix_cells(2), 3);
    assert_eq!(siegel_matrix_cells(3), 6);
    assert_eq!(siegel_matrix_cells(4), 10);
}

#[test]
fn contract_serializes_native_phase_one_shape() {
    let contract = SiegelFinslerContract::new(SiegelFinslerContractInput {
        target_count: 263,
        directed_edge_count: 519,
        genus: DEFAULT_SIEGEL_GENUS,
        distance_evaluations: 34_453,
        asymmetric_pair_count: 712,
        hierarchy_violation_count: 3,
        timings: SiegelFinslerTimings {
            build_ms: 9,
            matrix_plan_ms: 2,
            distance_ms: 5,
            hierarchy_ms: 1,
            serialize_ms: 1,
        },
    });

    let json = serde_json::to_value(&contract).expect("contract should serialize");

    assert_eq!(json["projectionSpace"], SIEGEL_FINSLER_PROJECTION_SPACE);
    assert_eq!(json["targetCount"], 263);
    assert_eq!(json["directedEdgeCount"], 519);
    assert_eq!(json["genus"], 3);
    assert_eq!(json["matrixCells"], 6);
    assert_eq!(json["distanceEvaluations"], 34_453);
    assert_eq!(json["asymmetricPairCount"], 712);
    assert_eq!(json["hierarchyViolationCount"], 3);
    assert_eq!(json["timings"]["distanceMs"], 5);
    assert!(json.get("coordinates").is_none());
}

#[test]
fn estimated_bytes_are_deterministic_and_bounded_to_contract_payload() {
    let contract = SiegelFinslerContract::new(SiegelFinslerContractInput {
        target_count: 10,
        directed_edge_count: 4,
        genus: 3,
        ..SiegelFinslerContractInput::default()
    });

    assert_eq!(contract.estimated_bytes, 10 * 6 * 2 * 4 + 4 * 2 * 4);
}

#[test]
fn pair_builder_keeps_only_directed_structural_edges_under_caps() {
    let targets = [
        SiegelTargetView::new(0, 10, SiegelLane::Document, 0),
        SiegelTargetView::new(1, 11, SiegelLane::Chunk, 1),
        SiegelTargetView::new(2, 12, SiegelLane::Entity, 2),
    ];
    let edges = [
        SiegelDirectedEdgeView::new(0, 1, SiegelEdgeKind::Parent),
        SiegelDirectedEdgeView::new(1, 2, SiegelEdgeKind::Backbone),
        SiegelDirectedEdgeView::new(2, 1, SiegelEdgeKind::Associative),
        SiegelDirectedEdgeView::new(0, 9, SiegelEdgeKind::Bridge),
        SiegelDirectedEdgeView::new(1, 0, SiegelEdgeKind::Bridge),
    ];
    let caps = SiegelKernelCaps {
        max_targets: 3,
        max_directed_edges: 5,
        max_pairs: 2,
        max_distance_evaluations: 8,
    };
    let mut pairs = Vec::new();

    let counters = build_directed_pairs_into(&targets, &edges, caps, &mut pairs);

    assert_eq!(pairs.len(), 2);
    assert_eq!(pairs[0].kind, SiegelEdgeKind::Parent);
    assert_eq!(pairs[1].kind, SiegelEdgeKind::Backbone);
    assert_eq!(counters.skipped_edge_count, 2);
    assert_eq!(counters.capped_pair_count, 1);
}

#[test]
fn finsler_distance_is_directional_and_penalizes_hierarchy_violations() {
    let parent = SiegelTargetView::new(0, 10, SiegelLane::Document, 0);
    let child = SiegelTargetView::new(1, 11, SiegelLane::Chunk, 1);
    let parent_matrix = SiegelMatrixG3::new([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]);
    let child_matrix = SiegelMatrixG3::new([0.2, 0.3, 0.4, 0.3, 0.4, 0.5]);
    let pair = SiegelDirectedPair {
        from_ord: 0,
        to_ord: 1,
        kind: SiegelEdgeKind::Parent,
        weight_milli: 1_000,
    };

    let forward = finsler_distance(
        parent,
        child,
        &parent_matrix,
        &child_matrix,
        &pair,
        Default::default(),
    );
    let reverse = finsler_distance(
        child,
        parent,
        &child_matrix,
        &parent_matrix,
        &SiegelDirectedPair {
            from_ord: 1,
            to_ord: 0,
            ..pair
        },
        Default::default(),
    );

    assert_ne!(forward, reverse);
    assert!(reverse > forward);
}

#[test]
fn evaluator_counts_asymmetry_and_hierarchy_violations_without_all_pairs() {
    let targets = [
        SiegelTargetView::new(0, 10, SiegelLane::Document, 0),
        SiegelTargetView::new(1, 11, SiegelLane::Chunk, 1),
        SiegelTargetView::new(2, 12, SiegelLane::Entity, 2),
    ];
    let matrices = [
        SiegelMatrixG3::new([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]),
        SiegelMatrixG3::new([0.2, 0.3, 0.4, 0.5, 0.6, 0.7]),
        SiegelMatrixG3::new([0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
    ];
    let pairs = [
        SiegelDirectedPair {
            from_ord: 0,
            to_ord: 1,
            kind: SiegelEdgeKind::Parent,
            weight_milli: 1_000,
        },
        SiegelDirectedPair {
            from_ord: 2,
            to_ord: 1,
            kind: SiegelEdgeKind::Backbone,
            weight_milli: 1_000,
        },
    ];
    let caps = SiegelKernelCaps {
        max_targets: 3,
        max_directed_edges: 4,
        max_pairs: 2,
        max_distance_evaluations: 1,
    };

    let counters = evaluate_pairs_g3(&targets, &matrices, &pairs, caps, Default::default());

    assert_eq!(counters.pair_count, 2);
    assert_eq!(counters.distance_evaluations, 2);
    assert_eq!(counters.asymmetric_pair_count, 1);
    assert_eq!(counters.hierarchy_violation_count, 0);
    assert_eq!(counters.capped_distance_count, 1);
}

#[test]
fn counters_feed_phase_one_contract() {
    let counters = SiegelKernelCounters {
        target_count: 3,
        directed_edge_count: 2,
        distance_evaluations: 4,
        asymmetric_pair_count: 2,
        hierarchy_violation_count: 1,
        ..SiegelKernelCounters::default()
    };

    let contract = contract_from_counters(
        counters,
        3,
        SiegelFinslerTimings {
            build_ms: 1,
            matrix_plan_ms: 1,
            distance_ms: 2,
            hierarchy_ms: 1,
            serialize_ms: 1,
        },
    );

    assert_eq!(contract.projection_space, SIEGEL_FINSLER_PROJECTION_SPACE);
    assert_eq!(contract.target_count, 3);
    assert_eq!(contract.directed_edge_count, 2);
    assert_eq!(contract.distance_evaluations, 4);
    assert_eq!(contract.asymmetric_pair_count, 2);
    assert_eq!(contract.hierarchy_violation_count, 1);
    assert_eq!(contract.timings.total_observed_ms(), 6);
}

#[test]
fn native_run_request_compacts_graph_inputs_into_kernel_receipt() {
    let request = SiegelKernelRunRequest {
        genus: Some(3),
        targets: vec![
            target_input(10, "document_spine", 0),
            target_input(11, "chunk_spine", 1),
            target_input(12, "entity_anchor", 2),
            target_input(13, "causal_fact", 3),
        ],
        edges: vec![
            edge_input(0, 1, "parent"),
            edge_input(1, 2, "parent"),
            edge_input(2, 3, "backbone"),
            edge_input(3, 1, "co_occurs_with"),
            edge_input(9, 1, "bridge"),
        ],
        caps: Some(SiegelKernelCaps {
            max_targets: 8,
            max_directed_edges: 8,
            max_pairs: 8,
            max_distance_evaluations: 8,
        }),
        config: None,
    };

    let receipt = run_siegel_finsler_kernel(&request);

    assert_eq!(
        receipt.contract.projection_space,
        SIEGEL_FINSLER_PROJECTION_SPACE
    );
    assert_eq!(receipt.contract.target_count, 4);
    assert_eq!(receipt.contract.directed_edge_count, 5);
    assert_eq!(receipt.contract.matrix_cells, 6);
    assert_eq!(receipt.parent_pairs, 2);
    assert_eq!(receipt.backbone_pairs, 1);
    assert_eq!(receipt.bridge_pairs, 0);
    assert_eq!(receipt.counters.skipped_edge_count, 2);
    assert_eq!(receipt.contract.distance_evaluations, 6);
}

#[test]
fn native_run_request_honors_hard_caps_before_distances() {
    let request = SiegelKernelRunRequest {
        targets: vec![
            target_input(10, "document_spine", 0),
            target_input(11, "chunk_spine", 1),
            target_input(12, "entity_anchor", 2),
        ],
        edges: vec![
            edge_input(0, 1, "parent"),
            edge_input(1, 2, "parent"),
            edge_input(0, 2, "bridge"),
        ],
        caps: Some(SiegelKernelCaps {
            max_targets: 3,
            max_directed_edges: 2,
            max_pairs: 1,
            max_distance_evaluations: 1,
        }),
        ..SiegelKernelRunRequest::default()
    };

    let receipt = run_siegel_finsler_kernel(&request);

    assert_eq!(receipt.counters.directed_edge_count, 2);
    assert_eq!(receipt.counters.capped_edge_count, 1);
    assert_eq!(receipt.counters.pair_count, 1);
    assert_eq!(receipt.counters.capped_pair_count, 1);
    assert_eq!(receipt.counters.distance_evaluations, 2);
    assert_eq!(receipt.counters.capped_distance_count, 0);
}

fn target_input(stable_hash: u64, lane: &str, hierarchy_depth: u16) -> SiegelTargetInput {
    SiegelTargetInput {
        stable_hash,
        lane: lane.to_owned(),
        hierarchy_depth,
        confidence_milli: Some(900),
    }
}

fn edge_input(from_ord: u32, to_ord: u32, kind: &str) -> SiegelEdgeInput {
    SiegelEdgeInput {
        from_ord,
        to_ord,
        kind: kind.to_owned(),
        weight_milli: Some(1_000),
    }
}
