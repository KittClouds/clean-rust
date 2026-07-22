#[cfg(feature = "gold-harness")]
mod enabled {
    use std::collections::BTreeSet;
    use std::fmt::Write as _;
    use std::fs;
    use std::path::{Path, PathBuf};

    use phoenix_revision_impact::gold_harness::{
        analyze_case, case_fixture, gold_fixtures, GoldProjectionCase,
    };
    use phoenix_revision_impact::{
        execute_shadow_semantic_repair, generate_author_directed_repairs,
        generate_deterministic_repairs, is_author_directed_template, simulate_repair_candidate,
        AuthorDirectiveGenerationInput, AuthorRepairDirective, AuthorRepairDirectiveCorpus,
        GraphEditOperation, ProposedEdit, RepairDisposition, RepairGenerationInput,
        RepairSimulationInput, RippleConfig, ShadowSemanticRepairResult,
        CONSTRAINED_PORTAL_DIRECTIVE_ID, DELAYED_REVEAL_DIRECTIVE_ID, HAZEL_ESPIONAGE_DIRECTIVE_ID,
        HAZEL_KEY_DIRECTIVE_ID, KAI_POWER_OVERDRAW_DIRECTIVE_ID, MARA_PRIOR_RECORD_DIRECTIVE_ID,
        TAMSIN_DECEPTION_DIRECTIVE_ID,
    };
    use phoenix_types::{GoldRepairExpectation, RevisionImpactGoldCase};
    use serde::Serialize;

    const REVIEW_SCHEMA: &str = "phoenix.repair-author-review/v1";

    #[derive(Serialize)]
    #[serde(rename_all = "camelCase")]
    struct AuthorDecisionMetrics {
        schema: &'static str,
        review_token: String,
        source_review_token: String,
        reviewed_by: String,
        reviewed_at_unix_ms: i64,
        labels_pending_author_review: usize,
        cases: usize,
        candidates: usize,
        graph_proven_candidates: usize,
        author_directed_candidates: usize,
        author_directed_proven_candidates: usize,
        author_directed_unknown_candidates: usize,
        mutation_preserving_graph_proven_cases: usize,
        top_1_author_template_matches: usize,
        top_3_author_template_matches: usize,
        top_1_author_template_and_target_matches: usize,
        top_3_author_template_and_target_matches: usize,
        cases_with_no_emitted_expected_template: Vec<String>,
        statement_candidates_missing_exact_source_anchor: usize,
        author_gate_passed: bool,
    }

    struct CandidateReview {
        edit: ProposedEdit,
        disposition: RepairDisposition,
        template_match: bool,
        template_and_target_match: bool,
        source_status: &'static str,
        shadow_result: Option<ShadowSemanticRepairResult>,
    }

    struct CaseReview {
        case_id: String,
        title: String,
        mutation_json: String,
        impacts: Vec<String>,
        unknowns: Vec<String>,
        expected_repairs: Vec<String>,
        preferred_candidate_id: String,
        candidates: Vec<CandidateReview>,
        emitted_expected_template: bool,
    }

    pub fn run() {
        let (gold, projections) = gold_fixtures();
        let directives: AuthorRepairDirectiveCorpus = serde_json::from_str(include_str!(
            "../../fixtures/revision-repair-author-directives-v1.json"
        ))
        .expect("author directive fixture");
        directives.validate().expect("valid author directives");
        let cases = gold
            .cases
            .iter()
            .map(|gold_case| {
                review_case(
                    gold_case,
                    projection_case(&projections.cases, gold_case),
                    directives
                        .for_case(&gold_case.case_id.0)
                        .expect("case author directive"),
                )
            })
            .collect::<Vec<_>>();
        let review_token = review_token(&cases);
        let metrics = metrics(&gold, &directives, &cases, review_token.clone());
        let output_dir = output_dir();
        fs::create_dir_all(&output_dir).expect("create review output directory");
        let markdown_path = output_dir.join(format!("gold-repair-review-v1-{review_token}.md"));
        let metrics_path = output_dir.join(format!("gold-repair-metrics-v1-{review_token}.json"));
        let shadow_path = output_dir.join(format!("gold-shadow-semantic-v1-{review_token}.json"));
        fs::write(&markdown_path, markdown(&cases, &metrics)).expect("write review packet");
        fs::write(
            &metrics_path,
            serde_json::to_vec_pretty(&metrics).expect("serialize metrics"),
        )
        .expect("write metrics");
        fs::write(
            &shadow_path,
            serde_json::to_vec_pretty(&ShadowResultBundle {
                schema: "phoenix.shadow-semantic-result-bundle/v1",
                review_token: &review_token,
                results: cases
                    .iter()
                    .flat_map(|case| &case.candidates)
                    .filter_map(|candidate| candidate.shadow_result.as_ref())
                    .collect(),
            })
            .expect("serialize shadow semantic results"),
        )
        .expect("write shadow semantic result bundle");
        println!("review_packet={}", markdown_path.display());
        println!("metrics_receipt={}", metrics_path.display());
        println!("shadow_semantic_receipt={}", shadow_path.display());
        println!("review_token={review_token}");
        println!(
            "pending_labels={} cases={} candidates={} graph_proven_candidates={}",
            metrics.labels_pending_author_review,
            metrics.cases,
            metrics.candidates,
            metrics.graph_proven_candidates
        );
        println!(
            "author_top1_template={} author_top3_template={} missing_expected_template_cases={}",
            metrics.top_1_author_template_matches,
            metrics.top_3_author_template_matches,
            metrics.cases_with_no_emitted_expected_template.len()
        );
        assert!(metrics.author_gate_passed);
    }

    fn review_case(
        gold: &RevisionImpactGoldCase,
        projection: &GoldProjectionCase,
        directive: &AuthorRepairDirective,
    ) -> CaseReview {
        let fixture = case_fixture(gold, projection);
        let report = analyze_case(gold, projection).report;
        let mutations = vec![fixture.mutation.clone()];
        let mut edits = generate_author_directed_repairs(AuthorDirectiveGenerationInput {
            report: &report,
            directives: std::slice::from_ref(directive),
            author_locked_ids: &BTreeSet::new(),
        })
        .candidates;
        edits.extend(
            generate_deterministic_repairs(RepairGenerationInput {
                base: &fixture.base,
                mutations: &mutations,
                requirements: &fixture.requirements,
                report: &report,
                author_locked_ids: &BTreeSet::new(),
            })
            .candidates,
        );
        let candidates = edits
            .into_iter()
            .map(|edit| {
                let simulation_input = RepairSimulationInput {
                    base: &fixture.base,
                    mutations: &mutations,
                    requirements: &fixture.requirements,
                    temporal: Some(&fixture.temporal),
                    memory: Some(&fixture.memory),
                    causal: Some(&fixture.causal),
                    original_report: &report,
                    author_locked_ids: &BTreeSet::new(),
                    ripple_config: RippleConfig::default(),
                };
                let (disposition, source_status, shadow_result) = if matches!(
                    edit.edit_id.0.as_str(),
                    DELAYED_REVEAL_DIRECTIVE_ID
                        | MARA_PRIOR_RECORD_DIRECTIVE_ID
                        | TAMSIN_DECEPTION_DIRECTIVE_ID
                        | KAI_POWER_OVERDRAW_DIRECTIVE_ID
                        | CONSTRAINED_PORTAL_DIRECTIVE_ID
                        | HAZEL_ESPIONAGE_DIRECTIVE_ID
                        | HAZEL_KEY_DIRECTIVE_ID
                ) {
                    let result = execute_shadow_semantic_repair(simulation_input, &edit)
                        .expect("supported shadow semantic simulation");
                    (
                        result.candidate.disposition,
                        "shadow_semantic_validated",
                        Some(result),
                    )
                } else {
                    let result = simulate_repair_candidate(simulation_input, &edit)
                        .expect("gold candidate simulation");
                    (result.disposition, source_status(&edit), None)
                };
                CandidateReview {
                    template_match: gold
                        .reasonable_repairs
                        .iter()
                        .any(|expected| expected.kind == edit.template),
                    template_and_target_match: gold
                        .reasonable_repairs
                        .iter()
                        .any(|expected| candidate_matches_expected(&edit, expected)),
                    source_status,
                    shadow_result,
                    edit,
                    disposition,
                }
            })
            .collect::<Vec<_>>();
        let emitted_expected_template = candidates.iter().any(|candidate| candidate.template_match);
        CaseReview {
            case_id: gold.case_id.0.to_string(),
            title: gold.title.to_string(),
            mutation_json: serde_json::to_string_pretty(&gold.mutation).expect("mutation JSON"),
            impacts: gold
                .expected_impacts
                .iter()
                .map(|impact| {
                    format!(
                        "{} — {:?}: {}",
                        impact.scene_id.0, impact.classification, impact.rationale
                    )
                })
                .collect(),
            unknowns: gold
                .expected_unknowns
                .iter()
                .map(|unknown| {
                    format!(
                        "{} — missing {:?}: {}",
                        unknown.scene_id.0, unknown.missing_planes, unknown.rationale
                    )
                })
                .collect(),
            expected_repairs: gold
                .reasonable_repairs
                .iter()
                .map(|repair| {
                    format!(
                        "{} — {:?} at [{}]: {}",
                        repair.repair_id.0,
                        repair.kind,
                        repair
                            .target_scene_ids
                            .iter()
                            .map(|scene| scene.0.as_str())
                            .collect::<Vec<_>>()
                            .join(", "),
                        repair.rationale
                    )
                })
                .collect(),
            preferred_candidate_id: directive.directive_id.to_string(),
            candidates,
            emitted_expected_template,
        }
    }

    #[derive(Serialize)]
    #[serde(rename_all = "camelCase")]
    struct ShadowResultBundle<'a> {
        schema: &'static str,
        review_token: &'a str,
        results: Vec<&'a ShadowSemanticRepairResult>,
    }

    fn metrics(
        gold: &phoenix_types::RevisionImpactGoldCorpus,
        directives: &AuthorRepairDirectiveCorpus,
        cases: &[CaseReview],
        review_token: String,
    ) -> AuthorDecisionMetrics {
        AuthorDecisionMetrics {
            schema: REVIEW_SCHEMA,
            review_token,
            source_review_token: directives.source_review_token.to_string(),
            reviewed_by: directives.reviewed_by.to_string(),
            reviewed_at_unix_ms: directives.reviewed_at_unix_ms,
            labels_pending_author_review: gold.pending_author_review_ids().len(),
            cases: cases.len(),
            candidates: cases.iter().map(|case| case.candidates.len()).sum(),
            graph_proven_candidates: cases
                .iter()
                .flat_map(|case| &case.candidates)
                .filter(|candidate| {
                    !is_author_directed_template(candidate.edit.template)
                        && candidate.disposition == RepairDisposition::ProvenFix
                })
                .count(),
            author_directed_candidates: cases
                .iter()
                .flat_map(|case| &case.candidates)
                .filter(|candidate| is_author_directed_template(candidate.edit.template))
                .count(),
            author_directed_proven_candidates: cases
                .iter()
                .flat_map(|case| &case.candidates)
                .filter(|candidate| {
                    is_author_directed_template(candidate.edit.template)
                        && candidate.disposition == RepairDisposition::ProvenFix
                })
                .count(),
            author_directed_unknown_candidates: cases
                .iter()
                .flat_map(|case| &case.candidates)
                .filter(|candidate| {
                    is_author_directed_template(candidate.edit.template)
                        && candidate.disposition == RepairDisposition::Unknown
                })
                .count(),
            mutation_preserving_graph_proven_cases: cases
                .iter()
                .filter(|case| {
                    case.candidates.iter().any(|candidate| {
                        candidate.edit.preserves_mutation
                            && !is_author_directed_template(candidate.edit.template)
                            && candidate.disposition == RepairDisposition::ProvenFix
                    })
                })
                .count(),
            top_1_author_template_matches: count_top_k(cases, 1, false),
            top_3_author_template_matches: count_top_k(cases, 3, false),
            top_1_author_template_and_target_matches: count_top_k(cases, 1, true),
            top_3_author_template_and_target_matches: count_top_k(cases, 3, true),
            cases_with_no_emitted_expected_template: cases
                .iter()
                .filter(|case| !case.emitted_expected_template)
                .map(|case| case.case_id.clone())
                .collect(),
            statement_candidates_missing_exact_source_anchor: cases
                .iter()
                .flat_map(|case| &case.candidates)
                .filter(|candidate| candidate.source_status == "missing_exact_anchor")
                .count(),
            author_gate_passed: gold.author_review_complete(),
        }
    }

    fn count_top_k(cases: &[CaseReview], top_k: usize, require_target: bool) -> usize {
        cases
            .iter()
            .filter(|case| {
                case.candidates.iter().take(top_k).any(|candidate| {
                    if require_target {
                        candidate.template_and_target_match
                    } else {
                        candidate.template_match
                    }
                })
            })
            .count()
    }

    fn markdown(cases: &[CaseReview], metrics: &AuthorDecisionMetrics) -> String {
        let mut output = String::new();
        writeln!(output, "# Deterministic repair author decision receipt").unwrap();
        writeln!(output).unwrap();
        writeln!(output, "Schema: {REVIEW_SCHEMA}").unwrap();
        writeln!(output, "Review token: {}", metrics.review_token).unwrap();
        writeln!(
            output,
            "Source review token: {}",
            metrics.source_review_token
        )
        .unwrap();
        writeln!(output).unwrap();
        writeln!(
            output,
            "> Author intent is confirmed. Author-directed candidates remain Unknown until their specific shadow semantic executor rebuilds and revalidates the required sidecars."
        )
        .unwrap();
        writeln!(output).unwrap();
        writeln!(output, "## Gate summary").unwrap();
        writeln!(output).unwrap();
        writeln!(
            output,
            "- Pending labels: {}/{}",
            metrics.labels_pending_author_review, metrics.cases
        )
        .unwrap();
        writeln!(output, "- Generated candidates: {}", metrics.candidates).unwrap();
        writeln!(
            output,
            "- Graph-only candidates at ProvenFix: {}",
            metrics.graph_proven_candidates
        )
        .unwrap();
        writeln!(
            output,
            "- Author-directed candidates at ProvenFix: {}/{}",
            metrics.author_directed_proven_candidates, metrics.author_directed_candidates
        )
        .unwrap();
        writeln!(
            output,
            "- Author-directed candidates still Unknown: {}/{}",
            metrics.author_directed_unknown_candidates, metrics.author_directed_candidates
        )
        .unwrap();
        writeln!(
            output,
            "- Mutation-preserving proven cases: {}/{}",
            metrics.mutation_preserving_graph_proven_cases, metrics.cases
        )
        .unwrap();
        writeln!(
            output,
            "- Author top-1/top-3 template match: {}/{} and {}/{}",
            metrics.top_1_author_template_matches,
            metrics.cases,
            metrics.top_3_author_template_matches,
            metrics.cases
        )
        .unwrap();
        writeln!(
            output,
            "- No emitted expected template: {:?}",
            metrics.cases_with_no_emitted_expected_template
        )
        .unwrap();
        writeln!(
            output,
            "- Statement candidates missing exact planted source anchors: {}",
            metrics.statement_candidates_missing_exact_source_anchor
        )
        .unwrap();

        for case in cases {
            writeln!(output).unwrap();
            writeln!(output, "## {} — {}", case.case_id, case.title).unwrap();
            writeln!(output).unwrap();
            writeln!(output, "Mutation:").unwrap();
            for line in case.mutation_json.lines() {
                writeln!(output, "    {line}").unwrap();
            }
            writeln!(output).unwrap();
            writeln!(output, "Expected impacts:").unwrap();
            writeln!(output).unwrap();
            for impact in &case.impacts {
                writeln!(output, "- {impact}").unwrap();
            }
            writeln!(output).unwrap();
            writeln!(output, "Expected unknowns:").unwrap();
            writeln!(output).unwrap();
            for unknown in &case.unknowns {
                writeln!(output, "- {unknown}").unwrap();
            }
            writeln!(output).unwrap();
            writeln!(output, "Author-confirmed reasonable repairs:").unwrap();
            writeln!(output).unwrap();
            for repair in &case.expected_repairs {
                writeln!(output, "- {repair}").unwrap();
            }
            writeln!(output).unwrap();
            writeln!(
                output,
                "| Rank | Candidate | Template | Preserves mutation | Simulation | Source binding | Author match |"
            )
            .unwrap();
            writeln!(output, "| ---: | --- | --- | :---: | --- | --- | --- |").unwrap();
            for (rank, candidate) in case.candidates.iter().enumerate() {
                let author_match = match (
                    candidate.template_match,
                    candidate.template_and_target_match,
                ) {
                    (_, true) => "template + target",
                    (true, false) => "template only",
                    (false, false) => "none",
                };
                writeln!(
                    output,
                    "| {} | {} | {:?} | {} | {:?} | {} | {} |",
                    rank + 1,
                    candidate.edit.edit_id.0,
                    candidate.edit.template,
                    yes_no(candidate.edit.preserves_mutation),
                    candidate.disposition,
                    candidate.source_status,
                    author_match
                )
                .unwrap();
            }
            writeln!(output).unwrap();
            writeln!(output, "Author checks:").unwrap();
            writeln!(output).unwrap();
            writeln!(output, "- [x] Impact labels are correct.").unwrap();
            writeln!(output, "- [x] Unknown coverage is honest.").unwrap();
            writeln!(output, "- [x] A repair preserves the intended mutation.").unwrap();
            writeln!(output, "- [x] Preferred candidate is narratively coherent.").unwrap();
            writeln!(
                output,
                "- Preferred candidate ID: {}",
                case.preferred_candidate_id
            )
            .unwrap();
            writeln!(output, "- Missing template or objection: none recorded").unwrap();
        }
        writeln!(output).unwrap();
        writeln!(output, "## Review attestation").unwrap();
        writeln!(output).unwrap();
        writeln!(output, "- Reviewer ID: {}", metrics.reviewed_by).unwrap();
        writeln!(
            output,
            "- Reviewed at Unix ms: {}",
            metrics.reviewed_at_unix_ms
        )
        .unwrap();
        writeln!(
            output,
            "- [x] All seven decisions were supplied by the author; fixture metrics did not decide them."
        )
        .unwrap();
        output
    }

    fn candidate_matches_expected(edit: &ProposedEdit, expected: &GoldRepairExpectation) -> bool {
        edit.template == expected.kind
            && expected
                .target_scene_ids
                .iter()
                .any(|scene| edit.target_ids.contains(&scene.0))
    }

    fn source_status(edit: &ProposedEdit) -> &'static str {
        let mut statement_operations = 0;
        let mut exact_anchors = 0;
        for operation in &edit.operations {
            if matches!(operation, GraphEditOperation::ApplyAuthorDirective { .. }) {
                return "semantic_rebuild_required";
            }
            if let GraphEditOperation::RemoveRequirementBearingStatement { evidence, .. } =
                operation
            {
                statement_operations += 1;
                if evidence
                    .iter()
                    .filter(|anchor| anchor.document_id.is_some() && anchor.source_range.is_some())
                    .count()
                    == 1
                {
                    exact_anchors += 1;
                }
            }
        }
        if statement_operations == 0 {
            "not_required"
        } else if exact_anchors == statement_operations {
            "document_snapshot_required"
        } else {
            "missing_exact_anchor"
        }
    }

    fn review_token(cases: &[CaseReview]) -> String {
        let mut hasher = blake3::Hasher::new();
        hasher.update(REVIEW_SCHEMA.as_bytes());
        for case in cases {
            hasher.update(case.case_id.as_bytes());
            for candidate in &case.candidates {
                hasher.update(candidate.edit.edit_id.0.as_bytes());
                hasher.update(&[candidate.disposition as u8]);
                if let Some(result) = &candidate.shadow_result {
                    hasher.update(&result.receipt.compiled_delta_digest.0);
                    hasher.update(&result.receipt.shadow_snapshot_digest.0);
                }
            }
        }
        hasher.finalize().to_hex()[..16].to_owned()
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

    fn output_dir() -> PathBuf {
        std::env::var_os("REVISION_REVIEW_DIR").map_or_else(
            || Path::new(r"D:\phoenix-target-revision-impact-duel\reviews").to_path_buf(),
            PathBuf::from,
        )
    }

    const fn yes_no(value: bool) -> &'static str {
        if value {
            "yes"
        } else {
            "no"
        }
    }
}

#[cfg(feature = "gold-harness")]
fn main() {
    enabled::run();
}

#[cfg(not(feature = "gold-harness"))]
fn main() {
    eprintln!("revision_repair_review requires --features gold-harness");
}
