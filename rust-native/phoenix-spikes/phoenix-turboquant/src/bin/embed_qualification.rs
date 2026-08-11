use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{bail, Context, Result};
use phoenix_chunker_native::{build_chunks, ChunkerConfig};
use phoenix_embed::{
    default_ort_dylib_path, workspace_root, EmbeddingBatchOrder, EmbeddingRunTelemetry,
    OrtTextEmbedConfig, OrtTextEmbedder, TextEmbeddingBatch,
};
use serde::Serialize;
use sha2::{Digest, Sha256};

#[path = "frozen_gate/input.rs"]
mod input;

const DEFAULT_BUNDLE: &str =
    r"C:\benchmarks\phoenix-qps-v3-20260804\semantic-review-bundles-confirmation-v1-1751.json";
const DEFAULT_OUTPUT: &str = r"D:\phoenix-turboquant-gate-20260811\embedding-qualification-v1.json";
const GEMMA_ROOT: &str = r"D:\phoenix-models\embeddinggemma-300m-ONNX";
const JINA_ROOT: &str = r"D:\phoenix-models\jina-embeddings-v5-text-nano-retrieval";
const CHUNK_SIZE: usize = 1_840;
const CHUNK_OVERLAP: usize = 256;
const DOCUMENT_SAMPLE_ROWS: usize = 24;
const QUERY_SAMPLE_ROWS: usize = 32;
const BATCH_SIZE: usize = 8;

#[derive(Clone)]
struct SampleText {
    stable_id: String,
    text: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Receipt {
    contract: &'static str,
    source: SourceReceipt,
    chunking: ChunkReceipt,
    runtime: RuntimeReceipt,
    models: Vec<ModelReceipt>,
    gates: GateReceipt,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SourceReceipt {
    bundle_path: String,
    bundle_sha256: String,
    bundle_blake3: String,
    source_contract: String,
    source_packet: input::BoundFile,
    phase_5: input::BoundFile,
    dataset_counts: std::collections::BTreeMap<String, usize>,
    candidate_documents: usize,
    queries: usize,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ChunkReceipt {
    implementation: &'static str,
    chunk_size: usize,
    overlap: usize,
    total_chunks: usize,
    sample_rows: usize,
    sample_char_p50: usize,
    sample_char_p95: usize,
    sample_char_max: usize,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeReceipt {
    ort_dylib_path: String,
    ort_dylib_sha256: String,
    batch_size: usize,
    document_sample_rows: usize,
    query_sample_rows: usize,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ModelReceipt {
    model: &'static str,
    model_root: String,
    document: LaneReceipt,
    query: LaneReceipt,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LaneReceipt {
    runner: RunnerReceipt,
    assets: Vec<FileReceipt>,
    rows: usize,
    input_order_ms: f64,
    length_bucketed_ms: f64,
    speedup: f64,
    input_order: TelemetryReceipt,
    length_bucketed: TelemetryReceipt,
    max_abs_difference: f32,
    minimum_cosine: f32,
    input_output_hash: String,
    length_bucketed_output_hash: String,
    gates: LaneGateReceipt,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RunnerReceipt {
    model_path: String,
    max_length: usize,
    intra_threads: usize,
    inter_threads: usize,
    parallel_execution: bool,
    configured_batch_order: &'static str,
    execution_provider: &'static str,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct FileReceipt {
    path: String,
    bytes: u64,
    sha256: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct TelemetryReceipt {
    order: &'static str,
    batches: usize,
    useful_tokens: u64,
    padded_tokens: u64,
    token_padding_ratio: f64,
    useful_attention_cells: u64,
    padded_attention_cells: u64,
    attention_padding_ratio: f64,
    max_sequence_tokens: usize,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LaneGateReceipt {
    canonical_order_restored: bool,
    cosine_at_least_0_99999: bool,
    max_abs_at_most_0_0001: bool,
    padded_tokens_non_increasing: bool,
    padded_attention_non_increasing: bool,
    qualified: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct GateReceipt {
    gemma_document_qualified: bool,
    gemma_query_qualified: bool,
    jina_document_qualified: bool,
    jina_query_qualified: bool,
    all_qualified: bool,
}

fn main() -> Result<()> {
    configure_ort();
    let args = env::args().skip(1).collect::<Vec<_>>();
    let bundle_path = PathBuf::from(args.first().map(String::as_str).unwrap_or(DEFAULT_BUNDLE));
    let output_path = PathBuf::from(args.get(1).map(String::as_str).unwrap_or(DEFAULT_OUTPUT));
    if output_path.exists() {
        bail!("output already exists: {}", output_path.display());
    }

    let frozen = input::load(&bundle_path)?;
    let chunks = build_phoenix_chunks(&frozen.corpus);
    let document_sample = representative_sample(&chunks, DOCUMENT_SAMPLE_ROWS);
    let query_candidates = frozen
        .queries
        .iter()
        .map(|query| SampleText {
            stable_id: format!("{}:{}", query.dataset, query.stable_id),
            text: query.text.clone(),
        })
        .collect::<Vec<_>>();
    let query_sample = representative_sample(&query_candidates, QUERY_SAMPLE_ROWS);

    let gemma = qualify_model(
        "embeddinggemma-300m-q4",
        Path::new(GEMMA_ROOT),
        OrtTextEmbedConfig::embedding_gemma_document,
        OrtTextEmbedConfig::embedding_gemma_query,
        &document_sample,
        &query_sample,
    )?;
    let jina = qualify_model(
        "jina-v5-nano-retrieval",
        Path::new(JINA_ROOT),
        OrtTextEmbedConfig::jina_v5_retrieval_document,
        OrtTextEmbedConfig::jina_v5_retrieval_query,
        &document_sample,
        &query_sample,
    )?;
    let gates = GateReceipt {
        gemma_document_qualified: gemma.document.gates.qualified,
        gemma_query_qualified: gemma.query.gates.qualified,
        jina_document_qualified: jina.document.gates.qualified,
        jina_query_qualified: jina.query.gates.qualified,
        all_qualified: gemma.document.gates.qualified
            && gemma.query.gates.qualified
            && jina.document.gates.qualified
            && jina.query.gates.qualified,
    };
    let ort_path = env::var_os("ORT_DYLIB_PATH")
        .map(PathBuf::from)
        .context("ORT_DYLIB_PATH was not configured")?;
    let lengths = document_sample
        .iter()
        .map(|row| row.text.len())
        .collect::<Vec<_>>();
    let receipt = Receipt {
        contract: "phoenix.embedding-qualification/v1",
        source: SourceReceipt {
            bundle_path: bundle_path.display().to_string(),
            bundle_sha256: sha256_file(&bundle_path)?,
            bundle_blake3: hex(frozen.bundle_hash),
            source_contract: frozen.source_contract.clone(),
            source_packet: frozen.source_packet.clone(),
            phase_5: frozen.phase_5.clone(),
            dataset_counts: frozen.dataset_counts.clone(),
            candidate_documents: frozen.corpus.len(),
            queries: frozen.queries.len(),
        },
        chunking: ChunkReceipt {
            implementation: "phoenix_chunker_native::build_chunks",
            chunk_size: CHUNK_SIZE,
            overlap: CHUNK_OVERLAP,
            total_chunks: chunks.len(),
            sample_rows: document_sample.len(),
            sample_char_p50: quantile(&lengths, 0.50),
            sample_char_p95: quantile(&lengths, 0.95),
            sample_char_max: lengths.iter().copied().max().unwrap_or_default(),
        },
        runtime: RuntimeReceipt {
            ort_dylib_path: ort_path.display().to_string(),
            ort_dylib_sha256: sha256_file(&ort_path)?,
            batch_size: BATCH_SIZE,
            document_sample_rows: document_sample.len(),
            query_sample_rows: query_sample.len(),
        },
        models: vec![gemma, jina],
        gates,
    };
    write_new_json(&output_path, &receipt)?;
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    Ok(())
}

fn build_phoenix_chunks(corpus: &[input::CorpusItem]) -> Vec<SampleText> {
    let config = ChunkerConfig {
        chunk_size: CHUNK_SIZE,
        overlap: CHUNK_OVERLAP,
    };
    let mut rows = Vec::new();
    for item in corpus {
        for (ordinal, chunk) in build_chunks(&item.text, &config).into_iter().enumerate() {
            if let Some(text) = item.text.get(chunk.start..chunk.end) {
                rows.push(SampleText {
                    stable_id: format!("{}:{ordinal}", item.stable_id),
                    text: text.to_owned(),
                });
            }
        }
    }
    rows
}

fn representative_sample(rows: &[SampleText], wanted: usize) -> Vec<SampleText> {
    if rows.len() <= wanted {
        return rows.to_vec();
    }
    let mut by_length = (0..rows.len()).collect::<Vec<_>>();
    by_length.sort_unstable_by_key(|&index| (rows[index].text.len(), index));
    let mut selected = (0..wanted)
        .map(|slot| {
            let rank = ((slot * 2 + 1) * by_length.len()) / (wanted * 2);
            rows[by_length[rank.min(by_length.len() - 1)]].clone()
        })
        .collect::<Vec<_>>();
    selected.sort_unstable_by(|left, right| {
        blake3::hash(left.stable_id.as_bytes())
            .as_bytes()
            .cmp(blake3::hash(right.stable_id.as_bytes()).as_bytes())
    });
    selected
}

fn qualify_model(
    model: &'static str,
    root: &Path,
    document_config: fn(PathBuf) -> OrtTextEmbedConfig,
    query_config: fn(PathBuf) -> OrtTextEmbedConfig,
    documents: &[SampleText],
    queries: &[SampleText],
) -> Result<ModelReceipt> {
    Ok(ModelReceipt {
        model,
        model_root: root.display().to_string(),
        document: qualify_lane(document_config(root.to_path_buf()), documents)?,
        query: qualify_lane(query_config(root.to_path_buf()), queries)?,
    })
}

fn qualify_lane(config: OrtTextEmbedConfig, sample: &[SampleText]) -> Result<LaneReceipt> {
    let embedder = OrtTextEmbedder::load(&config)?;
    let texts = sample
        .iter()
        .map(|row| row.text.as_str())
        .collect::<Vec<_>>();
    let _ = embedder.embed_batched_flat_profiled(&texts[..1], 1, EmbeddingBatchOrder::Input)?;

    let (input_first, input_telemetry, input_first_ms) =
        timed_embed(&embedder, &texts, EmbeddingBatchOrder::Input)?;
    let (bucket_first, bucket_telemetry, bucket_first_ms) =
        timed_embed(&embedder, &texts, EmbeddingBatchOrder::LengthBucketed)?;
    let (_, _, bucket_second_ms) =
        timed_embed(&embedder, &texts, EmbeddingBatchOrder::LengthBucketed)?;
    let (_, _, input_second_ms) = timed_embed(&embedder, &texts, EmbeddingBatchOrder::Input)?;

    let input_ms = input_first_ms.min(input_second_ms);
    let bucket_ms = bucket_first_ms.min(bucket_second_ms);
    let (max_abs_difference, minimum_cosine) = compare_batches(&input_first, &bucket_first)?;
    let input_hash = batch_hash(&input_first);
    let bucket_hash = batch_hash(&bucket_first);
    let gates = LaneGateReceipt {
        canonical_order_restored: input_first.rows() == bucket_first.rows()
            && input_first.dims() == bucket_first.dims(),
        cosine_at_least_0_99999: minimum_cosine >= 0.99999,
        max_abs_at_most_0_0001: max_abs_difference <= 0.0001,
        padded_tokens_non_increasing: bucket_telemetry.padded_tokens
            <= input_telemetry.padded_tokens,
        padded_attention_non_increasing: bucket_telemetry.padded_attention_cells
            <= input_telemetry.padded_attention_cells,
        qualified: false,
    };
    let qualified = gates.canonical_order_restored
        && gates.cosine_at_least_0_99999
        && gates.max_abs_at_most_0_0001
        && gates.padded_tokens_non_increasing
        && gates.padded_attention_non_increasing;
    let gates = LaneGateReceipt { qualified, ..gates };
    let info = embedder.info();
    Ok(LaneReceipt {
        runner: RunnerReceipt {
            model_path: info.model_path.display().to_string(),
            max_length: info.max_length,
            intra_threads: info.intra_threads,
            inter_threads: info.inter_threads,
            parallel_execution: info.parallel_execution,
            configured_batch_order: info.batch_order.label(),
            execution_provider: info.execution_provider.label(),
        },
        assets: model_assets(&info.model_path)?,
        rows: sample.len(),
        input_order_ms: input_ms,
        length_bucketed_ms: bucket_ms,
        speedup: input_ms / bucket_ms.max(f64::EPSILON),
        input_order: telemetry_receipt(input_telemetry),
        length_bucketed: telemetry_receipt(bucket_telemetry),
        max_abs_difference,
        minimum_cosine,
        input_output_hash: input_hash,
        length_bucketed_output_hash: bucket_hash,
        gates,
    })
}

fn timed_embed(
    embedder: &OrtTextEmbedder,
    texts: &[&str],
    order: EmbeddingBatchOrder,
) -> Result<(TextEmbeddingBatch, EmbeddingRunTelemetry, f64)> {
    let started = Instant::now();
    let (rows, telemetry) = embedder.embed_batched_flat_profiled(texts, BATCH_SIZE, order)?;
    Ok((rows, telemetry, started.elapsed().as_secs_f64() * 1_000.0))
}

fn compare_batches(left: &TextEmbeddingBatch, right: &TextEmbeddingBatch) -> Result<(f32, f32)> {
    if left.rows() != right.rows() || left.dims() != right.dims() {
        bail!("embedding batch shapes differ");
    }
    let mut max_abs = 0.0f32;
    let mut min_cosine = 1.0f32;
    for row in 0..left.rows() {
        let left_row = left.row(row).context("left row missing")?;
        let right_row = right.row(row).context("right row missing")?;
        let mut dot = 0.0f32;
        let mut left_norm = 0.0f32;
        let mut right_norm = 0.0f32;
        for (&a, &b) in left_row.iter().zip(right_row) {
            max_abs = max_abs.max((a - b).abs());
            dot += a * b;
            left_norm += a * a;
            right_norm += b * b;
        }
        let cosine = dot / (left_norm.sqrt() * right_norm.sqrt()).max(f32::EPSILON);
        min_cosine = min_cosine.min(cosine);
    }
    Ok((max_abs, min_cosine))
}

fn telemetry_receipt(value: EmbeddingRunTelemetry) -> TelemetryReceipt {
    TelemetryReceipt {
        order: value.order.label(),
        batches: value.batches,
        useful_tokens: value.useful_tokens,
        padded_tokens: value.padded_tokens,
        token_padding_ratio: value.token_padding_ratio(),
        useful_attention_cells: value.useful_attention_cells,
        padded_attention_cells: value.padded_attention_cells,
        attention_padding_ratio: value.attention_padding_ratio(),
        max_sequence_tokens: value.max_sequence_tokens,
    }
}

fn batch_hash(batch: &TextEmbeddingBatch) -> String {
    blake3::hash(bytemuck::cast_slice(batch.values()))
        .to_hex()
        .to_string()
}

fn model_assets(model_path: &Path) -> Result<Vec<FileReceipt>> {
    let mut paths = vec![model_path.to_path_buf()];
    if let Some(name) = model_path.file_name().and_then(|name| name.to_str()) {
        let external = model_path.with_file_name(format!("{name}_data"));
        if external.exists() {
            paths.push(external);
        }
    }
    paths.into_iter().map(file_receipt).collect()
}

fn file_receipt(path: PathBuf) -> Result<FileReceipt> {
    Ok(FileReceipt {
        bytes: fs::metadata(&path)?.len(),
        sha256: sha256_file(&path)?,
        path: path.display().to_string(),
    })
}

fn quantile(values: &[usize], quantile: f64) -> usize {
    if values.is_empty() {
        return 0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let index = ((sorted.len() - 1) as f64 * quantile).floor() as usize;
    sorted[index]
}

fn sha256_file(path: &Path) -> Result<String> {
    let mut file = File::open(path).with_context(|| format!("open {}", path.display()))?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; 1 << 20];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn write_new_json(path: &Path, value: &impl Serialize) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let bytes = serde_json::to_vec_pretty(value)?;
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(&bytes)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

fn configure_ort() {
    if env::var_os("ORT_DYLIB_PATH").is_none() {
        if let Some(path) = default_ort_dylib_path(&workspace_root()) {
            // SAFETY: this CLI configures ORT before creating threads or sessions.
            unsafe { env::set_var("ORT_DYLIB_PATH", path) };
        }
    }
}

fn hex(bytes: [u8; 32]) -> String {
    blake3::Hash::from_bytes(bytes).to_hex().to_string()
}
