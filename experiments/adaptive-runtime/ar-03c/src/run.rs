use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::hint::black_box;
use std::path::Path;
use std::time::Instant;

use crate::cost;
use crate::features::{self, Projection, Proxy};
use crate::integrity::R2Receipt;
use crate::metrics::{self, PanelMean};
use crate::model::{MappedDataset, TRAIN_SAMPLES};
use crate::output;
use crate::partition::{self, STRATUM_SIZE};
use crate::partition_methods::{self, Partition};
use crate::protocol::{self, StateSnapshot, StreamRole};
use crate::records::{
    CostFrontierRecord, METHODS, PanelRecord, PartitionCostRecord, QualityRecord,
    VerifierCostRecord,
};

const R2_CHECKPOINTS: [usize; 3] = [600, 2_400, 4_200];
const ANCHORS: [usize; 2] = [600, 2_400];
const REUSE_AGES: [usize; 5] = [1, 10, 25, 50, 100];
const B_CAPTURE_STEPS: [usize; 9] = [600, 625, 650, 700, 2_400, 2_425, 2_450, 2_500, 4_200];
const EXPECTED_C_CAPTURES: usize = 13;
const TIMING_REPETITIONS: usize = 3;
const SOURCE_REVISION: &str = match option_env!("AR03C_SOURCE_COMMIT") {
    Some(revision) => revision,
    None => "UNRECORDED",
};

#[derive(Clone, Debug)]
struct ExpectedSnapshot {
    fingerprint: String,
    train_loss: f32,
    candidate_count: usize,
}

#[derive(Clone, Debug)]
struct Analyzed {
    mean: PanelMean,
    within_variance: f64,
    predicted_rmse: f64,
    panel_values: Vec<[f64; 5]>,
}

pub fn run(r2_root: &Path, b_root: &Path, output_dir: &Path) -> Result<(), String> {
    if SOURCE_REVISION == "UNRECORDED" {
        return Err("AR03C_SOURCE_COMMIT must be set to the frozen source revision".to_owned());
    }
    if output_dir.exists() {
        return Err(format!(
            "refusing to overwrite existing output directory {}",
            output_dir.display()
        ));
    }
    let receipt = R2Receipt::load(r2_root)?;
    let b_snapshots = load_b_snapshots(&b_root.join("snapshot-index.csv"))?;
    let datasets = open_datasets(r2_root)?;
    let projection = Projection::frozen();
    let hash_partition_ns = cost::measure_hash_partition_ns();

    let mut quality_rows = Vec::new();
    let mut panel_rows = Vec::new();
    let mut partition_cost_rows = Vec::new();
    let mut verifier_cost_rows = Vec::new();
    let mut integrity_rows = Vec::new();
    let mut replayed_states = 0_usize;
    let mut r2_checkpoints = 0_usize;
    let mut b_snapshots_matched = 0_usize;
    let mut unique_eval_seeds = BTreeMap::new();

    for (dataset_index, dataset) in datasets.iter().enumerate() {
        let dataset_seed = protocol::DATASET_SEEDS[dataset_index];
        let train = dataset.samples();
        for (initialization_index, &initialization_seed) in
            protocol::INITIALIZATION_SEEDS.iter().enumerate()
        {
            let cell = dataset_index * protocol::INITIALIZATION_SEEDS.len() + initialization_index;
            let stream_start = cell * protocol::STREAMS_PER_ROLE_PER_CELL;
            let stream_end = stream_start + protocol::STREAMS_PER_ROLE_PER_CELL;
            for &stream_seed in &protocol::EVALUATION_SEEDS[stream_start..stream_end] {
                unique_eval_seeds.insert(stream_seed, (dataset_index, initialization_index));
                let snapshots = protocol::replay_seed(
                    train,
                    stream_seed,
                    StreamRole::Evaluation,
                    dataset_index as u8,
                    dataset_seed,
                    initialization_index as u8,
                    initialization_seed,
                );
                if snapshots.len() != EXPECTED_C_CAPTURES {
                    return Err(format!(
                        "capture count mismatch for stream {stream_seed:016x}: {}",
                        snapshots.len()
                    ));
                }
                let mut anchor_partitions = HashMap::<usize, HashMap<String, Partition>>::new();
                let mut previous_warm_centroids: Option<Vec<Vec<f64>>> = None;
                let mut previous_quota_centroids: Option<Vec<Vec<f64>>> = None;

                for state in &snapshots {
                    replayed_states += 1;
                    validate_state_values(state)?;
                    let r2_checkpoint = R2_CHECKPOINTS.contains(&state.step);
                    if r2_checkpoint {
                        receipt.validate_state(state)?;
                        let full_features = features::acquire(
                            Proxy::FullGradient,
                            &state.model,
                            train,
                            &projection,
                        );
                        let full_partition =
                            partition::balanced_kmeans(&full_features, partition::KMEANS_INIT_SEED);
                        receipt.validate_gradient_partition(state, &full_partition.ids)?;
                        integrity_rows.push((
                            state.dataset_index,
                            state.initialization_index,
                            state.seed,
                            state.step,
                            state.fingerprint,
                            state.evaluation_candidates.len(),
                        ));
                        r2_checkpoints += 1;
                    }
                    if B_CAPTURE_STEPS.contains(&state.step) {
                        validate_b_snapshot(&b_snapshots, state)?;
                        b_snapshots_matched += 1;
                    }
                    if state.step == 4_200 {
                        continue;
                    }
                    let Some((anchor, age)) = anchor_and_age(state.step) else {
                        return Err(format!("unexpected measurement capture at {}", state.step));
                    };

                    let feature_ns = features::measure_acquisition_ns(
                        Proxy::OutputLayer,
                        &state.model,
                        train,
                        &projection,
                        TIMING_REPETITIONS,
                    );
                    let feature_rows =
                        features::acquire(Proxy::OutputLayer, &state.model, train, &projection);
                    if feature_rows.len() != TRAIN_SAMPLES
                        || feature_rows.iter().any(|row| {
                            row.len() != 27 || row.iter().any(|value| !value.is_finite())
                        })
                    {
                        return Err(format!("invalid output-layer features at {}", state.step));
                    }
                    let feature_bytes = feature_rows
                        .iter()
                        .map(|row| row.len() * std::mem::size_of::<f64>())
                        .sum();

                    let exact = measured_partition(|| partition_methods::exact(&feature_rows));
                    let warm = match &previous_warm_centroids {
                        Some(centers) => measured_partition(|| {
                            partition_methods::warm_start(&feature_rows, centers)
                        }),
                        None => measured_partition(|| partition_methods::exact(&feature_rows)),
                    };
                    let projected =
                        measured_partition(|| partition_methods::projected_order(&feature_rows));
                    let quota = match &previous_quota_centroids {
                        Some(centers) => measured_partition(|| {
                            partition_methods::nearest_centroid_quota_repair(&feature_rows, centers)
                        }),
                        None => measured_partition(|| partition_methods::exact(&feature_rows)),
                    };
                    let fresh = [
                        ("balanced_kmeans", exact.0.clone(), exact.1),
                        ("warm_start_balanced_kmeans", warm.0.clone(), warm.1),
                        ("projected_order_1d", projected.0.clone(), projected.1),
                        ("nearest_centroid_quota_repair", quota.0.clone(), quota.1),
                    ];
                    previous_warm_centroids = Some(warm.0.centroids.clone());
                    previous_quota_centroids = Some(quota.0.centroids.clone());

                    for (method, partition, partition_ns) in &fresh {
                        if partition::stratum_counts(&partition.ids) != [STRATUM_SIZE; 12]
                            || !partition.within_sse.is_finite()
                        {
                            return Err(format!("invalid {method} partition at {}", state.step));
                        }
                        partition_cost_rows.push(PartitionCostRecord {
                            dataset: state.dataset_index,
                            initialization: state.initialization_index,
                            stream_seed,
                            state_step: state.step,
                            anchor_step: anchor,
                            age,
                            method: (*method).to_owned(),
                            feature_dimensions: 27,
                            feature_bytes,
                            feature_ns,
                            partition_ns: *partition_ns,
                            iterations: partition.iterations,
                            within_sse: partition.within_sse,
                        });
                    }

                    let placebo_ids = partition_methods::hash_placebo_mean_ids();
                    partition_cost_rows.push(PartitionCostRecord {
                        dataset: state.dataset_index,
                        initialization: state.initialization_index,
                        stream_seed,
                        state_step: state.step,
                        anchor_step: anchor,
                        age,
                        method: "hash_placebo_mean".to_owned(),
                        feature_dimensions: 0,
                        feature_bytes: 0,
                        feature_ns: 0,
                        partition_ns: hash_partition_ns,
                        iterations: 0,
                        within_sse: 0.0,
                    });

                    let verifier = cost::measure_verifier_cost(
                        &state.model,
                        train,
                        &state.evaluation_candidates,
                        4,
                        stream_seed,
                        state.step,
                    );
                    verifier_cost_rows.push(VerifierCostRecord {
                        dataset: state.dataset_index,
                        initialization: state.initialization_index,
                        stream_seed,
                        state_step: state.step,
                        elapsed_ns: verifier.median_ns,
                        candidate_count: verifier.candidate_count,
                        sample_evaluations: verifier.candidate_sample_evaluations,
                    });

                    if age == 0 {
                        let mut cache = HashMap::new();
                        for (method, part, _) in &fresh {
                            cache.insert((*method).to_owned(), part.clone());
                        }
                        cache.insert(
                            "hash_placebo_mean".to_owned(),
                            Partition {
                                ids: placebo_ids[0],
                                centroids: Vec::new(),
                                iterations: 0,
                                within_sse: 0.0,
                            },
                        );
                        anchor_partitions.insert(anchor, cache);
                    }
                    let stale = anchor_partitions.get(&anchor).ok_or_else(|| {
                        format!("missing anchor partition {anchor} at state {}", state.step)
                    })?;
                    let context = QualityContext {
                        dataset: state.dataset_index,
                        initialization: state.initialization_index,
                        stream_seed,
                        state_step: state.step,
                        anchor_step: anchor,
                        age,
                        candidate_count: state.evaluation_candidates.len(),
                    };

                    for (method, part, _) in &fresh {
                        let analyzed = analyze(
                            &part.ids,
                            state,
                            method,
                            "fresh",
                            &context,
                            &mut quality_rows,
                            &mut panel_rows,
                        );
                        black_box(analyzed);
                        let stale_part = stale.get(*method).ok_or_else(|| {
                            format!("missing stale method {method} at {}", state.step)
                        })?;
                        analyze(
                            &stale_part.ids,
                            state,
                            method,
                            "stale_reuse",
                            &context,
                            &mut quality_rows,
                            &mut panel_rows,
                        );
                    }
                    analyze_placebo_mean(
                        &placebo_ids,
                        state,
                        &context,
                        &mut quality_rows,
                        &mut panel_rows,
                    );
                    if state.evaluation_candidates.is_empty() {
                        return Err("empty held-out candidate set".to_owned());
                    }
                }
            }
        }
    }

    if replayed_states != 18 * EXPECTED_C_CAPTURES
        || r2_checkpoints != 54
        || b_snapshots_matched != 162
        || unique_eval_seeds.len() != 18
    {
        return Err(format!(
            "integrity count mismatch: states={replayed_states}, R2={r2_checkpoints}, B={b_snapshots_matched}, seeds={}",
            unique_eval_seeds.len()
        ));
    }
    if quality_rows.len() != 18 * 12 * 17
        || panel_rows.len() != quality_rows.len() * metrics::PANEL_REPLICATES
        || verifier_cost_rows.len() != 18 * 12
    {
        return Err(format!(
            "measurement coverage mismatch: {} quality records, {} verifier timing records",
            quality_rows.len(),
            verifier_cost_rows.len()
        ));
    }

    let frontier_rows =
        build_cost_frontier(&quality_rows, &partition_cost_rows, &verifier_cost_rows)?;
    if frontier_rows.len() != 18 * 2 * REUSE_AGES.len() * METHODS.len() {
        return Err(format!(
            "cost frontier row count mismatch: {}",
            frontier_rows.len()
        ));
    }
    let integrity_json = make_integrity_json(
        &receipt,
        replayed_states,
        r2_checkpoints,
        b_snapshots_matched,
        quality_rows.len(),
        panel_rows.len(),
    );
    let report_json = make_report_json(
        replayed_states,
        r2_checkpoints,
        b_snapshots_matched,
        &quality_rows,
        &partition_cost_rows,
        &verifier_cost_rows,
        &frontier_rows,
    );
    output::write_all(output::OutputData {
        root: output_dir,
        quality: &quality_rows,
        panels: &panel_rows,
        costs: &partition_cost_rows,
        verifier_costs: &verifier_cost_rows,
        frontier: &frontier_rows,
        integrity_json: &integrity_json,
        report_json: &report_json,
    })
    .map_err(|error| error.to_string())
}

#[derive(Clone, Copy)]
struct QualityContext {
    dataset: u8,
    initialization: u8,
    stream_seed: u64,
    state_step: usize,
    anchor_step: usize,
    age: usize,
    candidate_count: usize,
}

fn analyze(
    ids: &[u8; TRAIN_SAMPLES],
    state: &StateSnapshot,
    method: &str,
    mode: &str,
    context: &QualityContext,
    quality_rows: &mut Vec<QualityRecord>,
    panel_rows: &mut Vec<PanelRecord>,
) -> Analyzed {
    let curve = metrics::predicted_error_curve(ids, &state.evaluation_candidates);
    let point = curve
        .iter()
        .find(|row| row.examples == 48)
        .expect("V48 entry exists in the frozen evidence curve");
    let (mean, panels) =
        metrics::audit_v48(ids, &state.evaluation_candidates, state.seed, state.step);
    quality_rows.push(QualityRecord {
        dataset: context.dataset,
        initialization: context.initialization,
        stream_seed: context.stream_seed,
        state_step: context.state_step,
        anchor_step: context.anchor_step,
        age: context.age,
        method: method.to_owned(),
        mode: mode.to_owned(),
        candidate_count: context.candidate_count,
        within_variance_v48: point.within_stratum_variance,
        predicted_rmse_v48: point.predicted_rmse,
        observed_rmse_v48: mean.observed_rmse,
        sign_error_v48: mean.sign_error_rate,
        cross_block_regret_v48: mean.cross_block_regret,
        selected_regret_v48: mean.selected_program_regret,
        false_authorization_v48: mean.false_authorization_rate,
    });
    let panel_values = panels
        .into_iter()
        .map(|row| {
            panel_rows.push(PanelRecord {
                dataset: context.dataset,
                initialization: context.initialization,
                stream_seed: context.stream_seed,
                state_step: context.state_step,
                anchor_step: context.anchor_step,
                age: context.age,
                method: method.to_owned(),
                mode: mode.to_owned(),
                panel: row.panel,
                utility_rmse: row.metric.utility_rmse,
                sign_error: row.metric.sign_error_rate,
                cross_block_regret: row.metric.cross_block_regret,
                selected_regret: row.metric.selected_program_regret,
                false_authorization: bool_value(row.metric.false_authorization),
            });
            [
                row.metric.utility_rmse,
                row.metric.sign_error_rate,
                row.metric.cross_block_regret,
                row.metric.selected_program_regret,
                bool_value(row.metric.false_authorization),
            ]
        })
        .collect();
    Analyzed {
        mean,
        within_variance: point.within_stratum_variance,
        predicted_rmse: point.predicted_rmse,
        panel_values,
    }
}

fn analyze_placebo_mean(
    placebo_ids: &[[u8; TRAIN_SAMPLES]],
    state: &StateSnapshot,
    context: &QualityContext,
    quality_rows: &mut Vec<QualityRecord>,
    panel_rows: &mut Vec<PanelRecord>,
) {
    let mut runs = Vec::with_capacity(placebo_ids.len());
    for (index, ids) in placebo_ids.iter().enumerate() {
        runs.push(analyze(
            ids,
            state,
            &format!("hash_placebo_{index:02}"),
            "placebo_component",
            context,
            quality_rows,
            panel_rows,
        ));
    }
    let count = runs.len() as f64;
    let mean = PanelMean {
        observed_rmse: runs.iter().map(|run| run.mean.observed_rmse).sum::<f64>() / count,
        sign_error_rate: runs.iter().map(|run| run.mean.sign_error_rate).sum::<f64>() / count,
        cross_block_regret: runs
            .iter()
            .map(|run| run.mean.cross_block_regret)
            .sum::<f64>()
            / count,
        selected_program_regret: runs
            .iter()
            .map(|run| run.mean.selected_program_regret)
            .sum::<f64>()
            / count,
        false_authorization_rate: runs
            .iter()
            .map(|run| run.mean.false_authorization_rate)
            .sum::<f64>()
            / count,
    };
    let within_variance = runs.iter().map(|run| run.within_variance).sum::<f64>() / count;
    let predicted_rmse = runs.iter().map(|run| run.predicted_rmse).sum::<f64>() / count;
    quality_rows.push(QualityRecord {
        dataset: context.dataset,
        initialization: context.initialization,
        stream_seed: context.stream_seed,
        state_step: context.state_step,
        anchor_step: context.anchor_step,
        age: context.age,
        method: "hash_placebo_mean".to_owned(),
        mode: "fixed_placebos".to_owned(),
        candidate_count: context.candidate_count,
        within_variance_v48: within_variance,
        predicted_rmse_v48: predicted_rmse,
        observed_rmse_v48: mean.observed_rmse,
        sign_error_v48: mean.sign_error_rate,
        cross_block_regret_v48: mean.cross_block_regret,
        selected_regret_v48: mean.selected_program_regret,
        false_authorization_v48: mean.false_authorization_rate,
    });
    for panel in 0..metrics::PANEL_REPLICATES {
        let values: [f64; 5] = std::array::from_fn(|metric| {
            runs.iter()
                .map(|run| run.panel_values[panel][metric])
                .sum::<f64>()
                / count
        });
        panel_rows.push(PanelRecord {
            dataset: context.dataset,
            initialization: context.initialization,
            stream_seed: context.stream_seed,
            state_step: context.state_step,
            anchor_step: context.anchor_step,
            age: context.age,
            method: "hash_placebo_mean".to_owned(),
            mode: "fixed_placebos".to_owned(),
            panel,
            utility_rmse: values[0],
            sign_error: values[1],
            cross_block_regret: values[2],
            selected_regret: values[3],
            false_authorization: values[4],
        });
    }
}

fn measured_partition<F>(mut build: F) -> (Partition, u128)
where
    F: FnMut() -> Partition,
{
    let partition = build();
    let mut durations = Vec::with_capacity(TIMING_REPETITIONS);
    for _ in 0..TIMING_REPETITIONS {
        let started = Instant::now();
        let result = build();
        black_box(result.ids);
        durations.push(started.elapsed().as_nanos());
    }
    durations.sort_unstable();
    (partition, durations[durations.len() / 2])
}

fn bool_value(value: bool) -> f64 {
    if value { 1.0 } else { 0.0 }
}

fn build_cost_frontier(
    quality: &[QualityRecord],
    partition_costs: &[PartitionCostRecord],
    verifier_costs: &[VerifierCostRecord],
) -> Result<Vec<CostFrontierRecord>, String> {
    let mut output = Vec::with_capacity(18 * 2 * REUSE_AGES.len() * METHODS.len());
    for quality_row in quality
        .iter()
        .filter(|row| row.mode == "stale_reuse" || row.mode == "fixed_placebos")
    {
        if !REUSE_AGES.contains(&quality_row.age) {
            continue;
        }
        let build = partition_costs
            .iter()
            .find(|row| {
                row.dataset == quality_row.dataset
                    && row.initialization == quality_row.initialization
                    && row.stream_seed == quality_row.stream_seed
                    && row.state_step == quality_row.anchor_step
                    && row.method == quality_row.method
            })
            .ok_or_else(|| format!("missing anchor cost for {}", quality_row.method))?;
        let verifier = verifier_costs
            .iter()
            .find(|row| {
                row.dataset == quality_row.dataset
                    && row.initialization == quality_row.initialization
                    && row.stream_seed == quality_row.stream_seed
                    && row.state_step == quality_row.state_step
            })
            .ok_or_else(|| format!("missing V48 timing at {}", quality_row.state_step))?;
        let (refresh_feature_ns, refresh_partition_ns) =
            if quality_row.method == "hash_placebo_mean" {
                if quality_row.anchor_step == ANCHORS[0] {
                    (0, build.partition_ns)
                } else {
                    (0, 0)
                }
            } else {
                (build.feature_ns, build.partition_ns)
            };
        let amortized_proxy_ns =
            (refresh_feature_ns + refresh_partition_ns) as f64 / quality_row.age as f64;
        output.push(CostFrontierRecord {
            dataset: quality_row.dataset,
            initialization: quality_row.initialization,
            stream_seed: quality_row.stream_seed,
            anchor_step: quality_row.anchor_step,
            reuse_commits: quality_row.age,
            quality_readout_step: quality_row.state_step,
            method: quality_row.method.clone(),
            build_feature_ns: refresh_feature_ns,
            build_partition_ns: refresh_partition_ns,
            amortized_proxy_ns,
            verifier_ns: verifier.elapsed_ns,
            projected_total_ns: amortized_proxy_ns + verifier.elapsed_ns as f64,
            within_variance_v48: quality_row.within_variance_v48,
            predicted_rmse_v48: quality_row.predicted_rmse_v48,
            observed_rmse_v48: quality_row.observed_rmse_v48,
            sign_error_v48: quality_row.sign_error_v48,
            cross_block_regret_v48: quality_row.cross_block_regret_v48,
            selected_regret_v48: quality_row.selected_regret_v48,
            false_authorization_v48: quality_row.false_authorization_v48,
        });
    }
    Ok(output)
}

fn anchor_and_age(step: usize) -> Option<(usize, usize)> {
    for anchor in ANCHORS {
        let age = step.checked_sub(anchor)?;
        if age == 0 || REUSE_AGES.contains(&age) {
            return Some((anchor, age));
        }
    }
    None
}

fn validate_state_values(state: &StateSnapshot) -> Result<(), String> {
    if state.role != StreamRole::Evaluation || state.evaluation_candidates.is_empty() {
        return Err("unexpected evaluation replay state".to_owned());
    }
    if !state.train_loss.is_finite()
        || state.evaluation_candidates.iter().any(|candidate| {
            !candidate.exact_utility[0].is_finite()
                || candidate.per_example_utility[0].len() != TRAIN_SAMPLES
                || candidate.per_example_utility[0]
                    .iter()
                    .any(|utility| !utility.is_finite())
        })
    {
        return Err(format!(
            "non-finite state/candidate response at {}",
            state.step
        ));
    }
    Ok(())
}

fn load_b_snapshots(path: &Path) -> Result<HashMap<String, ExpectedSnapshot>, String> {
    let text = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut rows = HashMap::new();
    for line in text.lines().skip(1) {
        let fields = line.split(',').collect::<Vec<_>>();
        if fields.len() != 8 {
            return Err("malformed AR-03B snapshot-index row".to_owned());
        }
        let dataset = parse_usize(fields[0])? as u8;
        let initialization = parse_usize(fields[1])? as u8;
        let seed = u64::from_str_radix(fields[2], 16).map_err(|error| error.to_string())?;
        let step = parse_usize(fields[3])?;
        let key = state_key(dataset, initialization, seed, step);
        let value = ExpectedSnapshot {
            fingerprint: fields[4].to_owned(),
            train_loss: fields[5]
                .parse()
                .map_err(|error: std::num::ParseFloatError| error.to_string())?,
            candidate_count: parse_usize(fields[6])?,
        };
        if rows.insert(key, value).is_some() {
            return Err("duplicate AR-03B snapshot-index key".to_owned());
        }
    }
    if rows.len() != 162 {
        return Err(format!(
            "expected 162 AR-03B snapshot rows, got {}",
            rows.len()
        ));
    }
    Ok(rows)
}

fn validate_b_snapshot(
    expected: &HashMap<String, ExpectedSnapshot>,
    state: &StateSnapshot,
) -> Result<(), String> {
    let key = state_key(
        state.dataset_index,
        state.initialization_index,
        state.seed,
        state.step,
    );
    let row = expected
        .get(&key)
        .ok_or_else(|| format!("missing AR-03B replay state {key}"))?;
    if row.fingerprint != format!("{:016x}", state.fingerprint)
        || row.candidate_count != state.evaluation_candidates.len()
        || (row.train_loss - state.train_loss).abs() > 2.0e-8
    {
        return Err(format!("AR-03B replay mismatch at {key}"));
    }
    Ok(())
}

fn open_datasets(root: &Path) -> Result<Vec<MappedDataset>, String> {
    (0..protocol::DATASET_SEEDS.len())
        .map(|index| {
            MappedDataset::open(root.join(format!("dataset-d{index:02}.bin")))
                .map_err(|error| error.to_string())
        })
        .collect()
}

fn state_key(dataset: u8, initialization: u8, seed: u64, step: usize) -> String {
    format!("{dataset}:{initialization}:{seed:016x}:{step}")
}

fn parse_usize(value: &str) -> Result<usize, String> {
    value.parse::<usize>().map_err(|error| error.to_string())
}

fn make_integrity_json(
    receipt: &R2Receipt,
    replayed: usize,
    r2_checkpoints: usize,
    b_states: usize,
    quality_rows: usize,
    panel_rows: usize,
) -> String {
    format!(
        "{{\n  \"experiment\":\"AR-03C\",\n  \"source_revision\":\"{}\",\n  \"diagnostic_only\":true,\n  \"runtime_proxy_used\":false,\n  \"training_policy_changed\":false,\n  \"replayed_states\":{replayed},\n  \"r2_checkpoints_verified\":{r2_checkpoints},\n  \"ar03b_snapshots_matched\":{b_states},\n  \"quality_rows\":{quality_rows},\n  \"panel_rows\":{panel_rows},\n  \"r2_model_states_sha256\":\"{}\",\n  \"r2_dataset_sha256\":[\"{}\",\"{}\",\"{}\"],\n  \"capture_steps\":{:?},\n  \"candidate_features\":\"output_layer_gradient_27\",\n  \"limitations\":[\"same nine R2 crossed cells and 18 streams\",\"new capture ages are observational replays only\",\"timings are local CPU component measurements\",\"no end-to-end optimizer comparison\"]\n}}\n",
        SOURCE_REVISION,
        receipt.model_states_sha256,
        receipt.dataset_sha256[0],
        receipt.dataset_sha256[1],
        receipt.dataset_sha256[2],
        protocol::CAPTURE_STEPS,
    )
}

fn make_report_json(
    replayed: usize,
    r2_checkpoints: usize,
    b_states: usize,
    quality: &[QualityRecord],
    partition_cost: &[PartitionCostRecord],
    verifier_cost: &[VerifierCostRecord],
    frontier: &[CostFrontierRecord],
) -> String {
    format!(
        "{{\n  \"experiment\":\"AR-03C\",\n  \"source_revision\":\"{}\",\n  \"status\":\"diagnostic-only\",\n  \"runtime_proxy_used\":false,\n  \"training_policy_changed\":false,\n  \"end_to_end_training_comparison\":false,\n  \"replayed_states\":{replayed},\n  \"r2_checkpoints_verified\":{r2_checkpoints},\n  \"ar03b_snapshots_matched\":{b_states},\n  \"quality_rows\":{},\n  \"partition_cost_rows\":{},\n  \"verifier_cost_rows\":{},\n  \"cost_frontier_rows\":{},\n  \"partition_methods\":[\"balanced_kmeans\",\"warm_start_balanced_kmeans\",\"projected_order_1d\",\"nearest_centroid_quota_repair\",\"hash_placebo_mean\"],\n  \"reuse_ages\":[1,10,25,50,100],\n  \"limitations\":[\"quality for K is the held anchor partition at exact age K\",\"same R2 task family and trajectories\",\"nested streams and checkpoints are not independent cells\",\"component cost projections exclude system overhead\"]\n}}\n",
        SOURCE_REVISION,
        quality.len(),
        partition_cost.len(),
        verifier_cost.len(),
        frontier.len(),
    )
}

#[cfg(test)]
mod tests {
    use super::anchor_and_age;

    #[test]
    fn declared_reuse_ages_map_to_exact_capture_steps() {
        for anchor in [600, 2_400] {
            for age in [0, 1, 10, 25, 50, 100] {
                assert_eq!(anchor_and_age(anchor + age), Some((anchor, age)));
            }
        }
        assert_eq!(anchor_and_age(700 + 1), None);
        assert_eq!(anchor_and_age(2_500 + 1), None);
    }
}
