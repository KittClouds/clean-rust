use std::collections::BTreeMap;

use compact_str::{format_compact, CompactString};

use crate::types::{
    GraphAnchor, GraphChunk, GraphEmbeddingTarget, GraphEvent, GraphMemoryState, GraphNode,
    GraphRelationship, GraphTemporalEdge,
};

mod snapshot_targets;
pub use snapshot_targets::build_snapshot_embedding_targets;

pub fn build_embedding_targets(
    note_id: &str,
    note_text: &str,
    chunks: &[GraphChunk],
    anchors: &[GraphAnchor],
    nodes: &[GraphNode],
    relationships: &[GraphRelationship],
    events: &[GraphEvent],
    temporal_edges: &[GraphTemporalEdge],
    causal_edges: &[GraphTemporalEdge],
    memory_state: &[GraphMemoryState],
) -> Vec<GraphEmbeddingTarget> {
    let mut targets = Vec::with_capacity(
        chunks.len()
            + anchors.len()
            + nodes.len()
            + relationships.len()
            + events.len()
            + temporal_edges.len()
            + causal_edges.len()
            + memory_state.len()
            + 6,
    );
    targets.push(GraphEmbeddingTarget {
        id: format_compact!("embed:note:{note_id}"),
        kind: "note".into(),
        source_id: note_id.into(),
        note_id: Some(note_id.into()),
        chunk_id: None,
        entity_id: None,
        label: format_compact!("Note {note_id}"),
        text: note_embedding_text(note_id, note_text),
        evidence_ids: Vec::new(),
        parent_ids: Vec::new(),
    });
    targets.extend(structure_root_targets(note_id));
    targets.extend(chunks.iter().map(|chunk| GraphEmbeddingTarget {
        id: format_compact!("embed:chunk:{}", chunk.id),
        kind: "chunk".into(),
        source_id: chunk.id.clone(),
        note_id: Some(chunk.note_id.clone()),
        chunk_id: Some(chunk.id.clone()),
        entity_id: None,
        label: format_compact!("Chunk {}", chunk.ordinal + 1),
        text: chunk_embedding_text(note_text, chunk),
        evidence_ids: Vec::new(),
        parent_ids: vec![structure_root_id(&chunk.note_id, "document-structure")],
    }));
    targets.extend(nodes.iter().map(|node| GraphEmbeddingTarget {
        id: format_compact!("embed:entity:{}", node.entity_id.0),
        kind: "entity".into(),
        source_id: node.entity_id.0.as_str().into(),
        note_id: None,
        chunk_id: None,
        entity_id: Some(node.entity_id.clone()),
        label: node.label.clone(),
        text: node.label.clone(),
        evidence_ids: node.anchor_ids.clone(),
        parent_ids: Vec::new(),
    }));
    targets.extend(representative_anchors(anchors).into_iter().map(|anchor| {
        GraphEmbeddingTarget {
            id: format_compact!("embed:anchor:{}", anchor.id),
            kind: "anchor".into(),
            source_id: anchor.id.clone(),
            note_id: Some(anchor.note_id.clone()),
            chunk_id: anchor.chunk_id.clone(),
            entity_id: Some(anchor.entity_id.clone()),
            label: anchor.surface.clone(),
            text: anchor.surface.clone(),
            evidence_ids: vec![anchor.id.clone()],
            parent_ids: vec![structure_root_id(&anchor.note_id, "evidence")],
        }
    }));
    targets.extend(
        relationships
            .iter()
            .filter(|relationship| relationship.status != "rejected")
            .filter(|relationship| {
                relationship.status == "accepted" || !is_weak_cooccurrence(relationship)
            })
            .map(|relationship| GraphEmbeddingTarget {
                id: format_compact!("embed:graph-fact:{}", relationship.id),
                kind: "graphFact".into(),
                source_id: relationship.id.clone(),
                note_id: None,
                chunk_id: None,
                entity_id: None,
                label: format_compact!(
                    "{} {} {}",
                    relationship.source_entity_id.0,
                    relationship.relation_type,
                    relationship.target_entity_id.0
                ),
                text: format_compact!(
                    "{} {} {} [{}]",
                    relationship.source_entity_id.0,
                    relationship.relation_type,
                    relationship.target_entity_id.0,
                    relationship.status
                ),
                evidence_ids: relationship.evidence_anchor_ids.clone(),
                parent_ids: Vec::new(),
            }),
    );
    targets.extend(events.iter().map(|event| GraphEmbeddingTarget {
        id: format_compact!("embed:event:{}", event.id),
        kind: "event".into(),
        source_id: event.id.clone(),
        note_id: Some(event.note_id.clone()),
        chunk_id: event.chunk_id.clone(),
        entity_id: event.entity_ids.first().cloned(),
        label: event.label.clone(),
        text: event.label.clone(),
        evidence_ids: event.evidence_anchor_ids.clone(),
        parent_ids: Vec::new(),
    }));
    targets.extend(
        temporal_edges
            .iter()
            .map(|edge| temporal_target(note_id, edge, "temporalFact")),
    );
    targets.extend(
        causal_edges
            .iter()
            .map(|edge| temporal_target(note_id, edge, "causalFact")),
    );
    targets.extend(memory_state.iter().map(|state| {
        GraphEmbeddingTarget {
            id: format_compact!("embed:memory:{}", state.id),
            kind: "memoryState".into(),
            source_id: state.id.clone(),
            note_id: state.note_id.clone(),
            chunk_id: None,
            entity_id: Some(state.entity_id.clone()),
            label: state.key.clone(),
            text: format_compact!("{} {}", state.key, state.value),
            evidence_ids: state.evidence_ids.clone(),
            parent_ids: state
                .note_id
                .as_ref()
                .map(|note_id| vec![structure_root_id(note_id, "identity")])
                .unwrap_or_default(),
        }
    }));
    targets
}

fn structure_root_targets(note_id: &str) -> Vec<GraphEmbeddingTarget> {
    [
        (
            "document-structure",
            "Document structure",
            "document spine and chunk hierarchy root",
        ),
        (
            "identity",
            "Identity root",
            "accepted entity and alias provenance root",
        ),
        (
            "temporal",
            "Temporal root",
            "event order and before/after signal root",
        ),
        (
            "causal",
            "Causal root",
            "cause, explanation, authority, and consequence signal root",
        ),
        (
            "evidence",
            "Evidence root",
            "raw anchor evidence and supporting context root",
        ),
    ]
    .into_iter()
    .map(|(key, label, text)| GraphEmbeddingTarget {
        id: format_compact!("embed:structure-root:{note_id}:{key}"),
        kind: "structureRoot".into(),
        source_id: format_compact!("{note_id}:{key}"),
        note_id: Some(note_id.into()),
        chunk_id: None,
        entity_id: None,
        label: label.into(),
        text: format_compact!("structure_root:{} note:{} {}", key, note_id, text),
        evidence_ids: Vec::new(),
        parent_ids: vec![format_compact!("embed:note:{note_id}")],
    })
    .collect()
}

fn representative_anchors(anchors: &[GraphAnchor]) -> Vec<&GraphAnchor> {
    let mut by_entity = BTreeMap::<&str, &GraphAnchor>::new();
    for anchor in anchors {
        by_entity
            .entry(anchor.entity_id.0.as_str())
            .and_modify(|current| {
                if anchor_quality(anchor) > anchor_quality(current) {
                    *current = anchor;
                }
            })
            .or_insert(anchor);
    }
    by_entity.into_values().collect()
}

fn anchor_quality(anchor: &GraphAnchor) -> u32 {
    let source_score = match anchor.source.as_str() {
        "manual_tag" | "accepted_suggestion" => 50,
        "dictionary_match" | "Some(ExactCanonical)" | "Some(ExactAlias)" => 40,
        "machine_suggestion" | "machine_evidence" => 36,
        _ => 20,
    };
    (anchor.confidence.clamp(0.0, 1.0) * 100.0) as u32
        + source_score
        + u32::from(anchor.chunk_id.is_some()) * 10
        + (anchor.surface.len() as u32).min(16)
}

fn is_weak_cooccurrence(relationship: &GraphRelationship) -> bool {
    relationship.relation_type == "co_occurs_with"
        || relationship.relation_type == "anchored-cooccurrence"
}

fn temporal_target(note_id: &str, edge: &GraphTemporalEdge, prefix: &str) -> GraphEmbeddingTarget {
    GraphEmbeddingTarget {
        id: format_compact!("embed:{}:{}", prefix, edge.id),
        kind: prefix.into(),
        source_id: edge.id.clone(),
        note_id: Some(note_id.into()),
        chunk_id: None,
        entity_id: None,
        label: edge.relation_type.clone(),
        text: format_compact!(
            "{} {} {}",
            edge.source_id,
            edge.relation_type,
            edge.target_id
        ),
        evidence_ids: edge.evidence_ids.clone(),
        parent_ids: Vec::new(),
    }
}

fn structure_root_id(note_id: &str, key: &str) -> CompactString {
    format_compact!("embed:structure-root:{note_id}:{key}")
}

fn note_embedding_text(note_id: &str, note_text: &str) -> CompactString {
    let trimmed = note_text.trim();
    if trimmed.is_empty() {
        return format_compact!("note:{note_id}");
    }
    safe_prefix(trimmed, 12_000).into()
}

fn chunk_embedding_text(note_text: &str, chunk: &GraphChunk) -> CompactString {
    safe_slice(note_text, chunk.start as usize, chunk.end as usize)
        .trim()
        .into()
}

fn safe_prefix(value: &str, max_len: usize) -> &str {
    if value.len() <= max_len {
        return value;
    }
    let mut end = max_len.min(value.len());
    while end > 0 && !value.is_char_boundary(end) {
        end -= 1;
    }
    &value[..end]
}

fn safe_slice(value: &str, start: usize, end: usize) -> &str {
    if value.is_empty() {
        return "";
    }
    let mut left = start.min(value.len());
    let mut right = end.min(value.len());
    while left < value.len() && !value.is_char_boundary(left) {
        left += 1;
    }
    while right > left && !value.is_char_boundary(right) {
        right -= 1;
    }
    value.get(left..right).unwrap_or("")
}
