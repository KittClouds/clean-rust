use hashbrown::HashMap;
use serde::{Deserialize, Serialize};

use crate::{
    leakage_split_identity_v3, rank_evidence_schema_identity_v3, FeatureNormalizationV3,
    KeyedIdentity, LeakageSplitV3, LinearRankerV3, LinearTrainingConfigV3, PairwiseJudgmentV3,
    PrimarySplitV3, RankEvidenceV3, RelevanceLedgerV3, RANK_EVIDENCE_V3_FEATURE_COUNT,
};

/// Every reviewed pair retains a small amount of force, while errors that
/// exchange a preferred and non-preferred document near the top of the list
/// receive the exact binary-gain DCG@10 swap delta.
pub const TOP_SENSITIVE_OFF_TOP_FLOOR_V3: f32 = 0.05;

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct QueryNormalizedObjectiveReceiptV3 {
    pub training_ledger_identity: [u8; 32],
    pub leakage_split_identity: [u8; 32],
    pub feature_schema_identity: [u8; 32],
    pub model_identity: [u8; 32],
    pub training_judgments: usize,
    pub training_queries: usize,
    pub epochs: u16,
    pub learning_rate: f32,
    pub l2_penalty: f32,
    pub off_top_weight_floor: f32,
    pub initial_query_normalized_objective: f32,
    pub final_query_normalized_objective: f32,
    pub correctly_ordered: usize,
    pub row_pairwise_accuracy: f32,
    pub query_normalized_weighted_accuracy: f32,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct QueryNormalizedDevelopmentV3 {
    pub judgments: usize,
    pub queries: usize,
    pub correctly_ordered: usize,
    pub row_pairwise_accuracy: f32,
    pub query_normalized_weighted_accuracy: f32,
    pub query_normalized_logistic_loss: f32,
    pub non_finite_scores: usize,
}

pub fn train_query_normalized_top_sensitive_ranker_v3(
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    training_ledger_identity: [u8; 32],
    config: LinearTrainingConfigV3,
) -> Result<(LinearRankerV3, QueryNormalizedObjectiveReceiptV3), &'static str> {
    ledger.validate()?;
    train_query_normalized_top_sensitive_ranker_v3_prevalidated(
        ledger,
        split,
        training_ledger_identity,
        config,
    )
}

/// Runs the same deterministic trainer after the caller has validated the
/// immutable ledger once. This exists for bounded hyperparameter grids so a
/// large append-only ledger is not reparsed for every configuration.
pub fn train_query_normalized_top_sensitive_ranker_v3_prevalidated(
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    training_ledger_identity: [u8; 32],
    config: LinearTrainingConfigV3,
) -> Result<(LinearRankerV3, QueryNormalizedObjectiveReceiptV3), &'static str> {
    validate_config(config)?;
    if training_ledger_identity == [0; 32]
        || split.audit.eligible_judgments == 0
        || !split.audit.is_qualified()
    {
        return Err("top-sensitive V3 training requires a qualified split and ledger identity");
    }
    let training = split_judgments(ledger, split, PrimarySplitV3::Training);
    if training.is_empty() {
        return Err("top-sensitive V3 training split contains no judgments");
    }
    let weighted = query_normalized_pairs(training)?;
    let query_ranges = query_ranges(&weighted);
    let normalization = FeatureNormalizationV3::identity();
    let mut weights = [0.0; RANK_EVIDENCE_V3_FEATURE_COUNT];
    let initial = objective(
        &weights,
        normalization,
        &weighted,
        query_ranges.len(),
        config,
    );
    let l2_gradient_per_query = 2.0 * config.l2_penalty / query_ranges.len().max(1) as f32;

    for _ in 0..config.epochs {
        for range in &query_ranges {
            let mut gradient = [0.0; RANK_EVIDENCE_V3_FEATURE_COUNT];
            for pair in &weighted[range.clone()] {
                let difference = normalized_difference(
                    normalization,
                    pair.judgment.positive_features,
                    pair.judgment.negative_features,
                );
                let margin = dot(&weights, &difference);
                let pressure = pair.normalized_weight / (1.0 + margin.exp());
                for (value, delta) in gradient.iter_mut().zip(difference) {
                    *value = pressure.mul_add(delta, *value);
                }
            }
            for (weight, data_gradient) in weights.iter_mut().zip(gradient) {
                *weight += config.learning_rate * (data_gradient - l2_gradient_per_query * *weight);
                *weight = weight.max(0.0);
            }
        }
    }

    let model = LinearRankerV3::from_weights(normalization, weights)?;
    let final_objective = objective(
        &weights,
        normalization,
        &weighted,
        query_ranges.len(),
        config,
    );
    let evaluation = evaluate_weighted(&model, &weighted, query_ranges.len());
    let receipt = QueryNormalizedObjectiveReceiptV3 {
        training_ledger_identity,
        leakage_split_identity: leakage_split_identity_v3(split),
        feature_schema_identity: rank_evidence_schema_identity_v3(),
        model_identity: model.identity(),
        training_judgments: weighted.len(),
        training_queries: query_ranges.len(),
        epochs: config.epochs,
        learning_rate: config.learning_rate,
        l2_penalty: config.l2_penalty,
        off_top_weight_floor: TOP_SENSITIVE_OFF_TOP_FLOOR_V3,
        initial_query_normalized_objective: initial,
        final_query_normalized_objective: final_objective,
        correctly_ordered: evaluation.correctly_ordered,
        row_pairwise_accuracy: evaluation.row_pairwise_accuracy,
        query_normalized_weighted_accuracy: evaluation.query_normalized_weighted_accuracy,
    };
    Ok((model, receipt))
}

pub fn evaluate_query_normalized_top_sensitive_ranker_v3(
    model: &LinearRankerV3,
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    target: PrimarySplitV3,
) -> Result<QueryNormalizedDevelopmentV3, &'static str> {
    if !model.is_valid() {
        return Err("invalid top-sensitive V3 model");
    }
    let judgments = split_judgments(ledger, split, target);
    if judgments.is_empty() {
        return Err("requested V3 evaluation split is empty");
    }
    let weighted = query_normalized_pairs(judgments)?;
    let queries = query_ranges(&weighted).len();
    let evaluation = evaluate_weighted(model, &weighted, queries);
    let logistic_loss = weighted
        .iter()
        .map(|pair| {
            let difference = normalized_difference(
                model.normalization,
                pair.judgment.positive_features,
                pair.judgment.negative_features,
            );
            pair.normalized_weight * softplus(-dot(&model.weights, &difference))
        })
        .sum::<f32>()
        / queries.max(1) as f32;
    Ok(QueryNormalizedDevelopmentV3 {
        judgments: weighted.len(),
        queries,
        correctly_ordered: evaluation.correctly_ordered,
        row_pairwise_accuracy: evaluation.row_pairwise_accuracy,
        query_normalized_weighted_accuracy: evaluation.query_normalized_weighted_accuracy,
        query_normalized_logistic_loss: logistic_loss,
        non_finite_scores: evaluation.non_finite_scores,
    })
}

#[derive(Clone, Copy)]
struct WeightedPair<'a> {
    judgment: &'a PairwiseJudgmentV3,
    normalized_weight: f32,
}

#[derive(Clone, Copy, Default)]
struct WeightedEvaluation {
    correctly_ordered: usize,
    row_pairwise_accuracy: f32,
    query_normalized_weighted_accuracy: f32,
    non_finite_scores: usize,
}

fn split_judgments<'a>(
    ledger: &'a RelevanceLedgerV3,
    split: &LeakageSplitV3,
    target: PrimarySplitV3,
) -> Vec<&'a PairwiseJudgmentV3> {
    let assignments = split
        .assignments
        .iter()
        .map(|value| (value.judgment_identity, value.primary_split))
        .collect::<HashMap<_, _>>();
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

fn query_normalized_pairs(
    judgments: Vec<&PairwiseJudgmentV3>,
) -> Result<Vec<WeightedPair<'_>>, &'static str> {
    let mut totals = HashMap::<KeyedIdentity, f32>::new();
    for judgment in &judgments {
        let raw = raw_pair_weight(judgment);
        if !raw.is_finite() || raw <= 0.0 {
            return Err("invalid top-sensitive pair weight");
        }
        *totals.entry(judgment.query_identity).or_default() += raw;
    }
    judgments
        .into_iter()
        .map(|judgment| {
            let total = totals.get(&judgment.query_identity).copied().unwrap_or(0.0);
            let normalized_weight = raw_pair_weight(judgment) / total;
            if !normalized_weight.is_finite() || normalized_weight <= 0.0 {
                return Err("invalid query-normalized pair weight");
            }
            Ok(WeightedPair {
                judgment,
                normalized_weight,
            })
        })
        .collect()
}

fn query_ranges(weighted: &[WeightedPair<'_>]) -> Vec<std::ops::Range<usize>> {
    let mut ranges = Vec::new();
    let mut start = 0;
    while start < weighted.len() {
        let query = weighted[start].judgment.query_identity;
        let mut end = start + 1;
        while end < weighted.len() && weighted[end].judgment.query_identity == query {
            end += 1;
        }
        ranges.push(start..end);
        start = end;
    }
    ranges
}

fn raw_pair_weight(judgment: &PairwiseJudgmentV3) -> f32 {
    judgment.weight
        * judgment.confidence
        * top_sensitive_swap_weight(judgment.positive_position, judgment.negative_position)
}

fn top_sensitive_swap_weight(positive_position: u16, negative_position: u16) -> f32 {
    TOP_SENSITIVE_OFF_TOP_FLOOR_V3
        + (dcg_discount_at_10(positive_position) - dcg_discount_at_10(negative_position)).abs()
}

fn dcg_discount_at_10(position: u16) -> f32 {
    if position < 10 {
        1.0 / ((position as f32 + 2.0).log2())
    } else {
        0.0
    }
}

fn evaluate_weighted(
    model: &LinearRankerV3,
    weighted: &[WeightedPair<'_>],
    queries: usize,
) -> WeightedEvaluation {
    let mut evaluation = WeightedEvaluation::default();
    let mut correct_weight = 0.0;
    for pair in weighted {
        match (
            model.score(pair.judgment.positive_features),
            model.score(pair.judgment.negative_features),
        ) {
            (Some(positive), Some(negative)) => {
                if positive > negative {
                    evaluation.correctly_ordered += 1;
                    correct_weight += pair.normalized_weight;
                }
            }
            _ => evaluation.non_finite_scores += 1,
        }
    }
    evaluation.row_pairwise_accuracy =
        evaluation.correctly_ordered as f32 / weighted.len().max(1) as f32;
    evaluation.query_normalized_weighted_accuracy = correct_weight / queries.max(1) as f32;
    evaluation
}

fn objective(
    weights: &[f32; RANK_EVIDENCE_V3_FEATURE_COUNT],
    normalization: FeatureNormalizationV3,
    weighted: &[WeightedPair<'_>],
    queries: usize,
    config: LinearTrainingConfigV3,
) -> f32 {
    let data_loss = weighted
        .iter()
        .map(|pair| {
            let difference = normalized_difference(
                normalization,
                pair.judgment.positive_features,
                pair.judgment.negative_features,
            );
            pair.normalized_weight * softplus(-dot(weights, &difference))
        })
        .sum::<f32>()
        / queries.max(1) as f32;
    data_loss + config.l2_penalty * dot(weights, weights)
}

fn normalized_difference(
    normalization: FeatureNormalizationV3,
    positive: RankEvidenceV3,
    negative: RankEvidenceV3,
) -> [f32; RANK_EVIDENCE_V3_FEATURE_COUNT] {
    let mut difference = [0.0; RANK_EVIDENCE_V3_FEATURE_COUNT];
    for (index, value) in difference.iter_mut().enumerate() {
        *value = ((positive.values[index] - normalization.offsets[index])
            * normalization.scales[index])
            .clamp(0.0, 1.0)
            - ((negative.values[index] - normalization.offsets[index])
                * normalization.scales[index])
                .clamp(0.0, 1.0);
    }
    difference
}

fn dot(
    weights: &[f32; RANK_EVIDENCE_V3_FEATURE_COUNT],
    values: &[f32; RANK_EVIDENCE_V3_FEATURE_COUNT],
) -> f32 {
    weights
        .iter()
        .zip(values)
        .fold(0.0, |score, (weight, value)| weight.mul_add(*value, score))
}

fn softplus(value: f32) -> f32 {
    if value > 20.0 {
        value
    } else {
        value.exp().ln_1p()
    }
}

fn validate_config(config: LinearTrainingConfigV3) -> Result<(), &'static str> {
    if config.epochs == 0
        || config.epochs > 16_384
        || !config.learning_rate.is_finite()
        || !(0.0..=1.0).contains(&config.learning_rate)
        || config.learning_rate == 0.0
        || !config.l2_penalty.is_finite()
        || !(0.0..=0.1).contains(&config.l2_penalty)
    {
        return Err("invalid top-sensitive V3 training configuration");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn top_swap_has_more_force_than_an_off_top_swap() {
        assert!(top_sensitive_swap_weight(0, 1) > top_sensitive_swap_weight(20, 30));
        assert_eq!(
            top_sensitive_swap_weight(20, 30),
            TOP_SENSITIVE_OFF_TOP_FLOOR_V3
        );
    }

    #[test]
    fn dcg_discount_is_capped_at_ten() {
        assert_eq!(dcg_discount_at_10(0), 1.0);
        assert!(dcg_discount_at_10(9) > 0.0);
        assert_eq!(dcg_discount_at_10(10), 0.0);
    }
}
