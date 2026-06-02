//! Surface memory builds deterministic pre-linker resolution facts.
//!
//! It does not decide final atlas identity. It records stable surface aliases,
//! kind evidence, and speculative same-surface clusters for later graph work.

use std::collections::BTreeMap;

use phoenix_types::MentionEntityRef;

use crate::types::{EntityLabel, MentionKind, MentionPacket, MentionStatus};

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SurfaceMemoryReport {
    pub entries: Vec<SurfaceMemoryEntry>,
    pub candidate_edges: Vec<SurfaceCandidateEdge>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SurfaceMemoryEntry {
    pub key: String,
    pub display: String,
    pub kind: Option<String>,
    pub kind_confidence: f32,
    pub mention_count: usize,
    pub exportable_count: usize,
    pub known_count: usize,
    pub model_count: usize,
    pub prior_count: usize,
    pub conflict: bool,
    pub aliases: Vec<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SurfaceCandidateEdge {
    pub mention_id: u64,
    pub surface: String,
    pub key: String,
    pub target: SurfaceCandidateTarget,
    pub kind: SurfaceCandidateKind,
    pub confidence: f32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SurfaceCandidateTarget {
    KnownEntity(String),
    SpeculativeEntity(String),
    DeferredReview,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SurfaceCandidateKind {
    KnownExactOrAlias,
    NormalizedAlias,
    SameSurfaceCluster,
    ReviewOnly,
}

impl SurfaceMemoryReport {
    pub fn build(mentions: &[MentionPacket]) -> Self {
        let mut builders = BTreeMap::<String, SurfaceEntryBuilder>::new();
        for mention in mentions.iter().filter(|mention| {
            mention.mention_kind == MentionKind::Named && mention.status != MentionStatus::Rejected
        }) {
            let key = alias_key(mention);
            let builder = builders
                .entry(key.clone())
                .or_insert_with(|| SurfaceEntryBuilder::new(key, mention.surface.to_string()));
            builder.add_mention(mention);
        }

        let entries = builders
            .values()
            .map(SurfaceEntryBuilder::to_entry)
            .collect::<Vec<_>>();
        let candidate_edges = build_candidate_edges(mentions, &builders);
        Self {
            entries,
            candidate_edges,
        }
    }
}

#[derive(Clone, Debug)]
struct SurfaceEntryBuilder {
    key: String,
    display: String,
    mention_count: usize,
    exportable_count: usize,
    known_count: usize,
    model_count: usize,
    prior_count: usize,
    aliases: BTreeMap<String, usize>,
    labels: BTreeMap<String, f32>,
    known_target: Option<String>,
}

impl SurfaceEntryBuilder {
    fn new(key: String, display: String) -> Self {
        Self {
            key,
            display,
            mention_count: 0,
            exportable_count: 0,
            known_count: 0,
            model_count: 0,
            prior_count: 0,
            aliases: BTreeMap::new(),
            labels: BTreeMap::new(),
            known_target: None,
        }
    }

    fn add_mention(&mut self, mention: &MentionPacket) {
        self.mention_count += 1;
        if mention.is_exportable() {
            self.exportable_count += 1;
        }
        *self.aliases.entry(mention.surface.to_string()).or_default() += 1;
        if let Some((label, weight)) = best_label(mention) {
            *self
                .labels
                .entry(kind_group(label.as_str()).to_owned())
                .or_default() += weight;
        }
        for vote in &mention.source_votes {
            match vote.source {
                crate::types::MentionSourceKind::KnownLexicon => self.known_count += 1,
                crate::types::MentionSourceKind::ModelDiscovery
                | crate::types::MentionSourceKind::ModelVerify => self.model_count += 1,
                _ => {}
            }
            if vote.reason == crate::types::VoteReason::RepeatedSurface && vote.label.is_some() {
                self.prior_count += 1;
            }
        }
        if let Some(MentionEntityRef::Known(entity_id)) = mention.entity_ref.as_ref() {
            self.known_count += 1;
            self.known_target.get_or_insert_with(|| entity_id.0.clone());
        }
    }

    fn to_entry(&self) -> SurfaceMemoryEntry {
        let labels = self.sorted_labels();
        let (kind, confidence) = labels
            .first()
            .map(|(label, score)| ((*label).to_owned(), *score))
            .unwrap_or_else(|| ("unknown".to_owned(), 0.0));
        SurfaceMemoryEntry {
            key: self.key.clone(),
            display: self.display.clone(),
            kind: (kind != "unknown").then_some(kind),
            kind_confidence: confidence,
            mention_count: self.mention_count,
            exportable_count: self.exportable_count,
            known_count: self.known_count,
            model_count: self.model_count,
            prior_count: self.prior_count,
            conflict: self.has_label_conflict(),
            aliases: self.aliases.keys().cloned().collect(),
        }
    }

    fn has_label_conflict(&self) -> bool {
        let labels = self.sorted_labels();
        let Some((_, confidence)) = labels.first() else {
            return false;
        };
        let runner_up = labels.get(1).map(|(_, score)| *score).unwrap_or(0.0);
        runner_up > 0.0 && *confidence < runner_up + 0.25
    }

    fn sorted_labels(&self) -> Vec<(&str, f32)> {
        let mut labels = self
            .labels
            .iter()
            .map(|(label, score)| (label.as_str(), *score))
            .collect::<Vec<_>>();
        labels.sort_by(|left, right| {
            right
                .1
                .partial_cmp(&left.1)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        labels
    }
}

fn build_candidate_edges(
    mentions: &[MentionPacket],
    builders: &BTreeMap<String, SurfaceEntryBuilder>,
) -> Vec<SurfaceCandidateEdge> {
    let mut edges = Vec::new();
    for mention in mentions
        .iter()
        .filter(|mention| mention.mention_kind == MentionKind::Named)
    {
        let key = alias_key(mention);
        let Some(builder) = builders.get(&key) else {
            continue;
        };
        let (target, kind, confidence) = match mention.entity_ref.as_ref() {
            Some(MentionEntityRef::Known(entity_id)) => (
                SurfaceCandidateTarget::KnownEntity(entity_id.0.clone()),
                SurfaceCandidateKind::KnownExactOrAlias,
                mention.confidence.max(0.90),
            ),
            _ if builder.known_target.is_some() => (
                SurfaceCandidateTarget::KnownEntity(builder.known_target.clone().unwrap()),
                alias_edge_kind(&key, mention),
                mention.confidence.max(0.72),
            ),
            _ if builder.exportable_count >= 2 && !builder.has_label_conflict() => (
                SurfaceCandidateTarget::SpeculativeEntity(key.clone()),
                alias_edge_kind(&key, mention),
                (mention.confidence + 0.12).min(0.88),
            ),
            _ => (
                SurfaceCandidateTarget::DeferredReview,
                SurfaceCandidateKind::ReviewOnly,
                mention.confidence,
            ),
        };
        edges.push(SurfaceCandidateEdge {
            mention_id: mention.mention_id.0,
            surface: mention.surface.to_string(),
            key,
            target,
            kind,
            confidence,
        });
    }
    edges
}

fn alias_edge_kind(key: &str, mention: &MentionPacket) -> SurfaceCandidateKind {
    if key == mention.normalized.as_str() {
        SurfaceCandidateKind::SameSurfaceCluster
    } else {
        SurfaceCandidateKind::NormalizedAlias
    }
}

fn alias_key(mention: &MentionPacket) -> String {
    let stripped = normalize_alias_surface(mention.surface.as_str());
    if stripped.is_empty() {
        mention.normalized.to_string()
    } else {
        stripped
    }
}

fn normalize_alias_surface(surface: &str) -> String {
    let words = surface
        .trim_matches(|ch: char| ch.is_ascii_punctuation() || ch.is_whitespace())
        .split_whitespace()
        .skip_while(|word| is_title_or_article(word.trim_matches('.')))
        .collect::<Vec<_>>();
    let joined = words.join(" ");
    let stripped = joined
        .strip_suffix("'s")
        .or_else(|| joined.strip_suffix("\u{2019}s"))
        .unwrap_or(joined.as_str());
    stripped
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_ascii_lowercase()
}

fn is_title_or_article(word: &str) -> bool {
    matches!(
        word.to_ascii_lowercase().as_str(),
        "the"
            | "a"
            | "an"
            | "mr"
            | "mrs"
            | "ms"
            | "miss"
            | "professor"
            | "prof"
            | "doctor"
            | "dr"
            | "sir"
            | "lady"
            | "lord"
            | "king"
            | "queen"
    )
}

fn best_label(mention: &MentionPacket) -> Option<(&EntityLabel, f32)> {
    mention
        .label_distribution
        .iter()
        .max_by(|left, right| {
            left.1
                .partial_cmp(&right.1)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .map(|(label, score)| (label, *score))
}

fn kind_group(label: &str) -> &'static str {
    match label.to_ascii_lowercase().as_str() {
        "character" | "person" | "npc" => "Person",
        "organization" | "faction" | "alliance" | "department" => "Organization",
        "location" | "region" | "landmark" => "Location",
        "artifact" | "item" | "weapon" => "Artifact",
        "ability" | "spell" => "Ability",
        "event" => "Event",
        _ => "unknown",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use compact_str::CompactString;
    use smallvec::smallvec;

    #[test]
    fn alias_normalization_strips_titles_articles_and_possessives() {
        assert_eq!(normalize_alias_surface("Professor Xvim"), "xvim");
        assert_eq!(normalize_alias_surface("the matriarch"), "matriarch");
        assert_eq!(normalize_alias_surface("Zorian\u{2019}s"), "zorian");
    }

    #[test]
    fn report_clusters_repeated_speculative_surface() {
        let mentions = vec![
            packet(0, "Rook", "Person", MentionStatus::AliasCandidate),
            packet(10, "Rook", "Person", MentionStatus::AliasCandidate),
        ];
        let report = SurfaceMemoryReport::build(&mentions);
        assert_eq!(report.entries.len(), 1);
        assert_eq!(report.entries[0].key, "rook");
        assert!(report
            .candidate_edges
            .iter()
            .all(|edge| matches!(edge.target, SurfaceCandidateTarget::SpeculativeEntity(_))));
    }

    fn packet(start: u32, surface: &str, label: &str, status: MentionStatus) -> MentionPacket {
        MentionPacket {
            mention_id: crate::types::LocalMentionId(u64::from(start)),
            document_id: CompactString::from("doc"),
            chunk_id: None,
            sentence_index: 0,
            range: phoenix_types::TextRange {
                start,
                end: start + surface.len() as u32,
            },
            surface: CompactString::from(surface),
            normalized: CompactString::from(surface.to_ascii_lowercase()),
            mention_kind: MentionKind::Named,
            label_distribution: smallvec![(EntityLabel::new(label), 1.0)],
            entity_ref: None,
            source_votes: smallvec![],
            context: crate::types::MentionContext::default(),
            syntax: None,
            semantics: crate::types::MentionSemantics::default(),
            confidence: 0.62,
            status,
        }
    }
}
