use std::fs::OpenOptions;
use std::hint::black_box;
use std::io::Write;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Result};
use phoenix_turboquant::{SearchExecution, SearchKernel, SearchScratch, VerifiedQuantizedIndex};
use serde::Serialize;

const ROWS: [usize; 5] = [1_024, 4_096, 16_384, 65_536, 100_000];
const BITS: [u8; 2] = [2, 4];
const WORKERS: [usize; 5] = [1, 2, 4, 8, 16];
const SAMPLES: usize = 51;
const TOP_K: usize = 64;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Receipt {
    contract: &'static str,
    samples: usize,
    top_k: usize,
    runs: Vec<RunReceipt>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RunReceipt {
    rows: usize,
    bits: u8,
    workers: usize,
    execution: SearchExecution,
    median_ns: u64,
    p95_ns: u64,
    ns_per_row: f64,
    output_hash: String,
}

fn main() -> Result<()> {
    let mut arguments = std::env::args_os().skip(1);
    let root = PathBuf::from(
        arguments
            .next()
            .ok_or_else(|| anyhow!("usage: physics_profile ARTIFACT_DIRECTORY OUTPUT_JSON"))?,
    );
    let output = PathBuf::from(
        arguments
            .next()
            .ok_or_else(|| anyhow!("usage: physics_profile ARTIFACT_DIRECTORY OUTPUT_JSON"))?,
    );
    if arguments.next().is_some() {
        bail!("too many arguments");
    }

    let pools = WORKERS
        .into_iter()
        .map(|workers| {
            Ok((
                workers,
                rayon::ThreadPoolBuilder::new()
                    .num_threads(workers)
                    .build()?,
            ))
        })
        .collect::<Result<Vec<_>, rayon::ThreadPoolBuildError>>()?;
    let mut runs = Vec::with_capacity(ROWS.len() * BITS.len() * WORKERS.len());
    for bits in BITS {
        for rows in ROWS {
            let path = root.join(format!("projected-{rows}-{bits}bit.phxq1"));
            let index = VerifiedQuantizedIndex::open(path)?;
            let query = deterministic_query(index.dimension());
            for (workers, pool) in &pools {
                let execution = if *workers == 1 {
                    SearchExecution::Serial
                } else {
                    SearchExecution::Rayon
                };
                let run = pool.install(|| measure(&index, &query, *workers, execution))?;
                println!(
                    "rows={rows:>6} bits={bits} workers={workers:>2} median={:>8}ns p95={:>8}ns",
                    run.median_ns, run.p95_ns
                );
                runs.push(run);
            }
        }
    }

    let receipt = Receipt {
        contract: "phoenix-turboquant-physics-profile/v1",
        samples: SAMPLES,
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
    query: &[f32],
    workers: usize,
    execution: SearchExecution,
) -> Result<RunReceipt> {
    let mut scratch = SearchScratch::new(index.dimension(), TOP_K);
    let mut output = Vec::with_capacity(TOP_K);
    index.prepare_query(query, &mut scratch)?;
    for _ in 0..2 {
        index.search_prepared_with_execution_into(
            TOP_K,
            SearchKernel::Auto,
            execution,
            &mut scratch,
            &mut output,
        )?;
    }
    let mut samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        let start = Instant::now();
        index.search_prepared_with_execution_into(
            TOP_K,
            SearchKernel::Auto,
            execution,
            &mut scratch,
            &mut output,
        )?;
        samples.push(nanos(start.elapsed()));
        black_box(&output);
    }
    samples.sort_unstable();
    let median_ns = samples[SAMPLES / 2];
    let p95_ns = samples[(SAMPLES * 95 / 100).min(SAMPLES - 1)];
    Ok(RunReceipt {
        rows: index.len(),
        bits: index.bits(),
        workers,
        execution,
        median_ns,
        p95_ns,
        ns_per_row: median_ns as f64 / index.len() as f64,
        output_hash: output_hash(&output),
    })
}

fn output_hash(output: &[phoenix_turboquant::SearchHit]) -> String {
    let mut hasher = blake3::Hasher::new();
    for hit in output {
        hasher.update(&(hit.row as u64).to_le_bytes());
        hasher.update(&hit.subject_id.to_le_bytes());
        hasher.update(&hit.score.to_bits().to_le_bytes());
    }
    hasher.finalize().to_hex().to_string()
}

fn deterministic_query(dimension: usize) -> Vec<f32> {
    let mut query = (0..dimension)
        .map(|column| (((column * 29 + 7) % 251) as f32 / 125.0) - 1.0)
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
}

fn nanos(duration: Duration) -> u64 {
    duration.as_nanos().min(u64::MAX as u128) as u64
}
