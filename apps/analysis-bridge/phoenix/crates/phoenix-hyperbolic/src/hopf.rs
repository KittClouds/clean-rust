//! Hopf-style anchor + context-fiber navigation layer.
//!
//! This module is intentionally storage-agnostic. OverGraph remains the truth
//! store and ANN remains the candidate generator. Hopf v1 gives rerankers a
//! stable shape for saying: same identity anchor, different contextual orbit.

use core::cmp::Ordering;
use serde::{Deserialize, Serialize};
use thiserror::Error;

const DEFAULT_EPS: f32 = 1e-6;

#[derive(Debug, Error)]
pub enum HopfError {
    #[error("empty vector")]
    EmptyVector,

    #[error("dimension mismatch: expected {expected}, got {got}")]
    DimensionMismatch { expected: usize, got: usize },

    #[error("invalid config field {field}: {value}")]
    InvalidConfigField { field: &'static str, value: f32 },
}

pub type HopfResult<T> = Result<T, HopfError>;

/// Controlled MVP vocabulary for contextual lanes.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum FiberKind {
    Identity,
    Relationship,
    Location,
    Event,
    Temporal,
    Causal,
    Mechanical,
    Emotional,
    Political,
    Evidence,
    Provenance,
    Contradiction,
    Abstraction,
    Species,
    PowerSystem,
    DocumentStructure,
}

impl FiberKind {
    #[inline]
    pub fn is_compatible_with(self, other: Self) -> bool {
        if self == other {
            return true;
        }
        matches!(
            (self, other),
            (Self::Relationship, Self::Emotional)
                | (Self::Emotional, Self::Relationship)
                | (Self::Temporal, Self::Causal)
                | (Self::Causal, Self::Temporal)
                | (Self::Evidence, Self::Provenance)
                | (Self::Provenance, Self::Evidence)
                | (Self::Mechanical, Self::PowerSystem)
                | (Self::PowerSystem, Self::Mechanical)
        )
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HopfQueryMode {
    AnchorSearch,
    DirectLookup,
    ContextualContinuity,
    CrossDomainSynthesis,
    Contradiction,
}

impl Default for HopfQueryMode {
    fn default() -> Self {
        Self::DirectLookup
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HopfFiberEdgeKind {
    ContextShift,
    TemporalStep,
    CausalStep,
    EvidenceSupport,
    Contradiction,
    ProvenancePath,
    IdentityFacet,
    Generic,
}

/// Stable semantic location for one OverGraph node.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HopfAnchor {
    pub node_id: String,
    pub anchor_vector: Vec<f32>,
    pub anchor_vector_ref: Option<String>,
    pub base_cell_id: Option<String>,
    pub macro_sector: Option<String>,
    pub anchor_confidence: f32,
    pub geometry_version: u64,
}

impl HopfAnchor {
    pub fn new(node_id: impl Into<String>, anchor_vector: &[f32]) -> HopfResult<Self> {
        Ok(Self {
            node_id: node_id.into(),
            anchor_vector: normalize_or_north_pole(anchor_vector)?,
            anchor_vector_ref: None,
            base_cell_id: None,
            macro_sector: None,
            anchor_confidence: 1.0,
            geometry_version: 1,
        })
    }

    #[inline]
    pub fn dim(&self) -> usize {
        self.anchor_vector.len()
    }
}

/// Contextual orbit around one anchor.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HopfFiber {
    pub fiber_id: String,
    pub node_id: String,
    pub fiber_kind: FiberKind,
    pub fiber_label: String,
    pub context_vector: Vec<f32>,
    /// Normalized orbit position in [0, 1). Lane-specific builders decide what
    /// the phase means: cause/effect, early/late, distance/trust/repair, etc.
    pub phase: f32,
    pub radius: f32,
    pub strength: f32,
    pub confidence: f32,
    pub source_count: u32,
    pub geometry_version: u64,
}

impl HopfFiber {
    pub fn new(
        fiber_id: impl Into<String>,
        node_id: impl Into<String>,
        fiber_kind: FiberKind,
        fiber_label: impl Into<String>,
        context_vector: &[f32],
        phase: f32,
    ) -> HopfResult<Self> {
        Ok(Self {
            fiber_id: fiber_id.into(),
            node_id: node_id.into(),
            fiber_kind,
            fiber_label: fiber_label.into(),
            context_vector: normalize_or_north_pole(context_vector)?,
            phase: normalize_phase(phase),
            radius: 1.0,
            strength: 1.0,
            confidence: 1.0,
            source_count: 1,
            geometry_version: 1,
        })
    }

    #[inline]
    pub fn dim(&self) -> usize {
        self.context_vector.len()
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HopfFiberEdge {
    pub from_fiber_id: String,
    pub to_fiber_id: String,
    pub edge_kind: HopfFiberEdgeKind,
    pub strength: f32,
    pub evidence_count: u32,
    pub traversal_cost: f32,
    pub reason: String,
}

impl HopfFiberEdge {
    pub fn new(
        from_fiber_id: impl Into<String>,
        to_fiber_id: impl Into<String>,
        edge_kind: HopfFiberEdgeKind,
    ) -> Self {
        Self {
            from_fiber_id: from_fiber_id.into(),
            to_fiber_id: to_fiber_id.into(),
            edge_kind,
            strength: 1.0,
            evidence_count: 1,
            traversal_cost: 1.0,
            reason: String::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HopfCell {
    pub cell_id: String,
    pub parent_cell_id: Option<String>,
    pub level: u32,
    pub label: String,
    pub centroid: Vec<f32>,
    pub centroid_ref: Option<String>,
    pub density: f32,
    pub dominant_kinds: Vec<FiberKind>,
    pub geometry_version: u64,
}

impl HopfCell {
    pub fn new(
        cell_id: impl Into<String>,
        level: u32,
        label: impl Into<String>,
        centroid: &[f32],
    ) -> HopfResult<Self> {
        Ok(Self {
            cell_id: cell_id.into(),
            parent_cell_id: None,
            level,
            label: label.into(),
            centroid: normalize_or_north_pole(centroid)?,
            centroid_ref: None,
            density: 0.0,
            dominant_kinds: Vec::new(),
            geometry_version: 1,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HopfQuery {
    pub anchor_vector: Vec<f32>,
    pub context_vector: Option<Vec<f32>>,
    pub fiber_kinds: Vec<FiberKind>,
    pub phase: Option<f32>,
    pub mode: HopfQueryMode,
}

impl HopfQuery {
    pub fn new(anchor_vector: &[f32]) -> HopfResult<Self> {
        Ok(Self {
            anchor_vector: normalize_or_north_pole(anchor_vector)?,
            context_vector: None,
            fiber_kinds: Vec::new(),
            phase: None,
            mode: HopfQueryMode::DirectLookup,
        })
    }

    pub fn with_context_vector(mut self, context_vector: &[f32]) -> HopfResult<Self> {
        self.context_vector = Some(normalize_or_north_pole(context_vector)?);
        Ok(self)
    }

    pub fn with_fiber_kinds(mut self, fiber_kinds: Vec<FiberKind>) -> Self {
        self.fiber_kinds = fiber_kinds;
        self
    }

    pub fn with_phase(mut self, phase: f32) -> Self {
        self.phase = Some(normalize_phase(phase));
        self
    }

    pub fn with_mode(mut self, mode: HopfQueryMode) -> Self {
        self.mode = mode;
        self
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HopfScoreConfig {
    pub anchor_weight: f32,
    pub fiber_kind_weight: f32,
    pub context_weight: f32,
    pub graph_edge_weight: f32,
    pub evidence_weight: f32,
    pub phase_weight: f32,
    pub provenance_weight: f32,
    pub unsupported_jump_penalty: f32,
    pub fiber_drift_penalty: f32,
    pub phase_mismatch_penalty: f32,
}

impl Default for HopfScoreConfig {
    fn default() -> Self {
        Self {
            anchor_weight: 0.34,
            fiber_kind_weight: 0.20,
            context_weight: 0.18,
            graph_edge_weight: 0.10,
            evidence_weight: 0.06,
            phase_weight: 0.09,
            provenance_weight: 0.03,
            unsupported_jump_penalty: 0.22,
            fiber_drift_penalty: 0.18,
            phase_mismatch_penalty: 0.14,
        }
    }
}

impl HopfScoreConfig {
    pub fn validate(self) -> HopfResult<Self> {
        for (field, value) in [
            ("anchor_weight", self.anchor_weight),
            ("fiber_kind_weight", self.fiber_kind_weight),
            ("context_weight", self.context_weight),
            ("graph_edge_weight", self.graph_edge_weight),
            ("evidence_weight", self.evidence_weight),
            ("phase_weight", self.phase_weight),
            ("provenance_weight", self.provenance_weight),
            ("unsupported_jump_penalty", self.unsupported_jump_penalty),
            ("fiber_drift_penalty", self.fiber_drift_penalty),
            ("phase_mismatch_penalty", self.phase_mismatch_penalty),
        ] {
            validate_non_negative(field, value)?;
        }
        Ok(self)
    }
}

#[derive(Clone, Debug)]
pub struct HopfCandidateRef<'a, T> {
    pub candidate_id: T,
    pub anchor: &'a HopfAnchor,
    pub fiber: Option<&'a HopfFiber>,
    pub incoming_edge: Option<&'a HopfFiberEdge>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HopfCandidateScore<T> {
    pub candidate_id: T,
    pub node_id: String,
    pub fiber_id: Option<String>,
    pub fiber_kind: Option<FiberKind>,
    pub score: f32,
    pub anchor_similarity: f32,
    pub fiber_match: f32,
    pub context_similarity: f32,
    pub graph_edge_strength: f32,
    pub evidence_strength: f32,
    pub phase_alignment: f32,
    pub provenance_confidence: f32,
    pub unsupported_jump_penalty: f32,
    pub fiber_drift_penalty: f32,
    pub phase_mismatch_penalty: f32,
}

pub fn score_hopf_candidate<T: Clone>(
    query: &HopfQuery,
    candidate: HopfCandidateRef<'_, T>,
    config: HopfScoreConfig,
) -> HopfResult<HopfCandidateScore<T>> {
    let config = config.validate()?;
    ensure_same_dim(&query.anchor_vector, &candidate.anchor.anchor_vector)?;
    let anchor_similarity =
        cosine_similarity01(&query.anchor_vector, &candidate.anchor.anchor_vector)?
            * candidate.anchor.anchor_confidence.clamp(0.0, 1.0);

    let fiber_match = candidate
        .fiber
        .map(|fiber| fiber_kind_match(query, fiber.fiber_kind))
        .unwrap_or_else(|| {
            if query.fiber_kinds.is_empty() {
                1.0
            } else {
                0.0
            }
        });

    let context_similarity = match (&query.context_vector, candidate.fiber) {
        (Some(context_vector), Some(fiber)) => {
            ensure_same_dim(context_vector, &fiber.context_vector)?;
            cosine_similarity01(context_vector, &fiber.context_vector)?
        }
        (Some(_), None) => 0.0,
        (None, Some(_)) => 0.5,
        (None, None) => 1.0,
    };

    let phase_alignment = match (query.phase, candidate.fiber) {
        (Some(query_phase), Some(fiber)) => phase_alignment_score(query_phase, fiber.phase),
        (Some(_), None) => 0.0,
        (None, _) => 0.5,
    };

    let graph_edge_strength = candidate
        .incoming_edge
        .map(edge_support_score)
        .unwrap_or_default();
    let evidence_strength = candidate
        .fiber
        .map(|fiber| source_count_score(fiber.source_count))
        .unwrap_or_default();
    let provenance_confidence = candidate
        .fiber
        .map(|fiber| fiber.confidence.clamp(0.0, 1.0))
        .unwrap_or(candidate.anchor.anchor_confidence.clamp(0.0, 1.0));

    let needs_edge = matches!(
        query.mode,
        HopfQueryMode::CrossDomainSynthesis | HopfQueryMode::Contradiction
    );
    let unsupported_jump_penalty = if needs_edge && candidate.incoming_edge.is_none() {
        config.unsupported_jump_penalty
    } else {
        0.0
    };
    let fiber_drift_penalty = if query.fiber_kinds.is_empty() {
        0.0
    } else {
        config.fiber_drift_penalty * (1.0 - fiber_match).clamp(0.0, 1.0)
    };
    let phase_mismatch_penalty = if query.phase.is_some() {
        config.phase_mismatch_penalty * (1.0 - phase_alignment).clamp(0.0, 1.0)
    } else {
        0.0
    };

    let raw = (config.anchor_weight * anchor_similarity)
        + (config.fiber_kind_weight * fiber_match)
        + (config.context_weight * context_similarity)
        + (config.graph_edge_weight * graph_edge_strength)
        + (config.evidence_weight * evidence_strength)
        + (config.phase_weight * phase_alignment)
        + (config.provenance_weight * provenance_confidence)
        - unsupported_jump_penalty
        - fiber_drift_penalty
        - phase_mismatch_penalty;

    Ok(HopfCandidateScore {
        candidate_id: candidate.candidate_id,
        node_id: candidate.anchor.node_id.clone(),
        fiber_id: candidate.fiber.map(|fiber| fiber.fiber_id.clone()),
        fiber_kind: candidate.fiber.map(|fiber| fiber.fiber_kind),
        score: raw,
        anchor_similarity,
        fiber_match,
        context_similarity,
        graph_edge_strength,
        evidence_strength,
        phase_alignment,
        provenance_confidence,
        unsupported_jump_penalty,
        fiber_drift_penalty,
        phase_mismatch_penalty,
    })
}

pub fn rank_hopf_candidates<'a, T: Clone + Ord>(
    query: &HopfQuery,
    candidates: impl IntoIterator<Item = HopfCandidateRef<'a, T>>,
    config: HopfScoreConfig,
) -> HopfResult<Vec<HopfCandidateScore<T>>> {
    let mut scores = candidates
        .into_iter()
        .map(|candidate| score_hopf_candidate(query, candidate, config))
        .collect::<HopfResult<Vec<_>>>()?;
    scores.sort_by(|left, right| {
        compare_score_desc(left.score, right.score)
            .then_with(|| left.node_id.cmp(&right.node_id))
            .then_with(|| left.fiber_id.cmp(&right.fiber_id))
            .then_with(|| left.candidate_id.cmp(&right.candidate_id))
    });
    Ok(scores)
}

#[inline]
pub fn normalize_phase(phase: f32) -> f32 {
    if !phase.is_finite() {
        return 0.0;
    }
    phase.rem_euclid(1.0)
}

#[inline]
pub fn phase_alignment_score(query_phase: f32, candidate_phase: f32) -> f32 {
    let query_phase = normalize_phase(query_phase);
    let candidate_phase = normalize_phase(candidate_phase);
    let direct = (query_phase - candidate_phase).abs();
    let wrapped = 1.0 - direct;
    let circular = direct.min(wrapped);
    (1.0 - (circular / 0.5)).clamp(0.0, 1.0)
}

#[inline]
pub fn cosine_similarity01(a: &[f32], b: &[f32]) -> HopfResult<f32> {
    ensure_same_dim(a, b)?;
    Ok(dot(a, b).clamp(-1.0, 1.0).max(0.0))
}

fn fiber_kind_match(query: &HopfQuery, candidate: FiberKind) -> f32 {
    if query.fiber_kinds.is_empty() {
        return match query.mode {
            HopfQueryMode::AnchorSearch => 0.5,
            HopfQueryMode::DirectLookup => 0.75,
            HopfQueryMode::ContextualContinuity => contextual_mode_match(candidate),
            HopfQueryMode::CrossDomainSynthesis => synthesis_mode_match(candidate),
            HopfQueryMode::Contradiction => contradiction_mode_match(candidate),
        };
    }

    if query.fiber_kinds.contains(&candidate) {
        1.0
    } else if query
        .fiber_kinds
        .iter()
        .any(|kind| kind.is_compatible_with(candidate))
    {
        0.65
    } else {
        0.0
    }
}

fn contextual_mode_match(kind: FiberKind) -> f32 {
    match kind {
        FiberKind::Temporal | FiberKind::Causal | FiberKind::Evidence | FiberKind::Provenance => {
            0.85
        }
        FiberKind::Relationship | FiberKind::Emotional | FiberKind::Identity => 0.65,
        _ => 0.45,
    }
}

fn synthesis_mode_match(kind: FiberKind) -> f32 {
    match kind {
        FiberKind::Causal
        | FiberKind::Temporal
        | FiberKind::Evidence
        | FiberKind::Provenance
        | FiberKind::Contradiction
        | FiberKind::Identity => 0.85,
        _ => 0.55,
    }
}

fn contradiction_mode_match(kind: FiberKind) -> f32 {
    match kind {
        FiberKind::Contradiction | FiberKind::Evidence | FiberKind::Provenance => 1.0,
        FiberKind::Temporal | FiberKind::Causal | FiberKind::Identity => 0.65,
        _ => 0.30,
    }
}

fn edge_support_score(edge: &HopfFiberEdge) -> f32 {
    let strength = edge.strength.clamp(0.0, 1.0);
    let evidence = source_count_score(edge.evidence_count);
    let cost = edge.traversal_cost.max(0.0);
    let cost_penalty = 1.0 / (1.0 + cost);
    ((0.55 * strength) + (0.35 * evidence) + (0.10 * cost_penalty)).clamp(0.0, 1.0)
}

fn source_count_score(source_count: u32) -> f32 {
    if source_count == 0 {
        0.0
    } else {
        ((source_count as f32).ln_1p() / 8.0_f32.ln_1p()).clamp(0.0, 1.0)
    }
}

fn normalize_or_north_pole(v: &[f32]) -> HopfResult<Vec<f32>> {
    if v.is_empty() {
        return Err(HopfError::EmptyVector);
    }
    let mut norm_sq = 0.0f32;
    let mut all_finite = true;
    for &value in v {
        all_finite &= value.is_finite();
        norm_sq = value.mul_add(value, norm_sq);
    }
    if !all_finite || norm_sq <= DEFAULT_EPS {
        let mut fallback = vec![0.0; v.len()];
        fallback[0] = 1.0;
        return Ok(fallback);
    }
    let inv = norm_sq.sqrt().recip();
    Ok(v.iter().map(|value| value * inv).collect())
}

fn ensure_same_dim(a: &[f32], b: &[f32]) -> HopfResult<()> {
    if a.is_empty() {
        return Err(HopfError::EmptyVector);
    }
    if a.len() != b.len() {
        return Err(HopfError::DimensionMismatch {
            expected: a.len(),
            got: b.len(),
        });
    }
    Ok(())
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
fn validate_non_negative(field: &'static str, value: f32) -> HopfResult<()> {
    if !value.is_finite() || value < 0.0 {
        return Err(HopfError::InvalidConfigField { field, value });
    }
    Ok(())
}

#[inline]
fn compare_score_desc(a: f32, b: f32) -> Ordering {
    b.partial_cmp(&a).unwrap_or(Ordering::Equal)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assert_close(left: f32, right: f32, tol: f32) {
        assert!(
            (left - right).abs() <= tol,
            "expected {left} ~= {right} within {tol}, diff={}",
            (left - right).abs()
        );
    }

    fn kai_anchor() -> HopfAnchor {
        HopfAnchor::new("kai", &[1.0, 0.0, 0.0]).assert_ok()
    }

    fn eureka_anchor() -> HopfAnchor {
        HopfAnchor::new("eureka", &[0.86, 0.14, 0.0]).assert_ok()
    }

    fn kai_causality() -> HopfFiber {
        HopfFiber::new(
            "kai.causality",
            "kai",
            FiberKind::Causal,
            "causality",
            &[0.0, 1.0, 0.0],
            0.20,
        )
        .assert_ok()
    }

    fn kai_domestic() -> HopfFiber {
        HopfFiber::new(
            "kai.domestic",
            "kai",
            FiberKind::Emotional,
            "domestic circle",
            &[0.0, 0.0, 1.0],
            0.72,
        )
        .assert_ok()
    }

    #[test]
    fn anchor_normalizes_and_zero_falls_back_to_north_pole() {
        let anchor = HopfAnchor::new("veir", &[3.0, 4.0]).assert_ok();
        let norm = anchor
            .anchor_vector
            .iter()
            .map(|value| value * value)
            .sum::<f32>()
            .sqrt();
        assert_close(norm, 1.0, 1e-5);

        let zero = HopfAnchor::new("empty", &[0.0, 0.0, 0.0]).assert_ok();
        assert_eq!(zero.anchor_vector, vec![1.0, 0.0, 0.0]);
    }

    #[test]
    fn phase_alignment_wraps_around_orbit() {
        assert_close(phase_alignment_score(0.98, 0.02), 0.92, 1e-5);
        assert_close(phase_alignment_score(0.25, 0.75), 0.0, 1e-5);
        assert_close(phase_alignment_score(0.25, 0.25), 1.0, 1e-5);
    }

    #[test]
    fn same_anchor_correct_fiber_beats_same_anchor_wrong_context() {
        let anchor = kai_anchor();
        let causality = kai_causality();
        let domestic = kai_domestic();
        let query = HopfQuery::new(&[1.0, 0.0, 0.0])
            .assert_ok()
            .with_context_vector(&[0.0, 1.0, 0.0])
            .assert_ok()
            .with_fiber_kinds(vec![FiberKind::Causal])
            .with_phase(0.22)
            .with_mode(HopfQueryMode::DirectLookup);

        let scores = rank_hopf_candidates(
            &query,
            [
                HopfCandidateRef {
                    candidate_id: "causal",
                    anchor: &anchor,
                    fiber: Some(&causality),
                    incoming_edge: None,
                },
                HopfCandidateRef {
                    candidate_id: "domestic",
                    anchor: &anchor,
                    fiber: Some(&domestic),
                    incoming_edge: None,
                },
            ],
            HopfScoreConfig::default(),
        )
        .assert_ok();

        assert_eq!(scores[0].candidate_id, "causal");
        assert!(
            scores[0].score - scores[1].score > 0.55,
            "expected decisive lane separation, got {:?}",
            scores
        );
        assert_eq!(scores[1].fiber_drift_penalty > 0.0, true);
    }

    #[test]
    fn fiber_context_can_beat_near_anchor_with_wrong_lane() {
        let kai = kai_anchor();
        let eureka = eureka_anchor();
        let kai_domestic = kai_domestic();
        let eureka_logs = HopfFiber::new(
            "eureka.logs",
            "eureka",
            FiberKind::Evidence,
            "logs",
            &[0.0, 1.0, 0.0],
            0.30,
        )
        .assert_ok();
        let query = HopfQuery::new(&[0.92, 0.08, 0.0])
            .assert_ok()
            .with_context_vector(&[0.0, 1.0, 0.0])
            .assert_ok()
            .with_fiber_kinds(vec![FiberKind::Evidence])
            .with_phase(0.30)
            .with_mode(HopfQueryMode::ContextualContinuity);

        let scores = rank_hopf_candidates(
            &query,
            [
                HopfCandidateRef {
                    candidate_id: "kai-domestic",
                    anchor: &kai,
                    fiber: Some(&kai_domestic),
                    incoming_edge: None,
                },
                HopfCandidateRef {
                    candidate_id: "eureka-logs",
                    anchor: &eureka,
                    fiber: Some(&eureka_logs),
                    incoming_edge: None,
                },
            ],
            HopfScoreConfig::default(),
        )
        .assert_ok();

        assert_eq!(scores[0].candidate_id, "eureka-logs");
    }

    #[test]
    fn phase_orders_cause_before_aftermath_inside_same_fiber_kind() {
        let anchor = kai_anchor();
        let cause = HopfFiber::new(
            "kai.cause",
            "kai",
            FiberKind::Causal,
            "cause",
            &[0.0, 1.0, 0.0],
            0.12,
        )
        .assert_ok();
        let aftermath = HopfFiber::new(
            "kai.aftermath",
            "kai",
            FiberKind::Causal,
            "aftermath",
            &[0.0, 1.0, 0.0],
            0.66,
        )
        .assert_ok();
        let query = HopfQuery::new(&[1.0, 0.0, 0.0])
            .assert_ok()
            .with_context_vector(&[0.0, 1.0, 0.0])
            .assert_ok()
            .with_fiber_kinds(vec![FiberKind::Causal])
            .with_phase(0.10);

        let scores = rank_hopf_candidates(
            &query,
            [
                HopfCandidateRef {
                    candidate_id: "aftermath",
                    anchor: &anchor,
                    fiber: Some(&aftermath),
                    incoming_edge: None,
                },
                HopfCandidateRef {
                    candidate_id: "cause",
                    anchor: &anchor,
                    fiber: Some(&cause),
                    incoming_edge: None,
                },
            ],
            HopfScoreConfig::default(),
        )
        .assert_ok();

        assert_eq!(scores[0].candidate_id, "cause");
        assert!(scores[0].phase_alignment > scores[1].phase_alignment);
        assert!(scores[1].phase_mismatch_penalty > 0.0);
    }

    #[test]
    fn cross_domain_query_prefers_supported_fiber_bridge() {
        let echo = HopfAnchor::new("echo@root", &[1.0, 0.0, 0.0]).assert_ok();
        let eureka = HopfAnchor::new("eureka", &[0.96, 0.04, 0.0]).assert_ok();
        let unsupported = HopfFiber::new(
            "echo.logs",
            "echo@root",
            FiberKind::Evidence,
            "logs",
            &[0.0, 1.0, 0.0],
            0.40,
        )
        .assert_ok();
        let supported = HopfFiber::new(
            "eureka.causality_witness",
            "eureka",
            FiberKind::Causal,
            "causality witness",
            &[0.0, 1.0, 0.0],
            0.42,
        )
        .assert_ok();
        let mut edge = HopfFiberEdge::new(
            "echo.logs",
            "eureka.causality_witness",
            HopfFiberEdgeKind::ContextShift,
        );
        edge.strength = 0.90;
        edge.evidence_count = 5;
        edge.traversal_cost = 0.25;

        let query = HopfQuery::new(&[1.0, 0.0, 0.0])
            .assert_ok()
            .with_context_vector(&[0.0, 1.0, 0.0])
            .assert_ok()
            .with_fiber_kinds(vec![FiberKind::Causal, FiberKind::Evidence])
            .with_phase(0.41)
            .with_mode(HopfQueryMode::CrossDomainSynthesis);

        let scores = rank_hopf_candidates(
            &query,
            [
                HopfCandidateRef {
                    candidate_id: "unsupported",
                    anchor: &echo,
                    fiber: Some(&unsupported),
                    incoming_edge: None,
                },
                HopfCandidateRef {
                    candidate_id: "supported",
                    anchor: &eureka,
                    fiber: Some(&supported),
                    incoming_edge: Some(&edge),
                },
            ],
            HopfScoreConfig::default(),
        )
        .assert_ok();

        assert_eq!(scores[0].candidate_id, "supported");
        assert!(scores[1].unsupported_jump_penalty > 0.0);
        assert!(scores[0].graph_edge_strength > 0.75);
    }

    #[test]
    fn dimension_mismatch_is_rejected() {
        let anchor = HopfAnchor::new("kai", &[1.0, 0.0]).assert_ok();
        let query = HopfQuery::new(&[1.0, 0.0, 0.0]).assert_ok();
        let err = score_hopf_candidate(
            &query,
            HopfCandidateRef {
                candidate_id: "kai",
                anchor: &anchor,
                fiber: None,
                incoming_edge: None,
            },
            HopfScoreConfig::default(),
        )
        .unwrap_err();
        assert!(matches!(err, HopfError::DimensionMismatch { .. }));
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
