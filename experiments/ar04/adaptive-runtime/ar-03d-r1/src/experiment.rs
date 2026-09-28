use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::process::Command;
use std::time::Instant;

use hashbrown::HashSet;
use sha2::{Digest, Sha256};

use crate::model::{MappedDataset, TRAIN_SAMPLES};
use crate::protocol::{self, DEVELOPMENT_SEEDS, EVALUATION_SEEDS, INITIALIZATION_SEEDS};
use crate::runtime::{
    self, RUNTIME_CHECKPOINTS, RUNTIME_STEPS, RuntimeArm, RuntimeCheckpoint, RuntimeContext,
    RuntimeTrajectory, VALIDATION_SEEDS,
};

const PARENT_COMMIT: &str = "2df36ced17a9d347f49fd64dc08631217c55227a";
const CELL_COUNT: usize = protocol::DATASET_SEEDS.len() * INITIALIZATION_SEEDS.len();
const STREAMS_PER_CELL: usize = protocol::STREAMS_PER_ROLE_PER_CELL;
const AR_03D_SEED_PREFIXES: [u32; 5] = [
    0xa303_dada,
    0xa303_1a17,
    0xa303_de00,
    0xa303_ea00,
    0xa303_fa00,
];

pub struct RunReport {
    pub trajectory_count: usize,
}

struct DatasetFiles {
    training: MappedDataset,
    evaluation: MappedDataset,
    training_sha256: String,
    evaluation_sha256: String,
}

struct MeasuredTrajectory {
    trace: RuntimeTrajectory,
    wall_ns: u128,
}

#[derive(Clone, Copy)]
struct ArmSummary {
    final_train_loss: f64,
    final_evaluation_loss: f64,
    final_evaluation_accuracy: f64,
    accepted_updates: usize,
    no_op_slots: usize,
    beneficial_updates: usize,
    harmful_updates: usize,
    false_authorizations: usize,
    false_authorization_rate: f64,
    cumulative_beneficial_utility: f64,
    cumulative_harmful_utility: f64,
    p90_harmful_utility: f64,
    p95_harmful_utility: f64,
    p99_harmful_utility: f64,
    max_harmful_utility: f64,
    projected_feature_ns: u128,
    partition_ns: u128,
    panel_ns: u128,
    policy_ns: u128,
    shadow_ns: u128,
    wall_ns: u128,
}

#[derive(Default)]
struct CellAggregates {
    projected_losses: Vec<f64>,
    hash_losses: Vec<f64>,
    paired_differences: Vec<f64>,
    projected_accuracies: Vec<f64>,
    hash_accuracies: Vec<f64>,
    projected_train_losses: Vec<f64>,
    hash_train_losses: Vec<f64>,
}

pub fn run(output_dir: &Path) -> io::Result<RunReport> {
    let source_commit = git_source_commit()?;
    let binary_sha256 = sha256_file(&std::env::current_exe()?)?;
    let source_status = git_source_status()?;
    if !source_status.is_empty() {
        return Err(io::Error::other(format!(
            "refusing collection from a dirty source tree: {source_status}"
        )));
    }
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

    validate_seed_disjointness();
    let mut datasets = Vec::with_capacity(protocol::DATASET_SEEDS.len());
    for (index, (&training_seed, &evaluation_seed)) in protocol::DATASET_SEEDS
        .iter()
        .zip(&VALIDATION_SEEDS)
        .enumerate()
    {
        let train_path = output_dir.join(format!("training-dataset-{index:02}.bin"));
        let evaluation_path = output_dir.join(format!("evaluation-dataset-{index:02}.bin"));
        let training = MappedDataset::generate_write_open(train_path, training_seed)?;
        let evaluation = MappedDataset::generate_write_open(evaluation_path, evaluation_seed)?;
        assert_eq!(training.samples().len(), TRAIN_SAMPLES);
        assert_eq!(evaluation.samples().len(), TRAIN_SAMPLES);
        let training_sha256 =
            sha256_file(&output_dir.join(format!("training-dataset-{index:02}.bin")))?;
        let evaluation_sha256 =
            sha256_file(&output_dir.join(format!("evaluation-dataset-{index:02}.bin")))?;
        datasets.push(DatasetFiles {
            training,
            evaluation,
            training_sha256,
            evaluation_sha256,
        });
    }

    let mut trajectories =
        Vec::with_capacity(CELL_COUNT * STREAMS_PER_CELL * RuntimeArm::ALL.len());
    for (dataset_index, dataset) in datasets.iter().enumerate() {
        for (initialization_index, &initialization_seed) in INITIALIZATION_SEEDS.iter().enumerate()
        {
            let cell_index = dataset_index * INITIALIZATION_SEEDS.len() + initialization_index;
            let first_stream = cell_index * STREAMS_PER_CELL;
            for stream_within_cell in 0..STREAMS_PER_CELL {
                let stream_index = first_stream + stream_within_cell;
                let stream_seed = EVALUATION_SEEDS[stream_index];
                let hash_id = ((cell_index * 3 + stream_within_cell * 4) % 8) as u8;
                for arm in RuntimeArm::ALL {
                    let started = Instant::now();
                    let trace = runtime::replay_training_arm(
                        dataset.training.samples(),
                        dataset.evaluation.samples(),
                        RuntimeContext {
                            dataset_index: dataset_index as u8,
                            dataset_seed: protocol::DATASET_SEEDS[dataset_index],
                            initialization_index: initialization_index as u8,
                            initialization_seed,
                            stream_seed,
                            arm,
                            hash_partition_id: hash_id,
                        },
                    );
                    let wall_ns = started.elapsed().as_nanos();
                    validate_trajectory(&trace, hash_id)?;
                    trajectories.push(MeasuredTrajectory { trace, wall_ns });
                }
            }
        }
    }

    validate_paired_exogenous_inputs(&trajectories)?;
    assert_eq!(
        trajectories.len(),
        CELL_COUNT * STREAMS_PER_CELL * RuntimeArm::ALL.len()
    );
    write_dataset_manifest(output_dir, &datasets)?;
    write_trajectory_outputs(output_dir, &trajectories)?;
    write_integrity(
        output_dir,
        &datasets,
        &trajectories,
        &source_commit,
        &binary_sha256,
    )?;
    Ok(RunReport {
        trajectory_count: trajectories.len(),
    })
}

fn validate_seed_disjointness() {
    let expected_count = protocol::DATASET_SEEDS.len()
        + INITIALIZATION_SEEDS.len()
        + DEVELOPMENT_SEEDS.len()
        + EVALUATION_SEEDS.len()
        + VALIDATION_SEEDS.len();
    let mut seeds = Vec::with_capacity(expected_count);
    seeds.extend(protocol::DATASET_SEEDS);
    seeds.extend(INITIALIZATION_SEEDS);
    seeds.extend(DEVELOPMENT_SEEDS);
    seeds.extend(EVALUATION_SEEDS);
    seeds.extend(VALIDATION_SEEDS);
    let unique: HashSet<_> = seeds.iter().copied().collect();
    assert_eq!(seeds.len(), expected_count);
    assert_eq!(unique.len(), seeds.len());
    assert!(seeds.iter().all(|seed| {
        let high_word = (seed >> 32) as u32;
        !AR_03D_SEED_PREFIXES.contains(&high_word)
    }));
}

fn validate_trajectory(trace: &RuntimeTrajectory, expected_hash_id: u8) -> io::Result<()> {
    if trace.decisions.len() != RUNTIME_STEPS
        || trace.panels.len() != RUNTIME_STEPS / protocol::COMMITS_PER_EVIDENCE
        || trace.checkpoints.len() != RUNTIME_CHECKPOINTS.len()
    {
        return Err(io::Error::other("trajectory count/integrity mismatch"));
    }
    if trace.arm == RuntimeArm::HashPlacebo {
        if trace.hash_partition_id != Some(expected_hash_id)
            || trace.partition_builds.len() != 1
            || trace.partition_builds[0].refresh_slot != 0
        {
            return Err(io::Error::other(
                "hash partition assignment/refresh mismatch",
            ));
        }
    } else {
        let expected: Vec<_> = (0..RUNTIME_STEPS)
            .step_by(runtime::PARTITION_REFRESH_SLOTS)
            .collect();
        let actual: Vec<_> = trace
            .partition_builds
            .iter()
            .map(|build| build.refresh_slot)
            .collect();
        if trace.hash_partition_id.is_some() || actual != expected {
            return Err(io::Error::other(
                "projected partition refresh schedule mismatch",
            ));
        }
    }
    if trace.panels.iter().any(|panel| !panel.quota_valid)
        || trace.decisions.iter().any(|decision| {
            !decision.verifier_utility.is_finite()
                || decision
                    .full_training_utility
                    .is_some_and(|utility| !utility.is_finite())
        })
        || trace.checkpoints.iter().any(|checkpoint| {
            !checkpoint.train_loss.is_finite()
                || !checkpoint.evaluation_loss.is_finite()
                || !checkpoint.evaluation_accuracy.is_finite()
        })
    {
        return Err(io::Error::other("non-finite or invalid trajectory output"));
    }
    for (index, decision) in trace.decisions.iter().enumerate() {
        if decision.step != index + 1
            || decision.schedule_offset != index % crate::model::PARAMS
            || decision.verifier_programs_evaluated > 341
            || decision.selected != decision.full_training_utility.is_some()
        {
            return Err(io::Error::other("decision ledger invariant failed"));
        }
    }
    for (index, panel) in trace.panels.iter().enumerate() {
        if panel.evidence_round != index
            || panel.slot_start != index * protocol::COMMITS_PER_EVIDENCE
        {
            return Err(io::Error::other("panel evidence-round clock mismatch"));
        }
    }
    Ok(())
}

fn validate_paired_exogenous_inputs(trajectories: &[MeasuredTrajectory]) -> io::Result<()> {
    for index in (0..trajectories.len()).step_by(2) {
        let first = &trajectories[index].trace;
        let second = &trajectories[index + 1].trace;
        if first.stream_seed != second.stream_seed
            || first.arm == second.arm
            || first.panels.len() != second.panels.len()
            || first.decisions.len() != second.decisions.len()
            || first.checkpoints.len() != second.checkpoints.len()
        {
            return Err(io::Error::other("paired trajectory identity mismatch"));
        }
        let (first_initial, second_initial) = (&first.checkpoints[0], &second.checkpoints[0]);
        if first_initial.step != 0
            || second_initial.step != 0
            || first_initial.fingerprint != second_initial.fingerprint
            || first_initial.train_loss != second_initial.train_loss
            || first_initial.evaluation_loss != second_initial.evaluation_loss
            || first_initial.evaluation_accuracy != second_initial.evaluation_accuracy
        {
            return Err(io::Error::other("paired initial-state mismatch"));
        }
        for (left, right) in first.panels.iter().zip(&second.panels) {
            if left.evidence_round != right.evidence_round
                || left.slot_start != right.slot_start
                || left.proposal_fingerprint != right.proposal_fingerprint
            {
                return Err(io::Error::other("paired proposal stream mismatch"));
            }
        }
        for (left, right) in first.decisions.iter().zip(&second.decisions) {
            if left.step != right.step || left.schedule_offset != right.schedule_offset {
                return Err(io::Error::other("paired pair-schedule mismatch"));
            }
        }
    }
    Ok(())
}

fn summarize(trajectory: &MeasuredTrajectory) -> ArmSummary {
    let trace = &trajectory.trace;
    let mut harmful = Vec::new();
    let mut accepted_updates = 0;
    let mut beneficial_updates = 0;
    let mut false_authorizations = 0;
    let mut cumulative_beneficial_utility = 0.0;
    let mut cumulative_harmful_utility = 0.0;
    let mut policy_ns = 0_u128;
    let mut shadow_ns = 0_u128;
    for decision in &trace.decisions {
        policy_ns += decision.policy_ns;
        shadow_ns += decision.shadow_ns;
        if let Some(utility) = decision.full_training_utility {
            accepted_updates += 1;
            if utility > 0.0 {
                beneficial_updates += 1;
                cumulative_beneficial_utility += f64::from(utility);
            } else {
                false_authorizations += 1;
                let magnitude = f64::from(-utility);
                harmful.push(magnitude);
                cumulative_harmful_utility += magnitude;
            }
        }
    }
    harmful.sort_by(f64::total_cmp);
    let final_checkpoint = trace.checkpoints.last().expect("final checkpoint exists");
    let projected_feature_ns = trace
        .partition_builds
        .iter()
        .map(|build| build.feature_ns)
        .sum();
    let partition_ns = trace
        .partition_builds
        .iter()
        .map(|build| build.ordering_or_hash_ns)
        .sum();
    let panel_ns = trace.panels.iter().map(|panel| panel.panel_ns).sum();
    ArmSummary {
        final_train_loss: f64::from(final_checkpoint.train_loss),
        final_evaluation_loss: f64::from(final_checkpoint.evaluation_loss),
        final_evaluation_accuracy: f64::from(final_checkpoint.evaluation_accuracy),
        accepted_updates,
        no_op_slots: RUNTIME_STEPS - accepted_updates,
        beneficial_updates,
        harmful_updates: false_authorizations,
        false_authorizations,
        false_authorization_rate: if accepted_updates == 0 {
            0.0
        } else {
            false_authorizations as f64 / accepted_updates as f64
        },
        cumulative_beneficial_utility,
        cumulative_harmful_utility,
        p90_harmful_utility: percentile(&harmful, 0.90),
        p95_harmful_utility: percentile(&harmful, 0.95),
        p99_harmful_utility: percentile(&harmful, 0.99),
        max_harmful_utility: harmful.last().copied().unwrap_or(0.0),
        projected_feature_ns,
        partition_ns,
        panel_ns,
        policy_ns,
        shadow_ns,
        wall_ns: trajectory.wall_ns,
    }
}

fn percentile(sorted: &[f64], probability: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let rank = (probability * sorted.len() as f64).ceil() as usize;
    sorted[rank.saturating_sub(1).min(sorted.len() - 1)]
}

fn write_dataset_manifest(output_dir: &Path, datasets: &[DatasetFiles]) -> io::Result<()> {
    let file = File::create(output_dir.join("dataset-manifest.csv"))?;
    let mut writer = BufWriter::new(file);
    writeln!(
        writer,
        "dataset_index,training_seed,evaluation_seed,training_samples,evaluation_samples,training_sha256,evaluation_sha256"
    )?;
    for (index, dataset) in datasets.iter().enumerate() {
        writeln!(
            writer,
            "{index},{:016x},{:016x},{TRAIN_SAMPLES},{TRAIN_SAMPLES},{},{}",
            protocol::DATASET_SEEDS[index],
            VALIDATION_SEEDS[index],
            dataset.training_sha256,
            dataset.evaluation_sha256,
        )?;
    }
    writer.flush()
}

fn write_trajectory_outputs(
    output_dir: &Path,
    trajectories: &[MeasuredTrajectory],
) -> io::Result<()> {
    write_summaries(output_dir, trajectories)?;
    write_checkpoints(output_dir, trajectories)?;
    write_decisions(output_dir, trajectories)?;
    write_panels(output_dir, trajectories)?;
    write_partition_builds(output_dir, trajectories)
}

fn write_summaries(output_dir: &Path, trajectories: &[MeasuredTrajectory]) -> io::Result<()> {
    let file = File::create(output_dir.join("trajectory-summary.csv"))?;
    let mut writer = BufWriter::new(file);
    writeln!(
        writer,
        "dataset_index,dataset_seed,initialization_index,initialization_seed,stream_seed,arm,hash_partition_id,final_train_loss,final_evaluation_loss,final_evaluation_accuracy,accepted_updates,no_op_slots,beneficial_updates,harmful_updates,false_authorizations,false_authorization_rate,cumulative_beneficial_utility,cumulative_harmful_utility_noop_regret,p90_harmful_utility,p95_harmful_utility,p99_harmful_utility,max_harmful_utility,projected_feature_ns,partition_ns,panel_ns,policy_ns,shadow_ns,wall_ns"
    )?;
    for trajectory in trajectories {
        let trace = &trajectory.trace;
        let summary = summarize(trajectory);
        writeln!(
            writer,
            "{},{:016x},{},{:016x},{:016x},{},{},{:.9e},{:.9e},{:.6},{},{},{},{},{},{:.8},{:.9e},{:.9e},{:.9e},{:.9e},{:.9e},{:.9e},{},{},{},{},{},{}",
            trace.dataset_index,
            trace.dataset_seed,
            trace.initialization_index,
            trace.initialization_seed,
            trace.stream_seed,
            trace.arm.as_str(),
            option_u8(trace.hash_partition_id),
            summary.final_train_loss,
            summary.final_evaluation_loss,
            summary.final_evaluation_accuracy,
            summary.accepted_updates,
            summary.no_op_slots,
            summary.beneficial_updates,
            summary.harmful_updates,
            summary.false_authorizations,
            summary.false_authorization_rate,
            summary.cumulative_beneficial_utility,
            summary.cumulative_harmful_utility,
            summary.p90_harmful_utility,
            summary.p95_harmful_utility,
            summary.p99_harmful_utility,
            summary.max_harmful_utility,
            summary.projected_feature_ns,
            summary.partition_ns,
            summary.panel_ns,
            summary.policy_ns,
            summary.shadow_ns,
            summary.wall_ns,
        )?;
    }
    writer.flush()?;
    write_cell_summary(output_dir, trajectories)
}

fn write_cell_summary(output_dir: &Path, trajectories: &[MeasuredTrajectory]) -> io::Result<()> {
    let file = File::create(output_dir.join("cell-summary.csv"))?;
    let mut writer = BufWriter::new(file);
    writeln!(
        writer,
        "dataset_index,initialization_index,n_streams,projected_evaluation_loss,hash_evaluation_loss,paired_evaluation_loss_difference,projected_accuracy,hash_accuracy,projected_train_loss,hash_train_loss"
    )?;
    let mut cells = CellAggregates {
        projected_losses: Vec::with_capacity(CELL_COUNT),
        hash_losses: Vec::with_capacity(CELL_COUNT),
        paired_differences: Vec::with_capacity(CELL_COUNT),
        projected_accuracies: Vec::with_capacity(CELL_COUNT),
        hash_accuracies: Vec::with_capacity(CELL_COUNT),
        projected_train_losses: Vec::with_capacity(CELL_COUNT),
        hash_train_losses: Vec::with_capacity(CELL_COUNT),
    };
    for cell in 0..CELL_COUNT {
        let cell_rows: Vec<_> = trajectories
            .iter()
            .filter(|row| {
                usize::from(row.trace.dataset_index) * INITIALIZATION_SEEDS.len()
                    + usize::from(row.trace.initialization_index)
                    == cell
            })
            .collect();
        let mut paired_differences = Vec::with_capacity(STREAMS_PER_CELL);
        let mut projected_loss = 0.0;
        let mut hash_loss = 0.0;
        let mut projected_accuracy = 0.0;
        let mut hash_accuracy = 0.0;
        let mut projected_train = 0.0;
        let mut hash_train = 0.0;
        for stream_slot in 0..STREAMS_PER_CELL {
            let seed = EVALUATION_SEEDS[cell * STREAMS_PER_CELL + stream_slot];
            let projected = cell_rows
                .iter()
                .find(|row| {
                    row.trace.stream_seed == seed && row.trace.arm == RuntimeArm::ProjectedOrder1d
                })
                .expect("paired projected trajectory");
            let hash = cell_rows
                .iter()
                .find(|row| {
                    row.trace.stream_seed == seed && row.trace.arm == RuntimeArm::HashPlacebo
                })
                .expect("paired hash trajectory");
            let projected_summary = summarize(projected);
            let hash_summary = summarize(hash);
            projected_loss += projected_summary.final_evaluation_loss;
            hash_loss += hash_summary.final_evaluation_loss;
            projected_accuracy += projected_summary.final_evaluation_accuracy;
            hash_accuracy += hash_summary.final_evaluation_accuracy;
            projected_train += projected_summary.final_train_loss;
            hash_train += hash_summary.final_train_loss;
            paired_differences
                .push(projected_summary.final_evaluation_loss - hash_summary.final_evaluation_loss);
        }
        let n = STREAMS_PER_CELL as f64;
        let mean_projected = projected_loss / n;
        let mean_hash = hash_loss / n;
        let mean_difference = paired_differences.iter().sum::<f64>() / n;
        cells.paired_differences.push(mean_difference);
        cells.projected_losses.push(mean_projected);
        cells.hash_losses.push(mean_hash);
        cells.projected_accuracies.push(projected_accuracy / n);
        cells.hash_accuracies.push(hash_accuracy / n);
        cells.projected_train_losses.push(projected_train / n);
        cells.hash_train_losses.push(hash_train / n);
        writeln!(
            writer,
            "{},{},{},{:.9e},{:.9e},{:.9e},{:.6},{:.6},{:.9e},{:.9e}",
            cell / INITIALIZATION_SEEDS.len(),
            cell % INITIALIZATION_SEEDS.len(),
            STREAMS_PER_CELL,
            mean_projected,
            mean_hash,
            mean_difference,
            cells.projected_accuracies[cell],
            cells.hash_accuracies[cell],
            cells.projected_train_losses[cell],
            cells.hash_train_losses[cell],
        )?;
    }
    writer.flush()?;
    write_overall_summary(output_dir, &cells)?;
    write_factor_marginals(output_dir, &cells)
}

fn write_overall_summary(output_dir: &Path, cells: &CellAggregates) -> io::Result<()> {
    let file = File::create(output_dir.join("overall-summary.csv"))?;
    let mut writer = BufWriter::new(file);
    writeln!(
        writer,
        "n_cells,equal_cell_projected_evaluation_loss,equal_cell_hash_evaluation_loss,equal_cell_paired_loss_difference,equal_cell_projected_accuracy,equal_cell_hash_accuracy,equal_cell_projected_train_loss,equal_cell_hash_train_loss"
    )?;
    let mean = |values: &[f64]| values.iter().sum::<f64>() / values.len() as f64;
    writeln!(
        writer,
        "{},{:.9e},{:.9e},{:.9e},{:.6},{:.6},{:.9e},{:.9e}",
        cells.paired_differences.len(),
        mean(&cells.projected_losses),
        mean(&cells.hash_losses),
        mean(&cells.paired_differences),
        mean(&cells.projected_accuracies),
        mean(&cells.hash_accuracies),
        mean(&cells.projected_train_losses),
        mean(&cells.hash_train_losses),
    )?;
    writer.flush()
}

fn write_factor_marginals(output_dir: &Path, cells: &CellAggregates) -> io::Result<()> {
    let file = File::create(output_dir.join("factor-marginals.csv"))?;
    let mut writer = BufWriter::new(file);
    writeln!(
        writer,
        "factor,factor_index,n_cells,projected_evaluation_loss,hash_evaluation_loss,paired_loss_difference,projected_accuracy,hash_accuracy"
    )?;
    for dataset in 0..protocol::DATASET_SEEDS.len() {
        let start = dataset * INITIALIZATION_SEEDS.len();
        let indices = start..start + INITIALIZATION_SEEDS.len();
        write_factor_marginal(&mut writer, "dataset", dataset, indices, cells)?;
    }
    for initialization in 0..INITIALIZATION_SEEDS.len() {
        let indices = (0..protocol::DATASET_SEEDS.len())
            .map(|dataset| dataset * INITIALIZATION_SEEDS.len() + initialization);
        write_factor_marginal(
            &mut writer,
            "initialization",
            initialization,
            indices,
            cells,
        )?;
    }
    writer.flush()
}

fn write_factor_marginal(
    writer: &mut impl Write,
    factor: &str,
    factor_index: usize,
    cell_indices: impl IntoIterator<Item = usize>,
    cells: &CellAggregates,
) -> io::Result<()> {
    let mut count = 0_usize;
    let mut projected_loss = 0.0;
    let mut hash_loss = 0.0;
    let mut difference = 0.0;
    let mut projected_accuracy = 0.0;
    let mut hash_accuracy = 0.0;
    for cell in cell_indices {
        count += 1;
        projected_loss += cells.projected_losses[cell];
        hash_loss += cells.hash_losses[cell];
        difference += cells.paired_differences[cell];
        projected_accuracy += cells.projected_accuracies[cell];
        hash_accuracy += cells.hash_accuracies[cell];
    }
    let denominator = count as f64;
    writeln!(
        writer,
        "{factor},{factor_index},{count},{:.9e},{:.9e},{:.9e},{:.6},{:.6}",
        projected_loss / denominator,
        hash_loss / denominator,
        difference / denominator,
        projected_accuracy / denominator,
        hash_accuracy / denominator,
    )
}

fn write_checkpoints(output_dir: &Path, trajectories: &[MeasuredTrajectory]) -> io::Result<()> {
    let file = File::create(output_dir.join("checkpoint-ledger.csv"))?;
    let mut writer = BufWriter::new(file);
    writeln!(
        writer,
        "dataset_index,initialization_index,stream_seed,arm,step,train_loss,evaluation_loss,evaluation_accuracy,parameter_fingerprint"
    )?;
    for trajectory in trajectories {
        let trace = &trajectory.trace;
        for checkpoint in &trace.checkpoints {
            write_checkpoint_row(&mut writer, trace, checkpoint)?;
        }
    }
    writer.flush()
}

fn write_checkpoint_row(
    writer: &mut impl Write,
    trace: &RuntimeTrajectory,
    checkpoint: &RuntimeCheckpoint,
) -> io::Result<()> {
    writeln!(
        writer,
        "{},{},{:016x},{},{},{:.9e},{:.9e},{:.6},{:016x}",
        trace.dataset_index,
        trace.initialization_index,
        trace.stream_seed,
        trace.arm.as_str(),
        checkpoint.step,
        checkpoint.train_loss,
        checkpoint.evaluation_loss,
        checkpoint.evaluation_accuracy,
        checkpoint.fingerprint,
    )
}

fn write_decisions(output_dir: &Path, trajectories: &[MeasuredTrajectory]) -> io::Result<()> {
    let file = File::create(output_dir.join("decision-ledger.csv"))?;
    let mut writer = BufWriter::new(file);
    writeln!(
        writer,
        "dataset_index,initialization_index,stream_seed,arm,step,schedule_offset,partition_epoch,panel_fingerprint,policy_ns,verifier_programs_evaluated,selected,left_parameter,right_parameter,left_delta,right_delta,verifier_utility,full_training_utility,shadow_ns"
    )?;
    for trajectory in trajectories {
        let trace = &trajectory.trace;
        for row in &trace.decisions {
            writeln!(
                writer,
                "{},{},{:016x},{},{},{},{},{:016x},{},{},{},{},{},{:.6},{:.6},{:.9e},{},{}",
                trace.dataset_index,
                trace.initialization_index,
                trace.stream_seed,
                trace.arm.as_str(),
                row.step,
                row.schedule_offset,
                row.partition_epoch,
                row.panel_fingerprint,
                row.policy_ns,
                row.verifier_programs_evaluated,
                row.selected,
                option_usize(row.left_parameter),
                option_usize(row.right_parameter),
                row.left_delta,
                row.right_delta,
                row.verifier_utility,
                option_f32(row.full_training_utility),
                row.shadow_ns,
            )?;
        }
    }
    writer.flush()
}

fn write_panels(output_dir: &Path, trajectories: &[MeasuredTrajectory]) -> io::Result<()> {
    let file = File::create(output_dir.join("panel-ledger.csv"))?;
    let mut writer = BufWriter::new(file);
    writeln!(
        writer,
        "dataset_index,initialization_index,stream_seed,arm,hash_partition_id,evidence_round,slot_start,partition_epoch,partition_fingerprint,panel_fingerprint,proposal_fingerprint,verifier_examples,panel_ns,quota_valid"
    )?;
    for trajectory in trajectories {
        let trace = &trajectory.trace;
        for row in &trace.panels {
            writeln!(
                writer,
                "{},{},{:016x},{},{},{},{},{},{:016x},{:016x},{:016x},48,{},{}",
                trace.dataset_index,
                trace.initialization_index,
                trace.stream_seed,
                trace.arm.as_str(),
                option_u8(row.partition_id),
                row.evidence_round,
                row.slot_start,
                row.partition_epoch,
                row.partition_fingerprint,
                row.panel_fingerprint,
                row.proposal_fingerprint,
                row.panel_ns,
                row.quota_valid,
            )?;
        }
    }
    writer.flush()
}

fn write_partition_builds(
    output_dir: &Path,
    trajectories: &[MeasuredTrajectory],
) -> io::Result<()> {
    let file = File::create(output_dir.join("partition-build-ledger.csv"))?;
    let mut writer = BufWriter::new(file);
    writeln!(
        writer,
        "dataset_index,initialization_index,stream_seed,arm,refresh_slot,partition_epoch,hash_partition_id,partition_fingerprint,feature_ns,ordering_or_hash_ns"
    )?;
    for trajectory in trajectories {
        let trace = &trajectory.trace;
        for (epoch, build) in trace.partition_builds.iter().enumerate() {
            writeln!(
                writer,
                "{},{},{:016x},{},{},{},{},{:016x},{},{}",
                trace.dataset_index,
                trace.initialization_index,
                trace.stream_seed,
                trace.arm.as_str(),
                build.refresh_slot,
                epoch,
                option_u8(build.partition_id),
                build.partition_fingerprint,
                build.feature_ns,
                build.ordering_or_hash_ns,
            )?;
        }
    }
    writer.flush()
}

fn write_integrity(
    output_dir: &Path,
    datasets: &[DatasetFiles],
    trajectories: &[MeasuredTrajectory],
    source_commit: &str,
    binary_sha256: &str,
) -> io::Result<()> {
    let decisions = trajectories
        .iter()
        .map(|row| row.trace.decisions.len())
        .sum::<usize>();
    let panels = trajectories
        .iter()
        .map(|row| row.trace.panels.len())
        .sum::<usize>();
    let partition_builds = trajectories
        .iter()
        .map(|row| row.trace.partition_builds.len())
        .sum::<usize>();
    let mut out = BufWriter::new(File::create(output_dir.join("integrity.json"))?);
    writeln!(out, "{{")?;
    writeln!(out, "  \"protocol\": \"AR-03D-R1-5x5-2026-09-21\",")?;
    writeln!(out, "  \"parent_commit\": \"{PARENT_COMMIT}\",")?;
    writeln!(out, "  \"frozen_source_commit\": \"{source_commit}\",")?;
    writeln!(out, "  \"binary_sha256\": \"{binary_sha256}\",")?;
    writeln!(out, "  \"training_dataset_count\": {},", datasets.len())?;
    writeln!(out, "  \"evaluation_dataset_count\": {},", datasets.len())?;
    writeln!(
        out,
        "  \"initialization_count\": {},",
        INITIALIZATION_SEEDS.len()
    )?;
    writeln!(out, "  \"streams_per_cell\": {STREAMS_PER_CELL},")?;
    writeln!(out, "  \"dataset_initialization_cells\": {CELL_COUNT},")?;
    writeln!(out, "  \"evaluation_streams\": {},", EVALUATION_SEEDS.len())?;
    writeln!(out, "  \"paired_trajectories\": {},", trajectories.len())?;
    writeln!(out, "  \"decision_slots\": {decisions},")?;
    writeln!(out, "  \"panel_records\": {panels},")?;
    writeln!(out, "  \"partition_build_records\": {partition_builds},")?;
    writeln!(out, "  \"steps_per_trajectory\": {},", RUNTIME_STEPS)?;
    writeln!(out, "  \"verifier_examples\": 48,")?;
    writeln!(out, "  \"samples_per_stratum\": 4,")?;
    writeln!(out, "  \"strata\": 12,")?;
    writeln!(out, "  \"examples_per_stratum\": 8,")?;
    writeln!(
        out,
        "  \"projected_refresh_slots\": [0,100,200,300,400,500,600,700,800,900,1000,1100,1200,1300,1400,1500,1600,1700,1800,1900,2000,2100,2200,2300,2400,2500,2600,2700,2800,2900,3000,3100,3200,3300,3400,3500,3600,3700,3800,3900,4000,4100],"
    )?;
    writeln!(
        out,
        "  \"full_reference_scope\": \"chosen program only on all 96 training examples; no best-action search\","
    )?;
    writeln!(
        out,
        "  \"evaluation_scope\": \"independent 96-example synthetic set per training dataset; readout only\","
    )?;
    writeln!(out, "  \"integrity_valid\": true")?;
    writeln!(out, "}}")?;
    out.flush()
}

fn git_source_commit() -> io::Result<String> {
    let output = Command::new("git")
        .args(["rev-parse", "HEAD"])
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .output()?;
    if !output.status.success() {
        return Err(io::Error::other("git rev-parse HEAD failed"));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn git_source_status() -> io::Result<String> {
    let output = Command::new("git")
        .args(["status", "--porcelain"])
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .output()?;
    if !output.status.success() {
        return Err(io::Error::other("git status --porcelain failed"));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn sha256_file(path: &Path) -> io::Result<String> {
    let bytes = fs::read(path)?;
    let digest = Sha256::digest(bytes);
    Ok(digest.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn option_u8(value: Option<u8>) -> String {
    value.map_or_else(String::new, |value| value.to_string())
}

fn option_usize(value: Option<usize>) -> String {
    value.map_or_else(String::new, |value| value.to_string())
}

fn option_f32(value: Option<f32>) -> String {
    value.map_or_else(String::new, |value| format!("{value:.9e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn seeds_are_distinct_and_placebo_assignment_balanced_by_cell() {
        validate_seed_disjointness();
        let mut counts = [0_usize; 8];
        for cell in 0..CELL_COUNT {
            let first = (cell * 3) % 8;
            let second = (cell * 3 + 4) % 8;
            assert_ne!(first, second);
            counts[first] += 1;
            counts[second] += 1;
        }
        assert!(counts.iter().all(|count| (6..=7).contains(count)));
    }

    #[test]
    fn percentiles_use_nearest_rank_and_empty_is_zero() {
        assert_eq!(percentile(&[], 0.90), 0.0);
        assert_eq!(percentile(&[1.0, 2.0, 3.0, 4.0], 0.50), 2.0);
        assert_eq!(percentile(&[1.0, 2.0, 3.0, 4.0], 0.95), 4.0);
    }
}
