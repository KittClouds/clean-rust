use crate::hyper_encoder_examples::prepare_hyper_examples;
use crate::hyper_encoder_memory::{train_fused_hyper_encoder16, FusedHyperTrainingOutcome};
use crate::telemetry::{peak_working_set_bytes, AllocationSnapshot};
use crate::CandleTrainerError;
use compact_str::CompactString;
use phoenix_graph_research::{
    encode_hyper_encoder, evaluate_hyper_relational_validation_batched,
    hyper_encoder_model_identity, initialize_hyper_encoder_weights, pair_identity,
    stage_hyper_encoder, write_hyper_encoder_model, write_hyper_encoder_pair,
    ExternalDatasetMapped, HyperEncoderConfig, HyperEncoderMapped, HyperEncoderMode,
    HyperEncoderModelPaths, HyperEncoderModelSnapshot, HyperEncoderPairManifest,
    HyperEncoderPairPaths, HyperEncoderTrainingConfig, HyperEncoderTrainingReceipt,
    HyperEncoderWeights, HyperRelationalCandidatePolicy, HyperRelationalScoreCertificate,
    HyperRelationalTaskMapped, DEFAULT_HYPER_RELATIONAL_QUERY_BATCH, HYPER_ENCODER_PAIR_SCHEMA,
};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::time::Instant;

pub const PAIRED_HYPER_ENCODER_TRAINER_SCHEMA: &str =
    "phoenix-paired-fused-stare-compgcn-trainer/v1";
pub const PAIRED_HYPER_ENCODER_TRAINER_ID: &str = "phoenix-fused-hyper-encoder-e2e/v1";

#[derive(Clone, Debug, PartialEq)]
pub struct PairedHyperEncoderRequest {
    pub source_manifest: PathBuf,
    pub task_manifest: PathBuf,
    pub output_root: PathBuf,
    pub seed: u64,
    pub config: HyperEncoderTrainingConfig,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PairedHyperEncoderReport {
    pub schema_version: CompactString,
    pub pair_id: CompactString,
    pub seed: u64,
    pub training_config: HyperEncoderTrainingConfig,
    pub initialization_blake3: CompactString,
    pub example_schedule_blake3: CompactString,
    pub training_examples: u64,
    pub staging_micros: u64,
    pub compgcn_training_micros: u64,
    pub stare_training_micros: u64,
    pub compgcn_validation_micros: u64,
    pub stare_validation_micros: u64,
    pub restart_micros: u64,
    pub allocation_volume_bytes: u64,
    pub allocation_count: u64,
    pub peak_working_set_bytes: u64,
    pub source_mmap_bytes: u64,
    pub compgcn_model_mmap_bytes: u64,
    pub stare_model_mmap_bytes: u64,
    pub compgcn: HyperRelationalScoreCertificate,
    pub stare: HyperRelationalScoreCertificate,
    pub compgcn_restart_exact: bool,
    pub stare_restart_exact: bool,
    pub model_ids_distinct: bool,
    pub test_partition_accessed: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PairedHyperEncoderOutcome {
    pub compgcn: HyperEncoderModelPaths,
    pub stare: HyperEncoderModelPaths,
    pub pair: HyperEncoderPairPaths,
    pub report: PairedHyperEncoderReport,
}

pub fn train_paired_hyper_encoder16(
    request: &PairedHyperEncoderRequest,
) -> Result<PairedHyperEncoderOutcome, CandleTrainerError> {
    request.config.validate()?;
    let allocations = AllocationSnapshot::now();
    let source = ExternalDatasetMapped::open(&request.source_manifest)?;
    let task = HyperRelationalTaskMapped::open(&request.task_manifest, &source)?;
    let staging_started = Instant::now();
    let staged = stage_hyper_encoder(&source, &task)?;
    let examples = prepare_hyper_examples(&source, &staged, request.config, request.seed)?;
    let staging_micros = micros(staging_started.elapsed());
    let initial = initialize_hyper_encoder_weights(&staged, request.seed);
    let initialization_blake3: CompactString = weights_digest(&initial).into();

    let control_started = Instant::now();
    let control_trained = train_fused_hyper_encoder16(
        &source,
        &staged,
        &examples,
        HyperEncoderMode::CompgcnTriple,
        request.config,
        initial.clone(),
    )?;
    let compgcn_training_micros = micros(control_started.elapsed());
    let stare_started = Instant::now();
    let stare_trained = train_fused_hyper_encoder16(
        &source,
        &staged,
        &examples,
        HyperEncoderMode::StareQualifiers,
        request.config,
        initial,
    )?;
    let stare_training_micros = micros(stare_started.elapsed());

    let control_config = HyperEncoderConfig::compgcn(request.seed);
    let stare_config = HyperEncoderConfig::stare(request.seed);
    let control_id =
        hyper_encoder_model_identity(&staged, control_config, &control_trained.weights)?;
    let stare_id = hyper_encoder_model_identity(&staged, stare_config, &stare_trained.weights)?;
    let control_encoded =
        encode_hyper_encoder(&source, &staged, control_config, &control_trained.weights)?;
    let stare_encoded =
        encode_hyper_encoder(&source, &staged, stare_config, &stare_trained.weights)?;
    let control_validation_started = Instant::now();
    let control_validation = evaluate_hyper_relational_validation_batched(
        &task,
        control_id.as_str(),
        HyperRelationalCandidatePolicy::FullEntity,
        DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
        |queries, candidates, scores| {
            control_encoded.score_candidate_batch(&source, queries, candidates, scores)
        },
    )?;
    let compgcn_validation_micros = micros(control_validation_started.elapsed());
    let stare_validation_started = Instant::now();
    let stare_validation = evaluate_hyper_relational_validation_batched(
        &task,
        stare_id.as_str(),
        HyperRelationalCandidatePolicy::FullEntity,
        DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
        |queries, candidates, scores| {
            stare_encoded.score_candidate_batch(&source, queries, candidates, scores)
        },
    )?;
    let stare_validation_micros = micros(stare_validation_started.elapsed());
    drop(control_encoded);
    drop(stare_encoded);

    let mut pair_manifest = HyperEncoderPairManifest {
        schema_version: HYPER_ENCODER_PAIR_SCHEMA.into(),
        pair_id: "pending".into(),
        trainer_id: PAIRED_HYPER_ENCODER_TRAINER_ID.into(),
        source_dataset_id: staged.source_dataset_id.clone(),
        task_id: staged.task_id.clone(),
        seed: request.seed,
        training_config: request.config,
        initialization_blake3: initialization_blake3.clone(),
        example_schedule_blake3: examples.schedule_blake3.as_str().into(),
        compgcn_manifest_id: "derived-after-pair".into(),
        compgcn_model_id: control_id.clone(),
        compgcn_validation_certificate_id: control_validation.certificate_id.clone(),
        stare_manifest_id: "derived-after-pair".into(),
        stare_model_id: stare_id.clone(),
        stare_validation_certificate_id: stare_validation.certificate_id.clone(),
        qualifier_intervention_only: true,
        test_partition_accessed: false,
    };
    pair_manifest.pair_id = pair_identity(&pair_manifest)?;
    let control_snapshot = snapshot(
        &staged,
        &pair_manifest.pair_id,
        control_config,
        request.config,
        receipt(
            &staged,
            &examples.schedule_blake3,
            &initialization_blake3,
            request.config,
            examples.len(),
            &control_trained,
        ),
        control_validation.clone(),
        control_trained.weights,
    );
    let stare_snapshot = snapshot(
        &staged,
        &pair_manifest.pair_id,
        stare_config,
        request.config,
        receipt(
            &staged,
            &examples.schedule_blake3,
            &initialization_blake3,
            request.config,
            examples.len(),
            &stare_trained,
        ),
        stare_validation.clone(),
        stare_trained.weights,
    );
    let control_paths = write_hyper_encoder_model(&control_snapshot, &request.output_root)?;
    let stare_paths = write_hyper_encoder_model(&stare_snapshot, &request.output_root)?;
    pair_manifest.compgcn_manifest_id = control_paths.manifest_id.clone();
    pair_manifest.stare_manifest_id = stare_paths.manifest_id.clone();
    let pair_paths = write_hyper_encoder_pair(&pair_manifest, &request.output_root)?;

    let restart_started = Instant::now();
    let control_mapped = HyperEncoderMapped::open(&control_paths.manifest)?;
    let stare_mapped = HyperEncoderMapped::open(&stare_paths.manifest)?;
    let control_restart = restart_certificate(&source, &task, &staged, &control_mapped)?;
    let stare_restart = restart_certificate(&source, &task, &staged, &stare_mapped)?;
    let restart_micros = micros(restart_started.elapsed());
    let compgcn_restart_exact = control_restart == control_validation;
    let stare_restart_exact = stare_restart == stare_validation;
    if !compgcn_restart_exact || !stare_restart_exact {
        return Err(CandleTrainerError::Contract("hyper encoder restart parity"));
    }
    let allocation_delta = allocations.elapsed();
    let source_mmap_bytes = source
        .manifest()
        .binary_bytes
        .checked_add(task.manifest().binary_bytes)
        .ok_or(CandleTrainerError::Contract("hyper mmap bytes"))?;
    Ok(PairedHyperEncoderOutcome {
        report: PairedHyperEncoderReport {
            schema_version: PAIRED_HYPER_ENCODER_TRAINER_SCHEMA.into(),
            pair_id: pair_manifest.pair_id,
            seed: request.seed,
            training_config: request.config,
            initialization_blake3,
            example_schedule_blake3: examples.schedule_blake3.clone().into(),
            training_examples: examples.len() as u64,
            staging_micros,
            compgcn_training_micros,
            stare_training_micros,
            compgcn_validation_micros,
            stare_validation_micros,
            restart_micros,
            allocation_volume_bytes: allocation_delta.bytes,
            allocation_count: allocation_delta.count,
            peak_working_set_bytes: peak_working_set_bytes()?,
            source_mmap_bytes,
            compgcn_model_mmap_bytes: control_mapped.manifest().weights_bytes,
            stare_model_mmap_bytes: stare_mapped.manifest().weights_bytes,
            compgcn: control_validation,
            stare: stare_validation,
            compgcn_restart_exact,
            stare_restart_exact,
            model_ids_distinct: control_paths.model_id != stare_paths.model_id,
            test_partition_accessed: false,
        },
        compgcn: control_paths,
        stare: stare_paths,
        pair: pair_paths,
    })
}

pub(crate) fn snapshot(
    staged: &phoenix_graph_research::HyperEncoderStagedInput,
    pair_id: &CompactString,
    config: HyperEncoderConfig,
    training_config: HyperEncoderTrainingConfig,
    training: HyperEncoderTrainingReceipt,
    validation: HyperRelationalScoreCertificate,
    weights: HyperEncoderWeights,
) -> HyperEncoderModelSnapshot {
    HyperEncoderModelSnapshot {
        pair_id: pair_id.clone(),
        source_dataset_id: staged.source_dataset_id.clone(),
        source_binary_blake3: staged.source_binary_blake3.clone(),
        task_id: staged.task_id.clone(),
        task_binary_blake3: staged.task_binary_blake3.clone(),
        candidate_universe: staged.candidate_universe,
        base_relation_count: staged.base_relation_count,
        config,
        training_config,
        training,
        validation,
        weights,
    }
}

pub(crate) fn receipt(
    staged: &phoenix_graph_research::HyperEncoderStagedInput,
    schedule: &str,
    initialization: &str,
    _config: HyperEncoderTrainingConfig,
    examples: usize,
    outcome: &FusedHyperTrainingOutcome,
) -> HyperEncoderTrainingReceipt {
    HyperEncoderTrainingReceipt {
        trainer_id: PAIRED_HYPER_ENCODER_TRAINER_ID.into(),
        initialization_blake3: initialization.into(),
        train_topology_blake3: staged.profile.train_topology_blake3.clone(),
        example_schedule_blake3: schedule.into(),
        train_statements: staged.profile.train_statements,
        directed_messages: staged.profile.directed_messages,
        training_examples: examples as u64,
        optimizer_steps: outcome.optimizer_steps,
        optimizer_state_blake3: outcome.optimizer_state_blake3.as_str().into(),
        gradient_arena_bytes: outcome.gradient_arena_bytes,
        epoch_allocation_bytes: outcome.epoch_allocation_bytes,
        epoch_allocation_count: outcome.epoch_allocation_count,
        test_locked_during_training: true,
    }
}

pub(crate) fn restart_certificate(
    source: &ExternalDatasetMapped,
    task: &HyperRelationalTaskMapped,
    staged: &phoenix_graph_research::HyperEncoderStagedInput,
    model: &HyperEncoderMapped,
) -> Result<HyperRelationalScoreCertificate, CandleTrainerError> {
    if model.manifest().source_dataset_id != staged.source_dataset_id
        || model.manifest().task_id != staged.task_id
        || model.manifest().training.train_topology_blake3 != staged.profile.train_topology_blake3
    {
        return Err(CandleTrainerError::Contract("hyper restart authority"));
    }
    let weights = model.weights()?;
    let encoded = encode_hyper_encoder(source, staged, model.manifest().config, &weights)?;
    Ok(evaluate_hyper_relational_validation_batched(
        task,
        model.manifest().model_id.as_str(),
        HyperRelationalCandidatePolicy::FullEntity,
        DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
        |queries, candidates, scores| {
            encoded.score_candidate_batch(source, queries, candidates, scores)
        },
    )?)
}

pub(crate) fn weights_digest(weights: &HyperEncoderWeights) -> String {
    let mut hasher = blake3::Hasher::new();
    for tensor in [
        &weights.node_embeddings,
        &weights.direction_weights,
        &weights.relation_embeddings,
        &weights.relation_projection,
        &weights.qualifier_projection,
        &weights.decoder_bias,
    ] {
        for value in tensor {
            hasher.update(&value.to_bits().to_le_bytes());
        }
    }
    format!("b3-{}", hasher.finalize().to_hex())
}

pub(crate) fn micros(duration: std::time::Duration) -> u64 {
    duration.as_micros().try_into().unwrap_or(u64::MAX)
}
