use std::io::Write;
use std::time::{Duration, Instant};

use phoenix_store_native_core::{
    NativeDecisionReceiptAppend, PhoenixNativeDecisionStore, StoreError,
};
use phoenix_types::{
    certify_graph_decision_hard_constraints, certify_native_decision_outcome_receipt,
    certify_native_decision_receipt, certify_native_decision_reward_observation,
    graph_decision_action_identity, AttachToEpisodeAction, CreateEpisodeAction,
    GraphDecisionAction, GraphDecisionAuthority, GraphDecisionAuthorityKind,
    GraphDecisionEvidenceRef, GraphDecisionHardConstraintReceipt, GraphDecisionRewardDimension,
    GraphDecisionRewardSignal, GraphDecisionRewardVector, NativeDecisionAuthorityBridge,
    NativeDecisionAuthorityClass, NativeDecisionCandidateDisposition,
    NativeDecisionCandidateReceipt, NativeDecisionEffect, NativeDecisionOutcomeOperation,
    NativeDecisionOutcomeReceipt, NativeDecisionReceipt, NativeDecisionRewardObservationOperation,
    NativeDecisionRewardObservationReceipt, NativeDecisionTaskFamily,
    GRAPH_DECISION_HARD_CONSTRAINT_SCHEMA_VERSION, GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION,
    GRAPH_DECISION_REWARD_SCHEMA_VERSION, NATIVE_DECISION_OUTCOME_SCHEMA_VERSION,
    NATIVE_DECISION_RECEIPT_SCHEMA_VERSION, NATIVE_DECISION_REWARD_OBSERVATION_SCHEMA_VERSION,
};
use tempfile::tempdir;

use super::PhoenixOvergraphStore;

fn digest(byte: char) -> String {
    format!("b3-{}", byte.to_string().repeat(64))
}

fn authority() -> GraphDecisionAuthority {
    GraphDecisionAuthority {
        authority_id: "operator".into(),
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

pub(super) fn decision(index: u32) -> NativeDecisionReceipt {
    let decision_id = format!("decision-{index}");
    let pre_state = digest(char::from_digit(index.min(9), 10).unwrap_or('a'));
    let header = phoenix_types::GraphDecisionHeader {
        schema_version: GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION,
        decision_id: decision_id.as_str().into(),
        pre_state_id: pre_state.as_str().into(),
        decided_at: 100 + i64::from(index),
        authority: authority(),
        approval: None,
    };
    let attach = GraphDecisionAction::AttachToEpisode(AttachToEpisodeAction {
        header: header.clone(),
        event_id: format!("event-{index}").into(),
        episode_id: format!("episode-{index}").into(),
        candidate_set_id: digest('a').into(),
        evidence: [evidence()].into_iter().collect(),
    });
    let create = GraphDecisionAction::CreateEpisode(CreateEpisodeAction {
        header,
        event_id: format!("event-{index}").into(),
        episode_id: format!("new-episode-{index}").into(),
        candidate_set_id: digest('a').into(),
        evidence: [evidence()].into_iter().collect(),
    });
    let candidates = [
        (attach, NativeDecisionCandidateDisposition::Chosen),
        (create, NativeDecisionCandidateDisposition::Unselected),
    ]
    .into_iter()
    .map(|(action, disposition)| NativeDecisionCandidateReceipt {
        action_identity: graph_decision_action_identity(&action).expect("action identity"),
        action,
        disposition,
        counterfactual_role: None,
        source_labels: vec!["episode-generator".into()],
    })
    .collect();
    certify_native_decision_receipt(NativeDecisionReceipt {
        schema_version: NATIVE_DECISION_RECEIPT_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        decision_id: decision_id.as_str().into(),
        task_family: NativeDecisionTaskFamily::CanonicalEpisodeAssignment,
        scope_key: "workspace:hub".into(),
        lineage_ids: vec![format!("document-{index}").into()],
        observed_at: 100 + i64::from(index),
        label_available_at: 101 + i64::from(index),
        pre_state_snapshot_id: pre_state.into(),
        candidate_set_id: "pending".into(),
        generator_id: "episode-generator".into(),
        generator_version: "1".into(),
        generator_input_id: digest('b').into(),
        invalid_candidates_rejected: 0,
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
            source_state_receipt_id: digest('c').into(),
            bridged_at: 110 + i64::from(index),
        },
    })
    .expect("certify decision")
}

fn reward(decision_id: &str, observed_at: i64, score: i32) -> GraphDecisionRewardVector {
    let observed = || GraphDecisionRewardSignal::Observed {
        score_micros: score,
        observed_at,
        evidence: vec![evidence()],
    };
    GraphDecisionRewardVector {
        schema_version: GRAPH_DECISION_REWARD_SCHEMA_VERSION,
        decision_id: decision_id.into(),
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

pub(super) fn hard_constraints(observed_at: i64) -> GraphDecisionHardConstraintReceipt {
    certify_graph_decision_hard_constraints(GraphDecisionHardConstraintReceipt {
        schema_version: GRAPH_DECISION_HARD_CONSTRAINT_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        policy_id: "hard-constraints-v1".into(),
        evaluated_at: observed_at,
        passed: true,
        violations: Vec::new(),
    })
    .expect("hard constraints")
}

fn outcome(decision: &NativeDecisionReceipt, observed_at: i64) -> NativeDecisionOutcomeReceipt {
    certify_native_decision_outcome_receipt(NativeDecisionOutcomeReceipt {
        schema_version: NATIVE_DECISION_OUTCOME_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        decision_receipt_id: decision.receipt_id.clone(),
        decision_id: decision.decision_id.clone(),
        candidate_action_identity: decision.candidates[0].action_identity.clone(),
        operation: NativeDecisionOutcomeOperation::Observe,
        observed_at,
        authority_class: NativeDecisionAuthorityClass::AuthoritativeGraphOutcome,
        outcome_authority_id: "graph-truth-lineage".into(),
        reward_vector: Some(reward(&decision.decision_id, observed_at, 100_000)),
        hard_constraints: hard_constraints(observed_at),
        effect: Some(NativeDecisionEffect::GraphMutation {
            post_state_snapshot_id: digest('d').into(),
            before_delta_id: digest('e').into(),
            after_delta_id: digest('f').into(),
            graph_truth_commit_id: digest('9').into(),
        }),
        predecessor_outcome_receipt_id: None,
        evidence_anchors: vec![evidence()],
    })
    .expect("certify outcome")
}

fn reward_observation(
    decision: &NativeDecisionReceipt,
    observed_at: i64,
) -> NativeDecisionRewardObservationReceipt {
    certify_native_decision_reward_observation(NativeDecisionRewardObservationReceipt {
        schema_version: NATIVE_DECISION_REWARD_OBSERVATION_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        decision_receipt_id: decision.receipt_id.clone(),
        decision_id: decision.decision_id.clone(),
        candidate_action_identity: decision.candidates[0].action_identity.clone(),
        truth_link_id: digest('7').into(),
        graph_truth_commit_id: "commit:reward:1".into(),
        dimension: GraphDecisionRewardDimension::HumanAcceptance,
        operation: NativeDecisionRewardObservationOperation::Observe,
        score_micros: Some(1_000_000),
        observed_at,
        authority_class: NativeDecisionAuthorityClass::OperatorPreference,
        authority_id: "operator".into(),
        predecessor_observation_receipt_id: None,
        evidence_anchors: vec![GraphDecisionEvidenceRef {
            evidence_id: "operator-evaluation:1".into(),
            authority_id: "operator".into(),
            available_at: observed_at,
        }],
    })
    .expect("certify reward observation")
}

#[test]
fn immutable_decision_and_outcome_receipts_reopen_from_mmap_index() {
    let root = tempdir().expect("store root");
    let decision = decision(1);
    let outcome = outcome(&decision, 200);
    {
        let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
        assert!(matches!(
            store.append_native_decision_receipt(&decision),
            Ok(NativeDecisionReceiptAppend::Appended { .. })
        ));
        assert!(matches!(
            store.append_native_decision_receipt(&decision),
            Ok(NativeDecisionReceiptAppend::AlreadyPresent { .. })
        ));
        assert!(matches!(
            store.append_native_decision_outcome_receipt(&outcome),
            Ok(NativeDecisionReceiptAppend::Appended { .. })
        ));
    }
    let store = PhoenixOvergraphStore::open(root.path()).expect("reopen store");
    assert_eq!(
        store
            .load_native_decision_receipt(&decision.receipt_id)
            .expect("load decision"),
        Some(decision.clone())
    );
    assert_eq!(
        store
            .load_native_decision_receipt_by_decision_id(&decision.decision_id)
            .expect("load decision identity"),
        Some(decision.clone())
    );
    assert_eq!(
        store
            .load_native_decision_outcome_receipts(&decision.receipt_id)
            .expect("load outcomes"),
        vec![outcome]
    );
    assert_eq!(
        store.load_native_decision_receipts().unwrap(),
        vec![decision]
    );
}

#[test]
fn outcomes_require_an_existing_decision_and_extend_only_the_latest_receipt() {
    let root = tempdir().expect("store root");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    let decision = decision(1);
    let first = outcome(&decision, 200);
    assert!(matches!(
        store.append_native_decision_outcome_receipt(&first),
        Err(StoreError::Query(_))
    ));
    store
        .append_native_decision_receipt(&decision)
        .expect("append decision");
    store
        .append_native_decision_outcome_receipt(&first)
        .expect("append first outcome");
    let revision = certify_native_decision_outcome_receipt(NativeDecisionOutcomeReceipt {
        receipt_id: "pending".into(),
        operation: NativeDecisionOutcomeOperation::Revise,
        observed_at: 300,
        reward_vector: Some(reward(&decision.decision_id, 300, 200_000)),
        hard_constraints: hard_constraints(300),
        predecessor_outcome_receipt_id: Some(first.receipt_id.clone()),
        ..first.clone()
    })
    .expect("certify revision");
    store
        .append_native_decision_outcome_receipt(&revision)
        .expect("append revision");
    let fork = certify_native_decision_outcome_receipt(NativeDecisionOutcomeReceipt {
        receipt_id: "pending".into(),
        operation: NativeDecisionOutcomeOperation::Revise,
        observed_at: 400,
        reward_vector: Some(reward(&decision.decision_id, 400, 300_000)),
        hard_constraints: hard_constraints(400),
        predecessor_outcome_receipt_id: Some(first.receipt_id),
        ..first
    })
    .expect("certify fork fixture");
    assert!(matches!(
        store.append_native_decision_outcome_receipt(&fork),
        Err(StoreError::Query(_))
    ));
}

#[test]
fn checksum_corruption_fails_before_receipt_return() {
    let root = tempdir().expect("store root");
    let decision = decision(1);
    {
        let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
        store
            .append_native_decision_receipt(&decision)
            .expect("append decision");
    }
    let path = root.path().join("native-decision-receipts-v1.bin");
    let mut bytes = std::fs::read(&path).expect("read receipt log");
    let midpoint = bytes.len() / 2;
    bytes[midpoint] ^= 1;
    std::fs::write(path, bytes).expect("corrupt receipt log");
    let store = PhoenixOvergraphStore::open(root.path()).expect("reopen store");
    assert!(matches!(
        store.load_native_decision_receipts(),
        Err(StoreError::Snapshot(_))
    ));
}

#[test]
fn reward_observation_reopens_exactly_and_corruption_fails_before_return() {
    let root = tempdir().expect("store root");
    let decision = decision(1);
    let observation = reward_observation(&decision, 200);
    {
        let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
        store
            .append_native_decision_receipt(&decision)
            .expect("append decision");
        store
            .append_native_decision_reward_observation(&observation)
            .expect("append reward observation");
    }
    let reopened = PhoenixOvergraphStore::open(root.path()).expect("reopen store");
    assert_eq!(
        reopened
            .load_native_decision_reward_observations(&decision.receipt_id)
            .expect("load reward observations"),
        vec![observation]
    );
    drop(reopened);

    let path = root.path().join("native-decision-receipts-v1.bin");
    let mut bytes = std::fs::read(&path).expect("read receipt log");
    *bytes.last_mut().expect("non-empty receipt log") ^= 1;
    std::fs::write(path, bytes).expect("corrupt reward observation");
    let corrupted = PhoenixOvergraphStore::open(root.path()).expect("reopen corrupt store");
    assert!(matches!(
        corrupted.load_native_decision_reward_observations(&decision.receipt_id),
        Err(StoreError::Snapshot(_))
    ));
}

#[test]
fn incomplete_crash_tail_is_truncated_before_the_next_append() {
    let root = tempdir().expect("store root");
    let first = decision(1);
    {
        let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
        store
            .append_native_decision_receipt(&first)
            .expect("append first");
    }
    let path = root.path().join("native-decision-receipts-v1.bin");
    let valid_len = std::fs::metadata(&path).expect("metadata").len();
    let mut file = std::fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .expect("open crash tail");
    file.write_all(b"PHXN").expect("write crash tail");
    file.sync_all().expect("flush crash tail");
    drop(file);

    let store = PhoenixOvergraphStore::open(root.path()).expect("reopen store");
    assert_eq!(store.load_native_decision_receipts().unwrap(), vec![first]);
    store
        .append_native_decision_receipt(&decision(2))
        .expect("append after crash tail");
    assert!(std::fs::metadata(path).expect("metadata").len() > valid_len);
    assert_eq!(store.load_native_decision_receipts().unwrap().len(), 2);
}

#[test]
fn durable_append_and_restart_index_stay_within_receipt_smoke_gate() {
    const RECEIPTS: u32 = 128;
    let root = tempdir().expect("store root");
    let append_started = Instant::now();
    {
        let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
        for index in 1..=RECEIPTS {
            store
                .append_native_decision_receipt(&decision(index))
                .expect("append receipt");
        }
    }
    assert!(append_started.elapsed() < Duration::from_secs(30));
    let restart_started = Instant::now();
    let store = PhoenixOvergraphStore::open(root.path()).expect("reopen store");
    assert_eq!(
        store
            .load_native_decision_receipts()
            .expect("restart load")
            .len(),
        RECEIPTS as usize
    );
    assert!(restart_started.elapsed() < Duration::from_secs(5));
}
