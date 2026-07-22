use phoenix_candle_baseline_trainer::{open_hyper_learning_gates, run_hyper_learning_gates};
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let output = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or("usage: hyper-learning-gates <output-root>")?;
    let paths = run_hyper_learning_gates(output)?;
    let receipt = open_hyper_learning_gates(&paths.receipt)?;
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    if !receipt.all_passed {
        return Err("hyper learning launch gate failed".into());
    }
    Ok(())
}
