use phoenix_types::{PosTag, Proposition, SourceRange, TextRange, TokenSpan};

use super::DocumentSemanticArgument;

#[derive(Clone, Debug)]
pub(super) struct RolePrecision {
    pub semantic_role: &'static str,
    pub confidence_millis: u16,
    pub failure_reasons: Vec<String>,
}

pub(super) fn role_precision_for(
    syntactic_role: &str,
    relation_type: &str,
    surface: &str,
    resolved_entity: bool,
    has_span: bool,
) -> RolePrecision {
    let semantic_role = semantic_role_for(syntactic_role, relation_type);
    let mut score = role_base_confidence(syntactic_role, semantic_role);
    let mut failure_reasons = Vec::with_capacity(3);
    if resolved_entity {
        score += 70;
    } else if !surface.is_empty() && semantic_role_prefers_entity(semantic_role) {
        score -= 95;
        failure_reasons.push("unresolved_entity".to_owned());
    }
    if surface.is_empty() {
        score -= 180;
        failure_reasons.push("missing_surface".to_owned());
    }
    if !has_span {
        score -= 130;
        failure_reasons.push("missing_span".to_owned());
    }
    if semantic_role == "context" {
        score -= 70;
        failure_reasons.push("generic_context_role".to_owned());
    }
    if semantic_role == "role_unknown" {
        score -= 140;
        failure_reasons.push("unmapped_syntactic_role".to_owned());
    }
    RolePrecision {
        semantic_role,
        confidence_millis: score.clamp(120, 980) as u16,
        failure_reasons,
    }
}

fn semantic_role_for(syntactic_role: &str, relation_type: &str) -> &'static str {
    match syntactic_role {
        "subject" => subject_semantic_role(relation_type),
        "object" => "theme",
        "recipient" => "recipient",
        "source" => "source",
        "destination" => "destination",
        "location" => "location",
        "time" => "time",
        "cause" => "cause",
        "instrument" => "instrument",
        "context" | "attachment" => "context",
        _ => "role_unknown",
    }
}

fn subject_semantic_role(relation_type: &str) -> &'static str {
    if relation_type.contains("state")
        || relation_type.contains("identity")
        || relation_type.contains("attribute")
    {
        "bearer"
    } else if relation_type.contains("perception") || relation_type.contains("cognition") {
        "experiencer"
    } else {
        "actor"
    }
}

fn role_base_confidence(syntactic_role: &str, semantic_role: &str) -> i32 {
    match (syntactic_role, semantic_role) {
        ("subject" | "object" | "recipient", _) => 820,
        (_, "source" | "destination" | "location" | "time" | "cause" | "instrument") => 760,
        (_, "context") => 650,
        _ => 580,
    }
}

fn semantic_role_prefers_entity(role: &str) -> bool {
    matches!(
        role,
        "actor"
            | "bearer"
            | "experiencer"
            | "theme"
            | "recipient"
            | "source"
            | "destination"
            | "location"
            | "cause"
            | "instrument"
    )
}

pub(super) fn proposition_confidence(
    proposition: &Proposition,
    arguments: &[DocumentSemanticArgument],
    quality: &PredicateQuality,
) -> u16 {
    let resolved = arguments
        .iter()
        .filter(|argument| argument.entity_id.is_some())
        .count();
    let weak_roles = arguments
        .iter()
        .filter(|argument| argument.role_confidence_millis < 500)
        .count();
    let mut score = 560i32 + arguments.len().min(3) as i32 * 70 + resolved.min(2) as i32 * 75;
    score -= weak_roles.min(2) as i32 * 45;
    if proposition.quote.is_some() || proposition.conditional.is_some() {
        score += 35;
    }
    score += quality.score_delta;
    score.clamp(160, 960) as u16
}

#[derive(Clone, Debug)]
pub(super) struct PredicateQuality {
    pub quality: &'static str,
    pub admission: &'static str,
    pub score_delta: i32,
    pub reasons: Vec<String>,
}

pub(super) fn predicate_quality(
    text: &str,
    proposition: &Proposition,
    arguments: &[DocumentSemanticArgument],
    tokens: &[TokenSpan],
) -> PredicateQuality {
    let predicate = proposition.predicate.predicate.to_ascii_lowercase();
    let trigger = proposition.predicate.trigger_range;
    let index = token_index_for_range(tokens, trigger);
    let previous = index.and_then(|value| previous_token_in_sentence(tokens, value, trigger));
    let next = index.and_then(|value| next_token_in_sentence(tokens, value, trigger));
    let previous_pos = previous
        .and_then(|value| tokens.get(value))
        .and_then(|token| token.pos.as_ref());
    let next_pos = next
        .and_then(|value| tokens.get(value))
        .and_then(|token| token.pos.as_ref());
    let previous_surface = previous
        .and_then(|value| tokens.get(value))
        .map(|token| slice_range(text, token.range).to_ascii_lowercase())
        .unwrap_or_default();
    let has_subject = arguments
        .iter()
        .any(|argument| argument.syntactic_role == "subject");
    let resolved = arguments
        .iter()
        .filter(|argument| argument.entity_id.is_some())
        .count();
    let has_core_argument = arguments.iter().any(|argument| {
        matches!(
            argument.semantic_role.as_str(),
            "theme" | "recipient" | "cause" | "destination" | "source" | "location"
        )
    });
    let scoped = proposition
        .scope_ops
        .iter()
        .any(|scope| scope.kind != "assertion");
    let relation_type = proposition.predicate.relation_type.as_str();
    let ing = predicate.ends_with("ing");
    let ed = predicate.ends_with("ed");
    let next_nominal = next_pos.is_some_and(is_nominal);
    let recent_perfect_auxiliary = index.is_some_and(|value| {
        has_recent_perfect_auxiliary_before_predicate(text, tokens, value, trigger)
    });
    let previous_predicate_context = previous_pos
        .is_some_and(|pos| matches!(pos, PosTag::Verb | PosTag::Auxiliary | PosTag::Modal));
    let previous_modifier = previous_pos.is_some_and(|pos| {
        matches!(
            pos,
            PosTag::Determiner | PosTag::Adjective | PosTag::Preposition | PosTag::Conjunction
        )
    }) || matches!(
        previous_surface.as_str(),
        "his" | "her" | "their" | "my" | "our" | "your" | "its" | "perfect" | "different"
    );
    let strong_frame =
        (has_subject && (has_core_argument || resolved > 0 || scoped)) || arguments.len() >= 3;

    let mut reasons = Vec::with_capacity(4);
    if is_noise_predicate(&predicate) {
        reasons.push("predicate_stop_or_ordinal".to_owned());
        return PredicateQuality {
            quality: "noise",
            admission: "ledger_only",
            score_delta: -320,
            reasons,
        };
    }
    if ed && recent_perfect_auxiliary {
        reasons.push("perfect_auxiliary_context".to_owned());
    }
    if (ed || ing)
        && next_nominal
        && !recent_perfect_auxiliary
        && (!has_subject
            || previous_modifier
            || previous_predicate_context
            || relation_type == "relates_to"
            || !has_core_argument)
    {
        reasons.push("participle_before_nominal".to_owned());
        reasons.push("attribute_descriptor_not_event".to_owned());
        return PredicateQuality {
            quality: "participle_modifier",
            admission: "ledger_only",
            score_delta: -220,
            reasons,
        };
    }
    if ing && !has_subject {
        reasons.push("gerund_without_actor".to_owned());
        let quality = if previous_modifier || !has_core_argument {
            "nominal_event"
        } else {
            "gerund_action"
        };
        return PredicateQuality {
            quality,
            admission: if arguments.len() >= 3 && scoped {
                "review"
            } else {
                "ledger_only"
            },
            score_delta: if arguments.len() >= 3 && scoped {
                -20
            } else {
                -150
            },
            reasons,
        };
    }
    if matches!(
        predicate.as_str(),
        "be" | "is" | "are" | "was" | "were" | "been" | "being"
    ) || relation_type.contains("state")
        || relation_type.contains("identity")
        || relation_type.contains("attribute")
    {
        reasons.push("copula_or_state_relation".to_owned());
        return PredicateQuality {
            quality: "copula_state",
            admission: if strong_frame {
                "review"
            } else {
                "ledger_only"
            },
            score_delta: if strong_frame { 45 } else { -80 },
            reasons,
        };
    }
    if ed && previous_surface_matches_be(&previous_surface) {
        reasons.push("passive_auxiliary_context".to_owned());
        return PredicateQuality {
            quality: "passive_event",
            admission: if has_core_argument || resolved > 0 {
                "review"
            } else {
                "ledger_only"
            },
            score_delta: if has_core_argument || resolved > 0 {
                35
            } else {
                -80
            },
            reasons,
        };
    }
    if relation_type != "action" && relation_type != "relates_to" {
        reasons.push("typed_relation_cue".to_owned());
        return PredicateQuality {
            quality: "relation_cue",
            admission: if strong_frame
                || proposition.conditional.is_some()
                || proposition.quote.is_some()
            {
                "review"
            } else {
                "ledger_only"
            },
            score_delta: if strong_frame { 60 } else { -40 },
            reasons,
        };
    }
    reasons.push(
        if has_subject {
            "finite_subject_frame"
        } else {
            "weak_action_context"
        }
        .to_owned(),
    );
    PredicateQuality {
        quality: if has_subject {
            "finite_verb"
        } else if ing {
            "gerund_action"
        } else {
            "action_context"
        },
        admission: if strong_frame
            || proposition.attribution.is_some()
            || proposition.conditional.is_some()
        {
            "review"
        } else {
            "ledger_only"
        },
        score_delta: if strong_frame { 45 } else { -110 },
        reasons,
    }
}

fn slice_range(text: &str, range: TextRange) -> &str {
    text.get(range.start as usize..range.end as usize)
        .unwrap_or_default()
}

fn token_index_for_range(tokens: &[TokenSpan], range: SourceRange) -> Option<usize> {
    tokens
        .iter()
        .position(|token| token.range.start <= range.start && token.range.end >= range.end)
        .or_else(|| {
            tokens
                .iter()
                .position(|token| token.range.start < range.end && token.range.end > range.start)
        })
}

fn previous_token_in_sentence(
    tokens: &[TokenSpan],
    index: usize,
    trigger: SourceRange,
) -> Option<usize> {
    index.checked_sub(1).filter(|previous| {
        tokens
            .get(*previous)
            .is_some_and(|token| trigger.start.saturating_sub(token.range.end) <= 64)
    })
}

fn next_token_in_sentence(
    tokens: &[TokenSpan],
    index: usize,
    trigger: SourceRange,
) -> Option<usize> {
    let next = index + 1;
    (next < tokens.len()
        && tokens
            .get(next)
            .is_some_and(|token| token.range.start.saturating_sub(trigger.end) <= 64))
    .then_some(next)
}

fn is_nominal(pos: &PosTag) -> bool {
    matches!(pos, PosTag::Noun | PosTag::Pronoun | PosTag::ProperNoun)
}

fn has_recent_perfect_auxiliary_before_predicate(
    text: &str,
    tokens: &[TokenSpan],
    index: usize,
    trigger: SourceRange,
) -> bool {
    let mut cursor = index;
    let mut skipped = 0usize;
    while let Some(previous) = cursor.checked_sub(1) {
        let Some(token) = tokens.get(previous) else {
            return false;
        };
        if trigger.start.saturating_sub(token.range.end) > 96 {
            return false;
        }
        let surface = slice_range(text, token.range).trim();
        if surface_matches_perfect_auxiliary(surface) {
            return true;
        }
        let skippable = token
            .pos
            .as_ref()
            .is_some_and(|pos| matches!(pos, PosTag::Adverb))
            || surface_matches_auxiliary_adverb(surface);
        if !skippable || skipped >= 3 {
            return false;
        }
        skipped += 1;
        cursor = previous;
    }
    false
}

fn surface_matches_perfect_auxiliary(value: &str) -> bool {
    value.eq_ignore_ascii_case("had")
        || value.eq_ignore_ascii_case("has")
        || value.eq_ignore_ascii_case("have")
        || value.eq_ignore_ascii_case("having")
}

fn surface_matches_auxiliary_adverb(value: &str) -> bool {
    value.eq_ignore_ascii_case("not")
        || value.eq_ignore_ascii_case("n't")
        || value.eq_ignore_ascii_case("already")
        || value.eq_ignore_ascii_case("just")
        || value.eq_ignore_ascii_case("never")
        || value.eq_ignore_ascii_case("still")
        || value.eq_ignore_ascii_case("also")
        || value.eq_ignore_ascii_case("then")
        || value.eq_ignore_ascii_case("ever")
        || value.eq_ignore_ascii_case("almost")
}

fn previous_surface_matches_be(value: &str) -> bool {
    matches!(
        value,
        "is" | "are" | "was" | "were" | "be" | "been" | "being"
    )
}

fn is_noise_predicate(value: &str) -> bool {
    value.is_empty()
        || value.len() < 2
        || matches!(
            value,
            "he" | "she"
                | "it"
                | "they"
                | "his"
                | "her"
                | "their"
                | "this"
                | "that"
                | "these"
                | "those"
        )
        || value.chars().next().is_some_and(|ch| ch.is_ascii_digit())
        || matches!(value, "and" | "or" | "but")
}
