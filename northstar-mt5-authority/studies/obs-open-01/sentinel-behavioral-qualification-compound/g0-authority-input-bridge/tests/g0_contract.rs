use obs_open_04a_g0::bridge::price_to_ticks;
use obs_open_04a_g0::{
    OBSERVATION_CADENCE_NS, PRICE_SCALE, SOURCE_TIME_RESOLUTION_NS, STORAGE_NS_PER_SOURCE_SECOND,
};
use obs_open_meas02::{Bar, build_candidates_and_tape, build_ranges, session_spec};

fn bar(index: i64, open: f64, high: f64, low: f64, close: f64) -> Bar {
    Bar {
        source_row_id: format!("SYNTH:{index}"),
        open_time: 1_704_187_800 + index * 60,
        close_time: 1_704_187_860 + index * 60,
        open,
        high,
        low,
        close,
        coverage: "COMPLETE".into(),
    }
}

#[test]
fn qualified_price_grid_roundtrips_exact_float_bits() {
    for value in [37_731.90, 37_736.10, 37_700.70, 40_000.00, 40_000.01] {
        let ticks = price_to_ticks(value).expect("qualified cent grid");
        assert_eq!(
            (ticks as f64 / PRICE_SCALE as f64).to_bits(),
            value.to_bits()
        );
    }
}

#[test]
fn fractional_tick_and_nonfinite_values_fail_closed() {
    assert_eq!(price_to_ticks(100.005), None);
    assert_eq!(price_to_ticks(f64::NAN), None);
    assert_eq!(price_to_ticks(f64::INFINITY), None);
}

#[test]
fn integer_normalization_preserves_equality_and_strict_order() {
    let values = [100.00, 100.00, 100.01, 100.02];
    let ticks = values.map(|value| price_to_ticks(value).unwrap());
    assert_eq!(ticks[0], ticks[1]);
    assert!(ticks[1] < ticks[2] && ticks[2] < ticks[3]);
}

#[test]
fn nanosecond_storage_preserves_seconds_without_claiming_finer_source_time() {
    let seconds = 1_704_187_800_i64;
    let stored = seconds.checked_mul(STORAGE_NS_PER_SOURCE_SECOND).unwrap();
    assert_eq!(stored / STORAGE_NS_PER_SOURCE_SECOND, seconds);
    assert_eq!(SOURCE_TIME_RESOLUTION_NS, 1_000_000_000);
    assert_eq!(OBSERVATION_CADENCE_NS, 60_000_000_000);
    assert_ne!(SOURCE_TIME_RESOLUTION_NS, 1);
}

#[test]
fn normalized_fixture_preserves_range_and_candidate_tape() {
    let spec = session_spec("SYNTH_G0", "2024-01-02", 120, "DISCOVERY").unwrap();
    let mut original = vec![
        bar(0, 100.00, 101.00, 99.00, 100.50),
        bar(1, 100.50, 102.00, 99.00, 101.00),
        bar(2, 101.00, 102.00, 98.00, 99.00),
        bar(3, 99.00, 103.00, 97.00, 102.00),
    ];
    for index in 4..35 {
        original.push(bar(index, 100.00, 102.00, 98.00, 101.00));
    }
    let normalized = original
        .iter()
        .map(|source| Bar {
            source_row_id: source.source_row_id.clone(),
            open_time: source.open_time * STORAGE_NS_PER_SOURCE_SECOND
                / STORAGE_NS_PER_SOURCE_SECOND,
            close_time: source.close_time * STORAGE_NS_PER_SOURCE_SECOND
                / STORAGE_NS_PER_SOURCE_SECOND,
            open: price_to_ticks(source.open).unwrap() as f64 / PRICE_SCALE as f64,
            high: price_to_ticks(source.high).unwrap() as f64 / PRICE_SCALE as f64,
            low: price_to_ticks(source.low).unwrap() as f64 / PRICE_SCALE as f64,
            close: price_to_ticks(source.close).unwrap() as f64 / PRICE_SCALE as f64,
            coverage: source.coverage.clone(),
        })
        .collect::<Vec<_>>();
    assert_eq!(
        serde_json::to_vec(&original).unwrap(),
        serde_json::to_vec(&normalized).unwrap()
    );
    assert_eq!(
        serde_json::to_vec(&build_ranges(&spec, &original).unwrap()).unwrap(),
        serde_json::to_vec(&build_ranges(&spec, &normalized).unwrap()).unwrap()
    );
    assert_eq!(
        serde_json::to_vec(&build_candidates_and_tape(&spec, &original).unwrap()).unwrap(),
        serde_json::to_vec(&build_candidates_and_tape(&spec, &normalized).unwrap()).unwrap()
    );
}

#[test]
fn represented_value_identity_is_not_byte_identity() {
    let text = b"37731.90";
    let ticks = price_to_ticks(37_731.90).unwrap().to_le_bytes();
    assert_ne!(text.as_slice(), ticks.as_slice());
}
