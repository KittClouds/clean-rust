use phoenix_types::{
    FrameFactCandidate, FrameSlot, FrameSlotSource, TextRange, UmrLiteArgument, UmrLiteFrame,
    UmrLiteRole, UmrLiteScope, UmrLiteScopeKind, VerbFrame,
};

pub(crate) fn frames_from_verb_frames(
    text: &str,
    sentence_index: usize,
    verb_frames: &[VerbFrame],
) -> (Vec<UmrLiteFrame>, Vec<FrameFactCandidate>) {
    let frames = verb_frames
        .iter()
        .map(|frame| umr_frame_from_verb_frame(text, sentence_index, frame))
        .collect::<Vec<_>>();
    let facts = frames
        .iter()
        .flat_map(facts_from_umr_frame)
        .collect::<Vec<_>>();
    (frames, facts)
}

fn umr_frame_from_verb_frame(text: &str, sentence_index: usize, frame: &VerbFrame) -> UmrLiteFrame {
    let frame_id = format!(
        "umr::{sentence_index}:{}:{}:{:016x}",
        frame.verb_range.start,
        frame.verb_range.end,
        hash64(frame.lemma.as_bytes())
    );
    let mut arguments = Vec::new();
    arguments.extend(
        frame
            .subject_candidates
            .iter()
            .map(|slot| argument_from_slot(text, UmrLiteRole::Actor, slot)),
    );
    arguments.extend(
        frame
            .object_candidates
            .iter()
            .filter(|slot| !should_skip_generic_object(slot))
            .map(|slot| argument_from_slot(text, UmrLiteRole::Target, slot)),
    );
    arguments.extend(
        frame
            .recipient_candidates
            .iter()
            .map(|slot| argument_from_slot(text, UmrLiteRole::Recipient, slot)),
    );
    for attachment in &frame.pp_attachments {
        if let Some(argument) = argument_from_attachment(text, *attachment) {
            arguments.push(argument);
        }
    }
    arguments.extend(outcome_arguments(text, frame.clause_range));
    let scopes = scope_ops_for_frame(text, frame.clause_range, frame.verb_range);
    let confidence = frame
        .subject_candidates
        .first()
        .map(|slot| slot.confidence)
        .unwrap_or(0.55)
        .min(
            frame
                .object_candidates
                .first()
                .map(|slot| slot.confidence)
                .unwrap_or(0.7),
        )
        .max(0.45);
    UmrLiteFrame {
        frame_id,
        sentence_index,
        trigger_range: frame.verb_range,
        lemma: frame.lemma.clone(),
        event_class: frame.event_class.clone(),
        relation_type: frame.relation_type.clone(),
        clause_range: frame.clause_range,
        confidence,
        arguments,
        scopes,
        evidence: frame.evidence.clone(),
    }
}

fn should_skip_generic_object(slot: &FrameSlot) -> bool {
    let generic_len = slot.range.end.saturating_sub(slot.range.start);
    generic_len <= 12 && slot.entity_ref.is_none()
}

fn argument_from_slot(text: &str, role: UmrLiteRole, slot: &FrameSlot) -> UmrLiteArgument {
    UmrLiteArgument {
        role,
        range: slot.range,
        surface: span_text(text, slot.range),
        entity_ref: slot.entity_ref.clone(),
        confidence: slot.confidence,
        source: slot.source.clone(),
    }
}

fn argument_from_attachment(text: &str, range: TextRange) -> Option<UmrLiteArgument> {
    let surface = span_text(text, range);
    let first = surface
        .split_whitespace()
        .next()
        .unwrap_or_default()
        .trim_matches(|ch: char| !ch.is_ascii_alphabetic())
        .to_ascii_lowercase();
    let role = match first.as_str() {
        "in" | "at" | "on" | "near" | "inside" | "outside" | "through" | "across" | "around" => {
            UmrLiteRole::Location
        }
        "from" => UmrLiteRole::Source,
        "to" | "into" | "onto" | "toward" | "towards" => UmrLiteRole::Destination,
        "with" | "by" | "using" | "via" => UmrLiteRole::Instrument,
        "before" | "after" | "during" | "until" | "when" => UmrLiteRole::Time,
        "because" => UmrLiteRole::Cause,
        _ => return None,
    };
    Some(UmrLiteArgument {
        role,
        range,
        surface,
        entity_ref: None,
        confidence: 0.58,
        source: Some(FrameSlotSource::UmrCue),
    })
}

fn outcome_arguments(text: &str, clause_range: TextRange) -> Vec<UmrLiteArgument> {
    let clause = span_text(text, clause_range);
    let lower = clause.to_ascii_lowercase();
    for cue in ["causing ", "leading to ", "resulting in ", "so "] {
        if let Some(offset) = lower.find(cue) {
            let start = clause_range.start + (offset + cue.len()) as u32;
            let end = clause_range.end;
            return vec![UmrLiteArgument {
                role: UmrLiteRole::Outcome,
                range: TextRange { start, end },
                surface: span_text(text, TextRange { start, end }),
                entity_ref: None,
                confidence: 0.52,
                source: Some(FrameSlotSource::UmrCue),
            }];
        }
    }
    Vec::new()
}

fn scope_ops_for_frame(
    text: &str,
    clause_range: TextRange,
    trigger_range: TextRange,
) -> Vec<UmrLiteScope> {
    let clause = span_text(text, clause_range);
    let lower = clause.to_ascii_lowercase();
    let trigger_offset = trigger_range.start.saturating_sub(clause_range.start) as usize;
    let before_trigger = lower.get(..trigger_offset.min(lower.len())).unwrap_or("");
    let mut scopes = Vec::new();
    for cue in ["not", "never", "no longer"] {
        if let Some(range) = cue_range(clause_range, &lower, cue, true, trigger_offset) {
            scopes.push(UmrLiteScope {
                kind: UmrLiteScopeKind::Polarity,
                value: "negative".to_owned(),
                range: Some(range),
                confidence: 0.92,
            });
            break;
        }
    }
    for cue in [
        "might", "could", "should", "would", "will", "must", "can", "may",
    ] {
        if before_trigger
            .split(|ch: char| !ch.is_ascii_alphabetic())
            .any(|token| token == cue)
        {
            scopes.push(UmrLiteScope {
                kind: UmrLiteScopeKind::Modality,
                value: cue.to_owned(),
                range: cue_range(clause_range, &lower, cue, true, trigger_offset),
                confidence: 0.82,
            });
            break;
        }
    }
    for cue in ["if", "unless"] {
        if let Some(range) = cue_range(clause_range, &lower, cue, false, trigger_offset) {
            scopes.push(UmrLiteScope {
                kind: UmrLiteScopeKind::Conditional,
                value: cue.to_owned(),
                range: Some(range),
                confidence: 0.74,
            });
            break;
        }
    }
    scopes
}

fn cue_range(
    clause_range: TextRange,
    lower_clause: &str,
    cue: &str,
    before_only: bool,
    trigger_offset: usize,
) -> Option<TextRange> {
    let search = if before_only {
        lower_clause.get(..trigger_offset.min(lower_clause.len()))?
    } else {
        lower_clause
    };
    let offset = search
        .char_indices()
        .find(|(idx, _)| word_at(search, *idx, cue))
        .map(|(idx, _)| idx)?;
    Some(TextRange {
        start: clause_range.start + offset as u32,
        end: clause_range.start + (offset + cue.len()) as u32,
    })
}

fn word_at(text: &str, offset: usize, word: &str) -> bool {
    let Some(rest) = text.get(offset..) else {
        return false;
    };
    if !rest.starts_with(word) {
        return false;
    }
    let before_ok = offset == 0
        || text[..offset]
            .chars()
            .last()
            .map(|ch| !ch.is_ascii_alphabetic())
            .unwrap_or(true);
    let after = offset + word.len();
    let after_ok = after >= text.len()
        || text[after..]
            .chars()
            .next()
            .map(|ch| !ch.is_ascii_alphabetic())
            .unwrap_or(true);
    before_ok && after_ok
}

fn facts_from_umr_frame(frame: &UmrLiteFrame) -> Vec<FrameFactCandidate> {
    let mut facts = Vec::new();
    let actors = frame
        .arguments
        .iter()
        .filter(|arg| arg.role == UmrLiteRole::Actor)
        .collect::<Vec<_>>();
    let targets = frame
        .arguments
        .iter()
        .filter(|arg| arg.role == UmrLiteRole::Target)
        .collect::<Vec<_>>();
    for actor in &actors {
        for target in &targets {
            facts.push(frame_fact(
                frame,
                "directRelation",
                argument_key(actor),
                frame.relation_type.clone(),
                argument_key(target),
                frame
                    .confidence
                    .min(actor.confidence)
                    .min(target.confidence),
            ));
        }
    }
    for argument in frame.arguments.iter().filter(|arg| {
        matches!(
            arg.role,
            UmrLiteRole::Location
                | UmrLiteRole::Time
                | UmrLiteRole::Instrument
                | UmrLiteRole::Source
                | UmrLiteRole::Destination
                | UmrLiteRole::Outcome
        )
    }) {
        let predicate = format!("role:{:?}", argument.role).to_ascii_lowercase();
        facts.push(frame_fact(
            frame,
            "eventRole",
            frame.frame_id.clone(),
            predicate,
            argument_key(argument),
            frame.confidence.min(argument.confidence),
        ));
    }
    facts
}

fn frame_fact(
    frame: &UmrLiteFrame,
    fact_kind: &str,
    subject: String,
    predicate: String,
    object: String,
    confidence: f32,
) -> FrameFactCandidate {
    let seed = format!(
        "{}:{fact_kind}:{subject}:{predicate}:{object}",
        frame.frame_id
    );
    FrameFactCandidate {
        fact_id: format!("framefact::{:016x}", hash64(seed.as_bytes())),
        frame_id: frame.frame_id.clone(),
        sentence_index: frame.sentence_index,
        fact_kind: fact_kind.to_owned(),
        subject,
        predicate,
        object,
        confidence,
        evidence: frame.evidence.clone(),
    }
}

fn argument_key(argument: &UmrLiteArgument) -> String {
    match &argument.entity_ref {
        Some(phoenix_types::MentionEntityRef::Known(entity_id)) => {
            format!("entity:{}", entity_id.0)
        }
        Some(phoenix_types::MentionEntityRef::Speculative(key)) => format!("candidate:{key}"),
        None => argument.surface.clone(),
    }
}

fn span_text(text: &str, range: TextRange) -> String {
    let start = floor_boundary(text, range.start as usize);
    let end = floor_boundary(text, range.end as usize);
    text.get(start.min(text.len())..end.min(text.len()))
        .unwrap_or_default()
        .trim()
        .to_owned()
}

fn floor_boundary(text: &str, mut index: usize) -> usize {
    index = index.min(text.len());
    while index > 0 && !text.is_char_boundary(index) {
        index -= 1;
    }
    index
}

fn hash64(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}
