use crate::{
    galaxy_graph_from_snapshot, GalaxyBuildOptions, GalaxyEdgeRecord, GalaxyNodeRecord, KernelEdge,
    KernelEdgeType, KernelEntityFacet, KernelGraphLayer, KernelGraphSnapshot, KernelVertex,
    KernelVertexClass, KernelVertexId,
};
use serde_json::Value;
use std::mem;

fn entity(id: &str, label: &str, kind: &str) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(id.to_owned()),
        kind: kind.to_owned(),
        class: KernelVertexClass::Entity,
        labels: vec![label.to_owned()],
        weight: 7,
        value: Value::Null,
        entity_id: Some(id.to_owned()),
        entity_facet: Some(KernelEntityFacet {
            canonical_entity_id: Some(id.to_owned()),
            surface: Some(label.to_owned()),
            entity_kind: Some(kind.to_owned()),
        }),
        ..KernelVertex::default()
    }
}

fn entity_with_vertex_id(vertex_id: &str, entity_id: &str, label: &str) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(vertex_id.to_owned()),
        entity_id: Some(entity_id.to_owned()),
        entity_facet: Some(KernelEntityFacet {
            canonical_entity_id: Some(entity_id.to_owned()),
            surface: Some(label.to_owned()),
            entity_kind: Some("Character".to_owned()),
        }),
        ..entity(entity_id, label, "Character")
    }
}

fn relation(source: &str, target: &str, weight: i64, layer: KernelGraphLayer) -> KernelEdge {
    KernelEdge {
        source_id: KernelVertexId(source.to_owned()),
        target_id: KernelVertexId(target.to_owned()),
        edge_type: KernelEdgeType("cooccurs".to_owned()),
        weight,
        layer,
        ..KernelEdge::default()
    }
}

#[test]
fn builds_dense_binary_pack_from_entity_snapshot() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            entity("zorian", "Zorian", "Character"),
            entity("kirielle", "Kirielle", "Character"),
        ],
        asserted_edges: vec![relation(
            "zorian",
            "kirielle",
            5,
            KernelGraphLayer::Asserted,
        )],
        ..KernelGraphSnapshot::default()
    };

    let pack = galaxy_graph_from_snapshot(&snapshot, GalaxyBuildOptions::default());

    assert_eq!(pack.nodes.len(), 2);
    assert_eq!(pack.edges.len(), 1);
    assert_eq!(pack.edges[0].weight_millis, 5);
    assert_eq!(pack.node_label(pack.nodes[0]), Some("Zorian"));
    assert_eq!(
        pack.node_bytes().len(),
        pack.nodes.len() * mem::size_of::<GalaxyNodeRecord>()
    );
    assert_eq!(
        pack.edge_bytes().len(),
        pack.edges.len() * mem::size_of::<GalaxyEdgeRecord>()
    );
}

#[test]
fn excludes_candidate_edges_by_default() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![entity("a", "A", "Character"), entity("b", "B", "Character")],
        candidate_edges: vec![relation("a", "b", 9, KernelGraphLayer::Candidate)],
        ..KernelGraphSnapshot::default()
    };

    let pack = galaxy_graph_from_snapshot(&snapshot, GalaxyBuildOptions::default());

    assert!(pack.edges.is_empty());
}

#[test]
fn aggregates_undirected_duplicate_edges() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![entity("a", "A", "Character"), entity("b", "B", "Character")],
        asserted_edges: vec![
            relation("a", "b", 2, KernelGraphLayer::Asserted),
            relation("b", "a", 3, KernelGraphLayer::Asserted),
        ],
        ..KernelGraphSnapshot::default()
    };

    let pack = galaxy_graph_from_snapshot(&snapshot, GalaxyBuildOptions::default());

    assert_eq!(pack.edges.len(), 1);
    assert_eq!(pack.edges[0].weight_millis, 5);
}

#[test]
fn resolves_edges_by_vertex_id_and_canonical_entity_id() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![
            entity_with_vertex_id("vertex:a", "entity:a", "A"),
            entity_with_vertex_id("vertex:b", "entity:b", "B"),
        ],
        asserted_edges: vec![
            relation("vertex:a", "vertex:b", 4, KernelGraphLayer::Asserted),
            relation("entity:a", "entity:b", 6, KernelGraphLayer::Asserted),
        ],
        ..KernelGraphSnapshot::default()
    };

    let pack = galaxy_graph_from_snapshot(&snapshot, GalaxyBuildOptions::default());

    assert_eq!(pack.entity_ids, vec!["entity:a", "entity:b"]);
    assert_eq!(pack.edges.len(), 1);
    assert_eq!(pack.edges[0].weight_millis, 10);
}

#[test]
fn packs_mid_sized_graph_into_compact_records() {
    let mut vertices = Vec::with_capacity(2048);
    let mut asserted_edges = Vec::with_capacity(4096);

    for index in 0..2048 {
        let id = format!("entity:{index}");
        vertices.push(entity(&id, &format!("Entity {index}"), "Character"));
    }
    for index in 0..4096 {
        let source = format!("entity:{}", index % 2048);
        let target = format!("entity:{}", (index * 17 + 29) % 2048);
        asserted_edges.push(relation(&source, &target, 1, KernelGraphLayer::Asserted));
    }

    let snapshot = KernelGraphSnapshot {
        vertices,
        asserted_edges,
        ..KernelGraphSnapshot::default()
    };
    let pack = galaxy_graph_from_snapshot(&snapshot, GalaxyBuildOptions::default());
    let stats = pack.stats();

    assert_eq!(stats.node_count, 2048);
    assert!(stats.edge_count <= 4096);
    assert!(stats.resident_bytes < 512 * 1024);
}

#[test]
fn skips_edges_without_dense_entity_endpoints() {
    let snapshot = KernelGraphSnapshot {
        vertices: vec![entity("a", "A", "Character")],
        asserted_edges: vec![relation("a", "missing", 2, KernelGraphLayer::Asserted)],
        ..KernelGraphSnapshot::default()
    };

    let pack = galaxy_graph_from_snapshot(&snapshot, GalaxyBuildOptions::default());

    assert!(pack.edges.is_empty());
    assert_eq!(pack.skipped_edges, 1);
}
