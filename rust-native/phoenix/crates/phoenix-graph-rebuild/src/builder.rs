use std::time::{SystemTime, UNIX_EPOCH};

use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};
use phoenix_alex::api as alex;
use phoenix_chunker::api::default_chunk_ranges;
use phoenix_types::{EntityId, KnownMatch, LexiconEntry, ScopeKey};
use smallvec::SmallVec;
use thiserror::Error;

use crate::adjudication::adjudicate_cooccurrence_edges;
use crate::embedding::build_embedding_targets;
use crate::facts::derive_graph_facts;
use crate::types::{
    GraphAnchor, GraphChunk, GraphCounters, GraphDropReasons, GraphEdge, GraphMention, GraphNode,
    GraphRebuildSnapshot, GraphScopeKind,
};

#[derive(Debug, Error)]
pub enum GraphRebuildError {
    #[error("Alex lexicon build failed: {0}")]
    Alex(#[from] phoenix_alex::AlexError),
}

#[derive(Clone, Debug)]
pub struct GraphRebuildInput<'a> {
    pub scope_kind: GraphScopeKind,
    pub scope_id: &'a str,
    pub note_id: &'a str,
    pub text: &'a str,
    pub scope: ScopeKey,
    pub entities: &'a [LexiconEntry],
    pub candidate_count: usize,
    pub built_at: Option<u64>,
}

pub struct GraphRebuildBuilder;

struct BucketEntity<'a> {
    entity_id: &'a EntityId,
    anchor_indexes: SmallVec<[usize; 4]>,
}

impl GraphRebuildBuilder {
    pub fn build(input: GraphRebuildInput<'_>) -> Result<GraphRebuildSnapshot, GraphRebuildError> {
        build_graph_rebuild_snapshot(input)
    }
}

pub fn build_graph_rebuild_snapshot(
    input: GraphRebuildInput<'_>,
) -> Result<GraphRebuildSnapshot, GraphRebuildError> {
    let built_at = input.built_at.unwrap_or_else(now_ms);
    let chunks = build_chunks(input.note_id, input.text);
    let lexicon = alex::build_lexicon(input.entities)?;
    let matches = alex::scan_text(&lexicon, input.text, &input.scope);
    let mut drops = GraphDropReasons::default();
    let mut seen = HashSet::<CompactString>::new();
    let mut mentions = Vec::with_capacity(matches.len());
    let mut anchors = Vec::with_capacity(matches.len());

    for known in matches {
        let mention = known_to_mention(input.note_id, &chunks, &known);
        let Some(entry) = known.entries.first() else {
            drops.missing_entity += 1;
            mentions.push(GraphMention {
                status: "dropped".into(),
                ..mention
            });
            continue;
        };
        if known.range.end <= known.range.start {
            drops.invalid_span += 1;
            mentions.push(GraphMention {
                entity_id: Some(entry.entity_id.clone()),
                status: "dropped".into(),
                ..mention
            });
            continue;
        }
        let anchor_id = format_compact!(
            "{}:{}:{}:{}:{}",
            input.note_id,
            entry.entity_id.0,
            known.range.start,
            known.range.end,
            mention.source
        );
        if !seen.insert(anchor_id.clone()) {
            drops.duplicate_anchor += 1;
            mentions.push(GraphMention {
                id: anchor_id,
                entity_id: Some(entry.entity_id.clone()),
                status: "dropped".into(),
                ..mention
            });
            continue;
        }
        let anchor = GraphAnchor {
            id: anchor_id,
            entity_id: entry.entity_id.clone(),
            note_id: input.note_id.into(),
            chunk_id: mention.chunk_id.clone(),
            surface: mention.surface.clone(),
            source_start: known.range.start,
            source_end: known.range.end,
            source: mention.source.clone(),
            confidence: known.confidence,
            generation: built_at,
        };
        mentions.push(GraphMention {
            id: anchor.id.clone(),
            entity_id: Some(entry.entity_id.clone()),
            status: "accepted".into(),
            ..mention
        });
        anchors.push(anchor);
    }

    let nodes = build_nodes(&anchors, input.entities);
    let mut edges = build_edges(&anchors, &mut drops);
    let (mut relationships, _) = adjudicate_cooccurrence_edges(&edges);
    let mut derived = derive_graph_facts(input.note_id, input.text, &chunks, &anchors);
    edges.append(&mut derived.edges);
    edges.sort_by(|left, right| {
        right
            .weight
            .cmp(&left.weight)
            .then_with(|| left.edge_type.cmp(&right.edge_type))
            .then_with(|| left.id.cmp(&right.id))
    });
    relationships.append(&mut derived.relationships);
    let relationship_candidates = relationships.len();
    let accepted_relationships = relationships
        .iter()
        .filter(|relationship| relationship.status == "accepted")
        .count();
    let review_relationships = relationships
        .iter()
        .filter(|relationship| relationship.status == "review")
        .count();
    let rejected_relationships = relationships
        .iter()
        .filter(|relationship| relationship.status == "rejected")
        .count();
    let events = derived.events;
    let episodes = derived.episodes;
    let temporal_edges = derived.temporal_edges;
    let causal_edges = derived.causal_edges;
    let memory_state = derived.memory_state;
    let embedding_targets = build_embedding_targets(
        input.note_id,
        input.text,
        &chunks,
        &anchors,
        &nodes,
        &relationships,
        &events,
        &temporal_edges,
        &causal_edges,
        &memory_state,
    );
    let counters = GraphCounters {
        entities: input.entities.len(),
        aliases: input.entities.iter().map(|entry| entry.aliases.len()).sum(),
        candidates: input.candidate_count,
        mentions: mentions.len(),
        accepted_anchors: anchors.len(),
        chunks: chunks.len(),
        anchor_evidence: anchors.len(),
        relation_signals: relationships.len(),
        promoted_facts: accepted_relationships
            + events.len()
            + temporal_edges.len()
            + causal_edges.len()
            + memory_state.len(),
        relationship_candidates,
        relationships: relationships.len(),
        accepted_relationships,
        review_relationships,
        rejected_relationships,
        events: events.len(),
        episodes: episodes.len(),
        temporal_edges: temporal_edges.len(),
        causal_edges: causal_edges.len(),
        memory_state: memory_state.len(),
        embedding_targets: embedding_targets.len(),
        nodes: nodes.len(),
        edges: edges.len(),
        drop_reasons: drops,
        ..GraphCounters::default()
    };

    Ok(GraphRebuildSnapshot {
        schema_version: "phoenix-graph-rebuild/v1".into(),
        id: format_compact!(
            "graph-rebuild:{}:{}:{}",
            input.note_id,
            input.scope_id,
            built_at
        ),
        source: "phoenix-graph-rebuild".into(),
        scope_kind: input.scope_kind,
        scope_id: input.scope_id.into(),
        note_ids: vec![input.note_id.into()],
        built_at,
        chunks,
        mentions,
        entity_anchors: anchors,
        relationships,
        events,
        episodes,
        temporal_edges,
        causal_edges,
        memory_state,
        embedding_targets,
        embedding_vectors: Vec::new(),
        projection_refs: Vec::new(),
        nodes,
        edges,
        calendar_registry_summary: None,
        counters,
    })
}

fn build_chunks(note_id: &str, text: &str) -> Vec<GraphChunk> {
    let sentence_like = memchr::memchr_iter(b'.', text.as_bytes()).count();
    let mut chunks = default_chunk_ranges(text);
    if chunks.is_empty() && !text.trim().is_empty() {
        chunks.push(phoenix_chunker::Chunk {
            start: 0,
            end: text.len(),
        });
    }
    chunks
        .into_iter()
        .enumerate()
        .map(|(ordinal, chunk)| GraphChunk {
            id: format_compact!("{note_id}:chunk:{ordinal}"),
            note_id: note_id.into(),
            start: chunk.start as u32,
            end: chunk.end as u32,
            ordinal: ordinal as u32,
            source: if sentence_like > 0 {
                "dynamic-chunking"
            } else {
                "note-fallback"
            }
            .into(),
        })
        .collect()
}

fn known_to_mention(note_id: &str, chunks: &[GraphChunk], known: &KnownMatch) -> GraphMention {
    GraphMention {
        id: format_compact!(
            "mention:{}:{}:{}",
            note_id,
            known.range.start,
            known.range.end
        ),
        note_id: note_id.into(),
        chunk_id: chunk_for_span(chunks, known.range.start, known.range.end),
        surface: known.surface.as_str().into(),
        source_start: known.range.start,
        source_end: known.range.end,
        source: format_compact!("{:?}", known.source),
        confidence: known.confidence,
        entity_id: known.entries.first().map(|entry| entry.entity_id.clone()),
        status: "candidate".into(),
    }
}

fn chunk_for_span(chunks: &[GraphChunk], start: u32, end: u32) -> Option<CompactString> {
    if chunks.is_empty() {
        return None;
    }
    let index = chunks.partition_point(|chunk| chunk.start <= start);
    let candidate = index.checked_sub(1).and_then(|slot| chunks.get(slot))?;
    if start >= candidate.start && (end <= candidate.end || start < candidate.end) {
        return Some(candidate.id.clone());
    }
    None
}

fn build_nodes(anchors: &[GraphAnchor], entities: &[LexiconEntry]) -> Vec<GraphNode> {
    let entries = entities
        .iter()
        .map(|entry| (&entry.entity_id, entry))
        .collect::<HashMap<_, _>>();
    let mut by_entity = HashMap::<&EntityId, GraphNode>::new();
    for anchor in anchors {
        let Some(entry) = entries.get(&anchor.entity_id) else {
            continue;
        };
        let node = by_entity
            .entry(&anchor.entity_id)
            .or_insert_with(|| GraphNode {
                id: entry.entity_id.clone(),
                entity_id: entry.entity_id.clone(),
                label: entry.label.as_str().into(),
                kind: format_compact!("{:?}", entry.kind),
                aliases: entry
                    .aliases
                    .iter()
                    .map(|alias| alias.as_str().into())
                    .collect(),
                anchor_ids: Vec::new(),
                note_ids: Vec::new(),
                total_mentions: 0,
            });
        node.anchor_ids.push(anchor.id.clone());
        if !node.note_ids.iter().any(|note| note == &anchor.note_id) {
            node.note_ids.push(anchor.note_id.clone());
        }
        node.total_mentions += 1;
    }
    let mut nodes = by_entity.into_values().collect::<Vec<_>>();
    nodes.sort_by(|left, right| {
        right
            .total_mentions
            .cmp(&left.total_mentions)
            .then_with(|| left.label.cmp(&right.label))
    });
    nodes
}

fn build_edges(anchors: &[GraphAnchor], drops: &mut GraphDropReasons) -> Vec<GraphEdge> {
    let mut buckets = HashMap::<CompactString, SmallVec<[usize; 4]>>::new();
    for (index, anchor) in anchors.iter().enumerate() {
        let key = anchor
            .chunk_id
            .clone()
            .unwrap_or_else(|| format_compact!("note:{}", anchor.note_id));
        buckets.entry(key).or_default().push(index);
    }
    let mut edges = HashMap::<CompactString, GraphEdge>::new();
    for (scope_key, indexes) in buckets {
        let entities = bucket_entities(anchors, &indexes);
        if entities.len() < 2 {
            drops.singleton_bucket += 1;
            continue;
        }
        for left_index in 0..entities.len() {
            for right_index in (left_index + 1)..entities.len() {
                upsert_edge(
                    &mut edges,
                    &entities[left_index],
                    &entities[right_index],
                    anchors,
                    &scope_key,
                );
            }
        }
    }
    let mut out = edges.into_values().collect::<Vec<_>>();
    out.sort_by(|left, right| {
        right
            .weight
            .cmp(&left.weight)
            .then_with(|| left.id.cmp(&right.id))
    });
    out
}

fn bucket_entities<'a>(anchors: &'a [GraphAnchor], indexes: &[usize]) -> Vec<BucketEntity<'a>> {
    let mut positions = HashMap::<&'a EntityId, usize>::with_capacity(indexes.len());
    let mut out = Vec::<BucketEntity<'a>>::new();
    for &index in indexes {
        let entity_id = &anchors[index].entity_id;
        if let Some(position) = positions.get(entity_id).copied() {
            out[position].anchor_indexes.push(index);
        } else {
            positions.insert(entity_id, out.len());
            out.push(BucketEntity {
                entity_id,
                anchor_indexes: smallvec::smallvec![index],
            });
        }
    }
    out
}

fn upsert_edge(
    edges: &mut HashMap<CompactString, GraphEdge>,
    left: &BucketEntity<'_>,
    right: &BucketEntity<'_>,
    anchors: &[GraphAnchor],
    scope_key: &CompactString,
) {
    let (source, target) = if left.entity_id <= right.entity_id {
        (left, right)
    } else {
        (right, left)
    };
    let id = format_compact!(
        "{}:anchored-cooccurrence:{}",
        source.entity_id.0,
        target.entity_id.0
    );
    let edge = edges.entry(id.clone()).or_insert_with(|| GraphEdge {
        id,
        source_id: source.entity_id.clone(),
        target_id: target.entity_id.clone(),
        edge_type: "anchored-cooccurrence".into(),
        weight: 0,
        confidence: 0.0,
        evidence_anchor_ids: Vec::new(),
        scope_keys: Vec::new(),
        note_ids: Vec::new(),
    });
    edge.weight += 1;
    edge.confidence = (edge.confidence + 0.2).min(1.0);
    if !edge.scope_keys.iter().any(|key| key == scope_key) {
        edge.scope_keys.push(scope_key.clone());
    }
    for &index in source
        .anchor_indexes
        .iter()
        .chain(target.anchor_indexes.iter())
    {
        let anchor = &anchors[index];
        push_unique(&mut edge.evidence_anchor_ids, anchor.id.clone());
        push_unique(&mut edge.note_ids, anchor.note_id.clone());
    }
}

fn push_unique(values: &mut Vec<CompactString>, value: CompactString) {
    if !values.iter().any(|item| item == &value) {
        values.push(value);
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or_default()
}
