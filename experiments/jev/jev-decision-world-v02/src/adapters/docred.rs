use std::collections::BTreeMap;

use anyhow::{Context, Result, ensure};

use super::common::fingerprint;
use crate::types::{
    AuthorityClass, AuthorityDomain, AuthorityRecord, AuthoritySummary, CandidateDefinition,
    CandidateKind, CandidateSet, CandidateSetSemantics, CanonicalEpisode, ContractStatus,
    DistributionInterpretation, EntityRecord, EvaluationConstraints, EvidenceItem, EvidenceLink,
    EvidenceLocation, GoldTarget, Identity, Lineage, MentionRecord, ProbabilitySource,
    ProbabilitySourceMetadata, Query, QueryView, RelationPolarity, RelationTarget, Representation,
    RuntimeSchema, ScoreSemantics, SemanticRelation, State, StructuredState, TargetPayload,
    VariableVisibility, WorkloadMetadata,
};

pub const ADAPTER_ID: &str = "docred_v0.2";

type RenderedSentences = (String, Vec<(usize, usize)>, Vec<Vec<String>>);

/// Normalizes an annotated DocRED row without turning unannotated pairs into false relations.
/// DocRED token offsets are converted to byte offsets in the joined sentence rendering.
pub fn normalize_row(
    row: &serde_json::Value,
    row_id: &str,
    revision: &str,
    split: &str,
) -> Result<CanonicalEpisode> {
    let sentences = row
        .get("sents")
        .and_then(serde_json::Value::as_array)
        .context("DocRED row missing sents")?;
    ensure!(!sentences.is_empty(), "DocRED row has no sentences");
    let (text, sentence_offsets, sentence_tokens) = render_sentences(sentences)?;
    let vertices = row
        .get("vertexSet")
        .and_then(serde_json::Value::as_array)
        .context("DocRED row missing vertexSet")?;
    let mut entities = Vec::with_capacity(vertices.len());
    let mut mention_ids_by_entity = Vec::with_capacity(vertices.len());
    for (entity_index, mentions) in vertices.iter().enumerate() {
        let mentions = mentions
            .as_array()
            .context("DocRED vertexSet entry is not an array")?;
        ensure!(!mentions.is_empty(), "DocRED entity has no mentions");
        let mut normalized_mentions = Vec::with_capacity(mentions.len());
        let mut entity_type = "entity".to_string();
        let mut canonical_name = String::new();
        for (mention_index, mention) in mentions.iter().enumerate() {
            let sent_id = mention
                .get("sent_id")
                .and_then(serde_json::Value::as_u64)
                .context("DocRED mention missing sent_id")? as usize;
            let pos = mention
                .get("pos")
                .and_then(serde_json::Value::as_array)
                .context("DocRED mention missing pos")?;
            ensure!(pos.len() == 2, "DocRED mention pos must contain start/end");
            let start_token = pos[0]
                .as_u64()
                .context("DocRED mention start is not an integer")?
                as usize;
            let end_token = pos[1]
                .as_u64()
                .context("DocRED mention end is not an integer")?
                as usize;
            let (start, end, surface) = token_span(
                &sentence_tokens,
                &sentence_offsets,
                sent_id,
                start_token,
                end_token,
            )?;
            let type_id = mention
                .get("type")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("entity");
            let name = mention
                .get("name")
                .and_then(serde_json::Value::as_str)
                .unwrap_or(&surface);
            if canonical_name.is_empty() {
                canonical_name = name.to_string();
                entity_type = type_id.to_string();
            }
            normalized_mentions.push(MentionRecord {
                mention_id: format!("docred-entity-{entity_index}-mention-{mention_index}"),
                entity_semantic_id: format!("docred-entity-{entity_index}"),
                character_start: start,
                character_end: end,
                surface,
                type_semantic_id: type_id.to_string(),
            });
        }
        mention_ids_by_entity.push(
            normalized_mentions
                .first()
                .map(|m| m.mention_id.clone())
                .context("DocRED entity has no normalized mention")?,
        );
        entities.push(EntityRecord {
            entity_semantic_id: format!("docred-entity-{entity_index}"),
            type_semantic_id: entity_type,
            canonical_name,
            mentions: normalized_mentions,
        });
    }

    let labels = row
        .get("labels")
        .and_then(serde_json::Value::as_array)
        .map_or(&[][..], |value| value.as_slice());
    let mut relation_names = BTreeMap::<String, String>::new();
    for label in labels {
        let relation_id = label
            .get("r")
            .or_else(|| label.get("relation_id"))
            .and_then(serde_json::Value::as_u64)
            .context("DocRED label missing relation id")?;
        let relation_text = label
            .get("relation_text")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("relation");
        relation_names
            .entry(relation_id.to_string())
            .or_insert_with(|| relation_text.to_string());
    }
    let relation_candidates: Vec<CandidateDefinition> = relation_names
        .iter()
        .map(|(id, name)| CandidateDefinition {
            candidate_id: format!("relation-{id}"),
            candidate_semantic_id: name.clone(),
            kind: CandidateKind::RelationType,
            name: Some(name.clone()),
            description: Some(format!("DocRED relation {name}.")),
            aliases: Vec::new(),
            opaque_id: Some(format!("relation-{id}")),
            parent_candidate_semantic_id: None,
            order_rank: None,
            mutually_exclusive_group_id: None,
            independent_allowed: false,
        })
        .collect();

    let authority_id = format!("auth-{ADAPTER_ID}-{split}-{row_id}");
    let query = Query {
        query_id: "q-docred-relations".to_string(),
        query_semantic_id: "docred-directed-relation-compatibility".to_string(),
        view: QueryView::Relation,
        instruction: Some(
            "Which directed relations hold between the selected entity mentions?".to_string(),
        ),
        candidate_set_id: Some("cs-docred-relations".to_string()),
        argument_scope: None,
        abstention_policy: Some("unannotated_is_unknown_not_false".to_string()),
        exposed_fields: vec!["name".to_string(), "description".to_string()],
    };
    let mut relation_targets = Vec::with_capacity(labels.len());
    let mut semantic_relations = Vec::with_capacity(labels.len());
    let mut evidence_links = Vec::new();
    for (index, label) in labels.iter().enumerate() {
        let head = label
            .get("h")
            .and_then(serde_json::Value::as_u64)
            .context("DocRED label missing head")? as usize;
        let tail = label
            .get("t")
            .and_then(serde_json::Value::as_u64)
            .context("DocRED label missing tail")? as usize;
        let relation_id = label
            .get("r")
            .or_else(|| label.get("relation_id"))
            .and_then(serde_json::Value::as_u64)
            .context("DocRED label missing relation id")?;
        let relation_name = label
            .get("relation_text")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("relation");
        ensure!(
            head < mention_ids_by_entity.len() && tail < mention_ids_by_entity.len(),
            "DocRED relation endpoint out of range"
        );
        let relation_instance_id = format!("docred-relation-{index}");
        relation_targets.push(RelationTarget {
            relation_instance_id: relation_instance_id.clone(),
            head_span_id: mention_ids_by_entity[head].clone(),
            tail_span_id: mention_ids_by_entity[tail].clone(),
            candidate_semantic_id: relation_name.to_string(),
            direction: "directed".to_string(),
            polarity: RelationPolarity::Holds,
            probability: None,
        });
        semantic_relations.push(SemanticRelation {
            relation_instance_id: relation_instance_id.clone(),
            relation_semantic_id: relation_name.to_string(),
            head_entity_id: format!("docred-entity-{head}"),
            tail_entity_id: format!("docred-entity-{tail}"),
            direction: "directed".to_string(),
            polarity: RelationPolarity::Holds,
        });
        let evidence = label
            .get("evidence")
            .and_then(serde_json::Value::as_array)
            .map_or(&[][..], |value| value.as_slice());
        let sentence_ids: Vec<usize> = evidence
            .iter()
            .filter_map(serde_json::Value::as_u64)
            .map(|value| value as usize)
            .collect();
        let evidence_item_ids: Vec<String> = sentence_ids
            .iter()
            .map(|sentence_id| format!("docred-sentence-{sentence_id}"))
            .collect();
        let locations = sentence_ids
            .iter()
            .filter_map(|sentence_id| {
                sentence_offsets
                    .get(*sentence_id)
                    .map(|(start, end)| EvidenceLocation {
                        evidence_id: format!("docred-sentence-{sentence_id}"),
                        start: *start,
                        end: *end,
                    })
            })
            .collect();
        evidence_links.push(EvidenceLink {
            evidence_link_id: format!("link-docred-relation-{index}"),
            target_ref: format!("relation:{relation_instance_id}"),
            evidence_item_ids,
            role: "support".to_string(),
            locations,
            required_for_target: false,
        });
        let _ = relation_id;
    }
    let evidence_items = sentence_offsets
        .iter()
        .enumerate()
        .map(|(index, (start, end))| EvidenceItem {
            evidence_id: format!("docred-sentence-{index}"),
            kind: "sentence".to_string(),
            content: text[*start..*end].to_string(),
            source_ref: format!("docred:{split}:{row_id}"),
            available_at: None,
            character_span: Some([*start, *end]),
        })
        .collect();
    let candidate_ids = relation_candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect();
    let mut episode = CanonicalEpisode {
        contract: crate::types::CONTRACT_V1.to_string(),
        contract_status: ContractStatus::V1PlusProposedE01E02,
        identity: Identity {
            episode_id: format!("docred-{split}-{row_id}"),
            world_family_id: "external:docred".to_string(),
            world_instance_id: format!("docred:{row_id}"),
            surface_renderer_id: "source-docred-sentence-join".to_string(),
            paraphrase_family_id: "external-source-native".to_string(),
            perturbation_family_id: "none".to_string(),
            schema_family_id: "schema-docred-relations".to_string(),
            task_family_ids: vec!["relation".to_string(), "evidence".to_string()],
            domain_family_id: "document_relation_extraction".to_string(),
            semantic_fingerprint: String::new(),
        },
        state: State {
            representation: Representation::Prose,
            observable: crate::types::ObservableState {
                content: text.clone(),
                items: sentence_offsets
                    .iter()
                    .enumerate()
                    .map(|(index, _)| format!("docred-sentence-{index}"))
                    .collect(),
            },
            latent: None,
            variables: VariableVisibility {
                observed: vec!["document_text".to_string()],
                missing: vec!["unannotated_relation_status".to_string()],
                hidden: Vec::new(),
            },
            structured_state: Some(StructuredState {
                offset_unit: "utf8_byte".to_string(),
                entities,
                semantic_relations,
            }),
        },
        evidence_items,
        runtime_schema: RuntimeSchema {
            schema_id: "schema-docred-relations".to_string(),
            schema_family_id: "schema-docred-relations".to_string(),
            candidates: relation_candidates,
            candidate_sets: vec![CandidateSet {
                candidate_set_id: "cs-docred-relations".to_string(),
                candidate_ids,
                set_role: "relation-types".to_string(),
                declared_semantics: CandidateSetSemantics::RelationPairs,
                ordered: false,
                parent_candidate_set_id: None,
            }],
            constraints: vec!["unannotated_pairs_are_unknown".to_string()],
            presentation_profiles: Vec::new(),
        },
        queries: vec![query],
        gold_targets: vec![GoldTarget {
            query_id: "q-docred-relations".to_string(),
            authority_record_id: authority_id.clone(),
            score_semantics: ScoreSemantics::RelationCompatibility,
            candidate_set_id: Some("cs-docred-relations".to_string()),
            probability_source: ProbabilitySourceMetadata {
                probability_source: ProbabilitySource::NoProbability,
                sample_count: None,
                annotator_count: None,
                raw_label_counts: None,
                aggregation_method: "source_relation_annotation".to_string(),
                normalization_scope: "none".to_string(),
                distribution_interpretation: DistributionInterpretation::NotApplicable,
            },
            target: TargetPayload::Relation {
                relations: relation_targets,
            },
            annotations: None,
        }],
        evidence_links,
        perturbation: None,
        authority: AuthoritySummary {
            episode_authority_class: AuthorityClass::ExternallyAnnotated,
            authority_record_ids: vec![authority_id.clone()],
            phoenix_authority_domain: false,
        },
        authority_records: vec![AuthorityRecord {
            authority_record_id: authority_id,
            authority_class: AuthorityClass::ExternallyAnnotated,
            authority_domain: AuthorityDomain::ExternalDataset,
            authority_scope: "DocRED annotated relations and evidence sentences".to_string(),
            creator_or_system: "DocRED / THUNLP".to_string(),
            source_identity: "thunlp/docred".to_string(),
            source_revision_or_snapshot: revision.to_string(),
            annotation_or_generator_protocol: "entity/relation annotations with sentence evidence"
                .to_string(),
            created_at: None,
            available_at: None,
            license_or_access_basis: Some("MIT metadata; verify upstream terms".to_string()),
            parent_authority_ids: Vec::new(),
            quality_limitations: vec![
                "positive relation annotations do not establish false for unannotated pairs"
                    .to_string(),
            ],
            lineage: Lineage {
                source_dataset_id: "thunlp/docred".to_string(),
                source_revision: revision.to_string(),
                source_split: split.to_string(),
                source_row_id: row_id.to_string(),
                upstream_dataset_id: Some("DocRED".to_string()),
                upstream_row_id: Some(row_id.to_string()),
                adapter_id: ADAPTER_ID.to_string(),
                adapter_revision: "0.2.0".to_string(),
                transformation_chain: vec![
                    "sentence_tokens_to_utf8_offsets".to_string(),
                    "vertexSet_to_entities".to_string(),
                    "labels_to_relation_targets".to_string(),
                ],
            },
        }],
        workload: WorkloadMetadata {
            query_count: 1,
            span_count: Some(mention_ids_by_entity.len() as u32),
            relation_count: Some(labels.len() as u32),
            ..WorkloadMetadata::default()
        },
        evaluation_constraints: EvaluationConstraints {
            split_regime: Some("span_relation_eval".to_string()),
            excluded_from_primary_benchmark: split == "train_distant",
            notes: vec!["unannotated relation pairs remain unknown".to_string()],
        },
    };
    episode.identity.semantic_fingerprint = fingerprint(&episode)?;
    Ok(episode)
}

fn render_sentences(sentences: &[serde_json::Value]) -> Result<RenderedSentences> {
    let mut text = String::new();
    let mut offsets = Vec::with_capacity(sentences.len());
    let mut tokens = Vec::with_capacity(sentences.len());
    for (index, sentence) in sentences.iter().enumerate() {
        let sentence_tokens: Vec<String> = sentence
            .as_array()
            .context("DocRED sentence is not a token array")?
            .iter()
            .map(|token| {
                token
                    .as_str()
                    .map(str::to_string)
                    .context("DocRED token is not a string")
            })
            .collect::<Result<_>>()?;
        if index > 0 {
            text.push(' ');
        }
        let start = text.len();
        text.push_str(&sentence_tokens.join(" "));
        let end = text.len();
        offsets.push((start, end));
        tokens.push(sentence_tokens);
    }
    Ok((text, offsets, tokens))
}

fn token_span(
    tokens: &[Vec<String>],
    sentence_offsets: &[(usize, usize)],
    sentence_id: usize,
    start_token: usize,
    end_token: usize,
) -> Result<(usize, usize, String)> {
    let sentence = tokens
        .get(sentence_id)
        .context("DocRED sent_id out of range")?;
    ensure!(
        start_token < end_token && end_token <= sentence.len(),
        "DocRED token span is invalid"
    );
    let sentence_start = sentence_offsets[sentence_id].0;
    let local_start: usize = sentence
        .iter()
        .take(start_token)
        .map(|token| token.len() + 1)
        .sum();
    let surface = sentence[start_token..end_token].join(" ");
    let start = sentence_start + local_start;
    Ok((start, start + surface.len(), surface))
}
