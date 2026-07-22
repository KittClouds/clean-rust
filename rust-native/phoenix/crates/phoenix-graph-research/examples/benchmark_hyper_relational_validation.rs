use phoenix_graph_research::{
    evaluate_hyper_relational_validation_batched, ExternalDatasetMapped,
    HyperRelationalCandidatePolicy, HyperRelationalQueryView, HyperRelationalTaskMapped,
};
use serde::Serialize;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Report<'a> {
    task_id: &'a str,
    certificate_id: &'a str,
    score_blake3: &'a str,
    validation_queries: u64,
    candidates_ranked: u64,
    elapsed_ms: f64,
    million_candidate_ranks_per_second: f64,
    mean_reciprocal_rank: f64,
    hits_at_5: f64,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let source_manifest = PathBuf::from(
        args.next()
            .ok_or("usage: <source-manifest> <task-manifest>")?,
    );
    let task_manifest = PathBuf::from(
        args.next()
            .ok_or("usage: <source-manifest> <task-manifest>")?,
    );
    if args.next().is_some() {
        return Err("usage: <source-manifest> <task-manifest>".into());
    }
    let source = ExternalDatasetMapped::open(source_manifest)?;
    let task = HyperRelationalTaskMapped::open(task_manifest, &source)?;
    let started = Instant::now();
    let certificate = evaluate_hyper_relational_validation_batched(
        &task,
        "deterministic-hyper-relational-evaluator-calibration-v1",
        HyperRelationalCandidatePolicy::FullEntity,
        64,
        deterministic_scores,
    )?;
    let elapsed_ms = started.elapsed().as_secs_f64() * 1_000.0;
    let throughput = certificate.metrics.candidates_scored as f64 / elapsed_ms / 1_000.0;
    println!(
        "{}",
        serde_json::to_string_pretty(&Report {
            task_id: certificate.task_id.as_str(),
            certificate_id: certificate.certificate_id.as_str(),
            score_blake3: certificate.score_blake3.as_str(),
            validation_queries: certificate.metrics.queries,
            candidates_ranked: certificate.metrics.candidates_scored,
            elapsed_ms,
            million_candidate_ranks_per_second: throughput,
            mean_reciprocal_rank: certificate.metrics.mean_reciprocal_rank,
            hits_at_5: certificate.metrics.hits_at_5,
        })?
    );
    Ok(())
}

fn deterministic_scores(
    queries: &[HyperRelationalQueryView],
    candidates: &[u32],
    scores: &mut [f32],
) -> Result<(), String> {
    for (query, row) in queries
        .iter()
        .zip(scores.chunks_exact_mut(candidates.len()))
    {
        let seed = query.source
            ^ query.relation.wrapping_mul(0x9e37_79b9)
            ^ query.qualifier_count.rotate_left(13);
        for (candidate, score) in candidates.iter().copied().zip(row) {
            let mantissa = candidate.wrapping_mul(0x85eb_ca6b).rotate_left(seed & 31) ^ seed;
            *score = f32::from_bits(0x3f00_0000 | (mantissa & 0x007f_ffff));
        }
    }
    Ok(())
}
