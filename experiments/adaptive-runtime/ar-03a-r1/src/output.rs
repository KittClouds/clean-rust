use std::fs::File;
use std::io::{self, BufReader, BufWriter, Read, Write};
use std::path::Path;

use sha2::{Digest, Sha256};

use crate::audit::{
    CandidateRecord, MetricMean, PanelRecord, PartitionRecord, StateMetric, TaylorRecord,
};
use crate::model::MappedDataset;
use crate::protocol::{DEVELOPMENT_SEEDS, EVALUATION_SEEDS, StateSnapshot};

pub struct OutputData<'a> {
    pub states: &'a [StateSnapshot],
    pub candidates: &'a [CandidateRecord],
    pub partitions: &'a [PartitionRecord],
    pub panels: &'a [PanelRecord],
    pub state_metrics: &'a [StateMetric],
    pub seed_means: &'a [MetricMean],
    pub summaries: &'a [MetricMean],
    pub taylor: &'a [TaylorRecord],
    pub dataset: &'a MappedDataset,
    pub development_response_dimensions: usize,
}

pub fn write_all(output_dir: &Path, data: OutputData<'_>) -> io::Result<()> {
    let dataset_hash = sha256_file(&output_dir.join("dataset.bin"))?;
    write_states(output_dir.join("states.csv"), data.states)?;
    write_model_states(output_dir.join("model-states.bin"), data.states)?;
    write_candidates(output_dir.join("candidate-index.csv"), data.candidates)?;
    write_partitions(output_dir.join("partitions.csv"), data.partitions)?;
    write_panels(output_dir.join("panels.csv"), data.panels)?;
    write_state_metrics(output_dir.join("state-metrics.csv"), data.state_metrics)?;
    write_metric_rows(output_dir.join("seed-summary.csv"), data.seed_means)?;
    write_metric_rows(output_dir.join("summary.csv"), data.summaries)?;
    write_taylor(output_dir.join("taylor.csv"), data.taylor)?;
    write_report(
        output_dir.join("report.json"),
        data,
        &dataset_hash,
        sha256_file(&output_dir.join("model-states.bin"))?.as_str(),
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

fn write_model_states(path: impl AsRef<Path>, states: &[StateSnapshot]) -> io::Result<()> {
    let mut output = writer(path)?;
    for state in states {
        for parameter in state.model.parameters {
            output.write_all(&parameter.to_le_bytes())?;
        }
    }
    output.flush()
}

fn write_candidates(path: impl AsRef<Path>, rows: &[CandidateRecord]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "role,seed,step,action_split,block,left_parameter,right_parameter,left_rank,right_rank,left_delta,right_delta,utility_alpha_0_5,utility_alpha_1,utility_alpha_2"
    )?;
    for row in rows {
        writeln!(
            output,
            "{},{:016x},{},{},{},{},{},{},{},{:.8},{:.8},{:.12e},{:.12e},{:.12e}",
            row.role,
            row.seed,
            row.step,
            row.split,
            row.block,
            row.left_parameter,
            row.right_parameter,
            row.left_rank,
            row.right_rank,
            row.left_delta,
            row.right_delta,
            row.exact_utility[0],
            row.exact_utility[1],
            row.exact_utility[2],
        )?;
    }
    output.flush()
}

fn write_partitions(path: impl AsRef<Path>, rows: &[PartitionRecord]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "role,seed,step,scale,method,sample_index,stratum,kmeans_iterations,within_sse"
    )?;
    for row in rows {
        let seed = if row.seed == 0 {
            String::new()
        } else {
            format!("{:016x}", row.seed)
        };
        writeln!(
            output,
            "{},{},{},{:.1},{},{},{},{},{:.12e}",
            row.role,
            seed,
            row.step,
            row.scale,
            row.method,
            row.sample,
            row.stratum,
            row.iterations,
            row.within_sse,
        )?;
    }
    output.flush()
}

fn write_panels(path: impl AsRef<Path>, rows: &[PanelRecord]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "seed,step,scale,method,panel,candidate_count,utility_rmse,sign_error_rate,cross_block_regret,selected_program_regret,false_authorization"
    )?;
    for row in rows {
        writeln!(
            output,
            "{:016x},{},{:.1},{},{},{},{:.12e},{:.9},{:.12e},{:.12e},{}",
            row.seed,
            row.step,
            row.scale,
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
        "seed,step,scale,method,candidate_count,within_stratum_utility_variance,predicted_finite_population_rmse,observed_panel_rmse,sign_error_rate,cross_block_regret,selected_program_regret,false_authorization_rate"
    )?;
    for row in rows {
        writeln!(
            output,
            "{:016x},{},{:.1},{},{},{:.12e},{:.12e},{:.12e},{:.9},{:.12e},{:.12e},{:.9}",
            row.seed,
            row.step,
            row.scale,
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

fn write_metric_rows(path: impl AsRef<Path>, rows: &[MetricMean]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "method,seed,n_states,scale,within_stratum_utility_variance,predicted_finite_population_rmse,observed_panel_rmse,sign_error_rate,cross_block_regret,selected_program_regret,false_authorization_rate"
    )?;
    for row in rows {
        let seed = if row.seed == 0 {
            String::new()
        } else {
            format!("{:016x}", row.seed)
        };
        writeln!(
            output,
            "{},{},{},{:.1},{:.12e},{:.12e},{:.12e},{:.9},{:.12e},{:.12e},{:.9}",
            row.method,
            seed,
            row.n_states,
            row.scale,
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
        "seed,step,scale,evaluation_candidates,point_count,taylor_rmse,correlation,r_squared,sign_error_rate"
    )?;
    for row in rows {
        writeln!(
            output,
            "{:016x},{},{:.1},{},{},{:.12e},{:.9},{:.9},{:.9}",
            row.seed,
            row.step,
            row.scale,
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
    data: OutputData<'_>,
    dataset_hash: &str,
    model_states_hash: &str,
) -> io::Result<()> {
    let mut output = writer(path)?;
    let development_candidate_count = data
        .candidates
        .iter()
        .filter(|candidate| candidate.split == "development")
        .count();
    let evaluation_candidate_count = data.candidates.len() - development_candidate_count;
    writeln!(output, "{{")?;
    writeln!(output, "  \"experiment\": \"AR-03A-R1\",")?;
    writeln!(output, "  \"status\": \"diagnostic-only\",")?;
    writeln!(output, "  \"runtime_proxy_used\": false,")?;
    writeln!(output, "  \"end_to_end_training_comparison\": false,")?;
    writeln!(output, "  \"validation_data_generated_or_read\": false,")?;
    writeln!(
        output,
        "  \"training_rows\": {},",
        data.dataset.samples().len()
    )?;
    writeln!(
        output,
        "  \"dataset_seed\": \"{:016x}\",",
        crate::model::DATASET_SEED
    )?;
    writeln!(output, "  \"input_dimensions\": 8,")?;
    writeln!(output, "  \"model_parameters\": 171,")?;
    writeln!(output, "  \"strata\": 12,")?;
    writeln!(output, "  \"examples_per_stratum\": 8,")?;
    writeln!(output, "  \"verifier_panel_size\": 48,")?;
    writeln!(output, "  \"proposal_batch_size\": 16,")?;
    writeln!(output, "  \"commits_per_evidence_draw\": 4,")?;
    writeln!(output, "  \"panel_replicates\": 64,")?;
    writeln!(output, "  \"state_snapshots\": {},", data.states.len())?;
    writeln!(
        output,
        "  \"development_candidate_rows\": {development_candidate_count},"
    )?;
    writeln!(
        output,
        "  \"evaluation_candidate_rows\": {evaluation_candidate_count},"
    )?;
    writeln!(output, "  \"panel_rows\": {},", data.panels.len())?;
    writeln!(
        output,
        "  \"state_metric_rows\": {},",
        data.state_metrics.len()
    )?;
    writeln!(
        output,
        "  \"development_response_dimensions\": {},",
        data.development_response_dimensions
    )?;
    writeln!(output, "  \"dataset_sha256\": \"{dataset_hash}\",")?;
    writeln!(
        output,
        "  \"model_states_sha256\": \"{model_states_hash}\","
    )?;
    writeln!(output, "  \"checkpoints\": [600, 2400, 4200],")?;
    writeln!(
        output,
        "  \"action_scales\": [{:.1}, {:.1}, {:.1}],",
        crate::protocol::SCALES[0],
        crate::protocol::SCALES[1],
        crate::protocol::SCALES[2]
    )?;
    writeln!(output, "  \"training_action_scale\": 1.0,")?;
    writeln!(
        output,
        "  \"action_values\": [0.0, -0.02, 0.02, -0.01, 0.01, -0.005, 0.005],"
    )?;
    write_seed_array(&mut output, "development_seeds", &DEVELOPMENT_SEEDS)?;
    write_seed_array(&mut output, "evaluation_seeds", &EVALUATION_SEEDS)?;
    writeln!(output, "  \"summary\": [")?;
    for (index, row) in data.summaries.iter().enumerate() {
        let suffix = if index + 1 == data.summaries.len() {
            ""
        } else {
            ","
        };
        write_metric_json(&mut output, row, "    ", suffix)?;
    }
    writeln!(output, "  ],")?;
    writeln!(output, "  \"evaluation_seed_summary\": [")?;
    for (index, row) in data
        .seed_means
        .iter()
        .filter(|row| row.seed != 0)
        .enumerate()
    {
        let suffix = if index + 1 == data.seed_means.iter().filter(|row| row.seed != 0).count() {
            ""
        } else {
            ","
        };
        write_metric_json(&mut output, row, "    ", suffix)?;
    }
    writeln!(output, "  ]")?;
    writeln!(output, "}}")?;
    output.flush()
}

fn write_seed_array(output: &mut impl Write, name: &str, seeds: &[u64]) -> io::Result<()> {
    writeln!(output, "  \"{name}\": [")?;
    for (index, seed) in seeds.iter().enumerate() {
        let suffix = if index + 1 == seeds.len() { "" } else { "," };
        writeln!(output, "    \"{seed:016x}\"{suffix}")?;
    }
    writeln!(output, "  ],")
}

fn write_metric_json(
    output: &mut impl Write,
    row: &MetricMean,
    indent: &str,
    suffix: &str,
) -> io::Result<()> {
    let seed = if row.seed == 0 {
        String::new()
    } else {
        format!("{:016x}", row.seed)
    };
    writeln!(
        output,
        "{indent}{{\"method\":\"{}\",\"seed\":\"{}\",\"n_states\":{},\"scale\":{:.1},\"within_stratum_variance\":{:.12e},\"predicted_rmse\":{:.12e},\"observed_rmse\":{:.12e},\"sign_error_rate\":{:.9},\"cross_block_regret\":{:.12e},\"selected_program_regret\":{:.12e},\"false_authorization_rate\":{:.9}}}{suffix}",
        row.method,
        seed,
        row.n_states,
        row.scale,
        row.within_stratum_variance,
        row.predicted_rmse,
        row.observed_rmse,
        row.sign_error_rate,
        row.cross_block_regret,
        row.selected_program_regret,
        row.false_authorization_rate,
    )
}

fn sha256_file(path: &Path) -> io::Result<String> {
    let file = File::open(path)?;
    let mut input = BufReader::new(file);
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let bytes = input.read(&mut buffer)?;
        if bytes == 0 {
            break;
        }
        hasher.update(&buffer[..bytes]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}
