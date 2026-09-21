use crate::model::TRAIN_SAMPLES;

pub const STRATUM_COUNT: usize = 12;
pub const STRATUM_SIZE: usize = 8;
pub const KMEANS_INIT_SEED: u64 = 0x4152_3033_4152_314b;
pub const KMEANS_MAX_ITERATIONS: usize = 25;
const PLACEBO_SALT: u64 = 0x4152_3033_4152_3150;

#[derive(Clone, Debug)]
pub struct BalancedPartition {
    pub ids: [u8; TRAIN_SAMPLES],
    pub counts: [usize; STRATUM_COUNT],
    pub iterations: usize,
    pub within_sse: f64,
}

pub fn balanced_kmeans(features: &[Vec<f64>], initialization_seed: u64) -> BalancedPartition {
    assert_eq!(features.len(), TRAIN_SAMPLES);
    let dimensions = features.first().expect("nonempty features").len();
    assert!(dimensions > 0);
    assert!(features.iter().all(|row| row.len() == dimensions));
    assert!(features.iter().flatten().all(|value| value.is_finite()));

    let mut centroids = initialize_centroids(features, initialization_seed);
    let mut previous = [u8::MAX; TRAIN_SAMPLES];
    let mut ids = [0_u8; TRAIN_SAMPLES];
    let mut iterations = 0;
    for iteration in 0..KMEANS_MAX_ITERATIONS {
        let distances = point_centroid_distances(features, &centroids);
        ids = capacity_assignment(&distances);
        iterations = iteration + 1;
        let stable = ids == previous;
        centroids = recompute_centroids(features, &ids, dimensions);
        if stable {
            break;
        }
        previous = ids;
    }
    let mut counts = [0_usize; STRATUM_COUNT];
    let mut within_sse = 0.0;
    for (sample, &stratum) in features.iter().zip(&ids) {
        let stratum = stratum as usize;
        counts[stratum] += 1;
        within_sse += squared_distance(sample, &centroids[stratum]);
    }
    assert_eq!(counts, [STRATUM_SIZE; STRATUM_COUNT]);
    BalancedPartition {
        ids,
        counts,
        iterations,
        within_sse,
    }
}

pub fn hash_placebo(partition_id: u8) -> [u8; TRAIN_SAMPLES] {
    let mut ranked: Vec<(u64, usize)> = (0..TRAIN_SAMPLES)
        .map(|sample| {
            (
                mix64(sample as u64 ^ PLACEBO_SALT ^ u64::from(partition_id)),
                sample,
            )
        })
        .collect();
    ranked.sort_unstable_by(|left, right| left.0.cmp(&right.0).then_with(|| left.1.cmp(&right.1)));
    let mut ids = [0_u8; TRAIN_SAMPLES];
    for (rank, &(_, sample)) in ranked.iter().enumerate() {
        ids[sample] = (rank / STRATUM_SIZE) as u8;
    }
    ids
}

pub fn stratum_counts(ids: &[u8; TRAIN_SAMPLES]) -> [usize; STRATUM_COUNT] {
    let mut counts = [0; STRATUM_COUNT];
    for &stratum in ids {
        assert!((stratum as usize) < STRATUM_COUNT);
        counts[stratum as usize] += 1;
    }
    counts
}

fn initialize_centroids(features: &[Vec<f64>], seed: u64) -> Vec<Vec<f64>> {
    let first = (0..TRAIN_SAMPLES)
        .min_by_key(|&sample| mix64(sample as u64 ^ seed))
        .expect("fixed nonempty input");
    let mut selected = [false; TRAIN_SAMPLES];
    selected[first] = true;
    let mut centroids = Vec::with_capacity(STRATUM_COUNT);
    centroids.push(features[first].clone());

    while centroids.len() < STRATUM_COUNT {
        let mut best_sample = None;
        let mut best_distance = f64::NEG_INFINITY;
        for (sample_index, sample) in features.iter().enumerate() {
            if selected[sample_index] {
                continue;
            }
            let distance = centroids
                .iter()
                .map(|centroid| squared_distance(sample, centroid))
                .fold(f64::INFINITY, f64::min);
            if distance > best_distance {
                best_distance = distance;
                best_sample = Some(sample_index);
            }
        }
        let sample = best_sample.expect("enough distinct sample indices");
        selected[sample] = true;
        centroids.push(features[sample].clone());
    }
    centroids
}

fn point_centroid_distances(features: &[Vec<f64>], centroids: &[Vec<f64>]) -> Vec<f64> {
    let dimensions = centroids[0].len();
    let mut distances = vec![0.0; TRAIN_SAMPLES * STRATUM_COUNT];
    for sample in 0..TRAIN_SAMPLES {
        for stratum in 0..STRATUM_COUNT {
            let mut distance = 0.0;
            for dimension in 0..dimensions {
                let delta = features[sample][dimension] - centroids[stratum][dimension];
                distance += delta * delta;
            }
            distances[sample * STRATUM_COUNT + stratum] = distance;
        }
    }
    distances
}

fn capacity_assignment(distances: &[f64]) -> [u8; TRAIN_SAMPLES] {
    assert_eq!(distances.len(), TRAIN_SAMPLES * STRATUM_COUNT);
    let mut slot_cost = vec![0.0; TRAIN_SAMPLES * TRAIN_SAMPLES];
    for sample in 0..TRAIN_SAMPLES {
        for slot in 0..TRAIN_SAMPLES {
            let stratum = slot / STRATUM_SIZE;
            slot_cost[sample * TRAIN_SAMPLES + slot] = distances[sample * STRATUM_COUNT + stratum];
        }
    }
    let assigned_slots = hungarian_minimize(&slot_cost);
    let mut ids = [0_u8; TRAIN_SAMPLES];
    for (sample, slot) in assigned_slots.into_iter().enumerate() {
        ids[sample] = (slot / STRATUM_SIZE) as u8;
    }
    ids
}

fn hungarian_minimize(cost: &[f64]) -> [usize; TRAIN_SAMPLES] {
    let size = TRAIN_SAMPLES;
    assert_eq!(cost.len(), size * size);
    let mut row_potential = vec![0.0; size + 1];
    let mut column_potential = vec![0.0; size + 1];
    let mut matched_row = vec![0_usize; size + 1];
    let mut predecessor = vec![0_usize; size + 1];

    for row in 1..=size {
        matched_row[0] = row;
        let mut column = 0;
        let mut minimum = vec![f64::INFINITY; size + 1];
        let mut used = vec![false; size + 1];
        loop {
            used[column] = true;
            let active_row = matched_row[column];
            let mut delta = f64::INFINITY;
            let mut next_column = 0;
            for candidate_column in 1..=size {
                if used[candidate_column] {
                    continue;
                }
                let edge = cost[(active_row - 1) * size + candidate_column - 1]
                    - row_potential[active_row]
                    - column_potential[candidate_column];
                if edge < minimum[candidate_column] {
                    minimum[candidate_column] = edge;
                    predecessor[candidate_column] = column;
                }
                if minimum[candidate_column] < delta {
                    delta = minimum[candidate_column];
                    next_column = candidate_column;
                }
            }
            for candidate_column in 0..=size {
                if used[candidate_column] {
                    row_potential[matched_row[candidate_column]] += delta;
                    column_potential[candidate_column] -= delta;
                } else {
                    minimum[candidate_column] -= delta;
                }
            }
            column = next_column;
            if matched_row[column] == 0 {
                break;
            }
        }
        loop {
            let prior = predecessor[column];
            matched_row[column] = matched_row[prior];
            column = prior;
            if column == 0 {
                break;
            }
        }
    }

    let mut assignment = [0_usize; TRAIN_SAMPLES];
    for column in 1..=size {
        assignment[matched_row[column] - 1] = column - 1;
    }
    assignment
}

fn recompute_centroids(
    features: &[Vec<f64>],
    ids: &[u8; TRAIN_SAMPLES],
    dimensions: usize,
) -> Vec<Vec<f64>> {
    let mut centroids = vec![vec![0.0; dimensions]; STRATUM_COUNT];
    for (sample, &stratum) in features.iter().zip(ids) {
        for (sum, value) in centroids[stratum as usize].iter_mut().zip(sample) {
            *sum += *value;
        }
    }
    for centroid in &mut centroids {
        for value in centroid {
            *value /= STRATUM_SIZE as f64;
        }
    }
    centroids
}

fn squared_distance(left: &[f64], right: &[f64]) -> f64 {
    left.iter()
        .zip(right)
        .map(|(left, right)| {
            let difference = left - right;
            difference * difference
        })
        .sum()
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

    #[test]
    fn eight_hash_placebos_are_distinct_and_quota_balanced() {
        let mut first = hash_placebo(0);
        for partition_id in 0..8 {
            let current = hash_placebo(partition_id);
            assert_eq!(stratum_counts(&current), [8; STRATUM_COUNT]);
            if partition_id == 1 {
                assert_ne!(first, current);
            }
            if partition_id == 0 {
                first = current;
            }
        }
    }

    #[test]
    fn capacity_assignment_obeys_exact_quotas() {
        let distances: Vec<f64> = (0..TRAIN_SAMPLES)
            .flat_map(|sample| {
                (0..STRATUM_COUNT).map(move |stratum| {
                    ((sample * 17 + stratum * 29 + sample * stratum) % 101) as f64
                })
            })
            .collect();
        let ids = capacity_assignment(&distances);
        assert_eq!(stratum_counts(&ids), [8; STRATUM_COUNT]);
    }
}
