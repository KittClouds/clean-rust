use crate::link_prediction_artifact::QueryRecord;
use crate::link_prediction_eval::{
    certificate, filtered_average_tie_ranks_checked, LinkPredictionEvaluationProfile,
    ProfiledLinkPredictionEvaluation,
};
use crate::{
    FilteredRankingMetrics, LinkPredictionError, LinkPredictionQueryView,
    LinkPredictionScoreCertificate, LinkPredictionSplit, LinkPredictionTaskMapped,
    LINK_PREDICTION_SCORE_PREFIX_BYTES,
};
use rayon::prelude::*;
use std::mem::size_of;
use std::time::{Duration, Instant};
use zerocopy::AsBytes;

pub const LINK_PREDICTION_SCORE_PREFIX_WORDS: usize =
    LINK_PREDICTION_SCORE_PREFIX_BYTES / size_of::<f32>();

pub struct CanonicalScoreMatrixMut<'a> {
    arena: &'a mut [f32],
    rows: usize,
    candidates: usize,
    row_words: usize,
}

impl<'a> CanonicalScoreMatrixMut<'a> {
    pub fn rows(&self) -> usize {
        self.rows
    }

    pub fn candidates(&self) -> usize {
        self.candidates
    }

    pub fn row_mut(&mut self, row: usize) -> Option<&mut [f32]> {
        if row >= self.rows {
            return None;
        }
        let start = row * self.row_words + LINK_PREDICTION_SCORE_PREFIX_WORDS;
        self.arena.get_mut(start..start + self.candidates)
    }

    pub(crate) fn into_layout(self) -> (&'a mut [f32], usize, usize) {
        (
            self.arena,
            self.row_words,
            LINK_PREDICTION_SCORE_PREFIX_WORDS,
        )
    }
}

pub fn link_prediction_canonical_arena_bytes(
    candidate_count: u64,
    batch_size: usize,
) -> Option<u64> {
    candidate_count
        .checked_add(LINK_PREDICTION_SCORE_PREFIX_WORDS as u64)?
        .checked_mul(size_of::<f32>() as u64)?
        .checked_mul(batch_size as u64)
}

pub fn evaluate_link_prediction_validation_canonical_batched<F>(
    task: &LinkPredictionTaskMapped,
    model_id: &str,
    batch_size: usize,
    scorer: F,
) -> Result<LinkPredictionScoreCertificate, LinkPredictionError>
where
    F: FnMut(&[LinkPredictionQueryView], &[u32], CanonicalScoreMatrixMut<'_>) -> Result<(), String>,
{
    evaluate_validation_canonical_batched(task, model_id, batch_size, None, scorer)
}

pub fn evaluate_link_prediction_validation_canonical_batched_profiled<F>(
    task: &LinkPredictionTaskMapped,
    model_id: &str,
    batch_size: usize,
    scorer: F,
) -> Result<ProfiledLinkPredictionEvaluation, LinkPredictionError>
where
    F: FnMut(&[LinkPredictionQueryView], &[u32], CanonicalScoreMatrixMut<'_>) -> Result<(), String>,
{
    let mut profile = LinkPredictionEvaluationProfile::default();
    let certificate = evaluate_validation_canonical_batched(
        task,
        model_id,
        batch_size,
        Some(&mut profile),
        scorer,
    )?;
    Ok(ProfiledLinkPredictionEvaluation {
        certificate,
        profile,
    })
}

fn evaluate_validation_canonical_batched<F>(
    task: &LinkPredictionTaskMapped,
    model_id: &str,
    batch_size: usize,
    mut profile: Option<&mut LinkPredictionEvaluationProfile>,
    mut scorer: F,
) -> Result<LinkPredictionScoreCertificate, LinkPredictionError>
where
    F: FnMut(&[LinkPredictionQueryView], &[u32], CanonicalScoreMatrixMut<'_>) -> Result<(), String>,
{
    let evaluator_started = profile.as_ref().map(|_| Instant::now());
    if cfg!(not(target_endian = "little")) || model_id.is_empty() || batch_size == 0 {
        return Err(LinkPredictionError::InvalidInput(
            "canonical single-arena evaluator",
        ));
    }
    let candidate_count = task.manifest().candidate_universe as usize;
    let candidates = (0..task.manifest().candidate_universe).collect::<Vec<_>>();
    let queries = task.queries(LinkPredictionSplit::Validation)?;
    let conflicts = task.conflicts()?;
    let max_positives = queries
        .iter()
        .map(|record| record.conflict_count() as usize)
        .max()
        .ok_or(LinkPredictionError::CorruptArtifact("empty split"))?;
    let row_words = candidate_count
        .checked_add(LINK_PREDICTION_SCORE_PREFIX_WORDS)
        .ok_or(LinkPredictionError::InvalidInput("batch size"))?;
    let arena_words = batch_size
        .checked_mul(row_words)
        .ok_or(LinkPredictionError::InvalidInput("batch size"))?;
    let rank_elements = batch_size
        .checked_mul(max_positives)
        .ok_or(LinkPredictionError::InvalidInput("batch size"))?;
    let mut arena = vec![0.0_f32; arena_words];
    let mut views = Vec::with_capacity(batch_size);
    let mut optimistic = vec![0_u64; rank_elements];
    let mut pessimistic = vec![0_u64; rank_elements];
    let mut ranks = vec![0.0_f64; rank_elements];
    let mut score_hasher = blake3::Hasher::new();
    let mut reciprocal_rank_sum = 0.0_f64;
    let mut hits_at_1 = 0_u64;
    let mut hits_at_3 = 0_u64;
    let mut hits_at_10 = 0_u64;
    let mut positives = 0_u64;

    for records in queries.chunks(batch_size) {
        if let Some(profile) = profile.as_deref_mut() {
            profile.batches = profile.batches.saturating_add(1);
        }
        views.clear();
        views.extend(records.iter().map(|record| LinkPredictionQueryView {
            observed_at: record.observed_at(),
            source: record.source(),
            relation: record.relation(),
            split: LinkPredictionSplit::Validation,
            inverse: record.inverse(),
        }));
        let active_arena = &mut arena[..records.len() * row_words];
        let prefix_started = profile.as_ref().map(|_| Instant::now());
        install_prefixes(records, active_arena, row_words);
        if let (Some(profile), Some(started)) = (profile.as_deref_mut(), prefix_started) {
            add_elapsed(&mut profile.prefix_installation_micros, started.elapsed());
        }
        let scorer_started = profile.as_ref().map(|_| Instant::now());
        scorer(
            &views,
            &candidates,
            CanonicalScoreMatrixMut {
                arena: active_arena,
                rows: records.len(),
                candidates: candidate_count,
                row_words,
            },
        )
        .map_err(LinkPredictionError::Scorer)?;
        if let (Some(profile), Some(started)) = (profile.as_deref_mut(), scorer_started) {
            add_elapsed(&mut profile.scorer_micros, started.elapsed());
        }

        let active_ranks = &mut ranks[..records.len() * max_positives];
        let active_optimistic = &mut optimistic[..records.len() * max_positives];
        let active_pessimistic = &mut pessimistic[..records.len() * max_positives];
        let profiling = profile.is_some();
        let join_started = profiling.then(Instant::now);
        let mut hash_elapsed = Duration::ZERO;
        let mut ranking_elapsed = Duration::ZERO;
        let ((), rank_result) = rayon::join(
            || {
                let started = profiling.then(Instant::now);
                score_hasher.update_rayon(active_arena.as_bytes());
                if let Some(started) = started {
                    hash_elapsed = started.elapsed();
                }
            },
            || {
                let started = profiling.then(Instant::now);
                let result = records
                    .par_iter()
                    .zip(active_arena.par_chunks(row_words))
                    .zip(active_optimistic.par_chunks_mut(max_positives))
                    .zip(active_pessimistic.par_chunks_mut(max_positives))
                    .zip(active_ranks.par_chunks_mut(max_positives))
                    .try_for_each(|((((record, row), optimistic), pessimistic), ranks)| {
                        let start = record.conflict_offset() as usize;
                        let end = start
                            .checked_add(record.conflict_count() as usize)
                            .ok_or(LinkPredictionError::CorruptArtifact("conflict range"))?;
                        let filtered = conflicts
                            .get(start..end)
                            .ok_or(LinkPredictionError::CorruptArtifact("conflict range"))?;
                        filtered_average_tie_ranks_checked(
                            &row[LINK_PREDICTION_SCORE_PREFIX_WORDS..],
                            filtered,
                            optimistic,
                            pessimistic,
                            ranks,
                            true,
                        )
                    });
                if let Some(started) = started {
                    ranking_elapsed = started.elapsed();
                }
                result
            },
        );
        if let Some(profile) = profile.as_deref_mut() {
            add_elapsed(&mut profile.hash_micros, hash_elapsed);
            add_elapsed(&mut profile.ranking_micros, ranking_elapsed);
            if let Some(started) = join_started {
                add_elapsed(&mut profile.hash_rank_join_micros, started.elapsed());
            }
        }
        rank_result?;
        let metric_started = profile.as_ref().map(|_| Instant::now());
        for (row, record) in records.iter().enumerate() {
            let count = record.conflict_count() as usize;
            for rank in &active_ranks[row * max_positives..row * max_positives + count] {
                reciprocal_rank_sum += rank.recip();
                hits_at_1 += u64::from(*rank <= 1.0);
                hits_at_3 += u64::from(*rank <= 3.0);
                hits_at_10 += u64::from(*rank <= 10.0);
                positives += 1;
            }
        }
        if let (Some(profile), Some(started)) = (profile.as_deref_mut(), metric_started) {
            add_elapsed(&mut profile.metric_accumulation_micros, started.elapsed());
        }
    }
    if positives == 0 {
        return Err(LinkPredictionError::CorruptArtifact("empty split"));
    }
    let query_count = queries.len() as u64;
    let denominator = positives as f64;
    let result = certificate(
        task.manifest().task_id.as_str(),
        model_id,
        LinkPredictionSplit::Validation,
        format!("b3-{}", score_hasher.finalize().to_hex()),
        FilteredRankingMetrics {
            mean_reciprocal_rank: reciprocal_rank_sum / denominator,
            hits_at_1: hits_at_1 as f64 / denominator,
            hits_at_3: hits_at_3 as f64 / denominator,
            hits_at_10: hits_at_10 as f64 / denominator,
            queries: query_count,
            positives,
            candidates_scored: query_count.saturating_mul(candidate_count as u64),
        },
    )?;
    if let (Some(profile), Some(started)) = (profile, evaluator_started) {
        profile.evaluator_micros = elapsed_micros(started.elapsed());
    }
    Ok(result)
}

fn install_prefixes(records: &[QueryRecord], arena: &mut [f32], row_words: usize) {
    records
        .par_iter()
        .zip(arena.par_chunks_mut(row_words))
        .for_each(|(record, row)| {
            let prefix = row[..LINK_PREDICTION_SCORE_PREFIX_WORDS].as_bytes_mut();
            prefix[..8].copy_from_slice(&record.observed_at().to_le_bytes());
            prefix[8..12].copy_from_slice(&record.source().to_le_bytes());
            prefix[12..].copy_from_slice(&record.relation().to_le_bytes());
        });
}

fn elapsed_micros(duration: Duration) -> u64 {
    duration.as_micros().try_into().unwrap_or(u64::MAX)
}

fn add_elapsed(total: &mut u64, duration: Duration) {
    *total = total.saturating_add(elapsed_micros(duration));
}
