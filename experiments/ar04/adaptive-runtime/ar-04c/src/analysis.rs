use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::Path;

use bytemuck::try_cast_slice;

use crate::experiment::DatasetBundle;
use crate::model::{Model, Sample};
use crate::protocol::{self, Arm, Candidate, TIE_EPSILON};
use crate::runtime::Checkpoint;

pub fn analyze(
    output_dir: &Path,
    datasets: &[DatasetBundle],
    checkpoints: &[Checkpoint],
) -> io::Result<()> {
    let mut action_output = BufWriter::new(File::create(
        output_dir.join("checkpoint-action-scores.csv"),
    )?);
    let mut metric_output = BufWriter::new(File::create(output_dir.join("ranking-metrics.csv"))?);
    let mut outcome_output =
        BufWriter::new(File::create(output_dir.join("checkpoint-outcomes.csv"))?);
    writeln!(
        action_output,
        "cell_id,arm,stage,action_id,operational_utility,final_utility"
    )?;
    writeln!(
        metric_output,
        "cell_id,arm,stage,candidate_count,spearman,pairwise_agreement,pair_count,top1_agreement,candidate_regret"
    )?;
    writeln!(
        outcome_output,
        "cell_id,dataset_id,initialization_id,arm,stage,train_loss,final_loss,final_accuracy,operational_loss,verifier_size"
    )?;

    let mut cell_final = vec![[f64::NAN; 3]; protocol::CELL_COUNT];
    for checkpoint in checkpoints {
        let dataset_id = checkpoint.cell_id / protocol::INITIALIZATION_COUNT;
        let final_measurement = load_samples(&datasets[dataset_id].measurement_path)?;
        let train = &datasets[dataset_id].train;
        let proposal_round = checkpoint.step / protocol::COMMITS_PER_EVIDENCE;
        let proposal_indices = crate::frozen_protocol::proposal_indices(
            protocol::stream_seed(checkpoint.cell_id),
            proposal_round,
        );
        let candidates = protocol::build_candidates(
            &checkpoint.model,
            train,
            &proposal_indices,
            checkpoint.step,
        );
        if candidates.is_empty() {
            return Err(io::Error::other(
                "AR-04C checkpoint candidate universe is empty",
            ));
        }
        let (operational, verifier_size) = operational_panel(checkpoint, datasets, dataset_id);
        let operational_loss = checkpoint.model.loss(&operational);
        let final_loss = checkpoint.model.loss(&final_measurement);
        let accuracy = accuracy(&checkpoint.model, &final_measurement);
        writeln!(
            outcome_output,
            "{},{},{},{},{},{:.12e},{:.12e},{:.9},{:.12e},{}",
            checkpoint.cell_id,
            dataset_id,
            checkpoint.cell_id % protocol::INITIALIZATION_COUNT,
            checkpoint.arm.name(),
            checkpoint.step,
            checkpoint.train_loss,
            final_loss,
            accuracy,
            operational_loss,
            verifier_size
        )?;
        if checkpoint.step == protocol::RUNTIME_STEPS {
            cell_final[checkpoint.cell_id][arm_index(checkpoint.arm)] = f64::from(final_loss);
        }

        let op_baseline = checkpoint.model.loss(&operational);
        let final_baseline = checkpoint.model.loss(&final_measurement);
        let mut op_scores = Vec::with_capacity(candidates.len());
        let mut final_scores = Vec::with_capacity(candidates.len());
        for candidate in &candidates {
            let changed = apply_action(checkpoint.model, candidate);
            let op_utility = f64::from(op_baseline - changed.loss(&operational));
            let final_utility = f64::from(final_baseline - changed.loss(&final_measurement));
            op_scores.push(op_utility);
            final_scores.push(final_utility);
            writeln!(
                action_output,
                "{},{},{},{},{:.12e},{:.12e}",
                checkpoint.cell_id,
                checkpoint.arm.name(),
                checkpoint.step,
                candidate.action_id,
                op_utility,
                final_utility
            )?;
        }
        let metrics = compare(&op_scores, &final_scores);
        writeln!(
            metric_output,
            "{},{},{},{},{:.12e},{:.12e},{},{:.9},{:.12e}",
            checkpoint.cell_id,
            checkpoint.arm.name(),
            checkpoint.step,
            candidates.len(),
            metrics.spearman,
            metrics.pairwise,
            metrics.pair_count,
            metrics.top1,
            metrics.regret
        )?;
    }
    action_output.flush()?;
    metric_output.flush()?;
    outcome_output.flush()?;
    write_contrasts(output_dir, &cell_final)?;
    write_summary(output_dir, &cell_final)?;
    Ok(())
}

#[derive(Clone, Copy, Debug)]
struct Metrics {
    spearman: f64,
    pairwise: f64,
    pair_count: usize,
    top1: f64,
    regret: f64,
}

fn compare(source: &[f64], reference: &[f64]) -> Metrics {
    let source_order = ranking(source);
    let reference_order = ranking(reference);
    let pair_count = source
        .iter()
        .enumerate()
        .flat_map(|(left, source_left)| {
            source
                .iter()
                .enumerate()
                .skip(left + 1)
                .filter_map(move |(right, source_right)| {
                    let reference_delta = reference[left] - reference[right];
                    let source_delta = source_left - source_right;
                    (source_delta.abs() > TIE_EPSILON && reference_delta.abs() > TIE_EPSILON)
                        .then_some((source_delta.signum() == reference_delta.signum()) as usize)
                })
        })
        .collect::<Vec<_>>();
    let pairwise = if pair_count.is_empty() {
        0.0
    } else {
        pair_count.iter().sum::<usize>() as f64 / pair_count.len() as f64
    };
    let best_source = source_order[0];
    let best_reference = reference.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    Metrics {
        spearman: pearson(&rank_values(source), &rank_values(reference)),
        pairwise,
        pair_count: pair_count.len(),
        top1: (best_source == reference_order[0]) as u8 as f64,
        regret: best_reference - reference[best_source],
    }
}

fn ranking(values: &[f64]) -> Vec<usize> {
    let mut order: Vec<_> = (0..values.len()).collect();
    order.sort_by(|left, right| {
        values[*right]
            .total_cmp(&values[*left])
            .then_with(|| left.cmp(right))
    });
    order
}

fn rank_values(values: &[f64]) -> Vec<f64> {
    let mut order: Vec<_> = (0..values.len()).collect();
    order.sort_by(|left, right| values[*left].total_cmp(&values[*right]));
    let mut ranks = vec![0.0; values.len()];
    let mut start = 0;
    while start < order.len() {
        let mut end = start + 1;
        while end < order.len() && (values[order[end]] - values[order[start]]).abs() <= TIE_EPSILON
        {
            end += 1;
        }
        let rank = (start + end - 1) as f64 / 2.0;
        for &index in &order[start..end] {
            ranks[index] = rank;
        }
        start = end;
    }
    ranks
}

fn pearson(left: &[f64], right: &[f64]) -> f64 {
    let left_mean = left.iter().sum::<f64>() / left.len() as f64;
    let right_mean = right.iter().sum::<f64>() / right.len() as f64;
    let mut numerator = 0.0;
    let mut left_sum = 0.0;
    let mut right_sum = 0.0;
    for (&a, &b) in left.iter().zip(right) {
        let da = a - left_mean;
        let db = b - right_mean;
        numerator += da * db;
        left_sum += da * da;
        right_sum += db * db;
    }
    if left_sum == 0.0 || right_sum == 0.0 {
        0.0
    } else {
        numerator / (left_sum * right_sum).sqrt()
    }
}

fn apply_action(mut model: Model, candidate: &Candidate) -> Model {
    model.parameters[usize::from(candidate.left_parameter)] += candidate.left_delta;
    model.parameters[usize::from(candidate.right_parameter)] += candidate.right_delta;
    model
}

fn operational_panel(
    checkpoint: &Checkpoint,
    datasets: &[DatasetBundle],
    dataset_id: usize,
) -> (Vec<Sample>, usize) {
    let round = if checkpoint.step == 0 {
        0
    } else {
        checkpoint.step / protocol::COMMITS_PER_EVIDENCE - 1
    };
    match checkpoint.arm {
        Arm::TrainingFull96 => (datasets[dataset_id].train.to_vec(), 96),
        Arm::SentinelFixed128 => (datasets[checkpoint.cell_id].fixed_panel.to_vec(), 128),
        Arm::SentinelRotating128 => (
            protocol::rotating_panel(checkpoint.cell_id, round).to_vec(),
            128,
        ),
    }
}

fn load_samples(path: &Path) -> io::Result<Vec<Sample>> {
    let bytes = fs::read(path)?;
    try_cast_slice(&bytes)
        .map(|samples: &[Sample]| samples.to_vec())
        .map_err(|_| io::Error::other("final measurement binary layout invalid"))
}

fn accuracy(model: &Model, samples: &[Sample]) -> f32 {
    let correct = samples
        .iter()
        .filter(|sample| {
            let logits = model.logits(sample).0;
            let prediction = logits
                .iter()
                .enumerate()
                .max_by(|left, right| left.1.total_cmp(right.1))
                .map_or(0, |(index, _)| index);
            prediction == sample.target as usize
        })
        .count();
    correct as f32 / samples.len() as f32
}

fn arm_index(arm: Arm) -> usize {
    match arm {
        Arm::TrainingFull96 => 0,
        Arm::SentinelFixed128 => 1,
        Arm::SentinelRotating128 => 2,
    }
}

fn write_contrasts(output_dir: &Path, final_losses: &[[f64; 3]]) -> io::Result<()> {
    let mut output = BufWriter::new(File::create(output_dir.join("cell-contrasts.csv"))?);
    writeln!(
        output,
        "cell_id,training_full96,sentinel_fixed128,sentinel_rotating128,fixed_minus_training,rotating_minus_training"
    )?;
    for (cell_id, values) in final_losses.iter().enumerate() {
        writeln!(
            output,
            "{cell_id},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e}",
            values[0],
            values[1],
            values[2],
            values[1] - values[0],
            values[2] - values[0]
        )?;
    }
    output.flush()
}

fn write_summary(output_dir: &Path, final_losses: &[[f64; 3]]) -> io::Result<()> {
    let means = (0..3)
        .map(|arm| final_losses.iter().map(|row| row[arm]).sum::<f64>() / final_losses.len() as f64)
        .collect::<Vec<_>>();
    let mut output = BufWriter::new(File::create(output_dir.join("summary.json"))?);
    writeln!(output, "{{")?;
    writeln!(output, "  \"cell_count\": {},", final_losses.len())?;
    writeln!(output, "  \"mean_final_measurement_loss\": [")?;
    writeln!(output, "    {:.12e},", means[0])?;
    writeln!(output, "    {:.12e},", means[1])?;
    writeln!(output, "    {:.12e}", means[2])?;
    writeln!(output, "  ],")?;
    writeln!(
        output,
        "  \"fixed_minus_training\": {:.12e},",
        means[1] - means[0]
    )?;
    writeln!(
        output,
        "  \"rotating_minus_training\": {:.12e}",
        means[2] - means[0]
    )?;
    writeln!(output, "}}")?;
    output.flush()
}
