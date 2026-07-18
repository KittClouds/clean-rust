use phoenix_types::ScopeKey;

use crate::{
    build_document_semantic_summary, build_graph_rebuild_snapshot, ChunkSemanticBridgeCandidate,
    ChunkSemanticBridgeCommitPolicy, ChunkSemanticBridgeStatus, ChunkSemanticBridgeType,
    DocumentSemanticEventOrdering, DocumentSemanticInput, DocumentSemanticRequest,
    DocumentSemanticStateInterval, DocumentSemanticSummary, GraphRebuildInput,
    GraphRebuildSnapshot, GraphScopeKind, CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION,
};

use super::{
    assert_story_continuity_candidate_only, build_story_continuity_contract, ContinuityStatus,
    ContinuityTemporalRelation, EpisodeBoundaryDecision, EpisodeContinuityKind,
    StoryContinuityDocument, StoryContinuityInput,
};

fn build(text: &str) -> super::StoryContinuityContract {
    build_mutating_semantics(text, |_| {})
}

fn build_mutating_semantics(
    text: &str,
    mutate: impl FnOnce(&mut DocumentSemanticSummary),
) -> super::StoryContinuityContract {
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "continuity-fixture",
        note_id: "note-continuity",
        text,
        scope: ScopeKey::default(),
        entities: &[],
        candidate_count: 0,
        built_at: Some(42),
    })
    .expect("graph snapshot");
    let mut semantic = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![DocumentSemanticInput {
            note_id: "note-continuity".to_owned(),
            text: text.to_owned(),
        }],
        entities: Vec::new(),
    });
    mutate(&mut semantic);
    build_story_continuity_contract(StoryContinuityInput {
        snapshot: &snapshot,
        documents: &[StoryContinuityDocument {
            note_id: "note-continuity".into(),
            text: text.to_owned(),
        }],
        semantic_summary: Some(&semantic),
        bridge_candidates: &[],
    })
}

fn long_scene(subject: &str, action: &str) -> String {
    (0..24)
        .map(|index| {
            format!(
                "{subject} {action} marker {index}. The room answered, and the witnesses remembered it. "
            )
        })
        .collect()
}

#[test]
fn episode_boundaries_are_source_signals_not_fixed_event_batches() {
    let text = format!(
        "# Arrival\n{}\n\n# Departure\n{}",
        long_scene("Kai", "opened the gate"),
        long_scene("Rift", "closed the gate")
    );
    let contract = build(&text);
    assert!(contract.events.len() > 12, "fixture must pressure batching");
    assert_eq!(contract.episodes.len(), 2);
    assert_ne!(
        contract.episodes.len(),
        contract.events.len().div_ceil(12),
        "episode count must not be derived from twelve-event batches"
    );
    assert!(contract
        .boundary_receipts
        .iter()
        .any(|row| row.decision == EpisodeBoundaryDecision::Heading));
    assert!(!contract.certificate.fixed_batching_detected);
}

#[test]
fn stable_episode_identity_survives_appended_source() {
    let first = format!("# Arrival\n{}", long_scene("Kai", "opened the gate"));
    let extended = format!("{first}\n\n# Later\n{}", long_scene("Rift", "returned"));
    let first_contract = build(&first);
    let extended_contract = build(&extended);
    assert_eq!(
        first_contract.episodes[0].id,
        extended_contract.episodes[0].id
    );
    assert_eq!(
        first_contract.episodes[0].boundary_receipt_ids,
        extended_contract.episodes[0].boundary_receipt_ids
    );
}

#[test]
fn every_continuity_row_is_candidate_only() {
    let text = format!(
        "# Before\n{}\n\n***\nMeanwhile, {}",
        long_scene("Kai", "waited"),
        long_scene("Rift", "returned because Kai called")
    );
    let contract = build(&text);
    assert!(contract.certificate.no_topology_writes);
    assert!(contract.certificate.all_rows_evidenced);
    assert_story_continuity_candidate_only(&contract).expect("candidate-only continuity");
}

#[test]
fn event_identities_are_source_derived_and_unique() {
    let contract = build("Kai opened the gate. Later, Rift closed the gate because Kai called.");
    assert!(!contract.events.is_empty());
    assert!(contract
        .events
        .iter()
        .all(|row| row.id.starts_with("continuity:event:note-continuity:")));
    let mut ids = contract
        .events
        .iter()
        .map(|row| row.id.as_str())
        .collect::<Vec<_>>();
    ids.sort_unstable();
    ids.dedup();
    assert_eq!(ids.len(), contract.events.len());
}

#[test]
fn scene_break_receipt_uses_the_exact_source_offset() {
    let text = "Kai opened the gate.\n\n***\n\nRift entered the city.";
    let contract = build(text);
    let scene_break = contract
        .boundary_receipts
        .iter()
        .find(|row| row.decision == EpisodeBoundaryDecision::SceneBreak)
        .expect("scene break receipt");
    assert_eq!(
        scene_break.source_offset as usize,
        text.find("***").unwrap()
    );
    assert!(scene_break
        .signals
        .iter()
        .all(|signal| !signal.evidence_ids.is_empty()));
}

#[test]
fn unicode_heading_offsets_stay_in_graph_byte_coordinates() {
    let first_scene = (0..40)
        .map(|index| format!("Kai said caf\u{e9} marker {index}. The witnesses remembered it. "))
        .collect::<String>();
    let text = format!(
        "Chapter 1: Arrival\n{first_scene}\nChapter 2: Departure\n{}",
        long_scene("Rift", "closed the gate")
    );
    let second_heading = text.find("Chapter 2:").expect("second heading") as u32;
    let contract = build(&text);
    let second = contract
        .episodes
        .iter()
        .find(|episode| episode.label.starts_with("Chapter 2:"))
        .expect("second heading episode");
    assert_eq!(second.source_start, second_heading);
    assert!(!second.chunk_ids.is_empty());
}

#[test]
fn semantic_spans_join_byte_ranged_chunks_after_unicode() {
    let first_scene = (0..40)
        .map(|index| {
            format!(
                "Kai watched the caf\u{e9} sign \u{1f642} marker {index}. The witnesses waited. "
            )
        })
        .collect::<String>();
    let text = format!(
        "Chapter 1: Arrival\n{first_scene}\nChapter 2: Departure\n{}",
        long_scene("Rift", "closed the gate")
    );
    let contract = build_mutating_semantics(&text, |semantic| {
        let document = &mut semantic.documents[0];
        let situation = document.situations.last().expect("late situation").clone();
        document
            .state_intervals
            .push(DocumentSemanticStateInterval {
                id: "state:unicode-coordinate".to_owned(),
                note_id: document.note_id.clone(),
                state_key: "closed".to_owned(),
                subject_key: "gate".to_owned(),
                predicate: "close".to_owned(),
                value: Some("closed".to_owned()),
                polarity: "positive".to_owned(),
                status: "active".to_owned(),
                start_situation_id: situation.id,
                end_situation_id: None,
                start: situation.start,
                end: Some(situation.end),
                persists: true,
                confidence_millis: 900,
                ..Default::default()
            });
    });
    let second_heading = text.find("Chapter 2:").expect("second heading") as u32;
    let second = contract
        .episodes
        .iter()
        .find(|episode| episode.label.starts_with("Chapter 2:"))
        .expect("second heading episode");
    let interval = contract
        .state_intervals
        .iter()
        .find(|interval| interval.id == "continuity:state:state:unicode-coordinate")
        .expect("Unicode state interval");
    let start_event = contract
        .events
        .iter()
        .find(|event| event.id == interval.start_event_id)
        .expect("state start event");

    assert!(start_event.source_start >= second_heading);
    assert!(second.event_ids.contains(&start_event.id));
    assert_eq!(interval.source_start, start_event.source_start);
    assert_eq!(interval.source_end, Some(start_event.source_end));
}

#[test]
fn recurrence_and_flashback_are_typed_episode_connections() {
    let text = format!(
        "# First\n{}\n\n# Second\n{}",
        long_scene("Kai", "opened the amber gate"),
        long_scene("Rift", "returned to the amber gate")
    );
    let contract = build_mutating_semantics(&text, |semantic| {
        let document = &mut semantic.documents[0];
        assert!(document.situations.len() >= 2);
        let source = document.situations[0].id.clone();
        let target = document.situations.last().unwrap().id.clone();
        document.event_orderings.extend([
            DocumentSemanticEventOrdering {
                id: "ordering:recurrence".to_owned(),
                note_id: document.note_id.clone(),
                source_situation_id: source.clone(),
                target_situation_id: target.clone(),
                relation: "recurs_after".to_owned(),
                cue: Some("again".to_owned()),
                source: "explicit_fixture".to_owned(),
                confidence_millis: 900,
                ..Default::default()
            },
            DocumentSemanticEventOrdering {
                id: "ordering:flashback".to_owned(),
                note_id: document.note_id.clone(),
                source_situation_id: target,
                target_situation_id: source,
                relation: "after".to_owned(),
                cue: Some("remembered".to_owned()),
                source: "explicit_fixture".to_owned(),
                confidence_millis: 880,
                ..Default::default()
            },
        ]);
    });
    assert!(
        contract
            .temporal_candidates
            .iter()
            .any(|row| row.relation == ContinuityTemporalRelation::RecursAfter),
        "temporal candidates: {:?}",
        contract.temporal_candidates
    );
    assert!(contract
        .episode_connections
        .iter()
        .any(|row| row.kind == EpisodeContinuityKind::Recurrence));
    assert!(contract
        .episode_connections
        .iter()
        .any(|row| row.kind == EpisodeContinuityKind::Flashback));
}

#[test]
fn state_transition_connects_ordered_episodes_without_committing() {
    let text = format!(
        "# Before\n{}\n\n# After\n{}",
        long_scene("Kai", "found the amber gate open"),
        long_scene("Rift", "found the amber gate closed")
    );
    let contract = build_mutating_semantics(&text, |semantic| {
        let document = &mut semantic.documents[0];
        assert!(document.situations.len() >= 2);
        let start = document.situations[0].clone();
        let end = document.situations.last().unwrap().clone();
        document
            .state_intervals
            .push(DocumentSemanticStateInterval {
                id: "state:gate".to_owned(),
                note_id: document.note_id.clone(),
                state_key: "open".to_owned(),
                subject_key: "gate".to_owned(),
                predicate: "be".to_owned(),
                value: Some("closed".to_owned()),
                polarity: "positive".to_owned(),
                status: "superseded".to_owned(),
                start_situation_id: start.id,
                end_situation_id: Some(end.id),
                start: start.start,
                end: Some(end.end),
                persists: false,
                confidence_millis: 920,
                ..Default::default()
            });
    });
    assert!(contract
        .state_intervals
        .iter()
        .any(|row| row.subject_key == "gate" && !row.persists));
    assert!(contract
        .episode_connections
        .iter()
        .any(|row| row.kind == EpisodeContinuityKind::StateTransition && row.no_topology_commit));
}

#[test]
fn hypothetical_causal_language_never_becomes_an_asserted_candidate() {
    let contract = build("Kai wondered if the gate opened because Rift might return.");
    assert!(contract
        .causal_candidates
        .iter()
        .all(|row| row.status == ContinuityStatus::ReviewRequired || row.modality != "asserted"));
    assert_story_continuity_candidate_only(&contract).expect("candidate-only false cause");
}

#[test]
fn semantic_bridge_can_connect_episodes_across_documents_without_becoming_identity() {
    let documents = [
        StoryContinuityDocument {
            note_id: "early".into(),
            text: format!(
                "# Signal\n{}",
                long_scene(
                    "Kai",
                    "lit the rare amber beacon because the north gate failed"
                )
            ),
        },
        StoryContinuityDocument {
            note_id: "late".into(),
            text: format!(
                "# Return\n{}",
                long_scene(
                    "Rift",
                    "answered the rare amber beacon after the north gate failed"
                )
            ),
        },
    ];
    let mut snapshots = documents
        .iter()
        .map(snapshot_for_document)
        .collect::<Vec<_>>();
    let mut snapshot = snapshots.remove(0);
    merge_snapshot(&mut snapshot, snapshots.remove(0));
    let semantic = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: documents
            .iter()
            .map(|document| DocumentSemanticInput {
                note_id: document.note_id.to_string(),
                text: document.text.clone(),
            })
            .collect(),
        entities: Vec::new(),
    });
    let source_chunk_id = snapshot
        .chunks
        .iter()
        .find(|chunk| chunk.note_id == "early")
        .unwrap()
        .id
        .clone();
    let target_chunk_id = snapshot
        .chunks
        .iter()
        .find(|chunk| chunk.note_id == "late")
        .unwrap()
        .id
        .clone();
    let bridges = vec![ChunkSemanticBridgeCandidate {
        schema_version: CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION.into(),
        id: "bridge:early:late".into(),
        bridge_type: ChunkSemanticBridgeType::CauseEffect,
        source_chunk_id,
        target_chunk_id,
        source_event_id: None,
        target_event_id: None,
        source_episode_id: None,
        target_episode_id: None,
        claim: "The later beacon answers the earlier gate failure".into(),
        evidence_ids: vec!["evidence:early".into(), "evidence:late".into()],
        supporting_entity_ids: Vec::new(),
        confidence: 0.9,
        status: ChunkSemanticBridgeStatus::Candidate,
        commit_policy: ChunkSemanticBridgeCommitPolicy::NoTopologyCommit,
        semantic_verbs: vec!["answer".into()],
        source_cue: Some("because".into()),
        target_cue: Some("after".into()),
        rationale: vec!["typed_cross_document_cause".into()],
    }];
    let contract = build_story_continuity_contract(StoryContinuityInput {
        snapshot: &snapshot,
        documents: &documents,
        semantic_summary: Some(&semantic),
        bridge_candidates: &bridges,
    });
    assert!(
        contract
            .episode_connections
            .iter()
            .any(|row| row.kind == EpisodeContinuityKind::CrossDocumentContinuation),
        "episodes: {:?}; connections: {:?}",
        contract.episodes,
        contract.episode_connections
    );
    assert!(contract
        .episode_connections
        .iter()
        .all(|row| row.id.starts_with("continuity:episode:") && row.no_topology_commit));
}

fn snapshot_for_document(document: &StoryContinuityDocument) -> GraphRebuildSnapshot {
    build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::MultiNote,
        scope_id: "continuity-multi",
        note_id: document.note_id.as_str(),
        text: document.text.as_str(),
        scope: ScopeKey::default(),
        entities: &[],
        candidate_count: 0,
        built_at: Some(42),
    })
    .expect("document snapshot")
}

fn merge_snapshot(target: &mut GraphRebuildSnapshot, mut source: GraphRebuildSnapshot) {
    target.note_ids.append(&mut source.note_ids);
    target.chunks.append(&mut source.chunks);
    target.events.append(&mut source.events);
    target.episodes.append(&mut source.episodes);
    target.temporal_edges.append(&mut source.temporal_edges);
    target.causal_edges.append(&mut source.causal_edges);
    target.memory_state.append(&mut source.memory_state);
    target.note_ids.sort();
    target.note_ids.dedup();
}
