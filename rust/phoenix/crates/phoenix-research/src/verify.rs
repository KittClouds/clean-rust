use hashbrown::{HashMap, HashSet};

use crate::{ResearchSession, VerificationIssue, VerificationReport};

pub fn verify_session(session: &ResearchSession) -> VerificationReport {
    let mut issues = Vec::new();
    let mut verified_citations = 0usize;
    let source_ids = session
        .sources
        .iter()
        .map(|source| source.id.as_str())
        .collect::<HashSet<_>>();
    let source_terms = session
        .sources
        .iter()
        .map(|source| (source.id.as_str(), meaningful_terms(&source.content)))
        .collect::<HashMap<_, _>>();
    let normalized_sources = session
        .sources
        .iter()
        .map(|source| (source.id.as_str(), normalize(&source.content)))
        .collect::<HashMap<_, _>>();

    for citation in &session.citations {
        let source = citation
            .source_id
            .as_deref()
            .and_then(|id| session.sources.iter().find(|candidate| candidate.id == id));
        if citation
            .source_id
            .as_deref()
            .is_none_or(|id| !source_ids.contains(id))
        {
            issues.push(VerificationIssue {
                code: "citation_source_missing".to_owned(),
                claim_id: Some(citation.claim_id.clone()),
                citation_id: Some(citation.id.clone()),
                detail: format!("Citation source was not captured: {}", citation.url),
            });
            continue;
        }
        let Some(source) = source else { continue };
        if !source.fetched || !(200..400).contains(&source.fetch_status) {
            issues.push(VerificationIssue {
                code: "citation_link_unverified".to_owned(),
                claim_id: Some(citation.claim_id.clone()),
                citation_id: Some(citation.id.clone()),
                detail: format!(
                    "Citation URL was not fetched successfully: {}",
                    citation.url
                ),
            });
            continue;
        }
        let claim = session
            .claims
            .iter()
            .find(|claim| claim.id == citation.claim_id);
        let quote_present = !citation.quote.trim().is_empty()
            && normalized_sources
                .get(source.id.as_str())
                .is_some_and(|content| content.contains(&normalize(&citation.quote)));
        let support = claim.map_or(0, |claim| {
            lexical_support_bps(
                &meaningful_terms(&claim.text),
                source_terms
                    .get(source.id.as_str())
                    .expect("captured source terms"),
            )
        });
        if !quote_present && support < 1_800 {
            issues.push(VerificationIssue {
                code: "citation_support_weak".to_owned(),
                claim_id: Some(citation.claim_id.clone()),
                citation_id: Some(citation.id.clone()),
                detail: format!(
                    "Captured source does not deterministically support the claim: {}",
                    citation.url
                ),
            });
            continue;
        }
        verified_citations += 1;
    }

    let verified_claims = session
        .claims
        .iter()
        .filter(|claim| {
            !claim.citation_ids.is_empty()
                && claim.citation_ids.iter().any(|citation_id| {
                    !issues
                        .iter()
                        .any(|issue| issue.citation_id.as_deref() == Some(citation_id))
                })
        })
        .count();

    for claim in &session.claims {
        if claim.citation_ids.is_empty() {
            issues.push(VerificationIssue {
                code: "claim_uncited".to_owned(),
                claim_id: Some(claim.id.clone()),
                citation_id: None,
                detail: "Factual claim has no citation.".to_owned(),
            });
        } else if !claim.citation_ids.iter().any(|citation_id| {
            !issues
                .iter()
                .any(|issue| issue.citation_id.as_deref() == Some(citation_id))
        }) {
            issues.push(VerificationIssue {
                code: "claim_unsupported".to_owned(),
                claim_id: Some(claim.id.clone()),
                citation_id: None,
                detail: "No citation for this claim passed source and support checks.".to_owned(),
            });
        } else {
            let draft = session.draft_markdown.as_deref().unwrap_or_default();
            let cited_in_draft = claim
                .citation_ids
                .iter()
                .filter_map(|citation_id| {
                    session
                        .citations
                        .iter()
                        .find(|citation| citation.id == *citation_id)
                })
                .any(|citation| draft.contains(&citation.url));
            if !cited_in_draft {
                issues.push(VerificationIssue {
                    code: "draft_citation_missing".to_owned(),
                    claim_id: Some(claim.id.clone()),
                    citation_id: None,
                    detail: "Verified claim source URL is absent from the note synthesis."
                        .to_owned(),
                });
            }
        }
    }

    let draft_citation_failures = issues
        .iter()
        .filter(|issue| issue.code == "draft_citation_missing")
        .count();
    let draft_verified_claims = verified_claims.saturating_sub(draft_citation_failures);
    let coverage_bps = if session.claims.is_empty() {
        0
    } else {
        ((draft_verified_claims * 10_000) / session.claims.len()).min(10_000) as u16
    };
    if coverage_bps < session.budget.minimum_coverage_bps {
        issues.push(VerificationIssue {
            code: "coverage_below_policy".to_owned(),
            claim_id: None,
            citation_id: None,
            detail: format!(
                "Verified claim coverage is {coverage_bps} bps; policy requires {} bps.",
                session.budget.minimum_coverage_bps
            ),
        });
    }
    if session
        .draft_markdown
        .as_deref()
        .is_none_or(|draft| draft.trim().is_empty())
    {
        issues.push(VerificationIssue {
            code: "synthesis_missing".to_owned(),
            claim_id: None,
            citation_id: None,
            detail: "No note synthesis was staged for verification.".to_owned(),
        });
    }

    VerificationReport {
        passed: issues.is_empty(),
        claim_count: session.claims.len(),
        verified_claim_count: draft_verified_claims,
        citation_count: session.citations.len(),
        verified_citation_count: verified_citations,
        coverage_bps,
        issues,
    }
}

fn lexical_support_bps(claim_terms: &HashSet<String>, source_terms: &HashSet<String>) -> u16 {
    if claim_terms.is_empty() {
        return 0;
    }
    let hits = claim_terms
        .iter()
        .filter(|term| source_terms.contains(*term))
        .count();
    ((hits * 10_000) / claim_terms.len()).min(10_000) as u16
}

fn meaningful_terms(input: &str) -> HashSet<String> {
    input
        .split(|ch: char| !ch.is_alphanumeric())
        .map(str::to_lowercase)
        .filter(|term| term.len() >= 4 && !STOP_WORDS.contains(&term.as_str()))
        .collect()
}

fn normalize(input: &str) -> String {
    input
        .split_whitespace()
        .flat_map(str::chars)
        .flat_map(char::to_lowercase)
        .collect()
}

const STOP_WORDS: &[&str] = &[
    "about", "after", "before", "could", "from", "have", "into", "more", "most", "other", "should",
    "than", "that", "their", "there", "these", "they", "this", "those", "were", "what", "when",
    "where", "which", "while", "with", "would",
];
