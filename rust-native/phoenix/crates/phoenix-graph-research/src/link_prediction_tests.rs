use crate::link_prediction_artifact::write_link_prediction_task;
use crate::tgb_pickle::{parse_tgb_conflict_pickle, TgbConflictEntry};
use crate::{
    build_canonical_link_prediction_task, create_link_prediction_test_lock,
    evaluate_link_prediction_validation, evaluate_link_prediction_validation_batched,
    evaluate_link_prediction_validation_batched_profiled,
    evaluate_link_prediction_validation_canonical_batched,
    evaluate_link_prediction_validation_canonical_batched_profiled,
    evaluate_locked_link_prediction_test, evaluate_locked_link_prediction_test_batched,
    ExternalDatasetBundle, ExternalDatasetKind, ExternalDatasetMapped, ExternalDatasetSnapshot,
    ExternalFact, ExternalFactSplit, ExternalSourceFile, ExternalSplitPolicy, LinkPredictionError,
    LinkPredictionQuery, LinkPredictionScoreCertificate, LinkPredictionSplit,
    LinkPredictionTaskMapped, LinkPredictionTaskSnapshot, LinkPredictionTestLockInput,
};
use compact_str::CompactString;
use std::io::{Seek, SeekFrom, Write};
use std::path::Path;
use std::time::{Duration, Instant};

#[test]
fn official_conflicts_build_deterministic_compact_mmap_task() {
    let first = tempfile::tempdir().expect("first");
    let second = tempfile::tempdir().expect("second");
    let first_source = write_source_fixture(first.path(), false);
    let second_source = write_source_fixture(second.path(), false);
    let first_mapped = ExternalDatasetMapped::open(first_source).expect("first source");
    let second_mapped = ExternalDatasetMapped::open(second_source).expect("second source");
    let first_paths = build_canonical_link_prediction_task(
        &first_mapped,
        first.path(),
        first.path().join("task"),
    )
    .expect("first task");
    let second_paths = build_canonical_link_prediction_task(
        &second_mapped,
        second.path(),
        second.path().join("task"),
    )
    .expect("second task");
    assert_eq!(first_paths.task_id, second_paths.task_id);
    let task = LinkPredictionTaskMapped::open(first_paths.manifest).expect("open task");
    assert_eq!(task.manifest().candidate_universe, 4);
    assert_eq!(task.manifest().base_relation_count, 2);
    assert_eq!(task.manifest().derived_relation_count, 4);
    assert_eq!(task.manifest().validation_queries, 5);
    assert_eq!(task.manifest().validation_positives, 6);
    assert_eq!(task.manifest().test_queries, 3);
    assert_eq!(task.manifest().test_positives, 4);
    assert_eq!(task.manifest().inverse_queries, 5);
    assert!(task.manifest().binary_bytes < 1_000);
}

#[test]
fn official_negative_parity_fails_before_task_installation() {
    let root = tempfile::tempdir().expect("root");
    let source_manifest = write_source_fixture(root.path(), true);
    let source = ExternalDatasetMapped::open(source_manifest).expect("source");
    let output = root.path().join("task");
    assert!(matches!(
        build_canonical_link_prediction_task(&source, root.path(), &output),
        Err(LinkPredictionError::NegativeParity(
            LinkPredictionSplit::Validation
        ))
    ));
    assert!(!output.exists());
}

#[test]
fn simd_filtered_average_ties_match_tgb_semantics() {
    let root = tempfile::tempdir().expect("root");
    let task = direct_task(root.path());
    let certificate =
        evaluate_link_prediction_validation(&task, "model-b3", |_query, candidates, scores| {
            assert_eq!(candidates, &[0, 1, 2, 3]);
            scores.copy_from_slice(&[0.0, 2.0, 2.0, 4.0]);
            Ok(())
        })
        .expect("score");
    assert_eq!(certificate.queries, 1);
    assert_eq!(certificate.positives, 2);
    assert_eq!(certificate.candidates_scored, 4);
    assert_eq!(certificate.mean_reciprocal_rank, 0.5);
    assert_eq!(certificate.hits_at_1, 0.0);
    assert_eq!(certificate.hits_at_3, 1.0);
    assert_eq!(certificate.hits_at_10, 1.0);
}

#[test]
fn bounded_batched_evaluator_is_certificate_exact() {
    let root = tempfile::tempdir().expect("root");
    let source_manifest = write_source_fixture(root.path(), false);
    let source = ExternalDatasetMapped::open(source_manifest).expect("source");
    let paths = build_canonical_link_prediction_task(
        &source,
        root.path(),
        root.path().join("batched-task"),
    )
    .expect("task");
    let task = LinkPredictionTaskMapped::open(paths.manifest).expect("open task");
    let serial =
        evaluate_link_prediction_validation(&task, "batched-model", |query, candidates, scores| {
            score_fixture(query, candidates, scores);
            Ok(())
        })
        .expect("serial");
    let batched = evaluate_link_prediction_validation_batched(
        &task,
        "batched-model",
        3,
        |queries, candidates, scores| {
            for (query, row) in queries
                .iter()
                .copied()
                .zip(scores.chunks_exact_mut(candidates.len()))
            {
                score_fixture(query, candidates, row);
            }
            Ok(())
        },
    )
    .expect("batched");
    assert_eq!(batched, serial);
    let profiled = evaluate_link_prediction_validation_batched_profiled(
        &task,
        "batched-model",
        3,
        |queries, candidates, scores| {
            for (query, row) in queries
                .iter()
                .copied()
                .zip(scores.chunks_exact_mut(candidates.len()))
            {
                score_fixture(query, candidates, row);
            }
            Ok(())
        },
    )
    .expect("profiled");
    assert_eq!(profiled.certificate, serial);
    assert_eq!(profiled.profile.batches, 2);
    assert!(profiled.profile.evaluator_micros >= profiled.profile.hash_rank_join_micros);
    let canonical = evaluate_link_prediction_validation_canonical_batched_profiled(
        &task,
        "batched-model",
        3,
        |queries, candidates, mut matrix| {
            for (row, query) in queries.iter().copied().enumerate() {
                score_fixture(
                    query,
                    candidates,
                    matrix.row_mut(row).expect("canonical score row"),
                );
            }
            Ok(())
        },
    )
    .expect("canonical");
    assert_eq!(canonical.certificate, serial);
    assert_eq!(canonical.profile.batches, 2);
    assert_eq!(canonical.profile.stream_composition_micros, 0);
    assert!(canonical.profile.evaluator_micros >= canonical.profile.hash_rank_join_micros);
    assert!(matches!(
        evaluate_link_prediction_validation_batched(&task, "batched-model", 0, |_, _, _| Ok(())),
        Err(LinkPredictionError::InvalidInput("batched evaluator"))
    ));
}

#[test]
fn parallel_hash_compositor_is_exact_across_chunk_and_batch_boundaries() {
    let root = tempfile::tempdir().expect("root");
    let candidate_universe = 257_u32;
    let query_count = 19_u32;
    let mut queries = Vec::with_capacity(query_count as usize + 1);
    let mut conflicts = Vec::with_capacity(query_count as usize + 1);
    for query in 0..query_count {
        conflicts.push((query * 17 + 3) % candidate_universe);
        queries.push(LinkPredictionQuery {
            observed_at: i64::from(query) * 13 + 41,
            source: query % 11,
            relation: query % 6,
            conflict_offset: query,
            conflict_count: 1,
            split: LinkPredictionSplit::Validation,
            inverse: query % 6 >= 3,
        });
    }
    conflicts.push(0);
    queries.push(LinkPredictionQuery {
        observed_at: 1_000,
        source: 0,
        relation: 0,
        conflict_offset: query_count,
        conflict_count: 1,
        split: LinkPredictionSplit::Test,
        inverse: false,
    });
    let paths = write_link_prediction_task(
        &LinkPredictionTaskSnapshot {
            source_dataset_id: "chunk-source-b3".into(),
            source_binary_blake3: "chunk-source-binary-b3".into(),
            candidate_universe,
            base_relation_count: 3,
            validation_pickle_blake3: "chunk-val-pkl-b3".into(),
            test_pickle_blake3: "chunk-test-pkl-b3".into(),
            validation_parity_blake3: "chunk-val-parity-b3".into(),
            test_parity_blake3: "chunk-test-parity-b3".into(),
            queries,
            conflicts,
        },
        root.path().join("chunk-task"),
    )
    .expect("write chunk task");
    let task = LinkPredictionTaskMapped::open(paths.manifest).expect("open chunk task");
    let serial =
        evaluate_link_prediction_validation(&task, "chunk-model", |query, candidates, scores| {
            score_chunk_fixture(query, candidates, scores);
            Ok(())
        })
        .expect("serial");
    for batch_size in [1, 2, 3, 7, 16, 64] {
        let batched = evaluate_link_prediction_validation_batched(
            &task,
            "chunk-model",
            batch_size,
            |batch, candidates, scores| {
                for (query, row) in batch
                    .iter()
                    .copied()
                    .zip(scores.chunks_exact_mut(candidates.len()))
                {
                    score_chunk_fixture(query, candidates, row);
                }
                Ok(())
            },
        )
        .expect("batched");
        assert_eq!(batched, serial, "batch size {batch_size}");
        let canonical = evaluate_link_prediction_validation_canonical_batched(
            &task,
            "chunk-model",
            batch_size,
            |batch, candidates, mut matrix| {
                for (row, query) in batch.iter().copied().enumerate() {
                    score_chunk_fixture(
                        query,
                        candidates,
                        matrix.row_mut(row).expect("canonical score row"),
                    );
                }
                Ok(())
            },
        )
        .expect("canonical");
        assert_eq!(canonical, serial, "canonical batch size {batch_size}");
    }
}

#[test]
fn canonical_single_arena_rejects_non_finite_scores_before_certificate() {
    let root = tempfile::tempdir().expect("root");
    let task = direct_task(root.path());
    let result = evaluate_link_prediction_validation_canonical_batched(
        &task,
        "non-finite-model",
        3,
        |queries, _, mut matrix| {
            for row in 0..queries.len() {
                let scores = matrix.row_mut(row).expect("canonical score row");
                scores.fill(0.0);
                scores[0] = f32::NAN;
            }
            Ok(())
        },
    );
    assert!(matches!(result, Err(LinkPredictionError::Scorer(_))));
}

fn score_chunk_fixture(
    query: crate::LinkPredictionQueryView,
    candidates: &[u32],
    scores: &mut [f32],
) {
    for (candidate, score) in candidates.iter().copied().zip(scores) {
        let bits = candidate
            .wrapping_mul(0x9e37_79b9)
            .wrapping_add(query.source.rotate_left(7))
            .wrapping_add(query.relation.rotate_left(19))
            & 0x007f_ffff;
        *score = f32::from_bits(0x3f00_0000 | bits);
    }
}

fn score_fixture(query: crate::LinkPredictionQueryView, candidates: &[u32], scores: &mut [f32]) {
    for (candidate, score) in candidates.iter().copied().zip(scores) {
        *score =
            candidate as f32 * 0.25 + query.source as f32 * 0.5 + query.relation as f32 * 0.125;
    }
}

#[test]
fn locked_test_is_claimed_once_before_scores_are_exposed() {
    let root = tempfile::tempdir().expect("root");
    let task = direct_task(root.path());
    let validation = evaluate_link_prediction_validation(&task, "model-b3", |_query, _, scores| {
        scores.fill(0.0);
        Ok(())
    })
    .expect("validation");
    let lock = create_link_prediction_test_lock(
        &task,
        &LinkPredictionTestLockInput {
            task_id: task.manifest().task_id.clone(),
            selection_ledger_id: "ledger-b3".into(),
            selected_model_id: "model-b3".into(),
            validation_certificate_id: validation.certificate_id,
        },
        root.path().join("locks"),
    )
    .expect("lock");
    let output = root.path().join("test-results");
    let result =
        evaluate_locked_link_prediction_test(&task, &lock.receipt, &output, |_query, _, scores| {
            scores.copy_from_slice(&[0.0, 2.0, 2.0, 4.0]);
            Ok(())
        })
        .expect("test");
    assert!(result.claim.is_file());
    assert!(result.certificate.is_file());
    let mut called = false;
    assert!(matches!(
        evaluate_locked_link_prediction_test(&task, lock.receipt, &output, |_query, _, _| {
            called = true;
            Ok(())
        }),
        Err(LinkPredictionError::TestAlreadyClaimed(_))
    ));
    assert!(!called);
    let second_lock = create_link_prediction_test_lock(
        &task,
        &LinkPredictionTestLockInput {
            task_id: task.manifest().task_id.clone(),
            selection_ledger_id: "other-ledger-b3".into(),
            selected_model_id: "other-model-b3".into(),
            validation_certificate_id: "other-validation-b3".into(),
        },
        root.path().join("locks"),
    )
    .expect("second lock");
    assert!(matches!(
        evaluate_locked_link_prediction_test(&task, second_lock.receipt, output, |_, _, _| Ok(())),
        Err(LinkPredictionError::TestAlreadyClaimed(_))
    ));
}

#[test]
fn locked_batched_test_certificate_matches_serial_surface() {
    let root = tempfile::tempdir().expect("root");
    let task = direct_task(root.path());
    let lock = create_link_prediction_test_lock(
        &task,
        &LinkPredictionTestLockInput {
            task_id: task.manifest().task_id.clone(),
            selection_ledger_id: "ledger-b3".into(),
            selected_model_id: "model-b3".into(),
            validation_certificate_id: "validation-b3".into(),
        },
        root.path().join("locks"),
    )
    .expect("lock");
    let serial = evaluate_locked_link_prediction_test(
        &task,
        &lock.receipt,
        root.path().join("serial-test"),
        |_query, _, scores| {
            scores.copy_from_slice(&[0.0, 2.0, 2.0, 4.0]);
            Ok(())
        },
    )
    .expect("serial test");
    let batched = evaluate_locked_link_prediction_test_batched(
        &task,
        &lock.receipt,
        root.path().join("batched-test"),
        2,
        |_queries, candidates, scores| {
            for row in scores.chunks_exact_mut(candidates.len()) {
                row.copy_from_slice(&[0.0, 2.0, 2.0, 4.0]);
            }
            Ok(())
        },
    )
    .expect("batched test");
    let serial_certificate: LinkPredictionScoreCertificate =
        serde_json::from_slice(&std::fs::read(serial.certificate).expect("serial certificate"))
            .expect("serial json");
    let batched_certificate: LinkPredictionScoreCertificate =
        serde_json::from_slice(&std::fs::read(batched.certificate).expect("batched certificate"))
            .expect("batched json");
    assert_eq!(batched_certificate, serial_certificate);
}

#[test]
fn scorer_failure_burns_test_claim_fail_closed() {
    let root = tempfile::tempdir().expect("root");
    let task = direct_task(root.path());
    let lock = create_link_prediction_test_lock(
        &task,
        &LinkPredictionTestLockInput {
            task_id: task.manifest().task_id.clone(),
            selection_ledger_id: "ledger-b3".into(),
            selected_model_id: "model-b3".into(),
            validation_certificate_id: "validation-b3".into(),
        },
        root.path().join("locks"),
    )
    .expect("lock");
    let output = root.path().join("test-results");
    assert!(matches!(
        evaluate_locked_link_prediction_test(&task, &lock.receipt, &output, |_, _, _| {
            Err("model failure".to_owned())
        }),
        Err(LinkPredictionError::Scorer(_))
    ));
    assert!(matches!(
        evaluate_locked_link_prediction_test(&task, lock.receipt, output, |_, _, _| Ok(())),
        Err(LinkPredictionError::TestAlreadyClaimed(_))
    ));
}

#[test]
fn task_corruption_fails_before_mmap_queries() {
    let root = tempfile::tempdir().expect("root");
    let paths = direct_task_paths(root.path());
    let mut binary = std::fs::OpenOptions::new()
        .write(true)
        .open(paths.binary)
        .expect("binary");
    binary.seek(SeekFrom::Start(8)).expect("seek");
    binary.write_all(&[0xff]).expect("mutate");
    binary.sync_all().expect("sync");
    assert!(matches!(
        LinkPredictionTaskMapped::open(paths.manifest),
        Err(LinkPredictionError::CorruptArtifact("binary identity"))
    ));
}

#[test]
fn forged_manifest_split_boundary_cannot_expose_test_queries() {
    let root = tempfile::tempdir().expect("root");
    let source_manifest = write_source_fixture(root.path(), false);
    let source = ExternalDatasetMapped::open(source_manifest).expect("source");
    let paths =
        build_canonical_link_prediction_task(&source, root.path(), root.path().join("task"))
            .expect("task");
    let mut manifest: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&paths.manifest).expect("read")).expect("json");
    manifest["validationQueries"] = 4.into();
    manifest["testQueries"] = 4.into();
    manifest["validationPositives"] = 5.into();
    manifest["testPositives"] = 5.into();
    std::fs::write(
        &paths.manifest,
        serde_json::to_vec_pretty(&manifest).expect("encode"),
    )
    .expect("forge");
    assert!(matches!(
        LinkPredictionTaskMapped::open(paths.manifest),
        Err(LinkPredictionError::CorruptArtifact("query contract"))
            | Err(LinkPredictionError::CorruptArtifact("record counts"))
    ));
}

#[test]
fn restricted_pickle_parser_rejects_executable_global() {
    let bytes = [
        0x80, 5, 0x8c, 2, b'o', b's', 0x8c, 6, b's', b'y', b's', b't', b'e', b'm', 0x93, b'.',
    ];
    assert!(matches!(
        parse_tgb_conflict_pickle(&bytes),
        Err(LinkPredictionError::InvalidPickle("global"))
    ));
}

#[test]
fn evaluates_five_million_candidates_within_debug_gate() {
    let root = tempfile::tempdir().expect("root");
    let mut queries = Vec::with_capacity(20_001);
    let mut conflicts = Vec::with_capacity(20_001);
    for index in 0..20_000_u32 {
        queries.push(LinkPredictionQuery {
            observed_at: i64::from(index) + 1,
            source: index % 256,
            relation: 0,
            conflict_offset: index,
            conflict_count: 1,
            split: LinkPredictionSplit::Validation,
            inverse: false,
        });
        conflicts.push((index + 1) % 256);
    }
    queries.push(LinkPredictionQuery {
        observed_at: 20_001,
        source: 0,
        relation: 0,
        conflict_offset: 20_000,
        conflict_count: 1,
        split: LinkPredictionSplit::Test,
        inverse: false,
    });
    conflicts.push(1);
    let paths = write_link_prediction_task(
        &LinkPredictionTaskSnapshot {
            source_dataset_id: "performance-source".into(),
            source_binary_blake3: "performance-source-binary".into(),
            candidate_universe: 256,
            base_relation_count: 1,
            validation_pickle_blake3: "performance-validation".into(),
            test_pickle_blake3: "performance-test".into(),
            validation_parity_blake3: "performance-validation-parity".into(),
            test_parity_blake3: "performance-test-parity".into(),
            queries,
            conflicts,
        },
        root.path().join("performance-task"),
    )
    .expect("write task");
    let task = LinkPredictionTaskMapped::open(paths.manifest).expect("open task");
    let started = Instant::now();
    let certificate = evaluate_link_prediction_validation(
        &task,
        "performance-model",
        |_query, candidates, scores| {
            for (score, candidate) in scores.iter_mut().zip(candidates) {
                *score = *candidate as f32;
            }
            Ok(())
        },
    )
    .expect("evaluate");
    assert_eq!(certificate.candidates_scored, 5_120_000);
    assert!(started.elapsed() < Duration::from_secs(5));
}

fn direct_task(root: &Path) -> LinkPredictionTaskMapped {
    let paths = direct_task_paths(root);
    LinkPredictionTaskMapped::open(paths.manifest).expect("direct task")
}

fn direct_task_paths(root: &Path) -> crate::LinkPredictionTaskPaths {
    write_link_prediction_task(
        &LinkPredictionTaskSnapshot {
            source_dataset_id: "source-b3".into(),
            source_binary_blake3: "source-binary-b3".into(),
            candidate_universe: 4,
            base_relation_count: 2,
            validation_pickle_blake3: "val-pkl-b3".into(),
            test_pickle_blake3: "test-pkl-b3".into(),
            validation_parity_blake3: "val-parity-b3".into(),
            test_parity_blake3: "test-parity-b3".into(),
            queries: vec![
                LinkPredictionQuery {
                    observed_at: 8,
                    source: 0,
                    relation: 0,
                    conflict_offset: 0,
                    conflict_count: 2,
                    split: LinkPredictionSplit::Validation,
                    inverse: false,
                },
                LinkPredictionQuery {
                    observed_at: 10,
                    source: 0,
                    relation: 0,
                    conflict_offset: 2,
                    conflict_count: 2,
                    split: LinkPredictionSplit::Test,
                    inverse: false,
                },
            ],
            conflicts: vec![1, 2, 1, 2],
        },
        root.join("direct-task"),
    )
    .expect("write direct task")
}

fn write_source_fixture(root: &Path, wrong_validation: bool) -> std::path::PathBuf {
    let validation = if wrong_validation {
        vec![entry(8, 0, 0, &[3])]
    } else {
        vec![
            entry(8, 0, 0, &[1, 2]),
            entry(9, 2, 1, &[3]),
            entry(8, 1, 2, &[0]),
            entry(8, 2, 2, &[0]),
            entry(9, 3, 3, &[2]),
        ]
    };
    let test = vec![
        entry(10, 1, 0, &[3, 2]),
        entry(10, 3, 2, &[1]),
        entry(10, 2, 2, &[1]),
    ];
    let validation_pickle = encode_pickle(&validation);
    let test_pickle = encode_pickle(&test);
    let val_path = root.join("tkgl-smallpedia_val_ns.pkl");
    let test_path = root.join("tkgl-smallpedia_test_ns.pkl");
    std::fs::write(&val_path, &validation_pickle).expect("validation pickle");
    std::fs::write(&test_path, &test_pickle).expect("test pickle");
    let source_files = vec![
        source_receipt("tkgl-smallpedia_val_ns.pkl", &validation_pickle),
        source_receipt("tkgl-smallpedia_test_ns.pkl", &test_pickle),
    ];
    let facts = vec![
        fact(0, 0, 1, 1, ExternalFactSplit::Train),
        fact(1, 1, 2, 2, ExternalFactSplit::Train),
        fact(2, 0, 3, 3, ExternalFactSplit::Train),
        fact(3, 1, 0, 4, ExternalFactSplit::Train),
        fact(0, 0, 1, 8, ExternalFactSplit::Validation),
        fact(0, 0, 2, 8, ExternalFactSplit::Validation),
        fact(2, 1, 3, 9, ExternalFactSplit::Validation),
        fact(1, 0, 3, 10, ExternalFactSplit::Test),
        fact(1, 0, 2, 10, ExternalFactSplit::Test),
    ];
    ExternalDatasetBundle::write(
        &ExternalDatasetSnapshot {
            name: "tkgl-smallpedia".into(),
            kind: ExternalDatasetKind::TemporalKnowledgeGraph,
            upstream_url: "fixture".into(),
            upstream_version: "fixture-v1".into(),
            license_notice: "fixture".into(),
            split_policy: ExternalSplitPolicy::TemporalQuantile {
                train_through: 4,
                validation_through: 9,
                validation_basis_points: 1_500,
                test_basis_points: 1_500,
            },
            source_files,
            entities: ["E0", "E1", "E2", "E3"].map(CompactString::from).to_vec(),
            relations: ["R0", "R1"].map(CompactString::from).to_vec(),
            facts,
            qualifiers: Vec::new(),
        },
        root.join("source-artifact"),
    )
    .expect("source artifact")
    .manifest
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

fn entry(time: i64, source: u32, relation: u32, destinations: &[u32]) -> TgbConflictEntry {
    TgbConflictEntry {
        observed_at: time,
        source,
        relation,
        destinations: destinations.to_vec(),
    }
}

fn source_receipt(name: &str, bytes: &[u8]) -> ExternalSourceFile {
    ExternalSourceFile {
        logical_name: name.into(),
        blake3: format!("b3-{}", blake3::hash(bytes).to_hex()).into(),
        bytes: bytes.len() as u64,
        role: "officialNegatives".into(),
    }
}

fn encode_pickle(entries: &[TgbConflictEntry]) -> Vec<u8> {
    let mut bytes = vec![0x80, 5, b'}', b'('];
    for entry in entries {
        encode_scalar(&mut bytes, entry.observed_at);
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
