use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};
use std::time::{Duration, Instant};

use candle_core::{Device, Tensor};
use g_reasoner_34m_parity::checkpoint::MappedCheckpoint as ReasonerCheckpoint;
use g_reasoner_34m_parity::constants::{
    CHECKPOINT_SAFETENSORS_SHA256 as REASONER_CHECKPOINT_SHA256, QWEN_ONNX_DATA_SHA256,
    QWEN_ONNX_MODEL_SHA256, QWEN_SAFETENSORS_SHA256,
};
use g_reasoner_34m_parity::model::{AggregationBackend as ReasonerBackend, GraphReasonerModel};
use g_reasoner_34m_parity::qwen::QwenEmbedder;
use g_reasoner_34m_parity::qwen_onnx::QwenOnnxEmbedder;
use g_reasoner_34m_parity::ranker::{StableTypedRanking, rank_typed_nodes_stable};
use gfm_rag_8m_parity::checkpoint::MappedCheckpoint as GfmCheckpoint;
use gfm_rag_8m_parity::constants::{
    CHECKPOINT_SAFETENSORS_SHA256 as GFM_CHECKPOINT_SHA256, MPNET_ONNX_SHA256,
};
use gfm_rag_8m_parity::model::{AggregationBackend as GfmBackend, GfmModel};
use gfm_rag_8m_parity::mpnet::MpnetEmbedder;
use gfm_rag_8m_parity::ranker::{RankedDocuments, reciprocal_frequency_rank};
use hashbrown::HashMap;
use phoenix_model_hot_cache::{MaterializedArtifact, MaterializedBundle, ModelHotCache};
use serde::{Deserialize, Serialize};

use crate::{
    ArtifactHotCacheReceipt, CacheReuseReceipt, EncoderExecutionBackend, GfmBundle, GfmProjection,
    InferenceArtifactError, InferencePerformanceReceipt, ModelKind, ModelProvenance,
    PeakMemorySampler, ReasonerBundle, ReasonerProjection, Result, write_gfm_bundle,
    write_reasoner_bundle,
};

const HOT_CACHE_CHUNK_BYTES: usize = 16 * 1024 * 1024;
const MPNET_EMBEDDING_CHUNK_ROWS: usize = 32;
const QWEN_CANDLE_CHUNK_ROWS: usize = 4;
const QWEN_ONNX_CHUNK_ROWS: usize = 4;

#[derive(Clone, Debug)]
pub struct GfmAssets {
    pub checkpoint: PathBuf,
    pub checkpoint_manifest: PathBuf,
    pub mpnet_model: PathBuf,
    pub mpnet_tokenizer: PathBuf,
    pub onnx_runtime: PathBuf,
    pub hot_cache: PathBuf,
}

#[derive(Clone, Debug)]
pub struct ReasonerAssets {
    pub checkpoint: PathBuf,
    pub checkpoint_manifest: PathBuf,
    pub qwen_directory: PathBuf,
    pub qwen_onnx_directory: PathBuf,
    pub onnx_runtime: PathBuf,
    pub encoder_backend: EncoderExecutionBackend,
    pub hot_cache: PathBuf,
}

#[derive(Clone, Debug)]
pub struct ReasonerQueryEmbedding {
    pub values: Box<[f32]>,
    pub encoder_backend: EncoderExecutionBackend,
    pub encoder_resident_reused: bool,
    pub encoder_artifact_bundle_reused: bool,
    pub prepare_micros: u64,
    pub peak_resident_bytes: u64,
    pub artifact_hot_cache: ArtifactHotCacheReceipt,
}

pub fn prepare_reasoner_query_embedding(
    assets: &ReasonerAssets,
    query: &str,
) -> Result<ReasonerQueryEmbedding> {
    let sampler = PeakMemorySampler::start(Duration::from_millis(5));
    let hot_cache = model_hot_cache(&assets.hot_cache)?;
    let started = Instant::now();
    let (artifacts, mut resident, encoder_resident_reused) =
        prepare_reasoner_encoder(assets, &hot_cache)?;
    let values = resident
        .as_mut()
        .expect("resident encoder initialized")
        .encoder
        .embed_query(query)?
        .into_boxed_slice();
    let prepare_micros = micros(started.elapsed());
    drop(resident);
    Ok(ReasonerQueryEmbedding {
        values,
        encoder_backend: assets.encoder_backend,
        encoder_resident_reused,
        encoder_artifact_bundle_reused: artifacts.bundle_reused(),
        prepare_micros,
        peak_resident_bytes: sampler.finish(),
        artifact_hot_cache: artifacts.hot_cache_receipt(None),
    })
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BundleBuildReceipt {
    pub model: ModelKind,
    pub encoder_backend: EncoderExecutionBackend,
    pub encoder_resident_reused: bool,
    pub encoder_artifact_bundle_reused: bool,
    pub encoder_load_micros: u64,
    pub embedding_compute_micros: u64,
    pub artifact_write_micros: u64,
    pub peak_resident_bytes: u64,
    pub relation_rows_computed: u64,
    pub node_rows_computed: u64,
    pub artifact_hot_cache: ArtifactHotCacheReceipt,
}

#[derive(Debug)]
pub struct GfmInferenceOutput {
    pub logits: Box<[f32]>,
    pub ranked_documents: RankedDocuments,
    pub top_entity_ids: Vec<String>,
    pub ordered_document_ids: Vec<String>,
    pub receipt: InferencePerformanceReceipt,
}

#[derive(Debug)]
pub struct ReasonerInferenceOutput {
    pub ranking: StableTypedRanking,
    pub receipt: InferencePerformanceReceipt,
}

pub fn build_gfm_bundle_with_encoder(
    output: impl AsRef<Path>,
    generation: u64,
    projection: GfmProjection,
    assets: &GfmAssets,
) -> Result<BundleBuildReceipt> {
    initialize_onnx_runtime(&assets.onnx_runtime)?;
    let sampler = PeakMemorySampler::start(Duration::from_millis(10));
    let started = Instant::now();
    let hot_cache = model_hot_cache(&assets.hot_cache)?;
    let mpnet = hot_cache.materialize(&assets.mpnet_model, MPNET_ONNX_SHA256)?;
    let mut encoder = MpnetEmbedder::open_materialized(&mpnet, &assets.mpnet_tokenizer)?;
    let encoder_load_micros = micros(started.elapsed());
    let relation_count = projection.view.relation_names.len();
    let relation_text = projection
        .view
        .relation_names
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>();
    let started = Instant::now();
    let relation_embeddings = encoder
        .embed_unnormalized_chunked(&relation_text, MPNET_EMBEDDING_CHUNK_ROWS)?
        .into_iter()
        .flatten()
        .collect::<Vec<_>>();
    let embedding_compute_micros = micros(started.elapsed());
    let started = Instant::now();
    write_gfm_bundle(
        output,
        generation,
        projection,
        &relation_embeddings,
        gfm_provenance(),
    )?;
    let artifact_write_micros = micros(started.elapsed());
    let peak_resident_bytes = sampler.finish();
    Ok(BundleBuildReceipt {
        model: ModelKind::GfmRag8M,
        encoder_backend: EncoderExecutionBackend::MpnetOnnxFp32,
        encoder_resident_reused: false,
        encoder_artifact_bundle_reused: false,
        encoder_load_micros,
        embedding_compute_micros,
        artifact_write_micros,
        peak_resident_bytes,
        relation_rows_computed: relation_count as u64,
        node_rows_computed: 0,
        artifact_hot_cache: ArtifactHotCacheReceipt::from_materializations([mpnet.receipt()]),
    })
}

pub fn build_reasoner_bundle_with_encoder(
    output: impl AsRef<Path>,
    generation: u64,
    projection: ReasonerProjection,
    assets: &ReasonerAssets,
) -> Result<BundleBuildReceipt> {
    let sampler = PeakMemorySampler::start(Duration::from_millis(10));
    let started = Instant::now();
    let hot_cache = model_hot_cache(&assets.hot_cache)?;
    let (encoder_artifacts, mut resident, encoder_resident_reused) =
        prepare_reasoner_encoder(assets, &hot_cache)?;
    let encoder_load_micros = micros(started.elapsed());
    let relation_count = projection.view.relation_names.len();
    let node_count = projection.embedding_texts.len();
    let mut text = Vec::with_capacity(relation_count + node_count);
    text.extend(projection.view.relation_names.iter().map(String::as_str));
    text.extend(projection.embedding_texts.iter().map(String::as_str));
    let started = Instant::now();
    let encoder = &mut resident
        .as_mut()
        .expect("resident encoder initialized")
        .encoder;
    let chunk_rows = encoder.chunk_rows();
    let encoded = encoder.embed_passages_chunked(&text, chunk_rows)?;
    let embedding_compute_micros = micros(started.elapsed());
    drop(resident);
    let mut encoded = encoded.into_iter();
    let relation_embeddings = encoded
        .by_ref()
        .take(relation_count)
        .flatten()
        .collect::<Vec<_>>();
    let node_embeddings = encoded.flatten().collect::<Vec<_>>();
    let started = Instant::now();
    write_reasoner_bundle(
        output,
        generation,
        projection,
        &relation_embeddings,
        &node_embeddings,
        reasoner_provenance(assets.encoder_backend),
    )?;
    let artifact_write_micros = micros(started.elapsed());
    let peak_resident_bytes = sampler.finish();
    Ok(BundleBuildReceipt {
        model: ModelKind::GReasoner34M,
        encoder_backend: assets.encoder_backend,
        encoder_resident_reused,
        encoder_artifact_bundle_reused: encoder_artifacts.bundle_reused(),
        encoder_load_micros,
        embedding_compute_micros,
        artifact_write_micros,
        peak_resident_bytes,
        relation_rows_computed: relation_count as u64,
        node_rows_computed: node_count as u64,
        artifact_hot_cache: encoder_artifacts.hot_cache_receipt(None),
    })
}

pub fn run_gfm_complete(
    bundle_root: impl AsRef<Path>,
    assets: &GfmAssets,
    query: &str,
    start_entity_ids: &[&str],
    top_k: usize,
) -> Result<GfmInferenceOutput> {
    initialize_onnx_runtime(&assets.onnx_runtime)?;
    let sampler = PeakMemorySampler::start(Duration::from_millis(5));
    let hot_cache = model_hot_cache(&assets.hot_cache)?;
    let started = Instant::now();
    let bundle = GfmBundle::open(bundle_root)?;
    let bundle_open_micros = micros(started.elapsed());

    let started = Instant::now();
    let mpnet = hot_cache.materialize(&assets.mpnet_model, MPNET_ONNX_SHA256)?;
    let mut encoder = MpnetEmbedder::open_materialized(&mpnet, &assets.mpnet_tokenizer)?;
    let question = encoder.embed_unnormalized(query)?;
    let encoder_cold_micros = micros(started.elapsed());
    let started = Instant::now();
    let warm_question = encoder.embed_unnormalized(query)?;
    let encoder_warm_micros = micros(started.elapsed());
    ensure_same_embedding(&question, &warm_question, "MPNet cold/warm")?;

    let started = Instant::now();
    let checkpoint_artifact = hot_cache.materialize(&assets.checkpoint, GFM_CHECKPOINT_SHA256)?;
    let checkpoint =
        GfmCheckpoint::open_materialized(&checkpoint_artifact, &assets.checkpoint_manifest)?;
    let device = Device::Cpu;
    let model = GfmModel::load(&checkpoint, &device, 256)?;
    let model_load_micros = micros(started.elapsed());

    let started = Instant::now();
    let question_tensor = Tensor::from_slice(&question, question.len(), &device)?;
    let relation_tensor = Tensor::from_slice(
        bundle.relation_embeddings.values(),
        (
            bundle.relation_embeddings.rows(),
            bundle.relation_embeddings.columns(),
        ),
        &device,
    )?;
    let (start_mask, frequency) = gfm_start_inputs(&bundle, start_entity_ids)?;
    let input_prepare_micros = micros(started.elapsed());

    let started = Instant::now();
    let inference = model.infer_logits(
        &bundle.graph,
        &question_tensor,
        &relation_tensor,
        &start_mask,
        &frequency,
        GfmBackend::Fast,
    )?;
    let logits = inference.logits.to_vec1::<f32>()?;
    let graph_inference_micros = micros(started.elapsed());

    let started = Instant::now();
    let entity_documents = bundle
        .manifest
        .entity_documents
        .iter()
        .map(|documents| documents.clone().into_boxed_slice())
        .collect::<Vec<_>>();
    let ranked_documents = reciprocal_frequency_rank(
        &logits,
        &entity_documents,
        bundle.manifest.document_ids.len(),
        top_k,
    )?;
    let top_entity_ids = ranked_documents
        .top_entities
        .iter()
        .map(|&index| bundle.manifest.node_ids[index].clone())
        .collect();
    let ordered_document_ids = ranked_documents
        .order
        .iter()
        .map(|&index| bundle.manifest.document_ids[index].clone())
        .collect();
    let ranking_micros = micros(started.elapsed());
    let peak_resident_bytes = sampler.finish();
    let complete_inference_micros = bundle_open_micros
        + encoder_cold_micros
        + model_load_micros
        + input_prepare_micros
        + graph_inference_micros
        + ranking_micros;
    let receipt = InferencePerformanceReceipt {
        schema: "phoenix.revision-inference-performance/v1".into(),
        model: ModelKind::GfmRag8M,
        snapshot_digest: bundle.manifest.snapshot_digest.clone(),
        encoder_backend: EncoderExecutionBackend::MpnetOnnxFp32,
        encoder_resident_reused: false,
        encoder_artifact_bundle_reused: false,
        bundle_open_micros,
        encoder_cold_micros,
        encoder_warm_micros,
        model_load_micros,
        input_prepare_micros,
        graph_inference_micros,
        ranking_micros,
        complete_inference_micros,
        peak_resident_bytes,
        artifact_hot_cache: ArtifactHotCacheReceipt::from_materializations([
            mpnet.receipt(),
            checkpoint_artifact.receipt(),
        ]),
        cache: CacheReuseReceipt {
            relation_rows_reused: bundle.relation_embeddings.rows() as u64,
            node_rows_reused: 0,
            encoder_cache_hits: bundle.relation_embeddings.rows() as u64,
            encoder_cache_misses: 1,
        },
    };
    Ok(GfmInferenceOutput {
        logits: logits.into_boxed_slice(),
        ranked_documents,
        top_entity_ids,
        ordered_document_ids,
        receipt,
    })
}

static ONNX_RUNTIME: Mutex<Option<PathBuf>> = Mutex::new(None);
static REASONER_ENCODER: Mutex<Option<ResidentReasonerEncoder>> = Mutex::new(None);

struct ResidentReasonerEncoder {
    key: String,
    encoder: ReasonerEncoder,
}

enum ReasonerEncoder {
    Candle(QwenEmbedder),
    Onnx(QwenOnnxEmbedder),
}

impl ReasonerEncoder {
    fn chunk_rows(&self) -> usize {
        match self {
            Self::Candle(_) => QWEN_CANDLE_CHUNK_ROWS,
            Self::Onnx(_) => QWEN_ONNX_CHUNK_ROWS,
        }
    }

    fn embed_query(&mut self, query: &str) -> g_reasoner_34m_parity::Result<Vec<f32>> {
        match self {
            Self::Candle(encoder) => encoder.embed_query(query),
            Self::Onnx(encoder) => encoder.embed_query(query),
        }
    }

    fn embed_passages_chunked(
        &mut self,
        texts: &[&str],
        max_rows: usize,
    ) -> g_reasoner_34m_parity::Result<Vec<Vec<f32>>> {
        match self {
            Self::Candle(encoder) => encoder.embed_passages_chunked(texts, max_rows),
            Self::Onnx(encoder) => encoder.embed_passages_chunked(texts, max_rows),
        }
    }
}

enum PreparedReasonerArtifacts {
    Candle { weights: MaterializedArtifact },
    Onnx(Box<PreparedOnnxArtifacts>),
}

struct PreparedOnnxArtifacts {
    model: MaterializedArtifact,
    data: MaterializedArtifact,
    bundle: MaterializedBundle,
}

impl PreparedReasonerArtifacts {
    fn key(&self) -> String {
        match self {
            Self::Candle { weights } => format!("qwen-candle-fp32:{}", weights.sha256()),
            Self::Onnx(artifacts) => {
                format!("qwen-onnx-fp32:{}", artifacts.bundle.digest())
            }
        }
    }

    fn bundle_reused(&self) -> bool {
        matches!(self, Self::Onnx(artifacts) if artifacts.bundle.reused())
    }

    fn load(&self, assets: &ReasonerAssets) -> Result<ReasonerEncoder> {
        match self {
            Self::Candle { weights } => Ok(ReasonerEncoder::Candle(
                QwenEmbedder::load_materialized(&assets.qwen_directory, 512, weights)?,
            )),
            Self::Onnx(artifacts) => {
                Ok(ReasonerEncoder::Onnx(QwenOnnxEmbedder::open_materialized(
                    artifacts.bundle.root(),
                    assets.qwen_directory.join("tokenizer.json"),
                    &artifacts.model,
                    &artifacts.data,
                    512,
                )?))
            }
        }
    }

    fn hot_cache_receipt(
        &self,
        checkpoint: Option<&MaterializedArtifact>,
    ) -> ArtifactHotCacheReceipt {
        match (self, checkpoint) {
            (Self::Candle { weights }, Some(checkpoint)) => {
                ArtifactHotCacheReceipt::from_materializations([
                    weights.receipt(),
                    checkpoint.receipt(),
                ])
            }
            (Self::Candle { weights }, None) => {
                ArtifactHotCacheReceipt::from_materializations([weights.receipt()])
            }
            (Self::Onnx(artifacts), Some(checkpoint)) => {
                ArtifactHotCacheReceipt::from_materializations([
                    artifacts.model.receipt(),
                    artifacts.data.receipt(),
                    checkpoint.receipt(),
                ])
            }
            (Self::Onnx(artifacts), None) => ArtifactHotCacheReceipt::from_materializations([
                artifacts.model.receipt(),
                artifacts.data.receipt(),
            ]),
        }
    }
}

fn prepare_reasoner_encoder(
    assets: &ReasonerAssets,
    hot_cache: &ModelHotCache,
) -> Result<(
    PreparedReasonerArtifacts,
    MutexGuard<'static, Option<ResidentReasonerEncoder>>,
    bool,
)> {
    let artifacts = match assets.encoder_backend {
        EncoderExecutionBackend::QwenCandleFp32 => PreparedReasonerArtifacts::Candle {
            weights: hot_cache.materialize(
                assets.qwen_directory.join("model.safetensors"),
                QWEN_SAFETENSORS_SHA256,
            )?,
        },
        EncoderExecutionBackend::QwenOnnxFp32 => {
            initialize_onnx_runtime(&assets.onnx_runtime)?;
            let model = hot_cache.materialize(
                assets.qwen_onnx_directory.join("model.onnx"),
                QWEN_ONNX_MODEL_SHA256,
            )?;
            let data = hot_cache.materialize(
                assets.qwen_onnx_directory.join("model.onnx.data"),
                QWEN_ONNX_DATA_SHA256,
            )?;
            let bundle =
                hot_cache.assemble_bundle(&[(&model, "model.onnx"), (&data, "model.onnx.data")])?;
            PreparedReasonerArtifacts::Onnx(Box::new(PreparedOnnxArtifacts {
                model,
                data,
                bundle,
            }))
        }
        EncoderExecutionBackend::MpnetOnnxFp32 => {
            return Err(InferenceArtifactError::InvalidArtifact(
                "MPNet cannot encode a G-reasoner bundle".into(),
            ));
        }
    };
    let key = artifacts.key();
    let mut resident = REASONER_ENCODER.lock().map_err(|_| {
        InferenceArtifactError::InvalidArtifact("reasoner encoder lock was poisoned".into())
    })?;
    let reused = resident.as_ref().is_some_and(|active| active.key == key);
    if !reused {
        resident.replace(ResidentReasonerEncoder {
            key,
            encoder: artifacts.load(assets)?,
        });
    }
    Ok((artifacts, resident, reused))
}

fn model_hot_cache(root: &Path) -> Result<ModelHotCache> {
    ModelHotCache::new(root, HOT_CACHE_CHUNK_BYTES).map_err(Into::into)
}

fn initialize_onnx_runtime(path: &Path) -> Result<()> {
    let canonical = std::fs::canonicalize(path).map_err(|source| crate::io_error(path, source))?;
    let mut configured = ONNX_RUNTIME.lock().map_err(|_| {
        InferenceArtifactError::InvalidArtifact("ONNX Runtime lock was poisoned".into())
    })?;
    if let Some(active) = configured.as_ref() {
        return if active == &canonical {
            Ok(())
        } else {
            Err(InferenceArtifactError::InvalidArtifact(format!(
                "ONNX Runtime already pinned to {}, cannot switch to {}",
                active.display(),
                canonical.display()
            )))
        };
    }
    ort::init_from(canonical.to_string_lossy())
        .commit()
        .map_err(|error| {
            InferenceArtifactError::InvalidArtifact(format!(
                "failed to initialize pinned ONNX Runtime {}: {error}",
                canonical.display()
            ))
        })?;
    configured.replace(canonical);
    Ok(())
}

pub fn run_reasoner_complete(
    bundle_root: impl AsRef<Path>,
    assets: &ReasonerAssets,
    query: &str,
    start_node_ids: &[&str],
    requested_type: &str,
    top_k: usize,
) -> Result<ReasonerInferenceOutput> {
    let sampler = PeakMemorySampler::start(Duration::from_millis(10));
    let hot_cache = model_hot_cache(&assets.hot_cache)?;
    let started = Instant::now();
    let bundle = ReasonerBundle::open(bundle_root)?;
    let bundle_open_micros = micros(started.elapsed());

    let started = Instant::now();
    let (encoder_artifacts, mut resident, encoder_resident_reused) =
        prepare_reasoner_encoder(assets, &hot_cache)?;
    let question = resident
        .as_mut()
        .expect("resident encoder initialized")
        .encoder
        .embed_query(query)?;
    let encoder_cold_micros = micros(started.elapsed());
    let started = Instant::now();
    let warm_question = resident
        .as_mut()
        .expect("resident encoder initialized")
        .encoder
        .embed_query(query)?;
    let encoder_warm_micros = micros(started.elapsed());
    ensure_same_embedding(&question, &warm_question, "Qwen cold/warm")?;
    drop(resident);

    let started = Instant::now();
    let checkpoint_artifact =
        hot_cache.materialize(&assets.checkpoint, REASONER_CHECKPOINT_SHA256)?;
    let checkpoint =
        ReasonerCheckpoint::open_materialized(&checkpoint_artifact, &assets.checkpoint_manifest)?;
    let device = Device::Cpu;
    let model = GraphReasonerModel::load(&checkpoint, &device, 128)?;
    let model_load_micros = micros(started.elapsed());

    let started = Instant::now();
    let question_tensor = Tensor::from_slice(&question, question.len(), &device)?;
    let relation_tensor = Tensor::from_slice(
        bundle.relation_embeddings.values(),
        (
            bundle.relation_embeddings.rows(),
            bundle.relation_embeddings.columns(),
        ),
        &device,
    )?;
    let node_tensor = Tensor::from_slice(
        bundle.node_embeddings.values(),
        (
            bundle.node_embeddings.rows(),
            bundle.node_embeddings.columns(),
        ),
        &device,
    )?;
    let start_mask = reasoner_start_mask(&bundle, start_node_ids)?;
    let requested_nodes = typed_nodes(&bundle, requested_type);
    if requested_nodes.is_empty() {
        return Err(InferenceArtifactError::InvalidProjection(format!(
            "bundle has no nodes of requested type {requested_type}"
        )));
    }
    let input_prepare_micros = micros(started.elapsed());

    let started = Instant::now();
    let inference = model.infer_logits(
        &bundle.graph,
        &question_tensor,
        &relation_tensor,
        &node_tensor,
        &start_mask,
        ReasonerBackend::Fast,
    )?;
    let logits = inference.logits.to_vec1::<f32>()?;
    let graph_inference_micros = micros(started.elapsed());

    let started = Instant::now();
    let ranking =
        rank_typed_nodes_stable(&logits, &bundle.manifest.node_ids, &requested_nodes, top_k)?;
    let ranking_micros = micros(started.elapsed());
    let peak_resident_bytes = sampler.finish();
    let complete_inference_micros = bundle_open_micros
        + encoder_cold_micros
        + model_load_micros
        + input_prepare_micros
        + graph_inference_micros
        + ranking_micros;
    let receipt = InferencePerformanceReceipt {
        schema: "phoenix.revision-inference-performance/v1".into(),
        model: ModelKind::GReasoner34M,
        snapshot_digest: bundle.manifest.snapshot_digest.clone(),
        encoder_backend: assets.encoder_backend,
        encoder_resident_reused,
        encoder_artifact_bundle_reused: encoder_artifacts.bundle_reused(),
        bundle_open_micros,
        encoder_cold_micros,
        encoder_warm_micros,
        model_load_micros,
        input_prepare_micros,
        graph_inference_micros,
        ranking_micros,
        complete_inference_micros,
        peak_resident_bytes,
        artifact_hot_cache: encoder_artifacts.hot_cache_receipt(Some(&checkpoint_artifact)),
        cache: CacheReuseReceipt {
            relation_rows_reused: bundle.relation_embeddings.rows() as u64,
            node_rows_reused: bundle.node_embeddings.rows() as u64,
            encoder_cache_hits: (bundle.relation_embeddings.rows() + bundle.node_embeddings.rows())
                as u64,
            encoder_cache_misses: 1,
        },
    };
    Ok(ReasonerInferenceOutput { ranking, receipt })
}

fn gfm_start_inputs(bundle: &GfmBundle, requested: &[&str]) -> Result<(Vec<f32>, Vec<f32>)> {
    let index = bundle
        .manifest
        .node_ids
        .iter()
        .enumerate()
        .map(|(index, id)| (id.as_str(), index))
        .collect::<HashMap<_, _>>();
    let mut mask = vec![0.0; index.len()];
    let starts = default_start_ids(&bundle.manifest.node_ids, requested);
    for id in starts {
        let node = index.get(id).ok_or_else(|| {
            InferenceArtifactError::InvalidProjection(format!("unknown start entity {id}"))
        })?;
        mask[*node] = 1.0;
    }
    let frequency = bundle
        .manifest
        .entity_documents
        .iter()
        .map(|documents| documents.len().max(1) as f32)
        .collect();
    Ok((mask, frequency))
}

fn reasoner_start_mask(bundle: &ReasonerBundle, requested: &[&str]) -> Result<Vec<f32>> {
    let index = bundle
        .manifest
        .node_ids
        .iter()
        .enumerate()
        .map(|(index, id)| (id.as_str(), index))
        .collect::<HashMap<_, _>>();
    let mut mask = vec![0.0; index.len()];
    let starts = default_start_ids(&bundle.manifest.node_ids, requested);
    for id in starts {
        let node = index.get(id).ok_or_else(|| {
            InferenceArtifactError::InvalidProjection(format!("unknown start node {id}"))
        })?;
        mask[*node] = 1.0;
    }
    Ok(mask)
}

fn typed_nodes(bundle: &ReasonerBundle, requested_type: &str) -> Vec<u32> {
    bundle
        .manifest
        .node_types
        .iter()
        .enumerate()
        .filter_map(|(index, node_type)| (node_type == requested_type).then_some(index as u32))
        .collect()
}

fn default_start_ids<'a>(all: &'a [String], requested: &'a [&str]) -> Vec<&'a str> {
    if requested.is_empty() {
        all.first().map_or_else(Vec::new, |id| vec![id.as_str()])
    } else {
        requested.to_vec()
    }
}

fn ensure_same_embedding(left: &[f32], right: &[f32], label: &str) -> Result<()> {
    if left.len() != right.len()
        || left
            .iter()
            .zip(right)
            .any(|(left, right)| (left - right).abs() > 1e-5)
    {
        return Err(InferenceArtifactError::InvalidArtifact(format!(
            "{label} embedding drift"
        )));
    }
    Ok(())
}

fn gfm_provenance() -> ModelProvenance {
    ModelProvenance {
        checkpoint_revision: gfm_rag_8m_parity::constants::CHECKPOINT_REVISION.into(),
        checkpoint_digest: gfm_rag_8m_parity::constants::CHECKPOINT_SAFETENSORS_SHA256.into(),
        encoder_revision: gfm_rag_8m_parity::constants::MPNET_REVISION.into(),
        encoder_digest: gfm_rag_8m_parity::constants::MPNET_ONNX_SHA256.into(),
    }
}

fn reasoner_provenance(backend: EncoderExecutionBackend) -> ModelProvenance {
    let encoder_digest = match backend {
        EncoderExecutionBackend::QwenOnnxFp32 => {
            g_reasoner_34m_parity::constants::QWEN_ONNX_BUNDLE_BLAKE3
        }
        EncoderExecutionBackend::QwenCandleFp32 | EncoderExecutionBackend::MpnetOnnxFp32 => {
            g_reasoner_34m_parity::constants::QWEN_SAFETENSORS_SHA256
        }
    };
    ModelProvenance {
        checkpoint_revision: g_reasoner_34m_parity::constants::CHECKPOINT_REVISION.into(),
        checkpoint_digest: g_reasoner_34m_parity::constants::CHECKPOINT_SAFETENSORS_SHA256.into(),
        encoder_revision: g_reasoner_34m_parity::constants::QWEN_REVISION.into(),
        encoder_digest: encoder_digest.into(),
    }
}

fn micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}
