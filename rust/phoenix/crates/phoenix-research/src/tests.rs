use crate::{
    web::validate_url_for_test, CitationInput, ClaimInput, GapInput, ResearchBudget, ResearchPhase,
    ResearchSession, WebFetch, WebSearchHit, WebSearchResults,
};

fn session() -> ResearchSession {
    ResearchSession::new(
        "chat-run-1",
        "Rust AI harnesses",
        1_000,
        ResearchBudget::default(),
    )
}

#[test]
fn enforces_plan_search_gap_synthesis_verification_note_gate() {
    let mut run = session();
    run.plan(
        vec!["What makes a durable agent harness?".to_owned()],
        1_001,
    )
    .unwrap();
    let query_id = run
        .begin_search(
            "durable AI agent harness receipts",
            "find primary architecture sources",
            1_002,
        )
        .unwrap();
    run.finish_search(
        &query_id,
        WebSearchResults {
            provider: "mock".to_owned(),
            query: "durable AI agent harness receipts".to_owned(),
            elapsed_ms: 4,
            hits: vec![WebSearchHit {
                url: "https://example.com/harness".to_owned(),
                title: "Harness".to_owned(),
                excerpt: "Durable harnesses persist ordered events and receipts.".to_owned(),
            }],
        },
        1_003,
    )
    .unwrap();
    run.begin_fetch(1_004).unwrap();
    run.finish_fetch(
        WebFetch {
            requested_url: "https://example.com/harness".to_owned(),
            final_url: "https://example.com/harness".to_owned(),
            status: 200,
            title: "Harness".to_owned(),
            content_type: "text/html".to_owned(),
            content: "Durable harnesses persist ordered events and receipts for recovery."
                .to_owned(),
            bytes: 67,
            elapsed_ms: 5,
        },
        1_005,
    )
    .unwrap();
    run.record_claims(
        vec![ClaimInput {
            text: "Durable harnesses persist ordered events and receipts for recovery.".to_owned(),
            confidence_bps: 9_000,
            citations: vec![CitationInput {
                url: "https://example.com/harness".to_owned(),
                locator: "main".to_owned(),
                quote: "Durable harnesses persist ordered events and receipts for recovery."
                    .to_owned(),
            }],
        }],
        1_006,
    )
    .unwrap();
    run.assess_gaps(Vec::<GapInput>::new(), false, 1_007)
        .unwrap();
    assert_eq!(run.phase, ResearchPhase::Synthesizing);
    run.submit_synthesis("# Durable harnesses\n\nDurable harnesses persist ordered events and receipts for recovery. [Source](https://example.com/harness)\n\n## Conclusion\n\nThe note remains the approval-gated output interface.".to_owned(), 1_008).unwrap();
    assert!(!run.allow_note_proposal());
    let report = run.verify(1_009).unwrap().clone();
    assert!(report.passed, "{:#?}", report.issues);
    assert!(run.allow_note_proposal());
    assert_eq!(run.phase, ResearchPhase::AwaitingNoteProposal);
}

#[test]
fn verification_rejects_uncaptured_sources() {
    let mut run = session();
    run.plan(vec!["What evidence exists?".to_owned()], 1_001)
        .unwrap();
    run.record_claims(
        vec![ClaimInput {
            text: "An unsupported factual claim belongs in no note.".to_owned(),
            confidence_bps: 8_000,
            citations: vec![CitationInput {
                url: "https://missing.example/source".to_owned(),
                locator: String::new(),
                quote: String::new(),
            }],
        }],
        1_002,
    )
    .unwrap();
    run.assess_gaps(Vec::new(), false, 1_003).unwrap();
    run.submit_synthesis("# Report\n\nAn unsupported factual claim belongs in no note.\n\nThis deliberately long draft exists to exercise the deterministic citation verification rejection path.".to_owned(), 1_004).unwrap();
    let report = run.verify(1_005).unwrap();
    assert!(!report.passed);
    assert!(report
        .issues
        .iter()
        .any(|issue| issue.code == "citation_source_missing"));
    assert!(!run.allow_note_proposal());
}

#[test]
fn rejects_private_and_credentialed_web_targets() {
    assert!(validate_url_for_test("http://127.0.0.1/admin").is_err());
    assert!(validate_url_for_test("http://169.254.169.254/latest/meta-data").is_err());
    assert!(validate_url_for_test("https://user:secret@example.com/").is_err());
    assert!(validate_url_for_test("file:///etc/passwd").is_err());
    assert!(validate_url_for_test("https://example.com/research").is_ok());
}

#[test]
fn recovery_round_trip_preserves_budget_and_gate_state() {
    let mut run = session();
    run.plan(vec!["How does recovery work?".to_owned()], 1_001)
        .unwrap();
    let restored: ResearchSession =
        serde_json::from_str(&serde_json::to_string(&run).unwrap()).unwrap();
    assert_eq!(restored.phase, ResearchPhase::Searching);
    assert_eq!(restored.questions, vec!["How does recovery work?"]);
    assert_eq!(restored.budget, ResearchBudget::default());
    assert!(!restored.allow_note_proposal());
}

#[test]
fn repeated_gap_cycles_stop_on_stagnation() {
    let mut run = session();
    run.plan(vec!["Where are the gaps?".to_owned()], 1_001)
        .unwrap();
    let gap = || {
        vec![GapInput {
            description: "Need another primary source".to_owned(),
            priority: 8,
            suggested_queries: vec!["primary source".to_owned()],
        }]
    };
    run.assess_gaps(gap(), true, 1_002).unwrap();
    run.assess_gaps(gap(), true, 1_003).unwrap();
    run.assess_gaps(gap(), true, 1_004).unwrap();
    assert_eq!(run.phase, ResearchPhase::Synthesizing);
    assert_eq!(
        run.stop_reason.as_deref(),
        Some("research progress stalled")
    );
}

#[test]
fn shortrun_b_ledger_and_verifier_emit_a_bounded_timing_receipt() {
    let started = std::time::Instant::now();
    let mut run = ResearchSession::new(
        "shortrun-b",
        "Shortrun B research harness",
        10_000,
        ResearchBudget::default(),
    );
    run.plan(
        vec!["How does a durable research harness protect note truth?".to_owned()],
        10_001,
    )
    .unwrap();
    let query = run
        .begin_search(
            "durable research harness note transactions",
            "Shortrun B performance fixture",
            10_002,
        )
        .unwrap();
    run.finish_search(
        &query,
        WebSearchResults {
            provider: "fixture".to_owned(),
            query: "durable research harness note transactions".to_owned(),
            elapsed_ms: 1,
            hits: vec![WebSearchHit {
                url: "https://example.com/shortrun-b".to_owned(),
                title: "Shortrun B".to_owned(),
                excerpt: "Approval-gated commits preserve note truth.".to_owned(),
            }],
        },
        10_003,
    )
    .unwrap();
    run.begin_fetch(10_004).unwrap();
    run.finish_fetch(
        WebFetch {
            requested_url: "https://example.com/shortrun-b".to_owned(),
            final_url: "https://example.com/shortrun-b".to_owned(),
            status: 200,
            title: "Shortrun B".to_owned(),
            content_type: "text/plain".to_owned(),
            content: "Approval-gated commits preserve note truth with durable receipts and exact revisions. ".repeat(128),
            bytes: 10_000,
            elapsed_ms: 1,
        },
        10_005,
    )
    .unwrap();
    for index in 0..64 {
        run.record_claims(
            vec![ClaimInput {
                text: format!("Approval-gated commits preserve note truth with durable receipts and exact revisions number {index}."),
                confidence_bps: 9_000,
                citations: vec![CitationInput {
                    url: "https://example.com/shortrun-b".to_owned(),
                    locator: format!("fixture-{index}"),
                    quote: "Approval-gated commits preserve note truth with durable receipts and exact revisions.".to_owned(),
                }],
            }],
            10_006 + index,
        )
        .unwrap();
    }
    run.assess_gaps(Vec::new(), false, 10_100).unwrap();
    run.submit_synthesis("# Shortrun B\n\nApproval-gated commits preserve note truth with durable receipts and exact revisions. [Source](https://example.com/shortrun-b)\n\n## Receipt\n\nThis deterministic performance fixture exercises sixty-four claim and citation ledger entries.".to_owned(), 10_101).unwrap();
    let report = run.verify(10_102).unwrap();
    assert!(report.passed);
    let elapsed = started.elapsed();
    assert!(
        elapsed.as_millis() < 250,
        "Shortrun B research ledger took {elapsed:?}"
    );
    eprintln!(
        "{}",
        serde_json::json!({
            "note": "Shortrun B",
            "claims": 64,
            "coverageBps": report.coverage_bps,
            "localEngineMs": elapsed.as_secs_f64() * 1000.0
        })
    );
}
