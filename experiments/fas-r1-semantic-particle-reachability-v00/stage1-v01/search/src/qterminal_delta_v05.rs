//! Frozen V05 clausewise-Q action deltas for proposal scoring.
//!
//! The Q model's clause/global projections are cached per task. At each state,
//! an edit recomputes only clauses incident to its entity; all other terms
//! cancel in `sum(sigmoid(logit_after) - sigmoid(logit_before))`.

use crate::{Edit, FeatureError, SemanticFeatures};
use bytemuck::try_cast_slice;
use hashbrown::HashMap;
use memmap2::{Mmap, MmapOptions};
use r1_world::InferenceTask;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::Read;
use std::ops::Range;
use std::path::Path;

const HIDDEN_DIM: usize = 2048;
const PROJECTION_DIM: usize = 128;
const HEAD_INPUT_DIM: usize = 270;
const HEAD_HIDDEN_DIM: usize = 64;
const MAX_ROLES: usize = 6;
const LAYER_NORM_EPSILON: f32 = 1e-5;
const QTERMINAL_V05_CHECKPOINT_BYTES: usize = 2_279_759;
pub const QTERMINAL_V05_CHECKPOINT_SHA256: &str =
    "00e1654dbd335b9bd7622b8bb65b983a20335f81f226904cc2c808f934d4838c";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QDeltaError(pub String);

impl std::fmt::Display for QDeltaError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for QDeltaError {}

impl From<FeatureError> for QDeltaError {
    fn from(error: FeatureError) -> Self {
        Self(error.0)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct QDeltaBatch {
    pub deltas: Vec<f32>,
    /// Number of per-clause scalar head outputs, excluding cached projections.
    pub clause_logits_scored: u64,
}

#[derive(Deserialize)]
struct ArtifactRecord {
    sha256: String,
    bytes: usize,
}

#[derive(Deserialize)]
struct TensorField {
    name: String,
    shape: Vec<usize>,
    offset_f32: usize,
    count_f32: usize,
}

#[derive(Deserialize)]
struct Manifest {
    schema: String,
    status: String,
    checkpoint: ArtifactRecord,
    binary: ArtifactRecord,
    architecture: HashMap<String, serde_json::Value>,
    fields: Vec<TensorField>,
    float32_values: usize,
    qualification_targets_read: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FeatureKey {
    clauses_ptr: usize,
    global_ptr: usize,
    entity_incidence_ptr: usize,
    role_incidence_ptr: usize,
    mask_ptr: usize,
    entity_mask_ptr: usize,
    role_mask_ptr: usize,
    hidden_dim: usize,
    clauses: usize,
    entities: usize,
    roles: usize,
}

struct PreparedTask {
    key: FeatureKey,
    clauses_by_entity: Box<[Box<[usize]>]>,
    entity_incidence: Box<[u8]>,
    role_incidence: Box<[u8]>,
    role_count_by_clause: Box<[usize]>,
    entity_count_by_clause: Box<[usize]>,
    head_static: Box<[f32]>,
}

/// Memory-mapped Q-terminal model with task-local projection caching.
pub struct FrozenQTerminalDeltaV05 {
    weights: Mmap,
    fields: HashMap<String, Range<usize>>,
    prepared: HashMap<String, PreparedTask>,
    binary_sha256: String,
    checkpoint_sha256: String,
}

impl FrozenQTerminalDeltaV05 {
    /// Load the fixed V258 checkpoint export after checking its source pin and bytes.
    pub fn load(
        manifest_path: impl AsRef<Path>,
        weights_path: impl AsRef<Path>,
    ) -> Result<Self, QDeltaError> {
        let manifest: Manifest = serde_json::from_slice(
            &std::fs::read(manifest_path.as_ref())
                .map_err(|error| QDeltaError(format!("read Q-delta manifest: {error}")))?,
        )
        .map_err(|error| QDeltaError(format!("parse Q-delta manifest: {error}")))?;
        if manifest.schema != "R1_QTERMINAL_DELTA_V05_WEIGHTS_V01"
            || manifest.status != "QTERMINAL_V05_WEIGHTS_EXPORTED"
            || manifest.qualification_targets_read
            || manifest.checkpoint.sha256 != QTERMINAL_V05_CHECKPOINT_SHA256
            || manifest.checkpoint.bytes != QTERMINAL_V05_CHECKPOINT_BYTES
            || cfg!(target_endian = "big")
        {
            return Err(QDeltaError(
                "unexpected or unpinned Q-delta manifest".to_owned(),
            ));
        }
        check_architecture(&manifest.architecture)?;
        let expected_fields = expected_fields();
        if manifest.fields.len() != expected_fields.len() {
            return Err(QDeltaError(
                "Q-delta tensor field count mismatch".to_owned(),
            ));
        }
        let mut fields = HashMap::with_capacity(expected_fields.len());
        let mut expected_offset = 0usize;
        for (actual, (name, shape)) in manifest.fields.iter().zip(expected_fields.iter()) {
            let count = shape.iter().product::<usize>();
            if actual.name != *name
                || actual.shape != *shape
                || actual.offset_f32 != expected_offset
                || actual.count_f32 != count
            {
                return Err(QDeltaError(format!(
                    "Q-delta tensor layout mismatch for {name}"
                )));
            }
            fields.insert(name.to_string(), expected_offset..expected_offset + count);
            expected_offset += count;
        }
        if expected_offset != manifest.float32_values {
            return Err(QDeltaError("Q-delta tensor count mismatch".to_owned()));
        }

        let weights_path = weights_path.as_ref();
        if sha256_file(weights_path)? != manifest.binary.sha256 {
            return Err(QDeltaError("Q-delta binary SHA-256 mismatch".to_owned()));
        }
        let file = File::open(weights_path)
            .map_err(|error| QDeltaError(format!("open Q-delta weights: {error}")))?;
        // This read-only mmap is a receipt-checked local model artifact.
        let weights = unsafe { MmapOptions::new().map(&file) }
            .map_err(|error| QDeltaError(format!("map Q-delta weights: {error}")))?;
        if weights.len() != manifest.binary.bytes || weights.len() != expected_offset * 4 {
            return Err(QDeltaError("Q-delta binary byte count mismatch".to_owned()));
        }
        try_cast_slice::<u8, f32>(&weights[..])
            .map_err(|error| QDeltaError(format!("Q-delta weight alignment error: {error}")))?;
        Ok(Self {
            weights,
            fields,
            prepared: HashMap::new(),
            binary_sha256: manifest.binary.sha256,
            checkpoint_sha256: manifest.checkpoint.sha256,
        })
    }

    pub fn checkpoint_sha256(&self) -> &str {
        &self.checkpoint_sha256
    }

    pub fn binary_sha256(&self) -> &str {
        &self.binary_sha256
    }

    /// Prepare invariant clause/global projections once for an inference task.
    pub fn prepare_task(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
    ) -> Result<(), QDeltaError> {
        features.validate_for(task)?;
        if features.hidden_dim != HIDDEN_DIM || features.role_count > MAX_ROLES {
            return Err(QDeltaError(
                "V05 Q-delta requires H=2048 and at most six roles".to_owned(),
            ));
        }
        validate_feature_surface(features)?;
        let key = feature_key(features);
        if self
            .prepared
            .get(&task.id)
            .is_some_and(|prepared| prepared.key == key)
        {
            return Ok(());
        }
        let weights = self.weight_values()?;
        let clause_semantics = project_rows(
            &features.constraint_embeddings,
            features.constraint_count,
            weights,
            &self.fields,
            ("clause_projection.0.weight", "clause_projection.0.bias"),
            ("clause_projection.1.weight", "clause_projection.1.bias"),
        );
        let global_semantics = project_rows(
            &features.global_embedding,
            1,
            weights,
            &self.fields,
            ("global_projection.0.weight", "global_projection.0.bias"),
            ("global_projection.1.weight", "global_projection.1.bias"),
        );
        let mut clauses_by_entity = vec![Vec::new(); features.entity_count];
        let mut entity_count_by_clause = vec![0usize; features.constraint_count];
        let mut role_count_by_clause = vec![0usize; features.constraint_count];
        for clause in 0..features.constraint_count {
            for (entity, clauses) in clauses_by_entity.iter_mut().enumerate() {
                if features.entity_incidence[clause * features.entity_count + entity] != 0 {
                    clauses.push(clause);
                    entity_count_by_clause[clause] += 1;
                }
            }
            for role in 0..features.role_count {
                role_count_by_clause[clause] +=
                    usize::from(features.role_incidence[clause * features.role_count + role] != 0);
            }
        }
        let mut head_static = vec![0.0f32; features.constraint_count * PROJECTION_DIM];
        let head_weight = tensor(weights, &self.fields, "clause_head.0.weight")?;
        let head_bias = tensor(weights, &self.fields, "clause_head.0.bias")?;
        for clause in 0..features.constraint_count {
            let clause_h =
                &clause_semantics[clause * PROJECTION_DIM..(clause + 1) * PROJECTION_DIM];
            for output in 0..PROJECTION_DIM {
                let row = &head_weight
                    [output * HEAD_INPUT_DIM..output * HEAD_INPUT_DIM + 2 * PROJECTION_DIM];
                let left = dot(&row[..PROJECTION_DIM], clause_h);
                let right = dot(&row[PROJECTION_DIM..], &global_semantics[..PROJECTION_DIM]);
                head_static[clause * PROJECTION_DIM + output] = head_bias[output] + left + right;
            }
        }
        self.prepared.insert(
            task.id.clone(),
            PreparedTask {
                key,
                clauses_by_entity: clauses_by_entity
                    .into_iter()
                    .map(Vec::into_boxed_slice)
                    .collect::<Vec<_>>()
                    .into_boxed_slice(),
                entity_incidence: features.entity_incidence.clone(),
                role_incidence: features.role_incidence.clone(),
                role_count_by_clause: role_count_by_clause.into_boxed_slice(),
                entity_count_by_clause: entity_count_by_clause.into_boxed_slice(),
                head_static: head_static.into_boxed_slice(),
            },
        );
        Ok(())
    }

    /// Return predicted ΔC in the exact candidate order supplied by the scheduler.
    pub fn score_deltas(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
        assignment: &[u8],
        candidates: &[Edit],
    ) -> Result<Vec<f32>, QDeltaError> {
        Ok(self
            .score_deltas_with_costs(task, features, assignment, candidates)?
            .deltas)
    }

    /// Score a complete candidate batch and expose the actual clause-head count.
    pub fn score_deltas_with_costs(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
        assignment: &[u8],
        candidates: &[Edit],
    ) -> Result<QDeltaBatch, QDeltaError> {
        self.prepare_task(task, features)?;
        if assignment.len() != features.entity_count
            || assignment
                .iter()
                .any(|role| usize::from(*role) >= features.role_count)
        {
            return Err(QDeltaError("invalid assignment for V05 Q-delta".to_owned()));
        }
        let prepared = self
            .prepared
            .get(&task.id)
            .ok_or_else(|| QDeltaError("Q-delta task preparation was lost".to_owned()))?;
        let weights = self.weight_values()?;
        let assigned_roles = assignment_counts(assignment, prepared);
        let mut before = vec![0.0f32; features.constraint_count];
        let mut clause_logits_scored = 0u64;
        for (clause, score) in before.iter_mut().enumerate() {
            if features.constraint_mask[clause] != 0 {
                *score = sigmoid(clause_logit(
                    clause,
                    &assigned_roles[clause],
                    features,
                    prepared,
                    weights,
                    &self.fields,
                )?);
                clause_logits_scored += 1;
            }
        }
        let mut deltas = Vec::with_capacity(candidates.len());
        for edit in candidates {
            let entity = usize::from(edit.entity);
            let old_role = assignment
                .get(entity)
                .copied()
                .map(usize::from)
                .ok_or_else(|| QDeltaError("Q-delta edit entity is out of range".to_owned()))?;
            let new_role = usize::from(edit.new_role);
            if new_role >= features.role_count || new_role == old_role {
                return Err(QDeltaError("Q-delta edit role is illegal".to_owned()));
            }
            let mut delta = 0.0f64;
            for &clause in &prepared.clauses_by_entity[entity] {
                if features.constraint_mask[clause] == 0 {
                    continue;
                }
                let mut after_roles = assigned_roles[clause];
                after_roles[old_role] -= 1.0;
                after_roles[new_role] += 1.0;
                let after = sigmoid(clause_logit(
                    clause,
                    &after_roles,
                    features,
                    prepared,
                    weights,
                    &self.fields,
                )?);
                clause_logits_scored += 1;
                delta += f64::from(after - before[clause]);
            }
            let value = delta as f32;
            if !value.is_finite() {
                return Err(QDeltaError(
                    "V05 Q-delta produced a non-finite score".to_owned(),
                ));
            }
            deltas.push(value);
        }
        Ok(QDeltaBatch {
            deltas,
            clause_logits_scored,
        })
    }

    fn weight_values(&self) -> Result<&[f32], QDeltaError> {
        try_cast_slice::<u8, f32>(&self.weights[..])
            .map_err(|error| QDeltaError(format!("Q-delta weight cast failed: {error}")))
    }
}

fn expected_fields() -> Vec<(&'static str, Vec<usize>)> {
    vec![
        ("clause_projection.0.weight", vec![128, 2048]),
        ("clause_projection.0.bias", vec![128]),
        ("clause_projection.1.weight", vec![128]),
        ("clause_projection.1.bias", vec![128]),
        ("global_projection.0.weight", vec![128, 2048]),
        ("global_projection.0.bias", vec![128]),
        ("global_projection.1.weight", vec![128]),
        ("global_projection.1.bias", vec![128]),
        ("clause_head.0.weight", vec![128, 270]),
        ("clause_head.0.bias", vec![128]),
        ("clause_head.1.weight", vec![128]),
        ("clause_head.1.bias", vec![128]),
        ("clause_head.3.weight", vec![64, 128]),
        ("clause_head.3.bias", vec![64]),
        ("clause_head.5.weight", vec![1, 64]),
        ("clause_head.5.bias", vec![1]),
    ]
}

fn check_architecture(
    architecture: &HashMap<String, serde_json::Value>,
) -> Result<(), QDeltaError> {
    let expected = [
        ("hidden_dim", 2048),
        ("projection_dim", 128),
        ("head_hidden_dim", 64),
        ("max_roles", 6),
        ("layer_norm_epsilon", 0),
    ];
    for (name, value) in expected {
        let valid = if name == "layer_norm_epsilon" {
            architecture
                .get(name)
                .and_then(serde_json::Value::as_f64)
                .is_some_and(|observed| (observed - f64::from(LAYER_NORM_EPSILON)).abs() < 1e-10)
        } else {
            architecture.get(name).and_then(serde_json::Value::as_u64) == Some(value)
        };
        if !valid {
            return Err(QDeltaError(format!(
                "Q-delta architecture mismatch at {name}"
            )));
        }
    }
    if architecture.get("gelu").and_then(serde_json::Value::as_str) != Some("libm-f64-erf-v01") {
        return Err(QDeltaError("Q-delta GELU contract mismatch".to_owned()));
    }
    if architecture
        .get("dtype")
        .and_then(serde_json::Value::as_str)
        != Some("float32-le")
        || architecture
            .get("endianness")
            .and_then(serde_json::Value::as_str)
            != Some("little")
    {
        return Err(QDeltaError(
            "Q-delta byte-order contract mismatch".to_owned(),
        ));
    }
    Ok(())
}

fn validate_feature_surface(features: &SemanticFeatures) -> Result<(), QDeltaError> {
    if features.constraint_mask.iter().any(|mask| *mask != 1)
        || features.entity_mask.iter().any(|mask| *mask != 1)
        || features.role_mask.iter().any(|mask| *mask != 1)
        || features.entity_incidence.iter().any(|value| *value > 1)
        || features.role_incidence.iter().any(|value| *value > 1)
        || features
            .constraint_embeddings
            .iter()
            .chain(&features.global_embedding)
            .any(|value| !value.is_finite())
    {
        return Err(QDeltaError(
            "V05 Q-delta requires finite embeddings and binary unpadded public masks".to_owned(),
        ));
    }
    Ok(())
}

fn feature_key(features: &SemanticFeatures) -> FeatureKey {
    FeatureKey {
        clauses_ptr: features.constraint_embeddings.as_ptr() as usize,
        global_ptr: features.global_embedding.as_ptr() as usize,
        entity_incidence_ptr: features.entity_incidence.as_ptr() as usize,
        role_incidence_ptr: features.role_incidence.as_ptr() as usize,
        mask_ptr: features.constraint_mask.as_ptr() as usize,
        entity_mask_ptr: features.entity_mask.as_ptr() as usize,
        role_mask_ptr: features.role_mask.as_ptr() as usize,
        hidden_dim: features.hidden_dim,
        clauses: features.constraint_count,
        entities: features.entity_count,
        roles: features.role_count,
    }
}

fn project_rows(
    input: &[f32],
    rows: usize,
    weights: &[f32],
    fields: &HashMap<String, Range<usize>>,
    linear: (&str, &str),
    norm: (&str, &str),
) -> Vec<f32> {
    let w = tensor(weights, fields, linear.0).expect("validated Q-delta field");
    let b = tensor(weights, fields, linear.1).expect("validated Q-delta field");
    let gamma = tensor(weights, fields, norm.0).expect("validated Q-delta field");
    let beta = tensor(weights, fields, norm.1).expect("validated Q-delta field");
    let mut result = vec![0.0f32; rows * PROJECTION_DIM];
    let mut linear = [0.0f32; PROJECTION_DIM];
    let mut normalized = [0.0f32; PROJECTION_DIM];
    for row in 0..rows {
        let source = &input[row * HIDDEN_DIM..(row + 1) * HIDDEN_DIM];
        linear_into(source, w, b, &mut linear);
        layer_norm(&linear, gamma, beta, &mut normalized);
        for index in 0..PROJECTION_DIM {
            result[row * PROJECTION_DIM + index] = gelu(normalized[index]);
        }
    }
    result
}

fn assignment_counts(assignment: &[u8], prepared: &PreparedTask) -> Vec<[f32; MAX_ROLES]> {
    let mut counts = vec![[0.0f32; MAX_ROLES]; prepared.entity_count_by_clause.len()];
    for (clause, roles) in counts.iter_mut().enumerate() {
        let start = clause * prepared.key.entities;
        for (entity, role) in assignment.iter().enumerate() {
            if prepared.entity_incidence[start + entity] != 0 {
                roles[usize::from(*role)] += 1.0;
            }
        }
    }
    counts
}

fn clause_logit(
    clause: usize,
    assigned: &[f32; MAX_ROLES],
    features: &SemanticFeatures,
    prepared: &PreparedTask,
    weights: &[f32],
    fields: &HashMap<String, Range<usize>>,
) -> Result<f32, QDeltaError> {
    let head_weight = tensor(weights, fields, "clause_head.0.weight")?;
    let mut hidden = [0.0f32; PROJECTION_DIM];
    let mut dynamic = [0.0f32; 14];
    let entity_count = prepared.entity_count_by_clause[clause].max(1) as f32;
    let role_count = prepared.role_count_by_clause[clause].max(1) as f32;
    for role in 0..MAX_ROLES {
        dynamic[role] = assigned[role] / entity_count;
        if role < features.role_count {
            dynamic[6 + role] =
                f32::from(prepared.role_incidence[clause * features.role_count + role]);
        }
    }
    let mut agreement = 0.0f32;
    for role in 0..MAX_ROLES {
        agreement += assigned[role] * dynamic[6 + role];
    }
    dynamic[12] = agreement / (entity_count * role_count);
    dynamic[13] = if prepared.entity_count_by_clause[clause] > 0 {
        1.0
    } else {
        0.0
    };
    for output in 0..PROJECTION_DIM {
        let row = &head_weight
            [output * HEAD_INPUT_DIM + 2 * PROJECTION_DIM..(output + 1) * HEAD_INPUT_DIM];
        hidden[output] =
            prepared.head_static[clause * PROJECTION_DIM + output] + dot(row, &dynamic);
    }
    let norm_gamma = tensor(weights, fields, "clause_head.1.weight")?;
    let norm_beta = tensor(weights, fields, "clause_head.1.bias")?;
    let mut normalized = [0.0f32; PROJECTION_DIM];
    layer_norm(&hidden, norm_gamma, norm_beta, &mut normalized);
    for value in &mut normalized {
        *value = gelu(*value);
    }
    let second_weight = tensor(weights, fields, "clause_head.3.weight")?;
    let second_bias = tensor(weights, fields, "clause_head.3.bias")?;
    let mut second = [0.0f32; HEAD_HIDDEN_DIM];
    linear_into(&normalized, second_weight, second_bias, &mut second);
    for value in &mut second {
        *value = gelu(*value);
    }
    let final_weight = tensor(weights, fields, "clause_head.5.weight")?;
    let final_bias = tensor(weights, fields, "clause_head.5.bias")?;
    Ok(dot(final_weight, &second) + final_bias[0])
}

fn tensor<'a>(
    weights: &'a [f32],
    fields: &HashMap<String, Range<usize>>,
    name: &str,
) -> Result<&'a [f32], QDeltaError> {
    let range = fields
        .get(name)
        .ok_or_else(|| QDeltaError(format!("Q-delta tensor {name} is absent")))?;
    weights
        .get(range.clone())
        .ok_or_else(|| QDeltaError(format!("Q-delta tensor {name} is out of bounds")))
}

fn linear_into(input: &[f32], weights: &[f32], bias: &[f32], output: &mut [f32]) {
    for (index, value) in output.iter_mut().enumerate() {
        let row = &weights[index * input.len()..(index + 1) * input.len()];
        *value = dot(row, input) + bias[index];
    }
}

fn layer_norm(input: &[f32], gamma: &[f32], beta: &[f32], output: &mut [f32]) {
    let mean = input.iter().map(|value| f64::from(*value)).sum::<f64>() / input.len() as f64;
    let variance = input
        .iter()
        .map(|value| {
            let difference = f64::from(*value) - mean;
            difference * difference
        })
        .sum::<f64>()
        / input.len() as f64;
    let inverse = (variance + f64::from(LAYER_NORM_EPSILON)).sqrt().recip();
    for index in 0..input.len() {
        output[index] =
            ((f64::from(input[index]) - mean) * inverse) as f32 * gamma[index] + beta[index];
    }
}

fn gelu(value: f32) -> f32 {
    let x = f64::from(value) / std::f64::consts::SQRT_2;
    let erf = libm::erf(x);
    (0.5 * f64::from(value) * (1.0 + erf)) as f32
}

fn sigmoid(value: f32) -> f32 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exp = value.exp();
        exp / (1.0 + exp)
    }
}

fn dot(left: &[f32], right: &[f32]) -> f32 {
    left.iter().zip(right).map(|(a, b)| *a * *b).sum()
}

fn sha256_file(path: &Path) -> Result<String, QDeltaError> {
    let mut file = File::open(path)
        .map_err(|error| QDeltaError(format!("open {}: {error}", path.display())))?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|error| QDeltaError(format!("hash {}: {error}", path.display())))?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

#[cfg(test)]
mod tests {
    use super::{gelu, sigmoid};

    #[test]
    fn activation_functions_are_stable_at_extremes_and_zero() {
        assert_eq!(gelu(0.0), 0.0);
        assert!((sigmoid(0.0) - 0.5).abs() < 1e-7);
        assert!(sigmoid(80.0) > 0.999);
        assert!(sigmoid(-80.0) < 1e-30);
        assert!(gelu(-8.0).abs() < 1e-6);
        assert!((gelu(8.0) - 8.0).abs() < 1e-5);
    }
}
