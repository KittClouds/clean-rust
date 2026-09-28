use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::Path;

use adaptive_runtime_ar_02a_r2::{Sample, TRAIN_SAMPLES};

use crate::features;
use crate::output;
use crate::partition::{self, STRATUM_COUNT, STRATUM_SIZE};
use crate::protocol::{Candidate, StateSnapshot, StreamRole, collect_states};

const PANEL_REPLICATES: usize = 64;
const SIGN_EPSILON: f64 = 1.0e-8;
const PANEL_SEED_SALT: u64 = 0x4130_3350_414e_454c;

#[derive(Clone, Debug)]
pub(super) struct PanelRecord {
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
    pub seed: u64,
    pub step: usize,
    pub action_split: String,
    pub candidate: Candidate,
}

#[derive(Clone, Debug)]
pub(super) struct PartitionRecord {
    pub role: String,
    pub seed: u64,
    pub step: usize,
    pub method: String,
    pub sample: usize,
    pub stratum: u8,
    pub kmeans_iterations: usize,
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

pub fn run(samples: &[Sample], output_dir: &Path) -> io::Result<usize> {
    if samples.len() < TRAIN_SAMPLES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "AR-03A dataset does not contain the 96 frozen training examples",
        ));
    }
    fs::create_dir(output_dir)?;
    let train = &samples[..TRAIN_SAMPLES];
    let states = collect_states(train);
    let development: Vec<_> = states
        .iter()
        .filter(|state| state.role == StreamRole::Development)
        .collect();
    let evaluation: Vec<_> = states
        .iter()
        .filter(|state| state.role == StreamRole::Evaluation)
        .collect();
    assert_eq!(development.len(), 18);
    assert_eq!(evaluation.len(), 18);

    let input_partition = partition_from_features(&features::input_features(train), "input_only");
    let development_response_features = response_features(
        development
            .iter()
            .map(|state| state.development_candidates.as_slice()),
    );
    let development_oracle = partition_from_features(
        &development_response_features,
        "development_response_oracle",
    );

    let mut panels = Vec::with_capacity(evaluation.len() * (8 + 5) * PANEL_REPLICATES);
    let mut state_metrics = Vec::with_capacity(evaluation.len() * 13);
    let mut partition_rows = Vec::with_capacity((evaluation.len() * 13 + 1) * TRAIN_SAMPLES);
    let mut taylor_rows = Vec::with_capacity(evaluation.len());
    let mut candidate_rows = Vec::new();

    for state in &states {
        let role = state.role.as_str().to_owned();
        candidate_rows.extend(
            state
                .development_candidates
                .iter()
                .copied()
                .map(|candidate| CandidateRecord {
                    role: role.clone(),
                    seed: state.seed,
                    step: state.step,
                    action_split: "development".to_owned(),
                    candidate,
                }),
        );
        candidate_rows.extend(
            state
                .evaluation_candidates
                .iter()
                .copied()
                .map(|candidate| CandidateRecord {
                    role: role.clone(),
                    seed: state.seed,
                    step: state.step,
                    action_split: "evaluation".to_owned(),
                    candidate,
                }),
        );
    }
    add_partition_rows(
        &mut partition_rows,
        "development",
        0,
        0,
        &development_oracle,
    );

    for state in &evaluation {
        assert!(!state.evaluation_candidates.is_empty());
        let gradients = features::per_example_gradients(&state.model, train);
        let state_partition = partition_from_features(
            &features::current_state_features(&state.model, train),
            "state_stats",
        );
        let gradient_partition =
            partition_from_features(&features::gradient_features(&gradients), "gradient_full123");
        let evaluation_response_features =
            response_features(std::iter::once(state.evaluation_candidates.as_slice()));
        let evaluation_oracle = partition_from_features(
            &evaluation_response_features,
            "evaluation_state_response_oracle",
        );
        let mut methods = Vec::with_capacity(13);
        for placebo in 0..8 {
            let ids = partition::hash_placebo(placebo);
            methods.push(MethodPartition {
                name: format!("hash_placebo_{placebo:02}"),
                ids,
                iterations: 0,
                within_sse: 0.0,
            });
        }
        methods.push(input_partition.clone());
        methods.push(state_partition);
        methods.push(gradient_partition);
        methods.push(development_oracle.clone());
        methods.push(evaluation_oracle);
        assert_eq!(methods.len(), 13);

        let taylor = audit_taylor(state, &gradients);
        taylor_rows.push(taylor);
        for method in methods {
            add_partition_rows(
                &mut partition_rows,
                "evaluation",
                state.seed,
                state.step,
                &method,
            );
            let (within_variance, predicted_rmse) =
                predicted_partition_error(&method.ids, &state.evaluation_candidates);
            let panel_seed_base = state.seed
                ^ PANEL_SEED_SALT
                ^ (state.step as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15);
            let mut records = Vec::with_capacity(PANEL_REPLICATES);
            let mut squared_panel_rmse = 0.0;
            let mut sign_error = 0.0;
            let mut cross_block_regret = 0.0;
            let mut selected_program_regret = 0.0;
            let mut false_authorizations = 0;
            for panel in 0..PANEL_REPLICATES {
                let panel_seed =
                    panel_seed_base ^ (panel as u64).wrapping_mul(0xd6e8_feb8_6659_fd93);
                let indices = sample_panel(&method.ids, panel_seed);
                let metrics = audit_panel(&state.evaluation_candidates, &indices);
                squared_panel_rmse += metrics.utility_rmse * metrics.utility_rmse;
                sign_error += metrics.sign_error_rate;
                cross_block_regret += metrics.cross_block_regret;
                selected_program_regret += metrics.selected_program_regret;
                false_authorizations += usize::from(metrics.false_authorization);
                let row = PanelRecord {
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
                };
                records.push(row.clone());
                panels.push(row);
            }
            let inverse_panels = 1.0 / PANEL_REPLICATES as f64;
            state_metrics.push(StateMetric {
                seed: state.seed,
                step: state.step,
                method: method.name,
                candidate_count: state.evaluation_candidates.len(),
                within_stratum_variance: within_variance,
                predicted_rmse,
                observed_rmse: (squared_panel_rmse * inverse_panels).sqrt(),
                sign_error_rate: sign_error * inverse_panels,
                cross_block_regret: cross_block_regret * inverse_panels,
                selected_program_regret: selected_program_regret * inverse_panels,
                false_authorization_rate: false_authorizations as f64 * inverse_panels,
            });
            debug_assert_eq!(records.len(), PANEL_REPLICATES);
        }
    }

    let seed_means = aggregate_by_seed(&state_metrics);
    let summaries = aggregate_seeds(&seed_means);
    output::write_all(
        output_dir,
        output::OutputData {
            states: &states,
            candidates: &candidate_rows,
            partitions: &partition_rows,
            panels: &panels,
            state_metrics: &state_metrics,
            seed_means: &seed_means,
            summaries: &summaries,
            taylor: &taylor_rows,
            development_response_dimensions: development_response_features[0].len(),
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

fn response_features<'a>(candidate_sets: impl Iterator<Item = &'a [Candidate]>) -> Vec<Vec<f64>> {
    let candidate_sets: Vec<_> = candidate_sets.collect();
    let capacity = candidate_sets
        .iter()
        .map(|candidates| candidates.len())
        .sum();
    let mut rows: Vec<Vec<f64>> = (0..TRAIN_SAMPLES)
        .map(|_| Vec::with_capacity(capacity))
        .collect();
    for candidates in candidate_sets {
        for candidate in candidates {
            for (row, &utility) in rows.iter_mut().zip(&candidate.per_example_utility) {
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
            seed,
            step,
            method: partition.name.clone(),
            sample,
            stratum,
            kmeans_iterations: partition.iterations,
            within_sse: partition.within_sse,
        });
    }
}

fn predicted_partition_error(ids: &[u8; TRAIN_SAMPLES], candidates: &[Candidate]) -> (f64, f64) {
    let mut members = [[0_usize; STRATUM_SIZE]; STRATUM_COUNT];
    let mut counts = [0_usize; STRATUM_COUNT];
    for (sample, &stratum) in ids.iter().enumerate() {
        let group = stratum as usize;
        let slot = counts[group];
        members[group][slot] = sample;
        counts[group] += 1;
    }
    assert_eq!(counts, [STRATUM_SIZE; STRATUM_COUNT]);
    let mut within_variance_sum = 0.0;
    let mut estimator_variance_sum = 0.0;
    for candidate in candidates {
        let mut within = 0.0;
        let mut estimator_variance = 0.0;
        for group_members in &members {
            let mean = group_members
                .iter()
                .map(|&sample| f64::from(candidate.per_example_utility[sample]))
                .sum::<f64>()
                / STRATUM_SIZE as f64;
            let sum_squares = group_members
                .iter()
                .map(|&sample| {
                    let difference = f64::from(candidate.per_example_utility[sample]) - mean;
                    difference * difference
                })
                .sum::<f64>();
            let sample_variance = sum_squares / (STRATUM_SIZE - 1) as f64;
            within += sample_variance / STRATUM_COUNT as f64;
            estimator_variance += (1.0 / (STRATUM_COUNT * STRATUM_COUNT) as f64)
                * (1.0 - 4.0 / STRATUM_SIZE as f64)
                * sample_variance
                / 4.0;
        }
        within_variance_sum += within;
        estimator_variance_sum += estimator_variance;
    }
    let count = candidates.len() as f64;
    (
        within_variance_sum / count,
        (estimator_variance_sum / count).sqrt(),
    )
}

fn sample_panel(ids: &[u8; TRAIN_SAMPLES], seed: u64) -> [[usize; 4]; STRATUM_COUNT] {
    let mut members = [[0_usize; STRATUM_SIZE]; STRATUM_COUNT];
    let mut counts = [0_usize; STRATUM_COUNT];
    for (sample, &stratum) in ids.iter().enumerate() {
        let group = stratum as usize;
        let slot = counts[group];
        members[group][slot] = sample;
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
        let mut estimate = 0.0;
        for selected in panel {
            let group_mean = selected
                .iter()
                .map(|&sample| f64::from(candidate.per_example_utility[sample]))
                .sum::<f64>()
                / selected.len() as f64;
            estimate += group_mean / STRATUM_COUNT as f64;
        }
        let difference = estimate - candidate.exact_utility;
        squared_error += difference * difference;
        if candidate.exact_utility.abs() > SIGN_EPSILON {
            sign_trials += 1;
            sign_errors += usize::from((estimate > 0.0) != (candidate.exact_utility > 0.0));
        }
        block_exact[candidate.block] = block_exact[candidate.block].max(candidate.exact_utility);
        if estimate > block_estimated[candidate.block] {
            block_estimated[candidate.block] = estimate;
            let candidate_index = estimates.len();
            block_choice[candidate.block] = Some(candidate_index);
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
    let selected_utility = selected_index.map_or(0.0, |index| candidates[index].exact_utility);
    let selected_block_exact = selected_block.map_or(0.0, |block| block_exact[block]);
    let cross_block_regret = (exact_best - selected_block_exact).max(0.0);
    let selected_program_regret = (exact_best - selected_utility).max(0.0);
    PanelMetrics {
        utility_rmse: (squared_error / candidates.len() as f64).sqrt(),
        sign_error_rate: sign_errors as f64 / sign_trials.max(1) as f64,
        cross_block_regret,
        selected_program_regret,
        false_authorization: selected_index
            .is_some_and(|index| candidates[index].exact_utility <= 0.0),
    }
}

fn audit_taylor(
    state: &StateSnapshot,
    gradients: &[[f32; adaptive_runtime_ar_02a_r2::PARAMS]],
) -> TaylorRecord {
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
            let utility = f64::from(candidate.per_example_utility[sample]);
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

fn aggregate_by_seed(rows: &[StateMetric]) -> Vec<MetricMean> {
    let mut grouped: BTreeMap<(String, u64), Vec<&StateMetric>> = BTreeMap::new();
    for row in rows {
        let method = if row.method.starts_with("hash_placebo_") {
            "hash_placebo_mean".to_owned()
        } else {
            row.method.clone()
        };
        grouped.entry((method, row.seed)).or_default().push(row);
    }
    grouped
        .into_iter()
        .map(|((method, seed), values)| mean_metrics(method, seed, values))
        .collect()
}

fn aggregate_seeds(rows: &[MetricMean]) -> Vec<MetricMean> {
    let mut grouped: BTreeMap<String, Vec<&MetricMean>> = BTreeMap::new();
    for row in rows {
        grouped.entry(row.method.clone()).or_default().push(row);
    }
    grouped
        .into_iter()
        .map(|(method, values)| {
            let mut result = mean_seed_metrics(method, &values);
            result.seed = 0;
            result
        })
        .collect()
}

fn mean_metrics(method: String, seed: u64, rows: Vec<&StateMetric>) -> MetricMean {
    let count = rows.len().max(1) as f64;
    let n_states = if method == "hash_placebo_mean" {
        rows.len() / 8
    } else {
        rows.len()
    };
    MetricMean {
        method,
        seed,
        n_states,
        within_stratum_variance: rows
            .iter()
            .map(|row| row.within_stratum_variance)
            .sum::<f64>()
            / count,
        predicted_rmse: rows.iter().map(|row| row.predicted_rmse).sum::<f64>() / count,
        observed_rmse: rows.iter().map(|row| row.observed_rmse).sum::<f64>() / count,
        sign_error_rate: rows.iter().map(|row| row.sign_error_rate).sum::<f64>() / count,
        cross_block_regret: rows.iter().map(|row| row.cross_block_regret).sum::<f64>() / count,
        selected_program_regret: rows
            .iter()
            .map(|row| row.selected_program_regret)
            .sum::<f64>()
            / count,
        false_authorization_rate: rows
            .iter()
            .map(|row| row.false_authorization_rate)
            .sum::<f64>()
            / count,
    }
}

fn mean_seed_metrics(method: String, rows: &[&MetricMean]) -> MetricMean {
    let count = rows.len().max(1) as f64;
    MetricMean {
        method,
        seed: 0,
        n_states: rows.iter().map(|row| row.n_states).sum(),
        within_stratum_variance: rows
            .iter()
            .map(|row| row.within_stratum_variance)
            .sum::<f64>()
            / count,
        predicted_rmse: rows.iter().map(|row| row.predicted_rmse).sum::<f64>() / count,
        observed_rmse: rows.iter().map(|row| row.observed_rmse).sum::<f64>() / count,
        sign_error_rate: rows.iter().map(|row| row.sign_error_rate).sum::<f64>() / count,
        cross_block_regret: rows.iter().map(|row| row.cross_block_regret).sum::<f64>() / count,
        selected_program_regret: rows
            .iter()
            .map(|row| row.selected_program_regret)
            .sum::<f64>()
            / count,
        false_authorization_rate: rows
            .iter()
            .map(|row| row.false_authorization_rate)
            .sum::<f64>()
            / count,
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
