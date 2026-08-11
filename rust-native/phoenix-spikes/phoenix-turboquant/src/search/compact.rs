use std::cmp::Reverse;
use std::collections::BinaryHeap;

use rayon::prelude::*;

use crate::format::BLOCK_VECTORS;
use crate::{Result, SearchKernel, VerifiedQuantizedIndex};

use super::{push_heap, HeapHit};

const LUT_VALUES_PER_GROUP: usize = 32;
const LUT_MAX: f32 = 127.0;
const PARALLEL_VECTORS: usize = BLOCK_VECTORS * 2;

#[derive(Debug, Default)]
pub(super) struct CompactLookup {
    bytes: Vec<u8>,
    scale: f32,
    bias: f32,
}

impl CompactLookup {
    pub(super) fn capacity(&self) -> usize {
        self.bytes.capacity()
    }

    #[inline]
    pub(super) fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[inline]
    pub(super) fn scale(&self) -> f32 {
        self.scale
    }

    #[inline]
    pub(super) fn bias(&self) -> f32 {
        self.bias
    }
}

pub(super) fn build_lookup(
    index: &VerifiedQuantizedIndex,
    query: &[f32],
    lookup: &mut CompactLookup,
) {
    match index.bits() {
        2 => build_2bit_lookup(index, query, lookup),
        4 => build_4bit_lookup(index, query, lookup),
        _ => unreachable!(),
    }
}

fn build_2bit_lookup(index: &VerifiedQuantizedIndex, query: &[f32], lookup: &mut CompactLookup) {
    let groups = index.dimension() / 4;
    let centroids = index.codebook().centroids();
    lookup.bytes.clear();
    lookup.bytes.resize(groups * LUT_VALUES_PER_GROUP, 0);
    let mut max_span = 0.0f32;
    let mut bias = 0.0f32;
    for group in 0..groups {
        let values = values_2bit(group, query, centroids);
        let (lo_min, lo_max) = min_max(&values[..16]);
        let (hi_min, hi_max) = min_max(&values[16..]);
        bias += lo_min + hi_min;
        max_span = max_span.max(lo_max - lo_min).max(hi_max - hi_min);
    }
    let scale = stable_scale(max_span);
    let inverse = scale.recip();
    for group in 0..groups {
        let values = values_2bit(group, query, centroids);
        quantize_group(
            &values,
            &mut lookup.bytes[group * LUT_VALUES_PER_GROUP..(group + 1) * LUT_VALUES_PER_GROUP],
            inverse,
        );
    }
    lookup.scale = scale;
    lookup.bias = bias;
}

fn build_4bit_lookup(index: &VerifiedQuantizedIndex, query: &[f32], lookup: &mut CompactLookup) {
    let groups = index.dimension() / 2;
    let centroids = index.codebook().centroids();
    lookup.bytes.clear();
    lookup.bytes.resize(groups * LUT_VALUES_PER_GROUP, 0);
    let mut max_span = 0.0f32;
    let mut bias = 0.0f32;
    for group in 0..groups {
        let values = values_4bit(group, query, centroids);
        let (lo_min, lo_max) = min_max(&values[..16]);
        let (hi_min, hi_max) = min_max(&values[16..]);
        bias += lo_min + hi_min;
        max_span = max_span.max(lo_max - lo_min).max(hi_max - hi_min);
    }
    let scale = stable_scale(max_span);
    let inverse = scale.recip();
    for group in 0..groups {
        let values = values_4bit(group, query, centroids);
        quantize_group(
            &values,
            &mut lookup.bytes[group * LUT_VALUES_PER_GROUP..(group + 1) * LUT_VALUES_PER_GROUP],
            inverse,
        );
    }
    lookup.scale = scale;
    lookup.bias = bias;
}

#[inline]
fn values_2bit(group: usize, query: &[f32], centroids: &[f32]) -> [f32; 32] {
    let start = group * 4;
    let mut values = [0.0f32; 32];
    for nibble in 0..16 {
        let first = nibble & 0b11;
        let second = (nibble >> 2) & 0b11;
        values[nibble] = query[start] * centroids[first] + query[start + 1] * centroids[second];
        values[16 + nibble] =
            query[start + 2] * centroids[first] + query[start + 3] * centroids[second];
    }
    values
}

#[inline]
fn values_4bit(group: usize, query: &[f32], centroids: &[f32]) -> [f32; 32] {
    let start = group * 2;
    let mut values = [0.0f32; 32];
    for code in 0..16 {
        values[code] = query[start] * centroids[code];
        values[16 + code] = query[start + 1] * centroids[code];
    }
    values
}

fn quantize_group(values: &[f32; 32], destination: &mut [u8], inverse: f32) {
    let (lo_min, _) = min_max(&values[..16]);
    let (hi_min, _) = min_max(&values[16..]);
    for index in 0..16 {
        destination[index] = quantize_lut_value(values[index], lo_min, inverse);
        destination[16 + index] = quantize_lut_value(values[16 + index], hi_min, inverse);
    }
}

#[inline]
fn quantize_lut_value(value: f32, minimum: f32, inverse: f32) -> u8 {
    ((value - minimum) * inverse).round().clamp(0.0, LUT_MAX) as u8
}

fn min_max(values: &[f32]) -> (f32, f32) {
    values.iter().copied().fold(
        (f32::INFINITY, f32::NEG_INFINITY),
        |(minimum, maximum), value| (minimum.min(value), maximum.max(value)),
    )
}

fn stable_scale(max_span: f32) -> f32 {
    let scale = max_span / LUT_MAX;
    if scale >= f32::MIN_POSITIVE {
        scale
    } else {
        1.0
    }
}

pub(super) fn score_scalar(
    index: &VerifiedQuantizedIndex,
    lookup: &CompactLookup,
    codes: &[u8],
    scales: &[f32],
    top_k: usize,
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
) {
    match index.bits() {
        2 => score_2bit_scalar(index, lookup, codes, scales, top_k, heap),
        4 => score_4bit_scalar(index, lookup, codes, scales, top_k, heap),
        _ => unreachable!(),
    }
}

fn score_2bit_scalar(
    index: &VerifiedQuantizedIndex,
    lookup: &CompactLookup,
    codes: &[u8],
    scales: &[f32],
    top_k: usize,
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
) {
    let groups = index.dimension() / 4;
    for block in 0..index.header().padded_count as usize / BLOCK_VECTORS {
        let first_row = block * BLOCK_VECTORS;
        let active = (index.len() - first_row).min(BLOCK_VECTORS);
        let scores = score_2bit_block_scalar(block, groups, lookup, codes);
        retain_block(first_row, active, scores, lookup, scales, top_k, heap);
    }
}

fn score_4bit_scalar(
    index: &VerifiedQuantizedIndex,
    lookup: &CompactLookup,
    codes: &[u8],
    scales: &[f32],
    top_k: usize,
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
) {
    let groups = index.dimension() / 2;
    for block in 0..index.header().padded_count as usize / BLOCK_VECTORS {
        let first_row = block * BLOCK_VECTORS;
        let active = (index.len() - first_row).min(BLOCK_VECTORS);
        let scores = score_4bit_block_scalar(block, groups, lookup, codes);
        retain_block(first_row, active, scores, lookup, scales, top_k, heap);
    }
}

#[inline]
fn score_2bit_block_scalar(
    block: usize,
    groups: usize,
    lookup: &CompactLookup,
    codes: &[u8],
) -> [u32; BLOCK_VECTORS] {
    let mut scores = [0u32; BLOCK_VECTORS];
    for group in 0..groups {
        let source = (block * groups + group) * BLOCK_VECTORS;
        let table = &lookup.bytes[group * 32..(group + 1) * 32];
        for (candidate, score) in scores.iter_mut().enumerate() {
            let packed = codes[source + candidate];
            *score += table[(packed & 0x0f) as usize] as u32;
            *score += table[16 + (packed >> 4) as usize] as u32;
        }
    }
    scores
}

#[inline]
fn score_4bit_block_scalar(
    block: usize,
    groups: usize,
    lookup: &CompactLookup,
    codes: &[u8],
) -> [u32; BLOCK_VECTORS] {
    let mut scores = [0u32; BLOCK_VECTORS];
    for group in 0..groups {
        let source = (block * groups + group) * BLOCK_VECTORS;
        let table = &lookup.bytes[group * 32..(group + 1) * 32];
        for (candidate, score) in scores.iter_mut().enumerate() {
            let packed = codes[source + candidate];
            *score += table[(packed & 0x0f) as usize] as u32;
            *score += table[16 + (packed >> 4) as usize] as u32;
        }
    }
    scores
}

fn retain_block(
    first_row: usize,
    active: usize,
    scores: [u32; BLOCK_VECTORS],
    lookup: &CompactLookup,
    scales: &[f32],
    top_k: usize,
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
) {
    for (candidate, score) in scores.iter().take(active).copied().enumerate() {
        let row = first_row + candidate;
        let corrected = (lookup.bias + lookup.scale * score as f32) * scales[row];
        push_heap(heap, top_k, corrected, row);
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
pub(super) unsafe fn score_avx2(
    index: &VerifiedQuantizedIndex,
    lookup: &CompactLookup,
    codes: &[u8],
    scales: &[f32],
    top_k: usize,
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
) {
    match index.bits() {
        2 => score_2bit_avx2(index, lookup, codes, scales, top_k, heap),
        4 => score_4bit_avx2(index, lookup, codes, scales, top_k, heap),
        _ => unreachable!(),
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn score_2bit_avx2(
    index: &VerifiedQuantizedIndex,
    lookup: &CompactLookup,
    codes: &[u8],
    scales: &[f32],
    top_k: usize,
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
) {
    let groups = index.dimension() / 4;
    for block in 0..index.header().padded_count as usize / BLOCK_VECTORS {
        let first_row = block * BLOCK_VECTORS;
        let active = (index.len() - first_row).min(BLOCK_VECTORS);
        let scores = score_2bit_block_avx2(block, groups, lookup, codes);
        retain_float_block(first_row, active, scores, scales, top_k, heap);
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn score_4bit_avx2(
    index: &VerifiedQuantizedIndex,
    lookup: &CompactLookup,
    codes: &[u8],
    scales: &[f32],
    top_k: usize,
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
) {
    let groups = index.dimension() / 2;
    for block in 0..index.header().padded_count as usize / BLOCK_VECTORS {
        let first_row = block * BLOCK_VECTORS;
        let active = (index.len() - first_row).min(BLOCK_VECTORS);
        let scores = score_4bit_block_avx2(block, groups, lookup, codes);
        retain_float_block(first_row, active, scores, scales, top_k, heap);
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn score_2bit_block_avx2(
    block: usize,
    groups: usize,
    lookup: &CompactLookup,
    codes: &[u8],
) -> [f32; BLOCK_VECTORS] {
    use std::arch::x86_64::*;

    let mask = _mm_set1_epi8(0x0f);
    let mut low_sum = _mm_setzero_si128();
    let mut high_sum = _mm_setzero_si128();
    for group in 0..groups {
        let source = (block * groups + group) * BLOCK_VECTORS;
        let packed = _mm_loadl_epi64(codes.as_ptr().add(source).cast());
        let low_codes = _mm_and_si128(packed, mask);
        let high_codes = _mm_and_si128(_mm_srli_epi16(packed, 4), mask);
        let table = lookup.bytes.as_ptr().add(group * 32);
        let low_table = _mm_loadu_si128(table.cast());
        let high_table = _mm_loadu_si128(table.add(16).cast());
        low_sum = _mm_add_epi16(
            low_sum,
            _mm_cvtepu8_epi16(_mm_shuffle_epi8(low_table, low_codes)),
        );
        high_sum = _mm_add_epi16(
            high_sum,
            _mm_cvtepu8_epi16(_mm_shuffle_epi8(high_table, high_codes)),
        );
    }
    finish_accumulators(low_sum, high_sum, lookup)
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn score_4bit_block_avx2(
    block: usize,
    groups: usize,
    lookup: &CompactLookup,
    codes: &[u8],
) -> [f32; BLOCK_VECTORS] {
    use std::arch::x86_64::*;

    let mask = _mm_set1_epi8(0x0f);
    let mut low_sum = _mm_setzero_si128();
    let mut high_sum = _mm_setzero_si128();
    for group in 0..groups {
        let source = (block * groups + group) * BLOCK_VECTORS;
        let packed = _mm_loadl_epi64(codes.as_ptr().add(source).cast());
        let low_codes = _mm_and_si128(packed, mask);
        let high_codes = _mm_and_si128(_mm_srli_epi16(packed, 4), mask);
        let table = lookup.bytes.as_ptr().add(group * 32);
        let low_table = _mm_loadu_si128(table.cast());
        let high_table = _mm_loadu_si128(table.add(16).cast());
        low_sum = _mm_add_epi16(
            low_sum,
            _mm_cvtepu8_epi16(_mm_shuffle_epi8(low_table, low_codes)),
        );
        high_sum = _mm_add_epi16(
            high_sum,
            _mm_cvtepu8_epi16(_mm_shuffle_epi8(high_table, high_codes)),
        );
    }
    finish_accumulators(low_sum, high_sum, lookup)
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
pub(super) unsafe fn finish_accumulators(
    low_sum: std::arch::x86_64::__m128i,
    high_sum: std::arch::x86_64::__m128i,
    lookup: &CompactLookup,
) -> [f32; BLOCK_VECTORS] {
    use std::arch::x86_64::*;

    let integers = _mm256_add_epi32(
        _mm256_cvtepu16_epi32(low_sum),
        _mm256_cvtepu16_epi32(high_sum),
    );
    let scores = _mm256_add_ps(
        _mm256_set1_ps(lookup.bias),
        _mm256_mul_ps(_mm256_set1_ps(lookup.scale), _mm256_cvtepi32_ps(integers)),
    );
    let mut output = [0.0f32; BLOCK_VECTORS];
    _mm256_storeu_ps(output.as_mut_ptr(), scores);
    output
}

fn retain_float_block(
    first_row: usize,
    active: usize,
    scores: [f32; BLOCK_VECTORS],
    scales: &[f32],
    top_k: usize,
    heap: &mut BinaryHeap<Reverse<HeapHit>>,
) {
    for (candidate, score) in scores.iter().take(active).copied().enumerate() {
        let row = first_row + candidate;
        push_heap(heap, top_k, score * scales[row], row);
    }
}

pub(super) fn score_all_prepared(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    lookup: &CompactLookup,
    output: &mut [f32],
) -> Result<()> {
    let codes = index.codes()?;
    match (kernel, index.bits()) {
        (SearchKernel::Scalar, 2) => score_all_2bit_scalar(index, lookup, codes, output),
        (SearchKernel::Scalar, 4) => score_all_4bit_scalar(index, lookup, codes, output),
        (SearchKernel::Avx2, 2) => {
            #[cfg(target_arch = "x86_64")]
            unsafe {
                score_all_2bit_avx2(index, lookup, codes, output)
            }
            #[cfg(not(target_arch = "x86_64"))]
            score_all_2bit_scalar(index, lookup, codes, output)
        }
        (SearchKernel::Avx2, 4) => {
            #[cfg(target_arch = "x86_64")]
            unsafe {
                score_all_4bit_avx2(index, lookup, codes, output)
            }
            #[cfg(not(target_arch = "x86_64"))]
            score_all_4bit_scalar(index, lookup, codes, output)
        }
        _ => unreachable!(),
    }
    Ok(())
}

pub(super) fn score_all_prepared_parallel(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    lookup: &CompactLookup,
    output: &mut [f32],
) -> Result<()> {
    score_all_prepared_parallel_impl::<false>(index, kernel, lookup, &[], output)
}

pub(super) fn score_all_prepared_parallel_scaled(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    lookup: &CompactLookup,
    scales: &[f32],
    output: &mut [f32],
) -> Result<()> {
    score_all_prepared_parallel_impl::<true>(index, kernel, lookup, scales, output)
}

fn score_all_prepared_parallel_impl<const APPLY_SCALES: bool>(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    lookup: &CompactLookup,
    scales: &[f32],
    output: &mut [f32],
) -> Result<()> {
    let codes = index.codes()?;
    match index.bits() {
        2 => score_all_2bit_parallel_impl::<APPLY_SCALES>(
            index, kernel, lookup, scales, codes, output,
        ),
        4 => score_all_4bit_parallel_impl::<APPLY_SCALES>(
            index, kernel, lookup, scales, codes, output,
        ),
        _ => unreachable!(),
    }
    Ok(())
}

fn score_all_2bit_parallel_impl<const APPLY_SCALES: bool>(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    lookup: &CompactLookup,
    scales: &[f32],
    codes: &[u8],
    output: &mut [f32],
) {
    let groups = index.dimension() / 4;
    output
        .par_chunks_mut(BLOCK_VECTORS)
        .enumerate()
        .for_each(|(block, destination)| {
            let mut scores = match kernel {
                SearchKernel::Scalar => integer_to_float(
                    score_2bit_block_scalar(block, groups, lookup, codes),
                    lookup,
                ),
                SearchKernel::Avx2 => {
                    #[cfg(target_arch = "x86_64")]
                    unsafe {
                        score_2bit_block_avx2(block, groups, lookup, codes)
                    }
                    #[cfg(not(target_arch = "x86_64"))]
                    integer_to_float(
                        score_2bit_block_scalar(block, groups, lookup, codes),
                        lookup,
                    )
                }
                SearchKernel::Auto => unreachable!(),
            };
            if APPLY_SCALES {
                let first_row = block * BLOCK_VECTORS;
                for (score, scale) in scores
                    .iter_mut()
                    .zip(&scales[first_row..first_row + destination.len()])
                {
                    *score *= scale;
                }
            }
            destination.copy_from_slice(&scores[..destination.len()]);
        });
}

fn score_all_4bit_parallel_impl<const APPLY_SCALES: bool>(
    index: &VerifiedQuantizedIndex,
    kernel: SearchKernel,
    lookup: &CompactLookup,
    scales: &[f32],
    codes: &[u8],
    output: &mut [f32],
) {
    let groups = index.dimension() / 2;
    let blocks = index.header().padded_count as usize / BLOCK_VECTORS;
    output
        .par_chunks_mut(PARALLEL_VECTORS)
        .enumerate()
        .for_each(|(pair, destination)| {
            let first_block = pair * 2;
            let mut scores = match kernel {
                SearchKernel::Scalar => pair_integer_to_float(
                    score_4bit_block_scalar(first_block, groups, lookup, codes),
                    (first_block + 1 < blocks)
                        .then(|| score_4bit_block_scalar(first_block + 1, groups, lookup, codes)),
                    lookup,
                ),
                SearchKernel::Avx2 => {
                    #[cfg(target_arch = "x86_64")]
                    unsafe {
                        score_4bit_pair_avx2(first_block, blocks, groups, lookup, codes)
                    }
                    #[cfg(not(target_arch = "x86_64"))]
                    pair_integer_to_float(
                        score_4bit_block_scalar(first_block, groups, lookup, codes),
                        (first_block + 1 < blocks).then(|| {
                            score_4bit_block_scalar(first_block + 1, groups, lookup, codes)
                        }),
                        lookup,
                    )
                }
                SearchKernel::Auto => unreachable!(),
            };
            if APPLY_SCALES {
                let first_row = first_block * BLOCK_VECTORS;
                for (score, scale) in scores
                    .iter_mut()
                    .zip(&scales[first_row..first_row + destination.len()])
                {
                    *score *= scale;
                }
            }
            destination.copy_from_slice(&scores[..destination.len()]);
        });
}

fn pair_integer_to_float(
    first: [u32; BLOCK_VECTORS],
    second: Option<[u32; BLOCK_VECTORS]>,
    lookup: &CompactLookup,
) -> [f32; PARALLEL_VECTORS] {
    let mut output = [0.0; PARALLEL_VECTORS];
    for (destination, score) in output.iter_mut().zip(first) {
        *destination = lookup.bias + lookup.scale * score as f32;
    }
    if let Some(second) = second {
        for (destination, score) in output[BLOCK_VECTORS..].iter_mut().zip(second) {
            *destination = lookup.bias + lookup.scale * score as f32;
        }
    }
    output
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn score_4bit_pair_avx2(
    first_block: usize,
    blocks: usize,
    groups: usize,
    lookup: &CompactLookup,
    codes: &[u8],
) -> [f32; PARALLEL_VECTORS] {
    if first_block + 1 >= blocks {
        return single_pair_output(score_4bit_block_avx2(first_block, groups, lookup, codes));
    }
    score_pair_avx2(first_block, groups, lookup, codes)
}

fn single_pair_output(first: [f32; BLOCK_VECTORS]) -> [f32; PARALLEL_VECTORS] {
    let mut output = [0.0; PARALLEL_VECTORS];
    output[..BLOCK_VECTORS].copy_from_slice(&first);
    output
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn score_pair_avx2(
    first_block: usize,
    groups: usize,
    lookup: &CompactLookup,
    codes: &[u8],
) -> [f32; PARALLEL_VECTORS] {
    use std::arch::x86_64::*;

    let second_block = first_block + 1;
    let mask = _mm_set1_epi8(0x0f);
    let mut first_low = _mm_setzero_si128();
    let mut first_high = _mm_setzero_si128();
    let mut second_low = _mm_setzero_si128();
    let mut second_high = _mm_setzero_si128();
    for group in 0..groups {
        let first_source = (first_block * groups + group) * BLOCK_VECTORS;
        let second_source = (second_block * groups + group) * BLOCK_VECTORS;
        let first_packed = _mm_loadl_epi64(codes.as_ptr().add(first_source).cast());
        let second_packed = _mm_loadl_epi64(codes.as_ptr().add(second_source).cast());
        let table = lookup.bytes.as_ptr().add(group * 32);
        let low_table = _mm_loadu_si128(table.cast());
        let high_table = _mm_loadu_si128(table.add(16).cast());

        let first_low_codes = _mm_and_si128(first_packed, mask);
        let first_high_codes = _mm_and_si128(_mm_srli_epi16(first_packed, 4), mask);
        first_low = _mm_add_epi16(
            first_low,
            _mm_cvtepu8_epi16(_mm_shuffle_epi8(low_table, first_low_codes)),
        );
        first_high = _mm_add_epi16(
            first_high,
            _mm_cvtepu8_epi16(_mm_shuffle_epi8(high_table, first_high_codes)),
        );

        let second_low_codes = _mm_and_si128(second_packed, mask);
        let second_high_codes = _mm_and_si128(_mm_srli_epi16(second_packed, 4), mask);
        second_low = _mm_add_epi16(
            second_low,
            _mm_cvtepu8_epi16(_mm_shuffle_epi8(low_table, second_low_codes)),
        );
        second_high = _mm_add_epi16(
            second_high,
            _mm_cvtepu8_epi16(_mm_shuffle_epi8(high_table, second_high_codes)),
        );
    }
    let first = finish_accumulators(first_low, first_high, lookup);
    let second = finish_accumulators(second_low, second_high, lookup);
    let mut output = [0.0; PARALLEL_VECTORS];
    output[..BLOCK_VECTORS].copy_from_slice(&first);
    output[BLOCK_VECTORS..].copy_from_slice(&second);
    output
}

fn integer_to_float(scores: [u32; BLOCK_VECTORS], lookup: &CompactLookup) -> [f32; BLOCK_VECTORS] {
    scores.map(|score| lookup.bias + lookup.scale * score as f32)
}

fn score_all_2bit_scalar(
    index: &VerifiedQuantizedIndex,
    lookup: &CompactLookup,
    codes: &[u8],
    output: &mut [f32],
) {
    let groups = index.dimension() / 4;
    for block in 0..index.header().padded_count as usize / BLOCK_VECTORS {
        let first = block * BLOCK_VECTORS;
        let active = (index.len() - first).min(BLOCK_VECTORS);
        let scores = score_2bit_block_scalar(block, groups, lookup, codes);
        for (destination, score) in output[first..first + active].iter_mut().zip(scores) {
            *destination = lookup.bias + lookup.scale * score as f32;
        }
    }
}

fn score_all_4bit_scalar(
    index: &VerifiedQuantizedIndex,
    lookup: &CompactLookup,
    codes: &[u8],
    output: &mut [f32],
) {
    let groups = index.dimension() / 2;
    for block in 0..index.header().padded_count as usize / BLOCK_VECTORS {
        let first = block * BLOCK_VECTORS;
        let active = (index.len() - first).min(BLOCK_VECTORS);
        let scores = score_4bit_block_scalar(block, groups, lookup, codes);
        for (destination, score) in output[first..first + active].iter_mut().zip(scores) {
            *destination = lookup.bias + lookup.scale * score as f32;
        }
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn score_all_2bit_avx2(
    index: &VerifiedQuantizedIndex,
    lookup: &CompactLookup,
    codes: &[u8],
    output: &mut [f32],
) {
    let groups = index.dimension() / 4;
    for block in 0..index.header().padded_count as usize / BLOCK_VECTORS {
        let first = block * BLOCK_VECTORS;
        let active = (index.len() - first).min(BLOCK_VECTORS);
        let scores = score_2bit_block_avx2(block, groups, lookup, codes);
        output[first..first + active].copy_from_slice(&scores[..active]);
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn score_all_4bit_avx2(
    index: &VerifiedQuantizedIndex,
    lookup: &CompactLookup,
    codes: &[u8],
    output: &mut [f32],
) {
    let groups = index.dimension() / 2;
    for block in 0..index.header().padded_count as usize / BLOCK_VECTORS {
        let first = block * BLOCK_VECTORS;
        let active = (index.len() - first).min(BLOCK_VECTORS);
        let scores = score_4bit_block_avx2(block, groups, lookup, codes);
        output[first..first + active].copy_from_slice(&scores[..active]);
    }
}
