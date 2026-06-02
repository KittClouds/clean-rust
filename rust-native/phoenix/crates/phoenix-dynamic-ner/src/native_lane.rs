//! Native Discovery Lane — cheap, broad, ugly-fast.
//!
//! Spots suspicious surfaces without any model: capitalized spans, title+name
//! patterns, nominal roles, pronouns, dialogue speaker cues, repeated unknowns.
//! Uses `memchr` for SIMD-accelerated cue scanning.

use compact_str::CompactString;
use memchr::memmem;
use phoenix_alex::normalize_raw;
use phoenix_types::{MentionEntityRef, PosTag, SentenceSpan, TextRange, TokenClass, TokenSpan};
use rustc_hash::FxHashMap;
use smallvec::SmallVec;

use crate::known_lane::locate_sentence;
use crate::types::{
    EntityLabel, LocalMentionId, MentionKind, MentionSourceKind, MentionVote, VoteReason,
};

/// A candidate produced by native heuristic discovery.
#[derive(Clone, Debug)]
pub struct NativeCandidate {
    pub mention_id: LocalMentionId,
    pub range: TextRange,
    pub surface: CompactString,
    pub normalized: CompactString,
    pub mention_kind: MentionKind,
    pub entity_ref: Option<MentionEntityRef>,
    pub votes: SmallVec<[MentionVote; 2]>,
    pub sentence_index: u32,
}

/// The native discovery scanner.
pub struct NativeDiscoveryLane;

#[derive(Clone, Copy, Debug, Default)]
struct CapSurfaceStats {
    total: u16,
    mid_sentence: u16,
}

impl CapSurfaceStats {
    #[inline]
    fn bump(&mut self, sentence_initial: bool) {
        self.total = self.total.saturating_add(1);
        if !sentence_initial {
            self.mid_sentence = self.mid_sentence.saturating_add(1);
        }
    }

    #[inline]
    fn has_mid_sentence(self) -> bool {
        self.mid_sentence > 0
    }
}

impl NativeDiscoveryLane {
    /// Run the full native discovery pass over tokenized text.
    pub fn discover(
        text: &str,
        tokens: &[TokenSpan],
        sentences: &[SentenceSpan],
        known_ranges: &[TextRange],
        id_base: u64,
    ) -> Vec<NativeCandidate> {
        let mut candidates = Vec::new();
        let protected_ranges = markdown_protected_ranges(text);
        let cap_surface_stats =
            collect_cap_surface_stats(text, tokens, sentences, known_ranges, &protected_ranges);
        let mut next_id = id_base;
        let mut idx = 0usize;

        while idx < tokens.len() {
            let token = &tokens[idx];
            let token_text = safe_slice(text, token.range);
            let sent_idx = locate_sentence(sentences, token.range);

            // Skip tokens already covered by known-lane matches.
            if range_overlaps_any(token.range, known_ranges)
                || range_overlaps_any(token.range, &protected_ranges)
            {
                if !range_overlaps_any(token.range, &protected_ranges)
                    && capitalized_entity_token_range(text, token).is_some()
                {
                    let (end_idx, range) = extend_cap_span(text, tokens, idx);
                    let surface = safe_slice(text, range);
                    let normalized = CompactString::from(normalize_raw(surface));
                    if range.end > token.range.end
                        && !range_overlaps_any(range, &protected_ranges)
                        && should_keep_cap_span(
                            surface,
                            is_sentence_initial_range(text, range, sentences),
                            sentence_initial_quoted_name_like(text, range, sentences),
                            CapSurfaceStats::default(),
                        )
                    {
                        candidates.push(NativeCandidate {
                            mention_id: LocalMentionId(next_id),
                            range,
                            surface: CompactString::from(surface),
                            normalized,
                            mention_kind: MentionKind::Named,
                            entity_ref: Some(MentionEntityRef::Speculative(
                                normalize_raw(surface).to_string(),
                            )),
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
                            sentence_index: sent_idx,
                        });
                        next_id += 1;
                        idx = end_idx + 1;
                        continue;
                    }
                }
                idx += 1;
                continue;
            }

            // --- Pronoun harvesting ---
            if matches!(token.pos, Some(PosTag::Pronoun)) {
                candidates.push(NativeCandidate {
                    mention_id: LocalMentionId(next_id),
                    range: token.range,
                    surface: CompactString::from(token_text),
                    normalized: CompactString::from(normalize_raw(token_text)),
                    mention_kind: MentionKind::Pronoun,
                    entity_ref: None,
                    votes: SmallVec::from_elem(
                        MentionVote {
                            source: MentionSourceKind::Pronoun,
                            label: None,
                            entity_ref: None,
                            confidence: 0.65,
                            reason: VoteReason::NominalRole,
                        },
                        1,
                    ),
                    sentence_index: sent_idx,
                });
                next_id += 1;
                idx += 1;
                continue;
            }

            // --- Title + name pattern ---
            if is_title_token(token_text) {
                if let Some((end_idx, range)) = extend_title_span(text, tokens, idx) {
                    if range_overlaps_any(range, &protected_ranges) {
                        idx = end_idx + 1;
                        continue;
                    }
                    let surface = safe_slice(text, range);
                    candidates.push(NativeCandidate {
                        mention_id: LocalMentionId(next_id),
                        range,
                        surface: CompactString::from(surface),
                        normalized: CompactString::from(normalize_raw(surface)),
                        mention_kind: MentionKind::Named,
                        entity_ref: Some(MentionEntityRef::Speculative(
                            normalize_raw(surface).to_string(),
                        )),
                        votes: SmallVec::from_elem(
                            MentionVote {
                                source: MentionSourceKind::NativeDiscovery,
                                label: None,
                                entity_ref: None,
                                confidence: 0.80,
                                reason: VoteReason::TitlePattern,
                            },
                            1,
                        ),
                        sentence_index: sent_idx,
                    });
                    next_id += 1;
                    idx = end_idx + 1;
                    continue;
                }
            }

            // --- Species / denizen role detection ---
            if let Some((end_idx, range, label, confidence)) =
                extend_species_role_span(text, tokens, idx)
            {
                let surface = safe_slice(text, range);
                candidates.push(NativeCandidate {
                    mention_id: LocalMentionId(next_id),
                    range,
                    surface: CompactString::from(surface),
                    normalized: CompactString::from(normalize_raw(surface)),
                    mention_kind: MentionKind::Named,
                    entity_ref: Some(MentionEntityRef::Speculative(
                        normalize_raw(surface).to_string(),
                    )),
                    votes: SmallVec::from_elem(
                        MentionVote {
                            source: MentionSourceKind::NativeDiscovery,
                            label: Some(EntityLabel::new(label)),
                            entity_ref: None,
                            confidence,
                            reason: VoteReason::NominalRole,
                        },
                        1,
                    ),
                    sentence_index: sent_idx,
                });
                next_id += 1;
                idx = end_idx + 1;
                continue;
            }

            // --- Capitalized span detection ---
            if capitalized_entity_token_range(text, token).is_some() {
                let (end_idx, range) = extend_cap_span(text, tokens, idx);
                let surface = safe_slice(text, range);
                let normalized = CompactString::from(normalize_raw(surface));
                let stats = cap_surface_stats
                    .get(&normalized)
                    .copied()
                    .unwrap_or_default();
                if !surface.is_empty()
                    && !range_overlaps_any(range, &protected_ranges)
                    && should_keep_cap_span(
                        surface,
                        is_sentence_initial_range(text, range, sentences),
                        sentence_initial_quoted_name_like(text, range, sentences),
                        stats,
                    )
                {
                    let mut votes = SmallVec::new();
                    votes.push(MentionVote {
                        source: MentionSourceKind::NativeDiscovery,
                        label: None,
                        entity_ref: None,
                        confidence: 0.78,
                        reason: VoteReason::CapSpan,
                    });
                    if stats.total > 1 {
                        votes.push(MentionVote {
                            source: MentionSourceKind::NativeDiscovery,
                            label: None,
                            entity_ref: None,
                            confidence: (0.55 + f32::from(stats.total.min(5)) * 0.05).min(0.80),
                            reason: VoteReason::RepeatedSurface,
                        });
                    }
                    candidates.push(NativeCandidate {
                        mention_id: LocalMentionId(next_id),
                        range,
                        surface: CompactString::from(surface),
                        normalized,
                        mention_kind: MentionKind::Named,
                        entity_ref: Some(MentionEntityRef::Speculative(
                            normalize_raw(surface).to_string(),
                        )),
                        votes,
                        sentence_index: sent_idx,
                    });
                    next_id += 1;
                    idx = end_idx + 1;
                    continue;
                }
            }

            // --- Nominal role detection ---
            if is_nominal_role(token_text) {
                candidates.push(NativeCandidate {
                    mention_id: LocalMentionId(next_id),
                    range: token.range,
                    surface: CompactString::from(token_text),
                    normalized: CompactString::from(normalize_raw(token_text)),
                    mention_kind: MentionKind::Nominal,
                    entity_ref: None,
                    votes: SmallVec::from_elem(
                        MentionVote {
                            source: MentionSourceKind::NativeDiscovery,
                            label: None,
                            entity_ref: None,
                            confidence: 0.52,
                            reason: VoteReason::NominalRole,
                        },
                        1,
                    ),
                    sentence_index: sent_idx,
                });
                next_id += 1;
            }

            idx += 1;
        }

        candidates
    }

    /// Detect dialogue speaker cues in a sentence using SIMD memmem.
    pub fn has_dialogue_cue(text: &str, sentence: &SentenceSpan) -> bool {
        let slice = safe_slice(text, sentence.range);
        let lowered = slice.to_ascii_lowercase();
        let bytes = lowered.as_bytes();
        DIALOGUE_CUES
            .iter()
            .any(|cue| memmem::find(bytes, cue.as_bytes()).is_some())
    }
}

const DIALOGUE_CUES: &[&str] = &[
    " said ",
    " told ",
    " asked ",
    " called ",
    " known as ",
    " according to ",
    " wrote ",
    " says ",
    " says,",
    " replied ",
    " answered ",
    " whispered ",
    " shouted ",
    " muttered ",
    " exclaimed ",
];

// ---------------------------------------------------------------------------
// Span extension helpers
// ---------------------------------------------------------------------------

fn extend_title_span(text: &str, tokens: &[TokenSpan], start: usize) -> Option<(usize, TextRange)> {
    let mut last = start;
    let mut end = tokens[start].range.end;
    while let Some(next) = tokens.get(last + 1) {
        let clean_gap = if last == start {
            gap_allows_title_join(text, end, next.range.start)
        } else {
            gap_allows_entity_join(text, end, next.range.start)
        };
        if !clean_gap {
            break;
        }
        let next_text = safe_slice(text, next.range);
        if looks_like_entity_token(next_text) {
            end = next.range.end;
            last += 1;
        } else if is_connective(next_text) {
            let Some(after) = tokens.get(last + 2) else {
                break;
            };
            if !gap_allows_entity_join(text, next.range.end, after.range.start) {
                break;
            }
            if looks_like_entity_token(safe_slice(text, after.range)) {
                end = after.range.end;
                last += 2;
            } else {
                break;
            }
        } else {
            break;
        }
    }
    if last > start {
        Some((
            last,
            TextRange {
                start: tokens[start].range.start,
                end,
            },
        ))
    } else {
        None
    }
}

fn capitalized_entity_token_range(text: &str, token: &TokenSpan) -> Option<TextRange> {
    if !matches!(token.token_class, Some(TokenClass::Word)) {
        return None;
    }
    if token.capitalized {
        return Some(token.range);
    }
    let surface = safe_slice(text, token.range);
    let mut trimmed_start = token.range.start as usize;
    let mut trimmed_any = false;
    for (offset, ch) in surface.char_indices() {
        if is_quote_noise_char(ch) {
            trimmed_start = token.range.start as usize + offset + ch.len_utf8();
            trimmed_any = true;
        } else {
            break;
        }
    }
    if !trimmed_any || trimmed_start >= token.range.end as usize {
        return None;
    }
    let trimmed = text.get(trimmed_start..token.range.end as usize)?;
    if trimmed.starts_with(char::is_uppercase) && trimmed.chars().any(|ch| ch.is_alphabetic()) {
        Some(TextRange {
            start: trimmed_start as u32,
            end: token.range.end,
        })
    } else {
        None
    }
}

fn extend_cap_span(text: &str, tokens: &[TokenSpan], start: usize) -> (usize, TextRange) {
    let mut last = start;
    let first_range =
        capitalized_entity_token_range(text, &tokens[start]).unwrap_or(tokens[start].range);
    let mut end = first_range.end;
    while let Some(next) = tokens.get(last + 1) {
        let next_text = safe_slice(text, next.range);
        if let Some(next_range) = capitalized_entity_token_range(text, next) {
            if !gap_allows_entity_join(text, end, next_range.start) {
                break;
            }
            end = next_range.end;
            last += 1;
        } else if is_connective(next_text) {
            if !gap_allows_entity_join(text, end, next.range.start) {
                break;
            }
            let Some(after) = tokens.get(last + 2) else {
                break;
            };
            let Some(after_range) = capitalized_entity_token_range(text, after) else {
                break;
            };
            if !gap_allows_entity_join(text, next.range.end, after_range.start) {
                break;
            }
            end = after_range.end;
            last += 2;
        } else {
            break;
        }
    }
    (
        last,
        TextRange {
            start: first_range.start,
            end,
        },
    )
}

// ---------------------------------------------------------------------------
// Token classifiers
// ---------------------------------------------------------------------------

fn is_title_token(value: &str) -> bool {
    matches!(
        value.to_ascii_lowercase().trim_end_matches('.'),
        "mr" | "mrs"
            | "ms"
            | "dr"
            | "prof"
            | "captain"
            | "capt"
            | "sir"
            | "lord"
            | "lady"
            | "king"
            | "queen"
            | "prince"
            | "princess"
    )
}

fn is_nominal_role(value: &str) -> bool {
    matches!(
        value.to_ascii_lowercase().as_str(),
        "manager"
            | "captain"
            | "doctor"
            | "professor"
            | "teacher"
            | "brother"
            | "sister"
            | "mother"
            | "father"
            | "leader"
            | "chief"
            | "assistant"
            | "guard"
            | "agent"
            | "priest"
            | "king"
            | "queen"
            | "commander"
            | "general"
            | "elder"
            | "healer"
            | "warrior"
            | "mage"
            | "sorcerer"
            | "witch"
    )
}

fn is_connective(value: &str) -> bool {
    matches!(
        value.to_ascii_lowercase().as_str(),
        "of" | "the" | "and" | "&"
    )
}

fn looks_like_entity_token(value: &str) -> bool {
    value
        .chars()
        .next()
        .map(|ch| ch.is_uppercase())
        .unwrap_or(false)
        && value.chars().any(|ch| ch.is_alphabetic())
}

fn extend_species_role_span(
    text: &str,
    tokens: &[TokenSpan],
    start: usize,
) -> Option<(usize, TextRange, &'static str, f32)> {
    let token = tokens.get(start)?;
    if !matches!(token.token_class, Some(TokenClass::Word)) {
        return None;
    }
    let token_text = clean_word_token(safe_slice(text, token.range));
    if !is_species_denizen_term(token_text.as_str()) {
        return None;
    }

    let mut end_idx = start;
    let mut end = token.range.end;
    let mut label = "Creature";
    let mut confidence = 0.88;
    if let Some(next) = tokens.get(start + 1) {
        let next_text = clean_word_token(safe_slice(text, next.range));
        if gap_allows_entity_join(text, end, next.range.start)
            && is_species_person_role(next_text.as_str())
        {
            end_idx = start + 1;
            end = next.range.end;
            label = "NPC";
            confidence = 0.90;
        }
    }

    Some((
        end_idx,
        TextRange {
            start: token.range.start,
            end,
        },
        label,
        confidence,
    ))
}

fn clean_word_token(value: &str) -> String {
    value
        .trim_matches(|ch: char| !ch.is_alphanumeric() && ch != '-' && ch != '\'')
        .trim_end_matches("'s")
        .trim_end_matches('\u{2019}')
        .to_ascii_lowercase()
}

fn is_species_denizen_term(value: &str) -> bool {
    matches!(
        value,
        "devil" | "devils" | "dwarf" | "dwarves" | "titan" | "titans"
    )
}

fn is_species_person_role(value: &str) -> bool {
    matches!(
        value,
        "boy" | "girl" | "guard" | "man" | "teenager" | "woman"
    )
}

fn should_keep_cap_span(
    surface: &str,
    sentence_initial: bool,
    quoted_sentence_initial: bool,
    stats: CapSurfaceStats,
) -> bool {
    let cleaned = surface.trim_matches(|ch: char| {
        !(ch.is_alphanumeric()
            || ch == '-'
            || ch == '\''
            || ch == '\u{2019}'
            || ch == '&'
            || ch.is_whitespace())
    });
    if cleaned.len() < 2 {
        return false;
    }
    if cleaned.contains('_') || cleaned.contains('/') || cleaned.contains('\\') {
        return false;
    }
    if has_span_boundary_noise(cleaned) {
        return false;
    }

    let mut word_count = 0usize;
    let mut doc_word_count = 0usize;
    let mut first_word = "";
    for word in cleaned.split_whitespace() {
        if word_count == 0 {
            first_word = word;
        }
        word_count += 1;
        if is_doc_control_word(word) {
            doc_word_count += 1;
        }
    }
    if word_count == 0 {
        return false;
    }
    if is_common_sentence_starter(first_word) {
        return false;
    }
    if sentence_initial
        && !stats.has_mid_sentence()
        && !(word_count > 1 && has_location_suffix_word(cleaned))
        && !(quoted_sentence_initial && looks_like_person_name_span(cleaned))
    {
        return false;
    }
    if word_count == 1 {
        if is_all_caps_acronym(first_word)
            || is_doc_control_word(first_word)
            || is_native_single_word_noise(first_word)
        {
            return false;
        }
        return true;
    }
    if word_count > 4 && doc_word_count * 2 >= word_count {
        return false;
    }
    doc_word_count < word_count
}

fn looks_like_person_name_span(surface: &str) -> bool {
    let words = surface.split_whitespace().collect::<Vec<_>>();
    if !(2..=4).contains(&words.len()) {
        return false;
    }
    words.iter().all(|word| {
        !is_doc_control_word(word)
            && !is_common_sentence_starter(word)
            && word.split('-').all(|part| {
                part.chars().any(|ch| ch.is_alphabetic())
                    && part.chars().next().is_some_and(|ch| ch.is_uppercase())
            })
    })
}

fn has_location_suffix_word(surface: &str) -> bool {
    surface
        .split_whitespace()
        .last()
        .map(|word| {
            matches!(
                word.to_ascii_lowercase().as_str(),
                "access"
                    | "base"
                    | "camp"
                    | "city"
                    | "district"
                    | "fort"
                    | "gate"
                    | "land"
                    | "mesa"
                    | "province"
                    | "region"
                    | "station"
                    | "tower"
                    | "town"
                    | "valley"
            )
        })
        .unwrap_or(false)
}

fn collect_cap_surface_stats(
    text: &str,
    tokens: &[TokenSpan],
    sentences: &[SentenceSpan],
    known_ranges: &[TextRange],
    protected_ranges: &[TextRange],
) -> FxHashMap<CompactString, CapSurfaceStats> {
    let mut stats = FxHashMap::<CompactString, CapSurfaceStats>::default();
    let mut idx = 0usize;
    while idx < tokens.len() {
        let token = &tokens[idx];
        if capitalized_entity_token_range(text, token).is_none()
            || range_overlaps_any(token.range, known_ranges)
            || range_overlaps_any(token.range, protected_ranges)
        {
            idx += 1;
            continue;
        }

        let (end_idx, range) = extend_cap_span(text, tokens, idx);
        if !range_overlaps_any(range, protected_ranges) {
            let surface = safe_slice(text, range);
            if !surface.is_empty() && !has_span_boundary_noise(surface) {
                let normalized = CompactString::from(normalize_raw(surface));
                stats
                    .entry(normalized)
                    .or_default()
                    .bump(is_sentence_initial_range(text, range, sentences));
            }
        }
        idx = end_idx + 1;
    }
    stats
}

fn gap_allows_entity_join(text: &str, left_end: u32, right_start: u32) -> bool {
    if right_start < left_end {
        return false;
    }
    let Some(gap) = text.get(left_end as usize..right_start as usize) else {
        return false;
    };
    !gap.is_empty() && gap.chars().all(char::is_whitespace)
}

fn gap_allows_title_join(text: &str, left_end: u32, right_start: u32) -> bool {
    if right_start < left_end {
        return false;
    }
    let Some(gap) = text.get(left_end as usize..right_start as usize) else {
        return false;
    };
    !gap.is_empty()
        && gap.chars().all(|ch| ch.is_whitespace() || ch == '.')
        && gap.chars().any(char::is_whitespace)
}

fn is_sentence_initial_range(text: &str, range: TextRange, sentences: &[SentenceSpan]) -> bool {
    let sentence_index = locate_sentence(sentences, range);
    let Some(sentence) = sentences.get(sentence_index as usize) else {
        return false;
    };
    let prefix = safe_slice(
        text,
        TextRange {
            start: sentence.range.start,
            end: range.start,
        },
    );
    !prefix
        .chars()
        .any(|ch| ch.is_alphanumeric() && !is_quote_noise_char(ch))
}

fn sentence_initial_quoted_name_like(
    text: &str,
    range: TextRange,
    sentences: &[SentenceSpan],
) -> bool {
    if !is_sentence_initial_range(text, range, sentences) {
        return false;
    }
    let sentence_index = locate_sentence(sentences, range);
    let Some(sentence) = sentences.get(sentence_index as usize) else {
        return false;
    };
    let prefix = safe_slice(
        text,
        TextRange {
            start: sentence.range.start,
            end: range.start,
        },
    )
    .trim();
    !prefix.is_empty()
        && prefix.chars().any(is_quote_noise_char)
        && prefix
            .chars()
            .all(|ch| ch.is_whitespace() || is_quote_noise_char(ch))
}

fn is_quote_noise_char(ch: char) -> bool {
    matches!(
        ch,
        '"' | '\''
            | '\u{2018}'
            | '\u{2019}'
            | '\u{201c}'
            | '\u{201d}'
            | '\u{00e2}'
            | '\u{20ac}'
            | '\u{0153}'
            | '\u{009d}'
    )
}

fn has_span_boundary_noise(surface: &str) -> bool {
    surface.chars().any(|ch| {
        matches!(
            ch,
            '\n' | '\r' | ',' | '.' | ';' | ':' | '!' | '?' | '"' | '\u{201c}' | '\u{201d}'
        )
    })
}

fn is_native_single_word_noise(value: &str) -> bool {
    matches!(
        value
            .trim_matches(|ch: char| !ch.is_alphanumeric() && ch != '-' && ch != '\'')
            .to_ascii_lowercase()
            .as_str(),
        "i" | "i'm"
            | "i've"
            | "he"
            | "she"
            | "her"
            | "him"
            | "his"
            | "they"
            | "them"
            | "we"
            | "you"
            | "your"
            | "me"
            | "my"
            | "our"
            | "their"
            | "ah"
            | "aha"
            | "aww"
            | "eh"
            | "hey"
            | "hello"
            | "hi"
            | "mmm"
            | "nope"
            | "nah"
            | "italian"
            | "french"
            | "english"
            | "arabic"
            | "turkish"
            | "latin"
            | "korean"
            | "japanese"
            | "chinese"
            | "greek"
            | "roman"
            | "german"
            | "spanish"
            | "black"
            | "blue"
            | "green"
            | "orange"
            | "red"
            | "violet"
            | "white"
            | "yellow"
    )
}

fn is_common_sentence_starter(value: &str) -> bool {
    matches!(
        value.to_ascii_lowercase().as_str(),
        "a" | "an"
            | "about"
            | "according"
            | "actually"
            | "after"
            | "all"
            | "already"
            | "alright"
            | "also"
            | "although"
            | "always"
            | "among"
            | "and"
            | "the"
            | "this"
            | "that"
            | "these"
            | "those"
            | "it"
            | "if"
            | "are"
            | "as"
            | "at"
            | "because"
            | "before"
            | "both"
            | "but"
            | "by"
            | "can"
            | "come"
            | "could"
            | "did"
            | "does"
            | "driving"
            | "especially"
            | "even"
            | "everyone"
            | "finally"
            | "good"
            | "have"
            | "having"
            | "here"
            | "how"
            | "however"
            | "in"
            | "instead"
            | "is"
            | "just"
            | "last"
            | "like"
            | "look"
            | "made"
            | "man"
            | "may"
            | "maybe"
            | "neither"
            | "never"
            | "nobody"
            | "not"
            | "nothing"
            | "now"
            | "of"
            | "oh"
            | "okay"
            | "one"
            | "or"
            | "probably"
            | "since"
            | "so"
            | "some"
            | "someone"
            | "sorry"
            | "still"
            | "sure"
            | "thankfully"
            | "there"
            | "though"
            | "three"
            | "to"
            | "too"
            | "unfortunately"
            | "very"
            | "wait"
            | "well"
            | "what"
            | "whatever"
            | "when"
            | "where"
            | "while"
            | "who"
            | "why"
            | "with"
            | "without"
            | "yeah"
            | "yes"
            | "yet"
            | "for"
            | "each"
            | "every"
            | "once"
            | "then"
            | "no"
            | "do"
            | "use"
            | "run"
            | "allow"
            | "require"
            | "expected"
            | "missing"
            | "failure"
            | "purpose"
            | "test"
            | "add"
            | "compare"
            | "generate"
    )
}

fn is_doc_control_word(value: &str) -> bool {
    matches!(
        value
            .trim_matches(|ch: char| !ch.is_alphanumeric() && ch != '-')
            .to_ascii_lowercase()
            .as_str(),
        "assertion"
            | "assertions"
            | "baseline"
            | "benchmark"
            | "boundary-cell"
            | "chart"
            | "charts"
            | "chunk"
            | "chunking"
            | "cli"
            | "command"
            | "cone"
            | "cones"
            | "coverage"
            | "decision"
            | "determinism"
            | "embedding"
            | "embeddings"
            | "expected"
            | "fail"
            | "gate"
            | "gates"
            | "geometry"
            | "hash"
            | "hashes"
            | "ids"
            | "manifold"
            | "metric"
            | "metrics"
            | "output"
            | "pass"
            | "performance"
            | "phase"
            | "plan"
            | "projection"
            | "regression"
            | "report"
            | "reports"
            | "rss"
            | "seam"
            | "seams"
            | "smoke"
            | "test"
            | "topology"
            | "trace"
            | "traces"
            | "vector"
            | "vectors"
            | "warning"
            | "warnings"
    )
}

fn is_all_caps_acronym(value: &str) -> bool {
    let mut alpha_count = 0usize;
    let mut has_lower = false;
    for ch in value.chars().filter(|ch| ch.is_alphabetic()) {
        alpha_count += 1;
        if ch.is_lowercase() {
            has_lower = true;
        }
    }
    (2..=8).contains(&alpha_count) && !has_lower
}

fn markdown_protected_ranges(text: &str) -> Vec<TextRange> {
    let mut ranges = Vec::new();
    let mut offset = 0usize;
    let mut fence_start: Option<usize> = None;

    for line in text.split_inclusive('\n') {
        let line_start = offset;
        let line_end = offset + line.len();
        let line_no_newline = line.trim_end_matches(|ch| ch == '\r' || ch == '\n');
        let trimmed = line_no_newline.trim_start();
        let is_fence = trimmed.starts_with("```");

        if let Some(start) = fence_start {
            if is_fence {
                push_protected_range(&mut ranges, start, line_end);
                fence_start = None;
            }
            offset = line_end;
            continue;
        }

        if is_fence {
            fence_start = Some(line_start);
            offset = line_end;
            continue;
        }

        if is_markdown_heading(trimmed) || is_markdown_label_line(trimmed) {
            push_protected_range(&mut ranges, line_start, line_end);
        } else {
            add_inline_code_ranges(&mut ranges, line, line_start);
        }

        offset = line_end;
    }

    if let Some(start) = fence_start {
        push_protected_range(&mut ranges, start, text.len());
    }

    ranges
}

fn is_markdown_heading(trimmed: &str) -> bool {
    let hashes = trimmed.chars().take_while(|ch| *ch == '#').count();
    hashes > 0 && hashes <= 6 && trimmed.as_bytes().get(hashes) == Some(&b' ')
}

fn is_markdown_label_line(trimmed: &str) -> bool {
    if trimmed.len() > 80 || !trimmed.ends_with(':') || trimmed.contains('.') {
        return false;
    }
    trimmed.chars().any(|ch| ch.is_alphabetic())
        && !trimmed.starts_with('-')
        && !trimmed.starts_with('*')
}

fn add_inline_code_ranges(ranges: &mut Vec<TextRange>, line: &str, line_start: usize) {
    let bytes = line.as_bytes();
    let mut idx = 0usize;
    while idx < bytes.len() {
        if bytes[idx] != b'`' {
            idx += 1;
            continue;
        }
        let start = idx;
        idx += 1;
        while idx < bytes.len() && bytes[idx] != b'`' {
            idx += 1;
        }
        if idx < bytes.len() {
            push_protected_range(ranges, line_start + start, line_start + idx + 1);
            idx += 1;
        }
    }
}

fn push_protected_range(ranges: &mut Vec<TextRange>, start: usize, end: usize) {
    if start < end {
        ranges.push(TextRange {
            start: start as u32,
            end: end as u32,
        });
    }
}

fn range_overlaps_any(r: TextRange, ranges: &[TextRange]) -> bool {
    ranges
        .iter()
        .any(|other| r.start < other.end && other.start < r.end)
}

pub(crate) fn safe_slice(text: &str, range: TextRange) -> &str {
    let start = (range.start as usize).min(text.len());
    let end = (range.end as usize).min(text.len());
    text.get(start..end).unwrap_or("")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn title_token_matches() {
        assert!(is_title_token("Dr."));
        assert!(is_title_token("Captain"));
        assert!(!is_title_token("hello"));
    }

    #[test]
    fn nominal_role_matches() {
        assert!(is_nominal_role("captain"));
        assert!(is_nominal_role("warrior"));
        assert!(!is_nominal_role("quickly"));
    }

    #[test]
    fn connective_matches() {
        assert!(is_connective("of"));
        assert!(is_connective("The"));
        assert!(!is_connective("ran"));
    }

    #[test]
    fn entity_token_detection() {
        assert!(looks_like_entity_token("Kamaria"));
        assert!(!looks_like_entity_token("quickly"));
        assert!(!looks_like_entity_token("123"));
    }

    #[test]
    fn markdown_ranges_protect_headings_code_and_inline_code() {
        let text = "# CLI Shape\nUse `novel_full` now.\n```text\nPASS\n```\nAella waited.";
        let protected = markdown_protected_ranges(text);
        let heading = TextRange { start: 2, end: 5 };
        let inline = TextRange { start: 17, end: 27 };
        let fenced = TextRange { start: 43, end: 47 };
        let prose = TextRange { start: 52, end: 57 };
        assert!(range_overlaps_any(heading, &protected));
        assert!(range_overlaps_any(inline, &protected));
        assert!(range_overlaps_any(fenced, &protected));
        assert!(!range_overlaps_any(prose, &protected));
    }

    #[test]
    fn cap_span_guard_keeps_names_not_doc_terms() {
        let mid = CapSurfaceStats {
            total: 2,
            mid_sentence: 1,
        };
        assert!(should_keep_cap_span("Aella", false, false, mid));
        assert!(should_keep_cap_span("New Rome", false, false, mid));
        assert!(should_keep_cap_span("Red Mesa", false, false, mid));
        assert!(!should_keep_cap_span(
            "Aella",
            true,
            false,
            CapSurfaceStats::default()
        ));
        assert!(!should_keep_cap_span("CLI", false, false, mid));
        assert!(!should_keep_cap_span("The", false, false, mid));
        assert!(!should_keep_cap_span("Actually, I", false, false, mid));
        assert!(!should_keep_cap_span(
            "Projection Assertions",
            false,
            false,
            mid
        ));
        assert!(!should_keep_cap_span(
            "novel_full_manifold_smoke_v1",
            false,
            false,
            mid
        ));
    }

    #[test]
    fn sentence_initial_place_suffix_can_seed_location_span() {
        assert!(should_keep_cap_span(
            "Red Mesa",
            true,
            false,
            CapSurfaceStats::default()
        ));
        assert!(!should_keep_cap_span(
            "Red Claimant",
            true,
            false,
            CapSurfaceStats::default()
        ));
    }

    #[test]
    fn quoted_sentence_initial_full_name_can_seed_span() {
        let text = "The awning rope snapped. \"Borrik Vane-Tallow.\"";
        let tokens = test_tokens(text);
        let sentences = test_sentences(text);
        let borrik_index = tokens
            .iter()
            .position(|token| safe_slice(text, token.range) == "Borrik")
            .unwrap();
        let (_, range) = extend_cap_span(text, &tokens, borrik_index);
        assert_eq!(safe_slice(text, range), "Borrik Vane-Tallow");
        assert!(sentence_initial_quoted_name_like(text, range, &sentences));
        assert!(should_keep_cap_span(
            safe_slice(text, range),
            true,
            true,
            CapSurfaceStats::default()
        ));
        assert!(!should_keep_cap_span(
            "Projection Assertions",
            true,
            false,
            CapSurfaceStats::default()
        ));
    }

    #[test]
    fn species_denizen_terms_seed_creature_and_npc_spans() {
        let text = "Two dwarves argued. A devil woman waved. A Titan teenager crossed.";
        let tokens = test_tokens(text);
        let sentences = test_sentences(text);

        let candidates = NativeDiscoveryLane::discover(text, &tokens, &sentences, &[], 0);

        assert_native_label(&candidates, "dwarves", "Creature");
        assert_native_label(&candidates, "devil woman", "NPC");
        assert_native_label(&candidates, "Titan teenager", "NPC");
        assert!(!candidates
            .iter()
            .any(|candidate| candidate.surface.as_str() == "woman"));
    }

    #[test]
    fn known_first_name_can_still_seed_full_name_alias_span() {
        let text = "The dwarf nodded. \"Kai Gearlock,\" Kai said.";
        let tokens = test_tokens(text);
        let sentences = test_sentences(text);
        let known_start = text.find("Kai").unwrap();
        let known_ranges = [TextRange {
            start: known_start as u32,
            end: (known_start + "Kai".len()) as u32,
        }];

        let candidates = NativeDiscoveryLane::discover(text, &tokens, &sentences, &known_ranges, 0);

        assert!(candidates
            .iter()
            .any(|candidate| candidate.surface.as_str() == "Kai Gearlock"));
    }

    #[test]
    fn mojibake_quote_prefix_does_not_block_full_name_alias_span() {
        let text =
            "The dwarf nodded. \u{00e2}\u{20ac}\u{0153}Kai Gearlock,\u{00e2}\u{20ac}\u{009d} Kai said.";
        let tokens = test_tokens(text);
        let sentences = test_sentences(text);
        let known_start = text.find("Kai").unwrap();
        let known_ranges = [TextRange {
            start: known_start as u32,
            end: (known_start + "Kai".len()) as u32,
        }];

        let candidates = NativeDiscoveryLane::discover(text, &tokens, &sentences, &known_ranges, 0);

        assert!(candidates
            .iter()
            .any(|candidate| candidate.surface.as_str() == "Kai Gearlock"));
    }

    #[test]
    fn cap_span_extension_stops_at_punctuation() {
        let text = "A-bomb. As Ryan reached New Rome.";
        let tokens = test_tokens(text);

        let (first_end, first_range) = extend_cap_span(text, &tokens, 0);
        assert_eq!(first_end, 0);
        assert_eq!(safe_slice(text, first_range), "A-bomb");

        let new_index = tokens
            .iter()
            .position(|token| safe_slice(text, token.range) == "New")
            .unwrap();
        let (_, new_range) = extend_cap_span(text, &tokens, new_index);
        assert_eq!(safe_slice(text, new_range), "New Rome");
    }

    #[test]
    fn dialogue_cue_detection() {
        let span = SentenceSpan {
            index: 0,
            range: TextRange { start: 0, end: 30 },
        };
        assert!(NativeDiscoveryLane::has_dialogue_cue(
            "\"Hello,\" she said quietly.",
            &span
        ));
        assert!(!NativeDiscoveryLane::has_dialogue_cue(
            "The sky was blue and calm.",
            &SentenceSpan {
                index: 0,
                range: TextRange { start: 0, end: 25 }
            }
        ));
    }

    #[test]
    fn range_overlap_check() {
        let r = TextRange { start: 5, end: 10 };
        let others = [TextRange { start: 8, end: 15 }];
        assert!(range_overlaps_any(r, &others));
        let others2 = [TextRange { start: 10, end: 15 }];
        assert!(!range_overlaps_any(r, &others2));
    }

    fn test_tokens(text: &str) -> Vec<TokenSpan> {
        let mut tokens = Vec::new();
        let mut start = None;
        for (idx, ch) in text.char_indices() {
            if ch.is_alphanumeric() || ch == '\'' || ch == '-' {
                start.get_or_insert(idx);
            } else if let Some(token_start) = start.take() {
                tokens.push(TokenSpan {
                    range: TextRange {
                        start: token_start as u32,
                        end: idx as u32,
                    },
                    capitalized: text[token_start..].starts_with(char::is_uppercase),
                    pos: None,
                    token_class: Some(TokenClass::Word),
                    masked: false,
                });
            }
        }
        if let Some(token_start) = start {
            tokens.push(TokenSpan {
                range: TextRange {
                    start: token_start as u32,
                    end: text.len() as u32,
                },
                capitalized: text[token_start..].starts_with(char::is_uppercase),
                pos: None,
                token_class: Some(TokenClass::Word),
                masked: false,
            });
        }
        tokens
    }

    fn assert_native_label(candidates: &[NativeCandidate], surface: &str, label: &str) {
        let candidate = candidates
            .iter()
            .find(|candidate| candidate.surface.as_str() == surface)
            .expect(surface);
        assert_eq!(candidate.mention_kind, MentionKind::Named);
        assert!(candidate.votes.iter().any(|vote| {
            vote.label
                .as_ref()
                .is_some_and(|candidate_label| candidate_label.as_str() == label)
        }));
    }

    fn test_sentences(text: &str) -> Vec<SentenceSpan> {
        let mut sentences = Vec::new();
        let mut sent_start = 0usize;
        for (idx, ch) in text.char_indices() {
            if matches!(ch, '.' | '!' | '?') {
                sentences.push(SentenceSpan {
                    index: sentences.len(),
                    range: TextRange {
                        start: sent_start as u32,
                        end: (idx + ch.len_utf8()) as u32,
                    },
                });
                sent_start = idx + ch.len_utf8();
            }
        }
        if sent_start < text.len() {
            sentences.push(SentenceSpan {
                index: sentences.len(),
                range: TextRange {
                    start: sent_start as u32,
                    end: text.len() as u32,
                },
            });
        }
        sentences
    }
}
