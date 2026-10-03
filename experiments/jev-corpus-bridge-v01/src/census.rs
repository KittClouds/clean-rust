use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use jev_decision_world_v02::types::{
    AuthorityClass, CanonicalEpisode, ProbabilitySource, TargetPayload,
};

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ScalarStats {
    pub count: usize,
    pub mean: Option<f64>,
    pub min: Option<f64>,
    pub max: Option<f64>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct EntropyStats {
    pub count: usize,
    pub mean_entropy: Option<f64>,
    pub min_entropy: Option<f64>,
    pub max_entropy: Option<f64>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct SemanticCensus {
    pub episode_count: usize,
    pub query_count: usize,
    pub view_counts: BTreeMap<String, usize>,
    pub authority_counts: BTreeMap<String, usize>,
    pub probability_source_counts: BTreeMap<String, usize>,
    pub contract_status_counts: BTreeMap<String, usize>,
    pub representation_counts: BTreeMap<String, usize>,
    pub candidate_cardinality: ScalarStats,
    pub state_length_bytes: ScalarStats,
    pub schema_candidate_count: ScalarStats,
    pub target_entropy_by_probability_source: BTreeMap<String, EntropyStats>,
    pub hard_target_count: usize,
    pub soft_target_count: usize,
    pub abstention_episode_count: usize,
    pub span_count: usize,
    pub relation_count: usize,
    pub evidence_link_count: usize,
    pub renderer_counts: BTreeMap<String, usize>,
    pub domain_counts: BTreeMap<String, usize>,
}

pub fn census(episodes: &[CanonicalEpisode]) -> SemanticCensus {
    let mut report = SemanticCensus {
        episode_count: episodes.len(),
        ..SemanticCensus::default()
    };
    let mut candidate_values = Vec::with_capacity(episodes.len());
    let mut state_lengths = Vec::with_capacity(episodes.len());
    let mut schema_lengths = Vec::with_capacity(episodes.len());
    for episode in episodes {
        report.query_count += episode.queries.len();
        bump(
            &mut report.authority_counts,
            authority_name(&episode.authority.episode_authority_class).to_string(),
        );
        bump(
            &mut report.contract_status_counts,
            contract_status_name(&episode.contract_status).to_string(),
        );
        bump(
            &mut report.representation_counts,
            representation_name(&episode.state.representation).to_string(),
        );
        bump(
            &mut report.renderer_counts,
            episode.identity.surface_renderer_id.clone(),
        );
        bump(
            &mut report.domain_counts,
            episode.identity.domain_family_id.clone(),
        );
        candidate_values.push(episode.runtime_schema.candidates.len() as f64);
        state_lengths.push(episode.state.observable.content.len() as f64);
        schema_lengths.push(episode.runtime_schema.candidates.len() as f64);
        report.evidence_link_count += episode.evidence_links.len();
        if episode.queries.iter().any(|query| {
            matches!(
                query.view,
                jev_decision_world_v02::types::QueryView::Abstain
            )
        }) {
            report.abstention_episode_count += 1;
        }
        for query in &episode.queries {
            bump(&mut report.view_counts, view_name(&query.view).to_string());
        }
        for target in &episode.gold_targets {
            let source_name =
                probability_source_name(&target.probability_source.probability_source).to_string();
            bump(&mut report.probability_source_counts, source_name.clone());
            if matches!(
                target.probability_source.probability_source,
                ProbabilitySource::HardLabel | ProbabilitySource::NoProbability
            ) {
                report.hard_target_count += 1;
            } else {
                report.soft_target_count += 1;
            }
            if let Some(entropy) = target_entropy(&target.target) {
                push_distribution_stat(
                    &mut report.target_entropy_by_probability_source,
                    &source_name,
                    entropy,
                );
            }
            match &target.target {
                TargetPayload::SpanType { spans } => report.span_count += spans.len(),
                TargetPayload::Relation { relations } => report.relation_count += relations.len(),
                _ => {}
            }
        }
    }
    report.candidate_cardinality = stats(&candidate_values);
    report.state_length_bytes = stats(&state_lengths);
    report.schema_candidate_count = stats(&schema_lengths);
    report
}

fn target_entropy(target: &TargetPayload) -> Option<f64> {
    let mut values = Vec::new();
    match target {
        TargetPayload::Choice {
            distribution,
            other_probability,
            ..
        } => {
            if let Some(distribution) = distribution {
                values.extend(distribution.iter().map(|entry| entry.probability));
            }
            if let Some(other) = other_probability {
                values.push(*other);
            }
        }
        TargetPayload::Ordinal {
            distribution: Some(distribution),
            ..
        } => values.extend(distribution.iter().copied()),
        TargetPayload::IndependentApplicability { candidates } => {
            let mean_binary_entropy = candidates
                .iter()
                .filter_map(|entry| entry.probability)
                .map(|probability| {
                    let positive = if probability > 0.0 {
                        -probability * probability.ln()
                    } else {
                        0.0
                    };
                    let negative_probability = 1.0 - probability;
                    let negative = if negative_probability > 0.0 {
                        -negative_probability * negative_probability.ln()
                    } else {
                        0.0
                    };
                    positive + negative
                })
                .collect::<Vec<_>>();
            return if mean_binary_entropy.is_empty() {
                None
            } else {
                Some(mean_binary_entropy.iter().sum::<f64>() / mean_binary_entropy.len() as f64)
            };
        }
        TargetPayload::Abstention {
            distribution: Some(distribution),
            ..
        } => values.extend(distribution.iter().map(|entry| entry.probability)),
        TargetPayload::SpanType { spans } => {
            for span in spans {
                let probabilities: Vec<f64> = span
                    .type_targets
                    .iter()
                    .filter_map(|entry| entry.probability)
                    .collect();
                if !probabilities.is_empty() {
                    values.extend(probabilities);
                }
            }
        }
        _ => return None,
    }
    let sum: f64 = values.iter().sum();
    if sum <= 0.0 {
        return None;
    }
    Some(
        values
            .into_iter()
            .filter(|probability| *probability > 0.0)
            .map(|probability| {
                let normalized = probability / sum;
                -normalized * normalized.ln()
            })
            .sum(),
    )
}

fn push_distribution_stat(map: &mut BTreeMap<String, EntropyStats>, key: &str, value: f64) {
    let stats = map.entry(key.to_string()).or_default();
    stats.count += 1;
    stats.mean_entropy = Some(
        stats.mean_entropy.unwrap_or(0.0)
            + (value - stats.mean_entropy.unwrap_or(0.0)) / stats.count as f64,
    );
    stats.min_entropy = Some(stats.min_entropy.map_or(value, |old| old.min(value)));
    stats.max_entropy = Some(stats.max_entropy.map_or(value, |old| old.max(value)));
}

fn stats(values: &[f64]) -> ScalarStats {
    if values.is_empty() {
        return ScalarStats::default();
    }
    ScalarStats {
        count: values.len(),
        mean: Some(values.iter().sum::<f64>() / values.len() as f64),
        min: values.iter().copied().reduce(f64::min),
        max: values.iter().copied().reduce(f64::max),
    }
}

fn bump(map: &mut BTreeMap<String, usize>, key: String) {
    *map.entry(key).or_default() += 1;
}

fn authority_name(authority: &AuthorityClass) -> &'static str {
    match authority {
        AuthorityClass::Authoritative => "authoritative",
        AuthorityClass::ExternallyAnnotated => "externally_annotated",
        AuthorityClass::Adjudicated => "adjudicated",
        AuthorityClass::Weak => "weak",
        AuthorityClass::SyntheticControl => "synthetic_control",
        AuthorityClass::Unverified => "unverified",
    }
}

fn contract_status_name(status: &jev_decision_world_v02::types::ContractStatus) -> &'static str {
    match status {
        jev_decision_world_v02::types::ContractStatus::V1Compatible => "v1_compatible",
        jev_decision_world_v02::types::ContractStatus::V1PlusProposedE01 => "v1_plus_proposed_e01",
        jev_decision_world_v02::types::ContractStatus::V1PlusProposedE02 => "v1_plus_proposed_e02",
        jev_decision_world_v02::types::ContractStatus::V1PlusProposedE01E02 => {
            "v1_plus_proposed_e01_e02"
        }
    }
}

fn representation_name(
    representation: &jev_decision_world_v02::types::Representation,
) -> &'static str {
    match representation {
        jev_decision_world_v02::types::Representation::Prose => "prose",
        jev_decision_world_v02::types::Representation::Json => "json",
        jev_decision_world_v02::types::Representation::Table => "table",
        jev_decision_world_v02::types::Representation::EventStream => "event_stream",
        jev_decision_world_v02::types::Representation::KeyValue => "key_value",
        jev_decision_world_v02::types::Representation::Dialogue => "dialogue",
    }
}

fn view_name(view: &jev_decision_world_v02::types::QueryView) -> &'static str {
    match view {
        jev_decision_world_v02::types::QueryView::Choice => "choice",
        jev_decision_world_v02::types::QueryView::IndependentApplicability => {
            "independent_applicability"
        }
        jev_decision_world_v02::types::QueryView::OrdinalScore => "ordinal_score",
        jev_decision_world_v02::types::QueryView::Abstain => "abstain",
        jev_decision_world_v02::types::QueryView::SpanType => "span_type",
        jev_decision_world_v02::types::QueryView::Relation => "relation",
    }
}

fn probability_source_name(source: &ProbabilitySource) -> &'static str {
    match source {
        ProbabilitySource::ExactGenerativePosterior => "exact_generative_posterior",
        ProbabilitySource::EmpiricalAnnotatorDistribution => "empirical_annotator_distribution",
        ProbabilitySource::ElicitedSubjectiveProbability => "elicited_subjective_probability",
        ProbabilitySource::AdjudicatedDistribution => "adjudicated_distribution",
        ProbabilitySource::HardLabel => "hard_label",
        ProbabilitySource::WeakScore => "weak_score",
        ProbabilitySource::NoProbability => "no_probability",
    }
}
