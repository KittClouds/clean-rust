use super::{
    bounded_walk_projected_graph, KernelWalkBudget, KernelWalkScoring, KernelWalkSeed,
    KernelWalkSeedFamily,
};
use crate::{
    KernelEdge, KernelEdgeType, KernelGraphLayer, KernelMutationBatch, KernelMutationScope,
    KernelProvenance, KernelVertex, KernelVertexClass, KernelVertexId, KernelViewRequest,
    PhoenixGraphKernel,
};
use serde_json::json;

#[test]
fn projected_walk_respects_per_family_fanout() {
    let edges = (0..8)
        .map(|index| edge("seed", &format!("chunk_{index}"), "under_view"))
        .collect::<Vec<_>>();
    let view = view_with(
        [
            vertex("seed", "entity", KernelVertexClass::Entity, "a"),
            vertex("chunk_0", "chunk", KernelVertexClass::Chunk, "a"),
            vertex("chunk_1", "chunk", KernelVertexClass::Chunk, "a"),
            vertex("chunk_2", "chunk", KernelVertexClass::Chunk, "a"),
            vertex("chunk_3", "chunk", KernelVertexClass::Chunk, "a"),
            vertex("chunk_4", "chunk", KernelVertexClass::Chunk, "a"),
            vertex("chunk_5", "chunk", KernelVertexClass::Chunk, "a"),
            vertex("chunk_6", "chunk", KernelVertexClass::Chunk, "a"),
            vertex("chunk_7", "chunk", KernelVertexClass::Chunk, "a"),
        ],
        edges,
    );
    let result = bounded_walk_projected_graph(
        &view,
        &[],
        &[seed("seed", KernelWalkSeedFamily::Entity)],
        KernelWalkBudget {
            max_per_family_fanout: 2,
            max_depth: 1,
            compact: false,
            ..KernelWalkBudget::default()
        },
        KernelWalkScoring::default(),
        |_| true,
    );

    let chunk_count = result
        .included_vertex_ids
        .iter()
        .filter(|id| id.starts_with("chunk_"))
        .count();
    assert_eq!(chunk_count, 2);
    assert!(result.stats.pruned_by_family_fanout > 0);
}

#[test]
fn projected_walk_prunes_contradiction_debt() {
    let view = view_with(
        [
            vertex("seed", "claim", KernelVertexClass::Generic, "a"),
            vertex("supported", "state", KernelVertexClass::State, "a"),
            vertex("conflict", "conflict", KernelVertexClass::State, "a"),
        ],
        vec![
            edge("seed", "supported", "supported_by"),
            edge("seed", "conflict", "contradicts"),
        ],
    );
    let result = bounded_walk_projected_graph(
        &view,
        &[],
        &[seed("seed", KernelWalkSeedFamily::Lexical)],
        KernelWalkBudget {
            max_depth: 1,
            max_contradiction_debt_millis: 100,
            compact: false,
            ..KernelWalkBudget::default()
        },
        KernelWalkScoring::default(),
        |_| true,
    );

    assert!(result
        .included_vertex_ids
        .iter()
        .any(|id| id == "supported"));
    assert!(!result.included_vertex_ids.iter().any(|id| id == "conflict"));
    assert!(result.stats.pruned_by_contradiction_debt > 0);
}

#[test]
fn projected_walk_charges_cross_island_bridges() {
    let view = view_with(
        [
            vertex("seed", "claim", KernelVertexClass::Generic, "island-a"),
            vertex("remote", "claim", KernelVertexClass::Generic, "island-b"),
        ],
        vec![edge("seed", "remote", "context_island_bridge")],
    );
    let result = bounded_walk_projected_graph(
        &view,
        &[],
        &[seed("seed", KernelWalkSeedFamily::Lexical)],
        KernelWalkBudget {
            max_depth: 1,
            compact: false,
            projected_csr_diagnostics: true,
            ..KernelWalkBudget::default()
        },
        KernelWalkScoring {
            cross_island_cost_millis: 5_000,
            ..KernelWalkScoring::default()
        },
        |_| true,
    );

    assert!(result.included_vertex_ids.iter().any(|id| id == "seed"));
    assert!(!result.included_vertex_ids.iter().any(|id| id == "remote"));
    assert!(result.stats.projected_csr_memory_bytes > 0);
}

#[test]
fn projected_walk_respects_edge_budget() {
    let view = view_with(
        [
            vertex("seed", "entity", KernelVertexClass::Entity, "a"),
            vertex("state", "state", KernelVertexClass::State, "a"),
            vertex("claim", "claim", KernelVertexClass::Generic, "a"),
        ],
        vec![
            edge("seed", "state", "state_of"),
            edge("state", "claim", "supported_by"),
            edge("seed", "claim", "about"),
        ],
    );
    let result = bounded_walk_projected_graph(
        &view,
        &[],
        &[seed("seed", KernelWalkSeedFamily::Entity)],
        KernelWalkBudget {
            max_edges: 1,
            max_depth: 2,
            compact: false,
            ..KernelWalkBudget::default()
        },
        KernelWalkScoring::default(),
        |_| true,
    );

    let edge_count = result.snapshot.asserted_edges.len() + result.snapshot.candidate_edges.len();
    assert!(edge_count <= 1);
}

fn view_with<const N: usize>(
    vertices: [KernelVertex; N],
    edges: Vec<KernelEdge>,
) -> crate::KernelQueryView {
    let mut kernel = PhoenixGraphKernel::new();
    kernel
        .apply_kernel_batch(KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Full,
            recorded_at: None,
            vertices: vertices.into(),
            edges,
        })
        .expect("apply kernel batch");
    kernel.query_view(KernelViewRequest {
        include_candidate_graph: true,
        ..KernelViewRequest::default()
    })
}

fn seed(vertex_id: &str, family: KernelWalkSeedFamily) -> KernelWalkSeed {
    KernelWalkSeed {
        vertex_id: vertex_id.to_owned(),
        family,
        prize_millis: 1_000,
        evidence_refs: vec![format!("graph_vertex:{vertex_id}")],
    }
}

fn vertex(id: &str, kind: &str, class: KernelVertexClass, island: &str) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(id.to_owned()),
        kind: kind.to_owned(),
        class,
        value: json!({"status":"active"}),
        attributes: json!({"contextIslandId": island}),
        provenance: KernelProvenance {
            confidence: Some(0.9),
            evidence_refs: vec![format!("graph_vertex:{id}")],
            ..KernelProvenance::default()
        },
        ..KernelVertex::default()
    }
}

fn edge(source: &str, target: &str, edge_type: &str) -> KernelEdge {
    KernelEdge {
        source_id: KernelVertexId(source.to_owned()),
        target_id: KernelVertexId(target.to_owned()),
        edge_type: KernelEdgeType(edge_type.to_owned()),
        layer: KernelGraphLayer::Asserted,
        provenance: KernelProvenance {
            confidence: Some(0.9),
            ..KernelProvenance::default()
        },
        ..KernelEdge::default()
    }
}
