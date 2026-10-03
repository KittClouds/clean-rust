use crate::model::{ContextAuthority, EpistemicStatus, TransitionResult, WitnessTrace};
use obs_open_04a_g1::kernel::{init, step};
use obs_open_04a_g1::model::{
    CompletedObservation, CoverageState, InputAuthority, KernelContext, KernelState, RangeContext,
};

const START: i64 = 2_000_000_000_000;
const MINUTE: i64 = 60_000_000_000;

pub fn context(id: &str, bars: i64) -> KernelContext {
    let ranges = (1..=30)
        .map(|k| RangeContext {
            k,
            high_ticks: 10_000 + i64::from(k),
            low_ticks: 9_900 - i64::from(k),
            freeze_commit_time_ns: START + i64::from(k) * MINUTE,
        })
        .collect::<Vec<_>>()
        .into_boxed_slice();
    KernelContext {
        session_id: id.into(),
        session_start_ns: START,
        session_terminal_ns: START + bars * MINUTE,
        price_scale: 100,
        source_time_resolution_ns: 1_000_000_000,
        storage_time_resolution_ns: 1,
        observation_cadence_ns: MINUTE,
        ranges,
    }
}

pub fn observation(index: usize, high: i64, low: i64, close: i64) -> CompletedObservation {
    CompletedObservation {
        input_authority: InputAuthority::SyntheticSequenceFixture,
        source_row_id: format!("SYNTH-{index:03}"),
        event_time_ns: START + index as i64 * MINUTE,
        knowledge_time_ns: START + (index as i64 + 1) * MINUTE,
        open_ticks: close.clamp(low, high),
        high_ticks: high,
        low_ticks: low,
        close_ticks: close,
        price_scale: 100,
        source_time_resolution_ns: 1_000_000_000,
        observation_cadence_ns: MINUTE,
        coverage: CoverageState::Complete,
    }
}

fn make_applied(
    id: &str,
    establishes: &[&str],
    context: KernelContext,
    prefix: Vec<CompletedObservation>,
) -> Result<WitnessTrace, String> {
    let target_input = prefix.last().ok_or("EMPTY_WITNESS")?.clone();
    let mut state = init(&context).map_err(|e| e.to_string())?;
    for input in &prefix[..prefix.len() - 1] {
        state = step(&state, input, &context)
            .map_err(|e| e.to_string())?
            .state;
    }
    let prior = state.clone();
    let applied = step(&state, &target_input, &context).map_err(|e| e.to_string())?;
    Ok(WitnessTrace {
        witness_id: id.into(),
        authority: EpistemicStatus::ReachableWithWitnessTrace,
        context_authority: ContextAuthority::SyntheticSemanticFixtureContext,
        establishes: establishes.iter().map(|x| (*x).into()).collect(),
        context,
        prefix,
        target_prior_state: prior,
        target_input,
        target_result: TransitionResult::Applied {
            next_state: applied.state,
            emissions: applied.emissions,
        },
        historical_instantiation_claimed: false,
    })
}

fn make_rejected(
    id: &str,
    establishes: &[&str],
    context: KernelContext,
    accepted_prefix: Vec<CompletedObservation>,
    target: CompletedObservation,
) -> Result<WitnessTrace, String> {
    let mut state = init(&context).map_err(|e| e.to_string())?;
    for input in &accepted_prefix {
        state = step(&state, input, &context)
            .map_err(|e| e.to_string())?
            .state;
    }
    let reason = step(&state, &target, &context)
        .expect_err("rejection fixture must reject")
        .to_string();
    let mut prefix = accepted_prefix;
    prefix.push(target.clone());
    Ok(WitnessTrace {
        witness_id: id.into(),
        authority: EpistemicStatus::ReachableWithWitnessTrace,
        context_authority: ContextAuthority::SyntheticSemanticFixtureContext,
        establishes: establishes.iter().map(|x| (*x).into()).collect(),
        context,
        prefix,
        target_prior_state: state,
        target_input: target,
        target_result: TransitionResult::Rejected { reason },
        historical_instantiation_claimed: false,
    })
}

pub fn witness_corpus() -> Result<Vec<WitnessTrace>, String> {
    let base = observation(0, 10_000, 9_900, 9_950);
    let upper = observation(1, 10_050, 9_910, 10_020);
    let lower = observation(1, 9_990, 9_850, 9_880);
    let both = observation(1, 10_060, 9_840, 9_960);
    let equal = observation(1, 10_000, 9_900, 9_950);
    let mut output = vec![
        make_applied(
            "W_INITIALIZE",
            &["INITIALIZATION", "BOTH_CANDIDATE_ID_1"],
            context("W_INITIALIZE", 40),
            vec![base.clone()],
        )?,
        make_applied(
            "W_PERSIST_EQUAL",
            &["PERSISTENCE", "EQUALITY_NO_RENEWAL", "AGE_INCREMENT"],
            context("W_PERSIST_EQUAL", 40),
            vec![base.clone(), equal.clone()],
        )?,
        make_applied(
            "W_UPPER_RENEWAL",
            &["UPPER_RENEWAL", "UPPER_ID_INCREMENT", "UPPER_AGE_RESET"],
            context("W_UPPER_RENEWAL", 40),
            vec![base.clone(), upper],
        )?,
        make_applied(
            "W_LOWER_RENEWAL",
            &["LOWER_RENEWAL", "LOWER_ID_INCREMENT", "LOWER_AGE_RESET"],
            context("W_LOWER_RENEWAL", 40),
            vec![base.clone(), lower],
        )?,
        make_applied(
            "W_SIMULTANEOUS_RENEWAL",
            &["SIMULTANEOUS_UPPER_LOWER_RENEWAL", "ORDERED_EMISSIONS"],
            context("W_SIMULTANEOUS_RENEWAL", 40),
            vec![base.clone(), both],
        )?,
    ];

    let mut long = vec![base.clone()];
    for i in 1..20 {
        long.push(observation(i, 10_000, 9_900, 9_950));
    }
    output.push(make_applied(
        "W_LONG_AGE",
        &["LONG_AGE", "BIRTH_ORDINAL_TIME_IDENTITY"],
        context("W_LONG_AGE", 40),
        long,
    )?);

    let mut freeze = Vec::with_capacity(30);
    for i in 0..30 {
        freeze.push(observation(i, 10_000, 9_900, 9_950));
    }
    output.push(make_applied(
        "W_RANGE_BECOMES_AVAILABLE",
        &["R30_UNAVAILABLE_THEN_AVAILABLE", "LOCATION_IN_ZONE"],
        context("W_RANGE_BECOMES_AVAILABLE", 40),
        freeze,
    )?);

    output.push(make_applied(
        "W_LOCATION_ABOVE",
        &["LOCATION_ABOVE", "UPPER_EXTENSION_POSITIVE"],
        context("W_LOCATION_ABOVE", 40),
        vec![observation(0, 10_100, 9_950, 10_080)],
    )?);
    output.push(make_applied(
        "W_LOCATION_BELOW",
        &["LOCATION_BELOW", "LOWER_EXTENSION_POSITIVE"],
        context("W_LOCATION_BELOW", 40),
        vec![observation(0, 9_950, 9_800, 9_820)],
    )?);

    let mut incomplete = base.clone();
    incomplete.coverage = CoverageState::Incomplete;
    output.push(make_applied(
        "W_COVERAGE_INCOMPLETE",
        &["COVERAGE_INCOMPLETE_COPY"],
        context("W_COVERAGE_INCOMPLETE", 40),
        vec![incomplete],
    )?);

    let change = vec![base.clone(), observation(1, 10_100, 9_900, 10_050)];
    output.push(make_applied(
        "W_LOCATION_CHANGE",
        &["LOCATION_CHANGE_EMISSION"],
        context("W_LOCATION_CHANGE", 40),
        change,
    )?);
    output.push(make_applied(
        "W_SESSION_TERMINAL",
        &["SESSION_TERMINAL_BOUNDARY"],
        context("W_SESSION_TERMINAL", 2),
        vec![base.clone(), equal.clone()],
    )?);

    let mut gap = observation(2, 10_000, 9_900, 9_950);
    gap.source_row_id = "SYNTH-GAP".into();
    output.push(make_rejected(
        "W_REJECT_GAP",
        &["REJECTED_OBSERVATION_SEQUENCE_GAP"],
        context("W_REJECT_GAP", 40),
        vec![base.clone()],
        gap,
    )?);
    let mut bad_authority = base.clone();
    bad_authority.input_authority = InputAuthority::CurrentCanonicalL2Runtime;
    output.push(make_rejected(
        "W_REJECT_AUTHORITY",
        &["REJECTED_UNQUALIFIED_INPUT_AUTHORITY"],
        context("W_REJECT_AUTHORITY", 40),
        vec![],
        bad_authority,
    )?);
    let mut bad_bar = base.clone();
    bad_bar.low_ticks = 10_001;
    output.push(make_rejected(
        "W_REJECT_BAR",
        &["REJECTED_INVALID_BAR_GEOMETRY"],
        context("W_REJECT_BAR", 40),
        vec![],
        bad_bar,
    )?);
    let out_of_session = observation(1, 10_000, 9_900, 9_950);
    output.push(make_rejected(
        "W_REJECT_TERMINAL",
        &["REJECTED_OUTSIDE_SESSION"],
        context("W_REJECT_TERMINAL", 1),
        vec![base],
        out_of_session,
    )?);
    Ok(output)
}

pub fn replay_witness(witness: &WitnessTrace) -> Result<TransitionResult, String> {
    let mut state = init(&witness.context).map_err(|e| e.to_string())?;
    for input in &witness.prefix[..witness.prefix.len() - 1] {
        state = step(&state, input, &witness.context)
            .map_err(|e| e.to_string())?
            .state;
    }
    if state != witness.target_prior_state {
        return Err("WITNESS_PRIOR_STATE_DRIFT".into());
    }
    Ok(
        match step(&state, &witness.target_input, &witness.context) {
            Ok(value) => TransitionResult::Applied {
                next_state: value.state,
                emissions: value.emissions,
            },
            Err(error) => TransitionResult::Rejected {
                reason: error.to_string(),
            },
        },
    )
}

pub fn initial_state(context: &KernelContext) -> Result<KernelState, String> {
    init(context).map_err(|e| e.to_string())
}
