use hashbrown::HashSet;
use r1_world::{validate, InferenceTask, Task};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fmt;

/// Sensor outputs available to the frozen proposal and value heads. This is
/// supplied by the separately qualified sensor lane; this crate never runs an
/// encoder or constructs these vectors.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PublicFeatures {
    /// SHA-256 of the frozen sensor extraction receipt that covers these rows.
    pub sensor_artifact_sha256: String,
    pub global_embedding: Vec<f32>,
    /// One vector per rendered clause, in the same order as InferenceTask.
    pub clause_embeddings: Vec<Vec<f32>>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct IndividualState {
    pub state_id: String,
    pub assignment: Vec<u8>,
    pub latent_state: Vec<f32>,
    pub remaining_budget: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct ProposalActionProbability {
    pub entity: u16,
    pub new_role: u8,
    pub probability: f64,
}

/// Read-only public view presented to a frozen proposal. It cannot access the
/// private Task AST, exact solutions, teacher labels, or validator results.
pub struct ProposalContext<'a> {
    pub inference: &'a InferenceTask,
    pub features: &'a PublicFeatures,
    pub assignment: &'a [u8],
    pub latent_state: &'a [f32],
}

/// Adapter for the already-frozen proposal model. Implementations provide a
/// content digest and deterministic latent transition; no fitting API exists
/// in this crate. The callback sees only public text/features and state.
pub trait FrozenProposal {
    fn snapshot_sha256(&self) -> [u8; 32];

    fn action_distribution(
        &self,
        context: &ProposalContext<'_>,
        remaining_budget: u32,
    ) -> Result<Vec<ProposalActionProbability>, String>;

    fn advance_latent(
        &self,
        context: &ProposalContext<'_>,
        entity: u16,
        new_role: u8,
    ) -> Result<Vec<f32>, String>;
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RolloutLabel {
    pub rollout_index: u32,
    pub seed: u64,
    pub rng_state_end: u64,
    pub proposal_sha256: String,
    pub transitions: u32,
    /// Includes the supplied initial assignment. The rollout still consumes
    /// its full budget after a hit; the private label never stops the policy.
    pub success_within_budget: bool,
    pub first_hit_step: Option<u32>,
    pub final_assignment: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ReachabilityLabel {
    pub schema: String,
    pub task_id: String,
    pub task_sha256: String,
    pub state_id: String,
    pub assignment: Vec<u8>,
    pub latent_state: Vec<f32>,
    pub remaining_budget: u32,
    pub sensor_artifact_sha256: String,
    pub proposal_sha256: String,
    pub rollouts: Vec<RolloutLabel>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LabelDataset {
    pub schema: String,
    pub task_id: String,
    pub task_sha256: String,
    pub sensor_artifact_sha256: String,
    pub proposal_sha256: String,
    pub base_seed: u64,
    pub rollouts_per_state: u32,
    pub states: Vec<ReachabilityLabel>,
}

/// Build individual-state Monte Carlo labels for
/// `V_reach(a,s,H,b) = P(hit within b | fixed proposal)`. Each rollout starts
/// from the same state with a derived seed, takes exactly `b` transitions,
/// and receives no validator signal. There is no particle resampling.
pub fn build_reachability_dataset<P: FrozenProposal>(
    task: &Task,
    inference: &InferenceTask,
    features: &PublicFeatures,
    states: &[IndividualState],
    base_seed: u64,
    rollouts_per_state: u32,
    proposal: &P,
) -> Result<LabelDataset, RolloutError> {
    validate_public_pair(task, inference, features)?;
    if states.is_empty() {
        return Err(RolloutError::NoStates);
    }
    if rollouts_per_state == 0 {
        return Err(RolloutError::NoRollouts);
    }
    let proposal_digest = proposal.snapshot_sha256();
    let proposal_sha256 = hex_digest(proposal_digest);
    let task_sha256 = task_digest(task)?;
    let rollout_builder = RolloutBuilder {
        task,
        inference,
        features,
        proposal,
        expected_digest: proposal_digest,
    };
    let mut labels = Vec::with_capacity(states.len());
    let mut state_ids = HashSet::with_capacity(states.len());
    for state in states {
        validate_state(task, state)?;
        if !state_ids.insert(state.state_id.as_str()) {
            return Err(RolloutError::DuplicateStateId(state.state_id.clone()));
        }
        let mut rollouts = Vec::with_capacity(rollouts_per_state as usize);
        for rollout_index in 0..rollouts_per_state {
            let seed = derive_seed(base_seed, &state.state_id, rollout_index);
            let rollout = rollout_builder.run(state, rollout_index, seed)?;
            rollouts.push(rollout);
        }
        labels.push(ReachabilityLabel {
            schema: "r1-v-reach-rollout-label-v01".to_owned(),
            task_id: task.id.clone(),
            task_sha256: task_sha256.clone(),
            state_id: state.state_id.clone(),
            assignment: state.assignment.clone(),
            latent_state: state.latent_state.clone(),
            remaining_budget: state.remaining_budget,
            sensor_artifact_sha256: features.sensor_artifact_sha256.clone(),
            proposal_sha256: proposal_sha256.clone(),
            rollouts,
        });
    }
    if proposal.snapshot_sha256() != proposal_digest {
        return Err(RolloutError::ProposalChangedDuringDataset);
    }
    Ok(LabelDataset {
        schema: "r1-v-reach-label-dataset-v01".to_owned(),
        task_id: task.id.clone(),
        task_sha256,
        sensor_artifact_sha256: features.sensor_artifact_sha256.clone(),
        proposal_sha256,
        base_seed,
        rollouts_per_state,
        states: labels,
    })
}

struct RolloutBuilder<'a, P> {
    task: &'a Task,
    inference: &'a InferenceTask,
    features: &'a PublicFeatures,
    proposal: &'a P,
    expected_digest: [u8; 32],
}

impl<P: FrozenProposal> RolloutBuilder<'_, P> {
    fn run(
        &self,
        state: &IndividualState,
        rollout_index: u32,
        seed: u64,
    ) -> Result<RolloutLabel, RolloutError> {
        let task = self.task;
        let inference = self.inference;
        let features = self.features;
        let proposal = self.proposal;
        let expected_digest = self.expected_digest;
        let mut assignment = state.assignment.clone();
        let mut latent = state.latent_state.clone();
        let mut rng = StableRng::new(seed);
        let mut trajectory = Vec::with_capacity(state.remaining_budget as usize + 1);
        trajectory.push(assignment.clone());

        for step in 1..=state.remaining_budget {
            ensure_snapshot(proposal, expected_digest)?;
            let context = ProposalContext {
                inference,
                features,
                assignment: &assignment,
                latent_state: &latent,
            };
            let distribution = proposal
                .action_distribution(&context, state.remaining_budget - step + 1)
                .map_err(RolloutError::Proposal)?;
            ensure_snapshot(proposal, expected_digest)?;
            let selected = sample_action(&distribution, inference, &assignment, &mut rng)?;
            let next_latent = proposal
                .advance_latent(&context, selected.entity, selected.new_role)
                .map_err(RolloutError::Proposal)?;
            ensure_snapshot(proposal, expected_digest)?;
            if next_latent.iter().any(|value| !value.is_finite()) {
                return Err(RolloutError::NonFiniteLatent);
            }
            assignment[usize::from(selected.entity)] = selected.new_role;
            latent = next_latent;
            trajectory.push(assignment.clone());
        }
        let rng_state_end = rng.state;
        ensure_snapshot(proposal, expected_digest)?;
        // Close the public-policy rollout before touching the private validator.
        // This keeps validity labels post-hoc, with no opportunity for even timing
        // or callback sequencing to steer later proposal transitions.
        let first_hit_step = trajectory
            .iter()
            .position(|candidate| validate(task, candidate))
            .map(|step| step as u32);
        Ok(RolloutLabel {
            rollout_index,
            seed,
            rng_state_end,
            proposal_sha256: hex_digest(expected_digest),
            transitions: state.remaining_budget,
            success_within_budget: first_hit_step.is_some(),
            first_hit_step,
            final_assignment: trajectory
                .last()
                .cloned()
                .ok_or(RolloutError::EmptyTrajectory)?,
        })
    }
}

fn sample_action(
    distribution: &[ProposalActionProbability],
    inference: &InferenceTask,
    assignment: &[u8],
    rng: &mut StableRng,
) -> Result<ProposalActionProbability, RolloutError> {
    if distribution.is_empty() {
        return Err(RolloutError::EmptyDistribution);
    }
    let mut total = 0.0f64;
    for (index, action) in distribution.iter().enumerate() {
        if usize::from(action.entity) >= assignment.len()
            || action.new_role >= inference.k
            || action.new_role == assignment[usize::from(action.entity)]
        {
            return Err(RolloutError::InvalidAction);
        }
        if !action.probability.is_finite() || action.probability < 0.0 {
            return Err(RolloutError::InvalidProbability);
        }
        if distribution[..index]
            .iter()
            .any(|prior| prior.entity == action.entity && prior.new_role == action.new_role)
        {
            return Err(RolloutError::DuplicateAction);
        }
        total += action.probability;
    }
    if !total.is_finite() || total <= 0.0 || (total - 1.0).abs() > 1e-6 {
        return Err(RolloutError::UnnormalizedDistribution(total));
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
        .ok_or(RolloutError::EmptyDistribution)
}

fn validate_public_pair(
    task: &Task,
    inference: &InferenceTask,
    features: &PublicFeatures,
) -> Result<(), RolloutError> {
    if task.id != inference.id
        || task.family_id != inference.family_id
        || task.n != inference.n
        || task.k != inference.k
        || task.role_anonymous != inference.role_anonymous
        || task.clauses.len() != inference.clauses.len()
    {
        return Err(RolloutError::PublicTaskMismatch);
    }
    if features.clause_embeddings.len() != inference.clauses.len() {
        return Err(RolloutError::FeatureClauseCount {
            expected: inference.clauses.len(),
            actual: features.clause_embeddings.len(),
        });
    }
    if features.sensor_artifact_sha256.len() != 64
        || !features
            .sensor_artifact_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(RolloutError::InvalidSensorArtifactHash);
    }
    if features.global_embedding.is_empty() {
        return Err(RolloutError::EmptyFeatures);
    }
    let hidden_dim = features.global_embedding.len();
    if features
        .clause_embeddings
        .iter()
        .any(|embedding| embedding.len() != hidden_dim)
    {
        return Err(RolloutError::FeatureDimensionMismatch);
    }
    if features
        .global_embedding
        .iter()
        .chain(features.clause_embeddings.iter().flatten())
        .any(|v| !v.is_finite())
    {
        return Err(RolloutError::NonFiniteFeature);
    }
    Ok(())
}

fn validate_state(task: &Task, state: &IndividualState) -> Result<(), RolloutError> {
    if state.assignment.len() != usize::from(task.n) {
        return Err(RolloutError::AssignmentLength);
    }
    if state.assignment.iter().any(|role| *role >= task.k) {
        return Err(RolloutError::RoleOutOfRange);
    }
    if state.latent_state.iter().any(|value| !value.is_finite()) {
        return Err(RolloutError::NonFiniteLatent);
    }
    if state.state_id.is_empty() {
        return Err(RolloutError::EmptyStateId);
    }
    Ok(())
}

fn ensure_snapshot<P: FrozenProposal>(
    proposal: &P,
    expected: [u8; 32],
) -> Result<(), RolloutError> {
    if proposal.snapshot_sha256() != expected {
        return Err(RolloutError::ProposalChangedDuringDataset);
    }
    Ok(())
}

fn task_digest(task: &Task) -> Result<String, RolloutError> {
    let bytes = serde_json::to_vec(task).map_err(|_| RolloutError::Serialization)?;
    Ok(hex_digest(Sha256::digest(bytes).into()))
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

fn derive_seed(base: u64, state_id: &str, rollout_index: u32) -> u64 {
    let mut hash = Sha256::new();
    hash.update(base.to_le_bytes());
    hash.update(state_id.as_bytes());
    hash.update(rollout_index.to_le_bytes());
    let digest = hash.finalize();
    u64::from_le_bytes(
        digest[..8]
            .try_into()
            .expect("SHA-256 prefix has eight bytes"),
    )
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

#[derive(Clone, Debug, PartialEq)]
pub enum RolloutError {
    NoStates,
    NoRollouts,
    PublicTaskMismatch,
    FeatureClauseCount { expected: usize, actual: usize },
    InvalidSensorArtifactHash,
    EmptyFeatures,
    FeatureDimensionMismatch,
    NonFiniteFeature,
    AssignmentLength,
    RoleOutOfRange,
    NonFiniteLatent,
    EmptyStateId,
    DuplicateStateId(String),
    EmptyDistribution,
    EmptyTrajectory,
    InvalidAction,
    InvalidProbability,
    DuplicateAction,
    UnnormalizedDistribution(f64),
    Proposal(String),
    ProposalChangedDuringDataset,
    Serialization,
}

impl fmt::Display for RolloutError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoStates => write!(f, "reachability dataset has no individual states"),
            Self::NoRollouts => write!(f, "each state requires at least one rollout"),
            Self::PublicTaskMismatch => {
                write!(f, "private and public task identities/shapes differ")
            }
            Self::FeatureClauseCount { expected, actual } => {
                write!(f, "feature clause count {actual}, expected {expected}")
            }
            Self::InvalidSensorArtifactHash => {
                write!(f, "sensor artifact identity must be 64 hex characters")
            }
            Self::EmptyFeatures => write!(f, "global sensor embedding must not be empty"),
            Self::FeatureDimensionMismatch => write!(
                f,
                "clause and global sensor embeddings have different dimensions"
            ),
            Self::NonFiniteFeature => write!(f, "public feature contains a non-finite value"),
            Self::AssignmentLength => write!(f, "assignment length does not match task"),
            Self::RoleOutOfRange => write!(f, "assignment contains a role outside the task range"),
            Self::NonFiniteLatent => write!(f, "latent state contains a non-finite value"),
            Self::EmptyStateId => write!(f, "individual state ID must not be empty"),
            Self::DuplicateStateId(state_id) => {
                write!(f, "duplicate individual state ID: {state_id}")
            }
            Self::EmptyDistribution => write!(f, "frozen proposal returned no actions"),
            Self::EmptyTrajectory => write!(f, "rollout did not retain an initial state"),
            Self::InvalidAction => {
                write!(f, "proposal action is outside the legal single-edit set")
            }
            Self::InvalidProbability => {
                write!(f, "proposal probability must be finite and nonnegative")
            }
            Self::DuplicateAction => write!(f, "proposal distribution contains a duplicate action"),
            Self::UnnormalizedDistribution(sum) => {
                write!(f, "proposal probabilities sum to {sum}, expected one")
            }
            Self::Proposal(message) => write!(f, "frozen proposal failed: {message}"),
            Self::ProposalChangedDuringDataset => {
                write!(f, "proposal snapshot changed while building labels")
            }
            Self::Serialization => write!(f, "could not serialize private task for identity hash"),
        }
    }
}

impl std::error::Error for RolloutError {}
