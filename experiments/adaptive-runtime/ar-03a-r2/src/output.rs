use std::fs::File;
use std::io::{self, BufReader, BufWriter, Read, Write};
use std::path::Path;

use sha2::{Digest, Sha256};

use crate::audit::{
    CandidateRecord, MetricMean, PanelRecord, PartitionRecord, StateMetric, TaylorRecord,
};
use crate::model::{CLASSES, MappedDataset};
use crate::protocol::{
    DATASET_SEEDS, DEVELOPMENT_SEEDS, EVALUATION_SEEDS, INITIALIZATION_SEEDS, StateSnapshot,
};

pub struct OutputData<'a> {
    pub states: &'a [StateSnapshot],
    pub candidates: &'a [CandidateRecord],
    pub partitions: &'a [PartitionRecord],
    pub panels: &'a [PanelRecord],
    pub state_metrics: &'a [StateMetric],
    pub stream_means: &'a [MetricMean],
    pub cell_means: &'a [MetricMean],
    pub dataset_means: &'a [MetricMean],
    pub initialization_means: &'a [MetricMean],
    pub summaries: &'a [MetricMean],
    pub taylor: &'a [TaylorRecord],
    pub datasets: &'a [MappedDataset],
    pub development_response_dimensions: &'a [usize],
}

pub fn write_all(output_dir: &Path, data: OutputData<'_>) -> io::Result<()> {
    write_states(output_dir.join("states.csv"), data.states)?;
    write_model_states(output_dir.join("model-states.bin"), data.states)?;
    write_candidates(output_dir.join("candidate-index.csv"), data.candidates)?;
    write_partitions(output_dir.join("partitions.csv"), data.partitions)?;
    write_panels(output_dir.join("panels.csv"), data.panels)?;
    write_state_metrics(output_dir.join("state-metrics.csv"), data.state_metrics)?;
    write_metric_rows(output_dir.join("stream-summary.csv"), data.stream_means)?;
    write_metric_rows(output_dir.join("cell-summary.csv"), data.cell_means)?;
    write_metric_rows(output_dir.join("dataset-summary.csv"), data.dataset_means)?;
    write_metric_rows(
        output_dir.join("initialization-summary.csv"),
        data.initialization_means,
    )?;
    write_metric_rows(output_dir.join("summary.csv"), data.summaries)?;
    write_taylor(output_dir.join("taylor-alpha-1.csv"), data.taylor)?;
    write_report(
        output_dir.join("report.json"),
        data,
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
        "role,dataset_index,dataset_seed,initialization_index,initialization_seed,stream_seed,step,train_loss,parameter_fingerprint,development_candidates,evaluation_candidates,eligible_blocks,bounds_skipped_blocks"
    )?;
    for state in states {
        writeln!(
            output,
            "{},{},{:016x},{},{:016x},{:016x},{},{:.9},{:016x},{},{},{},{}",
            state.role.as_str(),
            state.dataset_index,
            state.dataset_seed,
            state.initialization_index,
            state.initialization_seed,
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
        "role,dataset_index,initialization_index,dataset_seed,initialization_seed,stream_seed,step,action_split,block,left_parameter,right_parameter,left_rank,right_rank,left_delta,right_delta,utility_alpha_1"
    )?;
    for row in rows {
        writeln!(
            output,
            "{},{},{},{:016x},{:016x},{:016x},{},{},{},{},{},{},{},{:.8},{:.8},{:.12e}",
            row.role,
            row.dataset_index,
            row.initialization_index,
            row.dataset_seed,
            row.initialization_seed,
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
        )?;
    }
    output.flush()
}

fn write_partitions(path: impl AsRef<Path>, rows: &[PartitionRecord]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "role,dataset_index,initialization_index,stream_seed,step,method,sample_index,stratum,kmeans_iterations,within_sse"
    )?;
    for row in rows {
        let seed = if row.seed == 0 {
            String::new()
        } else {
            format!("{:016x}", row.seed)
        };
        writeln!(
            output,
            "{},{},{},{},{},{},{},{},{},{:.12e}",
            row.role,
            row.dataset_index,
            row.initialization_index,
            seed,
            row.step,
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
        "dataset_index,initialization_index,stream_seed,step,method,panel,candidate_count,utility_rmse,sign_error_rate,cross_block_regret,selected_program_regret,false_authorization"
    )?;
    for row in rows {
        writeln!(
            output,
            "{},{},{:016x},{},{},{},{},{:.12e},{:.9},{:.12e},{:.12e},{}",
            row.dataset_index,
            row.initialization_index,
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
        "dataset_index,initialization_index,stream_seed,step,method,candidate_count,within_stratum_utility_variance,predicted_finite_population_rmse,observed_panel_rmse,sign_error_rate,cross_block_regret,selected_program_regret,false_authorization_rate"
    )?;
    for row in rows {
        writeln!(
            output,
            "{},{},{:016x},{},{},{},{:.12e},{:.12e},{:.12e},{:.9},{:.12e},{:.12e},{:.9}",
            row.dataset_index,
            row.initialization_index,
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

fn write_metric_rows(path: impl AsRef<Path>, rows: &[MetricMean]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "dataset_index,initialization_index,stream_seed,method,n_states,within_stratum_utility_variance,predicted_finite_population_rmse,observed_panel_rmse,sign_error_rate,cross_block_regret,selected_program_regret,false_authorization_rate"
    )?;
    for row in rows {
        let dataset = index_label(row.dataset_index);
        let initialization = index_label(row.initialization_index);
        let seed = if row.seed == 0 {
            String::new()
        } else {
            format!("{:016x}", row.seed)
        };
        writeln!(
            output,
            "{dataset},{initialization},{seed},{},{},{:.12e},{:.12e},{:.12e},{:.9},{:.12e},{:.12e},{:.9}",
            row.method,
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

fn index_label(index: u8) -> String {
    if index == u8::MAX {
        String::new()
    } else {
        index.to_string()
    }
}

fn write_taylor(path: impl AsRef<Path>, rows: &[TaylorRecord]) -> io::Result<()> {
    let mut output = writer(path)?;
    writeln!(
        output,
        "dataset_index,initialization_index,stream_seed,step,evaluation_candidates,point_count,taylor_rmse,correlation,r_squared,sign_error_rate"
    )?;
    for row in rows {
        writeln!(
            output,
            "{},{},{:016x},{},{},{},{:.12e},{:.9},{:.9},{:.9}",
            row.dataset_index,
            row.initialization_index,
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
    data: OutputData<'_>,
    model_states_hash: &str,
) -> io::Result<()> {
    let path = path.as_ref().to_path_buf();
    let mut output = writer(&path)?;
    let development_candidate_count = data
        .candidates
        .iter()
        .filter(|candidate| candidate.split == "development")
        .count();
    let evaluation_candidate_count = data.candidates.len() - development_candidate_count;
    writeln!(output, "{{")?;
    writeln!(output, "  \"experiment\": \"AR-03A-R2\",")?;
    writeln!(output, "  \"status\": \"diagnostic-only\",")?;
    writeln!(output, "  \"runtime_proxy_used\": false,")?;
    writeln!(output, "  \"end_to_end_training_comparison\": false,")?;
    writeln!(output, "  \"validation_data_generated_or_read\": false,")?;
    writeln!(output, "  \"crossed_cells\": 9,")?;
    writeln!(
        output,
        "  \"training_rows_per_dataset\": {},",
        crate::model::TRAIN_SAMPLES
    )?;
    writeln!(output, "  \"input_dimensions\": 8,")?;
    writeln!(output, "  \"model_parameters\": {},", crate::model::PARAMS)?;
    writeln!(output, "  \"strata\": 12,")?;
    writeln!(output, "  \"examples_per_stratum\": 8,")?;
    writeln!(output, "  \"verifier_panel_size\": 48,")?;
    writeln!(output, "  \"proposal_batch_size\": 16,")?;
    writeln!(output, "  \"commits_per_evidence_draw\": 4,")?;
    writeln!(output, "  \"action_scale\": 1.0,")?;
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
    writeln!(output, "  \"checkpoints\": [600, 2400, 4200],")?;
    writeln!(output, "  \"datasets\": [")?;
    for (index, dataset) in data.datasets.iter().enumerate() {
        let path = output_dir_dataset_path(&path, index);
        let hash = sha256_file(&path)?;
        let mut class_counts = [0_usize; CLASSES];
        for sample in dataset.samples() {
            class_counts[sample.target as usize] += 1;
        }
        let suffix = if index + 1 == data.datasets.len() {
            ""
        } else {
            ","
        };
        writeln!(
            output,
            "    {{\"index\":{index},\"seed\":\"{:016x}\",\"class_counts\":[{},{},{}],\"sha256\":\"{hash}\"}}{suffix}",
            DATASET_SEEDS[index], class_counts[0], class_counts[1], class_counts[2]
        )?;
    }
    writeln!(output, "  ],")?;
    writeln!(output, "  \"initialization_seeds\": [")?;
    write_seed_array_items(&mut output, &INITIALIZATION_SEEDS)?;
    writeln!(output, "  ],")?;
    write_seed_array(&mut output, "development_stream_seeds", &DEVELOPMENT_SEEDS)?;
    write_seed_array(&mut output, "evaluation_stream_seeds", &EVALUATION_SEEDS)?;
    writeln!(
        output,
        "  \"development_response_dimensions_by_cell\": {:?},",
        data.development_response_dimensions
    )?;
    writeln!(
        output,
        "  \"model_states_sha256\": \"{model_states_hash}\","
    )?;
    write_metric_section(&mut output, "summary", data.summaries)?;
    write_metric_section(&mut output, "cell_summary", data.cell_means)?;
    write_metric_section(&mut output, "dataset_summary", data.dataset_means)?;
    write_metric_section(
        &mut output,
        "initialization_summary",
        data.initialization_means,
    )?;
    write_metric_section(&mut output, "stream_summary", data.stream_means)?;
    writeln!(
        output,
        "  \"action_values\": [0.0, -0.02, 0.02, -0.01, 0.01, -0.005, 0.005]"
    )?;
    writeln!(output, "}}")?;
    output.flush()
}

fn output_dir_dataset_path(report_path: &Path, index: usize) -> std::path::PathBuf {
    report_path
        .parent()
        .expect("report path has parent")
        .join(format!("dataset-d{index:02}.bin"))
}

fn write_seed_array(output: &mut impl Write, name: &str, seeds: &[u64]) -> io::Result<()> {
    writeln!(output, "  \"{name}\": [")?;
    write_seed_array_items(output, seeds)?;
    writeln!(output, "  ],")
}

fn write_seed_array_items(output: &mut impl Write, seeds: &[u64]) -> io::Result<()> {
    for (index, seed) in seeds.iter().enumerate() {
        let suffix = if index + 1 == seeds.len() { "" } else { "," };
        writeln!(output, "    \"{seed:016x}\"{suffix}")?;
    }
    Ok(())
}

fn write_metric_section(
    output: &mut impl Write,
    name: &str,
    rows: &[MetricMean],
) -> io::Result<()> {
    writeln!(output, "  \"{name}\": [")?;
    for (index, row) in rows.iter().enumerate() {
        let suffix = if index + 1 == rows.len() { "" } else { "," };
        let dataset = index_label(row.dataset_index);
        let initialization = index_label(row.initialization_index);
        writeln!(
            output,
            "    {{\"dataset_index\":\"{dataset}\",\"initialization_index\":\"{initialization}\",\"stream_seed\":\"{:016x}\",\"method\":\"{}\",\"n_states\":{},\"within_stratum_variance\":{:.12e},\"predicted_rmse\":{:.12e},\"observed_rmse\":{:.12e},\"sign_error_rate\":{:.9},\"cross_block_regret\":{:.12e},\"selected_program_regret\":{:.12e},\"false_authorization_rate\":{:.9}}}{suffix}",
            row.seed,
            row.method,
            row.n_states,
            row.within_stratum_variance,
            row.predicted_rmse,
            row.observed_rmse,
            row.sign_error_rate,
            row.cross_block_regret,
            row.selected_program_regret,
            row.false_authorization_rate
        )?;
    }
    writeln!(output, "  ],")
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
