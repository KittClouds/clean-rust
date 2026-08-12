use super::*;
use phoenix_memory_embeddings::EmbeddingRowV1;
use phoenix_turboquant::{
    exact_rerank_candidates_into, exact_search_into, ExactSearchScratch, SearchHit, SearchScratch,
};
use std::time::{Duration, Instant};

pub(super) fn run_worker(
    receiver: mpsc::Receiver<Work>,
    metrics: Arc<RuntimeMetrics>,
    sidecar: Arc<RwLock<SidecarSlot>>,
    shutting_down: Arc<AtomicBool>,
    embedder: Arc<dyn SemanticQueryEmbedder>,
    config: SemanticShadowConfig,
) {
    let mut scratch = WorkerScratch::default();
    while let Ok(work) = receiver.recv() {
        if shutting_down.load(Ordering::Acquire) || matches!(work, Work::Shutdown) {
            break;
        }
        let Work::Evaluate(job) = work else {
            break;
        };
        metrics.queue_depth.fetch_sub(1, Ordering::AcqRel);
        let receipt = evaluate_job(&job, embedder.as_ref(), config, &mut scratch);
        let still_current = sidecar.read().is_ok_and(|slot| {
            slot.status == SemanticSidecarStatus::Ready
                && slot.observed_generation == Some(job.generation_hash)
                && slot.index.as_ref().is_some_and(|current| {
                    current.quantized_artifact_hash() == job.index.quantized_artifact_hash()
                })
        });
        let mut receipt = receipt;
        if !still_current {
            receipt.status = SemanticShadowEvaluationStatus::GenerationChanged;
        }
        if receipt.status != SemanticShadowEvaluationStatus::Ready {
            metrics.failures.fetch_add(1, Ordering::AcqRel);
        }
        if let Ok(mut latest) = metrics.latest.write() {
            *latest = Some(Arc::new(receipt));
        }
        metrics.completed.fetch_add(1, Ordering::AcqRel);
    }
}

#[derive(Default)]
struct WorkerScratch {
    dimension: usize,
    query: Vec<f32>,
    quantized: Option<SearchScratch>,
    exact: Option<ExactSearchScratch>,
    candidates: Vec<SearchHit>,
    reranked: Vec<SearchHit>,
    exact_hits: Vec<SearchHit>,
}

fn evaluate_job(
    job: &EvaluationJob,
    embedder: &dyn SemanticQueryEmbedder,
    config: SemanticShadowConfig,
    scratch: &mut WorkerScratch,
) -> SemanticShadowEvaluationReceipt {
    let total_started = Instant::now();
    let index = &job.index;
    prepare_scratch(scratch, index.dimension(), config);
    scratch.query.clear();
    let embedding_started = Instant::now();
    let embedded = embedder.embed_query(&job.query, index.dimension(), &mut scratch.query);
    let embedding_ns = nanos(embedding_started.elapsed());
    let mut receipt = base_evaluation(job, embedding_ns);
    if embedded.is_err() || !valid_query(&scratch.query, index.dimension()) {
        return failed(
            receipt,
            SemanticShadowEvaluationStatus::EmbeddingFailed,
            total_started,
        );
    }
    let (Ok(vectors), Ok(subject_ids)) =
        (index.embeddings.vectors(), index.quantized.subject_ids())
    else {
        return failed(
            receipt,
            SemanticShadowEvaluationStatus::SearchFailed,
            total_started,
        );
    };
    receipt.query_embedding_hash = hash_embedding(config.privacy_key, &scratch.query);
    let quantized_started = Instant::now();
    let execution = index.quantized.recommended_execution();
    let kernel = index.quantized.search_into(
        &scratch.query,
        config.candidate_k,
        SearchKernel::Auto,
        scratch.quantized.as_mut().expect("dimension initialized"),
        &mut scratch.candidates,
    );
    receipt.quantized_ns = nanos(quantized_started.elapsed());
    let Ok(kernel) = kernel else {
        return failed(
            receipt,
            SemanticShadowEvaluationStatus::SearchFailed,
            total_started,
        );
    };
    receipt.kernel = Some(kernel);
    receipt.execution = Some(execution);
    receipt.quantized_top64_hash = hash_hits(
        config.privacy_key,
        b"quantized-candidates/v1",
        index,
        &scratch.candidates,
    );
    let rerank_started = Instant::now();
    let reranked = exact_rerank_candidates_into(
        vectors,
        subject_ids,
        index.dimension(),
        &scratch.query,
        &scratch.candidates,
        config.rerank_k,
        scratch.exact.as_mut().expect("dimension initialized"),
        &mut scratch.reranked,
    );
    receipt.rerank_ns = nanos(rerank_started.elapsed());
    if reranked.is_err() {
        return failed(
            receipt,
            SemanticShadowEvaluationStatus::SearchFailed,
            total_started,
        );
    }
    receipt.reranked_top10_hash =
        hash_hits(config.privacy_key, b"reranked/v1", index, &scratch.reranked);
    if job.exact_reference_sampled {
        let exact_started = Instant::now();
        let exact = exact_search_into(
            vectors,
            subject_ids,
            index.dimension(),
            &scratch.query,
            config.rerank_k,
            scratch.exact.as_mut().expect("dimension initialized"),
            &mut scratch.exact_hits,
        );
        receipt.exact_reference_ns = nanos(exact_started.elapsed());
        if exact.is_err() {
            return failed(
                receipt,
                SemanticShadowEvaluationStatus::SearchFailed,
                total_started,
            );
        }
        populate_exact_comparison(&mut receipt, scratch, config.privacy_key, index);
    }
    receipt.total_ns = nanos(total_started.elapsed());
    receipt
}

fn prepare_scratch(scratch: &mut WorkerScratch, dimension: usize, config: SemanticShadowConfig) {
    if scratch.dimension == dimension {
        return;
    }
    scratch.dimension = dimension;
    scratch.query.clear();
    scratch.query.reserve(dimension);
    scratch.quantized = Some(SearchScratch::new(dimension, config.candidate_k));
    scratch.exact = Some(ExactSearchScratch::new(config.candidate_k));
    scratch.candidates = Vec::with_capacity(config.candidate_k);
    scratch.reranked = Vec::with_capacity(config.rerank_k);
    scratch.exact_hits = Vec::with_capacity(config.rerank_k);
}

fn populate_exact_comparison(
    receipt: &mut SemanticShadowEvaluationReceipt,
    scratch: &WorkerScratch,
    key: [u8; 32],
    index: &ResidentSemanticIndex,
) {
    receipt.exact_top10_hash = hash_hits(key, b"exact-reference/v1", index, &scratch.exact_hits);
    receipt.exact_top1_in_top64 = scratch.exact_hits.first().is_some_and(|exact| {
        scratch
            .candidates
            .iter()
            .any(|candidate| candidate.row == exact.row)
    });
    receipt.exact_top10_recall_at_64 = scratch
        .exact_hits
        .iter()
        .filter(|exact| {
            scratch
                .candidates
                .iter()
                .any(|candidate| candidate.row == exact.row)
        })
        .count() as u16;
    receipt.reranked_top1_equal = scratch.reranked.first().map(|hit| hit.row)
        == scratch.exact_hits.first().map(|hit| hit.row);
    receipt.ordered_top10_equal = scratch
        .reranked
        .iter()
        .map(|hit| hit.row)
        .eq(scratch.exact_hits.iter().map(|hit| hit.row));
}

fn base_evaluation(job: &EvaluationJob, embedding_ns: u64) -> SemanticShadowEvaluationReceipt {
    let index = &job.index;
    SemanticShadowEvaluationReceipt {
        path_id: SemanticShadowPathId::Phxq1ShadowV1,
        status: SemanticShadowEvaluationStatus::Ready,
        authority_unchanged: true,
        query_hash: job.query_hash,
        generation_hash: job.generation_hash,
        embedding_artifact_hash: index.embedding_artifact_hash(),
        quantized_artifact_hash: index.quantized_artifact_hash(),
        quantizer_hash: index.quantized.header().quantizer_hash,
        bits: index.quantized.bits(),
        rows: u32::try_from(index.rows()).unwrap_or(u32::MAX),
        dimension: u32::try_from(index.dimension()).unwrap_or(u32::MAX),
        exact_reference_sampled: job.exact_reference_sampled,
        embedding_ns,
        ..SemanticShadowEvaluationReceipt::default()
    }
}

fn failed(
    mut receipt: SemanticShadowEvaluationReceipt,
    status: SemanticShadowEvaluationStatus,
    started: Instant,
) -> SemanticShadowEvaluationReceipt {
    receipt.status = status;
    receipt.total_ns = nanos(started.elapsed());
    receipt
}

fn valid_query(query: &[f32], dimension: usize) -> bool {
    if query.len() != dimension || query.iter().any(|value| !value.is_finite()) {
        return false;
    }
    let norm = query.iter().map(|value| value * value).sum::<f32>();
    (0.998..=1.002).contains(&norm)
}

fn hash_embedding(key: [u8; 32], embedding: &[f32]) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new_keyed(&key);
    hasher.update(b"phoenix/semantic-shadow/query-embedding/v1");
    for value in embedding {
        hasher.update(&value.to_bits().to_le_bytes());
    }
    *hasher.finalize().as_bytes()
}

fn hash_hits(
    key: [u8; 32],
    domain: &[u8],
    index: &ResidentSemanticIndex,
    hits: &[SearchHit],
) -> [u8; 32] {
    let rows = index.embeddings.rows().unwrap_or_default();
    let mut hasher = blake3::Hasher::new_keyed(&key);
    hasher.update(b"phoenix/semantic-shadow/results/");
    hasher.update(domain);
    for hit in hits {
        if let Some(row) = rows.get(hit.row) {
            hash_provenance(&mut hasher, row);
            hasher.update(&hit.score.to_bits().to_le_bytes());
        }
    }
    *hasher.finalize().as_bytes()
}

fn hash_provenance(hasher: &mut blake3::Hasher, row: &EmbeddingRowV1) {
    hasher.update(&row.source_id.to_le_bytes());
    hasher.update(&row.source_start.to_le_bytes());
    hasher.update(&row.source_end.to_le_bytes());
    hasher.update(&row.ordinal.to_le_bytes());
    hasher.update(&row.content_hash);
}

fn nanos(duration: Duration) -> u64 {
    duration.as_nanos().min(u128::from(u64::MAX)) as u64
}
