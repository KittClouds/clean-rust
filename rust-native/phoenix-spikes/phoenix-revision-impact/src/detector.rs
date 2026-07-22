use std::collections::{BTreeMap, BTreeSet};

use compact_str::CompactString;
use hashbrown::HashMap;
use phoenix_types::{
    ConstraintKind, CoveragePlane, DependencyClass, GraphTruthDigest, ImpactClassification,
    SceneId, StoryInterval,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::truth_adapter::requirement_plane;
use crate::{
    causal_ripple_search, AdapterCoverageStatus, AdapterTruthPlane, ConstraintAtom,
    ConstraintGraph, ConstraintProjectionReceipt, CounterfactualGraphView, EvidenceRef,
    GraphGeneration, ImpactPath, RevisionIdentityMap, RevisionRequirementSidecar, RippleConfig,
    RippleError, RippleRunReceipt, REVISION_IDENTITY_SCHEMA,
};

#[path = "detector_digest.rs"]
mod digest;
use digest::digest_report;

pub const REVISION_IMPACT_REPORT_SCHEMA: &str = "phoenix-revision-impact-report/v2";

const COVERAGE_PLANES: [CoveragePlane; 10] = [
    CoveragePlane::Identity,
    CoveragePlane::Temporal,
    CoveragePlane::Belief,
    CoveragePlane::Lifecycle,
    CoveragePlane::Possession,
    CoveragePlane::Location,
    CoveragePlane::State,
    CoveragePlane::Relationship,
    CoveragePlane::Capability,
    CoveragePlane::Causal,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoverageStatus {
    Covered,
    Partial,
    Unavailable,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoveragePlaneReceipt {
    pub plane: CoveragePlane,
    pub status: CoverageStatus,
    pub projected_constraints: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoverageCertificate {
    pub planes: Vec<CoveragePlaneReceipt>,
    pub required_planes: Vec<CoveragePlane>,
    pub missing_required_planes: Vec<CoveragePlane>,
    pub classification_supported: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConstraintImpact {
    pub constraint_id: CompactString,
    pub kind: ConstraintKind,
    pub dependency_class: DependencyClass,
    pub valid_interval: StoryInterval,
    pub evidence: Vec<EvidenceRef>,
    pub confidence_millis: u16,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionImpact {
    pub scene_id: SceneId,
    pub classification: ImpactClassification,
    pub score_millis: u16,
    pub violated_constraints: Vec<ConstraintImpact>,
    pub support_loss_constraints: Vec<ConstraintImpact>,
    pub causal_paths: Vec<ImpactPath>,
    pub coverage: CoverageCertificate,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ModelOverlayKind {
    Retrieval,
    GraphSpotlight,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ModelQueryMode {
    Dynamic,
    Cached,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ModelRankedNode {
    pub node_id: CompactString,
    pub node_type: CompactString,
    pub rank: u32,
    pub raw_score: f32,
    pub score_millis: u16,
    pub evidence_targets: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ModelRelevanceOverlay {
    pub model_id: CompactString,
    pub generation: GraphGeneration,
    pub kind: ModelOverlayKind,
    pub query_mode: ModelQueryMode,
    pub start_node_ids: Vec<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_node_type: Option<CompactString>,
    pub ranked_nodes: Vec<ModelRankedNode>,
    pub full_latency_micros: u64,
    pub peak_resident_bytes: u64,
    pub presentation_only: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ModelIntegrationState {
    Disabled,
    ExperimentalPresentationOnly,
}

/// Deliberate capability token for isolated experiments. Product code has no
/// implicit/default path for attaching model output to an impact report.
#[derive(Clone, Copy, Debug)]
pub struct ExperimentalModelOverlayPermit {
    _private: (),
}

impl ExperimentalModelOverlayPermit {
    pub const fn for_isolated_harness() -> Self {
        Self { _private: () }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IdentityCoverageKind {
    SameRevision,
    CrossRevision,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ImpactRunReceipt {
    pub schema_version: CompactString,
    pub generation: GraphGeneration,
    pub base_digest: GraphTruthDigest,
    pub mutation_digest: GraphTruthDigest,
    pub identity_coverage_kind: IdentityCoverageKind,
    pub ripple_config: RippleConfig,
    pub projection: ConstraintProjectionReceipt,
    pub ripple: RippleRunReceipt,
    pub broken_impacts: usize,
    pub suspicious_impacts: usize,
    pub unknown_impacts: usize,
    pub coverage_warning_planes: Vec<CoveragePlane>,
    pub model_integration_state: ModelIntegrationState,
    pub model_overlay_count: usize,
    pub report_digest: GraphTruthDigest,
    pub no_truth_writes: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionImpactReport {
    pub authoritative_impacts: Vec<RevisionImpact>,
    pub deterministic_receipt: ImpactRunReceipt,
    pub model_overlays: Vec<ModelRelevanceOverlay>,
}

#[derive(Debug, Error)]
pub enum ModelOverlayError {
    #[error("model overlay generation does not match the authoritative report")]
    GenerationMismatch,
    #[error("model overlay must remain presentation-only")]
    NotPresentationOnly,
    #[error("model overlay ranks must be contiguous and one-based")]
    InvalidRanks,
}

pub fn attach_model_overlays(
    report: &mut RevisionImpactReport,
    mut overlays: Vec<ModelRelevanceOverlay>,
    _permit: ExperimentalModelOverlayPermit,
) -> Result<(), ModelOverlayError> {
    for overlay in &overlays {
        if overlay.generation != report.deterministic_receipt.generation {
            return Err(ModelOverlayError::GenerationMismatch);
        }
        if !overlay.presentation_only {
            return Err(ModelOverlayError::NotPresentationOnly);
        }
        if overlay
            .ranked_nodes
            .iter()
            .enumerate()
            .any(|(index, node)| node.rank != index as u32 + 1)
        {
            return Err(ModelOverlayError::InvalidRanks);
        }
    }
    overlays.sort_by(|left, right| {
        left.model_id
            .cmp(&right.model_id)
            .then_with(|| left.kind.cmp(&right.kind))
            .then_with(|| left.query_mode.cmp(&right.query_mode))
            .then_with(|| left.target_node_type.cmp(&right.target_node_type))
    });
    report.deterministic_receipt.model_integration_state =
        ModelIntegrationState::ExperimentalPresentationOnly;
    report.deterministic_receipt.model_overlay_count = overlays.len();
    report.model_overlays = overlays;
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SceneCoverageRequest {
    pub scene_id: SceneId,
    pub required_planes: Vec<CoveragePlane>,
    pub unavailable_planes: Vec<CoveragePlane>,
}

#[derive(Clone)]
struct CanonicalCoverageRequest {
    required_planes: Vec<CoveragePlane>,
    unavailable_planes: Vec<CoveragePlane>,
}

#[derive(Clone, Copy)]
pub enum IdentityCoverage<'a> {
    SameRevision,
    CrossRevision(&'a RevisionIdentityMap),
}

impl IdentityCoverage<'_> {
    const fn kind(self) -> IdentityCoverageKind {
        match self {
            Self::SameRevision => IdentityCoverageKind::SameRevision,
            Self::CrossRevision(_) => IdentityCoverageKind::CrossRevision,
        }
    }
}

pub struct RevisionDetectorInput<'a, 'graph> {
    pub overlay: &'a CounterfactualGraphView<'graph>,
    pub constraint_graph: &'a ConstraintGraph,
    pub requirements: &'a RevisionRequirementSidecar,
    pub projection_receipt: &'a ConstraintProjectionReceipt,
    pub identity_coverage: IdentityCoverage<'a>,
    pub coverage_requests: &'a [SceneCoverageRequest],
}

#[derive(Debug, Error)]
pub enum RevisionDetectorError {
    #[error("detector generation mismatch")]
    GenerationMismatch,
    #[error("constraint projection receipt does not describe the supplied graph")]
    ProjectionReceiptMismatch,
    #[error("identity map schema mismatch")]
    IdentitySchemaMismatch,
    #[error("duplicate coverage request for {0}")]
    DuplicateCoverageRequest(CompactString),
    #[error("coverage request for {0} has no required planes")]
    EmptyCoverageRequest(CompactString),
    #[error("coverage request for {0} marks a plane unavailable without requiring it")]
    UnavailablePlaneNotRequired(CompactString),
    #[error("constraint {0} has no authoritative requirement")]
    MissingRequirement(CompactString),
    #[error("constraint {0} is absent from the projected graph")]
    MissingConstraint(CompactString),
    #[error("impact {scene_id} depends on unavailable plane {plane:?}")]
    ImpactWithoutCoverage {
        scene_id: CompactString,
        plane: CoveragePlane,
    },
    #[error(transparent)]
    Ripple(#[from] RippleError),
}

pub fn detect_revision_impacts(
    input: RevisionDetectorInput<'_, '_>,
    config: RippleConfig,
) -> Result<RevisionImpactReport, RevisionDetectorError> {
    validate_input(&input)?;
    let requests = canonical_requests(input.coverage_requests)?;
    let atoms = input
        .constraint_graph
        .atoms()
        .iter()
        .map(|atom| (atom.constraint_id.as_str(), atom))
        .collect::<HashMap<_, _>>();
    let requirement_planes = input
        .requirements
        .requirements
        .iter()
        .map(|requirement| {
            (
                requirement.constraint_id.as_str(),
                requirement_plane(requirement),
            )
        })
        .collect::<HashMap<_, _>>();
    for atom in input.constraint_graph.atoms() {
        if !requirement_planes.contains_key(atom.constraint_id.as_str()) {
            return Err(RevisionDetectorError::MissingRequirement(
                atom.constraint_id.clone(),
            ));
        }
    }

    let ripple = causal_ripple_search(
        input.overlay,
        input.constraint_graph,
        input.requirements,
        config,
    )?;
    let mut seen_scenes = BTreeSet::new();
    let mut impacts = Vec::with_capacity(ripple.impacts.len() + requests.len());
    for impact in ripple.impacts {
        let scene_id = SceneId(impact.dependent_id.clone());
        seen_scenes.insert(impact.dependent_id.clone());
        let violated_constraints = constraint_impacts(&impact.violated_constraints, &atoms)?;
        let support_loss_constraints =
            constraint_impacts(&impact.support_loss_constraints, &atoms)?;
        let decisive_planes = constraint_planes(
            impact
                .violated_constraints
                .iter()
                .chain(&impact.support_loss_constraints),
            &requirement_planes,
        )?;
        let mut required_planes = decisive_planes.clone();
        let unavailable_planes = requests
            .get(scene_id.0.as_str())
            .map_or(&[][..], |request| request.unavailable_planes.as_slice());
        if let Some(requested) = requests.get(scene_id.0.as_str()) {
            required_planes.extend(requested.required_planes.iter().copied());
        }
        canonicalize_planes(&mut required_planes);
        let coverage = coverage_certificate(
            &input,
            &scene_id,
            required_planes,
            &decisive_planes,
            unavailable_planes,
        );
        if let Some(plane) = decisive_planes
            .iter()
            .find(|plane| !plane_is_covered(&coverage.planes, **plane))
        {
            return Err(RevisionDetectorError::ImpactWithoutCoverage {
                scene_id: scene_id.0,
                plane: *plane,
            });
        }
        impacts.push(RevisionImpact {
            scene_id,
            classification: impact.classification,
            score_millis: impact.score_millis,
            violated_constraints,
            support_loss_constraints,
            causal_paths: impact.causal_paths,
            coverage,
        });
    }

    for (scene_id, request) in &requests {
        if seen_scenes.contains(scene_id) {
            continue;
        }
        let scene_id = SceneId(scene_id.clone());
        let coverage = coverage_certificate(
            &input,
            &scene_id,
            request.required_planes.clone(),
            &[],
            &request.unavailable_planes,
        );
        if coverage.missing_required_planes.is_empty() {
            continue;
        }
        impacts.push(RevisionImpact {
            scene_id,
            classification: ImpactClassification::Unknown,
            score_millis: 0,
            violated_constraints: Vec::new(),
            support_loss_constraints: Vec::new(),
            causal_paths: Vec::new(),
            coverage,
        });
    }
    impacts.sort_unstable_by(impact_order);

    let broken_impacts = count_classification(&impacts, ImpactClassification::Broken);
    let suspicious_impacts = count_classification(&impacts, ImpactClassification::Suspicious);
    let unknown_impacts = count_classification(&impacts, ImpactClassification::Unknown);
    let coverage_warning_planes = coverage_warnings(&input, &impacts);
    let report_digest = digest_report(
        input.overlay.base_generation,
        input.overlay.receipt.base_digest,
        input.overlay.receipt.mutation_digest,
        &impacts,
        &requests,
        config,
    );
    Ok(RevisionImpactReport {
        authoritative_impacts: impacts,
        deterministic_receipt: ImpactRunReceipt {
            schema_version: REVISION_IMPACT_REPORT_SCHEMA.into(),
            generation: input.overlay.base_generation,
            base_digest: input.overlay.receipt.base_digest,
            mutation_digest: input.overlay.receipt.mutation_digest,
            identity_coverage_kind: input.identity_coverage.kind(),
            ripple_config: config,
            projection: input.projection_receipt.clone(),
            ripple: ripple.receipt,
            broken_impacts,
            suspicious_impacts,
            unknown_impacts,
            coverage_warning_planes,
            model_integration_state: ModelIntegrationState::Disabled,
            model_overlay_count: 0,
            report_digest,
            no_truth_writes: true,
        },
        model_overlays: Vec::new(),
    })
}

fn validate_input(input: &RevisionDetectorInput<'_, '_>) -> Result<(), RevisionDetectorError> {
    let generation = input.overlay.base_generation;
    if input.constraint_graph.generation() != generation
        || input.requirements.generation != generation
        || input.projection_receipt.generation != generation
    {
        return Err(RevisionDetectorError::GenerationMismatch);
    }
    let hard = input
        .constraint_graph
        .atoms()
        .iter()
        .filter(|atom| atom.strength == DependencyClass::HardRequirement)
        .count();
    if input.projection_receipt.projected_constraints != input.constraint_graph.atoms().len()
        || input.projection_receipt.hard_constraints != hard
        || input.projection_receipt.soft_constraints
            != input.constraint_graph.atoms().len().saturating_sub(hard)
        || input
            .projection_receipt
            .planes
            .iter()
            .map(|plane| plane.projected_constraints)
            .sum::<usize>()
            != input.constraint_graph.atoms().len()
    {
        return Err(RevisionDetectorError::ProjectionReceiptMismatch);
    }
    if let IdentityCoverage::CrossRevision(identity) = input.identity_coverage {
        if identity.schema_version.as_str() != REVISION_IDENTITY_SCHEMA {
            return Err(RevisionDetectorError::IdentitySchemaMismatch);
        }
    }
    Ok(())
}

fn canonical_requests(
    requests: &[SceneCoverageRequest],
) -> Result<BTreeMap<CompactString, CanonicalCoverageRequest>, RevisionDetectorError> {
    let mut out = BTreeMap::new();
    for request in requests {
        if request.required_planes.is_empty() {
            return Err(RevisionDetectorError::UnavailablePlaneNotRequired(
                request.scene_id.0.clone(),
            ));
        }
        let mut planes = request.required_planes.clone();
        canonicalize_planes(&mut planes);
        let mut unavailable_planes = request.unavailable_planes.clone();
        canonicalize_planes(&mut unavailable_planes);
        if unavailable_planes
            .iter()
            .any(|plane| !planes.contains(plane))
        {
            return Err(RevisionDetectorError::EmptyCoverageRequest(
                request.scene_id.0.clone(),
            ));
        }
        if out
            .insert(
                request.scene_id.0.clone(),
                CanonicalCoverageRequest {
                    required_planes: planes,
                    unavailable_planes,
                },
            )
            .is_some()
        {
            return Err(RevisionDetectorError::DuplicateCoverageRequest(
                request.scene_id.0.clone(),
            ));
        }
    }
    Ok(out)
}

fn constraint_impacts(
    ids: &[CompactString],
    atoms: &HashMap<&str, &ConstraintAtom>,
) -> Result<Vec<ConstraintImpact>, RevisionDetectorError> {
    ids.iter()
        .map(|id| {
            let atom = atoms
                .get(id.as_str())
                .ok_or_else(|| RevisionDetectorError::MissingConstraint(id.clone()))?;
            let mut evidence = atom.evidence.iter().cloned().collect::<Vec<_>>();
            evidence.sort_unstable_by(|left, right| {
                left.evidence_id
                    .cmp(&right.evidence_id)
                    .then_with(|| left.document_id.cmp(&right.document_id))
                    .then_with(|| {
                        left.source_range
                            .map(|range| (range.start, range.end))
                            .cmp(&right.source_range.map(|range| (range.start, range.end)))
                    })
            });
            evidence.dedup();
            Ok(ConstraintImpact {
                constraint_id: id.clone(),
                kind: atom.kind,
                dependency_class: atom.strength,
                valid_interval: atom.valid_interval,
                evidence,
                confidence_millis: atom.confidence_millis,
            })
        })
        .collect()
}

fn constraint_planes<'a>(
    ids: impl Iterator<Item = &'a CompactString>,
    planes: &HashMap<&str, AdapterTruthPlane>,
) -> Result<Vec<CoveragePlane>, RevisionDetectorError> {
    let mut out = Vec::new();
    for id in ids {
        let plane = planes
            .get(id.as_str())
            .copied()
            .ok_or_else(|| RevisionDetectorError::MissingRequirement(id.clone()))?;
        out.push(adapter_plane(plane));
    }
    canonicalize_planes(&mut out);
    Ok(out)
}

fn coverage_certificate(
    input: &RevisionDetectorInput<'_, '_>,
    scene_id: &SceneId,
    mut required_planes: Vec<CoveragePlane>,
    decisive_planes: &[CoveragePlane],
    unavailable_planes: &[CoveragePlane],
) -> CoverageCertificate {
    canonicalize_planes(&mut required_planes);
    let planes = COVERAGE_PLANES
        .into_iter()
        .map(|plane| CoveragePlaneReceipt {
            plane,
            status: if unavailable_planes.contains(&plane) {
                CoverageStatus::Unavailable
            } else {
                plane_status(input, scene_id, plane)
            },
            projected_constraints: projected_constraints(input.projection_receipt, plane),
        })
        .collect::<Vec<_>>();
    let missing_required_planes = required_planes
        .iter()
        .copied()
        .filter(|plane| !plane_is_covered(&planes, *plane))
        .collect();
    let classification_supported = !decisive_planes.is_empty()
        && decisive_planes
            .iter()
            .all(|plane| plane_is_covered(&planes, *plane));
    CoverageCertificate {
        planes,
        required_planes,
        missing_required_planes,
        classification_supported,
    }
}

fn plane_status(
    input: &RevisionDetectorInput<'_, '_>,
    scene_id: &SceneId,
    plane: CoveragePlane,
) -> CoverageStatus {
    if plane == CoveragePlane::Identity {
        return identity_status(input.identity_coverage, scene_id.0.as_str());
    }
    input
        .projection_receipt
        .planes
        .iter()
        .find(|row| adapter_plane(row.plane) == plane)
        .map_or(CoverageStatus::Unavailable, |row| match row.status {
            AdapterCoverageStatus::Covered => CoverageStatus::Covered,
            AdapterCoverageStatus::Unavailable => CoverageStatus::Unavailable,
        })
}

fn identity_status(identity: IdentityCoverage<'_>, scene_id: &str) -> CoverageStatus {
    let IdentityCoverage::CrossRevision(identity) = identity else {
        return CoverageStatus::Covered;
    };
    let ambiguous =
        identity.ambiguous.iter().any(|row| {
            row.subject_id == scene_id || row.candidate_ids.iter().any(|id| id == scene_id)
        }) || identity.splits.iter().any(|row| {
            row.previous_id == scene_id || row.current_ids.iter().any(|id| id == scene_id)
        }) || identity.merges.iter().any(|row| {
            row.current_id == scene_id || row.previous_ids.iter().any(|id| id == scene_id)
        });
    if ambiguous {
        return CoverageStatus::Partial;
    }
    if identity
        .scene_matches
        .iter()
        .any(|row| row.previous_id == scene_id || row.current_id == scene_id)
    {
        return CoverageStatus::Covered;
    }
    CoverageStatus::Unavailable
}

fn projected_constraints(receipt: &ConstraintProjectionReceipt, plane: CoveragePlane) -> usize {
    receipt
        .planes
        .iter()
        .find(|row| adapter_plane(row.plane) == plane)
        .map_or(0, |row| row.projected_constraints)
}

const fn adapter_plane(plane: AdapterTruthPlane) -> CoveragePlane {
    match plane {
        AdapterTruthPlane::Belief => CoveragePlane::Belief,
        AdapterTruthPlane::Temporal => CoveragePlane::Temporal,
        AdapterTruthPlane::Lifecycle => CoveragePlane::Lifecycle,
        AdapterTruthPlane::Possession => CoveragePlane::Possession,
        AdapterTruthPlane::Location => CoveragePlane::Location,
        AdapterTruthPlane::State => CoveragePlane::State,
        AdapterTruthPlane::Relationship => CoveragePlane::Relationship,
        AdapterTruthPlane::Capability => CoveragePlane::Capability,
        AdapterTruthPlane::Causal => CoveragePlane::Causal,
    }
}

fn coverage_warnings(
    input: &RevisionDetectorInput<'_, '_>,
    impacts: &[RevisionImpact],
) -> Vec<CoveragePlane> {
    let mut warnings = input
        .projection_receipt
        .planes
        .iter()
        .filter(|row| row.status != AdapterCoverageStatus::Covered)
        .map(|row| adapter_plane(row.plane))
        .collect::<Vec<_>>();
    warnings.extend(impacts.iter().flat_map(|impact| {
        impact
            .coverage
            .planes
            .iter()
            .filter(|row| row.status != CoverageStatus::Covered)
            .map(|row| row.plane)
    }));
    canonicalize_planes(&mut warnings);
    warnings
}

fn plane_is_covered(rows: &[CoveragePlaneReceipt], plane: CoveragePlane) -> bool {
    rows.iter()
        .any(|row| row.plane == plane && row.status == CoverageStatus::Covered)
}

fn canonicalize_planes(planes: &mut Vec<CoveragePlane>) {
    planes.sort_unstable_by_key(|plane| plane_rank(*plane));
    planes.dedup();
}

const fn plane_rank(plane: CoveragePlane) -> u8 {
    match plane {
        CoveragePlane::Identity => 0,
        CoveragePlane::Temporal => 1,
        CoveragePlane::Belief => 2,
        CoveragePlane::Lifecycle => 3,
        CoveragePlane::Possession => 4,
        CoveragePlane::Location => 5,
        CoveragePlane::State => 6,
        CoveragePlane::Relationship => 7,
        CoveragePlane::Capability => 8,
        CoveragePlane::Causal => 9,
    }
}

fn impact_order(left: &RevisionImpact, right: &RevisionImpact) -> std::cmp::Ordering {
    classification_rank(left.classification)
        .cmp(&classification_rank(right.classification))
        .then_with(|| right.score_millis.cmp(&left.score_millis))
        .then_with(|| left.scene_id.cmp(&right.scene_id))
}

const fn classification_rank(classification: ImpactClassification) -> u8 {
    match classification {
        ImpactClassification::Broken => 0,
        ImpactClassification::Suspicious => 1,
        ImpactClassification::Unknown => 2,
    }
}

fn count_classification(impacts: &[RevisionImpact], expected: ImpactClassification) -> usize {
    impacts
        .iter()
        .filter(|impact| impact.classification == expected)
        .count()
}

#[cfg(test)]
#[path = "detector_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "detector_shortrun_tests.rs"]
mod shortrun_tests;
