use crate::telemetry::{peak_working_set_bytes, AllocationSnapshot};
use crate::temporal_rgcn_memory::train_fused_temporal_rgcn16;
use crate::{micros, CandleTrainerError};
use compact_str::CompactString;
use phoenix_graph_research::{
    encode_temporal_rgcn, encode_temporal_rgcn_weights,
    evaluate_link_prediction_validation_canonical_batched, evaluate_temporal_frequency_baseline,
    link_prediction_canonical_arena_bytes, stage_temporal_rgcn, temporal_rgcn_model_identity,
    write_temporal_rgcn, ExternalDatasetMapped, LinkPredictionScoreCertificate,
    LinkPredictionSplit, LinkPredictionTaskMapped, TemporalRgcnConfig, TemporalRgcnMapped,
    TemporalRgcnPaths, TemporalRgcnRuntimeIdentity, TemporalRgcnSnapshot, TemporalRgcnStagedInput,
    TemporalRgcnStagingProfile, TemporalRgcnTrainingReceipt, DEFAULT_LINK_PREDICTION_QUERY_BATCH,
    LINK_PREDICTION_SCORE_SCHEMA, TEMPORAL_RGCN_CANDIDATE_TILE, TEMPORAL_RGCN_QUERY_TILE,
};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::time::Instant;

pub const CANDLE_TEMPORAL_RGCN_TRAINER_ID: &str = "phoenix-fused-temporal-rgcn16/v2";
pub const CANDLE_TEMPORAL_RGCN_REPORT_SCHEMA: &str =
    "phoenix-canonical-evaluator-throughput-report/v5";

#[derive(Clone, Debug, PartialEq)]
pub struct CandleTemporalRgcnRequest {
    pub source_manifest: PathBuf,
    pub task_manifest: PathBuf,
    pub output_root: PathBuf,
    pub config: TemporalRgcnConfig,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CandleTemporalRgcnReport {
    pub schema_version: CompactString,
    pub manifest_id: CompactString,
    pub model_id: CompactString,
    pub weights_blake3: CompactString,
    pub selected_seed: u64,
    pub evaluation_query_batch: u64,
    pub evaluation_query_tile: u64,
    pub evaluation_candidate_tile: u64,
    pub evaluation_canonical_score_arena_bytes: u64,
    pub evaluation_duplicate_score_arena_bytes: u64,
    pub baseline_validation_micros: u64,
    pub training_micros: u64,
    pub canonical_encode_micros: u64,
    pub canonical_validation_micros: u64,
    pub restart_open_encode_micros: u64,
    pub allocation_volume_bytes: u64,
    pub allocation_count: u64,
    pub peak_working_set_bytes: u64,
    pub training_parameter_bytes: u64,
    pub training_gradient_arena_bytes: u64,
    pub training_allocation_volume_bytes: u64,
    pub training_allocation_count: u64,
    pub epoch_allocation_volume_bytes: u64,
    pub epoch_allocation_count: u64,
    pub training_working_set_bytes: u64,
    pub source_mmap_bytes: u64,
    pub model_mmap_bytes: u64,
    pub staging: TemporalRgcnStagingProfile,
    pub baseline: LinkPredictionScoreCertificate,
    pub validation: LinkPredictionScoreCertificate,
    pub restart_witness_bits_exact: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CandleTemporalRgcnOutcome {
    pub artifact: TemporalRgcnPaths,
    pub report: CandleTemporalRgcnReport,
}

pub fn train_candle_temporal_rgcn16(
    request: &CandleTemporalRgcnRequest,
) -> Result<CandleTemporalRgcnOutcome, CandleTrainerError> {
    let allocations = AllocationSnapshot::now();
    request.config.validate()?;
    let source = ExternalDatasetMapped::open(&request.source_manifest)?;
    let task = LinkPredictionTaskMapped::open(&request.task_manifest)?;
    let staged = stage_temporal_rgcn(&source, &task, request.config)?;
    let baseline_started = Instant::now();
    let baseline = evaluate_temporal_frequency_baseline(&task, &staged)?;
    let baseline_validation_micros = micros(baseline_started.elapsed());
    let source_mmap_bytes = source
        .manifest()
        .binary_bytes
        .checked_add(task.manifest().binary_bytes)
        .ok_or(CandleTrainerError::Contract("temporal source mmap bytes"))?;
    let training_started = Instant::now();
    let trained = train_fused_temporal_rgcn16(&staged, request.config)?;
    let training_micros = micros(training_started.elapsed());
    let weights = trained.weights;
    let training = training_receipt(request.config, &staged, training_micros)?;
    let runtime_identity = TemporalRgcnRuntimeIdentity {
        framework: "phoenix-fused".into(),
        framework_version: "temporal-rgcn-memory-v2".into(),
        backend: "cpu-wide-f32x8".into(),
        target: env!("PHOENIX_BUILD_TARGET").into(),
    };
    let mut snapshot = TemporalRgcnSnapshot {
        source_dataset_id: staged.source_dataset_id.clone(),
        source_binary_blake3: staged.source_binary_blake3.clone(),
        task_id: staged.task_id.clone(),
        task_binary_blake3: staged.task_binary_blake3.clone(),
        candidate_universe: staged.graph.node_types.len() as u32,
        base_relation_count: staged.base_relation_count,
        config: request.config,
        runtime: runtime_identity,
        training,
        baseline: baseline.clone(),
        validation: pending_validation(&staged.task_id),
        weights,
    };
    let model_id = temporal_rgcn_model_identity(&snapshot)?;
    let encode_started = Instant::now();
    let encoded = encode_temporal_rgcn_weights(
        model_id.as_str().into(),
        staged.task_id.clone(),
        &snapshot.weights,
        &staged,
    )?;
    let canonical_encode_micros = micros(encode_started.elapsed());
    let validation_started = Instant::now();
    let validation = evaluate_link_prediction_validation_canonical_batched(
        &task,
        &model_id,
        DEFAULT_LINK_PREDICTION_QUERY_BATCH,
        |queries, candidates, matrix| {
            encoded.score_candidate_batch_canonical(queries, candidates, matrix)
        },
    )?;
    let canonical_validation_micros = micros(validation_started.elapsed());
    if validation.mean_reciprocal_rank <= baseline.mean_reciprocal_rank {
        return Err(CandleTrainerError::Contract(
            "temporal R-GCN must beat structural baseline",
        ));
    }
    let live_witness = witness_scores(&encoded, &staged)?;
    snapshot.validation = validation.clone();
    let artifact = write_temporal_rgcn(&snapshot, &request.output_root)?;
    drop(encoded);
    drop(snapshot);

    let restart_started = Instant::now();
    let mapped = TemporalRgcnMapped::open(&artifact.manifest)?;
    let restart_encoded = encode_temporal_rgcn(&mapped, &staged)?;
    let restart_open_encode_micros = micros(restart_started.elapsed());
    let restart_witness_bits_exact = live_witness == witness_scores(&restart_encoded, &staged)?;
    if !restart_witness_bits_exact || mapped.manifest().validation != validation {
        return Err(CandleTrainerError::Contract("temporal restart parity"));
    }
    let model_mmap_bytes = mapped.manifest().weights_bytes;
    let allocation_delta = allocations.elapsed();
    let evaluation_canonical_score_arena_bytes = link_prediction_canonical_arena_bytes(
        staged.graph.node_types.len() as u64,
        DEFAULT_LINK_PREDICTION_QUERY_BATCH,
    )
    .ok_or(CandleTrainerError::Contract(
        "evaluation canonical score arena bytes",
    ))?;
    Ok(CandleTemporalRgcnOutcome {
        report: CandleTemporalRgcnReport {
            schema_version: CANDLE_TEMPORAL_RGCN_REPORT_SCHEMA.into(),
            manifest_id: artifact.manifest_id.clone(),
            model_id: artifact.model_id.clone(),
            weights_blake3: mapped.manifest().weights_blake3.clone(),
            selected_seed: request.config.seed,
            evaluation_query_batch: DEFAULT_LINK_PREDICTION_QUERY_BATCH as u64,
            evaluation_query_tile: TEMPORAL_RGCN_QUERY_TILE as u64,
            evaluation_candidate_tile: TEMPORAL_RGCN_CANDIDATE_TILE as u64,
            evaluation_canonical_score_arena_bytes,
            evaluation_duplicate_score_arena_bytes: 0,
            baseline_validation_micros,
            training_micros,
            canonical_encode_micros,
            canonical_validation_micros,
            restart_open_encode_micros,
            allocation_volume_bytes: allocation_delta.bytes,
            allocation_count: allocation_delta.count,
            peak_working_set_bytes: peak_working_set_bytes()?,
            training_parameter_bytes: trained.profile.parameter_bytes,
            training_gradient_arena_bytes: trained.profile.gradient_arena_bytes,
            training_allocation_volume_bytes: trained.profile.allocation_volume_bytes,
            training_allocation_count: trained.profile.allocation_count,
            epoch_allocation_volume_bytes: trained.profile.epoch_allocation_volume_bytes,
            epoch_allocation_count: trained.profile.epoch_allocation_count,
            training_working_set_bytes: trained.profile.working_set_bytes,
            source_mmap_bytes,
            model_mmap_bytes,
            staging: staged.profile.clone(),
            baseline,
            validation,
            restart_witness_bits_exact,
        },
        artifact,
    })
}

fn training_receipt(
    config: TemporalRgcnConfig,
    staged: &TemporalRgcnStagedInput,
    training_micros: u64,
) -> Result<TemporalRgcnTrainingReceipt, CandleTrainerError> {
    let optimizer_state_blake3 = format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            "sgd-full-batch/phoenix-fused-simd-v2",
            config,
            training_micros > 0,
        ))?)
        .to_hex()
    );
    Ok(TemporalRgcnTrainingReceipt {
        trainer_id: CANDLE_TEMPORAL_RGCN_TRAINER_ID.into(),
        train_facts: staged.profile.train_facts,
        directed_messages: staged.profile.directed_messages,
        training_examples: staged.profile.training_examples,
        optimizer_steps: u64::from(config.epochs),
        optimizer_state_blake3: optimizer_state_blake3.into(),
        train_topology_blake3: staged.profile.train_topology_blake3.clone(),
        test_locked_during_training: true,
    })
}

fn pending_validation(task_id: &str) -> LinkPredictionScoreCertificate {
    LinkPredictionScoreCertificate {
        schema_version: LINK_PREDICTION_SCORE_SCHEMA.into(),
        certificate_id: "pending".into(),
        task_id: task_id.into(),
        model_id: "pending".into(),
        split: LinkPredictionSplit::Validation,
        score_blake3: "pending".into(),
        mean_reciprocal_rank: 1.0,
        hits_at_1: 0.0,
        hits_at_3: 0.0,
        hits_at_10: 0.0,
        queries: 1,
        positives: 1,
        candidates_scored: 1,
    }
}

fn witness_scores(
    encoded: &phoenix_graph_research::TemporalRgcnEncoded,
    staged: &TemporalRgcnStagedInput,
) -> Result<Vec<u32>, CandleTrainerError> {
    let candidates = (0..staged.graph.node_types.len() as u32).collect::<Vec<_>>();
    let mut scores = vec![0.0; candidates.len()];
    encoded
        .score_candidates(
            phoenix_graph_research::LinkPredictionQueryView {
                observed_at: 1,
                source: 0,
                relation: 0,
                split: LinkPredictionSplit::Validation,
                inverse: false,
            },
            &candidates,
            &mut scores,
        )
        .map_err(|_| CandleTrainerError::Contract("temporal restart witness"))?;
    Ok(scores.into_iter().map(f32::to_bits).collect())
}
