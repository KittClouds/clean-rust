use std::fs::{self, File};
use std::io::{self, BufWriter, Seek, Write};
use std::path::Path;
use std::process::Command;

use bytemuck::cast_slice;
use sha2::{Digest, Sha256};

use crate::analysis;
use crate::model::{self, Sample, TRAIN_SAMPLES};
use crate::protocol::{self, Arm};
use crate::runtime::{Checkpoint, Decision};

const PARENT_COMMIT: &str = "b932975cca2e792d325a92f53a60f4a41741c6fa";
const EXPECTED_BRANCH: &str = "codex/ar-04d-sentinel-exposure-frontier-20260926";

pub struct DatasetBundle {
    pub train: [Sample; TRAIN_SAMPLES],
    pub final_measurement: [Sample; TRAIN_SAMPLES],
    pub population: Vec<Sample>,
}

pub struct CellData {
    pub train: [Sample; TRAIN_SAMPLES],
    pub final_measurement: [Sample; TRAIN_SAMPLES],
    pub population: Vec<Sample>,
    pub panel_bank: Vec<[Sample; protocol::PANEL_SIZE]>,
    pub pooled_panel: Vec<Sample>,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct Exposure {
    pub decisions: usize,
    pub scored_candidates: usize,
}

#[derive(Clone, Copy, Debug)]
pub struct Outcome {
    pub cell_id: usize,
    pub dataset_id: usize,
    pub initialization_id: usize,
    pub arm: Arm,
    pub step: usize,
    pub train_loss: f32,
    pub final_loss: f32,
    pub final_accuracy: f32,
    pub population_loss: f32,
    pub population_accuracy: f32,
    pub operational_loss: f32,
    pub operational_gap: f32,
    pub verifier_size: usize,
    pub support_size: usize,
    pub panel_id: usize,
}

pub struct RunReport {
    pub cells: usize,
    pub trajectories: usize,
    pub decisions: usize,
    pub master_panels: usize,
    pub population_size: usize,
}

pub fn run(output_dir: &Path) -> io::Result<RunReport> {
    validate_source(output_dir)?;
    fs::create_dir_all(output_dir.join("data"))?;

    let mut sample_rows = hashbrown::HashSet::<[u32; 9]>::new();
    let datasets = generate_datasets(output_dir, &mut sample_rows)?;
    let mut panel_manifest = BufWriter::new(File::create(output_dir.join("panel-manifest.csv"))?);
    let mut pooled_manifest =
        BufWriter::new(File::create(output_dir.join("pooled-panel-manifest.csv"))?);
    writeln!(
        panel_manifest,
        "cell_id,dataset_id,initialization_id,panel_id,seed_a,seed_b,order_seed,samples,fingerprint"
    )?;
    writeln!(
        pooled_manifest,
        "cell_id,dataset_id,initialization_id,source_first_panel,source_panel_count,samples,fingerprint"
    )?;

    let mut decisions = BufWriter::new(File::create(output_dir.join("trajectory-decisions.csv"))?);
    writeln!(
        decisions,
        "cell_id,arm,step,evidence_round,panel_id,panel_hash,verifier_size,support_size,scored_candidates,proposal_hash,schedule_offset,selected,left_parameter,right_parameter,left_delta,right_delta,program_len,verifier_utility,training_utility"
    )?;
    let mut checkpoint_manifest =
        BufWriter::new(File::create(output_dir.join("checkpoint-manifest.csv"))?);
    let mut checkpoint_models =
        BufWriter::new(File::create(output_dir.join("checkpoint-models.bin"))?);
    writeln!(
        checkpoint_manifest,
        "cell_id,arm,step,train_loss,model_offset,model_bytes"
    )?;
    let mut outcomes_writer =
        BufWriter::new(File::create(output_dir.join("checkpoint-outcomes.csv"))?);
    writeln!(
        outcomes_writer,
        "cell_id,dataset_id,initialization_id,arm,step,train_loss,final_loss,final_accuracy,population_loss,population_accuracy,operational_loss,operational_gap,verifier_size,support_size,panel_id"
    )?;

    let mut outcomes = Vec::with_capacity(protocol::CELL_COUNT * Arm::ALL.len() * 4);
    let exposure_len = protocol::CELL_COUNT * Arm::ALL.len() * protocol::MASTER_PANEL_COUNT;
    let mut exposures = vec![Exposure::default(); exposure_len];
    let mut trajectory_count = 0;

    for cell_id in 0..protocol::CELL_COUNT {
        let dataset_id = cell_id / protocol::INITIALIZATION_COUNT;
        let initialization_id = cell_id % protocol::INITIALIZATION_COUNT;
        let data = &datasets[dataset_id];
        let cell = generate_cell_data(
            output_dir,
            cell_id,
            dataset_id,
            initialization_id,
            data,
            &mut sample_rows,
            &mut panel_manifest,
            &mut pooled_manifest,
        )?;
        let initialization_seed = protocol::initialization_seed(initialization_id);
        let stream_seed = protocol::stream_seed(cell_id);

        for (arm_index, arm) in Arm::ALL.into_iter().enumerate() {
            let trajectory = crate::runtime::run_arm(
                cell_id,
                &cell.train,
                initialization_seed,
                stream_seed,
                arm,
                &cell.panel_bank,
                &cell.pooled_panel,
            );
            write_decisions(&mut decisions, &trajectory.decisions)?;
            update_exposures(&mut exposures, &trajectory.decisions, arm_index);
            for checkpoint in &trajectory.checkpoints {
                write_checkpoint(&mut checkpoint_manifest, &mut checkpoint_models, checkpoint)?;
                let outcome =
                    make_outcome(&cell, cell_id, dataset_id, initialization_id, checkpoint);
                write_outcome(&mut outcomes_writer, &outcome)?;
                outcomes.push(outcome);
            }
            trajectory_count += 1;
        }
    }
    panel_manifest.flush()?;
    pooled_manifest.flush()?;
    decisions.flush()?;
    checkpoint_manifest.flush()?;
    checkpoint_models.flush()?;
    outcomes_writer.flush()?;
    write_exposure_summary(output_dir, &exposures)?;
    analysis::analyze(output_dir, &outcomes, &exposures)?;
    write_integrity_receipt(output_dir, &outcomes, &exposures, sample_rows.len())?;

    Ok(RunReport {
        cells: protocol::CELL_COUNT,
        trajectories: trajectory_count,
        decisions: trajectory_count * protocol::RUNTIME_STEPS,
        master_panels: protocol::CELL_COUNT * protocol::MASTER_PANEL_COUNT,
        population_size: protocol::POPULATION_SIZE,
    })
}

fn validate_source(output_dir: &Path) -> io::Result<()> {
    if output_dir.exists() {
        return Err(io::Error::new(
            io::ErrorKind::AlreadyExists,
            format!(
                "refusing to overwrite AR-04D output {}",
                output_dir.display()
            ),
        ));
    }
    let branch = git_output(&["rev-parse", "--abbrev-ref", "HEAD"])?;
    let commit = git_output(&["rev-parse", "HEAD"])?;
    let parent = git_output(&["merge-base", PARENT_COMMIT, "HEAD"])?;
    let dirty = git_output(&["status", "--porcelain"])?;
    if branch != EXPECTED_BRANCH
        || commit.is_empty()
        || parent != PARENT_COMMIT
        || !dirty.is_empty()
        || !protocol::seeds_are_unique_and_namespaced()
    {
        return Err(io::Error::other(format!(
            "AR-04D preflight failed: branch={branch}, commit={commit}, merge_base={parent}, dirty={dirty:?}"
        )));
    }
    Ok(())
}

fn generate_datasets(
    output_dir: &Path,
    rows: &mut hashbrown::HashSet<[u32; 9]>,
) -> io::Result<Vec<DatasetBundle>> {
    let mut datasets = Vec::with_capacity(protocol::DATASET_COUNT);
    let mut manifest = BufWriter::new(File::create(output_dir.join("dataset-manifest.csv"))?);
    writeln!(manifest, "dataset_id,kind,seed,samples,path,sha256")?;

    for dataset_id in 0..protocol::DATASET_COUNT {
        let train = model::generate_dataset(protocol::training_seed(dataset_id));
        let final_measurement = model::generate_dataset(protocol::measurement_seed(dataset_id));
        let mut population = Vec::with_capacity(protocol::POPULATION_SIZE);
        for chunk in 0..protocol::POPULATION_CHUNKS {
            population.extend(model::generate_dataset(protocol::population_seed(
                dataset_id, chunk,
            )));
        }
        population.truncate(protocol::POPULATION_SIZE);
        insert_samples(rows, &train, "training")?;
        insert_samples(rows, &final_measurement, "final measurement")?;
        insert_samples(rows, &population, "population reference")?;

        let train_path = output_dir.join(format!("data/training-{dataset_id:02}.bin"));
        let final_path = output_dir.join(format!("data/final-measurement-{dataset_id:02}.bin"));
        let population_path = output_dir.join(format!("data/population-{dataset_id:02}.bin"));
        let train_hash = write_samples(&train_path, &train)?;
        let final_hash = write_samples(&final_path, &final_measurement)?;
        let population_hash = write_samples(&population_path, &population)?;
        writeln!(
            manifest,
            "{dataset_id},training,{:016x},{TRAIN_SAMPLES},{},{}",
            protocol::training_seed(dataset_id),
            train_path.strip_prefix(output_dir).unwrap().display(),
            train_hash
        )?;
        writeln!(
            manifest,
            "{dataset_id},final_measurement,{:016x},{TRAIN_SAMPLES},{},{}",
            protocol::measurement_seed(dataset_id),
            final_path.strip_prefix(output_dir).unwrap().display(),
            final_hash
        )?;
        writeln!(
            manifest,
            "{dataset_id},population_reference,{:016x},{},{},{}",
            protocol::population_seed(dataset_id, 0),
            protocol::POPULATION_SIZE,
            population_path.strip_prefix(output_dir).unwrap().display(),
            population_hash
        )?;
        datasets.push(DatasetBundle {
            train,
            final_measurement,
            population,
        });
    }
    manifest.flush()?;
    Ok(datasets)
}

#[allow(clippy::too_many_arguments)]
fn generate_cell_data(
    output_dir: &Path,
    cell_id: usize,
    dataset_id: usize,
    initialization_id: usize,
    data: &DatasetBundle,
    rows: &mut hashbrown::HashSet<[u32; 9]>,
    panel_manifest: &mut BufWriter<File>,
    pooled_manifest: &mut BufWriter<File>,
) -> io::Result<CellData> {
    let mut panel_bank = Vec::with_capacity(protocol::MASTER_PANEL_COUNT);
    for panel_id in 0..protocol::MASTER_PANEL_COUNT {
        let panel = protocol::panel_from_seeds(
            protocol::panel_draw_seed(cell_id, panel_id, 0),
            protocol::panel_draw_seed(cell_id, panel_id, 1),
            protocol::panel_order_seed(cell_id, panel_id),
        );
        insert_samples(rows, &panel, "sentinel panel")?;
        writeln!(
            panel_manifest,
            "{cell_id},{dataset_id},{initialization_id},{panel_id},{:016x},{:016x},{:016x},{},{:016x}",
            protocol::panel_draw_seed(cell_id, panel_id, 0),
            protocol::panel_draw_seed(cell_id, panel_id, 1),
            protocol::panel_order_seed(cell_id, panel_id),
            protocol::PANEL_SIZE,
            protocol::sample_fingerprint(&panel)
        )?;
        panel_bank.push(panel);
    }
    let mut pooled_panel = Vec::with_capacity(protocol::POOLED_PANEL_SIZE);
    for panel in panel_bank.iter().take(protocol::POOLED_PANEL_COUNT) {
        pooled_panel.extend_from_slice(panel);
    }
    writeln!(
        pooled_manifest,
        "{cell_id},{dataset_id},{initialization_id},0,{},{},{:016x}",
        protocol::POOLED_PANEL_COUNT,
        protocol::POOLED_PANEL_SIZE,
        protocol::sample_fingerprint(&pooled_panel)
    )?;
    let _ = output_dir;
    Ok(CellData {
        train: data.train,
        final_measurement: data.final_measurement,
        population: data.population.clone(),
        panel_bank,
        pooled_panel,
    })
}

fn make_outcome(
    cell: &CellData,
    cell_id: usize,
    dataset_id: usize,
    initialization_id: usize,
    checkpoint: &Checkpoint,
) -> Outcome {
    let evidence_round = if checkpoint.step == 0 {
        0
    } else {
        checkpoint.step / protocol::COMMITS_PER_EVIDENCE - 1
    };
    let panel_id = protocol::panel_id_for_round(checkpoint.arm, evidence_round);
    let operational: &[Sample] = if checkpoint.arm.is_pooled() {
        &cell.pooled_panel
    } else {
        &cell.panel_bank[panel_id]
    };
    let final_loss = checkpoint.model.loss(&cell.final_measurement);
    let population_loss = checkpoint.model.loss(&cell.population);
    let operational_loss = checkpoint.model.loss(operational);
    Outcome {
        cell_id,
        dataset_id,
        initialization_id,
        arm: checkpoint.arm,
        step: checkpoint.step,
        train_loss: checkpoint.train_loss,
        final_loss,
        final_accuracy: accuracy(&checkpoint.model, &cell.final_measurement),
        population_loss,
        population_accuracy: accuracy(&checkpoint.model, &cell.population),
        operational_loss,
        operational_gap: operational_loss - final_loss,
        verifier_size: operational.len(),
        support_size: checkpoint.arm.support_size(evidence_round),
        panel_id,
    }
}

fn accuracy(model: &model::Model, samples: &[Sample]) -> f32 {
    let correct = samples
        .iter()
        .filter(|sample| {
            let logits = model.logits(sample).0;
            let predicted = logits
                .iter()
                .enumerate()
                .max_by(|left, right| left.1.total_cmp(right.1))
                .map_or(0, |(index, _)| index) as u32;
            predicted == sample.target
        })
        .count();
    correct as f32 / samples.len() as f32
}

fn update_exposures(exposures: &mut [Exposure], decisions: &[Decision], arm_index: usize) {
    for decision in decisions {
        let index = (decision.cell_id * Arm::ALL.len() + arm_index) * protocol::MASTER_PANEL_COUNT
            + decision.panel_id;
        exposures[index].decisions += 1;
        exposures[index].scored_candidates += usize::from(decision.scored_candidates);
    }
}

fn write_decisions(output: &mut BufWriter<File>, rows: &[Decision]) -> io::Result<()> {
    for row in rows {
        writeln!(
            output,
            "{},{},{},{},{},{:016x},{},{},{},{:016x},{},{},{},{},{:.9},{:.9},{},{:.12e},{:.12e}",
            row.cell_id,
            row.arm.name(),
            row.step,
            row.evidence_round,
            row.panel_id,
            row.panel_hash,
            row.verifier_size,
            row.support_size,
            row.scored_candidates,
            row.proposal_hash,
            row.schedule_offset,
            row.selected,
            row.left_parameter,
            row.right_parameter,
            row.left_delta,
            row.right_delta,
            row.program_len,
            row.verifier_utility,
            row.training_utility,
        )?;
    }
    Ok(())
}

fn write_checkpoint(
    manifest: &mut BufWriter<File>,
    models: &mut BufWriter<File>,
    checkpoint: &Checkpoint,
) -> io::Result<()> {
    let offset = models.stream_position()?;
    let bytes = cast_slice(&checkpoint.model.parameters);
    models.write_all(bytes)?;
    writeln!(
        manifest,
        "{},{},{},{:.9},{},{}",
        checkpoint.cell_id,
        checkpoint.arm.name(),
        checkpoint.step,
        checkpoint.train_loss,
        offset,
        bytes.len()
    )?;
    Ok(())
}

fn write_outcome(output: &mut BufWriter<File>, row: &Outcome) -> io::Result<()> {
    writeln!(
        output,
        "{},{},{},{},{},{:.9},{:.9},{:.9},{:.9},{:.9},{:.9},{:.9},{},{},{}",
        row.cell_id,
        row.dataset_id,
        row.initialization_id,
        row.arm.name(),
        row.step,
        row.train_loss,
        row.final_loss,
        row.final_accuracy,
        row.population_loss,
        row.population_accuracy,
        row.operational_loss,
        row.operational_gap,
        row.verifier_size,
        row.support_size,
        row.panel_id,
    )?;
    Ok(())
}

fn write_exposure_summary(output_dir: &Path, exposures: &[Exposure]) -> io::Result<()> {
    let mut output = BufWriter::new(File::create(output_dir.join("exposure-summary.csv"))?);
    writeln!(
        output,
        "cell_id,arm,panel_id,scheduled_rounds,decision_count,scored_candidates,verifier_size,support_size"
    )?;
    for cell_id in 0..protocol::CELL_COUNT {
        for (arm_index, arm) in Arm::ALL.into_iter().enumerate() {
            for panel_id in 0..protocol::MASTER_PANEL_COUNT {
                let index = (cell_id * Arm::ALL.len() + arm_index) * protocol::MASTER_PANEL_COUNT
                    + panel_id;
                let expected = expected_rounds(arm, panel_id);
                let exposure = exposures[index];
                if expected == 0 && exposure.decisions == 0 {
                    continue;
                }
                writeln!(
                    output,
                    "{cell_id},{},{panel_id},{expected},{},{},{},{}",
                    arm.name(),
                    exposure.decisions,
                    exposure.scored_candidates,
                    if arm.is_pooled() {
                        protocol::POOLED_PANEL_SIZE
                    } else {
                        protocol::PANEL_SIZE
                    },
                    arm.support_size(panel_id.min(protocol::EVIDENCE_ROUNDS - 1)),
                )?;
            }
        }
    }
    output.flush()
}

fn expected_rounds(arm: Arm, panel_id: usize) -> usize {
    match arm {
        Arm::SentinelK1 => usize::from(panel_id == 0) * protocol::EVIDENCE_ROUNDS,
        Arm::SentinelK4Cyclic => {
            if panel_id < 4 {
                protocol::cyclic_exposure_count(panel_id, 4)
            } else {
                0
            }
        }
        Arm::SentinelK16Cyclic => {
            if panel_id < 16 {
                protocol::cyclic_exposure_count(panel_id, 16)
            } else {
                0
            }
        }
        Arm::SentinelK16Pooled => usize::from(panel_id == 0) * protocol::EVIDENCE_ROUNDS,
        Arm::SentinelK16Blocked => {
            if panel_id < 16 {
                protocol::blocked_exposure_count(panel_id)
            } else {
                0
            }
        }
        Arm::SentinelK64Cyclic => {
            if panel_id < 64 {
                protocol::cyclic_exposure_count(panel_id, 64)
            } else {
                0
            }
        }
        Arm::SentinelFresh => usize::from(panel_id < protocol::EVIDENCE_ROUNDS),
    }
}

fn insert_samples(
    set: &mut hashbrown::HashSet<[u32; 9]>,
    samples: &[Sample],
    role: &str,
) -> io::Result<()> {
    for sample in samples {
        if !set.insert(sample_key(sample)) {
            return Err(io::Error::other(format!(
                "AR-04D duplicate sample row across declared pools: {role}"
            )));
        }
    }
    Ok(())
}

fn sample_key(sample: &Sample) -> [u32; 9] {
    let mut key = [0_u32; 9];
    for (slot, value) in key[..8].iter_mut().zip(sample.x) {
        *slot = value.to_bits();
    }
    key[8] = sample.target;
    key
}

fn write_samples(path: &Path, samples: &[Sample]) -> io::Result<String> {
    fs::write(path, cast_slice(samples))?;
    Ok(hex(&sha256_file(path)?))
}

fn write_integrity_receipt(
    output_dir: &Path,
    outcomes: &[Outcome],
    exposures: &[Exposure],
    unique_rows: usize,
) -> io::Result<()> {
    let commit = git_output(&["rev-parse", "HEAD"])?;
    let mut files = Vec::new();
    for entry in fs::read_dir(output_dir)? {
        let entry = entry?;
        if entry.path().is_file() {
            files.push((
                entry.file_name().to_string_lossy().into_owned(),
                sha256_file(&entry.path())?,
            ));
        }
    }
    let mut output = BufWriter::new(File::create(output_dir.join("integrity-receipt.json"))?);
    writeln!(output, "{{")?;
    writeln!(
        output,
        "  \"protocol\": \"AR-04D-sentinel-exposure-2026-09-26\","
    )?;
    writeln!(output, "  \"source_commit\": \"{commit}\",")?;
    writeln!(output, "  \"cells\": {},", protocol::CELL_COUNT)?;
    writeln!(output, "  \"arms\": {},", Arm::ALL.len())?;
    writeln!(
        output,
        "  \"trajectories\": {},",
        protocol::CELL_COUNT * Arm::ALL.len()
    )?;
    writeln!(
        output,
        "  \"decisions\": {},",
        protocol::CELL_COUNT * Arm::ALL.len() * protocol::RUNTIME_STEPS
    )?;
    writeln!(output, "  \"checkpoints\": {},", outcomes.len())?;
    writeln!(
        output,
        "  \"master_panels\": {},",
        protocol::CELL_COUNT * protocol::MASTER_PANEL_COUNT
    )?;
    writeln!(
        output,
        "  \"population_size_per_dataset\": {},",
        protocol::POPULATION_SIZE
    )?;
    writeln!(output, "  \"unique_sample_rows\": {},", unique_rows)?;
    writeln!(output, "  \"exposure_slots\": {},", exposures.len())?;
    writeln!(output, "  \"integrity_valid\": true,")?;
    writeln!(output, "  \"files\": {{")?;
    for (index, (name, hash)) in files.iter().enumerate() {
        let comma = if index + 1 == files.len() { "" } else { "," };
        writeln!(output, "    \"{name}\": \"{}\"{comma}", hex(hash))?;
    }
    writeln!(output, "  }}")?;
    writeln!(output, "}}")?;
    output.flush()
}

fn git_output(arguments: &[&str]) -> io::Result<String> {
    let output = Command::new("git").args(arguments).output()?;
    if !output.status.success() {
        return Err(io::Error::other(format!("git {:?} failed", arguments)));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn sha256_file(path: &Path) -> io::Result<[u8; 32]> {
    let bytes = fs::read(path)?;
    Ok(Sha256::digest(bytes).into())
}

fn hex(bytes: &[u8; 32]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
