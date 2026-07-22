use crate::hyper_clip_runtime::routed_clip_coefficients;
use crate::hyper_encoder_examples::prepare_hyper_examples;
use crate::hyper_encoder_memory::train_fused_hyper_encoder16_with_optimizer;
use crate::{
    HyperClipPartition, HyperGradientClipPolicy, HyperOptimizerConfig, LossScaleSemantics,
};
use phoenix_graph_research::{
    build_canonical_hyper_relational_task, import_wd50k, initialize_hyper_encoder_weights,
    stage_hyper_encoder, ExternalDatasetMapped, HyperEncoderMode, HyperEncoderTrainingConfig,
    HyperRelationalTaskMapped,
};
use std::path::Path;

#[test]
fn loss_scale_semantics_are_identified_and_unscale_is_bit_exact() {
    let root = tempfile::tempdir().expect("root");
    write_fixture(root.path());
    let source_paths = import_wd50k(root.path(), root.path().join("source")).expect("source");
    let source = ExternalDatasetMapped::open(source_paths.manifest).expect("source open");
    let task_paths =
        build_canonical_hyper_relational_task(&source, root.path().join("task")).expect("task");
    let task = HyperRelationalTaskMapped::open(task_paths.manifest, &source).expect("task open");
    let staged = stage_hyper_encoder(&source, &task).expect("stage");
    let config = HyperEncoderTrainingConfig {
        epochs: 1,
        learning_rate: 0.02,
        l2: 0.0,
        negatives_per_positive: 1,
    };
    let examples = prepare_hyper_examples(&source, &staged, config, 0x5ca1_e001).expect("examples");
    let initial = initialize_hyper_encoder_weights(&staged, 0x5ca1_e001);
    let mut unit = HyperOptimizerConfig::bounded_sum_no_decay(0.02, 2);
    unit.loss_scale_semantics = LossScaleSemantics::UnscaleBeforeClip;
    let mut scaled = unit;
    scaled.global_loss_scale = 256.0;
    assert_ne!(
        unit.identity().expect("unit id"),
        scaled.identity().expect("scaled id")
    );
    let unit_outcome = train_fused_hyper_encoder16_with_optimizer(
        &source,
        &staged,
        &examples,
        HyperEncoderMode::StareQualifiers,
        config,
        unit,
        initial.clone(),
    )
    .expect("unit train");
    let scaled_outcome = train_fused_hyper_encoder16_with_optimizer(
        &source,
        &staged,
        &examples,
        HyperEncoderMode::StareQualifiers,
        config,
        scaled,
        initial.clone(),
    )
    .expect("scaled train");
    assert_eq!(unit_outcome.weights, scaled_outcome.weights);
    assert_eq!(
        unit_outcome.optimizer_state_blake3,
        scaled_outcome.optimizer_state_blake3
    );
    assert_eq!(unit_outcome.final_epoch.clip_activation_rate, 0.0);
    assert_eq!(scaled_outcome.final_epoch.clip_activation_rate, 0.0);

    let mut semantic = scaled;
    semantic.loss_scale_semantics = LossScaleSemantics::ClipScaledGradient;
    semantic.gradient_clip_policy = HyperGradientClipPolicy::GlobalNorm;
    semantic.gradient_clip_norm = 1.0e-12;
    assert_ne!(
        semantic.identity().expect("semantic id"),
        scaled.identity().expect("scaled id")
    );
    let semantic_outcome = train_fused_hyper_encoder16_with_optimizer(
        &source,
        &staged,
        &examples,
        HyperEncoderMode::StareQualifiers,
        config,
        semantic,
        initial,
    )
    .expect("semantic train");
    assert!(semantic_outcome.final_epoch.clip_activation_rate > 0.0);
    assert!(semantic_outcome.final_epoch.clip_activation_rate <= 1.0);
    assert_ne!(unit_outcome.weights, semantic_outcome.weights);
}

#[test]
fn grouped_pressure_routing_passes_equivalence_isolation_and_partition_gates() {
    let root = tempfile::tempdir().expect("root");
    write_fixture(root.path());
    let source_paths = import_wd50k(root.path(), root.path().join("source")).expect("source");
    let source = ExternalDatasetMapped::open(source_paths.manifest).expect("source open");
    let task_paths =
        build_canonical_hyper_relational_task(&source, root.path().join("task")).expect("task");
    let task = HyperRelationalTaskMapped::open(task_paths.manifest, &source).expect("task open");
    let staged = stage_hyper_encoder(&source, &task).expect("stage");
    let config = HyperEncoderTrainingConfig {
        epochs: 1,
        learning_rate: 0.02,
        l2: 0.0,
        negatives_per_positive: 1,
    };
    let examples = prepare_hyper_examples(&source, &staged, config, 0x5ca1_e001).expect("examples");
    let initial = initialize_hyper_encoder_weights(&staged, 0x5ca1_e001);

    let mut unclipped = HyperOptimizerConfig::bounded_sum_no_decay(0.02, 2);
    let mut grouped_no_clip = unclipped;
    grouped_no_clip.gradient_clip_policy = HyperGradientClipPolicy::DecoderBiasVsNonBias;
    grouped_no_clip.gradient_clip_norm = f32::MAX;
    let plain = train_fused_hyper_encoder16_with_optimizer(
        &source,
        &staged,
        &examples,
        HyperEncoderMode::StareQualifiers,
        config,
        unclipped,
        initial.clone(),
    )
    .expect("unclipped");
    let grouped = train_fused_hyper_encoder16_with_optimizer(
        &source,
        &staged,
        &examples,
        HyperEncoderMode::StareQualifiers,
        config,
        grouped_no_clip,
        initial.clone(),
    )
    .expect("grouped no clip");
    assert_eq!(plain.weights, grouped.weights);

    unclipped.gradient_clip_policy = HyperGradientClipPolicy::GlobalNorm;
    unclipped.gradient_clip_norm = 1.0e-6;
    let mut single_partition = unclipped;
    single_partition.gradient_clip_policy = HyperGradientClipPolicy::PartitionedSingleGlobal;
    let legacy = train_fused_hyper_encoder16_with_optimizer(
        &source,
        &staged,
        &examples,
        HyperEncoderMode::StareQualifiers,
        config,
        unclipped,
        initial.clone(),
    )
    .expect("legacy global");
    let single = train_fused_hyper_encoder16_with_optimizer(
        &source,
        &staged,
        &examples,
        HyperEncoderMode::StareQualifiers,
        config,
        single_partition,
        initial.clone(),
    )
    .expect("single partition");
    assert_eq!(legacy.weights, single.weights);

    let low_bias = routed_clip_coefficients(
        HyperGradientClipPolicy::DecoderBiasVsNonBias,
        1.0,
        4.0,
        10.0,
    );
    let huge_bias = routed_clip_coefficients(
        HyperGradientClipPolicy::DecoderBiasVsNonBias,
        1.0,
        4.0,
        1.0e12,
    );
    assert_eq!(low_bias.0.to_bits(), huge_bias.0.to_bits());
    assert_ne!(low_bias.1.to_bits(), huge_bias.1.to_bits());

    let mut optimizer = grouped_no_clip;
    optimizer.gradient_clip_norm = 1.0;
    let partition = HyperClipPartition::for_optimizer(&initial, optimizer).expect("partition");
    partition.validate(&initial).expect("valid partition");
    let mut duplicate = partition.clone();
    duplicate.spans.push(duplicate.spans[0].clone());
    assert!(duplicate.validate(&initial).is_err());
    let mut omitted = partition.clone();
    omitted.spans.pop();
    assert!(omitted.validate(&initial).is_err());
    let mut reordered = partition.clone();
    reordered.spans.swap(0, 1);
    assert!(reordered.validate(&initial).is_err());
    let mut overlap = partition;
    overlap.spans[1].start_offset = overlap.spans[0].start_offset;
    assert!(overlap.validate(&initial).is_err());
}

fn write_fixture(root: &Path) {
    let statements = root.join("statements");
    std::fs::create_dir_all(&statements).expect("statements");
    std::fs::write(
        statements.join("train.txt"),
        b"Q1,P1,Q2,P1,Q1\nQ2,P2,Q3,P2,Q2\n",
    )
    .expect("train");
    std::fs::write(statements.join("valid.txt"), b"Q1,P1,Q3,P1,Q1\n").expect("validation");
    std::fs::write(statements.join("test.txt"), b"Q3,P2,Q1,P2,Q3\n").expect("test");
}
