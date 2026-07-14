use crate::hyper_encoder_examples::prepare_hyper_examples;
use crate::hyper_encoder_memory::{train_fused_hyper_encoder16, FusedHyperTrainingOutcome};
use crate::hyper_encoder_trainer::{
    micros, receipt, restart_certificate, snapshot, weights_digest,
};
use crate::hyper_optimizer::{GradientBlockEconomics, HyperEpochEconomics};
use crate::telemetry::{peak_working_set_bytes, AllocationSnapshot};
use crate::CandleTrainerError;
use compact_str::{format_compact, CompactString};
use phoenix_graph_research::{
    encode_hyper_encoder, evaluate_hyper_relational_validation_batched,
    hyper_encoder_model_identity, initialize_hyper_encoder_weights, stage_hyper_encoder,
    write_hyper_encoder_model, ExternalDatasetMapped, HyperEncoderConfig, HyperEncoderMapped,
    HyperEncoderMode, HyperEncoderModelPaths, HyperEncoderTrainingConfig, HyperEncoderWeights,
    HyperRelationalCandidatePolicy, HyperRelationalScoreCertificate, HyperRelationalTaskMapped,
    DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
};
use serde::{Deserialize, Serialize};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

pub const QUALIFIER_SIGNAL_MATRIX_SCHEMA: &str = "phoenix-qualifier-signal-isolation-matrix/v1";
pub const QUALIFIER_SIGNAL_MATRIX_TRAINER_ID: &str = "phoenix-fused-qualifier-matrix-e2e/v1";

const MATRIX_MODES: [HyperEncoderMode; 8] = [
    HyperEncoderMode::CompgcnTriple,
    HyperEncoderMode::StareQualifiers,
    HyperEncoderMode::RoleOnly,
    HyperEncoderMode::ValueOnly,
    HyperEncoderMode::Shuffled,
    HyperEncoderMode::Detached,
    HyperEncoderMode::QueryOnly,
    HyperEncoderMode::MessageOnly,
];

#[derive(Clone, Debug, PartialEq)]
pub struct QualifierSignalMatrixRequest {
    pub source_manifest: PathBuf,
    pub task_manifest: PathBuf,
    pub output_root: PathBuf,
    pub seed: u64,
    pub config: HyperEncoderTrainingConfig,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct QualifierSignalArm {
    pub mode: HyperEncoderMode,
    pub model_id: CompactString,
    pub model_manifest_id: CompactString,
    pub validation: HyperRelationalScoreCertificate,
    pub final_epoch: HyperEpochEconomics,
    pub economics_blake3: CompactString,
    pub training_micros: u64,
    pub validation_micros: u64,
    pub restart_micros: u64,
    pub restart_exact: bool,
    pub model_mmap_bytes: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct QualifierSignalMatrixManifest {
    pub schema_version: CompactString,
    pub matrix_id: CompactString,
    pub trainer_id: CompactString,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_id: CompactString,
    pub task_binary_blake3: CompactString,
    pub seed: u64,
    pub training_config: HyperEncoderTrainingConfig,
    pub initialization_blake3: CompactString,
    pub example_schedule_blake3: CompactString,
    pub shuffled_qualifier_refs_blake3: CompactString,
    pub training_examples: u64,
    pub staging_micros: u64,
    pub allocation_volume_bytes: u64,
    pub allocation_count: u64,
    pub peak_working_set_bytes: u64,
    pub source_mmap_bytes: u64,
    pub same_initialization: bool,
    pub same_example_schedule: bool,
    pub validation_only: bool,
    pub test_partition_accessed: bool,
    pub arms: Vec<QualifierSignalArm>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualifierSignalMatrixPaths {
    pub manifest: PathBuf,
    pub matrix_id: CompactString,
    pub models: Vec<HyperEncoderModelPaths>,
}

struct TrainedArm {
    mode: HyperEncoderMode,
    model_id: CompactString,
    validation: HyperRelationalScoreCertificate,
    outcome: FusedHyperTrainingOutcome,
    training_micros: u64,
    validation_micros: u64,
    economics_blake3: CompactString,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct MatrixIdentity<'a> {
    schema_version: &'a str,
    trainer_id: &'a str,
    source_dataset_id: &'a str,
    source_binary_blake3: &'a str,
    task_id: &'a str,
    task_binary_blake3: &'a str,
    seed: u64,
    training_config: HyperEncoderTrainingConfig,
    initialization_blake3: &'a str,
    example_schedule_blake3: &'a str,
    shuffled_qualifier_refs_blake3: &'a str,
    results: Vec<MatrixArmIdentity<'a>>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct MatrixArmIdentity<'a> {
    mode: HyperEncoderMode,
    model_id: &'a str,
    validation_certificate_id: &'a str,
    economics_blake3: &'a str,
}

pub fn run_qualifier_signal_matrix16(
    request: &QualifierSignalMatrixRequest,
) -> Result<QualifierSignalMatrixPaths, CandleTrainerError> {
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
    let mut trained = Vec::with_capacity(MATRIX_MODES.len());
    for mode in MATRIX_MODES {
        trained.push(train_arm(
            &source,
            &task,
            &staged,
            &examples,
            mode,
            request,
            initial.clone(),
        )?);
    }
    let matrix_id = matrix_identity(
        &staged,
        request,
        &initialization_blake3,
        &examples.schedule_blake3,
        &trained,
    )?;
    let mut arms = Vec::with_capacity(trained.len());
    let mut model_paths = Vec::with_capacity(trained.len());
    for trained_arm in trained {
        let config = HyperEncoderConfig::with_mode(request.seed, trained_arm.mode);
        let mut training = receipt(
            &staged,
            &examples.schedule_blake3,
            &initialization_blake3,
            request.config,
            examples.len(),
            &trained_arm.outcome,
        );
        training.trainer_id = QUALIFIER_SIGNAL_MATRIX_TRAINER_ID.into();
        let model = snapshot(
            &staged,
            &matrix_id,
            config,
            request.config,
            training,
            trained_arm.validation.clone(),
            trained_arm.outcome.weights,
        );
        let paths = write_hyper_encoder_model(&model, &request.output_root)?;
        let restart_started = Instant::now();
        let mapped = HyperEncoderMapped::open(&paths.manifest)?;
        let restart = restart_certificate(&source, &task, &staged, &mapped)?;
        let restart_micros = micros(restart_started.elapsed());
        if restart != trained_arm.validation {
            return Err(CandleTrainerError::Contract(
                "qualifier matrix restart parity",
            ));
        }
        arms.push(QualifierSignalArm {
            mode: trained_arm.mode,
            model_id: paths.model_id.clone(),
            model_manifest_id: paths.manifest_id.clone(),
            validation: trained_arm.validation,
            final_epoch: trained_arm.outcome.final_epoch,
            economics_blake3: trained_arm.economics_blake3,
            training_micros: trained_arm.training_micros,
            validation_micros: trained_arm.validation_micros,
            restart_micros,
            restart_exact: true,
            model_mmap_bytes: mapped.manifest().weights_bytes,
        });
        model_paths.push(paths);
    }
    let allocation_delta = allocations.elapsed();
    let source_mmap_bytes = source
        .manifest()
        .binary_bytes
        .checked_add(task.manifest().binary_bytes)
        .ok_or(CandleTrainerError::Contract("qualifier matrix mmap bytes"))?;
    let manifest = QualifierSignalMatrixManifest {
        schema_version: QUALIFIER_SIGNAL_MATRIX_SCHEMA.into(),
        matrix_id: matrix_id.clone(),
        trainer_id: QUALIFIER_SIGNAL_MATRIX_TRAINER_ID.into(),
        source_dataset_id: staged.source_dataset_id.clone(),
        source_binary_blake3: staged.source_binary_blake3.clone(),
        task_id: staged.task_id.clone(),
        task_binary_blake3: staged.task_binary_blake3.clone(),
        seed: request.seed,
        training_config: request.config,
        initialization_blake3,
        example_schedule_blake3: examples.schedule_blake3.as_str().into(),
        shuffled_qualifier_refs_blake3: u32_digest(&staged.shuffled_qualifier_refs),
        training_examples: examples.len() as u64,
        staging_micros,
        allocation_volume_bytes: allocation_delta.bytes,
        allocation_count: allocation_delta.count,
        peak_working_set_bytes: peak_working_set_bytes()?,
        source_mmap_bytes,
        same_initialization: true,
        same_example_schedule: true,
        validation_only: true,
        test_partition_accessed: false,
        arms,
    };
    validate_manifest(&manifest)?;
    let manifest_path = request.output_root.join(format!("{matrix_id}.matrix.json"));
    write_new(&manifest_path, &serde_json::to_vec_pretty(&manifest)?)?;
    Ok(QualifierSignalMatrixPaths {
        manifest: manifest_path,
        matrix_id,
        models: model_paths,
    })
}

pub fn open_qualifier_signal_matrix(
    path: impl AsRef<Path>,
) -> Result<QualifierSignalMatrixManifest, CandleTrainerError> {
    let manifest: QualifierSignalMatrixManifest =
        serde_json::from_slice(&std::fs::read(path.as_ref())?)?;
    validate_manifest(&manifest)?;
    Ok(manifest)
}

fn train_arm(
    source: &ExternalDatasetMapped,
    task: &HyperRelationalTaskMapped,
    staged: &phoenix_graph_research::HyperEncoderStagedInput,
    examples: &crate::hyper_encoder_examples::PreparedHyperExamples,
    mode: HyperEncoderMode,
    request: &QualifierSignalMatrixRequest,
    initial: HyperEncoderWeights,
) -> Result<TrainedArm, CandleTrainerError> {
    let training_started = Instant::now();
    let mut outcome =
        train_fused_hyper_encoder16(source, staged, examples, mode, request.config, initial)?;
    outcome.final_epoch = canonical_economics(outcome.final_epoch);
    let training_micros = micros(training_started.elapsed());
    let encoder_config = HyperEncoderConfig::with_mode(request.seed, mode);
    let model_id = hyper_encoder_model_identity(staged, encoder_config, &outcome.weights)?;
    let encoded = encode_hyper_encoder(source, staged, encoder_config, &outcome.weights)?;
    let validation_started = Instant::now();
    let validation = evaluate_hyper_relational_validation_batched(
        task,
        model_id.as_str(),
        HyperRelationalCandidatePolicy::FullEntity,
        DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
        |queries, candidates, scores| {
            encoded.score_candidate_batch(source, queries, candidates, scores)
        },
    )?;
    let validation_micros = micros(validation_started.elapsed());
    let economics_blake3 = economics_digest(&outcome.final_epoch);
    Ok(TrainedArm {
        mode,
        model_id,
        validation,
        outcome,
        training_micros,
        validation_micros,
        economics_blake3,
    })
}

fn matrix_identity(
    staged: &phoenix_graph_research::HyperEncoderStagedInput,
    request: &QualifierSignalMatrixRequest,
    initialization: &str,
    schedule: &str,
    arms: &[TrainedArm],
) -> Result<CompactString, CandleTrainerError> {
    let shuffled = u32_digest(&staged.shuffled_qualifier_refs);
    let identity = MatrixIdentity {
        schema_version: QUALIFIER_SIGNAL_MATRIX_SCHEMA,
        trainer_id: QUALIFIER_SIGNAL_MATRIX_TRAINER_ID,
        source_dataset_id: staged.source_dataset_id.as_str(),
        source_binary_blake3: staged.source_binary_blake3.as_str(),
        task_id: staged.task_id.as_str(),
        task_binary_blake3: staged.task_binary_blake3.as_str(),
        seed: request.seed,
        training_config: request.config,
        initialization_blake3: initialization,
        example_schedule_blake3: schedule,
        shuffled_qualifier_refs_blake3: shuffled.as_str(),
        results: arms
            .iter()
            .map(|arm| MatrixArmIdentity {
                mode: arm.mode,
                model_id: arm.model_id.as_str(),
                validation_certificate_id: arm.validation.certificate_id.as_str(),
                economics_blake3: arm.economics_blake3.as_str(),
            })
            .collect(),
    };
    digest_identity(&identity)
}

fn validate_manifest(manifest: &QualifierSignalMatrixManifest) -> Result<(), CandleTrainerError> {
    if manifest.schema_version != QUALIFIER_SIGNAL_MATRIX_SCHEMA
        || manifest.trainer_id != QUALIFIER_SIGNAL_MATRIX_TRAINER_ID
        || manifest.arms.len() != MATRIX_MODES.len()
        || manifest.test_partition_accessed
        || !manifest.validation_only
        || !manifest.same_initialization
        || !manifest.same_example_schedule
        || manifest.arms.iter().zip(MATRIX_MODES).any(|(arm, mode)| {
            arm.mode != mode
                || !arm.restart_exact
                || arm.validation.model_id != arm.model_id
                || arm.validation.task_id != manifest.task_id
        })
    {
        return Err(CandleTrainerError::Contract("qualifier matrix manifest"));
    }
    for arm in &manifest.arms {
        if economics_digest(&arm.final_epoch) != arm.economics_blake3 {
            return Err(CandleTrainerError::Contract(
                "qualifier matrix economics identity",
            ));
        }
    }
    let identity = MatrixIdentity {
        schema_version: manifest.schema_version.as_str(),
        trainer_id: manifest.trainer_id.as_str(),
        source_dataset_id: manifest.source_dataset_id.as_str(),
        source_binary_blake3: manifest.source_binary_blake3.as_str(),
        task_id: manifest.task_id.as_str(),
        task_binary_blake3: manifest.task_binary_blake3.as_str(),
        seed: manifest.seed,
        training_config: manifest.training_config,
        initialization_blake3: manifest.initialization_blake3.as_str(),
        example_schedule_blake3: manifest.example_schedule_blake3.as_str(),
        shuffled_qualifier_refs_blake3: manifest.shuffled_qualifier_refs_blake3.as_str(),
        results: manifest
            .arms
            .iter()
            .map(|arm| MatrixArmIdentity {
                mode: arm.mode,
                model_id: arm.model_id.as_str(),
                validation_certificate_id: arm.validation.certificate_id.as_str(),
                economics_blake3: arm.economics_blake3.as_str(),
            })
            .collect(),
    };
    if digest_identity(&identity)? != manifest.matrix_id {
        return Err(CandleTrainerError::Contract("qualifier matrix identity"));
    }
    Ok(())
}

fn economics_digest(economics: &HyperEpochEconomics) -> CompactString {
    let economics = canonical_economics(*economics);
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix-hyper-gradient-economics/v1");
    hasher.update(&economics.mean_binary_cross_entropy.to_bits().to_le_bytes());
    hasher.update(&economics.clip_coefficient.to_bits().to_le_bytes());
    hasher.update(&[economics.clip_activated as u8]);
    hasher.update(&economics.clip_activation_rate.to_bits().to_le_bytes());
    for block in [
        economics.entity_embeddings,
        economics.relation_embeddings,
        economics.relation_projection,
        economics.qualifier_projection,
        economics.direction_matrices,
        economics.decoder_bias,
    ] {
        for value in [
            block.gradient_l2,
            block.parameter_l2,
            block.update_l2,
            block.update_to_weight,
        ] {
            hasher.update(&value.to_bits().to_le_bytes());
        }
        hasher.update(&block.exactly_zero_gradients.to_le_bytes());
        hasher.update(&block.parameters.to_le_bytes());
    }
    format_compact!("b3-{}", hasher.finalize().to_hex())
}

fn canonical_economics(economics: HyperEpochEconomics) -> HyperEpochEconomics {
    HyperEpochEconomics {
        mean_binary_cross_entropy: canonical_f64(economics.mean_binary_cross_entropy),
        clip_coefficient: economics.clip_coefficient,
        clip_activated: economics.clip_activated,
        clip_activation_rate: canonical_f64(economics.clip_activation_rate),
        non_bias_raw_gradient_l2: canonical_f64(economics.non_bias_raw_gradient_l2),
        decoder_bias_raw_gradient_l2: canonical_f64(economics.decoder_bias_raw_gradient_l2),
        non_bias_clip_coefficient: economics.non_bias_clip_coefficient,
        decoder_bias_clip_coefficient: economics.decoder_bias_clip_coefficient,
        non_bias_clip_activation_rate: canonical_f64(economics.non_bias_clip_activation_rate),
        decoder_bias_clip_activation_rate: canonical_f64(
            economics.decoder_bias_clip_activation_rate,
        ),
        positive_examples: economics.positive_examples,
        negative_examples: economics.negative_examples,
        mean_positive_logit: canonical_f64(economics.mean_positive_logit),
        mean_negative_logit: canonical_f64(economics.mean_negative_logit),
        mean_decoder_bias_value: canonical_f64(economics.mean_decoder_bias_value),
        entity_embeddings: canonical_block(economics.entity_embeddings),
        relation_embeddings: canonical_block(economics.relation_embeddings),
        relation_projection: canonical_block(economics.relation_projection),
        qualifier_projection: canonical_block(economics.qualifier_projection),
        direction_matrices: canonical_block(economics.direction_matrices),
        decoder_bias: canonical_block(economics.decoder_bias),
    }
}

fn canonical_block(block: GradientBlockEconomics) -> GradientBlockEconomics {
    GradientBlockEconomics {
        gradient_l2: canonical_f64(block.gradient_l2),
        parameter_l2: canonical_f64(block.parameter_l2),
        update_l2: canonical_f64(block.update_l2),
        update_to_weight: canonical_f64(block.update_to_weight),
        exactly_zero_gradients: block.exactly_zero_gradients,
        parameters: block.parameters,
    }
}

fn canonical_f64(value: f64) -> f64 {
    f64::from(value as f32)
}

fn digest_identity(identity: &MatrixIdentity<'_>) -> Result<CompactString, CandleTrainerError> {
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(identity)?).to_hex()
    ))
}

fn u32_digest(values: &[u32]) -> CompactString {
    let mut hasher = blake3::Hasher::new();
    for value in values {
        hasher.update(&value.to_le_bytes());
    }
    format_compact!("b3-{}", hasher.finalize().to_hex())
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), CandleTrainerError> {
    std::fs::create_dir_all(path.parent().unwrap_or_else(|| Path::new(".")))?;
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
