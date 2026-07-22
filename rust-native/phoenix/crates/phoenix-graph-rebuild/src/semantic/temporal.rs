use hashbrown::{HashMap, HashSet};
use serde::{Deserialize, Serialize};

use super::{DocumentSemanticInput, DocumentSemanticProposition};

mod cues;
use cues::{normalize, temporal_cues};

const RECOVERY_CONFIDENCE_MIN: u16 = 600;
const DOCUMENT_ORDER_CONFIDENCE: u16 = 580;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticSituationInstance {
    pub id: String,
    pub proposition_id: String,
    pub note_id: String,
    pub sentence_index: usize,
    pub start: usize,
    pub end: usize,
    pub predicate: String,
    pub frame: String,
    pub situation_kind: String,
    pub participant_entity_ids: Vec<String>,
    pub participant_surfaces: Vec<String>,
    pub factuality: String,
    pub world_state_eligible: bool,
    pub recurrence_of_situation_id: Option<String>,
    pub recurrence_index: usize,
    pub confidence_millis: u16,
    pub detector_reasons: Vec<String>,
    pub failure_reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticStateInterval {
    pub id: String,
    pub note_id: String,
    pub state_key: String,
    pub subject_key: String,
    pub predicate: String,
    pub value: Option<String>,
    pub polarity: String,
    pub status: String,
    pub start_situation_id: String,
    pub end_situation_id: Option<String>,
    pub mention_situation_ids: Vec<String>,
    pub start: usize,
    pub end: Option<usize>,
    pub persists: bool,
    pub termination_cue: Option<String>,
    pub confidence_millis: u16,
    pub detector_reasons: Vec<String>,
    pub failure_reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticEventOrdering {
    pub id: String,
    pub note_id: String,
    pub source_situation_id: String,
    pub target_situation_id: String,
    pub relation: String,
    pub cue: Option<String>,
    pub source: String,
    pub confidence_millis: u16,
    pub detector_reasons: Vec<String>,
    pub failure_reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticTemporalConflict {
    pub id: String,
    pub note_id: String,
    pub kind: String,
    pub state_key: Option<String>,
    pub situation_ids: Vec<String>,
    pub state_interval_ids: Vec<String>,
    pub severity: String,
    pub confidence_millis: u16,
    pub detector_reasons: Vec<String>,
    pub failure_reasons: Vec<String>,
}

#[derive(Clone, Debug, Default)]
pub(super) struct TemporalContinuityBundle {
    pub situations: Vec<DocumentSemanticSituationInstance>,
    pub state_intervals: Vec<DocumentSemanticStateInterval>,
    pub event_orderings: Vec<DocumentSemanticEventOrdering>,
    pub temporal_conflicts: Vec<DocumentSemanticTemporalConflict>,
}

pub(super) fn build_temporal_continuity(
    document: &DocumentSemanticInput,
    propositions: &[DocumentSemanticProposition],
) -> TemporalContinuityBundle {
    let mut situations = build_situations(document, propositions);
    situations.sort_by_key(|row| (row.start, row.end, row.sentence_index));
    let proposition_by_id = propositions
        .iter()
        .map(|row| (row.id.as_str(), row))
        .collect::<HashMap<_, _>>();
    let (state_intervals, mut temporal_conflicts) =
        build_state_intervals(document, &situations, &proposition_by_id);
    let event_orderings = build_event_orderings(document, &situations, &proposition_by_id);
    temporal_conflicts.extend(ordering_conflicts(document, &event_orderings));
    TemporalContinuityBundle {
        situations,
        state_intervals,
        event_orderings,
        temporal_conflicts,
    }
}

fn build_situations(
    document: &DocumentSemanticInput,
    propositions: &[DocumentSemanticProposition],
) -> Vec<DocumentSemanticSituationInstance> {
    let mut out = Vec::with_capacity(propositions.len());
    let mut recurrence = HashMap::<String, (String, usize)>::with_capacity(propositions.len() / 3);
    for proposition in propositions {
        if proposition.predicate_quality == "noise" || proposition.predicate.is_empty() {
            continue;
        }
        let (participant_entity_ids, participant_surfaces) = participants(proposition);
        let situation_kind = situation_kind(proposition);
        let cues = temporal_cues(&proposition.preview);
        if proposition.review_state == "ledger_only"
            && situation_kind != "state"
            && !cues.has_temporal_evidence()
        {
            continue;
        }
        let world_state_eligible = world_state_eligible(proposition);
        let signature = recurrence_signature(
            proposition,
            &participant_entity_ids,
            &participant_surfaces,
            situation_kind,
        );
        let recurrence_trackable = world_state_eligible
            && proposition.confidence_millis >= 650
            && has_reliable_participant(&participant_entity_ids, &participant_surfaces);
        let previous_recurrence = recurrence_trackable
            .then(|| recurrence.get(&signature).cloned())
            .flatten();
        let recurrence_row = previous_recurrence
            .clone()
            .filter(|_| !participant_entity_ids.is_empty() || cues.recurrence);
        let recurrence_index = recurrence_row.as_ref().map_or(0, |(_, count)| *count);
        let id = format!("{}:situation:{}", document.note_id, proposition.id);
        if recurrence_trackable {
            let next_index = previous_recurrence.map_or(1, |(_, count)| count + 1);
            recurrence.insert(signature, (id.clone(), next_index));
        }
        let mut detector_reasons = vec!["native_proposition_situation".to_owned()];
        detector_reasons.push(format!("frame:{}", proposition.frame.frame));
        detector_reasons.push(format!("kind:{situation_kind}"));
        if recurrence_row.is_some() {
            detector_reasons.push("repeated_situation_signature".to_owned());
        }
        let mut failure_reasons = Vec::with_capacity(3);
        if participant_entity_ids.is_empty() && participant_surfaces.is_empty() {
            failure_reasons.push("participants_unresolved".to_owned());
        }
        if !world_state_eligible {
            failure_reasons.push("factuality_blocks_world_state_commit".to_owned());
        }
        if proposition.confidence_millis < RECOVERY_CONFIDENCE_MIN {
            failure_reasons.push("low_proposition_confidence".to_owned());
        }
        out.push(DocumentSemanticSituationInstance {
            id,
            proposition_id: proposition.id.clone(),
            note_id: document.note_id.clone(),
            sentence_index: proposition.sentence_index,
            start: proposition.start,
            end: proposition.end,
            predicate: proposition.predicate.clone(),
            frame: proposition.frame.frame.clone(),
            situation_kind: situation_kind.to_owned(),
            participant_entity_ids,
            participant_surfaces,
            factuality: proposition.factuality.factuality.clone(),
            world_state_eligible,
            recurrence_of_situation_id: recurrence_row.map(|(id, _)| id),
            recurrence_index,
            confidence_millis: situation_confidence(proposition, failure_reasons.len()),
            detector_reasons,
            failure_reasons,
        });
    }
    out
}

fn build_state_intervals(
    document: &DocumentSemanticInput,
    situations: &[DocumentSemanticSituationInstance],
    propositions: &HashMap<&str, &DocumentSemanticProposition>,
) -> (
    Vec<DocumentSemanticStateInterval>,
    Vec<DocumentSemanticTemporalConflict>,
) {
    let mut intervals = Vec::<DocumentSemanticStateInterval>::new();
    let mut open_by_key = HashMap::<String, usize>::new();
    let mut last_subject_by_signature = HashMap::<String, String>::new();
    let mut conflicts = Vec::new();
    for situation in situations
        .iter()
        .filter(|row| row.situation_kind == "state" && row.world_state_eligible)
    {
        let Some(proposition) = propositions.get(situation.proposition_id.as_str()).copied() else {
            continue;
        };
        let cues = temporal_cues(&proposition.preview);
        let value = principal_value(proposition);
        let signature = format!(
            "{}:{}:{}",
            proposition.frame.frame,
            normalize(&proposition.predicate),
            value.as_deref().map(normalize).unwrap_or_default()
        );
        let detected_subject = principal_subject_key(proposition);
        let carried_subject = unreliable_state_subject(&detected_subject)
            .then(|| last_subject_by_signature.get(&signature).cloned())
            .flatten();
        let subject_key = carried_subject.clone().unwrap_or(detected_subject);
        if !unreliable_state_subject(&subject_key) {
            last_subject_by_signature.insert(signature, subject_key.clone());
        }
        let state_key = format!(
            "{}:{}:{}",
            subject_key,
            proposition.frame.frame,
            normalize(&proposition.predicate)
        );
        let polarity = proposition.factuality.polarity.clone();
        let existing = open_by_key.get(&state_key).copied();

        if let Some(index) = existing {
            let previous_polarity = intervals[index].polarity.clone();
            if cues.persistence && previous_polarity == polarity {
                let row = &mut intervals[index];
                row.mention_situation_ids.push(situation.id.clone());
                row.end = Some(situation.end);
                row.persists = true;
                row.detector_reasons
                    .push("persistence_cue_extended_interval".to_owned());
                row.confidence_millis = row.confidence_millis.max(situation.confidence_millis);
                continue;
            }
            if cues.termination || cues.transition || previous_polarity != polarity {
                let row = &mut intervals[index];
                row.end_situation_id = Some(situation.id.clone());
                row.end = Some(situation.start);
                row.status = if cues.termination {
                    "terminated"
                } else {
                    "superseded"
                }
                .to_owned();
                row.termination_cue = cues.termination_cue.clone().or(cues.transition_cue.clone());
                if previous_polarity != polarity && !cues.termination && !cues.transition {
                    conflicts.push(state_conflict(
                        document,
                        &state_key,
                        &intervals[index],
                        situation,
                    ));
                }
                open_by_key.remove(&state_key);
            } else {
                let row = &mut intervals[index];
                row.mention_situation_ids.push(situation.id.clone());
                row.end = Some(situation.end);
                row.detector_reasons
                    .push("repeated_state_mention".to_owned());
                continue;
            }
        }

        let interval_id = format!("{}:state-interval:{}", document.note_id, intervals.len());
        let mut detector_reasons = vec!["state_frame_interval".to_owned()];
        detector_reasons.extend(cues.reasons());
        if carried_subject.is_some() {
            detector_reasons.push("state_subject_carried_from_prior_interval".to_owned());
        }
        let mut failure_reasons = Vec::with_capacity(2);
        if subject_key == "unresolved-subject" {
            failure_reasons.push("state_subject_unresolved".to_owned());
        }
        if !situation.world_state_eligible {
            failure_reasons.push("state_not_world_commit_eligible".to_owned());
        }
        intervals.push(DocumentSemanticStateInterval {
            id: interval_id,
            note_id: document.note_id.clone(),
            state_key: state_key.clone(),
            subject_key,
            predicate: proposition.predicate.clone(),
            value,
            polarity,
            status: if cues.termination {
                "termination_observed"
            } else {
                "open"
            }
            .to_owned(),
            start_situation_id: situation.id.clone(),
            end_situation_id: None,
            mention_situation_ids: vec![situation.id.clone()],
            start: situation.start,
            end: None,
            persists: cues.persistence,
            termination_cue: cues.termination_cue,
            confidence_millis: situation
                .confidence_millis
                .saturating_sub(u16::try_from(failure_reasons.len() * 70).unwrap_or(u16::MAX)),
            detector_reasons,
            failure_reasons,
        });
        open_by_key.insert(state_key, intervals.len() - 1);
    }
    (intervals, conflicts)
}

fn build_event_orderings(
    document: &DocumentSemanticInput,
    situations: &[DocumentSemanticSituationInstance],
    propositions: &HashMap<&str, &DocumentSemanticProposition>,
) -> Vec<DocumentSemanticEventOrdering> {
    let mut out = Vec::with_capacity(situations.len());
    let mut seen = HashSet::<(String, String, String)>::with_capacity(situations.len());
    let mut explicit_sentence_scopes =
        HashSet::<(usize, String)>::with_capacity(situations.len() / 4);
    for window in situations.windows(2) {
        let previous = &window[0];
        let current = &window[1];
        let Some(proposition) = propositions.get(current.proposition_id.as_str()).copied() else {
            continue;
        };
        let cues = temporal_cues(&proposition.preview);
        let shared = shared_participant(previous, current);
        let sentence_gap = current
            .sentence_index
            .saturating_sub(previous.sentence_index);
        let ordering = if let Some(cue) = cues.overlap_cue {
            Some((previous, current, "overlaps", cue, "explicit_cue", 820))
        } else if let Some(cue) = cues.before_cue {
            Some((current, previous, "before", cue, "explicit_cue", 720))
        } else if let Some(cue) = cues.after_cue.or(cues.sequence_cue) {
            Some((previous, current, "before", cue, "explicit_cue", 840))
        } else if shared
            && sentence_gap <= 2
            && previous.world_state_eligible
            && current.world_state_eligible
        {
            Some((
                previous,
                current,
                "before",
                "document order",
                "document_order",
                DOCUMENT_ORDER_CONFIDENCE,
            ))
        } else {
            None
        };
        let Some((source, target, relation, cue, source_kind, confidence)) = ordering else {
            continue;
        };
        if source_kind == "explicit_cue"
            && !explicit_sentence_scopes.insert((current.sentence_index, relation.to_owned()))
        {
            continue;
        }
        let key = (source.id.clone(), target.id.clone(), relation.to_owned());
        if !seen.insert(key) {
            continue;
        }
        let mut failure_reasons = Vec::with_capacity(2);
        if source_kind == "document_order" {
            failure_reasons.push("implicit_narrative_order_requires_review".to_owned());
        }
        if cue == "before" {
            failure_reasons.push("before_scope_may_span_multiple_clauses".to_owned());
        }
        let scoped = !source.world_state_eligible || !target.world_state_eligible;
        if scoped {
            failure_reasons.push("ordering_contains_scoped_situation".to_owned());
        }
        out.push(DocumentSemanticEventOrdering {
            id: format!("{}:event-ordering:{}", document.note_id, out.len()),
            note_id: document.note_id.clone(),
            source_situation_id: source.id.clone(),
            target_situation_id: target.id.clone(),
            relation: relation.to_owned(),
            cue: (cue != "document order").then(|| cue.to_owned()),
            source: source_kind.to_owned(),
            confidence_millis: confidence.saturating_sub((scoped as u16) * 120),
            detector_reasons: vec![
                format!("{source_kind}:{relation}"),
                format!("sentence_gap:{sentence_gap}"),
            ],
            failure_reasons,
        });
    }
    append_recurrence_orderings(document, situations, &mut out, &mut seen);
    out
}

fn append_recurrence_orderings(
    document: &DocumentSemanticInput,
    situations: &[DocumentSemanticSituationInstance],
    out: &mut Vec<DocumentSemanticEventOrdering>,
    seen: &mut HashSet<(String, String, String)>,
) {
    for situation in situations {
        let Some(previous_id) = situation.recurrence_of_situation_id.as_ref() else {
            continue;
        };
        let key = (
            previous_id.clone(),
            situation.id.clone(),
            "recurs_after".to_owned(),
        );
        if !seen.insert(key) {
            continue;
        }
        out.push(DocumentSemanticEventOrdering {
            id: format!("{}:event-ordering:{}", document.note_id, out.len()),
            note_id: document.note_id.clone(),
            source_situation_id: previous_id.clone(),
            target_situation_id: situation.id.clone(),
            relation: "recurs_after".to_owned(),
            cue: None,
            source: "situation_recurrence".to_owned(),
            confidence_millis: 700,
            detector_reasons: vec!["repeated_situation_signature".to_owned()],
            failure_reasons: Vec::new(),
        });
    }
}

fn ordering_conflicts(
    document: &DocumentSemanticInput,
    orderings: &[DocumentSemanticEventOrdering],
) -> Vec<DocumentSemanticTemporalConflict> {
    let pairs = orderings
        .iter()
        .filter(|row| row.relation == "before")
        .map(|row| {
            (
                (
                    row.source_situation_id.as_str(),
                    row.target_situation_id.as_str(),
                ),
                row,
            )
        })
        .collect::<HashMap<_, _>>();
    let mut out = Vec::new();
    for ordering in orderings.iter().filter(|row| row.relation == "before") {
        let Some(reverse) = pairs.get(&(
            ordering.target_situation_id.as_str(),
            ordering.source_situation_id.as_str(),
        )) else {
            continue;
        };
        if ordering.id >= reverse.id {
            continue;
        }
        out.push(DocumentSemanticTemporalConflict {
            id: format!("{}:temporal-conflict:{}", document.note_id, out.len()),
            note_id: document.note_id.clone(),
            kind: "ordering_cycle".to_owned(),
            state_key: None,
            situation_ids: vec![
                ordering.source_situation_id.clone(),
                ordering.target_situation_id.clone(),
            ],
            state_interval_ids: Vec::new(),
            severity: "high".to_owned(),
            confidence_millis: ordering.confidence_millis.min(reverse.confidence_millis),
            detector_reasons: vec!["opposing_before_edges".to_owned()],
            failure_reasons: vec!["temporal_order_cannot_be_committed".to_owned()],
        });
    }
    out
}

fn state_conflict(
    document: &DocumentSemanticInput,
    state_key: &str,
    previous: &DocumentSemanticStateInterval,
    current: &DocumentSemanticSituationInstance,
) -> DocumentSemanticTemporalConflict {
    DocumentSemanticTemporalConflict {
        id: format!("{}:temporal-conflict:{}", document.note_id, current.id),
        note_id: document.note_id.clone(),
        kind: "unresolved_state_transition".to_owned(),
        state_key: Some(state_key.to_owned()),
        situation_ids: vec![previous.start_situation_id.clone(), current.id.clone()],
        state_interval_ids: vec![previous.id.clone()],
        severity: "medium".to_owned(),
        confidence_millis: previous.confidence_millis.min(current.confidence_millis),
        detector_reasons: vec!["opposing_state_polarity_without_transition_cue".to_owned()],
        failure_reasons: vec!["state_transition_requires_review".to_owned()],
    }
}

fn participants(proposition: &DocumentSemanticProposition) -> (Vec<String>, Vec<String>) {
    let mut entity_ids = Vec::new();
    let mut surfaces = Vec::new();
    let mut seen_entities = HashSet::new();
    let mut seen_surfaces = HashSet::new();
    for argument in &proposition.arguments {
        push_unique(
            argument.entity_id.as_ref(),
            &mut entity_ids,
            &mut seen_entities,
        );
        push_surface(&argument.surface, &mut surfaces, &mut seen_surfaces);
    }
    for argument in proposition
        .document_argument_recoveries
        .iter()
        .filter(|row| row.confidence_millis >= RECOVERY_CONFIDENCE_MIN)
    {
        push_unique(
            argument.entity_id.as_ref(),
            &mut entity_ids,
            &mut seen_entities,
        );
        push_surface(&argument.surface, &mut surfaces, &mut seen_surfaces);
    }
    (entity_ids, surfaces)
}

fn push_unique<'a>(value: Option<&'a String>, out: &mut Vec<String>, seen: &mut HashSet<&'a str>) {
    if let Some(value) = value.filter(|value| !value.is_empty()) {
        if seen.insert(value.as_str()) {
            out.push(value.clone());
        }
    }
}

fn push_surface<'a>(value: &'a str, out: &mut Vec<String>, seen: &mut HashSet<&'a str>) {
    if !value.is_empty() && seen.insert(value) {
        out.push(value.to_owned());
    }
}

fn situation_kind(proposition: &DocumentSemanticProposition) -> &'static str {
    if matches!(
        proposition.frame.family.as_str(),
        "state" | "identity" | "possession" | "attribute"
    ) || proposition.predicate_quality == "copula_state"
        || proposition.relation_type.contains("state")
        || proposition.relation_type.contains("identity")
    {
        "state"
    } else {
        "event"
    }
}

fn world_state_eligible(proposition: &DocumentSemanticProposition) -> bool {
    proposition.review_state == "proposed"
        && proposition.confidence_millis >= RECOVERY_CONFIDENCE_MIN
        && !proposition.factuality.modal
        && !proposition.factuality.hypothetical
        && !proposition.factuality.conditional
        && !proposition.factuality.quoted
        && !proposition.factuality.reported
        && !proposition.factuality.believed
        && !proposition.factuality.questioned
        && !proposition.factuality.commanded
}

fn situation_confidence(proposition: &DocumentSemanticProposition, failures: usize) -> u16 {
    let base = proposition
        .confidence_millis
        .saturating_add(proposition.frame.confidence_millis)
        / 2;
    base.saturating_sub(u16::try_from(failures * 55).unwrap_or(u16::MAX))
}

fn recurrence_signature(
    proposition: &DocumentSemanticProposition,
    entity_ids: &[String],
    surfaces: &[String],
    kind: &str,
) -> String {
    let participant = entity_ids
        .first()
        .or_else(|| surfaces.first())
        .map_or("unresolved", String::as_str);
    format!(
        "{}:{}:{}:{}",
        kind,
        normalize(&proposition.frame.frame),
        normalize(&proposition.predicate),
        normalize(participant)
    )
}

fn principal_subject_key(proposition: &DocumentSemanticProposition) -> String {
    proposition
        .arguments
        .iter()
        .find(|row| is_subject_role(&row.semantic_role))
        .and_then(|row| {
            row.entity_id
                .as_ref()
                .or_else(|| (!row.surface.is_empty()).then_some(&row.surface))
        })
        .or_else(|| {
            proposition
                .document_argument_recoveries
                .iter()
                .filter(|row| row.confidence_millis >= RECOVERY_CONFIDENCE_MIN)
                .find(|row| is_subject_role(&row.semantic_role))
                .and_then(|row| {
                    row.entity_id
                        .as_ref()
                        .or_else(|| (!row.surface.is_empty()).then_some(&row.surface))
                })
        })
        .map_or_else(|| "unresolved-subject".to_owned(), |value| normalize(value))
}

fn principal_value(proposition: &DocumentSemanticProposition) -> Option<String> {
    proposition
        .arguments
        .iter()
        .find(|row| !is_subject_role(&row.semantic_role) && !row.surface.is_empty())
        .map(|row| row.surface.clone())
        .or_else(|| {
            proposition
                .document_argument_recoveries
                .iter()
                .filter(|row| row.confidence_millis >= RECOVERY_CONFIDENCE_MIN)
                .find(|row| !is_subject_role(&row.semantic_role) && !row.surface.is_empty())
                .map(|row| row.surface.clone())
        })
}

fn is_subject_role(role: &str) -> bool {
    matches!(
        role,
        "actor" | "agent" | "bearer" | "experiencer" | "subject" | "topic"
    )
}

fn unreliable_state_subject(value: &str) -> bool {
    value == "unresolved-subject" || matches!(value, "not" | "never" | "no" | "none" | "neither")
}

fn shared_participant(
    left: &DocumentSemanticSituationInstance,
    right: &DocumentSemanticSituationInstance,
) -> bool {
    left.participant_entity_ids
        .iter()
        .any(|id| right.participant_entity_ids.contains(id))
        || left.participant_surfaces.iter().any(|surface| {
            right
                .participant_surfaces
                .iter()
                .any(|candidate| surface.trim().eq_ignore_ascii_case(candidate.trim()))
        })
}

fn has_reliable_participant(entity_ids: &[String], surfaces: &[String]) -> bool {
    !entity_ids.is_empty()
        || surfaces.iter().any(|surface| {
            let normalized = normalize(surface);
            normalized.len() >= 3
                && !matches!(
                    normalized.as_str(),
                    "he" | "she" | "it" | "they" | "him" | "her" | "them" | "this" | "that"
                )
        })
}
