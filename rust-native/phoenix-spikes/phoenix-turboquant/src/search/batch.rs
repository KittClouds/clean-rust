use std::cmp::Reverse;
use std::collections::BinaryHeap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

use rayon::prelude::*;

use crate::format::BLOCK_VECTORS;
use crate::{Result, SearchHit, SearchKernel, TurboQuantError, VerifiedQuantizedIndex};

use super::compact::{self, CompactLookup};
use super::{finish_heap, nanos, push_heap, resolve_kernel, validate_query, HeapHit};

/// Upper bound chosen to keep per-block accumulators in a small fixed frame.
pub const MAX_BATCH_QUERIES: usize = 8;
pub const MAX_BLOCK_ROWS: usize = 4_096;
pub const MAX_LOCAL_K: usize = 128;

/// Cache-block and local-candidate geometry for exact block-local reduction.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BlockLocalTopKConfig {
    pub block_rows: usize,
    pub local_k: usize,
}

#[derive(Clone, Copy, Debug, Default, serde::Serialize)]
pub struct BlockLocalPhaseTimings {
    pub query_preparation_ns: u64,
    pub parallel_score_select_wall_ns: u64,
    pub decode_work_ns: u64,
    pub local_selection_work_ns: u64,
    pub global_merge_materialization_ns: u64,
    pub total_ns: u64,
}

#[derive(Default)]
struct BlockPhaseCounters {
    decode_ns: AtomicU64,
    selection_ns: AtomicU64,
}

impl Default for BlockLocalTopKConfig {
    fn default() -> Self {
        Self {
            block_rows: 512,
            local_k: 64,
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct BlockHit {
    score: f32,
    row: u32,
}

impl BlockHit {
    const EMPTY: Self = Self {
        score: f32::NEG_INFINITY,
        row: u32::MAX,
    };

    #[inline]
    fn better_than(self, other: Self) -> bool {
        self.score
            .total_cmp(&other.score)
            .then_with(|| other.row.cmp(&self.row))
            .is_gt()
    }
}

#[derive(Clone, Debug)]
struct BlockTopK {
    entries: [BlockHit; MAX_LOCAL_K],
    len: usize,
    limit: usize,
}

impl Default for BlockTopK {
    fn default() -> Self {
        Self {
            entries: [BlockHit::EMPTY; MAX_LOCAL_K],
            len: 0,
            limit: 0,
        }
    }
}

impl BlockTopK {
    #[inline]
    fn reset(&mut self, limit: usize) {
        self.len = 0;
        self.limit = limit;
    }

    #[inline]
    fn insert(&mut self, candidate: BlockHit) {
        if self.len < self.limit {
            let mut index = self.len;
            self.entries[index] = candidate;
            self.len += 1;
            while index > 0 {
                let parent = (index - 1) / 2;
                if !self.entries[parent].better_than(self.entries[index]) {
                    break;
                }
                self.entries.swap(parent, index);
                index = parent;
            }
        } else if candidate.better_than(self.entries[0]) {
            self.entries[0] = candidate;
            let mut index = 0;
            loop {
                let left = index * 2 + 1;
                if left >= self.len {
                    break;
                }
                let right = left + 1;
                let worse =
                    if right < self.len && self.entries[left].better_than(self.entries[right]) {
                        right
                    } else {
                        left
                    };
                if !self.entries[index].better_than(self.entries[worse]) {
                    break;
                }
                self.entries.swap(index, worse);
                index = worse;
            }
        }
    }

    fn entries(&self) -> &[BlockHit] {
        &self.entries[..self.len]
    }
}

struct BlockScoreScratch {
    values: [f32; MAX_BLOCK_ROWS * MAX_BATCH_QUERIES],
}

impl Default for BlockScoreScratch {
    fn default() -> Self {
        Self {
            values: [0.0; MAX_BLOCK_ROWS * MAX_BATCH_QUERIES],
        }
    }
}

/// Reusable storage for packed-block multi-query search.
#[derive(Debug)]
pub struct BatchSearchScratch {
    rotated: Vec<f32>,
    rotation_scratch: Vec<f32>,
    lookups: Vec<CompactLookup>,
    scores: Vec<f32>,
    heaps: Vec<BinaryHeap<Reverse<HeapHit>>>,
    block_candidates: Vec<BlockTopK>,
    top_k_capacity: usize,
}

impl BatchSearchScratch {
    pub fn new(dimension: usize, batch_capacity: usize, top_k: usize) -> Self {
        let capacity = batch_capacity.min(MAX_BATCH_QUERIES);
        let mut lookups = Vec::with_capacity(capacity);
        lookups.resize_with(capacity, CompactLookup::default);
        let mut heaps = Vec::with_capacity(capacity);
        heaps.resize_with(capacity, || BinaryHeap::with_capacity(top_k));
        Self {
            rotated: vec![0.0; dimension],
            rotation_scratch: vec![0.0; dimension],
            lookups,
            scores: Vec::new(),
            heaps,
            block_candidates: Vec::new(),
            top_k_capacity: top_k,
        }
    }

    /// Capacities used by the warmed-path allocation regression gate.
    pub fn capacities(&self) -> (usize, usize, usize, usize, usize, usize, usize) {
        (
            self.rotated.capacity(),
            self.rotation_scratch.capacity(),
            self.lookups.capacity(),
            self.lookups.iter().map(CompactLookup::capacity).sum(),
            self.scores.capacity(),
            self.heaps.iter().map(BinaryHeap::capacity).sum(),
            self.block_candidates.capacity(),
        )
    }
}

pub(crate) fn search_batch_parallel<Q: AsRef<[f32]>>(
    index: &VerifiedQuantizedIndex,
    queries: &[Q],
    top_k: usize,
    requested: SearchKernel,
    scratch: &mut BatchSearchScratch,
    outputs: &mut [Vec<SearchHit>],
) -> Result<SearchKernel> {
    let query_count = queries.len();
    validate_batch_shape(query_count, outputs.len())?;
    prepare_queries(index, queries, scratch)?;

    let top_k = top_k.min(index.len());
    let score_count = index
        .len()
        .checked_mul(query_count)
        .ok_or(TurboQuantError::Overflow)?;
    scratch.scores.clear();
    scratch.scores.resize(score_count, 0.0);
    ensure_heaps(scratch, query_count, top_k);
    let kernel = resolve_kernel(requested);
    if top_k == 0 {
        outputs.iter_mut().for_each(Vec::clear);
        return Ok(kernel);
    }

    score_interleaved(
        index,
        kernel,
        &scratch.lookups[..query_count],
        &mut scratch.scores,
    )?;
    let subject_ids = index.subject_ids()?;
    scratch.heaps[..query_count]
        .par_iter_mut()
        .zip(outputs.par_iter_mut())
        .enumerate()
        .for_each(|(query, (heap, output))| {
            heap.clear();
            for row in 0..index.len() {
                push_heap(heap, top_k, scratch.scores[row * query_count + query], row);
            }
            finish_heap(heap, subject_ids, output);
        });
    Ok(kernel)
}

pub(crate) fn search_batch_block_local<Q: AsRef<[f32]>>(
    index: &VerifiedQuantizedIndex,
    queries: &[Q],
    top_k: usize,
    requested: SearchKernel,
    config: BlockLocalTopKConfig,
    scratch: &mut BatchSearchScratch,
    outputs: &mut [Vec<SearchHit>],
) -> Result<SearchKernel> {
    Ok(search_batch_block_local_impl::<false, Q>(
        index, queries, top_k, requested, config, scratch, outputs,
    )?
    .0)
}

pub(crate) fn profile_batch_block_local<Q: AsRef<[f32]>>(
    index: &VerifiedQuantizedIndex,
    queries: &[Q],
    top_k: usize,
    requested: SearchKernel,
    config: BlockLocalTopKConfig,
    scratch: &mut BatchSearchScratch,
    outputs: &mut [Vec<SearchHit>],
) -> Result<BlockLocalPhaseTimings> {
    Ok(search_batch_block_local_impl::<true, Q>(
        index, queries, top_k, requested, config, scratch, outputs,
    )?
    .1)
}

#[allow(clippy::too_many_arguments)]
fn search_batch_block_local_impl<const PROFILE: bool, Q: AsRef<[f32]>>(
    index: &VerifiedQuantizedIndex,
    queries: &[Q],
    top_k: usize,
    requested: SearchKernel,
    config: BlockLocalTopKConfig,
    scratch: &mut BatchSearchScratch,
    outputs: &mut [Vec<SearchHit>],
) -> Result<(SearchKernel, BlockLocalPhaseTimings)> {
    let total_start = Instant::now();
    let mut timings = BlockLocalPhaseTimings::default();
    let query_count = queries.len();
    validate_batch_shape(query_count, outputs.len())?;
    validate_block_local(top_k, config)?;
    let preparation_start = Instant::now();
    prepare_queries(index, queries, scratch)?;
    if PROFILE {
        timings.query_preparation_ns = nanos(preparation_start.elapsed());
    }
    let top_k = top_k.min(index.len());
    let kernel = resolve_kernel(requested);
    if top_k == 0 {
        outputs.iter_mut().for_each(Vec::clear);
        timings.total_ns = nanos(total_start.elapsed());
        return Ok((kernel, timings));
    }

    let chunks = index.len().div_ceil(config.block_rows);
    let candidate_count = chunks
        .checked_mul(query_count)
        .ok_or(TurboQuantError::Overflow)?;
    scratch.block_candidates.clear();
    scratch
        .block_candidates
        .resize_with(candidate_count, BlockTopK::default);
    match query_count {
        1 => score_reduce_blocks::<1, PROFILE>(
            index,
            kernel,
            top_k,
            config,
            scratch,
            outputs,
            &mut timings,
        )?,
        2 => score_reduce_blocks::<2, PROFILE>(
            index,
            kernel,
            top_k,
            config,
            scratch,
            outputs,
            &mut timings,
        )?,
        3 => score_reduce_blocks::<3, PROFILE>(
            index,
            kernel,
            top_k,
            config,
            scratch,
            outputs,
            &mut timings,
        )?,
        4 => score_reduce_blocks::<4, PROFILE>(
            index,
            kernel,
            top_k,
            config,
            scratch,
            outputs,
            &mut timings,
        )?,
        5 => score_reduce_blocks::<5, PROFILE>(
            index,
            kernel,
            top_k,
            config,
            scratch,
            outputs,
            &mut timings,
        )?,
        6 => score_reduce_blocks::<6, PROFILE>(
            index,
            kernel,
            top_k,
            config,
            scratch,
            outputs,
            &mut timings,
        )?,
        7 => score_reduce_blocks::<7, PROFILE>(
            index,
            kernel,
            top_k,
            config,
            scratch,
            outputs,
            &mut timings,
        )?,
        8 => score_reduce_blocks::<8, PROFILE>(
            index,
            kernel,
            top_k,
            config,
            scratch,
            outputs,
            &mut timings,
        )?,
        _ => unreachable!(),
    }
    if PROFILE {
        timings.total_ns = nanos(total_start.elapsed());
    }
    Ok((kernel, timings))
}

fn validate_block_local(top_k: usize, config: BlockLocalTopKConfig) -> Result<()> {
    if top_k > 64 {
        return Err(TurboQuantError::BlockLocalTopKTooLarge(top_k));
    }
    if config.block_rows == 0
        || !config.block_rows.is_multiple_of(BLOCK_VECTORS)
        || config.block_rows > MAX_BLOCK_ROWS
    {
        return Err(TurboQuantError::InvalidBlockRows(config.block_rows));
    }
    if config.local_k < top_k || config.local_k > MAX_LOCAL_K {
        return Err(TurboQuantError::InvalidLocalK {
            local_k: config.local_k,
            top_k,
        });
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn score_reduce_blocks<const QUERIES: usize, const PROFILE: bool>(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    top_k: usize,
    config: BlockLocalTopKConfig,
    scratch: &mut BatchSearchScratch,
    outputs: &mut [Vec<SearchHit>],
    timings: &mut BlockLocalPhaseTimings,
) -> Result<()> {
    let codes = index.codes()?;
    let scales = index.scales()?;
    let lookups = &scratch.lookups[..QUERIES];
    let counters = BlockPhaseCounters::default();
    let parallel_start = Instant::now();
    scratch
        .block_candidates
        .par_chunks_mut(QUERIES)
        .enumerate()
        .for_each_init(
            BlockScoreScratch::default,
            |block_scores, (chunk, local)| {
                let first_row = chunk * config.block_rows;
                let rows = (index.len() - first_row).min(config.block_rows);
                let score_slice = &mut block_scores.values[..rows * QUERIES];
                let decode_start = Instant::now();
                score_cache_block::<QUERIES>(
                    index,
                    kernel,
                    first_row,
                    rows,
                    lookups,
                    codes,
                    scales,
                    score_slice,
                );
                if PROFILE {
                    counters
                        .decode_ns
                        .fetch_add(nanos(decode_start.elapsed()), Ordering::Relaxed);
                }
                let selection_start = Instant::now();
                for selector in local.iter_mut() {
                    selector.reset(config.local_k.min(rows));
                }
                for row in 0..rows {
                    for query in 0..QUERIES {
                        local[query].insert(BlockHit {
                            score: score_slice[row * QUERIES + query],
                            row: (first_row + row) as u32,
                        });
                    }
                }
                if PROFILE {
                    counters
                        .selection_ns
                        .fetch_add(nanos(selection_start.elapsed()), Ordering::Relaxed);
                }
            },
        );

    if PROFILE {
        timings.parallel_score_select_wall_ns = nanos(parallel_start.elapsed());
        timings.decode_work_ns = counters.decode_ns.load(Ordering::Relaxed);
        timings.local_selection_work_ns = counters.selection_ns.load(Ordering::Relaxed);
    }

    let merge_start = Instant::now();
    let mut global: [BlockTopK; QUERIES] = std::array::from_fn(|_| BlockTopK::default());
    for selector in &mut global {
        selector.reset(top_k);
    }
    for chunk in scratch.block_candidates.chunks_exact(QUERIES) {
        for query in 0..QUERIES {
            for candidate in chunk[query].entries().iter().copied() {
                global[query].insert(candidate);
            }
        }
    }
    let subject_ids = index.subject_ids()?;
    for (query, output) in outputs.iter_mut().enumerate() {
        output.clear();
        output.extend(global[query].entries().iter().map(|candidate| SearchHit {
            row: candidate.row as usize,
            subject_id: subject_ids[candidate.row as usize],
            score: candidate.score,
        }));
        output.sort_unstable_by(|left, right| {
            right
                .score
                .total_cmp(&left.score)
                .then_with(|| left.row.cmp(&right.row))
        });
    }
    if PROFILE {
        timings.global_merge_materialization_ns = nanos(merge_start.elapsed());
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn score_cache_block<const QUERIES: usize>(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    first_row: usize,
    rows: usize,
    lookups: &[CompactLookup],
    codes: &[u8],
    scales: &[f32],
    output: &mut [f32],
) {
    let groups = match index.bits() {
        2 => index.dimension() / 4,
        4 => index.dimension() / 2,
        _ => unreachable!(),
    };
    let first_block = first_row / BLOCK_VECTORS;
    for local_block in 0..rows.div_ceil(BLOCK_VECTORS) {
        let block = first_block + local_block;
        let scores = match (index.bits(), kernel) {
            (2, SearchKernel::Scalar) => {
                score_2bit_batch_block_scalar::<QUERIES>(block, groups, lookups, codes)
            }
            (4, SearchKernel::Scalar) => {
                score_4bit_batch_block_scalar::<QUERIES>(block, groups, lookups, codes)
            }
            (2, SearchKernel::Avx2) => {
                #[cfg(target_arch = "x86_64")]
                unsafe {
                    score_2bit_batch_block_avx2::<QUERIES>(block, groups, lookups, codes)
                }
                #[cfg(not(target_arch = "x86_64"))]
                score_2bit_batch_block_scalar::<QUERIES>(block, groups, lookups, codes)
            }
            (4, SearchKernel::Avx2) => {
                #[cfg(target_arch = "x86_64")]
                unsafe {
                    score_4bit_batch_block_avx2::<QUERIES>(block, groups, lookups, codes)
                }
                #[cfg(not(target_arch = "x86_64"))]
                score_4bit_batch_block_scalar::<QUERIES>(block, groups, lookups, codes)
            }
            (_, SearchKernel::Auto) => unreachable!(),
            _ => unreachable!(),
        };
        let destination_start = local_block * BLOCK_VECTORS * QUERIES;
        let active = (rows - local_block * BLOCK_VECTORS).min(BLOCK_VECTORS);
        write_scaled_rows::<QUERIES>(
            block,
            active,
            &mut output[destination_start..destination_start + active * QUERIES],
            &scores,
            scales,
        );
    }
}

fn write_scaled_rows<const QUERIES: usize>(
    block: usize,
    active: usize,
    destination: &mut [f32],
    scores: &[[f32; BLOCK_VECTORS]; QUERIES],
    scales: &[f32],
) {
    let first_row = block * BLOCK_VECTORS;
    for candidate in 0..active {
        let scale = scales[first_row + candidate];
        for query in 0..QUERIES {
            destination[candidate * QUERIES + query] = scores[query][candidate] * scale;
        }
    }
}

fn validate_batch_shape(query_count: usize, output_count: usize) -> Result<()> {
    if !(1..=MAX_BATCH_QUERIES).contains(&query_count) {
        return Err(TurboQuantError::InvalidBatchSize {
            actual: query_count,
            maximum: MAX_BATCH_QUERIES,
        });
    }
    if output_count != query_count {
        return Err(TurboQuantError::BatchOutputLength {
            actual: output_count,
            expected: query_count,
        });
    }
    Ok(())
}

fn ensure_heaps(scratch: &mut BatchSearchScratch, query_count: usize, top_k: usize) {
    if scratch.lookups.len() < query_count {
        scratch
            .lookups
            .resize_with(query_count, CompactLookup::default);
    }
    if scratch.heaps.len() < query_count {
        let capacity = scratch.top_k_capacity.max(top_k);
        scratch
            .heaps
            .resize_with(query_count, || BinaryHeap::with_capacity(capacity));
    }
    if top_k > scratch.top_k_capacity {
        for heap in &mut scratch.heaps[..query_count] {
            heap.reserve(top_k.saturating_sub(heap.capacity()));
        }
        scratch.top_k_capacity = top_k;
    }
}

fn prepare_queries<Q: AsRef<[f32]>>(
    index: &VerifiedQuantizedIndex,
    queries: &[Q],
    scratch: &mut BatchSearchScratch,
) -> Result<()> {
    ensure_heaps(scratch, queries.len(), scratch.top_k_capacity);
    scratch.rotated.resize(index.dimension(), 0.0);
    scratch.rotation_scratch.resize(index.dimension(), 0.0);
    for (query, lookup) in queries.iter().zip(&mut scratch.lookups) {
        let query = query.as_ref();
        validate_query(index, query)?;
        scratch.rotated.copy_from_slice(query);
        index
            .rotation()
            .apply(&mut scratch.rotated, &mut scratch.rotation_scratch);
        compact::build_lookup(index, &scratch.rotated, lookup);
    }
    Ok(())
}

fn score_interleaved(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    lookups: &[CompactLookup],
    output: &mut [f32],
) -> Result<()> {
    debug_assert_eq!(lookups.len(), scratch_query_count(output, index.len()));
    match lookups.len() {
        1 => score_interleaved_const::<1>(index, kernel, lookups, output),
        2 => score_interleaved_const::<2>(index, kernel, lookups, output),
        3 => score_interleaved_const::<3>(index, kernel, lookups, output),
        4 => score_interleaved_const::<4>(index, kernel, lookups, output),
        5 => score_interleaved_const::<5>(index, kernel, lookups, output),
        6 => score_interleaved_const::<6>(index, kernel, lookups, output),
        7 => score_interleaved_const::<7>(index, kernel, lookups, output),
        8 => score_interleaved_const::<8>(index, kernel, lookups, output),
        _ => unreachable!(),
    }
}

fn scratch_query_count(output: &[f32], rows: usize) -> usize {
    output.len().checked_div(rows).unwrap_or(0)
}

fn score_interleaved_const<const QUERIES: usize>(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    lookups: &[CompactLookup],
    output: &mut [f32],
) -> Result<()> {
    let codes = index.codes()?;
    let scales = index.scales()?;
    match index.bits() {
        2 => score_2bit_batch::<QUERIES>(index, kernel, lookups, codes, scales, output),
        4 => score_4bit_batch::<QUERIES>(index, kernel, lookups, codes, scales, output),
        _ => unreachable!(),
    }
    Ok(())
}

fn score_2bit_batch<const QUERIES: usize>(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    lookups: &[CompactLookup],
    codes: &[u8],
    scales: &[f32],
    output: &mut [f32],
) {
    let groups = index.dimension() / 4;
    output
        .par_chunks_mut(QUERIES * BLOCK_VECTORS)
        .enumerate()
        .for_each(|(block, destination)| {
            let scores = match kernel {
                SearchKernel::Scalar => {
                    score_2bit_batch_block_scalar::<QUERIES>(block, groups, lookups, codes)
                }
                SearchKernel::Avx2 => {
                    #[cfg(target_arch = "x86_64")]
                    unsafe {
                        score_2bit_batch_block_avx2::<QUERIES>(block, groups, lookups, codes)
                    }
                    #[cfg(not(target_arch = "x86_64"))]
                    score_2bit_batch_block_scalar::<QUERIES>(block, groups, lookups, codes)
                }
                SearchKernel::Auto => unreachable!(),
            };
            write_scaled::<QUERIES>(block, destination, &scores, scales);
        });
}

fn score_4bit_batch<const QUERIES: usize>(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    lookups: &[CompactLookup],
    codes: &[u8],
    scales: &[f32],
    output: &mut [f32],
) {
    let groups = index.dimension() / 2;
    output
        .par_chunks_mut(QUERIES * BLOCK_VECTORS)
        .enumerate()
        .for_each(|(block, destination)| {
            let scores = match kernel {
                SearchKernel::Scalar => {
                    score_4bit_batch_block_scalar::<QUERIES>(block, groups, lookups, codes)
                }
                SearchKernel::Avx2 => {
                    #[cfg(target_arch = "x86_64")]
                    unsafe {
                        score_4bit_batch_block_avx2::<QUERIES>(block, groups, lookups, codes)
                    }
                    #[cfg(not(target_arch = "x86_64"))]
                    score_4bit_batch_block_scalar::<QUERIES>(block, groups, lookups, codes)
                }
                SearchKernel::Auto => unreachable!(),
            };
            write_scaled::<QUERIES>(block, destination, &scores, scales);
        });
}

fn score_2bit_batch_block_scalar<const QUERIES: usize>(
    block: usize,
    groups: usize,
    lookups: &[CompactLookup],
    codes: &[u8],
) -> [[f32; BLOCK_VECTORS]; QUERIES] {
    score_batch_block_scalar::<QUERIES>(block, groups, lookups, codes)
}

fn score_4bit_batch_block_scalar<const QUERIES: usize>(
    block: usize,
    groups: usize,
    lookups: &[CompactLookup],
    codes: &[u8],
) -> [[f32; BLOCK_VECTORS]; QUERIES] {
    score_batch_block_scalar::<QUERIES>(block, groups, lookups, codes)
}

fn score_batch_block_scalar<const QUERIES: usize>(
    block: usize,
    groups: usize,
    lookups: &[CompactLookup],
    codes: &[u8],
) -> [[f32; BLOCK_VECTORS]; QUERIES] {
    let mut sums = [[0u32; BLOCK_VECTORS]; QUERIES];
    for group in 0..groups {
        let source = (block * groups + group) * BLOCK_VECTORS;
        for candidate in 0..BLOCK_VECTORS {
            let packed = codes[source + candidate];
            let low = (packed & 0x0f) as usize;
            let high = 16 + (packed >> 4) as usize;
            for query in 0..QUERIES {
                let table = &lookups[query].bytes()[group * 32..];
                sums[query][candidate] += table[low] as u32 + table[high] as u32;
            }
        }
    }
    std::array::from_fn(|query| {
        sums[query].map(|sum| lookups[query].bias() + lookups[query].scale() * sum as f32)
    })
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn score_2bit_batch_block_avx2<const QUERIES: usize>(
    block: usize,
    groups: usize,
    lookups: &[CompactLookup],
    codes: &[u8],
) -> [[f32; BLOCK_VECTORS]; QUERIES] {
    use std::arch::x86_64::*;

    let mask = _mm_set1_epi8(0x0f);
    let mut low_sums = [_mm_setzero_si128(); QUERIES];
    let mut high_sums = [_mm_setzero_si128(); QUERIES];
    for group in 0..groups {
        let source = (block * groups + group) * BLOCK_VECTORS;
        let packed = _mm_loadl_epi64(codes.as_ptr().add(source).cast());
        let low_codes = _mm_and_si128(packed, mask);
        let high_codes = _mm_and_si128(_mm_srli_epi16(packed, 4), mask);
        for query in 0..QUERIES {
            let table = lookups[query].bytes().as_ptr().add(group * 32);
            low_sums[query] = _mm_add_epi16(
                low_sums[query],
                _mm_cvtepu8_epi16(_mm_shuffle_epi8(_mm_loadu_si128(table.cast()), low_codes)),
            );
            high_sums[query] = _mm_add_epi16(
                high_sums[query],
                _mm_cvtepu8_epi16(_mm_shuffle_epi8(
                    _mm_loadu_si128(table.add(16).cast()),
                    high_codes,
                )),
            );
        }
    }
    std::array::from_fn(|query| {
        compact::finish_accumulators(low_sums[query], high_sums[query], &lookups[query])
    })
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn score_4bit_batch_block_avx2<const QUERIES: usize>(
    block: usize,
    groups: usize,
    lookups: &[CompactLookup],
    codes: &[u8],
) -> [[f32; BLOCK_VECTORS]; QUERIES] {
    use std::arch::x86_64::*;

    let mask = _mm_set1_epi8(0x0f);
    let mut low_sums = [_mm_setzero_si128(); QUERIES];
    let mut high_sums = [_mm_setzero_si128(); QUERIES];
    for group in 0..groups {
        let source = (block * groups + group) * BLOCK_VECTORS;
        let packed = _mm_loadl_epi64(codes.as_ptr().add(source).cast());
        let low_codes = _mm_and_si128(packed, mask);
        let high_codes = _mm_and_si128(_mm_srli_epi16(packed, 4), mask);
        for query in 0..QUERIES {
            let table = lookups[query].bytes().as_ptr().add(group * 32);
            low_sums[query] = _mm_add_epi16(
                low_sums[query],
                _mm_cvtepu8_epi16(_mm_shuffle_epi8(_mm_loadu_si128(table.cast()), low_codes)),
            );
            high_sums[query] = _mm_add_epi16(
                high_sums[query],
                _mm_cvtepu8_epi16(_mm_shuffle_epi8(
                    _mm_loadu_si128(table.add(16).cast()),
                    high_codes,
                )),
            );
        }
    }
    std::array::from_fn(|query| {
        compact::finish_accumulators(low_sums[query], high_sums[query], &lookups[query])
    })
}

fn write_scaled<const QUERIES: usize>(
    block: usize,
    destination: &mut [f32],
    scores: &[[f32; BLOCK_VECTORS]; QUERIES],
    scales: &[f32],
) {
    let first_row = block * BLOCK_VECTORS;
    let active = destination.len() / QUERIES;
    for candidate in 0..active {
        let scale = scales[first_row + candidate];
        for query in 0..QUERIES {
            destination[candidate * QUERIES + query] = scores[query][candidate] * scale;
        }
    }
}
