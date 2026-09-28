use std::fs::{self, File};
use std::io::{self, BufWriter, Seek, Write};
use std::path::{Path, PathBuf};
use std::process::Command;

use bytemuck::cast_slice;
use sha2::{Digest, Sha256};

use crate::analysis;
use crate::model::{self, Sample, TRAIN_SAMPLES};
use crate::protocol::{self, Arm};
use crate::runtime::{Checkpoint, Decision};

const PARENT_COMMIT: &str = "c6daf025d3db08908a5a16bd2e0ee50e69c08787";
const EXPECTED_BRANCH: &str = "codex/ar-04c-sentinel-reuse-20260921";

pub struct DatasetBundle {
    pub train: [Sample; TRAIN_SAMPLES],
    pub measurement_path: PathBuf,
    pub fixed_panel: [Sample; protocol::PANEL_SIZE],
}

pub struct RunReport {
    pub cells: usize,
    pub trajectories: usize,
    pub decisions: usize,
    pub rotating_panels: usize,
}

pub fn run(output_dir: &Path) -> io::Result<RunReport> {
    validate_source(output_dir)?;
    fs::create_dir_all(output_dir.join("data"))?;
    let (datasets, rotating_panels) = generate_data(output_dir)?;

    let mut decisions = BufWriter::new(File::create(output_dir.join("trajectory-decisions.csv"))?);
    writeln!(
        decisions,
        "cell_id,arm,step,evidence_round,panel_hash,verifier_size,proposal_hash,schedule_offset,selected,left_parameter,right_parameter,left_delta,right_delta,program_len,verifier_utility,training_utility"
    )?;
    let mut checkpoints = Vec::with_capacity(protocol::CELL_COUNT * Arm::ALL.len() * 4);
    let mut trajectory_count = 0;
    for cell_id in 0..protocol::CELL_COUNT {
        let dataset_id = cell_id / protocol::INITIALIZATION_COUNT;
        let initialization_seed =
            protocol::initialization_seed(cell_id % protocol::INITIALIZATION_COUNT);
        let stream_seed = protocol::stream_seed(cell_id);
        for arm in Arm::ALL {
            let trajectory = crate::runtime::run_arm(
                cell_id,
                &datasets[dataset_id].train,
                initialization_seed,
                stream_seed,
                arm,
                &datasets[cell_id].fixed_panel,
            );
            write_decisions(&mut decisions, &trajectory.decisions)?;
            checkpoints.extend_from_slice(&trajectory.checkpoints);
            trajectory_count += 1;
        }
    }
    decisions.flush()?;
    write_checkpoint_artifacts(output_dir, &checkpoints)?;
    analysis::analyze(output_dir, &datasets, &checkpoints)?;
    write_integrity_receipt(output_dir, &datasets, &checkpoints, rotating_panels)?;
    Ok(RunReport {
        cells: protocol::CELL_COUNT,
        trajectories: trajectory_count,
        decisions: trajectory_count * protocol::RUNTIME_STEPS,
        rotating_panels,
    })
}

fn validate_source(output_dir: &Path) -> io::Result<()> {
    if output_dir.exists() {
        return Err(io::Error::new(
            io::ErrorKind::AlreadyExists,
            format!(
                "refusing to overwrite AR-04C output {}",
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
            "AR-04C preflight failed: branch={branch}, commit={commit}, merge_base={parent}, dirty={dirty:?}"
        )));
    }
    Ok(())
}

fn generate_data(output_dir: &Path) -> io::Result<(Vec<DatasetBundle>, usize)> {
    let mut datasets = Vec::with_capacity(protocol::CELL_COUNT);
    let mut rows = hashbrown::HashSet::<[u32; 9]>::new();
    let mut dataset_manifest =
        BufWriter::new(File::create(output_dir.join("dataset-manifest.csv"))?);
    let mut fixed_manifest =
        BufWriter::new(File::create(output_dir.join("fixed-panel-manifest.csv"))?);
    let mut rotating_manifest = BufWriter::new(File::create(
        output_dir.join("rotating-panel-manifest.csv"),
    )?);
    writeln!(dataset_manifest, "dataset_id,kind,seed,samples,path,sha256")?;
    writeln!(
        fixed_manifest,
        "cell_id,dataset_id,initialization_id,seed_a,seed_b,order_seed,samples,path,sha256"
    )?;
    writeln!(
        rotating_manifest,
        "cell_id,dataset_id,initialization_id,evidence_round,seed_a,seed_b,order_seed,samples,fingerprint"
    )?;

    for dataset_id in 0..protocol::DATASET_COUNT {
        let train = model::generate_dataset(protocol::training_seed(dataset_id));
        let measurement = model::generate_dataset(protocol::measurement_seed(dataset_id));
        insert_samples(&mut rows, &train)?;
        insert_samples(&mut rows, &measurement)?;
        let train_path = output_dir.join(format!("data/training-{dataset_id:02}.bin"));
        let measurement_path =
            output_dir.join(format!("data/final-measurement-{dataset_id:02}.bin"));
        let train_hash = write_samples(&train_path, &train)?;
        let measurement_hash = write_samples(&measurement_path, &measurement)?;
        writeln!(
            dataset_manifest,
            "{dataset_id},training,{:016x},{TRAIN_SAMPLES},{},{}",
            protocol::training_seed(dataset_id),
            train_path.strip_prefix(output_dir).unwrap().display(),
            train_hash
        )?;
        writeln!(
            dataset_manifest,
            "{dataset_id},final_measurement,{:016x},{TRAIN_SAMPLES},{},{}",
            protocol::measurement_seed(dataset_id),
            measurement_path.strip_prefix(output_dir).unwrap().display(),
            measurement_hash
        )?;

        for initialization_id in 0..protocol::INITIALIZATION_COUNT {
            let cell_id = dataset_id * protocol::INITIALIZATION_COUNT + initialization_id;
            let fixed = protocol::panel_from_seeds(
                protocol::fixed_draw_seed(cell_id, 0),
                protocol::fixed_draw_seed(cell_id, 1),
                protocol::fixed_order_seed(cell_id),
            );
            insert_samples(&mut rows, &fixed)?;
            let fixed_path = output_dir.join(format!("data/fixed-cell-{cell_id:02}.bin"));
            let fixed_hash = write_samples(&fixed_path, &fixed)?;
            writeln!(
                fixed_manifest,
                "{cell_id},{dataset_id},{initialization_id},{:016x},{:016x},{:016x},{},{},{}",
                protocol::fixed_draw_seed(cell_id, 0),
                protocol::fixed_draw_seed(cell_id, 1),
                protocol::fixed_order_seed(cell_id),
                protocol::PANEL_SIZE,
                fixed_path.strip_prefix(output_dir).unwrap().display(),
                fixed_hash
            )?;
            datasets.push(DatasetBundle {
                train,
                measurement_path: measurement_path.clone(),
                fixed_panel: fixed,
            });
        }
    }

    let mut rotating_count = 0;
    for cell_id in 0..protocol::CELL_COUNT {
        let dataset_id = cell_id / protocol::INITIALIZATION_COUNT;
        let initialization_id = cell_id % protocol::INITIALIZATION_COUNT;
        for round in 0..protocol::EVIDENCE_ROUNDS {
            let panel = protocol::rotating_panel(cell_id, round);
            insert_samples(&mut rows, &panel)?;
            writeln!(
                rotating_manifest,
                "{cell_id},{dataset_id},{initialization_id},{round},{:016x},{:016x},{:016x},{},{}",
                protocol::rotating_draw_seed(cell_id, round, 0),
                protocol::rotating_draw_seed(cell_id, round, 1),
                protocol::rotating_order_seed(cell_id, round),
                protocol::PANEL_SIZE,
                protocol::sample_fingerprint(&panel)
            )?;
            rotating_count += 1;
        }
    }
    dataset_manifest.flush()?;
    fixed_manifest.flush()?;
    rotating_manifest.flush()?;
    Ok((datasets, rotating_count))
}

fn insert_samples(set: &mut hashbrown::HashSet<[u32; 9]>, samples: &[Sample]) -> io::Result<()> {
    for sample in samples {
        if !set.insert(sample_key(sample)) {
            return Err(io::Error::other(
                "AR-04C duplicate sample row across declared pools",
            ));
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

fn write_decisions(output: &mut BufWriter<File>, rows: &[Decision]) -> io::Result<()> {
    for row in rows {
        writeln!(
            output,
            "{},{},{},{},{:016x},{},{:016x},{},{},{},{},{:.9},{:.9},{},{:.12e},{:.12e}",
            row.cell_id,
            row.arm.name(),
            row.step,
            row.evidence_round,
            row.panel_hash,
            row.verifier_size,
            row.proposal_hash,
            row.schedule_offset,
            row.selected,
            row.left_parameter,
            row.right_parameter,
            row.left_delta,
            row.right_delta,
            row.program_len,
            row.verifier_utility,
            row.training_utility
        )?;
    }
    Ok(())
}

fn write_checkpoint_artifacts(output_dir: &Path, checkpoints: &[Checkpoint]) -> io::Result<()> {
    let mut manifest = BufWriter::new(File::create(output_dir.join("checkpoint-manifest.csv"))?);
    let mut models = BufWriter::new(File::create(output_dir.join("checkpoint-models.bin"))?);
    writeln!(
        manifest,
        "cell_id,arm,step,train_loss,parameter_offset,parameter_count"
    )?;
    for checkpoint in checkpoints {
        let offset = models.stream_position()?;
        for parameter in checkpoint.model.parameters {
            models.write_all(&parameter.to_le_bytes())?;
        }
        writeln!(
            manifest,
            "{},{},{},{:.12e},{},{}",
            checkpoint.cell_id,
            checkpoint.arm.name(),
            checkpoint.step,
            checkpoint.train_loss,
            offset,
            crate::model::PARAMS
        )?;
    }
    manifest.flush()?;
    models.flush()
}

fn write_integrity_receipt(
    output_dir: &Path,
    datasets: &[DatasetBundle],
    checkpoints: &[Checkpoint],
    rotating_panels: usize,
) -> io::Result<()> {
    if datasets.len() != protocol::CELL_COUNT {
        return Err(io::Error::other(
            "AR-04C dataset bundle cardinality mismatch",
        ));
    }
    let output_files = [
        "dataset-manifest.csv",
        "fixed-panel-manifest.csv",
        "rotating-panel-manifest.csv",
        "trajectory-decisions.csv",
        "checkpoint-manifest.csv",
        "checkpoint-models.bin",
        "checkpoint-action-scores.csv",
        "ranking-metrics.csv",
        "checkpoint-outcomes.csv",
        "cell-contrasts.csv",
        "summary.json",
    ];
    let executable = std::env::current_exe()?;
    let mut output = BufWriter::new(File::create(output_dir.join("integrity-receipt.json"))?);
    writeln!(output, "{{")?;
    writeln!(
        output,
        "  \"protocol\": \"AR-04C-sentinel-reuse-2026-09-21\","
    )?;
    writeln!(
        output,
        "  \"source_commit\": \"{}\",",
        git_output(&["rev-parse", "HEAD"])?
    )?;
    writeln!(
        output,
        "  \"optimized_executable_sha256\": \"{}\",",
        hex(&sha256_file(&executable)?)
    )?;
    writeln!(output, "  \"integrity_valid\": true,")?;
    writeln!(
        output,
        "  \"cells\": {}, \"checkpoints\": {}, \"rotating_panels\": {},",
        protocol::CELL_COUNT,
        checkpoints.len(),
        rotating_panels
    )?;
    writeln!(
        output,
        "  \"datasets\": {}, \"all_role_seeds_unique\": {},",
        protocol::DATASET_COUNT,
        protocol::seeds_are_unique_and_namespaced()
    )?;
    writeln!(output, "  \"derived_output_sha256\": [")?;
    let mut first = true;
    for relative in output_files {
        let path = output_dir.join(relative);
        if !path.exists() {
            continue;
        }
        if !first {
            writeln!(output, ",")?;
        }
        first = false;
        write!(
            output,
            "    {{\"path\":\"{relative}\",\"sha256\":\"{}\"}}",
            hex(&sha256_file(&path)?)
        )?;
    }
    writeln!(output, "\n  ]\n}}")?;
    output.flush()
}

fn git_output(arguments: &[&str]) -> io::Result<String> {
    let output = Command::new("git").args(arguments).output()?;
    if !output.status.success() {
        return Err(io::Error::other(format!(
            "git {} failed",
            arguments.join(" ")
        )));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn sha256_file(path: &Path) -> io::Result<[u8; 32]> {
    let bytes = fs::read(path)?;
    Ok(Sha256::digest(bytes).into())
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}
