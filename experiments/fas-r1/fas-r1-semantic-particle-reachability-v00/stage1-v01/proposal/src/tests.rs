use crate::{
    build_reachability_dataset, build_teacher_target, ExactSolutionClasses, FrozenProposal,
    IndividualState, ProposalActionProbability, ProposalContext, PublicFeatures, RolloutError,
    TeacherOutcome,
};
use r1_world::{render_task, Clause, InferenceTask, Task};
use std::cell::Cell;

fn two_class_task() -> Task {
    Task {
        id: "two-targets".to_owned(),
        family_id: "test-family".to_owned(),
        seed: 1,
        n: 2,
        k: 3,
        clauses: vec![Clause::FixedRole { entity: 0, role: 0 }],
        role_anonymous: false,
    }
}

fn unique_class_task() -> Task {
    Task {
        id: "unique-class".to_owned(),
        family_id: "test-family".to_owned(),
        seed: 2,
        n: 1,
        k: 1,
        clauses: vec![],
        role_anonymous: false,
    }
}

fn public_pair(task: &Task) -> (InferenceTask, PublicFeatures) {
    let rendered = render_task(task, 700);
    let feature = PublicFeatures {
        sensor_artifact_sha256: "a".repeat(64),
        global_embedding: vec![0.1, -0.2],
        clause_embeddings: rendered
            .inference
            .clauses
            .iter()
            .map(|_| vec![0.3, 0.4])
            .collect(),
    };
    (rendered.inference, feature)
}

struct UniformFrozenProposal;

impl FrozenProposal for UniformFrozenProposal {
    fn snapshot_sha256(&self) -> [u8; 32] {
        [7; 32]
    }

    fn action_distribution(
        &self,
        context: &ProposalContext<'_>,
        _remaining_budget: u32,
    ) -> Result<Vec<ProposalActionProbability>, String> {
        let mut actions = Vec::new();
        for entity in 0..context.inference.n {
            let current = context.assignment[usize::from(entity)];
            for new_role in 0..context.inference.k {
                if new_role != current {
                    actions.push((entity, new_role));
                }
            }
        }
        let probability = 1.0 / actions.len() as f64;
        Ok(actions
            .into_iter()
            .map(|(entity, new_role)| ProposalActionProbability {
                entity,
                new_role,
                probability,
            })
            .collect())
    }

    fn advance_latent(
        &self,
        _context: &ProposalContext<'_>,
        _entity: u16,
        _new_role: u8,
    ) -> Result<Vec<f32>, String> {
        Ok(vec![0.0, 0.25])
    }
}

struct RepairProposal {
    calls: Cell<usize>,
}

impl FrozenProposal for RepairProposal {
    fn snapshot_sha256(&self) -> [u8; 32] {
        [9; 32]
    }

    fn action_distribution(
        &self,
        context: &ProposalContext<'_>,
        _remaining_budget: u32,
    ) -> Result<Vec<ProposalActionProbability>, String> {
        self.calls.set(self.calls.get() + 1);
        let action = if context.assignment[0] != 0 {
            (0, 0)
        } else if context.assignment[1] != 1 {
            (1, 1)
        } else {
            (1, 0)
        };
        Ok(vec![ProposalActionProbability {
            entity: action.0,
            new_role: action.1,
            probability: 1.0,
        }])
    }

    fn advance_latent(
        &self,
        _context: &ProposalContext<'_>,
        _entity: u16,
        _new_role: u8,
    ) -> Result<Vec<f32>, String> {
        Ok(vec![0.0, 0.25])
    }
}

#[test]
fn teacher_preserves_multiple_valid_classes_without_picking_one_target() {
    let task = two_class_task();
    let classes = ExactSolutionClasses::solve(&task, 32).unwrap();
    assert_eq!(classes.raw_solution_count(), 3);
    assert_eq!(classes.classes().len(), 3);

    let target = build_teacher_target(&task, &classes, &[0, 0]).unwrap();
    assert_eq!(target.outcome, TeacherOutcome::PositiveMass);
    let positive: Vec<_> = target
        .edits
        .iter()
        .filter(|edit| edit.q_probability > 0.0)
        .collect();
    assert_eq!(positive.len(), 2);
    assert_eq!((positive[0].entity, positive[0].new_role), (1, 1));
    assert_eq!((positive[1].entity, positive[1].new_role), (1, 2));
    assert!((positive[0].q_probability - 0.5).abs() < 1e-12);
    assert!((positive[1].q_probability - 0.5).abs() < 1e-12);
    assert_eq!(positive[0].n_improved_classes, 1);
    assert_eq!(positive[1].n_improved_classes, 1);
    assert_eq!(positive[0].delta_d_min, 0);
}

#[test]
fn a_solved_single_class_state_has_explicit_zero_teacher_mass() {
    let task = unique_class_task();
    let classes = ExactSolutionClasses::solve(&task, 4).unwrap();
    let target = build_teacher_target(&task, &classes, &[0]).unwrap();
    assert_eq!(target.outcome, TeacherOutcome::ZeroMass);
    assert_eq!(target.total_improved_class_mass, 0);
    assert!(target.edits.is_empty());
}

#[test]
fn canonical_role_symmetry_collapses_raw_solutions_before_teacher_balancing() {
    let task = Task {
        id: "anonymous-roles".to_owned(),
        family_id: "test-family".to_owned(),
        seed: 3,
        n: 2,
        k: 2,
        clauses: vec![],
        role_anonymous: true,
    };
    let classes = ExactSolutionClasses::solve(&task, 8).unwrap();
    assert_eq!(classes.raw_solution_count(), 4);
    assert_eq!(classes.classes().len(), 2);
    assert!(classes
        .classes()
        .iter()
        .all(|class| class.members.len() == 2));
    let target = build_teacher_target(&task, &classes, &[0, 0]).unwrap();
    assert_eq!(target.class_count, 2);
    assert_eq!(target.total_improved_class_mass, 2);
}

#[test]
fn reachability_rollouts_are_seeded_and_run_the_full_budget_after_a_hit() {
    let task = two_class_task();
    let (inference, features) = public_pair(&task);
    let state = IndividualState {
        state_id: "state-0001".to_owned(),
        assignment: vec![0, 0],
        latent_state: vec![0.0, 0.0],
        remaining_budget: 5,
    };
    let first = build_reachability_dataset(
        &task,
        &inference,
        &features,
        std::slice::from_ref(&state),
        12345,
        8,
        &UniformFrozenProposal,
    )
    .unwrap();
    let replay = build_reachability_dataset(
        &task,
        &inference,
        &features,
        &[state],
        12345,
        8,
        &UniformFrozenProposal,
    )
    .unwrap();
    assert_eq!(first, replay);
    assert_eq!(first.states[0].rollouts.len(), 8);
    assert!(first.states[0]
        .rollouts
        .iter()
        .all(|row| row.transitions == 5));
    assert!(first.states[0]
        .rollouts
        .iter()
        .all(|row| row.success_within_budget == row.first_hit_step.is_some()));
}

#[test]
fn posthoc_hit_label_does_not_stop_the_frozen_proposal() {
    let task = two_class_task();
    let (inference, features) = public_pair(&task);
    let proposal = RepairProposal {
        calls: Cell::new(0),
    };
    let data = build_reachability_dataset(
        &task,
        &inference,
        &features,
        &[IndividualState {
            state_id: "needs-repair".to_owned(),
            assignment: vec![1, 0],
            latent_state: vec![0.0, 0.0],
            remaining_budget: 3,
        }],
        99,
        1,
        &proposal,
    )
    .unwrap();
    assert_eq!(proposal.calls.get(), 3);
    assert_eq!(data.states[0].rollouts[0].first_hit_step, Some(1));
    assert_eq!(data.states[0].rollouts[0].transitions, 3);
}

#[test]
fn runtime_proposal_receives_only_the_public_projection() {
    fn assert_public_type(_: &InferenceTask) {}
    let task = two_class_task();
    let (inference, _) = public_pair(&task);
    assert_public_type(&inference);
    assert!(!serde_json::to_string(&inference)
        .unwrap()
        .contains("FixedRole"));
}

#[test]
fn mismatched_clause_feature_count_is_rejected_before_rollout() {
    let task = two_class_task();
    let (inference, mut features) = public_pair(&task);
    features.clause_embeddings.clear();
    let error = build_reachability_dataset(
        &task,
        &inference,
        &features,
        &[IndividualState {
            state_id: "s".to_owned(),
            assignment: vec![0, 0],
            latent_state: vec![],
            remaining_budget: 1,
        }],
        0,
        1,
        &UniformFrozenProposal,
    )
    .unwrap_err();
    assert!(matches!(error, RolloutError::FeatureClauseCount { .. }));
}
