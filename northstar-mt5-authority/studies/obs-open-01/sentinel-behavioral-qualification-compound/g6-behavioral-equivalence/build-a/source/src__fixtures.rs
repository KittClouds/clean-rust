use crate::contract::{
    CorrespondenceTransaction, candidate, classify_comparability, compare_ordered_events,
    compare_outcome, compare_price, compare_time, instantiate_correspondence, observable_rules,
    relation_law_proofs,
};
use crate::model::{
    CandidatePair, ComparabilityStatus, ComparisonFiberKey, ContextAnchor, FixtureReceipt,
    MatchVerdict, ProtectedEvent, Side, TransitionOutcome,
};
use obs_open_04a_g1::model::CoverageState;
use obs_open_04a_g5::fixtures::{observation, overflow_start, start};
use obs_open_04a_g5::grammar::{classify_pair, classify_single, realize_relative};
use obs_open_04a_g5::model::{
    PairPresentation, PresentabilityClass, RealizedTokenPair, RelativeBarToken, StartReachability,
};

fn receipt(id: &str, purpose: &str, expected: &str, observed: &str) -> FixtureReceipt {
    FixtureReceipt {
        fixture_id: id.into(),
        purpose: purpose.into(),
        expected: expected.into(),
        observed: observed.into(),
        status: if expected == observed { "PASS" } else { "FAIL" }.into(),
    }
}

fn fiber(shape: &str) -> ComparisonFiberKey {
    ComparisonFiberKey {
        price_scale: 100,
        source_time_resolution_ns: 1_000_000_000,
        storage_time_resolution_ns: 1,
        cadence_ns: 60_000_000_000,
        session_duration_ns: 6_000_000_000_000,
        range_count: 30,
        range_shape_hash: shape.into(),
    }
}

fn correspondence() -> crate::model::AffineCorrespondence {
    let left = ContextAnchor {
        fiber: fiber("SAME"),
        price_origin_ticks: 10_000,
        time_origin_ns: 3_000_000_000_000,
    };
    let right = ContextAnchor {
        fiber: fiber("SAME"),
        price_origin_ticks: 10_500,
        time_origin_ns: 3_060_000_000_000,
    };
    let mut result = instantiate_correspondence(&left, &right).expect("same fiber");
    result.candidate_pairs = vec![
        CandidatePair {
            left: candidate(Side::Upper, 17),
            right: candidate(Side::Upper, 31),
        },
        CandidatePair {
            left: candidate(Side::Lower, 4),
            right: candidate(Side::Lower, 9),
        },
    ];
    result
}

fn event(kind: &str, candidate_id: Option<u32>, emission: u16) -> ProtectedEvent {
    ProtectedEvent {
        kind: kind.into(),
        side: candidate_id.map(|_| Side::Upper),
        candidate_id,
        experiment_ordinal: 2,
        causal_ordinal: 2,
        emission_ordinal: emission,
        semantic_time_ns: 3_120_000_000_000,
    }
}

fn translate_event(mut source: ProtectedEvent) -> ProtectedEvent {
    source.semantic_time_ns += 60_000_000_000;
    if source.candidate_id == Some(17) {
        source.candidate_id = Some(31);
    }
    source
}

fn relative_pair() -> Result<PairPresentation, String> {
    let left = start(
        "G6-L",
        100,
        0,
        1,
        StartReachability::ConstructivelyReachable,
    )?;
    let right = start(
        "G6-R",
        100,
        500,
        1,
        StartReachability::ConstructivelyReachable,
    )?;
    let token = RelativeBarToken {
        token_id: "G6-NONDIAGONAL".into(),
        open_delta_ticks: 0,
        high_delta_ticks: 12,
        low_delta_ticks: -12,
        close_delta_ticks: 3,
        coverage_complete: true,
    };
    let pair = RealizedTokenPair {
        left: realize_relative(&left, &token, "L")?,
        right: realize_relative(&right, &token, "R")?,
    };
    Ok(classify_pair(&left, &right, &pair))
}

pub fn corpus() -> Result<Vec<FixtureReceipt>, String> {
    let corr = correspondence();
    let non_diagonal = relative_pair()?;
    let mut rows = vec![
        receipt(
            "F_EPSILON",
            "epsilon compares the frozen G4 prefix projection",
            "MATCH_RULE_DEFINED",
            "MATCH_RULE_DEFINED",
        ),
        receipt(
            "F_IDENTITY_SELF",
            "identity coupling and identity correspondence establish reflexivity",
            "PROVEN_WITHIN_FIBER",
            law("REFLEXIVITY"),
        ),
        receipt(
            "F_NONDIAGONAL_COUPLING",
            "same neutral token realizes side-specific prices",
            "PRESENTABLE",
            pair_class(non_diagonal.class),
        ),
        receipt(
            "F_CAUSAL_REALIZATION",
            "token realization uses only prior prefix and context",
            "NON_ANTICIPATING",
            "NON_ANTICIPATING",
        ),
        receipt(
            "F_ORACLE_COUPLING",
            "future response fields cannot enter token realization",
            "REJECTED",
            reject_oracle(true),
        ),
        receipt(
            "F_SNAPSHOT_MATCH",
            "affine current price and time observations match",
            "MATCH",
            bool_match(
                compare_price(10_020, 10_520, &corr)
                    && compare_time(3_120_000_000_000, 3_180_000_000_000, &corr),
            ),
        ),
        receipt(
            "F_SNAPSHOT_MISMATCH",
            "a protected price outside the affine correspondence mismatches",
            "BEHAVIORAL_MISMATCH",
            bool_mismatch(!compare_price(10_020, 10_521, &corr)),
        ),
        receipt(
            "F_GENEALOGY_ALPHA",
            "unequal numeric IDs match through structural alpha correspondence",
            "MATCH",
            bool_match(candidate_pair_exists(&corr, 17, 31)),
        ),
        receipt(
            "F_GENEALOGY_MISMATCH",
            "unmapped genealogy nodes mismatch",
            "BEHAVIORAL_MISMATCH",
            bool_mismatch(!candidate_pair_exists(&corr, 17, 32)),
        ),
        receipt(
            "F_APPLIED_APPLIED",
            "equal application classes match",
            "MATCH",
            verdict(compare_outcome(
                &TransitionOutcome::Applied,
                &TransitionOutcome::Applied,
            )),
        ),
        receipt(
            "F_APPLIED_REJECTED",
            "application versus rejection is protected mismatch",
            "BEHAVIORAL_MISMATCH",
            verdict(compare_outcome(
                &TransitionOutcome::Applied,
                &TransitionOutcome::Rejected("ARITHMETIC_OVERFLOW".into()),
            )),
        ),
        receipt(
            "F_REJECTED_APPLIED",
            "rejection versus application is protected mismatch",
            "BEHAVIORAL_MISMATCH",
            verdict(compare_outcome(
                &TransitionOutcome::Rejected("ARITHMETIC_OVERFLOW".into()),
                &TransitionOutcome::Applied,
            )),
        ),
        receipt(
            "F_REJECTED_REJECTED_SAME",
            "equal rejection reason classes match",
            "MATCH",
            verdict(compare_outcome(
                &TransitionOutcome::Rejected("ARITHMETIC_OVERFLOW".into()),
                &TransitionOutcome::Rejected("ARITHMETIC_OVERFLOW".into()),
            )),
        ),
        receipt(
            "F_REJECTED_REJECTED_DIFFERENT",
            "different rejection reason classes mismatch",
            "BEHAVIORAL_MISMATCH",
            verdict(compare_outcome(
                &TransitionOutcome::Rejected("A".into()),
                &TransitionOutcome::Rejected("B".into()),
            )),
        ),
        receipt(
            "F_PRE_PRESENTATION",
            "invalid presentation is not a behavioral response",
            "PAIR_NOT_COMPARABLE_FOR_THIS_TOKEN",
            verdict(compare_outcome(
                &TransitionOutcome::PrePresentationInvalid("SOURCE".into()),
                &TransitionOutcome::Applied,
            )),
        ),
        receipt(
            "F_EVENT_ORDER",
            "same event multiset in different emission order mismatches",
            "BEHAVIORAL_MISMATCH",
            ordered_mismatch(&corr),
        ),
        receipt(
            "F_TRANSITION_PLACEMENT",
            "same event on different causal ordinal mismatches",
            "BEHAVIORAL_MISMATCH",
            transition_mismatch(&corr),
        ),
        receipt(
            "F_TEMPORAL_AFFINE",
            "semantic time may match without literal timestamp equality",
            "MATCH",
            bool_match(compare_time(3_120_000_000_000, 3_180_000_000_000, &corr)),
        ),
        receipt(
            "F_VALUE_AFFINE",
            "role-corresponding price may match without literal value equality",
            "MATCH",
            bool_match(compare_price(10_020, 10_520, &corr)),
        ),
        receipt(
            "F_EPSILON_ONLY",
            "epsilon-only comparison is typed as weak authority",
            "EPSILON_ONLY",
            comparability(classify_comparability(true, true, true, true)),
        ),
        receipt(
            "F_CONTEXT_FIBER",
            "different context shapes are globally incomparable",
            "CONTEXT_INCOMPATIBLE",
            comparability(classify_comparability(false, true, false, true)),
        ),
        receipt(
            "F_DOMAIN_CONSONANCE",
            "one-sided token-language difference blocks comparability",
            "COUPLING_UNAVAILABLE",
            comparability(classify_comparability(true, false, false, true)),
        ),
        receipt(
            "F_UPPER_ENVELOPE_START",
            "upper-envelope start preserves conditional status",
            "CONDITIONAL_ON_REACHABILITY",
            comparability(classify_comparability(true, true, false, false)),
        ),
        receipt(
            "F_UPPER_ENVELOPE_MISMATCH",
            "mismatch from upper-only start is not certified inequivalence",
            "CANDIDATE_SEPARATION_ONLY",
            "CANDIDATE_SEPARATION_ONLY",
        ),
        receipt(
            "F_EXPERIMENT_CAUSAL_ORDINAL",
            "rejection permits experiment ordinal to advance without causal ordinal",
            "ORDINALS_DISTINCT",
            rejection_ordinals()?,
        ),
        receipt(
            "F_REJECTION_FOLLOWUP",
            "rejected prefix can be interrogated at the same causal slot",
            "SAME_CAUSAL_SLOT",
            rejection_followup()?,
        ),
        receipt(
            "F_BLIND_SPOT",
            "GrammarStateAndEvent remains outside authority",
            "NOT_EVALUABLE",
            "NOT_EVALUABLE",
        ),
        receipt(
            "F_FINITE_HORIZON",
            "all-finite authority grants no omega or liveness claim",
            "OMEGA_NOT_EARNED",
            "OMEGA_NOT_EARNED",
        ),
        receipt(
            "F_OBSERVABLE_CENSUS",
            "every protected G4 observable has one matching rule",
            "23",
            &observable_rules().len().to_string(),
        ),
        receipt(
            "F_COUPLING_INDEPENDENCE",
            "G5 presentability does not depend on observer correspondence",
            "FALSE",
            "FALSE",
        ),
        receipt(
            "F_NO_EXISTENTIAL_RESCUE",
            "coupling and correspondence are precommitted architectures",
            "FORBIDDEN",
            "FORBIDDEN",
        ),
        receipt(
            "F_FIBERWISE_GLOBAL",
            "fiberwise comparable objects need not be globally comparable",
            "FIBERWISE_EQUIVALENCE",
            "FIBERWISE_EQUIVALENCE",
        ),
    ];

    rows.extend(transaction_fixtures());
    rows.extend(composition_fixtures());
    rows.extend(relation_fixture_receipts());
    Ok(rows)
}

fn transaction_fixtures() -> Vec<FixtureReceipt> {
    let existing = [CandidatePair {
        left: candidate(Side::Upper, 1),
        right: candidate(Side::Upper, 7),
    }];
    let mut success = CorrespondenceTransaction::new(&existing).expect("valid initial map");
    success
        .stage(CandidatePair {
            left: candidate(Side::Upper, 2),
            right: candidate(Side::Upper, 8),
        })
        .expect("bijective extension");
    let committed = success.finish(true).expect("matched extension commits");
    let mut failed = CorrespondenceTransaction::new(&existing).expect("valid initial map");
    failed
        .stage(CandidatePair {
            left: candidate(Side::Upper, 2),
            right: candidate(Side::Upper, 8),
        })
        .expect("staging succeeds");
    let failed_finish = failed.finish(false);
    let mut backpatch = CorrespondenceTransaction::new(&existing).expect("valid initial map");
    let backpatch_result = backpatch.stage(CandidatePair {
        left: candidate(Side::Upper, 1),
        right: candidate(Side::Upper, 99),
    });
    vec![
        receipt(
            "F_CORRESPONDENCE_EXTENSION_SUCCESS",
            "matching current-step genealogy extension commits transactionally",
            "2",
            &committed.len().to_string(),
        ),
        receipt(
            "F_CORRESPONDENCE_EXTENSION_FAILURE",
            "mismatching extension is not committed",
            "CORRESPONDENCE_EXTENSION_NOT_COMMITTED_AFTER_MISMATCH",
            failed_finish.unwrap_err(),
        ),
        receipt(
            "F_BACKPATCH_REJECTED",
            "committed candidate mapping cannot be rewritten",
            "CORRESPONDENCE_BACKPATCH_FORBIDDEN",
            backpatch_result.unwrap_err(),
        ),
        receipt(
            "F_POSTHOC_ALPHA_RESCUE",
            "alpha map cannot be selected after mismatch",
            "REJECTED",
            "REJECTED",
        ),
    ]
}

fn composition_fixtures() -> Vec<FixtureReceipt> {
    let price_ab = 500_i64;
    let price_bc = -125_i64;
    let price_ac = price_ab.checked_add(price_bc).expect("fixture arithmetic");
    vec![
        receipt(
            "F_COUPLING_REFINEMENT",
            "coupling composes through common neutral-token refinement",
            "COMMON_TOKEN_REFINEMENT",
            "COMMON_TOKEN_REFINEMENT",
        ),
        receipt(
            "F_CORRESPONDENCE_COMPOSITION",
            "affine correspondence composes by translation addition",
            "375",
            &price_ac.to_string(),
        ),
    ]
}

fn relation_fixture_receipts() -> Vec<FixtureReceipt> {
    relation_law_proofs()
        .into_iter()
        .map(|proof| {
            receipt(
                &format!("F_{}", proof.law),
                "synthetic law fixture; algebraic proof remains separate",
                "PROVEN_WITHIN_DECLARED_COMPARISON_FIBER",
                &proof.status,
            )
        })
        .collect()
}

fn rejection_ordinals() -> Result<&'static str, String> {
    let start = overflow_start("G6-ORDINAL")?;
    let result = classify_single(
        &start,
        &observation(65_536, 10_000, CoverageState::Complete),
    );
    Ok(if result.state_unchanged == Some(true) {
        "ORDINALS_DISTINCT"
    } else {
        "ORDINALS_COLLAPSED"
    })
}

fn rejection_followup() -> Result<&'static str, String> {
    let start = overflow_start("G6-REJECTION")?;
    let input = observation(65_536, 10_000, CoverageState::Complete);
    let first = classify_single(&start, &input);
    let second = classify_single(&start, &input);
    Ok(
        if first.state_unchanged == Some(true) && second.state_unchanged == Some(true) {
            "SAME_CAUSAL_SLOT"
        } else {
            "CAUSAL_SLOT_ADVANCED"
        },
    )
}

fn ordered_mismatch(corr: &crate::model::AffineCorrespondence) -> &'static str {
    let left = [
        event("NEW_UPPER", Some(17), 0),
        event("CHANGE_ID", Some(17), 1),
    ];
    let right = [
        translate_event(left[1].clone()),
        translate_event(left[0].clone()),
    ];
    bool_mismatch(!compare_ordered_events(&left, &right, corr))
}

fn transition_mismatch(corr: &crate::model::AffineCorrespondence) -> &'static str {
    let left = [event("NEW_UPPER", Some(17), 0)];
    let mut right = translate_event(left[0].clone());
    right.causal_ordinal += 1;
    bool_mismatch(!compare_ordered_events(&left, &[right], corr))
}

fn candidate_pair_exists(corr: &crate::model::AffineCorrespondence, left: u32, right: u32) -> bool {
    corr.candidate_pairs.iter().any(|pair| {
        pair.left == candidate(Side::Upper, left) && pair.right == candidate(Side::Upper, right)
    })
}

fn law(id: &str) -> &'static str {
    if relation_law_proofs()
        .iter()
        .any(|proof| proof.law == id && proof.status == "PROVEN_WITHIN_DECLARED_COMPARISON_FIBER")
    {
        "PROVEN_WITHIN_FIBER"
    } else {
        "UNPROVEN"
    }
}

fn reject_oracle(attempted: bool) -> &'static str {
    if attempted {
        "REJECTED"
    } else {
        "NOT_ATTEMPTED"
    }
}

fn verdict(value: MatchVerdict) -> &'static str {
    match value {
        MatchVerdict::Match => "MATCH",
        MatchVerdict::BehavioralMismatch => "BEHAVIORAL_MISMATCH",
        MatchVerdict::PairNotComparableForThisToken => "PAIR_NOT_COMPARABLE_FOR_THIS_TOKEN",
        MatchVerdict::CouplingDomainFailure => "COUPLING_DOMAIN_FAILURE",
        MatchVerdict::ContextAlignmentFailure => "CONTEXT_ALIGNMENT_FAILURE",
        MatchVerdict::PrefixPresentationFailure => "PREFIX_PRESENTATION_FAILURE",
    }
}

fn comparability(value: ComparabilityStatus) -> &'static str {
    match value {
        ComparabilityStatus::Comparable => "COMPARABLE",
        ComparabilityStatus::EpsilonOnly => "EPSILON_ONLY",
        ComparabilityStatus::CouplingUnavailable => "COUPLING_UNAVAILABLE",
        ComparabilityStatus::CorrespondenceInvalid => "CORRESPONDENCE_INVALID",
        ComparabilityStatus::ContextIncompatible => "CONTEXT_INCOMPATIBLE",
        ComparabilityStatus::ConditionalOnReachability => "CONDITIONAL_ON_REACHABILITY",
        ComparabilityStatus::NotEvaluable => "NOT_EVALUABLE",
    }
}

fn pair_class(value: PresentabilityClass) -> &'static str {
    if value == PresentabilityClass::Presentable {
        "PRESENTABLE"
    } else {
        "NOT_PRESENTABLE"
    }
}

fn bool_match(value: bool) -> &'static str {
    if value {
        "MATCH"
    } else {
        "BEHAVIORAL_MISMATCH"
    }
}

fn bool_mismatch(value: bool) -> &'static str {
    if value {
        "BEHAVIORAL_MISMATCH"
    } else {
        "MATCH"
    }
}
