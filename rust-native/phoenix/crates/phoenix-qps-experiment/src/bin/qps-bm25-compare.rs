use std::hint::black_box;
use std::time::Instant;

use bm25_turbo::{BM25Builder, BM25Index};
use phoenix_qps_experiment::{
    benchmark_corpus, fixed_match_corpus, judged_fixture, representative_fixture, DocumentInput,
    FieldConfig, FixtureDocument, JudgedQuery, QpsBuilder, QpsConfig, QpsIndex, SearchReceipt,
    SearchScratch,
};

const TOP_K: usize = 10;
const WARM_SAMPLES: usize = 3_000;
const COLD_SAMPLES: usize = 32;
const CACHE_SWEEP_MIB: usize = 128;

#[derive(Clone, Copy)]
struct QueryCase {
    bucket: &'static str,
    text: &'static str,
}

const QUERY_CASES: &[QueryCase] = &[
    QueryCase {
        bucket: "one-token",
        text: "term17",
    },
    QueryCase {
        bucket: "multi-token",
        text: "term17 term203 term411",
    },
    QueryCase {
        bucket: "phrase-like",
        text: "graph memory retrieval",
    },
    QueryCase {
        bucket: "high-frequency",
        text: "term0 term1",
    },
    QueryCase {
        bucket: "fuzzy-miss",
        text: "retrievel memry",
    },
    QueryCase {
        bucket: "no-result",
        text: "neverindexedtoken",
    },
];

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (adversarial_documents, adversarial_queries) = judged_fixture();
    quality_comparison(
        "frozen adversarial",
        &adversarial_documents,
        &adversarial_queries,
    )?;
    let (representative_documents, representative_queries) = representative_fixture();
    quality_comparison(
        "representative ordinary",
        &representative_documents,
        &representative_queries,
    )?;
    paired_query_buckets(10_000)?;
    candidate_set_sensitivity(&[1_000, 10_000, 25_000], 64)?;
    Ok(())
}

fn quality_comparison(
    label: &str,
    documents: &[FixtureDocument],
    queries: &[JudgedQuery],
) -> Result<(), Box<dyn std::error::Error>> {
    let flattened = documents
        .iter()
        .map(FixtureDocument::flattened)
        .collect::<Vec<_>>();
    let borrowed = flattened.iter().map(String::as_str).collect::<Vec<_>>();
    let bm25 = BM25Builder::new().build_from_corpus(&borrowed)?;
    let fields = [
        FieldConfig::new("title", 3.0, 0.35, 0.45),
        FieldConfig::new("body", 1.0, 0.75, 0.15),
    ];
    let mut builder = QpsBuilder::new(fields, QpsConfig::default())?;
    for document in documents {
        let values = [document.title.as_str(), document.body.as_str()];
        builder.insert(DocumentInput {
            external_id: document.external_id,
            fields: &values,
        })?;
    }
    let qps = builder.build()?;
    let mut scratch = SearchScratch::new();
    let mut output = Vec::new();
    let mut qps_rr = 0.0_f64;
    let mut bm25_rr = 0.0_f64;
    let mut qps_recall = 0_u32;
    let mut bm25_recall = 0_u32;
    println!("QUALITY — {label}");
    for query in queries {
        qps.search_into(query.text, documents.len(), &mut scratch, &mut output)?;
        let qps_rank = output
            .iter()
            .position(|hit| hit.external_id == query.relevant_external_id)
            .map(|rank| rank + 1);
        let bm25_results = bm25.search(query.text, documents.len())?;
        let bm25_rank = bm25_results
            .doc_ids
            .iter()
            .position(|document| {
                documents[*document as usize].external_id == query.relevant_external_id
            })
            .map(|rank| rank + 1);
        qps_rr += qps_rank.map_or(0.0, |rank| 1.0 / rank as f64);
        bm25_rr += bm25_rank.map_or(0.0, |rank| 1.0 / rank as f64);
        qps_recall += u32::from(qps_rank.is_some_and(|rank| rank <= 5));
        bm25_recall += u32::from(bm25_rank.is_some_and(|rank| rank <= 5));
        println!(
            "  {:28} positional_rank={:<2?} bm25_rank={:<2?}",
            query.text, qps_rank, bm25_rank
        );
    }
    let count = queries.len() as f64;
    let qps_mrr = qps_rr / count;
    let bm25_mrr = bm25_rr / count;
    println!(
        "  aggregate positional MRR={qps_mrr:.3} R@5={:.3} | BM25 MRR={bm25_mrr:.3} R@5={:.3} | delta MRR={:+.3}",
        qps_recall as f64 / count,
        bm25_recall as f64 / count,
        qps_mrr - bm25_mrr
    );
    println!();
    Ok(())
}

fn paired_query_buckets(documents: usize) -> Result<(), Box<dyn std::error::Error>> {
    let corpus = benchmark_corpus(documents);
    let borrowed = corpus.iter().map(String::as_str).collect::<Vec<_>>();
    let bm25_started = Instant::now();
    let bm25 = BM25Builder::new().build_from_corpus(&borrowed)?;
    let bm25_build_ns = bm25_started.elapsed().as_nanos() as u64;
    let qps_started = Instant::now();
    let qps = build_qps(&corpus, QpsConfig::default())?;
    let qps_build_ns = qps_started.elapsed().as_nanos() as u64;
    let mut cache_sweep = vec![0_u64; CACHE_SWEEP_MIB * 1024 * 1024 / 8];

    println!("PAIRED QUERY-SHAPE BENCHMARK — {documents} documents x 96 tokens");
    println!(
        "  build positional={:.3} ms | BM25={:.3} ms",
        qps_build_ns as f64 / 1_000_000.0,
        bm25_build_ns as f64 / 1_000_000.0
    );
    println!(
        "  warm samples={WARM_SAMPLES}; cold proxy samples={COLD_SAMPLES}; cache sweep={CACHE_SWEEP_MIB} MiB before each engine"
    );
    for case in QUERY_CASES {
        let (receipt, candidate_recall) = candidate_proof(&qps, case.text)?;
        let warm = paired_samples(&bm25, &qps, case.text, WARM_SAMPLES, None)?;
        let cold = paired_samples(&bm25, &qps, case.text, COLD_SAMPLES, Some(&mut cache_sweep))?;
        println!(
            "  bucket={:<14} query={:<29} candidates={:<5} reranked={:<3} rows={:<6} positions={:<6} lane={:?} oracle_recall@{}={:.3}",
            case.bucket,
            case.text,
            receipt.covered_candidates,
            receipt.reranked_candidates,
            receipt.posting_rows_visited,
            receipt.position_values_visited,
            receipt.selection,
            TOP_K,
            candidate_recall
        );
        print_pair("warm", &warm);
        print_pair("cold-proxy", &cold);
    }
    let stats = qps.stats();
    println!(
        "  packed positional index docs={} terms={} rows={} positions={} estimated={:.2} MiB",
        stats.documents,
        stats.terms,
        stats.posting_rows,
        stats.positions,
        stats.estimated_bytes as f64 / (1024.0 * 1024.0)
    );
    println!("  BM25 heap bytes are not exposed by bm25_turbo's public API.");
    println!();
    Ok(())
}

fn candidate_set_sensitivity(
    corpus_sizes: &[usize],
    matching_documents: usize,
) -> Result<(), Box<dyn std::error::Error>> {
    println!("CANDIDATE-SET SENSITIVITY — fixed {matching_documents}-document posting set");
    for &documents in corpus_sizes {
        let corpus = fixed_match_corpus(documents, matching_documents);
        let borrowed = corpus.iter().map(String::as_str).collect::<Vec<_>>();
        let bm25 = BM25Builder::new().build_from_corpus(&borrowed)?;
        let qps = build_qps(&corpus, QpsConfig::default())?;
        let (receipt, candidate_recall) = candidate_proof(&qps, "needle cobalt anchor")?;
        let samples = paired_samples(&bm25, &qps, "needle cobalt anchor", WARM_SAMPLES, None)?;
        let bm25_stats = summarize_unsigned(&samples.bm25_ns);
        let qps_stats = summarize_unsigned(&samples.positional_ns);
        println!(
            "  docs={documents:<6} candidates={:<3} rows={:<4} positions={:<4} oracle_recall@{}={:.3} positional_p99={:>7.3} us bm25_p99={:>7.3} us",
            receipt.covered_candidates,
            receipt.posting_rows_visited,
            receipt.position_values_visited,
            TOP_K,
            candidate_recall,
            ns_to_us(qps_stats.p99),
            ns_to_us(bm25_stats.p99)
        );
    }
    println!();
    Ok(())
}

fn build_qps(corpus: &[String], config: QpsConfig) -> Result<QpsIndex, Box<dyn std::error::Error>> {
    let fields = [FieldConfig::new("body", 1.0, 0.75, 0.0)];
    let mut builder = QpsBuilder::new(fields, config)?;
    for (document, text) in corpus.iter().enumerate() {
        let values = [text.as_str()];
        builder.insert(DocumentInput {
            external_id: document as u64,
            fields: &values,
        })?;
    }
    Ok(builder.build()?)
}

fn candidate_proof(
    qps: &QpsIndex,
    query: &str,
) -> Result<(SearchReceipt, f64), Box<dyn std::error::Error>> {
    let mut bounded_scratch = SearchScratch::new();
    let mut exhaustive_scratch = SearchScratch::new();
    let mut bounded = Vec::with_capacity(TOP_K);
    let mut exhaustive = Vec::with_capacity(TOP_K);
    let receipt = qps.search_into(query, TOP_K, &mut bounded_scratch, &mut bounded)?;
    qps.search_exhaustive_into(query, TOP_K, &mut exhaustive_scratch, &mut exhaustive)?;
    let retained = exhaustive
        .iter()
        .filter(|oracle| {
            bounded
                .iter()
                .any(|candidate| candidate.document == oracle.document)
        })
        .count();
    let recall = if exhaustive.is_empty() {
        f64::from(bounded.is_empty())
    } else {
        retained as f64 / exhaustive.len() as f64
    };
    Ok((receipt, recall))
}

struct PairedSamples {
    bm25_ns: Vec<u64>,
    positional_ns: Vec<u64>,
    delta_ns: Vec<i64>,
}

fn paired_samples(
    bm25: &BM25Index,
    qps: &QpsIndex,
    query: &str,
    iterations: usize,
    mut cache_sweep: Option<&mut [u64]>,
) -> Result<PairedSamples, Box<dyn std::error::Error>> {
    let iterations = iterations.max(1);
    let mut bm25_ns = Vec::with_capacity(iterations);
    let mut positional_ns = Vec::with_capacity(iterations);
    let mut delta_ns = Vec::with_capacity(iterations);
    let mut scratch = SearchScratch::new();
    let mut output = Vec::with_capacity(TOP_K);
    for _ in 0..32 {
        black_box(bm25.search(black_box(query), TOP_K)?);
        black_box(qps.search_into(black_box(query), TOP_K, &mut scratch, &mut output)?);
    }
    for iteration in 0..iterations {
        let (bm25, positional) = if iteration & 1 == 0 {
            let left = timed_bm25(bm25, query, cache_sweep.as_deref_mut())?;
            let right = timed_positional(
                qps,
                query,
                &mut scratch,
                &mut output,
                cache_sweep.as_deref_mut(),
            )?;
            (left, right)
        } else {
            let right = timed_positional(
                qps,
                query,
                &mut scratch,
                &mut output,
                cache_sweep.as_deref_mut(),
            )?;
            let left = timed_bm25(bm25, query, cache_sweep.as_deref_mut())?;
            (left, right)
        };
        bm25_ns.push(bm25);
        positional_ns.push(positional);
        delta_ns.push(positional as i64 - bm25 as i64);
    }
    Ok(PairedSamples {
        bm25_ns,
        positional_ns,
        delta_ns,
    })
}

fn timed_bm25(
    index: &BM25Index,
    query: &str,
    cache_sweep: Option<&mut [u64]>,
) -> Result<u64, Box<dyn std::error::Error>> {
    if let Some(cache) = cache_sweep {
        disturb_cpu_cache(cache);
    }
    let started = Instant::now();
    black_box(index.search(black_box(query), TOP_K)?);
    Ok(started.elapsed().as_nanos() as u64)
}

fn timed_positional(
    index: &QpsIndex,
    query: &str,
    scratch: &mut SearchScratch,
    output: &mut Vec<phoenix_qps_experiment::SearchHit>,
    cache_sweep: Option<&mut [u64]>,
) -> Result<u64, Box<dyn std::error::Error>> {
    if let Some(cache) = cache_sweep {
        disturb_cpu_cache(cache);
    }
    let started = Instant::now();
    black_box(index.search_into(black_box(query), TOP_K, scratch, output)?);
    Ok(started.elapsed().as_nanos() as u64)
}

fn disturb_cpu_cache(cache: &mut [u64]) {
    let mut checksum = 0_u64;
    for index in (0..cache.len()).step_by(8) {
        let value = cache[index].wrapping_add(index as u64 | 1);
        cache[index] = value;
        checksum ^= value.rotate_left((index & 63) as u32);
    }
    black_box(checksum);
}

#[derive(Clone, Copy)]
struct Percentiles<T> {
    median: T,
    p95: T,
    p99: T,
}

fn summarize_unsigned(samples: &[u64]) -> Percentiles<u64> {
    let mut sorted = samples.to_vec();
    sorted.sort_unstable();
    Percentiles {
        median: percentile(&sorted, 50),
        p95: percentile(&sorted, 95),
        p99: percentile(&sorted, 99),
    }
}

fn summarize_signed(samples: &[i64]) -> Percentiles<i64> {
    let mut sorted = samples.to_vec();
    sorted.sort_unstable();
    Percentiles {
        median: percentile(&sorted, 50),
        p95: percentile(&sorted, 95),
        p99: percentile(&sorted, 99),
    }
}

fn percentile<T: Copy>(sorted: &[T], percentile: usize) -> T {
    let index = (sorted.len() - 1) * percentile / 100;
    sorted[index]
}

fn print_pair(label: &str, samples: &PairedSamples) {
    let bm25 = summarize_unsigned(&samples.bm25_ns);
    let positional = summarize_unsigned(&samples.positional_ns);
    let delta = summarize_signed(&samples.delta_ns);
    let relative_p99 = positional.p99 as f64 / bm25.p99.max(1) as f64;
    let absolute_p99 = positional.p99 as i64 - bm25.p99 as i64;
    println!(
        "    {label:<10} BM25 p50/p95/p99={:>7.3}/{:>7.3}/{:>7.3} us | positional={:>7.3}/{:>7.3}/{:>7.3} us",
        ns_to_us(bm25.median),
        ns_to_us(bm25.p95),
        ns_to_us(bm25.p99),
        ns_to_us(positional.median),
        ns_to_us(positional.p95),
        ns_to_us(positional.p99),
    );
    println!(
        "    {:<10} paired delta p50/p95/p99={:>+7.3}/{:>+7.3}/{:>+7.3} us | p99 overhead={relative_p99:.2}x, {:+.3} us",
        "",
        signed_ns_to_us(delta.median),
        signed_ns_to_us(delta.p95),
        signed_ns_to_us(delta.p99),
        signed_ns_to_us(absolute_p99),
    );
}

fn ns_to_us(nanoseconds: u64) -> f64 {
    nanoseconds as f64 / 1_000.0
}

fn signed_ns_to_us(nanoseconds: i64) -> f64 {
    nanoseconds as f64 / 1_000.0
}
