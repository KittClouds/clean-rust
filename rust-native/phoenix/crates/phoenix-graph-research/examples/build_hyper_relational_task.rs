use phoenix_graph_research::{
    build_canonical_hyper_relational_task, ExternalDatasetMapped, HyperRelationalTaskMapped,
};
use serde::Serialize;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Report<'a> {
    task_id: &'a str,
    build_ms: f64,
    restart_open_ms: f64,
    binary_bytes: u64,
    source_binary_bytes: u64,
    candidate_universe: u32,
    base_relations: u32,
    train_statements: u64,
    validation_statements: u64,
    test_statements: u64,
    validation_queries: u64,
    test_queries: u64,
    truth_groups: u64,
    truth_targets: u64,
    qualifier_contexts: u64,
    qualifier_only_entities: u64,
    qualifier_only_relations: u64,
    qualifiers_borrowed_from_source: bool,
    manifest: String,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let source_manifest = PathBuf::from(
        args.next()
            .ok_or("usage: <source-manifest> <output-root>")?,
    );
    let output_root = PathBuf::from(
        args.next()
            .ok_or("usage: <source-manifest> <output-root>")?,
    );
    if args.next().is_some() {
        return Err("usage: <source-manifest> <output-root>".into());
    }
    let source = ExternalDatasetMapped::open(&source_manifest)?;
    let source_binary_bytes = source.manifest().binary_bytes;
    let started = Instant::now();
    let paths = build_canonical_hyper_relational_task(&source, output_root)?;
    let build_ms = started.elapsed().as_secs_f64() * 1_000.0;
    let open_started = Instant::now();
    let task = HyperRelationalTaskMapped::open(&paths.manifest, &source)?;
    let restart_open_ms = open_started.elapsed().as_secs_f64() * 1_000.0;
    let manifest = task.manifest();
    println!(
        "{}",
        serde_json::to_string_pretty(&Report {
            task_id: manifest.task_id.as_str(),
            build_ms,
            restart_open_ms,
            binary_bytes: manifest.binary_bytes,
            source_binary_bytes,
            candidate_universe: manifest.candidate_universe,
            base_relations: manifest.base_relation_count,
            train_statements: manifest.train_statements,
            validation_statements: manifest.validation_statements,
            test_statements: manifest.test_statements,
            validation_queries: manifest.validation_queries,
            test_queries: manifest.test_queries,
            truth_groups: manifest.truth_groups,
            truth_targets: manifest.truth_targets,
            qualifier_contexts: manifest.qualifier_contexts,
            qualifier_only_entities: manifest.qualifier_only_entities,
            qualifier_only_relations: manifest.qualifier_only_relations,
            qualifiers_borrowed_from_source: manifest.qualifiers_borrowed_from_source,
            manifest: paths.manifest.display().to_string(),
        })?
    );
    Ok(())
}
