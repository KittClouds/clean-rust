use crate::{
    collector::{self, EPS, ETA, REFERENCE_LR, TAU},
    graph::Graph,
    reach_sim::Sim,
    task::{Pattern, Task},
};
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, BufWriter, Write},
    path::Path,
};

const SIM_SEED_XOR: u64 = 0;
const CHECKPOINTS: [usize; 6] = [0, 512, 1024, 2048, 4096, 8192];
const RUN_ID: &str = "qualification-v2";

#[derive(Deserialize)]
struct TrainBlock {
    task_seed: u64,
    labels: Vec<bool>,
    schedule: Vec<Vec<usize>>,
    cue_count: usize,
}

#[derive(Deserialize)]
struct TrainBank {
    blocks: BTreeMap<String, TrainBlock>,
}

#[derive(Deserialize)]
struct Cell {
    cell_key: String,
    substrate: String,
    side: String,
    n_kc_mb_edges: usize,
    coordinates_per_cell: usize,
    coordinates: Vec<usize>,
    inclusion_probability: f64,
    graph_id: String,
}

#[derive(Deserialize)]
struct QualificationManifest {
    cells: Vec<Cell>,
}

#[derive(Serialize, Deserialize)]
struct SnapshotDescriptor {
    schema: String,
    snapshot_id: u32,
    graph_id: String,
    task_manifest_id: String,
    substrate: String,
    side: String,
    block: u64,
    trial: usize,
    sim_seed: u64,
    tau: f32,
    eta: f32,
    reference_lr: f64,
    pre_state_sha256: Option<String>,
    reference_vector_sha256: Option<String>,
    sample_reference_sha256: String,
    sample_target_sha256: String,
}

struct BinaryRows {
    file: BufWriter<File>,
    rows: u64,
}

impl BinaryRows {
    fn create(
        path: &Path,
        substrate: &str,
        side: &str,
        block: u64,
        coordinates: &[usize],
    ) -> Result<Self> {
        let file = OpenOptions::new().create_new(true).write(true).open(path)?;
        let mut writer = BufWriter::with_capacity(1 << 20, file);
        writer.write_all(b"FLYREACH3ROWS\0")?;
        writer.write_all(&1_u32.to_le_bytes())?;
        writer.write_all(&(substrate.len() as u16).to_le_bytes())?;
        writer.write_all(substrate.as_bytes())?;
        writer.write_all(&(side.len() as u16).to_le_bytes())?;
        writer.write_all(side.as_bytes())?;
        writer.write_all(&block.to_le_bytes())?;
        writer.write_all(&(coordinates.len() as u32).to_le_bytes())?;
        for &coordinate in coordinates {
            writer.write_all(&(coordinate as u32).to_le_bytes())?;
        }
        Ok(Self {
            file: writer,
            rows: 0,
        })
    }

    #[inline]
    fn u8(&mut self, value: u8) -> Result<()> {
        self.file.write_all(&[value])?;
        Ok(())
    }
    #[inline]
    fn i8(&mut self, value: i8) -> Result<()> {
        self.file.write_all(&[value as u8])?;
        Ok(())
    }
    #[inline]
    fn u32(&mut self, value: u32) -> Result<()> {
        self.file.write_all(&value.to_le_bytes())?;
        Ok(())
    }
    #[inline]
    fn u64(&mut self, value: u64) -> Result<()> {
        self.file.write_all(&value.to_le_bytes())?;
        Ok(())
    }
    #[inline]
    fn f32(&mut self, value: f32) -> Result<()> {
        self.file.write_all(&value.to_bits().to_le_bytes())?;
        Ok(())
    }
    #[inline]
    fn f64(&mut self, value: f64) -> Result<()> {
        self.file.write_all(&value.to_bits().to_le_bytes())?;
        Ok(())
    }

    fn f32_slice(&mut self, values: &[f32]) -> Result<()> {
        self.u8(values.len() as u8)?;
        for &value in values {
            self.f32(value)?;
        }
        Ok(())
    }

    fn i8_slice(&mut self, values: &[i8]) -> Result<()> {
        self.u8(values.len() as u8)?;
        for &value in values {
            self.i8(value)?;
        }
        Ok(())
    }

    fn row(
        &mut self,
        substrate_index: u8,
        side_index: u8,
        block: u64,
        trial: usize,
        coordinate: usize,
        inclusion_probability: f64,
        reference_value: f32,
        native_value: f32,
        target: i8,
        primary_support: bool,
        edge_pre: u32,
        edge_post: u32,
        pre_degree: usize,
        post_degree: usize,
        anatomical_sign: f32,
        weight_before: f32,
        eligibility: f32,
        presynaptic_spike_count: u32,
        postsynaptic_deviation: f32,
        local_signed: f32,
        weight_sign: i8,
        eligibility_history: &[f32],
        weight_history: &[f32],
        local_sign_history: &[i8],
        reward: f32,
        dan_mean: f32,
        feedback_mean: f32,
        gain_for_post: f32,
        scale: f32,
        eligibility_l1: f32,
        active_eligibility_fraction: f32,
        global_work: u64,
        global_events: u64,
        trial_snapshot: u32,
    ) -> Result<()> {
        self.u8(substrate_index)?;
        self.u8(side_index)?;
        self.u64(block)?;
        self.u32(trial as u32)?;
        self.u32(coordinate as u32)?;
        self.f64(inclusion_probability)?;
        self.f32(reference_value)?;
        self.i8(target)?;
        self.f32(native_value)?;
        self.u8(u8::from(primary_support))?;
        self.u32(edge_pre)?;
        self.u32(edge_post)?;
        self.u32(pre_degree as u32)?;
        self.u32(post_degree as u32)?;
        self.f32(anatomical_sign)?;
        self.f32(weight_before)?;
        self.f32(eligibility)?;
        self.u32(presynaptic_spike_count)?;
        self.f32(postsynaptic_deviation)?;
        self.f32(local_signed)?;
        self.i8(weight_sign)?;
        self.f32_slice(eligibility_history)?;
        self.f32_slice(weight_history)?;
        self.i8_slice(local_sign_history)?;
        self.f32(reward)?;
        self.f32(dan_mean)?;
        self.f32(feedback_mean)?;
        self.f32(gain_for_post)?;
        self.f32(scale)?;
        self.u8(1)?;
        self.f32(eligibility_l1)?;
        self.f32(active_eligibility_fraction)?;
        self.u64(global_work)?;
        self.u64(global_events)?;
        self.u32(trial_snapshot)?;
        self.rows += 1;
        Ok(())
    }

    fn finish(mut self) -> Result<u64> {
        self.file.flush()?;
        Ok(self.rows)
    }
}

fn digest_f32(values: &[f32]) -> String {
    let mut digest = Sha256::new();
    for &value in values {
        digest.update(value.to_bits().to_le_bytes());
    }
    format!("{:x}", digest.finalize())
}

fn digest_sample(values: &[f32], coordinates: &[usize]) -> String {
    let mut digest = Sha256::new();
    for &coordinate in coordinates {
        digest.update(values[coordinate].to_bits().to_le_bytes());
    }
    format!("{:x}", digest.finalize())
}

fn digest_targets(values: &[f32], coordinates: &[usize]) -> String {
    let mut digest = Sha256::new();
    for &coordinate in coordinates {
        digest.update([collector::target(values[coordinate]) as u8]);
    }
    format!("{:x}", digest.finalize())
}

fn pattern_sample_counts(task: &Task, coordinates: &[usize]) -> Vec<Vec<u32>> {
    let mut counts = vec![vec![0_u32; coordinates.len()]; task.patterns.len()];
    let mut positions = hashbrown::HashMap::with_capacity(coordinates.len());
    for (position, &coordinate) in coordinates.iter().enumerate() {
        positions.insert(coordinate, position);
    }
    for (pattern_index, pattern) in task.patterns.iter().enumerate() {
        for &edge in &pattern.edges {
            if let Some(&position) = positions.get(&edge) {
                counts[pattern_index][position] += 1;
            }
        }
    }
    counts
}

fn write_descriptor(file: &mut BufWriter<File>, descriptor: &SnapshotDescriptor) -> Result<()> {
    serde_json::to_writer(&mut *file, descriptor)?;
    file.write_all(b"\n")?;
    Ok(())
}

fn collect_cell(
    graph: &Graph,
    block_id: u64,
    train: &TrainBlock,
    cell: &Cell,
    rows_path: &Path,
    snapshots_path: &Path,
    substrate_index: u8,
    side_index: u8,
) -> Result<(u64, u64)> {
    ensure!(train.cue_count == train.labels.len());
    ensure!(cell.n_kc_mb_edges == graph.kc_mb.edges.len());
    ensure!(cell.coordinates_per_cell == cell.coordinates.len());
    let task = Task::new(
        graph,
        train.task_seed,
        train.labels.clone(),
        train.schedule.clone(),
    );
    let mut sim = Sim::new(graph, train.task_seed ^ SIM_SEED_XOR, TAU, ETA);
    let mut local_abs = vec![0.0; sim.weights.len()];
    let mut local_signed = vec![0.0; sim.weights.len()];
    let mut native_delta = vec![0.0; sim.weights.len()];
    let mut reference = vec![0.0; sim.weights.len()];
    let mut grad = vec![0.0; sim.weights.len()];
    let pre_degree = collector::pre_degree(graph);
    let sample_counts = pattern_sample_counts(&task, &cell.coordinates);
    let mut eligibility_history = vec![Vec::<f32>::new(); cell.coordinates.len()];
    let mut weight_history = vec![Vec::<f32>::new(); cell.coordinates.len()];
    let mut local_sign_history = vec![Vec::<i8>::new(); cell.coordinates.len()];
    let mut rows = BinaryRows::create(
        rows_path,
        &cell.substrate,
        &cell.side,
        block_id,
        &cell.coordinates,
    )?;
    let snapshot_file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(snapshots_path)?;
    let mut snapshots = BufWriter::with_capacity(1 << 20, snapshot_file);
    let mut row_count = 0_u64;
    for trial in 0..train.schedule.len() {
        let sampled_weights: Vec<f32> = cell
            .coordinates
            .iter()
            .map(|&coordinate| sim.weights[coordinate])
            .collect();
        let (_correct, reward) =
            sim.begin_trial_with_local(&task, trial, &mut local_abs, &mut local_signed);
        collector::reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference, &mut grad);
        sim.proposed_delta_into(reward, &mut native_delta);
        let snapshot_id = trial as u32;
        let checkpoint = CHECKPOINTS.contains(&trial);
        let pre_state_sha256 = checkpoint.then(|| sim.digest());
        let reference_vector_sha256 = checkpoint.then(|| digest_f32(&reference));
        let descriptor = SnapshotDescriptor {
            schema: "FLY-REACH-03-f4-replay-descriptor-v1".to_string(),
            snapshot_id,
            graph_id: cell.graph_id.clone(),
            task_manifest_id: format!("{}:{}:{}", cell.substrate, cell.side, block_id),
            substrate: cell.substrate.clone(),
            side: cell.side.clone(),
            block: block_id,
            trial,
            sim_seed: train.task_seed ^ SIM_SEED_XOR,
            tau: TAU,
            eta: ETA,
            reference_lr: REFERENCE_LR,
            pre_state_sha256,
            reference_vector_sha256,
            sample_reference_sha256: digest_sample(&reference, &cell.coordinates),
            sample_target_sha256: digest_targets(&reference, &cell.coordinates),
        };
        write_descriptor(&mut snapshots, &descriptor)?;
        for (position, &coordinate) in cell.coordinates.iter().enumerate() {
            let edge = graph.kc_mb.edges[coordinate];
            let post = edge.post as usize;
            let weight = sampled_weights[position];
            eligibility_history[position].push(sim.eligibility[coordinate]);
            weight_history[position].push(weight);
            local_sign_history[position].push(if local_signed[coordinate] > EPS {
                1
            } else if local_signed[coordinate] < -EPS {
                -1
            } else {
                0
            });
            let hist_start = eligibility_history[position].len().saturating_sub(32);
            let weight_start = weight_history[position].len().saturating_sub(32);
            let sign_start = local_sign_history[position].len().saturating_sub(32);
            let spikes = task.schedule[trial % task.schedule.len()]
                .iter()
                .map(|&pattern| sample_counts[pattern][position])
                .sum();
            rows.row(
                substrate_index,
                side_index,
                block_id,
                trial,
                coordinate,
                cell.inclusion_probability,
                reference[coordinate],
                native_delta[coordinate],
                collector::target(reference[coordinate]),
                native_delta[coordinate].abs() > EPS,
                edge.pre,
                edge.post,
                pre_degree[edge.pre as usize],
                graph.kc_mb.row(post).len(),
                graph.mb_sign[post],
                weight,
                sim.eligibility[coordinate],
                spikes,
                sim.post[post] - sim.baseline[post],
                local_signed[coordinate],
                if weight > EPS {
                    1
                } else if weight < -EPS {
                    -1
                } else {
                    0
                },
                &eligibility_history[position][hist_start..],
                &weight_history[position][weight_start..],
                &local_sign_history[position][sign_start..],
                reward,
                sim.dan.iter().sum::<f32>() / sim.dan.len().max(1) as f32,
                sim.feedback.iter().sum::<f32>() / sim.feedback.len().max(1) as f32,
                sim.gain[post],
                sim.scale,
                sim.eligibility.iter().map(|value| value.abs()).sum(),
                sim.eligibility
                    .iter()
                    .filter(|value| value.abs() > EPS)
                    .count() as f32
                    / sim.eligibility.len().max(1) as f32,
                sim.work,
                sim.events,
                snapshot_id,
            )?;
            row_count += 1;
        }
        sim.apply_delta(&native_delta);
        ensure!(
            sim.finite(),
            "nonfinite qualification state at {cell_id} trial {trial}",
            cell_id = cell.cell_key
        );
    }
    let terminal_trial = train.schedule.len();
    collector::reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference, &mut grad);
    write_descriptor(
        &mut snapshots,
        &SnapshotDescriptor {
            schema: "FLY-REACH-03-f4-replay-descriptor-v1".to_string(),
            snapshot_id: terminal_trial as u32,
            graph_id: cell.graph_id.clone(),
            task_manifest_id: format!("{}:{}:{}", cell.substrate, cell.side, block_id),
            substrate: cell.substrate.clone(),
            side: cell.side.clone(),
            block: block_id,
            trial: terminal_trial,
            sim_seed: train.task_seed ^ SIM_SEED_XOR,
            tau: TAU,
            eta: ETA,
            reference_lr: REFERENCE_LR,
            pre_state_sha256: Some(sim.digest()),
            reference_vector_sha256: Some(digest_f32(&reference)),
            sample_reference_sha256: digest_sample(&reference, &cell.coordinates),
            sample_target_sha256: digest_targets(&reference, &cell.coordinates),
        },
    )?;
    snapshots.flush()?;
    let _ = rows.finish()?;
    Ok((row_count, train.schedule.len() as u64))
}

pub fn run(study: &Path, lineage: &Path) -> Result<()> {
    let run_root = study.join("runs").join(RUN_ID);
    ensure!(
        !run_root.exists(),
        "qualification identity already exists; preserve it and stop"
    );
    let training_path = study.join("inputs/qualification/training.json");
    let manifest_path = study.join("manifests/QUALIFICATION-MANIFEST.json");
    let training: TrainBank = serde_json::from_slice(&fs::read(&training_path)?)?;
    let manifest: QualificationManifest = serde_json::from_slice(&fs::read(&manifest_path)?)?;
    ensure!(training.blocks.len() == 4);
    ensure!(manifest.cells.len() == 18);
    fs::create_dir_all(run_root.join("rows"))?;
    fs::create_dir_all(run_root.join("f4"))?;
    let mut total_rows = 0_u64;
    let mut total_trials = 0_u64;
    for (cell_index, cell) in manifest.cells.iter().enumerate() {
        let graph = crate::graph::load(lineage, &cell.substrate, &cell.side, -1.0)
            .with_context(|| format!("load graph {}", cell.cell_key))?;
        for (block_index, (block_key, train)) in training.blocks.iter().enumerate() {
            let block_id: u64 = block_key.parse()?;
            let stem = format!("{}-{}-{}", cell.substrate, cell.side, block_id);
            let rows_path = run_root.join("rows").join(format!("{stem}.bin"));
            let snapshots_path = run_root.join("f4").join(format!("{stem}.jsonl"));
            let (rows, trials) = collect_cell(
                &graph,
                block_id,
                train,
                cell,
                &rows_path,
                &snapshots_path,
                cell_index as u8,
                if cell.side == "R" { 1 } else { 0 },
            )?;
            total_rows += rows;
            total_trials += trials;
            eprintln!(
                "qualification_cell_complete cell={}/18 block={}/4 rows={rows}",
                cell_index + 1,
                block_index + 1
            );
        }
    }
    let receipt = serde_json::json!({
        "schema": "FLY-REACH-03-qualification-collection-receipt-v1",
        "run_id": RUN_ID,
        "status": "COLLECTION_COMPLETE",
        "qualification_only": true,
        "native_only": true,
        "cells": 72,
        "rows": total_rows,
        "trials": total_trials,
        "expected_rows": 37748736_u64,
        "expected_trials": 589824_u64,
        "f4_physical_encoding": "deterministic_replay_descriptor_v1",
        "estimators_fit": false,
        "measured_namespace_created": false,
        "scientific_execution_started": false,
        "lineage_root": lineage.display().to_string(),
    });
    let receipt_path = run_root.join("QUALIFICATION-COLLECTION-RECEIPT.json");
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(receipt_path)?;
    serde_json::to_writer_pretty(&mut file, &receipt)?;
    file.write_all(b"\n")?;
    Ok(())
}

fn audit_cell(
    graph: &Graph,
    block_id: u64,
    train: &TrainBlock,
    cell: &Cell,
    snapshots_path: &Path,
) -> Result<(u64, u64)> {
    let task = Task::new(
        graph,
        train.task_seed,
        train.labels.clone(),
        train.schedule.clone(),
    );
    let mut sim = Sim::new(graph, train.task_seed ^ SIM_SEED_XOR, TAU, ETA);
    let mut native_delta = vec![0.0; sim.weights.len()];
    let mut reference = vec![0.0; sim.weights.len()];
    let mut grad = vec![0.0; sim.weights.len()];
    let file = File::open(snapshots_path)?;
    let reader = BufReader::with_capacity(1 << 20, file);
    let mut checked = 0_u64;
    let mut checkpoints = 0_u64;
    let mut descriptors = 0_u64;
    for (trial, line) in reader.lines().enumerate() {
        let line = line?;
        descriptors += 1;
        let descriptor: SnapshotDescriptor = serde_json::from_str(&line)?;
        ensure!(descriptor.trial == trial);
        ensure!(descriptor.block == block_id);
        ensure!(descriptor.substrate == cell.substrate && descriptor.side == cell.side);
        let terminal = trial == train.schedule.len();
        let reward = if terminal {
            0.0
        } else {
            let (_correct, reward) = sim.begin_trial(&task, trial);
            reward
        };
        collector::reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference, &mut grad);
        if !terminal {
            sim.proposed_delta_into(reward, &mut native_delta);
        }
        ensure!(
            digest_sample(&reference, &cell.coordinates) == descriptor.sample_reference_sha256,
            "sample reference digest mismatch at {} trial {}",
            cell.cell_key,
            trial
        );
        ensure!(
            digest_targets(&reference, &cell.coordinates) == descriptor.sample_target_sha256,
            "sample target digest mismatch at {} trial {}",
            cell.cell_key,
            trial
        );
        if CHECKPOINTS.contains(&trial) {
            ensure!(
                descriptor.pre_state_sha256.as_deref() == Some(sim.digest().as_str()),
                "pre-state digest mismatch at {} trial {}",
                cell.cell_key,
                trial
            );
            ensure!(
                descriptor.reference_vector_sha256.as_deref()
                    == Some(digest_f32(&reference).as_str()),
                "reference vector digest mismatch at {} trial {}",
                cell.cell_key,
                trial
            );
            checkpoints += 1;
        }
        if !terminal {
            sim.apply_delta(&native_delta);
            ensure!(
                sim.finite(),
                "nonfinite replay state at {} trial {}",
                cell.cell_key,
                trial
            );
            checked += 1;
        }
    }
    ensure!(
        checked == train.schedule.len() as u64,
        "snapshot count mismatch for {}",
        cell.cell_key
    );
    ensure!(
        descriptors == train.schedule.len() as u64 + 1,
        "terminal snapshot missing for {}",
        cell.cell_key
    );
    Ok((checked, checkpoints))
}

fn terminal_descriptor(
    graph: &Graph,
    block_id: u64,
    train: &TrainBlock,
    cell: &Cell,
) -> Result<SnapshotDescriptor> {
    let task = Task::new(
        graph,
        train.task_seed,
        train.labels.clone(),
        train.schedule.clone(),
    );
    let mut sim = Sim::new(graph, train.task_seed ^ SIM_SEED_XOR, TAU, ETA);
    let mut native_delta = vec![0.0; sim.weights.len()];
    let mut reference = vec![0.0; sim.weights.len()];
    let mut grad = vec![0.0; sim.weights.len()];
    for trial in 0..train.schedule.len() {
        let (_correct, reward) = sim.begin_trial(&task, trial);
        collector::reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference, &mut grad);
        sim.proposed_delta_into(reward, &mut native_delta);
        sim.apply_delta(&native_delta);
    }
    collector::reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference, &mut grad);
    Ok(SnapshotDescriptor {
        schema: "FLY-REACH-03-f4-replay-descriptor-v1".to_string(),
        snapshot_id: train.schedule.len() as u32,
        graph_id: cell.graph_id.clone(),
        task_manifest_id: format!("{}:{}:{}", cell.substrate, cell.side, block_id),
        substrate: cell.substrate.clone(),
        side: cell.side.clone(),
        block: block_id,
        trial: train.schedule.len(),
        sim_seed: train.task_seed ^ SIM_SEED_XOR,
        tau: TAU,
        eta: ETA,
        reference_lr: REFERENCE_LR,
        pre_state_sha256: Some(sim.digest()),
        reference_vector_sha256: Some(digest_f32(&reference)),
        sample_reference_sha256: digest_sample(&reference, &cell.coordinates),
        sample_target_sha256: digest_targets(&reference, &cell.coordinates),
    })
}

pub fn repair_v2_from_v1(study: &Path, lineage: &Path) -> Result<()> {
    let source_root = study.join("runs/qualification-v1");
    let target_root = study.join("runs").join(RUN_ID);
    ensure!(source_root.is_dir(), "qualification-v1 source is missing");
    ensure!(!target_root.exists(), "qualification-v2 already exists");
    fs::create_dir_all(target_root.join("rows"))?;
    fs::create_dir_all(target_root.join("f4"))?;
    let training: TrainBank =
        serde_json::from_slice(&fs::read(study.join("inputs/qualification/training.json"))?)?;
    let manifest: QualificationManifest = serde_json::from_slice(&fs::read(
        study.join("manifests/QUALIFICATION-MANIFEST.json"),
    )?)?;
    for cell in &manifest.cells {
        for block_key in training.blocks.keys() {
            let block_id: u64 = block_key.parse()?;
            let stem = format!("{}-{}-{}", cell.substrate, cell.side, block_id);
            fs::copy(
                source_root.join("rows").join(format!("{stem}.bin")),
                target_root.join("rows").join(format!("{stem}.bin")),
            )?;
            fs::copy(
                source_root.join("f4").join(format!("{stem}.jsonl")),
                target_root.join("f4").join(format!("{stem}.jsonl")),
            )?;
        }
    }
    for (cell_index, cell) in manifest.cells.iter().enumerate() {
        let graph = crate::graph::load(lineage, &cell.substrate, &cell.side, -1.0)
            .with_context(|| format!("load graph {}", cell.cell_key))?;
        for block_key in training.blocks.keys() {
            let block_id: u64 = block_key.parse()?;
            let stem = format!("{}-{}-{}", cell.substrate, cell.side, block_id);
            let path = target_root.join("f4").join(format!("{stem}.jsonl"));
            let file = OpenOptions::new().append(true).open(path)?;
            let mut writer = BufWriter::with_capacity(1 << 20, file);
            let descriptor = terminal_descriptor(
                &graph,
                block_id,
                training.blocks.get(block_key).context("training block")?,
                cell,
            )?;
            write_descriptor(&mut writer, &descriptor)?;
            writer.flush()?;
        }
        eprintln!("qualification_v2_terminal_added cell={}/18", cell_index + 1);
    }
    let receipt = serde_json::json!({
        "schema": "FLY-REACH-03-qualification-v2-repair-receipt-v1",
        "status": "REPLACEMENT_PREPARED",
        "run_id": RUN_ID,
        "source_run_id": "qualification-v1",
        "source_preserved_nonpromotable": true,
        "reason": "append the frozen terminal F4 checkpoint 8192 in a fresh identity",
        "rows_reused_without_mutation": 37748736_u64,
        "terminal_descriptors_added": 72_u64,
        "measured_namespace_created": false,
        "estimators_started": false,
    });
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(target_root.join("QUALIFICATION-V2-REPAIR-RECEIPT.json"))?;
    serde_json::to_writer_pretty(&mut file, &receipt)?;
    file.write_all(b"\n")?;
    Ok(())
}

pub fn audit_f4(study: &Path, lineage: &Path) -> Result<()> {
    let run_root = study.join("runs").join(RUN_ID);
    let training: TrainBank =
        serde_json::from_slice(&fs::read(study.join("inputs/qualification/training.json"))?)?;
    let manifest: QualificationManifest = serde_json::from_slice(&fs::read(
        study.join("manifests/QUALIFICATION-MANIFEST.json"),
    )?)?;
    let mut checked = 0_u64;
    let mut checkpoints = 0_u64;
    for (cell_index, cell) in manifest.cells.iter().enumerate() {
        let graph = crate::graph::load(lineage, &cell.substrate, &cell.side, -1.0)
            .with_context(|| format!("load graph {}", cell.cell_key))?;
        for block_key in training.blocks.keys() {
            let block_id: u64 = block_key.parse()?;
            let stem = format!("{}-{}-{}", cell.substrate, cell.side, block_id);
            let snapshots_path = run_root.join("f4").join(format!("{stem}.jsonl"));
            let result = audit_cell(
                &graph,
                block_id,
                training.blocks.get(block_key).context("training block")?,
                cell,
                &snapshots_path,
            )?;
            checked += result.0;
            checkpoints += result.1;
        }
        eprintln!(
            "qualification_f4_audit_complete cell={}/18 checked={checked}",
            cell_index + 1
        );
    }
    let receipt = serde_json::json!({
        "schema": "FLY-REACH-03-qualification-f4-reconstruction-receipt-v1",
        "run_id": RUN_ID,
        "status": "PASS",
        "rows_checked_by_replay": checked,
        "checkpoint_digests_checked": checkpoints,
        "expected_trials": 589824_u64,
        "expected_checkpoint_digests": 432_u64,
        "target_channel": "sample target digest recomputed from reference_delta_into",
        "estimators_started": false,
        "measured_namespace_created": false,
    });
    let receipt_path = run_root.join("F4-RECONSTRUCTION-RECEIPT.json");
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(receipt_path)?;
    serde_json::to_writer_pretty(&mut file, &receipt)?;
    file.write_all(b"\n")?;
    Ok(())
}

#[allow(dead_code)]
fn _pattern_snapshot(pattern: &Pattern) -> (&[usize], &[usize], &[f32]) {
    (&pattern.edges, &pattern.offsets, &pattern.dan)
}
