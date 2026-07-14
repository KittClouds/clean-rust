mod hyper_encoder_examples;
mod hyper_encoder_memory;
mod hyper_encoder_trainer;
mod hyper_learning_gate_artifact;
mod hyper_learning_gate_context;
mod hyper_learning_gate_metrics;
mod hyper_learning_gate_receipt;
mod hyper_learning_gates;
mod hyper_optimizer;
#[cfg(test)]
mod hyper_optimizer_tests;
mod optimization_envelope;
mod optimization_envelope_eval;
mod optimization_envelope_model;
mod qualifier_matrix;
mod rgcn;
mod telemetry;
mod temporal_compgcn;
mod temporal_compgcn_memory;
mod temporal_rgcn;
mod temporal_rgcn_evaluator;
mod temporal_rgcn_memory;

pub use hyper_encoder_trainer::*;
pub use hyper_learning_gate_receipt::open_hyper_learning_gates;
pub use hyper_learning_gates::*;
pub use hyper_optimizer::*;
pub use optimization_envelope::*;
pub use optimization_envelope_model::*;
pub use qualifier_matrix::*;
pub use rgcn::*;
pub use temporal_compgcn::*;
pub use temporal_rgcn::*;
pub use temporal_rgcn_evaluator::*;

use candle_core::{Device, Tensor, Var};
use candle_nn::{Optimizer, SGD};
use compact_str::{format_compact, CompactString};
use phoenix_graph_research::{
    certify_model_scores, certify_model_seed_receipt, evaluate_binary_scores,
    evaluate_ranking_scores, score_mlp16_tensors, BinaryMetrics, DerivedFeatureRow,
    FrozenGraphResearchError, FrozenGraphResearchMapped, FrozenModelArchitecture,
    FrozenModelBundle, FrozenModelError, FrozenModelHyperparameters, FrozenModelMapped,
    FrozenModelPaths, FrozenModelRuntimeIdentity, FrozenModelSnapshot, FrozenModelSourceIdentity,
    FrozenModelTensor, FrozenOptimizerReceipt, FrozenTensorMapped, FrozenTrainingReceipt,
    RankingEvaluationError, RankingMetrics, ResearchEvaluationError, ResearchEvaluationProtocol,
    ResearchSplit, RgcnResearchError, SeedCertificate, TrainTopologyFeatureMapped,
    MODEL_HIDDEN_BIAS, MODEL_HIDDEN_WEIGHT, MODEL_OUTPUT_BIAS, MODEL_OUTPUT_WEIGHT,
    RANKING_EVALUATION_SCHEMA, RESEARCH_EVALUATION_SCHEMA,
};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::time::Instant;
use telemetry::{peak_working_set_bytes, AllocationSnapshot};

pub const CANDLE_BASELINE_TRAINER_SCHEMA: &str = "phoenix-candle-baseline-trainer/v1";
pub const CANDLE_BASELINE_TRAINER_ID: &str = "candle-mlp16/v1";
pub const TYPED_LINK_TASK_ID: &str = "typed-link-prediction/v1";
pub const TYPED_LINK_BINARY_TASK_ID: &str = "typed-link-binary-selection/v1";
const FEATURE_DIM: usize = 16;
const HIDDEN_DIM: usize = 16;

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CandleTrainerConfig {
    pub epochs: u32,
    pub batch_size: u32,
    pub learning_rate: f32,
    pub l2: f32,
}

impl Default for CandleTrainerConfig {
    fn default() -> Self {
        Self {
            epochs: 24,
            batch_size: 32,
            learning_rate: 0.025,
            l2: 0.0005,
        }
    }
}

impl CandleTrainerConfig {
    fn validate(self) -> Result<(), CandleTrainerError> {
        if self.epochs == 0
            || self.batch_size == 0
            || !self.learning_rate.is_finite()
            || self.learning_rate <= 0.0
            || !self.l2.is_finite()
            || self.l2 < 0.0
        {
            return Err(CandleTrainerError::Contract("trainer configuration"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct CandleTrainerRequest {
    pub graph_manifest: PathBuf,
    pub tensor_manifest: PathBuf,
    pub evaluation_protocol: PathBuf,
    pub topology_manifest: PathBuf,
    pub output_root: PathBuf,
    pub selected_repeat: u16,
    pub config: CandleTrainerConfig,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CandleTrainerReport {
    pub schema_version: CompactString,
    pub model_id: CompactString,
    pub weights_blake3: CompactString,
    pub weights_bytes: u64,
    pub validation_score_blake3: CompactString,
    pub validation_certificates_blake3: CompactString,
    pub selected_seed: u64,
    pub training_examples: u64,
    pub validation_examples: u64,
    pub epochs: u32,
    pub batch_size: u32,
    pub optimizer_steps: u64,
    pub training_micros: u64,
    pub candle_validation_micros: u64,
    pub canonical_scoring_micros: u64,
    pub canonical_validation_micros: u64,
    pub artifact_write_micros: u64,
    pub restart_open_micros: u64,
    pub restart_scoring_micros: u64,
    pub restart_open_and_score_micros: u64,
    pub allocation_volume_bytes: u64,
    pub allocation_count: u64,
    pub peak_working_set_bytes: u64,
    pub source_mmap_bytes: u64,
    pub restart_weight_mmap_bytes: u64,
    pub mmap_bytes: u64,
    pub dense_staging_bytes: u64,
    pub candle_max_abs_error: f32,
    pub restart_score_bits_exact: bool,
    pub validation_metrics: BinaryMetrics,
    pub validation_ranking_metrics: RankingMetrics,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CandleTrainingOutcome {
    pub artifact: FrozenModelPaths,
    pub report: CandleTrainerReport,
}

#[derive(Debug, thiserror::Error)]
pub enum CandleTrainerError {
    #[error("trainer contract is invalid: {0}")]
    Contract(&'static str),
    #[error(
        "temporal CompGCN candidate did not beat control: candidate MRR {candidate_mrr}, control MRR {control_mrr}, score {score_blake3}, receipt {receipt}"
    )]
    TemporalCompgcnCandidate {
        candidate_mrr: f64,
        control_mrr: f64,
        score_blake3: CompactString,
        receipt: PathBuf,
    },
    #[error("Candle training failed: {0}")]
    Candle(#[from] candle_core::Error),
    #[error("frozen graph or tensor input failed validation: {0}")]
    Graph(#[from] FrozenGraphResearchError),
    #[error("evaluation or topology input failed validation: {0}")]
    Evaluation(#[from] ResearchEvaluationError),
    #[error("ranking evaluation failed: {0}")]
    Ranking(#[from] RankingEvaluationError),
    #[error("R-GCN research input failed validation: {0}")]
    Rgcn(#[from] RgcnResearchError),
    #[error("temporal R-GCN research input failed validation: {0}")]
    TemporalRgcn(#[from] phoenix_graph_research::TemporalRgcnError),
    #[error("temporal CompGCN research input failed validation: {0}")]
    TemporalCompgcn(#[from] phoenix_graph_research::TemporalCompgcnError),
    #[error("hyper encoder research input failed validation: {0}")]
    HyperEncoder(#[from] phoenix_graph_research::HyperEncoderError),
    #[error("hyper-relational task failed validation: {0}")]
    HyperRelational(#[from] phoenix_graph_research::HyperRelationalTaskError),
    #[error("canonical link task failed validation: {0}")]
    LinkPrediction(#[from] phoenix_graph_research::LinkPredictionError),
    #[error("external dataset failed validation: {0}")]
    ExternalDataset(#[from] phoenix_graph_research::ExternalDatasetError),
    #[error("frozen baseline selection failed validation: {0}")]
    Selection(#[from] phoenix_graph_research::FrozenModelSelectionError),
    #[error("frozen model emission failed: {0}")]
    Model(#[from] FrozenModelError),
    #[error("trainer input I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("trainer input JSON failed: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Clone, Copy)]
struct TrainRow {
    features: [f32; FEATURE_DIM],
    label: bool,
}

struct PreparedRows {
    train: Vec<TrainRow>,
    validation: Vec<DerivedFeatureRow>,
    validation_features: Vec<[f32; FEATURE_DIM]>,
}

impl PreparedRows {
    fn dense_staging_bytes(&self) -> Result<u64, CandleTrainerError> {
        let train = self
            .train
            .capacity()
            .checked_mul(std::mem::size_of::<TrainRow>());
        let validation = self
            .validation
            .capacity()
            .checked_mul(std::mem::size_of::<DerivedFeatureRow>());
        let features = self
            .validation_features
            .capacity()
            .checked_mul(std::mem::size_of::<[f32; FEATURE_DIM]>());
        train
            .and_then(|bytes| validation.and_then(|value| bytes.checked_add(value)))
            .and_then(|bytes| features.and_then(|value| bytes.checked_add(value)))
            .and_then(|bytes| u64::try_from(bytes).ok())
            .ok_or(CandleTrainerError::Contract("dense staging byte overflow"))
    }
}

struct SourceAuthority {
    identity: FrozenModelSourceIdentity,
    seeds: SeedCertificate,
    topology: TrainTopologyFeatureMapped,
    tensor: FrozenTensorMapped,
    mmap_bytes: u64,
}

struct CandleMlp {
    hidden_weight: Var,
    hidden_bias: Var,
    output_weight: Var,
    output_bias: Var,
}

impl CandleMlp {
    fn new(seed: u64, device: &Device) -> Result<(Self, SplitMix64), CandleTrainerError> {
        let mut random = SplitMix64(seed);
        let hidden_weight = (0..FEATURE_DIM * HIDDEN_DIM)
            .map(|_| random.signed_unit() * 0.08)
            .collect::<Vec<_>>();
        let output_weight = (0..HIDDEN_DIM)
            .map(|_| random.signed_unit() * 0.08)
            .collect::<Vec<_>>();
        Ok((
            Self {
                hidden_weight: Var::from_tensor(&Tensor::from_vec(
                    hidden_weight,
                    (HIDDEN_DIM, FEATURE_DIM),
                    device,
                )?)?,
                hidden_bias: Var::zeros(HIDDEN_DIM, candle_core::DType::F32, device)?,
                output_weight: Var::from_tensor(&Tensor::from_vec(
                    output_weight,
                    (1, HIDDEN_DIM),
                    device,
                )?)?,
                output_bias: Var::zeros(1, candle_core::DType::F32, device)?,
            },
            random,
        ))
    }

    fn vars(&self) -> Vec<Var> {
        vec![
            self.hidden_weight.clone(),
            self.hidden_bias.clone(),
            self.output_weight.clone(),
            self.output_bias.clone(),
        ]
    }

    fn logits(&self, features: &Tensor) -> candle_core::Result<Tensor> {
        let hidden = features
            .matmul(&self.hidden_weight.as_tensor().t()?)?
            .broadcast_add(self.hidden_bias.as_tensor())?
            .relu()?;
        hidden
            .matmul(&self.output_weight.as_tensor().t()?)?
            .broadcast_add(self.output_bias.as_tensor())
    }

    fn l2_penalty(&self, l2: f32) -> candle_core::Result<Tensor> {
        let hidden = self.hidden_weight.as_tensor().sqr()?.sum_all()?;
        let output = self.output_weight.as_tensor().sqr()?.sum_all()?;
        (hidden + output)?.affine(f64::from(l2) * 0.5, 0.0)
    }

    fn export(&self) -> Result<Vec<FrozenModelTensor>, CandleTrainerError> {
        Ok(vec![
            model_tensor(
                MODEL_HIDDEN_WEIGHT,
                &[HIDDEN_DIM as u64, FEATURE_DIM as u64],
                tensor_values(self.hidden_weight.as_tensor())?,
            ),
            model_tensor(
                MODEL_HIDDEN_BIAS,
                &[HIDDEN_DIM as u64],
                tensor_values(self.hidden_bias.as_tensor())?,
            ),
            model_tensor(
                MODEL_OUTPUT_WEIGHT,
                &[HIDDEN_DIM as u64],
                tensor_values(self.output_weight.as_tensor())?,
            ),
            model_tensor(
                MODEL_OUTPUT_BIAS,
                &[1],
                tensor_values(self.output_bias.as_tensor())?,
            ),
        ])
    }
}

pub fn train_candle_mlp16(
    request: &CandleTrainerRequest,
) -> Result<CandleTrainingOutcome, CandleTrainerError> {
    let allocations_started = AllocationSnapshot::now();
    request.config.validate()?;
    let authority = open_authority(request)?;
    let seed_receipt = certify_model_seed_receipt(&authority.seeds, request.selected_repeat)?;
    let seed = seed_receipt
        .selected_seed()
        .ok_or(CandleTrainerError::Contract("selected seed"))?;
    let rows = prepare_rows(&authority.topology)?;
    if rows.train.is_empty() || rows.validation.is_empty() {
        return Err(CandleTrainerError::Contract(
            "nonempty train and validation splits",
        ));
    }
    let dense_staging_bytes = rows.dense_staging_bytes()?;
    let source_mmap_bytes = authority.mmap_bytes;

    let device = Device::Cpu;
    let (model, mut random) = CandleMlp::new(seed, &device)?;
    let training_started = Instant::now();
    let steps = train_model(&model, &rows.train, request.config, &mut random, &device)?;
    let training_micros = micros(training_started.elapsed());

    let candle_started = Instant::now();
    let candle_scores = candle_scores(&model, &rows.validation_features, &device)?;
    let candle_validation_micros = micros(candle_started.elapsed());
    let tensors = model.export()?;
    drop(model);

    let canonical_started = Instant::now();
    let canonical_scoring_started = Instant::now();
    let canonical_scores = score_mlp16_tensors(&tensors, &rows.validation_features)?;
    let canonical_scoring_micros = micros(canonical_scoring_started.elapsed());
    let validation_ranking_metrics = evaluate_ranking_scores(
        &rows.validation,
        &canonical_scores,
        ResearchSplit::Validation,
    )?
    .ok_or(CandleTrainerError::Contract("rankable validation rows"))?;
    let validation_labels = rows
        .validation
        .iter()
        .map(|row| row.label)
        .collect::<Vec<_>>();
    let validation_metrics = evaluate_binary_scores(&validation_labels, &canonical_scores, 10)?;
    let binary_score_certificate = certify_model_scores(
        TYPED_LINK_BINARY_TASK_ID,
        RESEARCH_EVALUATION_SCHEMA,
        ResearchSplit::Validation,
        &canonical_scores,
        &validation_metrics,
    )?;
    let ranking_score_certificate = certify_model_scores(
        TYPED_LINK_TASK_ID,
        RANKING_EVALUATION_SCHEMA,
        ResearchSplit::Validation,
        &canonical_scores,
        &validation_ranking_metrics,
    )?;
    let validation_score_blake3 = binary_score_certificate.score_blake3.clone();
    let score_certificates = vec![binary_score_certificate, ranking_score_certificate];
    let validation_certificates_blake3 = format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&score_certificates)?).to_hex()
    );
    let canonical_validation_micros = micros(canonical_started.elapsed());
    let candle_max_abs_error = max_abs_error(&candle_scores, &canonical_scores)?;
    if candle_max_abs_error > 1.0e-4 {
        return Err(CandleTrainerError::Contract("Candle/SIMD score parity"));
    }

    let optimizer = FrozenOptimizerReceipt {
        algorithm: "sgd".into(),
        implementation_version: "candle-nn-sgd/0.11.0-stateless".into(),
        steps_completed: steps,
        state_blake3: optimizer_state_digest(request.config.learning_rate, steps),
    };
    let snapshot = FrozenModelSnapshot {
        source: authority.identity,
        architecture: FrozenModelArchitecture::mlp16(),
        hyperparameters: FrozenModelHyperparameters {
            epochs: request.config.epochs,
            batch_size: request.config.batch_size,
            learning_rate: request.config.learning_rate,
            l2: request.config.l2,
        },
        seeds: seed_receipt,
        runtime: FrozenModelRuntimeIdentity {
            framework: "candle".into(),
            framework_version: "0.11.0".into(),
            backend: "cpu".into(),
            target: env!("PHOENIX_BUILD_TARGET").into(),
        },
        training: FrozenTrainingReceipt {
            trainer_id: CANDLE_BASELINE_TRAINER_ID.into(),
            training_examples: rows.train.len() as u64,
            validation_examples: rows.validation.len() as u64,
            epochs_completed: request.config.epochs,
            training_executions: 1,
            selected_on_validation: true,
            test_locked_during_selection: true,
            optimizer,
        },
        score_certificates,
        tensors,
    };
    let write_started = Instant::now();
    let artifact = FrozenModelBundle::write(&snapshot, &request.output_root)?;
    let artifact_write_micros = micros(write_started.elapsed());
    drop(snapshot);

    let restart_started = Instant::now();
    let restart_open_started = Instant::now();
    let mapped = FrozenModelMapped::open(&artifact.manifest)?;
    let restart_open_micros = micros(restart_open_started.elapsed());
    let restart_scoring_started = Instant::now();
    let restart_scores = mapped.score_mlp16(&rows.validation_features)?;
    let restart_scoring_micros = micros(restart_scoring_started.elapsed());
    let restart_open_and_score_micros = micros(restart_started.elapsed());
    let restart_score_bits_exact = score_bits(&restart_scores) == score_bits(&canonical_scores);
    let restart_certificates = vec![
        certify_model_scores(
            TYPED_LINK_BINARY_TASK_ID,
            RESEARCH_EVALUATION_SCHEMA,
            ResearchSplit::Validation,
            &restart_scores,
            &validation_metrics,
        )?,
        certify_model_scores(
            TYPED_LINK_TASK_ID,
            RANKING_EVALUATION_SCHEMA,
            ResearchSplit::Validation,
            &restart_scores,
            &validation_ranking_metrics,
        )?,
    ];
    if !restart_score_bits_exact || mapped.manifest().score_certificates != restart_certificates {
        return Err(CandleTrainerError::Contract("restart score certificate"));
    }
    let restart_weight_mmap_bytes = mapped.manifest().weights_bytes;
    let mmap_bytes = source_mmap_bytes
        .checked_add(restart_weight_mmap_bytes)
        .ok_or(CandleTrainerError::Contract("mmap byte overflow"))?;
    let allocation_delta = allocations_started.elapsed();
    let peak_working_set_bytes = peak_working_set_bytes()?;
    let report = CandleTrainerReport {
        schema_version: CANDLE_BASELINE_TRAINER_SCHEMA.into(),
        model_id: mapped.manifest().model_id.clone(),
        weights_blake3: mapped.manifest().weights_blake3.clone(),
        weights_bytes: mapped.manifest().weights_bytes,
        validation_score_blake3,
        validation_certificates_blake3,
        selected_seed: seed,
        training_examples: rows.train.len() as u64,
        validation_examples: rows.validation.len() as u64,
        epochs: request.config.epochs,
        batch_size: request.config.batch_size,
        optimizer_steps: steps,
        training_micros,
        candle_validation_micros,
        canonical_scoring_micros,
        canonical_validation_micros,
        artifact_write_micros,
        restart_open_micros,
        restart_scoring_micros,
        restart_open_and_score_micros,
        allocation_volume_bytes: allocation_delta.bytes,
        allocation_count: allocation_delta.count,
        peak_working_set_bytes,
        source_mmap_bytes,
        restart_weight_mmap_bytes,
        mmap_bytes,
        dense_staging_bytes,
        candle_max_abs_error,
        restart_score_bits_exact,
        validation_metrics,
        validation_ranking_metrics,
    };
    Ok(CandleTrainingOutcome { artifact, report })
}

fn open_authority(request: &CandleTrainerRequest) -> Result<SourceAuthority, CandleTrainerError> {
    let graph = FrozenGraphResearchMapped::open(&request.graph_manifest)?;
    let tensor = FrozenTensorMapped::open(&request.tensor_manifest)?;
    let topology = TrainTopologyFeatureMapped::open(&request.topology_manifest)?;
    let protocol = read_protocol(&request.evaluation_protocol)?;
    let graph_manifest = graph.manifest();
    let tensor_manifest = tensor.manifest();
    let topology_manifest = topology.manifest();
    if graph_manifest.dataset_id != tensor_manifest.source_dataset_id
        || graph_manifest.dataset_id != protocol.source_dataset_id
        || graph_manifest.dataset_id != topology_manifest.source_dataset_id
        || tensor_manifest.tensor_id != protocol.tensor_id
        || tensor_manifest.tensor_id != topology_manifest.source_tensor_id
        || protocol.protocol_id != topology_manifest.evaluation_protocol_id
        || graph_manifest.split_policy != protocol.split_policy
        || !topology_manifest.audit.train_only
        || !topology_manifest.audit.asserted_edges_only
        || !topology_manifest.audit.resolved_incidences_only
        || !topology_manifest.audit.leave_one_positive_out
        || !is_blake3(graph_manifest.dataset_id.as_str())
        || !is_blake3(tensor_manifest.tensor_id.as_str())
        || !is_blake3(protocol.protocol_id.as_str())
        || !is_blake3(topology_manifest.derivation_id.as_str())
        || !is_blake3(topology_manifest.audit.topology_blake3.as_str())
    {
        return Err(CandleTrainerError::Contract("source authority chain"));
    }
    let mmap_bytes = graph_manifest
        .binary_bytes
        .checked_add(tensor_manifest.binary_bytes)
        .and_then(|bytes| bytes.checked_add(topology_manifest.binary_bytes))
        .ok_or(CandleTrainerError::Contract("source mmap byte overflow"))?;
    let identity = FrozenModelSourceIdentity {
        dataset_id: graph_manifest.dataset_id.clone(),
        checkpoint_id: graph_manifest.checkpoint_id.clone(),
        checkpoint_generation: graph_manifest.checkpoint_generation,
        tensor_id: tensor_manifest.tensor_id.clone(),
        topology_derivation_id: topology_manifest.derivation_id.clone(),
        topology_blake3: topology_manifest.audit.topology_blake3.clone(),
        evaluation_protocol_id: protocol.protocol_id,
    };
    Ok(SourceAuthority {
        identity,
        seeds: protocol.seed_certificate,
        topology,
        tensor,
        mmap_bytes,
    })
}

fn read_protocol(path: &Path) -> Result<ResearchEvaluationProtocol, CandleTrainerError> {
    let protocol: ResearchEvaluationProtocol = serde_json::from_slice(&std::fs::read(path)?)?;
    let expected_name = format!("{}.evaluation.json", protocol.protocol_id);
    let mut identity = protocol.clone();
    identity.protocol_id = "pending".into();
    let expected_id = format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&identity)?).to_hex()
    );
    if protocol.schema_version != RESEARCH_EVALUATION_SCHEMA
        || protocol.protocol_id != expected_id
        || path.file_name().and_then(|name| name.to_str()) != Some(expected_name.as_str())
    {
        return Err(CandleTrainerError::Contract("evaluation protocol identity"));
    }
    Ok(protocol)
}

fn prepare_rows(topology: &TrainTopologyFeatureMapped) -> Result<PreparedRows, CandleTrainerError> {
    let records = topology.link_rows()?;
    let mut train_rows = 0_usize;
    let mut validation_rows = 0_usize;
    for record in records.iter() {
        match record.split() {
            1 => train_rows += 1,
            2 => validation_rows += 1,
            3 => {}
            _ => return Err(CandleTrainerError::Contract("topology row split")),
        }
    }
    let mut train = Vec::with_capacity(train_rows);
    let mut validation = Vec::with_capacity(validation_rows);
    let mut validation_features = Vec::with_capacity(validation_rows);
    for record in records.iter() {
        let split = match record.split() {
            1 => ResearchSplit::Train,
            2 => ResearchSplit::Validation,
            3 => continue,
            _ => return Err(CandleTrainerError::Contract("topology row split")),
        };
        let mut features = [0.0_f32; FEATURE_DIM];
        for (column, value) in features.iter_mut().enumerate() {
            *value = record
                .feature(column)
                .ok_or(CandleTrainerError::Contract("topology feature column"))?;
        }
        if features.iter().any(|value| !value.is_finite()) {
            return Err(CandleTrainerError::Contract("finite topology features"));
        }
        if split == ResearchSplit::Train {
            train.push(TrainRow {
                features,
                label: record.label(),
            });
        } else {
            validation_features.push(features);
            validation.push(DerivedFeatureRow {
                positive_index: record.positive_index(),
                candidate: record.candidate(),
                split,
                label: record.label(),
                features,
            });
        }
    }
    Ok(PreparedRows {
        train,
        validation,
        validation_features,
    })
}

fn train_model(
    model: &CandleMlp,
    rows: &[TrainRow],
    config: CandleTrainerConfig,
    random: &mut SplitMix64,
    device: &Device,
) -> Result<u64, CandleTrainerError> {
    let mut optimizer = SGD::new(model.vars(), f64::from(config.learning_rate))?;
    let mut order = (0..rows.len()).collect::<Vec<_>>();
    let batch_size = usize::try_from(config.batch_size)
        .map_err(|_| CandleTrainerError::Contract("batch size"))?;
    let mut batch_features = Vec::with_capacity(batch_size * FEATURE_DIM);
    let mut batch_labels = Vec::with_capacity(batch_size);
    let mut steps = 0_u64;
    for _ in 0..config.epochs {
        shuffle(&mut order, random);
        for batch in order.chunks(batch_size) {
            batch_features.clear();
            batch_labels.clear();
            for &index in batch {
                batch_features.extend_from_slice(&rows[index].features);
                batch_labels.push(f32::from(rows[index].label));
            }
            let features = Tensor::from_slice(&batch_features, (batch.len(), FEATURE_DIM), device)?;
            let labels = Tensor::from_slice(&batch_labels, (batch.len(), 1), device)?;
            let logits = model.logits(&features)?;
            let data_loss = candle_nn::loss::binary_cross_entropy_with_logit(&logits, &labels)?;
            let loss = (data_loss + model.l2_penalty(config.l2)?)?;
            optimizer.backward_step(&loss)?;
            steps = steps
                .checked_add(1)
                .ok_or(CandleTrainerError::Contract("optimizer step overflow"))?;
        }
    }
    Ok(steps)
}

fn candle_scores(
    model: &CandleMlp,
    rows: &[[f32; FEATURE_DIM]],
    device: &Device,
) -> Result<Vec<f32>, CandleTrainerError> {
    let mut flattened = Vec::with_capacity(rows.len() * FEATURE_DIM);
    for row in rows {
        flattened.extend_from_slice(row);
    }
    let features = Tensor::from_vec(flattened, (rows.len(), FEATURE_DIM), device)?;
    Ok(candle_nn::ops::sigmoid(&model.logits(&features)?)?
        .flatten_all()?
        .to_vec1::<f32>()?)
}

fn tensor_values(tensor: &Tensor) -> Result<Vec<f32>, CandleTrainerError> {
    Ok(tensor.flatten_all()?.to_vec1::<f32>()?)
}

fn model_tensor(name: &str, shape: &[u64], values: Vec<f32>) -> FrozenModelTensor {
    FrozenModelTensor {
        name: name.into(),
        shape: shape.to_vec(),
        values,
    }
}

fn optimizer_state_digest(learning_rate: f32, steps: u64) -> CompactString {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix-candle-sgd-state/v1");
    hasher.update(&learning_rate.to_bits().to_le_bytes());
    hasher.update(&steps.to_le_bytes());
    format_compact!("b3-{}", hasher.finalize().to_hex())
}

fn max_abs_error(left: &[f32], right: &[f32]) -> Result<f32, CandleTrainerError> {
    if left.len() != right.len() {
        return Err(CandleTrainerError::Contract("score shape parity"));
    }
    Ok(left
        .iter()
        .zip(right)
        .map(|(left, right)| (left - right).abs())
        .fold(0.0_f32, f32::max))
}

fn score_bits(scores: &[f32]) -> Vec<u32> {
    scores.iter().map(|score| score.to_bits()).collect()
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value[3..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn micros(duration: std::time::Duration) -> u64 {
    duration.as_micros().try_into().unwrap_or(u64::MAX)
}

struct SplitMix64(u64);

impl SplitMix64 {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }

    fn signed_unit(&mut self) -> f32 {
        let unit = (self.next() >> 40) as f32 / (1_u32 << 24) as f32;
        unit * 2.0 - 1.0
    }
}

fn shuffle(values: &mut [usize], random: &mut SplitMix64) {
    for index in (1..values.len()).rev() {
        let selected = (random.next() % (index as u64 + 1)) as usize;
        values.swap(index, selected);
    }
}
