use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Result};
use phoenix_turboquant::{BatchSearchScratch, SearchHit, SearchKernel, VerifiedQuantizedIndex};
use serde::Serialize;

const ROWS: [usize; 2] = [16_384, 100_000];
const BITS: [u8; 2] = [2, 4];
const BATCH_SIZES: [usize; 4] = [1, 2, 4, 8];
const TOTAL_QUERIES: usize = 512;
const QUERY_VARIANTS: usize = 16;
const TOP_K: usize = 64;
const WORKERS: usize = 16;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Receipt {
    contract: &'static str,
    total_queries: usize,
    query_variants: usize,
    top_k: usize,
    workers: usize,
    runs: Vec<RunReceipt>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RunReceipt {
    rows: usize,
    bits: u8,
    batch_queries: usize,
    elapsed_ns: u64,
    queries_per_second: f64,
    batch_latency_p50_ns: u64,
    batch_latency_p95_ns: u64,
    batch_latency_p99_ns: u64,
    result_digest: String,
}

fn main() -> Result<()> {
    let mut arguments = std::env::args_os().skip(1);
    let root = PathBuf::from(
        arguments
            .next()
            .ok_or_else(|| anyhow!("usage: batch_profile ARTIFACT_DIRECTORY OUTPUT_JSON"))?,
    );
    let output = PathBuf::from(
        arguments
            .next()
            .ok_or_else(|| anyhow!("usage: batch_profile ARTIFACT_DIRECTORY OUTPUT_JSON"))?,
    );
    if arguments.next().is_some() {
        bail!("too many arguments");
    }

    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(WORKERS)
        .build()?;
    let mut runs = Vec::with_capacity(ROWS.len() * BITS.len() * BATCH_SIZES.len());
    for bits in BITS {
        for rows in ROWS {
            let path = root.join(format!("projected-{rows}-{bits}bit.phxq1"));
            let index = VerifiedQuantizedIndex::open(path)?;
            let scheduled_queries = deterministic_queries(index.dimension());
            let mut expected_digest = None;
            for batch_queries in BATCH_SIZES {
                let run = pool.install(|| measure(&index, &scheduled_queries, batch_queries))?;
                if let Some(expected) = &expected_digest {
                    if expected != &run.result_digest {
                        bail!(
                            "batch result digest changed for {bits}-bit {rows} rows at batch {batch_queries}"
                        );
                    }
                } else {
                    expected_digest = Some(run.result_digest.clone());
                }
                println!(
                    "rows={rows:>6} bits={bits} batch={batch_queries} workers={WORKERS} qps={:>8.1} batch_p95={:>8}ns",
                    run.queries_per_second, run.batch_latency_p95_ns
                );
                runs.push(run);
            }
        }
    }

    let receipt = Receipt {
        contract: "phoenix-turboquant-packed-block-batch-profile/v1",
        total_queries: TOTAL_QUERIES,
        query_variants: QUERY_VARIANTS,
        top_k: TOP_K,
        workers: WORKERS,
        runs,
    };
    let bytes = serde_json::to_vec_pretty(&receipt)?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&output)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    println!("receipt={}", output.display());
    Ok(())
}

fn measure(
    index: &VerifiedQuantizedIndex,
    scheduled_queries: &[Vec<f32>],
    batch_queries: usize,
) -> Result<RunReceipt> {
    let mut scratch = BatchSearchScratch::new(index.dimension(), batch_queries, TOP_K);
    let mut outputs = (0..batch_queries)
        .map(|_| Vec::with_capacity(TOP_K))
        .collect::<Vec<_>>();
    index.search_batch_parallel_into(
        &scheduled_queries[..batch_queries],
        TOP_K,
        SearchKernel::Auto,
        &mut scratch,
        &mut outputs,
    )?;

    let start = Instant::now();
    let mut latencies = Vec::with_capacity(TOTAL_QUERIES / batch_queries);
    let mut digest = [0u8; 32];
    for first_query in (0..TOTAL_QUERIES).step_by(batch_queries) {
        let batch_start = Instant::now();
        index.search_batch_parallel_into(
            &scheduled_queries[first_query..first_query + batch_queries],
            TOP_K,
            SearchKernel::Auto,
            &mut scratch,
            &mut outputs,
        )?;
        latencies.push(nanos(batch_start.elapsed()));
        for (offset, output) in outputs.iter().enumerate() {
            xor_digest(&mut digest, first_query + offset, output);
        }
    }
    let elapsed = start.elapsed();
    latencies.sort_unstable();
    Ok(RunReceipt {
        rows: index.len(),
        bits: index.bits(),
        batch_queries,
        elapsed_ns: nanos(elapsed),
        queries_per_second: TOTAL_QUERIES as f64 / elapsed.as_secs_f64(),
        batch_latency_p50_ns: percentile(&latencies, 50),
        batch_latency_p95_ns: percentile(&latencies, 95),
        batch_latency_p99_ns: percentile(&latencies, 99),
        result_digest: hex(digest),
    })
}

fn deterministic_queries(dimension: usize) -> Vec<Vec<f32>> {
    (0..TOTAL_QUERIES)
        .map(|query_id| {
            let variant = query_id % QUERY_VARIANTS;
            let mut query = (0..dimension)
                .map(|column| (((column * 29 + variant * 43 + 7) % 251) as f32 / 125.0) - 1.0)
                .collect::<Vec<_>>();
            let inverse = query
                .iter()
                .map(|value| value * value)
                .sum::<f32>()
                .sqrt()
                .recip();
            for value in &mut query {
                *value *= inverse;
            }
            query
        })
        .collect()
}

fn xor_digest(digest: &mut [u8; 32], query_id: usize, output: &[SearchHit]) {
    let mut hasher = blake3::Hasher::new();
    hasher.update(&(query_id as u64).to_le_bytes());
    for hit in output {
        hasher.update(&(hit.row as u64).to_le_bytes());
        hasher.update(&hit.subject_id.to_le_bytes());
        hasher.update(&hit.score.to_bits().to_le_bytes());
    }
    for (destination, source) in digest.iter_mut().zip(hasher.finalize().as_bytes()) {
        *destination ^= source;
    }
}

fn percentile(values: &[u64], percentile: usize) -> u64 {
    values[(values.len() * percentile / 100).min(values.len() - 1)]
}

fn nanos(duration: Duration) -> u64 {
    duration.as_nanos().min(u64::MAX as u128) as u64
}

fn hex(bytes: [u8; 32]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
