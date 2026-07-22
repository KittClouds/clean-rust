use compact_str::CompactString;
use hashbrown::HashMap;
use phoenix_graph_rebuild::{
    ContinuityEventIdentity, ContinuityStateIntervalCandidate, StoryContinuityContract,
    StoryEpisodeCandidate,
};
use phoenix_types::{DocumentId, EntityId};
use smallvec::SmallVec;

use crate::{
    IdentityFingerprint, RevisionIdentityKind, RevisionIdentityRecord, RevisionIdentitySnapshot,
};

pub fn story_continuity_identity_snapshot(
    revision: u64,
    contract: &StoryContinuityContract,
) -> RevisionIdentitySnapshot {
    let event_fingerprints = contract
        .events
        .iter()
        .map(|event| (event.id.as_str(), event_fingerprint(event)))
        .collect::<HashMap<_, _>>();
    let event_neighbors = event_neighbor_fingerprints(contract, &event_fingerprints);
    let mut records = Vec::with_capacity(
        contract.episodes.len() + contract.events.len() + contract.state_intervals.len(),
    );

    records.extend(
        contract
            .episodes
            .iter()
            .map(|episode| scene_record(episode, &event_fingerprints, &event_neighbors)),
    );
    records.extend(contract.events.iter().map(|event| {
        event_record(
            event,
            event_fingerprints[&event.id.as_str()],
            event_neighbors
                .get(event.id.as_str())
                .cloned()
                .unwrap_or_default(),
        )
    }));
    records.extend(
        contract
            .state_intervals
            .iter()
            .map(|state| state_record(state, &event_fingerprints)),
    );
    RevisionIdentitySnapshot { revision, records }
}

fn scene_record(
    episode: &StoryEpisodeCandidate,
    event_fingerprints: &HashMap<&str, IdentityFingerprint>,
    event_neighbors: &HashMap<&str, SmallVec<[IdentityFingerprint; 4]>>,
) -> RevisionIdentityRecord {
    let mut anchors = episode
        .event_ids
        .iter()
        .filter_map(|event_id| event_fingerprints.get(event_id.as_str()).copied())
        .collect::<SmallVec<[_; 4]>>();
    anchors.sort_unstable();
    anchors.dedup();
    let mut neighbors = episode
        .event_ids
        .iter()
        .filter_map(|event_id| event_neighbors.get(event_id.as_str()))
        .flatten()
        .copied()
        .collect::<SmallVec<[_; 4]>>();
    neighbors.sort_unstable();
    neighbors.dedup();

    RevisionIdentityRecord {
        stable_id: episode.id.clone(),
        kind: RevisionIdentityKind::Scene,
        document_id: DocumentId(episode.note_id.to_string()),
        semantic_fingerprint: fingerprint_parts(
            b"scene",
            std::iter::once(episode.label.as_bytes())
                .chain(anchors.iter().map(|fingerprint| fingerprint.0.as_slice())),
        ),
        evidence_anchor_fingerprints: anchors,
        participant_entity_ids: episode
            .entity_ids
            .iter()
            .map(|entity_id| EntityId(entity_id.to_string()))
            .collect(),
        neighbor_event_fingerprints: neighbors,
        source_start: episode.source_start,
        source_end: episode.source_end,
    }
}

fn event_record(
    event: &ContinuityEventIdentity,
    semantic_fingerprint: IdentityFingerprint,
    neighbor_event_fingerprints: SmallVec<[IdentityFingerprint; 4]>,
) -> RevisionIdentityRecord {
    RevisionIdentityRecord {
        stable_id: event.id.clone(),
        kind: RevisionIdentityKind::Event,
        document_id: DocumentId(event.note_id.to_string()),
        semantic_fingerprint,
        evidence_anchor_fingerprints: SmallVec::new(),
        participant_entity_ids: event
            .participant_entity_ids
            .iter()
            .map(|entity_id| EntityId(entity_id.to_string()))
            .collect(),
        neighbor_event_fingerprints,
        source_start: event.source_start,
        source_end: event.source_end,
    }
}

fn state_record(
    state: &ContinuityStateIntervalCandidate,
    event_fingerprints: &HashMap<&str, IdentityFingerprint>,
) -> RevisionIdentityRecord {
    let mut neighbors = SmallVec::new();
    if let Some(fingerprint) = event_fingerprints.get(state.start_event_id.as_str()) {
        neighbors.push(*fingerprint);
    }
    if let Some(end_event_id) = &state.end_event_id {
        if let Some(fingerprint) = event_fingerprints.get(end_event_id.as_str()) {
            neighbors.push(*fingerprint);
        }
    }
    neighbors.sort_unstable();
    neighbors.dedup();
    let value = state.value.as_deref().unwrap_or("none");

    RevisionIdentityRecord {
        stable_id: state.id.clone(),
        kind: RevisionIdentityKind::Fact,
        document_id: DocumentId(state.note_id.to_string()),
        semantic_fingerprint: fingerprint_parts(
            b"fact",
            [
                state.subject_key.as_bytes(),
                state.state_key.as_bytes(),
                value.as_bytes(),
                state.polarity.as_bytes(),
            ],
        ),
        evidence_anchor_fingerprints: SmallVec::new(),
        participant_entity_ids: smallvec::smallvec![EntityId(state.subject_key.to_string())],
        neighbor_event_fingerprints: neighbors,
        source_start: state.source_start,
        source_end: state.source_end.unwrap_or(state.source_start),
    }
}

fn event_fingerprint(event: &ContinuityEventIdentity) -> IdentityFingerprint {
    let mut participants = event
        .participant_entity_ids
        .iter()
        .map(CompactString::as_bytes)
        .collect::<Vec<_>>();
    participants.sort_unstable();
    let parts = std::iter::once(event.predicate.as_bytes())
        .chain(std::iter::once(event.factuality.as_bytes()))
        .chain(participants);
    fingerprint_parts(b"event", parts)
}

fn event_neighbor_fingerprints<'a>(
    contract: &'a StoryContinuityContract,
    event_fingerprints: &HashMap<&'a str, IdentityFingerprint>,
) -> HashMap<&'a str, SmallVec<[IdentityFingerprint; 4]>> {
    let mut neighbors = HashMap::<&str, SmallVec<[IdentityFingerprint; 4]>>::new();
    for episode in &contract.episodes {
        let episode_context = fingerprint_parts(b"episode-context", [episode.label.as_bytes()]);
        for (index, event_id) in episode.event_ids.iter().enumerate() {
            let row = neighbors.entry(event_id.as_str()).or_default();
            row.push(episode_context);
            if index > 0 {
                if let Some(fingerprint) =
                    event_fingerprints.get(episode.event_ids[index - 1].as_str())
                {
                    row.push(*fingerprint);
                }
            }
            if let Some(next) = episode.event_ids.get(index + 1) {
                if let Some(fingerprint) = event_fingerprints.get(next.as_str()) {
                    row.push(*fingerprint);
                }
            }
            row.sort_unstable();
            row.dedup();
        }
    }
    neighbors
}

fn fingerprint_parts<'a>(
    domain: &[u8],
    parts: impl IntoIterator<Item = &'a [u8]>,
) -> IdentityFingerprint {
    let mut hasher = blake3::Hasher::new();
    hash_part(&mut hasher, domain);
    for part in parts {
        hash_part(&mut hasher, part);
    }
    IdentityFingerprint(*hasher.finalize().as_bytes())
}

fn hash_part(hasher: &mut blake3::Hasher, bytes: &[u8]) {
    hasher.update(&(bytes.len() as u64).to_le_bytes());
    hasher.update(bytes);
}

#[cfg(test)]
#[path = "adapter_tests.rs"]
mod tests;
