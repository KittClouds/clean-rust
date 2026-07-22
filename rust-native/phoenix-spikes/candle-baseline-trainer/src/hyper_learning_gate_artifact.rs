use crate::hyper_encoder_examples::PreparedHyperExamples;
use crate::hyper_encoder_memory::FusedHyperTrainingOutcome;
use crate::{CandleTrainerError, HyperClipPartition, HyperOptimizerConfig};
use compact_str::{format_compact, CompactString};
use phoenix_graph_research::{
    encode_hyper_encoder, evaluate_hyper_relational_validation_batched,
    hyper_encoder_model_identity, write_hyper_encoder_model, ExternalDatasetMapped,
    HyperEncoderConfig, HyperEncoderMapped, HyperEncoderMode, HyperEncoderModelSnapshot,
    HyperEncoderStagedInput, HyperEncoderTrainingConfig, HyperEncoderTrainingReceipt,
    HyperEncoderWeights, HyperRelationalCandidatePolicy, HyperRelationalTaskMapped,
    DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
};
use std::path::Path;

pub(crate) struct RestartedGateModel {
    pub model_id: CompactString,
    pub manifest_id: CompactString,
    pub weights: HyperEncoderWeights,
}

pub(crate) struct GateArtifactRequest<'a> {
    pub root: &'a Path,
    pub source: &'a ExternalDatasetMapped,
    pub task: &'a HyperRelationalTaskMapped,
    pub staged: &'a HyperEncoderStagedInput,
    pub examples: &'a PreparedHyperExamples,
    pub initial_weights_blake3: &'a str,
    pub seed: u64,
    pub mode: HyperEncoderMode,
    pub training_config: HyperEncoderTrainingConfig,
    pub optimizer: HyperOptimizerConfig,
    pub outcome: &'a FusedHyperTrainingOutcome,
}

pub(crate) fn persist_and_reopen_gate_model(
    request: GateArtifactRequest<'_>,
) -> Result<RestartedGateModel, CandleTrainerError> {
    let config = HyperEncoderConfig::with_mode(request.seed, request.mode);
    let model_id = hyper_encoder_model_identity(request.staged, config, &request.outcome.weights)?;
    let encoded = encode_hyper_encoder(
        request.source,
        request.staged,
        config,
        &request.outcome.weights,
    )?;
    let validation = evaluate_hyper_relational_validation_batched(
        request.task,
        model_id.as_str(),
        HyperRelationalCandidatePolicy::FullEntity,
        DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
        |queries, candidates, scores| {
            encoded.score_candidate_batch(request.source, queries, candidates, scores)
        },
    )?;
    drop(encoded);
    let partition = HyperClipPartition::for_optimizer(&request.outcome.weights, request.optimizer)?;
    let optimizer_id = request.optimizer.identity_with_partition_and_schedule(
        &partition,
        request.examples.schedule_blake3.as_str(),
    )?;
    let pair_id = gate_pair_id(
        request.staged,
        request.examples,
        config,
        optimizer_id.as_str(),
    );
    let snapshot = HyperEncoderModelSnapshot {
        pair_id,
        source_dataset_id: request.staged.source_dataset_id.clone(),
        source_binary_blake3: request.staged.source_binary_blake3.clone(),
        task_id: request.staged.task_id.clone(),
        task_binary_blake3: request.staged.task_binary_blake3.clone(),
        candidate_universe: request.staged.candidate_universe,
        base_relation_count: request.staged.base_relation_count,
        config,
        training_config: request.training_config,
        training: HyperEncoderTrainingReceipt {
            trainer_id: format_compact!("phoenix-hyper-learning-gate/v1:{optimizer_id}"),
            initialization_blake3: request.initial_weights_blake3.into(),
            train_topology_blake3: request.staged.profile.train_topology_blake3.clone(),
            example_schedule_blake3: request.examples.schedule_blake3.as_str().into(),
            train_statements: request.staged.profile.train_statements,
            directed_messages: request.staged.profile.directed_messages,
            training_examples: request.examples.len() as u64,
            optimizer_steps: request.outcome.optimizer_steps,
            optimizer_state_blake3: request.outcome.optimizer_state_blake3.as_str().into(),
            gradient_arena_bytes: request.outcome.gradient_arena_bytes,
            epoch_allocation_bytes: request.outcome.epoch_allocation_bytes,
            epoch_allocation_count: request.outcome.epoch_allocation_count,
            test_locked_during_training: true,
        },
        validation,
        weights: request.outcome.weights.clone(),
    };
    let paths = write_hyper_encoder_model(&snapshot, request.root)?;
    let mapped = HyperEncoderMapped::open(&paths.manifest)?;
    let weights = mapped.weights()?;
    if paths.model_id != model_id || weights_digest(&weights) != weights_digest(&snapshot.weights) {
        return Err(CandleTrainerError::Contract("gate model mmap restart"));
    }
    Ok(RestartedGateModel {
        model_id: paths.model_id,
        manifest_id: paths.manifest_id,
        weights,
    })
}

fn gate_pair_id(
    staged: &HyperEncoderStagedInput,
    examples: &PreparedHyperExamples,
    config: HyperEncoderConfig,
    optimizer_id: &str,
) -> CompactString {
    let mut hasher = blake3::Hasher::new();
    hasher.update(staged.source_dataset_id.as_bytes());
    hasher.update(staged.task_id.as_bytes());
    hasher.update(examples.schedule_blake3.as_bytes());
    hasher.update(optimizer_id.as_bytes());
    hasher.update(&config.seed.to_le_bytes());
    hasher.update(&[config.mode as u8]);
    format_compact!("b3-{}", hasher.finalize().to_hex())
}

fn weights_digest(weights: &HyperEncoderWeights) -> blake3::Hash {
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
    hasher.finalize()
}
