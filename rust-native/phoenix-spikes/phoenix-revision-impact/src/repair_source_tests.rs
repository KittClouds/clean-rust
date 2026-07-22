use std::collections::BTreeSet;

use phoenix_types::{RepairTemplateKind, RevisionImpactGoldCase};

use super::*;
use crate::truth_adapter::tests::{case_fixture, gold_fixtures, CaseFixture, GoldProjectionCase};
use crate::{
    detect_revision_impacts, generate_deterministic_repairs, project_authoritative_constraints,
    AuthoritativeRevisionSources, CounterfactualGraphView, EvidenceRef, IdentityCoverage,
    InferenceProjectionInput, RepairDisposition, RepairGenerationInput, RevisionAnalysisViews,
    RevisionDetectorInput, RevisionImpactReport, RippleConfig, SceneCoverageRequest,
};

#[test]
fn exact_source_binding_rewrites_shadow_and_rebuilds_sidecar() {
    let (fixture, report, mutations, documents) = anchored_gold_case(0);
    let edit = generated_statement_repairs(&fixture, &report, &mutations)
        .into_iter()
        .next()
        .expect("statement repair");
    let bound = bind_repair_sources(&edit, &documents).expect("source binding");
    assert_eq!(bound.source_bindings.len(), bound.operations.len());
    let before = documents.digest();
    let shadow = apply_source_bound_edit(&documents, &fixture.requirements, &bound)
        .expect("shadow source edit");
    assert_eq!(documents.digest(), before);
    assert_ne!(shadow.revised_documents.digest(), before);
    assert!(shadow.receipt.exact_operation_coverage);
    assert!(shadow.receipt.original_documents_unchanged);
    assert!(shadow.receipt.no_source_writes);
    assert_eq!(
        fixture.requirements.requirements.len() - shadow.rebuilt_requirements.requirements.len(),
        bound.source_bindings.len()
    );
}

#[test]
fn all_seven_gold_cases_reproduce_statement_repairs_from_shadow_source() {
    for case_index in 0..7 {
        let (fixture, report, mutations, documents) = anchored_gold_case(case_index);
        let repairs = generated_statement_repairs(&fixture, &report, &mutations);
        assert!(!repairs.is_empty());
        for edit in repairs {
            let bound = bind_repair_sources(&edit, &documents).expect("gold source binding");
            let validated = simulate_source_bound_candidate(
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
                &documents,
                &bound,
            )
            .expect("source-bound repair simulation");
            assert_eq!(
                validated.candidate.disposition,
                RepairDisposition::ProvenFix
            );
            assert!(validated.source_validation.exact_operation_coverage);
            assert_eq!(
                validated.source_validation.bound_constraint_ids,
                validated.candidate.edit.source_constraints
            );
        }
    }
}

#[test]
fn unanchored_ambiguous_and_changed_source_fail_closed() {
    let (fixture, report, mutations, documents) = anchored_gold_case(0);
    let edit = generated_statement_repairs(&fixture, &report, &mutations)
        .into_iter()
        .next()
        .expect("statement repair");
    let mut unanchored = edit.clone();
    let GraphEditOperation::RemoveRequirementBearingStatement { evidence, .. } =
        &mut unanchored.operations[0]
    else {
        panic!("statement operation");
    };
    evidence[0].document_id = None;
    evidence[0].source_range = None;
    assert!(matches!(
        bind_repair_sources(&unanchored, &documents),
        Err(RepairSourceError::UnanchoredConstraint(_))
    ));

    let mut ambiguous = edit.clone();
    let GraphEditOperation::RemoveRequirementBearingStatement { evidence, .. } =
        &mut ambiguous.operations[0]
    else {
        panic!("statement operation");
    };
    let mut second = evidence[0].clone();
    second.evidence_id = "evidence:ambiguous".into();
    evidence.push(second);
    assert!(matches!(
        bind_repair_sources(&ambiguous, &documents),
        Err(RepairSourceError::AmbiguousAnchors(_))
    ));

    let mut split_utf8 = edit.clone();
    let GraphEditOperation::RemoveRequirementBearingStatement { evidence, .. } =
        &mut split_utf8.operations[0]
    else {
        panic!("statement operation");
    };
    evidence[0].document_id = Some("document:utf8".into());
    evidence[0].source_range = Some(SourceRange { start: 1, end: 2 });
    let utf8_documents = SourceDocumentSet::new(
        documents.generation(),
        vec![SourceDocument::utf8("document:utf8", "éclair")],
    )
    .unwrap();
    assert!(matches!(
        bind_repair_sources(&split_utf8, &utf8_documents),
        Err(RepairSourceError::InvalidUtf8Boundary(_))
    ));

    let bound = bind_repair_sources(&edit, &documents).expect("source binding");
    let mut changed_documents = documents.documents().to_vec();
    let changed = &bound.source_bindings[0];
    let document = changed_documents
        .iter_mut()
        .find(|document| document.document_id == changed.document_id)
        .expect("bound document");
    let mut text = String::from_utf8(document.bytes().to_vec()).expect("fixture utf8");
    let replacement =
        "x".repeat(changed.source_range.end as usize - changed.source_range.start as usize);
    text.replace_range(
        changed.source_range.start as usize..changed.source_range.end as usize,
        &replacement,
    );
    *document = SourceDocument::utf8(document.document_id.clone(), text);
    let changed_set = SourceDocumentSet::new(documents.generation(), changed_documents).unwrap();
    assert!(matches!(
        apply_source_bound_edit(&changed_set, &fixture.requirements, &bound),
        Err(RepairSourceError::SpanDigestMismatch(_))
    ));
}

fn anchored_gold_case(
    case_index: usize,
) -> (
    CaseFixture,
    RevisionImpactReport,
    Vec<phoenix_types::StoryMutation>,
    SourceDocumentSet,
) {
    let (gold, projections) = gold_fixtures();
    let gold_case = &gold.cases[case_index];
    let projection = projection_case(&projections.cases, gold_case);
    let mut fixture = case_fixture(gold_case, projection);
    let documents = anchor_requirements(&mut fixture);
    let report = report_from_fixture(gold_case, &fixture);
    let mutations = vec![fixture.mutation.clone()];
    (fixture, report, mutations, documents)
}

fn anchor_requirements(fixture: &mut CaseFixture) -> SourceDocumentSet {
    let mut documents = Vec::with_capacity(fixture.requirements.requirements.len());
    for requirement in &mut fixture.requirements.requirements {
        let document_id = format!("document:{}", requirement.constraint_id);
        let text = format!(
            "Scene {}. Requirement statement for {}.",
            requirement.dependent_scene_id.0, requirement.constraint_id
        );
        let range = SourceRange {
            start: 0,
            end: u32::try_from(text.len()).expect("gold source length"),
        };
        requirement.evidence = vec![EvidenceRef {
            evidence_id: format!("evidence:source:{}", requirement.constraint_id).into(),
            document_id: Some(document_id.clone().into()),
            source_range: Some(range),
        }];
        documents.push(SourceDocument::utf8(document_id, text));
    }
    SourceDocumentSet::new(fixture.base.generation(), documents).expect("gold source documents")
}

fn generated_statement_repairs(
    fixture: &CaseFixture,
    report: &RevisionImpactReport,
    mutations: &[phoenix_types::StoryMutation],
) -> Vec<ProposedEdit> {
    generate_deterministic_repairs(RepairGenerationInput {
        base: &fixture.base,
        mutations,
        requirements: &fixture.requirements,
        report,
        author_locked_ids: &BTreeSet::new(),
    })
    .candidates
    .into_iter()
    .filter(|edit| edit.template == RepairTemplateKind::ReviseRequirementBearingStatement)
    .collect()
}

fn report_from_fixture(
    gold: &RevisionImpactGoldCase,
    fixture: &CaseFixture,
) -> RevisionImpactReport {
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
    let overlay = CounterfactualGraphView::new(&fixture.base, vec![fixture.mutation.clone()])
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
