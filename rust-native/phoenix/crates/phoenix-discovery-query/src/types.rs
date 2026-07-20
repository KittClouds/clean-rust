use crate::{QueryLimits, QueryMode, SeedChannelReceipt};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct QueryStableId {
    pub hash: u64,
    pub collision: u16,
}

#[derive(Clone, Debug)]
pub struct PreparedQueryRequest<'a> {
    pub query: &'a str,
    pub query_vector: Option<&'a [f32]>,
    pub narrative_time: Option<i64>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BudgetExhaustion {
    pub seed_candidates: bool,
    pub ppr_vertices: bool,
    pub ppr_edges: bool,
    pub total_edges: bool,
    pub beam_width: bool,
    pub fanout: bool,
    pub returned_paths: bool,
    pub evidence: bool,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PruningCounters {
    pub seed_candidates: u32,
    pub ppr_vertices: u32,
    pub edge_scan: u32,
    pub zero_quality_edges: u32,
    pub fanout_neighbors: u32,
    pub cycle_states: u32,
    pub beam_states: u32,
    pub path_candidates: u32,
    pub evidence_refs: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CancellationPhase {
    SeedResolution,
    Ppr,
    Beam,
    Selection,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CancellationReceipt {
    pub checks: u32,
    pub requested: bool,
    pub observed: bool,
    pub phase: Option<CancellationPhase>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SignalContribution {
    pub available: bool,
    pub value_micros: i64,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PathScoreReceipt {
    pub seed_relevance: SignalContribution,
    pub local_ppr_importance: SignalContribution,
    pub evidence_quality: SignalContribution,
    pub normalized_asserted_confidence: SignalContribution,
    pub bridge_strength: SignalContribution,
    pub community_affinity: SignalContribution,
    pub cross_community_novelty: SignalContribution,
    pub temporal_relevance: SignalContribution,
    pub model_frontier_boost: SignalContribution,
    pub common_relation_penalty: SignalContribution,
    pub path_length_penalty: SignalContribution,
    pub selected_path_redundancy: SignalContribution,
    pub final_score_micros: i64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EdgeReceipt {
    pub dense_edge: u32,
    pub identity: QueryStableId,
    pub relation_code: u16,
    pub confidence_micros: u32,
    pub evidence: Vec<QueryStableId>,
    pub evidence_truncated: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveryPath {
    pub dense_nodes: Vec<u32>,
    pub node_identities: Vec<QueryStableId>,
    pub edges: Vec<EdgeReceipt>,
    pub terminal_community: Option<QueryStableId>,
    pub score: PathScoreReceipt,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PreparedQueryReceipt {
    pub generation: u64,
    pub source_snapshot_id: String,
    pub source_snapshot_digest: String,
    pub evidence_registry_digest: String,
    pub discovery_digest: String,
    pub discovery_payload_digest: String,
    pub community_digest: String,
    pub community_payload_digest: String,
    pub community_policy_id: String,
    pub community_policy_version: String,
    pub community_policy_digest: String,
    pub relation_policy_digest: String,
    pub score_policy_id: String,
    pub score_policy_version: String,
    pub score_policy_digest: String,
    pub limits_digest: String,
    pub mode: QueryMode,
    pub limits: QueryLimits,
    pub lexical_candidates: u32,
    pub vector_candidates: u32,
    pub invalid_seed_candidates: u32,
    pub lexical_seed_receipt: SeedChannelReceipt,
    pub vector_seed_receipt: SeedChannelReceipt,
    pub seed_receipt_digest: String,
    pub resolved_seeds: u32,
    pub ppr_visited_vertices: u32,
    pub ppr_pushes: u32,
    pub ppr_examined_edges: u32,
    pub beam_states: u32,
    pub beam_examined_edges: u32,
    pub total_examined_edges: u32,
    pub returned_paths: u32,
    pub exhaustion: BudgetExhaustion,
    pub pruning: PruningCounters,
    pub cancellation: CancellationReceipt,
    pub admitted_candidate_edges: u64,
    pub topology_writes: u32,
    pub fallback_used: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PreparedQueryResponse {
    pub paths: Vec<DiscoveryPath>,
    pub receipt: PreparedQueryReceipt,
}
