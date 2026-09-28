use crate::{
    graph::{Edge, Graph},
    reach_sim::Sim,
    task::{Pattern, Task},
};
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::{self, File},
    io::{BufWriter, Write},
    path::Path,
};

pub(crate) const TAU: f32 = 16.0;
pub(crate) const ETA: f32 = 0.05;
pub(crate) const REFERENCE_LR: f64 = 0.05;
pub(crate) const EPS: f32 = 1e-12;

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

#[derive(Serialize, Deserialize)]
struct F0 {
    coordinate: usize,
    pre: u32,
    post: u32,
    pre_degree: usize,
    post_degree: usize,
    anatomical_mb_sign: f32,
    substrate: String,
    side: String,
}

#[derive(Serialize, Deserialize)]
struct F1 {
    weight_before: f32,
    eligibility: f32,
    presynaptic_spike_count: u32,
    postsynaptic_deviation: f32,
    local_signed_contribution: f32,
    weight_sign: i8,
}

#[derive(Serialize, Deserialize)]
struct F2 {
    eligibility_history: Vec<f32>,
    weight_history: Vec<f32>,
    local_sign_history: Vec<i8>,
}

#[derive(Serialize, Deserialize)]
struct F3a {
    reward: f32,
    dan_mean: f32,
    feedback_mean: f32,
    gain_for_post: f32,
    scale: f32,
    native_update_consumed: bool,
}

#[derive(Serialize, Deserialize)]
struct F3b {
    eligibility_l1: f32,
    active_eligibility_fraction: f32,
    global_work: u64,
    global_events: u64,
}

#[derive(Serialize, Deserialize)]
struct Row {
    schema: String,
    substrate: String,
    side: String,
    block: u64,
    trial: usize,
    coordinate: usize,
    inclusion_probability: f64,
    reference_value: f32,
    target: i8,
    native_proposed: f32,
    primary_support: bool,
    f0: F0,
    f1: F1,
    f2: F2,
    f3a: F3a,
    f3b: F3b,
    f4_snapshot_id: String,
}

#[derive(Serialize, Deserialize)]
struct PatternSnapshot {
    edges: Vec<usize>,
    offsets: Vec<usize>,
    dan: Vec<f32>,
}

#[derive(Serialize, Deserialize)]
struct F4Snapshot {
    schema: String,
    id: String,
    trial: usize,
    weights: Vec<f32>,
    bias: Vec<f32>,
    denom: Vec<f32>,
    action_sign: Vec<f32>,
    labels: Vec<bool>,
    schedule: Vec<Vec<usize>>,
    cue_patterns: Vec<PatternSnapshot>,
}

#[derive(Serialize)]
struct FixtureReceipt {
    schema: &'static str,
    status: &'static str,
    telemetry_on_off_identical: bool,
    steps: usize,
    sampled_coordinates: Vec<usize>,
    row_count: usize,
    snapshot_count: usize,
    rows_sha256: String,
    snapshots_sha256: String,
    source_mapping: &'static str,
}

#[derive(Serialize)]
struct ReconstructionReceipt {
    schema: &'static str,
    status: &'static str,
    rows_checked: usize,
    target_matches: usize,
    value_mismatches: usize,
    max_abs_error: f32,
    tolerance: f32,
}

fn sigmoid(x: f64) -> f64 {
    1.0 / (1.0 + (-x.clamp(-40.0, 40.0)).exp())
}

fn expected_score(weights: &[f32], sim: &Sim<'_>, pattern: &Pattern) -> f64 {
    let mut score = 0.0;
    for j in 0..sim.post.len() {
        let mut drive = 0.0;
        for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] {
            drive += f64::from(weights[ix]);
        }
        let p = sigmoid(2.0 * (drive / f64::from(sim.denom[j]) - f64::from(sim.bias[j])));
        score += f64::from(sim.action_sign[j]) * (p - 0.5);
    }
    score
}

pub(crate) fn reference_delta_into(
    sim: &Sim<'_>,
    task: &Task,
    lr: f64,
    out: &mut [f32],
    grad: &mut [f64],
) {
    grad.fill(0.0);
    for (pattern, &label) in task.patterns[..task.cues].iter().zip(&task.labels) {
        let score = expected_score(&sim.weights, sim, pattern);
        let y = if label { 1.0 } else { -1.0 };
        let coeff = -y * 4.0 * sigmoid(-y * 4.0 * score);
        for j in 0..sim.post.len() {
            let mut drive = 0.0;
            for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] {
                drive += f64::from(sim.weights[ix]);
            }
            let p = sigmoid(2.0 * (drive / f64::from(sim.denom[j]) - f64::from(sim.bias[j])));
            let d = f64::from(sim.action_sign[j]) * 2.0 * p * (1.0 - p) / f64::from(sim.denom[j]);
            for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] {
                grad[ix] += coeff * d / task.cues as f64;
            }
        }
    }
    for (value, &g) in out.iter_mut().zip(grad.iter()) {
        *value = (-lr * g) as f32;
    }
}

fn sha256(path: &Path) -> Result<String> {
    let bytes = fs::read(path)?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

pub(crate) fn target(value: f32) -> i8 {
    if value > EPS {
        1
    } else if value < -EPS {
        -1
    } else {
        0
    }
}

pub(crate) fn pre_degree(graph: &Graph) -> Vec<usize> {
    let mut degree = vec![0_usize; graph.kc_mb.n_pre];
    for Edge { pre, .. } in &graph.kc_mb.edges {
        degree[*pre as usize] += 1;
    }
    degree
}

fn pattern_spikes(task: &Task, trial: usize, edge_count: usize) -> Vec<u32> {
    let mut spikes = vec![0_u32; edge_count];
    for &pattern_index in &task.schedule[trial % task.schedule.len()] {
        for &edge in &task.patterns[pattern_index].edges {
            spikes[edge] += 1;
        }
    }
    spikes
}

fn pattern_snapshot(pattern: &Pattern) -> PatternSnapshot {
    PatternSnapshot {
        edges: pattern.edges.clone(),
        offsets: pattern.offsets.clone(),
        dan: pattern.dan.clone(),
    }
}

fn run_trace(
    graph: &Graph,
    task: &Task,
    sim_seed: u64,
    substrate: &'static str,
    side: &'static str,
    block: u64,
    coordinates: &[usize],
    steps: usize,
    telemetry: bool,
) -> Result<(Vec<Row>, Vec<F4Snapshot>, Vec<String>)> {
    let mut sim = Sim::new(graph, sim_seed, TAU, ETA);
    let mut local_abs = vec![0.0; sim.weights.len()];
    let mut local_signed = vec![0.0; sim.weights.len()];
    let mut native_delta = vec![0.0; sim.weights.len()];
    let mut reference = vec![0.0; sim.weights.len()];
    let mut grad = vec![0.0; sim.weights.len()];
    let mut rows = Vec::new();
    let mut snapshots = Vec::new();
    let mut digests = Vec::with_capacity(steps + 1);
    let pre_degree = pre_degree(graph);
    let mut histories: Vec<Vec<f32>> = vec![Vec::new(); sim.weights.len()];
    let mut weight_histories: Vec<Vec<f32>> = vec![Vec::new(); sim.weights.len()];
    let mut sign_histories: Vec<Vec<i8>> = vec![Vec::new(); sim.weights.len()];
    digests.push(sim.digest());

    for trial in 0..steps {
        let before_weights = sim.weights.clone();
        let (_correct, reward) = if telemetry {
            sim.begin_trial_with_local(task, trial, &mut local_abs, &mut local_signed)
        } else {
            let result = sim.begin_trial(task, trial);
            local_abs.fill(0.0);
            local_signed.fill(0.0);
            result
        };
        reference_delta_into(&sim, task, REFERENCE_LR, &mut reference, &mut grad);
        sim.proposed_delta_into(reward, &mut native_delta);
        let spikes = pattern_spikes(task, trial, sim.weights.len());
        let snapshot_id = format!("fixture-{trial:04}");
        if telemetry {
            snapshots.push(F4Snapshot {
                schema: "FLY-REACH-03-f4-snapshot-v1".to_string(),
                id: snapshot_id.clone(),
                trial,
                weights: before_weights.clone(),
                bias: sim.bias.clone(),
                denom: sim.denom.clone(),
                action_sign: sim.action_sign.clone(),
                labels: task.labels.clone(),
                schedule: task.schedule.clone(),
                cue_patterns: task.patterns[..task.cues]
                    .iter()
                    .map(pattern_snapshot)
                    .collect(),
            });
            for &coordinate in coordinates {
                let edge = graph.kc_mb.edges[coordinate];
                let post = edge.post as usize;
                let f0 = F0 {
                    coordinate,
                    pre: edge.pre,
                    post: edge.post,
                    pre_degree: pre_degree[edge.pre as usize],
                    post_degree: graph.kc_mb.row(post).len(),
                    anatomical_mb_sign: graph.mb_sign[post],
                    substrate: substrate.to_string(),
                    side: side.to_string(),
                };
                let weight = before_weights[coordinate];
                let f1 = F1 {
                    weight_before: weight,
                    eligibility: sim.eligibility[coordinate],
                    presynaptic_spike_count: spikes[coordinate],
                    postsynaptic_deviation: sim.post[post] - sim.baseline[post],
                    local_signed_contribution: local_signed[coordinate],
                    weight_sign: if weight > EPS {
                        1
                    } else if weight < -EPS {
                        -1
                    } else {
                        0
                    },
                };
                histories[coordinate].push(sim.eligibility[coordinate]);
                weight_histories[coordinate].push(weight);
                sign_histories[coordinate].push(if local_signed[coordinate] > EPS {
                    1
                } else if local_signed[coordinate] < -EPS {
                    -1
                } else {
                    0
                });
                let f2 = F2 {
                    eligibility_history: histories[coordinate]
                        .iter()
                        .rev()
                        .take(32)
                        .copied()
                        .collect(),
                    weight_history: weight_histories[coordinate]
                        .iter()
                        .rev()
                        .take(32)
                        .copied()
                        .collect(),
                    local_sign_history: sign_histories[coordinate]
                        .iter()
                        .rev()
                        .take(32)
                        .copied()
                        .collect(),
                };
                let dan_mean = sim.dan.iter().sum::<f32>() / sim.dan.len().max(1) as f32;
                let feedback_mean =
                    sim.feedback.iter().sum::<f32>() / sim.feedback.len().max(1) as f32;
                let eligibility_l1 = sim.eligibility.iter().map(|value| value.abs()).sum();
                let active_count = sim
                    .eligibility
                    .iter()
                    .filter(|value| value.abs() > EPS)
                    .count();
                rows.push(Row {
                    schema: "FLY-REACH-03-row-v1".to_string(),
                    substrate: substrate.to_string(),
                    side: side.to_string(),
                    block,
                    trial,
                    coordinate,
                    inclusion_probability: 1.0,
                    reference_value: reference[coordinate],
                    target: target(reference[coordinate]),
                    native_proposed: native_delta[coordinate],
                    primary_support: native_delta[coordinate].abs() > EPS,
                    f0,
                    f1,
                    f2,
                    f3a: F3a {
                        reward,
                        dan_mean,
                        feedback_mean,
                        gain_for_post: sim.gain[post],
                        scale: sim.scale,
                        native_update_consumed: true,
                    },
                    f3b: F3b {
                        eligibility_l1,
                        active_eligibility_fraction: active_count as f32
                            / sim.eligibility.len().max(1) as f32,
                        global_work: sim.work,
                        global_events: sim.events,
                    },
                    f4_snapshot_id: snapshot_id.clone(),
                });
            }
        }
        sim.apply_delta(&native_delta);
        ensure!(
            sim.finite(),
            "fixture native state became nonfinite at trial {trial}"
        );
        digests.push(sim.digest());
    }
    Ok((rows, snapshots, digests))
}

pub fn run_fixture(study: &Path, lineage: &Path) -> Result<()> {
    let graph = crate::graph::load(lineage, "fly", "L", -1.0)?;
    let bank: TrainBank = serde_json::from_slice(&fs::read(
        lineage.join("inputs/banks/qualification-training.json"),
    )?)?;
    let block = bank.blocks.get("92000").context("fixture block 92000")?;
    ensure!(block.cue_count == block.labels.len());
    let task = Task::new(
        &graph,
        block.task_seed,
        block.labels.clone(),
        block.schedule.clone(),
    );
    let coordinates = vec![
        0,
        graph.kc_mb.edges.len() / 2,
        graph.kc_mb.edges.len().saturating_sub(1),
    ];
    let steps = 4;
    let (rows_on, snapshots, on_digests) = run_trace(
        &graph,
        &task,
        block.task_seed,
        "fly",
        "L",
        92000,
        &coordinates,
        steps,
        true,
    )?;
    let (_, _, off_digests) = run_trace(
        &graph,
        &task,
        block.task_seed,
        "fly",
        "L",
        92000,
        &coordinates,
        steps,
        false,
    )?;
    ensure!(
        on_digests == off_digests,
        "telemetry changed native trajectory"
    );

    let output_dir = study.join("artifacts/preimplementation/collector-fixture");
    fs::create_dir_all(&output_dir)?;
    let rows_path = output_dir.join("rows.jsonl");
    let snapshots_path = output_dir.join("f4-snapshots.jsonl");
    let mut rows_file = BufWriter::new(File::create(&rows_path)?);
    for row in &rows_on {
        serde_json::to_writer(&mut rows_file, row)?;
        rows_file.write_all(b"\n")?;
    }
    rows_file.flush()?;
    let mut snapshots_file = BufWriter::new(File::create(&snapshots_path)?);
    for snapshot in &snapshots {
        serde_json::to_writer(&mut snapshots_file, snapshot)?;
        snapshots_file.write_all(b"\n")?;
    }
    snapshots_file.flush()?;
    let receipt = FixtureReceipt {
        schema: "FLY-REACH-03-collector-fixture-receipt-v1",
        status: "PASS",
        telemetry_on_off_identical: true,
        steps,
        sampled_coordinates: coordinates,
        row_count: rows_on.len(),
        snapshot_count: snapshots.len(),
        rows_sha256: sha256(&rows_path)?,
        snapshots_sha256: sha256(&snapshots_path)?,
        source_mapping: "pre_trace=per-trial presynaptic edge spike count; post_trace=post-baseline deviation; native proposal=proposed_delta_into before apply_delta",
    };
    fs::write(
        output_dir.join("COLLECTOR-FIXTURE-RECEIPT.json"),
        serde_json::to_vec_pretty(&receipt)?,
    )?;
    Ok(())
}

pub fn audit_f4_fixture(study: &Path, lineage: &Path) -> Result<()> {
    let graph = crate::graph::load(lineage, "fly", "L", -1.0)?;
    let fixture = study.join("artifacts/preimplementation/collector-fixture");
    let rows_text = fs::read_to_string(fixture.join("rows.jsonl"))?;
    let rows: Vec<Row> = rows_text
        .lines()
        .map(serde_json::from_str)
        .collect::<std::result::Result<_, _>>()?;
    let snapshots_text = fs::read_to_string(fixture.join("f4-snapshots.jsonl"))?;
    let snapshots: Vec<F4Snapshot> = snapshots_text
        .lines()
        .map(serde_json::from_str)
        .collect::<std::result::Result<_, _>>()?;
    let by_id: BTreeMap<String, F4Snapshot> = snapshots
        .into_iter()
        .map(|snapshot| (snapshot.id.clone(), snapshot))
        .collect();
    let tolerance = 1e-6_f32;
    let mut target_matches = 0_usize;
    let mut value_mismatches = 0_usize;
    let mut max_abs_error = 0.0_f32;
    for row in &rows {
        let snapshot = by_id
            .get(&row.f4_snapshot_id)
            .context("missing F4 snapshot")?;
        let mut sim = Sim::new(&graph, 0x4f3a_03, TAU, ETA);
        sim.weights = snapshot.weights.clone();
        sim.bias = snapshot.bias.clone();
        sim.denom = snapshot.denom.clone();
        sim.action_sign = snapshot.action_sign.clone();
        let task = Task {
            patterns: snapshot
                .cue_patterns
                .iter()
                .map(|pattern| Pattern {
                    edges: pattern.edges.clone(),
                    offsets: pattern.offsets.clone(),
                    dan: pattern.dan.clone(),
                })
                .collect(),
            cues: snapshot.labels.len(),
            labels: snapshot.labels.clone(),
            schedule: snapshot.schedule.clone(),
        };
        let mut reference = vec![0.0_f32; sim.weights.len()];
        let mut grad = vec![0.0_f64; sim.weights.len()];
        reference_delta_into(&sim, &task, REFERENCE_LR, &mut reference, &mut grad);
        let error = (reference[row.coordinate] - row.reference_value).abs();
        max_abs_error = max_abs_error.max(error);
        if error > tolerance {
            value_mismatches += 1;
        }
        if target(reference[row.coordinate]) == row.target {
            target_matches += 1;
        }
    }
    let receipt = ReconstructionReceipt {
        schema: "FLY-REACH-03-f4-reconstruction-receipt-v1",
        status: if value_mismatches == 0 && target_matches == rows.len() {
            "PASS"
        } else {
            "STOP"
        },
        rows_checked: rows.len(),
        target_matches,
        value_mismatches,
        max_abs_error,
        tolerance,
    };
    fs::write(
        fixture.join("F4-RECONSTRUCTION-RECEIPT.json"),
        serde_json::to_vec_pretty(&receipt)?,
    )?;
    ensure!(receipt.status == "PASS", "F4 reconstruction audit failed");
    Ok(())
}
