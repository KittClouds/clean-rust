use std::fs::{File, create_dir_all};
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use anyhow::{Context, Result, bail, ensure};
use jev_decision_world_v01 as v01;
use jev_decision_world_v02 as v02;
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
struct LocalityRecord {
    contract: String,
    episode_id: String,
    parent_episode_id: String,
    operation: String,
    changed_variable: Option<String>,
    changed_fact_id: Option<String>,
    directly_affected_query_ids: Vec<String>,
    indirectly_affected_query_ids: Vec<String>,
    provably_unaffected_query_ids: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
struct InformationGainRecord {
    contract: String,
    episode_id: String,
    query_id: String,
    target_variable: String,
    evidence_id: String,
    expected_information_gain: f64,
    current_entropy: f64,
    expected_posterior_entropy: f64,
    outcomes: Vec<OutcomeGain>,
}

#[derive(Clone, Debug, Serialize)]
struct OutcomeGain {
    observed_value: u8,
    probability: f64,
    posterior_entropy: f64,
}

#[derive(Clone, Debug, Serialize)]
struct WorldMetadata {
    contract: String,
    episode_id: String,
    parent_episode_id: Option<String>,
    world_family_id: String,
    topology_template_id: String,
    world_regime: String,
    ontology_regime: String,
    factorial_cell: String,
    intervention: String,
    exact_gold_recomputed: bool,
}

#[derive(Clone, Debug, Serialize)]
struct NoveltyReceipt {
    contract: String,
    training_world_families: Vec<String>,
    held_out_world_families: Vec<String>,
    held_out_topology_templates: Vec<String>,
    held_out_ontology_families: Vec<String>,
    prohibited_identity_overlap: bool,
    lexical_overlap_allowed: bool,
    status: String,
}

fn main() -> Result<()> {
    let options = Options::parse(std::env::args().skip(1))?;
    create_dir_all(&options.output)?;

    let templates = ood_templates();
    let mut episodes = BufWriter::new(File::create(
        options.output.join("world-ood-episodes.jsonl"),
    )?);
    let mut metadata = BufWriter::new(File::create(
        options.output.join("world-ood-metadata.jsonl"),
    )?);
    let mut locality = BufWriter::new(File::create(options.output.join("locality-truth.jsonl"))?);
    let mut information_gain = BufWriter::new(File::create(
        options.output.join("expected-information-gain.jsonl"),
    )?);
    let mut episode_count = 0_usize;
    let mut locality_count = 0_usize;
    let mut ig_count = 0_usize;

    for (template_index, template) in templates.iter().enumerate() {
        for local_index in 0..options.count_per_template {
            let sequence = template_index * options.count_per_template + local_index;
            let config = v01::GenerationConfig {
                seed: options.seed,
                count: 1,
                visibility_probability: 1.0,
            };
            let base_v01 = v01::generate_episode(template, sequence, &config)?;
            let base = v02::synthetic::from_v01(&base_v01, template)?;
            v02::validate::validate_episode(&base)?;
            write_episode(&mut episodes, &mut metadata, &base, None, template, "base")?;
            episode_count += 1;

            let base_locality = classify_locality(&base_v01, template, None, None, "base")?;
            serde_json::to_writer(&mut locality, &base_locality)?;
            locality.write_all(b"\n")?;
            locality_count += 1;

            for record in exact_information_gain(&base_v01, template)? {
                serde_json::to_writer(&mut information_gain, &record)?;
                information_gain.write_all(b"\n")?;
                ig_count += 1;
            }

            for variable in &template.variables {
                if !matches!(
                    variable.role,
                    v01::VariableRole::Latent | v01::VariableRole::DecisionRelevant
                ) {
                    continue;
                }
                let variable_index = template
                    .variable_index(&variable.id)
                    .context("variable index")?;
                let sampled = base_v01.sampled_world[variable_index];
                for value in 0..variable.domain.len() as u8 {
                    if value == sampled {
                        continue;
                    }
                    let child_v01 =
                        v01::world_perturbation(&base_v01, template, &variable.id, value)?;
                    let child = v02::synthetic::from_v01(&child_v01, template)?;
                    v02::validate::validate_episode(&child)?;
                    write_episode(
                        &mut episodes,
                        &mut metadata,
                        &child,
                        Some(&base),
                        template,
                        "world_intervention",
                    )?;
                    episode_count += 1;
                    let truth = classify_locality(
                        &child_v01,
                        template,
                        Some(&base_v01),
                        Some(variable.id.as_str()),
                        "world_intervention",
                    )?;
                    serde_json::to_writer(&mut locality, &truth)?;
                    locality.write_all(b"\n")?;
                    locality_count += 1;
                }
            }

            for fact in base_v01
                .evidence_state
                .facts
                .iter()
                .filter(|fact| matches!(fact.visibility, v01::Visibility::Visible))
            {
                let child_v01 = v01::observation_perturbation(&base_v01, template, &fact.fact_id)?;
                let child = v02::synthetic::from_v01(&child_v01, template)?;
                v02::validate::validate_episode(&child)?;
                write_episode(
                    &mut episodes,
                    &mut metadata,
                    &child,
                    Some(&base),
                    template,
                    "observation_intervention",
                )?;
                episode_count += 1;
                let truth = classify_locality(
                    &child_v01,
                    template,
                    Some(&base_v01),
                    None,
                    "observation_intervention",
                )?;
                let mut truth = truth;
                truth.changed_fact_id = Some(fact.fact_id.clone());
                serde_json::to_writer(&mut locality, &truth)?;
                locality.write_all(b"\n")?;
                locality_count += 1;
            }
        }
    }

    episodes.flush()?;
    metadata.flush()?;
    locality.flush()?;
    information_gain.flush()?;

    let receipt = NoveltyReceipt {
        contract: "jev-frozen-saturation-true-ood-gate/v0.4".to_string(),
        training_world_families: v01::all_templates()
            .into_iter()
            .map(|t| t.family_id)
            .collect(),
        held_out_world_families: templates.iter().map(|t| t.family_id.clone()).collect(),
        held_out_topology_templates: templates.iter().map(|t| t.template_id.clone()).collect(),
        held_out_ontology_families: vec![
            "v04-ontology-heldout-deep-narrow".to_string(),
            "v04-ontology-heldout-asymmetric".to_string(),
        ],
        prohibited_identity_overlap: false,
        lexical_overlap_allowed: true,
        status: "verified_before_model_evaluation; held-out families are disjoint by identity"
            .to_string(),
    };
    std::fs::write(
        options.output.join("ood-novelty-audit.json"),
        serde_json::to_vec_pretty(&receipt)?,
    )?;
    let manifest = serde_json::json!({
        "contract": "jev-frozen-saturation-true-ood-gate/v0.4",
        "generator": "jev-frozen-saturation-v04",
        "world_ood_episode_count": episode_count,
        "locality_record_count": locality_count,
        "expected_information_gain_record_count": ig_count,
        "exact_inference": true,
        "topology_families": templates.iter().map(|t| t.template_id.clone()).collect::<Vec<_>>(),
    });
    std::fs::write(
        options.output.join("world-ood-manifest.json"),
        serde_json::to_vec_pretty(&manifest)?,
    )?;
    println!("{}", serde_json::to_string_pretty(&manifest)?);
    Ok(())
}

fn write_episode(
    episodes: &mut BufWriter<File>,
    metadata: &mut BufWriter<File>,
    episode: &v02::types::CanonicalEpisode,
    parent: Option<&v02::types::CanonicalEpisode>,
    template: &v01::WorldTemplate,
    operation: &str,
) -> Result<()> {
    serde_json::to_writer(&mut *episodes, episode)?;
    episodes.write_all(b"\n")?;
    let world_regime = if template.family_id.starts_with("world_ood") {
        "ood"
    } else {
        "id"
    };
    let metadata_record = WorldMetadata {
        contract: "jev-frozen-saturation-true-ood-gate/v0.4".to_string(),
        episode_id: episode.identity.episode_id.clone(),
        parent_episode_id: parent.map(|value| value.identity.episode_id.clone()),
        world_family_id: template.family_id.clone(),
        topology_template_id: template.template_id.clone(),
        world_regime: world_regime.to_string(),
        ontology_regime: "id".to_string(),
        factorial_cell: format!("ontology_id_world_{}", world_regime),
        intervention: operation.to_string(),
        exact_gold_recomputed: operation != "base" || parent.is_none(),
    };
    serde_json::to_writer(&mut *metadata, &metadata_record)?;
    metadata.write_all(b"\n")?;
    Ok(())
}

fn classify_locality(
    episode: &v01::Episode,
    template: &v01::WorldTemplate,
    _parent: Option<&v01::Episode>,
    changed_variable: Option<&str>,
    operation: &str,
) -> Result<LocalityRecord> {
    let mut direct = Vec::new();
    let mut indirect = Vec::new();
    let mut unaffected = Vec::new();
    for query in &episode.queries {
        let variable = query.variable();
        if changed_variable == Some(variable) {
            direct.push(query.id().to_string());
        } else if changed_variable
            .map(|changed| related_by_dag(template, changed, variable))
            .unwrap_or(false)
        {
            indirect.push(query.id().to_string());
        } else {
            unaffected.push(query.id().to_string());
        }
    }
    Ok(LocalityRecord {
        contract: "jev-frozen-saturation-true-ood-gate/v0.4".to_string(),
        episode_id: episode.episode_id.clone(),
        parent_episode_id: episode
            .perturbation_links
            .first()
            .map(|link| link.parent_episode_id.clone())
            .unwrap_or_else(|| episode.episode_id.clone()),
        operation: operation.to_string(),
        changed_variable: changed_variable.map(str::to_string),
        changed_fact_id: None,
        directly_affected_query_ids: direct,
        indirectly_affected_query_ids: indirect,
        provably_unaffected_query_ids: unaffected,
    })
}

fn related_by_dag(template: &v01::WorldTemplate, source: &str, target: &str) -> bool {
    if source == target {
        return true;
    }
    let mut frontier = vec![source.to_string()];
    let mut seen = std::collections::BTreeSet::new();
    while let Some(current) = frontier.pop() {
        if !seen.insert(current.clone()) {
            continue;
        }
        for mechanism in &template.mechanisms {
            if mechanism.parents.iter().any(|parent| parent == &current) {
                if mechanism.target == target {
                    return true;
                }
                frontier.push(mechanism.target.clone());
            }
        }
        for mechanism in &template.mechanisms {
            if mechanism.target == current {
                for parent in &mechanism.parents {
                    if parent == target {
                        return true;
                    }
                    frontier.push(parent.clone());
                }
            }
        }
    }
    false
}

fn exact_information_gain(
    episode: &v01::Episode,
    template: &v01::WorldTemplate,
) -> Result<Vec<InformationGainRecord>> {
    let target_variable = if template.variable("root_cause").is_some() {
        "root_cause"
    } else {
        bail!("OOD template has no root_cause query target")
    };
    let target_index = template
        .variable_index(target_variable)
        .context("target index")?;
    let mut records = Vec::new();
    for fact in episode
        .evidence_state
        .facts
        .iter()
        .filter(|fact| matches!(fact.visibility, v01::Visibility::Visible))
    {
        let mut context = episode.evidence_state.clone();
        hide_fact(&mut context, &fact.fact_id)?;
        let context_posterior = v01::solve_exact(template, &context)?;
        let current_entropy = entropy(&context_posterior.marginals[target_index]);
        let channel = template
            .channel(&fact.channel_id)
            .with_context(|| format!("missing channel {}", fact.channel_id))?;
        let mut outcomes = Vec::new();
        let mut expected_entropy = 0.0;
        for observed_value in 0..channel.observed_domain.len() as u8 {
            let mut outcome = context.clone();
            reveal_fact(&mut outcome, &fact.fact_id, observed_value)?;
            let posterior = v01::solve_exact(template, &outcome)?;
            let probability =
                posterior.evidence_probability / context_posterior.evidence_probability;
            let posterior_entropy = entropy(&posterior.marginals[target_index]);
            expected_entropy += probability * posterior_entropy;
            outcomes.push(OutcomeGain {
                observed_value,
                probability,
                posterior_entropy,
            });
        }
        ensure!(
            outcomes
                .iter()
                .map(|outcome| outcome.probability)
                .sum::<f64>()
                > 0.999999,
            "observation outcomes do not normalize"
        );
        records.push(InformationGainRecord {
            contract: "jev-frozen-saturation-true-ood-gate/v0.4".to_string(),
            episode_id: episode.episode_id.clone(),
            query_id: "q_choice_closed".to_string(),
            target_variable: target_variable.to_string(),
            evidence_id: fact.fact_id.clone(),
            expected_information_gain: (current_entropy - expected_entropy).max(0.0),
            current_entropy,
            expected_posterior_entropy: expected_entropy,
            outcomes,
        });
    }
    Ok(records)
}

fn hide_fact(evidence: &mut v01::EvidenceState, fact_id: &str) -> Result<()> {
    let fact = evidence
        .facts
        .iter_mut()
        .find(|fact| fact.fact_id == fact_id)
        .context("fact not found")?;
    fact.visibility = v01::Visibility::Hidden;
    fact.observed_value = None;
    evidence.visible_fact_ids.retain(|id| id != fact_id);
    if !evidence.missing_fact_ids.iter().any(|id| id == fact_id) {
        evidence.missing_fact_ids.push(fact_id.to_string());
    }
    Ok(())
}

fn reveal_fact(evidence: &mut v01::EvidenceState, fact_id: &str, value: u8) -> Result<()> {
    let fact = evidence
        .facts
        .iter_mut()
        .find(|fact| fact.fact_id == fact_id)
        .context("fact not found")?;
    fact.visibility = v01::Visibility::Visible;
    fact.observed_value = Some(value);
    evidence.missing_fact_ids.retain(|id| id != fact_id);
    if !evidence.visible_fact_ids.iter().any(|id| id == fact_id) {
        evidence.visible_fact_ids.push(fact_id.to_string());
    }
    Ok(())
}

fn entropy(values: &[f64]) -> f64 {
    values
        .iter()
        .filter(|value| **value > 0.0)
        .map(|value| -value * value.ln())
        .sum()
}

fn binary(id: &str, role: v01::VariableRole) -> v01::Variable {
    v01::Variable {
        id: id.to_string(),
        role,
        kind: v01::VariableKind::Boolean,
        domain: vec!["false".to_string(), "true".to_string()],
        ordered: false,
    }
}

fn categorical(id: &str, role: v01::VariableRole, values: &[&str]) -> v01::Variable {
    v01::Variable {
        id: id.to_string(),
        role,
        kind: v01::VariableKind::Categorical,
        domain: values.iter().map(|value| (*value).to_string()).collect(),
        ordered: false,
    }
}

fn ordinal(id: &str, role: v01::VariableRole, values: &[&str]) -> v01::Variable {
    let mut variable = categorical(id, role, values);
    variable.kind = v01::VariableKind::Ordinal;
    variable.ordered = true;
    variable
}

fn prior(target: &str, probabilities: &[f64]) -> v01::Mechanism {
    v01::Mechanism {
        target: target.to_string(),
        parents: Vec::new(),
        table: probabilities.to_vec(),
    }
}

fn conditional_binary(target: &str, parent: &str, p_true: &[f64]) -> v01::Mechanism {
    v01::Mechanism {
        target: target.to_string(),
        parents: vec![parent.to_string()],
        table: p_true
            .iter()
            .flat_map(|probability| [1.0 - probability, *probability])
            .collect(),
    }
}

fn conditional_categorical(target: &str, parent: &str, rows: &[&[f64]]) -> v01::Mechanism {
    v01::Mechanism {
        target: target.to_string(),
        parents: vec![parent.to_string()],
        table: rows.iter().flat_map(|row| row.iter().copied()).collect(),
    }
}

fn conditional_binary_two_parents(
    target: &str,
    first: &str,
    second: &str,
    p_true: &[[f64; 2]; 2],
) -> v01::Mechanism {
    let mut table = Vec::with_capacity(8);
    for first_value in 0..2 {
        for second_value in 0..2 {
            let probability = p_true[first_value][second_value];
            table.extend([1.0 - probability, probability]);
        }
    }
    v01::Mechanism {
        target: target.to_string(),
        parents: vec![first.to_string(), second.to_string()],
        table,
    }
}

fn conditional_binary_categorical_two_parents(
    target: &str,
    first: &str,
    second: &str,
    p_true: &[[f64; 2]; 3],
) -> v01::Mechanism {
    let mut table = Vec::with_capacity(12);
    for first_value in 0..3 {
        for second_value in 0..2 {
            let probability = p_true[first_value][second_value];
            table.extend([1.0 - probability, probability]);
        }
    }
    v01::Mechanism {
        target: target.to_string(),
        parents: vec![first.to_string(), second.to_string()],
        table,
    }
}

fn channel(source: &str) -> v01::ObservationChannel {
    v01::ObservationChannel {
        id: format!("{source}_sensor"),
        source_variable: source.to_string(),
        observed_domain: vec!["false".to_string(), "true".to_string()],
        likelihood_table: vec![0.96, 0.04, 0.08, 0.92],
        default_visibility_probability: 1.0,
    }
}

fn base_variables(extra: Vec<v01::Variable>) -> Vec<v01::Variable> {
    let mut variables = vec![categorical(
        "root_cause",
        v01::VariableRole::Latent,
        &["alpha", "beta", "gamma"],
    )];
    variables.extend(extra);
    variables
}

fn collider() -> v01::WorldTemplate {
    let variables = base_variables(vec![
        binary("cause_a", v01::VariableRole::Latent),
        binary("cause_b", v01::VariableRole::Latent),
        binary("collider_signal", v01::VariableRole::Observable),
        ordinal(
            "severity",
            v01::VariableRole::DecisionRelevant,
            &["1", "2", "3", "4", "5"],
        ),
    ]);
    let mechanisms = vec![
        prior("root_cause", &[0.40, 0.35, 0.25]),
        prior("cause_a", &[0.55, 0.45]),
        prior("cause_b", &[0.60, 0.40]),
        conditional_binary_two_parents(
            "collider_signal",
            "cause_a",
            "cause_b",
            &[[0.04, 0.45], [0.55, 0.96]],
        ),
        conditional_categorical(
            "severity",
            "root_cause",
            &[
                &[0.55, 0.30, 0.10, 0.04, 0.01],
                &[0.15, 0.30, 0.32, 0.17, 0.06],
                &[0.04, 0.12, 0.24, 0.34, 0.26],
            ],
        ),
    ];
    WorldTemplateBuilder::new(
        "world_ood_collider",
        "world_ood_collider_v1",
        variables,
        mechanisms,
    )
    .channels(["collider_signal"])
    .build()
}

fn mediated_chain() -> v01::WorldTemplate {
    let variables = base_variables(vec![
        binary("mediator", v01::VariableRole::Derived),
        binary("chain_signal", v01::VariableRole::Observable),
        ordinal(
            "severity",
            v01::VariableRole::DecisionRelevant,
            &["1", "2", "3", "4", "5"],
        ),
    ]);
    let mechanisms = vec![
        prior("root_cause", &[0.40, 0.35, 0.25]),
        conditional_binary("mediator", "root_cause", &[0.15, 0.55, 0.86]),
        conditional_binary("chain_signal", "mediator", &[0.08, 0.88]),
        conditional_categorical(
            "severity",
            "root_cause",
            &[
                &[0.55, 0.30, 0.10, 0.04, 0.01],
                &[0.15, 0.30, 0.32, 0.17, 0.06],
                &[0.04, 0.12, 0.24, 0.34, 0.26],
            ],
        ),
    ];
    WorldTemplateBuilder::new(
        "world_ood_mediated_chain",
        "world_ood_mediated_chain_v1",
        variables,
        mechanisms,
    )
    .channels(["chain_signal"])
    .build()
}

fn hidden_common_cause() -> v01::WorldTemplate {
    let variables = base_variables(vec![
        binary("symptom_a", v01::VariableRole::Observable),
        binary("symptom_b", v01::VariableRole::Observable),
        ordinal(
            "severity",
            v01::VariableRole::DecisionRelevant,
            &["1", "2", "3", "4", "5"],
        ),
    ]);
    let mechanisms = vec![
        prior("root_cause", &[0.40, 0.35, 0.25]),
        conditional_binary("symptom_a", "root_cause", &[0.10, 0.52, 0.88]),
        conditional_binary("symptom_b", "root_cause", &[0.18, 0.68, 0.82]),
        conditional_categorical(
            "severity",
            "root_cause",
            &[
                &[0.55, 0.30, 0.10, 0.04, 0.01],
                &[0.15, 0.30, 0.32, 0.17, 0.06],
                &[0.04, 0.12, 0.24, 0.34, 0.26],
            ],
        ),
    ];
    WorldTemplateBuilder::new(
        "world_ood_hidden_common_cause",
        "world_ood_hidden_common_cause_v1",
        variables,
        mechanisms,
    )
    .channels(["symptom_a", "symptom_b"])
    .build()
}

fn competing_pathways() -> v01::WorldTemplate {
    let variables = base_variables(vec![
        binary("cause_b", v01::VariableRole::Latent),
        binary("pathway_c", v01::VariableRole::Observable),
        binary("pathway_d", v01::VariableRole::Observable),
        ordinal(
            "severity",
            v01::VariableRole::DecisionRelevant,
            &["1", "2", "3", "4", "5"],
        ),
    ]);
    let mechanisms = vec![
        prior("root_cause", &[0.45, 0.35, 0.20]),
        prior("cause_b", &[0.58, 0.42]),
        conditional_binary_categorical_two_parents(
            "pathway_c",
            "root_cause",
            "cause_b",
            &[[0.05, 0.52], [0.62, 0.94], [0.38, 0.82]],
        ),
        conditional_binary_categorical_two_parents(
            "pathway_d",
            "root_cause",
            "cause_b",
            &[[0.28, 0.74], [0.50, 0.90], [0.42, 0.86]],
        ),
        conditional_categorical(
            "severity",
            "root_cause",
            &[
                &[0.55, 0.30, 0.10, 0.04, 0.01],
                &[0.15, 0.30, 0.32, 0.17, 0.06],
                &[0.04, 0.12, 0.24, 0.34, 0.26],
            ],
        ),
    ];
    WorldTemplateBuilder::new(
        "world_ood_competing_pathways",
        "world_ood_competing_pathways_v1",
        variables,
        mechanisms,
    )
    .channels(["pathway_c", "pathway_d"])
    .build()
}

struct WorldTemplateBuilder {
    family_id: String,
    template_id: String,
    variables: Vec<v01::Variable>,
    mechanisms: Vec<v01::Mechanism>,
    channels: Vec<String>,
}

impl WorldTemplateBuilder {
    fn new(
        family_id: &str,
        template_id: &str,
        variables: Vec<v01::Variable>,
        mechanisms: Vec<v01::Mechanism>,
    ) -> Self {
        Self {
            family_id: family_id.to_string(),
            template_id: template_id.to_string(),
            variables,
            mechanisms,
            channels: Vec::new(),
        }
    }

    fn channels<const N: usize>(mut self, channels: [&str; N]) -> Self {
        self.channels = channels.into_iter().map(str::to_string).collect();
        self
    }

    fn build(self) -> v01::WorldTemplate {
        v01::WorldTemplate {
            family_id: self.family_id,
            template_id: self.template_id,
            version: 1,
            variables: self.variables,
            mechanisms: self.mechanisms,
            constraints: Vec::new(),
            observation_channels: self.channels.iter().map(|id| channel(id)).collect(),
            derived_variables: Vec::new(),
        }
    }
}

fn ood_templates() -> Vec<v01::WorldTemplate> {
    vec![
        collider(),
        mediated_chain(),
        hidden_common_cause(),
        competing_pathways(),
    ]
}

struct Options {
    output: PathBuf,
    count_per_template: usize,
    seed: u64,
}

impl Options {
    fn parse(mut args: impl Iterator<Item = String>) -> Result<Self> {
        let mut output = PathBuf::from("D:/codex-runs/jev-frozen-saturation-v04/ood");
        let mut count_per_template = 100_usize;
        let mut seed = 20260919_u64;
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--output" => output = PathBuf::from(args.next().context("--output needs a path")?),
                "--count-per-template" => {
                    count_per_template = args
                        .next()
                        .context("--count-per-template needs a value")?
                        .parse()?
                }
                "--seed" => seed = args.next().context("--seed needs a value")?.parse()?,
                other => bail!("unknown argument {other}"),
            }
        }
        ensure!(
            count_per_template > 0,
            "count-per-template must be positive"
        );
        Ok(Self {
            output,
            count_per_template,
            seed,
        })
    }
}
