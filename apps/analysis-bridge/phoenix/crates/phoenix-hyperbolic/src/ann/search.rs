use crate::ann::frozen::{NodeRecord, NODE_FLAG_DELETED};
use crate::{
    Candidate, FilterMode, HyperbolicDiskError, MetricF32, SearchHit, SearchParams, StableVectorId,
};
use std::cmp::Reverse;
use std::collections::BinaryHeap;

pub trait SearchFilter {
    fn accepts(&self, id: StableVectorId, tag_mask: u64) -> bool;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct NoFilter;

impl SearchFilter for NoFilter {
    #[inline]
    fn accepts(&self, _id: StableVectorId, _tag_mask: u64) -> bool {
        true
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TagFilter {
    pub require_any: u64,
    pub exclude_any: u64,
}

impl SearchFilter for TagFilter {
    #[inline]
    fn accepts(&self, _id: StableVectorId, tag_mask: u64) -> bool {
        (self.require_any == 0 || tag_mask & self.require_any != 0)
            && tag_mask & self.exclude_any == 0
    }
}

pub struct SearchScratch {
    query: Vec<f32>,
    visited_epochs: Vec<u32>,
    epoch: u32,
    frontier: BinaryHeap<Reverse<Candidate>>,
    navigation: BinaryHeap<Candidate>,
    accepted: BinaryHeap<Candidate>,
    hits: Vec<SearchHit>,
}

impl Default for SearchScratch {
    fn default() -> Self {
        Self::new()
    }
}

impl SearchScratch {
    pub const fn new() -> Self {
        Self {
            query: Vec::new(),
            visited_epochs: Vec::new(),
            epoch: 0,
            frontier: BinaryHeap::new(),
            navigation: BinaryHeap::new(),
            accepted: BinaryHeap::new(),
            hits: Vec::new(),
        }
    }

    pub fn reserve(&mut self, nodes: usize, dimension: usize, ef_search: usize) {
        if self.visited_epochs.len() < nodes {
            self.visited_epochs.resize(nodes, 0);
        }
        self.query
            .reserve(dimension.saturating_sub(self.query.capacity()));
        self.frontier
            .reserve(ef_search.saturating_sub(self.frontier.capacity()));
        self.navigation
            .reserve(ef_search.saturating_sub(self.navigation.capacity()));
        self.accepted
            .reserve(ef_search.saturating_sub(self.accepted.capacity()));
        self.hits
            .reserve(ef_search.saturating_sub(self.hits.capacity()));
    }

    pub fn hits(&self) -> &[SearchHit] {
        &self.hits
    }

    pub fn allocation_capacities(&self) -> SearchScratchCapacities {
        SearchScratchCapacities {
            query: self.query.capacity(),
            visited: self.visited_epochs.capacity(),
            frontier: self.frontier.capacity(),
            navigation: self.navigation.capacity(),
            accepted: self.accepted.capacity(),
            hits: self.hits.capacity(),
        }
    }

    fn begin(&mut self, nodes: usize, dimension: usize, ef_search: usize) {
        self.frontier.clear();
        self.navigation.clear();
        self.accepted.clear();
        self.hits.clear();
        self.query.clear();
        self.reserve(nodes, dimension, ef_search);
        self.epoch = self.epoch.wrapping_add(1);
        if self.epoch == 0 {
            self.visited_epochs.fill(0);
            self.epoch = 1;
        }
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SearchScratchCapacities {
    pub query: usize,
    pub visited: usize,
    pub frontier: usize,
    pub navigation: usize,
    pub accepted: usize,
    pub hits: usize,
}

pub(crate) trait GraphView {
    fn dimension(&self) -> usize;
    fn node_count(&self) -> usize;
    fn maximum_level(&self) -> u8;
    fn entry_point(&self) -> u32;
    fn node(&self, id: u32) -> Option<NodeRecord>;
    fn vector(&self, id: u32) -> Option<&[f32]>;
    fn base_neighbors(&self, id: u32) -> Option<&[u32]>;
    fn upper_neighbors(&self, id: u32, level: u8) -> Option<&[u32]>;
}

pub(crate) fn search_view<'a, G, M, F>(
    graph: &G,
    metric: &M,
    query: &[f32],
    params: SearchParams,
    filter: &F,
    scratch: &'a mut SearchScratch,
) -> Result<&'a [SearchHit], HyperbolicDiskError>
where
    G: GraphView,
    M: MetricF32,
    F: SearchFilter,
{
    let params = params.validate()?;
    if query.len() != graph.dimension() {
        return Err(HyperbolicDiskError::InvalidSearch(
            "query dimension does not match index",
        ));
    }
    scratch.begin(graph.node_count(), graph.dimension(), params.ef_search);
    if graph.node_count() == 0 {
        return Ok(scratch.hits());
    }
    scratch.query.extend_from_slice(query);
    metric.project_to_ball(&mut scratch.query);
    if scratch.query.iter().any(|value| !value.is_finite()) {
        return Err(HyperbolicDiskError::NonFiniteVector);
    }

    let mut current = live_entry(graph, filter, params.filter_mode)?;
    let mut current_distance = metric.rank_eval(
        &scratch.query,
        graph
            .vector(current)
            .ok_or(HyperbolicDiskError::InvalidTopology(
                "entry vector is missing",
            ))?,
    );
    for level in (1..=graph.maximum_level()).rev() {
        loop {
            let mut changed = false;
            for &neighbor in graph.upper_neighbors(current, level).unwrap_or_default() {
                if !traversable(graph, neighbor, filter, params.filter_mode) {
                    continue;
                }
                let distance = metric.rank_eval(
                    &scratch.query,
                    graph
                        .vector(neighbor)
                        .ok_or(HyperbolicDiskError::InvalidTopology(
                            "upper-layer vector is missing",
                        ))?,
                );
                if distance < current_distance
                    || (distance.to_bits() == current_distance.to_bits() && neighbor < current)
                {
                    current = neighbor;
                    current_distance = distance;
                    changed = true;
                }
            }
            if !changed {
                break;
            }
        }
    }

    scratch.visit(current);
    let first = Candidate {
        id: current,
        dist: current_distance,
    };
    scratch.frontier.push(Reverse(first));
    scratch.navigation.push(first);
    push_if_accepted(graph, filter, first, params.ef_search, scratch);

    while let Some(Reverse(candidate)) = scratch.frontier.pop() {
        if scratch.navigation.len() >= params.ef_search
            && scratch
                .navigation
                .peek()
                .is_some_and(|worst| candidate.dist > worst.dist)
        {
            break;
        }
        for &neighbor in graph.base_neighbors(candidate.id).unwrap_or_default() {
            if !traversable(graph, neighbor, filter, params.filter_mode) || !scratch.visit(neighbor)
            {
                continue;
            }
            let distance = metric.rank_eval(
                &scratch.query,
                graph
                    .vector(neighbor)
                    .ok_or(HyperbolicDiskError::InvalidTopology(
                        "base-layer vector is missing",
                    ))?,
            );
            let next = Candidate {
                id: neighbor,
                dist: distance,
            };
            push_if_accepted(graph, filter, next, params.ef_search, scratch);
            if scratch.navigation.len() < params.ef_search
                || scratch.navigation.peek().is_some_and(|worst| next < *worst)
            {
                scratch.frontier.push(Reverse(next));
                scratch.navigation.push(next);
                if scratch.navigation.len() > params.ef_search {
                    scratch.navigation.pop();
                }
            }
        }
    }

    while let Some(candidate) = scratch.accepted.pop() {
        let node = graph
            .node(candidate.id)
            .ok_or(HyperbolicDiskError::InvalidTopology(
                "accepted node is missing",
            ))?;
        let exact = metric.eval(
            &scratch.query,
            graph
                .vector(candidate.id)
                .ok_or(HyperbolicDiskError::InvalidTopology(
                    "accepted vector is missing",
                ))?,
        );
        scratch.hits.push(SearchHit {
            id: StableVectorId::new(node.stable_id)?,
            dense_id: crate::DenseVectorId(candidate.id),
            distance: exact,
        });
    }
    scratch.hits.sort_by(|left, right| {
        left.distance
            .total_cmp(&right.distance)
            .then_with(|| left.id.cmp(&right.id))
    });
    scratch.hits.truncate(params.k);
    Ok(scratch.hits())
}

fn live_entry<G, F>(graph: &G, filter: &F, mode: FilterMode) -> Result<u32, HyperbolicDiskError>
where
    G: GraphView,
    F: SearchFilter,
{
    let preferred = graph.entry_point();
    if traversable(graph, preferred, filter, mode) {
        return Ok(preferred);
    }
    (0..graph.node_count() as u32)
        .find(|id| traversable(graph, *id, filter, mode))
        .ok_or(HyperbolicDiskError::InvalidSearch(
            "no live node satisfies the strict filter",
        ))
}

#[inline]
fn traversable<G, F>(graph: &G, id: u32, filter: &F, mode: FilterMode) -> bool
where
    G: GraphView,
    F: SearchFilter,
{
    let Some(node) = graph.node(id) else {
        return false;
    };
    if node.flags & NODE_FLAG_DELETED != 0 {
        return false;
    }
    mode == FilterMode::PostFilter
        || StableVectorId::new(node.stable_id)
            .is_ok_and(|stable| filter.accepts(stable, node.tag_mask))
}

fn push_if_accepted<G, F>(
    graph: &G,
    filter: &F,
    candidate: Candidate,
    capacity: usize,
    scratch: &mut SearchScratch,
) where
    G: GraphView,
    F: SearchFilter,
{
    let Some(node) = graph.node(candidate.id) else {
        return;
    };
    if node.flags & NODE_FLAG_DELETED != 0 {
        return;
    }
    if StableVectorId::new(node.stable_id).is_ok_and(|stable| filter.accepts(stable, node.tag_mask))
    {
        scratch.accepted.push(candidate);
        if scratch.accepted.len() > capacity {
            scratch.accepted.pop();
        }
    }
}
