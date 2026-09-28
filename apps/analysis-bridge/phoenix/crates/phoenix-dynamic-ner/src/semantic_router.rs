//! Semantic label routing abstractions.
//!
//! The Dynamic NER core does not own a particular embedding model. It accepts
//! route hints from a semantic router so CLI/runtime layers can use Jina today
//! and another retrieval model later without changing GLiNER span extraction.

use compact_str::CompactString;
use phoenix_types::SentenceSpan;
use smallvec::SmallVec;

use crate::known_lane::KnownCandidate;
use crate::label_catalog;
use crate::native_lane::NativeCandidate;
use crate::types::{DomainProfile, EntityLabel};

pub struct SemanticRouteInput<'a> {
    pub document_text: &'a str,
    pub window_text: &'a str,
    pub sentences: &'a [SentenceSpan],
    pub window_start_sentence: u32,
    pub window_end_sentence: u32,
    pub known: &'a [KnownCandidate],
    pub native: &'a [NativeCandidate],
    pub context_domain: Option<DomainProfile>,
}

#[derive(Clone, Debug)]
pub struct SemanticRouteHint {
    pub domain_profile: DomainProfile,
    pub confidence: f32,
    pub labels: SmallVec<[EntityLabel; 16]>,
    pub source: CompactString,
}

impl SemanticRouteHint {
    pub fn new(
        domain_profile: DomainProfile,
        confidence: f32,
        labels: SmallVec<[EntityLabel; 16]>,
        source: impl Into<CompactString>,
    ) -> Self {
        Self {
            domain_profile,
            confidence: confidence.clamp(0.0, 1.0),
            labels,
            source: source.into(),
        }
    }
}

pub trait SemanticLabelRouter {
    fn route_window(&self, input: &SemanticRouteInput<'_>) -> Option<SemanticRouteHint>;

    fn route_windows(&self, inputs: &[SemanticRouteInput<'_>]) -> Vec<Option<SemanticRouteHint>> {
        inputs
            .iter()
            .map(|input| self.route_window(input))
            .collect()
    }
}

#[derive(Clone, Debug)]
pub struct LexicalSemanticLabelRouter {
    min_confidence: f32,
}

impl Default for LexicalSemanticLabelRouter {
    fn default() -> Self {
        Self {
            min_confidence: 0.38,
        }
    }
}

impl LexicalSemanticLabelRouter {
    pub fn new(min_confidence: f32) -> Self {
        Self {
            min_confidence: min_confidence.clamp(0.0, 1.0),
        }
    }
}

impl SemanticLabelRouter for LexicalSemanticLabelRouter {
    fn route_window(&self, input: &SemanticRouteInput<'_>) -> Option<SemanticRouteHint> {
        let mut scores = domain_scores(input.window_text);
        apply_candidate_priors(&mut scores, input.known, input.native);
        let (domain, confidence) = best_domain(scores)?;
        if confidence < self.min_confidence {
            return None;
        }
        let mut labels = SmallVec::<[EntityLabel; 16]>::new();
        label_catalog::push_domain_labels(&mut labels, domain, 12);
        let source = format!(
            "lexical-semantic-router:{}",
            label_catalog::LABEL_ONTOLOGY_VERSION
        );
        Some(SemanticRouteHint::new(domain, confidence, labels, source))
    }
}

fn domain_scores(text: &str) -> [(DomainProfile, f32); 8] {
    let lower = text.to_ascii_lowercase();
    [
        (DomainProfile::Story, cue_score(&lower, STORY_CUES)),
        (DomainProfile::Fantasy, cue_score(&lower, FANTASY_CUES)),
        (DomainProfile::Corporate, cue_score(&lower, CORPORATE_CUES)),
        (DomainProfile::Technical, cue_score(&lower, TECHNICAL_CUES)),
        (DomainProfile::Legal, cue_score(&lower, LEGAL_CUES)),
        (DomainProfile::Academic, cue_score(&lower, ACADEMIC_CUES)),
        (DomainProfile::Memory, cue_score(&lower, MEMORY_CUES)),
        (DomainProfile::General, 0.05),
    ]
}

fn apply_candidate_priors(
    scores: &mut [(DomainProfile, f32); 8],
    known: &[KnownCandidate],
    native: &[NativeCandidate],
) {
    for candidate in known {
        if let Some(kind) = candidate.type_hint.as_ref() {
            match kind {
                phoenix_types::EntityKind::Character | phoenix_types::EntityKind::Npc => {
                    bump(scores, DomainProfile::Story, 0.35);
                }
                phoenix_types::EntityKind::Faction => {
                    bump(scores, DomainProfile::Story, 0.35);
                    bump(scores, DomainProfile::Fantasy, 0.15);
                }
                phoenix_types::EntityKind::Organization => {
                    bump(scores, DomainProfile::Corporate, 0.2);
                }
                phoenix_types::EntityKind::Item => {
                    bump(scores, DomainProfile::Story, 0.15);
                }
                _ => {}
            }
        }
    }
    let nominal_count = native
        .iter()
        .filter(|candidate| candidate.mention_kind == crate::types::MentionKind::Nominal)
        .count();
    if nominal_count > 0 {
        bump(
            scores,
            DomainProfile::Story,
            (nominal_count as f32).min(4.0) * 0.1,
        );
    }
}

fn cue_score(text: &str, cues: &[&str]) -> f32 {
    cues.iter()
        .filter(|cue| text.contains(**cue))
        .map(|cue| if cue.contains(' ') { 0.35 } else { 0.18 })
        .sum()
}

fn bump(scores: &mut [(DomainProfile, f32); 8], domain: DomainProfile, value: f32) {
    if let Some((_, score)) = scores
        .iter_mut()
        .find(|(candidate, _)| *candidate == domain)
    {
        *score += value;
    }
}

fn best_domain(mut scores: [(DomainProfile, f32); 8]) -> Option<(DomainProfile, f32)> {
    scores.sort_by(|left, right| {
        right
            .1
            .partial_cmp(&left.1)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let (domain, top) = scores[0];
    let runner_up = scores.get(1).map(|(_, score)| *score).unwrap_or(0.0);
    if top <= 0.05 {
        return None;
    }
    let margin = (top - runner_up).max(0.0);
    let confidence = (0.28 + top.min(2.0) * 0.24 + margin.min(1.0) * 0.24).clamp(0.0, 0.92);
    Some((domain, confidence))
}

const STORY_CUES: &[&str] = &[
    "said",
    "asked",
    "replied",
    "told",
    "laughed",
    "smiled",
    "looked",
    "fought",
    "dialogue",
    "chapter",
    "scene",
    "character",
    "gang",
    "city",
];

const FANTASY_CUES: &[&str] = &[
    "creature", "species", "monster", "dragon", "dwarf", "titan", "devil", "spell", "magic",
    "sword", "blade", "weapon",
];

const CORPORATE_CUES: &[&str] = &[
    "company",
    "department",
    "executive",
    "product",
    "metric",
    "initiative",
    "risk",
    "security",
];

const TECHNICAL_CUES: &[&str] = &[
    "module",
    "function",
    "library",
    "cli",
    "benchmark",
    "algorithm",
    "embedding",
    "projection",
    "vector",
    "hash",
];

const LEGAL_CUES: &[&str] = &[
    "court",
    "ruling",
    "statute",
    "claim",
    "jurisdiction",
    "party",
];

const ACADEMIC_CUES: &[&str] = &[
    "paper",
    "research",
    "dataset",
    "method",
    "theory",
    "institution",
];

const MEMORY_CUES: &[&str] = &[
    "state",
    "goal",
    "relationship",
    "emotion",
    "remembered",
    "memory",
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lexical_router_prefers_story_for_dialogue_and_factions() {
        let router = LexicalSemanticLabelRouter::new(0.0);
        let hint = router
            .route_window(&SemanticRouteInput {
                document_text: "Ryan said the gang owned the city.",
                window_text: "Ryan said the gang owned the city.",
                sentences: &[],
                window_start_sentence: 0,
                window_end_sentence: 1,
                known: &[],
                native: &[],
                context_domain: None,
            })
            .expect("route hint");

        assert_eq!(hint.domain_profile, DomainProfile::Story);
        assert!(hint.labels.iter().any(|label| label.as_str() == "Npc"));
        assert!(hint
            .source
            .as_str()
            .contains(label_catalog::LABEL_ONTOLOGY_VERSION));
    }

    #[test]
    fn lexical_router_can_route_technical_windows() {
        let router = LexicalSemanticLabelRouter::new(0.0);
        let hint = router
            .route_window(&SemanticRouteInput {
                document_text: "The module benchmark checks projection vectors.",
                window_text: "The module benchmark checks projection vectors.",
                sentences: &[],
                window_start_sentence: 0,
                window_end_sentence: 1,
                known: &[],
                native: &[],
                context_domain: None,
            })
            .expect("route hint");

        assert_eq!(hint.domain_profile, DomainProfile::Technical);
        assert!(hint.labels.iter().any(|label| label.as_str() == "Module"));
    }
}
