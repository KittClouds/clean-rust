use crate::{
    ann::search::{search_view, GraphView},
    MetricF32, MetricIdentity, SearchFilter, SearchHit, SearchParams, SearchScratch,
};
use crate::{DenseVectorId, HnswBuildOptions, HyperbolicDiskError, StableVectorId};
use bytemuck::{Pod, Zeroable};

pub(crate) const NODE_FLAG_DELETED: u8 = 1;

#[derive(Clone, Copy, Debug, Pod, Zeroable)]
#[repr(C)]
pub(crate) struct NodeRecord {
    pub stable_id: u64,
    pub tag_mask: u64,
    pub upper_row_start: u32,
    pub upper_row_count: u16,
    pub level: u8,
    pub flags: u8,
}

#[derive(Clone, Copy, Debug, Pod, Zeroable)]
#[repr(C)]
pub(crate) struct UpperRowRecord {
    pub neighbor_offset: u64,
    pub neighbor_count: u32,
    pub level: u16,
    pub reserved: u16,
}

#[derive(Clone, Debug)]
pub struct FrozenHnsw {
    pub(crate) dimension: u32,
    pub(crate) entry_point: u32,
    pub(crate) maximum_level: u8,
    pub(crate) options: HnswBuildOptions,
    pub(crate) metric_identity: MetricIdentity,
    pub(crate) nodes: Box<[NodeRecord]>,
    pub(crate) vectors: Box<[f32]>,
    pub(crate) base_offsets: Box<[u64]>,
    pub(crate) base_neighbors: Box<[u32]>,
    pub(crate) upper_rows: Box<[UpperRowRecord]>,
    pub(crate) upper_neighbors: Box<[u32]>,
}

/// Allocation-free input for a future Vamana/DiskANN publisher.
///
/// The HNSW base CSR is exposed as an optional warm-start or comparison graph.
/// It must not be mislabeled as a Vamana graph.
#[derive(Clone, Copy)]
pub struct DiskAnnSourceView<'a> {
    dimension: usize,
    nodes: &'a [NodeRecord],
    vectors: &'a [f32],
    base_offsets: &'a [u64],
    base_neighbors: &'a [u32],
}

impl<'a> DiskAnnSourceView<'a> {
    pub(crate) const fn new(
        dimension: usize,
        nodes: &'a [NodeRecord],
        vectors: &'a [f32],
        base_offsets: &'a [u64],
        base_neighbors: &'a [u32],
    ) -> Self {
        Self {
            dimension,
            nodes,
            vectors,
            base_offsets,
            base_neighbors,
        }
    }

    pub const fn dimension(self) -> usize {
        self.dimension
    }

    pub fn len(self) -> usize {
        self.nodes.len()
    }

    pub fn is_empty(self) -> bool {
        self.nodes.is_empty()
    }

    pub fn live_len(self) -> usize {
        self.nodes
            .iter()
            .filter(|node| node.flags & NODE_FLAG_DELETED == 0)
            .count()
    }

    pub fn stable_id(self, dense_id: DenseVectorId) -> Option<StableVectorId> {
        self.nodes
            .get(dense_id.0 as usize)
            .and_then(|record| StableVectorId::new(record.stable_id).ok())
    }

    pub fn tag_mask(self, dense_id: DenseVectorId) -> Option<u64> {
        self.nodes
            .get(dense_id.0 as usize)
            .map(|record| record.tag_mask)
    }

    pub fn is_deleted(self, dense_id: DenseVectorId) -> Option<bool> {
        self.nodes
            .get(dense_id.0 as usize)
            .map(|record| record.flags & NODE_FLAG_DELETED != 0)
    }

    pub fn vector(self, dense_id: DenseVectorId) -> Option<&'a [f32]> {
        let start = dense_id.0 as usize * self.dimension;
        self.vectors.get(start..start + self.dimension)
    }

    pub fn base_neighbors(self, dense_id: DenseVectorId) -> Option<&'a [u32]> {
        let index = dense_id.0 as usize;
        let start = *self.base_offsets.get(index)? as usize;
        let end = *self.base_offsets.get(index + 1)? as usize;
        self.base_neighbors.get(start..end)
    }

    pub const fn vectors(self) -> &'a [f32] {
        self.vectors
    }

    pub const fn base_offsets(self) -> &'a [u64] {
        self.base_offsets
    }

    pub const fn base_neighbors_flat(self) -> &'a [u32] {
        self.base_neighbors
    }
}

impl FrozenHnsw {
    pub fn dimension(&self) -> usize {
        self.dimension as usize
    }

    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    pub fn entry_point(&self) -> Option<DenseVectorId> {
        (!self.nodes.is_empty()).then_some(DenseVectorId(self.entry_point))
    }

    pub fn metric_identity(&self) -> MetricIdentity {
        self.metric_identity
    }

    pub fn diskann_source(&self) -> DiskAnnSourceView<'_> {
        DiskAnnSourceView::new(
            self.dimension(),
            &self.nodes,
            &self.vectors,
            &self.base_offsets,
            &self.base_neighbors,
        )
    }

    pub fn stable_id(&self, dense_id: DenseVectorId) -> Option<StableVectorId> {
        self.nodes
            .get(dense_id.0 as usize)
            .and_then(|record| StableVectorId::new(record.stable_id).ok())
    }

    pub fn vector(&self, dense_id: DenseVectorId) -> Option<&[f32]> {
        let start = dense_id.0 as usize * self.dimension();
        self.vectors.get(start..start + self.dimension())
    }

    pub fn base_neighbors(&self, dense_id: DenseVectorId) -> Option<&[u32]> {
        let index = dense_id.0 as usize;
        let start = *self.base_offsets.get(index)? as usize;
        let end = *self.base_offsets.get(index + 1)? as usize;
        self.base_neighbors.get(start..end)
    }

    pub fn search_with_scratch<'a, M, F>(
        &self,
        metric: &M,
        query: &[f32],
        params: SearchParams,
        filter: &F,
        scratch: &'a mut SearchScratch,
    ) -> Result<&'a [SearchHit], HyperbolicDiskError>
    where
        M: MetricF32,
        F: SearchFilter,
    {
        if metric.identity() != self.metric_identity {
            return Err(HyperbolicDiskError::MetricMismatch {
                expected: self.metric_identity,
                actual: metric.identity(),
            });
        }
        search_view(self, metric, query, params, filter, scratch)?;
        Ok(scratch.hits())
    }
}

impl GraphView for FrozenHnsw {
    fn dimension(&self) -> usize {
        self.dimension()
    }

    fn node_count(&self) -> usize {
        self.nodes.len()
    }

    fn maximum_level(&self) -> u8 {
        self.maximum_level
    }

    fn entry_point(&self) -> u32 {
        self.entry_point
    }

    fn node(&self, id: u32) -> Option<NodeRecord> {
        self.nodes.get(id as usize).copied()
    }

    fn vector(&self, id: u32) -> Option<&[f32]> {
        self.vector(DenseVectorId(id))
    }

    fn base_neighbors(&self, id: u32) -> Option<&[u32]> {
        self.base_neighbors(DenseVectorId(id))
    }

    fn upper_neighbors(&self, id: u32, level: u8) -> Option<&[u32]> {
        let node = self.nodes.get(id as usize)?;
        let start = node.upper_row_start as usize;
        let rows = self
            .upper_rows
            .get(start..start + node.upper_row_count as usize)?;
        let row = rows.iter().find(|row| row.level == u16::from(level))?;
        let start = row.neighbor_offset as usize;
        self.upper_neighbors
            .get(start..start + row.neighbor_count as usize)
    }
}
