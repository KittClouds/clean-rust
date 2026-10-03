use bytemuck::{Pod, Zeroable};
use obs_open_meas02::{Bar, Candidate, RangeObject, SessionSpec};
use serde::Serialize;

pub const PROTOCOL_ROOT: &str = "3d1da3657154d5a4e11eca99cab021c71c9c8a5d6d4458469133f3d2b8e3a402";
pub const ATLAS_SESSIONS: usize = 154;
pub const D_B_SESSIONS: usize = 103;
pub const D_C_SESSIONS: usize = 69;
pub const SESSION_BARS: usize = 390;
pub const SESSION_MINUTES: u16 = 390;
pub const ABSENT_TIME: i64 = i64::MIN;

#[derive(Debug)]
pub struct AtlasSession {
    pub spec: SessionSpec,
    pub month: String,
    pub bars: Vec<Bar>,
    pub ranges: Vec<RangeObject>,
    pub candidates: Vec<Candidate>,
    pub path_complete: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct PathGap {
    pub session_id: String,
    pub expected_open_epoch: i64,
    pub first_later_observed_epoch: Option<i64>,
    pub retained_prefix_bars: usize,
    pub state: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct AccessAudit {
    pub source_prefix_rows_scanned: usize,
    pub source_prefix_sha256: String,
    #[serde(rename = "D_A_sessions_decoded")]
    pub d_a_sessions_decoded: usize,
    #[serde(rename = "D_A_ohlc_observations_decoded")]
    pub d_a_ohlc_observations_decoded: usize,
    #[serde(rename = "D_A_retained_causal_bars")]
    pub d_a_retained_causal_bars: usize,
    #[serde(rename = "D_A_path_gap_sessions")]
    pub d_a_path_gap_sessions: usize,
    #[serde(rename = "D_A_path_gaps")]
    pub d_a_path_gaps: Vec<PathGap>,
    #[serde(rename = "D_A_outcome_registry_applications")]
    pub d_a_outcome_registry_applications: usize,
    #[serde(rename = "D_B_session_ids_decoded_for_outcomes")]
    pub d_b_session_ids_decoded_for_outcomes: usize,
    #[serde(rename = "D_B_ohlc_values_decoded")]
    pub d_b_ohlc_values_decoded: usize,
    #[serde(rename = "D_B_outcome_registry_applications")]
    pub d_b_outcome_registry_applications: usize,
    #[serde(rename = "D_B_derived_outcomes_inspected")]
    pub d_b_derived_outcomes_inspected: usize,
    #[serde(rename = "D_B_formal_scores")]
    pub d_b_formal_scores: usize,
    #[serde(rename = "D_C_membership_rows_decoded")]
    pub d_c_membership_rows_decoded: usize,
    #[serde(rename = "D_C_observations_read")]
    pub d_c_observations_read: usize,
    #[serde(rename = "D_C_outcomes_computed")]
    pub d_c_outcomes_computed: usize,
    pub next_source_row_requested: bool,
}

#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum AnchorKind {
    Candidate = 1,
    Range = 2,
}

#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Side {
    None = 0,
    Upper = 1,
    Lower = 2,
}

#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Representation {
    RawPrice = 1,
    RangeZ = 2,
    Dimensionless = 3,
}

#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum OutcomeState {
    ObservedComplete = 1,
    RightCensored = 2,
    SessionTerminated = 3,
    SourcePathIncomplete = 4,
    NotEvaluable = 5,
}

#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum CensorReason {
    None = 0,
    SessionTermination = 1,
    CandidateSupersession = 2,
    SourcePathGap = 3,
    InvalidAnchor = 4,
    DegenerateRange = 5,
}

#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum TerminalClass {
    NotApplicable = 0,
    Superseded = 1,
    TerminalSurvivor = 2,
    SourcePathIncomplete = 3,
}

#[repr(u16)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum OutcomeCode {
    CandidateTerminalOrientedDisplacement = 1,
    CandidateMaxParallelDisplacement = 2,
    CandidateMaxAntiparallelDisplacement = 3,
    CandidateRealizedCloseVariation = 4,
    CandidatePathEfficiency = 5,
    CandidateFirstPassageParallel = 6,
    CandidateFirstPassageAntiparallel = 7,
    CandidateTimeToSupersession = 8,
    CandidateSurvivalAtHorizon = 9,
    CandidateTerminalStatus = 10,
    RangeTerminalClose = 101,
    RangeMaxUpperDisplacement = 102,
    RangeMaxLowerDisplacement = 103,
    RangeRealizedCloseVariation = 104,
    RangePathEfficiency = 105,
    RangeFirstPassageUpper = 106,
    RangeFirstPassageLower = 107,
    RangeLocationOccupancy = 108,
    RangeMidpointCrossingCount = 109,
    RangeRailCrossingCount = 110,
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct PackedOutcome {
    pub value_bits: u64,
    pub censor_minutes_bits: u64,
    pub anchor_known_at: i64,
    pub outcome_known_at: i64,
    pub requested_end: i64,
    pub observed_until: i64,
    pub anchor_index: u32,
    pub session_index: u32,
    pub outcome_code: u16,
    pub horizon_minutes: u16,
    pub support_bars: u16,
    pub k: u8,
    pub threshold_index: u8,
    pub anchor_kind: u8,
    pub side: u8,
    pub representation: u8,
    pub outcome_state: u8,
    pub censor_reason: u8,
    pub terminal_class: u8,
    pub value_present: u8,
    pub outcome_known_present: u8,
    pub censor_present: u8,
    pub reserved: [u8; 7],
}

impl PackedOutcome {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        value: Option<f64>,
        censor_minutes: Option<f64>,
        anchor_known_at: i64,
        outcome_known_at: Option<i64>,
        requested_end: i64,
        observed_until: i64,
        anchor_index: u32,
        session_index: u32,
        outcome_code: OutcomeCode,
        horizon_minutes: u16,
        support_bars: u16,
        k: u8,
        threshold_index: u8,
        anchor_kind: AnchorKind,
        side: Side,
        representation: Representation,
        outcome_state: OutcomeState,
        censor_reason: CensorReason,
        terminal_class: TerminalClass,
    ) -> Self {
        Self {
            value_bits: value.unwrap_or_default().to_bits(),
            censor_minutes_bits: censor_minutes.unwrap_or_default().to_bits(),
            anchor_known_at,
            outcome_known_at: outcome_known_at.unwrap_or(ABSENT_TIME),
            requested_end,
            observed_until,
            anchor_index,
            session_index,
            outcome_code: outcome_code as u16,
            horizon_minutes,
            support_bars,
            k,
            threshold_index,
            anchor_kind: anchor_kind as u8,
            side: side as u8,
            representation: representation as u8,
            outcome_state: outcome_state as u8,
            censor_reason: censor_reason as u8,
            terminal_class: terminal_class as u8,
            value_present: u8::from(value.is_some()),
            outcome_known_present: u8::from(outcome_known_at.is_some()),
            censor_present: u8::from(censor_minutes.is_some()),
            reserved: [0; 7],
        }
    }

    pub fn value(self) -> Option<f64> {
        (self.value_present == 1).then(|| f64::from_bits(self.value_bits))
    }

    pub fn censor_minutes(self) -> Option<f64> {
        (self.censor_present == 1).then(|| f64::from_bits(self.censor_minutes_bits))
    }
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct EcdfPoint {
    pub value: f64,
    pub cumulative_mass: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct AnchorReceipt {
    pub anchor_index: u32,
    pub anchor_id: String,
    pub session_index: u32,
    pub session_id: String,
    pub anchor_kind: String,
    pub side: String,
    pub k: Option<u8>,
    pub anchor_known_at: i64,
    pub source_path_sha256: String,
    pub path_bars: usize,
    pub terminal_class: String,
}

pub const fn outcome_name(code: u16) -> &'static str {
    match code {
        1 => "CANDIDATE_TERMINAL_ORIENTED_DISPLACEMENT_RAW",
        2 => "CANDIDATE_MAX_PARALLEL_DISPLACEMENT_RAW",
        3 => "CANDIDATE_MAX_ANTIPARALLEL_DISPLACEMENT_RAW",
        4 => "CANDIDATE_REALIZED_CLOSE_VARIATION_RAW",
        5 => "CANDIDATE_PATH_EFFICIENCY",
        6 => "CANDIDATE_FIRST_PASSAGE_PARALLEL_RAW",
        7 => "CANDIDATE_FIRST_PASSAGE_ANTIPARALLEL_RAW",
        8 => "CANDIDATE_TIME_TO_SUPERSESSION",
        9 => "CANDIDATE_SURVIVAL_AT_HORIZON",
        10 => "CANDIDATE_TERMINAL_STATUS",
        101 => "RANGE_TERMINAL_CLOSE",
        102 => "RANGE_MAX_UPPER_DISPLACEMENT",
        103 => "RANGE_MAX_LOWER_DISPLACEMENT",
        104 => "RANGE_REALIZED_CLOSE_VARIATION",
        105 => "RANGE_PATH_EFFICIENCY",
        106 => "RANGE_FIRST_PASSAGE_UPPER_Z",
        107 => "RANGE_FIRST_PASSAGE_LOWER_Z",
        108 => "RANGE_LOCATION_OCCUPANCY",
        109 => "RANGE_MIDPOINT_CROSSING_COUNT",
        110 => "RANGE_RAIL_CROSSING_COUNT",
        _ => "UNKNOWN_OUTCOME",
    }
}

pub const fn representation_name(code: u8) -> &'static str {
    match code {
        1 => "RAW_PRICE",
        2 => "RANGE_Z",
        3 => "DIMENSIONLESS",
        _ => "UNKNOWN_REPRESENTATION",
    }
}
