use std::time::Instant;

use crate::model::{CLASSES, HIDDEN_2, Model, Sample, TRAIN_SAMPLES};
use crate::partition::{self, STRATUM_COUNT, STRATUM_SIZE};

const OUTPUT_FEATURES: usize = 27;
const ORDER_SEED: u64 = 0xa303_4350_524f_4a31;
const PANEL_STREAM: u64 = 0x4152_3033_4456_3438;
const STEP_MUL: u64 = 0x9e37_79b9;

pub const PANEL_SIZE: usize = STRATUM_COUNT * 4;
const PER_STRATUM_PANEL: usize = 4;

#[derive(Clone, Copy, Debug)]
pub struct ProjectedPartition {
    pub ids: [u8; TRAIN_SAMPLES],
    pub feature_ns: u128,
    pub ordering_ns: u128,
}

pub fn projected_order(model: &Model, samples: &[Sample]) -> ProjectedPartition {
    assert_eq!(samples.len(), TRAIN_SAMPLES);
    let feature_started = Instant::now();
    let features =
        std::array::from_fn::<_, TRAIN_SAMPLES, _>(|index| output_gradient(model, &samples[index]));
    let feature_ns = feature_started.elapsed().as_nanos();

    let ordering_started = Instant::now();
    let scale = 1.0_f64 / (OUTPUT_FEATURES as f64).sqrt();
    let mut projected = [0.0_f64; TRAIN_SAMPLES];
    for (sample, feature) in features.iter().enumerate() {
        for (dimension, &coordinate) in feature.iter().enumerate() {
            let sign = if mix64(ORDER_SEED ^ dimension as u64) & 1 == 0 {
                1.0
            } else {
                -1.0
            };
            projected[sample] += coordinate * sign * scale;
        }
    }

    let mut order = std::array::from_fn::<_, TRAIN_SAMPLES, _>(|index| index);
    order.sort_by(|left, right| {
        projected[*left]
            .total_cmp(&projected[*right])
            .then_with(|| left.cmp(right))
    });
    let mut ids = [0_u8; TRAIN_SAMPLES];
    for (rank, sample) in order.into_iter().enumerate() {
        ids[sample] = (rank / STRATUM_SIZE) as u8;
    }
    assert_eq!(
        partition::stratum_counts(&ids),
        [STRATUM_SIZE; STRATUM_COUNT]
    );
    assert!(projected.iter().all(|value| value.is_finite()));

    ProjectedPartition {
        ids,
        feature_ns,
        ordering_ns: ordering_started.elapsed().as_nanos(),
    }
}

pub fn sample_panel(
    ids: &[u8; TRAIN_SAMPLES],
    stream_seed: u64,
    evidence_round: usize,
) -> [usize; PANEL_SIZE] {
    assert_eq!(
        partition::stratum_counts(ids),
        [STRATUM_SIZE; STRATUM_COUNT]
    );
    let mut rng =
        PanelRng::new(stream_seed ^ PANEL_STREAM ^ (evidence_round as u64).wrapping_mul(STEP_MUL));
    let mut panel = [0_usize; PANEL_SIZE];
    let mut output = 0;
    for stratum in 0..STRATUM_COUNT {
        let mut members = [0_usize; STRATUM_SIZE];
        let mut count = 0;
        for (sample, &assigned) in ids.iter().enumerate() {
            if usize::from(assigned) == stratum {
                members[count] = sample;
                count += 1;
            }
        }
        assert_eq!(count, STRATUM_SIZE);
        for draw in 0..PER_STRATUM_PANEL {
            let remaining = STRATUM_SIZE - draw;
            let selected = draw + rng.next() as usize % remaining;
            members.swap(draw, selected);
            panel[output] = members[draw];
            output += 1;
        }
    }
    assert_eq!(output, PANEL_SIZE);
    assert!(has_exact_panel_quotas(ids, &panel));
    panel
}

pub fn has_exact_panel_quotas(ids: &[u8; TRAIN_SAMPLES], panel: &[usize; PANEL_SIZE]) -> bool {
    let mut counts = [0_usize; STRATUM_COUNT];
    let mut seen = [false; TRAIN_SAMPLES];
    for &sample in panel {
        if sample >= TRAIN_SAMPLES || seen[sample] {
            return false;
        }
        seen[sample] = true;
        let stratum = ids[sample] as usize;
        if stratum >= STRATUM_COUNT {
            return false;
        }
        counts[stratum] += 1;
    }
    counts == [PER_STRATUM_PANEL; STRATUM_COUNT]
}

pub fn indices_fingerprint(indices: &[usize]) -> u64 {
    indices
        .iter()
        .enumerate()
        .fold(0xcbf2_9ce4_8422_2325_u64, |hash, (position, &index)| {
            (hash ^ (index as u64).wrapping_add(position as u64))
                .wrapping_mul(0x0000_0100_0000_01b3)
        })
}

pub fn partition_fingerprint(ids: &[u8; TRAIN_SAMPLES]) -> u64 {
    ids.iter()
        .enumerate()
        .fold(0xcbf2_9ce4_8422_2325_u64, |hash, (position, &stratum)| {
            (hash ^ u64::from(stratum).wrapping_add(position as u64))
                .wrapping_mul(0x0000_0100_0000_01b3)
        })
}

fn output_gradient(model: &Model, sample: &Sample) -> [f64; OUTPUT_FEATURES] {
    let (logits, _, hidden) = model.logits(sample);
    let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let exponential_sum = logits
        .iter()
        .map(|value| (*value - maximum).exp())
        .sum::<f32>();
    let mut error = std::array::from_fn::<_, CLASSES, _>(|class| {
        (logits[class] - maximum).exp() / exponential_sum
    });
    error[sample.target as usize] -= 1.0;

    let mut result = [0.0_f64; OUTPUT_FEATURES];
    for class in 0..CLASSES {
        for unit in 0..HIDDEN_2 {
            result[class * HIDDEN_2 + unit] = f64::from(error[class] * hidden[unit]);
        }
        result[CLASSES * HIDDEN_2 + class] = f64::from(error[class]);
    }
    result
}

#[derive(Clone, Copy)]
struct PanelRng {
    state: u64,
}

impl PanelRng {
    const fn new(state: u64) -> Self {
        Self { state }
    }

    fn next(&mut self) -> u64 {
        let mut value = self.state;
        value ^= value << 7;
        value ^= value >> 9;
        value ^= value << 8;
        self.state = value;
        value
    }
}

fn mix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{self, PARAMS};

    const OUTPUT_START: usize = 144;

    #[test]
    fn projected_gradient_order_is_deterministic_and_balanced() {
        let samples = model::generate_dataset(0xa303_dada_0000_0001);
        let model = Model::initial(0xa303_1a17_0000_0001);
        let first = projected_order(&model, &samples);
        let second = projected_order(&model, &samples);
        assert_eq!(first.ids, second.ids);
        assert_eq!(
            partition::stratum_counts(&first.ids),
            [STRATUM_SIZE; STRATUM_COUNT]
        );
        assert!(first.feature_ns > 0);
        assert!(first.ordering_ns > 0);
    }

    #[test]
    fn output_gradient_matches_frozen_r2_full_gradient_slice() {
        let samples = model::generate_dataset(0xa303_dada_0000_0001);
        let model = Model::initial(0xa303_1a17_0000_0001);
        for sample in samples.iter().take(12) {
            let full = model.gradient_one(sample).1;
            let output = output_gradient(&model, sample);
            assert_eq!(output.len(), PARAMS - OUTPUT_START);
            for (actual, expected) in output.iter().zip(&full[OUTPUT_START..]) {
                assert_eq!(*actual, f64::from(*expected));
            }
        }
    }

    #[test]
    fn verifier_panel_is_deterministic_unique_and_four_per_stratum() {
        let ids = partition::hash_placebo(3);
        let first = sample_panel(&ids, 0xa303_ea00_0000_0001, 17);
        let second = sample_panel(&ids, 0xa303_ea00_0000_0001, 17);
        assert_eq!(first, second);
        assert_eq!(first.len(), 48);
        assert!(has_exact_panel_quotas(&ids, &first));
        assert!(!has_exact_panel_quotas(&ids, &[0; PANEL_SIZE]));
    }
}
