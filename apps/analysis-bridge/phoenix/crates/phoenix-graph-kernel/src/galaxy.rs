use crate::{
    KernelEdge, KernelGraphLayer, KernelGraphSnapshot, KernelRelationClass, KernelVertex,
    KernelVertexClass,
};
use hashbrown::HashMap;
use rustc_hash::FxHasher;
use serde::{Deserialize, Serialize};
use std::hash::BuildHasherDefault;
use std::mem;
use std::path::Path;
use zerocopy::{AsBytes, FromBytes, FromZeroes};

type FastBuildHasher = BuildHasherDefault<FxHasher>;
type FastMap<K, V> = HashMap<K, V, FastBuildHasher>;

#[repr(C)]
#[derive(
    Clone,
    Copy,
    Debug,
    Default,
    PartialEq,
    Eq,
    Serialize,
    Deserialize,
    AsBytes,
    FromBytes,
    FromZeroes,
)]
pub struct GalaxyNodeRecord {
    pub entity_index: u32,
    pub label_offset: u32,
    pub label_len: u32,
    pub importance_millis: u32,
    pub kind_code: u16,
    pub flags: u16,
}

#[repr(C)]
#[derive(
    Clone,
    Copy,
    Debug,
    Default,
    PartialEq,
    Eq,
    Serialize,
    Deserialize,
    AsBytes,
    FromBytes,
    FromZeroes,
)]
pub struct GalaxyEdgeRecord {
    pub source: u32,
    pub target: u32,
    pub weight_millis: u32,
    pub edge_kind: u16,
    pub flags: u16,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyBuildOptions {
    pub include_candidate_edges: bool,
    pub min_weight_millis: u32,
}

impl Default for GalaxyBuildOptions {
    fn default() -> Self {
        Self {
            include_candidate_edges: false,
            min_weight_millis: 1,
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyPackStats {
    pub node_count: usize,
    pub edge_count: usize,
    pub skipped_edges: usize,
    pub label_bytes: usize,
    pub resident_bytes: usize,
    pub node_record_bytes: usize,
    pub edge_record_bytes: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyGraphPack {
    pub entity_ids: Vec<String>,
    pub label_slab: Vec<u8>,
    pub nodes: Vec<GalaxyNodeRecord>,
    pub edges: Vec<GalaxyEdgeRecord>,
    pub skipped_edges: usize,
}

impl GalaxyGraphPack {
    pub fn from_snapshot(snapshot: &KernelGraphSnapshot, options: GalaxyBuildOptions) -> Self {
        let mut entity_ids = Vec::with_capacity(snapshot.vertices.len());
        let mut label_slab = Vec::with_capacity(snapshot.vertices.len().saturating_mul(16));
        let mut nodes = Vec::with_capacity(snapshot.vertices.len());
        let mut dense = fast_map_with_capacity(snapshot.vertices.len());

        for vertex in &snapshot.vertices {
            if !is_entity_vertex(vertex) {
                continue;
            }
            let entity_id = canonical_entity_id(vertex);
            if let Some(&entity_index) = dense.get(entity_id) {
                insert_dense_alias(&mut dense, &vertex.id.0, entity_index);
                if let Some(raw_entity_id) = vertex.entity_id.as_deref() {
                    insert_dense_alias(&mut dense, raw_entity_id, entity_index);
                }
                continue;
            }

            let entity_index = usize_to_u32(entity_ids.len());
            insert_dense_alias(&mut dense, entity_id, entity_index);
            insert_dense_alias(&mut dense, &vertex.id.0, entity_index);
            if let Some(raw_entity_id) = vertex.entity_id.as_deref() {
                insert_dense_alias(&mut dense, raw_entity_id, entity_index);
            }
            entity_ids.push(entity_id.to_owned());

            let label = entity_label(vertex, entity_id);
            let label_offset = usize_to_u32(label_slab.len());
            label_slab.extend_from_slice(label.as_bytes());
            nodes.push(GalaxyNodeRecord {
                entity_index,
                label_offset,
                label_len: usize_to_u32(label.len()),
                importance_millis: weight_millis(vertex.weight),
                kind_code: vertex_kind_code(vertex),
                flags: vertex_flags(vertex),
            });
        }

        let mut raw_edges = Vec::with_capacity(
            snapshot.asserted_edges.len()
                + if options.include_candidate_edges {
                    snapshot.candidate_edges.len()
                } else {
                    0
                },
        );
        let mut skipped_edges = collect_edges(
            &snapshot.asserted_edges,
            &dense,
            &mut raw_edges,
            GalaxyEdgeFlags::ASSERTED,
        );

        if options.include_candidate_edges {
            skipped_edges += collect_edges(
                &snapshot.candidate_edges,
                &dense,
                &mut raw_edges,
                GalaxyEdgeFlags::CANDIDATE,
            );
        }

        let edges = aggregate_edges(raw_edges, options.min_weight_millis);

        Self {
            entity_ids,
            label_slab,
            nodes,
            edges,
            skipped_edges,
        }
    }

    pub fn node_bytes(&self) -> &[u8] {
        self.nodes.as_slice().as_bytes()
    }

    pub fn edge_bytes(&self) -> &[u8] {
        self.edges.as_slice().as_bytes()
    }

    pub fn memory_bytes(&self) -> usize {
        let id_bytes = self
            .entity_ids
            .iter()
            .map(|id| id.capacity())
            .sum::<usize>();
        self.entity_ids.capacity() * mem::size_of::<String>()
            + id_bytes
            + self.label_slab.capacity()
            + self.nodes.capacity() * mem::size_of::<GalaxyNodeRecord>()
            + self.edges.capacity() * mem::size_of::<GalaxyEdgeRecord>()
    }

    pub fn stats(&self) -> GalaxyPackStats {
        GalaxyPackStats {
            node_count: self.nodes.len(),
            edge_count: self.edges.len(),
            skipped_edges: self.skipped_edges,
            label_bytes: self.label_slab.len(),
            resident_bytes: self.memory_bytes(),
            node_record_bytes: self.node_bytes().len(),
            edge_record_bytes: self.edge_bytes().len(),
        }
    }

    pub fn node_label(&self, node: GalaxyNodeRecord) -> Option<&str> {
        let start = node.label_offset as usize;
        let end = start.checked_add(node.label_len as usize)?;
        std::str::from_utf8(self.label_slab.get(start..end)?).ok()
    }

    pub fn write_immutable_store(
        &self,
        manifolds: &[crate::GalaxyManifoldPositions],
        output: impl AsRef<Path>,
        options: crate::GalaxyGraphStoreBuildOptions,
    ) -> Result<crate::GalaxyStoreManifest, crate::GalaxyStoreError> {
        crate::write_galaxy_graph_store(self, manifolds, output, options)
    }
}

pub fn galaxy_graph_from_snapshot(
    snapshot: &KernelGraphSnapshot,
    options: GalaxyBuildOptions,
) -> GalaxyGraphPack {
    GalaxyGraphPack::from_snapshot(snapshot, options)
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct RawGalaxyEdge {
    source: u32,
    target: u32,
    weight_millis: u32,
    edge_kind: u16,
    flags: u16,
}

struct GalaxyEdgeFlags;

impl GalaxyEdgeFlags {
    const ASSERTED: u16 = 0;
    const CANDIDATE: u16 = 1;
}

fn fast_map_with_capacity<K, V>(capacity: usize) -> FastMap<K, V> {
    HashMap::with_capacity_and_hasher(capacity, FastBuildHasher::default())
}

fn insert_dense_alias(dense: &mut FastMap<String, u32>, alias: &str, entity_index: u32) {
    if !alias.is_empty() {
        dense.entry(alias.to_owned()).or_insert(entity_index);
    }
}

fn is_entity_vertex(vertex: &KernelVertex) -> bool {
    matches!(vertex.class, KernelVertexClass::Entity) || vertex.entity_id.is_some()
}

fn canonical_entity_id(vertex: &KernelVertex) -> &str {
    vertex
        .entity_facet
        .as_ref()
        .and_then(|facet| facet.canonical_entity_id.as_deref())
        .or(vertex.entity_id.as_deref())
        .unwrap_or(&vertex.id.0)
}

fn entity_label<'a>(vertex: &'a KernelVertex, fallback: &'a str) -> &'a str {
    vertex
        .entity_facet
        .as_ref()
        .and_then(|facet| facet.surface.as_deref())
        .or_else(|| vertex.value.get("label").and_then(|value| value.as_str()))
        .or_else(|| vertex.value.get("name").and_then(|value| value.as_str()))
        .or_else(|| vertex.labels.first().map(|label| label.as_str()))
        .unwrap_or(fallback)
}

fn vertex_kind_code(vertex: &KernelVertex) -> u16 {
    let kind = vertex
        .entity_facet
        .as_ref()
        .and_then(|facet| facet.entity_kind.as_deref())
        .filter(|kind| !kind.is_empty())
        .unwrap_or(&vertex.kind);
    stable_kind_code(kind)
}

fn vertex_flags(vertex: &KernelVertex) -> u16 {
    let mut flags = 0u16;
    if matches!(vertex.class, KernelVertexClass::Entity) {
        flags |= 1;
    }
    if vertex.note_id.is_some() {
        flags |= 1 << 1;
    }
    if vertex.document_id.is_some() {
        flags |= 1 << 2;
    }
    flags
}

fn collect_edges(
    edges: &[KernelEdge],
    dense: &FastMap<String, u32>,
    raw_edges: &mut Vec<RawGalaxyEdge>,
    flags: u16,
) -> usize {
    let mut skipped = 0usize;
    for edge in edges {
        let Some(&source) = dense.get(&edge.source_id.0) else {
            skipped += 1;
            continue;
        };
        let Some(&target) = dense.get(&edge.target_id.0) else {
            skipped += 1;
            continue;
        };
        if source == target {
            skipped += 1;
            continue;
        }
        let (source, target) = if source < target {
            (source, target)
        } else {
            (target, source)
        };
        raw_edges.push(RawGalaxyEdge {
            source,
            target,
            weight_millis: weight_millis(edge.weight),
            edge_kind: edge_kind_code(edge),
            flags: flags | layer_flag(edge.layer.clone()),
        });
    }
    skipped
}

fn aggregate_edges(
    mut raw_edges: Vec<RawGalaxyEdge>,
    min_weight_millis: u32,
) -> Vec<GalaxyEdgeRecord> {
    raw_edges.sort_unstable_by_key(|edge| (edge.source, edge.target, edge.edge_kind, edge.flags));
    let mut edges = Vec::with_capacity(raw_edges.len());
    let mut iter = raw_edges.into_iter();
    let Some(mut current) = iter.next() else {
        return edges;
    };

    for edge in iter {
        if edge.source == current.source
            && edge.target == current.target
            && edge.edge_kind == current.edge_kind
            && edge.flags == current.flags
        {
            current.weight_millis = current.weight_millis.saturating_add(edge.weight_millis);
        } else {
            push_edge(&mut edges, current, min_weight_millis);
            current = edge;
        }
    }
    push_edge(&mut edges, current, min_weight_millis);
    edges
}

fn push_edge(edges: &mut Vec<GalaxyEdgeRecord>, edge: RawGalaxyEdge, min_weight_millis: u32) {
    if edge.weight_millis < min_weight_millis {
        return;
    }
    edges.push(GalaxyEdgeRecord {
        source: edge.source,
        target: edge.target,
        weight_millis: edge.weight_millis,
        edge_kind: edge.edge_kind,
        flags: edge.flags,
    });
}

fn layer_flag(layer: KernelGraphLayer) -> u16 {
    match layer {
        KernelGraphLayer::Asserted => 0,
        KernelGraphLayer::Candidate => GalaxyEdgeFlags::CANDIDATE,
    }
}

fn edge_kind_code(edge: &KernelEdge) -> u16 {
    let edge_code = stable_kind_code(&edge.edge_type.0);
    if edge_code != 0 {
        return edge_code;
    }
    relation_class_code(&edge.relation_class)
}

fn relation_class_code(class: &KernelRelationClass) -> u16 {
    match class {
        KernelRelationClass::Structural => 1,
        KernelRelationClass::Semantic => 2,
        KernelRelationClass::Identity => 3,
        KernelRelationClass::Resolution => 4,
        KernelRelationClass::Temporal => 5,
        KernelRelationClass::Calendar => 6,
        KernelRelationClass::Memory => 7,
        KernelRelationClass::Narrative => 8,
        KernelRelationClass::Candidate => 9,
        KernelRelationClass::Custom => 0,
    }
}

fn stable_kind_code(kind: &str) -> u16 {
    match kind.to_ascii_lowercase().as_str() {
        "" | "generic" | "custom" => 0,
        "character" => 1,
        "npc" => 2,
        "location" => 3,
        "faction" => 4,
        "organization" => 5,
        "network" => 6,
        "item" => 7,
        "event" => 8,
        "concept" => 9,
        "narrative" => 10,
        other => stable_u16(other.as_bytes()),
    }
}

fn stable_u16(bytes: &[u8]) -> u16 {
    let mut hash = 0xcbf2_9ce4_8422_2325u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    (hash as u16).max(1)
}

fn weight_millis(weight: i64) -> u32 {
    if weight <= 0 {
        1
    } else {
        u32::try_from(weight).unwrap_or(u32::MAX)
    }
}

fn usize_to_u32(value: usize) -> u32 {
    u32::try_from(value).unwrap_or(u32::MAX)
}
