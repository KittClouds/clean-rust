use crate::link_prediction_artifact::QueryRecord;
use crate::{
    FilteredRankingMetrics, LinkPredictionError, LinkPredictionQueryView,
    LinkPredictionScoreCertificate, LinkPredictionSplit, LinkPredictionTaskMapped,
    LinkPredictionTestLock, LinkPredictionTestLockInput, LinkPredictionTestLockPaths,
    LinkPredictionTestResultPaths, LINK_PREDICTION_SCORE_SCHEMA, LINK_PREDICTION_TEST_LOCK_SCHEMA,
};
use rayon::prelude::*;
use std::fs::OpenOptions;
use std::io::Write;
use std::mem::size_of;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
use wide::{f32x8, CmpGe, CmpGt};
use zerocopy::AsBytes;

pub const DEFAULT_LINK_PREDICTION_QUERY_BATCH: usize = 64;
pub const LINK_PREDICTION_SCORE_PREFIX_BYTES: usize = 16;

#[derive(Clone, Debug, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LinkPredictionEvaluationProfile {
    pub batches: u64,
    pub prefix_installation_micros: u64,
    pub scorer_micros: u64,
    pub stream_composition_micros: u64,
    pub hash_micros: u64,
    pub ranking_micros: u64,
    pub hash_rank_join_micros: u64,
    pub metric_accumulation_micros: u64,
    pub evaluator_micros: u64,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProfiledLinkPredictionEvaluation {
    pub certificate: LinkPredictionScoreCertificate,
    pub profile: LinkPredictionEvaluationProfile,
}

pub fn link_prediction_hash_buffer_bytes(candidate_count: u64, batch_size: usize) -> Option<u64> {
    candidate_count
        .checked_mul(size_of::<f32>() as u64)?
        .checked_add(LINK_PREDICTION_SCORE_PREFIX_BYTES as u64)?
        .checked_mul(batch_size as u64)
}

pub fn evaluate_link_prediction_validation<F>(
    task: &LinkPredictionTaskMapped,
    model_id: &str,
    scorer: F,
) -> Result<LinkPredictionScoreCertificate, LinkPredictionError>
where
    F: FnMut(LinkPredictionQueryView, &[u32], &mut [f32]) -> Result<(), String>,
{
    evaluate_split(task, model_id, LinkPredictionSplit::Validation, scorer)
}

pub fn evaluate_link_prediction_validation_batched<F>(
    task: &LinkPredictionTaskMapped,
    model_id: &str,
    batch_size: usize,
    scorer: F,
) -> Result<LinkPredictionScoreCertificate, LinkPredictionError>
where
    F: FnMut(&[LinkPredictionQueryView], &[u32], &mut [f32]) -> Result<(), String>,
{
    evaluate_split_batched(
        task,
        model_id,
        LinkPredictionSplit::Validation,
        batch_size,
        None,
        scorer,
    )
}

pub fn evaluate_link_prediction_validation_batched_profiled<F>(
    task: &LinkPredictionTaskMapped,
    model_id: &str,
    batch_size: usize,
    scorer: F,
) -> Result<ProfiledLinkPredictionEvaluation, LinkPredictionError>
where
    F: FnMut(&[LinkPredictionQueryView], &[u32], &mut [f32]) -> Result<(), String>,
{
    let mut profile = LinkPredictionEvaluationProfile::default();
    let certificate = evaluate_split_batched(
        task,
        model_id,
        LinkPredictionSplit::Validation,
        batch_size,
        Some(&mut profile),
        scorer,
    )?;
    Ok(ProfiledLinkPredictionEvaluation {
        certificate,
        profile,
    })
}

pub fn create_link_prediction_test_lock(
    task: &LinkPredictionTaskMapped,
    input: &LinkPredictionTestLockInput,
    root: impl AsRef<Path>,
) -> Result<LinkPredictionTestLockPaths, LinkPredictionError> {
    if input.task_id != task.manifest().task_id
        || input.selection_ledger_id.is_empty()
        || input.selected_model_id.is_empty()
        || input.validation_certificate_id.is_empty()
    {
        return Err(LinkPredictionError::InvalidInput("test lock input"));
    }
    let lock_id = lock_identity(input)?;
    let lock = LinkPredictionTestLock {
        schema_version: LINK_PREDICTION_TEST_LOCK_SCHEMA.into(),
        lock_id: lock_id.as_str().into(),
        task_id: input.task_id.clone(),
        selection_ledger_id: input.selection_ledger_id.clone(),
        selected_model_id: input.selected_model_id.clone(),
        validation_certificate_id: input.validation_certificate_id.clone(),
    };
    let root = root.as_ref();
    std::fs::create_dir_all(root)?;
    let receipt = root.join(format!("{lock_id}.test-lock.json"));
    write_new_durable(&receipt, &serde_json::to_vec_pretty(&lock)?)?;
    Ok(LinkPredictionTestLockPaths {
        receipt,
        lock_id: lock_id.into(),
    })
}

pub fn evaluate_locked_link_prediction_test<F>(
    task: &LinkPredictionTaskMapped,
    lock_receipt: impl AsRef<Path>,
    output_root: impl AsRef<Path>,
    scorer: F,
) -> Result<LinkPredictionTestResultPaths, LinkPredictionError>
where
    F: FnMut(LinkPredictionQueryView, &[u32], &mut [f32]) -> Result<(), String>,
{
    let (lock, root, claim) = claim_locked_test(task, lock_receipt, output_root)?;
    let certificate = evaluate_split(
        task,
        lock.selected_model_id.as_str(),
        LinkPredictionSplit::Test,
        scorer,
    )?;
    let certificate_path = root.join(format!("{}.test-score.json", certificate.certificate_id));
    write_new_durable(&certificate_path, &serde_json::to_vec_pretty(&certificate)?)?;
    Ok(LinkPredictionTestResultPaths {
        claim,
        certificate: certificate_path,
    })
}

pub fn evaluate_locked_link_prediction_test_batched<F>(
    task: &LinkPredictionTaskMapped,
    lock_receipt: impl AsRef<Path>,
    output_root: impl AsRef<Path>,
    batch_size: usize,
    scorer: F,
) -> Result<LinkPredictionTestResultPaths, LinkPredictionError>
where
    F: FnMut(&[LinkPredictionQueryView], &[u32], &mut [f32]) -> Result<(), String>,
{
    let (lock, root, claim) = claim_locked_test(task, lock_receipt, output_root)?;
    let certificate = evaluate_split_batched(
        task,
        lock.selected_model_id.as_str(),
        LinkPredictionSplit::Test,
        batch_size,
        None,
        scorer,
    )?;
    let certificate_path = root.join(format!("{}.test-score.json", certificate.certificate_id));
    write_new_durable(&certificate_path, &serde_json::to_vec_pretty(&certificate)?)?;
    Ok(LinkPredictionTestResultPaths {
        claim,
        certificate: certificate_path,
    })
}

fn claim_locked_test(
    task: &LinkPredictionTaskMapped,
    lock_receipt: impl AsRef<Path>,
    output_root: impl AsRef<Path>,
) -> Result<(LinkPredictionTestLock, PathBuf, PathBuf), LinkPredictionError> {
    let lock: LinkPredictionTestLock =
        serde_json::from_slice(&std::fs::read(lock_receipt.as_ref())?)?;
    validate_lock(task, &lock)?;
    let root = output_root.as_ref().to_path_buf();
    std::fs::create_dir_all(&root)?;
    let claim = root.join(format!("{}.test-claimed.json", lock.task_id));
    let claim_body = serde_json::to_vec_pretty(&(
        LINK_PREDICTION_TEST_LOCK_SCHEMA,
        lock.lock_id.as_str(),
        lock.task_id.as_str(),
        lock.selected_model_id.as_str(),
    ))?;
    match write_new_durable(&claim, &claim_body) {
        Err(LinkPredictionError::Io(error))
            if error.kind() == std::io::ErrorKind::AlreadyExists =>
        {
            return Err(LinkPredictionError::TestAlreadyClaimed(claim));
        }
        Err(error) => return Err(error),
        Ok(()) => {}
    }
    Ok((lock, root, claim))
}

fn evaluate_split<F>(
    task: &LinkPredictionTaskMapped,
    model_id: &str,
    split: LinkPredictionSplit,
    mut scorer: F,
) -> Result<LinkPredictionScoreCertificate, LinkPredictionError>
where
    F: FnMut(LinkPredictionQueryView, &[u32], &mut [f32]) -> Result<(), String>,
{
    if model_id.is_empty() {
        return Err(LinkPredictionError::InvalidInput("model identity"));
    }
    let candidate_count = task.manifest().candidate_universe as usize;
    let candidates = (0..task.manifest().candidate_universe).collect::<Vec<_>>();
    let mut scores = vec![0.0_f32; candidate_count];
    let queries = task.queries(split)?;
    let conflicts = task.conflicts()?;
    let mut score_hasher = blake3::Hasher::new();
    let mut reciprocal_rank_sum = 0.0_f64;
    let mut hits_at_1 = 0_u64;
    let mut hits_at_3 = 0_u64;
    let mut hits_at_10 = 0_u64;
    let mut positives = 0_u64;

    for record in queries.iter().copied() {
        let query = LinkPredictionQueryView {
            observed_at: record.observed_at(),
            source: record.source(),
            relation: record.relation(),
            split,
            inverse: record.inverse(),
        };
        scorer(query, &candidates, &mut scores).map_err(LinkPredictionError::Scorer)?;
        if scores.iter().any(|score| !score.is_finite()) {
            return Err(LinkPredictionError::Scorer(
                "scorer returned non-finite score".to_owned(),
            ));
        }
        score_hasher.update(&record.observed_at().to_le_bytes());
        score_hasher.update(&record.source().to_le_bytes());
        score_hasher.update(&record.relation().to_le_bytes());
        hash_scores(&mut score_hasher, &scores);
        let start = record.conflict_offset() as usize;
        let end = start
            .checked_add(record.conflict_count() as usize)
            .ok_or(LinkPredictionError::CorruptArtifact("conflict range"))?;
        let filtered = conflicts
            .get(start..end)
            .ok_or(LinkPredictionError::CorruptArtifact("conflict range"))?;
        for destination in filtered.iter().copied().map(|value| value.get()) {
            let positive_score = scores[destination as usize];
            let rank = filtered_average_tie_rank(&scores, filtered, positive_score)?;
            reciprocal_rank_sum += rank.recip();
            hits_at_1 += u64::from(rank <= 1.0);
            hits_at_3 += u64::from(rank <= 3.0);
            hits_at_10 += u64::from(rank <= 10.0);
            positives += 1;
        }
    }
    if positives == 0 {
        return Err(LinkPredictionError::CorruptArtifact("empty split"));
    }
    let query_count = queries.len() as u64;
    let denominator = positives as f64;
    let metrics = FilteredRankingMetrics {
        mean_reciprocal_rank: reciprocal_rank_sum / denominator,
        hits_at_1: hits_at_1 as f64 / denominator,
        hits_at_3: hits_at_3 as f64 / denominator,
        hits_at_10: hits_at_10 as f64 / denominator,
        queries: query_count,
        positives,
        candidates_scored: query_count.saturating_mul(candidate_count as u64),
    };
    certificate(
        task.manifest().task_id.as_str(),
        model_id,
        split,
        format!("b3-{}", score_hasher.finalize().to_hex()),
        metrics,
    )
}

fn evaluate_split_batched<F>(
    task: &LinkPredictionTaskMapped,
    model_id: &str,
    split: LinkPredictionSplit,
    batch_size: usize,
    mut profile: Option<&mut LinkPredictionEvaluationProfile>,
    mut scorer: F,
) -> Result<LinkPredictionScoreCertificate, LinkPredictionError>
where
    F: FnMut(&[LinkPredictionQueryView], &[u32], &mut [f32]) -> Result<(), String>,
{
    let evaluator_started = profile.as_ref().map(|_| Instant::now());
    if model_id.is_empty() || batch_size == 0 {
        return Err(LinkPredictionError::InvalidInput("batched evaluator"));
    }
    let candidate_count = task.manifest().candidate_universe as usize;
    let candidates = (0..task.manifest().candidate_universe).collect::<Vec<_>>();
    let queries = task.queries(split)?;
    let conflicts = task.conflicts()?;
    let max_positives = queries
        .iter()
        .map(|record| record.conflict_count() as usize)
        .max()
        .ok_or(LinkPredictionError::CorruptArtifact("empty split"))?;
    let score_elements = batch_size
        .checked_mul(candidate_count)
        .ok_or(LinkPredictionError::InvalidInput("batch size"))?;
    let rank_elements = batch_size
        .checked_mul(max_positives)
        .ok_or(LinkPredictionError::InvalidInput("batch size"))?;
    let mut scores = vec![0.0_f32; score_elements];
    let mut views = Vec::with_capacity(batch_size);
    let mut optimistic = vec![0_u64; rank_elements];
    let mut pessimistic = vec![0_u64; rank_elements];
    let mut ranks = vec![0.0_f64; rank_elements];
    let hash_record_bytes = candidate_count
        .checked_mul(size_of::<f32>())
        .and_then(|bytes| bytes.checked_add(LINK_PREDICTION_SCORE_PREFIX_BYTES))
        .ok_or(LinkPredictionError::InvalidInput("batch size"))?;
    let hash_elements = batch_size
        .checked_mul(hash_record_bytes)
        .ok_or(LinkPredictionError::InvalidInput("batch size"))?;
    let mut hash_buffer = vec![0_u8; hash_elements];
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
            split,
            inverse: record.inverse(),
        }));
        let active_scores = &mut scores[..records.len() * candidate_count];
        let scorer_started = profile.as_ref().map(|_| Instant::now());
        scorer(&views, &candidates, active_scores).map_err(LinkPredictionError::Scorer)?;
        if let (Some(profile), Some(started)) = (profile.as_deref_mut(), scorer_started) {
            add_elapsed(&mut profile.scorer_micros, started.elapsed());
        }
        let active_hash_buffer = &mut hash_buffer[..records.len() * hash_record_bytes];
        let composition_started = profile.as_ref().map(|_| Instant::now());
        if !compose_score_hash_batch(
            records,
            active_scores,
            candidate_count,
            hash_record_bytes,
            active_hash_buffer,
        ) {
            return Err(LinkPredictionError::Scorer(
                "scorer returned non-finite score".to_owned(),
            ));
        }
        if let (Some(profile), Some(started)) = (profile.as_deref_mut(), composition_started) {
            add_elapsed(&mut profile.stream_composition_micros, started.elapsed());
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
                score_hasher.update_rayon(active_hash_buffer);
                if let Some(started) = started {
                    hash_elapsed = started.elapsed();
                }
            },
            || {
                let started = profiling.then(Instant::now);
                let result = records
                    .par_iter()
                    .zip(active_scores.par_chunks(candidate_count))
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
                        filtered_average_tie_ranks(row, filtered, optimistic, pessimistic, ranks)
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
    let certificate = certificate(
        task.manifest().task_id.as_str(),
        model_id,
        split,
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
    Ok(certificate)
}

fn elapsed_micros(duration: Duration) -> u64 {
    duration.as_micros().try_into().unwrap_or(u64::MAX)
}

fn add_elapsed(total: &mut u64, duration: Duration) {
    *total = total.saturating_add(elapsed_micros(duration));
}

fn compose_score_hash_batch(
    records: &[QueryRecord],
    scores: &[f32],
    candidate_count: usize,
    hash_record_bytes: usize,
    output: &mut [u8],
) -> bool {
    records
        .par_iter()
        .zip(scores.par_chunks(candidate_count))
        .zip(output.par_chunks_mut(hash_record_bytes))
        .all(|((record, row), bytes)| {
            bytes[..8].copy_from_slice(&record.observed_at().to_le_bytes());
            bytes[8..12].copy_from_slice(&record.source().to_le_bytes());
            bytes[12..LINK_PREDICTION_SCORE_PREFIX_BYTES]
                .copy_from_slice(&record.relation().to_le_bytes());
            copy_score_bytes(row, &mut bytes[LINK_PREDICTION_SCORE_PREFIX_BYTES..]);
            row.iter().all(|score| score.is_finite())
        })
}

#[cfg(target_endian = "little")]
fn copy_score_bytes(scores: &[f32], output: &mut [u8]) {
    output.copy_from_slice(scores.as_bytes());
}

#[cfg(not(target_endian = "little"))]
fn copy_score_bytes(scores: &[f32], output: &mut [u8]) {
    for (score, bytes) in scores.iter().zip(output.chunks_exact_mut(size_of::<f32>())) {
        bytes.copy_from_slice(&score.to_bits().to_le_bytes());
    }
}

#[cfg(target_endian = "little")]
fn hash_scores(hasher: &mut blake3::Hasher, scores: &[f32]) {
    hasher.update(scores.as_bytes());
}

#[cfg(not(target_endian = "little"))]
fn hash_scores(hasher: &mut blake3::Hasher, scores: &[f32]) {
    for score in scores {
        hasher.update(&score.to_bits().to_le_bytes());
    }
}

fn filtered_average_tie_rank(
    scores: &[f32],
    filtered: &[crate::link_prediction_artifact::LeU32],
    positive_score: f32,
) -> Result<f64, LinkPredictionError> {
    let positive = f32x8::splat(positive_score);
    let mut optimistic = 0_u64;
    let mut pessimistic = 0_u64;
    let mut chunks = scores.chunks_exact(8);
    for chunk in &mut chunks {
        let lanes = f32x8::from(
            <[f32; 8]>::try_from(chunk)
                .map_err(|_| LinkPredictionError::CorruptArtifact("SIMD score chunk"))?,
        );
        optimistic += u64::from(lanes.cmp_gt(positive).move_mask().count_ones());
        pessimistic += u64::from(lanes.cmp_ge(positive).move_mask().count_ones());
    }
    for score in chunks.remainder() {
        optimistic += u64::from(*score > positive_score);
        pessimistic += u64::from(*score >= positive_score);
    }
    for destination in filtered.iter().copied().map(|value| value.get()) {
        let score = *scores
            .get(destination as usize)
            .ok_or(LinkPredictionError::CorruptArtifact("conflict destination"))?;
        optimistic -= u64::from(score > positive_score);
        pessimistic -= u64::from(score >= positive_score);
    }
    Ok(0.5 * (optimistic + pessimistic) as f64 + 1.0)
}

pub(crate) fn filtered_average_tie_ranks(
    scores: &[f32],
    filtered: &[crate::link_prediction_artifact::LeU32],
    optimistic: &mut [u64],
    pessimistic: &mut [u64],
    ranks: &mut [f64],
) -> Result<(), LinkPredictionError> {
    filtered_average_tie_ranks_checked(scores, filtered, optimistic, pessimistic, ranks, false)
}

pub(crate) fn filtered_average_tie_ranks_checked(
    scores: &[f32],
    filtered: &[crate::link_prediction_artifact::LeU32],
    optimistic: &mut [u64],
    pessimistic: &mut [u64],
    ranks: &mut [f64],
    validate_finite: bool,
) -> Result<(), LinkPredictionError> {
    let count = filtered.len();
    if optimistic.len() < count || pessimistic.len() < count || ranks.len() < count {
        return Err(LinkPredictionError::CorruptArtifact("rank scratch"));
    }
    optimistic[..count].fill(0);
    pessimistic[..count].fill(0);
    for (rank, destination) in ranks.iter_mut().zip(filtered.iter().copied()) {
        *rank = f64::from(
            *scores
                .get(destination.get() as usize)
                .ok_or(LinkPredictionError::CorruptArtifact("conflict destination"))?,
        );
    }
    let mut chunks = scores.chunks_exact(8);
    for chunk in &mut chunks {
        if validate_finite && chunk.iter().any(|score| !score.is_finite()) {
            return Err(LinkPredictionError::Scorer(
                "scorer returned non-finite score".to_owned(),
            ));
        }
        let lanes = f32x8::from(
            <[f32; 8]>::try_from(chunk)
                .map_err(|_| LinkPredictionError::CorruptArtifact("SIMD score chunk"))?,
        );
        for positive in 0..count {
            let threshold = f32x8::splat(ranks[positive] as f32);
            optimistic[positive] += u64::from(lanes.cmp_gt(threshold).move_mask().count_ones());
            pessimistic[positive] += u64::from(lanes.cmp_ge(threshold).move_mask().count_ones());
        }
    }
    for score in chunks.remainder() {
        if validate_finite && !score.is_finite() {
            return Err(LinkPredictionError::Scorer(
                "scorer returned non-finite score".to_owned(),
            ));
        }
        for positive in 0..count {
            let threshold = ranks[positive] as f32;
            optimistic[positive] += u64::from(*score > threshold);
            pessimistic[positive] += u64::from(*score >= threshold);
        }
    }
    for destination in filtered.iter().copied() {
        let score = *scores
            .get(destination.get() as usize)
            .ok_or(LinkPredictionError::CorruptArtifact("conflict destination"))?;
        for positive in 0..count {
            let threshold = ranks[positive] as f32;
            optimistic[positive] -= u64::from(score > threshold);
            pessimistic[positive] -= u64::from(score >= threshold);
        }
    }
    for positive in 0..count {
        ranks[positive] = 0.5 * (optimistic[positive] + pessimistic[positive]) as f64 + 1.0;
    }
    Ok(())
}

pub(crate) fn certificate(
    task_id: &str,
    model_id: &str,
    split: LinkPredictionSplit,
    score_blake3: String,
    metrics: FilteredRankingMetrics,
) -> Result<LinkPredictionScoreCertificate, LinkPredictionError> {
    let certificate_id = format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            LINK_PREDICTION_SCORE_SCHEMA,
            task_id,
            model_id,
            split,
            score_blake3.as_str(),
            metrics.mean_reciprocal_rank.to_bits(),
            metrics.hits_at_1.to_bits(),
            metrics.hits_at_3.to_bits(),
            metrics.hits_at_10.to_bits(),
            metrics.queries,
            metrics.positives,
            metrics.candidates_scored,
        ))?)
        .to_hex()
    );
    Ok(LinkPredictionScoreCertificate {
        schema_version: LINK_PREDICTION_SCORE_SCHEMA.into(),
        certificate_id: certificate_id.into(),
        task_id: task_id.into(),
        model_id: model_id.into(),
        split,
        score_blake3: score_blake3.into(),
        mean_reciprocal_rank: metrics.mean_reciprocal_rank,
        hits_at_1: metrics.hits_at_1,
        hits_at_3: metrics.hits_at_3,
        hits_at_10: metrics.hits_at_10,
        queries: metrics.queries,
        positives: metrics.positives,
        candidates_scored: metrics.candidates_scored,
    })
}

fn lock_identity(input: &LinkPredictionTestLockInput) -> Result<String, LinkPredictionError> {
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            LINK_PREDICTION_TEST_LOCK_SCHEMA,
            input.task_id.as_str(),
            input.selection_ledger_id.as_str(),
            input.selected_model_id.as_str(),
            input.validation_certificate_id.as_str(),
        ))?)
        .to_hex()
    ))
}

fn validate_lock(
    task: &LinkPredictionTaskMapped,
    lock: &LinkPredictionTestLock,
) -> Result<(), LinkPredictionError> {
    let input = LinkPredictionTestLockInput {
        task_id: lock.task_id.clone(),
        selection_ledger_id: lock.selection_ledger_id.clone(),
        selected_model_id: lock.selected_model_id.clone(),
        validation_certificate_id: lock.validation_certificate_id.clone(),
    };
    if lock.schema_version != LINK_PREDICTION_TEST_LOCK_SCHEMA
        || lock.task_id != task.manifest().task_id
        || lock.lock_id != lock_identity(&input)?
    {
        return Err(LinkPredictionError::CorruptArtifact("test lock"));
    }
    Ok(())
}

fn write_new_durable(path: &Path, bytes: &[u8]) -> Result<(), LinkPredictionError> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    sync_parent(path)?;
    Ok(())
}

fn sync_parent(path: &Path) -> Result<(), LinkPredictionError> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let directory = OpenOptions::new().read(true).open(parent);
    match directory {
        Ok(directory) => directory.sync_all().map_err(LinkPredictionError::Io),
        Err(error) if cfg!(windows) && error.kind() == std::io::ErrorKind::PermissionDenied => {
            Ok(())
        }
        Err(error) => Err(LinkPredictionError::Io(error)),
    }
}
