use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum InputAuthority {
    CanonicalIntegerM1BridgeV1,
    CurrentCanonicalL2Runtime,
    SyntheticSequenceFixture,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoverageState {
    Complete,
    Incomplete,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Location {
    InZone,
    Above,
    Below,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RangeContext {
    pub k: u8,
    pub high_ticks: i64,
    pub low_ticks: i64,
    pub freeze_commit_time_ns: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KernelContext {
    pub session_id: String,
    pub session_start_ns: i64,
    pub session_terminal_ns: i64,
    pub price_scale: i64,
    pub source_time_resolution_ns: i64,
    pub storage_time_resolution_ns: i64,
    pub observation_cadence_ns: i64,
    pub ranges: Box<[RangeContext]>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompletedObservation {
    pub input_authority: InputAuthority,
    pub source_row_id: String,
    pub event_time_ns: i64,
    pub knowledge_time_ns: i64,
    pub open_ticks: i64,
    pub high_ticks: i64,
    pub low_ticks: i64,
    pub close_ticks: i64,
    pub price_scale: i64,
    pub source_time_resolution_ns: i64,
    pub observation_cadence_ns: i64,
    pub coverage: CoverageState,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CandidateState {
    pub id: u32,
    pub value_ticks: i64,
    pub birth_bar_index: u16,
    pub birth_knowledge_time_ns: i64,
    pub age_bars: u16,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KernelState {
    pub initialized: bool,
    pub bar_index: Option<u16>,
    pub knowledge_time_ns: Option<i64>,
    pub upper: Option<CandidateState>,
    pub lower: Option<CandidateState>,
    pub close_ticks: Option<i64>,
    pub upper_giveback_ticks: Option<i64>,
    pub lower_giveback_ticks: Option<i64>,
    pub range_locations: Box<[Option<Location>]>,
    pub upper_extensions_ticks: Box<[Option<i64>]>,
    pub lower_extensions_ticks: Box<[Option<i64>]>,
    pub window_active: bool,
    pub coverage_complete: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Emission {
    ObservationCommit {
        source_row_id: String,
        knowledge_time_ns: i64,
        coverage: CoverageState,
    },
    NewUpperExtreme {
        candidate_id: u32,
    },
    UpperCandidateIdChange {
        prior: Option<u32>,
        current: u32,
    },
    NewLowerExtreme {
        candidate_id: u32,
    },
    LowerCandidateIdChange {
        prior: Option<u32>,
        current: u32,
    },
    LocationTransition {
        k: u8,
        prior: Option<Location>,
        current: Location,
        knowledge_time_ns: i64,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KernelEmissions {
    pub ordered: Box<[Emission]>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StepResult {
    pub state: KernelState,
    pub emissions: KernelEmissions,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum KernelError {
    InputAuthorityNotQualifiedForG1,
    InvalidContext(&'static str),
    InvalidObservation(&'static str),
    ObservationSequenceGap,
    StateOutsideExtractedDomain,
    ArithmeticOverflow,
}

impl std::fmt::Display for KernelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InputAuthorityNotQualifiedForG1 => {
                f.write_str("INPUT_AUTHORITY_NOT_QUALIFIED_FOR_G1")
            }
            Self::InvalidContext(x) | Self::InvalidObservation(x) => f.write_str(x),
            Self::ObservationSequenceGap => f.write_str("OBSERVATION_SEQUENCE_GAP"),
            Self::StateOutsideExtractedDomain => f.write_str("STATE_OUTSIDE_EXTRACTED_DOMAIN"),
            Self::ArithmeticOverflow => f.write_str("ARITHMETIC_OVERFLOW"),
        }
    }
}

impl std::error::Error for KernelError {}
