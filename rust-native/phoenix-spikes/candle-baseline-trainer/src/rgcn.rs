use crate::telemetry::{peak_working_set_bytes, AllocationSnapshot};
use crate::{
    micros, model_tensor, open_authority, optimizer_state_digest, prepare_rows, score_bits,
    tensor_values, CandleTrainerError, CandleTrainerRequest, SplitMix64, TYPED_LINK_BINARY_TASK_ID,
    TYPED_LINK_TASK_ID,
};
use candle_core::{DType, Device, Tensor, Var};
use candle_nn::{Optimizer, SGD};
use compact_str::CompactString;
use phoenix_graph_research::{
    certify_model_scores, certify_model_seed_receipt, evaluate_binary_scores,
    evaluate_ranking_scores, open_frozen_model_selection_ledger, score_rgcn16,
    score_rgcn16_tensors, stage_rgcn_input, BinaryMetrics, FrozenModelArchitecture,
    FrozenModelBundle, FrozenModelHyperparameters, FrozenModelMapped, FrozenModelPaths,
    FrozenModelRuntimeIdentity, FrozenModelSnapshot, FrozenModelTensor, FrozenOptimizerReceipt,
    FrozenTrainingReceipt, RankingMetrics, ResearchSplit, RgcnGraphBatch, RgcnQueryBatch,
    RgcnStagedInput, RgcnStagingProfile, RANKING_EVALUATION_SCHEMA, RESEARCH_EVALUATION_SCHEMA,
    RGCN_DECODER_BIAS, RGCN_DECODER_RELATION, RGCN_NODE_TYPE_EMBEDDING, RGCN_RELATION_WEIGHT,
    RGCN_SELF_WEIGHT,
};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::time::Instant;

pub const CANDLE_RGCN_TRAINER_ID: &str = "candle-rgcn16/v1";
pub const CANDLE_RGCN_REPORT_SCHEMA: &str = "phoenix-candle-rgcn-report/v1";
const HIDDEN: usize = 16;

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CandleRgcnConfig {
    pub epochs: u32,
    pub learning_rate: f32,
    pub l2: f32,
}

impl Default for CandleRgcnConfig {
    fn default() -> Self {
        Self {
            epochs: 80,
            learning_rate: 0.03,
            l2: 0.0001,
        }
    }
}

impl CandleRgcnConfig {
    fn validate(self) -> Result<(), CandleTrainerError> {
        if self.epochs == 0
            || !self.learning_rate.is_finite()
            || self.learning_rate <= 0.0
            || !self.l2.is_finite()
            || self.l2 < 0.0
        {
            return Err(CandleTrainerError::Contract("R-GCN configuration"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct CandleRgcnRequest {
    pub authority: CandleTrainerRequest,
    pub baseline_ledger: PathBuf,
    pub baseline_manifest: PathBuf,
    pub config: CandleRgcnConfig,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CandleRgcnReport {
    pub schema_version: CompactString,
    pub model_id: CompactString,
    pub weights_blake3: CompactString,
    pub baseline_ledger_id: CompactString,
    pub baseline_model_id: CompactString,
    pub selected_seed: u64,
    pub training_micros: u64,
    pub canonical_scoring_micros: u64,
    pub restart_open_and_score_micros: u64,
    pub allocation_volume_bytes: u64,
    pub allocation_count: u64,
    pub peak_working_set_bytes: u64,
    pub source_mmap_bytes: u64,
    pub restart_weight_mmap_bytes: u64,
    pub mmap_bytes: u64,
    pub staging: RgcnStagingProfile,
    pub baseline_validation: BinaryMetrics,
    pub rgcn_validation: BinaryMetrics,
    pub baseline_ranking: RankingMetrics,
    pub rgcn_ranking: RankingMetrics,
    pub beats_frozen_baseline: bool,
    pub restart_score_bits_exact: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CandleRgcnOutcome {
    pub artifact: FrozenModelPaths,
    pub report: CandleRgcnReport,
}

pub fn train_candle_rgcn16(
    request: &CandleRgcnRequest,
) -> Result<CandleRgcnOutcome, CandleTrainerError> {
    let allocations_started = AllocationSnapshot::now();
    request.config.validate()?;
    request.authority.config.validate()?;
    let authority = open_authority(&request.authority)?;
    let seed_receipt =
        certify_model_seed_receipt(&authority.seeds, request.authority.selected_repeat)?;
    let seed = seed_receipt
        .selected_seed()
        .ok_or(CandleTrainerError::Contract("selected R-GCN seed"))?;
    let mut staged = stage_rgcn_input(&authority.tensor, &authority.topology)?;
    let rows = prepare_rows(&authority.topology)?;
    if rows.validation.len() != staged.validation.len()
        || rows
            .validation
            .iter()
            .map(|row| row.label)
            .ne(staged.validation.labels.iter().copied())
    {
        return Err(CandleTrainerError::Contract("shared evaluator row order"));
    }
    let ledger = open_frozen_model_selection_ledger(&request.baseline_ledger)?;
    let baseline = FrozenModelMapped::open(&request.baseline_manifest)?;
    if baseline.manifest().source != authority.identity
        || ledger.source != authority.identity
        || ledger.seed_certificate != authority.seeds
        || ledger.selected_validation_model_id != baseline.manifest().model_id
        || ledger.selected_weights_blake3 != baseline.manifest().weights_blake3
        || ledger.policy.task_id != TYPED_LINK_BINARY_TASK_ID
        || ledger.policy.evaluator_schema != RESEARCH_EVALUATION_SCHEMA
        || ledger.policy.calibration_bins != 10
        || baseline.manifest().architecture != FrozenModelArchitecture::mlp16()
        || baseline
            .manifest()
            .score_certificates
            .iter()
            .any(|certificate| certificate.split == ResearchSplit::Test)
    {
        return Err(CandleTrainerError::Contract("frozen baseline authority"));
    }
    let baseline_scores = baseline.score_mlp16(&rows.validation_features)?;
    let baseline_validation =
        evaluate_binary_scores(&staged.validation.labels, &baseline_scores, 10)?;
    let baseline_ranking = evaluate_ranking_scores(
        &rows.validation,
        &baseline_scores,
        ResearchSplit::Validation,
    )?
    .ok_or(CandleTrainerError::Contract("baseline ranking rows"))?;
    let baseline_ledger_id = ledger.ledger_id.clone();
    let baseline_model_id = baseline.manifest().model_id.clone();
    let source_mmap_bytes = authority.mmap_bytes;

    let device = Device::Cpu;
    let runtime = RgcnRuntime::new(&staged, &device)?;
    let model = CandleRgcn::new(
        seed,
        authority.tensor.manifest().node_type_vocabulary.len(),
        staged.graph.relation_batches.len(),
        staged.graph.relation_count as usize,
        &device,
    )?;
    let training_started = Instant::now();
    train_model(&model, &runtime, request.config)?;
    let training_micros = micros(training_started.elapsed());
    staged.profile.frozen_relation_batch_required = staged.profile.staging_micros >= 5_000
        && staged.profile.staging_micros.saturating_mul(4) >= training_micros;
    if staged.profile.frozen_relation_batch_required {
        return Err(CandleTrainerError::Contract(
            "profile requires a frozen relation batch",
        ));
    }
    let candle_scores = model.scores(&runtime.graph, &runtime.validation)?;
    let tensors = model.export()?;
    drop(model);
    drop(runtime);

    let canonical_started = Instant::now();
    let canonical_scores = score_rgcn16_tensors(&tensors, &staged.graph, &staged.validation)?;
    let canonical_scoring_micros = micros(canonical_started.elapsed());
    if max_abs_error(&candle_scores, &canonical_scores)? > 1.0e-4 {
        return Err(CandleTrainerError::Contract("Candle/R-GCN SIMD parity"));
    }
    let rgcn_validation = evaluate_binary_scores(&staged.validation.labels, &canonical_scores, 10)?;
    let rgcn_ranking = evaluate_ranking_scores(
        &rows.validation,
        &canonical_scores,
        ResearchSplit::Validation,
    )?
    .ok_or(CandleTrainerError::Contract("R-GCN ranking rows"))?;
    let beats_frozen_baseline = beats(&rgcn_validation, &baseline_validation);
    if !beats_frozen_baseline {
        return Err(CandleTrainerError::Contract(
            "R-GCN must beat frozen baseline",
        ));
    }
    let certificates = vec![
        certify_model_scores(
            TYPED_LINK_BINARY_TASK_ID,
            RESEARCH_EVALUATION_SCHEMA,
            ResearchSplit::Validation,
            &canonical_scores,
            &rgcn_validation,
        )?,
        certify_model_scores(
            TYPED_LINK_TASK_ID,
            RANKING_EVALUATION_SCHEMA,
            ResearchSplit::Validation,
            &canonical_scores,
            &rgcn_ranking,
        )?,
    ];
    let optimizer = FrozenOptimizerReceipt {
        algorithm: "sgd-full-batch".into(),
        implementation_version: "candle-nn-sgd/0.11.0-rgcn".into(),
        steps_completed: u64::from(request.config.epochs),
        state_blake3: optimizer_state_digest(
            request.config.learning_rate,
            u64::from(request.config.epochs),
        ),
    };
    let batch_size = u32::try_from(staged.train.len())
        .map_err(|_| CandleTrainerError::Contract("R-GCN batch size"))?;
    let training_examples = staged.train.len() as u64;
    let validation_examples = staged.validation.len() as u64;
    let staging_profile = staged.profile.clone();
    let snapshot = FrozenModelSnapshot {
        source: authority.identity.clone(),
        architecture: FrozenModelArchitecture::rgcn16(),
        hyperparameters: FrozenModelHyperparameters {
            epochs: request.config.epochs,
            batch_size,
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
            trainer_id: CANDLE_RGCN_TRAINER_ID.into(),
            training_examples,
            validation_examples,
            epochs_completed: request.config.epochs,
            training_executions: 1,
            selected_on_validation: true,
            test_locked_during_selection: true,
            optimizer,
        },
        score_certificates: certificates,
        tensors,
    };
    let artifact = FrozenModelBundle::write(&snapshot, &request.authority.output_root)?;
    drop(snapshot);
    drop(staged);
    drop(authority);
    drop(baseline);
    drop(ledger);
    let restart_started = Instant::now();
    let restart_authority = open_authority(&request.authority)?;
    let restart_staged = stage_rgcn_input(&restart_authority.tensor, &restart_authority.topology)?;
    let mapped = FrozenModelMapped::open(&artifact.manifest)?;
    if restart_authority.identity != mapped.manifest().source {
        return Err(CandleTrainerError::Contract(
            "R-GCN restart source identity",
        ));
    }
    let restart_scores = score_rgcn16(&mapped, &restart_staged.graph, &restart_staged.validation)?;
    let restart_open_and_score_micros = micros(restart_started.elapsed());
    let restart_score_bits_exact = score_bits(&restart_scores) == score_bits(&canonical_scores);
    if !restart_score_bits_exact {
        return Err(CandleTrainerError::Contract("R-GCN restart score parity"));
    }
    if restart_open_and_score_micros.saturating_mul(2) >= training_micros {
        return Err(CandleTrainerError::Contract(
            "R-GCN restart must be materially faster than training",
        ));
    }
    let restart_weight_mmap_bytes = mapped.manifest().weights_bytes;
    let mmap_bytes = source_mmap_bytes
        .checked_add(restart_weight_mmap_bytes)
        .ok_or(CandleTrainerError::Contract("R-GCN mmap byte overflow"))?;
    let allocation_delta = allocations_started.elapsed();
    Ok(CandleRgcnOutcome {
        report: CandleRgcnReport {
            schema_version: CANDLE_RGCN_REPORT_SCHEMA.into(),
            model_id: mapped.manifest().model_id.clone(),
            weights_blake3: mapped.manifest().weights_blake3.clone(),
            baseline_ledger_id,
            baseline_model_id,
            selected_seed: seed,
            training_micros,
            canonical_scoring_micros,
            restart_open_and_score_micros,
            allocation_volume_bytes: allocation_delta.bytes,
            allocation_count: allocation_delta.count,
            peak_working_set_bytes: peak_working_set_bytes()?,
            source_mmap_bytes,
            restart_weight_mmap_bytes,
            mmap_bytes,
            staging: staging_profile,
            baseline_validation,
            rgcn_validation,
            baseline_ranking,
            rgcn_ranking,
            beats_frozen_baseline,
            restart_score_bits_exact,
        },
        artifact,
    })
}

struct CandleRgcn {
    node_types: Var,
    self_weight: Var,
    relation_weight: Var,
    decoder: Var,
    bias: Var,
    message_relations: usize,
    decoder_relations: usize,
}

impl CandleRgcn {
    fn new(
        seed: u64,
        node_types: usize,
        message_relations: usize,
        decoder_relations: usize,
        device: &Device,
    ) -> Result<Self, CandleTrainerError> {
        if node_types == 0 || decoder_relations == 0 || message_relations < decoder_relations * 2 {
            return Err(CandleTrainerError::Contract("R-GCN vocabulary"));
        }
        let mut random = SplitMix64(seed);
        let mut initialized = |count: usize| {
            (0..count)
                .map(|_| random.signed_unit() * 0.12)
                .collect::<Vec<_>>()
        };
        Ok(Self {
            node_types: variable(
                initialized(node_types * HIDDEN),
                (node_types, HIDDEN),
                device,
            )?,
            self_weight: variable(initialized(HIDDEN * HIDDEN), (HIDDEN, HIDDEN), device)?,
            relation_weight: variable(
                initialized(message_relations * HIDDEN * HIDDEN),
                (message_relations, HIDDEN, HIDDEN),
                device,
            )?,
            decoder: variable(
                initialized(decoder_relations * HIDDEN),
                (decoder_relations, HIDDEN),
                device,
            )?,
            bias: Var::zeros(decoder_relations, DType::F32, device)?,
            message_relations,
            decoder_relations,
        })
    }

    fn vars(&self) -> Vec<Var> {
        vec![
            self.node_types.clone(),
            self.self_weight.clone(),
            self.relation_weight.clone(),
            self.decoder.clone(),
            self.bias.clone(),
        ]
    }

    fn encode(&self, graph: &GraphRuntime) -> candle_core::Result<Tensor> {
        let initial = self
            .node_types
            .as_tensor()
            .index_select(&graph.node_types, 0)?;
        let mut encoded = initial.matmul(&self.self_weight.as_tensor().t()?)?;
        for (relation, batch) in graph.relations.iter().enumerate() {
            if batch.len == 0 {
                continue;
            }
            let source = initial.index_select(&batch.sources, 0)?;
            let matrix = self.relation_weight.as_tensor().get(relation)?;
            let messages = source
                .matmul(&matrix.t()?)?
                .broadcast_mul(&batch.normalizers.unsqueeze(1)?)?;
            encoded = encoded.index_add(&batch.targets, &messages, 0)?;
        }
        encoded.relu()
    }

    fn scores(
        &self,
        graph: &GraphRuntime,
        queries: &QueryRuntime,
    ) -> candle_core::Result<Vec<f32>> {
        candle_nn::ops::sigmoid(&self.logits(graph, queries)?)?.to_vec1::<f32>()
    }

    fn logits(&self, graph: &GraphRuntime, queries: &QueryRuntime) -> candle_core::Result<Tensor> {
        let encoded = self.encode(graph)?;
        let source = encoded.index_select(&queries.sources, 0)?;
        let target = encoded.index_select(&queries.targets, 0)?;
        let relation = self
            .decoder
            .as_tensor()
            .index_select(&queries.relations, 0)?;
        let product = source.mul(&target)?.mul(&relation)?;
        let logits = product.sum(1)?;
        logits.add(&self.bias.as_tensor().index_select(&queries.relations, 0)?)
    }

    fn l2_penalty(&self, l2: f32) -> candle_core::Result<Tensor> {
        let mut total = self.node_types.as_tensor().sqr()?.sum_all()?;
        for value in [&self.self_weight, &self.relation_weight, &self.decoder] {
            total = (total + value.as_tensor().sqr()?.sum_all()?)?;
        }
        total.affine(f64::from(l2) * 0.5, 0.0)
    }

    fn export(&self) -> Result<Vec<FrozenModelTensor>, CandleTrainerError> {
        Ok(vec![
            model_tensor(
                RGCN_NODE_TYPE_EMBEDDING,
                &[self.node_types.dims()[0] as u64, HIDDEN as u64],
                tensor_values(self.node_types.as_tensor())?,
            ),
            model_tensor(
                RGCN_SELF_WEIGHT,
                &[HIDDEN as u64, HIDDEN as u64],
                tensor_values(self.self_weight.as_tensor())?,
            ),
            model_tensor(
                RGCN_RELATION_WEIGHT,
                &[self.message_relations as u64, HIDDEN as u64, HIDDEN as u64],
                tensor_values(self.relation_weight.as_tensor())?,
            ),
            model_tensor(
                RGCN_DECODER_RELATION,
                &[self.decoder_relations as u64, HIDDEN as u64],
                tensor_values(self.decoder.as_tensor())?,
            ),
            model_tensor(
                RGCN_DECODER_BIAS,
                &[self.decoder_relations as u64],
                tensor_values(self.bias.as_tensor())?,
            ),
        ])
    }
}

struct RelationRuntime {
    sources: Tensor,
    targets: Tensor,
    normalizers: Tensor,
    len: usize,
}

struct GraphRuntime {
    node_types: Tensor,
    relations: Vec<RelationRuntime>,
}

struct QueryRuntime {
    sources: Tensor,
    targets: Tensor,
    relations: Tensor,
    labels: Tensor,
}

struct RgcnRuntime {
    graph: GraphRuntime,
    train: QueryRuntime,
    validation: QueryRuntime,
}

impl RgcnRuntime {
    fn new(staged: &RgcnStagedInput, device: &Device) -> Result<Self, CandleTrainerError> {
        Ok(Self {
            graph: GraphRuntime::new(&staged.graph, device)?,
            train: QueryRuntime::new(&staged.train, device)?,
            validation: QueryRuntime::new(&staged.validation, device)?,
        })
    }
}

impl GraphRuntime {
    fn new(graph: &RgcnGraphBatch, device: &Device) -> Result<Self, CandleTrainerError> {
        let mut relations = Vec::with_capacity(graph.relation_batches.len());
        for batch in &graph.relation_batches {
            relations.push(RelationRuntime {
                sources: Tensor::from_vec(batch.sources.clone(), batch.sources.len(), device)?,
                targets: Tensor::from_vec(batch.targets.clone(), batch.targets.len(), device)?,
                normalizers: Tensor::from_vec(
                    batch.normalizers.clone(),
                    batch.normalizers.len(),
                    device,
                )?,
                len: batch.sources.len(),
            });
        }
        Ok(Self {
            node_types: Tensor::from_vec(graph.node_types.clone(), graph.node_types.len(), device)?,
            relations,
        })
    }
}

impl QueryRuntime {
    fn new(queries: &RgcnQueryBatch, device: &Device) -> Result<Self, CandleTrainerError> {
        Ok(Self {
            sources: Tensor::from_vec(queries.sources.clone(), queries.len(), device)?,
            targets: Tensor::from_vec(queries.targets.clone(), queries.len(), device)?,
            relations: Tensor::from_vec(queries.relations.clone(), queries.len(), device)?,
            labels: Tensor::from_vec(
                queries
                    .labels
                    .iter()
                    .map(|label| f32::from(*label))
                    .collect::<Vec<_>>(),
                queries.len(),
                device,
            )?,
        })
    }
}

fn train_model(
    model: &CandleRgcn,
    runtime: &RgcnRuntime,
    config: CandleRgcnConfig,
) -> Result<(), CandleTrainerError> {
    let mut optimizer = SGD::new(model.vars(), f64::from(config.learning_rate))?;
    for _ in 0..config.epochs {
        let logits = model.logits(&runtime.graph, &runtime.train)?;
        let data_loss =
            candle_nn::loss::binary_cross_entropy_with_logit(&logits, &runtime.train.labels)?;
        let loss = (data_loss + model.l2_penalty(config.l2)?)?;
        optimizer.backward_step(&loss)?;
    }
    Ok(())
}

fn variable<S: Into<candle_core::Shape>>(
    values: Vec<f32>,
    shape: S,
    device: &Device,
) -> Result<Var, CandleTrainerError> {
    Ok(Var::from_tensor(&Tensor::from_vec(values, shape, device)?)?)
}

fn beats(candidate: &BinaryMetrics, baseline: &BinaryMetrics) -> bool {
    match (candidate.average_precision, baseline.average_precision) {
        (Some(candidate_ap), Some(baseline_ap)) => {
            candidate_ap > baseline_ap
                || (candidate_ap == baseline_ap && candidate.brier_score < baseline.brier_score)
        }
        _ => false,
    }
}

fn max_abs_error(left: &[f32], right: &[f32]) -> Result<f32, CandleTrainerError> {
    if left.len() != right.len() {
        return Err(CandleTrainerError::Contract("R-GCN score shape"));
    }
    Ok(left
        .iter()
        .zip(right)
        .map(|(left, right)| (left - right).abs())
        .fold(0.0_f32, f32::max))
}
