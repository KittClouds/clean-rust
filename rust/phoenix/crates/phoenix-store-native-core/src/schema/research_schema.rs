use super::{PhoenixColumnSpec, PhoenixColumnType};

const fn col(name: &'static str, ty: PhoenixColumnType, optional: bool, key: bool) -> PhoenixColumnSpec {
    PhoenixColumnSpec::new(name, ty, optional, key)
}

pub(super) const RESEARCH_RUNS: &[PhoenixColumnSpec] = &[
    col("id", PhoenixColumnType::String, false, true),
    col("chat_run_id", PhoenixColumnType::String, false, false),
    col("topic", PhoenixColumnType::String, false, false),
    col("phase", PhoenixColumnType::String, false, false),
    col("state_json", PhoenixColumnType::Json, false, false),
    col("cancel_requested", PhoenixColumnType::Bool, false, false),
    col("created_at", PhoenixColumnType::Int, false, false),
    col("updated_at", PhoenixColumnType::Int, false, false),
];

pub(super) const RESEARCH_QUERIES: &[PhoenixColumnSpec] = &[
    col("id", PhoenixColumnType::String, false, true),
    col("run_id", PhoenixColumnType::String, false, false),
    col("ordinal", PhoenixColumnType::Int, false, false),
    col("query", PhoenixColumnType::String, false, false),
    col("rationale", PhoenixColumnType::String, false, false),
    col("status", PhoenixColumnType::String, false, false),
    col("result_count", PhoenixColumnType::Int, false, false),
    col("created_at", PhoenixColumnType::Int, false, false),
];

pub(super) const RESEARCH_SOURCES: &[PhoenixColumnSpec] = &[
    col("id", PhoenixColumnType::String, false, true),
    col("run_id", PhoenixColumnType::String, false, false),
    col("url", PhoenixColumnType::String, false, false),
    col("canonical_url", PhoenixColumnType::String, false, false),
    col("title", PhoenixColumnType::String, false, false),
    col("excerpt", PhoenixColumnType::String, false, false),
    col("content_hash", PhoenixColumnType::String, false, false),
    col("artifact_key", PhoenixColumnType::String, false, false),
    col("fetched", PhoenixColumnType::Bool, false, false),
    col("fetch_status", PhoenixColumnType::Int, false, false),
    col("content_type", PhoenixColumnType::String, false, false),
    col("discovered_by_json", PhoenixColumnType::Json, false, false),
    col("created_at", PhoenixColumnType::Int, false, false),
    col("updated_at", PhoenixColumnType::Int, false, false),
];

pub(super) const RESEARCH_CLAIMS: &[PhoenixColumnSpec] = &[
    col("id", PhoenixColumnType::String, false, true),
    col("run_id", PhoenixColumnType::String, false, false),
    col("text", PhoenixColumnType::String, false, false),
    col("confidence_bps", PhoenixColumnType::Int, false, false),
    col("citation_ids_json", PhoenixColumnType::Json, false, false),
    col("verified", PhoenixColumnType::Bool, false, false),
    col("created_at", PhoenixColumnType::Int, false, false),
];

pub(super) const RESEARCH_CITATIONS: &[PhoenixColumnSpec] = &[
    col("id", PhoenixColumnType::String, false, true),
    col("run_id", PhoenixColumnType::String, false, false),
    col("claim_id", PhoenixColumnType::String, false, false),
    col("source_id", PhoenixColumnType::String, true, false),
    col("url", PhoenixColumnType::String, false, false),
    col("locator", PhoenixColumnType::String, false, false),
    col("quote_hash", PhoenixColumnType::String, false, false),
    col("structural_valid", PhoenixColumnType::Bool, false, false),
    col("link_valid", PhoenixColumnType::Bool, false, false),
    col("support_bps", PhoenixColumnType::Int, false, false),
];

pub(super) const RESEARCH_GAPS: &[PhoenixColumnSpec] = &[
    col("id", PhoenixColumnType::String, false, true),
    col("run_id", PhoenixColumnType::String, false, false),
    col("description", PhoenixColumnType::String, false, false),
    col("priority", PhoenixColumnType::Int, false, false),
    col("suggested_queries_json", PhoenixColumnType::Json, false, false),
    col("status", PhoenixColumnType::String, false, false),
    col("cycle", PhoenixColumnType::Int, false, false),
    col("created_at", PhoenixColumnType::Int, false, false),
];

pub(super) const RESEARCH_RECEIPTS: &[PhoenixColumnSpec] = &[
    col("id", PhoenixColumnType::String, false, true),
    col("run_id", PhoenixColumnType::String, false, false),
    col("status", PhoenixColumnType::String, false, false),
    col("receipt_json", PhoenixColumnType::Json, false, false),
    col("note_uri", PhoenixColumnType::String, true, false),
    col("created_at", PhoenixColumnType::Int, false, false),
];
