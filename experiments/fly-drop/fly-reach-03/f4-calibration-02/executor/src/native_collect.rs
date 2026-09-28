use crate::{
    collector::{self, EPS, ETA, REFERENCE_LR, TAU},
    graph::{self, Graph},
    reach_sim::Sim,
    task::{Pattern, Task},
};
use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::{BufWriter, Seek, SeekFrom, Write},
    path::Path,
    time::Instant,
};

const INPUT_MAGIC: &[u8] = b"FLYREACH3SYMINP\0";
const TRUTH_MAGIC: &[u8] = b"FLYREACH3SYMTRU\0";
const INPUT_WIDTH: usize = 342;
const TRUTH_WIDTH: usize = 39;
const ROW_MODULUS: usize = 256;
const SUBSTRATES: [&str; 9] = [
    "fly", "g001", "g002", "g003", "g004", "g005", "g006", "g007", "g008",
];
const SIDES: [&str; 2] = ["L", "R"];

#[derive(Deserialize)]
struct TrainBlock {
    task_seed: u64,
    labels: Vec<bool>,
    schedule: Vec<Vec<usize>>,
    cue_count: usize,
    pretraining_trials: usize,
    delay_steps: usize,
}

#[derive(Deserialize)]
struct TrainBank {
    schema: String,
    qualification_only: bool,
    blocks: BTreeMap<String, TrainBlock>,
}

#[derive(Deserialize)]
struct Cell {
    substrate: String,
    side: String,
    coordinates: Vec<usize>,
    inclusion_probability: f64,
}

#[derive(Deserialize)]
struct Manifest {
    cells: Vec<Cell>,
}

#[derive(Clone, Copy)]
struct RelTuple {
    incidence: u8,
    role: i8,
    incidence_role: i8,
    delta: f32,
    incidence_delta: f32,
    role_delta: f32,
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn sha_file(path: &Path) -> Result<String> {
    Ok(sha256(&fs::read(path)?))
}

fn substrate_id(name: &str) -> Result<u8> {
    match name {
        "fly" => Ok(0),
        "g001" => Ok(1),
        "g002" => Ok(2),
        "g003" => Ok(3),
        "g004" => Ok(4),
        "g005" => Ok(5),
        "g006" => Ok(6),
        "g007" => Ok(7),
        "g008" => Ok(8),
        _ => anyhow::bail!("unknown substrate {name}"),
    }
}

fn side_id(side: &str) -> Result<u8> {
    match side {
        "L" => Ok(0),
        "R" => Ok(1),
        _ => anyhow::bail!("unknown side {side}"),
    }
}

fn find_cell<'a>(manifest: &'a Manifest, substrate: &str, side: &str) -> Result<&'a Cell> {
    manifest
        .cells
        .iter()
        .find(|cell| cell.substrate == substrate && cell.side == side)
        .with_context(|| format!("missing cell {substrate}:{side}"))
}

fn standalone_p(pattern: &Pattern, post: usize, sim: &Sim<'_>) -> f32 {
    let mut drive = 0.0_f32;
    for &ix in &pattern.edges[pattern.offsets[post]..pattern.offsets[post + 1]] {
        if sim.active[ix] {
            drive = drive + sim.weights[ix];
        }
    }
    let x = 2.0_f32 * (drive / sim.denom[post] - sim.bias[post]);
    1.0_f32 / (1.0_f32 + (-x.clamp(-30.0_f32, 30.0_f32)).exp())
}

fn tuple_for(task: &Task, sim: &Sim<'_>, coordinate: usize) -> Result<[RelTuple; 4]> {
    ensure!(task.cues == 4 && task.labels.len() == 4, "expected four cues");
    let post = sim.graph.kc_mb.edges[coordinate].post as usize;
    let action = sim.action_sign[post];
    ensure!(action == -1.0 || action == 1.0, "action sign is not exact +/-1");
    let mut tuples = [RelTuple {
        incidence: 0,
        role: 0,
        incidence_role: 0,
        delta: 0.0,
        incidence_delta: 0.0,
        role_delta: 0.0,
    }; 4];
    for (cue, tuple) in tuples.iter_mut().enumerate() {
        let label = if task.labels[cue] { 1_i8 } else { -1_i8 };
        let role = label * action as i8;
        let incidence = u8::from(task.patterns[cue].edges.binary_search(&coordinate).is_ok());
        let incidence_role = incidence as i8 * role;
        let delta = standalone_p(&task.patterns[cue], post, sim) - 0.5_f32;
        let incidence_delta = incidence as f32 * delta;
        let role_delta = role as f32 * delta;
        *tuple = RelTuple {
            incidence,
            role,
            incidence_role,
            delta: if delta == 0.0 { 0.0 } else { delta },
            incidence_delta: if incidence_delta == 0.0 { 0.0 } else { incidence_delta },
            role_delta: if role_delta == 0.0 { 0.0 } else { role_delta },
        };
        ensure!(tuple.delta.is_finite() && tuple.incidence_delta.is_finite() && tuple.role_delta.is_finite());
    }
    Ok(tuples)
}

fn make_a(
    graph: &Graph,
    task: &Task,
    sim: &Sim<'_>,
    pre_degree: &[usize],
    trial: usize,
    coordinate: usize,
) -> [f32; 66] {
    let edge = graph.kc_mb.edges[coordinate];
    let post = edge.post as usize;
    let mut a = [0.0_f32; 66];
    let edge_count = graph.kc_mb.edges.len() as f32;
    let pre_count = graph.kc_mb.n_pre.max(1) as f32;
    let post_count = graph.kc_mb.n_post.max(1) as f32;
    let post_degree = graph.kc_mb.row(post).len() as f32;
    a[0] = coordinate as f32 / edge_count;
    a[1] = edge.pre as f32 / pre_count;
    a[2] = edge.post as f32 / post_count;
    a[3] = pre_degree[edge.pre as usize] as f32 / post_count;
    a[4] = post_degree / edge_count;
    a[5] = edge.count as f32 / 32.0;
    a[6] = graph.mb_sign[post];
    a[7] = trial as f32 / task.schedule.len().max(1) as f32;
    a[8] = sim.weights[coordinate];
    a[9] = sim.eligibility[coordinate];
    a[10] = sim.probabilities[post];
    a[11] = sim.post[post];
    a[12] = sim.baseline[post];
    a[13] = sim.signed_post[post];
    a[14] = sim.gain[post];
    a[15] = sim.denom[post];
    a[16] = sim.bias[post];
    a[17] = sim.scale;
    a[18] = sim.lambda;
    a[19] = (sim.work as f32).ln_1p() / 32.0;
    a[20] = (sim.events as f32).ln_1p() / 16.0;
    for cue in 0..4 {
        a[21 + cue] = if task.labels[cue] { 1.0 } else { -1.0 };
        a[25 + cue] = if task.patterns[cue].edges.binary_search(&coordinate).is_ok() { 1.0 } else { 0.0 };
    }
    let current = &task.schedule[trial % task.schedule.len()];
    for (offset, &pattern) in current.iter().take(13).enumerate() {
        a[29 + offset] = pattern as f32 / (task.cues + 32).max(1) as f32;
    }
    for family in 0..4_u64 {
        for bucket in 0..6_u64 {
            let mut value = 0.0_f32;
            for cue in 0..4 {
                let key = (coordinate as u64)
                    .wrapping_add((cue as u64).wrapping_mul(0x9e3779b97f4a7c15))
                    .wrapping_add((task.patterns[cue].edges.len() as u64) << 17)
                    .wrapping_add(family << 32);
                let mut mixed = key;
                mixed ^= mixed >> 30;
                mixed = mixed.wrapping_mul(0xbf58476d1ce4e5b9);
                mixed ^= mixed >> 27;
                mixed = mixed.wrapping_mul(0x94d049bb133111eb);
                mixed ^= mixed >> 31;
                if mixed % 6 == bucket {
                    let sign = if mixed & 1 == 0 { 1.0 } else { -1.0 };
                    let label = if task.labels[cue] { 1.0 } else { -1.0 };
                    value += sign * label;
                }
            }
            a[42 + family as usize * 6 + bucket as usize] = value / 4.0;
        }
    }
    a
}

fn write_row(
    features: &mut BufWriter<File>,
    truth: &mut BufWriter<File>,
    substrate: &str,
    side: &str,
    block: u64,
    trial: u32,
    coordinate: u32,
    a: &[f32; 66],
    tuples: &[RelTuple; 4],
    q: f64,
    target: i8,
    native_delta: f32,
    weight: f32,
    reference: f32,
) -> Result<()> {
    let mut key = [0_u8; 18];
    key[0] = substrate_id(substrate)?;
    key[1] = side_id(side)?;
    key[2..10].copy_from_slice(&block.to_le_bytes());
    key[10..14].copy_from_slice(&trial.to_le_bytes());
    key[14..18].copy_from_slice(&coordinate.to_le_bytes());
    features.write_all(&key)?;
    for value in a {
        ensure!(value.is_finite(), "nonfinite A feature");
        features.write_all(&value.to_le_bytes())?;
    }
    for tuple in tuples {
        features.write_all(&[tuple.incidence, tuple.role as u8, tuple.incidence_role as u8])?;
        features.write_all(&tuple.delta.to_le_bytes())?;
        features.write_all(&tuple.incidence_delta.to_le_bytes())?;
        features.write_all(&tuple.role_delta.to_le_bytes())?;
    }
    truth.write_all(&key)?;
    truth.write_all(&q.to_le_bytes())?;
    truth.write_all(&[target as u8])?;
    truth.write_all(&native_delta.to_le_bytes())?;
    truth.write_all(&weight.to_le_bytes())?;
    truth.write_all(&reference.to_le_bytes())?;
    Ok(())
}

fn pre_degree(graph: &Graph) -> Vec<usize> {
    let mut degree = vec![0; graph.kc_mb.n_pre];
    for edge in &graph.kc_mb.edges {
        degree[edge.pre as usize] += 1;
    }
    degree
}

fn load_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T> {
    Ok(serde_json::from_slice(&fs::read(path).with_context(|| path.display().to_string())?)?)
}

fn p_reconciliation(graph: &Graph, train: &TrainBlock) -> Result<usize> {
    let task = Task::new(graph, train.task_seed, train.labels.clone(), train.schedule.clone());
    let mut sim = Sim::new(graph, train.task_seed, TAU, ETA);
    let mut local_abs = vec![0.0; sim.weights.len()];
    let mut local_signed = vec![0.0; sim.weights.len()];
    sim.begin_trial_with_local(&task, 0, &mut local_abs, &mut local_signed);
    let mut comparisons = 0;
    for cue in 0..task.cues {
        let mut ordinary = sim.clone();
        ordinary.sample_for_fixture(&task.patterns[cue]);
        for post in 0..sim.post.len() {
            let standalone = standalone_p(&task.patterns[cue], post, &sim);
            ensure!(standalone.to_bits() == ordinary.probabilities[post].to_bits(), "forward p mismatch cue={cue}, post={post}");
            comparisons += 1;
        }
    }
    Ok(comparisons)
}

fn collect_stream(
    graph: &Graph,
    cell: &Cell,
    block_id: u64,
    train: &TrainBlock,
    features: &mut BufWriter<File>,
    truth: &mut BufWriter<File>,
) -> Result<(usize, String)> {
    ensure!(train.cue_count == 4 && train.pretraining_trials == 8192 && train.delay_steps == 12);
    ensure!(train.labels.len() == 4 && train.schedule.len() == 8192);
    let task = Task::new(graph, train.task_seed, train.labels.clone(), train.schedule.clone());
    let mut sim = Sim::new(graph, train.task_seed, TAU, ETA);
    let mut local_abs = vec![0.0; sim.weights.len()];
    let mut local_signed = vec![0.0; sim.weights.len()];
    let mut native = vec![0.0; sim.weights.len()];
    let mut reference = vec![0.0; sim.weights.len()];
    let mut grad = vec![0.0; sim.weights.len()];
    let degree = pre_degree(graph);
    let mut row_index = 0_usize;
    let mut count = 0_usize;
    let mut keys = Sha256::new();
    for trial in 0..train.schedule.len() {
        let (_correct, reward) = sim.begin_trial_with_local(&task, trial, &mut local_abs, &mut local_signed);
        collector::reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference, &mut grad);
        sim.proposed_delta_into(reward, &mut native);
        for &coordinate in &cell.coordinates {
            let target = collector::target(reference[coordinate]);
            if row_index % ROW_MODULUS == 0 && target != 0 && native[coordinate].abs() > EPS {
                let a = make_a(graph, &task, &sim, &degree, trial, coordinate);
                let tuples = tuple_for(&task, &sim, coordinate)?;
                write_row(
                    features,
                    truth,
                    &cell.substrate,
                    &cell.side,
                    block_id,
                    trial as u32,
                    coordinate as u32,
                    &a,
                    &tuples,
                    cell.inclusion_probability,
                    target,
                    native[coordinate],
                    sim.weights[coordinate],
                    reference[coordinate],
                )?;
                keys.update(key_bytes(&cell.substrate, &cell.side, block_id, trial as u32, coordinate as u32)?);
                count += 1;
            }
            row_index += 1;
        }
        sim.apply_delta(&native);
        ensure!(sim.finite(), "nonfinite native replay at {block_id}/{trial}");
    }
    Ok((count, format!("{:x}", keys.finalize())))
}

fn key_bytes(substrate: &str, side: &str, block: u64, trial: u32, coordinate: u32) -> Result<[u8; 18]> {
    let mut key = [0_u8; 18];
    key[0] = substrate_id(substrate)?;
    key[1] = side_id(side)?;
    key[2..10].copy_from_slice(&block.to_le_bytes());
    key[10..14].copy_from_slice(&trial.to_le_bytes());
    key[14..18].copy_from_slice(&coordinate.to_le_bytes());
    Ok(key)
}

fn finalize_writer(mut writer: BufWriter<File>, count: usize) -> Result<()> {
    writer.flush()?;
    let mut file = writer.into_inner().map_err(|error| error.into_error())?;
    file.seek(SeekFrom::Start(24))?;
    file.write_all(&(count as u64).to_le_bytes())?;
    file.sync_all()?;
    Ok(())
}

pub(crate) fn run(study: &Path, lineage: &Path, task_run: &Path, out: &Path) -> Result<()> {
    ensure!(out.is_dir() && fs::read_dir(out)?.next().is_none(), "native output must be an empty directory");
    let bank: TrainBank = load_json(&task_run.join("training.json"))?;
    ensure!(bank.schema == "FLY-REACH-03-F4-SYMMETRY-03-training-v1" && bank.qualification_only);
    let manifest: Manifest = load_json(&study.join("manifests/QUALIFICATION-MANIFEST.json"))?;
    ensure!(manifest.cells.len() == SUBSTRATES.len() * SIDES.len());
    let feature_file = OpenOptions::new().create_new(true).read(true).write(true).open(out.join("RAW-PREDICTORS.bin"))?;
    let truth_file = OpenOptions::new().create_new(true).read(true).write(true).open(out.join("RAW-SCORING-TRUTH.bin"))?;
    let mut features = BufWriter::with_capacity(1 << 20, feature_file);
    let mut truth = BufWriter::with_capacity(1 << 20, truth_file);
    features.write_all(INPUT_MAGIC)?;
    features.write_all(&1_u32.to_le_bytes())?;
    features.write_all(&(INPUT_WIDTH as u32).to_le_bytes())?;
    features.write_all(&0_u64.to_le_bytes())?;
    truth.write_all(TRUTH_MAGIC)?;
    truth.write_all(&1_u32.to_le_bytes())?;
    truth.write_all(&(TRUTH_WIDTH as u32).to_le_bytes())?;
    truth.write_all(&0_u64.to_le_bytes())?;

    let started = Instant::now();
    let block_ids: Vec<u64> = bank
        .blocks
        .keys()
        .map(|id| id.parse::<u64>())
        .collect::<std::result::Result<_, _>>()?;
    ensure!(block_ids.len() == 12 && block_ids.windows(2).all(|pair| pair[0] < pair[1]));
    let mut stream_receipts = Vec::with_capacity(block_ids.len() * SUBSTRATES.len() * SIDES.len());
    let mut total_rows = 0_usize;
    let mut p_matches = 0_usize;
    for substrate in SUBSTRATES {
        for side in SIDES {
            let cell = find_cell(&manifest, substrate, side)?;
            ensure!(cell.coordinates.len() == 64 && cell.inclusion_probability > 0.0);
            let graph = graph::load(lineage, substrate, side, -1.0)?;
            for &block_id in &block_ids {
                let train = bank.blocks.get(&block_id.to_string()).context("missing task block")?;
                if substrate == "fly" && side == "L" && block_id == block_ids[0] {
                    p_matches = p_reconciliation(&graph, train)?;
                }
                let (rows, key_hash) = collect_stream(&graph, cell, block_id, train, &mut features, &mut truth)
                    .with_context(|| format!("native stream {substrate}:{side}:{block_id}"))?;
                total_rows += rows;
                stream_receipts.push(json!({
                    "substrate":substrate,"side":side,"block_id":block_id,
                    "rows":rows,"ordered_key_sha256":key_hash,"status":"PASS"
                }));
                eprintln!("symmetry03_stream_complete substrate={substrate} side={side} block={block_id} rows={rows} total={total_rows}");
            }
        }
    }
    finalize_writer(features, total_rows)?;
    finalize_writer(truth, total_rows)?;
    let predictor_path = out.join("RAW-PREDICTORS.bin");
    let truth_path = out.join("RAW-SCORING-TRUTH.bin");
    let receipt = json!({
        "schema":"F4-CALIBRATION-02-native-collection-v1",
        "status":"PASS",
        "block_ids":block_ids,
        "stream_count":stream_receipts.len(),
        "expected_stream_count":12*SUBSTRATES.len()*SIDES.len(),
        "row_count":total_rows,
        "predictor_sha256":sha_file(&predictor_path)?,
        "predictor_bytes":fs::metadata(&predictor_path)?.len(),
        "truth_sha256":sha_file(&truth_path)?,
        "truth_bytes":fs::metadata(&truth_path)?.len(),
        "p_forward_fixture_comparisons":p_matches,
        "p_forward_fixture_status":"PASS",
        "streams":stream_receipts,
        "runtime_seconds":started.elapsed().as_secs_f64(),
        "target_read_for_Ustar_collection":true,
        "comparative_metrics_emitted":false,
        "measured_namespace_created":false
    });
    fs::write(out.join("NATIVE-COLLECTION-RECEIPT.json"), serde_json::to_vec_pretty(&receipt)?)?;
    Ok(())
}
