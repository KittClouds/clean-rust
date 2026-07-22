use std::collections::BTreeSet;
use std::path::Path;

use phoenix_discovery_view::{
    write_asserted_discovery_view, DiscoveryAuthorityBinding, DiscoveryRelationPolicy,
    DiscoveryViewManifest,
};
use phoenix_graph_kernel::{
    KernelEdge, KernelEdgeType, KernelGraphLayer, KernelGraphSnapshot, KernelProvenance,
    KernelRelationClass, KernelVertex, KernelVertexClass, KernelVertexId,
};
use phoenix_graph_rebuild::GraphRebuildSnapshot;
use phoenix_revision_impact::{
    graph_rebuild_asserted_inference_input, InferenceAuthority, InferenceEdgeSeed,
};

pub fn prepare_graph_generation_query(
    snapshot: &GraphRebuildSnapshot,
    authority_hash: &str,
    output_root: &Path,
) -> Result<DiscoveryViewManifest, String> {
    if snapshot.id.is_empty() || snapshot.scope_id.is_empty() || authority_hash.is_empty() {
        return Err("asserted query artifact requires complete graph authority".to_owned());
    }
    let input = graph_rebuild_asserted_inference_input(snapshot);
    let mut vertices = input
        .accepted_nodes
        .into_iter()
        .map(|node| KernelVertex {
            id: KernelVertexId(node.node_id.to_string()),
            kind: node.node_type.to_string(),
            class: vertex_class(node.node_type.as_str()),
            ..Default::default()
        })
        .collect::<Vec<_>>();
    vertices.sort_unstable_by(|left, right| left.id.0.cmp(&right.id.0));
    if vertices.windows(2).any(|pair| pair[0].id == pair[1].id) {
        return Err("asserted query artifact contains duplicate node identities".to_owned());
    }

    let mut asserted_edges = Vec::with_capacity(input.relations.len() + input.memberships.len());
    let mut candidate_edges = Vec::new();
    let mut evidence = BTreeSet::new();
    for (seed, membership) in input
        .relations
        .into_iter()
        .map(|seed| (seed, false))
        .chain(input.memberships.into_iter().map(|seed| (seed, true)))
    {
        evidence.extend(seed.evidence_ids.iter().map(ToString::to_string));
        match seed.authority {
            InferenceAuthority::Asserted | InferenceAuthority::Accepted => {
                asserted_edges.push(kernel_edge(seed, membership, KernelGraphLayer::Asserted));
            }
            InferenceAuthority::Candidate => {
                candidate_edges.push(kernel_edge(seed, membership, KernelGraphLayer::Candidate));
            }
            InferenceAuthority::Rejected => {}
        }
    }
    sort_edges(&mut asserted_edges);
    sort_edges(&mut candidate_edges);
    let source_digest = *blake3::hash(
        format!(
            "phoenix-graph-generation-query-source/v1\0{}\0{}\0{}",
            snapshot.scope_id, snapshot.id, authority_hash
        )
        .as_bytes(),
    )
    .as_bytes();
    let mut evidence_hasher = blake3::Hasher::new();
    evidence_hasher.update(b"phoenix-graph-generation-query-evidence/v1\0");
    for id in evidence {
        evidence_hasher.update(&(id.len() as u64).to_le_bytes());
        evidence_hasher.update(id.as_bytes());
    }
    let authority = DiscoveryAuthorityBinding {
        generation: snapshot.built_at.max(1),
        source_snapshot_id: snapshot.id.to_string(),
        source_snapshot_digest: source_digest,
        evidence_registry_digest: *evidence_hasher.finalize().as_bytes(),
    };
    let graph = KernelGraphSnapshot {
        vertices,
        asserted_edges,
        candidate_edges,
    };
    let manifest = write_asserted_discovery_view(
        &graph,
        &authority,
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        output_root.join("objects"),
    )
    .map_err(|error| error.to_string())?;
    if manifest.admitted_candidate_edges != 0 {
        return Err("asserted query artifact admitted candidate topology".to_owned());
    }
    Ok(manifest)
}

fn kernel_edge(seed: InferenceEdgeSeed, membership: bool, layer: KernelGraphLayer) -> KernelEdge {
    let relation = seed.relation_type.to_string();
    let relation_class = if layer == KernelGraphLayer::Candidate {
        KernelRelationClass::Candidate
    } else if membership {
        KernelRelationClass::Structural
    } else if relation.starts_with("temporal:") {
        KernelRelationClass::Temporal
    } else {
        KernelRelationClass::Semantic
    };
    KernelEdge {
        source_id: KernelVertexId(seed.source_id.to_string()),
        target_id: KernelVertexId(seed.target_id.to_string()),
        edge_type: KernelEdgeType(relation),
        relation_class,
        weight: i64::from(seed.confidence_millis),
        layer,
        provenance: KernelProvenance {
            confidence: Some(f64::from(seed.confidence_millis) / 1000.0),
            evidence_refs: seed
                .evidence_ids
                .into_iter()
                .map(|id| id.to_string())
                .collect(),
            ..Default::default()
        },
        ..Default::default()
    }
}

fn sort_edges(edges: &mut [KernelEdge]) {
    edges.sort_unstable_by(|left, right| {
        left.source_id
            .0
            .cmp(&right.source_id.0)
            .then_with(|| left.target_id.0.cmp(&right.target_id.0))
            .then_with(|| left.edge_type.0.cmp(&right.edge_type.0))
            .then_with(|| {
                left.provenance
                    .evidence_refs
                    .cmp(&right.provenance.evidence_refs)
            })
    });
}

fn vertex_class(kind: &str) -> KernelVertexClass {
    match kind {
        "document" => KernelVertexClass::Document,
        "chunk" => KernelVertexClass::Chunk,
        "entity" => KernelVertexClass::Entity,
        "event" => KernelVertexClass::Event,
        "episode" => KernelVertexClass::Episode,
        _ => KernelVertexClass::Generic,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use phoenix_graph_rebuild::GraphCounters;
    use serde_json::json;

    #[test]
    fn graph_rebuild_node_classes_remain_explicit() {
        assert_eq!(vertex_class("document"), KernelVertexClass::Document);
        assert_eq!(vertex_class("chunk"), KernelVertexClass::Chunk);
        assert_eq!(vertex_class("entity"), KernelVertexClass::Entity);
        assert_eq!(vertex_class("event"), KernelVertexClass::Event);
        assert_eq!(vertex_class("episode"), KernelVertexClass::Episode);
    }

    #[test]
    fn edge_order_is_stable_for_mmap_identity_assignment() {
        let mut edges = vec![
            fixture_edge("b", "c", "z"),
            fixture_edge("a", "c", "z"),
            fixture_edge("a", "b", "a"),
        ];
        sort_edges(&mut edges);
        let order = edges
            .iter()
            .map(|edge| {
                (
                    edge.source_id.0.clone(),
                    edge.target_id.0.clone(),
                    edge.edge_type.0.clone(),
                )
            })
            .collect::<Vec<_>>();
        assert_eq!(
            order,
            vec![
                ("a".to_owned(), "b".to_owned(), "a".to_owned()),
                ("a".to_owned(), "c".to_owned(), "z".to_owned()),
                ("b".to_owned(), "c".to_owned(), "z".to_owned()),
            ]
        );
    }

    #[test]
    fn writes_a_candidate_free_mmap_discovery_artifact() {
        let snapshot: GraphRebuildSnapshot = serde_json::from_value(json!({
            "schemaVersion": "phoenix-graph-rebuild/v1",
            "id": "snapshot:test",
            "source": "phoenix-graph-rebuild",
            "scopeKind": "global",
            "scopeId": "global",
            "noteIds": [],
            "builtAt": 7,
            "chunks": [],
            "mentions": [],
            "entityAnchors": [],
            "relationships": [],
            "events": [],
            "episodes": [],
            "episodeProjectionEdges": [],
            "temporalEdges": [],
            "causalEdges": [],
            "memoryState": [],
            "memoryGovernanceCandidates": [],
            "embeddingTargets": [],
            "embeddingVectors": [],
            "projectionRefs": [],
            "nodes": [
                { "id": "a", "entityId": "a", "label": "A", "kind": "CHARACTER",
                  "aliases": [], "anchorIds": [], "noteIds": [], "totalMentions": 0 },
                { "id": "b", "entityId": "b", "label": "B", "kind": "LOCATION",
                  "aliases": [], "anchorIds": [], "noteIds": [], "totalMentions": 0 }
            ],
            "edges": [
                { "id": "edge:a:b", "sourceId": "a", "targetId": "b", "type": "related",
                  "weight": 1, "confidence": 0.9, "evidenceAnchorIds": [], "scopeKeys": [], "noteIds": [] }
            ],
            "counters": serde_json::to_value(GraphCounters::default()).unwrap()
        }))
        .unwrap();
        let directory = tempfile::tempdir().unwrap();

        let manifest =
            prepare_graph_generation_query(&snapshot, "fnv64-authority-test", directory.path())
                .unwrap();

        assert_eq!(manifest.source_snapshot_id, "snapshot:test");
        assert_eq!(manifest.node_count, 2);
        assert_eq!(manifest.edge_count, 1);
        assert_eq!(manifest.admitted_candidate_edges, 0);
        assert!(manifest.binary_bytes > 0);
        assert!(directory
            .path()
            .join("objects")
            .join(&manifest.artifact_digest)
            .join(&manifest.binary_file)
            .is_file());
        #[cfg(feature = "graph-analytics-wgpu-shadow")]
        {
            let coordinator =
                crate::graph_offline_analytics::OfflineAnalyticsCoordinator::default();
            let shadow = coordinator
                .run_community_artifact_shadow(
                    &crate::graph_offline_analytics::OfflineCommunityArtifactJob {
                        generation: manifest.generation,
                        source_artifact_digest: manifest.artifact_digest.clone(),
                        source_artifact_root: directory
                            .path()
                            .join("objects")
                            .join(&manifest.artifact_digest),
                        shadow_artifact_root: directory.path().join("community-shadow"),
                        mode: crate::graph_offline_analytics::OfflineAnalyticsMode::AutoQualified,
                    },
                )
                .unwrap();
            assert_eq!(
                shadow.receipt.execution_path_id,
                "community_cpu_deterministic_v1"
            );
            assert_eq!(
                shadow.receipt.selection_reason,
                "below_structural_gpu_crossover"
            );
            assert_eq!(shadow.receipt.fallback_count, 0);
            assert_eq!(shadow.receipt.resident_uploads, 0);
            assert!(!shadow.receipt.production_published);
            assert!(directory
                .path()
                .join("community-shadow")
                .join(&shadow.manifest.artifact_digest)
                .join(&shadow.manifest.binary_file)
                .is_file());
        }
    }

    fn fixture_edge(source: &str, target: &str, relation: &str) -> KernelEdge {
        KernelEdge {
            source_id: KernelVertexId(source.to_owned()),
            target_id: KernelVertexId(target.to_owned()),
            edge_type: KernelEdgeType(relation.to_owned()),
            ..Default::default()
        }
    }
}
