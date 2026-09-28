"""Library Lab owns authoritative event terms; clients cannot extend them."""
EVENT_TYPES = frozenset({
    "RunCreated", "AttemptStarted", "AttemptStopped", "AttemptCompleted", "ResultDeclared",
    "ArtifactRegistered", "SealCreated", "SealVerified", "PolicyRegistered", "SpecBound",
    "PolicyEvaluated", "AuthorizationIssued", "AuthorizationDenied", "ActorRegistered", "GrantIssued",
    "ExposureRequested", "ExposureDenied", "ExposureOpened", "ExposureClosed", "PanelRegistered",
    "ResourceRegistered", "LeaseRequested", "LeaseGranted", "LeaseDenied", "LeaseRenewed", "LeaseExpired", "LeaseReleased",
    "AdapterRegistered", "AdapterApplied", "WorkerKeyRegistered", "RemoteBundleCreated", "RemoteWorkerStarted",
    "RemoteWorkerReturned", "RemoteReceiptVerified", "MemoryRecorded", "MemorySuperseded", "MemoryRetrieved",
    "ProjectionRebuilt", "ReplayVerified", "ContactRecorded", "FactRecorded", "LibraryAccepted",
    "VaultCreated", "VaultSourceCommitted", "VaultGenerationSelected", "VaultReaderPositionSet",
    "VaultProductPrimarySelected",
})
EVENT_FIELDS = frozenset({"schema", "seq", "prev", "type", "payload_artifact", "actor", "request_id", "utc"})


def validate_event(event):
    if set(event) != EVENT_FIELDS or event["schema"] != "KAMMI_EVENT_V1" or event["type"] not in EVENT_TYPES:
        raise ValueError("event does not match registered custody vocabulary")
