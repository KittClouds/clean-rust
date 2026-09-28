//! The closed v1 event vocabulary (`ledgerd/vocabulary.py`).

/// Every event envelope has exactly these keys, listed in canonical order.
pub const EVENT_FIELDS: [&str; 8] = [
    "actor",
    "payload_artifact",
    "prev",
    "request_id",
    "schema",
    "seq",
    "type",
    "utc",
];

pub const EVENT_SCHEMA: &str = "KAMMI_EVENT_V1";

/// The 47 registered event types, sorted so membership is a binary search.
pub const EVENT_TYPES: [&str; 47] = [
    "ActorRegistered",
    "AdapterApplied",
    "AdapterRegistered",
    "ArtifactRegistered",
    "AttemptCompleted",
    "AttemptStarted",
    "AttemptStopped",
    "AuthorizationDenied",
    "AuthorizationIssued",
    "ContactRecorded",
    "ExposureClosed",
    "ExposureDenied",
    "ExposureOpened",
    "ExposureRequested",
    "FactRecorded",
    "GrantIssued",
    "LeaseDenied",
    "LeaseExpired",
    "LeaseGranted",
    "LeaseReleased",
    "LeaseRenewed",
    "LeaseRequested",
    "LibraryAccepted",
    "MemoryRecorded",
    "MemoryRetrieved",
    "MemorySuperseded",
    "PanelRegistered",
    "PolicyEvaluated",
    "PolicyRegistered",
    "ProjectionRebuilt",
    "RemoteBundleCreated",
    "RemoteReceiptVerified",
    "RemoteWorkerReturned",
    "RemoteWorkerStarted",
    "ReplayVerified",
    "ResourceRegistered",
    "ResultDeclared",
    "RunCreated",
    "SealCreated",
    "SealVerified",
    "SpecBound",
    "VaultCreated",
    "VaultGenerationSelected",
    "VaultProductPrimarySelected",
    "VaultReaderPositionSet",
    "VaultSourceCommitted",
    "WorkerKeyRegistered",
];

pub fn is_event_type(name: &str) -> bool {
    EVENT_TYPES.binary_search(&name).is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vocabulary_is_sorted_unique_and_complete() {
        assert!(EVENT_TYPES.windows(2).all(|pair| pair[0] < pair[1]));
        assert!(EVENT_FIELDS.windows(2).all(|pair| pair[0] < pair[1]));
        assert!(is_event_type("VaultSourceCommitted"));
        assert!(!is_event_type("WorkspaceCreated"));
    }
}
