use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};

use crate::{
    ChunkSemanticBridgeCandidate, ChunkSemanticBridgeType, DocumentSemanticSummary,
    GraphRebuildSnapshot,
};

use super::events::EventBuild;
use super::types::{
    ContinuityCausalCandidate, ContinuityCausalRelation, ContinuityConflictCandidate,
    ContinuityEvidenceClass, ContinuityStateIntervalCandidate, ContinuityStatus,
    ContinuityTemporalCandidate, ContinuityTemporalRelation, EpisodeContinuityCandidate,
    EpisodeContinuityKind, StoryEpisodeCandidate,
};

pub(super) struct RelationBuild {
    pub temporal: Vec<ContinuityTemporalCandidate>,
    pub state_intervals: Vec<ContinuityStateIntervalCandidate>,
    pub causal: Vec<ContinuityCausalCandidate>,
    pub episode_connections: Vec<EpisodeContinuityCandidate>,
    pub conflicts: Vec<ContinuityConflictCandidate>,
}

pub(super) fn build_relations(
    snapshot: &GraphRebuildSnapshot,
    semantic: Option<&DocumentSemanticSummary>,
    bridges: &[ChunkSemanticBridgeCandidate],
    events: &EventBuild,
    episodes: &[StoryEpisodeCandidate],
    event_episode: &HashMap<CompactString, CompactString>,
) -> RelationBuild {
    let mut temporal = semantic_temporal(semantic, events);
    append_legacy_temporal(snapshot, events, &mut temporal);
    append_episode_temporal(episodes, &mut temporal);
    let state_intervals = semantic_state_intervals(semantic, events);
    let mut causal = semantic_causal(semantic, events);
    append_legacy_causal(snapshot, events, &mut causal);
    let conflicts = semantic_conflicts(semantic, events);
    let episode_connections = episode_connections(
        episodes,
        event_episode,
        &temporal,
        &state_intervals,
        bridges,
    );
    RelationBuild {
        temporal,
        state_intervals,
        causal,
        episode_connections,
        conflicts,
    }
}

fn semantic_temporal(
    semantic: Option<&DocumentSemanticSummary>,
    events: &EventBuild,
) -> Vec<ContinuityTemporalCandidate> {
    let mut out = Vec::new();
    let mut seen = HashSet::new();
    for row in semantic
        .into_iter()
        .flat_map(|summary| &summary.documents)
        .flat_map(|document| &document.event_orderings)
    {
        let Some(source_id) = events
            .situation_to_event
            .get(row.source_situation_id.as_str())
        else {
            continue;
        };
        let Some(target_id) = events
            .situation_to_event
            .get(row.target_situation_id.as_str())
        else {
            continue;
        };
        let relation = temporal_relation(&row.relation);
        let id = format_compact!(
            "continuity:temporal:{}:{:?}:{}",
            source_id,
            relation,
            target_id
        );
        if !seen.insert(id.clone()) {
            continue;
        }
        out.push(ContinuityTemporalCandidate {
            id,
            source_id: source_id.clone(),
            target_id: target_id.clone(),
            relation,
            evidence_class: if row.source.contains("calendar") {
                ContinuityEvidenceClass::Calendar
            } else if row.cue.is_some() || row.source.contains("explicit") {
                ContinuityEvidenceClass::ExplicitCue
            } else {
                ContinuityEvidenceClass::DocumentOrder
            },
            evidence_ids: vec![row.id.clone().into()],
            cue: row.cue.clone().map(CompactString::from),
            confidence_millis: row.confidence_millis,
            status: if row.failure_reasons.is_empty() {
                ContinuityStatus::Candidate
            } else {
                ContinuityStatus::ReviewRequired
            },
            no_topology_commit: true,
        });
    }
    out
}

fn append_legacy_temporal(
    snapshot: &GraphRebuildSnapshot,
    events: &EventBuild,
    out: &mut Vec<ContinuityTemporalCandidate>,
) {
    let mut pairs = out
        .iter()
        .map(|row| (row.source_id.clone(), row.target_id.clone()))
        .collect::<HashSet<_>>();
    for row in &snapshot.temporal_edges {
        let Some(source_id) = events.legacy_to_event.get(&row.source_id) else {
            continue;
        };
        let Some(target_id) = events.legacy_to_event.get(&row.target_id) else {
            continue;
        };
        if !pairs.insert((source_id.clone(), target_id.clone())) {
            continue;
        }
        out.push(ContinuityTemporalCandidate {
            id: format_compact!("continuity:temporal:legacy:{}:{}", source_id, target_id),
            source_id: source_id.clone(),
            target_id: target_id.clone(),
            relation: temporal_relation(row.relation_type.as_str()),
            evidence_class: ContinuityEvidenceClass::LegacyAdjacency,
            evidence_ids: row.evidence_ids.clone(),
            cue: None,
            confidence_millis: confidence_millis(row.confidence),
            status: ContinuityStatus::ReviewRequired,
            no_topology_commit: true,
        });
    }
}

fn append_episode_temporal(
    episodes: &[StoryEpisodeCandidate],
    out: &mut Vec<ContinuityTemporalCandidate>,
) {
    for pair in episodes.windows(2) {
        if pair[0].note_id != pair[1].note_id {
            continue;
        }
        out.push(ContinuityTemporalCandidate {
            id: format_compact!("continuity:temporal:episode:{}:{}", pair[0].id, pair[1].id),
            source_id: pair[0].id.clone(),
            target_id: pair[1].id.clone(),
            relation: ContinuityTemporalRelation::Before,
            evidence_class: ContinuityEvidenceClass::DocumentOrder,
            evidence_ids: pair[1].boundary_receipt_ids.clone(),
            cue: None,
            confidence_millis: 700,
            status: ContinuityStatus::Candidate,
            no_topology_commit: true,
        });
    }
}

fn semantic_state_intervals(
    semantic: Option<&DocumentSemanticSummary>,
    events: &EventBuild,
) -> Vec<ContinuityStateIntervalCandidate> {
    semantic
        .into_iter()
        .flat_map(|summary| &summary.documents)
        .flat_map(|document| &document.state_intervals)
        .filter_map(|row| {
            let start_event_id = events
                .situation_to_event
                .get(row.start_situation_id.as_str())?
                .clone();
            let end_event_id = row
                .end_situation_id
                .as_ref()
                .and_then(|id| events.situation_to_event.get(id.as_str()).cloned());
            Some(ContinuityStateIntervalCandidate {
                id: format_compact!("continuity:state:{}", row.id),
                note_id: row.note_id.clone().into(),
                subject_key: row.subject_key.clone().into(),
                state_key: row.state_key.clone().into(),
                value: row.value.clone().map(CompactString::from),
                polarity: row.polarity.clone().into(),
                start_event_id,
                end_event_id,
                source_start: clamp_u32(row.start),
                source_end: row.end.map(clamp_u32),
                persists: row.persists,
                confidence_millis: row.confidence_millis,
                status: if row.failure_reasons.is_empty() {
                    ContinuityStatus::Candidate
                } else {
                    ContinuityStatus::ReviewRequired
                },
                no_topology_commit: true,
            })
        })
        .collect()
}

fn semantic_causal(
    semantic: Option<&DocumentSemanticSummary>,
    events: &EventBuild,
) -> Vec<ContinuityCausalCandidate> {
    let mut out = Vec::new();
    for document in semantic.into_iter().flat_map(|summary| &summary.documents) {
        let situation_by_proposition = document
            .situations
            .iter()
            .map(|row| (row.proposition_id.as_str(), row.id.as_str()))
            .collect::<HashMap<_, _>>();
        let mut note_events = events
            .events
            .iter()
            .filter(|event| event.note_id.as_str() == document.note_id)
            .collect::<Vec<_>>();
        note_events.sort_by_key(|event| (event.source_start, event.source_end));
        let event_by_id = note_events
            .iter()
            .map(|event| (event.id.as_str(), *event))
            .collect::<HashMap<_, _>>();
        let previous_by_id = note_events
            .windows(2)
            .map(|pair| (pair[1].id.as_str(), pair[0]))
            .collect::<HashMap<_, _>>();
        for proposition in &document.propositions {
            let Some((relation, cue)) = causal_relation(&proposition.preview) else {
                continue;
            };
            let Some(situation_id) = situation_by_proposition.get(proposition.id.as_str()) else {
                continue;
            };
            let Some(target_id) = events.situation_to_event.get(*situation_id) else {
                continue;
            };
            let Some(target) = event_by_id.get(target_id.as_str()).copied() else {
                continue;
            };
            let Some(source) = previous_by_id.get(target.id.as_str()).copied() else {
                continue;
            };
            let temporal_legal = source.source_start <= target.source_start;
            let asserted = proposition.factuality.asserted
                && !proposition.factuality.hypothetical
                && !proposition.factuality.questioned;
            out.push(ContinuityCausalCandidate {
                id: format_compact!(
                    "continuity:causal:{}:{:?}:{}",
                    source.id,
                    relation,
                    target.id
                ),
                source_event_id: source.id.clone(),
                target_event_id: target.id.clone(),
                relation,
                evidence_class: ContinuityEvidenceClass::ExplicitCue,
                evidence_ids: vec![proposition.id.clone().into()],
                cue: Some(cue.into()),
                polarity: proposition.factuality.polarity.clone().into(),
                modality: proposition
                    .factuality
                    .modality
                    .clone()
                    .unwrap_or_else(|| "asserted".to_owned())
                    .into(),
                attribution_entity_id: proposition
                    .attribution_frame
                    .as_ref()
                    .and_then(|frame| frame.source_entity_id.clone())
                    .map(CompactString::from),
                temporal_legal,
                confidence_millis: proposition.confidence_millis,
                status: if temporal_legal && asserted {
                    ContinuityStatus::Candidate
                } else {
                    ContinuityStatus::ReviewRequired
                },
                no_topology_commit: true,
            });
        }
    }
    out
}

fn append_legacy_causal(
    snapshot: &GraphRebuildSnapshot,
    events: &EventBuild,
    out: &mut Vec<ContinuityCausalCandidate>,
) {
    let mut pairs = out
        .iter()
        .map(|row| (row.source_event_id.clone(), row.target_event_id.clone()))
        .collect::<HashSet<_>>();
    for row in &snapshot.causal_edges {
        let Some(source_id) = events.legacy_to_event.get(&row.source_id) else {
            continue;
        };
        let Some(target_id) = events.legacy_to_event.get(&row.target_id) else {
            continue;
        };
        if !pairs.insert((source_id.clone(), target_id.clone())) {
            continue;
        }
        out.push(ContinuityCausalCandidate {
            id: format_compact!("continuity:causal:legacy:{}:{}", source_id, target_id),
            source_event_id: source_id.clone(),
            target_event_id: target_id.clone(),
            relation: ContinuityCausalRelation::Explanation,
            evidence_class: ContinuityEvidenceClass::LegacyAdjacency,
            evidence_ids: row.evidence_ids.clone(),
            cue: None,
            polarity: "unknown".into(),
            modality: "unknown".into(),
            attribution_entity_id: None,
            temporal_legal: true,
            confidence_millis: confidence_millis(row.confidence),
            status: ContinuityStatus::ReviewRequired,
            no_topology_commit: true,
        });
    }
}

fn semantic_conflicts(
    semantic: Option<&DocumentSemanticSummary>,
    events: &EventBuild,
) -> Vec<ContinuityConflictCandidate> {
    semantic
        .into_iter()
        .flat_map(|summary| &summary.documents)
        .flat_map(|document| &document.temporal_conflicts)
        .map(|row| ContinuityConflictCandidate {
            id: format_compact!("continuity:conflict:{}", row.id),
            note_id: row.note_id.clone().into(),
            kind: row.kind.clone().into(),
            row_ids: row
                .situation_ids
                .iter()
                .filter_map(|id| events.situation_to_event.get(id.as_str()).cloned())
                .collect(),
            evidence_ids: row
                .state_interval_ids
                .iter()
                .map(CompactString::from)
                .collect(),
            severity: row.severity.clone().into(),
            confidence_millis: row.confidence_millis,
            status: ContinuityStatus::ReviewRequired,
            no_topology_commit: true,
        })
        .collect()
}

fn episode_connections(
    episodes: &[StoryEpisodeCandidate],
    event_episode: &HashMap<CompactString, CompactString>,
    temporal: &[ContinuityTemporalCandidate],
    states: &[ContinuityStateIntervalCandidate],
    bridges: &[ChunkSemanticBridgeCandidate],
) -> Vec<EpisodeContinuityCandidate> {
    let mut out = Vec::new();
    let mut seen = HashSet::new();
    for pair in episodes.windows(2) {
        if pair[0].note_id != pair[1].note_id {
            continue;
        }
        push_episode_connection(
            &mut out,
            &mut seen,
            &pair[0].id,
            &pair[1].id,
            EpisodeContinuityKind::Continuation,
            ContinuityEvidenceClass::DocumentOrder,
            pair[1].boundary_receipt_ids.clone(),
            shared_entities(&pair[0].entity_ids, &pair[1].entity_ids),
            vec!["adjacent_source_episodes".into()],
            700,
        );
    }
    for row in temporal {
        let Some(source_episode) = event_episode.get(&row.source_id) else {
            continue;
        };
        let Some(target_episode) = event_episode.get(&row.target_id) else {
            continue;
        };
        if source_episode == target_episode {
            continue;
        }
        let kind = match row.relation {
            ContinuityTemporalRelation::RecursAfter => EpisodeContinuityKind::Recurrence,
            ContinuityTemporalRelation::Overlaps => EpisodeContinuityKind::ParallelAction,
            ContinuityTemporalRelation::After => EpisodeContinuityKind::Flashback,
            _ => continue,
        };
        push_episode_connection(
            &mut out,
            &mut seen,
            source_episode,
            target_episode,
            kind,
            row.evidence_class,
            row.evidence_ids.clone(),
            Vec::new(),
            vec![format_compact!("temporal_relation:{:?}", row.relation)],
            row.confidence_millis,
        );
    }
    for state in states.iter().filter(|state| state.end_event_id.is_some()) {
        let Some(source_episode) = event_episode.get(&state.start_event_id) else {
            continue;
        };
        let Some(target_episode) = state
            .end_event_id
            .as_ref()
            .and_then(|id| event_episode.get(id))
        else {
            continue;
        };
        if source_episode != target_episode {
            push_episode_connection(
                &mut out,
                &mut seen,
                source_episode,
                target_episode,
                EpisodeContinuityKind::StateTransition,
                ContinuityEvidenceClass::StateTransition,
                vec![state.id.clone()],
                Vec::new(),
                vec![format_compact!("state_key:{}", state.state_key)],
                state.confidence_millis,
            );
        }
    }
    let episode_by_chunk = episodes
        .iter()
        .flat_map(|episode| {
            episode
                .chunk_ids
                .iter()
                .map(move |chunk_id| (chunk_id.as_str(), episode))
        })
        .collect::<HashMap<_, _>>();
    for bridge in bridges {
        let Some(source) = episode_by_chunk.get(bridge.source_chunk_id.as_str()) else {
            continue;
        };
        let Some(target) = episode_by_chunk.get(bridge.target_chunk_id.as_str()) else {
            continue;
        };
        if source.id == target.id {
            continue;
        }
        let kind = bridge_episode_kind(bridge.bridge_type, source.note_id != target.note_id);
        push_episode_connection(
            &mut out,
            &mut seen,
            &source.id,
            &target.id,
            kind,
            ContinuityEvidenceClass::SemanticBridge,
            bridge.evidence_ids.clone(),
            bridge.supporting_entity_ids.iter().cloned().collect(),
            bridge.rationale.clone(),
            confidence_millis(bridge.confidence),
        );
    }
    out.sort_by(|left, right| left.id.cmp(&right.id));
    out
}

#[allow(clippy::too_many_arguments)]
fn push_episode_connection(
    out: &mut Vec<EpisodeContinuityCandidate>,
    seen: &mut HashSet<CompactString>,
    source: &CompactString,
    target: &CompactString,
    kind: EpisodeContinuityKind,
    evidence_class: ContinuityEvidenceClass,
    evidence_ids: Vec<CompactString>,
    supporting_entity_ids: Vec<CompactString>,
    rationale: Vec<CompactString>,
    confidence_millis: u16,
) {
    let id = format_compact!("continuity:episode:{}:{:?}:{}", source, kind, target);
    if !seen.insert(id.clone()) {
        return;
    }
    out.push(EpisodeContinuityCandidate {
        id,
        source_episode_id: source.clone(),
        target_episode_id: target.clone(),
        kind,
        evidence_class,
        evidence_ids,
        supporting_entity_ids,
        rationale,
        confidence_millis,
        status: ContinuityStatus::Candidate,
        no_topology_commit: true,
    });
}

fn temporal_relation(value: &str) -> ContinuityTemporalRelation {
    let value = value.to_ascii_lowercase();
    if value.contains("recur") {
        ContinuityTemporalRelation::RecursAfter
    } else if value.contains("overlap") || value.contains("simult") {
        ContinuityTemporalRelation::Overlaps
    } else if value.contains("during") {
        ContinuityTemporalRelation::During
    } else if value.contains("contain") {
        ContinuityTemporalRelation::Contains
    } else if value.contains("start") {
        ContinuityTemporalRelation::Starts
    } else if value.contains("finish") || value.contains("end") {
        ContinuityTemporalRelation::Finishes
    } else if value.contains("supersed") {
        ContinuityTemporalRelation::Supersedes
    } else if value.contains("after") {
        ContinuityTemporalRelation::After
    } else {
        ContinuityTemporalRelation::Before
    }
}

fn causal_relation(preview: &str) -> Option<(ContinuityCausalRelation, &'static str)> {
    let lower = preview.to_ascii_lowercase();
    [
        ("as a result", ContinuityCausalRelation::Consequence),
        ("therefore", ContinuityCausalRelation::Consequence),
        ("thus", ContinuityCausalRelation::Consequence),
        ("in order to", ContinuityCausalRelation::Motivation),
        ("so that", ContinuityCausalRelation::Motivation),
        ("prevented", ContinuityCausalRelation::Prevention),
        ("stopped", ContinuityCausalRelation::Prevention),
        ("blocked", ContinuityCausalRelation::Prevention),
        ("enabled", ContinuityCausalRelation::EnablingCondition),
        ("allowed", ContinuityCausalRelation::EnablingCondition),
        ("because", ContinuityCausalRelation::DirectCause),
        ("due to", ContinuityCausalRelation::DirectCause),
        ("which meant", ContinuityCausalRelation::Explanation),
        ("that meant", ContinuityCausalRelation::Explanation),
    ]
    .into_iter()
    .find_map(|(cue, relation)| lower.contains(cue).then_some((relation, cue)))
}

fn bridge_episode_kind(
    kind: ChunkSemanticBridgeType,
    cross_document: bool,
) -> EpisodeContinuityKind {
    if cross_document {
        return EpisodeContinuityKind::CrossDocumentContinuation;
    }
    match kind {
        ChunkSemanticBridgeType::SetupPayoff => EpisodeContinuityKind::SetupPayoff,
        ChunkSemanticBridgeType::MotifEcho => EpisodeContinuityKind::MotifEcho,
        ChunkSemanticBridgeType::EvidenceReframe => EpisodeContinuityKind::EvidenceReframe,
        ChunkSemanticBridgeType::StateDelta | ChunkSemanticBridgeType::RelationshipDelta => {
            EpisodeContinuityKind::StateTransition
        }
        _ => EpisodeContinuityKind::Continuation,
    }
}

fn shared_entities(left: &[CompactString], right: &[CompactString]) -> Vec<CompactString> {
    left.iter()
        .filter(|value| right.contains(value))
        .cloned()
        .collect()
}

fn confidence_millis(value: f32) -> u16 {
    (value.clamp(0.0, 1.0) * 1000.0).round() as u16
}

fn clamp_u32(value: usize) -> u32 {
    value.min(u32::MAX as usize) as u32
}
