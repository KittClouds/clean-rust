use std::borrow::Cow;
use std::collections::BTreeSet;

use compact_str::CompactString;
use phoenix_semantic_v2::{
    BeliefSourceKind, BeliefStateAtom, BeliefStateKind, CausalClaimStatus, CausalEdgeAddition,
    CausalEdgeId, CausalRelationKind, CausalScopeSidecar, MemoryClaimStatus, MemoryScopeSidecar,
    MemoryStateRecord, RelationshipMemoryLedger, TemporalScopeSidecar, TemporalTruthStatus,
};
use phoenix_types::{
    BiTemporalWindow, CausalKind, ConstraintKind, CoveragePlane, EntityId, EventId, FactId,
    FactValue, Polarity, RepairTemplateKind, SceneId, SemanticNodeRef, StateKind, StoryInterval,
    StoryMutation, StoryTime,
};

use crate::repair_shadow::{build_shadow_snapshot, digest, validation_edit};
use crate::repair_simulation::simulate_repair_candidate_with_coverage;
use crate::{
    EvidenceRef, GraphEditOperation, ProposedEdit, RepairSimulationInput, RequirementDependency,
    RequirementTruthRef, RevisionEdgeRecord, RevisionFactRecord, RevisionRequirementRecord,
    RevisionRequirementSidecar, RevisionStateRecord, SceneCoverageRequest, SemanticDelta,
    ShadowOutcomeValidation, ShadowSemanticRepairError, ShadowSemanticRepairReceipt,
    ShadowSemanticRepairResult, StateRef, SHADOW_SEMANTIC_REPAIR_SCHEMA,
};

pub const HAZEL_ESPIONAGE_DIRECTIVE_ID: &str = "edit:reframe_confidant_access_as_espionage:hazel";

const PERFORMANCE_STATE_KIND: &str = "public_alliance:silas";
const ACCESS_STATE_KIND: &str = "access:silas_private_channel";
const UTILITY_STATE_KIND: &str = "alliance_utility:silas";
const THEFT_FACT: &str = "fact:hazel_stole_silas_private_channel_access";
const DISTRUST_FACT: &str = "fact:hazel_silas_mutual_distrust";
const EXPOSURE_FACT: &str = "fact:hazel_publicly_exposes_silas";
const SABOTAGE_FACT: &str = "fact:hazel_sabotages_shared_objective";

const PERFORMANCE_CONSTRAINT: &str = "constraint:repair:relationship:performed_alliance";
const ACCESS_CONSTRAINT: &str = "constraint:repair:relationship:stolen_access";
const THEFT_CONSTRAINT: &str = "constraint:repair:relationship:theft_enables_access";
const DISTRUST_CONSTRAINT: &str = "constraint:repair:relationship:mutual_distrust";
const EXPOSURE_CONSTRAINT: &str = "constraint:repair:relationship:public_exposure";
const SABOTAGE_CONSTRAINT: &str = "constraint:repair:relationship:objective_sabotage";
const UTILITY_CONSTRAINT: &str = "constraint:repair:relationship:alliance_useless";

const PERFORMANCE_EDGE: &str = "causal:repair:relationship:alliance_performance";
const ACCESS_EDGE: &str = "causal:repair:relationship:stolen_channel_access";
const THEFT_EDGE: &str = "causal:repair:relationship:theft_enables_channel_use";
const DISTRUST_EDGE: &str = "causal:repair:relationship:distrust_shapes_performance";
const EXPOSURE_EDGE: &str = "causal:repair:relationship:public_exposure";
const SABOTAGE_EDGE: &str = "causal:repair:relationship:objective_sabotage";
const UTILITY_EDGE: &str = "causal:repair:relationship:alliance_loses_usefulness";

const HAZEL_DISTRUST_BELIEF: &str = "belief:repair:hazel_doubts_silas";
const SILAS_DISTRUST_BELIEF: &str = "belief:repair:silas_doubts_hazel";
const PUBLIC_ALLIANCE_LEDGER: &str = "relationship:repair:hazel_silas:performed_alliance";
const MUTUAL_DISTRUST_LEDGER: &str = "relationship:repair:hazel_silas:mutual_distrust";

const ALLIANCE_SCENE: &str = "scene:chapter_5_public_alliance";
const ACCESS_SCENE: &str = "scene:chapter_6_hazel_uses_private_channel";
const BETRAYAL_SCENE: &str = "scene:chapter_11_betrayal";

const ORIGINAL_CONSTRAINTS: [&str; 2] = [
    "constraint:relationship:betrayal_motivation",
    "constraint:relationship:private_channel",
];
const TARGET_SCENES: [&str; 3] = [BETRAYAL_SCENE, ALLIANCE_SCENE, ACCESS_SCENE];
const ADDED_CONSTRAINTS: [&str; 7] = [
    UTILITY_CONSTRAINT,
    EXPOSURE_CONSTRAINT,
    DISTRUST_CONSTRAINT,
    PERFORMANCE_CONSTRAINT,
    SABOTAGE_CONSTRAINT,
    ACCESS_CONSTRAINT,
    THEFT_CONSTRAINT,
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
    let memory_base = input
        .memory
        .ok_or(ShadowSemanticRepairError::MissingTruthPlane("memory"))?;
    let mut temporal = Cow::Borrowed(temporal_base);
    let mut causal = Cow::Borrowed(causal_base);
    let mut memory = Cow::Borrowed(memory_base);
    apply_deltas(
        &semantic_deltas,
        requirements.to_mut(),
        temporal.to_mut(),
        causal.to_mut(),
        memory.to_mut(),
    );

    let shadow_snapshot = build_shadow_snapshot(
        input.base,
        &semantic_deltas,
        compiled_delta_digest,
        HAZEL_ESPIONAGE_DIRECTIVE_ID,
    )?;
    let validation_edit = validation_edit(edit, input.requirements, &ORIGINAL_CONSTRAINTS)?;
    let coverage_requests = coverage_after_relationship_rebuild(&input)?;
    let mut candidate = simulate_repair_candidate_with_coverage(
        RepairSimulationInput {
            base: &shadow_snapshot,
            mutations: input.mutations,
            requirements: requirements.as_ref(),
            temporal: Some(temporal.as_ref()),
            memory: Some(memory.as_ref()),
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
        memory.as_ref(),
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
        directive_id: HAZEL_ESPIONAGE_DIRECTIVE_ID.into(),
        committed_base_digest,
        shadow_snapshot_digest: shadow_snapshot.digest(),
        compiled_delta_digest,
        shadow_sidecar_digest: compiled_delta_digest,
        removed_constraint_ids: ORIGINAL_CONSTRAINTS.map(CompactString::from).to_vec(),
        added_constraint_ids: ADDED_CONSTRAINTS.map(CompactString::from).to_vec(),
        rebuilt_planes: vec![
            CoveragePlane::Relationship,
            CoveragePlane::Belief,
            CoveragePlane::State,
            CoveragePlane::Causal,
        ],
        copy_on_write_clones: 4,
        outcomes,
        all_outcomes_satisfied,
        full_shadow_revalidation_completed: candidate
            .validation_receipt
            .full_revalidation_completed,
        committed_base_unchanged,
        no_truth_writes,
        deterministic: true,
    };
    Ok(ShadowSemanticRepairResult {
        candidate,
        semantic_deltas,
        receipt,
    })
}

fn validate_contract(edit: &ProposedEdit) -> Result<(), ShadowSemanticRepairError> {
    if edit.edit_id.0.as_str() != HAZEL_ESPIONAGE_DIRECTIVE_ID
        || edit.template != RepairTemplateKind::ReclassifyAccessAsEspionage
    {
        return Err(ShadowSemanticRepairError::UnsupportedDirective(
            edit.edit_id.0.clone(),
        ));
    }
    let operation_matches = matches!(
        edit.operations.as_slice(),
        [GraphEditOperation::ApplyAuthorDirective { directive_id, required_outcomes, .. }]
            if directive_id.as_str() == HAZEL_ESPIONAGE_DIRECTIVE_ID
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
    let specs = specs();
    let mut deltas = ORIGINAL_CONSTRAINTS
        .into_iter()
        .map(|constraint_id| SemanticDelta::RemoveRequirement {
            constraint_id: constraint_id.into(),
        })
        .collect::<Vec<_>>();
    deltas.extend(
        [
            fact(THEFT_FACT, 600),
            fact(DISTRUST_FACT, 500),
            fact(EXPOSURE_FACT, 1100),
            fact(SABOTAGE_FACT, 1100),
        ]
        .into_iter()
        .map(|record| SemanticDelta::AddFact { record }),
    );
    deltas.extend(
        [state(&specs[0]), state(&specs[1]), state(&specs[6])]
            .into_iter()
            .map(|record| SemanticDelta::AddState { record }),
    );
    let replacements = replacement_records(&specs, generation);
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
            .memory_states
            .into_iter()
            .map(|record| SemanticDelta::AddMemoryState { record }),
    );
    deltas.extend(
        distrust_beliefs()
            .into_iter()
            .map(|record| SemanticDelta::AddBeliefAtom { record }),
    );
    deltas.extend(
        replacements
            .causal_edges
            .into_iter()
            .map(|record| SemanticDelta::AddCausalEdge { record }),
    );
    deltas.extend(
        relationship_ledgers()
            .into_iter()
            .map(|record| SemanticDelta::AddRelationshipLedger { record }),
    );
    deltas.push(SemanticDelta::AssertStateBoundary {
        subject_id: EntityId("entity:hazel".to_owned()),
        state_kind: "relationship:silas".into(),
        replacement: FactValue::Text("none".into()),
        valid_from: StoryTime(0),
    });
    deltas.push(SemanticDelta::ResolveCoverageRequirement {
        scene_id: SceneId(ALLIANCE_SCENE.into()),
        removed_required_planes: vec![CoveragePlane::Relationship, CoveragePlane::Belief],
        rationale: "Performed-alliance ledgers and mutual-distrust beliefs are present".into(),
    });
    Ok(deltas)
}

struct Spec {
    constraint: &'static str,
    dependency: RequirementDependency,
    expected: FactValue,
    scene: &'static str,
    time: i64,
    edge: &'static str,
    event: &'static str,
    kind: ConstraintKind,
}

fn specs() -> [Spec; 7] {
    [
        state_spec(
            PERFORMANCE_CONSTRAINT,
            PERFORMANCE_STATE_KIND,
            "performed",
            ALLIANCE_SCENE,
            500,
            PERFORMANCE_EDGE,
            "event:hazel_silas_stage_public_alliance",
        ),
        state_spec(
            ACCESS_CONSTRAINT,
            ACCESS_STATE_KIND,
            "stolen",
            ACCESS_SCENE,
            600,
            ACCESS_EDGE,
            "event:hazel_uses_stolen_channel_access",
        ),
        fact_spec(
            THEFT_CONSTRAINT,
            THEFT_FACT,
            ACCESS_SCENE,
            600,
            THEFT_EDGE,
            "event:hazel_steals_private_channel_access",
            ConstraintKind::CausalSupport,
        ),
        fact_spec(
            DISTRUST_CONSTRAINT,
            DISTRUST_FACT,
            ALLIANCE_SCENE,
            500,
            DISTRUST_EDGE,
            "event:hazel_silas_conceal_mutual_distrust",
            ConstraintKind::CausalSupport,
        ),
        fact_spec(
            EXPOSURE_CONSTRAINT,
            EXPOSURE_FACT,
            BETRAYAL_SCENE,
            1100,
            EXPOSURE_EDGE,
            "event:hazel_publicly_exposes_silas",
            ConstraintKind::CausalSupport,
        ),
        fact_spec(
            SABOTAGE_CONSTRAINT,
            SABOTAGE_FACT,
            BETRAYAL_SCENE,
            1100,
            SABOTAGE_EDGE,
            "event:hazel_sabotages_shared_objective",
            ConstraintKind::CausalSupport,
        ),
        state_spec(
            UTILITY_CONSTRAINT,
            UTILITY_STATE_KIND,
            "destroyed",
            BETRAYAL_SCENE,
            1100,
            UTILITY_EDGE,
            "event:alliance_becomes_useless",
        ),
    ]
}

#[allow(clippy::too_many_arguments)]
fn state_spec(
    constraint: &'static str,
    state_kind: &'static str,
    value: &'static str,
    scene: &'static str,
    time: i64,
    edge: &'static str,
    event: &'static str,
) -> Spec {
    Spec {
        constraint,
        dependency: RequirementDependency::State {
            state_ref: StateRef {
                subject_id: EntityId("entity:hazel".to_owned()),
                state_kind: StateKind(state_kind.into()),
            },
        },
        expected: FactValue::Text(value.into()),
        scene,
        time,
        edge,
        event,
        kind: ConstraintKind::RequiresState,
    }
}

#[allow(clippy::too_many_arguments)]
fn fact_spec(
    constraint: &'static str,
    fact_id: &'static str,
    scene: &'static str,
    time: i64,
    edge: &'static str,
    event: &'static str,
    kind: ConstraintKind,
) -> Spec {
    Spec {
        constraint,
        dependency: RequirementDependency::Fact {
            fact_id: FactId(fact_id.into()),
        },
        expected: FactValue::Boolean(true),
        scene,
        time,
        edge,
        event,
        kind,
    }
}

struct ReplacementRecords {
    requirements: [RevisionRequirementRecord; 7],
    edges: [RevisionEdgeRecord; 7],
    memory_states: [MemoryStateRecord; 3],
    causal_edges: [CausalEdgeAddition; 7],
}

fn replacement_records(specs: &[Spec; 7], generation: u64) -> ReplacementRecords {
    let requirements = specs.each_ref().map(requirement);
    let edges = requirements.each_ref().map(graph_edge);
    let memory_states = [
        memory_state(&specs[0]),
        memory_state(&specs[1]),
        memory_state(&specs[6]),
    ];
    let causal_edges = specs.each_ref().map(|spec| causal_edge(spec, generation));
    ReplacementRecords {
        requirements,
        edges,
        memory_states,
        causal_edges,
    }
}

fn requirement(spec: &Spec) -> RevisionRequirementRecord {
    let truth_ref = match &spec.dependency {
        RequirementDependency::State { .. } => RequirementTruthRef::MemoryState {
            state_id: format!("memory:{}", spec.constraint).into(),
        },
        RequirementDependency::Fact { .. } => RequirementTruthRef::CausalEdge {
            edge_id: spec.edge.into(),
        },
    };
    RevisionRequirementRecord {
        constraint_id: spec.constraint.into(),
        dependency: spec.dependency.clone(),
        expected_value: spec.expected.clone(),
        dependent_scene_id: SceneId(spec.scene.into()),
        kind: spec.kind,
        valid_interval: StoryInterval {
            valid_from: StoryTime(spec.time),
            valid_to_exclusive: Some(StoryTime(spec.time + 1)),
        },
        truth_ref,
        evidence: vec![EvidenceRef::anchored(author_evidence(spec.constraint))],
        confidence_millis: 1000,
    }
}

fn graph_edge(requirement: &RevisionRequirementRecord) -> RevisionEdgeRecord {
    let (facts, states) = match &requirement.dependency {
        RequirementDependency::Fact { fact_id } => (vec![fact_id.clone()], Vec::new()),
        RequirementDependency::State { state_ref } => (Vec::new(), vec![state_ref.clone()]),
    };
    RevisionEdgeRecord {
        edge_id: requirement.constraint_id.clone(),
        dependency_fact_ids: facts,
        dependency_state_refs: states,
    }
}

fn fact(fact_id: &str, time: i64) -> RevisionFactRecord {
    RevisionFactRecord {
        fact_id: FactId(fact_id.into()),
        value: FactValue::Boolean(true),
        interval: interval(time, None),
    }
}

fn state(spec: &Spec) -> RevisionStateRecord {
    let RequirementDependency::State { state_ref } = &spec.dependency else {
        unreachable!("relationship state spec")
    };
    RevisionStateRecord {
        state_ref: state_ref.clone(),
        value: spec.expected.clone(),
        interval: interval(spec.time, None),
    }
}

fn memory_state(spec: &Spec) -> MemoryStateRecord {
    let RequirementDependency::State { state_ref } = &spec.dependency else {
        unreachable!("relationship memory state")
    };
    let FactValue::Text(value) = &spec.expected else {
        unreachable!("relationship state value")
    };
    MemoryStateRecord {
        state_id: format!("memory:{}", spec.constraint),
        entity_id: state_ref.subject_id.clone(),
        slot_key: state_ref.state_kind.0.to_string(),
        value: value.to_string(),
        value_entity_id: None,
        status: MemoryClaimStatus::Active,
        source_class: "author-confirmed-espionage-reframe".to_owned(),
        confidence_millis: 1000,
        temporal: window(spec.time, None),
        claim_ids: vec![author_evidence(spec.constraint)],
    }
}

fn distrust_beliefs() -> [BeliefStateAtom; 2] {
    [
        belief(HAZEL_DISTRUST_BELIEF, "entity:hazel", "entity:silas"),
        belief(SILAS_DISTRUST_BELIEF, "entity:silas", "entity:hazel"),
    ]
}

fn belief(belief_id: &str, observer: &str, subject: &str) -> BeliefStateAtom {
    BeliefStateAtom {
        belief_id: belief_id.to_owned(),
        document_id: HAZEL_ESPIONAGE_DIRECTIVE_ID.to_owned(),
        proposition_id: Some(DISTRUST_FACT.to_owned()),
        observer_entity_id: Some(EntityId(observer.to_owned())),
        subject_entity_id: Some(EntityId(subject.to_owned())),
        kind: BeliefStateKind::Doubts,
        truth_status: TemporalTruthStatus::Asserted,
        source_kind: BeliefSourceKind::Attribution,
        label: "mutual distrust hidden by performed alliance".to_owned(),
        confidence_millis: 1000,
        temporal: window(500, None),
        evidence_refs: vec![author_evidence(DISTRUST_CONSTRAINT)],
        ..BeliefStateAtom::default()
    }
}

fn relationship_ledgers() -> [RelationshipMemoryLedger; 2] {
    [
        RelationshipMemoryLedger {
            ledger_id: PUBLIC_ALLIANCE_LEDGER.to_owned(),
            relation_family: "performed_alliance".to_owned(),
            source_entity_id: EntityId("entity:hazel".to_owned()),
            target_entity_id: EntityId("entity:silas".to_owned()),
            current_status: MemoryClaimStatus::Superseded,
            temporal: window(500, Some(1100)),
            supporting_claim_ids: vec![author_evidence(PERFORMANCE_CONSTRAINT)],
            contradicting_claim_ids: Vec::new(),
        },
        RelationshipMemoryLedger {
            ledger_id: MUTUAL_DISTRUST_LEDGER.to_owned(),
            relation_family: "mutual_distrust".to_owned(),
            source_entity_id: EntityId("entity:hazel".to_owned()),
            target_entity_id: EntityId("entity:silas".to_owned()),
            current_status: MemoryClaimStatus::Active,
            temporal: window(500, None),
            supporting_claim_ids: vec![author_evidence(DISTRUST_CONSTRAINT)],
            contradicting_claim_ids: Vec::new(),
        },
    ]
}

fn causal_edge(spec: &Spec, generation: u64) -> CausalEdgeAddition {
    CausalEdgeAddition {
        edge_id: CausalEdgeId(spec.edge.to_owned()),
        case_id: HAZEL_ESPIONAGE_DIRECTIVE_ID.to_owned(),
        document_id: HAZEL_ESPIONAGE_DIRECTIVE_ID.to_owned(),
        source: SemanticNodeRef::Event(EventId(spec.event.to_owned())),
        canonical_cause_event_id: None,
        target: SemanticNodeRef::Event(EventId(spec.scene.to_owned())),
        canonical_effect_event_id: None,
        kind: if spec.constraint == UTILITY_CONSTRAINT {
            CausalKind::ResultsIn
        } else {
            CausalKind::ConditionFor
        },
        relation_kind: CausalRelationKind::EnablingCondition,
        status: CausalClaimStatus::Active,
        first_seen_revision: generation,
        latest_decision_id: None,
        confidence_millis: 1000,
        cue: Some("author-confirmed espionage and performed alliance".to_owned()),
        attributed_to: Some(EntityId("entity:hazel".to_owned())),
        polarity: Polarity::Positive,
        claim_atom_ids: Vec::new(),
        evidence_refs: vec![author_evidence(spec.constraint)],
        effective_interval: window(spec.time, None),
        observation_interval: window(spec.time, None),
        temporal_certainty_millis: 1000,
        created_at: 1_784_295_149,
    }
}

fn apply_deltas(
    deltas: &[SemanticDelta],
    requirements: &mut RevisionRequirementSidecar,
    temporal: &mut TemporalScopeSidecar,
    causal: &mut CausalScopeSidecar,
    memory: &mut MemoryScopeSidecar,
) {
    for delta in deltas {
        match delta {
            SemanticDelta::AddRequirement { record } => {
                requirements.requirements.push(record.clone())
            }
            SemanticDelta::AddBeliefAtom { record } => temporal.belief_atoms.push(record.clone()),
            SemanticDelta::AddCausalEdge { record } => causal.edge_records.push(record.clone()),
            SemanticDelta::AddMemoryState { record } => memory.states.push(record.clone()),
            SemanticDelta::AddRelationshipLedger { record } => {
                memory.relationship_ledgers.push(record.clone())
            }
            _ => {}
        }
    }
    requirements
        .requirements
        .sort_unstable_by(|a, b| a.constraint_id.cmp(&b.constraint_id));
    temporal
        .belief_atoms
        .sort_unstable_by(|a, b| a.belief_id.cmp(&b.belief_id));
    causal
        .edge_records
        .sort_unstable_by(|a, b| a.edge_id.0.cmp(&b.edge_id.0));
    memory
        .states
        .sort_unstable_by(|a, b| a.state_id.cmp(&b.state_id));
    memory
        .relationship_ledgers
        .sort_unstable_by(|a, b| a.ledger_id.cmp(&b.ledger_id));
}

fn coverage_after_relationship_rebuild(
    input: &RepairSimulationInput<'_>,
) -> Result<Vec<SceneCoverageRequest>, ShadowSemanticRepairError> {
    let alliance = input
        .original_report
        .authoritative_impacts
        .iter()
        .find(|impact| impact.scene_id.0 == ALLIANCE_SCENE)
        .ok_or_else(|| ShadowSemanticRepairError::MalformedDirective(ALLIANCE_SCENE.into()))?;
    let missing = &alliance.coverage.missing_required_planes;
    if !missing.contains(&CoveragePlane::Relationship) || !missing.contains(&CoveragePlane::Belief)
    {
        return Err(ShadowSemanticRepairError::MalformedDirective(
            ALLIANCE_SCENE.into(),
        ));
    }
    Ok(input
        .original_report
        .authoritative_impacts
        .iter()
        .filter(|impact| impact.scene_id.0 != ALLIANCE_SCENE)
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
    memory: &MemoryScopeSidecar,
    candidate: &crate::RepairCandidate,
) -> Vec<ShadowOutcomeValidation> {
    let mutation = mutations.iter().any(|mutation| matches!(mutation,
        StoryMutation::ChangeState { subject_id, state_kind, replacement: FactValue::Text(value), valid_from }
            if subject_id.0 == "entity:hazel" && state_kind.0 == "relationship:silas"
                && value == "none" && *valid_from == StoryTime(0)));
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
    let edges = causal
        .edge_records
        .iter()
        .map(|row| row.edge_id.0.as_str())
        .collect::<BTreeSet<_>>();
    let beliefs = temporal
        .belief_atoms
        .iter()
        .map(|row| row.belief_id.as_str())
        .collect::<BTreeSet<_>>();
    let ledgers = memory
        .relationship_ledgers
        .iter()
        .map(|row| row.ledger_id.as_str())
        .collect::<BTreeSet<_>>();
    let states = memory
        .states
        .iter()
        .map(|row| (row.slot_key.as_str(), row.value.as_str()))
        .collect::<BTreeSet<_>>();
    vec![
        outcome(
            "confidant_access_is_replaced_by_theft",
            mutation
                && fixed.contains(ORIGINAL_CONSTRAINTS[1])
                && states.contains(&(ACCESS_STATE_KIND, "stolen"))
                && added.contains(THEFT_CONSTRAINT)
                && edges.contains(THEFT_EDGE),
            &[THEFT_EDGE.into()],
        ),
        outcome(
            "public_alliance_is_performance_hiding_mutual_distrust",
            mutation
                && ledgers.contains(PUBLIC_ALLIANCE_LEDGER)
                && ledgers.contains(MUTUAL_DISTRUST_LEDGER)
                && beliefs.contains(HAZEL_DISTRUST_BELIEF)
                && beliefs.contains(SILAS_DISTRUST_BELIEF)
                && states.contains(&(PERFORMANCE_STATE_KIND, "performed")),
            &[PUBLIC_ALLIANCE_LEDGER.into(), MUTUAL_DISTRUST_LEDGER.into()],
        ),
        outcome(
            "later_betrayal_is_public_exposure_and_objective_sabotage",
            fixed.contains(ORIGINAL_CONSTRAINTS[0])
                && added.contains(EXPOSURE_CONSTRAINT)
                && added.contains(SABOTAGE_CONSTRAINT)
                && edges.contains(EXPOSURE_EDGE)
                && edges.contains(SABOTAGE_EDGE),
            &[EXPOSURE_EDGE.into(), SABOTAGE_EDGE.into()],
        ),
        outcome(
            "alliance_loses_usefulness_after_hazels_actions",
            states.contains(&(UTILITY_STATE_KIND, "destroyed"))
                && added.contains(UTILITY_CONSTRAINT)
                && edges.contains(UTILITY_EDGE),
            &[UTILITY_EDGE.into()],
        ),
    ]
}

fn interval(valid_from: i64, valid_to: Option<i64>) -> StoryInterval {
    StoryInterval {
        valid_from: StoryTime(valid_from),
        valid_to_exclusive: valid_to.map(StoryTime),
    }
}

fn window(valid_from: i64, valid_to: Option<i64>) -> BiTemporalWindow {
    BiTemporalWindow {
        valid_from: Some(valid_from),
        valid_to,
        recorded_from: Some(0),
        recorded_to: None,
    }
}

fn author_evidence(constraint_id: &str) -> String {
    format!("author-directive:{constraint_id}")
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
#[path = "repair_shadow_relationship_tests.rs"]
mod tests;
