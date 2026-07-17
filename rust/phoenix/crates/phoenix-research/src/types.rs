use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResearchPhase {
    #[default]
    Planning,
    Searching,
    GapAnalysis,
    Synthesizing,
    Verifying,
    AwaitingNoteProposal,
    Completed,
    Cancelled,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResearchBudget {
    pub max_searches: u32,
    pub max_fetches: u32,
    pub max_sources: u32,
    pub max_claims: u32,
    pub max_gap_cycles: u32,
    pub max_source_bytes: usize,
    pub max_total_source_bytes: usize,
    pub max_wall_ms: i64,
    pub minimum_coverage_bps: u16,
}

impl Default for ResearchBudget {
    fn default() -> Self {
        Self {
            max_searches: 12,
            max_fetches: 24,
            max_sources: 32,
            max_claims: 96,
            max_gap_cycles: 4,
            max_source_bytes: 256 * 1024,
            max_total_source_bytes: 2 * 1024 * 1024,
            max_wall_ms: 180_000,
            minimum_coverage_bps: 8_500,
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResearchUsage {
    pub searches: u32,
    pub fetches: u32,
    pub source_bytes: usize,
    pub gap_cycles: u32,
    pub synthesis_revisions: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct QueryRecord {
    pub id: String,
    pub ordinal: u32,
    pub query: String,
    pub rationale: String,
    pub status: String,
    pub result_count: usize,
    pub created_at: i64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SourceRecord {
    pub id: String,
    pub url: String,
    pub canonical_url: String,
    pub title: String,
    pub excerpt: String,
    pub content: String,
    pub content_hash: String,
    pub fetched: bool,
    pub fetch_status: u16,
    pub content_type: String,
    pub discovered_by: Vec<String>,
    pub created_at: i64,
    pub updated_at: i64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CitationInput {
    pub url: String,
    #[serde(default)]
    pub locator: String,
    #[serde(default)]
    pub quote: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ClaimInput {
    pub text: String,
    #[serde(default)]
    pub confidence_bps: u16,
    #[serde(default)]
    pub citations: Vec<CitationInput>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CitationRecord {
    pub id: String,
    pub claim_id: String,
    pub source_id: Option<String>,
    pub url: String,
    pub locator: String,
    pub quote: String,
    pub quote_hash: String,
    pub structural_valid: bool,
    pub link_valid: bool,
    pub support_bps: u16,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ClaimRecord {
    pub id: String,
    pub text: String,
    pub confidence_bps: u16,
    pub citation_ids: Vec<String>,
    pub verified: bool,
    pub created_at: i64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GapInput {
    pub description: String,
    #[serde(default)]
    pub priority: u8,
    #[serde(default)]
    pub suggested_queries: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GapRecord {
    pub id: String,
    pub description: String,
    pub priority: u8,
    pub suggested_queries: Vec<String>,
    pub status: String,
    pub cycle: u32,
    pub created_at: i64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VerificationIssue {
    pub code: String,
    pub claim_id: Option<String>,
    pub citation_id: Option<String>,
    pub detail: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VerificationReport {
    pub passed: bool,
    pub claim_count: usize,
    pub verified_claim_count: usize,
    pub citation_count: usize,
    pub verified_citation_count: usize,
    pub coverage_bps: u16,
    pub issues: Vec<VerificationIssue>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResearchReceipt {
    pub schema_version: String,
    pub run_id: String,
    pub phase: ResearchPhase,
    pub stop_reason: Option<String>,
    pub searches: u32,
    pub fetches: u32,
    pub source_count: usize,
    pub claim_count: usize,
    pub gap_cycles: u32,
    pub coverage_bps: u16,
    pub elapsed_ms: i64,
    pub created_at: i64,
}
