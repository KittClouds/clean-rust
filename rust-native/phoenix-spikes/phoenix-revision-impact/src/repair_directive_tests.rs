use std::collections::BTreeSet;

use phoenix_types::RevisionImpactGoldCase;

use super::*;
use crate::truth_adapter::tests::{case_fixture, gold_fixtures, GoldProjectionCase};
use crate::{
    detect_revision_impacts, project_authoritative_constraints, simulate_repair_candidate,
    AuthoritativeRevisionSources, CounterfactualGraphView, IdentityCoverage,
    InferenceProjectionInput, RepairDisposition, RepairSimulationInput, RevisionAnalysisViews,
    RevisionDetectorInput, RevisionImpactReport, RippleConfig, SceneCoverageRequest,
};

fn author_directives() -> AuthorRepairDirectiveCorpus {
    serde_json::from_str(include_str!(
        "../fixtures/revision-repair-author-directives-v1.json"
    ))
    .expect("author directive fixture")
}

#[test]
fn confirmed_author_directives_are_complete_typed_and_deterministic() {
    let directives = author_directives();
    let (gold, _) = gold_fixtures();
    directives.validate().expect("valid author directives");
    assert_eq!(directives.cases.len(), 7);
    assert!(directives
        .cases
        .iter()
        .all(|directive| is_author_directed_template(directive.template)));
    assert_eq!(directives.digest().unwrap(), directives.digest().unwrap());
    assert!(!directives.digest().unwrap().is_zero());
    for gold_case in &gold.cases {
        let directive = directives.for_case(&gold_case.case_id.0).unwrap();
        assert_eq!(gold_case.reasonable_repairs.len(), 1);
        let preferred = &gold_case.reasonable_repairs[0];
        assert_eq!(preferred.repair_id.0, directive.directive_id);
        assert_eq!(preferred.kind, directive.template);
        assert_eq!(preferred.target_scene_ids, directive.target_scene_ids);
    }
}

#[test]
fn every_author_directive_emits_one_preferred_candidate_that_abstains() {
    let directives = author_directives();
    let (gold, projections) = gold_fixtures();
    assert!(gold.author_review_complete());

    for gold_case in &gold.cases {
        let projection = projection_case(&projections.cases, gold_case);
        let fixture = case_fixture(gold_case, projection);
        let report = report_for(gold_case, projection);
        let directive = directives
            .for_case(&gold_case.case_id.0)
            .expect("case directive");
        let first = generate_author_directed_repairs(AuthorDirectiveGenerationInput {
            report: &report,
            directives: std::slice::from_ref(directive),
            author_locked_ids: &BTreeSet::new(),
        });
        let second = generate_author_directed_repairs(AuthorDirectiveGenerationInput {
            report: &report,
            directives: std::slice::from_ref(directive),
            author_locked_ids: &BTreeSet::new(),
        });
        assert_eq!(first, second);
        assert_eq!(first.candidates.len(), 1);
        let edit = &first.candidates[0];
        assert_eq!(edit.edit_id.0, directive.directive_id);
        assert_eq!(edit.template, directive.template);
        assert!(edit.preserves_mutation);
        assert!(matches!(
            edit.operations.as_slice(),
            [GraphEditOperation::ApplyAuthorDirective { .. }]
        ));
        let mutations = [fixture.mutation.clone()];
        let candidate = simulate_repair_candidate(
            RepairSimulationInput {
                base: &fixture.base,
                mutations: &mutations,
                requirements: &fixture.requirements,
                temporal: Some(&fixture.temporal),
                memory: Some(&fixture.memory),
                causal: Some(&fixture.causal),
                original_report: &report,
                author_locked_ids: &BTreeSet::new(),
                ripple_config: RippleConfig::default(),
            },
            edit,
        )
        .expect("author directive simulation");
        assert_eq!(candidate.disposition, RepairDisposition::Unknown);
        assert!(candidate.fixed_constraints.is_empty());
        assert!(!candidate.validation_receipt.full_revalidation_completed);
        assert!(
            !candidate
                .validation_receipt
                .coverage
                .complete_for_claimed_constraints
        );
        assert!(candidate.validation_receipt.base_graph_unchanged);
        assert!(candidate.validation_receipt.no_truth_writes);
    }
}

#[test]
fn author_locks_skip_directives_without_partial_emission() {
    let directives = author_directives();
    let (gold, projections) = gold_fixtures();
    let gold_case = &gold.cases[0];
    let report = report_for(gold_case, projection_case(&projections.cases, gold_case));
    let directive = directives.for_case(&gold_case.case_id.0).unwrap();
    let locked = BTreeSet::from([directive.target_scene_ids[0].0.clone()]);
    let result = generate_author_directed_repairs(AuthorDirectiveGenerationInput {
        report: &report,
        directives: std::slice::from_ref(directive),
        author_locked_ids: &locked,
    });
    assert!(result.candidates.is_empty());
    assert_eq!(
        result.receipt.skipped_locked_directive_ids,
        vec![directive.directive_id.clone()]
    );
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
    .expect("impact report")
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
