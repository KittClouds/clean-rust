use anyhow::{Context, Result};
use phoenix_analysis_contract::{open_analysis_artifact, NliAdjudication};
use std::env;
use std::path::PathBuf;

fn main() -> Result<()> {
    let mut arguments = env::args_os().skip(1).map(PathBuf::from);
    let left_path = arguments.next().context("missing left analysis artifact")?;
    let right_path = arguments
        .next()
        .context("missing right analysis artifact")?;
    anyhow::ensure!(arguments.next().is_none(), "unexpected extra argument");

    let left = open_analysis_artifact(&left_path).context("open left artifact")?;
    let right = open_analysis_artifact(&right_path).context("open right artifact")?;
    let left = left.analysis();
    let right = right.analysis();

    anyhow::ensure!(left.ner.entities == right.ner.entities, "entities differ");
    anyhow::ensure!(left.ner.mentions == right.ner.mentions, "mentions differ");
    anyhow::ensure!(
        left.nli.nli_candidates == right.nli.nli_candidates,
        "NLI candidates differ"
    );
    anyhow::ensure!(
        left.nli.nli_adjudications.len() == right.nli.nli_adjudications.len(),
        "NLI adjudication counts differ"
    );

    let mut decision_mismatches = 0_usize;
    let mut review_mismatches = 0_usize;
    let mut max_probability_delta = 0_u32;
    for (left, right) in left
        .nli
        .nli_adjudications
        .iter()
        .zip(&right.nli.nli_adjudications)
    {
        compare_adjudication(
            left,
            right,
            &mut decision_mismatches,
            &mut review_mismatches,
            &mut max_probability_delta,
        )?;
    }

    println!(
        "PHOENIX_ANALYSIS_PARITY entities={} mentions={} candidates={} adjudications={} decision_mismatches={} review_mismatches={} max_probability_delta_millis={}",
        left.ner.entities.len(),
        left.ner.mentions.len(),
        left.nli.nli_candidates.len(),
        left.nli.nli_adjudications.len(),
        decision_mismatches,
        review_mismatches,
        max_probability_delta,
    );
    println!(
        "left_decisions={:?}",
        decision_counts(&left.nli.nli_adjudications)
    );
    println!(
        "right_decisions={:?}",
        decision_counts(&right.nli.nli_adjudications)
    );
    Ok(())
}

fn decision_counts(values: &[NliAdjudication]) -> [usize; 3] {
    let mut counts = [0; 3];
    for value in values {
        let index = match value.decision {
            phoenix_analysis_contract::NliDecision::Supported => 0,
            phoenix_analysis_contract::NliDecision::Contradicted => 1,
            phoenix_analysis_contract::NliDecision::Unknown => 2,
        };
        counts[index] += 1;
    }
    counts
}

fn compare_adjudication(
    left: &NliAdjudication,
    right: &NliAdjudication,
    decision_mismatches: &mut usize,
    review_mismatches: &mut usize,
    max_probability_delta: &mut u32,
) -> Result<()> {
    anyhow::ensure!(
        left.candidate_id == right.candidate_id,
        "candidate ordering or identity differs"
    );
    *decision_mismatches += usize::from(left.decision != right.decision);
    *review_mismatches += usize::from(left.needs_human_review != right.needs_human_review);
    for delta in [
        left.entailment_millis.abs_diff(right.entailment_millis),
        left.contradiction_millis
            .abs_diff(right.contradiction_millis),
        left.neutral_millis.abs_diff(right.neutral_millis),
        left.confidence_millis.abs_diff(right.confidence_millis),
    ] {
        *max_probability_delta = (*max_probability_delta).max(delta);
    }
    Ok(())
}
