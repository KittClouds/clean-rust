use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AuthorityMembership {
    InAuthority,
    NotInAuthority,
    NotEvaluable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RetentionFidelity {
    ExactSemanticValue,
    SemanticClass,
    RelationalStructure,
    StructureOnly,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ComparisonStatus {
    Deferred,
    NotApplicable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PreservationScope {
    StateSnapshot,
    Transition,
    Emission,
    OrderedTrace,
    Timing,
    Genealogy,
    Rejection,
    ContextConditional,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ElementG4Role {
    DirectObservable,
    ContributesToObservable,
    ContextParameter,
    InternalOnly,
    NotInAuthority,
    NotEvaluable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ContextRole {
    ObservedContext,
    InterpretationParameter,
    ComparisonPreconditionDeferred,
    ProvenanceOnly,
    NotInAuthority,
    NotEvaluable,
    NotApplicable,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Observable {
    pub observable_id: String,
    pub description: String,
    pub authority_membership: AuthorityMembership,
    pub retention_fidelity: Option<RetentionFidelity>,
    pub scopes: Vec<PreservationScope>,
    pub cross_history_comparison: ComparisonStatus,
    pub normative_reason: String,
    pub source_authority: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ElementDisposition {
    pub element_id: String,
    pub g2_roles: Vec<String>,
    pub g3_constraint_ids: Vec<String>,
    pub element_g4_role: ElementG4Role,
    pub authority_membership: AuthorityMembership,
    pub mapped_observable_ids: Vec<String>,
    pub retention_fidelity: Option<RetentionFidelity>,
    pub scopes: Vec<PreservationScope>,
    pub context_role: ContextRole,
    pub temporal_authority: String,
    pub ordering_authority: String,
    pub genealogy_sensitive: bool,
    pub representation_sensitive: bool,
    pub cross_history_comparison: ComparisonStatus,
    pub normative_reason: String,
    pub authority_source: Vec<String>,
    pub not_evaluable_reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SurfaceProducts {
    pub observables: Vec<Observable>,
    pub elements: Vec<ElementDisposition>,
}
