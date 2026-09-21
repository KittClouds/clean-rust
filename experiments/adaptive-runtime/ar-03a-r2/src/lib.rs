mod aggregate;
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
    use protocol::{DATASET_SEEDS, DEVELOPMENT_SEEDS, EVALUATION_SEEDS, INITIALIZATION_SEEDS};

    #[test]
    fn balanced_partitions_are_deterministic_and_exact_quota() {
        let samples = model::generate_dataset(DATASET_SEEDS[0]);
        let initialized = model::Model::initial(INITIALIZATION_SEEDS[0]);
        let gradients = features::per_example_gradients(&initialized, &samples);
        let rows = features::gradient_features(&gradients);
        let first = partition::balanced_kmeans(&rows, partition::KMEANS_INIT_SEED);
        let second = partition::balanced_kmeans(&rows, partition::KMEANS_INIT_SEED);
        assert_eq!(first.ids, second.ids);
        assert_eq!(first.counts, [8; 12]);
        assert!(first.within_sse.is_finite());
    }

    #[test]
    fn all_data_init_and_stream_seeds_are_unique() {
        let mut seeds = DATASET_SEEDS.to_vec();
        seeds.extend(INITIALIZATION_SEEDS);
        seeds.extend(DEVELOPMENT_SEEDS);
        seeds.extend(EVALUATION_SEEDS);
        seeds.sort_unstable();
        seeds.dedup();
        assert_eq!(seeds.len(), 42);
        assert_eq!(ACTION_VALUES.len(), 7);
        assert_eq!(PARAMS, 171);
        assert_eq!(TRAIN_SAMPLES, 96);
    }

    #[test]
    fn crossed_dataset_and_initialization_seeds_change_inputs() {
        for seed in DATASET_SEEDS {
            let samples = model::generate_dataset(seed);
            let mut class_counts = [0; model::CLASSES];
            for sample in samples {
                class_counts[sample.target as usize] += 1;
            }
            assert!(class_counts.iter().all(|count| *count > 0));
        }
        let first_dataset = model::generate_dataset(DATASET_SEEDS[0]);
        let second_dataset = model::generate_dataset(DATASET_SEEDS[1]);
        assert_ne!(first_dataset[0].x, second_dataset[0].x);
        assert_ne!(
            model::Model::initial(INITIALIZATION_SEEDS[0]).parameters,
            model::Model::initial(INITIALIZATION_SEEDS[1]).parameters
        );
    }
}
