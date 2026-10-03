use northstar_rl_core::{Digest, WindTunnelMode};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

pub const BROKER_INSTRUMENT_REGISTRY_V1: &str = "BROKER_INSTRUMENT_REGISTRY_V1";
pub const INSTRUMENT_BINDING_V1: &str = "INSTRUMENT_BINDING_V1";
pub const BROKER_OBSERVATION_TAPE_V1: &str = "BROKER_OBSERVATION_TAPE_V1";
pub const CLOCK_COMPARISON_RECEIPT_V1: &str = "CLOCK_COMPARISON_RECEIPT_V1";
pub const BROKER_PRICE_COMPARISON_V1: &str = "BROKER_PRICE_COMPARISON_V1";
pub const BROKER_CONTRACT_TAPE_V1: &str = "BROKER_CONTRACT_TAPE_V1";
pub const EXECUTION_REALITY_TAPE_V1: &str = "EXECUTION_REALITY_TAPE_V1";
pub const EXECUTION_CALIBRATION_V1: &str = "EXECUTION_CALIBRATION_V1";
pub const WIND_TUNNEL_MODE_V1: &str = "WIND_TUNNEL_MODE_V1";
pub const BROKER_ACCOUNT_SNAPSHOT_V1: &str = "BROKER_ACCOUNT_SNAPSHOT_V1";
pub const BROKER_POSITION_PROJECTION_V1: &str = "BROKER_POSITION_PROJECTION_V1";

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct RawPayloadAuthority {
    pub payload_hash: Digest,
    pub retention: RawRetention,
    pub retained_relative_path: Option<String>,
}

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RawRetention {
    HashOnly,
    RetainedWithExplicitAuthority,
    SyntheticFixture,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct BrokerInstrument {
    pub broker: String,
    pub venue: String,
    pub broker_instrument_id: String,
    pub broker_symbol: String,
    pub northstar_instrument_id: u32,
    pub asset_class: String,
    pub quote_currency: String,
    pub price_precision: u8,
    pub tick_size: f64,
    pub quantity_precision: u8,
    pub quantity_step: f64,
    pub min_quantity: f64,
    pub max_quantity: Option<f64>,
    pub contract_size: f64,
    pub trading_status: String,
    pub raw_metadata: RawPayloadAuthority,
    pub observed_at_ns: i64,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct BrokerInstrumentRegistry {
    pub schema_version: String,
    pub instruments: Vec<BrokerInstrument>,
    pub content_hash: Digest,
}

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum BindingStatus {
    Exact,
    Compatible,
    TransformRequired,
    Partial,
    Unresolved,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct FieldComparison {
    pub field: String,
    pub mt5_value: Option<String>,
    pub tradelocker_value: Option<String>,
    pub status: BindingStatus,
    pub transform: Option<String>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct InstrumentBinding {
    pub schema_version: String,
    pub binding_id: Digest,
    pub northstar_instrument_id: u32,
    pub mt5_terminal_id: String,
    pub mt5_symbol: String,
    pub tradelocker_account_environment: String,
    pub tradelocker_instrument_id: String,
    pub tradelocker_symbol: String,
    pub binding_basis: String,
    pub observed_contract_fields: Vec<FieldComparison>,
    pub binding_status: BindingStatus,
    pub created_at_ns: i64,
    pub verified_at_ns: i64,
}

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ConnectionState {
    Connected,
    Reauthenticated,
    CapturedReplay,
    Unavailable,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct BrokerQuoteObservation {
    pub observation_id: Digest,
    pub broker: String,
    pub account_environment: String,
    pub instrument_id: u32,
    pub event_time_ns: i64,
    pub received_time_ns: i64,
    pub recorded_time_ns: i64,
    pub bid: f64,
    pub ask: f64,
    pub last: Option<f64>,
    pub spread: f64,
    pub raw_payload_hash: Digest,
    pub normalized_payload_hash: Digest,
    pub connection_state: ConnectionState,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct BrokerObservationTape {
    pub schema_version: String,
    pub source_authority: String,
    pub account_id_hash: Digest,
    pub rows: Vec<BrokerQuoteObservation>,
    pub content_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct BrokerAccountSnapshot {
    pub schema_version: String,
    pub account_id_hash: Digest,
    pub environment: String,
    pub broker_raw_terms: Vec<(String, f64)>,
    pub cash_equivalent: Option<f64>,
    pub equity: Option<f64>,
    pub unrealized_pnl: Option<f64>,
    pub realized_pnl: Option<f64>,
    pub available_funds: Option<f64>,
    pub margin_terms: Vec<(String, f64)>,
    pub broker_time_ns: Option<i64>,
    pub received_time_ns: i64,
    pub raw_payload_hash: Digest,
    pub field_provenance: Vec<(String, String)>,
    pub content_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct BrokerPositionProjection {
    pub schema_version: String,
    pub broker_position_id_hash: Digest,
    pub northstar_instrument_id: u32,
    pub side: String,
    pub quantity: f64,
    pub average_price: f64,
    pub current_price: Option<f64>,
    pub unrealized_result: Option<f64>,
    pub broker_status: String,
    pub observation_time_ns: i64,
    pub raw_payload_hash: Digest,
    pub content_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ClockComparisonReceipt {
    pub schema_version: String,
    pub northstar_instrument_id: u32,
    pub left_source: String,
    pub right_source: String,
    pub left_source_time_ns: i64,
    pub right_source_time_ns: i64,
    pub left_arrival_offset_ns: i64,
    pub right_arrival_offset_ns: i64,
    pub source_time_delta_ns: i64,
    pub bar_boundary_delta_ns: i64,
    pub session_boundary_relationship: String,
    pub receipt_id: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct PriceComparison {
    pub schema_version: String,
    pub northstar_instrument_id: u32,
    pub mt5_time_ns: i64,
    pub tradelocker_time_ns: i64,
    pub bid_difference: Option<f64>,
    pub ask_difference: Option<f64>,
    pub midpoint_difference: Option<f64>,
    pub spread_difference: Option<f64>,
    pub bar_open_difference: Option<f64>,
    pub bar_high_difference: Option<f64>,
    pub bar_low_difference: Option<f64>,
    pub bar_close_difference: Option<f64>,
    pub missing_observation_state: Option<String>,
    pub temporal_alignment: String,
    pub difference_class: String,
    pub receipt_id: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct BrokerContractRow {
    pub northstar_instrument_id: u32,
    pub valid_from_ns: i64,
    pub observed_at_ns: i64,
    pub tick_size: f64,
    pub quantity_step: f64,
    pub minimum_quantity: f64,
    pub contract_size: f64,
    pub margin_fields: Vec<(String, f64)>,
    pub broker_precision: u8,
    pub quote_denomination: String,
    pub trading_availability: String,
    pub source_authority: String,
    pub source_payload_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct BrokerContractTape {
    pub schema_version: String,
    pub rows: Vec<BrokerContractRow>,
    pub content_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ExecutionRealityRow {
    pub intent_id: Option<Digest>,
    pub command_id: Option<Digest>,
    pub broker_order_id_hash: Digest,
    pub instrument_id: u32,
    pub side: String,
    pub requested_quantity: f64,
    pub command_time_ns: i64,
    pub accepted_time_ns: Option<i64>,
    pub fill_time_ns: Option<i64>,
    pub reference_price_at_command: Option<f64>,
    pub reference_price_at_acceptance: Option<f64>,
    pub fill_price: Option<f64>,
    pub filled_quantity: f64,
    pub broker_status: String,
    pub observed_spread: Option<f64>,
    pub price_delta_to_reference: Option<f64>,
    pub latency_components_ns: Vec<(String, i64)>,
    pub commission_components: Vec<(String, f64)>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ExecutionRealityTape {
    pub schema_version: String,
    pub source_authority: String,
    pub rows: Vec<ExecutionRealityRow>,
    pub content_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct EmpiricalPoint {
    pub value: f64,
    pub cumulative_probability: f64,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ExecutionCalibration {
    pub schema_version: String,
    pub calibration_id: Digest,
    pub instrument_id: u32,
    pub market_regime_partition: String,
    pub observed_spread_distribution: Vec<EmpiricalPoint>,
    pub observed_price_delta_distribution: Vec<EmpiricalPoint>,
    pub observed_latency_distribution_ns: Vec<EmpiricalPoint>,
    pub observed_fill_ratio_distribution: Vec<EmpiricalPoint>,
    pub sample_count: u64,
    pub effective_period_ns: (i64, i64),
    pub source_tape_id: Digest,
    pub calibration_method: String,
    pub calibration_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct WindTunnelSourceSpec {
    pub schema_version: String,
    pub mode: WindTunnelMode,
    pub runraw_tape_id: Option<Digest>,
    pub mt5_capture_id: Option<Digest>,
    pub tradelocker_capture_id: Option<Digest>,
    pub binding_id: Digest,
    pub source_spec_id: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct StudioBacktraderAdapterSpec {
    pub schema_version: String,
    pub northstar_episode_spec_id: Digest,
    pub northstar_feature_spec_id: Digest,
    pub northstar_action_spec_id: Digest,
    pub broker_contract_id: Digest,
    pub studio_adapter_version: String,
    pub restrictions: Vec<String>,
    pub adapter_id: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ConnectionDiagnostic {
    pub provider: String,
    pub credential_provider: String,
    pub credential_alias: String,
    pub credential_resolved: bool,
    pub authenticated_account_id_hash: Option<Digest>,
    pub connection_environment: String,
    pub connection_state: ConnectionState,
    pub detail_code: String,
}
