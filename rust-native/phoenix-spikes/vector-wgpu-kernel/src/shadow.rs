use std::{sync::Arc, time::Instant};

use crate::{
    DispatchBackend, DispatchPolicy, GpuVectorRuntime, ResidentLease, ResidentVectorCorpus,
    ValidatedRerankBatch, VectorCorpusInput, VectorRerankBatch,
    reconcile::{
        CPU_ACCUMULATOR, FallbackReason, GPU_ACCUMULATOR, SCORE_POLICY_VERSION,
        f32_dot_error_bound, gpu_output_width, reconcile_row,
    },
};

const QUERY_BATCH_ROWS: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ShadowDisposition {
    Unqualified,
    AdapterUnavailable,
    Certified,
    Reconciled,
    Drift,
    Rejected,
}

#[derive(Debug)]
pub struct GpuShadowReceipt {
    pub generation: u64,
    pub score_policy_version: &'static str,
    pub gpu_accumulator: &'static str,
    pub cpu_accumulator: &'static str,
    pub error_bound: f64,
    pub guard_records: u32,
    pub disposition: ShadowDisposition,
    pub compared_queries: u32,
    pub skipped_queries: u32,
    pub candidate_pairs: u64,
    pub identity_mismatches: u64,
    pub score_mismatches: u64,
    pub maximum_quantized_delta: u32,
    pub shortlist_records: u64,
    pub boundary_certified_queries: u32,
    pub row_fallback_queries: u32,
    pub ambiguous_boundary_queries: u32,
    pub capacity_fallback_queries: u32,
    pub invalid_page_fallback_queries: u32,
    pub minimum_boundary_margin: Option<f64>,
    pub maximum_observed_score_error: f64,
    pub upload_micros: u64,
    pub dispatch_micros: u64,
    pub readback_micros: u64,
    pub wall_micros: u64,
    pub runtime_reused: bool,
    pub corpus_reused: bool,
    pub adapter: Option<String>,
    pub failure: Option<String>,
}

pub struct ShadowInput<'a> {
    pub values: &'a [f32],
    pub lexical_ranks: &'a [u32],
    pub rows: usize,
    pub dimensions: usize,
    pub top_k: usize,
    pub max_candidates: usize,
    pub minimum_similarity: f64,
    pub generation: u64,
    pub authoritative: &'a [Vec<(u32, i32)>],
}

struct CandidateChunk {
    start: usize,
    end: usize,
    offsets: Vec<u32>,
    identities: Vec<u32>,
}

pub fn verify_gpu_shadow<F>(input: ShadowInput<'_>, candidates_for: F) -> GpuShadowReceipt
where
    F: FnMut(usize, &mut [u32]) -> Result<usize, String>,
{
    let values = input.values;
    let dimensions = input.dimensions;
    verify_gpu_shadow_with_provider_and_scorer(
        input,
        candidates_for,
        |corpus| {
            let runtime = GpuVectorRuntime::request(DispatchPolicy::default())
                .map_err(|error| error.to_string())?;
            let resident = runtime.upload(corpus).map_err(|error| error.to_string())?;
            Ok(ResidentLease {
                corpus: Arc::new(resident),
                runtime_reused: false,
                corpus_reused: false,
            })
        },
        move |source, target| exact_dot(values, dimensions, source, target),
    )
}

pub fn verify_gpu_shadow_with_provider<F, P>(
    input: ShadowInput<'_>,
    candidates_for: F,
    resident_provider: P,
) -> GpuShadowReceipt
where
    F: FnMut(usize, &mut [u32]) -> Result<usize, String>,
    P: FnOnce(VectorCorpusInput<'_>) -> Result<ResidentLease, String>,
{
    let values = input.values;
    let dimensions = input.dimensions;
    verify_gpu_shadow_with_provider_and_scorer(
        input,
        candidates_for,
        resident_provider,
        move |source, target| exact_dot(values, dimensions, source, target),
    )
}

pub fn verify_gpu_shadow_with_provider_and_scorer<F, P, S>(
    input: ShadowInput<'_>,
    mut candidates_for: F,
    resident_provider: P,
    mut exact_score: S,
) -> GpuShadowReceipt
where
    F: FnMut(usize, &mut [u32]) -> Result<usize, String>,
    P: FnOnce(VectorCorpusInput<'_>) -> Result<ResidentLease, String>,
    S: FnMut(usize, usize) -> f64,
{
    let started = Instant::now();
    let mut receipt = empty_receipt(input.generation, input.dimensions);
    if input.top_k == 0
        || input.top_k > crate::MAX_TOP_K as usize
        || input.max_candidates == 0
        || input.max_candidates > crate::MAX_CANDIDATES_PER_QUERY as usize
        || !input.minimum_similarity.is_finite()
        || !(-1.0..=1.0).contains(&input.minimum_similarity)
    {
        return reject(
            receipt,
            "shadow scoring bounds are outside the packed contract",
        );
    }
    let (Ok(rows), Ok(dimensions)) = (u32::try_from(input.rows), u32::try_from(input.dimensions))
    else {
        return reject(receipt, "shadow corpus shape exceeds u32 addressing");
    };
    if input.authoritative.len() != input.rows {
        return reject(receipt, "authoritative neighborhood row extent drift");
    }
    let corpus = VectorCorpusInput {
        values: input.values,
        lexical_ranks: input.lexical_ranks,
        rows,
        dimensions,
    };
    let corpus_shape = match corpus.validate() {
        Ok(shape) => shape,
        Err(error) => return reject(receipt, error.to_string()),
    };
    let policy = DispatchPolicy::default();
    let mut next_start = 0;
    let first_qualified = loop {
        let chunk = match prepare_chunk(&input, next_start, &mut candidates_for) {
            Ok(chunk) => chunk,
            Err(error) => return reject(receipt, error),
        };
        next_start = chunk.end;
        receipt.candidate_pairs += chunk.identities.len() as u64;
        let batch = batch(&input, &chunk);
        let shape = match batch.validate(corpus_shape) {
            Ok(shape) => shape,
            Err(error) => return reject(receipt, error.to_string()),
        };
        let resident_bytes = match total_resident_bytes(corpus_shape.resident_bytes, shape) {
            Some(bytes) => bytes,
            None => return reject(receipt, "shadow resident byte accounting overflow"),
        };
        if policy.select(shape, resident_bytes, true) == DispatchBackend::Gpu {
            break Some(chunk);
        }
        receipt.skipped_queries += (chunk.end - chunk.start) as u32;
        if next_start == input.rows {
            break None;
        }
    };
    let Some(first_qualified) = first_qualified else {
        receipt.disposition = ShadowDisposition::Unqualified;
        return finish(receipt, started);
    };
    let lease = match resident_provider(corpus) {
        Ok(lease) => lease,
        Err(error) => {
            receipt.disposition = ShadowDisposition::AdapterUnavailable;
            receipt.failure = Some(error);
            return finish(receipt, started);
        }
    };
    receipt.runtime_reused = lease.runtime_reused;
    receipt.corpus_reused = lease.corpus_reused;
    receipt.adapter = Some(lease.corpus.adapter_receipt().name.clone());
    receipt.upload_micros = if lease.corpus_reused {
        0
    } else {
        lease.corpus.receipt().upload_micros
    };
    compare_chunk(
        &input,
        &lease.corpus,
        first_qualified,
        &mut receipt,
        &mut exact_score,
    );
    while next_start < input.rows && receipt.failure.is_none() {
        let chunk = match prepare_chunk(&input, next_start, &mut candidates_for) {
            Ok(chunk) => chunk,
            Err(error) => {
                receipt.disposition = ShadowDisposition::Rejected;
                receipt.failure = Some(error);
                break;
            }
        };
        next_start = chunk.end;
        receipt.candidate_pairs += chunk.identities.len() as u64;
        let batch = batch(&input, &chunk);
        match lease.corpus.dispatch_backend(batch, true) {
            Ok(DispatchBackend::Gpu) => {
                compare_chunk(&input, &lease.corpus, chunk, &mut receipt, &mut exact_score)
            }
            Ok(DispatchBackend::Cpu) => {
                receipt.skipped_queries += (chunk.end - chunk.start) as u32;
            }
            Err(error) => {
                receipt.disposition = ShadowDisposition::Rejected;
                receipt.failure = Some(error.to_string());
            }
        }
    }
    if receipt.failure.is_none() {
        receipt.disposition = if receipt.identity_mismatches != 0 || receipt.score_mismatches != 0 {
            ShadowDisposition::Drift
        } else if receipt.row_fallback_queries != 0 {
            ShadowDisposition::Reconciled
        } else {
            ShadowDisposition::Certified
        };
    }
    finish(receipt, started)
}

fn compare_chunk<S>(
    input: &ShadowInput<'_>,
    resident: &ResidentVectorCorpus,
    chunk: CandidateChunk,
    receipt: &mut GpuShadowReceipt,
    exact_score: &mut S,
) where
    S: FnMut(usize, usize) -> f64,
{
    let output = match resident.rerank(batch(input, &chunk)) {
        Ok(output) => output,
        Err(error) => {
            receipt.disposition = ShadowDisposition::Rejected;
            receipt.failure = Some(error.to_string());
            return;
        }
    };
    receipt.dispatch_micros = receipt
        .dispatch_micros
        .saturating_add(output.receipt.dispatch_micros);
    receipt.readback_micros = receipt
        .readback_micros
        .saturating_add(output.receipt.readback_micros);
    for local in 0..chunk.end - chunk.start {
        let source = chunk.start + local;
        let expected = &input.authoritative[chunk.start + local];
        let candidate_start = chunk.offsets[local] as usize;
        let candidate_end = chunk.offsets[local + 1] as usize;
        let candidates = &chunk.identities[candidate_start..candidate_end];
        let row = reconcile_row(
            candidates,
            output.top_k.query(local),
            input.top_k,
            input.minimum_similarity,
            input.lexical_ranks,
            receipt.error_bound,
            |target| exact_score(source, target as usize),
        );
        receipt.compared_queries += 1;
        receipt.shortlist_records = receipt
            .shortlist_records
            .saturating_add(row.shortlist_records as u64);
        receipt.maximum_observed_score_error = receipt
            .maximum_observed_score_error
            .max(row.maximum_observed_score_error);
        if row.certified {
            receipt.boundary_certified_queries += 1;
            if let Some(margin) = row.boundary_margin {
                receipt.minimum_boundary_margin = Some(
                    receipt
                        .minimum_boundary_margin
                        .map_or(margin, |current| current.min(margin)),
                );
            }
        } else {
            record_fallback(receipt, row.fallback_reason);
            continue;
        }
        let actual = &row.records;
        receipt.identity_mismatches += expected.len().abs_diff(actual.len()) as u64;
        for (&(expected_id, expected_score), actual) in expected.iter().zip(actual) {
            if expected_id != actual.0 {
                receipt.identity_mismatches += 1;
                continue;
            }
            let delta = expected_score.abs_diff(actual.1);
            receipt.maximum_quantized_delta = receipt.maximum_quantized_delta.max(delta);
            receipt.score_mismatches += u64::from(delta != 0);
        }
    }
}

fn prepare_chunk<F>(
    input: &ShadowInput<'_>,
    start: usize,
    candidates_for: &mut F,
) -> Result<CandidateChunk, String>
where
    F: FnMut(usize, &mut [u32]) -> Result<usize, String>,
{
    let end = input.rows.min(start + QUERY_BATCH_ROWS);
    let mut scratch = vec![0_u32; input.max_candidates];
    let mut offsets = Vec::with_capacity(end - start + 1);
    let mut identities = Vec::with_capacity((end - start) * input.max_candidates);
    offsets.push(0);
    for source in start..end {
        let count = candidates_for(source, &mut scratch)?;
        if count > input.max_candidates {
            return Err("ANN candidate callback exceeded its bounded scratch page".to_owned());
        }
        identities.extend_from_slice(&scratch[..count]);
        offsets.push(identities.len() as u32);
    }
    Ok(CandidateChunk {
        start,
        end,
        offsets,
        identities,
    })
}

fn batch<'a>(input: &ShadowInput<'a>, chunk: &'a CandidateChunk) -> VectorRerankBatch<'a> {
    let query_start = chunk.start * input.dimensions;
    let query_end = chunk.end * input.dimensions;
    VectorRerankBatch {
        queries: &input.values[query_start..query_end],
        query_count: (chunk.end - chunk.start) as u32,
        candidate_offsets: &chunk.offsets,
        candidate_ids: &chunk.identities,
        top_k: gpu_output_width(input.top_k) as u32,
        minimum_similarity: -1.0,
    }
}

fn total_resident_bytes(corpus_bytes: u64, batch: ValidatedRerankBatch) -> Option<u64> {
    let readback_bytes = batch.readback_bytes.checked_mul(2)?;
    corpus_bytes
        .checked_add(batch.query_bytes)?
        .checked_add(batch.candidate_bytes)?
        .checked_add(readback_bytes)
}

fn record_fallback(receipt: &mut GpuShadowReceipt, reason: Option<FallbackReason>) {
    receipt.row_fallback_queries += 1;
    match reason {
        Some(FallbackReason::AmbiguousBoundary) => receipt.ambiguous_boundary_queries += 1,
        Some(FallbackReason::InsufficientGuardCapacity) => receipt.capacity_fallback_queries += 1,
        Some(FallbackReason::InvalidGpuPage | FallbackReason::InvalidExactScore) | None => {
            receipt.invalid_page_fallback_queries += 1;
        }
    }
}

fn exact_dot(values: &[f32], dimensions: usize, left: usize, right: usize) -> f64 {
    let left = &values[left * dimensions..(left + 1) * dimensions];
    let right = &values[right * dimensions..(right + 1) * dimensions];
    left.iter()
        .zip(right)
        .map(|(&left, &right)| f64::from(left) * f64::from(right))
        .sum::<f64>()
        .clamp(-1.0, 1.0)
}

fn empty_receipt(generation: u64, dimensions: usize) -> GpuShadowReceipt {
    GpuShadowReceipt {
        generation,
        score_policy_version: SCORE_POLICY_VERSION,
        gpu_accumulator: GPU_ACCUMULATOR,
        cpu_accumulator: CPU_ACCUMULATOR,
        error_bound: f32_dot_error_bound(dimensions),
        guard_records: crate::reconcile::GUARD_RECORDS as u32,
        disposition: ShadowDisposition::Rejected,
        compared_queries: 0,
        skipped_queries: 0,
        candidate_pairs: 0,
        identity_mismatches: 0,
        score_mismatches: 0,
        maximum_quantized_delta: 0,
        shortlist_records: 0,
        boundary_certified_queries: 0,
        row_fallback_queries: 0,
        ambiguous_boundary_queries: 0,
        capacity_fallback_queries: 0,
        invalid_page_fallback_queries: 0,
        minimum_boundary_margin: None,
        maximum_observed_score_error: 0.0,
        upload_micros: 0,
        dispatch_micros: 0,
        readback_micros: 0,
        wall_micros: 0,
        runtime_reused: false,
        corpus_reused: false,
        adapter: None,
        failure: None,
    }
}

fn reject(mut receipt: GpuShadowReceipt, message: impl Into<String>) -> GpuShadowReceipt {
    receipt.disposition = ShadowDisposition::Rejected;
    receipt.failure = Some(message.into());
    receipt
}

fn finish(mut receipt: GpuShadowReceipt, started: Instant) -> GpuShadowReceipt {
    receipt.wall_micros = started.elapsed().as_micros().min(u128::from(u64::MAX)) as u64;
    receipt
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{GpuResidencyCache, ResidencyKey};

    #[test]
    fn small_ann_batches_never_request_the_gpu() {
        let values = [1.0_f32, 0.0, 0.0, 1.0, -1.0, 0.0, 0.0, -1.0];
        let ranks = [0, 1, 2, 3];
        let authoritative = vec![Vec::new(); 4];
        let receipt = verify_gpu_shadow(
            ShadowInput {
                values: &values,
                lexical_ranks: &ranks,
                rows: 4,
                dimensions: 2,
                top_k: 2,
                max_candidates: 2,
                minimum_similarity: -1.0,
                generation: 9,
                authoritative: &authoritative,
            },
            |_source, out| {
                out[..2].copy_from_slice(&[0, 1]);
                Ok(2)
            },
        );
        assert_eq!(receipt.disposition, ShadowDisposition::Unqualified);
        assert_eq!(receipt.compared_queries, 0);
        assert_eq!(receipt.skipped_queries, 4);
        assert!(receipt.adapter.is_none());
        assert!(receipt.failure.is_none());
    }

    #[test]
    #[ignore = "requires a hardware GPU; run for production shadow qualification"]
    fn gpu_shadow_replays_bounded_candidates_without_identity_drift() {
        let rows = 2_048;
        let dimensions = 256;
        let top_k = 16;
        let candidates_per_row = 128;
        let mut values = (0..rows * dimensions)
            .map(|index| ((index * 73 + index / 17 * 29 + 11) % 1_009) as f32 / 504.0 - 1.0)
            .collect::<Vec<_>>();
        normalize(&mut values, dimensions);
        let ranks = (0..rows as u32).collect::<Vec<_>>();
        let authoritative =
            authoritative_rows(&values, &ranks, rows, dimensions, candidates_per_row, top_k);
        let key = ResidencyKey {
            generation: 11,
            rows: rows as u32,
            dimensions: dimensions as u32,
            corpus_digest: [3; 32],
        };
        let mut cache = GpuResidencyCache::new(DispatchPolicy::default());
        let mut run = || {
            verify_gpu_shadow_with_provider(
                ShadowInput {
                    values: &values,
                    lexical_ranks: &ranks,
                    rows,
                    dimensions,
                    top_k,
                    max_candidates: candidates_per_row,
                    minimum_similarity: -1.0,
                    generation: 11,
                    authoritative: &authoritative,
                },
                |source, out| {
                    for (slot, target) in out[..candidates_per_row].iter_mut().enumerate() {
                        *target = ((source + slot + 1) % rows) as u32;
                    }
                    Ok(candidates_per_row)
                },
                |input| cache.lease(key, input).map_err(|error| error.to_string()),
            )
        };
        let first = run();
        let mut warm = (0..5).map(|_| run()).collect::<Vec<_>>();
        warm.sort_unstable_by_key(|receipt| receipt.wall_micros);
        let receipt = &warm[warm.len() / 2];
        eprintln!(
            "[vector-shadow-qualification] disposition={:?} compared={} certified={} fallbacks={} pairs={} identity_mismatches={} score_mismatches={} max_quantized_delta={} error_bound={:.9} observed_error={:.9} min_margin={} runtime_reused={} corpus_reused={} upload_us={} dispatch_us={} readback_us={} wall_us={} adapter={}",
            receipt.disposition,
            receipt.compared_queries,
            receipt.boundary_certified_queries,
            receipt.row_fallback_queries,
            receipt.candidate_pairs,
            receipt.identity_mismatches,
            receipt.score_mismatches,
            receipt.maximum_quantized_delta,
            receipt.error_bound,
            receipt.maximum_observed_score_error,
            receipt
                .minimum_boundary_margin
                .map_or_else(|| "none".to_owned(), |margin| format!("{margin:.9}"),),
            receipt.runtime_reused,
            receipt.corpus_reused,
            receipt.upload_micros,
            receipt.dispatch_micros,
            receipt.readback_micros,
            receipt.wall_micros,
            receipt.adapter.as_deref().unwrap_or("none"),
        );
        assert!(!first.runtime_reused);
        assert!(!first.corpus_reused);
        assert!(warm.iter().all(|receipt| receipt.runtime_reused));
        assert!(warm.iter().all(|receipt| receipt.corpus_reused));
        assert!(warm.iter().all(|receipt| receipt.upload_micros == 0));
        assert_eq!(receipt.compared_queries, rows as u32);
        assert_eq!(receipt.skipped_queries, 0);
        assert_eq!(receipt.disposition, ShadowDisposition::Certified);
        assert_eq!(receipt.boundary_certified_queries, rows as u32);
        assert_eq!(receipt.row_fallback_queries, 0);
        assert_eq!(receipt.identity_mismatches, 0);
        assert_eq!(receipt.score_mismatches, 0);
        assert_eq!(receipt.maximum_quantized_delta, 0);
        assert!(receipt.maximum_observed_score_error <= receipt.error_bound);
        assert!(receipt.failure.is_none());
    }

    fn authoritative_rows(
        values: &[f32],
        ranks: &[u32],
        rows: usize,
        dimensions: usize,
        candidate_count: usize,
        top_k: usize,
    ) -> Vec<Vec<(u32, i32)>> {
        (0..rows)
            .map(|source| {
                let left = &values[source * dimensions..(source + 1) * dimensions];
                let mut ranked = (0..candidate_count)
                    .map(|slot| {
                        let target = (source + slot + 1) % rows;
                        let right = &values[target * dimensions..(target + 1) * dimensions];
                        let score = left
                            .iter()
                            .zip(right)
                            .fold(0.0_f64, |sum, (&a, &b)| sum + f64::from(a) * f64::from(b));
                        (target as u32, score)
                    })
                    .collect::<Vec<_>>();
                ranked.sort_unstable_by(|left, right| {
                    right
                        .1
                        .total_cmp(&left.1)
                        .then_with(|| ranks[left.0 as usize].cmp(&ranks[right.0 as usize]))
                        .then_with(|| left.0.cmp(&right.0))
                });
                ranked
                    .into_iter()
                    .take(top_k)
                    .map(|(target, score)| {
                        let quantized = ((score.clamp(-1.0, 1.0) * 1_000_000.0) + 0.5).floor();
                        (target, quantized as i32)
                    })
                    .collect()
            })
            .collect()
    }

    fn normalize(values: &mut [f32], dimensions: usize) {
        for row in values.chunks_exact_mut(dimensions) {
            let norm = row
                .iter()
                .map(|value| f64::from(*value) * f64::from(*value))
                .sum::<f64>()
                .sqrt();
            for value in row {
                *value = (f64::from(*value) / norm) as f32;
            }
        }
    }
}
