use crate::hyper_encoder_examples::PreparedHyperExamples;
use crate::optimization_envelope_model::{
    empty_metrics, CausalRankArtifactReceipt, EnvelopeArm, PairedRankDeltaReceipt,
    RankArtifactReceipt, StructuralValidationSlices, TrainScoreReceipt,
};
use crate::CandleTrainerError;
use compact_str::format_compact;
use phoenix_graph_research::{
    profile_hyper_relational_validation_batched, ExternalDatasetMapped, ExternalFactSplit,
    HyperEncoderEncoded, HyperRelationalCandidatePolicy, HyperRelationalMetricSlice,
    HyperRelationalQueryRank, HyperRelationalQueryView, HyperRelationalRankingMetrics,
    HyperRelationalTaskMapped, LinkPredictionSplit, ProfiledHyperRelationalEvaluation,
    DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

const RANK_MAGIC: &[u8; 8] = b"PHXRNK01";
const DELTA_MAGIC: &[u8; 8] = b"PHXRND01";
const BUCKETS: [u64; 8] = [1, 2, 4, 8, 16, 32, 64, 128];

pub(crate) fn evaluate_validation(
    source: &ExternalDatasetMapped,
    task: &HyperRelationalTaskMapped,
    encoded: &HyperEncoderEncoded<'_>,
) -> Result<ProfiledHyperRelationalEvaluation, CandleTrainerError> {
    Ok(profile_hyper_relational_validation_batched(
        task,
        encoded.model_id(),
        HyperRelationalCandidatePolicy::FullEntity,
        DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
        |queries, candidates, scores| {
            encoded.score_candidate_batch(source, queries, candidates, scores)
        },
    )?)
}

pub(crate) fn score_train_examples(
    source: &ExternalDatasetMapped,
    encoded: &HyperEncoderEncoded<'_>,
    examples: &PreparedHyperExamples,
) -> Result<TrainScoreReceipt, CandleTrainerError> {
    let batch = 4096_usize;
    let mut scores = vec![0.0_f32; batch];
    let mut views = Vec::with_capacity(batch);
    let mut hash = blake3::Hasher::new();
    let mut positive = 0.0_f64;
    let mut negative = 0.0_f64;
    let mut positives = 0_u64;
    let mut negatives = 0_u64;
    let mut loss = 0.0_f64;
    let mut ordered = 0_u64;
    let mut pairs = 0_u64;
    let mut pending_positive = None;
    for start in (0..examples.len()).step_by(batch) {
        let end = (start + batch).min(examples.len());
        views.clear();
        for index in start..end {
            views.push(HyperRelationalQueryView {
                source: examples.sources[index],
                relation: examples.relations[index],
                qualifier_offset: examples.qualifier_offsets[index],
                qualifier_count: examples.qualifier_counts[index],
                split: LinkPredictionSplit::Validation,
                inverse: false,
                target_role: 0,
            });
        }
        encoded
            .score_target_batch(
                source,
                &views,
                &examples.targets[start..end],
                &mut scores[..end - start],
            )
            .map_err(phoenix_graph_research::HyperRelationalTaskError::Scorer)?;
        for (index, &score) in scores[..end - start].iter().enumerate() {
            hash.update(&score.to_bits().to_le_bytes());
            let label = examples.labels[start + index];
            loss += if score >= 0.0 {
                f64::from((1.0 + (-score).exp()).ln()) + if label { 0.0 } else { f64::from(score) }
            } else {
                f64::from((1.0 + score.exp()).ln()) - if label { f64::from(score) } else { 0.0 }
            };
            if label {
                positive += f64::from(score);
                positives += 1;
                pending_positive = Some(score);
            } else {
                negative += f64::from(score);
                negatives += 1;
                if let Some(value) = pending_positive.take() {
                    ordered += u64::from(value > score);
                    pairs += 1;
                }
            }
        }
    }
    let mean_positive = positive / positives.max(1) as f64;
    let mean_negative = negative / negatives.max(1) as f64;
    Ok(TrainScoreReceipt {
        score_blake3: format_compact!("b3-{}", hash.finalize().to_hex()),
        binary_cross_entropy: loss / examples.len().max(1) as f64,
        mean_positive_score: mean_positive,
        mean_negative_score: mean_negative,
        mean_positive_negative_margin: mean_positive - mean_negative,
        correctly_ordered_pair_fraction: ordered as f64 / pairs.max(1) as f64,
        examples: examples.len() as u64,
    })
}

pub(crate) fn structural_slices(
    source: &ExternalDatasetMapped,
    ranks: &[HyperRelationalQueryRank],
    candidate_count: u64,
    base_relations: u32,
) -> Result<StructuralValidationSlices, CandleTrainerError> {
    let mut relation_frequency = vec![0_u64; base_relations as usize];
    let mut degree = vec![0_u64; source.manifest().entities as usize];
    for fact in source
        .facts()?
        .iter()
        .copied()
        .filter(|fact| fact.split() == ExternalFactSplit::Train as u8)
    {
        relation_frequency[fact.predicate() as usize] += 1;
        degree[fact.subject() as usize] += 1;
        degree[fact.object() as usize] += 1;
    }
    let mut relation = vec![MetricAccumulator::default(); BUCKETS.len() + 1];
    let mut entity = vec![MetricAccumulator::default(); BUCKETS.len() + 1];
    for rank in ranks {
        relation[bucket(relation_frequency[(rank.relation % base_relations) as usize])]
            .push(rank.doubled_rank, candidate_count);
        entity[bucket(degree[rank.target as usize])].push(rank.doubled_rank, candidate_count);
    }
    Ok(StructuralValidationSlices {
        relation_frequency: finish_buckets(relation, "train-relation-frequency"),
        target_entity_degree: finish_buckets(entity, "train-target-degree"),
    })
}

pub(crate) fn write_ranks(
    root: &Path,
    ranks: &[HyperRelationalQueryRank],
) -> Result<RankArtifactReceipt, CandleTrainerError> {
    let mut bytes = Vec::with_capacity(16 + ranks.len() * 8);
    bytes.extend_from_slice(RANK_MAGIC);
    bytes.extend_from_slice(&(ranks.len() as u64).to_le_bytes());
    for rank in ranks {
        bytes.extend_from_slice(&rank.doubled_rank.to_le_bytes());
    }
    let digest = format_compact!("b3-{}", blake3::hash(&bytes).to_hex());
    let file = format_compact!("{digest}.ranks.bin");
    write_immutable(&root.join(file.as_str()), &bytes)?;
    Ok(RankArtifactReceipt {
        file,
        blake3: digest,
        bytes: bytes.len() as u64,
        queries: ranks.len() as u64,
    })
}

pub(crate) fn write_causal_deltas(
    root: &Path,
    comp: &[HyperRelationalQueryRank],
    null: &[HyperRelationalQueryRank],
    value: &[HyperRelationalQueryRank],
    full: &[HyperRelationalQueryRank],
) -> Result<CausalRankArtifactReceipt, CandleTrainerError> {
    if comp.len() != null.len() || comp.len() != value.len() || comp.len() != full.len() {
        return Err(CandleTrainerError::Contract("envelope rank shape"));
    }
    let pairs = [
        (
            EnvelopeArm::QualifierGradientNull,
            EnvelopeArm::Compgcn,
            null,
            comp,
        ),
        (
            EnvelopeArm::FullStare,
            EnvelopeArm::QualifierGradientNull,
            full,
            null,
        ),
        (EnvelopeArm::ValueOnly, EnvelopeArm::Compgcn, value, comp),
    ];
    let mut bytes = Vec::with_capacity(16 + comp.len() * pairs.len() * 8);
    bytes.extend_from_slice(DELTA_MAGIC);
    bytes.extend_from_slice(&(comp.len() as u64).to_le_bytes());
    let mut comparisons = Vec::with_capacity(pairs.len());
    for (left_arm, right_arm, left, right) in pairs {
        let mut wins = 0_u64;
        let mut losses = 0_u64;
        let mut ties = 0_u64;
        let mut mrr_delta = 0.0_f64;
        for (left, right) in left.iter().zip(right) {
            let delta = left.doubled_rank as i64 - right.doubled_rank as i64;
            bytes.extend_from_slice(&delta.to_le_bytes());
            wins += u64::from(delta < 0);
            losses += u64::from(delta > 0);
            ties += u64::from(delta == 0);
            mrr_delta += 2.0 / left.doubled_rank as f64 - 2.0 / right.doubled_rank as f64;
        }
        comparisons.push(PairedRankDeltaReceipt {
            left: left_arm,
            right: right_arm,
            wins,
            losses,
            ties,
            mean_reciprocal_rank_delta: mrr_delta / comp.len().max(1) as f64,
        });
    }
    let digest = format_compact!("b3-{}", blake3::hash(&bytes).to_hex());
    let file = format_compact!("{digest}.rank-deltas.bin");
    write_immutable(&root.join(file.as_str()), &bytes)?;
    Ok(CausalRankArtifactReceipt {
        file,
        blake3: digest,
        bytes: bytes.len() as u64,
        queries: comp.len() as u64,
        comparisons,
    })
}

#[derive(Clone, Copy, Default)]
struct MetricAccumulator {
    reciprocal_rank: f64,
    hits: [u64; 4],
    queries: u64,
    candidates: u64,
}

impl MetricAccumulator {
    fn push(&mut self, doubled_rank: u64, candidates: u64) {
        let rank = doubled_rank as f64 * 0.5;
        self.reciprocal_rank += rank.recip();
        for (hit, threshold) in self.hits.iter_mut().zip([1.0, 3.0, 5.0, 10.0]) {
            *hit += u64::from(rank <= threshold);
        }
        self.queries += 1;
        self.candidates += candidates;
    }
    fn finish(self) -> HyperRelationalRankingMetrics {
        if self.queries == 0 {
            return empty_metrics();
        }
        let count = self.queries as f64;
        HyperRelationalRankingMetrics {
            mean_reciprocal_rank: self.reciprocal_rank / count,
            hits_at_1: self.hits[0] as f64 / count,
            hits_at_3: self.hits[1] as f64 / count,
            hits_at_5: self.hits[2] as f64 / count,
            hits_at_10: self.hits[3] as f64 / count,
            queries: self.queries,
            candidates_scored: self.candidates,
        }
    }
}

fn bucket(value: u64) -> usize {
    BUCKETS
        .iter()
        .position(|limit| value < *limit)
        .unwrap_or(BUCKETS.len())
}

fn finish_buckets(values: Vec<MetricAccumulator>, prefix: &str) -> Vec<HyperRelationalMetricSlice> {
    values
        .into_iter()
        .enumerate()
        .filter(|(_, value)| value.queries != 0)
        .map(|(index, value)| HyperRelationalMetricSlice {
            label: if index == 0 {
                format_compact!("{prefix}-0")
            } else if index == BUCKETS.len() {
                format_compact!("{prefix}-{}-plus", BUCKETS[index - 1])
            } else {
                format_compact!("{prefix}-{}-{}", BUCKETS[index - 1], BUCKETS[index] - 1)
            },
            metrics: value.finish(),
        })
        .collect()
}

fn write_immutable(path: &Path, bytes: &[u8]) -> Result<(), CandleTrainerError> {
    if path.exists() {
        if std::fs::read(path)? == bytes {
            return Ok(());
        }
        return Err(CandleTrainerError::Contract(
            "immutable envelope artifact collision",
        ));
    }
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
