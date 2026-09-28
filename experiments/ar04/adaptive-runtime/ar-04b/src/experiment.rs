use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::process::Command;

use bytemuck::cast_slice;
use sha2::{Digest, Sha256};

use crate::analysis;
use crate::frozen_protocol;
use crate::model::{self, Model, Sample, TRAIN_SAMPLES};
use crate::protocol::{
    self, CANDIDATE_PROPOSAL_SEEDS, Candidate, DATASET_COUNT, FrozenState, INITIALIZATION_COUNT,
    INITIALIZATION_SEEDS, MEASUREMENT_SEEDS, PANEL_COUNT, PANEL_SIZES, ReferenceScore,
    SENTINEL_DRAW_SEEDS, SENTINEL_ORDER_SEEDS, STATE_COUNT, STATE_STAGES, STATE_STREAM_SEEDS,
    SentinelMethod, SentinelScore, TRAINING_SEEDS,
};
use crate::stategen;

const PARENT_BRANCH: &str = "codex/ar-04a-continuation-conditioned-action-value-20260921";
const PARENT_COMMIT: &str = "6f731c135e56fc87cb7f6cdfaa0ae2b26cd8a0dd";
const EXPECTED_BRANCH: &str = "codex/ar-04b-generalization-objective-bridge-20260921";

struct DatasetBundle {
    train: [Sample; TRAIN_SAMPLES],
    measurement: [Sample; TRAIN_SAMPLES],
    sentinel_panels: Vec<Vec<Sample>>,
}

struct DataArtifact {
    dataset_id: usize,
    kind: &'static str,
    panel_id: Option<usize>,
    seed_a: u64,
    seed_b: Option<u64>,
    order_seed: Option<u64>,
    sample_count: usize,
    relative_path: String,
    sha256: String,
}

pub struct RunReport {
    pub states: usize,
    pub actions: usize,
    pub sentinel_rows: usize,
}

pub fn run(output_dir: &Path) -> io::Result<RunReport> {
    validate_source(output_dir)?;
    fs::create_dir_all(output_dir.join("data"))?;

    let (datasets, artifacts, unique_samples) = generate_datasets(output_dir)?;
    write_dataset_manifest(output_dir, &artifacts)?;

    let (states, candidates) = freeze_states_and_candidates(&datasets)?;
    if states.len() != STATE_COUNT || candidates.len() != STATE_COUNT {
        return Err(io::Error::other("AR-04B frozen state cardinality mismatch"));
    }
    write_frozen_state_artifacts(output_dir, &states, &candidates)?;

    // Candidate identities are now fixed. The final measurement arrays first enter
    // the scoring stage here; they were never inputs to state/action generation.
    let (reference_scores, sentinel_scores, max_reference_consistency_error) =
        score_actions(&datasets, &states, &candidates)?;
    write_reference_scores(output_dir, &states, &candidates, &reference_scores)?;
    write_sentinel_scores(output_dir, &sentinel_scores)?;
    analysis::analyze(
        output_dir,
        &states,
        &candidates,
        &reference_scores,
        &sentinel_scores,
    )?;

    let action_count = candidates.iter().map(Vec::len).sum();
    let integrity_valid = unique_samples
        && protocol::fresh_seeds_are_unique()
        && states.len() == STATE_COUNT
        && reference_scores.len() == action_count
        && sentinel_scores.len() == action_count * PANEL_COUNT * PANEL_SIZES.len() * 2
        && max_reference_consistency_error <= 2.0e-5;
    write_integrity_receipt(
        output_dir,
        &artifacts,
        &states,
        &candidates,
        reference_scores.len(),
        sentinel_scores.len(),
        unique_samples,
        max_reference_consistency_error,
        integrity_valid,
    )?;
    if !integrity_valid {
        return Err(io::Error::other("AR-04B integrity validation failed"));
    }
    Ok(RunReport {
        states: states.len(),
        actions: action_count,
        sentinel_rows: sentinel_scores.len(),
    })
}

fn validate_source(output_dir: &Path) -> io::Result<()> {
    if output_dir.exists() {
        return Err(io::Error::new(
            io::ErrorKind::AlreadyExists,
            format!(
                "refusing to overwrite AR-04B output {}",
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
        || !protocol::fresh_seeds_are_unique()
    {
        return Err(io::Error::other(format!(
            "AR-04B collection preflight failed: branch={branch}, commit={commit}, merge_base={parent}, dirty={dirty:?}"
        )));
    }
    Ok(())
}

fn freeze_states_and_candidates(
    datasets: &[DatasetBundle],
) -> io::Result<(Vec<FrozenState>, Vec<Vec<Candidate>>)> {
    let mut states = Vec::with_capacity(STATE_COUNT);
    let mut all_candidates = Vec::with_capacity(STATE_COUNT);
    for (dataset_id, dataset) in datasets.iter().enumerate() {
        for (initialization_id, &initialization_seed) in INITIALIZATION_SEEDS.iter().enumerate() {
            let cell_id = dataset_id * INITIALIZATION_COUNT + initialization_id;
            let stream_seed = STATE_STREAM_SEEDS[cell_id];
            let snapshots = stategen::capture_hash_reference_states(
                &dataset.train,
                initialization_seed,
                stream_seed,
                (cell_id % 8) as u8,
            );
            for (stage_index, stage) in STATE_STAGES.iter().copied().enumerate() {
                let state_id = states.len();
                let model = snapshots[stage_index];
                let proposal_seed = CANDIDATE_PROPOSAL_SEEDS[state_id];
                let actions =
                    protocol::build_candidates(&model, &dataset.train, proposal_seed, stage);
                if actions.is_empty() {
                    return Err(io::Error::other(format!(
                        "empty candidate universe at frozen state {state_id}"
                    )));
                }
                let state = FrozenState {
                    state_id,
                    cell_id,
                    dataset_id,
                    initialization_id,
                    stage,
                    initialization_seed,
                    state_stream_seed: stream_seed,
                    proposal_seed,
                    model,
                    training_loss: f64::from(model.loss(&dataset.train)),
                    state_fingerprint: frozen_protocol::runtime_parameter_fingerprint(&model),
                    candidate_fingerprint: protocol::candidate_fingerprint(&actions),
                };
                states.push(state);
                all_candidates.push(actions);
            }
        }
    }
    Ok((states, all_candidates))
}

fn generate_datasets(
    output_dir: &Path,
) -> io::Result<(Vec<DatasetBundle>, Vec<DataArtifact>, bool)> {
    let mut datasets = Vec::with_capacity(DATASET_COUNT);
    let mut artifacts = Vec::with_capacity(DATASET_COUNT * (2 + PANEL_COUNT));
    let mut sample_rows = hashbrown::HashSet::<[u32; 9]>::new();

    for dataset_id in 0..DATASET_COUNT {
        let train = model::generate_dataset(TRAINING_SEEDS[dataset_id]);
        let measurement = model::generate_dataset(MEASUREMENT_SEEDS[dataset_id]);
        let train_path = format!("data/training-{dataset_id:02}.bin");
        let measurement_path = format!("data/final-measurement-{dataset_id:02}.bin");
        artifacts.push(write_samples(
            output_dir,
            dataset_id,
            "training",
            None,
            TRAINING_SEEDS[dataset_id],
            None,
            None,
            &train_path,
            &train,
        )?);
        artifacts.push(write_samples(
            output_dir,
            dataset_id,
            "final_measurement",
            None,
            MEASUREMENT_SEEDS[dataset_id],
            None,
            None,
            &measurement_path,
            &measurement,
        )?);
        for sample in train.iter().chain(measurement.iter()) {
            sample_rows.insert(sample_key(sample));
        }

        let mut sentinel_panels = Vec::with_capacity(PANEL_COUNT);
        for panel_id in 0..PANEL_COUNT {
            let seed_index = dataset_id * PANEL_COUNT * 2 + panel_id * 2;
            let seed_a = SENTINEL_DRAW_SEEDS[seed_index];
            let seed_b = SENTINEL_DRAW_SEEDS[seed_index + 1];
            let order_seed = SENTINEL_ORDER_SEEDS[dataset_id * PANEL_COUNT + panel_id];
            let first = model::generate_dataset(seed_a);
            let second = model::generate_dataset(seed_b);
            let mut unshuffled = Vec::with_capacity(protocol::PANEL_SIZE);
            unshuffled.extend_from_slice(&first[..64]);
            unshuffled.extend_from_slice(&second[..64]);
            let order = protocol::sample_order(order_seed);
            let panel: Vec<_> = order.iter().map(|&index| unshuffled[index]).collect();
            if panel.len() != protocol::PANEL_SIZE {
                return Err(io::Error::other("sentinel panel cardinality mismatch"));
            }
            for sample in &panel {
                sample_rows.insert(sample_key(sample));
            }
            let relative_path = format!("data/sentinel-d{dataset_id:02}-p{panel_id:02}.bin");
            artifacts.push(write_samples(
                output_dir,
                dataset_id,
                "sentinel",
                Some(panel_id),
                seed_a,
                Some(seed_b),
                Some(order_seed),
                &relative_path,
                &panel,
            )?);
            sentinel_panels.push(panel);
        }
        datasets.push(DatasetBundle {
            train,
            measurement,
            sentinel_panels,
        });
    }

    let expected_rows = DATASET_COUNT * (TRAIN_SAMPLES * 2 + PANEL_COUNT * protocol::PANEL_SIZE);
    Ok((datasets, artifacts, sample_rows.len() == expected_rows))
}

fn sample_key(sample: &Sample) -> [u32; 9] {
    let mut key = [0_u32; 9];
    for (destination, value) in key.iter_mut().zip(sample.x) {
        *destination = value.to_bits();
    }
    key[8] = sample.target;
    key
}

#[allow(clippy::too_many_arguments)]
fn write_samples(
    output_dir: &Path,
    dataset_id: usize,
    kind: &'static str,
    panel_id: Option<usize>,
    seed_a: u64,
    seed_b: Option<u64>,
    order_seed: Option<u64>,
    relative_path: &str,
    samples: &[Sample],
) -> io::Result<DataArtifact> {
    let path = output_dir.join(relative_path);
    fs::write(&path, cast_slice(samples))?;
    Ok(DataArtifact {
        dataset_id,
        kind,
        panel_id,
        seed_a,
        seed_b,
        order_seed,
        sample_count: samples.len(),
        relative_path: relative_path.to_owned(),
        sha256: hex(&sha256_file(&path)?),
    })
}

fn score_actions(
    datasets: &[DatasetBundle],
    states: &[FrozenState],
    candidates: &[Vec<Candidate>],
) -> io::Result<(Vec<ReferenceScore>, Vec<SentinelScore>, f64)> {
    let action_count: usize = candidates.iter().map(Vec::len).sum();
    let mut references = Vec::with_capacity(action_count);
    let mut sentinel_rows = Vec::with_capacity(action_count * PANEL_COUNT * PANEL_SIZES.len() * 2);
    let mut max_reference_consistency_error = 0.0_f64;

    for state in states {
        let train = &datasets[state.dataset_id].train;
        let measurement = &datasets[state.dataset_id].measurement;
        let train_baseline = state.model.loss(train);
        let measurement_baseline = state.model.loss(measurement);
        let actions = &candidates[state.state_id];

        for action in actions {
            let candidate_model = apply_action(state.model, action);
            let train_utility = f64::from(train_baseline - candidate_model.loss(train));
            let measurement_utility =
                f64::from(measurement_baseline - candidate_model.loss(measurement));
            let train_per_example = per_example_utility(&state.model, &candidate_model, train);
            let measurement_per_example =
                per_example_utility(&state.model, &candidate_model, measurement);
            max_reference_consistency_error = max_reference_consistency_error
                .max((train_utility - train_per_example).abs())
                .max((measurement_utility - measurement_per_example).abs());
            references.push(ReferenceScore {
                state_id: state.state_id,
                action_id: action.action_id,
                training_utility: train_utility,
                measurement_utility,
            });
        }

        for (panel_id, panel) in datasets[state.dataset_id]
            .sentinel_panels
            .iter()
            .enumerate()
        {
            let panel_seed = SENTINEL_ORDER_SEEDS[state.dataset_id * PANEL_COUNT + panel_id];
            let gradients: Vec<_> = panel
                .iter()
                .map(|sample| state.model.gradient_one(sample).1)
                .collect();
            for sample_count in PANEL_SIZES {
                let subset = &panel[..sample_count];
                let baseline = state.model.loss(subset);
                for action in actions {
                    let candidate_model = apply_action(state.model, action);
                    let exact = f64::from(baseline - candidate_model.loss(subset));
                    let taylor_sum = gradients[..sample_count]
                        .iter()
                        .map(|gradient| {
                            -f64::from(
                                gradient[usize::from(action.left_parameter)] * action.left_delta
                                    + gradient[usize::from(action.right_parameter)]
                                        * action.right_delta,
                            )
                        })
                        .sum::<f64>();
                    let taylor = taylor_sum / sample_count as f64;
                    for (method, utility) in [
                        (SentinelMethod::Exact, exact),
                        (SentinelMethod::Taylor, taylor),
                    ] {
                        sentinel_rows.push(SentinelScore {
                            state_id: state.state_id,
                            cell_id: state.cell_id,
                            dataset_id: state.dataset_id,
                            initialization_id: state.initialization_id,
                            stage: state.stage,
                            action_id: action.action_id,
                            panel_id: panel_id as u8,
                            panel_seed,
                            sample_count: sample_count as u16,
                            method,
                            utility,
                        });
                    }
                }
            }
        }
    }
    if references.len() != action_count
        || sentinel_rows.len() != action_count * PANEL_COUNT * PANEL_SIZES.len() * 2
        || sentinel_rows.iter().any(|row| !row.utility.is_finite())
        || references
            .iter()
            .any(|row| !row.training_utility.is_finite() || !row.measurement_utility.is_finite())
    {
        return Err(io::Error::other(
            "AR-04B score cardinality or finiteness failed",
        ));
    }
    Ok((references, sentinel_rows, max_reference_consistency_error))
}

fn apply_action(mut model: Model, action: &Candidate) -> Model {
    model.parameters[usize::from(action.left_parameter)] += action.left_delta;
    model.parameters[usize::from(action.right_parameter)] += action.right_delta;
    model
}

fn per_example_utility(model: &Model, candidate: &Model, samples: &[Sample]) -> f64 {
    samples
        .iter()
        .map(|sample| f64::from(model.loss_one(sample) - candidate.loss_one(sample)))
        .sum::<f64>()
        / samples.len() as f64
}

fn write_dataset_manifest(output_dir: &Path, rows: &[DataArtifact]) -> io::Result<()> {
    let mut output = BufWriter::new(File::create(output_dir.join("dataset-manifest.csv"))?);
    writeln!(
        output,
        "dataset_id,kind,panel_id,seed_a,seed_b,order_seed,sample_count,path,sha256"
    )?;
    for row in rows {
        writeln!(
            output,
            "{},{},{},{:016x},{},{},{},{},{}",
            row.dataset_id,
            row.kind,
            row.panel_id
                .map_or_else(|| "".to_owned(), |value| value.to_string()),
            row.seed_a,
            row.seed_b
                .map_or_else(|| "".to_owned(), |value| format!("{value:016x}")),
            row.order_seed
                .map_or_else(|| "".to_owned(), |value| format!("{value:016x}")),
            row.sample_count,
            row.relative_path,
            row.sha256
        )?;
    }
    output.flush()
}

fn write_frozen_state_artifacts(
    output_dir: &Path,
    states: &[FrozenState],
    candidates: &[Vec<Candidate>],
) -> io::Result<()> {
    let mut state_output = BufWriter::new(File::create(output_dir.join("state-manifest.csv"))?);
    writeln!(
        state_output,
        "state_id,cell_id,dataset_id,initialization_id,stage,initialization_seed,state_stream_seed,proposal_seed,training_loss,state_fingerprint,candidate_fingerprint,candidate_count"
    )?;
    let mut model_output = BufWriter::new(File::create(output_dir.join("model-states.bin"))?);
    let mut candidate_output =
        BufWriter::new(File::create(output_dir.join("candidate-manifest.csv"))?);
    writeln!(
        candidate_output,
        "state_id,cell_id,dataset_id,initialization_id,stage,action_id,block_id,left_parameter,right_parameter,left_rank,right_rank,left_delta,right_delta"
    )?;
    for (state, actions) in states.iter().zip(candidates) {
        writeln!(
            state_output,
            "{},{},{},{},{},{:016x},{:016x},{:016x},{:.12e},{:016x},{:016x},{}",
            state.state_id,
            state.cell_id,
            state.dataset_id,
            state.initialization_id,
            state.stage,
            state.initialization_seed,
            state.state_stream_seed,
            state.proposal_seed,
            state.training_loss,
            state.state_fingerprint,
            state.candidate_fingerprint,
            actions.len()
        )?;
        for parameter in state.model.parameters {
            model_output.write_all(&parameter.to_le_bytes())?;
        }
        for action in actions {
            writeln!(
                candidate_output,
                "{},{},{},{},{},{},{},{},{},{},{},{:.9},{:.9}",
                state.state_id,
                state.cell_id,
                state.dataset_id,
                state.initialization_id,
                state.stage,
                action.action_id,
                action.block_id,
                action.left_parameter,
                action.right_parameter,
                action.left_rank,
                action.right_rank,
                action.left_delta,
                action.right_delta
            )?;
        }
    }
    state_output.flush()?;
    model_output.flush()?;
    candidate_output.flush()
}

fn write_reference_scores(
    output_dir: &Path,
    states: &[FrozenState],
    candidates: &[Vec<Candidate>],
    rows: &[ReferenceScore],
) -> io::Result<()> {
    let mut output = BufWriter::new(File::create(
        output_dir.join("reference-action-scores.csv"),
    )?);
    writeln!(
        output,
        "state_id,cell_id,dataset_id,initialization_id,stage,action_id,training_exact,final_measurement_exact"
    )?;
    for row in rows {
        let state = &states[row.state_id];
        let action = candidates[row.state_id][usize::from(row.action_id)];
        debug_assert_eq!(action.action_id, row.action_id);
        writeln!(
            output,
            "{},{},{},{},{},{},{:.12e},{:.12e}",
            state.state_id,
            state.cell_id,
            state.dataset_id,
            state.initialization_id,
            state.stage,
            row.action_id,
            row.training_utility,
            row.measurement_utility
        )?;
    }
    output.flush()
}

fn write_sentinel_scores(output_dir: &Path, rows: &[SentinelScore]) -> io::Result<()> {
    let mut output = BufWriter::new(File::create(output_dir.join("sentinel-action-scores.csv"))?);
    writeln!(
        output,
        "state_id,cell_id,dataset_id,initialization_id,stage,action_id,panel_id,panel_seed,sample_count,method,utility"
    )?;
    for row in rows {
        writeln!(
            output,
            "{},{},{},{},{},{},{},{:016x},{},{},{:.12e}",
            row.state_id,
            row.cell_id,
            row.dataset_id,
            row.initialization_id,
            row.stage,
            row.action_id,
            row.panel_id,
            row.panel_seed,
            row.sample_count,
            row.method.name(),
            row.utility
        )?;
    }
    output.flush()
}

#[allow(clippy::too_many_arguments)]
fn write_integrity_receipt(
    output_dir: &Path,
    artifacts: &[DataArtifact],
    states: &[FrozenState],
    candidates: &[Vec<Candidate>],
    reference_rows: usize,
    sentinel_rows: usize,
    unique_samples: bool,
    consistency_error: f64,
    valid: bool,
) -> io::Result<()> {
    let source_commit = git_output(&["rev-parse", "HEAD"])?;
    let executable_hash = hex(&sha256_file(&std::env::current_exe()?)?);
    let output_files = [
        "dataset-manifest.csv",
        "state-manifest.csv",
        "candidate-manifest.csv",
        "model-states.bin",
        "reference-action-scores.csv",
        "sentinel-action-scores.csv",
        "ranking-metrics.csv",
        "immediate-vs-generalization-ranking.json",
        "taylor-fidelity.json",
    ];
    let output_hashes: Vec<_> = output_files
        .iter()
        .map(|relative| Ok((*relative, hex(&sha256_file(&output_dir.join(relative))?))))
        .collect::<io::Result<_>>()?;
    let mut output = BufWriter::new(File::create(output_dir.join("integrity-receipt.json"))?);
    writeln!(output, "{{")?;
    writeln!(
        output,
        "  \"protocol\": \"AR-04B-generalization-objective-bridge-2026-09-21\","
    )?;
    writeln!(output, "  \"parent_branch\": \"{PARENT_BRANCH}\",")?;
    writeln!(output, "  \"parent_result_commit\": \"{PARENT_COMMIT}\",")?;
    writeln!(output, "  \"source_branch\": \"{EXPECTED_BRANCH}\",")?;
    writeln!(output, "  \"frozen_source_commit\": \"{source_commit}\",")?;
    writeln!(
        output,
        "  \"optimized_executable_sha256\": \"{executable_hash}\","
    )?;
    writeln!(output, "  \"source_clean_at_collection\": true,")?;
    writeln!(output, "  \"training_controller_effect\": false,")?;
    writeln!(
        output,
        "  \"sentinel_or_measurement_used_for_state_or_candidate_generation\": false,"
    )?;
    writeln!(output, "  \"integrity_valid\": {valid},")?;
    writeln!(
        output,
        "  \"datasets\": {DATASET_COUNT}, \"initializations\": {INITIALIZATION_COUNT}, \"crossed_cells\": {}, \"states\": {},",
        protocol::CELL_COUNT,
        states.len()
    )?;
    writeln!(
        output,
        "  \"panel_replicates_per_dataset\": {PANEL_COUNT}, \"sentinel_sizes\": [8,16,32,64,128],"
    )?;
    writeln!(
        output,
        "  \"unique_role_seed_count\": {}, \"all_role_seeds_unique\": {},",
        seed_count(),
        protocol::fresh_seeds_are_unique()
    )?;
    writeln!(
        output,
        "  \"all_training_sentinel_measurement_rows_disjoint\": {unique_samples},"
    )?;
    writeln!(
        output,
        "  \"candidate_action_count\": {}, \"reference_score_rows\": {reference_rows}, \"sentinel_score_rows\": {sentinel_rows},",
        candidates.iter().map(Vec::len).sum::<usize>()
    )?;
    writeln!(
        output,
        "  \"max_aggregate_vs_per_example_utility_error\": {:.12e},",
        consistency_error
    )?;
    writeln!(output, "  \"data_artifacts\": [")?;
    for (index, row) in artifacts.iter().enumerate() {
        writeln!(
            output,
            "    {{\"dataset_id\":{},\"kind\":\"{}\",\"panel_id\":{},\"samples\":{},\"path\":\"{}\",\"sha256\":\"{}\"}}{}",
            row.dataset_id,
            row.kind,
            row.panel_id
                .map_or_else(|| "null".to_owned(), |value| value.to_string()),
            row.sample_count,
            row.relative_path,
            row.sha256,
            if index + 1 == artifacts.len() {
                ""
            } else {
                ","
            }
        )?;
    }
    writeln!(output, "  ],\n  \"derived_output_sha256\": [")?;
    for (index, (path, hash)) in output_hashes.iter().enumerate() {
        writeln!(
            output,
            "    {{\"path\":\"{}\",\"sha256\":\"{}\"}}{}",
            path,
            hash,
            if index + 1 == output_hashes.len() {
                ""
            } else {
                ","
            }
        )?;
    }
    writeln!(output, "  ]")?;
    writeln!(output, "}}")?;
    output.flush()
}

fn seed_count() -> usize {
    protocol::TRAINING_SEEDS.len()
        + protocol::MEASUREMENT_SEEDS.len()
        + protocol::SENTINEL_DRAW_SEEDS.len()
        + protocol::SENTINEL_ORDER_SEEDS.len()
        + protocol::INITIALIZATION_SEEDS.len()
        + protocol::STATE_STREAM_SEEDS.len()
        + protocol::CANDIDATE_PROPOSAL_SEEDS.len()
}

fn git_output(arguments: &[&str]) -> io::Result<String> {
    let output = Command::new("git").args(arguments).output()?;
    if !output.status.success() {
        return Err(io::Error::other(format!(
            "git {} failed: {}",
            arguments.join(" "),
            String::from_utf8_lossy(&output.stderr)
        )));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn sha256_file(path: &Path) -> io::Result<[u8; 32]> {
    let bytes = fs::read(path)?;
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    Ok(hasher.finalize().into())
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
