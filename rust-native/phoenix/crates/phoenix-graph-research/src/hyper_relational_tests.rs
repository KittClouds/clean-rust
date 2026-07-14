use crate::hyper_relational_binary::{
    Header, HyperLeU32, HyperQualifierContextRecord, HyperQueryRecord, HyperTruthGroupRecord,
};
use crate::{
    build_canonical_hyper_relational_task, create_hyper_relational_test_lock,
    evaluate_hyper_encoder_pair, evaluate_hyper_relational_validation_batched,
    evaluate_locked_hyper_relational_test_batched, import_wd50k, stage_hyper_encoder,
    ExternalDatasetMapped, HyperRelationalCandidatePolicy, HyperRelationalTaskError,
    HyperRelationalTaskMapped, HyperRelationalTestLockInput,
};
use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};
use std::mem::size_of;
use std::path::Path;

#[test]
fn wd50k_task_is_deterministic_zero_copy_and_leakage_audited() {
    let root = tempfile::tempdir().expect("root");
    write_wd50k(root.path());
    let source_paths = import_wd50k(root.path(), root.path().join("source")).expect("source");
    let source = ExternalDatasetMapped::open(&source_paths.manifest).expect("open source");
    let first = build_canonical_hyper_relational_task(&source, root.path().join("task-a"))
        .expect("first task");
    let second = build_canonical_hyper_relational_task(&source, root.path().join("task-b"))
        .expect("second task");
    assert_eq!(first.task_id, second.task_id);

    let task = HyperRelationalTaskMapped::open(&first.manifest, &source).expect("open task");
    let manifest = task.manifest();
    assert_eq!(manifest.train_statements, 4);
    assert_eq!(manifest.validation_statements, 2);
    assert_eq!(manifest.test_statements, 2);
    assert_eq!(manifest.validation_queries, 4);
    assert_eq!(manifest.test_queries, 4);
    assert_eq!(manifest.qualifier_only_entities, 2);
    assert_eq!(manifest.qualifier_only_relations, 2);
    assert!(manifest.qualifiers_borrowed_from_source);
    assert!(manifest.test_locked);
    assert_eq!(manifest.leakage_audit.train_test_primary_overlap, 1);
    assert_eq!(manifest.leakage_audit.train_test_statement_duplicates, 1);
    assert_eq!(
        manifest
            .leakage_audit
            .cross_split_reordered_qualifier_duplicates,
        1
    );
    assert_ne!(
        manifest.original_qualifier_order_blake3,
        manifest.canonical_qualifier_order_blake3
    );

    let expected_bytes = size_of::<Header>()
        + (manifest.validation_queries + manifest.test_queries) as usize
            * size_of::<HyperQueryRecord>()
        + manifest.truth_groups as usize * size_of::<HyperTruthGroupRecord>()
        + manifest.truth_targets as usize * size_of::<HyperLeU32>()
        + manifest.qualifier_contexts as usize * size_of::<HyperQualifierContextRecord>()
        + manifest.candidate_universe as usize
        + manifest.base_relation_count as usize;
    assert_eq!(manifest.binary_bytes as usize, expected_bytes);
    let source_facts = source.facts().expect("facts");
    let queries = task
        .queries(crate::LinkPredictionSplit::Validation)
        .expect("queries");
    let groups = task.truth_groups().expect("groups");
    assert!(manifest.qualifier_contexts > 1);
    assert_eq!(groups[queries[0].truth_group() as usize].target_count(), 2);
    for record in queries.iter().copied() {
        let fact = source_facts[record.statement_id() as usize];
        assert_eq!(record.qualifier_offset(), fact.qualifier_offset());
        assert_eq!(record.qualifier_count(), fact.qualifier_count());
        assert_eq!(
            groups[record.truth_group() as usize].qualifier_context(),
            record.qualifier_context()
        );
    }
}

#[test]
fn exact_evaluator_certifies_both_candidate_policies_and_locks_test_once() {
    let root = tempfile::tempdir().expect("root");
    let (source, paths) = fixture_task(root.path());
    let task = HyperRelationalTaskMapped::open(&paths.manifest, &source).expect("task");
    let full = evaluate_hyper_relational_validation_batched(
        &task,
        "model-a",
        HyperRelationalCandidatePolicy::FullEntity,
        3,
        deterministic_scores,
    )
    .expect("full");
    let full_single = evaluate_hyper_relational_validation_batched(
        &task,
        "model-a",
        HyperRelationalCandidatePolicy::FullEntity,
        1,
        deterministic_scores,
    )
    .expect("full single");
    let role = evaluate_hyper_relational_validation_batched(
        &task,
        "model-a",
        HyperRelationalCandidatePolicy::PrimaryRole,
        3,
        deterministic_scores,
    )
    .expect("role");
    assert_eq!(full, full_single);
    assert_eq!(full.score_blake3, role.score_blake3);
    assert_ne!(full.certificate_id, role.certificate_id);
    assert_eq!(full.metrics.queries, task.manifest().validation_queries);
    assert!(role.metrics.candidates_scored < full.metrics.candidates_scored);
    assert!(full.metrics.hits_at_5 >= full.metrics.hits_at_3);
    assert_eq!(
        full.target_provenance
            .iter()
            .find(|slice| slice.label == "qualifier-only")
            .expect("qualifier-only slice")
            .metrics
            .queries,
        0
    );

    let lock = create_hyper_relational_test_lock(
        &task,
        &HyperRelationalTestLockInput {
            task_id: task.manifest().task_id.clone(),
            selection_ledger_id: "selection-a".into(),
            selected_model_id: "model-a".into(),
            validation_certificate_id: role.certificate_id.clone(),
            candidate_policy: HyperRelationalCandidatePolicy::PrimaryRole,
        },
        root.path().join("locks"),
    )
    .expect("lock");
    let result = evaluate_locked_hyper_relational_test_batched(
        &task,
        &lock.receipt,
        root.path().join("test-result"),
        2,
        deterministic_scores,
    )
    .expect("test");
    assert!(result.claim.is_file());
    assert!(result.certificate.is_file());
    assert!(matches!(
        evaluate_locked_hyper_relational_test_batched(
            &task,
            &lock.receipt,
            root.path().join("test-result"),
            2,
            deterministic_scores,
        ),
        Err(HyperRelationalTaskError::TestAlreadyClaimed(_))
    ));
}

#[test]
fn scorer_failure_burns_claim_and_corruption_or_source_drift_fail_closed() {
    let root = tempfile::tempdir().expect("root");
    let (source, paths) = fixture_task(root.path());
    let task = HyperRelationalTaskMapped::open(&paths.manifest, &source).expect("task");
    let lock = create_hyper_relational_test_lock(
        &task,
        &HyperRelationalTestLockInput {
            task_id: task.manifest().task_id.clone(),
            selection_ledger_id: "selection-b".into(),
            selected_model_id: "model-b".into(),
            validation_certificate_id: "validation-b".into(),
            candidate_policy: HyperRelationalCandidatePolicy::FullEntity,
        },
        root.path().join("burn-lock"),
    )
    .expect("lock");
    let output = root.path().join("burn-result");
    assert!(matches!(
        evaluate_locked_hyper_relational_test_batched(
            &task,
            &lock.receipt,
            &output,
            2,
            |_, _, _| Err("intentional".to_owned()),
        ),
        Err(HyperRelationalTaskError::Scorer(_))
    ));
    assert!(matches!(
        evaluate_locked_hyper_relational_test_batched(
            &task,
            &lock.receipt,
            &output,
            2,
            deterministic_scores,
        ),
        Err(HyperRelationalTaskError::TestAlreadyClaimed(_))
    ));

    let mut file = OpenOptions::new()
        .write(true)
        .open(&paths.binary)
        .expect("binary");
    file.seek(SeekFrom::Start(8)).expect("seek");
    file.write_all(&[0xff]).expect("corrupt");
    file.sync_all().expect("sync");
    assert!(matches!(
        HyperRelationalTaskMapped::open(&paths.manifest, &source),
        Err(HyperRelationalTaskError::CorruptArtifact("binary identity"))
    ));

    let other = tempfile::tempdir().expect("other");
    write_wd50k_variant(other.path());
    let other_paths = import_wd50k(other.path(), other.path().join("source")).expect("other");
    let other_source = ExternalDatasetMapped::open(other_paths.manifest).expect("other source");
    assert!(matches!(
        HyperRelationalTaskMapped::open(&paths.manifest, &other_source),
        Err(HyperRelationalTaskError::CorruptArtifact("manifest"))
    ));
}

#[test]
fn stare_and_compgcn_share_one_exact_zero_copy_evaluator_contract() {
    let root = tempfile::tempdir().expect("root");
    let (source, paths) = fixture_task(root.path());
    let task = HyperRelationalTaskMapped::open(&paths.manifest, &source).expect("task");
    let staged = stage_hyper_encoder(&source, &task).expect("stage");
    assert!(staged.profile.train_only);
    assert!(staged.profile.original_filter_order_preserved);
    assert_eq!(staged.profile.qualifier_payload_bytes_copied, 0);
    assert_eq!(
        staged.profile.canonical_ref_bytes,
        source.manifest().qualifiers * size_of::<u32>() as u64
    );
    let facts = source.facts().expect("facts");
    let qualifiers = source.qualifiers().expect("qualifiers");
    for fact in facts.iter().copied() {
        let start = fact.qualifier_offset() as usize;
        let end = start + fact.qualifier_count() as usize;
        let actual = staged.canonical_qualifier_refs[start..end]
            .iter()
            .map(|reference| {
                let qualifier = qualifiers[*reference as usize];
                (qualifier.predicate(), qualifier.object(), *reference)
            })
            .collect::<Vec<_>>();
        assert!(actual.windows(2).all(|pair| pair[0] <= pair[1]));
    }

    let first = evaluate_hyper_encoder_pair(
        &source,
        &task,
        &staged,
        0x51a7_e001,
        HyperRelationalCandidatePolicy::FullEntity,
    )
    .expect("first pair");
    let second = evaluate_hyper_encoder_pair(
        &source,
        &task,
        &staged,
        0x51a7_e001,
        HyperRelationalCandidatePolicy::FullEntity,
    )
    .expect("second pair");
    assert_eq!(first, second);
    assert_ne!(first.compgcn_model_id, first.stare_model_id);
    assert_ne!(first.compgcn.score_blake3, first.stare.score_blake3);
    assert_eq!(
        first.compgcn.metrics.queries,
        task.manifest().validation_queries
    );
    assert_eq!(
        first.stare.metrics.queries,
        task.manifest().validation_queries
    );
}

#[test]
fn stare_collapses_bit_exactly_without_train_or_validation_qualifiers() {
    let root = tempfile::tempdir().expect("root");
    let statements = root.path().join("statements");
    std::fs::create_dir_all(&statements).expect("statements");
    write(&statements.join("train.txt"), b"Q1,P1,Q2\n");
    write(&statements.join("valid.txt"), b"Q2,P1,Q3\n");
    write(&statements.join("test.txt"), b"Q3,P1,Q1,PQ,Q4\n");
    let source_paths = import_wd50k(root.path(), root.path().join("source")).expect("source");
    let source = ExternalDatasetMapped::open(source_paths.manifest).expect("source open");
    let paths =
        build_canonical_hyper_relational_task(&source, root.path().join("task")).expect("task");
    let task = HyperRelationalTaskMapped::open(paths.manifest, &source).expect("task open");
    let staged = stage_hyper_encoder(&source, &task).expect("stage");
    let pair = evaluate_hyper_encoder_pair(
        &source,
        &task,
        &staged,
        0x51a7_e001,
        HyperRelationalCandidatePolicy::FullEntity,
    )
    .expect("pair");
    assert_eq!(pair.compgcn.score_blake3, pair.stare.score_blake3);
    assert_eq!(pair.compgcn.metrics, pair.stare.metrics);
}

fn deterministic_scores(
    queries: &[crate::HyperRelationalQueryView],
    candidates: &[u32],
    scores: &mut [f32],
) -> Result<(), String> {
    for (query, row) in queries
        .iter()
        .zip(scores.chunks_exact_mut(candidates.len()))
    {
        for (candidate, score) in candidates.iter().copied().zip(row) {
            let mixed = candidate
                .wrapping_mul(0x9e37_79b9)
                .rotate_left(query.relation & 31)
                ^ query.source
                ^ query.qualifier_count;
            *score = f32::from_bits(0x3f80_0000 | (mixed & 0x007f_ffff));
        }
    }
    Ok(())
}

fn fixture_task(root: &Path) -> (ExternalDatasetMapped, crate::HyperRelationalTaskPaths) {
    write_wd50k(root);
    let source_paths = import_wd50k(root, root.join("source")).expect("source");
    let source = ExternalDatasetMapped::open(source_paths.manifest).expect("source open");
    let task = build_canonical_hyper_relational_task(&source, root.join("task")).expect("task");
    (source, task)
}

fn write_wd50k(root: &Path) {
    let statements = root.join("statements");
    std::fs::create_dir_all(&statements).expect("statements");
    write(
        &statements.join("train.txt"),
        b"Q1,P1,Q2,PQ,Q3,PQ2,Q4\nQ1,P1,Q10,PQ,Q7\nQ2,P2,Q5\nQ8,P1,Q9\n",
    );
    write(&statements.join("valid.txt"), b"Q1,P1,Q6,PQ,Q7\nQ5,P2,Q2\n");
    write(
        &statements.join("test.txt"),
        b"Q7,P3,Q1\nQ1,P1,Q2,PQ2,Q4,PQ,Q3\n",
    );
}

fn write_wd50k_variant(root: &Path) {
    write_wd50k(root);
    write(
        &root.join("statements").join("test.txt"),
        b"Q7,P3,Q10\nQ1,P1,Q2,PQ2,Q4,PQ,Q3\n",
    );
}

fn write(path: &Path, bytes: &[u8]) {
    std::fs::write(path, bytes).expect("write");
}
