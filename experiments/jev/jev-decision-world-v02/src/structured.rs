use anyhow::{Context, Result, ensure};
use blake3::Hasher;

use crate::candidates::{entity_runtime_schema, relation_runtime_schema};
use crate::types::{
    ApplicabilityEntry, AuthorityClass, AuthorityDomain, AuthorityRecord, AuthoritySummary,
    CanonicalEpisode, ContractStatus, DistributionInterpretation, EntityRecord,
    EvaluationConstraints, EvidenceItem, EvidenceLink, EvidenceLocation, GoldTarget, Identity,
    Lineage, MentionRecord, ProbabilitySource, ProbabilitySourceMetadata, Query, QueryView,
    RelationPolarity, RelationTarget, Representation, RuntimeSchema, ScoreSemantics,
    SemanticRelation, SpanTarget, State, StructuredState, TargetPayload, VariableVisibility,
    WorkloadMetadata,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StructuredRenderer {
    MaraFirst,
    OrionFirst,
}

pub fn structured_span_relation_episode(renderer: StructuredRenderer) -> Result<CanonicalEpisode> {
    let text = match renderer {
        StructuredRenderer::MaraFirst => "Mara still had the audit key assigned to Orion.",
        StructuredRenderer::OrionFirst => "Orion's audit key was still possessed by Mara.",
    };
    let renderer_id = match renderer {
        StructuredRenderer::MaraFirst => "structured-prose-mara-first-v1",
        StructuredRenderer::OrionFirst => "structured-prose-orion-first-v1",
    };
    let person = mention(text, "person_17", "person", "Mara", "mention-person")?;
    let credential = mention(
        text,
        "credential_3",
        "credential",
        "audit key",
        "mention-credential",
    )?;
    let system = mention(text, "system_4", "system", "Orion", "mention-system")?;
    ensure!(
        [
            person.character_start..person.character_end,
            credential.character_start..credential.character_end,
            system.character_start..system.character_end
        ]
        .windows(2)
        .all(|pair| pair[0].end <= pair[1].start || pair[1].end <= pair[0].start),
        "structured mentions overlap"
    );
    let entities = vec![
        EntityRecord {
            entity_semantic_id: "person_17".to_string(),
            type_semantic_id: "person".to_string(),
            canonical_name: "Mara".to_string(),
            mentions: vec![person.clone()],
        },
        EntityRecord {
            entity_semantic_id: "credential_3".to_string(),
            type_semantic_id: "credential".to_string(),
            canonical_name: "audit key".to_string(),
            mentions: vec![credential.clone()],
        },
        EntityRecord {
            entity_semantic_id: "system_4".to_string(),
            type_semantic_id: "system".to_string(),
            canonical_name: "Orion".to_string(),
            mentions: vec![system.clone()],
        },
    ];
    let semantic_relations = vec![
        SemanticRelation {
            relation_instance_id: "rel-possesses-1".to_string(),
            relation_semantic_id: "possesses".to_string(),
            head_entity_id: "person_17".to_string(),
            tail_entity_id: "credential_3".to_string(),
            direction: "directed".to_string(),
            polarity: RelationPolarity::Holds,
        },
        SemanticRelation {
            relation_instance_id: "rel-belongs-1".to_string(),
            relation_semantic_id: "belongs_to".to_string(),
            head_entity_id: "credential_3".to_string(),
            tail_entity_id: "system_4".to_string(),
            direction: "directed".to_string(),
            polarity: RelationPolarity::Holds,
        },
    ];
    let runtime_schema = merge_structured_schema();
    let type_query = Query {
        query_id: "q-span-types".to_string(),
        query_semantic_id: "entity-type-compatibility".to_string(),
        view: QueryView::SpanType,
        instruction: Some("Which runtime types apply to the canonical mentions?".to_string()),
        candidate_set_id: Some("cs-entity-types".to_string()),
        argument_scope: Some(crate::types::ArgumentScope {
            span_ids: vec![
                person.mention_id.clone(),
                credential.mention_id.clone(),
                system.mention_id.clone(),
            ],
            entity_ids: vec![
                "person_17".to_string(),
                "credential_3".to_string(),
                "system_4".to_string(),
            ],
            relation_direction: None,
        }),
        abstention_policy: None,
        exposed_fields: vec!["name".to_string(), "description".to_string()],
    };
    let relation_query = Query {
        query_id: "q-relations".to_string(),
        query_semantic_id: "possesses-compatibility".to_string(),
        view: QueryView::Relation,
        instruction: Some(
            "Which runtime relation holds between the selected arguments?".to_string(),
        ),
        candidate_set_id: Some("cs-relations".to_string()),
        argument_scope: Some(crate::types::ArgumentScope {
            span_ids: vec![person.mention_id.clone(), credential.mention_id.clone()],
            entity_ids: vec!["person_17".to_string(), "credential_3".to_string()],
            relation_direction: Some("directed".to_string()),
        }),
        abstention_policy: None,
        exposed_fields: vec!["name".to_string(), "description".to_string()],
    };
    let authority_id = format!("auth-structured-{renderer_id}");
    let probability_source = ProbabilitySourceMetadata {
        probability_source: ProbabilitySource::ExactGenerativePosterior,
        sample_count: Some(1),
        annotator_count: None,
        raw_label_counts: None,
        aggregation_method: "exact_factorization".to_string(),
        normalization_scope: "declared_label_inventory".to_string(),
        distribution_interpretation: DistributionInterpretation::WorldPosterior,
    };
    let type_target = GoldTarget {
        query_id: type_query.query_id.clone(),
        authority_record_id: authority_id.clone(),
        score_semantics: ScoreSemantics::SpanTypeCompatibility,
        candidate_set_id: type_query.candidate_set_id.clone(),
        probability_source: probability_source.clone(),
        target: TargetPayload::SpanType {
            spans: vec![
                span_target(&person, "person", [0.96, 0.02, 0.02]),
                span_target(&credential, "credential", [0.02, 0.96, 0.02]),
                span_target(&system, "system", [0.02, 0.02, 0.96]),
            ],
        },
        annotations: None,
    };
    let relation_probability = posterior_from_binary_world(0.60, 0.95, 0.10);
    let relation_target = GoldTarget {
        query_id: relation_query.query_id.clone(),
        authority_record_id: authority_id.clone(),
        score_semantics: ScoreSemantics::RelationCompatibility,
        candidate_set_id: relation_query.candidate_set_id.clone(),
        probability_source,
        target: TargetPayload::Relation {
            relations: vec![RelationTarget {
                relation_instance_id: "rel-possesses-1".to_string(),
                head_span_id: person.mention_id.clone(),
                tail_span_id: credential.mention_id.clone(),
                candidate_semantic_id: "possesses".to_string(),
                direction: "directed".to_string(),
                polarity: RelationPolarity::Holds,
                probability: Some(relation_probability),
            }],
        },
        annotations: None,
    };
    let source_ref = format!("synthetic:structured-v0.2:{renderer_id}");
    let evidence = EvidenceItem {
        evidence_id: "ev-structured-text".to_string(),
        kind: "text".to_string(),
        content: text.to_string(),
        source_ref: source_ref.clone(),
        available_at: Some(0),
        character_span: Some([0, text.len()]),
    };
    let structured_state = StructuredState {
        offset_unit: "utf8_byte".to_string(),
        entities,
        semantic_relations,
    };
    let mut episode = CanonicalEpisode {
        contract: crate::types::CONTRACT_V1.to_string(),
        contract_status: ContractStatus::V1PlusProposedE01E02,
        identity: Identity {
            episode_id: format!("structured-span-relation-{renderer_id}"),
            world_family_id: "structured_entity_relation_v02".to_string(),
            world_instance_id: "structured-world-001".to_string(),
            surface_renderer_id: renderer_id.to_string(),
            paraphrase_family_id: "structured-paraphrase-001".to_string(),
            perturbation_family_id: "structured-renderer-001".to_string(),
            schema_family_id: "structured-schema-v02".to_string(),
            task_family_ids: vec!["span_type".to_string(), "relation".to_string()],
            domain_family_id: "synthetic_structured_control".to_string(),
            semantic_fingerprint: String::new(),
        },
        state: State {
            representation: Representation::Prose,
            observable: crate::types::ObservableState {
                content: text.to_string(),
                items: vec![evidence.evidence_id.clone()],
            },
            latent: Some(serde_json::json!({
                "person_17": {"type": "person", "possesses": "credential_3"},
                "credential_3": {"type": "credential", "belongs_to": "system_4"},
                "system_4": {"type": "system"}
            })),
            variables: VariableVisibility {
                observed: vec!["structured_text".to_string()],
                missing: Vec::new(),
                hidden: vec!["relation_latent_noise".to_string()],
            },
            structured_state: Some(structured_state),
        },
        evidence_items: vec![evidence],
        runtime_schema,
        queries: vec![type_query, relation_query],
        gold_targets: vec![type_target, relation_target],
        evidence_links: vec![EvidenceLink {
            evidence_link_id: "link-structured-text".to_string(),
            target_ref: "q-span-types".to_string(),
            evidence_item_ids: vec!["ev-structured-text".to_string()],
            role: "support".to_string(),
            locations: vec![EvidenceLocation {
                evidence_id: "ev-structured-text".to_string(),
                start: 0,
                end: text.len(),
            }],
            required_for_target: false,
        }],
        perturbation: None,
        authority: AuthoritySummary {
            episode_authority_class: AuthorityClass::SyntheticControl,
            authority_record_ids: vec![authority_id.clone()],
            phoenix_authority_domain: false,
        },
        authority_records: vec![AuthorityRecord {
            authority_record_id: authority_id,
            authority_class: AuthorityClass::SyntheticControl,
            authority_domain: AuthorityDomain::SyntheticControl,
            authority_scope: "synthetic structured control".to_string(),
            creator_or_system: "jev-decision-world-v02".to_string(),
            source_identity: source_ref,
            source_revision_or_snapshot: "generator-v0.2.0".to_string(),
            annotation_or_generator_protocol:
                "finite binary relation channel plus deterministic entity types".to_string(),
            created_at: Some("2026-09-19".to_string()),
            available_at: Some("0".to_string()),
            license_or_access_basis: Some("local synthetic generation".to_string()),
            parent_authority_ids: Vec::new(),
            quality_limitations: vec!["structured_state is proposed E01 extension".to_string()],
            lineage: Lineage {
                source_dataset_id: "synthetic_structured_v02".to_string(),
                source_revision: "generator-v0.2.0".to_string(),
                source_split: "synthetic_control".to_string(),
                source_row_id: renderer_id.to_string(),
                upstream_dataset_id: None,
                upstream_row_id: None,
                adapter_id: "synthetic_structured".to_string(),
                adapter_revision: "0.2.0".to_string(),
                transformation_chain: vec![
                    "latent_entities".to_string(),
                    "controlled_renderer".to_string(),
                ],
            },
        }],
        workload: WorkloadMetadata {
            query_count: 2,
            span_count: Some(3),
            relation_count: Some(1),
            ..WorkloadMetadata::default()
        },
        evaluation_constraints: EvaluationConstraints {
            split_regime: Some("span_relation_eval".to_string()),
            excluded_from_primary_benchmark: true,
            notes: vec!["proposed structured_state extension".to_string()],
        },
    };
    episode.identity.semantic_fingerprint = fingerprint(&episode)?;
    Ok(episode)
}

fn merge_structured_schema() -> RuntimeSchema {
    let entity = entity_runtime_schema();
    let relation = relation_runtime_schema();
    RuntimeSchema {
        schema_id: "schema-structured-v02".to_string(),
        schema_family_id: "structured-schema-v02".to_string(),
        candidates: entity
            .candidates
            .into_iter()
            .chain(relation.candidates)
            .collect(),
        candidate_sets: entity
            .candidate_sets
            .into_iter()
            .chain(relation.candidate_sets)
            .collect(),
        constraints: entity
            .constraints
            .into_iter()
            .chain(relation.constraints)
            .collect(),
        presentation_profiles: entity.presentation_profiles,
    }
}

fn mention(
    text: &str,
    entity_id: &str,
    type_id: &str,
    surface: &str,
    mention_id: &str,
) -> Result<MentionRecord> {
    let start = text
        .find(surface)
        .with_context(|| format!("surface {surface} missing from renderer"))?;
    Ok(MentionRecord {
        mention_id: mention_id.to_string(),
        entity_semantic_id: entity_id.to_string(),
        character_start: start,
        character_end: start + surface.len(),
        surface: surface.to_string(),
        type_semantic_id: type_id.to_string(),
    })
}

fn span_target(mention: &MentionRecord, semantic_id: &str, probabilities: [f64; 3]) -> SpanTarget {
    let types = ["person", "credential", "system"];
    SpanTarget {
        span_id: mention.mention_id.clone(),
        start: mention.character_start,
        end: mention.character_end,
        type_targets: types
            .into_iter()
            .zip(probabilities)
            .map(|(candidate_semantic_id, probability)| ApplicabilityEntry {
                candidate_semantic_id: candidate_semantic_id.to_string(),
                applies: Some(candidate_semantic_id == semantic_id),
                probability: Some(probability),
            })
            .collect(),
    }
}

fn posterior_from_binary_world(
    prior_holds: f64,
    positive_if_holds: f64,
    positive_if_not: f64,
) -> f64 {
    let numerator = prior_holds * positive_if_holds;
    numerator / (numerator + (1.0 - prior_holds) * positive_if_not)
}

fn fingerprint(episode: &CanonicalEpisode) -> Result<String, serde_json::Error> {
    let bytes = episode.semantic_content_bytes()?;
    let mut hasher = Hasher::new();
    hasher.update(&bytes);
    Ok(hasher.finalize().to_hex().to_string())
}
