use hashbrown::HashMap;
use std::cmp::Ordering;
use std::collections::BinaryHeap;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct QueueEntry {
    pub mass: u64,
    pub node: u32,
    pub stable_hash: u64,
}

impl Ord for QueueEntry {
    fn cmp(&self, other: &Self) -> Ordering {
        self.mass
            .cmp(&other.mass)
            .then_with(|| other.stable_hash.cmp(&self.stable_hash))
            .then_with(|| other.node.cmp(&self.node))
    }
}

impl PartialOrd for QueueEntry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct Neighbor {
    pub edge: u32,
    pub target: u32,
    pub quality_micros: u32,
    pub target_hash: u64,
    pub edge_hash: u64,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct PathLink {
    pub node: u32,
    pub edge: Option<u32>,
    pub parent: Option<u32>,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct BeamState {
    pub link: u32,
    pub seed_score_micros: u32,
    pub score: i64,
}

pub struct QueryScratch {
    pub(crate) residual: HashMap<u32, u64>,
    pub(crate) reserve: HashMap<u32, u64>,
    pub(crate) queue: BinaryHeap<QueueEntry>,
    pub(crate) neighbors: Vec<Neighbor>,
    pub(crate) seed_hits: Vec<(crate::SeedChannel, crate::SeedHit)>,
    pub(crate) fused_seeds: HashMap<u32, (u32, u32)>,
    pub(crate) seeds: Vec<(u32, u32)>,
    pub(crate) paths: Vec<PathLink>,
    pub(crate) beam: Vec<BeamState>,
    pub(crate) next_beam: Vec<BeamState>,
    pub(crate) candidates: Vec<BeamState>,
}

impl QueryScratch {
    pub fn new(limits: crate::QueryLimits) -> Result<Self, crate::DiscoveryQueryError> {
        let limits = limits.validate()?;
        let vertices = limits.ppr_visited_vertices as usize;
        let states = usize::from(limits.beam_width);
        let expansions = states.saturating_mul(usize::from(limits.fanout_per_state));
        Ok(Self {
            residual: HashMap::with_capacity(vertices),
            reserve: HashMap::with_capacity(vertices),
            queue: BinaryHeap::with_capacity(vertices.min(8_192)),
            neighbors: Vec::with_capacity(usize::from(limits.edge_scan_per_state)),
            seed_hits: Vec::with_capacity(usize::from(limits.seeds) * 2),
            fused_seeds: HashMap::with_capacity(usize::from(limits.seeds) * 2),
            seeds: Vec::with_capacity(usize::from(limits.seeds)),
            paths: Vec::with_capacity(
                usize::from(limits.seeds) + expansions.saturating_mul(limits.hops as usize),
            ),
            beam: Vec::with_capacity(states),
            next_beam: Vec::with_capacity(expansions),
            candidates: Vec::with_capacity(states.saturating_mul(limits.hops as usize)),
        })
    }

    pub(crate) fn clear(&mut self) {
        self.residual.clear();
        self.reserve.clear();
        self.queue.clear();
        self.neighbors.clear();
        self.seed_hits.clear();
        self.fused_seeds.clear();
        self.seeds.clear();
        self.paths.clear();
        self.beam.clear();
        self.next_beam.clear();
        self.candidates.clear();
    }
}
