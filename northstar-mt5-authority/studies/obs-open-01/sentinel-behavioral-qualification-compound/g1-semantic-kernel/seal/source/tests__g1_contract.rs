use obs_open_04a_g1::kernel::{init, project_state_to_04a, step};
use obs_open_04a_g1::model::{
    CompletedObservation, CoverageState, InputAuthority, KernelContext, KernelError, Location,
    RangeContext,
};

fn context() -> KernelContext {
    let start = 1_700_000_000_i64 * 1_000_000_000;
    let ranges = (1..=30_u8)
        .map(|k| RangeContext {
            k,
            high_ticks: 10_000,
            low_ticks: 9_900,
            freeze_commit_time_ns: start + i64::from(k) * 60_000_000_000,
        })
        .collect::<Vec<_>>()
        .into_boxed_slice();
    KernelContext {
        session_id: "SYN".into(),
        session_start_ns: start,
        session_terminal_ns: start + 390 * 60_000_000_000,
        price_scale: 100,
        source_time_resolution_ns: 1_000_000_000,
        storage_time_resolution_ns: 1,
        observation_cadence_ns: 60_000_000_000,
        ranges,
    }
}

fn observation(index: i64, high: i64, low: i64, close: i64) -> CompletedObservation {
    let start = 1_700_000_000_i64 * 1_000_000_000 + index * 60_000_000_000;
    CompletedObservation {
        input_authority: InputAuthority::SyntheticSequenceFixture,
        source_row_id: format!("SYN:{index}"),
        event_time_ns: start,
        knowledge_time_ns: start + 60_000_000_000,
        open_ticks: close,
        high_ticks: high,
        low_ticks: low,
        close_ticks: close,
        price_scale: 100,
        source_time_resolution_ns: 1_000_000_000,
        observation_cadence_ns: 60_000_000_000,
        coverage: CoverageState::Complete,
    }
}

#[test]
fn first_step_initializes_exact_candidates() {
    let context = context();
    let state = init(&context).unwrap();
    let result = step(&state, &observation(0, 10_000, 9_900, 9_950), &context).unwrap();
    assert_eq!(result.state.upper.as_ref().unwrap().id, 1);
    assert_eq!(result.state.lower.as_ref().unwrap().id, 1);
    assert_eq!(result.state.upper.as_ref().unwrap().age_bars, 0);
    assert_eq!(result.state.lower.as_ref().unwrap().age_bars, 0);
    // Commit + upper/new-ID + lower/new-ID + R01 initial location at freeze.
    assert_eq!(result.emissions.ordered.len(), 6);
}

#[test]
fn equality_holds_candidate_and_increments_age() {
    let context = context();
    let first = step(
        &init(&context).unwrap(),
        &observation(0, 10_000, 9_900, 9_950),
        &context,
    )
    .unwrap();
    let second = step(
        &first.state,
        &observation(1, 10_000, 9_900, 9_950),
        &context,
    )
    .unwrap();
    assert_eq!(second.state.upper.as_ref().unwrap().id, 1);
    assert_eq!(second.state.lower.as_ref().unwrap().id, 1);
    assert_eq!(second.state.upper.as_ref().unwrap().age_bars, 1);
    assert_eq!(second.state.lower.as_ref().unwrap().age_bars, 1);
    assert_eq!(second.state.range_locations[0], Some(Location::InZone));
}

#[test]
fn strict_tick_renewals_preserve_ordered_identity_events() {
    let context = context();
    let first = step(
        &init(&context).unwrap(),
        &observation(0, 10_000, 9_900, 9_950),
        &context,
    )
    .unwrap();
    let second = step(
        &first.state,
        &observation(1, 10_001, 9_899, 9_950),
        &context,
    )
    .unwrap();
    assert_eq!(second.state.upper.as_ref().unwrap().id, 2);
    assert_eq!(second.state.lower.as_ref().unwrap().id, 2);
    let names = serde_json::to_string(&second.emissions).unwrap();
    assert!(names.find("NEW_UPPER_EXTREME").unwrap() < names.find("NEW_LOWER_EXTREME").unwrap());
}

#[test]
fn projection_recovers_exact_ancestor_numeric_surface() {
    let context = context();
    let result = step(
        &init(&context).unwrap(),
        &observation(0, 10_000, 9_900, 9_950),
        &context,
    )
    .unwrap();
    let projected = project_state_to_04a(&result.state, &context).unwrap();
    assert_eq!(projected.upper.value.to_bits(), 100.0_f64.to_bits());
    assert_eq!(projected.lower.value.to_bits(), 99.0_f64.to_bits());
    assert_eq!(projected.knowledge_time, 1_700_000_060);
}

#[test]
fn sequence_gap_fails_closed() {
    let context = context();
    let first = step(
        &init(&context).unwrap(),
        &observation(0, 10_000, 9_900, 9_950),
        &context,
    )
    .unwrap();
    let error = step(
        &first.state,
        &observation(2, 10_000, 9_900, 9_950),
        &context,
    )
    .unwrap_err();
    assert_eq!(error, KernelError::ObservationSequenceGap);
}

#[test]
fn current_canonical_l2_does_not_inherit_g1_authority() {
    let context = context();
    let mut input = observation(0, 10_000, 9_900, 9_950);
    input.input_authority = InputAuthority::CurrentCanonicalL2Runtime;
    let error = step(&init(&context).unwrap(), &input, &context).unwrap_err();
    assert_eq!(error, KernelError::InputAuthorityNotQualifiedForG1);
}
