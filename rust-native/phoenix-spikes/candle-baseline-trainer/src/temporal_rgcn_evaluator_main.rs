use phoenix_candle_baseline_trainer::{
    evaluate_temporal_rgcn_restart, TemporalRgcnEvaluatorRequest,
};
use serde::Serialize;
use std::io::Write;
use std::path::PathBuf;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Output<'a> {
    performance_certificate: String,
    report: &'a phoenix_candle_baseline_trainer::TemporalRgcnEvaluatorReport,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let source_manifest = PathBuf::from(args.next().ok_or("missing source manifest")?);
    let task_manifest = PathBuf::from(args.next().ok_or("missing task manifest")?);
    let model_manifest = PathBuf::from(args.next().ok_or("missing model manifest")?);
    let output_root = PathBuf::from(args.next().ok_or("missing output root")?);
    if args.next().is_some() {
        return Err(
            "usage: <source-manifest> <task-manifest> <model-manifest> <output-root>".into(),
        );
    }
    let report = evaluate_temporal_rgcn_restart(&TemporalRgcnEvaluatorRequest {
        source_manifest,
        task_manifest,
        model_manifest,
    })?;
    let report_bytes = serde_json::to_vec_pretty(&report)?;
    let report_digest = blake3::hash(&report_bytes).to_hex();
    std::fs::create_dir_all(&output_root)?;
    let report_path = output_root.join(format!(
        "b3-{report_digest}.canonical-evaluator-restart-report.json"
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
            performance_certificate: report_path.display().to_string(),
            report: &report,
        })?
    );
    Ok(())
}
