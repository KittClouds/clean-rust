use hashbrown::HashSet;
use r1_proposal_training::{
    build_reachability_dataset, FrozenProposal, IndividualState, ProposalActionProbability,
    ProposalContext, PublicFeatures,
};
use r1_world::{InferenceTask, Task};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::Path;

const BASE_FEATURES: usize = 10;
const STATIC_FEATURES: usize = 8;
const LATENT_WIDTH: usize = 128;
const USAGE: &str = "usage: r1_proposal_data_v02 generate REQUESTS_JSONL FROZEN_WEIGHTS_JSON LABELS_JSONL TRACES_JSONL";

#[derive(Clone, Debug, Deserialize)]
struct ProposalWeights {
    schema: String,
    architecture: String,
    input_dim: usize,
    hidden_dim: usize,
    w1: Vec<Vec<f32>>,
    b1: Vec<f32>,
    w2: Vec<f32>,
    b2: f32,
    adapter_logit_bias: f32,
}

impl ProposalWeights {
    fn validate(&self) -> Result<(), String> {
        if self.schema != "r1-proposal-weights-v02"
            || self.architecture != "tanh_mlp_base_f10_h16_plus_adapter_bias_v02"
            || self.input_dim != BASE_FEATURES
            || self.hidden_dim == 0
            || self.w1.len() != self.hidden_dim
            || self.b1.len() != self.hidden_dim
            || self.w2.len() != self.hidden_dim
            || self.w1.iter().any(|row| row.len() != self.input_dim)
        {
            return Err("v02 proposal weights have an unsupported schema or shape".to_owned());
        }
        if self
            .w1
            .iter()
            .flatten()
            .chain(&self.b1)
            .chain(&self.w2)
            .chain([&self.b2, &self.adapter_logit_bias])
            .any(|value| !value.is_finite())
        {
            return Err("v02 proposal weights contain a non-finite value".to_owned());
        }
        Ok(())
    }
}

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
    trajectory_steps: u32,
    trajectories: Vec<ProposalTrajectory>,
}

struct FixedProposal<'a> {
    task_id: &'a str,
    static_features: &'a [Vec<Vec<f32>>],
    clause_probabilities: &'a [[f32; 6]],
    weights: &'a ProposalWeights,
    digest: [u8; 32],
}

impl FrozenProposal for FixedProposal<'_> {
    fn snapshot_sha256(&self) -> [u8; 32] {
        self.digest
    }

    fn action_distribution(
        &self,
        context: &ProposalContext<'_>,
        _remaining_budget: u32,
    ) -> Result<Vec<ProposalActionProbability>, String> {
        if context.inference.id != self.task_id {
            return Err("v02 proposal feature cache was bound to another task".to_owned());
        }
        if self.clause_probabilities.len() != context.inference.clauses.len() {
            return Err("identity class probability count differs from public clauses".to_owned());
        }
        let mut role_loads = vec![0.0f32; usize::from(context.inference.k)];
        for &role in context.assignment {
            let Some(load) = role_loads.get_mut(usize::from(role)) else {
                return Err("assignment role is outside the public task".to_owned());
            };
            *load += 1.0;
        }
        let n = context.assignment.len() as f32;
        let mut actions =
            Vec::with_capacity(context.assignment.len() * usize::from(context.inference.k));
        let mut scores = Vec::with_capacity(actions.capacity());
        for entity in 0..context.inference.n {
            let old_role = context.assignment[usize::from(entity)];
            for new_role in 0..context.inference.k {
                if new_role == old_role {
                    continue;
                }
                let mut features = self
                    .static_features
                    .get(usize::from(entity))
                    .and_then(|roles| roles.get(usize::from(new_role)))
                    .ok_or_else(|| "static candidate feature cache has the wrong shape".to_owned())?
                    .clone();
                if features.len() != STATIC_FEATURES {
                    return Err("static candidate feature rows must have width eight".to_owned());
                }
                features.push(role_loads[usize::from(old_role)] / n);
                features.push(role_loads[usize::from(new_role)] / n);
                let adapter_score = action_adapter_score(
                    context.inference,
                    self.clause_probabilities,
                    context.assignment,
                    usize::from(entity),
                    new_role,
                )?;
                actions.push((entity, new_role));
                scores.push(
                    score(self.weights, &features)
                        + self.weights.adapter_logit_bias * adapter_score,
                );
            }
        }
        if actions.is_empty() || scores.iter().any(|value| !value.is_finite()) {
            return Err("v02 proposal has no legal actions or a non-finite score".to_owned());
        }
        let maximum = scores.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        let weights: Vec<f64> = scores
            .iter()
            .map(|value| f64::from((*value - maximum).exp()))
            .collect();
        let total = weights.iter().sum::<f64>();
        if !total.is_finite() || total <= 0.0 {
            return Err("v02 proposal softmax is invalid".to_owned());
        }
        Ok(actions
            .into_iter()
            .zip(weights)
            .map(|((entity, new_role), weight)| ProposalActionProbability {
                entity,
                new_role,
                probability: weight / total,
            })
            .collect())
    }

    fn advance_latent(
        &self,
        context: &ProposalContext<'_>,
        entity: u16,
        new_role: u8,
    ) -> Result<Vec<f32>, String> {
        let mut latent = context.latent_state.to_vec();
        if latent.is_empty() {
            return Ok(latent);
        }
        let index = usize::from(entity) % latent.len();
        let role_index = (usize::from(new_role) * 31 + index + 1) % latent.len();
        latent[index] = (0.875 * latent[index] + 0.125 * (f32::from(new_role) - 0.5)).tanh();
        latent[role_index] = (0.9 * latent[role_index] + 0.1 * (f32::from(entity) + 1.0)).tanh();
        Ok(latent)
    }
}

fn action_adapter_score(
    task: &InferenceTask,
    probabilities: &[[f32; 6]],
    assignment: &[u8],
    entity: usize,
    new_role: u8,
) -> Result<f32, String> {
    assignment
        .get(entity)
        .ok_or("edit entity is out of range")?;
    let mut after = assignment.to_vec();
    after[entity] = new_role;
    let mut total = 0.0f64;
    for clause_index in 0..task.clauses.len() {
        let entities = &task.entity_mentions[clause_index];
        if !entities.contains(&(entity as u16)) {
            continue;
        }
        let roles = &task.role_mentions[clause_index];
        let before_value = [
            satisfied(0, entities, roles, assignment),
            satisfied(1, entities, roles, assignment),
            satisfied(2, entities, roles, assignment),
            satisfied(3, entities, roles, assignment),
            satisfied(4, entities, roles, assignment),
            satisfied(5, entities, roles, assignment),
        ];
        let after_value = [
            satisfied(0, entities, roles, &after),
            satisfied(1, entities, roles, &after),
            satisfied(2, entities, roles, &after),
            satisfied(3, entities, roles, &after),
            satisfied(4, entities, roles, &after),
            satisfied(5, entities, roles, &after),
        ];
        let distribution = probabilities
            .get(clause_index)
            .ok_or("identity class probability row is missing")?;
        total += distribution
            .iter()
            .zip(after_value.iter().zip(before_value))
            .map(|(probability, (next, prior))| f64::from(*probability) * f64::from(next - prior))
            .sum::<f64>();
    }
    Ok(total as f32)
}

fn satisfied(kind: usize, entities: &[u16], roles: &[u8], assignment: &[u8]) -> f32 {
    match kind {
        0 | 5 if entities.len() == 2 => {
            let equal =
                assignment[usize::from(entities[0])] == assignment[usize::from(entities[1])];
            if (kind == 5 && equal) || (kind == 0 && !equal) {
                1.0
            } else {
                0.0
            }
        }
        1 if !entities.is_empty() && roles.len() == 1 => {
            let count = entities
                .iter()
                .filter(|entity| assignment[usize::from(**entity)] == roles[0])
                .count();
            if count == 1 {
                1.0
            } else {
                0.0
            }
        }
        2 | 3 if entities.len() == 1 && roles.len() == 1 => {
            let equal = assignment[usize::from(entities[0])] == roles[0];
            if (kind == 2 && equal) || (kind == 3 && !equal) {
                1.0
            } else {
                0.0
            }
        }
        4 if entities.len() == 1 && roles.len() == 2 && roles[0] != roles[1] => 1.0,
        4 if entities.len() == 2 && roles.len() == 2 => {
            let pairings = [
                ((entities[0], roles[0]), (entities[1], roles[1])),
                ((entities[0], roles[1]), (entities[1], roles[0])),
            ];
            pairings
                .iter()
                .map(|((if_entity, if_role), (then_entity, then_role))| {
                    if assignment[usize::from(*if_entity)] != *if_role
                        || assignment[usize::from(*then_entity)] != *then_role
                    {
                        1.0
                    } else {
                        0.0
                    }
                })
                .sum::<f32>()
                / 2.0
        }
        _ => 0.0,
    }
}

fn generate(
    request_path: &Path,
    weights_path: &Path,
    label_path: &Path,
    trace_path: &Path,
) -> Result<(), String> {
    let weights_bytes = fs::read(weights_path).map_err(|error| format!("read weights: {error}"))?;
    let weights: ProposalWeights =
        serde_json::from_slice(&weights_bytes).map_err(|error| error.to_string())?;
    weights.validate()?;
    let digest: [u8; 32] = Sha256::digest(&weights_bytes).into();
    let proposal_sha256 = hex_digest(digest);
    let mut label_output = new_writer(label_path)?;
    let mut trace_output = new_writer(trace_path)?;
    let mut total_states = 0usize;
    let mut total_rollouts = 0usize;
    for request in read_jsonl::<Request>(request_path)? {
        validate_request(&request)?;
        let proposal = FixedProposal {
            task_id: &request.task.id,
            static_features: &request.static_candidate_features,
            clause_probabilities: &request.clause_kind_probabilities,
            weights: &weights,
            digest,
        };
        let (states, trajectories) = collect_states(&request, &proposal, &proposal_sha256)?;
        let labels = build_reachability_dataset(
            &request.task,
            &request.inference,
            &request.features,
            &states,
            request.base_seed,
            request.rollouts_per_state,
            &proposal,
        )
        .map_err(|error| format!("v02 V_reach labels for {}: {error}", request.task.id))?;
        total_states += labels.states.len();
        total_rollouts += labels
            .states
            .iter()
            .map(|state| state.rollouts.len())
            .sum::<usize>();
        serde_json::to_writer(&mut label_output, &labels).map_err(|error| error.to_string())?;
        label_output
            .write_all(b"\n")
            .map_err(|error| error.to_string())?;
        let traces = TraceDataset {
            schema: "r1-proposal-trajectories-v02",
            task_id: request.task.id.clone(),
            sensor_artifact_sha256: request.features.sensor_artifact_sha256.clone(),
            proposal_sha256: proposal_sha256.clone(),
            trajectory_steps: request.trajectory_steps,
            trajectories,
        };
        serde_json::to_writer(&mut trace_output, &traces).map_err(|error| error.to_string())?;
        trace_output
            .write_all(b"\n")
            .map_err(|error| error.to_string())?;
    }
    label_output.flush().map_err(|error| error.to_string())?;
    trace_output.flush().map_err(|error| error.to_string())?;
    println!("R1_V02_LABELS_WRITTEN states={total_states} rollouts={total_rollouts} proposal_sha256={proposal_sha256}");
    Ok(())
}

fn validate_request(request: &Request) -> Result<(), String> {
    let n = usize::from(request.inference.n);
    let k = usize::from(request.inference.k);
    if request.task.id != request.inference.id
        || request.task.n != request.inference.n
        || request.task.k != request.inference.k
    {
        return Err("private/public task shape mismatch".to_owned());
    }
    if request.static_candidate_features.len() != n
        || request
            .static_candidate_features
            .iter()
            .any(|row| row.len() != k || row.iter().any(|v| v.len() != STATIC_FEATURES))
        || request.clause_kind_probabilities.len() != request.inference.clauses.len()
        || request.inference.entity_mentions.len() != request.inference.clauses.len()
        || request.inference.role_mentions.len() != request.inference.clauses.len()
    {
        return Err(format!(
            "v02 public feature shape mismatch for {}",
            request.task.id
        ));
    }
    for distribution in &request.clause_kind_probabilities {
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
                "identity class probabilities must be finite normalized six-way rows".to_owned(),
            );
        }
    }
    if request.teacher_states.is_empty()
        || request.rollouts_per_state == 0
        || request.trajectory_steps == 0
    {
        return Err("v02 request needs teacher states, rollouts and trajectory steps".to_owned());
    }
    Ok(())
}

fn collect_states<P: FrozenProposal>(
    request: &Request,
    proposal: &P,
    proposal_sha: &str,
) -> Result<(Vec<IndividualState>, Vec<ProposalTrajectory>), String> {
    let mut states = Vec::new();
    let mut ids = HashSet::new();
    for teacher in &request.teacher_states {
        if teacher.assignment.len() != usize::from(request.task.n)
            || teacher
                .assignment
                .iter()
                .any(|role| *role >= request.task.k)
        {
            return Err("teacher assignment is outside the task".to_owned());
        }
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
        .collect::<std::collections::BTreeMap<_, _>>();
    let mut trajectories = Vec::with_capacity(request.trace_state_indices.len());
    for &state_index in &request.trace_state_indices {
        let teacher = state_by_index
            .get(&state_index)
            .ok_or("trace state index is missing from teacher set")?;
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
                let action =
                    sample_action(&distribution, &request.inference, &assignment, &mut rng)?;
                let next_latent =
                    proposal.advance_latent(&context, action.entity, action.new_role)?;
                (action, next_latent)
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
            proposal_sha256: proposal_sha.to_owned(),
            points,
        });
    }
    Ok((states, trajectories))
}

fn push_state(
    states: &mut Vec<IndividualState>,
    ids: &mut HashSet<String>,
    state: IndividualState,
) -> Result<(), String> {
    if !ids.insert(state.state_id.clone()) {
        return Err(format!("duplicate v02 state id {}", state.state_id));
    }
    states.push(state);
    Ok(())
}

fn sample_action(
    distribution: &[ProposalActionProbability],
    inference: &InferenceTask,
    assignment: &[u8],
    rng: &mut StableRng,
) -> Result<ProposalActionProbability, String> {
    if distribution.is_empty() {
        return Err("proposal emitted no legal edits".to_owned());
    }
    let mut sum = 0.0;
    for (i, action) in distribution.iter().enumerate() {
        if usize::from(action.entity) >= assignment.len()
            || action.new_role >= inference.k
            || action.new_role == assignment[usize::from(action.entity)]
            || !action.probability.is_finite()
            || action.probability < 0.0
        {
            return Err("proposal emitted an invalid action or probability".to_owned());
        }
        if distribution[..i]
            .iter()
            .any(|prior| prior.entity == action.entity && prior.new_role == action.new_role)
        {
            return Err("proposal emitted a duplicate action".to_owned());
        }
        sum += action.probability;
    }
    if !sum.is_finite() || (sum - 1.0).abs() > 1e-6 {
        return Err("proposal probabilities are not normalized".to_owned());
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
        .ok_or_else(|| "proposal emitted no legal edits".to_owned())
}

struct StableRng {
    state: u64,
}
impl StableRng {
    fn new(seed: u64) -> Self {
        Self { state: seed }
    }
    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        value ^ (value >> 31)
    }
    fn unit_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / ((1u64 << 53) as f64))
    }
}

fn derive_seed(base: u64, state_id: &str, rollout_index: u32) -> u64 {
    let mut hash = Sha256::new();
    hash.update(base.to_le_bytes());
    hash.update(state_id.as_bytes());
    hash.update(rollout_index.to_le_bytes());
    u64::from_le_bytes(hash.finalize()[..8].try_into().expect("SHA-256 prefix"))
}

fn read_jsonl<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<Vec<T>, String> {
    let file = File::open(path).map_err(|error| format!("open {}: {error}", path.display()))?;
    BufReader::new(file)
        .lines()
        .enumerate()
        .filter_map(|(index, line)| match line {
            Ok(value) if value.trim().is_empty() => None,
            Ok(value) => Some(
                serde_json::from_str(&value)
                    .map_err(|error| format!("parse {}:{}: {error}", path.display(), index + 1)),
            ),
            Err(error) => Some(Err(format!(
                "read {}:{}: {error}",
                path.display(),
                index + 1
            ))),
        })
        .collect()
}

fn new_writer(path: &Path) -> Result<BufWriter<File>, String> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| format!("create {}: {error}", path.display()))?;
    Ok(BufWriter::new(file))
}

fn score(weights: &ProposalWeights, features: &[f32]) -> f32 {
    let mut output = weights.b2;
    for (index, (row, bias)) in weights.w1.iter().zip(&weights.b1).enumerate() {
        let hidden = row
            .iter()
            .zip(features)
            .fold(*bias, |sum, (weight, feature)| sum + weight * feature)
            .tanh();
        output += weights.w2[index] * hidden;
    }
    output
}

fn hex_digest(digest: [u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in digest {
        output.push(HEX[usize::from(byte >> 4)] as char);
        output.push(HEX[usize::from(byte & 0x0f)] as char);
    }
    output
}

fn main() {
    let args = env::args().collect::<Vec<_>>();
    if args.len() != 6 || args[1] != "generate" {
        eprintln!("{USAGE}");
        std::process::exit(2);
    }
    if let Err(error) = generate(
        Path::new(&args[2]),
        Path::new(&args[3]),
        Path::new(&args[4]),
        Path::new(&args[5]),
    ) {
        eprintln!("R1_V02_DATA_FAILED {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn implication_tautology_has_zero_edit_delta() {
        let task = InferenceTask {
            id: "t".into(),
            family_id: "f".into(),
            n: 2,
            k: 2,
            role_anonymous: false,
            global_text: String::new(),
            clauses: vec!["x".into()],
            entity_mentions: vec![vec![0]],
            role_mentions: vec![vec![0, 1]],
        };
        let probabilities = [[0.0, 0.0, 0.0, 0.0, 1.0, 0.0]];
        assert_eq!(
            action_adapter_score(&task, &probabilities, &[0, 1], 0, 1).unwrap(),
            0.0
        );
    }

    #[test]
    fn seeded_trace_rng_replays_identically() {
        let seed = derive_seed(20260926, "task-s0003-trace-v02", 0);
        let mut left = StableRng::new(seed);
        let mut right = StableRng::new(seed);
        let left_values = (0..64).map(|_| left.next_u64()).collect::<Vec<_>>();
        let right_values = (0..64).map(|_| right.next_u64()).collect::<Vec<_>>();
        assert_eq!(left_values, right_values);
        assert_eq!(left.state, right.state);
    }

    #[test]
    fn class_balanced_expected_delta_matches_kind_probabilities() {
        let task = InferenceTask {
            id: "t".into(),
            family_id: "f".into(),
            n: 2,
            k: 2,
            role_anonymous: false,
            global_text: String::new(),
            clauses: vec!["different".into()],
            entity_mentions: vec![vec![0, 1]],
            role_mentions: vec![vec![]],
        };
        let probabilities = [[0.0, 0.0, 0.0, 0.0, 0.0, 1.0]];
        assert_eq!(
            action_adapter_score(&task, &probabilities, &[0, 1], 1, 0).unwrap(),
            1.0
        );
    }
}
