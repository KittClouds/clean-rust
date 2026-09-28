//! Known Surface Lane — Alex's kingdom.
//!
//! Deterministic, high-confidence mention detection from the scoped lexicon.
//! Handles: known names, aliases, auto-aliases, fuzzy anchors, gazetteer lore.

use compact_str::CompactString;
use phoenix_alex::{normalize_raw, Lexicon};
use phoenix_types::{
    EntityKind, KnownMatch, KnownMatchSource, MentionEntityRef, ScopeKey, SentenceSpan, TextRange,
};
use smallvec::SmallVec;

use crate::types::{LocalMentionId, MentionKind, MentionSourceKind, MentionVote, VoteReason};

/// A raw candidate produced by the known-surface lane before scoring.
#[derive(Clone, Debug)]
pub struct KnownCandidate {
    pub mention_id: LocalMentionId,
    pub range: TextRange,
    pub surface: CompactString,
    pub normalized: CompactString,
    pub mention_kind: MentionKind,
    pub entity_ref: Option<MentionEntityRef>,
    pub type_hint: Option<EntityKind>,
    pub votes: SmallVec<[MentionVote; 2]>,
    pub sentence_index: u32,
}

/// The known-surface scanner.
pub struct KnownSurfaceLane;

impl KnownSurfaceLane {
    /// Scan text against the compiled lexicon, emitting candidates with votes.
    pub fn scan(
        lexicon: &Lexicon,
        scope: &ScopeKey,
        text: &str,
        sentences: &[SentenceSpan],
        id_base: u64,
    ) -> Vec<KnownCandidate> {
        let matches = lexicon.scan(text, scope);
        let mut candidates = Vec::with_capacity(matches.len());
        let mut next_id = id_base;

        for matched in matches {
            if let Some(candidate) =
                Self::candidate_from_match(matched, sentences, LocalMentionId(next_id))
            {
                candidates.push(candidate);
                next_id += 1;
            }
        }
        candidates
    }

    /// Try fuzzy anchor recovery for a single token.
    pub fn fuzzy_probe(
        lexicon: &Lexicon,
        scope: &ScopeKey,
        token: &str,
        sentence_index: u32,
        id: LocalMentionId,
    ) -> Option<KnownCandidate> {
        let matched = lexicon.fuzzy_anchor(token, scope)?;
        let entity_ref = matched
            .entries
            .first()
            .map(|e| MentionEntityRef::Known(e.entity_id.clone()));
        let type_hint = matched.entries.first().and_then(|e| e.kind.clone());
        let label = type_hint
            .as_ref()
            .map(|k| crate::types::entity_kind_to_label(k));

        let vote = MentionVote {
            source: MentionSourceKind::KnownLexicon,
            label,
            entity_ref: entity_ref.clone(),
            confidence: matched.confidence,
            reason: VoteReason::FuzzyAnchor,
        };

        Some(KnownCandidate {
            mention_id: id,
            range: TextRange::default(),
            surface: CompactString::from(token),
            normalized: CompactString::from(normalize_raw(token)),
            mention_kind: MentionKind::Named,
            entity_ref,
            type_hint,
            votes: SmallVec::from_elem(vote, 1),
            sentence_index,
        })
    }

    fn candidate_from_match(
        matched: KnownMatch,
        sentences: &[SentenceSpan],
        id: LocalMentionId,
    ) -> Option<KnownCandidate> {
        let surface_str = matched.surface.trim();
        if surface_str.is_empty() {
            return None;
        }
        let normalized = normalize_raw(surface_str);
        if normalized.is_empty() {
            return None;
        }

        let entity_ref = Self::resolve_entity_ref(&matched);
        let type_hint = matched.entries.first().and_then(|e| e.kind.clone());
        let sentence_index = locate_sentence(sentences, matched.range);

        let (confidence, reason) = match matched.source {
            Some(KnownMatchSource::ExactCanonical) => (1.0_f32, VoteReason::ExactCanonical),
            Some(KnownMatchSource::ExactAlias) => (0.96, VoteReason::ExactAlias),
            Some(KnownMatchSource::ExactAutoAlias) => (0.90, VoteReason::AutoAlias),
            Some(KnownMatchSource::FuzzyAnchor) | None => {
                (matched.confidence, VoteReason::FuzzyAnchor)
            }
        };

        let label = type_hint
            .as_ref()
            .map(|k| crate::types::entity_kind_to_label(k));

        let vote = MentionVote {
            source: MentionSourceKind::KnownLexicon,
            label,
            entity_ref: entity_ref.clone(),
            confidence,
            reason,
        };

        Some(KnownCandidate {
            mention_id: id,
            range: matched.range,
            surface: CompactString::from(surface_str),
            normalized: CompactString::from(normalized),
            mention_kind: MentionKind::Named,
            entity_ref,
            type_hint,
            votes: SmallVec::from_elem(vote, 1),
            sentence_index,
        })
    }

    fn resolve_entity_ref(matched: &KnownMatch) -> Option<MentionEntityRef> {
        let mut entity_id = None;
        let mut ambiguous = false;
        for entry in &matched.entries {
            match &entity_id {
                None => entity_id = Some(entry.entity_id.clone()),
                Some(existing) if *existing == entry.entity_id => {}
                Some(_) => {
                    ambiguous = true;
                    break;
                }
            }
        }
        if ambiguous {
            None
        } else {
            entity_id.map(MentionEntityRef::Known)
        }
    }
}

/// Binary-search locate sentence index for a byte range.
pub(crate) fn locate_sentence(sentences: &[SentenceSpan], range: TextRange) -> u32 {
    if sentences.is_empty() {
        return 0;
    }
    let midpoint = range.start + (range.end.saturating_sub(range.start)) / 2;
    match sentences.binary_search_by(|s| {
        if s.range.end <= midpoint {
            std::cmp::Ordering::Less
        } else if s.range.start > midpoint {
            std::cmp::Ordering::Greater
        } else {
            std::cmp::Ordering::Equal
        }
    }) {
        Ok(idx) => sentences[idx].index as u32,
        Err(idx) => {
            if idx < sentences.len() {
                sentences[idx].index as u32
            } else {
                sentences.last().map(|s| s.index as u32).unwrap_or(0)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use phoenix_types::{EntityId, GenderHint, LexiconEntry};

    fn test_entry(id: &str, label: &str, kind: EntityKind) -> LexiconEntry {
        LexiconEntry {
            entity_id: EntityId(id.to_owned()),
            label: label.to_owned(),
            aliases: Vec::new(),
            kind: Some(kind),
            gender: Some(GenderHint::Unknown),
            number: None,
            scope: ScopeKey::default(),
        }
    }

    fn test_sentences(ranges: &[(u32, u32)]) -> Vec<SentenceSpan> {
        ranges
            .iter()
            .enumerate()
            .map(|(i, (start, end))| SentenceSpan {
                index: i,
                range: TextRange {
                    start: *start,
                    end: *end,
                },
            })
            .collect()
    }

    #[test]
    fn scan_finds_known_entity() {
        let lexicon =
            Lexicon::from_entries(&[test_entry("k1", "Kamaria", EntityKind::Character)]).unwrap();
        let text = "Kamaria drew her blade.";
        let sentences = test_sentences(&[(0, text.len() as u32)]);
        let candidates =
            KnownSurfaceLane::scan(&lexicon, &ScopeKey::default(), text, &sentences, 0);
        assert_eq!(candidates.len(), 1);
        assert_eq!(candidates[0].surface.as_str(), "Kamaria");
        assert!(matches!(
            candidates[0].entity_ref,
            Some(MentionEntityRef::Known(_))
        ));
        assert!(candidates[0].votes[0].confidence >= 0.90);
    }

    #[test]
    fn scan_empty_text_returns_nothing() {
        let lexicon =
            Lexicon::from_entries(&[test_entry("k1", "Kamaria", EntityKind::Character)]).unwrap();
        let candidates = KnownSurfaceLane::scan(&lexicon, &ScopeKey::default(), "", &[], 0);
        assert!(candidates.is_empty());
    }

    #[test]
    fn locate_sentence_binary_search() {
        let sentences = test_sentences(&[(0, 20), (20, 50), (50, 80)]);
        assert_eq!(
            locate_sentence(&sentences, TextRange { start: 5, end: 10 }),
            0
        );
        assert_eq!(
            locate_sentence(&sentences, TextRange { start: 25, end: 30 }),
            1
        );
        assert_eq!(
            locate_sentence(&sentences, TextRange { start: 60, end: 70 }),
            2
        );
    }

    #[test]
    fn fuzzy_probe_recovers_typo() {
        let lexicon =
            Lexicon::from_entries(&[test_entry("z1", "Roronoa Zoro", EntityKind::Character)])
                .unwrap();
        let result = KnownSurfaceLane::fuzzy_probe(
            &lexicon,
            &ScopeKey::default(),
            "Zoroo",
            0,
            LocalMentionId(0),
        );
        assert!(result.is_some());
        let c = result.unwrap();
        assert_eq!(c.votes[0].reason, VoteReason::FuzzyAnchor);
    }
}
