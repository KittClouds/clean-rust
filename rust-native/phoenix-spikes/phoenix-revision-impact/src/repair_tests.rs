use std::collections::BTreeSet;

use compact_str::CompactString;
use phoenix_types::{RepairTemplateKind, RevisionImpactGoldCase};

use super::*;
use crate::truth_adapter::tests::{case_fixture, gold_fixtures, GoldProjectionCase};
use crate::{
    detect_revision_impacts, generate_deterministic_repairs, project_authoritative_constraints,
    AuthoritativeRevisionSources, CounterfactualGraphView, IdentityCoverage,
    InferenceProjectionInput, RepairGenerationInput, RevisionAnalysisViews, RevisionDetectorInput,
    RippleConfig, SceneCoverageRequest,
};

#[test]
fn seven_gold_mutations_have_simulated_mutation_preserving_fixes() {
    let (gold, projections) = gold_fixtures();
    let locks = BTreeSet::new();

    for gold_case in &gold.cases {
        let projection = projection_case(&projections.cases, gold_case);
        let fixture = case_fixture(gold_case, projection);
        let report = report_for(gold_case, projection);
        let base_digest = fixture.base.digest();
        let mutations = vec![fixture.mutation.clone()];
        let first = generate_deterministic_repairs(RepairGenerationInput {
            base: &fixture.base,
            mutations: &mutations,
            requirements: &fixture.requirements,
            report: &report,
            author_locked_ids: &locks,
        });
        let second = generate_deterministic_repairs(RepairGenerationInput {
            base: &fixture.base,
            mutations: &mutations,
            requirements: &fixture.requirements,
            report: &report,
            author_locked_ids: &locks,
        });
        assert_eq!(first, second, "generation: {}", gold_case.case_id.0);
        assert_eq!(first.receipt.emitted_candidates, first.candidates.len());
        assert!(first.receipt.deterministic);
        assert!(first
            .candidates
            .iter()
            .any(|edit| edit.template == RepairTemplateKind::ReviseRequirementBearingStatement));

        let mut preserving_proven = 0;
        for edit in &first.candidates {
            let candidate = simulate(&fixture, &mutations, &report, &locks, edit);
            let repeated = simulate(&fixture, &mutations, &report, &locks, edit);
            assert_eq!(candidate, repeated, "candidate: {}", edit.edit_id.0);
            assert_eq!(
                candidate.fixed_constraints,
                candidate.validation_receipt.fixed_constraints
            );
            assert_eq!(
                candidate.remaining_violations,
                candidate.validation_receipt.remaining_violations
            );
            assert_eq!(
                candidate.introduced_violations,
                candidate.validation_receipt.introduced_violations
            );
            assert!(candidate.validation_receipt.full_revalidation_completed);
            assert!(candidate.validation_receipt.base_graph_unchanged);
            assert!(candidate.validation_receipt.no_truth_writes);
            assert_eq!(fixture.base.digest(), base_digest);

            if candidate.disposition == RepairDisposition::ProvenFix {
                assert!(!candidate.fixed_constraints.is_empty());
                assert!(candidate
                    .validation_receipt
                    .introduced_hard_violations
                    .is_empty());
                assert!(candidate.introduced_violations.is_empty());
                assert!(
                    candidate
                        .validation_receipt
                        .coverage
                        .complete_for_claimed_constraints
                );
                if candidate.edit.preserves_mutation {
                    preserving_proven += 1;
                }
            }
        }
        assert!(
            preserving_proven > 0,
            "{} needs a mutation-preserving proven fix",
            gold_case.case_id.0
        );
    }
}

#[test]
fn rollback_is_explicitly_separate_from_mutation_preserving_repairs() {
    let (gold, projections) = gold_fixtures();
    let locks = BTreeSet::new();

    for gold_case in &gold.cases {
        let projection = projection_case(&projections.cases, gold_case);
        let fixture = case_fixture(gold_case, projection);
        let report = report_for(gold_case, projection);
        let mutations = vec![fixture.mutation.clone()];
        let generated = generate_deterministic_repairs(RepairGenerationInput {
            base: &fixture.base,
            mutations: &mutations,
            requirements: &fixture.requirements,
            report: &report,
            author_locked_ids: &locks,
        });
        for edit in generated
            .candidates
            .iter()
            .filter(|edit| edit.template == RepairTemplateKind::RestoreOriginalFact)
        {
            assert!(!edit.preserves_mutation);
            let candidate = simulate(&fixture, &mutations, &report, &locks, edit);
            assert_eq!(candidate.disposition, RepairDisposition::ProvenFix);
        }
    }
}

#[test]
fn author_locks_and_bad_preconditions_fail_closed() {
    let (gold, projections) = gold_fixtures();
    let gold_case = &gold.cases[0];
    let projection = projection_case(&projections.cases, gold_case);
    let fixture = case_fixture(gold_case, projection);
    let report = report_for(gold_case, projection);
    let mutations = vec![fixture.mutation.clone()];
    let scene_id = report
        .authoritative_impacts
        .iter()
        .find(|impact| !impact.violated_constraints.is_empty())
        .expect("broken impact")
        .scene_id
        .0
        .clone();
    let locks = BTreeSet::from([scene_id]);
    let generated = generate_deterministic_repairs(RepairGenerationInput {
        base: &fixture.base,
        mutations: &mutations,
        requirements: &fixture.requirements,
        report: &report,
        author_locked_ids: &locks,
    });
    assert!(generated
        .receipt
        .skipped_templates
        .iter()
        .any(|skip| skip.reason == "target is author-locked"));

    let no_locks = BTreeSet::new();
    let mut edit = generate_deterministic_repairs(RepairGenerationInput {
        base: &fixture.base,
        mutations: &mutations,
        requirements: &fixture.requirements,
        report: &report,
        author_locked_ids: &no_locks,
    })
    .candidates
    .into_iter()
    .find(|edit| edit.preserves_mutation)
    .expect("preserving repair");
    edit.preconditions
        .push(RepairPrecondition::ConstraintExists {
            constraint_id: "constraint:missing".into(),
        });
    let result = simulate_repair_candidate(
        simulation_input(&fixture, &mutations, &report, &no_locks),
        &edit,
    );
    assert!(matches!(
        result,
        Err(RepairSimulationError::Precondition(_))
    ));
}

fn simulate(
    fixture: &crate::truth_adapter::tests::CaseFixture,
    mutations: &[phoenix_types::StoryMutation],
    report: &RevisionImpactReport,
    locks: &BTreeSet<CompactString>,
    edit: &ProposedEdit,
) -> RepairCandidate {
    simulate_repair_candidate(simulation_input(fixture, mutations, report, locks), edit)
        .expect("repair simulation")
}

fn simulation_input<'a>(
    fixture: &'a crate::truth_adapter::tests::CaseFixture,
    mutations: &'a [phoenix_types::StoryMutation],
    report: &'a RevisionImpactReport,
    locks: &'a BTreeSet<CompactString>,
) -> RepairSimulationInput<'a> {
    RepairSimulationInput {
        base: &fixture.base,
        mutations,
        requirements: &fixture.requirements,
        temporal: Some(&fixture.temporal),
        memory: Some(&fixture.memory),
        causal: Some(&fixture.causal),
        original_report: report,
        author_locked_ids: locks,
        ripple_config: RippleConfig::default(),
    }
}

fn report_for(
    gold: &RevisionImpactGoldCase,
    projection: &GoldProjectionCase,
) -> RevisionImpactReport {
    let fixture = case_fixture(gold, projection);
    let bundle = project_authoritative_constraints(AuthoritativeRevisionSources {
        base: &fixture.base,
        requirements: &fixture.requirements,
        temporal: Some(&fixture.temporal),
        memory: Some(&fixture.memory),
        causal: Some(&fixture.causal),
    })
    .expect("authoritative constraints");
    let views = RevisionAnalysisViews::project(
        fixture.base.generation(),
        bundle.constraints,
        InferenceProjectionInput::default(),
    )
    .expect("constraint view");
    let overlay = CounterfactualGraphView::new(&fixture.base, vec![fixture.mutation])
        .expect("counterfactual overlay");
    let coverage_requests = gold
        .expected_unknowns
        .iter()
        .map(|unknown| SceneCoverageRequest {
            scene_id: unknown.scene_id.clone(),
            required_planes: unknown.missing_planes.clone(),
            unavailable_planes: unknown.missing_planes.clone(),
        })
        .collect::<Vec<_>>();
    detect_revision_impacts(
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
    .expect("revision impact report")
}

fn projection_case<'a>(
    cases: &'a [GoldProjectionCase],
    gold: &RevisionImpactGoldCase,
) -> &'a GoldProjectionCase {
    cases
        .iter()
        .find(|case| case.case_id == gold.case_id.0)
        .expect("projection case")
}
