use anyhow::{Context, Result, bail, ensure};
use blake3::Hasher;
use wide::f32x8;

use crate::exact::{entropy, targets_from_queries};
use crate::types::{
    AuthorityClass, CONTRACT, ChoiceMode, Episode, EvidenceFact, EvidenceState, ExpectedRelation,
    GoldValue, PerturbationClass, PerturbationLink, Provenance, Query, RenderFormat, Rendering,
    TemplateRef, Visibility, WorldTemplate,
};
use crate::validate::validate_episode;

#[derive(Clone, Debug)]
pub struct GenerationConfig {
    pub seed: u64,
    pub count: usize,
    pub visibility_probability: f64,
}

impl Default for GenerationConfig {
    fn default() -> Self {
        Self {
            seed: 0x4a_45_56_00_01,
            count: 1_000,
            visibility_probability: 0.80,
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct Rng(u64);

impl Rng {
    fn new(seed: u64) -> Self {
        Self(if seed == 0 {
            0x9e37_79b9_7f4a_7c15
        } else {
            seed
        })
    }

    fn next_u64(&mut self) -> u64 {
        let mut value = self.0;
        value ^= value << 13;
        value ^= value >> 7;
        value ^= value << 17;
        self.0 = value;
        value
    }

    fn next_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1_u64 << 53) as f64
    }

    fn choose(&mut self, probabilities: &[f64]) -> Result<u8> {
        let draw = self.next_f64();
        let mut cumulative = 0.0;
        for (index, probability) in probabilities.iter().copied().enumerate() {
            cumulative += probability;
            if draw < cumulative || index + 1 == probabilities.len() {
                return u8::try_from(index).context("domain exceeds u8");
            }
        }
        bail!("cannot sample from empty probability row")
    }
}

pub fn generate_episode(
    template: &WorldTemplate,
    sequence: usize,
    config: &GenerationConfig,
) -> Result<Episode> {
    ensure!(
        (0.0..=1.0).contains(&config.visibility_probability),
        "visibility probability outside [0,1]"
    );
    crate::validate::validate_template(template)?;
    let world_seed = mix_seed(config.seed, sequence as u64, 0x77);
    let observation_seed = mix_seed(config.seed, sequence as u64, 0x88);
    let renderer_seed = mix_seed(config.seed, sequence as u64, 0x99);
    let sampled_world = sample_world(template, world_seed, None)?;
    let evidence_state = observe(
        template,
        &sampled_world,
        observation_seed,
        config.visibility_probability,
        None,
    )?;
    build_episode(
        template,
        BuildInputs {
            sequence,
            seed: config.seed,
            world_sample_seed: world_seed,
            observation_seed,
            renderer_seed,
            sampled_world,
            evidence_state,
        },
    )
}

struct BuildInputs {
    sequence: usize,
    seed: u64,
    world_sample_seed: u64,
    observation_seed: u64,
    renderer_seed: u64,
    sampled_world: Vec<u8>,
    evidence_state: EvidenceState,
}

fn build_episode(template: &WorldTemplate, inputs: BuildInputs) -> Result<Episode> {
    let BuildInputs {
        sequence,
        seed,
        world_sample_seed,
        observation_seed,
        renderer_seed,
        sampled_world,
        evidence_state,
    } = inputs;
    let queries = queries_for_template(template)?;
    let gold_targets = targets_from_queries(template, &evidence_state, &queries, seed)?;
    let renderings = render_all(template, &evidence_state, renderer_seed)?;
    let semantic_fingerprint = semantic_fingerprint(
        template,
        &sampled_world,
        &evidence_state,
        &queries,
        &gold_targets,
    )?;
    let episode = Episode {
        contract: CONTRACT.to_string(),
        episode_id: format!("{}-{:06}", template.family_id, sequence),
        template: TemplateRef::from(template),
        authority: AuthorityClass::SyntheticControl,
        sampled_world,
        evidence_state,
        queries,
        gold_targets,
        renderings,
        perturbation_links: Vec::new(),
        provenance: Provenance {
            generator_id: "jev-decision-world-generator".to_string(),
            generator_version: "0.1.0".to_string(),
            seed,
            world_sample_seed,
            observation_seed,
            renderer_seed,
            semantic_fingerprint,
        },
    };
    validate_episode(&episode, template)?;
    Ok(episode)
}

pub fn surface_perturbation(
    parent: &Episode,
    template: &WorldTemplate,
    format: RenderFormat,
) -> Result<Episode> {
    validate_episode(parent, template)?;
    let mut child = parent.clone();
    child.episode_id = format!("{}-surface-{}", parent.episode_id, format_name(&format));
    child.renderings = vec![render(
        template,
        &child.evidence_state,
        format,
        parent.provenance.renderer_seed,
    )?];
    child.perturbation_links = vec![PerturbationLink {
        family_id: format!("{}:surface", parent.episode_id),
        parent_episode_id: parent.episode_id.clone(),
        class: PerturbationClass::SurfaceInvariance,
        operation: format!("render_as_{}", format_name(&child.renderings[0].format)),
        affected_fact_ids: Vec::new(),
        affected_variable: None,
        expected_relation: ExpectedRelation::StrictInvariant,
    }];
    child.provenance.renderer_seed = mix_seed(parent.provenance.renderer_seed, 0x51, 0x52);
    child.provenance.semantic_fingerprint = semantic_fingerprint(
        template,
        &child.sampled_world,
        &child.evidence_state,
        &child.queries,
        &child.gold_targets,
    )?;
    verify_perturbation_pair(parent, &child, template)?;
    Ok(child)
}

pub fn observation_perturbation(
    parent: &Episode,
    template: &WorldTemplate,
    fact_id: &str,
) -> Result<Episode> {
    validate_episode(parent, template)?;
    let mut child = parent.clone();
    let fact_index = child
        .evidence_state
        .facts
        .iter()
        .position(|fact| fact.fact_id == fact_id)
        .with_context(|| format!("unknown evidence fact {fact_id}"))?;
    ensure!(
        matches!(
            child.evidence_state.facts[fact_index].visibility,
            Visibility::Visible
        ),
        "observation perturbation requires a visible fact"
    );
    child.evidence_state.facts[fact_index].visibility = Visibility::Hidden;
    child.evidence_state.facts[fact_index].observed_value = None;
    child.evidence_state = evidence_from_facts(child.evidence_state.facts.clone());
    child.gold_targets = targets_from_queries(
        template,
        &child.evidence_state,
        &child.queries,
        parent.provenance.seed,
    )?;
    child.renderings = render_all(
        template,
        &child.evidence_state,
        parent.provenance.renderer_seed,
    )?;
    child.episode_id = format!("{}-hide-{}", parent.episode_id, fact_id);
    child.perturbation_links = vec![PerturbationLink {
        family_id: format!("{}:hide", parent.episode_id),
        parent_episode_id: parent.episode_id.clone(),
        class: PerturbationClass::ObservationIntervention,
        operation: "hide_observation".to_string(),
        affected_fact_ids: vec![fact_id.to_string()],
        affected_variable: Some(
            child.evidence_state.facts[fact_index]
                .source_variable
                .clone(),
        ),
        expected_relation: ExpectedRelation::Recomputed,
    }];
    child.provenance.observation_seed =
        mix_seed(parent.provenance.observation_seed, fact_index as u64, 0x61);
    child.provenance.semantic_fingerprint = semantic_fingerprint(
        template,
        &child.sampled_world,
        &child.evidence_state,
        &child.queries,
        &child.gold_targets,
    )?;
    validate_episode(&child, template)?;
    Ok(child)
}

pub fn world_perturbation(
    parent: &Episode,
    template: &WorldTemplate,
    variable: &str,
    value: u8,
) -> Result<Episode> {
    validate_episode(parent, template)?;
    let variable_index = template
        .variable_index(variable)
        .with_context(|| format!("unknown intervention variable {variable}"))?;
    ensure!(
        usize::from(value) < template.variables[variable_index].domain.len(),
        "intervention value outside domain"
    );
    let world_seed = mix_seed(
        parent.provenance.world_sample_seed,
        variable_index as u64,
        u64::from(value),
    );
    let sampled_world = sample_world(template, world_seed, Some((variable_index, value)))?;
    let observation_seed = mix_seed(
        parent.provenance.observation_seed,
        variable_index as u64,
        u64::from(value),
    );
    let evidence_state = observe_with_visibility(
        template,
        &sampled_world,
        observation_seed,
        &parent.evidence_state,
    )?;
    let mut child = build_episode(
        template,
        BuildInputs {
            sequence: 0,
            seed: parent.provenance.seed,
            world_sample_seed: world_seed,
            observation_seed,
            renderer_seed: parent.provenance.renderer_seed,
            sampled_world,
            evidence_state,
        },
    )?;
    child.episode_id = format!("{}-do-{}-{}", parent.episode_id, variable, value);
    child.perturbation_links = vec![PerturbationLink {
        family_id: format!("{}:do", parent.episode_id),
        parent_episode_id: parent.episode_id.clone(),
        class: PerturbationClass::WorldIntervention,
        operation: "do_intervention".to_string(),
        affected_fact_ids: Vec::new(),
        affected_variable: Some(variable.to_string()),
        expected_relation: ExpectedRelation::Recomputed,
    }];
    child.provenance.semantic_fingerprint = semantic_fingerprint(
        template,
        &child.sampled_world,
        &child.evidence_state,
        &child.queries,
        &child.gold_targets,
    )?;
    validate_episode(&child, template)?;
    Ok(child)
}

pub fn verify_perturbation_pair(
    parent: &Episode,
    child: &Episode,
    template: &WorldTemplate,
) -> Result<()> {
    validate_episode(parent, template)?;
    validate_episode(child, template)?;
    let link = child
        .perturbation_links
        .first()
        .context("child has no perturbation link")?;
    ensure!(
        link.parent_episode_id == parent.episode_id,
        "perturbation parent id mismatch"
    );
    match link.expected_relation {
        ExpectedRelation::StrictInvariant => {
            ensure!(
                parent.sampled_world == child.sampled_world,
                "surface perturbation changed sampled world"
            );
            ensure!(
                parent.evidence_state == child.evidence_state,
                "surface perturbation changed evidence"
            );
            ensure!(
                parent.queries == child.queries,
                "surface perturbation changed queries"
            );
            ensure!(
                parent.gold_targets == child.gold_targets,
                "surface perturbation changed gold targets"
            );
        }
        ExpectedRelation::Recomputed | ExpectedRelation::DirectionalOnly => {}
    }
    Ok(())
}

fn sample_world(
    template: &WorldTemplate,
    seed: u64,
    intervention: Option<(usize, u8)>,
) -> Result<Vec<u8>> {
    let order = topological_order(template)?;
    for attempt in 0..1_024_u64 {
        let mut assignment = vec![0_u8; template.variables.len()];
        let mut rng = Rng::new(if attempt == 0 {
            seed
        } else {
            mix_seed(seed, attempt, 0xc0)
        });
        for index in &order {
            if let Some((target, value)) = intervention
                && target == *index
            {
                assignment[*index] = value;
                continue;
            }
            let mechanism = template
                .mechanism(&template.variables[*index].id)
                .context("missing mechanism")?;
            let row = parent_row(template, mechanism, &assignment)?;
            let width = template.variables[*index].domain.len();
            let start = row * width;
            assignment[*index] = rng.choose(&mechanism.table[start..start + width])?;
        }
        let constraints_hold = template.constraints.iter().all(|constraint| {
            let Some(if_index) = template.variable_index(&constraint.if_variable) else {
                return false;
            };
            let Some(then_index) = template.variable_index(&constraint.then_variable) else {
                return false;
            };
            assignment[if_index] != constraint.if_value
                || assignment[then_index] == constraint.then_value
        });
        if constraints_hold {
            return Ok(assignment);
        }
    }
    bail!("could not sample a world satisfying template constraints")
}

fn observe(
    template: &WorldTemplate,
    sampled_world: &[u8],
    seed: u64,
    visibility_probability: f64,
    visibility_override: Option<&[bool]>,
) -> Result<EvidenceState> {
    let mut rng = Rng::new(seed);
    let mut facts = Vec::with_capacity(template.observation_channels.len());
    for (index, channel) in template.observation_channels.iter().enumerate() {
        let source_index = template
            .variable_index(&channel.source_variable)
            .context("channel source missing")?;
        let visible = visibility_override
            .and_then(|values| values.get(index).copied())
            .unwrap_or_else(|| {
                rng.next_f64() < visibility_probability * channel.default_visibility_probability
            });
        let true_value = sampled_world[source_index];
        let observed_value = if visible {
            let width = channel.observed_domain.len();
            let start = usize::from(true_value) * width;
            Some(rng.choose(&channel.likelihood_table[start..start + width])?)
        } else {
            None
        };
        facts.push(EvidenceFact {
            fact_id: format!("ev_{index:02}_{}", channel.source_variable),
            source_variable: channel.source_variable.clone(),
            true_value,
            visibility: if visible {
                Visibility::Visible
            } else {
                Visibility::Hidden
            },
            observed_value,
            channel_id: channel.id.clone(),
        });
    }
    if !facts
        .iter()
        .any(|fact| matches!(fact.visibility, Visibility::Visible))
        && !facts.is_empty()
    {
        let fact = &mut facts[0];
        let channel = template
            .channel(&fact.channel_id)
            .context("forced-visible channel missing")?;
        let width = channel.observed_domain.len();
        let start = usize::from(fact.true_value) * width;
        fact.visibility = Visibility::Visible;
        fact.observed_value =
            Some(Rng::new(seed ^ 0xabc).choose(&channel.likelihood_table[start..start + width])?);
    }
    Ok(evidence_from_facts(facts))
}

fn observe_with_visibility(
    template: &WorldTemplate,
    sampled_world: &[u8],
    seed: u64,
    parent: &EvidenceState,
) -> Result<EvidenceState> {
    let visible: Vec<bool> = parent.evidence_state_visibility_mask();
    observe(template, sampled_world, seed, 0.80, Some(&visible))
}

fn evidence_from_facts(facts: Vec<EvidenceFact>) -> EvidenceState {
    let visible_fact_ids = facts
        .iter()
        .filter(|fact| matches!(fact.visibility, Visibility::Visible))
        .map(|fact| fact.fact_id.clone())
        .collect();
    let missing_fact_ids = facts
        .iter()
        .filter(|fact| matches!(fact.visibility, Visibility::Hidden))
        .map(|fact| fact.fact_id.clone())
        .collect();
    EvidenceState {
        facts,
        visible_fact_ids,
        missing_fact_ids,
    }
}

fn queries_for_template(template: &WorldTemplate) -> Result<Vec<Query>> {
    let (decision_variable, positive_value) = match template.family_id.as_str() {
        "system_diagnosis" => ("root_cause", 0_u8),
        "support_routing" => ("route", 2_u8),
        "network_incident" => ("incident_type", 0_u8),
        _ if template.variable("root_cause").is_some() => ("root_cause", 0_u8),
        _ if template.variable("decision_target").is_some() => ("decision_target", 0_u8),
        family => bail!("no v0 query set for family {family}"),
    };
    let decision_domain_len = template
        .variable(decision_variable)
        .context("decision variable missing")?
        .domain
        .len();
    let ordinal_variable = if template.variable("severity").is_some() {
        "severity"
    } else {
        "impact"
    };
    let candidates: Vec<u8> = (0..decision_domain_len)
        .map(|value| u8::try_from(value).expect("validated domain width"))
        .collect();
    Ok(vec![
        Query::Proposition {
            id: "q_proposition".to_string(),
            variable: decision_variable.to_string(),
            value: positive_value,
        },
        Query::Applicability {
            id: "q_applicability".to_string(),
            variable: decision_variable.to_string(),
            value: positive_value,
        },
        Query::Choice {
            id: "q_choice_closed".to_string(),
            variable: decision_variable.to_string(),
            candidate_values: candidates.clone(),
            mode: ChoiceMode::ClosedWorld,
        },
        Query::Choice {
            id: "q_choice_open_subset".to_string(),
            variable: decision_variable.to_string(),
            candidate_values: candidates.iter().copied().take(2).collect(),
            mode: ChoiceMode::OpenWorld,
        },
        Query::Ordinal {
            id: "q_ordinal".to_string(),
            variable: ordinal_variable.to_string(),
        },
        Query::Abstain {
            id: "q_abstain".to_string(),
            variable: decision_variable.to_string(),
            entropy_threshold: 0.90,
        },
    ])
}

fn render_all(
    template: &WorldTemplate,
    evidence: &EvidenceState,
    seed: u64,
) -> Result<Vec<Rendering>> {
    Ok(vec![
        render(template, evidence, RenderFormat::Prose, seed)?,
        render(template, evidence, RenderFormat::Json, seed)?,
        render(template, evidence, RenderFormat::Log, seed)?,
    ])
}

fn render(
    template: &WorldTemplate,
    evidence: &EvidenceState,
    format: RenderFormat,
    seed: u64,
) -> Result<Rendering> {
    let visible: Vec<&EvidenceFact> = evidence
        .facts
        .iter()
        .filter(|fact| matches!(fact.visibility, Visibility::Visible))
        .collect();
    let source_fact_ids = visible.iter().map(|fact| fact.fact_id.clone()).collect();
    let text = match format {
        RenderFormat::Json => {
            let rows: Vec<serde_json::Value> = visible.iter().map(|fact| serde_json::json!({
                "fact_id": fact.fact_id,
                "variable": fact.source_variable,
                "value": template.variable(&fact.source_variable).and_then(|variable| variable.domain.get(usize::from(fact.observed_value.unwrap_or(0)))).cloned().unwrap_or_default(),
            })).collect();
            serde_json::to_string(&rows)?
        }
        RenderFormat::Log => visible
            .iter()
            .enumerate()
            .map(|(index, fact)| {
                let value = template
                    .variable(&fact.source_variable)
                    .and_then(|variable| {
                        variable
                            .domain
                            .get(usize::from(fact.observed_value.unwrap_or(0)))
                    })
                    .map(String::as_str)
                    .unwrap_or("unknown");
                format!(
                    "{:02}:{:02} {}={}",
                    (seed as usize + index) % 24,
                    (seed as usize / 24 + index * 7) % 60,
                    fact.source_variable,
                    value
                )
            })
            .collect::<Vec<_>>()
            .join("\n"),
        RenderFormat::Prose => visible
            .iter()
            .map(|fact| {
                let value = template
                    .variable(&fact.source_variable)
                    .and_then(|variable| {
                        variable
                            .domain
                            .get(usize::from(fact.observed_value.unwrap_or(0)))
                    })
                    .map(String::as_str)
                    .unwrap_or("unknown");
                format!(
                    "The observed {} was {}.",
                    fact.source_variable.replace('_', " "),
                    value
                )
            })
            .collect::<Vec<_>>()
            .join(" "),
    };
    let text = if text.is_empty() {
        "No observable evidence was available.".to_string()
    } else {
        text
    };
    Ok(Rendering {
        format,
        text,
        source_fact_ids,
    })
}

fn semantic_fingerprint(
    template: &WorldTemplate,
    world: &[u8],
    evidence: &EvidenceState,
    queries: &[Query],
    gold: &[crate::types::GoldTarget],
) -> Result<String> {
    let bytes = serde_json::to_vec(&(
        template.template_id.as_str(),
        world,
        evidence,
        queries,
        gold,
    ))?;
    let mut hasher = Hasher::new();
    hasher.update(&bytes);
    Ok(hasher.finalize().to_hex().to_string())
}

fn topological_order(template: &WorldTemplate) -> Result<Vec<usize>> {
    let mut state = vec![0_u8; template.variables.len()];
    let mut order = Vec::with_capacity(template.variables.len());
    for index in 0..template.variables.len() {
        visit(template, index, &mut state, &mut order)?;
    }
    Ok(order)
}

fn visit(
    template: &WorldTemplate,
    index: usize,
    state: &mut [u8],
    order: &mut Vec<usize>,
) -> Result<()> {
    if state[index] == 2 {
        return Ok(());
    }
    ensure!(state[index] != 1, "cycle while ordering template");
    state[index] = 1;
    let mechanism = template
        .mechanism(&template.variables[index].id)
        .context("missing mechanism")?;
    for parent in &mechanism.parents {
        let parent_index = template.variable_index(parent).context("missing parent")?;
        visit(template, parent_index, state, order)?;
    }
    state[index] = 2;
    order.push(index);
    Ok(())
}

fn parent_row(
    template: &WorldTemplate,
    mechanism: &crate::types::Mechanism,
    assignment: &[u8],
) -> Result<usize> {
    let mut row = 0_usize;
    let mut stride = 1_usize;
    for parent in mechanism.parents.iter().rev() {
        let index = template.variable_index(parent).context("parent missing")?;
        row += usize::from(assignment[index]) * stride;
        stride *= template.variables[index].domain.len();
    }
    Ok(row)
}

fn format_name(format: &RenderFormat) -> &'static str {
    match format {
        RenderFormat::Prose => "prose",
        RenderFormat::Json => "json",
        RenderFormat::Log => "log",
    }
}

fn mix_seed(seed: u64, a: u64, b: u64) -> u64 {
    let mut value =
        seed ^ a.wrapping_mul(0x9e37_79b9_7f4a_7c15) ^ b.wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value ^= value >> 30;
    value = value.wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value ^= value >> 27;
    value = value.wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

pub fn generate_pilot_report(config: &GenerationConfig) -> Result<crate::types::PilotReport> {
    let templates = crate::families::all_templates();
    let mut report = crate::types::PilotReport {
        contract: CONTRACT.to_string(),
        posterior_min: 1.0,
        posterior_max: 0.0,
        ..crate::types::PilotReport::default()
    };
    let mut probabilities = Vec::with_capacity(config.count * 12);
    for sequence in 0..config.count {
        let template = &templates[sequence % templates.len()];
        let episode = generate_episode(template, sequence, config)?;
        validate_episode(&episode, template)?;
        report.episode_count += 1;
        *report
            .template_counts
            .entry(template.template_id.clone())
            .or_default() += 1;
        for target in &episode.gold_targets {
            let distribution = target_distribution(&target.value);
            for probability in &distribution {
                report.posterior_min = report.posterior_min.min(*probability);
                report.posterior_max = report.posterior_max.max(*probability);
                probabilities.push(*probability);
            }
            *report
                .entropy_bands
                .entry(entropy_band(&distribution))
                .or_default() += 1;
        }
        report.verified_episodes += 1;
    }
    let (_simd_min, _simd_max, simd_sum) = simd_bounds(&probabilities);
    ensure!(
        simd_sum.is_finite(),
        "SIMD probability audit produced a non-finite sum"
    );
    Ok(report)
}

fn target_distribution(value: &GoldValue) -> Vec<f64> {
    match value {
        GoldValue::Proposition {
            true_probability,
            false_probability,
        } => vec![*true_probability, *false_probability],
        GoldValue::IndependentApplicability { probability } => {
            vec![*probability, 1.0 - *probability]
        }
        GoldValue::Choice {
            probabilities,
            other_probability,
            ..
        } => probabilities
            .iter()
            .map(|item| item.probability)
            .chain(std::iter::once(*other_probability))
            .collect(),
        GoldValue::Ordinal { distribution, .. } => distribution.clone(),
        GoldValue::Abstention { posterior, .. } => posterior.clone(),
    }
}

fn entropy_band(distribution: &[f64]) -> String {
    let maximum = (distribution.len() as f64).ln();
    let normalized = if maximum > 0.0 {
        entropy(distribution) / maximum
    } else {
        0.0
    };
    if normalized < 0.20 {
        "very_low"
    } else if normalized < 0.40 {
        "low"
    } else if normalized < 0.70 {
        "medium"
    } else if normalized < 0.90 {
        "high"
    } else {
        "near_unidentifiable"
    }
    .to_string()
}

fn simd_bounds(values: &[f64]) -> (f64, f64, f64) {
    let mut minimum = f32::INFINITY;
    let mut maximum = f32::NEG_INFINITY;
    let mut sum = 0.0_f32;
    for chunk in values.chunks(8) {
        let mut lanes = [0.0_f32; 8];
        for (lane, value) in chunk.iter().copied().enumerate() {
            lanes[lane] = value as f32;
        }
        let vector = f32x8::from(lanes);
        sum += vector.reduce_add();
        for value in lanes.into_iter().take(chunk.len()) {
            minimum = minimum.min(value);
            maximum = maximum.max(value);
        }
    }
    (f64::from(minimum), f64::from(maximum), f64::from(sum))
}

trait VisibilityMask {
    fn evidence_state_visibility_mask(&self) -> Vec<bool>;
}

impl VisibilityMask for EvidenceState {
    fn evidence_state_visibility_mask(&self) -> Vec<bool> {
        self.facts
            .iter()
            .map(|fact| matches!(fact.visibility, Visibility::Visible))
            .collect()
    }
}
