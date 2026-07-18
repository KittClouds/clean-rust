use std::borrow::Cow;
use std::collections::BTreeSet;

use compact_str::CompactString;
use phoenix_semantic_v2::{
    CausalClaimStatus, CausalEdgeAddition, CausalEdgeId, CausalRelationKind, CausalScopeSidecar,
    MemoryClaimStatus, MemoryScopeSidecar, MemoryStateRecord, TemporalConstraintId,
    TemporalConstraintRecord, TemporalScopeSidecar,
};
use phoenix_types::{
    BiTemporalWindow, CausalKind, ConstraintKind, CoveragePlane, EventId, FactId, FactValue,
    Polarity, RepairTemplateKind, SceneId, SemanticNodeRef, StoryInterval, StoryMutation,
    StoryTime,
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

pub const CONSTRAINED_PORTAL_DIRECTIVE_ID: &str = "edit:route_arrival_through_constrained_portal";

const ORDINARY_DURATION_FACT: &str = "fact:veyra_to_northern_fort_travel_minutes";
const PORTAL_EXISTS_FACT: &str = "fact:veyra_northern_fort_portal_exists";
const PORTAL_ROUTE_FACT: &str = "fact:veyra_northern_fort_portal_fixed_route";
const PORTAL_DURATION_FACT: &str = "fact:veyra_northern_fort_portal_travel_minutes";
const PORTAL_COST_FACT: &str = "fact:veyra_northern_fort_portal_consumes_charge";
const PORTAL_CAPACITY_FACT: &str = "fact:veyra_northern_fort_portal_passenger_limit";
const PORTAL_COOLDOWN_FACT: &str = "fact:veyra_northern_fort_portal_cooldown_minutes";
const PURSUIT_PRESSURE_FACT: &str = "fact:eight_hour_route_preserves_pursuit_pressure";

const PORTAL_EXISTS_CONSTRAINT: &str = "constraint:repair:travel:portal_exists";
const PORTAL_ROUTE_CONSTRAINT: &str = "constraint:repair:travel:fixed_endpoints";
const PORTAL_DURATION_CONSTRAINT: &str = "constraint:repair:travel:portal_duration";
const PORTAL_COST_CONSTRAINT: &str = "constraint:repair:travel:activation_cost";
const PORTAL_CAPACITY_CONSTRAINT: &str = "constraint:repair:travel:passenger_limit";
const PORTAL_COOLDOWN_CONSTRAINT: &str = "constraint:repair:travel:cooldown";
const PURSUIT_PRESSURE_CONSTRAINT: &str = "constraint:repair:travel:pursuit_pressure";

const PORTAL_EXISTS_EDGE: &str = "causal:repair:travel:portal_exists_before_arrival";
const PORTAL_ROUTE_EDGE: &str = "causal:repair:travel:portal_fixed_route";
const PORTAL_DURATION_EDGE: &str = "causal:repair:travel:portal_transit_time";
const PORTAL_COST_EDGE: &str = "causal:repair:travel:portal_activation_cost";
const PORTAL_CAPACITY_EDGE: &str = "causal:repair:travel:portal_capacity";
const PORTAL_COOLDOWN_EDGE: &str = "causal:repair:travel:portal_cooldown";
const PURSUIT_PRESSURE_EDGE: &str = "causal:repair:travel:eight_hour_pursuit_pressure";

const PORTAL_SCENE: &str = "scene:chapter_7_portal_rumor";
const ARRIVAL_SCENE: &str = "scene:chapter_8_same_evening_arrival";
const PURSUIT_SCENE: &str = "scene:chapter_9_pursuit_pressure";
const ORIGIN_ENDPOINT: &str = "location:veyra_portal_endpoint";
const DESTINATION_ENDPOINT: &str = "location:northern_fort_portal_endpoint";

const ORDINARY_TRAVEL_MINUTES: u32 = 480;
const PORTAL_TRAVEL_MINUTES: u32 = 30;
const PORTAL_PASSENGER_LIMIT: u16 = 4;
const PORTAL_COOLDOWN_MINUTES: u32 = 1_440;

const ORIGINAL_CONSTRAINTS: [&str; 3] = [
    "constraint:travel:arrival_order",
    "constraint:travel:arrival_reachability",
    "constraint:travel:pursuit_foreshadowing",
];
const TARGET_SCENES: [&str; 3] = [PORTAL_SCENE, ARRIVAL_SCENE, PURSUIT_SCENE];
const ADDED_CONSTRAINTS: [&str; 7] = [
    PORTAL_COST_CONSTRAINT,
    PORTAL_COOLDOWN_CONSTRAINT,
    PORTAL_ROUTE_CONSTRAINT,
    PORTAL_CAPACITY_CONSTRAINT,
    PORTAL_DURATION_CONSTRAINT,
    PORTAL_EXISTS_CONSTRAINT,
    PURSUIT_PRESSURE_CONSTRAINT,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TravelMode {
    Ordinary,
    Portal,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TravelActivationCost {
    ConsumedActivationCharge,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TravelRuleRecord {
    pub rule_id: CompactString,
    pub mode: TravelMode,
    pub origin_endpoint_id: CompactString,
    pub destination_endpoint_id: CompactString,
    pub travel_minutes: u32,
    pub activation_cost: Option<TravelActivationCost>,
    pub passenger_limit: Option<u16>,
    pub cooldown_minutes: Option<u32>,
    pub preserves_pursuit_pressure: bool,
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
    let memory_base = input
        .memory
        .ok_or(ShadowSemanticRepairError::MissingTruthPlane("memory"))?;
    let temporal_base = input
        .temporal
        .ok_or(ShadowSemanticRepairError::MissingTruthPlane("temporal"))?;
    let mut memory = Cow::Borrowed(memory_base);
    let mut temporal = Cow::Borrowed(temporal_base);
    apply_deltas(
        &semantic_deltas,
        requirements.to_mut(),
        causal.to_mut(),
        memory.to_mut(),
        temporal.to_mut(),
    );
    let shadow_snapshot = build_shadow_snapshot(
        input.base,
        &semantic_deltas,
        compiled_delta_digest,
        CONSTRAINED_PORTAL_DIRECTIVE_ID,
    )?;
    let validation_edit = validation_edit(edit, input.requirements, &ORIGINAL_CONSTRAINTS)?;
    let coverage_requests = coverage_after_travel_rebuild(&input)?;
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
        directive_id: CONSTRAINED_PORTAL_DIRECTIVE_ID.into(),
        committed_base_digest,
        shadow_snapshot_digest: shadow_snapshot.digest(),
        compiled_delta_digest,
        shadow_sidecar_digest: compiled_delta_digest,
        removed_constraint_ids: ORIGINAL_CONSTRAINTS.map(CompactString::from).to_vec(),
        added_constraint_ids: ADDED_CONSTRAINTS.map(CompactString::from).to_vec(),
        rebuilt_planes: vec![
            CoveragePlane::Location,
            CoveragePlane::Capability,
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
    if edit.edit_id.0.as_str() != CONSTRAINED_PORTAL_DIRECTIVE_ID
        || edit.template != RepairTemplateKind::AddConstrainedTravelMethod
    {
        return Err(ShadowSemanticRepairError::UnsupportedDirective(
            edit.edit_id.0.clone(),
        ));
    }
    let operation_matches = matches!(
        edit.operations.as_slice(),
        [GraphEditOperation::ApplyAuthorDirective { directive_id, required_outcomes, .. }]
            if directive_id.as_str() == CONSTRAINED_PORTAL_DIRECTIVE_ID
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
    let records = replacement_records(generation);
    deltas.extend(
        records
            .facts
            .iter()
            .cloned()
            .map(|record| SemanticDelta::AddFact { record }),
    );
    deltas.extend(
        records
            .edges
            .iter()
            .cloned()
            .map(|record| SemanticDelta::AddGraphEdge { record }),
    );
    deltas.extend(
        records
            .requirements
            .iter()
            .cloned()
            .map(|record| SemanticDelta::AddRequirement { record }),
    );
    deltas.extend(
        records
            .causal_edges
            .into_iter()
            .map(|record| SemanticDelta::AddCausalEdge { record }),
    );
    deltas.extend(
        records
            .memory_states
            .into_iter()
            .map(|record| SemanticDelta::AddMemoryState { record }),
    );
    deltas.extend(
        records
            .temporal_constraints
            .into_iter()
            .map(|record| SemanticDelta::AddTemporalConstraint { record }),
    );
    deltas.extend(
        travel_rules()
            .into_iter()
            .map(|record| SemanticDelta::AddTravelRule { record }),
    );
    deltas.push(SemanticDelta::ResolveCoverageRequirement {
        scene_id: SceneId(PORTAL_SCENE.into()),
        removed_required_planes: vec![CoveragePlane::Location, CoveragePlane::Capability],
        rationale: "Typed ordinary-route and constrained-portal rules are present".into(),
    });
    Ok(deltas)
}

struct ReplacementRecords {
    facts: [RevisionFactRecord; 7],
    requirements: [RevisionRequirementRecord; 7],
    edges: [RevisionEdgeRecord; 7],
    causal_edges: [CausalEdgeAddition; 7],
    memory_states: [MemoryStateRecord; 2],
    temporal_constraints: [TemporalConstraintRecord; 1],
}

struct Spec {
    constraint: &'static str,
    fact: &'static str,
    value: FactValue,
    scene: &'static str,
    story_time: i64,
    edge: &'static str,
    source_event: &'static str,
    kind: ConstraintKind,
}

fn replacement_records(generation: u64) -> ReplacementRecords {
    let specs = [
        spec(
            PORTAL_EXISTS_CONSTRAINT,
            PORTAL_EXISTS_FACT,
            FactValue::Boolean(true),
            PORTAL_SCENE,
            700,
            PORTAL_EXISTS_EDGE,
            "event:portal_confirmed_real",
            ConstraintKind::CausalSupport,
        ),
        spec(
            PORTAL_ROUTE_CONSTRAINT,
            PORTAL_ROUTE_FACT,
            FactValue::Boolean(true),
            ARRIVAL_SCENE,
            800,
            PORTAL_ROUTE_EDGE,
            "event:party_enters_veyra_portal",
            ConstraintKind::RequiresReachability,
        ),
        spec(
            PORTAL_DURATION_CONSTRAINT,
            PORTAL_DURATION_FACT,
            FactValue::DurationMinutes(PORTAL_TRAVEL_MINUTES.into()),
            ARRIVAL_SCENE,
            800,
            PORTAL_DURATION_EDGE,
            "event:portal_transit_begins",
            ConstraintKind::RequiresTemporalOrder,
        ),
        spec(
            PORTAL_COST_CONSTRAINT,
            PORTAL_COST_FACT,
            FactValue::Boolean(true),
            ARRIVAL_SCENE,
            800,
            PORTAL_COST_EDGE,
            "event:portal_charge_consumed",
            ConstraintKind::CausalSupport,
        ),
        spec(
            PORTAL_CAPACITY_CONSTRAINT,
            PORTAL_CAPACITY_FACT,
            FactValue::Integer(PORTAL_PASSENGER_LIMIT.into()),
            ARRIVAL_SCENE,
            800,
            PORTAL_CAPACITY_EDGE,
            "event:portal_passengers_selected",
            ConstraintKind::RequiresReachability,
        ),
        spec(
            PORTAL_COOLDOWN_CONSTRAINT,
            PORTAL_COOLDOWN_FACT,
            FactValue::DurationMinutes(PORTAL_COOLDOWN_MINUTES.into()),
            PURSUIT_SCENE,
            900,
            PORTAL_COOLDOWN_EDGE,
            "event:portal_enters_cooldown",
            ConstraintKind::CausalSupport,
        ),
        spec(
            PURSUIT_PRESSURE_CONSTRAINT,
            PURSUIT_PRESSURE_FACT,
            FactValue::Boolean(true),
            PURSUIT_SCENE,
            900,
            PURSUIT_PRESSURE_EDGE,
            "event:pursuers_exploit_eight_hour_route",
            ConstraintKind::Foreshadowing,
        ),
    ];
    let facts = specs
        .each_ref()
        .map(|row| fact(row.fact, row.value.clone(), row.story_time));
    let requirements = specs.each_ref().map(requirement);
    let edges = requirements.each_ref().map(graph_edge);
    let causal_edges = specs.each_ref().map(|row| causal_edge(row, generation));
    let memory_states = [memory_state(&specs[1]), memory_state(&specs[4])];
    let temporal_constraints = [temporal_constraint(&specs[2])];
    ReplacementRecords {
        facts,
        requirements,
        edges,
        causal_edges,
        memory_states,
        temporal_constraints,
    }
}

#[allow(clippy::too_many_arguments)]
fn spec(
    constraint: &'static str,
    fact: &'static str,
    value: FactValue,
    scene: &'static str,
    story_time: i64,
    edge: &'static str,
    source_event: &'static str,
    kind: ConstraintKind,
) -> Spec {
    Spec {
        constraint,
        fact,
        value,
        scene,
        story_time,
        edge,
        source_event,
        kind,
    }
}

fn travel_rules() -> [TravelRuleRecord; 2] {
    [
        TravelRuleRecord {
            rule_id: "travel-rule:veyra-northern-fort:ordinary".into(),
            mode: TravelMode::Ordinary,
            origin_endpoint_id: "location:veyra".into(),
            destination_endpoint_id: "location:northern_fort".into(),
            travel_minutes: ORDINARY_TRAVEL_MINUTES,
            activation_cost: None,
            passenger_limit: None,
            cooldown_minutes: None,
            preserves_pursuit_pressure: true,
            valid_interval: interval_from(StoryTime(0)),
            evidence_id: author_evidence(PURSUIT_PRESSURE_CONSTRAINT).into(),
        },
        TravelRuleRecord {
            rule_id: "travel-rule:veyra-northern-fort:portal".into(),
            mode: TravelMode::Portal,
            origin_endpoint_id: ORIGIN_ENDPOINT.into(),
            destination_endpoint_id: DESTINATION_ENDPOINT.into(),
            travel_minutes: PORTAL_TRAVEL_MINUTES,
            activation_cost: Some(TravelActivationCost::ConsumedActivationCharge),
            passenger_limit: Some(PORTAL_PASSENGER_LIMIT),
            cooldown_minutes: Some(PORTAL_COOLDOWN_MINUTES),
            preserves_pursuit_pressure: true,
            valid_interval: interval_from(StoryTime(700)),
            evidence_id: author_evidence(PORTAL_ROUTE_CONSTRAINT).into(),
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

fn requirement(spec: &Spec) -> RevisionRequirementRecord {
    let truth_ref = match spec.kind {
        ConstraintKind::RequiresReachability => RequirementTruthRef::MemoryState {
            state_id: format!("memory:{}", spec.constraint).into(),
        },
        ConstraintKind::RequiresTemporalOrder => RequirementTruthRef::TemporalConstraint {
            constraint_id: format!("temporal:{}", spec.constraint).into(),
        },
        _ => RequirementTruthRef::CausalEdge {
            edge_id: spec.edge.into(),
        },
    };
    RevisionRequirementRecord {
        constraint_id: spec.constraint.into(),
        dependency: RequirementDependency::Fact {
            fact_id: FactId(spec.fact.into()),
        },
        expected_value: spec.value.clone(),
        dependent_scene_id: SceneId(spec.scene.into()),
        kind: spec.kind,
        valid_interval: StoryInterval {
            valid_from: StoryTime(spec.story_time),
            valid_to_exclusive: Some(StoryTime(spec.story_time + 1)),
        },
        truth_ref,
        evidence: vec![EvidenceRef::anchored(author_evidence(spec.constraint))],
        confidence_millis: 1000,
    }
}

fn memory_state(spec: &Spec) -> MemoryStateRecord {
    MemoryStateRecord {
        state_id: format!("memory:{}", spec.constraint),
        entity_id: phoenix_types::EntityId(format!("source:{}", spec.fact)),
        slot_key: spec.fact.to_owned(),
        value: match &spec.value {
            FactValue::Boolean(value) => value.to_string(),
            FactValue::Integer(value) | FactValue::DurationMinutes(value) => value.to_string(),
            FactValue::Text(value) => value.to_string(),
            FactValue::Entity(value) => value.0.to_string(),
        },
        value_entity_id: None,
        status: MemoryClaimStatus::Active,
        source_class: "author-confirmed-travel-rule".to_owned(),
        confidence_millis: 1000,
        temporal: window_from(spec.story_time),
        claim_ids: vec![author_evidence(spec.constraint)],
    }
}

fn temporal_constraint(spec: &Spec) -> TemporalConstraintRecord {
    TemporalConstraintRecord {
        constraint_id: TemporalConstraintId(format!("temporal:{}", spec.constraint)),
        document_id: CONSTRAINED_PORTAL_DIRECTIVE_ID.to_owned(),
        hard: true,
        temporal: window_from(spec.story_time),
        confidence_millis: 1000,
        evidence_refs: vec![author_evidence(spec.constraint)],
        ..TemporalConstraintRecord::default()
    }
}

fn graph_edge(requirement: &RevisionRequirementRecord) -> RevisionEdgeRecord {
    let RequirementDependency::Fact { fact_id } = &requirement.dependency else {
        unreachable!("travel replacement dependencies are facts")
    };
    RevisionEdgeRecord {
        edge_id: requirement.constraint_id.clone(),
        dependency_fact_ids: vec![fact_id.clone()],
        dependency_state_refs: Vec::new(),
    }
}

fn causal_edge(spec: &Spec, generation: u64) -> CausalEdgeAddition {
    CausalEdgeAddition {
        edge_id: CausalEdgeId(spec.edge.to_owned()),
        case_id: CONSTRAINED_PORTAL_DIRECTIVE_ID.to_owned(),
        document_id: CONSTRAINED_PORTAL_DIRECTIVE_ID.to_owned(),
        source: SemanticNodeRef::Event(EventId(spec.source_event.to_owned())),
        canonical_cause_event_id: None,
        target: SemanticNodeRef::Event(EventId(spec.scene.to_owned())),
        canonical_effect_event_id: None,
        kind: if spec.kind == ConstraintKind::Foreshadowing {
            CausalKind::ResultsIn
        } else {
            CausalKind::ConditionFor
        },
        relation_kind: CausalRelationKind::EnablingCondition,
        status: CausalClaimStatus::Active,
        first_seen_revision: generation,
        latest_decision_id: None,
        confidence_millis: 1000,
        cue: Some("author-confirmed constrained travel method".to_owned()),
        attributed_to: None,
        polarity: Polarity::Positive,
        claim_atom_ids: Vec::new(),
        evidence_refs: vec![author_evidence(spec.constraint)],
        effective_interval: window_from(spec.story_time),
        observation_interval: window_from(spec.story_time),
        temporal_certainty_millis: 1000,
        created_at: 1_784_295_149,
    }
}

fn apply_deltas(
    deltas: &[SemanticDelta],
    requirements: &mut RevisionRequirementSidecar,
    causal: &mut CausalScopeSidecar,
    memory: &mut MemoryScopeSidecar,
    temporal: &mut TemporalScopeSidecar,
) {
    for delta in deltas {
        match delta {
            SemanticDelta::AddRequirement { record } => {
                requirements.requirements.push(record.clone())
            }
            SemanticDelta::AddCausalEdge { record } => causal.edge_records.push(record.clone()),
            SemanticDelta::AddMemoryState { record } => memory.states.push(record.clone()),
            SemanticDelta::AddTemporalConstraint { record } => {
                temporal.constraints.push(record.clone())
            }
            _ => {}
        }
    }
    requirements
        .requirements
        .sort_unstable_by(|left, right| left.constraint_id.cmp(&right.constraint_id));
    causal
        .edge_records
        .sort_unstable_by(|left, right| left.edge_id.0.cmp(&right.edge_id.0));
    memory
        .states
        .sort_unstable_by(|left, right| left.state_id.cmp(&right.state_id));
    temporal
        .constraints
        .sort_unstable_by(|left, right| left.constraint_id.0.cmp(&right.constraint_id.0));
}

fn coverage_after_travel_rebuild(
    input: &RepairSimulationInput<'_>,
) -> Result<Vec<SceneCoverageRequest>, ShadowSemanticRepairError> {
    let portal = input
        .original_report
        .authoritative_impacts
        .iter()
        .find(|impact| impact.scene_id.0 == PORTAL_SCENE)
        .ok_or_else(|| ShadowSemanticRepairError::MalformedDirective(PORTAL_SCENE.into()))?;
    let missing = &portal.coverage.missing_required_planes;
    if !missing.contains(&CoveragePlane::Location) || !missing.contains(&CoveragePlane::Capability)
    {
        return Err(ShadowSemanticRepairError::MalformedDirective(
            PORTAL_SCENE.into(),
        ));
    }
    Ok(input
        .original_report
        .authoritative_impacts
        .iter()
        .filter(|impact| impact.scene_id.0 != PORTAL_SCENE)
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
            SemanticDelta::AddTravelRule { record } => Some(record),
            _ => None,
        })
        .collect::<Vec<_>>();
    let ordinary = rules.iter().find(|rule| rule.mode == TravelMode::Ordinary);
    let portal = rules.iter().find(|rule| rule.mode == TravelMode::Portal);
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
    let mutation = mutations.iter().any(|mutation| matches!(
        mutation,
        StoryMutation::SupersedeFact { fact_id, replacement: FactValue::DurationMinutes(480), valid_from }
            if fact_id.0 == ORDINARY_DURATION_FACT && *valid_from == StoryTime(0)
    ));
    let fixed = candidate
        .fixed_constraints
        .iter()
        .map(CompactString::as_str)
        .collect::<BTreeSet<_>>();
    vec![
        outcome(
            "ordinary_route_remains_eight_hours",
            mutation
                && ordinary.is_some_and(|rule| rule.travel_minutes == ORDINARY_TRAVEL_MINUTES)
                && ORIGINAL_CONSTRAINTS
                    .iter()
                    .all(|constraint| fixed.contains(constraint)),
            &[ORDINARY_DURATION_FACT.into()],
        ),
        outcome(
            "portal_is_real_with_fixed_endpoints_before_arrival",
            portal.is_some_and(|rule| {
                rule.origin_endpoint_id == ORIGIN_ENDPOINT
                    && rule.destination_endpoint_id == DESTINATION_ENDPOINT
                    && rule.travel_minutes == PORTAL_TRAVEL_MINUTES
                    && rule.valid_interval.valid_from <= StoryTime(700)
            }) && added.contains(PORTAL_EXISTS_CONSTRAINT)
                && added.contains(PORTAL_ROUTE_CONSTRAINT)
                && edge_ids.contains(PORTAL_EXISTS_EDGE)
                && edge_ids.contains(PORTAL_ROUTE_EDGE),
            &[PORTAL_EXISTS_EDGE.into(), PORTAL_ROUTE_EDGE.into()],
        ),
        outcome(
            "portal_activation_has_a_consumed_cost",
            portal.is_some_and(|rule| {
                rule.activation_cost == Some(TravelActivationCost::ConsumedActivationCharge)
            }) && added.contains(PORTAL_COST_CONSTRAINT)
                && edge_ids.contains(PORTAL_COST_EDGE),
            &[PORTAL_COST_EDGE.into()],
        ),
        outcome(
            "portal_capacity_and_cooldown_are_bounded",
            portal.is_some_and(|rule| {
                rule.passenger_limit == Some(PORTAL_PASSENGER_LIMIT)
                    && rule.cooldown_minutes == Some(PORTAL_COOLDOWN_MINUTES)
            }) && added.contains(PORTAL_CAPACITY_CONSTRAINT)
                && added.contains(PORTAL_COOLDOWN_CONSTRAINT)
                && edge_ids.contains(PORTAL_CAPACITY_EDGE)
                && edge_ids.contains(PORTAL_COOLDOWN_EDGE),
            &[PORTAL_CAPACITY_EDGE.into(), PORTAL_COOLDOWN_EDGE.into()],
        ),
        outcome(
            "long_route_pursuit_tension_is_preserved",
            ordinary.is_some_and(|rule| rule.preserves_pursuit_pressure)
                && portal.is_some_and(|rule| rule.preserves_pursuit_pressure)
                && added.contains(PURSUIT_PRESSURE_CONSTRAINT)
                && edge_ids.contains(PURSUIT_PRESSURE_EDGE),
            &[PURSUIT_PRESSURE_EDGE.into()],
        ),
    ]
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
#[path = "repair_shadow_travel_tests.rs"]
mod tests;
