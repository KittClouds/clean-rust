use std::borrow::Cow;
use std::collections::BTreeSet;

use compact_str::{format_compact, CompactString};
use phoenix_semantic_v2::{
    BeliefSourceKind, BeliefStateAtom, BeliefStateKind, CausalClaimStatus, CausalEdgeAddition,
    CausalEdgeId, CausalRelationKind, CausalScopeSidecar, MemoryStateRecord,
    RelationshipMemoryLedger, TemporalConstraintRecord, TemporalScopeSidecar, TemporalTruthStatus,
};
use phoenix_types::{
    BiTemporalWindow, CausalKind, ConstraintKind, CoveragePlane, EntityId, EventId, FactId,
    FactValue, GraphTruthDigest, Polarity, RepairTemplateKind, SceneId, SemanticNodeRef,
    StoryInterval, StoryMutation, StoryTime,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{
    simulate_repair_candidate, EvidenceRef, GraphEditOperation, NamedSidecarDigest, ProposedEdit,
    RepairCandidate, RepairSimulationError, RepairSimulationInput, RequirementDependency,
    RequirementTruthRef, RevisionEdgeRecord, RevisionFactRecord, RevisionGraphSnapshot,
    RevisionRequirementRecord, RevisionRequirementSidecar,
};

pub const SHADOW_SEMANTIC_REPAIR_SCHEMA: &str = "phoenix.shadow-semantic-repair/v1";
pub const DELAYED_REVEAL_DIRECTIVE_ID: &str = "edit:reassign_causal_attribution:iriane_event_trail";

const SILAS_KNOWS_KAI: &str = "fact:silas_knows_kai";
const IRIANE_TRAIL_FACT: &str = "fact:iriane_independent_event_trail";
const IRIANE_SIGNATURE_FACT: &str = "fact:iriane_recognizes_kai_temporal_signature";
const HAZEL_FALSE_THEORY_FACT: &str = "fact:hazel_silas_theory_is_false";
const IRIANE_TRAIL_CONSTRAINT: &str = "constraint:repair:delayed_reveal:iriane_event_trail";
const IRIANE_SIGNATURE_CONSTRAINT: &str =
    "constraint:repair:delayed_reveal:iriane_signature_knowledge";
const HAZEL_FALSE_THEORY_CONSTRAINT: &str =
    "constraint:repair:delayed_reveal:hazel_false_suspicion";
const IRIANE_TRAIL_EDGE: &str = "causal:repair:iriane_event_trail";
const HAZEL_FALSE_THEORY_EDGE: &str = "causal:repair:hazel_false_suspicion";
const IRIANE_SIGNATURE_BELIEF: &str = "belief:repair:iriane_temporal_signature";

const ORIGINAL_CONSTRAINTS: [&str; 3] = [
    "constraint:delayed_reveal:hazel_support",
    "constraint:delayed_reveal:iriane_knowledge",
    "constraint:delayed_reveal:signature_knowledge",
];
const TARGET_SCENES: [&str; 3] = [
    "scene:chapter_10_hazel_assumption",
    "scene:chapter_5_iriane_assignment",
    "scene:chapter_8_temporal_signature",
];

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum SemanticDelta {
    RemoveRequirement {
        constraint_id: CompactString,
    },
    AddFact {
        record: RevisionFactRecord,
    },
    AddGraphEdge {
        record: RevisionEdgeRecord,
    },
    AddState {
        record: crate::RevisionStateRecord,
    },
    AddRequirement {
        record: RevisionRequirementRecord,
    },
    AddBeliefAtom {
        record: BeliefStateAtom,
    },
    AddCausalEdge {
        record: CausalEdgeAddition,
    },
    AddCapabilityRule {
        record: crate::CapabilityRuleRecord,
    },
    AddTravelRule {
        record: crate::TravelRuleRecord,
    },
    AddMemoryState {
        record: MemoryStateRecord,
    },
    AddTemporalConstraint {
        record: TemporalConstraintRecord,
    },
    AddRelationshipLedger {
        record: RelationshipMemoryLedger,
    },
    AddObjectIdentityRule {
        record: crate::ObjectIdentityRuleRecord,
    },
    AssertKnowledgeBoundary {
        fact_id: FactId,
        first_valid_at: StoryTime,
    },
    AssertFactSupersession {
        fact_id: FactId,
        replacement: FactValue,
        valid_from: StoryTime,
    },
    AssertStateBoundary {
        subject_id: EntityId,
        state_kind: CompactString,
        replacement: FactValue,
        valid_from: StoryTime,
    },
    ResolveCoverageRequirement {
        scene_id: SceneId,
        removed_required_planes: Vec<CoveragePlane>,
        rationale: CompactString,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ShadowOutcomeValidation {
    pub outcome_id: CompactString,
    pub satisfied: bool,
    pub evidence_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ShadowSemanticRepairReceipt {
    pub schema: CompactString,
    pub directive_id: CompactString,
    pub committed_base_digest: GraphTruthDigest,
    pub shadow_snapshot_digest: GraphTruthDigest,
    pub compiled_delta_digest: GraphTruthDigest,
    pub shadow_sidecar_digest: GraphTruthDigest,
    pub removed_constraint_ids: Vec<CompactString>,
    pub added_constraint_ids: Vec<CompactString>,
    pub rebuilt_planes: Vec<CoveragePlane>,
    pub copy_on_write_clones: u8,
    pub outcomes: Vec<ShadowOutcomeValidation>,
    pub all_outcomes_satisfied: bool,
    pub full_shadow_revalidation_completed: bool,
    pub committed_base_unchanged: bool,
    pub no_truth_writes: bool,
    pub deterministic: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ShadowSemanticRepairResult {
    pub candidate: RepairCandidate,
    pub semantic_deltas: Vec<SemanticDelta>,
    pub receipt: ShadowSemanticRepairReceipt,
}

#[derive(Debug, Error)]
pub enum ShadowSemanticRepairError {
    #[error("unsupported shadow semantic directive {0}")]
    UnsupportedDirective(CompactString),
    #[error("malformed author directive candidate: {0}")]
    MalformedDirective(CompactString),
    #[error("missing required shadow truth plane {0}")]
    MissingTruthPlane(&'static str),
    #[error("missing source constraint {0}")]
    MissingConstraint(CompactString),
    #[error("shadow semantic serialization failed: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error(transparent)]
    Overlay(#[from] crate::CounterfactualOverlayError),
    #[error(transparent)]
    Simulation(#[from] RepairSimulationError),
}

pub fn execute_shadow_semantic_repair(
    input: RepairSimulationInput<'_>,
    edit: &ProposedEdit,
) -> Result<ShadowSemanticRepairResult, ShadowSemanticRepairError> {
    if edit.edit_id.0.as_str() == crate::MARA_PRIOR_RECORD_DIRECTIVE_ID {
        return crate::repair_shadow_prior_record::execute(input, edit);
    }
    if edit.edit_id.0.as_str() == crate::TAMSIN_DECEPTION_DIRECTIVE_ID {
        return crate::repair_shadow_deception::execute(input, edit);
    }
    if edit.edit_id.0.as_str() == crate::KAI_POWER_OVERDRAW_DIRECTIVE_ID {
        return crate::repair_shadow_capability::execute(input, edit);
    }
    if edit.edit_id.0.as_str() == crate::CONSTRAINED_PORTAL_DIRECTIVE_ID {
        return crate::repair_shadow_travel::execute(input, edit);
    }
    if edit.edit_id.0.as_str() == crate::HAZEL_ESPIONAGE_DIRECTIVE_ID {
        return crate::repair_shadow_relationship::execute(input, edit);
    }
    if edit.edit_id.0.as_str() == crate::HAZEL_KEY_DIRECTIVE_ID {
        return crate::repair_shadow_possession::execute(input, edit);
    }
    execute_delayed_reveal_shadow(input, edit)
}

fn execute_delayed_reveal_shadow(
    input: RepairSimulationInput<'_>,
    edit: &ProposedEdit,
) -> Result<ShadowSemanticRepairResult, ShadowSemanticRepairError> {
    validate_delayed_reveal_contract(edit)?;
    let committed_base_digest = input.base.digest();
    let semantic_deltas =
        compile_delayed_reveal_deltas(input.requirements, input.base.generation().0)?;
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
        DELAYED_REVEAL_DIRECTIVE_ID,
    )?;
    let validation_edit = validation_edit(edit, input.requirements, &ORIGINAL_CONSTRAINTS)?;
    let mut candidate = simulate_repair_candidate(
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
    )?;
    candidate.edit = edit.clone();
    candidate.validation_receipt.candidate_digest = digest(edit)?;

    let outcomes = validate_delayed_reveal_outcomes(
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
        directive_id: DELAYED_REVEAL_DIRECTIVE_ID.into(),
        committed_base_digest,
        shadow_snapshot_digest: shadow_snapshot.digest(),
        compiled_delta_digest,
        shadow_sidecar_digest: compiled_delta_digest,
        removed_constraint_ids: ORIGINAL_CONSTRAINTS.map(CompactString::from).to_vec(),
        added_constraint_ids: [
            HAZEL_FALSE_THEORY_CONSTRAINT.into(),
            IRIANE_TRAIL_CONSTRAINT.into(),
            IRIANE_SIGNATURE_CONSTRAINT.into(),
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

fn validate_delayed_reveal_contract(edit: &ProposedEdit) -> Result<(), ShadowSemanticRepairError> {
    if edit.edit_id.0.as_str() != DELAYED_REVEAL_DIRECTIVE_ID
        || edit.template != RepairTemplateKind::ReassignCausalAttribution
    {
        return Err(ShadowSemanticRepairError::UnsupportedDirective(
            edit.edit_id.0.clone(),
        ));
    }
    let operation_matches = matches!(
        edit.operations.as_slice(),
        [GraphEditOperation::ApplyAuthorDirective { directive_id, required_outcomes, .. }]
            if directive_id.as_str() == DELAYED_REVEAL_DIRECTIVE_ID
                && !required_outcomes.is_empty()
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

fn compile_delayed_reveal_deltas(
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
    let facts = [
        fact(IRIANE_SIGNATURE_FACT),
        fact(IRIANE_TRAIL_FACT),
        fact(HAZEL_FALSE_THEORY_FACT),
    ];
    deltas.extend(
        facts
            .iter()
            .cloned()
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
    deltas.push(SemanticDelta::AddBeliefAtom {
        record: replacements.belief,
    });
    deltas.extend(
        replacements
            .causal_edges
            .into_iter()
            .map(|record| SemanticDelta::AddCausalEdge { record }),
    );
    deltas.push(SemanticDelta::AssertKnowledgeBoundary {
        fact_id: SILAS_KNOWS_KAI.into(),
        first_valid_at: StoryTime(1200),
    });
    Ok(deltas)
}

struct ReplacementRecords {
    requirements: [RevisionRequirementRecord; 3],
    edges: [RevisionEdgeRecord; 3],
    belief: BeliefStateAtom,
    causal_edges: [CausalEdgeAddition; 2],
}

fn replacement_records(generation: u64) -> ReplacementRecords {
    let trail_requirement = requirement(
        IRIANE_TRAIL_CONSTRAINT,
        IRIANE_TRAIL_FACT,
        "scene:chapter_5_iriane_assignment",
        ConstraintKind::CausalSupport,
        500,
        RequirementTruthRef::CausalEdge {
            edge_id: IRIANE_TRAIL_EDGE.into(),
        },
    );
    let signature_requirement = requirement(
        IRIANE_SIGNATURE_CONSTRAINT,
        IRIANE_SIGNATURE_FACT,
        "scene:chapter_8_temporal_signature",
        ConstraintKind::RequiresKnowledge,
        800,
        RequirementTruthRef::Belief {
            belief_id: IRIANE_SIGNATURE_BELIEF.into(),
        },
    );
    let hazel_requirement = requirement(
        HAZEL_FALSE_THEORY_CONSTRAINT,
        HAZEL_FALSE_THEORY_FACT,
        "scene:chapter_10_hazel_assumption",
        ConstraintKind::CausalSupport,
        1000,
        RequirementTruthRef::CausalEdge {
            edge_id: HAZEL_FALSE_THEORY_EDGE.into(),
        },
    );
    ReplacementRecords {
        edges: [
            graph_edge(&trail_requirement),
            graph_edge(&signature_requirement),
            graph_edge(&hazel_requirement),
        ],
        requirements: [trail_requirement, signature_requirement, hazel_requirement],
        belief: BeliefStateAtom {
            belief_id: IRIANE_SIGNATURE_BELIEF.to_owned(),
            document_id: DELAYED_REVEAL_DIRECTIVE_ID.to_owned(),
            proposition_id: Some(IRIANE_SIGNATURE_FACT.to_owned()),
            observer_entity_id: Some(EntityId("entity:iriane".to_owned())),
            kind: BeliefStateKind::Knows,
            truth_status: TemporalTruthStatus::Inferred,
            source_kind: BeliefSourceKind::DirectObservation,
            label: "Iriane recognizes Kai's temporal signature from her evidence".to_owned(),
            confidence_millis: 1000,
            temporal: wide_window(),
            evidence_refs: vec![author_evidence(IRIANE_SIGNATURE_CONSTRAINT)],
            ..BeliefStateAtom::default()
        },
        causal_edges: [
            causal_edge(
                IRIANE_TRAIL_EDGE,
                "event:missing_friend_past_action_consequence",
                "scene:chapter_5_iriane_assignment",
                "entity:iriane",
                IRIANE_TRAIL_CONSTRAINT,
                generation,
            ),
            causal_edge(
                HAZEL_FALSE_THEORY_EDGE,
                "event:hazel_incorrect_silas_suspicion",
                "scene:chapter_10_hazel_assumption",
                "entity:hazel",
                HAZEL_FALSE_THEORY_CONSTRAINT,
                generation,
            ),
        ],
    }
}

fn fact(fact_id: &str) -> RevisionFactRecord {
    RevisionFactRecord {
        fact_id: FactId(fact_id.into()),
        value: FactValue::Boolean(true),
        interval: StoryInterval {
            valid_from: StoryTime(0),
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
        unreachable!("delayed reveal replacement dependencies are facts")
    };
    RevisionEdgeRecord {
        edge_id: requirement.constraint_id.clone(),
        dependency_fact_ids: vec![fact_id.clone()],
        dependency_state_refs: Vec::new(),
    }
}

fn causal_edge(
    edge_id: &str,
    source_event: &str,
    target_event: &str,
    attributed_to: &str,
    constraint_id: &str,
    generation: u64,
) -> CausalEdgeAddition {
    CausalEdgeAddition {
        edge_id: CausalEdgeId(edge_id.to_owned()),
        case_id: DELAYED_REVEAL_DIRECTIVE_ID.to_owned(),
        document_id: DELAYED_REVEAL_DIRECTIVE_ID.to_owned(),
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
        effective_interval: wide_window(),
        observation_interval: wide_window(),
        temporal_certainty_millis: 1000,
        created_at: 1_784_295_149,
    }
}

fn author_evidence(constraint_id: &str) -> String {
    format!("author-directive:{constraint_id}")
}

fn wide_window() -> BiTemporalWindow {
    BiTemporalWindow {
        valid_from: Some(0),
        valid_to: None,
        recorded_from: Some(0),
        recorded_to: None,
    }
}

pub(crate) fn apply_sidecar_deltas(
    deltas: &[SemanticDelta],
    requirements: &mut RevisionRequirementSidecar,
    temporal: &mut TemporalScopeSidecar,
    causal: &mut CausalScopeSidecar,
) {
    for delta in deltas {
        match delta {
            SemanticDelta::AddRequirement { record } => {
                requirements.requirements.push(record.clone());
            }
            SemanticDelta::AddBeliefAtom { record } => {
                temporal.belief_atoms.push(record.clone());
            }
            SemanticDelta::AddCausalEdge { record } => {
                causal.edge_records.push(record.clone());
            }
            SemanticDelta::RemoveRequirement { .. }
            | SemanticDelta::AddFact { .. }
            | SemanticDelta::AddGraphEdge { .. }
            | SemanticDelta::AddCapabilityRule { .. }
            | SemanticDelta::AddTravelRule { .. }
            | SemanticDelta::AddMemoryState { .. }
            | SemanticDelta::AddTemporalConstraint { .. }
            | SemanticDelta::AddState { .. }
            | SemanticDelta::AddRelationshipLedger { .. }
            | SemanticDelta::AddObjectIdentityRule { .. }
            | SemanticDelta::AssertKnowledgeBoundary { .. }
            | SemanticDelta::AssertFactSupersession { .. }
            | SemanticDelta::AssertStateBoundary { .. }
            | SemanticDelta::ResolveCoverageRequirement { .. } => {}
        }
    }
    requirements
        .requirements
        .sort_unstable_by(|left, right| left.constraint_id.cmp(&right.constraint_id));
    temporal
        .belief_atoms
        .sort_unstable_by(|left, right| left.belief_id.cmp(&right.belief_id));
    causal
        .edge_records
        .sort_unstable_by(|left, right| left.edge_id.0.cmp(&right.edge_id.0));
}

pub(crate) fn build_shadow_snapshot(
    base: &RevisionGraphSnapshot,
    deltas: &[SemanticDelta],
    sidecar_digest: GraphTruthDigest,
    directive_id: &str,
) -> Result<RevisionGraphSnapshot, crate::CounterfactualOverlayError> {
    let added_facts = deltas
        .iter()
        .filter(|delta| matches!(delta, SemanticDelta::AddFact { .. }))
        .count();
    let added_edges = deltas
        .iter()
        .filter(|delta| matches!(delta, SemanticDelta::AddGraphEdge { .. }))
        .count();
    let added_states = deltas
        .iter()
        .filter(|delta| matches!(delta, SemanticDelta::AddState { .. }))
        .count();
    let mut facts = Vec::with_capacity(base.facts().len() + added_facts);
    facts.extend_from_slice(base.facts());
    let mut states = Vec::with_capacity(base.states().len() + added_states);
    states.extend_from_slice(base.states());
    let mut edges = Vec::with_capacity(base.edges().len() + added_edges);
    edges.extend_from_slice(base.edges());
    for delta in deltas {
        match delta {
            SemanticDelta::AddFact { record } => facts.push(record.clone()),
            SemanticDelta::AddGraphEdge { record } => edges.push(record.clone()),
            SemanticDelta::AddState { record } => states.push(record.clone()),
            _ => {}
        }
    }
    let mut sidecars = base.sidecar_digests().to_vec();
    sidecars.push(NamedSidecarDigest {
        sidecar_id: format_compact!("shadow:{directive_id}"),
        digest: sidecar_digest,
    });
    RevisionGraphSnapshot::new(base.generation(), facts, states, edges, sidecars)
}

pub(crate) fn validation_edit(
    edit: &ProposedEdit,
    requirements: &RevisionRequirementSidecar,
    removed_constraints: &[&str],
) -> Result<ProposedEdit, ShadowSemanticRepairError> {
    let operations = removed_constraints
        .iter()
        .copied()
        .map(|constraint_id| {
            let row = requirements
                .requirements
                .iter()
                .find(|row| row.constraint_id == constraint_id)
                .ok_or_else(|| {
                    ShadowSemanticRepairError::MissingConstraint(constraint_id.into())
                })?;
            Ok(GraphEditOperation::RemoveRequirementBearingStatement {
                constraint_id: row.constraint_id.clone(),
                scene_id: row.dependent_scene_id.0.clone(),
                evidence: row.evidence.clone(),
            })
        })
        .collect::<Result<Vec<_>, ShadowSemanticRepairError>>()?;
    let mut validation = edit.clone();
    validation.operations = operations;
    Ok(validation)
}

fn validate_delayed_reveal_outcomes(
    mutations: &[StoryMutation],
    requirements: &RevisionRequirementSidecar,
    temporal: &TemporalScopeSidecar,
    causal: &CausalScopeSidecar,
    candidate: &RepairCandidate,
) -> Vec<ShadowOutcomeValidation> {
    let fixed = candidate
        .fixed_constraints
        .iter()
        .map(CompactString::as_str)
        .collect::<BTreeSet<_>>();
    let original_constraints = ORIGINAL_CONSTRAINTS.into_iter().collect::<BTreeSet<_>>();
    let target_scenes = TARGET_SCENES.into_iter().collect::<BTreeSet<_>>();
    let replacement_chain_excludes_silas = requirements.requirements.iter().all(|row| {
        original_constraints.contains(row.constraint_id.as_str())
            || !target_scenes.contains(row.dependent_scene_id.0.as_str())
            || row.dependency.graph_id() != SILAS_KNOWS_KAI
    });
    let silas_removed = ORIGINAL_CONSTRAINTS
        .iter()
        .all(|constraint| fixed.contains(constraint))
        && replacement_chain_excludes_silas;
    let trail = causal.edge_records.iter().find(|edge| {
        edge.edge_id.0 == IRIANE_TRAIL_EDGE
            && edge
                .attributed_to
                .as_ref()
                .is_some_and(|id| id.0 == "entity:iriane")
    });
    let signature = temporal.belief_atoms.iter().find(|belief| {
        belief.belief_id == IRIANE_SIGNATURE_BELIEF
            && belief
                .observer_entity_id
                .as_ref()
                .is_some_and(|id| id.0 == "entity:iriane")
            && belief.truth_status == TemporalTruthStatus::Inferred
    });
    let false_theory = causal.edge_records.iter().find(|edge| {
        edge.edge_id.0 == HAZEL_FALSE_THEORY_EDGE
            && edge
                .attributed_to
                .as_ref()
                .is_some_and(|id| id.0 == "entity:hazel")
    });
    let boundary = mutations.iter().any(|mutation| {
        matches!(
            mutation,
            StoryMutation::ShiftValidity { fact_id, new_interval }
                if fact_id.0 == SILAS_KNOWS_KAI
                    && new_interval.valid_from == StoryTime(1200)
        )
    });
    let added = requirements
        .requirements
        .iter()
        .map(|row| row.constraint_id.as_str())
        .collect::<BTreeSet<_>>();
    vec![
        outcome(
            "silas_removed_from_pre_ch12_chain",
            silas_removed,
            &candidate.fixed_constraints,
        ),
        outcome(
            "iriane_independent_event_trail",
            trail.is_some() && added.contains(IRIANE_TRAIL_CONSTRAINT),
            &[IRIANE_TRAIL_EDGE.into()],
        ),
        outcome(
            "iriane_owns_signature_recognition",
            signature.is_some() && added.contains(IRIANE_SIGNATURE_CONSTRAINT),
            &[IRIANE_SIGNATURE_BELIEF.into()],
        ),
        outcome(
            "hazel_theory_explicitly_false",
            false_theory.is_some() && added.contains(HAZEL_FALSE_THEORY_CONSTRAINT),
            &[HAZEL_FALSE_THEORY_EDGE.into()],
        ),
        outcome(
            "silas_first_knowledge_at_ch12",
            boundary,
            &[SILAS_KNOWS_KAI.into()],
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

pub(crate) fn digest<T: Serialize>(value: &T) -> Result<GraphTruthDigest, serde_json::Error> {
    Ok(GraphTruthDigest(
        *blake3::hash(&serde_json::to_vec(value)?).as_bytes(),
    ))
}

#[cfg(test)]
#[path = "repair_shadow_tests.rs"]
mod tests;
