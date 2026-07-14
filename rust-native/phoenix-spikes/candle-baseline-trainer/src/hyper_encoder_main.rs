use phoenix_candle_baseline_trainer::{train_paired_hyper_encoder16, PairedHyperEncoderRequest};
use phoenix_graph_research::HyperEncoderTrainingConfig;
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = std::env::args_os().skip(1);
    let source_manifest = PathBuf::from(arguments.next().ok_or("source manifest")?);
    let task_manifest = PathBuf::from(arguments.next().ok_or("task manifest")?);
    let output_root = PathBuf::from(arguments.next().ok_or("output root")?);
    if arguments.next().is_some() {
        return Err("usage: paired-hyper-encoder-trainer SOURCE TASK OUTPUT".into());
    }
    let outcome = train_paired_hyper_encoder16(&PairedHyperEncoderRequest {
        source_manifest,
        task_manifest,
        output_root: output_root.clone(),
        seed: 0x51a7_e001,
        config: HyperEncoderTrainingConfig::default(),
    })?;
    let bytes = serde_json::to_vec_pretty(&outcome.report)?;
    let report = output_root.join(format!("{}.report.json", outcome.report.pair_id));
    std::fs::write(&report, &bytes)?;
    println!("{}", String::from_utf8(bytes)?);
    Ok(())
}
