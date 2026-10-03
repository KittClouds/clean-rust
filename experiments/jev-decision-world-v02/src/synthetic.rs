use anyhow::{Context, Result, ensure};
use blake3::Hasher;
use jev_decision_world_v01 as v01;

use crate::types::{
    ApplicabilityEntry, AuthorityClass, AuthorityDomain, AuthorityRecord, AuthoritySummary,
    CandidateDefinition, CandidateKind, CandidateSet, CandidateSetSemantics, CanonicalEpisode,
    ContractStatus, DistributionInterpretation, EvaluationConstraints, EvidenceItem, GoldTarget,
    Identity, Lineage, ProbabilityEntry, ProbabilitySource, ProbabilitySourceMetadata, Query,
    QueryView, Representation, RuntimeSchema, ScoreSemantics, State, TargetPayload,
    VariableVisibility, WorkloadMetadata,
};

pub fn from_v01(episode: &v01::Episode, template: &v01::WorldTemplate) -> Result<CanonicalEpisode> {
    ensure!(
        episode.contract == v01::CONTRACT,
        "unexpected v0.1 episode contract"
    );
    let prose = episode
        .renderings
        .iter()
        .find(|rendering| rendering.format == v01::RenderFormat::Prose)
        .context("v0.1 episode has no prose rendering")?;
    let source = format!("synthetic:{}", episode.episode_id);
    let authority_id = format!("auth-synthetic-{}", episode.episode_id);
    let candidate_sets_and_defs = build_schema(template, &episode.queries)?;
    let (runtime_schema, query_set_ids) = candidate_sets_and_defs;
    let candidate_cardinality = runtime_schema
        .candidate_sets
        .iter()
        .map(|set| set.candidate_ids.len() as u32)
        .max();
    let queries = episode
        .queries
        .iter()
        .map(|query| build_query(query, &query_set_ids))
        .collect::<Result<Vec<_>>>()?;
    let gold_targets = episode
        .gold_targets
        .iter()
        .map(|target| {
            let query = episode
                .queries
                .iter()
                .find(|query| query.id() == target.query_id)
                .context("v0.1 gold target query disappeared")?;
            build_target(target, query, template, &runtime_schema, &authority_id)
        })
        .collect::<Result<Vec<_>>>()?;
    let evidence_items = episode
        .evidence_state
        .facts
        .iter()
        .filter(|fact| matches!(fact.visibility, v01::Visibility::Visible))
        .map(|fact| {
            let observed = fact
                .observed_value
                .context("visible v0.1 fact has no observed value")?;
            let variable = template
                .variable(&fact.source_variable)
                .context("v0.1 fact variable disappeared")?;
            Ok(EvidenceItem {
                evidence_id: fact.fact_id.clone(),
                kind: "observed_fact".to_string(),
                content: format!(
                    "{}={}",
                    fact.source_variable,
                    variable
                        .domain
                        .get(observed as usize)
                        .cloned()
                        .unwrap_or_else(|| observed.to_string())
                ),
                source_ref: source.clone(),
                available_at: None,
                character_span: None,
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let sampled_world = template
        .variables
        .iter()
        .zip(episode.sampled_world.iter())
        .map(|(variable, value)| {
            serde_json::json!({
                "variable": variable.id,
                "value_index": value,
                "value": variable.domain.get(*value as usize),
            })
        })
        .collect::<Vec<_>>();
    let visible = episode.evidence_state.visible_fact_ids.clone();
    let missing = episode.evidence_state.missing_fact_ids.clone();
    let hidden = episode
        .evidence_state
        .facts
        .iter()
        .filter(|fact| matches!(fact.visibility, v01::Visibility::Hidden))
        .map(|fact| fact.fact_id.clone())
        .collect();
    let mut result = CanonicalEpisode {
        contract: crate::types::CONTRACT_V1.to_string(),
        contract_status: ContractStatus::V1PlusProposedE02,
        identity: Identity {
            episode_id: episode.episode_id.clone(),
            world_family_id: episode.template.family_id.clone(),
            world_instance_id: episode.episode_id.clone(),
            surface_renderer_id: "synthetic-v01-prose".to_string(),
            paraphrase_family_id: format!("synthetic-{}", episode.template.template_id),
            perturbation_family_id: episode
                .perturbation_links
                .first()
                .map(|link| link.family_id.clone())
                .unwrap_or_else(|| "none".to_string()),
            schema_family_id: "synthetic-runtime-schema-v02".to_string(),
            task_family_ids: episode.queries.iter().map(query_view_name).collect(),
            domain_family_id: format!("synthetic:{}", episode.template.family_id),
            semantic_fingerprint: String::new(),
        },
        state: State {
            representation: Representation::Prose,
            observable: crate::types::ObservableState {
                content: prose.text.clone(),
                items: visible.clone(),
            },
            latent: Some(serde_json::Value::Array(sampled_world)),
            variables: VariableVisibility {
                observed: visible,
                missing,
                hidden,
            },
            structured_state: None,
        },
        evidence_items,
        runtime_schema,
        queries,
        gold_targets,
        evidence_links: Vec::new(),
        perturbation: episode
            .perturbation_links
            .first()
            .map(|link| crate::types::Perturbation {
                family_id: link.family_id.clone(),
                parent_episode_id: Some(link.parent_episode_id.clone()),
                operation: link.operation.clone(),
                class: format!("{:?}", link.class).to_lowercase(),
                expected_relation: format!("{:?}", link.expected_relation).to_lowercase(),
                affected_query_ids: Vec::new(),
                unaffected_query_ids: Vec::new(),
                alignment: None,
            }),
        authority: AuthoritySummary {
            episode_authority_class: AuthorityClass::SyntheticControl,
            authority_record_ids: vec![authority_id.clone()],
            phoenix_authority_domain: false,
        },
        authority_records: vec![AuthorityRecord {
            authority_record_id: authority_id,
            authority_class: AuthorityClass::SyntheticControl,
            authority_domain: AuthorityDomain::SyntheticControl,
            authority_scope: "exact finite Bayesian world posterior".to_string(),
            creator_or_system: "jev-decision-world-v01 adapter".to_string(),
            source_identity: source.clone(),
            source_revision_or_snapshot: episode.template.version.to_string(),
            annotation_or_generator_protocol: "exact enumeration conditioned on visible evidence"
                .to_string(),
            created_at: Some("2026-09-19".to_string()),
            available_at: None,
            license_or_access_basis: Some("local synthetic generation".to_string()),
            parent_authority_ids: Vec::new(),
            quality_limitations: vec![
                "sampled world is retained for debugging but is not the gold posterior".to_string(),
            ],
            lineage: Lineage {
                source_dataset_id: "synthetic:jev-decision-world-v01".to_string(),
                source_revision: episode.template.version.to_string(),
                source_split: "synthetic_control".to_string(),
                source_row_id: episode.episode_id.clone(),
                upstream_dataset_id: None,
                upstream_row_id: None,
                adapter_id: "synthetic_v01_to_v02".to_string(),
                adapter_revision: "0.2.0".to_string(),
                transformation_chain: vec![
                    "v01_exact_episode".to_string(),
                    "runtime_candidate_expansion".to_string(),
                    "prose_observation_projection".to_string(),
                ],
            },
        }],
        workload: WorkloadMetadata {
            query_count: episode.queries.len(),
            candidate_cardinality,
            relevant_evidence_count: Some(episode.evidence_state.visible_fact_ids.len() as u32),
            ..WorkloadMetadata::default()
        },
        evaluation_constraints: EvaluationConstraints {
            split_regime: Some("synthetic_calibration_eval".to_string()),
            excluded_from_primary_benchmark: false,
            notes: Vec::new(),
        },
    };
    result.identity.semantic_fingerprint = fingerprint(&result)?;
    Ok(result)
}

fn build_schema(
    template: &v01::WorldTemplate,
    queries: &[v01::Query],
) -> Result<(RuntimeSchema, std::collections::BTreeMap<String, String>)> {
    let mut candidates = Vec::new();
    let mut sets = Vec::new();
    let mut set_ids = std::collections::BTreeMap::new();
    for query in queries {
        let variable = template
            .variable(query.variable())
            .context("query variable disappeared")?;
        let set_id = format!("cs-{}", query.id());
        let candidate_values = match query {
            v01::Query::Choice {
                candidate_values, ..
            } => candidate_values.clone(),
            v01::Query::Proposition { value, .. } | v01::Query::Applicability { value, .. } => {
                vec![*value]
            }
            v01::Query::Ordinal { .. } | v01::Query::Abstain { .. } => (0..variable.domain.len())
                .map(|value| value as u8)
                .collect(),
        };
        let mut candidate_ids = Vec::with_capacity(candidate_values.len());
        for value in candidate_values {
            let semantic_id = semantic_value_id(&variable.id, &variable.domain, value)?;
            let candidate_id = format!("candidate-{semantic_id}");
            if !candidates.iter().any(|candidate: &CandidateDefinition| {
                candidate.candidate_semantic_id == semantic_id
            }) {
                candidates.push(CandidateDefinition {
                    candidate_id: candidate_id.clone(),
                    candidate_semantic_id: semantic_id.clone(),
                    kind: if matches!(query, v01::Query::Ordinal { .. }) {
                        CandidateKind::OrdinalScale
                    } else {
                        CandidateKind::Label
                    },
                    name: variable.domain.get(value as usize).cloned(),
                    description: Some(format!(
                        "{}={}",
                        variable.id,
                        variable
                            .domain
                            .get(value as usize)
                            .cloned()
                            .unwrap_or_else(|| value.to_string())
                    )),
                    aliases: Vec::new(),
                    opaque_id: None,
                    parent_candidate_semantic_id: None,
                    order_rank: Some(value as i32),
                    mutually_exclusive_group_id: Some(format!("group-{}", variable.id)),
                    independent_allowed: matches!(
                        query,
                        v01::Query::Applicability { .. } | v01::Query::Proposition { .. }
                    ),
                });
            }
            candidate_ids.push(candidate_id);
        }
        let semantics = match query {
            v01::Query::Choice { .. } => CandidateSetSemantics::ChoiceConditional,
            v01::Query::Applicability { .. } | v01::Query::Proposition { .. } => {
                CandidateSetSemantics::IndependentApplicability
            }
            v01::Query::Ordinal { .. } => CandidateSetSemantics::OrdinalScale,
            v01::Query::Abstain { .. } => CandidateSetSemantics::Unknown,
        };
        sets.push(CandidateSet {
            candidate_set_id: set_id.clone(),
            candidate_ids,
            set_role: format!("{}-candidates", query_view_name(query)),
            declared_semantics: semantics,
            ordered: matches!(query, v01::Query::Ordinal { .. }),
            parent_candidate_set_id: None,
        });
        set_ids.insert(query.id().to_string(), set_id);
    }
    Ok((
        RuntimeSchema {
            schema_id: "schema-synthetic-runtime-v02".to_string(),
            schema_family_id: "synthetic-runtime-schema-v02".to_string(),
            candidates,
            candidate_sets: sets,
            constraints: Vec::new(),
            presentation_profiles: Vec::new(),
        },
        set_ids,
    ))
}

fn build_query(
    query: &v01::Query,
    set_ids: &std::collections::BTreeMap<String, String>,
) -> Result<Query> {
    Ok(Query {
        query_id: query.id().to_string(),
        query_semantic_id: format!("synthetic:{}", query.variable()),
        view: match query {
            v01::Query::Proposition { .. } | v01::Query::Applicability { .. } => {
                QueryView::IndependentApplicability
            }
            v01::Query::Choice { .. } => QueryView::Choice,
            v01::Query::Ordinal { .. } => QueryView::OrdinalScore,
            v01::Query::Abstain { .. } => QueryView::Abstain,
        },
        instruction: None,
        candidate_set_id: set_ids.get(query.id()).cloned(),
        argument_scope: None,
        abstention_policy: None,
        exposed_fields: vec!["name".to_string(), "description".to_string()],
    })
}

fn build_target(
    target: &v01::GoldTarget,
    query: &v01::Query,
    template: &v01::WorldTemplate,
    schema: &RuntimeSchema,
    authority_id: &str,
) -> Result<GoldTarget> {
    let (score_semantics, payload) = match &target.value {
        v01::GoldValue::Proposition {
            true_probability, ..
        } => (
            ScoreSemantics::IndependentApplicability,
            TargetPayload::IndependentApplicability {
                candidates: vec![ApplicabilityEntry {
                    candidate_semantic_id: semantic_value_id(
                        query.variable(),
                        &template
                            .variable(query.variable())
                            .context("query variable disappeared")?
                            .domain,
                        match query {
                            v01::Query::Proposition { value, .. } => *value,
                            _ => 0,
                        },
                    )?,
                    applies: None,
                    probability: Some(*true_probability),
                }],
            },
        ),
        v01::GoldValue::IndependentApplicability { probability } => (
            ScoreSemantics::IndependentApplicability,
            TargetPayload::IndependentApplicability {
                candidates: vec![ApplicabilityEntry {
                    candidate_semantic_id: semantic_value_id(
                        query.variable(),
                        &template
                            .variable(query.variable())
                            .context("query variable disappeared")?
                            .domain,
                        match query {
                            v01::Query::Applicability { value, .. } => *value,
                            _ => 0,
                        },
                    )?,
                    applies: None,
                    probability: Some(*probability),
                }],
            },
        ),
        v01::GoldValue::Choice {
            probabilities,
            other_probability,
            ..
        } => (
            ScoreSemantics::ChoiceConditional,
            TargetPayload::Choice {
                selected_candidate_semantic_id: probabilities
                    .iter()
                    .max_by(|a, b| a.probability.total_cmp(&b.probability))
                    .map(|item| {
                        semantic_value_id(
                            query.variable(),
                            &template
                                .variable(query.variable())
                                .context("query variable disappeared")?
                                .domain,
                            item.value,
                        )
                    })
                    .transpose()?,
                distribution: Some(
                    probabilities
                        .iter()
                        .map(|item| {
                            Ok(ProbabilityEntry {
                                candidate_semantic_id: semantic_value_id(
                                    query.variable(),
                                    &template
                                        .variable(query.variable())
                                        .context("query variable disappeared")?
                                        .domain,
                                    item.value,
                                )?,
                                probability: item.probability,
                            })
                        })
                        .collect::<Result<Vec<_>>>()?,
                ),
                other_probability: Some(*other_probability),
                abstain_allowed: false,
            },
        ),
        v01::GoldValue::Ordinal {
            distribution,
            expected_value,
            ..
        } => (
            ScoreSemantics::OrdinalDistribution,
            TargetPayload::Ordinal {
                scale_id: query.variable().to_string(),
                ordered_values: (0..distribution.len() as i32).collect(),
                distribution: Some(distribution.clone()),
                expected_value: Some(*expected_value),
                interval: None,
            },
        ),
        v01::GoldValue::Abstention {
            posterior,
            abstain_recommended,
            ..
        } => (
            ScoreSemantics::AbstentionProbability,
            TargetPayload::Abstention {
                evidence_status: "posterior_answerability".to_string(),
                abstain: Some(*abstain_recommended),
                reason: None,
                distribution: Some(
                    posterior
                        .iter()
                        .enumerate()
                        .map(|(value, probability)| {
                            Ok(ProbabilityEntry {
                                candidate_semantic_id: semantic_value_id(
                                    query.variable(),
                                    &template
                                        .variable(query.variable())
                                        .context("query variable disappeared")?
                                        .domain,
                                    value as u8,
                                )?,
                                probability: *probability,
                            })
                        })
                        .collect::<Result<Vec<_>>>()?,
                ),
            },
        ),
    };
    let _ = schema;
    Ok(GoldTarget {
        query_id: target.query_id.clone(),
        authority_record_id: authority_id.to_string(),
        score_semantics,
        candidate_set_id: Some(format!("cs-{}", query.id())),
        probability_source: ProbabilitySourceMetadata {
            probability_source: ProbabilitySource::ExactGenerativePosterior,
            sample_count: Some(1),
            annotator_count: None,
            raw_label_counts: None,
            aggregation_method: "exact_enumeration".to_string(),
            normalization_scope: "query_declared".to_string(),
            distribution_interpretation: DistributionInterpretation::WorldPosterior,
        },
        target: payload,
        annotations: None,
    })
}

fn semantic_value_id(variable: &str, domain: &[String], value: u8) -> Result<String> {
    Ok(format!(
        "{}={}",
        variable,
        domain
            .get(value as usize)
            .context("value outside variable domain")?
    ))
}

fn query_view_name(query: &v01::Query) -> String {
    match query {
        v01::Query::Proposition { .. } => "independent_applicability",
        v01::Query::Applicability { .. } => "independent_applicability",
        v01::Query::Choice { .. } => "choice",
        v01::Query::Ordinal { .. } => "ordinal_score",
        v01::Query::Abstain { .. } => "abstain",
    }
    .to_string()
}

fn fingerprint(episode: &CanonicalEpisode) -> Result<String, serde_json::Error> {
    let bytes = episode.semantic_content_bytes()?;
    let mut hasher = Hasher::new();
    hasher.update(&bytes);
    Ok(hasher.finalize().to_hex().to_string())
}
