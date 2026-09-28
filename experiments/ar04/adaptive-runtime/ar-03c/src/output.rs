use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;

use crate::records::{
    CostFrontierRecord, PanelRecord, PartitionCostRecord, QualityRecord, VerifierCostRecord,
};
use crate::summary;

pub struct OutputData<'a> {
    pub root: &'a Path,
    pub quality: &'a [QualityRecord],
    pub panels: &'a [PanelRecord],
    pub costs: &'a [PartitionCostRecord],
    pub verifier_costs: &'a [VerifierCostRecord],
    pub frontier: &'a [CostFrontierRecord],
    pub integrity_json: &'a str,
    pub report_json: &'a str,
}

pub fn write_all(data: OutputData<'_>) -> std::io::Result<()> {
    fs::create_dir_all(data.root)?;
    write_quality(data.root.join("partition-quality.csv"), data.quality)?;
    write_panels(data.root.join("panel-v48.csv"), data.panels)?;
    write_partition_cost(data.root.join("partition-cost.csv"), data.costs)?;
    write_verifier_cost(data.root.join("verifier-cost-v48.csv"), data.verifier_costs)?;
    write_cost_frontier(data.root.join("cost-frontier.csv"), data.frontier)?;
    summary::write_all(data.root, data.quality, data.frontier)?;
    fs::write(data.root.join("integrity.json"), data.integrity_json)?;
    fs::write(data.root.join("report.json"), data.report_json)?;
    Ok(())
}

fn writer(path: impl AsRef<Path>, header: &str) -> std::io::Result<BufWriter<File>> {
    let mut out = BufWriter::new(File::create(path)?);
    writeln!(out, "{header}")?;
    Ok(out)
}

fn write_quality(path: impl AsRef<Path>, rows: &[QualityRecord]) -> std::io::Result<()> {
    let mut out = writer(
        path,
        "dataset_index,initialization_index,stream_seed,state_step,anchor_step,partition_age,method,mode,candidate_count,within_stratum_utility_variance_v48,predicted_rmse_v48,observed_rmse_v48,sign_error_rate_v48,cross_block_regret_v48,selected_program_regret_v48,false_authorization_rate_v48",
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{:016x},{},{},{},{},{},{},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e}",
            row.dataset,
            row.initialization,
            row.stream_seed,
            row.state_step,
            row.anchor_step,
            row.age,
            row.method,
            row.mode,
            row.candidate_count,
            row.within_variance_v48,
            row.predicted_rmse_v48,
            row.observed_rmse_v48,
            row.sign_error_v48,
            row.cross_block_regret_v48,
            row.selected_regret_v48,
            row.false_authorization_v48
        )?;
    }
    out.flush()
}

fn write_panels(path: impl AsRef<Path>, rows: &[PanelRecord]) -> std::io::Result<()> {
    let mut out = writer(
        path,
        "dataset_index,initialization_index,stream_seed,state_step,anchor_step,partition_age,method,mode,panel,utility_rmse_v48,sign_error_rate_v48,cross_block_regret_v48,selected_program_regret_v48,false_authorization_v48",
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{:016x},{},{},{},{},{},{},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e}",
            row.dataset,
            row.initialization,
            row.stream_seed,
            row.state_step,
            row.anchor_step,
            row.age,
            row.method,
            row.mode,
            row.panel,
            row.utility_rmse,
            row.sign_error,
            row.cross_block_regret,
            row.selected_regret,
            row.false_authorization
        )?;
    }
    out.flush()
}

fn write_partition_cost(
    path: impl AsRef<Path>,
    rows: &[PartitionCostRecord],
) -> std::io::Result<()> {
    let mut out = writer(
        path,
        "dataset_index,initialization_index,stream_seed,state_step,anchor_step,age,method,feature_dimensions,feature_payload_bytes,feature_acquisition_median_ns,partition_build_median_ns,iterations,within_sse,measurement_repetitions",
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{:016x},{},{},{},{},{},{},{},{},{},{:.12e},3",
            row.dataset,
            row.initialization,
            row.stream_seed,
            row.state_step,
            row.anchor_step,
            row.age,
            row.method,
            row.feature_dimensions,
            row.feature_bytes,
            row.feature_ns,
            row.partition_ns,
            row.iterations,
            row.within_sse
        )?;
    }
    out.flush()
}

fn write_verifier_cost(path: impl AsRef<Path>, rows: &[VerifierCostRecord]) -> std::io::Result<()> {
    let mut out = writer(
        path,
        "dataset_index,initialization_index,stream_seed,state_step,verifier_examples,candidate_count,candidate_sample_evaluations,elapsed_median_ns,measurement_repetitions",
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{:016x},{},48,{},{},{},3",
            row.dataset,
            row.initialization,
            row.stream_seed,
            row.state_step,
            row.candidate_count,
            row.sample_evaluations,
            row.elapsed_ns
        )?;
    }
    out.flush()
}

fn write_cost_frontier(path: impl AsRef<Path>, rows: &[CostFrontierRecord]) -> std::io::Result<()> {
    let mut out = writer(
        path,
        "dataset_index,initialization_index,stream_seed,anchor_step,reuse_commits,quality_readout_step,method,refresh_feature_ns,refresh_partition_ns,amortized_proxy_ns_per_commit,verifier_ns_per_commit,projected_total_ns_per_commit,within_stratum_utility_variance_v48,predicted_rmse_v48,observed_rmse_v48,sign_error_rate_v48,cross_block_regret_v48,selected_program_regret_v48,false_authorization_rate_v48,quality_mode",
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{:016x},{},{},{},{},{},{},{:.2},{},{:.2},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},stale_reuse",
            row.dataset,
            row.initialization,
            row.stream_seed,
            row.anchor_step,
            row.reuse_commits,
            row.quality_readout_step,
            row.method,
            row.build_feature_ns,
            row.build_partition_ns,
            row.amortized_proxy_ns,
            row.verifier_ns,
            row.projected_total_ns,
            row.within_variance_v48,
            row.predicted_rmse_v48,
            row.observed_rmse_v48,
            row.sign_error_v48,
            row.cross_block_regret_v48,
            row.selected_regret_v48,
            row.false_authorization_v48
        )?;
    }
    out.flush()
}
