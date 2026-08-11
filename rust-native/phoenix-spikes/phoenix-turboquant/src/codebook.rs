use crate::{Result, TurboQuantError};

/// Lloyd-Max scalar codebook for the high-dimensional normal approximation.
///
/// TurboQuant's exact marginal is a shifted Beta distribution. At Phoenix's
/// 768 dimensions it is already close to `N(0, 1/d)`. This clean-room spike
/// solves the standard-normal Lloyd-Max recurrence and scales the result by
/// `1/sqrt(d)`. The approximation is an explicit experimental boundary.
#[derive(Clone, Debug)]
pub struct LloydMaxCodebook {
    bits: u8,
    dimension: usize,
    boundaries: Box<[f32]>,
    centroids: Box<[f32]>,
}

impl LloydMaxCodebook {
    pub fn new(bits: u8, dimension: usize) -> Result<Self> {
        if !matches!(bits, 2 | 4) {
            return Err(TurboQuantError::UnsupportedBitWidth(bits));
        }
        if dimension == 0 || !dimension.is_multiple_of(8) {
            return Err(TurboQuantError::InvalidDimension(dimension));
        }
        let levels = 1usize << bits;
        let mut centroids = initial_centroids(levels);
        for _ in 0..256 {
            let boundaries = midpoints(&centroids);
            let mut next = vec![0.0; levels];
            for index in 0..levels {
                let low = if index == 0 {
                    f64::NEG_INFINITY
                } else {
                    boundaries[index - 1]
                };
                let high = if index + 1 == levels {
                    f64::INFINITY
                } else {
                    boundaries[index]
                };
                next[index] = truncated_normal_mean(low, high);
            }
            let delta = centroids
                .iter()
                .zip(&next)
                .map(|(left, right)| (left - right).abs())
                .fold(0.0f64, f64::max);
            centroids = next;
            if delta < 1e-13 {
                break;
            }
        }
        let inv_sqrt_dim = 1.0 / (dimension as f64).sqrt();
        let boundaries = midpoints(&centroids)
            .into_iter()
            .map(|value| (value * inv_sqrt_dim) as f32)
            .collect::<Vec<_>>()
            .into_boxed_slice();
        let centroids = centroids
            .into_iter()
            .map(|value| (value * inv_sqrt_dim) as f32)
            .collect::<Vec<_>>()
            .into_boxed_slice();
        Ok(Self {
            bits,
            dimension,
            boundaries,
            centroids,
        })
    }

    pub fn bits(&self) -> u8 {
        self.bits
    }

    pub fn dimension(&self) -> usize {
        self.dimension
    }

    pub fn boundaries(&self) -> &[f32] {
        &self.boundaries
    }

    pub fn centroids(&self) -> &[f32] {
        &self.centroids
    }

    #[inline]
    pub fn quantize(&self, value: f32) -> u8 {
        self.boundaries
            .partition_point(|boundary| value > *boundary) as u8
    }

    pub fn hash(&self) -> [u8; 32] {
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"phoenix/lloyd-max-normal-v1");
        hasher.update(&[self.bits]);
        hasher.update(&(self.dimension as u64).to_le_bytes());
        hasher.update(bytemuck::cast_slice(&self.boundaries));
        hasher.update(bytemuck::cast_slice(&self.centroids));
        *hasher.finalize().as_bytes()
    }
}

fn initial_centroids(levels: usize) -> Vec<f64> {
    // Symmetric coverage of almost all standard-normal mass. Lloyd-Max
    // convergence is insensitive to this evenly-spaced initialization.
    (0..levels)
        .map(|index| -3.0 + 6.0 * index as f64 / (levels - 1) as f64)
        .collect()
}

fn midpoints(centroids: &[f64]) -> Vec<f64> {
    centroids
        .windows(2)
        .map(|pair| 0.5 * (pair[0] + pair[1]))
        .collect()
}

fn truncated_normal_mean(low: f64, high: f64) -> f64 {
    let probability = normal_cdf(high) - normal_cdf(low);
    if probability <= 1e-16 {
        return if low.is_finite() && high.is_finite() {
            0.5 * (low + high)
        } else if low.is_finite() {
            low
        } else if high.is_finite() {
            high
        } else {
            0.0
        };
    }
    (normal_pdf(low) - normal_pdf(high)) / probability
}

fn normal_pdf(value: f64) -> f64 {
    if !value.is_finite() {
        return 0.0;
    }
    const INV_SQRT_TWO_PI: f64 = 0.398_942_280_401_432_7;
    INV_SQRT_TWO_PI * (-0.5 * value * value).exp()
}

fn normal_cdf(value: f64) -> f64 {
    if value == f64::NEG_INFINITY {
        return 0.0;
    }
    if value == f64::INFINITY {
        return 1.0;
    }
    // Abramowitz-Stegun 7.1.26. Its error is far below the f32 codebook
    // precision this experiment persists.
    let absolute = value.abs();
    let t = 1.0 / (1.0 + 0.231_641_9 * absolute);
    let polynomial = t
        * (0.319_381_530
            + t * (-0.356_563_782
                + t * (1.781_477_937 + t * (-1.821_255_978 + t * 1.330_274_429))));
    let upper = 1.0 - normal_pdf(absolute) * polynomial;
    if value >= 0.0 {
        upper
    } else {
        1.0 - upper
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn codebooks_are_symmetric_and_ordered() {
        for bits in [2, 4] {
            let codebook = LloydMaxCodebook::new(bits, 768).unwrap();
            assert_eq!(codebook.centroids().len(), 1usize << bits);
            assert!(codebook
                .boundaries()
                .windows(2)
                .all(|pair| pair[0] < pair[1]));
            for (left, right) in codebook
                .centroids()
                .iter()
                .zip(codebook.centroids().iter().rev())
            {
                assert!((left + right).abs() < 2e-6);
            }
        }
    }

    #[test]
    fn codebook_hash_is_stable_for_same_contract() {
        let first = LloydMaxCodebook::new(4, 768).unwrap();
        let second = LloydMaxCodebook::new(4, 768).unwrap();
        assert_eq!(first.hash(), second.hash());
    }
}
