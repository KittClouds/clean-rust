use super::selection::select_bridge_rows_fair;
use super::*;

#[test]
fn omnipresent_protagonist_does_not_admit_opaque_cross_document_rows() {
    let protagonist = EntityId("character:protagonist".to_owned());
    let entities = vec![protagonist];
    let chunks = three_document_chunks("The protagonist stood quietly.", &entities);

    let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        ..ChunkSemanticBridgeEngineInput::default()
    });

    assert!(candidates.is_empty());
}

#[test]
fn widespread_location_does_not_become_semantic_evidence_by_frequency() {
    let location = EntityId("location:everywhere".to_owned());
    let entities = vec![location];
    let chunks = three_document_chunks("The old city remained quiet.", &entities);

    let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        ..ChunkSemanticBridgeEngineInput::default()
    });

    assert!(candidates.is_empty());
}

#[test]
fn rare_shared_entity_sponsors_protagonist_pair() {
    let protagonist = EntityId("character:protagonist".to_owned());
    let rare = EntityId("location:rare-threshold".to_owned());
    let pair = vec![protagonist.clone(), rare.clone()];
    let protagonist_only = vec![protagonist];
    let chunks = vec![
        chunk(
            "a:chunk:0",
            "a",
            0,
            "episode:a",
            "At the rare threshold the warning asked who would open the gate.",
            &pair,
        ),
        chunk(
            "b:chunk:0",
            "b",
            0,
            "episode:b",
            "At the rare threshold the answer arrived and opened the gate.",
            &pair,
        ),
        chunk(
            "c:chunk:0",
            "c",
            0,
            "episode:c",
            "The protagonist crossed another silent room.",
            &protagonist_only,
        ),
    ];

    let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        ..ChunkSemanticBridgeEngineInput::default()
    });
    let bridge = candidates
        .iter()
        .find(|bridge| {
            bridge.source_chunk_id == "a:chunk:0" && bridge.target_chunk_id == "b:chunk:0"
        })
        .expect("rare entity bridge");

    assert!(has(
        bridge,
        "primary_support_entity:location:rare-threshold"
    ));
    assert!(has(
        bridge,
        "support_role:incidental_registry_wide:character:protagonist"
    ));
    assert!(bridge
        .rationale
        .iter()
        .any(|row| row.starts_with("entity_frequency_receipt:location:rare-threshold|")));
}

#[test]
fn semantic_only_bridge_carries_explicit_support_role() {
    let chunks = vec![
        chunk(
            "a:chunk:0",
            "a",
            0,
            "episode:a",
            "The sealed warning asked who would open the gate.",
            &[],
        ),
        chunk(
            "b:chunk:0",
            "b",
            0,
            "episode:b",
            "At dawn the answer arrived and opened the gate.",
            &[],
        ),
    ];

    let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        ..ChunkSemanticBridgeEngineInput::default()
    });

    assert_eq!(candidates.len(), 1);
    assert!(has(&candidates[0], "support_role:semantic_only"));
    assert!(has(&candidates[0], "semantic_admission:passed"));
}

#[test]
fn max_min_selection_balances_available_primary_sponsors_registry_wide() {
    let sponsors = ["entity:alpha", "entity:beta", "entity:gamma"];
    let mut rows = Vec::new();
    for sponsor in sponsors {
        for index in 0..10 {
            rows.push(selection_candidate(sponsor, index));
        }
    }

    let selected = select_bridge_rows_fair(rows);
    let cross_document = selected
        .iter()
        .filter(|bridge| has(bridge, "cross_document_bridge"))
        .collect::<Vec<_>>();
    let mut counts = HashMap::<CompactString, usize>::new();
    for bridge in &cross_document {
        let sponsor = bridge
            .rationale
            .iter()
            .find_map(|row| row.strip_prefix("primary_support_entity:"))
            .unwrap();
        *counts.entry(sponsor.into()).or_default() += 1;
        assert!(has(bridge, "registry_max_min_selection:passed"));
    }

    assert_eq!(cross_document.len(), 24);
    assert_eq!(counts.len(), 3);
    assert!(counts.values().all(|count| *count == 8));
}

#[test]
fn promotion_consumes_the_same_frequency_support_receipt() {
    let protagonist = EntityId("character:protagonist".to_owned());
    let rare = EntityId("location:rare-threshold".to_owned());
    let pair = vec![protagonist.clone(), rare];
    let protagonist_only = vec![protagonist];
    let chunks = vec![
        chunk(
            "a:chunk:0",
            "a",
            0,
            "episode:a",
            "The warning asked who would open the gate.",
            &pair,
        ),
        chunk(
            "b:chunk:0",
            "b",
            0,
            "episode:b",
            "The answer arrived and opened the gate.",
            &pair,
        ),
        chunk(
            "c:chunk:0",
            "c",
            0,
            "episode:c",
            "The protagonist waited elsewhere.",
            &protagonist_only,
        ),
    ];
    let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
        chunks: &chunks,
        ..ChunkSemanticBridgeEngineInput::default()
    });
    let candidate = candidates
        .iter()
        .find(|bridge| {
            bridge.source_chunk_id == "a:chunk:0" && bridge.target_chunk_id == "b:chunk:0"
        })
        .unwrap()
        .clone();
    let promotion_chunks = [
        ChunkSemanticBridgePromotionChunk { id: "a:chunk:0" },
        ChunkSemanticBridgePromotionChunk { id: "b:chunk:0" },
    ];
    let accepted = ["a:chunk:0", "b:chunk:0"];
    let output = promote_chunk_semantic_bridge_candidates(ChunkSemanticBridgePromotionInput {
        candidates: std::slice::from_ref(&candidate),
        chunks: &promotion_chunks,
        accepted_evidence_ids: &accepted,
    });

    assert_eq!(output.audit.proposed, 1);
    assert!(output.proposals[0]
        .gate_receipts
        .iter()
        .any(|row| row == "entity_frequency_support_contract:passed"));
    assert!(output.proposals[0]
        .gate_receipts
        .iter()
        .any(|row| row == "registry_max_min_selection:passed"));
}

fn three_document_chunks<'a>(
    text: &'a str,
    entity_ids: &'a [EntityId],
) -> Vec<ChunkSemanticBridgeChunk<'a>> {
    vec![
        chunk("a:chunk:0", "a", 0, "episode:a", text, entity_ids),
        chunk("b:chunk:0", "b", 0, "episode:b", text, entity_ids),
        chunk("c:chunk:0", "c", 0, "episode:c", text, entity_ids),
    ]
}

fn chunk<'a>(
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

fn selection_candidate(sponsor: &str, index: usize) -> ChunkSemanticBridgeCandidate {
    ChunkSemanticBridgeCandidate {
        schema_version: CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION.into(),
        id: format_compact!("bridge:{sponsor}:{index}"),
        bridge_type: ChunkSemanticBridgeType::MotifEcho,
        source_chunk_id: format_compact!("a:chunk:{index}"),
        target_chunk_id: format_compact!("b:chunk:{index}"),
        source_event_id: None,
        target_event_id: None,
        source_episode_id: Some(format_compact!("episode:a:{index}")),
        target_episode_id: Some(format_compact!("episode:b:{index}")),
        claim: "fair selection fixture".into(),
        evidence_ids: vec![
            format_compact!("a:chunk:{index}"),
            format_compact!("b:chunk:{index}"),
        ],
        supporting_entity_ids: vec![sponsor.into()],
        confidence: 0.75,
        status: ChunkSemanticBridgeStatus::Candidate,
        commit_policy: ChunkSemanticBridgeCommitPolicy::NoTopologyCommit,
        semantic_verbs: vec!["echoes".into()],
        source_cue: Some("threshold".into()),
        target_cue: Some("threshold".into()),
        rationale: vec![
            CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT.into(),
            "cross_document_bridge".into(),
            "document_pair:a->b".into(),
            format_compact!("primary_support_entity:{sponsor}"),
            format_compact!("cross_document_budget_key:entity:{sponsor}"),
            "entity_frequency_profile:phoenix-chunk-semantic-bridge-entity-frequency/v1".into(),
        ],
    }
}

fn has(bridge: &ChunkSemanticBridgeCandidate, receipt: &str) -> bool {
    bridge.rationale.iter().any(|row| row == receipt)
}
