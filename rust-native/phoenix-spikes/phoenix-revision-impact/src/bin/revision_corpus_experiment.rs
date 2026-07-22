use std::path::PathBuf;

use phoenix_revision_impact::{
    default_receipt_path, run_corpus_experiment, write_corpus_experiment_receipt,
};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let manifest = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("PHOENIX_REVISION_CORPUS_MANIFEST").map(PathBuf::from))
        .ok_or("usage: revision_corpus_experiment <protected-manifest.json> [receipt.json]")?;
    let receipt_path = std::env::args_os()
        .nth(2)
        .map(PathBuf::from)
        .unwrap_or_else(|| default_receipt_path(&manifest));
    let receipt = run_corpus_experiment(&manifest)?;
    write_corpus_experiment_receipt(&receipt, &receipt_path)?;
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    eprintln!("receipt={}", receipt_path.display());
    if !receipt.all_source_copies_unchanged || !receipt.all_cases_passed {
        return Err("real-corpus experiment gate failed".into());
    }
    Ok(())
}
