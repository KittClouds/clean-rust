use compact_str::CompactString;
use hashbrown::HashMap;
use phoenix_types::EntityId;

use crate::types::{GraphRebuildSnapshot, GraphTemporalEdge};

use super::{
    build_chunk_semantic_bridge_run, ChunkSemanticBridgeCandidate, ChunkSemanticBridgeChunk,
    ChunkSemanticBridgeEngineInput, ChunkSemanticBridgeEntity, ChunkSemanticBridgeEvent,
    ChunkSemanticBridgeEventEdge, ChunkSemanticBridgeEvidence, ChunkSemanticBridgeRun,
};

#[derive(Clone, Copy, Debug)]
pub struct ChunkSemanticBridgeSnapshotDocument<'a> {
    pub note_id: &'a str,
    pub text: &'a str,
}

pub fn build_chunk_semantic_bridge_candidates_from_snapshot<'a>(
    snapshot: &'a GraphRebuildSnapshot,
    documents: &'a [ChunkSemanticBridgeSnapshotDocument<'a>],
) -> Vec<ChunkSemanticBridgeCandidate> {
    build_chunk_semantic_bridge_run_from_snapshot(snapshot, documents).candidates
}

pub fn build_chunk_semantic_bridge_run_from_snapshot<'a>(
    snapshot: &'a GraphRebuildSnapshot,
    documents: &'a [ChunkSemanticBridgeSnapshotDocument<'a>],
) -> ChunkSemanticBridgeRun {
    let texts = documents
        .iter()
        .map(|document| (document.note_id, document.text))
        .collect::<HashMap<_, _>>();
    let document_order = documents
        .iter()
        .enumerate()
        .map(|(index, document)| (document.note_id, index))
        .collect::<HashMap<_, _>>();
    let event_by_id = snapshot
        .events
        .iter()
        .map(|event| (event.id.as_str(), event))
        .collect::<HashMap<_, _>>();
    let episode_by_chunk = episode_ids_by_chunk(snapshot, &event_by_id);
    let (entities_by_chunk, evidence_by_chunk) = chunk_anchor_indexes(snapshot);

    let mut chunks = snapshot
        .chunks
        .iter()
        .map(|chunk| {
            let text = texts
                .get(chunk.note_id.as_str())
                .and_then(|text| chunk_text(text, chunk.start, chunk.end))
                .unwrap_or_default();
            ChunkSemanticBridgeChunk {
                id: chunk.id.as_str(),
                note_id: chunk.note_id.as_str(),
                ordinal: chunk.ordinal,
                text,
                role: None,
                episode_id: episode_by_chunk
                    .get(chunk.id.as_str())
                    .map(|id| id.as_str()),
                entity_ids: entities_by_chunk
                    .get(chunk.id.as_str())
                    .map(Vec::as_slice)
                    .unwrap_or(&[]),
                evidence_ids: evidence_by_chunk
                    .get(chunk.id.as_str())
                    .map(Vec::as_slice)
                    .unwrap_or(&[]),
            }
        })
        .collect::<Vec<_>>();
    chunks.sort_by(|left, right| {
        document_order
            .get(left.note_id)
            .copied()
            .unwrap_or(usize::MAX)
            .cmp(
                &document_order
                    .get(right.note_id)
                    .copied()
                    .unwrap_or(usize::MAX),
            )
            .then_with(|| left.ordinal.cmp(&right.ordinal))
            .then_with(|| left.id.cmp(right.id))
    });

    let events = snapshot
        .events
        .iter()
        .map(|event| ChunkSemanticBridgeEvent {
            id: event.id.as_str(),
            note_id: event.note_id.as_str(),
            chunk_id: event.chunk_id.as_deref(),
            label: event.label.as_str(),
            entity_ids: event.entity_ids.as_slice(),
            evidence_ids: event.evidence_anchor_ids.as_slice(),
            confidence: event.confidence,
        })
        .collect::<Vec<_>>();
    let temporal_edges = event_edges(&snapshot.temporal_edges);
    let causal_edges = event_edges(&snapshot.causal_edges);
    let entities = snapshot
        .nodes
        .iter()
        .map(|node| ChunkSemanticBridgeEntity {
            id: &node.entity_id,
            label: node.label.as_str(),
            kind: Some(node.kind.as_str()),
        })
        .collect::<Vec<_>>();
    let evidence = snapshot_evidence(snapshot);

    build_chunk_semantic_bridge_run(ChunkSemanticBridgeEngineInput {
        chunks: chunks.as_slice(),
        events: events.as_slice(),
        entities: entities.as_slice(),
        evidence: evidence.as_slice(),
        temporal_edges: temporal_edges.as_slice(),
        causal_edges: causal_edges.as_slice(),
    })
}

fn chunk_anchor_indexes(
    snapshot: &GraphRebuildSnapshot,
) -> (
    HashMap<&str, Vec<EntityId>>,
    HashMap<&str, Vec<CompactString>>,
) {
    let mut entities_by_chunk = HashMap::<&str, Vec<EntityId>>::new();
    let mut evidence_by_chunk = HashMap::<&str, Vec<CompactString>>::new();
    for anchor in &snapshot.entity_anchors {
        let Some(chunk_id) = anchor.chunk_id.as_deref() else {
            continue;
        };
        push_entity_unique(
            entities_by_chunk.entry(chunk_id).or_default(),
            anchor.entity_id.clone(),
        );
        push_unique(
            evidence_by_chunk.entry(chunk_id).or_default(),
            anchor.id.clone(),
        );
    }
    (entities_by_chunk, evidence_by_chunk)
}

fn episode_ids_by_chunk<'a>(
    snapshot: &'a GraphRebuildSnapshot,
    event_by_id: &HashMap<&'a str, &'a crate::types::GraphEvent>,
) -> HashMap<&'a str, &'a CompactString> {
    let mut out = HashMap::<&str, &CompactString>::new();
    for episode in &snapshot.episodes {
        for event_id in &episode.event_ids {
            let Some(event) = event_by_id.get(event_id.as_str()) else {
                continue;
            };
            if let Some(chunk_id) = event.chunk_id.as_deref() {
                out.entry(chunk_id).or_insert(&episode.id);
            }
        }
    }
    out
}

fn event_edges<'a>(edges: &'a [GraphTemporalEdge]) -> Vec<ChunkSemanticBridgeEventEdge<'a>> {
    edges
        .iter()
        .map(|edge| ChunkSemanticBridgeEventEdge {
            source_event_id: edge.source_id.as_str(),
            target_event_id: edge.target_id.as_str(),
            relation_type: edge.relation_type.as_str(),
            cue: None,
            evidence_ids: edge.evidence_ids.as_slice(),
            confidence: edge.confidence,
        })
        .collect()
}

fn snapshot_evidence(snapshot: &GraphRebuildSnapshot) -> Vec<ChunkSemanticBridgeEvidence<'_>> {
    let mut out = Vec::with_capacity(
        snapshot.entity_anchors.len() + snapshot.events.len() + snapshot.temporal_edges.len(),
    );
    out.extend(
        snapshot
            .entity_anchors
            .iter()
            .map(|anchor| ChunkSemanticBridgeEvidence {
                id: anchor.id.as_str(),
                source_id: Some(anchor.entity_id.0.as_str()),
                chunk_id: anchor.chunk_id.as_deref(),
                event_id: None,
            }),
    );
    out.extend(
        snapshot
            .events
            .iter()
            .map(|event| ChunkSemanticBridgeEvidence {
                id: event.id.as_str(),
                source_id: Some(event.id.as_str()),
                chunk_id: event.chunk_id.as_deref(),
                event_id: Some(event.id.as_str()),
            }),
    );
    out
}

fn chunk_text(text: &str, start: u32, end: u32) -> Option<&str> {
    let start = start as usize;
    let end = end as usize;
    text.get(start..end).or_else(|| {
        let start_byte = utf16_offset_to_byte(text, start)?;
        let end_byte = utf16_offset_to_byte(text, end)?;
        text.get(start_byte..end_byte)
    })
}

fn utf16_offset_to_byte(text: &str, target: usize) -> Option<usize> {
    let mut offset = 0usize;
    for (byte, character) in text.char_indices() {
        if offset == target {
            return Some(byte);
        }
        offset += character.len_utf16();
        if offset > target {
            return None;
        }
    }
    (offset == target).then_some(text.len())
}

fn push_unique(out: &mut Vec<CompactString>, value: CompactString) {
    if !out.iter().any(|existing| existing == &value) {
        out.push(value);
    }
}

fn push_entity_unique(out: &mut Vec<EntityId>, value: EntityId) {
    if !out.iter().any(|existing| existing == &value) {
        out.push(value);
    }
}
