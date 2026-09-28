//! Frozen identity-composition terminal scoring for Stage 1.
//!
//! This composes the pinned six-way clause identity head with public
//! incidence and the candidate assignment. The calibrated wrapper is
//! separate so an uncalibrated composition can never masquerade as the
//! common terminal probability.

use crate::{PolicyCosts, PolicyError, PolicyValue, SelectorInput, TerminalScorer};
use hashbrown::HashMap;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

pub const IDENTITY_LINEAR_V03_METADATA_SHA256: &str =
    "b1fc47ce69a77a14d920f63fe30a92042a2334df63c055546854ca721d8f6e1d";
pub const IDENTITY_LINEAR_V03_BINARY_SHA256: &str =
    "a3b1875728591fd2eeadd50986355d0062746949ce5308e6c2372625ac363cc0";
pub const Q_TERMINAL_V06_CALIBRATION_METADATA_SHA256: &str =
    "944fbac122a8bacef9aa1ce60d61455f55114d8bad4a630f2742196622338197";
pub const Q_TERMINAL_V06_CALIBRATION_BINARY_SHA256: &str =
    "1c98c01a428fe6b542220b5a0e70b6ee094e7e9e40eedd14a0a9a32beb84f82b";
pub const Q_TERMINAL_V06_REFERENCE_SHA256: &str =
    "550a781ad9b0f36a591353cc8bbd18f69c0e780b49d27e3f5daf14f8ead01ba1";
pub const Q_TERMINAL_V07_TASK_POOLED_WEIGHT: f64 = 0.75;

const HIDDEN_DIM: usize = 2048;
const KIND_COUNT: usize = 6;
const WEIGHTS_OFFSET: usize = 16_384;
const BIAS_OFFSET: usize = 65_536;
const BINARY_BYTES: usize = 65_560;
const KIND_ORDER: [&str; KIND_COUNT] = [
    "different",
    "exactly_one_role",
    "fixed_role",
    "forbidden_role",
    "implies_not_role",
    "same",
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TerminalError(pub String);

impl std::fmt::Display for TerminalError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for TerminalError {}

#[derive(Clone, Debug, Deserialize)]
struct ExportField {
    dtype: String,
    shape: Vec<usize>,
    byte_offset: usize,
    byte_length: usize,
}

#[derive(Clone, Debug, Deserialize)]
struct ExportMetadata {
    schema: String,
    kind_order: Vec<String>,
    input_dim: usize,
    output_dim: usize,
    binary_file: String,
    binary_sha256: String,
    binary_bytes: usize,
    fields: std::collections::HashMap<String, ExportField>,
    parity_pass: bool,
}

#[derive(Clone, Debug, Deserialize)]
struct CalibrationMetadata {
    schema: String,
    dtype: String,
    binary_file: String,
    binary_sha256: String,
    binary_bytes: usize,
    coefficient_count: usize,
    coefficient_order: Vec<String>,
    calibration_training_split: String,
    validation_or_test_labels_used_for_fit: bool,
}

/// Raw incidence-composition score from the frozen v03 identity head.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TerminalPrediction {
    /// Sum of per-clause log satisfaction probabilities; negative infinity
    /// represents a zero-probability candidate under the factorized model.
    pub semantic_log_score: f64,
    /// Exponentiated raw score, before the separately fitted calibration.
    pub raw_probability: f64,
}

/// Batch action deltas and exact public-incidence work counts for proposal
/// scoring. Candidate order matches the supplied edit slice.
#[derive(Clone, Debug, PartialEq)]
pub struct ExpectedActionDeltaBatch {
    pub deltas: Vec<f64>,
    pub affected_clause_counts: Vec<u32>,
}

/// Byte-pinned identity-linear export and exact public-incidence composition.
pub struct IdentityCompositionV03 {
    weights: Box<[f32]>,
    bias: [f32; KIND_COUNT],
    metadata_sha256: String,
    binary_sha256: String,
    prepared: HashMap<String, PreparedTask>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FeatureToken {
    global_ptr: usize,
    clauses_ptr: usize,
    entity_incidence_ptr: usize,
    role_incidence_ptr: usize,
    constraint_mask_ptr: usize,
    entity_mask_ptr: usize,
    role_mask_ptr: usize,
    hidden_dim: usize,
    constraint_count: usize,
    entity_count: usize,
    role_count: usize,
}

struct PreparedTask {
    token: FeatureToken,
    raw_probabilities: Box<[[f64; KIND_COUNT]]>,
    conditioned_probabilities: Box<[[f64; KIND_COUNT]]>,
    task_identity_prior: [f64; KIND_COUNT],
    entities_by_clause: Box<[Box<[usize]>]>,
    roles_by_clause: Box<[Box<[usize]>]>,
    supported_kinds_by_clause: Box<[Box<[u8]>]>,
    clauses_by_entity: Box<[Box<[usize]>]>,
}

impl IdentityCompositionV03 {
    pub fn default_paths() -> (PathBuf, PathBuf) {
        let base = Path::new(
            r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v03",
        );
        (
            base.join("identity-head-export.json"),
            base.join("identity-head-f32le.bin"),
        )
    }

    /// Load only the frozen v03 metadata and binary identified by their hashes.
    pub fn load_from_paths(
        metadata_path: impl AsRef<Path>,
        binary_path: impl AsRef<Path>,
    ) -> Result<Self, TerminalError> {
        let metadata_bytes = fs::read(metadata_path.as_ref()).map_err(|error| {
            TerminalError(format!(
                "read {}: {error}",
                metadata_path.as_ref().display()
            ))
        })?;
        let metadata_sha256 = sha256_hex(&metadata_bytes);
        if metadata_sha256 != IDENTITY_LINEAR_V03_METADATA_SHA256 {
            return Err(TerminalError(format!(
                "identity metadata hash mismatch: got {metadata_sha256}"
            )));
        }
        let metadata: ExportMetadata = serde_json::from_slice(&metadata_bytes)
            .map_err(|error| TerminalError(format!("parse identity metadata: {error}")))?;
        validate_metadata(&metadata, binary_path.as_ref())?;

        let binary = fs::read(binary_path.as_ref()).map_err(|error| {
            TerminalError(format!("read {}: {error}", binary_path.as_ref().display()))
        })?;
        let binary_sha256 = sha256_hex(&binary);
        if binary_sha256 != IDENTITY_LINEAR_V03_BINARY_SHA256
            || metadata.binary_sha256 != binary_sha256
        {
            return Err(TerminalError(format!(
                "identity binary hash mismatch: got {binary_sha256}"
            )));
        }
        if binary.len() != BINARY_BYTES {
            return Err(TerminalError(format!(
                "identity binary length is {}, expected {BINARY_BYTES}",
                binary.len()
            )));
        }

        let weights = read_f32_slice(&binary, WEIGHTS_OFFSET, KIND_COUNT * HIDDEN_DIM)?;
        let bias_values = read_f32_slice(&binary, BIAS_OFFSET, KIND_COUNT)?;
        if weights
            .iter()
            .chain(&bias_values)
            .any(|value| !value.is_finite())
        {
            return Err(TerminalError(
                "identity export contains non-finite weights".into(),
            ));
        }
        let bias = bias_values
            .try_into()
            .map_err(|_| TerminalError("identity bias shape mismatch".into()))?;
        Ok(Self {
            weights: weights.into_boxed_slice(),
            bias,
            metadata_sha256,
            binary_sha256,
            prepared: HashMap::new(),
        })
    }

    pub fn load_default() -> Result<Self, TerminalError> {
        let (metadata, binary) = Self::default_paths();
        Self::load_from_paths(metadata, binary)
    }

    pub fn metadata_sha256(&self) -> &str {
        &self.metadata_sha256
    }

    pub fn binary_sha256(&self) -> &str {
        &self.binary_sha256
    }

    /// Prepare raw and incidence-conditioned clause posteriors once per task.
    /// Reusing a task ID with a changed feature token is rejected.
    pub fn prepare_task(
        &mut self,
        task_id: &str,
        features: &crate::SemanticFeatures,
    ) -> Result<(), TerminalError> {
        let token = feature_token(features);
        if let Some(existing) = self.prepared.get(task_id) {
            return if existing.token == token {
                Ok(())
            } else {
                Err(TerminalError(format!(
                    "Q_terminal task {task_id} was reused with changed feature token"
                )))
            };
        }
        validate_feature_surface(features)?;
        let mut raw_probabilities = Vec::with_capacity(features.constraint_count);
        let mut conditioned_probabilities = Vec::with_capacity(features.constraint_count);
        let mut entities_by_clause = Vec::with_capacity(features.constraint_count);
        let mut roles_by_clause = Vec::with_capacity(features.constraint_count);
        let mut supported_kinds_by_clause = Vec::with_capacity(features.constraint_count);
        let mut clauses_by_entity = vec![Vec::new(); features.entity_count];
        for clause in 0..features.constraint_count {
            let entities = incidence_ids(
                &features.entity_incidence
                    [clause * features.entity_count..(clause + 1) * features.entity_count],
            )?;
            let roles = incidence_ids(
                &features.role_incidence
                    [clause * features.role_count..(clause + 1) * features.role_count],
            )?;
            let raw_h =
                &features.constraint_embeddings[clause * HIDDEN_DIM..(clause + 1) * HIDDEN_DIM];
            let raw = self.identity_probabilities(raw_h)?;
            let (conditioned, _) =
                Self::incidence_conditioned_probabilities(&raw, &entities, &roles)?;
            let supported = supported_kind_ids(&entities, &roles)?
                .iter()
                .map(|&kind| kind as u8)
                .collect::<Vec<_>>()
                .into_boxed_slice();
            for &entity in &entities {
                clauses_by_entity[entity].push(clause);
            }
            raw_probabilities.push(raw);
            conditioned_probabilities.push(conditioned);
            entities_by_clause.push(entities.into_boxed_slice());
            roles_by_clause.push(roles.into_boxed_slice());
            supported_kinds_by_clause.push(supported);
        }
        let mut task_identity_prior = [0.0f64; KIND_COUNT];
        for probabilities in &raw_probabilities {
            for (prior, probability) in task_identity_prior.iter_mut().zip(probabilities) {
                *prior += probability;
            }
        }
        for prior in &mut task_identity_prior {
            *prior /= features.constraint_count as f64;
        }
        self.prepared.insert(
            task_id.to_owned(),
            PreparedTask {
                token,
                raw_probabilities: raw_probabilities.into_boxed_slice(),
                conditioned_probabilities: conditioned_probabilities.into_boxed_slice(),
                task_identity_prior,
                entities_by_clause: entities_by_clause.into_boxed_slice(),
                roles_by_clause: roles_by_clause.into_boxed_slice(),
                supported_kinds_by_clause: supported_kinds_by_clause.into_boxed_slice(),
                clauses_by_entity: clauses_by_entity
                    .into_iter()
                    .map(Vec::into_boxed_slice)
                    .collect::<Vec<_>>()
                    .into_boxed_slice(),
            },
        );
        Ok(())
    }

    pub fn prepared_task_count(&self) -> usize {
        self.prepared.len()
    }

    pub fn identity_probabilities_for_task(
        &mut self,
        task_id: &str,
        features: &crate::SemanticFeatures,
        clause: usize,
    ) -> Result<[f64; KIND_COUNT], TerminalError> {
        self.prepare_task(task_id, features)?;
        self.prepared
            .get(task_id)
            .and_then(|prepared| prepared.raw_probabilities.get(clause))
            .copied()
            .ok_or_else(|| TerminalError("identity clause index is out of range".into()))
    }

    pub fn incidence_conditioned_probabilities_for_task(
        &mut self,
        task_id: &str,
        features: &crate::SemanticFeatures,
        clause: usize,
    ) -> Result<[f64; KIND_COUNT], TerminalError> {
        self.prepare_task(task_id, features)?;
        self.prepared
            .get(task_id)
            .and_then(|prepared| prepared.conditioned_probabilities.get(clause))
            .copied()
            .ok_or_else(|| TerminalError("identity clause index is out of range".into()))
    }

    /// Return six-way softmax probabilities for one raw float32 clause vector.
    pub fn identity_probabilities(
        &self,
        raw_h: &[f32],
    ) -> Result<[f64; KIND_COUNT], TerminalError> {
        let logits = self.identity_logits(raw_h)?;
        softmax(&logits)
    }

    /// Evaluate the folded standardized six-way linear head on one raw H row.
    pub fn identity_logits(&self, raw_h: &[f32]) -> Result<[f64; KIND_COUNT], TerminalError> {
        if raw_h.len() != HIDDEN_DIM || raw_h.iter().any(|value| !value.is_finite()) {
            return Err(TerminalError(
                "identity input must be a finite 2048-value H row".into(),
            ));
        }
        let mut logits = [0.0f64; KIND_COUNT];
        for (kind, destination) in logits.iter_mut().enumerate() {
            let row = &self.weights[kind * HIDDEN_DIM..(kind + 1) * HIDDEN_DIM];
            let mut sum = f64::from(self.bias[kind]);
            for (&feature, &weight) in raw_h.iter().zip(row) {
                sum += f64::from(feature) * f64::from(weight);
            }
            *destination = sum;
        }
        Ok(logits)
    }

    /// Zero unsupported classes and renormalize over the public incidence
    /// shape, matching semantic-composition v03.
    pub fn incidence_conditioned_probabilities(
        probabilities: &[f64; KIND_COUNT],
        entities: &[usize],
        roles: &[usize],
    ) -> Result<([f64; KIND_COUNT], f64), TerminalError> {
        if probabilities
            .iter()
            .any(|probability| !probability.is_finite() || *probability < 0.0)
        {
            return Err(TerminalError(
                "identity probabilities must be finite and nonnegative".into(),
            ));
        }
        let supported = supported_kind_ids(entities, roles)?;
        let mass = supported
            .iter()
            .map(|&kind| probabilities[kind])
            .sum::<f64>();
        if !mass.is_finite() || mass <= 0.0 {
            return Err(TerminalError(
                "identity posterior has no mass on grounded kinds".into(),
            ));
        }
        let mut conditioned = [0.0; KIND_COUNT];
        for &kind in supported {
            conditioned[kind] = probabilities[kind] / mass;
        }
        Ok((conditioned, mass))
    }

    /// Compose clause identity probabilities with public incidence and a
    /// candidate assignment. Latent state and search budget are not inputs.
    pub fn score_raw(
        &self,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
    ) -> Result<TerminalPrediction, TerminalError> {
        validate_surface(features, assignment)?;
        let mut semantic_log_score = 0.0f64;
        for clause in 0..features.constraint_count {
            let entities = incidence_ids(
                &features.entity_incidence
                    [clause * features.entity_count..(clause + 1) * features.entity_count],
            )?;
            let roles = incidence_ids(
                &features.role_incidence
                    [clause * features.role_count..(clause + 1) * features.role_count],
            )?;
            let supported = supported_kind_ids(&entities, &roles)?;
            let raw_h =
                &features.constraint_embeddings[clause * HIDDEN_DIM..(clause + 1) * HIDDEN_DIM];
            let probabilities = self.identity_probabilities(raw_h)?;
            let supported_mass = supported
                .iter()
                .map(|&kind| probabilities[kind])
                .sum::<f64>();
            if !supported_mass.is_finite() || supported_mass <= 0.0 {
                return Err(TerminalError(format!(
                    "identity posterior has no mass on grounded kinds at clause {clause}"
                )));
            }
            let p_satisfied = supported
                .iter()
                .map(|&kind| {
                    probabilities[kind] / supported_mass
                        * satisfaction(kind, &entities, &roles, assignment)
                })
                .sum::<f64>();
            if !p_satisfied.is_finite() || !(0.0..=1.0).contains(&p_satisfied) {
                return Err(TerminalError(format!(
                    "invalid composed satisfaction probability at clause {clause}"
                )));
            }
            if p_satisfied == 0.0 {
                semantic_log_score = f64::NEG_INFINITY;
                break;
            }
            semantic_log_score += p_satisfied.ln();
        }
        let raw_probability = if semantic_log_score == f64::NEG_INFINITY {
            0.0
        } else {
            semantic_log_score.exp()
        };
        Ok(TerminalPrediction {
            semantic_log_score,
            raw_probability,
        })
    }

    pub fn score_raw_for_task(
        &mut self,
        task_id: &str,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
    ) -> Result<TerminalPrediction, TerminalError> {
        self.prepare_task(task_id, features)?;
        validate_surface(features, assignment)?;
        let prepared = self.prepared.get(task_id).expect("prepared above");
        let mut semantic_log_score = 0.0f64;
        for clause in 0..features.constraint_count {
            let entities = &prepared.entities_by_clause[clause];
            let roles = &prepared.roles_by_clause[clause];
            let probabilities = &prepared.conditioned_probabilities[clause];
            let p_satisfied = supported_kind_ids(entities, roles)?
                .iter()
                .map(|&kind| probabilities[kind] * satisfaction(kind, entities, roles, assignment))
                .sum::<f64>();
            if !p_satisfied.is_finite() || !(0.0..=1.0).contains(&p_satisfied) {
                return Err(TerminalError(format!(
                    "invalid composed satisfaction probability at clause {clause}"
                )));
            }
            if p_satisfied == 0.0 {
                semantic_log_score = f64::NEG_INFINITY;
                break;
            }
            semantic_log_score += p_satisfied.ln();
        }
        Ok(TerminalPrediction {
            semantic_log_score,
            raw_probability: if semantic_log_score == f64::NEG_INFINITY {
                0.0
            } else {
                semantic_log_score.exp()
            },
        })
    }

    /// Sum the frozen identity head's per-clause expected satisfaction under
    /// public incidence. This is an ordinal candidate-ranking signal, not a
    /// calibrated probability that the whole assignment is valid.
    pub fn expected_satisfied_clause_count_for_task(
        &mut self,
        task_id: &str,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
    ) -> Result<f64, TerminalError> {
        self.expected_satisfied_clause_count_with_task_prior_for_task(
            task_id, features, assignment, 0.0,
        )
    }

    /// Rank assignments using a blend of local clause identity and the
    /// task-pooled raw identity posterior. `pooled_weight` is a diagnostic
    /// engineering knob; this remains an ordinal score, not P(valid).
    pub fn expected_satisfied_clause_count_with_task_prior_for_task(
        &mut self,
        task_id: &str,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
        pooled_weight: f64,
    ) -> Result<f64, TerminalError> {
        if !pooled_weight.is_finite() || !(0.0..=1.0).contains(&pooled_weight) {
            return Err(TerminalError(
                "task-pooled identity weight must be between zero and one".into(),
            ));
        }
        self.prepare_task(task_id, features)?;
        validate_surface(features, assignment)?;
        let prepared = self.prepared.get(task_id).expect("prepared above");
        let mut expected_count = 0.0f64;
        for clause in 0..features.constraint_count {
            let entities = &prepared.entities_by_clause[clause];
            let roles = &prepared.roles_by_clause[clause];
            let probabilities = &prepared.conditioned_probabilities[clause];
            let supported = &prepared.supported_kinds_by_clause[clause];
            let prior_mass = supported
                .iter()
                .map(|&kind| prepared.task_identity_prior[usize::from(kind)])
                .sum::<f64>();
            if !prior_mass.is_finite() || prior_mass <= 0.0 {
                return Err(TerminalError(format!(
                    "task identity prior has no mass on grounded kinds at clause {clause}"
                )));
            }
            let p_satisfied = supported
                .iter()
                .map(|&kind| {
                    let kind = usize::from(kind);
                    let pooled = prepared.task_identity_prior[kind] / prior_mass;
                    ((1.0 - pooled_weight) * probabilities[kind] + pooled_weight * pooled)
                        * satisfaction(kind, entities, roles, assignment)
                })
                .sum::<f64>();
            if !p_satisfied.is_finite() || !(0.0..=1.0).contains(&p_satisfied) {
                return Err(TerminalError(format!(
                    "invalid composed satisfaction probability at clause {clause}"
                )));
            }
            expected_count += p_satisfied;
        }
        Ok(expected_count)
    }

    /// Exact action feature used by the frozen proposal-v02 training code:
    /// sum of per-affected-clause expected satisfaction change under the raw
    /// six-way identity posterior. Unsupported formulas contribute zero,
    /// matching `proposal/v02/train_pipeline.py::satisfied`.
    pub fn expected_satisfaction_delta_raw_v02(
        &self,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
        edit: crate::Edit,
    ) -> Result<f64, TerminalError> {
        validate_edit_surface(features, assignment, edit)?;
        let entity = usize::from(edit.entity);
        let mut total = 0.0f64;
        for clause in 0..features.constraint_count {
            if features.entity_incidence[clause * features.entity_count + entity] == 0 {
                continue;
            }
            let entities = incidence_ids(
                &features.entity_incidence
                    [clause * features.entity_count..(clause + 1) * features.entity_count],
            )?;
            let roles = incidence_ids(
                &features.role_incidence
                    [clause * features.role_count..(clause + 1) * features.role_count],
            )?;
            let raw_h =
                &features.constraint_embeddings[clause * HIDDEN_DIM..(clause + 1) * HIDDEN_DIM];
            let probabilities = self.identity_probabilities(raw_h)?;
            let mut after = assignment.to_vec();
            after[entity] = edit.new_role;
            for (kind, probability) in probabilities.iter().enumerate() {
                let delta = satisfaction_v02(kind, &entities, &roles, &after)
                    - satisfaction_v02(kind, &entities, &roles, assignment);
                total += probability * delta;
            }
        }
        if !total.is_finite() {
            return Err(TerminalError(
                "raw expected satisfaction delta is non-finite".into(),
            ));
        }
        Ok(total)
    }

    /// Proposal-v02 action adapter signal (raw six-way softmax semantics).
    pub fn expected_satisfaction_delta(
        &self,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
        edit: crate::Edit,
    ) -> Result<f64, TerminalError> {
        self.expected_satisfaction_delta_raw_v02(features, assignment, edit)
    }

    pub fn expected_satisfaction_delta_for_task(
        &mut self,
        task_id: &str,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
        edit: crate::Edit,
    ) -> Result<f64, TerminalError> {
        self.expected_satisfaction_deltas_for_task(task_id, features, assignment, &[edit], false)?
            .deltas
            .pop()
            .ok_or_else(|| TerminalError("single-edit delta result is empty".into()))
    }

    /// Incidence-conditioned alternative for action proposals. This uses the
    /// same per-clause supported-kind posterior as Q_terminal composition.
    pub fn expected_satisfaction_delta_incidence_masked(
        &self,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
        edit: crate::Edit,
    ) -> Result<f64, TerminalError> {
        validate_edit_surface(features, assignment, edit)?;
        let entity = usize::from(edit.entity);
        let mut total = 0.0f64;
        for clause in 0..features.constraint_count {
            if features.entity_incidence[clause * features.entity_count + entity] == 0 {
                continue;
            }
            let entities = incidence_ids(
                &features.entity_incidence
                    [clause * features.entity_count..(clause + 1) * features.entity_count],
            )?;
            let roles = incidence_ids(
                &features.role_incidence
                    [clause * features.role_count..(clause + 1) * features.role_count],
            )?;
            let raw_h =
                &features.constraint_embeddings[clause * HIDDEN_DIM..(clause + 1) * HIDDEN_DIM];
            let probabilities = self.identity_probabilities(raw_h)?;
            let (conditioned, _) =
                Self::incidence_conditioned_probabilities(&probabilities, &entities, &roles)?;
            let mut after = assignment.to_vec();
            after[entity] = edit.new_role;
            for &kind in supported_kind_ids(&entities, &roles)? {
                let delta = satisfaction(kind, &entities, &roles, &after)
                    - satisfaction(kind, &entities, &roles, assignment);
                total += conditioned[kind] * delta;
            }
        }
        if !total.is_finite() {
            return Err(TerminalError(
                "incidence-masked expected satisfaction delta is non-finite".into(),
            ));
        }
        Ok(total)
    }

    pub fn expected_satisfaction_delta_incidence_masked_for_task(
        &mut self,
        task_id: &str,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
        edit: crate::Edit,
    ) -> Result<f64, TerminalError> {
        self.expected_satisfaction_deltas_for_task(task_id, features, assignment, &[edit], true)?
            .deltas
            .pop()
            .ok_or_else(|| TerminalError("single-edit delta result is empty".into()))
    }

    /// Score all legal candidate edits against one prepared task view. The
    /// entity-to-clause CSR cache avoids rebuilding incidence vectors and
    /// rescanning every clause for every candidate.
    pub fn expected_satisfaction_deltas_for_task(
        &mut self,
        task_id: &str,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
        edits: &[crate::Edit],
        incidence_masked: bool,
    ) -> Result<ExpectedActionDeltaBatch, TerminalError> {
        self.prepare_task(task_id, features)?;
        validate_surface(features, assignment)?;
        let prepared = self.prepared.get(task_id).expect("prepared above");
        let mut deltas = Vec::with_capacity(edits.len());
        let mut affected_clause_counts = Vec::with_capacity(edits.len());
        for &edit in edits {
            validate_edit_only(features, assignment, edit)?;
            let affected_count = prepared.clauses_by_entity[usize::from(edit.entity)].len();
            deltas.push(expected_delta_prepared(
                assignment,
                edit,
                prepared,
                incidence_masked,
            )?);
            affected_clause_counts.push(affected_count as u32);
        }
        Ok(ExpectedActionDeltaBatch {
            deltas,
            affected_clause_counts,
        })
    }
}

/// Five-coefficient v06 train-only monotone logistic calibration.
#[derive(Clone, Debug, PartialEq)]
pub struct QTerminalCalibrationV06 {
    floor: f64,
    center: f64,
    scale: f64,
    slope: f64,
    intercept: f64,
    metadata_sha256: String,
    binary_sha256: String,
}

impl QTerminalCalibrationV06 {
    pub fn default_paths() -> (PathBuf, PathBuf) {
        let base = Path::new(
            r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v06",
        );
        (
            base.join("logistic-calibration-export.json"),
            base.join("logistic-calibration-f64le.bin"),
        )
    }

    pub fn load_default() -> Result<Self, TerminalError> {
        let (metadata, binary) = Self::default_paths();
        Self::load_from_paths(metadata, binary)
    }

    pub fn load_from_paths(
        metadata_path: impl AsRef<Path>,
        binary_path: impl AsRef<Path>,
    ) -> Result<Self, TerminalError> {
        let metadata_bytes = fs::read(metadata_path.as_ref()).map_err(|error| {
            TerminalError(format!(
                "read {}: {error}",
                metadata_path.as_ref().display()
            ))
        })?;
        let metadata_sha256 = sha256_hex(&metadata_bytes);
        if metadata_sha256 != Q_TERMINAL_V06_CALIBRATION_METADATA_SHA256 {
            return Err(TerminalError(format!(
                "Q_terminal calibration metadata hash mismatch: got {metadata_sha256}"
            )));
        }
        let metadata: CalibrationMetadata = serde_json::from_slice(&metadata_bytes)
            .map_err(|error| TerminalError(format!("parse Q_terminal calibration: {error}")))?;
        let expected_order = [
            "negative_infinity_floor",
            "training_score_center",
            "training_score_scale",
            "nonnegative_standardized_slope",
            "intercept",
        ];
        if metadata.schema != "R1_SEMANTIC_LOGISTIC_RUNTIME_EXPORT_V01"
            || metadata.dtype != "float64_le"
            || metadata.binary_file
                != binary_path
                    .as_ref()
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
            || metadata.binary_bytes != 40
            || metadata.coefficient_count != 5
            || metadata
                .coefficient_order
                .iter()
                .map(String::as_str)
                .ne(expected_order)
            || metadata.calibration_training_split != "train only"
            || metadata.validation_or_test_labels_used_for_fit
        {
            return Err(TerminalError(
                "Q_terminal calibration metadata schema differs from frozen v06".into(),
            ));
        }
        let binary = fs::read(binary_path.as_ref()).map_err(|error| {
            TerminalError(format!("read {}: {error}", binary_path.as_ref().display()))
        })?;
        let binary_sha256 = sha256_hex(&binary);
        if binary.len() != 40
            || binary_sha256 != Q_TERMINAL_V06_CALIBRATION_BINARY_SHA256
            || metadata.binary_sha256 != binary_sha256
        {
            return Err(TerminalError(format!(
                "Q_terminal calibration binary hash/length mismatch: got {binary_sha256}"
            )));
        }
        let mut coefficients = [0.0; 5];
        for (index, chunk) in binary.chunks_exact(8).enumerate() {
            coefficients[index] = f64::from_le_bytes([
                chunk[0], chunk[1], chunk[2], chunk[3], chunk[4], chunk[5], chunk[6], chunk[7],
            ]);
        }
        Self::from_coefficients(coefficients).map(|mut calibration| {
            calibration.metadata_sha256 = metadata_sha256;
            calibration.binary_sha256 = binary_sha256;
            calibration
        })
    }

    fn from_coefficients(coefficients: [f64; 5]) -> Result<Self, TerminalError> {
        let [floor, center, scale, slope, intercept] = coefficients;
        if coefficients.iter().any(|value| !value.is_finite()) || scale <= 0.0 || slope < 0.0 {
            return Err(TerminalError(
                "Q_terminal calibration coefficients are malformed".into(),
            ));
        }
        Ok(Self {
            floor,
            center,
            scale,
            slope,
            intercept,
            metadata_sha256: String::new(),
            binary_sha256: String::new(),
        })
    }

    pub fn metadata_sha256(&self) -> &str {
        &self.metadata_sha256
    }

    pub fn binary_sha256(&self) -> &str {
        &self.binary_sha256
    }

    pub fn probability(&self, semantic_log_score: f64) -> f64 {
        let score = if semantic_log_score == f64::NEG_INFINITY {
            self.floor
        } else {
            semantic_log_score
        };
        let logit = self.intercept + self.slope * ((score - self.center) / self.scale);
        stable_sigmoid(logit)
    }
}

/// A pinned v03 identity composition and pinned v06 train-only calibration.
pub struct CalibratedIdentityTerminalV06 {
    identity: IdentityCompositionV03,
    calibration: QTerminalCalibrationV06,
}

impl CalibratedIdentityTerminalV06 {
    pub fn load_default() -> Result<Self, TerminalError> {
        Ok(Self::new(
            IdentityCompositionV03::load_default()?,
            QTerminalCalibrationV06::load_default()?,
        ))
    }

    pub fn load_from_paths(
        identity_metadata_path: impl AsRef<Path>,
        identity_binary_path: impl AsRef<Path>,
        calibration_metadata_path: impl AsRef<Path>,
        calibration_binary_path: impl AsRef<Path>,
    ) -> Result<Self, TerminalError> {
        Ok(Self::new(
            IdentityCompositionV03::load_from_paths(identity_metadata_path, identity_binary_path)?,
            QTerminalCalibrationV06::load_from_paths(
                calibration_metadata_path,
                calibration_binary_path,
            )?,
        ))
    }

    fn new(identity: IdentityCompositionV03, calibration: QTerminalCalibrationV06) -> Self {
        Self {
            identity,
            calibration,
        }
    }

    pub fn score(
        &mut self,
        task_id: &str,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
    ) -> Result<(TerminalPrediction, f64), TerminalError> {
        let raw = self
            .identity
            .score_raw_for_task(task_id, features, assignment)?;
        Ok((raw, self.calibration.probability(raw.semantic_log_score)))
    }

    pub fn identity(&self) -> &IdentityCompositionV03 {
        &self.identity
    }

    pub fn calibration(&self) -> &QTerminalCalibrationV06 {
        &self.calibration
    }
}

impl TerminalScorer for CalibratedIdentityTerminalV06 {
    fn q_terminal(&mut self, input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError> {
        let (raw, probability) = self
            .score(input.task_id, input.features, input.assignment)
            .map_err(|error| PolicyError(error.to_string()))?;
        if !probability.is_finite() || !(0.0..=1.0).contains(&probability) {
            return Err(PolicyError(
                "calibrated Q_terminal is not a probability".into(),
            ));
        }
        Ok(PolicyValue {
            value: probability as f32,
            selection_score: Some(raw.semantic_log_score),
            costs: PolicyCosts {
                logits_scored: 6u64 * input.features.constraint_count as u64,
                ..PolicyCosts::default()
            },
        })
    }
}

/// Engineering selector v07: retain the frozen v06 validity probability,
/// while ranking visited assignments by a task-pooled identity composition.
pub struct TaskPooledIdentityTerminalV07 {
    identity: IdentityCompositionV03,
    calibration: QTerminalCalibrationV06,
}

impl TaskPooledIdentityTerminalV07 {
    pub fn load_default() -> Result<Self, TerminalError> {
        Ok(Self {
            identity: IdentityCompositionV03::load_default()?,
            calibration: QTerminalCalibrationV06::load_default()?,
        })
    }

    pub fn score(
        &mut self,
        task_id: &str,
        features: &crate::SemanticFeatures,
        assignment: &[u8],
    ) -> Result<(TerminalPrediction, f64, f64), TerminalError> {
        let raw = self
            .identity
            .score_raw_for_task(task_id, features, assignment)?;
        let probability = self.calibration.probability(raw.semantic_log_score);
        let ranking_score = self
            .identity
            .expected_satisfied_clause_count_with_task_prior_for_task(
                task_id,
                features,
                assignment,
                Q_TERMINAL_V07_TASK_POOLED_WEIGHT,
            )?;
        Ok((raw, probability, ranking_score))
    }
}

impl TerminalScorer for TaskPooledIdentityTerminalV07 {
    fn q_terminal(&mut self, input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError> {
        let (_raw, probability, ranking_score) = self
            .score(input.task_id, input.features, input.assignment)
            .map_err(|error| PolicyError(error.to_string()))?;
        if !probability.is_finite() || !(0.0..=1.0).contains(&probability) {
            return Err(PolicyError(
                "calibrated Q_terminal is not a probability".into(),
            ));
        }
        if !ranking_score.is_finite() {
            return Err(PolicyError(
                "task-pooled Q_terminal ranking score is not finite".into(),
            ));
        }
        Ok(PolicyValue {
            value: probability as f32,
            selection_score: Some(ranking_score),
            costs: PolicyCosts {
                logits_scored: 6u64 * input.features.constraint_count as u64,
                ..PolicyCosts::default()
            },
        })
    }
}

fn validate_metadata(metadata: &ExportMetadata, binary_path: &Path) -> Result<(), TerminalError> {
    if metadata.schema != "R1_IDENTITY_LINEAR_STANDARDIZED_F32LE_V01"
        || metadata.input_dim != HIDDEN_DIM
        || metadata.output_dim != KIND_COUNT
        || metadata.binary_file
            != binary_path
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
        || metadata.binary_bytes != BINARY_BYTES
        || metadata
            .kind_order
            .iter()
            .map(String::as_str)
            .ne(KIND_ORDER)
        || !metadata.parity_pass
    {
        return Err(TerminalError(
            "identity export metadata schema, dimensions, or class order differ".into(),
        ));
    }
    for (name, shape, offset, length) in [
        ("mean", vec![HIDDEN_DIM], 0, HIDDEN_DIM * 4),
        ("std", vec![HIDDEN_DIM], HIDDEN_DIM * 4, HIDDEN_DIM * 4),
        (
            "standardized_weight",
            vec![KIND_COUNT, HIDDEN_DIM],
            WEIGHTS_OFFSET,
            KIND_COUNT * HIDDEN_DIM * 4,
        ),
        (
            "standardized_bias",
            vec![KIND_COUNT],
            BIAS_OFFSET,
            KIND_COUNT * 4,
        ),
    ] {
        let field = metadata
            .fields
            .get(name)
            .ok_or_else(|| TerminalError(format!("identity metadata missing {name}")))?;
        if field.dtype != "float32_le"
            || field.shape != shape
            || field.byte_offset != offset
            || field.byte_length != length
        {
            return Err(TerminalError(format!(
                "identity metadata field {name} has an unexpected layout"
            )));
        }
    }
    Ok(())
}

fn validate_surface(
    features: &crate::SemanticFeatures,
    assignment: &[u8],
) -> Result<(), TerminalError> {
    validate_feature_surface(features)?;
    if assignment.len() != features.entity_count
        || assignment
            .iter()
            .any(|&role| usize::from(role) >= features.role_count)
    {
        return Err(TerminalError(
            "Q_terminal input dimensions or assignment are invalid".into(),
        ));
    }
    Ok(())
}

fn validate_feature_surface(features: &crate::SemanticFeatures) -> Result<(), TerminalError> {
    if features.hidden_dim != HIDDEN_DIM
        || features.constraint_embeddings.len() != features.constraint_count * HIDDEN_DIM
        || features.global_embedding.len() != HIDDEN_DIM
        || features.constraint_mask.len() != features.constraint_count
        || features.entity_incidence.len() != features.constraint_count * features.entity_count
        || features.role_incidence.len() != features.constraint_count * features.role_count
        || features.entity_mask.len() != features.entity_count
        || features.role_mask.len() != features.role_count
    {
        return Err(TerminalError(
            "Q_terminal input feature dimensions are invalid".into(),
        ));
    }
    if features.constraint_mask.iter().any(|&mask| mask != 1)
        || features.entity_mask.iter().any(|&mask| mask != 1)
        || features.role_mask.iter().any(|&mask| mask != 1)
        || features.entity_incidence.iter().any(|&value| value > 1)
        || features.role_incidence.iter().any(|&value| value > 1)
        || features
            .constraint_embeddings
            .iter()
            .chain(&features.global_embedding)
            .any(|value| !value.is_finite())
    {
        return Err(TerminalError(
            "Q_terminal requires finite embeddings and binary unpadded public masks".into(),
        ));
    }
    Ok(())
}

fn feature_token(features: &crate::SemanticFeatures) -> FeatureToken {
    FeatureToken {
        global_ptr: features.global_embedding.as_ptr() as usize,
        clauses_ptr: features.constraint_embeddings.as_ptr() as usize,
        entity_incidence_ptr: features.entity_incidence.as_ptr() as usize,
        role_incidence_ptr: features.role_incidence.as_ptr() as usize,
        constraint_mask_ptr: features.constraint_mask.as_ptr() as usize,
        entity_mask_ptr: features.entity_mask.as_ptr() as usize,
        role_mask_ptr: features.role_mask.as_ptr() as usize,
        hidden_dim: features.hidden_dim,
        constraint_count: features.constraint_count,
        entity_count: features.entity_count,
        role_count: features.role_count,
    }
}

fn expected_delta_prepared(
    assignment: &[u8],
    edit: crate::Edit,
    prepared: &PreparedTask,
    incidence_masked: bool,
) -> Result<f64, TerminalError> {
    let entity = usize::from(edit.entity);
    let mut total = 0.0f64;
    let affected_clauses = prepared
        .clauses_by_entity
        .get(entity)
        .ok_or_else(|| TerminalError("action entity index is out of range".into()))?;
    let probabilities_by_clause = if incidence_masked {
        &prepared.conditioned_probabilities
    } else {
        &prepared.raw_probabilities
    };
    for &clause in affected_clauses {
        let entities = prepared.entities_by_clause.get(clause).ok_or_else(|| {
            TerminalError("cached entity-incidence clause is out of range".into())
        })?;
        let roles = prepared
            .roles_by_clause
            .get(clause)
            .ok_or_else(|| TerminalError("cached role-incidence clause is out of range".into()))?;
        let probabilities = probabilities_by_clause
            .get(clause)
            .ok_or_else(|| TerminalError("cached clause posterior is out of range".into()))?;
        if incidence_masked {
            let supported = prepared
                .supported_kinds_by_clause
                .get(clause)
                .ok_or_else(|| {
                    TerminalError("cached support-kind clause is out of range".into())
                })?;
            for &kind in supported {
                let kind = usize::from(kind);
                let after = satisfaction_after_edit(kind, entities, roles, assignment, edit);
                let before = satisfaction(kind, entities, roles, assignment);
                total += probabilities[kind] * (after - before);
            }
        } else {
            for (kind, probability) in probabilities.iter().enumerate() {
                let after = satisfaction_v02_after_edit(kind, entities, roles, assignment, edit);
                let before = satisfaction_v02(kind, entities, roles, assignment);
                total += probability * (after - before);
            }
        }
    }
    if !total.is_finite() {
        return Err(TerminalError(
            "expected satisfaction delta is non-finite".into(),
        ));
    }
    Ok(total)
}

fn validate_edit_surface(
    features: &crate::SemanticFeatures,
    assignment: &[u8],
    edit: crate::Edit,
) -> Result<(), TerminalError> {
    validate_surface(features, assignment)?;
    validate_edit_only(features, assignment, edit)
}

fn validate_edit_only(
    features: &crate::SemanticFeatures,
    assignment: &[u8],
    edit: crate::Edit,
) -> Result<(), TerminalError> {
    let entity = usize::from(edit.entity);
    if entity >= features.entity_count
        || usize::from(edit.new_role) >= features.role_count
        || assignment[entity] == edit.new_role
    {
        return Err(TerminalError("proposal edit is not legal".into()));
    }
    Ok(())
}

fn role_after_edit(assignment: &[u8], entity: usize, edit: crate::Edit) -> u8 {
    if entity == usize::from(edit.entity) {
        edit.new_role
    } else {
        assignment[entity]
    }
}

fn satisfaction_after_edit(
    kind: usize,
    entities: &[usize],
    roles: &[usize],
    assignment: &[u8],
    edit: crate::Edit,
) -> f64 {
    match kind {
        0 => f64::from(
            role_after_edit(assignment, entities[0], edit)
                != role_after_edit(assignment, entities[1], edit),
        ),
        1 => f64::from(
            entities
                .iter()
                .filter(|&&entity| {
                    usize::from(role_after_edit(assignment, entity, edit)) == roles[0]
                })
                .count()
                == 1,
        ),
        2 => f64::from(usize::from(role_after_edit(assignment, entities[0], edit)) == roles[0]),
        3 => f64::from(usize::from(role_after_edit(assignment, entities[0], edit)) != roles[0]),
        4 if entities.len() == 1 && roles.len() == 2 => f64::from(
            roles[0] != roles[1]
                || usize::from(role_after_edit(assignment, entities[0], edit)) != roles[0],
        ),
        4 if entities.len() == 2 && roles.len() == 2 => {
            let first = usize::from(role_after_edit(assignment, entities[0], edit));
            let second = usize::from(role_after_edit(assignment, entities[1], edit));
            let direct = first != roles[0] || second != roles[1];
            let swapped = first != roles[1] || second != roles[0];
            f64::from(direct) * 0.5 + f64::from(swapped) * 0.5
        }
        5 => f64::from(
            role_after_edit(assignment, entities[0], edit)
                == role_after_edit(assignment, entities[1], edit),
        ),
        _ => unreachable!("supported kind/incidence pair was validated"),
    }
}

fn satisfaction_v02_after_edit(
    kind: usize,
    entities: &[usize],
    roles: &[usize],
    assignment: &[u8],
    edit: crate::Edit,
) -> f64 {
    match kind {
        0 | 5 => {
            if entities.len() != 2 {
                0.0
            } else {
                let equal = role_after_edit(assignment, entities[0], edit)
                    == role_after_edit(assignment, entities[1], edit);
                f64::from((kind == 5 && equal) || (kind == 0 && !equal))
            }
        }
        1 => f64::from(
            !entities.is_empty()
                && roles.len() == 1
                && entities
                    .iter()
                    .filter(|&&entity| {
                        usize::from(role_after_edit(assignment, entity, edit)) == roles[0]
                    })
                    .count()
                    == 1,
        ),
        2 | 3 => {
            if entities.len() != 1 || roles.len() != 1 {
                0.0
            } else {
                let equal = usize::from(role_after_edit(assignment, entities[0], edit)) == roles[0];
                f64::from((kind == 2 && equal) || (kind == 3 && !equal))
            }
        }
        4 => {
            if entities.len() == 1 && roles.len() == 2 && roles[0] != roles[1] {
                1.0
            } else if entities.len() != 2 || roles.len() != 2 {
                0.0
            } else {
                let first = usize::from(role_after_edit(assignment, entities[0], edit));
                let second = usize::from(role_after_edit(assignment, entities[1], edit));
                let direct = first != roles[0] || second != roles[1];
                let swapped = first != roles[1] || second != roles[0];
                (f64::from(direct) + f64::from(swapped)) * 0.5
            }
        }
        _ => 0.0,
    }
}

fn incidence_ids(row: &[u8]) -> Result<Vec<usize>, TerminalError> {
    if row.iter().any(|&value| value > 1) {
        return Err(TerminalError("public incidence must be binary".into()));
    }
    Ok(row
        .iter()
        .enumerate()
        .filter_map(|(index, &present)| (present == 1).then_some(index))
        .collect())
}

fn supported_kind_ids(
    entities: &[usize],
    roles: &[usize],
) -> Result<&'static [usize], TerminalError> {
    const DIFFERENT_SAME: &[usize] = &[0, 5];
    const EXACT_FIXED_FORBIDDEN: &[usize] = &[1, 2, 3];
    const EXACTLY_ONE: &[usize] = &[1];
    const IMPLIES: &[usize] = &[4];
    match (entities.len(), roles.len()) {
        (2, 0) => Ok(DIFFERENT_SAME),
        (1, 1) => Ok(EXACT_FIXED_FORBIDDEN),
        (n, 1) if n >= 2 => Ok(EXACTLY_ONE),
        (1, 2) => Ok(IMPLIES),
        shape => Err(TerminalError(format!(
            "public incidence shape {shape:?} grounds no supported clause kinds"
        ))),
    }
}

fn satisfaction(kind: usize, entities: &[usize], roles: &[usize], assignment: &[u8]) -> f64 {
    match kind {
        0 => f64::from(assignment[entities[0]] != assignment[entities[1]]),
        1 => f64::from(
            entities
                .iter()
                .filter(|&&entity| usize::from(assignment[entity]) == roles[0])
                .count()
                == 1,
        ),
        2 => f64::from(usize::from(assignment[entities[0]]) == roles[0]),
        3 => f64::from(usize::from(assignment[entities[0]]) != roles[0]),
        4 if entities.len() == 1 && roles.len() == 2 => {
            if roles[0] != roles[1] {
                1.0
            } else {
                f64::from(usize::from(assignment[entities[0]]) != roles[0])
            }
        }
        4 if entities.len() == 2 && roles.len() == 2 => {
            let first = assignment[entities[0]];
            let second = assignment[entities[1]];
            let direct = first != roles[0] as u8 || second != roles[1] as u8;
            let swapped = first != roles[1] as u8 || second != roles[0] as u8;
            f64::from(direct) * 0.5 + f64::from(swapped) * 0.5
        }
        5 => f64::from(assignment[entities[0]] == assignment[entities[1]]),
        _ => unreachable!("supported kind/incidence pair was validated"),
    }
}

/// Existing proposal-v02 feature semantics, including zero for a class whose
/// arguments are not present in the public incidence row.
fn satisfaction_v02(kind: usize, entities: &[usize], roles: &[usize], assignment: &[u8]) -> f64 {
    match kind {
        0 | 5 => {
            if entities.len() != 2 {
                0.0
            } else {
                let equal = assignment[entities[0]] == assignment[entities[1]];
                f64::from((kind == 5 && equal) || (kind == 0 && !equal))
            }
        }
        1 => f64::from(
            !entities.is_empty()
                && roles.len() == 1
                && entities
                    .iter()
                    .filter(|&&entity| usize::from(assignment[entity]) == roles[0])
                    .count()
                    == 1,
        ),
        2 | 3 => {
            if entities.len() != 1 || roles.len() != 1 {
                0.0
            } else {
                let equal = usize::from(assignment[entities[0]]) == roles[0];
                f64::from((kind == 2 && equal) || (kind == 3 && !equal))
            }
        }
        4 => {
            if entities.len() == 1 && roles.len() == 2 && roles[0] != roles[1] {
                1.0
            } else if entities.len() != 2 || roles.len() != 2 {
                0.0
            } else {
                let direct = usize::from(assignment[entities[0]]) != roles[0]
                    || usize::from(assignment[entities[1]]) != roles[1];
                let swapped = usize::from(assignment[entities[0]]) != roles[1]
                    || usize::from(assignment[entities[1]]) != roles[0];
                (f64::from(direct) + f64::from(swapped)) * 0.5
            }
        }
        _ => 0.0,
    }
}

fn softmax(logits: &[f64; KIND_COUNT]) -> Result<[f64; KIND_COUNT], TerminalError> {
    let max = logits.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    if !max.is_finite() {
        return Err(TerminalError("identity logits are non-finite".into()));
    }
    let mut probabilities = [0.0f64; KIND_COUNT];
    let mut total = 0.0;
    for (destination, &logit) in probabilities.iter_mut().zip(logits) {
        *destination = (logit - max).exp();
        total += *destination;
    }
    if !total.is_finite() || total <= 0.0 {
        return Err(TerminalError("identity softmax is not normalizable".into()));
    }
    for probability in &mut probabilities {
        *probability /= total;
    }
    Ok(probabilities)
}

fn read_f32_slice(bytes: &[u8], offset: usize, count: usize) -> Result<Vec<f32>, TerminalError> {
    let end = offset
        .checked_add(
            count
                .checked_mul(4)
                .ok_or_else(|| TerminalError("identity field byte length overflow".into()))?,
        )
        .ok_or_else(|| TerminalError("identity field offset overflow".into()))?;
    let field = bytes
        .get(offset..end)
        .ok_or_else(|| TerminalError("identity field lies outside binary".into()))?;
    Ok(field
        .chunks_exact(4)
        .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
        .collect())
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        write!(&mut output, "{byte:02x}").expect("write to string");
    }
    output
}

fn stable_sigmoid(value: f64) -> f64 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exp = value.exp();
        exp / (1.0 + exp)
    }
}
