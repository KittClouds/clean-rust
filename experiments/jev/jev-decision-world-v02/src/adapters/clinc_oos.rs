use anyhow::{Context, Result, ensure};

use super::common::{candidate_label, fingerprint};
use crate::types::{
    AuthorityClass, AuthorityDomain, AuthorityRecord, AuthoritySummary, CandidateDefinition,
    CandidateKind, CandidateSet, CandidateSetSemantics, CanonicalEpisode, ContractStatus,
    DistributionInterpretation, EvaluationConstraints, EvidenceItem, GoldTarget, Identity, Lineage,
    ProbabilitySource, ProbabilitySourceMetadata, Query, QueryView, Representation, RuntimeSchema,
    ScoreSemantics, State, TargetPayload, VariableVisibility, WorkloadMetadata,
};

pub const ADAPTER_ID: &str = "clinc_oos_v0.2";

pub fn normalize_row(
    row: &serde_json::Value,
    row_id: &str,
    revision: &str,
    split: &str,
    candidate_labels: &[String],
) -> Result<CanonicalEpisode> {
    let text = row
        .get("text")
        .and_then(serde_json::Value::as_str)
        .context("CLINC row missing text")?;
    let intent = row
        .get("intent")
        .and_then(serde_json::Value::as_str)
        .context("CLINC row missing intent")?;
    ensure!(
        !candidate_labels.is_empty(),
        "CLINC adapter requires a pinned label inventory"
    );
    ensure!(
        candidate_labels.iter().any(|candidate| candidate == intent),
        "CLINC label {intent} absent from supplied inventory"
    );
    let candidates: Vec<CandidateDefinition> = candidate_labels
        .iter()
        .map(|label| {
            candidate_label(
                label,
                if is_oos(label) {
                    CandidateKind::Oos
                } else {
                    CandidateKind::Label
                },
                None,
            )
        })
        .collect();
    let candidate_ids = candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect();
    let authority_id = format!("auth-{ADAPTER_ID}-{split}-{row_id}");
    let is_out_of_scope = is_oos(intent);
    let query = Query {
        query_id: if is_out_of_scope {
            "q-clinc-abstain"
        } else {
            "q-clinc-intent"
        }
        .to_string(),
        query_semantic_id: if is_out_of_scope {
            "clinc-oos"
        } else {
            "clinc-intent"
        }
        .to_string(),
        view: if is_out_of_scope {
            QueryView::Abstain
        } else {
            QueryView::Choice
        },
        instruction: Some("Determine the CLINC intent status.".to_string()),
        candidate_set_id: Some("cs-clinc-labels".to_string()),
        argument_scope: None,
        abstention_policy: Some("explicit_oos_label".to_string()),
        exposed_fields: vec!["name".to_string()],
    };
    let probability_source = ProbabilitySourceMetadata {
        probability_source: ProbabilitySource::HardLabel,
        sample_count: Some(1),
        annotator_count: None,
        raw_label_counts: None,
        aggregation_method: "source_label".to_string(),
        normalization_scope: "none".to_string(),
        distribution_interpretation: DistributionInterpretation::NotApplicable,
    };
    let target = if is_out_of_scope {
        GoldTarget {
            query_id: query.query_id.clone(),
            authority_record_id: authority_id.clone(),
            score_semantics: ScoreSemantics::AbstentionProbability,
            candidate_set_id: query.candidate_set_id.clone(),
            probability_source: probability_source.clone(),
            target: TargetPayload::Abstention {
                evidence_status: "out_of_scope".to_string(),
                abstain: Some(true),
                reason: Some("source OOS label".to_string()),
                distribution: None,
            },
            annotations: None,
        }
    } else {
        GoldTarget {
            query_id: query.query_id.clone(),
            authority_record_id: authority_id.clone(),
            score_semantics: ScoreSemantics::HardLabelOnly,
            candidate_set_id: query.candidate_set_id.clone(),
            probability_source: probability_source.clone(),
            target: TargetPayload::Choice {
                selected_candidate_semantic_id: Some(intent.to_string()),
                distribution: None,
                other_probability: None,
                abstain_allowed: true,
            },
            annotations: None,
        }
    };
    let lineage = Lineage {
        source_dataset_id: "clinc/oos-eval".to_string(),
        source_revision: revision.to_string(),
        source_split: split.to_string(),
        source_row_id: row_id.to_string(),
        upstream_dataset_id: Some("CLINC150".to_string()),
        upstream_row_id: Some(row_id.to_string()),
        adapter_id: ADAPTER_ID.to_string(),
        adapter_revision: "0.2.0".to_string(),
        transformation_chain: vec![
            "source_intent".to_string(),
            if is_out_of_scope {
                "oos_to_explicit_abstention".to_string()
            } else {
                "hard_intent_to_choice".to_string()
            },
        ],
    };
    let evidence_id = format!("ev-clinc-{split}-{row_id}");
    let mut episode = CanonicalEpisode {
        contract: crate::types::CONTRACT_V1.to_string(),
        contract_status: ContractStatus::V1PlusProposedE02,
        identity: Identity {
            episode_id: format!("clinc-{split}-{row_id}"),
            world_family_id: "external:clinc_oos".to_string(),
            world_instance_id: format!("clinc:{split}:{row_id}"),
            surface_renderer_id: "source-clinc-utterance".to_string(),
            paraphrase_family_id: "external-source-native".to_string(),
            perturbation_family_id: "none".to_string(),
            schema_family_id: "schema-clinc-labels".to_string(),
            task_family_ids: vec![if is_out_of_scope { "abstain" } else { "choice" }.to_string()],
            domain_family_id: "intent_oos".to_string(),
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
            source_ref: format!("clinc:{split}:{row_id}"),
            available_at: None,
            character_span: None,
        }],
        runtime_schema: RuntimeSchema {
            schema_id: "schema-clinc-labels".to_string(),
            schema_family_id: "schema-clinc-labels".to_string(),
            candidates,
            candidate_sets: vec![CandidateSet {
                candidate_set_id: "cs-clinc-labels".to_string(),
                candidate_ids,
                set_role: "intent-and-oos".to_string(),
                declared_semantics: CandidateSetSemantics::Unknown,
                ordered: false,
                parent_candidate_set_id: None,
            }],
            constraints: vec!["oos_is_not_in_scope_intent".to_string()],
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
            authority_scope: "CLINC intent/OOS label".to_string(),
            creator_or_system: "CLINC OOS".to_string(),
            source_identity: "clinc/oos-eval".to_string(),
            source_revision_or_snapshot: revision.to_string(),
            annotation_or_generator_protocol: "source intent inventory with explicit OOS partition"
                .to_string(),
            created_at: None,
            available_at: None,
            license_or_access_basis: Some("license receipt required before ingestion".to_string()),
            parent_authority_ids: Vec::new(),
            quality_limitations: vec![
                "adapter requires pinned complete candidate inventory".to_string(),
            ],
            lineage,
        }],
        workload: WorkloadMetadata {
            query_count: 1,
            candidate_cardinality: Some(candidate_labels.len() as u32),
            ..WorkloadMetadata::default()
        },
        evaluation_constraints: EvaluationConstraints {
            split_regime: Some(
                if is_out_of_scope {
                    "abstention_eval"
                } else {
                    "in_distribution_validation"
                }
                .to_string(),
            ),
            excluded_from_primary_benchmark: false,
            notes: Vec::new(),
        },
    };
    episode.identity.semantic_fingerprint = fingerprint(&episode)?;
    Ok(episode)
}

fn is_oos(label: &str) -> bool {
    matches!(
        label.to_ascii_lowercase().as_str(),
        "oos" | "out_of_scope" | "out-of-scope"
    )
}
