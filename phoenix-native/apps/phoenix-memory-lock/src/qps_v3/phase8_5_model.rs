use hashbrown::HashMap;
use phoenix_lexical_qps::{
    leakage_split_identity_v3, rank_evidence_schema_identity_v3, JudgmentReasonV3, LeakageSplitV3,
    LinearRankerV3, PairwiseJudgmentV3, PrimarySplitV3, RankEvidenceV3, RelevanceLedgerV3,
    RANK_EVIDENCE_V3_FEATURE_COUNT,
};
use serde::{Deserialize, Serialize};

const DIAGNOSTIC_VERSION: u16 = 1;
const SHAPE_BASIS_COUNT: usize = 3;
const QUERY_ONLY_FEATURES: [usize; SHAPE_BASIS_COUNT] = [
    RankEvidenceV3::QUERY_GROUP_COUNT,
    RankEvidenceV3::SINGLE_GROUP_FLAG,
    RankEvidenceV3::LONG_QUERY_FLAG,
];

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub(super) struct ShapeTrainingConfig {
    pub epochs: u16,
    pub learning_rate: f32,
    pub l2_penalty: f32,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, Deserialize)]
pub(super) struct DevelopmentEvaluation {
    pub judgments: usize,
    pub correctly_ordered: usize,
    pub accuracy: f32,
    pub represented_classes: usize,
    pub macro_class_accuracy: f32,
    pub minimum_class_accuracy: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub(super) struct ShapeConditionedRanker {
    pub version: u16,
    pub feature_schema_identity: [u8; 32],
    pub base_weights: [f32; RANK_EVIDENCE_V3_FEATURE_COUNT],
    pub shape_interactions: [[f32; RANK_EVIDENCE_V3_FEATURE_COUNT]; SHAPE_BASIS_COUNT],
}

impl ShapeConditionedRanker {
    pub(super) fn from_linear(model: &LinearRankerV3) -> Result<Self, &'static str> {
        if !model.is_valid() {
            return Err("shape diagnostic requires a valid Phase 7 model");
        }
        let mut base_weights = model.weights;
        for index in QUERY_ONLY_FEATURES {
            base_weights[index] = 0.0;
        }
        Ok(Self {
            version: DIAGNOSTIC_VERSION,
            feature_schema_identity: rank_evidence_schema_identity_v3(),
            base_weights,
            shape_interactions: [[0.0; RANK_EVIDENCE_V3_FEATURE_COUNT]; SHAPE_BASIS_COUNT],
        })
    }

    pub(super) fn is_valid(&self) -> bool {
        self.version == DIAGNOSTIC_VERSION
            && self.feature_schema_identity == rank_evidence_schema_identity_v3()
            && self.base_weights.iter().all(|value| value.is_finite())
            && self
                .shape_interactions
                .iter()
                .flatten()
                .all(|value| value.is_finite())
            && QUERY_ONLY_FEATURES.iter().all(|index| {
                self.base_weights[*index] == 0.0
                    && self
                        .shape_interactions
                        .iter()
                        .all(|weights| weights[*index] == 0.0)
            })
    }

    #[inline]
    pub(super) fn score(&self, evidence: RankEvidenceV3) -> Option<f32> {
        if !self.is_valid() || !evidence.is_valid() {
            return None;
        }
        Some(self.score_prevalidated(evidence))
    }

    #[inline]
    fn score_prevalidated(&self, evidence: RankEvidenceV3) -> f32 {
        debug_assert!(evidence.is_valid());
        let basis = shape_basis(evidence);
        let mut score = 0.0_f32;
        for (index, value) in evidence.values.into_iter().enumerate() {
            if is_query_only(index) {
                continue;
            }
            let mut weight = self.base_weights[index];
            for (shape_value, interaction) in basis.iter().zip(&self.shape_interactions) {
                weight = shape_value.mul_add(interaction[index], weight);
            }
            score = weight.max(0.0).mul_add(value, score);
        }
        debug_assert!(score.is_finite());
        score
    }

    pub(super) fn identity(&self) -> [u8; 32] {
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"phoenix-qps-v3-shape-conditioned-diagnostic\0");
        hasher.update(&self.version.to_le_bytes());
        hasher.update(&self.feature_schema_identity);
        for value in self.base_weights {
            hasher.update(&value.to_bits().to_le_bytes());
        }
        for block in self.shape_interactions {
            for value in block {
                hasher.update(&value.to_bits().to_le_bytes());
            }
        }
        *hasher.finalize().as_bytes()
    }

    pub(super) fn nonnegative_for(&self, evidence: RankEvidenceV3) -> bool {
        let basis = shape_basis(evidence);
        (0..RANK_EVIDENCE_V3_FEATURE_COUNT).all(|index| {
            if is_query_only(index) {
                return true;
            }
            let raw = basis
                .iter()
                .zip(&self.shape_interactions)
                .fold(self.base_weights[index], |weight, (shape, block)| {
                    shape.mul_add(block[index], weight)
                });
            raw.max(0.0).is_finite() && raw.max(0.0) >= 0.0
        })
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub(super) struct ShapeTrainingReceipt {
    pub training_ledger_identity: [u8; 32],
    pub leakage_split_identity: [u8; 32],
    pub baseline_model_identity: [u8; 32],
    pub diagnostic_model_identity: [u8; 32],
    pub configurations_evaluated: usize,
    pub selected_configuration: Option<ShapeTrainingConfig>,
    pub baseline_development: DevelopmentEvaluation,
    pub selected_development: DevelopmentEvaluation,
    pub deterministic_retraining: bool,
    pub query_only_coordinates_excluded_from_candidate_dot_product: bool,
    pub signed_interactions_with_nonnegative_effective_weights: bool,
}

pub(super) fn select_and_train(
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    ledger_identity: [u8; 32],
    baseline: &LinearRankerV3,
) -> Result<(ShapeConditionedRanker, ShapeTrainingReceipt), &'static str> {
    ledger.validate()?;
    if ledger_identity == [0; 32] || !split.audit.is_qualified() {
        return Err("shape diagnostic requires a qualified ledger and split");
    }
    let assignments = assignments(split);
    let training = sorted_judgments(ledger, &assignments, PrimarySplitV3::Training);
    if training.is_empty() {
        return Err("shape diagnostic training split is empty");
    }
    let baseline_shape = ShapeConditionedRanker::from_linear(baseline)?;
    let baseline_development = evaluate_development(
        &baseline_shape,
        ledger,
        &assignments,
        PrimarySplitV3::Development,
    );
    let mut best_model = baseline_shape.clone();
    let mut best_config = None;
    let mut best_evaluation = baseline_development;
    let mut configurations_evaluated = 1_usize;
    const EPOCHS: [u16; 5] = [8, 16, 32, 64, 128];
    const LEARNING_RATES: [f32; 3] = [0.0025, 0.005, 0.01];
    for epochs in EPOCHS {
        for learning_rate in LEARNING_RATES {
            let config = ShapeTrainingConfig {
                epochs,
                learning_rate,
                l2_penalty: 0.0001,
            };
            let candidate = train_once(&baseline_shape, &training, config);
            let evaluation = evaluate_development(
                &candidate,
                ledger,
                &assignments,
                PrimarySplitV3::Development,
            );
            configurations_evaluated += 1;
            if better_development(evaluation, best_evaluation) {
                best_model = candidate;
                best_config = Some(config);
                best_evaluation = evaluation;
            }
        }
    }
    let repeated = best_config.map_or_else(
        || baseline_shape.clone(),
        |config| train_once(&baseline_shape, &training, config),
    );
    let deterministic_retraining = repeated == best_model;
    let monotonic = ledger
        .active_model_training_judgments()
        .into_iter()
        .all(|judgment| {
            best_model.nonnegative_for(judgment.positive_features)
                && best_model.nonnegative_for(judgment.negative_features)
        });
    let receipt = ShapeTrainingReceipt {
        training_ledger_identity: ledger_identity,
        leakage_split_identity: leakage_split_identity_v3(split),
        baseline_model_identity: baseline.identity(),
        diagnostic_model_identity: best_model.identity(),
        configurations_evaluated,
        selected_configuration: best_config,
        baseline_development,
        selected_development: best_evaluation,
        deterministic_retraining,
        query_only_coordinates_excluded_from_candidate_dot_product: true,
        signed_interactions_with_nonnegative_effective_weights: monotonic,
    };
    Ok((best_model, receipt))
}

fn train_once(
    initial: &ShapeConditionedRanker,
    training: &[&PairwiseJudgmentV3],
    config: ShapeTrainingConfig,
) -> ShapeConditionedRanker {
    let mut model = initial.clone();
    let anchor = initial.base_weights;
    let l2_scale = 2.0 * config.l2_penalty / training.len().max(1) as f32;
    for _ in 0..config.epochs {
        for judgment in training {
            let basis = shape_basis(judgment.positive_features);
            let difference = judgment
                .positive_features
                .difference(judgment.negative_features);
            let margin = model.score_prevalidated(judgment.positive_features)
                - model.score_prevalidated(judgment.negative_features);
            let pressure = judgment.weight * judgment.confidence / (1.0 + margin.exp());
            for (index, delta) in difference.into_iter().enumerate() {
                if is_query_only(index) {
                    continue;
                }
                let raw = basis
                    .iter()
                    .zip(&model.shape_interactions)
                    .fold(model.base_weights[index], |weight, (shape, block)| {
                        shape.mul_add(block[index], weight)
                    });
                let data_gradient = pressure * delta;
                if raw > 0.0 || data_gradient > 0.0 {
                    let regularization = l2_scale * (model.base_weights[index] - anchor[index]);
                    model.base_weights[index] = bounded(
                        model.base_weights[index]
                            + config.learning_rate * (data_gradient - regularization),
                    );
                    for (shape, interaction) in basis.iter().zip(&mut model.shape_interactions) {
                        let regularization = l2_scale * interaction[index];
                        interaction[index] = bounded(
                            interaction[index]
                                + config.learning_rate * (data_gradient * *shape - regularization),
                        );
                    }
                }
            }
        }
    }
    model
}

fn evaluate_development(
    model: &ShapeConditionedRanker,
    ledger: &RelevanceLedgerV3,
    assignments: &HashMap<phoenix_lexical_qps::JudgmentIdentity, PrimarySplitV3>,
    target: PrimarySplitV3,
) -> DevelopmentEvaluation {
    let mut judgments = 0_usize;
    let mut correctly_ordered = 0_usize;
    let mut classes = HashMap::<JudgmentReasonV3, (usize, usize)>::new();
    for judgment in ledger
        .active_model_training_judgments()
        .into_iter()
        .filter(|judgment| assignments.get(&judgment.identity) == Some(&target))
    {
        let correct = model
            .score(judgment.positive_features)
            .unwrap_or(f32::NEG_INFINITY)
            > model
                .score(judgment.negative_features)
                .unwrap_or(f32::NEG_INFINITY);
        judgments += 1;
        correctly_ordered += usize::from(correct);
        let entry = classes.entry(judgment.reason).or_default();
        entry.0 += 1;
        entry.1 += usize::from(correct);
    }
    let represented_classes = classes.len();
    let macro_class_accuracy = classes
        .values()
        .map(|(total, correct)| *correct as f32 / (*total).max(1) as f32)
        .sum::<f32>()
        / represented_classes.max(1) as f32;
    let minimum_class_accuracy = classes
        .values()
        .map(|(total, correct)| *correct as f32 / (*total).max(1) as f32)
        .fold(1.0_f32, f32::min);
    DevelopmentEvaluation {
        judgments,
        correctly_ordered,
        accuracy: correctly_ordered as f32 / judgments.max(1) as f32,
        represented_classes,
        macro_class_accuracy,
        minimum_class_accuracy,
    }
}

fn better_development(candidate: DevelopmentEvaluation, best: DevelopmentEvaluation) -> bool {
    candidate.accuracy > best.accuracy
        || (candidate.accuracy == best.accuracy
            && candidate.macro_class_accuracy > best.macro_class_accuracy)
        || (candidate.accuracy == best.accuracy
            && candidate.macro_class_accuracy == best.macro_class_accuracy
            && candidate.minimum_class_accuracy > best.minimum_class_accuracy)
}

fn assignments(
    split: &LeakageSplitV3,
) -> HashMap<phoenix_lexical_qps::JudgmentIdentity, PrimarySplitV3> {
    split
        .assignments
        .iter()
        .map(|assignment| (assignment.judgment_identity, assignment.primary_split))
        .collect()
}

fn sorted_judgments<'a>(
    ledger: &'a RelevanceLedgerV3,
    assignments: &HashMap<phoenix_lexical_qps::JudgmentIdentity, PrimarySplitV3>,
    target: PrimarySplitV3,
) -> Vec<&'a PairwiseJudgmentV3> {
    let mut judgments = ledger
        .active_model_training_judgments()
        .into_iter()
        .filter(|judgment| assignments.get(&judgment.identity) == Some(&target))
        .collect::<Vec<_>>();
    judgments.sort_unstable_by(|left, right| {
        left.query_identity
            .cmp(&right.query_identity)
            .then_with(|| {
                left.positive_document_version
                    .cmp(&right.positive_document_version)
            })
            .then_with(|| {
                left.negative_document_version
                    .cmp(&right.negative_document_version)
            })
            .then_with(|| left.identity.cmp(&right.identity))
    });
    judgments
}

#[inline]
fn shape_basis(evidence: RankEvidenceV3) -> [f32; SHAPE_BASIS_COUNT] {
    [
        evidence.values[RankEvidenceV3::QUERY_GROUP_COUNT],
        evidence.values[RankEvidenceV3::SINGLE_GROUP_FLAG],
        evidence.values[RankEvidenceV3::LONG_QUERY_FLAG],
    ]
}

#[inline]
fn is_query_only(index: usize) -> bool {
    QUERY_ONLY_FEATURES.contains(&index)
}

#[inline]
fn bounded(value: f32) -> f32 {
    value.clamp(-16.0, 16.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use phoenix_lexical_qps::FeatureNormalizationV3;

    fn evidence(long: bool, lexical: f32) -> RankEvidenceV3 {
        let mut values = [0.0; RANK_EVIDENCE_V3_FEATURE_COUNT];
        values[RankEvidenceV3::BM25F_LEXICAL] = lexical;
        values[RankEvidenceV3::MATCHED_GROUP_FRACTION] = 1.0;
        values[RankEvidenceV3::MISSING_GROUP_ABSENCE] = 1.0;
        values[RankEvidenceV3::COMPLETE_COVERAGE] = 1.0;
        values[RankEvidenceV3::QUERY_GROUP_COUNT] = 0.25;
        values[RankEvidenceV3::LONG_QUERY_FLAG] = f32::from(long);
        RankEvidenceV3 {
            schema_version: 3,
            query_groups: 2,
            matched_groups: 2,
            missing_groups: 0,
            query_flags: if long { 1 << 2 } else { 0 },
            field_count: 1,
            values,
        }
    }

    #[test]
    fn interactions_change_candidate_slope_without_query_only_score() {
        let mut weights = [0.0; RANK_EVIDENCE_V3_FEATURE_COUNT];
        weights[RankEvidenceV3::BM25F_LEXICAL] = 1.0;
        let linear = LinearRankerV3::from_weights(FeatureNormalizationV3::identity(), weights)
            .expect("linear model");
        let mut model = ShapeConditionedRanker::from_linear(&linear).expect("shape model");
        assert_eq!(model.score(evidence(false, 0.5)), Some(0.5));
        assert_eq!(model.score(evidence(true, 0.5)), Some(0.5));
        model.shape_interactions[2][RankEvidenceV3::BM25F_LEXICAL] = 2.0;
        assert_eq!(model.score(evidence(false, 0.5)), Some(0.5));
        assert_eq!(model.score(evidence(true, 0.5)), Some(1.5));
    }

    #[test]
    fn effective_weights_are_monotonic_after_signed_modulation() {
        let mut weights = [0.0; RANK_EVIDENCE_V3_FEATURE_COUNT];
        weights[RankEvidenceV3::BM25F_LEXICAL] = 1.0;
        let linear = LinearRankerV3::from_weights(FeatureNormalizationV3::identity(), weights)
            .expect("linear model");
        let mut model = ShapeConditionedRanker::from_linear(&linear).expect("shape model");
        model.shape_interactions[2][RankEvidenceV3::BM25F_LEXICAL] = -4.0;
        assert!(model.nonnegative_for(evidence(true, 0.5)));
        assert_eq!(model.score(evidence(true, 0.5)), Some(0.0));
    }
}
