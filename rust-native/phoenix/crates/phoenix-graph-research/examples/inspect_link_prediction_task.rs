use phoenix_graph_research::LinkPredictionTaskMapped;
use std::error::Error;
use std::path::PathBuf;
use std::time::Instant;

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let manifest = PathBuf::from(args.next().ok_or("usage: <task-manifest>")?);
    if args.next().is_some() {
        return Err("usage: <task-manifest>".into());
    }
    let started = Instant::now();
    let task = LinkPredictionTaskMapped::open(&manifest)?;
    let open_ms = started.elapsed().as_secs_f64() * 1_000.0;
    println!(
        "{{\"taskId\":\"{}\",\"openMs\":{open_ms:.3},\"binaryBytes\":{},\"validationQueries\":{},\"testQueries\":{}}}",
        task.manifest().task_id,
        task.manifest().binary_bytes,
        task.validation_query_count(),
        task.test_query_count(),
    );
    Ok(())
}
