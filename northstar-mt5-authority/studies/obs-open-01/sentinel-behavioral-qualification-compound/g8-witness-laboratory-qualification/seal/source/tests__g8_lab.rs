use obs_open_04a_g8::authority::expected_binding;
use obs_open_04a_g8::explorer::{bounded_coverage, canonical_first, shrink_by_deletion};
use obs_open_04a_g8::fixtures::{
    comparison, constant_machine, corpus, finite_equal_pair, sign_machine,
};
use obs_open_04a_g8::model::{AuthorityVerdict, LabArtifactClass, NeutralToken, SearchStatus};
use obs_open_04a_g8::oracle::{OracleResult, independent_product_oracle};
use obs_open_04a_g8::ranking::{finite_shell, rank_key};
use obs_open_04a_g8::verifier::{
    make_certificate, verify_bounded_exhaustion, verify_no_witness_box, verify_separator,
    verify_universal_proof,
};

#[test]
fn qualification_corpus_is_independent_and_passes() {
    let rows = corpus().unwrap();
    assert!(rows.len() >= 30);
    assert!(rows.iter().all(|row| row.status == "PASS"));
    assert!(
        rows.iter()
            .all(|row| !row.production_verifier_is_ground_truth)
    );
}

#[test]
fn search_artifact_and_verdict_are_distinct_types() {
    let pair = comparison(sign_machine("L", "F"), constant_machine("R", "F", 0));
    let found = canonical_first(&pair, 1);
    assert_eq!(found.search_status, SearchStatus::Complete);
    assert_eq!(
        found.artifact_class,
        LabArtifactClass::CanonicalFirstWitness
    );
    assert_eq!(
        found.authority_verdict,
        AuthorityVerdict::BehaviorallyNonEquivalentWithVerifiedSeparator
    );
}

#[test]
fn timeout_or_bounded_silence_never_becomes_equivalence() {
    let pair = comparison(sign_machine("A", "F"), sign_machine("B", "F"));
    let (search, receipt) = bounded_coverage(&pair, 1);
    assert_eq!(search.search_status, SearchStatus::BoundedDomainExhausted);
    assert_eq!(search.authority_verdict, AuthorityVerdict::Unknown);
    assert!(verify_bounded_exhaustion(1, &receipt));
    assert!(verify_no_witness_box(&pair, 1, &receipt));
}

#[test]
fn derived_claims_and_lineage_are_recomputed() {
    let pair = comparison(sign_machine("L", "F"), constant_machine("R", "F", 0));
    let mut certificate = make_certificate(pair, vec![NeutralToken::flat(1)], "test").unwrap();
    assert!(verify_separator(&certificate).accepted);
    certificate.claimed.first_mismatch_experiment_ordinal = Some(42);
    assert_eq!(
        verify_separator(&certificate).code,
        "DERIVED_CLAIM_MISMATCH"
    );
    certificate.binding = expected_binding();
    certificate.binding.g7_root = "FOREIGN".into();
    assert_eq!(
        verify_separator(&certificate).code,
        "AUTHORITY_LINEAGE_MISMATCH"
    );
}

#[test]
fn ranking_is_deterministic_fair_by_finite_shell_and_epsilon_first() {
    let words = finite_shell(1);
    assert!(words.first().unwrap().is_empty());
    assert!(
        words
            .windows(2)
            .all(|pair| rank_key(&pair[0]) < rank_key(&pair[1]))
    );
}

#[test]
fn shrinking_strictly_decreases_tokens_without_mutating_comparison() {
    let pair = comparison(sign_machine("L", "F"), constant_machine("R", "F", 0));
    let parent = make_certificate(
        pair.clone(),
        vec![NeutralToken::flat(0), NeutralToken::flat(1)],
        "parent",
    )
    .unwrap();
    let shrunk = shrink_by_deletion(&parent);
    let child = shrunk.certificate.unwrap();
    assert_eq!(shrunk.artifact_class, LabArtifactClass::ShrunkWitness);
    assert!(child.neutral_token_sequence.len() < parent.neutral_token_sequence.len());
    assert_eq!(child.comparison, pair);
    assert!(verify_separator(&child).accepted);
}

#[test]
fn universal_equivalence_requires_accepted_named_proof() {
    let (left, right) = finite_equal_pair();
    let proof = match independent_product_oracle(&left, &right) {
        OracleResult::Equivalent(proof) => proof,
        _ => panic!("expected independent equivalent reference"),
    };
    let verified = verify_universal_proof(&proof);
    assert!(verified.accepted);
    assert_eq!(
        verified.verdict,
        AuthorityVerdict::EquivalentWithAcceptedUniversalProof
    );
}
