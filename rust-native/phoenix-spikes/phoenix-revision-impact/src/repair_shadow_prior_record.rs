use std::borrow::Cow;
use std::collections::BTreeSet;

use compact_str::CompactString;
use phoenix_semantic_v2::{
    BeliefSourceKind, BeliefStateAtom, BeliefStateKind, CausalClaimStatus, CausalEdgeAddition,
    CausalEdgeId, CausalRelationKind, CausalScopeSidecar, TemporalScopeSidecar,
    TemporalTruthStatus,
};
use phoenix_types::{
    BiTemporalWindow, CausalKind, ConstraintKind, CoveragePlane, EntityId, EventId, FactId,
    FactValue, Polarity, RepairTemplateKind, SceneId, SemanticNodeRef, StoryInterval,
    StoryMutation, StoryTime,
};

use crate::repair_shadow::{apply_sidecar_deltas, build_shadow_snapshot, digest, validation_edit};
use crate::repair_simulation::simulate_repair_candidate_with_coverage;
use crate::{
    EvidenceRef, GraphEditOperation, ProposedEdit, RepairSimulationInput, RequirementDependency,
    RequirementTruthRef, RevisionEdgeRecord, RevisionFactRecord, RevisionRequirementRecord,
    RevisionRequirementSidecar, SceneCoverageRequest, SemanticDelta, ShadowOutcomeValidation,
    ShadowSemanticRepairError, ShadowSemanticRepairReceipt, ShadowSemanticRepairResult,
    SHADOW_SEMANTIC_REPAIR_SCHEMA,
};

pub const MARA_PRIOR_RECORD_DIRECTIVE_ID: &str = "edit:rebind_warning_to_prerecorded_message:mara";

const RECORDING_FACT: &str = "fact:mara_prerecorded_warning_exists";
const PRIOR_PLAN_FACT: &str = "fact:mara_prior_plan_remains_actionable";
const FALSE_RUMOR_FACT: &str = "fact:mara_resurrection_rumor_is_false";
const RECORDING_KNOWLEDGE_CONSTRAINT: &str =
    "constraint:repair:earlier_death:kai_receives_recording";
const RECORDING_DELIVERY_CONSTRAINT: &str = "constraint:repair:earlier_death:recording_delivery";
const PRIOR_PLAN_CONSTRAINT: &str = "constraint:repair:earlier_death:prior_plan_support";
const FALSE_RUMOR_CONSTRAINT: &str = "constraint:repair:earlier_death:false_resurrection_rumor";
const RECORDING_BELIEF: &str = "belief:repair:kai_receives_mara_recording";
const FALSE_RUMOR_BELIEF: &str = "belief:repair:mara_resurrection_rumor_contradicted";
const RECORDING_EDGE: &str = "causal:repair:mara_recording_delivery";
const PRIOR_PLAN_EDGE: &str = "causal:repair:mara_prior_plan";
const FALSE_RUMOR_EDGE: &str = "causal:repair:mara_false_resurrection_rumor";
const RUMOR_SCENE: &str = "scene:chapter_12_resurrection_rumor";

const ORIGINAL_CONSTRAINTS: [&str; 2] = [
    "constraint:earlier_death:faction_support",
    "constraint:earlier_death:mara_alive",
];
const TARGET_SCENES: [&str; 3] = [
    "scene:chapter_11_faction_response",
    "scene:chapter_12_resurrection_rumor",
    "scene:chapter_9_mara_warning",
];

pub(crate) fn execute(
    input: RepairSimulationInput<'_>,
    edit: &ProposedEdit,
) -> Result<ShadowSemanticRepairResult, ShadowSemanticRepairError> {
    validate_contract(edit)?;
    let committed_base_digest = input.base.digest();
    let semantic_deltas = compile_deltas(input.requirements, input.base.generation().0)?;
    let compiled_delta_digest = digest(&semantic_deltas)?;

    let mut requirements = Cow::Borrowed(input.requirements);
    let temporal_base = input
        .temporal
        .ok_or(ShadowSemanticRepairError::MissingTruthPlane("belief"))?;
    let causal_base = input
        .causal
        .ok_or(ShadowSemanticRepairError::MissingTruthPlane("causal"))?;
    let mut temporal = Cow::Borrowed(temporal_base);
    let mut causal = Cow::Borrowed(causal_base);
    apply_sidecar_deltas(
        &semantic_deltas,
        requirements.to_mut(),
        temporal.to_mut(),
        causal.to_mut(),
    );

    let shadow_snapshot = build_shadow_snapshot(
        input.base,
        &semantic_deltas,
        compiled_delta_digest,
        MARA_PRIOR_RECORD_DIRECTIVE_ID,
    )?;
    let validation_edit = validation_edit(edit, input.requirements, &ORIGINAL_CONSTRAINTS)?;
    let coverage_requests = coverage_after_false_rumor_retyping(&input)?;
    let mut candidate = simulate_repair_candidate_with_coverage(
        RepairSimulationInput {
            base: &shadow_snapshot,
            mutations: input.mutations,
            requirements: requirements.as_ref(),
            temporal: Some(temporal.as_ref()),
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
        temporal.as_ref(),
        causal.as_ref(),
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
        directive_id: MARA_PRIOR_RECORD_DIRECTIVE_ID.into(),
        committed_base_digest,
        shadow_snapshot_digest: shadow_snapshot.digest(),
        compiled_delta_digest,
        shadow_sidecar_digest: compiled_delta_digest,
        removed_constraint_ids: ORIGINAL_CONSTRAINTS.map(CompactString::from).to_vec(),
        added_constraint_ids: [
            FALSE_RUMOR_CONSTRAINT.into(),
            PRIOR_PLAN_CONSTRAINT.into(),
            RECORDING_DELIVERY_CONSTRAINT.into(),
            RECORDING_KNOWLEDGE_CONSTRAINT.into(),
        ]
        .to_vec(),
        rebuilt_planes: vec![CoveragePlane::Belief, CoveragePlane::Causal],
        copy_on_write_clones: 3,
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
    if edit.edit_id.0.as_str() != MARA_PRIOR_RECORD_DIRECTIVE_ID
        || edit.template != RepairTemplateKind::RebindActionToPriorRecord
    {
        return Err(ShadowSemanticRepairError::UnsupportedDirective(
            edit.edit_id.0.clone(),
        ));
    }
    let operation_matches = matches!(
        edit.operations.as_slice(),
        [GraphEditOperation::ApplyAuthorDirective { directive_id, required_outcomes, .. }]
            if directive_id.as_str() == MARA_PRIOR_RECORD_DIRECTIVE_ID
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
            fact(RECORDING_FACT, 650),
            fact(PRIOR_PLAN_FACT, 0),
            fact(FALSE_RUMOR_FACT, 700),
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
            .beliefs
            .into_iter()
            .map(|record| SemanticDelta::AddBeliefAtom { record }),
    );
    deltas.extend(
        replacements
            .causal_edges
            .into_iter()
            .map(|record| SemanticDelta::AddCausalEdge { record }),
    );
    deltas.push(SemanticDelta::AssertStateBoundary {
        subject_id: EntityId("entity:mara".to_owned()),
        state_kind: "alive".into(),
        replacement: FactValue::Boolean(false),
        valid_from: StoryTime(700),
    });
    deltas.push(SemanticDelta::ResolveCoverageRequirement {
        scene_id: SceneId(RUMOR_SCENE.into()),
        removed_required_planes: vec![CoveragePlane::Lifecycle, CoveragePlane::Capability],
        rationale: "The scene is an attributed false rumor, not a resurrection event".into(),
    });
    Ok(deltas)
}

struct ReplacementRecords {
    requirements: [RevisionRequirementRecord; 4],
    edges: [RevisionEdgeRecord; 4],
    beliefs: [BeliefStateAtom; 2],
    causal_edges: [CausalEdgeAddition; 3],
}

fn replacement_records(generation: u64) -> ReplacementRecords {
    let recording_knowledge = requirement(
        RECORDING_KNOWLEDGE_CONSTRAINT,
        RECORDING_FACT,
        "scene:chapter_9_mara_warning",
        ConstraintKind::RequiresKnowledge,
        900,
        RequirementTruthRef::Belief {
            belief_id: RECORDING_BELIEF.into(),
        },
    );
    let recording_delivery = requirement(
        RECORDING_DELIVERY_CONSTRAINT,
        RECORDING_FACT,
        "scene:chapter_9_mara_warning",
        ConstraintKind::CausalSupport,
        900,
        RequirementTruthRef::CausalEdge {
            edge_id: RECORDING_EDGE.into(),
        },
    );
    let prior_plan = requirement(
        PRIOR_PLAN_CONSTRAINT,
        PRIOR_PLAN_FACT,
        "scene:chapter_11_faction_response",
        ConstraintKind::CausalSupport,
        1100,
        RequirementTruthRef::CausalEdge {
            edge_id: PRIOR_PLAN_EDGE.into(),
        },
    );
    let false_rumor = requirement(
        FALSE_RUMOR_CONSTRAINT,
        FALSE_RUMOR_FACT,
        RUMOR_SCENE,
        ConstraintKind::CausalSupport,
        1200,
        RequirementTruthRef::CausalEdge {
            edge_id: FALSE_RUMOR_EDGE.into(),
        },
    );
    let requirements = [
        recording_knowledge,
        recording_delivery,
        prior_plan,
        false_rumor,
    ];
    let edges = requirements.each_ref().map(graph_edge);
    ReplacementRecords {
        requirements,
        edges,
        beliefs: [recording_belief(), false_rumor_belief()],
        causal_edges: [
            causal_edge(
                RECORDING_EDGE,
                "event:mara_records_warning_before_death",
                "scene:chapter_9_mara_warning",
                "entity:mara",
                RECORDING_DELIVERY_CONSTRAINT,
                650,
                generation,
            ),
            causal_edge(
                PRIOR_PLAN_EDGE,
                "event:mara_sets_faction_contingency_before_death",
                "scene:chapter_11_faction_response",
                "entity:mara",
                PRIOR_PLAN_CONSTRAINT,
                650,
                generation,
            ),
            causal_edge(
                FALSE_RUMOR_EDGE,
                "event:ambiguous_evidence_surrounding_mara_death",
                RUMOR_SCENE,
                "entity:rumor_network",
                FALSE_RUMOR_CONSTRAINT,
                700,
                generation,
            ),
        ],
    }
}

fn fact(fact_id: &str, valid_from: i64) -> RevisionFactRecord {
    RevisionFactRecord {
        fact_id: FactId(fact_id.into()),
        value: FactValue::Boolean(true),
        interval: StoryInterval {
            valid_from: StoryTime(valid_from),
            valid_to_exclusive: None,
        },
    }
}

fn requirement(
    constraint_id: &str,
    fact_id: &str,
    scene_id: &str,
    kind: ConstraintKind,
    story_time: i64,
    truth_ref: RequirementTruthRef,
) -> RevisionRequirementRecord {
    RevisionRequirementRecord {
        constraint_id: constraint_id.into(),
        dependency: RequirementDependency::Fact {
            fact_id: FactId(fact_id.into()),
        },
        expected_value: FactValue::Boolean(true),
        dependent_scene_id: SceneId(scene_id.into()),
        kind,
        valid_interval: StoryInterval {
            valid_from: StoryTime(story_time),
            valid_to_exclusive: Some(StoryTime(story_time + 1)),
        },
        truth_ref,
        evidence: vec![EvidenceRef::anchored(author_evidence(constraint_id))],
        confidence_millis: 1000,
    }
}

fn graph_edge(requirement: &RevisionRequirementRecord) -> RevisionEdgeRecord {
    let RequirementDependency::Fact { fact_id } = &requirement.dependency else {
        unreachable!("prior-record replacement dependencies are facts")
    };
    RevisionEdgeRecord {
        edge_id: requirement.constraint_id.clone(),
        dependency_fact_ids: vec![fact_id.clone()],
        dependency_state_refs: Vec::new(),
    }
}

fn recording_belief() -> BeliefStateAtom {
    BeliefStateAtom {
        belief_id: RECORDING_BELIEF.to_owned(),
        document_id: MARA_PRIOR_RECORD_DIRECTIVE_ID.to_owned(),
        proposition_id: Some(RECORDING_FACT.to_owned()),
        observer_entity_id: Some(EntityId("entity:kai".to_owned())),
        subject_entity_id: Some(EntityId("entity:mara_recording".to_owned())),
        kind: BeliefStateKind::Knows,
        truth_status: TemporalTruthStatus::Observed,
        source_kind: BeliefSourceKind::DirectObservation,
        label: "Kai receives Mara's prerecorded warning".to_owned(),
        confidence_millis: 1000,
        temporal: window_from(900),
        evidence_refs: vec![author_evidence(RECORDING_KNOWLEDGE_CONSTRAINT)],
        ..BeliefStateAtom::default()
    }
}

fn false_rumor_belief() -> BeliefStateAtom {
    BeliefStateAtom {
        belief_id: FALSE_RUMOR_BELIEF.to_owned(),
        document_id: MARA_PRIOR_RECORD_DIRECTIVE_ID.to_owned(),
        proposition_id: Some(FALSE_RUMOR_FACT.to_owned()),
        observer_entity_id: Some(EntityId("entity:rumor_network".to_owned())),
        subject_entity_id: Some(EntityId("entity:mara".to_owned())),
        kind: BeliefStateKind::Reported,
        truth_status: TemporalTruthStatus::Contradicted,
        source_kind: BeliefSourceKind::Attribution,
        label: "Attributed resurrection rumor contradicted by story truth".to_owned(),
        confidence_millis: 1000,
        temporal: window_from(1200),
        evidence_refs: vec![author_evidence(FALSE_RUMOR_CONSTRAINT)],
        ..BeliefStateAtom::default()
    }
}

fn causal_edge(
    edge_id: &str,
    source_event: &str,
    target_event: &str,
    attributed_to: &str,
    constraint_id: &str,
    valid_from: i64,
    generation: u64,
) -> CausalEdgeAddition {
    CausalEdgeAddition {
        edge_id: CausalEdgeId(edge_id.to_owned()),
        case_id: MARA_PRIOR_RECORD_DIRECTIVE_ID.to_owned(),
        document_id: MARA_PRIOR_RECORD_DIRECTIVE_ID.to_owned(),
        source: SemanticNodeRef::Event(EventId(source_event.to_owned())),
        canonical_cause_event_id: None,
        target: SemanticNodeRef::Event(EventId(target_event.to_owned())),
        canonical_effect_event_id: None,
        kind: CausalKind::Enables,
        relation_kind: CausalRelationKind::EnablingCondition,
        status: CausalClaimStatus::Active,
        first_seen_revision: generation,
        latest_decision_id: None,
        confidence_millis: 1000,
        cue: Some("author-confirmed shadow repair".to_owned()),
        attributed_to: Some(EntityId(attributed_to.to_owned())),
        polarity: Polarity::Positive,
        claim_atom_ids: Vec::new(),
        evidence_refs: vec![author_evidence(constraint_id)],
        effective_interval: window_from(valid_from),
        observation_interval: window_from(valid_from),
        temporal_certainty_millis: 1000,
        created_at: 1_784_295_149,
    }
}

fn author_evidence(constraint_id: &str) -> String {
    format!("author-directive:{constraint_id}")
}

fn window_from(valid_from: i64) -> BiTemporalWindow {
    BiTemporalWindow {
        valid_from: Some(valid_from),
        valid_to: None,
        recorded_from: Some(0),
        recorded_to: None,
    }
}

fn coverage_after_false_rumor_retyping(
    input: &RepairSimulationInput<'_>,
) -> Result<Vec<SceneCoverageRequest>, ShadowSemanticRepairError> {
    let rumor = input
        .original_report
        .authoritative_impacts
        .iter()
        .find(|impact| impact.scene_id.0 == RUMOR_SCENE)
        .ok_or_else(|| ShadowSemanticRepairError::MalformedDirective(RUMOR_SCENE.into()))?;
    if !rumor
        .coverage
        .missing_required_planes
        .contains(&CoveragePlane::Capability)
    {
        return Err(ShadowSemanticRepairError::MalformedDirective(
            RUMOR_SCENE.into(),
        ));
    }
    Ok(input
        .original_report
        .authoritative_impacts
        .iter()
        .filter(|impact| impact.scene_id.0 != RUMOR_SCENE)
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
    temporal: &TemporalScopeSidecar,
    causal: &CausalScopeSidecar,
    candidate: &crate::RepairCandidate,
) -> Vec<ShadowOutcomeValidation> {
    let fixed = candidate
        .fixed_constraints
        .iter()
        .map(CompactString::as_str)
        .collect::<BTreeSet<_>>();
    let added = requirements
        .requirements
        .iter()
        .map(|row| row.constraint_id.as_str())
        .collect::<BTreeSet<_>>();
    let death_boundary = mutations.iter().any(|mutation| {
        matches!(
            mutation,
            StoryMutation::ChangeState {
                subject_id,
                state_kind,
                replacement: FactValue::Boolean(false),
                valid_from,
            } if subject_id.0 == "entity:mara"
                && state_kind.0 == "alive"
                && *valid_from == StoryTime(700)
        )
    });
    let recording = causal.edge_records.iter().find(|edge| {
        edge.edge_id.0 == RECORDING_EDGE
            && edge
                .effective_interval
                .valid_from
                .is_some_and(|time| time < 700)
    });
    let delivery = temporal.belief_atoms.iter().find(|belief| {
        belief.belief_id == RECORDING_BELIEF
            && belief
                .observer_entity_id
                .as_ref()
                .is_some_and(|id| id.0 == "entity:kai")
            && belief.truth_status == TemporalTruthStatus::Observed
    });
    let prior_plan = causal
        .edge_records
        .iter()
        .find(|edge| edge.edge_id.0 == PRIOR_PLAN_EDGE);
    let false_rumor = temporal.belief_atoms.iter().find(|belief| {
        belief.belief_id == FALSE_RUMOR_BELIEF
            && belief.kind == BeliefStateKind::Reported
            && belief.truth_status == TemporalTruthStatus::Contradicted
            && belief
                .observer_entity_id
                .as_ref()
                .is_some_and(|id| id.0 != "entity:mara")
    });
    let rumor_cause = causal
        .edge_records
        .iter()
        .find(|edge| edge.edge_id.0 == FALSE_RUMOR_EDGE);
    let old_constraints_fixed = ORIGINAL_CONSTRAINTS
        .iter()
        .all(|constraint| fixed.contains(constraint));
    vec![
        outcome(
            "mara_definitively_dead_at_700",
            death_boundary && old_constraints_fixed,
            &["state:entity:mara:alive".into()],
        ),
        outcome(
            "recording_created_before_death",
            recording.is_some(),
            &[RECORDING_EDGE.into()],
        ),
        outcome(
            "chapter_nine_uses_recording_delivery",
            delivery.is_some()
                && added.contains(RECORDING_KNOWLEDGE_CONSTRAINT)
                && added.contains(RECORDING_DELIVERY_CONSTRAINT),
            &[RECORDING_BELIEF.into(), RECORDING_EDGE.into()],
        ),
        outcome(
            "faction_response_uses_prior_plan",
            prior_plan.is_some() && added.contains(PRIOR_PLAN_CONSTRAINT),
            &[PRIOR_PLAN_EDGE.into()],
        ),
        outcome(
            "resurrection_is_attributed_false_rumor",
            false_rumor.is_some()
                && rumor_cause.is_some()
                && added.contains(FALSE_RUMOR_CONSTRAINT),
            &[FALSE_RUMOR_BELIEF.into(), FALSE_RUMOR_EDGE.into()],
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
#[path = "repair_shadow_prior_record_tests.rs"]
mod tests;
