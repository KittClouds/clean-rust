use std::cmp::Reverse;

use hashbrown::{HashMap, HashSet};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{
    verify_session, CitationRecord, ClaimInput, ClaimRecord, GapInput, GapRecord, QueryRecord,
    ResearchBudget, ResearchPhase, ResearchReceipt, ResearchUsage, SourceRecord,
    VerificationReport, WebFetch, WebSearchResults,
};

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ResearchError {
    #[error("research run is cancelled")]
    Cancelled,
    #[error("research budget exceeded: {0}")]
    Budget(&'static str),
    #[error("invalid research phase: expected {expected}, found {actual:?}")]
    Phase {
        expected: &'static str,
        actual: ResearchPhase,
    },
    #[error("invalid research input: {0}")]
    Invalid(String),
    #[error("research verification failed")]
    VerificationFailed,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResearchSession {
    pub schema_version: String,
    pub id: String,
    pub chat_run_id: String,
    pub topic: String,
    pub phase: ResearchPhase,
    pub budget: ResearchBudget,
    pub usage: ResearchUsage,
    pub questions: Vec<String>,
    pub queries: Vec<QueryRecord>,
    pub sources: Vec<SourceRecord>,
    pub claims: Vec<ClaimRecord>,
    pub citations: Vec<CitationRecord>,
    pub gaps: Vec<GapRecord>,
    pub draft_markdown: Option<String>,
    pub verification: Option<VerificationReport>,
    pub stop_reason: Option<String>,
    pub cancel_requested: bool,
    pub started_at: i64,
    pub updated_at: i64,
    last_progress_signature: String,
    stagnant_cycles: u8,
}

impl ResearchSession {
    pub fn new(chat_run_id: &str, topic: &str, now: i64, budget: ResearchBudget) -> Self {
        Self {
            schema_version: "phoenix-research-run/v1".to_owned(),
            id: stable_id("research", chat_run_id),
            chat_run_id: chat_run_id.to_owned(),
            topic: topic.trim().to_owned(),
            phase: ResearchPhase::Planning,
            budget,
            usage: ResearchUsage::default(),
            questions: Vec::new(),
            queries: Vec::new(),
            sources: Vec::new(),
            claims: Vec::new(),
            citations: Vec::new(),
            gaps: Vec::new(),
            draft_markdown: None,
            verification: None,
            stop_reason: None,
            cancel_requested: false,
            started_at: now,
            updated_at: now,
            last_progress_signature: String::new(),
            stagnant_cycles: 0,
        }
    }

    pub fn plan(&mut self, questions: Vec<String>, now: i64) -> Result<(), ResearchError> {
        self.guard(now)?;
        self.require_phase(&[ResearchPhase::Planning], "planning")?;
        let mut seen = HashSet::new();
        self.questions = questions
            .into_iter()
            .map(|value| value.trim().to_owned())
            .filter(|value| value.len() >= 3 && seen.insert(value.to_lowercase()))
            .take(12)
            .collect();
        if self.questions.is_empty() {
            return Err(ResearchError::Invalid(
                "plan requires at least one concrete research question".to_owned(),
            ));
        }
        self.phase = ResearchPhase::Searching;
        self.touch(now);
        Ok(())
    }

    pub fn begin_search(
        &mut self,
        query: &str,
        rationale: &str,
        now: i64,
    ) -> Result<String, ResearchError> {
        self.guard(now)?;
        self.require_phase(
            &[ResearchPhase::Searching, ResearchPhase::GapAnalysis],
            "searching or gap_analysis",
        )?;
        if self.usage.searches >= self.budget.max_searches {
            return Err(ResearchError::Budget("search count"));
        }
        let query = query.trim();
        if query.len() < 3 || query.len() > 512 {
            return Err(ResearchError::Invalid(
                "search query must be between 3 and 512 bytes".to_owned(),
            ));
        }
        let normalized = normalize_space(query).to_lowercase();
        if self
            .queries
            .iter()
            .any(|item| normalize_space(&item.query).to_lowercase() == normalized)
        {
            return Err(ResearchError::Invalid("duplicate search query".to_owned()));
        }
        self.usage.searches += 1;
        let id = stable_id("query", &format!("{}:{normalized}", self.id));
        self.queries.push(QueryRecord {
            id: id.clone(),
            ordinal: self.usage.searches,
            query: query.to_owned(),
            rationale: rationale.trim().to_owned(),
            status: "running".to_owned(),
            result_count: 0,
            provider: String::new(),
            search_elapsed_ms: 0,
            created_at: now,
        });
        self.phase = ResearchPhase::Searching;
        self.touch(now);
        Ok(id)
    }

    pub fn finish_search(
        &mut self,
        query_id: &str,
        results: WebSearchResults,
        now: i64,
    ) -> Result<usize, ResearchError> {
        self.guard(now)?;
        let query = self
            .queries
            .iter_mut()
            .find(|item| item.id == query_id)
            .ok_or_else(|| ResearchError::Invalid(format!("unknown query id: {query_id}")))?;
        query.status = "completed".to_owned();
        query.result_count = results.hits.len();
        query.provider = results.provider.clone();
        query.search_elapsed_ms = results.elapsed_ms;
        let mut added = 0usize;
        for hit in results.hits {
            if self.sources.len() >= self.budget.max_sources as usize {
                break;
            }
            let canonical = canonical_url(&hit.url);
            if let Some(existing) = self
                .sources
                .iter_mut()
                .find(|source| source.canonical_url == canonical)
            {
                if !existing.discovered_by.iter().any(|id| id == query_id) {
                    existing.discovered_by.push(query_id.to_owned());
                }
                if existing.excerpt.is_empty() {
                    existing.excerpt = hit.excerpt;
                }
                existing.updated_at = now;
                continue;
            }
            self.sources.push(SourceRecord {
                id: stable_id("source", &canonical),
                url: hit.url,
                canonical_url: canonical,
                title: hit.title,
                excerpt: hit.excerpt,
                content: String::new(),
                content_hash: String::new(),
                fetched: false,
                fetch_status: 0,
                content_type: String::new(),
                fetch_backend: String::new(),
                requested_fetch_mode: String::new(),
                resolved_fetch_mode: String::new(),
                extraction: String::new(),
                rendered: false,
                fetch_elapsed_ms: 0,
                discovered_by: vec![query_id.to_owned()],
                created_at: now,
                updated_at: now,
            });
            added += 1;
        }
        self.touch(now);
        Ok(added)
    }

    pub fn begin_fetch(&mut self, now: i64) -> Result<(), ResearchError> {
        self.guard(now)?;
        self.require_phase(
            &[ResearchPhase::Searching, ResearchPhase::GapAnalysis],
            "searching or gap_analysis",
        )?;
        if self.usage.fetches >= self.budget.max_fetches {
            return Err(ResearchError::Budget("fetch count"));
        }
        self.usage.fetches += 1;
        self.touch(now);
        Ok(())
    }

    pub fn finish_fetch(&mut self, fetched: WebFetch, now: i64) -> Result<String, ResearchError> {
        self.guard(now)?;
        let receipt = fetched.receipt.clone();
        let fetch_elapsed_ms = fetched.elapsed_ms;
        let canonical = canonical_url(&fetched.final_url);
        let bytes = fetched.content.len();
        if bytes > self.budget.max_source_bytes {
            return Err(ResearchError::Budget("single source bytes"));
        }
        if self.usage.source_bytes.saturating_add(bytes) > self.budget.max_total_source_bytes {
            return Err(ResearchError::Budget("total source bytes"));
        }
        self.usage.source_bytes += bytes;
        let content_hash = blake3::hash(fetched.content.as_bytes())
            .to_hex()
            .to_string();
        let id = stable_id("source", &canonical);
        if let Some(existing) = self
            .sources
            .iter_mut()
            .find(|source| source.canonical_url == canonical || source.id == id)
        {
            existing.url = fetched.final_url;
            existing.title = if fetched.title.is_empty() {
                existing.title.clone()
            } else {
                fetched.title
            };
            existing.content = fetched.content;
            existing.content_hash = content_hash;
            existing.fetched = true;
            existing.fetch_status = fetched.status;
            existing.content_type = fetched.content_type;
            existing.fetch_backend = receipt.backend;
            existing.requested_fetch_mode = receipt.requested_mode.as_str().to_owned();
            existing.resolved_fetch_mode = receipt.resolved_mode.as_str().to_owned();
            existing.extraction = receipt.extraction;
            existing.rendered = receipt.rendered;
            existing.fetch_elapsed_ms = fetch_elapsed_ms;
            existing.updated_at = now;
        } else {
            if self.sources.len() >= self.budget.max_sources as usize {
                return Err(ResearchError::Budget("source count"));
            }
            self.sources.push(SourceRecord {
                id: id.clone(),
                url: fetched.final_url,
                canonical_url: canonical,
                title: fetched.title,
                excerpt: String::new(),
                content: fetched.content,
                content_hash,
                fetched: true,
                fetch_status: fetched.status,
                content_type: fetched.content_type,
                fetch_backend: receipt.backend,
                requested_fetch_mode: receipt.requested_mode.as_str().to_owned(),
                resolved_fetch_mode: receipt.resolved_mode.as_str().to_owned(),
                extraction: receipt.extraction,
                rendered: receipt.rendered,
                fetch_elapsed_ms,
                discovered_by: Vec::new(),
                created_at: now,
                updated_at: now,
            });
        }
        self.touch(now);
        Ok(id)
    }

    pub fn record_claims(
        &mut self,
        inputs: Vec<ClaimInput>,
        now: i64,
    ) -> Result<usize, ResearchError> {
        self.guard(now)?;
        self.require_phase(
            &[
                ResearchPhase::Searching,
                ResearchPhase::GapAnalysis,
                ResearchPhase::Synthesizing,
            ],
            "researching or synthesizing",
        )?;
        if inputs.is_empty() {
            return Err(ResearchError::Invalid("claims cannot be empty".to_owned()));
        }
        if self.claims.len().saturating_add(inputs.len()) > self.budget.max_claims as usize {
            return Err(ResearchError::Budget("claim count"));
        }
        let by_url = self
            .sources
            .iter()
            .map(|source| (canonical_url(&source.url), source.id.clone()))
            .collect::<HashMap<_, _>>();
        let mut added = 0usize;
        for input in inputs {
            let text = normalize_space(&input.text);
            if text.len() < 8
                || self
                    .claims
                    .iter()
                    .any(|claim| claim.text.eq_ignore_ascii_case(&text))
            {
                continue;
            }
            let claim_id = stable_id("claim", &format!("{}:{text}", self.id));
            let mut citation_ids = Vec::new();
            for citation in input.citations {
                let canonical = canonical_url(&citation.url);
                let citation_id = stable_id(
                    "citation",
                    &format!("{claim_id}:{canonical}:{}", citation.locator),
                );
                citation_ids.push(citation_id.clone());
                self.citations.push(CitationRecord {
                    id: citation_id,
                    claim_id: claim_id.clone(),
                    source_id: by_url.get(&canonical).cloned(),
                    url: citation.url,
                    locator: citation.locator,
                    quote_hash: blake3::hash(citation.quote.as_bytes()).to_hex().to_string(),
                    quote: citation.quote,
                    structural_valid: false,
                    link_valid: false,
                    support_bps: 0,
                });
            }
            self.claims.push(ClaimRecord {
                id: claim_id,
                text,
                confidence_bps: input.confidence_bps.min(10_000),
                citation_ids,
                verified: false,
                created_at: now,
            });
            added += 1;
        }
        self.touch(now);
        Ok(added)
    }

    pub fn assess_gaps(
        &mut self,
        inputs: Vec<GapInput>,
        continue_research: bool,
        now: i64,
    ) -> Result<(), ResearchError> {
        self.guard(now)?;
        self.require_phase(
            &[ResearchPhase::Searching, ResearchPhase::GapAnalysis],
            "searching or gap_analysis",
        )?;
        self.usage.gap_cycles += 1;
        let cycle = self.usage.gap_cycles;
        let mut unique = HashSet::new();
        for input in inputs.into_iter().take(12) {
            let description = normalize_space(&input.description);
            if description.len() < 5 || !unique.insert(description.to_lowercase()) {
                continue;
            }
            self.gaps.push(GapRecord {
                id: stable_id("gap", &format!("{}:{cycle}:{description}", self.id)),
                description,
                priority: input.priority.min(9),
                suggested_queries: input.suggested_queries,
                status: if continue_research {
                    "open"
                } else {
                    "accepted"
                }
                .to_owned(),
                cycle,
                created_at: now,
            });
        }
        let signature = format!(
            "{}:{}:{}",
            self.sources.iter().filter(|source| source.fetched).count(),
            self.claims.len(),
            self.citations.len()
        );
        if signature == self.last_progress_signature {
            self.stagnant_cycles = self.stagnant_cycles.saturating_add(1);
        } else {
            self.stagnant_cycles = 0;
        }
        self.last_progress_signature = signature;
        let budget_stop = cycle >= self.budget.max_gap_cycles;
        let stalled = self.stagnant_cycles >= 2;
        if continue_research && !budget_stop && !stalled {
            self.phase = ResearchPhase::GapAnalysis;
        } else {
            if budget_stop {
                self.stop_reason = Some("gap cycle budget reached".to_owned());
            }
            if stalled {
                self.stop_reason = Some("research progress stalled".to_owned());
            }
            self.phase = ResearchPhase::Synthesizing;
        }
        self.touch(now);
        Ok(())
    }

    pub fn submit_synthesis(&mut self, markdown: String, now: i64) -> Result<(), ResearchError> {
        self.guard(now)?;
        self.require_phase(
            &[
                ResearchPhase::Synthesizing,
                ResearchPhase::GapAnalysis,
                ResearchPhase::Searching,
            ],
            "synthesizing",
        )?;
        if markdown.trim().len() < 80 {
            return Err(ResearchError::Invalid("synthesis is too short".to_owned()));
        }
        if self.claims.is_empty() {
            return Err(ResearchError::Invalid(
                "synthesis requires recorded claims".to_owned(),
            ));
        }
        self.draft_markdown = Some(markdown);
        self.usage.synthesis_revisions += 1;
        self.phase = ResearchPhase::Verifying;
        self.touch(now);
        Ok(())
    }

    pub fn verify(&mut self, now: i64) -> Result<&VerificationReport, ResearchError> {
        self.guard(now)?;
        self.require_phase(&[ResearchPhase::Verifying], "verifying")?;
        let report = verify_session(self);
        for citation in &mut self.citations {
            let source = citation
                .source_id
                .as_deref()
                .and_then(|id| self.sources.iter().find(|source| source.id == id));
            citation.structural_valid = source.is_some();
            citation.link_valid = source
                .is_some_and(|source| source.fetched && (200..400).contains(&source.fetch_status));
            let weak = report
                .issues
                .iter()
                .any(|issue| issue.citation_id.as_deref() == Some(&citation.id));
            citation.support_bps = if weak { 0 } else { 10_000 };
        }
        for claim in &mut self.claims {
            claim.verified = !report
                .issues
                .iter()
                .any(|issue| issue.claim_id.as_deref() == Some(&claim.id));
        }
        self.verification = Some(report);
        if self.verification.as_ref().is_some_and(|value| value.passed) {
            self.phase = ResearchPhase::AwaitingNoteProposal;
        } else if self.usage.synthesis_revisions < 3
            && self.usage.gap_cycles < self.budget.max_gap_cycles
        {
            self.phase = ResearchPhase::GapAnalysis;
        } else {
            self.phase = ResearchPhase::Failed;
            self.stop_reason = Some("citation verification failed within budget".to_owned());
        }
        self.touch(now);
        Ok(self
            .verification
            .as_ref()
            .expect("verification was assigned"))
    }

    pub fn allow_note_proposal(&self) -> bool {
        self.phase == ResearchPhase::AwaitingNoteProposal
            && self
                .verification
                .as_ref()
                .is_some_and(|report| report.passed)
    }

    pub fn mark_completed(&mut self, now: i64) -> Result<(), ResearchError> {
        self.require_phase(
            &[ResearchPhase::AwaitingNoteProposal],
            "awaiting_note_proposal",
        )?;
        self.phase = ResearchPhase::Completed;
        self.touch(now);
        Ok(())
    }

    pub fn cancel(&mut self, now: i64) {
        self.cancel_requested = true;
        self.phase = ResearchPhase::Cancelled;
        self.stop_reason = Some("cancelled by user".to_owned());
        self.touch(now);
    }

    pub fn receipt(&self, now: i64) -> ResearchReceipt {
        ResearchReceipt {
            schema_version: "phoenix-research-receipt/v1".to_owned(),
            run_id: self.id.clone(),
            phase: self.phase,
            stop_reason: self.stop_reason.clone(),
            searches: self.usage.searches,
            fetches: self.usage.fetches,
            source_count: self.sources.len(),
            claim_count: self.claims.len(),
            gap_cycles: self.usage.gap_cycles,
            coverage_bps: self
                .verification
                .as_ref()
                .map_or(0, |report| report.coverage_bps),
            elapsed_ms: now.saturating_sub(self.started_at),
            created_at: now,
        }
    }

    pub fn prioritized_sources(&self) -> Vec<&SourceRecord> {
        let cited = self
            .citations
            .iter()
            .filter_map(|citation| citation.source_id.as_deref())
            .collect::<HashSet<_>>();
        let mut sources = self.sources.iter().collect::<Vec<_>>();
        sources.sort_by_key(|source| {
            Reverse((
                cited.contains(source.id.as_str()),
                source.fetched,
                source.discovered_by.len(),
            ))
        });
        sources
    }

    fn guard(&self, now: i64) -> Result<(), ResearchError> {
        if self.cancel_requested || self.phase == ResearchPhase::Cancelled {
            return Err(ResearchError::Cancelled);
        }
        if now.saturating_sub(self.started_at) > self.budget.max_wall_ms {
            return Err(ResearchError::Budget("wall clock"));
        }
        Ok(())
    }

    fn require_phase(
        &self,
        allowed: &[ResearchPhase],
        expected: &'static str,
    ) -> Result<(), ResearchError> {
        if allowed.contains(&self.phase) {
            Ok(())
        } else {
            Err(ResearchError::Phase {
                expected,
                actual: self.phase,
            })
        }
    }

    fn touch(&mut self, now: i64) {
        self.updated_at = now;
    }
}

pub(crate) fn stable_id(prefix: &str, input: &str) -> String {
    let digest = blake3::hash(input.as_bytes()).to_hex();
    format!("{prefix}:{}", &digest.as_str()[..24])
}

pub(crate) fn canonical_url(input: &str) -> String {
    let Ok(mut url) = url::Url::parse(input.trim()) else {
        return input.trim().to_lowercase();
    };
    url.set_fragment(None);
    let retained = url
        .query_pairs()
        .filter(|(key, _)| !key.starts_with("utm_") && !matches!(key.as_ref(), "fbclid" | "gclid"))
        .map(|(key, value)| (key.into_owned(), value.into_owned()))
        .collect::<Vec<_>>();
    url.set_query(None);
    if !retained.is_empty() {
        url.query_pairs_mut().extend_pairs(retained);
    }
    let value = url.to_string();
    value.trim_end_matches('/').to_owned()
}

fn normalize_space(input: &str) -> String {
    input.split_whitespace().collect::<Vec<_>>().join(" ")
}
