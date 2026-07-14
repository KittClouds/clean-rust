use phoenix_candle_baseline_trainer::{train_candle_temporal_rgcn16, CandleTemporalRgcnRequest};
use phoenix_graph_research::TemporalRgcnConfig;
use serde::Serialize;
use std::io::Write;
use std::path::PathBuf;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Output<'a> {
    model_manifest: String,
    model_weights: String,
    performance_certificate: String,
    report: &'a phoenix_candle_baseline_trainer::CandleTemporalRgcnReport,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let source_manifest = PathBuf::from(args.next().ok_or("missing source manifest")?);
    let task_manifest = PathBuf::from(args.next().ok_or("missing task manifest")?);
    let output_root = PathBuf::from(args.next().ok_or("missing output root")?);
    let mut config = TemporalRgcnConfig::default();
    if let Some(epochs) = args.next() {
        config.epochs = epochs.to_string_lossy().parse()?;
    }
    if let Some(seed) = args.next() {
        config.seed = seed.to_string_lossy().parse()?;
    }
    if args.next().is_some() {
        return Err(
            "usage: <source-manifest> <task-manifest> <output-root> [epochs] [seed]".into(),
        );
    }
    let outcome = train_candle_temporal_rgcn16(&CandleTemporalRgcnRequest {
        source_manifest,
        task_manifest,
        output_root,
        config,
    })?;
    let report_bytes = serde_json::to_vec_pretty(&outcome.report)?;
    let report_digest = blake3::hash(&report_bytes).to_hex();
    let report_path = outcome
        .artifact
        .manifest
        .parent()
        .ok_or("missing artifact directory")?
        .join(format!(
            "b3-{report_digest}.canonical-evaluator-throughput-report.json"
        ));
    let mut report_file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&report_path)?;
    report_file.write_all(&report_bytes)?;
    report_file.sync_all()?;
    println!(
        "{}",
        serde_json::to_string_pretty(&Output {
            model_manifest: outcome.artifact.manifest.display().to_string(),
            model_weights: outcome.artifact.weights.display().to_string(),
            performance_certificate: report_path.display().to_string(),
            report: &outcome.report,
        })?
    );
    Ok(())
}
