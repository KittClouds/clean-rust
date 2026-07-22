use phoenix_candle_baseline_trainer::{train_temporal_compgcn16, TemporalCompgcnRequest};
use phoenix_graph_research::{TemporalCompgcnConfig, TemporalComposition, TemporalRelationUpdate};
use serde::Serialize;
use std::io::Write;
use std::path::PathBuf;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Output<'a> {
    model_manifest: String,
    model_weights: String,
    performance_certificate: String,
    report: &'a phoenix_candle_baseline_trainer::TemporalCompgcnReport,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let source_manifest = PathBuf::from(args.next().ok_or("missing source manifest")?);
    let task_manifest = PathBuf::from(args.next().ok_or("missing task manifest")?);
    let control_manifest = PathBuf::from(args.next().ok_or("missing R-GCN control manifest")?);
    let output_root = PathBuf::from(args.next().ok_or("missing output root")?);
    let mut config = TemporalCompgcnConfig::default();
    if let Some(epochs) = args.next() {
        config.base.epochs = epochs.to_string_lossy().parse()?;
    }
    if let Some(composition) = args.next() {
        config.composition = match composition.to_string_lossy().as_ref() {
            "mult" => TemporalComposition::Multiply,
            "sub" => TemporalComposition::Subtract,
            "corr" => TemporalComposition::CircularCorrelation,
            _ => return Err("composition must be mult, sub, or corr".into()),
        };
    }
    if let Some(update) = args.next() {
        config.relation_update = match update.to_string_lossy().as_ref() {
            "joint" => TemporalRelationUpdate::JointLinear,
            "frozen" => TemporalRelationUpdate::Frozen,
            _ => return Err("relation update must be joint or frozen".into()),
        };
    }
    if let Some(learning_rate) = args.next() {
        config.base.learning_rate = learning_rate.to_string_lossy().parse()?;
    }
    if let Some(seed) = args.next() {
        config.base.seed = seed.to_string_lossy().parse()?;
    }
    if args.next().is_some() {
        return Err("usage: <source> <task> <rgcn-control> <output> [epochs] [mult|sub|corr] [joint|frozen] [learning-rate] [seed]".into());
    }
    let outcome = train_temporal_compgcn16(&TemporalCompgcnRequest {
        source_manifest,
        task_manifest,
        control_manifest,
        output_root,
        config,
    })?;
    let report_bytes = serde_json::to_vec_pretty(&outcome.report)?;
    let report_path = outcome
        .artifact
        .manifest
        .parent()
        .ok_or("missing artifact directory")?
        .join(format!(
            "b3-{}.temporal-compgcn-report.json",
            blake3::hash(&report_bytes).to_hex()
        ));
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&report_path)?;
    file.write_all(&report_bytes)?;
    file.sync_all()?;
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
