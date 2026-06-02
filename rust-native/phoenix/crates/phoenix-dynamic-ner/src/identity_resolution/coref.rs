use std::cmp::Ordering;
use std::collections::BTreeSet;

use phoenix_types::{AtlasIdentityReceiptAction, AtlasIdentityTargetSummary, EntityKind};

use crate::graph::{MentionEdgeKind, MentionGraph};
use crate::types::{MentionKind, MentionPacket, VoteReason};

use super::support::{
    best_entity_kind, mention_node_id, small_evidence, surface_key, target_key, ResolutionCandidate,
};
use super::{DagBuilder, IdentityEdgeKind};

#[derive(Clone, Copy)]
struct CorefLink {
    reference_id: u64,
    antecedent_id: u64,
    score: f32,
    source: &'static str,
    rationale: &'static str,
}

struct CorefDefer {
    reference_id: u64,
    score: f32,
    rationale: String,
}

#[derive(Default)]
struct CorefPlan {
    links: Vec<CorefLink>,
    defers: Vec<CorefDefer>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum ReferenceClass {
    Character,
    Group,
    Object,
    Place,
    FirstPerson,
    SecondPerson,
    Unknown,
}

#[derive(Clone, Copy)]
struct RankedAntecedent<'a> {
    mention: &'a MentionPacket,
    score: f32,
    source: &'static str,
    rationale: &'static str,
}

impl<'a> DagBuilder<'a> {
    pub(super) fn emit_unresolved_identity_receipt(
        &mut self,
        mention: &MentionPacket,
        confidence: f32,
        named_rationale: &str,
        reference_rationale: &str,
    ) {
        if mention.mention_kind == MentionKind::Named {
            self.emit_new_entity_receipt(mention, confidence, named_rationale);
        } else {
            self.emit_defer_receipt(mention, confidence.min(0.54), reference_rationale);
        }
    }

    pub(super) fn emit_single_local_group_receipt(&mut self, id: u64, confidence: f32) {
        let Some(mention) = self.mentions_by_id.get(&id).copied() else {
            return;
        };
        self.emit_unresolved_identity_receipt(
            mention,
            confidence,
            "single run-local identity remains unsaved",
            "single reference mention remains unresolved",
        );
    }

    pub(super) fn ingest_document_coreference(&mut self) {
        let mut mentions = self
            .mentions_by_id
            .values()
            .copied()
            .collect::<Vec<&MentionPacket>>();
        mentions.sort_by_key(|mention| {
            (
                mention.sentence_index,
                mention.range.start,
                mention.range.end,
                mention.mention_id.0,
            )
        });
        let plan = collect_coref_plan(&mentions, self.input.mention_graph);
        for defer in plan.defers {
            if let Some(reference) = self.mentions_by_id.get(&defer.reference_id).copied() {
                self.add_defer_candidate(reference, defer.score, &defer.rationale);
            }
        }
        for link in plan.links {
            self.ingest_coref_link(link);
        }
    }

    fn ingest_coref_link(&mut self, link: CorefLink) {
        let Some(reference) = self.mentions_by_id.get(&link.reference_id).copied() else {
            return;
        };
        let Some(antecedent) = self.mentions_by_id.get(&link.antecedent_id).copied() else {
            return;
        };
        let target = self
            .sorted_candidates(antecedent.mention_id.0)
            .into_iter()
            .find(|candidate| {
                !matches!(
                    candidate.target,
                    AtlasIdentityTargetSummary::Deferred
                        | AtlasIdentityTargetSummary::NewEntity { .. }
                )
            })
            .map(|candidate| candidate.target)
            .unwrap_or_else(|| {
                let key = surface_key(antecedent.surface.as_str());
                let target = self.local_target(&key, antecedent);
                self.ensure_local_node(&target, &[antecedent.mention_id.0, reference.mention_id.0]);
                self.add_candidate(
                    antecedent.mention_id.0,
                    ResolutionCandidate {
                        target_key: target_key(&target),
                        target: target.clone(),
                        action: AtlasIdentityReceiptAction::MergeRunLocal,
                        score: (link.score + 0.04).min(0.78),
                        evidence: small_evidence(
                            "document_coreference",
                            link.score,
                            "antecedent anchors a run-local coreference cluster",
                        ),
                        rationale: "named antecedent anchors a run-local identity".to_owned(),
                        rank: 6,
                    },
                );
                target
            });
        self.ensure_target_node(&target, &[antecedent.mention_id.0, reference.mention_id.0]);
        let score = coref_candidate_score(link.score, &target);
        self.add_candidate(
            reference.mention_id.0,
            ResolutionCandidate {
                target_key: target_key(&target),
                target: target.clone(),
                action: AtlasIdentityReceiptAction::Coreference,
                score,
                evidence: small_evidence(link.source, score, link.rationale),
                rationale: link.rationale.to_owned(),
                rank: 5,
            },
        );
        self.add_edge(
            mention_node_id(antecedent.mention_id.0),
            mention_node_id(reference.mention_id.0),
            IdentityEdgeKind::DocumentCoreference,
            score,
            format!(
                "coref:{}->{}",
                antecedent.mention_id.0, reference.mention_id.0
            ),
        );
    }
}

fn collect_coref_plan(mentions: &[&MentionPacket], graph: &MentionGraph) -> CorefPlan {
    let mut plan = CorefPlan::default();
    let mut seen = BTreeSet::<(u64, u64)>::new();
    for edge in &graph.edges {
        if !matches!(
            edge.kind,
            MentionEdgeKind::PronounCandidate
                | MentionEdgeKind::SpeakerContinuity
                | MentionEdgeKind::DependencyCoreArgument
                | MentionEdgeKind::Apposition
        ) {
            continue;
        }
        if seen.insert((edge.right.0, edge.left.0)) {
            plan.links.push(CorefLink {
                reference_id: edge.right.0,
                antecedent_id: edge.left.0,
                score: graph_edge_score(edge.kind, edge.weight),
                source: "mention_graph_coref",
                rationale: "mention graph supplied a document coreference edge",
            });
        }
    }
    for (idx, reference) in mentions.iter().enumerate() {
        if !is_reference_like(reference) {
            continue;
        }
        let ranked = ranked_antecedents(reference, &mentions[..idx]);
        if let Some(defer) = ambiguous_coref_defer(reference, &ranked) {
            plan.defers.push(defer);
            continue;
        }
        if let Some(top) = ranked.first().copied() {
            if seen.insert((reference.mention_id.0, top.mention.mention_id.0)) {
                plan.links.push(CorefLink {
                    reference_id: reference.mention_id.0,
                    antecedent_id: top.mention.mention_id.0,
                    score: top.score,
                    source: top.source,
                    rationale: top.rationale,
                });
            }
        }
    }
    plan
}

fn ranked_antecedents<'a>(
    reference: &MentionPacket,
    prior_mentions: &[&'a MentionPacket],
) -> Vec<RankedAntecedent<'a>> {
    let mut ranked = Vec::new();
    let dialogue_target = dialogue_target_id(reference);
    for antecedent in prior_mentions.iter().rev().copied() {
        if antecedent.mention_kind != MentionKind::Named {
            continue;
        }
        let distance = reference.sentence_index.abs_diff(antecedent.sentence_index);
        if distance > coref_window(reference) {
            break;
        }
        let mut source = "salience_rank";
        let mut rationale = "document salience links reference to ranked antecedent";
        let mut bonus = salience_bonus(antecedent);
        if dialogue_target == Some(antecedent.mention_id.0) {
            source = "dialogue_state";
            rationale = "dialogue state links quoted reference to speaker or addressee";
            bonus += 0.18;
        } else if !compatible_reference(reference, antecedent) {
            continue;
        }
        let base = match reference.mention_kind {
            MentionKind::Pronoun => 0.74,
            MentionKind::Nominal => 0.66,
            MentionKind::Named => 0.62,
        };
        let score = (base + bonus - distance as f32 * 0.06).clamp(0.50, 0.84);
        if source == "salience_rank" {
            rationale = match reference.mention_kind {
                MentionKind::Pronoun => "pronoun links to highest-ranked compatible antecedent",
                MentionKind::Nominal => {
                    "role nominal links to highest-ranked compatible antecedent"
                }
                MentionKind::Named => "epithet-like mention links to ranked antecedent",
            };
        }
        ranked.push(RankedAntecedent {
            mention: antecedent,
            score,
            source,
            rationale,
        });
    }
    ranked.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(Ordering::Equal)
            .then_with(|| left.mention.mention_id.0.cmp(&right.mention.mention_id.0))
    });
    ranked
}

fn ambiguous_coref_defer(
    reference: &MentionPacket,
    ranked: &[RankedAntecedent<'_>],
) -> Option<CorefDefer> {
    let top = ranked.first()?;
    let runner = ranked.get(1)?;
    if top.score >= runner.score + 0.07 {
        return None;
    }
    Some(CorefDefer {
        reference_id: reference.mention_id.0,
        score: top.score.min(0.54),
        rationale: format!(
            "document coreference was ambiguous: {} {:.3} vs {} {:.3}",
            top.mention.surface, top.score, runner.mention.surface, runner.score
        ),
    })
}

fn compatible_reference(reference: &MentionPacket, antecedent: &MentionPacket) -> bool {
    match reference.mention_kind {
        MentionKind::Pronoun => compatible_pronoun(reference.surface.as_str(), antecedent),
        MentionKind::Nominal => character_like(antecedent),
        MentionKind::Named => is_epithet_like(reference) && character_like(antecedent),
    }
}

fn compatible_pronoun(surface: &str, antecedent: &MentionPacket) -> bool {
    match reference_class(surface) {
        ReferenceClass::Character => character_like(antecedent),
        ReferenceClass::Group => character_like(antecedent) || organization_like(antecedent),
        ReferenceClass::Object => object_like(antecedent),
        ReferenceClass::Place => location_like(antecedent),
        ReferenceClass::FirstPerson | ReferenceClass::SecondPerson => false,
        ReferenceClass::Unknown => false,
    }
}

fn is_reference_like(mention: &MentionPacket) -> bool {
    match mention.mention_kind {
        MentionKind::Pronoun | MentionKind::Nominal => true,
        MentionKind::Named => is_epithet_like(mention),
    }
}

fn is_epithet_like(mention: &MentionPacket) -> bool {
    mention.source_votes.iter().any(|vote| {
        matches!(
            vote.reason,
            crate::types::VoteReason::TitlePattern | crate::types::VoteReason::NominalRole
        )
    })
}

fn coref_window(reference: &MentionPacket) -> u32 {
    match reference.mention_kind {
        MentionKind::Pronoun => match reference_class(reference.surface.as_str()) {
            ReferenceClass::FirstPerson | ReferenceClass::SecondPerson => 8,
            ReferenceClass::Object | ReferenceClass::Place => 4,
            _ => 3,
        },
        MentionKind::Nominal => 2,
        MentionKind::Named => 1,
    }
}

fn reference_class(surface: &str) -> ReferenceClass {
    match surface.trim().to_ascii_lowercase().as_str() {
        "he" | "him" | "his" | "she" | "her" | "hers" => ReferenceClass::Character,
        "they" | "them" | "their" | "theirs" | "we" | "us" | "our" | "ours" => {
            ReferenceClass::Group
        }
        "it" | "its" => ReferenceClass::Object,
        "there" | "here" => ReferenceClass::Place,
        "i" | "me" | "my" | "mine" => ReferenceClass::FirstPerson,
        "you" | "your" | "yours" => ReferenceClass::SecondPerson,
        _ => ReferenceClass::Unknown,
    }
}

fn dialogue_target_id(reference: &MentionPacket) -> Option<u64> {
    if !reference.semantics.is_quoted {
        return None;
    }
    let role = reference.context.paragraph_role.as_ref()?.as_str();
    match reference_class(reference.surface.as_str()) {
        ReferenceClass::FirstPerson => parse_dialogue_role(role, "speaker"),
        ReferenceClass::SecondPerson => parse_dialogue_role(role, "addressee"),
        _ => None,
    }
}

fn parse_dialogue_role(role: &str, key: &str) -> Option<u64> {
    for part in role.split([';', ',']) {
        let part = part.trim();
        let value = part
            .strip_prefix(key)
            .and_then(|rest| rest.strip_prefix([':', '=']))?;
        if let Ok(id) = value.parse::<u64>() {
            return Some(id);
        }
    }
    None
}

fn salience_bonus(mention: &MentionPacket) -> f32 {
    let mut bonus = 0.0;
    if mention.entity_ref.is_some() {
        bonus += 0.04;
    }
    if mention
        .syntax
        .as_ref()
        .is_some_and(|syntax| syntax.is_subject)
    {
        bonus += 0.05;
    }
    if mention
        .source_votes
        .iter()
        .any(|vote| vote.reason == VoteReason::DialogueSpeaker)
    {
        bonus += 0.06;
    }
    bonus
}

fn character_like(mention: &MentionPacket) -> bool {
    matches!(
        best_entity_kind(mention),
        Some(EntityKind::Character | EntityKind::Npc)
    )
}

fn organization_like(mention: &MentionPacket) -> bool {
    matches!(
        best_entity_kind(mention),
        Some(EntityKind::Faction | EntityKind::Organization)
    )
}

fn object_like(mention: &MentionPacket) -> bool {
    matches!(
        best_entity_kind(mention),
        Some(EntityKind::Item | EntityKind::Concept | EntityKind::Event)
    )
}

fn location_like(mention: &MentionPacket) -> bool {
    matches!(best_entity_kind(mention), Some(EntityKind::Location))
}

fn graph_edge_score(kind: MentionEdgeKind, weight: f32) -> f32 {
    let base: f32 = match kind {
        MentionEdgeKind::PronounCandidate => 0.72,
        MentionEdgeKind::SpeakerContinuity => 0.70,
        MentionEdgeKind::DependencyCoreArgument => 0.68,
        MentionEdgeKind::Apposition => 0.76,
        _ => 0.58,
    };
    base.max(weight).min(0.82)
}

fn coref_candidate_score(score: f32, target: &AtlasIdentityTargetSummary) -> f32 {
    match target {
        AtlasIdentityTargetSummary::KnownEntity { .. } => score.max(0.62),
        AtlasIdentityTargetSummary::RunLocalEntity { .. } => score.max(0.58),
        _ => score,
    }
}
