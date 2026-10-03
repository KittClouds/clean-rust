use serde::{Deserialize, Serialize};

pub const UNIVERSE_ROOT: &str = "6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235";
pub const MEAS02_ROOT: &str = "f7abf12d1473a5e1eddc8a7efb84ff7224811eda83ad62ba4fe300a7648ce5ea";
pub const DISC02P_ROOT: &str = "f6ab7b3f4ba95e70399367e4a16140549bea5e16fe9a58d460e5166ec4200877";
pub const DISC02E_ROOT: &str = "b626d058c5719d797e84848ed7141f2a0c0a3d3a5f28ad3b2f7b24b405e62697";
pub const DISCOVERY_SESSIONS: usize = 257;
pub const ATLAS_SESSIONS: usize = 154;
pub const REPRESENTATION_GATE_SESSIONS: usize = 103;
pub const CONFIRMATION_SESSIONS: usize = 69;
pub const PARTITION_SALT: &str = "OBS_OPEN_03A_FIREWALL_V1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SessionMeta {
    pub session_id: String,
    pub civil_date: String,
    pub month: String,
    pub server_offset_minutes: i16,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum DerivedPartition {
    AtlasDa,
    RepresentationDb,
}

impl DerivedPartition {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::AtlasDa => "ATLAS_DA",
            Self::RepresentationDb => "REPRESENTATION_DB",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PartitionedSession {
    pub session: SessionMeta,
    pub partition: DerivedPartition,
    pub rank_key: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AnchorKind {
    ExtremeCandidateBirth,
    RangeFreeze,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Orientation {
    Upper,
    Lower,
    None,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum OutcomeState {
    ObservedComplete,
    RightCensored,
    SessionTerminated,
    SourcePathIncomplete,
    NotEvaluable,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CensorReason {
    None,
    SessionTermination,
    CandidateSupersession,
    SourcePathGap,
    InvalidAnchor,
    DegenerateRange,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SyntheticBar {
    pub close_epoch: i64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub coverage: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct OutcomeReceipt {
    pub outcome_id: String,
    pub anchor_id: String,
    pub anchor_kind: AnchorKind,
    pub anchor_known_at: i64,
    pub outcome_window_start: i64,
    pub requested_window_end: i64,
    pub observed_until: i64,
    pub outcome_known_at: Option<i64>,
    pub outcome_state: OutcomeState,
    pub censor_reason: CensorReason,
    pub support_bars: u32,
    pub value: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReadReceipt {
    pub relative_path: String,
    pub purpose: String,
    pub sha256: String,
    pub bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CompareResult {
    pub artifact_count: usize,
    pub mismatch_count: usize,
    pub root: String,
}
