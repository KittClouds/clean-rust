use obs_open_03ap::{
    ATLAS_SESSIONS, AnchorKind, CensorReason, DerivedPartition, Orientation, OutcomeState,
    REPRESENTATION_GATE_SESSIONS, SessionMeta, first_passage, fixed_horizon_terminal,
    parse_discovery_prefix, partition_sessions, run_synthetic_qualification,
};

fn session(index: usize) -> SessionMeta {
    SessionMeta {
        session_id: format!("S{index:03}"),
        civil_date: format!("2025-{:02}-{:02}", index % 12 + 1, index % 27 + 1),
        month: format!("2025-{:02}", index % 12 + 1),
        server_offset_minutes: if index.is_multiple_of(2) { 120 } else { 180 },
    }
}

#[test]
fn parser_decodes_discovery_and_ignores_confirmation_membership() {
    let bytes = b"session_id\tcivil_date\tpartition\tserver_offset_minutes\tconfirmation_status\nD1\t2025-01-01\tDISCOVERY\t120\tNOT_APPLICABLE\nSECRET\t2025-07-01\tCONFIRMATION\t180\tFROZEN_UNOPENED\n";
    let rows = parse_discovery_prefix(bytes).expect("parse");
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].session_id, "D1");
    assert!(rows.iter().all(|row| row.session_id != "SECRET"));
}

#[test]
fn salted_partition_is_order_invariant_and_exact() {
    let forward: Vec<_> = (0..ATLAS_SESSIONS + REPRESENTATION_GATE_SESSIONS)
        .map(session)
        .collect();
    let mut reverse = forward.clone();
    reverse.reverse();
    let mut a = partition_sessions(forward).expect("partition");
    let mut b = partition_sessions(reverse).expect("partition");
    a.sort_unstable_by(|x, y| x.session.session_id.cmp(&y.session.session_id));
    b.sort_unstable_by(|x, y| x.session.session_id.cmp(&y.session.session_id));
    assert_eq!(a, b);
    assert_eq!(
        a.iter()
            .filter(|row| row.partition == DerivedPartition::AtlasDa)
            .count(),
        ATLAS_SESSIONS
    );
}

#[test]
fn synthetic_qualification_is_complete_and_market_free() {
    let receipt = run_synthetic_qualification().expect("qualification");
    assert_eq!(receipt.status, "PASS");
    assert_eq!(receipt.market_observations_read, 0);
    assert_eq!(receipt.failed, 0);
    assert!(receipt.passed >= 15);
}

#[test]
fn fixed_horizon_does_not_backdate_future_value() {
    let bars = vec![obs_open_03ap::SyntheticBar {
        close_epoch: 1_060,
        high: 103.0,
        low: 99.0,
        close: 102.0,
        coverage: true,
    }];
    let outcome = fixed_horizon_terminal(
        "Y",
        "A",
        AnchorKind::ExtremeCandidateBirth,
        1_000,
        100.0,
        Orientation::Upper,
        1,
        1_060,
        &bars,
    );
    assert_eq!(outcome.outcome_state, OutcomeState::ObservedComplete);
    assert_eq!(outcome.anchor_known_at, 1_000);
    assert_eq!(outcome.outcome_known_at, Some(1_060));
}

#[test]
fn source_gap_is_not_a_negative_first_passage() {
    let bars = vec![
        obs_open_03ap::SyntheticBar {
            close_epoch: 1_060,
            high: 101.0,
            low: 99.0,
            close: 100.0,
            coverage: false,
        },
        obs_open_03ap::SyntheticBar {
            close_epoch: 1_120,
            high: 120.0,
            low: 99.0,
            close: 120.0,
            coverage: true,
        },
    ];
    let outcome = first_passage(
        "FP",
        "A",
        1_000,
        100.0,
        Orientation::Upper,
        10.0,
        true,
        1_120,
        CensorReason::SessionTermination,
        &bars,
    );
    assert_eq!(outcome.outcome_state, OutcomeState::SourcePathIncomplete);
    assert_eq!(outcome.value, None);
}
