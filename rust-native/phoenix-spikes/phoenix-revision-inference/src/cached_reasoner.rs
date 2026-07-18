use std::path::Path;
use std::time::{Duration, Instant};

use candle_core::{Device, Tensor};
use g_reasoner_34m_parity::checkpoint::MappedCheckpoint;
use g_reasoner_34m_parity::constants::CHECKPOINT_SAFETENSORS_SHA256;
use g_reasoner_34m_parity::model::{AggregationBackend, GraphReasonerModel};
use g_reasoner_34m_parity::ranker::rank_typed_nodes_stable;
use hashbrown::HashMap;
use phoenix_model_hot_cache::ModelHotCache;

use crate::{
    ArtifactHotCacheReceipt, CacheReuseReceipt, InferenceArtifactError,
    InferencePerformanceReceipt, ModelKind, PeakMemorySampler, ReasonerAssets, ReasonerBundle,
    ReasonerInferenceOutput, ReasonerQueryEmbedding, Result,
};

const HOT_CACHE_CHUNK_BYTES: usize = 16 * 1024 * 1024;

pub fn run_reasoner_precomputed(
    bundle_root: impl AsRef<Path>,
    assets: &ReasonerAssets,
    query: &ReasonerQueryEmbedding,
    start_node_ids: &[&str],
    requested_type: &str,
    top_k: usize,
) -> Result<ReasonerInferenceOutput> {
    if query.encoder_backend != assets.encoder_backend {
        return Err(InferenceArtifactError::InvalidArtifact(
            "precomputed query encoder does not match model assets".into(),
        ));
    }
    let sampler = PeakMemorySampler::start(Duration::from_millis(5));
    let started = Instant::now();
    let bundle = ReasonerBundle::open(bundle_root)?;
    let bundle_open_micros = micros(started.elapsed());

    let started = Instant::now();
    let hot_cache = ModelHotCache::new(&assets.hot_cache, HOT_CACHE_CHUNK_BYTES)?;
    let checkpoint_artifact =
        hot_cache.materialize(&assets.checkpoint, CHECKPOINT_SAFETENSORS_SHA256)?;
    let checkpoint =
        MappedCheckpoint::open_materialized(&checkpoint_artifact, &assets.checkpoint_manifest)?;
    let device = Device::Cpu;
    let model = GraphReasonerModel::load(&checkpoint, &device, 128)?;
    let model_load_micros = micros(started.elapsed());

    let started = Instant::now();
    let question_tensor = Tensor::from_slice(&query.values, query.values.len(), &device)?;
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
    let start_mask = start_mask(&bundle, start_node_ids)?;
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
        AggregationBackend::Fast,
    )?;
    let logits = inference.logits.to_vec1::<f32>()?;
    let graph_inference_micros = micros(started.elapsed());
    let started = Instant::now();
    let ranking =
        rank_typed_nodes_stable(&logits, &bundle.manifest.node_ids, &requested_nodes, top_k)?;
    let ranking_micros = micros(started.elapsed());
    let peak_resident_bytes = sampler.finish();
    Ok(ReasonerInferenceOutput {
        ranking,
        receipt: InferencePerformanceReceipt {
            schema: "phoenix.revision-inference-performance/v1".into(),
            model: ModelKind::GReasoner34M,
            snapshot_digest: bundle.manifest.snapshot_digest.clone(),
            encoder_backend: query.encoder_backend,
            encoder_resident_reused: query.encoder_resident_reused,
            encoder_artifact_bundle_reused: query.encoder_artifact_bundle_reused,
            bundle_open_micros,
            encoder_cold_micros: 0,
            encoder_warm_micros: 0,
            model_load_micros,
            input_prepare_micros,
            graph_inference_micros,
            ranking_micros,
            complete_inference_micros: bundle_open_micros
                + model_load_micros
                + input_prepare_micros
                + graph_inference_micros
                + ranking_micros,
            peak_resident_bytes,
            artifact_hot_cache: ArtifactHotCacheReceipt::from_materializations([
                checkpoint_artifact.receipt(),
            ]),
            cache: CacheReuseReceipt {
                relation_rows_reused: bundle.relation_embeddings.rows() as u64,
                node_rows_reused: bundle.node_embeddings.rows() as u64,
                encoder_cache_hits: 1,
                encoder_cache_misses: 0,
            },
        },
    })
}

fn start_mask(bundle: &ReasonerBundle, requested: &[&str]) -> Result<Vec<f32>> {
    let index = bundle
        .manifest
        .node_ids
        .iter()
        .enumerate()
        .map(|(index, id)| (id.as_str(), index))
        .collect::<HashMap<_, _>>();
    let mut mask = vec![0.0; index.len()];
    for id in requested {
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

fn micros(duration: Duration) -> u64 {
    duration.as_micros().min(u128::from(u64::MAX)) as u64
}
