use std::collections::BTreeSet;

use phoenix_graph_kernel::{
    GraphTruthCommit, GraphTruthLineage, KernelBiTemporal, KernelEdge, KernelEdgeType,
    KernelGraphLayer, KernelMutationBatch, KernelMutationScope, KernelProvenance,
    KernelRelationClass, KernelVertex, KernelVertexClass, KernelVertexId,
};
use phoenix_store_native_core::PhoenixGraphKernelStoreV2;
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{
    GraphTruthCommitHeader, GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthDigest,
    GraphTruthKind, GraphTruthOperation, GraphTruthSourceGenerationRef, NativeDecisionReceipt,
};
use serde_json::json;

use super::{
    CanonicalEpisodeAssignmentCommitRequest, CanonicalEpisodeAssignmentError,
    NativeEpisodeAssignmentEpisode, EPISODE_ASSIGNMENT_POLICY, EPISODE_EDGE_TYPE,
};

pub(super) fn build_commit(
    store: &PhoenixOvergraphStore,
    lineage: &GraphTruthLineage,
    request: &CanonicalEpisodeAssignmentCommitRequest,
    selected: &NativeEpisodeAssignmentEpisode,
    decision: &NativeDecisionReceipt,
    operator_receipt_id: &str,
    commit_id: &str,
) -> Result<GraphTruthCommit, CanonicalEpisodeAssignmentError> {
    let generation = store.kernel_current_generation()?.checked_add(1).ok_or(
        CanonicalEpisodeAssignmentError::Invalid("graph truth generation overflow"),
    )?;
    let mut vertices = Vec::with_capacity(2);
    if lineage.active_vertex_commit(&request.event.id).is_none() {
        vertices.push(event_vertex(request));
    }
    if lineage.active_vertex_commit(&selected.id).is_none() {
        vertices.push(episode_vertex(request, selected));
    }
    let edge = KernelEdge {
        source_id: KernelVertexId(selected.id.clone()),
        target_id: KernelVertexId(request.event.id.clone()),
        edge_type: KernelEdgeType(EPISODE_EDGE_TYPE.to_owned()),
        relation_class: KernelRelationClass::Narrative,
        weight: 1_000,
        attributes: json!({
            "decisionReceiptId": decision.receipt_id,
            "candidateSetId": decision.candidate_set_id,
            "authority": "operator_preference"
        }),
        data: None,
        document_id: Some(request.event.note_id.clone()),
        note_id: Some(request.event.note_id.clone()),
        layer: KernelGraphLayer::Asserted,
        temporal: KernelBiTemporal {
            recorded_at: Some(request.decided_at),
            ..KernelBiTemporal::default()
        },
        provenance: KernelProvenance {
            resolver: Some(EPISODE_ASSIGNMENT_POLICY.to_owned()),
            source: Some(request.source_snapshot_id.clone()),
            confidence: Some(selected.confidence_millis as f64 / 1_000.0),
            evidence_refs: canonical_evidence_ids(request, selected),
        },
        ..KernelEdge::default()
    };
    let digest = blake3::hash(
        format!(
            "phoenix-canonical-episode-assignment-idempotency/v1\0{}\0{}",
            decision.receipt_id, decision.candidate_set_id
        )
        .as_bytes(),
    );
    Ok(GraphTruthCommit {
        header: GraphTruthCommitHeader {
            commit_id: commit_id.into(),
            generation,
            operation: GraphTruthOperation::Assert,
            truth: GraphTruthDescriptor {
                kind: GraphTruthKind::Structural,
                plane: None,
            },
            source_generations: vec![GraphTruthSourceGenerationRef {
                source_id: request.source_snapshot_id.as_str().into(),
                generation: request.source_snapshot_built_at as u64,
            }]
            .into(),
            receipt_ids: vec![decision.receipt_id.clone(), operator_receipt_id.into()].into(),
            compiler_policy: GraphTruthCompilerPolicy {
                compiler_id: "phoenix-api".into(),
                compiler_version: "1".into(),
                policy_id: EPISODE_ASSIGNMENT_POLICY.into(),
                policy_version: "1".into(),
            },
            idempotency_hash: GraphTruthDigest(*digest.as_bytes()),
            committed_at: request.decided_at,
            ..GraphTruthCommitHeader::default()
        },
        batch: KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Document {
                document_id: request.event.note_id.clone(),
            },
            recorded_at: Some(request.decided_at),
            vertices,
            edges: vec![edge],
        },
    })
}

pub(super) fn reject_conflicting_membership(
    lineage: &GraphTruthLineage,
    selected_episode_id: &str,
    event_id: &str,
) -> Result<(), CanonicalEpisodeAssignmentError> {
    for commit in lineage.commits() {
        for edge in &commit.batch.edges {
            if edge.edge_type.0 == EPISODE_EDGE_TYPE
                && edge.target_id.0 == event_id
                && edge.source_id.0 != selected_episode_id
                && lineage
                    .active_edge_commit(&edge.source_id.0, event_id, EPISODE_EDGE_TYPE)
                    .is_some()
            {
                return Err(CanonicalEpisodeAssignmentError::Invalid(
                    "event already has a different canonical episode",
                ));
            }
        }
    }
    Ok(())
}

fn event_vertex(request: &CanonicalEpisodeAssignmentCommitRequest) -> KernelVertex {
    let event = &request.event;
    KernelVertex {
        id: KernelVertexId(event.id.clone()),
        kind: "canonical_event".to_owned(),
        class: KernelVertexClass::Event,
        labels: vec![event.predicate.clone()],
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
            recorded_at: Some(request.decided_at),
            ..KernelBiTemporal::default()
        },
        provenance: KernelProvenance {
            resolver: Some(EPISODE_ASSIGNMENT_POLICY.to_owned()),
            source: Some(request.source_snapshot_id.clone()),
            confidence: Some(event.confidence_millis as f64 / 1_000.0),
            evidence_refs: event.evidence_ids.clone(),
        },
        search_chunk_id: Some(event.chunk_id.clone()),
        document_id: Some(event.note_id.clone()),
        note_id: Some(event.note_id.clone()),
        ..KernelVertex::default()
    }
}

fn episode_vertex(
    request: &CanonicalEpisodeAssignmentCommitRequest,
    episode: &NativeEpisodeAssignmentEpisode,
) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(episode.id.clone()),
        kind: "canonical_episode".to_owned(),
        class: KernelVertexClass::Episode,
        labels: vec![episode.label.clone()],
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
            recorded_at: Some(request.decided_at),
            ..KernelBiTemporal::default()
        },
        provenance: KernelProvenance {
            resolver: Some(EPISODE_ASSIGNMENT_POLICY.to_owned()),
            source: Some(request.source_snapshot_id.clone()),
            confidence: Some(episode.confidence_millis as f64 / 1_000.0),
            evidence_refs: episode.boundary_receipt_ids.clone(),
        },
        document_id: Some(episode.note_id.clone()),
        note_id: Some(episode.note_id.clone()),
        ..KernelVertex::default()
    }
}

fn canonical_evidence_ids(
    request: &CanonicalEpisodeAssignmentCommitRequest,
    selected: &NativeEpisodeAssignmentEpisode,
) -> Vec<String> {
    request
        .event
        .evidence_ids
        .iter()
        .chain(selected.boundary_receipt_ids.iter())
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}
