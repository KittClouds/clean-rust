use super::*;

const GOLD_V1: &str = include_str!("../fixtures/revision-impact-gold-v1.json");

fn gold_corpus() -> RevisionImpactGoldCorpus {
    serde_json::from_str(GOLD_V1).expect("gold corpus must decode")
}

#[test]
fn mutation_vocabulary_round_trips_all_four_closed_variants() {
    let mutations = [
        StoryMutation::RetractFact {
            fact_id: "fact:old".into(),
        },
        StoryMutation::SupersedeFact {
            fact_id: "fact:limit".into(),
            replacement: FactValue::Integer(2),
            valid_from: StoryTime(300),
        },
        StoryMutation::ShiftValidity {
            fact_id: "fact:reveal".into(),
            new_interval: StoryInterval {
                valid_from: StoryTime(1200),
                valid_to_exclusive: None,
            },
        },
        StoryMutation::ChangeState {
            subject_id: "entity:kai".into(),
            state_kind: "alive".into(),
            replacement: FactValue::Boolean(false),
            valid_from: StoryTime(700),
        },
    ];

    for mutation in mutations {
        let encoded = serde_json::to_vec(&mutation).expect("mutation must encode");
        let decoded: StoryMutation =
            serde_json::from_slice(&encoded).expect("mutation must decode");
        assert_eq!(decoded, mutation);
    }
}

#[test]
fn mutation_vocabulary_rejects_unknown_fields_and_variants() {
    assert!(serde_json::from_str::<StoryMutation>(
        r#"{"kind":"retract_fact","factId":"fact:a","fallback":true}"#
    )
    .is_err());
    assert!(serde_json::from_str::<StoryMutation>(r#"{"kind":"rewrite_everything"}"#).is_err());
}

#[test]
fn constraint_vocabulary_has_closed_dependency_classes() {
    let hard = [
        ConstraintKind::RequiresKnowledge,
        ConstraintKind::RequiresWitness,
        ConstraintKind::RequiresAlive,
        ConstraintKind::RequiresPossession,
        ConstraintKind::RequiresReachability,
        ConstraintKind::RequiresState,
        ConstraintKind::RequiresTemporalOrder,
        ConstraintKind::MutuallyExclusiveStates,
    ];
    let defeasible = [
        ConstraintKind::CausalSupport,
        ConstraintKind::Motivation,
        ConstraintKind::Foreshadowing,
    ];
    let weak = [ConstraintKind::Mention, ConstraintKind::ThematicEcho];

    assert!(hard
        .into_iter()
        .all(|kind| kind.dependency_class() == DependencyClass::HardRequirement));
    assert!(defeasible
        .into_iter()
        .all(|kind| kind.dependency_class() == DependencyClass::DefeasibleSupport));
    assert!(weak
        .into_iter()
        .all(|kind| kind.dependency_class() == DependencyClass::WeakAssociation));
}

#[test]
fn gold_v1_has_all_seven_complete_mutation_families() {
    let corpus = gold_corpus();
    corpus.validate().expect("gold corpus must be complete");

    assert_eq!(corpus.cases.len(), REVISION_IMPACT_GOLD_CASE_COUNT);
    assert_eq!(
        corpus
            .cases
            .iter()
            .map(|case| case.family)
            .collect::<Vec<_>>(),
        GoldMutationFamily::ALL
    );
    assert!(corpus.cases.iter().all(|case| {
        !case.expected_impacts.is_empty()
            && !case.expected_unknowns.is_empty()
            && !case.reasonable_repairs.is_empty()
    }));
}

#[test]
fn gold_v1_never_uses_unknown_as_a_claimed_impact() {
    let corpus = gold_corpus();
    assert!(corpus.cases.iter().all(|case| {
        case.expected_impacts
            .iter()
            .all(|impact| impact.classification != ImpactClassification::Unknown)
    }));
    assert!(corpus.cases.iter().all(|case| {
        case.expected_unknowns
            .iter()
            .all(|unknown| !unknown.missing_planes.is_empty())
    }));
}

#[test]
fn gold_v1_author_gate_records_confirmed_workspace_owner_review() {
    let corpus = gold_corpus();

    assert!(corpus.author_review_complete());
    assert!(corpus.pending_author_review_ids().is_empty());
    assert!(corpus.cases.iter().all(|case| {
        case.review_status == GoldReviewStatus::AuthorReviewed
            && case.reviewed_by.as_deref() == Some("author:workspace-owner")
            && case.reviewed_at_unix_ms == Some(1784295149199)
    }));
}

#[test]
fn gold_v1_round_trips_without_contract_drift() {
    let corpus = gold_corpus();
    let encoded = serde_json::to_vec(&corpus).expect("gold corpus must encode");
    let decoded: RevisionImpactGoldCorpus =
        serde_json::from_slice(&encoded).expect("encoded corpus must decode");

    assert_eq!(decoded, corpus);
    decoded.validate().expect("round trip must remain valid");
}

#[test]
fn malformed_intervals_and_broken_soft_claims_fail_closed() {
    let mut corpus = gold_corpus();
    corpus.cases[0].mutation = StoryMutation::ShiftValidity {
        fact_id: "fact:invalid".into(),
        new_interval: StoryInterval {
            valid_from: StoryTime(12),
            valid_to_exclusive: Some(StoryTime(12)),
        },
    };
    assert!(matches!(
        corpus.validate(),
        Err(RevisionImpactContractError::InvalidInterval(_))
    ));

    let mut corpus = gold_corpus();
    corpus.cases[0].expected_impacts[0].constraint_kinds = vec![ConstraintKind::CausalSupport];
    assert!(matches!(
        corpus.validate(),
        Err(RevisionImpactContractError::BrokenWithoutHardConstraint(_))
    ));
}
