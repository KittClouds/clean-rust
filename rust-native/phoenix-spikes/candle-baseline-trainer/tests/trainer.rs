use compact_str::{format_compact, CompactString};
use phoenix_candle_baseline_trainer::{
    train_candle_mlp16, CandleTrainerConfig, CandleTrainerError, CandleTrainerRequest,
    CANDLE_BASELINE_TRAINER_ID,
};
use phoenix_graph_research::*;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
use tempfile::TempDir;

#[test]
fn deterministic_training_emits_restartable_frozen_model() {
    let fixture = Fixture::new(64, 16, 8);
    let first = train_candle_mlp16(&fixture.request).expect("first training execution");
    let second = train_candle_mlp16(&fixture.request).expect("deterministic rerun");

    assert_eq!(first.artifact, second.artifact);
    assert_eq!(first.report.model_id, second.report.model_id);
    assert_eq!(first.report.weights_blake3, second.report.weights_blake3);
    assert_eq!(first.report.selected_seed, fixture.seeds[1]);
    assert!(first.report.restart_score_bits_exact);
    assert!(first.report.candle_max_abs_error <= 1.0e-4);
    assert_eq!(first.report.validation_metrics.samples, 32);
    assert_eq!(first.report.validation_ranking_metrics.queries, 16);
    assert_eq!(
        std::fs::read_dir(fixture.output.path())
            .expect("model artifact directory")
            .count(),
        2
    );

    let manifest = first.artifact.manifest.clone();
    drop(first);
    drop(second);
    let mapped = FrozenModelMapped::open(&manifest).expect("trainer-free restart open");
    let expected = mapped
        .score_mlp16(&fixture.validation_features)
        .expect("first restart score");
    drop(mapped);
    let reopened = FrozenModelMapped::open(&manifest).expect("second restart open");
    let actual = reopened
        .score_mlp16(&fixture.validation_features)
        .expect("second restart score");
    assert_eq!(score_bits(&expected), score_bits(&actual));
    assert_eq!(reopened.manifest().training.training_executions, 1);
    assert_eq!(
        reopened.manifest().training.trainer_id,
        CANDLE_BASELINE_TRAINER_ID
    );
    assert!(reopened.manifest().training.test_locked_during_selection);
    assert_eq!(reopened.manifest().score_certificates.len(), 2);
    assert_eq!(
        reopened.manifest().score_certificates[0].split,
        ResearchSplit::Validation
    );
}

#[test]
fn trainer_fails_closed_on_authority_or_seed_drift() {
    let fixture = Fixture::new(16, 8, 4);
    let mut invalid_seed = fixture.request.clone();
    invalid_seed.selected_repeat = u16::MAX;
    assert!(matches!(
        train_candle_mlp16(&invalid_seed),
        Err(CandleTrainerError::Model(
            FrozenModelError::InvalidContract("seed receipt")
        ))
    ));

    let mut protocol: ResearchEvaluationProtocol = serde_json::from_slice(
        &std::fs::read(&fixture.request.evaluation_protocol).expect("read protocol"),
    )
    .expect("decode protocol");
    protocol.source_dataset_id = digest(b"different-dataset");
    let drifted = write_protocol(&mut protocol, fixture.input.path());
    let mut invalid_authority = fixture.request.clone();
    invalid_authority.evaluation_protocol = drifted;
    assert!(matches!(
        train_candle_mlp16(&invalid_authority),
        Err(CandleTrainerError::Contract("source authority chain"))
    ));
    assert_eq!(
        std::fs::read_dir(fixture.output.path())
            .expect("empty output")
            .count(),
        0
    );
}

#[test]
fn training_path_has_a_bounded_smoke_gate_and_never_counts_test_rows() {
    let fixture = Fixture::new(512, 128, 64);
    let started = Instant::now();
    let outcome = train_candle_mlp16(&fixture.request).expect("bounded training run");
    let elapsed = started.elapsed();
    assert_eq!(outcome.report.training_examples, 1_024);
    assert_eq!(outcome.report.validation_examples, 256);
    assert_eq!(
        outcome.report.optimizer_steps,
        u64::from(fixture.request.config.epochs) * 16
    );
    assert!(outcome.report.restart_score_bits_exact);
    eprintln!(
        "trainer smoke: wall={elapsed:?} train={}us restart={}us rows={}",
        outcome.report.training_micros,
        outcome.report.restart_open_and_score_micros,
        outcome.report.training_examples
    );
    assert!(
        elapsed < Duration::from_secs(10),
        "trainer smoke gate exceeded: {elapsed:?}"
    );
}

struct Fixture {
    _root: TempDir,
    input: TempDir,
    output: TempDir,
    request: CandleTrainerRequest,
    validation_features: Vec<[f32; 16]>,
    seeds: [u64; 3],
}

impl Fixture {
    fn new(train_queries: u32, validation_queries: u32, test_queries: u32) -> Self {
        let root = tempfile::tempdir().expect("fixture root");
        let input = tempfile::tempdir_in(root.path()).expect("input directory");
        let output = tempfile::tempdir_in(root.path()).expect("output directory");
        let dataset_id = digest(b"candle-trainer-dataset-v1");
        let tensor_id = digest(b"candle-trainer-tensor-v1");
        let graph = FrozenGraphResearchSnapshot {
            dataset_id: dataset_id.clone(),
            checkpoint_id: "candle-trainer-checkpoint-v1".into(),
            checkpoint_generation: 3,
            frozen_at_ms: 300,
            split_policy: TemporalSplitPolicy {
                train_through_ms: 100,
                validation_through_ms: 200,
            },
            nodes: Vec::new(),
            edges: Vec::new(),
            incidences: Vec::new(),
            proposals: Vec::new(),
        };
        let graph_paths =
            FrozenGraphResearchBundle::write(&graph, input.path()).expect("write frozen graph");
        let tensor = empty_tensor(dataset_id.clone(), tensor_id.clone());
        let tensor_paths =
            FrozenTensorBundle::write(&tensor, input.path()).expect("write frozen tensor");
        let seeds = [11_u64, 29, 47];
        let mut protocol = protocol(dataset_id.clone(), tensor_id.clone(), seeds);
        let protocol_path = write_protocol(&mut protocol, input.path());
        let (rows, validation_features) =
            feature_rows(train_queries, validation_queries, test_queries);
        let topology = TrainTopologyFeatureSnapshot {
            schema_version: TRAIN_TOPOLOGY_FEATURE_SCHEMA.into(),
            derivation_id: digest(b"candle-trainer-topology-v1"),
            source_dataset_id: dataset_id,
            source_tensor_id: tensor_id,
            evaluation_protocol_id: protocol.protocol_id,
            policy: TrainTopologyFeaturePolicy {
                incidence_negatives_per_positive: 1,
            },
            audit: TrainTopologyAudit {
                fit_edges: train_queries as u64,
                fit_incidences: 0,
                link_examples: rows.len() as u64,
                incidence_examples: 0,
                latest_fit_edge_ms: Some(100),
                topology_blake3: digest(b"candle-trainer-asserted-topology-v1"),
                train_only: true,
                asserted_edges_only: true,
                resolved_incidences_only: true,
                leave_one_positive_out: true,
            },
            feature_certificates: Vec::new(),
            link_rows: rows,
            incidence_rows: Vec::new(),
        };
        let topology_paths = TrainTopologyFeatureBundle::write(&topology, input.path())
            .expect("write train topology");
        let request = CandleTrainerRequest {
            graph_manifest: graph_paths.manifest,
            tensor_manifest: tensor_paths.manifest,
            evaluation_protocol: protocol_path,
            topology_manifest: topology_paths.manifest,
            output_root: output.path().to_path_buf(),
            selected_repeat: 1,
            config: CandleTrainerConfig {
                epochs: 4,
                batch_size: 64,
                learning_rate: 0.04,
                l2: 0.0005,
            },
        };
        Self {
            _root: root,
            input,
            output,
            request,
            validation_features,
            seeds,
        }
    }
}

fn empty_tensor(dataset_id: CompactString, tensor_id: CompactString) -> FrozenTensorSnapshot {
    FrozenTensorSnapshot {
        tensor_id,
        source_dataset_id: dataset_id,
        policy: TensorizationPolicy {
            negatives_per_asserted_edge: 1,
        },
        node_ids: Vec::new(),
        node_type_vocabulary: Vec::new(),
        relation_vocabulary: Vec::new(),
        role_vocabulary: Vec::new(),
        feature_schema_vocabulary: Vec::new(),
        node_type_ids: Vec::new(),
        node_authority: Vec::new(),
        node_splits: Vec::new(),
        node_available_at_ms: Vec::new(),
        coo_sources: Vec::new(),
        coo_targets: Vec::new(),
        coo_relation_types: Vec::new(),
        coo_authority: Vec::new(),
        coo_splits: Vec::new(),
        coo_available_at_ms: Vec::new(),
        coo_weights: Vec::new(),
        csr_row_offsets: vec![0],
        csr_columns: Vec::new(),
        csr_edge_indices: Vec::new(),
        incidence_hyperedges: Vec::new(),
        incidence_participants: Vec::new(),
        incidence_role_types: Vec::new(),
        incidence_splits: Vec::new(),
        incidence_resolved: Vec::new(),
        proposal_features: Vec::new(),
        proposal_labels: Vec::new(),
        proposal_label_observed: Vec::new(),
        proposal_splits: Vec::new(),
        proposal_observed_at_ms: Vec::new(),
        proposal_label_available_at_ms: Vec::new(),
        proposal_feature_schema_ids: Vec::new(),
        feature_certificates: Vec::new(),
        negatives: Vec::new(),
    }
}

fn protocol(
    dataset_id: CompactString,
    tensor_id: CompactString,
    seeds: [u64; 3],
) -> ResearchEvaluationProtocol {
    ResearchEvaluationProtocol {
        schema_version: RESEARCH_EVALUATION_SCHEMA.into(),
        protocol_id: "pending".into(),
        tensor_id,
        source_dataset_id: dataset_id,
        split_policy: TemporalSplitPolicy {
            train_through_ms: 100,
            validation_through_ms: 200,
        },
        policy: EvaluationPolicy {
            feature_schema_id: "train-topology-link-v1".into(),
            seed_root: 11,
            repeats: 3,
            calibration_bins: 10,
            ftrl: FtrlConfig::default(),
            mlp: MlpConfig::default(),
        },
        seed_certificate: SeedCertificate {
            namespace: "candle-baseline-trainer-test".into(),
            digest: seed_digest(&seeds),
            seeds: seeds.to_vec(),
        },
        tasks: Vec::new(),
        leakage_audit: LeakageAudit {
            nodes_checked: 0,
            edges_checked: 0,
            incidences_checked: 0,
            proposals_checked: 0,
            observed_proposals: 0,
            censored_proposals: 0,
            negatives_checked: 0,
            feature_columns_checked: 16,
            train_examples: 0,
            validation_examples: 0,
            test_examples: 0,
            no_future_rows: true,
            no_label_before_availability: true,
            no_censored_supervision: true,
            no_feature_schema_mixing: true,
            no_negative_collisions: true,
        },
    }
}

fn write_protocol(protocol: &mut ResearchEvaluationProtocol, root: &Path) -> PathBuf {
    protocol.protocol_id = "pending".into();
    protocol.protocol_id = digest(&serde_json::to_vec(protocol).expect("encode protocol identity"));
    let path = root.join(format!("{}.evaluation.json", protocol.protocol_id));
    std::fs::write(
        &path,
        serde_json::to_vec_pretty(protocol).expect("encode protocol"),
    )
    .expect("write protocol");
    path
}

fn feature_rows(
    train_queries: u32,
    validation_queries: u32,
    test_queries: u32,
) -> (Vec<DerivedFeatureRow>, Vec<[f32; 16]>) {
    let mut rows = Vec::with_capacity(
        (train_queries as usize + validation_queries as usize + test_queries as usize) * 2,
    );
    let mut validation_features = Vec::with_capacity(validation_queries as usize * 2);
    let mut query = 0_u32;
    for (split, count) in [
        (ResearchSplit::Train, train_queries),
        (ResearchSplit::Validation, validation_queries),
        (ResearchSplit::Test, test_queries),
    ] {
        for _ in 0..count {
            for (candidate_offset, label, sign) in [(0, true, 1.0), (1, false, -1.0)] {
                let features = std::array::from_fn(|column| {
                    sign * (column as f32 + 1.0) / 16.0 + query as f32 * 0.000_01
                });
                if split == ResearchSplit::Validation {
                    validation_features.push(features);
                }
                rows.push(DerivedFeatureRow {
                    positive_index: query,
                    candidate: query * 2 + candidate_offset,
                    split,
                    label,
                    features,
                });
            }
            query += 1;
        }
    }
    (rows, validation_features)
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

fn score_bits(scores: &[f32]) -> Vec<u32> {
    scores.iter().map(|score| score.to_bits()).collect()
}
