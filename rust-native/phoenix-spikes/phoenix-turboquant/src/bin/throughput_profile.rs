use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::{Arc, Barrier};
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Result};
use phoenix_turboquant::{
    SearchExecution, SearchHit, SearchKernel, SearchScratch, VerifiedQuantizedIndex,
};
use serde::Serialize;

const ROWS: [usize; 2] = [16_384, 100_000];
const BITS: [u8; 2] = [2, 4];
const TOTAL_QUERIES: usize = 512;
const QUERY_VARIANTS: usize = 16;
const TOP_K: usize = 64;
const CONFIGS: [(usize, usize); 15] = [
    (1, 1),
    (1, 2),
    (1, 4),
    (1, 8),
    (1, 16),
    (2, 1),
    (2, 2),
    (2, 4),
    (2, 8),
    (4, 1),
    (4, 2),
    (4, 4),
    (8, 1),
    (8, 2),
    (16, 1),
];

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Receipt {
    contract: &'static str,
    total_queries: usize,
    query_variants: usize,
    top_k: usize,
    runs: Vec<RunReceipt>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RunReceipt {
    rows: usize,
    bits: u8,
    concurrent_queries: usize,
    workers_per_query: usize,
    total_worker_threads: usize,
    elapsed_ns: u64,
    queries_per_second: f64,
    latency_p50_ns: u64,
    latency_p95_ns: u64,
    latency_p99_ns: u64,
    result_digest: String,
}

struct LaneResult {
    elapsed: Duration,
    latencies: Vec<u64>,
    digest: [u8; 32],
}

fn main() -> Result<()> {
    let mut arguments = std::env::args_os().skip(1);
    let root = PathBuf::from(
        arguments
            .next()
            .ok_or_else(|| anyhow!("usage: throughput_profile ARTIFACT_DIRECTORY OUTPUT_JSON"))?,
    );
    let output = PathBuf::from(
        arguments
            .next()
            .ok_or_else(|| anyhow!("usage: throughput_profile ARTIFACT_DIRECTORY OUTPUT_JSON"))?,
    );
    if arguments.next().is_some() {
        bail!("too many arguments");
    }

    let mut runs = Vec::with_capacity(ROWS.len() * BITS.len() * CONFIGS.len());
    for bits in BITS {
        for rows in ROWS {
            let path = root.join(format!("projected-{rows}-{bits}bit.phxq1"));
            let index = VerifiedQuantizedIndex::open(path)?;
            let queries = deterministic_queries(index.dimension());
            let mut expected_digest = None;
            for (concurrent_queries, workers_per_query) in CONFIGS {
                let run = measure(&index, &queries, concurrent_queries, workers_per_query)?;
                if let Some(expected) = &expected_digest {
                    if expected != &run.result_digest {
                        bail!(
                            "result digest changed for {bits}-bit {rows} rows at {concurrent_queries}x{workers_per_query}"
                        );
                    }
                } else {
                    expected_digest = Some(run.result_digest.clone());
                }
                println!(
                    "rows={rows:>6} bits={bits} queries={concurrent_queries:>2} workers={workers_per_query:>2} qps={:>8.1} p95={:>8}ns",
                    run.queries_per_second, run.latency_p95_ns
                );
                runs.push(run);
            }
        }
    }

    let receipt = Receipt {
        contract: "phoenix-turboquant-throughput-profile/v1",
        total_queries: TOTAL_QUERIES,
        query_variants: QUERY_VARIANTS,
        top_k: TOP_K,
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
    queries: &[Vec<f32>],
    concurrent_queries: usize,
    workers_per_query: usize,
) -> Result<RunReceipt> {
    let barrier = Arc::new(Barrier::new(concurrent_queries));
    let lane_results = std::thread::scope(|scope| {
        let mut handles = Vec::with_capacity(concurrent_queries);
        for lane in 0..concurrent_queries {
            let barrier = Arc::clone(&barrier);
            handles.push(scope.spawn(move || {
                run_lane(
                    index,
                    queries,
                    lane,
                    concurrent_queries,
                    workers_per_query,
                    barrier,
                )
            }));
        }
        handles
            .into_iter()
            .map(|handle| {
                handle
                    .join()
                    .map_err(|_| anyhow!("throughput lane panicked"))?
            })
            .collect::<Result<Vec<_>>>()
    })?;

    let elapsed = lane_results
        .iter()
        .map(|lane| lane.elapsed)
        .max()
        .unwrap_or_default();
    let mut latencies = Vec::with_capacity(TOTAL_QUERIES);
    let mut digest = [0u8; 32];
    for lane in lane_results {
        latencies.extend(lane.latencies);
        for (destination, source) in digest.iter_mut().zip(lane.digest) {
            *destination ^= source;
        }
    }
    latencies.sort_unstable();
    Ok(RunReceipt {
        rows: index.len(),
        bits: index.bits(),
        concurrent_queries,
        workers_per_query,
        total_worker_threads: concurrent_queries * workers_per_query,
        elapsed_ns: nanos(elapsed),
        queries_per_second: TOTAL_QUERIES as f64 / elapsed.as_secs_f64(),
        latency_p50_ns: percentile(&latencies, 50),
        latency_p95_ns: percentile(&latencies, 95),
        latency_p99_ns: percentile(&latencies, 99),
        result_digest: hex(digest),
    })
}

fn run_lane(
    index: &VerifiedQuantizedIndex,
    queries: &[Vec<f32>],
    lane: usize,
    concurrent_queries: usize,
    workers_per_query: usize,
    barrier: Arc<Barrier>,
) -> Result<LaneResult> {
    let pool = (workers_per_query > 1)
        .then(|| {
            rayon::ThreadPoolBuilder::new()
                .num_threads(workers_per_query)
                .build()
        })
        .transpose()?;
    let execution = if pool.is_some() {
        SearchExecution::Rayon
    } else {
        SearchExecution::Serial
    };
    let mut scratch = SearchScratch::new(index.dimension(), TOP_K);
    let mut output = Vec::with_capacity(TOP_K);
    run_query(
        index,
        &queries[lane % queries.len()],
        execution,
        pool.as_ref(),
        &mut scratch,
        &mut output,
    )?;
    barrier.wait();
    let lane_start = Instant::now();
    let mut latencies = Vec::with_capacity(TOTAL_QUERIES.div_ceil(concurrent_queries));
    let mut digest = [0u8; 32];
    for query_id in (lane..TOTAL_QUERIES).step_by(concurrent_queries) {
        let start = Instant::now();
        run_query(
            index,
            &queries[query_id % queries.len()],
            execution,
            pool.as_ref(),
            &mut scratch,
            &mut output,
        )?;
        latencies.push(nanos(start.elapsed()));
        xor_digest(&mut digest, query_id, &output);
    }
    Ok(LaneResult {
        elapsed: lane_start.elapsed(),
        latencies,
        digest,
    })
}

fn run_query(
    index: &VerifiedQuantizedIndex,
    query: &[f32],
    execution: SearchExecution,
    pool: Option<&rayon::ThreadPool>,
    scratch: &mut SearchScratch,
    output: &mut Vec<SearchHit>,
) -> Result<()> {
    let mut search = || -> phoenix_turboquant::Result<()> {
        index.prepare_query(query, scratch)?;
        index.search_prepared_with_execution_into(
            TOP_K,
            SearchKernel::Auto,
            execution,
            scratch,
            output,
        )?;
        Ok(())
    };
    match pool {
        Some(pool) => pool.install(search)?,
        None => search()?,
    }
    Ok(())
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

fn deterministic_queries(dimension: usize) -> Vec<Vec<f32>> {
    (0..QUERY_VARIANTS)
        .map(|variant| {
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

fn percentile(values: &[u64], percentile: usize) -> u64 {
    values[(values.len() * percentile / 100).min(values.len() - 1)]
}

fn nanos(duration: Duration) -> u64 {
    duration.as_nanos().min(u64::MAX as u128) as u64
}

fn hex(bytes: [u8; 32]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
