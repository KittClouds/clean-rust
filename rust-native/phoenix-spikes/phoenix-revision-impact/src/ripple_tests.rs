use std::collections::BTreeSet;

use phoenix_types::{
    ConstraintKind, FactId, FactValue, GraphTruthDigest, StoryInterval, StoryMutation, StoryTime,
};

use super::*;
use crate::truth_adapter::tests::{case_fixture, gold_fixtures};
use crate::{
    project_authoritative_constraints, AuthoritativeRevisionSources, ConstraintSeed,
    CounterfactualGraphView, EvidenceRef, InferenceProjectionInput, NamedSidecarDigest,
    RequirementDependency, RequirementTruthRef, RevisionAnalysisViews, RevisionEdgeRecord,
    RevisionFactRecord, RevisionGraphSnapshot, RevisionRequirementRecord,
    RevisionRequirementSidecar, REVISION_REQUIREMENT_SIDECAR_SCHEMA,
};

#[test]
fn all_planted_hard_violations_are_found_and_soft_results_stay_suspicious() {
    let (gold, projection) = gold_fixtures();
    for gold_case in &gold.cases {
        let projection_case = projection
            .cases
            .iter()
            .find(|case| case.case_id == gold_case.case_id.0)
            .unwrap();
        let fixture = case_fixture(gold_case, projection_case);
        let bundle = project_authoritative_constraints(AuthoritativeRevisionSources {
            base: &fixture.base,
            requirements: &fixture.requirements,
            temporal: Some(&fixture.temporal),
            memory: Some(&fixture.memory),
            causal: Some(&fixture.causal),
        })
        .unwrap();
        let views = RevisionAnalysisViews::project(
            fixture.base.generation(),
            bundle.constraints,
            fixture.inference,
        )
        .unwrap();
        let overlay =
            CounterfactualGraphView::new(&fixture.base, vec![fixture.mutation.clone()]).unwrap();
        let result = causal_ripple_search(
            &overlay,
            &views.constraint_graph,
            &fixture.requirements,
            RippleConfig::default(),
        )
        .unwrap();

        let expected_broken = gold_case
            .expected_impacts
            .iter()
            .filter(|impact| impact.classification == ImpactClassification::Broken)
            .map(|impact| impact.scene_id.0.as_str())
            .collect::<BTreeSet<_>>();
        let actual_broken = result
            .impacts
            .iter()
            .filter(|impact| impact.classification == ImpactClassification::Broken)
            .map(|impact| impact.dependent_id.as_str())
            .collect::<BTreeSet<_>>();
        assert_eq!(actual_broken, expected_broken, "{}", gold_case.case_id.0);

        for expected in &gold_case.expected_impacts {
            let impact = result
                .impacts
                .iter()
                .find(|impact| impact.dependent_id == expected.scene_id.0)
                .expect("expected ripple impact");
            assert_eq!(
                impact.classification, expected.classification,
                "{} in {}",
                expected.scene_id.0, gold_case.case_id.0
            );
            if expected.classification == ImpactClassification::Broken {
                assert_eq!(impact.score_millis, 1000);
                assert!(!impact.violated_constraints.is_empty());
            } else {
                assert!(impact.violated_constraints.is_empty());
                assert!(!impact.support_loss_constraints.is_empty());
            }
        }
        assert!(!result.receipt.truncation.truncated());
        assert!(result.receipt.unmatched_seed_ids.is_empty());
    }
}

#[test]
fn soft_cycles_are_condensed_and_never_escalate_to_broken() {
    let fixture = soft_fixture(vec![
        soft("soft:seed_a", "fact:seed", "node:a", "evidence:seed"),
        soft("soft:a_b", "node:a", "node:b", "evidence:a_b"),
        soft("soft:b_a", "node:b", "node:a", "evidence:b_a"),
        soft(
            "soft:b_scene",
            "node:b",
            "scene:cycle_result",
            "evidence:b_scene",
        ),
    ]);
    let overlay = CounterfactualGraphView::new(
        &fixture.base,
        vec![StoryMutation::RetractFact {
            fact_id: FactId::from("fact:seed"),
        }],
    )
    .unwrap();
    let first = causal_ripple_search(
        &overlay,
        &fixture.views.constraint_graph,
        &fixture.requirements,
        RippleConfig::default(),
    )
    .unwrap();
    let second = causal_ripple_search(
        &overlay,
        &fixture.views.constraint_graph,
        &fixture.requirements,
        RippleConfig::default(),
    )
    .unwrap();

    assert_eq!(first, second);
    assert_eq!(first.receipt.strongly_connected_components, 3);
    assert_eq!(first.receipt.condensed_edges, 2);
    assert!(first
        .impacts
        .iter()
        .all(|impact| impact.classification == ImpactClassification::Suspicious));
    assert!(first
        .impacts
        .iter()
        .any(|impact| impact.dependent_id == "scene:cycle_result"));
    assert!(!first.receipt.truncation.truncated());
}

#[test]
fn shared_evidence_is_deduplicated_and_independent_paths_combine() {
    let fixture = soft_fixture(vec![
        soft(
            "soft:shared_1",
            "fact:seed",
            "scene:impact",
            "evidence:shared",
        ),
        soft(
            "soft:shared_2",
            "fact:seed",
            "scene:impact",
            "evidence:shared",
        ),
        soft(
            "soft:independent",
            "fact:seed",
            "scene:impact",
            "evidence:independent",
        ),
    ]);
    let overlay = CounterfactualGraphView::new(
        &fixture.base,
        vec![StoryMutation::RetractFact {
            fact_id: FactId::from("fact:seed"),
        }],
    )
    .unwrap();
    let result = causal_ripple_search(
        &overlay,
        &fixture.views.constraint_graph,
        &fixture.requirements,
        RippleConfig::default(),
    )
    .unwrap();
    let impact = result
        .impacts
        .iter()
        .find(|impact| impact.dependent_id == "scene:impact")
        .unwrap();

    assert_eq!(impact.classification, ImpactClassification::Suspicious);
    assert_eq!(impact.causal_paths.len(), 2);
    assert_eq!(impact.score_millis, 998);
}

#[test]
fn traversal_and_path_limits_are_reported() {
    let fixture = soft_fixture(vec![
        soft("soft:1", "fact:seed", "node:1", "evidence:1"),
        soft("soft:2", "node:1", "node:2", "evidence:2"),
        soft("soft:3", "node:2", "scene:end", "evidence:3"),
    ]);
    let overlay = CounterfactualGraphView::new(
        &fixture.base,
        vec![StoryMutation::RetractFact {
            fact_id: FactId::from("fact:seed"),
        }],
    )
    .unwrap();
    let result = causal_ripple_search(
        &overlay,
        &fixture.views.constraint_graph,
        &fixture.requirements,
        RippleConfig {
            max_traversed_edges: 1,
            ..RippleConfig::default()
        },
    )
    .unwrap();

    assert!(result.receipt.truncation.traversed_edge_limit_hit);
    assert!(result.receipt.truncation.truncated());
    assert_eq!(result.receipt.traversed_edges, 1);
}

#[test]
fn long_hard_chain_remains_broken_at_full_severity() {
    let fact_id = FactId::from("fact:hard-seed");
    let generation = GraphGeneration(12);
    let interval = StoryInterval {
        valid_from: StoryTime(10),
        valid_to_exclusive: Some(StoryTime(11)),
    };
    let mut constraints = Vec::new();
    let mut requirements = Vec::new();
    let mut edges = Vec::new();
    for index in 0..12 {
        let constraint_id = format_compact!("hard:{index:02}");
        constraints.push(ConstraintSeed {
            constraint_id: constraint_id.clone(),
            source_id: if index == 0 {
                fact_id.0.clone()
            } else {
                format_compact!("node:{:02}", index - 1)
            },
            dependent_id: format_compact!("node:{index:02}"),
            kind: ConstraintKind::RequiresState,
            valid_interval: interval,
            evidence: vec![EvidenceRef::anchored(format_compact!(
                "evidence:hard:{index:02}"
            ))],
            confidence_millis: 1000,
        });
        requirements.push(RevisionRequirementRecord {
            constraint_id: constraint_id.clone(),
            dependency: RequirementDependency::Fact {
                fact_id: fact_id.clone(),
            },
            expected_value: FactValue::Boolean(true),
            dependent_scene_id: format!("node:{index:02}").into(),
            kind: ConstraintKind::RequiresState,
            valid_interval: interval,
            truth_ref: RequirementTruthRef::MemoryState {
                state_id: format_compact!("unused:{index:02}"),
            },
            evidence: vec![EvidenceRef::anchored(format_compact!(
                "evidence:hard:{index:02}"
            ))],
            confidence_millis: 1000,
        });
        edges.push(RevisionEdgeRecord {
            edge_id: constraint_id,
            dependency_fact_ids: vec![fact_id.clone()],
            dependency_state_refs: Vec::new(),
        });
    }
    let base = RevisionGraphSnapshot::new(
        generation,
        vec![RevisionFactRecord {
            fact_id: fact_id.clone(),
            value: FactValue::Boolean(true),
            interval: StoryInterval {
                valid_from: StoryTime(0),
                valid_to_exclusive: None,
            },
        }],
        Vec::new(),
        edges,
        vec![NamedSidecarDigest {
            sidecar_id: "hard-chain".into(),
            digest: GraphTruthDigest([12; 32]),
        }],
    )
    .unwrap();
    let views = RevisionAnalysisViews::project(
        generation,
        constraints,
        InferenceProjectionInput::default(),
    )
    .unwrap();
    let requirement_sidecar = RevisionRequirementSidecar {
        schema_version: REVISION_REQUIREMENT_SIDECAR_SCHEMA.into(),
        generation,
        requirements,
    };
    let overlay =
        CounterfactualGraphView::new(&base, vec![StoryMutation::RetractFact { fact_id }]).unwrap();
    let result = causal_ripple_search(
        &overlay,
        &views.constraint_graph,
        &requirement_sidecar,
        RippleConfig::default(),
    )
    .unwrap();
    let final_impact = result
        .impacts
        .iter()
        .find(|impact| impact.dependent_id == "node:11")
        .unwrap();

    assert_eq!(final_impact.classification, ImpactClassification::Broken);
    assert_eq!(final_impact.score_millis, 1000);
    assert_eq!(final_impact.causal_paths[0].constraint_ids.len(), 12);
}

struct SoftFixture {
    base: RevisionGraphSnapshot,
    views: RevisionAnalysisViews,
    requirements: RevisionRequirementSidecar,
}

fn soft(id: &str, source: &str, dependent: &str, evidence: &str) -> ConstraintSeed {
    ConstraintSeed {
        constraint_id: id.into(),
        source_id: source.into(),
        dependent_id: dependent.into(),
        kind: ConstraintKind::CausalSupport,
        valid_interval: StoryInterval {
            valid_from: StoryTime(10),
            valid_to_exclusive: Some(StoryTime(11)),
        },
        evidence: vec![EvidenceRef::anchored(evidence)],
        confidence_millis: 900,
    }
}

fn soft_fixture(constraints: Vec<ConstraintSeed>) -> SoftFixture {
    let fact_id = FactId::from("fact:seed");
    let generation = GraphGeneration(9);
    let base = RevisionGraphSnapshot::new(
        generation,
        vec![RevisionFactRecord {
            fact_id: fact_id.clone(),
            value: FactValue::Boolean(true),
            interval: StoryInterval {
                valid_from: StoryTime(0),
                valid_to_exclusive: None,
            },
        }],
        Vec::new(),
        constraints
            .iter()
            .map(|constraint| RevisionEdgeRecord {
                edge_id: constraint.constraint_id.clone(),
                dependency_fact_ids: vec![fact_id.clone()],
                dependency_state_refs: Vec::new(),
            })
            .collect(),
        vec![NamedSidecarDigest {
            sidecar_id: "soft-ripple".into(),
            digest: GraphTruthDigest([9; 32]),
        }],
    )
    .unwrap();
    let views = RevisionAnalysisViews::project(
        generation,
        constraints,
        InferenceProjectionInput::default(),
    )
    .unwrap();
    SoftFixture {
        base,
        views,
        requirements: RevisionRequirementSidecar {
            schema_version: REVISION_REQUIREMENT_SIDECAR_SCHEMA.into(),
            generation,
            requirements: Vec::new(),
        },
    }
}
