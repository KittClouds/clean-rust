//! Scoring + MentionWorkspace — additive vote scoring and packet finalization.
//!
//! Source-calibrated scoring collapses votes from all lanes into a single
//! confidence and status per mention. The workspace acts as an arena-style
//! accumulator during the pipeline.

use compact_str::CompactString;
use phoenix_types::{MentionEntityRef, SentenceSpan};
use rustc_hash::FxHashMap;
use smallvec::SmallVec;

use crate::known_lane::KnownCandidate;
use crate::native_lane::NativeCandidate;
use crate::traits::{AdjudicationCase, InstructTask};
use crate::types::{
    EntityLabel, LocalMentionId, MentionContext, MentionKind, MentionPacket, MentionSemantics,
    MentionSourceKind, MentionStatus, MentionVote, VoteReason,
};

// ---------------------------------------------------------------------------
// Score table — calibrated additive weights
// ---------------------------------------------------------------------------

/// Calibrated score weights per vote reason.
pub struct ScoreTable {
    pub exact_canonical: f32,
    pub exact_alias: f32,
    pub auto_alias: f32,
    pub fuzzy_anchor: f32,
    pub title_pattern: f32,
    pub cap_span: f32,
    pub nominal_role: f32,
    pub repeated_surface: f32,
    pub dependency_role: f32,
    pub dialogue_speaker: f32,
    pub model_span: f32,
    pub model_label: f32,
    pub nli_support: f32,
    pub nli_contradiction: f32,
    pub stopword_penalty: f32,
    pub guard_violation: f32,
}

impl Default for ScoreTable {
    fn default() -> Self {
        Self {
            exact_canonical: 1.00,
            exact_alias: 0.96,
            auto_alias: 0.90,
            fuzzy_anchor: 0.78,
            title_pattern: 0.70,
            cap_span: 0.42,
            nominal_role: 0.52,
            repeated_surface: 0.08,
            dependency_role: 0.10,
            dialogue_speaker: 0.06,
            model_span: 0.15,
            model_label: 0.15,
            nli_support: 0.20,
            nli_contradiction: -0.30,
            stopword_penalty: -0.60,
            guard_violation: -0.50,
        }
    }
}

impl ScoreTable {
    /// Score a single vote reason.
    #[inline]
    pub fn weight(&self, reason: VoteReason) -> f32 {
        match reason {
            VoteReason::ExactCanonical => self.exact_canonical,
            VoteReason::ExactAlias => self.exact_alias,
            VoteReason::AutoAlias => self.auto_alias,
            VoteReason::FuzzyAnchor => self.fuzzy_anchor,
            VoteReason::TitlePattern => self.title_pattern,
            VoteReason::CapSpan => self.cap_span,
            VoteReason::NominalRole => self.nominal_role,
            VoteReason::RepeatedSurface => self.repeated_surface,
            VoteReason::DependencyRole => self.dependency_role,
            VoteReason::DialogueSpeaker => self.dialogue_speaker,
            VoteReason::ModelSpan => self.model_span,
            VoteReason::ModelLabel => self.model_label,
            VoteReason::NliSupport => self.nli_support,
            VoteReason::NliContradiction => self.nli_contradiction,
            VoteReason::StopwordPenalty => self.stopword_penalty,
            VoteReason::GuardViolation => self.guard_violation,
        }
    }
}

// ---------------------------------------------------------------------------
// Workspace entry — pre-packet accumulator
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
struct WorkspaceEntry {
    id: LocalMentionId,
    range: phoenix_types::TextRange,
    surface: CompactString,
    normalized: CompactString,
    mention_kind: MentionKind,
    entity_ref: Option<MentionEntityRef>,
    votes: SmallVec<[MentionVote; 6]>,
    sentence_index: u32,
}

#[derive(Clone, Debug)]
struct LabelHint {
    label: EntityLabel,
    confidence: f32,
}

#[derive(Clone, Debug)]
struct SurfaceKindPrior {
    label: EntityLabel,
    confidence: f32,
    has_known: bool,
}

#[derive(Clone, Debug)]
struct SurfaceLabelEvidence {
    label: EntityLabel,
    score: f32,
    count: usize,
    known_count: usize,
    context_count: usize,
    strong_context_count: usize,
}

// ---------------------------------------------------------------------------
// MentionWorkspace
// ---------------------------------------------------------------------------

/// Arena-style accumulator for mentions during the NER pipeline.
pub struct MentionWorkspace {
    document_id: CompactString,
    entries: Vec<WorkspaceEntry>,
    score_table: ScoreTable,
    next_id: u64,
}

impl MentionWorkspace {
    pub fn new(document_id: &str, id_base: u64) -> Self {
        Self {
            document_id: CompactString::from(document_id),
            entries: Vec::with_capacity(256),
            score_table: ScoreTable::default(),
            next_id: id_base,
        }
    }

    /// Ingest known-lane candidates.
    pub fn add_known(&mut self, candidates: Vec<KnownCandidate>) {
        for c in candidates {
            self.entries.push(WorkspaceEntry {
                id: c.mention_id,
                range: c.range,
                surface: c.surface,
                normalized: c.normalized,
                mention_kind: c.mention_kind,
                entity_ref: c.entity_ref,
                votes: c.votes.into_iter().collect(),
                sentence_index: c.sentence_index,
            });
        }
    }

    /// Ingest native-lane candidates.
    pub fn add_native(&mut self, candidates: Vec<NativeCandidate>) {
        for c in candidates {
            self.entries.push(WorkspaceEntry {
                id: c.mention_id,
                range: c.range,
                surface: c.surface,
                normalized: c.normalized,
                mention_kind: c.mention_kind,
                entity_ref: c.entity_ref,
                votes: c.votes.into_iter().collect(),
                sentence_index: c.sentence_index,
            });
        }
    }

    /// Add model-produced votes to existing entries or create new ones.
    pub fn add_model_votes(&mut self, votes: Vec<(LocalMentionId, MentionVote)>) {
        for (id, vote) in votes {
            if let Some(entry) = self.entries.iter_mut().find(|e| e.id == id) {
                entry.votes.push(vote);
            }
        }
    }

    /// Add a completely new span discovered by the model, or merge with existing by range.
    pub fn add_discovered_span(
        &mut self,
        range: phoenix_types::TextRange,
        surface: compact_str::CompactString,
        sentence_index: u32,
        vote: MentionVote,
    ) {
        if let Some(entry) = self.entries.iter_mut().find(|e| e.range == range) {
            entry.votes.push(vote);
            return;
        }

        let id = self.next_id();
        let normalized = compact_str::CompactString::from(surface.to_lowercase());
        self.entries.push(WorkspaceEntry {
            id,
            range,
            surface,
            normalized,
            mention_kind: crate::types::MentionKind::Named,
            entity_ref: None,
            votes: smallvec::smallvec![vote],
            sentence_index,
        });
    }

    /// Apply adjudication decisions.
    pub fn apply_adjudication(&mut self, decisions: Vec<(LocalMentionId, MentionVote)>) {
        for (id, vote) in decisions {
            if let Some(entry) = self.entries.iter_mut().find(|e| e.id == id) {
                entry.votes.push(vote);
            }
        }
    }

    pub fn build_kind_adjudication_cases(
        &self,
        text: &str,
        sentences: &[SentenceSpan],
        limit: usize,
    ) -> Vec<AdjudicationCase> {
        if limit == 0 {
            return Vec::new();
        }

        let mut cases = self
            .entries
            .iter()
            .filter_map(|entry| {
                let priority = kind_adjudication_priority(entry, text, sentences)?;
                Some((
                    priority,
                    entry.range.start,
                    self.kind_adjudication_case(entry, text, sentences),
                ))
            })
            .collect::<Vec<_>>();
        cases.sort_by(|left, right| right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1)));
        cases
            .into_iter()
            .take(limit)
            .map(|(_, _, case)| case)
            .collect()
    }

    pub fn apply_context_kind_hints(&mut self, text: &str, sentences: &[SentenceSpan]) {
        for entry in self.entries.iter_mut() {
            if entry.mention_kind != MentionKind::Named || entry_has_known_label(entry) {
                continue;
            }
            let sentence = sentence_text(text, sentences, entry.sentence_index);
            let Some(label) = surface_kind_hint(entry.surface.as_str(), sentence.as_str()) else {
                continue;
            };
            if entry_has_label_group(entry, label.as_str()) {
                if should_reinforce_context_hint(
                    entry.surface.as_str(),
                    sentence.as_str(),
                    label.as_str(),
                ) {
                    let reason = if label_group(label.as_str()) == "person"
                        && dialogue_speaker_hint(entry.surface.as_str(), sentence.as_str())
                    {
                        VoteReason::DialogueSpeaker
                    } else {
                        VoteReason::DependencyRole
                    };
                    entry.votes.push(MentionVote {
                        source: MentionSourceKind::NativeDiscovery,
                        label: Some(label.clone()),
                        entity_ref: None,
                        confidence: context_kind_hint_confidence(
                            entry.surface.as_str(),
                            sentence.as_str(),
                            label.as_str(),
                        ),
                        reason,
                    });
                }
                continue;
            }
            let reason = if label_group(label.as_str()) == "person"
                && dialogue_speaker_hint(entry.surface.as_str(), sentence.as_str())
            {
                VoteReason::DialogueSpeaker
            } else {
                VoteReason::DependencyRole
            };
            let confidence = context_kind_hint_confidence(
                entry.surface.as_str(),
                sentence.as_str(),
                label.as_str(),
            );
            entry.votes.push(MentionVote {
                source: MentionSourceKind::NativeDiscovery,
                label: Some(label),
                entity_ref: None,
                confidence,
                reason,
            });
        }
    }

    fn kind_adjudication_case(
        &self,
        entry: &WorkspaceEntry,
        text: &str,
        sentences: &[SentenceSpan],
    ) -> AdjudicationCase {
        AdjudicationCase {
            mention_id: entry.id,
            task: InstructTask::SpanLabelChoice,
            surface: entry.surface.clone(),
            sentence_text: sentence_text(text, sentences, entry.sentence_index),
            neighbor_sentence: None,
            candidate_labels: candidate_labels_for_entry(entry, text, sentences),
            candidate_entities: SmallVec::new(),
        }
    }

    /// Next available mention id.
    pub fn next_id(&mut self) -> LocalMentionId {
        let id = LocalMentionId(self.next_id);
        self.next_id += 1;
        id
    }

    /// Finalize all entries into scored MentionPackets.
    pub fn finalize_packets(mut self) -> Vec<MentionPacket> {
        let mut entries = std::mem::take(&mut self.entries);
        Self::propagate_model_labels(&mut entries);
        Self::apply_surface_kind_priors(&mut entries);
        let mut packets = Vec::with_capacity(entries.len());

        for entry in entries {
            let (confidence, status) = self.score_entry(&entry);
            let label_distribution = Self::build_label_distribution(&entry.votes);

            packets.push(MentionPacket {
                mention_id: entry.id,
                document_id: self.document_id.clone(),
                chunk_id: None,
                sentence_index: entry.sentence_index,
                range: entry.range,
                surface: entry.surface,
                normalized: entry.normalized,
                mention_kind: entry.mention_kind,
                label_distribution,
                entity_ref: entry.entity_ref,
                source_votes: entry.votes,
                context: MentionContext::default(),
                syntax: None,
                semantics: MentionSemantics::default(),
                confidence,
                status,
            });
        }

        // Sort by range start for stable output.
        packets.sort_by_key(|p| p.range.start);
        packets
    }

    fn apply_surface_kind_priors(entries: &mut [WorkspaceEntry]) {
        let priors = Self::surface_kind_priors(entries);
        for entry in entries.iter_mut() {
            if entry.mention_kind != MentionKind::Named || entry_has_known_label(entry) {
                continue;
            }
            let (prior_label, prior_confidence, prior_has_known) =
                if let Some(prior) = priors.get(entry.normalized.as_str()) {
                    (prior.label.clone(), prior.confidence, prior.has_known)
                } else if let Some(prior) =
                    compound_alias_kind_prior(entry.normalized.as_str(), &priors)
                {
                    (
                        prior.label.clone(),
                        prior.confidence.max(0.78),
                        prior.has_known,
                    )
                } else {
                    continue;
                };
            if entry_has_label_group(entry, prior_label.as_str()) {
                continue;
            }
            if !prior_has_known && entry_has_strong_non_model_label(entry) {
                continue;
            }
            entry.votes.push(MentionVote {
                source: MentionSourceKind::NativeDiscovery,
                label: Some(prior_label),
                entity_ref: None,
                confidence: prior_confidence,
                reason: VoteReason::RepeatedSurface,
            });
        }
    }

    fn surface_kind_priors(
        entries: &[WorkspaceEntry],
    ) -> FxHashMap<CompactString, SurfaceKindPrior> {
        let mut evidence = FxHashMap::<CompactString, Vec<SurfaceLabelEvidence>>::default();
        for entry in entries {
            if entry.mention_kind != MentionKind::Named {
                continue;
            }
            for vote in &entry.votes {
                let Some(label) = vote.label.as_ref() else {
                    continue;
                };
                if !is_entity_label(label.as_str()) || vote.reason == VoteReason::RepeatedSurface {
                    continue;
                }
                let Some((weight, is_context, is_strong_context)) = surface_evidence_weight(vote)
                else {
                    continue;
                };
                upsert_surface_evidence(
                    evidence.entry(entry.normalized.clone()).or_default(),
                    label,
                    weight,
                    vote.source == MentionSourceKind::KnownLexicon,
                    is_context,
                    is_strong_context,
                );
            }
        }

        let mut priors = FxHashMap::<CompactString, SurfaceKindPrior>::default();
        for (surface, mut rows) in evidence {
            if let Some(context_top) = rows
                .iter()
                .filter(|row| row.strong_context_count > 0)
                .max_by(|left, right| {
                    left.score
                        .partial_cmp(&right.score)
                        .unwrap_or(std::cmp::Ordering::Equal)
                        .then_with(|| left.strong_context_count.cmp(&right.strong_context_count))
                })
            {
                priors.insert(
                    surface,
                    SurfaceKindPrior {
                        label: context_top.label.clone(),
                        confidence: (0.76 + context_top.strong_context_count.min(3) as f32 * 0.04)
                            .min(0.88),
                        has_known: false,
                    },
                );
                continue;
            }
            rows.sort_by(|left, right| {
                right
                    .score
                    .partial_cmp(&left.score)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| right.count.cmp(&left.count))
            });
            let Some(top) = rows.first() else {
                continue;
            };
            let runner_up = rows.get(1).map(|row| row.score).unwrap_or(0.0);
            let has_known = top.known_count > 0;
            let stable_repeat = top.count >= 2 && top.score >= runner_up + 0.45;
            if !has_known && !stable_repeat {
                continue;
            }
            let confidence = if has_known {
                0.86
            } else if top.count >= 6 && top.score >= runner_up + 1.2 {
                0.92
            } else if top.count >= 3 && top.score >= runner_up + 0.8 {
                0.86
            } else {
                (0.56 + top.count.min(5) as f32 * 0.04).min(0.78)
            };
            priors.insert(
                surface,
                SurfaceKindPrior {
                    label: top.label.clone(),
                    confidence,
                    has_known,
                },
            );
        }
        priors
    }

    fn propagate_model_labels(entries: &mut [WorkspaceEntry]) {
        let mut hints = FxHashMap::<CompactString, LabelHint>::default();
        for entry in entries.iter() {
            for vote in &entry.votes {
                let Some(label) = vote.label.as_ref() else {
                    continue;
                };
                if !is_surface_label_source(vote.source) || !is_entity_label(label.as_str()) {
                    continue;
                }
                let score = vote.confidence
                    + if vote.source == MentionSourceKind::KnownLexicon {
                        0.25
                    } else {
                        0.0
                    };
                let replace = hints
                    .get(entry.normalized.as_str())
                    .is_none_or(|hint| score > hint.confidence);
                if replace {
                    hints.insert(
                        entry.normalized.clone(),
                        LabelHint {
                            label: label.clone(),
                            confidence: score,
                        },
                    );
                }
            }
        }

        for entry in entries.iter_mut() {
            if entry.mention_kind != MentionKind::Named
                || entry.votes.iter().any(|vote| vote.label.is_some())
            {
                continue;
            }
            let Some(hint) = hints.get(entry.normalized.as_str()) else {
                continue;
            };
            entry.votes.push(MentionVote {
                source: MentionSourceKind::ModelVerify,
                label: Some(hint.label.clone()),
                entity_ref: None,
                confidence: hint.confidence.clamp(0.55, 0.72),
                reason: VoteReason::ModelLabel,
            });
        }
    }

    fn score_entry(&self, entry: &WorkspaceEntry) -> (f32, MentionStatus) {
        let mut score = 0.0_f32;
        let mut has_known = false;
        let mut has_model = false;
        let mut max_model_confidence = 0.0_f32;
        let mut has_contradiction = false;

        for vote in &entry.votes {
            score += self.score_table.weight(vote.reason) * vote.confidence;
            if vote.source == MentionSourceKind::KnownLexicon {
                has_known = true;
            }
            if matches!(
                vote.source,
                MentionSourceKind::ModelDiscovery | MentionSourceKind::ModelVerify
            ) {
                has_model = true;
                max_model_confidence = max_model_confidence.max(vote.confidence);
            }
            if vote.reason == VoteReason::NliContradiction {
                has_contradiction = true;
            }
        }

        let confidence = score.clamp(0.0, 1.0);

        let status = if has_contradiction && confidence < 0.3 {
            MentionStatus::Rejected
        } else if has_known && confidence >= 0.85 {
            MentionStatus::AcceptedKnown
        } else if confidence >= 0.65 {
            MentionStatus::AcceptedNew
        } else if (has_model && max_model_confidence >= 0.55) || confidence >= 0.45 {
            MentionStatus::AliasCandidate
        } else {
            MentionStatus::NeedsAdjudication
        };

        (confidence, status)
    }

    fn build_label_distribution(
        votes: &SmallVec<[MentionVote; 6]>,
    ) -> SmallVec<[(EntityLabel, f32); 4]> {
        let mut labels = Vec::<(EntityLabel, f32)>::new();
        for vote in votes {
            if let Some(label) = &vote.label {
                let weight = vote.confidence * label_distribution_vote_weight(vote);
                if let Some(existing) = labels.iter_mut().find(|(l, _)| l == label) {
                    existing.1 += weight;
                } else {
                    labels.push((label.clone(), weight));
                }
            }
        }
        labels.sort_by(|left, right| {
            right
                .1
                .partial_cmp(&left.1)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        labels.truncate(4);
        // Normalize to sum=1 if possible.
        let total: f32 = labels.iter().map(|(_, w)| *w).sum();
        if total > 0.0 {
            for (_, w) in labels.iter_mut() {
                *w /= total;
            }
        }
        SmallVec::from_vec(labels)
    }
}

fn label_distribution_vote_weight(vote: &MentionVote) -> f32 {
    match vote.reason {
        VoteReason::ExactCanonical | VoteReason::ExactAlias => 2.0,
        VoteReason::AutoAlias | VoteReason::FuzzyAnchor => 1.65,
        VoteReason::RepeatedSurface => 1.45,
        VoteReason::NliSupport => 1.25,
        VoteReason::DependencyRole | VoteReason::DialogueSpeaker => {
            if vote.confidence >= 0.80 {
                1.0
            } else {
                0.55
            }
        }
        VoteReason::ModelLabel | VoteReason::ModelSpan => 1.0,
        VoteReason::CapSpan | VoteReason::NominalRole => 0.85,
        VoteReason::TitlePattern => 0.75,
        VoteReason::NliContradiction | VoteReason::StopwordPenalty | VoteReason::GuardViolation => {
            0.0
        }
    }
}

fn surface_evidence_weight(vote: &MentionVote) -> Option<(f32, bool, bool)> {
    match vote.source {
        MentionSourceKind::KnownLexicon => Some((3.0 + vote.confidence, false, false)),
        MentionSourceKind::ModelDiscovery => Some((vote.confidence, false, false)),
        MentionSourceKind::NativeDiscovery
            if vote.label.is_some()
                && matches!(
                    vote.reason,
                    VoteReason::DependencyRole | VoteReason::DialogueSpeaker
                ) =>
        {
            let strong_context = vote.confidence >= 0.80;
            let score = if strong_context {
                0.65 + vote.confidence * 0.5
            } else {
                0.20 + vote.confidence * 0.25
            };
            Some((score, true, strong_context))
        }
        _ => None,
    }
}

fn upsert_surface_evidence(
    rows: &mut Vec<SurfaceLabelEvidence>,
    label: &EntityLabel,
    score: f32,
    is_known: bool,
    is_context: bool,
    is_strong_context: bool,
) {
    let group = label_group(label.as_str());
    if let Some(row) = rows
        .iter_mut()
        .find(|row| label_group(row.label.as_str()) == group)
    {
        row.score += score;
        row.count += 1;
        if is_known {
            row.known_count += 1;
            row.label = label.clone();
        }
        if is_context {
            row.context_count += 1;
            row.label = label.clone();
        }
        if is_strong_context {
            row.strong_context_count += 1;
            row.label = label.clone();
        }
    } else {
        rows.push(SurfaceLabelEvidence {
            label: label.clone(),
            score,
            count: 1,
            known_count: usize::from(is_known),
            context_count: usize::from(is_context),
            strong_context_count: usize::from(is_strong_context),
        });
    }
}

fn compound_alias_kind_prior<'a>(
    normalized: &str,
    priors: &'a FxHashMap<CompactString, SurfaceKindPrior>,
) -> Option<&'a SurfaceKindPrior> {
    let mut words = normalized.split_whitespace();
    let first = words.next()?;
    if words.next().is_none() {
        return None;
    }

    let exact_key = CompactString::from(first);
    if let Some(prior) = priors.get(&exact_key) {
        return Some(prior);
    }
    if first.len() < 4 {
        return None;
    }

    priors
        .iter()
        .filter_map(|(alias, prior)| {
            let alias = alias.as_str();
            if alias.len() < 4
                || alias.contains(' ')
                || first.len() <= alias.len() + 2
                || !first.starts_with(alias)
            {
                return None;
            }
            Some((alias.len(), prior))
        })
        .max_by_key(|(len, _)| *len)
        .map(|(_, prior)| prior)
}

fn entry_has_known_label(entry: &WorkspaceEntry) -> bool {
    entry
        .votes
        .iter()
        .any(|vote| vote.source == MentionSourceKind::KnownLexicon && vote.label.is_some())
}

fn entry_has_strong_non_model_label(entry: &WorkspaceEntry) -> bool {
    entry.votes.iter().any(|vote| {
        vote.label.is_some()
            && !matches!(
                vote.source,
                MentionSourceKind::ModelDiscovery | MentionSourceKind::ModelVerify
            )
            && !is_weak_context_vote(vote)
            && matches!(
                vote.reason,
                VoteReason::ExactCanonical
                    | VoteReason::ExactAlias
                    | VoteReason::AutoAlias
                    | VoteReason::FuzzyAnchor
                    | VoteReason::DependencyRole
                    | VoteReason::DialogueSpeaker
                    | VoteReason::NliSupport
            )
    })
}

fn is_weak_context_vote(vote: &MentionVote) -> bool {
    vote.source == MentionSourceKind::NativeDiscovery
        && matches!(
            vote.reason,
            VoteReason::DependencyRole | VoteReason::DialogueSpeaker
        )
        && vote.confidence < 0.80
}

fn entry_has_label_group(entry: &WorkspaceEntry, label: &str) -> bool {
    let group = label_group(label);
    entry.votes.iter().any(|vote| {
        vote.label
            .as_ref()
            .is_some_and(|existing| label_group(existing.as_str()) == group)
    })
}

fn label_group(label: &str) -> &'static str {
    match label.to_ascii_lowercase().as_str() {
        "character" | "person" | "npc" => "person",
        "creature" | "species" | "monster" | "nonhuman" | "denizen" => "creature",
        "organization" | "faction" | "alliance" | "department" => "organization",
        "location" | "region" | "landmark" => "location",
        "artifact" | "item" | "weapon" => "item",
        "ability" | "spell" => "ability",
        "event" => "event",
        "concept" | "rank" | "role" | "title" | "state" | "goal" | "relationship" | "emotion"
        | "theory" | "method" | "metric" | "risk" => "concept",
        _ => "other",
    }
}

fn kind_adjudication_priority(
    entry: &WorkspaceEntry,
    text: &str,
    sentences: &[SentenceSpan],
) -> Option<u16> {
    if entry.mention_kind != MentionKind::Named
        || entry_has_known_label(entry)
        || entry
            .votes
            .iter()
            .any(|vote| vote.source == MentionSourceKind::Adjudication)
    {
        return None;
    }

    let sentence = sentence_text(text, sentences, entry.sentence_index);
    let groups = label_groups_for_entry(entry);
    if groups.len() > 1 {
        return Some(120 + groups.len().min(4) as u16);
    }

    if let Some(hint) = surface_kind_hint(entry.surface.as_str(), sentence.as_str()) {
        let hint_group = label_group(hint.as_str());
        if groups.is_empty() {
            return Some(88);
        }
        if groups.iter().any(|group| *group != hint_group) {
            return Some(110);
        }
    }

    if dialogue_speaker_hint(entry.surface.as_str(), sentence.as_str())
        && groups.iter().any(|group| *group != "person")
    {
        return Some(104);
    }

    let has_repeated = entry
        .votes
        .iter()
        .any(|vote| vote.reason == VoteReason::RepeatedSurface);
    let has_model = entry.votes.iter().any(|vote| {
        matches!(
            vote.source,
            MentionSourceKind::ModelDiscovery | MentionSourceKind::ModelVerify
        )
    });
    if has_repeated && (!has_model || groups.is_empty()) {
        return Some(72);
    }

    None
}

fn candidate_labels_for_entry(
    entry: &WorkspaceEntry,
    text: &str,
    sentences: &[SentenceSpan],
) -> SmallVec<[EntityLabel; 4]> {
    let sentence = sentence_text(text, sentences, entry.sentence_index);
    let mut labels = SmallVec::<[EntityLabel; 4]>::new();
    for vote in &entry.votes {
        let Some(label) = vote.label.as_ref() else {
            continue;
        };
        push_unique_label(&mut labels, canonical_kind_label(label.as_str()));
    }
    if let Some(label) = surface_kind_hint(entry.surface.as_str(), sentence.as_str()) {
        push_unique_label(&mut labels, label);
    }
    for fallback in [
        "Character",
        "Organization",
        "Location",
        "Creature",
        "Concept",
        "Event",
        "Artifact",
    ] {
        if labels.len() >= 4 {
            break;
        }
        push_unique_label(&mut labels, EntityLabel::new(fallback));
    }
    labels
}

fn push_unique_label(labels: &mut SmallVec<[EntityLabel; 4]>, label: EntityLabel) {
    let group = label_group(label.as_str());
    if labels
        .iter()
        .any(|existing| label_group(existing.as_str()) == group)
    {
        return;
    }
    labels.push(label);
}

fn label_groups_for_entry(entry: &WorkspaceEntry) -> SmallVec<[&'static str; 4]> {
    let mut groups = SmallVec::<[&'static str; 4]>::new();
    for vote in &entry.votes {
        let Some(label) = vote.label.as_ref() else {
            continue;
        };
        let group = label_group(label.as_str());
        if group == "other" || groups.contains(&group) {
            continue;
        }
        groups.push(group);
    }
    groups
}

fn canonical_kind_label(label: &str) -> EntityLabel {
    match label_group(label) {
        "person" => EntityLabel::new("Character"),
        "organization" => EntityLabel::new("Organization"),
        "location" => EntityLabel::new("Location"),
        "event" => EntityLabel::new("Event"),
        "item" => EntityLabel::new("Artifact"),
        "ability" => EntityLabel::new("Ability"),
        "creature" => EntityLabel::new("Creature"),
        "concept" => EntityLabel::new("Concept"),
        _ => EntityLabel::new(label),
    }
}

fn surface_kind_hint(surface: &str, sentence: &str) -> Option<EntityLabel> {
    let normalized = surface.to_ascii_lowercase();
    let normalized_sentence = normalize_context_sentence(sentence);
    if let Some(label) = role_or_species_surface_hint(surface) {
        return Some(label);
    }
    if item_context_hint(&normalized, &normalized_sentence) {
        return Some(EntityLabel::new("Artifact"));
    }
    if organization_context_hint(&normalized, &normalized_sentence) {
        return Some(EntityLabel::new("Organization"));
    }
    if strong_location_context_hint(&normalized, &normalized_sentence) {
        return Some(EntityLabel::new("Location"));
    }
    if person_context_hint(&normalized, &normalized_sentence)
        || dialogue_speaker_hint(surface, sentence)
    {
        return Some(EntityLabel::new("Character"));
    }
    if dialogue_speaker_hint(surface, sentence) {
        return Some(EntityLabel::new("Character"));
    }
    if contains_kind_cue(&normalized, ORG_CUES) {
        return Some(EntityLabel::new("Organization"));
    }
    if contains_kind_cue(&normalized, LOCATION_CUES) {
        return Some(EntityLabel::new("Location"));
    }
    if contains_kind_cue(&normalized, ROLE_CUES) {
        return Some(EntityLabel::new("NPC"));
    }
    if contains_kind_cue(&normalized, CREATURE_CUES) {
        return Some(EntityLabel::new("Creature"));
    }
    if contains_kind_cue(&normalized, CONCEPT_CUES) {
        return Some(EntityLabel::new("Concept"));
    }
    if weak_location_context_hint(&normalized, &normalized_sentence) {
        return Some(EntityLabel::new("Location"));
    }
    None
}

fn should_reinforce_context_hint(surface: &str, sentence: &str, label: &str) -> bool {
    let normalized = surface.to_ascii_lowercase();
    let normalized_sentence = normalize_context_sentence(sentence);
    match label_group(label) {
        "person" => {
            person_context_hint(&normalized, &normalized_sentence)
                || dialogue_speaker_hint(surface, sentence)
        }
        "concept" => contains_kind_cue(&normalized, CONCEPT_CUES),
        "creature" => contains_kind_cue(&normalized, CREATURE_CUES),
        _ => false,
    }
}

fn context_kind_hint_confidence(surface: &str, sentence: &str, label: &str) -> f32 {
    let normalized = surface.to_ascii_lowercase();
    let normalized_sentence = normalize_context_sentence(sentence);
    match label_group(label) {
        "person" if person_context_hint(&normalized, &normalized_sentence) => 0.90,
        "person" if dialogue_speaker_hint(surface, sentence) => 0.88,
        "location" if strong_location_context_hint(&normalized, &normalized_sentence) => 0.84,
        "location" if weak_location_context_hint(&normalized, &normalized_sentence) => 0.46,
        "item" if item_context_hint(&normalized, &normalized_sentence) => 0.88,
        "concept" if contains_kind_cue(&normalized, CONCEPT_CUES) => 1.0,
        "creature" if contains_kind_cue(&normalized, CREATURE_CUES) => 0.92,
        _ => 0.82,
    }
}

fn normalize_context_sentence(value: &str) -> String {
    value
        .to_ascii_lowercase()
        .replace(['\u{2018}', '\u{2019}'], "'")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn organization_context_hint(surface: &str, sentence: &str) -> bool {
    if surface.is_empty() || !sentence.contains(surface) {
        return false;
    }
    if role_or_species_surface_hint(surface).is_some() {
        return false;
    }
    let possessive = format!("{surface}'");
    if phrase(sentence, &format!("{surface} corporation"))
        || phrase(sentence, &format!("{surface} company"))
        || phrase(sentence, &format!("{surface} organization"))
        || phrase(sentence, &format!("{surface} security"))
        || phrase(sentence, &format!("{surface} gang"))
        || phrase(sentence, &format!("{surface} faction"))
        || phrase(sentence, &format!("{surface} division"))
        || phrase(sentence, &format!("the {surface} corporation"))
        || phrase(sentence, &format!("the {surface} company"))
        || phrase(sentence, &format!("the {surface} organization"))
        || phrase(sentence, &format!("represent the {surface}"))
        || phrase(sentence, &format!("represents the {surface}"))
        || phrase(sentence, &format!("belong to a group called {surface}"))
        || phrase(sentence, &format!("belongs to a group called {surface}"))
        || phrase(sentence, &format!("group called {surface}"))
        || phrase(sentence, &format!("members of {surface}"))
        || phrase(sentence, &format!("member of {surface}"))
        || phrase(sentence, &format!("on {surface} payroll"))
        || phrase(sentence, &format!("on {surface}'s payroll"))
        || phrase(sentence, &format!("on {possessive} payroll"))
    {
        return true;
    }
    contains_kind_cue(surface, ORG_CUES)
}

fn item_context_hint(surface: &str, sentence: &str) -> bool {
    if surface.is_empty() || !sentence.contains(surface) {
        return false;
    }
    phrase(sentence, &format!("sell {surface} to"))
        || phrase(sentence, &format!("sell {surface} there"))
        || phrase(sentence, &format!("sell {surface} anymore"))
        || phrase(sentence, &format!("peddled {surface}"))
        || phrase(sentence, &format!("gram of {surface}"))
        || phrase(sentence, &format!("smelled of {surface}"))
        || phrase(sentence, &format!("doses of {surface}"))
        || phrase(sentence, &format!("{surface} drug"))
        || phrase(sentence, &format!("{surface} business"))
        || phrase(sentence, &format!("{surface} supply"))
        || phrase(sentence, &format!("{surface} addicts"))
        || phrase(sentence, &format!("no {surface} allowed"))
        || phrase(sentence, &format!("produces their {surface}"))
}

fn strong_location_context_hint(surface: &str, sentence: &str) -> bool {
    if surface.is_empty() || !sentence.contains(surface) {
        return false;
    }
    if phrase(sentence, &format!("city called {surface}"))
        || phrase(sentence, &format!("city called the {surface}"))
        || phrase(sentence, &format!("casino called {surface}"))
        || phrase(sentence, &format!("casino called the {surface}"))
        || phrase(sentence, &format!("landmark called {surface}"))
        || phrase(sentence, &format!("landmark called the {surface}"))
        || phrase(sentence, &format!("address called {surface}"))
        || phrase(sentence, &format!("area called {surface}"))
        || phrase(sentence, &format!("district called {surface}"))
        || phrase(sentence, &format!("{surface} access"))
        || phrase(sentence, &format!("{surface} interior"))
        || phrase(sentence, &format!("{surface} proper"))
    {
        return true;
    }
    if LOCATION_CUES
        .iter()
        .any(|cue| phrase_with_trailing_boundary(sentence, &format!("{surface} {cue}")))
    {
        return true;
    }
    contains_kind_cue(surface, LOCATION_CUES)
}

fn weak_location_context_hint(surface: &str, sentence: &str) -> bool {
    if surface.is_empty() || !sentence.contains(surface) {
        return false;
    }
    phrase(sentence, &format!("into {surface}"))
        || phrase(sentence, &format!("through {surface}"))
        || phrase(sentence, &format!("from {surface}"))
        || phrase(sentence, &format!("inside {surface}"))
}

fn role_or_species_surface_hint(surface: &str) -> Option<EntityLabel> {
    let normalized = surface.trim().to_ascii_lowercase();
    if normalized.is_empty() {
        return None;
    }
    if is_capitalized_family_alias(surface) {
        return Some(EntityLabel::new("Character"));
    }
    if contains_kind_cue(&normalized, ROLE_CUES) {
        return Some(EntityLabel::new("NPC"));
    }
    if contains_kind_cue(&normalized, CREATURE_CUES) {
        return Some(EntityLabel::new("Creature"));
    }
    None
}

fn is_capitalized_family_alias(surface: &str) -> bool {
    let trimmed = surface.trim();
    let Some(first) = trimmed.chars().next() else {
        return false;
    };
    first.is_ascii_uppercase()
        && matches!(
            trimmed.to_ascii_lowercase().as_str(),
            "dad" | "mom" | "mum" | "father" | "mother" | "uncle" | "aunt"
        )
}

fn person_context_hint(surface: &str, sentence: &str) -> bool {
    if surface.is_empty() || !sentence.contains(surface) {
        return false;
    }
    if phrase(sentence, &format!("my name is {surface}"))
        || phrase(sentence, &format!("name is {surface}"))
        || phrase(sentence, &format!("i'm {surface}"))
        || phrase(sentence, &format!("i am {surface}"))
        || phrase(sentence, &format!("{surface} introduced herself"))
        || phrase(sentence, &format!("{surface} introduced himself"))
        || phrase(sentence, &format!("{surface} replied"))
        || phrase(sentence, &format!("{surface} answered"))
        || phrase(sentence, &format!("{surface} asked"))
        || phrase(sentence, &format!("{surface} told"))
        || phrase(sentence, &format!("{surface} said"))
        || phrase(sentence, &format!("{surface} laughed"))
        || phrase(sentence, &format!("{surface} admitted"))
        || phrase(sentence, &format!("{surface} insisted"))
        || phrase(sentence, &format!("{surface} recognized"))
    {
        return true;
    }
    if ROLE_CUES
        .iter()
        .any(|cue| phrase(sentence, &format!("{cue} called {surface}")))
    {
        return true;
    }
    ROLE_CUES.iter().any(|cue| {
        phrase(sentence, &format!("{surface}, a {cue}"))
            || phrase(sentence, &format!("{surface}, an {cue}"))
            || phrase(sentence, &format!("{surface}, the {cue}"))
    })
}

fn phrase(sentence: &str, value: &str) -> bool {
    sentence.contains(value)
}

fn phrase_with_trailing_boundary(sentence: &str, value: &str) -> bool {
    let mut offset = 0usize;
    while let Some(found) = sentence[offset..].find(value) {
        let end = offset + found + value.len();
        let boundary = sentence[end..]
            .chars()
            .next()
            .is_none_or(|ch| !ch.is_ascii_alphanumeric());
        if boundary {
            return true;
        }
        offset = end;
    }
    false
}

fn contains_kind_cue(surface: &str, cues: &[&str]) -> bool {
    cues.iter().any(|cue| {
        surface
            .split(|ch: char| !ch.is_ascii_alphanumeric())
            .any(|word| !word.is_empty() && word == *cue)
    })
}

fn dialogue_speaker_hint(surface: &str, sentence: &str) -> bool {
    let surface = surface.trim().to_ascii_lowercase();
    if surface.is_empty() {
        return false;
    }
    let sentence = sentence.to_ascii_lowercase();
    let cues = [
        "said",
        "asked",
        "told",
        "replied",
        "answered",
        "whispered",
        "shouted",
    ];
    cues.iter().any(|cue| {
        sentence.starts_with(&format!("{surface} {cue}"))
            || sentence.contains(&format!(" {surface} {cue}"))
    })
}

fn sentence_text(text: &str, sentences: &[SentenceSpan], sentence_index: u32) -> CompactString {
    sentences
        .get(sentence_index as usize)
        .and_then(|sentence| text.get(sentence.range.start as usize..sentence.range.end as usize))
        .map(str::trim)
        .unwrap_or_default()
        .into()
}

const ORG_CUES: &[&str] = &[
    "academy",
    "alliance",
    "allied",
    "association",
    "business",
    "clan",
    "committee",
    "company",
    "corporation",
    "council",
    "department",
    "division",
    "faction",
    "family",
    "gang",
    "guild",
    "institute",
    "mafia",
    "order",
    "security",
    "society",
    "table",
    "team",
];

const LOCATION_CUES: &[&str] = &[
    "base", "camp", "city", "country", "district", "fort", "germany", "kingdom", "land", "mesa",
    "mount", "province", "region", "river", "station", "tower", "town", "valley",
];

const ROLE_CUES: &[&str] = &[
    "adventurer",
    "assassin",
    "boss",
    "boy",
    "caller",
    "citizen",
    "civilian",
    "courier",
    "denizen",
    "elder",
    "employee",
    "genome",
    "genomes",
    "genius",
    "girl",
    "guard",
    "healer",
    "mage",
    "man",
    "merchant",
    "mutant",
    "priest",
    "psycho",
    "soldier",
    "superhero",
    "superheroine",
    "teenager",
    "vendor",
    "warrior",
    "woman",
];

const CREATURE_CUES: &[&str] = &[
    "devil", "devils", "dwarf", "dwarves", "mongrel", "mongrels", "titan", "titans",
];

const CONCEPT_CUES: &[&str] = &[
    "boundary",
    "claim",
    "field",
    "force",
    "law",
    "principle",
    "rank",
    "rule",
    "state",
    "system",
    "theory",
];

fn is_surface_label_source(source: MentionSourceKind) -> bool {
    matches!(
        source,
        MentionSourceKind::KnownLexicon
            | MentionSourceKind::ModelDiscovery
            | MentionSourceKind::ModelVerify
    )
}

fn is_entity_label(label: &str) -> bool {
    matches!(
        label.to_ascii_lowercase().as_str(),
        "character"
            | "person"
            | "npc"
            | "creature"
            | "species"
            | "monster"
            | "nonhuman"
            | "denizen"
            | "organization"
            | "faction"
            | "location"
            | "region"
            | "landmark"
            | "event"
            | "artifact"
            | "item"
            | "weapon"
            | "ability"
            | "spell"
            | "concept"
            | "rank"
            | "role"
            | "state"
            | "goal"
            | "relationship"
            | "theory"
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::VoteReason;

    #[test]
    fn score_table_positive_weights() {
        let table = ScoreTable::default();
        assert!(table.weight(VoteReason::ExactCanonical) > 0.0);
        assert!(table.weight(VoteReason::CapSpan) > 0.0);
    }

    #[test]
    fn score_table_negative_penalties() {
        let table = ScoreTable::default();
        assert!(table.weight(VoteReason::NliContradiction) < 0.0);
        assert!(table.weight(VoteReason::StopwordPenalty) < 0.0);
        assert!(table.weight(VoteReason::GuardViolation) < 0.0);
    }

    #[test]
    fn workspace_finalize_produces_sorted_packets() {
        let mut ws = MentionWorkspace::new("doc1", 0);
        ws.entries.push(WorkspaceEntry {
            id: LocalMentionId(1),
            range: phoenix_types::TextRange { start: 20, end: 30 },
            surface: CompactString::from("Adrian"),
            normalized: CompactString::from("adrian"),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::NativeDiscovery,
                    label: None,
                    entity_ref: None,
                    confidence: 0.78,
                    reason: VoteReason::CapSpan,
                },
                1,
            ),
            sentence_index: 0,
        });
        ws.entries.push(WorkspaceEntry {
            id: LocalMentionId(0),
            range: phoenix_types::TextRange { start: 0, end: 7 },
            surface: CompactString::from("Kamaria"),
            normalized: CompactString::from("kamaria"),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::KnownLexicon,
                    label: None,
                    entity_ref: None,
                    confidence: 1.0,
                    reason: VoteReason::ExactCanonical,
                },
                1,
            ),
            sentence_index: 0,
        });
        let packets = ws.finalize_packets();
        assert_eq!(packets.len(), 2);
        assert!(packets[0].range.start < packets[1].range.start);
    }

    #[test]
    fn known_entity_gets_accepted_known_status() {
        let mut ws = MentionWorkspace::new("doc1", 0);
        ws.entries.push(WorkspaceEntry {
            id: LocalMentionId(0),
            range: phoenix_types::TextRange { start: 0, end: 7 },
            surface: CompactString::from("Kamaria"),
            normalized: CompactString::from("kamaria"),
            mention_kind: MentionKind::Named,
            entity_ref: Some(MentionEntityRef::Known(phoenix_types::EntityId(
                "k1".into(),
            ))),
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::KnownLexicon,
                    label: Some(EntityLabel::new("Character")),
                    entity_ref: Some(MentionEntityRef::Known(phoenix_types::EntityId(
                        "k1".into(),
                    ))),
                    confidence: 1.0,
                    reason: VoteReason::ExactCanonical,
                },
                1,
            ),
            sentence_index: 0,
        });
        let packets = ws.finalize_packets();
        assert_eq!(packets[0].status, MentionStatus::AcceptedKnown);
        assert!(packets[0].confidence >= 0.95);
    }

    #[test]
    fn contradiction_drops_to_rejected() {
        let mut ws = MentionWorkspace::new("doc1", 0);
        let mut votes = SmallVec::new();
        votes.push(MentionVote {
            source: MentionSourceKind::NativeDiscovery,
            label: None,
            entity_ref: None,
            confidence: 0.5,
            reason: VoteReason::CapSpan,
        });
        votes.push(MentionVote {
            source: MentionSourceKind::Adjudication,
            label: None,
            entity_ref: None,
            confidence: 1.0,
            reason: VoteReason::NliContradiction,
        });
        ws.entries.push(WorkspaceEntry {
            id: LocalMentionId(0),
            range: phoenix_types::TextRange { start: 0, end: 5 },
            surface: CompactString::from("the"),
            normalized: CompactString::from("the"),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes,
            sentence_index: 0,
        });
        let packets = ws.finalize_packets();
        assert_eq!(packets[0].status, MentionStatus::Rejected);
    }

    #[test]
    fn weak_native_cap_span_needs_adjudication() {
        let mut ws = MentionWorkspace::new("doc1", 0);
        ws.entries.push(WorkspaceEntry {
            id: LocalMentionId(0),
            range: phoenix_types::TextRange { start: 0, end: 7 },
            surface: CompactString::from("Output"),
            normalized: CompactString::from("output"),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::NativeDiscovery,
                    label: None,
                    entity_ref: None,
                    confidence: 0.78,
                    reason: VoteReason::CapSpan,
                },
                1,
            ),
            sentence_index: 0,
        });
        let packets = ws.finalize_packets();
        assert_eq!(packets[0].status, MentionStatus::NeedsAdjudication);
        assert!(packets[0].confidence < 0.45);
    }

    #[test]
    fn model_label_propagates_to_same_surface_native_mentions() {
        let mut ws = MentionWorkspace::new("doc1", 0);
        ws.entries.push(WorkspaceEntry {
            id: LocalMentionId(0),
            range: phoenix_types::TextRange { start: 0, end: 4 },
            surface: CompactString::from("Ryan"),
            normalized: CompactString::from("ryan"),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::ModelDiscovery,
                    label: Some(EntityLabel::new("Character")),
                    entity_ref: None,
                    confidence: 0.82,
                    reason: VoteReason::ModelLabel,
                },
                1,
            ),
            sentence_index: 0,
        });
        ws.entries.push(WorkspaceEntry {
            id: LocalMentionId(1),
            range: phoenix_types::TextRange { start: 20, end: 24 },
            surface: CompactString::from("Ryan"),
            normalized: CompactString::from("ryan"),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::NativeDiscovery,
                    label: None,
                    entity_ref: None,
                    confidence: 0.78,
                    reason: VoteReason::CapSpan,
                },
                1,
            ),
            sentence_index: 1,
        });

        let packets = ws.finalize_packets();
        let propagated = packets
            .iter()
            .find(|packet| packet.mention_id == LocalMentionId(1))
            .unwrap();
        assert!(propagated
            .label_distribution
            .iter()
            .any(|(label, _)| label.as_str() == "Character"));
        assert_eq!(propagated.status, MentionStatus::AliasCandidate);
    }

    #[test]
    fn known_surface_kind_prior_resists_conflicting_model_label() {
        let mut ws = MentionWorkspace::new("doc1", 0);
        ws.entries.push(WorkspaceEntry {
            id: LocalMentionId(0),
            range: phoenix_types::TextRange { start: 0, end: 6 },
            surface: CompactString::from("Cyoria"),
            normalized: CompactString::from("cyoria"),
            mention_kind: MentionKind::Named,
            entity_ref: Some(MentionEntityRef::Known(phoenix_types::EntityId(
                "cyoria".into(),
            ))),
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::KnownLexicon,
                    label: Some(EntityLabel::new("Location")),
                    entity_ref: Some(MentionEntityRef::Known(phoenix_types::EntityId(
                        "cyoria".into(),
                    ))),
                    confidence: 1.0,
                    reason: VoteReason::ExactCanonical,
                },
                1,
            ),
            sentence_index: 0,
        });
        ws.entries.push(WorkspaceEntry {
            id: LocalMentionId(1),
            range: phoenix_types::TextRange { start: 20, end: 26 },
            surface: CompactString::from("Cyoria"),
            normalized: CompactString::from("cyoria"),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::ModelDiscovery,
                    label: Some(EntityLabel::new("Person")),
                    entity_ref: None,
                    confidence: 0.74,
                    reason: VoteReason::ModelLabel,
                },
                1,
            ),
            sentence_index: 1,
        });

        let packets = ws.finalize_packets();
        let contested = packets
            .iter()
            .find(|packet| packet.mention_id == LocalMentionId(1))
            .unwrap();

        assert_eq!(contested.label_distribution[0].0.as_str(), "Location");
        assert!(contested.source_votes.iter().any(|vote| {
            vote.reason == VoteReason::RepeatedSurface
                && vote
                    .label
                    .as_ref()
                    .is_some_and(|label| label.as_str() == "Location")
        }));
    }

    #[test]
    fn context_kind_hints_relabel_story_roles_without_name_patches() {
        let text = "Have you seen a girl called Len? I represent the Augusti. The casino called the Bakuto stayed open.";
        let sentences = vec![
            SentenceSpan {
                index: 0,
                range: phoenix_types::TextRange { start: 0, end: 34 },
            },
            SentenceSpan {
                index: 1,
                range: phoenix_types::TextRange { start: 35, end: 59 },
            },
            SentenceSpan {
                index: 2,
                range: phoenix_types::TextRange {
                    start: 60,
                    end: text.len() as u32,
                },
            },
        ];
        let mut ws = MentionWorkspace::new("doc1", 0);
        for (id, surface, start, sentence_index, bad_label) in [
            (0, "Len", 29, 0, "Creature"),
            (1, "Augusti", 51, 1, "Person"),
            (2, "Bakuto", 86, 2, "Person"),
        ] {
            ws.entries.push(WorkspaceEntry {
                id: LocalMentionId(id),
                range: phoenix_types::TextRange {
                    start,
                    end: start + surface.len() as u32,
                },
                surface: CompactString::from(surface),
                normalized: CompactString::from(surface.to_ascii_lowercase()),
                mention_kind: MentionKind::Named,
                entity_ref: None,
                votes: SmallVec::from_elem(
                    MentionVote {
                        source: MentionSourceKind::ModelDiscovery,
                        label: Some(EntityLabel::new(bad_label)),
                        entity_ref: None,
                        confidence: 0.70,
                        reason: VoteReason::ModelLabel,
                    },
                    1,
                ),
                sentence_index,
            });
        }

        ws.apply_context_kind_hints(text, &sentences);
        let packets = ws.finalize_packets();

        assert_eq!(packets[0].label_distribution[0].0.as_str(), "Character");
        assert_eq!(packets[1].label_distribution[0].0.as_str(), "Organization");
        assert_eq!(packets[2].label_distribution[0].0.as_str(), "Location");
    }

    #[test]
    fn role_apposition_reinforces_person_prior_over_wrong_repeated_location() {
        let text = "Rook, a Psycho from the Red Pack. Rook escaped. Rook froze the door.";
        let sentences = test_sentence_spans(text);
        let mut ws = MentionWorkspace::new("doc1", 0);
        ws.entries
            .push(model_entry_with_confidence(0, "Rook", "Person", 0, 0.64));
        ws.entries
            .push(model_entry_with_confidence(1, "Rook", "Location", 1, 0.70));
        ws.entries
            .push(model_entry_with_confidence(2, "Rook", "Location", 2, 0.70));

        ws.apply_context_kind_hints(text, &sentences);
        let packets = ws.finalize_packets();

        for packet in packets
            .iter()
            .filter(|packet| packet.surface.as_str() == "Rook")
        {
            assert_eq!(
                label_group(packet.label_distribution[0].0.as_str()),
                "person",
                "{:?}",
                packet.source_votes
            );
        }
    }

    #[test]
    fn repeated_person_surface_beats_weak_preposition_location_drift() {
        let text = "Ryan said hello. Ryan laughed. Fortuna heard from Ryan. Ryan thanked everyone.";
        let sentences = test_sentence_spans(text);
        let mut ws = MentionWorkspace::new("doc1", 0);
        for (id, label, sentence_index) in [
            (0, "Person", 0),
            (1, "Person", 1),
            (2, "Location", 2),
            (3, "Person", 3),
        ] {
            ws.entries.push(model_entry_with_confidence(
                id,
                "Ryan",
                label,
                sentence_index,
                0.72,
            ));
        }
        ws.entries
            .iter_mut()
            .find(|entry| entry.id == LocalMentionId(2))
            .expect("weak location entry")
            .votes
            .push(MentionVote {
                source: MentionSourceKind::NativeDiscovery,
                label: Some(EntityLabel::new("Location")),
                entity_ref: None,
                confidence: 0.46,
                reason: VoteReason::DependencyRole,
            });

        ws.apply_context_kind_hints(text, &sentences);
        let packets = ws.finalize_packets();

        for packet in packets
            .iter()
            .filter(|packet| packet.surface.as_str() == "Ryan")
        {
            assert_eq!(
                label_group(packet.label_distribution[0].0.as_str()),
                "person",
                "{:?}",
                packet.source_votes
            );
        }
    }

    #[test]
    fn role_class_surfaces_beat_weak_place_and_group_context() {
        let text = "Dad will return. The Genomes came from Rust Town. A Psycho gang moved in. Mongrel hissed.";
        let sentences = test_sentence_spans(text);
        let mut ws = MentionWorkspace::new("doc1", 0);
        for (id, surface, bad_label, sentence_index) in [
            (0, "Dad", "Location", 0),
            (1, "Genomes", "Location", 1),
            (2, "Psycho", "Organization", 2),
            (3, "Mongrel", "Location", 3),
        ] {
            ws.entries.push(model_entry_with_confidence(
                id,
                surface,
                bad_label,
                sentence_index,
                0.72,
            ));
        }

        ws.apply_context_kind_hints(text, &sentences);
        let packets = ws.finalize_packets();

        assert_eq!(packet_label_group(&packets, "Dad"), "person");
        assert!(matches!(
            packet_label_group(&packets, "Genomes"),
            "person" | "creature"
        ));
        assert_eq!(packet_label_group(&packets, "Psycho"), "person");
        assert_eq!(packet_label_group(&packets, "Mongrel"), "creature");
    }

    #[test]
    fn substance_context_relabels_named_drug_as_item() {
        let text = "Dealers sell Bliss. Ryan smelled of Bliss. The Bliss drug spread.";
        let sentences = test_sentence_spans(text);
        let mut ws = MentionWorkspace::new("doc1", 0);
        for (id, sentence_index) in [(0, 0), (1, 1), (2, 2)] {
            ws.entries.push(model_entry_with_confidence(
                id,
                "Bliss",
                "Location",
                sentence_index,
                0.72,
            ));
        }

        ws.apply_context_kind_hints(text, &sentences);
        let packets = ws.finalize_packets();

        for packet in packets
            .iter()
            .filter(|packet| packet.surface.as_str() == "Bliss")
        {
            assert_eq!(
                label_group(packet.label_distribution[0].0.as_str()),
                "item",
                "{:?}",
                packet.source_votes
            );
        }
    }

    #[test]
    fn location_context_repairs_repeated_place_surface_without_name_patch() {
        let text = "The Red Arcadia interior had settled around the Kharon Vel access. The gate opened into Kharon Vel proper. Kharon Vel had lunch.";
        let sentences = test_sentence_spans(text);
        let mut ws = MentionWorkspace::new("doc1", 0);
        for (id, surface, sentence_index, bad_label) in [
            (0, "Red Arcadia", 0, "Organization"),
            (1, "Kharon Vel", 0, "Person"),
            (2, "Kharon Vel", 1, "Person"),
            (3, "Kharon Vel", 2, "Person"),
        ] {
            ws.entries
                .push(model_entry(id, surface, bad_label, sentence_index));
        }

        ws.apply_context_kind_hints(text, &sentences);
        let packets = ws.finalize_packets();

        for surface in ["Red Arcadia", "Kharon Vel"] {
            let labels = packets
                .iter()
                .filter(|packet| packet.surface.as_str() == surface)
                .map(|packet| packet.label_distribution[0].0.as_str())
                .collect::<Vec<_>>();
            assert!(
                labels.iter().all(|label| *label == "Location"),
                "{surface} labels: {labels:?}"
            );
        }
    }

    #[test]
    fn place_suffix_context_relabels_duplicate_native_cap_spans() {
        let text = "The highway linked the city to the rest of the Campania region.";
        let sentences = test_sentence_spans(text);
        let mut ws = MentionWorkspace::new("doc1", 0);
        ws.entries.push(native_cap_entry(0, "Campania", 0));
        ws.entries.push(native_cap_entry(1, "Campania", 0));

        ws.apply_context_kind_hints(text, &sentences);
        let packets = ws.finalize_packets();
        let labels = packets
            .iter()
            .filter(|packet| packet.surface.as_str() == "Campania")
            .map(|packet| packet.label_distribution[0].0.as_str())
            .collect::<Vec<_>>();

        assert_eq!(labels.len(), 2);
        assert!(
            labels.iter().all(|label| *label == "Location"),
            "Campania labels: {labels:?}"
        );
        assert!(!strong_location_context_hint(
            "acid rain",
            "acid rain towered over him like an angel of death."
        ));
    }

    #[test]
    fn abstract_and_species_cues_repair_kind_without_name_patch() {
        let text = "The room held a full city's worth of Boundary Lattice. A dwarf argued by the ramp. A devil woman carried a parcel.";
        let sentences = test_sentence_spans(text);
        let mut ws = MentionWorkspace::new("doc1", 0);
        let mut boundary = model_entry_with_confidence(0, "Boundary Lattice", "Creature", 0, 0.95);
        boundary.votes.push(MentionVote {
            source: MentionSourceKind::ModelDiscovery,
            label: Some(EntityLabel::new("Concept")),
            entity_ref: None,
            confidence: 0.52,
            reason: VoteReason::ModelLabel,
        });
        ws.entries.push(boundary);
        ws.entries.push(model_entry(1, "dwarf", "Artifact", 1));
        ws.entries
            .push(model_entry(2, "devil woman", "Creature", 2));

        ws.apply_context_kind_hints(text, &sentences);
        let packets = ws.finalize_packets();
        let boundary = packets
            .iter()
            .find(|packet| packet.surface.as_str() == "Boundary Lattice")
            .unwrap();
        let dwarf = packets
            .iter()
            .find(|packet| packet.surface.as_str() == "dwarf")
            .unwrap();
        let devil_woman = packets
            .iter()
            .find(|packet| packet.surface.as_str() == "devil woman")
            .unwrap();

        assert_eq!(boundary.label_distribution[0].0.as_str(), "Concept");
        assert_eq!(dwarf.label_distribution[0].0.as_str(), "Creature");
        assert_eq!(
            label_group(devil_woman.label_distribution[0].0.as_str()),
            "person"
        );
    }

    #[test]
    fn repeated_short_name_prior_repairs_compound_full_name_kind() {
        let mut ws = MentionWorkspace::new("doc1", 0);
        for id in 0..3 {
            ws.entries
                .push(model_entry(id, "Rift", "Person", id as u32));
        }
        ws.entries
            .push(model_entry(3, "Riftmach Gearlock", "Creature", 3));
        for id in 4..6 {
            ws.entries
                .push(model_entry(id, "Tempest", "Person", id as u32));
        }
        ws.entries
            .push(model_entry(6, "Tempest Barish", "Creature", 6));
        ws.entries.push(known_entry(7, "Kai", "Character", 7));
        ws.entries.push(WorkspaceEntry {
            id: LocalMentionId(8),
            range: phoenix_types::TextRange { start: 80, end: 92 },
            surface: CompactString::from("Kai Gearlock"),
            normalized: CompactString::from("kai gearlock"),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::NativeDiscovery,
                    label: None,
                    entity_ref: None,
                    confidence: 0.78,
                    reason: VoteReason::CapSpan,
                },
                1,
            ),
            sentence_index: 8,
        });

        let packets = ws.finalize_packets();

        for surface in ["Riftmach Gearlock", "Tempest Barish", "Kai Gearlock"] {
            let packet = packets
                .iter()
                .find(|packet| packet.surface.as_str() == surface)
                .expect(surface);
            assert_eq!(
                label_group(packet.label_distribution[0].0.as_str()),
                "person"
            );
            assert!(packet.source_votes.iter().any(|vote| {
                vote.reason == VoteReason::RepeatedSurface
                    && vote
                        .label
                        .as_ref()
                        .is_some_and(|label| label_group(label.as_str()) == "person")
            }));
        }
    }

    #[test]
    fn label_distribution_normalizes() {
        let votes: SmallVec<[MentionVote; 6]> = SmallVec::from_vec(vec![
            MentionVote {
                source: MentionSourceKind::KnownLexicon,
                label: Some(EntityLabel::new("Character")),
                entity_ref: None,
                confidence: 0.8,
                reason: VoteReason::ExactCanonical,
            },
            MentionVote {
                source: MentionSourceKind::NativeDiscovery,
                label: Some(EntityLabel::new("Location")),
                entity_ref: None,
                confidence: 0.2,
                reason: VoteReason::CapSpan,
            },
        ]);
        let dist = MentionWorkspace::build_label_distribution(&votes);
        let total: f32 = dist.iter().map(|(_, w)| *w).sum();
        assert!((total - 1.0).abs() < 0.01);
    }

    fn model_entry(id: u64, surface: &str, label: &str, sentence_index: u32) -> WorkspaceEntry {
        model_entry_with_confidence(id, surface, label, sentence_index, 0.70)
    }

    fn native_cap_entry(id: u64, surface: &str, sentence_index: u32) -> WorkspaceEntry {
        WorkspaceEntry {
            id: LocalMentionId(id),
            range: phoenix_types::TextRange {
                start: id as u32 * 10,
                end: id as u32 * 10 + surface.len() as u32,
            },
            surface: CompactString::from(surface),
            normalized: CompactString::from(surface.to_ascii_lowercase()),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::NativeDiscovery,
                    label: None,
                    entity_ref: None,
                    confidence: 0.78,
                    reason: VoteReason::CapSpan,
                },
                1,
            ),
            sentence_index,
        }
    }

    fn packet_label_group<'a>(packets: &'a [MentionPacket], surface: &str) -> &'a str {
        packets
            .iter()
            .find(|packet| packet.surface.as_str() == surface)
            .map(|packet| label_group(packet.label_distribution[0].0.as_str()))
            .expect(surface)
    }

    fn model_entry_with_confidence(
        id: u64,
        surface: &str,
        label: &str,
        sentence_index: u32,
        confidence: f32,
    ) -> WorkspaceEntry {
        WorkspaceEntry {
            id: LocalMentionId(id),
            range: phoenix_types::TextRange {
                start: id as u32 * 10,
                end: id as u32 * 10 + surface.len() as u32,
            },
            surface: CompactString::from(surface),
            normalized: CompactString::from(surface.to_ascii_lowercase()),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::ModelDiscovery,
                    label: Some(EntityLabel::new(label)),
                    entity_ref: None,
                    confidence,
                    reason: VoteReason::ModelLabel,
                },
                1,
            ),
            sentence_index,
        }
    }

    fn known_entry(id: u64, surface: &str, label: &str, sentence_index: u32) -> WorkspaceEntry {
        WorkspaceEntry {
            id: LocalMentionId(id),
            range: phoenix_types::TextRange {
                start: id as u32 * 10,
                end: id as u32 * 10 + surface.len() as u32,
            },
            surface: CompactString::from(surface),
            normalized: CompactString::from(surface.to_ascii_lowercase()),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes: SmallVec::from_elem(
                MentionVote {
                    source: MentionSourceKind::KnownLexicon,
                    label: Some(EntityLabel::new(label)),
                    entity_ref: None,
                    confidence: 1.0,
                    reason: VoteReason::ExactCanonical,
                },
                1,
            ),
            sentence_index,
        }
    }

    fn test_sentence_spans(text: &str) -> Vec<SentenceSpan> {
        let mut spans = Vec::new();
        let mut start = 0usize;
        for (idx, ch) in text.char_indices() {
            if matches!(ch, '.' | '!' | '?') {
                spans.push(SentenceSpan {
                    index: spans.len(),
                    range: phoenix_types::TextRange {
                        start: start as u32,
                        end: (idx + ch.len_utf8()) as u32,
                    },
                });
                start = idx + ch.len_utf8() + 1;
            }
        }
        if start < text.len() {
            spans.push(SentenceSpan {
                index: spans.len(),
                range: phoenix_types::TextRange {
                    start: start as u32,
                    end: text.len() as u32,
                },
            });
        }
        spans
    }
}
