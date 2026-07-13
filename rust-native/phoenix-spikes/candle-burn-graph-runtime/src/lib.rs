use phoenix_graph_research::{
    evaluate_ranking_scores, DerivedFeatureRow, ResearchSplit, TrainTopologyAudit,
    TrainTopologyFeatureBundle, TrainTopologyFeatureMapped, TrainTopologyFeaturePolicy,
    TrainTopologyFeatureSnapshot, TRAIN_TOPOLOGY_FEATURE_SCHEMA,
};
use serde::Serialize;
use std::hint::black_box;
use std::path::Path;
use std::time::{Duration, Instant};

pub const FEATURE_DIM: usize = 16;
pub const HIDDEN_DIM: usize = 16;

#[derive(Clone, Debug)]
pub struct PreparedInput {
    pub rows: Vec<DerivedFeatureRow>,
    pub features: Vec<f32>,
    pub reference_scores: Vec<f32>,
    pub weight_1: Vec<f32>,
    pub weight_2: Vec<f32>,
    pub artifact_blake3: String,
    pub artifact_bytes: u64,
    pub artifact_open_micros: u64,
    pub staging_micros: u64,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeSpikeReport {
    pub schema_version: &'static str,
    pub framework: &'static str,
    pub framework_version: &'static str,
    pub backend: &'static str,
    pub rows: usize,
    pub feature_dim: usize,
    pub hidden_dim: usize,
    pub artifact_blake3: String,
    pub artifact_bytes: u64,
    pub source_rows_mmap: bool,
    pub dense_staging_allocations: u8,
    pub warmups: usize,
    pub iterations: usize,
    pub artifact_open_micros: u64,
    pub staging_micros: u64,
    pub tensor_create_micros: u64,
    pub warmup_micros: u64,
    pub inference_total_micros: u64,
    pub inference_per_iteration_micros: u64,
    pub output_copy_micros: u64,
    pub phoenix_evaluation_micros: u64,
    pub max_abs_error: f32,
    pub score_blake3: String,
    pub filtered_mrr: f64,
    pub hits_at_1: f64,
    pub working_set_bytes: u64,
}

pub fn prepare_input(root: &Path, query_count: usize) -> Result<PreparedInput, String> {
    let snapshot = synthetic_snapshot(query_count);
    let paths =
        TrainTopologyFeatureBundle::write(&snapshot, root).map_err(|error| error.to_string())?;
    let opened = Instant::now();
    let mapped =
        TrainTopologyFeatureMapped::open(&paths.manifest).map_err(|error| error.to_string())?;
    let artifact_open_micros = micros(opened.elapsed());
    let artifact_blake3 = mapped.manifest().binary_blake3.to_string();
    let artifact_bytes = mapped.manifest().binary_bytes;
    let staged = Instant::now();
    let records = mapped.link_rows().map_err(|error| error.to_string())?;
    let mut rows = Vec::with_capacity(records.len());
    let mut features = Vec::with_capacity(records.len() * FEATURE_DIM);
    for record in records.iter() {
        let mut values = [0.0_f32; FEATURE_DIM];
        for (column, value) in values.iter_mut().enumerate() {
            *value = record
                .feature(column)
                .ok_or_else(|| "missing feature column".to_owned())?;
        }
        features.extend_from_slice(&values);
        rows.push(DerivedFeatureRow {
            positive_index: record.positive_index(),
            candidate: record.candidate(),
            split: ResearchSplit::Validation,
            label: record.label(),
            features: values,
        });
    }
    let (weight_1, weight_2) = fixed_weights();
    let reference_scores = scalar_scores(&features, &weight_1, &weight_2);
    Ok(PreparedInput {
        rows,
        features,
        reference_scores,
        weight_1,
        weight_2,
        artifact_blake3,
        artifact_bytes,
        artifact_open_micros,
        staging_micros: micros(staged.elapsed()),
    })
}

#[allow(clippy::too_many_arguments)]
pub fn finish_report(
    framework: &'static str,
    framework_version: &'static str,
    backend: &'static str,
    input: &PreparedInput,
    scores: Vec<f32>,
    warmups: usize,
    iterations: usize,
    tensor_create: Duration,
    warmup: Duration,
    inference: Duration,
    output_copy: Duration,
) -> Result<RuntimeSpikeReport, String> {
    if scores.len() != input.reference_scores.len() {
        return Err("runtime output shape differs from reference".to_owned());
    }
    let max_abs_error = scores
        .iter()
        .zip(&input.reference_scores)
        .map(|(actual, expected)| (actual - expected).abs())
        .fold(0.0_f32, f32::max);
    if max_abs_error > 1.0e-4 {
        return Err(format!("runtime parity error {max_abs_error}"));
    }
    let evaluation_started = Instant::now();
    let metrics = evaluate_ranking_scores(&input.rows, &scores, ResearchSplit::Validation)
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "no rankable validation rows".to_owned())?;
    let phoenix_evaluation_micros = micros(evaluation_started.elapsed());
    let mut bytes = Vec::with_capacity(scores.len() * 4);
    for score in &scores {
        bytes.extend_from_slice(&score.to_bits().to_le_bytes());
    }
    black_box(&bytes);
    Ok(RuntimeSpikeReport {
        schema_version: "phoenix-candle-burn-graph-runtime-spike/v1",
        framework,
        framework_version,
        backend,
        rows: input.rows.len(),
        feature_dim: FEATURE_DIM,
        hidden_dim: HIDDEN_DIM,
        artifact_blake3: input.artifact_blake3.clone(),
        artifact_bytes: input.artifact_bytes,
        source_rows_mmap: true,
        dense_staging_allocations: 1,
        warmups,
        iterations,
        artifact_open_micros: input.artifact_open_micros,
        staging_micros: input.staging_micros,
        tensor_create_micros: micros(tensor_create),
        warmup_micros: micros(warmup),
        inference_total_micros: micros(inference),
        inference_per_iteration_micros: micros(inference) / iterations as u64,
        output_copy_micros: micros(output_copy),
        phoenix_evaluation_micros,
        max_abs_error,
        score_blake3: format!("b3-{}", blake3::hash(&bytes).to_hex()),
        filtered_mrr: metrics.mean_reciprocal_rank,
        hits_at_1: metrics.hits_at_1,
        working_set_bytes: working_set_bytes(),
    })
}

pub fn benchmark_args() -> (usize, usize, usize) {
    let mut values = std::env::args().skip(1);
    let queries = values
        .next()
        .and_then(|value| value.parse().ok())
        .unwrap_or(20_000);
    let warmups = values
        .next()
        .and_then(|value| value.parse().ok())
        .unwrap_or(5);
    let iterations = values
        .next()
        .and_then(|value| value.parse().ok())
        .unwrap_or(30);
    (queries, warmups, iterations)
}

pub fn artifact_root(framework: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!("phoenix-graph-runtime-spike-{framework}"))
}

fn synthetic_snapshot(query_count: usize) -> TrainTopologyFeatureSnapshot {
    let mut link_rows = Vec::with_capacity(query_count * 2);
    for query in 0..query_count as u32 {
        for (candidate, label, sign) in [(query * 2, true, 1.0), (query * 2 + 1, false, -1.0)] {
            let mut features = [0.0_f32; FEATURE_DIM];
            for (column, value) in features.iter_mut().enumerate() {
                *value = sign * (column as f32 + 1.0) / FEATURE_DIM as f32;
            }
            link_rows.push(DerivedFeatureRow {
                positive_index: query,
                candidate,
                split: ResearchSplit::Validation,
                label,
                features,
            });
        }
    }
    TrainTopologyFeatureSnapshot {
        schema_version: TRAIN_TOPOLOGY_FEATURE_SCHEMA.into(),
        derivation_id: format!("runtime-spike-v1-{query_count}").into(),
        source_dataset_id: "runtime-spike-dataset".into(),
        source_tensor_id: "runtime-spike-tensor".into(),
        evaluation_protocol_id: "runtime-spike-evaluation".into(),
        policy: TrainTopologyFeaturePolicy {
            incidence_negatives_per_positive: 1,
        },
        audit: TrainTopologyAudit {
            fit_edges: 0,
            fit_incidences: 0,
            link_examples: link_rows.len() as u64,
            incidence_examples: 0,
            latest_fit_edge_ms: None,
            topology_blake3: "b3-runtime-spike".into(),
            train_only: true,
            asserted_edges_only: true,
            resolved_incidences_only: true,
            leave_one_positive_out: true,
        },
        feature_certificates: Vec::new(),
        link_rows,
        incidence_rows: Vec::new(),
    }
}

fn fixed_weights() -> (Vec<f32>, Vec<f32>) {
    let mut first = vec![0.0_f32; FEATURE_DIM * HIDDEN_DIM];
    for input in 0..FEATURE_DIM {
        for hidden in 0..HIDDEN_DIM {
            first[input * HIDDEN_DIM + hidden] =
                (((input * 17 + hidden * 13 + 7) % 29) as f32 - 14.0) / 64.0;
        }
    }
    let second = (0..HIDDEN_DIM)
        .map(|index| ((index * 11 + 3) % 17) as f32 / 17.0 - 0.25)
        .collect();
    (first, second)
}

fn scalar_scores(features: &[f32], first: &[f32], second: &[f32]) -> Vec<f32> {
    let mut scores = Vec::with_capacity(features.len() / FEATURE_DIM);
    for row in features.chunks_exact(FEATURE_DIM) {
        let mut score = 0.0_f32;
        for hidden in 0..HIDDEN_DIM {
            let mut activation = 0.0_f32;
            for input in 0..FEATURE_DIM {
                activation += row[input] * first[input * HIDDEN_DIM + hidden];
            }
            score += activation.max(0.0) * second[hidden];
        }
        scores.push(score);
    }
    scores
}

fn micros(duration: Duration) -> u64 {
    duration.as_micros().try_into().unwrap_or(u64::MAX)
}

#[cfg(windows)]
fn working_set_bytes() -> u64 {
    #[repr(C)]
    struct ProcessMemoryCounters {
        cb: u32,
        page_fault_count: u32,
        peak_working_set_size: usize,
        working_set_size: usize,
        quota_peak_paged_pool_usage: usize,
        quota_paged_pool_usage: usize,
        quota_peak_non_paged_pool_usage: usize,
        quota_non_paged_pool_usage: usize,
        pagefile_usage: usize,
        peak_pagefile_usage: usize,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentProcess() -> *mut core::ffi::c_void;
    }
    #[link(name = "psapi")]
    extern "system" {
        fn GetProcessMemoryInfo(
            process: *mut core::ffi::c_void,
            counters: *mut ProcessMemoryCounters,
            size: u32,
        ) -> i32;
    }
    let mut counters: ProcessMemoryCounters = unsafe { std::mem::zeroed() };
    counters.cb = std::mem::size_of::<ProcessMemoryCounters>() as u32;
    let size = counters.cb;
    let success = unsafe { GetProcessMemoryInfo(GetCurrentProcess(), &mut counters, size) };
    if success == 0 {
        0
    } else {
        counters.working_set_size as u64
    }
}

#[cfg(not(windows))]
fn working_set_bytes() -> u64 {
    0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_artifact_feeds_the_shared_evaluator() {
        let root = std::env::temp_dir().join(format!(
            "phoenix-graph-runtime-spike-test-{}",
            std::process::id()
        ));
        let input = prepare_input(&root, 64).expect("prepare mapped input");
        let metrics = evaluate_ranking_scores(
            &input.rows,
            &input.reference_scores,
            ResearchSplit::Validation,
        )
        .expect("evaluate scores")
        .expect("rankable rows");

        assert_eq!(input.rows.len(), 128);
        assert_eq!(input.features.len(), 128 * FEATURE_DIM);
        assert_eq!(metrics.queries, 64);
        assert_eq!(metrics.hits_at_1, 1.0);
        std::fs::remove_dir_all(root).expect("remove test artifact");
    }
}
