use std::collections::{BTreeMap, BTreeSet};

use phoenix_types::{
    ConstraintKind, GoldMutationFamily, ImpactClassification, RevisionImpactGoldCase,
};

use super::*;
use crate::truth_adapter::tests::{case_fixture, gold_fixtures, GoldProjectionCase};
use crate::{
    project_authoritative_constraints, AuthoritativeRevisionSources, CounterfactualGraphView,
    IdentityAmbiguity, IdentityAmbiguitySide, IdentityMatch, IdentityMatchBasis,
    RevisionAnalysisViews, RevisionIdentityMap, REVISION_IDENTITY_SCHEMA,
};

#[test]
fn all_seven_gold_cases_emit_exact_impacts_unknowns_and_empty_model_overlays() {
    let (gold, projection) = gold_fixtures();
    let mut hard_expected = 0;
    let mut hard_found = 0;

    for gold_case in &gold.cases {
        let projection_case = projection_case(&projection.cases, gold_case);
        let report = report_for(gold_case, projection_case);
        let actual = report
            .authoritative_impacts
            .iter()
            .map(|impact| (impact.scene_id.0.as_str(), impact.classification))
            .collect::<BTreeMap<_, _>>();
        let expected = gold_case
            .expected_impacts
            .iter()
            .map(|impact| (impact.scene_id.0.as_str(), impact.classification))
            .chain(
                gold_case
                    .expected_unknowns
                    .iter()
                    .map(|impact| (impact.scene_id.0.as_str(), ImpactClassification::Unknown)),
            )
            .collect::<BTreeMap<_, _>>();
        assert_eq!(actual, expected, "case {}", gold_case.case_id.0);
        assert!(report
            .authoritative_impacts
            .windows(2)
            .all(|pair| impact_order(&pair[0], &pair[1]) != std::cmp::Ordering::Greater));

        for expected_unknown in &gold_case.expected_unknowns {
            let impact = report
                .authoritative_impacts
                .iter()
                .find(|impact| impact.scene_id == expected_unknown.scene_id)
                .expect("unknown impact");
            let mut expected_missing = expected_unknown.missing_planes.clone();
            canonicalize_planes(&mut expected_missing);
            assert_eq!(
                impact.coverage.missing_required_planes, expected_missing,
                "case {}",
                gold_case.case_id.0
            );
            assert!(!impact.coverage.classification_supported);
        }
        assert!(report
            .authoritative_impacts
            .iter()
            .filter(|impact| impact.classification != ImpactClassification::Unknown)
            .all(|impact| impact.coverage.classification_supported));
        assert!(report.model_overlays.is_empty());
        assert_eq!(
            report.deterministic_receipt.model_integration_state,
            ModelIntegrationState::Disabled
        );
        assert_eq!(report.deterministic_receipt.model_overlay_count, 0);
        assert!(report.deterministic_receipt.no_truth_writes);
        assert!(report
            .deterministic_receipt
            .coverage_warning_planes
            .contains(&CoveragePlane::Capability));

        hard_expected += gold_case
            .expected_impacts
            .iter()
            .filter(|impact| impact.classification == ImpactClassification::Broken)
            .count();
        hard_found += report
            .authoritative_impacts
            .iter()
            .filter(|impact| impact.classification == ImpactClassification::Broken)
            .count();
    }
    assert_eq!(hard_found, hard_expected);
    assert_eq!(hard_expected, 8);
}

#[test]
fn detector_consumes_but_does_not_create_author_review_metadata() {
    let (gold, _) = gold_fixtures();
    assert!(gold.author_review_complete());
    assert!(gold.pending_author_review_ids().is_empty());
    assert!(gold.cases.iter().all(|case| {
        case.reviewed_by.as_deref() == Some("author:workspace-owner")
            && case.reviewed_at_unix_ms == Some(1784295149199)
    }));
}

#[test]
fn presentation_overlays_never_modify_authoritative_impacts_or_digest() {
    let (gold, projection) = gold_fixtures();
    let mut report = report_for(&gold.cases[0], &projection.cases[0]);
    let authoritative = report.authoritative_impacts.clone();
    let digest = report.deterministic_receipt.report_digest;
    let generation = report.deterministic_receipt.generation;
    attach_model_overlays(
        &mut report,
        vec![ModelRelevanceOverlay {
            model_id: "gfm-rag-8m".into(),
            generation,
            kind: ModelOverlayKind::Retrieval,
            query_mode: ModelQueryMode::Cached,
            start_node_ids: vec!["entity:mutation".into()],
            target_node_type: Some("scene".into()),
            ranked_nodes: vec![ModelRankedNode {
                node_id: "scene:chapter_5_iriane_assignment".into(),
                node_type: "scene".into(),
                rank: 1,
                raw_score: 0.5,
                score_millis: 500,
                evidence_targets: vec!["evidence:gold:delayed_reveal:0".into()],
            }],
            full_latency_micros: 42,
            peak_resident_bytes: 1_024,
            presentation_only: true,
        }],
        ExperimentalModelOverlayPermit::for_isolated_harness(),
    )
    .unwrap();
    assert_eq!(report.authoritative_impacts, authoritative);
    assert_eq!(report.deterministic_receipt.report_digest, digest);
    assert_eq!(report.deterministic_receipt.model_overlay_count, 1);
    assert_eq!(
        report.deterministic_receipt.model_integration_state,
        ModelIntegrationState::ExperimentalPresentationOnly
    );
}

#[test]
fn complete_report_and_serialized_receipt_are_deterministic() {
    let (gold, projection) = gold_fixtures();
    for gold_case in &gold.cases {
        let projection_case = projection_case(&projection.cases, gold_case);
        let first = report_for(gold_case, projection_case);
        let second = report_for(gold_case, projection_case);
        assert_eq!(first, second, "case {}", gold_case.case_id.0);
        assert_eq!(
            serde_json::to_vec(&first).unwrap(),
            serde_json::to_vec(&second).unwrap(),
            "case {}",
            gold_case.case_id.0
        );
        assert!(!first.deterministic_receipt.report_digest.is_zero());
    }
}

#[test]
fn detector_improves_over_keyword_and_existing_conflict_baselines() {
    let (gold, projection) = gold_fixtures();
    let mut expected = BTreeSet::new();
    let mut detector = BTreeSet::new();
    let mut keyword = BTreeSet::new();
    let mut existing_conflicts = BTreeSet::new();

    for gold_case in &gold.cases {
        let report = report_for(gold_case, projection_case(&projection.cases, gold_case));
        let case_id = gold_case.case_id.0.as_str();
        for impact in &gold_case.expected_impacts {
            let key = format!("{case_id}|{}", impact.scene_id.0);
            if impact.classification == ImpactClassification::Broken {
                expected.insert(key.clone());
            }
            if keyword_hit(gold_case.family, impact.rationale.as_str()) {
                keyword.insert(key.clone());
            }
            // The current continuity reporter only receives already-extracted temporal
            // conflicts. Give it an optimistic hit for every temporal-order violation.
            if impact
                .constraint_kinds
                .contains(&ConstraintKind::RequiresTemporalOrder)
            {
                existing_conflicts.insert(key);
            }
        }
        for impact in &gold_case.expected_unknowns {
            if keyword_hit(gold_case.family, impact.rationale.as_str()) {
                keyword.insert(format!("{case_id}|{}", impact.scene_id.0));
            }
        }
        detector.extend(
            report
                .authoritative_impacts
                .iter()
                .filter(|impact| impact.classification == ImpactClassification::Broken)
                .map(|impact| format!("{case_id}|{}", impact.scene_id.0)),
        );
    }

    let detector_metrics = metrics(&detector, &expected);
    let keyword_metrics = metrics(&keyword, &expected);
    let conflict_metrics = metrics(&existing_conflicts, &expected);
    println!(
        "detector_recall_bp={} detector_precision_bp={} detector_f1_bp={}",
        detector_metrics.recall_bp, detector_metrics.precision_bp, detector_metrics.f1_bp
    );
    println!(
        "keyword_recall_bp={} keyword_precision_bp={} keyword_f1_bp={}",
        keyword_metrics.recall_bp, keyword_metrics.precision_bp, keyword_metrics.f1_bp
    );
    println!(
        "existing_conflict_recall_bp={} existing_conflict_precision_bp={} existing_conflict_f1_bp={}",
        conflict_metrics.recall_bp, conflict_metrics.precision_bp, conflict_metrics.f1_bp
    );
    assert_eq!(detector_metrics.recall_bp, 10_000);
    assert_eq!(detector_metrics.precision_bp, 10_000);
    assert!(detector_metrics.f1_bp > keyword_metrics.f1_bp);
    assert!(detector_metrics.f1_bp > conflict_metrics.f1_bp);
}

#[test]
fn projection_receipt_mismatch_fails_before_propagation() {
    let (gold, projection) = gold_fixtures();
    let gold_case = &gold.cases[0];
    let projection_case = projection_case(&projection.cases, gold_case);
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
    let overlay = CounterfactualGraphView::new(&fixture.base, vec![fixture.mutation]).unwrap();
    let mut receipt = bundle.receipt;
    receipt.projected_constraints += 1;
    let error = detect_revision_impacts(
        RevisionDetectorInput {
            overlay: &overlay,
            constraint_graph: &views.constraint_graph,
            requirements: &fixture.requirements,
            projection_receipt: &receipt,
            identity_coverage: IdentityCoverage::SameRevision,
            coverage_requests: &[],
        },
        RippleConfig::default(),
    )
    .unwrap_err();
    assert!(matches!(
        error,
        RevisionDetectorError::ProjectionReceiptMismatch
    ));
}

#[test]
fn cross_revision_identity_coverage_distinguishes_matches_ambiguity_and_absence() {
    let identity = RevisionIdentityMap {
        schema_version: REVISION_IDENTITY_SCHEMA.into(),
        previous_revision: 1,
        current_revision: 2,
        scene_matches: vec![IdentityMatch {
            previous_id: "scene:old".into(),
            current_id: "scene:matched".into(),
            score_millis: 1000,
            basis: IdentityMatchBasis::default(),
        }],
        event_matches: Vec::new(),
        fact_matches: Vec::new(),
        splits: Vec::new(),
        merges: Vec::new(),
        ambiguous: vec![IdentityAmbiguity {
            side: IdentityAmbiguitySide::Current,
            subject_id: "scene:ambiguous".into(),
            candidate_ids: vec!["scene:candidate".into()],
            top_score_millis: 800,
        }],
        unmatched_previous_ids: Vec::new(),
        unmatched_current_ids: vec!["scene:missing".into()],
    };
    let coverage = IdentityCoverage::CrossRevision(&identity);
    assert_eq!(
        identity_status(coverage, "scene:matched"),
        CoverageStatus::Covered
    );
    assert_eq!(
        identity_status(coverage, "scene:ambiguous"),
        CoverageStatus::Partial
    );
    assert_eq!(
        identity_status(coverage, "scene:missing"),
        CoverageStatus::Unavailable
    );
}

fn report_for(
    gold_case: &RevisionImpactGoldCase,
    projection_case: &GoldProjectionCase,
) -> RevisionImpactReport {
    let fixture = case_fixture(gold_case, projection_case);
    let bundle = project_authoritative_constraints(AuthoritativeRevisionSources {
        base: &fixture.base,
        requirements: &fixture.requirements,
        temporal: Some(&fixture.temporal),
        memory: Some(&fixture.memory),
        causal: Some(&fixture.causal),
    })
    .expect("authoritative projection");
    let views = RevisionAnalysisViews::project(
        fixture.base.generation(),
        bundle.constraints,
        fixture.inference,
    )
    .expect("analysis views");
    let overlay = CounterfactualGraphView::new(&fixture.base, vec![fixture.mutation])
        .expect("counterfactual overlay");
    let coverage_requests = gold_case
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
    .expect("Phase 5 report")
}

fn projection_case<'a>(
    cases: &'a [GoldProjectionCase],
    gold_case: &RevisionImpactGoldCase,
) -> &'a GoldProjectionCase {
    cases
        .iter()
        .find(|case| case.case_id == gold_case.case_id.0)
        .expect("projection case")
}

fn keyword_hit(family: GoldMutationFamily, text: &str) -> bool {
    let text = text.to_ascii_lowercase();
    keyword_terms(family).iter().any(|term| text.contains(term))
}

const fn keyword_terms(family: GoldMutationFamily) -> &'static [&'static str] {
    match family {
        GoldMutationFamily::DelayedReveal => &["silas", "kai"],
        GoldMutationFamily::EarlierDeath => &["mara"],
        GoldMutationFamily::ChangedWitness => &["tamsin", "orin"],
        GoldMutationFamily::ChangedPowerLimitation => &["kai", "limit"],
        GoldMutationFamily::ChangedTravelDuration => &["travel", "timing", "fort"],
        GoldMutationFamily::RemovedRelationship => &["hazel", "relationship"],
        GoldMutationFamily::ChangedPossession => &["kai", "hazel", "key"],
    }
}

#[derive(Clone, Copy)]
struct Metrics {
    recall_bp: usize,
    precision_bp: usize,
    f1_bp: usize,
}

fn metrics(actual: &BTreeSet<String>, expected: &BTreeSet<String>) -> Metrics {
    let true_positive = actual.intersection(expected).count();
    Metrics {
        recall_bp: ratio_bp(true_positive, expected.len()),
        precision_bp: ratio_bp(true_positive, actual.len()),
        f1_bp: ratio_bp(2 * true_positive, actual.len() + expected.len()),
    }
}

fn ratio_bp(numerator: usize, denominator: usize) -> usize {
    (numerator * 10_000).checked_div(denominator).unwrap_or(0)
}
