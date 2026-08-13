use hashbrown::HashMap;
use serde::{Deserialize, Serialize};
use smallvec::SmallVec;

use crate::{
    leakage_split_identity_v3, rank_evidence_schema_identity_v3, FeatureNormalizationV3,
    KeyedIdentity, LeakageSplitV3, LinearRankerV3, LinearTrainingConfigV3, PairwiseJudgmentV3,
    PrimarySplitV3, QueryNormalizedDevelopmentV3, RankEvidenceV3, RelevanceLedgerV3, RelevanceTier,
    RANK_EVIDENCE_V3_FEATURE_COUNT, TOP_SENSITIVE_OFF_TOP_FLOOR_V3,
};

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct LambdaRankObjectiveReceiptV3 {
    pub training_ledger_identity: [u8; 32],
    pub leakage_split_identity: [u8; 32],
    pub feature_schema_identity: [u8; 32],
    pub model_identity: [u8; 32],
    pub training_judgments: usize,
    pub training_queries: usize,
    pub judged_candidates: usize,
    pub epochs: u16,
    pub learning_rate: f32,
    pub l2_penalty: f32,
    pub off_top_weight_floor: f32,
    pub dynamic_current_order_reweighting: bool,
    pub initial_query_normalized_objective: f32,
    pub final_query_normalized_objective: f32,
    pub correctly_ordered: usize,
    pub row_pairwise_accuracy: f32,
    pub query_normalized_weighted_accuracy: f32,
}

pub fn train_query_normalized_lambdarank_v3(
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    training_ledger_identity: [u8; 32],
    config: LinearTrainingConfigV3,
) -> Result<(LinearRankerV3, LambdaRankObjectiveReceiptV3), &'static str> {
    ledger.validate()?;
    train_query_normalized_lambdarank_v3_prevalidated(
        ledger,
        split,
        training_ledger_identity,
        config,
    )
}

/// Prevalidated entry point for deterministic development grids. The caller
/// must have validated the immutable ledger once before invoking this method.
pub fn train_query_normalized_lambdarank_v3_prevalidated(
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    training_ledger_identity: [u8; 32],
    config: LinearTrainingConfigV3,
) -> Result<(LinearRankerV3, LambdaRankObjectiveReceiptV3), &'static str> {
    validate_config(config)?;
    if training_ledger_identity == [0; 32]
        || split.audit.eligible_judgments == 0
        || !split.audit.is_qualified()
    {
        return Err("LambdaRank V3 requires a qualified split and ledger identity");
    }
    let judgments = split_judgments(ledger, split, PrimarySplitV3::Training);
    let batches = build_query_batches(&judgments)?;
    if batches.is_empty() {
        return Err("LambdaRank V3 training split contains no query batches");
    }
    let normalization = FeatureNormalizationV3::identity();
    let mut weights = [0.0; RANK_EVIDENCE_V3_FEATURE_COUNT];
    let initial = objective(&weights, normalization, &batches, config);
    let l2_gradient_per_query = 2.0 * config.l2_penalty / batches.len() as f32;

    for _ in 0..config.epochs {
        for batch in &batches {
            let ranks = current_ranks(batch, &weights, normalization);
            let total = batch
                .pairs
                .iter()
                .map(|pair| dynamic_raw_weight(pair, &ranks))
                .sum::<f32>();
            if !total.is_finite() || total <= 0.0 {
                return Err("invalid LambdaRank query weight");
            }
            let mut gradient = [0.0; RANK_EVIDENCE_V3_FEATURE_COUNT];
            for pair in &batch.pairs {
                let difference = normalized_difference(
                    normalization,
                    pair.judgment.positive_features,
                    pair.judgment.negative_features,
                );
                let margin = dot(&weights, &difference);
                let normalized_weight = dynamic_raw_weight(pair, &ranks) / total;
                let pressure = normalized_weight / (1.0 + margin.exp());
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
    let final_objective = objective(&weights, normalization, &batches, config);
    let evaluation = evaluate_batches(&model, &batches);
    let receipt = LambdaRankObjectiveReceiptV3 {
        training_ledger_identity,
        leakage_split_identity: leakage_split_identity_v3(split),
        feature_schema_identity: rank_evidence_schema_identity_v3(),
        model_identity: model.identity(),
        training_judgments: judgments.len(),
        training_queries: batches.len(),
        judged_candidates: batches.iter().map(|batch| batch.candidates.len()).sum(),
        epochs: config.epochs,
        learning_rate: config.learning_rate,
        l2_penalty: config.l2_penalty,
        off_top_weight_floor: TOP_SENSITIVE_OFF_TOP_FLOOR_V3,
        dynamic_current_order_reweighting: true,
        initial_query_normalized_objective: initial,
        final_query_normalized_objective: final_objective,
        correctly_ordered: evaluation.correctly_ordered,
        row_pairwise_accuracy: evaluation.row_pairwise_accuracy,
        query_normalized_weighted_accuracy: evaluation.query_normalized_weighted_accuracy,
    };
    Ok((model, receipt))
}

pub fn evaluate_query_normalized_lambdarank_v3(
    model: &LinearRankerV3,
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    target: PrimarySplitV3,
) -> Result<QueryNormalizedDevelopmentV3, &'static str> {
    if !model.is_valid() {
        return Err("invalid LambdaRank V3 model");
    }
    let judgments = split_judgments(ledger, split, target);
    let batches = build_query_batches(&judgments)?;
    if batches.is_empty() {
        return Err("requested LambdaRank V3 evaluation split is empty");
    }
    let evaluated = evaluate_batches(model, &batches);
    Ok(QueryNormalizedDevelopmentV3 {
        judgments: judgments.len(),
        queries: batches.len(),
        correctly_ordered: evaluated.correctly_ordered,
        row_pairwise_accuracy: evaluated.row_pairwise_accuracy,
        query_normalized_weighted_accuracy: evaluated.query_normalized_weighted_accuracy,
        query_normalized_logistic_loss: evaluated.logistic_loss,
        non_finite_scores: evaluated.non_finite_scores,
    })
}

#[derive(Clone, Copy)]
struct Candidate {
    identity: KeyedIdentity,
    tier: RelevanceTier,
    evidence: RankEvidenceV3,
}

#[derive(Clone, Copy)]
struct IndexedPair<'a> {
    judgment: &'a PairwiseJudgmentV3,
    positive: usize,
    negative: usize,
}

struct QueryBatch<'a> {
    candidates: Vec<Candidate>,
    pairs: Vec<IndexedPair<'a>>,
}

#[derive(Clone, Copy, Default)]
struct BatchEvaluation {
    correctly_ordered: usize,
    row_pairwise_accuracy: f32,
    query_normalized_weighted_accuracy: f32,
    logistic_loss: f32,
    non_finite_scores: usize,
}

fn build_query_batches<'a>(
    judgments: &[&'a PairwiseJudgmentV3],
) -> Result<Vec<QueryBatch<'a>>, &'static str> {
    let mut batches = Vec::new();
    let mut start = 0;
    while start < judgments.len() {
        let query = judgments[start].query_identity;
        let mut end = start + 1;
        while end < judgments.len() && judgments[end].query_identity == query {
            end += 1;
        }
        let mut candidates = Vec::new();
        let mut indices = HashMap::<KeyedIdentity, usize>::new();
        let mut pairs = Vec::with_capacity(end - start);
        for judgment in &judgments[start..end] {
            let positive = insert_candidate(
                &mut candidates,
                &mut indices,
                judgment.positive_document_version,
                judgment.positive_tier,
                judgment.positive_features,
            )?;
            let negative = insert_candidate(
                &mut candidates,
                &mut indices,
                judgment.negative_document_version,
                judgment.negative_tier,
                judgment.negative_features,
            )?;
            pairs.push(IndexedPair {
                judgment,
                positive,
                negative,
            });
        }
        batches.push(QueryBatch { candidates, pairs });
        start = end;
    }
    Ok(batches)
}

fn insert_candidate(
    candidates: &mut Vec<Candidate>,
    indices: &mut HashMap<KeyedIdentity, usize>,
    identity: KeyedIdentity,
    tier: RelevanceTier,
    evidence: RankEvidenceV3,
) -> Result<usize, &'static str> {
    if let Some(index) = indices.get(&identity).copied() {
        let existing = candidates[index];
        if existing.tier != tier || existing.evidence != evidence {
            return Err("query candidate has inconsistent tier or evidence across judgments");
        }
        return Ok(index);
    }
    let index = candidates.len();
    candidates.push(Candidate {
        identity,
        tier,
        evidence,
    });
    indices.insert(identity, index);
    Ok(index)
}

fn current_ranks(
    batch: &QueryBatch<'_>,
    weights: &[f32; RANK_EVIDENCE_V3_FEATURE_COUNT],
    normalization: FeatureNormalizationV3,
) -> SmallVec<[usize; 8]> {
    let mut order = (0..batch.candidates.len()).collect::<SmallVec<[usize; 8]>>();
    order.sort_unstable_by(|left, right| {
        let left = batch.candidates[*left];
        let right = batch.candidates[*right];
        left.tier
            .cmp(&right.tier)
            .then_with(|| {
                score(weights, normalization, right.evidence).total_cmp(&score(
                    weights,
                    normalization,
                    left.evidence,
                ))
            })
            .then_with(|| left.identity.cmp(&right.identity))
    });
    let mut ranks = SmallVec::<[usize; 8]>::from_elem(0, batch.candidates.len());
    for (rank, candidate) in order.into_iter().enumerate() {
        ranks[candidate] = rank;
    }
    ranks
}

fn dynamic_raw_weight(pair: &IndexedPair<'_>, ranks: &[usize]) -> f32 {
    pair.judgment.weight
        * pair.judgment.confidence
        * (TOP_SENSITIVE_OFF_TOP_FLOOR_V3
            + (discount(ranks[pair.positive]) - discount(ranks[pair.negative])).abs())
}

fn discount(rank: usize) -> f32 {
    if rank < 10 {
        1.0 / ((rank as f32 + 2.0).log2())
    } else {
        0.0
    }
}

fn evaluate_batches(model: &LinearRankerV3, batches: &[QueryBatch<'_>]) -> BatchEvaluation {
    let mut evaluation = BatchEvaluation::default();
    let mut correct_weight = 0.0;
    let mut loss = 0.0;
    let mut judgments = 0;
    for batch in batches {
        let ranks = current_ranks(batch, &model.weights, model.normalization);
        let total = batch
            .pairs
            .iter()
            .map(|pair| dynamic_raw_weight(pair, &ranks))
            .sum::<f32>();
        for pair in &batch.pairs {
            let normalized_weight = dynamic_raw_weight(pair, &ranks) / total;
            match (
                model.score(pair.judgment.positive_features),
                model.score(pair.judgment.negative_features),
            ) {
                (Some(positive), Some(negative)) => {
                    let margin = positive - negative;
                    loss += normalized_weight * softplus(-margin);
                    if margin > 0.0 {
                        evaluation.correctly_ordered += 1;
                        correct_weight += normalized_weight;
                    }
                }
                _ => evaluation.non_finite_scores += 1,
            }
            judgments += 1;
        }
    }
    evaluation.row_pairwise_accuracy =
        evaluation.correctly_ordered as f32 / judgments.max(1) as f32;
    evaluation.query_normalized_weighted_accuracy = correct_weight / batches.len().max(1) as f32;
    evaluation.logistic_loss = loss / batches.len().max(1) as f32;
    evaluation
}

fn objective(
    weights: &[f32; RANK_EVIDENCE_V3_FEATURE_COUNT],
    normalization: FeatureNormalizationV3,
    batches: &[QueryBatch<'_>],
    config: LinearTrainingConfigV3,
) -> f32 {
    let mut loss = 0.0;
    for batch in batches {
        let ranks = current_ranks(batch, weights, normalization);
        let total = batch
            .pairs
            .iter()
            .map(|pair| dynamic_raw_weight(pair, &ranks))
            .sum::<f32>();
        for pair in &batch.pairs {
            let difference = normalized_difference(
                normalization,
                pair.judgment.positive_features,
                pair.judgment.negative_features,
            );
            loss += dynamic_raw_weight(pair, &ranks) / total * softplus(-dot(weights, &difference));
        }
    }
    loss / batches.len().max(1) as f32 + config.l2_penalty * dot(weights, weights)
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

fn score(
    weights: &[f32; RANK_EVIDENCE_V3_FEATURE_COUNT],
    normalization: FeatureNormalizationV3,
    evidence: RankEvidenceV3,
) -> f32 {
    let mut values = [0.0; RANK_EVIDENCE_V3_FEATURE_COUNT];
    for (index, value) in values.iter_mut().enumerate() {
        *value = ((evidence.values[index] - normalization.offsets[index])
            * normalization.scales[index])
            .clamp(0.0, 1.0);
    }
    dot(weights, &values)
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
        .fold(0.0, |sum, (weight, value)| weight.mul_add(*value, sum))
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
        return Err("invalid LambdaRank V3 training configuration");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dynamic_discount_is_top_ten_capped() {
        assert_eq!(discount(0), 1.0);
        assert!(discount(9) > 0.0);
        assert_eq!(discount(10), 0.0);
    }
}
