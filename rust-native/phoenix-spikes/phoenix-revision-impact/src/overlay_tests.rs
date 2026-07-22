use super::*;
use phoenix_types::StoryTime;

fn interval(start: i64, end: Option<i64>) -> StoryInterval {
    StoryInterval {
        valid_from: StoryTime(start),
        valid_to_exclusive: end.map(StoryTime),
    }
}

fn state_ref(subject: &str, kind: &str) -> StateRef {
    StateRef {
        subject_id: subject.into(),
        state_kind: kind.into(),
    }
}

fn digest(byte: u8) -> GraphTruthDigest {
    GraphTruthDigest([byte; 32])
}

fn base_snapshot() -> RevisionGraphSnapshot {
    RevisionGraphSnapshot::new(
        GraphGeneration(41),
        vec![
            RevisionFactRecord {
                fact_id: "fact:knowledge".into(),
                value: FactValue::Boolean(true),
                interval: interval(400, None),
            },
            RevisionFactRecord {
                fact_id: "fact:travel".into(),
                value: FactValue::DurationMinutes(120),
                interval: interval(0, None),
            },
        ],
        vec![RevisionStateRecord {
            state_ref: state_ref("entity:kai", "possession:key"),
            value: FactValue::Boolean(true),
            interval: interval(500, None),
        }],
        vec![
            RevisionEdgeRecord {
                edge_id: "edge:knowledge-to-scene".into(),
                dependency_fact_ids: vec!["fact:knowledge".into()],
                dependency_state_refs: Vec::new(),
            },
            RevisionEdgeRecord {
                edge_id: "edge:possession-to-vault".into(),
                dependency_fact_ids: Vec::new(),
                dependency_state_refs: vec![state_ref("entity:kai", "possession:key")],
            },
            RevisionEdgeRecord {
                edge_id: "edge:unrelated".into(),
                dependency_fact_ids: Vec::new(),
                dependency_state_refs: Vec::new(),
            },
        ],
        vec![
            NamedSidecarDigest {
                sidecar_id: "event-identity".into(),
                digest: digest(1),
            },
            NamedSidecarDigest {
                sidecar_id: "temporal".into(),
                digest: digest(2),
            },
        ],
    )
    .expect("base snapshot")
}

#[test]
fn overlay_changes_effective_values_without_changing_base_digests() {
    let base = base_snapshot();
    let base_digest = base.digest();
    let sidecars = base.sidecar_digests().to_vec();
    {
        let overlay = CounterfactualGraphView::new(
            &base,
            vec![
                StoryMutation::ShiftValidity {
                    fact_id: "fact:knowledge".into(),
                    new_interval: interval(1_200, None),
                },
                StoryMutation::ChangeState {
                    subject_id: "entity:kai".into(),
                    state_kind: "possession:key".into(),
                    replacement: FactValue::Boolean(false),
                    valid_from: StoryTime(600),
                },
            ],
        )
        .expect("overlay");

        assert_eq!(overlay.base_generation, GraphGeneration(41));
        assert_eq!(overlay.receipt.base_digest, base_digest);
        assert_eq!(overlay.receipt.base_sidecar_digests, sidecars);
        assert!(overlay.receipt.no_base_writes);
        assert_eq!(
            overlay
                .effective_fact(&FactId::from("fact:knowledge"))
                .expect("effective fact")
                .interval,
            interval(1_200, None)
        );
        assert_eq!(
            overlay
                .effective_state(&state_ref("entity:kai", "possession:key"))
                .expect("effective state")
                .value,
            FactValue::Boolean(false)
        );
        assert!(overlay.edge_is_invalidated("edge:knowledge-to-scene"));
        assert!(overlay.edge_is_invalidated("edge:possession-to-vault"));
        assert!(!overlay.edge_is_invalidated("edge:unrelated"));
        assert_eq!(base.digest(), base_digest);
    }
    assert_eq!(base.digest(), base_digest);
    assert_eq!(base.sidecar_digests(), sidecars);
}

#[test]
fn overlay_retraction_hides_fact_only_inside_view() {
    let base = base_snapshot();
    let overlay = CounterfactualGraphView::new(
        &base,
        vec![StoryMutation::RetractFact {
            fact_id: "fact:travel".into(),
        }],
    )
    .expect("overlay");

    assert!(overlay
        .effective_fact(&FactId::from("fact:travel"))
        .is_none());
    assert!(base.fact(&FactId::from("fact:travel")).is_some());
}

#[test]
fn supersession_and_state_change_preserve_baseline_before_valid_from() {
    let base = base_snapshot();
    let overlay = CounterfactualGraphView::new(
        &base,
        vec![
            StoryMutation::SupersedeFact {
                fact_id: "fact:travel".into(),
                replacement: FactValue::DurationMinutes(480),
                valid_from: StoryTime(800),
            },
            StoryMutation::ChangeState {
                subject_id: "entity:kai".into(),
                state_kind: "possession:key".into(),
                replacement: FactValue::Boolean(false),
                valid_from: StoryTime(900),
            },
        ],
    )
    .unwrap();

    assert!(overlay.fact_satisfies(
        &"fact:travel".into(),
        &FactValue::DurationMinutes(120),
        interval(700, Some(701)),
    ));
    assert!(!overlay.fact_satisfies(
        &"fact:travel".into(),
        &FactValue::DurationMinutes(120),
        interval(800, Some(801)),
    ));
    assert!(overlay.state_satisfies(
        &state_ref("entity:kai", "possession:key"),
        &FactValue::Boolean(true),
        interval(800, Some(801)),
    ));
    assert!(!overlay.state_satisfies(
        &state_ref("entity:kai", "possession:key"),
        &FactValue::Boolean(true),
        interval(900, Some(901)),
    ));
}

#[test]
fn mutation_order_does_not_change_overlay_or_receipt() {
    let base = base_snapshot();
    let left = StoryMutation::ShiftValidity {
        fact_id: "fact:knowledge".into(),
        new_interval: interval(1_200, None),
    };
    let right = StoryMutation::SupersedeFact {
        fact_id: "fact:travel".into(),
        replacement: FactValue::DurationMinutes(480),
        valid_from: StoryTime(0),
    };

    let first =
        CounterfactualGraphView::new(&base, vec![left.clone(), right.clone()]).expect("first");
    let second = CounterfactualGraphView::new(&base, vec![right, left]).expect("second");

    assert_eq!(first.mutations, second.mutations);
    assert_eq!(first.overridden_facts, second.overridden_facts);
    assert_eq!(first.invalidated_edges, second.invalidated_edges);
    assert_eq!(first.receipt, second.receipt);
}

#[test]
fn conflicting_or_missing_fact_mutations_fail_closed() {
    let base = base_snapshot();
    let conflict = CounterfactualGraphView::new(
        &base,
        vec![
            StoryMutation::RetractFact {
                fact_id: "fact:knowledge".into(),
            },
            StoryMutation::ShiftValidity {
                fact_id: "fact:knowledge".into(),
                new_interval: interval(1_200, None),
            },
        ],
    );
    assert!(matches!(
        conflict,
        Err(CounterfactualOverlayError::ConflictingMutation(_))
    ));

    let missing = CounterfactualGraphView::new(
        &base,
        vec![StoryMutation::RetractFact {
            fact_id: "fact:missing".into(),
        }],
    );
    assert!(matches!(
        missing,
        Err(CounterfactualOverlayError::MissingFact(_))
    ));
}

#[test]
fn snapshot_digest_is_independent_of_input_order() {
    let first = base_snapshot();
    let second = RevisionGraphSnapshot::new(
        first.generation(),
        first.facts().iter().cloned().rev().collect(),
        first.states().iter().cloned().rev().collect(),
        first.edges().iter().cloned().rev().collect(),
        first.sidecar_digests().iter().cloned().rev().collect(),
    )
    .expect("reordered snapshot");

    assert_eq!(first, second);
    assert_eq!(first.digest(), second.digest());
}
