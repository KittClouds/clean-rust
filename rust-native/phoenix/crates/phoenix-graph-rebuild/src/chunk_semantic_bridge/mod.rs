//! Pure chunk semantic bridge candidate engine.
//!
//! This module borrows chunk, event, entity, and evidence rows, then returns
//! candidate-only bridge rows. It does not own persistence, graph promotion, or
//! Overgraph writes.

use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};
use phoenix_types::EntityId;

mod cues;
mod promotion;
#[cfg(test)]
mod promotion_tests;
mod promotion_types;
mod quality_gate;
mod shortrun_parity;
mod snapshot_adapter;
#[cfg(test)]
mod tests;
mod types;

use cues::*;
pub use promotion::promote_chunk_semantic_bridge_candidates;
pub use promotion_types::{
    ChunkSemanticBridgePromotionAudit, ChunkSemanticBridgePromotionChunk,
    ChunkSemanticBridgePromotionCommitPolicy, ChunkSemanticBridgePromotionInput,
    ChunkSemanticBridgePromotionOutput, ChunkSemanticBridgePromotionProposal,
    ChunkSemanticBridgePromotionRejection, ChunkSemanticBridgePromotionStatus,
    CHUNK_SEMANTIC_BRIDGE_PROMOTION_COMMIT_POLICY,
    CHUNK_SEMANTIC_BRIDGE_PROMOTION_NO_TOPOLOGY_COMMIT,
    CHUNK_SEMANTIC_BRIDGE_PROMOTION_SCHEMA_VERSION,
};
pub use quality_gate::{
    audit_chunk_semantic_bridge_quality_gate, bridge_quality_gate_decision,
    is_same_entity_only_bridge_suspect, BridgeQualityGateAudit, BridgeQualityGateDecision,
};
#[allow(unused_imports)]
pub use shortrun_parity::{
    build_chunk_semantic_bridge_shortrun_parity_report, BridgeCandidateOnlyAudit, BridgeCounts,
    BridgeRepresentativeRow, BridgeShortrunParityComparison, BridgeShortrunParityReport,
    BridgeTimingReport,
};
pub use snapshot_adapter::{
    build_chunk_semantic_bridge_candidates_from_snapshot, ChunkSemanticBridgeSnapshotDocument,
};
pub use types::{
    ChunkSemanticBridgeCandidate, ChunkSemanticBridgeChunk, ChunkSemanticBridgeCommitPolicy,
    ChunkSemanticBridgeEngineInput, ChunkSemanticBridgeEntity, ChunkSemanticBridgeEvent,
    ChunkSemanticBridgeEventEdge, ChunkSemanticBridgeEvidence, ChunkSemanticBridgeStatus,
    ChunkSemanticBridgeType, CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY,
    CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT, CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION,
};

const BRIDGE_LIMIT: usize = 320;
const BRIDGE_TYPE_QUOTA: usize = 40;
const MAX_DISTANCE: u32 = 36;

struct EngineIndex<'a> {
    chunk_by_id: HashMap<&'a str, usize>,
    event_by_id: HashMap<&'a str, usize>,
    event_by_chunk: HashMap<&'a str, usize>,
    lower_chunk_text: Vec<String>,
}

struct BridgeClass<'a> {
    bridge_type: ChunkSemanticBridgeType,
    semantic_verbs: &'static [&'static str],
    source_cue: Option<&'a str>,
    target_cue: Option<&'a str>,
    confidence: f32,
    rationale: CompactString,
}

pub fn build_chunk_semantic_bridge_candidates(
    input: ChunkSemanticBridgeEngineInput<'_>,
) -> Vec<ChunkSemanticBridgeCandidate> {
    let index = EngineIndex::new(input);
    let mut bridges = HashMap::<CompactString, ChunkSemanticBridgeCandidate>::new();

    for edge in input.causal_edges {
        let Some(source_event) = event_for(input, &index, edge.source_event_id) else {
            continue;
        };
        let Some(target_event) = event_for(input, &index, edge.target_event_id) else {
            continue;
        };
        let class = BridgeClass {
            bridge_type: ChunkSemanticBridgeType::CauseEffect,
            semantic_verbs: &["causes", "enables", "answers"],
            source_cue: edge.cue.or(Some("causal_edge")),
            target_cue: Some(edge.relation_type),
            confidence: edge.confidence.max(0.64),
            rationale: "causal_event_edge_seed".into(),
        };
        insert_bridge(
            &mut bridges,
            input,
            event_chunk(input, &index, source_event),
            event_chunk(input, &index, target_event),
            class,
            Some(source_event),
            Some(target_event),
            edge.evidence_ids,
        );
    }

    for edge in input.temporal_edges {
        let Some(source_event) = event_for(input, &index, edge.source_event_id) else {
            continue;
        };
        let Some(target_event) = event_for(input, &index, edge.target_event_id) else {
            continue;
        };
        let source = event_chunk(input, &index, source_event);
        let target = event_chunk(input, &index, target_event);
        let Some(class) =
            classify_temporal(input, &index, source, target, source_event, target_event)
        else {
            continue;
        };
        insert_bridge(
            &mut bridges,
            input,
            source,
            target,
            class,
            Some(source_event),
            Some(target_event),
            edge.evidence_ids,
        );
    }

    for note_chunks in chunks_by_note(input.chunks) {
        for left_index in 0..note_chunks.len().saturating_sub(2) {
            let max_right = (left_index + MAX_DISTANCE as usize + 1).min(note_chunks.len());
            for right_index in left_index + 2..max_right {
                let source = &input.chunks[note_chunks[left_index]];
                let target = &input.chunks[note_chunks[right_index]];
                let shared = shared_entities(source.entity_ids, target.entity_ids);
                if shared.is_empty() {
                    continue;
                }
                let source_event = index
                    .event_by_chunk
                    .get(source.id)
                    .map(|row| &input.events[*row]);
                let target_event = index
                    .event_by_chunk
                    .get(target.id)
                    .map(|row| &input.events[*row]);
                let Some(class) = classify_pair(
                    input,
                    &index,
                    source,
                    target,
                    source_event,
                    target_event,
                    shared.len(),
                ) else {
                    continue;
                };
                insert_bridge(
                    &mut bridges,
                    input,
                    Some(source),
                    Some(target),
                    class,
                    source_event,
                    target_event,
                    &[],
                );
            }
        }
    }

    select_bridge_rows(
        bridges
            .into_values()
            .filter(|bridge| {
                bridge_quality_gate_decision(bridge) == BridgeQualityGateDecision::Accept
            })
            .collect(),
    )
}

pub fn assert_chunk_semantic_bridge_candidate_only(
    candidates: &[ChunkSemanticBridgeCandidate],
) -> Result<(), CompactString> {
    for bridge in candidates {
        if bridge.schema_version != CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION {
            return Err(format_compact!("{} has wrong schema version", bridge.id));
        }
        if bridge.status != ChunkSemanticBridgeStatus::Candidate {
            return Err(format_compact!("{} must stay candidate-only", bridge.id));
        }
        if bridge.commit_policy != ChunkSemanticBridgeCommitPolicy::NoTopologyCommit {
            return Err(format_compact!(
                "{} cannot request topology commit",
                bridge.id
            ));
        }
        if !bridge
            .rationale
            .iter()
            .any(|row| row == CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT)
        {
            return Err(format_compact!("{} missing no-topology receipt", bridge.id));
        }
    }
    Ok(())
}

impl<'a> EngineIndex<'a> {
    fn new(input: ChunkSemanticBridgeEngineInput<'a>) -> Self {
        let mut chunk_by_id = HashMap::with_capacity(input.chunks.len());
        let mut lower_chunk_text = Vec::with_capacity(input.chunks.len());
        for (index, chunk) in input.chunks.iter().enumerate() {
            chunk_by_id.insert(chunk.id, index);
            lower_chunk_text.push(chunk.text.to_ascii_lowercase());
        }

        let mut event_by_id = HashMap::with_capacity(input.events.len());
        let mut event_by_chunk = HashMap::with_capacity(input.events.len());
        for (index, event) in input.events.iter().enumerate() {
            event_by_id.insert(event.id, index);
            if let Some(chunk_id) = event.chunk_id {
                event_by_chunk.entry(chunk_id).or_insert(index);
            }
        }

        Self {
            chunk_by_id,
            event_by_id,
            event_by_chunk,
            lower_chunk_text,
        }
    }
}

fn insert_bridge(
    bridges: &mut HashMap<CompactString, ChunkSemanticBridgeCandidate>,
    input: ChunkSemanticBridgeEngineInput<'_>,
    source: Option<&ChunkSemanticBridgeChunk<'_>>,
    target: Option<&ChunkSemanticBridgeChunk<'_>>,
    class: BridgeClass<'_>,
    source_event: Option<&ChunkSemanticBridgeEvent<'_>>,
    target_event: Option<&ChunkSemanticBridgeEvent<'_>>,
    edge_evidence_ids: &[CompactString],
) {
    let (Some(source), Some(target)) = (source, target) else {
        return;
    };
    if source.id == target.id || source.note_id != target.note_id {
        return;
    }
    let supporting_entity_ids = shared_entities(source.entity_ids, target.entity_ids);
    if supporting_entity_ids.is_empty() {
        return;
    }
    let distance = source.ordinal.abs_diff(target.ordinal);
    let confidence = clamp(
        class.confidence + (supporting_entity_ids.len() as f32 * 0.015).min(0.08)
            - ((distance as f32) * 0.002).min(0.08),
        0.52,
        0.92,
    );
    let id = format_compact!(
        "chunk_semantic_bridge:{}:{}:{}",
        class.bridge_type.as_str(),
        slug(source.id),
        slug(target.id)
    );

    let current = bridges.remove(&id);
    let mut evidence_ids = current
        .as_ref()
        .map(|bridge| bridge.evidence_ids.clone())
        .unwrap_or_default();
    push_unique(&mut evidence_ids, source.id.into());
    push_unique(&mut evidence_ids, target.id.into());
    if let Some(event) = source_event {
        push_unique(&mut evidence_ids, event.id.into());
        push_all_unique(&mut evidence_ids, event.evidence_ids);
    }
    if let Some(event) = target_event {
        push_unique(&mut evidence_ids, event.id.into());
        push_all_unique(&mut evidence_ids, event.evidence_ids);
    }
    push_all_unique(&mut evidence_ids, source.evidence_ids);
    push_all_unique(&mut evidence_ids, target.evidence_ids);
    push_all_unique(&mut evidence_ids, edge_evidence_ids);

    let mut semantic_verbs = current
        .as_ref()
        .map(|bridge| bridge.semantic_verbs.clone())
        .unwrap_or_default();
    for verb in class.semantic_verbs {
        push_unique(&mut semantic_verbs, (*verb).into());
    }

    let mut rationale = current
        .as_ref()
        .map(|bridge| bridge.rationale.clone())
        .unwrap_or_default();
    push_unique(
        &mut rationale,
        CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT.into(),
    );
    push_unique(
        &mut rationale,
        format_compact!("bridge_type:{}", class.bridge_type.as_str()),
    );
    push_unique(
        &mut rationale,
        format_compact!("supporting_entities:{}", supporting_entity_ids.len()),
    );
    push_unique(&mut rationale, format_compact!("chunk_distance:{distance}"));
    push_unique(&mut rationale, class.rationale);

    let mut merged_supporting_entities = current
        .as_ref()
        .map(|bridge| bridge.supporting_entity_ids.clone())
        .unwrap_or_default();
    for entity_id in supporting_entity_ids {
        push_entity_unique(&mut merged_supporting_entities, entity_id);
    }

    let claim = current
        .as_ref()
        .map(|bridge| bridge.claim.clone())
        .unwrap_or_else(|| {
            chunk_bridge_claim(
                class.bridge_type,
                source.ordinal,
                target.ordinal,
                merged_supporting_entities.len(),
            )
        });

    bridges.insert(
        id.clone(),
        ChunkSemanticBridgeCandidate {
            schema_version: CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION.into(),
            id,
            bridge_type: class.bridge_type,
            source_chunk_id: source.id.into(),
            target_chunk_id: target.id.into(),
            source_event_id: source_event.map(|event| event.id.into()),
            target_event_id: target_event.map(|event| event.id.into()),
            source_episode_id: source.episode_id.map(CompactString::from),
            target_episode_id: target.episode_id.map(CompactString::from),
            claim,
            evidence_ids,
            supporting_entity_ids: merged_supporting_entities,
            confidence: current
                .as_ref()
                .map(|bridge| bridge.confidence.max(confidence))
                .unwrap_or(confidence),
            status: ChunkSemanticBridgeStatus::Candidate,
            commit_policy: ChunkSemanticBridgeCommitPolicy::NoTopologyCommit,
            semantic_verbs,
            source_cue: current
                .as_ref()
                .and_then(|bridge| bridge.source_cue.clone())
                .or_else(|| class.source_cue.map(CompactString::from)),
            target_cue: current
                .as_ref()
                .and_then(|bridge| bridge.target_cue.clone())
                .or_else(|| class.target_cue.map(CompactString::from)),
            rationale,
        },
    );
    let _ = input;
}

fn classify_temporal<'a>(
    input: ChunkSemanticBridgeEngineInput<'a>,
    index: &'a EngineIndex<'a>,
    source: Option<&'a ChunkSemanticBridgeChunk<'a>>,
    target: Option<&'a ChunkSemanticBridgeChunk<'a>>,
    source_event: &'a ChunkSemanticBridgeEvent<'a>,
    target_event: &'a ChunkSemanticBridgeEvent<'a>,
) -> Option<BridgeClass<'a>> {
    let (Some(source), Some(target)) = (source, target) else {
        return None;
    };
    let left = lower_text(input, index, source)?;
    let right = lower_text(input, index, target)?;
    let route_cue = cue_hit_pair(left, right, ROUTE_CUES);
    if route_cue.is_some() || source.role == Some("transition") || target.role == Some("transition")
    {
        return Some(bridge_class(
            ChunkSemanticBridgeType::RouteContinuity,
            &["continues", "crosses", "moves"],
            cue_hit(left, ROUTE_CUES).or(source.role),
            cue_hit(right, ROUTE_CUES).or(target.role),
            0.64,
            "temporal_event_edge_route_seed",
        ));
    }
    if event_type(source_event) == event_type(target_event) && event_type(source_event).is_some() {
        return Some(bridge_class(
            ChunkSemanticBridgeType::TopicContinuation,
            &["continues", "carries"],
            event_type(source_event),
            event_type(target_event),
            0.60,
            "temporal_event_edge_same_event_type",
        ));
    }
    None
}

fn classify_pair<'a>(
    input: ChunkSemanticBridgeEngineInput<'a>,
    index: &'a EngineIndex<'a>,
    source: &'a ChunkSemanticBridgeChunk<'a>,
    target: &'a ChunkSemanticBridgeChunk<'a>,
    source_event: Option<&'a ChunkSemanticBridgeEvent<'a>>,
    target_event: Option<&'a ChunkSemanticBridgeEvent<'a>>,
    shared_entity_count: usize,
) -> Option<BridgeClass<'a>> {
    let left = lower_text(input, index, source)?;
    let right = lower_text(input, index, target)?;
    let source_setup = cue_hit(left, SETUP_CUES);
    let target_payoff = cue_hit(right, PAYOFF_CUES);
    if let (Some(source_cue), Some(target_cue)) = (source_setup, target_payoff) {
        return Some(bridge_class(
            ChunkSemanticBridgeType::SetupPayoff,
            &["sets_up", "pays_off", "answers"],
            Some(source_cue),
            Some(target_cue),
            0.74,
            "setup_cue_plus_later_payoff_cue",
        ));
    }
    if let Some(cue) = cue_hit_pair(left, right, CAUSE_CUES) {
        return Some(bridge_class(
            ChunkSemanticBridgeType::CauseEffect,
            &["causes", "explains", "answers"],
            Some(cue),
            cue_hit(right, CAUSE_CUES),
            0.70,
            "causal_language_spans_chunks",
        ));
    }
    if let Some(cue) = cue_hit_pair(left, right, EVIDENCE_CUES) {
        return Some(bridge_class(
            ChunkSemanticBridgeType::EvidenceReframe,
            &["reframes", "documents", "explains"],
            Some(cue),
            cue_hit(right, EVIDENCE_CUES),
            0.69,
            "evidence_or_documentation_reframes_prior_chunk",
        ));
    }
    if let Some(cue) = cue_hit_pair(left, right, RELATIONSHIP_DELTA_CUES) {
        if shared_entity_count >= 2 {
            return Some(bridge_class(
                ChunkSemanticBridgeType::RelationshipDelta,
                &["shifts", "pressures", "realigns"],
                cue_hit(left, RELATIONSHIP_DELTA_CUES),
                Some(cue),
                0.67,
                "relationship_cue_with_shared_participants",
            ));
        }
    }
    if let Some(cue) = cue_hit_pair(left, right, ROUTE_CUES) {
        return Some(bridge_class(
            ChunkSemanticBridgeType::RouteContinuity,
            &["continues", "crosses", "moves"],
            cue_hit(left, ROUTE_CUES),
            Some(cue),
            0.66,
            "route_or_threshold_cue_spans_chunks",
        ));
    }
    if let Some(change_cue) = cue_hit(right, CHANGE_CUES) {
        if cue_hit(left, STATE_CUES).is_some() {
            return Some(bridge_class(
                ChunkSemanticBridgeType::StateDelta,
                &["changes", "updates", "reverses"],
                cue_hit(left, STATE_CUES),
                Some(change_cue),
                0.65,
                "later_chunk_changes_prior_state",
            ));
        }
    }
    if let Some(motif) = shared_motif(left, right) {
        return Some(bridge_class(
            ChunkSemanticBridgeType::MotifEcho,
            &["echoes", "recurs", "recontextualizes"],
            Some(motif),
            Some(motif),
            0.62,
            format_compact!("motif:{motif}"),
        ));
    }
    if shared_entity_count >= 2 && same_event_type(source_event, target_event) {
        return Some(bridge_class(
            ChunkSemanticBridgeType::TopicContinuation,
            &["continues", "carries", "extends"],
            source_event.and_then(event_type),
            target_event.and_then(event_type),
            0.58,
            "same_frame_or_event_type_with_shared_participants",
        ));
    }
    None
}

fn select_bridge_rows(
    mut bridges: Vec<ChunkSemanticBridgeCandidate>,
) -> Vec<ChunkSemanticBridgeCandidate> {
    bridges.sort_by(compare_bridge_rows);
    let mut selected = HashMap::<CompactString, ChunkSemanticBridgeCandidate>::new();
    for bridge_type in [
        ChunkSemanticBridgeType::SetupPayoff,
        ChunkSemanticBridgeType::CauseEffect,
        ChunkSemanticBridgeType::EvidenceReframe,
        ChunkSemanticBridgeType::RelationshipDelta,
        ChunkSemanticBridgeType::StateDelta,
        ChunkSemanticBridgeType::RouteContinuity,
        ChunkSemanticBridgeType::MotifEcho,
        ChunkSemanticBridgeType::TopicContinuation,
    ] {
        for row in bridges
            .iter()
            .filter(|bridge| bridge.bridge_type == bridge_type)
            .take(BRIDGE_TYPE_QUOTA)
        {
            selected.insert(row.id.clone(), row.clone());
        }
    }
    for row in bridges {
        if selected.len() >= BRIDGE_LIMIT {
            break;
        }
        selected.insert(row.id.clone(), row);
    }
    let mut out: Vec<_> = selected.into_values().collect();
    out.sort_by(compare_bridge_rows);
    out.truncate(BRIDGE_LIMIT);
    out
}

fn compare_bridge_rows(
    left: &ChunkSemanticBridgeCandidate,
    right: &ChunkSemanticBridgeCandidate,
) -> std::cmp::Ordering {
    bridge_rank(left.bridge_type)
        .cmp(&bridge_rank(right.bridge_type))
        .then_with(|| right.confidence.total_cmp(&left.confidence))
        .then_with(|| left.source_chunk_id.cmp(&right.source_chunk_id))
        .then_with(|| left.target_chunk_id.cmp(&right.target_chunk_id))
}

fn bridge_rank(bridge_type: ChunkSemanticBridgeType) -> u8 {
    match bridge_type {
        ChunkSemanticBridgeType::SetupPayoff => 0,
        ChunkSemanticBridgeType::CauseEffect => 1,
        ChunkSemanticBridgeType::EvidenceReframe => 2,
        ChunkSemanticBridgeType::RelationshipDelta => 3,
        ChunkSemanticBridgeType::StateDelta => 4,
        ChunkSemanticBridgeType::RouteContinuity => 5,
        ChunkSemanticBridgeType::MotifEcho => 6,
        ChunkSemanticBridgeType::TopicContinuation => 7,
    }
}

fn bridge_class<'a>(
    bridge_type: ChunkSemanticBridgeType,
    semantic_verbs: &'static [&'static str],
    source_cue: Option<&'a str>,
    target_cue: Option<&'a str>,
    confidence: f32,
    rationale: impl Into<CompactString>,
) -> BridgeClass<'a> {
    BridgeClass {
        bridge_type,
        semantic_verbs,
        source_cue,
        target_cue,
        confidence,
        rationale: rationale.into(),
    }
}

fn chunk_bridge_claim(
    bridge_type: ChunkSemanticBridgeType,
    source_ordinal: u32,
    target_ordinal: u32,
    supporting_entity_count: usize,
) -> CompactString {
    let left = source_ordinal + 1;
    let right = target_ordinal + 1;
    match bridge_type {
        ChunkSemanticBridgeType::SetupPayoff => format_compact!(
            "Chunk {left} sets up an intent, risk, or question that Chunk {right} later answers; supporting_entities:{supporting_entity_count}."
        ),
        ChunkSemanticBridgeType::CauseEffect => format_compact!(
            "Chunk {left} creates pressure or cause that Chunk {right} responds to; supporting_entities:{supporting_entity_count}."
        ),
        ChunkSemanticBridgeType::StateDelta => format_compact!(
            "Chunk {right} changes a state established by Chunk {left}; supporting_entities:{supporting_entity_count}."
        ),
        ChunkSemanticBridgeType::RelationshipDelta => format_compact!(
            "Chunk {right} shifts a relationship pattern active in Chunk {left}; supporting_entities:{supporting_entity_count}."
        ),
        ChunkSemanticBridgeType::EvidenceReframe => format_compact!(
            "Chunk {right} reframes Chunk {left} through evidence, records, or documentation; supporting_entities:{supporting_entity_count}."
        ),
        ChunkSemanticBridgeType::MotifEcho => format_compact!(
            "Chunk {right} echoes a motif from Chunk {left} with new context; supporting_entities:{supporting_entity_count}."
        ),
        ChunkSemanticBridgeType::RouteContinuity => format_compact!(
            "Chunk {right} continues the route, threshold, or spatial transition opened by Chunk {left}; supporting_entities:{supporting_entity_count}."
        ),
        ChunkSemanticBridgeType::TopicContinuation => format_compact!(
            "Chunk {right} continues an unresolved topic or thread from Chunk {left}; supporting_entities:{supporting_entity_count}."
        ),
    }
}

fn chunks_by_note(chunks: &[ChunkSemanticBridgeChunk<'_>]) -> Vec<Vec<usize>> {
    let mut buckets = HashMap::<&str, Vec<usize>>::new();
    for (index, chunk) in chunks.iter().enumerate() {
        buckets.entry(chunk.note_id).or_default().push(index);
    }
    let mut out: Vec<_> = buckets.into_values().collect();
    for rows in &mut out {
        rows.sort_by_key(|index| chunks[*index].ordinal);
    }
    out
}

fn event_for<'a>(
    input: ChunkSemanticBridgeEngineInput<'a>,
    index: &EngineIndex<'a>,
    event_id: &str,
) -> Option<&'a ChunkSemanticBridgeEvent<'a>> {
    index
        .event_by_id
        .get(event_id)
        .map(|row| &input.events[*row])
}

fn event_chunk<'a>(
    input: ChunkSemanticBridgeEngineInput<'a>,
    index: &EngineIndex<'a>,
    event: &ChunkSemanticBridgeEvent<'a>,
) -> Option<&'a ChunkSemanticBridgeChunk<'a>> {
    event
        .chunk_id
        .and_then(|id| index.chunk_by_id.get(id))
        .map(|row| &input.chunks[*row])
}

fn lower_text<'a>(
    input: ChunkSemanticBridgeEngineInput<'a>,
    index: &'a EngineIndex<'a>,
    chunk: &ChunkSemanticBridgeChunk<'_>,
) -> Option<&'a str> {
    index
        .chunk_by_id
        .get(chunk.id)
        .and_then(|row| index.lower_chunk_text.get(*row))
        .map(String::as_str)
        .or_else(|| {
            input
                .chunks
                .iter()
                .find(|row| row.id == chunk.id)
                .map(|row| row.text)
        })
}

fn cue_hit<'a>(text: &'a str, cues: &[&'a str]) -> Option<&'a str> {
    cues.iter()
        .copied()
        .find(|cue| memchr::memmem::find(text.as_bytes(), cue.as_bytes()).is_some())
}

fn cue_hit_pair<'a>(left: &'a str, right: &'a str, cues: &[&'a str]) -> Option<&'a str> {
    cue_hit(left, cues).or_else(|| cue_hit(right, cues))
}

fn shared_motif<'a>(left: &'a str, right: &'a str) -> Option<&'a str> {
    MOTIF_CUES.iter().copied().find(|motif| {
        memchr::memmem::find(left.as_bytes(), motif.as_bytes()).is_some()
            && memchr::memmem::find(right.as_bytes(), motif.as_bytes()).is_some()
    })
}

fn same_event_type(
    source: Option<&ChunkSemanticBridgeEvent<'_>>,
    target: Option<&ChunkSemanticBridgeEvent<'_>>,
) -> bool {
    match (source.and_then(event_type), target.and_then(event_type)) {
        (Some(left), Some(right)) => left == right,
        _ => false,
    }
}

fn event_type<'a>(event: &'a ChunkSemanticBridgeEvent<'_>) -> Option<&'a str> {
    event.label.split_once(" in chunk ").map(|(label, _)| label)
}

fn shared_entities(left: &[EntityId], right: &[EntityId]) -> Vec<CompactString> {
    let mut seen = HashSet::<&EntityId>::with_capacity(right.len());
    for entity_id in right {
        seen.insert(entity_id);
    }
    let mut out = Vec::new();
    for entity_id in left {
        if seen.contains(entity_id) {
            push_entity_unique(&mut out, entity_id.0.as_str().into());
        }
    }
    out
}

fn push_all_unique(out: &mut Vec<CompactString>, values: &[CompactString]) {
    for value in values {
        push_unique(out, value.clone());
    }
}

fn push_unique(out: &mut Vec<CompactString>, value: CompactString) {
    if !out.iter().any(|existing| existing == &value) {
        out.push(value);
    }
}

fn push_entity_unique(out: &mut Vec<CompactString>, value: CompactString) {
    if !out.iter().any(|existing| existing == &value) {
        out.push(value);
    }
}

fn clamp(value: f32, min: f32, max: f32) -> f32 {
    if value.is_finite() {
        value.clamp(min, max)
    } else {
        min
    }
}

fn slug(value: &str) -> CompactString {
    let mut out = String::with_capacity(value.len());
    let mut pending_dash = false;
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() {
            if pending_dash && !out.is_empty() {
                out.push('-');
            }
            out.push(byte.to_ascii_lowercase() as char);
            pending_dash = false;
        } else {
            pending_dash = true;
        }
    }
    if out.is_empty() {
        "row".into()
    } else {
        out.into()
    }
}
