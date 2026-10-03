use anyhow::{Context, Result, ensure};
use blake3::Hasher;

use crate::types::{
    AuthorityClass, AuthorityDomain, AuthorityRecord, AuthoritySummary, CandidateDefinition,
    CandidateKind, CandidateSet, CandidateSetSemantics, CanonicalEpisode, ContractStatus,
    DistributionInterpretation, EvaluationConstraints, EvidenceItem, GoldTarget, Identity, Lineage,
    ObservableState, ProbabilitySource, ProbabilitySourceMetadata, Query, QueryView,
    Representation, RuntimeSchema, ScoreSemantics, State, TargetPayload, VariableVisibility,
    WorkloadMetadata,
};

#[allow(clippy::too_many_arguments)]
pub fn hard_choice_episode(
    adapter_id: &str,
    adapter_revision: &str,
    source_dataset_id: &str,
    source_revision: &str,
    source_split: &str,
    source_row_id: &str,
    text: &str,
    instruction: Option<&str>,
    label: &str,
    candidates: Vec<CandidateDefinition>,
    source_limitations: Vec<String>,
    upstream_dataset_id: Option<String>,
    upstream_row_id: Option<String>,
) -> Result<CanonicalEpisode> {
    ensure!(!text.is_empty(), "hard-choice source text is empty");
    ensure!(
        !candidates.is_empty(),
        "hard-choice candidate inventory is empty"
    );
    ensure!(
        candidates
            .iter()
            .any(|candidate| candidate.candidate_semantic_id == label),
        "label {label} is absent from candidate inventory"
    );
    let authority_id = format!("auth-{adapter_id}-{source_row_id}");
    let candidate_ids = candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect();
    let runtime_schema = RuntimeSchema {
        schema_id: format!("schema-{adapter_id}-{source_row_id}"),
        schema_family_id: format!("schema-{adapter_id}"),
        candidates,
        candidate_sets: vec![CandidateSet {
            candidate_set_id: "cs-source-choice".to_string(),
            candidate_ids,
            set_role: "choice-alternatives".to_string(),
            declared_semantics: CandidateSetSemantics::ChoiceConditional,
            ordered: false,
            parent_candidate_set_id: None,
        }],
        constraints: Vec::new(),
        presentation_profiles: Vec::new(),
    };
    let query = Query {
        query_id: "q-source-choice".to_string(),
        query_semantic_id: format!("{adapter_id}-hard-choice"),
        view: QueryView::Choice,
        instruction: instruction.map(str::to_string),
        candidate_set_id: Some("cs-source-choice".to_string()),
        argument_scope: None,
        abstention_policy: None,
        exposed_fields: vec!["name".to_string(), "description".to_string()],
    };
    let target = GoldTarget {
        query_id: query.query_id.clone(),
        authority_record_id: authority_id.clone(),
        score_semantics: ScoreSemantics::HardLabelOnly,
        candidate_set_id: query.candidate_set_id.clone(),
        probability_source: ProbabilitySourceMetadata {
            probability_source: ProbabilitySource::HardLabel,
            sample_count: Some(1),
            annotator_count: None,
            raw_label_counts: None,
            aggregation_method: "source_label".to_string(),
            normalization_scope: "none".to_string(),
            distribution_interpretation: DistributionInterpretation::NotApplicable,
        },
        target: TargetPayload::Choice {
            selected_candidate_semantic_id: Some(label.to_string()),
            distribution: None,
            other_probability: None,
            abstain_allowed: false,
        },
        annotations: None,
    };
    let lineage = Lineage {
        source_dataset_id: source_dataset_id.to_string(),
        source_revision: source_revision.to_string(),
        source_split: source_split.to_string(),
        source_row_id: source_row_id.to_string(),
        upstream_dataset_id,
        upstream_row_id,
        adapter_id: adapter_id.to_string(),
        adapter_revision: adapter_revision.to_string(),
        transformation_chain: vec![
            "source_row".to_string(),
            "hard_choice_normalization".to_string(),
        ],
    };
    let evidence_id = format!("ev-{source_row_id}");
    let authority = AuthorityRecord {
        authority_record_id: authority_id.clone(),
        authority_class: AuthorityClass::ExternallyAnnotated,
        authority_domain: AuthorityDomain::ExternalDataset,
        authority_scope: "source row target".to_string(),
        creator_or_system: source_dataset_id.to_string(),
        source_identity: source_dataset_id.to_string(),
        source_revision_or_snapshot: source_revision.to_string(),
        annotation_or_generator_protocol: "source-provided categorical label".to_string(),
        created_at: None,
        available_at: None,
        license_or_access_basis: None,
        parent_authority_ids: Vec::new(),
        quality_limitations: source_limitations,
        lineage: lineage.clone(),
    };
    let mut episode = CanonicalEpisode {
        contract: crate::types::CONTRACT_V1.to_string(),
        contract_status: ContractStatus::V1PlusProposedE02,
        identity: Identity {
            episode_id: format!("{adapter_id}-{source_row_id}"),
            world_family_id: format!("external:{source_dataset_id}"),
            world_instance_id: format!("{source_dataset_id}:{source_row_id}"),
            surface_renderer_id: format!("source-{adapter_id}"),
            paraphrase_family_id: "external-source-native".to_string(),
            perturbation_family_id: "none".to_string(),
            schema_family_id: format!("schema-{adapter_id}"),
            task_family_ids: vec!["choice".to_string()],
            domain_family_id: format!("external:{source_dataset_id}"),
            semantic_fingerprint: String::new(),
        },
        state: State {
            representation: Representation::Prose,
            observable: ObservableState {
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
            evidence_id: evidence_id.clone(),
            kind: "text".to_string(),
            content: text.to_string(),
            source_ref: format!("{source_dataset_id}:{source_row_id}"),
            available_at: None,
            character_span: Some([0, text.len()]),
        }],
        runtime_schema,
        queries: vec![query.clone()],
        gold_targets: vec![target],
        evidence_links: Vec::new(),
        perturbation: None,
        authority: AuthoritySummary {
            episode_authority_class: AuthorityClass::ExternallyAnnotated,
            authority_record_ids: vec![authority_id],
            phoenix_authority_domain: false,
        },
        authority_records: vec![authority],
        workload: WorkloadMetadata {
            query_count: 1,
            candidate_cardinality: Some(0),
            ..WorkloadMetadata::default()
        },
        evaluation_constraints: EvaluationConstraints::default(),
    };
    episode.workload.candidate_cardinality = Some(episode.runtime_schema.candidates.len() as u32);
    episode.identity.semantic_fingerprint = fingerprint(&episode)?;
    Ok(episode)
}

pub fn candidate_label(
    name: &str,
    kind: CandidateKind,
    description: Option<String>,
) -> CandidateDefinition {
    CandidateDefinition {
        candidate_id: name.to_string(),
        candidate_semantic_id: name.to_string(),
        kind,
        name: Some(name.to_string()),
        description,
        aliases: Vec::new(),
        opaque_id: None,
        parent_candidate_semantic_id: None,
        order_rank: None,
        mutually_exclusive_group_id: None,
        independent_allowed: true,
    }
}

pub fn fingerprint(episode: &CanonicalEpisode) -> Result<String, serde_json::Error> {
    let bytes = episode.semantic_content_bytes()?;
    let mut hasher = Hasher::new();
    hasher.update(&bytes);
    Ok(hasher.finalize().to_hex().to_string())
}

pub fn get_string<'a>(row: &'a serde_json::Value, key: &str) -> Result<&'a str> {
    row.get(key)
        .and_then(serde_json::Value::as_str)
        .with_context(|| format!("missing string field {key}"))
}

pub fn get_usize(row: &serde_json::Value, key: &str) -> Result<usize> {
    row.get(key)
        .and_then(serde_json::Value::as_u64)
        .map(|value| value as usize)
        .with_context(|| format!("missing integer field {key}"))
}
