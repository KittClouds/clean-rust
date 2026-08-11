use rayon::prelude::*;

use crate::format::{QuantizedFormat, BLOCK_VECTORS};
use crate::{LloydMaxCodebook, Result, Rotation, TurboQuantError};

#[derive(Debug)]
pub struct EncodedVectors {
    pub format: QuantizedFormat,
    pub dimension: usize,
    pub row_count: usize,
    pub padded_count: usize,
    pub codes: Vec<u8>,
    pub scales: Vec<f32>,
    pub codebook: LloydMaxCodebook,
    pub rotation: Rotation,
}

impl EncodedVectors {
    pub fn bytes_per_row(&self) -> usize {
        self.dimension * self.format.bits() as usize / 8
    }

    pub fn groups_per_row(&self) -> usize {
        self.dimension / self.format.coordinates_per_byte()
    }
}

pub fn encode_vectors(
    vectors: &[f32],
    row_count: usize,
    dimension: usize,
    bits: u8,
) -> Result<EncodedVectors> {
    let format = QuantizedFormat::new(bits)?;
    if dimension == 0 || !dimension.is_multiple_of(8) {
        return Err(TurboQuantError::InvalidDimension(dimension));
    }
    let expected = row_count
        .checked_mul(dimension)
        .ok_or(TurboQuantError::Overflow)?;
    if vectors.len() != expected {
        return Err(TurboQuantError::InvalidVectorLength {
            actual: vectors.len(),
            rows: row_count,
            dimension,
        });
    }
    for (flat, value) in vectors.iter().copied().enumerate() {
        if !value.is_finite() {
            return Err(TurboQuantError::NonFinite {
                row: flat / dimension,
                coordinate: flat % dimension,
            });
        }
    }
    let rotation = Rotation::new(dimension)?;
    let codebook = LloydMaxCodebook::new(bits, dimension)?;
    let groups = dimension / format.coordinates_per_byte();
    let mut row_codes = vec![0u8; row_count * groups];
    let mut scales = vec![0.0f32; row_count];
    row_codes
        .par_chunks_mut(groups)
        .zip(scales.par_iter_mut())
        .enumerate()
        .for_each_init(
            || (vec![0.0f32; dimension], vec![0.0f32; dimension]),
            |(rotated, scratch), (row_index, (encoded, scale))| {
                let source = &vectors[row_index * dimension..(row_index + 1) * dimension];
                let norm = source
                    .iter()
                    .map(|value| f64::from(*value) * f64::from(*value))
                    .sum::<f64>()
                    .sqrt();
                if norm <= 1e-12 {
                    encoded.fill(0);
                    *scale = 0.0;
                    return;
                }
                let inverse = (1.0 / norm) as f32;
                for ((output, input), temporary) in
                    rotated.iter_mut().zip(source).zip(scratch.iter_mut())
                {
                    *output = *input * inverse;
                    *temporary = 0.0;
                }
                rotation.apply(rotated, scratch);
                let mut reconstructed_dot = 0.0f64;
                let coordinates_per_byte = format.coordinates_per_byte();
                for (group, output) in encoded.iter_mut().enumerate() {
                    let mut packed = 0u8;
                    let coordinate_start = group * coordinates_per_byte;
                    for lane in 0..coordinates_per_byte {
                        let coordinate = coordinate_start + lane;
                        let code = codebook.quantize(rotated[coordinate]);
                        packed |= code << (lane * bits as usize);
                        reconstructed_dot += f64::from(rotated[coordinate])
                            * f64::from(codebook.centroids()[code as usize]);
                    }
                    *output = packed;
                }
                *scale = if reconstructed_dot > 1e-12 {
                    (norm / reconstructed_dot) as f32
                } else {
                    0.0
                };
            },
        );

    let padded_count = row_count.next_multiple_of(BLOCK_VECTORS);
    let mut codes = vec![0u8; padded_count * groups];
    for row in 0..row_count {
        let block = row / BLOCK_VECTORS;
        let lane = row % BLOCK_VECTORS;
        for group in 0..groups {
            codes[(block * groups + group) * BLOCK_VECTORS + lane] =
                row_codes[row * groups + group];
        }
    }
    Ok(EncodedVectors {
        format,
        dimension,
        row_count,
        padded_count,
        codes,
        scales,
        codebook,
        rotation,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encoded_size_matches_bit_budget() {
        let mut vectors = vec![0.0f32; 9 * 768];
        for (index, value) in vectors.iter_mut().enumerate() {
            *value = ((index * 17 % 113) as f32 - 56.0) / 57.0;
        }
        for bits in [2, 4] {
            let encoded = encode_vectors(&vectors, 9, 768, bits).unwrap();
            assert_eq!(encoded.padded_count, 16);
            assert_eq!(encoded.codes.len(), 16 * 768 * bits as usize / 8);
            assert_eq!(encoded.scales.len(), 9);
            assert!(encoded
                .scales
                .iter()
                .all(|scale| scale.is_finite() && *scale > 0.0));
        }
    }
}
