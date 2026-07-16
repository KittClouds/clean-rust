use phoenix_candle_baseline_trainer::{
    run_qualifier_signal_matrix16, QualifierSignalMatrixRequest,
};
use phoenix_graph_research::HyperEncoderTrainingConfig;
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = std::env::args_os().skip(1);
    let source_manifest = PathBuf::from(arguments.next().ok_or("source manifest")?);
    let task_manifest = PathBuf::from(arguments.next().ok_or("task manifest")?);
    let output_root = PathBuf::from(arguments.next().ok_or("output root")?);
    if arguments.next().is_some() {
        return Err("usage: qualifier-signal-matrix SOURCE TASK OUTPUT".into());
    }
    let outcome = run_qualifier_signal_matrix16(&QualifierSignalMatrixRequest {
        source_manifest,
        task_manifest,
        output_root,
        seed: 0x51a7_e001,
        config: HyperEncoderTrainingConfig::default(),
    })?;
    println!("{}", std::fs::read_to_string(outcome.manifest)?);
    Ok(())
}
