use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};
use phoenix_types::EntityId;
use serde::{Deserialize, Serialize};

use super::{push_unique, ChunkSemanticBridgeCandidate, ChunkSemanticBridgeChunk};

pub const ENTITY_FREQUENCY_PROFILE_SCHEMA_VERSION: &str =
    "phoenix-chunk-semantic-bridge-entity-frequency/v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChunkSemanticBridgeSupportRole {
    Primary,
    Secondary,
    IncidentalRegistryWide,
    SemanticOnly,
}

impl ChunkSemanticBridgeSupportRole {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Primary => "primary",
            Self::Secondary => "secondary",
            Self::IncidentalRegistryWide => "incidental_registry_wide",
            Self::SemanticOnly => "semantic_only",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChunkSemanticBridgeEntityFrequencyProfile {
    pub schema_version: CompactString,
    pub entity_id: CompactString,
    pub chunk_document_frequency: usize,
    pub episode_document_frequency: usize,
    pub document_frequency: usize,
    pub total_chunks: usize,
    pub total_episodes: usize,
    pub total_documents: usize,
    pub chunk_specificity_millis: u16,
    pub episode_specificity_millis: u16,
    pub combined_specificity_millis: u16,
    pub registry_wide: bool,
}

pub fn build_chunk_semantic_bridge_entity_frequency_profiles(
    chunks: &[ChunkSemanticBridgeChunk<'_>],
) -> Vec<ChunkSemanticBridgeEntityFrequencyProfile> {
    EntityFrequencyIndex::new(chunks).profiles()
}

pub(super) struct EntityFrequencyIndex<'a> {
    profiles: HashMap<&'a EntityId, EntityFrequencyStats>,
    total_chunks: usize,
    total_episodes: usize,
    total_documents: usize,
    minimum_specificity_millis: u16,
}

#[derive(Clone, Copy, Debug, Default)]
struct EntityFrequencyStats {
    chunk_df: usize,
    episode_df: usize,
    document_df: usize,
    chunk_specificity_millis: u16,
    episode_specificity_millis: u16,
    combined_specificity_millis: u16,
}

impl<'a> EntityFrequencyIndex<'a> {
    pub(super) fn new(chunks: &'a [ChunkSemanticBridgeChunk<'a>]) -> Self {
        let mut chunk_df = HashMap::<&EntityId, usize>::new();
        let mut episodes = HashMap::<&EntityId, HashSet<&str>>::new();
        let mut documents = HashMap::<&EntityId, HashSet<&str>>::new();
        let mut all_episodes = HashSet::<&str>::new();
        let mut all_documents = HashSet::<&str>::new();

        for chunk in chunks {
            all_documents.insert(chunk.note_id);
            if let Some(episode_id) = chunk.episode_id {
                all_episodes.insert(episode_id);
            }
            let mut seen = HashSet::<&EntityId>::with_capacity(chunk.entity_ids.len());
            for entity_id in chunk.entity_ids {
                if !seen.insert(entity_id) {
                    continue;
                }
                *chunk_df.entry(entity_id).or_default() += 1;
                documents
                    .entry(entity_id)
                    .or_default()
                    .insert(chunk.note_id);
                if let Some(episode_id) = chunk.episode_id {
                    episodes.entry(entity_id).or_default().insert(episode_id);
                }
            }
        }

        let total_chunks = chunks.len();
        let total_episodes = all_episodes.len();
        let total_documents = all_documents.len();
        let mut profiles = HashMap::with_capacity(chunk_df.len());
        for (entity_id, entity_chunk_df) in chunk_df {
            let episode_df = episodes.get(entity_id).map_or(0, HashSet::len);
            let document_df = documents.get(entity_id).map_or(0, HashSet::len);
            let chunk_specificity_millis = normalized_idf_millis(total_chunks, entity_chunk_df);
            let episode_specificity_millis = if total_episodes == 0 || episode_df == 0 {
                chunk_specificity_millis
            } else {
                normalized_idf_millis(total_episodes, episode_df)
            };
            let combined_specificity_millis =
                geometric_mean_millis(chunk_specificity_millis, episode_specificity_millis);
            profiles.insert(
                entity_id,
                EntityFrequencyStats {
                    chunk_df: entity_chunk_df,
                    episode_df,
                    document_df,
                    chunk_specificity_millis,
                    episode_specificity_millis,
                    combined_specificity_millis,
                },
            );
        }

        let minimum_specificity_millis = profiles
            .values()
            .map(|profile| profile.combined_specificity_millis)
            .min()
            .unwrap_or_default();
        Self {
            profiles,
            total_chunks,
            total_episodes,
            total_documents,
            minimum_specificity_millis,
        }
    }

    pub(super) fn specificity_millis(&self, entity_id: &EntityId) -> u16 {
        self.profiles
            .get(entity_id)
            .map_or(0, |profile| profile.combined_specificity_millis)
    }

    pub(super) fn is_registry_wide(&self, entity_id: &EntityId) -> bool {
        self.total_documents > 1
            && self
                .profiles
                .get(entity_id)
                .is_some_and(|profile| profile.document_df == self.total_documents)
    }

    pub(super) fn all_frequency_floor(&self, entities: &[&EntityId]) -> bool {
        !entities.is_empty()
            && entities
                .iter()
                .all(|entity_id| self.is_frequency_floor(entity_id))
    }

    pub(super) fn is_frequency_floor(&self, entity_id: &EntityId) -> bool {
        self.specificity_millis(entity_id) == self.minimum_specificity_millis
    }

    pub(super) fn primary<'b>(&self, entities: &[&'b EntityId]) -> Option<&'b EntityId> {
        entities.iter().copied().max_by(|left, right| {
            self.specificity_millis(left)
                .cmp(&self.specificity_millis(right))
                .then_with(|| right.0.cmp(&left.0))
        })
    }

    pub(super) fn attach_support_receipts(
        &self,
        bridge: &mut ChunkSemanticBridgeCandidate,
        entities: &[&EntityId],
    ) -> Option<CompactString> {
        push_unique(
            &mut bridge.rationale,
            format_compact!("entity_frequency_profile:{ENTITY_FREQUENCY_PROFILE_SCHEMA_VERSION}"),
        );
        let Some(primary) = self.primary(entities) else {
            push_unique(
                &mut bridge.rationale,
                format_compact!(
                    "support_role:{}",
                    ChunkSemanticBridgeSupportRole::SemanticOnly.as_str()
                ),
            );
            return None;
        };
        let primary_specificity = self.specificity_millis(primary);
        push_unique(
            &mut bridge.rationale,
            format_compact!("primary_support_entity:{}", primary.0),
        );
        push_unique(
            &mut bridge.rationale,
            format_compact!("primary_support_specificity_millis:{primary_specificity}"),
        );

        let mut ordered = entities.to_vec();
        ordered.sort_by(|left, right| left.0.cmp(&right.0));
        for entity_id in ordered {
            let stats = self.profiles.get(entity_id).copied().unwrap_or_default();
            let role = if entity_id == primary {
                ChunkSemanticBridgeSupportRole::Primary
            } else if self.is_registry_wide(entity_id) {
                ChunkSemanticBridgeSupportRole::IncidentalRegistryWide
            } else {
                ChunkSemanticBridgeSupportRole::Secondary
            };
            push_unique(
                &mut bridge.rationale,
                format_compact!("support_role:{}:{}", role.as_str(), entity_id.0),
            );
            push_unique(
                &mut bridge.rationale,
                format_compact!(
                    "entity_frequency_receipt:{}|chunks={}|episodes={}|documents={}|specificity={}",
                    entity_id.0,
                    stats.chunk_df,
                    stats.episode_df,
                    stats.document_df,
                    stats.combined_specificity_millis
                ),
            );
        }
        Some(primary.0.as_str().into())
    }

    pub(super) fn attach_candidate_support_receipts(
        &self,
        bridge: &mut ChunkSemanticBridgeCandidate,
    ) {
        let entities = bridge
            .supporting_entity_ids
            .iter()
            .filter_map(|entity_id| {
                self.profiles
                    .keys()
                    .copied()
                    .find(|candidate| candidate.0 == entity_id)
            })
            .collect::<Vec<_>>();
        self.attach_support_receipts(bridge, &entities);
    }

    fn profiles(&self) -> Vec<ChunkSemanticBridgeEntityFrequencyProfile> {
        let mut rows = self
            .profiles
            .iter()
            .map(
                |(entity_id, stats)| ChunkSemanticBridgeEntityFrequencyProfile {
                    schema_version: ENTITY_FREQUENCY_PROFILE_SCHEMA_VERSION.into(),
                    entity_id: entity_id.0.as_str().into(),
                    chunk_document_frequency: stats.chunk_df,
                    episode_document_frequency: stats.episode_df,
                    document_frequency: stats.document_df,
                    total_chunks: self.total_chunks,
                    total_episodes: self.total_episodes,
                    total_documents: self.total_documents,
                    chunk_specificity_millis: stats.chunk_specificity_millis,
                    episode_specificity_millis: stats.episode_specificity_millis,
                    combined_specificity_millis: stats.combined_specificity_millis,
                    registry_wide: self.is_registry_wide(entity_id),
                },
            )
            .collect::<Vec<_>>();
        rows.sort_by(|left, right| left.entity_id.cmp(&right.entity_id));
        rows
    }
}

fn normalized_idf_millis(total: usize, document_frequency: usize) -> u16 {
    if total <= 1 || document_frequency == 0 {
        return 1_000;
    }
    let numerator = ((total + 1) as f64 / (document_frequency + 1) as f64).ln();
    let denominator = ((total + 1) as f64).ln();
    ((numerator / denominator).clamp(0.0, 1.0) * 1_000.0).round() as u16
}

fn geometric_mean_millis(left: u16, right: u16) -> u16 {
    ((f64::from(left) * f64::from(right)).sqrt().round()) as u16
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn profile_is_corpus_derived_and_name_agnostic() {
        let frequent = EntityId("character:frequent".to_owned());
        let rare = EntityId("location:rare".to_owned());
        let both = vec![frequent.clone(), rare.clone()];
        let only_frequent = vec![frequent];
        let chunks = vec![
            chunk("a:chunk:0", "a", "episode:a", &both),
            chunk("a:chunk:1", "a", "episode:a", &only_frequent),
            chunk("b:chunk:0", "b", "episode:b", &only_frequent),
        ];

        let profiles = build_chunk_semantic_bridge_entity_frequency_profiles(&chunks);
        let frequent = profiles
            .iter()
            .find(|row| row.entity_id == "character:frequent")
            .unwrap();
        let rare = profiles
            .iter()
            .find(|row| row.entity_id == "location:rare")
            .unwrap();

        assert!(frequent.registry_wide);
        assert!(!rare.registry_wide);
        assert!(rare.combined_specificity_millis > frequent.combined_specificity_millis);
    }

    fn chunk<'a>(
        id: &'a str,
        note_id: &'a str,
        episode_id: &'a str,
        entity_ids: &'a [EntityId],
    ) -> ChunkSemanticBridgeChunk<'a> {
        ChunkSemanticBridgeChunk {
            id,
            note_id,
            ordinal: 0,
            text: "",
            role: None,
            episode_id: Some(episode_id),
            entity_ids,
            evidence_ids: &[],
        }
    }
}
