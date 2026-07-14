use crate::hyper_encoder_examples::{prepare_hyper_examples, PreparedHyperExamples};
use crate::hyper_encoder_memory::{
    train_fused_hyper_encoder16_with_optimizer, FusedHyperTrainingOutcome,
};
use crate::hyper_learning_gate_metrics::{economics_gradient_norm, tensor_delta, weights_digest};
use crate::optimization_envelope_eval::{
    evaluate_validation, score_train_examples, structural_slices, write_causal_deltas, write_ranks,
};
use crate::optimization_envelope_model::*;
use crate::{
    CandleTrainerError, GradientBlockEconomics, HyperEpochEconomics, HyperGradientClipPolicy,
    HyperLossReduction, HyperOptimizerAlgorithm, HyperOptimizerConfig, HyperWeightDecaySemantics,
    LossScaleSemantics, QualifiedSamplingPolicy,
};
use compact_str::{format_compact, CompactString};
use phoenix_graph_research::{
    encode_hyper_encoder, hyper_encoder_model_identity, initialize_hyper_encoder_weights,
    stage_hyper_encoder, write_hyper_encoder_model, write_qualifier_null_composition,
    ExternalDatasetMapped, HyperEncoderConfig, HyperEncoderMapped, HyperEncoderMode,
    HyperEncoderModelPaths, HyperEncoderModelSnapshot, HyperEncoderStagedInput,
    HyperEncoderTrainingConfig, HyperEncoderTrainingReceipt, HyperEncoderWeights,
    HyperRelationalQueryRank, HyperRelationalTaskMapped, QualifierNullCompositionMapped,
};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

const BATCH_SIZE: u32 = 65_536;
const LEARNING_RATE: f32 = 0.02;
const LOSS_SCALE: f32 = 256.0;
const CLIP_NORM: f32 = 1.0;
const ENVELOPE_ID_PLACEHOLDER: &str =
    "b3-0000000000000000000000000000000000000000000000000000000000000000";

struct ArmState {
    mode: HyperEncoderMode,
    weights: HyperEncoderWeights,
    optimizer_steps: u64,
    clipped_steps: u64,
    gradient_arena_bytes: u64,
    last_economics: Option<HyperEpochEconomics>,
}

struct PersistedArm {
    checkpoint: EnvelopeArmCheckpoint,
    ranks: Vec<HyperRelationalQueryRank>,
    paths: HyperEncoderModelPaths,
}

pub fn run_optimization_envelope_v1(
    request: &OptimizationEnvelopeRequest,
) -> Result<OptimizationEnvelopePaths, CandleTrainerError> {
    std::fs::create_dir_all(&request.output_root)?;
    let source = ExternalDatasetMapped::open(&request.source_manifest)?;
    let task = HyperRelationalTaskMapped::open(&request.task_manifest, &source)?;
    let staged = stage_hyper_encoder(&source, &task)?;
    let training_config = frozen_training_config();
    let examples = prepare_hyper_examples(
        &source,
        &staged,
        HyperEncoderTrainingConfig {
            epochs: 1,
            ..training_config
        },
        OPTIMIZATION_ENVELOPE_SEED,
    )?;
    let optimizer = optimizer_recipe();
    optimizer.validate(examples.len())?;
    let optimizer_identity = optimizer.identity()?;
    let initial = initialize_hyper_encoder_weights(&staged, OPTIMIZATION_ENVELOPE_SEED);
    let initialization_blake3 = weights_digest(&initial);
    let lineage_id = lineage_identity(
        &staged,
        examples.schedule_blake3.as_str(),
        optimizer_identity.as_str(),
        initialization_blake3.as_str(),
    );
    let mut comp = ArmState::new(HyperEncoderMode::CompgcnTriple, initial.clone());
    let mut value = ArmState::new(HyperEncoderMode::ValueOnly, initial.clone());
    let mut full = ArmState::new(HyperEncoderMode::StareQualifiers, initial.clone());
    let mut checkpoint_zero_full = None::<PathBuf>;
    let mut completed = Vec::with_capacity(OPTIMIZATION_ENVELOPE_CHECKPOINTS.len());
    let mut previous_epoch = 0_u32;

    for epoch in OPTIMIZATION_ENVELOPE_CHECKPOINTS {
        let delta = epoch - previous_epoch;
        if delta != 0 {
            train_delta(&source, &staged, &examples, optimizer, delta, &mut comp)?;
            train_delta(&source, &staged, &examples, optimizer, delta, &mut value)?;
            train_delta(&source, &staged, &examples, optimizer, delta, &mut full)?;
        }
        let comp_arm = persist_trained_arm(
            &request.output_root,
            &source,
            &task,
            &staged,
            &examples,
            &initial,
            &lineage_id,
            &initialization_blake3,
            optimizer_identity.as_str(),
            epoch,
            EnvelopeArm::Compgcn,
            &comp,
            training_config,
        )?;
        let value_arm = persist_trained_arm(
            &request.output_root,
            &source,
            &task,
            &staged,
            &examples,
            &initial,
            &lineage_id,
            &initialization_blake3,
            optimizer_identity.as_str(),
            epoch,
            EnvelopeArm::ValueOnly,
            &value,
            training_config,
        )?;
        let full_arm = persist_trained_arm(
            &request.output_root,
            &source,
            &task,
            &staged,
            &examples,
            &initial,
            &lineage_id,
            &initialization_blake3,
            optimizer_identity.as_str(),
            epoch,
            EnvelopeArm::FullStare,
            &full,
            training_config,
        )?;
        if epoch == 0 {
            checkpoint_zero_full = Some(full_arm.paths.manifest.clone());
        }
        let null_arm = persist_null_arm(
            &request.output_root,
            &source,
            &task,
            &staged,
            &examples,
            &initial,
            epoch,
            optimizer_identity.as_str(),
            &comp_arm,
            checkpoint_zero_full
                .as_ref()
                .ok_or(CandleTrainerError::Contract(
                    "checkpoint zero qualifier model",
                ))?,
            &comp,
        )?;
        let causal_rank_deltas = write_causal_deltas(
            &request.output_root,
            &comp_arm.ranks,
            &null_arm.ranks,
            &value_arm.ranks,
            &full_arm.ranks,
        )?;
        let comp_mrr = comp_arm.checkpoint.validation.metrics.mean_reciprocal_rank;
        let null_mrr = null_arm.checkpoint.validation.metrics.mean_reciprocal_rank;
        let value_mrr = value_arm.checkpoint.validation.metrics.mean_reciprocal_rank;
        let full_mrr = full_arm.checkpoint.validation.metrics.mean_reciprocal_rank;
        completed.push(EnvelopeCheckpoint {
            epoch,
            arms: vec![
                comp_arm.checkpoint,
                null_arm.checkpoint,
                value_arm.checkpoint,
                full_arm.checkpoint,
            ],
            causal_rank_deltas,
            fixed_qualifier_feature_mrr_delta: null_mrr - comp_mrr,
            qualifier_conditioned_learning_mrr_delta: full_mrr - null_mrr,
            total_qualifier_value_mrr_delta: value_mrr - comp_mrr,
        });
        previous_epoch = epoch;
    }

    let mut manifest = OptimizationEnvelopeManifest {
        schema_version: OPTIMIZATION_ENVELOPE_SCHEMA.into(),
        envelope_id: "pending".into(),
        trainer_id: OPTIMIZATION_ENVELOPE_TRAINER.into(),
        source_dataset_id: staged.source_dataset_id.clone(),
        source_binary_blake3: staged.source_binary_blake3.clone(),
        task_id: staged.task_id.clone(),
        task_binary_blake3: staged.task_binary_blake3.clone(),
        seed: OPTIMIZATION_ENVELOPE_SEED,
        checkpoints: completed,
        optimizer,
        optimizer_identity,
        initialization_blake3,
        example_schedule_blake3: examples.schedule_blake3.as_str().into(),
        training_examples: examples.len() as u64,
        test_partition_accessed: false,
        validation_only: true,
        cumulative_checkpoint_lineage: true,
        exact_rank_encoding: "little-endian-u64-doubled-filtered-rank/query-order/v1".into(),
        relation_frequency_authority: "train-primary-facts/log2-buckets/v1".into(),
        entity_degree_authority: "train-primary-undirected-target-degree/log2-buckets/v1".into(),
        independent_replay_required: true,
    };
    let (envelope_id, durable) = seal_envelope_bytes(&manifest)?;
    manifest.envelope_id = envelope_id;
    let path = request.output_root.join(format!(
        "{}.optimization-envelope.json",
        manifest.envelope_id
    ));
    write_new_durable(&path, &durable)?;
    let reopened = open_optimization_envelope(&path)?;
    if reopened.envelope_id != manifest.envelope_id {
        return Err(CandleTrainerError::Contract(
            "envelope durable semantic replay",
        ));
    }
    Ok(OptimizationEnvelopePaths {
        manifest: path,
        envelope_id: manifest.envelope_id,
    })
}

pub fn open_optimization_envelope(
    path: impl AsRef<Path>,
) -> Result<OptimizationEnvelopeManifest, CandleTrainerError> {
    let bytes = std::fs::read(path.as_ref())?;
    let manifest: OptimizationEnvelopeManifest = serde_json::from_slice(&bytes)?;
    if manifest.schema_version != OPTIMIZATION_ENVELOPE_SCHEMA
        || manifest.envelope_id != envelope_identity_from_bytes(&bytes, &manifest.envelope_id)?
        || manifest.test_partition_accessed
        || !manifest.validation_only
        || manifest.checkpoints.len() != OPTIMIZATION_ENVELOPE_CHECKPOINTS.len()
    {
        return Err(CandleTrainerError::Contract(
            "envelope durable identity replay",
        ));
    }
    Ok(manifest)
}

impl ArmState {
    fn new(mode: HyperEncoderMode, weights: HyperEncoderWeights) -> Self {
        Self {
            mode,
            weights,
            optimizer_steps: 0,
            clipped_steps: 0,
            gradient_arena_bytes: 0,
            last_economics: None,
        }
    }
}

fn train_delta(
    source: &ExternalDatasetMapped,
    staged: &HyperEncoderStagedInput,
    examples: &PreparedHyperExamples,
    optimizer: HyperOptimizerConfig,
    epochs: u32,
    state: &mut ArmState,
) -> Result<(), CandleTrainerError> {
    let outcome = train_fused_hyper_encoder16_with_optimizer(
        source,
        staged,
        examples,
        state.mode,
        HyperEncoderTrainingConfig {
            epochs,
            learning_rate: LEARNING_RATE,
            l2: 0.0,
            negatives_per_positive: 1,
        },
        optimizer,
        state.weights.clone(),
    )?;
    absorb_outcome(state, outcome);
    Ok(())
}

fn absorb_outcome(state: &mut ArmState, outcome: FusedHyperTrainingOutcome) {
    state.optimizer_steps += outcome.optimizer_steps;
    state.clipped_steps +=
        (outcome.final_epoch.clip_activation_rate * outcome.optimizer_steps as f64).round() as u64;
    state.gradient_arena_bytes = outcome.gradient_arena_bytes;
    state.last_economics = Some(outcome.final_epoch);
    state.weights = outcome.weights;
}

#[allow(clippy::too_many_arguments)]
fn persist_trained_arm(
    root: &Path,
    source: &ExternalDatasetMapped,
    task: &HyperRelationalTaskMapped,
    staged: &HyperEncoderStagedInput,
    examples: &PreparedHyperExamples,
    initial: &HyperEncoderWeights,
    lineage_id: &CompactString,
    initialization_blake3: &CompactString,
    optimizer_identity: &str,
    epoch: u32,
    arm: EnvelopeArm,
    state: &ArmState,
    training_config: HyperEncoderTrainingConfig,
) -> Result<PersistedArm, CandleTrainerError> {
    let config = HyperEncoderConfig::with_mode(OPTIMIZATION_ENVELOPE_SEED, state.mode);
    let model_id = hyper_encoder_model_identity(staged, config, &state.weights)?;
    let encoded = encode_hyper_encoder(source, staged, config, &state.weights)?;
    let train = score_train_examples(source, &encoded, examples)?;
    let evaluation = evaluate_validation(source, task, &encoded)?;
    drop(encoded);
    let snapshot = HyperEncoderModelSnapshot {
        pair_id: lineage_id.clone(),
        source_dataset_id: staged.source_dataset_id.clone(),
        source_binary_blake3: staged.source_binary_blake3.clone(),
        task_id: staged.task_id.clone(),
        task_binary_blake3: staged.task_binary_blake3.clone(),
        candidate_universe: staged.candidate_universe,
        base_relation_count: staged.base_relation_count,
        config,
        training_config,
        training: training_receipt(
            staged,
            examples,
            initialization_blake3,
            optimizer_identity,
            state,
        ),
        validation: evaluation.certificate.clone(),
        weights: state.weights.clone(),
    };
    if evaluation.certificate.model_id != model_id {
        return Err(CandleTrainerError::Contract("envelope model identity"));
    }
    let paths = write_hyper_encoder_model(&snapshot, root)?;
    let ranks_receipt = write_ranks(root, &evaluation.ranks)?;
    let structural = structural_slices(
        source,
        &evaluation.ranks,
        task.manifest().candidate_universe as u64,
        staged.base_relation_count,
    )?;
    let mapped = HyperEncoderMapped::open(&paths.manifest)?;
    let restarted_weights = mapped.weights()?;
    let restarted =
        encode_hyper_encoder(source, staged, mapped.manifest().config, &restarted_weights)?;
    let replay = evaluate_validation(source, task, &restarted)?;
    let cold_restart_exact = replay == evaluation;
    if !cold_restart_exact {
        return Err(CandleTrainerError::Contract("envelope cold restart parity"));
    }
    let economics = state.last_economics.unwrap_or_else(empty_economics);
    let pre_clip = state
        .last_economics
        .as_ref()
        .map(economics_gradient_norm)
        .unwrap_or(0.0);
    Ok(PersistedArm {
        checkpoint: EnvelopeArmCheckpoint {
            arm,
            checkpoint_epoch: epoch,
            model_id: paths.model_id.clone(),
            model_manifest_id: paths.manifest_id.clone(),
            model_manifest_file: file_name(&paths.manifest)?,
            base_checkpoint_model_id: None,
            qualifier_parameter_source_model_id: None,
            routing_digest: None,
            train,
            validation: evaluation.certificate,
            structural_slices: structural,
            ranks: ranks_receipt,
            parameter_blocks: parameter_blocks(initial, &state.weights, economics),
            final_batch: state.last_economics,
            pre_clip_gradient_norm: pre_clip,
            clip_coefficient: state
                .last_economics
                .map(|value| f64::from(value.clip_coefficient))
                .unwrap_or(1.0),
            clip_activation_rate: state.clipped_steps as f64 / state.optimizer_steps.max(1) as f64,
            optimizer_steps: state.optimizer_steps,
            cold_restart_exact,
        },
        ranks: evaluation.ranks,
        paths,
    })
}

#[allow(clippy::too_many_arguments)]
fn persist_null_arm(
    root: &Path,
    source: &ExternalDatasetMapped,
    task: &HyperRelationalTaskMapped,
    staged: &HyperEncoderStagedInput,
    examples: &PreparedHyperExamples,
    initial: &HyperEncoderWeights,
    epoch: u32,
    optimizer_identity: &str,
    comp: &PersistedArm,
    checkpoint_zero: &Path,
    comp_state: &ArmState,
) -> Result<PersistedArm, CandleTrainerError> {
    let paths = write_qualifier_null_composition(
        &comp.paths.manifest,
        checkpoint_zero,
        optimizer_identity,
        epoch,
        root,
    )?;
    let mapped = QualifierNullCompositionMapped::open(&paths.manifest)?;
    let routing = mapped.routing_receipt(source, staged)?;
    let encoded = mapped.encode(source, staged)?;
    let train = score_train_examples(source, &encoded, examples)?;
    let evaluation = evaluate_validation(source, task, &encoded)?;
    let replay_mapped = QualifierNullCompositionMapped::open(&paths.manifest)?;
    let replay_encoded = replay_mapped.encode(source, staged)?;
    let replay = evaluate_validation(source, task, &replay_encoded)?;
    if replay != evaluation {
        return Err(CandleTrainerError::Contract(
            "qualifier null cold restart parity",
        ));
    }
    let ranks_receipt = write_ranks(root, &evaluation.ranks)?;
    let structural = structural_slices(
        source,
        &evaluation.ranks,
        task.manifest().candidate_universe as u64,
        staged.base_relation_count,
    )?;
    let economics = comp_state.last_economics.unwrap_or_else(empty_economics);
    let pre_clip = comp_state
        .last_economics
        .as_ref()
        .map(economics_gradient_norm)
        .unwrap_or(0.0);
    Ok(PersistedArm {
        checkpoint: EnvelopeArmCheckpoint {
            arm: EnvelopeArm::QualifierGradientNull,
            checkpoint_epoch: epoch,
            model_id: paths.composition_id.clone(),
            model_manifest_id: paths.composition_id.clone(),
            model_manifest_file: file_name(&paths.manifest)?,
            base_checkpoint_model_id: Some(comp.paths.model_id.clone()),
            qualifier_parameter_source_model_id: Some(
                mapped.manifest().checkpoint_zero_model_id.clone(),
            ),
            routing_digest: Some(routing.routing_digest),
            train,
            validation: evaluation.certificate,
            structural_slices: structural,
            ranks: ranks_receipt,
            parameter_blocks: null_parameter_blocks(initial, &comp_state.weights, economics),
            final_batch: comp_state.last_economics,
            pre_clip_gradient_norm: pre_clip,
            clip_coefficient: comp_state
                .last_economics
                .map(|value| f64::from(value.clip_coefficient))
                .unwrap_or(1.0),
            clip_activation_rate: comp_state.clipped_steps as f64
                / comp_state.optimizer_steps.max(1) as f64,
            optimizer_steps: comp_state.optimizer_steps,
            cold_restart_exact: true,
        },
        ranks: evaluation.ranks,
        paths: HyperEncoderModelPaths {
            manifest: paths.manifest,
            model_id: paths.composition_id.clone(),
            manifest_id: paths.composition_id,
            weights: PathBuf::new(),
        },
    })
}

fn training_receipt(
    staged: &HyperEncoderStagedInput,
    examples: &PreparedHyperExamples,
    initialization: &str,
    optimizer_identity: &str,
    state: &ArmState,
) -> HyperEncoderTrainingReceipt {
    HyperEncoderTrainingReceipt {
        trainer_id: format_compact!("{OPTIMIZATION_ENVELOPE_TRAINER}:{optimizer_identity}"),
        initialization_blake3: initialization.into(),
        train_topology_blake3: staged.profile.train_topology_blake3.clone(),
        example_schedule_blake3: examples.schedule_blake3.as_str().into(),
        train_statements: staged.profile.train_statements,
        directed_messages: staged.profile.directed_messages,
        training_examples: examples.len() as u64,
        optimizer_steps: state.optimizer_steps,
        optimizer_state_blake3: weights_digest(&state.weights),
        gradient_arena_bytes: state.gradient_arena_bytes,
        epoch_allocation_bytes: 0,
        epoch_allocation_count: 0,
        test_locked_during_training: true,
    }
}

fn parameter_blocks(
    before: &HyperEncoderWeights,
    after: &HyperEncoderWeights,
    economics: HyperEpochEconomics,
) -> Vec<ParameterBlockReceipt> {
    vec![
        block(
            "entity-embeddings",
            &before.node_embeddings,
            &after.node_embeddings,
            economics.entity_embeddings,
        ),
        block(
            "relation-embeddings",
            &before.relation_embeddings,
            &after.relation_embeddings,
            economics.relation_embeddings,
        ),
        block(
            "relation-projection",
            &before.relation_projection,
            &after.relation_projection,
            economics.relation_projection,
        ),
        block(
            "qualifier-projection",
            &before.qualifier_projection,
            &after.qualifier_projection,
            economics.qualifier_projection,
        ),
        block(
            "direction-matrices",
            &before.direction_weights,
            &after.direction_weights,
            economics.direction_matrices,
        ),
        block(
            "decoder-bias",
            &before.decoder_bias,
            &after.decoder_bias,
            economics.decoder_bias,
        ),
    ]
}

fn null_parameter_blocks(
    initial: &HyperEncoderWeights,
    trained: &HyperEncoderWeights,
    mut economics: HyperEpochEconomics,
) -> Vec<ParameterBlockReceipt> {
    economics.qualifier_projection = empty_block(initial.qualifier_projection.len());
    let mut blocks = parameter_blocks(initial, trained, economics);
    blocks[3].delta = tensor_delta(&initial.qualifier_projection, &initial.qualifier_projection);
    blocks
}

fn block(
    name: &str,
    before: &[f32],
    after: &[f32],
    economics: GradientBlockEconomics,
) -> ParameterBlockReceipt {
    ParameterBlockReceipt {
        name: name.into(),
        delta: tensor_delta(before, after),
        economics,
    }
}

fn empty_block(parameters: usize) -> GradientBlockEconomics {
    GradientBlockEconomics {
        gradient_l2: 0.0,
        parameter_l2: 0.0,
        update_l2: 0.0,
        update_to_weight: 0.0,
        exactly_zero_gradients: parameters as u64,
        parameters: parameters as u64,
    }
}

fn empty_economics() -> HyperEpochEconomics {
    HyperEpochEconomics {
        mean_binary_cross_entropy: 0.0,
        clip_coefficient: 1.0,
        clip_activated: false,
        clip_activation_rate: 0.0,
        entity_embeddings: empty_block(0),
        relation_embeddings: empty_block(0),
        relation_projection: empty_block(0),
        qualifier_projection: empty_block(0),
        direction_matrices: empty_block(0),
        decoder_bias: empty_block(0),
    }
}

fn optimizer_recipe() -> HyperOptimizerConfig {
    HyperOptimizerConfig {
        algorithm: HyperOptimizerAlgorithm::DeterministicBatchSgd,
        learning_rate: LEARNING_RATE,
        loss_reduction: HyperLossReduction::Sum,
        batch_size: BATCH_SIZE,
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

fn frozen_training_config() -> HyperEncoderTrainingConfig {
    HyperEncoderTrainingConfig {
        epochs: *OPTIMIZATION_ENVELOPE_CHECKPOINTS
            .last()
            .expect("checkpoints"),
        learning_rate: LEARNING_RATE,
        l2: 0.0,
        negatives_per_positive: 1,
    }
}

fn lineage_identity(
    staged: &HyperEncoderStagedInput,
    schedule: &str,
    optimizer: &str,
    initialization: &str,
) -> CompactString {
    let mut hasher = blake3::Hasher::new();
    for value in [
        OPTIMIZATION_ENVELOPE_SCHEMA,
        staged.source_dataset_id.as_str(),
        staged.task_id.as_str(),
        schedule,
        optimizer,
        initialization,
    ] {
        hasher.update(&(value.len() as u64).to_le_bytes());
        hasher.update(value.as_bytes());
    }
    format_compact!("b3-{}", hasher.finalize().to_hex())
}

pub fn optimization_envelope_identity(
    manifest: &OptimizationEnvelopeManifest,
) -> Result<CompactString, CandleTrainerError> {
    Ok(seal_envelope_bytes(manifest)?.0)
}

fn seal_envelope_bytes(
    manifest: &OptimizationEnvelopeManifest,
) -> Result<(CompactString, Vec<u8>), CandleTrainerError> {
    let mut identity = manifest.clone();
    identity.envelope_id = ENVELOPE_ID_PLACEHOLDER.into();
    let mut bytes = serde_json::to_vec_pretty(&identity)?;
    let id = format_compact!("b3-{}", blake3::hash(&bytes).to_hex());
    replace_once(
        &mut bytes,
        ENVELOPE_ID_PLACEHOLDER.as_bytes(),
        id.as_bytes(),
    )?;
    Ok((id, bytes))
}

fn envelope_identity_from_bytes(
    bytes: &[u8],
    stored_id: &str,
) -> Result<CompactString, CandleTrainerError> {
    if stored_id.len() != ENVELOPE_ID_PLACEHOLDER.len() {
        return Err(CandleTrainerError::Contract("envelope identity length"));
    }
    let mut normalized = bytes.to_vec();
    replace_once(
        &mut normalized,
        stored_id.as_bytes(),
        ENVELOPE_ID_PLACEHOLDER.as_bytes(),
    )?;
    Ok(format_compact!("b3-{}", blake3::hash(&normalized).to_hex()))
}

fn replace_once(
    bytes: &mut [u8],
    needle: &[u8],
    replacement: &[u8],
) -> Result<(), CandleTrainerError> {
    let start = bytes
        .windows(needle.len())
        .position(|window| window == needle)
        .ok_or(CandleTrainerError::Contract("envelope identity slot"))?;
    bytes[start..start + needle.len()].copy_from_slice(replacement);
    Ok(())
}

pub fn reseal_optimization_envelope(
    path: impl AsRef<Path>,
) -> Result<OptimizationEnvelopePaths, CandleTrainerError> {
    let path = path.as_ref();
    let mut manifest: OptimizationEnvelopeManifest = serde_json::from_slice(&std::fs::read(path)?)?;
    let (envelope_id, durable) = seal_envelope_bytes(&manifest)?;
    manifest.envelope_id = envelope_id;
    let replacement = path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join(format!(
            "{}.optimization-envelope.json",
            manifest.envelope_id
        ));
    write_new_durable(&replacement, &durable)?;
    let reopened = open_optimization_envelope(&replacement)?;
    if reopened.envelope_id != manifest.envelope_id {
        return Err(CandleTrainerError::Contract("envelope reseal replay"));
    }
    Ok(OptimizationEnvelopePaths {
        manifest: replacement,
        envelope_id: manifest.envelope_id,
    })
}

fn file_name(path: &Path) -> Result<CompactString, CandleTrainerError> {
    path.file_name()
        .and_then(|value| value.to_str())
        .map(Into::into)
        .ok_or(CandleTrainerError::Contract("envelope artifact filename"))
}

fn write_new_durable(path: &Path, bytes: &[u8]) -> Result<(), CandleTrainerError> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
