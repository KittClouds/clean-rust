use std::collections::BTreeMap;

use northstar_rl_campaign::{
    CampaignRunStatus, FeatureFitRow, PartitionRole, PolicyMaterializationState, apply_transform,
    build_campaign_fixture, fit_standard_score, observation_dictionary_hash, role_episode_ids,
    validate_campaign_fixture, validate_partition_identity,
};
use northstar_rl_core::{Digest, materialize_lab};

fn fixture() -> (tempfile::TempDir, northstar_rl_campaign::CampaignFixture) {
    let directory = tempfile::tempdir().unwrap();
    let lab = materialize_lab(directory.path()).unwrap();
    let dictionary = observation_dictionary_hash(&lab.observation_dictionary).unwrap();
    let fixture = build_campaign_fixture(&lab.config.environment_spec, dictionary).unwrap();
    (directory, fixture)
}

#[test]
fn groups_are_atomic_and_roles_are_chronological() {
    let (_, fixture) = fixture();
    let mut group_roles = BTreeMap::new();
    for assignment in &fixture.partition.assignments {
        assert!(
            group_roles
                .insert(&assignment.group_id, assignment.role)
                .is_none()
        );
    }
    let ordinals = |role| {
        fixture
            .partition
            .assignments
            .iter()
            .filter(|a| a.role == role)
            .map(|a| a.chronological_ordinal)
            .collect::<Vec<_>>()
    };
    let train = ordinals(PartitionRole::Train);
    let development = ordinals(PartitionRole::Development);
    let evaluation = ordinals(PartitionRole::Evaluation);
    assert!(train.iter().max() < development.iter().min());
    assert!(development.iter().max() < evaluation.iter().min());
}

#[test]
fn sealed_partition_mutation_fails_identity_validation() {
    let (_, mut fixture) = fixture();
    validate_partition_identity(&fixture.partition).unwrap();
    fixture.partition.assignments[0].role = PartitionRole::Evaluation;
    assert!(validate_partition_identity(&fixture.partition).is_err());
}

#[test]
fn development_and_evaluation_values_cannot_change_transform_fit() {
    let (_, fixture) = fixture();
    let feature_ids = vec!["a".to_string(), "b".to_string()];
    let mut rows = fixture
        .inputs
        .iter()
        .map(|episode| FeatureFitRow {
            episode_id: episode.episode_id,
            values: vec![1.0, 2.0],
        })
        .collect::<Vec<_>>();
    let first = fit_standard_score(
        Digest::hash(b"feature-tape", b"one"),
        &feature_ids,
        &fixture.partition,
        &rows,
        Some((-3.0, 3.0)),
    )
    .unwrap();
    let train = role_episode_ids(&fixture.partition, PartitionRole::Train);
    for row in &mut rows {
        if !train.contains(&row.episode_id) {
            row.values = vec![1e12, -1e12];
        }
    }
    let second = fit_standard_score(
        Digest::hash(b"feature-tape", b"one"),
        &feature_ids,
        &fixture.partition,
        &rows,
        Some((-3.0, 3.0)),
    )
    .unwrap();
    assert_eq!(first, second);
    assert_eq!(
        apply_transform(&first, &[1.0, 2.0]).unwrap(),
        vec![0.0, 0.0]
    );
}

#[test]
fn campaign_is_planned_and_policy_has_no_weights() {
    let (_, fixture) = fixture();
    validate_campaign_fixture(&fixture).unwrap();
    assert!(
        fixture
            .planned_runs
            .iter()
            .all(|run| run.status == CampaignRunStatus::Planned && run.learner_steps_executed == 0)
    );
    assert_eq!(
        fixture.policy_contract.materialization_state,
        PolicyMaterializationState::ContractOnlyPreLearner
    );
    assert!(fixture.policy_contract.weights_hash.is_none());
    assert_eq!(fixture.campaign_receipt.learner_execution, "NOT_RUN");
}
