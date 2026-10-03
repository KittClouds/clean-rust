//! Frozen float32 inference for the v01 proposal and continuation-value heads.
//! Q_terminal is deliberately absent; this module does not substitute for it.

use crate::{Edit, SemanticFeatures};
use hashbrown::HashMap;
use r1_world::InferenceTask;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

pub const PROPOSAL_V01_SHA256: &str =
    "f8871c7877295e8b200ce40951fdb77b488b09ad7c3221810e0252afcc7969aa";
pub const V_REACH_V01_SHA256: &str =
    "70c66d812996ed26c85c843eacdb78076311314bfd39ef2c6072b03a5de0843b";

const HIDDEN_DIM: usize = 2048;
const LATENT_DIM: usize = 128;
const MAX_ENTITIES: usize = 20;
const MAX_ROLES: usize = 6;
const STATIC_DIM: usize = 8;
const PROPOSAL_INPUT: usize = 10;
const VALUE_INPUT: usize = HIDDEN_DIM * 2 + MAX_ENTITIES * MAX_ROLES + LATENT_DIM + 1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InferenceError(pub String);

impl std::fmt::Display for InferenceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for InferenceError {}

#[derive(Clone, Debug, Deserialize)]
struct ProposalWeights {
    schema: String,
    architecture: String,
    input_dim: usize,
    hidden_dim: usize,
    static_feature_dim: usize,
    feature_schema: String,
    w1: Vec<Vec<f32>>,
    b1: Vec<f32>,
    w2: Vec<f32>,
    b2: f32,
}

#[derive(Clone, Debug, Deserialize)]
struct ValueWeights {
    schema: String,
    architecture: String,
    input_dim: usize,
    hidden_dim: usize,
    budget_normalization_max: u64,
    feature_schema: String,
    w1: Vec<Vec<f32>>,
    b1: Vec<f32>,
    w2: Vec<f32>,
    b2: f32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FeatureToken {
    global_ptr: usize,
    clauses_ptr: usize,
    entity_ptr: usize,
    role_ptr: usize,
    hidden_dim: usize,
    constraints: usize,
    entities: usize,
    roles: usize,
}

struct PreparedTask {
    token: FeatureToken,
    static_features: Box<[[f32; STATIC_DIM]]>,
    mean_clause: Box<[f32]>,
}

/// Pinned v01 proposal/value heads with cached per-task static features.
/// Construct with load_from_paths and prepare a task once before its search.
/// Feature buffers must remain immutable for the duration of a run.
pub struct FrozenProposalValueV01 {
    proposal: ProposalWeights,
    value: ValueWeights,
    proposal_sha256: String,
    value_sha256: String,
    cache: HashMap<String, PreparedTask>,
    value_buffer: Vec<f32>,
}

impl FrozenProposalValueV01 {
    pub fn default_paths() -> (PathBuf, PathBuf) {
        let base = Path::new(
            r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\proposal-value-v01",
        );
        (
            base.join("proposal-weights.json"),
            base.join("v-reach-weights.json"),
        )
    }

    /// Load only the byte-pinned v01 proposal and V_reach artifacts.
    pub fn load_from_paths(
        proposal_path: impl AsRef<Path>,
        value_path: impl AsRef<Path>,
    ) -> Result<Self, InferenceError> {
        let (proposal, proposal_sha256) =
            read_pinned::<ProposalWeights>(proposal_path, PROPOSAL_V01_SHA256)?;
        let (value, value_sha256) = read_pinned::<ValueWeights>(value_path, V_REACH_V01_SHA256)?;
        validate_proposal(&proposal)?;
        validate_value(&value)?;
        Ok(Self {
            proposal,
            value,
            proposal_sha256,
            value_sha256,
            cache: HashMap::new(),
            value_buffer: vec![0.0; VALUE_INPUT],
        })
    }

    pub fn load_default() -> Result<Self, InferenceError> {
        let (proposal, value) = Self::default_paths();
        Self::load_from_paths(proposal, value)
    }

    pub fn proposal_sha256(&self) -> &str {
        &self.proposal_sha256
    }

    pub fn value_sha256(&self) -> &str {
        &self.value_sha256
    }

    pub fn cache_len(&self) -> usize {
        self.cache.len()
    }

    pub fn clear_cache(&mut self) {
        self.cache.clear();
    }

    /// Build and cache H-only candidate features and mean(H). Repeating this
    /// explicit call refreshes the cache; normal scoring reuses the rows.
    pub fn prepare_task(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
    ) -> Result<(), InferenceError> {
        features
            .validate_for(task)
            .map_err(|error| InferenceError(error.to_string()))?;
        validate_dimensions(task, features)?;
        validate_public_incidence(task, features)?;
        let token = feature_token(features);
        let static_features = build_static_candidate_features(task, features)?;
        let mean_clause = mean_clause(features);
        self.cache.insert(
            task.id.clone(),
            PreparedTask {
                token,
                static_features: static_features.into_boxed_slice(),
                mean_clause: mean_clause.into_boxed_slice(),
            },
        );
        Ok(())
    }

    /// Score legal edits in caller order. Returns raw proposal logits; the
    /// scheduler applies its selected greedy or sampling rule.
    pub fn score_edits(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
        assignment: &[u8],
        candidates: &[Edit],
    ) -> Result<Vec<f32>, InferenceError> {
        self.ensure_prepared(task, features)?;
        validate_assignment(task, assignment)?;
        let cached = self
            .cache
            .get(&task.id)
            .expect("prepare called before this access");
        let mut role_loads = [0u32; MAX_ROLES];
        for &role in assignment {
            role_loads[usize::from(role)] += 1;
        }
        let n = assignment.len() as f32;
        let mut scores = Vec::with_capacity(candidates.len());
        let mut input = [0.0f32; PROPOSAL_INPUT];
        for edit in candidates {
            let entity = usize::from(edit.entity);
            let role = usize::from(edit.new_role);
            if entity >= usize::from(task.n)
                || role >= usize::from(task.k)
                || assignment[entity] == edit.new_role
            {
                return Err(InferenceError(
                    "candidate edit is illegal for the assignment".into(),
                ));
            }
            let row = &cached.static_features[entity * usize::from(task.k) + role];
            input[..STATIC_DIM].copy_from_slice(row);
            input[STATIC_DIM] = role_loads[usize::from(assignment[entity])] as f32 / n;
            input[STATIC_DIM + 1] = role_loads[role] as f32 / n;
            scores.push(score_proposal(&self.proposal, &input));
        }
        Ok(scores)
    }

    /// Evaluate sigmoid(V_reach) using the artifact's fixed budget
    /// normalization (64 transitions).
    pub fn v_reach(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
        assignment: &[u8],
        latent_state: &[f32],
        remaining_budget: u64,
    ) -> Result<f32, InferenceError> {
        self.ensure_prepared(task, features)?;
        validate_assignment(task, assignment)?;
        if latent_state.len() != LATENT_DIM {
            return Err(InferenceError(format!(
                "v01 V_reach expects {LATENT_DIM} latent values"
            )));
        }
        if latent_state.iter().any(|value| !value.is_finite()) {
            return Err(InferenceError(
                "V_reach latent state contains a non-finite value".into(),
            ));
        }
        let cached = self
            .cache
            .get(&task.id)
            .expect("prepare called before this access");
        self.value_buffer.fill(0.0);
        self.value_buffer[..HIDDEN_DIM].copy_from_slice(&features.global_embedding);
        self.value_buffer[HIDDEN_DIM..HIDDEN_DIM * 2].copy_from_slice(&cached.mean_clause);
        let assignment_start = HIDDEN_DIM * 2;
        for (entity, &role) in assignment.iter().enumerate() {
            self.value_buffer[assignment_start + entity * MAX_ROLES + usize::from(role)] = 1.0;
        }
        let latent_start = assignment_start + MAX_ENTITIES * MAX_ROLES;
        self.value_buffer[latent_start..latent_start + LATENT_DIM].copy_from_slice(latent_state);
        self.value_buffer[VALUE_INPUT - 1] =
            (remaining_budget as f64 / self.value.budget_normalization_max.max(1) as f64) as f32;
        Ok(score_value(&self.value, &self.value_buffer))
    }

    /// Deterministic latent transition paired with proposal v01's rollout
    /// labels. It is independent of the learned proposal scorer.
    pub fn advance_latent_v01(latent: &[f32], entity: u16, new_role: u8) -> Vec<f32> {
        let mut next = latent.to_vec();
        if next.is_empty() {
            return next;
        }
        let index = usize::from(entity) % next.len();
        let role_index = (usize::from(new_role) * 31 + index + 1) % next.len();
        next[index] = (0.875 * next[index] + 0.125 * (f32::from(new_role) - 0.5)).tanh();
        next[role_index] = (0.9 * next[role_index] + 0.1 * (f32::from(entity) + 1.0)).tanh();
        next
    }

    fn ensure_prepared(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
    ) -> Result<(), InferenceError> {
        let token = feature_token(features);
        if self
            .cache
            .get(&task.id)
            .is_none_or(|cached| cached.token != token)
        {
            self.prepare_task(task, features)?;
        }
        Ok(())
    }
}

fn read_pinned<T: for<'de> Deserialize<'de>>(
    path: impl AsRef<Path>,
    expected_sha256: &str,
) -> Result<(T, String), InferenceError> {
    let bytes = fs::read(path.as_ref())
        .map_err(|error| InferenceError(format!("read {}: {error}", path.as_ref().display())))?;
    let digest = hex_digest(&Sha256::digest(&bytes));
    if digest != expected_sha256 {
        return Err(InferenceError(format!(
            "weight hash mismatch for {}: got {digest}, expected {expected_sha256}",
            path.as_ref().display()
        )));
    }
    let parsed = serde_json::from_slice(&bytes)
        .map_err(|error| InferenceError(format!("parse {}: {error}", path.as_ref().display())))?;
    Ok((parsed, digest))
}

fn validate_proposal(weights: &ProposalWeights) -> Result<(), InferenceError> {
    if weights.schema != "r1-proposal-weights-v01"
        || weights.architecture != "tanh_mlp_candidate_f10_h16_v01"
        || weights.feature_schema != "r1-candidate-features-h-global-entity-role-load-v01"
        || weights.input_dim != PROPOSAL_INPUT
        || weights.hidden_dim != 16
        || weights.static_feature_dim != STATIC_DIM
        || weights.w1.len() != weights.hidden_dim
        || weights.w1.iter().any(|row| row.len() != PROPOSAL_INPUT)
        || weights.b1.len() != weights.hidden_dim
        || weights.w2.len() != weights.hidden_dim
    {
        return Err(InferenceError(
            "unsupported proposal-v01 weight schema or shape".into(),
        ));
    }
    let finite = weights
        .w1
        .iter()
        .flatten()
        .chain(&weights.b1)
        .chain(&weights.w2)
        .chain(std::iter::once(&weights.b2))
        .all(|value| value.is_finite());
    if !finite {
        return Err(InferenceError(
            "proposal-v01 weights contain non-finite values".into(),
        ));
    }
    Ok(())
}

fn validate_value(weights: &ValueWeights) -> Result<(), InferenceError> {
    if weights.schema != "r1-v-reach-weights-v01"
        || weights.architecture != "tanh_mlp_value_4345_h32_v01"
        || weights.feature_schema != "r1-value-input-h-global-meanH-assignment-latent-budget-v01"
        || weights.input_dim != VALUE_INPUT
        || weights.hidden_dim != 32
        || weights.budget_normalization_max == 0
        || weights.w1.len() != weights.hidden_dim
        || weights.w1.iter().any(|row| row.len() != VALUE_INPUT)
        || weights.b1.len() != weights.hidden_dim
        || weights.w2.len() != weights.hidden_dim
    {
        return Err(InferenceError(
            "unsupported V_reach-v01 weight schema or shape".into(),
        ));
    }
    let finite = weights
        .w1
        .iter()
        .flatten()
        .chain(&weights.b1)
        .chain(&weights.w2)
        .chain(std::iter::once(&weights.b2))
        .all(|value| value.is_finite());
    if !finite {
        return Err(InferenceError(
            "V_reach-v01 weights contain non-finite values".into(),
        ));
    }
    Ok(())
}

fn validate_dimensions(
    task: &InferenceTask,
    features: &SemanticFeatures,
) -> Result<(), InferenceError> {
    if features.hidden_dim != HIDDEN_DIM
        || usize::from(task.n) > MAX_ENTITIES
        || usize::from(task.k) > MAX_ROLES
    {
        return Err(InferenceError(format!(
            "v01 heads require hidden_dim={HIDDEN_DIM}, n<=20, and 2<=k<=6"
        )));
    }
    Ok(())
}

fn validate_assignment(task: &InferenceTask, assignment: &[u8]) -> Result<(), InferenceError> {
    if assignment.len() != usize::from(task.n) || assignment.iter().any(|role| *role >= task.k) {
        return Err(InferenceError(
            "assignment shape or role ID is invalid".into(),
        ));
    }
    Ok(())
}

fn validate_public_incidence(
    task: &InferenceTask,
    features: &SemanticFeatures,
) -> Result<(), InferenceError> {
    let n = usize::from(task.n);
    let k = usize::from(task.k);
    for clause in 0..features.constraint_count {
        for entity in 0..n {
            let expected = u8::from(task.entity_mentions[clause].contains(&(entity as u16)));
            if features.entity_incidence[clause * n + entity] != expected {
                return Err(InferenceError(
                    "entity incidence differs from public projection".into(),
                ));
            }
        }
        for role in 0..k {
            let expected = u8::from(task.role_mentions[clause].contains(&(role as u8)));
            if features.role_incidence[clause * k + role] != expected {
                return Err(InferenceError(
                    "role incidence differs from public projection".into(),
                ));
            }
        }
    }
    Ok(())
}

fn feature_token(features: &SemanticFeatures) -> FeatureToken {
    FeatureToken {
        global_ptr: features.global_embedding.as_ptr() as usize,
        clauses_ptr: features.constraint_embeddings.as_ptr() as usize,
        entity_ptr: features.entity_incidence.as_ptr() as usize,
        role_ptr: features.role_incidence.as_ptr() as usize,
        hidden_dim: features.hidden_dim,
        constraints: features.constraint_count,
        entities: features.entity_count,
        roles: features.role_count,
    }
}

fn build_static_candidate_features(
    task: &InferenceTask,
    features: &SemanticFeatures,
) -> Result<Vec<[f32; STATIC_DIM]>, InferenceError> {
    let n = usize::from(task.n);
    let k = usize::from(task.k);
    let clauses = features.constraint_count;
    let d = features.hidden_dim;
    let mut entity_sum = vec![0.0f64; n * d];
    let mut role_sum = vec![0.0f64; k * d];
    let mut entity_count = vec![0u64; n];
    let mut role_count = vec![0u64; k];
    let mut pair_count = vec![0u64; n * k];
    for clause in 0..clauses {
        let vector = &features.constraint_embeddings[clause * d..(clause + 1) * d];
        for entity in 0..n {
            if features.entity_incidence[clause * n + entity] == 0 {
                continue;
            }
            entity_count[entity] += 1;
            let offset = entity * d;
            for dim in 0..d {
                entity_sum[offset + dim] += f64::from(vector[dim]);
            }
            for role in 0..k {
                if features.role_incidence[clause * k + role] != 0 {
                    pair_count[entity * k + role] += 1;
                }
            }
        }
        for (role, count) in role_count.iter_mut().enumerate() {
            if features.role_incidence[clause * k + role] == 0 {
                continue;
            }
            *count += 1;
            let offset = role * d;
            for dim in 0..d {
                role_sum[offset + dim] += f64::from(vector[dim]);
            }
        }
    }
    let mut entity_ctx = vec![0.0f64; n * d];
    let mut role_ctx = vec![0.0f64; k * d];
    for (entity, &count) in entity_count.iter().enumerate() {
        if count == 0 {
            continue;
        }
        let offset = entity * d;
        for dim in 0..d {
            entity_ctx[offset + dim] = entity_sum[offset + dim] / count as f64;
        }
    }
    for (role, &count) in role_count.iter().enumerate() {
        if count == 0 {
            continue;
        }
        let offset = role * d;
        for dim in 0..d {
            role_ctx[offset + dim] = role_sum[offset + dim] / count as f64;
        }
    }
    let global = features
        .global_embedding
        .iter()
        .map(|value| f64::from(*value))
        .collect::<Vec<_>>();
    let global_norm = norm(&global);
    let entity_norms = (0..n)
        .map(|entity| norm(&entity_ctx[entity * d..(entity + 1) * d]))
        .collect::<Vec<_>>();
    let role_norms = (0..k)
        .map(|role| norm(&role_ctx[role * d..(role + 1) * d]))
        .collect::<Vec<_>>();
    let denominator = clauses.max(1) as f64;
    let dim_scale = (d as f64).sqrt();
    let mut rows = Vec::with_capacity(n * k);
    for entity in 0..n {
        for role in 0..k {
            let ev = &entity_ctx[entity * d..(entity + 1) * d];
            let rv = &role_ctx[role * d..(role + 1) * d];
            let en = entity_norms[entity];
            let rn = role_norms[role];
            let values = [
                dot(&global, ev) / (global_norm * en + 1e-12),
                dot(&global, rv) / (global_norm * rn + 1e-12),
                dot(ev, rv) / (en * rn + 1e-12),
                en / dim_scale,
                rn / dim_scale,
                entity_count[entity] as f64 / denominator,
                role_count[role] as f64 / denominator,
                pair_count[entity * k + role] as f64 / denominator,
            ];
            let mut row = [0.0f32; STATIC_DIM];
            for (dst, src) in row.iter_mut().zip(values) {
                *dst = src as f32;
            }
            if row.iter().any(|value| !value.is_finite()) {
                return Err(InferenceError(
                    "static candidate feature is non-finite".into(),
                ));
            }
            rows.push(row);
        }
    }
    Ok(rows)
}

fn mean_clause(features: &SemanticFeatures) -> Vec<f32> {
    if features.constraint_count == 0 {
        return vec![0.0; HIDDEN_DIM];
    }
    let count = features.constraint_count as f64;
    (0..HIDDEN_DIM)
        .map(|dim| {
            let mut sum = 0.0f64;
            for clause in 0..features.constraint_count {
                sum += f64::from(features.constraint_embeddings[clause * HIDDEN_DIM + dim]);
            }
            (sum / count) as f32
        })
        .collect()
}

fn norm(values: &[f64]) -> f64 {
    values.iter().map(|value| value * value).sum::<f64>().sqrt()
}

fn dot(left: &[f64], right: &[f64]) -> f64 {
    left.iter().zip(right).map(|(a, b)| a * b).sum()
}

fn score_proposal(weights: &ProposalWeights, input: &[f32; PROPOSAL_INPUT]) -> f32 {
    let mut output = weights.b2;
    for hidden in 0..weights.hidden_dim {
        let mut activation = weights.b1[hidden];
        for (weight, feature) in weights.w1[hidden].iter().zip(input) {
            activation += weight * feature;
        }
        output += weights.w2[hidden] * activation.tanh();
    }
    output
}

fn score_value(weights: &ValueWeights, input: &[f32]) -> f32 {
    let mut logit = weights.b2;
    for hidden in 0..weights.hidden_dim {
        let mut activation = weights.b1[hidden];
        for (weight, feature) in weights.w1[hidden].iter().zip(input) {
            activation += weight * feature;
        }
        logit += weights.w2[hidden] * activation.tanh();
    }
    if logit >= 0.0 {
        1.0 / (1.0 + (-logit).exp())
    } else {
        let exp = logit.exp();
        exp / (1.0 + exp)
    }
}

fn hex_digest(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
