use crate::model::{
    ApproximationDirection, CouplingContract, EpistemicStatus, PairPresentation,
    PresentabilityClass, PresentationLayer, PresentationResult, RealizedTokenPair,
    RelativeBarToken, StartReachability, StartingSituation,
};
use obs_open_04a_g1::kernel::{init, step};
use obs_open_04a_g1::model::{CompletedObservation, CoverageState, InputAuthority, KernelError};

pub fn classify_single(
    start: &StartingSituation,
    input: &CompletedObservation,
) -> PresentationResult {
    if !matches!(
        input.input_authority,
        InputAuthority::CanonicalIntegerM1BridgeV1 | InputAuthority::SyntheticSequenceFixture
    ) || input.low_ticks > input.high_ticks
        || input.low_ticks > input.open_ticks
        || input.low_ticks > input.close_ticks
        || input.high_ticks < input.open_ticks
        || input.high_ticks < input.close_ticks
        || input.knowledge_time_ns.checked_sub(input.event_time_ns)
            != Some(input.observation_cadence_ns)
    {
        return pre(
            PresentationLayer::SourceGrammarInvalid,
            "SOURCE_STIMULUS_GRAMMAR_VIOLATION",
        );
    }
    let c = &start.context;
    if init(c).is_err()
        || input.price_scale != c.price_scale
        || input.source_time_resolution_ns != c.source_time_resolution_ns
        || input.observation_cadence_ns != c.observation_cadence_ns
        || input.event_time_ns < c.session_start_ns
        || input.knowledge_time_ns > c.session_terminal_ns
    {
        return pre(
            PresentationLayer::ContextPresentationInvalid,
            "CONTEXT_PRESENTATION_CONTRACT_VIOLATION",
        );
    }
    if let Some(t) = start.state.knowledge_time_ns {
        if input.knowledge_time_ns.checked_sub(t) != Some(c.observation_cadence_ns) {
            return pre(
                PresentationLayer::PrefixPresentationInvalid,
                "PREFIX_CHRONOLOGY_VIOLATION",
            );
        }
    } else if input.event_time_ns != c.session_start_ns {
        return pre(
            PresentationLayer::PrefixPresentationInvalid,
            "INITIAL_PREFIX_ALIGNMENT_VIOLATION",
        );
    }
    match step(&start.state, input, c) {
        Ok(_) => PresentationResult {
            layer: PresentationLayer::KernelApplied,
            reason: None,
            state_unchanged: Some(false),
            continuation_after: "ADVANCE_TO_APPLIED_PREFIX".into(),
        },
        Err(KernelError::ArithmeticOverflow) => PresentationResult {
            layer: PresentationLayer::KernelRejected,
            reason: Some(KernelError::ArithmeticOverflow.to_string()),
            state_unchanged: Some(true),
            continuation_after: "RETAIN_PREFIX_AND_PRESENT_NEXT_EXPERIMENT_AT_SAME_CAUSAL_SLOT"
                .into(),
        },
        Err(KernelError::StateOutsideExtractedDomain) => pre(
            PresentationLayer::PrefixPresentationInvalid,
            "STARTING_SITUATION_OUTSIDE_G1_DOMAIN",
        ),
        Err(KernelError::ObservationSequenceGap) => pre(
            PresentationLayer::PrefixPresentationInvalid,
            "PREFIX_CHRONOLOGY_VIOLATION",
        ),
        Err(KernelError::InputAuthorityNotQualifiedForG1) => pre(
            PresentationLayer::SourceGrammarInvalid,
            "SOURCE_INPUT_AUTHORITY_INVALID",
        ),
        Err(KernelError::InvalidContext(reason)) => {
            pre(PresentationLayer::ContextPresentationInvalid, reason)
        }
        Err(KernelError::InvalidObservation(reason)) => {
            pre(PresentationLayer::SourceGrammarInvalid, reason)
        }
    }
}

fn pre(layer: PresentationLayer, reason: &str) -> PresentationResult {
    PresentationResult {
        layer,
        reason: Some(reason.into()),
        state_unchanged: None,
        continuation_after: "NOT_PRESENTED_TO_KERNEL".into(),
    }
}

pub fn realize_relative(
    start: &StartingSituation,
    token: &RelativeBarToken,
    side: &str,
) -> Result<CompletedObservation, String> {
    let close = start.state.close_ticks.ok_or("START_HAS_NO_CAUSAL_CLOSE")?;
    let prior_time = start.state.knowledge_time_ns;
    let event = prior_time.unwrap_or(start.context.session_start_ns);
    let knowledge = event
        .checked_add(start.context.observation_cadence_ns)
        .ok_or("TIME_OVERFLOW")?;
    let add = |delta: i64| close.checked_add(delta).ok_or("PRICE_OVERFLOW");
    Ok(CompletedObservation {
        input_authority: InputAuthority::SyntheticSequenceFixture,
        source_row_id: format!("G5-{side}-{}", token.token_id),
        event_time_ns: event,
        knowledge_time_ns: knowledge,
        open_ticks: add(token.open_delta_ticks)?,
        high_ticks: add(token.high_delta_ticks)?,
        low_ticks: add(token.low_delta_ticks)?,
        close_ticks: add(token.close_delta_ticks)?,
        price_scale: start.context.price_scale,
        source_time_resolution_ns: start.context.source_time_resolution_ns,
        observation_cadence_ns: start.context.observation_cadence_ns,
        coverage: if token.coverage_complete {
            CoverageState::Complete
        } else {
            CoverageState::Incomplete
        },
    })
}

pub fn realize_identity(
    left: &CompletedObservation,
    right_start: &StartingSituation,
) -> Result<RealizedTokenPair, String> {
    if left.price_scale != right_start.context.price_scale
        || left.source_time_resolution_ns != right_start.context.source_time_resolution_ns
        || left.observation_cadence_ns != right_start.context.observation_cadence_ns
    {
        return Err("IDENTITY_COUPLING_CONTEXT_MISMATCH".into());
    }
    Ok(RealizedTokenPair {
        left: left.clone(),
        right: left.clone(),
    })
}

pub fn classify_pair(
    left: &StartingSituation,
    right: &StartingSituation,
    pair: &RealizedTokenPair,
) -> PairPresentation {
    let l = classify_single(left, &pair.left);
    let r = classify_single(right, &pair.right);
    let lp = presented(&l);
    let rp = presented(&r);
    let class = match (lp, rp) {
        (true, true) => PresentabilityClass::Presentable,
        (true, false) => PresentabilityClass::LeftOnly,
        (false, true) => PresentabilityClass::RightOnly,
        (false, false) => dominant_pre(&l, &r),
    };
    let conditional_on_start_reachability = !matches!(
        left.reachability,
        StartReachability::ProvenReachable | StartReachability::ConstructivelyReachable
    ) || !matches!(
        right.reachability,
        StartReachability::ProvenReachable | StartReachability::ConstructivelyReachable
    );
    PairPresentation {
        class,
        epistemic_status: if conditional_on_start_reachability {
            EpistemicStatus::Conditional
        } else {
            EpistemicStatus::Proven
        },
        approximation: if conditional_on_start_reachability {
            ApproximationDirection::OverApproximation
        } else {
            ApproximationDirection::Exact
        },
        left: l,
        right: r,
        conditional_on_start_reachability,
    }
}

fn presented(x: &PresentationResult) -> bool {
    matches!(
        x.layer,
        PresentationLayer::KernelApplied | PresentationLayer::KernelRejected
    )
}
fn dominant_pre(a: &PresentationResult, b: &PresentationResult) -> PresentabilityClass {
    if matches!(a.layer, PresentationLayer::SourceGrammarInvalid)
        || matches!(b.layer, PresentationLayer::SourceGrammarInvalid)
    {
        PresentabilityClass::SourceGrammarInvalid
    } else if matches!(a.layer, PresentationLayer::ContextPresentationInvalid)
        || matches!(b.layer, PresentationLayer::ContextPresentationInvalid)
    {
        PresentabilityClass::ContextPresentationInvalid
    } else {
        PresentabilityClass::PrefixPresentationInvalid
    }
}

pub fn advance(
    start: &StartingSituation,
    input: &CompletedObservation,
) -> Result<StartingSituation, String> {
    match step(&start.state, input, &start.context) {
        Ok(result) => Ok(StartingSituation {
            prefix_id: format!("{}+{}", start.prefix_id, input.source_row_id),
            applied_prefix_length: start
                .applied_prefix_length
                .checked_add(1)
                .ok_or("PREFIX_LENGTH_OVERFLOW")?,
            state: result.state,
            context: start.context.clone(),
            reachability: start.reachability,
            reachability_receipt: start.reachability_receipt.clone(),
        }),
        Err(error) => Err(error.to_string()),
    }
}

pub fn relative_coupling() -> CouplingContract {
    CouplingContract {
        coupling_id: "RELATIVE_COMPLETED_BAR_COUPLING_V1".into(),
        kind: "PREFIX_SENSITIVE_SIDE_SPECIFIC_REALIZATION".into(),
        prefix_sensitive: true,
        observer_correspondence_dependency: "NONE".into(),
        identity_special_case: false,
        temporal_alignment:
            "NEXT_CAUSAL_SLOT_UNDER_EACH_SIDE_CONTEXT; ABSOLUTE_TIMESTAMP_EQUALITY_NOT_REQUIRED"
                .into(),
        price_alignment: "COMMON_INTEGER_TICK_DELTAS_RELATIVE_TO_EACH_SIDE_COMMITTED_CLOSE".into(),
    }
}
pub fn identity_coupling() -> CouplingContract {
    CouplingContract {
        coupling_id: "QUALIFIED_IDENTITY_PRESENTATION_V1".into(),
        kind: "IDENTICAL_RAW_COMPLETED_OBSERVATION_SPECIAL_CASE".into(),
        prefix_sensitive: true,
        observer_correspondence_dependency: "NONE".into(),
        identity_special_case: true,
        temporal_alignment:
            "REQUIRES_LITERAL_STIMULUS_TO_SATISFY_BOTH_CONTEXT_AND_PREFIX_CONTRACTS".into(),
        price_alignment: "REQUIRES_SHARED_CANONICAL_PRICE_SCALE".into(),
    }
}
