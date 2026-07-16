use std::collections::BTreeMap;

use compact_str::CompactString;
use serde::{Deserialize, Serialize};

use super::{ChunkSemanticBridgeCandidate, ChunkSemanticBridgeType};

pub const CHUNK_SEMANTIC_BRIDGE_PROMOTION_SCHEMA_VERSION: &str =
    "phoenix-chunk-semantic-bridge-promotion/v1";
pub const CHUNK_SEMANTIC_BRIDGE_PROMOTION_COMMIT_POLICY: &str = "proposal_only";
pub const CHUNK_SEMANTIC_BRIDGE_PROMOTION_NO_TOPOLOGY_COMMIT: &str =
    "chunk_semantic_bridge_promotion:proposal_only:no_topology_commit";

#[derive(Clone, Copy, Debug)]
pub struct ChunkSemanticBridgePromotionChunk<'a> {
    pub id: &'a str,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ChunkSemanticBridgePromotionInput<'a> {
    pub candidates: &'a [ChunkSemanticBridgeCandidate],
    pub chunks: &'a [ChunkSemanticBridgePromotionChunk<'a>],
    pub accepted_evidence_ids: &'a [&'a str],
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChunkSemanticBridgePromotionOutput {
    pub schema_version: CompactString,
    pub source: CompactString,
    pub proposals: Vec<ChunkSemanticBridgePromotionProposal>,
    pub rejected: Vec<ChunkSemanticBridgePromotionRejection>,
    pub audit: ChunkSemanticBridgePromotionAudit,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChunkSemanticBridgePromotionAudit {
    pub total: usize,
    pub proposed: usize,
    pub rejected: usize,
    pub by_rejection_reason: BTreeMap<CompactString, usize>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChunkSemanticBridgePromotionStatus {
    PromotionProposed,
    PromotionRejected,
}

impl ChunkSemanticBridgePromotionStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::PromotionProposed => "promotion_proposed",
            Self::PromotionRejected => "promotion_rejected",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChunkSemanticBridgePromotionCommitPolicy {
    ProposalOnly,
}

impl ChunkSemanticBridgePromotionCommitPolicy {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ProposalOnly => CHUNK_SEMANTIC_BRIDGE_PROMOTION_COMMIT_POLICY,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChunkSemanticBridgePromotionProposal {
    pub schema_version: CompactString,
    pub id: CompactString,
    pub source_bridge_id: CompactString,
    pub bridge_type: ChunkSemanticBridgeType,
    pub source_chunk_id: CompactString,
    pub target_chunk_id: CompactString,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_episode_id: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_episode_id: Option<CompactString>,
    pub claim: CompactString,
    pub evidence_ids: Vec<CompactString>,
    pub supporting_entity_ids: Vec<CompactString>,
    pub semantic_verbs: Vec<CompactString>,
    pub source_confidence: f32,
    pub deterministic_score: f32,
    pub status: ChunkSemanticBridgePromotionStatus,
    pub commit_policy: ChunkSemanticBridgePromotionCommitPolicy,
    pub gate_receipts: Vec<CompactString>,
    pub rationale: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChunkSemanticBridgePromotionRejection {
    pub id: CompactString,
    pub source_bridge_id: CompactString,
    pub bridge_type: ChunkSemanticBridgeType,
    pub source_confidence: f32,
    pub status: ChunkSemanticBridgePromotionStatus,
    pub reasons: Vec<CompactString>,
    pub gate_receipts: Vec<CompactString>,
}
