use phoenix_discovery_query::{
    BudgetExhaustion, CancellationReceipt, DiscoveryPath, PathScoreReceipt, PreparedQueryReceipt,
    PruningCounters, QueryLimits, QueryMode, SignalContribution,
};
use serde::{Deserialize, Serialize};

pub(crate) const PATH_RECEIPT_SCHEMA: &str = "phoenix-discovery-path-receipt/v1";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveryPathAuthority {
    pub graph_generation: u64,
    pub source_snapshot_id: String,
    pub source_snapshot_digest: String,
    pub evidence_registry_digest: String,
    pub discovery_artifact_digest: String,
    pub discovery_payload_digest: String,
    pub community_artifact_digest: String,
    pub community_payload_digest: String,
    pub relation_policy_digest: String,
    pub community_policy_digest: String,
    pub score_policy_digest: String,
    pub limits_digest: String,
    pub seed_receipt_digest: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveryPathExecution {
    pub mode: QueryMode,
    pub limits: QueryLimits,
    pub pruning: PruningCounters,
    pub exhaustion: BudgetExhaustion,
    pub cancellation: CancellationReceipt,
    pub lexical_seed_truncated: bool,
    pub vector_seed_truncated: bool,
    pub ppr_visited_vertices: u32,
    pub ppr_pushes: u32,
    pub ppr_examined_edges: u32,
    pub beam_states: u32,
    pub beam_examined_edges: u32,
    pub total_examined_edges: u32,
    pub fallback_used: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveryPathReceipt {
    pub schema_version: String,
    pub receipt_id: String,
    pub query_digest: String,
    pub canonical_path_digest: String,
    pub authority: DiscoveryPathAuthority,
    pub path: DiscoveryPath,
    pub execution: DiscoveryPathExecution,
    pub candidate_only: bool,
    pub asserted_edges_traversed: u32,
    pub candidate_edges_traversed: u32,
    pub topology_writes: u32,
}

pub(crate) fn build_path_receipt(
    query_digest: &str,
    path: &DiscoveryPath,
    query: &PreparedQueryReceipt,
) -> Result<DiscoveryPathReceipt, Box<dyn std::error::Error>> {
    let mut receipt = DiscoveryPathReceipt {
        schema_version: PATH_RECEIPT_SCHEMA.to_owned(),
        receipt_id: "pending".to_owned(),
        query_digest: query_digest.to_owned(),
        canonical_path_digest: canonical_path_digest(path),
        authority: DiscoveryPathAuthority {
            graph_generation: query.generation,
            source_snapshot_id: query.source_snapshot_id.clone(),
            source_snapshot_digest: query.source_snapshot_digest.clone(),
            evidence_registry_digest: query.evidence_registry_digest.clone(),
            discovery_artifact_digest: query.discovery_digest.clone(),
            discovery_payload_digest: query.discovery_payload_digest.clone(),
            community_artifact_digest: query.community_digest.clone(),
            community_payload_digest: query.community_payload_digest.clone(),
            relation_policy_digest: query.relation_policy_digest.clone(),
            community_policy_digest: query.community_policy_digest.clone(),
            score_policy_digest: query.score_policy_digest.clone(),
            limits_digest: query.limits_digest.clone(),
            seed_receipt_digest: query.seed_receipt_digest.clone(),
        },
        path: path.clone(),
        execution: DiscoveryPathExecution {
            mode: query.mode,
            limits: query.limits,
            pruning: query.pruning,
            exhaustion: query.exhaustion,
            cancellation: query.cancellation,
            lexical_seed_truncated: query.lexical_seed_receipt.truncated,
            vector_seed_truncated: query.vector_seed_receipt.truncated,
            ppr_visited_vertices: query.ppr_visited_vertices,
            ppr_pushes: query.ppr_pushes,
            ppr_examined_edges: query.ppr_examined_edges,
            beam_states: query.beam_states,
            beam_examined_edges: query.beam_examined_edges,
            total_examined_edges: query.total_examined_edges,
            fallback_used: query.fallback_used,
        },
        candidate_only: true,
        asserted_edges_traversed: path.edges.len().min(u32::MAX as usize) as u32,
        candidate_edges_traversed: 0,
        topology_writes: 0,
    };
    receipt.receipt_id = receipt_identity(&receipt)?;
    validate_path_receipt(&receipt)?;
    Ok(receipt)
}

pub(crate) fn validate_path_receipt(
    receipt: &DiscoveryPathReceipt,
) -> Result<(), Box<dyn std::error::Error>> {
    let limits_digest = blake3::Hash::from_bytes(receipt.execution.limits.digest()?)
        .to_hex()
        .to_string();
    let path_shape_valid = !receipt.path.node_identities.is_empty()
        && receipt.path.dense_nodes.len() == receipt.path.node_identities.len()
        && receipt.path.edges.len() + 1 == receipt.path.node_identities.len();
    let authority_digests = [
        receipt.query_digest.as_str(),
        receipt.canonical_path_digest.as_str(),
        receipt.authority.source_snapshot_digest.as_str(),
        receipt.authority.evidence_registry_digest.as_str(),
        receipt.authority.discovery_artifact_digest.as_str(),
        receipt.authority.discovery_payload_digest.as_str(),
        receipt.authority.community_artifact_digest.as_str(),
        receipt.authority.community_payload_digest.as_str(),
        receipt.authority.relation_policy_digest.as_str(),
        receipt.authority.community_policy_digest.as_str(),
        receipt.authority.score_policy_digest.as_str(),
        receipt.authority.limits_digest.as_str(),
        receipt.authority.seed_receipt_digest.as_str(),
    ];
    if receipt.schema_version != PATH_RECEIPT_SCHEMA
        || !is_digest(&receipt.receipt_id)
        || authority_digests.into_iter().any(|value| !is_digest(value))
        || receipt.authority.graph_generation == 0
        || receipt.authority.source_snapshot_id.trim().is_empty()
        || !path_shape_valid
        || receipt.canonical_path_digest != canonical_path_digest(&receipt.path)
        || receipt.asserted_edges_traversed as usize != receipt.path.edges.len()
        || receipt.candidate_edges_traversed != 0
        || receipt.topology_writes != 0
        || !receipt.candidate_only
        || receipt.execution.cancellation.requested
        || receipt.execution.cancellation.observed
        || receipt.execution.fallback_used
        || receipt.execution.mode != receipt.execution.limits.mode
        || receipt.execution.total_examined_edges
            != receipt
                .execution
                .ppr_examined_edges
                .saturating_add(receipt.execution.beam_examined_edges)
        || receipt.execution.total_examined_edges > receipt.execution.limits.total_examined_edges
        || receipt.execution.ppr_examined_edges > receipt.execution.limits.ppr_examined_edges
        || receipt.execution.ppr_visited_vertices > receipt.execution.limits.ppr_visited_vertices
        || receipt.authority.limits_digest != limits_digest
        || score_signals(&receipt.path.score)
            .into_iter()
            .any(|signal| !signal.available && signal.value_micros != 0)
        || receipt.path.score.final_score_micros != score_sum(&receipt.path.score)
        || receipt.receipt_id != receipt_identity(receipt)?
    {
        return Err("discovery path receipt violates immutable authority".into());
    }
    Ok(())
}

pub(crate) fn canonical_path_digest(path: &DiscoveryPath) -> String {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix-discovery-canonical-path/v1\0");
    for node in &path.node_identities {
        hasher.update(&node.hash.to_le_bytes());
        hasher.update(&node.collision.to_le_bytes());
    }
    for edge in &path.edges {
        hasher.update(&edge.identity.hash.to_le_bytes());
        hasher.update(&edge.identity.collision.to_le_bytes());
    }
    hasher.finalize().to_hex().to_string()
}

fn receipt_identity(receipt: &DiscoveryPathReceipt) -> Result<String, serde_json::Error> {
    let mut content = receipt.clone();
    content.receipt_id = "pending".to_owned();
    let bytes = serde_json::to_vec(&content)?;
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix-discovery-path-receipt-identity/v1\0");
    hasher.update(&bytes);
    Ok(hasher.finalize().to_hex().to_string())
}

fn score_sum(score: &PathScoreReceipt) -> i64 {
    score_signals(score).into_iter().fold(0_i64, |sum, signal| {
        sum.saturating_add(contribution(signal))
    })
}

fn score_signals(score: &PathScoreReceipt) -> [SignalContribution; 12] {
    [
        score.seed_relevance,
        score.local_ppr_importance,
        score.evidence_quality,
        score.normalized_asserted_confidence,
        score.bridge_strength,
        score.community_affinity,
        score.cross_community_novelty,
        score.temporal_relevance,
        score.model_frontier_boost,
        score.common_relation_penalty,
        score.path_length_penalty,
        score.selected_path_redundancy,
    ]
}

fn contribution(value: SignalContribution) -> i64 {
    value.value_micros
}

fn is_digest(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}
