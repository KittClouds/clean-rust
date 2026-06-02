use std::cmp::Ordering;

use phoenix_alex::tokenize_norm;
use phoenix_types::{
    AtlasAliasEvidence, AtlasAliasProposalDecision, AtlasAliasRelation, AtlasIdentityReceiptAction,
    AtlasIdentityReceiptSummary, AtlasIdentityResolutionSummary, AtlasIdentityTargetSummary,
    EntityKind,
};
use smallvec::SmallVec;

use crate::surface_memory::SurfaceCandidateKind;
use crate::types::{MentionKind, MentionPacket, MentionStatus};

use super::{DEFER_MARGIN, KNOWN_ACCEPT_THRESHOLD};

#[derive(Clone, Debug)]
pub(super) struct ResolutionCandidate {
    pub(super) target_key: String,
    pub(super) target: AtlasIdentityTargetSummary,
    pub(super) action: AtlasIdentityReceiptAction,
    pub(super) score: f32,
    pub(super) evidence: SmallVec<[AtlasAliasEvidence; 6]>,
    pub(super) rationale: String,
    pub(super) rank: u8,
}

impl ResolutionCandidate {
    pub(super) fn merge(&mut self, other: &Self) {
        let old_score = self.score;
        if other.score > self.score {
            self.score = other.score;
        }
        if other.rank < self.rank || (other.rank == self.rank && other.score > old_score) {
            self.action = other.action;
            self.target = other.target.clone();
            self.rationale = other.rationale.clone();
            self.rank = other.rank;
        }
        for item in &other.evidence {
            if self.evidence.len() >= 6 {
                break;
            }
            self.evidence.push(item.clone());
        }
    }
}

pub(super) struct LocalDecisionGroup {
    pub(super) action: AtlasIdentityReceiptAction,
    pub(super) mention_ids: Vec<u64>,
    pub(super) surface: String,
    pub(super) target: AtlasIdentityTargetSummary,
    pub(super) confidence: f32,
    pub(super) evidence: Vec<AtlasAliasEvidence>,
}

impl Default for LocalDecisionGroup {
    fn default() -> Self {
        Self {
            mention_ids: Vec::new(),
            action: AtlasIdentityReceiptAction::MergeRunLocal,
            surface: String::new(),
            target: AtlasIdentityTargetSummary::Deferred,
            confidence: 0.0,
            evidence: Vec::new(),
        }
    }
}

impl LocalDecisionGroup {
    pub(super) fn push<I>(
        &mut self,
        id: u64,
        surface: &str,
        confidence: f32,
        action: AtlasIdentityReceiptAction,
        target: AtlasIdentityTargetSummary,
        evidence: I,
    ) where
        I: IntoIterator<Item = AtlasAliasEvidence>,
    {
        if self.mention_ids.is_empty() {
            self.surface = surface.to_owned();
            self.target = target;
            self.action = action;
        } else if action == AtlasIdentityReceiptAction::Coreference {
            self.action = action;
        }
        self.mention_ids.push(id);
        self.confidence = self.confidence.max(confidence);
        for item in evidence {
            if self.evidence.len() >= 6 {
                break;
            }
            self.evidence.push(item);
        }
    }
}

pub(super) fn identity_eligible(mention: &MentionPacket) -> bool {
    matches!(
        mention.mention_kind,
        MentionKind::Named | MentionKind::Nominal | MentionKind::Pronoun
    ) && mention.status != MentionStatus::Rejected
}

pub(super) fn best_entity_kind(mention: &MentionPacket) -> Option<EntityKind> {
    mention
        .label_distribution
        .iter()
        .max_by(|left, right| left.1.partial_cmp(&right.1).unwrap_or(Ordering::Equal))
        .and_then(|(label, _)| entity_kind_from_label(label.as_str()))
}

fn entity_kind_from_label(label: &str) -> Option<EntityKind> {
    match label.trim().to_ascii_lowercase().as_str() {
        "character" | "person" | "speaker" => Some(EntityKind::Character),
        "npc" => Some(EntityKind::Npc),
        "location" | "place" | "region" => Some(EntityKind::Location),
        "item" | "artifact" | "object" => Some(EntityKind::Item),
        "faction" => Some(EntityKind::Faction),
        "organization" | "organisation" | "network" | "group" => Some(EntityKind::Organization),
        "event" => Some(EntityKind::Event),
        "concept" | "veir" => Some(EntityKind::Concept),
        _ => None,
    }
}

pub(super) fn action_for_relation(relation: AtlasAliasRelation) -> AtlasIdentityReceiptAction {
    match relation {
        AtlasAliasRelation::FullDesignation => AtlasIdentityReceiptAction::FullDesignation,
        AtlasAliasRelation::ExactKnownAlias
        | AtlasAliasRelation::Nickname
        | AtlasAliasRelation::Codename
        | AtlasAliasRelation::SpellingVariant
        | AtlasAliasRelation::TitleOrRole => AtlasIdentityReceiptAction::AliasOfKnown,
        AtlasAliasRelation::SameSurface => AtlasIdentityReceiptAction::KnownEntity,
        AtlasAliasRelation::NewEntity => AtlasIdentityReceiptAction::NewEntity,
        AtlasAliasRelation::RelatedButDistinct
        | AtlasAliasRelation::TypeConflict
        | AtlasAliasRelation::Ambiguous => AtlasIdentityReceiptAction::Defer,
    }
}

pub(super) fn alias_decision_score(decision: AtlasAliasProposalDecision, confidence: f32) -> f32 {
    match decision {
        AtlasAliasProposalDecision::Accept => confidence.max(0.78),
        AtlasAliasProposalDecision::Propose => confidence,
        AtlasAliasProposalDecision::Defer => confidence.min(0.54),
        AtlasAliasProposalDecision::Reject => 0.0,
    }
}

pub(super) fn relation_rank(relation: AtlasAliasRelation) -> u8 {
    match relation {
        AtlasAliasRelation::ExactKnownAlias => 1,
        AtlasAliasRelation::FullDesignation => 2,
        AtlasAliasRelation::SpellingVariant => 3,
        AtlasAliasRelation::SameSurface => 4,
        AtlasAliasRelation::NewEntity => 8,
        _ => 9,
    }
}

pub(super) fn should_defer(
    top: &ResolutionCandidate,
    runner_up: Option<&ResolutionCandidate>,
) -> bool {
    let Some(runner_up) = runner_up else {
        return false;
    };
    if !known_target(&top.target) || !known_target(&runner_up.target) {
        return false;
    }
    top.target_key != runner_up.target_key
        && top.score >= KNOWN_ACCEPT_THRESHOLD
        && runner_up.score >= KNOWN_ACCEPT_THRESHOLD
        && top.score < runner_up.score + DEFER_MARGIN
}

fn known_target(target: &AtlasIdentityTargetSummary) -> bool {
    matches!(target, AtlasIdentityTargetSummary::KnownEntity { .. })
}

pub(super) fn candidate_order(left: &ResolutionCandidate, right: &ResolutionCandidate) -> Ordering {
    right
        .score
        .partial_cmp(&left.score)
        .unwrap_or(Ordering::Equal)
        .then_with(|| left.rank.cmp(&right.rank))
        .then_with(|| left.target_key.cmp(&right.target_key))
}

pub(super) fn surface_key(surface: &str) -> String {
    tokenize_norm(surface).join(" ")
}

pub(super) fn surface_edge_note(kind: SurfaceCandidateKind) -> &'static str {
    match kind {
        SurfaceCandidateKind::KnownExactOrAlias => "known exact or saved alias surface",
        SurfaceCandidateKind::NormalizedAlias => "normalized alias surface",
        SurfaceCandidateKind::SameSurfaceCluster => "same surface run-local cluster",
        SurfaceCandidateKind::ReviewOnly => "review-only surface",
    }
}

pub(super) fn mention_node_id(id: u64) -> String {
    format!("mention:{id}")
}

pub(super) fn known_node_id(id: &str) -> String {
    format!("known:{id}")
}

pub(super) fn target_node_id(target: &AtlasIdentityTargetSummary) -> String {
    match target {
        AtlasIdentityTargetSummary::KnownEntity { entity_id, .. } => known_node_id(&entity_id.0),
        AtlasIdentityTargetSummary::RunLocalEntity { key, .. }
        | AtlasIdentityTargetSummary::NewEntity { key, .. } => format!("local:{key}"),
        AtlasIdentityTargetSummary::Deferred => "deferred".to_owned(),
    }
}

pub(super) fn target_key(target: &AtlasIdentityTargetSummary) -> String {
    target_node_id(target)
}

pub(super) fn target_display(target: &AtlasIdentityTargetSummary) -> String {
    match target {
        AtlasIdentityTargetSummary::KnownEntity { canonical_name, .. } => canonical_name.clone(),
        AtlasIdentityTargetSummary::RunLocalEntity { display, .. }
        | AtlasIdentityTargetSummary::NewEntity { display, .. } => display.clone(),
        AtlasIdentityTargetSummary::Deferred => "Deferred identity review".to_owned(),
    }
}

pub(super) fn small_evidence(
    source: &str,
    confidence: f32,
    note: &str,
) -> SmallVec<[AtlasAliasEvidence; 6]> {
    let mut evidence_vec = SmallVec::new();
    evidence_vec.push(evidence(source, confidence, note));
    evidence_vec
}

pub(super) fn evidence(source: &str, confidence: f32, note: &str) -> AtlasAliasEvidence {
    AtlasAliasEvidence {
        source: source.to_owned(),
        confidence: confidence.clamp(0.0, 1.0),
        note: note.to_owned(),
    }
}

pub(super) fn receipt_id(
    document_id: &str,
    action: AtlasIdentityReceiptAction,
    mention_ids: &[u64],
    target: &AtlasIdentityTargetSummary,
    surface: &str,
) -> String {
    let seed = format!(
        "{document_id}:{action:?}:{mention_ids:?}:{}:{surface}",
        target_key(target)
    );
    format!("identity-{:016x}", stable_hash(seed.as_bytes()))
}

fn stable_hash(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

pub(super) fn summarize(
    node_count: usize,
    edge_count: usize,
    receipts: &[AtlasIdentityReceiptSummary],
) -> AtlasIdentityResolutionSummary {
    let mut summary = AtlasIdentityResolutionSummary {
        node_count,
        edge_count,
        receipt_count: receipts.len(),
        receipts: receipts.to_vec(),
        ..AtlasIdentityResolutionSummary::default()
    };
    for receipt in receipts {
        match receipt.action {
            AtlasIdentityReceiptAction::KnownEntity => summary.known_decisions += 1,
            AtlasIdentityReceiptAction::AliasOfKnown
            | AtlasIdentityReceiptAction::FullDesignation => summary.alias_decisions += 1,
            AtlasIdentityReceiptAction::Coreference => summary.coreference_decisions += 1,
            AtlasIdentityReceiptAction::MergeRunLocal => summary.merge_decisions += 1,
            AtlasIdentityReceiptAction::Split => summary.split_decisions += 1,
            AtlasIdentityReceiptAction::Defer => summary.deferred_decisions += 1,
            AtlasIdentityReceiptAction::NewEntity => summary.new_entity_decisions += 1,
        }
    }
    summary
}
