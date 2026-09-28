use std::collections::BTreeMap;
use std::fs::{File, create_dir_all};
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use anyhow::{Context, Result, bail, ensure};
use jev_decision_world_v01 as v01;
use jev_decision_world_v02 as v02;
use jev_decision_world_v02::types::{
    CandidateDefinition, CandidateKind, CandidateSet, CanonicalEpisode, GoldTarget,
    ProbabilityEntry, QueryView, TargetPayload,
};
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
struct CandidateStress {
    candidate_semantic_id: String,
    ontology_node_id: String,
    node_path: Vec<String>,
    semantic_distance: u8,
    relation_to_query_target: String,
}

#[derive(Clone, Debug, Serialize)]
struct QueryStress {
    query_id: String,
    target_semantic_id: Option<String>,
    candidate_semantic_ids: Vec<String>,
    candidate_distances: BTreeMap<String, u8>,
    semantic_density: String,
    affected_query_ids: Vec<String>,
    unaffected_query_ids: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
struct StressRecord {
    contract: String,
    episode_id: String,
    parent_episode_id: Option<String>,
    stress_family_id: String,
    intervention_class: String,
    operation: String,
    expected_relation: String,
    schema_regime: String,
    lexical_regime: String,
    world_regime: String,
    representation: String,
    ontology_id: String,
    candidate_profiles: Vec<String>,
    candidates: Vec<CandidateStress>,
    queries: Vec<QueryStress>,
    gold_recomputed: bool,
}

#[derive(Clone, Debug, Serialize)]
struct Manifest {
    contract: String,
    generator: String,
    base_episode_count: usize,
    canonical_episode_count: usize,
    metadata_record_count: usize,
    intervention_counts: BTreeMap<String, usize>,
    regime_counts: BTreeMap<String, usize>,
    validation: String,
    limitations: Vec<String>,
}

#[derive(Clone, Copy, Debug)]
enum CandidateMode {
    Full,
    OneSibling,
    TwoSiblings,
    DenseLocal,
    UnrelatedAdded,
}

impl CandidateMode {
    fn name(self) -> &'static str {
        match self {
            Self::Full => "full_ontology_branch",
            Self::OneSibling => "target_plus_one_sibling",
            Self::TwoSiblings => "target_plus_two_siblings",
            Self::DenseLocal => "all_local_candidates",
            Self::UnrelatedAdded => "local_plus_unrelated_distractor",
        }
    }
}

fn main() -> Result<()> {
    let options = Options::parse(std::env::args().skip(1))?;
    create_dir_all(&options.output)
        .with_context(|| format!("create {}", options.output.display()))?;
    let episodes_path = options.output.join("stress-episodes.jsonl");
    let metadata_path = options.output.join("stress-metadata.jsonl");
    let mut episodes = BufWriter::new(File::create(&episodes_path)?);
    let mut metadata = BufWriter::new(File::create(&metadata_path)?);
    let templates = v01::all_templates();
    let mut canonical_count = 0_usize;
    let mut metadata_count = 0_usize;
    let mut interventions = BTreeMap::<String, usize>::new();
    let mut regimes = BTreeMap::<String, usize>::new();

    for sequence in 0..options.base_count {
        let template = &templates[sequence % templates.len()];
        let config = v01::GenerationConfig {
            seed: options.seed,
            count: 1,
            visibility_probability: 1.0,
        };
        let base_v01 = v01::generate_episode(template, sequence, &config)?;
        let base = v02::synthetic::from_v01(&base_v01, template)?;
        emit(
            &mut episodes,
            &mut metadata,
            &base,
            record_for(
                &base,
                None,
                "base",
                "none",
                "base",
                "strict_invariant",
                false,
                sequence,
            ),
            &mut canonical_count,
            &mut metadata_count,
            &mut interventions,
            &mut regimes,
        )?;

        for format in [v01::RenderFormat::Json, v01::RenderFormat::Log] {
            let rendered = v01::surface_perturbation(&base_v01, template, format.clone())?;
            let mut child = base.clone();
            child.identity.episode_id = rendered.episode_id.clone();
            child.identity.surface_renderer_id =
                format!("synthetic-v01-{:?}", format).to_lowercase();
            child.state.representation = match format {
                v01::RenderFormat::Json => v02::types::Representation::Json,
                v01::RenderFormat::Log => v02::types::Representation::EventStream,
                v01::RenderFormat::Prose => v02::types::Representation::Prose,
            };
            child.state.observable.content = rendered.renderings[0].text.clone();
            child.state.observable.items = rendered.renderings[0].source_fact_ids.clone();
            child.perturbation = Some(v02::types::Perturbation {
                family_id: format!("{}:surface", base.identity.episode_id),
                parent_episode_id: Some(base.identity.episode_id.clone()),
                operation: format!("render_as_{:?}", format).to_lowercase(),
                class: "surfaceinvariance".to_string(),
                expected_relation: "strictinvariant".to_string(),
                affected_query_ids: Vec::new(),
                unaffected_query_ids: child.queries.iter().map(|q| q.query_id.clone()).collect(),
                alignment: Some("same_world_same_visible_facts".to_string()),
            });
            child.identity.semantic_fingerprint = fingerprint(&child)?;
            v02::validate::validate_episode(&child)?;
            emit(
                &mut episodes,
                &mut metadata,
                &child,
                record_for(
                    &child,
                    Some(&base),
                    "surface",
                    "surface_invariance",
                    "representation_change",
                    "strict_invariant",
                    false,
                    sequence,
                ),
                &mut canonical_count,
                &mut metadata_count,
                &mut interventions,
                &mut regimes,
            )?;
        }

        let visible_facts = base_v01
            .evidence_state
            .visible_fact_ids
            .iter()
            .cloned()
            .collect::<Vec<_>>();
        for fact_id in visible_facts {
            let child_v01 = v01::observation_perturbation(&base_v01, template, &fact_id)?;
            let child = v02::synthetic::from_v01(&child_v01, template)?;
            let record = record_for(
                &child,
                Some(&base),
                "observation",
                "observation_intervention",
                "supporting_evidence_removal",
                "recomputed",
                true,
                sequence,
            );
            emit(
                &mut episodes,
                &mut metadata,
                &child,
                record,
                &mut canonical_count,
                &mut metadata_count,
                &mut interventions,
                &mut regimes,
            )?;
        }

        for (variable_index, variable) in template.variables.iter().enumerate() {
            if !matches!(
                variable.role,
                v01::VariableRole::Latent | v01::VariableRole::DecisionRelevant
            ) {
                continue;
            }
            let sampled = base_v01.sampled_world[variable_index];
            for value in 0..variable.domain.len() as u8 {
                if value == sampled {
                    continue;
                }
                let child_v01 = v01::world_perturbation(&base_v01, template, &variable.id, value)?;
                let child = v02::synthetic::from_v01(&child_v01, template)?;
                let record = record_for(
                    &child,
                    Some(&base),
                    "world",
                    "world_intervention",
                    "counterfactual_state_change",
                    "recomputed",
                    true,
                    sequence,
                );
                emit(
                    &mut episodes,
                    &mut metadata,
                    &child,
                    record,
                    &mut canonical_count,
                    &mut metadata_count,
                    &mut interventions,
                    &mut regimes,
                )?;
            }
        }

        for mode in [
            CandidateMode::Full,
            CandidateMode::OneSibling,
            CandidateMode::TwoSiblings,
            CandidateMode::DenseLocal,
            CandidateMode::UnrelatedAdded,
        ] {
            let Some(choice_query) = base
                .queries
                .iter()
                .find(|query| query.view == QueryView::Choice)
            else {
                continue;
            };
            let child = candidate_variant(&base, choice_query.query_id.as_str(), mode)?;
            let record = record_for(
                &child,
                Some(&base),
                "candidate_ontology",
                "schema_intervention",
                mode.name(),
                "recomputed",
                false,
                sequence,
            );
            emit(
                &mut episodes,
                &mut metadata,
                &child,
                record,
                &mut canonical_count,
                &mut metadata_count,
                &mut interventions,
                &mut regimes,
            )?;
        }

        for paraphrase_index in 0..2_u8 {
            let child = definition_variant(&base, paraphrase_index, sequence)?;
            let record = record_for(
                &child,
                Some(&base),
                "schema",
                "schema_intervention",
                "criterion_paraphrase",
                "strict_invariant",
                false,
                sequence,
            );
            emit(
                &mut episodes,
                &mut metadata,
                &child,
                record,
                &mut canonical_count,
                &mut metadata_count,
                &mut interventions,
                &mut regimes,
            )?;
        }
    }
    episodes.flush()?;
    metadata.flush()?;
    let manifest = Manifest {
        contract: "jev-semantic-stress/v0.3".to_string(),
        generator: "jev-semantic-stress-v03".to_string(),
        base_episode_count: options.base_count,
        canonical_episode_count: canonical_count,
        metadata_record_count: metadata_count,
        intervention_counts: interventions,
        regime_counts: regimes,
        validation: "every emitted canonical episode passed v1 validator and fingerprint check".to_string(),
        limitations: vec![
            "ontology distance is an explicit generator-side structural annotation, not an embedding distance".to_string(),
            "the current v0.1 world families do not yet provide a true held-out causal family; world_ood is marked as a split-design placeholder".to_string(),
            "observation siblings currently remove visible evidence; strong/weak evidence labels are deferred until likelihood-strength metadata is promoted".to_string(),
        ],
    };
    std::fs::write(
        options.output.join("stress-manifest.json"),
        serde_json::to_vec_pretty(&manifest)?,
    )?;
    println!("{}", serde_json::to_string_pretty(&manifest)?);
    Ok(())
}

fn emit(
    episodes: &mut BufWriter<File>,
    metadata: &mut BufWriter<File>,
    episode: &CanonicalEpisode,
    record: StressRecord,
    canonical_count: &mut usize,
    metadata_count: &mut usize,
    interventions: &mut BTreeMap<String, usize>,
    regimes: &mut BTreeMap<String, usize>,
) -> Result<()> {
    v02::validate::validate_episode(episode)?;
    serde_json::to_writer(&mut *episodes, episode)?;
    episodes.write_all(b"\n")?;
    serde_json::to_writer(&mut *metadata, &record)?;
    metadata.write_all(b"\n")?;
    *canonical_count += 1;
    *metadata_count += 1;
    *interventions.entry(record.operation.clone()).or_default() += 1;
    *regimes.entry(record.schema_regime.clone()).or_default() += 1;
    Ok(())
}

fn record_for(
    episode: &CanonicalEpisode,
    parent: Option<&CanonicalEpisode>,
    stress_family: &str,
    intervention_class: &str,
    operation: &str,
    expected_relation: &str,
    gold_recomputed: bool,
    sequence: usize,
) -> StressRecord {
    let schema_regime = match sequence % 10 {
        0 => "schema_composition_ood",
        1 => "lexical_ood",
        _ => "in_distribution",
    };
    let world_regime = if sequence % 10 == 0 {
        "world_family_ood_placeholder"
    } else {
        "in_distribution"
    };
    let queries = episode
        .queries
        .iter()
        .map(|query| query_stress(episode, query.query_id.as_str()))
        .collect();
    let candidates = episode
        .runtime_schema
        .candidates
        .iter()
        .map(|candidate| CandidateStress {
            candidate_semantic_id: candidate.candidate_semantic_id.clone(),
            ontology_node_id: format!(
                "{}::{}",
                episode.identity.world_family_id, candidate.candidate_semantic_id
            ),
            node_path: vec![
                episode.identity.domain_family_id.clone(),
                candidate.candidate_semantic_id.clone(),
            ],
            semantic_distance: 3,
            relation_to_query_target: "unresolved_until_query_alignment".to_string(),
        })
        .collect();
    StressRecord {
        contract: "jev-semantic-stress/v0.3".to_string(),
        episode_id: episode.identity.episode_id.clone(),
        parent_episode_id: parent.map(|item| item.identity.episode_id.clone()),
        stress_family_id: format!(
            "{}:{}",
            stress_family,
            parent
                .map(|item| item.identity.episode_id.as_str())
                .unwrap_or(episode.identity.episode_id.as_str())
        ),
        intervention_class: intervention_class.to_string(),
        operation: operation.to_string(),
        expected_relation: expected_relation.to_string(),
        schema_regime: schema_regime.to_string(),
        lexical_regime: if schema_regime == "lexical_ood" {
            "held_out_lexical"
        } else {
            "in_distribution"
        }
        .to_string(),
        world_regime: world_regime.to_string(),
        representation: format!("{:?}", episode.state.representation).to_lowercase(),
        ontology_id: format!("stress-ontology-{}", episode.identity.world_family_id),
        candidate_profiles: vec![
            "name".to_string(),
            "name_definition".to_string(),
            "opaque_definition".to_string(),
            "opaque_only".to_string(),
        ],
        candidates,
        queries,
        gold_recomputed,
    }
}

fn query_stress(episode: &CanonicalEpisode, query_id: &str) -> QueryStress {
    let query = episode
        .queries
        .iter()
        .find(|query| query.query_id == query_id);
    let target = episode
        .gold_targets
        .iter()
        .find(|target| target.query_id == query_id);
    let ids = query
        .and_then(|query| query.candidate_set_id.as_ref())
        .and_then(|set_id| {
            episode
                .runtime_schema
                .candidate_sets
                .iter()
                .find(|set| &set.candidate_set_id == set_id)
        })
        .map(|set| {
            set.candidate_ids
                .iter()
                .filter_map(|id| {
                    episode
                        .runtime_schema
                        .candidates
                        .iter()
                        .find(|candidate| &candidate.candidate_id == id)
                        .map(|candidate| candidate.candidate_semantic_id.clone())
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let target_id = target.and_then(target_semantic_id);
    let mut distances = BTreeMap::new();
    let mut sibling_distance = 1_u8;
    for id in &ids {
        let distance = if Some(id) == target_id.as_ref() {
            0
        } else {
            let value = sibling_distance.min(4);
            sibling_distance = sibling_distance.saturating_add(1);
            value
        };
        distances.insert(id.clone(), distance);
    }
    let semantic_density = if distances.values().filter(|value| **value <= 1).count() > 1 {
        "hard_local"
    } else {
        "mixed"
    }
    .to_string();
    QueryStress {
        query_id: query_id.to_string(),
        target_semantic_id: target_id,
        candidate_semantic_ids: ids,
        candidate_distances: distances,
        semantic_density,
        affected_query_ids: Vec::new(),
        unaffected_query_ids: Vec::new(),
    }
}

fn target_semantic_id(target: &GoldTarget) -> Option<String> {
    match &target.target {
        TargetPayload::Choice {
            selected_candidate_semantic_id,
            distribution,
            ..
        } => selected_candidate_semantic_id.clone().or_else(|| {
            distribution
                .as_ref()?
                .iter()
                .max_by(|a, b| a.probability.total_cmp(&b.probability))
                .map(|item| item.candidate_semantic_id.clone())
        }),
        _ => None,
    }
}

fn candidate_variant(
    base: &CanonicalEpisode,
    query_id: &str,
    mode: CandidateMode,
) -> Result<CanonicalEpisode> {
    let query = base
        .queries
        .iter()
        .find(|query| query.query_id == query_id)
        .context("choice query missing")?;
    let set_id = query
        .candidate_set_id
        .as_ref()
        .context("choice set missing")?;
    let base_set = base
        .runtime_schema
        .candidate_sets
        .iter()
        .find(|set| &set.candidate_set_id == set_id)
        .context("candidate set missing")?;
    let target = base
        .gold_targets
        .iter()
        .find(|target| target.query_id == query_id)
        .context("choice target missing")?;
    let target_id =
        target_semantic_id(target).context("choice target has no selected candidate")?;
    let mut child = base.clone();
    child.identity.episode_id = format!("{}-candidate-{}", base.identity.episode_id, mode.name());
    child.identity.schema_family_id = format!("stress-schema-{}", mode.name());
    let mut candidate_ids = base_set.candidate_ids.clone();
    if matches!(mode, CandidateMode::OneSibling | CandidateMode::TwoSiblings) {
        let sibling_limit = if matches!(mode, CandidateMode::OneSibling) {
            1
        } else {
            2
        };
        let target_candidate_id = base_set.candidate_ids.iter().find(|id| {
            base.runtime_schema
                .candidates
                .iter()
                .find(|candidate| &candidate.candidate_id == *id)
                .map(|candidate| candidate.candidate_semantic_id == target_id)
                .unwrap_or(false)
        });
        let mut kept = Vec::with_capacity(sibling_limit + 1);
        if let Some(target_candidate_id) = target_candidate_id {
            kept.push(target_candidate_id.clone());
        }
        for candidate_id in &base_set.candidate_ids {
            if kept.len() > sibling_limit {
                break;
            }
            if !kept.contains(candidate_id) {
                kept.push(candidate_id.clone());
            }
        }
        candidate_ids = kept;
    }
    if matches!(mode, CandidateMode::UnrelatedAdded) {
        let candidate = CandidateDefinition {
            candidate_id: "candidate-stress-unrelated-d4".to_string(),
            candidate_semantic_id: "stress_unrelated_d4".to_string(),
            kind: CandidateKind::Label,
            name: Some("unrelated_domain_condition".to_string()),
            description: Some(
                "A condition from a separate domain with no shared ontology branch.".to_string(),
            ),
            aliases: Vec::new(),
            opaque_id: Some("Q17".to_string()),
            parent_candidate_semantic_id: None,
            order_rank: Some(99),
            mutually_exclusive_group_id: Some(format!("stress-group-{query_id}")),
            independent_allowed: false,
        };
        child.runtime_schema.candidates.push(candidate.clone());
        candidate_ids.push(candidate.candidate_id);
    }
    let new_set_id = format!("{set_id}-stress-{}", mode.name());
    child.runtime_schema.candidate_sets.push(CandidateSet {
        candidate_set_id: new_set_id.clone(),
        candidate_ids: candidate_ids.clone(),
        set_role: "stress-choice-candidates".to_string(),
        declared_semantics: base_set.declared_semantics.clone(),
        ordered: base_set.ordered,
        parent_candidate_set_id: Some(set_id.clone()),
    });
    let query_mut = child
        .queries
        .iter_mut()
        .find(|item| item.query_id == query_id)
        .unwrap();
    query_mut.candidate_set_id = Some(new_set_id.clone());
    let target_mut = child
        .gold_targets
        .iter_mut()
        .find(|item| item.query_id == query_id)
        .unwrap();
    target_mut.candidate_set_id = Some(new_set_id);
    if let TargetPayload::Choice {
        distribution,
        other_probability,
        selected_candidate_semantic_id,
        ..
    } = &mut target_mut.target
    {
        if let Some(values) = distribution {
            let original = values.clone();
            let mut filtered = original
                .into_iter()
                .filter(|entry| {
                    candidate_ids.iter().any(|candidate_id| {
                        child.runtime_schema.candidates.iter().any(|candidate| {
                            candidate.candidate_id == *candidate_id
                                && candidate.candidate_semantic_id == entry.candidate_semantic_id
                        })
                    })
                })
                .collect::<Vec<_>>();
            if matches!(
                mode,
                CandidateMode::Full | CandidateMode::DenseLocal | CandidateMode::UnrelatedAdded
            ) {
                if matches!(mode, CandidateMode::UnrelatedAdded) {
                    filtered.push(ProbabilityEntry {
                        candidate_semantic_id: "stress_unrelated_d4".to_string(),
                        probability: 0.0,
                    });
                }
            } else {
                let sum = filtered.iter().map(|entry| entry.probability).sum::<f64>();
                ensure!(sum > 0.0, "stress subset removed all posterior mass");
                for entry in &mut filtered {
                    entry.probability /= sum;
                }
            }
            *distribution = Some(filtered);
            if matches!(mode, CandidateMode::OneSibling | CandidateMode::TwoSiblings) {
                *other_probability = None;
            }
        }
        if selected_candidate_semantic_id.as_deref() == Some("stress_unrelated_d4") {
            *selected_candidate_semantic_id = None;
        }
    }
    child.perturbation = Some(v02::types::Perturbation {
        family_id: format!("{}:candidate", base.identity.episode_id),
        parent_episode_id: Some(base.identity.episode_id.clone()),
        operation: mode.name().to_string(),
        class: "schema_intervention".to_string(),
        expected_relation: "recomputed".to_string(),
        affected_query_ids: vec![query_id.to_string()],
        unaffected_query_ids: child
            .queries
            .iter()
            .filter(|query| query.query_id != query_id)
            .map(|query| query.query_id.clone())
            .collect(),
        alignment: Some("candidate_semantic_id".to_string()),
    });
    child.identity.semantic_fingerprint = fingerprint(&child)?;
    Ok(child)
}

fn definition_variant(
    base: &CanonicalEpisode,
    index: u8,
    sequence: usize,
) -> Result<CanonicalEpisode> {
    let mut child = base.clone();
    child.identity.episode_id =
        format!("{}-definition-paraphrase-{index}", base.identity.episode_id);
    child.identity.paraphrase_family_id = format!("stress-paraphrase-family-{sequence}");
    for candidate in &mut child.runtime_schema.candidates {
        let name = candidate
            .name
            .clone()
            .unwrap_or_else(|| candidate.candidate_semantic_id.clone());
        candidate.description = Some(if index == 0 {
            format!("The decision state is consistent with {name}.")
        } else {
            format!("Evidence supports the interpretation that this is {name}.")
        });
        candidate.opaque_id = Some(format!(
            "Q{:02}",
            (blake3::hash(candidate.candidate_semantic_id.as_bytes()).as_bytes()[0] % 89) + 10
        ));
    }
    child.perturbation = Some(v02::types::Perturbation {
        family_id: format!("{}:definitions", base.identity.episode_id),
        parent_episode_id: Some(base.identity.episode_id.clone()),
        operation: "criterion_paraphrase".to_string(),
        class: "surfaceinvariance".to_string(),
        expected_relation: "strictinvariant".to_string(),
        affected_query_ids: Vec::new(),
        unaffected_query_ids: child
            .queries
            .iter()
            .map(|query| query.query_id.clone())
            .collect(),
        alignment: Some("candidate_semantic_id".to_string()),
    });
    child.identity.semantic_fingerprint = fingerprint(&child)?;
    Ok(child)
}

fn fingerprint(episode: &CanonicalEpisode) -> Result<String> {
    Ok(blake3::hash(&episode.semantic_content_bytes()?)
        .to_hex()
        .to_string())
}

#[derive(Debug)]
struct Options {
    base_count: usize,
    seed: u64,
    output: PathBuf,
}

impl Options {
    fn parse(mut args: impl Iterator<Item = String>) -> Result<Self> {
        let mut options = Self {
            base_count: 120,
            seed: 0x4a_45_56_03,
            output: PathBuf::from(r"D:\codex-runs\jev-semantic-stress-v03\bank"),
        };
        while let Some(argument) = args.next() {
            match argument.as_str() {
                "--base-count" => {
                    options.base_count =
                        args.next().context("--base-count needs a value")?.parse()?
                }
                "--seed" => options.seed = args.next().context("--seed needs a value")?.parse()?,
                "--output" => {
                    options.output = PathBuf::from(args.next().context("--output needs a path")?)
                }
                "--help" | "-h" => {
                    println!("jev-semantic-stress-v03 --base-count N --seed N --output DIR");
                    std::process::exit(0);
                }
                other => bail!("unknown argument {other}"),
            }
        }
        Ok(options)
    }
}
