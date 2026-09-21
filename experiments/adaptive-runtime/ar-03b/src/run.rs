use std::collections::BTreeMap;
use std::io::{self, Write};
use std::path::Path;

use hashbrown::HashMap;

use crate::cost::{self, ProxyCost, VerifierCost};
use crate::features::{self, Projection, Proxy};
use crate::integrity::R2Receipt;
use crate::metrics::{self, ErrorPoint, PanelMean, PanelRow};
use crate::model::{MappedDataset, TRAIN_SAMPLES};
use crate::output::{self, OutputData};
use crate::partition::{self, STRATUM_SIZE};
use crate::protocol::{
    self, CAPTURE_STEPS, EVALUATION_SEEDS, INITIALIZATION_SEEDS, StateSnapshot, StreamRole,
};
use crate::records::{
    Context, ErrorRecord, IntegrityRecord, PanelRecord, SnapshotRecord, StateMetricRecord,
};
use crate::summary;

const R2_CHECKPOINTS: [usize; 3] = [600, 2_400, 4_200];
const ANCHOR_STEPS: [usize; 2] = [600, 2_400];

#[derive(Clone, Debug)]
struct NamedPartition {
    method: String,
    ids: [u8; TRAIN_SAMPLES],
}

#[derive(Clone, Debug)]
struct MethodResult {
    method: String,
    curve: Vec<ErrorPoint>,
    panel_mean: PanelMean,
    panel_rows: Vec<PanelRow>,
}

pub fn run(input_root: &Path, output_dir: &Path) -> Result<(), String> {
    if output_dir.exists() {
        return Err(format!(
            "refusing to overwrite run directory {}",
            output_dir.display()
        ));
    }
    let receipt = R2Receipt::load(input_root)?;
    let datasets = open_datasets(input_root)?;
    let projection = Projection::frozen();

    let mut errors = Vec::new();
    let mut state_metrics = Vec::new();
    let mut panels = Vec::new();
    let mut proxy_costs = Vec::new();
    let mut verifier_costs = Vec::new();
    let mut integrity = Vec::with_capacity(54);
    let mut snapshot_rows = Vec::with_capacity(162);
    let hash_partition_cost = cost::measure_hash_partition_ns();
    proxy_costs.push(ProxyCost {
        method: "hash_placebo_8".to_owned(),
        dataset_index: u8::MAX,
        initialization_index: u8::MAX,
        stream_seed: 0,
        step: 0,
        dimensions: 0,
        feature_payload_bytes: 0,
        acquisition_median_ns: 0,
        partition_median_ns: hash_partition_cost,
    });

    let mut anchor_cache: HashMap<(u64, usize), HashMap<String, [u8; TRAIN_SAMPLES]>> =
        HashMap::new();
    let mut replayed_snapshots = 0;
    let mut verified_checkpoints = 0;

    for (dataset_index, dataset) in datasets.iter().enumerate() {
        let dataset_seed = protocol::DATASET_SEEDS[dataset_index];
        let train = dataset.samples();
        for (initialization_index, &initialization_seed) in INITIALIZATION_SEEDS.iter().enumerate()
        {
            let cell_index = dataset_index * INITIALIZATION_SEEDS.len() + initialization_index;
            let stream_start = cell_index * protocol::STREAMS_PER_ROLE_PER_CELL;
            for &stream_seed in
                &EVALUATION_SEEDS[stream_start..stream_start + protocol::STREAMS_PER_ROLE_PER_CELL]
            {
                let snapshots = protocol::replay_seed(
                    train,
                    stream_seed,
                    StreamRole::Evaluation,
                    dataset_index as u8,
                    dataset_seed,
                    initialization_index as u8,
                    initialization_seed,
                );
                if snapshots.len() != CAPTURE_STEPS.len() {
                    return Err(format!("wrong capture count for stream {stream_seed:016x}"));
                }
                for state in &snapshots {
                    process_snapshot(
                        state,
                        train,
                        &projection,
                        &receipt,
                        &mut anchor_cache,
                        &mut errors,
                        &mut state_metrics,
                        &mut panels,
                        &mut proxy_costs,
                        &mut verifier_costs,
                        &mut integrity,
                        &mut snapshot_rows,
                        &mut verified_checkpoints,
                    )?;
                    replayed_snapshots += 1;
                }
            }
        }
    }

    if replayed_snapshots != 162 || verified_checkpoints != 54 || integrity.len() != 54 {
        return Err(format!(
            "replay integrity count mismatch: {replayed_snapshots} snapshots, {verified_checkpoints} checkpoints"
        ));
    }
    if snapshot_rows.len() != 162 {
        return Err(format!(
            "expected 162 indexed snapshots, got {}",
            snapshot_rows.len()
        ));
    }
    validate_capture_coverage(&snapshot_rows)?;

    let error_records = errors
        .iter()
        .map(|(context, method, point)| ErrorRecord {
            context: context.clone(),
            method: method.clone(),
            evidence_examples: point.examples,
            samples_per_stratum: point.examples / 12,
            within_stratum_variance: point.within_stratum_variance,
            predicted_rmse: point.predicted_rmse,
        })
        .collect::<Vec<_>>();
    let summary_v48 = summary::summarize_v48(&state_metrics);
    let frontier_summary = summary::summarize_error_curve(&error_records);

    let output_data = OutputData {
        output_dir,
        error_records: &error_records,
        state_metrics: &state_metrics,
        panel_records: &panels,
        proxy_costs: &proxy_costs,
        verifier_costs: &verifier_costs,
        integrity: &integrity,
        snapshots: &snapshot_rows,
        summary_v48: &summary_v48,
        frontier_summary: &frontier_summary,
        receipt: &receipt,
    };
    output::write_all(output_data).map_err(|error| error.to_string())?;
    let cost_projection_rows = write_cost_projection(
        output_dir,
        &proxy_costs,
        &verifier_costs,
        &frontier_summary,
        &summary_v48,
    )
    .map_err(|error| error.to_string())?;
    output::write_report(
        output_dir.join("report.json"),
        output_data,
        cost_projection_rows,
    )
    .map_err(|error| error.to_string())?;
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn process_snapshot(
    state: &StateSnapshot,
    train: &[crate::model::Sample],
    projection: &Projection,
    receipt: &R2Receipt,
    anchor_cache: &mut HashMap<(u64, usize), HashMap<String, [u8; TRAIN_SAMPLES]>>,
    errors: &mut Vec<(Context, String, ErrorPoint)>,
    state_metrics: &mut Vec<StateMetricRecord>,
    panels: &mut Vec<PanelRecord>,
    proxy_costs: &mut Vec<ProxyCost>,
    verifier_costs: &mut Vec<VerifierCost>,
    integrity: &mut Vec<IntegrityRecord>,
    snapshot_rows: &mut Vec<SnapshotRecord>,
    verified_checkpoints: &mut usize,
) -> Result<(), String> {
    if state.role != StreamRole::Evaluation || state.evaluation_candidates.is_empty() {
        return Err("unexpected evaluation replay state".to_owned());
    }
    if !state.train_loss.is_finite() {
        return Err(format!("non-finite training loss at step {}", state.step));
    }
    if state.evaluation_candidates.iter().any(|candidate| {
        !candidate.exact_utility[0].is_finite()
            || candidate.per_example_utility[0].len() != TRAIN_SAMPLES
            || candidate.per_example_utility[0]
                .iter()
                .any(|value| !value.is_finite())
    }) {
        return Err(format!(
            "non-finite candidate response at step {}",
            state.step
        ));
    }
    let r2_checkpoint = R2_CHECKPOINTS.contains(&state.step);
    snapshot_rows.push(SnapshotRecord {
        dataset_index: state.dataset_index,
        initialization_index: state.initialization_index,
        stream_seed: state.seed,
        state_step: state.step,
        parameter_fingerprint: state.fingerprint,
        train_loss: state.train_loss,
        evaluation_candidate_count: state.evaluation_candidates.len(),
        r2_checkpoint,
    });
    if r2_checkpoint {
        receipt.validate_state(state)?;
    }

    let mut partitions = Vec::with_capacity(13);
    for placebo in 0..8 {
        let ids = partition::hash_placebo(placebo);
        if partition::stratum_counts(&ids) != [STRATUM_SIZE; 12] {
            return Err(format!("unbalanced hash placebo {placebo}"));
        }
        partitions.push(NamedPartition {
            method: format!("hash_placebo_{placebo:02}"),
            ids,
        });
    }
    let dataset = train;
    for proxy in Proxy::ALL {
        let features = features::acquire(proxy, &state.model, dataset, projection);
        if features.len() != TRAIN_SAMPLES
            || features
                .iter()
                .any(|row| row.iter().any(|value| !value.is_finite()))
        {
            return Err(format!("invalid {} features", proxy.name()));
        }
        let partition = partition::balanced_kmeans(&features, partition::KMEANS_INIT_SEED);
        if partition.counts != [STRATUM_SIZE; 12] {
            return Err(format!("unbalanced {} partition", proxy.name()));
        }
        if proxy == Proxy::FullGradient && r2_checkpoint {
            receipt.validate_gradient_partition(state, &partition.ids)?;
        }
        if r2_checkpoint {
            let (acquisition_median_ns, partition_median_ns, feature_payload_bytes) =
                cost::measure_proxy_cost(proxy, &state.model, dataset, projection);
            proxy_costs.push(ProxyCost {
                method: proxy.name().to_owned(),
                dataset_index: state.dataset_index,
                initialization_index: state.initialization_index,
                stream_seed: state.seed,
                step: state.step,
                dimensions: proxy.dimensions(),
                feature_payload_bytes,
                acquisition_median_ns,
                partition_median_ns,
            });
        }
        partitions.push(NamedPartition {
            method: proxy.name().to_owned(),
            ids: partition.ids,
        });
    }

    if r2_checkpoint {
        *verified_checkpoints += 1;
        integrity.push(IntegrityRecord {
            dataset_index: state.dataset_index,
            initialization_index: state.initialization_index,
            stream_seed: state.seed,
            state_step: state.step,
            fingerprint: state.fingerprint,
            evaluation_candidate_count: state.evaluation_candidates.len(),
            r2_checkpoint: true,
            r2_state_match: true,
            r2_candidate_count_match: true,
            r2_utility_match: true,
            r2_gradient_partition_match: true,
        });
        for per_stratum in metrics::EVIDENCE_N_PER_STRATUM {
            let mut row = cost::measure_verifier_cost(
                &state.model,
                dataset,
                &state.evaluation_candidates,
                per_stratum,
                state.seed,
                state.step,
            );
            row.dataset_index = state.dataset_index;
            row.initialization_index = state.initialization_index;
            verifier_costs.push(row);
        }
    }

    let fresh_results = method_results(&partitions, state);
    if r2_checkpoint {
        let context = Context {
            dataset_index: state.dataset_index,
            initialization_index: state.initialization_index,
            stream_seed: state.seed,
            state_step: state.step,
            phase: "frontier_fresh".to_owned(),
            anchor_step: None,
            offset_from_anchor: None,
            partition_age: 0,
            candidate_count: state.evaluation_candidates.len(),
        };
        record_results(&context, &fresh_results, errors, state_metrics, panels);
    }

    if ANCHOR_STEPS.contains(&state.step) {
        let cache: HashMap<_, _> = partitions
            .iter()
            .map(|partition| (partition.method.clone(), partition.ids))
            .collect();
        anchor_cache.insert((state.seed, state.step), cache);
        let fresh_context = freshness_context(state, state.step, 0, "freshness_fresh");
        let stale_context = freshness_context(state, state.step, 0, "freshness_stale");
        record_results(
            &fresh_context,
            &fresh_results,
            errors,
            state_metrics,
            panels,
        );
        record_results(
            &stale_context,
            &fresh_results,
            errors,
            state_metrics,
            panels,
        );
    } else if let Some((anchor, age)) = anchor_and_age(state.step) {
        let stale_partitions = anchor_cache
            .get(&(state.seed, anchor))
            .ok_or_else(|| format!("missing partition anchor {anchor} for {:016x}", state.seed))?;
        let stale_named: Vec<_> = stale_partitions
            .iter()
            .map(|(method, ids)| NamedPartition {
                method: method.clone(),
                ids: *ids,
            })
            .collect();
        let stale_results = method_results(&stale_named, state);
        let fresh_context = freshness_context(state, anchor, age, "freshness_fresh");
        let stale_context = freshness_context(state, anchor, age, "freshness_stale");
        record_results(
            &fresh_context,
            &fresh_results,
            errors,
            state_metrics,
            panels,
        );
        record_results(
            &stale_context,
            &stale_results,
            errors,
            state_metrics,
            panels,
        );
    }
    Ok(())
}

fn method_results(partitions: &[NamedPartition], state: &StateSnapshot) -> Vec<MethodResult> {
    partitions
        .iter()
        .map(|partition| {
            let curve =
                metrics::predicted_error_curve(&partition.ids, &state.evaluation_candidates);
            let (panel_mean, panel_rows) = metrics::audit_v48(
                &partition.ids,
                &state.evaluation_candidates,
                state.seed,
                state.step,
            );
            MethodResult {
                method: partition.method.clone(),
                curve,
                panel_mean,
                panel_rows,
            }
        })
        .collect()
}

fn record_results(
    context: &Context,
    results: &[MethodResult],
    errors: &mut Vec<(Context, String, ErrorPoint)>,
    state_metrics: &mut Vec<StateMetricRecord>,
    panels: &mut Vec<PanelRecord>,
) {
    for result in results {
        record_one_result(context, result, errors, state_metrics, panels);
    }
    let placebo_results: Vec<_> = results
        .iter()
        .filter(|result| result.method.starts_with("hash_placebo_"))
        .collect();
    if placebo_results.len() == 8 {
        let mean = average_placebos(&placebo_results);
        record_one_result(context, &mean, errors, state_metrics, panels);
    }
}

fn record_one_result(
    context: &Context,
    result: &MethodResult,
    errors: &mut Vec<(Context, String, ErrorPoint)>,
    state_metrics: &mut Vec<StateMetricRecord>,
    panels: &mut Vec<PanelRecord>,
) {
    for &point in &result.curve {
        errors.push((context.clone(), result.method.clone(), point));
    }
    let point_v48 = result
        .curve
        .iter()
        .find(|point| point.examples == 48)
        .expect("48-example point in frozen evidence frontier");
    state_metrics.push(StateMetricRecord {
        context: context.clone(),
        method: result.method.clone(),
        within_stratum_variance: point_v48.within_stratum_variance,
        predicted_rmse_v48: point_v48.predicted_rmse,
        observed_rmse_v48: result.panel_mean.observed_rmse,
        sign_error_rate_v48: result.panel_mean.sign_error_rate,
        cross_block_regret_v48: result.panel_mean.cross_block_regret,
        selected_program_regret_v48: result.panel_mean.selected_program_regret,
        false_authorization_rate_v48: result.panel_mean.false_authorization_rate,
    });
    panels.extend(result.panel_rows.iter().map(|row| PanelRecord {
        context: context.clone(),
        method: result.method.clone(),
        panel: row.panel,
        utility_rmse_v48: row.metric.utility_rmse,
        sign_error_rate_v48: row.metric.sign_error_rate,
        cross_block_regret_v48: row.metric.cross_block_regret,
        selected_program_regret_v48: row.metric.selected_program_regret,
        false_authorization_v48: row.metric.false_authorization,
    }));
}

fn average_placebos(placebos: &[&MethodResult]) -> MethodResult {
    let first = placebos[0];
    let curve = (0..first.curve.len())
        .map(|index| {
            let mut point = first.curve[index];
            point.within_stratum_variance = placebos
                .iter()
                .map(|result| result.curve[index].within_stratum_variance)
                .sum::<f64>()
                / placebos.len() as f64;
            point.predicted_rmse = placebos
                .iter()
                .map(|result| result.curve[index].predicted_rmse)
                .sum::<f64>()
                / placebos.len() as f64;
            point
        })
        .collect();
    let average = |select: fn(PanelMean) -> f64| {
        placebos
            .iter()
            .map(|result| select(result.panel_mean))
            .sum::<f64>()
            / placebos.len() as f64
    };
    MethodResult {
        method: "hash_placebo_mean".to_owned(),
        curve,
        panel_mean: PanelMean {
            observed_rmse: average(|row| row.observed_rmse),
            sign_error_rate: average(|row| row.sign_error_rate),
            cross_block_regret: average(|row| row.cross_block_regret),
            selected_program_regret: average(|row| row.selected_program_regret),
            false_authorization_rate: average(|row| row.false_authorization_rate),
        },
        panel_rows: Vec::new(),
    }
}

fn freshness_context(
    state: &StateSnapshot,
    anchor_step: usize,
    age: usize,
    phase: &str,
) -> Context {
    Context {
        dataset_index: state.dataset_index,
        initialization_index: state.initialization_index,
        stream_seed: state.seed,
        state_step: state.step,
        phase: phase.to_owned(),
        anchor_step: Some(anchor_step),
        offset_from_anchor: Some(age),
        partition_age: if phase == "freshness_fresh" { 0 } else { age },
        candidate_count: state.evaluation_candidates.len(),
    }
}

fn anchor_and_age(step: usize) -> Option<(usize, usize)> {
    for anchor in ANCHOR_STEPS {
        let age = step.checked_sub(anchor)?;
        if [25, 50, 100].contains(&age) {
            return Some((anchor, age));
        }
    }
    None
}

fn open_datasets(input_root: &Path) -> Result<Vec<MappedDataset>, String> {
    (0..protocol::DATASET_SEEDS.len())
        .map(|index| {
            MappedDataset::open(input_root.join(format!("dataset-d{index:02}.bin")))
                .map_err(|error| error.to_string())
        })
        .collect()
}

fn validate_capture_coverage(rows: &[SnapshotRecord]) -> Result<(), String> {
    let mut counts = BTreeMap::new();
    for row in rows {
        *counts
            .entry((row.dataset_index, row.initialization_index, row.state_step))
            .or_insert(0_usize) += 1;
    }
    if counts.len() != 9 * CAPTURE_STEPS.len() || counts.values().any(|&count| count != 2) {
        return Err("capture coverage is not 9 crossed cells × 2 streams × 9 steps".to_owned());
    }
    if CAPTURE_STEPS
        .iter()
        .any(|step| !counts.keys().any(|key| key.2 == *step))
    {
        return Err("one or more frozen capture steps are absent".to_owned());
    }
    Ok(())
}

fn write_cost_projection(
    output_dir: &Path,
    proxy_costs: &[ProxyCost],
    verifier_costs: &[VerifierCost],
    frontier: &[crate::records::SummaryRecord],
    v48_summary: &[crate::records::SummaryRecord],
) -> io::Result<usize> {
    let mut refresh_cost = HashMap::<(String, usize), (u128, usize)>::new();
    for row in proxy_costs {
        if row.dataset_index == u8::MAX {
            refresh_cost.insert(
                ("hash_placebo_mean".to_owned(), 0),
                (row.partition_median_ns, 1),
            );
            continue;
        }
        let entry = refresh_cost
            .entry((row.method.clone(), row.step))
            .or_insert((0, 0));
        entry.0 += row.acquisition_median_ns + row.partition_median_ns;
        entry.1 += 1;
    }
    let refresh_cost: HashMap<_, _> = refresh_cost
        .into_iter()
        .map(|(key, (sum, count))| (key, sum as f64 / count.max(1) as f64))
        .collect();
    let mut verifier_cost = HashMap::<(usize, usize), (u128, usize)>::new();
    for row in verifier_costs {
        let entry = verifier_cost
            .entry((row.step, row.verifier_examples))
            .or_default();
        entry.0 += row.median_ns;
        entry.1 += 1;
    }
    let verifier_cost: HashMap<_, _> = verifier_cost
        .into_iter()
        .map(|(key, (sum, count))| (key, sum as f64 / count.max(1) as f64))
        .collect();
    let mut out = std::io::BufWriter::new(std::fs::File::create(
        output_dir.join("cost-projection.csv"),
    )?);
    writeln!(
        out,
        "method,anchor_step,reuse_commits,quality_readout_step,partition_age_at_quality_readout,verifier_examples,refresh_feature_plus_partition_ns,amortized_proxy_ns_per_commit,verifier_elapsed_ns_per_commit,projected_total_ns_per_commit,predicted_rmse_at_readout,observed_rmse_v48_at_readout,sign_error_rate_v48_at_readout,selected_program_regret_v48_at_readout,false_authorization_rate_v48_at_readout,readout_phase"
    )?;
    let mut rows_written = 0;
    for method in [
        "hash_placebo_mean",
        "full_gradient_171",
        "output_layer_27",
        "last_hidden_layer_72",
        "rademacher_projection_32",
        "sign_gradient_171",
    ] {
        for anchor in ANCHOR_STEPS {
            let refresh_step = if method == "hash_placebo_mean" {
                0
            } else {
                anchor
            };
            let Some(&refresh) = refresh_cost.get(&(method.to_owned(), refresh_step)) else {
                continue;
            };
            for reuse in [1_usize, 25, 50, 100] {
                let (phase, age) = if reuse == 1 {
                    ("freshness_fresh", 0)
                } else {
                    ("freshness_stale", reuse)
                };
                for examples in [12_usize, 24, 36, 48, 72, 96] {
                    let Some(&verifier_ns) = verifier_cost.get(&(anchor, examples)) else {
                        continue;
                    };
                    let quality = frontier
                        .iter()
                        .find(|row| {
                            row.level == "overall_equal_cell"
                                && row.phase == phase
                                && row.state_step == anchor + age
                                && row.anchor_step == Some(anchor)
                                && row.offset_from_anchor == Some(age)
                                && row.partition_age == if reuse == 1 { 0 } else { age }
                                && row.method == method
                                && row.evidence_examples == examples
                        })
                        .ok_or_else(|| {
                            io::Error::new(
                                io::ErrorKind::InvalidData,
                                format!(
                                    "missing quality row for {method}, anchor {anchor}, age {age}"
                                ),
                            )
                        })?;
                    let v48_quality = if examples == 48 {
                        let row = v48_summary
                            .iter()
                            .find(|row| {
                                row.level == "overall_equal_cell"
                                    && row.phase == phase
                                    && row.state_step == anchor + age
                                    && row.anchor_step == Some(anchor)
                                    && row.offset_from_anchor == Some(age)
                                    && row.partition_age == if reuse == 1 { 0 } else { age }
                                    && row.method == method
                                    && row.evidence_examples == 48
                            })
                            .ok_or_else(|| {
                                io::Error::new(
                                    io::ErrorKind::InvalidData,
                                    format!(
                                        "missing V48 decision row for {method}, anchor {anchor}, age {age}"
                                    ),
                                )
                            })?;
                        Some(row)
                    } else {
                        None
                    };
                    let predicted = quality.predicted_rmse;
                    let observed_v48 = v48_quality.and_then(|row| row.observed_rmse_v48);
                    let sign_error_v48 = v48_quality.and_then(|row| row.sign_error_rate_v48);
                    let selected_regret_v48 =
                        v48_quality.and_then(|row| row.selected_program_regret_v48);
                    let false_authorization_v48 =
                        v48_quality.and_then(|row| row.false_authorization_rate_v48);
                    let amortized = refresh / reuse as f64;
                    let projected = amortized + verifier_ns;
                    writeln!(
                        out,
                        "{method},{anchor},{reuse},{},{age},{examples},{refresh:.0},{amortized:.0},{verifier_ns:.0},{projected:.0},{predicted:.12e},{},{},{},{},{}",
                        anchor + age,
                        optional_scientific(observed_v48),
                        optional_scientific(sign_error_v48),
                        optional_scientific(selected_regret_v48),
                        optional_scientific(false_authorization_v48),
                        phase
                    )?;
                    rows_written += 1;
                }
            }
        }
    }
    out.flush()?;
    if rows_written != 288 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("expected 288 cost-projection rows, wrote {rows_written}"),
        ));
    }
    Ok(rows_written)
}

fn optional_scientific(value: Option<f64>) -> String {
    value.map_or_else(String::new, |number| format!("{number:.12e}"))
}
