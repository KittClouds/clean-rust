use super::*;

fn authority_rows(tables: &FrozenDecisionTrajectoryTables) -> Vec<NativeRgcnFeatureAuthorityRow> {
    let mut rows = Vec::with_capacity(tables.candidate_actions.len());
    for decision in &tables.decisions {
        let state = &tables.states[decision.state_ordinal as usize];
        for local in 0..decision.candidate_actions.length as usize {
            let candidate_ordinal = decision.candidate_actions.offset as usize + local;
            let candidate = &tables.candidate_actions[candidate_ordinal];
            let value = candidate_ordinal as u32 + 1;
            rows.push(NativeRgcnFeatureAuthorityRow {
                decision_id: decision.decision_id.clone(),
                candidate_action_identity: candidate.action_identity.clone(),
                split: decision.split,
                observation_cutoff: decision.observation_cutoff,
                pre_state_snapshot_id: state.pre_state_snapshot_id.clone(),
                topology_identity: format!("b3-topology-{}", decision.decision_id).into(),
                topology_fit_split: GraphDecisionSplit::Train,
                topology_fit_through: 90,
                authority_id: "native-graph-truth".into(),
                source_receipt_ids: vec![format!("receipt-{candidate_ordinal}").into()],
                available_through: decision.observation_cutoff,
                source_node: value,
                target_node: value + 100,
                relation_type: value % 3,
                raw: NativeRgcnRawFeatureAuthority {
                    typed_in_degree: value,
                    typed_out_degree: value + 1,
                    typed_neighbor_overlap_basis_points: (value * 100) as u16,
                    qualifier_incidence_count: value + 2,
                    qualifier_role_diversity: value + 1,
                    latest_visible_fact_at: Some(decision.observation_cutoff - 10),
                    prior_visible_fact_at: Some(decision.observation_cutoff - 20),
                    evidence_count: value + 4,
                    evidence_source_diversity: value + 3,
                    revision_depth: value + 6,
                    visible_episode_memberships: value + 7,
                    prior_accepted_proposals: value + 8,
                    prior_rejected_proposals: value + 9,
                    discrepancy_state: NativeDiscrepancyState::TemporalRevision,
                    authority_class: (value % 15) as u8,
                    confidence_class: ((value + 1) % 15) as u8,
                },
            });
        }
    }
    rows
}

#[test]
fn derives_exact_train_visible_sixteen_wide_contract() {
    let (_root, manifest, tables) = super::decision_evaluation_tests::frozen_fixture();
    let authority = authority_rows(&tables);
    let first = derive_native_rgcn_features(
        &tables,
        manifest.dataset_id.clone(),
        &authority,
        NativeRgcnFeatureDerivationPolicy::real(NativeRgcnFeatureFamily::TypedAdjacency),
    )
    .expect("derive native features");
    let second = derive_native_rgcn_features(
        &tables,
        manifest.dataset_id,
        &authority,
        NativeRgcnFeatureDerivationPolicy::real(NativeRgcnFeatureFamily::TypedAdjacency),
    )
    .expect("replay native features");
    assert_eq!(first, second);
    validate_native_rgcn_feature_snapshot(&first).expect("validate snapshot identity");
    assert_eq!(first.feature_contract.len(), NATIVE_RGCN_FEATURE_DIM);
    assert_eq!(first.rows.len(), tables.candidate_actions.len());
    assert!(first.audit.passes());
    assert!(first
        .feature_contract
        .iter()
        .all(|column| column.label_free && column.fixed_scale == 1_000));
    assert_eq!(first.rows[0].features[0], 1);
    assert_eq!(first.rows[0].features[1], 2);
    assert_eq!(first.rows[0].features[2], 10);
    assert_eq!(
        first.rows[0].features_f32()[0].to_bits(),
        0.001_f32.to_bits()
    );
    let mut forged = first;
    forged.rows[0].features[0] += 1;
    assert!(matches!(
        validate_native_rgcn_feature_snapshot(&forged),
        Err(NativeRgcnFeatureError::Identity(_))
    ));
}

#[test]
fn every_family_preserves_real_masked_shuffled_and_future_sentinel_ablations() {
    let (_root, manifest, tables) = super::decision_evaluation_tests::frozen_fixture();
    let authority = authority_rows(&tables);
    for (index, family) in NativeRgcnFeatureFamily::ALL.into_iter().enumerate() {
        let suite = derive_native_rgcn_feature_ablation_suite(
            &tables,
            manifest.dataset_id.clone(),
            &authority,
            family,
            0x5eed + index as u64,
        )
        .expect("derive ablation suite");
        let (start, end) = family.columns();
        assert!(suite.future_leak_sentinel_rejected);
        assert_ne!(suite.real.derivation_id, suite.masked.derivation_id);
        assert_ne!(suite.real.derivation_id, suite.shuffled.derivation_id);
        for (real, masked) in suite.real.rows.iter().zip(&suite.masked.rows) {
            assert!(masked.features[start..end].iter().all(|&value| value == 0));
            assert_eq!(real.features[..start], masked.features[..start]);
            assert_eq!(real.features[end..], masked.features[end..]);
        }
        for split in [
            GraphDecisionSplit::Train,
            GraphDecisionSplit::Validation,
            GraphDecisionSplit::Test,
        ] {
            let mut real = suite
                .real
                .rows
                .iter()
                .filter(|row| row.split == split)
                .map(|row| row.features[start..end].to_vec())
                .collect::<Vec<_>>();
            let mut shuffled = suite
                .shuffled
                .rows
                .iter()
                .filter(|row| row.split == split)
                .map(|row| row.features[start..end].to_vec())
                .collect::<Vec<_>>();
            real.sort_unstable();
            shuffled.sort_unstable();
            assert_eq!(real, shuffled);
        }
        assert_eq!(suite.shuffled.audit.cross_split_shuffle_moves, 0);
    }
}

#[test]
fn future_authority_identity_drift_and_unearned_multitask_launch_fail_closed() {
    let (_root, manifest, tables) = super::decision_evaluation_tests::frozen_fixture();
    let mut authority = authority_rows(&tables);
    authority[0].available_through = authority[0].observation_cutoff + 1;
    assert!(matches!(
        derive_native_rgcn_features(
            &tables,
            manifest.dataset_id,
            &authority,
            NativeRgcnFeatureDerivationPolicy::real(NativeRgcnFeatureFamily::Evidence),
        ),
        Err(NativeRgcnFeatureError::FutureLeak(_))
    ));

    let gate = certify_native_rgcn_multitask_launch_gate(None, 0, false, 100)
        .expect("certify locked launch gate");
    assert!(!gate.authorized);
    assert!(matches!(
        require_native_rgcn_multitask_launch(&gate),
        Err(NativeRgcnFeatureError::MultiTaskLocked(_))
    ));
    let mut forged = gate;
    forged.authoritative_task_count = 6;
    assert!(matches!(
        require_native_rgcn_multitask_launch(&forged),
        Err(NativeRgcnFeatureError::Identity(_))
    ));
}

#[test]
fn multitask_identity_and_promotion_require_the_complete_six_head_contract() {
    let digest = |byte: char| format!("b3-{}", byte.to_string().repeat(64));
    let gate = certify_native_rgcn_multitask_launch_gate(
        Some(digest('a').into()),
        NativeRgcnTaskHeadKind::ALL.len() as u32,
        true,
        100,
    )
    .expect("authorize launch contract");
    assert!(gate.authorized);
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
            checkpoint_selection_rule: "aggregate validation; no important-task regression".into(),
            encoder_width: 16,
            encoder_layers: 1,
            propagation_rule: "typed-normalized-sum+inverse+qualifier-incidence/relu/v1".into(),
        },
    )
    .expect("certify multi-task identity");
    validate_native_rgcn_multitask_identity(&identity).expect("validate model identity");

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
        .expect("certify promotion");
    assert!(promotion.promoted);
    assert_eq!(promotion.head_evidence.len(), 6);
}
