use crate::{
    write_deterministic_community_artifact, DeterministicCommunityArtifact,
    DeterministicCommunityPolicy,
};
use phoenix_discovery_view::{
    write_asserted_discovery_view, AssertedDiscoveryView, DiscoveryAuthorityBinding,
    DiscoveryRelationPolicy,
};
use phoenix_graph_kernel::{
    KernelEdge, KernelEdgeType, KernelGraphLayer, KernelGraphSnapshot, KernelProvenance,
    KernelRelationClass, KernelVertex, KernelVertexClass, KernelVertexId,
};
use std::io::{Seek, SeekFrom, Write};

#[test]
fn semantic_core_partition_is_canonical_sparse_and_excludes_containment_hubs() {
    let root = tempfile::tempdir().unwrap();
    let source = source_view(root.path(), &fixture(true), 41);
    let relation_policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
    let manifest = write_deterministic_community_artifact(
        &source,
        &relation_policy,
        &DeterministicCommunityPolicy::phoenix_semantic_core_v1(),
        root.path().join("communities"),
    )
    .unwrap();
    let artifact = DeterministicCommunityArtifact::open(
        root.path()
            .join("communities")
            .join(&manifest.artifact_digest),
    )
    .unwrap();
    artifact.validate_payload().unwrap();

    assert_eq!(manifest.node_count, 9);
    assert_eq!(manifest.core_node_count, 7);
    assert_eq!(manifest.selected_edge_count, 7);
    assert_eq!(manifest.component_count, 2);
    assert_eq!(manifest.community_count, 3);
    assert_eq!(manifest.affinity_count, 2);
    assert_eq!(manifest.admitted_candidate_edges, 0);
    assert_eq!(artifact.node_community(node(&source, "doc")).unwrap(), None);
    assert_eq!(
        artifact.node_community(node(&source, "chunk")).unwrap(),
        None
    );

    let left = community(&artifact, &source, "a");
    assert_eq!(community(&artifact, &source, "b"), left);
    assert_eq!(community(&artifact, &source, "c"), left);
    let right = community(&artifact, &source, "d");
    assert_eq!(community(&artifact, &source, "e"), right);
    assert_eq!(community(&artifact, &source, "event"), right);
    assert_ne!(left, right);
    let isolated = community(&artifact, &source, "isolated");
    assert_ne!(isolated, left);
    assert_ne!(isolated, right);
    assert_eq!(artifact.affinities(left).unwrap().len(), 1);
    assert_eq!(artifact.affinities(right).unwrap().len(), 1);
    assert!(artifact.affinities(isolated).unwrap().is_empty());

    for community_id in [left, right, isolated] {
        let members = (0..source.node_count() as u32)
            .filter(|node| artifact.node_community(*node).unwrap() == Some(community_id))
            .collect::<Vec<_>>();
        let minimum = members
            .iter()
            .map(|node| source.node_identity(*node).unwrap())
            .min_by_key(|identity| (identity.hash, identity.collision))
            .unwrap();
        assert_eq!(artifact.community_identity(community_id).unwrap(), minimum);
    }
}

#[test]
fn document_superhub_cannot_change_semantic_core_partition_or_bridge_metrics() {
    let root = tempfile::tempdir().unwrap();
    let with_hub = source_view(root.path(), &fixture(true), 43);
    let without_hub = source_view(root.path(), &fixture(false), 47);
    let relation_policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
    let policy = DeterministicCommunityPolicy::phoenix_semantic_core_v1();
    let with_manifest = write_deterministic_community_artifact(
        &with_hub,
        &relation_policy,
        &policy,
        root.path().join("with"),
    )
    .unwrap();
    let without_manifest = write_deterministic_community_artifact(
        &without_hub,
        &relation_policy,
        &policy,
        root.path().join("without"),
    )
    .unwrap();
    let with_artifact = DeterministicCommunityArtifact::open(
        root.path().join("with").join(with_manifest.artifact_digest),
    )
    .unwrap();
    let without_artifact = DeterministicCommunityArtifact::open(
        root.path()
            .join("without")
            .join(without_manifest.artifact_digest),
    )
    .unwrap();
    for id in ["a", "b", "c", "d", "e", "event", "isolated"] {
        assert_eq!(
            community(&with_artifact, &with_hub, id),
            community(&without_artifact, &without_hub, id)
        );
    }
    assert_eq!(bridge_rows(&with_artifact), bridge_rows(&without_artifact));
    assert_eq!(
        with_manifest.selected_edge_count,
        without_manifest.selected_edge_count
    );
}

#[test]
fn repeated_builds_are_byte_identical_and_payload_corruption_fails_closed() {
    let root = tempfile::tempdir().unwrap();
    let source = source_view(root.path(), &fixture(true), 53);
    let relation_policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
    let policy = DeterministicCommunityPolicy::phoenix_semantic_core_v1();
    let left = write_deterministic_community_artifact(
        &source,
        &relation_policy,
        &policy,
        root.path().join("left"),
    )
    .unwrap();
    let right = write_deterministic_community_artifact(
        &source,
        &relation_policy,
        &policy,
        root.path().join("right"),
    )
    .unwrap();
    assert_eq!(left, right);
    let directory = root.path().join("right").join(&right.artifact_digest);
    let artifact = DeterministicCommunityArtifact::open(&directory).unwrap();
    artifact.validate_payload().unwrap();
    drop(artifact);

    let path = directory.join("communities.bin");
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap();
    file.seek(SeekFrom::End(-1)).unwrap();
    file.write_all(&[0xA5]).unwrap();
    file.flush().unwrap();
    if let Ok(artifact) = DeterministicCommunityArtifact::open(directory) {
        assert!(artifact.validate_payload().is_err());
    }
}

#[test]
fn bridge_receipts_are_decomposed_and_rank_boundary_nodes() {
    let root = tempfile::tempdir().unwrap();
    let source = source_view(root.path(), &fixture(true), 59);
    let relation_policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
    let manifest = write_deterministic_community_artifact(
        &source,
        &relation_policy,
        &DeterministicCommunityPolicy::phoenix_semantic_core_v1(),
        root.path().join("communities"),
    )
    .unwrap();
    let artifact = DeterministicCommunityArtifact::open(
        root.path()
            .join("communities")
            .join(manifest.artifact_digest),
    )
    .unwrap();
    assert!(manifest.bridge_count >= 2);
    let bridges = bridge_rows(&artifact);
    let c = node(&source, "c");
    let d = node(&source, "d");
    assert!(bridges.iter().any(|row| row.0 == c));
    assert!(bridges.iter().any(|row| row.0 == d));
    assert_eq!(artifact.bridge_for_node(c).unwrap().unwrap().node, c);
    assert!(artifact
        .bridge_for_node(node(&source, "isolated"))
        .unwrap()
        .is_none());
    for (_, participation, boundary, conductance, score) in bridges {
        assert!(participation <= 1_000_000);
        assert!(boundary <= 1_000_000);
        assert!(conductance <= 1_000_000);
        assert!(score <= 1_000_000);
    }
}

#[test]
fn manifest_section_tampering_is_rejected_before_mapping_queries() {
    let root = tempfile::tempdir().unwrap();
    let source = source_view(root.path(), &fixture(true), 61);
    let relation_policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
    let manifest = write_deterministic_community_artifact(
        &source,
        &relation_policy,
        &DeterministicCommunityPolicy::phoenix_semantic_core_v1(),
        root.path().join("communities"),
    )
    .unwrap();
    let directory = root
        .path()
        .join("communities")
        .join(manifest.artifact_digest);
    let path = directory.join("manifest.json");
    let mut tampered: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    tampered["sections"][0]["offset"] = serde_json::json!(9_999_999_u64);
    std::fs::write(path, serde_json::to_vec(&tampered).unwrap()).unwrap();
    assert!(DeterministicCommunityArtifact::open(directory).is_err());
}

#[test]
fn relation_weight_policy_must_match_the_asserted_source_receipt() {
    let root = tempfile::tempdir().unwrap();
    let source = source_view(root.path(), &fixture(true), 67);
    let mut relation_policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
    relation_policy.families[0].traversal_weight_millis += 1;
    let error = write_deterministic_community_artifact(
        &source,
        &relation_policy,
        &DeterministicCommunityPolicy::phoenix_semantic_core_v1(),
        root.path().join("communities"),
    )
    .unwrap_err();
    assert!(error.to_string().contains("does not match"));
}

fn bridge_rows(artifact: &DeterministicCommunityArtifact) -> Vec<(u32, u32, u32, u32, u32)> {
    (0..artifact.manifest().bridge_count as u32)
        .map(|index| {
            let row = artifact.bridge(index).unwrap();
            (
                row.node,
                row.participation_micros,
                row.boundary_micros,
                row.conductance_micros,
                row.score_micros,
            )
        })
        .collect()
}

fn community(
    artifact: &DeterministicCommunityArtifact,
    source: &AssertedDiscoveryView,
    id: &str,
) -> u32 {
    artifact.node_community(node(source, id)).unwrap().unwrap()
}

fn node(source: &AssertedDiscoveryView, id: &str) -> u32 {
    (0..source.node_count() as u32)
        .find(|node| source.node_external_id(*node).unwrap() == id)
        .unwrap()
}

fn source_view(
    root: &std::path::Path,
    snapshot: &KernelGraphSnapshot,
    generation: u64,
) -> AssertedDiscoveryView {
    let relation_policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
    let authority = DiscoveryAuthorityBinding {
        generation,
        source_snapshot_id: format!("community-fixture-{generation}"),
        source_snapshot_digest: *blake3::hash(format!("snapshot-{generation}").as_bytes())
            .as_bytes(),
        evidence_registry_digest: *blake3::hash(format!("evidence-{generation}").as_bytes())
            .as_bytes(),
    };
    let artifact_root = root.join(format!("source-{generation}"));
    let manifest =
        write_asserted_discovery_view(snapshot, &authority, &relation_policy, &artifact_root)
            .unwrap();
    AssertedDiscoveryView::open(artifact_root.join(manifest.artifact_digest)).unwrap()
}

fn fixture(with_hub_edges: bool) -> KernelGraphSnapshot {
    let mut vertices = vec![
        vertex("doc", KernelVertexClass::Document),
        vertex("chunk", KernelVertexClass::Chunk),
        vertex("a", KernelVertexClass::Entity),
        vertex("b", KernelVertexClass::Entity),
        vertex("c", KernelVertexClass::Entity),
        vertex("d", KernelVertexClass::Entity),
        vertex("e", KernelVertexClass::Episode),
        vertex("event", KernelVertexClass::Event),
        vertex("isolated", KernelVertexClass::Entity),
    ];
    vertices.reverse();
    let mut asserted_edges = vec![
        edge("a", "b", "left-ab", KernelRelationClass::Semantic, 1.0),
        edge("a", "c", "left-ac", KernelRelationClass::Semantic, 1.0),
        edge("b", "c", "left-bc", KernelRelationClass::Narrative, 1.0),
        edge("d", "e", "right-de", KernelRelationClass::Semantic, 1.0),
        edge("d", "event", "right-dv", KernelRelationClass::Temporal, 1.0),
        edge(
            "e",
            "event",
            "right-ev",
            KernelRelationClass::Narrative,
            1.0,
        ),
        edge("c", "d", "causes", KernelRelationClass::Custom, 0.05),
        edge("a", "e", "custom-noise", KernelRelationClass::Custom, 1.0),
    ];
    if with_hub_edges {
        for id in ["a", "b", "c", "d", "e", "event"] {
            asserted_edges.push(edge(
                "doc",
                id,
                &format!("contains-{id}"),
                KernelRelationClass::Structural,
                1.0,
            ));
        }
        asserted_edges.push(edge(
            "doc",
            "chunk",
            "contains-chunk",
            KernelRelationClass::Structural,
            1.0,
        ));
    }
    KernelGraphSnapshot {
        vertices,
        asserted_edges,
        candidate_edges: vec![edge(
            "a",
            "e",
            "candidate-shortcut",
            KernelRelationClass::Candidate,
            1.0,
        )],
    }
}

fn vertex(id: &str, class: KernelVertexClass) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(id.to_owned()),
        kind: format!("{class:?}").to_lowercase(),
        class,
        ..KernelVertex::default()
    }
}

fn edge(
    source: &str,
    target: &str,
    relation: &str,
    relation_class: KernelRelationClass,
    confidence: f64,
) -> KernelEdge {
    KernelEdge {
        source_id: KernelVertexId(source.to_owned()),
        target_id: KernelVertexId(target.to_owned()),
        edge_type: KernelEdgeType(relation.to_owned()),
        relation_class,
        layer: KernelGraphLayer::Asserted,
        provenance: KernelProvenance {
            confidence: Some(confidence),
            ..KernelProvenance::default()
        },
        ..KernelEdge::default()
    }
}
