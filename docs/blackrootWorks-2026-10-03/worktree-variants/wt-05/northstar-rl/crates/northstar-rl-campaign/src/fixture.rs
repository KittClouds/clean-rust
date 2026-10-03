use northstar_rl_core::{Digest, RlEnvSpec, identified, identity};

use crate::{
    CAMPAIGN_RUN_RECEIPT_V1, CAMPAIGN_SPEC_V1, CampaignReceipt, CampaignRunReceipt,
    CampaignRunStatus, CampaignSpec, ChronologicalPartitionPlan, EVALUATION_SPEC_V1,
    EXPERIMENT_SPEC_V1, EpisodePartitionInput, EvaluationMetricRule, EvaluationSpec,
    ExperimentSpec, FeatureFitRow, InferenceSignature, LEARNER_SPEC_V1, LearnerAlgorithm,
    LearnerSpec, POLICY_ARTIFACT_V1, PartitionRole, PartitionTape, PolicyArchitecture,
    PolicyArtifact, PolicyMaterializationState, Result, StressVariant, TransformState,
    build_chronological_group_partition, campaign_implementation_hashes, fit_standard_score,
    role_episode_ids,
};

#[derive(Clone, Debug)]
pub struct CampaignFixture {
    pub partition: PartitionTape,
    pub transform: TransformState,
    pub learner: LearnerSpec,
    pub evaluation: EvaluationSpec,
    pub experiment: ExperimentSpec,
    pub campaign: CampaignSpec,
    pub planned_runs: Vec<CampaignRunReceipt>,
    pub campaign_receipt: CampaignReceipt,
    pub policy_contract: PolicyArtifact,
    pub inputs: Vec<EpisodePartitionInput>,
}

pub fn build_campaign_fixture(
    env: &RlEnvSpec,
    observation_dictionary_hash: Digest,
) -> Result<CampaignFixture> {
    let source_episode_tape_id = Digest::hash(
        b"northstar-campaign-fixture-episode-tape-v1",
        b"12 chronological session episodes",
    );
    let inputs = (0..12_u32)
        .map(|index| {
            let start = 1_800_000_000_000_000_000_i64 + index as i64 * 100_000_000_000;
            EpisodePartitionInput {
                episode_id: Digest::hash(
                    b"northstar-campaign-fixture-episode-v1",
                    &index.to_le_bytes(),
                ),
                instrument_id: 3,
                group_id: format!("session-{index:02}"),
                start_time_ns: start,
                end_time_ns: start + 90_000_000_000,
            }
        })
        .collect::<Vec<_>>();
    let partition = build_chronological_group_partition(
        source_episode_tape_id,
        &inputs,
        ChronologicalPartitionPlan {
            train_groups: 6,
            development_groups: 3,
            embargo_ns: 2_000_000_000,
        },
    )?;
    let feature_ids = vec![
        "market.simple_return.v1".into(),
        "market.candle_range.v1".into(),
        "clock.session_progress.v1".into(),
    ];
    let fit_rows = inputs
        .iter()
        .flat_map(|episode| {
            (0..4_u32).map(move |row| FeatureFitRow {
                episode_id: episode.episode_id,
                values: vec![
                    episode.start_time_ns.rem_euclid(17) as f64 + row as f64,
                    2.0 + row as f64 * 0.5,
                    row as f64 / 3.0,
                ],
            })
        })
        .collect::<Vec<_>>();
    let transform = fit_standard_score(
        env.feature_tape_id,
        &feature_ids,
        &partition,
        &fit_rows,
        Some((-5.0, 5.0)),
    )?;
    let learner = identified(
        b"northstar-learner-spec-v1",
        LearnerSpec {
            schema_version: LEARNER_SPEC_V1.into(),
            learner_spec_id: Digest::ZERO,
            algorithm: LearnerAlgorithm::FutureSb3Ppo,
            policy_architecture: PolicyArchitecture {
                policy_class: "MlpPolicy".into(),
                hidden_layers: vec![64, 64],
                activation: "tanh".into(),
                shared_backbone: true,
            },
            optimizer: "Adam".into(),
            learning_rate: 0.0003,
            rollout_length: 2048,
            batch_size: 64,
            gamma: 0.99,
            gae_lambda: 0.95,
            entropy_coefficient: 0.0,
            value_coefficient: 0.5,
            max_gradient_norm: 0.5,
            seed: 42,
            executor_name: "stable_baselines3".into(),
            executor_version: "2.9.0".into(),
            implementation_identity: Digest::hash(
                b"future-sb3-executor-identity-v1",
                b"stable_baselines3==2.9.0;PPO;not-executed",
            ),
            execution_permission: "PROHIBITED_UNTIL_DEGEN_RL_01".into(),
        },
        |value, digest| value.learner_spec_id = digest,
    )?;
    let evaluation_episode_ids = role_episode_ids(&partition, PartitionRole::Evaluation);
    let evaluation = identified(
        b"northstar-evaluation-spec-v1",
        EvaluationSpec {
            schema_version: EVALUATION_SPEC_V1.into(),
            evaluation_spec_id: Digest::ZERO,
            partition_tape_id: partition.partition_tape_id,
            evaluation_episode_ids,
            deterministic_policy_inference: true,
            policy_selection_uses_evaluation: false,
            metrics: [
                ("normalized_return_sum", "MAXIMIZE", "SUM"),
                ("gross_mark_to_market_sum", "MAXIMIZE", "SUM"),
                ("turnover_sum", "MINIMIZE", "SUM"),
                ("total_friction_sum", "MINIMIZE", "SUM"),
                ("max_drawdown", "MINIMIZE", "MAX"),
                ("mean_absolute_exposure", "DIAGNOSTIC", "MEAN"),
                ("step_count", "DIAGNOSTIC", "SUM"),
                ("terminal_count", "REQUIRE_EXACT", "SUM"),
            ]
            .into_iter()
            .map(|(metric_id, direction, aggregation)| EvaluationMetricRule {
                metric_id: metric_id.into(),
                direction: direction.into(),
                aggregation: aggregation.into(),
                missingness: "FAIL_CLOSED".into(),
            })
            .collect(),
            stress_variants: vec![
                StressVariant {
                    stress_id: "CANONICAL_DETERMINISTIC".into(),
                    execution_calibration_id: env.execution_calibration_id,
                    parameter_overrides: Vec::new(),
                },
                StressVariant {
                    stress_id: "DOUBLE_FRICTION_DECLARATION_ONLY".into(),
                    execution_calibration_id: env.execution_calibration_id,
                    parameter_overrides: vec![("friction_multiplier".into(), "2.0".into())],
                },
            ],
            aggregation_order: vec!["episode".into(), "seed".into(), "campaign".into()],
            implementation_hash: Digest::hash(
                b"northstar-evaluator-implementation-v1",
                include_bytes!("evaluate.rs"),
            ),
        },
        |value, digest| value.evaluation_spec_id = digest,
    )?;
    let experiment = identified(
        b"northstar-experiment-spec-v1",
        ExperimentSpec {
            schema_version: EXPERIMENT_SPEC_V1.into(),
            experiment_id: Digest::ZERO,
            environment_id: env.environment_id,
            feature_tape_id: env.feature_tape_id,
            observation_spec_id: env.observation_spec_id,
            partition_tape_id: partition.partition_tape_id,
            transform_state_id: transform.transform_state_id,
            learner_spec_id: learner.learner_spec_id,
            evaluation_spec_id: evaluation.evaluation_spec_id,
            root_seed: 42,
            immutable_input_hashes: vec![
                env.environment_id,
                env.feature_tape_id,
                partition.partition_tape_id,
                transform.transform_state_id,
            ],
            implementation_hashes: campaign_implementation_hashes(),
        },
        |value, digest| value.experiment_id = digest,
    )?;
    let campaign = identified(
        b"northstar-campaign-spec-v1",
        CampaignSpec {
            schema_version: CAMPAIGN_SPEC_V1.into(),
            campaign_id: Digest::ZERO,
            experiment_id: experiment.experiment_id,
            partition_tape_id: partition.partition_tape_id,
            run_seeds: vec![101, 202, 303],
            run_budget_steps: 10_000,
            variance_axes: vec!["LEARNER_SEED".into()],
            state: "SEALED_PRE_EXECUTION".into(),
        },
        |value, digest| value.campaign_id = digest,
    )?;
    let planned_runs = campaign
        .run_seeds
        .iter()
        .map(|&seed| {
            identified(
                b"northstar-campaign-run-receipt-v1",
                CampaignRunReceipt {
                    schema_version: CAMPAIGN_RUN_RECEIPT_V1.into(),
                    run_id: Digest::ZERO,
                    campaign_id: campaign.campaign_id,
                    experiment_id: experiment.experiment_id,
                    seed,
                    status: CampaignRunStatus::Planned,
                    learner_steps_executed: 0,
                    checkpoint_hashes: Vec::new(),
                    policy_artifact_id: None,
                    reason_code: "LEARNER_EXECUTION_PROHIBITED_FORGE_RL_02".into(),
                },
                |value, digest| value.run_id = digest,
            )
        })
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let campaign_receipt = identified(
        b"northstar-campaign-receipt-v1",
        CampaignReceipt {
            schema_version: "CAMPAIGN_RECEIPT_V1".into(),
            campaign_id: campaign.campaign_id,
            run_receipt_ids: planned_runs.iter().map(|run| run.run_id).collect(),
            learner_execution: "NOT_RUN".into(),
            receipt_id: Digest::ZERO,
        },
        |value, digest| value.receipt_id = digest,
    )?;
    let policy_contract = identified(
        b"northstar-policy-artifact-v1",
        PolicyArtifact {
            schema_version: POLICY_ARTIFACT_V1.into(),
            policy_artifact_id: Digest::ZERO,
            materialization_state: PolicyMaterializationState::ContractOnlyPreLearner,
            originating_experiment_id: experiment.experiment_id,
            weights_hash: None,
            observation_dictionary_hash,
            action_spec_id: env.action_spec_id,
            transform_state_id: transform.transform_state_id,
            environment_id: env.environment_id,
            executor_name: learner.executor_name.clone(),
            executor_version: learner.executor_version.clone(),
            inference_signature: InferenceSignature {
                input_dtype: "float32".into(),
                input_shape: vec![6],
                output_dtype: "float32".into(),
                output_shape: vec![1],
                deterministic: true,
            },
            onnx_export_identity: None,
        },
        |value, digest| value.policy_artifact_id = digest,
    )?;
    Ok(CampaignFixture {
        partition,
        transform,
        learner,
        evaluation,
        experiment,
        campaign,
        planned_runs,
        campaign_receipt,
        policy_contract,
        inputs,
    })
}

pub fn validate_campaign_fixture(fixture: &CampaignFixture) -> Result<()> {
    crate::validate_partition_identity(&fixture.partition)?;
    if fixture.experiment.partition_tape_id != fixture.partition.partition_tape_id
        || fixture.campaign.partition_tape_id != fixture.partition.partition_tape_id
        || fixture.transform.partition_tape_id != fixture.partition.partition_tape_id
        || fixture
            .planned_runs
            .iter()
            .any(|run| run.learner_steps_executed != 0 || run.status != CampaignRunStatus::Planned)
        || fixture.policy_contract.weights_hash.is_some()
        || fixture.policy_contract.materialization_state
            != PolicyMaterializationState::ContractOnlyPreLearner
    {
        return Err(crate::Error::Contract(
            "campaign fixture authority binding failed".into(),
        ));
    }
    Ok(())
}

pub fn observation_dictionary_hash(entries: &impl serde::Serialize) -> Result<Digest> {
    Ok(identity(b"northstar-observation-dictionary-v1", entries)?)
}
