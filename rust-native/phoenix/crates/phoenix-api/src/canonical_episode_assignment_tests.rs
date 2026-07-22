use phoenix_store_native_core::{PhoenixGraphKernelStoreV2, PhoenixNativeDecisionStore};
use tempfile::tempdir;

use super::*;
use crate::native_decision_census;

#[test]
fn selection_payload_uses_the_desktop_camel_case_contract() {
    let selection: CanonicalEpisodeAssignmentSelection = serde_json::from_value(
        serde_json::json!({ "kind": "attach_to_episode", "episodeId": "episode:1" }),
    )
    .expect("decode desktop selection");
    assert_eq!(
        selection,
        CanonicalEpisodeAssignmentSelection::AttachToEpisode {
            episode_id: "episode:1".to_owned(),
        }
    );
}

#[test]
fn accepted_episode_assignment_freezes_candidates_before_canonical_commit() {
    let root = tempdir().expect("episode assignment store");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    let request = request("snapshot:episode:1", "episode:1", 100);

    let response = commit_canonical_episode_assignment(&store, request.clone())
        .expect("commit canonical episode assignment");
    assert_eq!(
        response.commit_status,
        CanonicalEpisodeAssignmentCommitStatus::Appended
    );
    assert_eq!(response.candidate_count, 4);
    assert!(response.decision_appended);
    assert!(response.outcome_appended);
    assert_eq!(response.graph_truth_generation, Some(1));

    let decisions = store
        .load_native_decision_receipts()
        .expect("load decisions");
    assert_eq!(decisions.len(), 1);
    assert_eq!(
        decisions[0].task_family,
        NativeDecisionTaskFamily::CanonicalEpisodeAssignment
    );
    assert_eq!(
        decisions[0].candidates[decisions[0].chosen_candidate_ordinal as usize].counterfactual_role,
        Some(NativeDecisionCounterfactualRole::RecordedAction)
    );
    assert!(decisions[0]
        .candidates
        .iter()
        .any(|candidate| candidate.counterfactual_role
            == Some(NativeDecisionCounterfactualRole::SafeAbstention)));

    let outcomes = store
        .load_native_decision_outcome_receipts(&response.decision_receipt_id)
        .expect("load outcome");
    assert_eq!(outcomes.len(), 1);
    assert!(matches!(
        outcomes[0].effect,
        Some(NativeDecisionEffect::GraphMutation { .. })
    ));

    let commits = store
        .load_graph_truth_commits()
        .expect("load canonical commits");
    assert_eq!(commits.len(), 1);
    assert_eq!(commits[0].batch.vertices.len(), 2);
    assert_eq!(commits[0].batch.edges.len(), 1);
    assert_eq!(commits[0].batch.edges[0].source_id.0, "episode:1");
    assert_eq!(commits[0].batch.edges[0].target_id.0, "event:1");
    assert!(commits[0]
        .header
        .receipt_ids
        .contains(&decisions[0].receipt_id));
    assert!(commits[0]
        .header
        .receipt_ids
        .contains(&response.operator_mutation_receipt_id.as_str().into()));

    let reward = store
        .load_native_decision_reward_evidence_for_decision(&response.decision_receipt_id)
        .expect("load canonical reward");
    assert_eq!(reward.len(), 1);
    assert_eq!(
        crate::native_reward_observation_census(&store)
            .expect("pending reward census")
            .pending_canonical_episode_horizons,
        1
    );
    store
        .reconcile_canonical_reward_producers(
            100 + phoenix_types::CANONICAL_REWARD_STABILITY_HORIZON_MS,
        )
        .expect("mature canonical reward");
    let rewards = crate::native_reward_observation_census(&store).expect("reward census");
    assert_eq!(rewards.mature_canonical_episode_assignments, 1);
    assert_eq!(rewards.positive_canonical_episode_stability, 1);
    assert_eq!(rewards.negative_canonical_episode_stability, 0);
    assert_eq!(rewards.pending_canonical_episode_horizons, 0);
    let census = native_decision_census(&store).expect("decision census");
    assert_eq!(census.behavior_labels, 1);
    assert_eq!(census.canonical_episode_assignment_labels, 1);
    assert_eq!(census.canonical_episode_attach_labels, 1);
    assert_eq!(census.canonical_episode_candidate_count_total, 4);
    assert_eq!(census.canonical_episode_candidate_count_min, 4);
    assert_eq!(census.canonical_episode_candidate_count_max, 4);
    assert_eq!(census.canonical_episode_first_observed_at, Some(100));
    assert_eq!(census.canonical_episode_last_observed_at, Some(100));
    assert_eq!(census.execution_outcomes, 1);
    assert_eq!(census.graph_truth_linked_decisions, 1);
}

#[test]
fn restart_retry_reuses_the_exact_decision_outcome_and_commit() {
    let root = tempdir().expect("retry store");
    let first = {
        let store = PhoenixOvergraphStore::open(root.path()).expect("open first store");
        commit_canonical_episode_assignment(
            &store,
            request("snapshot:episode:retry", "episode:1", 100),
        )
        .expect("first commit")
    };
    let store = PhoenixOvergraphStore::open(root.path()).expect("restart store");
    let retry = commit_canonical_episode_assignment(
        &store,
        request("snapshot:episode:retry", "episode:1", 500),
    )
    .expect("retry commit");
    assert_eq!(
        retry.commit_status,
        CanonicalEpisodeAssignmentCommitStatus::AlreadyPresent
    );
    assert!(!retry.decision_appended);
    assert!(!retry.outcome_appended);
    assert_eq!(retry.decision_receipt_id, first.decision_receipt_id);
    assert_eq!(retry.outcome_receipt_id, first.outcome_receipt_id);
    assert_eq!(retry.graph_truth_commit_id, first.graph_truth_commit_id);
    assert_eq!(
        store
            .load_native_decision_receipts()
            .expect("decisions")
            .len(),
        1
    );
    assert_eq!(store.load_graph_truth_commits().expect("commits").len(), 1);
}

#[test]
fn conflicting_episode_membership_fails_before_recording_a_second_label() {
    let root = tempdir().expect("conflict store");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    commit_canonical_episode_assignment(
        &store,
        request("snapshot:episode:conflict:1", "episode:1", 100),
    )
    .expect("first membership");

    let error = commit_canonical_episode_assignment(
        &store,
        request("snapshot:episode:conflict:2", "episode:2", 200),
    )
    .expect_err("conflicting membership must fail");
    assert!(error
        .to_string()
        .contains("event already has a different canonical episode"));
    assert_eq!(
        store
            .load_native_decision_receipts()
            .expect("decisions")
            .len(),
        1
    );
}

#[test]
fn candidate_contract_cannot_smuggle_topology_authority() {
    let root = tempdir().expect("candidate guard store");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    let mut request = request("snapshot:episode:guard", "episode:1", 100);
    request.event.no_topology_commit = false;
    let error = commit_canonical_episode_assignment(&store, request)
        .expect_err("candidate authority guard");
    assert!(error.to_string().contains("request contract"));
    assert!(store
        .load_native_decision_receipts()
        .expect("decision receipts")
        .is_empty());
    assert!(store
        .load_graph_truth_commits()
        .expect("canonical commits")
        .is_empty());
}

#[test]
fn operator_can_override_the_compiler_with_an_active_compatible_episode() {
    let root = tempdir().expect("override store");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    let response = commit_canonical_episode_assignment(
        &store,
        request("snapshot:episode:override", "episode:2", 100),
    )
    .expect("commit override");
    assert_eq!(response.chosen_action_kind, "attach_to_episode");
    let commits = store.load_graph_truth_commits().expect("commits");
    assert_eq!(commits[0].batch.edges[0].source_id.0, "episode:2");
}

#[test]
fn create_episode_is_a_deterministic_canonical_mutation() {
    let root = tempdir().expect("create store");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    let mut input = request("snapshot:episode:create", "episode:1", 100);
    input.selected_action = CanonicalEpisodeAssignmentSelection::CreateEpisode;
    let response = commit_canonical_episode_assignment(&store, input).expect("create episode");
    assert_eq!(response.chosen_action_kind, "create_episode");
    let commits = store.load_graph_truth_commits().expect("commits");
    assert_eq!(commits.len(), 1);
    assert_eq!(commits[0].batch.vertices.len(), 2);
    assert!(commits[0].batch.edges[0].source_id.0.starts_with("b3-"));
}

#[test]
fn abstention_records_the_real_choice_without_mutating_graph_truth() {
    let root = tempdir().expect("abstain store");
    let store = PhoenixOvergraphStore::open(root.path()).expect("open store");
    let mut input = request("snapshot:episode:abstain", "episode:1", 100);
    input.selected_action = CanonicalEpisodeAssignmentSelection::Abstain;
    let response = commit_canonical_episode_assignment(&store, input).expect("abstain");
    assert_eq!(response.chosen_action_kind, "abstain");
    assert_eq!(
        response.commit_status,
        CanonicalEpisodeAssignmentCommitStatus::NoChange
    );
    assert!(response.graph_truth_commit_id.is_none());
    assert!(store
        .load_graph_truth_commits()
        .expect("commits")
        .is_empty());
    let outcomes = store
        .load_native_decision_outcome_receipts(&response.decision_receipt_id)
        .expect("outcomes");
    assert!(matches!(
        outcomes[0].effect,
        Some(NativeDecisionEffect::NoChange { .. })
    ));
}

fn request(
    snapshot_id: &str,
    selected_episode_id: &str,
    decided_at: i64,
) -> CanonicalEpisodeAssignmentCommitRequest {
    CanonicalEpisodeAssignmentCommitRequest {
        schema_version: CANONICAL_EPISODE_ASSIGNMENT_COMMIT_SCHEMA.to_owned(),
        scope_key: "scope:episode-tests".to_owned(),
        source_snapshot_id: snapshot_id.to_owned(),
        source_snapshot_built_at: 90,
        source_authority_content_hash: "authority:episode-tests".to_owned(),
        event: NativeEpisodeAssignmentEvent {
            id: "event:1".to_owned(),
            note_id: "note:1".to_owned(),
            chunk_id: "chunk:1".to_owned(),
            source_start: 10,
            source_end: 20,
            predicate: "arrives".to_owned(),
            participant_entity_ids: vec!["entity:1".to_owned()],
            evidence_ids: vec!["evidence:event:1".to_owned()],
            factuality: "asserted".to_owned(),
            confidence_millis: 900,
            no_topology_commit: true,
        },
        episodes: vec![
            episode("episode:1", "First", 0, 30, true),
            episode("episode:2", "Second", 31, 60, true),
        ],
        selected_action: CanonicalEpisodeAssignmentSelection::AttachToEpisode {
            episode_id: selected_episode_id.to_owned(),
        },
        decided_at,
        operator_id: "operator:local-user".to_owned(),
    }
}

fn episode(
    id: &str,
    label: &str,
    source_start: u32,
    source_end: u32,
    include_event: bool,
) -> NativeEpisodeAssignmentEpisode {
    NativeEpisodeAssignmentEpisode {
        id: id.to_owned(),
        note_id: "note:1".to_owned(),
        label: label.to_owned(),
        source_start,
        source_end,
        chunk_ids: vec![format!("chunk:{id}")],
        event_ids: include_event
            .then(|| "event:1".to_owned())
            .into_iter()
            .collect(),
        entity_ids: vec!["entity:1".to_owned()],
        boundary_receipt_ids: vec![format!("boundary:{id}")],
        confidence_millis: 850,
        status: "candidate".to_owned(),
        no_topology_commit: true,
    }
}
