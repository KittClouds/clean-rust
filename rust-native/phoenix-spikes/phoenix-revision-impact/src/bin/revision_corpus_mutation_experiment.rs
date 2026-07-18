use std::path::PathBuf;

use phoenix_revision_impact::{
    default_mutation_root, run_corpus_mutation_experiment, write_corpus_mutation_receipt,
    write_corpus_mutation_review,
};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let manifest = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or("usage: revision_corpus_mutation_experiment <manifest> [mutation-root] [receipt]")?;
    let mutation_root = std::env::args_os()
        .nth(2)
        .map(PathBuf::from)
        .unwrap_or_else(|| default_mutation_root(&manifest));
    let receipt_path = std::env::args_os()
        .nth(3)
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            manifest
                .parent()
                .unwrap_or_else(|| std::path::Path::new("."))
                .join("receipts")
                .join("real-text-mutations-v2.json")
        });
    let receipt = run_corpus_mutation_experiment(&manifest, &mutation_root)?;
    write_corpus_mutation_receipt(&receipt, &receipt_path)?;
    let review_path = receipt_path.with_extension("md");
    write_corpus_mutation_review(&receipt, &review_path)?;
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    eprintln!("receipt={}", receipt_path.display());
    eprintln!("review={}", review_path.display());
    if !receipt.all_cases_passed {
        return Err("real-text mutation experiment gate failed".into());
    }
    Ok(())
}
