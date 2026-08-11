use std::collections::BTreeMap;
use std::fs;
use std::time::Instant;

use anyhow::{Context, Result};
use phoenix_turboquant::{
    exact_rerank_candidates_into, exact_search_into, ExactSearchScratch, SearchHit, SearchKernel,
    SearchScratch, VerifiedQuantizedIndex,
};
use serde::Serialize;

use super::input::QueryItem;

const EXACT_TOP_K: usize = 10;
const CANDIDATE_K: usize = 64;

pub struct ExactReference {
    rankings: Vec<Vec<usize>>,
    pub latency_ns: Percentiles,
    pub output_hash: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Percentiles {
    pub p50: u64,
    pub p95: u64,
    pub p99: u64,
    pub max: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DatasetQuality {
    pub queries: usize,
    pub exact_top1_in_candidate_rate: f64,
    pub exact_top10_recall_at_64: f64,
    pub exact_top1_after_rerank_rate: f64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct QualityMetrics {
    pub exact_top1_in_candidate_rate: f64,
    pub exact_top10_recall_at_64: f64,
    pub exact_top1_after_rerank_rate: f64,
    pub exact_top10_ordered_match_rate: f64,
    pub datasets: BTreeMap<String, DatasetQuality>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BitGates {
    pub corpus_rows_at_least_5000: bool,
    pub queries_at_least_1000: bool,
    pub datasets_at_least_3: bool,
    pub aggregate_top1_candidate_recall: bool,
    pub aggregate_top10_candidate_recall: bool,
    pub aggregate_top1_after_rerank: bool,
    pub every_dataset_top1_after_rerank: bool,
    pub p95_candidate_plus_rerank_faster_than_exact: bool,
    pub storage_ratio_within_budget: bool,
    pub deterministic_repeat: bool,
    pub benchmark_lane_passed: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BitReceipt {
    pub bits: u8,
    pub candidate_k: usize,
    pub exact_top_k: usize,
    pub artifact_path: String,
    pub artifact_hash: String,
    pub artifact_bytes: u64,
    pub f32_payload_bytes: u64,
    pub storage_ratio: f64,
    pub quality: QualityMetrics,
    pub candidate_latency_ns: Percentiles,
    pub rerank_latency_ns: Percentiles,
    pub candidate_plus_rerank_latency_ns: Percentiles,
    pub exact_latency_ns: Percentiles,
    pub exact_output_hash: String,
    pub output_hash: String,
    pub repeat_output_hash: String,
    pub gates: BitGates,
}

#[derive(Default)]
struct SliceCounters {
    queries: usize,
    top1_candidate: usize,
    top10_found: usize,
    top1_reranked: usize,
    ordered_top10_matches: usize,
}

pub fn build_exact_reference(
    vectors: &[f32],
    subject_ids: &[u64],
    dimension: usize,
    query_vectors: &[f32],
) -> Result<ExactReference> {
    let mut scratch = ExactSearchScratch::new(EXACT_TOP_K);
    let mut output = Vec::with_capacity(EXACT_TOP_K);
    let mut rankings = Vec::with_capacity(query_vectors.len() / dimension);
    let mut latency = Vec::with_capacity(rankings.capacity());
    let mut hasher = blake3::Hasher::new();
    for query in query_vectors.chunks_exact(dimension) {
        let started = Instant::now();
        exact_search_into(
            vectors,
            subject_ids,
            dimension,
            query,
            EXACT_TOP_K,
            &mut scratch,
            &mut output,
        )?;
        latency.push(nanos(started));
        let rows = output.iter().map(|hit| hit.row).collect::<Vec<_>>();
        hash_rows(&mut hasher, &rows);
        rankings.push(rows);
    }
    Ok(ExactReference {
        rankings,
        latency_ns: percentiles(latency),
        output_hash: hasher.finalize().to_hex().to_string(),
    })
}

#[allow(clippy::too_many_arguments)]
pub fn evaluate(
    index: &VerifiedQuantizedIndex,
    artifact_path: &std::path::Path,
    vectors: &[f32],
    subject_ids: &[u64],
    dimension: usize,
    query_vectors: &[f32],
    queries: &[QueryItem],
    exact: &ExactReference,
) -> Result<BitReceipt> {
    let bits = index.bits();
    let mut search_scratch = SearchScratch::new(dimension, CANDIDATE_K);
    let mut exact_scratch = ExactSearchScratch::new(EXACT_TOP_K);
    let mut candidates = Vec::<SearchHit>::with_capacity(CANDIDATE_K);
    let mut reranked = Vec::<SearchHit>::with_capacity(EXACT_TOP_K);
    let mut candidate_latency = Vec::with_capacity(queries.len());
    let mut rerank_latency = Vec::with_capacity(queries.len());
    let mut combined_latency = Vec::with_capacity(queries.len());
    let mut aggregate = SliceCounters::default();
    let mut slices = BTreeMap::<String, SliceCounters>::new();
    let mut output_hasher = blake3::Hasher::new();

    for ((query, query_vector), exact_rows) in queries
        .iter()
        .zip(query_vectors.chunks_exact(dimension))
        .zip(&exact.rankings)
    {
        output_hasher.update(&(query.stable_id.len() as u64).to_le_bytes());
        output_hasher.update(query.stable_id.as_bytes());
        let combined_started = Instant::now();
        let candidate_started = Instant::now();
        index.search_into(
            query_vector,
            CANDIDATE_K,
            SearchKernel::Auto,
            &mut search_scratch,
            &mut candidates,
        )?;
        candidate_latency.push(nanos(candidate_started));
        let rerank_started = Instant::now();
        exact_rerank_candidates_into(
            vectors,
            subject_ids,
            dimension,
            query_vector,
            &candidates,
            EXACT_TOP_K,
            &mut exact_scratch,
            &mut reranked,
        )?;
        rerank_latency.push(nanos(rerank_started));
        combined_latency.push(nanos(combined_started));
        let counters = slices.entry(query.dataset.clone()).or_default();
        record_quality(counters, exact_rows, &candidates, &reranked);
        record_quality(&mut aggregate, exact_rows, &candidates, &reranked);
        hash_rows(
            &mut output_hasher,
            &reranked.iter().map(|hit| hit.row).collect::<Vec<_>>(),
        );
    }
    let output_hash = output_hasher.finalize().to_hex().to_string();
    let repeat_output_hash = repeat_hash(
        index,
        vectors,
        subject_ids,
        dimension,
        query_vectors,
        queries,
    )?;
    let quality = quality_metrics(aggregate, slices);
    let candidate_latency_ns = percentiles(candidate_latency);
    let rerank_latency_ns = percentiles(rerank_latency);
    let candidate_plus_rerank_latency_ns = percentiles(combined_latency);
    let artifact_bytes = fs::metadata(artifact_path)
        .with_context(|| format!("metadata {}", artifact_path.display()))?
        .len();
    let f32_payload_bytes = std::mem::size_of_val(vectors) as u64;
    let storage_ratio = artifact_bytes as f64 / f32_payload_bytes as f64;
    let gates = gates(
        bits,
        subject_ids.len(),
        queries.len(),
        quality.datasets.len(),
        &quality,
        &candidate_plus_rerank_latency_ns,
        &exact.latency_ns,
        storage_ratio,
        output_hash == repeat_output_hash,
    );
    Ok(BitReceipt {
        bits,
        candidate_k: CANDIDATE_K,
        exact_top_k: EXACT_TOP_K,
        artifact_path: artifact_path.display().to_string(),
        artifact_hash: hex(index.header().artifact_hash),
        artifact_bytes,
        f32_payload_bytes,
        storage_ratio,
        quality,
        candidate_latency_ns,
        rerank_latency_ns,
        candidate_plus_rerank_latency_ns,
        exact_latency_ns: exact.latency_ns.clone(),
        exact_output_hash: exact.output_hash.clone(),
        output_hash,
        repeat_output_hash,
        gates,
    })
}

fn repeat_hash(
    index: &VerifiedQuantizedIndex,
    vectors: &[f32],
    subject_ids: &[u64],
    dimension: usize,
    query_vectors: &[f32],
    queries: &[QueryItem],
) -> Result<String> {
    let mut search_scratch = SearchScratch::new(dimension, CANDIDATE_K);
    let mut exact_scratch = ExactSearchScratch::new(EXACT_TOP_K);
    let mut candidates = Vec::with_capacity(CANDIDATE_K);
    let mut reranked = Vec::with_capacity(EXACT_TOP_K);
    let mut hasher = blake3::Hasher::new();
    for (query, metadata) in query_vectors.chunks_exact(dimension).zip(queries) {
        hasher.update(&(metadata.stable_id.len() as u64).to_le_bytes());
        hasher.update(metadata.stable_id.as_bytes());
        index.search_into(
            query,
            CANDIDATE_K,
            SearchKernel::Auto,
            &mut search_scratch,
            &mut candidates,
        )?;
        exact_rerank_candidates_into(
            vectors,
            subject_ids,
            dimension,
            query,
            &candidates,
            EXACT_TOP_K,
            &mut exact_scratch,
            &mut reranked,
        )?;
        hash_rows(
            &mut hasher,
            &reranked.iter().map(|hit| hit.row).collect::<Vec<_>>(),
        );
    }
    Ok(hasher.finalize().to_hex().to_string())
}

fn record_quality(
    counters: &mut SliceCounters,
    exact: &[usize],
    candidates: &[SearchHit],
    reranked: &[SearchHit],
) {
    counters.queries += 1;
    counters.top1_candidate += usize::from(
        exact
            .first()
            .is_some_and(|row| candidates.iter().any(|hit| hit.row == *row)),
    );
    counters.top10_found += exact
        .iter()
        .filter(|row| candidates.iter().any(|hit| hit.row == **row))
        .count();
    counters.top1_reranked += usize::from(
        exact
            .first()
            .zip(reranked.first())
            .is_some_and(|(row, hit)| *row == hit.row),
    );
    counters.ordered_top10_matches += usize::from(
        exact.len() == reranked.len()
            && exact.iter().zip(reranked).all(|(row, hit)| *row == hit.row),
    );
}

fn quality_metrics(
    aggregate: SliceCounters,
    slices: BTreeMap<String, SliceCounters>,
) -> QualityMetrics {
    let datasets = slices
        .into_iter()
        .map(|(name, value)| {
            let queries = value.queries as f64;
            (
                name,
                DatasetQuality {
                    queries: value.queries,
                    exact_top1_in_candidate_rate: value.top1_candidate as f64 / queries,
                    exact_top10_recall_at_64: value.top10_found as f64
                        / (queries * EXACT_TOP_K as f64),
                    exact_top1_after_rerank_rate: value.top1_reranked as f64 / queries,
                },
            )
        })
        .collect();
    let queries = aggregate.queries as f64;
    QualityMetrics {
        exact_top1_in_candidate_rate: aggregate.top1_candidate as f64 / queries,
        exact_top10_recall_at_64: aggregate.top10_found as f64 / (queries * EXACT_TOP_K as f64),
        exact_top1_after_rerank_rate: aggregate.top1_reranked as f64 / queries,
        exact_top10_ordered_match_rate: aggregate.ordered_top10_matches as f64 / queries,
        datasets,
    }
}

#[allow(clippy::too_many_arguments)]
fn gates(
    bits: u8,
    rows: usize,
    queries: usize,
    datasets: usize,
    quality: &QualityMetrics,
    combined: &Percentiles,
    exact: &Percentiles,
    storage_ratio: f64,
    deterministic: bool,
) -> BitGates {
    let (top1, top10, dataset_top1, storage) = match bits {
        2 => (0.990, 0.990, 0.980, 0.075),
        4 => (0.999, 0.999, 0.995, 0.140),
        _ => unreachable!(),
    };
    let mut result = BitGates {
        corpus_rows_at_least_5000: rows >= 5_000,
        queries_at_least_1000: queries >= 1_000,
        datasets_at_least_3: datasets >= 3,
        aggregate_top1_candidate_recall: quality.exact_top1_in_candidate_rate >= top1,
        aggregate_top10_candidate_recall: quality.exact_top10_recall_at_64 >= top10,
        aggregate_top1_after_rerank: quality.exact_top1_after_rerank_rate >= top1,
        every_dataset_top1_after_rerank: quality
            .datasets
            .values()
            .all(|slice| slice.exact_top1_after_rerank_rate >= dataset_top1),
        p95_candidate_plus_rerank_faster_than_exact: combined.p95 < exact.p95,
        storage_ratio_within_budget: storage_ratio <= storage,
        deterministic_repeat: deterministic,
        benchmark_lane_passed: false,
    };
    result.benchmark_lane_passed = result.corpus_rows_at_least_5000
        && result.queries_at_least_1000
        && result.datasets_at_least_3
        && result.aggregate_top1_candidate_recall
        && result.aggregate_top10_candidate_recall
        && result.aggregate_top1_after_rerank
        && result.every_dataset_top1_after_rerank
        && result.p95_candidate_plus_rerank_faster_than_exact
        && result.storage_ratio_within_budget
        && result.deterministic_repeat;
    result
}

fn percentiles(mut values: Vec<u64>) -> Percentiles {
    values.sort_unstable();
    Percentiles {
        p50: percentile(&values, 50),
        p95: percentile(&values, 95),
        p99: percentile(&values, 99),
        max: values.last().copied().unwrap_or(0),
    }
}

fn percentile(values: &[u64], percent: usize) -> u64 {
    let index = (values.len() * percent).div_ceil(100).saturating_sub(1);
    values.get(index).copied().unwrap_or(0)
}

fn nanos(started: Instant) -> u64 {
    started.elapsed().as_nanos().min(u64::MAX as u128) as u64
}

fn hash_rows(hasher: &mut blake3::Hasher, rows: &[usize]) {
    hasher.update(&(rows.len() as u64).to_le_bytes());
    for row in rows {
        hasher.update(&(*row as u64).to_le_bytes());
    }
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
