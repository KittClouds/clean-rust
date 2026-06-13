use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;

use phoenix_graph_rebuild::{
    build_document_semantic_summary, DocumentSemanticInput, DocumentSemanticRequest,
};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("../../../../docs/midrun.md"));
    let text = fs::read_to_string(&path)?;
    let started = Instant::now();
    let summary = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![DocumentSemanticInput {
            note_id: path
                .file_stem()
                .and_then(|value| value.to_str())
                .unwrap_or("document")
                .to_owned(),
            text,
        }],
        entities: Vec::new(),
    });
    let elapsed = started.elapsed();
    let counters = &summary.counters;
    println!("schema={}", summary.schema_version);
    println!("source={}", path.display());
    println!("elapsed_ms={}", elapsed.as_millis());
    println!("sentences={}", counters.sentences);
    println!("propositions={}", counters.propositions);
    println!("arguments={}", counters.arguments);
    println!("negated={}", counters.negated);
    println!("modal={}", counters.modal);
    println!("conditional={}", counters.conditional);
    println!("attributed={}", counters.attributed);
    println!("quoted={}", counters.quoted);
    println!("questions={}", counters.questions);
    println!("directives={}", counters.directives);
    println!("n_ary={}", counters.n_ary);
    println!("reviewable={}", counters.reviewable);
    println!("ledger_only={}", counters.ledger_only);
    println!("predicate_modifiers={}", counters.predicate_modifiers);
    println!("predicate_noise={}", counters.predicate_noise);
    for proposition in summary
        .documents
        .iter()
        .flat_map(|document| &document.propositions)
        .take(12)
    {
        println!(
            "sample={} [{}] quality={} admission={} args={} confidence={} :: {}",
            proposition.predicate,
            proposition.relation_type,
            proposition.predicate_quality,
            proposition.predicate_admission,
            proposition.arguments.len(),
            proposition.confidence_millis,
            proposition.preview
        );
    }
    Ok(())
}
