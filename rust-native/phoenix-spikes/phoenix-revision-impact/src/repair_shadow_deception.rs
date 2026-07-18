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

pub const TAMSIN_DECEPTION_DIRECTIVE_ID: &str =
    "edit:reclassify_testimony_as_hidden_deception:tamsin";

const ORIN_WITNESS_FACT: &str = "fact:orin_actual_bridge_witness";
const TAMSIN_DETAILS_FACT: &str = "fact:tamsin_knows_bridge_details";
const TAMSIN_DECEPTION_FACT: &str = "fact:tamsin_intends_bridge_deception";
const COURT_FALSE_BELIEF_FACT: &str = "fact:court_believes_tamsin_false_testimony";
const DECEPTION_REVEALED_FACT: &str = "fact:tamsin_deception_revealed_later";

const ORIN_WITNESS_CONSTRAINT: &str = "constraint:repair:changed_witness:orin_observed";
const TAMSIN_DETAILS_CONSTRAINT: &str = "constraint:repair:changed_witness:tamsin_details";
const TAMSIN_DECEPTION_CONSTRAINT: &str = "constraint:repair:changed_witness:deliberate_deception";
const COURT_FALSE_BELIEF_CONSTRAINT: &str = "constraint:repair:changed_witness:court_false_belief";
const REVEAL_KNOWLEDGE_CONSTRAINT: &str =
    "constraint:repair:changed_witness:deception_reveal_knowledge";
const REVEAL_CAUSAL_CONSTRAINT: &str = "constraint:repair:changed_witness:deception_reveal_cause";

const ORIN_WITNESS_BELIEF: &str = "belief:repair:orin_observed_bridge_collapse";
const TAMSIN_DETAILS_BELIEF: &str = "belief:repair:tamsin_bridge_details";
const TAMSIN_INTENT_BELIEF: &str = "belief:repair:tamsin_intends_deception";
const COURT_FALSE_BELIEF: &str = "belief:repair:court_believes_tamsin_testimony";
const COURT_REVEAL_BELIEF: &str = "belief:repair:court_learns_tamsin_lied";

const DECEPTION_EDGE: &str = "causal:repair:tamsin_deliberate_testimony";
const COURT_TRUST_EDGE: &str = "causal:repair:tamsin_testimony_motivates_court";
const REVEAL_EDGE: &str = "causal:repair:tamsin_deception_revealed";
const BLIND_SPOT_SCENE: &str = "scene:chapter_8_blind_spot";
const REVEAL_SCENE: &str = "scene:chapter_11_tamsin_deception_reveal";

const ORIGINAL_CONSTRAINTS: [&str; 2] = [
    "constraint:changed_witness:court_motivation",
    "constraint:changed_witness:testimony",
];
const TARGET_SCENES: [&str; 2] = [
    "scene:chapter_7_tamsin_testimony",
    "scene:chapter_9_court_trusts_tamsin",
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
        TAMSIN_DECEPTION_DIRECTIVE_ID,
    )?;
    let validation_edit = validation_edit(edit, input.requirements, &ORIGINAL_CONSTRAINTS)?;
    let coverage_requests = coverage_after_witness_retyping(&input)?;
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
        directive_id: TAMSIN_DECEPTION_DIRECTIVE_ID.into(),
        committed_base_digest,
        shadow_snapshot_digest: shadow_snapshot.digest(),
        compiled_delta_digest,
        shadow_sidecar_digest: compiled_delta_digest,
        removed_constraint_ids: ORIGINAL_CONSTRAINTS.map(CompactString::from).to_vec(),
        added_constraint_ids: [
            COURT_FALSE_BELIEF_CONSTRAINT.into(),
            ORIN_WITNESS_CONSTRAINT.into(),
            REVEAL_CAUSAL_CONSTRAINT.into(),
            REVEAL_KNOWLEDGE_CONSTRAINT.into(),
            TAMSIN_DECEPTION_CONSTRAINT.into(),
            TAMSIN_DETAILS_CONSTRAINT.into(),
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
    if edit.edit_id.0.as_str() != TAMSIN_DECEPTION_DIRECTIVE_ID
        || edit.template != RepairTemplateKind::ReclassifyAssertionAsDeception
    {
        return Err(ShadowSemanticRepairError::UnsupportedDirective(
            edit.edit_id.0.clone(),
        ));
    }
    let operation_matches = matches!(
        edit.operations.as_slice(),
        [GraphEditOperation::ApplyAuthorDirective { directive_id, required_outcomes, .. }]
            if directive_id.as_str() == TAMSIN_DECEPTION_DIRECTIVE_ID
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
            fact(ORIN_WITNESS_FACT, 400),
            fact(TAMSIN_DETAILS_FACT, 400),
            fact(TAMSIN_DECEPTION_FACT, 700),
            fact(COURT_FALSE_BELIEF_FACT, 900),
            fact(DECEPTION_REVEALED_FACT, 1100),
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
    deltas.push(SemanticDelta::AssertFactSupersession {
        fact_id: FactId("fact:tamsin_witnessed_bridge_collapse".into()),
        replacement: FactValue::Entity(EntityId("entity:orin".to_owned())),
        valid_from: StoryTime(400),
    });
    deltas.push(SemanticDelta::ResolveCoverageRequirement {
        scene_id: SceneId(BLIND_SPOT_SCENE.into()),
        removed_required_planes: vec![CoveragePlane::Identity, CoveragePlane::Belief],
        rationale: "Orin is explicitly identified and carries an observed witness record".into(),
    });
    Ok(deltas)
}

struct ReplacementRecords {
    requirements: [RevisionRequirementRecord; 6],
    edges: [RevisionEdgeRecord; 6],
    beliefs: [BeliefStateAtom; 5],
    causal_edges: [CausalEdgeAddition; 3],
}

fn replacement_records(generation: u64) -> ReplacementRecords {
    let requirements = [
        requirement(
            ORIN_WITNESS_CONSTRAINT,
            ORIN_WITNESS_FACT,
            "scene:chapter_7_tamsin_testimony",
            ConstraintKind::RequiresWitness,
            700,
            RequirementTruthRef::Belief {
                belief_id: ORIN_WITNESS_BELIEF.into(),
            },
        ),
        requirement(
            TAMSIN_DETAILS_CONSTRAINT,
            TAMSIN_DETAILS_FACT,
            "scene:chapter_7_tamsin_testimony",
            ConstraintKind::RequiresKnowledge,
            700,
            RequirementTruthRef::Belief {
                belief_id: TAMSIN_DETAILS_BELIEF.into(),
            },
        ),
        requirement(
            TAMSIN_DECEPTION_CONSTRAINT,
            TAMSIN_DECEPTION_FACT,
            "scene:chapter_7_tamsin_testimony",
            ConstraintKind::CausalSupport,
            700,
            RequirementTruthRef::CausalEdge {
                edge_id: DECEPTION_EDGE.into(),
            },
        ),
        requirement(
            COURT_FALSE_BELIEF_CONSTRAINT,
            COURT_FALSE_BELIEF_FACT,
            "scene:chapter_9_court_trusts_tamsin",
            ConstraintKind::Motivation,
            900,
            RequirementTruthRef::CausalEdge {
                edge_id: COURT_TRUST_EDGE.into(),
            },
        ),
        requirement(
            REVEAL_KNOWLEDGE_CONSTRAINT,
            DECEPTION_REVEALED_FACT,
            REVEAL_SCENE,
            ConstraintKind::RequiresKnowledge,
            1100,
            RequirementTruthRef::Belief {
                belief_id: COURT_REVEAL_BELIEF.into(),
            },
        ),
        requirement(
            REVEAL_CAUSAL_CONSTRAINT,
            DECEPTION_REVEALED_FACT,
            REVEAL_SCENE,
            ConstraintKind::CausalSupport,
            1100,
            RequirementTruthRef::CausalEdge {
                edge_id: REVEAL_EDGE.into(),
            },
        ),
    ];
    let edges = requirements.each_ref().map(graph_edge);
    ReplacementRecords {
        requirements,
        edges,
        beliefs: beliefs(),
        causal_edges: [
            causal_edge(
                DECEPTION_EDGE,
                "event:tamsin_chooses_deliberate_lie",
                "scene:chapter_7_tamsin_testimony",
                "entity:tamsin",
                TAMSIN_DECEPTION_CONSTRAINT,
                CausalKind::Enables,
                700,
                generation,
            ),
            causal_edge(
                COURT_TRUST_EDGE,
                "event:tamsin_false_testimony",
                "scene:chapter_9_court_trusts_tamsin",
                "entity:tamsin",
                COURT_FALSE_BELIEF_CONSTRAINT,
                CausalKind::Motivates,
                900,
                generation,
            ),
            causal_edge(
                REVEAL_EDGE,
                "event:orin_evidence_exposes_tamsin_lie",
                REVEAL_SCENE,
                "entity:orin",
                REVEAL_CAUSAL_CONSTRAINT,
                CausalKind::Causes,
                1100,
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
        unreachable!("deception replacement dependencies are facts")
    };
    RevisionEdgeRecord {
        edge_id: requirement.constraint_id.clone(),
        dependency_fact_ids: vec![fact_id.clone()],
        dependency_state_refs: Vec::new(),
    }
}

fn beliefs() -> [BeliefStateAtom; 5] {
    [
        belief(
            ORIN_WITNESS_BELIEF,
            ORIN_WITNESS_FACT,
            "entity:orin",
            BeliefStateKind::Observed,
            TemporalTruthStatus::Observed,
            400,
            ORIN_WITNESS_CONSTRAINT,
        ),
        belief(
            TAMSIN_DETAILS_BELIEF,
            TAMSIN_DETAILS_FACT,
            "entity:tamsin",
            BeliefStateKind::Knows,
            TemporalTruthStatus::Inferred,
            400,
            TAMSIN_DETAILS_CONSTRAINT,
        ),
        belief(
            TAMSIN_INTENT_BELIEF,
            TAMSIN_DECEPTION_FACT,
            "entity:tamsin",
            BeliefStateKind::Intends,
            TemporalTruthStatus::Asserted,
            700,
            TAMSIN_DECEPTION_CONSTRAINT,
        ),
        belief(
            COURT_FALSE_BELIEF,
            COURT_FALSE_BELIEF_FACT,
            "entity:court",
            BeliefStateKind::Believes,
            TemporalTruthStatus::Reported,
            900,
            COURT_FALSE_BELIEF_CONSTRAINT,
        ),
        belief(
            COURT_REVEAL_BELIEF,
            DECEPTION_REVEALED_FACT,
            "entity:court",
            BeliefStateKind::Knows,
            TemporalTruthStatus::Asserted,
            1100,
            REVEAL_KNOWLEDGE_CONSTRAINT,
        ),
    ]
}

fn belief(
    belief_id: &str,
    proposition_id: &str,
    observer_id: &str,
    kind: BeliefStateKind,
    truth_status: TemporalTruthStatus,
    valid_from: i64,
    constraint_id: &str,
) -> BeliefStateAtom {
    BeliefStateAtom {
        belief_id: belief_id.to_owned(),
        document_id: TAMSIN_DECEPTION_DIRECTIVE_ID.to_owned(),
        proposition_id: Some(proposition_id.to_owned()),
        observer_entity_id: Some(EntityId(observer_id.to_owned())),
        kind,
        truth_status,
        source_kind: BeliefSourceKind::Attribution,
        label: proposition_id.to_owned(),
        confidence_millis: 1000,
        temporal: window_from(valid_from),
        evidence_refs: vec![author_evidence(constraint_id)],
        ..BeliefStateAtom::default()
    }
}

#[allow(clippy::too_many_arguments)]
fn causal_edge(
    edge_id: &str,
    source_event: &str,
    target_event: &str,
    attributed_to: &str,
    constraint_id: &str,
    kind: CausalKind,
    valid_from: i64,
    generation: u64,
) -> CausalEdgeAddition {
    CausalEdgeAddition {
        edge_id: CausalEdgeId(edge_id.to_owned()),
        case_id: TAMSIN_DECEPTION_DIRECTIVE_ID.to_owned(),
        document_id: TAMSIN_DECEPTION_DIRECTIVE_ID.to_owned(),
        source: SemanticNodeRef::Event(EventId(source_event.to_owned())),
        canonical_cause_event_id: None,
        target: SemanticNodeRef::Event(EventId(target_event.to_owned())),
        canonical_effect_event_id: None,
        kind,
        relation_kind: if kind == CausalKind::Causes {
            CausalRelationKind::DirectCause
        } else {
            CausalRelationKind::EnablingCondition
        },
        status: CausalClaimStatus::Active,
        first_seen_revision: generation,
        latest_decision_id: None,
        confidence_millis: 1000,
        cue: Some("author-confirmed hidden deception".to_owned()),
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

fn coverage_after_witness_retyping(
    input: &RepairSimulationInput<'_>,
) -> Result<Vec<SceneCoverageRequest>, ShadowSemanticRepairError> {
    let blind_spot = input
        .original_report
        .authoritative_impacts
        .iter()
        .find(|impact| impact.scene_id.0 == BLIND_SPOT_SCENE)
        .ok_or_else(|| ShadowSemanticRepairError::MalformedDirective(BLIND_SPOT_SCENE.into()))?;
    if !blind_spot
        .coverage
        .missing_required_planes
        .contains(&CoveragePlane::Identity)
        || !blind_spot
            .coverage
            .missing_required_planes
            .contains(&CoveragePlane::Belief)
    {
        return Err(ShadowSemanticRepairError::MalformedDirective(
            BLIND_SPOT_SCENE.into(),
        ));
    }
    Ok(input
        .original_report
        .authoritative_impacts
        .iter()
        .filter(|impact| impact.scene_id.0 != BLIND_SPOT_SCENE)
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
    let mutation = mutations.iter().any(|mutation| {
        matches!(
            mutation,
            StoryMutation::SupersedeFact {
                fact_id,
                replacement: FactValue::Entity(entity),
                valid_from,
            } if fact_id.0 == "fact:tamsin_witnessed_bridge_collapse"
                && entity.0 == "entity:orin"
                && *valid_from == StoryTime(400)
        )
    });
    let belief = |belief_id: &str| {
        temporal
            .belief_atoms
            .iter()
            .find(|belief| belief.belief_id == belief_id)
    };
    let edge = |edge_id: &str| {
        causal
            .edge_records
            .iter()
            .find(|edge| edge.edge_id.0 == edge_id)
    };
    let old_constraints_fixed = ORIGINAL_CONSTRAINTS
        .iter()
        .all(|constraint| fixed.contains(constraint));
    let orin = belief(ORIN_WITNESS_BELIEF);
    let details = belief(TAMSIN_DETAILS_BELIEF);
    let intent = belief(TAMSIN_INTENT_BELIEF);
    let court = belief(COURT_FALSE_BELIEF);
    let reveal = belief(COURT_REVEAL_BELIEF);
    vec![
        outcome(
            "orin_is_authoritative_witness",
            mutation
                && orin.is_some_and(|row| {
                    row.kind == BeliefStateKind::Observed
                        && row
                            .observer_entity_id
                            .as_ref()
                            .is_some_and(|id| id.0 == "entity:orin")
                })
                && added.contains(ORIN_WITNESS_CONSTRAINT),
            &[ORIN_WITNESS_BELIEF.into()],
        ),
        outcome(
            "tamsin_did_not_need_to_witness",
            old_constraints_fixed,
            &candidate.fixed_constraints,
        ),
        outcome(
            "tamsin_knows_details_and_intends_deception",
            details.is_some()
                && intent.is_some_and(|row| row.kind == BeliefStateKind::Intends)
                && edge(DECEPTION_EDGE).is_some()
                && added.contains(TAMSIN_DETAILS_CONSTRAINT)
                && added.contains(TAMSIN_DECEPTION_CONSTRAINT),
            &[TAMSIN_DETAILS_BELIEF.into(), TAMSIN_INTENT_BELIEF.into()],
        ),
        outcome(
            "court_believes_false_testimony",
            court.is_some_and(|row| {
                row.kind == BeliefStateKind::Believes
                    && row.truth_status == TemporalTruthStatus::Reported
            }) && edge(COURT_TRUST_EDGE).is_some()
                && added.contains(COURT_FALSE_BELIEF_CONSTRAINT),
            &[COURT_FALSE_BELIEF.into(), COURT_TRUST_EDGE.into()],
        ),
        outcome(
            "deception_is_revealed_later",
            reveal.is_some_and(|row| {
                row.kind == BeliefStateKind::Knows
                    && row.temporal.valid_from.is_some_and(|time| time > 900)
            }) && edge(REVEAL_EDGE).is_some()
                && added.contains(REVEAL_KNOWLEDGE_CONSTRAINT)
                && added.contains(REVEAL_CAUSAL_CONSTRAINT),
            &[COURT_REVEAL_BELIEF.into(), REVEAL_EDGE.into()],
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
#[path = "repair_shadow_deception_tests.rs"]
mod tests;
