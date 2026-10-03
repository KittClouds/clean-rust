use obs_open_03a::{
    AnchorKind, CensorReason, OutcomeCode, OutcomeState, PackedOutcome, Representation, Side,
    TerminalClass,
};

#[test]
fn packed_record_has_stable_compact_size() {
    assert_eq!(std::mem::size_of::<PackedOutcome>(), 80);
}

#[test]
fn packed_record_preserves_typed_absence() {
    let r = PackedOutcome::new(
        None,
        Some(5.0),
        10,
        None,
        20,
        15,
        1,
        2,
        OutcomeCode::CandidateFirstPassageParallel,
        10,
        5,
        0,
        1,
        AnchorKind::Candidate,
        Side::Upper,
        Representation::RawPrice,
        OutcomeState::RightCensored,
        CensorReason::CandidateSupersession,
        TerminalClass::Superseded,
    );
    assert_eq!(r.value(), None);
    assert_eq!(r.censor_minutes(), Some(5.0));
    assert_eq!(r.outcome_known_present, 0);
}

#[test]
fn zero_minute_censor_is_not_collapsed_into_absence() {
    let r = PackedOutcome::new(
        None,
        Some(0.0),
        10,
        Some(10),
        10,
        10,
        1,
        2,
        OutcomeCode::CandidateTimeToSupersession,
        0,
        0,
        0,
        0,
        AnchorKind::Candidate,
        Side::Lower,
        Representation::Dimensionless,
        OutcomeState::RightCensored,
        CensorReason::CandidateSupersession,
        TerminalClass::Superseded,
    );
    assert_eq!(r.censor_minutes(), Some(0.0));
    assert_eq!(r.censor_present, 1);
}

#[test]
fn candidate_and_range_codes_are_disjoint() {
    assert!((OutcomeCode::CandidateTerminalStatus as u16) < 100);
    assert!((OutcomeCode::RangeTerminalClose as u16) > 100);
}
