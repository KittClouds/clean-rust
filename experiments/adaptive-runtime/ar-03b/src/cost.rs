use std::hint::black_box;
use std::time::Instant;

use crate::features::{self, Projection, Proxy};
use crate::model::{Model, Sample, TRAIN_SAMPLES};
use crate::partition::{self, STRATUM_COUNT, STRATUM_SIZE};
use crate::protocol::Candidate;

pub const TIMING_REPETITIONS: usize = 3;

#[derive(Clone, Debug)]
pub struct ProxyCost {
    pub method: String,
    pub dataset_index: u8,
    pub initialization_index: u8,
    pub stream_seed: u64,
    pub step: usize,
    pub dimensions: usize,
    pub feature_payload_bytes: usize,
    pub acquisition_median_ns: u128,
    pub partition_median_ns: u128,
}

#[derive(Clone, Debug)]
pub struct VerifierCost {
    pub dataset_index: u8,
    pub initialization_index: u8,
    pub stream_seed: u64,
    pub step: usize,
    pub verifier_examples: usize,
    pub candidate_count: usize,
    pub candidate_sample_evaluations: usize,
    pub forward_passes: usize,
    pub median_ns: u128,
}

pub fn measure_proxy_cost(
    proxy: Proxy,
    model: &Model,
    samples: &[Sample],
    projection: &Projection,
) -> (u128, u128, usize) {
    let acquisition_ns =
        features::measure_acquisition_ns(proxy, model, samples, projection, TIMING_REPETITIONS);
    let rows = features::acquire(proxy, model, samples, projection);
    let payload_bytes = rows
        .iter()
        .map(|row| row.len() * std::mem::size_of::<f64>())
        .sum();
    let mut durations = Vec::with_capacity(TIMING_REPETITIONS);
    for _ in 0..TIMING_REPETITIONS {
        let started = Instant::now();
        let partition = partition::balanced_kmeans(&rows, partition::KMEANS_INIT_SEED);
        black_box(partition.ids);
        durations.push(started.elapsed().as_nanos());
    }
    durations.sort_unstable();
    (
        acquisition_ns,
        durations[durations.len() / 2],
        payload_bytes,
    )
}

pub fn measure_hash_partition_ns() -> u128 {
    let mut durations = Vec::with_capacity(TIMING_REPETITIONS);
    for _ in 0..TIMING_REPETITIONS {
        let started = Instant::now();
        let partitions: Vec<_> = (0..8).map(partition::hash_placebo).collect();
        black_box(partitions);
        durations.push(started.elapsed().as_nanos());
    }
    durations.sort_unstable();
    durations[durations.len() / 2]
}

pub fn measure_verifier_cost(
    model: &Model,
    samples: &[Sample],
    candidates: &[Candidate],
    samples_per_stratum: usize,
    stream_seed: u64,
    step: usize,
) -> VerifierCost {
    assert_eq!(samples.len(), TRAIN_SAMPLES);
    assert!((1..=STRATUM_SIZE).contains(&samples_per_stratum));
    let indices = fixed_verifier_indices(samples_per_stratum);
    let mut durations = Vec::with_capacity(TIMING_REPETITIONS);
    for _ in 0..TIMING_REPETITIONS {
        let started = Instant::now();
        let baseline: Vec<_> = indices
            .iter()
            .map(|&index| model.loss_one(&samples[index]))
            .collect();
        let mut utility_sum = 0.0_f32;
        for candidate in candidates {
            let mut changed = *model;
            changed.parameters[candidate.left_parameter] += candidate.left_delta;
            changed.parameters[candidate.right_parameter] += candidate.right_delta;
            for (position, &sample_index) in indices.iter().enumerate() {
                utility_sum += baseline[position] - changed.loss_one(&samples[sample_index]);
            }
        }
        black_box(utility_sum);
        durations.push(started.elapsed().as_nanos());
    }
    durations.sort_unstable();
    let sample_count = STRATUM_COUNT * samples_per_stratum;
    VerifierCost {
        dataset_index: 0,
        initialization_index: 0,
        stream_seed,
        step,
        verifier_examples: sample_count,
        candidate_count: candidates.len(),
        candidate_sample_evaluations: candidates.len() * sample_count,
        forward_passes: (candidates.len() + 1) * sample_count,
        median_ns: durations[durations.len() / 2],
    }
}

fn fixed_verifier_indices(samples_per_stratum: usize) -> Vec<usize> {
    let placebo = partition::hash_placebo(0);
    let mut members = [[0_usize; STRATUM_SIZE]; STRATUM_COUNT];
    let mut counts = [0_usize; STRATUM_COUNT];
    for (sample, &stratum) in placebo.iter().enumerate() {
        let group = stratum as usize;
        members[group][counts[group]] = sample;
        counts[group] += 1;
    }
    assert_eq!(counts, [STRATUM_SIZE; STRATUM_COUNT]);
    let mut indices = Vec::with_capacity(STRATUM_COUNT * samples_per_stratum);
    for group in members {
        indices.extend_from_slice(&group[..samples_per_stratum]);
    }
    indices
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn verifier_panels_have_exact_declared_sizes() {
        for per_stratum in [1, 2, 3, 4, 6, 8] {
            assert_eq!(fixed_verifier_indices(per_stratum).len(), 12 * per_stratum);
        }
    }
}
