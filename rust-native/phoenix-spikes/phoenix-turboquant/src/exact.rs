use std::cmp::Reverse;
use std::collections::BinaryHeap;
use std::time::{Duration, Instant};

use rayon::prelude::*;

use crate::search::{finish_heap, push_heap, HeapHit};
use crate::{Result, SearchHit, TurboQuantError};

#[derive(Clone, Copy, Debug, serde::Serialize)]
pub struct ExactPhaseTimings {
    pub rows: usize,
    pub top_k: usize,
    pub workers: usize,
    pub thread_orchestration_ns: u64,
    pub dot_accumulation_ns: u64,
    pub top_k_ns: u64,
    pub result_materialization_ns: u64,
    pub total_ns: u64,
}

#[derive(Debug)]
pub struct ExactSearchScratch {
    heap: BinaryHeap<Reverse<HeapHit>>,
    scores: Vec<f32>,
}

impl ExactSearchScratch {
    pub fn new(top_k: usize) -> Self {
        Self {
            heap: BinaryHeap::with_capacity(top_k),
            scores: Vec::new(),
        }
    }
}

pub fn exact_search(
    vectors: &[f32],
    subject_ids: &[u64],
    dimension: usize,
    query: &[f32],
    top_k: usize,
) -> Result<Vec<SearchHit>> {
    let mut scratch = ExactSearchScratch::new(top_k);
    let mut output = Vec::with_capacity(top_k);
    exact_search_into(
        vectors,
        subject_ids,
        dimension,
        query,
        top_k,
        &mut scratch,
        &mut output,
    )?;
    Ok(output)
}

/// Reranks a bounded quantized candidate set against the original f32 slab.
///
/// The warmed path reuses `scratch` and `output`; candidate rows are direct
/// offsets into the dense vector slab, so there is no hash lookup or copying.
#[allow(clippy::too_many_arguments)]
pub fn exact_rerank_candidates_into(
    vectors: &[f32],
    subject_ids: &[u64],
    dimension: usize,
    query: &[f32],
    candidates: &[SearchHit],
    top_k: usize,
    scratch: &mut ExactSearchScratch,
    output: &mut Vec<SearchHit>,
) -> Result<()> {
    validate(vectors, subject_ids, dimension, query)?;
    scratch.heap.clear();
    let top_k = top_k.min(candidates.len());
    for candidate in candidates {
        let start = candidate
            .row
            .checked_mul(dimension)
            .ok_or(TurboQuantError::Overflow)?;
        let end = start
            .checked_add(dimension)
            .ok_or(TurboQuantError::Overflow)?;
        let vector = vectors
            .get(start..end)
            .ok_or(TurboQuantError::InvalidLayout)?;
        #[cfg(target_arch = "x86_64")]
        let score = if std::arch::is_x86_feature_detected!("avx2") {
            // SAFETY: the feature is detected before entering the AVX2 kernel.
            unsafe { dot_avx2(vector, query) }
        } else {
            dot_scalar(vector, query)
        };
        #[cfg(not(target_arch = "x86_64"))]
        let score = dot_scalar(vector, query);
        push_heap(&mut scratch.heap, top_k, score, candidate.row);
    }
    finish_heap(&mut scratch.heap, subject_ids, output);
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub fn exact_search_into(
    vectors: &[f32],
    subject_ids: &[u64],
    dimension: usize,
    query: &[f32],
    top_k: usize,
    scratch: &mut ExactSearchScratch,
    output: &mut Vec<SearchHit>,
) -> Result<()> {
    validate(vectors, subject_ids, dimension, query)?;
    scratch.heap.clear();
    let top_k = top_k.min(subject_ids.len());
    #[cfg(target_arch = "x86_64")]
    if std::arch::is_x86_feature_detected!("avx2") {
        for (row, vector) in vectors.chunks_exact(dimension).enumerate() {
            // SAFETY: runtime feature detection occurs once outside the row loop.
            push_heap(
                &mut scratch.heap,
                top_k,
                unsafe { dot_avx2(vector, query) },
                row,
            );
        }
    } else {
        score_fused_scalar(vectors, dimension, query, top_k, &mut scratch.heap);
    }
    #[cfg(not(target_arch = "x86_64"))]
    score_fused_scalar(vectors, dimension, query, top_k, &mut scratch.heap);
    finish_heap(&mut scratch.heap, subject_ids, output);
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub fn profile_exact_search_into(
    vectors: &[f32],
    subject_ids: &[u64],
    dimension: usize,
    query: &[f32],
    top_k: usize,
    scratch: &mut ExactSearchScratch,
    output: &mut Vec<SearchHit>,
) -> Result<ExactPhaseTimings> {
    validate(vectors, subject_ids, dimension, query)?;
    profile_exact(
        vectors,
        subject_ids,
        dimension,
        query,
        top_k,
        scratch,
        output,
        false,
    )
}

#[allow(clippy::too_many_arguments)]
pub fn profile_exact_parallel_search_into(
    vectors: &[f32],
    subject_ids: &[u64],
    dimension: usize,
    query: &[f32],
    top_k: usize,
    scratch: &mut ExactSearchScratch,
    output: &mut Vec<SearchHit>,
) -> Result<ExactPhaseTimings> {
    validate(vectors, subject_ids, dimension, query)?;
    profile_exact(
        vectors,
        subject_ids,
        dimension,
        query,
        top_k,
        scratch,
        output,
        true,
    )
}

#[allow(clippy::too_many_arguments)]
fn profile_exact(
    vectors: &[f32],
    subject_ids: &[u64],
    dimension: usize,
    query: &[f32],
    top_k: usize,
    scratch: &mut ExactSearchScratch,
    output: &mut Vec<SearchHit>,
    parallel: bool,
) -> Result<ExactPhaseTimings> {
    let total_start = Instant::now();
    let rows = subject_ids.len();
    let top_k = top_k.min(rows);
    scratch.scores.clear();
    scratch.scores.resize(rows, 0.0);
    let workers = if parallel {
        rayon::current_num_threads()
    } else {
        1
    };
    let orchestration_start = Instant::now();
    if parallel {
        (0..workers).into_par_iter().for_each(|worker| {
            std::hint::black_box(worker);
        });
    }
    let thread_orchestration_ns = nanos(orchestration_start.elapsed());
    let dot_start = Instant::now();
    if parallel {
        score_all_parallel(vectors, dimension, query, &mut scratch.scores);
    } else {
        score_all_serial(vectors, dimension, query, &mut scratch.scores);
    }
    let dot_accumulation_ns = nanos(dot_start.elapsed());
    scratch.heap.clear();
    let top_k_start = Instant::now();
    for (row, score) in scratch.scores.iter().copied().enumerate() {
        push_heap(&mut scratch.heap, top_k, score, row);
    }
    let top_k_ns = nanos(top_k_start.elapsed());
    let materialization_start = Instant::now();
    finish_heap(&mut scratch.heap, subject_ids, output);
    let result_materialization_ns = nanos(materialization_start.elapsed());
    Ok(ExactPhaseTimings {
        rows,
        top_k,
        workers,
        thread_orchestration_ns,
        dot_accumulation_ns,
        top_k_ns,
        result_materialization_ns,
        total_ns: nanos(total_start.elapsed()),
    })
}

fn validate(vectors: &[f32], ids: &[u64], dimension: usize, query: &[f32]) -> Result<()> {
    if query.len() != dimension {
        return Err(TurboQuantError::QueryDimension {
            actual: query.len(),
            expected: dimension,
        });
    }
    if vectors.len() != ids.len() * dimension {
        return Err(TurboQuantError::InvalidVectorLength {
            actual: vectors.len(),
            rows: ids.len(),
            dimension,
        });
    }
    Ok(())
}

fn score_fused_scalar(
    vectors: &[f32],
    dimension: usize,
    query: &[f32],
    top_k: usize,
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
) {
    for (row, vector) in vectors.chunks_exact(dimension).enumerate() {
        push_heap(heap, top_k, dot_scalar(vector, query), row);
    }
}

fn score_all_serial(vectors: &[f32], dimension: usize, query: &[f32], output: &mut [f32]) {
    #[cfg(target_arch = "x86_64")]
    if std::arch::is_x86_feature_detected!("avx2") {
        for (destination, vector) in output.iter_mut().zip(vectors.chunks_exact(dimension)) {
            // SAFETY: runtime feature detection occurs once outside the row loop.
            *destination = unsafe { dot_avx2(vector, query) };
        }
        return;
    }
    for (destination, vector) in output.iter_mut().zip(vectors.chunks_exact(dimension)) {
        *destination = dot_scalar(vector, query);
    }
}

fn score_all_parallel(vectors: &[f32], dimension: usize, query: &[f32], output: &mut [f32]) {
    #[cfg(target_arch = "x86_64")]
    if std::arch::is_x86_feature_detected!("avx2") {
        output
            .par_iter_mut()
            .zip(vectors.par_chunks_exact(dimension))
            .for_each(|(destination, vector)| {
                // SAFETY: runtime feature detection occurs before the parallel loop.
                *destination = unsafe { dot_avx2(vector, query) };
            });
        return;
    }
    output
        .par_iter_mut()
        .zip(vectors.par_chunks_exact(dimension))
        .for_each(|(destination, vector)| *destination = dot_scalar(vector, query));
}

#[inline]
fn dot_scalar(left: &[f32], right: &[f32]) -> f32 {
    left.iter().zip(right).map(|(a, b)| a * b).sum()
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn dot_avx2(left: &[f32], right: &[f32]) -> f32 {
    use std::arch::x86_64::*;

    let mut accumulator = _mm256_setzero_ps();
    let chunks = left.len() / 8;
    for chunk in 0..chunks {
        let offset = chunk * 8;
        let a = _mm256_loadu_ps(left.as_ptr().add(offset));
        let b = _mm256_loadu_ps(right.as_ptr().add(offset));
        accumulator = _mm256_add_ps(accumulator, _mm256_mul_ps(a, b));
    }
    let mut lanes = [0.0f32; 8];
    _mm256_storeu_ps(lanes.as_mut_ptr(), accumulator);
    let mut total = lanes.into_iter().sum::<f32>();
    for index in chunks * 8..left.len() {
        total += left[index] * right[index];
    }
    total
}

fn nanos(duration: Duration) -> u64 {
    duration.as_nanos().min(u64::MAX as u128) as u64
}
