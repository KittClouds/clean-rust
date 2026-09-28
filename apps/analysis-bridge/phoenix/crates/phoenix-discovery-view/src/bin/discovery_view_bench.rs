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
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-discovery-view\bench-artifacts"));
    let nodes = parse_count(arguments.get(1), 100_000)?;
    let edges = parse_count(arguments.get(2), 400_000)?;
    let generation = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
    let root = base.join(format!("run-{generation}"));

    let fixture_started = Instant::now();
    let snapshot = fixture(nodes, edges);
    let fixture_elapsed = fixture_started.elapsed();
    let authority = DiscoveryAuthorityBinding {
        generation,
        source_snapshot_id: format!("synthetic-{nodes}-{edges}"),
        source_snapshot_digest: *blake3::hash(format!("snapshot-{nodes}-{edges}").as_bytes())
            .as_bytes(),
        evidence_registry_digest: *blake3::hash(format!("evidence-{nodes}-{edges}").as_bytes())
            .as_bytes(),
    };

    let build_started = Instant::now();
    let manifest = write_asserted_discovery_view(
        &snapshot,
        &authority,
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        &root,
    )?;
    let build_elapsed = build_started.elapsed();

    let open_started = Instant::now();
    let view = AssertedDiscoveryView::open(root.join(&manifest.artifact_digest))?;
    let open_elapsed = open_started.elapsed();
    let validation_started = Instant::now();
    view.validate_payload()?;
    let validation_elapsed = validation_started.elapsed();

    let walk_started = Instant::now();
    let mut checksum = 0_u64;
    for node in 0..nodes as u32 {
        for edge in view.outgoing_edges(node)?.iter() {
            checksum = checksum.wrapping_add(black_box(edge as u64));
        }
        for edge in view.incoming_edges(node)?.iter() {
            checksum = checksum.wrapping_add(black_box(edge as u64));
        }
    }
    let walk_elapsed = walk_started.elapsed();
    println!(
        "{{\"nodes\":{nodes},\"edges\":{edges},\"fixtureMs\":{:.3},\"buildMs\":{:.3},\"openMs\":{:.3},\"fullDigestMs\":{:.3},\"bidirectionalWalkMs\":{:.3},\"binaryBytes\":{},\"bytesPerNodeEdge\":{:.3},\"excludedCandidates\":{},\"admittedCandidates\":{},\"checksum\":{checksum}}}",
        fixture_elapsed.as_secs_f64() * 1_000.0,
        build_elapsed.as_secs_f64() * 1_000.0,
        open_elapsed.as_secs_f64() * 1_000.0,
        validation_elapsed.as_secs_f64() * 1_000.0,
        walk_elapsed.as_secs_f64() * 1_000.0,
        manifest.binary_bytes,
        manifest.binary_bytes as f64 / (nodes + edges).max(1) as f64,
        manifest.excluded_candidate_edges,
        manifest.admitted_candidate_edges,
    );
    Ok(())
}

fn fixture(nodes: usize, edges: usize) -> KernelGraphSnapshot {
    let vertices = (0..nodes)
        .map(|index| KernelVertex {
            id: KernelVertexId(format!("entity-{index:08}")),
            kind: "entity".to_owned(),
            class: KernelVertexClass::Entity,
            provenance: KernelProvenance {
                confidence: Some(1.0),
                evidence_refs: vec![format!("anchor-{index:08}")],
                ..Default::default()
            },
            ..Default::default()
        })
        .collect();
    let asserted_edges = (0..edges)
        .map(|index| {
            let source = index % nodes;
            let lane = index / nodes;
            let target = (source.wrapping_mul(31).wrapping_add(lane + 1)) % nodes;
            KernelEdge {
                source_id: KernelVertexId(format!("entity-{source:08}")),
                target_id: KernelVertexId(format!("entity-{target:08}")),
                edge_type: KernelEdgeType(format!("relation-{}", lane % 16)),
                relation_class: match lane % 4 {
                    0 => KernelRelationClass::Semantic,
                    1 => KernelRelationClass::Temporal,
                    2 => KernelRelationClass::Narrative,
                    _ => KernelRelationClass::Structural,
                },
                layer: KernelGraphLayer::Asserted,
                provenance: KernelProvenance {
                    confidence: Some(0.8),
                    evidence_refs: vec![format!("edge-anchor-{index:09}")],
                    ..Default::default()
                },
                ..Default::default()
            }
        })
        .collect();
    let candidate_edges = (0..32.min(nodes))
        .map(|index| KernelEdge {
            source_id: KernelVertexId(format!("entity-{index:08}")),
            target_id: KernelVertexId(format!("entity-{:08}", (index + 1) % nodes)),
            edge_type: KernelEdgeType("candidate-poison".to_owned()),
            relation_class: KernelRelationClass::Candidate,
            layer: KernelGraphLayer::Candidate,
            ..Default::default()
        })
        .collect();
    KernelGraphSnapshot {
        vertices,
        asserted_edges,
        candidate_edges,
    }
}

fn parse_count(
    value: Option<&String>,
    fallback: usize,
) -> Result<usize, Box<dyn std::error::Error>> {
    Ok(value.map_or(Ok(fallback), |value| value.parse())?)
}
