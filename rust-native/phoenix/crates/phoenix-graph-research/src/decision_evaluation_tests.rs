use super::*;
use phoenix_types::{
    GraphDecisionAction, GraphDecisionApproval, GraphDecisionAuthority, GraphDecisionAuthorityKind,
    GraphDecisionEvidenceRef, GraphDecisionHeader, GraphDecisionRewardSignal,
    GraphDecisionRewardVector, GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION,
    GRAPH_DECISION_REWARD_SCHEMA_VERSION,
};
use tempfile::tempdir;

const REWARD: i32 = 100_000;

fn state_id(kind: &str, index: usize) -> String {
    format!(
        "b3-{}",
        blake3::hash(format!("{kind}-{index}").as_bytes()).to_hex()
    )
}

fn authority(cutoff: i64) -> GraphDecisionAuthority {
    GraphDecisionAuthority {
        authority_id: "operator-tribunal".into(),
        kind: GraphDecisionAuthorityKind::Operator,
        policy_id: "decision-policy-v1".into(),
        issued_at: cutoff - 20,
    }
}

fn evidence(cutoff: i64) -> GraphDecisionEvidenceRef {
    GraphDecisionEvidenceRef {
        evidence_id: format!("evidence-{cutoff}").into(),
        authority_id: "source-ledger".into(),
        available_at: cutoff - 10,
    }
}

fn observed(cutoff: i64) -> GraphDecisionRewardSignal {
    GraphDecisionRewardSignal::Observed {
        score_micros: REWARD,
        observed_at: cutoff,
        evidence: vec![evidence(cutoff)],
    }
}

fn rewards(decision_id: &str, cutoff: i64) -> GraphDecisionRewardVector {
    GraphDecisionRewardVector {
        schema_version: GRAPH_DECISION_REWARD_SCHEMA_VERSION,
        decision_id: decision_id.into(),
        evidence_support: observed(cutoff),
        temporal_consistency: observed(cutoff),
        canonical_identity_preservation: observed(cutoff),
        contradiction_reduction: observed(cutoff),
        minimal_edit_cost: observed(cutoff),
        human_acceptance: observed(cutoff),
        future_stability: observed(cutoff),
        abstention_correctness: observed(cutoff),
    }
}

fn example(
    index: usize,
    cutoff: i64,
    split: GraphDecisionSplit,
) -> (
    GraphDecisionTrajectoryExample,
    CandidateGenerationPerformanceReceipt,
) {
    let request = EpisodeCandidateGenerationRequest {
        candidate_group_id: format!("group-{index}").into(),
        event_id: format!("event-{index}").into(),
        new_episode_id: format!("new-episode-{index}").into(),
        task_id: "canonical-episode-assignment-v1".into(),
        header: GraphDecisionHeader {
            schema_version: GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION,
            decision_id: format!("decision-{index}").into(),
            pre_state_id: state_id("pre", index).into(),
            decided_at: cutoff,
            authority: authority(cutoff),
            approval: None,
        },
        evidence: vec![evidence(cutoff)],
        episode_seeds: vec![EpisodeCandidateSeed {
            episode_id: format!("episode-{index}").into(),
            available_at: cutoff - 50,
            active: true,
            scope_compatible: true,
            temporally_plausible: true,
            same_entity: true,
            related_entity: true,
            difficult_near_neighbor: true,
        }],
    };
    let generated = generate_episode_assignment_candidates(&request).expect("candidates");
    let mut selected = generated
        .group
        .candidates
        .iter()
        .find(|candidate| matches!(candidate.action, GraphDecisionAction::AttachToEpisode(_)))
        .expect("attach candidate")
        .action
        .clone();
    if let GraphDecisionAction::AttachToEpisode(action) = &mut selected {
        action.header.approval = Some(GraphDecisionApproval {
            approval_id: format!("approval-{index}").into(),
            approver_id: "operator-tribunal".into(),
            approved_at: cutoff - 1,
        });
    }
    let decision_id = format!("decision-{index}");
    (
        GraphDecisionTrajectoryExample {
            decision_id: decision_id.as_str().into(),
            observation_cutoff: cutoff,
            pre_state_snapshot_id: state_id("pre", index).into(),
            candidate_group: generated.group,
            selected_action: selected,
            evidence_references: vec![evidence(cutoff)],
            delta: GraphDecisionDeltaReference {
                before_delta_id: format!("before-{index}").into(),
                after_delta_id: format!("after-{index}").into(),
            },
            post_state_snapshot_id: state_id("post", index).into(),
            reward_vector: rewards(&decision_id, cutoff),
            authority: authority(cutoff),
            split,
            provenance: GraphDecisionProvenance {
                decision_fingerprint: format!("fingerprint-{index}").into(),
                source_receipt_ids: vec![format!("receipt-{index}").into()],
                label_authority_id: "operator-tribunal".into(),
                label_available_at: cutoff,
                leakage_witness: GraphDecisionLeakageWitness {
                    pre_state_max_fact_available_at: cutoff,
                    post_decision_edges_in_pre_state: 0,
                    future_episode_memberships_in_features: 0,
                    validation_test_facts_in_training_topology: 0,
                    outcome_fields_used_as_inputs: 0,
                    candidate_generation_used_held_out_label: false,
                },
            },
        },
        generated.performance,
    )
}

pub(super) fn frozen_fixture() -> (
    tempfile::TempDir,
    FrozenGraphDecisionTrajectoryManifest,
    FrozenDecisionTrajectoryTables,
) {
    let root = tempdir().expect("temporary artifact root");
    let rows = [
        example(1, 100, GraphDecisionSplit::Train),
        example(2, 200, GraphDecisionSplit::Validation),
        example(3, 300, GraphDecisionSplit::Test),
    ];
    let (examples, performance) = rows.into_iter().unzip();
    let paths = FrozenGraphDecisionTrajectoryBundle::write(examples, performance, root.path())
        .expect("freeze decision trajectories");
    let mapped =
        FrozenGraphDecisionTrajectoryMapped::open(&paths.manifest).expect("open trajectories");
    let manifest = mapped.manifest().clone();
    let tables = mapped.tables().expect("decode tables");
    (root, manifest, tables)
}

fn protocol(
    dataset_id: &str,
    family: NativeDecisionTaskFamily,
) -> NativeDecisionEvaluationProtocol {
    certify_native_decision_evaluation_protocol(NativeDecisionEvaluationProtocol {
        schema_version: NATIVE_DECISION_EVALUATION_SCHEMA.into(),
        protocol_id: "pending".into(),
        dataset_id: dataset_id.into(),
        task_family: family,
        partition: GraphDecisionSplit::Validation,
        calibration_bins: 10,
        recall_at_k: 2,
        ndcg_at_k: 2,
        risk_coverage_basis_points: vec![5_000, 10_000],
        tie_policy: NATIVE_DECISION_TIE_POLICY.into(),
        slice_policy_id: NATIVE_DECISION_SLICE_POLICY.into(),
        reward_scalarization: (family == NativeDecisionTaskFamily::Policy).then_some(
            PolicyRewardScalarization {
                policy_id: "pending".into(),
                weights_micros: [125_000; 8],
                pending_signal_policy: "fail_closed".into(),
            },
        ),
    })
    .expect("certify protocol")
}

fn inputs(
    tables: &FrozenDecisionTrajectoryTables,
    model_id: &str,
) -> Vec<NativeDecisionEvaluationInput> {
    tables
        .decisions
        .iter()
        .filter(|record| record.split == GraphDecisionSplit::Validation)
        .map(|record| {
            let selected_row = &tables.selected_actions[record.selected_label_ordinal as usize];
            let selected = (selected_row.selected_candidate_ordinal
                - record.candidate_actions.offset) as usize;
            let count = record.candidate_actions.length as usize;
            let mut scores = vec![0.0; count];
            let mut probabilities = vec![0.05; count];
            let mut relevant = vec![false; count];
            let mut reference = vec![1.0; count];
            scores[selected] = 2.0;
            probabilities[selected] = 0.9;
            relevant[selected] = true;
            reference[selected] = -1.0;
            let mut outcomes = vec![
                DecisionPolicyOutcome {
                    reward_micros: [0; 8],
                    hard_constraint_violations: 1,
                    supported: false,
                    edit_cost_micros: 20,
                    future_stability_micros: 0,
                    authority_id: "outcome-ledger".into(),
                };
                count
            ];
            outcomes[selected] = DecisionPolicyOutcome {
                reward_micros: [REWARD; 8],
                hard_constraint_violations: 0,
                supported: true,
                edit_cost_micros: 10,
                future_stability_micros: REWARD,
                authority_id: "outcome-ledger".into(),
            };
            let prediction = certify_native_decision_prediction(NativeDecisionPrediction {
                decision_id: record.decision_id.clone(),
                prediction_id: "pending".into(),
                producer_model_id: model_id.into(),
                scores,
                probabilities,
                eligible: vec![true; count],
                relevant,
                predicted_candidate_ordinal: Some(selected as u32),
                confidence: 0.9,
                reference_scores: Some(reference),
                policy_outcomes: Some(outcomes),
            })
            .expect("certify prediction");
            NativeDecisionEvaluationInput {
                decision_id: record.decision_id.clone(),
                prediction,
                slices: DecisionEvaluationSliceKeys {
                    temporal: "middle".into(),
                    relation_frequency: "frequent".into(),
                    entity_degree: "medium".into(),
                    evidence_count: "one".into(),
                    action_family: selected_row.action.kind(),
                },
            }
        })
        .collect()
}

#[test]
fn exact_tribunal_covers_ranking_classification_policy_and_all_slices() {
    let (_root, manifest, tables) = frozen_fixture();
    let ranking = evaluate_native_decisions(
        &tables,
        &protocol(&manifest.dataset_id, NativeDecisionTaskFamily::Ranking),
        &inputs(&tables, "ranker-v1"),
    )
    .expect("ranking tribunal");
    let rank = ranking.ranking.expect("ranking metrics");
    assert_eq!(rank.filtered_mean_reciprocal_rank, 1.0);
    assert_eq!(rank.hits_at_1, 1.0);
    assert_eq!(rank.recall_at_k, 1.0);
    assert_eq!(rank.ndcg_at_k, 1.0);
    assert!(rank.paired_mean_rank_delta.expect("paired delta") > 0.0);
    assert_eq!(ranking.slices.len(), 5);

    let classification = evaluate_native_decisions(
        &tables,
        &protocol(
            &manifest.dataset_id,
            NativeDecisionTaskFamily::Classification,
        ),
        &inputs(&tables, "classifier-v1"),
    )
    .expect("classification tribunal")
    .classification
    .expect("classification metrics");
    assert_eq!(classification.macro_f1, 1.0);
    assert_eq!(classification.abstained, 0);
    assert_eq!(classification.risk_coverage[1].risk, 0.0);

    let policy = evaluate_native_decisions(
        &tables,
        &protocol(&manifest.dataset_id, NativeDecisionTaskFamily::Policy),
        &inputs(&tables, "policy-v1"),
    )
    .expect("policy tribunal")
    .policy
    .expect("policy metrics");
    assert_eq!(policy.mean_relative_reward_micros, 0.0);
    assert_eq!(policy.mean_regret_against_recorded_micros, 0.0);
    assert_eq!(policy.hard_constraint_violations, 0);
    assert_eq!(policy.unsupported_action_rate, 0.0);
}

#[test]
fn reports_are_content_addressed_and_corruption_fails_closed() {
    let (root, manifest, tables) = frozen_fixture();
    let report = evaluate_native_decisions(
        &tables,
        &protocol(&manifest.dataset_id, NativeDecisionTaskFamily::Ranking),
        &inputs(&tables, "ranker-v1"),
    )
    .expect("report");
    let path =
        NativeDecisionEvaluationBundle::write_report(root.path(), &report).expect("write report");
    assert_eq!(
        NativeDecisionEvaluationBundle::open_report(&path)
            .expect("open report")
            .report_id,
        report.report_id
    );
    let mut bytes = std::fs::read(&path).expect("read report");
    let midpoint = bytes.len() / 2;
    bytes[midpoint] ^= 1;
    std::fs::write(&path, bytes).expect("corrupt report fixture");
    assert!(matches!(
        NativeDecisionEvaluationBundle::open_report(&path),
        Err(NativeDecisionEvaluationError::Json(_))
            | Err(NativeDecisionEvaluationError::CorruptArtifact(_))
    ));
}

#[test]
fn baseline_ladder_is_ordered_single_task_and_test_locked() {
    let (_root, manifest, tables) = frozen_fixture();
    let protocol = protocol(&manifest.dataset_id, NativeDecisionTaskFamily::Ranking);
    let submissions = DecisionBaselineRung::REQUIRED
        .into_iter()
        .enumerate()
        .map(|(index, rung)| {
            let model_id = format!("baseline-{index}");
            DecisionBaselineSubmission {
                rung,
                model_id: model_id.as_str().into(),
                feature_manifest_id: format!("feature-manifest-{index}").into(),
                enabled_feature_families: rung.enabled_features(),
                inputs: inputs(&tables, &model_id),
            }
        })
        .collect();
    let ladder = run_native_decision_baseline_ladder(&tables, &protocol, submissions)
        .expect("baseline ladder");
    assert!(ladder.single_task_only);
    assert!(!ladder.test_accessed);
    assert_eq!(ladder.rungs.len(), 9);
    assert_eq!(
        ladder.rungs[8].isolated_feature,
        DecisionFeatureFamily::RevisionStructure
    );

    let mut test_protocol = protocol.clone();
    test_protocol.partition = GraphDecisionSplit::Test;
    test_protocol.protocol_id = "pending".into();
    test_protocol =
        certify_native_decision_evaluation_protocol(test_protocol).expect("test protocol identity");
    assert!(matches!(
        run_native_decision_baseline_ladder(&tables, &test_protocol, Vec::new()),
        Err(NativeDecisionEvaluationError::TestLocked)
    ));
}
