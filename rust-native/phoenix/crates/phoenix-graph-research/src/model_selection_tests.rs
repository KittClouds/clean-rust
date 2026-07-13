use crate::*;
use compact_str::{format_compact, CompactString};
use std::path::PathBuf;
use std::time::{Duration, Instant};
use tempfile::TempDir;

const TASK: &str = "typed-link-binary-selection/v1";

#[test]
fn selects_complete_seed_grid_and_finalizes_one_test_without_copying_weights() {
    let fixture = Fixture::new(64);
    let before = std::fs::read_dir(fixture.root.path())
        .expect("candidate files")
        .count();
    assert_eq!(before, 12);
    let selection = select_frozen_models(
        &fixture.manifests,
        fixture.policy.clone(),
        fixture.validation_set(),
    )
    .expect("select models");
    assert_eq!(selection.configuration_summaries().len(), 2);
    let selected_validation_model_id = selection.selected_validation_model_id().to_owned();
    let selected_manifest = fixture
        .manifests
        .iter()
        .find(|path| {
            FrozenModelMapped::open(path)
                .expect("open candidate")
                .manifest()
                .model_id
                == selected_validation_model_id
        })
        .expect("selected candidate");
    let selected = FrozenModelMapped::open(selected_manifest).expect("open selected model");
    let selected_weights_file = selected.manifest().weights_file.clone();
    let selected_weights_blake3 = selected.manifest().weights_blake3.clone();
    drop(selected);

    let outcome =
        finalize_frozen_model_selection(selection, fixture.test_set(), fixture.root.path())
            .expect("finalize locked test");
    assert_eq!(outcome.ledger.locked_test_executions, 1);
    assert_eq!(
        outcome.ledger.selected_validation_model_id,
        selected_validation_model_id
    );
    assert_ne!(
        outcome.ledger.finalized_model_id,
        outcome.ledger.selected_validation_model_id
    );
    assert_eq!(
        outcome.ledger.selected_weights_blake3,
        selected_weights_blake3
    );
    assert_eq!(outcome.ledger.candidates.len(), 6);
    assert!(outcome
        .ledger
        .configuration_summaries
        .iter()
        .all(|summary| summary.repeats == 3));
    let finalized = FrozenModelMapped::open(&outcome.paths.finalized_model.manifest)
        .expect("open finalized model");
    assert_eq!(finalized.manifest().weights_file, selected_weights_file);
    assert_eq!(
        finalized
            .manifest()
            .score_certificates
            .iter()
            .filter(|certificate| certificate.split == ResearchSplit::Test)
            .count(),
        1
    );
    assert_eq!(
        std::fs::read_dir(fixture.root.path())
            .expect("finalized files")
            .count(),
        before + 3
    );
    let persisted = open_frozen_model_selection_ledger(&outcome.paths.ledger).expect("open ledger");
    assert_eq!(persisted, outcome.ledger);

    let repeated_selection = select_frozen_models(
        &fixture.manifests,
        fixture.policy.clone(),
        fixture.validation_set(),
    )
    .expect("repeat validation-only selection");
    assert!(matches!(
        finalize_frozen_model_selection(
            repeated_selection,
            fixture.test_set(),
            fixture.root.path()
        ),
        Err(FrozenModelSelectionError::LockedTestAlreadyClaimed(_))
    ));

    let renamed = fixture.root.path().join("renamed.model-selection.json");
    std::fs::copy(&outcome.paths.ledger, &renamed).expect("copy renamed ledger");
    assert!(matches!(
        open_frozen_model_selection_ledger(&renamed),
        Err(FrozenModelSelectionError::InvalidContract(
            "persisted ledger identity"
        ))
    ));

    let tamper_root = tempfile::tempdir().expect("tamper directory");
    let tampered_path = tamper_root
        .path()
        .join(outcome.paths.ledger.file_name().expect("ledger filename"));
    let mut tampered = outcome.ledger.clone();
    tampered.locked_test_executions = 2;
    std::fs::write(
        &tampered_path,
        serde_json::to_vec_pretty(&tampered).expect("encode tampered ledger"),
    )
    .expect("write tampered ledger");
    assert!(matches!(
        open_frozen_model_selection_ledger(&tampered_path),
        Err(FrozenModelSelectionError::InvalidContract(
            "persisted ledger identity"
        ))
    ));

    let mut forged = outcome.ledger.clone();
    forged.selected_configuration_id = format!("b3-{}", "0".repeat(64)).into();
    forged.ledger_id = "pending".into();
    forged.ledger_id = format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&forged).expect("encode forged identity")).to_hex()
    )
    .into();
    let forged_path = tamper_root
        .path()
        .join(format!("{}.model-selection.json", forged.ledger_id));
    std::fs::write(
        &forged_path,
        serde_json::to_vec_pretty(&forged).expect("encode forged ledger"),
    )
    .expect("write forged ledger");
    assert!(matches!(
        open_frozen_model_selection_ledger(&forged_path),
        Err(FrozenModelSelectionError::InvalidContract(
            "persisted deterministic selection"
        ))
    ));
}

#[test]
fn rejects_incomplete_seed_sets_test_access_and_validation_drift() {
    let fixture = Fixture::new(16);
    let incomplete = fixture.manifests[..fixture.manifests.len() - 1].to_vec();
    assert!(matches!(
        select_frozen_models(
            &incomplete,
            fixture.policy.clone(),
            fixture.validation_set()
        ),
        Err(FrozenModelSelectionError::InvalidContract(
            "incomplete seed configuration"
        ))
    ));

    let mut drifted_features = fixture.validation_features.clone();
    drifted_features[0][0] += 0.25;
    assert!(matches!(
        select_frozen_models(
            &fixture.manifests,
            fixture.policy.clone(),
            FrozenBinaryEvaluationSet {
                features: &drifted_features,
                labels: &fixture.validation_labels,
            }
        ),
        Err(FrozenModelSelectionError::InvalidContract(
            "validation certificate mismatch"
        ))
    ));

    let candidate = FrozenModelMapped::open(&fixture.manifests[0]).expect("open candidate");
    let mut snapshot = candidate.snapshot().expect("candidate snapshot");
    let scores =
        score_mlp16_tensors(&snapshot.tensors, &fixture.test_features).expect("test scores");
    let metrics = evaluate_binary_scores(&fixture.test_labels, &scores, 10).expect("test metrics");
    snapshot.score_certificates.push(
        certify_model_scores(
            TASK,
            RESEARCH_EVALUATION_SCHEMA,
            ResearchSplit::Test,
            &scores,
            &metrics,
        )
        .expect("test certificate"),
    );
    drop(candidate);
    let test_touched = FrozenModelBundle::write(&snapshot, fixture.root.path())
        .expect("write test-touched candidate");
    let mut manifests = fixture.manifests.clone();
    manifests[0] = test_touched.manifest;
    assert!(matches!(
        select_frozen_models(&manifests, fixture.policy.clone(), fixture.validation_set()),
        Err(FrozenModelSelectionError::InvalidContract(
            "candidate test lock"
        ))
    ));
}

#[test]
fn selection_over_six_models_and_four_thousand_rows_stays_within_gate() {
    let fixture = Fixture::new(2_000);
    let started = Instant::now();
    let selection = select_frozen_models(
        &fixture.manifests,
        fixture.policy.clone(),
        fixture.validation_set(),
    )
    .expect("performance selection");
    let elapsed = started.elapsed();
    eprintln!(
        "selection smoke: wall={elapsed:?} models={} rows={}",
        fixture.manifests.len(),
        fixture.validation_features.len()
    );
    assert_eq!(selection.configuration_summaries().len(), 2);
    assert!(
        elapsed < Duration::from_secs(2),
        "model selection gate exceeded: {elapsed:?}"
    );
}

struct Fixture {
    root: TempDir,
    manifests: Vec<PathBuf>,
    policy: FrozenModelSelectionPolicy,
    validation_features: Vec<[f32; 16]>,
    validation_labels: Vec<bool>,
    test_features: Vec<[f32; 16]>,
    test_labels: Vec<bool>,
}

impl Fixture {
    fn new(validation_pairs: usize) -> Self {
        let root = tempfile::tempdir().expect("selection directory");
        let (validation_features, validation_labels) = evaluation_rows(validation_pairs, 0.0);
        let (test_features, test_labels) = evaluation_rows(32, 0.01);
        let seeds = [11_u64, 29, 47];
        let certificate = SeedCertificate {
            namespace: "model-selection-test".into(),
            digest: seed_digest(&seeds),
            seeds: seeds.to_vec(),
        };
        let mut manifests = Vec::with_capacity(6);
        for configuration in [0_u8, 1] {
            for repeat in 0..seeds.len() {
                let snapshot = candidate_snapshot(
                    configuration,
                    repeat as u16,
                    &certificate,
                    &validation_features,
                    &validation_labels,
                );
                manifests.push(
                    FrozenModelBundle::write(&snapshot, root.path())
                        .expect("write candidate")
                        .manifest,
                );
            }
        }
        manifests.reverse();
        Self {
            root,
            manifests,
            policy: FrozenModelSelectionPolicy {
                task_id: TASK.into(),
                evaluator_schema: RESEARCH_EVALUATION_SCHEMA.into(),
                calibration_bins: 10,
            },
            validation_features,
            validation_labels,
            test_features,
            test_labels,
        }
    }

    fn validation_set(&self) -> FrozenBinaryEvaluationSet<'_> {
        FrozenBinaryEvaluationSet {
            features: &self.validation_features,
            labels: &self.validation_labels,
        }
    }

    fn test_set(&self) -> FrozenBinaryEvaluationSet<'_> {
        FrozenBinaryEvaluationSet {
            features: &self.test_features,
            labels: &self.test_labels,
        }
    }
}

fn candidate_snapshot(
    configuration: u8,
    repeat: u16,
    seeds: &SeedCertificate,
    features: &[[f32; 16]],
    labels: &[bool],
) -> FrozenModelSnapshot {
    let tensors = candidate_tensors(configuration, repeat);
    let scores = score_mlp16_tensors(&tensors, features).expect("validation scores");
    let metrics = evaluate_binary_scores(labels, &scores, 10).expect("validation metrics");
    let certificate = certify_model_scores(
        TASK,
        RESEARCH_EVALUATION_SCHEMA,
        ResearchSplit::Validation,
        &scores,
        &metrics,
    )
    .expect("validation certificate");
    let learning_rate = if configuration == 0 { 0.025 } else { 0.05 };
    FrozenModelSnapshot {
        source: FrozenModelSourceIdentity {
            dataset_id: digest(b"selection-dataset"),
            checkpoint_id: "selection-checkpoint".into(),
            checkpoint_generation: 9,
            tensor_id: digest(b"selection-tensor"),
            topology_derivation_id: digest(b"selection-topology"),
            topology_blake3: digest(b"selection-topology-bytes"),
            evaluation_protocol_id: digest(b"selection-protocol"),
        },
        architecture: FrozenModelArchitecture::mlp16(),
        hyperparameters: FrozenModelHyperparameters {
            epochs: 24,
            batch_size: 32,
            learning_rate,
            l2: 0.0005,
        },
        seeds: certify_model_seed_receipt(seeds, repeat).expect("seed receipt"),
        runtime: FrozenModelRuntimeIdentity {
            framework: "candle".into(),
            framework_version: "0.11.0".into(),
            backend: "cpu".into(),
            target: "x86_64-pc-windows-msvc".into(),
        },
        training: FrozenTrainingReceipt {
            trainer_id: "candle-mlp16/v1".into(),
            training_examples: 128,
            validation_examples: features.len() as u64,
            epochs_completed: 24,
            training_executions: 1,
            selected_on_validation: true,
            test_locked_during_selection: true,
            optimizer: FrozenOptimizerReceipt {
                algorithm: "sgd".into(),
                implementation_version: "candle-nn-sgd/0.11.0-stateless".into(),
                steps_completed: 96,
                state_blake3: digest(&learning_rate.to_bits().to_le_bytes()),
            },
        },
        score_certificates: vec![certificate],
        tensors,
    }
}

fn candidate_tensors(configuration: u8, repeat: u16) -> Vec<FrozenModelTensor> {
    let mut hidden = vec![0.0_f32; 256];
    for index in 0..16 {
        hidden[index * 16 + index] = 1.0;
    }
    let direction = if configuration == 0 { 0.6 } else { -0.1 };
    let output_bias = -0.2 + f32::from(repeat) * 0.01;
    vec![
        tensor(MODEL_HIDDEN_WEIGHT, &[16, 16], hidden),
        tensor(MODEL_HIDDEN_BIAS, &[16], vec![0.0; 16]),
        tensor(MODEL_OUTPUT_WEIGHT, &[16], vec![direction; 16]),
        tensor(MODEL_OUTPUT_BIAS, &[1], vec![output_bias]),
    ]
}

fn evaluation_rows(pairs: usize, offset: f32) -> (Vec<[f32; 16]>, Vec<bool>) {
    let mut features = Vec::with_capacity(pairs * 2);
    let mut labels = Vec::with_capacity(pairs * 2);
    for pair in 0..pairs {
        let scale = 0.5 + pair as f32 * 0.000_01 + offset;
        features.push(std::array::from_fn(|index| {
            scale * (index + 1) as f32 / 16.0
        }));
        labels.push(true);
        features.push(std::array::from_fn(|index| {
            -scale * (index + 1) as f32 / 16.0
        }));
        labels.push(false);
    }
    (features, labels)
}

fn tensor(name: &str, shape: &[u64], values: Vec<f32>) -> FrozenModelTensor {
    FrozenModelTensor {
        name: name.into(),
        shape: shape.to_vec(),
        values,
    }
}

fn seed_digest(seeds: &[u64]) -> CompactString {
    let mut hasher = blake3::Hasher::new();
    for seed in seeds {
        hasher.update(&seed.to_le_bytes());
    }
    format_compact!("b3-{}", hasher.finalize().to_hex())
}

fn digest(bytes: &[u8]) -> CompactString {
    format_compact!("b3-{}", blake3::hash(bytes).to_hex())
}
