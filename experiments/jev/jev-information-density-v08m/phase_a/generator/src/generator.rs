use anyhow::{Context, Result, ensure};
use jev_decision_world_v01 as world;
use serde_json::{Value, json};

use crate::families::{CandidateSpec, FamilySpec};

#[derive(Clone, Copy, Debug)]
pub struct PriorProfile {
    pub prior: [f64; 4],
    pub high_likelihood: f64,
}

const PROFILES: [PriorProfile; 4] = [
    PriorProfile {
        prior: [0.30, 0.30, 0.20, 0.20],
        high_likelihood: 0.80,
    },
    PriorProfile {
        prior: [0.32, 0.28, 0.20, 0.20],
        high_likelihood: 0.82,
    },
    PriorProfile {
        prior: [0.28, 0.32, 0.20, 0.20],
        high_likelihood: 0.78,
    },
    PriorProfile {
        prior: [0.26, 0.34, 0.20, 0.20],
        high_likelihood: 0.84,
    },
];

pub struct Triplet {
    pub exact_episodes: [world::Episode; 4],
    pub canonical_episodes: [Value; 4],
    pub certificate: Value,
    pub anchor_id: String,
    pub family_id: String,
    pub partition: String,
}

pub fn profile(index: usize) -> PriorProfile {
    PROFILES[index % PROFILES.len()]
}

pub fn template(spec: &FamilySpec, partition: &str, profile_index: usize) -> world::WorldTemplate {
    let profile = profile(profile_index);
    let family_id = family_id(spec, partition);
    let cause_names = spec
        .candidates
        .map(|candidate| candidate.suffix.to_string())
        .to_vec();
    let variables = vec![
        world::Variable {
            id: "cause".to_string(),
            role: world::VariableRole::Latent,
            kind: world::VariableKind::Categorical,
            domain: cause_names,
            ordered: false,
        },
        world::Variable {
            id: "ambient_marker".to_string(),
            role: world::VariableRole::Nuisance,
            kind: world::VariableKind::Categorical,
            domain: vec!["marker_a".to_string(), "marker_b".to_string()],
            ordered: false,
        },
        world::Variable {
            id: "neutral_marker".to_string(),
            role: world::VariableRole::Nuisance,
            kind: world::VariableKind::Categorical,
            domain: vec!["neutral_a".to_string(), "neutral_b".to_string()],
            ordered: false,
        },
    ];
    let q = profile.high_likelihood;
    let observation_likelihood = vec![q, 1.0 - q, 1.0 - q, q, 0.5, 0.5, 0.5, 0.5];
    world::WorldTemplate {
        family_id,
        template_id: format!("jev_v08m_{}_p{}", spec.slug, profile_index % PROFILES.len()),
        version: 1,
        variables,
        mechanisms: vec![
            world::Mechanism {
                target: "cause".to_string(),
                parents: Vec::new(),
                table: profile.prior.to_vec(),
            },
            world::Mechanism {
                target: "ambient_marker".to_string(),
                parents: Vec::new(),
                table: vec![0.5, 0.5],
            },
            world::Mechanism {
                target: "neutral_marker".to_string(),
                parents: Vec::new(),
                table: vec![0.5, 0.5],
            },
        ],
        constraints: Vec::new(),
        observation_channels: vec![
            world::ObservationChannel {
                id: "focus_report_channel".to_string(),
                source_variable: "cause".to_string(),
                observed_domain: vec!["+".to_string(), "-".to_string()],
                likelihood_table: observation_likelihood,
                default_visibility_probability: 1.0,
            },
            world::ObservationChannel {
                id: "independent_marker_channel".to_string(),
                source_variable: "ambient_marker".to_string(),
                observed_domain: vec!["+".to_string(), "-".to_string()],
                likelihood_table: vec![0.85, 0.15, 0.15, 0.85],
                default_visibility_probability: 1.0,
            },
            world::ObservationChannel {
                id: "neutral_marker_channel".to_string(),
                source_variable: "neutral_marker".to_string(),
                observed_domain: vec!["+".to_string(), "-".to_string()],
                likelihood_table: vec![0.82, 0.18, 0.18, 0.82],
                default_visibility_probability: 1.0,
            },
        ],
        derived_variables: Vec::new(),
    }
}

pub fn build_triplet(
    spec: &FamilySpec,
    partition: &str,
    sequence: usize,
    seed: u64,
) -> Result<Triplet> {
    let profile_index = sequence % PROFILES.len();
    let selected_profile = profile(profile_index);
    let template = template(spec, partition, profile_index);
    let anchor_id = format!("v08m-{partition}-{}-{sequence:06}", spec.slug);
    let world_seed = seed_for(seed, &anchor_id, "world");
    let sampled_world = vec![
        (world_seed % 4) as u8,
        ((world_seed >> 9) % 2) as u8,
        ((world_seed >> 17) % 2) as u8,
    ];
    let context_code = seed_for(seed, &anchor_id, "context") % 100_000;

    let base = build_episode(
        spec,
        partition,
        &anchor_id,
        "anchor",
        "+",
        "+",
        "+",
        &sampled_world,
        context_code,
        &template,
        seed,
    )?;
    let flip = build_episode(
        spec,
        partition,
        &anchor_id,
        "fact_flip",
        "-",
        "+",
        "+",
        &sampled_world,
        context_code,
        &template,
        seed,
    )?;
    let sham = build_episode(
        spec,
        partition,
        &anchor_id,
        "sham",
        "+",
        "-",
        "+",
        &sampled_world,
        context_code,
        &template,
        seed,
    )?;
    let neutral = build_episode(
        spec,
        partition,
        &anchor_id,
        "local_neutral",
        "+",
        "+",
        "-",
        &sampled_world,
        context_code,
        &template,
        seed,
    )?;
    let joint = build_episode(
        spec,
        partition,
        &anchor_id,
        "joint_nuisance",
        "+",
        "-",
        "-",
        &sampled_world,
        context_code,
        &template,
        seed,
    )?;

    let base_distribution = choice_distribution(&base);
    let flip_distribution = choice_distribution(&flip);
    let sham_distribution = choice_distribution(&sham);
    let neutral_distribution = choice_distribution(&neutral);
    let joint_distribution = choice_distribution(&joint);
    let top = |values: &[f64]| -> usize {
        values
            .iter()
            .enumerate()
            .max_by(|a, b| a.1.total_cmp(b.1))
            .unwrap()
            .0
    };
    ensure!(
        top(&base_distribution) == 0,
        "focus-high failed to select first local sibling"
    );
    ensure!(
        top(&flip_distribution) == 1,
        "focus-low failed to select second local sibling"
    );
    ensure!(
        close_distribution(&base_distribution, &sham_distribution),
        "independent sham changed exact target"
    );
    ensure!(
        close_distribution(&base_distribution, &neutral_distribution),
        "local neutral changed exact target"
    );
    ensure!(
        close_distribution(&base_distribution, &joint_distribution),
        "joint nuisance intervention changed exact target"
    );
    ensure!(
        !close_distribution(&base_distribution, &flip_distribution),
        "decision-relevant fact failed to change exact posterior"
    );

    let (focus_spans, sham_spans, neutral_spans) = spans(spec, context_code);
    let family_id = family_id(spec, partition);
    let schema_id = format!("jev-v08m-schema:{}", spec.slug);
    let mut certificate = json!({
        "protocol": "jev-information-density/v0.8m-phase-a",
        "partition": partition,
        "anchor_id": anchor_id,
        "world_id": format!("world:{anchor_id}"),
        "world_family_id": family_id,
        "schema_family_id": schema_id,
        "schema_signature": schema_signature(spec),
        "state_signature": blake3::hash(format!("{}|{}|{}|{}", template.template_id, sampled_world[0], sampled_world[1], sampled_world[2]).as_bytes()).to_hex().to_string(),
        "focus_variable": format!("{}_reading", spec.metric.replace(' ', "_")),
        "focus_evidence_id": "ev-focus",
        "focus_before_value": "+",
        "focus_after_value": "-",
        "irrelevant_variable": "ambient_marker",
        "irrelevant_evidence_id": "ev-sham",
        "sham_before_value": "+",
        "sham_after_value": "-",
        "neutral_variable": "neutral_marker",
        "neutral_evidence_id": "ev-neutral",
        "neutral_before_value": "+",
        "neutral_after_value": "-",
        "expected_label_before": spec.candidates[0].suffix,
        "expected_label_after": spec.candidates[1].suffix,
        "sham_label_before": spec.candidates[0].suffix,
        "sham_label_after": spec.candidates[0].suffix,
        "exact_target_before": base_distribution,
        "exact_target_after": flip_distribution,
        "exact_sham_target": sham_distribution,
        "exact_neutral_target": neutral_distribution,
        "exact_joint_nuisance_target": joint_distribution,
        "nuisance_axes": {
            "sham": "ambient_marker",
            "neutral": "neutral_marker",
            "independent": true
        },
        "affected_query_ids": ["q_choice"],
        "unaffected_query_ids": [],
        "sham_affected_query_ids": [],
        "sham_unaffected_query_ids": ["q_choice"],
        "unchanged_required_fields": [
            "world_instance_id", "sampled_world", "runtime_schema", "candidate_order",
            "query_set", "focus_fact_in_sham", "sham_fact_in_fact_flip", "neutral_fact_in_fact_flip", "all other context"
        ],
        "changed_surface_spans": {
            "fact_flip": {"before": [focus_spans.0, focus_spans.1], "after": [focus_spans.0, focus_spans.1]},
            "sham": {"before": [sham_spans.0, sham_spans.1], "after": [sham_spans.0, sham_spans.1]},
            "neutral": {"before": [neutral_spans.0, neutral_spans.1], "after": [neutral_spans.0, neutral_spans.1]}
        },
        "edit_magnitude": {
            "character_edit_distance": 1,
            "changed_span_count": 1,
            "changed_value_characters": {"before": 1, "after": 1},
            "treatment_equals_sham": true,
            "treatment_equals_neutral": true
        },
        "intervention_type": "single_observed_fact_value_flip_plus_two_independent_nuisance_axes",
        "hard_local_competition": true,
        "same_parent_competitor_ids": [spec.candidates[0].suffix, spec.candidates[1].suffix],
        "profile_index": profile_index,
        "prior": selected_profile.prior,
        "high_likelihood": selected_profile.high_likelihood,
        "latent_sample": {"cause_value_index": sampled_world[0], "ambient_marker_value_index": sampled_world[1]},
        "episode_ids": {
            "anchor": base.episode_id,
            "fact_flip": flip.episode_id,
            "sham": sham.episode_id,
            "neutral": neutral.episode_id
        }
    });
    let canonical_certificate = serde_json::to_vec(&certificate)?;
    certificate["certificate_hash"] =
        json!(blake3::hash(&canonical_certificate).to_hex().to_string());

    Ok(Triplet {
        exact_episodes: [base.exact, flip.exact, sham.exact, neutral.exact],
        canonical_episodes: [base.canonical, flip.canonical, sham.canonical, neutral.canonical],
        certificate,
        anchor_id,
        family_id,
        partition: partition.to_string(),
    })
}

struct BuiltEpisode {
    exact: world::Episode,
    canonical: Value,
    episode_id: String,
}

fn build_episode(
    spec: &FamilySpec,
    partition: &str,
    anchor_id: &str,
    role: &str,
    focus_value: &str,
    sham_value: &str,
    neutral_value: &str,
    sampled_world: &[u8],
    context_code: u64,
    template: &world::WorldTemplate,
    seed: u64,
) -> Result<BuiltEpisode> {
    let episode_id = format!("{anchor_id}-{role}");
    let content = render_state(spec, context_code, focus_value, sham_value, neutral_value);
    let focus_text = format!("{} reading: {}", spec.metric, focus_value);
    let sham_text = format!("Independent panel marker: {sham_value}");
    let neutral_text = format!("Maintenance status flag: {neutral_value}");
    let facts = vec![
        world::EvidenceFact {
            fact_id: "ev-focus".to_string(),
            source_variable: "cause".to_string(),
            true_value: sampled_world[0],
            visibility: world::Visibility::Visible,
            observed_value: Some(if focus_value == "+" { 0 } else { 1 }),
            channel_id: "focus_report_channel".to_string(),
        },
        world::EvidenceFact {
            fact_id: "ev-sham".to_string(),
            source_variable: "ambient_marker".to_string(),
            true_value: sampled_world[1],
            visibility: world::Visibility::Visible,
            observed_value: Some(if sham_value == "+" { 0 } else { 1 }),
            channel_id: "independent_marker_channel".to_string(),
        },
        world::EvidenceFact {
            fact_id: "ev-neutral".to_string(),
            source_variable: "neutral_marker".to_string(),
            true_value: sampled_world[2],
            visibility: world::Visibility::Visible,
            observed_value: Some(if neutral_value == "+" { 0 } else { 1 }),
            channel_id: "neutral_marker_channel".to_string(),
        },
    ];
    let evidence = world::EvidenceState {
        facts: facts.clone(),
        visible_fact_ids: vec!["ev-focus".to_string(), "ev-sham".to_string(), "ev-neutral".to_string()],
        missing_fact_ids: Vec::new(),
    };
    let query = world::Query::Choice {
        id: "q_choice".to_string(),
        variable: "cause".to_string(),
        candidate_values: vec![0, 1, 2, 3],
        mode: world::ChoiceMode::ClosedWorld,
    };
    let posterior = world::solve_exact(template, &evidence)?;
    let distribution = posterior
        .marginals
        .first()
        .context("cause marginal absent")?
        .clone();
    let probabilities = distribution
        .iter()
        .enumerate()
        .map(|(index, probability)| world::NamedProbability {
            value: index as u8,
            probability: *probability,
        })
        .collect();
    let gold = world::GoldTarget {
        query_id: "q_choice".to_string(),
        value: world::GoldValue::Choice {
            mode: world::ChoiceMode::ClosedWorld,
            probabilities,
            other_probability: 0.0,
        },
        solver: world::SolverReceipt {
            method: world::SolverMethod::ExactEnumeration,
            template_id: template.template_id.clone(),
            conditioning_evidence: evidence.visible_fact_ids.clone(),
            approximation: false,
            seed: seed_for(seed, anchor_id, role),
        },
    };
    let semantic_fingerprint = semantic_fingerprint(template, &content, &distribution);
    let parent_id = (role != "anchor").then(|| format!("{anchor_id}-anchor"));
    let (operation, affected_fact, relation) = match role {
        "fact_flip" => ("controlled_fact_flip", "ev-focus", world::ExpectedRelation::Recomputed),
        "sham" => ("controlled_sham", "ev-sham", world::ExpectedRelation::StrictInvariant),
        "local_neutral" => ("controlled_local_neutral", "ev-neutral", world::ExpectedRelation::StrictInvariant),
        "joint_nuisance" => ("controlled_joint_nuisance", "ev-sham", world::ExpectedRelation::StrictInvariant),
        _ => ("anchor", "", world::ExpectedRelation::Recomputed),
    };
    let perturbation_links = parent_id
        .as_ref()
        .map(|parent_episode_id| {
            vec![world::PerturbationLink {
                family_id: format!("contrast:{anchor_id}"),
                parent_episode_id: parent_episode_id.clone(),
                class: world::PerturbationClass::ObservationIntervention,
                operation: operation.to_string(),
                affected_fact_ids: if role == "joint_nuisance" {
                    vec!["ev-sham".to_string(), "ev-neutral".to_string()]
                } else {
                    vec![affected_fact.to_string()]
                },
                affected_variable: None,
                expected_relation: relation,
            }]
        })
        .unwrap_or_default();
    let template_ref = world::TemplateRef::from(template);
    let exact = world::Episode {
        contract: world::CONTRACT.to_string(),
        episode_id: episode_id.clone(),
        template: template_ref,
        authority: world::AuthorityClass::SyntheticControl,
        sampled_world: sampled_world.to_vec(),
        evidence_state: evidence,
        queries: vec![query],
        gold_targets: vec![gold],
        renderings: vec![world::Rendering {
            format: world::RenderFormat::Prose,
            text: content.clone(),
                source_fact_ids: vec!["ev-focus".to_string(), "ev-sham".to_string(), "ev-neutral".to_string()],
        }],
        perturbation_links,
        provenance: world::Provenance {
            generator_id: "jev-v08m-local-invariance-direction".to_string(),
            generator_version: "0.1.0".to_string(),
            seed: seed_for(seed, anchor_id, role),
            world_sample_seed: seed_for(seed, anchor_id, "world"),
            observation_seed: seed_for(seed, anchor_id, role),
            renderer_seed: seed_for(seed, anchor_id, "renderer"),
            semantic_fingerprint: semantic_fingerprint.clone(),
        },
    };
    world::validate_episode(&exact, template)
        .with_context(|| format!("v0.1 exact episode failed validation: {episode_id}"))?;

    let canonical = canonical_episode(
        spec,
        partition,
        anchor_id,
        role,
        &content,
        &focus_text,
        &sham_text,
        &neutral_text,
        &distribution,
        context_code,
        &episode_id,
        parent_id.as_deref(),
        template,
        &semantic_fingerprint,
    );
    Ok(BuiltEpisode {
        exact,
        canonical,
        episode_id,
    })
}

#[allow(clippy::too_many_arguments)]
fn canonical_episode(
    spec: &FamilySpec,
    partition: &str,
    anchor_id: &str,
    role: &str,
    content: &str,
    focus_text: &str,
    sham_text: &str,
    neutral_text: &str,
    distribution: &[f64],
    context_code: u64,
    episode_id: &str,
    parent_episode_id: Option<&str>,
    template: &world::WorldTemplate,
    semantic_fingerprint: &str,
) -> Value {
    let focus_item_start = focus_text.len().saturating_sub(1);
    let sham_item_start = sham_text.len().saturating_sub(1);
    let neutral_item_start = neutral_text.len().saturating_sub(1);
    let family_id = family_id(spec, partition);
    let schema_family_id = format!("jev-v08m-schema:{}", spec.slug);
    let schema_id = schema_family_id.clone();
    let candidate_semantics: Vec<String> = spec
        .candidates
        .iter()
        .map(|candidate| format!("{}::{}", spec.slug, candidate.suffix))
        .collect();
    let candidates: Vec<Value> = spec
        .candidates
        .iter()
        .enumerate()
        .map(|(index, candidate)| candidate_json(spec, candidate, index))
        .collect();
    let top = distribution
        .iter()
        .enumerate()
        .max_by(|a, b| a.1.total_cmp(b.1))
        .map(|(index, _)| index)
        .unwrap_or(0);
    let probability_entries: Vec<Value> = candidate_semantics
        .iter()
        .zip(distribution)
        .map(|(semantic_id, probability)| {
            json!({
                "candidate_semantic_id": semantic_id,
                "probability": probability
            })
        })
        .collect();
    let observation_values = [
        if role == "fact_flip" { "-" } else { "+" },
        if role == "sham" { "-" } else { "+" },
        if role == "local_neutral" || role == "joint_nuisance" { "-" } else { "+" },
    ];
    let focus_content = focus_text.to_string();
    let sham_content = sham_text.to_string();
    let neutral_content = neutral_text.to_string();
    let (perturbation_class, perturbation_operation, changed_evidence_ids, affected_query_ids, unaffected_query_ids) = match role {
        "fact_flip" => ("controlled_fact_flip", "replace_one_decision_relevant_observation", vec!["ev-focus"], vec!["q_choice"], Vec::<&str>::new()),
        "sham" => ("controlled_sham", "replace_one_certified_irrelevant_observation", vec!["ev-sham"], Vec::<&str>::new(), vec!["q_choice"]),
        "local_neutral" => ("controlled_local_neutral", "replace_one_certified_neutral_observation", vec!["ev-neutral"], Vec::<&str>::new(), vec!["q_choice"]),
        "joint_nuisance" => ("controlled_joint_nuisance", "replace_two_certified_irrelevant_observations", vec!["ev-sham", "ev-neutral"], Vec::<&str>::new(), vec!["q_choice"]),
        _ => ("anchor", "none", Vec::<&str>::new(), Vec::<&str>::new(), Vec::<&str>::new()),
    };
    let perturbation = parent_episode_id.map(|parent| {
        json!({
            "class": perturbation_class,
            "parent_episode_id": parent,
            "operation": perturbation_operation,
            "affected_query_ids": affected_query_ids,
            "unaffected_query_ids": unaffected_query_ids,
            "changed_evidence_ids": changed_evidence_ids,
        })
    });
    json!({
        "contract": "jev-like-decision-dataset/v1",
        "episode_id": episode_id,
        "identity": {
            "episode_id": episode_id,
            "world_family_id": family_id,
            "world_instance_id": format!("world:{anchor_id}"),
            "surface_renderer_id": "render-prose-v1",
            "paraphrase_family_id": format!("definitions:{}:v1", spec.slug),
            "perturbation_family_id": format!("contrast:{anchor_id}"),
            "schema_family_id": schema_family_id,
            "task_family_ids": ["choice_local_discrimination"],
            "domain_family_id": format!("synthetic_control:{}", spec.slug),
            "semantic_fingerprint": semantic_fingerprint,
        },
        "state": {
            "representation": "prose",
            "observable": {"content": content, "items": ["ev-focus", "ev-sham", "ev-neutral"]},
            "latent": null,
            "variables": {
                "observed": [
                    {"evidence_id":"ev-focus","value":observation_values[0]},
                    {"evidence_id":"ev-sham","value":observation_values[1]},
                    {"evidence_id":"ev-neutral","value":observation_values[2]}
                ],
                "missing": [],
                "hidden": []
            }
        },
        "evidence_items": [
            {"evidence_id":"ev-focus","kind":"text","content":focus_content,
             "source_ref":"synthetic:jev-v08m-exact-world","available_at":0,
             "character_span":[focus_item_start,focus_item_start+1]},
            {"evidence_id":"ev-sham","kind":"text","content":sham_content,
             "source_ref":"synthetic:jev-v08m-exact-world","available_at":0,
             "character_span":[sham_item_start,sham_item_start+1]}
            ,{"evidence_id":"ev-neutral","kind":"text","content":neutral_content,
             "source_ref":"synthetic:jev-v08m-exact-world","available_at":0,
             "character_span":[neutral_item_start,neutral_item_start+1]}
        ],
        "runtime_schema": {
            "schema_id": schema_id,
            "schema_family_id": schema_family_id,
            "candidates": candidates,
            "candidate_sets": [{
                "candidate_set_id":"cs-choice",
                "candidate_ids":["candidate-0","candidate-1","candidate-2","candidate-3"],
                "set_role":"choice-alternatives",
                "declared_semantics":"choice_conditional",
                "ordered":false,
                "parent_candidate_set_id":null
            }],
            "constraints": [],
            "presentation_profiles": ["name_definition"]
        },
        "queries": [{
            "query_id":"q_choice",
            "query_semantic_id":format!("jev-v08m:{}:identify-condition", spec.slug),
            "view":"choice",
            "instruction":format!("Which {} condition is best supported by the report?", spec.domain),
            "candidate_set_id":"cs-choice",
            "argument_scope":null,
            "abstention_policy":"explicit_target",
            "exposed_fields":["name","description"]
        }],
        "gold_targets": [{
            "query_id":"q_choice",
            "authority_record_id":format!("auth:{episode_id}"),
            "score_semantics":"choice_conditional",
            "candidate_set_id":"cs-choice",
            "target":{
                "selected_candidate_semantic_id":candidate_semantics[top],
                "distribution":probability_entries,
                "abstain_allowed":false
            },
            "probability_source":{
                "probability_source":"exact_generative_posterior",
                "sample_count":null,
                "annotator_count":null,
                "aggregation_method":"exact_enumeration",
                "normalization_scope":"closed_candidate_set",
                "distribution_interpretation":"posterior over finite latent cause conditioned on visible evidence"
            }
        }],
        "evidence_links": [
            {"evidence_link_id":"link-focus","target_ref":"q_choice","evidence_item_ids":["ev-focus"],"role":"support","locations":[{"evidence_id":"ev-focus","start":focus_item_start,"end":focus_item_start+1}],"required_for_target":true},
            {"evidence_link_id":"link-sham","target_ref":"q_choice","evidence_item_ids":["ev-sham"],"role":"irrelevant","locations":[{"evidence_id":"ev-sham","start":sham_item_start,"end":sham_item_start+1}],"required_for_target":false},
            {"evidence_link_id":"link-neutral","target_ref":"q_choice","evidence_item_ids":["ev-neutral"],"role":"irrelevant","locations":[{"evidence_id":"ev-neutral","start":neutral_item_start,"end":neutral_item_start+1}],"required_for_target":false}
        ],
        "perturbation": perturbation,
        "authority":{"episode_authority_class":"synthetic_control","authority_record_ids":[format!("auth:{episode_id}")],"phoenix_authority_domain":false},
        "authority_records":[{"authority_record_id":format!("auth:{episode_id}"),"authority_class":"synthetic_control","generator_id":"jev-v08m-local-invariance-direction","generator_revision":"0.1.0","prior_identity":format!("{}:p{}",template.template_id,profile_index_for(template)),"likelihood_identity":format!("{}:q{}",template.template_id,profile_index_for(template)),"posterior_method":"exact-enumeration","seed":seed_for(0,anchor_id,"record")}],
        "workload":{"candidate_cardinality":4,"branch_width":4,"state_character_count":content.chars().count(),"context_code":context_code},
        "evaluation_constraints":{"partition":partition,"family_holdout_unit":"world_family_id"}
    })
}

fn candidate_json(spec: &FamilySpec, candidate: &CandidateSpec, index: usize) -> Value {
    let semantic_id = format!("{}::{}", spec.slug, candidate.suffix);
    json!({
        "candidate_id":format!("candidate-{index}"),
        "candidate_semantic_id":semantic_id,
        "kind":"label",
        "surface":{"name":candidate.name,"description":candidate.description,"aliases":[]},
        "opaque_id":format!("Q{index:02}"),
        "parent_candidate_semantic_id":format!("{}::condition_family",spec.slug),
        "group_ids":[format!("{}::hard-local-competitors",spec.slug)],
        "order_rank":null,
        "mutually_exclusive_group_id":format!("{}::exclusive-choice",spec.slug),
        "independent_allowed":false
    })
}

fn render_state(spec: &FamilySpec, context_code: u64, focus: &str, sham: &str, neutral: &str) -> String {
    format!(
        "Asset context: {} unit {:05}.\n{} reading: {}.\nIndependent panel marker: {}.\nMaintenance status flag: {}.",
        spec.asset, context_code, spec.metric, focus, sham, neutral
    )
}

fn value_span(content: &str, line: &str, value: &str) -> Result<(usize, usize)> {
    let line_start = content
        .find(line)
        .context("rendered evidence line missing")?;
    let value_start = line_start
        + line
            .rfind(value)
            .context("evidence value missing from line")?;
    Ok((value_start, value_start + value.len()))
}

fn spans(spec: &FamilySpec, context_code: u64) -> ((usize, usize), (usize, usize), (usize, usize)) {
    let content = render_state(spec, context_code, "+", "+", "+");
    (
        value_span(&content, &format!("{} reading: +", spec.metric), "+").unwrap(),
        value_span(&content, "Independent panel marker: +", "+").unwrap(),
        value_span(&content, "Maintenance status flag: +", "+").unwrap(),
    )
}

fn choice_distribution(episode: &BuiltEpisode) -> Vec<f64> {
    match &episode.exact.gold_targets[0].value {
        world::GoldValue::Choice { probabilities, .. } => {
            probabilities.iter().map(|item| item.probability).collect()
        }
        _ => unreachable!("controlled contrast uses closed choice"),
    }
}

fn close_distribution(left: &[f64], right: &[f64]) -> bool {
    left.len() == right.len()
        && left
            .iter()
            .zip(right)
            .all(|(a, b)| (a - b).abs() <= 1.0e-12)
}

fn semantic_fingerprint(template: &world::WorldTemplate, content: &str, target: &[f64]) -> String {
    let bytes = serde_json::to_vec(&(template.template_id.as_str(), content, target)).unwrap();
    format!("blake3:{}", blake3::hash(&bytes).to_hex())
}

fn schema_signature(spec: &FamilySpec) -> String {
    let bytes = serde_json::to_vec(
        &spec
            .candidates
            .map(|item| (item.suffix, item.name, item.description)),
    )
    .unwrap();
    blake3::hash(&bytes).to_hex().to_string()
}

fn family_id(spec: &FamilySpec, partition: &str) -> String {
    format!("jev-v08m-{partition}-family:{}", spec.slug)
}

fn profile_index_for(template: &world::WorldTemplate) -> usize {
    template
        .template_id
        .rsplit('_')
        .next()
        .and_then(|s| s.strip_prefix('p'))
        .and_then(|value| value.parse().ok())
        .unwrap_or(0)
}

pub fn seed_for(seed: u64, identity: &str, role: &str) -> u64 {
    let mut hasher = blake3::Hasher::new();
    hasher.update(&seed.to_le_bytes());
    hasher.update(identity.as_bytes());
    hasher.update(role.as_bytes());
    u64::from_le_bytes(hasher.finalize().as_bytes()[..8].try_into().unwrap())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::families::{TRAIN_FAMILY_COUNT, all_families};

    #[test]
    fn exact_fact_flip_changes_local_winner_and_sham_is_invariant() {
        for spec in all_families().iter().take(TRAIN_FAMILY_COUNT) {
            for sequence in 0..16 {
                let triplet = build_triplet(spec, "train", sequence, 77).unwrap();
                let base = &triplet.exact_episodes[0];
                let flip = &triplet.exact_episodes[1];
                let sham = &triplet.exact_episodes[2];
                assert_eq!(base.sampled_world, flip.sampled_world);
                assert_eq!(base.sampled_world, sham.sampled_world);
                let d0 = choice_distribution(&BuiltEpisode {
                    exact: base.clone(),
                    canonical: triplet.canonical_episodes[0].clone(),
                    episode_id: base.episode_id.clone(),
                });
                let d1 = choice_distribution(&BuiltEpisode {
                    exact: flip.clone(),
                    canonical: triplet.canonical_episodes[1].clone(),
                    episode_id: flip.episode_id.clone(),
                });
                let ds = choice_distribution(&BuiltEpisode {
                    exact: sham.clone(),
                    canonical: triplet.canonical_episodes[2].clone(),
                    episode_id: sham.episode_id.clone(),
                });
                let argmax = |values: &[f64]| {
                    values
                        .iter()
                        .enumerate()
                        .max_by(|a, b| a.1.total_cmp(b.1))
                        .unwrap()
                        .0
                };
                assert_eq!(argmax(&d0), 0);
                assert_eq!(argmax(&d1), 1);
                assert!(close_distribution(&d0, &ds));
                assert!(!close_distribution(&d0, &d1));
            }
        }
    }

    #[test]
    fn pair_surface_and_schema_change_only_at_certified_fact() {
        let spec = all_families().remove(0);
        let triplet = build_triplet(&spec, "train", 3, 99).unwrap();
        let state = |episode: &Value| {
            episode["state"]["observable"]["content"]
                .as_str()
                .unwrap()
                .to_owned()
        };
        let anchor = state(&triplet.canonical_episodes[0]);
        let flip = state(&triplet.canonical_episodes[1]);
        let sham = state(&triplet.canonical_episodes[2]);
        let neutral = state(&triplet.canonical_episodes[3]);
        let anchor_lines: Vec<_> = anchor.lines().collect();
        let flip_lines: Vec<_> = flip.lines().collect();
        let sham_lines: Vec<_> = sham.lines().collect();
        let neutral_lines: Vec<_> = neutral.lines().collect();
        assert_eq!(anchor_lines[0], flip_lines[0]);
        assert_ne!(anchor_lines[1], flip_lines[1]);
        assert_eq!(anchor_lines[2], flip_lines[2]);
        assert_eq!(anchor_lines[0], sham_lines[0]);
        assert_eq!(anchor_lines[1], sham_lines[1]);
        assert_ne!(anchor_lines[2], sham_lines[2]);
        assert_eq!(anchor_lines[3], sham_lines[3]);
        assert_eq!(anchor_lines[0], neutral_lines[0]);
        assert_eq!(anchor_lines[1], neutral_lines[1]);
        assert_eq!(anchor_lines[2], neutral_lines[2]);
        assert_ne!(anchor_lines[3], neutral_lines[3]);
        for index in 1..4 {
            assert_eq!(
                triplet.canonical_episodes[0]["runtime_schema"],
                triplet.canonical_episodes[index]["runtime_schema"]
            );
            assert_eq!(
                triplet.canonical_episodes[0]["queries"],
                triplet.canonical_episodes[index]["queries"]
            );
            assert_eq!(
                triplet.canonical_episodes[0]["identity"]["world_instance_id"],
                triplet.canonical_episodes[index]["identity"]["world_instance_id"]
            );
        }
        for episode in &triplet.canonical_episodes {
            assert_eq!(episode["identity"]["episode_id"], episode["episode_id"]);
            assert!(episode.get("_v08i").is_none());
            assert!(episode["identity"].get("world_profile_id").is_none());
            for candidate in episode["runtime_schema"]["candidates"].as_array().unwrap() {
                assert!(candidate["surface"]["name"].as_str().is_some());
                assert!(candidate["surface"]["description"].as_str().is_some());
                assert!(candidate.get("name").is_none());
                assert!(candidate.get("description").is_none());
            }
            for item in episode["evidence_items"].as_array().unwrap() {
                let text = item["content"].as_str().unwrap().as_bytes();
                let span = item["character_span"].as_array().unwrap();
                let start = span[0].as_u64().unwrap() as usize;
                let end = span[1].as_u64().unwrap() as usize;
                assert_eq!(end - start, 1);
                assert!(matches!(text.get(start), Some(b'+') | Some(b'-')));
            }
            for link in episode["evidence_links"].as_array().unwrap() {
                let location = &link["locations"][0];
                let evidence_id = location["evidence_id"].as_str().unwrap();
                let item = episode["evidence_items"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .find(|item| item["evidence_id"] == evidence_id)
                    .unwrap();
                let text = item["content"].as_str().unwrap().as_bytes();
                let start = location["start"].as_u64().unwrap() as usize;
                let end = location["end"].as_u64().unwrap() as usize;
                assert_eq!(end - start, 1);
                assert!(matches!(text.get(start), Some(b'+') | Some(b'-')));
            }
        }
        let spans = &triplet.certificate["changed_surface_spans"];
        for edge in ["fact_flip", "sham", "neutral"] {
            let before = &spans[edge]["before"];
            let after = &spans[edge]["after"];
            assert_eq!(before[1].as_u64().unwrap() - before[0].as_u64().unwrap(), 1);
            assert_eq!(after[1].as_u64().unwrap() - after[0].as_u64().unwrap(), 1);
        }
    }

    #[test]
    fn train_and_eval_family_and_template_ids_are_disjoint() {
        let families = all_families();
        let train: std::collections::BTreeSet<_> = families[..TRAIN_FAMILY_COUNT]
            .iter()
            .map(|spec| template(spec, "train", 0).template_id)
            .collect();
        let eval: std::collections::BTreeSet<_> = families[TRAIN_FAMILY_COUNT..]
            .iter()
            .map(|spec| template(spec, "eval", 0).template_id)
            .collect();
        assert!(train.is_disjoint(&eval));
        for train_spec in &families[..TRAIN_FAMILY_COUNT] {
            for eval_spec in &families[TRAIN_FAMILY_COUNT..] {
                assert_ne!(family_id(train_spec, "train"), family_id(eval_spec, "eval"));
            }
        }
    }
}
