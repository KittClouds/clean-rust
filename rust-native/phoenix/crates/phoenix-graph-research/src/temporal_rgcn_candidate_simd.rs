use rayon::prelude::*;
use wide::f32x8;

use crate::TEMPORAL_RGCN_HIDDEN;

pub(crate) const CANDIDATE_SIMD_LANES: usize = 8;

pub(crate) struct CandidateFeaturePlanes {
    values: Vec<f32>,
    stride: usize,
}

impl CandidateFeaturePlanes {
    pub(crate) fn from_rows(rows: &[[f32; TEMPORAL_RGCN_HIDDEN]]) -> Self {
        let candidates = rows.len();
        let stride = candidates.div_ceil(CANDIDATE_SIMD_LANES) * CANDIDATE_SIMD_LANES;
        let mut values = vec![0.0_f32; stride * TEMPORAL_RGCN_HIDDEN];
        values
            .par_chunks_mut(stride)
            .enumerate()
            .for_each(|(feature, plane)| {
                for (target, row) in plane.iter_mut().zip(rows) {
                    *target = row[feature];
                }
            });
        Self { values, stride }
    }

    pub(crate) fn bytes(&self) -> usize {
        self.values.len() * size_of::<f32>()
    }

    // Feature order is the bitwise contract; indexing prevents iterator rewrites from
    // obscuring or re-associating the sixteen sequential additions.
    #[allow(clippy::needless_range_loop)]
    #[inline(always)]
    pub(crate) fn score_block<const QUERIES: usize>(
        &self,
        features: &[[f32; TEMPORAL_RGCN_HIDDEN]; QUERIES],
        biases: &[f32; QUERIES],
        residual_scale: f32,
        candidate_start: usize,
    ) -> [[f32; CANDIDATE_SIMD_LANES]; QUERIES] {
        debug_assert!(candidate_start.is_multiple_of(CANDIDATE_SIMD_LANES));
        debug_assert!(candidate_start < self.stride);
        let mut sums = [f32x8::ZERO; QUERIES];
        for feature in 0..TEMPORAL_RGCN_HIDDEN {
            let start = feature * self.stride + candidate_start;
            let target = f32x8::from(
                <[f32; CANDIDATE_SIMD_LANES]>::try_from(
                    &self.values[start..start + CANDIDATE_SIMD_LANES],
                )
                .expect("candidate plane block"),
            );
            for query in 0..QUERIES {
                let product =
                    f32x8::from([features[query][feature]; CANDIDATE_SIMD_LANES]) * target;
                sums[query] += product;
            }
        }
        std::array::from_fn(|query| {
            let biased = sums[query] + f32x8::from([biases[query]; CANDIDATE_SIMD_LANES]);
            (f32x8::from([residual_scale; CANDIDATE_SIMD_LANES]) * biased).into()
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn candidate_lane_scores_preserve_feature_lane_reduction_bits() {
        let rows = (0..19)
            .map(|candidate| {
                std::array::from_fn(|feature| {
                    let signed = (candidate * 29 + feature * 11 + 3) as f32 / 37.0;
                    if (candidate + feature) % 3 == 0 {
                        -signed
                    } else {
                        signed
                    }
                })
            })
            .collect::<Vec<[f32; TEMPORAL_RGCN_HIDDEN]>>();
        let features = [
            std::array::from_fn(|index| (index as f32 - 7.0) / 13.0),
            std::array::from_fn(|index| (19.0 - index as f32) / 17.0),
            std::array::from_fn(|index| (index as f32 + 0.25) / -23.0),
            std::array::from_fn(|index| (index as f32 % 5.0) / 7.0),
        ];
        let biases = [-0.75, 0.0, 1.25, -3.5];
        let residual_scale = 0.03125;
        let planes = CandidateFeaturePlanes::from_rows(&rows);

        for candidate_start in (0..rows.len()).step_by(CANDIDATE_SIMD_LANES) {
            let actual = planes.score_block(&features, &biases, residual_scale, candidate_start);
            let valid = (rows.len() - candidate_start).min(CANDIDATE_SIMD_LANES);
            for query in 0..features.len() {
                for lane in 0..valid {
                    let expected = feature_lane_reference(
                        &features[query],
                        &rows[candidate_start + lane],
                        biases[query],
                        residual_scale,
                    );
                    assert_eq!(actual[query][lane].to_bits(), expected.to_bits());
                }
            }
        }
        assert_eq!(planes.bytes(), 24 * TEMPORAL_RGCN_HIDDEN * size_of::<f32>());
    }

    fn feature_lane_reference(
        features: &[f32; TEMPORAL_RGCN_HIDDEN],
        target: &[f32; TEMPORAL_RGCN_HIDDEN],
        bias: f32,
        residual_scale: f32,
    ) -> f32 {
        let feature_low: [f32; 8] = features[..8].try_into().expect("features low");
        let target_low: [f32; 8] = target[..8].try_into().expect("target low");
        let feature_high: [f32; 8] = features[8..].try_into().expect("features high");
        let target_high: [f32; 8] = target[8..].try_into().expect("target high");
        let low: [f32; 8] = (f32x8::from(feature_low) * f32x8::from(target_low)).into();
        let high: [f32; 8] = (f32x8::from(feature_high) * f32x8::from(target_high)).into();
        residual_scale * (low.into_iter().chain(high).sum::<f32>() + bias)
    }
}
