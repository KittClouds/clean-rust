use anyhow::{Context, Result};
use phoenix_analysis_contract::{NliAdjudication, NliCandidate, NliDecision};
use phoenix_rel_post::{
    adjudicate_claims_with_nli, NliClaimAdjudicationOptions, NliClaimDecisionKind, NliClaimInput,
    NliClaimPurpose, NliModel, NliModelMetadata,
};
use std::path::Path;
use std::time::Instant;

pub struct NliRun {
    pub adjudications: Vec<NliAdjudication>,
    pub metadata: NliModelMetadata,
    pub load_micros: u64,
    pub adjudication_micros: u64,
}

pub fn run(candidates: &[NliCandidate], model_root: &Path) -> Result<NliRun> {
    let load_started = Instant::now();
    let model = NliModel::load(model_root)
        .with_context(|| format!("load ModernBERT NLI from {}", model_root.display()))?;
    let load_micros = elapsed_micros(load_started);
    let metadata = model.metadata().clone();
    let claims = candidates
        .iter()
        .map(|candidate| NliClaimInput {
            schema_version: phoenix_rel_post::NLI_CLAIM_INPUT_SCHEMA_VERSION.to_owned(),
            claim_id: hex(&candidate.candidate_id),
            evidence_id: format!("{}:{}", candidate.premise_start, candidate.premise_end),
            premise: candidate.premise.clone(),
            hypothesis: candidate.hypothesis.clone(),
            purpose: NliClaimPurpose::HumanReviewTriage,
            classification_vote: None,
            evidence_refs: Vec::new(),
        })
        .collect::<Vec<_>>();
    let adjudication_started = Instant::now();
    let results = adjudicate_claims_with_nli(
        &claims,
        &model,
        NliClaimAdjudicationOptions {
            max_pairs_per_batch: 1,
            ..Default::default()
        },
    )
    .context("ModernBERT NLI candidate adjudication")?;
    let adjudication_micros = elapsed_micros(adjudication_started);
    let adjudications = results
        .into_iter()
        .zip(candidates)
        .map(|(result, candidate)| NliAdjudication {
            candidate_id: candidate.candidate_id,
            decision: match result.nli_vote.decision {
                NliClaimDecisionKind::Supported => NliDecision::Supported,
                NliClaimDecisionKind::Contradicted => NliDecision::Contradicted,
                NliClaimDecisionKind::Unknown => NliDecision::Unknown,
            },
            entailment_millis: result.nli_vote.entailment_millis,
            contradiction_millis: result.nli_vote.contradiction_millis,
            neutral_millis: result.nli_vote.neutral_millis,
            confidence_millis: result.nli_vote.confidence_millis,
            needs_human_review: result.needs_human_review,
        })
        .collect();
    Ok(NliRun {
        adjudications,
        metadata,
        load_micros,
        adjudication_micros,
    })
}

fn elapsed_micros(started: Instant) -> u64 {
    started.elapsed().as_micros().try_into().unwrap_or(u64::MAX)
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}
