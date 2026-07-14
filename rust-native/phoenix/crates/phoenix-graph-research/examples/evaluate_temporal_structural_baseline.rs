use phoenix_graph_research::{
    evaluate_temporal_frequency_baseline, stage_temporal_rgcn, ExternalDatasetMapped,
    LinkPredictionTaskMapped, TemporalRgcnConfig,
};
use std::error::Error;
use std::path::PathBuf;
use std::time::Instant;

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let source_path = PathBuf::from(args.next().ok_or("usage: <source> <task>")?);
    let task_path = PathBuf::from(args.next().ok_or("usage: <source> <task>")?);
    if args.next().is_some() {
        return Err("usage: <source> <task>".into());
    }
    let source = ExternalDatasetMapped::open(source_path)?;
    let task = LinkPredictionTaskMapped::open(task_path)?;
    if source.manifest().dataset_id != task.manifest().source_dataset_id {
        return Err("source/task identity mismatch".into());
    }
    let staged = stage_temporal_rgcn(&source, &task, TemporalRgcnConfig::default())?;
    let started = Instant::now();
    let certificate = evaluate_temporal_frequency_baseline(&task, &staged)?;
    println!(
        "{{\"modelId\":\"{}\",\"elapsedMs\":{:.3},\"stagedBytes\":{},\"certificate\":{}}}",
        certificate.model_id,
        started.elapsed().as_secs_f64() * 1_000.0,
        staged.profile.staged_bytes,
        serde_json::to_string(&certificate)?,
    );
    Ok(())
}
