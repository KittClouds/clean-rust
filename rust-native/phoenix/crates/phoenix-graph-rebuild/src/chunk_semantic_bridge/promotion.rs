use std::collections::BTreeMap;

use compact_str::{format_compact, CompactString};
use hashbrown::HashSet;

use super::{
    assert_chunk_semantic_bridge_candidate_only, bridge_quality_gate_decision,
    BridgeQualityGateDecision, ChunkSemanticBridgeCandidate, ChunkSemanticBridgePromotionAudit,
    ChunkSemanticBridgePromotionCommitPolicy, ChunkSemanticBridgePromotionInput,
    ChunkSemanticBridgePromotionOutput, ChunkSemanticBridgePromotionProposal,
    ChunkSemanticBridgePromotionRejection, ChunkSemanticBridgePromotionStatus,
    ChunkSemanticBridgeType, CHUNK_SEMANTIC_BRIDGE_PROMOTION_NO_TOPOLOGY_COMMIT,
    CHUNK_SEMANTIC_BRIDGE_PROMOTION_SCHEMA_VERSION,
};

pub fn promote_chunk_semantic_bridge_candidates(
    input: ChunkSemanticBridgePromotionInput<'_>,
) -> ChunkSemanticBridgePromotionOutput {
    let chunk_ids = input
        .chunks
        .iter()
        .map(|chunk| chunk.id)
        .collect::<HashSet<_>>();
    let accepted_evidence_ids = input
        .accepted_evidence_ids
        .iter()
        .copied()
        .collect::<HashSet<_>>();

    let mut proposals = Vec::new();
    let mut rejected = Vec::new();
    let mut by_rejection_reason = BTreeMap::<CompactString, usize>::new();

    for bridge in input.candidates {
        let decision = evaluate_bridge(bridge, &chunk_ids, &accepted_evidence_ids);
        if decision.reasons.is_empty() {
            proposals.push(build_proposal(bridge, decision.receipts, decision.score));
        } else {
            for reason in &decision.reasons {
                *by_rejection_reason.entry(reason.clone()).or_insert(0) += 1;
            }
            rejected.push(build_rejection(bridge, decision.reasons, decision.receipts));
        }
    }

    ChunkSemanticBridgePromotionOutput {
        schema_version: CHUNK_SEMANTIC_BRIDGE_PROMOTION_SCHEMA_VERSION.into(),
        source: "rust-deterministic-promotion/v1".into(),
        audit: ChunkSemanticBridgePromotionAudit {
            total: input.candidates.len(),
            proposed: proposals.len(),
            rejected: rejected.len(),
            by_rejection_reason,
        },
        proposals,
        rejected,
    }
}

struct PromotionDecision {
    reasons: Vec<CompactString>,
    receipts: Vec<CompactString>,
    score: f32,
}

fn evaluate_bridge(
    bridge: &ChunkSemanticBridgeCandidate,
    chunk_ids: &HashSet<&str>,
    accepted_evidence_ids: &HashSet<&str>,
) -> PromotionDecision {
    let mut reasons = Vec::new();
    let mut receipts = Vec::new();

    if let Err(error) = assert_chunk_semantic_bridge_candidate_only(std::slice::from_ref(bridge)) {
        reasons.push(format_compact!("candidate_contract_failed:{error}"));
    } else {
        receipts.push("candidate_contract:passed".into());
    }

    match bridge_quality_gate_decision(bridge) {
        BridgeQualityGateDecision::Accept => {
            receipts.push("semantic_support_guard:passed".into());
        }
        BridgeQualityGateDecision::DemoteSameEntityOnly => {
            reasons.push("same_entity_only_semantic_support".into());
        }
        BridgeQualityGateDecision::DemoteInsufficientSemanticEvidence => {
            reasons.push("insufficient_specific_semantic_evidence".into());
        }
    }

    gate_chunk(
        &mut reasons,
        &mut receipts,
        chunk_ids,
        "source",
        bridge.source_chunk_id.as_str(),
    );
    gate_chunk(
        &mut reasons,
        &mut receipts,
        chunk_ids,
        "target",
        bridge.target_chunk_id.as_str(),
    );
    gate_chunk_evidence(bridge, &mut reasons, &mut receipts);
    gate_accepted_evidence(bridge, accepted_evidence_ids, &mut reasons, &mut receipts);
    gate_frequency_support_contract(bridge, &mut reasons, &mut receipts);
    gate_type_semantics(bridge, &mut reasons, &mut receipts);
    gate_confidence(bridge, &mut reasons, &mut receipts);
    if bridge.semantic_verbs.is_empty() {
        reasons.push("missing_semantic_verbs".into());
    } else {
        receipts.push(format_compact!(
            "semantic_verbs:{}",
            bridge.semantic_verbs.len()
        ));
    }
    receipts.push(CHUNK_SEMANTIC_BRIDGE_PROMOTION_NO_TOPOLOGY_COMMIT.into());

    PromotionDecision {
        score: deterministic_score(bridge, reasons.is_empty()),
        reasons,
        receipts,
    }
}

fn gate_chunk(
    reasons: &mut Vec<CompactString>,
    receipts: &mut Vec<CompactString>,
    chunk_ids: &HashSet<&str>,
    side: &str,
    chunk_id: &str,
) {
    if chunk_ids.contains(chunk_id) {
        receipts.push(format_compact!("{side}_chunk_present"));
    } else {
        reasons.push(format_compact!("{side}_chunk_missing"));
    }
}

fn gate_chunk_evidence(
    bridge: &ChunkSemanticBridgeCandidate,
    reasons: &mut Vec<CompactString>,
    receipts: &mut Vec<CompactString>,
) {
    let source_seen = bridge
        .evidence_ids
        .iter()
        .any(|id| id == &bridge.source_chunk_id);
    let target_seen = bridge
        .evidence_ids
        .iter()
        .any(|id| id == &bridge.target_chunk_id);
    if source_seen && target_seen {
        receipts.push("source_target_chunk_evidence:present".into());
    } else {
        reasons.push("missing_source_target_chunk_evidence".into());
    }
}

fn gate_accepted_evidence(
    bridge: &ChunkSemanticBridgeCandidate,
    accepted_evidence_ids: &HashSet<&str>,
    reasons: &mut Vec<CompactString>,
    receipts: &mut Vec<CompactString>,
) {
    let accepted_count = bridge
        .evidence_ids
        .iter()
        .filter(|id| accepted_evidence_ids.contains(id.as_str()))
        .take(3)
        .count();
    if accepted_count >= 2 {
        receipts.push(format_compact!("accepted_evidence:{accepted_count}"));
    } else {
        reasons.push("insufficient_accepted_evidence".into());
    }
}

fn gate_type_semantics(
    bridge: &ChunkSemanticBridgeCandidate,
    reasons: &mut Vec<CompactString>,
    receipts: &mut Vec<CompactString>,
) {
    let required = required_rationale_prefix(bridge.bridge_type);
    if bridge.rationale.iter().any(|row| row.starts_with(required)) {
        receipts.push(format_compact!(
            "semantic_type_gate:{}:{required}",
            bridge.bridge_type.as_str()
        ));
    } else {
        reasons.push(format_compact!(
            "missing_type_semantic_support:{}",
            bridge.bridge_type.as_str()
        ));
    }
    let semantic_only = bridge
        .rationale
        .iter()
        .any(|row| row == "support_role:semantic_only")
        && bridge
            .rationale
            .iter()
            .any(|row| row == "semantic_admission:passed");
    if !semantic_only
        && bridge.supporting_entity_ids.len() < min_supporting_entities(bridge.bridge_type)
    {
        reasons.push(format_compact!(
            "insufficient_supporting_entities:{}",
            bridge.bridge_type.as_str()
        ));
    }
}

fn gate_frequency_support_contract(
    bridge: &ChunkSemanticBridgeCandidate,
    reasons: &mut Vec<CompactString>,
    receipts: &mut Vec<CompactString>,
) {
    if !bridge
        .rationale
        .iter()
        .any(|row| row == "cross_document_bridge")
    {
        return;
    }
    let profile = bridge
        .rationale
        .iter()
        .find(|row| row.starts_with("entity_frequency_profile:"));
    let primary = bridge
        .rationale
        .iter()
        .find(|row| row.starts_with("primary_support_entity:"));
    let specificity = bridge
        .rationale
        .iter()
        .find(|row| row.starts_with("primary_support_specificity_millis:"));
    let semantic_only = bridge
        .rationale
        .iter()
        .any(|row| row == "support_role:semantic_only");
    let fair_selection = bridge
        .rationale
        .iter()
        .any(|row| row == "registry_max_min_selection:passed");

    if profile.is_some() && (semantic_only || primary.is_some() && specificity.is_some()) {
        receipts.push("entity_frequency_support_contract:passed".into());
        if let Some(primary) = primary {
            receipts.push(primary.clone());
        }
        if let Some(specificity) = specificity {
            receipts.push(specificity.clone());
        }
    } else {
        reasons.push("entity_frequency_support_contract_missing".into());
    }
    if semantic_only
        && !bridge
            .rationale
            .iter()
            .any(|row| row == "semantic_admission:passed")
    {
        reasons.push("semantic_only_support_without_proof".into());
    }
    if fair_selection {
        receipts.push("registry_max_min_selection:passed".into());
    } else {
        reasons.push("registry_max_min_selection_receipt_missing".into());
    }
}

fn gate_confidence(
    bridge: &ChunkSemanticBridgeCandidate,
    reasons: &mut Vec<CompactString>,
    receipts: &mut Vec<CompactString>,
) {
    let floor = confidence_floor(bridge.bridge_type);
    if bridge.confidence >= floor {
        receipts.push(format_compact!("confidence_floor:{floor:.2}"));
    } else {
        reasons.push(format_compact!(
            "confidence_below_floor:{}:{:.2}",
            bridge.bridge_type.as_str(),
            floor
        ));
    }
}

fn build_proposal(
    bridge: &ChunkSemanticBridgeCandidate,
    gate_receipts: Vec<CompactString>,
    deterministic_score: f32,
) -> ChunkSemanticBridgePromotionProposal {
    ChunkSemanticBridgePromotionProposal {
        schema_version: CHUNK_SEMANTIC_BRIDGE_PROMOTION_SCHEMA_VERSION.into(),
        id: format_compact!("chunk_semantic_bridge_promotion:{}", bridge.id),
        source_bridge_id: bridge.id.clone(),
        bridge_type: bridge.bridge_type,
        source_chunk_id: bridge.source_chunk_id.clone(),
        target_chunk_id: bridge.target_chunk_id.clone(),
        source_episode_id: bridge.source_episode_id.clone(),
        target_episode_id: bridge.target_episode_id.clone(),
        claim: bridge.claim.clone(),
        evidence_ids: bridge.evidence_ids.clone(),
        supporting_entity_ids: bridge.supporting_entity_ids.clone(),
        semantic_verbs: bridge.semantic_verbs.clone(),
        source_confidence: bridge.confidence,
        deterministic_score,
        status: ChunkSemanticBridgePromotionStatus::PromotionProposed,
        commit_policy: ChunkSemanticBridgePromotionCommitPolicy::ProposalOnly,
        gate_receipts,
        rationale: vec![
            "deterministic_promotion_v1".into(),
            format_compact!("source_bridge_type:{}", bridge.bridge_type.as_str()),
            CHUNK_SEMANTIC_BRIDGE_PROMOTION_NO_TOPOLOGY_COMMIT.into(),
        ],
    }
}

fn build_rejection(
    bridge: &ChunkSemanticBridgeCandidate,
    reasons: Vec<CompactString>,
    gate_receipts: Vec<CompactString>,
) -> ChunkSemanticBridgePromotionRejection {
    ChunkSemanticBridgePromotionRejection {
        id: format_compact!("chunk_semantic_bridge_promotion_rejection:{}", bridge.id),
        source_bridge_id: bridge.id.clone(),
        bridge_type: bridge.bridge_type,
        source_confidence: bridge.confidence,
        status: ChunkSemanticBridgePromotionStatus::PromotionRejected,
        reasons,
        gate_receipts,
    }
}

fn deterministic_score(bridge: &ChunkSemanticBridgeCandidate, accepted: bool) -> f32 {
    if !accepted {
        return 0.0;
    }
    let evidence_bonus = (bridge.evidence_ids.len() as f32 * 0.005).min(0.04);
    (bridge.confidence + evidence_bonus).clamp(0.0, 0.97)
}

fn required_rationale_prefix(bridge_type: ChunkSemanticBridgeType) -> &'static str {
    match bridge_type {
        ChunkSemanticBridgeType::CauseEffect => "causal",
        ChunkSemanticBridgeType::SetupPayoff => "setup_cue_plus_later_payoff_cue",
        ChunkSemanticBridgeType::RouteContinuity => "route_or_threshold_cue_spans_chunks",
        ChunkSemanticBridgeType::EvidenceReframe => {
            "evidence_or_documentation_reframes_prior_chunk"
        }
        ChunkSemanticBridgeType::RelationshipDelta => "relationship_cue_with_shared_participants",
        ChunkSemanticBridgeType::StateDelta => "later_chunk_changes_prior_state",
        ChunkSemanticBridgeType::MotifEcho => "motif:",
        ChunkSemanticBridgeType::TopicContinuation => {
            "same_frame_or_event_type_with_shared_participants"
        }
    }
}

fn confidence_floor(bridge_type: ChunkSemanticBridgeType) -> f32 {
    match bridge_type {
        ChunkSemanticBridgeType::CauseEffect => 0.70,
        ChunkSemanticBridgeType::SetupPayoff => 0.74,
        ChunkSemanticBridgeType::RouteContinuity => 0.66,
        ChunkSemanticBridgeType::EvidenceReframe => 0.68,
        ChunkSemanticBridgeType::RelationshipDelta => 0.67,
        ChunkSemanticBridgeType::StateDelta => 0.65,
        ChunkSemanticBridgeType::MotifEcho => 0.62,
        ChunkSemanticBridgeType::TopicContinuation => 0.80,
    }
}

fn min_supporting_entities(bridge_type: ChunkSemanticBridgeType) -> usize {
    match bridge_type {
        ChunkSemanticBridgeType::RelationshipDelta => 2,
        _ => 1,
    }
}
