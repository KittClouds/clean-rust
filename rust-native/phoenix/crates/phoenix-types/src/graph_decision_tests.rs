use serde_json::json;
use smallvec::smallvec;

use super::*;

const DECIDED_AT: i64 = 1_720_000_000_000;

fn authority(kind: GraphDecisionAuthorityKind) -> GraphDecisionAuthority {
    GraphDecisionAuthority {
        authority_id: "authority-1".into(),
        kind,
        policy_id: "policy-1".into(),
        issued_at: DECIDED_AT - 20,
    }
}

fn approval() -> GraphDecisionApproval {
    GraphDecisionApproval {
        approval_id: "approval-1".into(),
        approver_id: "operator-1".into(),
        approved_at: DECIDED_AT - 10,
    }
}

fn header(
    kind: GraphDecisionAuthorityKind,
    approval: Option<GraphDecisionApproval>,
) -> GraphDecisionHeader {
    GraphDecisionHeader {
        schema_version: GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION,
        decision_id: "decision-1".into(),
        pre_state_id: "state-1".into(),
        decided_at: DECIDED_AT,
        authority: authority(kind),
        approval,
    }
}

fn evidence() -> GraphDecisionEvidence {
    smallvec![GraphDecisionEvidenceRef {
        evidence_id: "evidence-1".into(),
        authority_id: "source-1".into(),
        available_at: DECIDED_AT - 100,
    }]
}

#[test]
fn ontology_has_exactly_eleven_closed_action_contracts() {
    assert_eq!(GraphDecisionActionKind::ALL.len(), 11);
    for kind in GraphDecisionActionKind::ALL {
        let contract = kind.contract();
        assert_eq!(contract.kind, kind);
        assert!(!contract.required_parameters.is_empty());
        assert!(!contract.legal_preconditions.is_empty());
        assert!(!contract.deterministic_postconditions.is_empty());
        assert!(!contract.graph_invariants.is_empty());
        assert!(!contract.authority_requirements.is_empty());
        assert!(!contract.universal_rejection_reasons.is_empty());
        assert!(!contract.rejection_reasons.is_empty());
    }
}

#[test]
fn unknown_action_fails_closed() {
    let payload = json!({
        "kind": "do_whatever",
        "parameters": {}
    });
    assert!(matches!(
        decode_graph_decision_action(payload.to_string().as_bytes()),
        Err(GraphDecisionDecodeError::Malformed(_))
    ));
}

#[test]
fn unknown_parameter_fails_closed() {
    let payload = json!({
        "kind": "abstain",
        "parameters": {
            "header": header(GraphDecisionAuthorityKind::Policy, None),
            "taskId": "task-1",
            "candidateSetId": null,
            "reason": "insufficient_evidence",
            "evidence": [],
            "fallbackAction": "accept_delta"
        }
    });
    assert!(matches!(
        decode_graph_decision_action(payload.to_string().as_bytes()),
        Err(GraphDecisionDecodeError::Malformed(_))
    ));
}

#[test]
fn accept_delta_requires_evidence_and_human_approval() {
    let missing_approval = GraphDecisionAction::AcceptDelta(AcceptDeltaAction {
        header: header(GraphDecisionAuthorityKind::Operator, None),
        delta_id: "delta-1".into(),
        evidence: evidence(),
    });
    assert_eq!(
        missing_approval
            .validate()
            .expect_err("approval must be mandatory")
            .rejection_reason(),
        GraphDecisionRejectionReason::HumanApprovalRequired
    );
    missing_approval
        .validate_candidate()
        .expect("candidate validation must not require a future approval");

    let missing_evidence = GraphDecisionAction::AcceptDelta(AcceptDeltaAction {
        header: header(GraphDecisionAuthorityKind::Operator, Some(approval())),
        delta_id: "delta-1".into(),
        evidence: GraphDecisionEvidence::new(),
    });
    assert_eq!(
        missing_evidence
            .validate()
            .expect_err("evidence must be mandatory")
            .rejection_reason(),
        GraphDecisionRejectionReason::EvidenceRequired
    );
}

#[test]
fn future_evidence_is_rejected_before_action_execution() {
    let mut future = evidence();
    future[0].available_at = DECIDED_AT + 1;
    let action = GraphDecisionAction::ProposeRelation(ProposeRelationAction {
        header: header(GraphDecisionAuthorityKind::Compiler, None),
        proposal_id: "proposal-1".into(),
        source_id: "entity-1".into(),
        relation_type: "supports".into(),
        target_id: "entity-2".into(),
        evidence: future,
    });
    assert_eq!(
        action
            .validate()
            .expect_err("future evidence must fail closed")
            .rejection_reason(),
        GraphDecisionRejectionReason::EvidenceUnavailableAtDecision
    );
}

#[test]
fn authority_is_action_specific() {
    let action = GraphDecisionAction::RepairGraphRegion(RepairGraphRegionAction {
        header: header(GraphDecisionAuthorityKind::Compiler, Some(approval())),
        region_id: "region-1".into(),
        repair_delta_id: "delta-1".into(),
        evidence: evidence(),
    });
    assert_eq!(
        action
            .validate()
            .expect_err("compiler cannot authorize a graph repair")
            .rejection_reason(),
        GraphDecisionRejectionReason::AuthorityInsufficient
    );
}

#[test]
fn valid_action_round_trips_and_preserves_semantic_kind() {
    let action = GraphDecisionAction::AttachToEpisode(AttachToEpisodeAction {
        header: header(GraphDecisionAuthorityKind::Operator, Some(approval())),
        event_id: "event-1".into(),
        episode_id: "episode-1".into(),
        candidate_set_id: "candidates-1".into(),
        evidence: evidence(),
    });
    action.validate().expect("valid action");
    let bytes = serde_json::to_vec(&action).expect("serialize action");
    let decoded = decode_graph_decision_action(&bytes).expect("decode action");
    assert_eq!(decoded, action);
    assert_eq!(decoded.kind(), GraphDecisionActionKind::AttachToEpisode);
}

fn pending_reward_vector() -> GraphDecisionRewardVector {
    GraphDecisionRewardVector {
        schema_version: GRAPH_DECISION_REWARD_SCHEMA_VERSION,
        decision_id: "decision-1".into(),
        evidence_support: GraphDecisionRewardSignal::Pending,
        temporal_consistency: GraphDecisionRewardSignal::Pending,
        canonical_identity_preservation: GraphDecisionRewardSignal::Pending,
        contradiction_reduction: GraphDecisionRewardSignal::Pending,
        minimal_edit_cost: GraphDecisionRewardSignal::Pending,
        human_acceptance: GraphDecisionRewardSignal::Pending,
        future_stability: GraphDecisionRewardSignal::Pending,
        abstention_correctness: GraphDecisionRewardSignal::Pending,
    }
}

#[test]
fn reward_stays_an_eight_component_exact_vector() {
    let vector = pending_reward_vector();
    vector.validate().expect("pending vector is valid");
    assert_eq!(vector.dimensions().len(), 8);
    assert_eq!(GraphDecisionRewardDimension::ALL.len(), 8);
    assert!(std::mem::size_of::<GraphDecisionRewardVector>() <= 512);

    let encoded = serde_json::to_value(vector).expect("serialize reward vector");
    assert!(encoded.get("scalar").is_none());
    assert!(encoded.get("total").is_none());
    assert!(encoded.get("weights").is_none());
}

#[test]
fn reward_scores_use_bounded_fixed_point_not_floats() {
    let mut vector = pending_reward_vector();
    vector.evidence_support = GraphDecisionRewardSignal::Observed {
        score_micros: GRAPH_DECISION_REWARD_SCALE_MICROS + 1,
        observed_at: DECIDED_AT,
        evidence: evidence().into_vec(),
    };
    assert!(matches!(
        vector.validate(),
        Err(GraphDecisionRewardError::ScoreOutOfRange {
            dimension: GraphDecisionRewardDimension::EvidenceSupport,
            ..
        })
    ));
}
