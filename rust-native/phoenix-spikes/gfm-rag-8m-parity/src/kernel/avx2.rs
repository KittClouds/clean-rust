use rayon::prelude::*;

use crate::Result;

use super::validate;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FastKernel {
    Avx2Fma,
    Portable,
}

/// Destination-parallel kernel. Each destination retains deterministic incoming
/// edge order; only independent rows execute concurrently.
pub fn fast_distmult_sum(
    offsets: &[u64],
    sources: &[u32],
    relation_ids: &[u32],
    input: &[f32],
    relations: &[f32],
    boundary: &[f32],
    dim: usize,
) -> Result<(Vec<f32>, FastKernel)> {
    let (nodes, _) = validate(
        offsets,
        sources,
        relation_ids,
        input,
        relations,
        boundary,
        dim,
    )?;
    let use_avx2 = cfg!(target_arch = "x86_64")
        && std::arch::is_x86_feature_detected!("avx2")
        && std::arch::is_x86_feature_detected!("fma");
    let mut output = boundary.to_vec();
    output
        .par_chunks_mut(dim)
        .enumerate()
        .take(nodes)
        .for_each(|(dst, output_row)| {
            for edge in offsets[dst] as usize..offsets[dst + 1] as usize {
                let source = sources[edge] as usize;
                let relation = relation_ids[edge] as usize;
                let source_row = &input[source * dim..(source + 1) * dim];
                let relation_row = &relations[relation * dim..(relation + 1) * dim];
                if use_avx2 {
                    // SAFETY: runtime feature checks cover both target features;
                    // all slices are equal length and valid for the call.
                    unsafe { accumulate_avx2_fma(output_row, source_row, relation_row) };
                } else {
                    accumulate_portable(output_row, source_row, relation_row);
                }
            }
        });
    Ok((
        output,
        if use_avx2 {
            FastKernel::Avx2Fma
        } else {
            FastKernel::Portable
        },
    ))
}

fn accumulate_portable(output: &mut [f32], source: &[f32], relation: &[f32]) {
    let (output_chunks, output_tail) = output.as_chunks_mut::<8>();
    let (source_chunks, source_tail) = source.as_chunks::<8>();
    let (relation_chunks, relation_tail) = relation.as_chunks::<8>();
    for ((dst, src), rel) in output_chunks
        .iter_mut()
        .zip(source_chunks)
        .zip(relation_chunks)
    {
        let dst_vec = wide::f32x8::from(*dst);
        let src_vec = wide::f32x8::from(*src);
        let rel_vec = wide::f32x8::from(*rel);
        *dst = (src_vec.mul_add(rel_vec, dst_vec)).to_array();
    }
    for ((dst, src), rel) in output_tail.iter_mut().zip(source_tail).zip(relation_tail) {
        *dst = src.mul_add(*rel, *dst);
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2,fma")]
unsafe fn accumulate_avx2_fma(output: &mut [f32], source: &[f32], relation: &[f32]) {
    use std::arch::x86_64::{_mm256_fmadd_ps, _mm256_loadu_ps, _mm256_storeu_ps};

    let width = output.len() / 8 * 8;
    let mut index = 0;
    while index < width {
        // SAFETY: index..index+8 stays within all equal-length slices. Unaligned
        // loads/stores are intentional for arbitrary row alignment.
        unsafe {
            let dst = _mm256_loadu_ps(output.as_ptr().add(index));
            let src = _mm256_loadu_ps(source.as_ptr().add(index));
            let rel = _mm256_loadu_ps(relation.as_ptr().add(index));
            _mm256_storeu_ps(
                output.as_mut_ptr().add(index),
                _mm256_fmadd_ps(src, rel, dst),
            );
        }
        index += 8;
    }
    for index in width..output.len() {
        output[index] = source[index].mul_add(relation[index], output[index]);
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn accumulate_avx2_fma(_: &mut [f32], _: &[f32], _: &[f32]) {
    unreachable!()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kernel::scalar_distmult_sum;

    #[test]
    fn fast_matches_scalar_on_irregular_rows() {
        let offsets = [0, 0, 2, 3];
        let sources = [0, 2, 1];
        let relation_ids = [0, 1, 0];
        let input: Vec<f32> = (0..30).map(|value| value as f32 * 0.125).collect();
        let relations: Vec<f32> = (0..20).map(|value| value as f32 * -0.0625).collect();
        let boundary = vec![0.25; 30];
        let expected = scalar_distmult_sum(
            &offsets,
            &sources,
            &relation_ids,
            &input,
            &relations,
            &boundary,
            10,
        )
        .unwrap();
        let (actual, _) = fast_distmult_sum(
            &offsets,
            &sources,
            &relation_ids,
            &input,
            &relations,
            &boundary,
            10,
        )
        .unwrap();
        assert_eq!(actual, expected);
    }
}
