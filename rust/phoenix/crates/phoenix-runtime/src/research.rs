use phoenix_research::{ClaimInput, GapInput, NativeWebClient, ResearchBudget, ResearchSession};
use phoenix_store_native_core::StoreError;
use phoenix_types::{ChatPlannerMessage, ChatPlannerToolSpec, ChatRun, ChatRunEvent};
use serde_json::{json, Value};

use crate::{now_ms, planner::persist_run_artifact, PhoenixRuntime};

const RESEARCH_STRATEGY: &str = "deep_research";
const MAX_TOOL_TEXT_CHARS: usize = 12_000;
const MAX_CONTEXT_BYTES: usize = 72 * 1024;

pub(crate) fn is_deep_research(run: &ChatRun) -> bool {
    run.options.strategy.as_deref() == Some(RESEARCH_STRATEGY)
}

pub(crate) fn ensure_session(
    runtime: &PhoenixRuntime,
    run: &ChatRun,
) -> Result<ResearchSession, StoreError> {
    if let Some(session) = load_session(runtime, &run.id)? {
        return Ok(session);
    }
    let now = now_ms();
    let session = ResearchSession::new(&run.id, &run.user_prompt, now, ResearchBudget::default());
    persist_session(runtime, run, &session)?;
    runtime.chat.persist_event(
        runtime.chat_store()?,
        &ChatRunEvent {
            id: format!("research-start:{}:{now}", run.id),
            run_id: run.id.clone(),
            sequence: 0,
            phase: "research_planning".to_owned(),
            kind: "research".to_owned(),
            label: "Deep research run created".to_owned(),
            detail: Some(
                "Rust research policy, budgets, ledgers, and verification are active.".to_owned(),
            ),
            status: Some("running".to_owned()),
            payload: Some(json!({ "schemaVersion": session.schema_version }).to_string()),
            latency_ms: None,
            created_at: now,
        },
    )?;
    Ok(session)
}

pub(crate) fn cancel_session(runtime: &PhoenixRuntime, run_id: &str) -> Result<(), StoreError> {
    let Some(run) = runtime.chat.get_run(runtime.chat_store()?, run_id)? else {
        return Ok(());
    };
    if !is_deep_research(&run) {
        return Ok(());
    }
    let mut session = ensure_session(runtime, &run)?;
    session.cancel(now_ms());
    persist_session(runtime, &run, &session)
}

pub(crate) fn finalize_note_decision(
    runtime: &PhoenixRuntime,
    run_id: &str,
    approved: bool,
) -> Result<(), StoreError> {
    let Some(run) = runtime.chat.get_run(runtime.chat_store()?, run_id)? else {
        return Ok(());
    };
    if !is_deep_research(&run) {
        return Ok(());
    }
    let mut session = ensure_session(runtime, &run)?;
    if approved {
        session.mark_completed(now_ms()).map_err(research_error)?;
    } else {
        session.cancel(now_ms());
    }
    persist_session(runtime, &run, &session)
}

pub(crate) fn tool_specs() -> Vec<ChatPlannerToolSpec> {
    vec![
        tool("research_plan", "Create the bounded research question plan before web access.", json!({
            "type":"object","properties":{"questions":{"type":"array","minItems":1,"maxItems":12,"items":{"type":"string","minLength":3}}},"required":["questions"],"additionalProperties":false
        })),
        tool("research_web_search", "Search the public web through the native policy-bound provider. Results are durably ledgered.", json!({
            "type":"object","properties":{"query":{"type":"string","minLength":3},"rationale":{"type":"string"},"maxResults":{"type":"integer","minimum":1,"maximum":10}},"required":["query"],"additionalProperties":false
        })),
        tool("research_web_fetch", "Fetch one public http(s) source through native SSRF, redirect, time, type, and byte policies. Use rendered mode for JavaScript pages; auto preserves the direct fast path and escalates recognized app shells.", json!({
            "type":"object","properties":{"url":{"type":"string","minLength":8},"mode":{"type":"string","enum":["auto","direct","rendered"]}},"required":["url"],"additionalProperties":false
        })),
        tool("research_record_claims", "Record atomic factual claims with source URL, locator, and exact supporting quote before synthesis.", json!({
            "type":"object","properties":{"claims":{"type":"array","minItems":1,"maxItems":24,"items":{"type":"object","properties":{"text":{"type":"string","minLength":8},"confidenceBps":{"type":"integer","minimum":0,"maximum":10000},"citations":{"type":"array","items":{"type":"object","properties":{"url":{"type":"string"},"locator":{"type":"string"},"quote":{"type":"string"}},"required":["url"]}}},"required":["text","citations"]}}},"required":["claims"],"additionalProperties":false
        })),
        tool("research_assess_gaps", "Close or continue the bounded gap loop. Repeated no-progress cycles stop automatically.", json!({
            "type":"object","properties":{"continueResearch":{"type":"boolean"},"gaps":{"type":"array","maxItems":12,"items":{"type":"object","properties":{"description":{"type":"string","minLength":5},"priority":{"type":"integer","minimum":0,"maximum":9},"suggestedQueries":{"type":"array","items":{"type":"string"}}},"required":["description"]}}},"required":["continueResearch","gaps"],"additionalProperties":false
        })),
        tool("research_submit_synthesis", "Stage the complete Markdown research report for deterministic verification. Do not propose a note edit yet.", json!({
            "type":"object","properties":{"markdown":{"type":"string","minLength":80}},"required":["markdown"],"additionalProperties":false
        })),
        tool("research_verify", "Verify claim coverage, captured links, exact quotes, and deterministic source support. A passed receipt unlocks the note proposal.", json!({
            "type":"object","properties":{},"additionalProperties":false
        })),
    ]
}

pub(crate) fn execute_tool(
    runtime: &PhoenixRuntime,
    run: &ChatRun,
    name: &str,
    args: &Value,
) -> Result<Value, StoreError> {
    let mut session = ensure_session(runtime, run)?;
    let started = std::time::Instant::now();
    let now = now_ms();
    let result = match name {
        "research_plan" => {
            let questions =
                serde_json::from_value(args.get("questions").cloned().unwrap_or(Value::Null))
                    .map_err(query_error)?;
            session.plan(questions, now).map_err(research_error)?;
            json!({ "phase": session.phase, "questions": session.questions, "budget": session.budget })
        }
        "research_web_search" => {
            let query = required_str(args, "query")?;
            let rationale = args
                .get("rationale")
                .and_then(Value::as_str)
                .unwrap_or_default();
            let max_results = args
                .get("maxResults")
                .and_then(Value::as_u64)
                .unwrap_or(6)
                .clamp(1, 10) as usize;
            let query_id = session
                .begin_search(query, rationale, now)
                .map_err(research_error)?;
            persist_session(runtime, run, &session)?;
            let client = NativeWebClient::from_env(session.budget.max_source_bytes)
                .map_err(research_error)?;
            let results = match client.search(query, max_results) {
                Ok(results) => results,
                Err(error) => {
                    if let Some(record) =
                        session.queries.iter_mut().find(|item| item.id == query_id)
                    {
                        record.status = "failed".to_owned();
                    }
                    persist_session(runtime, run, &session)?;
                    return Err(research_error(error));
                }
            };
            let response_hits = results.hits.clone();
            let provider = results.provider.clone();
            let search_elapsed_ms = results.elapsed_ms;
            let added = session
                .finish_search(&query_id, results, now_ms())
                .map_err(research_error)?;
            json!({ "queryId": query_id, "provider": provider, "addedSources": added, "hits": response_hits, "phase": session.phase, "elapsedMs": search_elapsed_ms })
        }
        "research_web_fetch" => {
            let url = required_str(args, "url")?;
            let mode = phoenix_research::WebFetchMode::parse(
                args.get("mode").and_then(Value::as_str).unwrap_or("auto"),
            )
            .map_err(research_error)?;
            session.begin_fetch(now).map_err(research_error)?;
            persist_session(runtime, run, &session)?;
            let client = NativeWebClient::from_env(session.budget.max_source_bytes)
                .map_err(research_error)?;
            let fetched = phoenix_research::WebFetcher::fetch_mode(&client, url, mode)
                .map_err(research_error)?;
            let preview = fetched
                .content
                .chars()
                .take(MAX_TOOL_TEXT_CHARS)
                .collect::<String>();
            let elapsed_ms = fetched.elapsed_ms;
            let fetch_receipt = fetched.receipt.clone();
            let source_id = session
                .finish_fetch(fetched, now_ms())
                .map_err(research_error)?;
            json!({ "sourceId": source_id, "url": url, "content": preview, "truncated": session.sources.iter().find(|source| source.id == source_id).is_some_and(|source| source.content.chars().count() > MAX_TOOL_TEXT_CHARS), "elapsedMs": elapsed_ms, "fetchReceipt": fetch_receipt })
        }
        "research_record_claims" => {
            let claims: Vec<ClaimInput> =
                serde_json::from_value(args.get("claims").cloned().unwrap_or(Value::Null))
                    .map_err(query_error)?;
            let added = session.record_claims(claims, now).map_err(research_error)?;
            json!({ "addedClaims": added, "claimCount": session.claims.len(), "citationCount": session.citations.len(), "phase": session.phase })
        }
        "research_assess_gaps" => {
            let gaps: Vec<GapInput> =
                serde_json::from_value(args.get("gaps").cloned().unwrap_or_else(|| json!([])))
                    .map_err(query_error)?;
            let continue_research = args
                .get("continueResearch")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            session
                .assess_gaps(gaps, continue_research, now)
                .map_err(research_error)?;
            json!({ "phase": session.phase, "gapCycle": session.usage.gap_cycles, "stopReason": session.stop_reason, "openGaps": session.gaps.iter().filter(|gap| gap.status == "open").collect::<Vec<_>>() })
        }
        "research_submit_synthesis" => {
            let markdown = required_str(args, "markdown")?.to_owned();
            session
                .submit_synthesis(markdown, now)
                .map_err(research_error)?;
            json!({ "phase": session.phase, "draftChars": session.draft_markdown.as_deref().map_or(0, str::len) })
        }
        "research_verify" => {
            let report = session.verify(now).map_err(research_error)?.clone();
            json!({ "phase": session.phase, "report": report, "noteProposalUnlocked": session.allow_note_proposal(), "receipt": session.receipt(now_ms()) })
        }
        _ => {
            return Err(StoreError::Query(format!(
                "unsupported research tool: {name}"
            )))
        }
    };
    persist_session(runtime, run, &session)?;
    runtime.chat.persist_event(
        runtime.chat_store()?,
        &ChatRunEvent {
            id: format!("research-tool:{}:{}:{}", run.id, name, now_ms()),
            run_id: run.id.clone(),
            sequence: 0,
            phase: format!("research_{:?}", session.phase).to_lowercase(),
            kind: "research".to_owned(),
            label: research_label(name).to_owned(),
            detail: Some(research_detail(&session)),
            status: Some("done".to_owned()),
            payload: Some(json!({ "phase": session.phase, "usage": session.usage }).to_string()),
            latency_ms: Some(started.elapsed().as_millis().min(i64::MAX as u128) as i64),
            created_at: now_ms(),
        },
    )?;
    Ok(result)
}

pub(crate) fn note_proposal_allowed(
    runtime: &PhoenixRuntime,
    run: &ChatRun,
) -> Result<bool, StoreError> {
    Ok(load_session(runtime, &run.id)?.is_some_and(|session| session.allow_note_proposal()))
}

pub(crate) fn compact_messages(
    runtime: &PhoenixRuntime,
    run: &ChatRun,
    messages: &mut Vec<ChatPlannerMessage>,
) -> Result<bool, StoreError> {
    let bytes = serde_json::to_vec(messages).map_err(query_error)?.len();
    if bytes <= MAX_CONTEXT_BYTES || messages.len() <= 8 {
        return Ok(false);
    }
    let session = ensure_session(runtime, run)?;
    let keep_head = 2usize;
    let keep_tail = 6usize.min(messages.len().saturating_sub(keep_head));
    let tail_start = messages.len() - keep_tail;
    let displaced = messages[keep_head..tail_start].to_vec();
    let artifact = persist_run_artifact(
        runtime,
        run,
        None,
        "research_context_history/v1",
        json!({ "messages": displaced, "beforeBytes": bytes }),
        false,
    )?;
    let summary = json!({
        "researchRunId": session.id, "phase": session.phase, "questions": session.questions,
        "queryCount": session.queries.len(), "sourceCount": session.sources.len(), "claimCount": session.claims.len(),
        "gapCycles": session.usage.gap_cycles, "verification": session.verification,
    });
    let summary_artifact = persist_run_artifact(
        runtime,
        run,
        None,
        "research_context_summary/v1",
        summary.clone(),
        true,
    )?;
    let mut compacted = messages[..keep_head].to_vec();
    compacted.push(ChatPlannerMessage {
        role: "system".to_owned(),
        content: format!("Rust research context compacted. Displaced messages: artifact://{}. Ledger summary: artifact://{}. Summary: {}", artifact.key, summary_artifact.key, summary),
        name: Some("research_context_compaction".to_owned()), tool_call_id: None, tool_calls: Vec::new(),
    });
    compacted.extend_from_slice(&messages[tail_start..]);
    *messages = compacted;
    Ok(true)
}

fn load_session(
    runtime: &PhoenixRuntime,
    chat_run_id: &str,
) -> Result<Option<ResearchSession>, StoreError> {
    runtime
        .fetch_relation_rows("research_runs")?
        .into_iter()
        .find(|row| row.get("chat_run_id").and_then(Value::as_str) == Some(chat_run_id))
        .map(|row| {
            serde_json::from_value(row.get("state_json").cloned().unwrap_or(Value::Null))
                .map_err(query_error)
        })
        .transpose()
}

fn persist_session(
    runtime: &PhoenixRuntime,
    run: &ChatRun,
    session: &ResearchSession,
) -> Result<(), StoreError> {
    runtime.put_relation_row("research_runs", json!({
        "id": session.id, "chat_run_id": session.chat_run_id, "topic": session.topic,
        "phase": serde_json::to_value(session.phase).map_err(query_error)?, "state_json": session,
        "cancel_requested": session.cancel_requested, "created_at": session.started_at, "updated_at": session.updated_at,
    }))?;
    for query in &session.queries {
        runtime.put_relation_row("research_queries", json!({
            "id": query.id, "run_id": session.id, "ordinal": query.ordinal, "query": query.query,
            "rationale": query.rationale, "status": query.status, "result_count": query.result_count, "created_at": query.created_at,
            "provider": query.provider, "search_elapsed_ms": query.search_elapsed_ms,
        }))?;
    }
    for source in &session.sources {
        let artifact_key = if source.fetched {
            persist_run_artifact(runtime, run, Some(&format!("research-source:{}", source.id)), "research_source/v1", json!({
                "sourceId": source.id, "url": source.url, "title": source.title, "contentHash": source.content_hash,
                "contentType": source.content_type, "content": source.content,
                "fetchBackend": source.fetch_backend, "requestedFetchMode": source.requested_fetch_mode,
                "resolvedFetchMode": source.resolved_fetch_mode, "extraction": source.extraction,
                "rendered": source.rendered, "fetchElapsedMs": source.fetch_elapsed_ms,
            }), false)?.key
        } else {
            String::new()
        };
        runtime.put_relation_row("research_sources", json!({
            "id": source.id, "run_id": session.id, "url": source.url, "canonical_url": source.canonical_url,
            "title": source.title, "excerpt": source.excerpt, "content_hash": source.content_hash,
            "artifact_key": artifact_key, "fetched": source.fetched, "fetch_status": source.fetch_status,
            "content_type": source.content_type, "discovered_by_json": source.discovered_by,
            "fetch_backend": source.fetch_backend, "requested_fetch_mode": source.requested_fetch_mode,
            "resolved_fetch_mode": source.resolved_fetch_mode, "extraction": source.extraction,
            "rendered": source.rendered, "fetch_elapsed_ms": source.fetch_elapsed_ms,
            "created_at": source.created_at, "updated_at": source.updated_at,
        }))?;
    }
    for claim in &session.claims {
        runtime.put_relation_row("research_claims", json!({
            "id": claim.id, "run_id": session.id, "text": claim.text, "confidence_bps": claim.confidence_bps,
            "citation_ids_json": claim.citation_ids, "verified": claim.verified, "created_at": claim.created_at,
        }))?;
    }
    for citation in &session.citations {
        runtime.put_relation_row("research_citations", json!({
            "id": citation.id, "run_id": session.id, "claim_id": citation.claim_id, "source_id": citation.source_id,
            "url": citation.url, "locator": citation.locator, "quote_hash": citation.quote_hash,
            "structural_valid": citation.structural_valid, "link_valid": citation.link_valid, "support_bps": citation.support_bps,
        }))?;
    }
    for gap in &session.gaps {
        runtime.put_relation_row("research_gaps", json!({
            "id": gap.id, "run_id": session.id, "description": gap.description, "priority": gap.priority,
            "suggested_queries_json": gap.suggested_queries, "status": gap.status, "cycle": gap.cycle, "created_at": gap.created_at,
        }))?;
    }
    if let Some(markdown) = session.draft_markdown.as_deref() {
        persist_run_artifact(
            runtime,
            run,
            Some(&format!("research-synthesis:{}", session.id)),
            "research_synthesis/v1",
            json!({ "markdown": markdown, "verification": session.verification }),
            true,
        )?;
    }
    if session.verification.is_some() {
        let receipt = session.receipt(now_ms());
        persist_run_artifact(
            runtime,
            run,
            Some(&format!(
                "research-receipt:{}:{}",
                session.id, session.usage.synthesis_revisions
            )),
            "research_receipt/v1",
            serde_json::to_value(&receipt).map_err(query_error)?,
            true,
        )?;
        runtime.put_relation_row("research_receipts", json!({
            "id": format!("receipt:{}:{}", session.id, session.usage.synthesis_revisions), "run_id": session.id,
            "status": if receipt.coverage_bps >= session.budget.minimum_coverage_bps { "verified" } else { "rejected" },
            "receipt_json": receipt, "note_uri": run.options.canvas_target.as_ref().map(|target| target.note_uri.clone()), "created_at": now_ms(),
        }))?;
    }
    Ok(())
}

fn tool(name: &str, description: &str, parameters_json: Value) -> ChatPlannerToolSpec {
    ChatPlannerToolSpec {
        name: name.to_owned(),
        description: description.to_owned(),
        parameters_json,
    }
}

fn required_str<'a>(args: &'a Value, key: &str) -> Result<&'a str, StoreError> {
    args.get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| StoreError::Query(format!("research tool requires {key}")))
}

fn research_label(name: &str) -> &'static str {
    match name {
        "research_plan" => "Research plan accepted",
        "research_web_search" => "Web search ledgered",
        "research_web_fetch" => "Source captured",
        "research_record_claims" => "Claims ledgered",
        "research_assess_gaps" => "Research gaps assessed",
        "research_submit_synthesis" => "Note synthesis staged",
        "research_verify" => "Citations verified",
        _ => "Research step completed",
    }
}

fn research_detail(session: &ResearchSession) -> String {
    format!(
        "phase={:?} searches={} fetches={} sources={} claims={} gaps={}",
        session.phase,
        session.usage.searches,
        session.usage.fetches,
        session.sources.len(),
        session.claims.len(),
        session.gaps.len()
    )
}

fn query_error(error: impl std::fmt::Display) -> StoreError {
    StoreError::Query(error.to_string())
}
fn research_error(error: impl std::fmt::Display) -> StoreError {
    StoreError::Query(format!("research policy: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use phoenix_types::{ChatRun, ChatRunStatus, RunOptions, RuntimeConfig};

    fn runtime() -> PhoenixRuntime {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "phoenix-research-test-{}-{unique}",
            std::process::id()
        ));
        std::fs::create_dir_all(&root).expect("test root");
        let runtime = PhoenixRuntime::open(RuntimeConfig::default(), Some(root)).expect("runtime");
        runtime.init().expect("init");
        runtime
    }

    fn research_run() -> ChatRun {
        ChatRun {
            id: "chat-research-1".to_owned(),
            user_prompt: "Research durable Rust AI harnesses".to_owned(),
            status: ChatRunStatus::Planning,
            options: RunOptions {
                strategy: Some("deep_research".to_owned()),
                mutations_enabled: true,
                ..RunOptions::default()
            },
            ..ChatRun::default()
        }
    }

    #[test]
    fn deep_research_exposes_only_typed_research_tools() {
        let specs = tool_specs();
        assert_eq!(specs.len(), 7);
        assert!(specs.iter().all(|spec| spec.name.starts_with("research_")));
        assert!(!specs
            .iter()
            .any(|spec| spec.name.contains("graph_write") || spec.name.contains("shell")));
    }

    #[test]
    fn strategy_is_an_explicit_run_contract() {
        let run = ChatRun {
            options: RunOptions {
                strategy: Some("deep_research".to_owned()),
                ..RunOptions::default()
            },
            ..ChatRun::default()
        };
        assert!(is_deep_research(&run));
        let ordinary = ChatRun {
            options: RunOptions {
                strategy: Some("agent".to_owned()),
                ..RunOptions::default()
            },
            ..ChatRun::default()
        };
        assert!(!is_deep_research(&ordinary));
    }

    #[test]
    fn plan_is_durable_and_does_not_write_asserted_graph_relations() {
        let runtime = runtime();
        let run = research_run();
        let graph_before = runtime
            .fetch_relation_rows("graph_vertices")
            .expect("graph before");

        let value = execute_tool(
            &runtime,
            &run,
            "research_plan",
            &json!({ "questions": ["Which contracts make agent runs durable?"] }),
        )
        .expect("plan");

        assert_eq!(
            value.get("phase").and_then(Value::as_str),
            Some("searching")
        );
        let restored = load_session(&runtime, &run.id)
            .expect("load")
            .expect("session");
        assert_eq!(restored.phase, phoenix_research::ResearchPhase::Searching);
        assert_eq!(
            runtime
                .fetch_relation_rows("research_runs")
                .expect("runs")
                .len(),
            1
        );
        assert_eq!(
            runtime
                .fetch_relation_rows("graph_vertices")
                .expect("graph after"),
            graph_before
        );
    }
}
