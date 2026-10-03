use std::collections::BTreeSet;

use anyhow::{Context, Result};

use super::common::{candidate_label, fingerprint};
use crate::types::{
    ApplicabilityEntry, AuthorityClass, AuthorityDomain, AuthorityRecord, AuthoritySummary,
    CandidateDefinition, CandidateKind, CandidateSet, CandidateSetSemantics, CanonicalEpisode,
    ContractStatus, DistributionInterpretation, EntityRecord, EvaluationConstraints, EvidenceItem,
    GoldTarget, Identity, Lineage, MentionRecord, ProbabilitySource, ProbabilitySourceMetadata,
    Query, QueryView, Representation, RuntimeSchema, ScoreSemantics, SpanTarget, State,
    StructuredState, TargetPayload, VariableVisibility, WorkloadMetadata,
};

pub const ADAPTER_ID: &str = "massive_v0.2";

pub fn normalize_row(
    row: &serde_json::Value,
    row_id: &str,
    revision: &str,
    split: &str,
    locale: &str,
) -> Result<CanonicalEpisode> {
    let utterance = row
        .get("utt")
        .and_then(serde_json::Value::as_str)
        .context("MASSIVE row missing utt")?;
    let annotated = row
        .get("annot_utt")
        .and_then(serde_json::Value::as_str)
        .context("MASSIVE row missing annot_utt")?;
    let intent = row
        .get("intent")
        .and_then(serde_json::Value::as_str)
        .context("MASSIVE row missing intent")?;
    let (clean, slots) = parse_annotated_utterance(annotated, utterance)?;
    let mut slot_types = BTreeSet::new();
    for slot in &slots {
        slot_types.insert(slot.slot_type.clone());
    }
    let mut intent_candidate = candidate_label(
        intent,
        CandidateKind::Label,
        Some("Source-provided MASSIVE intent label.".to_string()),
    );
    intent_candidate.independent_allowed = false;
    let slot_candidates: Vec<CandidateDefinition> = slot_types
        .iter()
        .map(|slot_type| {
            candidate_label(
                slot_type,
                CandidateKind::EntityType,
                Some(format!("A MASSIVE slot of type {slot_type}.")),
            )
        })
        .collect();
    let mut candidates = vec![intent_candidate];
    candidates.extend(slot_candidates.clone());
    let authority_id = format!("auth-{ADAPTER_ID}-{locale}-{row_id}");
    let intent_query = Query {
        query_id: "q-massive-intent".to_string(),
        query_semantic_id: "massive-intent".to_string(),
        view: QueryView::Choice,
        instruction: Some("Which intent label applies to this utterance?".to_string()),
        candidate_set_id: Some("cs-massive-intent".to_string()),
        argument_scope: None,
        abstention_policy: None,
        exposed_fields: vec!["name".to_string(), "description".to_string()],
    };
    let span_query = Query {
        query_id: "q-massive-slots".to_string(),
        query_semantic_id: "massive-slot-types".to_string(),
        view: QueryView::SpanType,
        instruction: Some("Which runtime slot types apply to the annotated spans?".to_string()),
        candidate_set_id: Some("cs-massive-slots".to_string()),
        argument_scope: None,
        abstention_policy: None,
        exposed_fields: vec!["name".to_string()],
    };
    let hard_source = ProbabilitySourceMetadata {
        probability_source: ProbabilitySource::HardLabel,
        sample_count: Some(1),
        annotator_count: None,
        raw_label_counts: None,
        aggregation_method: "source_annotation".to_string(),
        normalization_scope: "none".to_string(),
        distribution_interpretation: DistributionInterpretation::NotApplicable,
    };
    let intent_target = GoldTarget {
        query_id: intent_query.query_id.clone(),
        authority_record_id: authority_id.clone(),
        score_semantics: ScoreSemantics::HardLabelOnly,
        candidate_set_id: intent_query.candidate_set_id.clone(),
        probability_source: hard_source.clone(),
        target: TargetPayload::Choice {
            selected_candidate_semantic_id: Some(intent.to_string()),
            distribution: None,
            other_probability: None,
            abstain_allowed: false,
        },
        annotations: None,
    };
    let spans_target = slots
        .iter()
        .enumerate()
        .map(|(index, slot)| SpanTarget {
            span_id: format!("massive-span-{index}"),
            start: slot.start,
            end: slot.end,
            type_targets: vec![ApplicabilityEntry {
                candidate_semantic_id: slot.slot_type.clone(),
                applies: Some(true),
                probability: None,
            }],
        })
        .collect();
    let span_target = GoldTarget {
        query_id: span_query.query_id.clone(),
        authority_record_id: authority_id.clone(),
        score_semantics: ScoreSemantics::SpanTypeCompatibility,
        candidate_set_id: span_query.candidate_set_id.clone(),
        probability_source: hard_source,
        target: TargetPayload::SpanType {
            spans: spans_target,
        },
        annotations: None,
    };
    let evidence_id = format!("ev-massive-{locale}-{row_id}");
    let mut mentions = Vec::new();
    for (index, slot) in slots.iter().enumerate() {
        mentions.push(MentionRecord {
            mention_id: format!("massive-span-{index}"),
            entity_semantic_id: format!("massive-entity-{index}"),
            character_start: slot.start,
            character_end: slot.end,
            surface: slot.value.clone(),
            type_semantic_id: slot.slot_type.clone(),
        });
    }
    let entities = slots
        .iter()
        .enumerate()
        .map(|(index, slot)| EntityRecord {
            entity_semantic_id: format!("massive-entity-{index}"),
            type_semantic_id: slot.slot_type.clone(),
            canonical_name: slot.value.clone(),
            mentions: vec![mentions[index].clone()],
        })
        .collect();
    let lineage = Lineage {
        source_dataset_id: "AmazonScience/massive".to_string(),
        source_revision: revision.to_string(),
        source_split: split.to_string(),
        source_row_id: row_id.to_string(),
        upstream_dataset_id: Some("MASSIVE".to_string()),
        upstream_row_id: Some(row_id.to_string()),
        adapter_id: ADAPTER_ID.to_string(),
        adapter_revision: "0.2.0".to_string(),
        transformation_chain: vec![
            "annot_utt_inline_slots".to_string(),
            "slot_offsets_to_mentions".to_string(),
        ],
    };
    let authority = AuthorityRecord {
        authority_record_id: authority_id.clone(),
        authority_class: AuthorityClass::ExternallyAnnotated,
        authority_domain: AuthorityDomain::ExternalDataset,
        authority_scope: "MASSIVE intent and slot annotations".to_string(),
        creator_or_system: "AmazonScience MASSIVE".to_string(),
        source_identity: "AmazonScience/massive".to_string(),
        source_revision_or_snapshot: revision.to_string(),
        annotation_or_generator_protocol:
            "localized utterances with intent and inline slot annotations".to_string(),
        created_at: None,
        available_at: None,
        license_or_access_basis: Some("CC-BY-4.0 metadata".to_string()),
        parent_authority_ids: Vec::new(),
        quality_limitations: vec![
            "slot offsets are reconstructed against source utterance".to_string(),
        ],
        lineage,
    };
    let mut episode = CanonicalEpisode {
        contract: crate::types::CONTRACT_V1.to_string(),
        contract_status: ContractStatus::V1PlusProposedE01E02,
        identity: Identity {
            episode_id: format!("massive-{locale}-{row_id}"),
            world_family_id: format!("external:massive:{locale}"),
            world_instance_id: format!("massive:{locale}:{row_id}"),
            surface_renderer_id: "source-massive-utterance".to_string(),
            paraphrase_family_id: "external-source-native".to_string(),
            perturbation_family_id: "none".to_string(),
            schema_family_id: "schema-massive-intent-slots".to_string(),
            task_family_ids: vec!["choice".to_string(), "span_type".to_string()],
            domain_family_id: "spoken_language_understanding".to_string(),
            semantic_fingerprint: String::new(),
        },
        state: State {
            representation: Representation::Prose,
            observable: crate::types::ObservableState {
                content: clean.clone(),
                items: vec![evidence_id.clone()],
            },
            latent: None,
            variables: VariableVisibility {
                observed: vec![evidence_id.clone()],
                missing: Vec::new(),
                hidden: Vec::new(),
            },
            structured_state: Some(StructuredState {
                offset_unit: "utf8_byte".to_string(),
                entities,
                semantic_relations: Vec::new(),
            }),
        },
        evidence_items: vec![EvidenceItem {
            evidence_id,
            kind: "text".to_string(),
            content: clean,
            source_ref: format!("AmazonScience/massive:{locale}:{row_id}"),
            available_at: None,
            character_span: Some([0, utterance.len()]),
        }],
        runtime_schema: RuntimeSchema {
            schema_id: "schema-massive-intent-slots".to_string(),
            schema_family_id: "schema-massive-intent-slots".to_string(),
            candidates,
            candidate_sets: vec![
                CandidateSet {
                    candidate_set_id: "cs-massive-intent".to_string(),
                    candidate_ids: vec![intent.to_string()],
                    set_role: "intent-label".to_string(),
                    declared_semantics: CandidateSetSemantics::Unknown,
                    ordered: false,
                    parent_candidate_set_id: None,
                },
                CandidateSet {
                    candidate_set_id: "cs-massive-slots".to_string(),
                    candidate_ids: slot_candidates
                        .iter()
                        .map(|candidate| candidate.candidate_id.clone())
                        .collect(),
                    set_role: "span-types".to_string(),
                    declared_semantics: CandidateSetSemantics::SpanTypePairs,
                    ordered: false,
                    parent_candidate_set_id: None,
                },
            ],
            constraints: vec!["contiguous_non_overlapping_mentions".to_string()],
            presentation_profiles: Vec::new(),
        },
        queries: vec![intent_query, span_query],
        gold_targets: vec![intent_target, span_target],
        evidence_links: Vec::new(),
        perturbation: None,
        authority: AuthoritySummary {
            episode_authority_class: AuthorityClass::ExternallyAnnotated,
            authority_record_ids: vec![authority_id.clone()],
            phoenix_authority_domain: false,
        },
        authority_records: vec![authority],
        workload: WorkloadMetadata {
            query_count: 2,
            span_count: Some(slots.len() as u32),
            ..WorkloadMetadata::default()
        },
        evaluation_constraints: EvaluationConstraints {
            split_regime: Some("span_relation_eval".to_string()),
            excluded_from_primary_benchmark: true,
            notes: vec!["structured_state proposed E01 extension".to_string()],
        },
    };
    episode.identity.semantic_fingerprint = fingerprint(&episode)?;
    Ok(episode)
}

#[derive(Clone, Debug)]
struct SlotSpan {
    slot_type: String,
    value: String,
    start: usize,
    end: usize,
}

fn parse_annotated_utterance(annotated: &str, raw: &str) -> Result<(String, Vec<SlotSpan>)> {
    let mut clean = String::with_capacity(raw.len());
    let mut slots = Vec::new();
    let mut cursor = 0_usize;
    while cursor < annotated.len() {
        if annotated.as_bytes()[cursor] != b'[' {
            let next = annotated[cursor..]
                .find('[')
                .map(|offset| cursor + offset)
                .unwrap_or(annotated.len());
            clean.push_str(&annotated[cursor..next]);
            cursor = next;
            continue;
        }
        let close = annotated[cursor..]
            .find(']')
            .map(|offset| cursor + offset)
            .context("unterminated MASSIVE slot annotation")?;
        let inner = &annotated[cursor + 1..close];
        let (slot_type, value) = inner.split_once(':').context("MASSIVE slot lacks colon")?;
        let slot_type = slot_type.trim().to_string();
        let value = value.trim().to_string();
        let start = clean.len();
        clean.push_str(&value);
        let end = clean.len();
        slots.push(SlotSpan {
            slot_type,
            value,
            start,
            end,
        });
        cursor = close + 1;
    }
    if clean != raw {
        let mut offset = 0_usize;
        for slot in &mut slots {
            let position = raw[offset..]
                .find(&slot.value)
                .map(|index| offset + index)
                .context("MASSIVE slot value missing from utt")?;
            slot.start = position;
            slot.end = position + slot.value.len();
            offset = slot.end;
        }
        return Ok((raw.to_string(), slots));
    }
    Ok((clean, slots))
}
