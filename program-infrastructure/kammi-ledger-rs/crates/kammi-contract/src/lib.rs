//! The amendment v4 contract (`ARCHITECTURE-AMENDMENT-v4-VAULT-WORKSPACE.md`), frozen in Phase 0.
//!
//! - [`time`]: `MemoryTimeV1`, Phoenix's six-clock envelope carried as JSON.
//! - [`workspace`]: the workspace event vocabulary and payload rules.
//! - [`verbs`]: the frozen shell ABI shared by the `kammi` CLI and MCP.
//!
//! Frozen, not active: nothing here is linked into `kammi-ledgerd`, and the journal's closed
//! registry (`kammi-v1`) accepts none of [`V4_EVENT_TYPES`] until the activation release.

pub mod time;
pub mod verbs;
pub mod workspace;

/// Every event type amendment v4 adds, sorted for binary search.
pub const V4_EVENT_TYPES: [&str; 16] = [
    "MemoryRecordedV2",
    "WorkspaceAgentAttached",
    "WorkspaceAgentDetached",
    "WorkspaceClosed",
    "WorkspaceCreated",
    "WorkspaceDecisionRecorded",
    "WorkspaceHandoffReceived",
    "WorkspaceHandoffSent",
    "WorkspaceNextStepSet",
    "WorkspaceNoteRecorded",
    "WorkspaceObjectiveSet",
    "WorkspacePinned",
    "WorkspaceQuestionOpened",
    "WorkspaceQuestionResolved",
    "WorkspaceScopeSet",
    "WorkspaceUnpinned",
];

/// Journals after v4: `main` and `memory` as in v1, plus the receipt stream (§4).
pub const JOURNALS: [&str; 3] = ["main", "memory", "receipts"];

pub fn is_v4_event_type(name: &str) -> bool {
    V4_EVENT_TYPES.binary_search(&name).is_ok()
}
