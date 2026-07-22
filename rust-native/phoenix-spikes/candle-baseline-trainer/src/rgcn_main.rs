use phoenix_candle_baseline_trainer::{
    train_candle_rgcn16, CandleRgcnConfig, CandleRgcnRequest, CandleTrainerConfig,
    CandleTrainerRequest,
};
use serde::Serialize;
use std::path::PathBuf;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Output<'a> {
    model_manifest: String,
    model_weights: String,
    report: &'a phoenix_candle_baseline_trainer::CandleRgcnReport,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1).map(PathBuf::from);
    let authority = CandleTrainerRequest {
        graph_manifest: required(&mut args, "frozen graph manifest")?,
        tensor_manifest: required(&mut args, "frozen tensor manifest")?,
        evaluation_protocol: required(&mut args, "evaluation protocol")?,
        topology_manifest: required(&mut args, "train-topology manifest")?,
        output_root: required(&mut args, "output directory")?,
        selected_repeat: required(&mut args, "selected repeat")?
            .to_string_lossy()
            .parse()?,
        config: CandleTrainerConfig::default(),
    };
    let request = CandleRgcnRequest {
        authority,
        baseline_ledger: required(&mut args, "baseline selection ledger")?,
        baseline_manifest: required(&mut args, "selected baseline manifest")?,
        config: CandleRgcnConfig::default(),
    };
    if args.next().is_some() {
        return Err("unexpected R-GCN trainer argument".into());
    }
    let outcome = train_candle_rgcn16(&request)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&Output {
            model_manifest: outcome.artifact.manifest.display().to_string(),
            model_weights: outcome.artifact.weights.display().to_string(),
            report: &outcome.report,
        })?
    );
    Ok(())
}

fn required(
    args: &mut impl Iterator<Item = PathBuf>,
    name: &'static str,
) -> Result<PathBuf, Box<dyn std::error::Error>> {
    args.next().ok_or_else(|| format!("missing {name}").into())
}
