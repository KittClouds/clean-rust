use compact_str::CompactString;
use phoenix_candle_baseline_trainer::{
    evaluate_temporal_rgcn_restart, train_candle_temporal_rgcn16, train_temporal_compgcn16,
    CandleTemporalRgcnRequest, TemporalCompgcnRequest, TemporalRgcnEvaluatorRequest,
};
use phoenix_graph_research::{
    build_canonical_link_prediction_task, encode_temporal_rgcn, stage_temporal_rgcn,
    ExternalDatasetBundle, ExternalDatasetKind, ExternalDatasetMapped, ExternalDatasetSnapshot,
    ExternalFact, ExternalFactSplit, ExternalSourceFile, ExternalSplitPolicy,
    LinkPredictionQueryView, LinkPredictionSplit, LinkPredictionTaskMapped, TemporalCompgcnConfig,
    TemporalComposition, TemporalRelationUpdate, TemporalRgcnConfig, TemporalRgcnError,
    TemporalRgcnMapped,
};
use std::io::{Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

#[test]
fn temporal_rgcn_trains_deterministically_and_restarts_without_test_access() {
    let root = tempfile::tempdir().expect("root");
    let (source_manifest, task_manifest) = fixture(root.path());
    let request = CandleTemporalRgcnRequest {
        source_manifest,
        task_manifest,
        output_root: root.path().join("first-model"),
        config: TemporalRgcnConfig {
            epochs: 3,
            learning_rate: 0.08,
            l2: 0.000_01,
            negatives_per_positive: 1,
            residual_scale: 0.01,
            seed: 17,
        },
    };
    let first = train_candle_temporal_rgcn16(&request).expect("first training");
    let mut second_request = request.clone();
    second_request.output_root = root.path().join("second-model");
    let second = train_candle_temporal_rgcn16(&second_request).expect("second training");
    assert_eq!(first.report.model_id, second.report.model_id);
    assert_eq!(first.report.weights_blake3, second.report.weights_blake3);
    assert_eq!(first.report.validation, second.report.validation);
    assert!(first.report.restart_witness_bits_exact);
    assert_eq!(first.report.epoch_allocation_volume_bytes, 0);
    assert_eq!(first.report.epoch_allocation_count, 0);
    assert_eq!(first.report.evaluation_query_batch, 64);
    assert_eq!(first.report.evaluation_query_tile, 4);
    assert_eq!(first.report.evaluation_candidate_tile, 4_096);
    assert_eq!(first.report.evaluation_canonical_score_arena_bytes, 64 * 32);
    assert_eq!(first.report.evaluation_duplicate_score_arena_bytes, 0);
    assert!(first.report.baseline_validation_micros > 0);
    assert_eq!(
        first.report.training_allocation_volume_bytes,
        first.report.training_parameter_bytes + first.report.training_gradient_arena_bytes
    );
    assert_eq!(first.report.training_allocation_count, 12);
    assert!(first.report.staging.train_only);
    assert_eq!(first.report.staging.train_facts, 8);
    assert_eq!(first.report.staging.directed_messages, 16);
    assert_eq!(first.report.staging.training_examples, 32);
    assert_eq!(first.report.validation.queries, 3);
    assert_eq!(first.report.validation.positives, 4);
    assert_eq!(first.report.validation.candidates_scored, 12);
    assert!(
        first.report.validation.mean_reciprocal_rank > first.report.baseline.mean_reciprocal_rank
    );
    assert!(!root
        .path()
        .join("first-model")
        .join("test-results")
        .exists());
    let mapped = TemporalRgcnMapped::open(&first.artifact.manifest).expect("restart model");
    assert_eq!(mapped.manifest().model_id, first.report.model_id);
    assert_eq!(mapped.manifest().validation, first.report.validation);
    let source = ExternalDatasetMapped::open(&request.source_manifest).expect("source");
    let task = LinkPredictionTaskMapped::open(&request.task_manifest).expect("task");
    let staged = stage_temporal_rgcn(&source, &task, request.config).expect("stage");
    let encoded = encode_temporal_rgcn(&mapped, &staged).expect("encode");
    let candidates = (0..task.manifest().candidate_universe).collect::<Vec<_>>();
    let queries = (0..11_u32)
        .map(|index| {
            let relation = index % task.manifest().derived_relation_count;
            LinkPredictionQueryView {
                observed_at: i64::from(index + 1),
                source: index % task.manifest().candidate_universe,
                relation,
                split: LinkPredictionSplit::Validation,
                inverse: relation >= task.manifest().base_relation_count,
            }
        })
        .collect::<Vec<_>>();
    let mut reference = vec![0.0_f32; queries.len() * candidates.len()];
    for (query, row) in queries
        .iter()
        .copied()
        .zip(reference.chunks_exact_mut(candidates.len()))
    {
        encoded
            .score_candidates(query, &candidates, row)
            .expect("query-major score");
    }
    let mut tiled = vec![0.0_f32; reference.len()];
    encoded
        .score_candidate_batch(&queries, &candidates, &mut tiled)
        .expect("tiled score");
    assert_eq!(
        tiled
            .iter()
            .map(|score| score.to_bits())
            .collect::<Vec<_>>(),
        reference
            .iter()
            .map(|score| score.to_bits())
            .collect::<Vec<_>>()
    );
    let evaluator = evaluate_temporal_rgcn_restart(&TemporalRgcnEvaluatorRequest {
        source_manifest: request.source_manifest.clone(),
        task_manifest: request.task_manifest.clone(),
        model_manifest: first.artifact.manifest.clone(),
    })
    .expect("restart evaluator");
    assert!(evaluator.certificate_exact);
    assert_eq!(evaluator.validation, first.report.validation);
    assert_eq!(evaluator.query_batch, 64);
    assert_eq!(evaluator.query_tile, 4);
    assert_eq!(evaluator.candidate_tile, 4_096);
    let padded_candidates = u64::from(task.manifest().candidate_universe).div_ceil(8) * 8;
    assert_eq!(evaluator.candidate_plane_bytes, padded_candidates * 16 * 4);
    assert_eq!(evaluator.evaluation_profile.batches, 1);
    assert!(
        evaluator.evaluation_profile.evaluator_micros
            >= evaluator.evaluation_profile.hash_rank_join_micros
    );
    assert!(evaluator.evaluation_micros >= evaluator.evaluation_profile.evaluator_micros);
    assert_eq!(evaluator.canonical_score_arena_bytes, 64 * 32);
    assert_eq!(evaluator.duplicate_score_arena_bytes, 0);

    let mut different = request;
    different.output_root = root.path().join("different-model");
    different.config.seed = 29;
    let different = train_candle_temporal_rgcn16(&different).expect("different seed");
    assert_ne!(first.report.model_id, different.report.model_id);
    assert_ne!(first.report.weights_blake3, different.report.weights_blake3);

    let mut weights = std::fs::OpenOptions::new()
        .write(true)
        .open(first.artifact.weights)
        .expect("weights");
    weights.seek(SeekFrom::Start(8)).expect("seek");
    weights.write_all(&[0xff]).expect("corrupt");
    weights.sync_all().expect("sync");
    assert!(matches!(
        TemporalRgcnMapped::open(first.artifact.manifest),
        Err(TemporalRgcnError::CorruptArtifact("weights identity"))
    ));
}

#[test]
fn temporal_compgcn_rejects_a_non_winning_candidate_without_artifact() {
    let root = tempfile::tempdir().expect("root");
    let (source_manifest, task_manifest) = fixture(root.path());
    let base = TemporalRgcnConfig {
        epochs: 12,
        learning_rate: 0.08,
        l2: 0.000_01,
        negatives_per_positive: 1,
        residual_scale: 0.01,
        seed: 17,
    };
    let control = train_candle_temporal_rgcn16(&CandleTemporalRgcnRequest {
        source_manifest: source_manifest.clone(),
        task_manifest: task_manifest.clone(),
        output_root: root.path().join("control"),
        config: base,
    })
    .expect("control");
    let request = TemporalCompgcnRequest {
        source_manifest,
        task_manifest,
        control_manifest: control.artifact.manifest.clone(),
        output_root: root.path().join("compgcn-a"),
        config: TemporalCompgcnConfig {
            base,
            composition: TemporalComposition::Multiply,
            relation_update: TemporalRelationUpdate::JointLinear,
        },
    };
    let error = train_temporal_compgcn16(&request).expect_err("fixture must retain control");
    match error {
        phoenix_candle_baseline_trainer::CandleTrainerError::TemporalCompgcnCandidate {
            candidate_mrr,
            control_mrr,
            score_blake3,
            receipt,
        } => {
            assert!(candidate_mrr <= control_mrr);
            assert!(score_blake3.starts_with("b3-"));
            let first: phoenix_candle_baseline_trainer::TemporalCompgcnCandidateReceipt =
                serde_json::from_slice(&std::fs::read(&receipt).expect("candidate receipt"))
                    .expect("candidate receipt JSON");
            let mut repeat = request.clone();
            repeat.output_root = root.path().join("compgcn-b");
            let repeat_error =
                train_temporal_compgcn16(&repeat).expect_err("repeat must retain control");
            let repeat_receipt = match repeat_error {
                phoenix_candle_baseline_trainer::CandleTrainerError::TemporalCompgcnCandidate {
                    receipt,
                    ..
                } => receipt,
                other => panic!("unexpected repeat result: {other}"),
            };
            let second: phoenix_candle_baseline_trainer::TemporalCompgcnCandidateReceipt =
                serde_json::from_slice(
                    &std::fs::read(&repeat_receipt).expect("repeat candidate receipt"),
                )
                .expect("repeat candidate receipt JSON");
            assert_eq!(first.model_id, second.model_id);
            assert_eq!(first.weights_blake3, second.weights_blake3);
            assert_eq!(first.validation, second.validation);
            assert!(!first.accepted);
        }
        other => panic!("unexpected CompGCN result: {other}"),
    }
    assert!(!std::fs::read_dir(&request.output_root)
        .expect("candidate directory")
        .any(|entry| {
            let path = entry.expect("candidate entry").path();
            matches!(
                path.extension().and_then(|value| value.to_str()),
                Some("tcw")
            ) || path
                .file_name()
                .and_then(|value| value.to_str())
                .is_some_and(|value| value.ends_with(".temporal-compgcn.json"))
        }));
}

fn fixture(root: &Path) -> (PathBuf, PathBuf) {
    let validation = vec![
        entry(8, 0, 0, &[1, 2]),
        entry(8, 1, 2, &[0]),
        entry(8, 2, 2, &[0]),
    ];
    let test = vec![entry(10, 1, 1, &[3]), entry(10, 3, 3, &[1])];
    let validation_pickle = encode_pickle(&validation);
    let test_pickle = encode_pickle(&test);
    std::fs::write(root.join("tkgl-smallpedia_val_ns.pkl"), &validation_pickle)
        .expect("validation pickle");
    std::fs::write(root.join("tkgl-smallpedia_test_ns.pkl"), &test_pickle).expect("test pickle");
    let mut facts = Vec::new();
    for cycle in 0..2_i64 {
        facts.extend([
            fact(0, 0, 1, cycle * 4 + 1, ExternalFactSplit::Train),
            fact(1, 1, 2, cycle * 4 + 2, ExternalFactSplit::Train),
            fact(2, 0, 3, cycle * 4 + 3, ExternalFactSplit::Train),
            fact(3, 1, 0, cycle * 4 + 4, ExternalFactSplit::Train),
        ]);
    }
    facts.extend([
        fact(0, 0, 1, 8, ExternalFactSplit::Validation),
        fact(0, 0, 2, 8, ExternalFactSplit::Validation),
        fact(1, 1, 3, 10, ExternalFactSplit::Test),
    ]);
    let source = ExternalDatasetBundle::write(
        &ExternalDatasetSnapshot {
            name: "tkgl-smallpedia".into(),
            kind: ExternalDatasetKind::TemporalKnowledgeGraph,
            upstream_url: "fixture".into(),
            upstream_version: "fixture-v1".into(),
            license_notice: "fixture".into(),
            split_policy: ExternalSplitPolicy::TemporalQuantile {
                train_through: 7,
                validation_through: 9,
                validation_basis_points: 1_500,
                test_basis_points: 1_500,
            },
            source_files: vec![
                receipt("tkgl-smallpedia_val_ns.pkl", &validation_pickle),
                receipt("tkgl-smallpedia_test_ns.pkl", &test_pickle),
            ],
            entities: ["E0", "E1", "E2", "E3"].map(CompactString::from).to_vec(),
            relations: ["R0", "R1"].map(CompactString::from).to_vec(),
            facts,
            qualifiers: Vec::new(),
        },
        root.join("source"),
    )
    .expect("source");
    let mapped = ExternalDatasetMapped::open(&source.manifest).expect("mapped source");
    let task = build_canonical_link_prediction_task(&mapped, root, root.join("task"))
        .expect("canonical task");
    (source.manifest, task.manifest)
}

fn fact(
    subject: u32,
    predicate: u32,
    object: u32,
    observed_at: i64,
    split: ExternalFactSplit,
) -> ExternalFact {
    ExternalFact {
        subject,
        predicate,
        object,
        qualifier_offset: 0,
        qualifier_count: 0,
        observed_at: Some(observed_at),
        split,
        is_static: false,
    }
}

struct Entry {
    time: i64,
    source: u32,
    relation: u32,
    destinations: Vec<u32>,
}

fn entry(time: i64, source: u32, relation: u32, destinations: &[u32]) -> Entry {
    Entry {
        time,
        source,
        relation,
        destinations: destinations.to_vec(),
    }
}

fn receipt(name: &str, bytes: &[u8]) -> ExternalSourceFile {
    ExternalSourceFile {
        logical_name: name.into(),
        blake3: format!("b3-{}", blake3::hash(bytes).to_hex()).into(),
        bytes: bytes.len() as u64,
        role: "officialNegatives".into(),
    }
}

fn encode_pickle(entries: &[Entry]) -> Vec<u8> {
    let mut bytes = vec![0x80, 5, b'}', b'('];
    for entry in entries {
        encode_scalar(&mut bytes, entry.time);
        encode_scalar(&mut bytes, i64::from(entry.source));
        encode_scalar(&mut bytes, i64::from(entry.relation));
        bytes.push(0x87);
        encode_array(&mut bytes, &entry.destinations);
    }
    bytes.extend_from_slice(b"u.");
    bytes
}

fn encode_scalar(bytes: &mut Vec<u8>, value: i64) {
    encode_global(bytes, "numpy.core.multiarray", "scalar");
    encode_dtype(bytes);
    bytes.extend_from_slice(&[b'C', 8]);
    bytes.extend_from_slice(&value.to_le_bytes());
    bytes.extend_from_slice(&[0x86, b'R']);
}

fn encode_array(bytes: &mut Vec<u8>, values: &[u32]) {
    encode_global(bytes, "numpy.core.numeric", "_frombuffer");
    bytes.push(b'(');
    bytes.push(0x96);
    bytes.extend_from_slice(&((values.len() * 8) as u64).to_le_bytes());
    for value in values {
        bytes.extend_from_slice(&i64::from(*value).to_le_bytes());
    }
    encode_dtype(bytes);
    bytes.extend_from_slice(&[b'K', values.len() as u8, 0x85]);
    encode_string(bytes, "C");
    bytes.extend_from_slice(b"tR");
}

fn encode_dtype(bytes: &mut Vec<u8>) {
    encode_global(bytes, "numpy", "dtype");
    encode_string(bytes, "i8");
    bytes.extend_from_slice(&[0x89, 0x88, 0x87, b'R']);
}

fn encode_global(bytes: &mut Vec<u8>, module: &str, name: &str) {
    encode_string(bytes, module);
    encode_string(bytes, name);
    bytes.push(0x93);
}

fn encode_string(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&[0x8c, value.len() as u8]);
    bytes.extend_from_slice(value.as_bytes());
}
