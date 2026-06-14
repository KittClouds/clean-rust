use phoenix_types::{Proposition, SourceRange};
use serde::{Deserialize, Serialize};

use super::DocumentSemanticFrame;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticFactualityEnvelope {
    pub factuality: String,
    pub polarity: String,
    pub modality: Option<String>,
    pub speech_act: String,
    pub asserted: bool,
    pub negated: bool,
    pub modal: bool,
    pub hypothetical: bool,
    pub conditional: bool,
    pub quoted: bool,
    pub reported: bool,
    pub believed: bool,
    pub questioned: bool,
    pub commanded: bool,
    pub confidence_millis: u16,
    pub scope_kinds: Vec<String>,
    pub detector_reasons: Vec<String>,
    pub failure_reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticAttributionFrame {
    pub source_entity_id: Option<String>,
    pub quote_start: Option<usize>,
    pub quote_end: Option<usize>,
    pub attribution_kind: String,
    pub confidence_millis: u16,
    pub detector_reasons: Vec<String>,
    pub failure_reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticConditionalFrame {
    pub condition_start: Option<usize>,
    pub condition_end: Option<usize>,
    pub consequent_start: Option<usize>,
    pub consequent_end: Option<usize>,
    pub confidence_millis: u16,
    pub detector_reasons: Vec<String>,
    pub failure_reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticSpeechOrBeliefFrame {
    pub kind: String,
    pub speaker_entity_id: Option<String>,
    pub quoted_start: Option<usize>,
    pub quoted_end: Option<usize>,
    pub embedded_factuality: String,
    pub confidence_millis: u16,
    pub detector_reasons: Vec<String>,
    pub failure_reasons: Vec<String>,
}

pub(super) struct FactualityBundle {
    pub envelope: DocumentSemanticFactualityEnvelope,
    pub attribution_frame: Option<DocumentSemanticAttributionFrame>,
    pub conditional_frame: Option<DocumentSemanticConditionalFrame>,
    pub speech_or_belief_frame: Option<DocumentSemanticSpeechOrBeliefFrame>,
}

pub(super) fn build_factuality_bundle<F>(
    proposition: &Proposition,
    frame: &DocumentSemanticFrame,
    offset: F,
) -> FactualityBundle
where
    F: Fn(u32) -> usize + Copy,
{
    let scope_kinds = proposition
        .scope_ops
        .iter()
        .map(|scope| scope.kind.to_string())
        .collect::<Vec<_>>();
    let negated = proposition
        .scope_ops
        .iter()
        .any(|scope| scope.polarity.as_deref() == Some("negative"));
    let modality = proposition
        .scope_ops
        .iter()
        .find_map(|scope| scope.modality.as_ref().map(ToString::to_string));
    let modal = proposition
        .scope_ops
        .iter()
        .any(|scope| scope.kind == "modality");
    let questioned = proposition
        .scope_ops
        .iter()
        .any(|scope| scope.kind == "question");
    let directive_scope = proposition
        .scope_ops
        .iter()
        .any(|scope| scope.kind == "directive");
    let has_subject_argument = proposition
        .arguments
        .iter()
        .any(|argument| argument.role == "subject" || argument.role == "agent");
    let broad_directive_scope = directive_scope
        && (proposition.predicate.predicate.ends_with("ing")
            || proposition.predicate.predicate.ends_with("ed")
            || proposition.predicate.relation_type == "relates_to"
            || has_subject_argument);
    let commanded = directive_scope && !broad_directive_scope;
    let conditional = proposition.conditional.is_some();
    let quoted = proposition.quote.is_some();
    let reported = proposition.attribution.is_some();
    let believed = frame.family == "cognition";
    let hypothetical = modal
        || proposition
            .scope_ops
            .iter()
            .any(|scope| scope.kind == "hypothetical" || scope.kind == "conditional");
    let factuality = primary_factuality(
        negated,
        modal,
        hypothetical,
        conditional,
        quoted,
        reported,
        believed,
        questioned,
        commanded,
    );
    let mut detector_reasons = Vec::with_capacity(8);
    detector_reasons.push("native_scope_substrate".to_owned());
    push_if(&mut detector_reasons, negated, "negative_polarity_scope");
    push_if(&mut detector_reasons, modal, "modality_scope");
    push_if(
        &mut detector_reasons,
        hypothetical,
        "hypothetical_or_modal_scope",
    );
    push_if(&mut detector_reasons, conditional, "conditional_frame");
    push_if(&mut detector_reasons, quoted, "quote_frame");
    push_if(&mut detector_reasons, reported, "attribution_frame");
    push_if(&mut detector_reasons, believed, "cognition_frame");
    push_if(&mut detector_reasons, questioned, "question_scope");
    push_if(&mut detector_reasons, commanded, "directive_scope");
    push_if(
        &mut detector_reasons,
        broad_directive_scope,
        "broad_directive_scope",
    );

    let attribution_frame = proposition
        .attribution
        .as_ref()
        .map(|frame| attribution_frame(frame, offset));
    let conditional_frame = proposition
        .conditional
        .as_ref()
        .map(|frame| conditional_frame(frame, offset));
    let speech_or_belief_frame = speech_or_belief_frame(proposition, frame, offset);

    let mut failure_reasons = Vec::with_capacity(4);
    if reported
        && attribution_frame
            .as_ref()
            .is_some_and(|frame| frame.source_entity_id.is_none())
    {
        failure_reasons.push("attribution_source_unresolved".to_owned());
    }
    if quoted
        && speech_or_belief_frame
            .as_ref()
            .is_some_and(|frame| frame.speaker_entity_id.is_none())
    {
        failure_reasons.push("quote_speaker_unresolved".to_owned());
    }
    if conditional
        && conditional_frame
            .as_ref()
            .is_some_and(|frame| !frame.failure_reasons.is_empty())
    {
        failure_reasons.push("conditional_span_incomplete".to_owned());
    }
    if broad_directive_scope {
        failure_reasons.push("directive_scope_did_not_match_predicate_shape".to_owned());
    }

    let confidence_millis = envelope_confidence_millis(
        detector_reasons.len(),
        failure_reasons.len(),
        factuality != "asserted",
    );
    let envelope = DocumentSemanticFactualityEnvelope {
        factuality: factuality.to_owned(),
        polarity: if negated { "negative" } else { "positive" }.to_owned(),
        modality,
        speech_act: speech_act(questioned, commanded, quoted, reported).to_owned(),
        asserted: factuality == "asserted",
        negated,
        modal,
        hypothetical,
        conditional,
        quoted,
        reported,
        believed,
        questioned,
        commanded,
        confidence_millis,
        scope_kinds,
        detector_reasons,
        failure_reasons,
    };

    FactualityBundle {
        envelope,
        attribution_frame,
        conditional_frame,
        speech_or_belief_frame,
    }
}

fn attribution_frame<F>(
    frame: &phoenix_types::AttributionFrame,
    offset: F,
) -> DocumentSemanticAttributionFrame
where
    F: Fn(u32) -> usize + Copy,
{
    let mut detector_reasons = vec!["native_attribution_frame".to_owned()];
    let mut failure_reasons = Vec::with_capacity(2);
    if frame.source_entity_id.is_none() {
        failure_reasons.push("missing_source_entity".to_owned());
    }
    if frame.quote_range.is_none() {
        failure_reasons.push("missing_quote_range".to_owned());
    }
    let confidence_millis = frame_confidence_millis(820, failure_reasons.len());
    if failure_reasons.is_empty() {
        detector_reasons.push("source_and_quote_present".to_owned());
    }
    DocumentSemanticAttributionFrame {
        source_entity_id: frame.source_entity_id.as_ref().map(|id| id.0.clone()),
        quote_start: frame.quote_range.map(|range| offset(range.start)),
        quote_end: frame.quote_range.map(|range| offset(range.end)),
        attribution_kind: "reported".to_owned(),
        confidence_millis,
        detector_reasons,
        failure_reasons,
    }
}

fn conditional_frame<F>(
    frame: &phoenix_types::ConditionalFrame,
    offset: F,
) -> DocumentSemanticConditionalFrame
where
    F: Fn(u32) -> usize + Copy,
{
    let mut failure_reasons = Vec::with_capacity(2);
    if frame.condition_range.is_none() {
        failure_reasons.push("missing_condition_span".to_owned());
    }
    if frame.consequent_range.is_none() {
        failure_reasons.push("missing_consequent_span".to_owned());
    }
    DocumentSemanticConditionalFrame {
        condition_start: start(frame.condition_range, offset),
        condition_end: end(frame.condition_range, offset),
        consequent_start: start(frame.consequent_range, offset),
        consequent_end: end(frame.consequent_range, offset),
        confidence_millis: frame_confidence_millis(840, failure_reasons.len()),
        detector_reasons: vec!["native_conditional_frame".to_owned()],
        failure_reasons,
    }
}

fn speech_or_belief_frame<F>(
    proposition: &Proposition,
    frame: &DocumentSemanticFrame,
    offset: F,
) -> Option<DocumentSemanticSpeechOrBeliefFrame>
where
    F: Fn(u32) -> usize + Copy,
{
    let quote = proposition.quote.as_ref();
    let is_speech = quote.is_some() || frame.family == "communication";
    let is_belief = frame.family == "cognition";
    if !(is_speech || is_belief) {
        return None;
    }
    let mut detector_reasons = Vec::with_capacity(3);
    push_if(&mut detector_reasons, is_speech, "speech_or_quote_frame");
    push_if(
        &mut detector_reasons,
        is_belief,
        "belief_or_cognition_frame",
    );
    let mut failure_reasons = Vec::with_capacity(2);
    if quote.is_some_and(|quote| quote.speaker_entity_id.is_none()) {
        failure_reasons.push("missing_speaker_entity".to_owned());
    }
    if is_speech && quote.is_none() {
        failure_reasons.push("speech_without_quote_span".to_owned());
    }
    let confidence_millis = frame_confidence_millis(790, failure_reasons.len());
    Some(DocumentSemanticSpeechOrBeliefFrame {
        kind: if is_belief { "belief" } else { "speech" }.to_owned(),
        speaker_entity_id: quote
            .and_then(|quote| quote.speaker_entity_id.as_ref().map(|id| id.0.clone())),
        quoted_start: quote.map(|quote| offset(quote.quote_range.start)),
        quoted_end: quote.map(|quote| offset(quote.quote_range.end)),
        embedded_factuality: if is_belief || proposition.attribution.is_some() {
            "reported_or_embedded"
        } else {
            "quoted"
        }
        .to_owned(),
        confidence_millis,
        detector_reasons,
        failure_reasons,
    })
}

fn primary_factuality(
    negated: bool,
    modal: bool,
    hypothetical: bool,
    conditional: bool,
    quoted: bool,
    reported: bool,
    believed: bool,
    questioned: bool,
    commanded: bool,
) -> &'static str {
    if commanded {
        "commanded"
    } else if questioned {
        "questioned"
    } else if conditional {
        "conditional"
    } else if negated {
        "negated"
    } else if believed {
        "believed"
    } else if reported {
        "reported"
    } else if quoted {
        "quoted"
    } else if hypothetical {
        "hypothetical"
    } else if modal {
        "modal"
    } else {
        "asserted"
    }
}

fn speech_act(questioned: bool, commanded: bool, quoted: bool, reported: bool) -> &'static str {
    if commanded {
        "command"
    } else if questioned {
        "question"
    } else if quoted || reported {
        "reported_speech"
    } else {
        "assertion"
    }
}

fn envelope_confidence_millis(signals: usize, failures: usize, scoped: bool) -> u16 {
    let mut score = if scoped { 760 } else { 700 };
    score += signals.min(5) as i32 * 24;
    score -= failures.min(3) as i32 * 80;
    score.clamp(160, 960) as u16
}

fn frame_confidence_millis(base: i32, failures: usize) -> u16 {
    (base - failures.min(3) as i32 * 120).clamp(160, 940) as u16
}

fn push_if(reasons: &mut Vec<String>, condition: bool, reason: &str) {
    if condition {
        reasons.push(reason.to_owned());
    }
}

fn start<F>(range: Option<SourceRange>, offset: F) -> Option<usize>
where
    F: Fn(u32) -> usize + Copy,
{
    range.map(|range| offset(range.start))
}

fn end<F>(range: Option<SourceRange>, offset: F) -> Option<usize>
where
    F: Fn(u32) -> usize + Copy,
{
    range.map(|range| offset(range.end))
}
