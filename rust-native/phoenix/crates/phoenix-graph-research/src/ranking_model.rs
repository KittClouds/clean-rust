use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const RANKING_EVALUATION_SCHEMA: &str = "phoenix-ranking-evaluation/v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum RankingTask {
    TypedLinkPrediction,
    HyperedgeRoleCompletion,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum StructuralBaselineFamily {
    LinkCommonNeighbors,
    LinkRelationPrior,
    LinkPreferentialAttachment,
    RoleParticipantPrior,
    RoleGlobalPrior,
    RoleStructuralComposite,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RankingMetrics {
    pub queries: u64,
    pub candidates: u64,
    pub mean_reciprocal_rank: f64,
    pub hits_at_1: f64,
    pub hits_at_3: f64,
    pub hits_at_10: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StructuralBaselineRun {
    pub family: StructuralBaselineFamily,
    pub train: Option<RankingMetrics>,
    pub validation: Option<RankingMetrics>,
    pub held_out_test: Option<RankingMetrics>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SplitQueryOmissions {
    pub train: u64,
    pub validation: u64,
    pub test: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskRankingReport {
    pub task: RankingTask,
    pub status: CompactString,
    pub selected_family: Option<StructuralBaselineFamily>,
    pub selection_rule: CompactString,
    pub zero_negative_queries_omitted: SplitQueryOmissions,
    pub runs: Vec<StructuralBaselineRun>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RankingEvaluationReport {
    pub schema_version: CompactString,
    pub report_id: CompactString,
    pub derivation_id: CompactString,
    pub evaluation_protocol_id: CompactString,
    pub tie_policy: CompactString,
    pub link_prediction: TaskRankingReport,
    pub hyperedge_role_completion: TaskRankingReport,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RankingEvaluationPath {
    pub report: PathBuf,
}

#[derive(Debug, thiserror::Error)]
pub enum RankingEvaluationError {
    #[error("ranking row and score arrays differ")]
    ScoreShape,
    #[error("ranking group has no positive or multiple positives")]
    InvalidGroup,
    #[error("ranking rows mix splits inside a query")]
    MixedGroupSplit,
    #[error("ranking score is not finite")]
    NonFiniteScore,
    #[error("ranking artifact identity is invalid")]
    Identity,
    #[error("ranking artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("ranking artifact I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("ranking serialization failed: {0}")]
    Json(#[from] serde_json::Error),
}
