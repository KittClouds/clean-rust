use std::collections::BTreeSet;
use std::sync::LazyLock;

use phoenix_types::{RevisionImpactGoldCase, StoryInterval, StoryMutation, StoryTime};

use super::*;
use crate::truth_adapter::tests::{case_fixture, gold_fixtures, GoldProjectionCase};
use crate::{
    detect_revision_impacts, generate_author_directed_repairs, project_authoritative_constraints,
    AuthorDirectiveGenerationInput, AuthorRepairDirectiveCorpus, AuthoritativeRevisionSources,
    CounterfactualGraphView, IdentityCoverage, InferenceProjectionInput, RepairDisposition,
    RevisionAnalysisViews, RevisionDetectorInput, RevisionImpactReport, RippleConfig,
    SceneCoverageRequest,
};

static NO_LOCKS: LazyLock<BTreeSet<compact_str::CompactString>> = LazyLock::new(BTreeSet::new);

fn author_directives() -> AuthorRepairDirectiveCorpus {
    serde_json::from_str(include_str!(
        "../fixtures/revision-repair-author-directives-v1.json"
    ))
    .expect("author directive fixture")
}

#[test]
fn delayed_reveal_shadow_rebuild_proves_all_author_outcomes_without_truth_writes() {
    let (gold, projections) = gold_fixtures();
    let gold_case = gold
        .cases
        .iter()
        .find(|case| case.case_id.0 == "gold:delayed_reveal")
        .unwrap();
    let projection = projection_case(&projections.cases, gold_case);
    let fixture = case_fixture(gold_case, projection);
    let report = report_for(gold_case, projection);
    let edit = preferred_edit(&report);
    let base_digest = fixture.base.digest();
    let mutations = [fixture.mutation.clone()];

    let result =
        execute_shadow_semantic_repair(simulation_input(&fixture, &report, &mutations), &edit)
            .expect("shadow semantic repair");

    assert_eq!(result.candidate.disposition, RepairDisposition::ProvenFix);
    assert_eq!(result.candidate.fixed_constraints.len(), 3);
    assert!(result.candidate.remaining_violations.is_empty());
    assert!(result.candidate.introduced_violations.is_empty());
    assert_eq!(result.semantic_deltas.len(), 16);
    assert!(result.receipt.all_outcomes_satisfied);
    assert!(result
        .receipt
        .outcomes
        .iter()
        .all(|outcome| outcome.satisfied));
    assert!(result.receipt.full_shadow_revalidation_completed);
    assert!(result.receipt.committed_base_unchanged);
    assert!(result.receipt.no_truth_writes);
    assert_eq!(result.receipt.copy_on_write_clones, 3);
    assert_ne!(
        result.receipt.shadow_snapshot_digest,
        result.receipt.committed_base_digest
    );
    assert_eq!(fixture.base.digest(), base_digest);
    assert_eq!(result.candidate.edit, edit);
}

#[test]
fn delayed_reveal_shadow_execution_and_receipts_are_deterministic() {
    let (gold, projections) = gold_fixtures();
    let gold_case = &gold.cases[0];
    assert_eq!(gold_case.case_id.0, "gold:delayed_reveal");
    let projection = projection_case(&projections.cases, gold_case);
    let fixture = case_fixture(gold_case, projection);
    let report = report_for(gold_case, projection);
    let edit = preferred_edit(&report);
    let mutations = [fixture.mutation.clone()];

    let first =
        execute_shadow_semantic_repair(simulation_input(&fixture, &report, &mutations), &edit)
            .unwrap();
    let second =
        execute_shadow_semantic_repair(simulation_input(&fixture, &report, &mutations), &edit)
            .unwrap();
    assert_eq!(first, second);
}

#[test]
fn wrong_knowledge_boundary_downgrades_the_candidate_to_unknown() {
    let (gold, projections) = gold_fixtures();
    let gold_case = &gold.cases[0];
    let projection = projection_case(&projections.cases, gold_case);
    let fixture = case_fixture(gold_case, projection);
    let report = report_for(gold_case, projection);
    let edit = preferred_edit(&report);
    let mutations = [StoryMutation::ShiftValidity {
        fact_id: "fact:silas_knows_kai".into(),
        new_interval: StoryInterval {
            valid_from: StoryTime(1100),
            valid_to_exclusive: None,
        },
    }];

    let result =
        execute_shadow_semantic_repair(simulation_input(&fixture, &report, &mutations), &edit)
            .unwrap();
    assert_eq!(result.candidate.disposition, RepairDisposition::Unknown);
    assert!(!result.receipt.all_outcomes_satisfied);
    assert!(!result.receipt.full_shadow_revalidation_completed);
    assert!(result
        .receipt
        .outcomes
        .iter()
        .any(
            |outcome| outcome.outcome_id == "silas_first_knowledge_at_ch12" && !outcome.satisfied
        ));
    assert!(result.receipt.no_truth_writes);
}

fn preferred_edit(report: &RevisionImpactReport) -> ProposedEdit {
    let directives = author_directives();
    let directive = directives
        .for_case("gold:delayed_reveal")
        .expect("delayed reveal directive");
    generate_author_directed_repairs(AuthorDirectiveGenerationInput {
        report,
        directives: std::slice::from_ref(directive),
        author_locked_ids: &NO_LOCKS,
    })
    .candidates
    .remove(0)
}

fn simulation_input<'a>(
    fixture: &'a crate::truth_adapter::tests::CaseFixture,
    report: &'a RevisionImpactReport,
    mutations: &'a [StoryMutation],
) -> RepairSimulationInput<'a> {
    RepairSimulationInput {
        base: &fixture.base,
        mutations,
        requirements: &fixture.requirements,
        temporal: Some(&fixture.temporal),
        memory: Some(&fixture.memory),
        causal: Some(&fixture.causal),
        original_report: report,
        author_locked_ids: &NO_LOCKS,
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
