use phoenix_machine::{MachineConfig, MachineExtractionConfig, SurfaceCompiler};
use phoenix_proposition::PropositionLowerer;
use phoenix_types::{
    EntityId, EntityKind, PosTag, Proposition, ResolverEntitySeed, ScopeKey, SourceRange,
    TextRange, TokenSpan,
};
use serde::{Deserialize, Serialize};

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
    pub arguments: Vec<DocumentSemanticArgument>,
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
    pub surface: String,
    pub entity_id: Option<String>,
    pub start: Option<usize>,
    pub end: Option<usize>,
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
        let rows = propositions
            .iter()
            .map(|proposition| {
                map_proposition(document, proposition, &artifacts.scan.tokens, &utf16)
            })
            .collect::<Vec<_>>();
        let document_counters = counters_for(artifacts.scan.sentences.len(), &rows);
        add_counters(&mut counters, &document_counters);
        documents.push(DocumentSemanticDocument {
            note_id: document.note_id.clone(),
            text_chars: document.text.encode_utf16().count(),
            propositions: rows,
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
            DocumentSemanticArgument {
                role: argument.role.to_string(),
                surface: range
                    .map(|value| slice(&document.text, value).trim().to_owned())
                    .unwrap_or_default(),
                entity_id: argument.entity_id.as_ref().map(|id| id.0.clone()),
                start: range.map(|value| utf16.offset(value.start)),
                end: range.map(|value| utf16.offset(value.end)),
            }
        })
        .collect::<Vec<_>>();
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
        arguments,
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

fn proposition_confidence(
    proposition: &Proposition,
    arguments: &[DocumentSemanticArgument],
    quality: &PredicateQuality,
) -> u16 {
    let resolved = arguments
        .iter()
        .filter(|argument| argument.entity_id.is_some())
        .count();
    let mut score = 560i32 + arguments.len().min(3) as i32 * 70 + resolved.min(2) as i32 * 75;
    if proposition.quote.is_some() || proposition.conditional.is_some() {
        score += 35;
    }
    score += quality.score_delta;
    score.clamp(160, 960) as u16
}

#[derive(Clone, Debug)]
struct PredicateQuality {
    quality: &'static str,
    admission: &'static str,
    score_delta: i32,
    reasons: Vec<String>,
}

fn predicate_quality(
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
    let has_subject = arguments.iter().any(|argument| argument.role == "subject");
    let resolved = arguments
        .iter()
        .filter(|argument| argument.entity_id.is_some())
        .count();
    let has_core_argument = arguments.iter().any(|argument| {
        matches!(
            argument.role.as_str(),
            "object" | "recipient" | "cause" | "destination" | "source" | "location"
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
