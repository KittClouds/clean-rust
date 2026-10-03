use std::collections::BTreeMap;

use anyhow::{Context, Result, ensure};

use super::common::{candidate_label, fingerprint};
use crate::types::{
    ApplicabilityEntry, AuthorityClass, AuthorityDomain, AuthorityRecord, AuthoritySummary,
    CandidateKind, CandidateSet, CandidateSetSemantics, CanonicalEpisode, ContractStatus,
    DistributionInterpretation, EvaluationConstraints, EvidenceItem, GoldTarget, Identity, Lineage,
    ProbabilitySource, ProbabilitySourceMetadata, Query, QueryView, Representation, RuntimeSchema,
    ScoreSemantics, State, TargetPayload, VariableVisibility, WorkloadMetadata,
};

pub const ADAPTER_ID: &str = "go_emotions_raw_v0.2";

pub const EMOTIONS: &[&str] = &[
    "admiration",
    "amusement",
    "anger",
    "annoyance",
    "approval",
    "caring",
    "confusion",
    "curiosity",
    "desire",
    "disappointment",
    "disapproval",
    "disgust",
    "embarrassment",
    "excitement",
    "fear",
    "gratitude",
    "grief",
    "joy",
    "love",
    "nervousness",
    "optimism",
    "pride",
    "realization",
    "relief",
    "remorse",
    "sadness",
    "surprise",
    "neutral",
];

pub fn normalize_group(
    rows: &[serde_json::Value],
    revision: &str,
    split: &str,
) -> Result<Vec<CanonicalEpisode>> {
    let mut grouped: BTreeMap<String, Vec<&serde_json::Value>> = BTreeMap::new();
    for row in rows {
        let id = row
            .get("id")
            .and_then(serde_json::Value::as_str)
            .context("GoEmotions row missing id")?;
        grouped.entry(id.to_string()).or_default().push(row);
    }
    grouped
        .into_iter()
        .map(|(id, rows)| normalize_item(&id, rows, revision, split))
        .collect()
}

fn normalize_item(
    id: &str,
    rows: Vec<&serde_json::Value>,
    revision: &str,
    split: &str,
) -> Result<CanonicalEpisode> {
    ensure!(!rows.is_empty(), "GoEmotions group is empty");
    let text = rows[0]
        .get("text")
        .and_then(serde_json::Value::as_str)
        .context("GoEmotions row missing text")?;
    let mut counts = vec![0_u32; EMOTIONS.len()];
    let mut annotations = Vec::with_capacity(rows.len());
    for row in &rows {
        let labels: Vec<String> = EMOTIONS
            .iter()
            .filter(|emotion| row.get(**emotion).and_then(serde_json::Value::as_i64) == Some(1))
            .map(|emotion| (*emotion).to_string())
            .collect();
        for (index, emotion) in EMOTIONS.iter().enumerate() {
            if labels.iter().any(|label| label == emotion) {
                counts[index] += 1;
            }
        }
        let annotator_id = row
            .get("rater_id")
            .and_then(serde_json::Value::as_i64)
            .map(|value| format!("rater-{value}"));
        annotations.push(crate::types::Annotation {
            annotator_id,
            labels,
            source_label: None,
        });
    }
    let annotator_count = rows.len() as u32;
    let candidates = EMOTIONS
        .iter()
        .map(|emotion| {
            candidate_label(
                emotion,
                CandidateKind::Label,
                Some(format!("The text expresses {emotion}.")),
            )
        })
        .collect::<Vec<_>>();
    let candidates_ids = candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect();
    let authority_id = format!("auth-{ADAPTER_ID}-{id}");
    let query = Query {
        query_id: "q-emotions".to_string(),
        query_semantic_id: "emotion-independent-applicability".to_string(),
        view: QueryView::IndependentApplicability,
        instruction: Some("Which emotion labels apply independently to this text?".to_string()),
        candidate_set_id: Some("cs-emotions".to_string()),
        argument_scope: None,
        abstention_policy: None,
        exposed_fields: vec!["name".to_string(), "description".to_string()],
    };
    let candidates_target = EMOTIONS
        .iter()
        .enumerate()
        .map(|(index, emotion)| ApplicabilityEntry {
            candidate_semantic_id: (*emotion).to_string(),
            applies: Some(counts[index] * 2 >= annotator_count),
            probability: Some(counts[index] as f64 / annotator_count as f64),
        })
        .collect();
    let target = GoldTarget {
        query_id: query.query_id.clone(),
        authority_record_id: authority_id.clone(),
        score_semantics: ScoreSemantics::IndependentApplicability,
        candidate_set_id: query.candidate_set_id.clone(),
        probability_source: ProbabilitySourceMetadata {
            probability_source: ProbabilitySource::EmpiricalAnnotatorDistribution,
            sample_count: Some(annotator_count as u64),
            annotator_count: Some(annotator_count),
            raw_label_counts: Some(
                EMOTIONS
                    .iter()
                    .enumerate()
                    .map(|(index, emotion)| ((*emotion).to_string(), counts[index] as u64))
                    .collect(),
            ),
            aggregation_method: "normalized_vote_counts".to_string(),
            normalization_scope: "annotator_label_inventory".to_string(),
            distribution_interpretation: DistributionInterpretation::HumanOpinionFrequency,
        },
        target: TargetPayload::IndependentApplicability {
            candidates: candidates_target,
        },
        annotations: Some(annotations),
    };
    let lineage = Lineage {
        source_dataset_id: "google-research-datasets/go_emotions".to_string(),
        source_revision: revision.to_string(),
        source_split: split.to_string(),
        source_row_id: id.to_string(),
        upstream_dataset_id: Some("GoEmotions-original".to_string()),
        upstream_row_id: Some(id.to_string()),
        adapter_id: ADAPTER_ID.to_string(),
        adapter_revision: "0.2.0".to_string(),
        transformation_chain: vec![
            "raw_rater_rows".to_string(),
            "group_by_item_id".to_string(),
            "vote_counts_to_frequencies".to_string(),
        ],
    };
    let evidence_id = format!("ev-go-emotions-{id}");
    let mut episode = CanonicalEpisode {
        contract: crate::types::CONTRACT_V1.to_string(),
        contract_status: ContractStatus::V1PlusProposedE02,
        identity: Identity {
            episode_id: format!("go-emotions-{id}"),
            world_family_id: "external:go_emotions".to_string(),
            world_instance_id: format!("go_emotions:{id}"),
            surface_renderer_id: "source-go-emotions-raw".to_string(),
            paraphrase_family_id: "external-source-native".to_string(),
            perturbation_family_id: "none".to_string(),
            schema_family_id: "schema-emotions-28".to_string(),
            task_family_ids: vec![
                "independent_applicability".to_string(),
                "human_uncertainty".to_string(),
            ],
            domain_family_id: "emotion".to_string(),
            semantic_fingerprint: String::new(),
        },
        state: State {
            representation: Representation::Prose,
            observable: crate::types::ObservableState {
                content: text.to_string(),
                items: vec![evidence_id.clone()],
            },
            latent: None,
            variables: VariableVisibility {
                observed: vec![evidence_id.clone()],
                missing: Vec::new(),
                hidden: Vec::new(),
            },
            structured_state: None,
        },
        evidence_items: vec![EvidenceItem {
            evidence_id,
            kind: "text".to_string(),
            content: text.to_string(),
            source_ref: format!("go_emotions:{id}"),
            available_at: None,
            character_span: None,
        }],
        runtime_schema: RuntimeSchema {
            schema_id: "schema-emotions-28".to_string(),
            schema_family_id: "schema-emotions-28".to_string(),
            candidates,
            candidate_sets: vec![CandidateSet {
                candidate_set_id: "cs-emotions".to_string(),
                candidate_ids: candidates_ids,
                set_role: "independent-labels".to_string(),
                declared_semantics: CandidateSetSemantics::IndependentApplicability,
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
            authority_scope: "rater-level emotion annotations".to_string(),
            creator_or_system: "Google Research GoEmotions".to_string(),
            source_identity: "google-research-datasets/go_emotions".to_string(),
            source_revision_or_snapshot: revision.to_string(),
            annotation_or_generator_protocol: "one raw row per rater/item annotation".to_string(),
            created_at: None,
            available_at: None,
            license_or_access_basis: Some("Apache-2.0 metadata".to_string()),
            parent_authority_ids: Vec::new(),
            quality_limitations: vec![
                "frequencies measure human label agreement, not latent emotion probability"
                    .to_string(),
            ],
            lineage,
        }],
        workload: WorkloadMetadata {
            query_count: 1,
            candidate_cardinality: Some(EMOTIONS.len() as u32),
            label_density: Some(
                counts
                    .iter()
                    .map(|count| *count as f64 / annotator_count as f64)
                    .sum::<f64>()
                    / EMOTIONS.len() as f64,
            ),
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
