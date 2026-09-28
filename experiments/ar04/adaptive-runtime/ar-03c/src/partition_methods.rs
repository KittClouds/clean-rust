use crate::model::TRAIN_SAMPLES;
use crate::partition::{self, STRATUM_COUNT, STRATUM_SIZE};

const MAX_ITERATIONS: usize = 25;
const ORDER_SEED: u64 = 0xa303_4350_524f_4a31;

#[derive(Clone, Debug)]
pub struct Partition {
    pub ids: [u8; TRAIN_SAMPLES],
    pub centroids: Vec<Vec<f64>>,
    pub iterations: usize,
    pub within_sse: f64,
}

pub fn exact(features: &[Vec<f64>]) -> Partition {
    let result = partition::balanced_kmeans(features, partition::KMEANS_INIT_SEED);
    from_ids(features, result.ids, result.iterations)
}

pub fn warm_start(features: &[Vec<f64>], initial_centroids: &[Vec<f64>]) -> Partition {
    balanced_kmeans_from(features, initial_centroids.to_vec())
}

pub fn projected_order(features: &[Vec<f64>]) -> Partition {
    validate_features(features);
    let scale = 1.0 / (features[0].len() as f64).sqrt();
    let mut projected = [0.0_f64; TRAIN_SAMPLES];
    for (sample, row) in features.iter().enumerate() {
        for (dimension, &coordinate) in row.iter().enumerate() {
            let bit = mix64(ORDER_SEED ^ dimension as u64) & 1;
            let sign = if bit == 0 { 1.0 } else { -1.0 };
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
    from_ids(features, ids, 1)
}

pub fn nearest_centroid_quota_repair(features: &[Vec<f64>], centroids: &[Vec<f64>]) -> Partition {
    validate_features(features);
    assert_eq!(centroids.len(), STRATUM_COUNT);
    assert!(
        centroids
            .iter()
            .all(|center| center.len() == features[0].len())
    );
    let distances = point_centroid_distances(features, centroids);
    let mut ids = [0_u8; TRAIN_SAMPLES];
    let mut counts = [0_usize; STRATUM_COUNT];
    for sample in 0..TRAIN_SAMPLES {
        let mut nearest = 0;
        let mut best = distances[sample * STRATUM_COUNT];
        for cluster in 1..STRATUM_COUNT {
            let distance = distances[sample * STRATUM_COUNT + cluster];
            if distance < best {
                best = distance;
                nearest = cluster;
            }
        }
        ids[sample] = nearest as u8;
        counts[nearest] += 1;
    }

    while counts.iter().any(|&count| count != STRATUM_SIZE) {
        let mut best_move: Option<(f64, usize, usize, usize)> = None;
        for sample in 0..TRAIN_SAMPLES {
            let source = ids[sample] as usize;
            if counts[source] <= STRATUM_SIZE {
                continue;
            }
            for target in 0..STRATUM_COUNT {
                if counts[target] >= STRATUM_SIZE {
                    continue;
                }
                let increase = distances[sample * STRATUM_COUNT + target]
                    - distances[sample * STRATUM_COUNT + source];
                let candidate = (increase, sample, source, target);
                if best_move.is_none_or(|best| move_order(candidate, best).is_lt()) {
                    best_move = Some(candidate);
                }
            }
        }
        let (_, sample, source, target) = best_move.expect("overfull and underfull clusters exist");
        ids[sample] = target as u8;
        counts[source] -= 1;
        counts[target] += 1;
    }
    from_ids(features, ids, 1)
}

pub fn hash_placebo_mean_ids() -> Vec<[u8; TRAIN_SAMPLES]> {
    (0..8).map(partition::hash_placebo).collect()
}

pub fn centroids_from_partition(features: &[Vec<f64>], ids: &[u8; TRAIN_SAMPLES]) -> Vec<Vec<f64>> {
    validate_features(features);
    let dimensions = features[0].len();
    let mut centroids = vec![vec![0.0; dimensions]; STRATUM_COUNT];
    let mut counts = [0_usize; STRATUM_COUNT];
    for (row, &cluster) in features.iter().zip(ids) {
        let cluster = cluster as usize;
        assert!(cluster < STRATUM_COUNT);
        counts[cluster] += 1;
        for (sum, &coordinate) in centroids[cluster].iter_mut().zip(row) {
            *sum += coordinate;
        }
    }
    assert_eq!(counts, [STRATUM_SIZE; STRATUM_COUNT]);
    for center in &mut centroids {
        for value in center {
            *value /= STRATUM_SIZE as f64;
        }
    }
    centroids
}

fn balanced_kmeans_from(features: &[Vec<f64>], mut centroids: Vec<Vec<f64>>) -> Partition {
    validate_features(features);
    assert_eq!(centroids.len(), STRATUM_COUNT);
    assert!(
        centroids
            .iter()
            .all(|center| center.len() == features[0].len())
    );
    let mut previous = [u8::MAX; TRAIN_SAMPLES];
    let mut ids = [0_u8; TRAIN_SAMPLES];
    let mut iterations = 0;
    for iteration in 0..MAX_ITERATIONS {
        let distances = point_centroid_distances(features, &centroids);
        ids = capacity_assignment(&distances);
        iterations = iteration + 1;
        let stable = ids == previous;
        centroids = centroids_from_partition(features, &ids);
        if stable {
            break;
        }
        previous = ids;
    }
    from_ids_with_centroids(features, ids, iterations, centroids)
}

fn from_ids(features: &[Vec<f64>], ids: [u8; TRAIN_SAMPLES], iterations: usize) -> Partition {
    let centroids = centroids_from_partition(features, &ids);
    from_ids_with_centroids(features, ids, iterations, centroids)
}

fn from_ids_with_centroids(
    features: &[Vec<f64>],
    ids: [u8; TRAIN_SAMPLES],
    iterations: usize,
    centroids: Vec<Vec<f64>>,
) -> Partition {
    assert_eq!(
        partition::stratum_counts(&ids),
        [STRATUM_SIZE; STRATUM_COUNT]
    );
    let within_sse = features
        .iter()
        .zip(&ids)
        .map(|(row, &cluster)| squared_distance(row, &centroids[cluster as usize]))
        .sum();
    Partition {
        ids,
        centroids,
        iterations,
        within_sse,
    }
}

fn point_centroid_distances(features: &[Vec<f64>], centroids: &[Vec<f64>]) -> Vec<f64> {
    let dimensions = features[0].len();
    let mut distances = vec![0.0; TRAIN_SAMPLES * STRATUM_COUNT];
    for sample in 0..TRAIN_SAMPLES {
        for cluster in 0..STRATUM_COUNT {
            let mut distance = 0.0;
            for dimension in 0..dimensions {
                let delta = features[sample][dimension] - centroids[cluster][dimension];
                distance += delta * delta;
            }
            distances[sample * STRATUM_COUNT + cluster] = distance;
        }
    }
    distances
}

fn capacity_assignment(distances: &[f64]) -> [u8; TRAIN_SAMPLES] {
    let mut slot_cost = vec![0.0; TRAIN_SAMPLES * TRAIN_SAMPLES];
    for sample in 0..TRAIN_SAMPLES {
        for slot in 0..TRAIN_SAMPLES {
            slot_cost[sample * TRAIN_SAMPLES + slot] =
                distances[sample * STRATUM_COUNT + slot / STRATUM_SIZE];
        }
    }
    let assigned = hungarian_minimize(&slot_cost);
    std::array::from_fn(|sample| (assigned[sample] / STRATUM_SIZE) as u8)
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
            for candidate in 1..=size {
                if used[candidate] {
                    continue;
                }
                let edge = cost[(active_row - 1) * size + candidate - 1]
                    - row_potential[active_row]
                    - column_potential[candidate];
                if edge < minimum[candidate] {
                    minimum[candidate] = edge;
                    predecessor[candidate] = column;
                }
                if minimum[candidate] < delta {
                    delta = minimum[candidate];
                    next_column = candidate;
                }
            }
            for candidate in 0..=size {
                if used[candidate] {
                    row_potential[matched_row[candidate]] += delta;
                    column_potential[candidate] -= delta;
                } else {
                    minimum[candidate] -= delta;
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

fn move_order(
    left: (f64, usize, usize, usize),
    right: (f64, usize, usize, usize),
) -> std::cmp::Ordering {
    left.0
        .total_cmp(&right.0)
        .then_with(|| left.1.cmp(&right.1))
        .then_with(|| left.3.cmp(&right.3))
        .then_with(|| left.2.cmp(&right.2))
}

fn squared_distance(left: &[f64], right: &[f64]) -> f64 {
    left.iter()
        .zip(right)
        .map(|(&left, &right)| {
            let difference = left - right;
            difference * difference
        })
        .sum()
}

fn validate_features(features: &[Vec<f64>]) {
    assert_eq!(features.len(), TRAIN_SAMPLES);
    let dimensions = features.first().expect("nonempty features").len();
    assert!(dimensions > 0);
    assert!(features.iter().all(|row| row.len() == dimensions));
    assert!(features.iter().flatten().all(|value| value.is_finite()));
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

    fn features() -> Vec<Vec<f64>> {
        (0..TRAIN_SAMPLES)
            .map(|sample| {
                (0..27)
                    .map(|dimension| {
                        ((sample * 37 + dimension * 19 + sample * dimension) % 127) as f64
                    })
                    .collect()
            })
            .collect()
    }

    #[test]
    fn projected_order_is_deterministic_and_exactly_balanced() {
        let rows = features();
        let first = projected_order(&rows);
        let second = projected_order(&rows);
        assert_eq!(first.ids, second.ids);
        assert_eq!(partition::stratum_counts(&first.ids), [8; 12]);
    }

    #[test]
    fn quota_repair_fills_exact_capacities() {
        let rows = features();
        let initial = exact(&rows);
        let repaired = nearest_centroid_quota_repair(&rows, &initial.centroids);
        assert_eq!(partition::stratum_counts(&repaired.ids), [8; 12]);
    }

    #[test]
    fn warm_start_from_current_centroids_is_stable() {
        let rows = features();
        let initial = exact(&rows);
        let warmed = warm_start(&rows, &initial.centroids);
        assert_eq!(partition::stratum_counts(&warmed.ids), [8; 12]);
        assert!(warmed.within_sse.is_finite());
    }
}
