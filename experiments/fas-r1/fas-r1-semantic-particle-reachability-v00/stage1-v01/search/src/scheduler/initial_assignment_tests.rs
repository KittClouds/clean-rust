use super::*;
use crate::{PolicyLatentUpdate, PolicyValue};
use r1_search::RunConfig;
use r1_world::{InferenceTask, Task};

struct NoopPolicy;

impl SearchPolicy for NoopPolicy {
    fn score_edits(
        &mut self,
        _input: TransitionInput<'_>,
        candidates: &[Edit],
    ) -> Result<PolicyScores, PolicyError> {
        Ok(PolicyScores {
            logits: vec![0.0; candidates.len()],
            costs: PolicyCosts::default(),
        })
    }

    fn advance_latent(
        &mut self,
        input: TransitionInput<'_>,
        _selected: Edit,
    ) -> Result<PolicyLatentUpdate, PolicyError> {
        Ok(PolicyLatentUpdate {
            next_state: input.latent_state.to_vec(),
            costs: PolicyCosts::default(),
        })
    }

    fn q_terminal(&mut self, _input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError> {
        Ok(PolicyValue {
            value: 0.5,
            ..PolicyValue::default()
        })
    }

    fn v_reach(&mut self, _input: ValueInput<'_>) -> Result<PolicyValue, PolicyError> {
        Ok(PolicyValue {
            value: 0.5,
            ..PolicyValue::default()
        })
    }
}

fn fixture() -> (InferenceTask, SemanticFeatures) {
    let task = Task {
        id: "explicit-start-task".to_owned(),
        family_id: "explicit-start-family".to_owned(),
        seed: 1,
        n: 2,
        k: 2,
        clauses: Vec::new(),
        role_anonymous: true,
    };
    let inference = r1_world::render_task(&task, 2).inference;
    let features = SemanticFeatures::from_projection(
        &inference,
        2,
        Vec::new().into_boxed_slice(),
        vec![0.0, 0.0].into_boxed_slice(),
    )
    .unwrap();
    (inference, features)
}

#[test]
fn explicit_initial_assignment_is_the_first_particle_state() {
    let (task, features) = fixture();
    let mut base = RunConfig::new(Arm::Depth, 1, 1, 17);
    base.latent_dim = 1;
    let mut config = Stage1RunConfig::from_stage0(base);
    config.initial_assignment = Some(vec![1, 0]);

    let result = run(&task, &features, config, &mut NoopPolicy).unwrap();

    assert_eq!(result.trace.header.initial_particles[0].assignment, [1, 0]);
}

#[test]
fn invalid_explicit_initial_assignment_fails_before_search() {
    let (task, features) = fixture();
    let mut base = RunConfig::new(Arm::Depth, 1, 1, 17);
    base.latent_dim = 1;
    let mut config = Stage1RunConfig::from_stage0(base);
    config.initial_assignment = Some(vec![0, 2]);

    let result = run(&task, &features, config, &mut NoopPolicy);

    assert!(matches!(result, Err(SearchError::InvalidConfig(_))));
}
