use anyhow::{Context, Result};
use phoenix_analysis_contract::{NliAdjudication, NliCandidate, NliDecision};
use phoenix_rel_post::{
    adjudicate_claims_with_nli, NliClaimAdjudicationOptions, NliClaimDecisionKind, NliClaimInput,
    NliClaimPurpose, NliModel, NliModelMetadata, OrtCacheStatus,
};
use std::path::Path;
use std::time::Instant;

// The quadratic attention budget in phoenix-rel-post is the actual memory
// guard. Keep the outer batch large enough to let that planner bucket the
// complete Shortrun candidate set globally instead of forcing two unrelated
// 32/25 plans and two extra DirectML submissions.
const DEFAULT_NLI_BATCH_SIZE: usize = 64;
const MAX_NLI_BATCH_SIZE: usize = 64;

/// Returns the bounded number of claims sent to ModernBERT per inference.
///
/// The resident runtime is deliberately batched: a one-claim call defeats
/// ONNX execution batching and turns a large candidate set into thousands of
/// model submissions.  The environment override is kept small and explicit
/// so benchmark runs can tune it without changing the artifact contract.
pub fn batch_size() -> usize {
    std::env::var("PHOENIX_NLI_BATCH_SIZE")
        .ok()
        .and_then(|raw| raw.parse::<usize>().ok())
        .map(|value| value.clamp(1, MAX_NLI_BATCH_SIZE))
        .unwrap_or(DEFAULT_NLI_BATCH_SIZE)
}

pub struct NliRun {
    pub adjudications: Vec<NliAdjudication>,
    pub load_micros: u64,
    pub adjudication_micros: u64,
}

pub struct LoadedNli {
    model: NliModel,
    metadata: NliModelMetadata,
    pub load_micros: u64,
    pub cache_status: OrtCacheStatus,
}

impl LoadedNli {
    pub fn load(model_root: &Path) -> Result<Self> {
        let load_started = Instant::now();
        let (model, ort_info) = NliModel::load_with_ort_info(model_root)
            .with_context(|| format!("load ModernBERT NLI from {}", model_root.display()))?;
        let load_micros = elapsed_micros(load_started);
        let metadata = model.metadata().clone();
        Ok(Self {
            model,
            metadata,
            load_micros,
            cache_status: ort_info.cache_status,
        })
    }

    pub fn run(&self, candidates: &[NliCandidate]) -> Result<NliRun> {
        run_loaded(candidates, &self.model)
    }

    pub fn metadata(&self) -> &NliModelMetadata {
        &self.metadata
    }
}

fn run_loaded(candidates: &[NliCandidate], model: &NliModel) -> Result<NliRun> {
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
        model,
        NliClaimAdjudicationOptions {
            max_pairs_per_batch: batch_size(),
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
        load_micros: 0,
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
