//! Evidence graph hardening layer.
//!
//! This module sits after `graph_adapter`.
//!
//! Mental model:
//! - the adapter decides what should happen for one candidate relation
//! - this hardening layer decides how durable that action is over time
//! - durable graph storage stays geometry-agnostic
//! - graph writes gain lifecycle, hysteresis, repair dedupe, and calibration stats
//!
//! The implementation is deliberately in-memory and storage-agnostic. Use it as
//! the reference policy engine; the OverGraph patch layer owns durable writes.

use std::collections::HashMap;
use std::hash::Hash;

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::graph_adapter::{
    GraphWriteAction, GraphWriteDecision, MentionGraphEdgeKind, MentionGraphRelationKind,
    PlacementSummary, RepairPriority, RepairQueueItem, RepairQueueKind,
};
use crate::hybrid_space::{ConeEvaluation, ConeVerdict, HierarchyRelationKind};

#[derive(Debug, Error)]
pub enum GraphHardeningError {
    #[error("invalid hardening config field {field}: {value}")]
    InvalidConfigField { field: &'static str, value: f32 },
}

pub type GraphHardeningResult<T> = Result<T, GraphHardeningError>;

/// Lifecycle for a graph edge produced by extraction + cone validation.
///
/// This is intentionally small and copyable. It gives the graph memory without
/// forcing the storage layer to understand cone math.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum EdgeLifecycle {
    /// Seen or proposed, but not yet trusted enough for normal graph traversal.
    Candidate,

    /// Usable with caution. Good for UI, debugging, and low-stakes retrieval.
    Provisional,

    /// Durable enough for structural graph operations.
    Confirmed,

    /// Previously useful edge is now under pressure from contradictory geometry
    /// or repeated failed observations.
    Contested,

    /// Retained for audit/history, but excluded from normal traversal.
    Deprecated,

    /// Rejected by policy. Can be revived only by stronger future evidence.
    Rejected,

    /// High-risk geometry. Requires repair/review before normal use.
    Quarantined,
}

impl EdgeLifecycle {
    #[inline]
    pub fn is_active(self) -> bool {
        matches!(self, Self::Provisional | Self::Confirmed | Self::Contested)
    }

    #[inline]
    pub fn is_structural_traversable(self) -> bool {
        matches!(self, Self::Confirmed)
    }

    #[inline]
    pub fn is_terminal_without_manual_repair(self) -> bool {
        matches!(self, Self::Quarantined)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum GraphMutationKind {
    InsertedEdge,
    UpdatedEdge,
    PromotedEdge,
    DemotedEdge,
    ContestedEdge,
    RejectedEdge,
    QuarantinedEdge,
    RepairQueued,
    RepairUpdated,
    Noop,
}

/// Compact reason code for fast logging and metrics.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum HardeningReason {
    NewEdge,
    Reinforced,
    PromotedByConfidence,
    HysteresisKeptConfirmed,
    HysteresisKeptProvisional,
    RepeatedRejections,
    ReversedGeometry,
    MissingIntermediate,
    ContradictoryGeometry,
    RejectedByAdapter,
    AssociativeWrite,
    EvidenceWrite,
    NoWritableAction,
}

/// Tunable hardening policy.
///
/// Defaults bias toward stability: strong edges do not thrash because one later
/// observation disagrees.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct HardeningConfig {
    /// Confidence needed to promote an active edge to Confirmed.
    pub promote_confirmed_confidence: f32,

    /// Confidence needed to revive a Rejected edge back to Provisional.
    pub revive_rejected_confidence: f32,

    /// Number of reject/repair observations needed before a Confirmed edge is
    /// demoted to Contested.
    pub confirmed_rejection_hysteresis: u32,

    /// Number of reject observations needed before a Provisional edge is moved
    /// to Rejected.
    pub provisional_rejection_hysteresis: u32,

    /// Exponential moving average alpha for confidence tracking.
    pub confidence_ema_alpha: f32,

    /// Store full cone diagnostics on each edge. Default false to avoid memory
    /// bloat on large ingestion runs.
    pub retain_last_edge_evaluation: bool,

    /// Store full cone diagnostics on repair records. Default false to keep the
    /// repair queue compact.
    pub retain_repair_evaluation: bool,
}

impl Default for HardeningConfig {
    fn default() -> Self {
        Self {
            promote_confirmed_confidence: 0.78,
            revive_rejected_confidence: 0.92,
            confirmed_rejection_hysteresis: 3,
            provisional_rejection_hysteresis: 2,
            confidence_ema_alpha: 0.25,
            retain_last_edge_evaluation: false,
            retain_repair_evaluation: false,
        }
    }
}

impl HardeningConfig {
    pub fn validate(self) -> GraphHardeningResult<Self> {
        validate_unit_interval(
            "promote_confirmed_confidence",
            self.promote_confirmed_confidence,
        )?;
        validate_unit_interval(
            "revive_rejected_confidence",
            self.revive_rejected_confidence,
        )?;
        validate_unit_interval("confidence_ema_alpha", self.confidence_ema_alpha)?;
        Ok(self)
    }
}

/// Stable key for edge dedupe and lifecycle updates.
///
/// `edge_kind` is intentionally not part of the key. The same logical relation
/// may mature from provisional hierarchy to confirmed hierarchy without changing
/// identity.
#[derive(Clone, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub struct EdgeKey<NodeId> {
    pub from_id: NodeId,
    pub to_id: NodeId,
    pub relation_kind: MentionGraphRelationKind,
    pub hierarchy_kind: Option<HierarchyRelationKind>,
}

impl<NodeId: Clone> EdgeKey<NodeId> {
    pub fn from_decision(decision: &GraphWriteDecision<NodeId>) -> Self {
        Self {
            from_id: decision.parent_id.clone(),
            to_id: decision.child_id.clone(),
            relation_kind: decision.relation_kind,
            hierarchy_kind: decision.hierarchy_kind,
        }
    }
}

/// Stable key for repair queue dedupe.
#[derive(Clone, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub struct RepairKey<NodeId> {
    pub kind: RepairQueueKind,
    pub parent_id: NodeId,
    pub child_id: NodeId,
    pub relation_kind: MentionGraphRelationKind,
    pub hierarchy_kind: Option<HierarchyRelationKind>,
}

impl<NodeId: Clone> RepairKey<NodeId> {
    pub fn from_item(item: &RepairQueueItem<NodeId>) -> Self {
        Self {
            kind: item.kind,
            parent_id: item.parent_id.clone(),
            child_id: item.child_id.clone(),
            relation_kind: item.relation_kind,
            hierarchy_kind: item.hierarchy_kind,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EdgeCounters {
    pub observations: u64,
    pub confirmations: u64,
    pub provisional_observations: u64,
    pub lateral_observations: u64,
    pub evidence_observations: u64,
    pub associative_observations: u64,
    pub rejections: u64,
    pub repair_observations: u64,
    pub contradictions: u64,
    pub reversals: u64,
    pub intermediate_requests: u64,
    pub max_confidence: f32,
    pub last_confidence: f32,
    pub ema_confidence: f32,
}

impl Default for EdgeCounters {
    fn default() -> Self {
        Self {
            observations: 0,
            confirmations: 0,
            provisional_observations: 0,
            lateral_observations: 0,
            evidence_observations: 0,
            associative_observations: 0,
            rejections: 0,
            repair_observations: 0,
            contradictions: 0,
            reversals: 0,
            intermediate_requests: 0,
            max_confidence: 0.0,
            last_confidence: 0.0,
            ema_confidence: 0.0,
        }
    }
}

impl EdgeCounters {
    fn observe(&mut self, action: GraphWriteAction, confidence: f32, ema_alpha: f32) {
        self.observations = self.observations.saturating_add(1);
        self.last_confidence = confidence.clamp(0.0, 1.0);
        self.max_confidence = self.max_confidence.max(self.last_confidence);

        if self.observations == 1 {
            self.ema_confidence = self.last_confidence;
        } else {
            let alpha = ema_alpha.clamp(0.0, 1.0);
            self.ema_confidence += alpha * (self.last_confidence - self.ema_confidence);
        }

        match action {
            GraphWriteAction::CommitStructuralEdge | GraphWriteAction::PreserveMultiParentDag => {
                self.confirmations = self.confirmations.saturating_add(1);
            }
            GraphWriteAction::CommitProvisionalEdge => {
                self.provisional_observations = self.provisional_observations.saturating_add(1);
            }
            GraphWriteAction::CommitLateralEdge | GraphWriteAction::CommitTopicalEdge => {
                self.lateral_observations = self.lateral_observations.saturating_add(1);
            }
            GraphWriteAction::CommitEvidenceEdge => {
                self.evidence_observations = self.evidence_observations.saturating_add(1);
            }
            GraphWriteAction::CommitAssociativeEdge => {
                self.associative_observations = self.associative_observations.saturating_add(1);
            }
            GraphWriteAction::RejectHierarchy | GraphWriteAction::Skip => {
                self.rejections = self.rejections.saturating_add(1);
            }
            GraphWriteAction::FlipAndRetest => {
                self.repair_observations = self.repair_observations.saturating_add(1);
                self.reversals = self.reversals.saturating_add(1);
            }
            GraphWriteAction::EnqueueIntermediateDiscovery => {
                self.repair_observations = self.repair_observations.saturating_add(1);
                self.intermediate_requests = self.intermediate_requests.saturating_add(1);
            }
            GraphWriteAction::QuarantineForRepair => {
                self.repair_observations = self.repair_observations.saturating_add(1);
                self.contradictions = self.contradictions.saturating_add(1);
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EdgeRecord<NodeId> {
    pub key: EdgeKey<NodeId>,
    pub edge_kind: MentionGraphEdgeKind,
    pub lifecycle: EdgeLifecycle,
    pub confidence: f32,
    pub support_score: f32,
    pub last_action: GraphWriteAction,
    pub last_verdict: Option<ConeVerdict>,
    pub first_seen_seq: u64,
    pub last_seen_seq: u64,
    pub version: u64,
    pub counters: EdgeCounters,
    pub last_evaluation: Option<ConeEvaluation>,
}

impl<NodeId: Clone> EdgeRecord<NodeId> {
    fn new(
        decision: &GraphWriteDecision<NodeId>,
        edge_kind: MentionGraphEdgeKind,
        lifecycle: EdgeLifecycle,
        seq: u64,
        config: HardeningConfig,
    ) -> Self {
        let mut counters = EdgeCounters::default();
        counters.observe(
            decision.action,
            decision.confidence,
            config.confidence_ema_alpha,
        );

        Self {
            key: EdgeKey::from_decision(decision),
            edge_kind,
            lifecycle,
            confidence: decision.confidence,
            support_score: decision.support_score,
            last_action: decision.action,
            last_verdict: decision
                .evaluation
                .as_ref()
                .map(|evaluation| evaluation.verdict),
            first_seen_seq: seq,
            last_seen_seq: seq,
            version: 1,
            counters,
            last_evaluation: retained_evaluation(decision, config.retain_last_edge_evaluation),
        }
    }

    fn update(
        &mut self,
        decision: &GraphWriteDecision<NodeId>,
        edge_kind: MentionGraphEdgeKind,
        target_lifecycle: EdgeLifecycle,
        seq: u64,
        config: HardeningConfig,
    ) -> (EdgeLifecycle, EdgeLifecycle, HardeningReason) {
        let previous = self.lifecycle;
        self.counters.observe(
            decision.action,
            decision.confidence,
            config.confidence_ema_alpha,
        );

        let (next, reason) = transition_lifecycle(
            previous,
            target_lifecycle,
            decision.action,
            decision.confidence,
            &self.counters,
            config,
        );

        self.edge_kind = edge_kind;
        self.lifecycle = next;
        self.confidence = self.confidence.max(decision.confidence);
        self.support_score = self.support_score.max(decision.support_score);
        self.last_action = decision.action;
        self.last_verdict = decision
            .evaluation
            .as_ref()
            .map(|evaluation| evaluation.verdict);
        self.last_seen_seq = seq;
        self.version = self.version.saturating_add(1);
        self.last_evaluation = retained_evaluation(decision, config.retain_last_edge_evaluation);

        (previous, next, reason)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RepairQueueRecord<NodeId> {
    pub key: RepairKey<NodeId>,
    pub item: RepairQueueItem<NodeId>,
    pub occurrences: u64,
    pub max_confidence: f32,
    pub first_seen_seq: u64,
    pub last_seen_seq: u64,
    pub resolved: bool,
}

impl<NodeId: Clone> RepairQueueRecord<NodeId> {
    fn new(item: RepairQueueItem<NodeId>, seq: u64) -> Self {
        let key = RepairKey::from_item(&item);
        let confidence = item.confidence;
        Self {
            key,
            item,
            occurrences: 1,
            max_confidence: confidence,
            first_seen_seq: seq,
            last_seen_seq: seq,
            resolved: false,
        }
    }

    fn reinforce(&mut self, item: RepairQueueItem<NodeId>, seq: u64) {
        self.occurrences = self.occurrences.saturating_add(1);
        self.max_confidence = self.max_confidence.max(item.confidence);
        self.last_seen_seq = seq;
        self.resolved = false;

        if priority_rank(item.priority) >= priority_rank(self.item.priority) {
            self.item.priority = item.priority;
        }

        if item.confidence >= self.item.confidence {
            self.item.confidence = item.confidence;
            self.item.evaluation = item.evaluation;
        }
    }
}

/// Compact mutation response. This avoids cloning full edge/repair records back
/// to the caller on the hot path.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AppliedGraphMutation<NodeId> {
    pub seq: u64,
    pub action: GraphWriteAction,
    pub kind: GraphMutationKind,
    pub edge_key: Option<EdgeKey<NodeId>>,
    pub repair_key: Option<RepairKey<NodeId>>,
    pub previous_lifecycle: Option<EdgeLifecycle>,
    pub new_lifecycle: Option<EdgeLifecycle>,
    pub confidence: f32,
    pub reason: HardeningReason,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct RelationCalibrationStats {
    pub observations: u64,
    pub committed: u64,
    pub provisional: u64,
    pub lateral: u64,
    pub evidence: u64,
    pub associative: u64,
    pub rejected: u64,
    pub repairs: u64,
    pub avg_confidence: f32,
    pub avg_support_score: f32,
    pub avg_fit_score: f32,
    pub avg_angular_margin_rad: f32,
    pub avg_radial_delta: f32,
}

impl RelationCalibrationStats {
    fn observe<NodeId>(&mut self, decision: &GraphWriteDecision<NodeId>) {
        self.observations = self.observations.saturating_add(1);

        match decision.action {
            GraphWriteAction::CommitStructuralEdge | GraphWriteAction::PreserveMultiParentDag => {
                self.committed = self.committed.saturating_add(1);
            }
            GraphWriteAction::CommitProvisionalEdge => {
                self.provisional = self.provisional.saturating_add(1);
            }
            GraphWriteAction::CommitLateralEdge | GraphWriteAction::CommitTopicalEdge => {
                self.lateral = self.lateral.saturating_add(1);
            }
            GraphWriteAction::CommitEvidenceEdge => {
                self.evidence = self.evidence.saturating_add(1);
            }
            GraphWriteAction::CommitAssociativeEdge => {
                self.associative = self.associative.saturating_add(1);
            }
            GraphWriteAction::RejectHierarchy | GraphWriteAction::Skip => {
                self.rejected = self.rejected.saturating_add(1);
            }
            GraphWriteAction::FlipAndRetest
            | GraphWriteAction::EnqueueIntermediateDiscovery
            | GraphWriteAction::QuarantineForRepair => {
                self.repairs = self.repairs.saturating_add(1);
            }
        }

        update_average(
            &mut self.avg_confidence,
            self.observations,
            decision.confidence,
        );
        update_average(
            &mut self.avg_support_score,
            self.observations,
            decision.support_score,
        );

        if let Some(evaluation) = &decision.evaluation {
            update_average(
                &mut self.avg_fit_score,
                self.observations,
                evaluation.fit_score,
            );
            update_average(
                &mut self.avg_angular_margin_rad,
                self.observations,
                evaluation.angular_margin_rad,
            );
            update_average(
                &mut self.avg_radial_delta,
                self.observations,
                evaluation.radial_delta,
            );
        }
    }
}

/// Low-cost calibration accumulator for profile hardening.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct ConeCalibrationStats {
    pub total_decisions: u64,
    pub by_relation: HashMap<MentionGraphRelationKind, RelationCalibrationStats>,
    pub by_hierarchy: HashMap<HierarchyRelationKind, RelationCalibrationStats>,
    pub by_action: HashMap<GraphWriteAction, u64>,
    pub by_verdict: HashMap<ConeVerdict, u64>,
}

impl ConeCalibrationStats {
    pub fn record_decision<NodeId>(&mut self, decision: &GraphWriteDecision<NodeId>) {
        self.total_decisions = self.total_decisions.saturating_add(1);

        self.by_relation
            .entry(decision.relation_kind)
            .or_default()
            .observe(decision);

        if let Some(hierarchy_kind) = decision.hierarchy_kind {
            self.by_hierarchy
                .entry(hierarchy_kind)
                .or_default()
                .observe(decision);
        }

        *self.by_action.entry(decision.action).or_insert(0) += 1;

        if let Some(evaluation) = &decision.evaluation {
            *self.by_verdict.entry(evaluation.verdict).or_insert(0) += 1;
        }
    }
}

/// In-memory hardening store.
///
/// This is intentionally simple and fast:
/// - one HashMap for edge lifecycle records
/// - one HashMap for deduped repairs
/// - one calibration accumulator
/// - monotonically increasing sequence numbers instead of timestamps
pub struct InMemoryGraphHardener<NodeId> {
    config: HardeningConfig,
    seq: u64,
    edges: HashMap<EdgeKey<NodeId>, EdgeRecord<NodeId>>,
    repairs: HashMap<RepairKey<NodeId>, RepairQueueRecord<NodeId>>,
    stats: ConeCalibrationStats,
}

impl<NodeId> Default for InMemoryGraphHardener<NodeId>
where
    NodeId: Clone + Eq + Hash,
{
    fn default() -> Self {
        Self {
            config: HardeningConfig::default(),
            seq: 0,
            edges: HashMap::new(),
            repairs: HashMap::new(),
            stats: ConeCalibrationStats::default(),
        }
    }
}

impl<NodeId> InMemoryGraphHardener<NodeId>
where
    NodeId: Clone + Eq + Hash,
{
    pub fn new(config: HardeningConfig) -> GraphHardeningResult<Self> {
        Ok(Self {
            config: config.validate()?,
            seq: 0,
            edges: HashMap::new(),
            repairs: HashMap::new(),
            stats: ConeCalibrationStats::default(),
        })
    }

    pub fn with_capacity(
        config: HardeningConfig,
        edge_capacity: usize,
        repair_capacity: usize,
    ) -> GraphHardeningResult<Self> {
        Ok(Self {
            config: config.validate()?,
            seq: 0,
            edges: HashMap::with_capacity(edge_capacity),
            repairs: HashMap::with_capacity(repair_capacity),
            stats: ConeCalibrationStats::default(),
        })
    }

    #[inline]
    pub fn config(&self) -> HardeningConfig {
        self.config
    }

    #[inline]
    pub fn sequence(&self) -> u64 {
        self.seq
    }

    #[inline]
    pub fn edge_count(&self) -> usize {
        self.edges.len()
    }

    #[inline]
    pub fn repair_count(&self) -> usize {
        self.repairs.len()
    }

    #[inline]
    pub fn stats(&self) -> &ConeCalibrationStats {
        &self.stats
    }

    #[inline]
    pub fn edges(&self) -> &HashMap<EdgeKey<NodeId>, EdgeRecord<NodeId>> {
        &self.edges
    }

    #[inline]
    pub fn repairs(&self) -> &HashMap<RepairKey<NodeId>, RepairQueueRecord<NodeId>> {
        &self.repairs
    }

    pub fn reserve(&mut self, additional_edges: usize, additional_repairs: usize) {
        self.edges.reserve(additional_edges);
        self.repairs.reserve(additional_repairs);
    }

    pub fn get_edge(&self, key: &EdgeKey<NodeId>) -> Option<&EdgeRecord<NodeId>> {
        self.edges.get(key)
    }

    pub fn get_repair(&self, key: &RepairKey<NodeId>) -> Option<&RepairQueueRecord<NodeId>> {
        self.repairs.get(key)
    }

    pub fn mark_repair_resolved(&mut self, key: &RepairKey<NodeId>) -> bool {
        if let Some(record) = self.repairs.get_mut(key) {
            record.resolved = true;
            true
        } else {
            false
        }
    }

    pub fn apply_summary(
        &mut self,
        summary: &PlacementSummary<NodeId>,
    ) -> GraphHardeningResult<Vec<AppliedGraphMutation<NodeId>>> {
        let mut mutations = Vec::with_capacity(summary.decisions.len());
        let edge_hint = summary.strong_parent_count
            + summary.provisional_parent_count
            + summary.lateral_edge_count
            + summary.evidence_edge_count;
        self.reserve(edge_hint, summary.repair_count);

        for decision in &summary.decisions {
            mutations.push(self.apply_decision(decision)?);
        }

        Ok(mutations)
    }

    pub fn apply_decisions<'a>(
        &mut self,
        decisions: impl IntoIterator<Item = &'a GraphWriteDecision<NodeId>>,
    ) -> GraphHardeningResult<Vec<AppliedGraphMutation<NodeId>>>
    where
        NodeId: 'a,
    {
        let iter = decisions.into_iter();
        let (lower, _) = iter.size_hint();
        let mut mutations = Vec::with_capacity(lower);

        for decision in iter {
            mutations.push(self.apply_decision(decision)?);
        }

        Ok(mutations)
    }

    pub fn apply_decision(
        &mut self,
        decision: &GraphWriteDecision<NodeId>,
    ) -> GraphHardeningResult<AppliedGraphMutation<NodeId>> {
        self.seq = self.seq.saturating_add(1);
        let seq = self.seq;
        self.stats.record_decision(decision);

        if let Some(edge_kind) = decision.edge_kind {
            if decision.action.writes_edge() {
                return Ok(self.apply_edge_decision(decision, edge_kind, seq));
            }
        }

        Ok(self.apply_control_decision(decision, seq))
    }

    fn apply_edge_decision(
        &mut self,
        decision: &GraphWriteDecision<NodeId>,
        edge_kind: MentionGraphEdgeKind,
        seq: u64,
    ) -> AppliedGraphMutation<NodeId> {
        let key = EdgeKey::from_decision(decision);
        let target_lifecycle = target_lifecycle_for_write(decision, self.config);

        if let Some(record) = self.edges.get_mut(&key) {
            let (previous, next, reason) =
                record.update(decision, edge_kind, target_lifecycle, seq, self.config);
            let kind = mutation_kind_for_lifecycle_change(previous, next);

            return AppliedGraphMutation {
                seq,
                action: decision.action,
                kind,
                edge_key: Some(key),
                repair_key: None,
                previous_lifecycle: Some(previous),
                new_lifecycle: Some(next),
                confidence: decision.confidence,
                reason,
            };
        }

        let record = EdgeRecord::new(decision, edge_kind, target_lifecycle, seq, self.config);
        self.edges.insert(key.clone(), record);

        AppliedGraphMutation {
            seq,
            action: decision.action,
            kind: GraphMutationKind::InsertedEdge,
            edge_key: Some(key),
            repair_key: None,
            previous_lifecycle: None,
            new_lifecycle: Some(target_lifecycle),
            confidence: decision.confidence,
            reason: reason_for_write_action(decision.action),
        }
    }

    fn apply_control_decision(
        &mut self,
        decision: &GraphWriteDecision<NodeId>,
        seq: u64,
    ) -> AppliedGraphMutation<NodeId> {
        let repair_key = decision
            .repair
            .as_ref()
            .map(|item| self.enqueue_repair(item, seq));

        let edge_key = EdgeKey::from_decision(decision);
        let mut previous_lifecycle = None;
        let mut new_lifecycle = None;
        let mut mutation_kind = if repair_key.is_some() {
            GraphMutationKind::RepairQueued
        } else {
            GraphMutationKind::Noop
        };
        let mut reason = reason_for_control_action(decision.action);

        if let Some(record) = self.edges.get_mut(&edge_key) {
            let previous = record.lifecycle;
            record.counters.observe(
                decision.action,
                decision.confidence,
                self.config.confidence_ema_alpha,
            );

            let target = target_lifecycle_for_control(decision.action, previous);
            let (next, transition_reason) = transition_lifecycle(
                previous,
                target,
                decision.action,
                decision.confidence,
                &record.counters,
                self.config,
            );

            record.lifecycle = next;
            record.last_action = decision.action;
            record.last_verdict = decision
                .evaluation
                .as_ref()
                .map(|evaluation| evaluation.verdict);
            record.last_seen_seq = seq;
            record.version = record.version.saturating_add(1);
            record.last_evaluation =
                retained_evaluation(decision, self.config.retain_last_edge_evaluation);

            previous_lifecycle = Some(previous);
            new_lifecycle = Some(next);
            mutation_kind = mutation_kind_for_lifecycle_change(previous, next);
            reason = transition_reason;
        }

        AppliedGraphMutation {
            seq,
            action: decision.action,
            kind: mutation_kind,
            edge_key: if previous_lifecycle.is_some() {
                Some(edge_key)
            } else {
                None
            },
            repair_key,
            previous_lifecycle,
            new_lifecycle,
            confidence: decision.confidence,
            reason,
        }
    }

    fn enqueue_repair(&mut self, item: &RepairQueueItem<NodeId>, seq: u64) -> RepairKey<NodeId> {
        let mut item = item.clone();
        if !self.config.retain_repair_evaluation {
            item.evaluation = None;
        }

        let key = RepairKey::from_item(&item);
        if let Some(record) = self.repairs.get_mut(&key) {
            record.reinforce(item, seq);
        } else {
            self.repairs
                .insert(key.clone(), RepairQueueRecord::new(item, seq));
        }
        key
    }
}

fn target_lifecycle_for_write<NodeId>(
    decision: &GraphWriteDecision<NodeId>,
    config: HardeningConfig,
) -> EdgeLifecycle {
    match decision.action {
        GraphWriteAction::CommitStructuralEdge | GraphWriteAction::PreserveMultiParentDag => {
            if decision.confidence >= config.promote_confirmed_confidence {
                EdgeLifecycle::Confirmed
            } else {
                EdgeLifecycle::Provisional
            }
        }
        GraphWriteAction::CommitProvisionalEdge => EdgeLifecycle::Provisional,
        GraphWriteAction::CommitEvidenceEdge
        | GraphWriteAction::CommitLateralEdge
        | GraphWriteAction::CommitTopicalEdge
        | GraphWriteAction::CommitAssociativeEdge => {
            if decision.confidence >= config.promote_confirmed_confidence {
                EdgeLifecycle::Confirmed
            } else {
                EdgeLifecycle::Provisional
            }
        }
        GraphWriteAction::RejectHierarchy => EdgeLifecycle::Rejected,
        GraphWriteAction::FlipAndRetest
        | GraphWriteAction::EnqueueIntermediateDiscovery
        | GraphWriteAction::QuarantineForRepair => EdgeLifecycle::Contested,
        GraphWriteAction::Skip => EdgeLifecycle::Candidate,
    }
}

fn target_lifecycle_for_control(action: GraphWriteAction, current: EdgeLifecycle) -> EdgeLifecycle {
    match action {
        GraphWriteAction::QuarantineForRepair => EdgeLifecycle::Quarantined,
        GraphWriteAction::FlipAndRetest | GraphWriteAction::EnqueueIntermediateDiscovery => {
            EdgeLifecycle::Contested
        }
        GraphWriteAction::RejectHierarchy | GraphWriteAction::Skip => EdgeLifecycle::Rejected,
        _ => current,
    }
}

fn transition_lifecycle(
    current: EdgeLifecycle,
    target: EdgeLifecycle,
    action: GraphWriteAction,
    confidence: f32,
    counters: &EdgeCounters,
    config: HardeningConfig,
) -> (EdgeLifecycle, HardeningReason) {
    if current.is_terminal_without_manual_repair() {
        return (current, HardeningReason::ContradictoryGeometry);
    }

    if matches!(action, GraphWriteAction::QuarantineForRepair) {
        return (
            EdgeLifecycle::Quarantined,
            HardeningReason::ContradictoryGeometry,
        );
    }

    match (current, target) {
        (EdgeLifecycle::Confirmed, EdgeLifecycle::Rejected) => {
            if counters.rejections >= config.confirmed_rejection_hysteresis as u64 {
                (
                    EdgeLifecycle::Contested,
                    HardeningReason::RepeatedRejections,
                )
            } else {
                (
                    EdgeLifecycle::Confirmed,
                    HardeningReason::HysteresisKeptConfirmed,
                )
            }
        }
        (EdgeLifecycle::Confirmed, EdgeLifecycle::Contested) => {
            if counters.repair_observations >= config.confirmed_rejection_hysteresis as u64 {
                (EdgeLifecycle::Contested, reason_for_control_action(action))
            } else {
                (
                    EdgeLifecycle::Confirmed,
                    HardeningReason::HysteresisKeptConfirmed,
                )
            }
        }
        (EdgeLifecycle::Provisional, EdgeLifecycle::Rejected) => {
            if counters.rejections >= config.provisional_rejection_hysteresis as u64 {
                (EdgeLifecycle::Rejected, HardeningReason::RepeatedRejections)
            } else {
                (
                    EdgeLifecycle::Provisional,
                    HardeningReason::HysteresisKeptProvisional,
                )
            }
        }
        (EdgeLifecycle::Rejected, EdgeLifecycle::Confirmed) => {
            if confidence >= config.revive_rejected_confidence {
                (
                    EdgeLifecycle::Provisional,
                    HardeningReason::PromotedByConfidence,
                )
            } else {
                (EdgeLifecycle::Rejected, HardeningReason::RejectedByAdapter)
            }
        }
        (EdgeLifecycle::Rejected, EdgeLifecycle::Provisional) => {
            if confidence >= config.revive_rejected_confidence {
                (
                    EdgeLifecycle::Provisional,
                    HardeningReason::PromotedByConfidence,
                )
            } else {
                (EdgeLifecycle::Rejected, HardeningReason::RejectedByAdapter)
            }
        }
        (_, EdgeLifecycle::Confirmed) => {
            if confidence >= config.promote_confirmed_confidence {
                (
                    EdgeLifecycle::Confirmed,
                    HardeningReason::PromotedByConfidence,
                )
            } else {
                (EdgeLifecycle::Provisional, HardeningReason::Reinforced)
            }
        }
        (_, EdgeLifecycle::Provisional) => {
            if current == EdgeLifecycle::Confirmed {
                (
                    EdgeLifecycle::Confirmed,
                    HardeningReason::HysteresisKeptConfirmed,
                )
            } else {
                (EdgeLifecycle::Provisional, HardeningReason::Reinforced)
            }
        }
        (_, next) => (next, reason_for_control_action(action)),
    }
}

fn mutation_kind_for_lifecycle_change(
    previous: EdgeLifecycle,
    next: EdgeLifecycle,
) -> GraphMutationKind {
    if previous == next {
        return GraphMutationKind::UpdatedEdge;
    }

    match next {
        EdgeLifecycle::Confirmed => GraphMutationKind::PromotedEdge,
        EdgeLifecycle::Provisional => GraphMutationKind::UpdatedEdge,
        EdgeLifecycle::Contested => GraphMutationKind::ContestedEdge,
        EdgeLifecycle::Deprecated => GraphMutationKind::DemotedEdge,
        EdgeLifecycle::Rejected => GraphMutationKind::RejectedEdge,
        EdgeLifecycle::Quarantined => GraphMutationKind::QuarantinedEdge,
        EdgeLifecycle::Candidate => GraphMutationKind::UpdatedEdge,
    }
}

fn reason_for_write_action(action: GraphWriteAction) -> HardeningReason {
    match action {
        GraphWriteAction::CommitStructuralEdge | GraphWriteAction::PreserveMultiParentDag => {
            HardeningReason::NewEdge
        }
        GraphWriteAction::CommitProvisionalEdge => HardeningReason::Reinforced,
        GraphWriteAction::CommitEvidenceEdge => HardeningReason::EvidenceWrite,
        GraphWriteAction::CommitLateralEdge
        | GraphWriteAction::CommitTopicalEdge
        | GraphWriteAction::CommitAssociativeEdge => HardeningReason::AssociativeWrite,
        GraphWriteAction::RejectHierarchy => HardeningReason::RejectedByAdapter,
        GraphWriteAction::FlipAndRetest => HardeningReason::ReversedGeometry,
        GraphWriteAction::EnqueueIntermediateDiscovery => HardeningReason::MissingIntermediate,
        GraphWriteAction::QuarantineForRepair => HardeningReason::ContradictoryGeometry,
        GraphWriteAction::Skip => HardeningReason::NoWritableAction,
    }
}

fn reason_for_control_action(action: GraphWriteAction) -> HardeningReason {
    match action {
        GraphWriteAction::FlipAndRetest => HardeningReason::ReversedGeometry,
        GraphWriteAction::EnqueueIntermediateDiscovery => HardeningReason::MissingIntermediate,
        GraphWriteAction::QuarantineForRepair => HardeningReason::ContradictoryGeometry,
        GraphWriteAction::RejectHierarchy => HardeningReason::RejectedByAdapter,
        GraphWriteAction::Skip => HardeningReason::NoWritableAction,
        _ => reason_for_write_action(action),
    }
}

fn retained_evaluation<NodeId>(
    decision: &GraphWriteDecision<NodeId>,
    retain: bool,
) -> Option<ConeEvaluation> {
    if retain {
        decision.evaluation.clone()
    } else {
        None
    }
}

#[inline]
fn priority_rank(priority: RepairPriority) -> u8 {
    match priority {
        RepairPriority::Low => 0,
        RepairPriority::Medium => 1,
        RepairPriority::High => 2,
        RepairPriority::Critical => 3,
    }
}

#[inline]
fn update_average(avg: &mut f32, observations: u64, value: f32) {
    if observations == 0 {
        return;
    }
    let n = observations as f32;
    *avg += (value - *avg) / n;
}

#[inline]
fn validate_unit_interval(field: &'static str, value: f32) -> GraphHardeningResult<()> {
    if !value.is_finite() || !(0.0..=1.0).contains(&value) {
        return Err(GraphHardeningError::InvalidConfigField { field, value });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn decision(
        action: GraphWriteAction,
        edge_kind: Option<MentionGraphEdgeKind>,
        confidence: f32,
    ) -> GraphWriteDecision<&'static str> {
        GraphWriteDecision {
            parent_id: "parent",
            child_id: "child",
            relation_kind: MentionGraphRelationKind::IsA,
            hierarchy_kind: Some(HierarchyRelationKind::TypeHierarchy),
            action,
            edge_kind,
            confidence,
            support_score: confidence,
            evaluation: None,
            repair: None,
        }
    }

    fn repair_decision(
        action: GraphWriteAction,
        repair_kind: RepairQueueKind,
    ) -> GraphWriteDecision<&'static str> {
        let repair = RepairQueueItem {
            kind: repair_kind,
            priority: RepairPriority::High,
            parent_id: "parent",
            child_id: "child",
            relation_kind: MentionGraphRelationKind::IsA,
            hierarchy_kind: Some(HierarchyRelationKind::TypeHierarchy),
            confidence: 0.88,
            evaluation: None,
        };

        GraphWriteDecision {
            parent_id: "parent",
            child_id: "child",
            relation_kind: MentionGraphRelationKind::IsA,
            hierarchy_kind: Some(HierarchyRelationKind::TypeHierarchy),
            action,
            edge_kind: None,
            confidence: 0.88,
            support_score: 0.88,
            evaluation: None,
            repair: Some(repair),
        }
    }

    #[test]
    fn hardener_inserts_confirmed_structural_edge() {
        let mut hardener = InMemoryGraphHardener::default();
        let mutation = hardener
            .apply_decision(&decision(
                GraphWriteAction::CommitStructuralEdge,
                Some(MentionGraphEdgeKind::StructuralHierarchy),
                0.93,
            ))
            .assert_ok();

        assert_eq!(mutation.kind, GraphMutationKind::InsertedEdge);
        assert_eq!(mutation.new_lifecycle, Some(EdgeLifecycle::Confirmed));
        assert_eq!(hardener.edge_count(), 1);
        assert_eq!(hardener.stats().total_decisions, 1);
    }

    #[test]
    fn hardener_keeps_confirmed_edge_stable_after_single_rejection() {
        let mut hardener = InMemoryGraphHardener::default();
        hardener
            .apply_decision(&decision(
                GraphWriteAction::CommitStructuralEdge,
                Some(MentionGraphEdgeKind::StructuralHierarchy),
                0.95,
            ))
            .assert_ok();

        let rejection = decision(GraphWriteAction::RejectHierarchy, None, 0.25);
        let mutation = hardener.apply_decision(&rejection).assert_ok();

        assert_eq!(mutation.reason, HardeningReason::HysteresisKeptConfirmed);
        assert_eq!(mutation.new_lifecycle, Some(EdgeLifecycle::Confirmed));
    }

    #[test]
    fn hardener_contests_confirmed_edge_after_repeated_rejections() {
        let mut hardener = InMemoryGraphHardener::default();
        hardener
            .apply_decision(&decision(
                GraphWriteAction::CommitStructuralEdge,
                Some(MentionGraphEdgeKind::StructuralHierarchy),
                0.95,
            ))
            .assert_ok();

        for _ in 0..3 {
            hardener
                .apply_decision(&decision(GraphWriteAction::RejectHierarchy, None, 0.2))
                .assert_ok();
        }

        let key = EdgeKey {
            from_id: "parent",
            to_id: "child",
            relation_kind: MentionGraphRelationKind::IsA,
            hierarchy_kind: Some(HierarchyRelationKind::TypeHierarchy),
        };
        assert_eq!(
            hardener.get_edge(&key).map(|record| record.lifecycle),
            Some(EdgeLifecycle::Contested)
        );
    }

    #[test]
    fn hardener_dedupes_repair_queue_items() {
        let mut hardener = InMemoryGraphHardener::default();
        let repair = repair_decision(
            GraphWriteAction::FlipAndRetest,
            RepairQueueKind::FlipAndRetest,
        );

        hardener.apply_decision(&repair).assert_ok();
        hardener.apply_decision(&repair).assert_ok();

        assert_eq!(hardener.repair_count(), 1);
        let repair_record = match hardener.repairs().values().next() {
            Some(record) => record,
            None => panic!("repair record missing"),
        };
        assert_eq!(repair_record.occurrences, 2);
    }

    #[test]
    fn hardener_quarantines_existing_edge_on_contradictory_geometry() {
        let mut hardener = InMemoryGraphHardener::default();
        hardener
            .apply_decision(&decision(
                GraphWriteAction::CommitStructuralEdge,
                Some(MentionGraphEdgeKind::StructuralHierarchy),
                0.95,
            ))
            .assert_ok();

        let mutation = hardener
            .apply_decision(&repair_decision(
                GraphWriteAction::QuarantineForRepair,
                RepairQueueKind::ContradictoryGeometry,
            ))
            .assert_ok();

        assert_eq!(mutation.kind, GraphMutationKind::QuarantinedEdge);
        assert_eq!(mutation.new_lifecycle, Some(EdgeLifecycle::Quarantined));
        assert_eq!(hardener.repair_count(), 1);
    }

    #[test]
    fn hardener_applies_placement_summary_in_batch() {
        let mut hardener =
            InMemoryGraphHardener::with_capacity(HardeningConfig::default(), 4, 2).assert_ok();

        let summary = PlacementSummary {
            child_id: "child",
            strong_parent_count: 1,
            provisional_parent_count: 1,
            lateral_edge_count: 0,
            evidence_edge_count: 0,
            repair_count: 0,
            rejected_count: 0,
            decisions: vec![
                decision(
                    GraphWriteAction::CommitStructuralEdge,
                    Some(MentionGraphEdgeKind::StructuralHierarchy),
                    0.91,
                ),
                GraphWriteDecision {
                    parent_id: "parent_2",
                    child_id: "child",
                    relation_kind: MentionGraphRelationKind::Generalizes,
                    hierarchy_kind: Some(HierarchyRelationKind::Abstraction),
                    action: GraphWriteAction::CommitProvisionalEdge,
                    edge_kind: Some(MentionGraphEdgeKind::ProvisionalHierarchy),
                    confidence: 0.62,
                    support_score: 0.62,
                    evaluation: None,
                    repair: None,
                },
            ],
        };

        let mutations = hardener.apply_summary(&summary).assert_ok();
        assert_eq!(mutations.len(), 2);
        assert_eq!(hardener.edge_count(), 2);
        assert_eq!(hardener.stats().total_decisions, 2);
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
