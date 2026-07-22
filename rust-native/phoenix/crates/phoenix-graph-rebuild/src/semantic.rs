use phoenix_machine::{MachineConfig, MachineExtractionConfig, SurfaceCompiler};
use phoenix_proposition::PropositionLowerer;
use phoenix_types::{
    EntityId, EntityKind, Proposition, ResolverEntitySeed, ScopeKey, SourceRange, TokenSpan,
};
use serde::{Deserialize, Serialize};

mod factuality;
mod frame;
mod precision;
mod recovery;
mod temporal;
pub use factuality::{
    DocumentSemanticAttributionFrame, DocumentSemanticConditionalFrame,
    DocumentSemanticFactualityEnvelope, DocumentSemanticSpeechOrBeliefFrame,
};
pub use frame::DocumentSemanticFrame;
use precision::{predicate_quality, proposition_confidence, role_precision_for};
pub use recovery::DocumentSemanticRecoveredArgument;
pub use temporal::{
    DocumentSemanticEventOrdering, DocumentSemanticSituationInstance,
    DocumentSemanticStateInterval, DocumentSemanticTemporalConflict,
};

const PREVIEW_CHARS: usize = 320;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticRequest {
    #[serde(default)]
    pub documents: Vec<DocumentSemanticInput>,
    #[serde(default)]
    pub entities: Vec<DocumentSemanticEntity>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticInput {
    pub note_id: String,
    pub text: String,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticEntity {
    pub id: String,
    pub label: String,
    #[serde(default)]
    pub aliases: Vec<String>,
    #[serde(default)]
    pub kind: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticCounters {
    pub documents: usize,
    pub sentences: usize,
    pub propositions: usize,
    pub arguments: usize,
    pub resolved_arguments: usize,
    pub role_annotations: usize,
    pub unresolved_role_surfaces: usize,
    pub role_failure_reasons: usize,
    pub frame_annotations: usize,
    pub lexical_frame_matches: usize,
    pub fallback_frame_matches: usize,
    pub low_confidence_frames: usize,
    pub frame_failure_reasons: usize,
    pub factuality_annotations: usize,
    pub scoped_factuality: usize,
    pub attributed_factuality: usize,
    pub quoted_factuality: usize,
    pub conditional_factuality: usize,
    pub speech_or_belief_frames: usize,
    pub low_confidence_factuality: usize,
    pub factuality_failure_reasons: usize,
    pub document_argument_recoveries: usize,
    pub local_coreference_recoveries: usize,
    pub alias_continuity_recoveries: usize,
    pub omitted_subject_recoveries: usize,
    pub quote_speaker_recoveries: usize,
    pub repeated_event_links: usize,
    pub window_argument_completions: usize,
    pub low_confidence_recoveries: usize,
    pub recovery_failure_reasons: usize,
    pub situation_instances: usize,
    pub state_intervals: usize,
    pub event_orderings: usize,
    pub explicit_event_orderings: usize,
    pub recurrence_orderings: usize,
    pub persistent_state_intervals: usize,
    pub terminated_state_intervals: usize,
    pub temporal_conflicts: usize,
    pub world_state_ineligible_situations: usize,
    pub negated: usize,
    pub modal: usize,
    pub conditional: usize,
    pub attributed: usize,
    pub quoted: usize,
    pub questions: usize,
    pub directives: usize,
    pub n_ary: usize,
    pub reviewable: usize,
    pub ledger_only: usize,
    pub predicate_modifiers: usize,
    pub predicate_noise: usize,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticSummary {
    pub schema_version: String,
    pub source: String,
    pub documents: Vec<DocumentSemanticDocument>,
    pub counters: DocumentSemanticCounters,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticDocument {
    pub note_id: String,
    pub text_chars: usize,
    pub propositions: Vec<DocumentSemanticProposition>,
    pub situations: Vec<DocumentSemanticSituationInstance>,
    pub state_intervals: Vec<DocumentSemanticStateInterval>,
    pub event_orderings: Vec<DocumentSemanticEventOrdering>,
    pub temporal_conflicts: Vec<DocumentSemanticTemporalConflict>,
    pub counters: DocumentSemanticCounters,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticProposition {
    pub id: String,
    pub note_id: String,
    pub sentence_index: usize,
    pub start: usize,
    pub end: usize,
    pub preview: String,
    pub predicate: String,
    pub relation_type: String,
    pub predicate_quality: String,
    pub predicate_admission: String,
    pub quality_reasons: Vec<String>,
    pub trigger_start: usize,
    pub trigger_end: usize,
    pub frame: DocumentSemanticFrame,
    pub factuality: DocumentSemanticFactualityEnvelope,
    pub attribution_frame: Option<DocumentSemanticAttributionFrame>,
    pub conditional_frame: Option<DocumentSemanticConditionalFrame>,
    pub speech_or_belief_frame: Option<DocumentSemanticSpeechOrBeliefFrame>,
    pub arguments: Vec<DocumentSemanticArgument>,
    pub document_argument_recoveries: Vec<DocumentSemanticRecoveredArgument>,
    pub scope: Vec<DocumentSemanticScope>,
    pub attribution: Option<DocumentSemanticAttribution>,
    pub conditional: Option<DocumentSemanticConditional>,
    pub quote: Option<DocumentSemanticQuote>,
    pub evidence: Vec<DocumentSemanticEvidence>,
    pub confidence_millis: u16,
    pub review_state: String,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticArgument {
    pub role: String,
    pub syntactic_role: String,
    pub semantic_role: String,
    pub surface: String,
    pub entity_id: Option<String>,
    pub start: Option<usize>,
    pub end: Option<usize>,
    pub role_confidence_millis: u16,
    pub role_failure_reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticScope {
    pub kind: String,
    pub polarity: Option<String>,
    pub modality: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticAttribution {
    pub source_entity_id: Option<String>,
    pub start: Option<usize>,
    pub end: Option<usize>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticConditional {
    pub condition_start: Option<usize>,
    pub condition_end: Option<usize>,
    pub consequent_start: Option<usize>,
    pub consequent_end: Option<usize>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticQuote {
    pub speaker_entity_id: Option<String>,
    pub start: usize,
    pub end: usize,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticEvidence {
    pub label: String,
    pub kind: Option<String>,
    pub start: usize,
    pub end: usize,
}

pub fn build_document_semantic_summary(
    request: &DocumentSemanticRequest,
) -> DocumentSemanticSummary {
    let compiler = SurfaceCompiler::new(MachineConfig {
        extraction: MachineExtractionConfig {
            enable_rustling_pos: false,
            enable_scirs2_rule_ner: false,
            enable_scirs2_pattern_ner: false,
            enable_native_refinement: false,
        },
    });
    let seeds = resolver_seeds(&request.entities);
    let mut documents = Vec::with_capacity(request.documents.len());
    let mut counters = DocumentSemanticCounters::default();
    for document in &request.documents {
        let artifacts = compiler.compile(&document.text, &ScopeKey::default(), &seeds);
        let propositions = PropositionLowerer::lower_with_text(&document.text, &artifacts);
        let utf16 = Utf16Index::new(&document.text);
        let mut rows = propositions
            .iter()
            .map(|proposition| {
                map_proposition(document, proposition, &artifacts.scan.tokens, &utf16)
            })
            .collect::<Vec<_>>();
        recovery::recover_document_arguments(document, &mut rows);
        let continuity = temporal::build_temporal_continuity(document, &rows);
        let mut document_counters = counters_for(artifacts.scan.sentences.len(), &rows);
        document_counters.situation_instances = continuity.situations.len();
        document_counters.state_intervals = continuity.state_intervals.len();
        document_counters.event_orderings = continuity.event_orderings.len();
        document_counters.explicit_event_orderings = continuity
            .event_orderings
            .iter()
            .filter(|row| row.source == "explicit_cue")
            .count();
        document_counters.recurrence_orderings = continuity
            .event_orderings
            .iter()
            .filter(|row| row.relation == "recurs_after")
            .count();
        document_counters.persistent_state_intervals = continuity
            .state_intervals
            .iter()
            .filter(|row| row.persists)
            .count();
        document_counters.terminated_state_intervals = continuity
            .state_intervals
            .iter()
            .filter(|row| row.status == "terminated" || row.status == "superseded")
            .count();
        document_counters.temporal_conflicts = continuity.temporal_conflicts.len();
        document_counters.world_state_ineligible_situations = continuity
            .situations
            .iter()
            .filter(|row| !row.world_state_eligible)
            .count();
        add_counters(&mut counters, &document_counters);
        documents.push(DocumentSemanticDocument {
            note_id: document.note_id.clone(),
            text_chars: document.text.encode_utf16().count(),
            propositions: rows,
            situations: continuity.situations,
            state_intervals: continuity.state_intervals,
            event_orderings: continuity.event_orderings,
            temporal_conflicts: continuity.temporal_conflicts,
            counters: document_counters,
        });
    }
    counters.documents = documents.len();
    DocumentSemanticSummary {
        schema_version: "phoenix-document-semantics/v1".to_owned(),
        source: "native_rust".to_owned(),
        documents,
        counters,
    }
}

pub fn build_document_semantic_document(
    document: &DocumentSemanticInput,
    entities: &[DocumentSemanticEntity],
) -> DocumentSemanticDocument {
    let mut summary = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![document.clone()],
        entities: entities.to_vec(),
    });
    summary.documents.pop().unwrap_or_default()
}

pub fn merge_document_semantic_documents(
    documents: Vec<DocumentSemanticDocument>,
) -> DocumentSemanticSummary {
    let mut counters = DocumentSemanticCounters::default();
    for document in &documents {
        add_counters(&mut counters, &document.counters);
    }
    counters.documents = documents.len();
    DocumentSemanticSummary {
        schema_version: "phoenix-document-semantics/v1".to_owned(),
        source: "native_rust".to_owned(),
        documents,
        counters,
    }
}

fn resolver_seeds(entities: &[DocumentSemanticEntity]) -> Vec<ResolverEntitySeed> {
    entities
        .iter()
        .filter(|entity| !entity.id.is_empty() && !entity.label.is_empty())
        .map(|entity| ResolverEntitySeed {
            entity_id: EntityId(entity.id.clone()),
            canonical_name: entity.label.clone(),
            aliases: entity.aliases.clone(),
            kind: Some(entity_kind(&entity.kind)),
            gender: None,
            number: None,
            scope: ScopeKey::default(),
        })
        .collect()
}

fn entity_kind(value: &str) -> EntityKind {
    match value.to_ascii_lowercase().as_str() {
        "character" => EntityKind::Character,
        "npc" => EntityKind::Npc,
        "location" => EntityKind::Location,
        "item" | "object" => EntityKind::Item,
        "faction" | "group" | "network" => EntityKind::Faction,
        "organization" | "organisation" => EntityKind::Organization,
        "event" | "timeline" => EntityKind::Event,
        "concept" => EntityKind::Concept,
        _ => EntityKind::Other,
    }
}

fn map_proposition(
    document: &DocumentSemanticInput,
    proposition: &Proposition,
    tokens: &[TokenSpan],
    utf16: &Utf16Index,
) -> DocumentSemanticProposition {
    let clause = proposition
        .clause_range
        .unwrap_or(proposition.predicate.trigger_range);
    let preview = slice(&document.text, clause)
        .chars()
        .take(PREVIEW_CHARS)
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    let arguments = proposition
        .arguments
        .iter()
        .map(|argument| {
            let range = argument.range;
            let surface = range
                .map(|value| slice(&document.text, value).trim().to_owned())
                .unwrap_or_default();
            let syntactic_role = argument.role.to_string();
            let precision = role_precision_for(
                syntactic_role.as_str(),
                proposition.predicate.relation_type.as_str(),
                surface.as_str(),
                argument.entity_id.is_some(),
                range.is_some(),
            );
            DocumentSemanticArgument {
                role: syntactic_role.clone(),
                syntactic_role,
                semantic_role: precision.semantic_role.to_owned(),
                surface,
                entity_id: argument.entity_id.as_ref().map(|id| id.0.clone()),
                start: range.map(|value| utf16.offset(value.start)),
                end: range.map(|value| utf16.offset(value.end)),
                role_confidence_millis: precision.confidence_millis,
                role_failure_reasons: precision.failure_reasons,
            }
        })
        .collect::<Vec<_>>();
    let frame = frame::classify_frame(
        proposition.predicate.predicate.as_str(),
        proposition.predicate.relation_type.as_str(),
        &arguments,
    );
    let factuality::FactualityBundle {
        envelope: factuality,
        attribution_frame,
        conditional_frame,
        speech_or_belief_frame,
    } = factuality::build_factuality_bundle(proposition, &frame, |offset| utf16.offset(offset));
    let quality = predicate_quality(&document.text, proposition, &arguments, tokens);
    let confidence_millis = proposition_confidence(proposition, &arguments, &quality);
    DocumentSemanticProposition {
        id: format!("{}:{}", document.note_id, proposition.proposition_id),
        note_id: document.note_id.clone(),
        sentence_index: proposition.sentence_index,
        start: utf16.offset(clause.start),
        end: utf16.offset(clause.end),
        preview,
        predicate: proposition.predicate.predicate.to_string(),
        relation_type: proposition.predicate.relation_type.to_string(),
        predicate_quality: quality.quality.to_owned(),
        predicate_admission: quality.admission.to_owned(),
        quality_reasons: quality.reasons.clone(),
        trigger_start: utf16.offset(proposition.predicate.trigger_range.start),
        trigger_end: utf16.offset(proposition.predicate.trigger_range.end),
        frame,
        factuality,
        attribution_frame,
        conditional_frame,
        speech_or_belief_frame,
        arguments,
        document_argument_recoveries: Vec::new(),
        scope: proposition
            .scope_ops
            .iter()
            .map(|scope| DocumentSemanticScope {
                kind: scope.kind.to_string(),
                polarity: scope.polarity.as_ref().map(ToString::to_string),
                modality: scope.modality.as_ref().map(ToString::to_string),
            })
            .collect(),
        attribution: proposition.attribution.as_ref().map(|attribution| {
            DocumentSemanticAttribution {
                source_entity_id: attribution.source_entity_id.as_ref().map(|id| id.0.clone()),
                start: attribution
                    .quote_range
                    .map(|range| utf16.offset(range.start)),
                end: attribution.quote_range.map(|range| utf16.offset(range.end)),
            }
        }),
        conditional: proposition.conditional.as_ref().map(|conditional| {
            DocumentSemanticConditional {
                condition_start: conditional
                    .condition_range
                    .map(|range| utf16.offset(range.start)),
                condition_end: conditional
                    .condition_range
                    .map(|range| utf16.offset(range.end)),
                consequent_start: conditional
                    .consequent_range
                    .map(|range| utf16.offset(range.start)),
                consequent_end: conditional
                    .consequent_range
                    .map(|range| utf16.offset(range.end)),
            }
        }),
        quote: proposition
            .quote
            .as_ref()
            .map(|quote| DocumentSemanticQuote {
                speaker_entity_id: quote.speaker_entity_id.as_ref().map(|id| id.0.clone()),
                start: utf16.offset(quote.quote_range.start),
                end: utf16.offset(quote.quote_range.end),
            }),
        evidence: proposition
            .evidence
            .iter()
            .map(|evidence| DocumentSemanticEvidence {
                label: evidence.label.to_string(),
                kind: evidence.kind.as_ref().map(ToString::to_string),
                start: utf16.offset(evidence.range.start),
                end: utf16.offset(evidence.range.end),
            })
            .collect(),
        confidence_millis,
        review_state: if quality.admission == "review" {
            "proposed"
        } else {
            "ledger_only"
        }
        .to_owned(),
    }
}

fn counters_for(
    sentences: usize,
    propositions: &[DocumentSemanticProposition],
) -> DocumentSemanticCounters {
    let mut counters = DocumentSemanticCounters {
        sentences,
        propositions: propositions.len(),
        ..DocumentSemanticCounters::default()
    };
    for proposition in propositions {
        if proposition.review_state == "proposed" {
            counters.reviewable += 1;
        }
        if proposition.review_state == "ledger_only" {
            counters.ledger_only += 1;
        }
        if proposition.predicate_quality == "participle_modifier"
            || proposition.predicate_quality == "nominal_event"
        {
            counters.predicate_modifiers += 1;
        }
        if proposition.predicate_quality == "noise" {
            counters.predicate_noise += 1;
        }
        counters.arguments += proposition.arguments.len();
        counters.resolved_arguments += proposition
            .arguments
            .iter()
            .filter(|argument| argument.entity_id.is_some())
            .count();
        counters.role_annotations += proposition.arguments.len();
        counters.unresolved_role_surfaces += proposition
            .arguments
            .iter()
            .filter(|argument| {
                argument.entity_id.is_none()
                    && !argument.surface.is_empty()
                    && argument
                        .role_failure_reasons
                        .iter()
                        .any(|reason| reason == "unresolved_entity")
            })
            .count();
        counters.role_failure_reasons += proposition
            .arguments
            .iter()
            .map(|argument| argument.role_failure_reasons.len())
            .sum::<usize>();
        counters.document_argument_recoveries += proposition.document_argument_recoveries.len();
        counters.local_coreference_recoveries += proposition
            .document_argument_recoveries
            .iter()
            .filter(|argument| argument.kind == "local_coreference")
            .count();
        counters.alias_continuity_recoveries += proposition
            .document_argument_recoveries
            .iter()
            .filter(|argument| argument.kind == "alias_continuity")
            .count();
        counters.omitted_subject_recoveries += proposition
            .document_argument_recoveries
            .iter()
            .filter(|argument| argument.kind == "omitted_subject")
            .count();
        counters.quote_speaker_recoveries += proposition
            .document_argument_recoveries
            .iter()
            .filter(|argument| argument.kind == "quote_speaker_carryover")
            .count();
        counters.repeated_event_links += proposition
            .document_argument_recoveries
            .iter()
            .filter(|argument| argument.kind == "repeated_event_entity_link")
            .count();
        counters.window_argument_completions += proposition
            .document_argument_recoveries
            .iter()
            .filter(|argument| argument.kind == "window_argument_completion")
            .count();
        counters.low_confidence_recoveries += proposition
            .document_argument_recoveries
            .iter()
            .filter(|argument| argument.confidence_millis < 600)
            .count();
        counters.recovery_failure_reasons += proposition
            .document_argument_recoveries
            .iter()
            .map(|argument| argument.failure_reasons.len())
            .sum::<usize>();
        counters.frame_annotations += 1;
        counters.lexical_frame_matches += (proposition.frame.source == "lexical_table") as usize;
        counters.fallback_frame_matches += matches!(
            proposition.frame.source.as_str(),
            "relation_type_rule" | "role_pattern_rule"
        ) as usize;
        counters.low_confidence_frames += (proposition.frame.confidence_millis < 600) as usize;
        counters.frame_failure_reasons += proposition.frame.failure_reasons.len();
        counters.factuality_annotations += 1;
        counters.scoped_factuality += (proposition.factuality.factuality != "asserted") as usize;
        counters.attributed_factuality += proposition.factuality.reported as usize;
        counters.quoted_factuality += proposition.factuality.quoted as usize;
        counters.conditional_factuality += proposition.factuality.conditional as usize;
        counters.speech_or_belief_frames += proposition.speech_or_belief_frame.is_some() as usize;
        counters.low_confidence_factuality +=
            (proposition.factuality.confidence_millis < 600) as usize;
        counters.factuality_failure_reasons += proposition.factuality.failure_reasons.len()
            + proposition
                .attribution_frame
                .as_ref()
                .map_or(0, |frame| frame.failure_reasons.len())
            + proposition
                .conditional_frame
                .as_ref()
                .map_or(0, |frame| frame.failure_reasons.len())
            + proposition
                .speech_or_belief_frame
                .as_ref()
                .map_or(0, |frame| frame.failure_reasons.len());
        counters.negated += proposition
            .scope
            .iter()
            .any(|scope| scope.polarity.as_deref() == Some("negative"))
            as usize;
        counters.modal += proposition
            .scope
            .iter()
            .any(|scope| scope.kind == "modality") as usize;
        counters.questions += proposition
            .scope
            .iter()
            .any(|scope| scope.kind == "question") as usize;
        counters.directives += proposition
            .scope
            .iter()
            .any(|scope| scope.kind == "directive") as usize;
        counters.conditional += proposition.conditional.is_some() as usize;
        counters.attributed += proposition.attribution.is_some() as usize;
        counters.quoted += proposition.quote.is_some() as usize;
        counters.n_ary += (proposition.arguments.len() >= 3) as usize;
    }
    counters
}

fn add_counters(total: &mut DocumentSemanticCounters, value: &DocumentSemanticCounters) {
    total.sentences += value.sentences;
    total.propositions += value.propositions;
    total.arguments += value.arguments;
    total.resolved_arguments += value.resolved_arguments;
    total.role_annotations += value.role_annotations;
    total.unresolved_role_surfaces += value.unresolved_role_surfaces;
    total.role_failure_reasons += value.role_failure_reasons;
    total.frame_annotations += value.frame_annotations;
    total.lexical_frame_matches += value.lexical_frame_matches;
    total.fallback_frame_matches += value.fallback_frame_matches;
    total.low_confidence_frames += value.low_confidence_frames;
    total.frame_failure_reasons += value.frame_failure_reasons;
    total.factuality_annotations += value.factuality_annotations;
    total.scoped_factuality += value.scoped_factuality;
    total.attributed_factuality += value.attributed_factuality;
    total.quoted_factuality += value.quoted_factuality;
    total.conditional_factuality += value.conditional_factuality;
    total.speech_or_belief_frames += value.speech_or_belief_frames;
    total.low_confidence_factuality += value.low_confidence_factuality;
    total.factuality_failure_reasons += value.factuality_failure_reasons;
    total.document_argument_recoveries += value.document_argument_recoveries;
    total.local_coreference_recoveries += value.local_coreference_recoveries;
    total.alias_continuity_recoveries += value.alias_continuity_recoveries;
    total.omitted_subject_recoveries += value.omitted_subject_recoveries;
    total.quote_speaker_recoveries += value.quote_speaker_recoveries;
    total.repeated_event_links += value.repeated_event_links;
    total.window_argument_completions += value.window_argument_completions;
    total.low_confidence_recoveries += value.low_confidence_recoveries;
    total.recovery_failure_reasons += value.recovery_failure_reasons;
    total.situation_instances += value.situation_instances;
    total.state_intervals += value.state_intervals;
    total.event_orderings += value.event_orderings;
    total.explicit_event_orderings += value.explicit_event_orderings;
    total.recurrence_orderings += value.recurrence_orderings;
    total.persistent_state_intervals += value.persistent_state_intervals;
    total.terminated_state_intervals += value.terminated_state_intervals;
    total.temporal_conflicts += value.temporal_conflicts;
    total.world_state_ineligible_situations += value.world_state_ineligible_situations;
    total.negated += value.negated;
    total.modal += value.modal;
    total.conditional += value.conditional;
    total.attributed += value.attributed;
    total.quoted += value.quoted;
    total.questions += value.questions;
    total.directives += value.directives;
    total.n_ary += value.n_ary;
    total.reviewable += value.reviewable;
    total.ledger_only += value.ledger_only;
    total.predicate_modifiers += value.predicate_modifiers;
    total.predicate_noise += value.predicate_noise;
}

fn slice(text: &str, range: SourceRange) -> &str {
    text.get(range.start as usize..range.end as usize)
        .unwrap_or_default()
}

struct Utf16Index {
    offsets: Vec<u32>,
}

impl Utf16Index {
    fn new(text: &str) -> Self {
        let mut offsets = vec![0u32; text.len() + 1];
        let mut utf16 = 0u32;
        for (start, ch) in text.char_indices() {
            let end = start + ch.len_utf8();
            for offset in &mut offsets[start..end] {
                *offset = utf16;
            }
            utf16 = utf16.saturating_add(ch.len_utf16() as u32);
            offsets[end] = utf16;
        }
        Self { offsets }
    }

    fn offset(&self, byte: u32) -> usize {
        self.offsets
            .get(byte as usize)
            .copied()
            .unwrap_or_else(|| self.offsets.last().copied().unwrap_or_default()) as usize
    }
}

#[cfg(test)]
mod tests;
