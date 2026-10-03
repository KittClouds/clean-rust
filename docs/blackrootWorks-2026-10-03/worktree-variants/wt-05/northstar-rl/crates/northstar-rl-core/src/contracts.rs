use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::{Digest, Result, identity};

pub const RUNRAW_TAPE_V1: &str = "RUNRAW_TAPE_V1";
pub const FEATURE_REGISTRY_V1: &str = "FEATURE_REGISTRY_V1";
pub const FEATURE_TAPE_V1: &str = "FEATURE_TAPE_V1";
pub const OBSERVATION_SPEC_V1: &str = "OBSERVATION_SPEC_V1";
pub const EPISODE_TAPE_V1: &str = "EPISODE_TAPE_V1";
pub const ACTION_SPEC_TARGET_EXPOSURE_V1: &str = "ACTION_SPEC_TARGET_EXPOSURE_V1";
pub const INSTRUMENT_CONTRACT_V1: &str = "INSTRUMENT_CONTRACT_V1";
pub const EXECUTION_SPEC_V1: &str = "EXECUTION_SPEC_V1";
pub const REWARD_PRIMITIVES_V1: &str = "REWARD_PRIMITIVES_V1";
pub const REWARD_SPEC_V1: &str = "REWARD_SPEC_V1";
pub const TERMINATION_SPEC_V1: &str = "TERMINATION_SPEC_V1";
pub const ENV_STEP_TAPE_V1: &str = "ENV_STEP_TAPE_V1";
pub const RL_ENV_SPEC_V1: &str = "RL_ENV_SPEC_V1";

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[repr(u8)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SourceStatus {
    Available = 0,
    Gap = 1,
    Unavailable = 2,
    Censored = 3,
}

impl SourceStatus {
    pub fn from_code(code: u8) -> Self {
        match code {
            0 => Self::Available,
            1 => Self::Gap,
            2 => Self::Unavailable,
            _ => Self::Censored,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[repr(u8)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum FeatureCellState {
    Available = 0,
    Warmup = 1,
    SourceGap = 2,
    Unavailable = 3,
    Censored = 4,
}

impl FeatureCellState {
    pub fn from_code(code: u8) -> Self {
        match code {
            0 => Self::Available,
            1 => Self::Warmup,
            2 => Self::SourceGap,
            3 => Self::Unavailable,
            _ => Self::Censored,
        }
    }
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct TapeIdentity {
    pub schema_version: String,
    pub source_manifest_hash: Digest,
    pub row_count: u64,
    pub first_time: i64,
    pub last_time: i64,
    pub instrument_set: Vec<u32>,
    pub source_set: Vec<u32>,
    pub content_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FeatureDType {
    Float64,
    Float32,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum FeatureTransform {
    RawOpen,
    RawHigh,
    RawLow,
    RawClose,
    LogReturn,
    SimpleReturn,
    CandleRange,
    CandleBody,
    UpperWick,
    LowerWick,
    RollingHigh { window: u32 },
    RollingLow { window: u32 },
    RollingRange { window: u32 },
    RollingMean { window: u32 },
    RollingVariance { window: u32 },
    RollingStdDev { window: u32 },
    RealizedAbsoluteMovement { window: u32 },
    VolumeChange,
    TimeOfDaySin,
    TimeOfDayCos,
    SessionProgress,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct FeatureDeclaration {
    pub feature_id: String,
    pub feature_family: String,
    pub version: u32,
    pub dtype: FeatureDType,
    pub shape: Vec<u32>,
    pub source_dependencies: Vec<String>,
    pub lookback: u32,
    pub warmup: u32,
    pub event_time_semantics: String,
    pub knowledge_time_semantics: String,
    pub missingness_semantics: String,
    pub units: String,
    pub transform: FeatureTransform,
    pub parameters: Vec<(String, String)>,
    pub implementation_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct FeatureRegistry {
    pub schema_version: String,
    pub features: Vec<FeatureDeclaration>,
    pub content_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ObservationLayout {
    Flat,
    WindowedMatrix,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ObservationSpec {
    pub schema_version: String,
    pub observation_spec_id: Digest,
    pub ordered_feature_ids: Vec<String>,
    pub history_depth: u32,
    pub stacking_semantics: String,
    pub dtype: FeatureDType,
    pub output_shape: Vec<u32>,
    pub availability_rule: String,
    pub layout: ObservationLayout,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct EpisodeSpec {
    pub schema_version: String,
    pub episode_spec_id: Digest,
    pub mode: String,
    pub source_gap_policy: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ActionSpec {
    pub schema_version: String,
    pub action_spec_id: Digest,
    pub low: f32,
    pub high: f32,
    pub shape: Vec<u32>,
    pub dtype: String,
    pub semantics: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct InstrumentContract {
    pub schema_version: String,
    pub instrument_contract_id: Digest,
    pub instrument_id: u32,
    pub price_precision: u8,
    pub tick_size: f64,
    pub tick_value: f64,
    pub contract_size: f64,
    pub quantity_step: f64,
    pub minimum_quantity: f64,
    pub maximum_quantity: f64,
    pub quote_currency: String,
    pub account_currency: String,
    pub conversion_rule: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QuantityRounding {
    TowardZero,
    Nearest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ExecutionSpec {
    pub schema_version: String,
    pub execution_spec_id: Digest,
    pub action_source: String,
    pub fill_timing: String,
    pub reference_fill_price: String,
    pub quantity_rounding: QuantityRounding,
    pub fixed_commission: f64,
    pub proportional_commission: f64,
    pub spread_ticks: f64,
    pub slippage_ticks: f64,
    /// Optional empirical calibration. `None` preserves the deterministic V1 contract.
    pub calibration_id: Option<Digest>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct RewardSpec {
    pub schema_version: String,
    pub reward_spec_id: Digest,
    pub formula: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct TerminationSpec {
    pub schema_version: String,
    pub termination_spec_id: Digest,
    pub account_floor: f64,
    pub episode_end_is_truncation: bool,
    pub source_gap_is_termination: bool,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct NumericContract {
    pub schema_version: String,
    pub numeric_contract_id: Digest,
    pub authority_float: String,
    pub observation_float: String,
    pub action_float: String,
    pub non_finite_policy: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct SeedContract {
    pub schema_version: String,
    pub seed_contract_id: Digest,
    pub derivation: String,
}

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum WindTunnelMode {
    RunRawReplay,
    Mt5CaptureReplay,
    TradeLockerCaptureReplay,
    CrossSourceComparison,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct RlEnvSpec {
    pub schema_version: String,
    pub environment_id: Digest,
    pub runraw_tape_id: Digest,
    pub feature_tape_id: Digest,
    pub observation_spec_id: Digest,
    pub episode_spec_id: Digest,
    pub action_spec_id: Digest,
    pub instrument_contract_id: Digest,
    pub execution_spec_id: Digest,
    pub reward_spec_id: Digest,
    pub termination_spec_id: Digest,
    pub numeric_contract_id: Digest,
    pub seed_contract_id: Digest,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub market_source_contract: Option<Digest>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub broker_contract_tape_id: Option<Digest>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub execution_calibration_id: Option<Digest>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub instrument_binding_id: Option<Digest>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wind_tunnel_mode: Option<WindTunnelMode>,
    pub implementation_hashes: Vec<Digest>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub extension_implementation_hashes: Vec<Digest>,
}

pub fn identified<T: Serialize + Clone>(
    domain: &[u8],
    mut value: T,
    set: impl Fn(&mut T, Digest),
) -> Result<T> {
    set(&mut value, Digest::ZERO);
    let digest = identity(domain, &value)?;
    set(&mut value, digest);
    Ok(value)
}
