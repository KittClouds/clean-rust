use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Result};
use phoenix_turboquant::{
    BatchSearchScratch, BlockLocalPhaseTimings, BlockLocalTopKConfig, SearchHit, SearchKernel,
    VerifiedQuantizedIndex,
};
use serde::Serialize;

const ROWS: [usize; 2] = [16_384, 100_000];
const BITS: [u8; 2] = [2, 4];
const BATCH_SIZES: [usize; 3] = [1, 4, 8];
const BLOCK_ROWS: [usize; 5] = [256, 512, 1_024, 2_048, 4_096];
const LOCAL_K: [usize; 4] = [64, 72, 96, 128];
const TOTAL_QUERIES: usize = 512;
const QUERY_VARIANTS: usize = 16;
const TOP_K: usize = 64;
const WORKERS: usize = 16;
const COMPACT_CANDIDATE_BYTES: usize = 8;

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
    method: &'static str,
    rows: usize,
    bits: u8,
    batch_queries: usize,
    block_rows: Option<usize>,
    local_k: Option<usize>,
    elapsed_ns: u64,
    queries_per_second: f64,
    batch_latency_p50_ns: u64,
    batch_latency_p95_ns: u64,
    batch_latency_p99_ns: u64,
    corpus_score_slab_bytes: usize,
    hot_score_scratch_bytes: usize,
    local_candidate_publication_bytes: usize,
    phase_timings: Option<BlockLocalPhaseTimings>,
    result_digest: String,
}

fn main() -> Result<()> {
    let mut arguments = std::env::args_os().skip(1);
    let root = PathBuf::from(
        arguments
            .next()
            .ok_or_else(|| anyhow!("usage: block_topk_profile ARTIFACT_DIRECTORY OUTPUT_JSON"))?,
    );
    let output = PathBuf::from(
        arguments
            .next()
            .ok_or_else(|| anyhow!("usage: block_topk_profile ARTIFACT_DIRECTORY OUTPUT_JSON"))?,
    );
    if arguments.next().is_some() {
        bail!("too many arguments");
    }

    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(WORKERS)
        .build()?;
    let mut runs = Vec::with_capacity(ROWS.len() * BITS.len() * BATCH_SIZES.len() * 13);
    for bits in BITS {
        for rows in ROWS {
            let path = root.join(format!("projected-{rows}-{bits}bit.phxq1"));
            let index = VerifiedQuantizedIndex::open(path)?;
            let queries = deterministic_queries(index.dimension());
            for batch_queries in BATCH_SIZES {
                let baseline = pool.install(|| measure_slab(&index, &queries, batch_queries))?;
                let expected_digest = baseline.result_digest.clone();
                print_run(&baseline);
                runs.push(baseline);
                for block_rows in BLOCK_ROWS {
                    for local_k in LOCAL_K {
                        let run = pool.install(|| {
                            measure_block_local(
                                &index,
                                &queries,
                                batch_queries,
                                BlockLocalTopKConfig {
                                    block_rows,
                                    local_k,
                                },
                            )
                        })?;
                        if run.result_digest != expected_digest {
                            bail!(
                                "block-local digest changed for {bits}-bit {rows} rows batch {batch_queries} block {block_rows} local-k {local_k}"
                            );
                        }
                        print_run(&run);
                        runs.push(run);
                    }
                }
            }
        }
    }

    let receipt = Receipt {
        contract: "phoenix-turboquant-block-local-topk-profile/v1",
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

fn measure_slab(
    index: &VerifiedQuantizedIndex,
    queries: &[Vec<f32>],
    batch_queries: usize,
) -> Result<RunReceipt> {
    measure(
        index,
        queries,
        batch_queries,
        None,
        |index, queries, scratch, outputs| {
            index.search_batch_parallel_into(
                queries,
                TOP_K,
                SearchKernel::Auto,
                scratch,
                outputs,
            )?;
            Ok(())
        },
    )
}

fn measure_block_local(
    index: &VerifiedQuantizedIndex,
    queries: &[Vec<f32>],
    batch_queries: usize,
    config: BlockLocalTopKConfig,
) -> Result<RunReceipt> {
    measure(
        index,
        queries,
        batch_queries,
        Some(config),
        |index, queries, scratch, outputs| {
            index.search_batch_block_local_into(
                queries,
                TOP_K,
                SearchKernel::Auto,
                config,
                scratch,
                outputs,
            )?;
            Ok(())
        },
    )
}

fn measure<F>(
    index: &VerifiedQuantizedIndex,
    queries: &[Vec<f32>],
    batch_queries: usize,
    config: Option<BlockLocalTopKConfig>,
    mut search: F,
) -> Result<RunReceipt>
where
    F: FnMut(
        &VerifiedQuantizedIndex,
        &[Vec<f32>],
        &mut BatchSearchScratch,
        &mut [Vec<SearchHit>],
    ) -> Result<()>,
{
    let mut scratch = BatchSearchScratch::new(index.dimension(), batch_queries, TOP_K);
    let mut outputs = (0..batch_queries)
        .map(|_| Vec::with_capacity(TOP_K))
        .collect::<Vec<_>>();
    search(index, &queries[..batch_queries], &mut scratch, &mut outputs)?;

    let start = Instant::now();
    let mut latencies = Vec::with_capacity(TOTAL_QUERIES / batch_queries);
    let mut digest = [0u8; 32];
    for first_query in (0..TOTAL_QUERIES).step_by(batch_queries) {
        let batch_start = Instant::now();
        search(
            index,
            &queries[first_query..first_query + batch_queries],
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
    let phase_timings = config
        .map(|config| {
            index.profile_batch_block_local_into(
                &queries[..batch_queries],
                TOP_K,
                SearchKernel::Auto,
                config,
                &mut scratch,
                &mut outputs,
            )
        })
        .transpose()?;
    let corpus_score_slab_bytes = index.len() * batch_queries * size_of::<f32>();
    let (method, block_rows, local_k, hot_score_scratch_bytes, publication_bytes) = match config {
        None => ("corpus_score_slab", None, None, corpus_score_slab_bytes, 0),
        Some(config) => (
            "block_local_topk",
            Some(config.block_rows),
            Some(config.local_k),
            config.block_rows * batch_queries * size_of::<f32>(),
            index.len().div_ceil(config.block_rows)
                * batch_queries
                * config.local_k
                * COMPACT_CANDIDATE_BYTES,
        ),
    };
    Ok(RunReceipt {
        method,
        rows: index.len(),
        bits: index.bits(),
        batch_queries,
        block_rows,
        local_k,
        elapsed_ns: nanos(elapsed),
        queries_per_second: TOTAL_QUERIES as f64 / elapsed.as_secs_f64(),
        batch_latency_p50_ns: percentile(&latencies, 50),
        batch_latency_p95_ns: percentile(&latencies, 95),
        batch_latency_p99_ns: percentile(&latencies, 99),
        corpus_score_slab_bytes: if config.is_none() {
            corpus_score_slab_bytes
        } else {
            0
        },
        hot_score_scratch_bytes,
        local_candidate_publication_bytes: publication_bytes,
        phase_timings,
        result_digest: hex(digest),
    })
}

fn print_run(run: &RunReceipt) {
    println!(
        "rows={:>6} bits={} batch={} method={:<18} block={:>4} local_k={:>3} qps={:>8.1} p95={:>8}ns",
        run.rows,
        run.bits,
        run.batch_queries,
        run.method,
        run.block_rows.unwrap_or(0),
        run.local_k.unwrap_or(0),
        run.queries_per_second,
        run.batch_latency_p95_ns,
    );
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
