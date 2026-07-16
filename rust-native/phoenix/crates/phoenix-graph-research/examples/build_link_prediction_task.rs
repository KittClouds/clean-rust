use phoenix_graph_research::{
    build_canonical_link_prediction_task, ExternalDatasetMapped, LinkPredictionTaskMapped,
};
use std::error::Error;
use std::path::PathBuf;
use std::time::Instant;

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let source_manifest = PathBuf::from(
        args.next()
            .ok_or("usage: <source-manifest> <source-root> <output-root>")?,
    );
    let source_root = PathBuf::from(
        args.next()
            .ok_or("usage: <source-manifest> <source-root> <output-root>")?,
    );
    let output_root = PathBuf::from(
        args.next()
            .ok_or("usage: <source-manifest> <source-root> <output-root>")?,
    );
    if args.next().is_some() {
        return Err("usage: <source-manifest> <source-root> <output-root>".into());
    }
    let source = ExternalDatasetMapped::open(source_manifest)?;
    let started = Instant::now();
    let paths = build_canonical_link_prediction_task(&source, source_root, output_root)?;
    let build_ms = started.elapsed().as_secs_f64() * 1_000.0;
    drop(source);
    let open_started = Instant::now();
    let task = LinkPredictionTaskMapped::open(&paths.manifest)?;
    let open_ms = open_started.elapsed().as_secs_f64() * 1_000.0;
    let manifest = task.manifest();
    println!(
        "{{\"taskId\":\"{}\",\"buildMs\":{build_ms:.3},\"openMs\":{open_ms:.3},\"binaryBytes\":{},\"candidateUniverse\":{},\"baseRelations\":{},\"derivedRelations\":{},\"validationQueries\":{},\"validationPositives\":{},\"testQueries\":{},\"testPositives\":{},\"inverseQueries\":{},\"manifest\":\"{}\"}}",
        manifest.task_id,
        manifest.binary_bytes,
        manifest.candidate_universe,
        manifest.base_relation_count,
        manifest.derived_relation_count,
        manifest.validation_queries,
        manifest.validation_positives,
        manifest.test_queries,
        manifest.test_positives,
        manifest.inverse_queries,
        paths.manifest.display(),
    );
    Ok(())
}
