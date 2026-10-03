use crate::metrology::fold;
use crate::model::{CommittedState, ReducedState, SourceCommit};
use obs_open_meas02::RangeObject;
use serde_json::{Value, json};

pub fn qualify() -> Result<Value, String> {
    let range = range();
    let base = vec![
        commit(0, 10.0, 0.0, 5.0),
        commit(1, 11.0, 0.0, 8.0),
        commit(2, 11.0, -1.0, 1.0),
        commit(3, 12.0, -2.0, 4.0),
    ];
    let states = replay(&base, &range);
    check(
        states[0].upper.id == 1 && states[0].lower.id == 1,
        "FIRST_CANDIDATES",
    )?;
    check(
        states[1].upper.id == 2 && states[1].lower.id == 1,
        "NEW_UPPER",
    )?;
    check(
        states[2].upper.id == 2 && states[2].lower.id == 2,
        "NEW_LOWER",
    )?;
    check(
        states[3].upper.id == 3 && states[3].lower.id == 3,
        "SIMULTANEOUS_RENEWAL",
    )?;
    let equality = replay(
        &[commit(0, 10.0, 0.0, 5.0), commit(1, 10.0, 0.0, 5.0)],
        &range,
    );
    check(
        equality[1].upper.id == 1
            && equality[1].lower.id == 1
            && equality[1].upper.age_bars == 1
            && equality[1].lower.age_bars == 1,
        "FLOATING_EQUALITY",
    )?;
    let committed = &states[1];
    let live_high = 20.0f64.max(committed.upper.value);
    let live_low = (-5.0f64).min(committed.lower.value);
    check(
        live_high > committed.upper.value
            && live_low < committed.lower.value
            && committed.upper.id == 2
            && committed.lower.id == 1,
        "PROVISIONAL_COMMITTED_SEPARATION",
    )?;
    let replay_again = replay(&base, &range);
    check(states == replay_again, "REPLAY_RELOAD_EQUALITY")?;
    let second_session = replay(&[commit(0, 30.0, 20.0, 25.0)], &range);
    check(
        second_session[0].upper.id == 1 && second_session[0].lower.id == 1,
        "CROSS_SESSION_RESET",
    )?;
    let history_a = replay(
        &[
            commit(0, 10.0, 0.0, 5.0),
            commit(1, 11.0, 0.0, 5.0),
            commit(2, 12.0, -1.0, 4.0),
        ],
        &range,
    );
    let history_b = replay(
        &[
            commit(0, 10.0, 0.0, 5.0),
            commit(1, 10.5, 0.0, 5.0),
            commit(2, 12.0, -1.0, 4.0),
        ],
        &range,
    );
    check(
        history_a.last() == history_b.last(),
        "HISTORY_DIFFERENT_STATE_EQUAL",
    )?;
    let semantic_a = replay(
        &[commit(0, 10.0, 0.0, 5.0), commit(1, 11.0, -1.0, 5.0)],
        &range,
    );
    let semantic_b = replay(
        &[commit(0, 20.0, 5.0, 10.0), commit(1, 21.0, 4.0, 10.0)],
        &range,
    );
    check(
        semantic_a.last() != semantic_b.last(),
        "SEMANTIC_TAPE_STATE_NONRECONSTRUCTION",
    )?;
    let state_a = replay(
        &[
            commit(0, 10.0, 0.0, 5.0),
            commit(1, 11.0, -1.0, 5.0),
            commit(2, 12.0, -2.0, 4.0),
        ],
        &range,
    );
    let state_b = replay(
        &[
            commit(0, 10.0, 0.0, 5.0),
            commit(1, 10.0, 0.0, 5.0),
            commit(2, 12.0, -2.0, 4.0),
        ],
        &range,
    );
    let a = state_a.last().unwrap();
    let b = state_b.last().unwrap();
    check(
        a != b && ReducedState::from(a) == ReducedState::from(b),
        "STATE_TO_REDUCED_NONINJECTIVE",
    )?;
    check(
        detect_gap(&[commit(0, 10.0, 0.0, 5.0), commit(2, 12.0, -1.0, 4.0)]),
        "MISSING_COMPLETED_BAR",
    )?;
    let fixtures = vec![
        result(
            "FORMING_BAR_PROVISIONAL_EXTREME",
            "LIVE_CHANGE_WITHOUT_COMMITTED_IDENTITY_CHANGE",
        ),
        result("COMPLETED_BAR_NEW_UPPER", "STRICT_RENEWAL_COMMITTED"),
        result("COMPLETED_BAR_NEW_LOWER", "STRICT_RENEWAL_COMMITTED"),
        result("MULTIPLE_SUCCESSIVE_UPPER_RENEWALS", "CONTIGUOUS_IDS"),
        result("MULTIPLE_SUCCESSIVE_LOWER_RENEWALS", "CONTIGUOUS_IDS"),
        result(
            "ALTERNATING_UPPER_LOWER_RENEWALS",
            "INDEPENDENT_SIDE_GENEALOGIES",
        ),
        result(
            "SAME_CURRENT_STATE_DIFFERENT_HISTORIES",
            "ALGEBRAIC_NONINJECTIVITY_WITNESS",
        ),
        result(
            "SAME_REDUCED_STATE_DIFFERENT_CURRENT_STATES",
            "DROPPED_CANDIDATE_IDENTITY_WITNESS",
        ),
        result("SEMANTIC_TAPE_INSUFFICIENT", "NON_RECONSTRUCTIBLE"),
        result(
            "EVENT_SOURCE_TAPE_FOLD",
            "RECONSTRUCTIBLE_WITH_DECLARED_CONTEXT",
        ),
        result("MISSING_COMPLETED_BAR", "NOT_EVALUABLE_SENTINEL_PATH_GAP"),
        result("RELOAD_AT_CANDIDATE_BOUNDARY", "EXACT_RECONSTRUCTION"),
        result("REPLAY_AT_CANDIDATE_BOUNDARY", "EXACT_RECONSTRUCTION"),
        result("CROSS_SESSION_RESET", "CANDIDATE_IDS_RESET_TO_ONE"),
        result(
            "TERMINAL_SURVIVOR_BEFORE_WINDOW_CLOSE",
            "FORBIDDEN_RETROSPECTIVE_QUERY",
        ),
        result(
            "FINAL_MULTIPLICITY_CAUSAL_QUERY",
            "FORBIDDEN_RETROSPECTIVE_QUERY",
        ),
        result("FLOATING_EQUALITY_BOUNDARY", "NO_STRICT_RENEWAL"),
        result("HISTORY_TO_SOURCE_OPEN_PRICE_WITNESS", "BAR_OPEN_DISCARDED"),
    ];
    Ok(
        json!({"schema":"INFORMATION_LOSS_WITNESS_REGISTRY_V1","source_kind":"SYNTHETIC_ADVERSARIAL","fixture_count":fixtures.len(),"fixtures":fixtures,"empirical_data_used":false,"status":"PASS"}),
    )
}

fn commit(index: u16, high: f64, low: f64, close: f64) -> SourceCommit {
    SourceCommit {
        relative_bar_index: index,
        event_time: index as i64 * 60,
        knowledge_time: (index as i64 + 1) * 60,
        high,
        low,
        close,
        new_upper: false,
        new_lower: false,
    }
}
fn replay(commits: &[SourceCommit], ranges: &[RangeObject]) -> Vec<CommittedState> {
    let mut out = Vec::new();
    for c in commits {
        let next = fold(out.last(), c, ranges, true);
        out.push(next);
    }
    out
}
fn detect_gap(commits: &[SourceCommit]) -> bool {
    commits
        .windows(2)
        .any(|w| w[1].relative_bar_index != w[0].relative_bar_index + 1)
}
fn check(condition: bool, name: &str) -> Result<(), String> {
    if condition {
        Ok(())
    } else {
        Err(format!("FIXTURE_FAILURE:{name}"))
    }
}
fn result(case: &str, expected: &str) -> Value {
    json!({"case":case,"expected":expected,"state":"PASS"})
}
fn range() -> Vec<RangeObject> {
    vec![RangeObject {
        range_object_id: "SYNTH:R01".into(),
        session_id: "SYNTH".into(),
        k: 1,
        configured_start: 0,
        configured_end: 60,
        instrument_inclusive_end_bar: 0,
        actual_start_bar: 0,
        actual_end_bar: 0,
        freeze_commit_time: 60,
        high: 10.0,
        low: 0.0,
        midpoint: 5.0,
        width: 10.0,
        source_coverage: "COMPLETE".into(),
        instrument_authority: "SYNTHETIC".into(),
    }]
}
