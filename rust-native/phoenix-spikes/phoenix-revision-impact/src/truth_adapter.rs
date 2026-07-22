use compact_str::{format_compact, CompactString};
use hashbrown::HashMap;
use phoenix_semantic_v2::{
    BeliefStateKind, CausalClaimStatus, CausalScopeSidecar, MemoryClaimStatus, MemoryScopeSidecar,
    TemporalScopeSidecar, TemporalTruthStatus,
};
use phoenix_types::{
    BiTemporalWindow, ConstraintKind, DependencyClass, FactId, FactValue, SceneId, StoryInterval,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{
    ConstraintSeed, CounterfactualGraphView, EvidenceRef, GraphGeneration, RevisionGraphSnapshot,
    SourceRange, StateRef,
};

pub const REVISION_REQUIREMENT_SIDECAR_SCHEMA: &str = "phoenix-revision-requirements/v1";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum RequirementDependency {
    Fact { fact_id: FactId },
    State { state_ref: StateRef },
}

impl RequirementDependency {
    pub fn graph_id(&self) -> CompactString {
        match self {
            Self::Fact { fact_id } => fact_id.0.clone(),
            Self::State { state_ref } => format_compact!(
                "state:{}:{}",
                state_ref.subject_id.0,
                state_ref.state_kind.0
            ),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "plane", rename_all = "snake_case", deny_unknown_fields)]
pub enum RequirementTruthRef {
    Belief { belief_id: CompactString },
    TemporalConstraint { constraint_id: CompactString },
    MemoryState { state_id: CompactString },
    MemoryConflict { conflict_id: CompactString },
    CausalEdge { edge_id: CompactString },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionRequirementRecord {
    pub constraint_id: CompactString,
    pub dependency: RequirementDependency,
    pub expected_value: FactValue,
    pub dependent_scene_id: SceneId,
    pub kind: ConstraintKind,
    pub valid_interval: StoryInterval,
    pub truth_ref: RequirementTruthRef,
    pub evidence: Vec<EvidenceRef>,
    pub confidence_millis: u16,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionRequirementSidecar {
    pub schema_version: CompactString,
    pub generation: GraphGeneration,
    pub requirements: Vec<RevisionRequirementRecord>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AdapterTruthPlane {
    Belief,
    Temporal,
    Lifecycle,
    Possession,
    Location,
    State,
    Relationship,
    Capability,
    Causal,
}

impl AdapterTruthPlane {
    pub const ALL: [Self; 9] = [
        Self::Belief,
        Self::Temporal,
        Self::Lifecycle,
        Self::Possession,
        Self::Location,
        Self::State,
        Self::Relationship,
        Self::Capability,
        Self::Causal,
    ];
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AdapterCoverageStatus {
    Covered,
    Unavailable,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AdapterPlaneCoverage {
    pub plane: AdapterTruthPlane,
    pub status: AdapterCoverageStatus,
    pub projected_constraints: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConstraintProjectionReceipt {
    pub generation: GraphGeneration,
    pub projected_constraints: usize,
    pub hard_constraints: usize,
    pub soft_constraints: usize,
    pub planes: Vec<AdapterPlaneCoverage>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProjectedConstraintBundle {
    pub constraints: Vec<ConstraintSeed>,
    pub receipt: ConstraintProjectionReceipt,
}

pub struct AuthoritativeRevisionSources<'a> {
    pub base: &'a RevisionGraphSnapshot,
    pub requirements: &'a RevisionRequirementSidecar,
    pub temporal: Option<&'a TemporalScopeSidecar>,
    pub memory: Option<&'a MemoryScopeSidecar>,
    pub causal: Option<&'a CausalScopeSidecar>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RequirementEvaluation {
    Satisfied,
    Violated,
}

pub fn project_authoritative_constraints(
    sources: AuthoritativeRevisionSources<'_>,
) -> Result<ProjectedConstraintBundle, TruthAdapterError> {
    validate_generations(&sources)?;
    if sources.requirements.schema_version.as_str() != REVISION_REQUIREMENT_SIDECAR_SCHEMA {
        return Err(TruthAdapterError::SchemaMismatch);
    }
    let mut requirements = sources.requirements.requirements.iter().collect::<Vec<_>>();
    requirements.sort_unstable_by(|left, right| left.constraint_id.cmp(&right.constraint_id));
    if let Some(pair) = requirements
        .windows(2)
        .find(|pair| pair[0].constraint_id == pair[1].constraint_id)
    {
        return Err(TruthAdapterError::DuplicateConstraint(
            pair[0].constraint_id.clone(),
        ));
    }
    let edges = sources
        .base
        .edges()
        .iter()
        .map(|edge| (edge.edge_id.as_str(), edge))
        .collect::<HashMap<_, _>>();
    let mut constraints = Vec::with_capacity(requirements.len());
    let mut plane_counts = HashMap::<AdapterTruthPlane, usize>::new();
    let mut hard_constraints = 0;
    let mut soft_constraints = 0;

    for requirement in requirements {
        validate_requirement_base(&sources, requirement, &edges)?;
        let source = authoritative_source(&sources, requirement)?;
        if !window_contains(&source.temporal, requirement.valid_interval) {
            return Err(TruthAdapterError::SourceIntervalGap(
                requirement.constraint_id.clone(),
            ));
        }
        let plane = requirement_plane(requirement);
        *plane_counts.entry(plane).or_default() += 1;
        match requirement.kind.dependency_class() {
            DependencyClass::HardRequirement => hard_constraints += 1,
            DependencyClass::DefeasibleSupport | DependencyClass::WeakAssociation => {
                soft_constraints += 1;
            }
        }
        let mut evidence = requirement.evidence.clone();
        evidence.extend(source.evidence);
        evidence.sort_unstable_by(|left, right| left.evidence_id.cmp(&right.evidence_id));
        evidence.dedup_by(|left, right| left.evidence_id == right.evidence_id);
        constraints.push(ConstraintSeed {
            constraint_id: requirement.constraint_id.clone(),
            source_id: requirement.dependency.graph_id(),
            dependent_id: requirement.dependent_scene_id.0.clone(),
            kind: requirement.kind,
            valid_interval: requirement.valid_interval,
            evidence,
            confidence_millis: requirement.confidence_millis.min(source.confidence_millis),
        });
    }
    let planes = AdapterTruthPlane::ALL
        .into_iter()
        .map(|plane| AdapterPlaneCoverage {
            plane,
            status: plane_status(&sources, plane),
            projected_constraints: plane_counts.get(&plane).copied().unwrap_or(0),
        })
        .collect();
    Ok(ProjectedConstraintBundle {
        receipt: ConstraintProjectionReceipt {
            generation: sources.base.generation(),
            projected_constraints: constraints.len(),
            hard_constraints,
            soft_constraints,
            planes,
        },
        constraints,
    })
}

pub fn evaluate_requirement(
    overlay: &CounterfactualGraphView<'_>,
    requirement: &RevisionRequirementRecord,
) -> RequirementEvaluation {
    let valid = match &requirement.dependency {
        RequirementDependency::Fact { fact_id } => overlay.fact_satisfies(
            fact_id,
            &requirement.expected_value,
            requirement.valid_interval,
        ),
        RequirementDependency::State { state_ref } => overlay.state_satisfies(
            state_ref,
            &requirement.expected_value,
            requirement.valid_interval,
        ),
    };
    if valid {
        RequirementEvaluation::Satisfied
    } else {
        RequirementEvaluation::Violated
    }
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum TruthAdapterError {
    #[error("revision requirement sidecar schema mismatch")]
    SchemaMismatch,
    #[error("generation mismatch for {plane_source}: expected {expected}, got {actual}")]
    GenerationMismatch {
        plane_source: &'static str,
        expected: u64,
        actual: u64,
    },
    #[error("duplicate constraint {0}")]
    DuplicateConstraint(CompactString),
    #[error("missing dependency edge {0}")]
    MissingDependencyEdge(CompactString),
    #[error("dependency edge does not name its source for {0}")]
    DependencyEdgeMismatch(CompactString),
    #[error("missing base dependency {0}")]
    MissingBaseDependency(CompactString),
    #[error("base dependency does not satisfy requirement {0}")]
    BaseRequirementMismatch(CompactString),
    #[error("missing truth plane for {0}")]
    MissingTruthPlane(CompactString),
    #[error("missing truth record for {0}")]
    MissingTruthRecord(CompactString),
    #[error("non-authoritative truth record for {0}")]
    NonAuthoritativeTruth(CompactString),
    #[error("truth record kind does not match requirement {0}")]
    TruthKindMismatch(CompactString),
    #[error("truth record interval does not cover requirement {0}")]
    SourceIntervalGap(CompactString),
    #[error("invalid confidence for {0}")]
    InvalidConfidence(CompactString),
    #[error("missing evidence for {0}")]
    MissingEvidence(CompactString),
}

struct AuthoritativeSource {
    temporal: BiTemporalWindow,
    evidence: Vec<EvidenceRef>,
    confidence_millis: u16,
}

fn validate_generations(
    sources: &AuthoritativeRevisionSources<'_>,
) -> Result<(), TruthAdapterError> {
    let expected = sources.base.generation().0;
    check_generation("requirements", expected, sources.requirements.generation.0)?;
    if let Some(sidecar) = sources.temporal {
        check_generation("temporal", expected, sidecar.generation)?;
    }
    if let Some(sidecar) = sources.memory {
        check_generation("memory", expected, sidecar.generation)?;
    }
    if let Some(sidecar) = sources.causal {
        check_generation("causal", expected, sidecar.generation)?;
    }
    Ok(())
}

fn check_generation(
    source: &'static str,
    expected: u64,
    actual: u64,
) -> Result<(), TruthAdapterError> {
    if expected == actual {
        Ok(())
    } else {
        Err(TruthAdapterError::GenerationMismatch {
            plane_source: source,
            expected,
            actual,
        })
    }
}

fn validate_requirement_base(
    sources: &AuthoritativeRevisionSources<'_>,
    requirement: &RevisionRequirementRecord,
    edges: &HashMap<&str, &crate::RevisionEdgeRecord>,
) -> Result<(), TruthAdapterError> {
    if requirement.confidence_millis > 1000 {
        return Err(TruthAdapterError::InvalidConfidence(
            requirement.constraint_id.clone(),
        ));
    }
    if requirement.evidence.is_empty() {
        return Err(TruthAdapterError::MissingEvidence(
            requirement.constraint_id.clone(),
        ));
    }
    let edge = edges
        .get(requirement.constraint_id.as_str())
        .ok_or_else(|| {
            TruthAdapterError::MissingDependencyEdge(requirement.constraint_id.clone())
        })?;
    let edge_matches = match &requirement.dependency {
        RequirementDependency::Fact { fact_id } => edge.dependency_fact_ids.contains(fact_id),
        RequirementDependency::State { state_ref } => {
            edge.dependency_state_refs.contains(state_ref)
        }
    };
    if !edge_matches {
        return Err(TruthAdapterError::DependencyEdgeMismatch(
            requirement.constraint_id.clone(),
        ));
    }
    let base_matches = match &requirement.dependency {
        RequirementDependency::Fact { fact_id } => sources.base.fact(fact_id).is_some_and(|fact| {
            fact.value == requirement.expected_value
                && interval_contains(fact.interval, requirement.valid_interval)
        }),
        RequirementDependency::State { state_ref } => {
            sources.base.state(state_ref).is_some_and(|state| {
                state.value == requirement.expected_value
                    && interval_contains(state.interval, requirement.valid_interval)
            })
        }
    };
    if base_matches {
        Ok(())
    } else {
        Err(TruthAdapterError::BaseRequirementMismatch(
            requirement.constraint_id.clone(),
        ))
    }
}

fn authoritative_source(
    sources: &AuthoritativeRevisionSources<'_>,
    requirement: &RevisionRequirementRecord,
) -> Result<AuthoritativeSource, TruthAdapterError> {
    match &requirement.truth_ref {
        RequirementTruthRef::Belief { belief_id } => {
            let sidecar = sources.temporal.ok_or_else(|| {
                TruthAdapterError::MissingTruthPlane(requirement.constraint_id.clone())
            })?;
            let row = sidecar
                .belief_atoms
                .iter()
                .find(|row| row.belief_id == belief_id.as_str())
                .ok_or_else(|| {
                    TruthAdapterError::MissingTruthRecord(requirement.constraint_id.clone())
                })?;
            let kind_matches = matches!(
                (requirement.kind, row.kind),
                (ConstraintKind::RequiresKnowledge, BeliefStateKind::Knows)
                    | (ConstraintKind::RequiresWitness, BeliefStateKind::Observed)
            );
            if !kind_matches {
                return Err(TruthAdapterError::TruthKindMismatch(
                    requirement.constraint_id.clone(),
                ));
            }
            if !matches!(
                row.truth_status,
                TemporalTruthStatus::Observed
                    | TemporalTruthStatus::Asserted
                    | TemporalTruthStatus::Inferred
            ) {
                return Err(TruthAdapterError::NonAuthoritativeTruth(
                    requirement.constraint_id.clone(),
                ));
            }
            source(
                requirement,
                row.temporal.clone(),
                &row.document_id,
                row.range.map(|range| (range.start, range.end)),
                &row.evidence_refs,
                row.confidence_millis,
            )
        }
        RequirementTruthRef::TemporalConstraint { constraint_id } => {
            let sidecar = sources.temporal.ok_or_else(|| {
                TruthAdapterError::MissingTruthPlane(requirement.constraint_id.clone())
            })?;
            let row = sidecar
                .constraints
                .iter()
                .find(|row| row.constraint_id.0 == constraint_id.as_str())
                .ok_or_else(|| {
                    TruthAdapterError::MissingTruthRecord(requirement.constraint_id.clone())
                })?;
            if requirement.kind != ConstraintKind::RequiresTemporalOrder || !row.hard {
                return Err(TruthAdapterError::TruthKindMismatch(
                    requirement.constraint_id.clone(),
                ));
            }
            source(
                requirement,
                row.temporal.clone(),
                &row.document_id,
                None,
                &row.evidence_refs,
                row.confidence_millis,
            )
        }
        RequirementTruthRef::MemoryState { state_id } => {
            let sidecar = sources.memory.ok_or_else(|| {
                TruthAdapterError::MissingTruthPlane(requirement.constraint_id.clone())
            })?;
            let row = sidecar
                .states
                .iter()
                .find(|row| row.state_id == state_id.as_str())
                .ok_or_else(|| {
                    TruthAdapterError::MissingTruthRecord(requirement.constraint_id.clone())
                })?;
            if !matches!(
                row.status,
                MemoryClaimStatus::Active | MemoryClaimStatus::Supported
            ) {
                return Err(TruthAdapterError::NonAuthoritativeTruth(
                    requirement.constraint_id.clone(),
                ));
            }
            if !matches!(
                requirement.kind,
                ConstraintKind::RequiresAlive
                    | ConstraintKind::RequiresPossession
                    | ConstraintKind::RequiresReachability
                    | ConstraintKind::RequiresState
            ) {
                return Err(TruthAdapterError::TruthKindMismatch(
                    requirement.constraint_id.clone(),
                ));
            }
            if !memory_value_matches(row, &requirement.expected_value)
                || matches!(
                    &requirement.dependency,
                    RequirementDependency::State { state_ref }
                        if row.entity_id != state_ref.subject_id
                            || row.slot_key != state_ref.state_kind.0
                )
            {
                return Err(TruthAdapterError::TruthKindMismatch(
                    requirement.constraint_id.clone(),
                ));
            }
            source(
                requirement,
                row.temporal.clone(),
                "memory-sidecar",
                None,
                &row.claim_ids,
                row.confidence_millis,
            )
        }
        RequirementTruthRef::MemoryConflict { conflict_id } => {
            let sidecar = sources.memory.ok_or_else(|| {
                TruthAdapterError::MissingTruthPlane(requirement.constraint_id.clone())
            })?;
            let row = sidecar
                .conflicts
                .iter()
                .find(|row| row.conflict_id == conflict_id.as_str())
                .ok_or_else(|| {
                    TruthAdapterError::MissingTruthRecord(requirement.constraint_id.clone())
                })?;
            if requirement.kind != ConstraintKind::MutuallyExclusiveStates
                || !matches!(
                    row.status,
                    MemoryClaimStatus::Active | MemoryClaimStatus::Supported
                )
            {
                return Err(TruthAdapterError::NonAuthoritativeTruth(
                    requirement.constraint_id.clone(),
                ));
            }
            source(
                requirement,
                row.temporal.clone(),
                "memory-sidecar",
                None,
                &row.claim_ids,
                1000,
            )
        }
        RequirementTruthRef::CausalEdge { edge_id } => {
            let sidecar = sources.causal.ok_or_else(|| {
                TruthAdapterError::MissingTruthPlane(requirement.constraint_id.clone())
            })?;
            let row = sidecar
                .edge_records
                .iter()
                .find(|row| row.edge_id.0 == edge_id.as_str())
                .ok_or_else(|| {
                    TruthAdapterError::MissingTruthRecord(requirement.constraint_id.clone())
                })?;
            if !matches!(
                row.status,
                CausalClaimStatus::Active | CausalClaimStatus::Supported
            ) {
                return Err(TruthAdapterError::NonAuthoritativeTruth(
                    requirement.constraint_id.clone(),
                ));
            }
            if !matches!(
                requirement.kind,
                ConstraintKind::CausalSupport
                    | ConstraintKind::Motivation
                    | ConstraintKind::Foreshadowing
            ) {
                return Err(TruthAdapterError::TruthKindMismatch(
                    requirement.constraint_id.clone(),
                ));
            }
            if requirement.kind == ConstraintKind::Motivation
                && row.kind != phoenix_types::CausalKind::Motivates
            {
                return Err(TruthAdapterError::TruthKindMismatch(
                    requirement.constraint_id.clone(),
                ));
            }
            source(
                requirement,
                row.effective_interval.clone(),
                &row.document_id,
                None,
                &row.evidence_refs,
                row.confidence_millis,
            )
        }
    }
}

fn source(
    requirement: &RevisionRequirementRecord,
    temporal: BiTemporalWindow,
    document_id: &str,
    range: Option<(u32, u32)>,
    evidence_ids: &[String],
    confidence_millis: u32,
) -> Result<AuthoritativeSource, TruthAdapterError> {
    if evidence_ids.is_empty() {
        return Err(TruthAdapterError::MissingEvidence(
            requirement.constraint_id.clone(),
        ));
    }
    let confidence_millis = u16::try_from(confidence_millis)
        .ok()
        .filter(|value| *value <= 1000)
        .ok_or_else(|| TruthAdapterError::InvalidConfidence(requirement.constraint_id.clone()))?;
    let evidence = evidence_ids
        .iter()
        .map(|evidence_id| EvidenceRef {
            evidence_id: evidence_id.as_str().into(),
            document_id: Some(document_id.into()),
            source_range: range.map(|(start, end)| SourceRange { start, end }),
        })
        .collect();
    Ok(AuthoritativeSource {
        temporal,
        evidence,
        confidence_millis,
    })
}

fn memory_value_matches(
    row: &phoenix_semantic_v2::MemoryStateRecord,
    expected: &FactValue,
) -> bool {
    match expected {
        FactValue::Boolean(value) => row.value == value.to_string(),
        FactValue::Integer(value) => row.value.parse::<i64>() == Ok(*value),
        FactValue::Text(value) => row.value == value.as_str(),
        FactValue::Entity(value) => {
            row.value_entity_id.as_ref() == Some(value) || row.value == value.0
        }
        FactValue::DurationMinutes(value) => row.value.parse::<i64>() == Ok(*value),
    }
}

pub(crate) fn requirement_plane(requirement: &RevisionRequirementRecord) -> AdapterTruthPlane {
    match requirement.kind {
        ConstraintKind::RequiresKnowledge | ConstraintKind::RequiresWitness => {
            AdapterTruthPlane::Belief
        }
        ConstraintKind::RequiresAlive => AdapterTruthPlane::Lifecycle,
        ConstraintKind::RequiresPossession => AdapterTruthPlane::Possession,
        ConstraintKind::RequiresReachability => AdapterTruthPlane::Location,
        ConstraintKind::RequiresTemporalOrder => AdapterTruthPlane::Temporal,
        ConstraintKind::CausalSupport
        | ConstraintKind::Motivation
        | ConstraintKind::Foreshadowing => AdapterTruthPlane::Causal,
        ConstraintKind::RequiresState => match &requirement.dependency {
            RequirementDependency::State { state_ref }
                if state_ref.state_kind.0.starts_with("relationship:") =>
            {
                AdapterTruthPlane::Relationship
            }
            _ => AdapterTruthPlane::State,
        },
        ConstraintKind::MutuallyExclusiveStates
        | ConstraintKind::Mention
        | ConstraintKind::ThematicEcho => AdapterTruthPlane::State,
    }
}

fn plane_status(
    sources: &AuthoritativeRevisionSources<'_>,
    plane: AdapterTruthPlane,
) -> AdapterCoverageStatus {
    let covered = match plane {
        AdapterTruthPlane::Belief | AdapterTruthPlane::Temporal => sources.temporal.is_some(),
        AdapterTruthPlane::Lifecycle
        | AdapterTruthPlane::Possession
        | AdapterTruthPlane::Location
        | AdapterTruthPlane::State
        | AdapterTruthPlane::Relationship => sources.memory.is_some(),
        AdapterTruthPlane::Causal => sources.causal.is_some(),
        AdapterTruthPlane::Capability => false,
    };
    if covered {
        AdapterCoverageStatus::Covered
    } else {
        AdapterCoverageStatus::Unavailable
    }
}

fn interval_contains(outer: StoryInterval, inner: StoryInterval) -> bool {
    outer.is_well_formed()
        && inner.is_well_formed()
        && outer.valid_from <= inner.valid_from
        && match (outer.valid_to_exclusive, inner.valid_to_exclusive) {
            (None, _) => true,
            (Some(_), None) => false,
            (Some(outer_end), Some(inner_end)) => inner_end <= outer_end,
        }
}

fn window_contains(window: &BiTemporalWindow, inner: StoryInterval) -> bool {
    let Some(start) = window.valid_from else {
        return false;
    };
    interval_contains(
        StoryInterval {
            valid_from: phoenix_types::StoryTime(start),
            valid_to_exclusive: window.valid_to.map(phoenix_types::StoryTime),
        },
        inner,
    )
}

#[cfg(test)]
#[path = "truth_adapter_tests.rs"]
pub(crate) mod tests;

#[cfg(all(feature = "gold-harness", not(test)))]
#[path = "truth_adapter_tests.rs"]
pub mod gold_harness;
