use std::borrow::Cow;

use compact_str::CompactString;
use phoenix_semantic_v2::{
    BeliefSourceKind, BeliefStateAtom, BeliefStateKind, CausalClaimStatus, CausalEdgeAddition,
    CausalEdgeId, CausalRelationKind, CausalScopeSidecar, MemoryClaimStatus, MemoryScopeSidecar,
    MemoryStateRecord, TemporalScopeSidecar, TemporalTruthStatus,
};
use phoenix_types::{
    BiTemporalWindow, CausalKind, ConstraintKind, CoveragePlane, EntityId, EventId, FactId,
    FactValue, Polarity, RepairTemplateKind, SceneId, SemanticNodeRef, StateKind, StoryInterval,
    StoryMutation, StoryTime,
};
use serde::{Deserialize, Serialize};

use crate::repair_shadow::{build_shadow_snapshot, digest, validation_edit};
use crate::repair_simulation::simulate_repair_candidate_with_coverage;
use crate::{
    EvidenceRef, GraphEditOperation, ProposedEdit, RepairSimulationInput, RequirementDependency,
    RequirementTruthRef, RevisionEdgeRecord, RevisionFactRecord, RevisionRequirementRecord,
    RevisionRequirementSidecar, RevisionStateRecord, SceneCoverageRequest, SemanticDelta,
    ShadowSemanticRepairError, ShadowSemanticRepairReceipt, ShadowSemanticRepairResult, StateRef,
    SHADOW_SEMANTIC_REPAIR_SCHEMA,
};

#[path = "repair_shadow_possession_validation.rs"]
mod possession_validation;
use possession_validation::validate_outcomes;

pub const HAZEL_KEY_DIRECTIVE_ID: &str = "edit:rebind_vault_key_use_and_suspicion_to_hazel";

const KEY_OBJECT: &str = "object:chronal_key";
const POSSESSION_STATE_KIND: &str = "possession:chronal_key";
const PRESENCE_STATE_KIND: &str = "location:vault";
const OPERATOR_STATE_KIND: &str = "action:chronal_key_use";
const KAI_KNOWS_FACT: &str = "fact:kai_knows_hazel_has_chronal_key";
const COOPERATION_FACT: &str = "fact:kai_vault_role_depends_on_hazel";
const SUSPICION_FACT: &str = "fact:silas_suspects_hazel_for_key_possession";
const FALSE_RUMOR_FACT: &str = "fact:duplicate_chronal_key_rumor_is_false";

const POSSESSION_CONSTRAINT: &str = "constraint:repair:possession:hazel_owns_unique_key";
const PRESENCE_CONSTRAINT: &str = "constraint:repair:possession:hazel_present_at_vault";
const OPERATOR_CONSTRAINT: &str = "constraint:repair:possession:hazel_uses_key";
const KNOWLEDGE_CONSTRAINT: &str = "constraint:repair:possession:kai_knows_owner";
const COOPERATION_CONSTRAINT: &str = "constraint:repair:possession:kai_depends_on_hazel";
const SUSPICION_CONSTRAINT: &str = "constraint:repair:possession:suspicion_targets_hazel";
const FALSE_RUMOR_CONSTRAINT: &str = "constraint:repair:possession:duplicate_rumor_false";

const POSSESSION_EDGE: &str = "causal:repair:possession:hazel_brings_unique_key";
const PRESENCE_EDGE: &str = "causal:repair:possession:hazel_accompanies_kai";
const OPERATOR_EDGE: &str = "causal:repair:possession:hazel_operates_key";
const KNOWLEDGE_EDGE: &str = "causal:repair:possession:kai_knows_hazel_owner";
const COOPERATION_EDGE: &str = "causal:repair:possession:kai_trusts_hazel_cooperation";
const SUSPICION_EDGE: &str = "causal:repair:possession:silas_suspects_hazel";
const FALSE_RUMOR_EDGE: &str = "causal:repair:possession:duplicate_key_rumor_rejected";

const KAI_KNOWS_BELIEF: &str = "belief:repair:kai_knows_hazel_owns_key";
const KAI_TRUSTS_BELIEF: &str = "belief:repair:kai_trusts_hazel_key_use";
const SILAS_SUSPICION_BELIEF: &str = "belief:repair:silas_suspects_hazel_key_owner";
const DUPLICATE_RUMOR_BELIEF: &str = "belief:repair:duplicate_key_rumor_contradicted";
const OBJECT_RULE_ID: &str = "identity-rule:chronal-key:unique";

const RUMOR_SCENE: &str = "scene:chapter_8_duplicate_key_rumor";
const VAULT_SCENE: &str = "scene:chapter_9_kai_opens_vault";
const SUSPICION_SCENE: &str = "scene:chapter_10_silas_suspects_kai";

const ORIGINAL_CONSTRAINTS: [&str; 2] = [
    "constraint:possession:suspicion_support",
    "constraint:possession:vault",
];
const TARGET_SCENES: [&str; 3] = [SUSPICION_SCENE, RUMOR_SCENE, VAULT_SCENE];
const ADDED_CONSTRAINTS: [&str; 7] = [
    FALSE_RUMOR_CONSTRAINT,
    POSSESSION_CONSTRAINT,
    PRESENCE_CONSTRAINT,
    OPERATOR_CONSTRAINT,
    COOPERATION_CONSTRAINT,
    KNOWLEDGE_CONSTRAINT,
    SUSPICION_CONSTRAINT,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DuplicateClaimStatus {
    FalseRumor,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectIdentityRuleRecord {
    pub rule_id: CompactString,
    pub object_id: CompactString,
    pub unique_identity: bool,
    pub duplicate_claim_status: DuplicateClaimStatus,
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
        HAZEL_KEY_DIRECTIVE_ID,
    )?;
    let validation_edit = validation_edit(edit, input.requirements, &ORIGINAL_CONSTRAINTS)?;
    let coverage_requests = coverage_after_identity_rebuild(&input)?;
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
        directive_id: HAZEL_KEY_DIRECTIVE_ID.into(),
        committed_base_digest,
        shadow_snapshot_digest: shadow_snapshot.digest(),
        compiled_delta_digest,
        shadow_sidecar_digest: compiled_delta_digest,
        removed_constraint_ids: ORIGINAL_CONSTRAINTS.map(CompactString::from).to_vec(),
        added_constraint_ids: ADDED_CONSTRAINTS.map(CompactString::from).to_vec(),
        rebuilt_planes: vec![
            CoveragePlane::Possession,
            CoveragePlane::Identity,
            CoveragePlane::Belief,
            CoveragePlane::Location,
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
    if edit.edit_id.0.as_str() != HAZEL_KEY_DIRECTIVE_ID
        || edit.template != RepairTemplateKind::RebindPossessionDependentAction
    {
        return Err(ShadowSemanticRepairError::UnsupportedDirective(
            edit.edit_id.0.clone(),
        ));
    }
    let operation_matches = matches!(
        edit.operations.as_slice(),
        [GraphEditOperation::ApplyAuthorDirective { directive_id, required_outcomes, .. }]
            if directive_id.as_str() == HAZEL_KEY_DIRECTIVE_ID
                && required_outcomes.len() == 5
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
            fact(KAI_KNOWS_FACT, 800),
            fact(COOPERATION_FACT, 900),
            fact(SUSPICION_FACT, 1000),
            fact(FALSE_RUMOR_FACT, 800),
        ]
        .into_iter()
        .map(|record| SemanticDelta::AddFact { record }),
    );
    deltas.extend(
        [state(&specs[0]), state(&specs[1]), state(&specs[2])]
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
        beliefs()
            .into_iter()
            .map(|record| SemanticDelta::AddBeliefAtom { record }),
    );
    deltas.extend(
        replacements
            .causal_edges
            .into_iter()
            .map(|record| SemanticDelta::AddCausalEdge { record }),
    );
    deltas.push(SemanticDelta::AddObjectIdentityRule {
        record: object_identity_rule(),
    });
    deltas.push(SemanticDelta::AssertStateBoundary {
        subject_id: EntityId("entity:kai".to_owned()),
        state_kind: POSSESSION_STATE_KIND.into(),
        replacement: FactValue::Entity(EntityId("entity:hazel".to_owned())),
        valid_from: StoryTime(600),
    });
    deltas.push(SemanticDelta::ResolveCoverageRequirement {
        scene_id: SceneId(RUMOR_SCENE.into()),
        removed_required_planes: vec![CoveragePlane::Possession, CoveragePlane::Identity],
        rationale: "Hazel ownership and a unique-object false-rumor rule are present".into(),
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
    truth_ref: RequirementTruthRef,
}

fn specs() -> [Spec; 7] {
    [
        state_spec(
            POSSESSION_CONSTRAINT,
            "entity:hazel",
            POSSESSION_STATE_KIND,
            FactValue::Entity(EntityId("entity:hazel".to_owned())),
            VAULT_SCENE,
            900,
            POSSESSION_EDGE,
            "event:hazel_brings_chronal_key",
            ConstraintKind::RequiresPossession,
        ),
        state_spec(
            PRESENCE_CONSTRAINT,
            "entity:hazel",
            PRESENCE_STATE_KIND,
            FactValue::Text("present".into()),
            VAULT_SCENE,
            900,
            PRESENCE_EDGE,
            "event:hazel_accompanies_kai_to_vault",
            ConstraintKind::RequiresReachability,
        ),
        state_spec(
            OPERATOR_CONSTRAINT,
            "entity:hazel",
            OPERATOR_STATE_KIND,
            FactValue::Text("operator".into()),
            VAULT_SCENE,
            900,
            OPERATOR_EDGE,
            "event:hazel_uses_chronal_key",
            ConstraintKind::RequiresState,
        ),
        belief_spec(
            KNOWLEDGE_CONSTRAINT,
            KAI_KNOWS_FACT,
            VAULT_SCENE,
            900,
            KNOWLEDGE_EDGE,
            "event:kai_accepts_hazel_as_key_owner",
            KAI_KNOWS_BELIEF,
        ),
        causal_spec(
            COOPERATION_CONSTRAINT,
            COOPERATION_FACT,
            VAULT_SCENE,
            900,
            COOPERATION_EDGE,
            "event:kai_depends_on_hazel_cooperation",
        ),
        causal_spec(
            SUSPICION_CONSTRAINT,
            SUSPICION_FACT,
            SUSPICION_SCENE,
            1000,
            SUSPICION_EDGE,
            "event:silas_redirects_suspicion_to_hazel",
        ),
        causal_spec(
            FALSE_RUMOR_CONSTRAINT,
            FALSE_RUMOR_FACT,
            RUMOR_SCENE,
            800,
            FALSE_RUMOR_EDGE,
            "event:duplicate_key_rumor_is_disproven",
        ),
    ]
}

#[allow(clippy::too_many_arguments)]
fn state_spec(
    constraint: &'static str,
    subject: &'static str,
    state_kind: &'static str,
    expected: FactValue,
    scene: &'static str,
    time: i64,
    edge: &'static str,
    event: &'static str,
    kind: ConstraintKind,
) -> Spec {
    Spec {
        constraint,
        dependency: RequirementDependency::State {
            state_ref: StateRef {
                subject_id: EntityId(subject.to_owned()),
                state_kind: StateKind(state_kind.into()),
            },
        },
        expected,
        scene,
        time,
        edge,
        event,
        kind,
        truth_ref: RequirementTruthRef::MemoryState {
            state_id: format!("memory:{constraint}").into(),
        },
    }
}

#[allow(clippy::too_many_arguments)]
fn belief_spec(
    constraint: &'static str,
    fact_id: &'static str,
    scene: &'static str,
    time: i64,
    edge: &'static str,
    event: &'static str,
    belief_id: &'static str,
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
        kind: ConstraintKind::RequiresKnowledge,
        truth_ref: RequirementTruthRef::Belief {
            belief_id: belief_id.into(),
        },
    }
}

#[allow(clippy::too_many_arguments)]
fn causal_spec(
    constraint: &'static str,
    fact_id: &'static str,
    scene: &'static str,
    time: i64,
    edge: &'static str,
    event: &'static str,
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
        kind: ConstraintKind::CausalSupport,
        truth_ref: RequirementTruthRef::CausalEdge {
            edge_id: edge.into(),
        },
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
        memory_state(&specs[2]),
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
    RevisionRequirementRecord {
        constraint_id: spec.constraint.into(),
        dependency: spec.dependency.clone(),
        expected_value: spec.expected.clone(),
        dependent_scene_id: SceneId(spec.scene.into()),
        kind: spec.kind,
        valid_interval: interval(spec.time),
        truth_ref: spec.truth_ref.clone(),
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
        interval: interval(time),
    }
}

fn state(spec: &Spec) -> RevisionStateRecord {
    let RequirementDependency::State { state_ref } = &spec.dependency else {
        unreachable!("possession state spec")
    };
    RevisionStateRecord {
        state_ref: state_ref.clone(),
        value: spec.expected.clone(),
        interval: interval(spec.time),
    }
}

fn memory_state(spec: &Spec) -> MemoryStateRecord {
    let RequirementDependency::State { state_ref } = &spec.dependency else {
        unreachable!("possession memory state")
    };
    let (value, value_entity_id) = match &spec.expected {
        FactValue::Entity(entity) => (entity.0.to_string(), Some(entity.clone())),
        FactValue::Text(value) => (value.to_string(), None),
        _ => unreachable!("possession state value"),
    };
    MemoryStateRecord {
        state_id: format!("memory:{}", spec.constraint),
        entity_id: state_ref.subject_id.clone(),
        slot_key: state_ref.state_kind.0.to_string(),
        value,
        value_entity_id,
        status: MemoryClaimStatus::Active,
        source_class: "author-confirmed-possession-rebind".to_owned(),
        confidence_millis: 1000,
        temporal: window(spec.time),
        claim_ids: vec![author_evidence(spec.constraint)],
    }
}

fn beliefs() -> [BeliefStateAtom; 4] {
    [
        belief(
            KAI_KNOWS_BELIEF,
            KAI_KNOWS_FACT,
            "entity:kai",
            BeliefStateKind::Knows,
            TemporalTruthStatus::Asserted,
            800,
        ),
        belief(
            KAI_TRUSTS_BELIEF,
            COOPERATION_FACT,
            "entity:kai",
            BeliefStateKind::Believes,
            TemporalTruthStatus::Asserted,
            800,
        ),
        belief(
            SILAS_SUSPICION_BELIEF,
            SUSPICION_FACT,
            "entity:silas",
            BeliefStateKind::Believes,
            TemporalTruthStatus::Inferred,
            1000,
        ),
        belief(
            DUPLICATE_RUMOR_BELIEF,
            FALSE_RUMOR_FACT,
            "entity:rumor_network",
            BeliefStateKind::Reported,
            TemporalTruthStatus::Contradicted,
            800,
        ),
    ]
}

fn belief(
    belief_id: &str,
    fact_id: &str,
    observer: &str,
    kind: BeliefStateKind,
    truth_status: TemporalTruthStatus,
    time: i64,
) -> BeliefStateAtom {
    BeliefStateAtom {
        belief_id: belief_id.to_owned(),
        document_id: HAZEL_KEY_DIRECTIVE_ID.to_owned(),
        proposition_id: Some(fact_id.to_owned()),
        observer_entity_id: Some(EntityId(observer.to_owned())),
        kind,
        truth_status,
        source_kind: BeliefSourceKind::Attribution,
        label: fact_id.to_owned(),
        confidence_millis: 1000,
        temporal: window(time),
        evidence_refs: vec![author_evidence(fact_id)],
        ..BeliefStateAtom::default()
    }
}

fn object_identity_rule() -> ObjectIdentityRuleRecord {
    ObjectIdentityRuleRecord {
        rule_id: OBJECT_RULE_ID.into(),
        object_id: KEY_OBJECT.into(),
        unique_identity: true,
        duplicate_claim_status: DuplicateClaimStatus::FalseRumor,
        valid_interval: interval(0),
        evidence_id: author_evidence(FALSE_RUMOR_CONSTRAINT).into(),
    }
}

fn causal_edge(spec: &Spec, generation: u64) -> CausalEdgeAddition {
    CausalEdgeAddition {
        edge_id: CausalEdgeId(spec.edge.to_owned()),
        case_id: HAZEL_KEY_DIRECTIVE_ID.to_owned(),
        document_id: HAZEL_KEY_DIRECTIVE_ID.to_owned(),
        source: SemanticNodeRef::Event(EventId(spec.event.to_owned())),
        canonical_cause_event_id: None,
        target: SemanticNodeRef::Event(EventId(spec.scene.to_owned())),
        canonical_effect_event_id: None,
        kind: CausalKind::ConditionFor,
        relation_kind: CausalRelationKind::EnablingCondition,
        status: CausalClaimStatus::Active,
        first_seen_revision: generation,
        latest_decision_id: None,
        confidence_millis: 1000,
        cue: Some("author-confirmed unique-key possession rebind".to_owned()),
        attributed_to: Some(EntityId("entity:hazel".to_owned())),
        polarity: Polarity::Positive,
        claim_atom_ids: Vec::new(),
        evidence_refs: vec![author_evidence(spec.constraint)],
        effective_interval: window(spec.time),
        observation_interval: window(spec.time),
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
}

fn coverage_after_identity_rebuild(
    input: &RepairSimulationInput<'_>,
) -> Result<Vec<SceneCoverageRequest>, ShadowSemanticRepairError> {
    let rumor = input
        .original_report
        .authoritative_impacts
        .iter()
        .find(|impact| impact.scene_id.0 == RUMOR_SCENE)
        .ok_or_else(|| ShadowSemanticRepairError::MalformedDirective(RUMOR_SCENE.into()))?;
    let missing = &rumor.coverage.missing_required_planes;
    if !missing.contains(&CoveragePlane::Possession) || !missing.contains(&CoveragePlane::Identity)
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

fn interval(valid_from: i64) -> StoryInterval {
    StoryInterval {
        valid_from: StoryTime(valid_from),
        valid_to_exclusive: None,
    }
}

fn window(valid_from: i64) -> BiTemporalWindow {
    BiTemporalWindow {
        valid_from: Some(valid_from),
        valid_to: None,
        recorded_from: Some(0),
        recorded_to: None,
    }
}

fn author_evidence(id: &str) -> String {
    format!("author-directive:{id}")
}

#[cfg(test)]
#[path = "repair_shadow_possession_tests.rs"]
mod tests;
