use std::borrow::Cow;
use std::collections::BTreeSet;

use compact_str::CompactString;
use phoenix_semantic_v2::{
    CausalClaimStatus, CausalEdgeAddition, CausalEdgeId, CausalRelationKind, CausalScopeSidecar,
};
use phoenix_types::{
    BiTemporalWindow, CausalKind, ConstraintKind, CoveragePlane, EntityId, EventId, FactId,
    FactValue, Polarity, RepairTemplateKind, SceneId, SemanticNodeRef, StoryInterval,
    StoryMutation, StoryTime,
};
use serde::{Deserialize, Serialize};

use crate::repair_shadow::{build_shadow_snapshot, digest, validation_edit};
use crate::repair_simulation::simulate_repair_candidate_with_coverage;
use crate::{
    EvidenceRef, GraphEditOperation, ProposedEdit, RepairSimulationInput, RequirementDependency,
    RequirementTruthRef, RevisionEdgeRecord, RevisionFactRecord, RevisionRequirementRecord,
    RevisionRequirementSidecar, SceneCoverageRequest, SemanticDelta, ShadowOutcomeValidation,
    ShadowSemanticRepairError, ShadowSemanticRepairReceipt, ShadowSemanticRepairResult,
    SHADOW_SEMANTIC_REPAIR_SCHEMA,
};

pub const KAI_POWER_OVERDRAW_DIRECTIVE_ID: &str =
    "edit:split_power_rule_into_safe_limit_and_overdraw:kai";

const UNAIDED_SAFE_LIMIT_FACT: &str = "fact:kai_unaided_safe_step_limit";
const THIRD_STEP_OVERDRAW_FACT: &str = "fact:kai_third_step_is_overdraw";
const PHYSICAL_INJURY_FACT: &str = "fact:kai_third_step_physical_injury";
const UNCONSCIOUSNESS_FACT: &str = "fact:kai_third_step_unconsciousness";
const RECOVERY_REQUIRED_FACT: &str = "fact:kai_overdraw_requires_recovery";
const ARTIFACT_SAFE_LIMIT_FACT: &str = "fact:kai_artifact_safe_step_limit";

const OVERDRAW_CONSTRAINT: &str = "constraint:repair:power_limit:third_step_overdraw";
const INJURY_CONSTRAINT: &str = "constraint:repair:power_limit:physical_injury";
const UNCONSCIOUSNESS_CONSTRAINT: &str = "constraint:repair:power_limit:unconsciousness";
const TRAINING_THRESHOLD_CONSTRAINT: &str = "constraint:repair:power_limit:training_safe_threshold";
const RECOVERY_CONSTRAINT: &str = "constraint:repair:power_limit:recovery_required";
const ARTIFACT_LIMIT_CONSTRAINT: &str = "constraint:repair:power_limit:artifact_safe_three";

const OVERDRAW_EDGE: &str = "causal:repair:kai_unaided_third_step_overdraw";
const INJURY_EDGE: &str = "causal:repair:kai_overdraw_physical_injury";
const UNCONSCIOUSNESS_EDGE: &str = "causal:repair:kai_overdraw_unconsciousness";
const TRAINING_EDGE: &str = "causal:repair:kai_training_uses_safe_two";
const RECOVERY_EDGE: &str = "causal:repair:kai_recovery_before_normal_action";
const ARTIFACT_EDGE: &str = "causal:repair:artifact_safe_limit_three";
const ARTIFACT_SCENE: &str = "scene:chapter_12_artifact_amplification";

const ORIGINAL_CONSTRAINTS: [&str; 2] = [
    "constraint:power_limit:escape",
    "constraint:power_limit:training_support",
];
const TARGET_SCENES: [&str; 3] = [
    "scene:chapter_10_training_strategy",
    "scene:chapter_12_artifact_amplification",
    "scene:chapter_6_three_step_escape",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CapabilityMode {
    Unaided,
    ArtifactAssisted,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CapabilityCost {
    PhysicalInjury,
    Unconsciousness,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CapabilityRuleRecord {
    pub rule_id: CompactString,
    pub subject_id: EntityId,
    pub capability_id: CompactString,
    pub mode: CapabilityMode,
    pub safe_limit: u8,
    pub overdraw_limit: Option<u8>,
    pub assisted_by: Option<CompactString>,
    pub overdraw_costs: Vec<CapabilityCost>,
    pub requires_recovery: bool,
    pub valid_interval: StoryInterval,
    pub evidence_id: CompactString,
}

pub(crate) fn execute(
    input: RepairSimulationInput<'_>,
    edit: &ProposedEdit,
) -> Result<ShadowSemanticRepairResult, ShadowSemanticRepairError> {
    validate_contract(edit)?;
    let committed_base_digest = input.base.digest();
    let semantic_deltas = compile_deltas(input.requirements, input.base.generation().0)?;
    let compiled_delta_digest = digest(&semantic_deltas)?;

    let mut requirements = Cow::Borrowed(input.requirements);
    let causal_base = input
        .causal
        .ok_or(ShadowSemanticRepairError::MissingTruthPlane("causal"))?;
    let mut causal = Cow::Borrowed(causal_base);
    apply_capability_deltas(&semantic_deltas, requirements.to_mut(), causal.to_mut());
    let shadow_snapshot = build_shadow_snapshot(
        input.base,
        &semantic_deltas,
        compiled_delta_digest,
        KAI_POWER_OVERDRAW_DIRECTIVE_ID,
    )?;
    let validation_edit = validation_edit(edit, input.requirements, &ORIGINAL_CONSTRAINTS)?;
    let coverage_requests = coverage_after_capability_rebuild(&input)?;
    let mut candidate = simulate_repair_candidate_with_coverage(
        RepairSimulationInput {
            base: &shadow_snapshot,
            mutations: input.mutations,
            requirements: requirements.as_ref(),
            temporal: input.temporal,
            memory: input.memory,
            causal: Some(causal.as_ref()),
            original_report: input.original_report,
            author_locked_ids: input.author_locked_ids,
            ripple_config: input.ripple_config,
        },
        &validation_edit,
        Some(&coverage_requests),
    )?;
    candidate.edit = edit.clone();
    candidate.validation_receipt.candidate_digest = digest(edit)?;

    let outcomes = validate_outcomes(
        input.mutations,
        requirements.as_ref(),
        causal.as_ref(),
        &semantic_deltas,
        &candidate,
    );
    let all_outcomes_satisfied = outcomes.iter().all(|outcome| outcome.satisfied);
    if !all_outcomes_satisfied {
        candidate.disposition = crate::RepairDisposition::Unknown;
        candidate.validation_receipt.full_revalidation_completed = false;
        candidate
            .validation_receipt
            .coverage
            .complete_for_claimed_constraints = false;
    }
    let committed_base_unchanged = input.base.digest() == committed_base_digest;
    let no_truth_writes = committed_base_unchanged && candidate.validation_receipt.no_truth_writes;
    let receipt = ShadowSemanticRepairReceipt {
        schema: SHADOW_SEMANTIC_REPAIR_SCHEMA.into(),
        directive_id: KAI_POWER_OVERDRAW_DIRECTIVE_ID.into(),
        committed_base_digest,
        shadow_snapshot_digest: shadow_snapshot.digest(),
        compiled_delta_digest,
        shadow_sidecar_digest: compiled_delta_digest,
        removed_constraint_ids: ORIGINAL_CONSTRAINTS.map(CompactString::from).to_vec(),
        added_constraint_ids: [
            ARTIFACT_LIMIT_CONSTRAINT.into(),
            INJURY_CONSTRAINT.into(),
            OVERDRAW_CONSTRAINT.into(),
            RECOVERY_CONSTRAINT.into(),
            TRAINING_THRESHOLD_CONSTRAINT.into(),
            UNCONSCIOUSNESS_CONSTRAINT.into(),
        ]
        .to_vec(),
        rebuilt_planes: vec![CoveragePlane::Capability, CoveragePlane::Causal],
        copy_on_write_clones: 2,
        all_outcomes_satisfied,
        full_shadow_revalidation_completed: candidate
            .validation_receipt
            .full_revalidation_completed,
        committed_base_unchanged,
        no_truth_writes,
        outcomes,
        deterministic: true,
    };
    Ok(ShadowSemanticRepairResult {
        candidate,
        semantic_deltas,
        receipt,
    })
}

fn validate_contract(edit: &ProposedEdit) -> Result<(), ShadowSemanticRepairError> {
    if edit.edit_id.0.as_str() != KAI_POWER_OVERDRAW_DIRECTIVE_ID
        || edit.template != RepairTemplateKind::AddCostedCapabilityOverdraw
    {
        return Err(ShadowSemanticRepairError::UnsupportedDirective(
            edit.edit_id.0.clone(),
        ));
    }
    let operation_matches = matches!(
        edit.operations.as_slice(),
        [GraphEditOperation::ApplyAuthorDirective { directive_id, required_outcomes, .. }]
            if directive_id.as_str() == KAI_POWER_OVERDRAW_DIRECTIVE_ID
                && required_outcomes.len() == 4
    );
    let mut constraints = edit.source_constraints.clone();
    constraints.sort_unstable();
    let mut targets = edit.target_ids.clone();
    targets.sort_unstable();
    if !operation_matches
        || constraints != ORIGINAL_CONSTRAINTS.map(CompactString::from)
        || targets != TARGET_SCENES.map(CompactString::from)
        || !edit.preserves_mutation
    {
        return Err(ShadowSemanticRepairError::MalformedDirective(
            edit.edit_id.0.clone(),
        ));
    }
    Ok(())
}

fn compile_deltas(
    requirements: &RevisionRequirementSidecar,
    generation: u64,
) -> Result<Vec<SemanticDelta>, ShadowSemanticRepairError> {
    for constraint_id in ORIGINAL_CONSTRAINTS {
        if !requirements
            .requirements
            .iter()
            .any(|row| row.constraint_id == constraint_id)
        {
            return Err(ShadowSemanticRepairError::MissingConstraint(
                constraint_id.into(),
            ));
        }
    }
    let mut deltas = ORIGINAL_CONSTRAINTS
        .into_iter()
        .map(|constraint_id| SemanticDelta::RemoveRequirement {
            constraint_id: constraint_id.into(),
        })
        .collect::<Vec<_>>();
    deltas.extend(
        [
            fact(UNAIDED_SAFE_LIMIT_FACT, FactValue::Integer(2), 300),
            fact(THIRD_STEP_OVERDRAW_FACT, FactValue::Boolean(true), 600),
            fact(PHYSICAL_INJURY_FACT, FactValue::Boolean(true), 600),
            fact(UNCONSCIOUSNESS_FACT, FactValue::Boolean(true), 600),
            fact(RECOVERY_REQUIRED_FACT, FactValue::Boolean(true), 600),
            fact(ARTIFACT_SAFE_LIMIT_FACT, FactValue::Integer(3), 1200),
        ]
        .into_iter()
        .map(|record| SemanticDelta::AddFact { record }),
    );
    let replacements = replacement_records(generation);
    deltas.extend(
        replacements
            .edges
            .iter()
            .cloned()
            .map(|record| SemanticDelta::AddGraphEdge { record }),
    );
    deltas.extend(
        replacements
            .requirements
            .iter()
            .cloned()
            .map(|record| SemanticDelta::AddRequirement { record }),
    );
    deltas.extend(
        replacements
            .causal_edges
            .into_iter()
            .map(|record| SemanticDelta::AddCausalEdge { record }),
    );
    deltas.extend(
        capability_rules()
            .into_iter()
            .map(|record| SemanticDelta::AddCapabilityRule { record }),
    );
    deltas.push(SemanticDelta::AssertFactSupersession {
        fact_id: FactId("fact:kai_temporal_step_limit".into()),
        replacement: FactValue::Integer(2),
        valid_from: StoryTime(300),
    });
    deltas.push(SemanticDelta::ResolveCoverageRequirement {
        scene_id: SceneId(ARTIFACT_SCENE.into()),
        removed_required_planes: vec![CoveragePlane::Capability],
        rationale: "Typed unaided and artifact-assisted capability rules are present".into(),
    });
    Ok(deltas)
}

struct ReplacementRecords {
    requirements: [RevisionRequirementRecord; 6],
    edges: [RevisionEdgeRecord; 6],
    causal_edges: [CausalEdgeAddition; 6],
}

fn replacement_records(generation: u64) -> ReplacementRecords {
    let specs = [
        (
            OVERDRAW_CONSTRAINT,
            THIRD_STEP_OVERDRAW_FACT,
            "scene:chapter_6_three_step_escape",
            600,
            OVERDRAW_EDGE,
            "event:kai_attempts_unaided_third_step",
            CausalKind::ResultsIn,
        ),
        (
            INJURY_CONSTRAINT,
            PHYSICAL_INJURY_FACT,
            "scene:chapter_6_three_step_escape",
            600,
            INJURY_EDGE,
            "event:kai_unaided_third_step_overdraw",
            CausalKind::ResultsIn,
        ),
        (
            UNCONSCIOUSNESS_CONSTRAINT,
            UNCONSCIOUSNESS_FACT,
            "scene:chapter_6_three_step_escape",
            600,
            UNCONSCIOUSNESS_EDGE,
            "event:kai_unaided_third_step_overdraw",
            CausalKind::ResultsIn,
        ),
        (
            TRAINING_THRESHOLD_CONSTRAINT,
            UNAIDED_SAFE_LIMIT_FACT,
            "scene:chapter_10_training_strategy",
            1000,
            TRAINING_EDGE,
            "event:kai_trains_below_safe_limit_two",
            CausalKind::ConditionFor,
        ),
        (
            RECOVERY_CONSTRAINT,
            RECOVERY_REQUIRED_FACT,
            "scene:chapter_10_training_strategy",
            1000,
            RECOVERY_EDGE,
            "event:kai_recovers_after_overdraw",
            CausalKind::ConditionFor,
        ),
        (
            ARTIFACT_LIMIT_CONSTRAINT,
            ARTIFACT_SAFE_LIMIT_FACT,
            ARTIFACT_SCENE,
            1200,
            ARTIFACT_EDGE,
            "event:kai_uses_limit_raising_artifact",
            CausalKind::Enables,
        ),
    ];
    let requirements = specs.map(|(constraint, fact, scene, time, edge, _, _)| {
        requirement(constraint, fact, scene, time, edge)
    });
    let edges = requirements.each_ref().map(graph_edge);
    let causal_edges = specs.map(|(constraint, _, scene, time, edge, source_event, kind)| {
        causal_edge(
            edge,
            source_event,
            scene,
            constraint,
            kind,
            time,
            generation,
        )
    });
    ReplacementRecords {
        requirements,
        edges,
        causal_edges,
    }
}

fn capability_rules() -> [CapabilityRuleRecord; 2] {
    [
        CapabilityRuleRecord {
            rule_id: "capability-rule:kai:temporal-step:unaided".into(),
            subject_id: EntityId("entity:kai".to_owned()),
            capability_id: "capability:temporal-step".into(),
            mode: CapabilityMode::Unaided,
            safe_limit: 2,
            overdraw_limit: Some(3),
            assisted_by: None,
            overdraw_costs: vec![
                CapabilityCost::PhysicalInjury,
                CapabilityCost::Unconsciousness,
            ],
            requires_recovery: true,
            valid_interval: interval_from(StoryTime(300)),
            evidence_id: author_evidence(OVERDRAW_CONSTRAINT).into(),
        },
        CapabilityRuleRecord {
            rule_id: "capability-rule:kai:temporal-step:artifact".into(),
            subject_id: EntityId("entity:kai".to_owned()),
            capability_id: "capability:temporal-step".into(),
            mode: CapabilityMode::ArtifactAssisted,
            safe_limit: 3,
            overdraw_limit: None,
            assisted_by: Some("artifact:temporal-amplifier".into()),
            overdraw_costs: Vec::new(),
            requires_recovery: false,
            valid_interval: StoryInterval {
                valid_from: StoryTime(1200),
                valid_to_exclusive: Some(StoryTime(1201)),
            },
            evidence_id: author_evidence(ARTIFACT_LIMIT_CONSTRAINT).into(),
        },
    ]
}

fn fact(fact_id: &str, value: FactValue, valid_from: i64) -> RevisionFactRecord {
    RevisionFactRecord {
        fact_id: FactId(fact_id.into()),
        value,
        interval: interval_from(StoryTime(valid_from)),
    }
}

fn requirement(
    constraint_id: &str,
    fact_id: &str,
    scene_id: &str,
    story_time: i64,
    edge_id: &str,
) -> RevisionRequirementRecord {
    RevisionRequirementRecord {
        constraint_id: constraint_id.into(),
        dependency: RequirementDependency::Fact {
            fact_id: FactId(fact_id.into()),
        },
        expected_value: if fact_id.ends_with("limit") {
            FactValue::Integer(if fact_id == ARTIFACT_SAFE_LIMIT_FACT {
                3
            } else {
                2
            })
        } else {
            FactValue::Boolean(true)
        },
        dependent_scene_id: SceneId(scene_id.into()),
        kind: ConstraintKind::CausalSupport,
        valid_interval: StoryInterval {
            valid_from: StoryTime(story_time),
            valid_to_exclusive: Some(StoryTime(story_time + 1)),
        },
        truth_ref: RequirementTruthRef::CausalEdge {
            edge_id: edge_id.into(),
        },
        evidence: vec![EvidenceRef::anchored(author_evidence(constraint_id))],
        confidence_millis: 1000,
    }
}

fn graph_edge(requirement: &RevisionRequirementRecord) -> RevisionEdgeRecord {
    let RequirementDependency::Fact { fact_id } = &requirement.dependency else {
        unreachable!("capability replacement dependencies are facts")
    };
    RevisionEdgeRecord {
        edge_id: requirement.constraint_id.clone(),
        dependency_fact_ids: vec![fact_id.clone()],
        dependency_state_refs: Vec::new(),
    }
}

#[allow(clippy::too_many_arguments)]
fn causal_edge(
    edge_id: &str,
    source_event: &str,
    target_event: &str,
    constraint_id: &str,
    kind: CausalKind,
    valid_from: i64,
    generation: u64,
) -> CausalEdgeAddition {
    CausalEdgeAddition {
        edge_id: CausalEdgeId(edge_id.to_owned()),
        case_id: KAI_POWER_OVERDRAW_DIRECTIVE_ID.to_owned(),
        document_id: KAI_POWER_OVERDRAW_DIRECTIVE_ID.to_owned(),
        source: SemanticNodeRef::Event(EventId(source_event.to_owned())),
        canonical_cause_event_id: None,
        target: SemanticNodeRef::Event(EventId(target_event.to_owned())),
        canonical_effect_event_id: None,
        kind,
        relation_kind: CausalRelationKind::EnablingCondition,
        status: CausalClaimStatus::Active,
        first_seen_revision: generation,
        latest_decision_id: None,
        confidence_millis: 1000,
        cue: Some("author-confirmed costed capability overdraw".to_owned()),
        attributed_to: Some(EntityId("entity:kai".to_owned())),
        polarity: Polarity::Positive,
        claim_atom_ids: Vec::new(),
        evidence_refs: vec![author_evidence(constraint_id)],
        effective_interval: window_from(valid_from),
        observation_interval: window_from(valid_from),
        temporal_certainty_millis: 1000,
        created_at: 1_784_295_149,
    }
}

fn apply_capability_deltas(
    deltas: &[SemanticDelta],
    requirements: &mut RevisionRequirementSidecar,
    causal: &mut CausalScopeSidecar,
) {
    for delta in deltas {
        match delta {
            SemanticDelta::AddRequirement { record } => {
                requirements.requirements.push(record.clone());
            }
            SemanticDelta::AddCausalEdge { record } => causal.edge_records.push(record.clone()),
            _ => {}
        }
    }
    requirements
        .requirements
        .sort_unstable_by(|left, right| left.constraint_id.cmp(&right.constraint_id));
    causal
        .edge_records
        .sort_unstable_by(|left, right| left.edge_id.0.cmp(&right.edge_id.0));
}

fn author_evidence(constraint_id: &str) -> String {
    format!("author-directive:{constraint_id}")
}

fn interval_from(valid_from: StoryTime) -> StoryInterval {
    StoryInterval {
        valid_from,
        valid_to_exclusive: None,
    }
}

fn window_from(valid_from: i64) -> BiTemporalWindow {
    BiTemporalWindow {
        valid_from: Some(valid_from),
        valid_to: None,
        recorded_from: Some(0),
        recorded_to: None,
    }
}

fn coverage_after_capability_rebuild(
    input: &RepairSimulationInput<'_>,
) -> Result<Vec<SceneCoverageRequest>, ShadowSemanticRepairError> {
    let artifact = input
        .original_report
        .authoritative_impacts
        .iter()
        .find(|impact| impact.scene_id.0 == ARTIFACT_SCENE)
        .ok_or_else(|| ShadowSemanticRepairError::MalformedDirective(ARTIFACT_SCENE.into()))?;
    if !artifact
        .coverage
        .missing_required_planes
        .contains(&CoveragePlane::Capability)
    {
        return Err(ShadowSemanticRepairError::MalformedDirective(
            ARTIFACT_SCENE.into(),
        ));
    }
    Ok(input
        .original_report
        .authoritative_impacts
        .iter()
        .filter(|impact| impact.scene_id.0 != ARTIFACT_SCENE)
        .filter(|impact| !impact.coverage.required_planes.is_empty())
        .map(|impact| SceneCoverageRequest {
            scene_id: impact.scene_id.clone(),
            required_planes: impact.coverage.required_planes.clone(),
            unavailable_planes: impact.coverage.missing_required_planes.clone(),
        })
        .collect())
}

fn validate_outcomes(
    mutations: &[StoryMutation],
    requirements: &RevisionRequirementSidecar,
    causal: &CausalScopeSidecar,
    deltas: &[SemanticDelta],
    candidate: &crate::RepairCandidate,
) -> Vec<ShadowOutcomeValidation> {
    let rules = deltas
        .iter()
        .filter_map(|delta| match delta {
            SemanticDelta::AddCapabilityRule { record } => Some(record),
            _ => None,
        })
        .collect::<Vec<_>>();
    let unaided = rules
        .iter()
        .find(|rule| rule.mode == CapabilityMode::Unaided);
    let artifact = rules
        .iter()
        .find(|rule| rule.mode == CapabilityMode::ArtifactAssisted);
    let added = requirements
        .requirements
        .iter()
        .map(|row| row.constraint_id.as_str())
        .collect::<BTreeSet<_>>();
    let edge_ids = causal
        .edge_records
        .iter()
        .map(|edge| edge.edge_id.0.as_str())
        .collect::<BTreeSet<_>>();
    let mutation = mutations.iter().any(|mutation| {
        matches!(
            mutation,
            StoryMutation::SupersedeFact {
                fact_id,
                replacement: FactValue::Integer(2),
                valid_from,
            } if fact_id.0 == "fact:kai_temporal_step_limit"
                && *valid_from == StoryTime(300)
        )
    });
    let fixed = candidate
        .fixed_constraints
        .iter()
        .map(CompactString::as_str)
        .collect::<BTreeSet<_>>();
    vec![
        outcome(
            "unaided_safe_limit_is_exactly_two",
            mutation
                && unaided.is_some_and(|rule| {
                    rule.safe_limit == 2
                        && rule.overdraw_limit == Some(3)
                        && rule.assisted_by.is_none()
                })
                && ORIGINAL_CONSTRAINTS
                    .iter()
                    .all(|constraint| fixed.contains(constraint)),
            &["capability-rule:kai:temporal-step:unaided".into()],
        ),
        outcome(
            "unaided_third_step_is_costed_overdraw",
            unaided.is_some_and(|rule| {
                rule.overdraw_costs
                    == [
                        CapabilityCost::PhysicalInjury,
                        CapabilityCost::Unconsciousness,
                    ]
            }) && edge_ids.contains(OVERDRAW_EDGE)
                && added.contains(OVERDRAW_CONSTRAINT),
            &[OVERDRAW_EDGE.into()],
        ),
        outcome(
            "overdraw_causes_injury_and_unconsciousness",
            edge_ids.contains(INJURY_EDGE)
                && edge_ids.contains(UNCONSCIOUSNESS_EDGE)
                && added.contains(INJURY_CONSTRAINT)
                && added.contains(UNCONSCIOUSNESS_CONSTRAINT),
            &[INJURY_EDGE.into(), UNCONSCIOUSNESS_EDGE.into()],
        ),
        outcome(
            "recovery_required_before_normal_action",
            unaided.is_some_and(|rule| rule.requires_recovery)
                && edge_ids.contains(RECOVERY_EDGE)
                && added.contains(RECOVERY_CONSTRAINT)
                && added.contains(TRAINING_THRESHOLD_CONSTRAINT),
            &[RECOVERY_EDGE.into()],
        ),
        outcome(
            "artifact_safe_limit_is_exactly_three",
            artifact.is_some_and(|rule| {
                rule.safe_limit == 3
                    && rule.overdraw_limit.is_none()
                    && rule.assisted_by.as_deref() == Some("artifact:temporal-amplifier")
                    && rule.valid_interval.valid_from == StoryTime(1200)
            }) && edge_ids.contains(ARTIFACT_EDGE)
                && added.contains(ARTIFACT_LIMIT_CONSTRAINT),
            &["capability-rule:kai:temporal-step:artifact".into()],
        ),
    ]
}

fn outcome(
    outcome_id: &str,
    satisfied: bool,
    evidence_ids: &[CompactString],
) -> ShadowOutcomeValidation {
    ShadowOutcomeValidation {
        outcome_id: outcome_id.into(),
        satisfied,
        evidence_ids: evidence_ids.to_vec(),
    }
}

#[cfg(test)]
#[path = "repair_shadow_capability_tests.rs"]
mod tests;
