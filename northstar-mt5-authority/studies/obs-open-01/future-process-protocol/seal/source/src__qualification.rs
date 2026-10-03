use crate::model::{AnchorKind, CensorReason, Orientation, OutcomeState, SyntheticBar};
use crate::outcomes::{
    first_passage, fixed_horizon_terminal, oriented_delta, range_z, realized_variation_simd,
    validate_receipt,
};
use serde::Serialize;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct Check {
    pub check_id: String,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct Qualification {
    pub schema: String,
    pub fixture_kind: String,
    pub market_observations_read: u64,
    pub checks: Vec<Check>,
    pub passed: usize,
    pub failed: usize,
    pub status: String,
}

pub fn run_synthetic_qualification() -> Result<Qualification, String> {
    let mut checks = Vec::new();
    let complete_bars = bars(true);
    record(
        &mut checks,
        "UPPER_ORIENTATION",
        oriented_delta(102.0, 100.0, Orientation::Upper) == Some(2.0),
    );
    record(
        &mut checks,
        "LOWER_ORIENTATION",
        oriented_delta(98.0, 100.0, Orientation::Lower) == Some(2.0),
    );
    record(
        &mut checks,
        "RANGE_HAS_NO_ORIENTATION",
        oriented_delta(102.0, 100.0, Orientation::None).is_none(),
    );
    record(
        &mut checks,
        "RANGE_Z_BOUNDARIES",
        range_z(110.0, 100.0, 20.0) == Some(1.0) && range_z(90.0, 100.0, 20.0) == Some(-1.0),
    );
    record(
        &mut checks,
        "DEGENERATE_RANGE_NOT_EVALUABLE",
        range_z(100.0, 100.0, 0.0).is_none(),
    );

    let terminal = fixed_horizon_terminal(
        "TERMINAL",
        "C1",
        AnchorKind::ExtremeCandidateBirth,
        1_000,
        100.0,
        Orientation::Upper,
        2,
        1_600,
        &complete_bars,
    );
    record(
        &mut checks,
        "FIXED_HORIZON_KNOWLEDGE_TIME",
        terminal.outcome_state == OutcomeState::ObservedComplete
            && terminal.outcome_known_at == Some(1_120)
            && terminal.value == Some(4.0)
            && validate_receipt(&terminal).is_ok(),
    );

    let terminated = fixed_horizon_terminal(
        "TERMINATED",
        "C1",
        AnchorKind::ExtremeCandidateBirth,
        1_000,
        100.0,
        Orientation::Upper,
        10,
        1_180,
        &complete_bars,
    );
    record(
        &mut checks,
        "SESSION_TERMINATION_TYPED",
        terminated.outcome_state == OutcomeState::SessionTerminated
            && terminated.censor_reason == CensorReason::SessionTermination
            && terminated.value.is_none()
            && validate_receipt(&terminated).is_ok(),
    );

    let passage = first_passage(
        "FIRST_PASSAGE_PARALLEL",
        "C1",
        1_000,
        100.0,
        Orientation::Upper,
        3.0,
        true,
        1_180,
        CensorReason::SessionTermination,
        &complete_bars,
    );
    record(
        &mut checks,
        "FIRST_PASSAGE_KNOWN_AT_CROSSING",
        passage.outcome_state == OutcomeState::ObservedComplete
            && passage.outcome_known_at == Some(1_120)
            && passage.value == Some(2.0)
            && validate_receipt(&passage).is_ok(),
    );

    let censored = first_passage(
        "FIRST_PASSAGE_ANTIPARALLEL",
        "C1",
        1_000,
        100.0,
        Orientation::Upper,
        20.0,
        false,
        1_180,
        CensorReason::CandidateSupersession,
        &complete_bars,
    );
    record(
        &mut checks,
        "FIRST_PASSAGE_RIGHT_CENSORED",
        censored.outcome_state == OutcomeState::RightCensored
            && censored.censor_reason == CensorReason::CandidateSupersession
            && censored.value.is_none()
            && validate_receipt(&censored).is_ok(),
    );

    let gap_bars = bars(false);
    let gap = fixed_horizon_terminal(
        "GAP",
        "C1",
        AnchorKind::ExtremeCandidateBirth,
        1_000,
        100.0,
        Orientation::Upper,
        3,
        1_600,
        &gap_bars,
    );
    record(
        &mut checks,
        "SOURCE_GAP_FAILS_CLOSED",
        gap.outcome_state == OutcomeState::SourcePathIncomplete
            && gap.censor_reason == CensorReason::SourcePathGap
            && gap.value.is_none(),
    );

    let first_bar_hit_after_gap = first_passage(
        "GAP_PRECEDENCE",
        "C1",
        1_000,
        100.0,
        Orientation::Upper,
        5.0,
        true,
        1_180,
        CensorReason::SessionTermination,
        &gap_bars,
    );
    record(
        &mut checks,
        "SOURCE_GAP_PRECEDES_LATER_EVENT",
        first_bar_hit_after_gap.outcome_state == OutcomeState::SourcePathIncomplete,
    );

    record(
        &mut checks,
        "SIMD_VARIATION_PARITY",
        (realized_variation_simd(&[100.0, 102.0, 99.0, 105.0, 104.0]) - 12.0).abs() < f64::EPSILON,
    );

    let mut invalid = terminal.clone();
    invalid.outcome_known_at = Some(999);
    record(
        &mut checks,
        "FUTURE_CANNOT_BACKFLOW",
        validate_receipt(&invalid) == Err("OUTCOME_KNOWN_BEFORE_ANCHOR"),
    );

    let mut illegal = censored.clone();
    illegal.value = Some(0.0);
    record(
        &mut checks,
        "TYPED_ABSENCE_CANNOT_COERCE_TO_ZERO",
        validate_receipt(&illegal) == Err("NONCOMPLETE_OUTCOME_HAS_COMPLETED_VALUE"),
    );

    let equal_wall_clock = fixed_horizon_terminal(
        "EQUAL_CLOCK_PHASE_ORDER",
        "C2",
        AnchorKind::ExtremeCandidateBirth,
        1_000,
        100.0,
        Orientation::Upper,
        1,
        1_060,
        &complete_bars,
    );
    record(
        &mut checks,
        "CAUSAL_PHASE_NOT_TIMESTAMP_ALIAS",
        equal_wall_clock.outcome_known_at == Some(1_060)
            && equal_wall_clock.anchor_known_at == 1_000,
    );

    let failed = checks.iter().filter(|check| check.status != "PASS").count();
    let passed = checks.len() - failed;
    if failed != 0 {
        return Err(format!("SYNTHETIC_QUALIFICATION_FAILED:{failed}"));
    }
    Ok(Qualification {
        schema: "OBS_OPEN_03AP_SYNTHETIC_QUALIFICATION_V1".into(),
        fixture_kind: "SYNTHETIC_ADVERSARIAL_NO_MARKET_DATA".into(),
        market_observations_read: 0,
        checks,
        passed,
        failed,
        status: "PASS".into(),
    })
}

fn bars(complete: bool) -> Vec<SyntheticBar> {
    vec![
        SyntheticBar {
            close_epoch: 1_060,
            high: 103.0,
            low: 99.0,
            close: 102.0,
            coverage: true,
        },
        SyntheticBar {
            close_epoch: 1_120,
            high: 105.0,
            low: 101.0,
            close: 104.0,
            coverage: complete,
        },
        SyntheticBar {
            close_epoch: 1_180,
            high: 108.0,
            low: 103.0,
            close: 107.0,
            coverage: true,
        },
    ]
}

fn record(checks: &mut Vec<Check>, check_id: &str, pass: bool) {
    checks.push(Check {
        check_id: check_id.to_owned(),
        status: if pass { "PASS" } else { "FAIL" }.to_owned(),
    });
}
