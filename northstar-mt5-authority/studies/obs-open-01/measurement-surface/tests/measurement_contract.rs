use obs_open_meas02::*;

fn spec() -> SessionSpec {
    session_spec("SYNTH", "2024-01-02", 120, "DISCOVERY").unwrap()
}

fn bars(highs: &[f64], lows: &[f64]) -> Vec<Bar> {
    let s = spec();
    highs
        .iter()
        .zip(lows)
        .enumerate()
        .map(|(i, (&high, &low))| Bar {
            source_row_id: format!("SYNTH:{i}"),
            open_time: s.start_epoch + i as i64 * 60,
            close_time: s.start_epoch + (i as i64 + 1) * 60,
            open: (high + low) / 2.0,
            high,
            low,
            close: (high + low) / 2.0,
            coverage: "COMPLETE".into(),
        })
        .collect()
}

#[test]
fn clock_composition_has_expected_winter_and_summer_source_wall() {
    let winter = session_spec("W", "2024-01-02", 120, "DISCOVERY").unwrap();
    let summer = session_spec("S", "2024-04-01", 180, "DISCOVERY").unwrap();
    assert_eq!(winter.start_epoch, 1_704_213_000); // 16:30 source wall
    assert_eq!(summer.start_epoch, 1_711_989_000); // 16:30 source wall
    assert_eq!(ny_utc_offset_minutes("2024-03-08").unwrap(), -300);
    assert_eq!(ny_utc_offset_minutes("2024-03-11").unwrap(), -240);
}

#[test]
fn confirmation_partition_fails_closed() {
    let err = session_spec("LOCKED", "2025-07-01", 180, "CONFIRMATION").unwrap_err();
    assert!(err.to_string().contains("confirmation firewall"));
}

#[test]
fn half_open_range_maps_to_inclusive_instrument_bar() {
    let s = spec();
    let mut b = bars(&[10.0; 30], &[5.0; 30]);
    b[4].high = 15.0;
    let ranges = build_ranges(&s, &b).unwrap();
    let r5 = &ranges[4];
    assert_eq!(r5.configured_end, s.start_epoch + 300);
    assert_eq!(r5.instrument_inclusive_end_bar, s.start_epoch + 240);
    assert_eq!(r5.freeze_commit_time, s.start_epoch + 300);
    assert_eq!(r5.high, 15.0);
}

#[test]
fn strict_candidate_chain_preserves_equal_extrema_and_availability() {
    let s = spec();
    let b = bars(
        &[10.0, 10.0, 11.0, 12.0, 12.0, 11.5],
        &[5.0, 5.0, 5.0, 4.0, 4.0, 4.5],
    );
    let (c, tape) = build_candidates_and_tape(&s, &b).unwrap();
    let uppers: Vec<_> = c.iter().filter(|x| x.side == "UPPER").collect();
    let lowers: Vec<_> = c.iter().filter(|x| x.side == "LOWER").collect();
    assert_eq!(uppers.len(), 3);
    assert_eq!(lowers.len(), 2);
    assert_eq!(uppers[0].superseded_at, Some(b[2].close_time));
    assert_eq!(uppers[1].superseded_at, Some(b[3].close_time));
    assert!(uppers[2].terminal_survivor);
    assert!(lowers[1].terminal_survivor);
    assert_eq!(tape[1].upper_candidate_age_bars, 1); // equality ages, no new ID
    assert!(!tape[1].new_upper_candidate);
    assert!(!tape[4].new_upper_candidate);
}

#[test]
fn simultaneous_upper_and_lower_candidates_are_distinct() {
    let s = spec();
    let b = bars(&[10.0, 12.0], &[5.0, 3.0]);
    let (c, tape) = build_candidates_and_tape(&s, &b).unwrap();
    assert_eq!(c.len(), 4);
    assert!(tape[1].new_upper_candidate);
    assert!(tape[1].new_lower_candidate);
}

#[test]
fn terminal_label_is_not_available_before_boundary() {
    let s = spec();
    let b = bars(&[10.0, 11.0], &[5.0, 4.0]);
    let (c, _) = build_candidates_and_tape(&s, &b).unwrap();
    for candidate in &c {
        if candidate.terminal_survivor {
            assert_eq!(candidate.terminal_label_known_at, Some(s.terminal_epoch));
            assert_eq!(
                candidate.terminal_label_knowledge_order.as_deref(),
                Some("AFTER_FINAL_BAR_COMMIT_AT_SESSION_BOUNDARY")
            );
            assert!(candidate.birth_knowledge_time <= s.terminal_epoch);
        } else {
            assert_eq!(candidate.terminal_label_known_at, None);
        }
    }
}

#[test]
fn range_path_starts_only_when_geometry_is_known() {
    let s = spec();
    let b = bars(&[10.0; 30], &[5.0; 30]);
    let ranges = build_ranges(&s, &b).unwrap();
    let path = range_path_view(&ranges[4], &b);
    assert_eq!(
        path.first().unwrap().bar_close,
        ranges[4].freeze_commit_time
    );
    assert!(
        path.iter()
            .all(|p| p.z_close.is_some() && p.status == "AVAILABLE")
    );
}

#[test]
fn range_relations_wait_for_both_authorities_and_preserve_degenerate_null() {
    let s = spec();
    let b = bars(&[10.0; 30], &[5.0; 30]);
    let ranges = build_ranges(&s, &b).unwrap();
    let (c, _) = build_candidates_and_tape(&s, &b).unwrap();
    let rel = build_range_relations(&c, &ranges);
    assert!(
        rel.iter()
            .all(|r| r.relation_available_at >= s.start_epoch + 60)
    );
    assert!(rel.iter().all(|r| r.status == "AVAILABLE"));

    let flat = bars(&[7.0; 30], &[7.0; 30]);
    let ranges = build_ranges(&s, &flat).unwrap();
    let (c, _) = build_candidates_and_tape(&s, &flat).unwrap();
    let rel = build_range_relations(&c, &ranges);
    assert!(rel.iter().all(|r| r.normalized_mid_coordinate.is_none()));
    assert!(
        rel.iter()
            .all(|r| r.status == "NOT_EVALUABLE_DEGENERATE_RANGE")
    );
}

#[test]
fn candidate_path_is_lazy_and_signed() {
    let s = spec();
    let b = bars(&[10.0, 11.0, 10.5], &[5.0, 5.5, 5.2]);
    let (c, _) = build_candidates_and_tape(&s, &b).unwrap();
    let upper2 = c
        .iter()
        .find(|x| x.side == "UPPER" && x.sequence_number == 2)
        .unwrap();
    let path = candidate_path_view(upper2, &b);
    assert_eq!(path.len(), 2);
    assert_eq!(path[0].signed_high_minus_candidate, 0.0);
    assert!(path[1].signed_close_minus_candidate < 0.0);
}

#[test]
fn grammar_join_is_asof_for_state_and_explicitly_future_for_next_event() {
    let s = spec();
    let b = bars(&[10.0; 30], &[5.0; 30]);
    let ranges = build_ranges(&s, &b).unwrap();
    let (c, _) = build_candidates_and_tape(&s, &b).unwrap();
    let p = vec![
        GrammarPoint {
            bar_close: s.start_epoch + 60,
            state: 1,
            event: Some(10),
        },
        GrammarPoint {
            bar_close: s.start_epoch + 120,
            state: 2,
            event: None,
        },
        GrammarPoint {
            bar_close: s.start_epoch + 180,
            state: 3,
            event: Some(20),
        },
    ];
    let rel = join_grammar(&c[0], &ranges[4], &p);
    assert_eq!(rel.grammar_state_at_birth, Some(1));
    assert_eq!(rel.most_recent_grammar_event, Some(10));
    assert_eq!(rel.next_observed_grammar_event, Some(20));
    assert_eq!(
        rel.next_observed_grammar_event_time,
        Some(s.start_epoch + 180)
    );
    assert_eq!(rel.join_status, "AVAILABLE");
}

#[test]
fn continuity_gap_is_typed_and_never_interpolated() {
    let s = spec();
    let path = std::env::temp_dir().join("obs-open-meas02-gap.tsv");
    let text = format!(
        "schema\tsource_day\ttimeframe\tserver_epoch\tserver_time\topen\thigh\tlow\tclose\ttick_volume\tspread\treal_volume\n\
         X\t2024.01.02\tM1\t{}\tX\t1\t2\t0\t1\t1\t0\t0\n\
         X\t2024.01.02\tM1\t{}\tX\t1\t3\t0\t1\t1\t0\t0\n",
        s.start_epoch,
        s.start_epoch + 120
    );
    std::fs::write(&path, text).unwrap();
    let err = load_m1_window(&path, s.start_epoch, s.start_epoch + 180).unwrap_err();
    assert!(err.to_string().contains("NOT_EVALUABLE_SENTINEL_PATH_GAP"));
    let _ = std::fs::remove_file(path);
}
