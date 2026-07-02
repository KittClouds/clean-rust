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

#[test]
fn gives_low_signal_chunks_specific_attenuation_rationale() {
    let snapshot = governance_snapshot();
    let candidates = build_memory_governance_candidates_from_snapshot(&snapshot);
    let candidate = candidates
        .iter()
        .find(|row| row.target_id == "note:memory:chunk:1")
        .expect("low signal chunk");

    assert_eq!(candidate.action, GraphMemoryGovernanceAction::Attenuate);
    assert_eq!(candidate.reason, "chunk_has_no_events_or_entity_evidence");
    assert!(candidate
        .rationale
        .iter()
        .any(|row| row == "audit:no_events"));
    assert!(candidate
        .rationale
        .iter()
        .any(|row| row == "audit:no_supporting_entities"));
}

#[test]
fn ranks_episode_compression_by_signal_density() {
    let episode = GraphEpisode {
        id: "episode:ranked".into(),
        note_id: "note:memory".into(),
        event_ids: Vec::new(),
        entity_ids: Vec::new(),
        label: "Ranked".into(),
    };
    let sparse = episode_candidate(&episode, Some(&compression_stats(4, 2, 3, 2)));
    let rich = episode_candidate(&episode, Some(&compression_stats(42, 8, 10, 8)));

    assert_eq!(sparse.action, GraphMemoryGovernanceAction::Compress);
    assert_eq!(rich.action, GraphMemoryGovernanceAction::Compress);
    assert!(rich.confidence > sparse.confidence);
    assert!(rich.confidence < 0.95);
}

#[test]
fn shortrun_golden_fixture_matches_rust_governance() {
    let report = build_memory_governance_shortrun_golden_report(
        include_str!("../../../../../docs/shortrun.md"),
        include_str!(
            "../../../../../src/app/graph-rebuild/fixtures/memory-governance-shortrun-golden.json"
        ),
    )
    .expect("shortrun governance golden report");

    assert_eq!(
        report.candidate_only_audit,
        MemoryGovernanceCandidateOnlyAudit::default()
    );
    assert!(
        report.comparison.exact_counts_match,
        "{:#?}",
        report.comparison
    );
    assert!(
        report.comparison.compress_confidence_matches,
        "{:#?}",
        report.comparison
    );
    assert!(report.comparison.golden_sample_ids_missing.is_empty());
    assert!(report.comparison.golden_sample_mismatches.is_empty());
    assert!(
        report.comparison.performance_budget_passed,
        "{:#?}",
        report.timing
    );
}

#[test]
fn retrieval_preview_applies_governance_without_mutating_topology() {
    let snapshot = governance_snapshot();
    let edge_count = snapshot.edges.len();
    let governance = build_memory_governance_candidates_from_snapshot(&snapshot);
    let retrieval = vec![
        retrieval_candidate(
            "hit:low-signal",
            "note:memory:chunk:1",
            GraphMemoryGovernanceTargetKind::Chunk,
            0.88,
        ),
        retrieval_candidate(
            "hit:episode",
            "episode:memory:0",
            GraphMemoryGovernanceTargetKind::Episode,
            0.82,
        ),
        retrieval_candidate(
            "hit:retain",
            "note:memory:chunk:0",
            GraphMemoryGovernanceTargetKind::Chunk,
            0.80,
        ),
        retrieval_candidate(
            "hit:ungoverned",
            "note:memory:chunk:missing",
            GraphMemoryGovernanceTargetKind::Chunk,
            0.79,
        ),
    ];

    let preview =
        build_memory_governance_retrieval_preview(MemoryGovernanceRetrievalPreviewInput {
            retrieval_candidates: &retrieval,
            governance_candidates: &governance,
        });

    assert_eq!(snapshot.edges.len(), edge_count);
    assert_eq!(
        preview.schema_version,
        MEMORY_GOVERNANCE_RETRIEVAL_PREVIEW_SCHEMA_VERSION
    );
    assert!(preview.no_topology_commit);
    assert_eq!(preview.summary.candidate_count, 4);
    assert_eq!(preview.summary.governed_count, 3);
    assert_eq!(preview.summary.compressed_count, 1);
    assert_eq!(preview.summary.attenuated_count, 1);
    assert!(preview.summary.changed_rank_count >= 2);

    let episode = preview
        .rows
        .iter()
        .find(|row| row.target_id == "episode:memory:0")
        .expect("episode row");
    let low_signal = preview
        .rows
        .iter()
        .find(|row| row.target_id == "note:memory:chunk:1")
        .expect("attenuated row");

    assert_eq!(
        episode.governance_action,
        Some(GraphMemoryGovernanceAction::Compress)
    );
    assert!(episode.adjusted_rank < episode.original_rank);
    assert_eq!(
        low_signal.governance_action,
        Some(GraphMemoryGovernanceAction::Attenuate)
    );
    assert!(low_signal.adjusted_score < low_signal.original_score);
    assert!(low_signal
        .rationale
        .iter()
        .any(|row| row == "audit:no_events"));
}

#[test]
fn retrieval_weighting_experiment_compares_policy_effects_without_live_retrieval() {
    let snapshot = governance_snapshot();
    let governance = build_memory_governance_candidates_from_snapshot(&snapshot);
    let retrieval = vec![
        retrieval_candidate(
            "hit:low-signal",
            "note:memory:chunk:1",
            GraphMemoryGovernanceTargetKind::Chunk,
            0.88,
        ),
        retrieval_candidate(
            "hit:episode",
            "episode:memory:0",
            GraphMemoryGovernanceTargetKind::Episode,
            0.82,
        ),
        retrieval_candidate(
            "hit:retain",
            "note:memory:chunk:0",
            GraphMemoryGovernanceTargetKind::Chunk,
            0.80,
        ),
        retrieval_candidate(
            "hit:ungoverned",
            "note:memory:chunk:missing",
            GraphMemoryGovernanceTargetKind::Chunk,
            0.79,
        ),
    ];

    let experiment = build_memory_governance_retrieval_weighting_experiment(
        MemoryGovernanceRetrievalPreviewInput {
            retrieval_candidates: &retrieval,
            governance_candidates: &governance,
        },
    );

    assert_eq!(
        experiment.schema_version,
        MEMORY_GOVERNANCE_RETRIEVAL_WEIGHTING_EXPERIMENT_SCHEMA_VERSION
    );
    assert_eq!(experiment.baseline_policy_id, "balanced");
    assert!(experiment.no_topology_commit);
    assert_eq!(experiment.variants.len(), 4);

    let conservative = experiment_variant(&experiment, "conservative");
    let episode_anchor = experiment_variant(&experiment, "episode_anchor");
    let decay_heavy = experiment_variant(&experiment, "decay_heavy");

    assert!(
        episode_anchor.compressed_mean_score_delta_millis
            > conservative.compressed_mean_score_delta_millis
    );
    assert!(
        decay_heavy.attenuated_mean_score_delta_millis
            < conservative.attenuated_mean_score_delta_millis
    );
    assert!(episode_anchor.summary.promoted_count >= conservative.summary.promoted_count);
    assert!(decay_heavy.summary.demoted_count >= conservative.summary.demoted_count);
    assert!(experiment
        .variants
        .iter()
        .all(|variant| variant.top_rows.iter().all(|row| row.no_topology_commit)));
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

fn compression_stats(
    evidence_count: usize,
    entity_count: usize,
    event_count: usize,
    chunk_count: usize,
) -> TargetStats {
    let mut entity_ids = HashSet::with_capacity(entity_count);
    for index in 0..entity_count {
        entity_ids.insert(format_compact!("entity:{index}"));
    }
    TargetStats {
        evidence_ids: (0..evidence_count)
            .map(|index| format_compact!("evidence:{index}"))
            .collect(),
        entity_ids,
        event_ids: (0..event_count)
            .map(|index| format_compact!("event:{index}"))
            .collect(),
        chunk_ids: (0..chunk_count)
            .map(|index| format_compact!("chunk:{index}"))
            .collect(),
        event_count,
        temporal_degree: event_count.saturating_sub(1),
        causal_degree: entity_count / 2,
        ..TargetStats::default()
    }
}

fn retrieval_candidate(
    id: &str,
    target_id: &str,
    target_kind: GraphMemoryGovernanceTargetKind,
    score: f32,
) -> MemoryGovernanceRetrievalCandidate {
    MemoryGovernanceRetrievalCandidate {
        id: id.into(),
        target_id: target_id.into(),
        target_kind,
        score,
    }
}

fn experiment_variant<'a>(
    experiment: &'a MemoryGovernanceRetrievalWeightingExperiment,
    policy_id: &str,
) -> &'a MemoryGovernanceRetrievalWeightingVariant {
    experiment
        .variants
        .iter()
        .find(|variant| variant.policy.id == policy_id)
        .expect("experiment variant")
}
