use std::collections::HashMap;

use overgraph::{
    ComponentOptions, DatabaseEngine, DegreeOptions, Direction, EdgeInput, EdgeRecord, GraphPatch,
    NodeInput, PageRequest, PropValue, ShortestPathOptions,
};
use phoenix_discovery_view::{
    AssertedDiscoveryView, DiscoveryViewError, PagedAssertedDiscoverySource,
};
use phoenix_kernel::{KernelEdge, KernelGraphLayer, KernelGraphSnapshot, KernelVertex};
use phoenix_store_native_core::StoreError;

use super::{
    btree_props, optional_string_prop, store_query_error, PhoenixOvergraphStore,
    EDGE_KERNEL_TOPOLOGY_ASSERTED, EDGE_KERNEL_TOPOLOGY_CANDIDATE, KERNEL_CHECKPOINT_KEY,
    PROP_DOCUMENT_ID, PROP_GENERATION, PROP_KIND, PROP_NODE_ID, PROP_RECORD,
    TYPE_KERNEL_CHECKPOINT, TYPE_KERNEL_TOPOLOGY_VERTEX,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KernelTopologyCounts {
    pub vertices: usize,
    pub asserted_edges: usize,
    pub candidate_edges: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KernelTopologyShortestPath {
    pub nodes: Vec<String>,
    pub edges: Vec<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KernelTopologyVertexId {
    pub stable_id: String,
    pub overgraph_id: u64,
}

impl PhoenixOvergraphStore {
    pub fn publish_kernel_topology(
        &self,
        snapshot: &KernelGraphSnapshot,
    ) -> Result<KernelTopologyCounts, StoreError> {
        self.with_engine(|engine| self.publish_kernel_topology_with_engine(engine, snapshot))
    }

    pub(crate) fn publish_kernel_topology_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        snapshot: &KernelGraphSnapshot,
    ) -> Result<KernelTopologyCounts, StoreError> {
        let stale_nodes = engine
            .get_nodes_by_type(TYPE_KERNEL_TOPOLOGY_VERTEX)
            .map_err(store_query_error)?
            .into_iter()
            .map(|node| node.id)
            .collect::<Vec<_>>();
        let stale_edges = engine
            .get_edges_by_type(EDGE_KERNEL_TOPOLOGY_ASSERTED)
            .map_err(store_query_error)?
            .into_iter()
            .chain(
                engine
                    .get_edges_by_type(EDGE_KERNEL_TOPOLOGY_CANDIDATE)
                    .map_err(store_query_error)?,
            )
            .map(|edge| edge.id)
            .collect::<Vec<_>>();
        if !stale_nodes.is_empty() || !stale_edges.is_empty() {
            engine
                .graph_patch(&GraphPatch {
                    delete_node_ids: stale_nodes,
                    delete_edge_ids: stale_edges,
                    ..Default::default()
                })
                .map_err(store_query_error)?;
        }

        let mut vertices = snapshot.vertices.iter().collect::<Vec<_>>();
        vertices.sort_unstable_by(|left, right| left.id.0.cmp(&right.id.0));
        let node_inputs = vertices
            .iter()
            .copied()
            .map(vertex_input)
            .collect::<Result<Vec<_>, _>>()?;
        let node_ids = engine
            .batch_upsert_nodes(&node_inputs)
            .map_err(store_query_error)?;
        let mut ids = HashMap::with_capacity(node_ids.len());
        for (vertex, overgraph_id) in vertices.iter().copied().zip(node_ids) {
            ids.insert(vertex.id.0.as_str(), overgraph_id);
        }

        let mut asserted_edges = snapshot.asserted_edges.iter().collect::<Vec<_>>();
        asserted_edges
            .sort_unstable_by(|left, right| edge_identity(left).cmp(&edge_identity(right)));
        let mut candidate_edges = snapshot.candidate_edges.iter().collect::<Vec<_>>();
        candidate_edges
            .sort_unstable_by(|left, right| edge_identity(left).cmp(&edge_identity(right)));
        let mut edge_inputs =
            Vec::with_capacity(snapshot.asserted_edges.len() + snapshot.candidate_edges.len());
        push_edge_inputs(
            &mut edge_inputs,
            &ids,
            &asserted_edges,
            EDGE_KERNEL_TOPOLOGY_ASSERTED,
            KernelGraphLayer::Asserted,
        )?;
        push_edge_inputs(
            &mut edge_inputs,
            &ids,
            &candidate_edges,
            EDGE_KERNEL_TOPOLOGY_CANDIDATE,
            KernelGraphLayer::Candidate,
        )?;
        if !edge_inputs.is_empty() {
            engine
                .batch_upsert_edges(&edge_inputs)
                .map_err(store_query_error)?;
        }

        Ok(KernelTopologyCounts {
            vertices: snapshot.vertices.len(),
            asserted_edges: snapshot.asserted_edges.len(),
            candidate_edges: snapshot.candidate_edges.len(),
        })
    }

    pub fn kernel_topology_counts(&self) -> Result<KernelTopologyCounts, StoreError> {
        self.with_engine(|engine| {
            Ok(KernelTopologyCounts {
                vertices: engine
                    .get_nodes_by_type(TYPE_KERNEL_TOPOLOGY_VERTEX)
                    .map_err(store_query_error)?
                    .len(),
                asserted_edges: engine
                    .get_edges_by_type(EDGE_KERNEL_TOPOLOGY_ASSERTED)
                    .map_err(store_query_error)?
                    .len(),
                candidate_edges: engine
                    .get_edges_by_type(EDGE_KERNEL_TOPOLOGY_CANDIDATE)
                    .map_err(store_query_error)?
                    .len(),
            })
        })
    }

    pub fn kernel_topology_vertex_id(
        &self,
        stable_id: &str,
    ) -> Result<Option<KernelTopologyVertexId>, StoreError> {
        self.with_engine(|engine| {
            Ok(engine
                .get_node_by_key(TYPE_KERNEL_TOPOLOGY_VERTEX, &vertex_storage_key(stable_id))
                .map_err(store_query_error)?
                .map(|node| KernelTopologyVertexId {
                    stable_id: stable_id.to_owned(),
                    overgraph_id: node.id,
                }))
        })
    }

    pub fn kernel_topology_degree(&self, stable_id: &str) -> Result<Option<u64>, StoreError> {
        self.with_engine(|engine| {
            let Some(node) = engine
                .get_node_by_key(TYPE_KERNEL_TOPOLOGY_VERTEX, &vertex_storage_key(stable_id))
                .map_err(store_query_error)?
            else {
                return Ok(None);
            };
            engine
                .degree(
                    node.id,
                    &DegreeOptions {
                        direction: Direction::Both,
                        type_filter: Some(vec![
                            EDGE_KERNEL_TOPOLOGY_ASSERTED,
                            EDGE_KERNEL_TOPOLOGY_CANDIDATE,
                        ]),
                        ..Default::default()
                    },
                )
                .map(Some)
                .map_err(store_query_error)
        })
    }

    pub fn kernel_topology_shortest_path(
        &self,
        from: &str,
        to: &str,
    ) -> Result<Option<KernelTopologyShortestPath>, StoreError> {
        self.with_engine(|engine| {
            let Some(from_node) = engine
                .get_node_by_key(TYPE_KERNEL_TOPOLOGY_VERTEX, &vertex_storage_key(from))
                .map_err(store_query_error)?
            else {
                return Ok(None);
            };
            let Some(to_node) = engine
                .get_node_by_key(TYPE_KERNEL_TOPOLOGY_VERTEX, &vertex_storage_key(to))
                .map_err(store_query_error)?
            else {
                return Ok(None);
            };
            let Some(path) = engine
                .shortest_path(
                    from_node.id,
                    to_node.id,
                    &ShortestPathOptions {
                        direction: Direction::Outgoing,
                        type_filter: Some(vec![EDGE_KERNEL_TOPOLOGY_ASSERTED]),
                        ..Default::default()
                    },
                )
                .map_err(store_query_error)?
            else {
                return Ok(None);
            };
            let nodes = engine
                .get_nodes(&path.nodes)
                .map_err(store_query_error)?
                .into_iter()
                .flatten()
                .filter_map(|node| optional_string_prop(&node, PROP_NODE_ID))
                .collect();
            Ok(Some(KernelTopologyShortestPath {
                nodes,
                edges: path.edges,
            }))
        })
    }

    pub fn kernel_topology_component_count(&self) -> Result<usize, StoreError> {
        self.with_engine(|engine| {
            let components = engine
                .connected_components(&ComponentOptions {
                    edge_type_filter: Some(vec![
                        EDGE_KERNEL_TOPOLOGY_ASSERTED,
                        EDGE_KERNEL_TOPOLOGY_CANDIDATE,
                    ]),
                    node_type_filter: Some(vec![TYPE_KERNEL_TOPOLOGY_VERTEX]),
                    ..Default::default()
                })
                .map_err(store_query_error)?;
            Ok(components.values().copied().max().unwrap_or(0) as usize)
        })
    }
}

fn vertex_input(vertex: &KernelVertex) -> Result<NodeInput, StoreError> {
    Ok(NodeInput {
        type_id: TYPE_KERNEL_TOPOLOGY_VERTEX,
        key: vertex_storage_key(&vertex.id.0),
        props: btree_props([
            (PROP_NODE_ID, PropValue::String(vertex.id.0.clone())),
            (PROP_KIND, PropValue::String(vertex.kind.clone())),
            (
                PROP_DOCUMENT_ID,
                vertex
                    .document_id
                    .clone()
                    .map(PropValue::String)
                    .unwrap_or(PropValue::Null),
            ),
            (PROP_RECORD, PropValue::Bytes(super::encode_record(vertex)?)),
        ]),
        weight: vertex.weight.max(1) as f32,
        dense_vector: None,
        sparse_vector: None,
    })
}

fn push_edge_inputs(
    out: &mut Vec<EdgeInput>,
    ids: &HashMap<&str, u64>,
    edges: &[&KernelEdge],
    edge_type_id: u32,
    layer: KernelGraphLayer,
) -> Result<(), StoreError> {
    for &edge in edges {
        let (Some(&from), Some(&to)) = (
            ids.get(edge.source_id.0.as_str()),
            ids.get(edge.target_id.0.as_str()),
        ) else {
            continue;
        };
        out.push(EdgeInput {
            from,
            to,
            type_id: edge_type_id,
            props: btree_props([
                (PROP_KIND, PropValue::String(edge.edge_type.0.clone())),
                (
                    "layer",
                    PropValue::String(match layer {
                        KernelGraphLayer::Asserted => "asserted".to_owned(),
                        KernelGraphLayer::Candidate => "candidate".to_owned(),
                    }),
                ),
                (
                    PROP_DOCUMENT_ID,
                    edge.document_id
                        .clone()
                        .map(PropValue::String)
                        .unwrap_or(PropValue::Null),
                ),
                (PROP_RECORD, PropValue::Bytes(super::encode_record(edge)?)),
            ]),
            weight: edge.weight.max(1) as f32,
            valid_from: edge.temporal.valid_from,
            valid_to: edge.temporal.valid_to,
        });
    }
    Ok(())
}

fn edge_identity(edge: &KernelEdge) -> (&str, &str, &str) {
    (&edge.source_id.0, &edge.target_id.0, &edge.edge_type.0)
}

impl PagedAssertedDiscoverySource for PhoenixOvergraphStore {
    fn generation(&self) -> Result<u64, DiscoveryViewError> {
        self.with_engine(|engine| {
            let generation = self.kernel_current_generation_with_engine(engine)?;
            if generation != 0 {
                return Ok(generation);
            }
            Ok(engine
                .get_node_by_key(TYPE_KERNEL_CHECKPOINT, KERNEL_CHECKPOINT_KEY)
                .map_err(store_query_error)?
                .as_ref()
                .and_then(|node| super::optional_u64_prop(node, PROP_GENERATION))
                .unwrap_or(0))
        })
        .map_err(discovery_source_error)
    }

    fn node_count(&self) -> Result<usize, DiscoveryViewError> {
        if let Some(source) = discovery_source_cache(self)? {
            return PagedAssertedDiscoverySource::node_count(source.as_ref());
        }
        self.with_engine(|engine| {
            engine
                .count_nodes_by_type(TYPE_KERNEL_TOPOLOGY_VERTEX)
                .map(|count| count as usize)
                .map_err(store_query_error)
        })
        .map_err(discovery_source_error)
    }

    fn asserted_edge_count(&self) -> Result<usize, DiscoveryViewError> {
        if let Some(source) = discovery_source_cache(self)? {
            return source.asserted_edge_count();
        }
        self.with_engine(|engine| {
            engine
                .count_edges_by_type(EDGE_KERNEL_TOPOLOGY_ASSERTED)
                .map(|count| count as usize)
                .map_err(store_query_error)
        })
        .map_err(discovery_source_error)
    }

    fn candidate_edge_count(&self) -> Result<usize, DiscoveryViewError> {
        if let Some(source) = discovery_source_cache(self)? {
            return source.candidate_edge_count();
        }
        self.with_engine(|engine| {
            engine
                .count_edges_by_type(EDGE_KERNEL_TOPOLOGY_CANDIDATE)
                .map(|count| count as usize)
                .map_err(store_query_error)
        })
        .map_err(discovery_source_error)
    }

    fn visit_nodes(
        &self,
        page_size: usize,
        visitor: &mut dyn FnMut(u64, &KernelVertex) -> Result<(), DiscoveryViewError>,
    ) -> Result<(), DiscoveryViewError> {
        if let Some(source) = discovery_source_cache(self)? {
            return source.visit_nodes(page_size, visitor);
        }
        self.with_engine(|engine| {
            let ids = engine
                .nodes_by_type_paged(TYPE_KERNEL_TOPOLOGY_VERTEX, &PageRequest::default())
                .map_err(store_query_error)?
                .items;
            for page in ids.chunks(page_size.max(1)) {
                for record in engine
                    .get_nodes(page)
                    .map_err(store_query_error)?
                    .into_iter()
                    .flatten()
                {
                    let vertex: KernelVertex =
                        super::decode_record_prop_required(&record, PROP_RECORD)?;
                    visitor(record.id, &vertex)
                        .map_err(|error| StoreError::Query(error.to_string()))?;
                }
            }
            Ok(())
        })
        .map_err(discovery_source_error)
    }

    fn visit_asserted_edges(
        &self,
        page_size: usize,
        visitor: &mut dyn FnMut(u64, u64, &KernelEdge) -> Result<(), DiscoveryViewError>,
    ) -> Result<(), DiscoveryViewError> {
        if let Some(source) = discovery_source_cache(self)? {
            return source.visit_asserted_edges(page_size, visitor);
        }
        self.with_engine(|engine| {
            let ids = engine
                .edges_by_type_paged(EDGE_KERNEL_TOPOLOGY_ASSERTED, &PageRequest::default())
                .map_err(store_query_error)?
                .items;
            for page in ids.chunks(page_size.max(1)) {
                for record in engine
                    .get_edges(page)
                    .map_err(store_query_error)?
                    .into_iter()
                    .flatten()
                {
                    let edge: KernelEdge = decode_topology_edge(&record)?;
                    visitor(record.from, record.to, &edge)
                        .map_err(|error| StoreError::Query(error.to_string()))?;
                }
            }
            Ok(())
        })
        .map_err(discovery_source_error)
    }
}

fn discovery_source_cache(
    store: &PhoenixOvergraphStore,
) -> Result<Option<std::sync::Arc<AssertedDiscoveryView>>, DiscoveryViewError> {
    let generation = PagedAssertedDiscoverySource::generation(store)?;
    store
        .open_discovery_source_cache(generation)
        .map_err(discovery_source_error)
}

fn decode_topology_edge(record: &EdgeRecord) -> Result<KernelEdge, StoreError> {
    let bytes = match record.props.get(PROP_RECORD) {
        Some(PropValue::Bytes(bytes)) => bytes,
        _ => {
            return Err(StoreError::Query(format!(
                "missing topology edge record {}",
                record.id
            )))
        }
    };
    super::decode_record(bytes)
}

fn discovery_source_error(error: StoreError) -> DiscoveryViewError {
    DiscoveryViewError::Invalid(format!("asserted topology source failed: {error}"))
}

fn vertex_storage_key(stable_id: &str) -> String {
    format!("kernel-topology:{stable_id}")
}

#[cfg(test)]
mod tests {
    use phoenix_discovery_view::{
        write_asserted_discovery_view, write_asserted_discovery_view_from_source,
        AssertedDiscoveryView, DiscoveryAuthorityBinding, DiscoveryRelationPolicy,
        DiscoveryViewRegistry,
    };
    use phoenix_kernel::{
        KernelEdge, KernelEdgeType, KernelGraphLayer, KernelGraphSnapshot, KernelProvenance,
        KernelRelationClass, KernelVertex, KernelVertexId,
    };
    use phoenix_store_native_core::PhoenixGraphKernelStoreV2;

    use super::*;

    fn temp_store(name: &str) -> PhoenixOvergraphStore {
        let path = std::env::temp_dir().join(format!(
            "phoenix-overgraph-topology-{name}-{}-{}",
            std::process::id(),
            super::super::now_ms()
        ));
        let _ = std::fs::remove_dir_all(&path);
        PhoenixOvergraphStore::open(&path).expect("open overgraph store")
    }

    fn vertex(id: &str, doc: &str) -> KernelVertex {
        KernelVertex {
            id: KernelVertexId(id.to_owned()),
            kind: "entity".to_owned(),
            weight: 1,
            document_id: Some(doc.to_owned()),
            ..Default::default()
        }
    }

    fn edge(source: &str, target: &str, doc: &str) -> KernelEdge {
        KernelEdge {
            source_id: KernelVertexId(source.to_owned()),
            target_id: KernelVertexId(target.to_owned()),
            edge_type: KernelEdgeType("mentions".to_owned()),
            weight: 1,
            document_id: Some(doc.to_owned()),
            ..Default::default()
        }
    }

    #[test]
    fn topology_publish_replaces_stale_vertices_and_edges() {
        let store = temp_store("replace");
        store
            .publish_kernel_topology(&KernelGraphSnapshot {
                vertices: vec![vertex("doc::old", "old"), vertex("entity::a", "old")],
                asserted_edges: vec![edge("doc::old", "entity::a", "old")],
                candidate_edges: Vec::new(),
            })
            .expect("publish old");

        store
            .publish_kernel_topology(&KernelGraphSnapshot {
                vertices: vec![vertex("doc::live", "live"), vertex("entity::b", "live")],
                asserted_edges: vec![edge("doc::live", "entity::b", "live")],
                candidate_edges: Vec::new(),
            })
            .expect("publish live");

        assert_eq!(
            store.kernel_topology_counts().expect("counts"),
            KernelTopologyCounts {
                vertices: 2,
                asserted_edges: 1,
                candidate_edges: 0,
            }
        );
        assert!(store
            .kernel_topology_vertex_id("doc::old")
            .expect("old lookup")
            .is_none());
        assert!(store
            .kernel_topology_shortest_path("doc::live", "entity::b")
            .expect("path")
            .is_some());
    }

    #[test]
    fn topology_publish_skips_dangling_edges() {
        let store = temp_store("dangling");
        store
            .publish_kernel_topology(&KernelGraphSnapshot {
                vertices: vec![vertex("entity::a", "doc")],
                asserted_edges: vec![edge("entity::a", "entity::missing", "doc")],
                candidate_edges: Vec::new(),
            })
            .expect("publish");

        assert_eq!(
            store.kernel_topology_counts().expect("counts"),
            KernelTopologyCounts {
                vertices: 1,
                asserted_edges: 0,
                candidate_edges: 0,
            }
        );
        assert_eq!(
            store.kernel_topology_degree("entity::a").expect("degree"),
            Some(0)
        );
    }

    #[test]
    fn kernel_checkpoint_publish_refreshes_overgraph_topology() {
        let store = temp_store("checkpoint-refresh");
        store
            .write_kernel_checkpoint(
                1,
                "old",
                &KernelGraphSnapshot {
                    vertices: vec![vertex("doc::old", "old"), vertex("entity::a", "old")],
                    asserted_edges: vec![edge("doc::old", "entity::a", "old")],
                    candidate_edges: Vec::new(),
                },
            )
            .expect("write old checkpoint");
        store
            .write_kernel_checkpoint(
                2,
                "live",
                &KernelGraphSnapshot {
                    vertices: vec![vertex("doc::live", "live")],
                    asserted_edges: Vec::new(),
                    candidate_edges: Vec::new(),
                },
            )
            .expect("write live checkpoint");

        assert_eq!(
            store.kernel_topology_counts().expect("counts"),
            KernelTopologyCounts {
                vertices: 1,
                asserted_edges: 0,
                candidate_edges: 0,
            }
        );
        assert!(store
            .kernel_topology_vertex_id("entity::a")
            .expect("stale lookup")
            .is_none());
    }

    #[test]
    fn paged_topology_source_is_canonical_and_payload_identical_to_snapshot_build() {
        let store = temp_store("discovery-source-parity");
        let mut nodes = vec![vertex("b", "doc"), vertex("a0", "doc"), vertex("a", "doc")];
        for node in &mut nodes {
            node.provenance = KernelProvenance {
                confidence: Some(1.0),
                evidence_refs: vec![format!("evidence-node-{}", node.id.0)],
                ..Default::default()
            };
        }
        let mut asserted = vec![edge("a0", "b", "doc"), edge("a", "b", "doc")];
        asserted[0].edge_type = KernelEdgeType("related".to_owned());
        asserted[1].edge_type = KernelEdgeType("before".to_owned());
        asserted[1].relation_class = KernelRelationClass::Temporal;
        for (index, value) in asserted.iter_mut().enumerate() {
            value.provenance = KernelProvenance {
                confidence: Some(0.8),
                evidence_refs: vec![format!("evidence-edge-{index}")],
                ..Default::default()
            };
        }
        let mut candidate = edge("b", "a", "doc");
        candidate.edge_type = KernelEdgeType("candidate-poison".to_owned());
        candidate.layer = KernelGraphLayer::Candidate;
        candidate.relation_class = KernelRelationClass::Candidate;
        let snapshot = KernelGraphSnapshot {
            vertices: nodes,
            asserted_edges: asserted,
            candidate_edges: vec![candidate],
        };
        store
            .write_kernel_checkpoint(9, "discovery-source-parity", &snapshot)
            .expect("write canonical checkpoint");

        let mut visited_nodes = Vec::new();
        store
            .visit_nodes(1, &mut |_, vertex| {
                visited_nodes.push(vertex.id.0.clone());
                Ok(())
            })
            .expect("visit paged nodes");
        assert_eq!(visited_nodes, vec!["a", "a0", "b"]);
        let mut visited_edges = Vec::new();
        store
            .visit_asserted_edges(1, &mut |_, _, edge| {
                visited_edges.push((
                    edge.source_id.0.clone(),
                    edge.target_id.0.clone(),
                    edge.edge_type.0.clone(),
                ));
                Ok(())
            })
            .expect("visit paged edges");
        assert_eq!(
            visited_edges,
            vec![
                ("a".to_owned(), "b".to_owned(), "before".to_owned()),
                ("a0".to_owned(), "b".to_owned(), "related".to_owned()),
            ]
        );

        let authority = DiscoveryAuthorityBinding {
            generation: 9,
            source_snapshot_id: "source-parity".to_owned(),
            source_snapshot_digest: *blake3::hash(b"source-parity-snapshot").as_bytes(),
            evidence_registry_digest: *blake3::hash(b"source-parity-evidence").as_bytes(),
        };
        let policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
        let legacy_root = tempfile::tempdir().expect("legacy root");
        let source_root = tempfile::tempdir().expect("source root");
        let legacy =
            write_asserted_discovery_view(&snapshot, &authority, &policy, legacy_root.path())
                .expect("legacy discovery build");
        let packed = write_asserted_discovery_view_from_source(
            &store,
            &authority,
            &policy,
            source_root.path(),
        )
        .expect("paged discovery build");
        assert_eq!(packed.payload_digest, legacy.payload_digest);
        assert_eq!(packed.binary_bytes, legacy.binary_bytes);
        assert_eq!(packed.excluded_candidate_edges, 1);
        assert_eq!(packed.admitted_candidate_edges, 0);
        AssertedDiscoveryView::open(source_root.path().join(&packed.artifact_digest))
            .expect("open packed view")
            .validate_payload()
            .expect("validate packed payload");

        let registry_root = tempfile::tempdir().expect("registry root");
        let registry = DiscoveryViewRegistry::new(registry_root.path());
        let receipt = registry
            .publish_from_source(&store, &authority, &policy)
            .expect("publish paged source generation");
        assert_eq!(receipt.artifact_digest, packed.artifact_digest);
        assert_eq!(receipt.admitted_candidate_edges, 0);
        assert_eq!(
            registry
                .open_generation(9)
                .expect("open generation")
                .edge_count(),
            2
        );
    }
}
