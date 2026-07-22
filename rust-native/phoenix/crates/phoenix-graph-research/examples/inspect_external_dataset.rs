use phoenix_graph_research::ExternalDatasetMapped;
use serde::Serialize;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RestartReport<'a> {
    open_and_verify_ms: f64,
    dataset_id: &'a str,
    binary_bytes: u64,
    facts: u64,
    qualifiers: u64,
    mapped_fact_rows: usize,
    mapped_qualifier_rows: usize,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let manifest = PathBuf::from(args.next().ok_or("usage: <manifest>")?);
    if args.next().is_some() {
        return Err("unexpected argument".into());
    }
    let started = Instant::now();
    let mapped = ExternalDatasetMapped::open(manifest)?;
    let open_and_verify_ms = started.elapsed().as_secs_f64() * 1_000.0;
    let facts = mapped.facts()?;
    let qualifiers = mapped.qualifiers()?;
    let manifest = mapped.manifest();
    println!(
        "{}",
        serde_json::to_string_pretty(&RestartReport {
            open_and_verify_ms,
            dataset_id: manifest.dataset_id.as_str(),
            binary_bytes: manifest.binary_bytes,
            facts: manifest.facts,
            qualifiers: manifest.qualifiers,
            mapped_fact_rows: facts.len(),
            mapped_qualifier_rows: qualifiers.len(),
        })?
    );
    Ok(())
}
