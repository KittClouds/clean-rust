use std::collections::{BTreeSet, HashSet};

use phoenix_types::{
    ConstraintKind, DependencyClass, RevisionImpactGoldCorpus, StoryInterval, StoryTime,
};
use serde::Deserialize;

use super::*;

fn interval(start: i64) -> StoryInterval {
    StoryInterval {
        valid_from: StoryTime(start),
        valid_to_exclusive: Some(StoryTime(start + 1)),
    }
}

fn constraint(id: &str, source: &str, dependent: &str, kind: ConstraintKind) -> ConstraintSeed {
    ConstraintSeed {
        constraint_id: id.into(),
        source_id: source.into(),
        dependent_id: dependent.into(),
        kind,
        valid_interval: interval(50),
        evidence: vec![EvidenceRef::anchored(format!("evidence:{id}"))],
        confidence_millis: 900,
    }
}

fn node(id: &str, kind: &str) -> InferenceNodeSeed {
    InferenceNodeSeed {
        node_id: id.into(),
        node_type: kind.into(),
        embedding_text: id.into(),
    }
}

fn edge(id: &str, authority: InferenceAuthority) -> InferenceEdgeSeed {
    InferenceEdgeSeed {
        edge_id: id.into(),
        source_id: "node:a".into(),
        target_id: "node:b".into(),
        relation_type: "causes".into(),
        authority,
        evidence_ids: vec!["anchor:1".into()],
        confidence_millis: 800,
    }
}

#[test]
fn both_views_share_one_generation_and_compact_adjacency() {
    let views = RevisionAnalysisViews::project(
        GraphGeneration(17),
        vec![
            constraint(
                "constraint:soft",
                "fact:1",
                "scene:2",
                ConstraintKind::CausalSupport,
            ),
            constraint(
                "constraint:hard",
                "fact:1",
                "scene:1",
                ConstraintKind::RequiresKnowledge,
            ),
        ],
        InferenceProjectionInput {
            accepted_nodes: vec![node("node:b", "scene"), node("node:a", "fact")],
            relations: vec![edge("edge:accepted", InferenceAuthority::Accepted)],
            memberships: Vec::new(),
        },
    )
    .expect("dual projection");

    assert_eq!(views.generation(), GraphGeneration(17));
    assert_eq!(views.constraint_graph.generation(), GraphGeneration(17));
    assert_eq!(views.inference_graph.generation(), GraphGeneration(17));
    let fact = views.constraint_graph.node_index("fact:1").unwrap();
    let outgoing = views.constraint_graph.outgoing(fact);
    assert_eq!(outgoing.len(), 2);
    assert_eq!(outgoing[0].strength, DependencyClass::HardRequirement);
    assert_eq!(outgoing[1].strength, DependencyClass::DefeasibleSupport);
    assert_eq!(views.inference_graph.incoming_offsets().len(), 3);
    assert_eq!(views.inference_graph.source_ids().len(), 1);
    assert_eq!(views.inference_graph.relation_type_ids().len(), 1);
}

#[test]
fn candidates_and_rejections_never_reach_model_arrays() {
    let views = RevisionAnalysisViews::project(
        GraphGeneration(2),
        Vec::new(),
        InferenceProjectionInput {
            accepted_nodes: vec![node("node:a", "entity"), node("node:b", "event")],
            relations: vec![
                edge("edge:asserted", InferenceAuthority::Asserted),
                edge("edge:candidate", InferenceAuthority::Candidate),
                edge("edge:rejected", InferenceAuthority::Rejected),
            ],
            memberships: vec![InferenceEdgeSeed {
                edge_id: "membership:accepted".into(),
                relation_type: "contains".into(),
                authority: InferenceAuthority::Accepted,
                ..edge("unused", InferenceAuthority::Accepted)
            }],
        },
    )
    .expect("filtered inference graph");

    let graph = &views.inference_graph;
    assert_eq!(graph.edge_metadata().len(), 2);
    assert!(graph
        .edge_metadata()
        .iter()
        .all(|edge| !edge.edge_id.contains("candidate") && !edge.edge_id.contains("rejected")));
    assert_eq!(graph.receipt().excluded_candidate_edges, 1);
    assert_eq!(graph.receipt().excluded_rejected_edges, 1);
    assert_eq!(graph.receipt().admitted_relations, 1);
    assert_eq!(graph.receipt().admitted_memberships, 1);
}

#[test]
fn shuffled_inputs_project_identically() {
    let constraints = vec![
        constraint(
            "constraint:b",
            "fact:b",
            "scene:b",
            ConstraintKind::RequiresAlive,
        ),
        constraint(
            "constraint:a",
            "fact:a",
            "scene:a",
            ConstraintKind::RequiresState,
        ),
    ];
    let inference = InferenceProjectionInput {
        accepted_nodes: vec![node("node:b", "scene"), node("node:a", "fact")],
        relations: vec![edge("edge:b", InferenceAuthority::Accepted)],
        memberships: vec![InferenceEdgeSeed {
            edge_id: "edge:a".into(),
            relation_type: "contains".into(),
            ..edge("unused", InferenceAuthority::Asserted)
        }],
    };
    let mut reversed_constraints = constraints.clone();
    reversed_constraints.reverse();
    let mut reversed_inference = inference.clone();
    reversed_inference.accepted_nodes.reverse();
    reversed_inference.relations.reverse();
    reversed_inference.memberships.reverse();

    let first = RevisionAnalysisViews::project(GraphGeneration(9), constraints, inference).unwrap();
    let second = RevisionAnalysisViews::project(
        GraphGeneration(9),
        reversed_constraints,
        reversed_inference,
    )
    .unwrap();
    assert_eq!(first, second);
}

#[test]
fn constraints_fail_closed_without_evidence_or_temporal_bounds() {
    let mut missing_evidence = constraint(
        "constraint:no_evidence",
        "fact:1",
        "scene:1",
        ConstraintKind::RequiresAlive,
    );
    missing_evidence.evidence.clear();
    assert!(matches!(
        RevisionAnalysisViews::project(
            GraphGeneration(1),
            vec![missing_evidence],
            InferenceProjectionInput::default()
        ),
        Err(ProjectionError::MissingConstraintEvidence(_))
    ));

    let mut invalid_time = constraint(
        "constraint:bad_time",
        "fact:1",
        "scene:1",
        ConstraintKind::RequiresAlive,
    );
    invalid_time.valid_interval.valid_to_exclusive = Some(invalid_time.valid_interval.valid_from);
    assert!(matches!(
        RevisionAnalysisViews::project(
            GraphGeneration(1),
            vec![invalid_time],
            InferenceProjectionInput::default()
        ),
        Err(ProjectionError::InvalidStoryInterval(_))
    ));
}

#[test]
fn every_contract_constraint_kind_survives_typed_projection() {
    let kinds = [
        ConstraintKind::RequiresKnowledge,
        ConstraintKind::RequiresWitness,
        ConstraintKind::RequiresAlive,
        ConstraintKind::RequiresPossession,
        ConstraintKind::RequiresReachability,
        ConstraintKind::RequiresState,
        ConstraintKind::RequiresTemporalOrder,
        ConstraintKind::MutuallyExclusiveStates,
        ConstraintKind::CausalSupport,
        ConstraintKind::Motivation,
        ConstraintKind::Foreshadowing,
        ConstraintKind::Mention,
        ConstraintKind::ThematicEcho,
    ];
    let seeds = kinds
        .iter()
        .enumerate()
        .map(|(index, kind)| {
            constraint(
                &format!("constraint:kind:{index}"),
                "fact:all-kinds",
                &format!("scene:{index}"),
                *kind,
            )
        })
        .collect();
    let views = RevisionAnalysisViews::project(
        GraphGeneration(3),
        seeds,
        InferenceProjectionInput::default(),
    )
    .expect("all typed constraints");

    assert_eq!(views.constraint_graph.atoms().len(), kinds.len());
    for atom in views.constraint_graph.atoms() {
        assert_eq!(atom.strength, atom.kind.dependency_class());
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct GoldProjectionFixture {
    schema_version: String,
    cases: Vec<GoldProjectionCase>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct GoldProjectionCase {
    case_id: String,
    constraints: Vec<ConstraintSeed>,
}

#[test]
fn every_planted_gold_violation_projects_with_evidence_and_bounds() {
    let gold: RevisionImpactGoldCorpus = serde_json::from_str(include_str!(
        "../../../phoenix/crates/phoenix-types/fixtures/revision-impact-gold-v1.json"
    ))
    .expect("Phase 0 gold corpus");
    gold.validate().expect("valid Phase 0 gold corpus");
    let fixture: GoldProjectionFixture = serde_json::from_str(include_str!(
        "../fixtures/revision-analysis-gold-projection-v1.json"
    ))
    .expect("Phase 3 gold projection fixture");
    assert_eq!(
        fixture.schema_version,
        "phoenix-revision-analysis-gold-projection/v1"
    );
    assert_eq!(fixture.cases.len(), gold.cases.len());

    let fixture_case_ids = fixture
        .cases
        .iter()
        .map(|case| case.case_id.as_str())
        .collect::<BTreeSet<_>>();
    let gold_case_ids = gold
        .cases
        .iter()
        .map(|case| case.case_id.0.as_str())
        .collect::<BTreeSet<_>>();
    assert_eq!(fixture_case_ids, gold_case_ids);

    for gold_case in &gold.cases {
        let projection_case = fixture
            .cases
            .iter()
            .find(|case| case.case_id == gold_case.case_id.0)
            .expect("projection case");
        let views = RevisionAnalysisViews::project(
            GraphGeneration(42),
            projection_case.constraints.clone(),
            InferenceProjectionInput::default(),
        )
        .expect("typed constraint projection");
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
        assert!(views
            .constraint_graph
            .atoms()
            .iter()
            .all(|atom| { !atom.evidence.is_empty() && atom.valid_interval.is_well_formed() }));
    }
}
