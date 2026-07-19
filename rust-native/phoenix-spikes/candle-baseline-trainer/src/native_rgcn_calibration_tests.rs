use super::*;
use phoenix_types::{
    certify_native_decision_receipt, graph_decision_action_identity, AttachToEpisodeAction,
    CreateEpisodeAction, GraphDecisionAction, GraphDecisionAuthority, GraphDecisionAuthorityKind,
    GraphDecisionEvidenceRef, GraphDecisionHeader, NativeDecisionAuthorityBridge,
    NativeDecisionAuthorityClass, NativeDecisionCandidateDisposition,
    NativeDecisionCandidateReceipt, NativeDecisionReceipt, NativeDecisionTaskFamily,
    GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION, NATIVE_DECISION_RECEIPT_SCHEMA_VERSION,
};

#[test]
fn receipt_calibration_is_deterministic_and_permanently_non_promotable() {
    let first_root = tempfile::tempdir().expect("first output");
    let second_root = tempfile::tempdir().expect("second output");
    let decisions = (0..12)
        .map(|index| decision(index, (index % 2) as usize))
        .collect::<Vec<_>>();
    let status = NativeRgcnCohortStatus {
        outcome_receipts: decisions.len() as u64,
        mature_trajectories: 0,
    };
    let mut request = request(first_root.path(), decisions.len());
    let first = train_native_rgcn_calibration(decisions.clone(), status, &request)
        .expect("first calibration");
    request.output_root = second_root.path().to_path_buf();
    let second =
        train_native_rgcn_calibration(decisions, status, &request).expect("second calibration");

    assert_eq!(first.cohort_blake3, second.cohort_blake3);
    assert_eq!(first.weights_blake3, second.weights_blake3);
    assert_eq!(first.score_blake3, second.score_blake3);
    assert!(first.restart_score_bits_exact);
    assert_eq!(first.epoch_allocation_volume_bytes, 0);
    assert_eq!(first.epoch_allocation_count, 0);
    assert!(first.gradient_arena_bytes > first.weights_bytes);
    assert!(!first.promotion_eligible);
    assert_eq!(
        first.evaluation_split,
        "train-rescore-only; temporal-validation-unavailable"
    );
    assert!(first
        .promotion_locks
        .iter()
        .any(|lock| lock == "zero-mature-trajectories"));
    assert!(first
        .promotion_locks
        .iter()
        .any(|lock| lock == "train-only-rescore-is-not-validation"));
}

#[test]
fn calibration_rejects_a_partial_receipt_or_outcome_census() {
    let root = tempfile::tempdir().expect("output");
    let decisions = vec![decision(1, 0), decision(2, 1)];
    let error = train_native_rgcn_calibration(
        decisions,
        NativeRgcnCohortStatus {
            outcome_receipts: 1,
            mature_trajectories: 0,
        },
        &request(root.path(), 2),
    )
    .expect_err("partial outcomes must fail");
    assert!(error.to_string().contains("exact receipt/outcome census"));
}

fn request(root: &std::path::Path, expected_receipts: usize) -> NativeRgcnCalibrationRequest {
    NativeRgcnCalibrationRequest {
        store_path: root.join("unused-store"),
        output_root: root.to_path_buf(),
        expected_receipts,
        seed: 0x7605_eed5_1ce5_2026,
        config: CandleRgcnConfig {
            epochs: 6,
            learning_rate: 0.03,
            l2: 0.0001,
        },
    }
}

fn decision(index: u32, chosen: usize) -> NativeDecisionReceipt {
    let decision_id = format!("decision-{index}");
    let observed_at = 1_000 + i64::from(index);
    let authority = authority();
    let header = GraphDecisionHeader {
        schema_version: GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION,
        decision_id: decision_id.as_str().into(),
        pre_state_id: digest('1').into(),
        decided_at: observed_at,
        authority: authority.clone(),
        approval: None,
    };
    let evidence = evidence(observed_at - 1);
    let actions = [
        GraphDecisionAction::AttachToEpisode(AttachToEpisodeAction {
            header: header.clone(),
            event_id: format!("event-{index}").into(),
            episode_id: format!("episode-{index}").into(),
            candidate_set_id: digest('2').into(),
            evidence: [evidence.clone()].into_iter().collect(),
        }),
        GraphDecisionAction::CreateEpisode(CreateEpisodeAction {
            header,
            event_id: format!("event-{index}").into(),
            episode_id: format!("new-episode-{index}").into(),
            candidate_set_id: digest('2').into(),
            evidence: [evidence.clone()].into_iter().collect(),
        }),
    ];
    let candidates = actions
        .into_iter()
        .enumerate()
        .map(|(ordinal, action)| NativeDecisionCandidateReceipt {
            action_identity: graph_decision_action_identity(&action).expect("action identity"),
            action,
            disposition: if ordinal == chosen {
                NativeDecisionCandidateDisposition::Chosen
            } else {
                NativeDecisionCandidateDisposition::Unselected
            },
            counterfactual_role: None,
            source_labels: vec!["episode-generator".into()],
        })
        .collect();
    certify_native_decision_receipt(NativeDecisionReceipt {
        schema_version: NATIVE_DECISION_RECEIPT_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        decision_id: decision_id.into(),
        task_family: NativeDecisionTaskFamily::CanonicalEpisodeAssignment,
        scope_key: "workspace:test".into(),
        lineage_ids: vec!["frozen-source".into()],
        observed_at,
        label_available_at: observed_at + 1,
        pre_state_snapshot_id: digest('1').into(),
        candidate_set_id: "pending".into(),
        generator_id: "episode-generator".into(),
        generator_version: "1".into(),
        generator_input_id: digest('3').into(),
        invalid_candidates_rejected: 0,
        generation_latency_ns: 1,
        allocation_volume_bytes: 0,
        candidates,
        chosen_candidate_ordinal: chosen as u32,
        authority,
        authority_class: NativeDecisionAuthorityClass::OperatorPreference,
        evidence_anchors: vec![evidence],
        bridge: NativeDecisionAuthorityBridge {
            source_authority_id: "desktop-runtime".into(),
            research_authority_id: "native-store".into(),
            source_state_receipt_id: digest('4').into(),
            bridged_at: observed_at + 1,
        },
    })
    .expect("decision receipt")
}

fn authority() -> GraphDecisionAuthority {
    GraphDecisionAuthority {
        authority_id: "operator".into(),
        kind: GraphDecisionAuthorityKind::Operator,
        policy_id: "operator-policy".into(),
        issued_at: 900,
    }
}

fn evidence(available_at: i64) -> GraphDecisionEvidenceRef {
    GraphDecisionEvidenceRef {
        evidence_id: format!("evidence-{available_at}").into(),
        authority_id: "source-ledger".into(),
        available_at,
    }
}

fn digest(byte: char) -> String {
    format!("b3-{}", byte.to_string().repeat(64))
}
