use std::fs;
use std::path::PathBuf;
use std::time::Instant;

use phoenix_rel_post::{GlinerXMetadata, GlinerXModel, GlinerXPrediction};
use serde::Serialize;

#[derive(Debug, Clone)]
struct SmokeConfig {
    model_root: PathBuf,
    text: String,
    labels: Vec<String>,
    threshold: f32,
    json: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SmokeReport {
    ok: bool,
    load_ms: u64,
    run_ms: u64,
    model: GlinerXMetadata,
    predictions: Vec<GlinerXPrediction>,
}

fn main() -> Result<(), String> {
    let config = parse_args(&std::env::args().collect::<Vec<_>>())?;
    let label_refs = config.labels.iter().map(String::as_str).collect::<Vec<_>>();
    let load_started = Instant::now();
    let model = GlinerXModel::load(&config.model_root, config.threshold).map_err(|error| {
        format!(
            "failed to load GLiNER-X model {}: {error}",
            config.model_root.display()
        )
    })?;
    let load_ms = load_started.elapsed().as_millis() as u64;
    let run_started = Instant::now();
    let predictions = model
        .predict_texts(&[config.text.as_str()], &label_refs)
        .map_err(|error| format!("GLiNER-X inference failed: {error}"))?;
    let run_ms = run_started.elapsed().as_millis() as u64;
    let report = SmokeReport {
        ok: true,
        load_ms,
        run_ms,
        model: model.metadata().clone(),
        predictions,
    };
    if config.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&report)
                .map_err(|error| format!("failed to render JSON: {error}"))?
        );
    } else {
        println!("model: {}", report.model.model_path);
        println!("tokenizer: {}", report.model.tokenizer_path);
        println!("threshold: {:.3}", report.model.threshold);
        println!("loadMs: {}", report.load_ms);
        println!("runMs: {}", report.run_ms);
        println!("predictions: {}", report.predictions.len());
        for prediction in &report.predictions {
            println!(
                "- {} :: {} :: score={:.4} [{}..{}]",
                prediction.label,
                prediction.text,
                prediction.score,
                prediction.span_start,
                prediction.span_end
            );
        }
    }
    Ok(())
}

fn parse_args(args: &[String]) -> Result<SmokeConfig, String> {
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        return Err(usage());
    }
    let model_root = parse_required_path(args, "--model-root")?;
    let text = match (
        parse_string_arg(args, "--text"),
        parse_string_arg(args, "--text-file"),
    ) {
        (Some(value), _) => value,
        (None, Some(path)) => fs::read_to_string(path)
            .map_err(|error| format!("failed to read --text-file: {error}"))?,
        (None, None) => return Err(format!("--text or --text-file is required\n\n{}", usage())),
    };
    let labels = parse_string_arg(args, "--labels")
        .map(|value| {
            value
                .split(',')
                .map(str::trim)
                .filter(|label| !label.is_empty())
                .map(str::to_owned)
                .collect::<Vec<_>>()
        })
        .filter(|labels| !labels.is_empty())
        .unwrap_or_else(|| {
            vec![
                "person".to_owned(),
                "organization".to_owned(),
                "location".to_owned(),
            ]
        });
    Ok(SmokeConfig {
        model_root,
        text,
        labels,
        threshold: parse_f32_arg(args, "--threshold").unwrap_or(0.45),
        json: args.iter().any(|arg| arg == "--json"),
    })
}

fn parse_required_path(args: &[String], flag: &str) -> Result<PathBuf, String> {
    parse_string_arg(args, flag)
        .map(PathBuf::from)
        .ok_or_else(|| format!("{flag} is required\n\n{}", usage()))
}

fn parse_string_arg(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find(|window| window[0] == flag)
        .map(|window| window[1].clone())
}

fn parse_f32_arg(args: &[String], flag: &str) -> Option<f32> {
    parse_string_arg(args, flag).and_then(|value| value.parse::<f32>().ok())
}

fn usage() -> String {
    "Usage:\n  phoenix-gliner-x-smoke --model-root <DIR> (--text <TEXT> | --text-file <FILE>) [--labels person,organization,location] [--threshold 0.45] [--json]".to_owned()
}
