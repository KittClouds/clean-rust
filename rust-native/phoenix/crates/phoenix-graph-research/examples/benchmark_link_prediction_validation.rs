use phoenix_graph_research::{evaluate_link_prediction_validation, LinkPredictionTaskMapped};
use std::error::Error;
use std::path::PathBuf;
use std::time::Instant;

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let manifest = PathBuf::from(args.next().ok_or("usage: <task-manifest>")?);
    if args.next().is_some() {
        return Err("usage: <task-manifest>".into());
    }
    let task = LinkPredictionTaskMapped::open(manifest)?;
    let score_template = (0..task.manifest().candidate_universe)
        .map(|candidate| candidate as f32)
        .collect::<Vec<_>>();
    let started = Instant::now();
    let certificate = evaluate_link_prediction_validation(
        &task,
        "evaluator-throughput-fixture-v1",
        |_query, _candidates, scores| {
            scores.copy_from_slice(&score_template);
            Ok(())
        },
    )?;
    let elapsed_ms = started.elapsed().as_secs_f64() * 1_000.0;
    println!(
        "{{\"certificateId\":\"{}\",\"elapsedMs\":{elapsed_ms:.3},\"queries\":{},\"positives\":{},\"candidatesScored\":{},\"mrr\":{:.9},\"hitsAt10\":{:.9}}}",
        certificate.certificate_id,
        certificate.queries,
        certificate.positives,
        certificate.candidates_scored,
        certificate.mean_reciprocal_rank,
        certificate.hits_at_10,
    );
    Ok(())
}
