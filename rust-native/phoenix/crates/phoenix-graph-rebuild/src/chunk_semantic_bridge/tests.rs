use phoenix_types::EntityId;

use super::*;

use crate::{
    GraphAnchor, GraphChunk, GraphCounters, GraphDropReasons, GraphEvent, GraphNode,
    GraphRebuildSnapshot, GraphScopeKind, GraphTemporalEdge,
};

#[test]
fn emits_candidate_only_bridge_rows_without_topology_commit() {
    let kai = EntityId("character:kai".to_owned());
    let tempest = EntityId("character:tempest".to_owned());
    let source_entities = vec![kai.clone(), tempest.clone()];
    let target_entities = vec![tempest.clone(), kai.clone()];
    let chunks = vec![
        chunk(
            "note:1:chunk:0",
            0,
            "Kai warned Tempest that somebody had to cross the transit door.",
            &source_entities,
        ),
        chunk("note:1:chunk:1", 1, "Arcadia looked quiet.", &[]),
        chunk(
            "note:1:chunk:2",
            2,
            "Tempest answered Kai and opened the rail door.",
            &target_entities,
        ),
    ];
    let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        ..ChunkSemanticBridgeEngineInput::default()
    });

    assert_eq!(candidates.len(), 1);
    let bridge = &candidates[0];
    assert_eq!(bridge.schema_version, CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION);
    assert_eq!(bridge.status, ChunkSemanticBridgeStatus::Candidate);
    assert_eq!(
        bridge.commit_policy,
        ChunkSemanticBridgeCommitPolicy::NoTopologyCommit
    );
    assert_eq!(bridge.bridge_type, ChunkSemanticBridgeType::SetupPayoff);
    assert_eq!(bridge.source_episode_id.as_deref(), Some("episode:0"));
    assert_eq!(bridge.target_episode_id.as_deref(), Some("episode:2"));
    assert!(bridge
        .rationale
        .iter()
        .any(|row| row == CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT));
    assert_chunk_semantic_bridge_candidate_only(&candidates).expect("candidate guard");
}

#[test]
fn serializes_to_frontend_chunk_semantic_bridge_contract() {
    let kai = EntityId("character:kai".to_owned());
    let tempest = EntityId("character:tempest".to_owned());
    let source_entities = vec![kai.clone(), tempest.clone()];
    let target_entities = vec![tempest, kai];
    let chunks = vec![
        chunk(
            "note:1:chunk:0",
            0,
            "Kai had to warn Tempest.",
            &source_entities,
        ),
        chunk("note:1:chunk:1", 1, "The city waited.", &[]),
        chunk(
            "note:1:chunk:2",
            2,
            "Tempest answered Kai with evidence.",
            &target_entities,
        ),
    ];
    let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        ..ChunkSemanticBridgeEngineInput::default()
    });
    let value = serde_json::to_value(&candidates[0]).expect("bridge json");
    let object = value.as_object().expect("bridge object");

    assert_eq!(
        object["schemaVersion"],
        CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION
    );
    assert_eq!(object["bridgeType"], "setup_payoff");
    assert_eq!(object["sourceChunkId"], "note:1:chunk:0");
    assert_eq!(object["targetChunkId"], "note:1:chunk:2");
    assert_eq!(object["status"], "candidate");
    assert_eq!(object["commitPolicy"], CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY);
    assert_eq!(object["supportingEntityIds"][0], "character:kai");
    assert!(object["rationale"]
        .as_array()
        .expect("rationale")
        .iter()
        .any(|row| row == CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT));
    assert!(!object.contains_key("commit_policy"));
    assert!(!object.contains_key("bridge_type"));
}

#[test]
fn demotes_same_entity_only_topic_rows() {
    let kai = EntityId("character:kai".to_owned());
    let tempest = EntityId("character:tempest".to_owned());
    let entities = vec![kai, tempest];
    let chunks = vec![
        chunk("note:1:chunk:0", 0, "Kai said this.", &entities),
        chunk("note:1:chunk:1", 1, "Tempest watched.", &entities),
        chunk("note:1:chunk:2", 2, "Kai said that.", &entities),
    ];
    let events = vec![
        event(
            "event:0",
            "note:1:chunk:0",
            "dialogue_event in chunk 1",
            &entities,
        ),
        event(
            "event:2",
            "note:1:chunk:2",
            "dialogue_event in chunk 3",
            &entities,
        ),
    ];
    let temporal_edges = vec![ChunkSemanticBridgeEventEdge {
        source_event_id: "event:0",
        target_event_id: "event:2",
        relation_type: "before",
        cue: None,
        evidence_ids: &[],
        confidence: 0.70,
    }];

    let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        events: &events,
        temporal_edges: &temporal_edges,
        causal_edges: &[],
        ..ChunkSemanticBridgeEngineInput::default()
    });

    assert!(candidates.is_empty());
}

#[test]
fn keeps_temporal_route_rows_with_real_semantic_cues() {
    let kai = EntityId("character:kai".to_owned());
    let entities = vec![kai];
    let chunks = vec![
        chunk(
            "note:1:chunk:0",
            0,
            "Kai entered the red transit station.",
            &entities,
        ),
        chunk("note:1:chunk:1", 1, "The city waited.", &[]),
        chunk(
            "note:1:chunk:2",
            2,
            "Kai returned through the rail door.",
            &entities,
        ),
    ];
    let events = vec![
        event(
            "event:0",
            "note:1:chunk:0",
            "arrival_event in chunk 1",
            &entities,
        ),
        event(
            "event:2",
            "note:1:chunk:2",
            "arrival_event in chunk 3",
            &entities,
        ),
    ];
    let temporal_edges = vec![ChunkSemanticBridgeEventEdge {
        source_event_id: "event:0",
        target_event_id: "event:2",
        relation_type: "before",
        cue: None,
        evidence_ids: &[],
        confidence: 0.70,
    }];

    let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        events: &events,
        temporal_edges: &temporal_edges,
        causal_edges: &[],
        ..ChunkSemanticBridgeEngineInput::default()
    });

    assert_eq!(candidates.len(), 1);
    assert_eq!(
        candidates[0].bridge_type,
        ChunkSemanticBridgeType::RouteContinuity
    );
    assert!(!is_same_entity_only_bridge_suspect(&candidates[0]));
}

#[test]
fn quality_gate_demotes_same_entity_only_and_keeps_real_semantic_cues() {
    let opaque_topic = quality_candidate(
        ChunkSemanticBridgeType::TopicContinuation,
        "same_frame_or_event_type_with_shared_participants",
    );
    assert_eq!(
        bridge_quality_gate_decision(&opaque_topic),
        BridgeQualityGateDecision::DemoteSameEntityOnly
    );

    let survivors = vec![
        quality_candidate(
            ChunkSemanticBridgeType::CauseEffect,
            "causal_language_spans_chunks",
        ),
        quality_candidate(
            ChunkSemanticBridgeType::SetupPayoff,
            "setup_cue_plus_later_payoff_cue",
        ),
        quality_candidate(
            ChunkSemanticBridgeType::RouteContinuity,
            "route_or_threshold_cue_spans_chunks",
        ),
        quality_candidate(
            ChunkSemanticBridgeType::EvidenceReframe,
            "evidence_or_documentation_reframes_prior_chunk",
        ),
        quality_candidate(
            ChunkSemanticBridgeType::RelationshipDelta,
            "relationship_cue_with_shared_participants",
        ),
        quality_candidate(
            ChunkSemanticBridgeType::StateDelta,
            "later_chunk_changes_prior_state",
        ),
        quality_candidate(ChunkSemanticBridgeType::MotifEcho, "motif:transit"),
    ];

    for bridge in &survivors {
        assert_eq!(
            bridge_quality_gate_decision(bridge),
            BridgeQualityGateDecision::Accept
        );
        assert!(!is_same_entity_only_bridge_suspect(bridge));
    }

    let mut all = survivors.clone();
    all.push(opaque_topic);
    let audit = audit_chunk_semantic_bridge_quality_gate(&all);
    assert_eq!(audit.total, 8);
    assert_eq!(audit.accepted, 7);
    assert_eq!(audit.demoted_same_entity_only, 1);
}

#[test]
fn snapshot_adapter_returns_candidates_without_mutating_snapshot() {
    let source = "Kai warned Tempest that somebody had to cross the transit door. ";
    let middle = "Arcadia waited between them. ";
    let target = "Tempest answered Kai because the rail door opened.";
    let text = format!("{source}{middle}{target}");
    let snapshot = adapter_snapshot(source, middle, target);
    let chunk_count = snapshot.chunks.len();
    let event_count = snapshot.events.len();

    let candidates = build_chunk_semantic_bridge_candidates_from_snapshot(
        &snapshot,
        &[ChunkSemanticBridgeSnapshotDocument {
            note_id: "note:adapter",
            text: &text,
        }],
    );

    assert!(!candidates.is_empty());
    assert_eq!(snapshot.chunks.len(), chunk_count);
    assert_eq!(snapshot.events.len(), event_count);
    assert_chunk_semantic_bridge_candidate_only(&candidates).expect("candidate-only adapter");
    assert!(candidates.iter().all(|candidate| snapshot
        .chunks
        .iter()
        .any(|chunk| chunk.id == candidate.source_chunk_id)));
    assert!(candidates.iter().all(|candidate| snapshot
        .chunks
        .iter()
        .any(|chunk| chunk.id == candidate.target_chunk_id)));
}

#[test]
fn emits_cross_document_chunk_and_episode_candidates_without_topology_commit() {
    let kai = EntityId("character:kai".to_owned());
    let tempest = EntityId("character:tempest".to_owned());
    let entities = vec![kai, tempest];
    let chunks = vec![
        document_chunk(
            "source-span-alpha",
            "early",
            0,
            "episode:early:0",
            "Kai asked Tempest to remember the transit warning.",
            &entities,
        ),
        document_chunk(
            "source-span-omega",
            "late",
            0,
            "episode:late:0",
            "Tempest answered Kai and opened the transit door.",
            &entities,
        ),
    ];

    let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        ..ChunkSemanticBridgeEngineInput::default()
    });

    assert_eq!(candidates.len(), 1);
    let bridge = &candidates[0];
    assert_eq!(bridge.source_chunk_id, "source-span-alpha");
    assert_eq!(bridge.target_chunk_id, "source-span-omega");
    assert_eq!(bridge.source_episode_id.as_deref(), Some("episode:early:0"));
    assert_eq!(bridge.target_episode_id.as_deref(), Some("episode:late:0"));
    assert!(bridge
        .rationale
        .iter()
        .any(|row| row == "cross_document_bridge"));
    assert!(bridge
        .rationale
        .iter()
        .any(|row| row == "document_pair:early->late"));
    assert_chunk_semantic_bridge_candidate_only(&candidates).expect("candidate-only cross-doc");
}

#[test]
fn cross_document_run_certificate_proves_coverage_excerpts_and_no_topology() {
    let kai = EntityId("character:kai".to_owned());
    let entities = vec![kai];
    let chunks = vec![
        document_chunk(
            "early:chunk:0",
            "early",
            0,
            "episode:early:0",
            "Kai sealed the transit warning beneath the red gate.",
            &entities,
        ),
        document_chunk(
            "late:chunk:0",
            "late",
            0,
            "episode:late:0",
            "Kai answered the old warning and opened the red gate.",
            &entities,
        ),
    ];

    let run = build_chunk_semantic_bridge_run(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        ..ChunkSemanticBridgeEngineInput::default()
    });
    let certificate = &run.cross_document_certificate;

    assert_eq!(
        certificate.schema_version,
        CROSS_DOCUMENT_BRIDGE_CERTIFICATE_SCHEMA_VERSION
    );
    assert_eq!(certificate.pair_coverage.len(), 1);
    assert_eq!(certificate.pair_coverage[0].source_document_id, "early");
    assert_eq!(certificate.pair_coverage[0].target_document_id, "late");
    assert_eq!(certificate.selected_candidates, run.candidates.len());
    assert!(certificate.no_topology_writes);
    assert!(certificate
        .selected_rows
        .iter()
        .all(|row| !row.source_excerpt.is_empty() && !row.target_excerpt.is_empty()));
    assert!(certificate
        .selected_rows
        .iter()
        .all(|row| row.no_topology_commit));
    assert!(certificate.weakest_rows.len() <= certificate.selected_rows.len());
}

#[test]
fn cross_document_selection_covers_pairs_and_dampens_global_protagonist() {
    let ryan = EntityId("character:ryan".to_owned());
    let ab = EntityId("thread:ab".to_owned());
    let ac = EntityId("thread:ac".to_owned());
    let bc = EntityId("thread:bc".to_owned());
    let a_entities = vec![ryan.clone(), ab.clone(), ac.clone()];
    let b_entities = vec![ryan.clone(), ab, bc.clone()];
    let c_entities = vec![ryan, ac, bc];
    let text = "Ryan asked what the transit warning meant and later answered at the door.";
    let chunks = vec![
        document_chunk("a:chunk:0", "a", 0, "episode:a:0", text, &a_entities),
        document_chunk("a:chunk:1", "a", 1, "episode:a:1", text, &a_entities),
        document_chunk("a:chunk:2", "a", 2, "episode:a:2", text, &a_entities),
        document_chunk("b:chunk:0", "b", 0, "episode:b:0", text, &b_entities),
        document_chunk("b:chunk:1", "b", 1, "episode:b:1", text, &b_entities),
        document_chunk("b:chunk:2", "b", 2, "episode:b:2", text, &b_entities),
        document_chunk("c:chunk:0", "c", 0, "episode:c:0", text, &c_entities),
        document_chunk("c:chunk:1", "c", 1, "episode:c:1", text, &c_entities),
        document_chunk("c:chunk:2", "c", 2, "episode:c:2", text, &c_entities),
    ];

    let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        ..ChunkSemanticBridgeEngineInput::default()
    });
    let cross_document = candidates
        .iter()
        .filter(|bridge| {
            bridge
                .source_chunk_id
                .split_once(":chunk:")
                .map(|row| row.0)
                != bridge
                    .target_chunk_id
                    .split_once(":chunk:")
                    .map(|row| row.0)
        })
        .collect::<Vec<_>>();
    let mut counts = hashbrown::HashMap::<String, usize>::new();
    for bridge in &cross_document {
        let source = bridge.source_chunk_id.split_once(":chunk:").unwrap().0;
        let target = bridge.target_chunk_id.split_once(":chunk:").unwrap().0;
        *counts.entry(format!("{source}->{target}")).or_default() += 1;
        assert!(bridge.supporting_entity_ids.len() >= 2);
        assert!(bridge
            .rationale
            .iter()
            .any(|row| row.starts_with("primary_support_entity:")));
        assert!(!bridge
            .rationale
            .iter()
            .any(|row| row == "primary_support_entity:character:ryan"));
        assert!(bridge
            .rationale
            .iter()
            .any(|row| row == "support_role:incidental_registry_wide:character:ryan"));
    }

    assert_eq!(counts.len(), 3);
    assert!(counts.values().all(|count| *count > 0 && *count <= 24));
    assert_chunk_semantic_bridge_candidate_only(&candidates).expect("candidate-only fair rows");
}

#[test]
fn shortrun_parity_report_compares_rust_candidates_to_fixture() {
    let report = build_chunk_semantic_bridge_shortrun_parity_report(
        include_str!("../../../../../../docs/shortrun.md"),
        include_str!(
            "../../../../../../src/app/graph-rebuild/fixtures/chunk-semantic-bridge-shortrun-golden.json"
        ),
    )
    .expect("shortrun parity report");

    assert_eq!(report.fixture.total, 320);
    assert!(report.rust.total > 0);
    assert_eq!(report.candidate_only_audit.invalid_schema_version, 0);
    assert_eq!(report.candidate_only_audit.invalid_status, 0);
    assert_eq!(report.candidate_only_audit.invalid_commit_policy, 0);
    assert_eq!(report.candidate_only_audit.missing_no_topology_guard, 0);
    assert_eq!(
        report
            .candidate_only_audit
            .same_entity_only_false_positive_suspects,
        0
    );
    assert!(!report.representative_rows.is_empty());
    assert!(report.timing.total_micros > 0);
}

fn quality_candidate(
    bridge_type: ChunkSemanticBridgeType,
    rationale: &str,
) -> ChunkSemanticBridgeCandidate {
    ChunkSemanticBridgeCandidate {
        schema_version: CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION.into(),
        id: format!("quality:{}:{rationale}", bridge_type.as_str()).into(),
        bridge_type,
        source_chunk_id: "chunk:source".into(),
        target_chunk_id: "chunk:target".into(),
        source_event_id: None,
        target_event_id: None,
        source_episode_id: Some("episode:source".into()),
        target_episode_id: Some("episode:target".into()),
        claim: "quality gate test bridge".into(),
        evidence_ids: vec!["chunk:source".into(), "chunk:target".into()],
        supporting_entity_ids: vec!["entity:kai".into()],
        confidence: 0.70,
        status: ChunkSemanticBridgeStatus::Candidate,
        commit_policy: ChunkSemanticBridgeCommitPolicy::NoTopologyCommit,
        semantic_verbs: vec!["continues".into()],
        source_cue: Some("dialogue_event".into()),
        target_cue: Some("dialogue_event".into()),
        rationale: vec![
            CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT.into(),
            format!("bridge_type:{}", bridge_type.as_str()).into(),
            "supporting_entities:1".into(),
            rationale.into(),
        ],
    }
}

fn chunk<'a>(
    id: &'a str,
    ordinal: u32,
    text: &'a str,
    entity_ids: &'a [EntityId],
) -> ChunkSemanticBridgeChunk<'a> {
    ChunkSemanticBridgeChunk {
        id,
        note_id: "note:1",
        ordinal,
        text,
        role: None,
        episode_id: Some(match ordinal {
            0 => "episode:0",
            1 => "episode:1",
            _ => "episode:2",
        }),
        entity_ids,
        evidence_ids: &[],
    }
}

fn document_chunk<'a>(
    id: &'a str,
    note_id: &'a str,
    ordinal: u32,
    episode_id: &'a str,
    text: &'a str,
    entity_ids: &'a [EntityId],
) -> ChunkSemanticBridgeChunk<'a> {
    ChunkSemanticBridgeChunk {
        id,
        note_id,
        ordinal,
        text,
        role: None,
        episode_id: Some(episode_id),
        entity_ids,
        evidence_ids: &[],
    }
}

fn event<'a>(
    id: &'a str,
    chunk_id: &'a str,
    label: &'a str,
    entity_ids: &'a [EntityId],
) -> ChunkSemanticBridgeEvent<'a> {
    ChunkSemanticBridgeEvent {
        id,
        note_id: "note:1",
        chunk_id: Some(chunk_id),
        label,
        entity_ids,
        evidence_ids: &[],
        confidence: 0.70,
    }
}

fn adapter_snapshot(source: &str, middle: &str, target: &str) -> GraphRebuildSnapshot {
    let kai = EntityId("character:kai".to_owned());
    let tempest = EntityId("character:tempest".to_owned());
    let source_end = source.len() as u32;
    let middle_start = source_end;
    let middle_end = middle_start + middle.len() as u32;
    let target_start = middle_end;
    let chunks = vec![
        graph_chunk("note:adapter:chunk:0", 0, 0, source_end),
        graph_chunk("note:adapter:chunk:1", 1, middle_start, middle_end),
        graph_chunk(
            "note:adapter:chunk:2",
            2,
            target_start,
            target_start + target.len() as u32,
        ),
    ];
    let anchors = vec![
        graph_anchor("anchor:kai:0", &kai, "note:adapter:chunk:0", 0, 3, "Kai"),
        graph_anchor(
            "anchor:tempest:0",
            &tempest,
            "note:adapter:chunk:0",
            11,
            18,
            "Tempest",
        ),
        graph_anchor(
            "anchor:tempest:2",
            &tempest,
            "note:adapter:chunk:2",
            target_start,
            target_start + 7,
            "Tempest",
        ),
        graph_anchor(
            "anchor:kai:2",
            &kai,
            "note:adapter:chunk:2",
            target_start + 17,
            target_start + 20,
            "Kai",
        ),
    ];
    let events = vec![
        graph_event(
            "event:warning",
            "note:adapter:chunk:0",
            "warning_event in chunk 1",
            &[kai.clone(), tempest.clone()],
            &["anchor:kai:0", "anchor:tempest:0"],
        ),
        graph_event(
            "event:answer",
            "note:adapter:chunk:2",
            "dialogue_event in chunk 3",
            &[tempest.clone(), kai.clone()],
            &["anchor:tempest:2", "anchor:kai:2"],
        ),
    ];
    GraphRebuildSnapshot {
        schema_version: "phoenix-graph-rebuild/v1".into(),
        id: "snapshot:adapter".into(),
        source: "test".into(),
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:adapter".into(),
        note_ids: vec!["note:adapter".into()],
        built_at: 77,
        chunks,
        mentions: Vec::new(),
        entity_anchors: anchors,
        relationships: Vec::new(),
        events,
        episodes: vec![crate::GraphEpisode {
            id: "episode:adapter:0".into(),
            note_id: "note:adapter".into(),
            event_ids: vec!["event:warning".into(), "event:answer".into()],
            entity_ids: vec![kai.clone(), tempest.clone()],
            label: "Episode 1".into(),
        }],
        episode_projection_edges: Vec::new(),
        temporal_edges: vec![GraphTemporalEdge {
            id: "temporal:event:warning:event:answer".into(),
            source_id: "event:warning".into(),
            target_id: "event:answer".into(),
            relation_type: "before".into(),
            evidence_ids: vec!["event:warning".into(), "event:answer".into()],
            confidence: 0.72,
        }],
        causal_edges: Vec::new(),
        memory_state: Vec::new(),
        memory_governance_candidates: Vec::new(),
        embedding_targets: Vec::new(),
        embedding_vectors: Vec::new(),
        projection_refs: Vec::new(),
        nodes: vec![graph_node(&kai, "Kai"), graph_node(&tempest, "Tempest")],
        edges: Vec::new(),
        calendar_registry_summary: None,
        document_sidecar_summary: None,
        document_review_summary: None,
        document_compiler_summary: None,
        discourse_spine_summary: None,
        counters: GraphCounters {
            chunks: 3,
            events: 2,
            episodes: 1,
            temporal_edges: 1,
            nodes: 2,
            drop_reasons: GraphDropReasons::default(),
            ..GraphCounters::default()
        },
    }
}

fn graph_chunk(id: &str, ordinal: u32, start: u32, end: u32) -> GraphChunk {
    GraphChunk {
        id: id.into(),
        note_id: "note:adapter".into(),
        start,
        end,
        ordinal,
        source: "test".into(),
    }
}

fn graph_anchor(
    id: &str,
    entity_id: &EntityId,
    chunk_id: &str,
    start: u32,
    end: u32,
    surface: &str,
) -> GraphAnchor {
    GraphAnchor {
        id: id.into(),
        entity_id: entity_id.clone(),
        note_id: "note:adapter".into(),
        chunk_id: Some(chunk_id.into()),
        surface: surface.into(),
        source_start: start,
        source_end: end,
        source: "test".into(),
        confidence: 1.0,
        generation: 77,
    }
}

fn graph_event(
    id: &str,
    chunk_id: &str,
    label: &str,
    entity_ids: &[EntityId],
    evidence_ids: &[&str],
) -> GraphEvent {
    GraphEvent {
        id: id.into(),
        note_id: "note:adapter".into(),
        chunk_id: Some(chunk_id.into()),
        label: label.into(),
        entity_ids: entity_ids.to_vec(),
        evidence_anchor_ids: evidence_ids.iter().map(|id| (*id).into()).collect(),
        confidence: 0.70,
    }
}

fn graph_node(entity_id: &EntityId, label: &str) -> GraphNode {
    GraphNode {
        id: entity_id.clone(),
        entity_id: entity_id.clone(),
        label: label.into(),
        kind: "character".into(),
        aliases: Vec::new(),
        anchor_ids: Vec::new(),
        note_ids: vec!["note:adapter".into()],
        total_mentions: 2,
    }
}
