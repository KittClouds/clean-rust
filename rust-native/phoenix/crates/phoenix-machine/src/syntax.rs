use phoenix_chunker_native::split_sentence_ranges;
use phoenix_types::{PosTag, SentenceSpan, TokenClass, TokenSpan};

#[cfg(test)]
use phoenix_types::ChunkSpan;

pub(crate) fn tokenize(text: &str) -> super::TokenizedDocument {
    let mut tokens = Vec::with_capacity(text.len() / 5);
    let mut normalized_tokens = Vec::with_capacity(text.len() / 5);
    let mut chars = text.char_indices().peekable();
    while let Some((start, ch)) = chars.next() {
        if ch.is_whitespace() {
            continue;
        }

        if ch.is_alphanumeric() || ch == '\'' || ch == '-' {
            let mut end = start + ch.len_utf8();
            while let Some((next_ix, next)) = chars.peek().copied() {
                if next.is_alphanumeric() || next == '\'' || next == '-' {
                    chars.next();
                    end = next_ix + next.len_utf8();
                } else {
                    break;
                }
            }

            let surface = &text[start..end];
            let normalized = super::normalize_token_surface(surface);
            let token_class = if surface.chars().all(|value| value.is_ascii_digit()) {
                TokenClass::Number
            } else {
                TokenClass::Word
            };
            let capitalized = surface
                .chars()
                .next()
                .is_some_and(|value| value.is_uppercase());
            tokens.push(TokenSpan {
                range: super::to_range(start, end),
                token_class: Some(token_class),
                pos: Some(guess_pos(surface, &normalized, capitalized)),
                masked: false,
                capitalized,
            });
            normalized_tokens.push(normalized);
        } else {
            tokens.push(TokenSpan {
                range: super::to_range(start, start + ch.len_utf8()),
                token_class: Some(if ch.is_ascii_punctuation() {
                    TokenClass::Punctuation
                } else {
                    TokenClass::Symbol
                }),
                pos: Some(PosTag::Punctuation),
                masked: false,
                capitalized: false,
            });
            normalized_tokens.push(String::new());
        }
    }

    retag_with_context(text, &mut tokens);
    super::TokenizedDocument {
        tokens,
        normalized_tokens,
    }
}

pub(crate) fn sentence_spans(text: &str) -> Vec<SentenceSpan> {
    let mut spans = Vec::new();
    for (index, (start, end)) in split_sentence_ranges(text).into_iter().enumerate() {
        spans.push(SentenceSpan {
            index,
            range: super::to_range(start, end),
        });
    }
    if spans.is_empty() && !text.trim().is_empty() {
        let start = text.len().saturating_sub(text.trim_start().len());
        let end = text.trim_end().len();
        spans.push(SentenceSpan {
            index: 0,
            range: super::to_range(start, end),
        });
    }
    spans
}

#[cfg(test)]
pub(crate) fn build_chunks(
    text: &str,
    tokens: &[TokenSpan],
    _normalized_tokens: &[String],
    sentences: &[SentenceSpan],
) -> Vec<ChunkSpan> {
    crate::dependency_syntax::build_dependency_syntax(text, tokens, sentences).chunks
}

pub(crate) fn retag_with_context(text: &str, tokens: &mut [TokenSpan]) {
    for index in 0..tokens.len() {
        let current = token_pos(tokens, index).unwrap_or(PosTag::Other);
        let previous = index
            .checked_sub(1)
            .and_then(|value| token_pos(tokens, value))
            .unwrap_or(PosTag::Other);
        let next = tokens
            .get(index + 1)
            .and_then(|_| token_pos(tokens, index + 1));

        if matches!(previous, PosTag::Determiner | PosTag::Adjective) && is_verbal(&current) {
            tokens[index].pos = Some(PosTag::Noun);
        }
        if previous == PosTag::Modal && current == PosTag::Noun {
            let surface = super::slice_or_empty(text, tokens[index].range);
            if !surface.starts_with(|ch: char| ch.is_ascii_digit()) {
                tokens[index].pos = Some(PosTag::Verb);
            }
        }
        if current == PosTag::Noun
            && previous == PosTag::Determiner
            && next.as_ref().is_some_and(is_nominal)
        {
            tokens[index].pos = Some(PosTag::Adjective);
        }
        if current == PosTag::ProperNoun && next == Some(PosTag::Verb) {
            tokens[index].pos = Some(PosTag::Noun);
        }
        if current == PosTag::Other {
            let surface = super::slice_or_empty(text, tokens[index].range);
            if surface.ends_with("ly") {
                tokens[index].pos = Some(PosTag::Adverb);
            }
        }
    }
}

fn guess_pos(surface: &str, normalized: &str, capitalized: bool) -> PosTag {
    if normalized.is_empty() {
        return PosTag::Other;
    }
    if matches!(surface, "." | "," | "!" | "?" | "(" | ")" | ":" | ";") {
        return PosTag::Punctuation;
    }
    if is_pronoun(normalized) {
        return PosTag::Pronoun;
    }
    if matches!(normalized, "who" | "that" | "which" | "whom") {
        return PosTag::RelativePronoun;
    }
    if matches!(
        normalized,
        "the" | "a" | "an" | "this" | "that" | "these" | "those"
    ) {
        return PosTag::Determiner;
    }
    if matches!(
        normalized,
        "in" | "on"
            | "at"
            | "to"
            | "from"
            | "with"
            | "into"
            | "over"
            | "under"
            | "around"
            | "through"
            | "after"
            | "before"
            | "for"
            | "of"
            | "by"
            | "near"
            | "within"
    ) {
        return PosTag::Preposition;
    }
    if matches!(normalized, "and" | "or" | "but" | "nor" | "yet") {
        return PosTag::Conjunction;
    }
    if matches!(
        normalized,
        "can" | "could" | "should" | "would" | "may" | "might" | "will"
    ) {
        return PosTag::Modal;
    }
    if matches!(
        normalized,
        "is" | "are"
            | "was"
            | "were"
            | "be"
            | "been"
            | "being"
            | "have"
            | "has"
            | "had"
            | "do"
            | "does"
            | "did"
    ) {
        return PosTag::Auxiliary;
    }
    if normalized.ends_with("ly") {
        return PosTag::Adverb;
    }
    if [
        "ous", "ful", "ive", "al", "less", "able", "ible", "ic", "ish", "ant", "ent",
    ]
    .iter()
    .any(|suffix| normalized.ends_with(suffix))
    {
        return PosTag::Adjective;
    }
    if super::is_verb_token(normalized)
        || normalized.ends_with("ed")
        || normalized.ends_with("ing")
        || matches!(
            normalized,
            "said" | "told" | "left" | "built" | "found" | "felt"
        )
    {
        return PosTag::Verb;
    }
    if capitalized {
        return PosTag::ProperNoun;
    }
    PosTag::Noun
}

fn token_pos(tokens: &[TokenSpan], index: usize) -> Option<PosTag> {
    tokens.get(index).and_then(|token| token.pos.clone())
}

fn is_pronoun(value: &str) -> bool {
    matches!(
        value,
        "he" | "him"
            | "his"
            | "she"
            | "her"
            | "hers"
            | "it"
            | "its"
            | "they"
            | "them"
            | "their"
            | "we"
            | "us"
            | "i"
            | "me"
            | "you"
    )
}

fn is_nominal(tag: &PosTag) -> bool {
    matches!(tag, PosTag::Noun | PosTag::Pronoun | PosTag::ProperNoun)
}

fn is_verbal(tag: &PosTag) -> bool {
    matches!(tag, PosTag::Verb | PosTag::Auxiliary | PosTag::Modal)
}

#[cfg(test)]
mod tests {
    use phoenix_types::{ChunkKind, PosTag};

    use super::{build_chunks, sentence_spans, tokenize};

    #[test]
    fn sentence_splitter_respects_short_guards() {
        let text = "Dr. Luffy ran. Mr. Zoro stayed. Wow!";
        let spans = sentence_spans(text);
        assert_eq!(spans.len(), 3);
        assert_eq!(
            &text[spans[0].range.start as usize..spans[0].range.end as usize],
            "Dr. Luffy ran."
        );
    }

    #[test]
    fn tokenization_recovers_richer_pos_tags() {
        let tokenized = tokenize("The quick fox can move into harbor.");
        let tags = tokenized
            .tokens
            .iter()
            .map(|token| token.pos.clone().expect("tag"))
            .collect::<Vec<_>>();
        assert_eq!(tags[0], PosTag::Determiner);
        assert_eq!(tags[1], PosTag::Adjective);
        assert_eq!(tags[3], PosTag::Modal);
        assert_eq!(tags[5], PosTag::Preposition);
    }

    #[test]
    fn modal_context_does_not_turn_pronouns_or_ordinals_into_verbs() {
        let tokenized = tokenize("Will he leave? May 8th return again.");
        let surfaces = tokenized
            .tokens
            .iter()
            .map(|token| {
                &"Will he leave? May 8th return again."
                    [token.range.start as usize..token.range.end as usize]
            })
            .zip(tokenized.tokens.iter().map(|token| token.pos.clone()))
            .collect::<Vec<_>>();
        assert!(surfaces.contains(&("he", Some(PosTag::Pronoun))));
        assert!(surfaces.contains(&("8th", Some(PosTag::Noun))));
    }

    #[test]
    fn rustling_pos_retagger_recovers_contextual_ambiguity() {
        let text = "The can rusted. The left door opened.";
        let mut tokenized = tokenize(text);
        let sentences = sentence_spans(text);
        crate::pos::retag_with_rustling_pos(text, &mut tokenized, &sentences);
        super::retag_with_context(text, &mut tokenized.tokens);
        let tags = tokenized
            .tokens
            .iter()
            .map(|token| token.pos.clone().expect("tag"))
            .collect::<Vec<_>>();

        assert_eq!(tags[1], PosTag::Noun);
        assert_eq!(tags[5], PosTag::Adjective);
    }

    #[test]
    fn chunk_builder_recovers_np_vp_and_pp_spans() {
        let text = "The brave captain quickly moved into the harbor.";
        let tokenized = tokenize(text);
        let sentences = sentence_spans(text);
        let chunks = build_chunks(
            text,
            &tokenized.tokens,
            &tokenized.normalized_tokens,
            &sentences,
        );

        assert!(chunks.iter().any(|chunk| chunk.kind == Some(ChunkKind::Np)));
        assert!(chunks.iter().any(|chunk| chunk.kind == Some(ChunkKind::Vp)));
        assert!(chunks.iter().any(|chunk| chunk.kind == Some(ChunkKind::Pp)));
        assert!(chunks
            .iter()
            .any(|chunk| chunk.kind == Some(ChunkKind::Clause)));
    }
}
