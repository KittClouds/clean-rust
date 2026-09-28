use r1_proposal_training::{
    build_reachability_dataset, build_teacher_target, ExactSolutionClasses, FrozenProposal,
    IndividualState, ProposalActionProbability, ProposalContext, PublicFeatures,
};
use r1_world::{InferenceTask, Task};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::Path;

const DEFAULT_SOLUTION_CAP: usize = 1_000_000;
const PROPOSAL_INPUT_DIM: usize = 10;
const STATIC_FEATURE_DIM: usize = 8;
const USAGE: &str = concat!(
    "usage:\n",
    "  r1-proposal-data teacher PRIVATE_TASKS_JSONL PUBLIC_TASKS_JSONL SUPPORT_MANIFEST_JSON STATES_PER_FAMILY OUTPUT_JSONL\n",
    "  r1-proposal-data label-vreach REQUESTS_JSONL FROZEN_PROPOSAL_JSON OUTPUT_JSONL\n",
    "  r1-proposal-data --help"
);

fn main() {
    if let Err(error) = dispatch() {
        eprintln!("R1_PROPOSAL_DATA_FAILED: {error}");
        std::process::exit(1);
    }
}

fn dispatch() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("--help" | "-h") if args.len() == 2 => {
            println!("{USAGE}");
            Ok(())
        }
        Some("teacher") if args.len() == 7 => teacher_command(
            Path::new(&args[2]),
            Path::new(&args[3]),
            Path::new(&args[4]),
            args[5]
                .parse()
                .map_err(|_| "states-per-family must be a positive integer")?,
            Path::new(&args[6]),
        ),
        Some("label-vreach") if args.len() == 5 => vreach_command(
            Path::new(&args[2]),
            Path::new(&args[3]),
            Path::new(&args[4]),
        ),
        _ => Err(USAGE.to_owned()),
    }
}

#[derive(Clone, Debug, Serialize)]
struct TeacherSample {
    schema: &'static str,
    task_id: String,
    family_id: String,
    family_split: String,
    state_index: u32,
    assignment: Vec<u8>,
    raw_solution_count: usize,
    canonical_solution_class_count: usize,
    target: r1_proposal_training::TeacherTarget,
}

fn teacher_command(
    private_path: &Path,
    public_path: &Path,
    manifest_path: &Path,
    states_per_family: u32,
    output_path: &Path,
) -> Result<(), String> {
    if states_per_family == 0 {
        return Err("states-per-family must be positive".to_owned());
    }
    let public_bytes = fs::read(public_path).map_err(|e| format!("read public tasks: {e}"))?;
    let public_sha256 = hex_sha256(&Sha256::digest(&public_bytes));
    let manifest: serde_json::Value = serde_json::from_slice(
        &fs::read(manifest_path).map_err(|e| format!("read support manifest: {e}"))?,
    )
    .map_err(|e| format!("parse support manifest: {e}"))?;
    let declared_sha = manifest
        .pointer("/source/sha256")
        .and_then(serde_json::Value::as_str)
        .ok_or("support manifest is missing source.sha256")?;
    if declared_sha != public_sha256 {
        return Err("public-tasks SHA-256 differs from the frozen support manifest".to_owned());
    }
    let roster: Vec<RosterEntry> = serde_json::from_value(
        manifest
            .get("family_roster")
            .cloned()
            .ok_or("support manifest is missing family_roster")?,
    )
    .map_err(|e| format!("parse support family roster: {e}"))?;
    let mut split_by_task = BTreeMap::new();
    let mut family_by_task = BTreeMap::new();
    for entry in roster {
        if split_by_task
            .insert(entry.task_id.clone(), entry.split)
            .is_some()
        {
            return Err(format!(
                "duplicate task in support roster: {}",
                entry.task_id
            ));
        }
        family_by_task.insert(entry.task_id, entry.family_id);
    }

    let private_tasks: Vec<Task> = read_jsonl(private_path)?;
    let public_tasks: Vec<InferenceTask> = read_jsonl(public_path)?;
    if private_tasks.len() != public_tasks.len() || private_tasks.is_empty() {
        return Err("private/public world row counts differ or are empty".to_owned());
    }
    if split_by_task.len() != private_tasks.len() {
        return Err("support roster row count differs from Stage 0 worlds".to_owned());
    }
    let mut output = create_new_writer(output_path)?;
    let mut written = 0usize;
    for (task, inference) in private_tasks.iter().zip(&public_tasks) {
        if task.id != inference.id
            || task.family_id != inference.family_id
            || task.n != inference.n
            || task.k != inference.k
            || task.role_anonymous != inference.role_anonymous
            || task.clauses.len() != inference.clauses.len()
        {
            return Err(format!(
                "public/private world projection mismatch for {}",
                task.id
            ));
        }
        let split = split_by_task
            .get(&task.id)
            .ok_or_else(|| format!("task absent from support roster: {}", task.id))?;
        if family_by_task.get(&task.id) != Some(&task.family_id) {
            return Err(format!("family roster mismatch for {}", task.id));
        }
        // The first 48 families train the proposal; the next 16 are reserved
        // for engineering validation. Qualification families stay unopened.
        if split != "train" && split != "validation" {
            continue;
        }
        let classes = ExactSolutionClasses::solve(task, DEFAULT_SOLUTION_CAP)
            .map_err(|e| format!("exact classes for {}: {e}", task.id))?;
        for state_index in 0..states_per_family {
            let assignment = sample_assignment(task, state_index);
            let target = build_teacher_target(task, &classes, &assignment)
                .map_err(|e| format!("teacher target for {} state {state_index}: {e}", task.id))?;
            let sample = TeacherSample {
                schema: "r1-proposal-teacher-sample-v01",
                task_id: task.id.clone(),
                family_id: task.family_id.clone(),
                family_split: split.clone(),
                state_index,
                assignment,
                raw_solution_count: classes.raw_solution_count(),
                canonical_solution_class_count: classes.classes().len(),
                target,
            };
            serde_json::to_writer(&mut output, &sample).map_err(|e| e.to_string())?;
            output.write_all(b"\n").map_err(|e| e.to_string())?;
            written += 1;
        }
    }
    output.flush().map_err(|e| e.to_string())?;
    println!("R1_TEACHER_TARGETS_WRITTEN rows={written}");
    Ok(())
}

#[derive(Deserialize)]
struct RosterEntry {
    task_id: String,
    family_id: String,
    split: String,
}

fn sample_assignment(task: &Task, state_index: u32) -> Vec<u8> {
    let seed_text = format!("FAS-R1-ACTION-PROBE-v01\0{}\0{}", task.id, state_index);
    let digest = Sha256::digest(seed_text.as_bytes());
    let seed = u64::from_le_bytes(digest[..8].try_into().expect("SHA-256 prefix"));
    let mut rng = SplitMix64::new(seed);
    (0..task.n)
        .map(|_| (rng.next_u64() % u64::from(task.k)) as u8)
        .collect()
}

struct SplitMix64(u64);

impl SplitMix64 {
    fn new(seed: u64) -> Self {
        Self(seed)
    }

    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }
}

#[derive(Deserialize)]
struct ProposalWeights {
    schema: String,
    architecture: String,
    input_dim: usize,
    hidden_dim: usize,
    w1: Vec<Vec<f32>>,
    b1: Vec<f32>,
    w2: Vec<f32>,
    b2: f32,
}

impl ProposalWeights {
    fn validate(&self) -> Result<(), String> {
        if self.schema != "r1-proposal-weights-v01"
            || self.architecture != "tanh_mlp_candidate_f10_h16_v01"
            || self.input_dim != PROPOSAL_INPUT_DIM
            || self.hidden_dim == 0
            || self.w1.len() != self.hidden_dim
            || self.b1.len() != self.hidden_dim
            || self.w2.len() != self.hidden_dim
            || self.w1.iter().any(|row| row.len() != self.input_dim)
        {
            return Err("proposal weights have an unsupported schema or shape".to_owned());
        }
        if self
            .w1
            .iter()
            .flatten()
            .chain(&self.b1)
            .chain(&self.w2)
            .chain(std::iter::once(&self.b2))
            .any(|value| !value.is_finite())
        {
            return Err("proposal weights contain a non-finite value".to_owned());
        }
        Ok(())
    }
}

#[derive(Deserialize)]
struct VRequest {
    task: Task,
    inference: InferenceTask,
    features: PublicFeatures,
    /// Per entity, per role, the eight H-derived features used by the Python
    /// fit; assignment occupancy features are appended online by this adapter.
    static_candidate_features: Vec<Vec<Vec<f32>>>,
    states: Vec<IndividualState>,
    base_seed: u64,
    rollouts_per_state: u32,
}

struct FixedProposal<'a> {
    task_id: &'a str,
    static_features: &'a [Vec<Vec<f32>>],
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
            return Err("proposal feature cache was bound to another task".to_owned());
        }
        let mut role_loads = vec![0.0f32; usize::from(context.inference.k)];
        for &role in context.assignment {
            let Some(load) = role_loads.get_mut(usize::from(role)) else {
                return Err("assignment role is out of range".to_owned());
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
                if features.len() != STATIC_FEATURE_DIM {
                    return Err("static candidate feature vector must have eight values".to_owned());
                }
                features.push(role_loads[usize::from(old_role)] / n);
                features.push(role_loads[usize::from(new_role)] / n);
                actions.push((entity, new_role));
                scores.push(score(self.weights, &features));
            }
        }
        let max_score = scores.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        let mut total = 0.0f64;
        let weights: Vec<f64> = scores
            .iter()
            .map(|score| {
                let weight = f64::from((*score - max_score).exp());
                total += weight;
                weight
            })
            .collect();
        if actions.is_empty() || !total.is_finite() || total <= 0.0 {
            return Err("proposal has no legal actions or invalid softmax".to_owned());
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

fn score(weights: &ProposalWeights, features: &[f32]) -> f32 {
    let mut hidden = Vec::with_capacity(weights.hidden_dim);
    for (row, bias) in weights.w1.iter().zip(&weights.b1) {
        let activation = row
            .iter()
            .zip(features)
            .fold(*bias, |sum, (weight, feature)| sum + weight * feature)
            .tanh();
        hidden.push(activation);
    }
    weights
        .w2
        .iter()
        .zip(hidden)
        .fold(weights.b2, |sum, (weight, activation)| {
            sum + weight * activation
        })
}

fn vreach_command(
    requests_path: &Path,
    weights_path: &Path,
    output_path: &Path,
) -> Result<(), String> {
    let weights_bytes = fs::read(weights_path).map_err(|e| format!("read frozen proposal: {e}"))?;
    let weights: ProposalWeights = serde_json::from_slice(&weights_bytes)
        .map_err(|e| format!("parse frozen proposal: {e}"))?;
    weights.validate()?;
    let digest: [u8; 32] = Sha256::digest(&weights_bytes).into();
    let mut output = create_new_writer(output_path)?;
    let mut written = 0usize;
    for mut request in read_jsonl::<VRequest>(requests_path)? {
        if request.static_candidate_features.len() != usize::from(request.task.n)
            || request.static_candidate_features.iter().any(|row| {
                row.len() != usize::from(request.task.k)
                    || row.iter().any(|features| {
                        features.len() != STATIC_FEATURE_DIM
                            || features.iter().any(|value| !value.is_finite())
                    })
            })
        {
            return Err(format!(
                "static feature cache shape invalid for {}",
                request.task.id
            ));
        }
        let proposal = FixedProposal {
            task_id: &request.task.id,
            static_features: &request.static_candidate_features,
            weights: &weights,
            digest,
        };
        let labels = build_reachability_dataset(
            &request.task,
            &request.inference,
            &request.features,
            &request.states,
            request.base_seed,
            request.rollouts_per_state,
            &proposal,
        )
        .map_err(|e| format!("V_reach rollout labels for {}: {e}", request.task.id))?;
        serde_json::to_writer(&mut output, &labels).map_err(|e| e.to_string())?;
        output.write_all(b"\n").map_err(|e| e.to_string())?;
        written += labels
            .states
            .iter()
            .map(|state| state.rollouts.len())
            .sum::<usize>();
        request.states.clear();
    }
    output.flush().map_err(|e| e.to_string())?;
    println!(
        "R1_VREACH_LABELS_WRITTEN rollouts={written} proposal_sha256={}",
        hex_sha256(&digest)
    );
    Ok(())
}

fn read_jsonl<T: DeserializeOwned>(path: &Path) -> Result<Vec<T>, String> {
    let file = File::open(path).map_err(|e| format!("open {}: {e}", path.display()))?;
    let mut rows = Vec::new();
    for (index, line) in BufReader::new(file).lines().enumerate() {
        let line = line.map_err(|e| format!("read {} line {}: {e}", path.display(), index + 1))?;
        if line.trim().is_empty() {
            continue;
        }
        rows.push(
            serde_json::from_str(&line)
                .map_err(|e| format!("parse {} line {}: {e}", path.display(), index + 1))?,
        );
    }
    Ok(rows)
}

fn create_new_writer(path: &Path) -> Result<BufWriter<File>, String> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| format!("create new output {}: {e}", path.display()))?;
    Ok(BufWriter::new(file))
}

fn hex_sha256(digest: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(digest.len() * 2);
    for byte in digest {
        output.push(HEX[usize::from(byte >> 4)] as char);
        output.push(HEX[usize::from(byte & 0x0f)] as char);
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    use r1_proposal_training::build_reachability_dataset;
    use r1_world::Clause;

    #[test]
    fn frozen_json_weight_adapter_generates_seeded_posthoc_value_labels() {
        let task = Task {
            id: "adapter-smoke".to_owned(),
            family_id: "adapter-family".to_owned(),
            seed: 17,
            n: 2,
            k: 2,
            clauses: vec![Clause::FixedRole { entity: 0, role: 0 }],
            role_anonymous: false,
        };
        let inference = InferenceTask {
            id: task.id.clone(),
            family_id: task.family_id.clone(),
            n: task.n,
            k: task.k,
            role_anonymous: task.role_anonymous,
            global_text: "public only".to_owned(),
            clauses: vec!["public clause".to_owned()],
            entity_mentions: vec![vec![0]],
            role_mentions: vec![vec![0]],
        };
        let features = PublicFeatures {
            sensor_artifact_sha256: "a".repeat(64),
            global_embedding: vec![0.0; 2048],
            clause_embeddings: vec![vec![0.0; 2048]],
        };
        let weights = ProposalWeights {
            schema: "r1-proposal-weights-v01".to_owned(),
            architecture: "tanh_mlp_candidate_f10_h16_v01".to_owned(),
            input_dim: PROPOSAL_INPUT_DIM,
            hidden_dim: 16,
            w1: vec![vec![0.0; PROPOSAL_INPUT_DIM]; 16],
            b1: vec![0.0; 16],
            w2: vec![0.0; 16],
            b2: 0.0,
        };
        weights.validate().unwrap();
        let digest = [31; 32];
        let static_features = vec![vec![vec![0.0; STATIC_FEATURE_DIM]; 2]; 2];
        let proposal = FixedProposal {
            task_id: &task.id,
            static_features: &static_features,
            weights: &weights,
            digest,
        };
        let labels = build_reachability_dataset(
            &task,
            &inference,
            &features,
            &[IndividualState {
                state_id: "initial".to_owned(),
                assignment: vec![1, 0],
                latent_state: vec![0.0; 128],
                remaining_budget: 4,
            }],
            92,
            3,
            &proposal,
        )
        .unwrap();
        assert!(labels.states[0]
            .rollouts
            .iter()
            .all(|rollout| rollout.proposal_sha256 == hex_sha256(&digest)));
        assert!(labels.states[0]
            .rollouts
            .iter()
            .all(|rollout| rollout.transitions == 4));
    }
}
