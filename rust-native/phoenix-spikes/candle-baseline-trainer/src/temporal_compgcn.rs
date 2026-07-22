use crate::telemetry::{peak_working_set_bytes, AllocationSnapshot};
use crate::temporal_compgcn_memory::train_fused_temporal_compgcn16;
use crate::{micros, CandleTrainerError};
use compact_str::CompactString;
use phoenix_graph_research::{
    encode_temporal_compgcn, encode_temporal_compgcn_weights, encode_temporal_rgcn,
    evaluate_link_prediction_validation_canonical_batched, stage_temporal_rgcn,
    temporal_compgcn_model_identity, temporal_compgcn_weights_identity, write_temporal_compgcn,
    ExternalDatasetMapped, LinkPredictionScoreCertificate, LinkPredictionSplit,
    LinkPredictionTaskMapped, TemporalCompgcnConfig, TemporalCompgcnMapped, TemporalCompgcnPaths,
    TemporalCompgcnSnapshot, TemporalCompgcnTrainingReceipt, TemporalRgcnMapped,
    TemporalRgcnRuntimeIdentity, TemporalRgcnStagedInput, TemporalRgcnStagingProfile,
    DEFAULT_LINK_PREDICTION_QUERY_BATCH, LINK_PREDICTION_SCORE_SCHEMA,
    TEMPORAL_RGCN_CANDIDATE_TILE, TEMPORAL_RGCN_QUERY_TILE,
};
use serde::{Deserialize, Serialize};
use std::io::Write;
use std::path::PathBuf;
use std::time::Instant;

pub const TEMPORAL_COMPGCN_TRAINER_ID: &str = "phoenix-fused-temporal-compgcn16/v1";
pub const TEMPORAL_COMPGCN_REPORT_SCHEMA: &str = "phoenix-temporal-compgcn-report/v1";
pub const TEMPORAL_COMPGCN_CANDIDATE_SCHEMA: &str = "phoenix-temporal-compgcn-candidate/v1";

#[derive(Clone, Debug, PartialEq)]
pub struct TemporalCompgcnRequest {
    pub source_manifest: PathBuf,
    pub task_manifest: PathBuf,
    pub control_manifest: PathBuf,
    pub output_root: PathBuf,
    pub config: TemporalCompgcnConfig,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalCompgcnReport {
    pub schema_version: CompactString,
    pub manifest_id: CompactString,
    pub model_id: CompactString,
    pub weights_blake3: CompactString,
    pub selected_seed: u64,
    pub config: TemporalCompgcnConfig,
    pub control_manifest_id: CompactString,
    pub control_model_id: CompactString,
    pub compatibility_score_bits_exact: bool,
    pub validation_mrr_delta: f64,
    pub training_micros: u64,
    pub canonical_validation_micros: u64,
    pub restart_open_encode_micros: u64,
    pub allocation_volume_bytes: u64,
    pub allocation_count: u64,
    pub peak_working_set_bytes: u64,
    pub parameter_bytes: u64,
    pub gradient_arena_bytes: u64,
    pub training_allocation_volume_bytes: u64,
    pub training_allocation_count: u64,
    pub relation_state_bytes: u64,
    pub composition_kernel_micros: u64,
    pub epoch_allocation_bytes: u64,
    pub epoch_allocation_count: u64,
    pub source_mmap_bytes: u64,
    pub model_mmap_bytes: u64,
    pub query_batch: u64,
    pub query_tile: u64,
    pub candidate_tile: u64,
    pub staging: TemporalRgcnStagingProfile,
    pub baseline: LinkPredictionScoreCertificate,
    pub control: LinkPredictionScoreCertificate,
    pub validation: LinkPredictionScoreCertificate,
    pub restart_witness_bits_exact: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TemporalCompgcnOutcome {
    pub artifact: TemporalCompgcnPaths,
    pub report: TemporalCompgcnReport,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalCompgcnCandidateResources {
    pub training_micros: u64,
    pub canonical_validation_micros: u64,
    pub parameter_bytes: u64,
    pub gradient_arena_bytes: u64,
    pub training_allocation_volume_bytes: u64,
    pub training_allocation_count: u64,
    pub relation_state_bytes: u64,
    pub composition_kernel_micros: u64,
    pub epoch_allocation_bytes: u64,
    pub epoch_allocation_count: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalCompgcnCandidateReceipt {
    pub schema_version: CompactString,
    pub receipt_id: CompactString,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_id: CompactString,
    pub task_binary_blake3: CompactString,
    pub control_manifest_id: CompactString,
    pub control_model_id: CompactString,
    pub model_id: CompactString,
    pub weights_blake3: CompactString,
    pub weights_bytes: u64,
    pub config: TemporalCompgcnConfig,
    pub runtime: TemporalRgcnRuntimeIdentity,
    pub training: TemporalCompgcnTrainingReceipt,
    pub staging: TemporalRgcnStagingProfile,
    pub resources: TemporalCompgcnCandidateResources,
    pub control: LinkPredictionScoreCertificate,
    pub validation: LinkPredictionScoreCertificate,
    pub accepted: bool,
}

pub fn train_temporal_compgcn16(
    request: &TemporalCompgcnRequest,
) -> Result<TemporalCompgcnOutcome, CandleTrainerError> {
    let allocations = AllocationSnapshot::now();
    request.config.validate()?;
    let source = ExternalDatasetMapped::open(&request.source_manifest)?;
    let task = LinkPredictionTaskMapped::open(&request.task_manifest)?;
    let control = TemporalRgcnMapped::open(&request.control_manifest)?;
    validate_control(&source, &task, &control)?;
    let control_staged = stage_temporal_rgcn(&source, &task, control.manifest().config)?;
    let control_encoded = encode_temporal_rgcn(&control, &control_staged)?;
    let control_replayed = evaluate_link_prediction_validation_canonical_batched(
        &task,
        &control.manifest().model_id,
        DEFAULT_LINK_PREDICTION_QUERY_BATCH,
        |queries, candidates, matrix| {
            control_encoded.score_candidate_batch_canonical(queries, candidates, matrix)
        },
    )?;
    let compatibility_score_bits_exact = control_replayed == control.manifest().validation;
    if !compatibility_score_bits_exact {
        return Err(CandleTrainerError::Contract(
            "CompGCN control score-bit compatibility",
        ));
    }
    drop(control_encoded);
    drop(control_staged);
    let staged = stage_temporal_rgcn(&source, &task, request.config.base)?;

    let training_started = Instant::now();
    let trained = train_fused_temporal_compgcn16(&staged, request.config)?;
    let training_micros = micros(training_started.elapsed());
    let runtime = TemporalRgcnRuntimeIdentity {
        framework: "phoenix-fused".into(),
        framework_version: "temporal-compgcn-v1".into(),
        backend: "cpu-wide-f32x8".into(),
        target: env!("PHOENIX_BUILD_TARGET").into(),
    };
    let training = training_receipt(request.config, &staged, &trained.profile)?;
    let mut snapshot = TemporalCompgcnSnapshot {
        source_dataset_id: staged.source_dataset_id.clone(),
        source_binary_blake3: staged.source_binary_blake3.clone(),
        task_id: staged.task_id.clone(),
        task_binary_blake3: staged.task_binary_blake3.clone(),
        candidate_universe: staged.graph.node_types.len() as u32,
        base_relation_count: staged.base_relation_count,
        control_manifest_id: control.manifest().manifest_id.clone(),
        control_model_id: control.manifest().model_id.clone(),
        config: request.config,
        runtime,
        training,
        baseline: control.manifest().baseline.clone(),
        control: control.manifest().validation.clone(),
        validation: pending_validation(&staged.task_id),
        weights: trained.weights,
    };
    let model_id = temporal_compgcn_model_identity(&snapshot)?;
    let encoded = encode_temporal_compgcn_weights(
        model_id.as_str().into(),
        staged.task_id.clone(),
        &snapshot.weights,
        &staged,
        request.config,
    )?;
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
    if validation.mean_reciprocal_rank <= control.manifest().validation.mean_reciprocal_rank {
        let receipt = write_candidate_receipt(
            &request.output_root,
            &snapshot,
            &validation,
            training_micros,
            canonical_validation_micros,
            &trained.profile,
            &staged.profile,
        )?;
        return Err(CandleTrainerError::TemporalCompgcnCandidate {
            candidate_mrr: validation.mean_reciprocal_rank,
            control_mrr: control.manifest().validation.mean_reciprocal_rank,
            score_blake3: validation.score_blake3,
            receipt,
        });
    }
    let live_witness = witness_scores(&encoded, &staged)?;
    snapshot.validation = validation.clone();
    let artifact = write_temporal_compgcn(&snapshot, &request.output_root)?;
    drop(encoded);
    drop(snapshot);

    let restart_started = Instant::now();
    let mapped = TemporalCompgcnMapped::open(&artifact.manifest)?;
    let restart_encoded = encode_temporal_compgcn(&mapped, &staged)?;
    let restart_open_encode_micros = micros(restart_started.elapsed());
    let restart_witness_bits_exact = live_witness == witness_scores(&restart_encoded, &staged)?;
    if !restart_witness_bits_exact || mapped.manifest().validation != validation {
        return Err(CandleTrainerError::Contract("CompGCN restart parity"));
    }
    let source_mmap_bytes = source
        .manifest()
        .binary_bytes
        .checked_add(task.manifest().binary_bytes)
        .ok_or(CandleTrainerError::Contract("CompGCN source mmap bytes"))?;
    let model_mmap_bytes = mapped.manifest().weights_bytes;
    let allocation_delta = allocations.elapsed();
    Ok(TemporalCompgcnOutcome {
        report: TemporalCompgcnReport {
            schema_version: TEMPORAL_COMPGCN_REPORT_SCHEMA.into(),
            manifest_id: artifact.manifest_id.clone(),
            model_id: artifact.model_id.clone(),
            weights_blake3: mapped.manifest().weights_blake3.clone(),
            selected_seed: request.config.base.seed,
            config: request.config,
            control_manifest_id: control.manifest().manifest_id.clone(),
            control_model_id: control.manifest().model_id.clone(),
            compatibility_score_bits_exact,
            validation_mrr_delta: validation.mean_reciprocal_rank
                - control.manifest().validation.mean_reciprocal_rank,
            training_micros,
            canonical_validation_micros,
            restart_open_encode_micros,
            allocation_volume_bytes: allocation_delta.bytes,
            allocation_count: allocation_delta.count,
            peak_working_set_bytes: peak_working_set_bytes()?,
            parameter_bytes: trained.profile.parameter_bytes,
            gradient_arena_bytes: trained.profile.gradient_arena_bytes,
            training_allocation_volume_bytes: trained.profile.allocation_volume_bytes,
            training_allocation_count: trained.profile.allocation_count,
            relation_state_bytes: trained.profile.relation_state_bytes,
            composition_kernel_micros: trained.profile.composition_kernel_micros,
            epoch_allocation_bytes: trained.profile.epoch_allocation_volume_bytes,
            epoch_allocation_count: trained.profile.epoch_allocation_count,
            source_mmap_bytes,
            model_mmap_bytes,
            query_batch: DEFAULT_LINK_PREDICTION_QUERY_BATCH as u64,
            query_tile: TEMPORAL_RGCN_QUERY_TILE as u64,
            candidate_tile: TEMPORAL_RGCN_CANDIDATE_TILE as u64,
            staging: staged.profile.clone(),
            baseline: control.manifest().baseline.clone(),
            control: control.manifest().validation.clone(),
            validation,
            restart_witness_bits_exact,
        },
        artifact,
    })
}

fn write_candidate_receipt(
    output_root: &std::path::Path,
    snapshot: &TemporalCompgcnSnapshot,
    validation: &LinkPredictionScoreCertificate,
    training_micros: u64,
    canonical_validation_micros: u64,
    profile: &crate::temporal_compgcn_memory::CompgcnTrainingProfile,
    staging: &TemporalRgcnStagingProfile,
) -> Result<PathBuf, CandleTrainerError> {
    let (weights_blake3, weights_bytes) = temporal_compgcn_weights_identity(snapshot)?;
    let resources = TemporalCompgcnCandidateResources {
        training_micros,
        canonical_validation_micros,
        parameter_bytes: profile.parameter_bytes,
        gradient_arena_bytes: profile.gradient_arena_bytes,
        training_allocation_volume_bytes: profile.allocation_volume_bytes,
        training_allocation_count: profile.allocation_count,
        relation_state_bytes: profile.relation_state_bytes,
        composition_kernel_micros: profile.composition_kernel_micros,
        epoch_allocation_bytes: profile.epoch_allocation_volume_bytes,
        epoch_allocation_count: profile.epoch_allocation_count,
    };
    let mut receipt = TemporalCompgcnCandidateReceipt {
        schema_version: TEMPORAL_COMPGCN_CANDIDATE_SCHEMA.into(),
        receipt_id: "pending".into(),
        source_dataset_id: snapshot.source_dataset_id.clone(),
        source_binary_blake3: snapshot.source_binary_blake3.clone(),
        task_id: snapshot.task_id.clone(),
        task_binary_blake3: snapshot.task_binary_blake3.clone(),
        control_manifest_id: snapshot.control_manifest_id.clone(),
        control_model_id: snapshot.control_model_id.clone(),
        model_id: validation.model_id.clone(),
        weights_blake3: weights_blake3.into(),
        weights_bytes,
        config: snapshot.config,
        runtime: snapshot.runtime.clone(),
        training: snapshot.training.clone(),
        staging: staging.clone(),
        resources,
        control: snapshot.control.clone(),
        validation: validation.clone(),
        accepted: false,
    };
    receipt.receipt_id = candidate_receipt_identity(&receipt)?.into();
    std::fs::create_dir_all(output_root)?;
    let path = output_root.join(format!(
        "{}.temporal-compgcn-candidate.json",
        receipt.receipt_id
    ));
    let bytes = serde_json::to_vec_pretty(&receipt)?;
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    Ok(path)
}

fn candidate_receipt_identity(
    receipt: &TemporalCompgcnCandidateReceipt,
) -> Result<String, CandleTrainerError> {
    #[derive(Serialize)]
    struct Identity<'a> {
        schema: &'a str,
        source: (&'a str, &'a str),
        task: (&'a str, &'a str),
        control_identity: (&'a str, &'a str),
        model_identity: (&'a str, &'a str, u64),
        config: TemporalCompgcnConfig,
        runtime: &'a TemporalRgcnRuntimeIdentity,
        training: &'a TemporalCompgcnTrainingReceipt,
        staging: &'a TemporalRgcnStagingProfile,
        resources: &'a TemporalCompgcnCandidateResources,
        control: &'a LinkPredictionScoreCertificate,
        validation: &'a LinkPredictionScoreCertificate,
        accepted: bool,
    }
    let identity = Identity {
        schema: &receipt.schema_version,
        source: (&receipt.source_dataset_id, &receipt.source_binary_blake3),
        task: (&receipt.task_id, &receipt.task_binary_blake3),
        control_identity: (&receipt.control_manifest_id, &receipt.control_model_id),
        model_identity: (
            &receipt.model_id,
            &receipt.weights_blake3,
            receipt.weights_bytes,
        ),
        config: receipt.config,
        runtime: &receipt.runtime,
        training: &receipt.training,
        staging: &receipt.staging,
        resources: &receipt.resources,
        control: &receipt.control,
        validation: &receipt.validation,
        accepted: receipt.accepted,
    };
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&identity)?).to_hex()
    ))
}

fn validate_control(
    source: &ExternalDatasetMapped,
    task: &LinkPredictionTaskMapped,
    control: &TemporalRgcnMapped,
) -> Result<(), CandleTrainerError> {
    let source_manifest = source.manifest();
    let task_manifest = task.manifest();
    let control_manifest = control.manifest();
    if control_manifest.source_dataset_id != source_manifest.dataset_id
        || control_manifest.source_binary_blake3 != source_manifest.binary_blake3
        || control_manifest.task_id != task_manifest.task_id
        || control_manifest.task_binary_blake3 != task_manifest.binary_blake3
        || control_manifest.validation.split != LinkPredictionSplit::Validation
    {
        return Err(CandleTrainerError::Contract("CompGCN frozen control"));
    }
    Ok(())
}

fn training_receipt(
    config: TemporalCompgcnConfig,
    staged: &TemporalRgcnStagedInput,
    profile: &crate::temporal_compgcn_memory::CompgcnTrainingProfile,
) -> Result<TemporalCompgcnTrainingReceipt, CandleTrainerError> {
    let optimizer_state_blake3 = format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            "sgd-full-batch/phoenix-compgcn-v1",
            config,
        ))?)
        .to_hex()
    );
    Ok(TemporalCompgcnTrainingReceipt {
        trainer_id: TEMPORAL_COMPGCN_TRAINER_ID.into(),
        train_facts: staged.profile.train_facts,
        directed_messages: staged.profile.directed_messages,
        training_examples: staged.profile.training_examples,
        optimizer_steps: u64::from(config.base.epochs),
        optimizer_state_blake3: optimizer_state_blake3.into(),
        train_topology_blake3: staged.profile.train_topology_blake3.clone(),
        relation_state_bytes: profile.relation_state_bytes,
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
        .map_err(|_| CandleTrainerError::Contract("CompGCN restart witness"))?;
    Ok(scores.into_iter().map(f32::to_bits).collect())
}
