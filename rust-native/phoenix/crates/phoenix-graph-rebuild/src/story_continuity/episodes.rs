use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};

use crate::{GraphChunk, GraphRebuildSnapshot};

use super::types::{
    ContinuityBoundarySignal, ContinuityEventIdentity, ContinuityStatus, EpisodeBoundaryDecision,
    EpisodeBoundaryReceipt, StoryContinuityDocument, StoryEpisodeCandidate,
};

pub(super) struct EpisodeBuild {
    pub boundary_receipts: Vec<EpisodeBoundaryReceipt>,
    pub episodes: Vec<StoryEpisodeCandidate>,
    pub event_episode: HashMap<CompactString, CompactString>,
}

pub(super) fn build_episodes(
    snapshot: &GraphRebuildSnapshot,
    documents: &[StoryContinuityDocument],
    events: &[ContinuityEventIdentity],
) -> EpisodeBuild {
    let document_text = documents
        .iter()
        .map(|document| (document.note_id.as_str(), document.text.as_str()))
        .collect::<HashMap<_, _>>();
    let location_ids = snapshot
        .nodes
        .iter()
        .filter(|node| {
            let kind = node.kind.to_ascii_lowercase();
            kind.contains("location") || kind.contains("place") || kind.contains("setting")
        })
        .map(|node| node.entity_id.0.as_str())
        .collect::<HashSet<_>>();
    let mut boundary_receipts = Vec::new();
    let mut episodes = Vec::new();
    let mut event_episode = HashMap::new();

    for note_id in &snapshot.note_ids {
        let mut chunks = snapshot
            .chunks
            .iter()
            .filter(|chunk| chunk.note_id == *note_id)
            .collect::<Vec<_>>();
        chunks.sort_by_key(|chunk| (chunk.ordinal, chunk.start, chunk.end));
        if chunks.is_empty() {
            continue;
        }
        let text = document_text
            .get(note_id.as_str())
            .copied()
            .unwrap_or_default();
        let boundaries = episode_boundaries(snapshot, &chunks, text, &location_ids);
        for (episode_ordinal, boundary) in boundaries.iter().enumerate() {
            let source_end = boundaries.get(episode_ordinal + 1).map_or_else(
                || chunks.last().expect("non-empty chunks").end,
                |row| row.source_offset,
            );
            let group = chunks
                .iter()
                .copied()
                .filter(|chunk| chunk.start < source_end && boundary.source_offset < chunk.end)
                .collect::<Vec<_>>();
            let Some(start_chunk) = group.first().copied() else {
                continue;
            };
            let episode_events = events
                .iter()
                .filter(|event| {
                    event.note_id == *note_id
                        && event.source_start >= boundary.source_offset
                        && event.source_start < source_end
                })
                .collect::<Vec<_>>();
            let id = episode_id(note_id, boundary.source_offset, start_chunk.id.as_str());
            let receipt_id =
                format_compact!("continuity:boundary:{}:{}", note_id, boundary.source_offset);
            boundary_receipts.push(EpisodeBoundaryReceipt {
                id: receipt_id.clone(),
                note_id: note_id.clone(),
                before_chunk_id: chunks
                    .iter()
                    .rev()
                    .find(|chunk| chunk.end <= boundary.source_offset)
                    .map(|chunk| chunk.id.clone()),
                after_chunk_id: start_chunk.id.clone(),
                source_offset: boundary.source_offset,
                decision: boundary.decision,
                signals: boundary.signals.clone(),
                confidence_millis: boundary.confidence_millis,
                status: ContinuityStatus::Candidate,
                no_topology_commit: true,
            });
            let entity_ids = sorted_unique(
                episode_events
                    .iter()
                    .flat_map(|event| event.participant_entity_ids.iter().cloned())
                    .collect(),
            );
            let event_ids = episode_events
                .iter()
                .map(|event| {
                    event_episode.insert(event.id.clone(), id.clone());
                    event.id.clone()
                })
                .collect();
            episodes.push(StoryEpisodeCandidate {
                id,
                note_id: note_id.clone(),
                label: episode_label(text, boundary.source_offset, source_end, episode_ordinal),
                source_start: boundary.source_offset,
                source_end,
                chunk_ids: group.iter().map(|chunk| chunk.id.clone()).collect(),
                event_ids,
                entity_ids,
                boundary_receipt_ids: vec![receipt_id],
                confidence_millis: boundary.confidence_millis,
                status: ContinuityStatus::Candidate,
                no_topology_commit: true,
            });
        }
    }
    EpisodeBuild {
        boundary_receipts,
        episodes,
        event_episode,
    }
}

#[derive(Clone)]
struct Boundary {
    source_offset: u32,
    decision: EpisodeBoundaryDecision,
    signals: Vec<ContinuityBoundarySignal>,
    confidence_millis: u16,
}

fn episode_boundaries(
    snapshot: &GraphRebuildSnapshot,
    chunks: &[&GraphChunk],
    text: &str,
    location_ids: &HashSet<&str>,
) -> Vec<Boundary> {
    let mut out = vec![Boundary {
        source_offset: 0,
        decision: EpisodeBoundaryDecision::DocumentStart,
        signals: vec![signal(
            "document_start",
            "first source span",
            &[chunks[0].id.clone()],
        )],
        confidence_millis: 1000,
    }];
    for (source_offset, heading) in source_headings(text) {
        if source_offset == 0 {
            out[0].signals.push(signal(
                "heading",
                heading,
                &boundary_chunk_evidence(chunks, source_offset),
            ));
            continue;
        }
        out.push(Boundary {
            source_offset,
            decision: EpisodeBoundaryDecision::Heading,
            signals: vec![signal(
                "heading",
                heading,
                &boundary_chunk_evidence(chunks, source_offset),
            )],
            confidence_millis: 980,
        });
    }
    for source_offset in source_scene_breaks(text) {
        if source_offset == 0 {
            continue;
        }
        out.push(Boundary {
            source_offset,
            decision: EpisodeBoundaryDecision::SceneBreak,
            signals: vec![signal(
                "scene_break",
                "explicit scene separator",
                &boundary_chunk_evidence(chunks, source_offset),
            )],
            confidence_millis: 960,
        });
    }
    for index in 1..chunks.len() {
        let previous = chunks[index - 1];
        let current = chunks[index];
        let preview = source_slice(text, current.start, current.end.min(current.start + 420));
        let mut signals = Vec::new();
        let temporal_jump = temporal_jump(preview);
        if let Some(value) = temporal_jump {
            signals.push(signal(
                "temporal_jump",
                value,
                std::slice::from_ref(&current.id),
            ));
        }
        let previous_entities = chunk_entities(snapshot, previous);
        let current_entities = chunk_entities(snapshot, current);
        let participant_shift = !previous_entities.is_empty()
            && !current_entities.is_empty()
            && previous_entities.is_disjoint(&current_entities);
        if participant_shift {
            signals.push(signal(
                "participant_shift",
                "adjacent spans have disjoint entity support",
                &[previous.id.clone(), current.id.clone()],
            ));
        }
        let previous_locations = previous_entities
            .iter()
            .filter(|entity| location_ids.contains(entity.as_str()))
            .collect::<HashSet<_>>();
        let current_locations = current_entities
            .iter()
            .filter(|entity| location_ids.contains(entity.as_str()))
            .collect::<HashSet<_>>();
        let location_shift = !previous_locations.is_empty()
            && !current_locations.is_empty()
            && previous_locations.is_disjoint(&current_locations);
        if location_shift {
            signals.push(signal(
                "location_shift",
                "adjacent spans have disjoint location support",
                &[previous.id.clone(), current.id.clone()],
            ));
        }
        let discourse_shift = previous.source != current.source;
        if discourse_shift {
            signals.push(signal(
                "discourse_shift",
                format_compact!("{} -> {}", previous.source, current.source),
                &[previous.id.clone(), current.id.clone()],
            ));
        }

        let decision = if temporal_jump.is_some() && (participant_shift || location_shift)
            || location_shift && participant_shift
            || discourse_shift && participant_shift && temporal_jump.is_some()
        {
            Some((EpisodeBoundaryDecision::CompositeTransition, 800))
        } else {
            None
        };
        if let Some((decision, confidence_millis)) = decision {
            out.push(Boundary {
                source_offset: current.start,
                decision,
                signals,
                confidence_millis,
            });
        }
    }
    out.sort_by_key(|boundary| boundary.source_offset);
    out.dedup_by(|left, right| {
        if left.source_offset != right.source_offset {
            return false;
        }
        if right.confidence_millis > left.confidence_millis {
            *left = right.clone();
        } else {
            left.signals.extend(right.signals.clone());
        }
        true
    });
    out
}

fn boundary_chunk_evidence(chunks: &[&GraphChunk], source_offset: u32) -> Vec<CompactString> {
    let chunk = chunks
        .iter()
        .find(|chunk| chunk.start <= source_offset && source_offset < chunk.end)
        .or_else(|| chunks.iter().find(|chunk| chunk.start >= source_offset));
    chunk.map_or_else(Vec::new, |chunk| vec![chunk.id.clone()])
}

fn source_headings(text: &str) -> Vec<(u32, CompactString)> {
    text.split_inclusive('\n')
        .scan(0_usize, |byte_offset, line| {
            let start = *byte_offset;
            *byte_offset += line.len();
            Some((start, line.trim()))
        })
        .filter(|(_, line)| {
            let lower = line.to_ascii_lowercase();
            line.starts_with('#')
                || lower.starts_with("chapter ")
                || lower.starts_with("scene ")
                || lower.starts_with("part ")
                || lower.starts_with("book ")
        })
        .map(|(byte_offset, line)| {
            (
                byte_offset.min(u32::MAX as usize) as u32,
                line.chars().take(120).collect::<String>().into(),
            )
        })
        .collect()
}

fn source_scene_breaks(text: &str) -> Vec<u32> {
    text.split_inclusive('\n')
        .scan(0_usize, |byte_offset, line| {
            let start = *byte_offset;
            *byte_offset += line.len();
            Some((start, line.trim()))
        })
        .filter(|(_, line)| matches!(*line, "***" | "---" | "###"))
        .map(|(byte_offset, _)| byte_offset.min(u32::MAX as usize) as u32)
        .collect()
}

fn chunk_entities(snapshot: &GraphRebuildSnapshot, chunk: &GraphChunk) -> HashSet<CompactString> {
    snapshot
        .entity_anchors
        .iter()
        .filter(|anchor| anchor.chunk_id.as_ref() == Some(&chunk.id))
        .map(|anchor| CompactString::from(anchor.entity_id.0.as_str()))
        .collect()
}

fn heading_text(preview: &str) -> Option<String> {
    let first = preview.lines().find(|line| !line.trim().is_empty())?.trim();
    let lower = first.to_ascii_lowercase();
    if first.starts_with('#')
        || lower.starts_with("chapter ")
        || lower.starts_with("scene ")
        || lower.starts_with("part ")
        || lower.starts_with("book ")
    {
        Some(first.chars().take(120).collect())
    } else {
        None
    }
}

fn temporal_jump(preview: &str) -> Option<&'static str> {
    let lower = preview.to_ascii_lowercase();
    [
        "meanwhile",
        "later",
        "the next day",
        "the following",
        "years earlier",
        "months earlier",
        "hours earlier",
        "afterward",
        "that night",
        "the next morning",
        "before dawn",
    ]
    .into_iter()
    .find(|cue| lower.contains(cue))
}

fn episode_label(text: &str, start: u32, end: u32, ordinal: usize) -> CompactString {
    let preview = source_slice(text, start, end.min(start + 420));
    heading_text(preview)
        .map(CompactString::from)
        .unwrap_or_else(|| format_compact!("Episode {}", ordinal + 1))
}

fn source_slice(text: &str, start: u32, end: u32) -> &str {
    let mut start = (start as usize).min(text.len());
    while start > 0 && !text.is_char_boundary(start) {
        start -= 1;
    }
    let mut end = (end as usize).max(start).min(text.len());
    while end > start && !text.is_char_boundary(end) {
        end -= 1;
    }
    text.get(start..end).unwrap_or_default()
}

fn signal(
    kind: &str,
    detail: impl Into<CompactString>,
    evidence_ids: &[CompactString],
) -> ContinuityBoundarySignal {
    ContinuityBoundarySignal {
        kind: kind.into(),
        detail: detail.into(),
        evidence_ids: evidence_ids.to_vec(),
    }
}

fn episode_id(note_id: &str, start: u32, chunk_id: &str) -> CompactString {
    let mut hash = 2_166_136_261_u32;
    for byte in chunk_id.as_bytes() {
        hash ^= u32::from(*byte);
        hash = hash.wrapping_mul(16_777_619);
    }
    format_compact!("continuity:episode:{note_id}:{start}:{hash:08x}")
}

fn sorted_unique(mut values: Vec<CompactString>) -> Vec<CompactString> {
    values.sort();
    values.dedup();
    values
}
