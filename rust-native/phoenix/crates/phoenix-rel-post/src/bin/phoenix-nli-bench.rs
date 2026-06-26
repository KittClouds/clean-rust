use std::cmp::Ordering;
use std::path::PathBuf;
use std::time::Instant;

use phoenix_rel_post::{build_relation_hypotheses, NliModel, NliPairJudgment};
use serde::Serialize;

#[derive(Debug, Clone)]
struct BenchConfig {
    model_root: PathBuf,
    text: String,
    source: String,
    target: String,
    edge_type: String,
    warmups: usize,
    iterations: usize,
    json: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct BenchReport {
    ok: bool,
    model_path: String,
    tokenizer_path: String,
    ort_execution_provider_preference: String,
    ort_dylib_path: Option<String>,
    max_length: usize,
    label_order: LabelOrderReport,
    warmups: usize,
    iterations: usize,
    load_ms: u64,
    min_ms: f64,
    mean_ms: f64,
    median_ms: f64,
    p95_ms: f64,
    max_ms: f64,
    runs_ms: Vec<f64>,
    last_judgment: NliPairJudgment,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct LabelOrderReport {
    contradiction_idx: usize,
    entailment_idx: usize,
    neutral_idx: usize,
}

#[derive(Debug)]
struct Stats {
    min: f64,
    mean: f64,
    median: f64,
    p95: f64,
    max: f64,
}

fn main() -> Result<(), String> {
    let config = parse_args(&std::env::args().collect::<Vec<_>>())?;
    let load_started = Instant::now();
    let model = NliModel::load(&config.model_root)
        .map_err(|error| format!("failed to load NLI model: {error}"))?;
    let load_ms = load_started.elapsed().as_millis() as u64;
    let forward = build_relation_hypotheses(&config.edge_type, &config.source, &config.target);
    let reverse = build_relation_hypotheses(&config.edge_type, &config.target, &config.source);

    let mut last_judgment = None;
    for _ in 0..config.warmups {
        last_judgment = Some(
            model
                .judge_relation(&config.text, &forward, &reverse)
                .map_err(|error| format!("warmup failed: {error}"))?,
        );
    }

    let mut runs_ms = Vec::with_capacity(config.iterations);
    for _ in 0..config.iterations {
        let started = Instant::now();
        last_judgment = Some(
            model
                .judge_relation(&config.text, &forward, &reverse)
                .map_err(|error| format!("inference failed: {error}"))?,
        );
        runs_ms.push(started.elapsed().as_secs_f64() * 1000.0);
    }

    let stats = stats(&runs_ms)?;
    let metadata = model.metadata();
    let report = BenchReport {
        ok: true,
        model_path: metadata.model_path.clone(),
        tokenizer_path: metadata.tokenizer_path.clone(),
        ort_execution_provider_preference: metadata.ort_execution_provider_preference.clone(),
        ort_dylib_path: metadata.ort_dylib_path.clone(),
        max_length: metadata.max_length,
        label_order: LabelOrderReport {
            contradiction_idx: metadata.contradiction_idx,
            entailment_idx: metadata.entailment_idx,
            neutral_idx: metadata.neutral_idx,
        },
        warmups: config.warmups,
        iterations: config.iterations,
        load_ms,
        min_ms: stats.min,
        mean_ms: stats.mean,
        median_ms: stats.median,
        p95_ms: stats.p95,
        max_ms: stats.max,
        runs_ms,
        last_judgment: last_judgment.ok_or_else(|| "no benchmark iterations ran".to_owned())?,
    };

    if config.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&report)
                .map_err(|error| format!("failed to render JSON: {error}"))?
        );
    } else {
        println!("model: {}", report.model_path);
        println!("tokenizer: {}", report.tokenizer_path);
        println!(
            "ortEpPreference: {}",
            report.ort_execution_provider_preference
        );
        println!(
            "ortDylib: {}",
            report.ort_dylib_path.as_deref().unwrap_or("<unset>")
        );
        println!("maxLength: {}", report.max_length);
        println!(
            "labelOrder: entailment={} neutral={} contradiction={}",
            report.label_order.entailment_idx,
            report.label_order.neutral_idx,
            report.label_order.contradiction_idx
        );
        println!("loadMs: {}", report.load_ms);
        println!(
            "runs: n={} warmups={} min={:.3} mean={:.3} median={:.3} p95={:.3} max={:.3}",
            report.iterations,
            report.warmups,
            report.min_ms,
            report.mean_ms,
            report.median_ms,
            report.p95_ms,
            report.max_ms
        );
        println!("usedReverse: {}", report.last_judgment.used_reverse);
        println!(
            "forward: entailment={:.3} neutral={:.3} contradiction={:.3}",
            report.last_judgment.forward.entailment,
            report.last_judgment.forward.neutral,
            report.last_judgment.forward.contradiction
        );
    }
    Ok(())
}

fn stats(values: &[f64]) -> Result<Stats, String> {
    if values.is_empty() {
        return Err("--iterations must be greater than zero".to_owned());
    }
    let mut sorted = values.to_vec();
    sorted.sort_by(|left, right| left.partial_cmp(right).unwrap_or(Ordering::Equal));
    let mean = sorted.iter().sum::<f64>() / sorted.len() as f64;
    Ok(Stats {
        min: sorted[0],
        mean,
        median: percentile(&sorted, 0.50),
        p95: percentile(&sorted, 0.95),
        max: *sorted.last().unwrap_or(&sorted[0]),
    })
}

fn percentile(sorted: &[f64], quantile: f64) -> f64 {
    let index = ((sorted.len() - 1) as f64 * quantile).round() as usize;
    sorted[index.min(sorted.len() - 1)]
}

fn parse_args(args: &[String]) -> Result<BenchConfig, String> {
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        return Err(usage());
    }
    let model_root = parse_string_arg(args, "--model-root")
        .map(PathBuf::from)
        .ok_or_else(|| format!("--model-root is required\n\n{}", usage()))?;
    let text = parse_string_arg(args, "--text").unwrap_or_else(default_text);
    let source = parse_string_arg(args, "--source").unwrap_or_else(|| "Alice".to_owned());
    let target = parse_string_arg(args, "--target").unwrap_or_else(|| "Dynamis".to_owned());
    let edge_type = parse_string_arg(args, "--edge-type").unwrap_or_else(|| "works_for".to_owned());
    let warmups = parse_usize_arg(args, "--warmups").unwrap_or(2);
    let iterations = parse_usize_arg(args, "--iterations").unwrap_or(5);
    if iterations == 0 {
        return Err("--iterations must be greater than zero".to_owned());
    }
    Ok(BenchConfig {
        model_root,
        text,
        source,
        target,
        edge_type,
        warmups,
        iterations,
        json: args.iter().any(|arg| arg == "--json"),
    })
}

fn parse_string_arg(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find(|window| window[0] == flag)
        .map(|window| window[1].clone())
}

fn parse_usize_arg(args: &[String], flag: &str) -> Option<usize> {
    parse_string_arg(args, flag).and_then(|value| value.parse::<usize>().ok())
}

fn default_text() -> String {
    "Alice works for Dynamis.".to_owned()
}

fn usage() -> String {
    [
        "Usage:",
        "  phoenix-nli-bench --model-root <DIR> [options]",
        "",
        "Options:",
        "  --text <TEXT>",
        "  --source <NAME>         Default: Alice",
        "  --target <NAME>         Default: Dynamis",
        "  --edge-type <TYPE>      Default: works_for",
        "  --warmups <N>           Default: 2",
        "  --iterations <N>        Default: 5",
        "  --json",
    ]
    .join("\n")
}
