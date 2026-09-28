use anyhow::{Context, Result, ensure};
use hashbrown::HashMap;
use jev_decision_world_v02 as v02;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use unicode_normalization::UnicodeNormalization;
use v02::types::{CandidateSetSemantics, CanonicalEpisode, Query, QueryView, TargetPayload};

use crate::project::FamilyIds;

const AXES: [&str; 6] = [
    "world_or_topology_family",
    "ontology_family",
    "schema_composition_family",
    "candidate_set_construction_family",
    "definition_template_family",
    "intervention_family",
];

#[derive(Serialize)]
pub struct GroupRecord {
    pub group_id: String,
    pub episode_id: String,
    pub root_id: String,
    pub valid: bool,
    pub family_ids: BTreeMap<String, String>,
    pub strata: BTreeMap<String, String>,
    pub coverage_features: BTreeMap<String, Vec<String>>,
    pub overlap_keys: Vec<String>,
    pub split_family_bundle_id: String,
    pub posterior_entropy_nats: f64,
}

pub fn group_records(
    episode: &CanonicalEpisode,
    root_id: &str,
    family_bundle_id: &str,
    family_ids: FamilyIds<'_>,
    generator_template_id: &str,
    topology: &str,
    hierarchy: usize,
    operation: &str,
) -> Result<Vec<GroupRecord>> {
    let mut result = Vec::with_capacity(4);
    for query in &episode.queries {
        let Some(target) = episode
            .gold_targets
            .iter()
            .find(|target| target.query_id == query.query_id)
        else {
            continue;
        };
        let (kind, cardinality, distribution, top_probability) = match &target.target {
            TargetPayload::IndependentApplicability { candidates } => {
                if query.view != QueryView::IndependentApplicability {
                    continue;
                }
                ensure!(
                    candidates.len() == 1,
                    "v0.8 currently expects one candidate per independent query; {} has {}",
                    query.query_id,
                    candidates.len()
                );
                let Some(probability) = candidates.first().and_then(|item| item.probability) else {
                    continue;
                };
                (
                    "independent_applicability",
                    1_usize,
                    vec![probability, 1.0 - probability],
                    probability.max(1.0 - probability),
                )
            }
            TargetPayload::Choice {
                distribution: Some(entries),
                other_probability: Some(other),
                ..
            } => {
                if *other > 1e-12 || query.view != QueryView::Choice {
                    continue;
                }
                let values: Vec<f64> = entries.iter().map(|entry| entry.probability).collect();
                if values.is_empty() {
                    continue;
                }
                let count = values.len();
                let maximum = values.iter().copied().fold(0.0_f64, f64::max);
                ("choice", count, values, maximum)
            }
            TargetPayload::Ordinal {
                distribution: Some(values),
                ..
            } => (
                "ordinal_score",
                values.len(),
                values.clone(),
                values.iter().copied().fold(0.0_f64, f64::max),
            ),
            _ => continue,
        };
        let entropy = entropy(&distribution);
        let cardinality_bin = cardinality_bin(cardinality).to_string();
        let view = view_name(&query.view);
        let state_text = &episode.state.observable.content;
        let normalized_hash = sha256_hex(normalize_text(state_text).as_bytes());
        let structure_hash = structural_fingerprint(episode, query, cardinality, operation)?;
        let mut families = BTreeMap::new();
        families.insert(AXES[0].to_string(), family_ids.world.to_string());
        families.insert(AXES[1].to_string(), family_ids.ontology.to_string());
        families.insert(AXES[2].to_string(), family_ids.schema.to_string());
        families.insert(AXES[3].to_string(), family_ids.candidate_set.to_string());
        families.insert(AXES[4].to_string(), family_ids.definition.to_string());
        families.insert(AXES[5].to_string(), family_ids.intervention.to_string());

        let candidate_semantics = query_candidate_semantics(episode, query);
        let candidate_surfaces = query_candidate_surfaces(episode, query);
        let sibling_count = local_sibling_count(episode, &candidate_semantics);
        let evidence_density = episode.state.variables.observed.len();
        let entropy_band = entropy_band(entropy);
        let top_band = top_probability_band(top_probability);
        let mut features = BTreeMap::new();
        features.insert(
            "semantic_novelty".to_string(),
            sorted(vec![
                family_ids.world.to_string(),
                family_ids.ontology.to_string(),
                family_ids.schema.to_string(),
                family_ids.definition.to_string(),
                format!("candidate_semantics:{:?}", candidate_semantics),
            ]),
        );
        features.insert(
            "local_discrimination".to_string(),
            sorted(vec![
                format!("hierarchy:{hierarchy}"),
                format!("same_parent_competitors:{sibling_count}"),
                format!("candidate_count:{cardinality}"),
            ]),
        );
        features.insert(
            "probability_geometry".to_string(),
            sorted(vec![
                format!("entropy:{entropy_band}"),
                format!("max_probability:{top_band}"),
                format!("target:{kind}"),
            ]),
        );
        features.insert(
            "structural_coverage".to_string(),
            sorted(vec![
                format!("topology:{topology}"),
                format!("query:{view}"),
                format!("cardinality:{cardinality_bin}"),
                format!("evidence_density:{}", density_bin(evidence_density)),
                format!("operation:{operation}"),
                episode.identity.surface_renderer_id.clone(),
                format!("hierarchy:{hierarchy}"),
            ]),
        );
        features.insert(
            "redundancy".to_string(),
            sorted(vec![
                format!("root:{root_id}"),
                format!("semantic:{}", episode.identity.semantic_fingerprint),
                format!("text:{normalized_hash}"),
                format!("structural:{structure_hash}"),
            ]),
        );

        let group_id = format!("{}|{}", episode.identity.episode_id, query.query_id);
        let group_id = if kind == "independent_applicability" {
            format!(
                "{group_id}|{}",
                candidate_semantics
                    .first()
                    .context("independent query has no candidate")?
            )
        } else {
            group_id
        };
        let state_text = &episode.state.observable.content;
        let exact_text_hash = sha256_hex(state_text.as_bytes());
        let schema_surface = schema_surface(episode, query, &candidate_surfaces, kind);
        let schema_surface_hash = sha256_hex(normalize_text(&schema_surface).as_bytes());
        let model_input_surface = format!("{state_text}\n{schema_surface}");
        let model_input_hash = sha256_hex(normalize_text(&model_input_surface).as_bytes());
        let gold_signature = gold_signature(target, kind)?;
        let gold_hash = sha256_hex(&gold_signature);
        let mut overlap = vec![
            format!("group:{group_id}"),
            format!("episode:{}", episode.identity.episode_id),
            format!("root:{root_id}"),
            format!("semantic:{}", episode.identity.semantic_fingerprint),
            format!("text:{normalized_hash}"),
            format!("text_exact:{exact_text_hash}"),
            format!("schema_surface:{schema_surface_hash}"),
            format!("model_input:{model_input_hash}"),
            format!("gold_target:{gold_hash}"),
            format!("structural:{structure_hash}"),
            format!("world_family:{}", family_ids.world),
            format!("ontology_family:{}", family_ids.ontology),
            format!("schema_composition:{}", family_ids.schema),
            format!("generator_template:{generator_template_id}"),
            format!("definition_template:{}", family_ids.definition),
            format!("intervention_family:{}", family_ids.intervention),
        ];
        overlap.sort();
        overlap.dedup();
        let mut strata = BTreeMap::new();
        strata.insert("world_family".to_string(), family_ids.world.to_string());
        strata.insert("query_view_type".to_string(), view.to_string());
        strata.insert("candidate_cardinality_bin".to_string(), cardinality_bin);
        strata.insert(
            "posterior_entropy_quintile".to_string(),
            "train_only_pending".to_string(),
        );
        result.push(GroupRecord {
            group_id,
            episode_id: episode.identity.episode_id.clone(),
            root_id: root_id.to_string(),
            valid: true,
            family_ids: families,
            strata,
            coverage_features: features,
            overlap_keys: overlap,
            split_family_bundle_id: family_bundle_id.to_string(),
            posterior_entropy_nats: entropy,
        });
    }
    Ok(result)
}

fn query_candidate_surfaces<'a>(
    episode: &'a CanonicalEpisode,
    query: &Query,
) -> Vec<&'a v02::types::CandidateDefinition> {
    let Some(set_id) = &query.candidate_set_id else {
        return Vec::new();
    };
    let Some(set) = episode
        .runtime_schema
        .candidate_sets
        .iter()
        .find(|set| set.candidate_set_id == *set_id)
    else {
        return Vec::new();
    };
    let mut candidates: Vec<_> = set
        .candidate_ids
        .iter()
        .filter_map(|id| {
            episode
                .runtime_schema
                .candidates
                .iter()
                .find(|candidate| candidate.candidate_id == *id)
        })
        .collect();
    candidates.sort_by(|left, right| left.candidate_semantic_id.cmp(&right.candidate_semantic_id));
    candidates
}

fn schema_surface(
    episode: &CanonicalEpisode,
    query: &Query,
    candidates: &[&v02::types::CandidateDefinition],
    kind: &str,
) -> String {
    let mut rows = vec![
        format!("view:{}", view_name(&query.view)),
        format!("task:{kind}"),
        query.instruction.clone().unwrap_or_default(),
    ];
    if let Some(set_id) = &query.candidate_set_id {
        if let Some(set) = episode
            .runtime_schema
            .candidate_sets
            .iter()
            .find(|set| set.candidate_set_id == *set_id)
        {
            rows.push(set.set_role.clone());
            rows.push(candidate_set_semantics_name(&set.declared_semantics).to_string());
            rows.push(format!("ordered:{}", set.ordered));
        }
    }
    let mut visible_candidates: Vec<_> = candidates
        .iter()
        .map(|candidate| {
            (
                candidate.name.clone().unwrap_or_default(),
                candidate.description.clone().unwrap_or_default(),
                if kind == "ordinal_score" {
                    candidate
                        .order_rank
                        .map(|rank| rank.to_string())
                        .unwrap_or_default()
                } else {
                    String::new()
                },
            )
        })
        .collect();
    visible_candidates.sort();
    for (name, description, order_rank) in visible_candidates {
        rows.push(name);
        rows.push(description);
        if kind == "ordinal_score" {
            rows.push(order_rank);
        }
    }
    rows.join("\n")
}

fn candidate_set_semantics_name(value: &CandidateSetSemantics) -> &'static str {
    match value {
        CandidateSetSemantics::ChoiceConditional => "choice_conditional",
        CandidateSetSemantics::IndependentApplicability => "independent_applicability",
        CandidateSetSemantics::OrdinalScale => "ordinal_scale",
        CandidateSetSemantics::SpanTypePairs => "span_type_pairs",
        CandidateSetSemantics::RelationPairs => "relation_pairs",
        CandidateSetSemantics::UnnormalizedCompatibility => "unnormalized_compatibility",
        CandidateSetSemantics::Unknown => "unknown",
    }
}

fn gold_signature(target: &v02::types::GoldTarget, kind: &str) -> Result<Vec<u8>> {
    let value = match &target.target {
        TargetPayload::IndependentApplicability { candidates } => {
            let item = candidates.first().context("independent target is empty")?;
            json!({"kind":kind,"candidate":item.candidate_semantic_id,"probability":item.probability})
        }
        TargetPayload::Choice {
            distribution: Some(entries),
            other_probability: Some(other),
            ..
        } => {
            let mut distribution: Vec<_> = entries
                .iter()
                .map(|entry| (entry.candidate_semantic_id.clone(), entry.probability))
                .collect();
            distribution.sort_by(|left, right| left.0.cmp(&right.0));
            json!({"kind":kind,"distribution":distribution,"other_probability":other})
        }
        TargetPayload::Ordinal {
            ordered_values,
            distribution: Some(values),
            ..
        } => {
            json!({"kind":kind,"ordered_values":ordered_values,"distribution":values})
        }
        _ => anyhow::bail!("unsupported target in group signature: {kind}"),
    };
    Ok(serde_json::to_vec(&value)?)
}

fn query_candidate_semantics(episode: &CanonicalEpisode, query: &Query) -> Vec<String> {
    let Some(set_id) = &query.candidate_set_id else {
        return Vec::new();
    };
    let candidate_ids: HashMap<&str, &str> = episode
        .runtime_schema
        .candidates
        .iter()
        .map(|candidate| {
            (
                candidate.candidate_id.as_str(),
                candidate.candidate_semantic_id.as_str(),
            )
        })
        .collect();
    episode
        .runtime_schema
        .candidate_sets
        .iter()
        .find(|set| set.candidate_set_id == *set_id)
        .map(|set| {
            set.candidate_ids
                .iter()
                .filter_map(|id| {
                    candidate_ids
                        .get(id.as_str())
                        .map(|value| (*value).to_string())
                })
                .collect()
        })
        .unwrap_or_default()
}

fn local_sibling_count(episode: &CanonicalEpisode, semantic_ids: &[String]) -> usize {
    let by_semantic: HashMap<&str, Option<&str>> = episode
        .runtime_schema
        .candidates
        .iter()
        .map(|candidate| {
            (
                candidate.candidate_semantic_id.as_str(),
                candidate.parent_candidate_semantic_id.as_deref(),
            )
        })
        .collect();
    semantic_ids
        .iter()
        .filter_map(|id| by_semantic.get(id.as_str()).copied().flatten())
        .map(|parent| {
            semantic_ids
                .iter()
                .filter(|other| by_semantic.get(other.as_str()).copied().flatten() == Some(parent))
                .count()
                .saturating_sub(1)
        })
        .max()
        .unwrap_or(0)
}

fn structural_fingerprint(
    episode: &CanonicalEpisode,
    query: &Query,
    cardinality: usize,
    operation: &str,
) -> Result<String> {
    let mut candidates: Vec<(String, String, Option<String>)> = episode
        .runtime_schema
        .candidates
        .iter()
        .map(|candidate| {
            (
                candidate.candidate_semantic_id.clone(),
                candidate_kind_name(&candidate.kind).to_string(),
                candidate.parent_candidate_semantic_id.clone(),
            )
        })
        .collect();
    candidates.sort();
    let mut sets: Vec<Value> = episode.runtime_schema.candidate_sets.iter().map(|set| {
        let mut members = set.candidate_ids.iter().filter_map(|candidate_id| episode.runtime_schema.candidates.iter()
            .find(|candidate| candidate.candidate_id == *candidate_id).map(|candidate| candidate.candidate_semantic_id.clone())).collect::<Vec<_>>();
        if !set.ordered { members.sort(); }
        json!({"role":set.set_role,"semantics":candidate_set_semantics_name(&set.declared_semantics),"ordered":set.ordered,"members":members})
    }).collect();
    sets.sort_by_key(|value| {
        (
            value["role"].as_str().unwrap_or_default().to_string(),
            serde_json::to_string(value).unwrap_or_default(),
        )
    });
    let signature = json!({
        "candidates": candidates,
        "candidate_sets": sets,
        "query_view": view_name(&query.view),
        "candidate_cardinality": cardinality,
        "topology_family": episode.identity.world_family_id,
        "operation": operation,
        "renderer": episode.identity.surface_renderer_id,
    });
    let bytes = serde_json::to_vec(&signature)?;
    Ok(sha256_hex(&bytes))
}

fn candidate_kind_name(value: &v02::types::CandidateKind) -> &'static str {
    match value {
        v02::types::CandidateKind::Label => "label",
        v02::types::CandidateKind::EntityType => "entity_type",
        v02::types::CandidateKind::RelationType => "relation_type",
        v02::types::CandidateKind::Oos => "oos",
        v02::types::CandidateKind::OrdinalScale => "ordinal_scale",
    }
}

fn view_name(view: &QueryView) -> &'static str {
    match view {
        QueryView::Choice => "choice",
        QueryView::IndependentApplicability => "independent_applicability",
        QueryView::OrdinalScore => "ordinal_score",
        QueryView::Abstain => "abstain",
        QueryView::SpanType => "span_type",
        QueryView::Relation => "relation",
    }
}

fn entropy(values: &[f64]) -> f64 {
    values
        .iter()
        .filter(|value| **value > 0.0)
        .map(|value| -value * value.ln())
        .sum()
}

fn entropy_band(value: f64) -> &'static str {
    if value < 0.20 {
        "very_low"
    } else if value < 0.55 {
        "low"
    } else if value < 0.95 {
        "medium"
    } else if value < 1.30 {
        "high"
    } else {
        "very_high"
    }
}

fn top_probability_band(value: f64) -> &'static str {
    if value >= 0.95 {
        "near_certain"
    } else if value >= 0.75 {
        "high"
    } else if value >= 0.50 {
        "moderate"
    } else {
        "diffuse"
    }
}

fn cardinality_bin(value: usize) -> &'static str {
    match value {
        1 => "1",
        2 => "2",
        3..=4 => "3-4",
        5..=8 => "5-8",
        _ => "9+",
    }
}

fn density_bin(value: usize) -> &'static str {
    match value {
        0 => "0",
        1 => "1",
        2 => "2",
        3..=4 => "3-4",
        _ => "5+",
    }
}

fn sorted(mut values: Vec<String>) -> Vec<String> {
    values.sort();
    values.dedup();
    values
}

fn normalize_text(value: &str) -> String {
    let mut output = String::with_capacity(value.len());
    let mut pending_space = false;
    for character in value.nfkc().flat_map(char::to_lowercase) {
        if character.is_alphanumeric() {
            if pending_space && !output.is_empty() {
                output.push(' ');
            }
            output.push(character);
            pending_space = false;
        } else {
            pending_space = true;
        }
    }
    output
}

fn sha256_hex(value: &[u8]) -> String {
    let digest = Sha256::digest(value);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}
