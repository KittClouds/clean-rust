#[allow(dead_code)]
#[path = "../../../ar-03a-r2/src/model.rs"]
mod model;
#[allow(dead_code)]
#[path = "../../../ar-04d/src/protocol.rs"]
mod old_protocol;

use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::{Path, PathBuf};

use bytemuck::try_cast_slice;
use model::{CLASSES, Model, Sample};

const AR04D_RUN: &str = "../../../../../ar-04d-exposure-frontier-20260926/clean-rust/experiments/adaptive-runtime/ar-04d/artifacts/run-20260926-ar04d-v1";

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let input = root.join(AR04D_RUN);
    let output = root.join("artifacts/ar-04d-addendum-20260926-r4");
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
    write_calibration(&output, &datasets, &checkpoints)?;
    write_contamination(&output, &datasets, &checkpoints)?;
    write_blocked_boundaries(&output, &datasets, &input)?;
    write_results(&output)?;
    println!("AR-04D addendum written to {}", output.display());
    Ok(())
}

struct Dataset {
    population: Vec<Sample>,
}

struct Checkpoint {
    cell_id: usize,
    arm: String,
    step: usize,
    model: Model,
}

struct Metrics {
    loss: f64,
    accuracy: f64,
    ece: f64,
    brier: f64,
    correct_nll: f64,
    wrong_nll: f64,
    wrong_count: usize,
    wrong_confidence: f64,
}

fn load_datasets(root: &Path) -> io::Result<Vec<Dataset>> {
    (0..old_protocol::DATASET_COUNT)
        .map(|dataset_id| {
            Ok(Dataset {
                population: load_samples(
                    &root.join(format!("data/population-{dataset_id:02}.bin")),
                )?,
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
        let bytes_len: usize = columns[5].parse().map_err(invalid_manifest)?;
        let bytes = model_bytes
            .get(offset..offset + bytes_len)
            .ok_or_else(|| io::Error::other("checkpoint model range out of bounds"))?;
        if bytes.len() != model::PARAMS * size_of::<f32>() {
            return Err(io::Error::other("invalid checkpoint parameter count"));
        }
        let mut parameters = [0.0_f32; model::PARAMS];
        for (slot, chunk) in parameters.iter_mut().zip(bytes.chunks_exact(4)) {
            *slot = f32::from_le_bytes(chunk.try_into().expect("four-byte model scalar"));
        }
        rows.push(Checkpoint {
            cell_id: columns[0].parse().map_err(invalid_manifest)?,
            arm: columns[1].to_owned(),
            step: columns[2].parse().map_err(invalid_manifest)?,
            model: Model { parameters },
        });
    }
    Ok(rows)
}

fn write_calibration(
    output: &Path,
    datasets: &[Dataset],
    checkpoints: &[Checkpoint],
) -> io::Result<()> {
    let mut file = BufWriter::new(File::create(output.join("calibration.csv"))?);
    writeln!(
        file,
        "cell_id,dataset_id,arm,step,population_loss,population_accuracy,ece,brier,correct_nll,wrong_nll,wrong_count,wrong_confidence,operational_loss"
    )?;
    for checkpoint in checkpoints {
        let dataset_id = checkpoint.cell_id / old_protocol::INITIALIZATION_COUNT;
        let population = &datasets[dataset_id].population;
        let panel = operational_panel(checkpoint.cell_id, &checkpoint.arm, checkpoint.step);
        let metrics = score(&checkpoint.model, population);
        let operational_loss = checkpoint.model.loss(&panel);
        writeln!(
            file,
            "{},{},{},{},{:.12e},{:.9},{:.12e},{:.12e},{:.12e},{:.12e},{},{:.12e},{:.12e}",
            checkpoint.cell_id,
            dataset_id,
            checkpoint.arm,
            checkpoint.step,
            metrics.loss,
            metrics.accuracy,
            metrics.ece,
            metrics.brier,
            metrics.correct_nll,
            metrics.wrong_nll,
            metrics.wrong_count,
            metrics.wrong_confidence,
            operational_loss,
        )?;
    }
    file.flush()
}

fn write_contamination(
    output: &Path,
    datasets: &[Dataset],
    checkpoints: &[Checkpoint],
) -> io::Result<()> {
    let mut file = BufWriter::new(File::create(output.join("contamination-gaps.csv"))?);
    writeln!(
        file,
        "cell_id,dataset_id,arm,step,operational_loss,population_loss,operational_minus_population"
    )?;
    for checkpoint in checkpoints {
        let dataset_id = checkpoint.cell_id / old_protocol::INITIALIZATION_COUNT;
        let population_loss = checkpoint.model.loss(&datasets[dataset_id].population);
        let operational_loss = checkpoint.model.loss(&operational_panel(
            checkpoint.cell_id,
            &checkpoint.arm,
            checkpoint.step,
        ));
        writeln!(
            file,
            "{},{},{},{},{:.12e},{:.12e},{:.12e}",
            checkpoint.cell_id,
            dataset_id,
            checkpoint.arm,
            checkpoint.step,
            operational_loss,
            population_loss,
            operational_loss - population_loss,
        )?;
    }
    file.flush()
}

fn write_blocked_boundaries(output: &Path, datasets: &[Dataset], input: &Path) -> io::Result<()> {
    let mut file = BufWriter::new(File::create(output.join("blocked-boundaries.csv"))?);
    writeln!(
        file,
        "cell_id,dataset_id,step,from_panel,to_panel,population_loss,from_panel_loss,to_panel_loss,population_accuracy,from_panel_accuracy,to_panel_accuracy"
    )?;
    let decisions = fs::read_to_string(input.join("trajectory-decisions.csv"))?;
    let mut current_cell = usize::MAX;
    let mut model = Model::initial(0);
    for line in decisions.lines().skip(1) {
        let c: Vec<&str> = line.split(',').collect();
        if c.len() != 19 || c[1] != "sentinel_k16_blocked" {
            continue;
        }
        let cell_id: usize = c[0].parse().map_err(invalid_manifest)?;
        let step: usize = c[2].parse().map_err(invalid_manifest)?;
        if cell_id != current_cell {
            current_cell = cell_id;
            let init = cell_id % old_protocol::INITIALIZATION_COUNT;
            model = Model::initial(old_protocol::initialization_seed(init));
        }
        if c[11] == "true" {
            let left: usize = c[12].parse().map_err(invalid_manifest)?;
            let right: usize = c[13].parse().map_err(invalid_manifest)?;
            let left_delta: f32 = c[14].parse().map_err(invalid_manifest)?;
            let right_delta: f32 = c[15].parse().map_err(invalid_manifest)?;
            model.parameters[left] += left_delta;
            if right != usize::MAX {
                model.parameters[right] += right_delta;
            }
        }
        if step < old_protocol::RUNTIME_STEPS
            && step.is_multiple_of(old_protocol::COMMITS_PER_EVIDENCE)
        {
            let from_round = step / old_protocol::COMMITS_PER_EVIDENCE - 1;
            let to_round = step / old_protocol::COMMITS_PER_EVIDENCE;
            let from_panel = old_protocol::blocked_panel_id(from_round);
            let to_panel = old_protocol::blocked_panel_id(to_round);
            if from_panel != to_panel {
                let dataset_id = cell_id / old_protocol::INITIALIZATION_COUNT;
                let population = &datasets[dataset_id].population;
                let from = panel(cell_id, from_panel);
                let to = panel(cell_id, to_panel);
                writeln!(
                    file,
                    "{cell_id},{dataset_id},{step},{from_panel},{to_panel},{:.12e},{:.12e},{:.12e},{:.9},{:.9},{:.9}",
                    model.loss(population),
                    model.loss(&from),
                    model.loss(&to),
                    accuracy(&model, population),
                    accuracy(&model, &from),
                    accuracy(&model, &to),
                )?;
            }
        }
    }
    file.flush()
}

fn operational_panel(cell_id: usize, arm: &str, step: usize) -> Vec<Sample> {
    let panel_id = if step == 0 {
        0
    } else {
        step / old_protocol::COMMITS_PER_EVIDENCE - 1
    };
    match arm {
        "sentinel_k16_pooled" => (0..16).flat_map(|id| panel(cell_id, id)).collect(),
        "sentinel_k1" => panel(cell_id, 0),
        "sentinel_k4_cyclic" => panel(cell_id, panel_id % 4),
        "sentinel_k16_cyclic" => panel(cell_id, panel_id % 16),
        "sentinel_k16_blocked" => panel(cell_id, old_protocol::blocked_panel_id(panel_id)),
        "sentinel_k64_cyclic" => panel(cell_id, panel_id % 64),
        "sentinel_fresh" => panel(cell_id, panel_id),
        _ => panic!("unknown AR-04C arm {arm}"),
    }
}

fn panel(cell_id: usize, panel_id: usize) -> Vec<Sample> {
    old_protocol::panel_from_seeds(
        old_protocol::panel_draw_seed(cell_id, panel_id, 0),
        old_protocol::panel_draw_seed(cell_id, panel_id, 1),
        old_protocol::panel_order_seed(cell_id, panel_id),
    )
    .to_vec()
}

fn score(model: &Model, samples: &[Sample]) -> Metrics {
    let mut loss = 0.0;
    let mut correct_nll = 0.0;
    let mut wrong_nll = 0.0;
    let mut correct_count = 0_usize;
    let mut wrong_count = 0_usize;
    let mut wrong_confidence = 0.0;
    let mut brier = 0.0;
    let mut bins = [[0.0_f64; 4]; 10];
    for sample in samples {
        let logits = model.logits(sample).0;
        let max_logit = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        let exp_sum: f32 = logits.iter().map(|value| (*value - max_logit).exp()).sum();
        let probabilities: Vec<f64> = logits
            .iter()
            .map(|value| f64::from((*value - max_logit).exp() / exp_sum))
            .collect();
        let target = sample.target as usize;
        let sample_loss = -probabilities[target].ln();
        let (predicted, confidence) = probabilities
            .iter()
            .enumerate()
            .max_by(|left, right| left.1.total_cmp(right.1))
            .map(|(index, value)| (index, *value))
            .unwrap_or((0, 0.0));
        let correct = predicted == target;
        loss += sample_loss;
        if correct {
            correct_count += 1;
            correct_nll += sample_loss;
        } else {
            wrong_count += 1;
            wrong_nll += sample_loss;
            wrong_confidence += confidence;
        }
        let bin = ((confidence * 10.0).floor() as usize).min(9);
        bins[bin][0] += 1.0;
        bins[bin][1] += confidence;
        bins[bin][2] += f64::from(correct);
        for (class, probability) in probabilities.iter().enumerate().take(CLASSES) {
            let target_value = f64::from(class == target);
            brier += (*probability - target_value).powi(2);
        }
    }
    for bin in &mut bins {
        if bin[0] > 0.0 {
            bin[3] = (bin[1] / bin[0] - bin[2] / bin[0]).abs() * bin[0];
        }
    }
    let n = samples.len() as f64;
    Metrics {
        loss: loss / n,
        accuracy: correct_count as f64 / n,
        ece: bins.iter().map(|bin| bin[3]).sum::<f64>() / n,
        brier: brier / n,
        correct_nll: if correct_count == 0 {
            0.0
        } else {
            correct_nll / correct_count as f64
        },
        wrong_nll: if wrong_count == 0 {
            0.0
        } else {
            wrong_nll / wrong_count as f64
        },
        wrong_count,
        wrong_confidence: if wrong_count == 0 {
            0.0
        } else {
            wrong_confidence / wrong_count as f64
        },
    }
}

fn accuracy(model: &Model, samples: &[Sample]) -> f64 {
    score(model, samples).accuracy
}

fn write_results(output: &Path) -> io::Result<()> {
    let mut file = BufWriter::new(File::create(output.join("RESULTS.md"))?);
    writeln!(file, "# AR-04D addendum")?;
    writeln!(file)?;
    writeln!(
        file,
        "This is a read-only descriptive analysis of sealed AR-04D artifacts. It does not alter AR-04D or authorize AR-04E."
    )?;
    writeln!(file)?;
    writeln!(
        file,
        "Outputs: `calibration.csv`, `contamination-gaps.csv`, and `blocked-boundaries.csv`. Calibration uses the untouched 4,096-example population reference, fixed 10-bin ECE, Brier score, correct/wrong NLL, and wrong-case confidence. Block-boundary rows are reconstructed from the sealed decision stream."
    )?;
    file.flush()
}

fn invalid_manifest<E>(_: E) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "invalid manifest field")
}

use std::mem::size_of;
