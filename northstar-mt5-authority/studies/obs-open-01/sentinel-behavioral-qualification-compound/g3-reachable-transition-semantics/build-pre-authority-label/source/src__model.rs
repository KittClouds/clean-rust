use obs_open_04a_g1::model::{CompletedObservation, KernelContext, KernelEmissions, KernelState};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ContextAuthority {
    HistoricallyQualifiedContext,
    SyntheticSemanticFixtureContext,
    ConstructedContextWithProvenKernelAdmissibility,
    UnqualifiedContext,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum LanguageStatus {
    Exact,
    SoundOverapproximation,
    ConstructiveUnderapproximation,
    Mixed,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EpistemicStatus {
    ProvenInvariant,
    ProvenTransitionConstraint,
    ProvenTraceConstraint,
    ProvenUnreachableConfiguration,
    ProvenUnreachableTransition,
    ReachableWithWitnessTrace,
    ObservedInDA,
    ConservativeOverapproximation,
    BoundedNoReachabilityWitness,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ConstraintScope {
    State,
    StateContext,
    StateInput,
    Transition,
    TransitionEmission,
    TracePrefix,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Constraint {
    pub constraint_id: String,
    pub participants: Vec<String>,
    pub scope: ConstraintScope,
    pub authority: EpistemicStatus,
    pub expression: String,
    pub preconditions: Vec<String>,
    pub proof_reference: String,
    pub approximation_direction: String,
    pub known_failure_domain: Vec<String>,
    pub g2_collision_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "result", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum TransitionResult {
    Applied {
        next_state: KernelState,
        emissions: KernelEmissions,
    },
    Rejected {
        reason: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WitnessTrace {
    pub witness_id: String,
    pub authority: EpistemicStatus,
    pub context_authority: ContextAuthority,
    pub establishes: Vec<String>,
    pub context: KernelContext,
    pub prefix: Vec<CompletedObservation>,
    pub target_prior_state: KernelState,
    pub target_input: CompletedObservation,
    pub target_result: TransitionResult,
    pub historical_instantiation_claimed: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApproximationBoundary {
    pub object: String,
    pub status: LanguageStatus,
    pub lower_bound: String,
    pub upper_bound: String,
    pub known_error_direction: String,
    pub exactness_claimed: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UnreachabilityProof {
    pub proof_id: String,
    pub status: EpistemicStatus,
    pub prohibited_configuration: String,
    pub contradiction: String,
    pub context_scope: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CollisionDisposition {
    pub collision_id: String,
    pub g2_element: String,
    pub g2_roles: Vec<String>,
    pub g3_disposition: String,
    pub constraint_ids: Vec<String>,
    pub evidence: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditProducts {
    pub constraints: Vec<Constraint>,
    pub witnesses: Vec<WitnessTrace>,
    pub bounds: Vec<ApproximationBoundary>,
    pub unreachability: Vec<UnreachabilityProof>,
    pub collisions: Vec<CollisionDisposition>,
}
