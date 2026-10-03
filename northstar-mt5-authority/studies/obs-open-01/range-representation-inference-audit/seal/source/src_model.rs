use serde::Serialize;

pub const AUTHORITY: &str = "OBS_OPEN_03B_PREOPEN_INFERENCE_AUTHORITY_AUDIT_V1";
pub const PARENT_AUTHORITY: &str = "OBS_OPEN_03BP_FROZEN_RANGE_REPRESENTATION_TOURNAMENT_V1";
pub const PARENT_ROOT: &str = "6954d4a17d2c08c305031ade0e57c468ab90945da6e58839ee145a38b43e60b3";
pub const FINAL_STATE: &str = "INFERENCE_PROCEDURE_REQUIRES_REVISION";

#[derive(Debug, Clone, Serialize)]
pub struct ParentEvidence {
    pub member_count: usize,
    pub inference_contract_sha256: String,
    pub protocol_sha256: String,
    pub inference_contract: serde_json::Value,
    pub exact_word_occurrences: Vec<String>,
    pub sign_reflection_occurrences: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct FixtureReceipt {
    pub fixture_id: &'static str,
    pub status: &'static str,
    pub established: &'static str,
    pub witness: serde_json::Value,
    pub real_session_assumption_established: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct AuditFinding {
    pub finding_id: &'static str,
    pub source_kind: &'static str,
    pub state: &'static str,
    pub statement: &'static str,
    pub evidence: Vec<String>,
}
