use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};

use crate::types::{
    GraphAnchor, GraphChunk, GraphEvent, GraphMemoryGovernanceAction,
    GraphMemoryGovernanceCandidate, GraphMemoryGovernanceCommitPolicy,
    GraphMemoryGovernanceSignals, GraphMemoryGovernanceStatus, GraphMemoryGovernanceTargetKind,
    GraphMemoryState, GraphRebuildSnapshot, GraphRelationship, GraphTemporalEdge,
};

pub const MEMORY_GOVERNANCE_SCHEMA_VERSION: &str = "phoenix-memory-governance-candidate/v1";
pub const MEMORY_GOVERNANCE_COMMIT_POLICY: &str = "no_topology_commit";
pub const MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT: &str =
    "memory_governance_candidate:no_topology_commit";
const CELEBRITY_ENTITY_PRESSURE_THRESHOLD: f32 = 0.20;
const WEAK_EVIDENCE_STRENGTH_THRESHOLD: f32 = 0.50;
const CONTRADICTION_QUARANTINE_THRESHOLD: f32 = 0.50;
const SUPERSESSION_ATTENUATE_THRESHOLD: f32 = 0.50;

#[path = "memory_governance_contradiction.rs"]
mod contradiction;
#[path = "memory_governance_retrieval_preview.rs"]
mod retrieval_preview;
#[path = "memory_governance_shortrun.rs"]
mod shortrun;
use contradiction::assign_contradiction_pressure;
pub use retrieval_preview::{
    build_memory_governance_retrieval_preview,
    build_memory_governance_retrieval_preview_with_policy,
    build_memory_governance_retrieval_weighting_experiment, MemoryGovernanceRetrievalCandidate,
    MemoryGovernanceRetrievalPreview, MemoryGovernanceRetrievalPreviewInput,
    MemoryGovernanceRetrievalPreviewRow, MemoryGovernanceRetrievalPreviewSummary,
    MemoryGovernanceRetrievalWeightPolicy, MemoryGovernanceRetrievalWeightingExperiment,
    MemoryGovernanceRetrievalWeightingVariant, MEMORY_GOVERNANCE_RETRIEVAL_PREVIEW_SCHEMA_VERSION,
    MEMORY_GOVERNANCE_RETRIEVAL_WEIGHTING_EXPERIMENT_SCHEMA_VERSION,
};
pub use shortrun::{
    build_memory_governance_shortrun_golden_report, MemoryGovernanceCandidateOnlyAudit,
    MemoryGovernanceConfidenceSummary, MemoryGovernanceCounts, MemoryGovernancePerformanceBudget,
    MemoryGovernanceRepresentativeRow, MemoryGovernanceShortrunComparison,
    MemoryGovernanceShortrunGoldenReport, MemoryGovernanceTimingReport,
};

#[derive(Clone, Copy, Debug, Default)]
pub struct MemoryGovernanceEngineInput<'a> {
    pub chunks: &'a [GraphChunk],
    pub episodes: &'a [crate::types::GraphEpisode],
    pub anchors: &'a [GraphAnchor],
    pub relationships: &'a [GraphRelationship],
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
    dominant_entity_pressure: f32,
    dominant_entity_count: usize,
    contradiction_risk: f32,
    contradiction_count: usize,
    contradiction_kinds: HashSet<CompactString>,
    supersession_risk: f32,
    supersession_count: usize,
    supersession_kinds: HashSet<CompactString>,
}

pub fn build_memory_governance_candidates_from_snapshot(
    snapshot: &GraphRebuildSnapshot,
) -> Vec<GraphMemoryGovernanceCandidate> {
    build_memory_governance_candidates(MemoryGovernanceEngineInput {
        chunks: &snapshot.chunks,
        episodes: &snapshot.episodes,
        anchors: &snapshot.entity_anchors,
        relationships: &snapshot.relationships,
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
    assign_entity_dominance(input.chunks.len(), &mut chunk_stats);
    assign_contradiction_pressure(input, &mut chunk_stats);
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
            .then_with(|| right.confidence.total_cmp(&left.confidence))
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
                    row.contradiction_risk =
                        row.contradiction_risk.max(chunk_row.contradiction_risk);
                    row.contradiction_count += chunk_row.contradiction_count;
                    row.contradiction_kinds
                        .extend(chunk_row.contradiction_kinds.iter().cloned());
                    row.supersession_risk = row.supersession_risk.max(chunk_row.supersession_risk);
                    row.supersession_count += chunk_row.supersession_count;
                    row.supersession_kinds
                        .extend(chunk_row.supersession_kinds.iter().cloned());
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
    let (action, reason) = if contradiction_quarantine_candidate(&signals) {
        (
            GraphMemoryGovernanceAction::Quarantine,
            "target_has_contradictory_memory_evidence",
        )
    } else if supersession_attenuate_candidate(&stats, &signals) {
        (
            GraphMemoryGovernanceAction::Attenuate,
            "target_superseded_by_later_memory_evidence",
        )
    } else if stats.causal_degree > 0 || stats.memory_state_count > 0 {
        (
            GraphMemoryGovernanceAction::Retain,
            "chunk_has_causal_or_memory_state_signal",
        )
    } else if stats.event_count == 0 && stats.entity_ids.is_empty() {
        (
            GraphMemoryGovernanceAction::Attenuate,
            "chunk_has_no_events_or_entity_evidence",
        )
    } else if celebrity_entity_dominance_candidate(&stats, &signals) {
        (
            GraphMemoryGovernanceAction::Quarantine,
            "chunk_entity_salience_dominated_by_celebrity_surface",
        )
    } else if stats.event_count == 0 && stats.redundancy >= 0.65 {
        (
            GraphMemoryGovernanceAction::Attenuate,
            "chunk_redundant_without_event_evidence",
        )
    } else {
        (
            GraphMemoryGovernanceAction::Retain,
            "chunk_has_retrieval_or_story_signal",
        )
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
    let action = if contradiction_quarantine_candidate(&signals) {
        GraphMemoryGovernanceAction::Quarantine
    } else if supersession_attenuate_candidate(&stats, &signals) {
        GraphMemoryGovernanceAction::Attenuate
    } else if stats.event_count == 0 {
        GraphMemoryGovernanceAction::Attenuate
    } else if stats.chunk_ids.len() > 1 && stats.event_count > 1 {
        GraphMemoryGovernanceAction::Compress
    } else {
        GraphMemoryGovernanceAction::Retain
    };
    let reason = match action {
        GraphMemoryGovernanceAction::Quarantine => "target_has_contradictory_memory_evidence",
        GraphMemoryGovernanceAction::Attenuate
            if stats.supersession_risk >= SUPERSESSION_ATTENUATE_THRESHOLD =>
        {
            "target_superseded_by_later_memory_evidence"
        }
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
    let confidence = governance_confidence(action, &stats, &signals);
    let mut rationale = vec![
        MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT.into(),
        "memory_governance:retrieval_policy_overlay".into(),
        format_compact!("reason:{reason}"),
    ];
    rationale.extend(governance_audit_rationale(action, reason, &stats));

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
        rationale,
    }
}

fn governance_confidence(
    action: GraphMemoryGovernanceAction,
    stats: &TargetStats,
    signals: &GraphMemoryGovernanceSignals,
) -> f32 {
    match action {
        GraphMemoryGovernanceAction::Compress => compression_confidence(stats),
        GraphMemoryGovernanceAction::Attenuate => clamp(
            0.52 + signals.redundancy * 0.18 + stats.supersession_risk * 0.18
                - signals.evidence_strength * 0.12,
        ),
        GraphMemoryGovernanceAction::Retain => {
            clamp(0.50 + signals.narrative_salience * 0.22 + signals.causal_importance * 0.16)
        }
        GraphMemoryGovernanceAction::Quarantine => clamp(
            0.58 + stats.dominant_entity_pressure * 0.25
                + signals.contradiction_risk * 0.24
                + signals.narrative_salience * 0.08
                - signals.evidence_strength * 0.08,
        ),
        GraphMemoryGovernanceAction::Retire => 0.0,
    }
}

fn compression_confidence(stats: &TargetStats) -> f32 {
    let event_span = soft_count(stats.event_count, 12.0);
    let chunk_span = soft_count(stats.chunk_ids.len(), 12.0);
    let evidence_density = soft_count(stats.evidence_ids.len(), 48.0);
    let entity_diversity = soft_count(stats.entity_ids.len(), 10.0);
    let causal_signal = soft_count(stats.causal_degree, 12.0);
    let temporal_signal = soft_count(stats.temporal_degree, 24.0);
    let memory_signal = soft_count(stats.memory_state_count, 8.0);

    clamp(
        0.62 + event_span * 0.10
            + chunk_span * 0.08
            + evidence_density * 0.10
            + entity_diversity * 0.07
            + causal_signal * 0.05
            + temporal_signal * 0.03
            + memory_signal * 0.02
            - stats.redundancy * 0.04,
    )
}

fn governance_audit_rationale(
    action: GraphMemoryGovernanceAction,
    reason: &str,
    stats: &TargetStats,
) -> Vec<CompactString> {
    let mut out = Vec::with_capacity(8);
    match action {
        GraphMemoryGovernanceAction::Attenuate => {
            if reason == "target_superseded_by_later_memory_evidence" {
                out.push("audit:superseded_memory_evidence".into());
                out.push(format_compact!(
                    "audit:supersession_risk:{:.2}",
                    stats.supersession_risk
                ));
                out.push(format_compact!(
                    "audit:supersession_count:{}",
                    stats.supersession_count
                ));
                let mut kinds = stats
                    .supersession_kinds
                    .iter()
                    .map(CompactString::as_str)
                    .collect::<Vec<_>>();
                kinds.sort_unstable();
                for kind in kinds {
                    out.push(format_compact!("audit:{kind}"));
                }
            }
            if stats.event_count == 0 {
                out.push("audit:no_events".into());
            }
            if stats.evidence_ids.is_empty() {
                out.push("audit:no_anchor_or_event_evidence".into());
            }
            if stats.entity_ids.is_empty() {
                out.push("audit:no_supporting_entities".into());
            }
            if stats.redundancy >= 0.65 {
                out.push(format_compact!("audit:redundancy:{:.2}", stats.redundancy));
            }
            if stats.causal_degree == 0 {
                out.push("audit:no_causal_edges".into());
            }
            if stats.memory_state_count == 0 {
                out.push("audit:no_memory_state".into());
            }
        }
        GraphMemoryGovernanceAction::Compress => {
            out.push(format_compact!(
                "audit:episode_events:{}",
                stats.event_count
            ));
            out.push(format_compact!(
                "audit:episode_chunks:{}",
                stats.chunk_ids.len()
            ));
            out.push(format_compact!(
                "audit:evidence:{}",
                stats.evidence_ids.len()
            ));
            out.push(format_compact!("audit:entities:{}", stats.entity_ids.len()));
            if stats.causal_degree > 0 {
                out.push(format_compact!(
                    "audit:causal_degree:{}",
                    stats.causal_degree
                ));
            }
            if stats.temporal_degree > 0 {
                out.push(format_compact!(
                    "audit:temporal_degree:{}",
                    stats.temporal_degree
                ));
            }
        }
        GraphMemoryGovernanceAction::Retain => {
            if stats.causal_degree > 0 {
                out.push(format_compact!(
                    "audit:causal_degree:{}",
                    stats.causal_degree
                ));
            }
            if stats.memory_state_count > 0 {
                out.push(format_compact!(
                    "audit:memory_state_count:{}",
                    stats.memory_state_count
                ));
            }
            if stats.event_count > 0 {
                out.push(format_compact!("audit:events:{}", stats.event_count));
            }
        }
        GraphMemoryGovernanceAction::Quarantine => {
            if reason == "target_has_contradictory_memory_evidence" {
                out.push("audit:contradictory_memory_evidence".into());
                out.push(format_compact!(
                    "audit:contradiction_risk:{:.2}",
                    stats.contradiction_risk
                ));
                out.push(format_compact!(
                    "audit:contradiction_count:{}",
                    stats.contradiction_count
                ));
                let mut kinds = stats
                    .contradiction_kinds
                    .iter()
                    .map(CompactString::as_str)
                    .collect::<Vec<_>>();
                kinds.sort_unstable();
                for kind in kinds {
                    out.push(format_compact!("audit:{kind}"));
                }
            } else {
                out.push("audit:celebrity_entity_dominance".into());
                out.push(format_compact!(
                    "audit:dominant_entity_pressure:{:.2}",
                    stats.dominant_entity_pressure
                ));
            }
            if stats.event_count == 0 {
                out.push("audit:no_events".into());
            }
            if stats.evidence_ids.len() <= 3 {
                out.push(format_compact!(
                    "audit:weak_evidence:{}",
                    stats.evidence_ids.len()
                ));
            }
            if stats.causal_degree == 0 {
                out.push("audit:no_causal_edges".into());
            }
            if stats.memory_state_count == 0 {
                out.push("audit:no_memory_state".into());
            }
        }
        GraphMemoryGovernanceAction::Retire => {}
    }
    if out.is_empty() {
        out.push(format_compact!("audit:{reason}"));
    }
    out
}

fn signals(stats: &TargetStats) -> GraphMemoryGovernanceSignals {
    let evidence = stats.evidence_ids.len() as f32;
    let entities = stats.entity_ids.len() as f32;
    let events = stats.event_count as f32;
    let causal = stats.causal_degree as f32;
    let temporal = stats.temporal_degree as f32;
    GraphMemoryGovernanceSignals {
        age: stats.supersession_risk,
        access_frequency: 0.0,
        redundancy: stats.redundancy,
        contradiction_risk: stats.contradiction_risk,
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

fn assign_entity_dominance(chunk_count: usize, stats: &mut HashMap<&str, TargetStats>) {
    let mut entity_counts = HashMap::<CompactString, usize>::new();
    for row in stats.values() {
        for entity_id in &row.entity_ids {
            *entity_counts.entry(entity_id.clone()).or_insert(0) += 1;
        }
    }
    let denominator = chunk_count.max(1) as f32;
    for row in stats.values_mut() {
        let mut dominant_count = 0_usize;
        row.dominant_entity_pressure = row
            .entity_ids
            .iter()
            .filter_map(|entity_id| entity_counts.get(entity_id).copied())
            .inspect(|count| {
                if *count as f32 / denominator >= CELEBRITY_ENTITY_PRESSURE_THRESHOLD {
                    dominant_count += 1;
                }
            })
            .max()
            .map(|count| count as f32 / denominator)
            .unwrap_or(0.0)
            .min(1.0);
        row.dominant_entity_count = dominant_count;
    }
}

fn celebrity_entity_dominance_candidate(
    stats: &TargetStats,
    signals: &GraphMemoryGovernanceSignals,
) -> bool {
    stats.event_count == 0
        && stats.entity_ids.len() >= 2
        && stats.causal_degree == 0
        && stats.memory_state_count == 0
        && stats.dominant_entity_pressure >= CELEBRITY_ENTITY_PRESSURE_THRESHOLD
        && stats.dominant_entity_count >= 2
        && signals.evidence_strength <= WEAK_EVIDENCE_STRENGTH_THRESHOLD
}

fn contradiction_quarantine_candidate(signals: &GraphMemoryGovernanceSignals) -> bool {
    signals.contradiction_risk >= CONTRADICTION_QUARANTINE_THRESHOLD && !signals.user_pinned
}

fn supersession_attenuate_candidate(
    stats: &TargetStats,
    signals: &GraphMemoryGovernanceSignals,
) -> bool {
    stats.supersession_risk >= SUPERSESSION_ATTENUATE_THRESHOLD && !signals.user_pinned
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

fn soft_count(count: usize, scale: f32) -> f32 {
    let count = count as f32;
    if count <= 0.0 {
        0.0
    } else {
        count / (count + scale)
    }
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
#[path = "memory_governance_tests.rs"]
mod tests;
