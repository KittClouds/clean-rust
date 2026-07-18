use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};
use phoenix_graph_rebuild::{GraphRebuildSnapshot, GraphRelationship};

use crate::{InferenceAuthority, InferenceEdgeSeed, InferenceNodeSeed, InferenceProjectionInput};

/// Builds the normal model-facing graph lane from asserted graph-rebuild truth.
/// Non-accepted semantic relationships are retained only as filtered inputs so
/// the projection receipt can prove that no candidate relation reached the CSR.
pub fn graph_rebuild_asserted_inference_input(
    snapshot: &GraphRebuildSnapshot,
) -> InferenceProjectionInput {
    let embedding_text = accepted_embedding_text(snapshot);
    let mut accepted_nodes = Vec::with_capacity(
        snapshot.note_ids.len()
            + snapshot.chunks.len()
            + snapshot.nodes.len()
            + snapshot.events.len()
            + snapshot.episodes.len(),
    );
    accepted_nodes.extend(snapshot.note_ids.iter().map(|note_id| InferenceNodeSeed {
        node_id: document_node_id(note_id),
        node_type: "document".into(),
        embedding_text: embedding_text_for(&embedding_text, "note", note_id, note_id),
    }));
    accepted_nodes.extend(snapshot.chunks.iter().map(|chunk| InferenceNodeSeed {
        node_id: chunk_node_id(&chunk.id),
        node_type: "chunk".into(),
        embedding_text: embedding_text_for(&embedding_text, "chunk", &chunk.id, &chunk.id),
    }));
    accepted_nodes.extend(snapshot.nodes.iter().map(|node| InferenceNodeSeed {
        node_id: entity_node_id(&node.entity_id.0),
        node_type: "entity".into(),
        embedding_text: embedding_text_for(
            &embedding_text,
            "entity",
            &node.entity_id.0,
            &node.label,
        ),
    }));
    accepted_nodes.extend(snapshot.events.iter().map(|event| InferenceNodeSeed {
        node_id: event_node_id(&event.id),
        node_type: "event".into(),
        embedding_text: embedding_text_for(&embedding_text, "event", &event.id, &event.label),
    }));
    accepted_nodes.extend(snapshot.episodes.iter().map(|episode| InferenceNodeSeed {
        node_id: episode_node_id(&episode.id),
        node_type: "episode".into(),
        embedding_text: embedding_text_for(&embedding_text, "episode", &episode.id, &episode.label),
    }));

    let mut relations = Vec::with_capacity(
        snapshot.edges.len()
            + snapshot.relationships.len()
            + snapshot.temporal_edges.len()
            + snapshot.causal_edges.len(),
    );
    relations.extend(snapshot.edges.iter().map(|edge| InferenceEdgeSeed {
        edge_id: format_compact!("inference:structural:{}", edge.id),
        source_id: entity_node_id(&edge.source_id.0),
        target_id: entity_node_id(&edge.target_id.0),
        relation_type: edge.edge_type.clone(),
        authority: InferenceAuthority::Asserted,
        evidence_ids: edge.evidence_anchor_ids.clone(),
        confidence_millis: confidence_millis(edge.confidence),
    }));
    relations.extend(snapshot.relationships.iter().map(relationship_seed));
    relations.extend(
        snapshot
            .temporal_edges
            .iter()
            .map(|edge| InferenceEdgeSeed {
                edge_id: format_compact!("inference:temporal:{}", edge.id),
                source_id: event_node_id(&edge.source_id),
                target_id: event_node_id(&edge.target_id),
                relation_type: format_compact!("temporal:{}", edge.relation_type),
                authority: InferenceAuthority::Asserted,
                evidence_ids: edge.evidence_ids.clone(),
                confidence_millis: confidence_millis(edge.confidence),
            }),
    );
    relations.extend(snapshot.causal_edges.iter().map(|edge| InferenceEdgeSeed {
        edge_id: format_compact!("inference:causal:{}", edge.id),
        source_id: event_node_id(&edge.source_id),
        target_id: event_node_id(&edge.target_id),
        relation_type: format_compact!("causal:{}", edge.relation_type),
        authority: InferenceAuthority::Asserted,
        evidence_ids: edge.evidence_ids.clone(),
        confidence_millis: confidence_millis(edge.confidence),
    }));

    let mut memberships = Vec::with_capacity(
        snapshot.chunks.len()
            + snapshot
                .nodes
                .iter()
                .map(|node| node.note_ids.len())
                .sum::<usize>()
            + snapshot.episodes.len()
            + snapshot.events.len()
            + snapshot
                .episodes
                .iter()
                .map(|row| row.event_ids.len())
                .sum::<usize>(),
    );
    memberships.extend(snapshot.chunks.iter().map(|chunk| InferenceEdgeSeed {
        edge_id: format_compact!("inference:document_chunk:{}:{}", chunk.note_id, chunk.id),
        source_id: document_node_id(&chunk.note_id),
        target_id: chunk_node_id(&chunk.id),
        relation_type: "document_contains_chunk".into(),
        authority: InferenceAuthority::Asserted,
        evidence_ids: Vec::new(),
        confidence_millis: 1000,
    }));
    let note_ids = snapshot
        .note_ids
        .iter()
        .map(CompactString::as_str)
        .collect::<HashSet<_>>();
    memberships.extend(snapshot.nodes.iter().flat_map(|node| {
        node.note_ids
            .iter()
            .filter(|note_id| note_ids.contains(note_id.as_str()))
            .map(|note_id| InferenceEdgeSeed {
                edge_id: format_compact!(
                    "inference:document_entity:{}:{}",
                    note_id,
                    node.entity_id.0
                ),
                source_id: document_node_id(note_id),
                target_id: entity_node_id(&node.entity_id.0),
                relation_type: "document_contains_entity".into(),
                authority: InferenceAuthority::Asserted,
                evidence_ids: node.anchor_ids.clone(),
                confidence_millis: 1000,
            })
    }));
    memberships.extend(snapshot.episodes.iter().map(|episode| InferenceEdgeSeed {
        edge_id: format_compact!(
            "inference:document_episode:{}:{}",
            episode.note_id,
            episode.id
        ),
        source_id: document_node_id(&episode.note_id),
        target_id: episode_node_id(&episode.id),
        relation_type: "document_contains_episode".into(),
        authority: InferenceAuthority::Asserted,
        evidence_ids: Vec::new(),
        confidence_millis: 1000,
    }));
    memberships.extend(snapshot.events.iter().filter_map(|event| {
        event.chunk_id.as_ref().map(|chunk_id| InferenceEdgeSeed {
            edge_id: format_compact!("inference:chunk_event:{}:{}", chunk_id, event.id),
            source_id: chunk_node_id(chunk_id),
            target_id: event_node_id(&event.id),
            relation_type: "chunk_contains_event".into(),
            authority: InferenceAuthority::Asserted,
            evidence_ids: event.evidence_anchor_ids.clone(),
            confidence_millis: confidence_millis(event.confidence),
        })
    }));
    let event_ids = snapshot
        .events
        .iter()
        .map(|event| event.id.as_str())
        .collect::<HashSet<_>>();
    memberships.extend(snapshot.episodes.iter().flat_map(|episode| {
        episode
            .event_ids
            .iter()
            .filter(|event_id| event_ids.contains(event_id.as_str()))
            .map(|event_id| InferenceEdgeSeed {
                edge_id: format_compact!("inference:episode_event:{}:{}", episode.id, event_id),
                source_id: episode_node_id(&episode.id),
                target_id: event_node_id(event_id),
                relation_type: "episode_contains_event".into(),
                authority: InferenceAuthority::Asserted,
                evidence_ids: Vec::new(),
                confidence_millis: 1000,
            })
    }));

    InferenceProjectionInput {
        accepted_nodes,
        relations,
        memberships,
    }
}

fn accepted_embedding_text(
    snapshot: &GraphRebuildSnapshot,
) -> HashMap<(&str, &str), &CompactString> {
    snapshot
        .embedding_targets
        .iter()
        .filter(|target| {
            matches!(
                target.admission_status.as_deref(),
                None | Some("accepted" | "asserted" | "structural")
            ) && !target.text.is_empty()
        })
        .map(|target| {
            (
                (target.kind.as_str(), target.source_id.as_str()),
                &target.text,
            )
        })
        .collect()
}

fn embedding_text_for(
    texts: &HashMap<(&str, &str), &CompactString>,
    kind: &str,
    source_id: &str,
    fallback: &str,
) -> CompactString {
    texts
        .get(&(kind, source_id))
        .map_or_else(|| fallback.into(), |text| (*text).clone())
}

fn relationship_seed(relationship: &GraphRelationship) -> InferenceEdgeSeed {
    let authority = match relationship.status.as_str() {
        "accepted" => InferenceAuthority::Accepted,
        "rejected" => InferenceAuthority::Rejected,
        "review" | "candidate" | "candidate_overlay" => InferenceAuthority::Candidate,
        _ => InferenceAuthority::Candidate,
    };
    InferenceEdgeSeed {
        edge_id: format_compact!("inference:relationship:{}", relationship.id),
        source_id: entity_node_id(&relationship.source_entity_id.0),
        target_id: entity_node_id(&relationship.target_entity_id.0),
        relation_type: relationship.relation_type.clone(),
        authority,
        evidence_ids: relationship.evidence_anchor_ids.clone(),
        confidence_millis: confidence_millis(relationship.confidence),
    }
}

fn document_node_id(id: &str) -> CompactString {
    format_compact!("inference:document:{id}")
}

fn chunk_node_id(id: &str) -> CompactString {
    format_compact!("inference:chunk:{id}")
}

fn entity_node_id(id: &str) -> CompactString {
    format_compact!("inference:entity:{id}")
}

fn event_node_id(id: &str) -> CompactString {
    format_compact!("inference:event:{id}")
}

fn episode_node_id(id: &str) -> CompactString {
    format_compact!("inference:episode:{id}")
}

fn confidence_millis(value: f32) -> u16 {
    if !value.is_finite() {
        return 0;
    }
    (value.clamp(0.0, 1.0) * 1000.0).round() as u16
}

#[cfg(test)]
#[path = "inference_adapter_tests.rs"]
mod tests;
