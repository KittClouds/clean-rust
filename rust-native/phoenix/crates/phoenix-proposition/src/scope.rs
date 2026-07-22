use compact_str::CompactString;
use phoenix_types::{EntityId, RelationCandidate, ScopeOp, TextRange};
use smallvec::{smallvec, SmallVec};

#[derive(Default)]
pub(crate) struct SentenceScope {
    pub scope_ops: SmallVec<[ScopeOp; 2]>,
    pub quote_range: Option<TextRange>,
    pub attribution_range: Option<TextRange>,
    pub speaker_entity_id: Option<EntityId>,
    pub conditional: Option<ConditionalRanges>,
}

pub(crate) struct ConditionalRanges {
    pub condition: Option<TextRange>,
    pub consequent: Option<TextRange>,
}

pub(crate) fn analyze_sentence_scope(
    text: &str,
    sentence_range: TextRange,
    relation: &RelationCandidate,
) -> SentenceScope {
    let sentence = slice(text, sentence_range);
    let lower = sentence.to_lowercase();
    let mut scope_ops = smallvec![ScopeOp {
        kind: CompactString::from("assertion"),
        polarity: None,
        modality: None,
    }];

    if contains_any_word(
        &lower,
        &[
            "not", "never", "neither", "nor", "cannot", "can't", "won't", "didn't", "doesn't",
            "isn't", "wasn't",
        ],
    ) || contains_phrase(&lower, "no longer")
    {
        scope_ops.push(ScopeOp {
            kind: CompactString::from("polarity"),
            polarity: Some(CompactString::from("negative")),
            modality: None,
        });
    }

    if let Some(modality) = first_word(
        &lower,
        &[
            "may", "might", "could", "can", "must", "should", "would", "will", "perhaps",
            "probably", "possibly", "likely",
        ],
    ) {
        scope_ops.push(ScopeOp {
            kind: CompactString::from("modality"),
            polarity: None,
            modality: Some(CompactString::from(modality)),
        });
    }

    if sentence.trim_end().ends_with('?') {
        scope_ops.push(ScopeOp {
            kind: CompactString::from("question"),
            polarity: None,
            modality: None,
        });
    } else if relation.subject.is_none()
        && relation.verb_range.start <= sentence_range.start.saturating_add(12)
    {
        scope_ops.push(ScopeOp {
            kind: CompactString::from("directive"),
            polarity: None,
            modality: Some(CompactString::from("imperative")),
        });
    }

    let quote_range = find_quote_range(sentence, sentence_range.start);
    let communication = relation.event_class == "communication"
        || matches!(
            relation.lemma.as_str(),
            "say" | "tell" | "report" | "announce" | "ask" | "reply" | "claim" | "write"
        );
    if communication || quote_range.is_some() {
        scope_ops.push(ScopeOp {
            kind: CompactString::from("attribution"),
            polarity: None,
            modality: communication.then(|| CompactString::from("reported")),
        });
    }

    let conditional = find_conditional(sentence, sentence_range.start);
    if conditional.is_some() {
        scope_ops.push(ScopeOp {
            kind: CompactString::from("conditional"),
            polarity: None,
            modality: Some(CompactString::from("conditional")),
        });
    }

    SentenceScope {
        scope_ops,
        quote_range,
        attribution_range: (communication || quote_range.is_some())
            .then_some(quote_range.unwrap_or(sentence_range)),
        speaker_entity_id: relation.subject.as_ref().and_then(|slot| {
            slot.entity_ref.as_ref().and_then(|entity| match entity {
                phoenix_types::MentionEntityRef::Known(id) => Some(id.clone()),
                phoenix_types::MentionEntityRef::Speculative(_) => None,
            })
        }),
        conditional,
    }
}

pub(crate) fn attachment_role(text: &str, range: TextRange) -> &'static str {
    let lower = slice(text, range).trim_start().to_ascii_lowercase();
    let first = lower.split_whitespace().next().unwrap_or_default();
    match first {
        "at" | "in" | "inside" | "near" | "on" | "under" | "within" => "location",
        "before" | "after" | "during" | "since" | "until" | "when" => "time",
        "from" => "source",
        "into" | "onto" | "toward" | "towards" | "to" => "destination",
        "because" | "due" => "cause",
        "with" | "using" | "via" => "instrument",
        _ => "context",
    }
}

fn find_conditional(sentence: &str, base: u32) -> Option<ConditionalRanges> {
    let lower = sentence.to_lowercase();
    let marker = ["if", "unless", "provided that", "assuming"]
        .iter()
        .find_map(|candidate| {
            find_phrase_start(&lower, candidate).map(|index| (index, *candidate))
        })?;
    let condition_start = marker.0;
    let separator = sentence[condition_start..]
        .find(',')
        .map(|offset| condition_start + offset);
    let sentence_end = sentence.len();
    let condition_end = separator.unwrap_or(sentence_end);
    let consequent_start = separator.map(|index| {
        sentence[index + 1..]
            .find(|ch: char| !ch.is_whitespace())
            .map(|offset| index + 1 + offset)
            .unwrap_or(sentence_end)
    });
    Some(ConditionalRanges {
        condition: Some(range(base, condition_start, condition_end)),
        consequent: consequent_start
            .filter(|start| *start < sentence_end)
            .map(|start| range(base, start, sentence_end)),
    })
}

fn find_quote_range(sentence: &str, base: u32) -> Option<TextRange> {
    const PAIRS: [(&str, &str); 7] = [
        ("\"", "\""),
        ("Â«", "Â»"),
        ("â€œ", "â€"),
        ("â€˜", "â€™"),
        ("“", "”"),
        ("‘", "’"),
        ("«", "»"),
    ];
    for (open, close) in PAIRS {
        let Some(start) = sentence.find(open) else {
            continue;
        };
        let content_start = start + open.len();
        let Some(close_offset) = sentence[content_start..].find(close) else {
            continue;
        };
        return Some(range(base, content_start, content_start + close_offset));
    }
    None
}

fn first_word<'a>(text: &str, candidates: &'a [&'a str]) -> Option<&'a str> {
    candidates
        .iter()
        .copied()
        .find(|candidate| contains_word(text, candidate))
}

fn contains_any_word(text: &str, candidates: &[&str]) -> bool {
    candidates
        .iter()
        .any(|candidate| contains_word(text, candidate))
}

fn contains_phrase(text: &str, phrase: &str) -> bool {
    text.match_indices(phrase).any(|(index, _)| {
        boundary(text, index.checked_sub(1)) && boundary(text, Some(index + phrase.len()))
    })
}

fn contains_word(text: &str, word: &str) -> bool {
    find_word_start(text, word).is_some()
}

fn find_word_start(text: &str, word: &str) -> Option<usize> {
    text.match_indices(word).find_map(|(index, _)| {
        (boundary(text, index.checked_sub(1)) && boundary(text, Some(index + word.len())))
            .then_some(index)
    })
}

fn find_phrase_start(text: &str, phrase: &str) -> Option<usize> {
    text.match_indices(phrase).find_map(|(index, _)| {
        (boundary(text, index.checked_sub(1)) && boundary(text, Some(index + phrase.len())))
            .then_some(index)
    })
}

fn boundary(text: &str, index: Option<usize>) -> bool {
    let Some(index) = index else {
        return true;
    };
    text.get(index..)
        .and_then(|tail| tail.chars().next())
        .map(|ch| !ch.is_alphanumeric() && ch != '_')
        .unwrap_or(true)
}

fn slice(text: &str, range: TextRange) -> &str {
    text.get(range.start as usize..range.end as usize)
        .unwrap_or_default()
}

fn range(base: u32, start: usize, end: usize) -> TextRange {
    TextRange {
        start: base.saturating_add(start.min(u32::MAX as usize) as u32),
        end: base.saturating_add(end.min(u32::MAX as usize) as u32),
    }
}

#[cfg(test)]
mod tests {
    use phoenix_types::{RelationCandidate, TextRange};

    use super::{analyze_sentence_scope, find_quote_range};

    #[test]
    fn detects_mojibake_quotes_used_by_imported_books() {
        let text = "Ryan said, Â«QuicksaveÂ» would return.";
        let range = find_quote_range(text, 0).expect("quote");
        assert_eq!(&text[range.start as usize..range.end as usize], "Quicksave");
    }

    #[test]
    fn detects_negative_modal_conditional_scope() {
        let text = "If Kai returns, Hazel might not leave.";
        let relation = RelationCandidate {
            event_class: "movement".to_owned(),
            lemma: "leave".to_owned(),
            ..RelationCandidate::default()
        };
        let scope = analyze_sentence_scope(
            text,
            TextRange {
                start: 0,
                end: text.len() as u32,
            },
            &relation,
        );
        assert!(scope.conditional.is_some());
        assert!(scope.scope_ops.iter().any(|op| op.polarity.is_some()));
        assert!(scope.scope_ops.iter().any(|op| op.modality.is_some()));
    }
}
