use std::cmp::{Ordering, Reverse};
use std::collections::BinaryHeap;
use std::time::{Duration, Instant};

use rayon::prelude::*;

use crate::{Result, TurboQuantError, VerifiedQuantizedIndex};

mod batch;
mod compact;

use compact::CompactLookup;

pub(crate) use batch::{
    profile_batch_block_local, search_batch_block_local, search_batch_parallel,
};
pub use batch::{
    BatchSearchScratch, BlockLocalPhaseTimings, BlockLocalTopKConfig, MAX_BATCH_QUERIES,
    MAX_BLOCK_ROWS, MAX_LOCAL_K,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchKernel {
    Auto,
    Scalar,
    Avx2,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchExecution {
    Auto,
    Serial,
    Rayon,
}

#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize)]
pub struct SearchHit {
    pub row: usize,
    pub subject_id: u64,
    pub score: f32,
}

#[derive(Clone, Copy, Debug, Default, serde::Serialize)]
pub struct QueryPreparationTimings {
    pub query_rotation_ns: u64,
    pub query_lut_ns: u64,
}

#[derive(Clone, Copy, Debug, serde::Serialize)]
pub struct PhaseTimings {
    pub rows: usize,
    pub top_k: usize,
    pub workers: usize,
    pub kernel: SearchKernel,
    pub query_rotation_ns: u64,
    pub query_lut_ns: u64,
    pub artifact_traversal_decode_accumulate_ns: u64,
    pub scale_correction_ns: u64,
    pub top_k_ns: u64,
    pub result_materialization_ns: u64,
    pub thread_orchestration_ns: u64,
    pub total_ns: u64,
}

#[derive(Debug)]
pub struct SearchScratch {
    rotated: Vec<f32>,
    rotation_scratch: Vec<f32>,
    lookup: CompactLookup,
    scores: Vec<f32>,
    local_top_k: Vec<FixedTopK>,
    heap: BinaryHeap<Reverse<HeapHit>>,
    prepared_quantizer_hash: Option<[u8; 32]>,
}

impl SearchScratch {
    pub fn new(dimension: usize, top_k: usize) -> Self {
        Self {
            rotated: vec![0.0; dimension],
            rotation_scratch: vec![0.0; dimension],
            lookup: CompactLookup::default(),
            scores: Vec::new(),
            local_top_k: Vec::new(),
            heap: BinaryHeap::with_capacity(top_k),
            prepared_quantizer_hash: None,
        }
    }

    pub fn capacities(&self) -> (usize, usize, usize, usize, usize, usize) {
        (
            self.rotated.capacity(),
            self.rotation_scratch.capacity(),
            self.lookup.capacity(),
            self.scores.capacity(),
            self.local_top_k.capacity(),
            self.heap.capacity(),
        )
    }
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct HeapHit {
    score: f32,
    row: usize,
}

impl PartialEq for HeapHit {
    fn eq(&self, other: &Self) -> bool {
        self.score.to_bits() == other.score.to_bits() && self.row == other.row
    }
}

impl Eq for HeapHit {}

impl PartialOrd for HeapHit {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for HeapHit {
    fn cmp(&self, other: &Self) -> Ordering {
        self.score
            .total_cmp(&other.score)
            .then_with(|| other.row.cmp(&self.row))
    }
}

#[derive(Clone, Debug)]
struct FixedTopK {
    entries: [HeapHit; 64],
    len: usize,
    limit: usize,
}

impl Default for FixedTopK {
    fn default() -> Self {
        Self {
            entries: [HeapHit {
                score: f32::NEG_INFINITY,
                row: 0,
            }; 64],
            len: 0,
            limit: 0,
        }
    }
}

impl FixedTopK {
    #[inline]
    fn reset(&mut self, limit: usize) {
        self.len = 0;
        self.limit = limit.min(self.entries.len());
    }

    #[inline]
    fn insert(&mut self, candidate: HeapHit) {
        if self.limit == 0 {
            return;
        }
        if self.len < self.limit {
            let mut index = self.len;
            self.entries[index] = candidate;
            self.len += 1;
            while index > 0 {
                let parent = (index - 1) / 2;
                if self.entries[parent] <= self.entries[index] {
                    break;
                }
                self.entries.swap(parent, index);
                index = parent;
            }
        } else if candidate > self.entries[0] {
            self.entries[0] = candidate;
            let mut index = 0;
            loop {
                let left = index * 2 + 1;
                if left >= self.len {
                    break;
                }
                let right = left + 1;
                let smaller = if right < self.len && self.entries[right] < self.entries[left] {
                    right
                } else {
                    left
                };
                if self.entries[index] <= self.entries[smaller] {
                    break;
                }
                self.entries.swap(index, smaller);
                index = smaller;
            }
        }
    }

    fn entries(&self) -> &[HeapHit] {
        &self.entries[..self.len]
    }
}

pub(crate) fn search_quantized(
    index: &VerifiedQuantizedIndex,
    query: &[f32],
    top_k: usize,
    requested: SearchKernel,
    scratch: &mut SearchScratch,
    output: &mut Vec<SearchHit>,
) -> Result<SearchKernel> {
    prepare_quantized_query(index, query, scratch)?;
    search_prepared_with_execution(
        index,
        top_k,
        requested,
        SearchExecution::Auto,
        scratch,
        output,
    )
}

pub(crate) fn prepare_quantized_query(
    index: &VerifiedQuantizedIndex,
    query: &[f32],
    scratch: &mut SearchScratch,
) -> Result<QueryPreparationTimings> {
    validate_query(index, query)?;
    scratch.rotated.resize(index.dimension(), 0.0);
    scratch.rotation_scratch.resize(index.dimension(), 0.0);
    let rotation_start = Instant::now();
    scratch.rotated.copy_from_slice(query);
    index
        .rotation()
        .apply(&mut scratch.rotated, &mut scratch.rotation_scratch);
    let query_rotation_ns = nanos(rotation_start.elapsed());
    let lookup_start = Instant::now();
    compact::build_lookup(index, &scratch.rotated, &mut scratch.lookup);
    let query_lut_ns = nanos(lookup_start.elapsed());
    scratch.prepared_quantizer_hash = Some(index.header().quantizer_hash);
    Ok(QueryPreparationTimings {
        query_rotation_ns,
        query_lut_ns,
    })
}

pub(crate) fn search_prepared(
    index: &VerifiedQuantizedIndex,
    top_k: usize,
    requested: SearchKernel,
    scratch: &mut SearchScratch,
    output: &mut Vec<SearchHit>,
) -> Result<SearchKernel> {
    search_prepared_with_execution(
        index,
        top_k,
        requested,
        SearchExecution::Serial,
        scratch,
        output,
    )
}

pub(crate) fn search_prepared_with_execution(
    index: &VerifiedQuantizedIndex,
    top_k: usize,
    requested: SearchKernel,
    execution: SearchExecution,
    scratch: &mut SearchScratch,
    output: &mut Vec<SearchHit>,
) -> Result<SearchKernel> {
    if use_rayon(index, execution) {
        return search_prepared_parallel(index, top_k, requested, scratch, output);
    }
    validate_prepared(index, scratch)?;
    let top_k = top_k.min(index.len());
    output.clear();
    scratch.heap.clear();
    let kernel = resolve_kernel(requested);
    if top_k == 0 {
        return Ok(kernel);
    }
    let codes = index.codes()?;
    let scales = index.scales()?;
    match kernel {
        SearchKernel::Scalar => compact::score_scalar(
            index,
            &scratch.lookup,
            codes,
            scales,
            top_k,
            &mut scratch.heap,
        ),
        SearchKernel::Avx2 => {
            #[cfg(target_arch = "x86_64")]
            unsafe {
                compact::score_avx2(
                    index,
                    &scratch.lookup,
                    codes,
                    scales,
                    top_k,
                    &mut scratch.heap,
                )
            }
            #[cfg(not(target_arch = "x86_64"))]
            compact::score_scalar(
                index,
                &scratch.lookup,
                codes,
                scales,
                top_k,
                &mut scratch.heap,
            )
        }
        SearchKernel::Auto => unreachable!(),
    }
    finish_heap(&mut scratch.heap, index.subject_ids()?, output);
    Ok(kernel)
}

fn search_prepared_parallel(
    index: &VerifiedQuantizedIndex,
    top_k: usize,
    requested: SearchKernel,
    scratch: &mut SearchScratch,
    output: &mut Vec<SearchHit>,
) -> Result<SearchKernel> {
    validate_prepared(index, scratch)?;
    let top_k = top_k.min(index.len());
    let kernel = resolve_kernel(requested);
    output.clear();
    scratch.scores.clear();
    scratch.scores.resize(index.len(), 0.0);
    if index.bits() == 4 {
        compact::score_all_prepared_parallel_scaled(
            index,
            kernel,
            &scratch.lookup,
            index.scales()?,
            &mut scratch.scores,
        )?;
    } else {
        compact::score_all_prepared_parallel(index, kernel, &scratch.lookup, &mut scratch.scores)?;
        scratch
            .scores
            .par_iter_mut()
            .zip(index.scales()?.par_iter())
            .for_each(|(score, scale)| *score *= scale);
    }
    retain_parallel_top_k(
        &scratch.scores,
        top_k,
        &mut scratch.local_top_k,
        &mut scratch.heap,
    );
    finish_heap(&mut scratch.heap, index.subject_ids()?, output);
    Ok(kernel)
}

fn use_rayon(index: &VerifiedQuantizedIndex, execution: SearchExecution) -> bool {
    match execution {
        SearchExecution::Serial => false,
        SearchExecution::Rayon => rayon::current_num_threads() > 1,
        SearchExecution::Auto => {
            rayon::current_num_threads() > 1
                && match index.bits() {
                    2 => index.len() >= 8_192,
                    4 => index.len() >= 4_096,
                    _ => false,
                }
        }
    }
}

pub(crate) fn recommended_execution(index: &VerifiedQuantizedIndex) -> SearchExecution {
    if use_rayon(index, SearchExecution::Auto) {
        SearchExecution::Rayon
    } else {
        SearchExecution::Serial
    }
}

pub(crate) fn profile_quantized_search(
    index: &VerifiedQuantizedIndex,
    query: &[f32],
    top_k: usize,
    requested: SearchKernel,
    scratch: &mut SearchScratch,
    output: &mut Vec<SearchHit>,
) -> Result<PhaseTimings> {
    let total_start = Instant::now();
    let preparation = prepare_quantized_query(index, query, scratch)?;
    let kernel = resolve_kernel(requested);
    let top_k = top_k.min(index.len());
    scratch.scores.clear();
    scratch.scores.resize(index.len(), 0.0);

    let scan_start = Instant::now();
    compact::score_all_prepared(index, kernel, &scratch.lookup, &mut scratch.scores)?;
    let artifact_traversal_decode_accumulate_ns = nanos(scan_start.elapsed());

    let scale_start = Instant::now();
    for (score, scale) in scratch.scores.iter_mut().zip(index.scales()?) {
        *score *= scale;
    }
    let scale_correction_ns = nanos(scale_start.elapsed());

    scratch.heap.clear();
    let top_k_start = Instant::now();
    for (row, score) in scratch.scores.iter().copied().enumerate() {
        push_heap(&mut scratch.heap, top_k, score, row);
    }
    let top_k_ns = nanos(top_k_start.elapsed());

    let materialization_start = Instant::now();
    finish_heap(&mut scratch.heap, index.subject_ids()?, output);
    let result_materialization_ns = nanos(materialization_start.elapsed());
    Ok(PhaseTimings {
        rows: index.len(),
        top_k,
        workers: 1,
        kernel,
        query_rotation_ns: preparation.query_rotation_ns,
        query_lut_ns: preparation.query_lut_ns,
        artifact_traversal_decode_accumulate_ns,
        scale_correction_ns,
        top_k_ns,
        result_materialization_ns,
        thread_orchestration_ns: 0,
        total_ns: nanos(total_start.elapsed()),
    })
}

pub(crate) fn profile_parallel_quantized_search(
    index: &VerifiedQuantizedIndex,
    query: &[f32],
    top_k: usize,
    requested: SearchKernel,
    scratch: &mut SearchScratch,
    output: &mut Vec<SearchHit>,
) -> Result<PhaseTimings> {
    let total_start = Instant::now();
    let preparation = prepare_quantized_query(index, query, scratch)?;
    let kernel = resolve_kernel(requested);
    let top_k = top_k.min(index.len());
    scratch.scores.clear();
    scratch.scores.resize(index.len(), 0.0);
    let workers = rayon::current_num_threads();

    let orchestration_start = Instant::now();
    (0..workers).into_par_iter().for_each(|worker| {
        std::hint::black_box(worker);
    });
    let thread_orchestration_ns = nanos(orchestration_start.elapsed());

    let scan_start = Instant::now();
    compact::score_all_prepared_parallel(index, kernel, &scratch.lookup, &mut scratch.scores)?;
    let artifact_traversal_decode_accumulate_ns = nanos(scan_start.elapsed());

    let scale_start = Instant::now();
    scratch
        .scores
        .par_iter_mut()
        .zip(index.scales()?.par_iter())
        .for_each(|(score, scale)| *score *= scale);
    let scale_correction_ns = nanos(scale_start.elapsed());

    let top_k_start = Instant::now();
    retain_parallel_top_k(
        &scratch.scores,
        top_k,
        &mut scratch.local_top_k,
        &mut scratch.heap,
    );
    let top_k_ns = nanos(top_k_start.elapsed());

    let materialization_start = Instant::now();
    finish_heap(&mut scratch.heap, index.subject_ids()?, output);
    let result_materialization_ns = nanos(materialization_start.elapsed());
    Ok(PhaseTimings {
        rows: index.len(),
        top_k,
        workers,
        kernel,
        query_rotation_ns: preparation.query_rotation_ns,
        query_lut_ns: preparation.query_lut_ns,
        artifact_traversal_decode_accumulate_ns,
        scale_correction_ns,
        top_k_ns,
        result_materialization_ns,
        thread_orchestration_ns,
        total_ns: nanos(total_start.elapsed()),
    })
}

fn validate_query(index: &VerifiedQuantizedIndex, query: &[f32]) -> Result<()> {
    if query.len() != index.dimension() {
        return Err(TurboQuantError::QueryDimension {
            actual: query.len(),
            expected: index.dimension(),
        });
    }
    if let Some(coordinate) = query.iter().position(|value| !value.is_finite()) {
        return Err(TurboQuantError::NonFinite { row: 0, coordinate });
    }
    Ok(())
}

fn retain_parallel_top_k(
    scores: &[f32],
    top_k: usize,
    local_top_k: &mut Vec<FixedTopK>,
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
) {
    const CHUNK_ROWS: usize = 4_096;
    if top_k > 64 {
        heap.clear();
        for (row, score) in scores.iter().copied().enumerate() {
            push_heap(heap, top_k, score, row);
        }
        return;
    }
    let chunks = scores.len().div_ceil(CHUNK_ROWS);
    local_top_k.clear();
    local_top_k.resize_with(chunks, FixedTopK::default);
    local_top_k
        .par_iter_mut()
        .zip(scores.par_chunks(CHUNK_ROWS))
        .enumerate()
        .for_each(|(chunk, (local, chunk_scores))| {
            local.reset(top_k);
            let first_row = chunk * CHUNK_ROWS;
            for (offset, score) in chunk_scores.iter().copied().enumerate() {
                local.insert(HeapHit {
                    score,
                    row: first_row + offset,
                });
            }
        });
    heap.clear();
    for local in local_top_k {
        for hit in local.entries().iter().copied() {
            push_heap(heap, top_k, hit.score, hit.row);
        }
    }
}

fn validate_prepared(index: &VerifiedQuantizedIndex, scratch: &SearchScratch) -> Result<()> {
    match scratch.prepared_quantizer_hash {
        None => Err(TurboQuantError::UnpreparedQuery),
        Some(hash) if hash != index.header().quantizer_hash => {
            Err(TurboQuantError::PreparedContractMismatch)
        }
        Some(_) => Ok(()),
    }
}

fn resolve_kernel(requested: SearchKernel) -> SearchKernel {
    match requested {
        SearchKernel::Auto => {
            #[cfg(target_arch = "x86_64")]
            if std::arch::is_x86_feature_detected!("avx2") {
                return SearchKernel::Avx2;
            }
            SearchKernel::Scalar
        }
        SearchKernel::Avx2 => {
            #[cfg(target_arch = "x86_64")]
            if std::arch::is_x86_feature_detected!("avx2") {
                return SearchKernel::Avx2;
            }
            SearchKernel::Scalar
        }
        SearchKernel::Scalar => SearchKernel::Scalar,
    }
}

pub(crate) fn push_heap(
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
    top_k: usize,
    score: f32,
    row: usize,
) {
    let candidate = HeapHit { score, row };
    if heap.len() < top_k {
        heap.push(Reverse(candidate));
    } else if heap.peek().is_some_and(|current| candidate > current.0) {
        heap.pop();
        heap.push(Reverse(candidate));
    }
}

pub(crate) fn finish_heap(
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
    subject_ids: &[u64],
    output: &mut Vec<SearchHit>,
) {
    output.clear();
    output.extend(heap.drain().map(|Reverse(hit)| SearchHit {
        row: hit.row,
        subject_id: subject_ids[hit.row],
        score: hit.score,
    }));
    output.sort_unstable_by(|left, right| {
        right
            .score
            .total_cmp(&left.score)
            .then_with(|| left.row.cmp(&right.row))
    });
}

fn nanos(duration: Duration) -> u64 {
    duration.as_nanos().min(u64::MAX as u128) as u64
}
