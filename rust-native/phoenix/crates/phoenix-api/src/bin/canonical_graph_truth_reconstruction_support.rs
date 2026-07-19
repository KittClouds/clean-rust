use std::collections::BTreeSet;

use phoenix_graph_kernel::{
    KernelBiTemporal, KernelEdge, KernelEdgeType, KernelGraphLayer, KernelProvenance,
    KernelRelationClass, KernelVertex, KernelVertexClass, KernelVertexId,
};
use phoenix_graph_rebuild::{ContinuityEventIdentity, StoryEpisodeCandidate};
use phoenix_types::NativeDecisionReceipt;
use serde_json::json;

use super::EPISODE_ASSIGNMENT_POLICY;

const EPISODE_EDGE_TYPE: &str = "episode_contains_event";

pub(super) fn event_vertex(
    event: &ContinuityEventIdentity,
    source: &str,
    recorded_at: i64,
) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(event.id.to_string()),
        kind: "canonical_event".to_owned(),
        class: KernelVertexClass::Event,
        labels: vec![event.predicate.to_string()],
        weight: event.confidence_millis as i64,
        value: json!({
            "predicate": event.predicate,
            "factuality": event.factuality,
            "sourceStart": event.source_start,
            "sourceEnd": event.source_end,
            "participantEntityIds": event.participant_entity_ids
        }),
        attributes: json!({"sourceCandidateOnly": true, "acceptedByOperator": true}),
        temporal: KernelBiTemporal {
            recorded_at: Some(recorded_at),
            ..Default::default()
        },
        provenance: KernelProvenance {
            resolver: Some(EPISODE_ASSIGNMENT_POLICY.to_owned()),
            source: Some(source.to_owned()),
            confidence: Some(event.confidence_millis as f64 / 1_000.0),
            evidence_refs: event.evidence_ids.iter().map(ToString::to_string).collect(),
        },
        search_chunk_id: Some(event.chunk_id.to_string()),
        document_id: Some(event.note_id.to_string()),
        note_id: Some(event.note_id.to_string()),
        ..Default::default()
    }
}

pub(super) fn episode_vertex(
    episode: &StoryEpisodeCandidate,
    source: &str,
    recorded_at: i64,
) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(episode.id.to_string()),
        kind: "canonical_episode".to_owned(),
        class: KernelVertexClass::Episode,
        labels: vec![episode.label.to_string()],
        weight: episode.confidence_millis as i64,
        value: json!({
            "label": episode.label,
            "sourceStart": episode.source_start,
            "sourceEnd": episode.source_end,
            "chunkIds": episode.chunk_ids,
            "entityIds": episode.entity_ids
        }),
        attributes: json!({"sourceCandidateOnly": true, "acceptedByOperator": true}),
        temporal: KernelBiTemporal {
            recorded_at: Some(recorded_at),
            ..Default::default()
        },
        provenance: KernelProvenance {
            resolver: Some(EPISODE_ASSIGNMENT_POLICY.to_owned()),
            source: Some(source.to_owned()),
            confidence: Some(episode.confidence_millis as f64 / 1_000.0),
            evidence_refs: episode
                .boundary_receipt_ids
                .iter()
                .map(ToString::to_string)
                .collect(),
        },
        document_id: Some(episode.note_id.to_string()),
        note_id: Some(episode.note_id.to_string()),
        ..Default::default()
    }
}

pub(super) fn episode_event_edge(
    event: &ContinuityEventIdentity,
    episode: &StoryEpisodeCandidate,
    decision: &NativeDecisionReceipt,
    source: &str,
    recorded_at: i64,
) -> KernelEdge {
    let mut evidence_refs = event
        .evidence_ids
        .iter()
        .chain(episode.boundary_receipt_ids.iter())
        .map(ToString::to_string)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    evidence_refs.shrink_to_fit();
    KernelEdge {
        source_id: KernelVertexId(episode.id.to_string()),
        target_id: KernelVertexId(event.id.to_string()),
        edge_type: KernelEdgeType(EPISODE_EDGE_TYPE.to_owned()),
        relation_class: KernelRelationClass::Narrative,
        weight: 1_000,
        attributes: json!({
            "decisionReceiptId": decision.receipt_id,
            "candidateSetId": decision.candidate_set_id,
            "authority": "operator_preference"
        }),
        data: None,
        document_id: Some(event.note_id.to_string()),
        note_id: Some(event.note_id.to_string()),
        layer: KernelGraphLayer::Asserted,
        temporal: KernelBiTemporal {
            recorded_at: Some(recorded_at),
            ..Default::default()
        },
        provenance: KernelProvenance {
            resolver: Some(EPISODE_ASSIGNMENT_POLICY.to_owned()),
            source: Some(source.to_owned()),
            confidence: Some(episode.confidence_millis as f64 / 1_000.0),
            evidence_refs,
        },
        ..Default::default()
    }
}
