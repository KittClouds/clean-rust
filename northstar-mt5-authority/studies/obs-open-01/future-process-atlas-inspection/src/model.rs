use serde::Serialize;

pub const PARENT_ROOT: &str = "5f6ee8f323cbddfb91589e31b442c9972a23f1a4dd6146bc74b4667b98908eae";
pub const AUTHORITY: &str = "OBS_OPEN_03AI_ATLAS_ANATOMY_SUPPLEMENT_V1";
pub const SESSION_COUNT: usize = 154;
pub const MAX_AGE_MINUTES: u16 = 389;

#[derive(Debug, Clone, Copy)]
pub struct CandidateDuration {
    pub session_index: u32,
    pub event_time: Option<u16>,
    pub endpoint_time: u16,
    pub endpoint: Endpoint,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Endpoint {
    Supersession,
    RightCensor,
    SessionTermination,
    SourcePathIncomplete,
    NotEvaluable,
}

#[derive(Debug, Clone, Serialize)]
pub struct PersistenceRow {
    pub age_minutes: u16,
    pub sampling_unit: String,
    pub at_risk_anchors: usize,
    pub contributing_sessions: usize,
    pub observed_supersessions: usize,
    pub right_censored: usize,
    pub session_terminated: usize,
    pub source_path_incomplete: usize,
    pub not_evaluable: usize,
    pub at_risk_mass: f64,
    pub event_mass: f64,
    pub censor_mass: f64,
    pub survival: f64,
    pub conditional_hazard: f64,
}

#[derive(Debug, Clone, Copy, Hash, PartialEq, Eq, PartialOrd, Ord)]
pub struct SurfaceKey {
    pub outcome: u16,
    pub representation: u8,
    pub k: u8,
    pub horizon: u16,
}

#[derive(Debug, Clone)]
pub struct SurfaceCell {
    pub key: SurfaceKey,
    pub values: Vec<(f64, u32)>,
    pub observed_complete: usize,
    pub right_censored: usize,
    pub session_terminated: usize,
    pub source_path_incomplete: usize,
    pub not_evaluable: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct SurfaceRow {
    pub outcome_code: u16,
    pub representation: String,
    pub k: u8,
    pub freeze_minute_after_open: u8,
    pub horizon_minutes: u16,
    pub evaluation_minute_after_open: u16,
    pub sampling_unit: String,
    pub observed_complete: usize,
    pub contributing_sessions: usize,
    pub right_censored: usize,
    pub session_terminated: usize,
    pub source_path_incomplete: usize,
    pub not_evaluable: usize,
    pub q10: Option<f64>,
    pub q25: Option<f64>,
    pub q50: Option<f64>,
    pub q75: Option<f64>,
    pub q90: Option<f64>,
    pub mean: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct WidthRow {
    pub k: u8,
    pub reconstructed_ranges: usize,
    pub contributing_sessions: usize,
    pub reconstruction_not_evaluable: usize,
    pub q10: Option<f64>,
    pub q25: Option<f64>,
    pub q50: Option<f64>,
    pub q75: Option<f64>,
    pub q90: Option<f64>,
    pub mean: Option<f64>,
    pub unit: String,
    pub derivation: String,
}

pub fn representation_name(code: u8) -> &'static str {
    match code {
        1 => "RAW_PRICE",
        2 => "RANGE_Z",
        3 => "DIMENSIONLESS",
        _ => "UNKNOWN",
    }
}
