use phoenix_graph_research::{import_tkgl_smallpedia, import_wd50k, ExternalDatasetMapped};
use serde::Serialize;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ImportReport<'a> {
    import_ms: f64,
    open_and_verify_ms: f64,
    dataset_id: &'a str,
    source_identity: &'a str,
    binary_blake3: &'a str,
    binary_bytes: u64,
    entities: u64,
    relations: u64,
    facts: u64,
    temporal_facts: u64,
    static_facts: u64,
    qualifiers: u64,
    train_facts: u64,
    validation_facts: u64,
    test_facts: u64,
    unsplit_facts: u64,
    max_qualifiers_per_fact: u32,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let kind = args
        .next()
        .ok_or("usage: <smallpedia|wd50k> <source> <output>")?;
    let source = PathBuf::from(args.next().ok_or("missing source")?);
    let output = PathBuf::from(args.next().ok_or("missing output")?);
    if args.next().is_some() {
        return Err("unexpected argument".into());
    }
    let started = Instant::now();
    let paths = match kind.to_str() {
        Some("smallpedia") => import_tkgl_smallpedia(source, output)?,
        Some("wd50k") => import_wd50k(source, output)?,
        _ => return Err("dataset must be smallpedia or wd50k".into()),
    };
    let import_ms = started.elapsed().as_secs_f64() * 1_000.0;
    let open_started = Instant::now();
    let mapped = ExternalDatasetMapped::open(paths.manifest)?;
    let open_and_verify_ms = open_started.elapsed().as_secs_f64() * 1_000.0;
    let manifest = mapped.manifest();
    let facts = mapped.facts()?;
    let mut split_counts = [0_u64; 4];
    let mut max_qualifiers_per_fact = 0_u32;
    for fact in facts.iter() {
        let slot = usize::from(fact.split());
        if slot >= split_counts.len() {
            return Err("invalid split in mapped artifact".into());
        }
        split_counts[slot] += 1;
        max_qualifiers_per_fact = max_qualifiers_per_fact.max(fact.qualifier_count());
    }
    println!(
        "{}",
        serde_json::to_string_pretty(&ImportReport {
            import_ms,
            open_and_verify_ms,
            dataset_id: manifest.dataset_id.as_str(),
            source_identity: manifest.source_identity.as_str(),
            binary_blake3: manifest.binary_blake3.as_str(),
            binary_bytes: manifest.binary_bytes,
            entities: manifest.entities,
            relations: manifest.relations,
            facts: manifest.facts,
            temporal_facts: manifest.temporal_facts,
            static_facts: manifest.static_facts,
            qualifiers: manifest.qualifiers,
            train_facts: split_counts[1],
            validation_facts: split_counts[2],
            test_facts: split_counts[3],
            unsplit_facts: split_counts[0],
            max_qualifiers_per_fact,
        })?
    );
    Ok(())
}
