use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;

use crate::audit::{
    CandidateRecord, MetricMean, PanelRecord, PartitionRecord, StateMetric, TaylorRecord,
};
use crate::protocol::{EVALUATION_SEEDS, StateSnapshot};

pub struct OutputData<'a> {
    pub states: &'a [StateSnapshot],
    pub candidates: &'a [CandidateRecord],
    pub partitions: &'a [PartitionRecord],
    pub panels: &'a [PanelRecord],
    pub state_metrics: &'a [StateMetric],
    pub seed_means: &'a [MetricMean],
    pub summaries: &'a [MetricMean],
    pub taylor: &'a [TaylorRecord],
    pub development_response_dimensions: usize,
}

pub fn write_all(output_dir: &Path, data: OutputData<'_>) -> io::Result<()> {
    let OutputData {
        states,
        candidates,
        partitions,
        panels,
        state_metrics,
        seed_means,
        summaries,
        taylor,
        development_response_dimensions,
    } = data;
    write_states(output_dir.join("states.csv"), states)?;
    write_candidates(output_dir.join("candidate-index.csv"), candidates)?;
    write_partitions(output_dir.join("partitions.csv"), partitions)?;
    write_panels(output_dir.join("panels.csv"), panels)?;
    write_state_metrics(output_dir.join("state-summary.csv"), state_metrics)?;
    write_metrics(output_dir.join("seed-summary.csv"), seed_means)?;
    write_metrics(output_dir.join("summary.csv"), summaries)?;
    write_taylor(output_dir.join("taylor.csv"), taylor)?;
    write_report(
        output_dir.join("report.json"),
        states,
        candidates,
        panels,
        summaries,
        development_response_dimensions,
    )
}

fn writer(path: impl AsRef<Path>) -> io::Result<BufWriter<File>> {
    Ok(BufWriter::new(File::create(path)?))
}

fn write_states(path: impl AsRef<Path>, states: &[StateSnapshot]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "role,seed,step,train_loss,parameter_fingerprint,development_candidates,evaluation_candidates,eligible_blocks,bounds_skipped_blocks"
    )?;
    for state in states {
        writeln!(
            output,
            "{},{:016x},{},{:.9},{:016x},{},{},{},{}",
            state.role.as_str(),
            state.seed,
            state.step,
            state.train_loss,
            state.fingerprint,
            state.development_candidates.len(),
            state.evaluation_candidates.len(),
            state.eligible_blocks,
            state.bounds_skipped_blocks,
        )?;
    }
    output.flush()
}

fn write_candidates(path: impl AsRef<Path>, rows: &[CandidateRecord]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "role,seed,step,action_split,block,left_parameter,right_parameter,left_rank,right_rank,left_delta,right_delta,exact_train_utility"
    )?;
    for row in rows {
        let candidate = row.candidate;
        writeln!(
            output,
            "{},{:016x},{},{},{},{},{},{},{},{:.8},{:.8},{:.12e}",
            row.role,
            row.seed,
            row.step,
            row.action_split,
            candidate.block,
            candidate.left_parameter,
            candidate.right_parameter,
            candidate.left_rank,
            candidate.right_rank,
            candidate.left_delta,
            candidate.right_delta,
            candidate.exact_utility,
        )?;
    }
    output.flush()
}

fn write_partitions(path: impl AsRef<Path>, rows: &[PartitionRecord]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "role,seed,step,method,sample_index,stratum,kmeans_iterations,within_sse"
    )?;
    for row in rows {
        let seed = if row.seed == 0 {
            String::new()
        } else {
            format!("{:016x}", row.seed)
        };
        writeln!(
            output,
            "{},{},{},{},{},{},{},{:.12e}",
            row.role,
            seed,
            row.step,
            row.method,
            row.sample,
            row.stratum,
            row.kmeans_iterations,
            row.within_sse,
        )?;
    }
    output.flush()
}

fn write_panels(path: impl AsRef<Path>, rows: &[PanelRecord]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "seed,step,method,panel,candidate_count,utility_rmse,sign_error_rate,cross_block_regret,selected_program_regret,false_authorization"
    )?;
    for row in rows {
        writeln!(
            output,
            "{:016x},{},{},{},{},{:.12e},{:.9},{:.12e},{:.12e},{}",
            row.seed,
            row.step,
            row.method,
            row.panel,
            row.candidate_count,
            row.utility_rmse,
            row.sign_error_rate,
            row.cross_block_regret,
            row.selected_program_regret,
            row.false_authorization,
        )?;
    }
    output.flush()
}

fn write_state_metrics(path: impl AsRef<Path>, rows: &[StateMetric]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "seed,step,method,candidate_count,within_stratum_utility_variance,predicted_finite_population_rmse,observed_panel_rmse,sign_error_rate,cross_block_regret,selected_program_regret,false_authorization_rate"
    )?;
    for row in rows {
        writeln!(
            output,
            "{:016x},{},{},{},{:.12e},{:.12e},{:.12e},{:.9},{:.12e},{:.12e},{:.9}",
            row.seed,
            row.step,
            row.method,
            row.candidate_count,
            row.within_stratum_variance,
            row.predicted_rmse,
            row.observed_rmse,
            row.sign_error_rate,
            row.cross_block_regret,
            row.selected_program_regret,
            row.false_authorization_rate,
        )?;
    }
    output.flush()
}

fn write_metrics(path: impl AsRef<Path>, rows: &[MetricMean]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "method,seed,n_states,within_stratum_utility_variance,predicted_finite_population_rmse,observed_panel_rmse,sign_error_rate,cross_block_regret,selected_program_regret,false_authorization_rate"
    )?;
    for row in rows {
        let seed = if row.seed == 0 {
            String::new()
        } else {
            format!("{:016x}", row.seed)
        };
        writeln!(
            output,
            "{},{},{},{:.12e},{:.12e},{:.12e},{:.9},{:.12e},{:.12e},{:.9}",
            row.method,
            seed,
            row.n_states,
            row.within_stratum_variance,
            row.predicted_rmse,
            row.observed_rmse,
            row.sign_error_rate,
            row.cross_block_regret,
            row.selected_program_regret,
            row.false_authorization_rate,
        )?;
    }
    output.flush()
}

fn write_taylor(path: impl AsRef<Path>, rows: &[TaylorRecord]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "seed,step,evaluation_candidates,point_count,taylor_rmse,correlation,r_squared,sign_error_rate"
    )?;
    for row in rows {
        writeln!(
            output,
            "{:016x},{},{},{},{:.12e},{:.9},{:.9},{:.9}",
            row.seed,
            row.step,
            row.candidate_count,
            row.point_count,
            row.rmse,
            row.correlation,
            row.r_squared,
            row.sign_error_rate,
        )?;
    }
    output.flush()
}

fn write_report(
    path: impl AsRef<Path>,
    states: &[StateSnapshot],
    candidates: &[CandidateRecord],
    panels: &[PanelRecord],
    summaries: &[MetricMean],
    development_response_dimensions: usize,
) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(output, "{{")?;
    writeln!(output, "  \"experiment\": \"AR-03A\",")?;
    writeln!(output, "  \"status\": \"diagnostic-only\",")?;
    writeln!(output, "  \"training_comparison\": false,")?;
    writeln!(output, "  \"validation_accessed\": false,")?;
    writeln!(output, "  \"training_examples\": 96,")?;
    writeln!(output, "  \"strata\": 12,")?;
    writeln!(output, "  \"examples_per_stratum\": 8,")?;
    writeln!(output, "  \"panel_size\": 48,")?;
    writeln!(output, "  \"panel_replicates\": 64,")?;
    writeln!(output, "  \"development_streams\": 6,")?;
    writeln!(output, "  \"evaluation_streams\": 6,")?;
    writeln!(output, "  \"state_snapshots\": {},", states.len())?;
    writeln!(output, "  \"candidate_rows\": {},", candidates.len())?;
    writeln!(output, "  \"panel_rows\": {},", panels.len())?;
    writeln!(
        output,
        "  \"development_response_dimensions\": {},",
        development_response_dimensions
    )?;
    writeln!(output, "  \"evaluation_seeds\": [")?;
    for (index, seed) in EVALUATION_SEEDS.iter().enumerate() {
        let suffix = if index + 1 == EVALUATION_SEEDS.len() {
            ""
        } else {
            ","
        };
        writeln!(output, "    \"{seed:016x}\"{suffix}")?;
    }
    writeln!(output, "  ],")?;
    writeln!(output, "  \"summary\": [")?;
    for (index, row) in summaries.iter().enumerate() {
        let suffix = if index + 1 == summaries.len() {
            ""
        } else {
            ","
        };
        writeln!(
            output,
            "    {{\"method\":\"{}\",\"seed_count\":6,\"within_stratum_variance\":{:.12e},\"predicted_rmse\":{:.12e},\"observed_rmse\":{:.12e},\"sign_error_rate\":{:.9},\"cross_block_regret\":{:.12e},\"selected_program_regret\":{:.12e},\"false_authorization_rate\":{:.9}}}{}",
            row.method,
            row.within_stratum_variance,
            row.predicted_rmse,
            row.observed_rmse,
            row.sign_error_rate,
            row.cross_block_regret,
            row.selected_program_regret,
            row.false_authorization_rate,
            suffix,
        )?;
    }
    writeln!(output, "  ]")?;
    writeln!(output, "}}")?;
    output.flush()
}
