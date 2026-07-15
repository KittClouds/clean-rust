use super::*;
use phoenix_types::{
    GraphDecisionAction, GraphDecisionApproval, GraphDecisionAuthority, GraphDecisionAuthorityKind,
    GraphDecisionEvidenceRef, GraphDecisionHeader, GraphDecisionRewardSignal,
    GraphDecisionRewardVector, GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION,
    GRAPH_DECISION_REWARD_SCHEMA_VERSION,
};
use tempfile::tempdir;

fn authority(cutoff: i64) -> GraphDecisionAuthority {
    GraphDecisionAuthority {
        authority_id: "operator-1".into(),
        kind: GraphDecisionAuthorityKind::Operator,
        policy_id: "native-decision-policy-v1".into(),
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

fn request(index: usize, cutoff: i64) -> EpisodeCandidateGenerationRequest {
    let authority = authority(cutoff);
    EpisodeCandidateGenerationRequest {
        candidate_group_id: format!("candidate-group-{index}").into(),
        event_id: format!("event-{index}").into(),
        new_episode_id: format!("new-episode-{index}").into(),
        task_id: "canonical-episode-assignment-v1".into(),
        header: GraphDecisionHeader {
            schema_version: GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION,
            decision_id: format!("decision-{index}").into(),
            pre_state_id: format!("pre-state-{index}").into(),
            decided_at: cutoff,
            authority,
            approval: None,
        },
        evidence: vec![evidence(cutoff)],
        episode_seeds: vec![
            EpisodeCandidateSeed {
                episode_id: format!("episode-{index}").into(),
                available_at: cutoff - 50,
                active: true,
                scope_compatible: true,
                temporally_plausible: true,
                same_entity: true,
                related_entity: true,
                difficult_near_neighbor: true,
            },
            EpisodeCandidateSeed {
                episode_id: format!("future-episode-{index}").into(),
                available_at: cutoff + 1,
                active: true,
                scope_compatible: true,
                temporally_plausible: true,
                same_entity: false,
                related_entity: false,
                difficult_near_neighbor: false,
            },
        ],
    }
}

fn pending_rewards(decision_id: &str) -> GraphDecisionRewardVector {
    GraphDecisionRewardVector {
        schema_version: GRAPH_DECISION_REWARD_SCHEMA_VERSION,
        decision_id: decision_id.into(),
        evidence_support: GraphDecisionRewardSignal::Pending,
        temporal_consistency: GraphDecisionRewardSignal::Pending,
        canonical_identity_preservation: GraphDecisionRewardSignal::Pending,
        contradiction_reduction: GraphDecisionRewardSignal::Pending,
        minimal_edit_cost: GraphDecisionRewardSignal::Pending,
        human_acceptance: GraphDecisionRewardSignal::Pending,
        future_stability: GraphDecisionRewardSignal::Pending,
        abstention_correctness: GraphDecisionRewardSignal::Pending,
    }
}

fn approve(mut action: GraphDecisionAction, index: usize, cutoff: i64) -> GraphDecisionAction {
    let approval = Some(GraphDecisionApproval {
        approval_id: format!("approval-{index}").into(),
        approver_id: "operator-1".into(),
        approved_at: cutoff - 1,
    });
    match &mut action {
        GraphDecisionAction::AttachToEpisode(value) => value.header.approval = approval,
        GraphDecisionAction::CreateEpisode(value) => value.header.approval = approval,
        _ => panic!("fixture selected action must be an episode action"),
    }
    action
}

fn example(
    index: usize,
    cutoff: i64,
    split: GraphDecisionSplit,
) -> (
    GraphDecisionTrajectoryExample,
    CandidateGenerationPerformanceReceipt,
) {
    let generated = generate_episode_assignment_candidates(&request(index, cutoff))
        .expect("generate candidate group");
    let selected = generated
        .group
        .candidates
        .iter()
        .find(|candidate| matches!(candidate.action, GraphDecisionAction::AttachToEpisode(_)))
        .expect("attach candidate")
        .action
        .clone();
    let decision_id = format!("decision-{index}");
    (
        GraphDecisionTrajectoryExample {
            decision_id: decision_id.as_str().into(),
            observation_cutoff: cutoff,
            pre_state_snapshot_id: format!("pre-state-{index}").into(),
            candidate_group: generated.group,
            selected_action: approve(selected, index, cutoff),
            evidence_references: vec![evidence(cutoff)],
            delta: GraphDecisionDeltaReference {
                before_delta_id: format!("before-delta-{index}").into(),
                after_delta_id: format!("after-delta-{index}").into(),
            },
            post_state_snapshot_id: format!("post-state-{index}").into(),
            reward_vector: pending_rewards(&decision_id),
            authority: authority(cutoff),
            split,
            provenance: GraphDecisionProvenance {
                decision_fingerprint: format!("fingerprint-{index}").into(),
                source_receipt_ids: vec![format!("receipt-{index}").into()],
                label_authority_id: "operator-1".into(),
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

fn fixture() -> (
    Vec<GraphDecisionTrajectoryExample>,
    Vec<CandidateGenerationPerformanceReceipt>,
) {
    let rows = [
        example(1, 100, GraphDecisionSplit::Train),
        example(2, 200, GraphDecisionSplit::Validation),
        example(3, 300, GraphDecisionSplit::Test),
    ];
    rows.into_iter().unzip()
}

#[test]
fn episode_candidate_generator_is_deterministic_and_grammar_complete() {
    let request = request(1, 100);
    let first = generate_episode_assignment_candidates(&request).expect("first generation");
    let second = generate_episode_assignment_candidates(&request).expect("second generation");
    assert_eq!(first.group, second.group);
    assert_eq!(first.group.candidates.len(), 3);
    assert_eq!(first.group.generation.invalid_candidates_rejected, 1);
    assert!(first
        .group
        .candidates
        .iter()
        .any(|candidate| matches!(candidate.action, GraphDecisionAction::AttachToEpisode(_))));
    assert!(first
        .group
        .candidates
        .iter()
        .any(|candidate| matches!(candidate.action, GraphDecisionAction::CreateEpisode(_))));
    assert!(first
        .group
        .candidates
        .iter()
        .any(|candidate| matches!(candidate.action, GraphDecisionAction::Abstain(_))));
    assert_eq!(
        first.performance.candidate_identity,
        second.performance.candidate_identity
    );

    let mut seeds = first
        .group
        .candidates
        .iter()
        .rev()
        .map(|candidate| GraphDecisionCandidateSeed {
            action: candidate.action.clone(),
            sources: candidate.sources.clone(),
        })
        .collect::<Vec<_>>();
    seeds.push(seeds[0].clone());
    seeds.push(GraphDecisionCandidateSeed {
        action: seeds[0].action.clone(),
        sources: Vec::new(),
    });
    let general = generate_graph_decision_candidates(&GraphDecisionCandidateGenerationRequest {
        candidate_group_id: "general-group".into(),
        generator_input_id: "b3-general-input".into(),
        seeds,
    })
    .expect("general grammar generation");
    assert_eq!(general.group.candidates.len(), 3);
    assert_eq!(general.group.generation.invalid_candidates_rejected, 2);
    assert!(general
        .group
        .candidates
        .windows(2)
        .all(|pair| pair[0].action_identity < pair[1].action_identity));
}

#[test]
fn frozen_trajectory_round_trips_ten_exact_sections_and_stable_identity() {
    let (mut examples, performance) = fixture();
    examples.reverse();
    let root = tempdir().expect("artifact root");
    let paths = FrozenGraphDecisionTrajectoryBundle::write(examples, performance, root.path())
        .expect("write frozen trajectories");
    let mapped = FrozenGraphDecisionTrajectoryMapped::open(&paths.manifest).expect("mmap open");
    assert_eq!(mapped.manifest().sections.len(), 10);
    assert_eq!(mapped.manifest().train_decisions, 1);
    assert_eq!(mapped.manifest().validation_decisions, 1);
    assert_eq!(mapped.manifest().test_decisions, 1);
    assert_eq!(
        mapped
            .manifest()
            .leakage_certificate
            .correct_action_candidate_coverage_basis_points,
        10_000
    );
    assert!(mapped.manifest().leakage_certificate.passes());
    let tables = mapped.tables().expect("decode sections");
    assert_eq!(tables.decisions.len(), 3);
    assert_eq!(tables.candidate_actions.len(), 9);
    assert_eq!(tables.decisions[0].candidate_actions.length, 3);
    assert_eq!(tables.decisions[0].evidence.length, 1);
    for section in FrozenDecisionSectionKind::ALL {
        assert!(!mapped.section_bytes(section).is_empty());
    }
}

#[test]
fn semantic_dataset_identity_excludes_generation_latency() {
    let (examples, performance) = fixture();
    let root_a = tempdir().expect("root a");
    let first = FrozenGraphDecisionTrajectoryBundle::write(
        examples.clone(),
        performance.clone(),
        root_a.path(),
    )
    .expect("first write");
    let mut changed_performance = performance;
    for receipt in &mut changed_performance {
        receipt.generation_latency_ns += 99_000;
    }
    let root_b = tempdir().expect("root b");
    let second =
        FrozenGraphDecisionTrajectoryBundle::write(examples, changed_performance, root_b.path())
            .expect("second write");
    assert_eq!(first.dataset_id, second.dataset_id);
    assert_eq!(
        std::fs::read(first.binary).expect("first binary"),
        std::fs::read(second.binary).expect("second binary")
    );
    assert_ne!(
        std::fs::read(first.performance_receipt).expect("first performance"),
        std::fs::read(second.performance_receipt).expect("second performance")
    );
}

#[test]
fn leakage_tribunal_rejects_each_forbidden_signal() {
    type Mutator = fn(&mut GraphDecisionTrajectoryExample);
    let cases: [Mutator; 6] = [
        |row| row.evidence_references[0].available_at = row.observation_cutoff + 1,
        |row| {
            row.provenance
                .leakage_witness
                .post_decision_edges_in_pre_state = 1
        },
        |row| {
            row.provenance
                .leakage_witness
                .future_episode_memberships_in_features = 1
        },
        |row| {
            row.provenance
                .leakage_witness
                .validation_test_facts_in_training_topology = 1
        },
        |row| row.provenance.leakage_witness.outcome_fields_used_as_inputs = 1,
        |row| {
            row.provenance
                .leakage_witness
                .candidate_generation_used_held_out_label = true
        },
    ];
    for mutate in cases {
        let (mut examples, performance) = fixture();
        mutate(&mut examples[0]);
        let root = tempdir().expect("leakage root");
        assert!(matches!(
            FrozenGraphDecisionTrajectoryBundle::write(examples, performance, root.path()),
            Err(FrozenGraphDecisionTrajectoryError::Leakage(_))
        ));
    }
}

#[test]
fn cross_split_fingerprint_and_missing_correct_action_fail_installation() {
    let (mut examples, performance) = fixture();
    examples[1].provenance.decision_fingerprint =
        examples[0].provenance.decision_fingerprint.clone();
    let root = tempdir().expect("fingerprint root");
    assert!(matches!(
        FrozenGraphDecisionTrajectoryBundle::write(examples, performance, root.path()),
        Err(FrozenGraphDecisionTrajectoryError::Leakage(_))
    ));

    let (mut examples, performance) = fixture();
    let cutoff = examples[0].observation_cutoff;
    let mut absent = examples[0]
        .candidate_group
        .candidates
        .iter()
        .find(|candidate| matches!(candidate.action, GraphDecisionAction::CreateEpisode(_)))
        .expect("create candidate")
        .action
        .clone();
    if let GraphDecisionAction::CreateEpisode(value) = &mut absent {
        value.episode_id = "not-generated".into();
    }
    examples[0].selected_action = approve(absent, 1, cutoff);
    let root = tempdir().expect("coverage root");
    assert!(matches!(
        FrozenGraphDecisionTrajectoryBundle::write(examples, performance, root.path()),
        Err(FrozenGraphDecisionTrajectoryError::Leakage(
            "correct action absent from candidate group"
        ))
    ));
}

#[test]
fn binary_corruption_fails_before_section_access() {
    let (examples, performance) = fixture();
    let root = tempdir().expect("corruption root");
    let paths = FrozenGraphDecisionTrajectoryBundle::write(examples, performance, root.path())
        .expect("write artifact");
    let mut binary = std::fs::read(&paths.binary).expect("read binary");
    let last = binary.len() - 1;
    binary[last] ^= 0x01;
    std::fs::write(&paths.binary, binary).expect("corrupt binary");
    assert!(matches!(
        FrozenGraphDecisionTrajectoryMapped::open(&paths.manifest),
        Err(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
            "binary identity"
        ))
    ));
}
