use crate::{
    collector::{self, EPS, ETA, REFERENCE_LR, TAU},
    graph::{self, Graph},
    reach_sim::Sim,
    task::{Pattern, Task},
};
use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    cmp::Ordering,
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
};

#[path = "symmetry_authority.rs"]
mod authority;
use authority::verify_preflight_manifest;

const CONTRACT_SHA256: &str = "cfef638aaeac1dfc0b768d13cc95afe7724861f74e3d3111d91401925bed6379";
const V3_MAGIC: &[u8] = b"FLYREACH3V3\0";
const INPUT_MAGIC: &[u8] = b"FLYREACH3SYMINP\0";
const TRUTH_MAGIC: &[u8] = b"FLYREACH3SYMTRU\0";
const INPUT_WIDTH: usize = 342;
const TRUTH_WIDTH: usize = 39;
const ROW_MODULUS: usize = 256;
const SIM_SEED_XOR: u64 = 0;
const BLOCKS: [u64; 4] = [303000, 303001, 303002, 303003];
const TRIAL_FIXTURES: [usize; 6] = [0, 1, 2, 7, 31, 255];

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
    coordinates: Vec<usize>,
    inclusion_probability: f64,
}

#[derive(Deserialize)]
struct QualificationManifest {
    cells: Vec<Cell>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct RelTuple {
    incidence: u8,
    role: i8,
    incidence_role: i8,
    delta: f32,
    incidence_delta: f32,
    role_delta: f32,
}

#[derive(Clone, Copy)]
struct RowKey {
    substrate: u8,
    side: u8,
    block: u64,
    trial: u32,
    coordinate: u32,
}

impl RowKey {
    fn bytes(self) -> [u8; 18] {
        let mut out = [0_u8; 18];
        out[0] = self.substrate;
        out[1] = self.side;
        out[2..10].copy_from_slice(&self.block.to_le_bytes());
        out[10..14].copy_from_slice(&self.trial.to_le_bytes());
        out[14..18].copy_from_slice(&self.coordinate.to_le_bytes());
        out
    }
}

#[derive(Clone)]
struct ExpectedRow {
    key: RowKey,
    q_bits: u64,
    target: i8,
}

struct Stream {
    path: PathBuf,
    substrate: String,
    side: String,
    block: u64,
    expected: Vec<ExpectedRow>,
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn write_json(path: &Path, value: &serde_json::Value) -> Result<()> {
    let file = OpenOptions::new().create_new(true).write(true).open(path)?;
    let mut out = BufWriter::new(file);
    serde_json::to_writer_pretty(&mut out, value)?;
    out.write_all(b"\n")?;
    out.flush()?;
    Ok(())
}

fn read_u16(data: &[u8], pos: &mut usize) -> Result<u16> {
    let value = data.get(*pos..*pos + 2).context("truncated u16")?;
    *pos += 2;
    Ok(u16::from_le_bytes(value.try_into()?))
}

fn read_u32(data: &[u8], pos: &mut usize) -> Result<u32> {
    let value = data.get(*pos..*pos + 4).context("truncated u32")?;
    *pos += 4;
    Ok(u32::from_le_bytes(value.try_into()?))
}

fn read_u64(data: &[u8], pos: &mut usize) -> Result<u64> {
    let value = data.get(*pos..*pos + 8).context("truncated u64")?;
    *pos += 8;
    Ok(u64::from_le_bytes(value.try_into()?))
}

fn substrate_id(substrate: &str) -> Result<u8> {
    match substrate {
        "fly" => Ok(0),
        "g001" => Ok(1),
        "g002" => Ok(2),
        "g003" => Ok(3),
        "g004" => Ok(4),
        "g005" => Ok(5),
        "g006" => Ok(6),
        "g007" => Ok(7),
        "g008" => Ok(8),
        _ => anyhow::bail!("unknown substrate {substrate}"),
    }
}

fn side_id(side: &str) -> Result<u8> {
    match side {
        "L" => Ok(0),
        "R" => Ok(1),
        _ => anyhow::bail!("unknown side {side}"),
    }
}

fn parse_v3(path: &Path) -> Result<Stream> {
    let data = fs::read(path)?;
    ensure!(
        data.starts_with(V3_MAGIC),
        "bad V3 magic at {}",
        path.display()
    );
    let mut pos = V3_MAGIC.len();
    ensure!(read_u32(&data, &mut pos)? == 1, "V3 version mismatch");
    ensure!(read_u16(&data, &mut pos)? == 85, "V3 width mismatch");
    let substrate_len = usize::from(read_u16(&data, &mut pos)?);
    let substrate =
        std::str::from_utf8(data.get(pos..pos + substrate_len).context("substrate")?)?.to_string();
    pos += substrate_len;
    let side_len = usize::from(read_u16(&data, &mut pos)?);
    let side = std::str::from_utf8(data.get(pos..pos + side_len).context("side")?)?.to_string();
    pos += side_len;
    let block = read_u64(&data, &mut pos)?;
    let record_width = 4 + 4 + 8 + 1 + 85 * 4;
    ensure!(
        (data.len() - pos) % record_width == 0,
        "V3 record alignment failure"
    );
    let mut expected = Vec::with_capacity((data.len() - pos) / record_width);
    while pos < data.len() {
        let trial = read_u32(&data, &mut pos)?;
        let coordinate = read_u32(&data, &mut pos)?;
        let q_bits = read_u64(&data, &mut pos)?;
        let target = data[pos] as i8;
        pos += 1 + 85 * 4;
        ensure!(target == -1 || target == 1, "V3 target not binary");
        expected.push(ExpectedRow {
            key: RowKey {
                substrate: substrate_id(&substrate)?,
                side: side_id(&side)?,
                block,
                trial,
                coordinate,
            },
            q_bits,
            target,
        });
    }
    Ok(Stream {
        path: path.to_path_buf(),
        substrate,
        side,
        block,
        expected,
    })
}

fn read_streams(study: &Path) -> Result<Vec<Stream>> {
    let root = study.join("runs/qualification-v2/f4-features-v3-post-probability");
    let mut paths: Vec<PathBuf> = fs::read_dir(&root)?
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .filter(|path| path.extension().is_some_and(|ext| ext == "bin"))
        .collect();
    paths.sort_by(|a, b| {
        a.file_name()
            .unwrap()
            .to_string_lossy()
            .as_bytes()
            .cmp(b.file_name().unwrap().to_string_lossy().as_bytes())
    });
    ensure!(
        paths.len() == 72,
        "expected 72 prior streams, found {}",
        paths.len()
    );
    paths.iter().map(|path| parse_v3(path)).collect()
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

fn cue_probability_table(task: &Task, sim: &Sim<'_>) -> [Vec<f32>; 4] {
    std::array::from_fn(|cue| {
        (0..sim.post.len())
            .map(|post| standalone_p(&task.patterns[cue], post, sim))
            .collect()
    })
}

fn tuple_for_probabilities(
    task: &Task,
    sim: &Sim<'_>,
    coordinate: usize,
    probabilities: &[Vec<f32>; 4],
) -> Result<[RelTuple; 4]> {
    ensure!(
        task.cues == 4 && task.labels.len() == 4,
        "expected four cues"
    );
    let post = sim.graph.kc_mb.edges[coordinate].post as usize;
    let action = sim.action_sign[post];
    ensure!(
        action == -1.0 || action == 1.0,
        "action sign is not exact +/-1"
    );
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
        let delta = probabilities[cue][post] - 0.5_f32;
        let incidence_delta = incidence as f32 * delta;
        let role_delta = role as f32 * delta;
        *tuple = RelTuple {
            incidence,
            role,
            incidence_role,
            delta: if delta == 0.0 { 0.0 } else { delta },
            incidence_delta: if incidence_delta == 0.0 {
                0.0
            } else {
                incidence_delta
            },
            role_delta: if role_delta == 0.0 { 0.0 } else { role_delta },
        };
        ensure!(
            tuple.delta.is_finite()
                && tuple.incidence_delta.is_finite()
                && tuple.role_delta.is_finite()
        );
    }
    Ok(tuples)
}

fn tuple_for(task: &Task, sim: &Sim<'_>, coordinate: usize) -> Result<[RelTuple; 4]> {
    ensure!(
        task.cues == 4 && task.labels.len() == 4,
        "expected four cues"
    );
    let post = sim.graph.kc_mb.edges[coordinate].post as usize;
    let action = sim.action_sign[post];
    ensure!(
        action == -1.0 || action == 1.0,
        "action sign is not exact +/-1"
    );
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
            incidence_delta: if incidence_delta == 0.0 {
                0.0
            } else {
                incidence_delta
            },
            role_delta: if role_delta == 0.0 { 0.0 } else { role_delta },
        };
        ensure!(
            tuple.delta.is_finite()
                && tuple.incidence_delta.is_finite()
                && tuple.role_delta.is_finite()
        );
    }
    Ok(tuples)
}

fn tuple_bytes(tuple: RelTuple) -> [u8; 15] {
    let mut out = [0_u8; 15];
    out[0] = tuple.incidence;
    out[1] = tuple.role as u8;
    out[2] = tuple.incidence_role as u8;
    out[3..7].copy_from_slice(&tuple.delta.to_bits().to_le_bytes());
    out[7..11].copy_from_slice(&tuple.incidence_delta.to_bits().to_le_bytes());
    out[11..15].copy_from_slice(&tuple.role_delta.to_bits().to_le_bytes());
    out
}

fn tuple_cmp(a: &RelTuple, b: &RelTuple) -> Ordering {
    a.incidence
        .cmp(&b.incidence)
        .then_with(|| a.role.cmp(&b.role))
        .then_with(|| a.incidence_role.cmp(&b.incidence_role))
        .then_with(|| a.delta.total_cmp(&b.delta))
        .then_with(|| a.incidence_delta.total_cmp(&b.incidence_delta))
        .then_with(|| a.role_delta.total_cmp(&b.role_delta))
}

fn sorted_tuple_bytes(mut tuples: [RelTuple; 4]) -> [[u8; 15]; 4] {
    tuples.sort_by(tuple_cmp);
    tuples.map(tuple_bytes)
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
        a[25 + cue] = if task.patterns[cue].edges.binary_search(&coordinate).is_ok() {
            1.0
        } else {
            0.0
        };
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
            a[42 + (family as usize) * 6 + bucket as usize] = value / 4.0;
        }
    }
    a
}

fn write_raw_row(
    features: &mut BufWriter<File>,
    truth: &mut BufWriter<File>,
    key: RowKey,
    a: &[f32; 66],
    tuples: &[RelTuple; 4],
    q: f64,
    target: i8,
    native_delta: f32,
    weight: f32,
    reference: f32,
) -> Result<()> {
    features.write_all(&key.bytes())?;
    for value in a {
        features.write_all(&value.to_bits().to_le_bytes())?;
    }
    for tuple in tuples {
        features.write_all(&tuple_bytes(*tuple))?;
    }
    truth.write_all(&key.bytes())?;
    truth.write_all(&q.to_bits().to_le_bytes())?;
    truth.write_all(&[target as u8])?;
    truth.write_all(&native_delta.to_bits().to_le_bytes())?;
    truth.write_all(&weight.to_bits().to_le_bytes())?;
    truth.write_all(&reference.to_bits().to_le_bytes())?;
    Ok(())
}

fn pre_degree(graph: &Graph) -> Vec<usize> {
    let mut result = vec![0; graph.kc_mb.n_pre];
    for edge in &graph.kc_mb.edges {
        result[edge.pre as usize] += 1;
    }
    result
}

fn parse_blocks(study: &Path) -> Result<(TrainBank, QualificationManifest)> {
    let training =
        serde_json::from_slice(&fs::read(study.join("inputs/qualification/training.json"))?)?;
    let manifest = serde_json::from_slice(&fs::read(
        study.join("manifests/QUALIFICATION-MANIFEST.json"),
    )?)?;
    Ok((training, manifest))
}

fn find_cell<'a>(
    manifest: &'a QualificationManifest,
    substrate: &str,
    side: &str,
) -> Result<&'a Cell> {
    manifest
        .cells
        .iter()
        .find(|cell| cell.substrate == substrate && cell.side == side)
        .with_context(|| format!("missing cell {substrate}:{side}"))
}

fn replay_stream(
    graph: &Graph,
    cell: &Cell,
    block: u64,
    train: &TrainBlock,
    expected: &[ExpectedRow],
    mut collect: Option<(&mut BufWriter<File>, &mut BufWriter<File>)>,
) -> Result<(usize, String)> {
    let task = Task::new(
        graph,
        train.task_seed,
        train.labels.clone(),
        train.schedule.clone(),
    );
    ensure!(
        task.cues == 4 && train.cue_count == 4,
        "qualification task cue count drift"
    );
    let mut sim = Sim::new(graph, train.task_seed ^ SIM_SEED_XOR, TAU, ETA);
    let mut local_abs = vec![0.0; sim.weights.len()];
    let mut local_signed = vec![0.0; sim.weights.len()];
    let mut native_delta = vec![0.0; sim.weights.len()];
    let mut reference = vec![0.0; sim.weights.len()];
    let mut grad = vec![0.0; sim.weights.len()];
    let degree = pre_degree(graph);
    let mut expected_index = 0usize;
    let mut row_index = 0usize;
    let mut key_hash = Sha256::new();
    for trial in 0..train.schedule.len() {
        let (_correct, reward) =
            sim.begin_trial_with_local(&task, trial, &mut local_abs, &mut local_signed);
        collector::reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference, &mut grad);
        sim.proposed_delta_into(reward, &mut native_delta);
        for &coordinate in &cell.coordinates {
            let target = collector::target(reference[coordinate]);
            let support = native_delta[coordinate].abs() > EPS;
            if target != 0 && support && row_index % ROW_MODULUS == 0 {
                ensure!(
                    expected_index < expected.len(),
                    "extra replay key for {} block {block}",
                    cell.cell_key
                );
                let key = RowKey {
                    substrate: substrate_id(&cell.substrate)?,
                    side: side_id(&cell.side)?,
                    block,
                    trial: trial as u32,
                    coordinate: coordinate as u32,
                };
                let expected_row = &expected[expected_index];
                ensure!(
                    key.bytes() == expected_row.key.bytes(),
                    "row-key/order mismatch at {} block {block} index {expected_index}",
                    cell.cell_key
                );
                ensure!(
                    cell.inclusion_probability.to_bits() == expected_row.q_bits,
                    "inclusion probability mismatch at {} block {block} index {expected_index}",
                    cell.cell_key
                );
                ensure!(
                    target == expected_row.target,
                    "target mismatch at {} block {block} index {expected_index}",
                    cell.cell_key
                );
                key_hash.update(key.bytes());
                if let Some((features, truth)) = collect.as_mut() {
                    let a = make_a(graph, &task, &sim, &degree, trial, coordinate);
                    let tuples = tuple_for(&task, &sim, coordinate)?;
                    write_raw_row(
                        features,
                        truth,
                        key,
                        &a,
                        &tuples,
                        cell.inclusion_probability,
                        target,
                        native_delta[coordinate],
                        sim.weights[coordinate],
                        reference[coordinate],
                    )?;
                }
                expected_index += 1;
            }
            row_index += 1;
        }
        sim.apply_delta(&native_delta);
        ensure!(
            sim.finite(),
            "nonfinite native replay at {} trial {trial}",
            cell.cell_key
        );
    }
    ensure!(
        expected_index == expected.len(),
        "missing replay rows for {} block {block}: {} of {}",
        cell.cell_key,
        expected_index,
        expected.len()
    );
    Ok((expected_index, format!("{:x}", key_hash.finalize())))
}

fn reconcile_rows(study: &Path, lineage: &Path, out: &Path, streams: &[Stream]) -> Result<()> {
    let (training, manifest) = parse_blocks(study)?;
    let mut expected_total = 0usize;
    let mut actual_total = 0usize;
    let mut stream_receipts = Vec::with_capacity(streams.len());
    for stream in streams {
        let cell = find_cell(&manifest, &stream.substrate, &stream.side)?;
        let graph = graph::load(lineage, &cell.substrate, &cell.side, -1.0)?;
        let train = training
            .blocks
            .get(&stream.block.to_string())
            .context("missing training block")?;
        let (count, key_hash) =
            replay_stream(&graph, cell, stream.block, train, &stream.expected, None)
                .with_context(|| format!("row reconciliation {}", stream.path.display()))?;
        expected_total += stream.expected.len();
        actual_total += count;
        stream_receipts.push(json!({"path": stream.path.file_name().unwrap().to_string_lossy(), "rows": count, "ordered_key_sha256": key_hash, "status":"PASS"}));
    }
    ensure!(
        expected_total == 13420 && actual_total == expected_total,
        "expected 13,420 reconciled rows; got {actual_total}"
    );
    write_json(
        &out.join("ROW-RECONCILIATION-RECEIPT.json"),
        &json!({
            "schema":"F4-SYMMETRY-01-row-reconciliation-v1", "gate_id":"ROW_RECONCILIATION", "status":"PASS",
            "expected_rows":13420, "actual_rows":actual_total, "streams":stream_receipts, "missing":0, "duplicate":0, "extra":0
        }),
    )?;
    Ok(())
}

fn forward_reconciliation(study: &Path, lineage: &Path, out: &Path) -> Result<()> {
    let (training, manifest) = parse_blocks(study)?;
    let _cell = find_cell(&manifest, "fly", "L")?;
    let graph = graph::load(lineage, "fly", "L", -1.0)?;
    let block = training.blocks.get("303000").context("fixture block")?;
    let task = Task::new(
        &graph,
        block.task_seed,
        block.labels.clone(),
        block.schedule.clone(),
    );
    let mut sim = Sim::new(&graph, block.task_seed ^ SIM_SEED_XOR, TAU, ETA);
    let mut local_abs = vec![0.0; sim.weights.len()];
    let mut local_signed = vec![0.0; sim.weights.len()];
    sim.begin_trial_with_local(&task, 0, &mut local_abs, &mut local_signed);
    let mut matches = 0usize;
    for cue in 0..task.cues {
        let mut ordinary = sim.clone();
        ordinary.sample_for_fixture(&task.patterns[cue]);
        for post in 0..sim.post.len() {
            let standalone = standalone_p(&task.patterns[cue], post, &sim);
            ensure!(
                standalone.is_finite(),
                "nonfinite p_cj cue={cue} post={post}"
            );
            ensure!(
                standalone.to_bits() == ordinary.probabilities[post].to_bits(),
                "p_cj mismatch fixture=fly:L block=303000 trial=0 cue={cue} post={post}: {:08x}!={:08x}",
                standalone.to_bits(),
                ordinary.probabilities[post].to_bits()
            );
            matches += 1;
        }
    }
    write_json(
        &out.join("FORWARD-P-RECONCILIATION-RECEIPT.json"),
        &json!({
            "schema":"F4-SYMMETRY-01-forward-p-reconciliation-v1", "gate_id":"FORWARD_PROBABILITY", "status":"PASS",
            "fixture":"fly:L/block303000/trial0/after-begin_trial-before-apply_delta", "cue_count":4,
            "posts_per_cue":sim.post.len(), "comparisons":matches, "bitwise_matches":matches, "first_mismatch":null
        }),
    )?;
    Ok(())
}

fn write_raw_files(study: &Path, lineage: &Path, out: &Path, streams: &[Stream]) -> Result<()> {
    let (training, manifest) = parse_blocks(study)?;
    let total: usize = streams.iter().map(|stream| stream.expected.len()).sum();
    let feat_file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(out.join("RAW-PREDICTORS.bin"))?;
    let truth_file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(out.join("RAW-SCORING-TRUTH.bin"))?;
    let mut features = BufWriter::with_capacity(1 << 20, feat_file);
    let mut truth = BufWriter::with_capacity(1 << 20, truth_file);
    features.write_all(INPUT_MAGIC)?;
    features.write_all(&1_u32.to_le_bytes())?;
    features.write_all(&(INPUT_WIDTH as u32).to_le_bytes())?;
    features.write_all(&(total as u64).to_le_bytes())?;
    truth.write_all(TRUTH_MAGIC)?;
    truth.write_all(&1_u32.to_le_bytes())?;
    truth.write_all(&(TRUTH_WIDTH as u32).to_le_bytes())?;
    truth.write_all(&(total as u64).to_le_bytes())?;
    let mut rows = 0usize;
    for stream in streams {
        let cell = find_cell(&manifest, &stream.substrate, &stream.side)?;
        let graph = graph::load(lineage, &cell.substrate, &cell.side, -1.0)?;
        let train = training
            .blocks
            .get(&stream.block.to_string())
            .context("missing training block")?;
        let (count, _) = replay_stream(
            &graph,
            cell,
            stream.block,
            train,
            &stream.expected,
            Some((&mut features, &mut truth)),
        )?;
        rows += count;
        eprintln!(
            "f4_symmetry_raw_stream_complete stream={} rows={count} total={rows}",
            stream.path.file_name().unwrap().to_string_lossy()
        );
    }
    features.flush()?;
    truth.flush()?;
    ensure!(rows == total && rows == 13420);
    Ok(())
}

fn collect_inner(study: &Path, lineage: &Path, out: &Path) -> Result<()> {
    ensure!(
        out.is_dir(),
        "preflight output directory must already exist"
    );
    verify_preflight_manifest(study, out)?;
    ensure!(
        !out.join("RAW-PREDICTORS.bin").exists(),
        "raw predictor identity already exists"
    );
    let contract = fs::read(study.join("F4-SYMMETRY-01-CONTRACT-v0.1.md"))?;
    ensure!(
        sha256(&contract) == CONTRACT_SHA256,
        "F4-SYMMETRY contract hash mismatch"
    );
    let streams = read_streams(study)?;
    let expected_count: usize = streams.iter().map(|stream| stream.expected.len()).sum();
    ensure!(
        expected_count == 13420,
        "prior streams contain {expected_count} rows, expected 13,420"
    );
    reconcile_rows(study, lineage, out, &streams)?;
    forward_reconciliation(study, lineage, out)?;
    write_raw_files(study, lineage, out, &streams)?;
    let predictor_bytes = fs::read(out.join("RAW-PREDICTORS.bin"))?;
    let truth_bytes = fs::read(out.join("RAW-SCORING-TRUTH.bin"))?;
    write_json(
        &out.join("NATIVE-COLLECTION-RECEIPT.json"),
        &json!({
            "schema":"F4-SYMMETRY-01-native-collection-v1", "status":"PASS", "rows":13420,
            "predictor_bytes":predictor_bytes.len(), "truth_bytes":truth_bytes.len(),
            "predictor_sha256":sha256(&predictor_bytes), "truth_sha256":sha256(&truth_bytes),
            "reference_blind_predictors":true, "measured_namespace_created":false
        }),
    )?;
    Ok(())
}

pub fn collect(study: &Path, lineage: &Path, out: &Path) -> Result<()> {
    let result = collect_inner(study, lineage, out);
    if let Err(error) = &result {
        let row_receipt = out.join("ROW-RECONCILIATION-RECEIPT.json");
        let forward_receipt = out.join("FORWARD-P-RECONCILIATION-RECEIPT.json");
        let (path, gate_id) = if !row_receipt.exists() {
            (row_receipt, "ROW_RECONCILIATION")
        } else if !forward_receipt.exists() {
            (forward_receipt, "FORWARD_PROBABILITY")
        } else {
            (
                out.join("NATIVE-COLLECTION-STOP-RECEIPT.json"),
                "NATIVE_COLLECTION",
            )
        };
        if !path.exists() {
            let _ = write_json(
                &path,
                &json!({
                    "schema":"F4-SYMMETRY-01-failed-gate-v1",
                    "gate_id":gate_id,
                    "status":"STOP",
                    "first_mismatch":format!("{error:#}"),
                    "measured_namespace_created":false
                }),
            );
        }
    }
    result
}

#[path = "symmetry_fixtures.rs"]
mod fixture_impl;
pub use fixture_impl::fixtures;

#[cfg(test)]
#[path = "symmetry_tests.rs"]
mod tests;
