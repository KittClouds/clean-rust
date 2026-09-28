use std::fs;
use std::io;
use std::path::Path;

use crate::aggregate;
use crate::features;
use crate::model::{PARAMS, TRAIN_SAMPLES};
use crate::output;
use crate::partition::{self, STRATUM_COUNT, STRATUM_SIZE};
use crate::protocol::{
    Candidate, DATASET_SEEDS, INITIALIZATION_SEEDS, StateSnapshot, StreamRole, collect_states,
};

const PANEL_REPLICATES: usize = 64;
const SIGN_EPSILON: f64 = 1.0e-8;
const PANEL_SEED_SALT: u64 = 0x4152_3033_4152_3150;

#[derive(Clone, Debug)]
pub(super) struct PanelRecord {
    pub dataset_index: u8,
    pub initialization_index: u8,
    pub seed: u64,
    pub step: usize,
    pub method: String,
    pub panel: usize,
    pub candidate_count: usize,
    pub utility_rmse: f64,
    pub sign_error_rate: f64,
    pub cross_block_regret: f64,
    pub selected_program_regret: f64,
    pub false_authorization: bool,
}

#[derive(Clone, Debug, Default)]
pub(super) struct MetricMean {
    pub method: String,
    pub dataset_index: u8,
    pub initialization_index: u8,
    pub seed: u64,
    pub n_states: usize,
    pub within_stratum_variance: f64,
    pub predicted_rmse: f64,
    pub observed_rmse: f64,
    pub sign_error_rate: f64,
    pub cross_block_regret: f64,
    pub selected_program_regret: f64,
    pub false_authorization_rate: f64,
}

#[derive(Clone, Debug)]
pub(super) struct StateMetric {
    pub dataset_index: u8,
    pub initialization_index: u8,
    pub seed: u64,
    pub step: usize,
    pub method: String,
    pub candidate_count: usize,
    pub within_stratum_variance: f64,
    pub predicted_rmse: f64,
    pub observed_rmse: f64,
    pub sign_error_rate: f64,
    pub cross_block_regret: f64,
    pub selected_program_regret: f64,
    pub false_authorization_rate: f64,
}

#[derive(Clone, Debug)]
pub(super) struct TaylorRecord {
    pub dataset_index: u8,
    pub initialization_index: u8,
    pub seed: u64,
    pub step: usize,
    pub candidate_count: usize,
    pub point_count: usize,
    pub rmse: f64,
    pub correlation: f64,
    pub r_squared: f64,
    pub sign_error_rate: f64,
}

#[derive(Clone, Debug)]
pub(super) struct CandidateRecord {
    pub role: String,
    pub dataset_index: u8,
    pub initialization_index: u8,
    pub dataset_seed: u64,
    pub initialization_seed: u64,
    pub seed: u64,
    pub step: usize,
    pub split: String,
    pub block: usize,
    pub left_parameter: usize,
    pub right_parameter: usize,
    pub left_rank: u8,
    pub right_rank: u8,
    pub left_delta: f32,
    pub right_delta: f32,
    pub exact_utility: [f64; 1],
}

#[derive(Clone, Debug)]
pub(super) struct PartitionRecord {
    pub role: String,
    pub dataset_index: u8,
    pub initialization_index: u8,
    pub seed: u64,
    pub step: usize,
    pub method: String,
    pub sample: usize,
    pub stratum: u8,
    pub iterations: usize,
    pub within_sse: f64,
}

#[derive(Clone, Debug)]
struct MethodPartition {
    name: String,
    ids: [u8; TRAIN_SAMPLES],
    iterations: usize,
    within_sse: f64,
}

#[derive(Clone, Copy, Debug)]
struct PanelMetrics {
    utility_rmse: f64,
    sign_error_rate: f64,
    cross_block_regret: f64,
    selected_program_regret: f64,
    false_authorization: bool,
}

pub fn run(output_dir: &Path) -> io::Result<usize> {
    if output_dir.exists() {
        return Err(io::Error::new(
            io::ErrorKind::AlreadyExists,
            format!(
                "refusing to overwrite existing run directory: {}",
                output_dir.display()
            ),
        ));
    }
    if let Some(parent) = output_dir.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::create_dir(output_dir)?;
    let mut datasets = Vec::with_capacity(DATASET_SEEDS.len());
    for (index, seed) in DATASET_SEEDS.iter().copied().enumerate() {
        let path = output_dir.join(format!("dataset-d{index:02}.bin"));
        datasets.push(crate::model::MappedDataset::generate_write_open(
            path, seed,
        )?);
    }
    let mut states = Vec::with_capacity(108);
    for (dataset_index, dataset_seed) in DATASET_SEEDS.iter().copied().enumerate() {
        for (initialization_index, initialization_seed) in
            INITIALIZATION_SEEDS.iter().copied().enumerate()
        {
            states.extend(collect_states(
                datasets[dataset_index].samples(),
                dataset_index as u8,
                dataset_seed,
                initialization_index as u8,
                initialization_seed,
            ));
        }
    }
    let development: Vec<_> = states
        .iter()
        .filter(|state| state.role == StreamRole::Development)
        .collect();
    let evaluation: Vec<_> = states
        .iter()
        .filter(|state| state.role == StreamRole::Evaluation)
        .collect();
    assert_eq!(development.len(), 54);
    assert_eq!(evaluation.len(), 54);

    let mut development_oracles = Vec::with_capacity(9);
    let mut development_response_dimensions = Vec::with_capacity(9);
    for dataset_index in 0..DATASET_SEEDS.len() as u8 {
        for initialization_index in 0..INITIALIZATION_SEEDS.len() as u8 {
            let cell_states: Vec<_> = development
                .iter()
                .filter(|state| {
                    state.dataset_index == dataset_index
                        && state.initialization_index == initialization_index
                })
                .collect();
            assert_eq!(cell_states.len(), 6);
            let responses = response_features(
                cell_states
                    .iter()
                    .map(|state| state.development_candidates.as_slice()),
            );
            development_response_dimensions.push(responses[0].len());
            development_oracles.push(partition_from_features(
                &responses,
                "development_response_oracle",
            ));
        }
    }

    let method_count = 11;
    let mut panels = Vec::with_capacity(evaluation.len() * method_count * PANEL_REPLICATES);
    let mut state_metrics = Vec::with_capacity(evaluation.len() * method_count);
    let mut partition_rows =
        Vec::with_capacity((evaluation.len() * method_count + 9) * TRAIN_SAMPLES);
    let mut taylor_rows = Vec::with_capacity(evaluation.len());
    let mut candidate_rows = Vec::new();
    for state in &states {
        let role = state.role.as_str().to_owned();
        candidate_rows.extend(state.development_candidates.iter().map(|candidate| {
            CandidateRecord {
                role: role.clone(),
                dataset_index: state.dataset_index,
                initialization_index: state.initialization_index,
                dataset_seed: state.dataset_seed,
                initialization_seed: state.initialization_seed,
                seed: state.seed,
                step: state.step,
                split: "development".to_owned(),
                block: candidate.block,
                left_parameter: candidate.left_parameter,
                right_parameter: candidate.right_parameter,
                left_rank: candidate.left_rank,
                right_rank: candidate.right_rank,
                left_delta: candidate.left_delta,
                right_delta: candidate.right_delta,
                exact_utility: candidate.exact_utility,
            }
        }));
        candidate_rows.extend(state.evaluation_candidates.iter().map(|candidate| {
            CandidateRecord {
                role: role.clone(),
                dataset_index: state.dataset_index,
                initialization_index: state.initialization_index,
                dataset_seed: state.dataset_seed,
                initialization_seed: state.initialization_seed,
                seed: state.seed,
                step: state.step,
                split: "evaluation".to_owned(),
                block: candidate.block,
                left_parameter: candidate.left_parameter,
                right_parameter: candidate.right_parameter,
                left_rank: candidate.left_rank,
                right_rank: candidate.right_rank,
                left_delta: candidate.left_delta,
                right_delta: candidate.right_delta,
                exact_utility: candidate.exact_utility,
            }
        }));
    }

    for (cell_index, oracle) in development_oracles.iter().enumerate() {
        add_partition_rows(
            &mut partition_rows,
            "development",
            (cell_index / INITIALIZATION_SEEDS.len()) as u8,
            (cell_index % INITIALIZATION_SEEDS.len()) as u8,
            0,
            0,
            oracle,
        );
    }

    for state in &evaluation {
        assert!(!state.evaluation_candidates.is_empty());
        let train = datasets[usize::from(state.dataset_index)].samples();
        let gradients = features::per_example_gradients(&state.model, train);
        let gradient_partition =
            partition_from_features(&features::gradient_features(&gradients), "gradient_full171");
        let cell_index = usize::from(state.dataset_index) * INITIALIZATION_SEEDS.len()
            + usize::from(state.initialization_index);
        let evaluation_responses =
            response_features(std::iter::once(state.evaluation_candidates.as_slice()));
        let evaluation_oracle = partition_from_features(
            &evaluation_responses,
            "evaluation_state_response_comparator",
        );
        let methods = method_partitions(
            &gradient_partition,
            &development_oracles[cell_index],
            &evaluation_oracle,
        );
        taylor_rows.push(audit_taylor(state, &gradients));

        for method in methods {
            add_partition_rows(
                &mut partition_rows,
                "evaluation",
                state.dataset_index,
                state.initialization_index,
                state.seed,
                state.step,
                &method,
            );
            let (within_variance, predicted_rmse) =
                predicted_partition_error(&method.ids, &state.evaluation_candidates);
            let panel_seed_base = state.seed
                ^ PANEL_SEED_SALT
                ^ (state.step as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15);
            let mut squared_rmse = 0.0;
            let mut sign_error = 0.0;
            let mut cross_block_regret = 0.0;
            let mut selected_program_regret = 0.0;
            let mut false_authorizations = 0;
            for panel in 0..PANEL_REPLICATES {
                let panel_seed =
                    panel_seed_base ^ (panel as u64).wrapping_mul(0xd6e8_feb8_6659_fd93);
                let selected = sample_panel(&method.ids, panel_seed);
                let metrics = audit_panel(&state.evaluation_candidates, &selected);
                squared_rmse += metrics.utility_rmse * metrics.utility_rmse;
                sign_error += metrics.sign_error_rate;
                cross_block_regret += metrics.cross_block_regret;
                selected_program_regret += metrics.selected_program_regret;
                false_authorizations += usize::from(metrics.false_authorization);
                panels.push(PanelRecord {
                    dataset_index: state.dataset_index,
                    initialization_index: state.initialization_index,
                    seed: state.seed,
                    step: state.step,
                    method: method.name.clone(),
                    panel,
                    candidate_count: state.evaluation_candidates.len(),
                    utility_rmse: metrics.utility_rmse,
                    sign_error_rate: metrics.sign_error_rate,
                    cross_block_regret: metrics.cross_block_regret,
                    selected_program_regret: metrics.selected_program_regret,
                    false_authorization: metrics.false_authorization,
                });
            }
            let inverse_panels = 1.0 / PANEL_REPLICATES as f64;
            state_metrics.push(StateMetric {
                dataset_index: state.dataset_index,
                initialization_index: state.initialization_index,
                seed: state.seed,
                step: state.step,
                method: method.name,
                candidate_count: state.evaluation_candidates.len(),
                within_stratum_variance: within_variance,
                predicted_rmse,
                observed_rmse: (squared_rmse * inverse_panels).sqrt(),
                sign_error_rate: sign_error * inverse_panels,
                cross_block_regret: cross_block_regret * inverse_panels,
                selected_program_regret: selected_program_regret * inverse_panels,
                false_authorization_rate: false_authorizations as f64 * inverse_panels,
            });
        }
    }

    let stream_means = aggregate::by_stream(&state_metrics);
    let cell_means = aggregate::cells(&stream_means);
    let dataset_means = aggregate::datasets(&cell_means);
    let initialization_means = aggregate::initializations(&cell_means);
    let summaries = aggregate::overall(&cell_means);
    output::write_all(
        output_dir,
        output::OutputData {
            states: &states,
            candidates: &candidate_rows,
            partitions: &partition_rows,
            panels: &panels,
            state_metrics: &state_metrics,
            stream_means: &stream_means,
            cell_means: &cell_means,
            dataset_means: &dataset_means,
            initialization_means: &initialization_means,
            summaries: &summaries,
            taylor: &taylor_rows,
            datasets: &datasets,
            development_response_dimensions: &development_response_dimensions,
        },
    )?;
    Ok(panels.len())
}

fn partition_from_features(features: &[Vec<f64>], name: &str) -> MethodPartition {
    let partition = partition::balanced_kmeans(features, partition::KMEANS_INIT_SEED);
    assert_eq!(partition.counts, [STRATUM_SIZE; STRATUM_COUNT]);
    MethodPartition {
        name: name.to_owned(),
        ids: partition.ids,
        iterations: partition.iterations,
        within_sse: partition.within_sse,
    }
}

fn method_partitions(
    gradient: &MethodPartition,
    development: &MethodPartition,
    evaluation: &MethodPartition,
) -> Vec<MethodPartition> {
    let mut methods = Vec::with_capacity(11);
    for placebo in 0..8 {
        methods.push(MethodPartition {
            name: format!("hash_placebo_{placebo:02}"),
            ids: partition::hash_placebo(placebo),
            iterations: 0,
            within_sse: 0.0,
        });
    }
    methods.extend([gradient.clone(), development.clone(), evaluation.clone()]);
    assert_eq!(methods.len(), 11);
    methods
}

fn response_features<'a>(candidate_sets: impl Iterator<Item = &'a [Candidate]>) -> Vec<Vec<f64>> {
    let sets: Vec<_> = candidate_sets.collect();
    let capacity = sets.iter().map(|candidates| candidates.len()).sum();
    let mut rows: Vec<Vec<f64>> = (0..TRAIN_SAMPLES)
        .map(|_| Vec::with_capacity(capacity))
        .collect();
    for candidates in sets {
        for candidate in candidates {
            for (row, &utility) in rows.iter_mut().zip(&candidate.per_example_utility[0]) {
                row.push(f64::from(utility));
            }
        }
    }
    assert!(rows.iter().all(|row| row.len() == capacity));
    rows
}

fn add_partition_rows(
    rows: &mut Vec<PartitionRecord>,
    role: &str,
    dataset_index: u8,
    initialization_index: u8,
    seed: u64,
    step: usize,
    partition: &MethodPartition,
) {
    assert_eq!(
        partition::stratum_counts(&partition.ids),
        [STRATUM_SIZE; STRATUM_COUNT]
    );
    for (sample, &stratum) in partition.ids.iter().enumerate() {
        rows.push(PartitionRecord {
            role: role.to_owned(),
            dataset_index,
            initialization_index,
            seed,
            step,
            method: partition.name.clone(),
            sample,
            stratum,
            iterations: partition.iterations,
            within_sse: partition.within_sse,
        });
    }
}

fn predicted_partition_error(ids: &[u8; TRAIN_SAMPLES], candidates: &[Candidate]) -> (f64, f64) {
    let mut members = [[0_usize; STRATUM_SIZE]; STRATUM_COUNT];
    let mut counts = [0_usize; STRATUM_COUNT];
    for (sample, &stratum) in ids.iter().enumerate() {
        let group = stratum as usize;
        members[group][counts[group]] = sample;
        counts[group] += 1;
    }
    assert_eq!(counts, [STRATUM_SIZE; STRATUM_COUNT]);
    let mut within_sum = 0.0;
    let mut estimator_variance_sum = 0.0;
    for candidate in candidates {
        let utilities = &candidate.per_example_utility[0];
        let mut candidate_within = 0.0;
        let mut candidate_variance = 0.0;
        for group_members in &members {
            let mean = group_members
                .iter()
                .map(|&sample| f64::from(utilities[sample]))
                .sum::<f64>()
                / STRATUM_SIZE as f64;
            let sum_squares = group_members
                .iter()
                .map(|&sample| {
                    let difference = f64::from(utilities[sample]) - mean;
                    difference * difference
                })
                .sum::<f64>();
            let sample_variance = sum_squares / (STRATUM_SIZE - 1) as f64;
            candidate_within += sample_variance / STRATUM_COUNT as f64;
            candidate_variance += (1.0 / (STRATUM_COUNT * STRATUM_COUNT) as f64)
                * (1.0 - 4.0 / STRATUM_SIZE as f64)
                * sample_variance
                / 4.0;
        }
        within_sum += candidate_within;
        estimator_variance_sum += candidate_variance;
    }
    let count = candidates.len() as f64;
    (within_sum / count, (estimator_variance_sum / count).sqrt())
}

fn sample_panel(ids: &[u8; TRAIN_SAMPLES], seed: u64) -> [[usize; 4]; STRATUM_COUNT] {
    let mut members = [[0_usize; STRATUM_SIZE]; STRATUM_COUNT];
    let mut counts = [0_usize; STRATUM_COUNT];
    for (sample, &stratum) in ids.iter().enumerate() {
        let group = stratum as usize;
        members[group][counts[group]] = sample;
        counts[group] += 1;
    }
    assert_eq!(counts, [STRATUM_SIZE; STRATUM_COUNT]);
    let mut rng = PanelRng { state: seed };
    let mut result = [[0_usize; 4]; STRATUM_COUNT];
    for group in 0..STRATUM_COUNT {
        for offset in 0..4 {
            let selected = offset + rng.next() as usize % (STRATUM_SIZE - offset);
            members[group].swap(offset, selected);
            result[group][offset] = members[group][offset];
        }
    }
    result
}

fn audit_panel(candidates: &[Candidate], panel: &[[usize; 4]; STRATUM_COUNT]) -> PanelMetrics {
    assert!(!candidates.is_empty());
    let block_count = candidates
        .iter()
        .map(|candidate| candidate.block)
        .max()
        .unwrap_or(0)
        + 1;
    let mut block_exact = vec![0.0_f64; block_count];
    let mut block_estimated = vec![0.0_f64; block_count];
    let mut block_choice = vec![None; block_count];
    let mut squared_error = 0.0;
    let mut sign_errors = 0_usize;
    let mut sign_trials = 0_usize;
    let mut estimates = Vec::with_capacity(candidates.len());

    for candidate in candidates {
        let utilities = &candidate.per_example_utility[0];
        let mut estimate = 0.0;
        for selected in panel {
            let group_mean = selected
                .iter()
                .map(|&sample| f64::from(utilities[sample]))
                .sum::<f64>()
                / selected.len() as f64;
            estimate += group_mean / STRATUM_COUNT as f64;
        }
        let exact = candidate.exact_utility[0];
        let difference = estimate - exact;
        squared_error += difference * difference;
        if exact.abs() > SIGN_EPSILON {
            sign_trials += 1;
            sign_errors += usize::from((estimate > 0.0) != (exact > 0.0));
        }
        block_exact[candidate.block] = block_exact[candidate.block].max(exact);
        if estimate > block_estimated[candidate.block] {
            block_estimated[candidate.block] = estimate;
            block_choice[candidate.block] = Some(estimates.len());
        }
        estimates.push(estimate);
    }

    let exact_best = block_exact.iter().copied().fold(0.0_f64, f64::max);
    let mut selected_block = None;
    let mut selected_estimate = 0.0;
    for (block, &estimate) in block_estimated.iter().enumerate() {
        if estimate > selected_estimate && block_choice[block].is_some() {
            selected_estimate = estimate;
            selected_block = Some(block);
        }
    }
    let selected_index = selected_block.and_then(|block| block_choice[block]);
    let selected_utility = selected_index.map_or(0.0, |index| candidates[index].exact_utility[0]);
    let selected_block_exact = selected_block.map_or(0.0, |block| block_exact[block]);
    PanelMetrics {
        utility_rmse: (squared_error / candidates.len() as f64).sqrt(),
        sign_error_rate: sign_errors as f64 / sign_trials.max(1) as f64,
        cross_block_regret: (exact_best - selected_block_exact).max(0.0),
        selected_program_regret: (exact_best - selected_utility).max(0.0),
        false_authorization: selected_index
            .is_some_and(|index| candidates[index].exact_utility[0] <= 0.0),
    }
}

fn audit_taylor(state: &StateSnapshot, gradients: &[[f32; PARAMS]]) -> TaylorRecord {
    let mut actual = Vec::with_capacity(state.evaluation_candidates.len() * TRAIN_SAMPLES);
    let mut predicted = Vec::with_capacity(actual.capacity());
    let mut sign_errors = 0;
    let mut sign_trials = 0;
    for candidate in &state.evaluation_candidates {
        for (sample, gradient) in gradients.iter().enumerate() {
            let linear = -f64::from(
                gradient[candidate.left_parameter] * candidate.left_delta
                    + gradient[candidate.right_parameter] * candidate.right_delta,
            );
            let utility = f64::from(candidate.per_example_utility[0][sample]);
            actual.push(utility);
            predicted.push(linear);
            if utility.abs() > SIGN_EPSILON {
                sign_trials += 1;
                sign_errors += usize::from((utility > 0.0) != (linear > 0.0));
            }
        }
    }
    let count = actual.len().max(1) as f64;
    let mean_actual = actual.iter().sum::<f64>() / count;
    let mean_predicted = predicted.iter().sum::<f64>() / count;
    let mut covariance = 0.0;
    let mut actual_variance = 0.0;
    let mut predicted_variance = 0.0;
    let mut squared_error = 0.0;
    for (&truth, &estimate) in actual.iter().zip(&predicted) {
        let actual_delta = truth - mean_actual;
        let predicted_delta = estimate - mean_predicted;
        covariance += actual_delta * predicted_delta;
        actual_variance += actual_delta * actual_delta;
        predicted_variance += predicted_delta * predicted_delta;
        let residual = truth - estimate;
        squared_error += residual * residual;
    }
    let correlation = if actual_variance > 0.0 && predicted_variance > 0.0 {
        covariance / (actual_variance * predicted_variance).sqrt()
    } else {
        0.0
    };
    TaylorRecord {
        dataset_index: state.dataset_index,
        initialization_index: state.initialization_index,
        seed: state.seed,
        step: state.step,
        candidate_count: state.evaluation_candidates.len(),
        point_count: actual.len(),
        rmse: (squared_error / count).sqrt(),
        correlation,
        r_squared: if actual_variance > 0.0 {
            1.0 - squared_error / actual_variance
        } else {
            0.0
        },
        sign_error_rate: sign_errors as f64 / sign_trials.max(1) as f64,
    }
}

struct PanelRng {
    state: u64,
}

impl PanelRng {
    fn next(&mut self) -> u64 {
        let mut value = self.state;
        value ^= value << 7;
        value ^= value >> 9;
        value ^= value << 8;
        self.state = value;
        value
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finite_population_prediction_matches_panel_design_parameters() {
        assert_eq!(TRAIN_SAMPLES, STRATUM_COUNT * STRATUM_SIZE);
        assert_eq!(STRATUM_SIZE - 4, 4);
        assert_eq!(STRATUM_COUNT * STRATUM_SIZE, TRAIN_SAMPLES);
    }
}
