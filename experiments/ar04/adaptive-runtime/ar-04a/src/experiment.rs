use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::process::Command;

use bytemuck::cast_slice;
use sha2::{Digest, Sha256};

use crate::analysis::{self, ActionOutcome};
use crate::frozen_protocol::{self, RuntimeProgram};
use crate::model::{self, LOWER_BOUND, Model, Sample, TRAIN_SAMPLES, UPPER_BOUND};
use crate::partition;
use crate::protocol::{
    self, ACTION_PROPOSAL_SEEDS, ActionCandidate, CONTINUATION_SEEDS, CONTINUATIONS_PER_STATE,
    Continuation, DATASET_COUNT, FrozenUpdate, HELDOUT_SEEDS, HORIZONS, INITIALIZATION_COUNT,
    INITIALIZATION_SEEDS, MIN_VALID_CONTINUATIONS, STATE_COUNT, STATE_STAGES, STATE_STREAM_SEEDS,
    StateRecord, TRAINING_SEEDS,
};
use crate::runtime_partition;

const PARENT_BRANCH: &str = "codex/ar-03d-r1-independent-5x5-20260921";
const PARENT_COMMIT: &str = "486b262cbd5c4eda6a217d897acccc0c25e60e6b";
const EXPECTED_BRANCH: &str = "codex/ar-04a-continuation-conditioned-action-value-20260921";
const RUNTIME_STEPS: usize = 4_200;
const COMMITS_PER_EVIDENCE: usize = 4;

#[derive(Clone, Copy)]
struct DatasetPair {
    train: [Sample; TRAIN_SAMPLES],
    heldout: [Sample; TRAIN_SAMPLES],
    train_sha256: [u8; 32],
    heldout_sha256: [u8; 32],
}

#[derive(Clone, Copy)]
struct DatasetHash {
    dataset_id: usize,
    train_seed: u64,
    heldout_seed: u64,
    train_sha256: [u8; 32],
    heldout_sha256: [u8; 32],
}

#[derive(Clone, Copy)]
struct CensorRecord {
    state_id: usize,
    continuation_id: usize,
    seed: u64,
    valid: bool,
    reason: &'static str,
    baseline_bound_events: usize,
    invalid_action_count: usize,
    first_invalid_action: Option<u16>,
    branch_bound_events: usize,
    source_state_fingerprint: u64,
    continuation_fingerprint: u64,
}

pub struct RunReport {
    pub state_count: usize,
    pub action_count: usize,
    pub valid_action_continuation_pairs: usize,
}

pub fn run(output_dir: &Path) -> io::Result<RunReport> {
    if output_dir.exists() {
        return Err(io::Error::new(
            io::ErrorKind::AlreadyExists,
            format!(
                "refusing to overwrite existing AR-04A output: {}",
                output_dir.display()
            ),
        ));
    }
    let source_commit = git_output(&["rev-parse", "HEAD"])?;
    let source_branch = git_output(&["rev-parse", "--abbrev-ref", "HEAD"])?;
    let common_ancestor = git_output(&["merge-base", PARENT_COMMIT, "HEAD"])?;
    let source_status = git_output(&["status", "--porcelain"])?;
    if !source_status.is_empty() {
        return Err(io::Error::other(format!(
            "refusing collection from dirty AR-04A source tree: {source_status}"
        )));
    }
    if source_branch != EXPECTED_BRANCH
        || common_ancestor != PARENT_COMMIT
        || source_commit.is_empty()
        || !protocol::fresh_seeds_are_unique()
    {
        return Err(io::Error::other(
            "AR-04A branch ancestry/source/seed validation failed",
        ));
    }
    fs::create_dir_all(output_dir)?;

    let datasets = generate_datasets(output_dir)?;
    let dataset_hashes: Vec<_> = datasets
        .iter()
        .enumerate()
        .map(|(dataset_id, dataset)| DatasetHash {
            dataset_id,
            train_seed: TRAINING_SEEDS[dataset_id],
            heldout_seed: HELDOUT_SEEDS[dataset_id],
            train_sha256: dataset.train_sha256,
            heldout_sha256: dataset.heldout_sha256,
        })
        .collect();

    let mut states = Vec::with_capacity(STATE_COUNT);
    let mut action_sets = Vec::with_capacity(STATE_COUNT);
    for (dataset_id, dataset) in datasets.iter().enumerate() {
        for (initialization_id, &initialization_seed) in INITIALIZATION_SEEDS.iter().enumerate() {
            let cell_id = dataset_id * INITIALIZATION_COUNT + initialization_id;
            let state_seed = STATE_STREAM_SEEDS[cell_id];
            let hash_partition_id = (cell_id % 8) as u8;
            let snapshots = capture_hash_reference_states(
                &dataset.train,
                initialization_seed,
                state_seed,
                hash_partition_id,
            );
            for (stage_index, stage) in STATE_STAGES.iter().copied().enumerate() {
                let state_id = states.len();
                let model = snapshots[stage_index];
                let action_proposal_seed = ACTION_PROPOSAL_SEEDS[state_id];
                let actions = protocol::build_action_set(
                    &model,
                    &dataset.train,
                    &dataset.heldout,
                    action_proposal_seed,
                    stage,
                );
                if actions.is_empty() {
                    return Err(io::Error::other(format!(
                        "empty frozen K2 candidate set at state {state_id}"
                    )));
                }
                let (parameter_rms, active_hidden_fraction) =
                    protocol::state_features(&model, &datasets[dataset_id].train);
                states.push(StateRecord {
                    cell_id,
                    dataset_id,
                    initialization_id,
                    initialization_seed,
                    state_id,
                    stage,
                    state_seed,
                    action_proposal_seed,
                    hash_partition_id,
                    model,
                    training_loss: f64::from(model.loss(&dataset.train)),
                    heldout_loss: f64::from(model.loss(&dataset.heldout)),
                    parameter_rms,
                    active_hidden_fraction,
                    fingerprint: frozen_protocol::runtime_parameter_fingerprint(&model),
                    candidate_fingerprint: protocol::action_fingerprint(&actions),
                    candidate_count: actions.len(),
                    valid_continuations: 0,
                    censored_continuations: 0,
                });
                action_sets.push(actions);
            }
        }
    }
    if states.len() != STATE_COUNT || action_sets.len() != STATE_COUNT {
        return Err(io::Error::other("AR-04A state cardinality mismatch"));
    }

    let mut continuations = Vec::with_capacity(protocol::CONTINUATION_COUNT);
    let mut censor_records = Vec::with_capacity(protocol::CONTINUATION_COUNT);
    let mut outcomes = Vec::new();
    let mut total_action_count = 0;
    let mut h0_consistency_error = 0.0_f64;
    for state_index in 0..states.len() {
        let state = states[state_index];
        let actions = &action_sets[state_index];
        total_action_count += actions.len();
        let train = &datasets[state.dataset_id].train;
        let heldout = &datasets[state.dataset_id].heldout;
        for replicate in 0..CONTINUATIONS_PER_STATE {
            let continuation_id = state_index * CONTINUATIONS_PER_STATE + replicate;
            let seed = CONTINUATION_SEEDS[continuation_id];
            let partition_id = ((state.state_id * 3 + replicate * 5) % 8) as u8;
            let continuation =
                generate_continuation(&state, train, continuation_id, seed, partition_id);
            let censor = assess_common_support(&state, actions, &continuation);
            let base_models = if censor.valid {
                let path = replay_path(&state.model, &continuation);
                if frozen_protocol::runtime_parameter_fingerprint(path.last().unwrap())
                    != frozen_protocol::runtime_parameter_fingerprint(&advance_clamped(
                        state.model,
                        &continuation.updates,
                    ))
                {
                    return Err(io::Error::other(
                        "frozen continuation replay fingerprint mismatch",
                    ));
                }
                Some(path)
            } else {
                None
            };
            if censor.valid {
                states[state_index].valid_continuations += 1;
                let models = base_models
                    .as_ref()
                    .expect("valid path has horizon snapshots");
                for action in actions {
                    for (horizon_index, &horizon) in HORIZONS.iter().enumerate() {
                        let noop_model = models[horizon_index];
                        let action_model = apply_initial_action(noop_model, action);
                        let noop_loss = f64::from(noop_model.loss(heldout));
                        let action_loss = f64::from(action_model.loss(heldout));
                        let q_h = state.heldout_loss - action_loss;
                        let delta_q_h = noop_loss - action_loss;
                        if horizon == 0 {
                            h0_consistency_error = h0_consistency_error
                                .max((delta_q_h - action.immediate_heldout_utility).abs());
                        }
                        outcomes.push(ActionOutcome {
                            state_id: state.state_id,
                            cell_id: state.cell_id,
                            dataset_id: state.dataset_id,
                            initialization_id: state.initialization_id,
                            stage: state.stage,
                            continuation_id,
                            continuation_seed: seed,
                            action_id: action.action_id,
                            horizon,
                            u0_train: action.immediate_train_utility,
                            u0_heldout: action.immediate_heldout_utility,
                            q_h,
                            delta_q_h,
                            noop_loss,
                            action_loss,
                            state_fingerprint: state.fingerprint,
                            continuation_fingerprint: continuation.sequence_fingerprint,
                            noop_fingerprint: frozen_protocol::runtime_parameter_fingerprint(
                                &noop_model,
                            ),
                            action_fingerprint: frozen_protocol::runtime_parameter_fingerprint(
                                &action_model,
                            ),
                        });
                    }
                }
            } else {
                states[state_index].censored_continuations += 1;
            }
            continuations.push(continuation);
            censor_records.push(censor);
        }
    }

    let expected_outcomes: usize = states
        .iter()
        .zip(&action_sets)
        .map(|(state, actions)| state.valid_continuations * actions.len() * HORIZONS.len())
        .sum();
    if outcomes.len() != expected_outcomes {
        return Err(io::Error::other(format!(
            "action-continuation cardinality mismatch: got {}, expected {expected_outcomes}",
            outcomes.len()
        )));
    }
    if h0_consistency_error > 2.0e-5 {
        return Err(io::Error::other(format!(
            "H=0 held-out action-effect consistency error too large: {h0_consistency_error}"
        )));
    }

    write_dataset_manifest(output_dir, &dataset_hashes)?;
    write_state_manifest(output_dir, &states)?;
    write_action_manifest(output_dir, &states, &action_sets)?;
    write_continuation_manifest(output_dir, &continuations)?;
    write_censor_ledger(output_dir, &censor_records)?;
    write_action_outcomes(output_dir, &outcomes)?;
    analysis::analyze(output_dir, &states, &action_sets, &outcomes)?;
    write_integrity_receipt(
        output_dir,
        &source_commit,
        &dataset_hashes,
        &states,
        &action_sets,
        &continuations,
        &censor_records,
        &outcomes,
        h0_consistency_error,
    )?;
    Ok(RunReport {
        state_count: states.len(),
        action_count: total_action_count,
        valid_action_continuation_pairs: outcomes.len() / HORIZONS.len(),
    })
}

fn generate_datasets(output_dir: &Path) -> io::Result<Vec<DatasetPair>> {
    let mut datasets = Vec::with_capacity(DATASET_COUNT);
    for dataset_id in 0..DATASET_COUNT {
        let train = model::generate_dataset(TRAINING_SEEDS[dataset_id]);
        let heldout = model::generate_dataset(HELDOUT_SEEDS[dataset_id]);
        let train_path = output_dir.join(format!("training-dataset-{dataset_id:02}.bin"));
        let heldout_path = output_dir.join(format!("heldout-dataset-{dataset_id:02}.bin"));
        fs::write(&train_path, cast_slice(&train))?;
        fs::write(&heldout_path, cast_slice(&heldout))?;
        datasets.push(DatasetPair {
            train,
            heldout,
            train_sha256: sha256_file(&train_path)?,
            heldout_sha256: sha256_file(&heldout_path)?,
        });
    }
    Ok(datasets)
}

fn capture_hash_reference_states(
    train: &[Sample; TRAIN_SAMPLES],
    initialization_seed: u64,
    stream_seed: u64,
    hash_partition_id: u8,
) -> Vec<Model> {
    let partition_ids = partition::hash_placebo(hash_partition_id);
    let mut model = Model::initial(initialization_seed);
    let mut snapshots = Vec::with_capacity(STATE_STAGES.len());
    let mut proposal = [train[0]; model::BATCH_SIZE];
    let mut verifier = [train[0]; model::VERIFIER_SIZE];
    let mut active_round = usize::MAX;
    for global_commit in 0..RUNTIME_STEPS {
        let evidence_round = global_commit / COMMITS_PER_EVIDENCE;
        if active_round != evidence_round {
            let proposal_indices = frozen_protocol::proposal_indices(stream_seed, evidence_round);
            proposal = std::array::from_fn(|index| train[proposal_indices[index]]);
            let panel_indices =
                runtime_partition::sample_panel(&partition_ids, stream_seed, evidence_round);
            verifier = std::array::from_fn(|index| train[panel_indices[index]]);
            active_round = evidence_round;
        }
        let (program, _) = frozen_protocol::select_runtime_program(
            &model,
            &proposal,
            &verifier,
            global_commit % model::PARAMS,
        );
        if let Some(program) = program {
            frozen_protocol::commit_runtime_program(&mut model, program);
        }
        let step = global_commit + 1;
        if STATE_STAGES.contains(&step) {
            if snapshots.len() >= STATE_STAGES.len() {
                unreachable!("each stage is captured exactly once");
            }
            snapshots.push(model);
        }
    }
    assert_eq!(snapshots.len(), STATE_STAGES.len());
    snapshots
}

fn generate_continuation(
    state: &StateRecord,
    train: &[Sample; TRAIN_SAMPLES],
    continuation_id: usize,
    seed: u64,
    hash_partition_id: u8,
) -> Continuation {
    let partition_ids = partition::hash_placebo(hash_partition_id);
    let mut model = state.model;
    let mut proposal = [train[0]; model::BATCH_SIZE];
    let mut verifier = [train[0]; model::VERIFIER_SIZE];
    let mut active_round = usize::MAX;
    let mut proposal_fingerprints =
        Vec::with_capacity(HORIZONS[HORIZONS.len() - 1] / COMMITS_PER_EVIDENCE);
    let mut panel_fingerprints = Vec::with_capacity(proposal_fingerprints.capacity());
    let mut updates = Vec::with_capacity(HORIZONS[HORIZONS.len() - 1]);
    let mut exogenous_fingerprint = 0xcbf2_9ce4_8422_2325_u64;
    let mut sequence_fingerprint = 0xcbf2_9ce4_8422_2325_u64;
    let mut baseline_bound_events = 0;
    for local_commit in 0..HORIZONS[HORIZONS.len() - 1] {
        let global_commit = state.stage + local_commit;
        let evidence_round = global_commit / COMMITS_PER_EVIDENCE;
        if active_round != evidence_round {
            let proposal_indices = frozen_protocol::proposal_indices(seed, evidence_round);
            proposal = std::array::from_fn(|index| train[proposal_indices[index]]);
            let panel_indices =
                runtime_partition::sample_panel(&partition_ids, seed, evidence_round);
            verifier = std::array::from_fn(|index| train[panel_indices[index]]);
            let proposal_hash = runtime_partition::indices_fingerprint(&proposal_indices);
            let panel_hash = runtime_partition::indices_fingerprint(&panel_indices);
            proposal_fingerprints.push(proposal_hash);
            panel_fingerprints.push(panel_hash);
            exogenous_fingerprint = fold(exogenous_fingerprint, evidence_round as u64);
            exogenous_fingerprint = fold(exogenous_fingerprint, proposal_hash);
            exogenous_fingerprint = fold(exogenous_fingerprint, panel_hash);
            active_round = evidence_round;
        }
        let (program, _) = frozen_protocol::select_runtime_program(
            &model,
            &proposal,
            &verifier,
            global_commit % model::PARAMS,
        );
        let update = match program {
            Some(program) => {
                baseline_bound_events += count_program_bound_events(&model, program);
                frozen_protocol::commit_runtime_program(&mut model, program);
                FrozenUpdate {
                    selected: true,
                    left_parameter: program.left as u16,
                    right_parameter: program.right as u16,
                    len: program.len as u8,
                    deltas: program.deltas,
                }
            }
            None => FrozenUpdate {
                selected: false,
                left_parameter: 0,
                right_parameter: 0,
                len: 0,
                deltas: [0.0; 2],
            },
        };
        sequence_fingerprint = fold_update(sequence_fingerprint, update);
        updates.push(update);
    }
    Continuation {
        continuation_id,
        seed,
        hash_partition_id,
        source_state_fingerprint: state.fingerprint,
        proposal_fingerprints,
        panel_fingerprints,
        updates,
        sequence_fingerprint,
        exogenous_fingerprint,
        baseline_bound_events,
    }
}

fn count_program_bound_events(model: &Model, program: RuntimeProgram) -> usize {
    let mut count = usize::from(
        !(LOWER_BOUND..=UPPER_BOUND)
            .contains(&(model.parameters[program.left] + program.deltas[0])),
    );
    if program.len == 2 {
        count += usize::from(
            !(LOWER_BOUND..=UPPER_BOUND)
                .contains(&(model.parameters[program.right] + program.deltas[1])),
        );
    }
    count
}

fn assess_common_support(
    state: &StateRecord,
    actions: &[ActionCandidate],
    continuation: &Continuation,
) -> CensorRecord {
    let mut invalid_action_count = 0;
    let mut first_invalid_action = None;
    let mut branch_bound_events = 0;
    for action in actions {
        let mut parameters = state.model.parameters;
        let left = usize::from(action.left_parameter);
        let right = usize::from(action.right_parameter);
        parameters[left] += action.left_delta;
        parameters[right] += action.right_delta;
        let mut local_events =
            usize::from(!(LOWER_BOUND..=UPPER_BOUND).contains(&parameters[left]))
                + usize::from(!(LOWER_BOUND..=UPPER_BOUND).contains(&parameters[right]));
        for update in &continuation.updates {
            if !update.selected {
                continue;
            }
            let indices = [
                usize::from(update.left_parameter),
                usize::from(update.right_parameter),
            ];
            for (slot, &parameter) in indices.iter().take(usize::from(update.len)).enumerate() {
                parameters[parameter] += update.deltas[slot];
                if !(LOWER_BOUND..=UPPER_BOUND).contains(&parameters[parameter]) {
                    local_events += 1;
                }
            }
        }
        branch_bound_events += local_events;
        if local_events > 0 {
            invalid_action_count += 1;
            first_invalid_action.get_or_insert(action.action_id);
        }
    }
    let reason = if continuation.baseline_bound_events > 0 {
        "baseline_bound"
    } else if invalid_action_count > 0 {
        "candidate_branch_bound"
    } else {
        "none"
    };
    CensorRecord {
        state_id: state.state_id,
        continuation_id: continuation.continuation_id,
        seed: continuation.seed,
        valid: reason == "none",
        reason,
        baseline_bound_events: continuation.baseline_bound_events,
        invalid_action_count,
        first_invalid_action,
        branch_bound_events,
        source_state_fingerprint: continuation.source_state_fingerprint,
        continuation_fingerprint: continuation.sequence_fingerprint,
    }
}

fn replay_path(start: &Model, continuation: &Continuation) -> Vec<Model> {
    let max_horizon = HORIZONS[HORIZONS.len() - 1];
    let mut snapshots = Vec::with_capacity(HORIZONS.len());
    let mut model = *start;
    snapshots.push(model);
    let mut next_horizon = 1;
    for (index, update) in continuation.updates.iter().enumerate() {
        if update.selected {
            apply_unclipped_update(&mut model, *update);
        }
        let step = index + 1;
        if HORIZONS.get(next_horizon) == Some(&step) {
            snapshots.push(model);
            next_horizon += 1;
        }
    }
    assert_eq!(snapshots.len(), HORIZONS.len());
    assert_eq!(max_horizon, continuation.updates.len());
    snapshots
}

fn advance_clamped(mut model: Model, updates: &[FrozenUpdate]) -> Model {
    for update in updates {
        if !update.selected {
            continue;
        }
        let left = usize::from(update.left_parameter);
        model.parameters[left] =
            (model.parameters[left] + update.deltas[0]).clamp(LOWER_BOUND, UPPER_BOUND);
        if update.len == 2 {
            let right = usize::from(update.right_parameter);
            model.parameters[right] =
                (model.parameters[right] + update.deltas[1]).clamp(LOWER_BOUND, UPPER_BOUND);
        }
    }
    model
}

fn apply_unclipped_update(model: &mut Model, update: FrozenUpdate) {
    let left = usize::from(update.left_parameter);
    model.parameters[left] += update.deltas[0];
    if update.len == 2 {
        let right = usize::from(update.right_parameter);
        model.parameters[right] += update.deltas[1];
    }
}

fn apply_initial_action(mut model: Model, action: &ActionCandidate) -> Model {
    model.parameters[usize::from(action.left_parameter)] += action.left_delta;
    model.parameters[usize::from(action.right_parameter)] += action.right_delta;
    model
}

fn fold_update(seed: u64, update: FrozenUpdate) -> u64 {
    let mut hash = fold(seed, u64::from(update.selected));
    hash = fold(hash, u64::from(update.left_parameter));
    hash = fold(hash, u64::from(update.right_parameter));
    hash = fold(hash, u64::from(update.len));
    hash = fold(hash, u64::from(update.deltas[0].to_bits()));
    fold(hash, u64::from(update.deltas[1].to_bits()))
}

fn fold(hash: u64, value: u64) -> u64 {
    (hash ^ value).wrapping_mul(0x0000_0100_0000_01b3)
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

fn hex(bytes: &[u8]) -> String {
    let mut text = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(text, "{byte:02x}");
    }
    text
}

fn write_dataset_manifest(output_dir: &Path, rows: &[DatasetHash]) -> io::Result<()> {
    let mut out = BufWriter::new(File::create(output_dir.join("dataset-manifest.csv"))?);
    writeln!(
        out,
        "dataset_id,training_seed,heldout_seed,sample_count,training_sha256,heldout_sha256"
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{:016x},{:016x},{},{},{}",
            row.dataset_id,
            row.train_seed,
            row.heldout_seed,
            TRAIN_SAMPLES,
            hex(&row.train_sha256),
            hex(&row.heldout_sha256)
        )?;
    }
    out.flush()
}

fn write_state_manifest(output_dir: &Path, rows: &[StateRecord]) -> io::Result<()> {
    let mut out = BufWriter::new(File::create(output_dir.join("state-manifest.csv"))?);
    writeln!(
        out,
        "state_id,cell_id,dataset_id,training_seed,heldout_seed,initialization_id,initialization_seed,state_seed,action_proposal_seed,stage,hash_partition_id,state_fingerprint,training_loss,heldout_loss,parameter_rms,active_hidden_fraction,candidate_count,candidate_fingerprint,valid_continuations,censored_continuations"
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{},{:016x},{:016x},{},{:016x},{:016x},{:016x},{},{},{:016x},{:.12e},{:.12e},{:.12e},{:.9},{},{:016x},{},{}",
            row.state_id,
            row.cell_id,
            row.dataset_id,
            TRAINING_SEEDS[row.dataset_id],
            HELDOUT_SEEDS[row.dataset_id],
            row.initialization_id,
            row.initialization_seed,
            row.state_seed,
            row.action_proposal_seed,
            row.stage,
            row.hash_partition_id,
            row.fingerprint,
            row.training_loss,
            row.heldout_loss,
            row.parameter_rms,
            row.active_hidden_fraction,
            row.candidate_count,
            row.candidate_fingerprint,
            row.valid_continuations,
            row.censored_continuations
        )?;
    }
    out.flush()
}

fn write_action_manifest(
    output_dir: &Path,
    states: &[StateRecord],
    action_sets: &[Vec<ActionCandidate>],
) -> io::Result<()> {
    let mut out = BufWriter::new(File::create(output_dir.join("action-manifest.csv"))?);
    writeln!(
        out,
        "state_id,cell_id,dataset_id,initialization_id,stage,action_id,block_id,left_parameter,right_parameter,left_layer,right_layer,left_rank,right_rank,left_delta,right_delta,u0_train,u0_heldout,taylor_train,taylor_heldout,output_taylor_train,output_taylor_heldout,projected_within_utility_variance"
    )?;
    for (state_index, actions) in action_sets.iter().enumerate() {
        let state = states[state_index];
        for action in actions {
            writeln!(
                out,
                "{},{},{},{},{},{},{},{},{},{},{},{},{},{:.9},{:.9},{:.12e},{:.12e},{:.12e},{:.12e},{},{},{:.12e}",
                state.state_id,
                state.cell_id,
                state.dataset_id,
                state.initialization_id,
                state.stage,
                action.action_id,
                action.block_id,
                action.left_parameter,
                action.right_parameter,
                protocol::parameter_layer(usize::from(action.left_parameter)),
                protocol::parameter_layer(usize::from(action.right_parameter)),
                action.left_rank,
                action.right_rank,
                action.left_delta,
                action.right_delta,
                action.immediate_train_utility,
                action.immediate_heldout_utility,
                action.taylor_train_utility,
                action.taylor_heldout_utility,
                number_option(action.output_taylor_train_utility),
                number_option(action.output_taylor_heldout_utility),
                action.projected_within_utility_variance
            )?;
        }
    }
    out.flush()
}

fn write_continuation_manifest(output_dir: &Path, rows: &[Continuation]) -> io::Result<()> {
    let mut out = BufWriter::new(File::create(output_dir.join("continuation-manifest.csv"))?);
    writeln!(
        out,
        "continuation_id,state_id,seed,hash_partition_id,source_state_fingerprint,sequence_fingerprint,exogenous_fingerprint,updates,selected_updates,no_op_slots,baseline_bound_events,proposal_fingerprints,panel_fingerprints"
    )?;
    for row in rows {
        let selected = row.updates.iter().filter(|update| update.selected).count();
        let proposals = row
            .proposal_fingerprints
            .iter()
            .map(|value| format!("{value:016x}"))
            .collect::<Vec<_>>()
            .join(";");
        let panels = row
            .panel_fingerprints
            .iter()
            .map(|value| format!("{value:016x}"))
            .collect::<Vec<_>>()
            .join(";");
        writeln!(
            out,
            "{},{},{:016x},{},{:016x},{:016x},{:016x},{},{},{},{},{},{}",
            row.continuation_id,
            row.continuation_id / CONTINUATIONS_PER_STATE,
            row.seed,
            row.hash_partition_id,
            row.source_state_fingerprint,
            row.sequence_fingerprint,
            row.exogenous_fingerprint,
            row.updates.len(),
            selected,
            row.updates.len() - selected,
            row.baseline_bound_events,
            proposals,
            panels
        )?;
    }
    out.flush()
}

fn write_censor_ledger(output_dir: &Path, rows: &[CensorRecord]) -> io::Result<()> {
    let mut out = BufWriter::new(File::create(output_dir.join("bounds-censor-ledger.csv"))?);
    writeln!(
        out,
        "state_id,continuation_id,seed,valid,reason,baseline_bound_events,invalid_action_count,first_invalid_action,branch_bound_events,source_state_fingerprint,continuation_fingerprint"
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{:016x},{},{},{},{},{},{},{:016x},{:016x}",
            row.state_id,
            row.continuation_id,
            row.seed,
            row.valid,
            row.reason,
            row.baseline_bound_events,
            row.invalid_action_count,
            row.first_invalid_action
                .map_or_else(|| "none".to_owned(), |value| value.to_string()),
            row.branch_bound_events,
            row.source_state_fingerprint,
            row.continuation_fingerprint
        )?;
    }
    out.flush()
}

fn write_action_outcomes(output_dir: &Path, rows: &[ActionOutcome]) -> io::Result<()> {
    let mut out = BufWriter::new(File::create(output_dir.join("action-continuation.csv"))?);
    writeln!(
        out,
        "state_id,cell_id,dataset_id,initialization_id,stage,continuation_id,continuation_seed,action_id,horizon,u0_train,u0_heldout,q_h,delta_q_h,noop_loss,action_loss,state_fingerprint,continuation_fingerprint,noop_state_fingerprint,action_state_fingerprint"
    )?;
    for row in rows {
        writeln!(
            out,
            "{},{},{},{},{},{},{:016x},{},{},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:016x},{:016x},{:016x},{:016x}",
            row.state_id,
            row.cell_id,
            row.dataset_id,
            row.initialization_id,
            row.stage,
            row.continuation_id,
            row.continuation_seed,
            row.action_id,
            row.horizon,
            row.u0_train,
            row.u0_heldout,
            row.q_h,
            row.delta_q_h,
            row.noop_loss,
            row.action_loss,
            row.state_fingerprint,
            row.continuation_fingerprint,
            row.noop_fingerprint,
            row.action_fingerprint
        )?;
    }
    out.flush()
}

#[allow(clippy::too_many_arguments)]
fn write_integrity_receipt(
    output_dir: &Path,
    source_commit: &str,
    data: &[DatasetHash],
    states: &[StateRecord],
    action_sets: &[Vec<ActionCandidate>],
    continuations: &[Continuation],
    censor_records: &[CensorRecord],
    outcomes: &[ActionOutcome],
    h0_consistency_error: f64,
) -> io::Result<()> {
    let executable_sha256 = hex(&sha256_file(&std::env::current_exe()?)?);
    let valid_count = censor_records.iter().filter(|row| row.valid).count();
    let censored_count = censor_records.len() - valid_count;
    let under_supported_states = states
        .iter()
        .filter(|state| state.valid_continuations < MIN_VALID_CONTINUATIONS)
        .count();
    let action_count: usize = action_sets.iter().map(Vec::len).sum();
    let expected_outcomes: usize = states
        .iter()
        .zip(action_sets)
        .map(|(state, actions)| state.valid_continuations * actions.len() * HORIZONS.len())
        .sum();
    let integrity_valid = protocol::fresh_seeds_are_unique()
        && data.len() == DATASET_COUNT
        && states.len() == STATE_COUNT
        && continuations.len() == protocol::CONTINUATION_COUNT
        && censor_records.len() == protocol::CONTINUATION_COUNT
        && valid_count + censored_count == protocol::CONTINUATION_COUNT
        && outcomes.len() == expected_outcomes
        && states.iter().all(|state| {
            state.valid_continuations + state.censored_continuations == CONTINUATIONS_PER_STATE
        })
        && h0_consistency_error <= 2.0e-5;
    let mut out = BufWriter::new(File::create(output_dir.join("integrity-receipt.json"))?);
    writeln!(out, "{{")?;
    writeln!(
        out,
        "  \"protocol\": \"AR-04A-continuation-conditioned-action-value-2026-09-21\","
    )?;
    writeln!(out, "  \"parent_branch\": \"{PARENT_BRANCH}\",")?;
    writeln!(out, "  \"parent_result_commit\": \"{PARENT_COMMIT}\",")?;
    writeln!(out, "  \"source_branch\": \"{EXPECTED_BRANCH}\",")?;
    writeln!(out, "  \"frozen_source_commit\": \"{source_commit}\",")?;
    writeln!(out, "  \"executable_sha256\": \"{executable_sha256}\",")?;
    writeln!(out, "  \"integrity_valid\": {integrity_valid},")?;
    writeln!(out, "  \"source_clean_at_collection\": true,")?;
    writeln!(out, "  \"branch_specific_replanning\": false,")?;
    writeln!(
        out,
        "  \"measurement_objective\": \"independent held-out cross-entropy; measurement only\","
    )?;
    writeln!(out, "  \"horizons\": [0, 8, 32, 128],")?;
    writeln!(
        out,
        "  \"datasets\": {}, \"initializations\": {}, \"cells\": {}, \"states\": {},",
        DATASET_COUNT,
        INITIALIZATION_COUNT,
        protocol::CELL_COUNT,
        states.len()
    )?;
    writeln!(out, "  \"state_stages\": [600, 2400, 4200],")?;
    writeln!(
        out,
        "  \"continuations_per_state\": {}, \"continuations\": {}, \"valid_continuations\": {}, \"bounds_censored_continuations\": {},",
        CONTINUATIONS_PER_STATE,
        continuations.len(),
        valid_count,
        censored_count
    )?;
    writeln!(
        out,
        "  \"minimum_valid_continuations_for_primary_summary\": {}, \"under_supported_state_count\": {},",
        MIN_VALID_CONTINUATIONS, under_supported_states
    )?;
    writeln!(
        out,
        "  \"candidate_actions\": {action_count}, \"valid_action_continuation_pairs\": {}, \"horizon_outcome_rows\": {}, \"expected_horizon_outcome_rows\": {},",
        outcomes.len() / HORIZONS.len(),
        outcomes.len(),
        expected_outcomes
    )?;
    writeln!(
        out,
        "  \"unique_seed_count\": 715, \"all_seed_roles_unique\": {},",
        protocol::fresh_seeds_are_unique()
    )?;
    writeln!(
        out,
        "  \"max_h0_effect_consistency_error\": {:.12e},",
        h0_consistency_error
    )?;
    writeln!(out, "  \"training_heldout_data_hashes\": [")?;
    for (index, row) in data.iter().enumerate() {
        write!(
            out,
            "    {{\"dataset_id\":{},\"training_seed\":\"{:016x}\",\"heldout_seed\":\"{:016x}\",\"training_sha256\":\"{}\",\"heldout_sha256\":\"{}\"}}{}",
            row.dataset_id,
            row.train_seed,
            row.heldout_seed,
            hex(&row.train_sha256),
            hex(&row.heldout_sha256),
            if index + 1 == data.len() { "" } else { "," }
        )?;
        writeln!(out)?;
    }
    writeln!(out, "  ]")?;
    writeln!(out, "}}")?;
    out.flush()?;
    if !integrity_valid {
        return Err(io::Error::other(
            "AR-04A integrity receipt reports invalid collection",
        ));
    }
    Ok(())
}

fn number_option(value: Option<f64>) -> String {
    value.map_or_else(|| "".to_owned(), |number| format!("{number:.12e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn continuation_replay_preserves_common_additive_updates_without_bounds() {
        let train = model::generate_dataset(TRAINING_SEEDS[0]);
        let heldout = model::generate_dataset(HELDOUT_SEEDS[0]);
        let mut initial = Model::initial(INITIALIZATION_SEEDS[0]);
        for value in initial.parameters.iter_mut() {
            *value *= 0.1;
        }
        let action = ActionCandidate {
            action_id: 0,
            block_id: 0,
            left_parameter: 0,
            right_parameter: 1,
            left_rank: 0,
            right_rank: 0,
            left_delta: 0.005,
            right_delta: -0.005,
            immediate_train_utility: 0.0,
            immediate_heldout_utility: 0.0,
            taylor_train_utility: 0.0,
            taylor_heldout_utility: 0.0,
            output_taylor_train_utility: None,
            output_taylor_heldout_utility: None,
            projected_within_utility_variance: 0.0,
        };
        let (parameter_rms, active_hidden_fraction) = protocol::state_features(&initial, &train);
        let state = StateRecord {
            cell_id: 0,
            dataset_id: 0,
            initialization_id: 0,
            initialization_seed: INITIALIZATION_SEEDS[0],
            state_id: 0,
            stage: 600,
            state_seed: STATE_STREAM_SEEDS[0],
            action_proposal_seed: ACTION_PROPOSAL_SEEDS[0],
            hash_partition_id: 0,
            model: initial,
            training_loss: f64::from(initial.loss(&train)),
            heldout_loss: f64::from(initial.loss(&heldout)),
            parameter_rms,
            active_hidden_fraction,
            fingerprint: frozen_protocol::runtime_parameter_fingerprint(&initial),
            candidate_fingerprint: 0,
            candidate_count: 1,
            valid_continuations: 0,
            censored_continuations: 0,
        };
        let updates: Vec<_> = (0..128)
            .map(|step| FrozenUpdate {
                selected: true,
                left_parameter: (2 + step % 3) as u16,
                right_parameter: 5,
                len: 2,
                deltas: [0.001, -0.001],
            })
            .collect();
        let continuation = Continuation {
            continuation_id: 0,
            seed: CONTINUATION_SEEDS[0],
            hash_partition_id: 0,
            source_state_fingerprint: state.fingerprint,
            proposal_fingerprints: vec![],
            panel_fingerprints: vec![],
            updates,
            sequence_fingerprint: 0x1234,
            exogenous_fingerprint: 0x5678,
            baseline_bound_events: 0,
        };
        let censor = assess_common_support(&state, &[action], &continuation);
        assert!(censor.valid);
        let path = replay_path(&state.model, &continuation);
        for horizon_model in path {
            let branched = apply_initial_action(horizon_model, &action);
            let d0 = branched.parameters[0] - horizon_model.parameters[0];
            let d1 = branched.parameters[1] - horizon_model.parameters[1];
            assert!((d0 - action.left_delta).abs() < 1.0e-6);
            assert!((d1 - action.right_delta).abs() < 1.0e-6);
        }
    }
}
