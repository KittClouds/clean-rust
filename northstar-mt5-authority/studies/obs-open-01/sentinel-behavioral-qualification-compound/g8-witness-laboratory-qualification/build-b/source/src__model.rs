use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AuthorityVerdict {
    VerifiedReachable,
    BoundedNotFound,
    Unknown,
    InductiveInNamedScope,
    ConcreteNoninductiveTransition,
    UnknownSemanticInvariance,
    EquivalentWithAcceptedUniversalProof,
    BehaviorallyNonEquivalentWithVerifiedSeparator,
    VerifiedFiniteSeparator,
    MinimalWithinDeclaredFiniteBox,
    CheaperVerifiedWitness,
    UnknownGlobalMinimality,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum LabArtifactClass {
    CanonicalFirstWitness,
    ShrunkWitness,
    FiniteBoxMinimum,
    UniversalProofCertificate,
    ReachabilityCertificate,
    OtherRegisteredArtifact,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SearchStatus {
    NotStarted,
    Running,
    BoundedDomainExhausted,
    Timeout,
    ResourceExhausted,
    Interrupted,
    Aborted,
    Complete,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct NeutralToken {
    pub open_delta_ticks: i64,
    pub high_delta_ticks: i64,
    pub low_delta_ticks: i64,
    pub close_delta_ticks: i64,
    pub coverage_class: u8,
}

impl NeutralToken {
    pub fn flat(value: i64) -> Self {
        Self {
            open_delta_ticks: value,
            high_delta_ticks: value,
            low_delta_ticks: value,
            close_delta_ticks: value,
            coverage_class: 1,
        }
    }

    pub fn is_source_valid(&self) -> bool {
        self.coverage_class <= 1
            && self.high_delta_ticks >= self.open_delta_ticks.max(self.close_delta_ticks)
            && self.low_delta_ticks <= self.open_delta_ticks.min(self.close_delta_ticks)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SyntheticMachine {
    pub machine_id: String,
    pub fiber_id: String,
    pub initial_state: usize,
    pub states: Vec<SyntheticState>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SyntheticState {
    pub protected_value: i64,
    pub on_negative: Option<usize>,
    pub on_zero: Option<usize>,
    pub on_positive: Option<usize>,
}

impl SyntheticMachine {
    pub fn next(&self, state: usize, token: &NeutralToken) -> Option<usize> {
        let row = self.states.get(state)?;
        match token.close_delta_ticks.cmp(&0) {
            std::cmp::Ordering::Less => row.on_negative,
            std::cmp::Ordering::Equal => row.on_zero,
            std::cmp::Ordering::Greater => row.on_positive,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FiberCertificate {
    pub schema_id: String,
    pub source: String,
    pub fiber_id: String,
    pub left_machine_id: String,
    pub right_machine_id: String,
    pub construction_proof_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AuthorityBinding {
    pub g3_root: String,
    pub g4_root: String,
    pub g5_root: String,
    pub g6_root: String,
    pub g7_root: String,
    pub theta_star_id: String,
    pub certificate_schema_id: String,
    pub certificate_schema_version: u32,
    pub g8_verifier_contract_hash: String,
    pub authority_bundle_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FrozenComparison {
    pub left_machine: SyntheticMachine,
    pub right_machine: SyntheticMachine,
    pub left_start: usize,
    pub right_start: usize,
    pub gamma: String,
    pub theta_star_id: String,
    pub lambda_policy_id: String,
    pub initial_correspondence_id: String,
    pub left_context_id: String,
    pub right_context_id: String,
    pub fiber_certificate: FiberCertificate,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DerivedClaims {
    pub left_state_trace: Vec<usize>,
    pub right_state_trace: Vec<usize>,
    pub protected_trace_left: Vec<i64>,
    pub protected_trace_right: Vec<i64>,
    pub first_mismatch_experiment_ordinal: Option<usize>,
    pub mismatch_observable_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SeparatorCertificate {
    pub binding: AuthorityBinding,
    pub comparison: FrozenComparison,
    pub neutral_token_sequence: Vec<NeutralToken>,
    pub claimed: DerivedClaims,
    pub metadata_note: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VerificationResult {
    pub accepted: bool,
    pub code: String,
    pub verdict: AuthorityVerdict,
    pub recomputed: Option<DerivedClaims>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SearchResult {
    pub search_status: SearchStatus,
    pub authority_verdict: AuthorityVerdict,
    pub artifact_class: LabArtifactClass,
    pub certificate: Option<SeparatorCertificate>,
    pub dispositioned_lower_ranks: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CoverageReceipt {
    pub domain_id: String,
    pub domain_cardinality: usize,
    pub visited_indices: Vec<usize>,
    pub visited_accumulator_hash: String,
    pub accepted_separator_indices: Vec<usize>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FiniteMachine {
    pub id: String,
    pub initial_state: usize,
    pub outputs: Vec<i64>,
    pub transitions: Vec<Vec<usize>>,
    pub alphabet_size: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UniversalProof {
    pub proof_system_id: String,
    pub left: FiniteMachine,
    pub right: FiniteMachine,
    pub relation: Vec<(usize, usize)>,
}
