use crate::ann::frozen::{FrozenHnsw, NodeRecord, UpperRowRecord, NODE_FLAG_DELETED};
use crate::ann::metric::validate_vector;
use crate::ann::search::{search_view, GraphView};
use crate::{
    Candidate, DenseVectorId, HnswBuildOptions, HnswBuildParams, HyperbolicDiskError, MetricF32,
    NoFilter, NodeMetadata, SearchFilter, SearchHit, SearchParams, SearchScratch, StableVectorId,
};
use hashbrown::HashMap;
use smallvec::SmallVec;
use std::cmp::Reverse;
use std::collections::BinaryHeap;

#[derive(Debug)]
pub struct BuildNode {
    pub id: u32,
    pub stable_id: StableVectorId,
    pub vector: Vec<f32>,
    pub connections: Vec<SmallVec<[u32; 32]>>,
    pub level: u8,
    pub metadata: NodeMetadata,
    pub deleted: bool,
}

#[derive(Debug, Default)]
struct BuildScratch {
    visited_epochs: Vec<u32>,
    epoch: u32,
    frontier: BinaryHeap<Reverse<Candidate>>,
    results: BinaryHeap<Candidate>,
}

impl BuildScratch {
    fn begin(&mut self, nodes: usize, ef: usize) {
        if self.visited_epochs.len() < nodes {
            self.visited_epochs.resize(nodes, 0);
        }
        self.frontier.clear();
        self.results.clear();
        self.epoch = self.epoch.wrapping_add(1);
        if self.epoch == 0 {
            self.visited_epochs.fill(0);
            self.epoch = 1;
        }
        self.frontier
            .reserve(ef.saturating_sub(self.frontier.capacity()));
        self.results
            .reserve(ef.saturating_sub(self.results.capacity()));
    }

    #[inline]
    fn visit(&mut self, id: u32) -> bool {
        let slot = &mut self.visited_epochs[id as usize];
        if *slot == self.epoch {
            false
        } else {
            *slot = self.epoch;
            true
        }
    }
}

#[derive(Debug)]
pub struct HyperbolicHnswBuilder<M: MetricF32> {
    nodes: Vec<BuildNode>,
    stable_to_dense: HashMap<StableVectorId, u32>,
    entry_point: Option<u32>,
    maximum_level: u8,
    options: HnswBuildOptions,
    metric: M,
    dimension: usize,
    scratch: BuildScratch,
}

impl<M: MetricF32> HyperbolicHnswBuilder<M> {
    pub fn new(dimension: usize, metric: M, params: HnswBuildParams) -> Self {
        Self::try_new(
            dimension,
            metric,
            HnswBuildOptions {
                params,
                ..HnswBuildOptions::default()
            },
        )
        .unwrap_or_else(|error| panic!("invalid HNSW builder configuration: {error}"))
    }

    pub fn try_new(
        dimension: usize,
        metric: M,
        options: HnswBuildOptions,
    ) -> Result<Self, HyperbolicDiskError> {
        if dimension == 0 || dimension > u32::MAX as usize {
            return Err(HyperbolicDiskError::InvalidDimension {
                actual: dimension,
                maximum: u32::MAX as usize,
            });
        }
        Ok(Self {
            nodes: Vec::new(),
            stable_to_dense: HashMap::new(),
            entry_point: None,
            maximum_level: 0,
            options: options.validate()?,
            metric,
            dimension,
            scratch: BuildScratch::default(),
        })
    }

    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    pub fn dimension(&self) -> usize {
        self.dimension
    }

    pub fn dense_id(&self, stable_id: StableVectorId) -> Option<DenseVectorId> {
        self.stable_to_dense
            .get(&stable_id)
            .copied()
            .map(DenseVectorId)
    }

    pub fn stable_id(&self, dense_id: DenseVectorId) -> Option<StableVectorId> {
        self.nodes
            .get(dense_id.get() as usize)
            .map(|node| node.stable_id)
    }

    pub fn entry_point(&self) -> Option<DenseVectorId> {
        self.entry_point.map(DenseVectorId)
    }

    pub fn contains(&self, stable_id: StableVectorId) -> bool {
        self.stable_to_dense.contains_key(&stable_id)
    }

    pub fn set_metadata(&mut self, stable_id: StableVectorId, metadata: NodeMetadata) -> bool {
        let Some(dense_id) = self.dense_id(stable_id) else {
            return false;
        };
        self.nodes[dense_id.get() as usize].metadata = metadata;
        true
    }

    pub fn insert(&mut self, vector: Vec<f32>) -> Result<u32, HyperbolicDiskError> {
        let mut raw = self.nodes.len() as u64 + 1;
        while self
            .stable_to_dense
            .contains_key(&StableVectorId::new(raw)?)
        {
            raw = raw
                .checked_add(1)
                .ok_or(HyperbolicDiskError::DenseIdOverflow)?;
        }
        self.insert_with_id(StableVectorId::new(raw)?, vector, NodeMetadata::default())
            .map(DenseVectorId::get)
    }

    pub fn insert_with_id(
        &mut self,
        stable_id: StableVectorId,
        mut vector: Vec<f32>,
        metadata: NodeMetadata,
    ) -> Result<DenseVectorId, HyperbolicDiskError> {
        if vector.len() != self.dimension {
            return Err(HyperbolicDiskError::DimensionMismatch {
                id: stable_id,
                expected: self.dimension,
                actual: vector.len(),
            });
        }
        if self.stable_to_dense.contains_key(&stable_id) {
            return Err(HyperbolicDiskError::DuplicateVectorId { id: stable_id });
        }
        if self.nodes.len() == u32::MAX as usize {
            return Err(HyperbolicDiskError::DenseIdOverflow);
        }
        validate_vector(&vector)?;
        self.metric.project_to_ball(&mut vector);
        validate_vector(&vector)?;

        let id = self.nodes.len() as u32;
        let level = deterministic_level(
            stable_id,
            self.options.seed,
            self.options.params.level_mult,
            self.options.maximum_level,
        );
        let mut connections = vec![SmallVec::new(); level as usize + 1];

        if let Some(entry) = self.entry_point {
            let mut current = entry;
            let mut current_distance = self
                .metric
                .rank_eval(&vector, &self.nodes[current as usize].vector);
            for search_level in ((level + 1)..=self.maximum_level).rev() {
                (current, current_distance) =
                    self.greedy_descent(&vector, current, current_distance, search_level);
            }
            for search_level in (0..=level.min(self.maximum_level)).rev() {
                let maximum = self.maximum_connections(search_level);
                let candidates = self.search_layer(
                    &vector,
                    current,
                    self.options.params.ef_construction,
                    search_level,
                );
                let selected = self.select_neighbors(&vector, candidates, maximum);
                current = selected.first().copied().unwrap_or(current);
                connections[search_level as usize].extend(selected);
            }
        }

        self.nodes.push(BuildNode {
            id,
            stable_id,
            vector,
            connections,
            level,
            metadata,
            deleted: false,
        });
        self.stable_to_dense.insert(stable_id, id);

        for search_level in 0..=level.min(self.maximum_level) {
            let neighbors = self.nodes[id as usize].connections[search_level as usize].clone();
            for neighbor in neighbors {
                self.nodes[neighbor as usize].connections[search_level as usize].push(id);
                self.prune_node(neighbor, search_level);
            }
        }
        if self.entry_point.is_none() || level > self.maximum_level {
            self.entry_point = Some(id);
            self.maximum_level = level;
        }
        Ok(DenseVectorId(id))
    }

    pub fn insert_batch_deterministic(
        &mut self,
        mut rows: Vec<(StableVectorId, Vec<f32>, NodeMetadata)>,
    ) -> Result<(), HyperbolicDiskError> {
        rows.sort_unstable_by_key(|row| row.0);
        for pair in rows.windows(2) {
            if pair[0].0 == pair[1].0 {
                return Err(HyperbolicDiskError::DuplicateVectorId { id: pair[0].0 });
            }
        }
        for (stable_id, vector, metadata) in rows {
            self.insert_with_id(stable_id, vector, metadata)?;
        }
        Ok(())
    }

    pub fn delete(&mut self, stable_id: StableVectorId) -> bool {
        let Some(&dense_id) = self.stable_to_dense.get(&stable_id) else {
            return false;
        };
        let node = &mut self.nodes[dense_id as usize];
        if node.deleted {
            false
        } else {
            node.deleted = true;
            if self.entry_point == Some(dense_id) {
                self.reselect_entry();
            }
            true
        }
    }

    pub fn search(&self, query: &[f32], k: usize, ef_search: usize) -> Vec<Candidate> {
        let mut scratch = SearchScratch::new();
        match self.search_with_scratch(
            query,
            SearchParams::new(k, ef_search.max(k)),
            &NoFilter,
            &mut scratch,
        ) {
            Ok(hits) => hits
                .iter()
                .map(|hit| Candidate {
                    id: hit.dense_id.get(),
                    dist: hit.distance,
                })
                .collect(),
            Err(_) => Vec::new(),
        }
    }

    pub fn search_with_scratch<'a, F>(
        &self,
        query: &[f32],
        params: SearchParams,
        filter: &F,
        scratch: &'a mut SearchScratch,
    ) -> Result<&'a [SearchHit], HyperbolicDiskError>
    where
        F: SearchFilter,
    {
        search_view(self, &self.metric, query, params, filter, scratch)
    }

    pub fn freeze(self) -> FrozenHnsw {
        let mut vectors = Vec::with_capacity(self.nodes.len() * self.dimension);
        let mut nodes = Vec::with_capacity(self.nodes.len());
        let mut base_offsets = Vec::with_capacity(self.nodes.len() + 1);
        let mut base_neighbors = Vec::new();
        let mut upper_rows = Vec::new();
        let mut upper_neighbors = Vec::new();
        base_offsets.push(0);

        for node in &self.nodes {
            vectors.extend_from_slice(&node.vector);
            let upper_row_start = upper_rows.len() as u32;
            for level in 1..=node.level {
                let neighbors = &node.connections[level as usize];
                upper_rows.push(UpperRowRecord {
                    neighbor_offset: upper_neighbors.len() as u64,
                    neighbor_count: neighbors.len() as u32,
                    level: u16::from(level),
                    reserved: 0,
                });
                upper_neighbors.extend(neighbors.iter().copied());
            }
            base_neighbors.extend(node.connections[0].iter().copied());
            base_offsets.push(base_neighbors.len() as u64);
            nodes.push(NodeRecord {
                stable_id: node.stable_id.get(),
                tag_mask: node.metadata.tag_mask,
                upper_row_start,
                upper_row_count: node.level as u16,
                level: node.level,
                flags: u8::from(node.deleted) * NODE_FLAG_DELETED,
            });
        }
        FrozenHnsw {
            dimension: self.dimension as u32,
            entry_point: self.entry_point.unwrap_or(0),
            maximum_level: self.maximum_level,
            options: self.options,
            metric_identity: self.metric.identity(),
            nodes: nodes.into_boxed_slice(),
            vectors: vectors.into_boxed_slice(),
            base_offsets: base_offsets.into_boxed_slice(),
            base_neighbors: base_neighbors.into_boxed_slice(),
            upper_rows: upper_rows.into_boxed_slice(),
            upper_neighbors: upper_neighbors.into_boxed_slice(),
        }
    }

    pub fn into_packed(self) -> crate::PackedHnswGraph {
        crate::PackedHnswGraph::from_frozen(&self.freeze())
    }

    pub fn save_to_disk(
        self,
        path: impl AsRef<std::path::Path>,
    ) -> Result<crate::ArchiveReceipt, HyperbolicDiskError> {
        self.freeze().write_new(path)
    }

    fn maximum_connections(&self, level: u8) -> usize {
        if level == 0 {
            self.options.params.m0
        } else {
            self.options.params.m
        }
    }

    fn reselect_entry(&mut self) {
        let mut best = None::<(u8, u32)>;
        for node in self.nodes.iter().filter(|node| !node.deleted) {
            if best.is_none_or(|(level, id)| {
                node.level > level || (node.level == level && node.id < id)
            }) {
                best = Some((node.level, node.id));
            }
        }
        self.entry_point = best.map(|(_, id)| id);
        self.maximum_level = best.map_or(0, |(level, _)| level);
    }

    fn greedy_descent(
        &self,
        query: &[f32],
        mut current: u32,
        mut current_distance: f32,
        level: u8,
    ) -> (u32, f32) {
        loop {
            let mut changed = false;
            for &neighbor in &self.nodes[current as usize].connections[level as usize] {
                if self.nodes[neighbor as usize].deleted {
                    continue;
                }
                let distance = self
                    .metric
                    .rank_eval(query, &self.nodes[neighbor as usize].vector);
                if distance < current_distance
                    || (distance.to_bits() == current_distance.to_bits() && neighbor < current)
                {
                    current = neighbor;
                    current_distance = distance;
                    changed = true;
                }
            }
            if !changed {
                return (current, current_distance);
            }
        }
    }

    fn search_layer(&mut self, query: &[f32], entry: u32, ef: usize, level: u8) -> Vec<Candidate> {
        self.scratch.begin(self.nodes.len(), ef);
        let entry_distance = self
            .metric
            .rank_eval(query, &self.nodes[entry as usize].vector);
        let first = Candidate {
            id: entry,
            dist: entry_distance,
        };
        self.scratch.visit(entry);
        self.scratch.frontier.push(Reverse(first));
        self.scratch.results.push(first);
        while let Some(Reverse(candidate)) = self.scratch.frontier.pop() {
            if self.scratch.results.len() >= ef
                && self
                    .scratch
                    .results
                    .peek()
                    .is_some_and(|worst| candidate.dist > worst.dist)
            {
                break;
            }
            for &neighbor in &self.nodes[candidate.id as usize].connections[level as usize] {
                if self.nodes[neighbor as usize].deleted || !self.scratch.visit(neighbor) {
                    continue;
                }
                let next = Candidate {
                    id: neighbor,
                    dist: self
                        .metric
                        .rank_eval(query, &self.nodes[neighbor as usize].vector),
                };
                if self.scratch.results.len() < ef
                    || self
                        .scratch
                        .results
                        .peek()
                        .is_some_and(|worst| next < *worst)
                {
                    self.scratch.frontier.push(Reverse(next));
                    self.scratch.results.push(next);
                    if self.scratch.results.len() > ef {
                        self.scratch.results.pop();
                    }
                }
            }
        }
        let mut output = self.scratch.results.iter().copied().collect::<Vec<_>>();
        output.sort_unstable();
        output
    }

    fn select_neighbors(
        &self,
        _query: &[f32],
        mut candidates: Vec<Candidate>,
        maximum: usize,
    ) -> SmallVec<[u32; 32]> {
        candidates.sort_unstable();
        candidates.dedup_by_key(|candidate| candidate.id);
        let mut selected = SmallVec::<[u32; 32]>::new();
        for candidate in &candidates {
            let occluded = selected.iter().any(|&other| {
                self.metric.rank_eval(
                    &self.nodes[candidate.id as usize].vector,
                    &self.nodes[other as usize].vector,
                ) < candidate.dist
            });
            if !occluded {
                selected.push(candidate.id);
                if selected.len() == maximum {
                    return selected;
                }
            }
        }
        for candidate in candidates {
            if !selected.contains(&candidate.id) {
                selected.push(candidate.id);
                if selected.len() == maximum {
                    break;
                }
            }
        }
        selected
    }

    fn prune_node(&mut self, id: u32, level: u8) {
        let maximum = self.maximum_connections(level);
        if self.nodes[id as usize].connections[level as usize].len() <= maximum {
            return;
        }
        let query = self.nodes[id as usize].vector.clone();
        let candidates = self.nodes[id as usize].connections[level as usize]
            .iter()
            .copied()
            .filter(|candidate| *candidate != id)
            .map(|candidate| Candidate {
                id: candidate,
                dist: self
                    .metric
                    .rank_eval(&query, &self.nodes[candidate as usize].vector),
            })
            .collect();
        self.nodes[id as usize].connections[level as usize] =
            self.select_neighbors(&query, candidates, maximum);
    }
}

impl<M: MetricF32> GraphView for HyperbolicHnswBuilder<M> {
    fn dimension(&self) -> usize {
        self.dimension
    }

    fn node_count(&self) -> usize {
        self.nodes.len()
    }

    fn maximum_level(&self) -> u8 {
        self.maximum_level
    }

    fn entry_point(&self) -> u32 {
        self.entry_point.unwrap_or(0)
    }

    fn node(&self, id: u32) -> Option<NodeRecord> {
        let node = self.nodes.get(id as usize)?;
        Some(NodeRecord {
            stable_id: node.stable_id.get(),
            tag_mask: node.metadata.tag_mask,
            upper_row_start: 0,
            upper_row_count: node.level as u16,
            level: node.level,
            flags: u8::from(node.deleted) * NODE_FLAG_DELETED,
        })
    }

    fn vector(&self, id: u32) -> Option<&[f32]> {
        self.nodes
            .get(id as usize)
            .map(|node| node.vector.as_slice())
    }

    fn base_neighbors(&self, id: u32) -> Option<&[u32]> {
        self.nodes
            .get(id as usize)?
            .connections
            .first()
            .map(SmallVec::as_slice)
    }

    fn upper_neighbors(&self, id: u32, level: u8) -> Option<&[u32]> {
        self.nodes
            .get(id as usize)?
            .connections
            .get(level as usize)
            .map(SmallVec::as_slice)
    }
}

fn deterministic_level(id: StableVectorId, seed: u64, multiplier: f32, maximum_level: u8) -> u8 {
    let random = splitmix64(id.get() ^ seed);
    let unit = (((random >> 11) as f64) + 1.0) * (1.0 / ((1_u64 << 53) as f64 + 1.0));
    ((-unit.ln() * multiplier as f64).floor() as u8).min(maximum_level)
}

#[inline]
fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}
