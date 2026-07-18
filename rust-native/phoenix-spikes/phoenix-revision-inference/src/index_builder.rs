use std::path::Path;
use std::sync::{Mutex, MutexGuard};
use std::time::{Duration, Instant};

use g_reasoner_34m_parity::constants::{
    FEATURE_DIM, QWEN_ONNX_DATA_SHA256, QWEN_ONNX_MODEL_SHA256, QWEN_SAFETENSORS_SHA256,
    QWEN_TOKENIZER_SHA256,
};
use gfm_rag_8m_parity::constants::{EMBEDDING_DIM, MPNET_ONNX_SHA256};
use serde::{Deserialize, Serialize};

use crate::runner::{
    PreparedReasonerArtifacts, ReasonerEncoder, ResidentGfmEncoder, gfm_provenance, micros,
    model_hot_cache, prepare_gfm_encoder, prepare_reasoner_encoder, reasoner_provenance,
};
use crate::{
    ArtifactHotCacheReceipt, EmbeddingCacheResolution, EmbeddingRowCache, EncoderExecutionBackend,
    GfmAssets, GfmProjection, InferenceArtifactError, ModelKind, PeakMemorySampler, ReasonerAssets,
    ReasonerProjection, Result, embedding_namespace, embedding_row_key, probe_bundle_authority,
    write_gfm_bundle, write_reasoner_bundle,
};

const EMBEDDING_CACHE_DIRECTORY: &str = "embedding-rows-v1";
const MPNET_BATCH_ROWS: usize = 32;
static GFM_INDEX_BUILD_LOCK: Mutex<()> = Mutex::new(());
static REASONER_INDEX_BUILD_LOCK: Mutex<()> = Mutex::new(());

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BundleBuildReceipt {
    pub model: ModelKind,
    pub encoder_backend: EncoderExecutionBackend,
    pub bundle_reused: bool,
    pub encoder_resident_reused: bool,
    pub encoder_artifact_bundle_reused: bool,
    pub bundle_probe_micros: u64,
    pub embedding_cache_probe_micros: u64,
    pub encoder_load_micros: u64,
    pub embedding_compute_micros: u64,
    pub embedding_cache_write_micros: u64,
    pub artifact_write_micros: u64,
    pub peak_resident_bytes: u64,
    pub relation_rows_reused: u64,
    pub relation_rows_computed: u64,
    pub node_rows_reused: u64,
    pub node_rows_computed: u64,
    pub embedding_bytes_written: u64,
    pub artifact_hot_cache: ArtifactHotCacheReceipt,
}

pub fn build_gfm_bundle_with_encoder(
    output: impl AsRef<Path>,
    generation: u64,
    projection: GfmProjection,
    assets: &GfmAssets,
) -> Result<BundleBuildReceipt> {
    let _build_guard = lock_build(&GFM_INDEX_BUILD_LOCK, "GFM")?;
    let output = output.as_ref();
    let provenance = gfm_provenance();
    let relation_count = projection.view.relation_names.len();
    let probe_started = Instant::now();
    if probe_existing(
        output,
        ModelKind::GfmRag8M,
        generation,
        &projection.snapshot_digest,
        &provenance,
    )? {
        return Ok(reused_receipt(
            ModelKind::GfmRag8M,
            EncoderExecutionBackend::MpnetOnnxFp32,
            micros(probe_started.elapsed()),
            relation_count,
            0,
        ));
    }
    let bundle_probe_micros = micros(probe_started.elapsed());
    let sampler = PeakMemorySampler::start(Duration::from_millis(10));
    let namespace = embedding_namespace(&[
        "mpnet-onnx-fp32",
        MPNET_ONNX_SHA256,
        "mean-pool-unnormalized-v1",
    ]);
    let texts = projection
        .view
        .relation_names
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>();
    let keys = texts
        .iter()
        .map(|text| embedding_row_key(&namespace, "relation", text))
        .collect::<Vec<_>>();
    let cache_started = Instant::now();
    let mut cache = EmbeddingRowCache::open(
        assets.hot_cache.join(EMBEDDING_CACHE_DIRECTORY),
        namespace,
        EMBEDDING_DIM,
        keys.len(),
    )?;
    let mut resolution = cache.resolve(&keys)?;
    let embedding_cache_probe_micros = micros(cache_started.elapsed());
    let relation_rows_computed = resolution.unique_miss_count();
    let relation_rows_reused = relation_count.saturating_sub(resolution.missing_row_count());
    let mut encoder_load_micros = 0;
    let mut embedding_compute_micros = 0;
    let mut embedding_cache_write_micros = 0;
    let mut embedding_bytes_written = 0;
    let mut encoder_resident_reused = false;
    let mut artifact_hot_cache = ArtifactHotCacheReceipt::default();
    if !resolution.misses.is_empty() {
        let started = Instant::now();
        let hot_cache = model_hot_cache(&assets.hot_cache)?;
        let (mpnet, mut resident, reused) = prepare_gfm_encoder(assets, &hot_cache)?;
        encoder_resident_reused = reused;
        encoder_load_micros = micros(started.elapsed());
        let miss_texts = miss_texts(&resolution, &texts);
        let started = Instant::now();
        let encoded = encode_mpnet_source_order(
            resident.as_mut().expect("resident GFM encoder initialized"),
            &miss_texts,
        )?;
        embedding_compute_micros = micros(started.elapsed());
        drop(resident);
        let started = Instant::now();
        embedding_bytes_written = cache.install(&mut resolution, &encoded)?;
        embedding_cache_write_micros = micros(started.elapsed());
        artifact_hot_cache = ArtifactHotCacheReceipt::from_materializations([mpnet.receipt()]);
    }
    let started = Instant::now();
    write_gfm_bundle(
        output,
        generation,
        projection,
        &resolution.values,
        provenance,
    )?;
    let artifact_write_micros = micros(started.elapsed());
    Ok(BundleBuildReceipt {
        model: ModelKind::GfmRag8M,
        encoder_backend: EncoderExecutionBackend::MpnetOnnxFp32,
        bundle_reused: false,
        encoder_resident_reused,
        encoder_artifact_bundle_reused: false,
        bundle_probe_micros,
        embedding_cache_probe_micros,
        encoder_load_micros,
        embedding_compute_micros,
        embedding_cache_write_micros,
        artifact_write_micros,
        peak_resident_bytes: sampler.finish(),
        relation_rows_reused: relation_rows_reused as u64,
        relation_rows_computed: relation_rows_computed as u64,
        node_rows_reused: 0,
        node_rows_computed: 0,
        embedding_bytes_written,
        artifact_hot_cache,
    })
}

pub fn build_reasoner_bundle_with_encoder(
    output: impl AsRef<Path>,
    generation: u64,
    projection: ReasonerProjection,
    assets: &ReasonerAssets,
) -> Result<BundleBuildReceipt> {
    let _build_guard = lock_build(&REASONER_INDEX_BUILD_LOCK, "G-reasoner")?;
    let output = output.as_ref();
    let provenance = reasoner_provenance(assets.encoder_backend);
    let relation_count = projection.view.relation_names.len();
    let node_count = projection.embedding_texts.len();
    let probe_started = Instant::now();
    if probe_existing(
        output,
        ModelKind::GReasoner34M,
        generation,
        &projection.snapshot_digest,
        &provenance,
    )? {
        return Ok(reused_receipt(
            ModelKind::GReasoner34M,
            assets.encoder_backend,
            micros(probe_started.elapsed()),
            relation_count,
            node_count,
        ));
    }
    let bundle_probe_micros = micros(probe_started.elapsed());
    let sampler = PeakMemorySampler::start(Duration::from_millis(10));
    let namespace = reasoner_namespace(assets.encoder_backend)?;
    let mut texts = Vec::with_capacity(relation_count + node_count);
    texts.extend(projection.view.relation_names.iter().map(String::as_str));
    texts.extend(projection.embedding_texts.iter().map(String::as_str));
    let keys = texts
        .iter()
        .enumerate()
        .map(|(index, text)| {
            embedding_row_key(
                &namespace,
                if index < relation_count {
                    "relation"
                } else {
                    "node"
                },
                text,
            )
        })
        .collect::<Vec<_>>();
    let cache_started = Instant::now();
    let mut cache = EmbeddingRowCache::open(
        assets.hot_cache.join(EMBEDDING_CACHE_DIRECTORY),
        namespace,
        FEATURE_DIM,
        keys.len(),
    )?;
    let mut resolution = cache.resolve(&keys)?;
    let embedding_cache_probe_micros = micros(cache_started.elapsed());
    let (relation_rows_computed, node_rows_computed) =
        computed_rows_by_lane(&resolution, relation_count);
    let relation_rows_reused = relation_count.saturating_sub(
        resolution
            .misses
            .iter()
            .map(|miss| {
                miss.positions
                    .iter()
                    .filter(|&&position| position < relation_count)
                    .count()
            })
            .sum(),
    );
    let node_rows_reused = node_count.saturating_sub(
        resolution
            .misses
            .iter()
            .map(|miss| {
                miss.positions
                    .iter()
                    .filter(|&&position| position >= relation_count)
                    .count()
            })
            .sum(),
    );
    let mut encoder_load_micros = 0;
    let mut embedding_compute_micros = 0;
    let mut embedding_cache_write_micros = 0;
    let mut embedding_bytes_written = 0;
    let mut encoder_resident_reused = false;
    let mut encoder_artifacts = None::<PreparedReasonerArtifacts>;
    if !resolution.misses.is_empty() {
        let started = Instant::now();
        let hot_cache = model_hot_cache(&assets.hot_cache)?;
        let (artifacts, mut resident, reused) = prepare_reasoner_encoder(assets, &hot_cache)?;
        encoder_load_micros = micros(started.elapsed());
        encoder_resident_reused = reused;
        let miss_texts = miss_texts(&resolution, &texts);
        let encoder = &mut resident
            .as_mut()
            .expect("resident reasoner encoder initialized")
            .encoder;
        let started = Instant::now();
        let encoded = encode_reasoner_source_order(encoder, &miss_texts)?;
        embedding_compute_micros = micros(started.elapsed());
        drop(resident);
        let started = Instant::now();
        embedding_bytes_written = cache.install(&mut resolution, &encoded)?;
        embedding_cache_write_micros = micros(started.elapsed());
        encoder_artifacts = Some(artifacts);
    }
    let relation_value_count = relation_count * FEATURE_DIM;
    let started = Instant::now();
    write_reasoner_bundle(
        output,
        generation,
        projection,
        &resolution.values[..relation_value_count],
        &resolution.values[relation_value_count..],
        provenance,
    )?;
    let artifact_write_micros = micros(started.elapsed());
    Ok(BundleBuildReceipt {
        model: ModelKind::GReasoner34M,
        encoder_backend: assets.encoder_backend,
        bundle_reused: false,
        encoder_resident_reused,
        encoder_artifact_bundle_reused: encoder_artifacts
            .as_ref()
            .is_some_and(PreparedReasonerArtifacts::bundle_reused),
        bundle_probe_micros,
        embedding_cache_probe_micros,
        encoder_load_micros,
        embedding_compute_micros,
        embedding_cache_write_micros,
        artifact_write_micros,
        peak_resident_bytes: sampler.finish(),
        relation_rows_reused: relation_rows_reused as u64,
        relation_rows_computed: relation_rows_computed as u64,
        node_rows_reused: node_rows_reused as u64,
        node_rows_computed: node_rows_computed as u64,
        embedding_bytes_written,
        artifact_hot_cache: encoder_artifacts
            .as_ref()
            .map_or_else(ArtifactHotCacheReceipt::default, |artifacts| {
                artifacts.hot_cache_receipt(None)
            }),
    })
}

fn probe_existing(
    output: &Path,
    model: ModelKind,
    generation: u64,
    snapshot_digest: &str,
    provenance: &crate::ModelProvenance,
) -> Result<bool> {
    let reused = probe_bundle_authority(output, model, generation, snapshot_digest, provenance)?;
    if output.exists() && !reused {
        return Err(InferenceArtifactError::InvalidArtifact(format!(
            "immutable bundle at {} does not match requested authority",
            output.display()
        )));
    }
    Ok(reused)
}

fn lock_build(lock: &'static Mutex<()>, model: &str) -> Result<MutexGuard<'static, ()>> {
    lock.lock().map_err(|_| {
        InferenceArtifactError::InvalidArtifact(format!("{model} index-build lock was poisoned"))
    })
}

fn reused_receipt(
    model: ModelKind,
    backend: EncoderExecutionBackend,
    bundle_probe_micros: u64,
    relation_rows: usize,
    node_rows: usize,
) -> BundleBuildReceipt {
    BundleBuildReceipt {
        model,
        encoder_backend: backend,
        bundle_reused: true,
        encoder_resident_reused: false,
        encoder_artifact_bundle_reused: false,
        bundle_probe_micros,
        embedding_cache_probe_micros: 0,
        encoder_load_micros: 0,
        embedding_compute_micros: 0,
        embedding_cache_write_micros: 0,
        artifact_write_micros: 0,
        peak_resident_bytes: 0,
        relation_rows_reused: relation_rows as u64,
        relation_rows_computed: 0,
        node_rows_reused: node_rows as u64,
        node_rows_computed: 0,
        embedding_bytes_written: 0,
        artifact_hot_cache: ArtifactHotCacheReceipt::default(),
    }
}

fn reasoner_namespace(backend: EncoderExecutionBackend) -> Result<[u8; 32]> {
    match backend {
        EncoderExecutionBackend::QwenOnnxFp32 => Ok(embedding_namespace(&[
            "qwen-onnx-fp32",
            QWEN_ONNX_MODEL_SHA256,
            QWEN_ONNX_DATA_SHA256,
            QWEN_TOKENIZER_SHA256,
            "passage-source-order-batch4-v2",
        ])),
        EncoderExecutionBackend::QwenCandleFp32 => Ok(embedding_namespace(&[
            "qwen-candle-fp32",
            QWEN_SAFETENSORS_SHA256,
            QWEN_TOKENIZER_SHA256,
            "passage-source-order-batch4-v2",
        ])),
        EncoderExecutionBackend::MpnetOnnxFp32 => Err(InferenceArtifactError::InvalidArtifact(
            "MPNet cannot encode a G-reasoner index".into(),
        )),
    }
}

fn miss_texts<'a>(resolution: &EmbeddingCacheResolution, all_texts: &[&'a str]) -> Vec<&'a str> {
    resolution
        .misses
        .iter()
        .map(|miss| all_texts[miss.positions[0]])
        .collect()
}

fn computed_rows_by_lane(
    resolution: &EmbeddingCacheResolution,
    relation_count: usize,
) -> (usize, usize) {
    let relation = resolution
        .misses
        .iter()
        .filter(|miss| miss.positions[0] < relation_count)
        .count();
    (relation, resolution.misses.len() - relation)
}

fn encode_mpnet_source_order(encoder: &mut ResidentGfmEncoder, texts: &[&str]) -> Result<Vec<f32>> {
    let mut output = vec![0.0_f32; texts.len() * EMBEDDING_DIM];
    for (chunk_index, input) in texts.chunks(MPNET_BATCH_ROWS).enumerate() {
        let rows = encoder
            .encoder
            .embed_unnormalized_chunked(input, input.len())?;
        let start = chunk_index * MPNET_BATCH_ROWS;
        let positions = (start..start + input.len()).collect::<Vec<_>>();
        scatter_rows(&mut output, EMBEDDING_DIM, &positions, rows)?;
    }
    Ok(output)
}

fn encode_reasoner_source_order(encoder: &mut ReasonerEncoder, texts: &[&str]) -> Result<Vec<f32>> {
    let mut output = vec![0.0_f32; texts.len() * FEATURE_DIM];
    let chunk_rows = encoder.chunk_rows();
    for (chunk_index, input) in texts.chunks(chunk_rows).enumerate() {
        let rows = encoder.embed_passages_chunked(input, input.len())?;
        let start = chunk_index * chunk_rows;
        let positions = (start..start + input.len()).collect::<Vec<_>>();
        scatter_rows(&mut output, FEATURE_DIM, &positions, rows)?;
    }
    Ok(output)
}

fn scatter_rows(
    output: &mut [f32],
    columns: usize,
    positions: &[usize],
    rows: Vec<Vec<f32>>,
) -> Result<()> {
    if rows.len() != positions.len() || rows.iter().any(|row| row.len() != columns) {
        return Err(InferenceArtifactError::InvalidArtifact(
            "source-order encoder batch returned a non-canonical matrix".into(),
        ));
    }
    for (&position, row) in positions.iter().zip(rows) {
        output[position * columns..(position + 1) * columns].copy_from_slice(&row);
    }
    Ok(())
}
