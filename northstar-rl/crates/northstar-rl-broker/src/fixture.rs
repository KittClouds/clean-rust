use northstar_rl_core::{Digest, Result as CoreResult, WindTunnelMode, identified, identity};
use serde::{Deserialize, Serialize};

use crate::{
    BROKER_CONTRACT_TAPE_V1, BROKER_INSTRUMENT_REGISTRY_V1, BROKER_OBSERVATION_TAPE_V1,
    BindingStatus, BrokerContractRow, BrokerContractTape, BrokerInstrument,
    BrokerInstrumentRegistry, BrokerObservationTape, BrokerQuoteObservation,
    CLOCK_COMPARISON_RECEIPT_V1, ClockComparisonReceipt, ConnectionState, EXECUTION_CALIBRATION_V1,
    EmpiricalPoint, ExecutionCalibration, FieldComparison, INSTRUMENT_BINDING_V1,
    InstrumentBinding, PriceComparison, RawPayloadAuthority, RawRetention, Result,
    StudioBacktraderAdapterSpec, WIND_TUNNEL_MODE_V1, WindTunnelSourceSpec, observation_identity,
    tape_content_hash,
};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct JointReplayFixture {
    pub schema_version: String,
    pub source_class: String,
    pub northstar_instrument_id: u32,
    pub registry: BrokerInstrumentRegistry,
    pub binding: InstrumentBinding,
    pub runraw_source_contract: Digest,
    pub mt5: BrokerObservationTape,
    pub tradelocker: BrokerObservationTape,
    pub broker_contracts: BrokerContractTape,
    pub clock_comparisons: Vec<ClockComparisonReceipt>,
    pub price_comparisons: Vec<PriceComparison>,
    pub calibration: ExecutionCalibration,
    pub wind_tunnel: WindTunnelSourceSpec,
    pub content_hash: Digest,
}

fn quote(
    source: &str,
    index: u32,
    event: i64,
    received: i64,
    bid: f64,
    ask: f64,
) -> Result<BrokerQuoteObservation> {
    let raw = format!("synthetic:{source}:{index}:{event}:{bid}:{ask}");
    let mut row = BrokerQuoteObservation {
        observation_id: Digest::ZERO,
        broker: source.into(),
        account_environment: "SYNTHETIC_QUALIFICATION".into(),
        instrument_id: 3,
        event_time_ns: event,
        received_time_ns: received,
        recorded_time_ns: received + 200_000,
        bid,
        ask,
        last: Some((bid + ask) * 0.5),
        spread: ask - bid,
        raw_payload_hash: Digest::hash(b"synthetic-raw-provider-payload-v1", raw.as_bytes()),
        normalized_payload_hash: Digest::ZERO,
        connection_state: ConnectionState::CapturedReplay,
    };
    row.normalized_payload_hash = identity(b"northstar-normalized-broker-quote-v1", &row)?;
    row.observation_id = observation_identity(&row)?;
    Ok(row)
}

fn tape(source: &str, rows: Vec<BrokerQuoteObservation>) -> Result<BrokerObservationTape> {
    let mut tape = BrokerObservationTape {
        schema_version: BROKER_OBSERVATION_TAPE_V1.into(),
        source_authority: format!("SYNTHETIC_{source}_CONTRACT_FIXTURE"),
        account_id_hash: Digest::hash(b"synthetic-account-v1", source.as_bytes()),
        rows,
        content_hash: Digest::ZERO,
    };
    tape.content_hash = tape_content_hash(&tape)?;
    Ok(tape)
}

pub fn joint_fixture() -> Result<JointReplayFixture> {
    let base = 1_800_000_000_000_000_000_i64;
    let mt5 = tape(
        "MT5",
        (0..4)
            .map(|i| {
                let mid = 40_000.0 + i as f64;
                quote(
                    "MT5",
                    i,
                    base + i as i64 * 60_000_000_000,
                    base + i as i64 * 60_000_000_000 + 2_000_000,
                    mid - 0.5,
                    mid + 0.5,
                )
            })
            .collect::<Result<Vec<_>>>()?,
    )?;
    let tradelocker = tape(
        "TRADELOCKER",
        (0..4)
            .map(|i| {
                let mid = 40_000.125 + i as f64;
                quote(
                    "TRADELOCKER",
                    i,
                    base + i as i64 * 60_000_000_000 + 1_000_000,
                    base + i as i64 * 60_000_000_000 + 6_000_000,
                    mid - 0.625,
                    mid + 0.625,
                )
            })
            .collect::<Result<Vec<_>>>()?,
    )?;

    let raw_hash = Digest::hash(
        b"synthetic-tl-instrument-payload-v1",
        b"US30:precision=2:tick=0.01:step=0.01",
    );
    let mut registry = BrokerInstrumentRegistry {
        schema_version: BROKER_INSTRUMENT_REGISTRY_V1.into(),
        instruments: vec![BrokerInstrument {
            broker: "TRADELOCKER".into(),
            venue: "SYNTHETIC_HEROFX".into(),
            broker_instrument_id: "3".into(),
            broker_symbol: "US30".into(),
            northstar_instrument_id: 3,
            asset_class: "INDEX_CFD".into(),
            quote_currency: "USD".into(),
            price_precision: 2,
            tick_size: 0.01,
            quantity_precision: 2,
            quantity_step: 0.01,
            min_quantity: 0.01,
            max_quantity: Some(100.0),
            contract_size: 1.0,
            trading_status: "SESSION_OPEN".into(),
            raw_metadata: RawPayloadAuthority {
                payload_hash: raw_hash,
                retention: RawRetention::SyntheticFixture,
                retained_relative_path: Some(
                    "fixtures/synthetic_tradelocker_instrument.json".into(),
                ),
            },
            observed_at_ns: base,
        }],
        content_hash: Digest::ZERO,
    };
    registry.content_hash = identity(b"northstar-broker-instrument-registry-v1", &registry)?;

    let binding = identified(
        b"northstar-instrument-binding-v1",
        InstrumentBinding {
            schema_version: INSTRUMENT_BINDING_V1.into(),
            binding_id: Digest::ZERO,
            northstar_instrument_id: 3,
            mt5_terminal_id: "SYNTHETIC_MT5_TERMINAL".into(),
            mt5_symbol: "US30".into(),
            tradelocker_account_environment: "SYNTHETIC_HEROFX".into(),
            tradelocker_instrument_id: "3".into(),
            tradelocker_symbol: "US30".into(),
            binding_basis:
                "explicit qualification fixture with shared symbol and typed contract comparison"
                    .into(),
            observed_contract_fields: vec![
                comparison("price_precision", "2", "2", BindingStatus::Exact),
                comparison("tick_size", "0.01", "0.01", BindingStatus::Exact),
                comparison("quantity_step", "0.01", "0.01", BindingStatus::Exact),
                comparison("quote_currency", "USD", "USD", BindingStatus::Exact),
                comparison(
                    "session_availability",
                    "fixture_open",
                    "fixture_open",
                    BindingStatus::Compatible,
                ),
            ],
            binding_status: BindingStatus::Compatible,
            created_at_ns: base,
            verified_at_ns: base,
        },
        |value, digest| value.binding_id = digest,
    )?;
    let mut contracts = BrokerContractTape {
        schema_version: BROKER_CONTRACT_TAPE_V1.into(),
        rows: vec![BrokerContractRow {
            northstar_instrument_id: 3,
            valid_from_ns: base,
            observed_at_ns: base,
            tick_size: 0.01,
            quantity_step: 0.01,
            minimum_quantity: 0.01,
            contract_size: 1.0,
            margin_fields: vec![("qualification_margin_rate".into(), 0.01)],
            broker_precision: 2,
            quote_denomination: "USD".into(),
            trading_availability: "SESSION_OPEN".into(),
            source_authority: "SYNTHETIC_TRADELOCKER_CONTRACT_FIXTURE".into(),
            source_payload_hash: raw_hash,
        }],
        content_hash: Digest::ZERO,
    };
    contracts.content_hash = identity(b"northstar-broker-contract-tape-v1", &contracts)?;
    let clock_comparisons = mt5
        .rows
        .iter()
        .zip(&tradelocker.rows)
        .map(|(left, right)| clock_receipt(left, right))
        .collect::<CoreResult<Vec<_>>>()?;
    let price_comparisons = mt5
        .rows
        .iter()
        .zip(&tradelocker.rows)
        .map(|(left, right)| price_receipt(left, right))
        .collect::<CoreResult<Vec<_>>>()?;
    let calibration = identified(
        b"northstar-execution-calibration-v1",
        ExecutionCalibration {
            schema_version: EXECUTION_CALIBRATION_V1.into(),
            calibration_id: Digest::ZERO,
            instrument_id: 3,
            market_regime_partition: "SYNTHETIC_QUALIFICATION_ONLY".into(),
            observed_spread_distribution: vec![EmpiricalPoint {
                value: 1.25,
                cumulative_probability: 1.0,
            }],
            observed_price_delta_distribution: vec![EmpiricalPoint {
                value: 0.125,
                cumulative_probability: 1.0,
            }],
            observed_latency_distribution_ns: vec![EmpiricalPoint {
                value: 5_000_000.0,
                cumulative_probability: 1.0,
            }],
            observed_fill_ratio_distribution: vec![EmpiricalPoint {
                value: 1.0,
                cumulative_probability: 1.0,
            }],
            sample_count: 4,
            effective_period_ns: (base, base + 180_000_000_000),
            source_tape_id: tradelocker.content_hash,
            calibration_method: "empirical_ecdf_fixture_no_interpolation".into(),
            calibration_hash: Digest::ZERO,
        },
        |value, digest| {
            value.calibration_id = digest;
            value.calibration_hash = digest;
        },
    )?;
    let runraw_source_contract = Digest::hash(
        b"northstar-runraw-source-contract-v1",
        b"FORGE-RL-01 synthetic common US30 fixture",
    );
    let wind_tunnel = identified(
        b"northstar-wind-tunnel-source-v1",
        WindTunnelSourceSpec {
            schema_version: WIND_TUNNEL_MODE_V1.into(),
            mode: WindTunnelMode::CrossSourceComparison,
            runraw_tape_id: Some(runraw_source_contract),
            mt5_capture_id: Some(mt5.content_hash),
            tradelocker_capture_id: Some(tradelocker.content_hash),
            binding_id: binding.binding_id,
            source_spec_id: Digest::ZERO,
        },
        |value, digest| value.source_spec_id = digest,
    )?;
    let mut fixture = JointReplayFixture {
        schema_version: "JOINT_REPLAY_FIXTURE_V1".into(),
        source_class: "SYNTHETIC_CONTRACT_FIXTURE_NOT_LIVE_MARKET_EVIDENCE".into(),
        northstar_instrument_id: 3,
        registry,
        binding,
        runraw_source_contract,
        mt5,
        tradelocker,
        broker_contracts: contracts,
        clock_comparisons,
        price_comparisons,
        calibration,
        wind_tunnel,
        content_hash: Digest::ZERO,
    };
    fixture.content_hash = identity(b"northstar-joint-replay-fixture-v1", &fixture)?;
    Ok(fixture)
}

fn comparison(field: &str, mt5: &str, tl: &str, status: BindingStatus) -> FieldComparison {
    FieldComparison {
        field: field.into(),
        mt5_value: Some(mt5.into()),
        tradelocker_value: Some(tl.into()),
        status,
        transform: None,
    }
}

fn clock_receipt(
    left: &BrokerQuoteObservation,
    right: &BrokerQuoteObservation,
) -> CoreResult<ClockComparisonReceipt> {
    identified(
        b"northstar-clock-comparison-v1",
        ClockComparisonReceipt {
            schema_version: CLOCK_COMPARISON_RECEIPT_V1.into(),
            northstar_instrument_id: left.instrument_id,
            left_source: left.broker.clone(),
            right_source: right.broker.clone(),
            left_source_time_ns: left.event_time_ns,
            right_source_time_ns: right.event_time_ns,
            left_arrival_offset_ns: left.received_time_ns - left.event_time_ns,
            right_arrival_offset_ns: right.received_time_ns - right.event_time_ns,
            source_time_delta_ns: right.event_time_ns - left.event_time_ns,
            bar_boundary_delta_ns: right.event_time_ns - left.event_time_ns,
            session_boundary_relationship: "SAME_SYNTHETIC_SESSION".into(),
            receipt_id: Digest::ZERO,
        },
        |value, digest| value.receipt_id = digest,
    )
}

fn price_receipt(
    left: &BrokerQuoteObservation,
    right: &BrokerQuoteObservation,
) -> CoreResult<PriceComparison> {
    let left_mid = (left.bid + left.ask) * 0.5;
    let right_mid = (right.bid + right.ask) * 0.5;
    identified(
        b"northstar-broker-price-comparison-v1",
        PriceComparison {
            schema_version: crate::BROKER_PRICE_COMPARISON_V1.into(),
            northstar_instrument_id: left.instrument_id,
            mt5_time_ns: left.event_time_ns,
            tradelocker_time_ns: right.event_time_ns,
            bid_difference: Some(right.bid - left.bid),
            ask_difference: Some(right.ask - left.ask),
            midpoint_difference: Some(right_mid - left_mid),
            spread_difference: Some(right.spread - left.spread),
            bar_open_difference: None,
            bar_high_difference: None,
            bar_low_difference: None,
            bar_close_difference: Some(right_mid - left_mid),
            missing_observation_state: None,
            temporal_alignment: "NEAREST_WITHIN_1MS_FIXTURE".into(),
            difference_class: "VENUE_OBSERVATION_DIFFERENCE".into(),
            receipt_id: Digest::ZERO,
        },
        |value, digest| value.receipt_id = digest,
    )
}

pub fn studio_adapter(
    episode: Digest,
    feature: Digest,
    action: Digest,
    broker: Digest,
) -> CoreResult<StudioBacktraderAdapterSpec> {
    identified(
        b"northstar-studio-backtrader-adapter-v1",
        StudioBacktraderAdapterSpec {
            schema_version: "STUDIO_BACKTRADER_ADAPTER_V1".into(),
            northstar_episode_spec_id: episode,
            northstar_feature_spec_id: feature,
            northstar_action_spec_id: action,
            broker_contract_id: broker,
            studio_adapter_version: "northstar-origin-v1".into(),
            restrictions: vec![
                "RESEARCH_CONSUMER_ONLY".into(),
                "NO_COMMAND_AUTHORITY".into(),
                "NO_LEARNER_EXECUTION".into(),
            ],
            adapter_id: Digest::ZERO,
        },
        |value, digest| value.adapter_id = digest,
    )
}
