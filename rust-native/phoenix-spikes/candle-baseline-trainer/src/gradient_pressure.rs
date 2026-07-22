use crate::gradient_pressure_model::*;
use crate::gradient_pressure_schedule::{
    build_diagnostic_schedules, slice_examples, DiagnosticSchedule, AUDIT_SAMPLE_PAIRS,
};
use crate::hyper_encoder_examples::prepare_hyper_examples;
use crate::hyper_encoder_memory::{
    train_fused_hyper_encoder16_with_optimizer, FusedHyperTrainingOutcome,
};
use crate::hyper_learning_gate_metrics::{economics_gradient_norm, weights_digest};
use crate::{
    CandleTrainerError, GradientBlockEconomics, HyperGradientClipPolicy, HyperLossReduction,
    HyperOptimizerAlgorithm, HyperOptimizerConfig, HyperWeightDecaySemantics, LossScaleSemantics,
    QualifiedSamplingPolicy,
};
use compact_str::{format_compact, CompactString};
use phoenix_graph_research::{
    initialize_hyper_encoder_weights, stage_hyper_encoder, ExternalDatasetMapped,
    HyperEncoderMapped, HyperEncoderMode, HyperEncoderStagedInput, HyperEncoderTrainingConfig,
    HyperEncoderWeights, HyperRelationalTaskMapped, HYPER_ENCODER_HIDDEN,
};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

const LEARNING_RATE: f32 = 0.02;
const LOSS_SCALE: f32 = 256.0;
const CLIP_NORM: f32 = 1.0;
const ID_PLACEHOLDER: &str = "b3-0000000000000000000000000000000000000000000000000000000000000000";

#[derive(Clone, Copy)]
enum BlockKind {
    Entity,
    Relation,
    RelationProjection,
    QualifierProjection,
    Direction,
    DecoderBias,
    QualifierValues,
    QualifierRoles,
}

const BLOCKS: [BlockKind; 8] = [
    BlockKind::Entity,
    BlockKind::Relation,
    BlockKind::RelationProjection,
    BlockKind::QualifierProjection,
    BlockKind::Direction,
    BlockKind::DecoderBias,
    BlockKind::QualifierValues,
    BlockKind::QualifierRoles,
];

pub fn run_gradient_pressure_audit_v1(
    request: &GradientPressureAuditRequest,
) -> Result<GradientPressureAuditPaths, CandleTrainerError> {
    std::fs::create_dir_all(&request.output_root)?;
    let source = ExternalDatasetMapped::open(&request.source_manifest)?;
    let task = HyperRelationalTaskMapped::open(&request.task_manifest, &source)?;
    let staged = stage_hyper_encoder(&source, &task)?;
    let training = training_config();
    let base = prepare_hyper_examples(&source, &staged, training, GRADIENT_PRESSURE_SEED)?;
    let initialized = initialize_hyper_encoder_weights(&staged, GRADIENT_PRESSURE_SEED);
    let initialized_blake3 = weights_digest(&initialized);
    let checkpoint = HyperEncoderMapped::open(&request.checkpoint_manifest)?;
    let checkpoint_manifest = checkpoint.manifest();
    if checkpoint_manifest.source_dataset_id != staged.source_dataset_id
        || checkpoint_manifest.source_binary_blake3 != staged.source_binary_blake3
        || checkpoint_manifest.task_id != staged.task_id
        || checkpoint_manifest.task_binary_blake3 != staged.task_binary_blake3
        || checkpoint_manifest.config.seed != GRADIENT_PRESSURE_SEED
        || checkpoint_manifest.config.mode != HyperEncoderMode::StareQualifiers
        || checkpoint_manifest.training_config.epochs != 32
        || checkpoint_manifest.training.initialization_blake3 != initialized_blake3
        || checkpoint_manifest.training.example_schedule_blake3 != base.schedule_blake3
    {
        return Err(CandleTrainerError::Contract(
            "gradient pressure checkpoint authority",
        ));
    }
    let initialization_blake3 = checkpoint_manifest.training.initialization_blake3.clone();
    let checkpoint_model_id = checkpoint_manifest.model_id.clone();
    let checkpoint_manifest_id = checkpoint_manifest.manifest_id.clone();
    let checkpoint_weights_blake3 = checkpoint_manifest.weights_blake3.clone();
    let initial = checkpoint.weights()?;
    let (pressure_schedules, cancellation_schedules) =
        build_diagnostic_schedules(&source, &staged, &base)?;

    let mut negative_pressure = Vec::with_capacity(pressure_schedules.len());
    for schedule in &pressure_schedules {
        negative_pressure.push(run_pressure(&source, &staged, &initial, schedule)?);
    }
    let mut cancellation = Vec::with_capacity(cancellation_schedules.len());
    for schedule in &cancellation_schedules {
        cancellation.push(run_cancellation(&source, &staged, &initial, schedule)?);
    }
    let decision = decide(&negative_pressure, &cancellation)?;
    let decision_evidence_blake3 = decision_evidence(decision, &negative_pressure, &cancellation);
    let optimizer_identity = pressure_optimizer(pressure_schedules[0].examples.len()).identity()?;
    let mut receipt = GradientPressureAuditReceipt {
        schema_version: GRADIENT_PRESSURE_AUDIT_SCHEMA.into(),
        audit_id: ID_PLACEHOLDER.into(),
        source_dataset_id: staged.source_dataset_id.clone(),
        source_binary_blake3: staged.source_binary_blake3.clone(),
        task_id: staged.task_id.clone(),
        task_binary_blake3: staged.task_binary_blake3.clone(),
        seed: GRADIENT_PRESSURE_SEED,
        optimizer_identity,
        initialization_blake3,
        checkpoint_model_id,
        checkpoint_manifest_id,
        checkpoint_weights_blake3,
        sample_pairs_per_schedule: AUDIT_SAMPLE_PAIRS as u32,
        decoder_weights_present: false,
        primary_graph_mutated: false,
        corruptions_filtered_against_train: true,
        semantic_row_gradient_estimator: "actual-f32-parameter-delta/learning-rate/clip-coefficient; optimizer-visible lower bound for shared entity and relation row subsets".into(),
        test_partition_accessed: false,
        negative_pressure,
        cancellation,
        decision,
        decision_evidence_blake3,
        next_cut: next_cut(decision).into(),
        stop_condition: "one corrected optimization run; stop this WD50K recipe if Full StarE minus Null remains functionally zero after healthy qualifier pressure and visible updates".into(),
        external_calibration: "can the learner exploit known qualifier value and role signals under measured optimizer pressure?".into(),
        phoenix_native_value: "carry understood pressure routing into canonical memory delta, discrepancy, episode, and context decisions".into(),
        exit_criterion: "healthy qualifier margins and updates with no Full StarE causal gain ends refinement of this benchmark recipe".into(),
    };
    let (audit_id, bytes) = seal_receipt(&receipt)?;
    receipt.audit_id = audit_id.clone();
    let path = request
        .output_root
        .join(format!("{audit_id}.gradient-pressure.json"));
    write_new_durable(&path, &bytes)?;
    let reopened = open_gradient_pressure_audit(&path)?;
    if reopened.audit_id != receipt.audit_id {
        return Err(CandleTrainerError::Contract(
            "gradient pressure durable replay",
        ));
    }
    Ok(GradientPressureAuditPaths {
        receipt: path,
        audit_id,
    })
}

pub fn open_gradient_pressure_audit(
    path: impl AsRef<Path>,
) -> Result<GradientPressureAuditReceipt, CandleTrainerError> {
    let bytes = std::fs::read(path.as_ref())?;
    let receipt: GradientPressureAuditReceipt = serde_json::from_slice(&bytes)?;
    if receipt.schema_version != GRADIENT_PRESSURE_AUDIT_SCHEMA
        || receipt.audit_id != identity_from_bytes(&bytes, &receipt.audit_id)?
        || receipt.primary_graph_mutated
        || receipt.test_partition_accessed
        || receipt.decoder_weights_present
        || !receipt.corruptions_filtered_against_train
    {
        return Err(CandleTrainerError::Contract(
            "gradient pressure receipt identity",
        ));
    }
    Ok(receipt)
}

fn run_pressure(
    source: &ExternalDatasetMapped,
    staged: &HyperEncoderStagedInput,
    initial: &HyperEncoderWeights,
    schedule: &DiagnosticSchedule,
) -> Result<NegativePressureReceipt, CandleTrainerError> {
    let optimizer = pressure_optimizer(schedule.examples.len());
    let outcome = train_once(
        source,
        staged,
        &schedule.examples,
        optimizer,
        initial.clone(),
    )?;
    let global = economics_gradient_norm(&outcome.final_epoch);
    let coefficient = f64::from(outcome.final_epoch.clip_coefficient);
    let blocks = pressure_blocks(initial, &outcome, schedule, global, coefficient);
    let decoder = outcome.final_epoch.decoder_bias.gradient_l2;
    let qualifier = outcome.final_epoch.qualifier_projection.gradient_l2;
    let bias_probes = bias_probes(initial, &outcome, schedule, global);
    Ok(NegativePressureReceipt {
        schedule_name: schedule.name.clone(),
        kind: schedule
            .kind
            .ok_or(CandleTrainerError::Contract("pressure kind"))?,
        positive_negative_pairs: (schedule.examples.len() / 2) as u64,
        schedule_blake3: schedule.examples.schedule_blake3.as_str().into(),
        optimizer_identity: optimizer.identity()?,
        raw_global_gradient_l2: global,
        global_clip_coefficient: coefficient,
        decoder_bias_norm_share: share(decoder, global),
        qualifier_projection_norm_share: share(qualifier, global),
        qualifier_to_decoder_gradient_ratio: ratio(qualifier, decoder),
        qualifier_value_embedding_raw_l2: block(&blocks, "qualifier-value-embeddings")
            .raw_gradient_l2,
        qualifier_role_embedding_raw_l2: block(&blocks, "qualifier-role-embeddings")
            .raw_gradient_l2,
        blocks,
        bias_probes,
    })
}

fn pressure_blocks(
    initial: &HyperEncoderWeights,
    outcome: &FusedHyperTrainingOutcome,
    schedule: &DiagnosticSchedule,
    global: f64,
    coefficient: f64,
) -> Vec<GradientPressureBlock> {
    BLOCKS
        .iter()
        .copied()
        .map(|kind| {
            if let Some(economics) = economics(&outcome.final_epoch, kind) {
                let changed = changed_bits(initial, &outcome.weights, kind, schedule);
                GradientPressureBlock {
                    name: block_name(kind).into(),
                    raw_gradient_l2: economics.gradient_l2,
                    global_norm_share: share(economics.gradient_l2, global),
                    post_clip_gradient_l2: economics.gradient_l2 * coefficient,
                    clip_coefficient: coefficient,
                    update_l2: economics.update_l2,
                    update_to_weight: economics.update_to_weight,
                    changed_parameter_bits: changed,
                    changed_parameter_bits_measured: true,
                    parameters: economics.parameters,
                }
            } else {
                let update = delta_norm(initial, &outcome.weights, kind, schedule);
                let parameter = parameter_norm(initial, kind, schedule);
                let post_clip = update / f64::from(LEARNING_RATE);
                let raw = if coefficient == 0.0 {
                    0.0
                } else {
                    post_clip / coefficient
                };
                GradientPressureBlock {
                    name: block_name(kind).into(),
                    raw_gradient_l2: raw,
                    global_norm_share: share(raw, global),
                    post_clip_gradient_l2: post_clip,
                    clip_coefficient: coefficient,
                    update_l2: update,
                    update_to_weight: ratio(update, parameter),
                    changed_parameter_bits: changed_bits(initial, &outcome.weights, kind, schedule),
                    changed_parameter_bits_measured: true,
                    parameters: parameter_count(initial, kind, schedule) as u64,
                }
            }
        })
        .collect()
}

fn bias_probes(
    initial: &HyperEncoderWeights,
    outcome: &FusedHyperTrainingOutcome,
    schedule: &DiagnosticSchedule,
    global: f64,
) -> Vec<BiasProbeReceipt> {
    let bias = outcome.final_epoch.decoder_bias.gradient_l2;
    let non_bias = (global * global - bias * bias).max(0.0).sqrt();
    [
        (BiasRoutingProbe::Normal, clip(global), clip(global), global),
        (BiasRoutingProbe::Frozen, clip(non_bias), 0.0, non_bias),
        (
            BiasRoutingProbe::ExcludedFromGlobalNorm,
            clip(non_bias),
            clip(non_bias),
            non_bias,
        ),
        (
            BiasRoutingProbe::SeparateClipGroup,
            clip(non_bias),
            clip(bias),
            global,
        ),
    ]
    .into_iter()
    .map(
        |(probe, non_bias_coefficient, bias_coefficient, norm)| BiasProbeReceipt {
            probe,
            global_norm: norm,
            non_bias_clip_coefficient: non_bias_coefficient,
            bias_clip_coefficient: bias_coefficient,
            blocks: BLOCKS
                .iter()
                .copied()
                .map(|kind| {
                    let raw = if let Some(e) = economics(&outcome.final_epoch, kind) {
                        e.gradient_l2
                    } else {
                        block(
                            &pressure_blocks(initial, outcome, schedule, global, clip(global)),
                            block_name(kind),
                        )
                        .raw_gradient_l2
                    };
                    let coefficient = if matches!(kind, BlockKind::DecoderBias) {
                        bias_coefficient
                    } else {
                        non_bias_coefficient
                    };
                    let weight = parameter_norm(initial, kind, schedule);
                    let update = f64::from(LEARNING_RATE) * raw * coefficient;
                    GradientPressureBlock {
                        name: block_name(kind).into(),
                        raw_gradient_l2: raw,
                        global_norm_share: share(raw, norm),
                        post_clip_gradient_l2: raw * coefficient,
                        clip_coefficient: coefficient,
                        update_l2: update,
                        update_to_weight: ratio(update, weight),
                        changed_parameter_bits: if probe == BiasRoutingProbe::Normal {
                            changed_bits(initial, &outcome.weights, kind, schedule)
                        } else {
                            0
                        },
                        changed_parameter_bits_measured: probe == BiasRoutingProbe::Normal,
                        parameters: parameter_count(initial, kind, schedule) as u64,
                    }
                })
                .collect(),
        },
    )
    .collect()
}

fn run_cancellation(
    source: &ExternalDatasetMapped,
    staged: &HyperEncoderStagedInput,
    initial: &HyperEncoderWeights,
    schedule: &DiagnosticSchedule,
) -> Result<CancellationReceipt, CandleTrainerError> {
    let aggregate = train_once(
        source,
        staged,
        &schedule.examples,
        analysis_optimizer(schedule.examples.len()),
        initial.clone(),
    )?;
    let midpoint = schedule.examples.len() / 2;
    let left_examples = slice_examples(&schedule.examples, 0..midpoint);
    let right_examples = slice_examples(&schedule.examples, midpoint..schedule.examples.len());
    let left = train_once(
        source,
        staged,
        &left_examples,
        analysis_optimizer(left_examples.len()),
        initial.clone(),
    )?;
    let right = train_once(
        source,
        staged,
        &right_examples,
        analysis_optimizer(right_examples.len()),
        initial.clone(),
    )?;
    let mut sums = [0.0_f64; BLOCKS.len()];
    let mut agreements = [0_u64; BLOCKS.len()];
    let mut comparisons = [0_u64; BLOCKS.len()];
    for index in 0..schedule.examples.len() {
        let one = slice_examples(&schedule.examples, index..index + 1);
        let outcome = train_once(source, staged, &one, analysis_optimizer(1), initial.clone())?;
        for (block_index, kind) in BLOCKS.iter().copied().enumerate() {
            sums[block_index] += delta_norm(initial, &outcome.weights, kind, schedule);
            compare_signs(
                initial,
                &aggregate.weights,
                &outcome.weights,
                kind,
                schedule,
                &mut agreements[block_index],
                &mut comparisons[block_index],
            );
        }
    }
    let blocks = BLOCKS
        .iter()
        .copied()
        .enumerate()
        .map(|(index, kind)| {
            let aggregate_norm = delta_norm(initial, &aggregate.weights, kind, schedule);
            CancellationBlockReceipt {
                name: block_name(kind).into(),
                aggregate_gradient_l2: aggregate_norm,
                sum_individual_gradient_l2: sums[index],
                cancellation_ratio: (1.0 - ratio(aggregate_norm, sums[index])).clamp(0.0, 1.0),
                sign_agreement: ratio(agreements[index] as f64, comparisons[index] as f64),
                nonzero_sign_comparisons: comparisons[index],
            }
        })
        .collect();
    Ok(CancellationReceipt {
        stratum: schedule.name.clone(),
        examples: schedule.examples.len() as u64,
        schedule_blake3: schedule.examples.schedule_blake3.as_str().into(),
        split_half_cosine_similarity: delta_cosine(initial, &left.weights, &right.weights),
        blocks,
    })
}

fn train_once(
    source: &ExternalDatasetMapped,
    staged: &HyperEncoderStagedInput,
    examples: &crate::hyper_encoder_examples::PreparedHyperExamples,
    optimizer: HyperOptimizerConfig,
    weights: HyperEncoderWeights,
) -> Result<FusedHyperTrainingOutcome, CandleTrainerError> {
    train_fused_hyper_encoder16_with_optimizer(
        source,
        staged,
        examples,
        HyperEncoderMode::StareQualifiers,
        training_config(),
        optimizer,
        weights,
    )
}

fn training_config() -> HyperEncoderTrainingConfig {
    HyperEncoderTrainingConfig {
        epochs: 1,
        learning_rate: LEARNING_RATE,
        l2: 0.0,
        negatives_per_positive: 1,
    }
}

fn pressure_optimizer(examples: usize) -> HyperOptimizerConfig {
    HyperOptimizerConfig {
        algorithm: HyperOptimizerAlgorithm::DeterministicBatchSgd,
        learning_rate: LEARNING_RATE,
        loss_reduction: HyperLossReduction::Sum,
        batch_size: examples as u32,
        gradient_accumulation_steps: 1,
        global_loss_scale: LOSS_SCALE,
        loss_scale_semantics: LossScaleSemantics::ClipScaledGradient,
        gradient_clip_policy: HyperGradientClipPolicy::GlobalNorm,
        gradient_clip_norm: CLIP_NORM,
        weight_decay: 0.0,
        weight_decay_semantics: HyperWeightDecaySemantics::None,
        qualified_sampling_policy: QualifiedSamplingPolicy::Natural,
    }
}

fn analysis_optimizer(examples: usize) -> HyperOptimizerConfig {
    HyperOptimizerConfig {
        algorithm: HyperOptimizerAlgorithm::DeterministicBatchSgd,
        learning_rate: 1.0,
        loss_reduction: HyperLossReduction::Sum,
        batch_size: examples as u32,
        gradient_accumulation_steps: 1,
        global_loss_scale: 1.0,
        loss_scale_semantics: LossScaleSemantics::UnscaleBeforeClip,
        gradient_clip_policy: HyperGradientClipPolicy::None,
        gradient_clip_norm: 0.0,
        weight_decay: 0.0,
        weight_decay_semantics: HyperWeightDecaySemantics::None,
        qualified_sampling_policy: QualifiedSamplingPolicy::Natural,
    }
}

fn economics(e: &crate::HyperEpochEconomics, kind: BlockKind) -> Option<GradientBlockEconomics> {
    match kind {
        BlockKind::Entity => Some(e.entity_embeddings),
        BlockKind::Relation => Some(e.relation_embeddings),
        BlockKind::RelationProjection => Some(e.relation_projection),
        BlockKind::QualifierProjection => Some(e.qualifier_projection),
        BlockKind::Direction => Some(e.direction_matrices),
        BlockKind::DecoderBias => Some(e.decoder_bias),
        BlockKind::QualifierValues | BlockKind::QualifierRoles => None,
    }
}

fn block_name(kind: BlockKind) -> &'static str {
    match kind {
        BlockKind::Entity => "entity-embeddings",
        BlockKind::Relation => "relation-embeddings",
        BlockKind::RelationProjection => "relation-projection",
        BlockKind::QualifierProjection => "qualifier-projection",
        BlockKind::Direction => "direction-matrices",
        BlockKind::DecoderBias => "decoder-bias",
        BlockKind::QualifierValues => "qualifier-value-embeddings",
        BlockKind::QualifierRoles => "qualifier-role-embeddings",
    }
}

fn values(weights: &HyperEncoderWeights, kind: BlockKind) -> &[f32] {
    match kind {
        BlockKind::Entity | BlockKind::QualifierValues => &weights.node_embeddings,
        BlockKind::Relation | BlockKind::QualifierRoles => &weights.relation_embeddings,
        BlockKind::RelationProjection => &weights.relation_projection,
        BlockKind::QualifierProjection => &weights.qualifier_projection,
        BlockKind::Direction => &weights.direction_weights,
        BlockKind::DecoderBias => &weights.decoder_bias,
    }
}

fn rows(kind: BlockKind, schedule: &DiagnosticSchedule) -> Option<&[u32]> {
    match kind {
        BlockKind::QualifierValues => Some(&schedule.qualifier_value_rows),
        BlockKind::QualifierRoles => Some(&schedule.qualifier_role_rows),
        _ => None,
    }
}

fn visit(kind: BlockKind, schedule: &DiagnosticSchedule, mut visit: impl FnMut(usize)) {
    if let Some(rows) = rows(kind, schedule) {
        for &row in rows {
            let start = row as usize * HYPER_ENCODER_HIDDEN;
            for index in start..start + HYPER_ENCODER_HIDDEN {
                visit(index);
            }
        }
    } else {
        for index in 0..selected_parameters(kind, schedule) {
            visit(index);
        }
    }
}

fn selected_parameters(kind: BlockKind, schedule: &DiagnosticSchedule) -> usize {
    rows(kind, schedule).map_or_else(|| 0, |rows| rows.len() * HYPER_ENCODER_HIDDEN)
}

fn parameter_count(
    weights: &HyperEncoderWeights,
    kind: BlockKind,
    schedule: &DiagnosticSchedule,
) -> usize {
    rows(kind, schedule).map_or_else(
        || values(weights, kind).len(),
        |rows| rows.len() * HYPER_ENCODER_HIDDEN,
    )
}

fn parameter_norm(
    weights: &HyperEncoderWeights,
    kind: BlockKind,
    schedule: &DiagnosticSchedule,
) -> f64 {
    let tensor = values(weights, kind);
    let mut squared = 0.0;
    if rows(kind, schedule).is_some() {
        visit(kind, schedule, |i| squared += f64::from(tensor[i]).powi(2));
    } else {
        squared = tensor.iter().map(|v| f64::from(*v).powi(2)).sum();
    }
    squared.sqrt()
}

fn delta_norm(
    before: &HyperEncoderWeights,
    after: &HyperEncoderWeights,
    kind: BlockKind,
    schedule: &DiagnosticSchedule,
) -> f64 {
    let left = values(before, kind);
    let right = values(after, kind);
    let mut squared = 0.0;
    let mut add = |i: usize| squared += f64::from(right[i] - left[i]).powi(2);
    if rows(kind, schedule).is_some() {
        visit(kind, schedule, &mut add);
    } else {
        for i in 0..left.len() {
            add(i);
        }
    }
    squared.sqrt()
}

fn changed_bits(
    before: &HyperEncoderWeights,
    after: &HyperEncoderWeights,
    kind: BlockKind,
    schedule: &DiagnosticSchedule,
) -> u64 {
    let left = values(before, kind);
    let right = values(after, kind);
    let mut changed = 0;
    let mut count = |i: usize| changed += u64::from(left[i].to_bits() != right[i].to_bits());
    if rows(kind, schedule).is_some() {
        visit(kind, schedule, &mut count);
    } else {
        for i in 0..left.len() {
            count(i);
        }
    }
    changed
}

fn compare_signs(
    initial: &HyperEncoderWeights,
    aggregate: &HyperEncoderWeights,
    individual: &HyperEncoderWeights,
    kind: BlockKind,
    schedule: &DiagnosticSchedule,
    agreements: &mut u64,
    comparisons: &mut u64,
) {
    let base = values(initial, kind);
    let sum = values(aggregate, kind);
    let one = values(individual, kind);
    let mut compare = |i: usize| {
        let aggregate_sign = (base[i] - sum[i]).signum();
        let individual_sign = (base[i] - one[i]).signum();
        if aggregate_sign != 0.0 && individual_sign != 0.0 {
            *comparisons += 1;
            *agreements += u64::from(aggregate_sign == individual_sign);
        }
    };
    if rows(kind, schedule).is_some() {
        visit(kind, schedule, &mut compare);
    } else {
        for i in 0..base.len() {
            compare(i);
        }
    }
}

fn delta_cosine(
    initial: &HyperEncoderWeights,
    left: &HyperEncoderWeights,
    right: &HyperEncoderWeights,
) -> f64 {
    let mut dot = 0.0;
    let mut left_squared = 0.0;
    let mut right_squared = 0.0;
    for kind in BLOCKS[..6].iter().copied() {
        for ((base, a), b) in values(initial, kind)
            .iter()
            .zip(values(left, kind))
            .zip(values(right, kind))
        {
            let x = f64::from(*base - *a);
            let y = f64::from(*base - *b);
            dot += x * y;
            left_squared += x * x;
            right_squared += y * y;
        }
    }
    ratio(dot, (left_squared * right_squared).sqrt())
}

fn clip(norm: f64) -> f64 {
    if norm <= f64::from(CLIP_NORM) {
        1.0
    } else {
        f64::from(CLIP_NORM) / norm
    }
}
fn ratio(numerator: f64, denominator: f64) -> f64 {
    if denominator == 0.0 {
        0.0
    } else {
        numerator / denominator
    }
}
fn share(norm: f64, global: f64) -> f64 {
    ratio(norm * norm, global * global)
}

fn block<'a>(blocks: &'a [GradientPressureBlock], name: &str) -> &'a GradientPressureBlock {
    blocks
        .iter()
        .find(|block| block.name == name)
        .expect("pressure block")
}

pub(crate) fn decide(
    pressure: &[NegativePressureReceipt],
    cancellation: &[CancellationReceipt],
) -> Result<PressureDecision, CandleTrainerError> {
    let real = pressure
        .iter()
        .filter(|r| r.kind == NegativePressureKind::FrozenRealBatch)
        .collect::<Vec<_>>();
    if real.is_empty() {
        return Err(CandleTrainerError::Contract("real batch pressure"));
    }
    let primary = pressure
        .iter()
        .find(|r| r.kind == NegativePressureKind::PrimaryTarget)
        .ok_or(CandleTrainerError::Contract("primary pressure"))?;
    let qualifier_max = pressure
        .iter()
        .filter(|r| {
            matches!(
                r.kind,
                NegativePressureKind::QualifierValue | NegativePressureKind::QualifierRole
            )
        })
        .map(|r| block(&r.blocks, "qualifier-projection").raw_gradient_l2)
        .fold(0.0_f64, f64::max);
    let primary_qualifier = block(&primary.blocks, "qualifier-projection").raw_gradient_l2;
    let clipping = real
        .iter()
        .filter(|receipt| {
            receipt.global_clip_coefficient < 0.01 && receipt.decoder_bias_norm_share > 0.5
        })
        .count()
        * 2
        >= real.len();
    let objective = qualifier_max > primary_qualifier * 10.0;
    let cancellation_dominant = cancellation
        .iter()
        .filter_map(|r| r.blocks.iter().find(|b| b.name == "qualifier-projection"))
        .any(|b| b.cancellation_ratio > 0.9);
    Ok(match (clipping, objective, cancellation_dominant) {
        (true, true, _) => PressureDecision::ClippingAndObjective,
        (true, false, _) => PressureDecision::ClippingDominant,
        (false, true, _) => PressureDecision::ObjectiveDominant,
        (false, false, true) => PressureDecision::CancellationDominant,
        (false, false, false) => PressureDecision::HealthyQualifierPressure,
    })
}

fn next_cut(decision: PressureDecision) -> &'static str {
    match decision {
        PressureDecision::ClippingAndObjective => {
            "Pressure Routing v1, then Qualifier-Negative Objective v1 as separate certified cuts"
        }
        PressureDecision::ClippingDominant => "Pressure Routing v1 with isolated clipping groups",
        PressureDecision::ObjectiveDominant => "Qualifier-Negative Objective v1",
        PressureDecision::CancellationDominant => "Deterministic Qualifier-Stratified Batching v1",
        PressureDecision::HealthyQualifierPressure => "one corrected narrow WD50K optimization run",
    }
}

fn decision_evidence(
    decision: PressureDecision,
    pressure: &[NegativePressureReceipt],
    cancellation: &[CancellationReceipt],
) -> CompactString {
    let mut hasher = blake3::Hasher::new();
    hasher.update(&[decision as u8]);
    for receipt in pressure {
        hasher.update(&[receipt.kind as u8]);
        hasher.update(receipt.schedule_name.as_bytes());
        hasher.update(&receipt.raw_global_gradient_l2.to_bits().to_le_bytes());
        hasher.update(&receipt.global_clip_coefficient.to_bits().to_le_bytes());
        for block in &receipt.blocks {
            hasher.update(block.name.as_bytes());
            hasher.update(&block.raw_gradient_l2.to_bits().to_le_bytes());
        }
    }
    for receipt in cancellation {
        hasher.update(receipt.stratum.as_bytes());
        for block in &receipt.blocks {
            hasher.update(&block.cancellation_ratio.to_bits().to_le_bytes());
        }
    }
    format_compact!("b3-{}", hasher.finalize().to_hex())
}

fn seal_receipt(
    receipt: &GradientPressureAuditReceipt,
) -> Result<(CompactString, Vec<u8>), CandleTrainerError> {
    let bytes = serde_json::to_vec_pretty(receipt)?;
    let hash = blake3::hash(&bytes);
    let id = format_compact!("b3-{}", hash.to_hex());
    let text = String::from_utf8(bytes)
        .map_err(|_| CandleTrainerError::Contract("gradient pressure UTF-8"))?;
    let durable = text.replacen(ID_PLACEHOLDER, id.as_str(), 1).into_bytes();
    Ok((id, durable))
}

fn identity_from_bytes(bytes: &[u8], stored: &str) -> Result<CompactString, CandleTrainerError> {
    if stored.len() != ID_PLACEHOLDER.len() {
        return Err(CandleTrainerError::Contract("gradient pressure id shape"));
    }
    let text = std::str::from_utf8(bytes)
        .map_err(|_| CandleTrainerError::Contract("gradient pressure UTF-8"))?;
    let pending = text.replacen(stored, ID_PLACEHOLDER, 1);
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(pending.as_bytes()).to_hex()
    ))
}

fn write_new_durable(path: &Path, bytes: &[u8]) -> Result<(), CandleTrainerError> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
