use std::fs::File;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail};
use clap::Parser;
use gliner25_rs::overlap::OverlapPolicy;
use gliner25_rs::processor::SchemaTask;
use memmap2::Mmap;
use phoenix_gliner25_eval::chunk::{chapter_windows, model_word_count};
use phoenix_gliner25_eval::features::{
    AttributeGroupSpec, ClassificationTaskSpec, ConstraintExpr, FeatureEngine, JointConfig,
    JointEntitySpec, JointRelationSpec, JointSchemaSpec,
};
use serde::Serialize;

#[derive(Parser)]
struct Args {
    #[arg(long)]
    model: PathBuf,
    #[arg(long)]
    document: PathBuf,
    #[arg(long, default_value_t = 8)]
    threads: usize,
    #[arg(long, default_value_t = 270)]
    window_words: usize,
    #[arg(long, default_value_t = 384)]
    long_chunk_words: usize,
    #[arg(long, default_value_t = 64)]
    long_overlap_words: usize,
    #[arg(long, default_value_t = 1)]
    warmup: usize,
    #[arg(long, default_value_t = 5)]
    runs: usize,
    #[arg(long)]
    disable_explicit_tiers: bool,
    #[arg(long)]
    output: PathBuf,
}

#[derive(Serialize)]
struct BenchRow {
    feature: &'static str,
    runs: usize,
    warmup: usize,
    stable_output_count: usize,
    p50_ms: f64,
    p95_ms: f64,
    p99_ms: f64,
    working_set_before_bytes: usize,
    working_set_after_bytes: usize,
    peak_working_set_bytes: usize,
}

fn bench(
    feature: &'static str,
    warmup: usize,
    runs: usize,
    mut operation: impl FnMut() -> Result<usize>,
) -> Result<BenchRow> {
    if runs == 0 {
        bail!("runs must be positive");
    }
    for _ in 0..warmup {
        operation()?;
    }
    let before = working_set_bytes();
    let mut peak = before;
    let mut samples = Vec::with_capacity(runs);
    let mut expected_count = None;
    for _ in 0..runs {
        let started = Instant::now();
        let count = operation()?;
        samples.push(started.elapsed());
        peak = peak.max(working_set_bytes());
        match expected_count {
            None => expected_count = Some(count),
            Some(expected) if expected != count => {
                bail!("{feature} output count changed from {expected} to {count}")
            }
            _ => {}
        }
    }
    samples.sort_unstable();
    Ok(BenchRow {
        feature,
        runs,
        warmup,
        stable_output_count: expected_count.unwrap_or(0),
        p50_ms: millis(percentile(&samples, 0.50)),
        p95_ms: millis(percentile(&samples, 0.95)),
        p99_ms: millis(percentile(&samples, 0.99)),
        working_set_before_bytes: before,
        working_set_after_bytes: working_set_bytes(),
        peak_working_set_bytes: peak,
    })
}

fn main() -> Result<()> {
    let args = Args::parse();
    let file =
        File::open(&args.document).with_context(|| format!("open {}", args.document.display()))?;
    let mapped = unsafe { Mmap::map(&file)? };
    let source = std::str::from_utf8(&mapped)?;
    let short_window = chapter_windows(source, args.window_words, 0)
        .into_iter()
        .next()
        .context("document has no benchmark window")?;
    let long_window = chapter_windows(source, 900, 0)
        .into_iter()
        .next()
        .context("document has no long benchmark window")?;
    let short_text = &source[short_window.byte_start..short_window.byte_end];
    let long_text = &source[long_window.byte_start..long_window.byte_end];

    gliner25_rs::init("phoenix-gliner25-five-surface-bench");
    let load_started = Instant::now();
    let mut engine = FeatureEngine::new(&args.model, args.threads)?;
    engine.set_tiered_explicit(!args.disable_explicit_tiers);
    let engine_load_ms = load_started.elapsed().as_secs_f64() * 1_000.0;
    let entity_labels = vec![
        "person".into(),
        "location".into(),
        "organization".into(),
        "creature".into(),
        "item".into(),
        "concept".into(),
        "event".into(),
        "group".into(),
        "temporal expression".into(),
        "causal trigger".into(),
        "memory".into(),
    ];

    let mut rows = Vec::new();
    rows.push(bench("long_context", args.warmup, args.runs, || {
        Ok(engine
            .extract_entities_long(
                long_text,
                &entity_labels,
                args.long_chunk_words,
                args.long_overlap_words,
                0.5,
            )?
            .len())
    })?);
    rows.push(bench("wide_span_entities", args.warmup, args.runs, || {
        let trace = engine.trace(short_text, &[SchemaTask::Entities(entity_labels.clone())])?;
        Ok(engine
            .decode_mentions(&trace, 0.5, &entity_labels, OverlapPolicy::Flat)
            .len())
    })?);
    rows.push(bench("span_attributes", args.warmup, args.runs, || {
        Ok(engine
            .extract_attributed(
                short_text,
                &[
                    "person".into(),
                    "location".into(),
                    "organization".into(),
                    "event".into(),
                ],
                &[AttributeGroupSpec {
                    name: "salience".into(),
                    labels: vec!["central".into(), "supporting".into(), "incidental".into()],
                    applies_to: None,
                    multi_label: false,
                    threshold: 0.5,
                    qualify_labels: true,
                }],
                0.5,
            )?
            .len())
    })?);
    let classification_tasks = vec![
        ClassificationTaskSpec {
            name: "scene_mode".into(),
            labels: vec!["action".into(), "dialogue".into(), "exposition".into()],
            multi_label: false,
            min_labels: 1,
            max_labels: Some(1),
            ordered: false,
            threshold: 0.5,
            temperature: 1.0,
            default: None,
        },
        ClassificationTaskSpec {
            name: "signals".into(),
            labels: vec!["temporal".into(), "causal".into(), "memory".into()],
            multi_label: true,
            min_labels: 0,
            max_labels: None,
            ordered: false,
            threshold: 0.5,
            temperature: 1.0,
            default: None,
        },
    ];
    rows.push(bench(
        "constrained_classification",
        args.warmup,
        args.runs,
        || {
            Ok(engine
                .classify_constrained(
                    short_text,
                    &classification_tasks,
                    &[ConstraintExpr::Excludes {
                        left: Box::new(ConstraintExpr::Label {
                            task: "scene_mode".into(),
                            label: "action".into(),
                        }),
                        right: Box::new(ConstraintExpr::Label {
                            task: "scene_mode".into(),
                            label: "exposition".into(),
                        }),
                    }],
                )?
                .tasks
                .len())
        },
    )?);
    let joint_schema = JointSchemaSpec {
        entities: vec![
            JointEntitySpec {
                name: "person".into(),
                threshold: 0.5,
                candidate_threshold: 0.05,
                allow_nested: false,
            },
            JointEntitySpec {
                name: "organization".into(),
                threshold: 0.5,
                candidate_threshold: 0.05,
                allow_nested: false,
            },
            JointEntitySpec {
                name: "location".into(),
                threshold: 0.5,
                candidate_threshold: 0.05,
                allow_nested: false,
            },
        ],
        relations: vec![
            JointRelationSpec {
                name: "affiliated_with".into(),
                head: vec!["person".into()],
                tail: vec!["organization".into()],
                threshold: 0.5,
                candidate_threshold: 0.05,
                allow_self: false,
                max_per_head: Some(1),
                max_per_tail: None,
            },
            JointRelationSpec {
                name: "located_in".into(),
                head: vec!["organization".into()],
                tail: vec!["location".into()],
                threshold: 0.5,
                candidate_threshold: 0.05,
                allow_self: false,
                max_per_head: Some(1),
                max_per_tail: None,
            },
        ],
        no_self_loops: true,
    };
    rows.push(bench(
        "joint_information_extraction",
        args.warmup,
        args.runs,
        || {
            let result =
                engine.extract_joint(short_text, &joint_schema, &JointConfig::default())?;
            Ok(result.entities.len() + result.relations.len())
        },
    )?);

    let receipt = serde_json::json!({
        "contract": "phoenix-gliner25-five-surface-novel-benchmark-v1",
        "model": args.model,
        "document": args.document,
        "document_bytes": mapped.len(),
        "short_window": {
            "bytes": short_text.len(),
            "whitespace_words": short_text.split_whitespace().count(),
            "model_words": model_word_count(short_text),
        },
        "long_window": {
            "bytes": long_text.len(),
            "whitespace_words": long_text.split_whitespace().count(),
            "model_words": model_word_count(long_text),
            "chunk_words": args.long_chunk_words,
            "overlap_words": args.long_overlap_words,
        },
        "engine_load_ms": engine_load_ms,
        "tiered_explicit": !args.disable_explicit_tiers,
        "features": rows,
        "graph_publications": 0,
    });
    if let Some(parent) = args.output.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&args.output, serde_json::to_vec_pretty(&receipt)?)?;
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    Ok(())
}

fn percentile(values: &[Duration], quantile: f64) -> Duration {
    let index = ((values.len() - 1) as f64 * quantile).ceil() as usize;
    values[index]
}

fn millis(value: Duration) -> f64 {
    value.as_secs_f64() * 1_000.0
}

#[cfg(windows)]
fn working_set_bytes() -> usize {
    use std::mem::size_of;
    use windows_sys::Win32::System::ProcessStatus::{
        GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS,
    };
    use windows_sys::Win32::System::Threading::GetCurrentProcess;
    let mut counters: PROCESS_MEMORY_COUNTERS = unsafe { std::mem::zeroed() };
    counters.cb = size_of::<PROCESS_MEMORY_COUNTERS>() as u32;
    let ok = unsafe {
        GetProcessMemoryInfo(
            GetCurrentProcess(),
            &mut counters,
            size_of::<PROCESS_MEMORY_COUNTERS>() as u32,
        )
    };
    if ok == 0 { 0 } else { counters.WorkingSetSize }
}

#[cfg(not(windows))]
fn working_set_bytes() -> usize {
    0
}
