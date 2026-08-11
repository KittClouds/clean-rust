mod frozen_gate {
    pub mod input;
    pub mod metrics;
}

use std::collections::HashMap;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{bail, Context, Result};
use frozen_gate::input::CorpusItem;
use frozen_gate::metrics::{build_exact_reference, evaluate, BitReceipt};
use phoenix_embed::{default_ort_dylib_path, workspace_root, OrtTextEmbedConfig, OrtTextEmbedder};
use phoenix_memory_contract::{
    ContentUnitKind, ContentUnitRecord, DocumentChunkInput, DocumentInput, DocumentRevisionRecord,
    MixedSourceBuilder, PageKindV3, SourceKind, VerifiedGraphGenerationV3,
};
use phoenix_memory_embeddings::{
    write_embedding_pages_new, EmbeddingPageWriteAuthority, EmbeddingRowV1,
    VerifiedEmbeddingPagesV1, ROW_FLAG_NORMALIZED,
};
use phoenix_turboquant::{write_quantized_artifact_new, ArtifactAuthority};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const CONTRACT: &str = "phoenix.turboquant-frozen-gate/v1";
const MODEL_ID: &str = "onnx-community/embeddinggemma-300m-ONNX";
const DIMENSION: usize = 768;
const DEFAULT_BUNDLE: &str =
    "C:\\benchmarks\\phoenix-qps-v3-20260804\\semantic-review-bundles-confirmation-v1-1751.json";
const DEFAULT_MODEL_ROOT: &str = "D:\\phoenix-models\\embeddinggemma-300m-ONNX";
const DEFAULT_OUTPUT: &str = "D:\\phoenix-turboquant-gate-20260810\\benchmark-frozen-v1";

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Receipt {
    contract: &'static str,
    disposition: &'static str,
    source: SourceReceipt,
    traffic: TrafficReceipt,
    corpus: CorpusReceipt,
    model: ModelReceipt,
    timings_ms: TimingReceipt,
    two_bit: BitReceipt,
    four_bit: BitReceipt,
    gates: OverallGates,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SourceReceipt {
    bundle_path: String,
    bundle_bytes: u64,
    bundle_sha256: String,
    bundle_blake3: String,
    source_contract: String,
    source_packet: frozen_gate::input::BoundFile,
    phase_5: frozen_gate::input::BoundFile,
    phase_5_verified: bool,
    dataset_counts: std::collections::BTreeMap<String, usize>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct TrafficReceipt {
    production_query_log_rows: usize,
    production_trace_found: bool,
    workload_classification: &'static str,
    benchmark_queries: usize,
    promotion_eligible: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CorpusReceipt {
    unique_candidate_rows: usize,
    generation_path: String,
    generation_hash: String,
    source_set_hash: String,
    generation_bytes: u64,
    embedding_path: String,
    embedding_artifact_hash: String,
    embedding_bytes: u64,
    dimension: usize,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ModelReceipt {
    model_id: &'static str,
    model_root: String,
    model_identity_hash: String,
    model_asset_hash: String,
    embedding_config_hash: String,
    execution_provider: &'static str,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct TimingReceipt {
    generation_build: f64,
    model_asset_hash: f64,
    document_model_load: f64,
    document_embedding: f64,
    embedding_write: f64,
    query_model_load: f64,
    query_embedding: f64,
    two_bit_encode_write: f64,
    four_bit_encode_write: f64,
    evaluation: f64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct OverallGates {
    frozen_corpus_hash_bound: bool,
    reviewed_benchmark_query_lane: bool,
    two_bit_benchmark_lane: bool,
    four_bit_benchmark_lane: bool,
    production_query_traffic_present: bool,
    promotion_allowed: bool,
}

#[derive(Deserialize)]
struct PhaseFiveStatus {
    phase_5_verified: bool,
}

struct EmbeddingInput {
    subject_id: u64,
    source_id: u64,
    content_hash: [u8; 32],
    start: u32,
    end: u32,
    ordinal: u32,
    text: String,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("frozen_gate: {error:#}");
        std::process::exit(2);
    }
}

fn run() -> Result<()> {
    let args = Args::parse(env::args().skip(1))?;
    if args.output.exists() {
        bail!(
            "refusing existing output directory {}",
            args.output.display()
        );
    }
    fs::create_dir_all(&args.output)
        .with_context(|| format!("create {}", args.output.display()))?;
    configure_ort();

    let input = frozen_gate::input::load(&args.bundle)?;
    let bundle_sha256 = sha256_file(&args.bundle)?;
    verify_bound_file(&input.source_packet)?;
    verify_bound_file(&input.phase_5)?;
    let phase_five: PhaseFiveStatus =
        serde_json::from_slice(&fs::read(&input.phase_5.path).context("read phase 5 receipt")?)
            .context("decode phase 5 receipt")?;

    let generation_path = args.output.join("reviewed-candidates.phxgg3");
    let started = Instant::now();
    let generation = build_generation(&generation_path, &input.corpus)?;
    let generation_build = millis(started);
    let embedding_inputs = collect_embedding_inputs(&generation)?;
    if embedding_inputs.len() != input.corpus.len() {
        bail!("generation row count changed while freezing corpus");
    }

    let started = Instant::now();
    let model_asset_hash = hash_model_assets(&args.model_root)?;
    let model_asset_hash_ms = millis(started);
    let model_identity_hash = *blake3::hash(MODEL_ID.as_bytes()).as_bytes();
    let embedding_config_hash = *blake3::hash(
        b"embeddinggemma/q4/native768/max2048/query-prefix-v1/document-prefix-v1/sentence-embedding/frozen-gate-v1",
    )
    .as_bytes();

    let document_config = OrtTextEmbedConfig::embedding_gemma_document(args.model_root.clone());
    let started = Instant::now();
    let document_embedder = OrtTextEmbedder::load(&document_config)?;
    let document_model_load = millis(started);
    let document_texts = embedding_inputs
        .iter()
        .map(|input| input.text.as_str())
        .collect::<Vec<_>>();
    let started = Instant::now();
    let document_vectors = document_embedder.embed_texts_flat(&document_texts)?;
    let document_embedding = millis(started);
    if document_vectors.rows() != embedding_inputs.len() || document_vectors.dims() != DIMENSION {
        bail!("unexpected document embedding shape");
    }
    drop(document_embedder);

    let rows = build_embedding_rows(&embedding_inputs)?;
    let embedding_path = args.output.join("reviewed-candidates.phxe1");
    let started = Instant::now();
    let embeddings = write_embedding_pages_new(
        &embedding_path,
        EmbeddingPageWriteAuthority {
            generation_hash: generation.header().generation_hash,
            source_set_hash: generation.header().source_set_hash,
            model_identity_hash,
            model_asset_hash,
            config_hash: embedding_config_hash,
            dimension: DIMENSION as u32,
        },
        &rows,
        document_vectors.values(),
    )?;
    let embedding_write = millis(started);
    let embedding_header = *embeddings.header();
    drop(document_vectors);

    let query_config = OrtTextEmbedConfig::embedding_gemma_query(args.model_root.clone());
    let started = Instant::now();
    let query_embedder = OrtTextEmbedder::load(&query_config)?;
    let query_model_load = millis(started);
    let query_texts = input
        .queries
        .iter()
        .map(|query| query.text.as_str())
        .collect::<Vec<_>>();
    let started = Instant::now();
    let query_vectors = query_embedder.embed_texts_flat(&query_texts)?;
    let query_embedding = millis(started);
    if query_vectors.rows() != input.queries.len() || query_vectors.dims() != DIMENSION {
        bail!("unexpected query embedding shape");
    }
    drop(query_embedder);

    let embeddings = VerifiedEmbeddingPagesV1::open(&embedding_path)?;
    let vectors = embeddings.vectors()?;
    let subject_ids = embeddings
        .rows()?
        .iter()
        .map(|row| row.subject_id)
        .collect::<Vec<_>>();
    let authority = ArtifactAuthority::from_embedding_header(embeddings.header());
    let two_path = args.output.join("reviewed-candidates-2bit.phxq1");
    let started = Instant::now();
    let two =
        write_quantized_artifact_new(&two_path, authority, &subject_ids, vectors, DIMENSION, 2)?;
    let two_bit_encode_write = millis(started);
    let four_path = args.output.join("reviewed-candidates-4bit.phxq1");
    let started = Instant::now();
    let four =
        write_quantized_artifact_new(&four_path, authority, &subject_ids, vectors, DIMENSION, 4)?;
    let four_bit_encode_write = millis(started);

    let started = Instant::now();
    let exact = build_exact_reference(vectors, &subject_ids, DIMENSION, query_vectors.values())?;
    let two_bit = evaluate(
        &two,
        &two_path,
        vectors,
        &subject_ids,
        DIMENSION,
        query_vectors.values(),
        &input.queries,
        &exact,
    )?;
    let four_bit = evaluate(
        &four,
        &four_path,
        vectors,
        &subject_ids,
        DIMENSION,
        query_vectors.values(),
        &input.queries,
        &exact,
    )?;
    let evaluation = millis(started);

    let gates = OverallGates {
        frozen_corpus_hash_bound: true,
        reviewed_benchmark_query_lane: input.queries.len() >= 1_000,
        two_bit_benchmark_lane: two_bit.gates.benchmark_lane_passed,
        four_bit_benchmark_lane: four_bit.gates.benchmark_lane_passed,
        production_query_traffic_present: false,
        promotion_allowed: false,
    };
    let receipt = Receipt {
        contract: CONTRACT,
        disposition: "blocked_missing_production_query_traffic",
        source: SourceReceipt {
            bundle_path: args.bundle.display().to_string(),
            bundle_bytes: fs::metadata(&args.bundle)?.len(),
            bundle_sha256,
            bundle_blake3: hex(input.bundle_hash),
            source_contract: input.source_contract,
            source_packet: input.source_packet,
            phase_5: input.phase_5,
            phase_5_verified: phase_five.phase_5_verified,
            dataset_counts: input.dataset_counts,
        },
        traffic: TrafficReceipt {
            production_query_log_rows: 0,
            production_trace_found: false,
            workload_classification: "reviewed_multi_dataset_benchmark_not_production_traffic",
            benchmark_queries: input.queries.len(),
            promotion_eligible: false,
        },
        corpus: CorpusReceipt {
            unique_candidate_rows: subject_ids.len(),
            generation_path: generation_path.display().to_string(),
            generation_hash: hex(generation.header().generation_hash),
            source_set_hash: hex(generation.header().source_set_hash),
            generation_bytes: generation.header().total_len,
            embedding_path: embedding_path.display().to_string(),
            embedding_artifact_hash: hex(embedding_header.artifact_hash),
            embedding_bytes: embedding_header.total_len,
            dimension: DIMENSION,
        },
        model: ModelReceipt {
            model_id: MODEL_ID,
            model_root: args.model_root.display().to_string(),
            model_identity_hash: hex(model_identity_hash),
            model_asset_hash: hex(model_asset_hash),
            embedding_config_hash: hex(embedding_config_hash),
            execution_provider: document_config.execution_provider.label(),
        },
        timings_ms: TimingReceipt {
            generation_build,
            model_asset_hash: model_asset_hash_ms,
            document_model_load,
            document_embedding,
            embedding_write,
            query_model_load,
            query_embedding,
            two_bit_encode_write,
            four_bit_encode_write,
            evaluation,
        },
        two_bit,
        four_bit,
        gates,
    };
    let receipt_path = args.output.join("frozen-gate-receipt.json");
    write_new_json(&receipt_path, &receipt)?;
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    Ok(())
}

fn build_generation(path: &Path, corpus: &[CorpusItem]) -> Result<VerifiedGraphGenerationV3> {
    let mut text = String::new();
    let mut chunks = Vec::with_capacity(corpus.len());
    let mut identity = blake3::Hasher::new();
    for (ordinal, item) in corpus.iter().enumerate() {
        identity.update(&(item.stable_id.len() as u64).to_le_bytes());
        identity.update(item.stable_id.as_bytes());
        if !text.is_empty() {
            text.push_str("\n\n");
        }
        let start = u32::try_from(text.len()).context("corpus text exceeds u32")?;
        text.push_str(&item.text);
        let end = u32::try_from(text.len()).context("corpus text exceeds u32")?;
        chunks.push(DocumentChunkInput {
            start,
            end,
            sentence_start: ordinal as u32,
            sentence_end: ordinal as u32 + 1,
            paragraph_start: ordinal as u32,
            paragraph_end: ordinal as u32 + 1,
            chapter_index: 0,
            token_count: item.text.split_whitespace().count() as u32,
            flags: 0,
        });
    }
    MixedSourceBuilder::new(b"phoenix/turboquant/reviewed-benchmark-v1")
        .generations(1, 1, 1)
        .add_document(DocumentInput::current(
            identity.finalize().as_bytes().to_vec(),
            1,
            "Benchmark/QPS-V3/ReviewedCandidates",
            text,
            chunks,
            1,
        ))
        .prepare()?
        .write(path)
        .map_err(Into::into)
}

fn collect_embedding_inputs(generation: &VerifiedGraphGenerationV3) -> Result<Vec<EmbeddingInput>> {
    let documents =
        generation.typed_page::<DocumentRevisionRecord>(PageKindV3::DocumentRevisions)?;
    let units = generation.typed_page::<ContentUnitRecord>(PageKindV3::ContentUnits)?;
    let mut document_text = HashMap::with_capacity(documents.len());
    for document in documents {
        document_text.insert(
            document.document_id,
            generation.resolve_source_text(document.content)?,
        );
    }
    let mut inputs = Vec::new();
    for unit in units {
        if ContentUnitKind::from_raw(unit.kind) != Some(ContentUnitKind::DynamicChunk) {
            continue;
        }
        let owner = document_text
            .get(&unit.owner_id)
            .context("dynamic chunk owner missing")?;
        let text = owner
            .get(unit.start as usize..unit.end as usize)
            .context("content range is not UTF-8")?;
        inputs.push(EmbeddingInput {
            subject_id: unit.id,
            source_id: unit.source_id,
            content_hash: unit.content_hash,
            start: unit.start,
            end: unit.end,
            ordinal: unit.ordinal,
            text: text.to_owned(),
        });
    }
    inputs.sort_unstable_by_key(|input| input.subject_id);
    Ok(inputs)
}

fn build_embedding_rows(inputs: &[EmbeddingInput]) -> Result<Vec<EmbeddingRowV1>> {
    inputs
        .iter()
        .enumerate()
        .map(|(index, input)| {
            Ok(EmbeddingRowV1 {
                subject_id: input.subject_id,
                source_id: input.source_id,
                content_hash: input.content_hash,
                vector_start: (index * DIMENSION) as u64,
                source_start: input.start,
                source_end: input.end,
                ordinal: input.ordinal,
                dimension: DIMENSION as u32,
                source_kind: SourceKind::WorkspaceDocument as u16,
                content_kind: ContentUnitKind::DynamicChunk as u16,
                flags: ROW_FLAG_NORMALIZED,
                reserved: [0; 2],
            })
        })
        .collect()
}

fn verify_bound_file(bound: &frozen_gate::input::BoundFile) -> Result<()> {
    let path = Path::new(&bound.path);
    let metadata = fs::metadata(path).with_context(|| format!("metadata {}", path.display()))?;
    if metadata.len() != bound.bytes || !sha256_file(path)?.eq_ignore_ascii_case(&bound.sha256) {
        bail!("bound input mismatch: {}", path.display());
    }
    Ok(())
}

fn hash_model_assets(root: &Path) -> Result<[u8; 32]> {
    let mut hasher = blake3::Hasher::new();
    for relative in [
        "tokenizer.json",
        "tokenizer_config.json",
        "config.json",
        "onnx/model_q4.onnx",
        "onnx/model_q4.onnx_data",
    ] {
        hasher.update(&(relative.len() as u64).to_le_bytes());
        hasher.update(relative.as_bytes());
        hash_file_into(&root.join(relative), &mut hasher)?;
    }
    Ok(*hasher.finalize().as_bytes())
}

fn hash_file_into(path: &Path, hasher: &mut blake3::Hasher) -> Result<()> {
    let mut file = File::open(path).with_context(|| format!("open {}", path.display()))?;
    let mut buffer = vec![0u8; 1 << 20];
    loop {
        let read = file
            .read(&mut buffer)
            .with_context(|| format!("read {}", path.display()))?;
        if read == 0 {
            return Ok(());
        }
        hasher.update(&buffer[..read]);
    }
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
            // SAFETY: this CLI configures ORT before creating any threads or sessions.
            unsafe { env::set_var("ORT_DYLIB_PATH", path) };
        }
    }
}

fn millis(started: Instant) -> f64 {
    started.elapsed().as_secs_f64() * 1_000.0
}

fn hex(bytes: [u8; 32]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}

struct Args {
    bundle: PathBuf,
    model_root: PathBuf,
    output: PathBuf,
}

impl Args {
    fn parse(mut args: impl Iterator<Item = String>) -> Result<Self> {
        let mut result = Self {
            bundle: PathBuf::from(DEFAULT_BUNDLE),
            model_root: PathBuf::from(DEFAULT_MODEL_ROOT),
            output: PathBuf::from(DEFAULT_OUTPUT),
        };
        while let Some(argument) = args.next() {
            let value = args
                .next()
                .with_context(|| format!("{argument} requires a value"))?;
            match argument.as_str() {
                "--bundle" => result.bundle = PathBuf::from(value),
                "--model-root" => result.model_root = PathBuf::from(value),
                "--output" => result.output = PathBuf::from(value),
                _ => bail!("unknown argument: {argument}"),
            }
        }
        Ok(result)
    }
}
