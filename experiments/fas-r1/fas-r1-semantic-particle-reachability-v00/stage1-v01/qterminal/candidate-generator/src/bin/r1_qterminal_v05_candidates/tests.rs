use super::*;

fn task() -> Task {
    Task {
        id: "test-task".to_owned(),
        family_id: "test-family".to_owned(),
        seed: 1,
        n: 4,
        k: 3,
        clauses: vec![
            Clause::Different { a: 0, b: 1 },
            Clause::Same { a: 2, b: 3 },
            Clause::ImpliesNotRole {
                if_entity: 0,
                if_role: 1,
                then_entity: 2,
                then_role: 2,
            },
        ],
        role_anonymous: true,
    }
}

#[test]
fn complete_partial_check_matches_both_validators() {
    let task = task();
    for a in 0..task.k {
        for b in 0..task.k {
            for c in 0..task.k {
                for d in 0..task.k {
                    let assignment = [a, b, c, d];
                    assert_eq!(
                        partial_constraints_hold(&task, &assignment),
                        validate(&task, &assignment)
                    );
                    assert_eq!(
                        validate(&task, &assignment),
                        validate_independent(&task, &assignment)
                    );
                }
            }
        }
    }
}

#[test]
fn randomized_solution_sampling_is_replayable_and_valid() {
    let task = task();
    let first = sample_valid_solutions(&task, 12, 0x1234).unwrap();
    let replay = sample_valid_solutions(&task, 12, 0x1234).unwrap();
    assert_eq!(first, replay);
    assert!(!first.is_empty());
    assert!(first
        .iter()
        .all(|assignment| validator_pair(&task, assignment) == Ok(true)));
}

#[test]
fn invalid_sampling_is_unique_balanced_and_validated() {
    let task = task();
    let positives = sample_valid_solutions(&task, 8, 0x5678).unwrap();
    let negatives = sample_invalid_assignments(&task, &positives, positives.len(), 0x9abc).unwrap();
    assert_eq!(negatives.len(), positives.len());
    let mut unique = HashSet::new();
    for (assignment, _) in negatives {
        assert!(unique.insert(assignment.clone()));
        assert_eq!(validator_pair(&task, &assignment), Ok(false));
    }
}
