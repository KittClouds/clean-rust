use obs_open_04a_g6::contract::{
    CorrespondenceTransaction, candidate, compare_outcome, observable_rules, relation_law_proofs,
};
use obs_open_04a_g6::fixtures::corpus;
use obs_open_04a_g6::model::{CandidatePair, MatchVerdict, Side, TransitionOutcome};

#[test]
fn all_23_g4_observables_have_one_rule() {
    let rules = observable_rules();
    assert_eq!(rules.len(), 23);
    let mut ids = rules.iter().map(|x| &x.observable_id).collect::<Vec<_>>();
    ids.sort_unstable();
    ids.dedup();
    assert_eq!(ids.len(), 23);
}

#[test]
fn fixture_corpus_passes_without_pair_mining() {
    let fixtures = corpus().unwrap();
    assert!(fixtures.len() >= 36);
    assert!(fixtures.iter().all(|x| x.status == "PASS"));
}

#[test]
fn relation_laws_are_algebraic_not_fixture_claims() {
    let proofs = relation_law_proofs();
    for law in ["REFLEXIVITY", "SYMMETRY", "TRANSITIVITY"] {
        let proof = proofs.iter().find(|x| x.law == law).unwrap();
        assert_eq!(proof.status, "PROVEN_WITHIN_DECLARED_COMPARISON_FIBER");
        assert!(!proof.fixture_is_proof);
    }
}

#[test]
fn applied_rejected_is_behavioral_mismatch() {
    assert_eq!(
        compare_outcome(
            &TransitionOutcome::Applied,
            &TransitionOutcome::Rejected("ARITHMETIC_OVERFLOW".into())
        ),
        MatchVerdict::BehavioralMismatch
    );
}

#[test]
fn correspondence_cannot_backpatch() {
    let original = CandidatePair {
        left: candidate(Side::Upper, 1),
        right: candidate(Side::Upper, 7),
    };
    let mut transaction = CorrespondenceTransaction::new(&[original]).unwrap();
    let error = transaction
        .stage(CandidatePair {
            left: candidate(Side::Upper, 1),
            right: candidate(Side::Upper, 8),
        })
        .unwrap_err();
    assert_eq!(error, "CORRESPONDENCE_BACKPATCH_FORBIDDEN");
}
