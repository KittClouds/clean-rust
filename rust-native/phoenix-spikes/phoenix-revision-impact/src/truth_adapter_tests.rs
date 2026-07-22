use std::collections::BTreeMap;

#[cfg(test)]
use std::collections::HashSet;

use compact_str::{format_compact, CompactString};
use phoenix_semantic_v2::{
    BeliefSourceKind, BeliefStateAtom, CausalEdgeAddition, CausalEdgeId, CausalRelationKind,
    MemoryStateRecord, TemporalConstraintId, TemporalConstraintRecord,
};
use phoenix_types::{
    BiTemporalWindow, CausalKind, ConstraintKind, EntityId, EventId, GraphTruthDigest, Polarity,
    RevisionImpactGoldCase, RevisionImpactGoldCorpus, SemanticNodeRef, StoryMutation, StoryTime,
    TextRange,
};
use serde::Deserialize;

use super::*;
use crate::{
    CounterfactualGraphView, InferenceAuthority, InferenceEdgeSeed, InferenceNodeSeed,
    InferenceProjectionInput, NamedSidecarDigest, RevisionAnalysisViews, RevisionEdgeRecord,
    RevisionFactRecord, RevisionStateRecord,
};

#[cfg(not(test))]
use crate::{
    detect_revision_impacts, IdentityCoverage, InferenceGraph, RevisionDetectorInput,
    RevisionImpactReport, RippleConfig, SceneCoverageRequest,
};

const GENERATION: GraphGeneration = GraphGeneration(73);

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GoldProjectionFixture {
    pub schema_version: String,
    pub cases: Vec<GoldProjectionCase>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GoldProjectionCase {
    pub case_id: String,
    pub constraints: Vec<ConstraintSeed>,
}

pub struct CaseFixture {
    pub base: RevisionGraphSnapshot,
    pub requirements: RevisionRequirementSidecar,
    pub temporal: TemporalScopeSidecar,
    pub memory: MemoryScopeSidecar,
    pub causal: CausalScopeSidecar,
    pub inference: InferenceProjectionInput,
    pub mutation: StoryMutation,
}

#[cfg(not(test))]
pub struct GoldCaseAnalysis {
    pub report: RevisionImpactReport,
    pub inference_graph: InferenceGraph,
}

#[cfg(not(test))]
pub fn analyze_case(
    gold: &RevisionImpactGoldCase,
    projection: &GoldProjectionCase,
) -> GoldCaseAnalysis {
    let fixture = case_fixture(gold, projection);
    let bundle = project_authoritative_constraints(AuthoritativeRevisionSources {
        base: &fixture.base,
        requirements: &fixture.requirements,
        temporal: Some(&fixture.temporal),
        memory: Some(&fixture.memory),
        causal: Some(&fixture.causal),
    })
    .expect("authoritative gold projection");
    let views = RevisionAnalysisViews::project(
        fixture.base.generation(),
        bundle.constraints,
        fixture.inference,
    )
    .expect("gold analysis views");
    let overlay = CounterfactualGraphView::new(&fixture.base, vec![fixture.mutation])
        .expect("gold counterfactual overlay");
    let coverage_requests = gold
        .expected_unknowns
        .iter()
        .map(|unknown| SceneCoverageRequest {
            scene_id: unknown.scene_id.clone(),
            required_planes: unknown.missing_planes.clone(),
            unavailable_planes: unknown.missing_planes.clone(),
        })
        .collect::<Vec<_>>();
    let report = detect_revision_impacts(
        RevisionDetectorInput {
            overlay: &overlay,
            constraint_graph: &views.constraint_graph,
            requirements: &fixture.requirements,
            projection_receipt: &bundle.receipt,
            identity_coverage: IdentityCoverage::SameRevision,
            coverage_requests: &coverage_requests,
        },
        RippleConfig::default(),
    )
    .expect("gold revision detector");
    GoldCaseAnalysis {
        report,
        inference_graph: views.inference_graph,
    }
}

#[cfg(test)]
#[test]
fn seven_mutations_run_base_overlay_adapters_and_dual_projection_end_to_end() {
    let (gold, projection) = gold_fixtures();
    assert_eq!(
        projection.schema_version,
        "phoenix-revision-analysis-gold-projection/v1"
    );

    for gold_case in &gold.cases {
        let projection_case = projection
            .cases
            .iter()
            .find(|case| case.case_id == gold_case.case_id.0)
            .expect("projection case");
        let fixture = case_fixture(gold_case, projection_case);
        let bundle = project_authoritative_constraints(AuthoritativeRevisionSources {
            base: &fixture.base,
            requirements: &fixture.requirements,
            temporal: Some(&fixture.temporal),
            memory: Some(&fixture.memory),
            causal: Some(&fixture.causal),
        })
        .expect("authoritative sidecar projection");
        assert_eq!(bundle.receipt.generation, GENERATION);
        assert_eq!(
            bundle.receipt.projected_constraints,
            projection_case.constraints.len()
        );
        assert!(bundle
            .receipt
            .planes
            .iter()
            .filter(|plane| plane.plane != AdapterTruthPlane::Capability)
            .all(|plane| plane.status == AdapterCoverageStatus::Covered));
        assert_eq!(
            bundle
                .receipt
                .planes
                .iter()
                .find(|plane| plane.plane == AdapterTruthPlane::Capability)
                .unwrap()
                .status,
            AdapterCoverageStatus::Unavailable
        );

        let views =
            RevisionAnalysisViews::project(GENERATION, bundle.constraints, fixture.inference)
                .expect("dual views");
        assert_eq!(views.generation(), GENERATION);
        assert!(!views.inference_graph.edge_metadata().is_empty());
        assert_expected_pairs(&views, gold_case);

        let overlay = CounterfactualGraphView::new(&fixture.base, vec![fixture.mutation])
            .expect("counterfactual overlay");
        for requirement in &fixture.requirements.requirements {
            assert!(
                overlay.edge_is_invalidated(&requirement.constraint_id),
                "{} must be invalidated for {}",
                requirement.constraint_id,
                gold_case.case_id.0
            );
            assert_eq!(
                evaluate_requirement(&overlay, requirement),
                RequirementEvaluation::Violated,
                "{} must fail after {}",
                requirement.constraint_id,
                gold_case.case_id.0
            );
        }
    }
}

#[cfg(test)]
#[test]
fn generation_skew_fails_before_projection() {
    let (gold, projection) = gold_fixtures();
    let mut fixture = case_fixture(&gold.cases[0], &projection.cases[0]);
    fixture.temporal.generation += 1;
    let error = project_authoritative_constraints(AuthoritativeRevisionSources {
        base: &fixture.base,
        requirements: &fixture.requirements,
        temporal: Some(&fixture.temporal),
        memory: Some(&fixture.memory),
        causal: Some(&fixture.causal),
    })
    .unwrap_err();
    assert!(matches!(
        error,
        TruthAdapterError::GenerationMismatch {
            plane_source: "temporal",
            ..
        }
    ));
}

#[cfg(test)]
#[test]
fn candidate_truth_records_fail_closed_in_every_authoritative_lane() {
    let (gold, projection) = gold_fixtures();

    let mut belief = case_fixture(&gold.cases[0], &projection.cases[0]);
    belief.temporal.belief_atoms[0].truth_status = TemporalTruthStatus::Hypothetical;
    assert_non_authoritative(&belief);

    let mut memory = case_fixture(&gold.cases[1], &projection.cases[1]);
    memory.memory.states[0].status = MemoryClaimStatus::Candidate;
    assert_non_authoritative(&memory);

    let mut causal = case_fixture(&gold.cases[0], &projection.cases[0]);
    causal.causal.edge_records[0].status = CausalClaimStatus::Candidate;
    assert_non_authoritative(&causal);
}

#[cfg(test)]
#[test]
fn inference_csr_constructs_both_real_model_graphs_without_encoders() {
    let (gold, projection) = gold_fixtures();
    let fixture = case_fixture(&gold.cases[0], &projection.cases[0]);
    let bundle = project_authoritative_constraints(AuthoritativeRevisionSources {
        base: &fixture.base,
        requirements: &fixture.requirements,
        temporal: Some(&fixture.temporal),
        memory: Some(&fixture.memory),
        causal: Some(&fixture.causal),
    })
    .unwrap();
    let views = RevisionAnalysisViews::project(GENERATION, bundle.constraints, fixture.inference)
        .expect("dual views");
    let graph = &views.inference_graph;

    let mut edges_8m = Vec::new();
    let mut edges_34m = Vec::new();
    for target in 0..graph.nodes().len() {
        let start = graph.incoming_offsets()[target] as usize;
        let end = graph.incoming_offsets()[target + 1] as usize;
        for edge in start..end {
            edges_8m.push(gfm_rag_8m_parity::graph::Edge {
                src: graph.source_ids()[edge],
                relation: graph.relation_type_ids()[edge],
                dst: target as u32,
            });
            edges_34m.push(g_reasoner_34m_parity::graph::Edge {
                src: graph.source_ids()[edge],
                relation: graph.relation_type_ids()[edge],
                dst: target as u32,
            });
        }
    }
    let graph_8m = gfm_rag_8m_parity::graph::IncomingCsr::from_edges(
        graph.nodes().len(),
        graph.relation_types().len(),
        edges_8m,
    )
    .expect("GFM-RAG-8M graph");
    let graph_34m = g_reasoner_34m_parity::graph::IncomingCsr::from_edges(
        graph.nodes().len(),
        graph.relation_types().len(),
        edges_34m,
    )
    .expect("G-reasoner-34M graph");
    let expected_offsets = graph
        .incoming_offsets()
        .iter()
        .map(|offset| u64::from(*offset))
        .collect::<Vec<_>>();

    assert_eq!(graph_8m.dst_offsets(), expected_offsets);
    assert_eq!(graph_34m.dst_offsets(), expected_offsets);
    assert_eq!(graph_8m.src_nodes(), graph.source_ids());
    assert_eq!(graph_34m.src_nodes(), graph.source_ids());
    assert_eq!(graph_8m.relation_ids(), graph.relation_type_ids());
    assert_eq!(graph_34m.relation_ids(), graph.relation_type_ids());
}

#[cfg(test)]
fn assert_non_authoritative(fixture: &CaseFixture) {
    let error = project_authoritative_constraints(AuthoritativeRevisionSources {
        base: &fixture.base,
        requirements: &fixture.requirements,
        temporal: Some(&fixture.temporal),
        memory: Some(&fixture.memory),
        causal: Some(&fixture.causal),
    })
    .unwrap_err();
    assert!(matches!(error, TruthAdapterError::NonAuthoritativeTruth(_)));
}

#[cfg(test)]
fn assert_expected_pairs(views: &RevisionAnalysisViews, gold_case: &RevisionImpactGoldCase) {
    let projected = views
        .constraint_graph
        .atoms()
        .iter()
        .map(|atom| {
            (
                views.constraint_graph.nodes()[atom.dependent as usize]
                    .id
                    .as_str(),
                atom.kind,
            )
        })
        .collect::<HashSet<_>>();
    let expected = gold_case
        .expected_impacts
        .iter()
        .flat_map(|impact| {
            impact
                .constraint_kinds
                .iter()
                .map(|kind| (impact.scene_id.0.as_str(), *kind))
        })
        .collect::<HashSet<_>>();
    assert_eq!(projected, expected, "case {}", gold_case.case_id.0);
}

pub fn gold_fixtures() -> (RevisionImpactGoldCorpus, GoldProjectionFixture) {
    let gold: RevisionImpactGoldCorpus = serde_json::from_str(include_str!(
        "../../../phoenix/crates/phoenix-types/fixtures/revision-impact-gold-v1.json"
    ))
    .expect("Phase 0 corpus");
    gold.validate().expect("valid Phase 0 corpus");
    let projection = serde_json::from_str(include_str!(
        "../fixtures/revision-analysis-gold-projection-v1.json"
    ))
    .expect("Phase 3 projection fixture");
    (gold, projection)
}

pub fn case_fixture(gold: &RevisionImpactGoldCase, projection: &GoldProjectionCase) -> CaseFixture {
    let (dependency, expected_value, facts, states) = baseline_dependency(&gold.mutation);
    let mut temporal = TemporalScopeSidecar {
        generation: GENERATION.0,
        ..TemporalScopeSidecar::default()
    };
    let mut memory = MemoryScopeSidecar {
        generation: GENERATION.0,
        ..MemoryScopeSidecar::default()
    };
    let mut causal = CausalScopeSidecar {
        generation: GENERATION.0,
        ..CausalScopeSidecar::default()
    };
    let mut requirements = Vec::with_capacity(projection.constraints.len());
    let mut edges = Vec::with_capacity(projection.constraints.len());

    for seed in &projection.constraints {
        let truth_ref = add_truth_record(
            seed,
            &dependency,
            &expected_value,
            &mut temporal,
            &mut memory,
            &mut causal,
        );
        requirements.push(RevisionRequirementRecord {
            constraint_id: seed.constraint_id.clone(),
            dependency: dependency.clone(),
            expected_value: expected_value.clone(),
            dependent_scene_id: seed.dependent_id.as_str().into(),
            kind: seed.kind,
            valid_interval: seed.valid_interval,
            truth_ref,
            evidence: seed.evidence.clone(),
            confidence_millis: seed.confidence_millis,
        });
        let (dependency_fact_ids, dependency_state_refs) = match &dependency {
            RequirementDependency::Fact { fact_id } => (vec![fact_id.clone()], Vec::new()),
            RequirementDependency::State { state_ref } => (Vec::new(), vec![state_ref.clone()]),
        };
        edges.push(RevisionEdgeRecord {
            edge_id: seed.constraint_id.clone(),
            dependency_fact_ids,
            dependency_state_refs,
        });
    }
    let base = RevisionGraphSnapshot::new(
        GENERATION,
        facts,
        states,
        edges,
        vec![NamedSidecarDigest {
            sidecar_id: "revision-e2e".into(),
            digest: GraphTruthDigest([7; 32]),
        }],
    )
    .expect("base revision graph");
    let requirement_sidecar = RevisionRequirementSidecar {
        schema_version: REVISION_REQUIREMENT_SIDECAR_SCHEMA.into(),
        generation: GENERATION,
        requirements,
    };
    let inference = inference_fixture(&requirement_sidecar.requirements);
    CaseFixture {
        base,
        requirements: requirement_sidecar,
        temporal,
        memory,
        causal,
        inference,
        mutation: gold.mutation.clone(),
    }
}

fn baseline_dependency(
    mutation: &StoryMutation,
) -> (
    RequirementDependency,
    FactValue,
    Vec<RevisionFactRecord>,
    Vec<RevisionStateRecord>,
) {
    let interval = StoryInterval {
        valid_from: StoryTime(0),
        valid_to_exclusive: None,
    };
    match mutation {
        StoryMutation::ShiftValidity { fact_id, .. } => {
            let value = FactValue::Boolean(true);
            (
                RequirementDependency::Fact {
                    fact_id: fact_id.clone(),
                },
                value.clone(),
                vec![RevisionFactRecord {
                    fact_id: fact_id.clone(),
                    value,
                    interval,
                }],
                Vec::new(),
            )
        }
        StoryMutation::SupersedeFact { fact_id, .. } => {
            let value = match fact_id.0.as_str() {
                "fact:tamsin_witnessed_bridge_collapse" => {
                    FactValue::Entity(EntityId("entity:tamsin".to_owned()))
                }
                "fact:kai_temporal_step_limit" => FactValue::Integer(3),
                "fact:veyra_to_northern_fort_travel_minutes" => FactValue::DurationMinutes(120),
                other => panic!("unknown gold fact {other}"),
            };
            (
                RequirementDependency::Fact {
                    fact_id: fact_id.clone(),
                },
                value.clone(),
                vec![RevisionFactRecord {
                    fact_id: fact_id.clone(),
                    value,
                    interval,
                }],
                Vec::new(),
            )
        }
        StoryMutation::ChangeState {
            subject_id,
            state_kind,
            ..
        } => {
            let value = match state_kind.0.as_str() {
                "alive" => FactValue::Boolean(true),
                "relationship:silas" => FactValue::Text("confidant".into()),
                "possession:chronal_key" => FactValue::Entity(EntityId("entity:kai".to_owned())),
                other => panic!("unknown gold state {other}"),
            };
            let state_ref = StateRef {
                subject_id: subject_id.clone(),
                state_kind: state_kind.clone(),
            };
            (
                RequirementDependency::State {
                    state_ref: state_ref.clone(),
                },
                value.clone(),
                Vec::new(),
                vec![RevisionStateRecord {
                    state_ref,
                    value,
                    interval,
                }],
            )
        }
        StoryMutation::RetractFact { .. } => panic!("gold corpus has no bare retraction"),
    }
}

fn add_truth_record(
    seed: &ConstraintSeed,
    dependency: &RequirementDependency,
    expected: &FactValue,
    temporal: &mut TemporalScopeSidecar,
    memory: &mut MemoryScopeSidecar,
    causal: &mut CausalScopeSidecar,
) -> RequirementTruthRef {
    let record_id = format_compact!("truth:{}", seed.constraint_id);
    let evidence = vec![format!("source:{}", seed.constraint_id)];
    match seed.kind {
        ConstraintKind::RequiresKnowledge | ConstraintKind::RequiresWitness => {
            temporal.belief_atoms.push(BeliefStateAtom {
                belief_id: record_id.to_string(),
                document_id: "note:gold".to_owned(),
                kind: if seed.kind == ConstraintKind::RequiresWitness {
                    BeliefStateKind::Observed
                } else {
                    BeliefStateKind::Knows
                },
                truth_status: if seed.kind == ConstraintKind::RequiresWitness {
                    TemporalTruthStatus::Observed
                } else {
                    TemporalTruthStatus::Asserted
                },
                source_kind: BeliefSourceKind::DirectObservation,
                confidence_millis: 1000,
                temporal: wide_window(),
                range: Some(TextRange { start: 10, end: 20 }),
                evidence_refs: evidence,
                ..BeliefStateAtom::default()
            });
            RequirementTruthRef::Belief {
                belief_id: record_id,
            }
        }
        ConstraintKind::RequiresTemporalOrder => {
            temporal.constraints.push(TemporalConstraintRecord {
                constraint_id: TemporalConstraintId(record_id.to_string()),
                document_id: "note:gold".to_owned(),
                hard: true,
                temporal: wide_window(),
                confidence_millis: 1000,
                evidence_refs: evidence,
                ..TemporalConstraintRecord::default()
            });
            RequirementTruthRef::TemporalConstraint {
                constraint_id: record_id,
            }
        }
        ConstraintKind::RequiresAlive
        | ConstraintKind::RequiresPossession
        | ConstraintKind::RequiresReachability
        | ConstraintKind::RequiresState => {
            let (entity_id, slot_key) = match dependency {
                RequirementDependency::State { state_ref } => (
                    state_ref.subject_id.clone(),
                    state_ref.state_kind.0.to_string(),
                ),
                RequirementDependency::Fact { fact_id } => (
                    EntityId(format!("source:{}", fact_id.0)),
                    fact_id.0.to_string(),
                ),
            };
            let (value, value_entity_id) = memory_value(expected);
            memory.states.push(MemoryStateRecord {
                state_id: record_id.to_string(),
                entity_id,
                slot_key,
                value,
                value_entity_id,
                status: MemoryClaimStatus::Active,
                source_class: "gold-e2e".to_owned(),
                confidence_millis: 1000,
                temporal: wide_window(),
                claim_ids: evidence,
            });
            RequirementTruthRef::MemoryState {
                state_id: record_id,
            }
        }
        ConstraintKind::CausalSupport
        | ConstraintKind::Motivation
        | ConstraintKind::Foreshadowing => {
            causal.edge_records.push(CausalEdgeAddition {
                edge_id: CausalEdgeId(record_id.to_string()),
                case_id: seed.constraint_id.to_string(),
                document_id: "note:gold".to_owned(),
                source: SemanticNodeRef::Event(EventId("event:source".to_owned())),
                canonical_cause_event_id: None,
                target: SemanticNodeRef::Event(EventId(seed.dependent_id.to_string())),
                canonical_effect_event_id: None,
                kind: if seed.kind == ConstraintKind::Motivation {
                    CausalKind::Motivates
                } else {
                    CausalKind::Enables
                },
                relation_kind: CausalRelationKind::EnablingCondition,
                status: CausalClaimStatus::Active,
                first_seen_revision: GENERATION.0,
                latest_decision_id: None,
                confidence_millis: 1000,
                cue: Some("gold-e2e".to_owned()),
                attributed_to: None,
                polarity: Polarity::Positive,
                claim_atom_ids: Vec::new(),
                evidence_refs: evidence,
                effective_interval: wide_window(),
                observation_interval: wide_window(),
                temporal_certainty_millis: 1000,
                created_at: 1,
            });
            RequirementTruthRef::CausalEdge { edge_id: record_id }
        }
        ConstraintKind::MutuallyExclusiveStates
        | ConstraintKind::Mention
        | ConstraintKind::ThematicEcho => panic!("not used by planted gold constraints"),
    }
}

fn inference_fixture(requirements: &[RevisionRequirementRecord]) -> InferenceProjectionInput {
    let mut nodes = BTreeMap::<CompactString, CompactString>::new();
    let mut relations = Vec::with_capacity(requirements.len());
    for requirement in requirements {
        let source_id = requirement.dependency.graph_id();
        let target_id = requirement.dependent_scene_id.0.clone();
        nodes.insert(source_id.clone(), "fact".into());
        nodes.insert(target_id.clone(), "scene".into());
        relations.push(InferenceEdgeSeed {
            edge_id: format_compact!("inference:{}", requirement.constraint_id),
            source_id,
            target_id,
            relation_type: format_compact!("constraint:{:?}", requirement.kind),
            authority: InferenceAuthority::Asserted,
            evidence_ids: requirement
                .evidence
                .iter()
                .map(|evidence| evidence.evidence_id.clone())
                .collect(),
            confidence_millis: requirement.confidence_millis,
        });
    }
    InferenceProjectionInput {
        accepted_nodes: nodes
            .into_iter()
            .map(|(node_id, node_type)| InferenceNodeSeed {
                embedding_text: node_id.clone(),
                node_id,
                node_type,
            })
            .collect(),
        relations,
        memberships: Vec::new(),
    }
}

fn memory_value(value: &FactValue) -> (String, Option<EntityId>) {
    match value {
        FactValue::Boolean(value) => (value.to_string(), None),
        FactValue::Integer(value) | FactValue::DurationMinutes(value) => (value.to_string(), None),
        FactValue::Text(value) => (value.to_string(), None),
        FactValue::Entity(value) => (value.0.clone(), Some(value.clone())),
    }
}

fn wide_window() -> BiTemporalWindow {
    BiTemporalWindow {
        valid_from: Some(0),
        valid_to: None,
        recorded_from: Some(0),
        recorded_to: None,
    }
}
