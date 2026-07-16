use super::*;

#[test]
fn promotes_deterministic_causal_candidate_as_proposal_only() {
    let bridge = promotion_candidate(
        ChunkSemanticBridgeType::CauseEffect,
        0.74,
        &["causes", "enables", "answers"],
        &["causal_event_edge_seed"],
        &["entity:kai", "entity:tempest"],
    );
    let chunks = promotion_chunks();
    let accepted = accepted_ids(&bridge);
    let output = promote_chunk_semantic_bridge_candidates(ChunkSemanticBridgePromotionInput {
        candidates: std::slice::from_ref(&bridge),
        chunks: &chunks,
        accepted_evidence_ids: &accepted,
    });

    assert_eq!(output.audit.total, 1);
    assert_eq!(output.audit.proposed, 1);
    assert_eq!(output.audit.rejected, 0);
    let proposal = &output.proposals[0];
    assert_eq!(
        proposal.schema_version,
        CHUNK_SEMANTIC_BRIDGE_PROMOTION_SCHEMA_VERSION
    );
    assert_eq!(
        proposal.commit_policy,
        ChunkSemanticBridgePromotionCommitPolicy::ProposalOnly
    );
    assert_eq!(
        proposal.status,
        ChunkSemanticBridgePromotionStatus::PromotionProposed
    );
    assert!(proposal
        .gate_receipts
        .iter()
        .any(|row| row == CHUNK_SEMANTIC_BRIDGE_PROMOTION_NO_TOPOLOGY_COMMIT));
    assert!(proposal.deterministic_score > bridge.confidence);
}

#[test]
fn rejects_candidates_without_accepted_evidence_or_semantic_support() {
    let mut weak = promotion_candidate(
        ChunkSemanticBridgeType::TopicContinuation,
        0.86,
        &["continues"],
        &["same_frame_or_event_type_with_shared_participants"],
        &["entity:kai"],
    );
    weak.source_cue = Some("dialogue_event".into());
    weak.target_cue = Some("dialogue_event".into());
    let chunks = promotion_chunks();
    let output = promote_chunk_semantic_bridge_candidates(ChunkSemanticBridgePromotionInput {
        candidates: std::slice::from_ref(&weak),
        chunks: &chunks,
        accepted_evidence_ids: &[],
    });

    assert_eq!(output.audit.total, 1);
    assert_eq!(output.audit.proposed, 0);
    assert_eq!(output.audit.rejected, 1);
    assert!(output
        .rejected
        .first()
        .expect("rejection")
        .reasons
        .iter()
        .any(|reason| reason == "insufficient_accepted_evidence"));
    assert!(output
        .rejected
        .first()
        .expect("rejection")
        .reasons
        .iter()
        .any(|reason| reason == "same_entity_only_semantic_support"));
}

#[test]
fn serializes_promotion_output_to_frontend_contract() {
    let bridge = promotion_candidate(
        ChunkSemanticBridgeType::SetupPayoff,
        0.78,
        &["sets_up", "pays_off", "answers"],
        &["setup_cue_plus_later_payoff_cue"],
        &["entity:kai"],
    );
    let chunks = promotion_chunks();
    let accepted = accepted_ids(&bridge);
    let output = promote_chunk_semantic_bridge_candidates(ChunkSemanticBridgePromotionInput {
        candidates: std::slice::from_ref(&bridge),
        chunks: &chunks,
        accepted_evidence_ids: &accepted,
    });
    let value = serde_json::to_value(&output).expect("promotion json");
    let proposal = &value["proposals"][0];

    assert_eq!(
        value["schemaVersion"],
        CHUNK_SEMANTIC_BRIDGE_PROMOTION_SCHEMA_VERSION
    );
    assert_eq!(value["source"], "rust-deterministic-promotion/v1");
    assert_eq!(proposal["status"], "promotion_proposed");
    assert_eq!(proposal["commitPolicy"], "proposal_only");
    assert_eq!(proposal["sourceBridgeId"], bridge.id.as_str());
    assert!(proposal["gateReceipts"]
        .as_array()
        .expect("receipts")
        .iter()
        .any(|row| row == CHUNK_SEMANTIC_BRIDGE_PROMOTION_NO_TOPOLOGY_COMMIT));
    assert!(!proposal
        .as_object()
        .expect("proposal")
        .contains_key("commit_policy"));
}

fn promotion_candidate(
    bridge_type: ChunkSemanticBridgeType,
    confidence: f32,
    semantic_verbs: &[&str],
    rationale: &[&str],
    supporting_entities: &[&str],
) -> ChunkSemanticBridgeCandidate {
    let mut full_rationale = vec![
        CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT.into(),
        format!("bridge_type:{}", bridge_type.as_str()).into(),
        format!("supporting_entities:{}", supporting_entities.len()).into(),
        "chunk_distance:2".into(),
    ];
    full_rationale.extend(rationale.iter().map(|row| (*row).into()));
    ChunkSemanticBridgeCandidate {
        schema_version: CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION.into(),
        id: format!(
            "chunk_semantic_bridge:{}:source:target",
            bridge_type.as_str()
        )
        .into(),
        bridge_type,
        source_chunk_id: "chunk:source".into(),
        target_chunk_id: "chunk:target".into(),
        source_event_id: Some("event:source".into()),
        target_event_id: Some("event:target".into()),
        source_episode_id: Some("episode:source".into()),
        target_episode_id: Some("episode:target".into()),
        claim: "Source chunk semantically supports target chunk.".into(),
        evidence_ids: vec![
            "chunk:source".into(),
            "chunk:target".into(),
            "event:source".into(),
            "event:target".into(),
        ],
        supporting_entity_ids: supporting_entities.iter().map(|id| (*id).into()).collect(),
        confidence,
        status: ChunkSemanticBridgeStatus::Candidate,
        commit_policy: ChunkSemanticBridgeCommitPolicy::NoTopologyCommit,
        semantic_verbs: semantic_verbs.iter().map(|verb| (*verb).into()).collect(),
        source_cue: Some("causal_edge".into()),
        target_cue: Some("causes_or_explains".into()),
        rationale: full_rationale,
    }
}

fn promotion_chunks() -> [ChunkSemanticBridgePromotionChunk<'static>; 2] {
    [
        ChunkSemanticBridgePromotionChunk { id: "chunk:source" },
        ChunkSemanticBridgePromotionChunk { id: "chunk:target" },
    ]
}

fn accepted_ids(bridge: &ChunkSemanticBridgeCandidate) -> Vec<&str> {
    bridge.evidence_ids.iter().map(|id| id.as_str()).collect()
}
