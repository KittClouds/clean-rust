use super::*;
use phoenix_types::{
    AttachToEpisodeAction, GraphDecisionAction, GraphDecisionActionKind, GraphDecisionRewardSignal,
    GraphDecisionRewardVector, LinkEvidenceAction, RepairGraphRegionAction,
    GRAPH_DECISION_REWARD_SCHEMA_VERSION,
};

fn digest(byte: char) -> String {
    format!("b3-{}", byte.to_string().repeat(64))
}

fn observed(
    score_micros: i32,
    observed_at: i64,
    evidence: &[phoenix_types::GraphDecisionEvidenceRef],
) -> GraphDecisionRewardSignal {
    GraphDecisionRewardSignal::Observed {
        score_micros,
        observed_at,
        evidence: evidence.to_vec(),
    }
}

fn rewards(
    decision_id: &str,
    score_micros: i32,
    observed_at: i64,
    evidence: &[phoenix_types::GraphDecisionEvidenceRef],
) -> GraphDecisionRewardVector {
    let signal = || observed(score_micros, observed_at, evidence);
    GraphDecisionRewardVector {
        schema_version: GRAPH_DECISION_REWARD_SCHEMA_VERSION,
        decision_id: decision_id.into(),
        evidence_support: signal(),
        temporal_consistency: signal(),
        canonical_identity_preservation: signal(),
        contradiction_reduction: signal(),
        minimal_edit_cost: signal(),
        human_acceptance: signal(),
        future_stability: signal(),
        abstention_correctness: signal(),
    }
}

fn constraint(
    evaluated_at: i64,
    violations: Vec<CounterfactualHardConstraintViolation>,
) -> CounterfactualHardConstraintResult {
    certify_counterfactual_constraint_result(CounterfactualHardConstraintResult {
        schema_version: phoenix_types::GRAPH_DECISION_HARD_CONSTRAINT_SCHEMA_VERSION,
        policy_id: "phoenix-hard-constraints-v1".into(),
        evaluated_at,
        passed: violations.is_empty(),
        violations,
        receipt_id: "pending".into(),
    })
    .expect("certify hard-constraint receipt")
}

fn outcome(
    role: CounterfactualCandidateRole,
    action: GraphDecisionAction,
    reward: GraphDecisionRewardVector,
    outcome_available_at: i64,
    violations: Vec<CounterfactualHardConstraintViolation>,
) -> CounterfactualCandidateOutcome {
    CounterfactualCandidateOutcome {
        role,
        action_identity: graph_decision_candidate_identity(&action).expect("candidate identity"),
        action,
        reward_vector: reward,
        hard_constraints: constraint(outcome_available_at, violations),
        outcome_authority_id: "counterfactual-tribunal".into(),
        outcome_available_at,
        outcome_used_as_feature: false,
    }
}

fn group_inputs(tables: &FrozenDecisionTrajectoryTables) -> Vec<CounterfactualCandidateGroupInput> {
    tables
        .decisions
        .iter()
        .map(|record| {
            let selected = &tables.selected_actions[record.selected_label_ordinal as usize];
            let recorded = tables.candidate_actions[selected.selected_candidate_ordinal as usize]
                .action
                .clone();
            let source_candidates = &tables.candidate_actions[record.candidate_actions.offset
                as usize
                ..record.candidate_actions.end().unwrap() as usize];
            let hard = source_candidates
                .iter()
                .find(|row| matches!(row.action, GraphDecisionAction::CreateEpisode(_)))
                .expect("create candidate")
                .action
                .clone();
            let abstain = source_candidates
                .iter()
                .find(|row| matches!(row.action, GraphDecisionAction::Abstain(_)))
                .expect("abstain candidate")
                .action
                .clone();
            let header = recorded.header().clone();
            let evidence = recorded.evidence().to_vec();
            let minimal = GraphDecisionAction::RepairGraphRegion(RepairGraphRegionAction {
                header: header.clone(),
                region_id: format!("minimal-region-{}", record.decision_id).into(),
                repair_delta_id: format!("minimal-delta-{}", record.decision_id).into(),
                evidence: evidence.iter().cloned().collect(),
            });
            let aggressive = GraphDecisionAction::RepairGraphRegion(RepairGraphRegionAction {
                header: header.clone(),
                region_id: format!("aggressive-region-{}", record.decision_id).into(),
                repair_delta_id: format!("aggressive-delta-{}", record.decision_id).into(),
                evidence: evidence.iter().cloned().collect(),
            });
            let evidence_rich = GraphDecisionAction::LinkEvidence(LinkEvidenceAction {
                header: header.clone(),
                claim_id: format!("claim-{}", record.decision_id).into(),
                evidence: evidence.iter().cloned().collect(),
            });
            let temporal_invalid = GraphDecisionAction::AttachToEpisode(AttachToEpisodeAction {
                header,
                event_id: format!("event-{}", record.decision_id).into(),
                episode_id: format!("future-episode-{}", record.decision_id).into(),
                candidate_set_id: format!("future-set-{}", record.decision_id).into(),
                evidence: evidence.iter().cloned().collect(),
            });
            let observed_at = record.observation_cutoff + 10;
            let alternative_reward =
                |score| rewards(record.decision_id.as_str(), score, observed_at, &evidence);
            CounterfactualCandidateGroupInput {
                decision_id: record.decision_id.clone(),
                behavior_policy_id: "decision-policy-v1".into(),
                candidates: vec![
                    outcome(
                        CounterfactualCandidateRole::RecordedAction,
                        recorded,
                        tables.rewards[record.reward_ordinal as usize].clone(),
                        record.observation_cutoff,
                        Vec::new(),
                    ),
                    outcome(
                        CounterfactualCandidateRole::HardPlausibleAlternative,
                        hard,
                        alternative_reward(90_000),
                        observed_at,
                        Vec::new(),
                    ),
                    outcome(
                        CounterfactualCandidateRole::SafeAbstention,
                        abstain,
                        alternative_reward(80_000),
                        observed_at,
                        Vec::new(),
                    ),
                    outcome(
                        CounterfactualCandidateRole::MinimalRepair,
                        minimal,
                        alternative_reward(70_000),
                        observed_at,
                        Vec::new(),
                    ),
                    outcome(
                        CounterfactualCandidateRole::AggressiveRepair,
                        aggressive,
                        alternative_reward(60_000),
                        observed_at,
                        Vec::new(),
                    ),
                    outcome(
                        CounterfactualCandidateRole::EvidenceRichAlternative,
                        evidence_rich,
                        alternative_reward(50_000),
                        observed_at,
                        Vec::new(),
                    ),
                    outcome(
                        CounterfactualCandidateRole::TemporallyAttractiveInvalidAlternative,
                        temporal_invalid,
                        alternative_reward(-100_000),
                        observed_at,
                        vec![CounterfactualHardConstraintViolation::FutureInformation],
                    ),
                ],
            }
        })
        .collect()
}

fn frozen_counterfactual_fixture() -> (tempfile::TempDir, FrozenCounterfactualCandidateGroups) {
    let (root, manifest, tables) = super::decision_evaluation_tests::frozen_fixture();
    let snapshot = freeze_counterfactual_candidate_groups(
        manifest.dataset_id,
        &tables,
        1_000,
        group_inputs(&tables),
    )
    .expect("freeze counterfactual groups");
    (root, snapshot)
}

fn native_receipts(
    tables: &FrozenDecisionTrajectoryTables,
) -> (
    Vec<phoenix_types::NativeDecisionReceipt>,
    Vec<phoenix_types::NativeDecisionOutcomeReceipt>,
) {
    let mut decisions = Vec::with_capacity(tables.decisions.len());
    let mut outcomes = Vec::with_capacity(tables.decisions.len() * 7);
    for (record, input) in tables.decisions.iter().zip(group_inputs(tables)) {
        let state = &tables.states[record.state_ordinal as usize];
        let native_candidates = input
            .candidates
            .iter()
            .map(|candidate| phoenix_types::NativeDecisionCandidateReceipt {
                action_identity: candidate.action_identity.clone(),
                action: candidate.action.clone(),
                disposition: match candidate.role {
                    CounterfactualCandidateRole::RecordedAction => {
                        phoenix_types::NativeDecisionCandidateDisposition::Chosen
                    }
                    CounterfactualCandidateRole::TemporallyAttractiveInvalidAlternative => {
                        phoenix_types::NativeDecisionCandidateDisposition::Rejected
                    }
                    _ => phoenix_types::NativeDecisionCandidateDisposition::Unselected,
                },
                counterfactual_role: Some(native_role(candidate.role)),
                source_labels: vec!["frozen-grammar-candidate".into()],
            })
            .collect::<Vec<_>>();
        let authority = native_candidates[0].action.header().authority.clone();
        let decision =
            phoenix_types::certify_native_decision_receipt(phoenix_types::NativeDecisionReceipt {
                schema_version: phoenix_types::NATIVE_DECISION_RECEIPT_SCHEMA_VERSION,
                receipt_id: "pending".into(),
                decision_id: record.decision_id.clone(),
                task_family: phoenix_types::NativeDecisionTaskFamily::CanonicalEpisodeAssignment,
                scope_key: "workspace:hub".into(),
                lineage_ids: vec![format!("lineage-{}", record.decision_id).into()],
                observed_at: record.observation_cutoff,
                label_available_at: record.observation_cutoff,
                pre_state_snapshot_id: state.pre_state_snapshot_id.clone(),
                candidate_set_id: "pending".into(),
                generator_id: "frozen-grammar-generator".into(),
                generator_version: "1".into(),
                generator_input_id: digest('8').into(),
                invalid_candidates_rejected: 0,
                generation_latency_ns: 1,
                allocation_volume_bytes: 0,
                candidates: native_candidates,
                chosen_candidate_ordinal: 0,
                authority,
                authority_class: phoenix_types::NativeDecisionAuthorityClass::OperatorPreference,
                evidence_anchors: input.candidates[0].action.evidence().to_vec(),
                bridge: phoenix_types::NativeDecisionAuthorityBridge {
                    source_authority_id: "desktop-runtime".into(),
                    research_authority_id: "native-graph-store".into(),
                    source_state_receipt_id: digest('9').into(),
                    bridged_at: record.observation_cutoff + 1,
                },
            })
            .expect("certify native decision receipt");
        for candidate in input.candidates {
            outcomes.push(
                phoenix_types::certify_native_decision_outcome_receipt(
                    phoenix_types::NativeDecisionOutcomeReceipt {
                        schema_version: phoenix_types::NATIVE_DECISION_OUTCOME_SCHEMA_VERSION,
                        receipt_id: "pending".into(),
                        decision_receipt_id: decision.receipt_id.clone(),
                        decision_id: decision.decision_id.clone(),
                        candidate_action_identity: candidate.action_identity,
                        operation: phoenix_types::NativeDecisionOutcomeOperation::Observe,
                        observed_at: candidate.outcome_available_at,
                        authority_class:
                            phoenix_types::NativeDecisionAuthorityClass::AuthoritativeGraphOutcome,
                        outcome_authority_id: candidate.outcome_authority_id,
                        reward_vector: Some(candidate.reward_vector),
                        hard_constraints: candidate.hard_constraints,
                        effect: Some(phoenix_types::NativeDecisionEffect::NoChange {
                            post_state_snapshot_id: state.post_state_snapshot_id.clone(),
                        }),
                        predecessor_outcome_receipt_id: None,
                        evidence_anchors: candidate.action.evidence().to_vec(),
                    },
                )
                .expect("certify native outcome receipt"),
            );
        }
        decisions.push(decision);
    }
    (decisions, outcomes)
}

const fn native_role(
    role: CounterfactualCandidateRole,
) -> phoenix_types::NativeDecisionCounterfactualRole {
    match role {
        CounterfactualCandidateRole::RecordedAction => {
            phoenix_types::NativeDecisionCounterfactualRole::RecordedAction
        }
        CounterfactualCandidateRole::HardPlausibleAlternative => {
            phoenix_types::NativeDecisionCounterfactualRole::HardPlausibleAlternative
        }
        CounterfactualCandidateRole::SafeAbstention => {
            phoenix_types::NativeDecisionCounterfactualRole::SafeAbstention
        }
        CounterfactualCandidateRole::MinimalRepair => {
            phoenix_types::NativeDecisionCounterfactualRole::MinimalRepair
        }
        CounterfactualCandidateRole::AggressiveRepair => {
            phoenix_types::NativeDecisionCounterfactualRole::AggressiveRepair
        }
        CounterfactualCandidateRole::EvidenceRichAlternative => {
            phoenix_types::NativeDecisionCounterfactualRole::EvidenceRichAlternative
        }
        CounterfactualCandidateRole::TemporallyAttractiveInvalidAlternative => {
            phoenix_types::NativeDecisionCounterfactualRole::TemporallyAttractiveInvalidAlternative
        }
    }
}

#[test]
fn seven_role_groups_bind_authoritative_outcomes_and_temporal_sentinel() {
    let (_root, snapshot) = frozen_counterfactual_fixture();
    assert!(snapshot.certificate.passes());
    assert_eq!(snapshot.groups.len(), 3);
    assert_eq!(snapshot.candidates.len(), 21);
    assert_eq!(snapshot.certificate.labels_after_observation, 18);
    assert_eq!(snapshot.certificate.outcomes_used_as_features, 0);
    for group in &snapshot.groups {
        let start = group.candidates.offset as usize;
        assert_eq!(
            snapshot.candidates[start..start + 7]
                .iter()
                .map(|row| row.role)
                .collect::<Vec<_>>(),
            CounterfactualCandidateRole::ALL
        );
    }
}

#[test]
fn pending_rewards_and_outcome_feature_leakage_fail_closed() {
    let (_root, manifest, tables) = super::decision_evaluation_tests::frozen_fixture();
    let mut inputs = group_inputs(&tables);
    inputs[0].candidates[1].reward_vector.future_stability = GraphDecisionRewardSignal::Pending;
    assert!(matches!(
        freeze_counterfactual_candidate_groups(manifest.dataset_id.clone(), &tables, 1_000, inputs),
        Err(CounterfactualCandidateGroupsError::InvalidInput(_))
    ));
    let mut inputs = group_inputs(&tables);
    inputs[0].candidates[1].outcome_used_as_feature = true;
    assert!(matches!(
        freeze_counterfactual_candidate_groups(manifest.dataset_id, &tables, 1_000, inputs),
        Err(CounterfactualCandidateGroupsError::InvalidInput(_))
    ));
}

#[test]
fn mmap_artifact_is_immutable_and_corruption_fails_before_decode() {
    let (root, snapshot) = frozen_counterfactual_fixture();
    let paths = CounterfactualCandidateGroupsBundle::write(root.path(), &snapshot)
        .expect("write counterfactual artifact");
    let mapped = CounterfactualCandidateGroupsMapped::open(&paths.manifest)
        .expect("open counterfactual artifact");
    assert_eq!(mapped.snapshot().expect("decode snapshot"), snapshot);
    assert!(matches!(
        CounterfactualCandidateGroupsBundle::write(root.path(), &snapshot),
        Err(CounterfactualCandidateGroupsError::ArtifactExists(_))
    ));
    drop(mapped);
    let mut bytes = std::fs::read(&paths.payload).expect("read payload");
    let midpoint = bytes.len() / 2;
    bytes[midpoint] ^= 1;
    std::fs::write(&paths.payload, bytes).expect("corrupt payload");
    assert!(matches!(
        CounterfactualCandidateGroupsMapped::open(&paths.manifest),
        Err(CounterfactualCandidateGroupsError::CorruptArtifact(_))
    ));
}

#[test]
fn authoritative_native_receipts_reproduce_the_exact_counterfactual_dataset() {
    let (_root, manifest, tables) = super::decision_evaluation_tests::frozen_fixture();
    let direct = freeze_counterfactual_candidate_groups(
        manifest.dataset_id.clone(),
        &tables,
        1_000,
        group_inputs(&tables),
    )
    .expect("freeze direct dataset");
    let (decisions, outcomes) = native_receipts(&tables);
    let bridged = freeze_counterfactual_groups_from_native_receipts(
        manifest.dataset_id,
        &tables,
        1_000,
        &decisions,
        &outcomes,
    )
    .expect("freeze dataset from native receipts");
    assert_eq!(bridged, direct);
}

fn promoted_workhorse() -> (
    NativeRgcnMultitaskIdentity,
    NativeRgcnMultitaskPromotionCertificate,
) {
    let gate = certify_native_rgcn_multitask_launch_gate(
        Some(digest('a').into()),
        NativeRgcnTaskHeadKind::ALL.len() as u32,
        true,
        100,
    )
    .expect("workhorse launch");
    let identity = certify_native_rgcn_multitask_identity(
        &gate,
        NativeRgcnMultitaskIdentity {
            schema_version: NATIVE_RGCN_MULTITASK_SCHEMA.into(),
            model_identity: "pending".into(),
            launch_gate_id: gate.gate_id.clone(),
            comparison_mode: NativeRgcnComparisonMode::SharedMultiTask,
            task_set: NativeRgcnTaskHeadKind::ALL.to_vec(),
            task_sampling_schedule: NativeRgcnTaskHeadKind::ALL
                .into_iter()
                .map(|task| NativeRgcnTaskSamplingStep {
                    task,
                    batches_per_cycle: 1,
                })
                .collect(),
            loss_reduction: NativeRgcnLossReduction::PerTaskMeanThenWeightedSum,
            loss_weights_micros: vec![166_667, 166_667, 166_667, 166_667, 166_666, 166_666],
            head_architectures: NativeRgcnTaskHeadKind::ALL
                .into_iter()
                .map(|task| NativeRgcnTaskHeadArchitecture {
                    task,
                    input_features: 16,
                    hidden_features: 0,
                    output_features: 1,
                    activation: "task-appropriate-logit".into(),
                })
                .collect(),
            feature_schema_id: NATIVE_RGCN_FEATURE_SCHEMA.into(),
            topology_identity: digest('b').into(),
            seed: 42,
            optimizer_identity: digest('c').into(),
            clipping_partition_identity: digest('d').into(),
            checkpoint_selection_rule: "aggregate validation without important regression".into(),
            encoder_width: 16,
            encoder_layers: 1,
            propagation_rule: "typed-normalized-sum+inverse+qualifier-incidence/relu/v1".into(),
        },
    )
    .expect("workhorse identity");
    let evidence = NativeRgcnTaskHeadKind::ALL
        .into_iter()
        .map(|task| NativeRgcnTaskPromotionEvidence {
            task,
            strongest_baseline_id: digest('e').into(),
            certified_seed_count: 3,
            beats_baseline: true,
            weights_reproduced: true,
            certificates_reproduced: true,
            cold_restart_passed: true,
            future_leakage_rejected: true,
            calibration_maintained: true,
            paired_query_improvement: true,
            epoch_allocation_bytes: 0,
            allocation_deviation_explanation: None,
            important_task_regression_basis_points: 0,
        })
        .collect();
    let promotion = certify_native_rgcn_multitask_promotion(&identity, 100, evidence)
        .expect("workhorse promotion");
    (identity, promotion)
}

fn metrics(offset: u32) -> SupervisedGraphActionPolicyMetrics {
    SupervisedGraphActionPolicyMetrics {
        filtered_mrr_micros: 800_000 + offset,
        hits_at_1_micros: 700_000 + offset,
        brier_micros: 100_000 - offset,
        log_loss_micros: 200_000 - offset,
        calibration_error_micros: 50_000 - offset,
        abstention_risk_micros: 40_000 - offset,
        abstention_coverage_basis_points: 8_000 + (offset / 1_000) as u16,
        mean_reward_micros: 100_000 + i64::from(offset),
        mean_regret_micros: 20_000 - u64::from(offset),
        hard_constraint_violations: u64::from(offset == 0),
        unsupported_action_count: u64::from(offset == 0),
        unnecessary_edit_cost_micros: 10_000 - u64::from(offset),
        future_stability_micros: 100_000 + i64::from(offset),
    }
}

#[test]
fn supervised_anchor_is_identity_complete_and_later_policies_cannot_regress() {
    let (_root, snapshot) = frozen_counterfactual_fixture();
    let (workhorse, promotion) = promoted_workhorse();
    let gate = certify_supervised_graph_action_launch(&snapshot, &workhorse, &promotion)
        .expect("authorize supervised policy");
    let identity = certify_supervised_graph_action_policy_identity(
        &gate,
        SupervisedGraphActionPolicyIdentity {
            schema_version: SUPERVISED_GRAPH_ACTION_POLICY_SCHEMA.into(),
            policy_identity: "pending".into(),
            launch_gate_id: gate.gate_id.clone(),
            counterfactual_dataset_id: snapshot.dataset_id,
            workhorse_model_identity: workhorse.model_identity,
            workhorse_promotion_certificate_id: promotion.certificate_id,
            evaluator_protocol_id: digest('f').into(),
            action_vocabulary: GraphDecisionActionKind::ALL.to_vec(),
            ranking_loss: SupervisedActionRankingLoss::RecordedActionGroupCrossEntropy,
            calibration: SupervisedActionCalibration::ValidationTemperatureScaling,
            abstention_label_policy_id: "safe-abstention-from-hard-constraints-v1".into(),
            seed: 9,
            optimizer_identity: digest('1').into(),
            clipping_partition_identity: digest('2').into(),
            batch_schedule_identity: digest('3').into(),
            checkpoint_selection_rule: "validation ranking then calibration and constraint gate"
                .into(),
        },
    )
    .expect("policy identity");
    let evidence = SupervisedGraphActionPolicyEvidence {
        evaluation_report_id: digest('4').into(),
        strongest_baseline_id: digest('5').into(),
        certified_seed_count: 3,
        policy_metrics: metrics(1_000),
        behavior_policy_metrics: metrics(0),
        beats_strongest_baseline: true,
        action_probabilities_calibrated: true,
        abstention_trained: true,
        paired_query_improvement: true,
        weights_reproduced: true,
        certificates_reproduced: true,
        cold_restart_passed: true,
        future_leakage_rejected: true,
    };
    let anchor = certify_supervised_graph_action_anchor(&identity, evidence)
        .expect("promote supervised anchor");
    certify_graph_action_policy_non_regression(&anchor, digest('6').into(), metrics(1_000))
        .expect("equal policy passes");
    let mut regressed = metrics(1_000);
    regressed.filtered_mrr_micros -= 1;
    assert!(matches!(
        certify_graph_action_policy_non_regression(&anchor, digest('7').into(), regressed),
        Err(CounterfactualCandidateGroupsError::InvalidInput(_))
    ));
}
