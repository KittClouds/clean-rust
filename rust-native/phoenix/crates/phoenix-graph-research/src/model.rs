use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

pub const FROZEN_GRAPH_RESEARCH_SCHEMA: &str = "phoenix-frozen-graph-research/v1";
pub const FROZEN_GRAPH_RESEARCH_BINARY_VERSION: u16 = 1;
pub const PROPOSAL_FEATURE_DIM: usize = 16;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[repr(u8)]
pub enum ResearchSplit {
    Train = 1,
    Validation = 2,
    Test = 3,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[repr(u8)]
pub enum ResearchAuthority {
    Asserted = 1,
    Candidate = 2,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[repr(u8)]
pub enum ResearchProposalLabel {
    Uncommitted = 0,
    Active = 1,
    Superseded = 2,
    Retracted = 3,
    Reverted = 4,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalSplitPolicy {
    pub train_through_ms: i64,
    pub validation_through_ms: i64,
}

impl TemporalSplitPolicy {
    pub fn validate(self, frozen_at_ms: i64) -> Result<(), FrozenGraphResearchError> {
        if self.train_through_ms <= 0
            || self.validation_through_ms <= self.train_through_ms
            || frozen_at_ms <= self.validation_through_ms
        {
            return Err(FrozenGraphResearchError::InvalidSplitPolicy);
        }
        Ok(())
    }

    pub fn split(self, available_at_ms: i64) -> ResearchSplit {
        if available_at_ms <= self.train_through_ms {
            ResearchSplit::Train
        } else if available_at_ms <= self.validation_through_ms {
            ResearchSplit::Validation
        } else {
            ResearchSplit::Test
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResearchNode {
    pub id: CompactString,
    pub kind: CompactString,
    pub authority: ResearchAuthority,
    pub split: ResearchSplit,
    pub available_at_ms: i64,
    pub source_generation: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResearchEdge {
    pub source: u32,
    pub target: u32,
    pub relation: CompactString,
    pub authority: ResearchAuthority,
    pub split: ResearchSplit,
    pub available_at_ms: i64,
    pub weight: f32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResearchIncidence {
    pub hyperedge: u32,
    pub participant: u32,
    pub role: CompactString,
    pub split: ResearchSplit,
    pub resolved: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResearchProposal {
    pub proposal_id: CompactString,
    pub receipt_id: CompactString,
    pub feature_schema_id: CompactString,
    pub split: ResearchSplit,
    pub label: ResearchProposalLabel,
    pub observed_at_ms: i64,
    pub label_available_at_ms: i64,
    pub features: [i16; PROPOSAL_FEATURE_DIM],
}

#[derive(Clone, Debug, PartialEq)]
pub struct FrozenGraphResearchSnapshot {
    pub dataset_id: CompactString,
    pub checkpoint_id: CompactString,
    pub checkpoint_generation: u64,
    pub frozen_at_ms: i64,
    pub split_policy: TemporalSplitPolicy,
    pub nodes: Vec<ResearchNode>,
    pub edges: Vec<ResearchEdge>,
    pub incidences: Vec<ResearchIncidence>,
    pub proposals: Vec<ResearchProposal>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrozenGraphResearchManifest {
    pub schema_version: CompactString,
    pub dataset_id: CompactString,
    pub checkpoint_id: CompactString,
    pub checkpoint_generation: u64,
    pub frozen_at_ms: i64,
    pub split_policy: TemporalSplitPolicy,
    pub binary_file: CompactString,
    pub binary_blake3: CompactString,
    pub binary_bytes: u64,
    pub nodes: u64,
    pub edges: u64,
    pub incidences: u64,
    pub proposals: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FrozenGraphResearchPaths {
    pub manifest: PathBuf,
    pub binary: PathBuf,
}

#[derive(Debug, Error)]
pub enum FrozenGraphResearchError {
    #[error("invalid temporal split policy")]
    InvalidSplitPolicy,
    #[error("checkpoint generation must be nonzero")]
    ZeroCheckpointGeneration,
    #[error("frozen time precedes graph data")]
    FutureGraphData,
    #[error("duplicate research identifier: {0}")]
    DuplicateId(String),
    #[error("research edge references an unknown vertex: {0}")]
    MissingVertex(String),
    #[error("proposal history is invalid: {0}")]
    ProposalHistory(String),
    #[error("tensorization policy is invalid: {0}")]
    InvalidTensorPolicy(&'static str),
    #[error("research artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("research artifact is corrupt: {0}")]
    CorruptArtifact(&'static str),
    #[error("research artifact I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("research manifest encoding failed: {0}")]
    Json(#[from] serde_json::Error),
}
