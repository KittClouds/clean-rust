use std::collections::{BTreeMap, BTreeSet};

use compact_str::CompactString;
use phoenix_semantic_v2::{CausalScopeSidecar, MemoryScopeSidecar, TemporalScopeSidecar};
use phoenix_types::{
    CoveragePlane, DependencyClass, GraphTruthDigest, StoryInterval, StoryMutation,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{
    detect_revision_impacts, mutation_target_id, project_authoritative_constraints,
    AuthoritativeRevisionSources, CounterfactualGraphView, CounterfactualOverlayError,
    GraphEditOperation, GraphGeneration, IdentityCoverage, InferenceProjectionInput,
    ProjectionError, ProposedEdit, RepairPrecondition, RevisionAnalysisViews,
    RevisionDetectorError, RevisionDetectorInput, RevisionGraphSnapshot, RevisionImpactReport,
    RevisionRequirementSidecar, RippleConfig, SceneCoverageRequest, TruthAdapterError,
};

pub const REPAIR_VALIDATION_SCHEMA: &str = "phoenix.repair-validation/v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RepairDisposition {
    ProvenFix,
    PartialFix,
    Rejected,
    Unknown,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StoryIntervalChange {
    pub target_id: CompactString,
    pub before: Option<StoryInterval>,
    pub after: Option<StoryInterval>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RepairCoverageReceipt {
    pub required_planes: Vec<CoveragePlane>,
    pub missing_required_planes: Vec<CoveragePlane>,
    pub source_constraints_were_observed: bool,
    pub traversal_complete: bool,
    pub complete_for_claimed_constraints: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RepairValidationReceipt {
    pub schema: CompactString,
    pub candidate_digest: GraphTruthDigest,
    pub base_generation: GraphGeneration,
    pub base_digest: GraphTruthDigest,
    pub overlay_digest: GraphTruthDigest,
    pub repaired_report_digest: GraphTruthDigest,
    pub fixed_constraints: Vec<CompactString>,
    pub remaining_violations: Vec<CompactString>,
    pub introduced_violations: Vec<CompactString>,
    pub introduced_hard_violations: Vec<CompactString>,
    pub changed_intervals: Vec<StoryIntervalChange>,
    pub coverage: RepairCoverageReceipt,
    pub full_revalidation_completed: bool,
    pub base_graph_unchanged: bool,
    pub no_truth_writes: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RepairCandidate {
    pub edit: ProposedEdit,
    pub disposition: RepairDisposition,
    pub fixed_constraints: Vec<CompactString>,
    pub remaining_violations: Vec<CompactString>,
    pub introduced_violations: Vec<CompactString>,
    pub validation_receipt: RepairValidationReceipt,
}

pub struct RepairSimulationInput<'a> {
    pub base: &'a RevisionGraphSnapshot,
    pub mutations: &'a [StoryMutation],
    pub requirements: &'a RevisionRequirementSidecar,
    pub temporal: Option<&'a TemporalScopeSidecar>,
    pub memory: Option<&'a MemoryScopeSidecar>,
    pub causal: Option<&'a CausalScopeSidecar>,
    pub original_report: &'a RevisionImpactReport,
    pub author_locked_ids: &'a BTreeSet<CompactString>,
    pub ripple_config: RippleConfig,
}

#[derive(Debug, Error)]
pub enum RepairSimulationError {
    #[error("repair candidate serialization failed: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("repair precondition failed: {0}")]
    Precondition(CompactString),
    #[error("repair operation is invalid: {0}")]
    InvalidOperation(CompactString),
    #[error(transparent)]
    Overlay(#[from] CounterfactualOverlayError),
    #[error(transparent)]
    Truth(#[from] TruthAdapterError),
    #[error(transparent)]
    Projection(#[from] ProjectionError),
    #[error(transparent)]
    Detector(#[from] RevisionDetectorError),
}

pub fn simulate_repair_candidate(
    input: RepairSimulationInput<'_>,
    edit: &ProposedEdit,
) -> Result<RepairCandidate, RepairSimulationError> {
    simulate_repair_candidate_with_coverage(input, edit, None)
}

pub(crate) fn simulate_repair_candidate_with_coverage(
    input: RepairSimulationInput<'_>,
    edit: &ProposedEdit,
    coverage_override: Option<&[SceneCoverageRequest]>,
) -> Result<RepairCandidate, RepairSimulationError> {
    let base_digest = input.base.digest();
    validate_preconditions(&input, edit)?;
    if edit
        .operations
        .iter()
        .any(|operation| matches!(operation, GraphEditOperation::ApplyAuthorDirective { .. }))
    {
        return unknown_author_directive_candidate(&input, edit, base_digest);
    }
    let (mutations, requirements, mut changed_intervals) = apply_edit(&input, edit)?;
    changed_intervals.sort_by(|left, right| left.target_id.cmp(&right.target_id));

    let overlay = CounterfactualGraphView::new(input.base, mutations)?;
    let projected = project_authoritative_constraints(AuthoritativeRevisionSources {
        base: input.base,
        requirements: &requirements,
        temporal: input.temporal,
        memory: input.memory,
        causal: input.causal,
    })?;
    let views = RevisionAnalysisViews::project(
        input.base.generation(),
        projected.constraints,
        InferenceProjectionInput::default(),
    )?;
    let coverage_requests = coverage_override
        .map(<[SceneCoverageRequest]>::to_vec)
        .unwrap_or_else(|| coverage_requests(input.original_report));
    let repaired_report = detect_revision_impacts(
        RevisionDetectorInput {
            overlay: &overlay,
            constraint_graph: &views.constraint_graph,
            requirements: &requirements,
            projection_receipt: &projected.receipt,
            identity_coverage: IdentityCoverage::SameRevision,
            coverage_requests: &coverage_requests,
        },
        input.ripple_config,
    )?;

    let before = violation_classes(input.original_report);
    let after = violation_classes(&repaired_report);
    let claimed = edit
        .source_constraints
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let after_ids = after.keys().cloned().collect::<BTreeSet<_>>();
    let fixed_constraints = claimed.difference(&after_ids).cloned().collect::<Vec<_>>();
    let remaining_violations = after.keys().cloned().collect::<Vec<_>>();
    let introduced_violations = after
        .keys()
        .filter(|id| !before.contains_key(*id))
        .cloned()
        .collect::<Vec<_>>();
    let introduced_hard_violations = introduced_violations
        .iter()
        .filter(|id| after.get(*id) == Some(&DependencyClass::HardRequirement))
        .cloned()
        .collect::<Vec<_>>();
    let claimed_remaining = claimed.iter().filter(|id| after.contains_key(*id)).count();
    let coverage = repair_coverage(input.original_report, &claimed, &repaired_report);
    let disposition = classify_repair(
        fixed_constraints.len(),
        claimed.len(),
        claimed_remaining,
        &introduced_violations,
        &introduced_hard_violations,
        coverage.complete_for_claimed_constraints,
    );
    let candidate_digest = digest_edit(edit)?;
    let base_graph_unchanged = input.base.digest() == base_digest;
    let receipt = RepairValidationReceipt {
        schema: REPAIR_VALIDATION_SCHEMA.into(),
        candidate_digest,
        base_generation: input.base.generation(),
        base_digest,
        overlay_digest: overlay.receipt.mutation_digest,
        repaired_report_digest: repaired_report.deterministic_receipt.report_digest,
        fixed_constraints: fixed_constraints.clone(),
        remaining_violations: remaining_violations.clone(),
        introduced_violations: introduced_violations.clone(),
        introduced_hard_violations,
        changed_intervals,
        coverage,
        full_revalidation_completed: true,
        base_graph_unchanged,
        no_truth_writes: overlay.receipt.no_base_writes
            && repaired_report.deterministic_receipt.no_truth_writes,
    };
    Ok(RepairCandidate {
        edit: edit.clone(),
        disposition,
        fixed_constraints,
        remaining_violations,
        introduced_violations,
        validation_receipt: receipt,
    })
}

fn validate_preconditions(
    input: &RepairSimulationInput<'_>,
    edit: &ProposedEdit,
) -> Result<(), RepairSimulationError> {
    let mutation_targets = input
        .mutations
        .iter()
        .map(mutation_target_id)
        .collect::<BTreeSet<_>>();
    let constraints = input
        .requirements
        .requirements
        .iter()
        .map(|row| row.constraint_id.clone())
        .collect::<BTreeSet<_>>();
    let evidence = input
        .original_report
        .authoritative_impacts
        .iter()
        .flat_map(|impact| {
            impact
                .violated_constraints
                .iter()
                .chain(&impact.support_loss_constraints)
        })
        .flat_map(|constraint| constraint.evidence.iter())
        .map(|evidence| evidence.evidence_id.clone())
        .collect::<BTreeSet<_>>();
    for precondition in &edit.preconditions {
        let satisfied = match precondition {
            RepairPrecondition::MutationTargetExists { target_id } => {
                mutation_targets.contains(target_id)
            }
            RepairPrecondition::ConstraintExists { constraint_id } => {
                constraints.contains(constraint_id)
            }
            RepairPrecondition::EvidenceAnchored { evidence_id } => evidence.contains(evidence_id),
            RepairPrecondition::AuthorUnlocked { target_id } => {
                !input.author_locked_ids.contains(target_id)
            }
        };
        if !satisfied {
            return Err(RepairSimulationError::Precondition(
                format!("{precondition:?}").into(),
            ));
        }
    }
    Ok(())
}

fn apply_edit(
    input: &RepairSimulationInput<'_>,
    edit: &ProposedEdit,
) -> Result<
    (
        Vec<StoryMutation>,
        RevisionRequirementSidecar,
        Vec<StoryIntervalChange>,
    ),
    RepairSimulationError,
> {
    let mut mutations = input.mutations.to_vec();
    let mut requirements = input.requirements.clone();
    let mut changes = Vec::new();
    for operation in &edit.operations {
        match operation {
            GraphEditOperation::DropOriginalMutation { target_id } => {
                let index = find_mutation(&mutations, target_id)?;
                let removed = mutations.remove(index);
                changes.push(StoryIntervalChange {
                    target_id: target_id.clone(),
                    before: mutation_interval(input.base, &removed),
                    after: base_interval(input.base, &removed),
                });
            }
            GraphEditOperation::ReplaceOriginalMutation { replacement } => {
                let target_id = mutation_target_id(replacement);
                let index = find_mutation(&mutations, &target_id)?;
                let before = mutation_interval(input.base, &mutations[index]);
                mutations[index] = replacement.clone();
                changes.push(StoryIntervalChange {
                    target_id,
                    before,
                    after: mutation_interval(input.base, replacement),
                });
            }
            GraphEditOperation::RemoveRequirementBearingStatement {
                constraint_id,
                scene_id,
                evidence,
            } => {
                let index = requirements
                    .requirements
                    .iter()
                    .position(|row| row.constraint_id == *constraint_id)
                    .ok_or_else(|| invalid_operation("missing requirement", constraint_id))?;
                let row = &requirements.requirements[index];
                if row.dependent_scene_id.0 != *scene_id || row.evidence != *evidence {
                    return Err(invalid_operation(
                        "requirement anchor mismatch",
                        constraint_id,
                    ));
                }
                requirements.requirements.remove(index);
            }
            GraphEditOperation::ApplyAuthorDirective { directive_id, .. } => {
                return Err(invalid_operation(
                    "author directive requires a rebuilt semantic sidecar",
                    directive_id,
                ));
            }
        }
    }
    mutations.sort_by_key(mutation_target_id);
    requirements
        .requirements
        .sort_unstable_by(|left, right| left.constraint_id.cmp(&right.constraint_id));
    Ok((mutations, requirements, changes))
}

fn find_mutation(
    mutations: &[StoryMutation],
    target_id: &str,
) -> Result<usize, RepairSimulationError> {
    mutations
        .iter()
        .position(|mutation| mutation_target_id(mutation) == target_id)
        .ok_or_else(|| invalid_operation("missing mutation target", target_id))
}

fn invalid_operation(reason: &str, id: &str) -> RepairSimulationError {
    RepairSimulationError::InvalidOperation(format!("{reason}: {id}").into())
}

fn unknown_author_directive_candidate(
    input: &RepairSimulationInput<'_>,
    edit: &ProposedEdit,
    base_digest: GraphTruthDigest,
) -> Result<RepairCandidate, RepairSimulationError> {
    let claimed = edit
        .source_constraints
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let mut coverage = repair_coverage(input.original_report, &claimed, input.original_report);
    coverage.traversal_complete = false;
    coverage.complete_for_claimed_constraints = false;
    let remaining_violations = violation_classes(input.original_report)
        .into_keys()
        .collect::<Vec<_>>();
    let receipt = RepairValidationReceipt {
        schema: REPAIR_VALIDATION_SCHEMA.into(),
        candidate_digest: digest_edit(edit)?,
        base_generation: input.base.generation(),
        base_digest,
        overlay_digest: input.original_report.deterministic_receipt.mutation_digest,
        repaired_report_digest: GraphTruthDigest::default(),
        fixed_constraints: Vec::new(),
        remaining_violations: remaining_violations.clone(),
        introduced_violations: Vec::new(),
        introduced_hard_violations: Vec::new(),
        changed_intervals: Vec::new(),
        coverage,
        full_revalidation_completed: false,
        base_graph_unchanged: input.base.digest() == base_digest,
        no_truth_writes: true,
    };
    Ok(RepairCandidate {
        edit: edit.clone(),
        disposition: RepairDisposition::Unknown,
        fixed_constraints: Vec::new(),
        remaining_violations,
        introduced_violations: Vec::new(),
        validation_receipt: receipt,
    })
}

fn mutation_interval(
    base: &RevisionGraphSnapshot,
    mutation: &StoryMutation,
) -> Option<StoryInterval> {
    match mutation {
        StoryMutation::RetractFact { .. } => None,
        StoryMutation::SupersedeFact {
            fact_id,
            valid_from,
            ..
        } => Some(StoryInterval {
            valid_from: *valid_from,
            valid_to_exclusive: base
                .fact(fact_id)
                .and_then(|record| record.interval.valid_to_exclusive)
                .filter(|end| valid_from < end),
        }),
        StoryMutation::ShiftValidity { new_interval, .. } => Some(*new_interval),
        StoryMutation::ChangeState { valid_from, .. } => Some(StoryInterval {
            valid_from: *valid_from,
            valid_to_exclusive: None,
        }),
    }
}

fn base_interval(base: &RevisionGraphSnapshot, mutation: &StoryMutation) -> Option<StoryInterval> {
    match mutation {
        StoryMutation::RetractFact { fact_id }
        | StoryMutation::SupersedeFact { fact_id, .. }
        | StoryMutation::ShiftValidity { fact_id, .. } => {
            base.fact(fact_id).map(|record| record.interval)
        }
        StoryMutation::ChangeState {
            subject_id,
            state_kind,
            ..
        } => base
            .states()
            .iter()
            .find(|record| {
                record.state_ref.subject_id == *subject_id
                    && record.state_ref.state_kind == *state_kind
            })
            .map(|record| record.interval),
    }
}

fn coverage_requests(report: &RevisionImpactReport) -> Vec<SceneCoverageRequest> {
    report
        .authoritative_impacts
        .iter()
        .filter(|impact| !impact.coverage.required_planes.is_empty())
        .map(|impact| SceneCoverageRequest {
            scene_id: impact.scene_id.clone(),
            required_planes: impact.coverage.required_planes.clone(),
            unavailable_planes: impact.coverage.missing_required_planes.clone(),
        })
        .collect()
}

fn violation_classes(report: &RevisionImpactReport) -> BTreeMap<CompactString, DependencyClass> {
    report
        .authoritative_impacts
        .iter()
        .flat_map(|impact| {
            impact
                .violated_constraints
                .iter()
                .chain(&impact.support_loss_constraints)
        })
        .map(|constraint| {
            (
                constraint.constraint_id.clone(),
                constraint.dependency_class,
            )
        })
        .collect()
}

fn repair_coverage(
    original: &RevisionImpactReport,
    claimed: &BTreeSet<CompactString>,
    repaired: &RevisionImpactReport,
) -> RepairCoverageReceipt {
    let mut observed = BTreeSet::new();
    let mut required = Vec::new();
    let mut missing = Vec::new();
    let mut classification_supported = true;
    for impact in &original.authoritative_impacts {
        let matches_claim = impact
            .violated_constraints
            .iter()
            .chain(&impact.support_loss_constraints)
            .any(|constraint| claimed.contains(&constraint.constraint_id));
        if !matches_claim {
            continue;
        }
        observed.extend(
            impact
                .violated_constraints
                .iter()
                .chain(&impact.support_loss_constraints)
                .filter(|constraint| claimed.contains(&constraint.constraint_id))
                .map(|constraint| constraint.constraint_id.clone()),
        );
        required.extend(impact.coverage.required_planes.iter().copied());
        missing.extend(impact.coverage.missing_required_planes.iter().copied());
        classification_supported &= impact.coverage.classification_supported;
    }
    canonicalize_planes(&mut required);
    canonicalize_planes(&mut missing);
    let source_constraints_were_observed = observed == *claimed;
    let traversal_complete = !repaired.deterministic_receipt.ripple.truncation.truncated();
    RepairCoverageReceipt {
        required_planes: required,
        missing_required_planes: missing.clone(),
        source_constraints_were_observed,
        traversal_complete,
        complete_for_claimed_constraints: source_constraints_were_observed
            && classification_supported
            && missing.is_empty()
            && traversal_complete,
    }
}

fn classify_repair(
    fixed: usize,
    claimed: usize,
    claimed_remaining: usize,
    introduced: &[CompactString],
    introduced_hard: &[CompactString],
    coverage_complete: bool,
) -> RepairDisposition {
    if !introduced_hard.is_empty() || fixed == 0 {
        RepairDisposition::Rejected
    } else if !coverage_complete {
        RepairDisposition::Unknown
    } else if fixed == claimed && claimed_remaining == 0 && introduced.is_empty() {
        RepairDisposition::ProvenFix
    } else {
        RepairDisposition::PartialFix
    }
}

fn canonicalize_planes(planes: &mut Vec<CoveragePlane>) {
    planes.sort_unstable_by_key(|plane| coverage_rank(*plane));
    planes.dedup();
}

const fn coverage_rank(plane: CoveragePlane) -> u8 {
    match plane {
        CoveragePlane::Identity => 0,
        CoveragePlane::Temporal => 1,
        CoveragePlane::Belief => 2,
        CoveragePlane::Lifecycle => 3,
        CoveragePlane::Possession => 4,
        CoveragePlane::Location => 5,
        CoveragePlane::State => 6,
        CoveragePlane::Relationship => 7,
        CoveragePlane::Capability => 8,
        CoveragePlane::Causal => 9,
    }
}

fn digest_edit(edit: &ProposedEdit) -> Result<GraphTruthDigest, serde_json::Error> {
    let encoded = serde_json::to_vec(edit)?;
    Ok(GraphTruthDigest(*blake3::hash(&encoded).as_bytes()))
}

#[cfg(test)]
#[path = "repair_tests.rs"]
mod tests;
