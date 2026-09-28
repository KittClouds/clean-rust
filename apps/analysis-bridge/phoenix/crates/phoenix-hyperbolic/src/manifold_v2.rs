//! Manifold v2: cone fields, chart stitching, and obstruction-aware traversal.
//!
//! v15 cones answer "what is inside this cone?". v2 answers "which local cone
//! fields and charts can this query move through, and where does meaning fail to
//! stitch cleanly?" This module is deliberately storage-agnostic.

use std::collections::{BTreeMap, BTreeSet};

use roaring::RoaringBitmap;
use rustc_hash::{FxHashMap, FxHashSet};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::hopf::FiberKind;
use crate::v15cones::{ConeLane, ConeProfileId, ManifoldId};

#[derive(Debug, Error)]
pub enum ManifoldV2Error {
    #[error("unknown cone field owner: {0:?}")]
    UnknownConeFieldOwner(ManifoldId),

    #[error("unknown chart: {0}")]
    UnknownChart(String),

    #[error("unknown pathlet: {0}")]
    UnknownPathlet(String),

    #[error("empty cone program")]
    EmptyProgram,
}

pub type ManifoldV2Result<T> = Result<T, ManifoldV2Error>;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ConeFieldOwnerKind {
    Anchor,
    Fiber,
    Phase,
    Cell,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeFieldDirection {
    pub target: ManifoldId,
    pub lane: ConeLane,
    pub preferred_profile: ConeProfileId,
    pub alignment: f32,
    pub transition_cost: f32,
    pub support_strength: f32,
    pub reason: String,
}

impl ConeFieldDirection {
    pub fn new(target: ManifoldId, lane: ConeLane, preferred_profile: ConeProfileId) -> Self {
        Self {
            target,
            lane,
            preferred_profile,
            alignment: 1.0,
            transition_cost: 0.25,
            support_strength: 1.0,
            reason: String::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeField {
    pub owner_id: ManifoldId,
    pub owner_kind: ConeFieldOwnerKind,
    pub outgoing_directions: Vec<ConeFieldDirection>,
    pub allowed_lanes: Vec<ConeLane>,
    pub preferred_profiles: Vec<ConeProfileId>,
    pub support_strength: f32,
    pub geometry_version: u64,
}

impl ConeField {
    pub fn new(owner_id: ManifoldId, owner_kind: ConeFieldOwnerKind) -> Self {
        Self {
            owner_id,
            owner_kind,
            outgoing_directions: Vec::new(),
            allowed_lanes: Vec::new(),
            preferred_profiles: Vec::new(),
            support_strength: 1.0,
            geometry_version: 1,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChartBoundaryLink {
    pub target_chart_id: String,
    pub via_fiber_id: String,
    pub lane: ConeLane,
    pub traversal_cost: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Chart {
    pub chart_id: String,
    pub center_anchor: String,
    pub included_fibers: Vec<String>,
    pub local_cells: Vec<String>,
    pub local_metric: String,
    pub valid_lanes: Vec<ConeLane>,
    pub boundary_links: Vec<ChartBoundaryLink>,
    pub geometry_version: u64,
}

impl Chart {
    pub fn new(chart_id: impl Into<String>, center_anchor: impl Into<String>) -> Self {
        Self {
            chart_id: chart_id.into(),
            center_anchor: center_anchor.into(),
            included_fibers: Vec::new(),
            local_cells: Vec::new(),
            local_metric: "hopf-local".to_owned(),
            valid_lanes: Vec::new(),
            boundary_links: Vec::new(),
            geometry_version: 1,
        }
    }

    pub fn contains(&self, id: &ManifoldId) -> bool {
        match id {
            ManifoldId::Anchor(anchor_id) => anchor_id == &self.center_anchor,
            ManifoldId::Fiber(fiber_id) => self.included_fibers.contains(fiber_id),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum StitchKind {
    LogToCausality,
    CausalityStep,
    TemporalStep,
    EvidenceSupport,
    IdentityFacet,
    Bridge,
    Contradiction,
    Generic,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Stitch {
    pub stitch_id: String,
    pub from_chart: String,
    pub to_chart: String,
    pub from_fiber: String,
    pub to_fiber: String,
    pub stitch_kind: StitchKind,
    pub compatibility_score: f32,
    pub evidence_score: f32,
    pub traversal_cost: f32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ObstructionKind {
    Contradiction,
    TemporalMismatch,
    CausalReversal,
    IdentityAmbiguity,
    UnsupportedBridge,
    PhaseMismatch,
    PolarityMismatch,
    ModalityMismatch,
    LaneMismatch,
    EvidenceMissing,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Obstruction {
    pub obstruction_id: String,
    pub chart_a: Option<String>,
    pub chart_b: Option<String>,
    pub fiber_a: Option<String>,
    pub fiber_b: Option<String>,
    pub kind: ObstructionKind,
    pub severity: f32,
    pub explanation: String,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Pathlet {
    pub pathlet_id: String,
    pub start: ManifoldId,
    pub end: ManifoldId,
    pub lane: ConeLane,
    pub nodes: Vec<ManifoldId>,
    pub fibers: Vec<String>,
    pub phases: Vec<f32>,
    pub support_score: f32,
    pub compression_score: f32,
    pub geometry_version: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ConeProgramRankKey {
    Support,
    PhaseAlignment,
    StitchQuality,
    Cost,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", tag = "op", content = "args")]
pub enum ConeProgramOp {
    Seed {
        ids: Vec<ManifoldId>,
    },
    Expand {
        lane: ConeLane,
        max_cost: f32,
        limit: usize,
    },
    FollowField {
        lane: ConeLane,
        max_cost: f32,
        limit: usize,
    },
    Intersect {
        ids: Vec<ManifoldId>,
    },
    Difference {
        ids: Vec<ManifoldId>,
    },
    Stitch {
        required: Vec<ManifoldId>,
        min_compatibility: f32,
        require_evidence: bool,
    },
    UsePathlet {
        pathlet_id: String,
    },
    Ground {
        strict: bool,
    },
    Rerank {
        by: Vec<ConeProgramRankKey>,
    },
    Explain {
        top_k: usize,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeProgram {
    pub program_id: String,
    pub ops: Vec<ConeProgramOp>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StitchedPath {
    pub path_id: String,
    pub nodes: Vec<ManifoldId>,
    pub charts: Vec<String>,
    pub stitches: Vec<String>,
    pub score: f32,
    pub support_score: f32,
    pub stitch_quality: f32,
    pub traversal_cost: f32,
    pub reasons: Vec<String>,
}

impl StitchedPath {
    fn seed(id: ManifoldId, chart: Option<String>) -> Self {
        Self {
            path_id: path_id_from_nodes(&[id.clone()]),
            nodes: vec![id],
            charts: chart.into_iter().collect(),
            stitches: Vec::new(),
            score: 1.0,
            support_score: 0.0,
            stitch_quality: 0.0,
            traversal_cost: 0.0,
            reasons: vec!["seed".to_owned()],
        }
    }

    fn last(&self) -> Option<&ManifoldId> {
        self.nodes.last()
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeProgramTrace {
    pub program_id: String,
    pub active_ids: Vec<ManifoldId>,
    pub paths: Vec<StitchedPath>,
    pub obstructions: Vec<Obstruction>,
    pub explanations: Vec<String>,
}

pub type ManifoldIx = u32;

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ManifoldIdInterner {
    ids: Vec<ManifoldId>,
    lookup: FxHashMap<ManifoldId, ManifoldIx>,
}

impl ManifoldIdInterner {
    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            ids: Vec::with_capacity(capacity),
            lookup: FxHashMap::default(),
        }
    }

    pub fn intern(&mut self, id: ManifoldId) -> ManifoldIx {
        if let Some(existing) = self.lookup.get(&id) {
            return *existing;
        }
        let index = u32::try_from(self.ids.len()).unwrap_or(u32::MAX);
        self.ids.push(id.clone());
        self.lookup.insert(id, index);
        index
    }

    pub fn index_of(&self, id: &ManifoldId) -> Option<ManifoldIx> {
        self.lookup.get(id).copied()
    }

    pub fn id(&self, index: ManifoldIx) -> Option<&ManifoldId> {
        self.ids.get(index as usize)
    }

    pub fn len(&self) -> usize {
        self.ids.len()
    }

    pub fn is_empty(&self) -> bool {
        self.ids.is_empty()
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConeFieldBitmapIndex {
    pub interner: ManifoldIdInterner,
    pub all: RoaringBitmap,
    pub anchors: RoaringBitmap,
    pub fibers: RoaringBitmap,
    pub lane_members: FxHashMap<ConeLane, RoaringBitmap>,
    pub chart_members: FxHashMap<String, RoaringBitmap>,
    pub owner_reachable: FxHashMap<ManifoldIx, RoaringBitmap>,
}

impl ConeFieldBitmapIndex {
    pub fn index_of(&self, id: &ManifoldId) -> Option<ManifoldIx> {
        self.interner.index_of(id)
    }

    pub fn ids_for_chart(&self, chart_id: &str) -> Option<&RoaringBitmap> {
        self.chart_members.get(chart_id)
    }

    pub fn ids_for_lane(&self, lane: &ConeLane) -> RoaringBitmap {
        let mut bitmap = RoaringBitmap::new();
        for (candidate_lane, members) in &self.lane_members {
            if lane_compatible(candidate_lane, lane) {
                bitmap |= members;
            }
        }
        bitmap
    }

    pub fn reachable_from(&self, owner: &ManifoldId) -> RoaringBitmap {
        self.index_of(owner)
            .and_then(|index| self.owner_reachable.get(&index).cloned())
            .unwrap_or_default()
    }

    pub fn resolve_set(&self, bitmap: &RoaringBitmap) -> Vec<ManifoldId> {
        bitmap
            .iter()
            .filter_map(|index| self.interner.id(index).cloned())
            .collect()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeFieldAtlas {
    pub fields: FxHashMap<ManifoldId, ConeField>,
    pub charts: BTreeMap<String, Chart>,
    pub stitches: BTreeMap<String, Stitch>,
    pub pathlets: FxHashMap<String, Pathlet>,
    pub evidence_scores: FxHashMap<ManifoldId, f32>,
    #[serde(default)]
    fiber_chart_index: FxHashMap<String, String>,
    #[serde(default)]
    anchor_chart_index: FxHashMap<String, String>,
    pub geometry_version: u64,
}

impl ConeFieldAtlas {
    pub fn new() -> Self {
        Self {
            geometry_version: 1,
            ..Self::default()
        }
    }

    pub fn insert_field(&mut self, field: ConeField) {
        self.fields.insert(field.owner_id.clone(), field);
    }

    pub fn insert_chart(&mut self, chart: Chart) {
        self.anchor_chart_index
            .insert(chart.center_anchor.clone(), chart.chart_id.clone());
        for fiber_id in &chart.included_fibers {
            self.fiber_chart_index
                .insert(fiber_id.clone(), chart.chart_id.clone());
        }
        self.charts.insert(chart.chart_id.clone(), chart);
    }

    pub fn insert_stitch(&mut self, stitch: Stitch) {
        self.stitches.insert(stitch.stitch_id.clone(), stitch);
    }

    pub fn insert_pathlet(&mut self, pathlet: Pathlet) {
        self.pathlets.insert(pathlet.pathlet_id.clone(), pathlet);
    }

    pub fn set_evidence_score(&mut self, id: ManifoldId, score: f32) {
        self.evidence_scores.insert(id, score.clamp(0.0, 1.0));
    }

    pub fn chart_for(&self, id: &ManifoldId) -> Option<&Chart> {
        let chart_id = match id {
            ManifoldId::Anchor(anchor_id) => self.anchor_chart_index.get(anchor_id),
            ManifoldId::Fiber(fiber_id) => self.fiber_chart_index.get(fiber_id),
        }?;
        self.charts.get(chart_id)
    }

    pub fn bitmap_index(&self) -> ConeFieldBitmapIndex {
        let mut index = ConeFieldBitmapIndex {
            interner: ManifoldIdInterner::with_capacity(self.estimated_id_count()),
            ..ConeFieldBitmapIndex::default()
        };

        for field in self.fields.values() {
            let owner_ix = intern_indexed_id(&mut index, field.owner_id.clone());
            for lane in &field.allowed_lanes {
                insert_lane_member(&mut index.lane_members, lane, owner_ix);
            }
            for direction in &field.outgoing_directions {
                let target_ix = intern_indexed_id(&mut index, direction.target.clone());
                index
                    .owner_reachable
                    .entry(owner_ix)
                    .or_default()
                    .insert(target_ix);
                insert_lane_member(&mut index.lane_members, &direction.lane, target_ix);
            }
        }

        for chart in self.charts.values() {
            let mut members = RoaringBitmap::new();
            let anchor_ix =
                intern_indexed_id(&mut index, ManifoldId::Anchor(chart.center_anchor.clone()));
            members.insert(anchor_ix);
            for fiber_id in &chart.included_fibers {
                let fiber_ix = intern_indexed_id(&mut index, ManifoldId::Fiber(fiber_id.clone()));
                members.insert(fiber_ix);
            }
            index.chart_members.insert(chart.chart_id.clone(), members);
        }

        for pathlet in self.pathlets.values() {
            for node in &pathlet.nodes {
                let node_ix = intern_indexed_id(&mut index, node.clone());
                insert_lane_member(&mut index.lane_members, &pathlet.lane, node_ix);
            }
        }

        for id in self.evidence_scores.keys() {
            let id_ix = intern_indexed_id(&mut index, id.clone());
            insert_lane_member(&mut index.lane_members, &ConeLane::Evidence, id_ix);
        }

        index
    }

    fn estimated_id_count(&self) -> usize {
        self.fields.len()
            + self
                .charts
                .values()
                .map(|chart| chart.included_fibers.len() + 1)
                .sum::<usize>()
            + self
                .fields
                .values()
                .map(|field| field.outgoing_directions.len())
                .sum::<usize>()
            + self.evidence_scores.len()
    }

    pub fn field_candidates(
        &self,
        owner: &ManifoldId,
        lane: &ConeLane,
        max_cost: f32,
    ) -> Vec<&ConeFieldDirection> {
        let Some(field) = self.fields.get(owner) else {
            return Vec::new();
        };
        let mut directions = Vec::with_capacity(field.outgoing_directions.len().min(16));
        directions.extend(
            field
                .outgoing_directions
                .iter()
                .filter(|direction| lane_compatible(&direction.lane, lane))
                .filter(|direction| direction.transition_cost <= max_cost),
        );
        directions.sort_by(|left, right| {
            left.transition_cost
                .total_cmp(&right.transition_cost)
                .then_with(|| right.support_strength.total_cmp(&left.support_strength))
                .then_with(|| left.target.cmp(&right.target))
        });
        directions
    }

    pub fn execute(&self, program: &ConeProgram) -> ManifoldV2Result<ConeProgramTrace> {
        if program.ops.is_empty() {
            return Err(ManifoldV2Error::EmptyProgram);
        }
        let mut state = ExecutionState::new(program.program_id.clone());
        for op in &program.ops {
            match op {
                ConeProgramOp::Seed { ids } => self.seed(&mut state, ids),
                ConeProgramOp::Expand {
                    lane,
                    max_cost,
                    limit,
                }
                | ConeProgramOp::FollowField {
                    lane,
                    max_cost,
                    limit,
                } => {
                    self.follow_field(&mut state, lane, *max_cost, *limit)?;
                }
                ConeProgramOp::Intersect { ids } => state.intersect(ids),
                ConeProgramOp::Difference { ids } => state.difference(ids),
                ConeProgramOp::Stitch {
                    required,
                    min_compatibility,
                    require_evidence,
                } => self.stitch(&mut state, required, *min_compatibility, *require_evidence),
                ConeProgramOp::UsePathlet { pathlet_id } => {
                    self.use_pathlet(&mut state, pathlet_id)?
                }
                ConeProgramOp::Ground { strict } => self.ground(&mut state, *strict),
                ConeProgramOp::Rerank { by } => state.rerank(by),
                ConeProgramOp::Explain { top_k } => state.explain(*top_k),
            }
        }
        Ok(state.into_trace())
    }

    pub fn compile_query(&self, intent: &ConeQueryIntent) -> ConeProgram {
        let mut ops = Vec::new();
        if !intent.seeds.is_empty() {
            ops.push(ConeProgramOp::Seed {
                ids: intent.seeds.clone(),
            });
        }
        ops.push(ConeProgramOp::FollowField {
            lane: intent.lane.clone(),
            max_cost: intent.max_cost,
            limit: intent.limit.max(1),
        });
        if !intent.required.is_empty() {
            ops.push(ConeProgramOp::Stitch {
                required: intent.required.clone(),
                min_compatibility: intent.min_stitch_compatibility,
                require_evidence: intent.require_evidence,
            });
        }
        if intent.require_evidence {
            ops.push(ConeProgramOp::Ground { strict: true });
        }
        ops.push(ConeProgramOp::Rerank {
            by: vec![
                ConeProgramRankKey::Support,
                ConeProgramRankKey::StitchQuality,
                ConeProgramRankKey::Cost,
            ],
        });
        ops.push(ConeProgramOp::Explain {
            top_k: intent.limit.max(1),
        });
        ConeProgram {
            program_id: intent.intent_id.clone(),
            ops,
        }
    }

    fn seed(&self, state: &mut ExecutionState, ids: &[ManifoldId]) {
        state.active.clear();
        state.paths.clear();
        for id in ids {
            state.active.insert(id.clone());
            state.paths.push(StitchedPath::seed(
                id.clone(),
                self.chart_for(id).map(|chart| chart.chart_id.clone()),
            ));
        }
        state.sort_paths();
    }

    fn follow_field(
        &self,
        state: &mut ExecutionState,
        lane: &ConeLane,
        max_cost: f32,
        limit: usize,
    ) -> ManifoldV2Result<()> {
        let current_paths = std::mem::take(&mut state.paths);
        let mut next_paths =
            Vec::with_capacity(current_paths.len().saturating_mul(limit.max(1).min(4)));
        let mut unexpanded_paths = Vec::new();
        for path in current_paths {
            let Some(owner) = path.last().cloned() else {
                continue;
            };
            if !self.fields.contains_key(&owner) {
                state.obstructions.push(Obstruction {
                    obstruction_id: format!("obs:no-field:{}", manifold_id_token(&owner)),
                    chart_a: self.chart_for(&owner).map(|chart| chart.chart_id.clone()),
                    chart_b: None,
                    fiber_a: fiber_id(&owner),
                    fiber_b: None,
                    kind: ObstructionKind::UnsupportedBridge,
                    severity: 0.45,
                    explanation: "No local cone field exists for expansion owner.".to_owned(),
                    evidence_refs: Vec::new(),
                });
                unexpanded_paths.push(path);
                continue;
            }
            let before_len = next_paths.len();
            for direction in self
                .field_candidates(&owner, lane, max_cost)
                .into_iter()
                .take(limit.max(1))
            {
                let mut expanded = path.clone();
                if expanded.nodes.last() != Some(&direction.target) {
                    expanded.nodes.push(direction.target.clone());
                }
                if let Some(chart) = self.chart_for(&direction.target) {
                    if expanded.charts.last() != Some(&chart.chart_id) {
                        expanded.charts.push(chart.chart_id.clone());
                    }
                }
                expanded.traversal_cost += direction.transition_cost.max(0.0);
                expanded.support_score = expanded
                    .support_score
                    .max(direction.support_strength.clamp(0.0, 1.0));
                expanded.score += (direction.alignment.clamp(0.0, 1.0) * 0.30)
                    + (direction.support_strength.clamp(0.0, 1.0) * 0.20)
                    - (direction.transition_cost.max(0.0) * 0.18);
                expanded
                    .reasons
                    .push(format!("follow_field:{:?}", direction.lane));
                expanded.path_id = path_id_from_nodes(&expanded.nodes);
                next_paths.push(expanded);
            }
            if next_paths.len() == before_len {
                unexpanded_paths.push(path);
            }
        }
        if !next_paths.is_empty() {
            state.paths = merge_paths(next_paths);
            state.active = state
                .paths
                .iter()
                .filter_map(|path| path.last().cloned())
                .collect();
            state.sort_paths();
        } else {
            state.paths = unexpanded_paths;
            state.active = state
                .paths
                .iter()
                .filter_map(|path| path.last().cloned())
                .collect();
        }
        Ok(())
    }

    fn stitch(
        &self,
        state: &mut ExecutionState,
        required: &[ManifoldId],
        min_compatibility: f32,
        require_evidence: bool,
    ) {
        let required = required.iter().cloned().collect::<FxHashSet<_>>();
        let current_paths = std::mem::take(&mut state.paths);
        let mut stitched = Vec::with_capacity(current_paths.len().max(1));
        for path in current_paths {
            let Some(ManifoldId::Fiber(from_fiber)) = path.last().cloned() else {
                stitched.push(path);
                continue;
            };
            let mut matched = false;
            for stitch in self.stitches.values() {
                if stitch.from_fiber != from_fiber {
                    continue;
                }
                let target = ManifoldId::Fiber(stitch.to_fiber.clone());
                let target_required = required.is_empty() || required.contains(&target);
                if !target_required {
                    continue;
                }
                if stitch.compatibility_score < min_compatibility {
                    state.obstructions.push(obstruction_from_stitch(
                        stitch,
                        ObstructionKind::LaneMismatch,
                        1.0 - stitch.compatibility_score.clamp(0.0, 1.0),
                        "Stitch compatibility is below the cone-program threshold.",
                    ));
                    continue;
                }
                if require_evidence && stitch.evidence_score <= 0.0 {
                    state.obstructions.push(obstruction_from_stitch(
                        stitch,
                        ObstructionKind::EvidenceMissing,
                        0.75,
                        "Stitch requires evidence but has no support score.",
                    ));
                    continue;
                }
                matched = true;
                let mut next = path.clone();
                next.nodes.push(target);
                if next.charts.last() != Some(&stitch.to_chart) {
                    next.charts.push(stitch.to_chart.clone());
                }
                next.stitches.push(stitch.stitch_id.clone());
                next.traversal_cost += stitch.traversal_cost.max(0.0);
                next.support_score = next
                    .support_score
                    .max(stitch.evidence_score.clamp(0.0, 1.0));
                next.stitch_quality = next
                    .stitch_quality
                    .max(stitch.compatibility_score.clamp(0.0, 1.0));
                next.score += stitch.compatibility_score.clamp(0.0, 1.0) * 0.35
                    + stitch.evidence_score.clamp(0.0, 1.0) * 0.20
                    - stitch.traversal_cost.max(0.0) * 0.14;
                next.reasons
                    .push(format!("stitch:{:?}", stitch.stitch_kind));
                next.path_id = path_id_from_nodes(&next.nodes);
                stitched.push(next);
            }
            if !matched && !required.is_empty() {
                for target in &required {
                    state.obstructions.push(Obstruction {
                        obstruction_id: format!(
                            "obs:unsupported:{}:{}",
                            sanitize_token(&from_fiber),
                            manifold_id_token(target)
                        ),
                        chart_a: self
                            .chart_for(&ManifoldId::Fiber(from_fiber.clone()))
                            .map(|chart| chart.chart_id.clone()),
                        chart_b: self.chart_for(target).map(|chart| chart.chart_id.clone()),
                        fiber_a: Some(from_fiber.clone()),
                        fiber_b: fiber_id(target),
                        kind: ObstructionKind::UnsupportedBridge,
                        severity: 0.70,
                        explanation:
                            "No typed stitch connects the current fiber to the required target."
                                .to_owned(),
                        evidence_refs: Vec::new(),
                    });
                }
                stitched.push(path);
            }
        }
        state.paths = merge_paths(stitched);
        state.active = state
            .paths
            .iter()
            .filter_map(|path| path.last().cloned())
            .collect();
        state.sort_paths();
    }

    fn use_pathlet(&self, state: &mut ExecutionState, pathlet_id: &str) -> ManifoldV2Result<()> {
        let pathlet = self
            .pathlets
            .get(pathlet_id)
            .ok_or_else(|| ManifoldV2Error::UnknownPathlet(pathlet_id.to_owned()))?;
        let mut path = StitchedPath {
            path_id: format!("pathlet:{}", pathlet.pathlet_id),
            nodes: pathlet.nodes.clone(),
            charts: pathlet
                .nodes
                .iter()
                .filter_map(|node| self.chart_for(node).map(|chart| chart.chart_id.clone()))
                .collect(),
            stitches: Vec::new(),
            score: pathlet.support_score + pathlet.compression_score,
            support_score: pathlet.support_score,
            stitch_quality: pathlet.compression_score,
            traversal_cost: 1.0 - pathlet.compression_score.clamp(0.0, 1.0),
            reasons: vec![format!("pathlet:{}", pathlet.pathlet_id)],
        };
        path.charts.dedup();
        state.active.insert(pathlet.end.clone());
        state.paths.push(path);
        state.sort_paths();
        Ok(())
    }

    fn ground(&self, state: &mut ExecutionState, strict: bool) {
        for path in &mut state.paths {
            let evidence = path
                .nodes
                .iter()
                .filter_map(|node| self.evidence_scores.get(node).copied())
                .fold(path.support_score, f32::max)
                .clamp(0.0, 1.0);
            if evidence > 0.0 {
                path.support_score = evidence;
                path.score += evidence * 0.28;
                path.reasons.push("ground:evidence".to_owned());
            } else if strict {
                path.score = f32::NEG_INFINITY;
                path.reasons.push("ground:rejected-unsupported".to_owned());
            } else {
                path.score -= 0.28;
                path.reasons.push("ground:unsupported-penalty".to_owned());
            }
        }
        if strict {
            state.paths.retain(|path| path.score.is_finite());
        }
        state.active = state
            .paths
            .iter()
            .filter_map(|path| path.last().cloned())
            .collect();
        state.sort_paths();
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeQueryIntent {
    pub intent_id: String,
    pub seeds: Vec<ManifoldId>,
    pub required: Vec<ManifoldId>,
    pub lane: ConeLane,
    pub max_cost: f32,
    pub min_stitch_compatibility: f32,
    pub require_evidence: bool,
    pub limit: usize,
}

struct ExecutionState {
    program_id: String,
    active: BTreeSet<ManifoldId>,
    paths: Vec<StitchedPath>,
    obstructions: Vec<Obstruction>,
    explanations: Vec<String>,
}

impl ExecutionState {
    fn new(program_id: String) -> Self {
        Self {
            program_id,
            active: BTreeSet::new(),
            paths: Vec::new(),
            obstructions: Vec::new(),
            explanations: Vec::new(),
        }
    }

    fn intersect(&mut self, ids: &[ManifoldId]) {
        let allowed = ids.iter().cloned().collect::<BTreeSet<_>>();
        self.paths
            .retain(|path| path.last().is_some_and(|id| allowed.contains(id)));
        self.active = self
            .paths
            .iter()
            .filter_map(|path| path.last().cloned())
            .collect();
    }

    fn difference(&mut self, ids: &[ManifoldId]) {
        let excluded = ids.iter().cloned().collect::<BTreeSet<_>>();
        self.paths
            .retain(|path| path.last().is_none_or(|id| !excluded.contains(id)));
        self.active = self
            .paths
            .iter()
            .filter_map(|path| path.last().cloned())
            .collect();
    }

    fn rerank(&mut self, by: &[ConeProgramRankKey]) {
        for path in &mut self.paths {
            let mut score = 0.0;
            for key in by {
                match key {
                    ConeProgramRankKey::Support => score += path.support_score * 0.38,
                    ConeProgramRankKey::PhaseAlignment => score += phase_proxy(path) * 0.16,
                    ConeProgramRankKey::StitchQuality => score += path.stitch_quality * 0.30,
                    ConeProgramRankKey::Cost => score += (1.0 / (1.0 + path.traversal_cost)) * 0.16,
                }
            }
            path.score += score;
        }
        self.sort_paths();
    }

    fn explain(&mut self, top_k: usize) {
        self.explanations = self
            .paths
            .iter()
            .take(top_k.max(1))
            .map(|path| {
                format!(
                    "{} score={:.3} support={:.3} stitches={} reasons={}",
                    path.path_id,
                    path.score,
                    path.support_score,
                    path.stitches.len(),
                    path.reasons.join(" -> ")
                )
            })
            .collect();
    }

    fn sort_paths(&mut self) {
        self.paths.sort_by(|left, right| {
            right
                .score
                .total_cmp(&left.score)
                .then_with(|| left.traversal_cost.total_cmp(&right.traversal_cost))
                .then_with(|| left.path_id.cmp(&right.path_id))
        });
    }

    fn into_trace(mut self) -> ConeProgramTrace {
        self.sort_paths();
        ConeProgramTrace {
            program_id: self.program_id,
            active_ids: self.active.into_iter().collect(),
            paths: self.paths,
            obstructions: self.obstructions,
            explanations: self.explanations,
        }
    }
}

fn obstruction_from_stitch(
    stitch: &Stitch,
    kind: ObstructionKind,
    severity: f32,
    explanation: &str,
) -> Obstruction {
    Obstruction {
        obstruction_id: format!(
            "obs:stitch:{}:{:?}",
            sanitize_token(&stitch.stitch_id),
            kind
        ),
        chart_a: Some(stitch.from_chart.clone()),
        chart_b: Some(stitch.to_chart.clone()),
        fiber_a: Some(stitch.from_fiber.clone()),
        fiber_b: Some(stitch.to_fiber.clone()),
        kind,
        severity: severity.clamp(0.0, 1.0),
        explanation: explanation.to_owned(),
        evidence_refs: Vec::new(),
    }
}

fn merge_paths(paths: Vec<StitchedPath>) -> Vec<StitchedPath> {
    let mut merged = FxHashMap::<String, StitchedPath>::default();
    for path in paths {
        let key = path.path_id.clone();
        if let Some(current) = merged.get_mut(&key) {
            if path.score > current.score {
                *current = path;
            }
        } else {
            merged.insert(key, path);
        }
    }
    merged.into_values().collect()
}

fn intern_indexed_id(index: &mut ConeFieldBitmapIndex, id: ManifoldId) -> ManifoldIx {
    let ix = index.interner.intern(id.clone());
    index.all.insert(ix);
    match id {
        ManifoldId::Anchor(_) => {
            index.anchors.insert(ix);
        }
        ManifoldId::Fiber(_) => {
            index.fibers.insert(ix);
        }
    }
    ix
}

fn insert_lane_member(
    lanes: &mut FxHashMap<ConeLane, RoaringBitmap>,
    lane: &ConeLane,
    index: ManifoldIx,
) {
    match lane {
        ConeLane::Mixed(members) => {
            for member in members {
                insert_lane_member(lanes, member, index);
            }
        }
        _ => {
            lanes.entry(lane.clone()).or_default().insert(index);
        }
    }
}

fn lane_compatible(candidate: &ConeLane, requested: &ConeLane) -> bool {
    if candidate == requested {
        return true;
    }
    match (candidate, requested) {
        (ConeLane::Mixed(lanes), requested) => {
            lanes.iter().any(|lane| lane_compatible(lane, requested))
        }
        (candidate, ConeLane::Mixed(lanes)) => {
            lanes.iter().any(|lane| lane_compatible(candidate, lane))
        }
        (ConeLane::Fiber(left), ConeLane::Fiber(right)) => {
            left == right || left.is_compatible_with(*right)
        }
        (ConeLane::Fiber(kind), ConeLane::Causal) | (ConeLane::Causal, ConeLane::Fiber(kind)) => {
            *kind == FiberKind::Causal || kind.is_compatible_with(FiberKind::Causal)
        }
        (ConeLane::Fiber(kind), ConeLane::Temporal)
        | (ConeLane::Temporal, ConeLane::Fiber(kind)) => {
            *kind == FiberKind::Temporal || kind.is_compatible_with(FiberKind::Temporal)
        }
        (ConeLane::Evidence, ConeLane::Fiber(kind))
        | (ConeLane::Fiber(kind), ConeLane::Evidence) => {
            *kind == FiberKind::Evidence || *kind == FiberKind::Provenance
        }
        (ConeLane::Bridge, ConeLane::Causal) | (ConeLane::Causal, ConeLane::Bridge) => true,
        (ConeLane::Bridge, ConeLane::Evidence) | (ConeLane::Evidence, ConeLane::Bridge) => true,
        _ => false,
    }
}

fn phase_proxy(path: &StitchedPath) -> f32 {
    (1.0 / (1.0 + path.nodes.len().saturating_sub(1) as f32)).clamp(0.0, 1.0)
}

fn fiber_id(id: &ManifoldId) -> Option<String> {
    match id {
        ManifoldId::Fiber(fiber_id) => Some(fiber_id.clone()),
        ManifoldId::Anchor(_) => None,
    }
}

fn path_id_from_nodes(nodes: &[ManifoldId]) -> String {
    nodes
        .iter()
        .map(manifold_id_token)
        .collect::<Vec<_>>()
        .join("->")
}

fn manifold_id_token(id: &ManifoldId) -> String {
    match id {
        ManifoldId::Anchor(id) => format!("anchor:{}", sanitize_token(id)),
        ManifoldId::Fiber(id) => format!("fiber:{}", sanitize_token(id)),
    }
}

fn sanitize_token(value: &str) -> String {
    value
        .chars()
        .map(|ch| if ch.is_ascii_alphanumeric() { ch } else { '-' })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fid(id: &str) -> ManifoldId {
        ManifoldId::Fiber(id.to_owned())
    }

    fn aid(id: &str) -> ManifoldId {
        ManifoldId::Anchor(id.to_owned())
    }

    fn dir(target: ManifoldId, lane: ConeLane, cost: f32, support: f32) -> ConeFieldDirection {
        ConeFieldDirection {
            target,
            lane,
            preferred_profile: ConeProfileId::Context,
            alignment: 0.90,
            transition_cost: cost,
            support_strength: support,
            reason: "fixture".to_owned(),
        }
    }

    fn fixture() -> ConeFieldAtlas {
        let mut atlas = ConeFieldAtlas::new();

        let mut echo_chart = Chart::new("chart.echo.timeline_fault", "echo@root");
        echo_chart.included_fibers = vec!["echo.logs".to_owned(), "echo.failed_packet".to_owned()];
        echo_chart.valid_lanes = vec![ConeLane::Evidence, ConeLane::Causal, ConeLane::Temporal];
        atlas.insert_chart(echo_chart);

        let mut eureka_chart = Chart::new("chart.eureka.causality", "eureka");
        eureka_chart.included_fibers = vec![
            "eureka.causality_witness".to_owned(),
            "eureka.logs".to_owned(),
        ];
        eureka_chart.valid_lanes = vec![ConeLane::Evidence, ConeLane::Causal];
        atlas.insert_chart(eureka_chart);

        let mut kai_chart = Chart::new("chart.kai.storm_core", "kai");
        kai_chart.included_fibers = vec!["kai.storm_core".to_owned(), "kai.domestic".to_owned()];
        kai_chart.valid_lanes = vec![
            ConeLane::Causal,
            ConeLane::Temporal,
            ConeLane::Fiber(FiberKind::Emotional),
        ];
        atlas.insert_chart(kai_chart);

        let mut shroud_chart = Chart::new("chart.shroud.filter", "shroud");
        shroud_chart.included_fibers = vec!["shroud.filter".to_owned()];
        shroud_chart.valid_lanes = vec![ConeLane::Evidence, ConeLane::Bridge];
        atlas.insert_chart(shroud_chart);

        let mut echo_field = ConeField::new(fid("echo.logs"), ConeFieldOwnerKind::Fiber);
        echo_field.allowed_lanes = vec![ConeLane::Evidence, ConeLane::Causal, ConeLane::Bridge];
        echo_field.outgoing_directions = vec![
            dir(
                fid("eureka.causality_witness"),
                ConeLane::Bridge,
                0.20,
                0.92,
            ),
            dir(fid("kai.storm_core"), ConeLane::Causal, 0.58, 0.68),
            dir(fid("shroud.filter"), ConeLane::Bridge, 0.72, 0.0),
            dir(
                fid("kai.domestic"),
                ConeLane::Fiber(FiberKind::Emotional),
                0.32,
                0.12,
            ),
        ];
        atlas.insert_field(echo_field);

        let mut eureka_field =
            ConeField::new(fid("eureka.causality_witness"), ConeFieldOwnerKind::Fiber);
        eureka_field.allowed_lanes = vec![ConeLane::Causal, ConeLane::Evidence];
        eureka_field.outgoing_directions = vec![
            dir(fid("kai.storm_core"), ConeLane::Causal, 0.24, 0.86),
            dir(
                fid("kai.domestic"),
                ConeLane::Fiber(FiberKind::Emotional),
                0.20,
                0.05,
            ),
        ];
        atlas.insert_field(eureka_field);

        let mut kai_field = ConeField::new(fid("kai.storm_core"), ConeFieldOwnerKind::Fiber);
        kai_field.allowed_lanes = vec![ConeLane::Causal, ConeLane::Temporal, ConeLane::Evidence];
        kai_field.outgoing_directions = vec![dir(
            fid("operator_claim.authority"),
            ConeLane::Bridge,
            0.28,
            0.75,
        )];
        atlas.insert_field(kai_field);

        atlas.insert_stitch(Stitch {
            stitch_id: "stitch.echo.eureka.logs_to_cause".to_owned(),
            from_chart: "chart.echo.timeline_fault".to_owned(),
            to_chart: "chart.eureka.causality".to_owned(),
            from_fiber: "echo.logs".to_owned(),
            to_fiber: "eureka.causality_witness".to_owned(),
            stitch_kind: StitchKind::LogToCausality,
            compatibility_score: 0.93,
            evidence_score: 0.88,
            traversal_cost: 0.20,
        });
        atlas.insert_stitch(Stitch {
            stitch_id: "stitch.eureka.kai.causal".to_owned(),
            from_chart: "chart.eureka.causality".to_owned(),
            to_chart: "chart.kai.storm_core".to_owned(),
            from_fiber: "eureka.causality_witness".to_owned(),
            to_fiber: "kai.storm_core".to_owned(),
            stitch_kind: StitchKind::CausalityStep,
            compatibility_score: 0.89,
            evidence_score: 0.82,
            traversal_cost: 0.24,
        });
        atlas.insert_stitch(Stitch {
            stitch_id: "stitch.echo.kai.domestic.invalid".to_owned(),
            from_chart: "chart.echo.timeline_fault".to_owned(),
            to_chart: "chart.kai.storm_core".to_owned(),
            from_fiber: "echo.logs".to_owned(),
            to_fiber: "kai.domestic".to_owned(),
            stitch_kind: StitchKind::Generic,
            compatibility_score: 0.18,
            evidence_score: 0.0,
            traversal_cost: 0.35,
        });
        atlas.insert_stitch(Stitch {
            stitch_id: "stitch.echo.shroud.unsupported".to_owned(),
            from_chart: "chart.echo.timeline_fault".to_owned(),
            to_chart: "chart.shroud.filter".to_owned(),
            from_fiber: "echo.logs".to_owned(),
            to_fiber: "shroud.filter".to_owned(),
            stitch_kind: StitchKind::Bridge,
            compatibility_score: 0.70,
            evidence_score: 0.0,
            traversal_cost: 0.45,
        });

        atlas.insert_pathlet(Pathlet {
            pathlet_id: "pathlet.echo.eureka.kai".to_owned(),
            start: fid("echo.logs"),
            end: fid("kai.storm_core"),
            lane: ConeLane::Causal,
            nodes: vec![
                fid("echo.logs"),
                fid("eureka.causality_witness"),
                fid("kai.storm_core"),
            ],
            fibers: vec![
                "echo.logs".to_owned(),
                "eureka.causality_witness".to_owned(),
                "kai.storm_core".to_owned(),
            ],
            phases: vec![0.24, 0.31, 0.42],
            support_score: 0.84,
            compression_score: 0.91,
            geometry_version: 1,
        });

        atlas.set_evidence_score(fid("eureka.causality_witness"), 0.88);
        atlas.set_evidence_score(fid("kai.storm_core"), 0.83);
        atlas.set_evidence_score(fid("shroud.filter"), 0.0);
        atlas.set_evidence_score(aid("semantic.mush"), 0.0);
        atlas
    }

    #[test]
    fn valid_stitch_preserves_lane_compatibility() {
        let atlas = fixture();
        let stitch = atlas
            .stitches
            .get("stitch.echo.eureka.logs_to_cause")
            .unwrap();
        assert!(stitch.compatibility_score > 0.9);
        assert!(lane_compatible(&ConeLane::Bridge, &ConeLane::Causal));
    }

    #[test]
    fn invalid_stitch_emits_obstruction() {
        let atlas = fixture();
        let program = ConeProgram {
            program_id: "invalid-domestic".to_owned(),
            ops: vec![
                ConeProgramOp::Seed {
                    ids: vec![fid("echo.logs")],
                },
                ConeProgramOp::Stitch {
                    required: vec![fid("kai.domestic")],
                    min_compatibility: 0.70,
                    require_evidence: true,
                },
            ],
        };
        let trace = atlas.execute(&program).assert_ok();
        assert!(trace
            .obstructions
            .iter()
            .any(|obs| obs.kind == ObstructionKind::LaneMismatch));
        assert!(!trace.active_ids.contains(&fid("kai.domestic")));
    }

    #[test]
    fn cone_field_narrowing_reduces_candidates() {
        let atlas = fixture();
        let wide = atlas.field_candidates(&fid("echo.logs"), &ConeLane::Bridge, 1.0);
        let narrow = atlas.field_candidates(&fid("echo.logs"), &ConeLane::Causal, 0.30);
        assert!(wide.len() > narrow.len());
        assert_eq!(narrow[0].target, fid("eureka.causality_witness"));
    }

    #[test]
    fn bitmap_index_supports_chart_lane_and_reachable_set_algebra() {
        let atlas = fixture();
        let index = atlas.bitmap_index();
        let causal = index.ids_for_lane(&ConeLane::Causal);
        let evidence = index.ids_for_lane(&ConeLane::Evidence);
        let echo_chart = index
            .ids_for_chart("chart.echo.timeline_fault")
            .expect("echo chart bitmap");
        let echo_causal = &causal & echo_chart;
        assert!(echo_causal.contains(index.index_of(&fid("echo.logs")).expect("echo.logs ix")));
        assert!(causal.contains(index.index_of(&fid("kai.storm_core")).expect("kai ix")));
        assert!(evidence.contains(
            index
                .index_of(&fid("eureka.causality_witness"))
                .expect("eureka ix")
        ));

        let reachable = index.reachable_from(&fid("echo.logs"));
        assert!(reachable.contains(
            index
                .index_of(&fid("eureka.causality_witness"))
                .expect("eureka ix")
        ));
        assert!(reachable.contains(index.index_of(&fid("shroud.filter")).expect("shroud ix")));

        let supported_context = &reachable & &causal;
        let resolved = index.resolve_set(&supported_context);
        assert!(resolved.contains(&fid("eureka.causality_witness")));
        assert!(resolved.contains(&fid("kai.storm_core")));
        assert!(!resolved.contains(&fid("kai.domestic")));
    }

    #[test]
    fn chart_traversal_is_deterministic() {
        let atlas = fixture();
        let program = ConeProgram {
            program_id: "deterministic".to_owned(),
            ops: vec![
                ConeProgramOp::Seed {
                    ids: vec![fid("echo.logs")],
                },
                ConeProgramOp::FollowField {
                    lane: ConeLane::Bridge,
                    max_cost: 1.0,
                    limit: 8,
                },
                ConeProgramOp::Rerank {
                    by: vec![ConeProgramRankKey::Support, ConeProgramRankKey::Cost],
                },
            ],
        };
        let first = atlas.execute(&program).assert_ok();
        let second = atlas.execute(&program).assert_ok();
        assert_eq!(first.paths, second.paths);
    }

    #[test]
    fn pathlet_expansion_matches_raw_traversal_shape() {
        let atlas = fixture();
        let raw = ConeProgram {
            program_id: "raw".to_owned(),
            ops: vec![
                ConeProgramOp::Seed {
                    ids: vec![fid("echo.logs")],
                },
                ConeProgramOp::Stitch {
                    required: vec![fid("eureka.causality_witness")],
                    min_compatibility: 0.70,
                    require_evidence: true,
                },
                ConeProgramOp::Stitch {
                    required: vec![fid("kai.storm_core")],
                    min_compatibility: 0.70,
                    require_evidence: true,
                },
            ],
        };
        let raw_trace = atlas.execute(&raw).assert_ok();
        let pathlet_trace = atlas
            .execute(&ConeProgram {
                program_id: "pathlet".to_owned(),
                ops: vec![ConeProgramOp::UsePathlet {
                    pathlet_id: "pathlet.echo.eureka.kai".to_owned(),
                }],
            })
            .assert_ok();
        assert_eq!(raw_trace.paths[0].nodes, pathlet_trace.paths[0].nodes);
    }

    #[test]
    fn evidence_grounding_never_increases_unsupported_score() {
        let atlas = fixture();
        let program_before = ConeProgram {
            program_id: "unsupported-before".to_owned(),
            ops: vec![
                ConeProgramOp::Seed {
                    ids: vec![fid("echo.logs")],
                },
                ConeProgramOp::FollowField {
                    lane: ConeLane::Bridge,
                    max_cost: 1.0,
                    limit: 8,
                },
                ConeProgramOp::Difference {
                    ids: vec![fid("eureka.causality_witness")],
                },
            ],
        };
        let before = atlas.execute(&program_before).assert_ok();
        let shroud_before = before
            .paths
            .iter()
            .find(|path| path.last() == Some(&fid("shroud.filter")))
            .unwrap()
            .score;

        let mut grounded = program_before.clone();
        grounded.ops.push(ConeProgramOp::Ground { strict: false });
        let after = atlas.execute(&grounded).assert_ok();
        let shroud_after = after
            .paths
            .iter()
            .find(|path| path.last() == Some(&fid("shroud.filter")))
            .unwrap()
            .score;
        assert!(shroud_after <= shroud_before);
    }

    #[test]
    fn golden_echo_eureka_kai_cone_program_finds_supported_path_and_obstructions() {
        let atlas = fixture();
        let intent = ConeQueryIntent {
            intent_id: "echo-to-kai".to_owned(),
            seeds: vec![fid("echo.logs")],
            required: vec![fid("eureka.causality_witness")],
            lane: ConeLane::Bridge,
            max_cost: 0.8,
            min_stitch_compatibility: 0.70,
            require_evidence: true,
            limit: 8,
        };
        let mut program = atlas.compile_query(&intent);
        program.ops.insert(
            program.ops.len().saturating_sub(3),
            ConeProgramOp::Stitch {
                required: vec![fid("kai.storm_core"), fid("shroud.filter")],
                min_compatibility: 0.70,
                require_evidence: true,
            },
        );
        let trace = atlas.execute(&program).assert_ok();
        let best = trace.paths.first().expect("supported path");
        assert!(best.nodes.contains(&fid("eureka.causality_witness")));
        assert!(best.nodes.contains(&fid("kai.storm_core")));
        assert!(!best.nodes.contains(&fid("kai.domestic")));
        assert!(best.support_score >= 0.83);
        assert!(trace
            .obstructions
            .iter()
            .any(|obs| obs.kind == ObstructionKind::EvidenceMissing
                || obs.kind == ObstructionKind::UnsupportedBridge));
        assert!(!trace.explanations.is_empty());
    }

    trait AssertOk<T> {
        fn assert_ok(self) -> T;
    }

    impl<T, E: core::fmt::Debug> AssertOk<T> for Result<T, E> {
        fn assert_ok(self) -> T {
            match self {
                Ok(value) => value,
                Err(error) => panic!("expected Ok(..), got Err({error:?})"),
            }
        }
    }
}
