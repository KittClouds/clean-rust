use crate::hyper_encoder_examples::PreparedHyperExamples;
use crate::hyper_encoder_memory::{
    train_fused_hyper_encoder16_with_optimizer, FusedHyperTrainingOutcome,
};
use crate::hyper_learning_gate_artifact::{persist_and_reopen_gate_model, GateArtifactRequest};
use crate::hyper_learning_gate_context::GateArmContext;
use crate::hyper_learning_gate_metrics::{
    clip_coefficient, economics_gradient_norm, row_delta, sigmoid, tensor_delta, weights_digest,
};
use crate::hyper_learning_gate_receipt::{open_hyper_learning_gates, seal_learning_gate_receipt};
use crate::{CandleTrainerError, HyperGradientClipPolicy, HyperOptimizerConfig};
use compact_str::{format_compact, CompactString};
use phoenix_graph_research::{
    build_canonical_hyper_relational_task, encode_hyper_encoder, import_wd50k,
    initialize_hyper_encoder_weights, stage_hyper_encoder, ExternalDatasetMapped,
    ExternalFactSplit, HyperEncoderConfig, HyperEncoderMode, HyperEncoderTrainingConfig,
    HyperEncoderWeights, HyperRelationalQueryView, HyperRelationalTaskMapped, LinkPredictionSplit,
    ENTITY_ROLE_OBJECT, HYPER_ENCODER_HIDDEN,
};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

pub const HYPER_LEARNING_GATES_SCHEMA: &str = "phoenix-hyper-learning-gates/v1";
const GATE_SEED: u64 = 0x6761_7465_2d76_0001;
const GATE_EPOCHS: u32 = 512;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GateScoreReceipt {
    pub score_blake3: CompactString,
    pub mean_positive_score: f64,
    pub mean_negative_score: f64,
    pub mean_margin: f64,
    pub correctly_ordered_fraction: f64,
    pub binary_cross_entropy: f64,
    pub pairs: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ParameterDeltaReceipt {
    pub changed_scalars: u64,
    pub unchanged_scalars: u64,
    pub non_finite: u64,
    pub max_absolute_delta: f64,
    pub mean_absolute_delta: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum LearningGateArm {
    Compgcn,
    RoleOnly,
    ValueOnly,
    FullStare,
    QualifierGradientNull,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GateArmReceipt {
    pub arm: LearningGateArm,
    pub initial: GateScoreReceipt,
    pub trained: GateScoreReceipt,
    pub model_id: CompactString,
    pub manifest_id: CompactString,
    pub base_checkpoint_model_id: Option<CompactString>,
    pub qualifier_parameter_source: Option<CompactString>,
    pub train_path_alias_exact: bool,
    pub qualifier_value_delta: ParameterDeltaReceipt,
    pub qualifier_role_delta: ParameterDeltaReceipt,
    pub qualifier_projection_delta: ParameterDeltaReceipt,
    pub pre_clip_gradient_norm: f64,
    pub clip_coefficient: f64,
    pub post_clip_gradient_norm: f64,
    pub optimizer_state_blake3: CompactString,
    pub cold_score_exact: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LearningGateCaseReceipt {
    pub name: CompactString,
    pub source_dataset_id: CompactString,
    pub task_id: CompactString,
    pub symmetric_parameter_bits: bool,
    pub optimizer: HyperOptimizerConfig,
    pub arms: Vec<GateArmReceipt>,
    pub passed: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperLearningGatesReceipt {
    pub schema_version: CompactString,
    pub receipt_id: CompactString,
    pub seed: u64,
    pub epochs: u32,
    pub optimizer_family: CompactString,
    pub single_pair: LearningGateCaseReceipt,
    pub qualifier_value: LearningGateCaseReceipt,
    pub qualifier_role: LearningGateCaseReceipt,
    pub all_passed: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HyperLearningGatePaths {
    pub receipt: PathBuf,
    pub receipt_id: CompactString,
}

pub fn run_hyper_learning_gates(
    root: impl AsRef<Path>,
) -> Result<HyperLearningGatePaths, CandleTrainerError> {
    let root = root.as_ref();
    std::fs::create_dir_all(root)?;
    let single = build_case(
        root,
        "single-pair",
        &["S,R,A,Q,V"],
        &["S,R,A,Q,V", "B,R,S"],
        GateKind::Single,
    )?;
    let value = build_case(
        root,
        "qualifier-value",
        &["S,R,A,QR,V1", "S,R,B,QR,V2"],
        &["S,R,A,QR,V1", "S,R,B,QR,V2"],
        GateKind::Value,
    )?;
    let role = build_case(
        root,
        "qualifier-role",
        &["S,R,A,QR1,V", "S,R,B,QR2,V"],
        &["S,R,A,QR1,V", "S,R,B,QR2,V"],
        GateKind::Role,
    )?;
    let receipt = HyperLearningGatesReceipt {
        schema_version: HYPER_LEARNING_GATES_SCHEMA.into(),
        receipt_id: "pending".into(),
        seed: GATE_SEED,
        epochs: GATE_EPOCHS,
        optimizer_family: "deterministic-pair-sum-no-decay-global-norm-clip-gate".into(),
        all_passed: single.passed && value.passed && role.passed,
        single_pair: single,
        qualifier_value: value,
        qualifier_role: role,
    };
    let (receipt, path) = seal_learning_gate_receipt(receipt, root)?;
    let reopened = open_hyper_learning_gates(&path)?;
    if reopened.receipt_id != receipt.receipt_id {
        return Err(CandleTrainerError::Contract("learning gate receipt replay"));
    }
    Ok(HyperLearningGatePaths {
        receipt: path,
        receipt_id: receipt.receipt_id,
    })
}

#[derive(Clone, Copy)]
enum GateKind {
    Single,
    Value,
    Role,
}

fn build_case(
    root: &Path,
    name: &str,
    train: &[&str],
    evaluation: &[&str],
    kind: GateKind,
) -> Result<LearningGateCaseReceipt, CandleTrainerError> {
    let case_root = root.join(name);
    write_statements(&case_root, train, evaluation)?;
    let source_paths = import_wd50k(&case_root, case_root.join("source"))?;
    let source = ExternalDatasetMapped::open(&source_paths.manifest)?;
    let task_paths = build_canonical_hyper_relational_task(&source, case_root.join("task"))?;
    let task = HyperRelationalTaskMapped::open(&task_paths.manifest, &source)?;
    let staged = stage_hyper_encoder(&source, &task)?;
    let facts = source.facts()?;
    let train_facts = facts
        .iter()
        .copied()
        .filter(|fact| fact.split() == ExternalFactSplit::Train as u8)
        .collect::<Vec<_>>();
    let examples = gate_examples(&train_facts, staged.candidate_universe, kind)?;
    let mut initial = initialize_hyper_encoder_weights(&staged, GATE_SEED);
    initialize_gate_weights(&mut initial);
    let (value_slots, role_slots) = symmetric_slots(&source, &train_facts, kind)?;
    impose_symmetry(&mut initial, &value_slots, &role_slots);
    neutralize_composition(&mut initial, &value_slots, &role_slots, kind);
    let symmetric_parameter_bits = slots_equal(&initial, &value_slots, &role_slots);
    let modes: &[HyperEncoderMode] = match kind {
        GateKind::Single => &[HyperEncoderMode::CompgcnTriple],
        GateKind::Value => &[
            HyperEncoderMode::CompgcnTriple,
            HyperEncoderMode::RoleOnly,
            HyperEncoderMode::ValueOnly,
            HyperEncoderMode::StareQualifiers,
        ],
        GateKind::Role => &[
            HyperEncoderMode::CompgcnTriple,
            HyperEncoderMode::ValueOnly,
            HyperEncoderMode::StareQualifiers,
        ],
    };
    let optimizer = gate_optimizer(examples.len());
    let config = gate_training_config();
    let mut arms = Vec::with_capacity(modes.len() + usize::from(!matches!(kind, GateKind::Single)));
    let mut control_outcome = None;
    let mut control_model_id = None;
    let initial_weights_blake3 = weights_digest(&initial);
    let model_root = case_root.join("models");
    let arm_context = GateArmContext {
        artifact_root: &model_root,
        source: &source,
        task: &task,
        staged: &staged,
        examples: &examples,
        initial: &initial,
        initial_weights_blake3: initial_weights_blake3.as_str(),
        value_slots: &value_slots,
        role_slots: &role_slots,
        optimizer,
    };
    for &mode in modes {
        let outcome = train_fused_hyper_encoder16_with_optimizer(
            &source,
            &staged,
            &examples,
            mode,
            config,
            optimizer,
            initial.clone(),
        )?;
        let arm = arm_receipt(&arm_context, mode, &outcome)?;
        if mode == HyperEncoderMode::CompgcnTriple {
            control_model_id = Some(arm.model_id.clone());
            control_outcome = Some(outcome);
        }
        arms.push(arm);
    }
    if !matches!(kind, GateKind::Single) {
        let control = control_outcome
            .as_ref()
            .ok_or(CandleTrainerError::Contract("gate control"))?;
        arms.push(null_view_receipt(
            &arm_context,
            control,
            control_model_id.ok_or(CandleTrainerError::Contract("gate control model"))?,
        )?);
    }
    let passed = gate_passed(kind, &arms, symmetric_parameter_bits);
    Ok(LearningGateCaseReceipt {
        name: name.into(),
        source_dataset_id: staged.source_dataset_id,
        task_id: staged.task_id,
        symmetric_parameter_bits,
        optimizer,
        arms,
        passed,
    })
}

fn gate_training_config() -> HyperEncoderTrainingConfig {
    HyperEncoderTrainingConfig {
        epochs: GATE_EPOCHS,
        learning_rate: 0.08,
        l2: 0.0,
        negatives_per_positive: 1,
    }
}

fn gate_optimizer(examples: usize) -> HyperOptimizerConfig {
    let mut optimizer = HyperOptimizerConfig::bounded_sum_no_decay(0.08, 2.min(examples) as u32);
    optimizer.global_loss_scale = 256.0;
    optimizer.loss_scale_semantics = crate::LossScaleSemantics::ClipScaledGradient;
    optimizer.gradient_clip_policy = HyperGradientClipPolicy::GlobalNorm;
    optimizer.gradient_clip_norm = 1.0;
    optimizer
}

fn initialize_gate_weights(weights: &mut HyperEncoderWeights) {
    weights.node_embeddings.fill(0.125);
    weights.relation_embeddings.fill(0.125);
    identity_matrices(&mut weights.direction_weights);
    identity_matrices(&mut weights.relation_projection);
    identity_matrices(&mut weights.qualifier_projection);
    weights.decoder_bias.fill(0.0);
}

fn identity_matrices(tensor: &mut [f32]) {
    tensor.fill(0.0);
    for matrix in tensor.chunks_exact_mut(HYPER_ENCODER_HIDDEN * HYPER_ENCODER_HIDDEN) {
        for feature in 0..HYPER_ENCODER_HIDDEN {
            matrix[feature * HYPER_ENCODER_HIDDEN + feature] = 1.0;
        }
    }
}

fn write_statements(
    root: &Path,
    train: &[&str],
    evaluation: &[&str],
) -> Result<(), CandleTrainerError> {
    let statements = root.join("statements");
    std::fs::create_dir_all(&statements)?;
    let lines = |values: &[&str]| format!("{}\n", values.join("\n"));
    std::fs::write(statements.join("train.txt"), lines(train))?;
    std::fs::write(statements.join("valid.txt"), lines(evaluation))?;
    std::fs::write(statements.join("test.txt"), lines(evaluation))?;
    Ok(())
}

fn gate_examples(
    facts: &[phoenix_graph_research::ExternalFactRecord],
    nodes: u32,
    kind: GateKind,
) -> Result<PreparedHyperExamples, CandleTrainerError> {
    if facts.is_empty() {
        return Err(CandleTrainerError::Contract("gate train facts"));
    }
    let mut output = PreparedHyperExamples {
        sources: Vec::new(),
        targets: Vec::new(),
        relations: Vec::new(),
        qualifier_offsets: Vec::new(),
        qualifier_counts: Vec::new(),
        labels: Vec::new(),
        schedule_blake3: String::new(),
    };
    match kind {
        GateKind::Single => {
            let fact = facts[0];
            let negative = (0..nodes)
                .find(|node| *node != fact.subject() && *node != fact.object())
                .ok_or(CandleTrainerError::Contract("single gate negative"))?;
            push_pair(&mut output, fact, fact.object(), negative);
        }
        GateKind::Value | GateKind::Role => {
            if facts.len() != 2 || facts[0].subject() != facts[1].subject() {
                return Err(CandleTrainerError::Contract("symmetric gate facts"));
            }
            push_pair(&mut output, facts[0], facts[0].object(), facts[1].object());
            push_pair(&mut output, facts[1], facts[1].object(), facts[0].object());
        }
    }
    output.schedule_blake3 = example_digest(&output);
    Ok(output)
}

fn push_pair(
    output: &mut PreparedHyperExamples,
    fact: phoenix_graph_research::ExternalFactRecord,
    positive: u32,
    negative: u32,
) {
    for (target, label) in [(positive, true), (negative, false)] {
        output.sources.push(fact.subject());
        output.targets.push(target);
        output.relations.push(fact.predicate());
        output.qualifier_offsets.push(fact.qualifier_offset());
        output.qualifier_counts.push(fact.qualifier_count());
        output.labels.push(label);
    }
}

fn example_digest(examples: &PreparedHyperExamples) -> String {
    let mut hasher = blake3::Hasher::new();
    for index in 0..examples.len() {
        for value in [
            examples.sources[index],
            examples.targets[index],
            examples.relations[index],
            examples.qualifier_offsets[index],
            examples.qualifier_counts[index],
        ] {
            hasher.update(&value.to_le_bytes());
        }
        hasher.update(&[examples.labels[index] as u8]);
    }
    format!("b3-{}", hasher.finalize().to_hex())
}

fn symmetric_slots(
    source: &ExternalDatasetMapped,
    facts: &[phoenix_graph_research::ExternalFactRecord],
    kind: GateKind,
) -> Result<(Vec<u32>, Vec<u32>), CandleTrainerError> {
    let qualifiers = source.qualifiers()?;
    let mut values = Vec::new();
    let mut roles = Vec::new();
    if !matches!(kind, GateKind::Single) {
        for fact in facts {
            let qualifier = qualifiers[fact.qualifier_offset() as usize];
            values.push(qualifier.object());
            roles.push(qualifier.predicate());
        }
        values.sort_unstable();
        values.dedup();
        roles.sort_unstable();
        roles.dedup();
    }
    Ok((values, roles))
}

fn impose_symmetry(weights: &mut HyperEncoderWeights, values: &[u32], roles: &[u32]) {
    copy_rows(&mut weights.node_embeddings, values);
    copy_rows(&mut weights.relation_embeddings, roles);
}

fn neutralize_composition(
    weights: &mut HyperEncoderWeights,
    values: &[u32],
    roles: &[u32],
    kind: GateKind,
) {
    let rows = match kind {
        GateKind::Value => (&mut weights.relation_embeddings, roles),
        GateKind::Role => (&mut weights.node_embeddings, values),
        GateKind::Single => return,
    };
    for &row in rows.1 {
        rows.0[row as usize * HYPER_ENCODER_HIDDEN..(row as usize + 1) * HYPER_ENCODER_HIDDEN]
            .fill(1.0);
    }
}

fn copy_rows(tensor: &mut [f32], indices: &[u32]) {
    if let Some((&first, rest)) = indices.split_first() {
        let row = tensor
            [first as usize * HYPER_ENCODER_HIDDEN..(first as usize + 1) * HYPER_ENCODER_HIDDEN]
            .to_vec();
        for &index in rest {
            tensor[index as usize * HYPER_ENCODER_HIDDEN
                ..(index as usize + 1) * HYPER_ENCODER_HIDDEN]
                .copy_from_slice(&row);
        }
    }
}

fn slots_equal(weights: &HyperEncoderWeights, values: &[u32], roles: &[u32]) -> bool {
    rows_equal(&weights.node_embeddings, values) && rows_equal(&weights.relation_embeddings, roles)
}

fn rows_equal(tensor: &[f32], indices: &[u32]) -> bool {
    indices.first().is_none_or(|first| {
        let first = &tensor
            [*first as usize * HYPER_ENCODER_HIDDEN..(*first as usize + 1) * HYPER_ENCODER_HIDDEN];
        indices.iter().all(|index| {
            first
                == &tensor[*index as usize * HYPER_ENCODER_HIDDEN
                    ..(*index as usize + 1) * HYPER_ENCODER_HIDDEN]
        })
    })
}

fn arm_receipt(
    context: &GateArmContext<'_>,
    mode: HyperEncoderMode,
    outcome: &FusedHyperTrainingOutcome,
) -> Result<GateArmReceipt, CandleTrainerError> {
    let GateArmContext {
        artifact_root,
        source,
        task,
        staged,
        examples,
        initial: initial_weights,
        initial_weights_blake3,
        value_slots,
        role_slots,
        optimizer,
    } = context;
    let initial = score_examples(source, staged, examples, initial_weights, mode)?;
    let trained = score_examples(source, staged, examples, &outcome.weights, mode)?;
    let gradient_norm = economics_gradient_norm(&outcome.final_epoch);
    let clip = clip_coefficient(gradient_norm, *optimizer);
    let restarted = persist_and_reopen_gate_model(GateArtifactRequest {
        root: &artifact_root.join(format!("{mode:?}")),
        source,
        task,
        staged,
        examples,
        initial_weights_blake3,
        seed: GATE_SEED,
        mode,
        training_config: gate_training_config(),
        optimizer: *optimizer,
        outcome,
    })?;
    let cold_score = score_examples(source, staged, examples, &restarted.weights, mode)?;
    Ok(GateArmReceipt {
        arm: arm_for_mode(mode)?,
        initial,
        trained: trained.clone(),
        model_id: restarted.model_id,
        manifest_id: restarted.manifest_id,
        base_checkpoint_model_id: None,
        qualifier_parameter_source: None,
        train_path_alias_exact: false,
        qualifier_value_delta: row_delta(
            &initial_weights.node_embeddings,
            &outcome.weights.node_embeddings,
            value_slots,
        ),
        qualifier_role_delta: row_delta(
            &initial_weights.relation_embeddings,
            &outcome.weights.relation_embeddings,
            role_slots,
        ),
        qualifier_projection_delta: tensor_delta(
            &initial_weights.qualifier_projection,
            &outcome.weights.qualifier_projection,
        ),
        pre_clip_gradient_norm: gradient_norm,
        clip_coefficient: clip,
        post_clip_gradient_norm: gradient_norm * clip,
        optimizer_state_blake3: outcome.optimizer_state_blake3.as_str().into(),
        cold_score_exact: cold_score == trained,
    })
}

fn arm_for_mode(mode: HyperEncoderMode) -> Result<LearningGateArm, CandleTrainerError> {
    match mode {
        HyperEncoderMode::CompgcnTriple => Ok(LearningGateArm::Compgcn),
        HyperEncoderMode::RoleOnly => Ok(LearningGateArm::RoleOnly),
        HyperEncoderMode::ValueOnly => Ok(LearningGateArm::ValueOnly),
        HyperEncoderMode::StareQualifiers => Ok(LearningGateArm::FullStare),
        HyperEncoderMode::Detached
        | HyperEncoderMode::Shuffled
        | HyperEncoderMode::QueryOnly
        | HyperEncoderMode::MessageOnly => Err(CandleTrainerError::Contract(
            "matrix-only arm is not a learning gate control",
        )),
    }
}

fn null_view_receipt(
    context: &GateArmContext<'_>,
    control: &FusedHyperTrainingOutcome,
    base_checkpoint_model_id: CompactString,
) -> Result<GateArmReceipt, CandleTrainerError> {
    let GateArmContext {
        artifact_root,
        source,
        task,
        staged,
        examples,
        initial,
        initial_weights_blake3,
        value_slots: values,
        role_slots: roles,
        optimizer,
    } = context;
    let initial_score = score_examples(
        source,
        staged,
        examples,
        initial,
        HyperEncoderMode::StareQualifiers,
    )?;
    let trained = score_examples(
        source,
        staged,
        examples,
        &control.weights,
        HyperEncoderMode::StareQualifiers,
    )?;
    let restarted = persist_and_reopen_gate_model(GateArtifactRequest {
        root: &artifact_root.join("qualifier-gradient-null"),
        source,
        task,
        staged,
        examples,
        initial_weights_blake3,
        seed: GATE_SEED,
        mode: HyperEncoderMode::StareQualifiers,
        training_config: gate_training_config(),
        optimizer: *optimizer,
        outcome: control,
    })?;
    Ok(GateArmReceipt {
        arm: LearningGateArm::QualifierGradientNull,
        initial: initial_score,
        trained: trained.clone(),
        model_id: restarted.model_id,
        manifest_id: restarted.manifest_id,
        base_checkpoint_model_id: Some(base_checkpoint_model_id),
        qualifier_parameter_source: Some((*initial_weights_blake3).into()),
        train_path_alias_exact: true,
        qualifier_value_delta: row_delta(
            &initial.node_embeddings,
            &control.weights.node_embeddings,
            values,
        ),
        qualifier_role_delta: row_delta(
            &initial.relation_embeddings,
            &control.weights.relation_embeddings,
            roles,
        ),
        qualifier_projection_delta: tensor_delta(
            &initial.qualifier_projection,
            &control.weights.qualifier_projection,
        ),
        pre_clip_gradient_norm: 0.0,
        clip_coefficient: 1.0,
        post_clip_gradient_norm: 0.0,
        optimizer_state_blake3: control.optimizer_state_blake3.as_str().into(),
        cold_score_exact: score_examples(
            source,
            staged,
            examples,
            &restarted.weights,
            HyperEncoderMode::StareQualifiers,
        )? == trained,
    })
}

fn score_examples(
    source: &ExternalDatasetMapped,
    staged: &phoenix_graph_research::HyperEncoderStagedInput,
    examples: &PreparedHyperExamples,
    weights: &HyperEncoderWeights,
    mode: HyperEncoderMode,
) -> Result<GateScoreReceipt, CandleTrainerError> {
    let encoded = encode_hyper_encoder(
        source,
        staged,
        HyperEncoderConfig::with_mode(GATE_SEED, mode),
        weights,
    )?;
    let candidates = (0..staged.candidate_universe).collect::<Vec<_>>();
    let queries = (0..examples.len())
        .map(|index| HyperRelationalQueryView {
            source: examples.sources[index],
            relation: examples.relations[index],
            qualifier_offset: examples.qualifier_offsets[index],
            qualifier_count: examples.qualifier_counts[index],
            split: LinkPredictionSplit::Validation,
            inverse: false,
            target_role: ENTITY_ROLE_OBJECT,
        })
        .collect::<Vec<_>>();
    let mut all_scores = vec![0.0; queries.len() * candidates.len()];
    encoded
        .score_candidate_batch(source, &queries, &candidates, &mut all_scores)
        .map_err(|_| CandleTrainerError::Contract("gate scoring"))?;
    let scores = examples
        .targets
        .iter()
        .enumerate()
        .map(|(index, target)| all_scores[index * candidates.len() + *target as usize])
        .collect::<Vec<_>>();
    score_receipt(&scores, &examples.labels)
}

fn score_receipt(scores: &[f32], labels: &[bool]) -> Result<GateScoreReceipt, CandleTrainerError> {
    let mut positive = 0.0_f64;
    let mut negative = 0.0_f64;
    let mut positives = 0_u64;
    let mut negatives = 0_u64;
    let mut margin = 0.0_f64;
    let mut ordered = 0_u64;
    let mut pairs = 0_u64;
    let mut last_positive = None;
    let mut loss = 0.0_f64;
    let mut hasher = blake3::Hasher::new();
    for (&score, &label) in scores.iter().zip(labels) {
        hasher.update(&score.to_bits().to_le_bytes());
        let probability = f64::from(sigmoid(score)).clamp(f64::EPSILON, 1.0 - f64::EPSILON);
        loss -= if label {
            probability.ln()
        } else {
            (1.0 - probability).ln()
        };
        if label {
            positive += f64::from(score);
            positives += 1;
            last_positive = Some(score);
        } else {
            negative += f64::from(score);
            negatives += 1;
            let positive_score =
                last_positive.ok_or(CandleTrainerError::Contract("gate pair order"))?;
            margin += f64::from(positive_score - score);
            ordered += u64::from(positive_score > score);
            pairs += 1;
        }
    }
    Ok(GateScoreReceipt {
        score_blake3: format_compact!("b3-{}", hasher.finalize().to_hex()),
        mean_positive_score: positive / positives as f64,
        mean_negative_score: negative / negatives as f64,
        mean_margin: margin / pairs as f64,
        correctly_ordered_fraction: ordered as f64 / pairs as f64,
        binary_cross_entropy: loss / scores.len() as f64,
        pairs,
    })
}

fn gate_passed(kind: GateKind, arms: &[GateArmReceipt], symmetric: bool) -> bool {
    let learned = |arm: &GateArmReceipt| {
        arm.trained.correctly_ordered_fraction == 1.0
            && arm.trained.mean_margin > 0.5
            && arm.trained.binary_cross_entropy < arm.initial.binary_cross_entropy * 0.51
            && arm.cold_score_exact
    };
    if !symmetric || arms.iter().any(|arm| !arm.cold_score_exact) {
        return false;
    }
    match kind {
        GateKind::Single => learned(&arms[0]),
        GateKind::Value => {
            !learned(&arms[0])
                && !learned(&arms[1])
                && learned(&arms[2])
                && learned(&arms[3])
                && !learned(&arms[4])
                && null_blocks_frozen(&arms[4])
        }
        GateKind::Role => {
            !learned(&arms[0])
                && !learned(&arms[1])
                && learned(&arms[2])
                && !learned(&arms[3])
                && null_blocks_frozen(&arms[3])
        }
    }
}

fn null_blocks_frozen(arm: &GateArmReceipt) -> bool {
    arm.qualifier_value_delta.changed_scalars == 0
        && arm.qualifier_role_delta.changed_scalars == 0
        && arm.qualifier_projection_delta.changed_scalars == 0
}
