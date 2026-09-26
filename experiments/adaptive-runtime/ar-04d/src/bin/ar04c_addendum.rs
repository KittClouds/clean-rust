#[allow(dead_code)]
#[path = "../../../ar-03d-r1/src/protocol.rs"]
mod frozen_protocol;
#[allow(dead_code)]
#[path = "../../../ar-03a-r2/src/model.rs"]
mod model;
#[allow(dead_code)]
#[path = "../../../ar-04c/src/protocol.rs"]
mod old_protocol;

use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::{Path, PathBuf};

use bytemuck::try_cast_slice;
use model::{Model, Sample, TRAIN_SAMPLES};

const AR04C_ARTIFACTS: &str = "../ar-04c/artifacts/run-20260921-ar04c-v1";

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let input = root.join(AR04C_ARTIFACTS);
    let output = root.join("artifacts/ar-04c-addendum-20260926-r2");
    if output.exists() {
        return Err(io::Error::new(
            io::ErrorKind::AlreadyExists,
            format!("refusing to overwrite {}", output.display()),
        )
        .into());
    }
    fs::create_dir_all(&output)?;
    let datasets = load_datasets(&input)?;
    let checkpoints = load_checkpoints(&input)?;
    let mut output_file = BufWriter::new(File::create(output.join("cross-scoring.csv"))?);
    writeln!(
        output_file,
        "cell_id,state_arm,step,source,candidate_count,spearman,pairwise_agreement,pair_count,top1_agreement,candidate_regret,utility_spread"
    )?;

    for checkpoint in checkpoints {
        let dataset_id = checkpoint.cell_id / old_protocol::INITIALIZATION_COUNT;
        let train = &datasets[dataset_id].train;
        let proposal_round = checkpoint.step / old_protocol::COMMITS_PER_EVIDENCE;
        let proposal_indices = frozen_protocol::proposal_indices(
            old_protocol::stream_seed(checkpoint.cell_id),
            proposal_round,
        );
        let candidates = old_protocol::build_candidates(
            &checkpoint.model,
            train,
            &proposal_indices,
            proposal_round % model::PARAMS,
        );
        if candidates.is_empty() {
            return Err(io::Error::other("AR-04C addendum found an empty candidate set").into());
        }
        let final_samples = &datasets[dataset_id].final_measurement;
        let fixed_path = input.join(format!("data/fixed-cell-{:02}.bin", checkpoint.cell_id));
        let fixed = load_samples(&fixed_path)?;
        let rotating_round = if checkpoint.step == 0 {
            0
        } else {
            checkpoint.step / old_protocol::COMMITS_PER_EVIDENCE - 1
        };
        let rotating = old_protocol::rotating_panel(checkpoint.cell_id, rotating_round);
        score_source(
            &mut output_file,
            &checkpoint,
            "training",
            train,
            final_samples,
            &candidates,
        )?;
        score_source(
            &mut output_file,
            &checkpoint,
            "fixed",
            &fixed,
            final_samples,
            &candidates,
        )?;
        score_source(
            &mut output_file,
            &checkpoint,
            "rotating",
            &rotating,
            final_samples,
            &candidates,
        )?;
    }
    output_file.flush()?;
    write_summary(&output)?;
    println!(
        "AR-04C read-only ranking addendum written to {}",
        output.display()
    );
    Ok(())
}

struct Dataset {
    train: [Sample; TRAIN_SAMPLES],
    final_measurement: [Sample; TRAIN_SAMPLES],
}

struct Checkpoint {
    cell_id: usize,
    arm: String,
    step: usize,
    model: Model,
}

fn load_datasets(root: &Path) -> io::Result<Vec<Dataset>> {
    (0..old_protocol::DATASET_COUNT)
        .map(|dataset_id| {
            let train = load_samples(&root.join(format!("data/training-{dataset_id:02}.bin")))?;
            let final_measurement =
                load_samples(&root.join(format!("data/final-measurement-{dataset_id:02}.bin")))?;
            let train: [Sample; TRAIN_SAMPLES] = train
                .try_into()
                .map_err(|_| io::Error::other("invalid AR-04C training sample count"))?;
            let final_measurement: [Sample; TRAIN_SAMPLES] = final_measurement
                .try_into()
                .map_err(|_| io::Error::other("invalid AR-04C final sample count"))?;
            Ok(Dataset {
                train,
                final_measurement,
            })
        })
        .collect()
}

fn load_samples(path: &Path) -> io::Result<Vec<Sample>> {
    let bytes = fs::read(path)?;
    try_cast_slice(&bytes)
        .map(|samples: &[Sample]| samples.to_vec())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "invalid sample artifact"))
}

fn load_checkpoints(root: &Path) -> io::Result<Vec<Checkpoint>> {
    let manifest = fs::read_to_string(root.join("checkpoint-manifest.csv"))?;
    let model_bytes = fs::read(root.join("checkpoint-models.bin"))?;
    let mut rows = Vec::with_capacity(old_protocol::CELL_COUNT * old_protocol::Arm::ALL.len() * 4);
    for line in manifest.lines().skip(1) {
        let columns: Vec<&str> = line.split(',').collect();
        if columns.len() != 6 {
            return Err(io::Error::other("invalid checkpoint manifest row"));
        }
        let offset: usize = columns[4].parse().map_err(invalid_manifest)?;
        let parameter_count: usize = columns[5].parse().map_err(invalid_manifest)?;
        let bytes_len = parameter_count * std::mem::size_of::<f32>();
        let bytes = model_bytes
            .get(offset..offset + bytes_len)
            .ok_or_else(|| io::Error::other("checkpoint model range out of bounds"))?;
        if bytes.len() != model::PARAMS * std::mem::size_of::<f32>() {
            return Err(io::Error::other("invalid checkpoint parameter count"));
        }
        let mut parameters = [0.0_f32; model::PARAMS];
        for (slot, chunk) in parameters.iter_mut().zip(bytes.chunks_exact(4)) {
            *slot = f32::from_le_bytes(chunk.try_into().expect("four-byte model scalar"));
        }
        let model = Model { parameters };
        rows.push(Checkpoint {
            cell_id: columns[0].parse().map_err(invalid_manifest)?,
            arm: columns[1].to_owned(),
            step: columns[2].parse().map_err(invalid_manifest)?,
            model,
        });
    }
    Ok(rows)
}

fn score_source(
    output: &mut BufWriter<File>,
    checkpoint: &Checkpoint,
    source: &str,
    source_samples: &[Sample],
    final_samples: &[Sample],
    candidates: &[old_protocol::Candidate],
) -> io::Result<()> {
    let source_utilities = utilities(&checkpoint.model, source_samples, candidates);
    let final_utilities = utilities(&checkpoint.model, final_samples, candidates);
    let metrics = compare(&source_utilities, &final_utilities);
    writeln!(
        output,
        "{},{},{},{},{},{:.9},{:.9},{},{:.9},{:.12e},{:.12e}",
        checkpoint.cell_id,
        checkpoint.arm,
        checkpoint.step,
        source,
        candidates.len(),
        metrics.spearman,
        metrics.pairwise,
        metrics.pair_count,
        metrics.top1,
        metrics.regret,
        metrics.spread,
    )
}

fn utilities(
    model: &Model,
    samples: &[Sample],
    candidates: &[old_protocol::Candidate],
) -> Vec<f64> {
    let baseline = model.loss(samples);
    candidates
        .iter()
        .map(|candidate| {
            let mut changed = *model;
            changed.parameters[usize::from(candidate.left_parameter)] += candidate.left_delta;
            changed.parameters[usize::from(candidate.right_parameter)] += candidate.right_delta;
            f64::from(baseline - changed.loss(samples))
        })
        .collect()
}

struct Metrics {
    spearman: f64,
    pairwise: f64,
    pair_count: usize,
    top1: f64,
    regret: f64,
    spread: f64,
}

fn compare(source: &[f64], reference: &[f64]) -> Metrics {
    let source_rank = ranks(source);
    let reference_rank = ranks(reference);
    let mean_source = source_rank.iter().sum::<f64>() / source_rank.len() as f64;
    let mean_reference = reference_rank.iter().sum::<f64>() / reference_rank.len() as f64;
    let numerator = source_rank
        .iter()
        .zip(&reference_rank)
        .map(|(left, right)| (left - mean_source) * (right - mean_reference))
        .sum::<f64>();
    let source_norm = source_rank
        .iter()
        .map(|value| (value - mean_source).powi(2))
        .sum::<f64>()
        .sqrt();
    let reference_norm = reference_rank
        .iter()
        .map(|value| (value - mean_reference).powi(2))
        .sum::<f64>()
        .sqrt();
    let spearman = if source_norm > 0.0 && reference_norm > 0.0 {
        numerator / (source_norm * reference_norm)
    } else {
        0.0
    };
    let mut agreement = 0_usize;
    let mut pair_count = 0_usize;
    for left in 0..source.len() {
        for right in (left + 1)..source.len() {
            let source_delta = source[left] - source[right];
            let reference_delta = reference[left] - reference[right];
            if source_delta.abs() <= 1.0e-7 || reference_delta.abs() <= 1.0e-7 {
                continue;
            }
            pair_count += 1;
            if source_delta.signum() == reference_delta.signum() {
                agreement += 1;
            }
        }
    }
    let source_best = argmax(source);
    let reference_best_index = argmax(reference);
    let reference_best = reference.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let regret = reference_best - reference[source_best];
    Metrics {
        spearman,
        pairwise: if pair_count == 0 {
            0.0
        } else {
            agreement as f64 / pair_count as f64
        },
        pair_count,
        top1: if source_best == reference_best_index {
            1.0
        } else {
            0.0
        },
        regret,
        spread: source.iter().copied().fold(f64::NEG_INFINITY, f64::max)
            - source.iter().copied().fold(f64::INFINITY, f64::min),
    }
}

fn argmax(values: &[f64]) -> usize {
    values
        .iter()
        .enumerate()
        .max_by(|left, right| left.1.total_cmp(right.1))
        .map_or(0, |(index, _)| index)
}

fn ranks(values: &[f64]) -> Vec<f64> {
    let mut order: Vec<usize> = (0..values.len()).collect();
    order.sort_by(|left, right| values[*left].total_cmp(&values[*right]));
    let mut result = vec![0.0; values.len()];
    let mut start = 0;
    while start < order.len() {
        let mut end = start + 1;
        while end < order.len() && (values[order[end]] - values[order[start]]).abs() <= 1.0e-7 {
            end += 1;
        }
        let rank = (start + end - 1) as f64 * 0.5;
        for index in start..end {
            result[order[index]] = rank;
        }
        start = end;
    }
    result
}

fn write_summary(output: &Path) -> io::Result<()> {
    let text = fs::read_to_string(output.join("cross-scoring.csv"))?;
    let rows = text.lines().count().saturating_sub(1);
    fs::write(
        output.join("RESULTS.md"),
        format!(
            "# AR-04C Ranking Addendum\n\nRead-only cross-scoring of sealed AR-04C checkpoint states. Rows: {rows}. This addendum does not alter AR-04C artifacts or authorize a controller. Interpret utility spread alongside ranking metrics; terminal near-ties are not treated as meaningful rank evidence.\n"
        ),
    )
}

fn invalid_manifest<T>(_: T) -> io::Error {
    io::Error::other("invalid checkpoint manifest integer")
}
