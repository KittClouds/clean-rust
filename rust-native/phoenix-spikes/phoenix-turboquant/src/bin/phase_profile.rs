use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::time::Instant;

use phoenix_turboquant::{
    profile_exact_parallel_search_into, ExactPhaseTimings, ExactSearchScratch, PhaseTimings,
    SearchKernel, SearchScratch, VerifiedQuantizedIndex,
};
use serde::Serialize;

const ROWS: [usize; 5] = [1_024, 4_096, 16_384, 65_536, 100_000];
const BITS: [u8; 2] = [2, 4];
const WORKERS: [usize; 5] = [1, 2, 4, 8, 16];
const SAMPLES: usize = 21;

#[derive(Serialize)]
struct Receipt {
    schema: &'static str,
    samples: usize,
    phases: Vec<PhaseMedian>,
    top_k_sweep_16384: Vec<TopKMedian>,
    worker_sweep: Vec<WorkerMedian>,
    exact_worker_sweep: Vec<ExactWorkerMedian>,
}

#[derive(Serialize)]
struct PhaseMedian {
    rows: usize,
    bits: u8,
    kernel: SearchKernel,
    query_rotation_ns: u64,
    query_lut_ns: u64,
    artifact_traversal_decode_accumulate_ns: u64,
    scale_correction_ns: u64,
    top_k_ns: u64,
    result_materialization_ns: u64,
    diagnostic_total_ns: u64,
    prepared_fused_search_ns: u64,
}

#[derive(Serialize)]
struct TopKMedian {
    bits: u8,
    top_k: usize,
    scan_ns: u64,
    top_k_ns: u64,
    materialization_ns: u64,
    total_ns: u64,
}

#[derive(Serialize)]
struct WorkerMedian {
    bits: u8,
    rows: usize,
    workers: usize,
    orchestration_ns: u64,
    scan_ns: u64,
    scale_ns: u64,
    top_k_ns: u64,
    total_ns: u64,
}

#[derive(Serialize)]
struct ExactWorkerMedian {
    rows: usize,
    workers: usize,
    orchestration_ns: u64,
    dot_ns: u64,
    top_k_ns: u64,
    total_ns: u64,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = std::env::args_os().skip(1);
    let root = PathBuf::from(
        arguments
            .next()
            .ok_or("usage: phase_profile ARTIFACT_DIRECTORY OUTPUT_JSON")?,
    );
    let output = PathBuf::from(
        arguments
            .next()
            .ok_or("usage: phase_profile ARTIFACT_DIRECTORY OUTPUT_JSON")?,
    );
    if arguments.next().is_some() {
        return Err("too many arguments".into());
    }

    let mut phases = Vec::with_capacity(ROWS.len() * BITS.len());
    let mut top_k_sweep = Vec::new();
    let pools: Vec<(usize, rayon::ThreadPool)> = WORKERS
        .into_iter()
        .map(|workers| {
            Ok((
                workers,
                rayon::ThreadPoolBuilder::new()
                    .num_threads(workers)
                    .build()?,
            ))
        })
        .collect::<Result<_, rayon::ThreadPoolBuildError>>()?;
    let mut worker_sweep = Vec::with_capacity(ROWS.len() * BITS.len() * pools.len());
    for bits in BITS {
        for rows in ROWS {
            let path = root.join(format!("projected-{rows}-{bits}bit.phxq1"));
            let index = VerifiedQuantizedIndex::open(path)?;
            let query = deterministic_query(index.dimension());
            let median = phase_median(&index, &query, 64)?;
            println!(
                "rows={rows:>6} bits={bits} rotate={:>7}ns lut={:>8}ns scan={:>8}ns scale={:>6}ns topk={:>7}ns fused={:>8}ns",
                median.query_rotation_ns,
                median.query_lut_ns,
                median.artifact_traversal_decode_accumulate_ns,
                median.scale_correction_ns,
                median.top_k_ns,
                median.prepared_fused_search_ns,
            );
            phases.push(PhaseMedian {
                rows,
                bits,
                ..median
            });
            for (workers, pool) in &pools {
                worker_sweep.push(parallel_phase_median(pool, *workers, &index, &query, 64)?);
            }
            if rows == 16_384 {
                for top_k in [0, 1, 8, 32, 64] {
                    let phase = phase_median(&index, &query, top_k)?;
                    top_k_sweep.push(TopKMedian {
                        bits,
                        top_k,
                        scan_ns: phase.artifact_traversal_decode_accumulate_ns,
                        top_k_ns: phase.top_k_ns,
                        materialization_ns: phase.result_materialization_ns,
                        total_ns: phase.diagnostic_total_ns,
                    });
                }
            }
        }
    }
    let max_rows = *ROWS.last().unwrap();
    let exact_vectors = normalized_vectors(max_rows, 768);
    let exact_ids: Vec<u64> = (1..=max_rows as u64).collect();
    let exact_query = deterministic_query(768);
    let mut exact_worker_sweep = Vec::with_capacity(ROWS.len() * pools.len());
    for rows in ROWS {
        for (workers, pool) in &pools {
            exact_worker_sweep.push(exact_parallel_median(
                pool,
                *workers,
                &exact_vectors[..rows * 768],
                &exact_ids[..rows],
                &exact_query,
            )?);
        }
    }
    let receipt = Receipt {
        schema: "phoenix-turboquant-phase-profile/v1",
        samples: SAMPLES,
        phases,
        top_k_sweep_16384: top_k_sweep,
        worker_sweep,
        exact_worker_sweep,
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

fn exact_parallel_median(
    pool: &rayon::ThreadPool,
    workers: usize,
    vectors: &[f32],
    ids: &[u64],
    query: &[f32],
) -> Result<ExactWorkerMedian, Box<dyn std::error::Error>> {
    let mut scratch = ExactSearchScratch::new(64);
    let mut output = Vec::with_capacity(64);
    pool.install(|| {
        profile_exact_parallel_search_into(vectors, ids, 768, query, 64, &mut scratch, &mut output)
    })?;
    let mut samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        samples.push(pool.install(|| {
            profile_exact_parallel_search_into(
                vectors,
                ids,
                768,
                query,
                64,
                &mut scratch,
                &mut output,
            )
        })?);
    }
    Ok(ExactWorkerMedian {
        rows: ids.len(),
        workers,
        orchestration_ns: exact_median_field(&samples, |sample| sample.thread_orchestration_ns),
        dot_ns: exact_median_field(&samples, |sample| sample.dot_accumulation_ns),
        top_k_ns: exact_median_field(&samples, |sample| sample.top_k_ns),
        total_ns: exact_median_field(&samples, |sample| sample.total_ns),
    })
}

fn parallel_phase_median(
    pool: &rayon::ThreadPool,
    workers: usize,
    index: &VerifiedQuantizedIndex,
    query: &[f32],
    top_k: usize,
) -> Result<WorkerMedian, Box<dyn std::error::Error>> {
    let mut scratch = SearchScratch::new(index.dimension(), top_k);
    let mut output = Vec::with_capacity(top_k);
    pool.install(|| {
        index.profile_parallel_search_into(
            query,
            top_k,
            SearchKernel::Auto,
            &mut scratch,
            &mut output,
        )
    })?;
    let mut samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        samples.push(pool.install(|| {
            index.profile_parallel_search_into(
                query,
                top_k,
                SearchKernel::Auto,
                &mut scratch,
                &mut output,
            )
        })?);
    }
    Ok(WorkerMedian {
        bits: index.bits(),
        rows: index.len(),
        workers,
        orchestration_ns: median_field(&samples, |sample| sample.thread_orchestration_ns),
        scan_ns: median_field(&samples, |sample| {
            sample.artifact_traversal_decode_accumulate_ns
        }),
        scale_ns: median_field(&samples, |sample| sample.scale_correction_ns),
        top_k_ns: median_field(&samples, |sample| sample.top_k_ns),
        total_ns: median_field(&samples, |sample| sample.total_ns),
    })
}

fn phase_median(
    index: &VerifiedQuantizedIndex,
    query: &[f32],
    top_k: usize,
) -> Result<PhaseMedian, Box<dyn std::error::Error>> {
    let mut scratch = SearchScratch::new(index.dimension(), top_k);
    let mut output = Vec::with_capacity(top_k);
    index.profile_search_into(query, top_k, SearchKernel::Auto, &mut scratch, &mut output)?;
    let mut samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        samples.push(index.profile_search_into(
            query,
            top_k,
            SearchKernel::Auto,
            &mut scratch,
            &mut output,
        )?);
    }
    index.prepare_query(query, &mut scratch)?;
    index.search_prepared_into(top_k, SearchKernel::Auto, &mut scratch, &mut output)?;
    let mut fused = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        let start = Instant::now();
        index.search_prepared_into(top_k, SearchKernel::Auto, &mut scratch, &mut output)?;
        fused.push(nanos(start.elapsed()));
    }
    Ok(PhaseMedian {
        rows: index.len(),
        bits: index.bits(),
        kernel: samples[0].kernel,
        query_rotation_ns: median_field(&samples, |sample| sample.query_rotation_ns),
        query_lut_ns: median_field(&samples, |sample| sample.query_lut_ns),
        artifact_traversal_decode_accumulate_ns: median_field(&samples, |sample| {
            sample.artifact_traversal_decode_accumulate_ns
        }),
        scale_correction_ns: median_field(&samples, |sample| sample.scale_correction_ns),
        top_k_ns: median_field(&samples, |sample| sample.top_k_ns),
        result_materialization_ns: median_field(&samples, |sample| {
            sample.result_materialization_ns
        }),
        diagnostic_total_ns: median_field(&samples, |sample| sample.total_ns),
        prepared_fused_search_ns: median(&mut fused),
    })
}

fn median_field(samples: &[PhaseTimings], field: impl Fn(&PhaseTimings) -> u64) -> u64 {
    let mut values: Vec<u64> = samples.iter().map(field).collect();
    median(&mut values)
}

fn exact_median_field(
    samples: &[ExactPhaseTimings],
    field: impl Fn(&ExactPhaseTimings) -> u64,
) -> u64 {
    let mut values: Vec<u64> = samples.iter().map(field).collect();
    median(&mut values)
}

fn median(values: &mut [u64]) -> u64 {
    values.sort_unstable();
    values[values.len() / 2]
}

fn deterministic_query(dimension: usize) -> Vec<f32> {
    let mut query: Vec<f32> = (0..dimension)
        .map(|column| (((column * 29 + 17) % 251) as f32 / 125.0) - 1.0)
        .collect();
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

fn normalized_vectors(rows: usize, dimension: usize) -> Vec<f32> {
    let mut vectors = Vec::with_capacity(rows * dimension);
    for row in 0..rows {
        let start = vectors.len();
        let mut norm = 0.0f32;
        for column in 0..dimension {
            let value = ((((row + 1) * 131 + column * 17) % 997) as f32 / 498.5) - 1.0;
            norm += value * value;
            vectors.push(value);
        }
        let inverse = norm.sqrt().recip();
        for value in &mut vectors[start..] {
            *value *= inverse;
        }
    }
    vectors
}

fn nanos(duration: std::time::Duration) -> u64 {
    duration.as_nanos().min(u64::MAX as u128) as u64
}
