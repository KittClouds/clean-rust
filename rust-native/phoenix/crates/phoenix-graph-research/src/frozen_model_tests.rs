use crate::*;
use compact_str::CompactString;
use std::time::{Duration, Instant};
use tempfile::tempdir;
use wide::f32x8;

#[test]
fn frozen_model_round_trips_and_restart_scores_without_training() {
    let features = fixture_features();
    let snapshot = fixture_model(&features);
    let directory = tempdir().expect("model directory");
    let first = FrozenModelBundle::write(&snapshot, directory.path()).expect("write model");
    let second = FrozenModelBundle::write(&snapshot, directory.path()).expect("reuse model");
    assert_eq!(first, second);
    assert_eq!(
        std::fs::read_dir(directory.path())
            .expect("artifact files")
            .count(),
        2
    );
    let expected = reference_scores(&snapshot.tensors, &features);
    drop(snapshot);

    let mapped = FrozenModelMapped::open(&first.manifest).expect("restart mmap");
    let restarted = mapped.score_mlp16(&features).expect("restart inference");
    assert_eq!(score_bits(&restarted), score_bits(&expected));
    assert_eq!(mapped.manifest().training.training_executions, 1);
    assert!(mapped.manifest().training.test_locked_during_selection);
    let metrics = evaluate_binary_scores(&[false, true, false, true], &restarted, 4)
        .expect("restart metrics");
    let certificate = certify_model_scores(
        "proposal-outcome-binary/v1",
        RESEARCH_EVALUATION_SCHEMA,
        ResearchSplit::Validation,
        &restarted,
        &metrics,
    )
    .expect("restart certificate");
    assert_eq!(mapped.manifest().score_certificates, vec![certificate]);
    let model_id = mapped.manifest().model_id.clone();
    drop(mapped);

    let reopened = FrozenModelMapped::open(&first.manifest).expect("second restart");
    assert_eq!(reopened.manifest().model_id, model_id);
    assert_eq!(
        score_bits(&reopened.score_mlp16(&features).expect("second scores")),
        score_bits(&expected)
    );
}

#[test]
fn frozen_model_rejects_manifest_drift_and_weight_corruption() {
    let features = fixture_features();
    let identity_directory = tempdir().expect("identity directory");
    let paths = FrozenModelBundle::write(&fixture_model(&features), identity_directory.path())
        .expect("write identity model");
    let mut manifest: FrozenModelManifest =
        serde_json::from_slice(&std::fs::read(&paths.manifest).expect("read model manifest"))
            .expect("decode model manifest");
    manifest.runtime.framework_version = "changed".into();
    std::fs::write(
        &paths.manifest,
        serde_json::to_vec_pretty(&manifest).expect("encode drift"),
    )
    .expect("write drift");
    assert!(matches!(
        FrozenModelMapped::open(&paths.manifest),
        Err(FrozenModelError::IdentityMismatch)
    ));

    let corrupt_directory = tempdir().expect("corrupt directory");
    let paths = FrozenModelBundle::write(&fixture_model(&features), corrupt_directory.path())
        .expect("write corrupt model");
    let mut weights = std::fs::read(&paths.weights).expect("read weights");
    let last = weights.last_mut().expect("weight byte");
    *last ^= 0x01;
    std::fs::write(&paths.weights, weights).expect("corrupt weights");
    assert!(matches!(
        FrozenModelMapped::open(&paths.manifest),
        Err(FrozenModelError::CorruptArtifact("weights digest"))
    ));
}

#[test]
fn frozen_model_rejects_training_seed_and_tensor_contract_drift() {
    let features = fixture_features();
    let directory = tempdir().expect("invalid directory");

    let mut invalid = fixture_model(&features);
    invalid.training.test_locked_during_selection = false;
    assert!(matches!(
        FrozenModelBundle::write(&invalid, directory.path()),
        Err(FrozenModelError::InvalidContract("training receipt"))
    ));

    let mut invalid = fixture_model(&features);
    invalid.seeds.selected_repeat = u16::MAX;
    assert!(matches!(
        FrozenModelBundle::write(&invalid, directory.path()),
        Err(FrozenModelError::InvalidContract("seed receipt"))
    ));

    let mut invalid = fixture_model(&features);
    invalid.tensors[0].shape = vec![8, 32];
    assert!(matches!(
        FrozenModelBundle::write(&invalid, directory.path()),
        Err(FrozenModelError::InvalidTensorLayout(
            "tensor specification"
        ))
    ));

    let mut invalid = fixture_model(&features);
    invalid.score_certificates[0].split = ResearchSplit::Test;
    assert!(matches!(
        FrozenModelBundle::write(&invalid, directory.path()),
        Err(FrozenModelError::InvalidContract(
            "validation score certificate"
        ))
    ));
}

#[test]
fn restart_scores_twenty_thousand_rows_within_gate() {
    let seed_features = fixture_features();
    let snapshot = fixture_model(&seed_features);
    let directory = tempdir().expect("performance directory");
    let paths = FrozenModelBundle::write(&snapshot, directory.path()).expect("write model");
    let mapped = FrozenModelMapped::open(paths.manifest).expect("map model");
    let features = (0..20_000)
        .map(|index| seed_features[index % seed_features.len()])
        .collect::<Vec<_>>();
    let started = Instant::now();
    let scores = mapped.score_mlp16(&features).expect("score rows");
    let elapsed = started.elapsed();
    assert_eq!(scores.len(), features.len());
    assert!(
        elapsed < Duration::from_secs(1),
        "restart inference gate exceeded: {elapsed:?}"
    );
}

fn fixture_model(features: &[[f32; 16]]) -> FrozenModelSnapshot {
    let tensors = fixture_tensors();
    let scores = reference_scores(&tensors, features);
    let labels = [false, true, false, true];
    let metrics = evaluate_binary_scores(&labels, &scores, 4).expect("fixture metrics");
    let score_certificate = certify_model_scores(
        "proposal-outcome-binary/v1",
        RESEARCH_EVALUATION_SCHEMA,
        ResearchSplit::Validation,
        &scores,
        &metrics,
    )
    .expect("fixture score certificate");
    let seeds = [11_u64, 29, 47];
    let certificate = SeedCertificate {
        namespace: "frozen-model-test".into(),
        digest: digest_seeds(&seeds),
        seeds: seeds.to_vec(),
    };
    FrozenModelSnapshot {
        source: FrozenModelSourceIdentity {
            dataset_id: digest_bytes(b"dataset-v1"),
            checkpoint_id: "checkpoint-v1".into(),
            checkpoint_generation: 7,
            tensor_id: digest_bytes(b"tensor-v1"),
            topology_derivation_id: digest_bytes(b"topology-v1"),
            topology_blake3: digest_bytes(b"topology"),
            evaluation_protocol_id: digest_bytes(b"protocol-v1"),
        },
        architecture: FrozenModelArchitecture::mlp16(),
        hyperparameters: FrozenModelHyperparameters {
            epochs: 24,
            batch_size: 32,
            learning_rate: 0.025,
            l2: 0.0005,
        },
        seeds: certify_model_seed_receipt(&certificate, 1).expect("seed receipt"),
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
                implementation_version: "phoenix-sgd/v1".into(),
                steps_completed: 96,
                state_blake3: digest_bytes(b"optimizer-state"),
            },
        },
        score_certificates: vec![score_certificate],
        tensors,
    }
}

fn fixture_tensors() -> Vec<FrozenModelTensor> {
    let mut hidden_weight = vec![0.0_f32; 256];
    for index in 0..16 {
        hidden_weight[index * 16 + index] = 0.5;
    }
    vec![
        tensor(MODEL_HIDDEN_WEIGHT, &[16, 16], hidden_weight),
        tensor(MODEL_HIDDEN_BIAS, &[16], vec![0.0; 16]),
        tensor(MODEL_OUTPUT_WEIGHT, &[16], vec![0.1; 16]),
        tensor(MODEL_OUTPUT_BIAS, &[1], vec![-0.2]),
    ]
}

fn fixture_features() -> Vec<[f32; 16]> {
    [0.0_f32, 0.25, -0.5, 1.0]
        .into_iter()
        .map(|scale| std::array::from_fn(|index| scale * (index + 1) as f32 / 16.0))
        .collect()
}

fn reference_scores(tensors: &[FrozenModelTensor], features: &[[f32; 16]]) -> Vec<f32> {
    let hidden_weight: &[f32; 256] = tensors[0].values.as_slice().try_into().expect("weights");
    let hidden_bias: &[f32; 16] = tensors[1].values.as_slice().try_into().expect("bias");
    let output_weight: &[f32; 16] = tensors[2].values.as_slice().try_into().expect("output");
    let output_bias = tensors[3].values[0];
    features
        .iter()
        .map(|feature| {
            let hidden: [f32; 16] = std::array::from_fn(|index| {
                let row: &[f32; 16] = hidden_weight[index * 16..(index + 1) * 16]
                    .try_into()
                    .expect("row");
                (simd_dot(row, feature) + hidden_bias[index]).max(0.0)
            });
            sigmoid(simd_dot(output_weight, &hidden) + output_bias)
        })
        .collect()
}

fn tensor(name: &str, shape: &[u64], values: Vec<f32>) -> FrozenModelTensor {
    FrozenModelTensor {
        name: CompactString::new(name),
        shape: shape.to_vec(),
        values,
    }
}

fn digest_seeds(seeds: &[u64]) -> CompactString {
    let mut hasher = blake3::Hasher::new();
    for seed in seeds {
        hasher.update(&seed.to_le_bytes());
    }
    format!("b3-{}", hasher.finalize().to_hex()).into()
}

fn digest_bytes(bytes: &[u8]) -> CompactString {
    format!("b3-{}", blake3::hash(bytes).to_hex()).into()
}

fn score_bits(scores: &[f32]) -> Vec<u32> {
    scores.iter().map(|score| score.to_bits()).collect()
}

fn simd_dot(left: &[f32; 16], right: &[f32; 16]) -> f32 {
    let left_low: [f32; 8] = left[..8].try_into().expect("eight values");
    let right_low: [f32; 8] = right[..8].try_into().expect("eight values");
    let left_high: [f32; 8] = left[8..].try_into().expect("eight values");
    let right_high: [f32; 8] = right[8..].try_into().expect("eight values");
    let low: [f32; 8] = (f32x8::from(left_low) * f32x8::from(right_low)).into();
    let high: [f32; 8] = (f32x8::from(left_high) * f32x8::from(right_high)).into();
    low.into_iter().chain(high).sum()
}

fn sigmoid(value: f32) -> f32 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exp = value.exp();
        exp / (1.0 + exp)
    }
}
