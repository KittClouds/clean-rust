//! Versioned V_reach data simulator for the runtime `incidence_masked_norm_4`
//! proposal mixture. The teacher/request generator remains outside this path.

use crate::{
    build_reachability_dataset, FrozenProposal, IndividualState, ProposalActionProbability,
    ProposalContext, PublicFeatures,
};
use hashbrown::HashSet;
use r1_world::{InferenceTask, Task};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::Path;

mod policy;
mod util;
#[cfg(test)]
use policy::{
    compose_norm4_logits, incidence_masked_expected_delta, mean_std, softmax_temperature,
};
use policy::{supported_kind_ids, FixedProposal, ProposalWeights};
use util::{
    count_jsonl_lines, derive_seed, ensure_distinct_new_paths, file_record, hex_bytes, new_writer,
    parse_digest, read_jsonl_bytes, sha256_file, sha256_hex, StableRng,
};

const BASE_FEATURES: usize = 10;
const STATIC_FEATURES: usize = 8;
const LATENT_WIDTH: usize = 128;
const MIXTURE_ID: &str = "incidence_masked_norm_4";
const SIMULATOR_VERSION: &str = "r1-vreach-simulator-v03";
const LABEL_SCHEMA: &str = "r1-v-reach-label-dataset-v03";
const STATE_LABEL_SCHEMA: &str = "r1-v-reach-rollout-label-v03";
const TRACE_SCHEMA: &str = "r1-proposal-trajectories-v03";

const SIMULATOR_SOURCE: &[u8] = include_bytes!("simulator_v03.rs");
const SIMULATOR_CLI_SOURCE: &[u8] = include_bytes!("bin/r1_proposal_data_v03.rs");
const SIMULATOR_UTIL_SOURCE: &[u8] = include_bytes!("simulator_v03/util.rs");
const SIMULATOR_POLICY_SOURCE: &[u8] = include_bytes!("simulator_v03/policy.rs");
const ROLLOUT_SOURCE: &[u8] = include_bytes!("rollout.rs");
const RUNTIME_MIX_SOURCE: &[u8] = include_bytes!("../../search/src/inference_v02.rs");
const RUNTIME_ACTION_SOURCE: &[u8] = include_bytes!("../../search/src/terminal.rs");
const RUNTIME_SAMPLER_SOURCE: &[u8] = include_bytes!("../../search/src/policy.rs");

#[derive(Clone, Debug, Deserialize)]
struct TeacherState {
    state_index: u32,
    assignment: Vec<u8>,
}

#[derive(Deserialize)]
struct Request {
    task: Task,
    inference: InferenceTask,
    features: PublicFeatures,
    static_candidate_features: Vec<Vec<Vec<f32>>>,
    clause_kind_probabilities: Vec<[f32; 6]>,
    teacher_states: Vec<TeacherState>,
    trace_state_indices: Vec<u32>,
    trajectory_steps: u32,
    trace_sample_steps: Vec<u32>,
    initial_budgets: Vec<u32>,
    trace_budgets: Vec<u32>,
    base_seed: u64,
    rollouts_per_state: u32,
}

#[derive(Clone, Debug, Serialize)]
pub struct PolicyIdentity {
    pub schema: &'static str,
    pub sha256: String,
    pub weights_sha256: String,
    pub mixture_id: &'static str,
    pub temperature: f64,
    pub temperature_f64_bits_le_hex: String,
    pub simulator_version: &'static str,
    pub source_sha256: SourceDigests,
}

#[derive(Clone, Debug, Serialize)]
pub struct SourceDigests {
    pub simulator_core: String,
    pub simulator_cli: String,
    pub simulator_util: String,
    pub simulator_policy: String,
    pub rollout_engine: String,
    pub runtime_mixture: String,
    pub runtime_action_delta: String,
    pub runtime_sampler: String,
}

#[derive(Clone, Debug, Serialize)]
struct TracePoint {
    step: u32,
    assignment: Vec<u8>,
    latent_state: Vec<f32>,
}

#[derive(Clone, Debug, Serialize)]
struct ProposalTrajectory {
    trajectory_id: String,
    source_state_index: u32,
    seed: u64,
    rng_state_end: u64,
    proposal_sha256: String,
    points: Vec<TracePoint>,
}

#[derive(Serialize)]
struct TraceDataset {
    schema: &'static str,
    task_id: String,
    sensor_artifact_sha256: String,
    proposal_sha256: String,
    policy_identity: PolicyIdentity,
    trajectory_steps: u32,
    trajectories: Vec<ProposalTrajectory>,
}

/// Generate versioned policy-matched labels and complete proposal traces.
pub fn generate(
    request_path: &Path,
    weights_path: &Path,
    label_path: &Path,
    trace_path: &Path,
    receipt_path: &Path,
    mixture_id: &str,
    temperature: f64,
) -> Result<(), String> {
    if mixture_id != MIXTURE_ID {
        return Err(format!("V03 simulator only supports mixture {MIXTURE_ID}"));
    }
    if !temperature.is_finite() || temperature <= 0.0 {
        return Err("temperature must be finite and positive".into());
    }
    ensure_distinct_new_paths(&[label_path, trace_path, receipt_path])?;

    let request_bytes =
        fs::read(request_path).map_err(|error| format!("read requests: {error}"))?;
    let request_sha256 = sha256_hex(&request_bytes);
    let requests = read_jsonl_bytes::<Request>(&request_bytes, request_path)?;
    let weights_bytes = fs::read(weights_path).map_err(|error| format!("read weights: {error}"))?;
    let weights: ProposalWeights =
        serde_json::from_slice(&weights_bytes).map_err(|error| error.to_string())?;
    weights.validate()?;
    let weights_sha256 = sha256_hex(&weights_bytes);
    let identity = policy_identity(&weights_sha256, mixture_id, temperature)?;
    let identity_digest = parse_digest(&identity.sha256)?;

    let mut label_output = new_writer(label_path)?;
    let mut trace_output = new_writer(trace_path)?;
    let mut total_states = 0usize;
    let mut total_rollouts = 0usize;
    for request in requests {
        validate_request(&request)?;
        let proposal = FixedProposal {
            task_id: &request.task.id,
            static_features: &request.static_candidate_features,
            clause_probabilities: &request.clause_kind_probabilities,
            weights: &weights,
            identity_digest,
            temperature,
        };
        let (states, trajectories) = collect_states(&request, &proposal, &identity.sha256)?;
        let mut labels = build_reachability_dataset(
            &request.task,
            &request.inference,
            &request.features,
            &states,
            request.base_seed,
            request.rollouts_per_state,
            &proposal,
        )
        .map_err(|error| format!("v03 V_reach labels for {}: {error}", request.task.id))?;
        total_states += labels.states.len();
        total_rollouts += labels
            .states
            .iter()
            .map(|state| state.rollouts.len())
            .sum::<usize>();
        let mut label_value = serde_json::to_value(&labels).map_err(|error| error.to_string())?;
        version_label_value(&mut label_value, &identity)?;
        serde_json::to_writer(&mut label_output, &label_value)
            .map_err(|error| error.to_string())?;
        label_output
            .write_all(b"\n")
            .map_err(|error| error.to_string())?;
        let traces = TraceDataset {
            schema: TRACE_SCHEMA,
            task_id: request.task.id.clone(),
            sensor_artifact_sha256: request.features.sensor_artifact_sha256.clone(),
            proposal_sha256: identity.sha256.clone(),
            policy_identity: identity.clone(),
            trajectory_steps: request.trajectory_steps,
            trajectories,
        };
        serde_json::to_writer(&mut trace_output, &traces).map_err(|error| error.to_string())?;
        trace_output
            .write_all(b"\n")
            .map_err(|error| error.to_string())?;
        labels.states.clear();
    }
    label_output.flush().map_err(|error| error.to_string())?;
    trace_output.flush().map_err(|error| error.to_string())?;
    drop(label_output);
    drop(trace_output);

    let receipt = json!({
        "schema": "R1_VREACH_SIMULATOR_RECEIPT_V03",
        "status": "COMPLETE",
        "request_file": file_record(request_path, &request_sha256)?,
        "proposal_weights_file": file_record(weights_path, &weights_sha256)?,
        "policy_identity": identity,
        "label_file": file_record(label_path, &sha256_file(label_path)?)?,
        "trace_file": file_record(trace_path, &sha256_file(trace_path)?)?,
        "task_count": count_jsonl_lines(label_path)?,
        "state_count": total_states,
        "rollout_count": total_rollouts,
        "generator_teacher_contract": "unchanged v02 request rows; V03 only changes frozen policy simulation and output envelope",
        "qualification_access_by_simulator": false
    });
    let mut receipt_output = new_writer(receipt_path)?;
    serde_json::to_writer_pretty(&mut receipt_output, &receipt)
        .map_err(|error| error.to_string())?;
    receipt_output
        .write_all(b"\n")
        .map_err(|error| error.to_string())?;
    receipt_output.flush().map_err(|error| error.to_string())?;
    println!(
        "R1_V03_LABELS_WRITTEN states={total_states} rollouts={total_rollouts} policy_identity_sha256={}",
        identity.sha256
    );
    Ok(())
}

fn policy_identity(
    weights_sha256: &str,
    mixture_id: &str,
    temperature: f64,
) -> Result<PolicyIdentity, String> {
    let weights_digest = parse_digest(weights_sha256)?;
    let source_sha256 = SourceDigests {
        simulator_core: hex_bytes(&Sha256::digest(SIMULATOR_SOURCE)),
        simulator_cli: hex_bytes(&Sha256::digest(SIMULATOR_CLI_SOURCE)),
        simulator_util: hex_bytes(&Sha256::digest(SIMULATOR_UTIL_SOURCE)),
        simulator_policy: hex_bytes(&Sha256::digest(SIMULATOR_POLICY_SOURCE)),
        rollout_engine: hex_bytes(&Sha256::digest(ROLLOUT_SOURCE)),
        runtime_mixture: hex_bytes(&Sha256::digest(RUNTIME_MIX_SOURCE)),
        runtime_action_delta: hex_bytes(&Sha256::digest(RUNTIME_ACTION_SOURCE)),
        runtime_sampler: hex_bytes(&Sha256::digest(RUNTIME_SAMPLER_SOURCE)),
    };
    let mut hasher = Sha256::new();
    hasher.update(b"FAS_R1_VREACH_POLICY_IDENTITY_V03\0");
    hasher.update(weights_digest);
    hasher.update((mixture_id.len() as u64).to_le_bytes());
    hasher.update(mixture_id.as_bytes());
    hasher.update(temperature.to_bits().to_le_bytes());
    hasher.update(SIMULATOR_VERSION.as_bytes());
    for source in [
        &source_sha256.simulator_core,
        &source_sha256.simulator_cli,
        &source_sha256.simulator_util,
        &source_sha256.simulator_policy,
        &source_sha256.rollout_engine,
        &source_sha256.runtime_mixture,
        &source_sha256.runtime_action_delta,
        &source_sha256.runtime_sampler,
    ] {
        hasher.update(parse_digest(source)?);
    }
    Ok(PolicyIdentity {
        schema: "r1-vreach-policy-identity-v03",
        sha256: hex_bytes(&hasher.finalize()),
        weights_sha256: weights_sha256.to_owned(),
        mixture_id: MIXTURE_ID,
        temperature,
        temperature_f64_bits_le_hex: hex_bytes(&temperature.to_bits().to_le_bytes()),
        simulator_version: SIMULATOR_VERSION,
        source_sha256,
    })
}

fn version_label_value(value: &mut Value, identity: &PolicyIdentity) -> Result<(), String> {
    let object = value
        .as_object_mut()
        .ok_or("shared rollout builder emitted a non-object dataset")?;
    object.insert("schema".into(), Value::String(LABEL_SCHEMA.into()));
    object.insert(
        "policy_identity".into(),
        serde_json::to_value(identity).map_err(|e| e.to_string())?,
    );
    object.insert(
        "policy_identity_sha256".into(),
        Value::String(identity.sha256.clone()),
    );
    let states = object
        .get_mut("states")
        .and_then(Value::as_array_mut)
        .ok_or("shared rollout builder emitted no label states")?;
    for state in states {
        let state_object = state
            .as_object_mut()
            .ok_or("label state is not an object")?;
        state_object.insert("schema".into(), Value::String(STATE_LABEL_SCHEMA.into()));
        state_object.insert(
            "policy_identity_sha256".into(),
            Value::String(identity.sha256.clone()),
        );
        let rollouts = state_object
            .get_mut("rollouts")
            .and_then(Value::as_array_mut)
            .ok_or("label state has no rollout records")?;
        for rollout in rollouts {
            rollout
                .as_object_mut()
                .ok_or("rollout label is not an object")?
                .insert(
                    "policy_identity_sha256".into(),
                    Value::String(identity.sha256.clone()),
                );
        }
    }
    Ok(())
}

fn validate_request(request: &Request) -> Result<(), String> {
    let n = usize::from(request.inference.n);
    let k = usize::from(request.inference.k);
    if request.task.id != request.inference.id
        || request.task.n != request.inference.n
        || request.task.k != request.inference.k
        || request.static_candidate_features.len() != n
        || request.static_candidate_features.iter().any(|row| {
            row.len() != k || row.iter().any(|features| features.len() != STATIC_FEATURES)
        })
        || request.clause_kind_probabilities.len() != request.inference.clauses.len()
        || request.inference.entity_mentions.len() != request.inference.clauses.len()
        || request.inference.role_mentions.len() != request.inference.clauses.len()
    {
        return Err(format!(
            "V03 public feature shape mismatch for {}",
            request.task.id
        ));
    }
    for (clause, distribution) in request.clause_kind_probabilities.iter().enumerate() {
        if distribution
            .iter()
            .any(|value| !value.is_finite() || *value < 0.0)
            || (distribution
                .iter()
                .map(|value| f64::from(*value))
                .sum::<f64>()
                - 1.0)
                .abs()
                > 1e-5
        {
            return Err(
                "identity class probabilities must be finite normalized six-way rows".into(),
            );
        }
        let entities = &request.inference.entity_mentions[clause];
        let roles = &request.inference.role_mentions[clause];
        if entities.iter().any(|&entity| usize::from(entity) >= n)
            || roles.iter().any(|&role| usize::from(role) >= k)
        {
            return Err("public incidence contains an out-of-range entity or role".into());
        }
        supported_kind_ids(entities.len(), roles.len())?;
    }
    if request.teacher_states.is_empty()
        || request.rollouts_per_state == 0
        || request.trajectory_steps == 0
    {
        return Err("V03 request needs teacher states, rollouts and trajectory steps".into());
    }
    for features in request.static_candidate_features.iter().flatten() {
        if features.iter().any(|value| !value.is_finite()) {
            return Err("static candidate features contain a non-finite value".into());
        }
    }
    for teacher in &request.teacher_states {
        if teacher.assignment.len() != n
            || teacher.assignment.iter().any(|&role| role as usize >= k)
        {
            return Err("teacher assignment is outside the public task".into());
        }
    }
    Ok(())
}

fn collect_states<P: FrozenProposal>(
    request: &Request,
    proposal: &P,
    proposal_sha256: &str,
) -> Result<(Vec<IndividualState>, Vec<ProposalTrajectory>), String> {
    let mut states = Vec::new();
    let mut ids = HashSet::new();
    for teacher in &request.teacher_states {
        for &budget in &request.initial_budgets {
            push_state(
                &mut states,
                &mut ids,
                IndividualState {
                    state_id: format!(
                        "{}-s{:04}-b{:04}",
                        request.task.id, teacher.state_index, budget
                    ),
                    assignment: teacher.assignment.clone(),
                    latent_state: vec![0.0; LATENT_WIDTH],
                    remaining_budget: budget,
                },
            )?;
        }
    }
    let state_by_index = request
        .teacher_states
        .iter()
        .map(|row| (row.state_index, row))
        .collect::<BTreeMap<_, _>>();
    if state_by_index.len() != request.teacher_states.len() {
        return Err("teacher states contain duplicate state indices".into());
    }
    let mut trajectories = Vec::with_capacity(request.trace_state_indices.len());
    for &state_index in &request.trace_state_indices {
        let teacher = state_by_index
            .get(&state_index)
            .ok_or("trace state index is missing from teacher set")?;
        // Keep the v02 ID in seed derivation so the policy change does not also
        // change the per-trajectory RNG stream.
        let trajectory_id = format!("{}-s{:04}-trace-v02", request.task.id, state_index);
        let seed = derive_seed(request.base_seed, &trajectory_id, 0);
        let mut rng = StableRng::new(seed);
        let mut assignment = teacher.assignment.clone();
        let mut latent = vec![0.0; LATENT_WIDTH];
        let mut points = Vec::with_capacity(request.trajectory_steps as usize + 1);
        points.push(TracePoint {
            step: 0,
            assignment: assignment.clone(),
            latent_state: latent.clone(),
        });
        for step in 1..=request.trajectory_steps {
            let (selected, next_latent) = {
                let context = ProposalContext {
                    inference: &request.inference,
                    features: &request.features,
                    assignment: &assignment,
                    latent_state: &latent,
                };
                let distribution =
                    proposal.action_distribution(&context, request.trajectory_steps - step + 1)?;
                let selected =
                    sample_distribution(&distribution, &request.inference, &assignment, &mut rng)?;
                let next_latent =
                    proposal.advance_latent(&context, selected.entity, selected.new_role)?;
                (selected, next_latent)
            };
            assignment[usize::from(selected.entity)] = selected.new_role;
            latent = next_latent;
            points.push(TracePoint {
                step,
                assignment: assignment.clone(),
                latent_state: latent.clone(),
            });
            if request.trace_sample_steps.contains(&step) {
                for &budget in &request.trace_budgets {
                    if budget <= request.trajectory_steps - step {
                        push_state(
                            &mut states,
                            &mut ids,
                            IndividualState {
                                state_id: format!(
                                    "{}-s{:04}-t{:04}-b{:04}",
                                    request.task.id, state_index, step, budget
                                ),
                                assignment: assignment.clone(),
                                latent_state: latent.clone(),
                                remaining_budget: budget,
                            },
                        )?;
                    }
                }
            }
        }
        trajectories.push(ProposalTrajectory {
            trajectory_id,
            source_state_index: state_index,
            seed,
            rng_state_end: rng.state,
            proposal_sha256: proposal_sha256.to_owned(),
            points,
        });
    }
    Ok((states, trajectories))
}

fn sample_distribution(
    distribution: &[ProposalActionProbability],
    inference: &InferenceTask,
    assignment: &[u8],
    rng: &mut StableRng,
) -> Result<ProposalActionProbability, String> {
    if distribution.is_empty() {
        return Err("proposal emitted no legal edits".into());
    }
    let mut sum = 0.0;
    for (index, action) in distribution.iter().enumerate() {
        if usize::from(action.entity) >= assignment.len()
            || action.new_role >= inference.k
            || action.new_role == assignment[usize::from(action.entity)]
            || !action.probability.is_finite()
            || action.probability < 0.0
        {
            return Err("proposal emitted an invalid action or probability".into());
        }
        if distribution[..index]
            .iter()
            .any(|prior| prior.entity == action.entity && prior.new_role == action.new_role)
        {
            return Err("proposal emitted a duplicate action".into());
        }
        sum += action.probability;
    }
    if !sum.is_finite() || (sum - 1.0).abs() > 1e-6 {
        return Err("proposal probabilities are not normalized".into());
    }
    let draw = rng.unit_f64();
    let mut cumulative = 0.0;
    for action in distribution {
        cumulative += action.probability;
        if draw < cumulative {
            return Ok(*action);
        }
    }
    distribution
        .last()
        .copied()
        .ok_or_else(|| "proposal emitted no legal edits".into())
}

fn push_state(
    states: &mut Vec<IndividualState>,
    ids: &mut HashSet<String>,
    state: IndividualState,
) -> Result<(), String> {
    if !ids.insert(state.state_id.clone()) {
        return Err(format!("duplicate V03 state id {}", state.state_id));
    }
    states.push(state);
    Ok(())
}

#[cfg(test)]
mod tests;
