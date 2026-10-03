use r1_stage1_search::{
    CalibratedIdentityTerminalV06, Edit, IdentityCompositionV03, SelectorInput, SemanticFeatures,
    TaskPooledIdentityTerminalV07, TerminalScorer, IDENTITY_LINEAR_V03_BINARY_SHA256,
    IDENTITY_LINEAR_V03_METADATA_SHA256, Q_TERMINAL_V06_CALIBRATION_BINARY_SHA256,
    Q_TERMINAL_V06_CALIBRATION_METADATA_SHA256, Q_TERMINAL_V06_REFERENCE_SHA256,
};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

const REFERENCE_PATH: &str = r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v06\rust-composition-reference-v01.json";

#[derive(Deserialize)]
struct CompositionReference {
    assignment: Vec<u8>,
    clauses: Vec<ClauseReference>,
    expected_semantic_log_score: f64,
    expected_semantic_probability: f64,
    global_h_used: bool,
    identity_head_binary_sha256: String,
    kind_order: Vec<String>,
    reference_id: String,
    schema: String,
}

#[derive(Deserialize)]
struct ClauseReference {
    entity_ids: Vec<usize>,
    role_ids: Vec<usize>,
    identity_logits_f64: Vec<f64>,
    supported_kind_probabilities: HashMap<String, f64>,
    #[serde(rename = "raw_H_f32")]
    raw_h_f32: Vec<f32>,
}

fn read_reference() -> (CompositionReference, SemanticFeatures) {
    let path = Path::new(REFERENCE_PATH);
    let bytes = fs::read(path).expect("sealed v06 reference vector is present");
    let digest = Sha256::digest(&bytes);
    let actual_hash = digest
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    assert_eq!(actual_hash, Q_TERMINAL_V06_REFERENCE_SHA256);
    let reference: CompositionReference = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(
        reference.schema,
        "R1_SEMANTIC_COMPOSITION_REFERENCE_VECTOR_V02"
    );
    assert_eq!(reference.reference_id, "fixed-vector-0001");
    assert!(!reference.global_h_used);
    assert_eq!(
        reference.identity_head_binary_sha256,
        IDENTITY_LINEAR_V03_BINARY_SHA256
    );
    assert_eq!(reference.kind_order.len(), 6);

    let entity_count = reference.assignment.len();
    let role_count = reference.assignment.iter().copied().max().unwrap_or(0) as usize + 1;
    let constraint_count = reference.clauses.len();
    let mut embeddings = Vec::with_capacity(constraint_count * 2048);
    let mut entity_incidence = vec![0; constraint_count * entity_count];
    let mut role_incidence = vec![0; constraint_count * role_count];
    for (clause_index, clause) in reference.clauses.iter().enumerate() {
        assert_eq!(clause.raw_h_f32.len(), 2048);
        embeddings.extend_from_slice(&clause.raw_h_f32);
        for &entity in &clause.entity_ids {
            entity_incidence[clause_index * entity_count + entity] = 1;
        }
        for &role in &clause.role_ids {
            role_incidence[clause_index * role_count + role] = 1;
        }
    }
    let features = SemanticFeatures {
        hidden_dim: 2048,
        constraint_count,
        entity_count,
        role_count,
        constraint_embeddings: embeddings.into_boxed_slice(),
        global_embedding: vec![0.0; 2048].into_boxed_slice(),
        constraint_mask: vec![1; constraint_count].into_boxed_slice(),
        entity_incidence: entity_incidence.into_boxed_slice(),
        role_incidence: role_incidence.into_boxed_slice(),
        entity_mask: vec![1; entity_count].into_boxed_slice(),
        role_mask: vec![1; role_count].into_boxed_slice(),
    };
    (reference, features)
}

fn assert_close(actual: f64, expected: f64, tolerance: f64) {
    assert!(
        (actual - expected).abs() <= tolerance,
        "actual={actual:.15e}, expected={expected:.15e}, error={:.15e}",
        (actual - expected).abs()
    );
}

fn softmax_reference(logits: &[f64]) -> [f64; 6] {
    let max = logits.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let mut probabilities = [0.0; 6];
    let sum = logits
        .iter()
        .zip(&mut probabilities)
        .map(|(logit, probability)| {
            *probability = (logit - max).exp();
            *probability
        })
        .sum::<f64>();
    probabilities
        .iter_mut()
        .for_each(|probability| *probability /= sum);
    probabilities
}

#[test]
fn pinned_v03_identity_export_matches_sanitized_v06_python_composition() {
    let scorer = IdentityCompositionV03::load_default().unwrap();
    assert_eq!(scorer.binary_sha256(), IDENTITY_LINEAR_V03_BINARY_SHA256);
    assert_eq!(
        scorer.metadata_sha256(),
        IDENTITY_LINEAR_V03_METADATA_SHA256
    );
    let (reference, features) = read_reference();
    let mut scorer = scorer;
    scorer
        .prepare_task(&reference.reference_id, &features)
        .unwrap();
    assert_eq!(scorer.prepared_task_count(), 1);

    for (clause_index, expected) in reference.clauses.iter().enumerate() {
        let logits = scorer.identity_logits(&expected.raw_h_f32).unwrap();
        for (actual, expected_logit) in logits.iter().zip(&expected.identity_logits_f64) {
            assert_close(*actual, *expected_logit, 2e-5);
        }
        let probabilities = scorer
            .identity_probabilities_for_task(&reference.reference_id, &features, clause_index)
            .unwrap();
        let python = softmax_reference(&expected.identity_logits_f64);
        for (actual, expected_probability) in probabilities.into_iter().zip(python) {
            assert_close(actual, expected_probability, 2e-10);
        }
        let conditioned = scorer
            .incidence_conditioned_probabilities_for_task(
                &reference.reference_id,
                &features,
                clause_index,
            )
            .unwrap();
        for (kind, actual) in [
            "different",
            "exactly_one_role",
            "fixed_role",
            "forbidden_role",
            "implies_not_role",
            "same",
        ]
        .into_iter()
        .zip(conditioned)
        {
            assert_close(
                actual,
                expected
                    .supported_kind_probabilities
                    .get(kind)
                    .copied()
                    .unwrap_or(0.0),
                2e-10,
            );
        }
    }
    let prediction = scorer
        .score_raw_for_task(&reference.reference_id, &features, &reference.assignment)
        .unwrap();
    assert_close(
        prediction.semantic_log_score,
        reference.expected_semantic_log_score,
        2e-6,
    );
    assert!(
        (prediction.raw_probability - reference.expected_semantic_probability).abs()
            / reference.expected_semantic_probability
            <= 2e-6
    );

    let expected_count = reference
        .clauses
        .iter()
        .map(|clause| {
            clause
                .supported_kind_probabilities
                .iter()
                .map(|(kind, probability)| {
                    let satisfied = match kind.as_str() {
                        "different" => f64::from(
                            reference.assignment[clause.entity_ids[0]]
                                != reference.assignment[clause.entity_ids[1]],
                        ),
                        "exactly_one_role" => f64::from(
                            clause
                                .entity_ids
                                .iter()
                                .filter(|&&entity| {
                                    usize::from(reference.assignment[entity]) == clause.role_ids[0]
                                })
                                .count()
                                == 1,
                        ),
                        "fixed_role" => f64::from(
                            usize::from(reference.assignment[clause.entity_ids[0]])
                                == clause.role_ids[0],
                        ),
                        "forbidden_role" => f64::from(
                            usize::from(reference.assignment[clause.entity_ids[0]])
                                != clause.role_ids[0],
                        ),
                        "implies_not_role" if clause.entity_ids.len() == 1 => {
                            f64::from(clause.role_ids[0] != clause.role_ids[1])
                        }
                        "implies_not_role" => {
                            let first = reference.assignment[clause.entity_ids[0]];
                            let second = reference.assignment[clause.entity_ids[1]];
                            let direct = first != clause.role_ids[0] as u8
                                || second != clause.role_ids[1] as u8;
                            let swapped = first != clause.role_ids[1] as u8
                                || second != clause.role_ids[0] as u8;
                            f64::from(direct) * 0.5 + f64::from(swapped) * 0.5
                        }
                        "same" => f64::from(
                            reference.assignment[clause.entity_ids[0]]
                                == reference.assignment[clause.entity_ids[1]],
                        ),
                        other => panic!("unexpected supported kind {other}"),
                    };
                    probability * satisfied
                })
                .sum::<f64>()
        })
        .sum::<f64>();
    let actual_count = scorer
        .expected_satisfied_clause_count_for_task(
            &reference.reference_id,
            &features,
            &reference.assignment,
        )
        .unwrap();
    assert_close(actual_count, expected_count, 2e-10);
    assert_close(
        scorer
            .expected_satisfied_clause_count_with_task_prior_for_task(
                &reference.reference_id,
                &features,
                &reference.assignment,
                0.0,
            )
            .unwrap(),
        actual_count,
        2e-10,
    );
    let pooled_count = scorer
        .expected_satisfied_clause_count_with_task_prior_for_task(
            &reference.reference_id,
            &features,
            &reference.assignment,
            1.0,
        )
        .unwrap();
    assert!((0.0..=features.constraint_count as f64).contains(&pooled_count));
    assert!(scorer
        .expected_satisfied_clause_count_with_task_prior_for_task(
            &reference.reference_id,
            &features,
            &reference.assignment,
            1.01,
        )
        .is_err());

    let mut selector = TaskPooledIdentityTerminalV07::load_default().unwrap();
    let expected_rank = scorer
        .expected_satisfied_clause_count_with_task_prior_for_task(
            &reference.reference_id,
            &features,
            &reference.assignment,
            0.75,
        )
        .unwrap();
    let q = selector
        .q_terminal(SelectorInput {
            task_id: &reference.reference_id,
            features: &features,
            assignment: &reference.assignment,
        })
        .unwrap();
    assert_close(q.selection_score.unwrap(), expected_rank, 2e-10);
    assert!((0.0..=1.0).contains(&f64::from(q.value)));
}

#[test]
fn same_task_id_with_changed_feature_token_fails_closed() {
    let (reference, features) = read_reference();
    let mut scorer = IdentityCompositionV03::load_default().unwrap();
    scorer
        .prepare_task(&reference.reference_id, &features)
        .unwrap();
    let changed_features = features.clone();
    assert!(scorer
        .prepare_task(&reference.reference_id, &changed_features)
        .is_err());
}

#[test]
fn raw_proposal_delta_and_masked_delta_match_python_feature_math() {
    let features = SemanticFeatures {
        hidden_dim: 2048,
        constraint_count: 4,
        entity_count: 2,
        role_count: 2,
        constraint_embeddings: (0..4)
            .flat_map(|clause| {
                (0..2048).map(move |index| ((((clause + 1) * (index % 37)) % 17) - 8) as f32 / 64.0)
            })
            .collect::<Vec<_>>()
            .into_boxed_slice(),
        global_embedding: vec![0.0; 2048].into_boxed_slice(),
        constraint_mask: vec![1; 4].into_boxed_slice(),
        entity_incidence: vec![1, 1, 1, 0, 1, 1, 0, 1].into_boxed_slice(),
        role_incidence: vec![0, 0, 1, 0, 1, 0, 1, 1].into_boxed_slice(),
        entity_mask: vec![1; 2].into_boxed_slice(),
        role_mask: vec![1; 2].into_boxed_slice(),
    };
    let mut scorer = IdentityCompositionV03::load_default().unwrap();
    let assignment = [0, 1];
    let edit = Edit {
        entity: 0,
        new_role: 1,
    };
    let raw = scorer
        .expected_satisfaction_delta(&features, &assignment, edit)
        .unwrap();
    let cached_raw = scorer
        .expected_satisfaction_delta_for_task("proposal-task", &features, &assignment, edit)
        .unwrap();
    let masked = scorer
        .expected_satisfaction_delta_incidence_masked(&features, &assignment, edit)
        .unwrap();
    let opposite_edit = Edit {
        entity: 1,
        new_role: 0,
    };
    let raw_batch = scorer
        .expected_satisfaction_deltas_for_task(
            "proposal-task",
            &features,
            &assignment,
            &[edit, opposite_edit],
            false,
        )
        .unwrap();
    let masked_batch = scorer
        .expected_satisfaction_deltas_for_task(
            "proposal-task",
            &features,
            &assignment,
            &[edit, opposite_edit],
            true,
        )
        .unwrap();
    assert_close(raw, -1.000_000_000_007_711_8, 2e-8);
    assert_close(cached_raw, raw, 1e-14);
    assert_close(masked, -3.0, 1e-12);
    assert_close(raw_batch.deltas[0], cached_raw, 1e-14);
    assert_close(masked_batch.deltas[0], masked, 1e-12);
    assert_eq!(raw_batch.affected_clause_counts, [3, 3]);
    assert_eq!(masked_batch.affected_clause_counts, [3, 3]);
}

#[test]
fn v06_calibration_is_hash_pinned_and_matches_python_vector() {
    let mut terminal = CalibratedIdentityTerminalV06::load_default().unwrap();
    assert_eq!(
        terminal.calibration().binary_sha256(),
        Q_TERMINAL_V06_CALIBRATION_BINARY_SHA256
    );
    assert_eq!(
        terminal.calibration().metadata_sha256(),
        Q_TERMINAL_V06_CALIBRATION_METADATA_SHA256
    );
    let (reference, features) = read_reference();
    let (raw, calibrated) = terminal
        .score(&reference.reference_id, &features, &reference.assignment)
        .unwrap();
    assert_close(raw.semantic_log_score, -289.690_281_100_320_65, 2e-6);
    assert_close(calibrated, 0.475_325_581_952_181, 2e-7);
}
