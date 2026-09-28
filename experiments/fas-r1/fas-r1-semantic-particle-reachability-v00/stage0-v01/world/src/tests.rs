use serde_json::to_string;

use crate::{
    automorphisms, canonical_assignment, enumerate_solutions, generate_family,
    generate_qualified_fixture, generate_smoke_batch, generate_task, render_task, validate,
    validate_independent, Clause, GenerationSpec, SolutionStratum, SolveError, Task,
};

fn task(n: u16, k: u8, clauses: Vec<Clause>, role_anonymous: bool) -> Task {
    Task {
        id: "test".to_owned(),
        family_id: "family".to_owned(),
        seed: 17,
        n,
        k,
        clauses,
        role_anonymous,
    }
}

fn assignments(n: u16, k: u8) -> Vec<Vec<u8>> {
    fn walk(n: usize, k: u8, values: &mut Vec<u8>, result: &mut Vec<Vec<u8>>) {
        if values.len() == n {
            result.push(values.clone());
            return;
        }
        for role in 0..k {
            values.push(role);
            walk(n, k, values, result);
            values.pop();
        }
    }
    let mut result = Vec::new();
    walk(
        usize::from(n),
        k,
        &mut Vec::with_capacity(usize::from(n)),
        &mut result,
    );
    result
}

fn cross_check(task: &Task) {
    let valid: Vec<Vec<u8>> = assignments(task.n, task.k)
        .into_iter()
        .filter(|assignment| validate_independent(task, assignment))
        .collect();
    let solved = enumerate_solutions(task, valid.len() + 1).expect("unbounded tiny solve");
    assert_eq!(solved, valid, "solver disagrees with independent validator");
    for assignment in assignments(task.n, task.k) {
        let fast = validate(task, &assignment);
        let independent = validate_independent(task, &assignment);
        assert_eq!(fast, independent, "validators disagree on {assignment:?}");
    }
}

fn clause_candidates(n: u16, k: u8) -> Vec<Clause> {
    let mut clauses = Vec::new();
    for left in 0..n {
        for right in (left + 1)..n {
            clauses.push(Clause::Same { a: left, b: right });
            clauses.push(Clause::Different { a: left, b: right });
        }
    }
    for entity in 0..n {
        for role in 0..k {
            clauses.push(Clause::FixedRole { entity, role });
            clauses.push(Clause::ForbiddenRole { entity, role });
        }
    }
    for mask in 1usize..(1usize << n) {
        let entities = (0..n)
            .filter(|entity| (mask & (1usize << usize::from(*entity))) != 0)
            .collect::<Vec<_>>();
        for role in 0..k {
            clauses.push(Clause::ExactlyOneRole {
                entities: entities.clone(),
                role,
            });
        }
    }
    for if_entity in 0..n {
        for if_role in 0..k {
            for then_entity in 0..n {
                for then_role in 0..k {
                    clauses.push(Clause::ImpliesNotRole {
                        if_entity,
                        if_role,
                        then_entity,
                        then_role,
                    });
                }
            }
        }
    }
    clauses
}

#[test]
fn exhaustive_tiny_single_clause_validator_and_solver_checks() {
    for n in 1..=3 {
        for k in 1..=3 {
            for clause in clause_candidates(n, k) {
                cross_check(&task(n, k, vec![clause], false));
            }
        }
    }
}

#[test]
fn exhaustive_tiny_multi_clause_checks_cover_interactions_and_pruning() {
    let clauses = [
        Clause::Same { a: 0, b: 1 },
        Clause::Different { a: 1, b: 2 },
        Clause::FixedRole { entity: 0, role: 0 },
        Clause::ForbiddenRole { entity: 1, role: 2 },
        Clause::ExactlyOneRole {
            entities: vec![0, 1, 2],
            role: 1,
        },
        Clause::ImpliesNotRole {
            if_entity: 0,
            if_role: 0,
            then_entity: 2,
            then_role: 2,
        },
    ];
    for left in 0..clauses.len() {
        for right in left..clauses.len() {
            cross_check(&task(
                3,
                3,
                vec![clauses[left].clone(), clauses[right].clone()],
                false,
            ));
        }
    }
}

#[test]
fn generated_n6_k3_worlds_match_solver_and_independent_validator_exhaustively() {
    for (offset, role_anonymous) in [false, true].into_iter().enumerate() {
        let generated = generate_task(
            0xA700 + offset as u64,
            GenerationSpec {
                n: 6,
                k: 3,
                stratum: SolutionStratum::Medium,
                role_anonymous,
            },
        )
        .unwrap();
        cross_check(&generated);
    }
}

#[test]
fn cap_is_not_reported_as_an_exhaustive_solution_count() {
    let unconstrained = task(3, 3, Vec::new(), false);
    assert_eq!(enumerate_solutions(&unconstrained, 27).unwrap().len(), 27);
    assert_eq!(
        enumerate_solutions(&unconstrained, 26),
        Err(SolveError::CapExceeded {
            cap: 26,
            found_at_least: 27,
        })
    );
    assert_eq!(
        enumerate_solutions(&unconstrained, 0).unwrap_err(),
        SolveError::CapExceeded {
            cap: 0,
            found_at_least: 1,
        }
    );
}

#[test]
fn malformed_tasks_and_assignments_fail_closed() {
    let bad_task = task(
        2,
        2,
        vec![Clause::ExactlyOneRole {
            entities: vec![0, 0],
            role: 1,
        }],
        false,
    );
    assert!(!validate(&bad_task, &[0, 1]));
    assert!(!validate_independent(&bad_task, &[0, 1]));
    assert!(matches!(
        enumerate_solutions(&bad_task, 10),
        Err(SolveError::InvalidTask(_))
    ));

    let good = task(
        1,
        2,
        vec![Clause::ForbiddenRole { entity: 0, role: 0 }],
        false,
    );
    assert!(!validate(&good, &[2]));
    assert!(!validate_independent(&good, &[2]));
    assert!(!validate(&good, &[]));
    assert!(!validate_independent(&good, &[]));
}

#[test]
fn anonymous_role_permutations_define_canonical_classes() {
    let anonymous = task(2, 3, vec![Clause::Same { a: 0, b: 1 }], true);
    let group = automorphisms(&anonymous);
    assert_eq!(group.len(), 6);
    assert_eq!(
        canonical_assignment(&[0, 0], &group),
        canonical_assignment(&[2, 2], &group)
    );
    assert_eq!(
        canonical_assignment(&[0, 1], &group),
        canonical_assignment(&[2, 1], &group)
    );
    let canonical = canonical_assignment(&[2, 0], &group);
    assert_eq!(canonical_assignment(&canonical, &group), canonical);
    for permutation in &group {
        let mapped: Vec<u8> = [0u8, 0]
            .iter()
            .map(|role| permutation[usize::from(*role)])
            .collect();
        assert!(validate(&anonymous, &mapped));
    }

    let role_specific = task(1, 3, vec![Clause::FixedRole { entity: 0, role: 1 }], false);
    let group = automorphisms(&role_specific);
    assert_eq!(group, vec![vec![0, 1, 2]]);
    assert_ne!(
        canonical_assignment(&[0], &group),
        canonical_assignment(&[1], &group)
    );
}

#[test]
fn qualified_generator_hits_canonical_strata_in_both_role_modes() {
    let cases = [
        (SolutionStratum::Unique, true, 1),
        (SolutionStratum::Small, true, 2),
        (SolutionStratum::Medium, true, 8),
        (SolutionStratum::Broad, true, 32),
        (SolutionStratum::Unique, false, 1),
        (SolutionStratum::Small, false, 2),
        (SolutionStratum::Medium, false, 8),
        (SolutionStratum::Broad, false, 32),
    ];
    for (index, (stratum, role_anonymous, expected)) in cases.into_iter().enumerate() {
        let fixture = generate_qualified_fixture(
            100 + index as u64,
            GenerationSpec {
                n: 6,
                k: 2,
                stratum,
                role_anonymous,
            },
        )
        .unwrap();
        assert_eq!(fixture.canonical_solution_class_count, expected);
        assert!(stratum.contains(fixture.canonical_solution_class_count));
        assert!(fixture.raw_solution_count >= fixture.canonical_solution_class_count);
    }
}

#[test]
fn smoke_batch_is_deterministic_and_covers_declared_strata() {
    let first = generate_smoke_batch(0x1234_5678, 96).unwrap();
    let replay = generate_smoke_batch(0x1234_5678, 96).unwrap();
    assert_eq!(first, replay);
    assert_eq!(first.len(), 96);
    let mut strata_seen = [false; 4];
    let mut modes_seen = [false; 2];
    for item in &first {
        modes_seen[usize::from(item.role_anonymous)] = true;
        let solutions = enumerate_solutions(item, 4_096).unwrap();
        let group = automorphisms(item);
        let canonical = solutions
            .iter()
            .map(|assignment| canonical_assignment(assignment, &group))
            .collect::<hashbrown::HashSet<_>>();
        let count = canonical.len();
        if count == 1 {
            strata_seen[0] = true;
        } else if count <= 4 {
            strata_seen[1] = true;
        } else if count <= 16 {
            strata_seen[2] = true;
        } else {
            strata_seen[3] = true;
        }
    }
    assert_eq!(modes_seen, [true, true]);
    assert_eq!(strata_seen, [true, true, true, true]);
    let family_count = first
        .iter()
        .map(|item| item.family_id.as_str())
        .collect::<hashbrown::HashSet<_>>()
        .len();
    assert!(family_count > 8, "smoke worlds need varied latent families");
}

#[test]
fn family_ids_ignore_entity_role_relabeling_and_clause_order() {
    for role_anonymous in [false, true] {
        let spec = GenerationSpec {
            n: 7,
            k: 3,
            stratum: SolutionStratum::Medium,
            role_anonymous,
        };
        let generated = generate_task(0xF011, spec).unwrap();
        let entity_map: Vec<u16> = (0..generated.n).rev().collect();
        let role_map: Vec<u8> = (0..generated.k)
            .map(|role| (role + 1) % generated.k)
            .collect();
        let mut relabeled: Vec<Clause> = generated
            .clauses
            .iter()
            .map(|clause| match clause {
                Clause::Same { a, b } => Clause::Same {
                    a: entity_map[usize::from(*a)],
                    b: entity_map[usize::from(*b)],
                },
                Clause::Different { a, b } => Clause::Different {
                    a: entity_map[usize::from(*a)],
                    b: entity_map[usize::from(*b)],
                },
                Clause::FixedRole { entity, role } => Clause::FixedRole {
                    entity: entity_map[usize::from(*entity)],
                    role: role_map[usize::from(*role)],
                },
                Clause::ForbiddenRole { entity, role } => Clause::ForbiddenRole {
                    entity: entity_map[usize::from(*entity)],
                    role: role_map[usize::from(*role)],
                },
                Clause::ExactlyOneRole { entities, role } => Clause::ExactlyOneRole {
                    entities: entities
                        .iter()
                        .map(|entity| entity_map[usize::from(*entity)])
                        .collect(),
                    role: role_map[usize::from(*role)],
                },
                Clause::ImpliesNotRole {
                    if_entity,
                    if_role,
                    then_entity,
                    then_role,
                } => Clause::ImpliesNotRole {
                    if_entity: entity_map[usize::from(*if_entity)],
                    if_role: role_map[usize::from(*if_role)],
                    then_entity: entity_map[usize::from(*then_entity)],
                    then_role: role_map[usize::from(*then_role)],
                },
            })
            .collect();
        relabeled.reverse();
        assert_eq!(
            crate::generator::family_id(spec, &relabeled),
            generated.family_id
        );
    }
}

#[test]
fn family_identity_precedes_surface_randomization_and_projection_hides_seed() {
    let spec = GenerationSpec {
        n: 8,
        k: 3,
        stratum: SolutionStratum::Medium,
        role_anonymous: true,
    };
    let first = generate_task(11, spec).unwrap();
    let replay_task = generate_task(11, spec).unwrap();
    let second = generate_task(12, spec).unwrap();
    assert_eq!(to_string(&first).unwrap(), to_string(&replay_task).unwrap());
    assert_eq!(first.family_id, replay_task.family_id);
    assert_ne!(first.id, second.id);

    let rendered = render_task(&first, 777);
    assert_eq!(rendered, render_task(&first, 777));
    assert_eq!(rendered.text, rendered.inference.global_text);
    assert_eq!(
        rendered.inference.clauses.len(),
        rendered.clause_order.len()
    );
    assert_eq!(
        rendered.inference.clauses.len(),
        rendered.template_ids.len()
    );
    assert_eq!(
        rendered.inference.clauses.len(),
        rendered.inference.entity_mentions.len()
    );
    assert_eq!(
        rendered.inference.clauses.len(),
        rendered.inference.role_mentions.len()
    );

    let projection_json = to_string(&rendered.inference).unwrap();
    assert!(!projection_json.contains("\"seed\""));
    assert!(!projection_json.contains("Same"));
    assert!(!projection_json.contains("raw_solution_count"));
    assert!(!projection_json.contains("canonical_solution_class_count"));
    assert!(projection_json.contains("global_text"));

    let family = generate_family(11, spec, &[10, 20, 30]).unwrap();
    assert_eq!(family.surfaces.len(), 3);
    assert!(family
        .surfaces
        .iter()
        .all(|surface| { surface.inference.family_id == family.task.family_id }));
}

#[test]
fn unique_anonymous_task_has_multiple_raw_assignments_but_one_class() {
    let fixture = generate_qualified_fixture(
        55,
        GenerationSpec {
            n: 6,
            k: 3,
            stratum: SolutionStratum::Unique,
            role_anonymous: true,
        },
    )
    .unwrap();
    assert_eq!(fixture.raw_solution_count, 3);
    assert_eq!(fixture.canonical_solution_class_count, 1);
}
