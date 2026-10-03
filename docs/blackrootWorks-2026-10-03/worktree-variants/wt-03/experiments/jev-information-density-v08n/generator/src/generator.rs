use anyhow::{Context, Result, anyhow, ensure};
use jev_decision_world_v01 as world;
use serde_json::{Value, json};

use crate::families::{CandidateSpec, FamilySpec};

pub const NEUTRAL_COUNT: usize = 8;
pub const MATERIALIZED_EPISODES: usize = 3 + NEUTRAL_COUNT;

#[derive(Clone, Copy, Debug)]
pub struct PriorProfile {
    pub prior: [f64; 4],
    pub high_likelihood: f64,
}

const PROFILES: [PriorProfile; 4] = [
    PriorProfile { prior: [0.30, 0.30, 0.20, 0.20], high_likelihood: 0.80 },
    PriorProfile { prior: [0.32, 0.28, 0.20, 0.20], high_likelihood: 0.82 },
    PriorProfile { prior: [0.28, 0.32, 0.20, 0.20], high_likelihood: 0.78 },
    PriorProfile { prior: [0.26, 0.34, 0.20, 0.20], high_likelihood: 0.84 },
];

pub struct Triplet {
    pub exact_episodes: [world::Episode; MATERIALIZED_EPISODES],
    pub canonical_episodes: [Value; MATERIALIZED_EPISODES],
    pub certificate: Value,
    pub anchor_id: String,
    pub family_id: String,
    pub partition: String,
}

pub fn profile(index: usize) -> PriorProfile { PROFILES[index % PROFILES.len()] }

pub fn neutral_axis_name(index: usize) -> String { format!("neutral_marker_{index}") }

pub fn neutral_axis_label(index: usize) -> String { format!("Neutral axis {index}") }

pub fn template(spec: &FamilySpec, partition: &str, profile_index: usize) -> world::WorldTemplate {
    let selected = profile(profile_index);
    let cause_names = spec.candidates.map(|candidate| candidate.suffix.to_string()).to_vec();
    let mut variables = vec![
        world::Variable { id: "cause".into(), role: world::VariableRole::Latent, kind: world::VariableKind::Categorical, domain: cause_names, ordered: false },
        world::Variable { id: "ambient_marker".into(), role: world::VariableRole::Nuisance, kind: world::VariableKind::Categorical, domain: vec!["marker_a".into(), "marker_b".into()], ordered: false },
    ];
    for index in 1..=NEUTRAL_COUNT {
        variables.push(world::Variable {
            id: neutral_axis_name(index), role: world::VariableRole::Nuisance,
            kind: world::VariableKind::Categorical,
            domain: vec![format!("neutral_{index}_a"), format!("neutral_{index}_b")], ordered: false,
        });
    }
    let q = selected.high_likelihood;
    let mut mechanisms = vec![
        world::Mechanism { target: "cause".into(), parents: Vec::new(), table: selected.prior.to_vec() },
        world::Mechanism { target: "ambient_marker".into(), parents: Vec::new(), table: vec![0.5, 0.5] },
    ];
    for index in 1..=NEUTRAL_COUNT {
        mechanisms.push(world::Mechanism { target: neutral_axis_name(index), parents: Vec::new(), table: vec![0.5, 0.5] });
    }
    let mut channels = vec![
        world::ObservationChannel { id: "focus_report_channel".into(), source_variable: "cause".into(), observed_domain: vec!["+".into(), "-".into()], likelihood_table: vec![q, 1.0 - q, 1.0 - q, q, 0.5, 0.5, 0.5, 0.5], default_visibility_probability: 1.0 },
        world::ObservationChannel { id: "independent_marker_channel".into(), source_variable: "ambient_marker".into(), observed_domain: vec!["+".into(), "-".into()], likelihood_table: vec![0.85, 0.15, 0.15, 0.85], default_visibility_probability: 1.0 },
    ];
    for index in 1..=NEUTRAL_COUNT {
        let high = 0.80 + index as f64 * 0.002;
        channels.push(world::ObservationChannel { id: format!("{}_channel", neutral_axis_name(index)), source_variable: neutral_axis_name(index), observed_domain: vec!["+".into(), "-".into()], likelihood_table: vec![high, 1.0 - high, 1.0 - high, high], default_visibility_probability: 1.0 });
    }
    world::WorldTemplate {
        family_id: family_id(spec, partition),
        template_id: format!("jev_v08n_{}_p{}", spec.slug, profile_index % PROFILES.len()),
        version: 1, variables, mechanisms, constraints: Vec::new(), observation_channels: channels, derived_variables: Vec::new(),
    }
}

pub fn build_triplet(spec: &FamilySpec, partition: &str, sequence: usize, seed: u64) -> Result<Triplet> {
    let profile_index = sequence % PROFILES.len();
    let selected = profile(profile_index);
    let template = template(spec, partition, profile_index);
    let anchor_id = format!("v08n-{partition}-{}-{sequence:06}", spec.slug);
    let world_seed = seed_for(seed, &anchor_id, "world");
    let mut sampled_world = vec![(world_seed % 4) as u8];
    for index in 0..=NEUTRAL_COUNT { sampled_world.push(((world_seed >> (9 + index * 3)) % 2) as u8); }
    let context_code = seed_for(seed, &anchor_id, "context") % 100_000;
    let plus = ["+"; NEUTRAL_COUNT];
    let minus = ["-"; NEUTRAL_COUNT];
    let base = build_episode(spec, partition, &anchor_id, "anchor", "+", "+", &plus, &sampled_world, context_code, &template, seed)?;
    let flip = build_episode(spec, partition, &anchor_id, "fact_flip", "-", "+", &plus, &sampled_world, context_code, &template, seed)?;
    let sham = build_episode(spec, partition, &anchor_id, "sham", "+", "-", &plus, &sampled_world, context_code, &template, seed)?;
    let mut neutrals = Vec::with_capacity(NEUTRAL_COUNT);
    for index in 1..=NEUTRAL_COUNT {
        let mut values = plus;
        values[index - 1] = "-";
        neutrals.push(build_episode(spec, partition, &anchor_id, &format!("neutral_{index}"), "+", "+", &values, &sampled_world, context_code, &template, seed)?);
    }
    let joint = build_episode(spec, partition, &anchor_id, "joint_nuisance", "+", "-", &minus, &sampled_world, context_code, &template, seed)?;
    let base_distribution = choice_distribution(&base);
    let flip_distribution = choice_distribution(&flip);
    let sham_distribution = choice_distribution(&sham);
    let neutral_distributions: Vec<Vec<f64>> = neutrals.iter().map(choice_distribution).collect();
    let joint_distribution = choice_distribution(&joint);
    let top = |values: &[f64]| values.iter().enumerate().max_by(|a, b| a.1.total_cmp(b.1)).unwrap().0;
    ensure!(top(&base_distribution) == 0 && top(&flip_distribution) == 1, "fact flip did not change local winner");
    ensure!(!close_distribution(&base_distribution, &flip_distribution), "fact flip did not change posterior");
    ensure!(close_distribution(&base_distribution, &sham_distribution), "sham changed exact target");
    ensure!(close_distribution(&base_distribution, &joint_distribution), "joint nuisance changed exact target");
    for (index, target) in neutral_distributions.iter().enumerate() { ensure!(close_distribution(&base_distribution, target), "neutral axis {index} changed exact target"); }
    let (focus_span, sham_span, neutral_spans) = spans(spec, context_code);
    let family_id = family_id(spec, partition);
    let mut span_map = serde_json::Map::new();
    for (index, span) in neutral_spans.iter().enumerate() { span_map.insert(format!("neutral_{}", index + 1), json!({"before":[span.0, span.1], "after":[span.0, span.1]})); }
    let mut episode_ids = vec![base.episode_id.clone(), flip.episode_id.clone(), sham.episode_id.clone()];
    episode_ids.extend(neutrals.iter().map(|episode| episode.episode_id.clone()));
    let certificate = json!({
        "protocol":"jev-information-density/v0.8n-base-v01", "partition":partition, "anchor_id":anchor_id,
        "world_id":format!("world:{anchor_id}"), "world_family_id":family_id,
        "schema_family_id":format!("jev-v08n-schema:{}", spec.slug), "schema_signature":schema_signature(spec),
        "state_signature":blake3::hash(format!("{}|{}", template.template_id, sampled_world.iter().map(|v| v.to_string()).collect::<Vec<_>>().join(",")).as_bytes()).to_hex().to_string(),
        "focus_variable":format!("{}_reading", spec.metric.replace(' ', "_")), "focus_evidence_id":"ev-focus", "focus_before_value":"+", "focus_after_value":"-",
        "sham_axis":"ambient_marker", "sham_evidence_id":"ev-sham", "sham_before_value":"+", "sham_after_value":"-",
        "neutral_candidate_count":NEUTRAL_COUNT, "neutral_axes":(1..=NEUTRAL_COUNT).map(neutral_axis_name).collect::<Vec<_>>(),
        "neutral_evidence_ids":(1..=NEUTRAL_COUNT).map(|index| format!("ev-neutral-{index}")).collect::<Vec<_>>(),
        "expected_label_before":spec.candidates[0].suffix, "expected_label_after":spec.candidates[1].suffix,
        "exact_target_before":base_distribution, "exact_target_after":flip_distribution, "exact_sham_target":sham_distribution,
        "exact_neutral_targets":neutral_distributions, "exact_joint_nuisance_target":joint_distribution,
        "nuisance_axes":{"sham":"ambient_marker", "neutral":(1..=NEUTRAL_COUNT).map(neutral_axis_name).collect::<Vec<_>>(), "independent":true, "pairwise_distinct":true},
        "changed_surface_spans":{"fact_flip":{"before":[focus_span.0,focus_span.1],"after":[focus_span.0,focus_span.1]},"sham":{"before":[sham_span.0,sham_span.1],"after":[sham_span.0,sham_span.1]},"neutrals":span_map},
        "edit_magnitude":{"changed_field_count":1,"changed_character_count":1,"changed_span_count":1,"all_neutral_magnitudes_equal":true,"sham_neutral_magnitude_equal":true},
        "latent_sample":{"cause_value_index":sampled_world[0],"ambient_marker_value_index":sampled_world[1],"neutral_marker_value_indices":sampled_world[2..].to_vec()},
        "episode_ids":{"anchor":episode_ids[0],"fact_flip":episode_ids[1],"sham":episode_ids[2],"neutrals":episode_ids[3..].to_vec()},
        "intervention_type":"single_observed_fact_flip_plus_eight_independent_nuisance_axes", "profile_index":profile_index, "prior":selected.prior, "high_likelihood":selected.high_likelihood,
    });
    let mut certificate = certificate;
    certificate["certificate_hash"] = json!(blake3::hash(&serde_json::to_vec(&certificate)?).to_hex().to_string());
    let mut exact = vec![base.exact, flip.exact, sham.exact];
    let mut canonical = vec![base.canonical, flip.canonical, sham.canonical];
    for neutral in neutrals { exact.push(neutral.exact); canonical.push(neutral.canonical); }
    Ok(Triplet {
        exact_episodes: exact.try_into().map_err(|_| anyhow!("exact materialized count drift"))?,
        canonical_episodes: canonical.try_into().map_err(|_| anyhow!("canonical materialized count drift"))?,
        certificate, anchor_id, family_id, partition: partition.to_string(),
    })
}

struct BuiltEpisode { exact: world::Episode, canonical: Value, episode_id: String }

fn build_episode(spec: &FamilySpec, partition: &str, anchor_id: &str, role: &str, focus: &str, sham: &str, neutral_values: &[&str; NEUTRAL_COUNT], sampled_world: &[u8], context_code: u64, template: &world::WorldTemplate, seed: u64) -> Result<BuiltEpisode> {
    let episode_id = format!("{anchor_id}-{role}");
    let content = render_state(spec, context_code, focus, sham, neutral_values);
    let mut facts = vec![
        world::EvidenceFact { fact_id:"ev-focus".into(), source_variable:"cause".into(), true_value:sampled_world[0], visibility:world::Visibility::Visible, observed_value:Some(if focus == "+" { 0 } else { 1 }), channel_id:"focus_report_channel".into() },
        world::EvidenceFact { fact_id:"ev-sham".into(), source_variable:"ambient_marker".into(), true_value:sampled_world[1], visibility:world::Visibility::Visible, observed_value:Some(if sham == "+" { 0 } else { 1 }), channel_id:"independent_marker_channel".into() },
    ];
    for index in 1..=NEUTRAL_COUNT {
        facts.push(world::EvidenceFact { fact_id:format!("ev-neutral-{index}"), source_variable:neutral_axis_name(index), true_value:sampled_world[index + 1], visibility:world::Visibility::Visible, observed_value:Some(if neutral_values[index - 1] == "+" { 0 } else { 1 }), channel_id:format!("{}_channel", neutral_axis_name(index)) });
    }
    let visible: Vec<String> = std::iter::once("ev-focus".into()).chain(std::iter::once("ev-sham".into())).chain((1..=NEUTRAL_COUNT).map(|i| format!("ev-neutral-{i}"))).collect();
    let evidence = world::EvidenceState { facts, visible_fact_ids:visible.clone(), missing_fact_ids:Vec::new() };
    let query = world::Query::Choice { id:"q_choice".into(), variable:"cause".into(), candidate_values:vec![0,1,2,3], mode:world::ChoiceMode::ClosedWorld };
    let posterior = world::solve_exact(template, &evidence)?;
    let distribution = posterior.marginals.first().context("cause marginal absent")?.clone();
    let probabilities = distribution.iter().enumerate().map(|(index, probability)| world::NamedProbability { value:index as u8, probability:*probability }).collect();
    let gold = world::GoldTarget { query_id:"q_choice".into(), value:world::GoldValue::Choice { mode:world::ChoiceMode::ClosedWorld, probabilities, other_probability:0.0 }, solver:world::SolverReceipt { method:world::SolverMethod::ExactEnumeration, template_id:template.template_id.clone(), conditioning_evidence:evidence.visible_fact_ids.clone(), approximation:false, seed:seed_for(seed, anchor_id, role) } };
    let fingerprint = semantic_fingerprint(template, &content, &distribution);
    let parent = (role != "anchor").then(|| format!("{anchor_id}-anchor"));
    let (operation, affected, relation) = if role == "fact_flip" { ("controlled_fact_flip".to_string(), vec!["ev-focus".to_string()], world::ExpectedRelation::Recomputed) } else if role == "sham" { ("controlled_sham".to_string(), vec!["ev-sham".to_string()], world::ExpectedRelation::StrictInvariant) } else if let Some(index) = role.strip_prefix("neutral_") { (format!("controlled_local_neutral_axis_{index}"), vec![format!("ev-neutral-{index}")], world::ExpectedRelation::StrictInvariant) } else if role == "joint_nuisance" { ("controlled_joint_nuisance".to_string(), std::iter::once("ev-sham".to_string()).chain((1..=NEUTRAL_COUNT).map(|i| format!("ev-neutral-{i}"))).collect(), world::ExpectedRelation::StrictInvariant) } else { ("anchor".into(), Vec::new(), world::ExpectedRelation::Recomputed) };
    let perturbation_links = parent.as_ref().map(|parent_episode_id| vec![world::PerturbationLink { family_id:format!("contrast:{anchor_id}"), parent_episode_id:parent_episode_id.clone(), class:world::PerturbationClass::ObservationIntervention, operation, affected_fact_ids:affected, affected_variable:None, expected_relation:relation }]).unwrap_or_default();
    let exact = world::Episode { contract:world::CONTRACT.into(), episode_id:episode_id.clone(), template:world::TemplateRef::from(template), authority:world::AuthorityClass::SyntheticControl, sampled_world:sampled_world.to_vec(), evidence_state:evidence, queries:vec![query], gold_targets:vec![gold], renderings:vec![world::Rendering { format:world::RenderFormat::Prose, text:content.clone(), source_fact_ids:visible.clone() }], perturbation_links, provenance:world::Provenance { generator_id:"jev-v08n-invariant-geometry-basis".into(), generator_version:"0.1.0".into(), seed:seed_for(seed,anchor_id,role), world_sample_seed:seed_for(seed,anchor_id,"world"), observation_seed:seed_for(seed,anchor_id,role), renderer_seed:seed_for(seed,anchor_id,"renderer"), semantic_fingerprint:fingerprint.clone() } };
    world::validate_episode(&exact, template).with_context(|| format!("exact episode failed validation: {episode_id}"))?;
    let canonical = canonical_episode(spec, partition, anchor_id, role, &content, &distribution, context_code, &episode_id, parent.as_deref(), template, &fingerprint, focus, sham, neutral_values)?;
    Ok(BuiltEpisode { exact, canonical, episode_id })
}

fn canonical_episode(spec: &FamilySpec, partition: &str, anchor_id: &str, role: &str, content: &str, distribution: &[f64], context_code: u64, episode_id: &str, parent: Option<&str>, template: &world::WorldTemplate, fingerprint: &str, focus: &str, sham: &str, neutral_values: &[&str; NEUTRAL_COUNT]) -> Result<Value> {
    let focus_text = format!("{} reading: {focus}", spec.metric);
    let sham_text = format!("Independent panel marker: {sham}");
    let neutral_texts: Vec<String> = (1..=NEUTRAL_COUNT).map(|i| format!("{}: {}", neutral_axis_label(i), neutral_values[i - 1])).collect();
    let focus_start = value_span(&focus_text, focus)?;
    let sham_start = value_span(&sham_text, sham)?;
    let neutral_starts: Vec<(usize,usize)> = neutral_texts.iter().zip(neutral_values).map(|(line, value)| value_span(line, value)).collect::<Result<_>>()?;
    let semantics: Vec<String> = spec.candidates.iter().map(|candidate| format!("{}::{}", spec.slug, candidate.suffix)).collect();
    let candidates: Vec<Value> = spec.candidates.iter().enumerate().map(|(i, c)| candidate_json(spec, c, i)).collect();
    let top = distribution.iter().enumerate().max_by(|a,b| a.1.total_cmp(b.1)).map(|x|x.0).unwrap_or(0);
    let probability_entries: Vec<Value> = semantics.iter().zip(distribution).map(|(id,p)| json!({"candidate_semantic_id":id,"probability":p})).collect();
    let observed: Vec<Value> = std::iter::once(json!({"evidence_id":"ev-focus","value":focus}))
        .chain(std::iter::once(json!({"evidence_id":"ev-sham","value":sham})))
        .chain((1..=NEUTRAL_COUNT).map(|i| json!({"evidence_id":format!("ev-neutral-{i}"),"value":neutral_values[i-1]}))).collect();
    let mut evidence_items = vec![
        json!({"evidence_id":"ev-focus","kind":"text","content":focus_text,"source_ref":"synthetic:jev-v08n-exact-world","available_at":0,"character_span":[focus_start.0,focus_start.1]}),
        json!({"evidence_id":"ev-sham","kind":"text","content":sham_text,"source_ref":"synthetic:jev-v08n-exact-world","available_at":0,"character_span":[sham_start.0,sham_start.1]}),
    ];
    for (i, text) in neutral_texts.iter().enumerate() { evidence_items.push(json!({"evidence_id":format!("ev-neutral-{}",i+1),"kind":"text","content":text,"source_ref":"synthetic:jev-v08n-exact-world","available_at":0,"character_span":[neutral_starts[i].0,neutral_starts[i].1]})); }
    let evidence_links: Vec<Value> = vec![json!({"evidence_link_id":"link-focus","target_ref":"q_choice","evidence_item_ids":["ev-focus"],"role":"support","locations":[{"evidence_id":"ev-focus","start":focus_start.0,"end":focus_start.1}],"required_for_target":true}),json!({"evidence_link_id":"link-sham","target_ref":"q_choice","evidence_item_ids":["ev-sham"],"role":"irrelevant","locations":[{"evidence_id":"ev-sham","start":sham_start.0,"end":sham_start.1}],"required_for_target":false})].into_iter().chain((1..=NEUTRAL_COUNT).map(|i| json!({"evidence_link_id":format!("link-neutral-{i}"),"target_ref":"q_choice","evidence_item_ids":[format!("ev-neutral-{i}")],"role":"irrelevant","locations":[{"evidence_id":format!("ev-neutral-{i}"),"start":neutral_starts[i-1].0,"end":neutral_starts[i-1].1}],"required_for_target":false}))).collect();
    let perturbation = parent.map(|parent_episode_id| json!({"parent_episode_id":parent_episode_id,"class":if role=="fact_flip" {"controlled_fact_flip"} else if role=="sham" {"controlled_sham"} else if role.starts_with("neutral_") {"controlled_local_neutral_axis"} else {"controlled_joint_nuisance"},"role":role}));
    Ok(json!({
        "contract":"jev-like-decision-dataset/v1","episode_id":episode_id,
        "identity":{"episode_id":episode_id,"world_family_id":family_id(spec,partition),"world_instance_id":format!("world:{anchor_id}"),"surface_renderer_id":"render-prose-v1","paraphrase_family_id":format!("definitions:{}:v1",spec.slug),"perturbation_family_id":format!("contrast:{anchor_id}"),"schema_family_id":format!("jev-v08n-schema:{}",spec.slug),"task_family_ids":["choice_local_discrimination"],"domain_family_id":format!("synthetic_control:{}",spec.slug),"semantic_fingerprint":fingerprint},
        "state":{"representation":"prose","observable":{"content":content,"items":(0..=NEUTRAL_COUNT+1).map(|i|if i==0 {"ev-focus".to_string()} else if i==1 {"ev-sham".to_string()} else {format!("ev-neutral-{}",i-1)}).collect::<Vec<_>>()},"latent":null,"variables":{"observed":observed,"missing":[],"hidden":[]}},
        "evidence_items":evidence_items,
        "runtime_schema":{"schema_id":format!("jev-v08n-schema:{}",spec.slug),"schema_family_id":format!("jev-v08n-schema:{}",spec.slug),"candidates":candidates,"candidate_sets":[{"candidate_set_id":"cs-choice","candidate_ids":["candidate-0","candidate-1","candidate-2","candidate-3"],"set_role":"choice-alternatives","declared_semantics":"choice_conditional","ordered":false,"parent_candidate_set_id":null}],"constraints":[],"presentation_profiles":["name_definition"]},
        "queries":[{"query_id":"q_choice","query_semantic_id":format!("jev-v08n:{}:identify-condition",spec.slug),"view":"choice","instruction":format!("Which {} condition is best supported by the report?",spec.domain),"candidate_set_id":"cs-choice","argument_scope":null,"abstention_policy":"explicit_target","exposed_fields":["name","description"]}],
        "gold_targets":[{"query_id":"q_choice","authority_record_id":format!("auth:{episode_id}"),"score_semantics":"choice_conditional","candidate_set_id":"cs-choice","target":{"selected_candidate_semantic_id":semantics[top],"distribution":probability_entries,"abstain_allowed":false},"probability_source":{"probability_source":"exact_generative_posterior","sample_count":null,"annotator_count":null,"aggregation_method":"exact_enumeration","normalization_scope":"closed_candidate_set","distribution_interpretation":"posterior over finite latent cause conditioned on visible evidence"}}],
        "evidence_links":evidence_links,"perturbation":perturbation,"authority":{"episode_authority_class":"synthetic_control","authority_record_ids":[format!("auth:{episode_id}")],"phoenix_authority_domain":false},
        "authority_records":[{"authority_record_id":format!("auth:{episode_id}"),"authority_class":"synthetic_control","generator_id":"jev-v08n-invariant-geometry-basis","generator_revision":"0.1.0","prior_identity":format!("{}:p{}",template.template_id,profile_index_for(template)),"likelihood_identity":format!("{}:q{}",template.template_id,profile_index_for(template)),"posterior_method":"exact-enumeration","seed":seed_for(0,anchor_id,"record")}],
        "workload":{"candidate_cardinality":4,"branch_width":4,"state_character_count":content.chars().count(),"context_code":context_code},"evaluation_constraints":{"partition":partition,"family_holdout_unit":"world_family_id"}
    }))
}

fn candidate_json(spec: &FamilySpec, candidate: &CandidateSpec, index: usize) -> Value {
    json!({"candidate_id":format!("candidate-{index}"),"candidate_semantic_id":format!("{}::{}",spec.slug,candidate.suffix),"kind":"label","surface":{"name":candidate.name,"description":candidate.description,"aliases":[]},"opaque_id":format!("Q{index:02}"),"parent_candidate_semantic_id":format!("{}::condition_family",spec.slug),"group_ids":[format!("{}::hard-local-competitors",spec.slug)],"order_rank":null,"mutually_exclusive_group_id":format!("{}::exclusive-choice",spec.slug),"independent_allowed":false})
}

fn render_state(spec: &FamilySpec, context_code: u64, focus: &str, sham: &str, neutral_values: &[&str; NEUTRAL_COUNT]) -> String {
    let mut lines = vec![format!("Asset context: {} unit {:05}.", spec.asset, context_code), format!("{} reading: {}.", spec.metric, focus), format!("Independent panel marker: {}.", sham)];
    for index in 1..=NEUTRAL_COUNT { lines.push(format!("{}: {}.", neutral_axis_label(index), neutral_values[index - 1])); }
    lines.join("\n")
}

fn value_span(line: &str, value: &str) -> Result<(usize, usize)> {
    let start = line.rfind(value).context("evidence value missing")?;
    Ok((start, start + value.len()))
}

fn spans(spec: &FamilySpec, context_code: u64) -> ((usize,usize),(usize,usize),Vec<(usize,usize)>) {
    let content = render_state(spec, context_code, "+", "+", &["+"; NEUTRAL_COUNT]);
    let lines: Vec<&str> = content.lines().collect();
    let focus = value_span(lines[1], "+").unwrap();
    let sham = value_span(lines[2], "+").unwrap();
    let mut neutral = Vec::new();
    for line in lines.iter().skip(3) { neutral.push(value_span(line, "+").unwrap()); }
    let prefix_focus = lines[0].len() + 1;
    let prefix_sham = prefix_focus + lines[1].len() + 1;
    let focus = (prefix_focus + focus.0, prefix_focus + focus.1);
    let sham = (prefix_sham + sham.0, prefix_sham + sham.1);
    let mut offset = prefix_sham + lines[2].len() + 1;
    let mut absolute = Vec::new();
    for (line, span) in lines.iter().skip(3).zip(neutral) { absolute.push((offset + span.0, offset + span.1)); offset += line.len() + 1; }
    (focus, sham, absolute)
}

fn choice_distribution(episode: &BuiltEpisode) -> Vec<f64> {
    match &episode.exact.gold_targets[0].value { world::GoldValue::Choice { probabilities, .. } => probabilities.iter().map(|p| p.probability).collect(), _ => panic!("choice target expected") }
}

fn close_distribution(left: &[f64], right: &[f64]) -> bool { left.len() == right.len() && left.iter().zip(right).all(|(a,b)| (a-b).abs() <= 1.0e-12) }

fn semantic_fingerprint(template: &world::WorldTemplate, content: &str, target: &[f64]) -> String { let mut hasher = blake3::Hasher::new(); hasher.update(template.template_id.as_bytes()); hasher.update(content.as_bytes()); for value in target { hasher.update(&value.to_le_bytes()); } format!("blake3:{}", hasher.finalize().to_hex()) }

fn schema_signature(spec: &FamilySpec) -> String { blake3::hash(format!("{}|{}|choice|4", spec.slug, spec.domain).as_bytes()).to_hex().to_string() }

fn profile_index_for(template: &world::WorldTemplate) -> usize { template.template_id.rsplit('_').next().and_then(|s|s.strip_prefix('p')).and_then(|v|v.parse().ok()).unwrap_or(0) }

fn family_id(spec: &FamilySpec, partition: &str) -> String { format!("jev-v08n-{partition}-family:{}", spec.slug) }

pub fn seed_for(seed: u64, identity: &str, role: &str) -> u64 { let mut hasher = blake3::Hasher::new(); hasher.update(&seed.to_le_bytes()); hasher.update(identity.as_bytes()); hasher.update(role.as_bytes()); u64::from_le_bytes(hasher.finalize().as_bytes()[..8].try_into().unwrap()) }
