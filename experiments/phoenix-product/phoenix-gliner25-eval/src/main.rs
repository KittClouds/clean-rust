use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail};
use blake3::Hasher as Blake3;
use clap::{Parser, Subcommand, ValueEnum};
use gliner25_rs::{BoundaryConfig, BoundaryEngine, BoundaryParams, Precision, SchemaTask};
use hashbrown::HashSet;
use memmap2::Mmap;
use phoenix_gliner25_eval::chunk::{chapter_windows, model_word_count};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Parser)]
#[command(version, about = "Isolated GLiNER2.5 Base shadow evaluator")]
struct Cli {
    #[arg(long, env = "GLINER25_MODEL")]
    model: PathBuf,
    #[arg(long, env = "GLINER25_SCHEMA")]
    schema: PathBuf,
    #[arg(long, value_enum, default_value_t = PrecisionArg::Fp32)]
    precision: PrecisionArg,
    #[arg(long, default_value_t = 8)]
    threads: usize,
    #[command(subcommand)]
    command: Command,
}

#[derive(Clone, Copy, ValueEnum)]
enum PrecisionArg {
    Fp32,
    Fp16,
    Fp16Iobinding,
}

impl From<PrecisionArg> for Precision {
    fn from(value: PrecisionArg) -> Self {
        match value {
            PrecisionArg::Fp32 => Self::Fp32,
            PrecisionArg::Fp16 => Self::Fp16,
            PrecisionArg::Fp16Iobinding => Self::Fp16IoBinding,
        }
    }
}

#[derive(Subcommand)]
enum Command {
    Probe {
        #[arg(long)]
        text: String,
        #[arg(long, default_value_t = 0.5)]
        threshold: f32,
    },
    Bench {
        #[arg(long)]
        text: String,
        #[arg(long, default_value_t = 3)]
        warmup: usize,
        #[arg(long, default_value_t = 20)]
        runs: usize,
        #[arg(long, default_value_t = 0.5)]
        threshold: f32,
        #[arg(long)]
        output: Option<PathBuf>,
    },
    Parity {
        #[arg(long)]
        cases: PathBuf,
        #[arg(long)]
        output: PathBuf,
        #[arg(long, default_value_t = 0.5)]
        threshold: f32,
    },
    Census {
        #[arg(required = true)]
        documents: Vec<PathBuf>,
        #[arg(long)]
        output: PathBuf,
        #[arg(long, default_value_t = 384)]
        chunk_words: usize,
        #[arg(long, default_value_t = 64)]
        overlap_words: usize,
        #[arg(long, default_value_t = 0.5)]
        threshold: f32,
        #[arg(long)]
        max_chunks: Option<usize>,
    },
}

#[derive(Deserialize)]
struct Schema {
    schema_id: String,
    labels: Vec<String>,
}

#[derive(Deserialize)]
struct ParityCase {
    name: String,
    text: String,
    entities: Vec<String>,
}

#[derive(Serialize)]
struct MentionRow<'a> {
    kind: &'static str,
    document: &'a str,
    document_sha256: &'a str,
    schema_id: &'a str,
    chunk_index: u32,
    chapter: u32,
    start: usize,
    end: usize,
    label: &'a str,
    text: &'a str,
    score: f32,
}

#[derive(Serialize)]
struct CensusReceipt {
    contract: &'static str,
    model_dir: String,
    model_manifest_sha256: String,
    schema_id: String,
    schema_sha256: String,
    precision: String,
    chunk_words: usize,
    overlap_words: usize,
    documents: Vec<DocumentReceipt>,
    chunks: u64,
    model_words_processed: u64,
    mentions: u64,
    duplicate_mentions: u64,
    invalid_ranges: u64,
    elapsed_ms: f64,
    warm_words_per_second: f64,
    peak_working_set_bytes: usize,
    output_blake3: String,
    graph_publications: u8,
}

#[derive(Serialize)]
struct DocumentReceipt {
    path: String,
    sha256: String,
    bytes: usize,
    words: u64,
    chapters: u32,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let schema_bytes =
        fs::read(&cli.schema).with_context(|| format!("read {}", cli.schema.display()))?;
    let schema: Schema = serde_json::from_slice(&schema_bytes)?;
    validate_schema(&schema)?;
    let tasks = vec![SchemaTask::Entities(schema.labels.clone())];
    gliner25_rs::init("phoenix-gliner25-eval");
    let config = BoundaryConfig::new(&cli.model)
        .with_precision(cli.precision.into())
        .with_intra_threads(cli.threads);
    let load_started = Instant::now();
    let mut engine = BoundaryEngine::new(config)?;
    let engine_load_ms = load_started.elapsed().as_secs_f64() * 1e3;
    eprintln!("engine_load_ms={engine_load_ms:.3}");

    match cli.command {
        Command::Probe { text, threshold } => probe(&mut engine, &tasks, &text, threshold),
        Command::Bench {
            text,
            warmup,
            runs,
            threshold,
            output,
        } => bench(BenchArgs {
            engine: &mut engine,
            tasks: &tasks,
            text: &text,
            threshold,
            warmup,
            runs,
            engine_load_ms,
            output_path: output.as_deref(),
        }),
        Command::Parity {
            cases,
            output,
            threshold,
        } => parity(&mut engine, &cases, &output, threshold),
        Command::Census {
            documents,
            output,
            chunk_words,
            overlap_words,
            threshold,
            max_chunks,
        } => census(CensusArgs {
            engine: &mut engine,
            tasks: &tasks,
            schema: &schema,
            schema_bytes: &schema_bytes,
            model_dir: &cli.model,
            precision: cli.precision,
            documents: &documents,
            output: &output,
            chunk_words,
            overlap_words,
            threshold,
            max_chunks,
        }),
    }
}

fn parity(
    engine: &mut BoundaryEngine,
    cases_path: &Path,
    output_path: &Path,
    threshold: f32,
) -> Result<()> {
    let cases: Vec<ParityCase> = serde_json::from_slice(&fs::read(cases_path)?)?;
    let mut suite = Vec::with_capacity(cases.len());
    for case in cases {
        let tasks = vec![SchemaTask::Entities(case.entities)];
        let result = engine.extract_with(&case.text, &tasks, &params(threshold))?;
        let mut mentions: Vec<_> = result
            .mentions
            .iter()
            .map(|mention| {
                serde_json::json!({
                    "text": mention.text,
                    "label": mention.field,
                    "start": mention.char_start,
                    "end": mention.char_end,
                    "score": (mention.score * 1e4).round() / 1e4,
                })
            })
            .collect();
        mentions.sort_by(|a, b| {
            (a["start"].as_u64(), a["end"].as_u64(), a["label"].as_str()).cmp(&(
                b["start"].as_u64(),
                b["end"].as_u64(),
                b["label"].as_str(),
            ))
        });
        suite.push(serde_json::json!({"name": case.name, "entities": mentions}));
    }
    if let Some(parent) = output_path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(output_path, serde_json::to_vec_pretty(&suite)?)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "contract": "phoenix-gliner25-parity-candidate-v1",
            "cases": suite.len(),
            "output": output_path,
            "output_sha256": sha256_file(output_path)?,
            "graph_publications": 0,
        }))?
    );
    Ok(())
}

fn validate_schema(schema: &Schema) -> Result<()> {
    if schema.schema_id.trim().is_empty() || schema.labels.is_empty() {
        bail!("schema_id and labels must be non-empty");
    }
    let mut seen = HashSet::with_capacity(schema.labels.len());
    for label in &schema.labels {
        if label.trim().is_empty() || !seen.insert(label.to_ascii_lowercase()) {
            bail!("blank or duplicate schema label: {label:?}");
        }
    }
    Ok(())
}

fn params(threshold: f32) -> BoundaryParams {
    BoundaryParams {
        threshold,
        ..Default::default()
    }
}

fn probe(
    engine: &mut BoundaryEngine,
    tasks: &[SchemaTask],
    text: &str,
    threshold: f32,
) -> Result<()> {
    let started = Instant::now();
    let output = engine.extract_with(text, tasks, &params(threshold))?;
    let elapsed = started.elapsed();
    let rows: Vec<_> = output.mentions.iter().map(|m| serde_json::json!({
        "text": m.text, "label": m.field, "start": m.char_start, "end": m.char_end,
        "score": m.score, "range_valid": text.get(m.char_start..m.char_end) == Some(m.text.as_str())
    })).collect();
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "elapsed_ms": elapsed.as_secs_f64() * 1e3, "working_set_bytes": working_set_bytes(),
            "mentions": rows
        }))?
    );
    Ok(())
}

struct BenchArgs<'a> {
    engine: &'a mut BoundaryEngine,
    tasks: &'a [SchemaTask],
    text: &'a str,
    threshold: f32,
    warmup: usize,
    runs: usize,
    engine_load_ms: f64,
    output_path: Option<&'a Path>,
}

fn bench(args: BenchArgs<'_>) -> Result<()> {
    if args.runs == 0 {
        bail!("runs must be non-zero");
    }
    for _ in 0..args.warmup {
        let _ = args
            .engine
            .extract_with(args.text, args.tasks, &params(args.threshold))?;
    }
    let working_set_before = working_set_bytes();
    let mut peak_working_set = working_set_before;
    let mut samples = Vec::with_capacity(args.runs);
    for _ in 0..args.runs {
        let started = Instant::now();
        let _ = args
            .engine
            .extract_with(args.text, args.tasks, &params(args.threshold))?;
        samples.push(started.elapsed());
        peak_working_set = peak_working_set.max(working_set_bytes());
    }
    samples.sort_unstable();
    let working_set_after = working_set_bytes();
    let receipt = serde_json::json!({
        "contract": "phoenix-gliner25-benchmark-v1",
        "device_intent": std::env::var("GLINER2_DEVICE").unwrap_or_else(|_| "auto".into()),
        "engine_load_ms": args.engine_load_ms,
        "runs": args.runs,
        "warmup": args.warmup,
        "whitespace_words": args.text.split_whitespace().count(),
        "model_words": model_word_count(args.text),
        "p50_ms": millis(percentile(&samples, 0.50)),
        "p95_ms": millis(percentile(&samples, 0.95)),
        "p99_ms": millis(percentile(&samples, 0.99)),
        "working_set_before_bytes": working_set_before,
        "working_set_after_bytes": working_set_after,
        "working_set_delta_bytes": working_set_after as i128 - working_set_before as i128,
        "peak_working_set_bytes": peak_working_set,
        "graph_publications": 0,
    });
    if let Some(path) = args.output_path {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(path, serde_json::to_vec_pretty(&receipt)?)?;
    }
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    Ok(())
}

struct CensusArgs<'a> {
    engine: &'a mut BoundaryEngine,
    tasks: &'a [SchemaTask],
    schema: &'a Schema,
    schema_bytes: &'a [u8],
    model_dir: &'a Path,
    precision: PrecisionArg,
    documents: &'a [PathBuf],
    output: &'a Path,
    chunk_words: usize,
    overlap_words: usize,
    threshold: f32,
    max_chunks: Option<usize>,
}

fn census(args: CensusArgs<'_>) -> Result<()> {
    if args.overlap_words >= args.chunk_words {
        bail!("overlap must be smaller than chunk size");
    }
    if let Some(parent) = args.output.parent() {
        fs::create_dir_all(parent)?;
    }
    let file = File::create(args.output)?;
    let mut writer = BufWriter::with_capacity(1 << 20, file);
    let mut output_hash = Blake3::new();
    let mut docs = Vec::with_capacity(args.documents.len());
    let mut seen = HashSet::new();
    let mut chunks_done = 0_u64;
    let mut words_done = 0_u64;
    let mut mention_count = 0_u64;
    let mut duplicates = 0_u64;
    let mut invalid = 0_u64;
    let mut peak = working_set_bytes();
    let started = Instant::now();

    'documents: for path in args.documents {
        let source = MappedDocument::open(path)?;
        let text = source.text()?;
        let doc_hash = sha256_hex(source.bytes());
        let windows = chapter_windows(text, args.chunk_words, args.overlap_words);
        let chapters = windows.last().map_or(0, |c| c.chapter + 1);
        docs.push(DocumentReceipt {
            path: path.display().to_string(),
            sha256: doc_hash.clone(),
            bytes: source.bytes().len(),
            words: text.split_whitespace().count() as u64,
            chapters,
        });
        for chunk in windows {
            if args
                .max_chunks
                .is_some_and(|limit| chunks_done as usize >= limit)
            {
                break 'documents;
            }
            let chunk_text = chunk.text(text);
            words_done += (chunk.word_end - chunk.word_start) as u64;
            let result =
                args.engine
                    .extract_with(chunk_text, args.tasks, &params(args.threshold))?;
            let mut mentions = result.mentions;
            mentions.sort_by(|a, b| {
                (a.char_start, a.char_end, &a.field).cmp(&(b.char_start, b.char_end, &b.field))
            });
            for mention in &mentions {
                let start = chunk.byte_start + mention.char_start;
                let end = chunk.byte_start + mention.char_end;
                let valid = text.get(start..end) == Some(mention.text.as_str());
                if !valid {
                    invalid += 1;
                    continue;
                }
                if !seen.insert((doc_hash.clone(), start, end, mention.field.clone())) {
                    duplicates += 1;
                    continue;
                }
                let row = MentionRow {
                    kind: "candidate_mention",
                    document: &path.to_string_lossy(),
                    document_sha256: &doc_hash,
                    schema_id: &args.schema.schema_id,
                    chunk_index: chunk.index,
                    chapter: chunk.chapter,
                    start,
                    end,
                    label: &mention.field,
                    text: &mention.text,
                    score: mention.score,
                };
                let mut line = serde_json::to_vec(&row)?;
                line.push(b'\n');
                output_hash.update(&line);
                writer.write_all(&line)?;
                mention_count += 1;
            }
            chunks_done += 1;
            peak = peak.max(working_set_bytes());
            if chunks_done.is_multiple_of(50) {
                eprintln!(
                    "progress chunks={} mentions={} invalid_ranges={} elapsed_s={:.1}",
                    chunks_done,
                    mention_count,
                    invalid,
                    started.elapsed().as_secs_f64()
                );
            }
        }
    }
    writer.flush()?;
    let elapsed = started.elapsed();
    let receipt = CensusReceipt {
        contract: "phoenix-gliner25-shadow-census-v1",
        model_dir: args.model_dir.display().to_string(),
        model_manifest_sha256: sha256_file(&args.model_dir.join("boundary_manifest.json"))?,
        schema_id: args.schema.schema_id.clone(),
        schema_sha256: sha256_hex(args.schema_bytes),
        precision: precision_name(args.precision).to_string(),
        chunk_words: args.chunk_words,
        overlap_words: args.overlap_words,
        documents: docs,
        chunks: chunks_done,
        model_words_processed: words_done,
        mentions: mention_count,
        duplicate_mentions: duplicates,
        invalid_ranges: invalid,
        elapsed_ms: elapsed.as_secs_f64() * 1e3,
        warm_words_per_second: words_done as f64 / elapsed.as_secs_f64().max(f64::EPSILON),
        peak_working_set_bytes: peak,
        output_blake3: output_hash.finalize().to_hex().to_string(),
        graph_publications: 0,
    };
    let receipt_path = args.output.with_extension("receipt.json");
    fs::write(&receipt_path, serde_json::to_vec_pretty(&receipt)?)?;
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    Ok(())
}

struct MappedDocument {
    _file: File,
    map: Mmap,
}
impl MappedDocument {
    fn open(path: &Path) -> Result<Self> {
        let file = File::open(path)?;
        let map = unsafe { Mmap::map(&file)? };
        Ok(Self { _file: file, map })
    }
    fn bytes(&self) -> &[u8] {
        &self.map
    }
    fn text(&self) -> Result<&str> {
        std::str::from_utf8(&self.map).context("document is not UTF-8")
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn sha256_file(path: &Path) -> Result<String> {
    Ok(sha256_hex(&fs::read(path)?))
}
fn millis(value: Duration) -> f64 {
    value.as_secs_f64() * 1e3
}
fn percentile(values: &[Duration], q: f64) -> Duration {
    values[((values.len() - 1) as f64 * q).round() as usize]
}
fn precision_name(value: PrecisionArg) -> &'static str {
    match value {
        PrecisionArg::Fp32 => "fp32",
        PrecisionArg::Fp16 => "fp16",
        PrecisionArg::Fp16Iobinding => "fp16_iobinding",
    }
}

fn working_set_bytes() -> usize {
    use windows_sys::Win32::System::ProcessStatus::{
        GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS,
    };
    use windows_sys::Win32::System::Threading::GetCurrentProcess;
    let mut counters = unsafe { std::mem::zeroed::<PROCESS_MEMORY_COUNTERS>() };
    counters.cb = std::mem::size_of::<PROCESS_MEMORY_COUNTERS>() as u32;
    let ok = unsafe { GetProcessMemoryInfo(GetCurrentProcess(), &mut counters, counters.cb) };
    if ok == 0 { 0 } else { counters.WorkingSetSize }
}
