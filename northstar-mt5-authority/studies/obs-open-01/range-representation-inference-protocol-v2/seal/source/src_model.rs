use serde::Serialize;

pub const AUTHORITY: &str = "OBS_OPEN_03BP2_FROZEN_AVERAGE_COMPETENCE_INFERENCE_V1";
pub const PARENT_PROTOCOL_ROOT: &str =
    "6954d4a17d2c08c305031ade0e57c468ab90945da6e58839ee145a38b43e60b3";
pub const PREOPEN_AUDIT_ROOT: &str =
    "c6ec93a00a2d62e646d5565c727c233844c64d05e1485fe95956cfc905d86aff";
pub const ATLAS_ROOT: &str = "5f6ee8f323cbddfb91589e31b442c9972a23f1a4dd6146bc74b4667b98908eae";
pub const D_A_SESSIONS: usize = 154;
pub const D_B_SESSIONS: usize = 103;
pub const D_C_SESSIONS: usize = 69;
pub const RANGE_COUNT: usize = 30;
pub const MIN_D_B_COMPLETE: usize = 80;
pub const MIN_D_B_OFFSET: usize = 20;
pub const MIN_MATERIAL_SKILL: f64 = 0.02;
pub const LAMBDAS: [f64; 6] = [1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0];

#[derive(Debug, Clone)]
pub struct SessionRows {
    pub session_index: usize,
    pub session_id: String,
    pub civil_date: String,
    pub month: String,
    pub offset: i32,
    pub targets: [f64; RANGE_COUNT],
    pub raw: [[f64; 5]; RANGE_COUNT],
    pub z: [[f64; 4]; RANGE_COUNT],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
pub enum Arm {
    Design,
    Raw,
    Z,
}

impl Arm {
    pub fn name(self) -> &'static str {
        match self {
            Self::Design => "DESIGN",
            Self::Raw => "RAW",
            Self::Z => "Z",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ScoreRow {
    pub fold_id: u8,
    pub model_state_id: String,
    pub representation: String,
    pub session_index: usize,
    pub session_id: String,
    pub civil_date: String,
    pub month: String,
    pub offset: i32,
    pub baseline_brier: f64,
    pub representation_brier: f64,
    pub difference: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct SelectedLambda {
    pub arm: String,
    pub lambda: f64,
    pub validation_brier: f64,
    pub validation_sessions: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct BlockDiagnostic {
    pub representation: String,
    pub fold_id: u8,
    pub model_state_id: String,
    pub session_count: usize,
    pub calendar_start: String,
    pub calendar_end: String,
    pub offset_plus120: usize,
    pub offset_plus180: usize,
    pub mean: f64,
    pub variance: f64,
    pub minimum: f64,
    pub maximum: f64,
    pub skewness: f64,
    pub excess_kurtosis: f64,
    pub acf: Vec<f64>,
    pub hac_lag: usize,
    pub long_run_variance: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct MethodAssessment {
    pub method: &'static str,
    pub target_parameter: &'static str,
    pub stochastic_assumptions: Vec<&'static str>,
    pub stationarity_requirement: &'static str,
    pub dependence_requirement: &'static str,
    pub authority: &'static str,
    pub nuisance_parameters: Vec<&'static str>,
    pub effective_sample_requirement: &'static str,
    pub failure_modes: Vec<&'static str>,
    pub selection_state: &'static str,
    pub reason: &'static str,
}
