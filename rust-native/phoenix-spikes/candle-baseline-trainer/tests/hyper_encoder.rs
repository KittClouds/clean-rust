use phoenix_candle_baseline_trainer::{
    open_hyper_learning_gates, open_qualifier_signal_matrix, run_hyper_learning_gates,
    run_qualifier_signal_matrix16, train_paired_hyper_encoder16, LearningGateArm,
    PairedHyperEncoderRequest, QualifierSignalMatrixRequest,
};
use phoenix_graph_research::{
    build_canonical_hyper_relational_task, import_wd50k, ExternalDatasetMapped, HyperEncoderError,
    HyperEncoderMapped, HyperEncoderMode, HyperEncoderTrainingConfig,
};
use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};
use std::path::Path;

#[test]
fn paired_trainer_is_deterministic_restart_exact_and_immutable() {
    let root = tempfile::tempdir().expect("root");
    write_wd50k(root.path());
    let source_paths = import_wd50k(root.path(), root.path().join("source")).expect("source");
    let source = ExternalDatasetMapped::open(&source_paths.manifest).expect("open source");
    let task_paths =
        build_canonical_hyper_relational_task(&source, root.path().join("task")).expect("task");
    let request = |output| PairedHyperEncoderRequest {
        source_manifest: source_paths.manifest.clone(),
        task_manifest: task_paths.manifest.clone(),
        output_root: output,
        seed: 0x51a7_e001,
        config: HyperEncoderTrainingConfig {
            epochs: 2,
            learning_rate: 0.04,
            l2: 0.000_05,
            negatives_per_positive: 1,
        },
    };
    let first =
        train_paired_hyper_encoder16(&request(root.path().join("models-a"))).expect("first");
    let second =
        train_paired_hyper_encoder16(&request(root.path().join("models-b"))).expect("second");
    assert_eq!(first.report.pair_id, second.report.pair_id);
    assert_eq!(first.compgcn.model_id, second.compgcn.model_id);
    assert_eq!(first.stare.model_id, second.stare.model_id);
    assert_eq!(first.report.compgcn, second.report.compgcn);
    assert_eq!(first.report.stare, second.report.stare);
    assert!(first.report.compgcn_restart_exact);
    assert!(first.report.stare_restart_exact);
    assert!(first.report.model_ids_distinct);
    assert!(!first.report.test_partition_accessed);
    assert_eq!(
        HyperEncoderMapped::open(&first.compgcn.manifest)
            .expect("mapped")
            .manifest()
            .training
            .epoch_allocation_count,
        0
    );

    let mut corrupt = OpenOptions::new()
        .write(true)
        .open(&first.stare.weights)
        .expect("weights");
    corrupt.seek(SeekFrom::Start(40)).expect("seek");
    corrupt.write_all(&[0xff]).expect("corrupt");
    corrupt.sync_all().expect("sync");
    assert!(matches!(
        HyperEncoderMapped::open(&first.stare.manifest),
        Err(HyperEncoderError::CorruptArtifact("weight identity"))
    ));
}

#[test]
fn qualifier_signal_matrix_is_deterministic_isolated_and_restart_exact() {
    let root = tempfile::tempdir().expect("root");
    write_wd50k(root.path());
    let source_paths = import_wd50k(root.path(), root.path().join("source")).expect("source");
    let source = ExternalDatasetMapped::open(&source_paths.manifest).expect("open source");
    let task_paths =
        build_canonical_hyper_relational_task(&source, root.path().join("task")).expect("task");
    let request = |output| QualifierSignalMatrixRequest {
        source_manifest: source_paths.manifest.clone(),
        task_manifest: task_paths.manifest.clone(),
        output_root: output,
        seed: 0x51a7_e001,
        config: HyperEncoderTrainingConfig {
            epochs: 2,
            learning_rate: 0.04,
            l2: 0.000_05,
            negatives_per_positive: 1,
        },
    };
    let first = run_qualifier_signal_matrix16(&request(root.path().join("matrix-a")))
        .expect("first matrix");
    let second = run_qualifier_signal_matrix16(&request(root.path().join("matrix-b")))
        .expect("second matrix");
    assert_eq!(first.matrix_id, second.matrix_id);
    let first_manifest = first.manifest.clone();
    let first = open_qualifier_signal_matrix(&first_manifest).expect("open first");
    let second = open_qualifier_signal_matrix(second.manifest).expect("open second");
    for (left, right) in first.arms.iter().zip(&second.arms) {
        assert_eq!(left.mode, right.mode);
        assert_eq!(left.model_id, right.model_id);
        assert_eq!(left.validation, right.validation);
        assert_eq!(left.final_epoch, right.final_epoch);
        assert_eq!(left.economics_blake3, right.economics_blake3);
    }
    assert_eq!(first.arms.len(), 8);
    assert!(first.arms.iter().all(|arm| arm.restart_exact));
    assert!(!first.test_partition_accessed);
    assert_eq!(first.arms[0].mode, HyperEncoderMode::CompgcnTriple);
    assert_eq!(first.arms[1].mode, HyperEncoderMode::StareQualifiers);
    assert_eq!(first.arms[4].mode, HyperEncoderMode::Shuffled);
    assert_eq!(first.arms[5].mode, HyperEncoderMode::Detached);
    assert_eq!(
        first.arms[5]
            .final_epoch
            .qualifier_projection
            .exactly_zero_gradients,
        first.arms[5].final_epoch.qualifier_projection.parameters
    );
    let mut model_ids = first
        .arms
        .iter()
        .map(|arm| arm.model_id.as_str())
        .collect::<Vec<_>>();
    model_ids.sort_unstable();
    model_ids.dedup();
    assert_eq!(model_ids.len(), 8);

    let mut corrupt: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&first_manifest).expect("read matrix"))
            .expect("matrix JSON");
    corrupt["arms"][1]["finalEpoch"]["meanBinaryCrossEntropy"] = serde_json::json!(0.5);
    std::fs::write(
        &first_manifest,
        serde_json::to_vec_pretty(&corrupt).expect("corrupt JSON"),
    )
    .expect("write corrupt matrix");
    assert!(open_qualifier_signal_matrix(&first_manifest).is_err());
}

#[test]
fn hyper_learning_gates_are_functional_deterministic_and_restart_exact() {
    let first_root = tempfile::tempdir().expect("first root");
    let second_root = tempfile::tempdir().expect("second root");
    let first = run_hyper_learning_gates(first_root.path()).expect("first gates");
    let second = run_hyper_learning_gates(second_root.path()).expect("second gates");
    assert_eq!(first.receipt_id, second.receipt_id);
    let first_receipt = open_hyper_learning_gates(&first.receipt).expect("open first");
    let second_receipt = open_hyper_learning_gates(&second.receipt).expect("open second");
    assert_eq!(first_receipt, second_receipt);
    assert!(first_receipt.all_passed);
    for case in [
        &first_receipt.single_pair,
        &first_receipt.qualifier_value,
        &first_receipt.qualifier_role,
    ] {
        assert!(case.passed);
        assert!(case.symmetric_parameter_bits);
        assert!(case.arms.iter().all(|arm| arm.cold_score_exact));
    }
    for case in [
        &first_receipt.qualifier_value,
        &first_receipt.qualifier_role,
    ] {
        let null = case
            .arms
            .iter()
            .find(|arm| arm.arm == LearningGateArm::QualifierGradientNull)
            .expect("null arm");
        let control = case
            .arms
            .iter()
            .find(|arm| arm.arm == LearningGateArm::Compgcn)
            .expect("control arm");
        assert!(null.train_path_alias_exact);
        assert_eq!(
            null.base_checkpoint_model_id.as_ref(),
            Some(&control.model_id)
        );
        assert_eq!(null.qualifier_value_delta.changed_scalars, 0);
        assert_eq!(null.qualifier_role_delta.changed_scalars, 0);
        assert_eq!(null.qualifier_projection_delta.changed_scalars, 0);
    }

    let mut corrupt: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&first.receipt).expect("read receipt"))
            .expect("receipt JSON");
    corrupt["qualifierValue"]["passed"] = serde_json::json!(false);
    std::fs::write(
        &first.receipt,
        serde_json::to_vec_pretty(&corrupt).expect("corrupt JSON"),
    )
    .expect("write corrupt receipt");
    assert!(open_hyper_learning_gates(&first.receipt).is_err());
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

fn write(path: &Path, bytes: &[u8]) {
    std::fs::write(path, bytes).expect("write");
}
