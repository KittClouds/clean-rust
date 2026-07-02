use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};

use crate::types::{
    GraphAnchor, GraphChunk, GraphEvent, GraphMemoryGovernanceAction,
    GraphMemoryGovernanceCandidate, GraphMemoryGovernanceCommitPolicy,
    GraphMemoryGovernanceSignals, GraphMemoryGovernanceStatus, GraphMemoryGovernanceTargetKind,
    GraphMemoryState, GraphRebuildSnapshot, GraphTemporalEdge,
};

pub const MEMORY_GOVERNANCE_SCHEMA_VERSION: &str = "phoenix-memory-governance-candidate/v1";
pub const MEMORY_GOVERNANCE_COMMIT_POLICY: &str = "no_topology_commit";
pub const MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT: &str =
    "memory_governance_candidate:no_topology_commit";

#[derive(Clone, Copy, Debug, Default)]
pub struct MemoryGovernanceEngineInput<'a> {
    pub chunks: &'a [GraphChunk],
    pub episodes: &'a [crate::types::GraphEpisode],
    pub anchors: &'a [GraphAnchor],
    pub events: &'a [GraphEvent],
    pub temporal_edges: &'a [GraphTemporalEdge],
    pub causal_edges: &'a [GraphTemporalEdge],
    pub memory_state: &'a [GraphMemoryState],
}

#[derive(Clone, Default)]
struct TargetStats {
    evidence_ids: Vec<CompactString>,
    entity_ids: HashSet<CompactString>,
    event_ids: Vec<CompactString>,
    chunk_ids: Vec<CompactString>,
    event_count: usize,
    temporal_degree: usize,
    causal_degree: usize,
    memory_state_count: usize,
    redundancy: f32,
}

pub fn build_memory_governance_candidates_from_snapshot(
    snapshot: &GraphRebuildSnapshot,
) -> Vec<GraphMemoryGovernanceCandidate> {
    build_memory_governance_candidates(MemoryGovernanceEngineInput {
        chunks: &snapshot.chunks,
        episodes: &snapshot.episodes,
        anchors: &snapshot.entity_anchors,
        events: &snapshot.events,
        temporal_edges: &snapshot.temporal_edges,
        causal_edges: &snapshot.causal_edges,
        memory_state: &snapshot.memory_state,
    })
}

pub fn build_memory_governance_candidates(
    input: MemoryGovernanceEngineInput<'_>,
) -> Vec<GraphMemoryGovernanceCandidate> {
    let mut chunk_stats = chunk_stats(input);
    assign_chunk_redundancy(input.chunks, &mut chunk_stats);
    let episode_stats = episode_stats(input, &chunk_stats);
    let mut out = Vec::with_capacity(input.chunks.len() + input.episodes.len());

    for chunk in input.chunks {
        let stats = chunk_stats.get(chunk.id.as_str());
        out.push(chunk_candidate(chunk, stats));
    }
    for episode in input.episodes {
        let stats = episode_stats.get(episode.id.as_str());
        out.push(episode_candidate(episode, stats));
    }

    out.sort_by(|left, right| {
        governance_rank(left.action)
            .cmp(&governance_rank(right.action))
            .then_with(|| left.target_kind.as_str().cmp(right.target_kind.as_str()))
            .then_with(|| left.target_id.cmp(&right.target_id))
    });
    out
}

pub fn assert_memory_governance_candidate_only(
    candidates: &[GraphMemoryGovernanceCandidate],
) -> Result<(), String> {
    for candidate in candidates {
        if candidate.schema_version != MEMORY_GOVERNANCE_SCHEMA_VERSION {
            return Err(format!(
                "invalid memory governance schema: {}",
                candidate.id
            ));
        }
        if candidate.status != GraphMemoryGovernanceStatus::Candidate {
            return Err(format!(
                "invalid memory governance status: {}",
                candidate.id
            ));
        }
        if candidate.commit_policy != GraphMemoryGovernanceCommitPolicy::NoTopologyCommit {
            return Err(format!(
                "invalid memory governance commit policy: {}",
                candidate.id
            ));
        }
        if !candidate.no_topology_commit {
            return Err(format!("missing no topology guard: {}", candidate.id));
        }
        if !candidate
            .rationale
            .iter()
            .any(|row| row == MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT)
        {
            return Err(format!("missing no topology rationale: {}", candidate.id));
        }
    }
    Ok(())
}

fn chunk_stats<'a>(input: MemoryGovernanceEngineInput<'a>) -> HashMap<&'a str, TargetStats> {
    let mut stats = HashMap::<&str, TargetStats>::with_capacity(input.chunks.len());
    for chunk in input.chunks {
        stats.insert(chunk.id.as_str(), TargetStats::default());
    }
    let event_chunk = input
        .events
        .iter()
        .filter_map(|event| {
            event
                .chunk_id
                .as_ref()
                .map(|chunk_id| (event.id.as_str(), chunk_id))
        })
        .collect::<HashMap<_, _>>();
    let anchor_chunk = input
        .anchors
        .iter()
        .filter_map(|anchor| {
            anchor
                .chunk_id
                .as_ref()
                .map(|chunk_id| (anchor.id.as_str(), chunk_id))
        })
        .collect::<HashMap<_, _>>();

    for anchor in input.anchors {
        let Some(chunk_id) = anchor.chunk_id.as_ref() else {
            continue;
        };
        let Some(row) = stats.get_mut(chunk_id.as_str()) else {
            continue;
        };
        push_unique(&mut row.evidence_ids, anchor.id.clone());
        row.entity_ids.insert(anchor.entity_id.0.as_str().into());
    }
    for event in input.events {
        let Some(chunk_id) = event.chunk_id.as_ref() else {
            continue;
        };
        let Some(row) = stats.get_mut(chunk_id.as_str()) else {
            continue;
        };
        row.event_count += 1;
        push_unique(&mut row.event_ids, event.id.clone());
        for evidence_id in &event.evidence_anchor_ids {
            push_unique(&mut row.evidence_ids, evidence_id.clone());
        }
        for entity_id in &event.entity_ids {
            row.entity_ids.insert(entity_id.0.as_str().into());
        }
    }
    for edge in input.temporal_edges {
        mark_event_edge_degree(edge, &event_chunk, &mut stats, false);
    }
    for edge in input.causal_edges {
        mark_event_edge_degree(edge, &event_chunk, &mut stats, true);
    }
    for state in input.memory_state {
        for evidence_id in &state.evidence_ids {
            let Some(chunk_id) = anchor_chunk.get(evidence_id.as_str()) else {
                continue;
            };
            let Some(row) = stats.get_mut(chunk_id.as_str()) else {
                continue;
            };
            row.memory_state_count += 1;
            push_unique(&mut row.evidence_ids, evidence_id.clone());
            row.entity_ids.insert(state.entity_id.0.as_str().into());
        }
    }
    stats
}

fn episode_stats<'a>(
    input: MemoryGovernanceEngineInput<'a>,
    chunk_stats: &HashMap<&str, TargetStats>,
) -> HashMap<&'a str, TargetStats> {
    let event_by_id = input
        .events
        .iter()
        .map(|event| (event.id.as_str(), event))
        .collect::<HashMap<_, _>>();
    let episode_by_event = input
        .episodes
        .iter()
        .flat_map(|episode| {
            episode
                .event_ids
                .iter()
                .map(move |event_id| (event_id.as_str(), episode.id.as_str()))
        })
        .collect::<HashMap<_, _>>();
    let mut stats = HashMap::<&str, TargetStats>::with_capacity(input.episodes.len());

    for episode in input.episodes {
        let mut row = TargetStats::default();
        row.entity_ids
            .extend(episode.entity_ids.iter().map(|id| id.0.as_str().into()));
        for event_id in &episode.event_ids {
            let Some(event) = event_by_id.get(event_id.as_str()) else {
                continue;
            };
            row.event_count += 1;
            push_unique(&mut row.event_ids, event.id.clone());
            for evidence_id in &event.evidence_anchor_ids {
                push_unique(&mut row.evidence_ids, evidence_id.clone());
            }
            for entity_id in &event.entity_ids {
                row.entity_ids.insert(entity_id.0.as_str().into());
            }
            if let Some(chunk_id) = &event.chunk_id {
                push_unique(&mut row.chunk_ids, chunk_id.clone());
                if let Some(chunk_row) = chunk_stats.get(chunk_id.as_str()) {
                    row.memory_state_count += chunk_row.memory_state_count;
                }
            }
        }
        stats.insert(episode.id.as_str(), row);
    }

    for edge in input.temporal_edges {
        mark_episode_edge_degree(edge, &episode_by_event, &mut stats, false);
    }
    for edge in input.causal_edges {
        mark_episode_edge_degree(edge, &episode_by_event, &mut stats, true);
    }
    stats
}

fn chunk_candidate(
    chunk: &GraphChunk,
    stats: Option<&TargetStats>,
) -> GraphMemoryGovernanceCandidate {
    let stats = stats.cloned().unwrap_or_default();
    let signals = signals(&stats);
    let action = if stats.causal_degree > 0 || stats.memory_state_count > 0 {
        GraphMemoryGovernanceAction::Retain
    } else if stats.event_count == 0 && stats.entity_ids.is_empty() {
        GraphMemoryGovernanceAction::Attenuate
    } else if stats.event_count == 0 && stats.redundancy >= 0.65 {
        GraphMemoryGovernanceAction::Attenuate
    } else {
        GraphMemoryGovernanceAction::Retain
    };
    let reason = match action {
        GraphMemoryGovernanceAction::Attenuate => "low_signal_or_redundant_chunk",
        _ => "chunk_has_retrieval_or_story_signal",
    };
    candidate(
        GraphMemoryGovernanceTargetKind::Chunk,
        &chunk.id,
        action,
        reason,
        stats,
        signals,
    )
}

fn episode_candidate(
    episode: &crate::types::GraphEpisode,
    stats: Option<&TargetStats>,
) -> GraphMemoryGovernanceCandidate {
    let stats = stats.cloned().unwrap_or_default();
    let signals = signals(&stats);
    let action = if stats.event_count == 0 {
        GraphMemoryGovernanceAction::Attenuate
    } else if stats.chunk_ids.len() > 1 && stats.event_count > 1 {
        GraphMemoryGovernanceAction::Compress
    } else {
        GraphMemoryGovernanceAction::Retain
    };
    let reason = match action {
        GraphMemoryGovernanceAction::Compress => "episode_can_compact_child_chunks",
        GraphMemoryGovernanceAction::Attenuate => "episode_has_no_event_evidence",
        _ => "episode_preserves_story_continuity",
    };
    candidate(
        GraphMemoryGovernanceTargetKind::Episode,
        &episode.id,
        action,
        reason,
        stats,
        signals,
    )
}

fn candidate(
    target_kind: GraphMemoryGovernanceTargetKind,
    target_id: &CompactString,
    action: GraphMemoryGovernanceAction,
    reason: &str,
    stats: TargetStats,
    signals: GraphMemoryGovernanceSignals,
) -> GraphMemoryGovernanceCandidate {
    let confidence = match action {
        GraphMemoryGovernanceAction::Compress => {
            clamp(0.55 + signals.narrative_salience * 0.25 + signals.retrieval_utility * 0.15)
        }
        GraphMemoryGovernanceAction::Attenuate => {
            clamp(0.52 + signals.redundancy * 0.18 - signals.evidence_strength * 0.12)
        }
        GraphMemoryGovernanceAction::Retain => {
            clamp(0.50 + signals.narrative_salience * 0.22 + signals.causal_importance * 0.16)
        }
        GraphMemoryGovernanceAction::Quarantine | GraphMemoryGovernanceAction::Retire => 0.0,
    };
    GraphMemoryGovernanceCandidate {
        schema_version: MEMORY_GOVERNANCE_SCHEMA_VERSION.into(),
        id: format_compact!(
            "memory_governance:{}:{}:{}",
            target_kind.as_str(),
            action.as_str(),
            target_id
        ),
        target_id: target_id.clone(),
        target_kind,
        action,
        reason: reason.into(),
        evidence_ids: stats.evidence_ids,
        supporting_entity_ids: sorted_set(stats.entity_ids),
        related_event_ids: stats.event_ids,
        related_chunk_ids: stats.chunk_ids,
        signals,
        confidence,
        status: GraphMemoryGovernanceStatus::Candidate,
        commit_policy: GraphMemoryGovernanceCommitPolicy::NoTopologyCommit,
        no_topology_commit: true,
        rationale: vec![
            MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT.into(),
            "memory_governance:retrieval_policy_overlay".into(),
            format_compact!("reason:{reason}"),
        ],
    }
}

fn signals(stats: &TargetStats) -> GraphMemoryGovernanceSignals {
    let evidence = stats.evidence_ids.len() as f32;
    let entities = stats.entity_ids.len() as f32;
    let events = stats.event_count as f32;
    let causal = stats.causal_degree as f32;
    let temporal = stats.temporal_degree as f32;
    GraphMemoryGovernanceSignals {
        age: 0.0,
        access_frequency: 0.0,
        redundancy: stats.redundancy,
        contradiction_risk: 0.0,
        causal_importance: clamp(causal / 3.0),
        narrative_salience: clamp(
            events * 0.24 + entities * 0.10 + causal * 0.20 + temporal * 0.08,
        ),
        retrieval_utility: clamp(
            evidence * 0.12 + events * 0.18 + stats.memory_state_count as f32 * 0.20,
        ),
        evidence_strength: clamp(evidence / 6.0),
        user_pinned: false,
    }
}

fn assign_chunk_redundancy(chunks: &[GraphChunk], stats: &mut HashMap<&str, TargetStats>) {
    let mut signatures = HashMap::<CompactString, usize>::with_capacity(chunks.len());
    for chunk in chunks {
        let Some(row) = stats.get(chunk.id.as_str()) else {
            continue;
        };
        let signature = entity_signature(&row.entity_ids);
        if signature.is_empty() {
            continue;
        }
        *signatures.entry(signature).or_insert(0) += 1;
    }
    let denominator = chunks.len().saturating_sub(1).max(1) as f32;
    for chunk in chunks {
        let Some(row) = stats.get_mut(chunk.id.as_str()) else {
            continue;
        };
        let signature = entity_signature(&row.entity_ids);
        if signature.is_empty() {
            row.redundancy = 0.0;
            continue;
        }
        row.redundancy = ((*signatures.get(&signature).unwrap_or(&1)).saturating_sub(1) as f32
            / denominator)
            .min(1.0);
    }
}

fn mark_event_edge_degree<'a>(
    edge: &GraphTemporalEdge,
    event_chunk: &HashMap<&str, &'a CompactString>,
    stats: &mut HashMap<&'a str, TargetStats>,
    causal: bool,
) {
    for event_id in [edge.source_id.as_str(), edge.target_id.as_str()] {
        let Some(chunk_id) = event_chunk.get(event_id) else {
            continue;
        };
        let Some(row) = stats.get_mut(chunk_id.as_str()) else {
            continue;
        };
        if causal {
            row.causal_degree += 1;
        } else {
            row.temporal_degree += 1;
        }
        for evidence_id in &edge.evidence_ids {
            push_unique(&mut row.evidence_ids, evidence_id.clone());
        }
    }
}

fn mark_episode_edge_degree<'a>(
    edge: &GraphTemporalEdge,
    episode_by_event: &HashMap<&str, &'a str>,
    stats: &mut HashMap<&'a str, TargetStats>,
    causal: bool,
) {
    for event_id in [edge.source_id.as_str(), edge.target_id.as_str()] {
        let Some(episode_id) = episode_by_event.get(event_id) else {
            continue;
        };
        let Some(row) = stats.get_mut(episode_id) else {
            continue;
        };
        if causal {
            row.causal_degree += 1;
        } else {
            row.temporal_degree += 1;
        }
        for evidence_id in &edge.evidence_ids {
            push_unique(&mut row.evidence_ids, evidence_id.clone());
        }
    }
}

fn push_unique(out: &mut Vec<CompactString>, value: CompactString) {
    if !out.iter().any(|row| row == &value) {
        out.push(value);
    }
}

fn sorted_set(values: HashSet<CompactString>) -> Vec<CompactString> {
    let mut out = values.into_iter().collect::<Vec<_>>();
    out.sort();
    out
}

fn entity_signature(values: &HashSet<CompactString>) -> CompactString {
    let mut sorted = values.iter().map(CompactString::as_str).collect::<Vec<_>>();
    sorted.sort_unstable();
    sorted.join("|").into()
}

fn clamp(value: f32) -> f32 {
    value.clamp(0.0, 1.0)
}

fn governance_rank(action: GraphMemoryGovernanceAction) -> u8 {
    match action {
        GraphMemoryGovernanceAction::Retain => 0,
        GraphMemoryGovernanceAction::Compress => 1,
        GraphMemoryGovernanceAction::Attenuate => 2,
        GraphMemoryGovernanceAction::Quarantine => 3,
        GraphMemoryGovernanceAction::Retire => 4,
    }
}

#[cfg(test)]
mod tests {
    use phoenix_types::EntityId;

    use super::*;
    use crate::types::{GraphEpisode, GraphMemoryGovernanceAction, GraphScopeKind};

    #[test]
    fn emits_candidate_only_governance_rows_without_topology_commit() {
        let snapshot = governance_snapshot();
        let edge_count = snapshot.edges.len();
        let candidates = build_memory_governance_candidates_from_snapshot(&snapshot);

        assert_eq!(snapshot.edges.len(), edge_count);
        assert!(!candidates.is_empty());
        assert_memory_governance_candidate_only(&candidates).expect("candidate only");
        assert!(candidates.iter().any(|candidate| {
            candidate.target_kind == GraphMemoryGovernanceTargetKind::Episode
                && candidate.action == GraphMemoryGovernanceAction::Compress
        }));
        assert!(candidates.iter().any(|candidate| {
            candidate.target_kind == GraphMemoryGovernanceTargetKind::Chunk
                && candidate.action == GraphMemoryGovernanceAction::Attenuate
        }));
    }

    #[test]
    fn serializes_to_frontend_memory_governance_contract() {
        let snapshot = governance_snapshot();
        let candidates = build_memory_governance_candidates_from_snapshot(&snapshot);
        let candidate = candidates
            .iter()
            .find(|row| row.action == GraphMemoryGovernanceAction::Compress)
            .expect("compress candidate");
        let value = serde_json::to_value(candidate).expect("candidate json");
        let object = value.as_object().expect("candidate object");

        assert_eq!(object["schemaVersion"], MEMORY_GOVERNANCE_SCHEMA_VERSION);
        assert_eq!(object["targetKind"], "episode");
        assert_eq!(object["action"], "compress");
        assert_eq!(object["status"], "candidate");
        assert_eq!(object["commitPolicy"], MEMORY_GOVERNANCE_COMMIT_POLICY);
        assert_eq!(object["noTopologyCommit"], true);
        assert!(!object.contains_key("target_kind"));
        assert!(!object.contains_key("commit_policy"));
    }

    fn governance_snapshot() -> GraphRebuildSnapshot {
        let kai = EntityId("character:kai".to_owned());
        let hazel = EntityId("character:hazel".to_owned());
        let chunks = vec![
            chunk("note:memory:chunk:0", 0),
            chunk("note:memory:chunk:1", 1),
            chunk("note:memory:chunk:2", 2),
        ];
        let anchors = vec![
            anchor("anchor:kai:0", &kai, "note:memory:chunk:0"),
            anchor("anchor:hazel:2", &hazel, "note:memory:chunk:2"),
        ];
        let events = vec![
            event("event:kai:0", "note:memory:chunk:0", &[kai.clone()]),
            event("event:hazel:2", "note:memory:chunk:2", &[hazel.clone()]),
        ];

        GraphRebuildSnapshot {
            schema_version: "phoenix-graph-rebuild/v1".into(),
            id: "snapshot:memory".into(),
            source: "test".into(),
            scope_kind: GraphScopeKind::Note,
            scope_id: "note:memory".into(),
            note_ids: vec!["note:memory".into()],
            built_at: 1,
            chunks,
            mentions: Vec::new(),
            entity_anchors: anchors,
            relationships: Vec::new(),
            events,
            episodes: vec![GraphEpisode {
                id: "episode:memory:0".into(),
                note_id: "note:memory".into(),
                event_ids: vec!["event:kai:0".into(), "event:hazel:2".into()],
                entity_ids: vec![kai, hazel],
                label: "Episode 1".into(),
            }],
            episode_projection_edges: Vec::new(),
            temporal_edges: vec![GraphTemporalEdge {
                id: "temporal:event:kai:event:hazel".into(),
                source_id: "event:kai:0".into(),
                target_id: "event:hazel:2".into(),
                relation_type: "before".into(),
                evidence_ids: vec!["event:kai:0".into(), "event:hazel:2".into()],
                confidence: 0.8,
            }],
            causal_edges: Vec::new(),
            memory_state: Vec::new(),
            memory_governance_candidates: Vec::new(),
            embedding_targets: Vec::new(),
            embedding_vectors: Vec::new(),
            projection_refs: Vec::new(),
            nodes: Vec::new(),
            edges: Vec::new(),
            calendar_registry_summary: None,
            document_sidecar_summary: None,
            document_review_summary: None,
            document_compiler_summary: None,
            discourse_spine_summary: None,
            counters: Default::default(),
        }
    }

    fn chunk(id: &str, ordinal: u32) -> GraphChunk {
        GraphChunk {
            id: id.into(),
            note_id: "note:memory".into(),
            start: ordinal * 10,
            end: ordinal * 10 + 8,
            ordinal,
            source: "test".into(),
        }
    }

    fn anchor(id: &str, entity_id: &EntityId, chunk_id: &str) -> GraphAnchor {
        GraphAnchor {
            id: id.into(),
            entity_id: entity_id.clone(),
            note_id: "note:memory".into(),
            chunk_id: Some(chunk_id.into()),
            surface: "entity".into(),
            source_start: 0,
            source_end: 6,
            source: "test".into(),
            confidence: 1.0,
            generation: 1,
        }
    }

    fn event(id: &str, chunk_id: &str, entity_ids: &[EntityId]) -> GraphEvent {
        GraphEvent {
            id: id.into(),
            note_id: "note:memory".into(),
            chunk_id: Some(chunk_id.into()),
            label: "event".into(),
            entity_ids: entity_ids.to_vec(),
            evidence_anchor_ids: Vec::new(),
            confidence: 0.8,
        }
    }
}
