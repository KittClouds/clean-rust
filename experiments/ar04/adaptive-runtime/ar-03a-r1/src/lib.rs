mod audit;
mod features;
mod model;
mod output;
mod partition;
mod protocol;

use std::io;
use std::path::Path;

pub fn run(output_dir: impl AsRef<Path>) -> io::Result<usize> {
    audit::run(output_dir.as_ref())
}

#[cfg(test)]
mod tests {
    use super::*;
    use model::{ACTION_VALUES, PARAMS, TRAIN_SAMPLES};
    use protocol::{DEVELOPMENT_SEEDS, EVALUATION_SEEDS};

    #[test]
    fn balanced_partitions_are_deterministic_and_exact_quota() {
        use std::time::{SystemTime, UNIX_EPOCH};

        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path =
            std::env::temp_dir().join(format!("ar03ar1-unit-{}-{nonce}.bin", std::process::id()));
        let dataset = model::MappedDataset::generate_write_open(&path).unwrap();
        let features = features::input_features(dataset.samples());
        let first = partition::balanced_kmeans(&features, partition::KMEANS_INIT_SEED);
        let second = partition::balanced_kmeans(&features, partition::KMEANS_INIT_SEED);
        assert_eq!(first.ids, second.ids);
        assert_eq!(first.counts, [8; 12]);
        assert!(first.within_sse.is_finite());
        drop(dataset);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn stream_seeds_are_unique_and_action_scales_are_fixed() {
        let mut seeds = DEVELOPMENT_SEEDS.to_vec();
        seeds.extend(EVALUATION_SEEDS);
        seeds.sort_unstable();
        seeds.dedup();
        assert_eq!(seeds.len(), 12);
        assert_eq!(ACTION_VALUES.len(), 7);
        assert_eq!(PARAMS, 171);
        assert_eq!(TRAIN_SAMPLES, 96);
    }
}
