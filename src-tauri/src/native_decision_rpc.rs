use std::path::Path;

use phoenix_graph_api::{
    begin_native_operator_decision, certify_native_decision_graph_truth_link,
    commit_canonical_episode_assignment, complete_native_operator_decision, native_decision_census,
    native_reward_observation_census, record_native_reward_observation,
    CanonicalEpisodeAssignmentCommitRequest, NativeDecisionGraphTruthLinkRequest,
    NativeOperatorDecisionBeginRequest, NativeOperatorDecisionCompleteRequest,
    NativeRewardObservationRequest,
};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use serde::de::DeserializeOwned;
use serde::Serialize;

pub fn begin(store_path: &Path, request_json: &str) -> Result<String, String> {
    let store = open_store(store_path)?;
    let request = parse::<NativeOperatorDecisionBeginRequest>(request_json)?;
    encode(&begin_native_operator_decision(&store, request).map_err(decision_error)?)
}

pub fn complete(store_path: &Path, request_json: &str) -> Result<String, String> {
    let store = open_store(store_path)?;
    let request = parse::<NativeOperatorDecisionCompleteRequest>(request_json)?;
    encode(&complete_native_operator_decision(&store, request).map_err(decision_error)?)
}

pub fn commit_episode_assignment(store_path: &Path, request_json: &str) -> Result<String, String> {
    let store = open_store(store_path)?;
    let request = parse::<CanonicalEpisodeAssignmentCommitRequest>(request_json)?;
    encode(
        &commit_canonical_episode_assignment(&store, request).map_err(|error| error.to_string())?,
    )
}

pub fn census(store_path: &Path) -> Result<String, String> {
    let store = open_store(store_path)?;
    encode(&native_decision_census(&store).map_err(decision_error)?)
}

pub fn link_graph_truth(store_path: &Path, request_json: &str) -> Result<String, String> {
    let store = open_store(store_path)?;
    let request = parse::<NativeDecisionGraphTruthLinkRequest>(request_json)?;
    encode(&certify_native_decision_graph_truth_link(&store, request).map_err(decision_error)?)
}

pub fn record_reward_observation(store_path: &Path, request_json: &str) -> Result<String, String> {
    let store = open_store(store_path)?;
    let request = parse::<NativeRewardObservationRequest>(request_json)?;
    encode(&record_native_reward_observation(&store, request).map_err(reward_error)?)
}

pub fn reward_observation_census(store_path: &Path) -> Result<String, String> {
    let store = open_store(store_path)?;
    encode(&native_reward_observation_census(&store).map_err(reward_error)?)
}

pub fn observe_reward_horizons(store_path: &Path) -> Result<String, String> {
    let store = open_store(store_path)?;
    encode(
        &store
            .reconcile_canonical_reward_producers(now_ms())
            .map_err(|error| error.to_string())?,
    )
}

fn open_store(path: &Path) -> Result<PhoenixOvergraphStore, String> {
    PhoenixOvergraphStore::open(path)
        .map_err(|error| format!("open native decision receipt store: {error}"))
}

fn parse<T: DeserializeOwned>(json: &str) -> Result<T, String> {
    serde_json::from_str(json).map_err(|error| format!("parse native decision request: {error}"))
}

fn encode<T: Serialize>(value: &T) -> Result<String, String> {
    serde_json::to_string(value)
        .map_err(|error| format!("encode native decision response: {error}"))
}

fn decision_error(error: phoenix_graph_api::NativeOperatorDecisionError) -> String {
    error.to_string()
}

fn reward_error(error: phoenix_graph_api::NativeRewardObservationApiError) -> String {
    error.to_string()
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Value};
    use tempfile::tempdir;

    use super::*;

    #[test]
    fn json_rpc_sequence_reopens_the_store_and_reports_one_censored_behavior_label() {
        let root = tempdir().expect("decision RPC store");
        let request = json!({
            "schemaVersion": "phoenix-native-operator-decision-begin/v1",
            "scopeKey": "scope:rpc",
            "sourceSnapshotId": "snapshot:rpc:1",
            "sourceSnapshotBuiltAt": 90,
            "sourceAuthorityContentHash": "authority:rpc:1",
            "targetObjectId": "fact:rpc:1",
            "targetObjectKind": "graph_fact_candidate",
            "sourceFingerprint": "fingerprint:rpc:1",
            "sourceReceiptIds": ["source:rpc:1"],
            "previousState": "proposed",
            "availableDecisions": ["accepted", "rejected"],
            "selectedDecision": "accepted",
            "decidedAt": 100,
            "operatorId": "operator:local-user"
        });
        let begin_value: Value = serde_json::from_str(
            &begin(root.path(), &request.to_string()).expect("begin JSON RPC"),
        )
        .expect("decode begin response");
        assert_eq!(begin_value["appended"], true);
        assert_eq!(begin_value["candidateCount"], 3);

        let retry_value: Value = serde_json::from_str(
            &begin(root.path(), &request.to_string()).expect("retry begin JSON RPC"),
        )
        .expect("decode retry response");
        assert_eq!(retry_value["appended"], false);
        assert_eq!(
            retry_value["decisionReceiptId"],
            begin_value["decisionReceiptId"]
        );

        let completion = json!({
            "schemaVersion": "phoenix-native-operator-decision-complete/v1",
            "decisionId": begin_value["decisionId"],
            "decisionReceiptId": begin_value["decisionReceiptId"],
            "postSnapshotId": "snapshot:rpc:2",
            "postSnapshotBuiltAt": 101,
            "postAuthorityContentHash": "authority:rpc:2",
            "operatorMutationReceiptId": "operator-receipt:rpc:1",
            "completedAt": 101,
            "outcomeAuthorityId": "operator:local-user",
            "applied": true
        });
        let complete_value: Value = serde_json::from_str(
            &complete(root.path(), &completion.to_string()).expect("complete JSON RPC"),
        )
        .expect("decode complete response");
        assert_eq!(complete_value["appended"], true);
        assert_eq!(complete_value["rewardReady"], false);

        let census_value: Value =
            serde_json::from_str(&census(root.path()).expect("census JSON RPC"))
                .expect("decode census response");
        assert_eq!(census_value["behaviorLabels"], 1);
        assert_eq!(census_value["executionOutcomes"], 1);
        assert_eq!(census_value["rewardCensoredOutcomes"], 1);
        assert_eq!(census_value["rewardCompleteOutcomes"], 0);
        assert_eq!(census_value["counterfactualReadyDecisions"], 0);
        assert_eq!(census_value["graphTruthLinkedDecisions"], 0);

        let reward_census: Value = serde_json::from_str(
            &reward_observation_census(root.path()).expect("reward census JSON RPC"),
        )
        .expect("decode reward census response");
        assert_eq!(reward_census["observationReceipts"], 0);
        assert_eq!(reward_census["partiallyObservedDecisions"], 0);
        assert_eq!(reward_census["fullyObservedDecisions"], 0);

        let observer: Value = serde_json::from_str(
            &observe_reward_horizons(root.path()).expect("reward horizon observer"),
        )
        .expect("decode reward horizon report");
        assert_eq!(
            observer["schemaVersion"],
            "phoenix-canonical-reward-producer-report/v1"
        );
        assert_eq!(observer["humanObservationsAppended"], 0);
        assert_eq!(observer["stabilityObservationsAppended"], 0);
    }

    #[test]
    fn episode_assignment_rpc_commits_the_selected_candidate_and_reward_lineage() {
        let root = tempdir().expect("episode RPC store");
        let request = json!({
            "schemaVersion": "phoenix-canonical-episode-assignment-commit/v1",
            "scopeKey": "scope:episode-rpc",
            "sourceSnapshotId": "snapshot:episode-rpc:1",
            "sourceSnapshotBuiltAt": 90,
            "sourceAuthorityContentHash": "authority:episode-rpc:1",
            "event": {
                "id": "event:rpc:1",
                "noteId": "note:rpc:1",
                "chunkId": "chunk:rpc:1",
                "sourceStart": 10,
                "sourceEnd": 20,
                "predicate": "arrives",
                "participantEntityIds": ["entity:rpc:1"],
                "evidenceIds": ["evidence:rpc:1"],
                "factuality": "asserted",
                "confidenceMillis": 900,
                "noTopologyCommit": true
            },
            "episodes": [{
                "id": "episode:rpc:1",
                "noteId": "note:rpc:1",
                "label": "Arrival",
                "sourceStart": 0,
                "sourceEnd": 30,
                "chunkIds": ["chunk:rpc:1"],
                "eventIds": ["event:rpc:1"],
                "entityIds": ["entity:rpc:1"],
                "boundaryReceiptIds": ["boundary:rpc:1"],
                "confidenceMillis": 850,
                "status": "candidate",
                "noTopologyCommit": true
            }],
            "selectedAction": { "kind": "attach_to_episode", "episodeId": "episode:rpc:1" },
            "decidedAt": 100,
            "operatorId": "operator:local-user"
        });
        let value: Value = serde_json::from_str(
            &commit_episode_assignment(root.path(), &request.to_string())
                .expect("episode assignment RPC"),
        )
        .expect("decode response");
        assert_eq!(value["commitStatus"], "appended");
        assert_eq!(value["chosenActionKind"], "attach_to_episode");
        assert_eq!(value["candidateCount"], 3);
        let census: Value =
            serde_json::from_str(&census(root.path()).expect("census")).expect("decode census");
        assert_eq!(census["behaviorLabels"], 1);
        assert_eq!(census["canonicalEpisodeAssignmentLabels"], 1);
        assert_eq!(census["canonicalEpisodeAttachLabels"], 1);
        assert_eq!(census["graphTruthLinkedDecisions"], 1);
    }
}
