use obs_open_04a_g1::model::CoverageState;
use obs_open_04a_g5::fixtures::{observation, overflow_start, qualified_corpus, start};
use obs_open_04a_g5::grammar::{classify_pair, classify_single, realize_relative};
use obs_open_04a_g5::model::{
    PresentationLayer, RealizedTokenPair, RelativeBarToken, StartReachability,
};

#[test]
fn required_fixture_corpus_passes() {
    let rows = qualified_corpus().unwrap();
    assert!(rows.len() >= 23);
    assert!(rows.iter().all(|x| x.status == "PASS"));
}
#[test]
fn arithmetic_overflow_is_presentable_kernel_rejection() {
    let start = overflow_start("OVERFLOW").unwrap();
    let input = observation(65_536, 10_000, CoverageState::Complete);
    let result = classify_single(&start, &input);
    assert_eq!(result.layer, PresentationLayer::KernelRejected);
    assert_eq!(result.reason.as_deref(), Some("ARITHMETIC_OVERFLOW"));
    assert_eq!(result.state_unchanged, Some(true));
}
#[test]
fn applied_rejected_matrix_is_jointly_presentable() {
    let normal = start(
        "NORMAL",
        65_537,
        0,
        1,
        StartReachability::ConstructivelyReachable,
    )
    .unwrap();
    let overflow = overflow_start("OVERFLOW_PAIR").unwrap();
    let token = RelativeBarToken {
        token_id: "PAIR".into(),
        open_delta_ticks: 0,
        high_delta_ticks: 10,
        low_delta_ticks: -10,
        close_delta_ticks: 1,
        coverage_complete: true,
    };
    let left = realize_relative(&normal, &token, "N").unwrap();
    let right = observation(65_536, 10_000, CoverageState::Complete);
    let pair = classify_pair(&normal, &overflow, &RealizedTokenPair { left, right });
    assert_eq!(pair.left.layer, PresentationLayer::KernelApplied);
    assert_eq!(pair.right.layer, PresentationLayer::KernelRejected);
}
#[test]
fn rejection_does_not_become_source_invalid() {
    let overflow = overflow_start("REPEAT_REJECT").unwrap();
    for _ in 0..2 {
        let result = classify_single(
            &overflow,
            &observation(65_536, 10_000, CoverageState::Complete),
        );
        assert_eq!(result.layer, PresentationLayer::KernelRejected);
        assert_eq!(
            result.continuation_after,
            "RETAIN_PREFIX_AND_PRESENT_NEXT_EXPERIMENT_AT_SAME_CAUSAL_SLOT"
        );
    }
}
#[test]
fn g3_witness_absence_is_not_grammar_exclusion() {
    let rows = qualified_corpus().unwrap();
    assert!(
        rows.iter().any(|x| x.fixture_id == "F_BOUNDED_FIXTURE"
            && x.observed == "CONSTRUCTIVE_UNDERAPPROXIMATION")
    );
}
