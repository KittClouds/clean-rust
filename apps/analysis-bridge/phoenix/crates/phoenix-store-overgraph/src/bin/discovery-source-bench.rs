use overgraph::{DatabaseEngine, DbOptions, EdgeInput, NodeInput, PropValue, UpsertNodeOptions};
use phoenix_discovery_view::{
    write_asserted_discovery_view_from_source, AssertedDiscoveryView, DiscoveryAuthorityBinding,
    DiscoveryRelationPolicy,
};
use phoenix_graph_kernel::{
    KernelEdge, KernelEdgeType, KernelGraphLayer, KernelProvenance, KernelRelationClass,
    KernelVertex, KernelVertexClass, KernelVertexId,
};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::Instant;

const TYPE_KERNEL_CHECKPOINT: u32 = 13;
const TYPE_KERNEL_TOPOLOGY_VERTEX: u32 = 34;
const EDGE_KERNEL_TOPOLOGY_ASSERTED: u32 = 1001;
const EDGE_KERNEL_TOPOLOGY_CANDIDATE: u32 = 1002;
const BATCH: usize = 4_096;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    match arguments.first().map(String::as_str) {
        Some("prepare") => prepare(
            required_path(&arguments, 1, "store")?,
            parse_count(arguments.get(2), 100_000)?,
            parse_count(arguments.get(3), 400_000)?,
        ),
        Some("build") => build(
            required_path(&arguments, 1, "store")?,
            required_path(&arguments, 2, "artifact root")?,
        ),
        Some("build-view") => build_view(
            required_path(&arguments, 1, "source artifact")?,
            required_path(&arguments, 2, "artifact root")?,
        ),
        Some("cache") => cache(required_path(&arguments, 1, "store")?),
        _ => Err("usage: discovery-source-bench prepare <store> <nodes> <edges> | cache <store> | build <store> <artifact-root> | build-view <source-artifact> <artifact-root>".into()),
    }
}

fn prepare(store: PathBuf, nodes: usize, edges: usize) -> Result<(), Box<dyn std::error::Error>> {
    if nodes == 0 || nodes > u32::MAX as usize || edges > u32::MAX as usize {
        return Err("node and edge counts must fit the discovery u32 contract".into());
    }
    if store.exists() {
        return Err(format!("benchmark store already exists: {}", store.display()).into());
    }
    let started = Instant::now();
    let mut engine = DatabaseEngine::open(
        &store,
        &DbOptions {
            memtable_flush_threshold: 128 * 1024 * 1024,
            memtable_hard_cap_bytes: 512 * 1024 * 1024,
            max_immutable_memtables: 8,
            compact_after_n_flushes: 4,
            ..DbOptions::default()
        },
    )?;

    let mut storage_ids = Vec::with_capacity(nodes);
    for start in (0..nodes).step_by(BATCH) {
        let end = (start + BATCH).min(nodes);
        let mut batch = Vec::with_capacity(end - start);
        for index in start..end {
            let stable_id = node_id(index);
            let vertex = KernelVertex {
                id: KernelVertexId(stable_id.clone()),
                kind: "entity".to_owned(),
                class: KernelVertexClass::Entity,
                weight: 1,
                provenance: KernelProvenance {
                    confidence: Some(1.0),
                    evidence_refs: vec![format!("anchor-{index:08}")],
                    ..Default::default()
                },
                ..Default::default()
            };
            batch.push(NodeInput {
                type_id: TYPE_KERNEL_TOPOLOGY_VERTEX,
                key: format!("kernel-topology:{stable_id}"),
                props: record_props(&vertex)?,
                weight: 1.0,
                dense_vector: None,
                sparse_vector: None,
            });
        }
        storage_ids.extend(engine.batch_upsert_nodes(&batch)?);
    }

    let lanes = edges.div_ceil(nodes);
    let mut batch = Vec::with_capacity(BATCH);
    for source in 0..nodes {
        let mut source_edges = Vec::with_capacity(lanes);
        for lane in 0..lanes {
            let index = lane * nodes + source;
            if index >= edges {
                continue;
            }
            let target = (source.wrapping_mul(31).wrapping_add(lane + 1)) % nodes;
            source_edges.push((target, lane, index));
        }
        source_edges.sort_unstable_by_key(|(target, lane, _)| (*target, lane % 16));
        for (target, lane, index) in source_edges {
            let relation = format!("relation-{}", lane % 16);
            let edge = KernelEdge {
                source_id: KernelVertexId(node_id(source)),
                target_id: KernelVertexId(node_id(target)),
                edge_type: KernelEdgeType(relation.clone()),
                relation_class: relation_class(lane),
                weight: 1,
                layer: KernelGraphLayer::Asserted,
                provenance: KernelProvenance {
                    confidence: Some(0.8),
                    evidence_refs: vec![format!("edge-anchor-{index:09}")],
                    ..Default::default()
                },
                ..Default::default()
            };
            batch.push(EdgeInput {
                from: storage_ids[source],
                to: storage_ids[target],
                type_id: EDGE_KERNEL_TOPOLOGY_ASSERTED,
                props: edge_props(&edge)?,
                weight: 1.0,
                valid_from: Some(0),
                valid_to: Some(i64::MAX),
            });
            if batch.len() == BATCH {
                engine.batch_upsert_edges(&batch)?;
                batch.clear();
            }
        }
    }
    if !batch.is_empty() {
        engine.batch_upsert_edges(&batch)?;
        batch.clear();
    }

    for index in 0..32.min(nodes) {
        let target = (index + 1) % nodes;
        let edge = KernelEdge {
            source_id: KernelVertexId(node_id(index)),
            target_id: KernelVertexId(node_id(target)),
            edge_type: KernelEdgeType("candidate-poison".to_owned()),
            relation_class: KernelRelationClass::Candidate,
            layer: KernelGraphLayer::Candidate,
            ..Default::default()
        };
        batch.push(EdgeInput {
            from: storage_ids[index],
            to: storage_ids[target],
            type_id: EDGE_KERNEL_TOPOLOGY_CANDIDATE,
            props: edge_props(&edge)?,
            weight: 1.0,
            valid_from: Some(0),
            valid_to: Some(i64::MAX),
        });
    }
    if !batch.is_empty() {
        engine.batch_upsert_edges(&batch)?;
    }

    let mut generation_props = BTreeMap::new();
    generation_props.insert("generation".to_owned(), PropValue::UInt(1));
    engine.upsert_node(
        TYPE_KERNEL_CHECKPOINT,
        "current",
        UpsertNodeOptions {
            props: generation_props,
            ..Default::default()
        },
    )?;
    engine.close()?;
    println!(
        "{{\"mode\":\"prepare\",\"nodes\":{nodes},\"edges\":{edges},\"elapsedMs\":{:.3}}}",
        started.elapsed().as_secs_f64() * 1_000.0
    );
    Ok(())
}

fn build(store: PathBuf, output: PathBuf) -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let store = PhoenixOvergraphStore::open(store)?;
    let open_ms = started.elapsed().as_secs_f64() * 1_000.0;
    let authority = DiscoveryAuthorityBinding {
        generation: 1,
        source_snapshot_id: "paged-overgraph-benchmark".to_owned(),
        source_snapshot_digest: *blake3::hash(b"paged-overgraph-benchmark-snapshot").as_bytes(),
        evidence_registry_digest: *blake3::hash(b"paged-overgraph-benchmark-evidence").as_bytes(),
    };
    let build_started = Instant::now();
    let manifest = write_asserted_discovery_view_from_source(
        &store,
        &authority,
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        &output,
    )?;
    let build_ms = build_started.elapsed().as_secs_f64() * 1_000.0;
    let view = AssertedDiscoveryView::open(output.join(&manifest.artifact_digest))?;
    view.validate_payload()?;
    println!(
        "{{\"mode\":\"build\",\"nodes\":{},\"edges\":{},\"openMs\":{open_ms:.3},\"buildMs\":{build_ms:.3},\"binaryBytes\":{},\"payloadDigest\":\"{}\",\"excludedCandidates\":{},\"admittedCandidates\":{}}}",
        manifest.node_count,
        manifest.edge_count,
        manifest.binary_bytes,
        manifest.payload_digest,
        manifest.excluded_candidate_edges,
        manifest.admitted_candidate_edges,
    );
    Ok(())
}

fn build_view(source: PathBuf, output: PathBuf) -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let source = AssertedDiscoveryView::open(source)?;
    source.validate_payload()?;
    let open_ms = started.elapsed().as_secs_f64() * 1_000.0;
    let authority = DiscoveryAuthorityBinding {
        generation: source.manifest().generation,
        source_snapshot_id: "paged-overgraph-benchmark".to_owned(),
        source_snapshot_digest: *blake3::hash(b"paged-overgraph-benchmark-snapshot").as_bytes(),
        evidence_registry_digest: *blake3::hash(b"paged-overgraph-benchmark-evidence").as_bytes(),
    };
    let build_started = Instant::now();
    let manifest = write_asserted_discovery_view_from_source(
        &source,
        &authority,
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        &output,
    )?;
    let build_ms = build_started.elapsed().as_secs_f64() * 1_000.0;
    let view = AssertedDiscoveryView::open(output.join(&manifest.artifact_digest))?;
    view.validate_payload()?;
    println!(
        "{{\"mode\":\"build-view\",\"nodes\":{},\"edges\":{},\"openMs\":{open_ms:.3},\"buildMs\":{build_ms:.3},\"binaryBytes\":{},\"payloadDigest\":\"{}\",\"excludedCandidates\":{},\"admittedCandidates\":{}}}",
        manifest.node_count,
        manifest.edge_count,
        manifest.binary_bytes,
        manifest.payload_digest,
        manifest.excluded_candidate_edges,
        manifest.admitted_candidate_edges,
    );
    Ok(())
}

fn cache(store: PathBuf) -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let store = PhoenixOvergraphStore::open(store)?;
    let receipt = store.rebuild_discovery_source_cache()?;
    println!(
        "{{\"mode\":\"cache\",\"nodes\":{},\"edges\":{},\"elapsedMs\":{:.3},\"payloadDigest\":\"{}\",\"excludedCandidates\":{}}}",
        receipt.node_count,
        receipt.edge_count,
        started.elapsed().as_secs_f64() * 1_000.0,
        receipt.payload_digest,
        receipt.excluded_candidate_edges,
    );
    Ok(())
}

fn node_id(index: usize) -> String {
    format!("entity-{index:08}")
}

fn relation_class(lane: usize) -> KernelRelationClass {
    match lane % 4 {
        0 => KernelRelationClass::Semantic,
        1 => KernelRelationClass::Temporal,
        2 => KernelRelationClass::Narrative,
        _ => KernelRelationClass::Structural,
    }
}

fn record_props(
    value: &KernelVertex,
) -> Result<BTreeMap<String, PropValue>, rmp_serde::encode::Error> {
    let mut props = BTreeMap::new();
    props.insert(
        "record".to_owned(),
        PropValue::Bytes(rmp_serde::to_vec_named(value)?),
    );
    Ok(props)
}

fn edge_props(value: &KernelEdge) -> Result<BTreeMap<String, PropValue>, rmp_serde::encode::Error> {
    let mut props = BTreeMap::new();
    props.insert(
        "record".to_owned(),
        PropValue::Bytes(rmp_serde::to_vec_named(value)?),
    );
    Ok(props)
}

fn required_path(
    arguments: &[String],
    index: usize,
    label: &str,
) -> Result<PathBuf, Box<dyn std::error::Error>> {
    arguments
        .get(index)
        .map(PathBuf::from)
        .ok_or_else(|| format!("missing {label}").into())
}

fn parse_count(
    value: Option<&String>,
    fallback: usize,
) -> Result<usize, Box<dyn std::error::Error>> {
    Ok(value.map_or(Ok(fallback), |value| value.parse())?)
}
