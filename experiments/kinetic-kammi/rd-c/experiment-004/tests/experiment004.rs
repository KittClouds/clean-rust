use std::{
    fs,
    time::{SystemTime, UNIX_EPOCH},
};

use rdc_experiment_001::{DecisionCompiler, Signal, State, standard_schema};
use rdc_experiment_004::{
    Choice, Policy, RunSpec,
    domain::{ObservationFeatures, proposal},
    episodes::{EpisodeClass, heldout_episodes},
    evaluation::heldout_labels,
    experiment_schema, plan_budgets,
    routing::{WitnessProposal, WitnessReason, evidence_witness},
    run_episode,
};

#[test]
fn public_frame_and_labels_are_separate_and_bank_is_fresh() {
    let episodes = heldout_episodes();
    let labels = heldout_labels(&episodes);
    assert_eq!(episodes.len(), 128);
    assert_eq!(labels.len(), episodes.len());
    assert_eq!(
        episodes[0].id,
        (rdc_experiment_004::episodes::HELDOUT_SEED as u32)
    );
    for (episode, label) in episodes.iter().zip(&labels) {
        assert_eq!(episode.id, label.episode_id);
        let observation = episode.observation(Signal::Approve);
        let decoded = ObservationFeatures::decode(&observation).unwrap();
        assert_eq!(decoded, episode.features);
        // The public schema records claims made by sources; the hidden truth is held in EvalLabel.
        assert_eq!(decoded.episode_id, label.episode_id);
        assert_eq!(
            rdc_experiment_004::hidden_label(decoded.goal, label.truth_revision),
            label.correct_action
        );
    }
    let mut changed_sources = episodes.clone();
    for episode in &mut changed_sources {
        episode.features.primary_action =
            Choice::ALL[(episode.features.primary_action as usize + 1) % 3];
        episode.features.audit_action =
            Choice::ALL[(episode.features.audit_action as usize + 2) % 3];
    }
    assert_eq!(heldout_labels(&changed_sources), labels);
}

#[test]
fn witness_flags_old_and_contract_inconsistent_shared_sources() {
    let episodes = heldout_episodes();
    let stale = episodes
        .iter()
        .find(|e| e.class == EpisodeClass::StaleSharedAgreement)
        .unwrap();
    let stale_observation = stale.observation(Signal::Approve);
    let stale_a = proposal(
        State::Deciding,
        &stale_observation,
        stale.features.primary_action,
        1,
        stale.features.primary_revision,
    );
    let stale_b = stale_a;
    assert_eq!(
        evidence_witness(stale_a, stale_b, stale.features),
        WitnessProposal::InspectEvidence {
            source_id: 1,
            reason: WitnessReason::SharedOldSource
        },
    );

    let misleading = episodes
        .iter()
        .find(|e| e.class == EpisodeClass::MisleadingFreshAgreement)
        .unwrap();
    let observation = misleading.observation(Signal::Approve);
    let a = proposal(
        State::Deciding,
        &observation,
        misleading.features.primary_action,
        1,
        misleading.features.primary_revision,
    );
    assert_eq!(
        evidence_witness(a, a, misleading.features),
        WitnessProposal::InspectEvidence {
            source_id: 1,
            reason: WitnessReason::SharedMisleadingSource
        },
    );
}

#[test]
fn all_policies_receive_exact_label_blind_budgets() {
    let episodes = heldout_episodes();
    let plans = plan_budgets(&episodes, &[16, 32, 64]);
    assert_eq!(plans.len(), Policy::ALL.len() * 3);
    for plan in &plans {
        assert_eq!(plan.selected_ids.len(), plan.budget);
        assert!(
            plan.selected_ids
                .iter()
                .all(|id| episodes.iter().any(|e| e.id == *id))
        );
    }
    for budget in [16, 32, 64] {
        for policy in Policy::ALL {
            assert_eq!(
                plans
                    .iter()
                    .find(|p| p.budget == budget && p.policy == policy)
                    .unwrap()
                    .selected_ids
                    .len(),
                budget
            );
        }
    }
}

#[test]
fn compiled_authority_run_replays_identically_with_zero_illegal_commits() {
    let episodes = heldout_episodes();
    let labels = heldout_labels(&episodes);
    let episode = *episodes
        .iter()
        .find(|e| e.class == EpisodeClass::StaleSharedAgreement)
        .unwrap();
    let label = *labels
        .iter()
        .find(|label| label.episode_id == episode.id)
        .unwrap();
    let schema = experiment_schema();
    let compiler = DecisionCompiler::compile(&schema).unwrap();
    let temp = std::env::temp_dir().join(format!(
        "rdc-e004-test-{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    fs::create_dir_all(&temp).unwrap();
    let result = run_episode(RunSpec {
        policy: Policy::Disagreement,
        budget: 1,
        escalated: true,
        episode,
        label,
        compiler: &compiler,
        schema: &schema,
        journal_root: &temp,
        task_salt: 0xE404,
    })
    .unwrap();
    assert!(result.replay_identity_ok);
    assert_eq!(result.illegal_commits, 0);
    assert_eq!(result.duplicate_actions, 0);
    assert_eq!(result.missing_actions, 0);
    assert_eq!(result.tool_calls, 2);
    assert_eq!(result.resolver_tokens, 0);
    assert_eq!(result.witness_source_id, Some(1));
    assert!(result.e2_journal.exists());
    fs::remove_dir_all(temp).unwrap();
}

#[test]
fn action_schema_keeps_three_legal_decision_choices() {
    let schema = experiment_schema();
    for action in [
        Choice::UsePrimary.action(),
        Choice::VerifyRecord.action(),
        Choice::RefreshSnapshot.action(),
    ] {
        assert!(schema.iter().any(|rule| rule.from == State::Deciding
            && rule.to == State::Acting
            && rule.action == action));
    }
    assert_eq!(standard_schema().len(), 9);
}
