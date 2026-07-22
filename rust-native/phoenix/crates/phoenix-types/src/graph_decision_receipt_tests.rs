use super::*;
use crate::{
    AbstainAction, AttachToEpisodeAction, CreateEpisodeAction, GraphDecisionAbstentionReason,
    GraphDecisionAuthorityKind, LinkEvidenceAction, RepairGraphRegionAction,
    GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION, GRAPH_DECISION_REWARD_SCHEMA_VERSION,
};

fn digest(byte: char) -> CompactString {
    format!("b3-{}", byte.to_string().repeat(64)).into()
}

fn authority() -> GraphDecisionAuthority {
    GraphDecisionAuthority {
        authority_id: "operator-1".into(),
        kind: GraphDecisionAuthorityKind::Operator,
        policy_id: "decision-policy-v1".into(),
        issued_at: 80,
    }
}

fn evidence() -> GraphDecisionEvidenceRef {
    GraphDecisionEvidenceRef {
        evidence_id: "evidence-1".into(),
        authority_id: "source-ledger".into(),
        available_at: 90,
    }
}

fn header() -> crate::GraphDecisionHeader {
    crate::GraphDecisionHeader {
        schema_version: GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION,
        decision_id: "decision-1".into(),
        pre_state_id: digest('a'),
        decided_at: 100,
        authority: authority(),
        approval: None,
    }
}

fn candidate(
    role: NativeDecisionCounterfactualRole,
    action: GraphDecisionAction,
    disposition: NativeDecisionCandidateDisposition,
) -> NativeDecisionCandidateReceipt {
    NativeDecisionCandidateReceipt {
        action_identity: graph_decision_action_identity(&action).expect("action identity"),
        action,
        disposition,
        counterfactual_role: Some(role),
        source_labels: vec!["grammar-constrained-generator".into()],
    }
}

fn decision() -> NativeDecisionReceipt {
    let evidence_rows = [evidence()];
    let make_evidence = || evidence_rows.iter().cloned().collect();
    let candidates = vec![
        candidate(
            NativeDecisionCounterfactualRole::RecordedAction,
            GraphDecisionAction::AttachToEpisode(AttachToEpisodeAction {
                header: header(),
                event_id: "event-1".into(),
                episode_id: "episode-1".into(),
                candidate_set_id: digest('b'),
                evidence: make_evidence(),
            }),
            NativeDecisionCandidateDisposition::Chosen,
        ),
        candidate(
            NativeDecisionCounterfactualRole::HardPlausibleAlternative,
            GraphDecisionAction::CreateEpisode(CreateEpisodeAction {
                header: header(),
                event_id: "event-1".into(),
                episode_id: "episode-new".into(),
                candidate_set_id: digest('b'),
                evidence: make_evidence(),
            }),
            NativeDecisionCandidateDisposition::Unselected,
        ),
        candidate(
            NativeDecisionCounterfactualRole::SafeAbstention,
            GraphDecisionAction::Abstain(AbstainAction {
                header: header(),
                task_id: "episode-assignment".into(),
                candidate_set_id: Some(digest('b')),
                reason: GraphDecisionAbstentionReason::AmbiguousCandidates,
                evidence: make_evidence(),
            }),
            NativeDecisionCandidateDisposition::Unselected,
        ),
        candidate(
            NativeDecisionCounterfactualRole::MinimalRepair,
            GraphDecisionAction::RepairGraphRegion(RepairGraphRegionAction {
                header: header(),
                region_id: "region-minimal".into(),
                repair_delta_id: digest('c'),
                evidence: make_evidence(),
            }),
            NativeDecisionCandidateDisposition::Unselected,
        ),
        candidate(
            NativeDecisionCounterfactualRole::AggressiveRepair,
            GraphDecisionAction::RepairGraphRegion(RepairGraphRegionAction {
                header: header(),
                region_id: "region-aggressive".into(),
                repair_delta_id: digest('d'),
                evidence: make_evidence(),
            }),
            NativeDecisionCandidateDisposition::Unselected,
        ),
        candidate(
            NativeDecisionCounterfactualRole::EvidenceRichAlternative,
            GraphDecisionAction::LinkEvidence(LinkEvidenceAction {
                header: header(),
                claim_id: "claim-1".into(),
                evidence: make_evidence(),
            }),
            NativeDecisionCandidateDisposition::Unselected,
        ),
        candidate(
            NativeDecisionCounterfactualRole::TemporallyAttractiveInvalidAlternative,
            GraphDecisionAction::AttachToEpisode(AttachToEpisodeAction {
                header: header(),
                event_id: "event-1".into(),
                episode_id: "future-episode".into(),
                candidate_set_id: digest('b'),
                evidence: make_evidence(),
            }),
            NativeDecisionCandidateDisposition::Rejected,
        ),
    ];
    certify_native_decision_receipt(NativeDecisionReceipt {
        schema_version: NATIVE_DECISION_RECEIPT_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        decision_id: "decision-1".into(),
        task_family: NativeDecisionTaskFamily::CanonicalEpisodeAssignment,
        scope_key: "workspace:hub".into(),
        lineage_ids: vec!["document-1".into(), "episode-lineage-1".into()],
        observed_at: 100,
        label_available_at: 101,
        pre_state_snapshot_id: digest('a'),
        candidate_set_id: "pending".into(),
        generator_id: "episode-candidate-generator".into(),
        generator_version: "1".into(),
        generator_input_id: digest('e'),
        invalid_candidates_rejected: 1,
        generation_latency_ns: 1,
        allocation_volume_bytes: 0,
        candidates,
        chosen_candidate_ordinal: 0,
        authority: authority(),
        authority_class: NativeDecisionAuthorityClass::OperatorPreference,
        evidence_anchors: vec![evidence()],
        bridge: NativeDecisionAuthorityBridge {
            source_authority_id: "desktop-runtime".into(),
            research_authority_id: "native-graph-store".into(),
            source_state_receipt_id: digest('f'),
            bridged_at: 102,
        },
    })
    .expect("certify decision receipt")
}

fn reward(score: i32, observed_at: i64) -> GraphDecisionRewardVector {
    let observed = || GraphDecisionRewardSignal::Observed {
        score_micros: score,
        observed_at,
        evidence: vec![evidence()],
    };
    GraphDecisionRewardVector {
        schema_version: GRAPH_DECISION_REWARD_SCHEMA_VERSION,
        decision_id: "decision-1".into(),
        evidence_support: observed(),
        temporal_consistency: observed(),
        canonical_identity_preservation: observed(),
        contradiction_reduction: observed(),
        minimal_edit_cost: observed(),
        human_acceptance: observed(),
        future_stability: observed(),
        abstention_correctness: observed(),
    }
}

fn hard_constraints(observed_at: i64, passed: bool) -> GraphDecisionHardConstraintReceipt {
    certify_graph_decision_hard_constraints(GraphDecisionHardConstraintReceipt {
        schema_version: GRAPH_DECISION_HARD_CONSTRAINT_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        policy_id: "hard-constraint-policy-v1".into(),
        evaluated_at: observed_at,
        passed,
        violations: if passed {
            Vec::new()
        } else {
            vec![GraphDecisionHardConstraintViolation::FutureInformation]
        },
    })
    .expect("certify hard constraints")
}

fn outcome(
    decision: &NativeDecisionReceipt,
    ordinal: usize,
    observed_at: i64,
) -> NativeDecisionOutcomeReceipt {
    let candidate = &decision.candidates[ordinal];
    let passed = candidate.counterfactual_role
        != Some(NativeDecisionCounterfactualRole::TemporallyAttractiveInvalidAlternative);
    certify_native_decision_outcome_receipt(NativeDecisionOutcomeReceipt {
        schema_version: NATIVE_DECISION_OUTCOME_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        decision_receipt_id: decision.receipt_id.clone(),
        decision_id: decision.decision_id.clone(),
        candidate_action_identity: candidate.action_identity.clone(),
        operation: NativeDecisionOutcomeOperation::Observe,
        observed_at,
        authority_class: NativeDecisionAuthorityClass::AuthoritativeGraphOutcome,
        outcome_authority_id: "outcome-tribunal".into(),
        reward_vector: Some(reward(100_000 - ordinal as i32, observed_at)),
        hard_constraints: hard_constraints(observed_at, passed),
        effect: Some(NativeDecisionEffect::NoChange {
            post_state_snapshot_id: digest('9'),
        }),
        predecessor_outcome_receipt_id: None,
        evidence_anchors: vec![evidence()],
    })
    .expect("certify outcome")
}

#[test]
fn decision_receipt_freezes_exact_prestate_ordered_candidates_and_authority_bridge() {
    let decision = decision();
    decision.validate().expect("validate decision");
    assert!(decision.counterfactual_complete());
    assert_eq!(
        decision.candidates[0].disposition,
        NativeDecisionCandidateDisposition::Chosen
    );
    assert_eq!(
        native_decision_candidate_set_identity(&decision.candidates).expect("candidate set"),
        decision.candidate_set_id
    );
    let mut forged = decision.clone();
    forged.observed_at += 1;
    assert_eq!(
        forged.validate(),
        Err(NativeDecisionReceiptError::InvalidCandidate(0))
    );
}

#[test]
fn complete_outcome_lineages_resolve_latest_without_backfill() {
    let decision = decision();
    let mut outcomes = decision
        .candidates
        .iter()
        .enumerate()
        .map(|(ordinal, _)| outcome(&decision, ordinal, 200))
        .collect::<Vec<_>>();
    let first = outcomes[0].clone();
    outcomes.push(
        certify_native_decision_outcome_receipt(NativeDecisionOutcomeReceipt {
            receipt_id: "pending".into(),
            operation: NativeDecisionOutcomeOperation::Revise,
            observed_at: 300,
            reward_vector: Some(reward(500_000, 300)),
            hard_constraints: hard_constraints(300, true),
            predecessor_outcome_receipt_id: Some(first.receipt_id.clone()),
            ..first.clone()
        })
        .expect("certify revision"),
    );
    let resolved = resolve_complete_native_decision_outcomes(&decision, &outcomes, 300)
        .expect("resolve complete outcomes");
    assert_eq!(resolved.len(), 7);
    assert_eq!(
        resolved[0].outcome.operation,
        NativeDecisionOutcomeOperation::Revise
    );

    let incomplete = &outcomes[..6];
    assert!(matches!(
        resolve_complete_native_decision_outcomes(&decision, incomplete, 300),
        Err(NativeDecisionReceiptError::MissingCandidateOutcome(_))
    ));

    let simultaneous_revision =
        certify_native_decision_outcome_receipt(NativeDecisionOutcomeReceipt {
            receipt_id: "pending".into(),
            operation: NativeDecisionOutcomeOperation::Revise,
            observed_at: first.observed_at,
            predecessor_outcome_receipt_id: Some(first.receipt_id.clone()),
            ..first
        })
        .expect("certify simultaneous revision");
    let mut non_monotonic = outcomes[1..].to_vec();
    non_monotonic.push(simultaneous_revision);
    assert_eq!(
        resolve_complete_native_decision_outcomes(&decision, &non_monotonic, 300),
        Err(NativeDecisionReceiptError::BrokenOutcomeLineage)
    );
}

#[test]
fn compiler_inference_and_pending_reward_cannot_become_outcomes() {
    let decision = decision();
    let mut candidate = outcome(&decision, 0, 200);
    candidate.receipt_id = "pending".into();
    candidate.authority_class = NativeDecisionAuthorityClass::CompilerInference;
    assert_eq!(
        certify_native_decision_outcome_receipt(candidate),
        Err(NativeDecisionReceiptError::InvalidOutcomeContract)
    );

    let mut candidate = outcome(&decision, 0, 200);
    candidate.receipt_id = "pending".into();
    candidate
        .reward_vector
        .as_mut()
        .expect("reward")
        .future_stability = GraphDecisionRewardSignal::Pending;
    assert_eq!(
        certify_native_decision_outcome_receipt(candidate),
        Err(NativeDecisionReceiptError::IncompleteReward)
    );

    let mut censored = outcome(&decision, 0, 200);
    censored.receipt_id = "pending".into();
    censored.reward_vector = None;
    let censored = certify_native_decision_outcome_receipt(censored)
        .expect("execution-only outcome remains durable but censored");
    let mut outcomes = decision
        .candidates
        .iter()
        .enumerate()
        .map(|(ordinal, _)| outcome(&decision, ordinal, 200))
        .collect::<Vec<_>>();
    outcomes[0] = censored;
    assert_eq!(
        resolve_complete_native_decision_outcomes(&decision, &outcomes, 200),
        Err(NativeDecisionReceiptError::IncompleteReward)
    );
}
