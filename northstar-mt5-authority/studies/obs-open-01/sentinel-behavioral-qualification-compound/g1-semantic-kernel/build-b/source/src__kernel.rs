use crate::model::{
    CandidateState, CompletedObservation, CoverageState, Emission, InputAuthority, KernelContext,
    KernelEmissions, KernelError, KernelState, Location, StepResult,
};
use obs_open_04a::model::{
    CandidateState as AncestorCandidate, CommittedState as AncestorState,
    Location as AncestorLocation,
};

pub fn init(context: &KernelContext) -> Result<KernelState, KernelError> {
    validate_context(context)?;
    let count = context.ranges.len();
    Ok(KernelState {
        initialized: false,
        bar_index: None,
        knowledge_time_ns: None,
        upper: None,
        lower: None,
        close_ticks: None,
        upper_giveback_ticks: None,
        lower_giveback_ticks: None,
        range_locations: vec![None; count].into_boxed_slice(),
        upper_extensions_ticks: vec![None; count].into_boxed_slice(),
        lower_extensions_ticks: vec![None; count].into_boxed_slice(),
        window_active: false,
        coverage_complete: false,
    })
}

pub fn step(
    prior: &KernelState,
    observation: &CompletedObservation,
    context: &KernelContext,
) -> Result<StepResult, KernelError> {
    validate_context(context)?;
    validate_state(prior, context)?;
    validate_observation(prior, observation, context)?;

    let bar_index = match prior.bar_index {
        Some(value) => value
            .checked_add(1)
            .ok_or(KernelError::ArithmeticOverflow)?,
        None => 0,
    };
    let prior_upper = prior.upper.as_ref();
    let prior_lower = prior.lower.as_ref();
    let new_upper = prior_upper.is_none_or(|x| observation.high_ticks > x.value_ticks);
    let new_lower = prior_lower.is_none_or(|x| observation.low_ticks < x.value_ticks);
    let upper = advance_upper(prior_upper, observation, bar_index, new_upper)?;
    let lower = advance_lower(prior_lower, observation, bar_index, new_lower)?;

    let mut locations = Vec::with_capacity(context.ranges.len());
    let mut upper_extensions = Vec::with_capacity(context.ranges.len());
    let mut lower_extensions = Vec::with_capacity(context.ranges.len());
    for range in &context.ranges {
        if observation.knowledge_time_ns < range.freeze_commit_time_ns {
            locations.push(None);
            upper_extensions.push(None);
            lower_extensions.push(None);
        } else {
            locations.push(Some(location(
                observation.close_ticks,
                range.high_ticks,
                range.low_ticks,
            )));
            upper_extensions.push(Some((upper.value_ticks - range.high_ticks).max(0)));
            lower_extensions.push(Some((range.low_ticks - lower.value_ticks).max(0)));
        }
    }

    let state = KernelState {
        initialized: true,
        bar_index: Some(bar_index),
        knowledge_time_ns: Some(observation.knowledge_time_ns),
        upper_giveback_ticks: Some((upper.value_ticks - observation.close_ticks).max(0)),
        lower_giveback_ticks: Some((observation.close_ticks - lower.value_ticks).max(0)),
        upper: Some(upper),
        lower: Some(lower),
        close_ticks: Some(observation.close_ticks),
        range_locations: locations.into_boxed_slice(),
        upper_extensions_ticks: upper_extensions.into_boxed_slice(),
        lower_extensions_ticks: lower_extensions.into_boxed_slice(),
        window_active: true,
        coverage_complete: observation.coverage == CoverageState::Complete,
    };
    let emissions = emit(prior, &state, observation, new_upper, new_lower);
    Ok(StepResult { state, emissions })
}

fn advance_upper(
    prior: Option<&CandidateState>,
    observation: &CompletedObservation,
    bar_index: u16,
    renewal: bool,
) -> Result<CandidateState, KernelError> {
    match prior {
        Some(value) if renewal => Ok(CandidateState {
            id: value
                .id
                .checked_add(1)
                .ok_or(KernelError::ArithmeticOverflow)?,
            value_ticks: observation.high_ticks,
            birth_bar_index: bar_index,
            birth_knowledge_time_ns: observation.knowledge_time_ns,
            age_bars: 0,
        }),
        Some(value) => Ok(CandidateState {
            age_bars: value
                .age_bars
                .checked_add(1)
                .ok_or(KernelError::ArithmeticOverflow)?,
            ..value.clone()
        }),
        None => Ok(CandidateState {
            id: 1,
            value_ticks: observation.high_ticks,
            birth_bar_index: 0,
            birth_knowledge_time_ns: observation.knowledge_time_ns,
            age_bars: 0,
        }),
    }
}

fn advance_lower(
    prior: Option<&CandidateState>,
    observation: &CompletedObservation,
    bar_index: u16,
    renewal: bool,
) -> Result<CandidateState, KernelError> {
    match prior {
        Some(value) if renewal => Ok(CandidateState {
            id: value
                .id
                .checked_add(1)
                .ok_or(KernelError::ArithmeticOverflow)?,
            value_ticks: observation.low_ticks,
            birth_bar_index: bar_index,
            birth_knowledge_time_ns: observation.knowledge_time_ns,
            age_bars: 0,
        }),
        Some(value) => Ok(CandidateState {
            age_bars: value
                .age_bars
                .checked_add(1)
                .ok_or(KernelError::ArithmeticOverflow)?,
            ..value.clone()
        }),
        None => Ok(CandidateState {
            id: 1,
            value_ticks: observation.low_ticks,
            birth_bar_index: 0,
            birth_knowledge_time_ns: observation.knowledge_time_ns,
            age_bars: 0,
        }),
    }
}

fn emit(
    prior: &KernelState,
    state: &KernelState,
    observation: &CompletedObservation,
    new_upper: bool,
    new_lower: bool,
) -> KernelEmissions {
    let upper_id = state.upper.as_ref().expect("qualified state").id;
    let lower_id = state.lower.as_ref().expect("qualified state").id;
    let mut ordered = Vec::with_capacity(35);
    ordered.push(Emission::ObservationCommit {
        source_row_id: observation.source_row_id.clone(),
        knowledge_time_ns: observation.knowledge_time_ns,
        coverage: observation.coverage,
    });
    if new_upper {
        ordered.push(Emission::NewUpperExtreme {
            candidate_id: upper_id,
        });
        ordered.push(Emission::UpperCandidateIdChange {
            prior: prior.upper.as_ref().map(|x| x.id),
            current: upper_id,
        });
    }
    if new_lower {
        ordered.push(Emission::NewLowerExtreme {
            candidate_id: lower_id,
        });
        ordered.push(Emission::LowerCandidateIdChange {
            prior: prior.lower.as_ref().map(|x| x.id),
            current: lower_id,
        });
    }
    for (index, current) in state.range_locations.iter().enumerate() {
        if let Some(current) = current {
            ordered.push(Emission::LocationTransition {
                k: (index + 1) as u8,
                prior: prior.range_locations[index],
                current: *current,
                knowledge_time_ns: observation.knowledge_time_ns,
            });
        }
    }
    KernelEmissions {
        ordered: ordered.into_boxed_slice(),
    }
}

fn location(close: i64, high: i64, low: i64) -> Location {
    if close > high {
        Location::Above
    } else if close < low {
        Location::Below
    } else {
        Location::InZone
    }
}

fn validate_context(context: &KernelContext) -> Result<(), KernelError> {
    if context.price_scale != obs_open_04a_g0::PRICE_SCALE
        || context.source_time_resolution_ns != obs_open_04a_g0::SOURCE_TIME_RESOLUTION_NS
        || context.storage_time_resolution_ns != 1
        || context.observation_cadence_ns != obs_open_04a_g0::OBSERVATION_CADENCE_NS
        || context.ranges.len() != 30
    {
        return Err(KernelError::InvalidContext("INVALID_KERNEL_CONTEXT"));
    }
    for (index, range) in context.ranges.iter().enumerate() {
        if range.k as usize != index + 1 || range.low_ticks > range.high_ticks {
            return Err(KernelError::InvalidContext("INVALID_RANGE_CONTEXT"));
        }
    }
    Ok(())
}

fn validate_state(state: &KernelState, context: &KernelContext) -> Result<(), KernelError> {
    let count = context.ranges.len();
    if state.range_locations.len() != count
        || state.upper_extensions_ticks.len() != count
        || state.lower_extensions_ticks.len() != count
    {
        return Err(KernelError::StateOutsideExtractedDomain);
    }
    let causal_fields_present = state.bar_index.is_some()
        && state.knowledge_time_ns.is_some()
        && state.upper.is_some()
        && state.lower.is_some()
        && state.close_ticks.is_some()
        && state.upper_giveback_ticks.is_some()
        && state.lower_giveback_ticks.is_some();
    if state.initialized != causal_fields_present || (!state.initialized && state.window_active) {
        return Err(KernelError::StateOutsideExtractedDomain);
    }
    Ok(())
}

fn validate_observation(
    prior: &KernelState,
    observation: &CompletedObservation,
    context: &KernelContext,
) -> Result<(), KernelError> {
    if observation.input_authority != InputAuthority::CanonicalIntegerM1BridgeV1
        && observation.input_authority != InputAuthority::SyntheticSequenceFixture
    {
        return Err(KernelError::InputAuthorityNotQualifiedForG1);
    }
    if observation.price_scale != context.price_scale
        || observation.source_time_resolution_ns != context.source_time_resolution_ns
        || observation.observation_cadence_ns != context.observation_cadence_ns
        || observation.knowledge_time_ns - observation.event_time_ns
            != context.observation_cadence_ns
        || observation.low_ticks > observation.high_ticks
        || observation.low_ticks > observation.open_ticks
        || observation.low_ticks > observation.close_ticks
        || observation.high_ticks < observation.open_ticks
        || observation.high_ticks < observation.close_ticks
    {
        return Err(KernelError::InvalidObservation(
            "INVALID_COMPLETED_OBSERVATION",
        ));
    }
    if let Some(prior_time) = prior.knowledge_time_ns {
        if observation.knowledge_time_ns - prior_time != context.observation_cadence_ns {
            return Err(KernelError::ObservationSequenceGap);
        }
    } else if observation.event_time_ns != context.session_start_ns {
        return Err(KernelError::InvalidObservation(
            "INVALID_SESSION_INITIAL_OBSERVATION",
        ));
    }
    if observation.event_time_ns < context.session_start_ns
        || observation.knowledge_time_ns > context.session_terminal_ns
    {
        return Err(KernelError::InvalidObservation(
            "OBSERVATION_OUTSIDE_SESSION",
        ));
    }
    Ok(())
}

pub fn project_state_to_04a(
    state: &KernelState,
    context: &KernelContext,
) -> Result<AncestorState, KernelError> {
    validate_context(context)?;
    if !state.initialized {
        return Err(KernelError::StateOutsideExtractedDomain);
    }
    let upper = state
        .upper
        .as_ref()
        .ok_or(KernelError::StateOutsideExtractedDomain)?;
    let lower = state
        .lower
        .as_ref()
        .ok_or(KernelError::StateOutsideExtractedDomain)?;
    Ok(AncestorState {
        bar_index: state
            .bar_index
            .ok_or(KernelError::StateOutsideExtractedDomain)?,
        knowledge_time: seconds(state.knowledge_time_ns)?,
        upper: project_candidate(upper)?,
        lower: project_candidate(lower)?,
        close: price(
            state
                .close_ticks
                .ok_or(KernelError::StateOutsideExtractedDomain)?,
        ),
        // Pi_04A reconstructs the ancestor's arithmetic representation from
        // its projected operands. Integer state equality is semantic; it does
        // not widen G0 into byte identity for derived floating arithmetic.
        upper_giveback: (price(upper.value_ticks)
            - price(
                state
                    .close_ticks
                    .ok_or(KernelError::StateOutsideExtractedDomain)?,
            ))
        .max(0.0),
        lower_giveback: (price(
            state
                .close_ticks
                .ok_or(KernelError::StateOutsideExtractedDomain)?,
        ) - price(lower.value_ticks))
        .max(0.0),
        range_locations: state
            .range_locations
            .iter()
            .map(|x| x.map(project_location))
            .collect(),
        upper_extensions: state
            .upper_extensions_ticks
            .iter()
            .zip(&context.ranges)
            .map(|(value, range)| {
                value.map(|_| (price(upper.value_ticks) - price(range.high_ticks)).max(0.0))
            })
            .collect(),
        lower_extensions: state
            .lower_extensions_ticks
            .iter()
            .zip(&context.ranges)
            .map(|(value, range)| {
                value.map(|_| (price(range.low_ticks) - price(lower.value_ticks)).max(0.0))
            })
            .collect(),
        window_active: state.window_active,
        coverage_complete: state.coverage_complete,
    })
}

fn project_candidate(value: &CandidateState) -> Result<AncestorCandidate, KernelError> {
    Ok(AncestorCandidate {
        id: value.id,
        value: price(value.value_ticks),
        birth_bar_index: value.birth_bar_index,
        birth_knowledge_time: seconds(Some(value.birth_knowledge_time_ns))?,
        age_bars: value.age_bars,
    })
}

fn project_location(value: Location) -> AncestorLocation {
    match value {
        Location::InZone => AncestorLocation::InZone,
        Location::Above => AncestorLocation::Above,
        Location::Below => AncestorLocation::Below,
    }
}

fn price(ticks: i64) -> f64 {
    ticks as f64 / obs_open_04a_g0::PRICE_SCALE as f64
}

fn seconds(value: Option<i64>) -> Result<i64, KernelError> {
    let value = value.ok_or(KernelError::StateOutsideExtractedDomain)?;
    if value % obs_open_04a_g0::STORAGE_NS_PER_SOURCE_SECOND != 0 {
        return Err(KernelError::StateOutsideExtractedDomain);
    }
    Ok(value / obs_open_04a_g0::STORAGE_NS_PER_SOURCE_SECOND)
}
