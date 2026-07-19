use crate::native_rgcn_fused::{train_fused_rgcn16, FusedRgcnTrainingOutcome};
use crate::telemetry::{peak_working_set_bytes, AllocationSnapshot};
use crate::{micros, CandleRgcnConfig, CandleTrainerError};
use compact_str::{format_compact, CompactString};
use memmap2::MmapOptions;
use phoenix_graph_research::{
    evaluate_binary_scores, BinaryMetrics, RgcnGraphBatch, RgcnQueryBatch, RgcnRelationBatch,
    RgcnStagedInput, RgcnStagingProfile,
};
use phoenix_store_native_core::PhoenixNativeDecisionStore;
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{
    GraphDecisionAction, GraphDecisionRewardDimension, NativeDecisionReceipt,
    NativeDecisionRewardObservationOperation,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;
use wide::f32x8;
use zerocopy::IntoBytes;

pub const NATIVE_RGCN_CALIBRATION_SCHEMA: &str = "phoenix-native-rgcn-calibration/v1";
pub const NATIVE_RGCN_CALIBRATION_MODEL_SCHEMA: &str = "phoenix-native-rgcn-calibration-model/v1";
pub const NATIVE_RGCN_CALIBRATION_ARM_ID: &str = "receipt-ordinal-rgcn16/train-only/v1";
const HIDDEN: usize = 16;
const MAX_CANDIDATES: usize = 5;
const ACTION_CLASSES: usize = 4;
const FORWARD_RELATIONS: usize = ACTION_CLASSES * MAX_CANDIDATES;
const MESSAGE_RELATIONS: usize = FORWARD_RELATIONS * 2;
const DECODER_RELATIONS: usize = 1;
const NODE_TYPES: usize = 5;

#[derive(Clone, Debug, PartialEq)]
pub struct NativeRgcnCalibrationRequest {
    pub store_path: PathBuf,
    pub output_root: PathBuf,
    pub expected_receipts: usize,
    pub seed: u64,
    pub config: CandleRgcnConfig,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct NativeRgcnCohortStatus {
    pub outcome_receipts: u64,
    pub mature_trajectories: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRgcnCalibrationReport {
    pub schema_version: CompactString,
    pub arm_id: CompactString,
    pub cohort_blake3: CompactString,
    pub receipt_count: u64,
    pub candidate_count: u64,
    pub outcome_receipt_count: u64,
    pub mature_trajectory_count: u64,
    pub first_observed_at: i64,
    pub last_observed_at: i64,
    pub cohort_window_ms: i64,
    pub source_lineage_count: u64,
    pub pre_state_count: u64,
    pub candidate_count_histogram: BTreeMap<u32, u64>,
    pub chosen_action_histogram: BTreeMap<CompactString, u64>,
    pub chosen_ordinal_histogram: BTreeMap<u32, u64>,
    pub selected_seed: u64,
    pub epochs: u32,
    pub learning_rate: f32,
    pub l2: f32,
    pub score_blake3: CompactString,
    pub weights_blake3: CompactString,
    pub weights_bytes: u64,
    pub binary_train_rescore: BinaryMetrics,
    pub train_top1_accuracy: f64,
    pub train_mean_reciprocal_rank: f64,
    pub training_micros: u64,
    pub canonical_scoring_micros: u64,
    pub artifact_write_micros: u64,
    pub restart_open_micros: u64,
    pub restart_scoring_micros: u64,
    pub allocation_volume_bytes: u64,
    pub allocation_count: u64,
    pub peak_working_set_bytes: u64,
    pub staged_bytes: u64,
    pub mmap_bytes: u64,
    pub parameter_bytes: u64,
    pub gradient_arena_bytes: u64,
    pub epoch_allocation_volume_bytes: u64,
    pub epoch_allocation_count: u64,
    pub training_kernel: CompactString,
    pub restart_score_bits_exact: bool,
    pub feature_authority: CompactString,
    pub evaluation_split: CompactString,
    pub promotion_eligible: bool,
    pub promotion_locks: Vec<CompactString>,
    pub model_manifest: PathBuf,
    pub weights_file: PathBuf,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CalibrationModelManifest {
    schema_version: CompactString,
    arm_id: CompactString,
    cohort_blake3: CompactString,
    weights_file: CompactString,
    weights_blake3: CompactString,
    weights_bytes: u64,
    node_types: u32,
    message_relations: u32,
    decoder_relations: u32,
    tensor_offsets: [u64; 6],
    selected_seed: u64,
    config: CandleRgcnConfig,
}

#[derive(Debug, thiserror::Error)]
pub enum NativeRgcnCalibrationError {
    #[error("native R-GCN calibration contract is invalid: {0}")]
    Contract(&'static str),
    #[error("native decision store failed: {0}")]
    Store(String),
    #[error("native R-GCN training failed: {0}")]
    Trainer(#[from] CandleTrainerError),
    #[error("native R-GCN evaluation failed: {0}")]
    Evaluation(#[from] phoenix_graph_research::ResearchEvaluationError),
    #[error("native R-GCN artifact I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("native R-GCN artifact JSON failed: {0}")]
    Json(#[from] serde_json::Error),
    #[error("native R-GCN mmap layout failed: {0}")]
    Mmap(&'static str),
}

pub fn run_native_rgcn_calibration(
    request: &NativeRgcnCalibrationRequest,
) -> Result<NativeRgcnCalibrationReport, NativeRgcnCalibrationError> {
    let store = PhoenixOvergraphStore::open(&request.store_path)
        .map_err(|error| NativeRgcnCalibrationError::Store(error.to_string()))?;
    let decisions = store
        .load_native_decision_receipts()
        .map_err(|error| NativeRgcnCalibrationError::Store(error.to_string()))?;
    let mut outcome_receipts = 0_u64;
    let mut mature_trajectories = 0_u64;
    for decision in &decisions {
        let outcomes = store
            .load_native_decision_outcome_receipts(&decision.receipt_id)
            .map_err(|error| NativeRgcnCalibrationError::Store(error.to_string()))?;
        outcome_receipts = outcome_receipts.saturating_add(outcomes.len() as u64);
        let observations = store
            .load_native_decision_reward_observations(&decision.receipt_id)
            .map_err(|error| NativeRgcnCalibrationError::Store(error.to_string()))?;
        mature_trajectories += u64::from(
            observations
                .iter()
                .filter(|row| row.dimension == GraphDecisionRewardDimension::FutureStability)
                .max_by(|left, right| {
                    (left.observed_at, left.receipt_id.as_str())
                        .cmp(&(right.observed_at, right.receipt_id.as_str()))
                })
                .is_some_and(|row| {
                    row.operation != NativeDecisionRewardObservationOperation::Retract
                        && row.score_micros.is_some()
                }),
        );
    }
    drop(store);
    train_native_rgcn_calibration(
        decisions,
        NativeRgcnCohortStatus {
            outcome_receipts,
            mature_trajectories,
        },
        request,
    )
}

pub fn train_native_rgcn_calibration(
    mut decisions: Vec<NativeDecisionReceipt>,
    status: NativeRgcnCohortStatus,
    request: &NativeRgcnCalibrationRequest,
) -> Result<NativeRgcnCalibrationReport, NativeRgcnCalibrationError> {
    let allocations = AllocationSnapshot::now();
    decisions.sort_unstable_by(|left, right| {
        (left.observed_at, left.receipt_id.as_str())
            .cmp(&(right.observed_at, right.receipt_id.as_str()))
    });
    validate_cohort(&decisions, status, request.expected_receipts)?;
    let cohort = summarize_cohort(&decisions)?;
    let staged = stage_receipt_graph(&decisions)?;
    let labels = staged.validation.labels.clone();
    let trained = train_fused_rgcn16(&staged, request.config, request.seed)?;
    let binary_train_rescore = evaluate_binary_scores(&labels, &trained.scores, 10)?;
    let (train_top1_accuracy, train_mean_reciprocal_rank) =
        grouped_train_metrics(&decisions, &trained.scores)?;
    let score_blake3 = score_digest(&trained.scores);
    let artifact_started = Instant::now();
    let (manifest_path, weights_path, manifest) = write_model(
        &request.output_root,
        &cohort.cohort_blake3,
        request.seed,
        request.config,
        &trained,
    )?;
    let artifact_write_micros = micros(artifact_started.elapsed());
    let restart_open_started = Instant::now();
    let mapped = MappedCalibrationModel::open(&manifest_path)?;
    let restart_open_micros = micros(restart_open_started.elapsed());
    let restart_scoring_started = Instant::now();
    let restart_scores = mapped.score(&staged.graph, &staged.validation)?;
    let restart_scoring_micros = micros(restart_scoring_started.elapsed());
    let restart_score_bits_exact = score_bits(&trained.scores) == score_bits(&restart_scores);
    if !restart_score_bits_exact || score_digest(&restart_scores) != score_blake3 {
        return Err(NativeRgcnCalibrationError::Contract(
            "cold mmap restart score parity",
        ));
    }
    let allocation_delta = allocations.elapsed();
    let promotion_locks = promotion_locks(&cohort, status);
    let report = NativeRgcnCalibrationReport {
        schema_version: NATIVE_RGCN_CALIBRATION_SCHEMA.into(),
        arm_id: NATIVE_RGCN_CALIBRATION_ARM_ID.into(),
        cohort_blake3: cohort.cohort_blake3,
        receipt_count: decisions.len() as u64,
        candidate_count: labels.len() as u64,
        outcome_receipt_count: status.outcome_receipts,
        mature_trajectory_count: status.mature_trajectories,
        first_observed_at: cohort.first_observed_at,
        last_observed_at: cohort.last_observed_at,
        cohort_window_ms: cohort.last_observed_at - cohort.first_observed_at,
        source_lineage_count: cohort.source_lineage_count,
        pre_state_count: cohort.pre_state_count,
        candidate_count_histogram: cohort.candidate_count_histogram,
        chosen_action_histogram: cohort.chosen_action_histogram,
        chosen_ordinal_histogram: cohort.chosen_ordinal_histogram,
        selected_seed: request.seed,
        epochs: request.config.epochs,
        learning_rate: request.config.learning_rate,
        l2: request.config.l2,
        score_blake3,
        weights_blake3: manifest.weights_blake3,
        weights_bytes: manifest.weights_bytes,
        binary_train_rescore,
        train_top1_accuracy,
        train_mean_reciprocal_rank,
        training_micros: trained.training_micros,
        canonical_scoring_micros: trained.canonical_scoring_micros,
        artifact_write_micros,
        restart_open_micros,
        restart_scoring_micros,
        allocation_volume_bytes: allocation_delta.bytes,
        allocation_count: allocation_delta.count,
        peak_working_set_bytes: peak_working_set_bytes()?,
        staged_bytes: staged.profile.staged_bytes,
        mmap_bytes: mapped.bytes(),
        parameter_bytes: trained.parameter_bytes,
        gradient_arena_bytes: trained.gradient_arena_bytes,
        epoch_allocation_volume_bytes: trained.epoch_allocation_volume_bytes,
        epoch_allocation_count: trained.epoch_allocation_count,
        training_kernel: "preallocated-wide-f32x8-full-batch-sgd/v1".into(),
        restart_score_bits_exact,
        feature_authority: "receipt-only:action-family+generator-ordinal; label-excluded".into(),
        evaluation_split: "train-rescore-only; temporal-validation-unavailable".into(),
        promotion_eligible: false,
        promotion_locks,
        model_manifest: manifest_path,
        weights_file: weights_path,
    };
    write_certificate(&request.output_root, &report)?;
    Ok(report)
}

struct CohortSummary {
    cohort_blake3: CompactString,
    first_observed_at: i64,
    last_observed_at: i64,
    source_lineage_count: u64,
    pre_state_count: u64,
    candidate_count_histogram: BTreeMap<u32, u64>,
    chosen_action_histogram: BTreeMap<CompactString, u64>,
    chosen_ordinal_histogram: BTreeMap<u32, u64>,
}

fn validate_cohort(
    decisions: &[NativeDecisionReceipt],
    status: NativeRgcnCohortStatus,
    expected: usize,
) -> Result<(), NativeRgcnCalibrationError> {
    if expected == 0 || decisions.len() != expected || status.outcome_receipts < expected as u64 {
        return Err(NativeRgcnCalibrationError::Contract(
            "exact receipt/outcome census",
        ));
    }
    let mut identities = BTreeSet::new();
    for decision in decisions {
        decision
            .validate()
            .map_err(|_| NativeRgcnCalibrationError::Contract("decision receipt validity"))?;
        if !identities.insert(decision.receipt_id.as_str())
            || !(2..=MAX_CANDIDATES).contains(&decision.candidates.len())
            || decision.chosen_candidate_ordinal as usize >= decision.candidates.len()
        {
            return Err(NativeRgcnCalibrationError::Contract(
                "receipt identity and candidate bounds",
            ));
        }
    }
    Ok(())
}

fn summarize_cohort(
    decisions: &[NativeDecisionReceipt],
) -> Result<CohortSummary, NativeRgcnCalibrationError> {
    let payload = serde_json::to_vec(decisions)?;
    let mut lineages = BTreeSet::new();
    let mut pre_states = BTreeSet::new();
    let mut candidate_count_histogram = BTreeMap::new();
    let mut chosen_action_histogram = BTreeMap::new();
    let mut chosen_ordinal_histogram = BTreeMap::new();
    for decision in decisions {
        lineages.extend(decision.lineage_ids.iter().map(|value| value.as_str()));
        pre_states.insert(decision.pre_state_snapshot_id.as_str());
        *candidate_count_histogram
            .entry(decision.candidates.len() as u32)
            .or_default() += 1;
        *chosen_ordinal_histogram
            .entry(decision.chosen_candidate_ordinal)
            .or_default() += 1;
        let chosen = &decision.candidates[decision.chosen_candidate_ordinal as usize];
        *chosen_action_histogram
            .entry(action_name(&chosen.action).into())
            .or_default() += 1;
    }
    Ok(CohortSummary {
        cohort_blake3: format_compact!("b3-{}", blake3::hash(&payload).to_hex()),
        first_observed_at: decisions.first().map_or(0, |value| value.observed_at),
        last_observed_at: decisions.last().map_or(0, |value| value.observed_at),
        source_lineage_count: lineages.len() as u64,
        pre_state_count: pre_states.len() as u64,
        candidate_count_histogram,
        chosen_action_histogram,
        chosen_ordinal_histogram,
    })
}

fn stage_receipt_graph(
    decisions: &[NativeDecisionReceipt],
) -> Result<RgcnStagedInput, NativeRgcnCalibrationError> {
    let started = Instant::now();
    let candidates = decisions
        .iter()
        .map(|decision| decision.candidates.len())
        .sum::<usize>();
    let nodes = decisions
        .len()
        .checked_add(candidates)
        .and_then(|value| value.checked_add(NODE_TYPES))
        .ok_or(NativeRgcnCalibrationError::Contract("node count"))?;
    let mut node_types = Vec::with_capacity(nodes);
    node_types.extend(0..NODE_TYPES as u32);
    let mut relation_batches = (0..MESSAGE_RELATIONS)
        .map(|_| RgcnRelationBatch {
            sources: Vec::new(),
            targets: Vec::new(),
            normalizers: Vec::new(),
        })
        .collect::<Vec<_>>();
    let mut queries = RgcnQueryBatch::with_capacity(candidates);
    for decision in decisions {
        let source = u32::try_from(node_types.len())
            .map_err(|_| NativeRgcnCalibrationError::Contract("node ordinal"))?;
        node_types.push(0);
        for (ordinal, candidate) in decision.candidates.iter().enumerate() {
            let target = u32::try_from(node_types.len())
                .map_err(|_| NativeRgcnCalibrationError::Contract("node ordinal"))?;
            let action_class = action_class(&candidate.action);
            node_types.push((action_class + 1) as u32);
            let forward = action_class * MAX_CANDIDATES + ordinal;
            push_edge(&mut relation_batches[forward], source, target);
            push_edge(
                &mut relation_batches[forward + FORWARD_RELATIONS],
                target,
                source,
            );
            queries.sources.push(source);
            queries.targets.push(target);
            queries.relations.push(0);
            queries
                .labels
                .push(ordinal == decision.chosen_candidate_ordinal as usize);
        }
    }
    let staged_bytes = node_types.capacity() * size_of::<u32>()
        + relation_batches.iter().fold(0, |total, batch| {
            total
                + batch.sources.capacity() * size_of::<u32>()
                + batch.targets.capacity() * size_of::<u32>()
                + batch.normalizers.capacity() * size_of::<f32>()
        })
        + queries.sources.capacity() * size_of::<u32>()
        + queries.targets.capacity() * size_of::<u32>()
        + queries.relations.capacity() * size_of::<u32>()
        + queries.labels.capacity() * size_of::<bool>();
    let validation = queries.clone();
    Ok(RgcnStagedInput {
        graph: RgcnGraphBatch {
            node_types,
            relation_batches,
            relation_count: DECODER_RELATIONS as u32,
        },
        train: queries,
        validation,
        profile: RgcnStagingProfile {
            source_edges: candidates as u64,
            train_message_edges: (candidates * 2) as u64,
            train_queries: candidates as u64,
            validation_queries: 0,
            incidence_rows_validated: 0,
            staged_bytes: staged_bytes as u64,
            staging_micros: micros(started.elapsed()),
            frozen_relation_batch_required: false,
        },
    })
}

fn push_edge(batch: &mut RgcnRelationBatch, source: u32, target: u32) {
    batch.sources.push(source);
    batch.targets.push(target);
    batch.normalizers.push(1.0);
}

fn action_class(action: &GraphDecisionAction) -> usize {
    match action {
        GraphDecisionAction::AttachToEpisode(_) => 0,
        GraphDecisionAction::CreateEpisode(_) => 1,
        GraphDecisionAction::Abstain(_) => 2,
        _ => 3,
    }
}

fn action_name(action: &GraphDecisionAction) -> &'static str {
    match action {
        GraphDecisionAction::AttachToEpisode(_) => "attach_to_episode",
        GraphDecisionAction::CreateEpisode(_) => "create_episode",
        GraphDecisionAction::Abstain(_) => "abstain",
        _ => "other",
    }
}

fn grouped_train_metrics(
    decisions: &[NativeDecisionReceipt],
    scores: &[f32],
) -> Result<(f64, f64), NativeRgcnCalibrationError> {
    let mut offset = 0_usize;
    let mut top1 = 0_u64;
    let mut reciprocal = 0.0_f64;
    for decision in decisions {
        let end = offset + decision.candidates.len();
        let group = scores
            .get(offset..end)
            .ok_or(NativeRgcnCalibrationError::Contract("grouped score shape"))?;
        let mut order = (0..group.len()).collect::<Vec<_>>();
        order.sort_unstable_by(|left, right| {
            group[*right]
                .total_cmp(&group[*left])
                .then_with(|| left.cmp(right))
        });
        let chosen = decision.chosen_candidate_ordinal as usize;
        let rank = order
            .iter()
            .position(|ordinal| *ordinal == chosen)
            .ok_or(NativeRgcnCalibrationError::Contract("chosen score rank"))?
            + 1;
        top1 += u64::from(rank == 1);
        reciprocal += 1.0 / rank as f64;
        offset = end;
    }
    if offset != scores.len() || decisions.is_empty() {
        return Err(NativeRgcnCalibrationError::Contract("grouped score census"));
    }
    Ok((
        top1 as f64 / decisions.len() as f64,
        reciprocal / decisions.len() as f64,
    ))
}

fn promotion_locks(cohort: &CohortSummary, status: NativeRgcnCohortStatus) -> Vec<CompactString> {
    let mut locks = vec![
        "train-only-rescore-is-not-validation".into(),
        "temporal-split-and-24h-embargo-unavailable".into(),
        "receipt-ordinal-features-are-not-native-rgcn-feature-v1".into(),
        "counterfactual-candidate-rewards-incomplete".into(),
    ];
    if cohort.last_observed_at - cohort.first_observed_at < 86_400_000 {
        locks.push("cohort-span-under-24h".into());
    }
    if cohort.chosen_action_histogram.len() < 2 {
        locks.push("chosen-action-family-collapsed".into());
    }
    if status.mature_trajectories == 0 {
        locks.push("zero-mature-trajectories".into());
    }
    locks
}

fn write_model(
    root: &Path,
    cohort_blake3: &str,
    seed: u64,
    config: CandleRgcnConfig,
    trained: &FusedRgcnTrainingOutcome,
) -> Result<(PathBuf, PathBuf, CalibrationModelManifest), NativeRgcnCalibrationError> {
    fs::create_dir_all(root)?;
    let mut values = Vec::new();
    let mut offsets = [0_u64; 6];
    for (index, tensor) in trained.tensors.iter().enumerate() {
        offsets[index] = values.len() as u64;
        values.extend_from_slice(&tensor.values);
    }
    offsets[5] = values.len() as u64;
    let bytes = values.as_slice().as_bytes();
    let weights_blake3 = format_compact!("b3-{}", blake3::hash(bytes).to_hex());
    let weights_name = format!("{}.rgcw", weights_blake3);
    let weights_path = root.join(&weights_name);
    write_once(&weights_path, bytes)?;
    let manifest = CalibrationModelManifest {
        schema_version: NATIVE_RGCN_CALIBRATION_MODEL_SCHEMA.into(),
        arm_id: NATIVE_RGCN_CALIBRATION_ARM_ID.into(),
        cohort_blake3: cohort_blake3.into(),
        weights_file: weights_name.into(),
        weights_blake3,
        weights_bytes: bytes.len() as u64,
        node_types: NODE_TYPES as u32,
        message_relations: MESSAGE_RELATIONS as u32,
        decoder_relations: DECODER_RELATIONS as u32,
        tensor_offsets: offsets,
        selected_seed: seed,
        config,
    };
    let manifest_path = root.join(format!(
        "{cohort_blake3}.{}.rgcn-calibration.json",
        manifest.weights_blake3
    ));
    write_json_once(&manifest_path, &manifest)?;
    Ok((manifest_path, weights_path, manifest))
}

fn write_once(path: &Path, bytes: &[u8]) -> Result<(), NativeRgcnCalibrationError> {
    match OpenOptions::new().write(true).create_new(true).open(path) {
        Ok(mut file) => {
            file.write_all(bytes)?;
            file.sync_all()?;
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            if fs::read(path)? != bytes {
                return Err(NativeRgcnCalibrationError::Contract(
                    "content-addressed artifact collision",
                ));
            }
        }
        Err(error) => return Err(error.into()),
    }
    Ok(())
}

fn write_json_once(path: &Path, value: &impl Serialize) -> Result<(), NativeRgcnCalibrationError> {
    let bytes = serde_json::to_vec_pretty(value)?;
    write_once(path, &bytes)
}

fn write_certificate(
    root: &Path,
    report: &NativeRgcnCalibrationReport,
) -> Result<(), NativeRgcnCalibrationError> {
    let path = root.join("native-rgcn-calibration-certificate.json");
    let temporary = root.join("native-rgcn-calibration-certificate.json.tmp");
    let bytes = serde_json::to_vec_pretty(report)?;
    let mut file = File::create(&temporary)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    if path.exists() {
        fs::remove_file(&path)?;
    }
    fs::rename(temporary, path)?;
    Ok(())
}

struct MappedCalibrationModel {
    manifest: CalibrationModelManifest,
    mmap: memmap2::Mmap,
}

impl MappedCalibrationModel {
    fn open(path: &Path) -> Result<Self, NativeRgcnCalibrationError> {
        let manifest: CalibrationModelManifest = serde_json::from_slice(&fs::read(path)?)?;
        validate_manifest(&manifest)?;
        let weights_path = path
            .parent()
            .ok_or(NativeRgcnCalibrationError::Contract("manifest parent"))?
            .join(manifest.weights_file.as_str());
        let file = File::open(weights_path)?;
        // SAFETY: the file is opened read-only and the mapping owns the file-backed view.
        let mmap = unsafe { MmapOptions::new().map(&file)? };
        if mmap.len() as u64 != manifest.weights_bytes
            || format_compact!("b3-{}", blake3::hash(&mmap).to_hex()) != manifest.weights_blake3
        {
            return Err(NativeRgcnCalibrationError::Contract(
                "mapped weight identity",
            ));
        }
        let _: &[f32] = bytemuck::try_cast_slice(&mmap)
            .map_err(|_| NativeRgcnCalibrationError::Mmap("f32 weight alignment"))?;
        Ok(Self { manifest, mmap })
    }

    fn bytes(&self) -> u64 {
        self.mmap.len() as u64
    }

    fn score(
        &self,
        graph: &RgcnGraphBatch,
        queries: &RgcnQueryBatch,
    ) -> Result<Vec<f32>, NativeRgcnCalibrationError> {
        let values: &[f32] = bytemuck::try_cast_slice(&self.mmap)
            .map_err(|_| NativeRgcnCalibrationError::Mmap("f32 weight alignment"))?;
        let offsets = self.manifest.tensor_offsets.map(|value| value as usize);
        let tensor = |index: usize| {
            values
                .get(offsets[index]..offsets[index + 1])
                .ok_or(NativeRgcnCalibrationError::Contract("mapped tensor range"))
        };
        score_mapped_rgcn(
            graph,
            queries,
            tensor(0)?,
            tensor(1)?,
            tensor(2)?,
            tensor(3)?,
            tensor(4)?,
        )
    }
}

fn validate_manifest(
    manifest: &CalibrationModelManifest,
) -> Result<(), NativeRgcnCalibrationError> {
    let expected = [
        0,
        (NODE_TYPES * HIDDEN) as u64,
        (NODE_TYPES * HIDDEN + HIDDEN * HIDDEN) as u64,
        (NODE_TYPES * HIDDEN + HIDDEN * HIDDEN + MESSAGE_RELATIONS * HIDDEN * HIDDEN) as u64,
        (NODE_TYPES * HIDDEN
            + HIDDEN * HIDDEN
            + MESSAGE_RELATIONS * HIDDEN * HIDDEN
            + DECODER_RELATIONS * HIDDEN) as u64,
        (NODE_TYPES * HIDDEN
            + HIDDEN * HIDDEN
            + MESSAGE_RELATIONS * HIDDEN * HIDDEN
            + DECODER_RELATIONS * HIDDEN
            + DECODER_RELATIONS) as u64,
    ];
    if manifest.schema_version != NATIVE_RGCN_CALIBRATION_MODEL_SCHEMA
        || manifest.arm_id != NATIVE_RGCN_CALIBRATION_ARM_ID
        || manifest.node_types != NODE_TYPES as u32
        || manifest.message_relations != MESSAGE_RELATIONS as u32
        || manifest.decoder_relations != DECODER_RELATIONS as u32
        || manifest.tensor_offsets != expected
        || manifest.weights_bytes != expected[5] * size_of::<f32>() as u64
    {
        return Err(NativeRgcnCalibrationError::Contract("model manifest"));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn score_mapped_rgcn(
    graph: &RgcnGraphBatch,
    queries: &RgcnQueryBatch,
    node_types: &[f32],
    self_weight: &[f32],
    relation_weights: &[f32],
    decoder: &[f32],
    bias: &[f32],
) -> Result<Vec<f32>, NativeRgcnCalibrationError> {
    if graph.relation_batches.len() != MESSAGE_RELATIONS
        || graph.relation_count != DECODER_RELATIONS as u32
        || node_types.len() != NODE_TYPES * HIDDEN
        || self_weight.len() != HIDDEN * HIDDEN
        || relation_weights.len() != MESSAGE_RELATIONS * HIDDEN * HIDDEN
        || decoder.len() != DECODER_RELATIONS * HIDDEN
        || bias.len() != DECODER_RELATIONS
    {
        return Err(NativeRgcnCalibrationError::Contract("mapped score shapes"));
    }
    let mut initial = vec![[0.0_f32; HIDDEN]; graph.node_types.len()];
    for (node, node_type) in graph.node_types.iter().copied().enumerate() {
        let start = node_type as usize * HIDDEN;
        initial[node].copy_from_slice(&node_types[start..start + HIDDEN]);
    }
    let mut encoded = vec![[0.0_f32; HIDDEN]; initial.len()];
    for (node, source) in initial.iter().enumerate() {
        transform_add(&mut encoded[node], source, self_weight);
    }
    for (relation, batch) in graph.relation_batches.iter().enumerate() {
        let start = relation * HIDDEN * HIDDEN;
        let matrix = &relation_weights[start..start + HIDDEN * HIDDEN];
        for edge in 0..batch.sources.len() {
            transform_add_scaled(
                &mut encoded[batch.targets[edge] as usize],
                &initial[batch.sources[edge] as usize],
                matrix,
                batch.normalizers[edge],
            );
        }
    }
    encoded
        .iter_mut()
        .for_each(|row| row.iter_mut().for_each(|value| *value = value.max(0.0)));
    let mut scores = Vec::with_capacity(queries.labels.len());
    for index in 0..queries.labels.len() {
        let relation = queries.relations[index] as usize;
        let logit = simd_triple(
            &encoded[queries.sources[index] as usize],
            &encoded[queries.targets[index] as usize],
            &decoder[relation * HIDDEN..(relation + 1) * HIDDEN],
        ) + bias[relation];
        scores.push(sigmoid(logit));
    }
    Ok(scores)
}

fn transform_add(target: &mut [f32; HIDDEN], source: &[f32; HIDDEN], matrix: &[f32]) {
    transform_add_scaled(target, source, matrix, 1.0);
}

fn transform_add_scaled(
    target: &mut [f32; HIDDEN],
    source: &[f32; HIDDEN],
    matrix: &[f32],
    scale: f32,
) {
    for (row, output) in target.iter_mut().enumerate() {
        *output += simd_dot(&matrix[row * HIDDEN..(row + 1) * HIDDEN], source) * scale;
    }
}

fn simd_dot(left: &[f32], right: &[f32]) -> f32 {
    let low: [f32; 8] = (load(left, 0) * load(right, 0)).into();
    let high: [f32; 8] = (load(left, 8) * load(right, 8)).into();
    low.into_iter().chain(high).sum()
}

fn simd_triple(left: &[f32], right: &[f32], relation: &[f32]) -> f32 {
    let low: [f32; 8] = (load(left, 0) * load(right, 0) * load(relation, 0)).into();
    let high: [f32; 8] = (load(left, 8) * load(right, 8) * load(relation, 8)).into();
    low.into_iter().chain(high).sum()
}

fn load(values: &[f32], offset: usize) -> f32x8 {
    f32x8::from(<[f32; 8]>::try_from(&values[offset..offset + 8]).expect("SIMD row"))
}

fn sigmoid(value: f32) -> f32 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exp = value.exp();
        exp / (1.0 + exp)
    }
}

fn score_digest(scores: &[f32]) -> CompactString {
    let mut hasher = blake3::Hasher::new();
    for score in scores {
        hasher.update(&score.to_bits().to_le_bytes());
    }
    format_compact!("b3-{}", hasher.finalize().to_hex())
}

fn score_bits(scores: &[f32]) -> Vec<u32> {
    scores.iter().map(|value| value.to_bits()).collect()
}
