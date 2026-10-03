//! Byte-pinned v02 proposal and corrected /64 V_reach inference.
//!
//! The proposal caller supplies one adapter `expected_delta` per candidate.
//! This module computes the pinned base MLP and adds the frozen adapter bias;
//! it does not derive semantic adapter probabilities or inspect private labels.

use crate::{Edit, SemanticFeatures};
use hashbrown::HashMap;
use r1_world::InferenceTask;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

pub const PROPOSAL_V02_SHA256: &str =
    "45960e4c62129998164ce6eaa20531ce8ea171bae962a979253b404d55f03ce0";
pub const V_REACH_V02_64_SHA256: &str =
    "0f08bf6c55142889e933fa15a82f6e1ff9bfc24365758667e88c19256da71fda";

pub const V_REACH_V03_SCALED_H_SHA256: &str =
    "48029538bc9ad40fcf049be0de013331cda5f399c702e94ccb4b592eb1611574";
pub const V_REACH_V05_STRESS_SHA256: &str =
    "f809e25c93ba8a99b769e3209d09294983089aadf601980425e89505ab8a85e6";
pub const V_REACH_V06_STRESS_SHA256: &str =
    "102b96ca8f2a9cd10d85c01a85c933ac03629d137e398cf92e91f8589d611056";

const HIDDEN_DIM: usize = 2048;
const LATENT_DIM: usize = 128;
const MAX_ENTITIES: usize = 20;
const MAX_ROLES: usize = 6;
const STATIC_DIM: usize = 8;
const PROPOSAL_INPUT: usize = 10;
const PROPOSAL_HIDDEN: usize = 16;
const VALUE_INPUT: usize = 4345;
const VALUE_HIDDEN: usize = 32;
const VALUE_BUDGET_MAX: u64 = 64;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InferenceV02Error(pub String);

impl std::fmt::Display for InferenceV02Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for InferenceV02Error {}

#[derive(Clone, Debug, Deserialize)]
struct ProposalWeightsV02 {
    schema: String,
    architecture: String,
    input_dim: usize,
    hidden_dim: usize,
    static_feature_dim: usize,
    feature_schema: String,
    adapter_logit_bias: f32,
    w1: Vec<Vec<f32>>,
    b1: Vec<f32>,
    w2: Vec<f32>,
    b2: f32,
}

#[derive(Clone, Debug, Deserialize)]
struct ValueWeightsV02 {
    schema: String,
    architecture: String,
    input_dim: usize,
    hidden_dim: usize,
    budget_normalization_max: u64,
    feature_schema: String,
    #[serde(default)]
    h_input_scale: Option<f32>,
    #[serde(default)]
    proposal_sha256: Option<String>,
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

/// Candidate logits and their decomposition for auditing the adapter term.
#[derive(Clone, Debug, PartialEq)]
pub struct ProposalScoresV02 {
    pub base_logits: Vec<f32>,
    pub adapter_adjustments: Vec<f32>,
    pub logits: Vec<f32>,
}

/// Versioned proposal mixtures for adaptive engineering sweeps. The pinned
/// v02 path remains the default and keeps its original raw-delta semantics.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ProposalMixV03 {
    PinnedRawV02,
    BaseOnlyV03,
    RawNormalizedV03 { spread_ratio: f32 },
    IncidenceMaskedV03,
    IncidenceMaskedNormalizedV03 { spread_ratio: f32 },
}

impl ProposalMixV03 {
    pub fn id(self) -> String {
        match self {
            Self::PinnedRawV02 => "pinned_raw_v02".to_owned(),
            Self::BaseOnlyV03 => "base_only_v03".to_owned(),
            Self::RawNormalizedV03 { spread_ratio } => {
                format!("raw_delta_norm_{spread_ratio}_v03")
            }
            Self::IncidenceMaskedV03 => "incidence_masked_v03".to_owned(),
            Self::IncidenceMaskedNormalizedV03 { spread_ratio } => {
                format!("incidence_masked_norm_{spread_ratio}_v03")
            }
        }
    }

    pub fn uses_action_signal(self) -> bool {
        !matches!(self, Self::BaseOnlyV03)
    }

    pub fn uses_incidence_masked_signal(self) -> bool {
        matches!(
            self,
            Self::IncidenceMaskedV03 | Self::IncidenceMaskedNormalizedV03 { .. }
        )
    }
}

/// Frozen v02 proposal and corrected V_reach heads with per-task feature cache.
pub struct FrozenProposalValueV02 {
    proposal: ProposalWeightsV02,
    value: ValueWeightsV02,
    proposal_sha256: String,
    value_sha256: String,
    value_h_scale: f32,
    value_budget_max: u64,
    cache: HashMap<String, PreparedTask>,
    value_buffer: Vec<f32>,
}

impl FrozenProposalValueV02 {
    /// Paths to the exact proposal-v02 and V64 refit files.
    pub fn default_paths() -> (PathBuf, PathBuf) {
        let root = Path::new(
            r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03",
        );
        (
            root.join("proposal-value-v02-attempt-03/proposal-weights-v02.json"),
            root.join(
                "proposal-value-v02-normalization-refit-v01/v-reach-weights-v02-normalization64.json",
            ),
        )
    }

    /// Load both checkpoints only when their exact bytes match the pins above.
    pub fn load_from_paths(
        proposal_path: impl AsRef<Path>,
        value_path: impl AsRef<Path>,
    ) -> Result<Self, InferenceV02Error> {
        Self::load_with_pins(
            proposal_path,
            PROPOSAL_V02_SHA256,
            value_path,
            V_REACH_V02_64_SHA256,
        )
    }

    /// Load explicitly supplied proposal and V_reach files after checking
    /// both caller-provided SHA-256 pins. The JSON schemas and tensor shapes
    /// remain validated exactly as on the legacy pinned path.
    pub fn load_explicit_heads(
        proposal_path: impl AsRef<Path>,
        expected_proposal_sha256: &str,
        value_path: impl AsRef<Path>,
        expected_value_sha256: &str,
    ) -> Result<Self, InferenceV02Error> {
        Self::load_with_pins(
            proposal_path,
            expected_proposal_sha256,
            value_path,
            expected_value_sha256,
        )
    }

    /// Load an explicitly supplied proposal with the legacy pinned /64 value
    /// head. This is useful for policy-only engineering versions that reuse
    /// the established continuation estimate.
    pub fn load_explicit_proposal_default(
        proposal_path: impl AsRef<Path>,
        expected_proposal_sha256: &str,
    ) -> Result<Self, InferenceV02Error> {
        let (_, value_path) = Self::default_paths();
        Self::load_with_pins(
            proposal_path,
            expected_proposal_sha256,
            value_path,
            V_REACH_V02_64_SHA256,
        )
    }

    /// Load an explicitly supplied proposal with the established scaled-H
    /// V_reach-v03 checkpoint.
    pub fn load_explicit_proposal_v03(
        proposal_path: impl AsRef<Path>,
        expected_proposal_sha256: &str,
    ) -> Result<Self, InferenceV02Error> {
        let value_path = Path::new(
            r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v19-vreach-scale-v03\v-reach-weights-v03.json",
        );
        Self::load_with_pins(
            proposal_path,
            expected_proposal_sha256,
            value_path,
            V_REACH_V03_SCALED_H_SHA256,
        )
    }

    /// Load an explicitly supplied proposal with the established 256-step
    /// stress V_reach-v05 checkpoint.
    pub fn load_explicit_proposal_v05(
        proposal_path: impl AsRef<Path>,
        expected_proposal_sha256: &str,
    ) -> Result<Self, InferenceV02Error> {
        let value_path = Path::new(
            r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v27-vreach-stress-fit-v05\v-reach-weights-v05.json",
        );
        Self::load_with_pins(
            proposal_path,
            expected_proposal_sha256,
            value_path,
            V_REACH_V05_STRESS_SHA256,
        )
    }

    /// Load an explicitly supplied proposal with the established 256-step
    /// neighborhood-start stress V_reach-v06 checkpoint.
    pub fn load_explicit_proposal_v06(
        proposal_path: impl AsRef<Path>,
        expected_proposal_sha256: &str,
    ) -> Result<Self, InferenceV02Error> {
        let value_path = Path::new(
            r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v36-vreach-stress-fit-v06\v-reach-weights-v06.json",
        );
        Self::load_with_pins(
            proposal_path,
            expected_proposal_sha256,
            value_path,
            V_REACH_V06_STRESS_SHA256,
        )
    }

    /// Load the legacy pinned proposal with a caller-pinned V_reach file.
    pub fn load_explicit_value(
        value_path: impl AsRef<Path>,
        expected_value_sha256: &str,
    ) -> Result<Self, InferenceV02Error> {
        let (proposal_path, _) = Self::default_paths();
        Self::load_with_pins(
            proposal_path,
            PROPOSAL_V02_SHA256,
            value_path,
            expected_value_sha256,
        )
    }

    /// Load the pinned v02 proposal with the engineering v03 scaled-H value
    /// checkpoint. The input scale is read from and validated against the
    /// checkpoint schema, then applied to both semantic embedding blocks.
    pub fn load_default_v03() -> Result<Self, InferenceV02Error> {
        let (proposal_path, _) = Self::default_paths();
        let value_path = Path::new(
            r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v19-vreach-scale-v03\v-reach-weights-v03.json",
        );
        Self::load_with_pins(
            proposal_path,
            PROPOSAL_V02_SHA256,
            value_path,
            V_REACH_V03_SCALED_H_SHA256,
        )
    }

    /// Load the stress-domain v05 value head trained through a 256-step horizon.
    pub fn load_default_v05() -> Result<Self, InferenceV02Error> {
        let (proposal_path, _) = Self::default_paths();
        let value_path = Path::new(
            r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v27-vreach-stress-fit-v05\v-reach-weights-v05.json",
        );
        Self::load_with_pins(
            proposal_path,
            PROPOSAL_V02_SHA256,
            value_path,
            V_REACH_V05_STRESS_SHA256,
        )
    }

    /// Load the v06 value head trained with explicit solution-neighborhood starts.
    pub fn load_default_v06() -> Result<Self, InferenceV02Error> {
        let (proposal_path, _) = Self::default_paths();
        let value_path = Path::new(
            r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v36-vreach-stress-fit-v06\v-reach-weights-v06.json",
        );
        Self::load_with_pins(
            proposal_path,
            PROPOSAL_V02_SHA256,
            value_path,
            V_REACH_V06_STRESS_SHA256,
        )
    }

    fn load_with_pins(
        proposal_path: impl AsRef<Path>,
        expected_proposal_sha256: &str,
        value_path: impl AsRef<Path>,
        expected_value_sha256: &str,
    ) -> Result<Self, InferenceV02Error> {
        let (proposal, proposal_sha256) =
            read_pinned::<ProposalWeightsV02>(proposal_path, expected_proposal_sha256)?;
        let (value, value_sha256) =
            read_pinned::<ValueWeightsV02>(value_path, expected_value_sha256)?;
        validate_proposal(&proposal)?;
        let (value_h_scale, value_budget_max) = validate_value(&value, &proposal_sha256)?;
        Ok(Self {
            proposal,
            value,
            proposal_sha256,
            value_sha256,
            value_h_scale,
            value_budget_max,
            cache: HashMap::new(),
            value_buffer: vec![0.0; VALUE_INPUT],
        })
    }

    pub fn load_default() -> Result<Self, InferenceV02Error> {
        let (proposal, value) = Self::default_paths();
        Self::load_from_paths(proposal, value)
    }

    pub fn proposal_sha256(&self) -> &str {
        &self.proposal_sha256
    }

    pub fn adapter_logit_bias(&self) -> f32 {
        self.proposal.adapter_logit_bias
    }

    pub fn value_sha256(&self) -> &str {
        &self.value_sha256
    }

    pub fn value_budget_max(&self) -> u64 {
        self.value_budget_max
    }

    pub fn cache_len(&self) -> usize {
        self.cache.len()
    }

    pub fn clear_cache(&mut self) {
        self.cache.clear();
    }

    /// Prepare cached H-only candidate features and the row-wise mean of H.
    /// Refresh by calling explicitly again after replacing feature storage.
    pub fn prepare_task(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
    ) -> Result<(), InferenceV02Error> {
        features
            .validate_for(task)
            .map_err(|error| InferenceV02Error(error.to_string()))?;
        validate_dimensions(task, features)?;
        validate_finite_features(features)?;
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

    /// Score candidates in caller order using `base_mlp + bias * expected_delta`.
    pub fn score_edits(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
        assignment: &[u8],
        candidates: &[Edit],
        expected_delta: &[f32],
    ) -> Result<Vec<f32>, InferenceV02Error> {
        Ok(self
            .score_edits_detailed(task, features, assignment, candidates, expected_delta)?
            .logits)
    }

    /// Return base logits, adapter adjustments, and the combined logits.
    pub fn score_edits_detailed(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
        assignment: &[u8],
        candidates: &[Edit],
        expected_delta: &[f32],
    ) -> Result<ProposalScoresV02, InferenceV02Error> {
        self.score_edits_detailed_with_mix(
            task,
            features,
            assignment,
            candidates,
            expected_delta,
            ProposalMixV03::PinnedRawV02,
        )
    }

    /// Score candidates under a named v03 engineering mixture while keeping
    /// all learned head bytes pinned to proposal-v02.
    pub fn score_edits_detailed_with_mix(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
        assignment: &[u8],
        candidates: &[Edit],
        expected_delta: &[f32],
        mix: ProposalMixV03,
    ) -> Result<ProposalScoresV02, InferenceV02Error> {
        self.ensure_prepared(task, features)?;
        validate_assignment(task, assignment)?;
        if expected_delta.len() != candidates.len() {
            return Err(InferenceV02Error(
                "expected_delta length must match candidate count".into(),
            ));
        }
        if expected_delta.iter().any(|value| !value.is_finite()) {
            return Err(InferenceV02Error(
                "expected_delta contains a non-finite value".into(),
            ));
        }
        let cached = self
            .cache
            .get(&task.id)
            .expect("prepare called before this access");
        let mut role_loads = [0u32; MAX_ROLES];
        for &role in assignment {
            role_loads[usize::from(role)] += 1;
        }
        let n = assignment.len() as f32;
        validate_mix(mix)?;
        let mut base_logits = Vec::with_capacity(candidates.len());
        let mut input = [0.0f32; PROPOSAL_INPUT];
        for &edit in candidates {
            let entity = usize::from(edit.entity);
            let role = usize::from(edit.new_role);
            if entity >= usize::from(task.n)
                || role >= usize::from(task.k)
                || assignment[entity] == edit.new_role
            {
                return Err(InferenceV02Error(
                    "candidate edit is illegal for the assignment".into(),
                ));
            }
            let row = &cached.static_features[entity * usize::from(task.k) + role];
            input[..STATIC_DIM].copy_from_slice(row);
            input[STATIC_DIM] = role_loads[usize::from(assignment[entity])] as f32 / n;
            input[STATIC_DIM + 1] = role_loads[role] as f32 / n;
            base_logits.push(score_proposal(&self.proposal, &input));
        }
        let adapter_adjustments = proposal_adjustments(
            &base_logits,
            expected_delta,
            self.proposal.adapter_logit_bias,
            mix,
        );
        let logits = base_logits
            .iter()
            .zip(&adapter_adjustments)
            .map(|(base, adjustment)| base + adjustment)
            .collect();
        Ok(ProposalScoresV02 {
            base_logits,
            adapter_adjustments,
            logits,
        })
    }

    /// Evaluate sigmoid(V_reach) with the pinned /64 budget feature.
    pub fn v_reach(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
        assignment: &[u8],
        latent_state: &[f32],
        remaining_budget: u64,
    ) -> Result<f32, InferenceV02Error> {
        self.ensure_prepared(task, features)?;
        validate_assignment(task, assignment)?;
        if latent_state.len() != LATENT_DIM {
            return Err(InferenceV02Error(format!(
                "v02 V_reach expects {LATENT_DIM} latent values"
            )));
        }
        if latent_state.iter().any(|value| !value.is_finite()) {
            return Err(InferenceV02Error(
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
        if self.value_h_scale != 1.0 {
            for value in &mut self.value_buffer[..HIDDEN_DIM * 2] {
                *value *= self.value_h_scale;
            }
        }
        let assignment_start = HIDDEN_DIM * 2;
        for (entity, &role) in assignment.iter().enumerate() {
            self.value_buffer[assignment_start + entity * MAX_ROLES + usize::from(role)] = 1.0;
        }
        let latent_start = assignment_start + MAX_ENTITIES * MAX_ROLES;
        self.value_buffer[latent_start..latent_start + LATENT_DIM].copy_from_slice(latent_state);
        self.value_buffer[VALUE_INPUT - 1] = (remaining_budget.min(self.value_budget_max) as f64
            / self.value_budget_max as f64) as f32;
        Ok(score_value(&self.value, &self.value_buffer))
    }

    fn ensure_prepared(
        &mut self,
        task: &InferenceTask,
        features: &SemanticFeatures,
    ) -> Result<(), InferenceV02Error> {
        let token = feature_token(features);
        if self
            .cache
            .get(&task.id)
            .is_none_or(|prepared| prepared.token != token)
        {
            self.prepare_task(task, features)?;
        }
        Ok(())
    }
}

fn read_pinned<T: for<'de> Deserialize<'de>>(
    path: impl AsRef<Path>,
    expected_sha256: &str,
) -> Result<(T, String), InferenceV02Error> {
    let bytes = fs::read(path.as_ref())
        .map_err(|error| InferenceV02Error(format!("read {}: {error}", path.as_ref().display())))?;
    let digest = hex_digest(&Sha256::digest(&bytes));
    if digest != expected_sha256 {
        return Err(InferenceV02Error(format!(
            "weight hash mismatch for {}: got {digest}, expected {expected_sha256}",
            path.as_ref().display()
        )));
    }
    let parsed = serde_json::from_slice(&bytes).map_err(|error| {
        InferenceV02Error(format!("parse {}: {error}", path.as_ref().display()))
    })?;
    Ok((parsed, digest))
}

fn validate_proposal(weights: &ProposalWeightsV02) -> Result<(), InferenceV02Error> {
    if weights.schema != "r1-proposal-weights-v02"
        || weights.architecture != "tanh_mlp_base_f10_h16_plus_adapter_bias_v02"
        || weights.feature_schema
            != "r1-candidate-features-h-global-entity-role-load-v01-plus-semantic-adapter-expected-delta-v02"
        || weights.input_dim != PROPOSAL_INPUT
        || weights.hidden_dim != PROPOSAL_HIDDEN
        || weights.static_feature_dim != STATIC_DIM
        || weights.w1.len() != PROPOSAL_HIDDEN
        || weights.w1.iter().any(|row| row.len() != PROPOSAL_INPUT)
        || weights.b1.len() != PROPOSAL_HIDDEN
        || weights.w2.len() != PROPOSAL_HIDDEN
    {
        return Err(InferenceV02Error(
            "unsupported proposal-v02 weight schema or shape".into(),
        ));
    }
    let finite = weights
        .w1
        .iter()
        .flatten()
        .chain(&weights.b1)
        .chain(&weights.w2)
        .chain(std::iter::once(&weights.b2))
        .chain(std::iter::once(&weights.adapter_logit_bias))
        .all(|value| value.is_finite());
    if !finite {
        return Err(InferenceV02Error(
            "proposal-v02 weights contain non-finite values".into(),
        ));
    }
    Ok(())
}

fn validate_mix(mix: ProposalMixV03) -> Result<(), InferenceV02Error> {
    let ratio = match mix {
        ProposalMixV03::RawNormalizedV03 { spread_ratio }
        | ProposalMixV03::IncidenceMaskedNormalizedV03 { spread_ratio } => Some(spread_ratio),
        _ => None,
    };
    if ratio.is_some_and(|value| !value.is_finite() || value < 0.0) {
        return Err(InferenceV02Error(
            "normalized adapter spread ratio must be finite and nonnegative".into(),
        ));
    }
    Ok(())
}

fn proposal_adjustments(
    base_logits: &[f32],
    expected_delta: &[f32],
    pinned_bias: f32,
    mix: ProposalMixV03,
) -> Vec<f32> {
    match mix {
        ProposalMixV03::PinnedRawV02 | ProposalMixV03::IncidenceMaskedV03 => expected_delta
            .iter()
            .map(|delta| pinned_bias * delta)
            .collect(),
        ProposalMixV03::BaseOnlyV03 => vec![0.0; expected_delta.len()],
        ProposalMixV03::RawNormalizedV03 { spread_ratio }
        | ProposalMixV03::IncidenceMaskedNormalizedV03 { spread_ratio } => {
            let (delta_mean, delta_sd) = mean_std(expected_delta);
            let (_, base_sd) = mean_std(base_logits);
            if delta_sd <= 1e-8 || base_sd <= 1e-8 || spread_ratio == 0.0 {
                return vec![0.0; expected_delta.len()];
            }
            expected_delta
                .iter()
                .map(|delta| ((delta - delta_mean) / delta_sd) * base_sd * spread_ratio)
                .collect()
        }
    }
}

fn mean_std(values: &[f32]) -> (f32, f32) {
    if values.is_empty() {
        return (0.0, 0.0);
    }
    let mean = values.iter().map(|value| f64::from(*value)).sum::<f64>() / values.len() as f64;
    let variance = values
        .iter()
        .map(|value| {
            let difference = f64::from(*value) - mean;
            difference * difference
        })
        .sum::<f64>()
        / values.len() as f64;
    (mean as f32, variance.sqrt() as f32)
}

fn validate_value(
    weights: &ValueWeightsV02,
    proposal_sha256: &str,
) -> Result<(f32, u64), InferenceV02Error> {
    let (h_scale, expected_budget_max) = match (
        weights.schema.as_str(),
        weights.architecture.as_str(),
        weights.feature_schema.as_str(),
        weights.h_input_scale,
    ) {
        (
            "r1-v-reach-weights-v02",
            "tanh_mlp_value_4345_h32_v02",
            "r1-value-input-h-global-meanH-assignment-latent-budget-v01",
            None,
        ) => (1.0, VALUE_BUDGET_MAX),
        (
            "r1-v-reach-weights-v03",
            "tanh_mlp_value_4345_h32_v03_scaled_h_groups",
            "r1-value-input-h-global-meanH-assignment-latent-budget-v02",
            Some(scale),
        ) if scale.is_finite() && scale > 0.0 && scale <= 1.0 => (scale, VALUE_BUDGET_MAX),
        (
            "r1-v-reach-weights-v05",
            "tanh_mlp_value_4345_h32_v05_stress_scaled_h_groups_budget256",
            "r1-value-input-h-global-meanH-assignment-latent-budget-v02",
            Some(scale),
        ) if scale.is_finite() && scale > 0.0 && scale <= 1.0 => (scale, 256),
        (
            "r1-v-reach-weights-v06",
            "tanh_mlp_value_4345_h32_v06_stress_scaled_h_groups_budget256",
            "r1-value-input-h-global-meanH-assignment-latent-budget-v02",
            Some(scale),
        ) if scale.is_finite() && scale > 0.0 && scale <= 1.0 => (scale, 256),
        (
            "r1-v-reach-weights-v07",
            "tanh_mlp_value_4345_h32_v07_stress_v04_scaled_h_groups_budget256",
            "r1-value-input-h-global-meanH-assignment-latent-budget-v02",
            Some(scale),
        ) if scale.is_finite() && scale > 0.0 && scale <= 1.0 => (scale, 256),
        _ => {
            return Err(InferenceV02Error(
                "unsupported V_reach schema or H input transform".into(),
            ));
        }
    };
    if weights.input_dim != VALUE_INPUT
        || weights.hidden_dim != VALUE_HIDDEN
        || weights.budget_normalization_max != expected_budget_max
        || weights.w1.len() != VALUE_HIDDEN
        || weights.w1.iter().any(|row| row.len() != VALUE_INPUT)
        || weights.b1.len() != VALUE_HIDDEN
        || weights.w2.len() != VALUE_HIDDEN
    {
        return Err(InferenceV02Error(
            "unsupported V_reach-v02 /64 weight schema or shape".into(),
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
        return Err(InferenceV02Error(
            "V_reach weights contain non-finite values".into(),
        ));
    }
    if weights.schema == "r1-v-reach-weights-v07"
        && weights.proposal_sha256.as_deref() != Some(proposal_sha256)
    {
        return Err(InferenceV02Error(
            "V_reach-v07 proposal SHA256 does not match the loaded proposal".into(),
        ));
    }
    Ok((h_scale, expected_budget_max))
}

fn validate_dimensions(
    task: &InferenceTask,
    features: &SemanticFeatures,
) -> Result<(), InferenceV02Error> {
    if features.hidden_dim != HIDDEN_DIM
        || usize::from(task.n) == 0
        || usize::from(task.n) > MAX_ENTITIES
        || !(2..=MAX_ROLES).contains(&usize::from(task.k))
    {
        return Err(InferenceV02Error(format!(
            "v02 heads require hidden_dim={HIDDEN_DIM}, 1<=n<=20, and 2<=k<=6"
        )));
    }
    Ok(())
}

fn validate_finite_features(features: &SemanticFeatures) -> Result<(), InferenceV02Error> {
    if features
        .constraint_embeddings
        .iter()
        .chain(features.global_embedding.iter())
        .any(|value| !value.is_finite())
    {
        return Err(InferenceV02Error(
            "semantic features contain a non-finite value".into(),
        ));
    }
    Ok(())
}

fn validate_assignment(task: &InferenceTask, assignment: &[u8]) -> Result<(), InferenceV02Error> {
    if assignment.len() != usize::from(task.n) || assignment.iter().any(|role| *role >= task.k) {
        return Err(InferenceV02Error(
            "assignment shape or role ID is invalid".into(),
        ));
    }
    Ok(())
}

fn validate_public_incidence(
    task: &InferenceTask,
    features: &SemanticFeatures,
) -> Result<(), InferenceV02Error> {
    let n = usize::from(task.n);
    let k = usize::from(task.k);
    for clause in 0..features.constraint_count {
        for entity in 0..n {
            let expected = u8::from(task.entity_mentions[clause].contains(&(entity as u16)));
            if features.entity_incidence[clause * n + entity] != expected {
                return Err(InferenceV02Error(
                    "entity incidence differs from public projection".into(),
                ));
            }
        }
        for role in 0..k {
            let expected = u8::from(task.role_mentions[clause].contains(&(role as u8)));
            if features.role_incidence[clause * k + role] != expected {
                return Err(InferenceV02Error(
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
) -> Result<Vec<[f32; STATIC_DIM]>, InferenceV02Error> {
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
                return Err(InferenceV02Error(
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

fn score_proposal(weights: &ProposalWeightsV02, input: &[f32; PROPOSAL_INPUT]) -> f32 {
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

fn score_value(weights: &ValueWeightsV02, input: &[f32]) -> f32 {
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
