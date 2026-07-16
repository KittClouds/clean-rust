//! Hybrid semantic-shell + hyperbolic-interior space.
//!
//! Mental model:
//! - semantic direction lives on the hypersphere
//! - hierarchy depth lives as radius inside the Poincare ball
//! - the unit sphere boundary acts as semantic infinity
//! - the interior carries parent/child depth
//! - hierarchy cones validate whether a proposed child is allowed under a parent
//!
//! This module intentionally does not modify `sphere.rs` or `poincare.rs`.

use core::cmp::Ordering;
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::poincare::{self, PoincareBall};
use crate::MetricF32;

const DEFAULT_EPS: f32 = 1e-6;
const PI: f32 = core::f32::consts::PI;

#[derive(Debug, Error)]
pub enum HybridSpaceError {
    #[error("empty vector")]
    EmptyVector,

    #[error("dimension mismatch: expected {expected}, got {got}")]
    DimensionMismatch { expected: usize, got: usize },

    #[error("invalid curvature: {0}")]
    InvalidCurvature(f32),

    #[error("invalid depth scale: {0}")]
    InvalidDepthScale(f32),

    #[error("invalid depth cap: {0}")]
    InvalidDepthCap(f32),

    #[error("invalid metric weights: semantic={semantic}, hierarchy={hierarchy}")]
    InvalidMetricWeights { semantic: f32, hierarchy: f32 },

    #[error("invalid cone aperture field {field}: {value}")]
    InvalidConeAperture { field: &'static str, value: f32 },

    #[error("invalid cone radial field {field}: {value}")]
    InvalidConeRadialThreshold { field: &'static str, value: f32 },

    #[error("invalid cone weights: semantic={semantic}, hierarchy={hierarchy}")]
    InvalidConeWeights { semantic: f32, hierarchy: f32 },

    #[error("empty Busemann prototype list")]
    EmptyBusemannPrototypes,

    #[error("invalid Busemann config field {field}: {value}")]
    InvalidBusemannConfig { field: &'static str, value: f32 },

    #[error("invalid Busemann top_k: {0}")]
    InvalidBusemannTopK(usize),

    #[error("invalid Busemann weights: commitment={commitment}, radial={radial}")]
    InvalidBusemannWeights { commitment: f32, radial: f32 },

    #[error("Busemann prototype family mismatch: expected {expected:?}, got {got:?}")]
    BusemannPrototypeFamilyMismatch {
        expected: PrototypeFamily,
        got: PrototypeFamily,
    },

    #[error("invalid Busemann prototype {prototype_id}: {reason}")]
    InvalidBusemannPrototype {
        prototype_id: u64,
        reason: &'static str,
    },

    #[error("Poincare point is outside the unit ball after curvature scaling: norm_sq={norm_sq}")]
    BusemannPointOutsideBall { norm_sq: f32 },

    #[error(transparent)]
    Poincare(#[from] poincare::HyperbolicError),
}

pub type HybridSpaceResult<T> = Result<T, HybridSpaceError>;

/// How hierarchy depth should be converted into hyperbolic distance
/// from the origin before being projected into Poincare radius.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub enum DepthMapping {
    /// h = depth_scale * depth
    Linear,

    /// h = depth_scale * ln(1 + depth)
    ///
    /// Better default for graph depths because it gives early levels
    /// meaningful separation while avoiding edge collapse.
    Log1p,

    /// depth is already a normalized value in [0, 1], then mapped
    /// against max_hyperbolic_radius.
    Normalized,
}

/// Which prototype family the Busemann interior is scoring.
///
/// Keep these lens-scoped. Do not run every prototype family at once unless
/// you intentionally want diagnostic soup.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum PrototypeFamily {
    EntityKind,
    RelationFamily,
    EvidenceAuthority,
    GraphStage,
    ConceptDomain,
}

/// Selects what the hyperbolic interior means.
///
/// RadialDepth is the legacy behavior:
/// - radius = hierarchy/depth signal
///
/// BusemannCommitment is the new behavior:
/// - boundary directions = class/prototype ideals
/// - interior point = unresolved candidate / graph artifact
/// - Busemann score = commitment pressure toward a prototype
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub enum InteriorGeometry {
    RadialDepth(DepthMapping),
    BusemannCommitment(BusemannConfig),
}

impl Default for InteriorGeometry {
    fn default() -> Self {
        Self::RadialDepth(DepthMapping::Log1p)
    }
}

/// Configuration for Busemann commitment scoring.
///
/// Convention:
/// - lower raw Busemann score means stronger commitment to that prototype.
/// - margin = second_best_score - best_score.
/// - larger margin means cleaner classification.
/// - entropy near 1.0 means ambiguity.
/// - entropy near 0.0 means concentrated prototype pressure.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct BusemannConfig {
    pub family: PrototypeFamily,

    /// Weight used when converting scores into softmax probabilities.
    /// Higher values make the strongest prototype dominate harder.
    pub commitment_weight: f32,

    /// Optional confidence blend from radial position.
    /// If radius means "evidence/resolution strength", this lets near-boundary
    /// candidates contribute more confidence than near-origin candidates.
    pub radial_weight: f32,

    /// Maximum normalized entropy allowed before the candidate is considered
    /// too ambiguous for promotion.
    ///
    /// Recommended v1: 0.35 - 0.55.
    pub ambiguity_threshold: f32,

    /// Minimum required score gap between best and second-best prototype.
    ///
    /// Recommended v1: 0.20 - 0.75 depending on score scale.
    pub promotion_margin: f32,

    /// Number of prototype scores to keep in the receipt.
    pub top_k: usize,

    /// Numerical guard.
    pub eps: f32,
}

impl Default for BusemannConfig {
    fn default() -> Self {
        Self {
            family: PrototypeFamily::EntityKind,
            commitment_weight: 1.0,
            radial_weight: 0.25,
            ambiguity_threshold: 0.45,
            promotion_margin: 0.35,
            top_k: 4,
            eps: DEFAULT_EPS,
        }
    }
}

/// Boundary prototype for a Busemann family.
///
/// `direction` should be in the same dimensionality as the interior point.
/// It does not have to be perfectly normalized; scoring normalizes it.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BusemannPrototype {
    pub prototype_id: u64,
    pub family: PrototypeFamily,
    pub direction: Vec<f32>,
}

/// One prototype score in a Busemann signature.
///
/// Lower `score` is stronger.
/// Higher `probability` is stronger after softmax conversion.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BusemannPrototypeScore {
    pub prototype_id: u64,
    pub family: PrototypeFamily,
    pub score: f32,
    pub probability: f32,
}

/// Diagnostic receipt for one candidate/node in the Busemann interior.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BusemannSignature {
    pub family: PrototypeFamily,

    pub top_prototype_id: u64,
    pub top_score: f32,
    pub top_probability: f32,

    pub second_prototype_id: Option<u64>,
    pub second_score: Option<f32>,
    pub second_probability: Option<f32>,

    /// second_score - top_score.
    /// Larger means cleaner prototype commitment.
    pub margin: f32,

    /// Normalized softmax entropy in [0, 1].
    /// Higher means more ambiguous.
    pub entropy: f32,

    /// Currently equal to entropy. Kept separate so UI/postprocess can evolve
    /// without changing the receipt shape.
    pub ambiguity_score: f32,

    /// Blended confidence from margin and optional radial strength.
    pub classification_confidence: f32,

    /// True when margin and entropy pass the configured thresholds.
    /// This is only a geometry/staging signal. Do not mutate graph truth here.
    pub promotion_ready: bool,

    pub radial_strength: f32,

    pub top_k_scores: Vec<BusemannPrototypeScore>,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct HybridSpaceConfig {
    /// Positive curvature parameter c.
    /// Hyperbolic curvature is -c.
    pub curvature: f32,

    /// Numerical guard.
    pub eps: f32,

    /// Converts graph depth into hyperbolic radial distance.
    pub depth_scale: f32,

    /// Maximum hyperbolic radial distance from origin.
    ///
    /// This is the practical "conceptual infinity" cap. The Poincare ball
    /// is mathematically infinite at the boundary, but real machines need
    /// an epsilon wall.
    pub max_hyperbolic_radius: f32,

    /// Minimum hyperbolic radius for non-root nodes.
    ///
    /// Keeps shallow categories from all collapsing into the origin.
    pub min_non_root_hyperbolic_radius: f32,

    pub depth_mapping: DepthMapping,

    /// Meaning of the Poincare/interior component.
    ///
    /// Defaults to legacy radial-depth behavior for serde/backward compatibility.
    #[serde(default)]
    pub interior_geometry: InteriorGeometry,
}

impl Default for HybridSpaceConfig {
    fn default() -> Self {
        Self {
            curvature: 1.0,
            eps: DEFAULT_EPS,
            depth_scale: 1.0,
            max_hyperbolic_radius: 12.0,
            min_non_root_hyperbolic_radius: 0.15,
            depth_mapping: DepthMapping::Log1p,
            interior_geometry: InteriorGeometry::RadialDepth(DepthMapping::Log1p),
        }
    }
}

impl HybridSpaceConfig {
    pub fn validate(self) -> HybridSpaceResult<Self> {
        if !self.curvature.is_finite() || self.curvature <= 0.0 {
            return Err(HybridSpaceError::InvalidCurvature(self.curvature));
        }
        if !self.depth_scale.is_finite() || self.depth_scale <= 0.0 {
            return Err(HybridSpaceError::InvalidDepthScale(self.depth_scale));
        }
        if !self.max_hyperbolic_radius.is_finite() || self.max_hyperbolic_radius <= 0.0 {
            return Err(HybridSpaceError::InvalidDepthCap(
                self.max_hyperbolic_radius,
            ));
        }
        Ok(self)
    }

    #[inline]
    pub fn max_poincare_radius(&self) -> f32 {
        (1.0 / self.curvature.sqrt()) - self.eps
    }

    #[inline]
    pub fn poincare_ball(&self) -> HybridSpaceResult<PoincareBall> {
        Ok(PoincareBall::with_eps(self.curvature, self.eps)?)
    }

    /// Convert graph depth into hyperbolic distance from the origin.
    #[inline]
    pub fn depth_to_hyperbolic_radius(&self, depth: f32) -> f32 {
        let safe_depth = depth.max(0.0);

        let raw = match self.depth_mapping {
            DepthMapping::Linear => self.depth_scale * safe_depth,
            DepthMapping::Log1p => self.depth_scale * safe_depth.ln_1p(),
            DepthMapping::Normalized => self.max_hyperbolic_radius * safe_depth.clamp(0.0, 1.0),
        };

        let with_floor = if safe_depth > 0.0 {
            raw.max(self.min_non_root_hyperbolic_radius)
        } else {
            0.0
        };

        with_floor.min(self.max_hyperbolic_radius)
    }

    /// Convert hyperbolic radial distance to Euclidean Poincare radius.
    ///
    /// For curvature c:
    /// r = tanh(sqrt(c) * h / 2) / sqrt(c)
    #[inline]
    pub fn hyperbolic_radius_to_poincare_radius(&self, h: f32) -> f32 {
        let sqrt_c = self.curvature.sqrt();
        let radius = ((sqrt_c * h) * 0.5).tanh() / sqrt_c;
        radius.min(self.max_poincare_radius()).max(0.0)
    }

    /// Convert Euclidean Poincare radius back to hyperbolic radial distance.
    #[inline]
    pub fn poincare_radius_to_hyperbolic_radius(&self, r: f32) -> f32 {
        let sqrt_c = self.curvature.sqrt();
        let clamped = (sqrt_c * r.max(0.0)).min(1.0 - self.eps);
        (2.0 / sqrt_c) * clamped.atanh()
    }

    #[inline]
    pub fn depth_to_poincare_radius(&self, depth: f32) -> f32 {
        let h = self.depth_to_hyperbolic_radius(depth);
        self.hyperbolic_radius_to_poincare_radius(h)
    }
}

/// A point in the Phoenix product manifold.
///
/// `semantic_direction` is unit-normalized and lives on the hypersphere.
/// `poincare` lives inside the open Poincare ball.
/// `depth` is graph-derived hierarchy depth, not embedding magnitude.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct HybridPoint {
    pub semantic_direction: Vec<f32>,
    pub poincare: Vec<f32>,
    pub depth: f32,
    pub hyperbolic_radius: f32,
    pub poincare_radius: f32,
}

impl HybridPoint {
    pub fn from_embedding_and_depth(
        embedding: &[f32],
        depth: f32,
        config: HybridSpaceConfig,
    ) -> HybridSpaceResult<Self> {
        let config = config.validate()?;

        let semantic_direction = normalize_or_north_pole(embedding)?;
        let hyperbolic_radius = config.depth_to_hyperbolic_radius(depth);
        let poincare_radius = config.hyperbolic_radius_to_poincare_radius(hyperbolic_radius);

        let poincare = semantic_direction
            .iter()
            .map(|v| v * poincare_radius)
            .collect::<Vec<_>>();

        Ok(Self {
            semantic_direction,
            poincare,
            depth: depth.max(0.0),
            hyperbolic_radius,
            poincare_radius,
        })
    }

    /// Build a hybrid point from an existing Poincare-interior coordinate.
    ///
    /// The semantic shell direction is recovered by radial projection toward the
    /// hypersphere boundary. This is the bridge used after Möbius/exp-map updates
    /// move the point inside the hyperball.
    pub fn from_poincare_interior(
        poincare_interior: &[f32],
        depth: f32,
        config: HybridSpaceConfig,
    ) -> HybridSpaceResult<Self> {
        let config = config.validate()?;
        let ball = config.poincare_ball()?;
        let mut poincare = poincare_interior.to_vec();
        ball.project(&mut poincare)?;

        let poincare_radius = poincare::norm(&poincare);
        let hyperbolic_radius = config.poincare_radius_to_hyperbolic_radius(poincare_radius);
        let semantic_direction = if poincare_radius <= DEFAULT_EPS {
            normalize_or_north_pole(&poincare)?
        } else {
            poincare
                .iter()
                .map(|value| value / poincare_radius)
                .collect()
        };

        Ok(Self {
            semantic_direction,
            poincare,
            depth: depth.max(0.0),
            hyperbolic_radius,
            poincare_radius,
        })
    }

    pub fn root(dim: usize) -> HybridSpaceResult<Self> {
        if dim == 0 {
            return Err(HybridSpaceError::EmptyVector);
        }

        let mut semantic_direction = vec![0.0; dim];
        semantic_direction[0] = 1.0;

        Ok(Self {
            semantic_direction,
            poincare: vec![0.0; dim],
            depth: 0.0,
            hyperbolic_radius: 0.0,
            poincare_radius: 0.0,
        })
    }

    #[inline]
    pub fn dim(&self) -> usize {
        self.semantic_direction.len()
    }

    pub fn project_interior(&mut self, config: HybridSpaceConfig) -> HybridSpaceResult<()> {
        let projected = Self::from_poincare_interior(&self.poincare, self.depth, config)?;
        *self = projected;
        Ok(())
    }
}

/// Metric over already-built hybrid Poincare vectors.
///
/// This is useful for indexing the hierarchy interior with your existing
/// ANN machinery. Insert `HybridPoint::poincare`.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct HybridInteriorMetric {
    pub curvature: f32,
    pub eps: f32,
}

impl Default for HybridInteriorMetric {
    fn default() -> Self {
        Self {
            curvature: 1.0,
            eps: DEFAULT_EPS,
        }
    }
}

impl MetricF32 for HybridInteriorMetric {
    #[inline]
    fn eval(&self, a: &[f32], b: &[f32]) -> f32 {
        poincare::poincare_distance(a, b, self.curvature)
    }

    #[inline]
    fn rank_eval(&self, a: &[f32], b: &[f32]) -> f32 {
        self.eval(a, b)
    }

    #[inline]
    fn project_to_ball(&self, vector: &mut [f32]) {
        poincare::project_to_ball_inplace(vector, self.curvature, self.eps);
    }
}

/// A blended metric for comparing full hybrid points outside ANN traversal.
///
/// This should be used for reranking, diagnostics, validation, and experiments.
/// For raw HNSW traversal, prefer indexing either:
/// - semantic_direction with SphereMetric
/// - poincare with HybridInteriorMetric
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct HybridPointMetric {
    pub semantic_weight: f32,
    pub hierarchy_weight: f32,
    pub curvature: f32,
}

impl Default for HybridPointMetric {
    fn default() -> Self {
        Self {
            semantic_weight: 0.35,
            hierarchy_weight: 0.65,
            curvature: 1.0,
        }
    }
}

impl HybridPointMetric {
    pub fn validate(self) -> HybridSpaceResult<Self> {
        if !self.semantic_weight.is_finite()
            || !self.hierarchy_weight.is_finite()
            || self.semantic_weight < 0.0
            || self.hierarchy_weight < 0.0
            || self.semantic_weight + self.hierarchy_weight <= DEFAULT_EPS
        {
            return Err(HybridSpaceError::InvalidMetricWeights {
                semantic: self.semantic_weight,
                hierarchy: self.hierarchy_weight,
            });
        }

        if !self.curvature.is_finite() || self.curvature <= 0.0 {
            return Err(HybridSpaceError::InvalidCurvature(self.curvature));
        }

        Ok(self)
    }

    pub fn eval_points(&self, a: &HybridPoint, b: &HybridPoint) -> HybridSpaceResult<f32> {
        let metric = self.validate()?;

        if a.dim() != b.dim() {
            return Err(HybridSpaceError::DimensionMismatch {
                expected: a.dim(),
                got: b.dim(),
            });
        }

        let semantic = angular_rank_score(&a.semantic_direction, &b.semantic_direction)?;
        let hierarchy = poincare::poincare_distance(&a.poincare, &b.poincare, metric.curvature);

        let total = metric.semantic_weight + metric.hierarchy_weight;
        let semantic_weight = metric.semantic_weight / total;
        let hierarchy_weight = metric.hierarchy_weight / total;

        Ok((semantic_weight * semantic) + (hierarchy_weight * hierarchy))
    }
}

/// Broad hierarchy lane. This is useful for metrics, logging, and UI labels.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum HierarchyLane {
    Type,
    Abstraction,
    Structure,
    Evidence,
    Causal,
    Temporal,
    Project,
    Schema,
    State,
    Provenance,
    Social,
    Topic,
    Custom,
}

/// Relation-aware hierarchy cone type.
///
/// One cone engine handles all of these, but each relation kind gets a different
/// default profile because "belongs under" does not mean the same thing for
/// taxonomy, documents, evidence, causality, and project structure.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum HierarchyRelationKind {
    /// Strict parent type -> child instance/type relation.
    TypeHierarchy,

    /// Entity -> entity type relation, usually stricter than general abstraction.
    EntityType,

    /// General concept -> more specific concept.
    Abstraction,

    /// Biological/mythic/product taxonomies and clean is-a trees/DAGs.
    Taxonomy,

    /// Whole -> part containment.
    PartWhole,

    /// Book/doc/chapter/section/paragraph/span containment.
    DocumentContainment,

    /// Claim -> supporting evidence chunk/span/source relation.
    EvidenceSupport,

    /// Cause/precondition -> effect/outcome dependency.
    CausalDependency,

    /// Era/timeline/event/state temporal nesting.
    TemporalContainment,

    /// Ordered event chain relation.
    EventSequence,

    /// Project -> task/subtask/milestone relation.
    ProjectTask,

    /// Schema -> field/relation/index/constraint containment.
    SchemaContainment,

    /// Prior state -> next state, or state -> state facet relation.
    StateTransition,

    /// Original -> variant/fork/derived version.
    VersionLineage,

    /// Source/session/document -> extracted claim/relation/entity provenance scope.
    ProvenanceScope,

    /// Owner/controller -> owned/controlled object relation.
    Ownership,

    /// Group/org/circle -> member relation.
    Membership,

    /// Topic -> subtopic or loose topical branch.
    TopicCluster,

    /// Premise/claim -> entailed conclusion or narrower claim.
    ClaimEntailment,

    /// Modality/scope -> observed/reported/inferred/desired/planned/conditional facet.
    ModalityScope,

    /// Escape hatch for user-defined hierarchy profiles.
    Custom,
}

impl HierarchyRelationKind {
    #[inline]
    pub fn lane(self) -> HierarchyLane {
        match self {
            Self::TypeHierarchy | Self::EntityType | Self::Taxonomy => HierarchyLane::Type,
            Self::Abstraction | Self::ClaimEntailment => HierarchyLane::Abstraction,
            Self::PartWhole | Self::DocumentContainment => HierarchyLane::Structure,
            Self::EvidenceSupport => HierarchyLane::Evidence,
            Self::CausalDependency => HierarchyLane::Causal,
            Self::TemporalContainment | Self::EventSequence => HierarchyLane::Temporal,
            Self::ProjectTask => HierarchyLane::Project,
            Self::SchemaContainment => HierarchyLane::Schema,
            Self::StateTransition | Self::ModalityScope => HierarchyLane::State,
            Self::VersionLineage | Self::ProvenanceScope => HierarchyLane::Provenance,
            Self::Ownership | Self::Membership => HierarchyLane::Social,
            Self::TopicCluster => HierarchyLane::Topic,
            Self::Custom => HierarchyLane::Custom,
        }
    }

    pub fn default_profile(self) -> ConeProfile {
        match self {
            Self::TypeHierarchy => ConeProfile::strict(self, 0.55, 0.16, 0.62, 0.28),
            Self::EntityType => ConeProfile::strict(self, 0.48, 0.14, 0.56, 0.32),
            Self::Taxonomy => ConeProfile::strict(self, 0.60, 0.18, 0.70, 0.26),
            Self::Abstraction => ConeProfile::balanced(self, 0.75, 0.22, 0.86, 0.20),
            Self::ClaimEntailment => ConeProfile::balanced(self, 0.82, 0.24, 0.95, 0.18),
            Self::PartWhole => ConeProfile::balanced(self, 0.95, 0.28, 1.10, 0.14),
            Self::DocumentContainment => ConeProfile::structure_heavy(self, 1.80, 0.72, 1.95, 0.03),
            Self::EvidenceSupport => ConeProfile::evidence_heavy(self, 1.35, 0.55, 1.65, 0.02),
            Self::CausalDependency => ConeProfile::causal_or_temporal(self, 1.20, 0.42, 1.55, 0.04),
            Self::TemporalContainment => {
                ConeProfile::causal_or_temporal(self, 1.05, 0.38, 1.35, 0.05)
            }
            Self::EventSequence => ConeProfile::causal_or_temporal(self, 1.10, 0.40, 1.45, 0.04),
            Self::ProjectTask => ConeProfile::balanced(self, 1.05, 0.35, 1.25, 0.08),
            Self::SchemaContainment => ConeProfile::strict(self, 0.72, 0.20, 0.84, 0.18),
            Self::StateTransition => ConeProfile::causal_or_temporal(self, 1.15, 0.40, 1.50, 0.04),
            Self::VersionLineage => ConeProfile::balanced(self, 0.92, 0.30, 1.15, 0.10),
            Self::ProvenanceScope => ConeProfile::structure_heavy(self, 1.35, 0.50, 1.60, 0.04),
            Self::Ownership => ConeProfile::balanced(self, 1.00, 0.34, 1.20, 0.08),
            Self::Membership => ConeProfile::balanced(self, 1.10, 0.40, 1.35, 0.06),
            Self::TopicCluster => ConeProfile::topic_heavy(self, 1.25, 0.50, 1.55, 0.03),
            Self::ModalityScope => ConeProfile::structure_heavy(self, 1.20, 0.42, 1.48, 0.04),
            Self::Custom => ConeProfile::balanced(self, 1.00, 0.32, 1.25, 0.08),
        }
    }
}

/// Relation-specific cone behavior.
///
/// `base_aperture_rad` is the starting cone width.
/// `parent_depth_narrowing` narrows the aperture as the parent moves deeper.
/// A shallow abstract parent accepts wider descendants; a deep specific parent
/// accepts only tighter descendants.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct ConeProfile {
    pub relation_kind: HierarchyRelationKind,
    pub base_aperture_rad: f32,
    pub min_aperture_rad: f32,
    pub max_aperture_rad: f32,
    pub parent_depth_narrowing: f32,
    pub min_radial_delta: f32,
    pub same_level_delta: f32,
    pub reverse_radial_delta: f32,
    pub strong_radial_delta: f32,
    pub max_radial_delta: Option<f32>,
    pub strong_margin_rad: f32,
    pub semantic_weight: f32,
    pub hierarchy_weight: f32,
    pub allow_lateral_fallback: bool,
}

impl ConeProfile {
    fn strict(
        relation_kind: HierarchyRelationKind,
        base_aperture_rad: f32,
        min_aperture_rad: f32,
        max_aperture_rad: f32,
        parent_depth_narrowing: f32,
    ) -> Self {
        Self {
            relation_kind,
            base_aperture_rad,
            min_aperture_rad,
            max_aperture_rad,
            parent_depth_narrowing,
            min_radial_delta: 0.035,
            same_level_delta: 0.045,
            reverse_radial_delta: 0.055,
            strong_radial_delta: 0.34,
            max_radial_delta: Some(2.75),
            strong_margin_rad: 0.22,
            semantic_weight: 0.68,
            hierarchy_weight: 0.32,
            allow_lateral_fallback: true,
        }
    }

    fn balanced(
        relation_kind: HierarchyRelationKind,
        base_aperture_rad: f32,
        min_aperture_rad: f32,
        max_aperture_rad: f32,
        parent_depth_narrowing: f32,
    ) -> Self {
        Self {
            relation_kind,
            base_aperture_rad,
            min_aperture_rad,
            max_aperture_rad,
            parent_depth_narrowing,
            min_radial_delta: 0.025,
            same_level_delta: 0.055,
            reverse_radial_delta: 0.070,
            strong_radial_delta: 0.30,
            max_radial_delta: Some(3.25),
            strong_margin_rad: 0.18,
            semantic_weight: 0.55,
            hierarchy_weight: 0.45,
            allow_lateral_fallback: true,
        }
    }

    fn structure_heavy(
        relation_kind: HierarchyRelationKind,
        base_aperture_rad: f32,
        min_aperture_rad: f32,
        max_aperture_rad: f32,
        parent_depth_narrowing: f32,
    ) -> Self {
        Self {
            relation_kind,
            base_aperture_rad,
            min_aperture_rad,
            max_aperture_rad,
            parent_depth_narrowing,
            min_radial_delta: 0.018,
            same_level_delta: 0.070,
            reverse_radial_delta: 0.080,
            strong_radial_delta: 0.28,
            max_radial_delta: Some(4.50),
            strong_margin_rad: 0.16,
            semantic_weight: 0.30,
            hierarchy_weight: 0.70,
            allow_lateral_fallback: true,
        }
    }

    fn evidence_heavy(
        relation_kind: HierarchyRelationKind,
        base_aperture_rad: f32,
        min_aperture_rad: f32,
        max_aperture_rad: f32,
        parent_depth_narrowing: f32,
    ) -> Self {
        Self {
            relation_kind,
            base_aperture_rad,
            min_aperture_rad,
            max_aperture_rad,
            parent_depth_narrowing,
            min_radial_delta: 0.012,
            same_level_delta: 0.080,
            reverse_radial_delta: 0.090,
            strong_radial_delta: 0.24,
            max_radial_delta: Some(5.25),
            strong_margin_rad: 0.12,
            semantic_weight: 0.24,
            hierarchy_weight: 0.76,
            allow_lateral_fallback: true,
        }
    }

    fn causal_or_temporal(
        relation_kind: HierarchyRelationKind,
        base_aperture_rad: f32,
        min_aperture_rad: f32,
        max_aperture_rad: f32,
        parent_depth_narrowing: f32,
    ) -> Self {
        Self {
            relation_kind,
            base_aperture_rad,
            min_aperture_rad,
            max_aperture_rad,
            parent_depth_narrowing,
            min_radial_delta: 0.015,
            same_level_delta: 0.065,
            reverse_radial_delta: 0.080,
            strong_radial_delta: 0.26,
            max_radial_delta: Some(4.25),
            strong_margin_rad: 0.14,
            semantic_weight: 0.36,
            hierarchy_weight: 0.64,
            allow_lateral_fallback: true,
        }
    }

    fn topic_heavy(
        relation_kind: HierarchyRelationKind,
        base_aperture_rad: f32,
        min_aperture_rad: f32,
        max_aperture_rad: f32,
        parent_depth_narrowing: f32,
    ) -> Self {
        Self {
            relation_kind,
            base_aperture_rad,
            min_aperture_rad,
            max_aperture_rad,
            parent_depth_narrowing,
            min_radial_delta: 0.020,
            same_level_delta: 0.090,
            reverse_radial_delta: 0.100,
            strong_radial_delta: 0.28,
            max_radial_delta: Some(4.75),
            strong_margin_rad: 0.15,
            semantic_weight: 0.48,
            hierarchy_weight: 0.52,
            allow_lateral_fallback: true,
        }
    }

    pub fn validate(self) -> HybridSpaceResult<Self> {
        validate_aperture("base_aperture_rad", self.base_aperture_rad)?;
        validate_aperture("min_aperture_rad", self.min_aperture_rad)?;
        validate_aperture("max_aperture_rad", self.max_aperture_rad)?;

        if self.min_aperture_rad > self.max_aperture_rad {
            return Err(HybridSpaceError::InvalidConeAperture {
                field: "min_aperture_rad > max_aperture_rad",
                value: self.min_aperture_rad,
            });
        }

        if !self.parent_depth_narrowing.is_finite() || self.parent_depth_narrowing < 0.0 {
            return Err(HybridSpaceError::InvalidConeRadialThreshold {
                field: "parent_depth_narrowing",
                value: self.parent_depth_narrowing,
            });
        }

        validate_non_negative("min_radial_delta", self.min_radial_delta)?;
        validate_non_negative("same_level_delta", self.same_level_delta)?;
        validate_non_negative("reverse_radial_delta", self.reverse_radial_delta)?;
        validate_positive("strong_radial_delta", self.strong_radial_delta)?;
        validate_non_negative("strong_margin_rad", self.strong_margin_rad)?;

        if let Some(max_radial_delta) = self.max_radial_delta {
            validate_positive("max_radial_delta", max_radial_delta)?;
        }

        if !self.semantic_weight.is_finite()
            || !self.hierarchy_weight.is_finite()
            || self.semantic_weight < 0.0
            || self.hierarchy_weight < 0.0
            || self.semantic_weight + self.hierarchy_weight <= DEFAULT_EPS
        {
            return Err(HybridSpaceError::InvalidConeWeights {
                semantic: self.semantic_weight,
                hierarchy: self.hierarchy_weight,
            });
        }

        Ok(self)
    }

    #[inline]
    pub fn effective_aperture_rad(&self, parent_hyperbolic_radius: f32) -> f32 {
        let depth = parent_hyperbolic_radius.max(0.0);
        let narrowed = self.base_aperture_rad / (1.0 + (self.parent_depth_narrowing * depth));
        narrowed.clamp(self.min_aperture_rad, self.max_aperture_rad)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum ConeVerdict {
    StrongParentChild,
    WeakParentChild,
    SiblingOrCousin,
    TopicalAssociation,
    EvidenceOnly,
    TooShallow,
    LikelyReversedEdge,
    OutsideCone,
    NeedsIntermediateNode,
    MultiParentCandidate,
    ContradictoryGeometry,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum ConeReason {
    DirectionInsideAperture,
    DirectionOutsideAperture,
    StrongAngularFit,
    WeakAngularFit,
    RadialDescentValid,
    RadialDeltaTooSmall,
    ChildSameLevel,
    ChildShallower,
    DepthJumpTooLarge,
    RelationAllowsWideSemanticSpread,
    StructureHeavyRelation,
    EvidenceRelation,
    CausalOrTemporalRelation,
    LateralFallback,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ConeEvaluation {
    pub relation_kind: HierarchyRelationKind,
    pub lane: HierarchyLane,
    pub parent_depth: f32,
    pub child_depth: f32,
    pub parent_hyperbolic_radius: f32,
    pub child_hyperbolic_radius: f32,
    pub radial_delta: f32,
    pub angular_offset_rad: f32,
    pub angular_rank_score: f32,
    pub aperture_rad: f32,
    pub angular_margin_rad: f32,
    pub inside_direction: bool,
    pub valid_radial_descent: bool,
    pub depth_jump_too_large: bool,
    pub fit_score: f32,
    pub verdict: ConeVerdict,
    pub reasons: Vec<ConeReason>,
}

impl ConeEvaluation {
    #[inline]
    pub fn is_parent_child(&self) -> bool {
        matches!(
            self.verdict,
            ConeVerdict::StrongParentChild
                | ConeVerdict::WeakParentChild
                | ConeVerdict::MultiParentCandidate
        )
    }

    #[inline]
    pub fn is_strong_parent_child(&self) -> bool {
        matches!(
            self.verdict,
            ConeVerdict::StrongParentChild | ConeVerdict::MultiParentCandidate
        )
    }

    #[inline]
    pub fn needs_repair(&self) -> bool {
        matches!(
            self.verdict,
            ConeVerdict::LikelyReversedEdge
                | ConeVerdict::NeedsIntermediateNode
                | ConeVerdict::ContradictoryGeometry
        )
    }
}

#[derive(Clone, Debug)]
pub struct ConeParentCandidate<'a, T> {
    pub parent_id: T,
    pub parent: &'a HybridPoint,
    pub relation_kind: HierarchyRelationKind,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ConeParentEvaluation<T> {
    pub parent_id: T,
    pub evaluation: ConeEvaluation,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum ConePlacementVerdict {
    SingleStrongParent,
    MultiParentCandidate,
    WeaklyPlaced,
    NeedsIntermediateNode,
    ContradictoryGeometry,
    Unplaced,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ConePlacement<T> {
    pub verdict: ConePlacementVerdict,
    pub strong_parent_count: usize,
    pub weak_parent_count: usize,
    pub needs_intermediate_count: usize,
    pub reversed_edge_count: usize,
    pub outside_count: usize,
    pub candidates: Vec<ConeParentEvaluation<T>>,
}

/// Build a child point from a parent, a child embedding, and child depth.
///
/// `parent_pull` keeps child direction near the parent sector.
/// Use 0.0 for pure embedding direction.
/// Use 1.0 to force the child onto the parent ray.
pub fn derive_child_point(
    parent: &HybridPoint,
    child_embedding: &[f32],
    child_depth: f32,
    parent_pull: f32,
    config: HybridSpaceConfig,
) -> HybridSpaceResult<HybridPoint> {
    if parent.dim() != child_embedding.len() {
        return Err(HybridSpaceError::DimensionMismatch {
            expected: parent.dim(),
            got: child_embedding.len(),
        });
    }

    let child_dir = normalize_or_north_pole(child_embedding)?;
    let pull = parent_pull.clamp(0.0, 1.0);

    let blended_direction = blend_unit_directions(&parent.semantic_direction, &child_dir, pull)?;
    let config = config.validate()?;

    let hyperbolic_radius = config.depth_to_hyperbolic_radius(child_depth);
    let poincare_radius = config.hyperbolic_radius_to_poincare_radius(hyperbolic_radius);

    let poincare = blended_direction
        .iter()
        .map(|v| v * poincare_radius)
        .collect::<Vec<_>>();

    Ok(HybridPoint {
        semantic_direction: blended_direction,
        poincare,
        depth: child_depth.max(0.0),
        hyperbolic_radius,
        poincare_radius,
    })
}

/// Apply a Möbius translation inside the hybrid hyperball and rebuild the
/// semantic shell direction from the moved Poincare interior point.
///
/// `depth` remains graph-owned; this operation updates the geometric radii but
/// does not infer a new graph depth label.
pub fn hybrid_mobius_translate(
    point: &HybridPoint,
    delta: &[f32],
    config: HybridSpaceConfig,
) -> HybridSpaceResult<HybridPoint> {
    if point.dim() != delta.len() {
        return Err(HybridSpaceError::DimensionMismatch {
            expected: point.dim(),
            got: delta.len(),
        });
    }
    let config = config.validate()?;
    let ball = config.poincare_ball()?;
    let moved = ball.mobius_add(&point.poincare, delta)?;
    HybridPoint::from_poincare_interior(&moved, point.depth, config)
}

/// Exponential map in the Poincare interior of the hybrid hyperball.
pub fn hybrid_exp_map(
    base: &HybridPoint,
    tangent: &[f32],
    config: HybridSpaceConfig,
) -> HybridSpaceResult<HybridPoint> {
    if base.dim() != tangent.len() {
        return Err(HybridSpaceError::DimensionMismatch {
            expected: base.dim(),
            got: tangent.len(),
        });
    }
    let config = config.validate()?;
    let ball = config.poincare_ball()?;
    let moved = ball.exp_map(&base.poincare, tangent)?;
    HybridPoint::from_poincare_interior(&moved, base.depth, config)
}

/// Logarithmic map between two hybrid points, expressed in the tangent space at
/// `base`'s Poincare coordinate.
pub fn hybrid_log_map(
    base: &HybridPoint,
    target: &HybridPoint,
    config: HybridSpaceConfig,
) -> HybridSpaceResult<Vec<f32>> {
    if base.dim() != target.dim() {
        return Err(HybridSpaceError::DimensionMismatch {
            expected: base.dim(),
            got: target.dim(),
        });
    }
    let config = config.validate()?;
    let ball = config.poincare_ball()?;
    Ok(ball.log_map(&base.poincare, &target.poincare)?)
}

/// Parallel transport a tangent vector between two hybrid Poincare interiors.
pub fn hybrid_parallel_transport(
    from: &HybridPoint,
    to: &HybridPoint,
    tangent: &[f32],
    config: HybridSpaceConfig,
) -> HybridSpaceResult<Vec<f32>> {
    if from.dim() != to.dim() {
        return Err(HybridSpaceError::DimensionMismatch {
            expected: from.dim(),
            got: to.dim(),
        });
    }
    if from.dim() != tangent.len() {
        return Err(HybridSpaceError::DimensionMismatch {
            expected: from.dim(),
            got: tangent.len(),
        });
    }
    let config = config.validate()?;
    let ball = config.poincare_ball()?;
    Ok(ball.parallel_transport(&from.poincare, &to.poincare, tangent)?)
}

/// Project a Poincare interior point back to semantic boundary direction.
///
/// Useful for UI rays, labels, and "where does this point aim?"
pub fn boundary_direction(point: &[f32]) -> HybridSpaceResult<Vec<f32>> {
    normalize_or_north_pole(point)
}

/// Return positive if `child` is radially deeper than `parent`.
#[inline]
pub fn radial_depth_delta(parent: &HybridPoint, child: &HybridPoint) -> f32 {
    child.hyperbolic_radius - parent.hyperbolic_radius
}

/// Evaluate a candidate parent-child edge using the default cone profile for
/// that hierarchy relation.
pub fn evaluate_relation_cone(
    parent: &HybridPoint,
    child: &HybridPoint,
    relation_kind: HierarchyRelationKind,
) -> HybridSpaceResult<ConeEvaluation> {
    evaluate_cone(parent, child, relation_kind.default_profile())
}

/// Evaluate a candidate parent-child edge with an explicit relation profile.
///
/// This is a validator first and a scorer second:
/// - semantic shell checks direction against the cone aperture
/// - hyperbolic interior checks that the child sits deeper than the parent
/// - relation profile decides how strict the cone should be
pub fn evaluate_cone(
    parent: &HybridPoint,
    child: &HybridPoint,
    profile: ConeProfile,
) -> HybridSpaceResult<ConeEvaluation> {
    let profile = profile.validate()?;

    if parent.dim() != child.dim() {
        return Err(HybridSpaceError::DimensionMismatch {
            expected: parent.dim(),
            got: child.dim(),
        });
    }

    let dot_score = dot(&parent.semantic_direction, &child.semantic_direction).clamp(-1.0, 1.0);
    let angular_offset_rad = safe_acos(dot_score);
    let angular_rank = 1.0 - dot_score;
    let aperture_rad = profile.effective_aperture_rad(parent.hyperbolic_radius);
    let angular_margin_rad = aperture_rad - angular_offset_rad;
    let inside_direction = angular_offset_rad <= aperture_rad;
    let radial_delta = radial_depth_delta(parent, child);
    let valid_radial_descent = radial_delta >= profile.min_radial_delta;
    let depth_jump_too_large = profile
        .max_radial_delta
        .map(|max_delta| radial_delta > max_delta)
        .unwrap_or(false);

    let mut reasons = Vec::with_capacity(6);

    if inside_direction {
        reasons.push(ConeReason::DirectionInsideAperture);
        if angular_margin_rad >= profile.strong_margin_rad {
            reasons.push(ConeReason::StrongAngularFit);
        } else {
            reasons.push(ConeReason::WeakAngularFit);
        }
    } else {
        reasons.push(ConeReason::DirectionOutsideAperture);
    }

    if valid_radial_descent {
        reasons.push(ConeReason::RadialDescentValid);
    } else if radial_delta.abs() <= profile.same_level_delta {
        reasons.push(ConeReason::ChildSameLevel);
    } else if radial_delta < -profile.reverse_radial_delta {
        reasons.push(ConeReason::ChildShallower);
    } else {
        reasons.push(ConeReason::RadialDeltaTooSmall);
    }

    if depth_jump_too_large {
        reasons.push(ConeReason::DepthJumpTooLarge);
    }

    match profile.relation_kind.lane() {
        HierarchyLane::Structure | HierarchyLane::Schema | HierarchyLane::Provenance => {
            reasons.push(ConeReason::StructureHeavyRelation);
        }
        HierarchyLane::Evidence => reasons.push(ConeReason::EvidenceRelation),
        HierarchyLane::Causal | HierarchyLane::Temporal => {
            reasons.push(ConeReason::CausalOrTemporalRelation);
        }
        HierarchyLane::Topic => reasons.push(ConeReason::RelationAllowsWideSemanticSpread),
        _ => {}
    }

    let fit_score = cone_fit_score(angular_offset_rad, aperture_rad, radial_delta, profile);
    let verdict = cone_verdict(
        profile,
        inside_direction,
        angular_margin_rad,
        radial_delta,
        valid_radial_descent,
        depth_jump_too_large,
    );

    if matches!(
        verdict,
        ConeVerdict::SiblingOrCousin | ConeVerdict::TopicalAssociation
    ) && profile.allow_lateral_fallback
    {
        reasons.push(ConeReason::LateralFallback);
    }

    Ok(ConeEvaluation {
        relation_kind: profile.relation_kind,
        lane: profile.relation_kind.lane(),
        parent_depth: parent.depth,
        child_depth: child.depth,
        parent_hyperbolic_radius: parent.hyperbolic_radius,
        child_hyperbolic_radius: child.hyperbolic_radius,
        radial_delta,
        angular_offset_rad,
        angular_rank_score: angular_rank,
        aperture_rad,
        angular_margin_rad,
        inside_direction,
        valid_radial_descent,
        depth_jump_too_large,
        fit_score,
        verdict,
        reasons,
    })
}

/// Evaluate several possible parents for one child and classify the placement.
///
/// Multiple strong parents are preserved as DAG truth instead of being collapsed
/// into a fake tree.
pub fn evaluate_parent_candidates<'a, T>(
    child: &HybridPoint,
    candidates: impl IntoIterator<Item = ConeParentCandidate<'a, T>>,
) -> HybridSpaceResult<ConePlacement<T>> {
    let mut evaluated = Vec::new();

    for candidate in candidates {
        let evaluation = evaluate_relation_cone(candidate.parent, child, candidate.relation_kind)?;
        evaluated.push(ConeParentEvaluation {
            parent_id: candidate.parent_id,
            evaluation,
        });
    }

    evaluated.sort_by(|a, b| compare_score_desc(a.evaluation.fit_score, b.evaluation.fit_score));

    let mut strong_parent_count = 0usize;
    let mut weak_parent_count = 0usize;
    let mut needs_intermediate_count = 0usize;
    let mut reversed_edge_count = 0usize;
    let mut outside_count = 0usize;

    for candidate in evaluated.iter_mut() {
        match candidate.evaluation.verdict {
            ConeVerdict::StrongParentChild => strong_parent_count += 1,
            ConeVerdict::WeakParentChild => weak_parent_count += 1,
            ConeVerdict::NeedsIntermediateNode => needs_intermediate_count += 1,
            ConeVerdict::LikelyReversedEdge => reversed_edge_count += 1,
            ConeVerdict::OutsideCone => outside_count += 1,
            _ => {}
        }
    }

    if strong_parent_count > 1 {
        for candidate in evaluated.iter_mut() {
            if candidate.evaluation.verdict == ConeVerdict::StrongParentChild {
                candidate.evaluation.verdict = ConeVerdict::MultiParentCandidate;
            }
        }
    }

    let verdict = if strong_parent_count > 1 {
        ConePlacementVerdict::MultiParentCandidate
    } else if strong_parent_count == 1 {
        ConePlacementVerdict::SingleStrongParent
    } else if weak_parent_count > 0 {
        ConePlacementVerdict::WeaklyPlaced
    } else if needs_intermediate_count > 0 {
        ConePlacementVerdict::NeedsIntermediateNode
    } else if reversed_edge_count > 0 {
        ConePlacementVerdict::ContradictoryGeometry
    } else {
        ConePlacementVerdict::Unplaced
    };

    Ok(ConePlacement {
        verdict,
        strong_parent_count,
        weak_parent_count,
        needs_intermediate_count,
        reversed_edge_count,
        outside_count,
        candidates: evaluated,
    })
}

#[inline]
fn cone_verdict(
    profile: ConeProfile,
    inside_direction: bool,
    angular_margin_rad: f32,
    radial_delta: f32,
    valid_radial_descent: bool,
    depth_jump_too_large: bool,
) -> ConeVerdict {
    if radial_delta < -profile.reverse_radial_delta {
        return ConeVerdict::LikelyReversedEdge;
    }

    if radial_delta.abs() <= profile.same_level_delta {
        if inside_direction && profile.allow_lateral_fallback {
            return ConeVerdict::SiblingOrCousin;
        }
        return ConeVerdict::TopicalAssociation;
    }

    if !inside_direction {
        return match profile.relation_kind.lane() {
            HierarchyLane::Evidence if valid_radial_descent => ConeVerdict::EvidenceOnly,
            HierarchyLane::Topic if valid_radial_descent => ConeVerdict::TopicalAssociation,
            _ => ConeVerdict::OutsideCone,
        };
    }

    if !valid_radial_descent {
        return ConeVerdict::TooShallow;
    }

    if depth_jump_too_large {
        return ConeVerdict::NeedsIntermediateNode;
    }

    if radial_delta >= profile.strong_radial_delta
        && angular_margin_rad >= profile.strong_margin_rad
    {
        ConeVerdict::StrongParentChild
    } else {
        ConeVerdict::WeakParentChild
    }
}

#[inline]
fn cone_fit_score(
    angular_offset_rad: f32,
    aperture_rad: f32,
    radial_delta: f32,
    profile: ConeProfile,
) -> f32 {
    let direction_fit = if aperture_rad <= DEFAULT_EPS {
        0.0
    } else {
        (1.0 - (angular_offset_rad / aperture_rad)).clamp(0.0, 1.0)
    };

    let depth_fit = if radial_delta <= 0.0 {
        0.0
    } else {
        (radial_delta / profile.strong_radial_delta.max(DEFAULT_EPS)).clamp(0.0, 1.0)
    };

    let total = profile.semantic_weight + profile.hierarchy_weight;
    let semantic_weight = profile.semantic_weight / total;
    let hierarchy_weight = profile.hierarchy_weight / total;

    ((semantic_weight * direction_fit) + (hierarchy_weight * depth_fit)).clamp(0.0, 1.0)
}

#[inline]
fn angular_rank_score(a: &[f32], b: &[f32]) -> HybridSpaceResult<f32> {
    if a.is_empty() {
        return Err(HybridSpaceError::EmptyVector);
    }
    if a.len() != b.len() {
        return Err(HybridSpaceError::DimensionMismatch {
            expected: a.len(),
            got: b.len(),
        });
    }

    Ok(1.0 - dot(a, b).clamp(-1.0, 1.0))
}

fn blend_unit_directions(
    parent: &[f32],
    child: &[f32],
    parent_pull: f32,
) -> HybridSpaceResult<Vec<f32>> {
    if parent.is_empty() {
        return Err(HybridSpaceError::EmptyVector);
    }
    if parent.len() != child.len() {
        return Err(HybridSpaceError::DimensionMismatch {
            expected: parent.len(),
            got: child.len(),
        });
    }

    let child_weight = 1.0 - parent_pull;
    let mut blended = Vec::with_capacity(parent.len());

    for (&p, &c) in parent.iter().zip(child.iter()) {
        blended.push((parent_pull * p) + (child_weight * c));
    }

    normalize_or_north_pole(&blended)
}

fn normalize_or_north_pole(v: &[f32]) -> HybridSpaceResult<Vec<f32>> {
    if v.is_empty() {
        return Err(HybridSpaceError::EmptyVector);
    }

    let mut norm_sq = 0.0f32;
    let mut all_finite = true;

    for &x in v {
        all_finite &= x.is_finite();
        norm_sq = x.mul_add(x, norm_sq);
    }

    if !all_finite || norm_sq <= DEFAULT_EPS {
        let mut fallback = vec![0.0; v.len()];
        fallback[0] = 1.0;
        return Ok(fallback);
    }

    let inv = norm_sq.sqrt().recip();
    Ok(v.iter().map(|x| x * inv).collect())
}

#[inline]
fn dot(a: &[f32], b: &[f32]) -> f32 {
    let len = a.len().min(b.len());
    let chunks = len / 4;
    let remainder = len % 4;

    let mut i = 0usize;
    let mut acc0 = 0.0f32;
    let mut acc1 = 0.0f32;
    let mut acc2 = 0.0f32;
    let mut acc3 = 0.0f32;

    for _ in 0..chunks {
        acc0 = a[i].mul_add(b[i], acc0);
        acc1 = a[i + 1].mul_add(b[i + 1], acc1);
        acc2 = a[i + 2].mul_add(b[i + 2], acc2);
        acc3 = a[i + 3].mul_add(b[i + 3], acc3);
        i += 4;
    }

    let mut sum = (acc0 + acc1) + (acc2 + acc3);

    for offset in 0..remainder {
        sum = a[i + offset].mul_add(b[i + offset], sum);
    }

    sum
}

#[inline]
fn safe_acos(x: f32) -> f32 {
    x.clamp(-1.0, 1.0).acos()
}

#[inline]
fn compare_score_desc(a: f32, b: f32) -> Ordering {
    match b.partial_cmp(&a) {
        Some(ordering) => ordering,
        None => Ordering::Equal,
    }
}

#[inline]
fn validate_aperture(field: &'static str, value: f32) -> HybridSpaceResult<()> {
    if !value.is_finite() || value <= 0.0 || value > PI {
        return Err(HybridSpaceError::InvalidConeAperture { field, value });
    }
    Ok(())
}

#[inline]
fn validate_non_negative(field: &'static str, value: f32) -> HybridSpaceResult<()> {
    if !value.is_finite() || value < 0.0 {
        return Err(HybridSpaceError::InvalidConeRadialThreshold { field, value });
    }
    Ok(())
}

#[inline]
fn validate_positive(field: &'static str, value: f32) -> HybridSpaceResult<()> {
    if !value.is_finite() || value <= 0.0 {
        return Err(HybridSpaceError::InvalidConeRadialThreshold { field, value });
    }
    Ok(())
}

pub fn validate_busemann_config(config: BusemannConfig) -> HybridSpaceResult<()> {
    if !(config.eps.is_finite() && config.eps > 0.0) {
        return Err(HybridSpaceError::InvalidBusemannConfig {
            field: "eps",
            value: config.eps,
        });
    }

    if !(config.commitment_weight.is_finite() && config.commitment_weight >= 0.0) {
        return Err(HybridSpaceError::InvalidBusemannConfig {
            field: "commitment_weight",
            value: config.commitment_weight,
        });
    }

    if !(config.radial_weight.is_finite() && config.radial_weight >= 0.0) {
        return Err(HybridSpaceError::InvalidBusemannConfig {
            field: "radial_weight",
            value: config.radial_weight,
        });
    }

    if config.commitment_weight + config.radial_weight <= config.eps {
        return Err(HybridSpaceError::InvalidBusemannWeights {
            commitment: config.commitment_weight,
            radial: config.radial_weight,
        });
    }

    if !(config.ambiguity_threshold.is_finite()
        && config.ambiguity_threshold >= 0.0
        && config.ambiguity_threshold <= 1.0)
    {
        return Err(HybridSpaceError::InvalidBusemannConfig {
            field: "ambiguity_threshold",
            value: config.ambiguity_threshold,
        });
    }

    if !(config.promotion_margin.is_finite() && config.promotion_margin >= 0.0) {
        return Err(HybridSpaceError::InvalidBusemannConfig {
            field: "promotion_margin",
            value: config.promotion_margin,
        });
    }

    if config.top_k == 0 {
        return Err(HybridSpaceError::InvalidBusemannTopK(config.top_k));
    }

    Ok(())
}

pub fn validate_interior_geometry(geometry: InteriorGeometry) -> HybridSpaceResult<()> {
    match geometry {
        InteriorGeometry::RadialDepth(_) => Ok(()),
        InteriorGeometry::BusemannCommitment(config) => validate_busemann_config(config),
    }
}

/// Scores one point in the Poincare interior against boundary prototypes.
///
/// Inputs:
/// - `point`: Poincare-ball point in your current curvature convention.
/// - `curvature`: positive c, where hyperbolic curvature is -c.
/// - `prototypes`: boundary directions in the same dimensionality as `point`.
/// - `config.family`: only prototypes from this family are accepted.
///
/// Formula uses the Poincare-unit-ball Busemann expression:
///
/// B_p(x) = ln( ||p - x||^2 / (1 - ||x||^2) )
///
/// with x scaled by sqrt(c) before scoring.
///
/// Convention:
/// lower score = stronger commitment.
pub fn busemann_signature(
    point: &[f32],
    curvature: f32,
    prototypes: &[BusemannPrototype],
    config: BusemannConfig,
) -> HybridSpaceResult<BusemannSignature> {
    validate_busemann_config(config)?;

    if point.is_empty() {
        return Err(HybridSpaceError::EmptyVector);
    }

    if !(curvature.is_finite() && curvature > 0.0) {
        return Err(HybridSpaceError::InvalidCurvature(curvature));
    }

    if prototypes.is_empty() {
        return Err(HybridSpaceError::EmptyBusemannPrototypes);
    }

    let sqrt_c = curvature.sqrt();
    let mut x_unit = Vec::with_capacity(point.len());
    let mut x_norm_sq = 0.0_f32;

    for value in point {
        if !value.is_finite() {
            return Err(HybridSpaceError::InvalidBusemannPrototype {
                prototype_id: 0,
                reason: "point contains non-finite coordinate",
            });
        }

        let scaled = *value * sqrt_c;
        x_norm_sq += scaled * scaled;
        x_unit.push(scaled);
    }

    if !(x_norm_sq.is_finite() && x_norm_sq < 1.0 - config.eps) {
        return Err(HybridSpaceError::BusemannPointOutsideBall { norm_sq: x_norm_sq });
    }

    let mut scores = Vec::with_capacity(prototypes.len());

    for prototype in prototypes {
        if prototype.family != config.family {
            return Err(HybridSpaceError::BusemannPrototypeFamilyMismatch {
                expected: config.family,
                got: prototype.family,
            });
        }

        if prototype.direction.len() != point.len() {
            return Err(HybridSpaceError::DimensionMismatch {
                expected: point.len(),
                got: prototype.direction.len(),
            });
        }

        let score = busemann_score_unit_ball(&x_unit, x_norm_sq, prototype, config.eps)?;

        scores.push(BusemannPrototypeScore {
            prototype_id: prototype.prototype_id,
            family: prototype.family,
            score,
            probability: 0.0,
        });
    }

    apply_busemann_probabilities(&mut scores, config.commitment_weight, config.eps)?;

    scores.sort_by(|a, b| match a.score.partial_cmp(&b.score) {
        Some(ordering) => ordering,
        None => Ordering::Equal,
    });

    let best = match scores.first() {
        Some(score) => score.clone(),
        None => return Err(HybridSpaceError::EmptyBusemannPrototypes),
    };

    let second = if scores.len() > 1 {
        Some(scores[1].clone())
    } else {
        None
    };

    let margin = match &second {
        Some(second_score) => second_score.score - best.score,
        None => config.promotion_margin.max(1.0),
    };

    let entropy = normalized_probability_entropy(&scores, config.eps);
    let radial_strength = x_norm_sq.sqrt().clamp(0.0, 1.0);

    let clean_margin = if margin.is_finite() && margin > 0.0 {
        margin
    } else {
        0.0
    };

    let commitment_confidence = clean_margin / (1.0 + clean_margin);

    let weight_sum = config.commitment_weight + config.radial_weight;
    let classification_confidence = if weight_sum <= config.eps {
        commitment_confidence
    } else {
        ((config.commitment_weight * commitment_confidence)
            + (config.radial_weight * radial_strength))
            / weight_sum
    }
    .clamp(0.0, 1.0);

    let promotion_ready =
        clean_margin >= config.promotion_margin && entropy <= config.ambiguity_threshold;

    let keep = config.top_k.min(scores.len());
    let top_k_scores = scores.into_iter().take(keep).collect::<Vec<_>>();

    Ok(BusemannSignature {
        family: config.family,

        top_prototype_id: best.prototype_id,
        top_score: best.score,
        top_probability: best.probability,

        second_prototype_id: second.as_ref().map(|s| s.prototype_id),
        second_score: second.as_ref().map(|s| s.score),
        second_probability: second.as_ref().map(|s| s.probability),

        margin: clean_margin,
        entropy,
        ambiguity_score: entropy,
        classification_confidence,
        promotion_ready,
        radial_strength,

        top_k_scores,
    })
}

fn busemann_score_unit_ball(
    x_unit: &[f32],
    x_norm_sq: f32,
    prototype: &BusemannPrototype,
    eps: f32,
) -> HybridSpaceResult<f32> {
    let mut prototype_norm_sq = 0.0_f32;

    for value in &prototype.direction {
        if !value.is_finite() {
            return Err(HybridSpaceError::InvalidBusemannPrototype {
                prototype_id: prototype.prototype_id,
                reason: "prototype direction contains non-finite coordinate",
            });
        }

        prototype_norm_sq += *value * *value;
    }

    if !(prototype_norm_sq.is_finite() && prototype_norm_sq > eps) {
        return Err(HybridSpaceError::InvalidBusemannPrototype {
            prototype_id: prototype.prototype_id,
            reason: "prototype direction has zero/invalid norm",
        });
    }

    let inv_norm = 1.0 / prototype_norm_sq.sqrt();

    let mut dist_sq = 0.0_f32;

    for (x, p) in x_unit.iter().zip(prototype.direction.iter()) {
        let p_unit = *p * inv_norm;
        let delta = p_unit - *x;
        dist_sq += delta * delta;
    }

    let numerator = dist_sq.max(eps);
    let denominator = (1.0 - x_norm_sq).max(eps);

    let score = (numerator / denominator).ln();

    if !score.is_finite() {
        return Err(HybridSpaceError::InvalidBusemannPrototype {
            prototype_id: prototype.prototype_id,
            reason: "Busemann score is non-finite",
        });
    }

    Ok(score)
}

fn apply_busemann_probabilities(
    scores: &mut [BusemannPrototypeScore],
    commitment_weight: f32,
    eps: f32,
) -> HybridSpaceResult<()> {
    if scores.is_empty() {
        return Err(HybridSpaceError::EmptyBusemannPrototypes);
    }

    let mut max_logit = f32::NEG_INFINITY;

    for score in scores.iter() {
        if !score.score.is_finite() {
            return Err(HybridSpaceError::InvalidBusemannPrototype {
                prototype_id: score.prototype_id,
                reason: "prototype score is non-finite",
            });
        }

        // Lower Busemann score means stronger commitment, so negate.
        let logit = -commitment_weight * score.score;

        if logit > max_logit {
            max_logit = logit;
        }
    }

    let mut denom = 0.0_f32;

    for score in scores.iter() {
        let logit = -commitment_weight * score.score;
        denom += (logit - max_logit).exp();
    }

    if !(denom.is_finite() && denom > eps) {
        let uniform = 1.0 / scores.len() as f32;
        for score in scores.iter_mut() {
            score.probability = uniform;
        }
        return Ok(());
    }

    for score in scores.iter_mut() {
        let logit = -commitment_weight * score.score;
        score.probability = ((logit - max_logit).exp() / denom).clamp(0.0, 1.0);
    }

    Ok(())
}

fn normalized_probability_entropy(scores: &[BusemannPrototypeScore], eps: f32) -> f32 {
    if scores.len() <= 1 {
        return 0.0;
    }

    let mut entropy = 0.0_f32;

    for score in scores {
        let p = score.probability.max(eps).min(1.0);
        entropy -= p * p.ln();
    }

    let max_entropy = (scores.len() as f32).ln();

    if max_entropy <= eps {
        0.0
    } else {
        (entropy / max_entropy).clamp(0.0, 1.0)
    }
}

#[cfg(test)]
mod busemann_tests {
    use super::*;

    fn proto(id: u64, x: f32, y: f32) -> BusemannPrototype {
        BusemannPrototype {
            prototype_id: id,
            family: PrototypeFamily::EntityKind,
            direction: vec![x, y],
        }
    }

    #[test]
    fn busemann_prefers_matching_boundary_direction() -> HybridSpaceResult<()> {
        let config = BusemannConfig {
            family: PrototypeFamily::EntityKind,
            commitment_weight: 2.0,
            radial_weight: 0.0,
            ambiguity_threshold: 0.6,
            promotion_margin: 0.25,
            top_k: 2,
            eps: DEFAULT_EPS,
        };

        let point = vec![0.45, 0.0];

        let prototypes = vec![proto(1, 1.0, 0.0), proto(2, -1.0, 0.0)];

        let sig = busemann_signature(&point, 1.0, &prototypes, config)?;

        assert_eq!(sig.top_prototype_id, 1);
        assert!(sig.margin > 0.25);
        assert!(sig.top_probability > sig.second_probability.unwrap_or(0.0));

        Ok(())
    }

    #[test]
    fn busemann_center_is_ambiguous_between_opposites() -> HybridSpaceResult<()> {
        let config = BusemannConfig {
            family: PrototypeFamily::EntityKind,
            commitment_weight: 2.0,
            radial_weight: 0.0,
            ambiguity_threshold: 0.4,
            promotion_margin: 0.25,
            top_k: 2,
            eps: DEFAULT_EPS,
        };

        let point = vec![0.0, 0.0];

        let prototypes = vec![proto(1, 1.0, 0.0), proto(2, -1.0, 0.0)];

        let sig = busemann_signature(&point, 1.0, &prototypes, config)?;

        assert!(sig.margin < 0.01);
        assert!(sig.entropy > 0.95);
        assert!(!sig.promotion_ready);

        Ok(())
    }

    #[test]
    fn busemann_rejects_point_outside_scaled_ball() {
        let config = BusemannConfig::default();

        let point = vec![1.2, 0.0];

        let prototypes = vec![proto(1, 1.0, 0.0), proto(2, -1.0, 0.0)];

        let err = busemann_signature(&point, 1.0, &prototypes, config);

        assert!(matches!(
            err,
            Err(HybridSpaceError::BusemannPointOutsideBall { .. })
        ));
    }

    #[test]
    fn busemann_rejects_wrong_family() {
        let config = BusemannConfig {
            family: PrototypeFamily::RelationFamily,
            ..BusemannConfig::default()
        };

        let point = vec![0.2, 0.0];
        let prototypes = vec![proto(1, 1.0, 0.0)];

        let err = busemann_signature(&point, 1.0, &prototypes, config);

        assert!(matches!(
            err,
            Err(HybridSpaceError::BusemannPrototypeFamilyMismatch { .. })
        ));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn norm(v: &[f32]) -> f32 {
        v.iter().map(|x| x * x).sum::<f32>().sqrt()
    }

    fn assert_close(left: f32, right: f32, tol: f32) {
        assert!(
            (left - right).abs() <= tol,
            "expected {left} ~= {right} within {tol}, diff={}",
            (left - right).abs()
        );
    }

    fn assert_vec_close(left: &[f32], right: &[f32], tol: f32) {
        assert_eq!(left.len(), right.len());
        for (index, (l, r)) in left.iter().zip(right).enumerate() {
            assert!(
                (l - r).abs() <= tol,
                "index {index}: expected {l} ~= {r} within {tol}, diff={}",
                (l - r).abs()
            );
        }
    }

    fn riemannian_norm(point: &HybridPoint, tangent: &[f32], config: HybridSpaceConfig) -> f32 {
        poincare::conformal_factor(&point.poincare, config.curvature) * norm(tangent)
    }

    fn unit_from_angle(rad: f32) -> [f32; 2] {
        [rad.cos(), rad.sin()]
    }

    #[test]
    fn semantic_direction_is_unit_normalized() {
        let config = HybridSpaceConfig::default();
        let point = HybridPoint::from_embedding_and_depth(&[3.0, 4.0], 2.0, config).assert_ok();

        let n = norm(&point.semantic_direction);
        assert!((n - 1.0).abs() < 1e-5);
    }

    #[test]
    fn deeper_points_move_outward() {
        let config = HybridSpaceConfig::default();

        let shallow = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 1.0, config).assert_ok();
        let deep = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 8.0, config).assert_ok();

        assert!(deep.hyperbolic_radius > shallow.hyperbolic_radius);
        assert!(deep.poincare_radius > shallow.poincare_radius);
        assert!(deep.poincare_radius < config.max_poincare_radius());
    }

    #[test]
    fn hybrid_rebuilds_shell_direction_from_poincare_interior() {
        let config = HybridSpaceConfig::default();
        let point = HybridPoint::from_poincare_interior(&[0.3, 0.4], 3.0, config).assert_ok();

        assert_close(norm(&point.semantic_direction), 1.0, 1e-5);
        assert_close(point.poincare_radius, 0.5, 1e-5);
        assert_close(
            point.hyperbolic_radius,
            config.poincare_radius_to_hyperbolic_radius(0.5),
            1e-5,
        );
        assert_vec_close(&point.semantic_direction, &[0.6, 0.8], 1e-5);
    }

    #[test]
    fn hybrid_projection_keeps_interior_inside_hyperball() {
        let config = HybridSpaceConfig::default();
        let mut point = HybridPoint {
            semantic_direction: vec![1.0, 0.0],
            poincare: vec![10.0, 0.0],
            depth: 2.0,
            hyperbolic_radius: 0.0,
            poincare_radius: 10.0,
        };

        point.project_interior(config).assert_ok();

        assert!(point.poincare_radius <= config.max_poincare_radius() + 1e-5);
        assert_close(norm(&point.semantic_direction), 1.0, 1e-5);
    }

    #[test]
    fn hybrid_mobius_translate_updates_projection_without_losing_depth_label() {
        let config = HybridSpaceConfig::default();
        let point = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 2.0, config).assert_ok();
        let moved = hybrid_mobius_translate(&point, &[0.05, 0.08], config).assert_ok();

        assert_eq!(moved.depth, point.depth);
        assert!(moved.poincare_radius <= config.max_poincare_radius() + 1e-5);
        assert_close(norm(&moved.semantic_direction), 1.0, 1e-5);
        assert!(moved.semantic_direction[1] > point.semantic_direction[1]);
    }

    #[test]
    fn hybrid_exp_log_roundtrip_uses_poincare_interior() {
        let config = HybridSpaceConfig::default();
        let base = HybridPoint::from_embedding_and_depth(&[1.0, 0.2], 2.0, config).assert_ok();
        let tangent = vec![0.025, -0.015];

        let moved = hybrid_exp_map(&base, &tangent, config).assert_ok();
        let recovered = hybrid_log_map(&base, &moved, config).assert_ok();

        assert_vec_close(&recovered, &tangent, 1e-3);
        assert!(moved.poincare_radius <= config.max_poincare_radius() + 1e-5);
        assert_close(norm(&moved.semantic_direction), 1.0, 1e-5);
    }

    #[test]
    fn hybrid_parallel_transport_preserves_poincare_riemannian_norm() {
        let config = HybridSpaceConfig::default();
        let from = HybridPoint::from_embedding_and_depth(&[1.0, 0.1], 2.0, config).assert_ok();
        let to = HybridPoint::from_embedding_and_depth(&[0.2, 1.0], 4.0, config).assert_ok();
        let tangent = vec![0.02, -0.01];

        let transported = hybrid_parallel_transport(&from, &to, &tangent, config).assert_ok();

        assert_close(
            riemannian_norm(&from, &tangent, config),
            riemannian_norm(&to, &transported, config),
            1e-3,
        );
    }

    #[test]
    fn root_lives_at_origin() {
        let root = HybridPoint::root(3).assert_ok();

        assert_eq!(root.poincare, vec![0.0, 0.0, 0.0]);
        assert_eq!(root.depth, 0.0);
        assert_eq!(root.hyperbolic_radius, 0.0);
    }

    #[test]
    fn child_can_be_pulled_toward_parent_sector() {
        let config = HybridSpaceConfig::default();
        let parent = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 1.0, config).assert_ok();

        let child = derive_child_point(&parent, &[0.0, 1.0], 2.0, 0.75, config).assert_ok();

        assert!(radial_depth_delta(&parent, &child) > 0.0);
        assert!(child.semantic_direction[0] > child.semantic_direction[1]);
    }

    #[test]
    fn hybrid_metric_preserves_hierarchy_distance_signal() {
        let config = HybridSpaceConfig::default();
        let metric = HybridPointMetric {
            semantic_weight: 0.0,
            hierarchy_weight: 1.0,
            curvature: 1.0,
        };

        let a = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 1.0, config).assert_ok();
        let near = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 2.0, config).assert_ok();
        let far = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 8.0, config).assert_ok();

        let d_near = metric.eval_points(&a, &near).assert_ok();
        let d_far = metric.eval_points(&a, &far).assert_ok();

        assert!(d_near < d_far);
    }

    #[test]
    fn interior_metric_projects_into_ball() {
        let metric = HybridInteriorMetric::default();
        let mut v = vec![10.0, 0.0, 0.0];

        metric.project_to_ball(&mut v);

        assert!(norm(&v) < 1.0);
    }

    #[test]
    fn cone_accepts_deeper_child_in_parent_direction() {
        let config = HybridSpaceConfig::default();
        let parent = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 1.0, config).assert_ok();
        let child = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 2.0, config).assert_ok();

        let eval = evaluate_relation_cone(&parent, &child, HierarchyRelationKind::TypeHierarchy)
            .assert_ok();

        assert_eq!(eval.verdict, ConeVerdict::StrongParentChild);
        assert!(eval.inside_direction);
        assert!(eval.valid_radial_descent);
    }

    #[test]
    fn cone_detects_likely_reversed_edge() {
        let config = HybridSpaceConfig::default();
        let parent = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 3.0, config).assert_ok();
        let child = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 1.0, config).assert_ok();

        let eval = evaluate_relation_cone(&parent, &child, HierarchyRelationKind::TypeHierarchy)
            .assert_ok();

        assert_eq!(eval.verdict, ConeVerdict::LikelyReversedEdge);
    }

    #[test]
    fn cone_separates_sibling_from_child() {
        let config = HybridSpaceConfig::default();
        let parent = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 2.0, config).assert_ok();
        let sibling_dir = unit_from_angle(0.20);
        let sibling = HybridPoint::from_embedding_and_depth(&sibling_dir, 2.0, config).assert_ok();

        let eval = evaluate_relation_cone(&parent, &sibling, HierarchyRelationKind::TypeHierarchy)
            .assert_ok();

        assert_eq!(eval.verdict, ConeVerdict::SiblingOrCousin);
    }

    #[test]
    fn cone_rejects_child_outside_aperture() {
        let config = HybridSpaceConfig::default();
        let parent = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 1.0, config).assert_ok();
        let child = HybridPoint::from_embedding_and_depth(&[-1.0, 0.0], 2.0, config).assert_ok();

        let eval = evaluate_relation_cone(&parent, &child, HierarchyRelationKind::TypeHierarchy)
            .assert_ok();

        assert_eq!(eval.verdict, ConeVerdict::OutsideCone);
        assert!(!eval.inside_direction);
    }

    #[test]
    fn shallow_parent_has_wider_cone_than_deep_parent() {
        let config = HybridSpaceConfig::default();
        let shallow_parent =
            HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 1.0, config).assert_ok();
        let deep_parent =
            HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 8.0, config).assert_ok();
        let profile = HierarchyRelationKind::TypeHierarchy.default_profile();

        let shallow_aperture = profile.effective_aperture_rad(shallow_parent.hyperbolic_radius);
        let deep_aperture = profile.effective_aperture_rad(deep_parent.hyperbolic_radius);

        assert!(shallow_aperture > deep_aperture);
    }

    #[test]
    fn cone_detects_missing_intermediate_node() {
        let config = HybridSpaceConfig::default();
        let parent = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 1.0, config).assert_ok();
        let child = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 100.0, config).assert_ok();

        let eval = evaluate_relation_cone(&parent, &child, HierarchyRelationKind::TypeHierarchy)
            .assert_ok();

        assert_eq!(eval.verdict, ConeVerdict::NeedsIntermediateNode);
        assert!(eval.depth_jump_too_large);
    }

    #[test]
    fn type_cone_is_stricter_than_evidence_cone() {
        let config = HybridSpaceConfig::default();
        let parent = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 1.0, config).assert_ok();
        let child_dir = unit_from_angle(0.75);
        let child = HybridPoint::from_embedding_and_depth(&child_dir, 2.0, config).assert_ok();

        let type_eval =
            evaluate_relation_cone(&parent, &child, HierarchyRelationKind::TypeHierarchy)
                .assert_ok();
        let evidence_eval =
            evaluate_relation_cone(&parent, &child, HierarchyRelationKind::EvidenceSupport)
                .assert_ok();

        assert_eq!(type_eval.verdict, ConeVerdict::OutsideCone);
        assert!(evidence_eval.inside_direction);
        assert!(evidence_eval.is_parent_child());
    }

    #[test]
    fn document_cone_accepts_wider_semantic_spread_than_type_cone() {
        let config = HybridSpaceConfig::default();
        let parent = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 1.0, config).assert_ok();
        let child_dir = unit_from_angle(1.20);
        let child = HybridPoint::from_embedding_and_depth(&child_dir, 2.0, config).assert_ok();

        let type_eval =
            evaluate_relation_cone(&parent, &child, HierarchyRelationKind::TypeHierarchy)
                .assert_ok();
        let doc_eval =
            evaluate_relation_cone(&parent, &child, HierarchyRelationKind::DocumentContainment)
                .assert_ok();

        assert_eq!(type_eval.verdict, ConeVerdict::OutsideCone);
        assert!(doc_eval.inside_direction);
        assert!(doc_eval.is_parent_child());
    }

    #[test]
    fn multi_parent_candidates_are_preserved() {
        let config = HybridSpaceConfig::default();
        let parent_a = HybridPoint::from_embedding_and_depth(&[1.0, 0.0], 1.0, config).assert_ok();
        let parent_b_dir = unit_from_angle(0.10);
        let parent_b =
            HybridPoint::from_embedding_and_depth(&parent_b_dir, 1.0, config).assert_ok();
        let child_dir = unit_from_angle(0.05);
        let child = HybridPoint::from_embedding_and_depth(&child_dir, 2.0, config).assert_ok();

        let placement = evaluate_parent_candidates(
            &child,
            vec![
                ConeParentCandidate {
                    parent_id: "a",
                    parent: &parent_a,
                    relation_kind: HierarchyRelationKind::Abstraction,
                },
                ConeParentCandidate {
                    parent_id: "b",
                    parent: &parent_b,
                    relation_kind: HierarchyRelationKind::Abstraction,
                },
            ],
        )
        .assert_ok();

        assert_eq!(
            placement.verdict,
            ConePlacementVerdict::MultiParentCandidate
        );
        assert_eq!(placement.strong_parent_count, 2);
        assert!(placement
            .candidates
            .iter()
            .all(|candidate| candidate.evaluation.verdict == ConeVerdict::MultiParentCandidate));
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
