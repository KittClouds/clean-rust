use anyhow::{Context, Result, ensure};

use super::common::fingerprint;
use crate::types::{
    Annotation, AuthorityClass, AuthorityDomain, AuthorityRecord, AuthoritySummary,
    CandidateDefinition, CandidateKind, CandidateSet, CandidateSetSemantics, CanonicalEpisode,
    ContractStatus, DistributionInterpretation, EvaluationConstraints, EvidenceItem, GoldTarget,
    Identity, Lineage, ProbabilitySource, ProbabilitySourceMetadata, Query, QueryView,
    Representation, RuntimeSchema, ScoreSemantics, State, TargetPayload, VariableVisibility,
    WorkloadMetadata,
};

pub const ADAPTER_ID: &str = "chaos_nli_v0.2";

pub fn normalize_row(
    row: &serde_json::Value,
    row_id: &str,
    revision: &str,
    split: &str,
) -> Result<CanonicalEpisode> {
    let uid = row
        .get("uid")
        .and_then(serde_json::Value::as_str)
        .unwrap_or(row_id);
    let example = row.get("example").context("ChaosNLI row missing example")?;
    let premise = example
        .get("premise")
        .and_then(serde_json::Value::as_str)
        .context("ChaosNLI example missing premise")?;
    let hypothesis = example
        .get("hypothesis")
        .and_then(serde_json::Value::as_str)
        .context("ChaosNLI example missing hypothesis")?;
    let counts = row
        .get("label_count")
        .and_then(serde_json::Value::as_array)
        .context("ChaosNLI row missing label_count")?;
    ensure!(
        counts.len() == 3,
        "ChaosNLI v0.2 adapter expects E/N/C counts"
    );
    let counts: Vec<u64> = counts
        .iter()
        .map(|value| {
            value
                .as_u64()
                .context("ChaosNLI label_count is not integer")
        })
        .collect::<Result<_>>()?;
    let total: u64 = counts.iter().sum();
    ensure!(total > 0, "ChaosNLI row has zero annotation count");
    let labels = ["entailment", "neutral", "contradiction"];
    let distribution: Vec<crate::types::ProbabilityEntry> = labels
        .iter()
        .zip(counts.iter())
        .map(|(label, count)| crate::types::ProbabilityEntry {
            candidate_semantic_id: (*label).to_string(),
            probability: *count as f64 / total as f64,
        })
        .collect();
    let selected = row
        .get("majority_label")
        .and_then(serde_json::Value::as_str)
        .and_then(|label| match label {
            "e" => Some("entailment"),
            "n" => Some("neutral"),
            "c" => Some("contradiction"),
            _ => None,
        });
    let candidates = labels
        .iter()
        .map(|label| CandidateDefinition {
            candidate_id: (*label).to_string(),
            candidate_semantic_id: (*label).to_string(),
            kind: CandidateKind::Label,
            name: Some((*label).to_string()),
            description: None,
            aliases: Vec::new(),
            opaque_id: None,
            parent_candidate_semantic_id: None,
            order_rank: None,
            mutually_exclusive_group_id: Some("nli-choice".to_string()),
            independent_allowed: false,
        })
        .collect();
    let authority_id = format!("auth-{ADAPTER_ID}-{uid}");
    let text = format!("Premise: {premise}\nHypothesis: {hypothesis}");
    let query = Query {
        query_id: "q-chaos-nli".to_string(),
        query_semantic_id: "nli-human-opinion-distribution".to_string(),
        view: QueryView::Choice,
        instruction: Some("Which NLI label best describes the premise and hypothesis?".to_string()),
        candidate_set_id: Some("cs-nli".to_string()),
        argument_scope: None,
        abstention_policy: None,
        exposed_fields: vec!["name".to_string()],
    };
    let target = GoldTarget {
        query_id: query.query_id.clone(),
        authority_record_id: authority_id.clone(),
        score_semantics: ScoreSemantics::ChoiceConditional,
        candidate_set_id: query.candidate_set_id.clone(),
        probability_source: ProbabilitySourceMetadata {
            probability_source: ProbabilitySource::EmpiricalAnnotatorDistribution,
            sample_count: Some(total),
            annotator_count: Some(total as u32),
            raw_label_counts: Some(
                labels
                    .iter()
                    .zip(counts.iter())
                    .map(|(label, count)| ((*label).to_string(), *count))
                    .collect(),
            ),
            aggregation_method: "normalized_vote_counts".to_string(),
            normalization_scope: "annotator_label_inventory".to_string(),
            distribution_interpretation: DistributionInterpretation::HumanOpinionFrequency,
        },
        target: TargetPayload::Choice {
            selected_candidate_semantic_id: selected.map(str::to_string),
            distribution: Some(distribution),
            other_probability: Some(0.0),
            abstain_allowed: false,
        },
        annotations: row
            .get("old_labels")
            .and_then(serde_json::Value::as_array)
            .map(|old_labels| {
                old_labels
                    .iter()
                    .filter_map(|label| label.as_str())
                    .map(|label| Annotation {
                        annotator_id: None,
                        labels: vec![label.to_string()],
                        source_label: Some(label.to_string()),
                    })
                    .collect()
            }),
    };
    let lineage = Lineage {
        source_dataset_id: "ChaosNLI".to_string(),
        source_revision: revision.to_string(),
        source_split: split.to_string(),
        source_row_id: uid.to_string(),
        upstream_dataset_id: example
            .get("source")
            .and_then(serde_json::Value::as_str)
            .map(str::to_string),
        upstream_row_id: Some(uid.to_string()),
        adapter_id: ADAPTER_ID.to_string(),
        adapter_revision: "0.2.0".to_string(),
        transformation_chain: vec![
            "chaos_jsonl".to_string(),
            "label_count_to_distribution".to_string(),
        ],
    };
    let mut episode = CanonicalEpisode {
        contract: crate::types::CONTRACT_V1.to_string(),
        contract_status: ContractStatus::V1PlusProposedE02,
        identity: Identity {
            episode_id: format!("chaos-nli-{uid}"),
            world_family_id: "external:ChaosNLI".to_string(),
            world_instance_id: format!("ChaosNLI:{uid}"),
            surface_renderer_id: "source-chaos-nli".to_string(),
            paraphrase_family_id: "external-source-native".to_string(),
            perturbation_family_id: "none".to_string(),
            schema_family_id: "schema-nli".to_string(),
            task_family_ids: vec!["choice".to_string(), "human_uncertainty".to_string()],
            domain_family_id: "nli".to_string(),
            semantic_fingerprint: String::new(),
        },
        state: State {
            representation: Representation::Prose,
            observable: crate::types::ObservableState {
                content: text.clone(),
                items: vec!["ev-chaos-text".to_string()],
            },
            latent: None,
            variables: VariableVisibility {
                observed: vec!["ev-chaos-text".to_string()],
                missing: Vec::new(),
                hidden: Vec::new(),
            },
            structured_state: None,
        },
        evidence_items: vec![EvidenceItem {
            evidence_id: "ev-chaos-text".to_string(),
            kind: "text".to_string(),
            content: text,
            source_ref: format!("ChaosNLI:{uid}"),
            available_at: None,
            character_span: None,
        }],
        runtime_schema: RuntimeSchema {
            schema_id: "schema-nli".to_string(),
            schema_family_id: "schema-nli".to_string(),
            candidates,
            candidate_sets: vec![CandidateSet {
                candidate_set_id: "cs-nli".to_string(),
                candidate_ids: vec![
                    "entailment".to_string(),
                    "neutral".to_string(),
                    "contradiction".to_string(),
                ],
                set_role: "nli-alternatives".to_string(),
                declared_semantics: CandidateSetSemantics::ChoiceConditional,
                ordered: false,
                parent_candidate_set_id: None,
            }],
            constraints: Vec::new(),
            presentation_profiles: Vec::new(),
        },
        queries: vec![query],
        gold_targets: vec![target],
        evidence_links: Vec::new(),
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
            authority_scope: "human opinion distribution".to_string(),
            creator_or_system: "ChaosNLI".to_string(),
            source_identity: "easonnie/ChaosNLI".to_string(),
            source_revision_or_snapshot: revision.to_string(),
            annotation_or_generator_protocol: "100-annotation collective judgment protocol"
                .to_string(),
            created_at: None,
            available_at: None,
            license_or_access_basis: Some("verify upstream CC BY-NC terms".to_string()),
            parent_authority_ids: Vec::new(),
            quality_limitations: vec!["human disagreement is not a world posterior".to_string()],
            lineage,
        }],
        workload: WorkloadMetadata {
            query_count: 1,
            candidate_cardinality: Some(3),
            ..WorkloadMetadata::default()
        },
        evaluation_constraints: EvaluationConstraints {
            split_regime: Some("human_uncertainty_eval".to_string()),
            excluded_from_primary_benchmark: false,
            notes: Vec::new(),
        },
    };
    episode.identity.semantic_fingerprint = fingerprint(&episode)?;
    Ok(episode)
}
