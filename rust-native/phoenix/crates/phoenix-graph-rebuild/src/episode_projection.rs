use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};

use crate::types::{
    GraphChunk, GraphEpisode, GraphEpisodeProjectionEdge, GraphEvent, GraphTemporalEdge,
};

pub fn build_episode_projection_edges(
    episodes: &[GraphEpisode],
    events: &[GraphEvent],
    chunks: &[GraphChunk],
    temporal_edges: &[GraphTemporalEdge],
    causal_edges: &[GraphTemporalEdge],
) -> Vec<GraphEpisodeProjectionEdge> {
    let event_by_id = events
        .iter()
        .map(|event| (event.id.as_str(), event))
        .collect::<HashMap<_, _>>();
    let chunk_by_id = chunks
        .iter()
        .map(|chunk| (chunk.id.as_str(), chunk))
        .collect::<HashMap<_, _>>();
    let event_episode = episode_by_event(episodes);
    let mut out =
        Vec::with_capacity(episodes.len() * 4 + temporal_edges.len() + causal_edges.len());
    let mut seen = HashSet::<CompactString>::new();

    for episode in episodes {
        push(
            &mut out,
            &mut seen,
            GraphEpisodeProjectionEdge {
                schema_version: "phoenix-episode-projection-edge/v1".into(),
                id: format_compact!(
                    "episode_projection:document_contains_episode:{}:{}",
                    episode.note_id,
                    episode.id
                ),
                kind: "document_contains_episode".into(),
                source_id: format_compact!("{}:document-structure", episode.note_id),
                target_id: episode.id.clone(),
                source_target_id: document_structure_target_id(&episode.note_id),
                target_target_id: episode_target_id(&episode.id),
                note_id: Some(episode.note_id.clone()),
                episode_id: Some(episode.id.clone()),
                relation_type: "document_contains_episode".into(),
                confidence: 1.0,
                status: "structural".into(),
                no_topology_commit: true,
                rationale: vec!["episode_projection:document_spine:no_topology_commit".into()],
                ..GraphEpisodeProjectionEdge::default()
            },
        );

        let mut chunk_ids = HashSet::<CompactString>::new();
        for event_id in &episode.event_ids {
            let Some(event) = event_by_id.get(event_id.as_str()) else {
                continue;
            };
            push(
                &mut out,
                &mut seen,
                GraphEpisodeProjectionEdge {
                    schema_version: "phoenix-episode-projection-edge/v1".into(),
                    id: format_compact!(
                        "episode_projection:episode_contains_event:{}:{}",
                        episode.id,
                        event.id
                    ),
                    kind: "episode_contains_event".into(),
                    source_id: episode.id.clone(),
                    target_id: event.id.clone(),
                    source_target_id: episode_target_id(&episode.id),
                    target_target_id: event_target_id(&event.id),
                    note_id: Some(episode.note_id.clone()),
                    episode_id: Some(episode.id.clone()),
                    event_id: Some(event.id.clone()),
                    relation_type: "episode_contains_event".into(),
                    evidence_ids: event.evidence_anchor_ids.clone(),
                    confidence: event.confidence,
                    status: "structural".into(),
                    no_topology_commit: true,
                    rationale: vec!["episode_projection:event_membership:no_topology_commit".into()],
                    ..GraphEpisodeProjectionEdge::default()
                },
            );
            if let Some(chunk_id) = &event.chunk_id {
                chunk_ids.insert(chunk_id.clone());
            }
        }
        for chunk_id in chunk_ids {
            let ordinal = chunk_by_id
                .get(chunk_id.as_str())
                .map(|chunk| format_compact!("chunk_ordinal:{}", chunk.ordinal));
            let mut rationale =
                vec!["episode_projection:chunk_membership:no_topology_commit".into()];
            if let Some(ordinal) = ordinal {
                rationale.push(ordinal);
            }
            push(
                &mut out,
                &mut seen,
                GraphEpisodeProjectionEdge {
                    schema_version: "phoenix-episode-projection-edge/v1".into(),
                    id: format_compact!(
                        "episode_projection:episode_contains_chunk:{}:{}",
                        episode.id,
                        chunk_id
                    ),
                    kind: "episode_contains_chunk".into(),
                    source_id: episode.id.clone(),
                    target_id: chunk_id.clone(),
                    source_target_id: episode_target_id(&episode.id),
                    target_target_id: chunk_target_id(&chunk_id),
                    note_id: Some(episode.note_id.clone()),
                    episode_id: Some(episode.id.clone()),
                    chunk_id: Some(chunk_id),
                    relation_type: "episode_contains_chunk".into(),
                    confidence: 0.9,
                    status: "structural".into(),
                    no_topology_commit: true,
                    rationale,
                    ..GraphEpisodeProjectionEdge::default()
                },
            );
        }
    }

    for edge in temporal_edges {
        push_connection(
            &mut out,
            &mut seen,
            edge,
            "episode_temporal",
            &event_episode,
        );
    }
    for edge in causal_edges {
        push_connection(&mut out, &mut seen, edge, "episode_causal", &event_episode);
    }
    out.sort_by(|left, right| {
        projection_rank(&left.kind)
            .cmp(&projection_rank(&right.kind))
            .then_with(|| left.source_target_id.cmp(&right.source_target_id))
            .then_with(|| left.target_target_id.cmp(&right.target_target_id))
            .then_with(|| left.id.cmp(&right.id))
    });
    out
}

pub fn episode_target_id(episode_id: &str) -> CompactString {
    format_compact!("embed:episode:{episode_id}")
}

fn push(
    out: &mut Vec<GraphEpisodeProjectionEdge>,
    seen: &mut HashSet<CompactString>,
    edge: GraphEpisodeProjectionEdge,
) {
    if edge.source_target_id == edge.target_target_id || !seen.insert(edge.id.clone()) {
        return;
    }
    out.push(edge);
}

fn push_connection(
    out: &mut Vec<GraphEpisodeProjectionEdge>,
    seen: &mut HashSet<CompactString>,
    edge: &GraphTemporalEdge,
    kind: &str,
    event_episode: &HashMap<&str, &GraphEpisode>,
) {
    let Some(source) = event_episode.get(edge.source_id.as_str()) else {
        return;
    };
    let Some(target) = event_episode.get(edge.target_id.as_str()) else {
        return;
    };
    if source.id == target.id {
        return;
    }
    push(
        out,
        seen,
        GraphEpisodeProjectionEdge {
            schema_version: "phoenix-episode-projection-edge/v1".into(),
            id: format_compact!(
                "episode_projection:{kind}:{}:{}:{}",
                source.id,
                edge.relation_type,
                target.id
            ),
            kind: kind.into(),
            source_id: source.id.clone(),
            target_id: target.id.clone(),
            source_target_id: episode_target_id(&source.id),
            target_target_id: episode_target_id(&target.id),
            source_episode_id: Some(source.id.clone()),
            target_episode_id: Some(target.id.clone()),
            episode_connection_id: Some(edge.id.clone()),
            relation_type: format_compact!("episode_{}", edge.relation_type),
            evidence_ids: edge.evidence_ids.clone(),
            confidence: edge.confidence,
            status: "derived".into(),
            no_topology_commit: true,
            rationale: vec![
                "episode_projection:connection_overlay:no_topology_commit".into(),
                format_compact!("{kind}:event_edge_aggregate"),
            ],
            ..GraphEpisodeProjectionEdge::default()
        },
    );
}

fn episode_by_event(episodes: &[GraphEpisode]) -> HashMap<&str, &GraphEpisode> {
    let mut out = HashMap::new();
    for episode in episodes {
        for event_id in &episode.event_ids {
            out.insert(event_id.as_str(), episode);
        }
    }
    out
}

fn document_structure_target_id(note_id: &str) -> CompactString {
    format_compact!("embed:structure-root:{note_id}:document-structure")
}

fn event_target_id(event_id: &str) -> CompactString {
    format_compact!("embed:event:{event_id}")
}

fn chunk_target_id(chunk_id: &str) -> CompactString {
    format_compact!("embed:chunk:{chunk_id}")
}

fn projection_rank(kind: &str) -> u8 {
    match kind {
        "document_contains_episode" => 0,
        "episode_contains_chunk" => 1,
        "episode_contains_event" => 2,
        "episode_temporal" => 3,
        "episode_causal" => 4,
        _ => 5,
    }
}
