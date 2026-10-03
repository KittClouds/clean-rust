use obs_open_disc02p::*;
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).to_path_buf()
}

fn contract(name: &str) -> Value {
    serde_json::from_slice(&fs::read(root().join("contracts").join(name)).unwrap()).unwrap()
}

#[test]
fn exact_parent_and_population_authorities_are_frozen() {
    let authority = contract("authority_v1.json");
    assert_eq!(authority["parent_authorities"]["meas02_root"], MEAS02_ROOT);
    assert_eq!(
        authority["parent_authorities"]["instrument_root"],
        INST01_ROOT
    );
    assert_eq!(
        authority["parent_authorities"]["universe_root"],
        UNIVERSE_ROOT
    );
    assert_eq!(
        authority["populations"]["discovery_sessions"],
        DISCOVERY_SESSIONS
    );
    assert_eq!(
        authority["populations"]["confirmation_sessions"],
        CONFIRMATION_SESSIONS
    );
    assert_eq!(
        authority["populations"]["discovery_state"],
        "MEAS02_DISCOVERY_UNOPENED"
    );
    assert_eq!(
        authority["populations"]["confirmation_state"],
        "FROZEN_UNOPENED"
    );
}

#[test]
fn only_two_question_families_and_three_formal_surfaces_exist() {
    let authority = contract("authority_v1.json");
    let measurements = contract("measurement_registry_v1.json");
    assert_eq!(authority["question_families"].as_array().unwrap().len(), 2);
    assert_eq!(
        measurements["formal_surfaces"].as_array().unwrap().len(),
        FORMAL_TESTS
    );
    assert_eq!(
        measurements["descriptive_only"].as_array().unwrap().len(),
        7
    );
    assert!(
        measurements["descriptive_only"]
            .as_array()
            .unwrap()
            .iter()
            .any(|x| x == "GRAMMAR_RELATIONS")
    );
}

#[test]
fn complete_contract_set_validates() {
    validate_contracts(
        &contract("authority_v1.json"),
        &contract("measurement_registry_v1.json"),
        &contract("inference_v1.json"),
        &contract("candidate_schema_v1.json"),
        &contract("confirmation_v1.json"),
    )
    .unwrap();
}

#[test]
fn resolution_has_more_than_tenfold_headroom() {
    assert_eq!(minimum_randomizations(ALPHA, FORMAL_TESTS, 10), 599);
    assert!(resolution_pass(RANDOMIZATIONS, ALPHA, FORMAL_TESTS, 10));
    assert_eq!(minimum_attainable_p(RANDOMIZATIONS), 0.0001);
    assert!(minimum_attainable_p(RANDOMIZATIONS) * 10.0 <= ALPHA / FORMAL_TESTS as f64);
}

#[test]
fn wilson_decision_fails_closed_near_threshold() {
    assert_eq!(
        monte_carlo_decision(0, RANDOMIZATIONS, ALPHA / FORMAL_TESTS as f64).unwrap(),
        NumericalDecision::Pass
    );
    assert_eq!(
        monte_carlo_decision(167, RANDOMIZATIONS, ALPHA / FORMAL_TESTS as f64).unwrap(),
        NumericalDecision::Unresolved
    );
    assert_eq!(
        monte_carlo_decision(400, RANDOMIZATIONS, ALPHA / FORMAL_TESTS as f64).unwrap(),
        NumericalDecision::Fail
    );
}

#[test]
fn holm_operates_on_three_family_level_tests() {
    let decisions = holm_bonferroni(
        &[
            ("A1".into(), 0.001),
            ("A2".into(), 0.02),
            ("B1".into(), 0.04),
        ],
        ALPHA,
    );
    assert_eq!(decisions[0], ("A1".into(), true, ALPHA / 3.0));
    assert_eq!(decisions[1], ("A2".into(), true, ALPHA / 2.0));
    assert_eq!(decisions[2], ("B1".into(), true, ALPHA));
}

#[test]
fn sessions_are_balanced_before_population_aggregation() {
    let rows = vec![(1, 9.0), (1, 9.0), (1, 9.0), (1, 9.0), (2, 1.0)];
    let balanced = session_balanced_values(&rows);
    assert_eq!(balanced, vec![(1, 9.0), (2, 1.0)]);
    assert_eq!(balanced.iter().map(|x| x.1).sum::<f64>() / 2.0, 5.0);
    let mut reversed = rows;
    reversed.reverse();
    assert_eq!(balanced, session_balanced_values(&reversed));
}

#[test]
fn sign_flip_surface_is_thread_deterministic() {
    let matrix: Vec<Vec<f64>> = (0..16)
        .map(|session| {
            (0..7)
                .map(|cell| 1.0 + session as f64 * 0.1 + cell as f64 * 0.01)
                .collect()
        })
        .collect();
    let one = sign_flip_max_t_distribution(&matrix, 1023, RANDOM_SEED, 1).unwrap();
    let four = sign_flip_max_t_distribution(&matrix, 1023, RANDOM_SEED, 4).unwrap();
    assert_eq!(one, four);
    assert_eq!(
        sha256_bytes(bytemuck::cast_slice(&one)),
        sha256_bytes(bytemuck::cast_slice(&four))
    );
}

#[test]
fn null_and_effect_fixtures_behave_differently() {
    let null = vec![vec![0.0; 5]; 20];
    let null_observed = observed_max_abs_t(&null).unwrap();
    let null_ref = sign_flip_max_t_distribution(&null, 2047, RANDOM_SEED, 2).unwrap();
    assert_eq!(plus_one_p(null_observed, &null_ref).1, 1.0);

    let effect: Vec<Vec<f64>> = (0..24)
        .map(|session| vec![2.0 + session as f64 * 0.01; 5])
        .collect();
    let observed = observed_max_abs_t(&effect).unwrap();
    let reference = sign_flip_max_t_distribution(&effect, RANDOMIZATIONS, RANDOM_SEED, 2).unwrap();
    let (exceedances, p) = plus_one_p(observed, &reference);
    assert!(p <= ALPHA / FORMAL_TESTS as f64);
    assert_eq!(
        monte_carlo_decision(exceedances, RANDOMIZATIONS, ALPHA / FORMAL_TESTS as f64).unwrap(),
        NumericalDecision::Pass
    );
}

#[test]
fn anchor_tie_break_is_label_canonical() {
    let anchor = canonical_anchor(&[
        ("K30_T001".into(), 8.0),
        ("K01_T010".into(), -8.0),
        ("K02_T010".into(), 7.0),
    ]);
    assert_eq!(anchor.as_deref(), Some("K01_T010"));
}

#[test]
fn temporal_sign_rules_do_not_rescue_conflict_or_zero() {
    assert_eq!(
        temporal_sign_status(1.0, &[0.2, 1.0, 3.0]),
        "TEMPORALLY_SUPPORTED"
    );
    assert_eq!(
        temporal_sign_status(1.0, &[0.2, -1.0, 3.0]),
        "TEMPORALLY_UNSTABLE"
    );
    assert_eq!(
        temporal_sign_status(1.0, &[0.2, 0.0, 3.0]),
        "TEMPORAL_SUPPORT_INSUFFICIENT"
    );
}

fn passing_support() -> SurfaceSupport {
    SurfaceSupport {
        eligible_sessions: 150,
        month_counts: vec![30, 30, 30, 30, 30],
        offset_120_sessions: 75,
        offset_180_sessions: 75,
        chronological_block_counts: [35, 35, 35, 35],
        leave_one_month: (0..5)
            .map(|_| LeaveOneMonthSupport {
                remaining_sessions: 120,
                supported_months: 4,
                offset_120_sessions: 60,
                offset_180_sessions: 60,
            })
            .collect(),
    }
}

#[test]
fn support_floors_are_executable_and_fail_closed() {
    let good = passing_support();
    assert_eq!(surface_support_status(&good), "PASS");

    let mut weak_sessions = good.clone();
    weak_sessions.eligible_sessions = 128;
    assert_eq!(
        surface_support_status(&weak_sessions),
        "SESSION_SUPPORT_INSUFFICIENT"
    );

    let mut weak_surface = good.clone();
    weak_surface.offset_180_sessions = 19;
    assert_eq!(
        surface_support_status(&weak_surface),
        "SURFACE_SUPPORT_INSUFFICIENT"
    );

    let mut missing_lomo = good;
    missing_lomo.leave_one_month.pop();
    assert_eq!(
        surface_support_status(&missing_lomo),
        "SURFACE_SUPPORT_INSUFFICIENT"
    );
}

#[test]
fn candidate_precedence_is_executable() {
    let passing = CandidateGates {
        coverage_evaluable: true,
        support_status: "PASS",
        numerical_resolution: true,
        monte_carlo: NumericalDecision::Pass,
        omnibus_pass: true,
        holm_pass: true,
        temporal_status: "TEMPORALLY_SUPPORTED",
    };
    assert_eq!(candidate_terminal_state(passing), "PROMOTED_DISCOVERY_ONLY");
    assert_eq!(
        candidate_terminal_state(CandidateGates {
            coverage_evaluable: false,
            ..passing
        }),
        "NOT_EVALUABLE_COVERAGE"
    );
    assert_eq!(
        candidate_terminal_state(CandidateGates {
            monte_carlo: NumericalDecision::Unresolved,
            ..passing
        }),
        "NUMERICAL_DECISION_UNRESOLVED"
    );
    assert_eq!(
        candidate_terminal_state(CandidateGates {
            holm_pass: false,
            ..passing
        }),
        "FAILS_FAMILYWISE_CORRECTION"
    );
    assert_eq!(
        candidate_terminal_state(CandidateGates {
            temporal_status: "TEMPORALLY_UNSTABLE",
            ..passing
        }),
        "TEMPORALLY_UNSTABLE"
    );
}

#[test]
fn candidate_terminal_semantics_keep_causal_phase_order() {
    let measurements = contract("measurement_registry_v1.json");
    assert_eq!(
        measurements["terminal_label_rule"],
        "RETROSPECTIVE_ONLY_WITH_EXPLICIT_CAUSAL_PHASE_ORDER"
    );
    assert_eq!(
        measurements["equal_wall_clock_rule"],
        "CAUSAL_PHASE_ORDER_OVERRIDES_TIMESTAMP_EQUALITY"
    );
    assert!(
        measurements["candidate_path"]["stop"]
            .as_str()
            .unwrap()
            .contains("SUPERSESSION_COMMIT_INCLUSIVE")
    );
}

#[test]
fn confirmation_contract_grants_no_access() {
    let confirmation = contract("confirmation_v1.json");
    assert_eq!(confirmation["current_state"], "FROZEN_UNOPENED");
    assert_eq!(
        confirmation["confirmation_access_authorized_by_disc02p"],
        false
    );
    assert_eq!(confirmation["one_shot"], true);
    assert_eq!(confirmation["discovery_reselection"], false);
}

#[test]
fn protocol_source_has_no_real_data_loader_or_confirmation_path() {
    let crate_root = root();
    for relative in ["src/lib.rs", "src/main.rs"] {
        let text = fs::read_to_string(crate_root.join(relative)).unwrap();
        assert!(!text.contains("partition_manifest.tsv"));
        assert!(!text.contains("discovery_census.tsv"));
        assert!(!text.contains("D:\\"));
        assert!(!text.contains("load_m1_window"));
    }
}

#[test]
fn packed_surface_hash_is_order_sensitive_and_repeatable() {
    let left = [
        PackedSurfaceCell {
            session: 1,
            coordinate: 1,
            value: 1.0,
        },
        PackedSurfaceCell {
            session: 2,
            coordinate: 1,
            value: 2.0,
        },
    ];
    let right = [left[1], left[0]];
    assert_eq!(packed_surface_hash(&left), packed_surface_hash(&left));
    assert_ne!(packed_surface_hash(&left), packed_surface_hash(&right));
}
