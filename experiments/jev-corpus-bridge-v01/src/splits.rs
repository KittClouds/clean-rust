use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use jev_decision_world_v02::types::{
    AuthorityClass, CanonicalEpisode, ProbabilitySource, QueryView,
};

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct SplitManifest {
    pub manifest_id: String,
    pub policy: String,
    pub group_key_by_episode: BTreeMap<String, String>,
    pub regimes: BTreeMap<String, Vec<String>>,
    pub warnings: Vec<String>,
}

pub fn build(episodes: &[CanonicalEpisode]) -> SplitManifest {
    let mut manifest = SplitManifest {
        manifest_id: "jev-mixed-pilot-v0.2-splits".to_string(),
        policy: "lineage-and-family-grouped; no random row split".to_string(),
        ..SplitManifest::default()
    };
    for regime in [
        "in_distribution_validation",
        "surface_ood",
        "schema_ood",
        "candidate_ood",
        "world_ood",
        "domain_ood",
        "human_uncertainty_eval",
        "synthetic_calibration_eval",
        "abstention_eval",
        "span_relation_eval",
    ] {
        manifest.regimes.entry(regime.to_string()).or_default();
    }
    for episode in episodes {
        let group_key = group_key(episode);
        manifest
            .group_key_by_episode
            .insert(episode.identity.episode_id.clone(), group_key);
        for regime in regimes_for(episode) {
            manifest
                .regimes
                .entry(regime)
                .or_default()
                .push(episode.identity.episode_id.clone());
        }
    }
    for ids in manifest.regimes.values_mut() {
        ids.sort();
        ids.dedup();
    }
    for (regime, ids) in &manifest.regimes {
        if ids.is_empty() && regime.ends_with("_ood") {
            manifest.warnings.push(format!(
                "{regime} is defined but empty in this pilot; no held-out OOD source was ingested"
            ));
        }
    }
    manifest
}

fn group_key(episode: &CanonicalEpisode) -> String {
    let perturbation = &episode.identity.perturbation_family_id;
    if perturbation != "none" {
        return format!("perturbation:{perturbation}");
    }
    if let Some(record) = episode.authority_records.first() {
        return format!(
            "lineage:{}:{}:{}",
            record.lineage.source_dataset_id,
            record.lineage.source_revision,
            record.lineage.source_row_id
        );
    }
    format!("world:{}", episode.identity.world_instance_id)
}

fn regimes_for(episode: &CanonicalEpisode) -> Vec<String> {
    let mut regimes = Vec::new();
    if episode.authority.episode_authority_class == AuthorityClass::SyntheticControl {
        regimes.push("synthetic_calibration_eval".to_string());
    }
    if episode.gold_targets.iter().any(|target| {
        target.probability_source.probability_source
            == ProbabilitySource::EmpiricalAnnotatorDistribution
    }) {
        regimes.push("human_uncertainty_eval".to_string());
    }
    if episode
        .queries
        .iter()
        .any(|query| query.view == QueryView::Abstain)
    {
        regimes.push("abstention_eval".to_string());
    }
    if episode
        .queries
        .iter()
        .any(|query| matches!(query.view, QueryView::SpanType | QueryView::Relation))
    {
        regimes.push("span_relation_eval".to_string());
    }
    if regimes.is_empty() {
        regimes.push("in_distribution_validation".to_string());
    }
    regimes
}
