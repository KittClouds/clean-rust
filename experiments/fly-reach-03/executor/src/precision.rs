use crate::{
    collector::{self, EPS, ETA, REFERENCE_LR, TAU},
    graph::Graph,
    reach_sim::Sim,
    task::{Pattern, Task},
};
use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::{BufWriter, Write},
    path::Path,
};

const FEATURE_MAGIC: &[u8] = b"FLYREACH3P64\0";
const FEATURE_WIDTH: usize = 80;
const SAMPLE_MODULUS: usize = 256;
const SIM_SEED_XOR: u64 = 0;

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

struct FeatureWriter {
    file: BufWriter<File>,
    rows: u64,
}

impl FeatureWriter {
    fn create(path: &Path, substrate: &str, side: &str, block: u64) -> Result<Self> {
        let file = OpenOptions::new().create_new(true).write(true).open(path)?;
        let mut file = BufWriter::with_capacity(1 << 20, file);
        file.write_all(FEATURE_MAGIC)?;
        file.write_all(&1_u32.to_le_bytes())?;
        file.write_all(&(FEATURE_WIDTH as u16).to_le_bytes())?;
        file.write_all(&(substrate.len() as u16).to_le_bytes())?;
        file.write_all(substrate.as_bytes())?;
        file.write_all(&(side.len() as u16).to_le_bytes())?;
        file.write_all(side.as_bytes())?;
        file.write_all(&block.to_le_bytes())?;
        Ok(Self { file, rows: 0 })
    }

    fn write_row(
        &mut self,
        trial: usize,
        coordinate: usize,
        inclusion_probability: f64,
        target: i8,
        abs_reference: f64,
        features: &[f64; FEATURE_WIDTH],
    ) -> Result<()> {
        self.file.write_all(&(trial as u32).to_le_bytes())?;
        self.file.write_all(&(coordinate as u32).to_le_bytes())?;
        self.file
            .write_all(&inclusion_probability.to_bits().to_le_bytes())?;
        self.file.write_all(&[target as u8])?;
        self.file
            .write_all(&abs_reference.to_bits().to_le_bytes())?;
        for value in features {
            self.file.write_all(&value.to_bits().to_le_bytes())?;
        }
        self.rows += 1;
        Ok(())
    }

    fn finish(mut self) -> Result<u64> {
        self.file.flush()?;
        Ok(self.rows)
    }
}

#[inline]
fn sigmoid_f64(value: f64) -> f64 {
    1.0 / (1.0 + (-value.clamp(-30.0, 30.0)).exp())
}

fn expected_score_f64(weights: &[f32], sim: &Sim<'_>, pattern: &Pattern) -> f64 {
    let mut score = 0.0_f64;
    for post in 0..sim.post.len() {
        let mut drive = 0.0_f64;
        for &edge in &pattern.edges[pattern.offsets[post]..pattern.offsets[post + 1]] {
            drive += f64::from(weights[edge]);
        }
        let p = sigmoid_f64(2.0 * (drive / f64::from(sim.denom[post]) - f64::from(sim.bias[post])));
        score += f64::from(sim.action_sign[post]) * (p - 0.5);
    }
    score
}

#[inline]
fn stable_mix(mut value: u64) -> u64 {
    value ^= value >> 30;
    value = value.wrapping_mul(0xbf58476d1ce4e5b9);
    value ^= value >> 27;
    value = value.wrapping_mul(0x94d049bb133111eb);
    value ^ (value >> 31)
}

fn features_f64(
    graph: &Graph,
    task: &Task,
    sim: &Sim<'_>,
    trial: usize,
    coordinate: usize,
    pre_degree: &[usize],
) -> [f64; FEATURE_WIDTH] {
    let edge = graph.kc_mb.edges[coordinate];
    let post = edge.post as usize;
    let edge_count = graph.kc_mb.edges.len() as f64;
    let pre_count = graph.kc_mb.n_pre.max(1) as f64;
    let post_count = graph.kc_mb.n_post.max(1) as f64;
    let mut out = [0.0_f64; FEATURE_WIDTH];
    let mut k = 0usize;
    out[k] = coordinate as f64 / edge_count;
    k += 1;
    out[k] = f64::from(edge.pre) / pre_count;
    k += 1;
    out[k] = f64::from(edge.post) / post_count;
    k += 1;
    out[k] = pre_degree[edge.pre as usize] as f64 / post_count;
    k += 1;
    out[k] = graph.kc_mb.row(post).len() as f64 / edge_count;
    k += 1;
    out[k] = f64::from(edge.count) / 32.0;
    k += 1;
    out[k] = f64::from(graph.mb_sign[post]);
    k += 1;
    out[k] = trial as f64 / task.schedule.len().max(1) as f64;
    k += 1;
    out[k] = f64::from(sim.weights[coordinate]);
    k += 1;
    out[k] = f64::from(sim.eligibility[coordinate]);
    k += 1;
    out[k] = f64::from(sim.probabilities[post]);
    k += 1;
    out[k] = f64::from(sim.post[post]);
    k += 1;
    out[k] = f64::from(sim.baseline[post]);
    k += 1;
    out[k] = f64::from(sim.signed_post[post]);
    k += 1;
    out[k] = f64::from(sim.gain[post]);
    k += 1;
    out[k] = f64::from(sim.denom[post]);
    k += 1;
    out[k] = f64::from(sim.bias[post]);
    k += 1;
    out[k] = f64::from(sim.scale);
    k += 1;
    out[k] = f64::from(sim.lambda);
    k += 1;
    out[k] = (sim.work as f64).ln_1p() / 32.0;
    k += 1;
    out[k] = (sim.events as f64).ln_1p() / 16.0;
    k += 1;
    for &label in &task.labels {
        out[k] = if label { 1.0 } else { -1.0 };
        k += 1;
    }
    for cue in 0..task.cues {
        out[k] = expected_score_f64(&sim.weights, sim, &task.patterns[cue]);
        k += 1;
    }
    for cue in 0..task.cues {
        out[k] = if task.patterns[cue].edges.binary_search(&coordinate).is_ok() {
            1.0
        } else {
            0.0
        };
        k += 1;
    }
    for &pattern in task.schedule[trial % task.schedule.len()].iter().take(13) {
        out[k] = pattern as f64 / (task.cues + 32).max(1) as f64;
        k += 1;
    }
    while k < 53 {
        out[k] = 0.0;
        k += 1;
    }
    for family in 0..4_u64 {
        for bucket in 0..6_u64 {
            let mut value = 0.0_f64;
            for cue in 0..task.cues {
                let key = (coordinate as u64)
                    .wrapping_add((cue as u64).wrapping_mul(0x9e3779b97f4a7c15))
                    .wrapping_add((task.patterns[cue].edges.len() as u64) << 17)
                    .wrapping_add(family << 32);
                let mixed = stable_mix(key);
                if mixed % 6 == bucket {
                    let sign = if mixed & 1 == 0 { 1.0 } else { -1.0 };
                    value += sign * if task.labels[cue] { 1.0 } else { -1.0 };
                }
            }
            out[k] = value / task.cues.max(1) as f64;
            k += 1;
        }
    }
    while k < FEATURE_WIDTH {
        out[k] = 0.0;
        k += 1;
    }
    out
}

fn collect_cell(
    graph: &Graph,
    block_id: u64,
    train: &TrainBlock,
    cell: &Cell,
    output_path: &Path,
) -> Result<u64> {
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
    let mut pre_degree = vec![0usize; graph.kc_mb.n_pre];
    for edge in &graph.kc_mb.edges {
        pre_degree[edge.pre as usize] += 1;
    }
    let mut writer = FeatureWriter::create(output_path, &cell.substrate, &cell.side, block_id)?;
    let mut row_index = 0usize;
    for trial in 0..train.schedule.len() {
        let (_correct, reward) =
            sim.begin_trial_with_local(&task, trial, &mut local_abs, &mut local_signed);
        collector::reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference, &mut grad);
        sim.proposed_delta_into(reward, &mut native_delta);
        for &coordinate in &cell.coordinates {
            let target = collector::target(reference[coordinate]);
            if target != 0
                && native_delta[coordinate].abs() > EPS
                && row_index % SAMPLE_MODULUS == 0
            {
                let values = features_f64(graph, &task, &sim, trial, coordinate, &pre_degree);
                ensure!(values.iter().all(|value| value.is_finite()));
                writer.write_row(
                    trial,
                    coordinate,
                    cell.inclusion_probability,
                    target,
                    f64::from(reference[coordinate]).abs(),
                    &values,
                )?;
            }
            row_index += 1;
        }
        sim.apply_delta(&native_delta);
        ensure!(
            sim.finite(),
            "nonfinite precision replay at {} trial {}",
            cell.cell_key,
            trial
        );
    }
    let rows = writer.finish()?;
    ensure!(!cell.graph_id.is_empty());
    Ok(rows)
}

pub fn collect(study: &Path, lineage: &Path) -> Result<()> {
    let run_root = study.join("runs/qualification-v2/f4-precision-01-attempt-02/arm-b-f64");
    ensure!(
        !run_root.exists(),
        "precision qualification identity already exists; preserve it and stop"
    );
    fs::create_dir_all(&run_root)?;
    eprintln!("precision_attempt02_output_ready");
    let training: TrainBank =
        serde_json::from_slice(&fs::read(study.join("inputs/qualification/training.json"))?)?;
    eprintln!(
        "precision_attempt02_training_loaded blocks={}",
        training.blocks.len()
    );
    let manifest: QualificationManifest = serde_json::from_slice(&fs::read(
        study.join("manifests/QUALIFICATION-MANIFEST.json"),
    )?)?;
    ensure!(training.blocks.len() == 4 && manifest.cells.len() == 18);
    eprintln!(
        "precision_attempt02_manifest_loaded cells={}",
        manifest.cells.len()
    );
    let mut total_rows = 0_u64;
    let mut output_manifest = Vec::new();
    for (cell_index, cell) in manifest.cells.iter().enumerate() {
        eprintln!(
            "precision_attempt02_graph_start cell={}/18 key={}",
            cell_index + 1,
            cell.cell_key
        );
        let graph = crate::graph::load(lineage, &cell.substrate, &cell.side, -1.0)
            .with_context(|| format!("load graph {}", cell.cell_key))?;
        eprintln!(
            "precision_attempt02_graph_loaded cell={}/18",
            cell_index + 1
        );
        for block_key in training.blocks.keys() {
            let block_id: u64 = block_key.parse()?;
            let filename = format!("{}-{}-{}.bin", cell.substrate, cell.side, block_id);
            let path = run_root.join(&filename);
            let rows = collect_cell(
                &graph,
                block_id,
                training.blocks.get(block_key).context("training block")?,
                cell,
                &path,
            )?;
            total_rows += rows;
            output_manifest.push(serde_json::json!({
                "cell_key": cell.cell_key,
                "block": block_id,
                "path": filename,
                "rows": rows,
                "sha256": hash_file(&path)?,
                "bytes": fs::metadata(&path)?.len(),
            }));
        }
        eprintln!(
            "precision_f64_replay_complete cell={}/18 rows={total_rows}",
            cell_index + 1
        );
    }
    let receipt = serde_json::json!({
        "schema": "FLY-REACH-03-F4-PRECISION-01-feature-collection-v1",
        "identity": "F4-PRECISION-01",
        "status": "COLLECTION_COMPLETE",
        "arm": "B-f64-feature-generation-and-storage",
        "rows": total_rows,
        "streams": output_manifest.len(),
        "feature_width": FEATURE_WIDTH,
        "record_encoding": "float64-little-endian-features-and-magnitude",
        "native_trajectory_mutated": false,
        "measured_namespace_created": false,
        "streams_manifest": output_manifest,
    });
    let receipt_path = run_root.join("F64-COLLECTION-RECEIPT.json");
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(receipt_path)?;
    serde_json::to_writer_pretty(&mut file, &receipt)?;
    file.write_all(b"\n")?;
    Ok(())
}

fn hash_file(path: &Path) -> Result<String> {
    let mut file = File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 1 << 20];
    loop {
        use std::io::Read;
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("{:x}", digest.finalize()))
}
