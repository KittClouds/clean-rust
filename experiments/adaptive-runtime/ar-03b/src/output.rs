use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::Path;

use crate::cost::{ProxyCost, VerifierCost};
use crate::integrity::R2Receipt;
use crate::model::TRAIN_SAMPLES;
use crate::records::{
    ErrorRecord, IntegrityRecord, PanelRecord, SnapshotRecord, StateMetricRecord, SummaryRecord,
};

#[derive(Clone, Copy)]
pub struct OutputData<'a> {
    pub output_dir: &'a Path,
    pub error_records: &'a [ErrorRecord],
    pub state_metrics: &'a [StateMetricRecord],
    pub panel_records: &'a [PanelRecord],
    pub proxy_costs: &'a [ProxyCost],
    pub verifier_costs: &'a [VerifierCost],
    pub integrity: &'a [IntegrityRecord],
    pub snapshots: &'a [SnapshotRecord],
    pub summary_v48: &'a [SummaryRecord],
    pub frontier_summary: &'a [SummaryRecord],
    pub receipt: &'a R2Receipt,
}

pub fn write_all(data: OutputData<'_>) -> io::Result<()> {
    if data.output_dir.exists() {
        return Err(io::Error::new(
            io::ErrorKind::AlreadyExists,
            format!("refusing to overwrite {}", data.output_dir.display()),
        ));
    }
    fs::create_dir_all(data.output_dir)?;
    write_error_frontier(
        data.output_dir.join("error-frontier.csv"),
        data.error_records,
    )?;
    write_state_metrics(data.output_dir.join("state-v48.csv"), data.state_metrics)?;
    write_panels(data.output_dir.join("panel-v48.csv"), data.panel_records)?;
    write_proxy_costs(data.output_dir.join("proxy-cost.csv"), data.proxy_costs)?;
    write_verifier_costs(
        data.output_dir.join("verifier-cost.csv"),
        data.verifier_costs,
    )?;
    write_integrity(data.output_dir.join("integrity.csv"), data.integrity)?;
    write_snapshots(data.output_dir.join("snapshot-index.csv"), data.snapshots)?;
    write_summaries(data.output_dir.join("summary-v48.csv"), data.summary_v48)?;
    write_summaries(
        data.output_dir.join("frontier-summary.csv"),
        data.frontier_summary,
    )?;
    Ok(())
}

fn writer(path: impl AsRef<Path>) -> io::Result<BufWriter<File>> {
    Ok(BufWriter::new(File::create(path)?))
}

fn write_error_frontier(path: impl AsRef<Path>, rows: &[ErrorRecord]) -> io::Result<()> {
    let mut out = writer(path)?;
    writeln!(
        out,
        "dataset_index,initialization_index,stream_seed,state_step,phase,anchor_step,offset_from_anchor,partition_age,method,candidate_count,evidence_examples,samples_per_stratum,within_stratum_utility_variance,predicted_finite_population_rmse"
    )?;
    for row in rows {
        let context = &row.context;
        writeln!(
            out,
            "{},{},{:016x},{},{},{},{},{},{},{},{},{},{:.12e},{:.12e}",
            context.dataset_index,
            context.initialization_index,
            context.stream_seed,
            context.state_step,
            context.phase,
            optional_usize(context.anchor_step),
            optional_usize(context.offset_from_anchor),
            context.partition_age,
            row.method,
            context.candidate_count,
            row.evidence_examples,
            row.samples_per_stratum,
            row.within_stratum_variance,
            row.predicted_rmse
        )?;
    }
    out.flush()
}

fn write_state_metrics(path: impl AsRef<Path>, rows: &[StateMetricRecord]) -> io::Result<()> {
    let mut out = writer(path)?;
    writeln!(
        out,
        "dataset_index,initialization_index,stream_seed,state_step,phase,anchor_step,offset_from_anchor,partition_age,method,candidate_count,within_stratum_utility_variance,predicted_rmse_v48,observed_panel_rmse_v48,sign_error_rate_v48,cross_block_regret_v48,selected_program_regret_v48,false_authorization_rate_v48"
    )?;
    for row in rows {
        let context = &row.context;
        writeln!(
            out,
            "{},{},{:016x},{},{},{},{},{},{},{},{:.12e},{:.12e},{:.12e},{:.9},{:.12e},{:.12e},{:.9}",
            context.dataset_index,
            context.initialization_index,
            context.stream_seed,
            context.state_step,
            context.phase,
            optional_usize(context.anchor_step),
            optional_usize(context.offset_from_anchor),
            context.partition_age,
            row.method,
            context.candidate_count,
            row.within_stratum_variance,
            row.predicted_rmse_v48,
            row.observed_rmse_v48,
            row.sign_error_rate_v48,
            row.cross_block_regret_v48,
            row.selected_program_regret_v48,
            row.false_authorization_rate_v48
        )?;
    }
    out.flush()
}

fn write_panels(path: impl AsRef<Path>, rows: &[PanelRecord]) -> io::Result<()> {
    let mut out = writer(path)?;
    writeln!(
        out,
        "dataset_index,initialization_index,stream_seed,state_step,phase,anchor_step,offset_from_anchor,partition_age,method,panel,utility_rmse_v48,sign_error_rate_v48,cross_block_regret_v48,selected_program_regret_v48,false_authorization_v48"
    )?;
    for row in rows {
        let context = &row.context;
        writeln!(
            out,
            "{},{},{:016x},{},{},{},{},{},{},{},{:.12e},{:.9},{:.12e},{:.12e},{}",
            context.dataset_index,
            context.initialization_index,
            context.stream_seed,
            context.state_step,
            context.phase,
            optional_usize(context.anchor_step),
            optional_usize(context.offset_from_anchor),
            context.partition_age,
            row.method,
            row.panel,
            row.utility_rmse_v48,
            row.sign_error_rate_v48,
            row.cross_block_regret_v48,
            row.selected_program_regret_v48,
            row.false_authorization_v48
        )?;
    }
    out.flush()
}

fn write_proxy_costs(path: impl AsRef<Path>, rows: &[ProxyCost]) -> io::Result<()> {
    let mut out = writer(path)?;
    writeln!(
        out,
        "method,dataset_index,initialization_index,stream_seed,state_step,feature_dimensions,feature_payload_bytes,feature_acquisition_median_ns,feature_acquisition_ns_per_example,partition_build_median_ns,partition_build_ns_per_example,measurement_repetitions"
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{},{:016x},{},{},{},{},{:.3},{},{:.3},3",
            row.method,
            row.dataset_index,
            row.initialization_index,
            row.stream_seed,
            row.step,
            row.dimensions,
            row.feature_payload_bytes,
            row.acquisition_median_ns,
            row.acquisition_median_ns as f64 / TRAIN_SAMPLES as f64,
            row.partition_median_ns,
            row.partition_median_ns as f64 / TRAIN_SAMPLES as f64
        )?;
    }
    out.flush()
}

fn write_verifier_costs(path: impl AsRef<Path>, rows: &[VerifierCost]) -> io::Result<()> {
    let mut out = writer(path)?;
    writeln!(
        out,
        "dataset_index,initialization_index,stream_seed,state_step,verifier_examples,candidate_count,candidate_sample_evaluations,forward_passes,median_elapsed_ns,measurement_repetitions"
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{:016x},{},{},{},{},{},{},3",
            row.dataset_index,
            row.initialization_index,
            row.stream_seed,
            row.step,
            row.verifier_examples,
            row.candidate_count,
            row.candidate_sample_evaluations,
            row.forward_passes,
            row.median_ns
        )?;
    }
    out.flush()
}

fn write_integrity(path: impl AsRef<Path>, rows: &[IntegrityRecord]) -> io::Result<()> {
    let mut out = writer(path)?;
    writeln!(
        out,
        "dataset_index,initialization_index,stream_seed,state_step,parameter_fingerprint,evaluation_candidate_count,r2_checkpoint,r2_state_match,r2_candidate_count_match,r2_utility_match,r2_gradient_partition_match"
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{:016x},{},{:016x},{},{},{},{},{},{}",
            row.dataset_index,
            row.initialization_index,
            row.stream_seed,
            row.state_step,
            row.fingerprint,
            row.evaluation_candidate_count,
            row.r2_checkpoint,
            row.r2_state_match,
            row.r2_candidate_count_match,
            row.r2_utility_match,
            row.r2_gradient_partition_match
        )?;
    }
    out.flush()
}

fn write_snapshots(path: impl AsRef<Path>, rows: &[SnapshotRecord]) -> io::Result<()> {
    let mut out = writer(path)?;
    writeln!(
        out,
        "dataset_index,initialization_index,stream_seed,state_step,parameter_fingerprint,train_loss,evaluation_candidate_count,r2_checkpoint"
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{:016x},{},{:016x},{:.9},{},{}",
            row.dataset_index,
            row.initialization_index,
            row.stream_seed,
            row.state_step,
            row.parameter_fingerprint,
            row.train_loss,
            row.evaluation_candidate_count,
            row.r2_checkpoint
        )?;
    }
    out.flush()
}

fn write_summaries(path: impl AsRef<Path>, rows: &[SummaryRecord]) -> io::Result<()> {
    let mut out = writer(path)?;
    writeln!(
        out,
        "aggregation_level,dataset_index,initialization_index,phase,state_step,anchor_step,offset_from_anchor,partition_age,method,evidence_examples,n_aggregation_units,within_stratum_utility_variance,predicted_rmse,observed_rmse_v48,sign_error_rate_v48,cross_block_regret_v48,selected_program_regret_v48,false_authorization_rate_v48"
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{},{},{},{},{},{},{},{},{},{:.12e},{:.12e},{},{},{},{},{}",
            row.level,
            optional_u8(row.dataset_index),
            optional_u8(row.initialization_index),
            row.phase,
            row.state_step,
            optional_usize(row.anchor_step),
            optional_usize(row.offset_from_anchor),
            row.partition_age,
            row.method,
            row.evidence_examples,
            row.n_aggregation_units,
            row.within_stratum_variance,
            row.predicted_rmse,
            optional_f64(row.observed_rmse_v48),
            optional_f64(row.sign_error_rate_v48),
            optional_f64(row.cross_block_regret_v48),
            optional_f64(row.selected_program_regret_v48),
            optional_f64(row.false_authorization_rate_v48)
        )?;
    }
    out.flush()
}

pub fn write_report(
    path: impl AsRef<Path>,
    data: OutputData<'_>,
    cost_projection_rows: usize,
) -> io::Result<()> {
    let mut out = writer(path)?;
    writeln!(out, "{{")?;
    writeln!(out, r#"  "experiment": "AR-03B","#)?;
    writeln!(out, r#"  "status": "diagnostic-only","#)?;
    writeln!(out, r#"  "runtime_proxy_used": false,"#)?;
    writeln!(out, r#"  "training_policy_changed": false,"#)?;
    writeln!(out, r#"  "end_to_end_training_comparison": false,"#)?;
    writeln!(
        out,
        r#"  "r2_model_states_sha256": "{}","#,
        data.receipt.model_states_sha256
    )?;
    writeln!(
        out,
        r#"  "r2_dataset_sha256": ["{}","{}","{}"],"#,
        data.receipt.dataset_sha256[0],
        data.receipt.dataset_sha256[1],
        data.receipt.dataset_sha256[2]
    )?;
    writeln!(out, r#"  "eval_streams_replayed": 18,"#)?;
    writeln!(out, r#"  "crossed_cells": 9,"#)?;
    writeln!(out, r#"  "captured_states": {},"#, data.snapshots.len())?;
    writeln!(
        out,
        r#"  "r2_checkpoints_verified": {},"#,
        data.integrity.len()
    )?;
    writeln!(
        out,
        r#"  "proxy_partitions": ["full_gradient_171","output_layer_27","last_hidden_layer_72","rademacher_projection_32","sign_gradient_171","eight_hash_placebos"],"#
    )?;
    writeln!(out, r#"  "evidence_examples": [12,24,36,48,72,96],"#)?;
    writeln!(out, r#"  "panel_replicates_at_48": 64,"#)?;
    writeln!(out, r#"  "partition_age_commits": [0,25,50,100],"#)?;
    writeln!(
        out,
        r#"  "state_metric_rows": {},"#,
        data.state_metrics.len()
    )?;
    writeln!(out, r#"  "panel_rows": {},"#, data.panel_records.len())?;
    writeln!(out, r#"  "frontier_rows": {},"#, data.error_records.len())?;
    writeln!(out, r#"  "proxy_cost_rows": {},"#, data.proxy_costs.len())?;
    writeln!(
        out,
        r#"  "verifier_cost_rows": {},"#,
        data.verifier_costs.len()
    )?;
    writeln!(out, r#"  "snapshot_index_rows": {},"#, data.snapshots.len())?;
    writeln!(out, r#"  "cost_projection_rows": {cost_projection_rows},"#)?;
    writeln!(
        out,
        r#"  "limitations": ["timings are local CPU measurements","no controller or optimizer result","only R2 empirical examples and synthetic family","nested streams, checkpoints, ages, and panels are not independent cells"]"#
    )?;
    writeln!(out, "}}")?;
    out.flush()
}

fn optional_usize(value: Option<usize>) -> String {
    value.map_or_else(String::new, |number| number.to_string())
}

fn optional_u8(value: Option<u8>) -> String {
    value.map_or_else(String::new, |number| number.to_string())
}

fn optional_f64(value: Option<f64>) -> String {
    value.map_or_else(String::new, |number| format!("{number:.12e}"))
}
