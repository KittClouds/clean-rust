use std::{
    fs,
    time::{SystemTime, UNIX_EPOCH},
};

use rdc_experiment_001::{
    Action, DecisionCompiler, Evidence, Proposal, Signal, State, standard_schema,
};
use rdc_experiment_002::{Authority, CompiledAuthority};
use rdc_experiment_003::{
    Choice, EpisodeClass, EscalationPolicy, experiment_schema, frozen_observer_pair,
    heldout_episodes, run_episode, workflow_correct_action,
};

#[test]
fn heldout_labels_are_contract_derived_and_cover_agreement_blindspots() {
    let episodes = heldout_episodes();
    assert_eq!(episodes.len(), 256);

    let mut disagreements = 0;
    let mut agreement_errors = 0;
    let mut disagreement_errors = 0;
    for episode in &episodes {
        assert_eq!(
            episode.correct_action,
            workflow_correct_action(episode.features.goal, episode.features.world_revision)
        );
        let (active, shadow) = frozen_observer_pair(&episode.observation(Signal::Approve)).unwrap();
        let active = Choice::from_action(active.action).unwrap();
        let shadow = Choice::from_action(shadow.action).unwrap();
        if active == shadow {
            agreement_errors += usize::from(active != episode.correct_action);
        } else {
            disagreements += 1;
            disagreement_errors += usize::from(active != episode.correct_action);
        }
    }
    assert_eq!(disagreements, 108);
    assert_eq!(agreement_errors, 36);
    assert_eq!(disagreement_errors, 80);
}

#[test]
fn all_three_domain_actions_are_legal_under_the_e002_compiled_authority() {
    let schema = experiment_schema();
    let compiler = DecisionCompiler::compile(&schema).unwrap();
    for choice in Choice::ALL {
        let mut authority = CompiledAuthority::from_compiler(compiler.clone());
        let evidence = Evidence {
            code: 0xE303,
            digest: [7; 16],
        };
        let start = authority.apply(Proposal::new(
            State::Idle,
            State::Observing,
            Action::Observe,
        ));
        assert!(start.accepted());
        let observed = authority.apply(
            Proposal::new(State::Observing, State::Deciding, Action::Decide)
                .with_evidence(evidence),
        );
        assert!(observed.accepted());
        let selected = authority.apply(
            Proposal::new(State::Deciding, State::Acting, choice.action())
                .with_evidence(evidence)
                .with_confidence(520),
        );
        assert!(selected.accepted(), "{} was rejected", choice.label());
        assert_eq!(selected.after, State::Acting);
    }
}

#[test]
fn disagreement_lane_routes_a_stale_proposal_then_replays_the_task() {
    let episode = heldout_episodes()
        .into_iter()
        .find(|episode| episode.class == EpisodeClass::StalePrimaryDisagreement)
        .unwrap();
    let schema = experiment_schema();
    let compiler = DecisionCompiler::compile(&schema).unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let root = std::env::temp_dir().join(format!("rdc003-smoke-{}-{now}", std::process::id()));
    fs::create_dir_all(&root).unwrap();
    let result = run_episode(
        EscalationPolicy::Disagreement,
        false,
        episode,
        &compiler,
        &schema,
        &root,
        0x5244_4303_0000_0000,
    )
    .unwrap();
    assert_eq!(
        result.raw_active,
        Choice::ALL[(episode.correct_action as usize + 1) % 3]
    );
    assert_ne!(result.raw_active, episode.correct_action);
    assert!(result.action_disagreement);
    assert!(result.escalated);
    assert_eq!(result.resolver_action, Some(episode.correct_action));
    assert!(result.task_completed);
    assert_eq!(result.illegal_commits, 0);
    assert!(result.replay_identity_ok);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn original_e002_standard_schema_remains_a_subset_of_the_experiment_schema() {
    let experiment = experiment_schema();
    for spec in standard_schema() {
        if spec.from == State::Deciding
            && spec.to == State::Acting
            && spec.action == Action::Execute
        {
            assert!(experiment.iter().any(|candidate| {
                candidate.from == spec.from
                    && candidate.to == spec.to
                    && candidate.action == spec.action
            }));
        } else {
            assert!(experiment.iter().any(|candidate| {
                candidate.from == spec.from
                    && candidate.to == spec.to
                    && candidate.action == spec.action
                    && candidate.guard == spec.guard
            }));
        }
    }
}
