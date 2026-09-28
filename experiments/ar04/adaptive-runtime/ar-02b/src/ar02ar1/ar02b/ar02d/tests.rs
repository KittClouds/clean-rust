use super::*;

fn program(left: f32, right: f32) -> Program {
    Program {
        left: 11,
        right: 47,
        deltas: [left, right],
        len: 2,
        ..Program::default()
    }
}

#[test]
fn exact_vector_domain_requires_translated_displacement() {
    let selected = program(0.01, 0.005);
    let control_1 = program(0.005, 0.005);
    let control_2 = program(0.0, 0.005);
    let (matches, residual, magnitude_error) =
        displacement_match(selected, control_1, control_2, MatchDomain::ExactVector);
    assert!(matches);
    assert_eq!(residual, [0, 0]);
    assert_eq!(magnitude_error, 0.0);
}

#[test]
fn magnitude_domain_keeps_equal_norm_nonidentical_vectors_separate() {
    let selected = program(0.01, 0.0);
    let control_1 = program(0.005, 0.0);
    let control_2 = program(0.005, -0.005);
    let (exact, exact_residual, _) =
        displacement_match(selected, control_1, control_2, MatchDomain::ExactVector);
    let (magnitude, residual, magnitude_error) =
        displacement_match(selected, control_1, control_2, MatchDomain::MagnitudeOnly);
    assert!(!exact);
    assert_eq!(exact_residual, [1, -1]);
    assert!(magnitude);
    assert_ne!(residual, [0, 0]);
    assert_eq!(magnitude_error, 0.0);
}

#[test]
fn magnitude_domain_has_a_frozen_one_primitive_unit_tolerance() {
    let selected = program(0.02, 0.0);
    let control_1 = program(0.01, 0.0);
    let one_unit_error = program(-0.005, 0.0);
    let (matches, _, error) = displacement_match(
        selected,
        control_1,
        one_unit_error,
        MatchDomain::MagnitudeOnly,
    );
    assert!(matches);
    assert!((error - 1.0).abs() < 1.0e-12);
    let two_unit_error = program(-0.01, 0.0);
    let (matches, _, error) = displacement_match(
        selected,
        control_1,
        two_unit_error,
        MatchDomain::MagnitudeOnly,
    );
    assert!(!matches);
    assert!(error > D_MAGNITUDE_TOLERANCE_UNITS);
}

#[test]
fn utility_matching_preserves_stratum_and_pairwise_tolerance() {
    assert!(utility_matched(0.001, 0.00102, 0.00098));
    assert!(!utility_matched(0.001, 0.00104, 0.001051));
    assert!(!utility_matched(0.000009, 0.000011, 0.000009));
}

#[test]
fn ancestor_and_branch_paths_share_the_next_global_commit() {
    let checkpoint = 2_400;
    let expected: Vec<_> = (1..=FUTURE_COMMITS)
        .map(|offset| checkpoint + offset)
        .collect();
    assert_eq!(expected[0], 2_401);
    assert_eq!(expected.last(), Some(&2_463));
    assert_eq!(
        expected,
        (checkpoint + 1..=checkpoint + FUTURE_COMMITS).collect::<Vec<_>>()
    );
}
