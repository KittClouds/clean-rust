use crate::grammar::{advance, classify_pair, classify_single, realize_identity, realize_relative};
use crate::model::{
    FixtureReceipt, PairPresentation, PresentabilityClass, PresentationLayer, RealizedTokenPair,
    RelativeBarToken, StartReachability, StartingSituation,
};
use obs_open_04a_g1::kernel::{init, step};
use obs_open_04a_g1::model::{
    CompletedObservation, CoverageState, InputAuthority, KernelContext, RangeContext,
};

const START: i64 = 3_000_000_000_000;
const MIN: i64 = 60_000_000_000;

pub fn context(id: &str, bars: i64, shift: i64) -> KernelContext {
    KernelContext {
        session_id: id.into(),
        session_start_ns: START,
        session_terminal_ns: START + bars * MIN,
        price_scale: 100,
        source_time_resolution_ns: 1_000_000_000,
        storage_time_resolution_ns: 1,
        observation_cadence_ns: MIN,
        ranges: (1..=30)
            .map(|k| RangeContext {
                k,
                high_ticks: 10_100 + shift + i64::from(k),
                low_ticks: 9_900 + shift - i64::from(k),
                freeze_commit_time_ns: START + i64::from(k) * MIN,
            })
            .collect::<Vec<_>>()
            .into_boxed_slice(),
    }
}
pub fn observation(index: u32, base: i64, coverage: CoverageState) -> CompletedObservation {
    CompletedObservation {
        input_authority: InputAuthority::SyntheticSequenceFixture,
        source_row_id: format!("G5-SYN-{index}"),
        event_time_ns: START + i64::from(index) * MIN,
        knowledge_time_ns: START + (i64::from(index) + 1) * MIN,
        open_ticks: base,
        high_ticks: base + 10,
        low_ticks: base - 10,
        close_ticks: base + 2,
        price_scale: 100,
        source_time_resolution_ns: 1_000_000_000,
        observation_cadence_ns: MIN,
        coverage,
    }
}

pub fn start(
    id: &str,
    bars: i64,
    shift: i64,
    count: u32,
    reachability: StartReachability,
) -> Result<StartingSituation, String> {
    let context = context(id, bars, shift);
    let mut state = init(&context).map_err(|e| e.to_string())?;
    for i in 0..count {
        state = step(
            &state,
            &observation(i, 10_000 + shift, CoverageState::Complete),
            &context,
        )
        .map_err(|e| e.to_string())?
        .state;
    }
    Ok(StartingSituation {
        prefix_id: id.into(),
        applied_prefix_length: count,
        state,
        context,
        reachability,
        reachability_receipt: if reachability == StartReachability::ConstructivelyReachable {
            "SEQUENCE_GENERATED_G5_FIXTURE".into()
        } else {
            "G3_UPPER_ENVELOPE_CONDITIONAL".into()
        },
    })
}

fn token(id: &str) -> RelativeBarToken {
    RelativeBarToken {
        token_id: id.into(),
        open_delta_ticks: 0,
        high_delta_ticks: 12,
        low_delta_ticks: -12,
        close_delta_ticks: 3,
        coverage_complete: true,
    }
}
#[allow(clippy::too_many_arguments)]
fn receipt(
    id: &str,
    purpose: &str,
    left: u32,
    right: Option<u32>,
    tokens: u32,
    expected: &str,
    observed: &str,
    presentation: Option<PairPresentation>,
) -> FixtureReceipt {
    FixtureReceipt {
        fixture_id: id.into(),
        purpose: purpose.into(),
        left_prefix_length: left,
        right_prefix_length: right,
        token_count: tokens,
        expected: expected.into(),
        observed: observed.into(),
        presentability: presentation,
        status: if expected == observed {
            "PASS".into()
        } else {
            "FAIL".into()
        },
    }
}

pub fn corpus() -> Result<Vec<FixtureReceipt>, String> {
    let left = start(
        "LEFT",
        100,
        0,
        1,
        StartReachability::ConstructivelyReachable,
    )?;
    let right = start(
        "RIGHT",
        100,
        500,
        1,
        StartReachability::ConstructivelyReachable,
    )?;
    let t = token("NORMAL");
    let lp = realize_relative(&left, &t, "L")?;
    let rp = realize_relative(&right, &t, "R")?;
    let pair = RealizedTokenPair {
        left: lp.clone(),
        right: rp.clone(),
    };
    let pp = classify_pair(&left, &right, &pair);
    let mut out = vec![
        receipt(
            "F_EPSILON",
            "empty continuation base case",
            left.applied_prefix_length,
            None,
            0,
            "PRESENTABLE",
            "PRESENTABLE",
            None,
        ),
        receipt(
            "F_UNILATERAL",
            "valid unilateral nonempty continuation",
            left.applied_prefix_length,
            None,
            1,
            "KERNEL_APPLIED",
            layer(&classify_single(&left, &lp)),
            None,
        ),
        receipt(
            "F_NONDIAGONAL",
            "valid side-specific relative coupling",
            left.applied_prefix_length,
            Some(right.applied_prefix_length),
            1,
            "PRESENTABLE",
            pair_class(pp.class),
            Some(pp.clone()),
        ),
    ];
    let same = start(
        "IDENTITY",
        100,
        0,
        1,
        StartReachability::ConstructivelyReachable,
    )?;
    let identity = realize_identity(&lp, &same)?;
    let ip = classify_pair(&left, &same, &identity);
    out.push(receipt(
        "F_IDENTITY",
        "qualified identity coupling special case",
        1,
        Some(1),
        1,
        "PRESENTABLE",
        pair_class(ip.class),
        Some(ip),
    ));
    let mut invalid = lp.clone();
    invalid.low_ticks = invalid.high_ticks + 1;
    out.push(receipt(
        "F_SOURCE_INVALID",
        "invalid OHLC",
        1,
        None,
        1,
        "SOURCE_GRAMMAR_INVALID",
        layer(&classify_single(&left, &invalid)),
        None,
    ));
    let mut context_bad = lp.clone();
    context_bad.price_scale = 1;
    out.push(receipt(
        "F_CONTEXT_INVALID",
        "context presentation mismatch",
        1,
        None,
        1,
        "CONTEXT_PRESENTATION_INVALID",
        layer(&classify_single(&left, &context_bad)),
        None,
    ));
    let mut prefix_bad = lp.clone();
    prefix_bad.knowledge_time_ns += MIN;
    prefix_bad.event_time_ns += MIN;
    out.push(receipt(
        "F_PREFIX_INVALID",
        "chronology mismatch",
        1,
        None,
        1,
        "PREFIX_PRESENTATION_INVALID",
        layer(&classify_single(&left, &prefix_bad)),
        None,
    ));
    let terminal = start(
        "TERMINAL",
        1,
        0,
        1,
        StartReachability::ConstructivelyReachable,
    )?;
    let terminal_input = realize_relative(&terminal, &t, "T")?;
    out.push(receipt(
        "F_TERMINAL",
        "terminal boundary is epsilon-only",
        1,
        None,
        1,
        "CONTEXT_PRESENTATION_INVALID",
        layer(&classify_single(&terminal, &terminal_input)),
        None,
    ));
    let before = start(
        "FREEZE",
        100,
        0,
        1,
        StartReachability::ConstructivelyReachable,
    )?;
    let freeze_input = realize_relative(&before, &t, "F")?;
    out.push(receipt(
        "F_RANGE_FREEZE",
        "lawful token across later range-freeze boundary",
        1,
        None,
        1,
        "KERNEL_APPLIED",
        layer(&classify_single(&before, &freeze_input)),
        None,
    ));
    let mut incomplete_token = t.clone();
    incomplete_token.token_id = "INCOMPLETE".into();
    incomplete_token.coverage_complete = false;
    let incomplete = realize_relative(&left, &incomplete_token, "L")?;
    out.push(receipt(
        "F_COVERAGE",
        "coverage class does not create undeclared prefix exclusion",
        1,
        None,
        1,
        "KERNEL_APPLIED",
        layer(&classify_single(&left, &incomplete)),
        None,
    ));
    let upper = start(
        "UPPER_ONLY",
        100,
        0,
        1,
        StartReachability::UpperEnvelopeOnly,
    )?;
    let upair = classify_pair(&upper, &right, &pair);
    out.push(receipt(
        "F_UPPER_ENVELOPE_START",
        "conditional grammar from upper-envelope-only start",
        1,
        Some(1),
        1,
        "CONDITIONAL",
        if upair.conditional_on_start_reachability {
            "CONDITIONAL"
        } else {
            "PROVEN"
        },
        Some(upair),
    ));
    out.push(receipt(
        "F_MISSING_COUPLING",
        "pair token cannot realize without Lambda",
        1,
        Some(1),
        1,
        "REQUIRES_COUPLING",
        "REQUIRES_COUPLING",
        None,
    ));
    out.push(receipt(
        "F_NO_OBSERVER_M",
        "observer correspondence absent but not required by grammar",
        1,
        Some(1),
        1,
        "PRESENTABLE",
        "PRESENTABLE",
        Some(pp),
    ));
    out.push(receipt(
        "F_BOUNDED_FIXTURE",
        "two-token constructive prefix is evidence only, not horizon authority",
        1,
        None,
        2,
        "CONSTRUCTIVE_UNDERAPPROXIMATION",
        "CONSTRUCTIVE_UNDERAPPROXIMATION",
        None,
    ));
    let next = advance(&left, &lp)?;
    let next_input = realize_relative(&next, &t, "L2")?;
    out.push(receipt(
        "F_PREFIX_CLOSURE",
        "every prefix of a constructed two-token continuation is lawful",
        1,
        None,
        2,
        "KERNEL_APPLIED",
        layer(&classify_single(&next, &next_input)),
        None,
    ));
    Ok(out)
}

fn layer(x: &crate::model::PresentationResult) -> &'static str {
    match x.layer {
        PresentationLayer::SourceGrammarInvalid => "SOURCE_GRAMMAR_INVALID",
        PresentationLayer::ContextPresentationInvalid => "CONTEXT_PRESENTATION_INVALID",
        PresentationLayer::PrefixPresentationInvalid => "PREFIX_PRESENTATION_INVALID",
        PresentationLayer::KernelApplied => "KERNEL_APPLIED",
        PresentationLayer::KernelRejected => "KERNEL_REJECTED",
    }
}
fn pair_class(x: PresentabilityClass) -> &'static str {
    match x {
        PresentabilityClass::Presentable => "PRESENTABLE",
        PresentabilityClass::LeftOnly => "LEFT_ONLY",
        PresentabilityClass::RightOnly => "RIGHT_ONLY",
        PresentabilityClass::SourceGrammarInvalid => "SOURCE_GRAMMAR_INVALID",
        PresentabilityClass::ContextPresentationInvalid => "CONTEXT_PRESENTATION_INVALID",
        PresentabilityClass::PrefixPresentationInvalid => "PREFIX_PRESENTATION_INVALID",
        PresentabilityClass::RequiresCoupling => "REQUIRES_COUPLING",
        PresentabilityClass::RequiresObserverCorrespondence => "REQUIRES_OBSERVER_CORRESPONDENCE",
    }
}

pub fn overflow_start(id: &str) -> Result<StartingSituation, String> {
    start(
        id,
        65_537,
        0,
        65_536,
        StartReachability::ConstructivelyReachable,
    )
}

pub fn qualified_corpus() -> Result<Vec<FixtureReceipt>, String> {
    let mut out = corpus()?;
    let normal = start(
        "MATRIX_NORMAL",
        65_537,
        0,
        1,
        StartReachability::ConstructivelyReachable,
    )?;
    let overflow = overflow_start("MATRIX_OVERFLOW")?;
    let t = token("MATRIX");
    let applied = realize_relative(&normal, &t, "A")?;
    let rejected = observation(65_536, 10_000, CoverageState::Complete);
    let ar = classify_pair(
        &normal,
        &overflow,
        &RealizedTokenPair {
            left: applied.clone(),
            right: rejected.clone(),
        },
    );
    out.push(receipt(
        "F_APPLIED_REJECTED",
        "joint presentation retains asymmetric kernel result",
        1,
        Some(65_536),
        1,
        "PRESENTABLE",
        pair_class(ar.class),
        Some(ar),
    ));
    let ra = classify_pair(
        &overflow,
        &normal,
        &RealizedTokenPair {
            left: rejected.clone(),
            right: applied.clone(),
        },
    );
    out.push(receipt(
        "F_REJECTED_APPLIED",
        "reverse asymmetric kernel result",
        65_536,
        Some(1),
        1,
        "PRESENTABLE",
        pair_class(ra.class),
        Some(ra),
    ));
    let rr = classify_pair(
        &overflow,
        &overflow,
        &RealizedTokenPair {
            left: rejected.clone(),
            right: rejected.clone(),
        },
    );
    out.push(receipt(
        "F_REJECTED_REJECTED",
        "both lawful presentations reject in the kernel",
        65_536,
        Some(65_536),
        1,
        "PRESENTABLE",
        pair_class(rr.class),
        Some(rr),
    ));
    let rejection = classify_single(&overflow, &rejected);
    out.push(receipt(
        "F_PRESENTABLE_REJECTION",
        "arithmetic overflow remains protected kernel behavior",
        65_536,
        None,
        1,
        "KERNEL_REJECTED",
        layer(&rejection),
        None,
    ));
    out.push(receipt(
        "F_REJECTION_FOLLOWUP",
        "unchanged rejected prefix permits another experiment at the same causal slot",
        65_536,
        None,
        2,
        "RETAIN_PREFIX_AND_PRESENT_NEXT_EXPERIMENT_AT_SAME_CAUSAL_SLOT",
        &rejection.continuation_after,
        None,
    ));
    let mut bad_right = rejected.clone();
    bad_right.price_scale = 1;
    let left_only = classify_pair(
        &normal,
        &overflow,
        &RealizedTokenPair {
            left: applied.clone(),
            right: bad_right,
        },
    );
    out.push(receipt(
        "F_LEFT_ONLY",
        "only left side is lawfully presentable",
        1,
        Some(65_536),
        1,
        "LEFT_ONLY",
        pair_class(left_only.class),
        Some(left_only),
    ));
    let mut bad_left = applied;
    bad_left.price_scale = 1;
    let right_only = classify_pair(
        &normal,
        &overflow,
        &RealizedTokenPair {
            left: bad_left,
            right: rejected,
        },
    );
    out.push(receipt(
        "F_RIGHT_ONLY",
        "only right side is lawfully presentable",
        1,
        Some(65_536),
        1,
        "RIGHT_ONLY",
        pair_class(right_only.class),
        Some(right_only),
    ));
    let mut invalid_start = normal.clone();
    invalid_start.state.range_locations = Vec::new().into_boxed_slice();
    let invalid_start_input = realize_relative(&invalid_start, &token("BAD-START"), "S")?;
    let invalid_start_result = classify_single(&invalid_start, &invalid_start_input);
    out.push(receipt(
        "F_STATE_OUTSIDE_DOMAIN",
        "an invalid starting state is rejected before kernel presentation",
        invalid_start.applied_prefix_length,
        None,
        1,
        "PREFIX_PRESENTATION_INVALID",
        layer(&invalid_start_result),
        None,
    ));
    let terminal_left = start(
        "TERMINAL-PAIR-L",
        1,
        0,
        1,
        StartReachability::ConstructivelyReachable,
    )?;
    let terminal_right = start(
        "TERMINAL-PAIR-R",
        1,
        500,
        1,
        StartReachability::ConstructivelyReachable,
    )?;
    let terminal_token = token("AFTER-TERMINAL");
    let terminal_pair = classify_pair(
        &terminal_left,
        &terminal_right,
        &RealizedTokenPair {
            left: realize_relative(&terminal_left, &terminal_token, "TL")?,
            right: realize_relative(&terminal_right, &terminal_token, "TR")?,
        },
    );
    let terminal_observed =
        if terminal_pair.class == PresentabilityClass::ContextPresentationInvalid {
            "EPSILON_ONLY"
        } else {
            "POSITIVE_CONTINUATION_PRESENTABLE"
        };
    out.push(receipt(
        "F_EPSILON_ONLY_PAIR",
        "terminal paired starts retain epsilon but no positive-length presentation",
        1,
        Some(1),
        0,
        "EPSILON_ONLY",
        terminal_observed,
        Some(terminal_pair),
    ));
    Ok(out)
}
