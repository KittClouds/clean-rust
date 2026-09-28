//! Evidence graph cone adapter.
//!
//! This module operationalizes the hybrid-space hierarchy cone system.
//!
//! Mental model:
//! - extraction proposes possible relations
//! - hybrid_space evaluates whether the proposed parent/child edge has the right shape
//! - this adapter turns cone verdicts into graph write decisions and repair queue items
//!
//! The adapter is intentionally geometry-first and storage-agnostic. The graph
//! compiler can consume `EdgeWrite` and `RepairQueueItem` without needing to know
//! cone math.

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::hybrid_space::{
    evaluate_relation_cone, ConeEvaluation, ConeVerdict, HierarchyRelationKind, HybridPoint,
    HybridSpaceError,
};

#[derive(Debug, Error)]
pub enum ConeAdapterError {
    #[error(transparent)]
    HybridSpace(#[from] HybridSpaceError),

    #[error("invalid support field {field}: {value}")]
    InvalidSupportField { field: &'static str, value: f32 },

    #[error("invalid adapter weights: geometry={geometry}, support={support}")]
    InvalidAdapterWeights { geometry: f32, support: f32 },
}

pub type ConeAdapterResult<T> = Result<T, ConeAdapterError>;

/// Relation labels emitted by evidence/candidate graph generation.
///
/// These are deliberately more operational than `HierarchyRelationKind`.
/// Extraction cares about evidence semantics; the cone layer cares about
/// hierarchy geometry. `hierarchy_relation_kind()` is the bridge.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum MentionGraphRelationKind {
    IsA,
    InstanceOf,
    EntityTypedAs,
    Generalizes,
    Specializes,
    TaxonomicParentOf,
    HasPart,
    ContainsPart,
    DocumentContains,
    ClaimSupportedBy,
    EvidenceFor,
    Causes,
    Enables,
    Preconditions,
    TemporallyContains,
    EventBefore,
    EventAfter,
    ProjectContainsTask,
    SchemaContains,
    StateTransitionsTo,
    VersionParentOf,
    DerivedInto,
    ProvenanceScopes,
    Owns,
    Controls,
    HasMember,
    TopicContains,
    Entails,
    ModalityScopes,
    RelatedTo,
    Mentions,
    CoOccursWith,
    CustomHierarchy(HierarchyRelationKind),
    CustomAssociative,
}

impl MentionGraphRelationKind {
    /// Returns the hierarchy profile to use for cone evaluation.
    ///
    /// `None` means the relation is intentionally non-hierarchical and should
    /// be written as an associative/lateral edge without cone validation.
    pub fn hierarchy_relation_kind(self) -> Option<HierarchyRelationKind> {
        match self {
            Self::IsA => Some(HierarchyRelationKind::TypeHierarchy),
            Self::InstanceOf | Self::EntityTypedAs => Some(HierarchyRelationKind::EntityType),
            Self::Generalizes | Self::Specializes => Some(HierarchyRelationKind::Abstraction),
            Self::TaxonomicParentOf => Some(HierarchyRelationKind::Taxonomy),
            Self::HasPart | Self::ContainsPart => Some(HierarchyRelationKind::PartWhole),
            Self::DocumentContains => Some(HierarchyRelationKind::DocumentContainment),
            Self::ClaimSupportedBy | Self::EvidenceFor => {
                Some(HierarchyRelationKind::EvidenceSupport)
            }
            Self::Causes | Self::Enables | Self::Preconditions => {
                Some(HierarchyRelationKind::CausalDependency)
            }
            Self::TemporallyContains => Some(HierarchyRelationKind::TemporalContainment),
            Self::EventBefore | Self::EventAfter => Some(HierarchyRelationKind::EventSequence),
            Self::ProjectContainsTask => Some(HierarchyRelationKind::ProjectTask),
            Self::SchemaContains => Some(HierarchyRelationKind::SchemaContainment),
            Self::StateTransitionsTo => Some(HierarchyRelationKind::StateTransition),
            Self::VersionParentOf | Self::DerivedInto => {
                Some(HierarchyRelationKind::VersionLineage)
            }
            Self::ProvenanceScopes => Some(HierarchyRelationKind::ProvenanceScope),
            Self::Owns | Self::Controls => Some(HierarchyRelationKind::Ownership),
            Self::HasMember => Some(HierarchyRelationKind::Membership),
            Self::TopicContains => Some(HierarchyRelationKind::TopicCluster),
            Self::Entails => Some(HierarchyRelationKind::ClaimEntailment),
            Self::ModalityScopes => Some(HierarchyRelationKind::ModalityScope),
            Self::CustomHierarchy(kind) => Some(kind),
            Self::RelatedTo | Self::Mentions | Self::CoOccursWith | Self::CustomAssociative => None,
        }
    }

    #[inline]
    pub fn is_hierarchical(self) -> bool {
        self.hierarchy_relation_kind().is_some()
    }
}

/// Lightweight evidence/support summary from extraction.
///
/// The cone geometry should not blindly trust extraction confidence, but the
/// final graph write decision should still account for evidence density and
/// compatibility checks.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct CandidateSupport {
    /// Confidence from extraction/linking/reranking in [0, 1].
    pub extraction_confidence: f32,

    /// Number of distinct evidence records supporting this relation.
    pub evidence_count: u32,

    /// Number of source spans that directly mention or imply this relation.
    pub source_span_count: u32,

    /// Optional temporal compatibility gate from the temporal lane.
    pub temporal_compatible: Option<bool>,

    /// Optional modality compatibility gate, such as observed/reported/inferred/planned.
    pub modality_compatible: Option<bool>,

    /// Optional provenance compatibility gate from source/session/document scope.
    pub provenance_compatible: Option<bool>,
}

impl Default for CandidateSupport {
    fn default() -> Self {
        Self {
            extraction_confidence: 0.5,
            evidence_count: 0,
            source_span_count: 0,
            temporal_compatible: None,
            modality_compatible: None,
            provenance_compatible: None,
        }
    }
}

impl CandidateSupport {
    pub fn validate(self) -> ConeAdapterResult<Self> {
        validate_unit_interval("extraction_confidence", self.extraction_confidence)?;
        Ok(self)
    }

    /// A bounded support score in [0, 1].
    ///
    /// Evidence saturates quickly on purpose. Five repeated spans should not
    /// outweigh bad geometry forever; they should only make a valid edge easier
    /// to commit instead of keeping it provisional.
    pub fn support_score(&self) -> ConeAdapterResult<f32> {
        let support = self.validate()?;

        let extraction = support.extraction_confidence;
        let evidence_density = ((support.evidence_count as f32) / 4.0).clamp(0.0, 1.0);
        let span_density = ((support.source_span_count as f32) / 6.0).clamp(0.0, 1.0);
        let evidence_score = (0.60 * evidence_density) + (0.40 * span_density);
        let compatibility_score = support.compatibility_score();

        Ok(
            ((0.60 * extraction) + (0.25 * evidence_score) + (0.15 * compatibility_score))
                .clamp(0.0, 1.0),
        )
    }

    fn compatibility_score(&self) -> f32 {
        let checks = [
            self.temporal_compatible,
            self.modality_compatible,
            self.provenance_compatible,
        ];

        let mut count = 0.0f32;
        let mut total = 0.0f32;

        for check in checks.into_iter().flatten() {
            count += 1.0;
            if check {
                total += 1.0;
            }
        }

        if count <= f32::EPSILON {
            0.5
        } else {
            total / count
        }
    }
}

/// Borrowed candidate relation proposed by evidence graph compilation.
///
/// `parent_id -> child_id` is the proposed structural direction. If extraction
/// guessed the wrong direction, the cone layer will emit `LikelyReversedEdge`.
#[derive(Clone, Debug)]
pub struct MentionGraphCandidateRef<'a, NodeId> {
    pub parent_id: NodeId,
    pub child_id: NodeId,
    pub parent_point: &'a HybridPoint,
    pub child_point: &'a HybridPoint,
    pub relation_kind: MentionGraphRelationKind,
    pub support: CandidateSupport,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct ConeAdapterConfig {
    /// Minimum final confidence for durable structural writes.
    pub min_commit_confidence: f32,

    /// Minimum final confidence for provisional hierarchy writes.
    pub min_provisional_confidence: f32,

    /// Final confidence geometry weight.
    pub geometry_weight: f32,

    /// Final confidence extraction/evidence support weight.
    pub support_weight: f32,

    /// Whether reversed edges should become repair items for flip+retest.
    pub auto_flip_reversed: bool,

    /// Whether contradictory geometry should be quarantined instead of rejected.
    pub quarantine_contradictions: bool,
}

impl Default for ConeAdapterConfig {
    fn default() -> Self {
        Self {
            min_commit_confidence: 0.72,
            min_provisional_confidence: 0.48,
            geometry_weight: 0.70,
            support_weight: 0.30,
            auto_flip_reversed: true,
            quarantine_contradictions: true,
        }
    }
}

impl ConeAdapterConfig {
    pub fn validate(self) -> ConeAdapterResult<Self> {
        validate_unit_interval("min_commit_confidence", self.min_commit_confidence)?;
        validate_unit_interval(
            "min_provisional_confidence",
            self.min_provisional_confidence,
        )?;

        if self.min_provisional_confidence > self.min_commit_confidence {
            return Err(ConeAdapterError::InvalidSupportField {
                field: "min_provisional_confidence > min_commit_confidence",
                value: self.min_provisional_confidence,
            });
        }

        if !self.geometry_weight.is_finite()
            || !self.support_weight.is_finite()
            || self.geometry_weight < 0.0
            || self.support_weight < 0.0
            || self.geometry_weight + self.support_weight <= f32::EPSILON
        {
            return Err(ConeAdapterError::InvalidAdapterWeights {
                geometry: self.geometry_weight,
                support: self.support_weight,
            });
        }

        Ok(self)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum GraphWriteAction {
    CommitStructuralEdge,
    CommitProvisionalEdge,
    PreserveMultiParentDag,
    CommitLateralEdge,
    CommitTopicalEdge,
    CommitEvidenceEdge,
    CommitAssociativeEdge,
    RejectHierarchy,
    FlipAndRetest,
    EnqueueIntermediateDiscovery,
    QuarantineForRepair,
    Skip,
}

impl GraphWriteAction {
    #[inline]
    pub fn writes_edge(self) -> bool {
        matches!(
            self,
            Self::CommitStructuralEdge
                | Self::CommitProvisionalEdge
                | Self::PreserveMultiParentDag
                | Self::CommitLateralEdge
                | Self::CommitTopicalEdge
                | Self::CommitEvidenceEdge
                | Self::CommitAssociativeEdge
        )
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum MentionGraphEdgeKind {
    StructuralHierarchy,
    ProvisionalHierarchy,
    MultiParentHierarchy,
    LateralSemantic,
    TopicalAssociation,
    EvidenceSupport,
    AssociativeMention,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum RepairPriority {
    Low,
    Medium,
    High,
    Critical,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum RepairQueueKind {
    FlipAndRetest,
    DiscoverIntermediateNode,
    ContradictoryGeometry,
    TooShallow,
    RejectedHierarchy,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RepairQueueItem<NodeId> {
    pub kind: RepairQueueKind,
    pub priority: RepairPriority,
    pub parent_id: NodeId,
    pub child_id: NodeId,
    pub relation_kind: MentionGraphRelationKind,
    pub hierarchy_kind: Option<HierarchyRelationKind>,
    pub confidence: f32,
    pub evaluation: Option<ConeEvaluation>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EdgeWrite<NodeId> {
    pub from_id: NodeId,
    pub to_id: NodeId,
    pub relation_kind: MentionGraphRelationKind,
    pub hierarchy_kind: Option<HierarchyRelationKind>,
    pub edge_kind: MentionGraphEdgeKind,
    pub confidence: f32,
    pub provisional: bool,
    pub cone_verdict: Option<ConeVerdict>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct GraphWriteDecision<NodeId> {
    pub parent_id: NodeId,
    pub child_id: NodeId,
    pub relation_kind: MentionGraphRelationKind,
    pub hierarchy_kind: Option<HierarchyRelationKind>,
    pub action: GraphWriteAction,
    pub edge_kind: Option<MentionGraphEdgeKind>,
    pub confidence: f32,
    pub support_score: f32,
    pub evaluation: Option<ConeEvaluation>,
    pub repair: Option<RepairQueueItem<NodeId>>,
}

impl<NodeId: Clone> GraphWriteDecision<NodeId> {
    pub fn edge_write(&self) -> Option<EdgeWrite<NodeId>> {
        let edge_kind = self.edge_kind?;

        if !self.action.writes_edge() {
            return None;
        }

        Some(EdgeWrite {
            from_id: self.parent_id.clone(),
            to_id: self.child_id.clone(),
            relation_kind: self.relation_kind,
            hierarchy_kind: self.hierarchy_kind,
            edge_kind,
            confidence: self.confidence,
            provisional: matches!(self.action, GraphWriteAction::CommitProvisionalEdge),
            cone_verdict: self.evaluation.as_ref().map(|eval| eval.verdict),
        })
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PlacementSummary<NodeId> {
    pub child_id: NodeId,
    pub strong_parent_count: usize,
    pub provisional_parent_count: usize,
    pub lateral_edge_count: usize,
    pub evidence_edge_count: usize,
    pub repair_count: usize,
    pub rejected_count: usize,
    pub decisions: Vec<GraphWriteDecision<NodeId>>,
}

impl<NodeId: Clone> PlacementSummary<NodeId> {
    pub fn edge_writes(&self) -> Vec<EdgeWrite<NodeId>> {
        self.decisions
            .iter()
            .filter_map(GraphWriteDecision::edge_write)
            .collect()
    }

    pub fn repair_items(&self) -> Vec<RepairQueueItem<NodeId>> {
        self.decisions
            .iter()
            .filter_map(|decision| decision.repair.clone())
            .collect()
    }
}

#[derive(Clone, Copy, Debug)]
pub struct ConeRelationClassifier {
    config: ConeAdapterConfig,
}

impl Default for ConeRelationClassifier {
    fn default() -> Self {
        Self {
            config: ConeAdapterConfig::default(),
        }
    }
}

impl ConeRelationClassifier {
    pub fn new(config: ConeAdapterConfig) -> ConeAdapterResult<Self> {
        Ok(Self {
            config: config.validate()?,
        })
    }

    pub fn config(&self) -> ConeAdapterConfig {
        self.config
    }

    /// Classify a single candidate into a graph write decision.
    pub fn classify<NodeId: Clone>(
        &self,
        candidate: MentionGraphCandidateRef<'_, NodeId>,
    ) -> ConeAdapterResult<GraphWriteDecision<NodeId>> {
        let support_score = candidate.support.support_score()?;
        let Some(hierarchy_kind) = candidate.relation_kind.hierarchy_relation_kind() else {
            return Ok(self.non_hierarchical_decision(candidate, support_score));
        };

        let evaluation = evaluate_relation_cone(
            candidate.parent_point,
            candidate.child_point,
            hierarchy_kind,
        )?;

        let confidence = final_confidence(evaluation.fit_score, support_score, self.config)?;
        let action = self.action_for_evaluation(candidate.relation_kind, &evaluation, confidence);
        let edge_kind = edge_kind_for_action(action);
        let repair =
            self.repair_for_action(&candidate, hierarchy_kind, &evaluation, action, confidence);

        Ok(GraphWriteDecision {
            parent_id: candidate.parent_id,
            child_id: candidate.child_id,
            relation_kind: candidate.relation_kind,
            hierarchy_kind: Some(hierarchy_kind),
            action,
            edge_kind,
            confidence,
            support_score,
            evaluation: Some(evaluation),
            repair,
        })
    }

    /// Classify a batch of candidates for one child and summarize the placement.
    ///
    /// This preserves DAG truth: multiple strong structural parents become
    /// `PreserveMultiParentDag` writes instead of being collapsed to one winner.
    pub fn classify_child_placement<'a, NodeId: Clone + PartialEq>(
        &self,
        child_id: NodeId,
        candidates: impl IntoIterator<Item = MentionGraphCandidateRef<'a, NodeId>>,
    ) -> ConeAdapterResult<PlacementSummary<NodeId>> {
        let mut decisions = Vec::new();

        for candidate in candidates {
            decisions.push(self.classify(candidate)?);
        }

        mark_multi_parent_dag(&mut decisions);
        decisions.sort_by(|a, b| compare_confidence_desc(a.confidence, b.confidence));

        let mut strong_parent_count = 0usize;
        let mut provisional_parent_count = 0usize;
        let mut lateral_edge_count = 0usize;
        let mut evidence_edge_count = 0usize;
        let mut repair_count = 0usize;
        let mut rejected_count = 0usize;

        for decision in &decisions {
            match decision.action {
                GraphWriteAction::CommitStructuralEdge
                | GraphWriteAction::PreserveMultiParentDag => {
                    strong_parent_count += 1;
                }
                GraphWriteAction::CommitProvisionalEdge => provisional_parent_count += 1,
                GraphWriteAction::CommitLateralEdge | GraphWriteAction::CommitTopicalEdge => {
                    lateral_edge_count += 1;
                }
                GraphWriteAction::CommitEvidenceEdge => evidence_edge_count += 1,
                GraphWriteAction::FlipAndRetest
                | GraphWriteAction::EnqueueIntermediateDiscovery
                | GraphWriteAction::QuarantineForRepair => repair_count += 1,
                GraphWriteAction::RejectHierarchy => rejected_count += 1,
                GraphWriteAction::CommitAssociativeEdge | GraphWriteAction::Skip => {}
            }
        }

        Ok(PlacementSummary {
            child_id,
            strong_parent_count,
            provisional_parent_count,
            lateral_edge_count,
            evidence_edge_count,
            repair_count,
            rejected_count,
            decisions,
        })
    }

    fn non_hierarchical_decision<NodeId: Clone>(
        &self,
        candidate: MentionGraphCandidateRef<'_, NodeId>,
        support_score: f32,
    ) -> GraphWriteDecision<NodeId> {
        let confidence = support_score;
        let should_write = confidence >= self.config.min_provisional_confidence;
        let action = if should_write {
            GraphWriteAction::CommitAssociativeEdge
        } else {
            GraphWriteAction::Skip
        };

        GraphWriteDecision {
            parent_id: candidate.parent_id,
            child_id: candidate.child_id,
            relation_kind: candidate.relation_kind,
            hierarchy_kind: None,
            action,
            edge_kind: if should_write {
                Some(MentionGraphEdgeKind::AssociativeMention)
            } else {
                None
            },
            confidence,
            support_score,
            evaluation: None,
            repair: None,
        }
    }

    fn action_for_evaluation(
        &self,
        relation_kind: MentionGraphRelationKind,
        evaluation: &ConeEvaluation,
        confidence: f32,
    ) -> GraphWriteAction {
        match evaluation.verdict {
            ConeVerdict::StrongParentChild => {
                if confidence >= self.config.min_commit_confidence {
                    GraphWriteAction::CommitStructuralEdge
                } else if confidence >= self.config.min_provisional_confidence {
                    GraphWriteAction::CommitProvisionalEdge
                } else {
                    GraphWriteAction::RejectHierarchy
                }
            }
            ConeVerdict::WeakParentChild => {
                if confidence >= self.config.min_provisional_confidence {
                    GraphWriteAction::CommitProvisionalEdge
                } else {
                    GraphWriteAction::RejectHierarchy
                }
            }
            ConeVerdict::MultiParentCandidate => {
                if confidence >= self.config.min_commit_confidence {
                    GraphWriteAction::PreserveMultiParentDag
                } else if confidence >= self.config.min_provisional_confidence {
                    GraphWriteAction::CommitProvisionalEdge
                } else {
                    GraphWriteAction::RejectHierarchy
                }
            }
            ConeVerdict::SiblingOrCousin => {
                if confidence >= self.config.min_provisional_confidence {
                    GraphWriteAction::CommitLateralEdge
                } else {
                    GraphWriteAction::RejectHierarchy
                }
            }
            ConeVerdict::TopicalAssociation => {
                if confidence >= self.config.min_provisional_confidence {
                    GraphWriteAction::CommitTopicalEdge
                } else {
                    GraphWriteAction::RejectHierarchy
                }
            }
            ConeVerdict::EvidenceOnly => {
                if matches!(
                    relation_kind.hierarchy_relation_kind(),
                    Some(HierarchyRelationKind::EvidenceSupport)
                ) && confidence >= self.config.min_provisional_confidence
                {
                    GraphWriteAction::CommitEvidenceEdge
                } else if confidence >= self.config.min_provisional_confidence {
                    GraphWriteAction::CommitLateralEdge
                } else {
                    GraphWriteAction::RejectHierarchy
                }
            }
            ConeVerdict::TooShallow => GraphWriteAction::RejectHierarchy,
            ConeVerdict::LikelyReversedEdge => {
                if self.config.auto_flip_reversed {
                    GraphWriteAction::FlipAndRetest
                } else {
                    GraphWriteAction::RejectHierarchy
                }
            }
            ConeVerdict::OutsideCone => GraphWriteAction::RejectHierarchy,
            ConeVerdict::NeedsIntermediateNode => GraphWriteAction::EnqueueIntermediateDiscovery,
            ConeVerdict::ContradictoryGeometry => {
                if self.config.quarantine_contradictions {
                    GraphWriteAction::QuarantineForRepair
                } else {
                    GraphWriteAction::RejectHierarchy
                }
            }
        }
    }

    fn repair_for_action<NodeId: Clone>(
        &self,
        candidate: &MentionGraphCandidateRef<'_, NodeId>,
        hierarchy_kind: HierarchyRelationKind,
        evaluation: &ConeEvaluation,
        action: GraphWriteAction,
        confidence: f32,
    ) -> Option<RepairQueueItem<NodeId>> {
        let (kind, priority) = match action {
            GraphWriteAction::FlipAndRetest => {
                (RepairQueueKind::FlipAndRetest, RepairPriority::High)
            }
            GraphWriteAction::EnqueueIntermediateDiscovery => (
                RepairQueueKind::DiscoverIntermediateNode,
                RepairPriority::Medium,
            ),
            GraphWriteAction::QuarantineForRepair => (
                RepairQueueKind::ContradictoryGeometry,
                RepairPriority::Critical,
            ),
            GraphWriteAction::RejectHierarchy if evaluation.verdict == ConeVerdict::TooShallow => {
                (RepairQueueKind::TooShallow, RepairPriority::Low)
            }
            GraphWriteAction::RejectHierarchy if evaluation.needs_repair() => {
                (RepairQueueKind::RejectedHierarchy, RepairPriority::Medium)
            }
            _ => return None,
        };

        Some(RepairQueueItem {
            kind,
            priority,
            parent_id: candidate.parent_id.clone(),
            child_id: candidate.child_id.clone(),
            relation_kind: candidate.relation_kind,
            hierarchy_kind: Some(hierarchy_kind),
            confidence,
            evaluation: Some(evaluation.clone()),
        })
    }
}

fn mark_multi_parent_dag<NodeId: Clone + PartialEq>(decisions: &mut [GraphWriteDecision<NodeId>]) {
    let structural_count = decisions
        .iter()
        .filter(|decision| {
            matches!(
                decision.action,
                GraphWriteAction::CommitStructuralEdge | GraphWriteAction::PreserveMultiParentDag
            )
        })
        .count();

    if structural_count <= 1 {
        return;
    }

    for decision in decisions.iter_mut() {
        if matches!(decision.action, GraphWriteAction::CommitStructuralEdge) {
            decision.action = GraphWriteAction::PreserveMultiParentDag;
            decision.edge_kind = Some(MentionGraphEdgeKind::MultiParentHierarchy);
            if let Some(evaluation) = decision.evaluation.as_mut() {
                evaluation.verdict = ConeVerdict::MultiParentCandidate;
            }
        }
    }
}

#[inline]
fn edge_kind_for_action(action: GraphWriteAction) -> Option<MentionGraphEdgeKind> {
    match action {
        GraphWriteAction::CommitStructuralEdge => Some(MentionGraphEdgeKind::StructuralHierarchy),
        GraphWriteAction::CommitProvisionalEdge => Some(MentionGraphEdgeKind::ProvisionalHierarchy),
        GraphWriteAction::PreserveMultiParentDag => {
            Some(MentionGraphEdgeKind::MultiParentHierarchy)
        }
        GraphWriteAction::CommitLateralEdge => Some(MentionGraphEdgeKind::LateralSemantic),
        GraphWriteAction::CommitTopicalEdge => Some(MentionGraphEdgeKind::TopicalAssociation),
        GraphWriteAction::CommitEvidenceEdge => Some(MentionGraphEdgeKind::EvidenceSupport),
        GraphWriteAction::CommitAssociativeEdge => Some(MentionGraphEdgeKind::AssociativeMention),
        GraphWriteAction::RejectHierarchy
        | GraphWriteAction::FlipAndRetest
        | GraphWriteAction::EnqueueIntermediateDiscovery
        | GraphWriteAction::QuarantineForRepair
        | GraphWriteAction::Skip => None,
    }
}

#[inline]
fn final_confidence(
    geometry_score: f32,
    support_score: f32,
    config: ConeAdapterConfig,
) -> ConeAdapterResult<f32> {
    let config = config.validate()?;
    validate_unit_interval("geometry_score", geometry_score)?;
    validate_unit_interval("support_score", support_score)?;

    let total = config.geometry_weight + config.support_weight;
    let geometry_weight = config.geometry_weight / total;
    let support_weight = config.support_weight / total;

    Ok(((geometry_weight * geometry_score) + (support_weight * support_score)).clamp(0.0, 1.0))
}

#[inline]
fn compare_confidence_desc(a: f32, b: f32) -> core::cmp::Ordering {
    match b.partial_cmp(&a) {
        Some(ordering) => ordering,
        None => core::cmp::Ordering::Equal,
    }
}

#[inline]
fn validate_unit_interval(field: &'static str, value: f32) -> ConeAdapterResult<()> {
    if !value.is_finite() || !(0.0..=1.0).contains(&value) {
        return Err(ConeAdapterError::InvalidSupportField { field, value });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hybrid_space::{HybridPoint, HybridSpaceConfig};

    fn point(angle_rad: f32, depth: f32) -> HybridPoint {
        let embedding = [angle_rad.cos(), angle_rad.sin()];
        HybridPoint::from_embedding_and_depth(&embedding, depth, HybridSpaceConfig::default())
            .assert_ok()
    }

    fn strong_support() -> CandidateSupport {
        CandidateSupport {
            extraction_confidence: 0.95,
            evidence_count: 4,
            source_span_count: 6,
            temporal_compatible: Some(true),
            modality_compatible: Some(true),
            provenance_compatible: Some(true),
        }
    }

    #[test]
    fn adapter_commits_strong_structural_edge() {
        let classifier = ConeRelationClassifier::default();
        let parent = point(0.0, 1.0);
        let child = point(0.0, 2.0);

        let decision = classifier
            .classify(MentionGraphCandidateRef {
                parent_id: "parent",
                child_id: "child",
                parent_point: &parent,
                child_point: &child,
                relation_kind: MentionGraphRelationKind::IsA,
                support: strong_support(),
            })
            .assert_ok();

        assert_eq!(decision.action, GraphWriteAction::CommitStructuralEdge);
        assert_eq!(
            decision.edge_kind,
            Some(MentionGraphEdgeKind::StructuralHierarchy)
        );
        assert!(decision.edge_write().is_some());
    }

    #[test]
    fn adapter_preserves_non_hierarchical_association() {
        let classifier = ConeRelationClassifier::default();
        let parent = point(0.0, 1.0);
        let child = point(1.4, 1.0);

        let decision = classifier
            .classify(MentionGraphCandidateRef {
                parent_id: "a",
                child_id: "b",
                parent_point: &parent,
                child_point: &child,
                relation_kind: MentionGraphRelationKind::Mentions,
                support: strong_support(),
            })
            .assert_ok();

        assert_eq!(decision.action, GraphWriteAction::CommitAssociativeEdge);
        assert_eq!(decision.hierarchy_kind, None);
        assert_eq!(
            decision.edge_kind,
            Some(MentionGraphEdgeKind::AssociativeMention)
        );
    }

    #[test]
    fn adapter_sends_reversed_edges_to_repair() {
        let classifier = ConeRelationClassifier::default();
        let parent = point(0.0, 4.0);
        let child = point(0.0, 1.0);

        let decision = classifier
            .classify(MentionGraphCandidateRef {
                parent_id: "too_deep_parent",
                child_id: "too_shallow_child",
                parent_point: &parent,
                child_point: &child,
                relation_kind: MentionGraphRelationKind::IsA,
                support: strong_support(),
            })
            .assert_ok();

        assert_eq!(decision.action, GraphWriteAction::FlipAndRetest);
        assert_eq!(
            decision.repair.as_ref().map(|item| item.kind),
            Some(RepairQueueKind::FlipAndRetest)
        );
    }

    #[test]
    fn adapter_turns_sibling_geometry_into_lateral_edge() {
        let classifier = ConeRelationClassifier::default();
        let parent = point(0.0, 2.0);
        let child = point(0.12, 2.0);

        let decision = classifier
            .classify(MentionGraphCandidateRef {
                parent_id: "dragon",
                child_id: "phoenix",
                parent_point: &parent,
                child_point: &child,
                relation_kind: MentionGraphRelationKind::IsA,
                support: strong_support(),
            })
            .assert_ok();

        assert_eq!(decision.action, GraphWriteAction::CommitLateralEdge);
        assert_eq!(
            decision.edge_kind,
            Some(MentionGraphEdgeKind::LateralSemantic)
        );
    }

    #[test]
    fn adapter_enqueues_intermediate_discovery() {
        let classifier = ConeRelationClassifier::default();
        let parent = point(0.0, 1.0);
        let child = point(0.0, 100.0);

        let decision = classifier
            .classify(MentionGraphCandidateRef {
                parent_id: "animal",
                child_id: "named_blue_storm_dragon",
                parent_point: &parent,
                child_point: &child,
                relation_kind: MentionGraphRelationKind::IsA,
                support: strong_support(),
            })
            .assert_ok();

        assert_eq!(
            decision.action,
            GraphWriteAction::EnqueueIntermediateDiscovery
        );
        assert_eq!(
            decision.repair.as_ref().map(|item| item.kind),
            Some(RepairQueueKind::DiscoverIntermediateNode)
        );
    }

    #[test]
    fn adapter_marks_multiple_strong_parents_as_dag_edges() {
        let classifier = ConeRelationClassifier::default();
        let parent_a = point(0.0, 1.0);
        let parent_b = point(0.08, 1.0);
        let child = point(0.04, 2.0);

        let summary = classifier
            .classify_child_placement(
                "child",
                vec![
                    MentionGraphCandidateRef {
                        parent_id: "parent_a",
                        child_id: "child",
                        parent_point: &parent_a,
                        child_point: &child,
                        relation_kind: MentionGraphRelationKind::Generalizes,
                        support: strong_support(),
                    },
                    MentionGraphCandidateRef {
                        parent_id: "parent_b",
                        child_id: "child",
                        parent_point: &parent_b,
                        child_point: &child,
                        relation_kind: MentionGraphRelationKind::Generalizes,
                        support: strong_support(),
                    },
                ],
            )
            .assert_ok();

        assert_eq!(summary.strong_parent_count, 2);
        assert!(summary.decisions.iter().all(|decision| {
            decision.action == GraphWriteAction::PreserveMultiParentDag
                && decision.edge_kind == Some(MentionGraphEdgeKind::MultiParentHierarchy)
        }));
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
