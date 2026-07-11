mod episodes;
mod events;
mod relations;
mod types;

#[cfg(test)]
mod tests;

use std::time::Instant;

use compact_str::CompactString;

use crate::{ChunkSemanticBridgeCandidate, DocumentSemanticSummary, GraphRebuildSnapshot};
use episodes::build_episodes;
use events::canonical_events;
use relations::build_relations;

pub use types::*;

pub struct StoryContinuityInput<'a> {
    pub snapshot: &'a GraphRebuildSnapshot,
    pub documents: &'a [StoryContinuityDocument],
    pub semantic_summary: Option<&'a DocumentSemanticSummary>,
    pub bridge_candidates: &'a [ChunkSemanticBridgeCandidate],
}

pub fn build_story_continuity_contract(input: StoryContinuityInput<'_>) -> StoryContinuityContract {
    let started = Instant::now();
    let event_started = Instant::now();
    let event_build = canonical_events(input.snapshot, input.semantic_summary);
    let event_identity_micros = elapsed_micros(event_started);
    let episode_started = Instant::now();
    let episode_build = build_episodes(input.snapshot, input.documents, &event_build.events);
    let episode_boundary_micros = elapsed_micros(episode_started);
    let relation_started = Instant::now();
    let relation_build = build_relations(
        input.snapshot,
        input.semantic_summary,
        input.bridge_candidates,
        &event_build,
        &episode_build.episodes,
        &episode_build.event_episode,
    );
    let relation_resolution_micros = elapsed_micros(relation_started);
    let review_required = event_build
        .events
        .iter()
        .filter(|row| row.status == ContinuityStatus::ReviewRequired)
        .count()
        + relation_build
            .temporal
            .iter()
            .filter(|row| row.status == ContinuityStatus::ReviewRequired)
            .count()
        + relation_build
            .causal
            .iter()
            .filter(|row| row.status == ContinuityStatus::ReviewRequired)
            .count()
        + relation_build.conflicts.len();
    let cross_document_connections = relation_build
        .episode_connections
        .iter()
        .filter(|row| row.kind == EpisodeContinuityKind::CrossDocumentContinuation)
        .count();
    let counters = StoryContinuityCounters {
        events: event_build.events.len(),
        boundary_receipts: episode_build.boundary_receipts.len(),
        episodes: episode_build.episodes.len(),
        temporal_candidates: relation_build.temporal.len(),
        state_intervals: relation_build.state_intervals.len(),
        causal_candidates: relation_build.causal.len(),
        episode_connections: relation_build.episode_connections.len(),
        conflicts: relation_build.conflicts.len(),
        cross_document_connections,
        review_required,
    };
    let all_rows_evidenced = relation_build
        .temporal
        .iter()
        .all(|row| !row.evidence_ids.is_empty())
        && relation_build
            .causal
            .iter()
            .all(|row| !row.evidence_ids.is_empty())
        && relation_build
            .episode_connections
            .iter()
            .all(|row| !row.evidence_ids.is_empty());
    let certificate = StoryContinuityRunCertificate {
        schema_version: STORY_CONTINUITY_CERTIFICATE_SCHEMA_VERSION.into(),
        source_snapshot_id: input.snapshot.id.clone(),
        source_document_ids: input.snapshot.note_ids.clone(),
        build_micros: started.elapsed().as_micros().min(u128::from(u64::MAX)) as u64,
        event_identity_micros,
        episode_boundary_micros,
        relation_resolution_micros,
        counters,
        no_topology_writes: true,
        all_rows_evidenced,
        stable_source_identities: true,
        fixed_batching_detected: false,
        invariant_receipts: vec![
            STORY_CONTINUITY_NO_TOPOLOGY_COMMIT.into(),
            "continuity_event_identity:source_span_hash".into(),
            "episode_boundary:independent_signal_receipt".into(),
            "temporal_evidence_class:explicit".into(),
            "causal_temporal_legality:required".into(),
            "semantic_bridge:evidence_not_identity".into(),
        ],
    };
    StoryContinuityContract {
        schema_version: STORY_CONTINUITY_SCHEMA_VERSION.into(),
        source: "rust_story_continuity".into(),
        source_snapshot_id: input.snapshot.id.clone(),
        generated_at: input.snapshot.built_at,
        commit_policy: "candidate_only".into(),
        no_topology_commit: true,
        events: event_build.events,
        boundary_receipts: episode_build.boundary_receipts,
        episodes: episode_build.episodes,
        temporal_candidates: relation_build.temporal,
        state_intervals: relation_build.state_intervals,
        causal_candidates: relation_build.causal,
        episode_connections: relation_build.episode_connections,
        conflicts: relation_build.conflicts,
        certificate,
    }
}

fn elapsed_micros(started: Instant) -> u64 {
    started.elapsed().as_micros().min(u128::from(u64::MAX)) as u64
}

pub fn assert_story_continuity_candidate_only(
    contract: &StoryContinuityContract,
) -> Result<(), CompactString> {
    if !contract.no_topology_commit || !contract.certificate.no_topology_writes {
        return Err("story continuity topology mutation was enabled".into());
    }
    let mut violation = None;
    let mut inspect = |no_topology_commit: bool, id: &CompactString| {
        if !no_topology_commit && violation.is_none() {
            violation = Some(id.clone());
        }
    };
    for row in &contract.events {
        inspect(row.no_topology_commit, &row.id);
    }
    for row in &contract.boundary_receipts {
        inspect(row.no_topology_commit, &row.id);
    }
    for row in &contract.episodes {
        inspect(row.no_topology_commit, &row.id);
    }
    for row in &contract.temporal_candidates {
        inspect(row.no_topology_commit, &row.id);
    }
    for row in &contract.state_intervals {
        inspect(row.no_topology_commit, &row.id);
    }
    for row in &contract.causal_candidates {
        inspect(row.no_topology_commit, &row.id);
    }
    for row in &contract.episode_connections {
        inspect(row.no_topology_commit, &row.id);
    }
    for row in &contract.conflicts {
        inspect(row.no_topology_commit, &row.id);
    }
    match violation {
        Some(id) => Err(format!("story continuity row permits topology commit: {id}").into()),
        None => Ok(()),
    }
}
