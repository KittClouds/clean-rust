use phoenix_discovery_community::{
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
use std::hint::black_box;
use std::path::PathBuf;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let base = arguments
        .first()
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-discovery-community\bench-artifacts"));
    let nodes = parse(arguments.get(1), 100_000)?;
    let edges = parse(arguments.get(2), 400_000)?;
    let generation = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
    let root = base.join(format!("run-{generation}"));
    let relation_policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
    let fixture_started = Instant::now();
    let snapshot = fixture(nodes, edges);
    let fixture_ms = fixture_started.elapsed().as_secs_f64() * 1_000.0;
    let authority = DiscoveryAuthorityBinding {
        generation,
        source_snapshot_id: format!("community-bench-{nodes}-{edges}"),
        source_snapshot_digest: *blake3::hash(format!("snapshot-{nodes}-{edges}").as_bytes())
            .as_bytes(),
        evidence_registry_digest: *blake3::hash(format!("evidence-{nodes}-{edges}").as_bytes())
            .as_bytes(),
    };
    let source_started = Instant::now();
    let source_manifest = write_asserted_discovery_view(
        &snapshot,
        &authority,
        &relation_policy,
        root.join("source"),
    )?;
    let source_ms = source_started.elapsed().as_secs_f64() * 1_000.0;
    let source =
        AssertedDiscoveryView::open(root.join("source").join(source_manifest.artifact_digest))?;
    let build_started = Instant::now();
    let manifest = write_deterministic_community_artifact(
        &source,
        &relation_policy,
        &DeterministicCommunityPolicy::phoenix_semantic_core_v1(),
        root.join("communities"),
    )?;
    let build_ms = build_started.elapsed().as_secs_f64() * 1_000.0;
    let open_started = Instant::now();
    let artifact = DeterministicCommunityArtifact::open(
        root.join("communities").join(&manifest.artifact_digest),
    )?;
    let open_ms = open_started.elapsed().as_secs_f64() * 1_000.0;
    let validation_started = Instant::now();
    artifact.validate_payload()?;
    let validation_ms = validation_started.elapsed().as_secs_f64() * 1_000.0;
    let scan_started = Instant::now();
    let mut checksum = 0_u64;
    for community in 0..manifest.community_count as u32 {
        checksum ^= artifact.community_identity(community)?.hash;
        for (target, weight) in artifact.affinities(community)?.iter() {
            checksum = checksum.wrapping_add(u64::from(target) ^ weight);
        }
    }
    for bridge in 0..manifest.bridge_count as u32 {
        checksum = checksum.wrapping_add(u64::from(artifact.bridge(bridge)?.score_micros));
    }
    black_box(checksum);
    let scan_ms = scan_started.elapsed().as_secs_f64() * 1_000.0;
    println!(
        "{{\"nodes\":{nodes},\"edges\":{edges},\"fixtureMs\":{fixture_ms:.3},\"sourceBuildMs\":{source_ms:.3},\"communityBuildMs\":{build_ms:.3},\"openMs\":{open_ms:.3},\"fullValidationMs\":{validation_ms:.3},\"scanMs\":{scan_ms:.3},\"components\":{},\"communities\":{},\"affinities\":{},\"bridges\":{},\"binaryBytes\":{},\"admittedCandidates\":{},\"checksum\":{checksum}}}",
        manifest.component_count,
        manifest.community_count,
        manifest.affinity_count,
        manifest.bridge_count,
        manifest.binary_bytes,
        manifest.admitted_candidate_edges,
    );
    Ok(())
}

fn parse(value: Option<&String>, fallback: usize) -> Result<usize, Box<dyn std::error::Error>> {
    Ok(value.map_or(Ok(fallback), |value| value.parse())?)
}

fn fixture(nodes: usize, edges: usize) -> KernelGraphSnapshot {
    let vertices = (0..nodes)
        .map(|node| KernelVertex {
            id: KernelVertexId(format!("entity:{node:010}")),
            kind: "entity".to_owned(),
            class: KernelVertexClass::Entity,
            ..KernelVertex::default()
        })
        .collect::<Vec<_>>();
    let cluster_size = 1_000_usize.min(nodes.max(1));
    let asserted_edges = (0..edges)
        .map(|edge| {
            let source = edge % nodes;
            let lane = edge / nodes + 1;
            let cluster_start = source / cluster_size * cluster_size;
            let cluster_len = cluster_size.min(nodes - cluster_start);
            let local = source - cluster_start;
            let target = if edge % 997 == 0 {
                (source + cluster_size) % nodes
            } else {
                cluster_start + (local + lane) % cluster_len
            };
            KernelEdge {
                source_id: KernelVertexId(format!("entity:{source:010}")),
                target_id: KernelVertexId(format!("entity:{target:010}")),
                edge_type: KernelEdgeType(format!("semantic-lane-{lane}")),
                relation_class: KernelRelationClass::Semantic,
                layer: KernelGraphLayer::Asserted,
                provenance: KernelProvenance {
                    confidence: Some(if edge % 997 == 0 { 0.05 } else { 1.0 }),
                    ..KernelProvenance::default()
                },
                ..KernelEdge::default()
            }
        })
        .collect();
    KernelGraphSnapshot {
        vertices,
        asserted_edges,
        candidate_edges: Vec::new(),
    }
}
