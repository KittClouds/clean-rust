use compact_str::{format_compact, CompactString};
use phoenix_candle_baseline_trainer::{
    train_candle_mlp16, train_candle_rgcn16, CandleRgcnConfig, CandleRgcnRequest,
    CandleTrainerConfig, CandleTrainerError, CandleTrainerRequest,
};
use phoenix_graph_research::*;
use std::path::{Path, PathBuf};
use tempfile::TempDir;

#[test]
fn rgcn_beats_the_frozen_dense_baseline_and_restarts_exactly() {
    let fixture = Fixture::new(64, 16, 8);
    let (baseline_ledger, baseline_manifest) = fixture.freeze_selected_baseline();
    let request = CandleRgcnRequest {
        authority: fixture.request.clone(),
        baseline_ledger,
        baseline_manifest,
        config: CandleRgcnConfig {
            epochs: 80,
            learning_rate: 0.5,
            l2: 0.0001,
        },
    };
    let first = train_candle_rgcn16(&request).expect("first R-GCN training execution");
    let second = train_candle_rgcn16(&request).expect("deterministic R-GCN rerun");

    assert!(first.report.beats_frozen_baseline);
    assert!(first.report.restart_score_bits_exact);
    assert_eq!(first.artifact, second.artifact);
    assert_eq!(first.report.model_id, second.report.model_id);
    assert_eq!(first.report.weights_blake3, second.report.weights_blake3);
    assert_eq!(first.report.rgcn_validation, second.report.rgcn_validation);
    assert_eq!(first.report.rgcn_ranking, second.report.rgcn_ranking);
    assert!(first.report.allocation_volume_bytes > first.report.staging.staged_bytes);
    assert!(first.report.allocation_count > 0);
    assert!(first.report.source_mmap_bytes > 0);
    assert!(first.report.restart_weight_mmap_bytes > 0);
    assert_eq!(
        first.report.mmap_bytes,
        first.report.source_mmap_bytes + first.report.restart_weight_mmap_bytes
    );
    assert!(
        first.report.restart_open_and_score_micros.saturating_mul(2) < first.report.training_micros
    );
    assert!(
        first.report.rgcn_validation.average_precision
            > first.report.baseline_validation.average_precision
            || first.report.rgcn_validation.brier_score
                < first.report.baseline_validation.brier_score
    );
    assert_eq!(first.report.staging.source_edges, 88);
    assert_eq!(first.report.staging.train_message_edges, 304);
    assert_eq!(first.report.staging.incidence_rows_validated, 88);
    assert_eq!(first.report.staging.train_queries, 128);
    assert_eq!(first.report.staging.validation_queries, 32);
    assert!(!first.report.staging.frozen_relation_batch_required);
    eprintln!(
        "R-GCN rung: baseline AP={:?} brier={:.6}, R-GCN AP={:?} brier={:.6}, stage={}us train={}us restart={}us mmap={}B staged={}B alloc={}B",
        first.report.baseline_validation.average_precision,
        first.report.baseline_validation.brier_score,
        first.report.rgcn_validation.average_precision,
        first.report.rgcn_validation.brier_score,
        first.report.staging.staging_micros,
        first.report.training_micros,
        first.report.restart_open_and_score_micros,
        first.report.mmap_bytes,
        first.report.staging.staged_bytes,
        first.report.allocation_volume_bytes,
    );

    let model = FrozenModelMapped::open(&first.artifact.manifest).expect("restart model");
    assert_eq!(
        model.manifest().architecture.family,
        FrozenModelFamily::Rgcn16
    );
    assert_eq!(model.manifest().training.training_executions, 1);
    assert!(model.manifest().training.test_locked_during_selection);
    assert!(model
        .manifest()
        .score_certificates
        .iter()
        .all(|certificate| certificate.split == ResearchSplit::Validation));

    let mut different_seed = request;
    different_seed.authority.selected_repeat = 1;
    let different = train_candle_rgcn16(&different_seed).expect("different R-GCN seed");
    assert_ne!(first.report.model_id, different.report.model_id);
    assert_ne!(first.report.weights_blake3, different.report.weights_blake3);
}

#[test]
fn typed_coo_staging_is_bounded_without_a_frozen_relation_batch() {
    let fixture = Fixture::new(20_000, 2_000, 1_000);
    let tensor = FrozenTensorMapped::open(&fixture.request.tensor_manifest).expect("mapped tensor");
    let topology = TrainTopologyFeatureMapped::open(&fixture.request.topology_manifest)
        .expect("mapped topology");
    let staged = stage_rgcn_input(&tensor, &topology).expect("stage typed COO");

    assert_eq!(staged.profile.source_edges, 23_000);
    assert_eq!(staged.profile.train_message_edges, 86_000);
    assert_eq!(staged.profile.incidence_rows_validated, 23_000);
    assert_eq!(staged.profile.train_queries, 40_000);
    assert_eq!(staged.profile.validation_queries, 4_000);
    assert_eq!(staged.profile.staged_bytes, 1_880_004);
    assert!(!staged.profile.frozen_relation_batch_required);
    assert!(staged.profile.staging_micros < 2_000_000);
    eprintln!(
        "R-GCN typed COO staging: {} edges, {} messages, {} bytes, {}us",
        staged.profile.source_edges,
        staged.profile.train_message_edges,
        staged.profile.staged_bytes,
        staged.profile.staging_micros
    );
}

#[test]
fn rgcn_fails_before_training_on_corruption_or_baseline_source_drift() {
    let corrupt = Fixture::new(16, 4, 2);
    let (ledger, manifest) = corrupt.freeze_selected_baseline();
    let mut bytes = std::fs::read(&corrupt.tensor_binary).expect("tensor binary");
    *bytes.last_mut().expect("nonempty tensor binary") ^= 0x80;
    std::fs::write(&corrupt.tensor_binary, bytes).expect("corrupt tensor");
    let request = CandleRgcnRequest {
        authority: corrupt.request.clone(),
        baseline_ledger: ledger,
        baseline_manifest: manifest,
        config: CandleRgcnConfig::default(),
    };
    assert!(matches!(
        train_candle_rgcn16(&request),
        Err(CandleTrainerError::Graph(
            FrozenGraphResearchError::CorruptArtifact("tensor binary digest")
        ))
    ));

    let baseline_source = Fixture::new(16, 4, 2);
    let (ledger, manifest) = baseline_source.freeze_selected_baseline();
    let different_source = Fixture::new(17, 4, 2);
    let request = CandleRgcnRequest {
        authority: different_source.request.clone(),
        baseline_ledger: ledger,
        baseline_manifest: manifest,
        config: CandleRgcnConfig::default(),
    };
    assert!(matches!(
        train_candle_rgcn16(&request),
        Err(CandleTrainerError::Contract("frozen baseline authority"))
    ));
}

struct Fixture {
    _root: TempDir,
    request: CandleTrainerRequest,
    tensor_binary: PathBuf,
    validation_features: Vec<[f32; PROPOSAL_FEATURE_DIM]>,
    validation_labels: Vec<bool>,
    test_features: Vec<[f32; PROPOSAL_FEATURE_DIM]>,
    test_labels: Vec<bool>,
}

impl Fixture {
    fn new(train: u32, validation: u32, test: u32) -> Self {
        let root = tempfile::tempdir().expect("fixture root");
        let input = root.path().join("input");
        let output = root.path().join("output");
        std::fs::create_dir_all(&input).expect("input directory");
        std::fs::create_dir_all(&output).expect("output directory");
        let dataset_id = digest(b"candle-rgcn-dataset-v1");
        let tensor_id =
            digest(format!("candle-rgcn-tensor-v1-{train}-{validation}-{test}").as_bytes());
        let graph = FrozenGraphResearchSnapshot {
            dataset_id: dataset_id.clone(),
            checkpoint_id: "candle-rgcn-checkpoint-v1".into(),
            checkpoint_generation: 4,
            frozen_at_ms: 300,
            split_policy: split_policy(),
            nodes: Vec::new(),
            edges: Vec::new(),
            incidences: Vec::new(),
            proposals: Vec::new(),
        };
        let graph_paths = FrozenGraphResearchBundle::write(&graph, &input).expect("frozen graph");
        let tensor = graph_tensor(
            dataset_id.clone(),
            tensor_id.clone(),
            train,
            validation,
            test,
        );
        let tensor_paths = FrozenTensorBundle::write(&tensor, &input).expect("frozen tensor");
        let mut protocol = protocol(dataset_id.clone(), tensor_id.clone());
        let protocol_path = write_protocol(&mut protocol, &input);
        let rows = zero_feature_rows(train, validation, test);
        let topology = TrainTopologyFeatureSnapshot {
            schema_version: TRAIN_TOPOLOGY_FEATURE_SCHEMA.into(),
            derivation_id: digest(
                format!("candle-rgcn-topology-v1-{train}-{validation}-{test}").as_bytes(),
            ),
            source_dataset_id: dataset_id,
            source_tensor_id: tensor_id,
            evaluation_protocol_id: protocol.protocol_id,
            policy: TrainTopologyFeaturePolicy {
                incidence_negatives_per_positive: 1,
            },
            audit: TrainTopologyAudit {
                fit_edges: u64::from(train),
                fit_incidences: u64::from(train + validation + test),
                link_examples: rows.len() as u64,
                incidence_examples: 0,
                latest_fit_edge_ms: Some(50),
                topology_blake3: digest(b"candle-rgcn-asserted-topology-v1"),
                train_only: true,
                asserted_edges_only: true,
                resolved_incidences_only: true,
                leave_one_positive_out: true,
            },
            feature_certificates: Vec::new(),
            link_rows: rows,
            incidence_rows: Vec::new(),
        };
        let topology_paths =
            TrainTopologyFeatureBundle::write(&topology, &input).expect("train topology");
        Self {
            _root: root,
            request: CandleTrainerRequest {
                graph_manifest: graph_paths.manifest,
                tensor_manifest: tensor_paths.manifest,
                evaluation_protocol: protocol_path,
                topology_manifest: topology_paths.manifest,
                output_root: output,
                selected_repeat: 0,
                config: CandleTrainerConfig {
                    epochs: 4,
                    batch_size: 64,
                    learning_rate: 0.04,
                    l2: 0.0005,
                },
            },
            tensor_binary: tensor_paths.binary,
            validation_features: vec![[0.0; PROPOSAL_FEATURE_DIM]; validation as usize * 2],
            validation_labels: alternating_labels(validation),
            test_features: vec![[0.0; PROPOSAL_FEATURE_DIM]; test as usize * 2],
            test_labels: alternating_labels(test),
        }
    }

    fn freeze_selected_baseline(&self) -> (PathBuf, PathBuf) {
        let mut manifests = Vec::with_capacity(3);
        for selected_repeat in 0..3 {
            let mut request = self.request.clone();
            request.selected_repeat = selected_repeat;
            manifests.push(
                train_candle_mlp16(&request)
                    .expect("baseline seed execution")
                    .artifact
                    .manifest,
            );
        }
        let policy = FrozenModelSelectionPolicy {
            task_id: "typed-link-binary-selection/v1".into(),
            evaluator_schema: RESEARCH_EVALUATION_SCHEMA.into(),
            calibration_bins: 10,
        };
        let selection = select_frozen_models(
            &manifests,
            policy,
            FrozenBinaryEvaluationSet {
                features: &self.validation_features,
                labels: &self.validation_labels,
            },
        )
        .expect("select frozen baseline");
        let selected_id = selection.selected_validation_model_id().to_owned();
        let selected_manifest = manifests
            .iter()
            .find(|path| {
                FrozenModelMapped::open(path)
                    .map(|model| model.manifest().model_id == selected_id)
                    .unwrap_or(false)
            })
            .expect("selected baseline manifest")
            .clone();
        let finalized = finalize_frozen_model_selection(
            selection,
            FrozenBinaryEvaluationSet {
                features: &self.test_features,
                labels: &self.test_labels,
            },
            &self.request.output_root,
        )
        .expect("finalize baseline selection ledger");
        (finalized.paths.ledger, selected_manifest)
    }
}

fn alternating_labels(queries: u32) -> Vec<bool> {
    (0..queries).flat_map(|_| [true, false]).collect::<Vec<_>>()
}

fn graph_tensor(
    dataset_id: CompactString,
    tensor_id: CompactString,
    train: u32,
    validation: u32,
    test: u32,
) -> FrozenTensorSnapshot {
    let queries = train + validation + test;
    let nodes = queries * 3 + 1;
    let mut node_ids = Vec::with_capacity(nodes as usize);
    let mut node_types = Vec::with_capacity(nodes as usize);
    let mut node_splits = Vec::with_capacity(nodes as usize);
    let mut node_times = Vec::with_capacity(nodes as usize);
    for family in 0..3_u32 {
        for query in 0..queries {
            node_ids.push(format_compact!("node-{family}-{query}"));
            node_types.push(u32::from(family != 0));
            node_splits.push(ResearchSplit::Train);
            node_times.push(50);
        }
    }
    node_ids.push("topology-anchor".into());
    node_types.push(2);
    node_splits.push(ResearchSplit::Train);
    node_times.push(50);
    let mut edge_splits = Vec::with_capacity(queries as usize);
    let mut edge_times = Vec::with_capacity(queries as usize);
    let mut negatives = Vec::with_capacity(queries as usize);
    for query in 0..queries {
        let split = query_split(query, train, validation);
        edge_splits.push(split);
        edge_times.push(split_time(split));
        negatives.push(TypedNegativeSample {
            positive_edge: query,
            source: query,
            target: queries * 2 + query,
            relation_type: 0,
            split,
        });
    }
    let mut offsets = Vec::with_capacity(nodes as usize + 1);
    offsets.push(0);
    for node in 0..nodes {
        let offset = if node < queries { node + 1 } else { queries };
        offsets.push(u64::from(offset));
    }
    let positive_targets = (0..queries)
        .map(|query| queries + query)
        .collect::<Vec<_>>();
    FrozenTensorSnapshot {
        tensor_id,
        source_dataset_id: dataset_id,
        policy: TensorizationPolicy {
            negatives_per_asserted_edge: 1,
        },
        node_ids,
        node_type_vocabulary: vec!["source".into(), "candidate".into(), "anchor".into()],
        relation_vocabulary: vec!["connects".into()],
        role_vocabulary: vec!["topology-marker".into()],
        feature_schema_vocabulary: Vec::new(),
        node_type_ids: node_types,
        node_authority: vec![ResearchAuthority::Asserted; nodes as usize],
        node_splits,
        node_available_at_ms: node_times,
        coo_sources: (0..queries).collect(),
        coo_targets: positive_targets.clone(),
        coo_relation_types: vec![0; queries as usize],
        coo_authority: vec![ResearchAuthority::Asserted; queries as usize],
        coo_splits: edge_splits,
        coo_available_at_ms: edge_times,
        coo_weights: vec![1.0; queries as usize],
        csr_row_offsets: offsets,
        csr_columns: positive_targets.clone(),
        csr_edge_indices: (0..queries).collect(),
        incidence_hyperedges: vec![queries * 3; queries as usize],
        incidence_participants: positive_targets,
        incidence_role_types: vec![0; queries as usize],
        incidence_splits: vec![ResearchSplit::Train; queries as usize],
        incidence_resolved: vec![true; queries as usize],
        proposal_features: Vec::new(),
        proposal_labels: Vec::new(),
        proposal_label_observed: Vec::new(),
        proposal_splits: Vec::new(),
        proposal_observed_at_ms: Vec::new(),
        proposal_label_available_at_ms: Vec::new(),
        proposal_feature_schema_ids: Vec::new(),
        feature_certificates: Vec::new(),
        negatives,
    }
}

fn zero_feature_rows(train: u32, validation: u32, test: u32) -> Vec<DerivedFeatureRow> {
    let queries = train + validation + test;
    let mut rows = Vec::with_capacity(queries as usize * 2);
    for query in 0..queries {
        let split = query_split(query, train, validation);
        rows.push(DerivedFeatureRow {
            positive_index: query,
            candidate: queries + query,
            split,
            label: true,
            features: [0.0; PROPOSAL_FEATURE_DIM],
        });
        rows.push(DerivedFeatureRow {
            positive_index: query,
            candidate: queries * 2 + query,
            split,
            label: false,
            features: [0.0; PROPOSAL_FEATURE_DIM],
        });
    }
    rows
}

fn query_split(query: u32, train: u32, validation: u32) -> ResearchSplit {
    if query < train {
        ResearchSplit::Train
    } else if query < train + validation {
        ResearchSplit::Validation
    } else {
        ResearchSplit::Test
    }
}

fn split_time(split: ResearchSplit) -> i64 {
    match split {
        ResearchSplit::Train => 50,
        ResearchSplit::Validation => 150,
        ResearchSplit::Test => 250,
    }
}

fn split_policy() -> TemporalSplitPolicy {
    TemporalSplitPolicy {
        train_through_ms: 100,
        validation_through_ms: 200,
    }
}

fn protocol(dataset_id: CompactString, tensor_id: CompactString) -> ResearchEvaluationProtocol {
    let seeds = [13_u64, 31, 53];
    ResearchEvaluationProtocol {
        schema_version: RESEARCH_EVALUATION_SCHEMA.into(),
        protocol_id: "pending".into(),
        tensor_id,
        source_dataset_id: dataset_id,
        split_policy: split_policy(),
        policy: EvaluationPolicy {
            feature_schema_id: "train-topology-link-v1".into(),
            seed_root: seeds[0],
            repeats: seeds.len() as u16,
            calibration_bins: 10,
            ftrl: FtrlConfig::default(),
            mlp: MlpConfig::default(),
        },
        seed_certificate: SeedCertificate {
            namespace: "candle-rgcn-test".into(),
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
            feature_columns_checked: PROPOSAL_FEATURE_DIM as u64,
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
    protocol.protocol_id = digest(&serde_json::to_vec(protocol).expect("protocol identity"));
    let path = root.join(format!("{}.evaluation.json", protocol.protocol_id));
    std::fs::write(
        &path,
        serde_json::to_vec_pretty(protocol).expect("encode protocol"),
    )
    .expect("write protocol");
    path
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
