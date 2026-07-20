use crate::{
    write_asserted_discovery_view, AssertedDiscoveryView, DiscoveryAuthorityBinding,
    DiscoveryRelationFamily, DiscoveryRelationPolicy, DiscoveryViewRegistry,
};
use phoenix_graph_kernel::{
    KernelBiTemporal, KernelEdge, KernelEdgeType, KernelGraphLayer, KernelGraphSnapshot,
    KernelProvenance, KernelRelationClass, KernelVertex, KernelVertexClass, KernelVertexId,
};
use std::io::{Read, Seek, SeekFrom, Write};
use std::sync::{Arc, Barrier};

#[test]
fn writes_and_reopens_bidirectional_asserted_csr_with_evidence() {
    let root = tempfile::tempdir().unwrap();
    let snapshot = fixture();
    let manifest = write_asserted_discovery_view(
        &snapshot,
        &authority(7),
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        root.path(),
    )
    .unwrap();
    assert_eq!(manifest.node_count, 3);
    assert_eq!(manifest.edge_count, 2);
    assert_eq!(manifest.temporal_edge_count, 1);
    assert_eq!(manifest.excluded_candidate_edges, 1);
    assert_eq!(manifest.admitted_candidate_edges, 0);

    let view = AssertedDiscoveryView::open(root.path().join(&manifest.artifact_digest)).unwrap();
    view.validate_payload().unwrap();
    assert_eq!(view.node_external_id(0).unwrap(), "a");
    assert_eq!(view.node_dense_for_external_id("a").unwrap(), Some(0));
    assert_eq!(view.node_dense_for_external_id("b").unwrap(), Some(1));
    assert_eq!(view.node_dense_for_external_id("missing").unwrap(), None);
    assert_eq!(view.node_external_id(1).unwrap(), "b");
    assert_eq!(view.node_external_id(2).unwrap(), "c");
    assert_eq!(
        view.outgoing_edges(0).unwrap().iter().collect::<Vec<_>>(),
        vec![0]
    );
    assert_eq!(
        view.incoming_edges(1).unwrap().iter().collect::<Vec<_>>(),
        vec![0]
    );
    assert_eq!(
        view.outgoing_edges(1).unwrap().iter().collect::<Vec<_>>(),
        vec![1]
    );
    assert_eq!(
        view.incoming_edges(2).unwrap().iter().collect::<Vec<_>>(),
        vec![1]
    );

    let first = view.edge(0).unwrap();
    assert_eq!(first.source, 0);
    assert_eq!(first.target, 1);
    assert_eq!(first.family, DiscoveryRelationFamily::Semantic);
    assert_eq!(first.temporal.valid_from, Some(10));
    assert_eq!(first.temporal.valid_to, Some(20));
    assert_eq!(view.edge(1).unwrap().temporal, Default::default());
    assert_eq!(view.edge_evidence(0).unwrap().len(), 1);
    let evidence = view.edge_evidence(0).unwrap().get(0).unwrap();
    assert_eq!(
        view.evidence_external_id(evidence).unwrap(),
        "evidence-edge-ab"
    );
}

#[test]
fn content_identity_is_independent_of_snapshot_row_order() {
    let left_root = tempfile::tempdir().unwrap();
    let right_root = tempfile::tempdir().unwrap();
    let left = fixture();
    let mut right = fixture();
    right.vertices.reverse();
    right.asserted_edges.reverse();
    right.candidate_edges.reverse();
    for vertex in &mut right.vertices {
        vertex.provenance.evidence_refs.reverse();
    }
    for edge in &mut right.asserted_edges {
        edge.provenance.evidence_refs.reverse();
    }

    let left_manifest = write_asserted_discovery_view(
        &left,
        &authority(11),
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        left_root.path(),
    )
    .unwrap();
    let right_manifest = write_asserted_discovery_view(
        &right,
        &authority(11),
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        right_root.path(),
    )
    .unwrap();
    assert_eq!(
        left_manifest.artifact_digest,
        right_manifest.artifact_digest
    );
    assert_eq!(left_manifest.payload_digest, right_manifest.payload_digest);
    assert_eq!(left_manifest.relations, right_manifest.relations);
}

#[test]
fn candidate_layer_cannot_enter_asserted_columns() {
    let root = tempfile::tempdir().unwrap();
    let mut snapshot = fixture();
    let mut poison = edge("a", "c", "poison", KernelRelationClass::Candidate);
    poison.layer = KernelGraphLayer::Candidate;
    snapshot.asserted_edges.push(poison);
    let error = write_asserted_discovery_view(
        &snapshot,
        &authority(13),
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        root.path(),
    )
    .unwrap_err();
    assert!(error.to_string().contains("candidate edge was presented"));
}

#[test]
fn registry_binds_exactly_one_immutable_artifact_to_a_generation() {
    let root = tempfile::tempdir().unwrap();
    let registry = DiscoveryViewRegistry::new(root.path());
    let policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
    let receipt = registry
        .publish(&fixture(), &authority(23), &policy)
        .unwrap();
    assert_eq!(receipt.generation, 23);
    assert_eq!(receipt.admitted_candidate_edges, 0);

    let repeated = registry
        .publish(&fixture(), &authority(23), &policy)
        .unwrap();
    assert_eq!(repeated, receipt);
    let view = registry.open_generation(23).unwrap();
    assert_eq!(view.manifest().artifact_digest, receipt.artifact_digest);
    assert_eq!(view.manifest().excluded_candidate_edges, 1);

    let mut changed_authority = authority(23);
    changed_authority.source_snapshot_digest = [0xA5; 32];
    let error = registry
        .publish(&fixture(), &changed_authority, &policy)
        .unwrap_err();
    assert!(error.to_string().contains("already bound"));
    assert_eq!(
        registry.receipt(23).unwrap().artifact_digest,
        receipt.artifact_digest
    );
}

#[test]
fn concurrent_identical_publications_converge_on_one_generation_receipt() {
    let root = tempfile::tempdir().unwrap();
    let registry = DiscoveryViewRegistry::new(root.path());
    let snapshot = Arc::new(fixture());
    let barrier = Arc::new(Barrier::new(4));
    let workers = (0..4)
        .map(|_| {
            let registry = registry.clone();
            let snapshot = Arc::clone(&snapshot);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                registry.publish(
                    &snapshot,
                    &authority(29),
                    &DiscoveryRelationPolicy::phoenix_asserted_v1(),
                )
            })
        })
        .collect::<Vec<_>>();
    let receipts = workers
        .into_iter()
        .map(|worker| worker.join().unwrap().unwrap())
        .collect::<Vec<_>>();
    assert!(receipts.windows(2).all(|pair| pair[0] == pair[1]));
    assert_eq!(registry.open_generation(29).unwrap().edge_count(), 2);
}

#[test]
fn payload_corruption_is_detected_without_materializing_the_graph() {
    let root = tempfile::tempdir().unwrap();
    let manifest = write_asserted_discovery_view(
        &fixture(),
        &authority(17),
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        root.path(),
    )
    .unwrap();
    let directory = root.path().join(&manifest.artifact_digest);
    let view = AssertedDiscoveryView::open(&directory).unwrap();
    view.validate_payload().unwrap();
    drop(view);

    let path = directory.join("view.bin");
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap();
    file.seek(SeekFrom::End(-1)).unwrap();
    let mut byte = [0_u8; 1];
    file.read_exact(&mut byte).unwrap();
    file.seek(SeekFrom::End(-1)).unwrap();
    byte[0] ^= 0x5a;
    file.write_all(&byte).unwrap();
    file.sync_all().unwrap();
    drop(file);

    let corrupted = AssertedDiscoveryView::open(directory).unwrap();
    assert!(corrupted.validate_payload().is_err());
}

#[test]
fn authority_or_policy_change_changes_content_address() {
    let root = tempfile::tempdir().unwrap();
    let snapshot = fixture();
    let first = write_asserted_discovery_view(
        &snapshot,
        &authority(19),
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        root.path(),
    )
    .unwrap();
    let mut changed = authority(20);
    changed.evidence_registry_digest = *blake3::hash(b"different-evidence-registry").as_bytes();
    let second = write_asserted_discovery_view(
        &snapshot,
        &changed,
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        root.path(),
    )
    .unwrap();
    assert_ne!(first.artifact_digest, second.artifact_digest);
}

#[test]
fn manifest_tampering_breaks_the_recomputed_content_address() {
    let root = tempfile::tempdir().unwrap();
    let manifest = write_asserted_discovery_view(
        &fixture(),
        &authority(23),
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        root.path(),
    )
    .unwrap();
    let directory = root.path().join(&manifest.artifact_digest);
    let path = directory.join("manifest.json");
    let mut value: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    value["sourceSnapshotId"] = "tampered".into();
    std::fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(AssertedDiscoveryView::open(directory).is_err());
}

fn fixture() -> KernelGraphSnapshot {
    KernelGraphSnapshot {
        vertices: vec![
            vertex("c", KernelVertexClass::Event, &["evidence-c"]),
            vertex("a", KernelVertexClass::Entity, &["evidence-a"]),
            vertex("b", KernelVertexClass::Entity, &["evidence-b"]),
        ],
        asserted_edges: vec![
            edge("b", "c", "before", KernelRelationClass::Temporal),
            KernelEdge {
                temporal: KernelBiTemporal {
                    valid_from: Some(10),
                    valid_to: Some(20),
                    recorded_at: Some(30),
                    expired_at: None,
                },
                provenance: KernelProvenance {
                    confidence: Some(0.875),
                    evidence_refs: vec!["evidence-edge-ab".to_owned()],
                    ..Default::default()
                },
                ..edge("a", "b", "knows", KernelRelationClass::Semantic)
            },
        ],
        candidate_edges: vec![edge(
            "c",
            "a",
            "candidate-only",
            KernelRelationClass::Candidate,
        )],
    }
}

fn vertex(id: &str, class: KernelVertexClass, evidence: &[&str]) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(id.to_owned()),
        kind: format!("{class:?}").to_lowercase(),
        class,
        provenance: KernelProvenance {
            confidence: Some(1.0),
            evidence_refs: evidence.iter().map(|value| (*value).to_owned()).collect(),
            ..Default::default()
        },
        ..Default::default()
    }
}

fn edge(
    source: &str,
    target: &str,
    relation: &str,
    relation_class: KernelRelationClass,
) -> KernelEdge {
    KernelEdge {
        source_id: KernelVertexId(source.to_owned()),
        target_id: KernelVertexId(target.to_owned()),
        edge_type: KernelEdgeType(relation.to_owned()),
        relation_class,
        layer: if relation == "candidate-only" {
            KernelGraphLayer::Candidate
        } else {
            KernelGraphLayer::Asserted
        },
        provenance: KernelProvenance {
            confidence: Some(0.75),
            evidence_refs: vec![format!("evidence-{source}-{target}")],
            ..Default::default()
        },
        ..Default::default()
    }
}

fn authority(generation: u64) -> DiscoveryAuthorityBinding {
    DiscoveryAuthorityBinding {
        generation,
        source_snapshot_id: "snapshot-test".to_owned(),
        source_snapshot_digest: *blake3::hash(b"snapshot-test").as_bytes(),
        evidence_registry_digest: *blake3::hash(b"evidence-registry-test").as_bytes(),
    }
}
