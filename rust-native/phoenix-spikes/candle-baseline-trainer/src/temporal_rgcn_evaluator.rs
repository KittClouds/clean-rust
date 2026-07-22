use crate::telemetry::{peak_working_set_bytes, AllocationSnapshot};
use crate::{micros, CandleTrainerError};
use compact_str::CompactString;
use phoenix_graph_research::{
    encode_temporal_rgcn, evaluate_link_prediction_validation_canonical_batched_profiled,
    link_prediction_canonical_arena_bytes, stage_temporal_rgcn, ExternalDatasetMapped,
    LinkPredictionEvaluationProfile, LinkPredictionScoreCertificate, LinkPredictionTaskMapped,
    TemporalRgcnMapped, TemporalRgcnStagingProfile, DEFAULT_LINK_PREDICTION_QUERY_BATCH,
    TEMPORAL_RGCN_CANDIDATE_TILE, TEMPORAL_RGCN_QUERY_TILE,
};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::time::Instant;

pub const TEMPORAL_RGCN_EVALUATOR_REPORT_SCHEMA: &str =
    "phoenix-canonical-evaluator-restart-report/v7";

#[derive(Clone, Debug, PartialEq)]
pub struct TemporalRgcnEvaluatorRequest {
    pub source_manifest: PathBuf,
    pub task_manifest: PathBuf,
    pub model_manifest: PathBuf,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalRgcnEvaluatorReport {
    pub schema_version: CompactString,
    pub model_id: CompactString,
    pub manifest_id: CompactString,
    pub validation_certificate_id: CompactString,
    pub score_blake3: CompactString,
    pub query_batch: u64,
    pub query_tile: u64,
    pub candidate_tile: u64,
    pub candidate_plane_bytes: u64,
    pub candidate_plane_build_micros: u64,
    pub canonical_score_arena_bytes: u64,
    pub duplicate_score_arena_bytes: u64,
    pub source_mmap_bytes: u64,
    pub model_mmap_bytes: u64,
    pub open_micros: u64,
    pub staging: TemporalRgcnStagingProfile,
    pub encode_micros: u64,
    pub evaluation_micros: u64,
    pub evaluation_profile: LinkPredictionEvaluationProfile,
    pub allocation_volume_bytes: u64,
    pub allocation_count: u64,
    pub peak_working_set_bytes: u64,
    pub certificate_exact: bool,
    pub validation: LinkPredictionScoreCertificate,
}

pub fn evaluate_temporal_rgcn_restart(
    request: &TemporalRgcnEvaluatorRequest,
) -> Result<TemporalRgcnEvaluatorReport, CandleTrainerError> {
    let allocations = AllocationSnapshot::now();
    let open_started = Instant::now();
    let source = ExternalDatasetMapped::open(&request.source_manifest)?;
    let task = LinkPredictionTaskMapped::open(&request.task_manifest)?;
    let model = TemporalRgcnMapped::open(&request.model_manifest)?;
    let open_micros = micros(open_started.elapsed());
    let source_mmap_bytes = source
        .manifest()
        .binary_bytes
        .checked_add(task.manifest().binary_bytes)
        .ok_or(CandleTrainerError::Contract("evaluator source mmap bytes"))?;
    let model_mmap_bytes = model.manifest().weights_bytes;
    let staged = stage_temporal_rgcn(&source, &task, model.manifest().config)?;
    let encode_started = Instant::now();
    let encoded = encode_temporal_rgcn(&model, &staged)?;
    let encode_micros = micros(encode_started.elapsed());
    let evaluation_started = Instant::now();
    let profiled = evaluate_link_prediction_validation_canonical_batched_profiled(
        &task,
        model.manifest().model_id.as_str(),
        DEFAULT_LINK_PREDICTION_QUERY_BATCH,
        |queries, candidates, matrix| {
            encoded.score_candidate_batch_canonical(queries, candidates, matrix)
        },
    )?;
    let evaluation_micros = micros(evaluation_started.elapsed());
    let validation = profiled.certificate;
    let certificate_exact = validation == model.manifest().validation;
    if !certificate_exact {
        return Err(CandleTrainerError::Contract("evaluator certificate parity"));
    }
    let canonical_score_arena_bytes = link_prediction_canonical_arena_bytes(
        task.manifest().candidate_universe as u64,
        DEFAULT_LINK_PREDICTION_QUERY_BATCH,
    )
    .ok_or(CandleTrainerError::Contract(
        "evaluator canonical score arena bytes",
    ))?;
    let allocation_delta = allocations.elapsed();
    Ok(TemporalRgcnEvaluatorReport {
        schema_version: TEMPORAL_RGCN_EVALUATOR_REPORT_SCHEMA.into(),
        model_id: model.manifest().model_id.clone(),
        manifest_id: model.manifest().manifest_id.clone(),
        validation_certificate_id: validation.certificate_id.clone(),
        score_blake3: validation.score_blake3.clone(),
        query_batch: DEFAULT_LINK_PREDICTION_QUERY_BATCH as u64,
        query_tile: TEMPORAL_RGCN_QUERY_TILE as u64,
        candidate_tile: TEMPORAL_RGCN_CANDIDATE_TILE as u64,
        candidate_plane_bytes: encoded.candidate_plane_bytes(),
        candidate_plane_build_micros: encoded.candidate_plane_build_micros(),
        canonical_score_arena_bytes,
        duplicate_score_arena_bytes: 0,
        source_mmap_bytes,
        model_mmap_bytes,
        open_micros,
        staging: staged.profile.clone(),
        encode_micros,
        evaluation_micros,
        evaluation_profile: profiled.profile,
        allocation_volume_bytes: allocation_delta.bytes,
        allocation_count: allocation_delta.count,
        peak_working_set_bytes: peak_working_set_bytes()?,
        certificate_exact,
        validation,
    })
}
