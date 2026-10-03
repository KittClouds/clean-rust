use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Side {
    Upper,
    Lower,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MatchingDisposition {
    LiteralSemanticEquality,
    SemanticClassEquality,
    RoleCorrespondence,
    RelationalIsomorphism,
    OrderedRelationalMatch,
    TemporalCorrespondence,
    CouplingRelativeMatch,
    NotApplicable,
    NotEvaluable,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ObservableRule {
    pub observable_id: String,
    pub disposition: MatchingDisposition,
    pub rule_id: String,
    pub literal_identity_required: bool,
    pub correspondence_component: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComparisonFiberKey {
    pub price_scale: i64,
    pub source_time_resolution_ns: i64,
    pub storage_time_resolution_ns: i64,
    pub cadence_ns: i64,
    pub session_duration_ns: i64,
    pub range_count: u16,
    pub range_shape_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ContextAnchor {
    pub fiber: ComparisonFiberKey,
    pub price_origin_ticks: i64,
    pub time_origin_ns: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct CandidateKey {
    pub side: Side,
    pub id: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CandidatePair {
    pub left: CandidateKey,
    pub right: CandidateKey,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AffineCorrespondence {
    pub price_delta_ticks: i64,
    pub time_delta_ns: i64,
    pub candidate_pairs: Vec<CandidatePair>,
    pub architecture_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "class", content = "reason", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum TransitionOutcome {
    Applied,
    Rejected(String),
    PrePresentationInvalid(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProtectedEvent {
    pub kind: String,
    pub side: Option<Side>,
    pub candidate_id: Option<u32>,
    pub experiment_ordinal: u32,
    pub causal_ordinal: u32,
    pub emission_ordinal: u16,
    pub semantic_time_ns: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MatchVerdict {
    Match,
    BehavioralMismatch,
    PairNotComparableForThisToken,
    CouplingDomainFailure,
    ContextAlignmentFailure,
    PrefixPresentationFailure,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ComparabilityStatus {
    Comparable,
    EpsilonOnly,
    CouplingUnavailable,
    CorrespondenceInvalid,
    ContextIncompatible,
    ConditionalOnReachability,
    NotEvaluable,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LawProof {
    pub law: String,
    pub status: String,
    pub domain: String,
    pub derivation: Vec<String>,
    pub fixture_is_proof: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FixtureReceipt {
    pub fixture_id: String,
    pub purpose: String,
    pub expected: String,
    pub observed: String,
    pub status: String,
}
