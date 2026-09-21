mod audit;
mod features;
mod output;
mod partition;
mod protocol;

use std::io;
use std::path::Path;

use adaptive_runtime_ar_02a_r2::Sample;

pub fn run(samples: &[Sample], output_dir: impl AsRef<Path>) -> io::Result<usize> {
    audit::run(samples, output_dir.as_ref())
}

#[cfg(test)]
mod tests {
    use super::*;
    use adaptive_runtime_ar_02a_r2::{TRAIN_SAMPLES, generate_gaussian_cells};

    #[test]
    fn balanced_clustering_is_deterministic_and_exactly_quota_balanced() {
        let dataset = generate_gaussian_cells();
        let features = features::input_features(&dataset.samples[..TRAIN_SAMPLES]);
        let first = partition::balanced_kmeans(&features, partition::KMEANS_INIT_SEED);
        let second = partition::balanced_kmeans(&features, partition::KMEANS_INIT_SEED);
        assert_eq!(first.ids, second.ids);
        assert_eq!(first.counts, [8; 12]);
        assert!(first.within_sse.is_finite());
    }

    #[test]
    fn action_split_is_two_by_two_and_marginal_balanced() {
        let dataset = generate_gaussian_cells();
        let train = &dataset.samples[..TRAIN_SAMPLES];
        let model = adaptive_runtime_ar_02a_r2::Model::initial();
        let state = protocol::build_candidate_universe(&model, train, &train[..16], 600);
        assert!(state.eligible_blocks > 0);
        for block in 0..adaptive_runtime_ar_02a_r2::PARAMS {
            let dev: Vec<_> = state
                .development_candidates
                .iter()
                .filter(|candidate| candidate.block == block)
                .collect();
            let eval: Vec<_> = state
                .evaluation_candidates
                .iter()
                .filter(|candidate| candidate.block == block)
                .collect();
            if dev.is_empty() && eval.is_empty() {
                continue;
            }
            assert_eq!((dev.len(), eval.len()), (2, 2));
            for candidates in [&dev, &eval] {
                let mut left = [0; 2];
                let mut right = [0; 2];
                for candidate in candidates.iter() {
                    left[candidate.left_rank as usize] += 1;
                    right[candidate.right_rank as usize] += 1;
                }
                assert_eq!(left, [1, 1]);
                assert_eq!(right, [1, 1]);
            }
        }
    }

    #[test]
    fn replay_matches_frozen_ar02_reference_checkpoints() {
        let dataset = generate_gaussian_cells();
        let train = &dataset.samples[..TRAIN_SAMPLES];
        let seed = 0x2b7e_1516_28ae_d2a6;
        let snapshots = protocol::replay_seed(train, seed, protocol::StreamRole::Development)
            .expect("reference seed checkpoints");
        let rows = include_str!("../../ar-02a-r2/artifacts/r2-replay-checkpoints.csv");
        for snapshot in snapshots {
            let prefix = format!("{seed:016x},{},", snapshot.step);
            let row = rows
                .lines()
                .find(|line| line.starts_with(&prefix))
                .expect("frozen reference row");
            let fields: Vec<_> = row.split(',').collect();
            let expected_loss = fields[2].parse::<f32>().unwrap();
            let expected_fingerprint = u64::from_str_radix(fields[4], 16).unwrap();
            assert!((snapshot.train_loss - expected_loss).abs() < 1e-7);
            assert_eq!(snapshot.fingerprint, expected_fingerprint);
        }
    }
}
