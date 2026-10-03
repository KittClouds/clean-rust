use crate::THETA_STAR_ID;
use crate::authority::{expected_binding, synthetic_fiber_certificate};
use crate::explorer::{bounded_coverage, canonical_first, shrink_by_deletion};
use crate::model::{
    AuthorityVerdict, FiniteMachine, FrozenComparison, LabArtifactClass, NeutralToken,
    SearchStatus, SyntheticMachine, SyntheticState,
};
use crate::oracle::{OracleResult, independent_product_oracle};
use crate::ranking::{finite_shell, rank_key};
use crate::verifier::{
    make_certificate, verify_bounded_exhaustion, verify_finite_box_minimum, verify_no_witness_box,
    verify_separator, verify_universal_proof,
};
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct QualificationCase {
    pub fixture_id: &'static str,
    pub expected: String,
    pub observed: String,
    pub status: &'static str,
    pub ground_truth_source: &'static str,
    pub production_verifier_is_ground_truth: bool,
}

fn result(
    id: &'static str,
    expected: impl Into<String>,
    observed: impl Into<String>,
    source: &'static str,
) -> QualificationCase {
    let expected = expected.into();
    let observed = observed.into();
    QualificationCase {
        fixture_id: id,
        status: if expected == observed { "PASS" } else { "FAIL" },
        expected,
        observed,
        ground_truth_source: source,
        production_verifier_is_ground_truth: false,
    }
}

pub fn sign_machine(id: &str, fiber: &str) -> SyntheticMachine {
    SyntheticMachine {
        machine_id: id.into(),
        fiber_id: fiber.into(),
        initial_state: 0,
        states: vec![
            SyntheticState {
                protected_value: 0,
                on_negative: Some(0),
                on_zero: Some(0),
                on_positive: Some(1),
            },
            SyntheticState {
                protected_value: 1,
                on_negative: Some(0),
                on_zero: Some(1),
                on_positive: Some(1),
            },
        ],
    }
}

pub fn constant_machine(id: &str, fiber: &str, value: i64) -> SyntheticMachine {
    SyntheticMachine {
        machine_id: id.into(),
        fiber_id: fiber.into(),
        initial_state: 0,
        states: vec![SyntheticState {
            protected_value: value,
            on_negative: Some(0),
            on_zero: Some(0),
            on_positive: Some(0),
        }],
    }
}

pub fn comparison(left: SyntheticMachine, right: SyntheticMachine) -> FrozenComparison {
    let fiber_certificate = synthetic_fiber_certificate(&left, &right);
    FrozenComparison {
        left_machine: left,
        right_machine: right,
        left_start: 0,
        right_start: 0,
        gamma: "SYNTHETIC_SHARED_OBSERVATION_ALIGNMENT_V1".into(),
        theta_star_id: THETA_STAR_ID.into(),
        lambda_policy_id: "RELATIVE_COMPLETED_BAR_COUPLING_V1".into(),
        initial_correspondence_id: "SYNTHETIC_ORDER_PRESERVING_CORRESPONDENCE_V1".into(),
        left_context_id: "SYNTHETIC_CONTEXT_LEFT_V1".into(),
        right_context_id: "SYNTHETIC_CONTEXT_RIGHT_V1".into(),
        fiber_certificate,
    }
}

pub fn finite_equal_pair() -> (FiniteMachine, FiniteMachine) {
    let left = FiniteMachine {
        id: "FINITE_EQ_LEFT".into(),
        initial_state: 0,
        outputs: vec![0, 1],
        transitions: vec![vec![0, 1], vec![0, 1]],
        alphabet_size: 2,
    };
    let mut right = left.clone();
    right.id = "FINITE_EQ_RIGHT".into();
    (left, right)
}

pub fn corpus() -> Result<Vec<QualificationCase>, Box<dyn std::error::Error>> {
    let divergent = comparison(
        sign_machine("SIGN_LEFT", "FIBER_A"),
        constant_machine("CONST_RIGHT", "FIBER_A", 0),
    );
    let equivalent = comparison(
        sign_machine("SIGN_A", "FIBER_B"),
        sign_machine("SIGN_B", "FIBER_B"),
    );
    let epsilon = comparison(
        constant_machine("EPS_LEFT", "FIBER_C", 0),
        constant_machine("EPS_RIGHT", "FIBER_C", 1),
    );
    let positive = NeutralToken::flat(1);

    let cert = make_certificate(
        divergent.clone(),
        vec![positive.clone()],
        "primitive fixture",
    )?;
    let verified = verify_separator(&cert);
    let mut rows = vec![
        result(
            "VERIFIED_SEPARATOR",
            "true",
            verified.accepted.to_string(),
            "ALGEBRAICALLY_CONSTRUCTED_MACHINE",
        ),
        result(
            "VERDICT_STRING",
            "BehaviorallyNonEquivalentWithVerifiedSeparator",
            format!("{:?}", verified.verdict),
            "HAND_SPECIFIED_EXPECTATION",
        ),
        result(
            "EPSILON_SEPARATOR",
            "Some(0)",
            format!(
                "{:?}",
                make_certificate(epsilon.clone(), vec![], "epsilon")?
                    .claimed
                    .first_mismatch_experiment_ordinal
            ),
            "HAND_CONSTRUCTED_INITIAL_MISMATCH",
        ),
        result(
            "NO_SEPARATOR_ON_EQUAL_TRACE",
            "false",
            verify_separator(&make_certificate(
                equivalent.clone(),
                vec![positive.clone()],
                "equal",
            )?)
            .accepted
            .to_string(),
            "IDENTICAL_TRANSITION_TABLES",
        ),
    ];

    let mut foreign = cert.clone();
    foreign.binding.g7_root = "FOREIGN".into();
    rows.push(result(
        "CROSS_LINEAGE_REPLAY",
        "AUTHORITY_LINEAGE_MISMATCH",
        verify_separator(&foreign).code,
        "ADVERSARIAL_MUTATION",
    ));
    let mut derived = cert.clone();
    derived.claimed.first_mismatch_experiment_ordinal = Some(99);
    rows.push(result(
        "DERIVED_CLAIM_NOT_TRUSTED",
        "DERIVED_CLAIM_MISMATCH",
        verify_separator(&derived).code,
        "ADVERSARIAL_MUTATION",
    ));
    let mut no_fiber = cert.clone();
    no_fiber
        .comparison
        .fiber_certificate
        .construction_proof_hash = "BAD".into();
    rows.push(result(
        "FIBER_CERT_REQUIRED",
        "FIBER_QUALIFICATION_MISSING_OR_INVALID",
        verify_separator(&no_fiber).code,
        "ADVERSARIAL_MUTATION",
    ));
    let mut impossible = cert.clone();
    impossible.comparison.left_start = 999;
    impossible.claimed = cert.claimed.clone();
    rows.push(result(
        "IMPOSSIBLE_START_REJECTED",
        "IMPOSSIBLE_STARTING_CONFIGURATION",
        verify_separator(&impossible).code,
        "ADVERSARIAL_MUTATION",
    ));
    let invalid = NeutralToken {
        open_delta_ticks: 0,
        high_delta_ticks: 0,
        low_delta_ticks: 0,
        close_delta_ticks: 1,
        coverage_class: 1,
    };
    rows.push(result(
        "ILLEGAL_CONTINUATION_REJECTED",
        "ILLEGAL_CONTINUATION_SOURCE_GRAMMAR",
        make_certificate(divergent.clone(), vec![invalid], "invalid").unwrap_err(),
        "HAND_CONSTRUCTED_INVALID_OHLC",
    ));

    let first = canonical_first(&divergent, 1);
    rows.push(result(
        "CANONICAL_FIRST_CLASS_SEPARATE",
        "CanonicalFirstWitness",
        format!("{:?}", first.artifact_class),
        "INDEPENDENT_RANK_ORDER",
    ));
    rows.push(result(
        "CANONICAL_FIRST_SEARCH_COMPLETE",
        "Complete",
        format!("{:?}", first.search_status),
        "INDEPENDENT_RANK_ORDER",
    ));
    rows.push(result(
        "CANONICAL_FIRST_VERDICT",
        "BehaviorallyNonEquivalentWithVerifiedSeparator",
        format!("{:?}", first.authority_verdict),
        "INDEPENDENT_RANK_ORDER",
    ));
    let epsilon_first = canonical_first(&epsilon, 0);
    rows.push(result(
        "EPSILON_RANKS_FIRST",
        "0",
        epsilon_first
            .certificate
            .as_ref()
            .unwrap()
            .neutral_token_sequence
            .len()
            .to_string(),
        "RANK_DEFINITION",
    ));

    let long = make_certificate(
        divergent.clone(),
        vec![NeutralToken::flat(0), positive],
        "shrink parent",
    )?;
    let shrunk = shrink_by_deletion(&long);
    rows.push(result(
        "SHRINK_CLASS",
        "ShrunkWitness",
        format!("{:?}", shrunk.artifact_class),
        "WELL_FOUNDED_DELETION",
    ));
    rows.push(result(
        "SHRINK_LENGTH",
        "1",
        shrunk
            .certificate
            .as_ref()
            .unwrap()
            .neutral_token_sequence
            .len()
            .to_string(),
        "WELL_FOUNDED_DELETION",
    ));
    rows.push(result(
        "SHRINK_COMPARISON_FROZEN",
        "true",
        (shrunk.certificate.as_ref().unwrap().comparison == long.comparison).to_string(),
        "STRUCTURAL_EQUALITY",
    ));
    rows.push(result(
        "SHRUNK_NOT_GLOBAL_MINIMUM",
        "BehaviorallyNonEquivalentWithVerifiedSeparator",
        format!("{:?}", shrunk.authority_verdict),
        "VOCABULARY_SEPARATION",
    ));

    let (bounded_result, coverage) = bounded_coverage(&equivalent, 1);
    rows.push(result(
        "BOUNDED_SEARCH_STATUS",
        "BoundedDomainExhausted",
        format!("{:?}", bounded_result.search_status),
        "FINITE_DOMAIN_ENUMERATION",
    ));
    rows.push(result(
        "BOUNDED_SILENCE_VERDICT",
        "Unknown",
        format!("{:?}", bounded_result.authority_verdict),
        "G7_AUTHORITY_BOUNDARY",
    ));
    rows.push(result(
        "EXHAUSTION_VERIFIER",
        "true",
        verify_bounded_exhaustion(1, &coverage).to_string(),
        "EXACT_FINITE_INDEX_SET",
    ));
    rows.push(result(
        "NO_WITNESS_BOX_VERIFIER",
        "true",
        verify_no_witness_box(&equivalent, 1, &coverage).to_string(),
        "IDENTICAL_SYNTHETIC_MACHINES",
    ));
    let mut missing_index = coverage.clone();
    missing_index.visited_indices.pop();
    rows.push(result(
        "COUNTER_ONLY_NOT_COVERAGE",
        "false",
        verify_bounded_exhaustion(1, &missing_index).to_string(),
        "ADVERSARIAL_COVERAGE_MUTATION",
    ));

    let (_, divergent_coverage) = bounded_coverage(&divergent, 1);
    let first_cert = first.certificate.as_ref().unwrap();
    rows.push(result(
        "FINITE_BOX_MINIMUM",
        "MinimalWithinDeclaredFiniteBox",
        format!(
            "{:?}",
            verify_finite_box_minimum(first_cert, 1, &divergent_coverage).verdict
        ),
        "COMPLETE_LOWER_CONE_RECOMPUTATION",
    ));

    let words = finite_shell(1);
    rows.push(result(
        "FAIR_RANK_EPSILON_FIRST",
        "true",
        words.first().is_some_and(Vec::is_empty).to_string(),
        "FINITE_SHELL_CONSTRUCTION",
    ));
    rows.push(result(
        "FAIR_RANK_MONOTONE",
        "true",
        words
            .windows(2)
            .all(|w| rank_key(&w[0]) < rank_key(&w[1]))
            .to_string(),
        "FINITE_SHELL_CONSTRUCTION",
    ));

    let (finite_left, finite_right) = finite_equal_pair();
    let oracle = independent_product_oracle(&finite_left, &finite_right);
    let proof = match oracle {
        OracleResult::Equivalent(proof) => proof,
        _ => return Err("REFERENCE_ORACLE_EXPECTATION_FAILURE".into()),
    };
    rows.push(result(
        "UNIVERSAL_PROOF_ACCEPTED",
        "EquivalentWithAcceptedUniversalProof",
        format!("{:?}", verify_universal_proof(&proof).verdict),
        "INDEPENDENT_PRODUCT_ORACLE",
    ));
    let mut bad_proof = proof.clone();
    bad_proof.relation.pop();
    rows.push(result(
        "UNIVERSAL_PROOF_CLOSURE_MUTATION",
        "false",
        verify_universal_proof(&bad_proof).accepted.to_string(),
        "ADVERSARIAL_PROOF_MUTATION",
    ));

    let mut foreign_comparison = divergent.clone();
    foreign_comparison.right_machine.fiber_id = "OTHER_FIBER".into();
    let bad_fiber_cert = make_certificate(
        foreign_comparison,
        vec![NeutralToken::flat(1)],
        "cross fiber",
    )?;
    rows.push(result(
        "APPARENT_COMPATIBILITY_CANNOT_DECIDE_FIBER",
        "FIBER_QUALIFICATION_MISSING_OR_INVALID",
        verify_separator(&bad_fiber_cert).code,
        "ADVERSARIAL_CROSS_FIBER_CONSTRUCTION",
    ));
    rows.push(result(
        "BINDING_IS_EXACT",
        "true",
        (cert.binding == expected_binding()).to_string(),
        "AUTHORITY_HASH_RECOMPUTATION",
    ));
    rows.push(result(
        "TIMEOUT_NOT_VERDICT",
        "true",
        (SearchStatus::Timeout != SearchStatus::Complete
            && AuthorityVerdict::Unknown != AuthorityVerdict::VerifiedFiniteSeparator)
            .to_string(),
        "TYPE_SYSTEM",
    ));
    rows.push(result(
        "ARTIFACT_NOT_VERDICT",
        "true",
        (LabArtifactClass::ShrunkWitness != LabArtifactClass::CanonicalFirstWitness).to_string(),
        "TYPE_SYSTEM",
    ));
    Ok(rows)
}
