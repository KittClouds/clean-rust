use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use jev_decision_world_v02::types::CanonicalEpisode;

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct CollisionGroup {
    pub key: String,
    pub episode_ids: Vec<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct OverlapReport {
    pub exact_text_collisions: Vec<CollisionGroup>,
    pub normalized_text_collisions: Vec<CollisionGroup>,
    pub semantic_fingerprint_collisions: Vec<CollisionGroup>,
    pub lineage_collisions: Vec<CollisionGroup>,
    pub warnings: Vec<String>,
}

pub fn audit(episodes: &[CanonicalEpisode]) -> OverlapReport {
    let exact = group_by(episodes, |episode| episode.state.observable.content.clone());
    let normalized = group_by(episodes, |episode| {
        normalize_text(&episode.state.observable.content)
    });
    let fingerprints = group_by(episodes, |episode| {
        episode.identity.semantic_fingerprint.clone()
    });
    let lineage = group_by(episodes, |episode| {
        episode
            .authority_records
            .first()
            .map(|record| {
                format!(
                    "{}:{}:{}",
                    record.lineage.source_dataset_id,
                    record.lineage.source_revision,
                    record.lineage.source_row_id
                )
            })
            .unwrap_or_else(|| "missing-lineage".to_string())
    });
    let exact_text_collisions = collisions(exact);
    let normalized_text_collisions = collisions(normalized);
    let semantic_fingerprint_collisions = collisions(fingerprints);
    let lineage_collisions = collisions(lineage);
    let mut warnings = Vec::new();
    if !exact_text_collisions.is_empty() {
        warnings.push("same observable text appears in multiple normalized episodes".to_string());
    }
    if !normalized_text_collisions.is_empty() {
        warnings.push("whitespace/case-normalized text collision detected".to_string());
    }
    if !lineage_collisions.is_empty() {
        warnings.push(
            "same source lineage appears more than once; keep the group together for splits"
                .to_string(),
        );
    }
    OverlapReport {
        exact_text_collisions,
        normalized_text_collisions,
        semantic_fingerprint_collisions,
        lineage_collisions,
        warnings,
    }
}

fn group_by<F>(episodes: &[CanonicalEpisode], mut key_fn: F) -> BTreeMap<String, Vec<String>>
where
    F: FnMut(&CanonicalEpisode) -> String,
{
    let mut groups = BTreeMap::new();
    for episode in episodes {
        groups
            .entry(key_fn(episode))
            .or_insert_with(Vec::new)
            .push(episode.identity.episode_id.clone());
    }
    groups
}

fn collisions(groups: BTreeMap<String, Vec<String>>) -> Vec<CollisionGroup> {
    groups
        .into_iter()
        .filter(|(_, ids)| ids.len() > 1)
        .map(|(key, episode_ids)| CollisionGroup {
            key: blake3::hash(key.as_bytes()).to_hex().to_string(),
            episode_ids,
        })
        .collect()
}

fn normalize_text(text: &str) -> String {
    text.split_whitespace()
        .map(|part| part.to_ascii_lowercase())
        .collect::<Vec<_>>()
        .join(" ")
}
