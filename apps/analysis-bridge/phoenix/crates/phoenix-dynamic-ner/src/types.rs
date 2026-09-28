use compact_str::CompactString;
use phoenix_types::{EntityKind, MentionEntityRef, TextRange};
use serde::{Deserialize, Serialize};
use smallvec::SmallVec;

// ---------------------------------------------------------------------------
// Identifiers
// ---------------------------------------------------------------------------

/// Local mention id — cheap u64, arena-friendly.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct LocalMentionId(pub u64);

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

/// A typed entity label backed by CompactString (inline ≤24 bytes).
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct EntityLabel(pub CompactString);

impl EntityLabel {
    #[inline]
    pub fn new(s: &str) -> Self {
        Self(CompactString::from(s))
    }

    #[inline]
    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

impl std::fmt::Display for EntityLabel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.0.as_str())
    }
}

impl From<&str> for EntityLabel {
    fn from(s: &str) -> Self {
        Self::new(s)
    }
}

// ---------------------------------------------------------------------------
// Source classification
// ---------------------------------------------------------------------------

/// Which lane / subsystem produced this vote.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub enum MentionSourceKind {
    KnownLexicon,
    NativeDiscovery,
    Scirs2Rule,
    Scirs2Pattern,
    ModelDiscovery,
    ModelVerify,
    Adjudication,
    Pronoun,
}

/// Broad morphological class of the mention.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum MentionKind {
    Named,
    Nominal,
    Pronoun,
}

/// Pipeline verdict after scoring.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum MentionStatus {
    AcceptedKnown,
    AcceptedNew,
    AliasCandidate,
    NeedsAdjudication,
    Rejected,
}

impl MentionStatus {
    #[inline]
    pub fn is_accepted(self) -> bool {
        matches!(self, Self::AcceptedKnown | Self::AcceptedNew)
    }

    #[inline]
    pub fn is_exportable(self) -> bool {
        matches!(
            self,
            Self::AcceptedKnown | Self::AcceptedNew | Self::AliasCandidate
        )
    }

    #[inline]
    pub fn is_rejected(self) -> bool {
        matches!(self, Self::Rejected)
    }
}

// ---------------------------------------------------------------------------
// Vote evidence
// ---------------------------------------------------------------------------

/// Why a source cast a particular vote.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum VoteReason {
    ExactCanonical,
    ExactAlias,
    AutoAlias,
    FuzzyAnchor,
    TitlePattern,
    CapSpan,
    NominalRole,
    RepeatedSurface,
    DependencyRole,
    DialogueSpeaker,
    ModelSpan,
    ModelLabel,
    NliSupport,
    NliContradiction,
    StopwordPenalty,
    GuardViolation,
}

/// A single vote from one NER source.
#[derive(Clone, Debug)]
pub struct MentionVote {
    pub source: MentionSourceKind,
    pub label: Option<EntityLabel>,
    pub entity_ref: Option<MentionEntityRef>,
    pub confidence: f32,
    pub reason: VoteReason,
}

// ---------------------------------------------------------------------------
// Context / syntax / semantics
// ---------------------------------------------------------------------------

/// Surrounding structural context for a mention.
#[derive(Clone, Debug, Default)]
pub struct MentionContext {
    pub sentence_range: Option<TextRange>,
    pub clause_range: Option<TextRange>,
    pub chunk_kind: Option<CompactString>,
    pub paragraph_role: Option<CompactString>,
}

/// Syntactic attachment information.
#[derive(Clone, Debug, Default)]
pub struct MentionSyntax {
    pub dep_label: Option<CompactString>,
    pub is_subject: bool,
    pub is_object: bool,
    pub head_range: Option<TextRange>,
}

/// Modality / polarity / evidentiality.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Modality {
    Observed,
    Reported,
    Hypothetical,
    Desired,
    Conditional,
}

/// Assertion polarity.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Polarity {
    Positive,
    Negated,
}

/// Semantic annotation on a mention.
#[derive(Clone, Debug, Default)]
pub struct MentionSemantics {
    pub modality: Option<Modality>,
    pub polarity: Option<Polarity>,
    pub is_negated: bool,
    pub is_hypothetical: bool,
    pub is_quoted: bool,
}

// ---------------------------------------------------------------------------
// MentionPacket — the canonical evidence artifact
// ---------------------------------------------------------------------------

/// Central evidence artifact. Every lane emits into this shape.
#[derive(Clone, Debug)]
pub struct MentionPacket {
    pub mention_id: LocalMentionId,
    pub document_id: CompactString,
    pub chunk_id: Option<CompactString>,
    pub sentence_index: u32,

    pub range: TextRange,
    pub surface: CompactString,
    pub normalized: CompactString,

    pub mention_kind: MentionKind,
    pub label_distribution: SmallVec<[(EntityLabel, f32); 4]>,
    pub entity_ref: Option<MentionEntityRef>,

    pub source_votes: SmallVec<[MentionVote; 6]>,
    pub context: MentionContext,
    pub syntax: Option<MentionSyntax>,
    pub semantics: MentionSemantics,

    pub confidence: f32,
    pub status: MentionStatus,
}

impl MentionPacket {
    #[inline]
    pub fn is_accepted(&self) -> bool {
        self.status.is_accepted()
    }

    #[inline]
    pub fn is_exportable(&self) -> bool {
        self.status.is_exportable()
    }

    pub fn is_hint_eligible(&self) -> bool {
        match self.status {
            MentionStatus::AcceptedKnown | MentionStatus::AcceptedNew => true,
            MentionStatus::AliasCandidate => {
                self.confidence >= 0.45
                    || self.source_votes.iter().any(|vote| {
                        matches!(
                            vote.source,
                            MentionSourceKind::KnownLexicon
                                | MentionSourceKind::ModelDiscovery
                                | MentionSourceKind::ModelVerify
                        )
                    })
            }
            MentionStatus::NeedsAdjudication | MentionStatus::Rejected => false,
        }
    }
}

// ---------------------------------------------------------------------------
// Routing types
// ---------------------------------------------------------------------------

/// Domain profile for label-pack construction.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum DomainProfile {
    Fantasy,
    Corporate,
    Technical,
    Legal,
    Academic,
    Memory,
    Story,
    General,
}

impl Default for DomainProfile {
    fn default() -> Self {
        Self::General
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum LabelBankSource {
    Schema,
    SourceFrameContext,
    GraphContext,
    DomainProfile,
    SemanticRouter,
    UserType,
    Gazetteer,
}

#[derive(Clone, Debug)]
pub struct LabelBankContext<'a> {
    pub domain_profile: Option<DomainProfile>,
    pub source_frame_labels: &'a [EntityLabel],
    pub graph_context_labels: &'a [EntityLabel],
    pub user_type_labels: &'a [EntityLabel],
}

impl<'a> Default for LabelBankContext<'a> {
    fn default() -> Self {
        Self {
            domain_profile: None,
            source_frame_labels: &[],
            graph_context_labels: &[],
            user_type_labels: &[],
        }
    }
}

/// A scoped label set for model NER.
#[derive(Clone, Debug)]
pub struct LabelPack {
    pub domain: DomainProfile,
    pub labels: SmallVec<[EntityLabel; 16]>,
    pub label_sources: SmallVec<[(EntityLabel, LabelBankSource); 16]>,
    pub seed_surfaces: SmallVec<[CompactString; 32]>,
    pub negative_labels: SmallVec<[EntityLabel; 8]>,
    pub max_labels: usize,
}

impl Default for LabelPack {
    fn default() -> Self {
        Self {
            domain: DomainProfile::General,
            labels: SmallVec::new(),
            label_sources: SmallVec::new(),
            seed_surfaces: SmallVec::new(),
            negative_labels: SmallVec::new(),
            max_labels: 14,
        }
    }
}

/// Feature vector that the router uses to decide NER routing per window.
#[derive(Clone, Debug, Default)]
pub struct NerNeedVector {
    pub has_known_seed: bool,
    pub has_unknown_cap_span: bool,
    pub has_nominal_role: bool,
    pub has_pronoun: bool,
    pub has_repeated_unknown_surface: bool,
    pub has_dialogue_structure: bool,
    pub has_dependency_subject_object: bool,
    pub has_causal_or_temporal_cue: bool,
    pub has_domain_signature: bool,
    pub has_entity_pair: bool,
    pub has_ambiguous_reference: bool,
    pub has_named_event_candidate: bool,

    pub candidate_count: u16,
    pub unknown_named_count: u16,
    pub ambiguity_score: f32,
    pub novelty_score: f32,
}

/// Routing decision for a text window.
#[derive(Clone, Debug)]
pub enum NerRoute {
    /// Only deterministic lanes needed.
    DeterministicOnly,
    /// Run native discovery (usually already done; marks intent).
    NativeDiscovery,
    /// Send to model NER with a scoped label pack.
    ModelDiscovery {
        window_start_sentence: u32,
        window_end_sentence: u32,
        label_pack: LabelPack,
    },
    /// Ask model to verify specific uncertain candidates.
    ModelVerify { cases: SmallVec<[VerifyCase; 8]> },
    /// Send hard cases to adjudicator.
    Adjudicate {
        cases: SmallVec<[AdjudicateCase; 8]>,
    },
}

/// A case sent to model verification.
#[derive(Clone, Debug)]
pub struct VerifyCase {
    pub mention_id: LocalMentionId,
    pub surface: CompactString,
    pub sentence_index: u32,
    pub candidate_labels: SmallVec<[EntityLabel; 4]>,
}

/// A case sent to adjudication.
#[derive(Clone, Debug)]
pub struct AdjudicateCase {
    pub mention_id: LocalMentionId,
    pub surface: CompactString,
    pub sentence_index: u32,
    pub candidate_entity_refs: SmallVec<[MentionEntityRef; 4]>,
    pub candidate_labels: SmallVec<[EntityLabel; 4]>,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Map existing EntityKind to a default EntityLabel.
pub fn entity_kind_to_label(kind: &EntityKind) -> EntityLabel {
    match kind {
        EntityKind::Character => EntityLabel::new("Character"),
        EntityKind::Location => EntityLabel::new("Location"),
        EntityKind::Npc => EntityLabel::new("NPC"),
        EntityKind::Item => EntityLabel::new("Item"),
        EntityKind::Faction => EntityLabel::new("Faction"),
        EntityKind::Organization => EntityLabel::new("Organization"),
        EntityKind::Event => EntityLabel::new("Event"),
        EntityKind::Concept => EntityLabel::new("Concept"),
        EntityKind::Other => EntityLabel::new("Other"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn entity_label_inline_small_string() {
        let label = EntityLabel::new("Character");
        assert_eq!(label.as_str(), "Character");
        assert_eq!(format!("{label}"), "Character");
    }

    #[test]
    fn label_pack_default_has_sane_cap() {
        let pack = LabelPack::default();
        assert_eq!(pack.max_labels, 14);
        assert!(pack.labels.is_empty());
        assert!(pack.label_sources.is_empty());
    }

    #[test]
    fn need_vector_default_is_all_false() {
        let need = NerNeedVector::default();
        assert!(!need.has_known_seed);
        assert!(!need.has_entity_pair);
        assert!(!need.has_ambiguous_reference);
        assert!(!need.has_named_event_candidate);
        assert_eq!(need.candidate_count, 0);
        assert_eq!(need.ambiguity_score, 0.0);
    }

    #[test]
    fn mention_source_kind_ordering() {
        assert!(MentionSourceKind::KnownLexicon < MentionSourceKind::NativeDiscovery);
        assert!(MentionSourceKind::ModelDiscovery < MentionSourceKind::Adjudication);
    }

    #[test]
    fn entity_kind_to_label_covers_all() {
        let kinds = [
            EntityKind::Character,
            EntityKind::Location,
            EntityKind::Npc,
            EntityKind::Item,
            EntityKind::Faction,
            EntityKind::Organization,
            EntityKind::Event,
            EntityKind::Concept,
            EntityKind::Other,
        ];
        for kind in &kinds {
            let label = entity_kind_to_label(kind);
            assert!(!label.as_str().is_empty());
        }
    }

    #[test]
    fn mention_status_export_contract_is_explicit() {
        assert!(MentionStatus::AcceptedKnown.is_exportable());
        assert!(MentionStatus::AcceptedNew.is_exportable());
        assert!(MentionStatus::AliasCandidate.is_exportable());
        assert!(!MentionStatus::NeedsAdjudication.is_exportable());
        assert!(!MentionStatus::Rejected.is_exportable());
        assert!(MentionStatus::AcceptedKnown.is_accepted());
        assert!(!MentionStatus::AliasCandidate.is_accepted());
    }
}
