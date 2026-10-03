use anyhow::{Context, Result, ensure};
use blake3::Hasher;
use jev_decision_world_v01 as v01;
use jev_decision_world_v02 as v02;
use v02::types::{CandidateDefinition, CandidateKind, Representation, RuntimeSchema};

use crate::worlds::{FamilySpec, definition, signal_phrase};

#[derive(Clone, Copy)]
pub struct FamilyIds<'a> {
    pub world: &'a str,
    pub ontology: &'a str,
    pub schema: &'a str,
    pub candidate_set: &'a str,
    pub definition: &'a str,
    pub intervention: &'a str,
}

pub fn canonical_episode(
    source: &v01::Episode,
    template: &v01::WorldTemplate,
    spec: &FamilySpec,
    family_ids: FamilyIds<'_>,
    hierarchy: usize,
    definition_variant: usize,
    renderer: usize,
    root_id: &str,
    new_episode_id: &str,
    parent_episode_id: Option<&str>,
) -> Result<v02::CanonicalEpisode> {
    let mut episode = v02::synthetic::from_v01(source, template)?;
    episode.identity.episode_id = new_episode_id.to_string();
    episode.identity.world_instance_id = if source
        .perturbation_links
        .first()
        .is_some_and(|link| link.class == v01::PerturbationClass::WorldIntervention)
    {
        format!("{root_id}:do")
    } else {
        root_id.to_string()
    };
    episode.identity.world_family_id = family_ids.world.to_string();
    episode.identity.schema_family_id = family_ids.schema.to_string();
    episode.identity.paraphrase_family_id = family_ids.definition.to_string();
    episode.identity.perturbation_family_id = family_ids.intervention.to_string();
    episode.identity.domain_family_id = format!("synthetic_control:{}", spec.slug);
    episode.runtime_schema.schema_id = format!("{}:h{}", family_ids.schema, hierarchy);
    episode.runtime_schema.schema_family_id = family_ids.schema.to_string();
    episode.runtime_schema.constraints.push(match hierarchy {
        0 => "flat_candidate_hierarchy".to_string(),
        1 => "two_balanced_sibling_branches".to_string(),
        2 => "single_parent_branch".to_string(),
        _ => "asymmetric_three_level_branching".to_string(),
    });
    install_runtime_definitions(
        &mut episode.runtime_schema,
        spec,
        family_ids,
        hierarchy,
        definition_variant,
    )?;
    render_observations(&mut episode, spec, renderer)?;
    bind_query_semantics(&mut episode, spec);
    update_lineage(&mut episode, new_episode_id, parent_episode_id, root_id);
    rehash_and_validate(&mut episode)?;
    Ok(episode)
}

fn install_runtime_definitions(
    schema: &mut RuntimeSchema,
    spec: &FamilySpec,
    family_ids: FamilyIds<'_>,
    hierarchy: usize,
    definition_variant: usize,
) -> Result<()> {
    let mut branch_ids = [None, None];
    let root_id = format!("ontology-root:{}", spec.slug);
    match hierarchy {
        1 | 3 => {
            branch_ids = [
                Some(format!("ontology-branch:{}:0", spec.slug)),
                Some(format!("ontology-branch:{}:1", spec.slug)),
            ];
            schema.candidates.push(parent_candidate(
                &branch_ids[0].clone().unwrap(),
                "Operational branch one",
                "A parent category grouping related candidate meanings.",
                Some(root_id.clone()),
            ));
            schema.candidates.push(parent_candidate(
                &branch_ids[1].clone().unwrap(),
                "Operational branch two",
                "A parent category grouping a different set of candidate meanings.",
                Some(root_id.clone()),
            ));
            schema.candidates.push(parent_candidate(
                &root_id,
                "Decision ontology",
                "The broad semantic family used to organize runtime alternatives.",
                None,
            ));
        }
        2 => schema.candidates.push(parent_candidate(
            &root_id,
            "Decision ontology",
            "The broad semantic family used to organize runtime alternatives.",
            None,
        )),
        _ => {}
    }

    for candidate in &mut schema.candidates {
        let Some(value) = candidate.candidate_semantic_id.strip_prefix("root_cause=") else {
            continue;
        };
        let index = spec
            .concepts
            .iter()
            .position(|concept| concept.id == value)
            .context("candidate semantic ID does not match the domain ontology")?;
        candidate.name = Some(spec.concepts[index].name.to_string());
        candidate.description = Some(definition(spec, index, definition_variant));
        candidate.aliases = vec![spec.concepts[index].id.replace('_', " ")];
        candidate.opaque_id = Some(format!("X{:02}", index + 1));
        candidate.independent_allowed = true;
        candidate.mutually_exclusive_group_id =
            Some(format!("{}:closed-choice", family_ids.candidate_set));
        candidate.parent_candidate_semantic_id = match hierarchy {
            0 => None,
            1 => Some(branch_ids[index / 2].clone().unwrap()),
            2 => Some(root_id.clone()),
            _ if index < 2 => Some(branch_ids[0].clone().unwrap()),
            _ if index == 3 => Some(branch_ids[1].clone().unwrap()),
            _ => Some(root_id.clone()),
        };
    }
    ensure!(
        schema
            .candidates
            .iter()
            .filter(|candidate| candidate.candidate_semantic_id.starts_with("root_cause="))
            .count()
            == 4,
        "expected four semantic leaf candidates"
    );
    Ok(())
}

fn parent_candidate(
    semantic_id: &str,
    name: &str,
    description: &str,
    parent: Option<String>,
) -> CandidateDefinition {
    CandidateDefinition {
        candidate_id: format!("node-{semantic_id}"),
        candidate_semantic_id: semantic_id.to_string(),
        kind: CandidateKind::Label,
        name: Some(name.to_string()),
        description: Some(description.to_string()),
        aliases: Vec::new(),
        opaque_id: None,
        parent_candidate_semantic_id: parent,
        order_rank: None,
        mutually_exclusive_group_id: None,
        independent_allowed: false,
    }
}

fn render_observations(
    episode: &mut v02::CanonicalEpisode,
    spec: &FamilySpec,
    renderer: usize,
) -> Result<()> {
    let mut facts = Vec::with_capacity(episode.evidence_items.len());
    for evidence in &mut episode.evidence_items {
        let (signal, raw_value) = evidence
            .content
            .split_once('=')
            .context("v0.2 adapter emitted unexpected evidence content")?;
        let signal = signal.to_string();
        let raw_value = raw_value.to_string();
        let index: usize = signal
            .strip_prefix("signal_")
            .context("unknown evidence signal")?
            .parse()?;
        let observed_true = raw_value == "true";
        let phrase = signal_phrase(spec, index, observed_true);
        evidence.content = phrase.clone();
        facts.push((signal, raw_value, phrase));
    }
    let representation = match renderer % 6 {
        0 => Representation::Prose,
        1 => Representation::Json,
        2 => Representation::Table,
        3 => Representation::EventStream,
        4 => Representation::KeyValue,
        _ => Representation::Dialogue,
    };
    let content = match renderer % 6 {
        0 => format!("Observed report for {}. {}", spec.setting, facts.iter().map(|fact| fact.2.as_str()).collect::<Vec<_>>().join(" ")),
        1 => serde_json::to_string(&facts.iter().map(|fact| serde_json::json!({"signal":fact.0,"observed":fact.1,"statement":fact.2})).collect::<Vec<_>>())?,
        2 => format!("Signal | Observation\n--- | ---\n{}", facts.iter().map(|fact| format!("{} | {}", fact.0, fact.2)).collect::<Vec<_>>().join("\n")),
        3 => facts.iter().enumerate().map(|(index, fact)| format!("T+{:02} | {}", index * 7 + 3, fact.2)).collect::<Vec<_>>().join("\n"),
        4 => facts.iter().map(|fact| format!("{} = {}", fact.0, fact.2)).collect::<Vec<_>>().join("\n"),
        _ => format!("Analyst: What is visible in the {}?\nObserver: {}", spec.setting, facts.iter().map(|fact| fact.2.as_str()).collect::<Vec<_>>().join(" ")),
    };
    episode.state.observable.content = if content.trim().is_empty() {
        "No observable evidence was available.".to_string()
    } else {
        content
    };
    episode.state.representation = representation;
    episode.identity.surface_renderer_id = format!(
        "jev-v08-renderer-{}",
        [
            "prose",
            "json",
            "table",
            "event_stream",
            "key_value",
            "dialogue"
        ][renderer % 6]
    );
    Ok(())
}

fn bind_query_semantics(episode: &mut v02::CanonicalEpisode, spec: &FamilySpec) {
    for query in &mut episode.queries {
        query.query_semantic_id = match &query.view {
            v02::types::QueryView::OrdinalScore => format!("jev-v08:{}:severity", spec.slug),
            v02::types::QueryView::Abstain => format!("jev-v08:{}:evidence-sufficiency", spec.slug),
            _ => format!("jev-v08:{}:root-cause", spec.slug),
        };
        query.instruction = Some(match &query.view {
            v02::types::QueryView::Choice => {
                let other_probability = episode
                    .gold_targets
                    .iter()
                    .find(|target| target.query_id == query.query_id)
                    .and_then(|target| match &target.target {
                        v02::types::TargetPayload::Choice {
                            other_probability, ..
                        } => *other_probability,
                        _ => None,
                    })
                    .unwrap_or(0.0);
                if other_probability > 1e-12 {
                    format!(
                        "Choose the best listed explanation for the {} evidence, or choose Other if none applies.",
                        spec.setting
                    )
                } else {
                    format!(
                        "Choose exactly one explanation from the complete candidate set for the {} evidence.",
                        spec.setting
                    )
                }
            }
            v02::types::QueryView::IndependentApplicability => {
                "Assess this criterion independently; other criteria may also apply.".to_string()
            }
            v02::types::QueryView::OrdinalScore => format!(
                "Estimate the severity of the {} event on the supplied ordered scale.",
                spec.setting
            ),
            v02::types::QueryView::Abstain => {
                "Determine whether the visible evidence is sufficient for a supported decision."
                    .to_string()
            }
            v02::types::QueryView::SpanType => {
                "Assign the runtime type to each identified span.".to_string()
            }
            v02::types::QueryView::Relation => {
                "Assess whether the runtime relation holds between the arguments.".to_string()
            }
        });
    }
}

fn update_lineage(
    episode: &mut v02::CanonicalEpisode,
    new_episode_id: &str,
    parent_episode_id: Option<&str>,
    root_id: &str,
) {
    episode.identity.episode_id = new_episode_id.to_string();
    for evidence in &mut episode.evidence_items {
        evidence.source_ref = format!("synthetic:{new_episode_id}");
    }
    for record in &mut episode.authority_records {
        let new_authority_id = format!("auth-{new_episode_id}");
        record.authority_record_id = new_authority_id.clone();
        record.source_identity = format!("synthetic:{new_episode_id}");
        record.lineage.source_row_id = new_episode_id.to_string();
        record.lineage.source_dataset_id = "synthetic:jev-information-density-v08".to_string();
        record.lineage.source_revision = "0.8.0".to_string();
        record.lineage.adapter_id = "jev-v08-exact-family-generator".to_string();
        record.lineage.adapter_revision = "0.8.0".to_string();
        record.lineage.transformation_chain = vec![
            "finite_discrete_world_exact_enumeration".to_string(),
            "runtime_ontology_and_definition_binding".to_string(),
            "visible_evidence_surface_rendering".to_string(),
        ];
        let _ = root_id;
    }
    if let Some(authority) = episode.authority_records.first() {
        episode.authority.authority_record_ids = vec![authority.authority_record_id.clone()];
        for target in &mut episode.gold_targets {
            target.authority_record_id = authority.authority_record_id.clone();
        }
    }
    if let Some(perturbation) = &mut episode.perturbation {
        perturbation.family_id = format!("{root_id}:{}", perturbation.operation);
        perturbation.parent_episode_id = parent_episode_id.map(str::to_string);
    }
}

pub fn rehash_and_validate(episode: &mut v02::CanonicalEpisode) -> Result<()> {
    let bytes = episode.semantic_content_bytes()?;
    let mut hasher = Hasher::new();
    hasher.update(&bytes);
    episode.identity.semantic_fingerprint = hasher.finalize().to_hex().to_string();
    v02::validate::validate_episode(episode)?;
    ensure!(
        !episode.authority.phoenix_authority_domain,
        "synthetic bridge must remain outside Phoenix authority"
    );
    Ok(())
}
