use hashbrown::HashMap;
use serde::{Deserialize, Serialize};

use super::{DocumentSemanticArgument, DocumentSemanticInput, DocumentSemanticProposition};

const RECENT_WINDOW: usize = 4;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticRecoveredArgument {
    pub kind: String,
    pub role: String,
    pub syntactic_role: String,
    pub semantic_role: String,
    pub surface: String,
    pub entity_id: Option<String>,
    pub start: Option<usize>,
    pub end: Option<usize>,
    pub source_proposition_id: Option<String>,
    pub source_sentence_index: Option<usize>,
    pub confidence_millis: u16,
    pub detector_reasons: Vec<String>,
    pub failure_reasons: Vec<String>,
}

#[derive(Clone)]
struct ContextMention {
    syntactic_role: String,
    semantic_role: String,
    surface: String,
    entity_id: Option<String>,
    start: Option<usize>,
    end: Option<usize>,
    proposition_id: String,
    sentence_index: usize,
}

pub(super) fn recover_document_arguments(
    _document: &DocumentSemanticInput,
    rows: &mut [DocumentSemanticProposition],
) {
    let mut recent_mentions: Vec<ContextMention> = Vec::with_capacity(RECENT_WINDOW * 4);
    let mut surface_index: HashMap<String, ContextMention> = HashMap::new();
    let mut event_index: HashMap<String, Vec<ContextMention>> = HashMap::new();
    let mut last_speaker: Option<ContextMention> = None;

    for index in 0..rows.len() {
        let recoveries = recover_for_row(
            &rows[index],
            &recent_mentions,
            &surface_index,
            &event_index,
            last_speaker.as_ref(),
        );
        rows[index].document_argument_recoveries.extend(recoveries);
        update_context(
            &rows[index],
            &mut recent_mentions,
            &mut surface_index,
            &mut event_index,
            &mut last_speaker,
        );
    }
}

fn recover_for_row(
    row: &DocumentSemanticProposition,
    recent_mentions: &[ContextMention],
    surface_index: &HashMap<String, ContextMention>,
    event_index: &HashMap<String, Vec<ContextMention>>,
    last_speaker: Option<&ContextMention>,
) -> Vec<DocumentSemanticRecoveredArgument> {
    let mut recoveries = Vec::with_capacity(3);
    recover_alias_or_coreference(row, recent_mentions, surface_index, &mut recoveries);
    recover_omitted_subject(row, recent_mentions, &mut recoveries);
    recover_quote_speaker(row, last_speaker, recent_mentions, &mut recoveries);
    recover_window_roles(row, recent_mentions, &mut recoveries);
    recover_repeated_event(row, event_index, &mut recoveries);
    recoveries
}

fn recover_alias_or_coreference(
    row: &DocumentSemanticProposition,
    recent_mentions: &[ContextMention],
    surface_index: &HashMap<String, ContextMention>,
    recoveries: &mut Vec<DocumentSemanticRecoveredArgument>,
) {
    for argument in &row.arguments {
        if argument.surface.is_empty() {
            continue;
        }
        let normalized = normalize_surface(&argument.surface);
        if argument.entity_id.is_some() && !is_pronoun(&normalized) {
            continue;
        }
        let (kind, mention) = if is_pronoun(&normalized) {
            (
                "local_coreference",
                recent_coreferent(
                    recent_mentions,
                    argument.entity_id.as_deref(),
                    row.sentence_index,
                ),
            )
        } else {
            ("alias_continuity", surface_index.get(&normalized).cloned())
        };
        if let Some(mention) = mention {
            push_recovery(
                recoveries,
                recovered_from(
                    kind,
                    argument.semantic_role.as_str(),
                    argument.syntactic_role.as_str(),
                    &mention,
                    row.sentence_index,
                    720,
                    vec!["document_window_entity_continuity".to_owned()],
                ),
            );
        }
    }
}

fn recover_omitted_subject(
    row: &DocumentSemanticProposition,
    recent_mentions: &[ContextMention],
    recoveries: &mut Vec<DocumentSemanticRecoveredArgument>,
) {
    if has_subject_like_argument(row) || !is_recoverable_predicate(row) {
        return;
    }
    if let Some(mention) = recent_subject_like(recent_mentions, row.sentence_index) {
        let mut recovery = recovered_from(
            "omitted_subject",
            "actor",
            "subject",
            &mention,
            row.sentence_index,
            690,
            vec![
                "missing_subject_argument".to_owned(),
                "document_window_actor_carryover".to_owned(),
            ],
        );
        if row.sentence_index.saturating_sub(mention.sentence_index) > 1 {
            recovery
                .failure_reasons
                .push("actor_distance_gt_1".to_owned());
        }
        push_recovery(recoveries, recovery);
    }
}

fn recover_quote_speaker(
    row: &DocumentSemanticProposition,
    last_speaker: Option<&ContextMention>,
    recent_mentions: &[ContextMention],
    recoveries: &mut Vec<DocumentSemanticRecoveredArgument>,
) {
    let needs_speaker = row
        .quote
        .as_ref()
        .is_some_and(|quote| quote.speaker_entity_id.is_none())
        || row
            .speech_or_belief_frame
            .as_ref()
            .is_some_and(|frame| frame.speaker_entity_id.is_none());
    if !needs_speaker {
        return;
    }
    let mention = current_subject_like(row).or_else(|| {
        last_speaker
            .cloned()
            .or_else(|| recent_subject_like(recent_mentions, row.sentence_index))
    });
    if let Some(mention) = mention {
        let mut recovery = recovered_from(
            "quote_speaker_carryover",
            "speaker",
            "speaker",
            &mention,
            row.sentence_index,
            760,
            vec!["previous_speech_or_actor_context".to_owned()],
        );
        if row.sentence_index.saturating_sub(mention.sentence_index) > 3 {
            recovery
                .failure_reasons
                .push("speaker_distance_gt_3".to_owned());
        }
        push_recovery(recoveries, recovery);
    }
}

fn recover_window_roles(
    row: &DocumentSemanticProposition,
    recent_mentions: &[ContextMention],
    recoveries: &mut Vec<DocumentSemanticRecoveredArgument>,
) {
    for role in row.frame.missing_roles.iter().map(String::as_str) {
        if matches!(role, "actor" | "speaker" | "agent" | "subject") || has_role(row, role) {
            continue;
        }
        if let Some(mention) = recent_mentions.iter().rev().find(|mention| {
            mention.semantic_role == role
                && row.sentence_index.saturating_sub(mention.sentence_index) <= 2
        }) {
            push_recovery(
                recoveries,
                recovered_from(
                    "window_argument_completion",
                    role,
                    mention.syntactic_role.as_str(),
                    mention,
                    row.sentence_index,
                    640,
                    vec!["frame_missing_role_completed_from_window".to_owned()],
                ),
            );
        }
    }
}

fn recover_repeated_event(
    row: &DocumentSemanticProposition,
    event_index: &HashMap<String, Vec<ContextMention>>,
    recoveries: &mut Vec<DocumentSemanticRecoveredArgument>,
) {
    if !row.preview.to_ascii_lowercase().contains("again") {
        return;
    }
    let Some(mentions) = event_index.get(&event_key(row)) else {
        return;
    };
    for mention in mentions.iter().rev().take(2) {
        if is_subject_like(&mention.semantic_role) || has_role(row, &mention.semantic_role) {
            continue;
        }
        let mut recovery = recovered_from(
            "repeated_event_entity_link",
            mention.semantic_role.as_str(),
            mention.syntactic_role.as_str(),
            mention,
            row.sentence_index,
            620,
            vec!["again_marker_reuses_prior_event_arguments".to_owned()],
        );
        recovery
            .failure_reasons
            .push("requires_review_for_event_identity".to_owned());
        push_recovery(recoveries, recovery);
    }
}

fn update_context(
    row: &DocumentSemanticProposition,
    recent_mentions: &mut Vec<ContextMention>,
    surface_index: &mut HashMap<String, ContextMention>,
    event_index: &mut HashMap<String, Vec<ContextMention>>,
    last_speaker: &mut Option<ContextMention>,
) {
    let mut row_mentions =
        Vec::with_capacity(row.arguments.len() + row.document_argument_recoveries.len());
    row_mentions.extend(
        row.arguments
            .iter()
            .filter_map(|argument| mention_from_argument(row, argument)),
    );
    row_mentions.extend(
        row.document_argument_recoveries
            .iter()
            .filter_map(|argument| mention_from_recovery(row, argument)),
    );

    for mention in row_mentions {
        let normalized = normalize_surface(&mention.surface);
        if !normalized.is_empty() {
            surface_index.insert(normalized, mention.clone());
        }
        if mention.semantic_role == "speaker"
            || (row.frame.family == "communication" && is_subject_like(&mention.semantic_role))
            || (row.quote.is_some() && is_subject_like(&mention.semantic_role))
        {
            *last_speaker = Some(mention.clone());
        }
        recent_mentions.push(mention.clone());
        event_index.entry(event_key(row)).or_default().push(mention);
    }
    let retain_from = row.sentence_index.saturating_sub(RECENT_WINDOW);
    recent_mentions.retain(|mention| mention.sentence_index >= retain_from);
}

fn current_subject_like(row: &DocumentSemanticProposition) -> Option<ContextMention> {
    if row.frame.family != "communication" && row.quote.is_none() {
        return None;
    }
    row.arguments
        .iter()
        .find(|argument| {
            is_subject_like(&argument.semantic_role) || is_subject_like(&argument.role)
        })
        .and_then(|argument| mention_from_argument(row, argument))
}

fn mention_from_argument(
    row: &DocumentSemanticProposition,
    argument: &DocumentSemanticArgument,
) -> Option<ContextMention> {
    if argument.surface.is_empty() {
        return None;
    }
    Some(ContextMention {
        syntactic_role: argument.syntactic_role.clone(),
        semantic_role: argument.semantic_role.clone(),
        surface: argument.surface.clone(),
        entity_id: argument.entity_id.clone(),
        start: argument.start,
        end: argument.end,
        proposition_id: row.id.clone(),
        sentence_index: row.sentence_index,
    })
}

fn mention_from_recovery(
    row: &DocumentSemanticProposition,
    argument: &DocumentSemanticRecoveredArgument,
) -> Option<ContextMention> {
    if argument.surface.is_empty() {
        return None;
    }
    Some(ContextMention {
        syntactic_role: argument.syntactic_role.clone(),
        semantic_role: argument.semantic_role.clone(),
        surface: argument.surface.clone(),
        entity_id: argument.entity_id.clone(),
        start: argument.start,
        end: argument.end,
        proposition_id: row.id.clone(),
        sentence_index: row.sentence_index,
    })
}

fn recovered_from(
    kind: &str,
    role: &str,
    syntactic_role: &str,
    mention: &ContextMention,
    sentence_index: usize,
    confidence_millis: u16,
    detector_reasons: Vec<String>,
) -> DocumentSemanticRecoveredArgument {
    let distance = sentence_index.saturating_sub(mention.sentence_index);
    let mut failure_reasons = Vec::new();
    if mention.entity_id.is_none() {
        failure_reasons.push("source_entity_unresolved".to_owned());
    }
    DocumentSemanticRecoveredArgument {
        kind: kind.to_owned(),
        role: role.to_owned(),
        syntactic_role: syntactic_role.to_owned(),
        semantic_role: role.to_owned(),
        surface: mention.surface.clone(),
        entity_id: mention.entity_id.clone(),
        start: mention.start,
        end: mention.end,
        source_proposition_id: Some(mention.proposition_id.clone()),
        source_sentence_index: Some(mention.sentence_index),
        confidence_millis: confidence_millis
            .saturating_sub(distance.min(4) as u16 * 30)
            .saturating_sub(if mention.entity_id.is_some() { 0 } else { 80 }),
        detector_reasons,
        failure_reasons,
    }
}

fn push_recovery(
    recoveries: &mut Vec<DocumentSemanticRecoveredArgument>,
    recovery: DocumentSemanticRecoveredArgument,
) {
    if recoveries.iter().any(|row| {
        row.kind == recovery.kind
            && row.semantic_role == recovery.semantic_role
            && row.entity_id == recovery.entity_id
            && row.surface == recovery.surface
    }) {
        return;
    }
    recoveries.push(recovery);
}

fn recent_coreferent(
    mentions: &[ContextMention],
    entity_id: Option<&str>,
    sentence_index: usize,
) -> Option<ContextMention> {
    mentions
        .iter()
        .rev()
        .find(|mention| {
            entity_id.map_or(true, |id| mention.entity_id.as_deref() == Some(id))
                && sentence_index.saturating_sub(mention.sentence_index) <= RECENT_WINDOW
        })
        .cloned()
}

fn recent_subject_like(
    mentions: &[ContextMention],
    sentence_index: usize,
) -> Option<ContextMention> {
    mentions
        .iter()
        .rev()
        .find(|mention| {
            is_subject_like(&mention.semantic_role)
                && sentence_index.saturating_sub(mention.sentence_index) <= RECENT_WINDOW
        })
        .cloned()
}

fn has_subject_like_argument(row: &DocumentSemanticProposition) -> bool {
    row.arguments
        .iter()
        .any(|argument| is_subject_like(&argument.semantic_role) || is_subject_like(&argument.role))
}

fn has_role(row: &DocumentSemanticProposition, role: &str) -> bool {
    row.arguments
        .iter()
        .any(|argument| argument.semantic_role == role || argument.role == role)
        || row
            .document_argument_recoveries
            .iter()
            .any(|argument| argument.semantic_role == role || argument.role == role)
}

fn is_recoverable_predicate(row: &DocumentSemanticProposition) -> bool {
    row.predicate_quality != "noise"
        && !(row.predicate_quality == "participle_modifier" && row.frame.frame == "unclassified")
        && !matches!(row.frame.family.as_str(), "attribute" | "identity")
}

fn is_subject_like(role: &str) -> bool {
    matches!(
        role,
        "subject" | "actor" | "agent" | "speaker" | "experiencer" | "bearer"
    )
}

fn is_pronoun(value: &str) -> bool {
    matches!(
        value,
        "he" | "him" | "his" | "she" | "her" | "hers" | "they" | "them" | "it" | "its"
    )
}

fn event_key(row: &DocumentSemanticProposition) -> String {
    if row.frame.frame != "unclassified" {
        format!("frame:{}", row.frame.frame)
    } else {
        format!("predicate:{}", row.predicate)
    }
}

fn normalize_surface(value: &str) -> String {
    let lower = value.to_ascii_lowercase();
    lower
        .trim_matches(|character: char| !character.is_alphanumeric())
        .trim_start_matches("the ")
        .trim_start_matches("a ")
        .trim_start_matches("an ")
        .to_owned()
}
