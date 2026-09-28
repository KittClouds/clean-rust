//! v15 cones: bounded traversal over derived manifold geometry.
//!
//! Cones are query/control primitives, not database objects. They operate on
//! typed IDs, normalized vectors, Hopf anchors/fibers, topology slices, and
//! evidence scores supplied by adapters.

use std::collections::VecDeque;

use rustc_hash::{FxHashMap, FxHashSet};
use serde::{Deserialize, Serialize};
use smallvec::SmallVec;
use thiserror::Error;

use crate::hopf::{phase_alignment_score, FiberKind, HopfAnchor, HopfFiber};

const EPS: f32 = 1e-6;

pub type ConeId = String;
pub type AnchorId = String;
pub type FiberId = String;
pub type SectorId = String;
pub type Phase = f32;

#[derive(Debug, Error)]
pub enum ConeError {
    #[error("missing apex")]
    MissingApex,

    #[error("missing axis")]
    MissingAxis,

    #[error("unknown anchor: {0}")]
    UnknownAnchor(String),

    #[error("unknown fiber: {0}")]
    UnknownFiber(String),

    #[error("invalid aperture: {0}")]
    InvalidAperture(f32),

    #[error("invalid height")]
    InvalidHeight,

    #[error("empty candidate set")]
    EmptyCandidateSet,

    #[error("geometry version mismatch")]
    GeometryVersionMismatch,

    #[error("dimension mismatch: expected {expected}, got {got}")]
    DimensionMismatch { expected: usize, got: usize },
}

pub type ConeResult<T> = Result<T, ConeError>;

#[derive(Clone, Debug, Eq, PartialEq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", tag = "kind", content = "id")]
pub enum ManifoldId {
    Anchor(AnchorId),
    Fiber(FiberId),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", tag = "kind", content = "value")]
pub enum ConeApex {
    Anchor(AnchorId),
    Fiber(FiberId),
    Phase { fiber_id: FiberId, phase: Phase },
    QueryVector(Vec<f32>),
    Multi(Vec<ConeApex>),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", tag = "kind", content = "value")]
pub enum ConeAxis {
    Vector(Vec<f32>),
    AnchorDirection { from: AnchorId, to: AnchorId },
    FiberDirection { from: FiberId, to: FiberId },
    PhaseForward,
    PhaseBackward,
    BridgeToSector(SectorId),
    EvidenceLane,
}

#[derive(Clone, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", tag = "kind", content = "value")]
pub enum ConeLane {
    Anchor,
    Fiber(FiberKind),
    Phase,
    Bridge,
    Evidence,
    Temporal,
    Causal,
    Contradiction,
    Mixed(Vec<ConeLane>),
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Aperture {
    pub cos_threshold: f32,
}

impl Aperture {
    pub fn from_degrees(degrees: f32) -> ConeResult<Self> {
        if !degrees.is_finite() || !(0.0..=180.0).contains(&degrees) {
            return Err(ConeError::InvalidAperture(degrees));
        }
        Ok(Self {
            cos_threshold: degrees.to_radians().cos(),
        })
    }

    pub fn needle() -> Self {
        Self::from_degrees(12.0).expect("valid needle aperture")
    }

    pub fn narrow() -> Self {
        Self::from_degrees(25.0).expect("valid narrow aperture")
    }

    pub fn medium() -> Self {
        Self::from_degrees(40.0).expect("valid medium aperture")
    }

    pub fn wide() -> Self {
        Self::from_degrees(58.0).expect("valid wide aperture")
    }

    pub fn wild() -> Self {
        Self::from_degrees(75.0).expect("valid wild aperture")
    }

    #[inline]
    pub fn contains_alignment(&self, alignment: f32) -> bool {
        alignment >= self.cos_threshold
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", tag = "kind", content = "value")]
pub enum ConeHeight {
    MaxDistance(f32),
    MaxHops(u8),
    MaxCost(f32),
    MaxResults(usize),
    Composite {
        max_hops: u8,
        max_cost: f32,
        max_results: usize,
    },
}

impl ConeHeight {
    pub fn permits(&self, hops: u8, cost: f32, distance: f32) -> bool {
        match *self {
            Self::MaxDistance(max_distance) => distance <= max_distance,
            Self::MaxHops(max_hops) => hops <= max_hops,
            Self::MaxCost(max_cost) => cost <= max_cost,
            Self::MaxResults(_) => true,
            Self::Composite {
                max_hops, max_cost, ..
            } => hops <= max_hops && cost <= max_cost,
        }
    }

    pub fn max_results(&self) -> Option<usize> {
        match *self {
            Self::MaxResults(max_results) => Some(max_results),
            Self::Composite { max_results, .. } => Some(max_results),
            _ => None,
        }
    }

    pub fn max_hops(&self) -> u8 {
        match *self {
            Self::MaxHops(max_hops) => max_hops,
            Self::Composite { max_hops, .. } => max_hops,
            _ => 4,
        }
    }

    pub fn max_cost(&self) -> f32 {
        match *self {
            Self::MaxCost(max_cost) => max_cost,
            Self::Composite { max_cost, .. } => max_cost,
            _ => f32::INFINITY,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ConeProfileId {
    Lookup,
    Context,
    Causal,
    Temporal,
    Synthesis,
    Contradiction,
    Evidence,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeProfile {
    pub profile_id: ConeProfileId,
    pub name: String,
    pub default_aperture: Aperture,
    pub default_height: ConeHeight,
    pub scoring_policy: ConePolicy,
}

impl ConeProfile {
    pub fn default_for(profile_id: ConeProfileId) -> Self {
        match profile_id {
            ConeProfileId::Lookup => Self {
                profile_id,
                name: "lookup_cone".to_owned(),
                default_aperture: Aperture::narrow(),
                default_height: ConeHeight::Composite {
                    max_hops: 2,
                    max_cost: 0.80,
                    max_results: 24,
                },
                scoring_policy: ConePolicy::lookup(),
            },
            ConeProfileId::Context => Self {
                profile_id,
                name: "context_cone".to_owned(),
                default_aperture: Aperture::medium(),
                default_height: ConeHeight::Composite {
                    max_hops: 3,
                    max_cost: 1.20,
                    max_results: 32,
                },
                scoring_policy: ConePolicy::context(),
            },
            ConeProfileId::Causal => Self {
                profile_id,
                name: "causal_cone".to_owned(),
                default_aperture: Aperture::medium(),
                default_height: ConeHeight::Composite {
                    max_hops: 4,
                    max_cost: 1.50,
                    max_results: 32,
                },
                scoring_policy: ConePolicy::causal(),
            },
            ConeProfileId::Temporal => Self {
                profile_id,
                name: "temporal_cone".to_owned(),
                default_aperture: Aperture::narrow(),
                default_height: ConeHeight::Composite {
                    max_hops: 4,
                    max_cost: 1.35,
                    max_results: 32,
                },
                scoring_policy: ConePolicy::temporal(),
            },
            ConeProfileId::Synthesis => Self {
                profile_id,
                name: "synthesis_cone".to_owned(),
                default_aperture: Aperture::wide(),
                default_height: ConeHeight::Composite {
                    max_hops: 5,
                    max_cost: 2.25,
                    max_results: 48,
                },
                scoring_policy: ConePolicy::synthesis(),
            },
            ConeProfileId::Contradiction => Self {
                profile_id,
                name: "contradiction_cone".to_owned(),
                default_aperture: Aperture::medium(),
                default_height: ConeHeight::Composite {
                    max_hops: 4,
                    max_cost: 1.75,
                    max_results: 32,
                },
                scoring_policy: ConePolicy::contradiction(),
            },
            ConeProfileId::Evidence => Self {
                profile_id,
                name: "evidence_cone".to_owned(),
                default_aperture: Aperture::needle(),
                default_height: ConeHeight::Composite {
                    max_hops: 3,
                    max_cost: 0.95,
                    max_results: 24,
                },
                scoring_policy: ConePolicy::evidence(),
            },
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConePolicy {
    pub alignment_weight: f32,
    pub apex_weight: f32,
    pub lane_weight: f32,
    pub fiber_weight: f32,
    pub phase_weight: f32,
    pub edge_weight: f32,
    pub evidence_weight: f32,
    pub traversal_cost_weight: f32,
    pub drift_penalty_weight: f32,
    pub unsupported_jump_penalty: f32,
    pub strict_lane_filter: bool,
    pub require_evidence: bool,
}

impl ConePolicy {
    pub fn lookup() -> Self {
        Self {
            alignment_weight: 0.28,
            apex_weight: 0.26,
            lane_weight: 0.14,
            fiber_weight: 0.12,
            phase_weight: 0.05,
            edge_weight: 0.05,
            evidence_weight: 0.06,
            traversal_cost_weight: 0.12,
            drift_penalty_weight: 0.16,
            unsupported_jump_penalty: 0.10,
            strict_lane_filter: true,
            require_evidence: false,
        }
    }

    pub fn context() -> Self {
        Self {
            alignment_weight: 0.22,
            apex_weight: 0.18,
            lane_weight: 0.20,
            fiber_weight: 0.18,
            phase_weight: 0.10,
            edge_weight: 0.06,
            evidence_weight: 0.06,
            traversal_cost_weight: 0.12,
            drift_penalty_weight: 0.18,
            unsupported_jump_penalty: 0.16,
            strict_lane_filter: true,
            require_evidence: false,
        }
    }

    pub fn causal() -> Self {
        Self {
            phase_weight: 0.18,
            unsupported_jump_penalty: 0.26,
            ..Self::context()
        }
    }

    pub fn temporal() -> Self {
        Self {
            phase_weight: 0.20,
            drift_penalty_weight: 0.22,
            ..Self::context()
        }
    }

    pub fn synthesis() -> Self {
        Self {
            alignment_weight: 0.18,
            apex_weight: 0.12,
            lane_weight: 0.14,
            fiber_weight: 0.14,
            phase_weight: 0.08,
            edge_weight: 0.18,
            evidence_weight: 0.14,
            traversal_cost_weight: 0.12,
            drift_penalty_weight: 0.12,
            unsupported_jump_penalty: 0.30,
            strict_lane_filter: false,
            require_evidence: false,
        }
    }

    pub fn contradiction() -> Self {
        Self {
            evidence_weight: 0.18,
            edge_weight: 0.14,
            unsupported_jump_penalty: 0.28,
            require_evidence: true,
            ..Self::context()
        }
    }

    pub fn evidence() -> Self {
        Self {
            alignment_weight: 0.12,
            apex_weight: 0.10,
            lane_weight: 0.18,
            fiber_weight: 0.10,
            phase_weight: 0.04,
            edge_weight: 0.14,
            evidence_weight: 0.34,
            traversal_cost_weight: 0.10,
            drift_penalty_weight: 0.14,
            unsupported_jump_penalty: 0.22,
            strict_lane_filter: true,
            require_evidence: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeSpec {
    pub id: ConeId,
    pub apex: ConeApex,
    pub axis: ConeAxis,
    pub aperture: Aperture,
    pub height: ConeHeight,
    pub lane: ConeLane,
    pub policy: ConePolicy,
    pub limit: usize,
}

impl ConeSpec {
    pub fn from_profile(
        id: impl Into<ConeId>,
        profile_id: ConeProfileId,
        apex: ConeApex,
        axis: ConeAxis,
        lane: ConeLane,
    ) -> Self {
        let profile = ConeProfile::default_for(profile_id);
        Self {
            id: id.into(),
            apex,
            axis,
            aperture: profile.default_aperture,
            height: profile.default_height.clone(),
            lane,
            policy: profile.scoring_policy,
            limit: profile.default_height.max_results().unwrap_or(32),
        }
    }
}

pub type ConeQuery = ConeSpec;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ConeReason {
    InsideAperture,
    SameApex,
    SameAnchor,
    MatchingFiberKind,
    CompatibleFiberKind,
    MatchingLane,
    PhaseForwardAlignment,
    PhaseBackwardAlignment,
    PhaseAligned,
    StrongFiberEdge,
    EvidenceSupported,
    TraversalWithinHeight,
    UnsupportedJumpPenalty,
    DriftPenalty,
    RequiredEvidenceMissing,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeHit {
    pub target: ManifoldId,
    pub score: f32,
    pub alignment: f32,
    pub distance: f32,
    pub traversal_cost: f32,
    pub lane_match: f32,
    pub fiber_match: f32,
    pub phase_fit: f32,
    pub edge_strength: f32,
    pub evidence_score: f32,
    pub path: Vec<ManifoldId>,
    pub reasons: Vec<ConeReason>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeRejectedCounts {
    pub aperture: usize,
    pub height: usize,
    pub lane: usize,
    pub evidence: usize,
    pub missing_vector: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeTrace {
    pub cone_id: ConeId,
    pub candidate_count: usize,
    pub hit_count: usize,
    pub rejected_counts: ConeRejectedCounts,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeResponse {
    pub hits: Vec<ConeHit>,
    pub trace: Option<ConeTrace>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NeighborRef {
    pub target: ManifoldId,
    pub lane: ConeLane,
    pub edge_strength: f32,
    pub evidence_count: u32,
    pub traversal_cost: f32,
    pub reason: String,
}

pub trait ManifoldRead {
    fn anchor(&self, id: &str) -> Option<&HopfAnchor>;
    fn fiber(&self, id: &str) -> Option<&HopfFiber>;
    fn neighbors(&self, id: &ManifoldId) -> &[NeighborRef];
    fn all_ids(&self) -> Vec<ManifoldId>;

    fn vector(&self, id: &ManifoldId) -> Option<&[f32]> {
        match id {
            ManifoldId::Anchor(anchor_id) => self.anchor(anchor_id).map(|anchor| {
                let vector: &[f32] = &anchor.anchor_vector;
                vector
            }),
            ManifoldId::Fiber(fiber_id) => self.fiber(fiber_id).map(|fiber| {
                let vector: &[f32] = &fiber.context_vector;
                vector
            }),
        }
    }
}

pub trait CandidateSource<M: ManifoldRead> {
    fn candidates(&self, manifold: &M, spec: &ConeSpec, limit: usize) -> Vec<ManifoldId>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct AllCandidates;

impl<M: ManifoldRead> CandidateSource<M> for AllCandidates {
    fn candidates(&self, manifold: &M, _spec: &ConeSpec, limit: usize) -> Vec<ManifoldId> {
        let mut ids = manifold.all_ids();
        ids.sort();
        ids.truncate(limit.max(1));
        ids
    }
}

pub trait EvidenceRead {
    fn evidence_score(&self, id: &ManifoldId) -> f32;
    fn evidence_count(&self, id: &ManifoldId) -> u32;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct NoEvidence;

impl EvidenceRead for NoEvidence {
    fn evidence_score(&self, _id: &ManifoldId) -> f32 {
        0.0
    }

    fn evidence_count(&self, _id: &ManifoldId) -> u32 {
        0
    }
}

pub struct ConeExecutor<'a, M, C, E> {
    manifold: &'a M,
    candidates: &'a C,
    evidence: &'a E,
}

impl<'a, M, C, E> ConeExecutor<'a, M, C, E>
where
    M: ManifoldRead,
    C: CandidateSource<M>,
    E: EvidenceRead,
{
    pub fn new(manifold: &'a M, candidates: &'a C, evidence: &'a E) -> Self {
        Self {
            manifold,
            candidates,
            evidence,
        }
    }

    pub fn run_cone(&self, spec: &ConeSpec) -> ConeResult<ConeResponse> {
        let apex_vector = resolve_apex_vector(self.manifold, &spec.apex)?;
        let axis_vector = resolve_axis_vector(self.manifold, spec, &apex_vector)?;
        let apex_ids = resolve_apex_ids(&spec.apex);
        let candidate_limit = spec.limit.saturating_mul(8).max(spec.limit).max(16);
        let candidate_ids = self
            .candidates
            .candidates(self.manifold, spec, candidate_limit);
        if candidate_ids.is_empty() {
            return Err(ConeError::EmptyCandidateSet);
        }

        let mut rejected = ConeRejectedCounts::default();
        let mut hits = Vec::new();
        for target in candidate_ids.iter() {
            let Some(target_vector) = self.manifold.vector(target) else {
                rejected.missing_vector += 1;
                continue;
            };
            ensure_same_dim(&apex_vector, target_vector)?;
            ensure_same_dim(&axis_vector, target_vector)?;

            let alignment = match spec.axis {
                ConeAxis::Vector(_) => dot(&axis_vector, target_vector).clamp(-1.0, 1.0),
                ConeAxis::PhaseForward | ConeAxis::PhaseBackward => {
                    phase_fit(self.manifold, spec, target).clamp(0.0, 1.0)
                }
                ConeAxis::EvidenceLane => 1.0,
                _ => directional_alignment(&axis_vector, &apex_vector, target_vector)?,
            };
            if !spec.aperture.contains_alignment(alignment) {
                rejected.aperture += 1;
                continue;
            }

            let distance = angular_distance01(&apex_vector, target_vector)?;
            let path = find_path(self.manifold, &apex_ids, target, &spec.height);
            let traversal_cost = path
                .as_ref()
                .map(|path| path.cost)
                .unwrap_or_else(|| unsupported_traversal_cost(distance));
            let hops = path.as_ref().map(|path| path.hops).unwrap_or(u8::MAX);
            if !spec.height.permits(hops, traversal_cost, distance) {
                rejected.height += 1;
                continue;
            }

            let lane_match = lane_match(self.manifold, &spec.lane, target);
            if spec.policy.strict_lane_filter && lane_match <= 0.0 {
                rejected.lane += 1;
                continue;
            }

            let evidence_score = self.evidence.evidence_score(target).clamp(0.0, 1.0);
            if spec.policy.require_evidence && evidence_score <= 0.0 {
                rejected.evidence += 1;
                continue;
            }

            hits.push(score_hit(
                self.manifold,
                self.evidence,
                spec,
                target.clone(),
                alignment,
                distance,
                lane_match,
                path,
                traversal_cost,
                evidence_score,
            )?);
        }

        let limit = spec
            .height
            .max_results()
            .unwrap_or(spec.limit)
            .min(spec.limit.max(1));
        trim_hits_to_limit(&mut hits, limit);
        Ok(ConeResponse {
            trace: Some(ConeTrace {
                cone_id: spec.id.clone(),
                candidate_count: candidate_ids.len(),
                hit_count: hits.len(),
                rejected_counts: rejected,
            }),
            hits,
        })
    }

    pub fn run_op(&self, op: &ConeOp) -> ConeResult<ConeResponse> {
        match op {
            ConeOp::Single(spec) => self.run_cone(spec),
            ConeOp::Union(specs) => self.run_union(specs),
            ConeOp::Intersection(specs) => self.run_intersection(specs),
            ConeOp::Difference { include, exclude } => self.run_difference(include, exclude),
            ConeOp::Cascade(cascade) => self.run_cascade(cascade),
        }
    }

    pub fn run_union(&self, specs: &[ConeSpec]) -> ConeResult<ConeResponse> {
        let mut merged = FxHashMap::<ManifoldId, ConeHit>::default();
        for spec in specs {
            for hit in self.run_cone(spec)?.hits {
                merged
                    .entry(hit.target.clone())
                    .and_modify(|current| {
                        if hit.score > current.score {
                            *current = hit.clone();
                        }
                    })
                    .or_insert(hit);
            }
        }
        let mut hits = merged.into_values().collect::<Vec<_>>();
        hits.sort_by(compare_hits);
        Ok(ConeResponse { hits, trace: None })
    }

    pub fn run_intersection(&self, specs: &[ConeSpec]) -> ConeResult<ConeResponse> {
        if specs.is_empty() {
            return Ok(ConeResponse {
                hits: Vec::new(),
                trace: None,
            });
        }
        let mut counts = FxHashMap::<ManifoldId, (usize, ConeHit)>::default();
        for spec in specs {
            for hit in self.run_cone(spec)?.hits {
                counts
                    .entry(hit.target.clone())
                    .and_modify(|(count, current)| {
                        *count += 1;
                        current.score = current.score.min(hit.score);
                        current.reasons.extend(hit.reasons.clone());
                    })
                    .or_insert((1, hit));
            }
        }
        let mut hits = counts
            .into_iter()
            .filter_map(|(_, (count, hit))| (count == specs.len()).then_some(hit))
            .collect::<Vec<_>>();
        hits.sort_by(compare_hits);
        Ok(ConeResponse { hits, trace: None })
    }

    pub fn run_difference(&self, include: &ConeOp, exclude: &ConeOp) -> ConeResult<ConeResponse> {
        let include_hits = self.run_op(include)?.hits;
        let excluded = self
            .run_op(exclude)?
            .hits
            .into_iter()
            .map(|hit| hit.target)
            .collect::<FxHashSet<_>>();
        let hits = include_hits
            .into_iter()
            .filter(|hit| !excluded.contains(&hit.target))
            .collect();
        Ok(ConeResponse { hits, trace: None })
    }

    pub fn run_cascade(&self, cascade: &ConeCascade) -> ConeResult<ConeResponse> {
        match cascade.merge_policy {
            CascadeMergePolicy::LastStage => cascade
                .stages
                .last()
                .map(|stage| self.run_cone(stage))
                .unwrap_or_else(|| {
                    Ok(ConeResponse {
                        hits: Vec::new(),
                        trace: None,
                    })
                }),
            CascadeMergePolicy::Union => self.run_union(&cascade.stages),
            CascadeMergePolicy::Intersection => self.run_intersection(&cascade.stages),
        }
    }
}

pub trait RunCone {
    fn run_cone(&self, query: ConeQuery) -> ConeResult<ConeResponse>;
}

impl<'a, M, C, E> RunCone for ConeExecutor<'a, M, C, E>
where
    M: ManifoldRead,
    C: CandidateSource<M>,
    E: EvidenceRead,
{
    fn run_cone(&self, query: ConeQuery) -> ConeResult<ConeResponse> {
        ConeExecutor::run_cone(self, &query)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", tag = "kind", content = "value")]
pub enum ConeOp {
    Single(ConeQuery),
    Union(Vec<ConeQuery>),
    Intersection(Vec<ConeQuery>),
    Difference {
        include: Box<ConeOp>,
        exclude: Box<ConeOp>,
    },
    Cascade(ConeCascade),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum CascadeMergePolicy {
    LastStage,
    Union,
    Intersection,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConeCascade {
    pub stages: Vec<ConeQuery>,
    pub merge_policy: CascadeMergePolicy,
}

#[derive(Clone, Debug)]
struct PathInfo {
    path: SmallVec<[ManifoldId; 8]>,
    cost: f32,
    hops: u8,
    edge_strength: f32,
    evidence_count: u32,
}

#[derive(Clone, Debug)]
struct PathSearchNode {
    id: ManifoldId,
    parent: Option<usize>,
    cost: f32,
    hops: u8,
    edge_strength: f32,
    evidence_count: u32,
}

fn score_hit<M: ManifoldRead, E: EvidenceRead>(
    manifold: &M,
    evidence: &E,
    spec: &ConeSpec,
    target: ManifoldId,
    alignment: f32,
    distance: f32,
    lane_match: f32,
    path: Option<PathInfo>,
    traversal_cost: f32,
    evidence_score: f32,
) -> ConeResult<ConeHit> {
    let fiber_match = fiber_match(manifold, &spec.lane, &target);
    let phase_fit = phase_fit(manifold, spec, &target);
    let edge_strength = path
        .as_ref()
        .map(|path| path.edge_strength)
        .unwrap_or_default();
    let edge_evidence = path
        .as_ref()
        .map(|path| evidence_count_score(path.evidence_count))
        .unwrap_or_default();
    let combined_evidence = evidence_score.max(edge_evidence);
    let apex_proximity = 1.0 - distance.clamp(0.0, 1.0);
    let normalized_cost = traversal_cost / (1.0 + traversal_cost);
    let unsupported_jump = path.is_none() as u8 as f32;
    let drift_penalty = (1.0 - lane_match.max(fiber_match)).clamp(0.0, 1.0);
    let raw_score = (spec.policy.alignment_weight * alignment.max(0.0))
        + (spec.policy.apex_weight * apex_proximity)
        + (spec.policy.lane_weight * lane_match)
        + (spec.policy.fiber_weight * fiber_match)
        + (spec.policy.phase_weight * phase_fit)
        + (spec.policy.edge_weight * edge_strength)
        + (spec.policy.evidence_weight * combined_evidence)
        - (spec.policy.traversal_cost_weight * normalized_cost)
        - (spec.policy.drift_penalty_weight * drift_penalty)
        - (spec.policy.unsupported_jump_penalty * unsupported_jump);

    let mut reasons = Vec::new();
    reasons.push(ConeReason::InsideAperture);
    if distance <= EPS {
        reasons.push(ConeReason::SameApex);
    }
    if same_anchor(manifold, &spec.apex, &target) {
        reasons.push(ConeReason::SameAnchor);
    }
    if lane_match > 0.0 {
        reasons.push(ConeReason::MatchingLane);
    }
    if fiber_match >= 1.0 {
        reasons.push(ConeReason::MatchingFiberKind);
    } else if fiber_match > 0.0 {
        reasons.push(ConeReason::CompatibleFiberKind);
    }
    if phase_fit > 0.85 {
        match spec.axis {
            ConeAxis::PhaseForward => reasons.push(ConeReason::PhaseForwardAlignment),
            ConeAxis::PhaseBackward => reasons.push(ConeReason::PhaseBackwardAlignment),
            _ => reasons.push(ConeReason::PhaseAligned),
        }
    }
    if edge_strength > 0.65 {
        reasons.push(ConeReason::StrongFiberEdge);
    }
    if evidence.evidence_count(&target) > 0 || edge_evidence > 0.0 {
        reasons.push(ConeReason::EvidenceSupported);
    }
    if path.is_some() {
        reasons.push(ConeReason::TraversalWithinHeight);
    } else {
        reasons.push(ConeReason::UnsupportedJumpPenalty);
    }
    if drift_penalty > 0.0 {
        reasons.push(ConeReason::DriftPenalty);
    }
    if spec.policy.require_evidence && combined_evidence <= 0.0 {
        reasons.push(ConeReason::RequiredEvidenceMissing);
    }

    Ok(ConeHit {
        target,
        score: raw_score,
        alignment,
        distance,
        traversal_cost,
        lane_match,
        fiber_match,
        phase_fit,
        edge_strength,
        evidence_score: combined_evidence,
        path: path.map(|path| path.path.into_vec()).unwrap_or_default(),
        reasons,
    })
}

fn resolve_apex_vector<M: ManifoldRead>(manifold: &M, apex: &ConeApex) -> ConeResult<Vec<f32>> {
    match apex {
        ConeApex::Anchor(anchor_id) => manifold
            .anchor(anchor_id)
            .map(|anchor| anchor.anchor_vector.clone())
            .ok_or_else(|| ConeError::UnknownAnchor(anchor_id.clone())),
        ConeApex::Fiber(fiber_id) | ConeApex::Phase { fiber_id, .. } => manifold
            .fiber(fiber_id)
            .map(|fiber| fiber.context_vector.clone())
            .ok_or_else(|| ConeError::UnknownFiber(fiber_id.clone())),
        ConeApex::QueryVector(vector) => normalize(vector),
        ConeApex::Multi(apexes) => {
            let mut vectors = Vec::new();
            for apex in apexes {
                vectors.push(resolve_apex_vector(manifold, apex)?);
            }
            normalize(&mean_vector(&vectors)?)
        }
    }
}

fn resolve_axis_vector<M: ManifoldRead>(
    manifold: &M,
    spec: &ConeSpec,
    apex_vector: &[f32],
) -> ConeResult<Vec<f32>> {
    match &spec.axis {
        ConeAxis::Vector(vector) => normalize(vector),
        ConeAxis::AnchorDirection { from, to } => {
            let from = manifold
                .anchor(from)
                .ok_or_else(|| ConeError::UnknownAnchor(from.clone()))?;
            let to = manifold
                .anchor(to)
                .ok_or_else(|| ConeError::UnknownAnchor(to.clone()))?;
            normalize_direction(&from.anchor_vector, &to.anchor_vector)
        }
        ConeAxis::FiberDirection { from, to } => {
            let from = manifold
                .fiber(from)
                .ok_or_else(|| ConeError::UnknownFiber(from.clone()))?;
            let to = manifold
                .fiber(to)
                .ok_or_else(|| ConeError::UnknownFiber(to.clone()))?;
            normalize_direction(&from.context_vector, &to.context_vector)
        }
        ConeAxis::PhaseForward | ConeAxis::PhaseBackward => Ok(apex_vector.to_vec()),
        ConeAxis::BridgeToSector(_) | ConeAxis::EvidenceLane => Ok(apex_vector.to_vec()),
    }
}

fn resolve_apex_ids(apex: &ConeApex) -> Vec<ManifoldId> {
    match apex {
        ConeApex::Anchor(anchor_id) => vec![ManifoldId::Anchor(anchor_id.clone())],
        ConeApex::Fiber(fiber_id) | ConeApex::Phase { fiber_id, .. } => {
            vec![ManifoldId::Fiber(fiber_id.clone())]
        }
        ConeApex::QueryVector(_) => Vec::new(),
        ConeApex::Multi(apexes) => apexes.iter().flat_map(resolve_apex_ids).collect(),
    }
}

fn find_path<M: ManifoldRead>(
    manifold: &M,
    starts: &[ManifoldId],
    target: &ManifoldId,
    height: &ConeHeight,
) -> Option<PathInfo> {
    if starts.is_empty() {
        return None;
    }
    let max_hops = height.max_hops();
    let max_cost = height.max_cost();
    let mut queue = VecDeque::new();
    let mut best_cost = FxHashMap::<ManifoldId, f32>::default();
    let mut arena = Vec::<PathSearchNode>::with_capacity(starts.len().max(1) * 4);

    for start in starts {
        let node_index = arena.len();
        arena.push(PathSearchNode {
            id: start.clone(),
            parent: None,
            cost: 0.0,
            hops: 0,
            edge_strength: 0.0,
            evidence_count: 0,
        });
        queue.push_back(node_index);
        best_cost.insert(start.clone(), 0.0);
    }

    while let Some(node_index) = queue.pop_front() {
        let current_id = arena[node_index].id.clone();
        let current_cost = arena[node_index].cost;
        let current_hops = arena[node_index].hops;
        let current_edge_strength = arena[node_index].edge_strength;
        let current_evidence_count = arena[node_index].evidence_count;
        if &current_id == target {
            return Some(reconstruct_path(&arena, node_index));
        }
        if current_hops >= max_hops {
            continue;
        }
        for neighbor in manifold.neighbors(&current_id) {
            let next_cost = current_cost + neighbor.traversal_cost.max(0.0);
            if next_cost > max_cost {
                continue;
            }
            if best_cost
                .get(&neighbor.target)
                .is_some_and(|seen_cost| *seen_cost <= next_cost)
            {
                continue;
            }
            best_cost.insert(neighbor.target.clone(), next_cost);
            let next_index = arena.len();
            arena.push(PathSearchNode {
                id: neighbor.target.clone(),
                parent: Some(node_index),
                cost: next_cost,
                hops: current_hops.saturating_add(1),
                edge_strength: current_edge_strength.max(neighbor.edge_strength.clamp(0.0, 1.0)),
                evidence_count: current_evidence_count.saturating_add(neighbor.evidence_count),
            });
            queue.push_back(next_index);
        }
    }
    None
}

fn reconstruct_path(arena: &[PathSearchNode], mut index: usize) -> PathInfo {
    let terminal = &arena[index];
    let mut reversed = SmallVec::<[ManifoldId; 8]>::new();
    loop {
        let node = &arena[index];
        reversed.push(node.id.clone());
        let Some(parent) = node.parent else {
            break;
        };
        index = parent;
    }
    reversed.reverse();
    PathInfo {
        path: reversed,
        cost: terminal.cost,
        hops: terminal.hops,
        edge_strength: terminal.edge_strength,
        evidence_count: terminal.evidence_count,
    }
}

fn lane_match<M: ManifoldRead>(manifold: &M, lane: &ConeLane, id: &ManifoldId) -> f32 {
    match lane {
        ConeLane::Anchor => matches!(id, ManifoldId::Anchor(_)) as u8 as f32,
        ConeLane::Fiber(kind) => fiber_kind_score(manifold, id, *kind),
        ConeLane::Phase => matches!(id, ManifoldId::Fiber(_)) as u8 as f32,
        ConeLane::Bridge => matches!(id, ManifoldId::Fiber(_)) as u8 as f32,
        ConeLane::Evidence => match id {
            ManifoldId::Fiber(fiber_id) => manifold
                .fiber(fiber_id)
                .map(|fiber| {
                    (fiber.fiber_kind == FiberKind::Evidence
                        || fiber.fiber_kind == FiberKind::Provenance) as u8
                        as f32
                })
                .unwrap_or_default(),
            ManifoldId::Anchor(_) => 0.0,
        },
        ConeLane::Temporal => fiber_kind_score(manifold, id, FiberKind::Temporal),
        ConeLane::Causal => fiber_kind_score(manifold, id, FiberKind::Causal),
        ConeLane::Contradiction => fiber_kind_score(manifold, id, FiberKind::Contradiction),
        ConeLane::Mixed(lanes) => lanes
            .iter()
            .map(|lane| lane_match(manifold, lane, id))
            .fold(0.0, f32::max),
    }
}

fn fiber_match<M: ManifoldRead>(manifold: &M, lane: &ConeLane, id: &ManifoldId) -> f32 {
    match lane {
        ConeLane::Fiber(kind) => fiber_kind_score(manifold, id, *kind),
        ConeLane::Causal => fiber_kind_score(manifold, id, FiberKind::Causal),
        ConeLane::Temporal => fiber_kind_score(manifold, id, FiberKind::Temporal),
        ConeLane::Evidence => lane_match(manifold, lane, id),
        ConeLane::Mixed(lanes) => lanes
            .iter()
            .map(|lane| fiber_match(manifold, lane, id))
            .fold(0.0, f32::max),
        _ => 0.5,
    }
}

fn fiber_kind_score<M: ManifoldRead>(manifold: &M, id: &ManifoldId, kind: FiberKind) -> f32 {
    let ManifoldId::Fiber(fiber_id) = id else {
        return 0.0;
    };
    manifold
        .fiber(fiber_id)
        .map(|fiber| {
            if fiber.fiber_kind == kind {
                1.0
            } else if fiber.fiber_kind.is_compatible_with(kind) {
                0.65
            } else {
                0.0
            }
        })
        .unwrap_or_default()
}

fn phase_fit<M: ManifoldRead>(manifold: &M, spec: &ConeSpec, target: &ManifoldId) -> f32 {
    let Some(target_phase) = target_phase(manifold, target) else {
        return 0.5;
    };
    let apex_phase = apex_phase(manifold, &spec.apex).unwrap_or(target_phase);
    match spec.axis {
        ConeAxis::PhaseForward => phase_forward_fit(apex_phase, target_phase),
        ConeAxis::PhaseBackward => phase_backward_fit(apex_phase, target_phase),
        _ => phase_alignment_score(apex_phase, target_phase),
    }
}

fn apex_phase<M: ManifoldRead>(manifold: &M, apex: &ConeApex) -> Option<f32> {
    match apex {
        ConeApex::Phase { phase, .. } => Some(phase.rem_euclid(1.0)),
        ConeApex::Fiber(fiber_id) => manifold.fiber(fiber_id).map(|fiber| fiber.phase),
        _ => None,
    }
}

fn target_phase<M: ManifoldRead>(manifold: &M, target: &ManifoldId) -> Option<f32> {
    match target {
        ManifoldId::Fiber(fiber_id) => manifold.fiber(fiber_id).map(|fiber| fiber.phase),
        ManifoldId::Anchor(_) => None,
    }
}

fn phase_forward_fit(from: f32, to: f32) -> f32 {
    let delta = (to - from).rem_euclid(1.0);
    if delta <= EPS {
        1.0
    } else if delta <= 0.5 {
        (1.0 - (delta / 0.5)).clamp(0.0, 1.0)
    } else {
        0.0
    }
}

fn phase_backward_fit(from: f32, to: f32) -> f32 {
    phase_forward_fit(to, from)
}

fn same_anchor<M: ManifoldRead>(manifold: &M, apex: &ConeApex, target: &ManifoldId) -> bool {
    let apex_node = match apex {
        ConeApex::Anchor(anchor_id) => Some(anchor_id.as_str()),
        ConeApex::Fiber(fiber_id) | ConeApex::Phase { fiber_id, .. } => {
            manifold.fiber(fiber_id).map(|fiber| fiber.node_id.as_str())
        }
        _ => None,
    };
    let target_node = match target {
        ManifoldId::Anchor(anchor_id) => Some(anchor_id.as_str()),
        ManifoldId::Fiber(fiber_id) => manifold.fiber(fiber_id).map(|fiber| fiber.node_id.as_str()),
    };
    apex_node.is_some() && apex_node == target_node
}

fn unsupported_traversal_cost(distance: f32) -> f32 {
    1.0 + distance.max(0.0)
}

fn evidence_count_score(count: u32) -> f32 {
    if count == 0 {
        0.0
    } else {
        ((count as f32).ln_1p() / 8.0_f32.ln_1p()).clamp(0.0, 1.0)
    }
}

fn directional_alignment(axis: &[f32], apex: &[f32], candidate: &[f32]) -> ConeResult<f32> {
    ensure_same_dim(axis, apex)?;
    ensure_same_dim(axis, candidate)?;
    let mut diff_norm_sq = 0.0f32;
    let mut axis_dot_diff = 0.0f32;
    for ((axis, apex), candidate) in axis.iter().zip(apex.iter()).zip(candidate.iter()) {
        let diff = candidate - apex;
        diff_norm_sq = diff.mul_add(diff, diff_norm_sq);
        axis_dot_diff = axis.mul_add(diff, axis_dot_diff);
    }
    if diff_norm_sq <= EPS {
        return Ok(dot(axis, candidate).clamp(-1.0, 1.0));
    }
    Ok((axis_dot_diff / diff_norm_sq.sqrt()).clamp(-1.0, 1.0))
}

fn normalize_direction(from: &[f32], to: &[f32]) -> ConeResult<Vec<f32>> {
    ensure_same_dim(from, to)?;
    let diff = to
        .iter()
        .zip(from.iter())
        .map(|(to, from)| to - from)
        .collect::<Vec<_>>();
    normalize(&diff)
}

fn normalize(vector: &[f32]) -> ConeResult<Vec<f32>> {
    if vector.is_empty() {
        return Err(ConeError::MissingAxis);
    }
    let norm_sq = norm_sq(vector);
    if !norm_sq.is_finite() || norm_sq <= EPS {
        let mut fallback = vec![0.0; vector.len()];
        fallback[0] = 1.0;
        return Ok(fallback);
    }
    let inv = norm_sq.sqrt().recip();
    Ok(vector.iter().map(|value| value * inv).collect())
}

fn mean_vector(vectors: &[Vec<f32>]) -> ConeResult<Vec<f32>> {
    let Some(first) = vectors.first() else {
        return Err(ConeError::MissingApex);
    };
    let mut mean = vec![0.0; first.len()];
    for vector in vectors {
        ensure_same_dim(first, vector)?;
        for (slot, value) in mean.iter_mut().zip(vector) {
            *slot += value;
        }
    }
    for slot in &mut mean {
        *slot /= vectors.len() as f32;
    }
    Ok(mean)
}

fn angular_distance01(a: &[f32], b: &[f32]) -> ConeResult<f32> {
    ensure_same_dim(a, b)?;
    let dot = dot(a, b).clamp(-1.0, 1.0);
    Ok(dot.acos() / core::f32::consts::PI)
}

fn norm_sq(vector: &[f32]) -> f32 {
    vector.iter().map(|value| value * value).sum()
}

fn dot(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b.iter()).map(|(a, b)| a * b).sum()
}

fn ensure_same_dim(a: &[f32], b: &[f32]) -> ConeResult<()> {
    if a.len() != b.len() {
        return Err(ConeError::DimensionMismatch {
            expected: a.len(),
            got: b.len(),
        });
    }
    Ok(())
}

fn trim_hits_to_limit(hits: &mut Vec<ConeHit>, limit: usize) {
    if hits.len() > limit {
        hits.select_nth_unstable_by(limit, compare_hits);
        hits.truncate(limit);
    }
    hits.sort_by(compare_hits);
}

fn compare_hits(left: &ConeHit, right: &ConeHit) -> std::cmp::Ordering {
    right
        .score
        .total_cmp(&left.score)
        .then_with(|| left.target.cmp(&right.target))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hopf::{HopfAnchor, HopfFiber};
    use std::collections::{BTreeMap, BTreeSet};

    #[derive(Default)]
    struct TinyManifold {
        anchors: BTreeMap<String, HopfAnchor>,
        fibers: BTreeMap<String, HopfFiber>,
        neighbors: BTreeMap<ManifoldId, Vec<NeighborRef>>,
        evidence: BTreeMap<ManifoldId, (f32, u32)>,
    }

    impl TinyManifold {
        fn insert_anchor(&mut self, anchor: HopfAnchor) {
            self.anchors.insert(anchor.node_id.clone(), anchor);
        }

        fn insert_fiber(&mut self, fiber: HopfFiber) {
            self.fibers.insert(fiber.fiber_id.clone(), fiber);
        }

        fn link(
            &mut self,
            from: ManifoldId,
            to: ManifoldId,
            lane: ConeLane,
            cost: f32,
            strength: f32,
            evidence_count: u32,
        ) {
            self.neighbors.entry(from).or_default().push(NeighborRef {
                target: to,
                lane,
                edge_strength: strength,
                evidence_count,
                traversal_cost: cost,
                reason: "test-edge".to_owned(),
            });
        }

        fn evidence(&mut self, id: ManifoldId, score: f32, count: u32) {
            self.evidence.insert(id, (score, count));
        }
    }

    impl ManifoldRead for TinyManifold {
        fn anchor(&self, id: &str) -> Option<&HopfAnchor> {
            self.anchors.get(id)
        }

        fn fiber(&self, id: &str) -> Option<&HopfFiber> {
            self.fibers.get(id)
        }

        fn neighbors(&self, id: &ManifoldId) -> &[NeighborRef] {
            self.neighbors.get(id).map(Vec::as_slice).unwrap_or(&[])
        }

        fn all_ids(&self) -> Vec<ManifoldId> {
            self.anchors
                .keys()
                .cloned()
                .map(ManifoldId::Anchor)
                .chain(self.fibers.keys().cloned().map(ManifoldId::Fiber))
                .collect()
        }
    }

    impl EvidenceRead for TinyManifold {
        fn evidence_score(&self, id: &ManifoldId) -> f32 {
            self.evidence
                .get(id)
                .map(|(score, _)| *score)
                .unwrap_or(0.0)
        }

        fn evidence_count(&self, id: &ManifoldId) -> u32 {
            self.evidence.get(id).map(|(_, count)| *count).unwrap_or(0)
        }
    }

    fn fixture() -> TinyManifold {
        let mut manifold = TinyManifold::default();
        manifold.insert_anchor(HopfAnchor::new("kai", &[1.0, 0.0, 0.0]).assert_ok());
        manifold.insert_anchor(HopfAnchor::new("eureka", &[0.85, 0.15, 0.0]).assert_ok());
        manifold.insert_anchor(HopfAnchor::new("echo@root", &[0.80, 0.20, 0.0]).assert_ok());
        manifold.insert_anchor(HopfAnchor::new("halcyon", &[0.0, 0.0, 1.0]).assert_ok());

        manifold.insert_fiber(
            HopfFiber::new(
                "kai.causality",
                "kai",
                FiberKind::Causal,
                "causality",
                &[0.0, 1.0, 0.0],
                0.20,
            )
            .assert_ok(),
        );
        manifold.insert_fiber(
            HopfFiber::new(
                "kai.domestic",
                "kai",
                FiberKind::Emotional,
                "domestic",
                &[0.0, 0.0, 1.0],
                0.70,
            )
            .assert_ok(),
        );
        manifold.insert_fiber(
            HopfFiber::new(
                "eureka.causality_witness",
                "eureka",
                FiberKind::Causal,
                "causality witness",
                &[0.0, 0.96, 0.04],
                0.30,
            )
            .assert_ok(),
        );
        manifold.insert_fiber(
            HopfFiber::new(
                "eureka.logs",
                "eureka",
                FiberKind::Evidence,
                "logs",
                &[0.0, 0.94, 0.06],
                0.34,
            )
            .assert_ok(),
        );
        manifold.insert_fiber(
            HopfFiber::new(
                "echo.logs",
                "echo@root",
                FiberKind::Evidence,
                "logs",
                &[0.0, 1.0, 0.0],
                0.26,
            )
            .assert_ok(),
        );
        manifold.insert_fiber(
            HopfFiber::new(
                "operator_claim.authority",
                "operator_claim",
                FiberKind::Identity,
                "authority",
                &[0.0, 0.90, 0.10],
                0.42,
            )
            .assert_ok(),
        );
        manifold.insert_fiber(
            HopfFiber::new(
                "halcyon.politics",
                "halcyon",
                FiberKind::Political,
                "politics",
                &[0.0, 0.0, 1.0],
                0.48,
            )
            .assert_ok(),
        );

        manifold.link(
            ManifoldId::Fiber("echo.logs".to_owned()),
            ManifoldId::Fiber("eureka.causality_witness".to_owned()),
            ConeLane::Bridge,
            0.20,
            0.90,
            4,
        );
        manifold.link(
            ManifoldId::Fiber("eureka.causality_witness".to_owned()),
            ManifoldId::Fiber("kai.causality".to_owned()),
            ConeLane::Causal,
            0.25,
            0.84,
            3,
        );
        manifold.link(
            ManifoldId::Fiber("kai.causality".to_owned()),
            ManifoldId::Fiber("operator_claim.authority".to_owned()),
            ConeLane::Bridge,
            0.25,
            0.78,
            3,
        );
        manifold.link(
            ManifoldId::Fiber("kai.causality".to_owned()),
            ManifoldId::Fiber("kai.domestic".to_owned()),
            ConeLane::Fiber(FiberKind::Emotional),
            0.70,
            0.35,
            0,
        );
        manifold.link(
            ManifoldId::Fiber("kai.causality".to_owned()),
            ManifoldId::Fiber("halcyon.politics".to_owned()),
            ConeLane::Bridge,
            1.40,
            0.15,
            0,
        );

        manifold.evidence(
            ManifoldId::Fiber("eureka.causality_witness".to_owned()),
            0.92,
            4,
        );
        manifold.evidence(ManifoldId::Fiber("kai.causality".to_owned()), 0.85, 3);
        manifold.evidence(
            ManifoldId::Fiber("operator_claim.authority".to_owned()),
            0.78,
            3,
        );
        manifold.evidence(ManifoldId::Fiber("kai.domestic".to_owned()), 0.12, 1);
        manifold
    }

    fn executor<'a>(
        manifold: &'a TinyManifold,
    ) -> ConeExecutor<'a, TinyManifold, AllCandidates, TinyManifold> {
        ConeExecutor::new(manifold, &AllCandidates, manifold)
    }

    #[test]
    fn aperture_includes_aligned_and_excludes_off_axis() {
        let manifold = fixture();
        let mut spec = ConeSpec::from_profile(
            "aperture",
            ConeProfileId::Lookup,
            ConeApex::Fiber("echo.logs".to_owned()),
            ConeAxis::Vector(vec![0.0, 1.0, 0.0]),
            ConeLane::Mixed(vec![ConeLane::Fiber(FiberKind::Causal), ConeLane::Evidence]),
        );
        spec.aperture = Aperture::narrow();
        spec.height = ConeHeight::MaxDistance(1.0);
        let response = executor(&manifold).run_cone(&spec).assert_ok();
        let ids = response
            .hits
            .iter()
            .map(|hit| hit.target.clone())
            .collect::<BTreeSet<_>>();
        assert!(ids.contains(&ManifoldId::Fiber("kai.causality".to_owned())));
        assert!(!ids.contains(&ManifoldId::Fiber("kai.domestic".to_owned())));
    }

    #[test]
    fn height_cost_cuts_off_mushy_bridge() {
        let manifold = fixture();
        let mut spec = ConeSpec::from_profile(
            "height",
            ConeProfileId::Synthesis,
            ConeApex::Fiber("kai.causality".to_owned()),
            ConeAxis::Vector(vec![0.0, 0.0, 1.0]),
            ConeLane::Bridge,
        );
        spec.aperture = Aperture::wild();
        spec.height = ConeHeight::MaxCost(0.80);
        let response = executor(&manifold).run_cone(&spec).assert_ok();
        let ids = response
            .hits
            .iter()
            .map(|hit| hit.target.clone())
            .collect::<BTreeSet<_>>();
        assert!(ids.contains(&ManifoldId::Fiber("kai.domestic".to_owned())));
        assert!(!ids.contains(&ManifoldId::Fiber("halcyon.politics".to_owned())));
    }

    #[test]
    fn fiber_lane_filter_keeps_causality_and_excludes_domestic() {
        let manifold = fixture();
        let spec = ConeSpec::from_profile(
            "fiber",
            ConeProfileId::Context,
            ConeApex::Fiber("echo.logs".to_owned()),
            ConeAxis::FiberDirection {
                from: "echo.logs".to_owned(),
                to: "eureka.causality_witness".to_owned(),
            },
            ConeLane::Fiber(FiberKind::Causal),
        );
        let response = executor(&manifold).run_cone(&spec).assert_ok();
        let ids = response
            .hits
            .iter()
            .map(|hit| hit.target.clone())
            .collect::<BTreeSet<_>>();
        assert!(ids.contains(&ManifoldId::Fiber("eureka.causality_witness".to_owned())));
        assert!(!ids.contains(&ManifoldId::Fiber("kai.domestic".to_owned())));
    }

    #[test]
    fn phase_forward_prefers_after_and_backward_prefers_before() {
        let manifold = fixture();
        let mut forward = ConeSpec::from_profile(
            "phase-forward",
            ConeProfileId::Causal,
            ConeApex::Phase {
                fiber_id: "echo.logs".to_owned(),
                phase: 0.27,
            },
            ConeAxis::PhaseForward,
            ConeLane::Mixed(vec![ConeLane::Causal, ConeLane::Evidence]),
        );
        forward.aperture = Aperture::wild();
        let response = executor(&manifold).run_cone(&forward).assert_ok();
        let top = response.hits.first().expect("phase hit");
        assert_eq!(
            top.target,
            ManifoldId::Fiber("eureka.causality_witness".to_owned())
        );
        assert!(response.hits.iter().any(|hit| hit.target
            == ManifoldId::Fiber("eureka.causality_witness".to_owned())
            && hit.phase_fit > 0.80));

        let mut backward = forward.clone();
        backward.id = "phase-backward".to_owned();
        backward.axis = ConeAxis::PhaseBackward;
        let response = executor(&manifold).run_cone(&backward).assert_ok();
        assert!(response
            .hits
            .iter()
            .any(|hit| hit.target == ManifoldId::Fiber("echo.logs".to_owned())));
    }

    #[test]
    fn bridge_cone_prefers_supported_context_path() {
        let manifold = fixture();
        let mut spec = ConeSpec::from_profile(
            "bridge",
            ConeProfileId::Synthesis,
            ConeApex::Fiber("echo.logs".to_owned()),
            ConeAxis::FiberDirection {
                from: "echo.logs".to_owned(),
                to: "eureka.causality_witness".to_owned(),
            },
            ConeLane::Bridge,
        );
        spec.aperture = Aperture::wide();
        let response = executor(&manifold).run_cone(&spec).assert_ok();
        let top = response.hits.first().expect("bridge hit");
        assert_eq!(
            top.target,
            ManifoldId::Fiber("eureka.causality_witness".to_owned())
        );
        assert!(top.reasons.contains(&ConeReason::StrongFiberEdge));
        assert!(top.reasons.contains(&ConeReason::EvidenceSupported));
    }

    #[test]
    fn cone_union_intersection_and_difference_are_stable() {
        let manifold = fixture();
        let causal = ConeSpec::from_profile(
            "causal",
            ConeProfileId::Context,
            ConeApex::Fiber("echo.logs".to_owned()),
            ConeAxis::Vector(vec![0.0, 1.0, 0.0]),
            ConeLane::Causal,
        );
        let evidence = ConeSpec::from_profile(
            "evidence",
            ConeProfileId::Evidence,
            ConeApex::Fiber("echo.logs".to_owned()),
            ConeAxis::Vector(vec![0.0, 1.0, 0.0]),
            ConeLane::Evidence,
        );
        let executor = executor(&manifold);
        let union = executor
            .run_op(&ConeOp::Union(vec![causal.clone(), evidence.clone()]))
            .assert_ok();
        let intersection = executor
            .run_op(&ConeOp::Intersection(vec![
                causal.clone(),
                evidence.clone(),
            ]))
            .assert_ok();
        let difference = executor
            .run_op(&ConeOp::Difference {
                include: Box::new(ConeOp::Single(causal.clone())),
                exclude: Box::new(ConeOp::Single(evidence.clone())),
            })
            .assert_ok();
        let union_ids = ids(&union);
        let intersection_ids = ids(&intersection);
        let difference_ids = ids(&difference);
        assert!(union_ids.len() >= intersection_ids.len());
        assert!(intersection_ids.is_subset(&union_ids));
        assert!(difference_ids.is_disjoint(&ids(&executor
            .run_op(&ConeOp::Single(evidence))
            .assert_ok())));
    }

    #[test]
    fn evidence_cascade_keeps_supported_context_lane() {
        let manifold = fixture();
        let fiber_stage = ConeSpec::from_profile(
            "stage-fiber",
            ConeProfileId::Context,
            ConeApex::Fiber("echo.logs".to_owned()),
            ConeAxis::Vector(vec![0.0, 1.0, 0.0]),
            ConeLane::Mixed(vec![ConeLane::Causal, ConeLane::Evidence]),
        );
        let evidence_stage = ConeSpec::from_profile(
            "stage-evidence",
            ConeProfileId::Evidence,
            ConeApex::Fiber("echo.logs".to_owned()),
            ConeAxis::EvidenceLane,
            ConeLane::Mixed(vec![ConeLane::Evidence, ConeLane::Causal]),
        );
        let cascade = ConeCascade {
            stages: vec![fiber_stage, evidence_stage],
            merge_policy: CascadeMergePolicy::Intersection,
        };
        let response = executor(&manifold)
            .run_op(&ConeOp::Cascade(cascade))
            .assert_ok();
        let ids = ids(&response);
        assert!(ids.contains(&ManifoldId::Fiber("eureka.causality_witness".to_owned())));
        assert!(!ids.contains(&ManifoldId::Fiber("halcyon.politics".to_owned())));
    }

    fn ids(response: &ConeResponse) -> BTreeSet<ManifoldId> {
        response.hits.iter().map(|hit| hit.target.clone()).collect()
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
