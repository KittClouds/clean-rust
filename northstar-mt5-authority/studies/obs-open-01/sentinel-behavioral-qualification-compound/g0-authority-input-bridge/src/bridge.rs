use crate::{
    OBSERVATION_CADENCE_NS, PRICE_SCALE, SOURCE_TIME_RESOLUTION_NS, STORAGE_NS_PER_SOURCE_SECOND,
};
use obs_open_03a::AtlasSession;
use obs_open_meas02::{Bar, build_candidates_and_tape, build_ranges};
use serde::Serialize;
use sha2::{Digest, Sha256};

const MAX_SCALE_ERROR_TICKS: f64 = 1.0e-6;

#[derive(Debug, Clone, Copy, Serialize)]
pub struct CanonicalM1Bar {
    pub open_time_ns: i64,
    pub close_time_ns: i64,
    pub open_ticks: i64,
    pub high_ticks: i64,
    pub low_ticks: i64,
    pub close_ticks: i64,
    pub price_scale: i64,
    pub source_time_resolution_ns: i64,
    pub observation_cadence_ns: i64,
}

#[derive(Debug, Serialize)]
pub struct BridgeAudit {
    pub schema: &'static str,
    pub sessions: usize,
    pub bars: usize,
    pub scalar_prices: usize,
    pub canonical_stream_sha256: String,
    pub original_trace_sha256: String,
    pub normalized_trace_sha256: String,
    pub original_metrology_sha256: String,
    pub normalized_metrology_sha256: String,
    pub price_scale: i64,
    pub tick_size_display_units: f64,
    pub maximum_admitted_scale_error_ticks: f64,
    pub off_grid_price_values: usize,
    pub f64_bit_roundtrip_mismatches: usize,
    pub timestamp_roundtrip_mismatches: usize,
    pub ohlc_invariant_failures: usize,
    pub range_object_mismatches: usize,
    pub candidate_tape_mismatches: usize,
    pub observer_trace_equal: bool,
    pub metrology_products_equal: bool,
    pub exact_historical_byte_equivalence: bool,
    pub source_time_resolution_ns: i64,
    pub canonical_storage_resolution_ns: i64,
    pub observation_cadence_ns: i64,
    pub input_bridge: &'static str,
    pub direct_canonical_l2_drop_in: bool,
    pub restriction: &'static str,
    pub question_status: &'static str,
    pub result: &'static str,
    pub disposition: &'static str,
}

pub fn audit(sessions: &[AtlasSession]) -> Result<BridgeAudit, Box<dyn std::error::Error>> {
    let mut normalized_sessions = Vec::with_capacity(sessions.len());
    let mut canonical_hash = Sha256::new();
    let mut original_trace = Sha256::new();
    let mut normalized_trace = Sha256::new();
    let mut bars = 0usize;
    let mut scalar_prices = 0usize;
    let mut off_grid = 0usize;
    let mut bit_mismatches = 0usize;
    let mut time_mismatches = 0usize;
    let mut ohlc_failures = 0usize;
    let mut range_mismatches = 0usize;
    let mut tape_mismatches = 0usize;

    for session in sessions {
        let mut normalized_bars = Vec::with_capacity(session.bars.len());
        for bar in &session.bars {
            let normalized = normalize_bar(bar);
            let Some(canonical) = normalized.canonical else {
                off_grid += normalized.off_grid_values;
                scalar_prices += 4;
                continue;
            };
            off_grid += normalized.off_grid_values;
            bit_mismatches += normalized.bit_mismatches;
            time_mismatches += normalized.time_mismatches;
            ohlc_failures += usize::from(
                canonical.low_ticks > canonical.open_ticks
                    || canonical.low_ticks > canonical.close_ticks
                    || canonical.high_ticks < canonical.open_ticks
                    || canonical.high_ticks < canonical.close_ticks
                    || canonical.low_ticks > canonical.high_ticks,
            );
            update_canonical_digest(
                &mut canonical_hash,
                session.spec.session_id.as_bytes(),
                &canonical,
            );
            normalized_bars.push(restored_bar(bar, &canonical));
            bars += 1;
            scalar_prices += 4;
        }
        if normalized_bars.len() != session.bars.len() {
            continue;
        }
        let normalized_ranges = build_ranges(&session.spec, &normalized_bars)?;
        let (original_candidates, original_tape) =
            build_candidates_and_tape(&session.spec, &session.bars)?;
        let (normalized_candidates, normalized_tape) =
            build_candidates_and_tape(&session.spec, &normalized_bars)?;
        range_mismatches += usize::from(
            serde_json::to_vec(&session.ranges)? != serde_json::to_vec(&normalized_ranges)?,
        );
        tape_mismatches += usize::from(
            serde_json::to_vec(&original_candidates)?
                != serde_json::to_vec(&normalized_candidates)?
                || serde_json::to_vec(&original_tape)? != serde_json::to_vec(&normalized_tape)?,
        );
        update_trace(
            &mut original_trace,
            &session.spec.session_id,
            &session.bars,
            &session.ranges,
            &original_candidates,
            &original_tape,
        )?;
        update_trace(
            &mut normalized_trace,
            &session.spec.session_id,
            &normalized_bars,
            &normalized_ranges,
            &normalized_candidates,
            &normalized_tape,
        )?;
        normalized_sessions.push(AtlasSession {
            spec: session.spec.clone(),
            month: session.month.clone(),
            bars: normalized_bars,
            ranges: normalized_ranges,
            candidates: normalized_candidates,
            path_complete: session.path_complete,
        });
    }

    let original_trace_sha256 = finish(original_trace);
    let normalized_trace_sha256 = finish(normalized_trace);
    let original_products = obs_open_04a::metrology::execute(sessions)?;
    let normalized_products = obs_open_04a::metrology::execute(&normalized_sessions)?;
    let original_metrology_sha256 = canonical_json_hash(&original_products)?;
    let normalized_metrology_sha256 = canonical_json_hash(&normalized_products)?;
    let trace_equal = original_trace_sha256 == normalized_trace_sha256
        && range_mismatches == 0
        && tape_mismatches == 0;
    let products_equal = original_metrology_sha256 == normalized_metrology_sha256;
    let lossless = normalized_sessions.len() == sessions.len()
        && off_grid == 0
        && bit_mismatches == 0
        && time_mismatches == 0
        && ohlc_failures == 0
        && trace_equal
        && products_equal;
    let (input_bridge, result, disposition) = if lossless {
        (
            "SEMANTICS_PRESERVING_NORMALIZATION",
            "04A_DA_OBSERVER_TRACE_PRESERVED_BY_INTEGER_TICK_AND_NANOSECOND_STORAGE_BRIDGE",
            "ADVANCE_WITH_RESTRICTION",
        )
    } else if off_grid > 0 || bit_mismatches > 0 {
        (
            "KNOWN_LOSSY_NORMALIZATION",
            "NORMALIZATION_DOES_NOT_PRESERVE_EXACT_04A_INPUT_VALUES",
            "REBASE",
        )
    } else {
        (
            "NOT_EQUIVALENT",
            "NORMALIZED_INPUT_CHANGES_04A_OBSERVER_BEHAVIOR",
            "FORK",
        )
    };
    Ok(BridgeAudit {
        schema: "OBS_OPEN_G0_INPUT_BRIDGE_AUDIT_V1",
        sessions: sessions.len(),
        bars,
        scalar_prices,
        canonical_stream_sha256: finish(canonical_hash),
        original_trace_sha256,
        normalized_trace_sha256,
        original_metrology_sha256,
        normalized_metrology_sha256,
        price_scale: PRICE_SCALE,
        tick_size_display_units: 1.0 / PRICE_SCALE as f64,
        maximum_admitted_scale_error_ticks: MAX_SCALE_ERROR_TICKS,
        off_grid_price_values: off_grid,
        f64_bit_roundtrip_mismatches: bit_mismatches,
        timestamp_roundtrip_mismatches: time_mismatches,
        ohlc_invariant_failures: ohlc_failures,
        range_object_mismatches: range_mismatches,
        candidate_tape_mismatches: tape_mismatches,
        observer_trace_equal: trace_equal,
        metrology_products_equal: products_equal,
        exact_historical_byte_equivalence: false,
        source_time_resolution_ns: SOURCE_TIME_RESOLUTION_NS,
        canonical_storage_resolution_ns: 1,
        observation_cadence_ns: OBSERVATION_CADENCE_NS,
        input_bridge,
        direct_canonical_l2_drop_in: false,
        restriction: "G1_MAY_CONSUME_CANONICAL_INTEGER_M1_BRIDGE_V1_ONLY; CURRENT_CANONICAL_L2_M4_M20_H2_H4_BAR_ENGINE_IS_NOT_04A_SOURCE_AUTHORITY",
        question_status: "CLOSED",
        result,
        disposition,
    })
}

struct NormalizedBar {
    canonical: Option<CanonicalM1Bar>,
    off_grid_values: usize,
    bit_mismatches: usize,
    time_mismatches: usize,
}

fn normalize_bar(bar: &Bar) -> NormalizedBar {
    let values = [bar.open, bar.high, bar.low, bar.close];
    let mut ticks = [0i64; 4];
    let mut off_grid = 0;
    let mut bit_mismatches = 0;
    for (index, value) in values.into_iter().enumerate() {
        match price_to_ticks(value) {
            Some(tick) => {
                ticks[index] = tick;
                bit_mismatches +=
                    usize::from((tick as f64 / PRICE_SCALE as f64).to_bits() != value.to_bits());
            }
            None => off_grid += 1,
        }
    }
    let open_ns = bar.open_time.checked_mul(STORAGE_NS_PER_SOURCE_SECOND);
    let close_ns = bar.close_time.checked_mul(STORAGE_NS_PER_SOURCE_SECOND);
    let time_mismatches = usize::from(open_ns.is_none() || close_ns.is_none())
        + usize::from(open_ns.is_some_and(|v| v / STORAGE_NS_PER_SOURCE_SECOND != bar.open_time))
        + usize::from(close_ns.is_some_and(|v| v / STORAGE_NS_PER_SOURCE_SECOND != bar.close_time));
    let canonical =
        (off_grid == 0 && open_ns.is_some() && close_ns.is_some()).then_some(CanonicalM1Bar {
            open_time_ns: open_ns.unwrap_or_default(),
            close_time_ns: close_ns.unwrap_or_default(),
            open_ticks: ticks[0],
            high_ticks: ticks[1],
            low_ticks: ticks[2],
            close_ticks: ticks[3],
            price_scale: PRICE_SCALE,
            source_time_resolution_ns: SOURCE_TIME_RESOLUTION_NS,
            observation_cadence_ns: OBSERVATION_CADENCE_NS,
        });
    NormalizedBar {
        canonical,
        off_grid_values: off_grid,
        bit_mismatches,
        time_mismatches,
    }
}

pub fn price_to_ticks(value: f64) -> Option<i64> {
    if !value.is_finite() {
        return None;
    }
    let scaled = value * PRICE_SCALE as f64;
    let rounded = scaled.round();
    if (scaled - rounded).abs() > MAX_SCALE_ERROR_TICKS
        || rounded < i64::MIN as f64
        || rounded > i64::MAX as f64
    {
        None
    } else {
        Some(rounded as i64)
    }
}

fn restored_bar(original: &Bar, canonical: &CanonicalM1Bar) -> Bar {
    Bar {
        source_row_id: original.source_row_id.clone(),
        open_time: canonical.open_time_ns / STORAGE_NS_PER_SOURCE_SECOND,
        close_time: canonical.close_time_ns / STORAGE_NS_PER_SOURCE_SECOND,
        open: canonical.open_ticks as f64 / PRICE_SCALE as f64,
        high: canonical.high_ticks as f64 / PRICE_SCALE as f64,
        low: canonical.low_ticks as f64 / PRICE_SCALE as f64,
        close: canonical.close_ticks as f64 / PRICE_SCALE as f64,
        coverage: original.coverage.clone(),
    }
}

fn update_canonical_digest(hash: &mut Sha256, session_id: &[u8], bar: &CanonicalM1Bar) {
    hash.update((session_id.len() as u64).to_le_bytes());
    hash.update(session_id);
    for value in [
        bar.open_time_ns,
        bar.close_time_ns,
        bar.open_ticks,
        bar.high_ticks,
        bar.low_ticks,
        bar.close_ticks,
        bar.price_scale,
        bar.source_time_resolution_ns,
        bar.observation_cadence_ns,
    ] {
        hash.update(value.to_le_bytes());
    }
}

fn update_trace<T: Serialize, U: Serialize, V: Serialize>(
    hash: &mut Sha256,
    session_id: &str,
    bars: &[Bar],
    ranges: &T,
    candidates: &U,
    tape: &V,
) -> Result<(), serde_json::Error> {
    hash.update((session_id.len() as u64).to_le_bytes());
    hash.update(session_id.as_bytes());
    hash.update(serde_json::to_vec(bars)?);
    hash.update(serde_json::to_vec(ranges)?);
    hash.update(serde_json::to_vec(candidates)?);
    hash.update(serde_json::to_vec(tape)?);
    Ok(())
}

fn canonical_json_hash<T: Serialize>(value: &T) -> Result<String, serde_json::Error> {
    let value = serde_json::to_value(value)?;
    Ok(crate::authority::sha256(&serde_json::to_vec(&value)?))
}

fn finish(hash: Sha256) -> String {
    format!("{:x}", hash.finalize())
}
