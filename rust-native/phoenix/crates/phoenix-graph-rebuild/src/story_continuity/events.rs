use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};

use crate::{DocumentSemanticSummary, GraphChunk, GraphRebuildSnapshot};

use super::types::{ContinuityEventIdentity, ContinuityStatus};

pub(super) struct EventBuild {
    pub events: Vec<ContinuityEventIdentity>,
    pub situation_to_event: HashMap<CompactString, CompactString>,
    pub legacy_to_event: HashMap<CompactString, CompactString>,
}

pub(super) fn canonical_events(
    snapshot: &GraphRebuildSnapshot,
    semantic: Option<&DocumentSemanticSummary>,
) -> EventBuild {
    let mut events = Vec::new();
    let mut situation_to_event = HashMap::new();
    let mut legacy_to_event = HashMap::new();
    let mut semantic_notes = HashSet::<&str>::new();

    for document in semantic.into_iter().flat_map(|summary| &summary.documents) {
        semantic_notes.insert(document.note_id.as_str());
        for situation in &document.situations {
            let Some(chunk) =
                chunk_for_offset(&snapshot.chunks, &situation.note_id, situation.start)
            else {
                continue;
            };
            let id = event_id(
                &situation.note_id,
                situation.start,
                situation.end,
                &situation.predicate,
                &situation.participant_entity_ids,
            );
            let evidence_ids = snapshot
                .entity_anchors
                .iter()
                .filter(|anchor| {
                    anchor.note_id.as_str() == situation.note_id
                        && ranges_overlap(
                            anchor.source_start as usize,
                            anchor.source_end as usize,
                            situation.start,
                            situation.end,
                        )
                })
                .map(|anchor| anchor.id.clone())
                .collect();
            situation_to_event.insert(situation.id.clone().into(), id.clone());
            events.push(ContinuityEventIdentity {
                id,
                source_situation_id: Some(situation.id.clone().into()),
                source_event_id: None,
                note_id: situation.note_id.clone().into(),
                chunk_id: chunk.id.clone(),
                source_start: clamp_u32(situation.start),
                source_end: clamp_u32(situation.end),
                predicate: situation.predicate.clone().into(),
                participant_entity_ids: sorted_unique(
                    situation
                        .participant_entity_ids
                        .iter()
                        .map(CompactString::from)
                        .collect(),
                ),
                evidence_ids,
                factuality: situation.factuality.clone().into(),
                confidence_millis: situation.confidence_millis,
                status: if situation.world_state_eligible {
                    ContinuityStatus::Candidate
                } else {
                    ContinuityStatus::ReviewRequired
                },
                no_topology_commit: true,
            });
        }
    }

    for event in &snapshot.events {
        if semantic_notes.contains(event.note_id.as_str()) {
            if let Some(canonical) = nearest_semantic_event(&events, event) {
                legacy_to_event.insert(event.id.clone(), canonical.id.clone());
            }
            continue;
        }
        let Some(chunk) = event
            .chunk_id
            .as_ref()
            .and_then(|id| snapshot.chunks.iter().find(|chunk| &chunk.id == id))
        else {
            continue;
        };
        let id = event_id(
            event.note_id.as_str(),
            chunk.start as usize,
            chunk.end as usize,
            event.label.as_str(),
            &event
                .entity_ids
                .iter()
                .map(|value| value.0.to_string())
                .collect::<Vec<_>>(),
        );
        legacy_to_event.insert(event.id.clone(), id.clone());
        events.push(ContinuityEventIdentity {
            id,
            source_situation_id: None,
            source_event_id: Some(event.id.clone()),
            note_id: event.note_id.clone(),
            chunk_id: chunk.id.clone(),
            source_start: chunk.start,
            source_end: chunk.end,
            predicate: event.label.clone(),
            participant_entity_ids: sorted_unique(
                event
                    .entity_ids
                    .iter()
                    .map(|value| CompactString::from(value.0.as_str()))
                    .collect(),
            ),
            evidence_ids: event.evidence_anchor_ids.clone(),
            factuality: "legacy_accepted".into(),
            confidence_millis: confidence_millis(event.confidence),
            status: ContinuityStatus::ReviewRequired,
            no_topology_commit: true,
        });
    }

    events.sort_by(|left, right| {
        left.note_id
            .cmp(&right.note_id)
            .then_with(|| left.source_start.cmp(&right.source_start))
            .then_with(|| left.source_end.cmp(&right.source_end))
            .then_with(|| left.id.cmp(&right.id))
    });
    events.dedup_by(|left, right| left.id == right.id);
    EventBuild {
        events,
        situation_to_event,
        legacy_to_event,
    }
}

fn nearest_semantic_event<'a>(
    events: &'a [ContinuityEventIdentity],
    event: &crate::GraphEvent,
) -> Option<&'a ContinuityEventIdentity> {
    let chunk_id = event.chunk_id.as_ref()?;
    events
        .iter()
        .filter(|candidate| candidate.note_id == event.note_id && candidate.chunk_id == *chunk_id)
        .max_by_key(|candidate| {
            candidate
                .participant_entity_ids
                .iter()
                .filter(|entity| {
                    event
                        .entity_ids
                        .iter()
                        .any(|other| other.0.as_str() == entity.as_str())
                })
                .count()
        })
}

fn chunk_for_offset<'a>(
    chunks: &'a [GraphChunk],
    note_id: &str,
    offset: usize,
) -> Option<&'a GraphChunk> {
    chunks
        .iter()
        .filter(|chunk| chunk.note_id.as_str() == note_id)
        .find(|chunk| chunk.start as usize <= offset && offset < chunk.end as usize)
        .or_else(|| {
            chunks
                .iter()
                .filter(|chunk| chunk.note_id.as_str() == note_id)
                .min_by_key(|chunk| (chunk.start as usize).abs_diff(offset))
        })
}

fn event_id(
    note_id: &str,
    start: usize,
    end: usize,
    predicate: &str,
    participants: &[impl AsRef<str>],
) -> CompactString {
    let mut hash = 2_166_136_261_u32;
    hash_bytes(&mut hash, predicate.as_bytes());
    for participant in participants {
        hash_bytes(&mut hash, participant.as_ref().as_bytes());
    }
    format_compact!("continuity:event:{note_id}:{start}:{end}:{hash:08x}")
}

fn hash_bytes(hash: &mut u32, bytes: &[u8]) {
    for byte in bytes {
        *hash ^= u32::from(*byte);
        *hash = hash.wrapping_mul(16_777_619);
    }
}

fn sorted_unique(mut values: Vec<CompactString>) -> Vec<CompactString> {
    values.sort();
    values.dedup();
    values
}

fn ranges_overlap(
    left_start: usize,
    left_end: usize,
    right_start: usize,
    right_end: usize,
) -> bool {
    left_start < right_end && right_start < left_end
}

fn confidence_millis(value: f32) -> u16 {
    (value.clamp(0.0, 1.0) * 1000.0).round() as u16
}

fn clamp_u32(value: usize) -> u32 {
    value.min(u32::MAX as usize) as u32
}
