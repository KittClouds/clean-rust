use crate::{
    certify_evaluation_protocol, evaluate_binary_scores, BaselineFamily, BaselineLadderReport,
    BaselineSeedRun, BinaryMetrics, EvaluationPolicy, FamilyValidationSummary,
    FrozenGraphResearchSnapshot, FrozenTensorSnapshot, ResearchEvaluationError,
    ResearchProposalLabel, ResearchSplit, BASELINE_LADDER_SCHEMA, PROPOSAL_FEATURE_DIM,
};
use compact_str::{format_compact, CompactString};
use serde::Serialize;
use wide::f32x8;

#[derive(Clone, Copy)]
struct Example {
    features: [f32; PROPOSAL_FEATURE_DIM],
    label: bool,
}

#[derive(Clone)]
enum TrainedModel {
    Prior(f32),
    Ftrl(FtrlModel),
    Mlp(Box<MlpModel>),
}

impl TrainedModel {
    fn predict(&self, features: &[f32; PROPOSAL_FEATURE_DIM]) -> f32 {
        match self {
            Self::Prior(probability) => *probability,
            Self::Ftrl(model) => sigmoid(simd_dot(&model.weights, features) + model.bias),
            Self::Mlp(model) => model.predict(features),
        }
    }
}

#[derive(Clone)]
struct FtrlModel {
    weights: [f32; PROPOSAL_FEATURE_DIM],
    bias: f32,
}

#[derive(Clone)]
struct MlpModel {
    hidden_weights: [[f32; PROPOSAL_FEATURE_DIM]; PROPOSAL_FEATURE_DIM],
    hidden_bias: [f32; PROPOSAL_FEATURE_DIM],
    output_weights: [f32; PROPOSAL_FEATURE_DIM],
    output_bias: f32,
}

impl MlpModel {
    fn predict(&self, features: &[f32; PROPOSAL_FEATURE_DIM]) -> f32 {
        let mut hidden = [0.0_f32; PROPOSAL_FEATURE_DIM];
        for (index, value) in hidden.iter_mut().enumerate() {
            *value = (simd_dot(&self.hidden_weights[index], features) + self.hidden_bias[index])
                .max(0.0);
        }
        sigmoid(simd_dot(&self.output_weights, &hidden) + self.output_bias)
    }
}

pub fn run_baseline_ladder(
    source: &FrozenGraphResearchSnapshot,
    tensors: &FrozenTensorSnapshot,
    policy: EvaluationPolicy,
) -> Result<BaselineLadderReport, ResearchEvaluationError> {
    let protocol = certify_evaluation_protocol(source, tensors, policy)?;
    run_baseline_ladder_for_protocol(tensors, &protocol)
}

pub fn run_baseline_ladder_for_protocol(
    tensors: &FrozenTensorSnapshot,
    protocol: &crate::ResearchEvaluationProtocol,
) -> Result<BaselineLadderReport, ResearchEvaluationError> {
    if protocol.tensor_id != tensors.tensor_id
        || protocol.source_dataset_id != tensors.source_dataset_id
    {
        return Err(ResearchEvaluationError::SourceIdentityMismatch);
    }
    let examples = collect_examples(tensors, &protocol.policy.feature_schema_id)?;
    validate_splits(&examples)?;
    let train = examples_for_split(&examples, ResearchSplit::Train);
    let validation = examples_for_split(&examples, ResearchSplit::Validation);
    let test = examples_for_split(&examples, ResearchSplit::Test);
    let families = [
        BaselineFamily::PriorHeuristic,
        BaselineFamily::FtrlLogistic,
        BaselineFamily::Mlp16,
    ];
    let mut runs = Vec::with_capacity(families.len() * protocol.seed_certificate.seeds.len());
    let mut trained = Vec::with_capacity(runs.capacity());
    for family in families {
        for &seed in &protocol.seed_certificate.seeds {
            let model = train_model(family, &train, seed, &protocol.policy);
            let train_metrics = evaluate_model(&model, &train, protocol.policy.calibration_bins)?;
            let validation_metrics =
                evaluate_model(&model, &validation, protocol.policy.calibration_bins)?;
            runs.push(BaselineSeedRun {
                family,
                seed,
                train: train_metrics,
                validation: validation_metrics,
                held_out_test: None,
            });
            trained.push(model);
        }
    }
    let validation_summaries = summarize_validation(&runs, protocol.policy.repeats);
    let selected_family = select_family(&validation_summaries);
    for (index, run) in runs.iter_mut().enumerate() {
        if run.family == selected_family {
            run.held_out_test = Some(evaluate_model(
                &trained[index],
                &test,
                protocol.policy.calibration_bins,
            )?);
        }
    }
    let mut report = BaselineLadderReport {
        schema_version: BASELINE_LADDER_SCHEMA.into(),
        report_id: "pending".into(),
        protocol_id: protocol.protocol_id.clone(),
        selected_family,
        selection_rule: "highest mean validation average precision; lowest mean validation brier tie-break; test unlocked only for selected family".into(),
        validation_summaries,
        runs,
    };
    report.report_id = content_id(&report)?;
    Ok(report)
}

fn collect_examples(
    tensors: &FrozenTensorSnapshot,
    selected_schema: &str,
) -> Result<Vec<(ResearchSplit, Example)>, ResearchEvaluationError> {
    let schema = tensors
        .feature_schema_vocabulary
        .iter()
        .position(|value| value == selected_schema)
        .ok_or_else(|| ResearchEvaluationError::FeatureSchema(selected_schema.to_owned()))?
        as u32;
    let mut examples = Vec::new();
    for index in 0..tensors.proposal_labels.len() {
        if tensors.proposal_feature_schema_ids[index] != schema
            || !tensors.proposal_label_observed[index]
        {
            continue;
        }
        let start = index * PROPOSAL_FEATURE_DIM;
        let mut features = [0.0_f32; PROPOSAL_FEATURE_DIM];
        for (slot, &value) in features
            .iter_mut()
            .zip(&tensors.proposal_features[start..start + PROPOSAL_FEATURE_DIM])
        {
            *slot = f32::from(value) / 1000.0;
        }
        examples.push((
            tensors.proposal_splits[index],
            Example {
                features,
                label: tensors.proposal_labels[index] == ResearchProposalLabel::Active,
            },
        ));
    }
    Ok(examples)
}

fn validate_splits(examples: &[(ResearchSplit, Example)]) -> Result<(), ResearchEvaluationError> {
    for split in [
        ResearchSplit::Train,
        ResearchSplit::Validation,
        ResearchSplit::Test,
    ] {
        let mut positive = false;
        let mut negative = false;
        for (_, example) in examples.iter().filter(|(candidate, _)| *candidate == split) {
            positive |= example.label;
            negative |= !example.label;
        }
        if !positive || !negative {
            return Err(ResearchEvaluationError::InsufficientSplit(split));
        }
    }
    Ok(())
}

fn examples_for_split(examples: &[(ResearchSplit, Example)], split: ResearchSplit) -> Vec<Example> {
    examples
        .iter()
        .filter_map(|(candidate, example)| (*candidate == split).then_some(*example))
        .collect()
}

fn train_model(
    family: BaselineFamily,
    train: &[Example],
    seed: u64,
    policy: &EvaluationPolicy,
) -> TrainedModel {
    match family {
        BaselineFamily::PriorHeuristic => {
            let positive = train.iter().filter(|row| row.label).count() as f32;
            TrainedModel::Prior((positive + 1.0) / (train.len() as f32 + 2.0))
        }
        BaselineFamily::FtrlLogistic => TrainedModel::Ftrl(train_ftrl(train, seed, policy.ftrl)),
        BaselineFamily::Mlp16 => TrainedModel::Mlp(Box::new(train_mlp(train, seed, policy.mlp))),
    }
}

fn train_ftrl(train: &[Example], seed: u64, config: crate::FtrlConfig) -> FtrlModel {
    let mut z = [0.0_f32; PROPOSAL_FEATURE_DIM];
    let mut n = [0.0_f32; PROPOSAL_FEATURE_DIM];
    let mut bias_z = 0.0_f32;
    let mut bias_n = 0.0_f32;
    let mut order = (0..train.len()).collect::<Vec<_>>();
    let mut random = SplitMix64(seed);
    for _ in 0..config.epochs {
        shuffle(&mut order, &mut random);
        for &row in &order {
            let weights = ftrl_weights(&z, &n, config);
            let bias = ftrl_weight(bias_z, bias_n, config);
            let example = train[row];
            let error =
                sigmoid(simd_dot(&weights, &example.features) + bias) - f32::from(example.label);
            for index in 0..PROPOSAL_FEATURE_DIM {
                let gradient = error * example.features[index];
                let sigma =
                    ((n[index] + gradient * gradient).sqrt() - n[index].sqrt()) / config.alpha;
                z[index] += gradient - sigma * weights[index];
                n[index] += gradient * gradient;
            }
            let sigma = ((bias_n + error * error).sqrt() - bias_n.sqrt()) / config.alpha;
            bias_z += error - sigma * bias;
            bias_n += error * error;
        }
    }
    FtrlModel {
        weights: ftrl_weights(&z, &n, config),
        bias: ftrl_weight(bias_z, bias_n, config),
    }
}

fn train_mlp(train: &[Example], seed: u64, config: crate::MlpConfig) -> MlpModel {
    let mut random = SplitMix64(seed);
    let mut model = MlpModel {
        hidden_weights: [[0.0; PROPOSAL_FEATURE_DIM]; PROPOSAL_FEATURE_DIM],
        hidden_bias: [0.0; PROPOSAL_FEATURE_DIM],
        output_weights: [0.0; PROPOSAL_FEATURE_DIM],
        output_bias: 0.0,
    };
    for row in &mut model.hidden_weights {
        for value in row {
            *value = random.signed_unit() * 0.08;
        }
    }
    for value in &mut model.output_weights {
        *value = random.signed_unit() * 0.08;
    }
    let mut order = (0..train.len()).collect::<Vec<_>>();
    for _ in 0..config.epochs {
        shuffle(&mut order, &mut random);
        for &row in &order {
            update_mlp(&mut model, train[row], config);
        }
    }
    model
}

fn update_mlp(model: &mut MlpModel, example: Example, config: crate::MlpConfig) {
    let mut hidden = [0.0_f32; PROPOSAL_FEATURE_DIM];
    for (index, value) in hidden.iter_mut().enumerate() {
        *value = (simd_dot(&model.hidden_weights[index], &example.features)
            + model.hidden_bias[index])
            .max(0.0);
    }
    let probability = sigmoid(simd_dot(&model.output_weights, &hidden) + model.output_bias);
    let error = probability - f32::from(example.label);
    let old_output = model.output_weights;
    for (weight, &activation) in model.output_weights.iter_mut().zip(&hidden) {
        *weight -= config.learning_rate * (error * activation + config.l2 * *weight);
    }
    model.output_bias -= config.learning_rate * error;
    for (hidden_index, &activation) in hidden.iter().enumerate() {
        if activation == 0.0 {
            continue;
        }
        let hidden_error = error * old_output[hidden_index];
        for (weight, &feature) in model.hidden_weights[hidden_index]
            .iter_mut()
            .zip(&example.features)
        {
            *weight -= config.learning_rate * (hidden_error * feature + config.l2 * *weight);
        }
        model.hidden_bias[hidden_index] -= config.learning_rate * hidden_error;
    }
}

fn evaluate_model(
    model: &TrainedModel,
    examples: &[Example],
    calibration_bins: u8,
) -> Result<BinaryMetrics, ResearchEvaluationError> {
    let labels = examples.iter().map(|row| row.label).collect::<Vec<_>>();
    let scores = examples
        .iter()
        .map(|row| model.predict(&row.features))
        .collect::<Vec<_>>();
    evaluate_binary_scores(&labels, &scores, calibration_bins)
}

fn summarize_validation(runs: &[BaselineSeedRun], repeats: u16) -> Vec<FamilyValidationSummary> {
    [
        BaselineFamily::PriorHeuristic,
        BaselineFamily::FtrlLogistic,
        BaselineFamily::Mlp16,
    ]
    .into_iter()
    .map(|family| {
        let rows = runs
            .iter()
            .filter(|run| run.family == family)
            .collect::<Vec<_>>();
        let count = rows.len() as f64;
        FamilyValidationSummary {
            family,
            mean_average_precision: rows
                .iter()
                .map(|run| run.validation.average_precision.unwrap_or(0.0))
                .sum::<f64>()
                / count,
            mean_brier_score: rows
                .iter()
                .map(|run| run.validation.brier_score)
                .sum::<f64>()
                / count,
            repeats,
        }
    })
    .collect()
}

fn select_family(summaries: &[FamilyValidationSummary]) -> BaselineFamily {
    summaries
        .iter()
        .max_by(|left, right| {
            left.mean_average_precision
                .total_cmp(&right.mean_average_precision)
                .then_with(|| right.mean_brier_score.total_cmp(&left.mean_brier_score))
        })
        .expect("three baseline families")
        .family
}

fn ftrl_weights(
    z: &[f32; PROPOSAL_FEATURE_DIM],
    n: &[f32; PROPOSAL_FEATURE_DIM],
    config: crate::FtrlConfig,
) -> [f32; PROPOSAL_FEATURE_DIM] {
    let mut weights = [0.0; PROPOSAL_FEATURE_DIM];
    for index in 0..PROPOSAL_FEATURE_DIM {
        weights[index] = ftrl_weight(z[index], n[index], config);
    }
    weights
}

fn ftrl_weight(z: f32, n: f32, config: crate::FtrlConfig) -> f32 {
    if z.abs() <= config.l1 {
        0.0
    } else {
        (z.signum() * config.l1 - z) / ((config.beta + n.sqrt()) / config.alpha + config.l2)
    }
}

fn simd_dot(left: &[f32; PROPOSAL_FEATURE_DIM], right: &[f32; PROPOSAL_FEATURE_DIM]) -> f32 {
    let left_low: [f32; 8] = left[..8].try_into().expect("eight values");
    let right_low: [f32; 8] = right[..8].try_into().expect("eight values");
    let left_high: [f32; 8] = left[8..].try_into().expect("eight values");
    let right_high: [f32; 8] = right[8..].try_into().expect("eight values");
    let low: [f32; 8] = (f32x8::from(left_low) * f32x8::from(right_low)).into();
    let high: [f32; 8] = (f32x8::from(left_high) * f32x8::from(right_high)).into();
    low.into_iter().chain(high).sum()
}

fn sigmoid(value: f32) -> f32 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exp = value.exp();
        exp / (1.0 + exp)
    }
}

fn shuffle(values: &mut [usize], random: &mut SplitMix64) {
    for index in (1..values.len()).rev() {
        values.swap(index, random.next_u64() as usize % (index + 1));
    }
}

struct SplitMix64(u64);

impl SplitMix64 {
    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }

    fn signed_unit(&mut self) -> f32 {
        let fraction = (self.next_u64() >> 40) as f32 / (1_u32 << 24) as f32;
        fraction * 2.0 - 1.0
    }
}

fn content_id(value: &impl Serialize) -> Result<CompactString, ResearchEvaluationError> {
    let bytes = serde_json::to_vec(value)?;
    Ok(format_compact!("b3-{}", blake3::hash(&bytes).to_hex()))
}
