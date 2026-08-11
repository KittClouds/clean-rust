use std::path::PathBuf;
use std::time::{Duration, Instant};

use phoenix_memory_embeddings::VerifiedEmbeddingPagesV1;
use phoenix_turboquant::{
    exact_search, exact_search_into, write_quantized_artifact_new, ArtifactAuthority,
    ExactSearchScratch, SearchExecution, SearchHit, SearchKernel, SearchScratch,
    VerifiedQuantizedIndex,
};
use serde::Serialize;

const DEFAULT_SOURCE: &str = r"D:\phoenix-memory-embedding-proof\embeddinggemma-pages-v1.phxe1";
const PROJECTED_ROWS: [usize; 5] = [1_024, 4_096, 16_384, 65_536, 100_000];
const EXTRAPOLATED_ROWS: [usize; 1] = [1_000_000];
const TOP_K: usize = 64;
const TIMED_QUERIES: usize = 12;

#[derive(Serialize)]
struct ProofReceipt {
    schema: &'static str,
    implementation_scope: &'static str,
    source: SourceReceipt,
    machine: MachineReceipt,
    real_quality: Vec<QualityReceipt>,
    measured_cohorts: Vec<CohortReceipt>,
    arithmetic_projections: Vec<ProjectionReceipt>,
    caveats: [&'static str; 4],
}

#[derive(Serialize)]
struct SourceReceipt {
    path: String,
    rows: usize,
    dimension: usize,
    f32_vector_bytes: u64,
    artifact_hash: String,
    generation_hash: String,
    model_identity_hash: String,
}

#[derive(Serialize)]
struct MachineReceipt {
    architecture: &'static str,
    operating_system: &'static str,
    logical_parallelism: usize,
    avx2: bool,
}

#[derive(Serialize)]
struct QualityReceipt {
    bits: u8,
    self_query_count: usize,
    midpoint_query_count: usize,
    self_query_top1_accuracy: f64,
    midpoint_mean_exact_top3_overlap_at_3: f64,
    kernel: SearchKernel,
    artifact_bytes: u64,
}

#[derive(Serialize)]
struct CohortReceipt {
    bits: u8,
    rows: usize,
    dimension: usize,
    f32_vector_bytes: u64,
    quantized_artifact_bytes: u64,
    compression_ratio: f64,
    build_write_verify_ms: f64,
    mmap_open_verify_ms: f64,
    exact_top64_us: Percentiles,
    quantized_top64_us: Percentiles,
    observed_kernel: SearchKernel,
    execution: SearchExecution,
    recall_query_count: usize,
    exact_top1_recall_at_64: f64,
}

#[derive(Clone, Copy, Serialize)]
struct Percentiles {
    p50: f64,
    p95: f64,
}

#[derive(Serialize)]
struct ProjectionReceipt {
    bits: u8,
    rows: usize,
    projected_f32_vector_bytes: u64,
    projected_quantized_bytes: u64,
    projected_exact_top64_p50_us: f64,
    projected_quantized_top64_p50_us: f64,
    method: &'static str,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (source_path, output_root) = arguments()?;
    std::fs::create_dir(&output_root)?;

    let pages = VerifiedEmbeddingPagesV1::open(&source_path)?;
    let header = pages.header();
    let rows = pages.rows()?;
    let real_vectors = pages.vectors()?;
    let dimension = header.dimension as usize;
    let real_ids: Vec<u64> = rows.iter().map(|row| row.subject_id).collect();
    let authority = ArtifactAuthority::from_embedding_header(header);

    println!(
        "source rows={} dimension={} artifact={}",
        rows.len(),
        dimension,
        short_hash(header.artifact_hash)
    );
    let real_queries = real_quality_queries(real_vectors, dimension);
    let mut real_quality = Vec::with_capacity(2);
    for bits in [2, 4] {
        let path = output_root.join(format!("real-{bits}bit.phxq1"));
        let index = write_quantized_artifact_new(
            &path,
            authority,
            &real_ids,
            real_vectors,
            dimension,
            bits,
        )?;
        let quality = quality_receipt(
            bits,
            &index,
            real_vectors,
            &real_ids,
            dimension,
            &real_queries,
            std::fs::metadata(path)?.len(),
        )?;
        println!(
            "real {bits}-bit self-top1={:.3} midpoint-top3-overlap={:.3} kernel={:?}",
            quality.self_query_top1_accuracy,
            quality.midpoint_mean_exact_top3_overlap_at_3,
            quality.kernel
        );
        real_quality.push(quality);
    }

    let max_rows = *PROJECTED_ROWS.last().unwrap();
    let projected_vectors = projected_vectors(real_vectors, dimension, max_rows);
    let projected_ids: Vec<u64> = (1..=max_rows as u64).collect();
    let query_rows = timed_query_rows(max_rows);
    let mut cohorts = Vec::with_capacity(PROJECTED_ROWS.len() * 2);
    for bits in [2, 4] {
        for rows in PROJECTED_ROWS {
            let vectors = &projected_vectors[..rows * dimension];
            let ids = &projected_ids[..rows];
            let path = output_root.join(format!("projected-{rows}-{bits}bit.phxq1"));
            let build_start = Instant::now();
            let first_open = write_quantized_artifact_new(
                &path,
                ArtifactAuthority::synthetic(b"phoenix-turboquant-projection-v1"),
                ids,
                vectors,
                dimension,
                bits,
            )?;
            let build_duration = build_start.elapsed();
            drop(first_open);
            let open_start = Instant::now();
            let index = VerifiedQuantizedIndex::open(&path)?;
            let open_duration = open_start.elapsed();
            let cohort = benchmark_cohort(
                bits,
                &index,
                vectors,
                ids,
                dimension,
                &query_rows,
                std::fs::metadata(&path)?.len(),
                build_duration,
                open_duration,
            )?;
            println!(
                "rows={rows:>6} bits={bits} bytes={:>8} exact_p50={:>9.1}us quant_p50={:>9.1}us recall@64={:.3}",
                cohort.quantized_artifact_bytes,
                cohort.exact_top64_us.p50,
                cohort.quantized_top64_us.p50,
                cohort.exact_top1_recall_at_64
            );
            cohorts.push(cohort);
        }
    }

    let projections = projections(&cohorts, dimension);
    let receipt = ProofReceipt {
        schema: "phoenix-turboquant-proof/v1",
        implementation_scope: "standalone first-party experiment; not wired into Phoenix",
        source: SourceReceipt {
            path: source_path.display().to_string(),
            rows: rows.len(),
            dimension,
            f32_vector_bytes: real_vectors.len() as u64 * 4,
            artifact_hash: hex(header.artifact_hash),
            generation_hash: hex(header.generation_hash),
            model_identity_hash: hex(header.model_identity_hash),
        },
        machine: MachineReceipt {
            architecture: std::env::consts::ARCH,
            operating_system: std::env::consts::OS,
            logical_parallelism: std::thread::available_parallelism()?.get(),
            avx2: cfg!(target_arch = "x86_64")
                && std::arch::is_x86_feature_detected!("avx2"),
        },
        real_quality,
        measured_cohorts: cohorts,
        arithmetic_projections: projections,
        caveats: [
            "The measured projected cohorts are deterministic perturbations of six real Phoenix embeddings, not production query traffic.",
            "The 1M latency values are least-squares extrapolations from measured cohorts through 100K rows, not measured runs.",
            "The clean-room codebook uses a high-dimensional normal approximation to the paper's spherical Beta law.",
            "Quantized candidates require exact reranking before semantic promotion decisions.",
        ],
    };
    let receipt_path = output_root.join("phoenix-turboquant-proof-receipt.json");
    std::fs::write(&receipt_path, serde_json::to_vec_pretty(&receipt)?)?;
    println!("receipt={}", receipt_path.display());
    Ok(())
}

fn arguments() -> Result<(PathBuf, PathBuf), Box<dyn std::error::Error>> {
    let mut arguments = std::env::args_os().skip(1);
    let source = arguments
        .next()
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(DEFAULT_SOURCE));
    let output = arguments
        .next()
        .map(PathBuf::from)
        .ok_or("usage: proof [source.phxe1] OUTPUT_DIRECTORY (output must not exist)")?;
    if arguments.next().is_some() {
        return Err("too many arguments".into());
    }
    Ok((source, output))
}

fn quality_receipt(
    bits: u8,
    index: &VerifiedQuantizedIndex,
    vectors: &[f32],
    ids: &[u64],
    dimension: usize,
    queries: &[Vec<f32>],
    artifact_bytes: u64,
) -> Result<QualityReceipt, Box<dyn std::error::Error>> {
    let self_queries = ids.len();
    let midpoint_queries = queries.len() - self_queries;
    let mut self_top1_matches = 0usize;
    let mut midpoint_overlap = 0usize;
    let mut kernel = SearchKernel::Scalar;
    for (query_index, query) in queries.iter().enumerate() {
        let exact = exact_search(vectors, ids, dimension, query, 3)?;
        let mut scratch = SearchScratch::new(dimension, TOP_K);
        let mut quantized = Vec::with_capacity(TOP_K);
        kernel = index.search_into(
            query,
            TOP_K,
            SearchKernel::Auto,
            &mut scratch,
            &mut quantized,
        )?;
        if query_index < self_queries {
            self_top1_matches += usize::from(quantized[0].subject_id == exact[0].subject_id);
        } else {
            midpoint_overlap += top_overlap(&exact, &quantized, 3);
        }
    }
    Ok(QualityReceipt {
        bits,
        self_query_count: self_queries,
        midpoint_query_count: midpoint_queries,
        self_query_top1_accuracy: self_top1_matches as f64 / self_queries as f64,
        midpoint_mean_exact_top3_overlap_at_3: midpoint_overlap as f64
            / (midpoint_queries * 3.min(ids.len())) as f64,
        kernel,
        artifact_bytes,
    })
}

#[allow(clippy::too_many_arguments)]
fn benchmark_cohort(
    bits: u8,
    index: &VerifiedQuantizedIndex,
    vectors: &[f32],
    ids: &[u64],
    dimension: usize,
    available_query_rows: &[usize],
    artifact_bytes: u64,
    build: Duration,
    open: Duration,
) -> Result<CohortReceipt, Box<dyn std::error::Error>> {
    let query_rows: Vec<usize> = available_query_rows
        .iter()
        .map(|row| row % ids.len())
        .collect();
    let mut exact_scratch = ExactSearchScratch::new(TOP_K);
    let mut quant_scratch = SearchScratch::new(dimension, TOP_K);
    let mut exact_hits = Vec::with_capacity(TOP_K);
    let mut quant_hits = Vec::with_capacity(TOP_K);
    let warm_query = row(vectors, dimension, query_rows[0]);
    exact_search_into(
        vectors,
        ids,
        dimension,
        warm_query,
        TOP_K,
        &mut exact_scratch,
        &mut exact_hits,
    )?;
    let mut kernel = index.search_into(
        warm_query,
        TOP_K,
        SearchKernel::Auto,
        &mut quant_scratch,
        &mut quant_hits,
    )?;

    let mut exact_times = Vec::with_capacity(TIMED_QUERIES);
    let mut quant_times = Vec::with_capacity(TIMED_QUERIES);
    for query_row in query_rows {
        let query = row(vectors, dimension, query_row);
        let start = Instant::now();
        exact_search_into(
            vectors,
            ids,
            dimension,
            query,
            TOP_K,
            &mut exact_scratch,
            &mut exact_hits,
        )?;
        exact_times.push(start.elapsed());
        let start = Instant::now();
        kernel = index.search_into(
            query,
            TOP_K,
            SearchKernel::Auto,
            &mut quant_scratch,
            &mut quant_hits,
        )?;
        quant_times.push(start.elapsed());
    }
    let quality_queries = cohort_quality_queries(vectors, dimension, ids.len());
    let mut recalled = 0usize;
    for query in &quality_queries {
        exact_search_into(
            vectors,
            ids,
            dimension,
            query,
            TOP_K,
            &mut exact_scratch,
            &mut exact_hits,
        )?;
        index.search_into(
            query,
            TOP_K,
            SearchKernel::Auto,
            &mut quant_scratch,
            &mut quant_hits,
        )?;
        recalled += usize::from(
            quant_hits
                .iter()
                .any(|hit| hit.subject_id == exact_hits[0].subject_id),
        );
    }
    let f32_bytes = vectors.len() as u64 * 4;
    Ok(CohortReceipt {
        bits,
        rows: ids.len(),
        dimension,
        f32_vector_bytes: f32_bytes,
        quantized_artifact_bytes: artifact_bytes,
        compression_ratio: f32_bytes as f64 / artifact_bytes as f64,
        build_write_verify_ms: milliseconds(build),
        mmap_open_verify_ms: milliseconds(open),
        exact_top64_us: percentiles(exact_times),
        quantized_top64_us: percentiles(quant_times),
        observed_kernel: kernel,
        execution: index.recommended_execution(),
        recall_query_count: quality_queries.len(),
        exact_top1_recall_at_64: recalled as f64 / quality_queries.len() as f64,
    })
}

fn real_quality_queries(vectors: &[f32], dimension: usize) -> Vec<Vec<f32>> {
    let rows = vectors.len() / dimension;
    let mut queries = Vec::with_capacity(rows + rows.saturating_sub(1) * rows / 2);
    for row_index in 0..rows {
        queries.push(row(vectors, dimension, row_index).to_vec());
    }
    for left in 0..rows {
        for right in left + 1..rows {
            let mut query: Vec<f32> = row(vectors, dimension, left)
                .iter()
                .zip(row(vectors, dimension, right))
                .map(|(a, b)| a + b)
                .collect();
            normalize(&mut query);
            queries.push(query);
        }
    }
    queries
}

fn projected_vectors(real: &[f32], dimension: usize, rows: usize) -> Vec<f32> {
    let real_rows = real.len() / dimension;
    let mut output = Vec::with_capacity(rows * dimension);
    for projected_row in 0..rows {
        let start = output.len();
        let base = row(real, dimension, projected_row % real_rows);
        for (column, value) in base.iter().copied().enumerate() {
            let mixed = splitmix64(
                (projected_row as u64 + 1).wrapping_mul(0x9e37_79b9_7f4a_7c15) ^ column as u64,
            );
            let noise = ((mixed >> 40) as f32 / 8_388_607.5 - 1.0) * 0.12;
            output.push(value + noise);
        }
        normalize(&mut output[start..]);
    }
    output
}

fn timed_query_rows(rows: usize) -> Vec<usize> {
    (0..TIMED_QUERIES)
        .map(|index| (index * 1_373 + 17) % rows)
        .collect()
}

fn cohort_quality_queries(vectors: &[f32], dimension: usize, rows: usize) -> Vec<Vec<f32>> {
    let mut queries = Vec::with_capacity(32);
    for index in 0..16 {
        let query_row = (index * 7_919 + 31) % rows;
        queries.push(row(vectors, dimension, query_row).to_vec());
    }
    for index in 0..16 {
        let left = (index * 3_571 + 17) % rows;
        let mut right = (index * 7_723 + rows / 3 + 1) % rows;
        if right == left {
            right = (right + 1) % rows;
        }
        let mut query: Vec<f32> = row(vectors, dimension, left)
            .iter()
            .zip(row(vectors, dimension, right))
            .map(|(a, b)| a + b)
            .collect();
        normalize(&mut query);
        queries.push(query);
    }
    queries
}

fn projections(cohorts: &[CohortReceipt], dimension: usize) -> Vec<ProjectionReceipt> {
    let mut output = Vec::with_capacity(4);
    for bits in [2, 4] {
        let selected: Vec<&CohortReceipt> = cohorts.iter().filter(|row| row.bits == bits).collect();
        let exact_points: Vec<(f64, f64)> = selected
            .iter()
            .map(|row| (row.rows as f64, row.exact_top64_us.p50))
            .collect();
        let quant_points: Vec<(f64, f64)> = selected
            .iter()
            .map(|row| (row.rows as f64, row.quantized_top64_us.p50))
            .collect();
        let exact_line = linear_fit(&exact_points);
        let quant_line = linear_fit(&quant_points);
        let bytes_per_row = dimension * bits as usize / 8 + 4 + 8;
        for rows in EXTRAPOLATED_ROWS {
            output.push(ProjectionReceipt {
                bits,
                rows,
                projected_f32_vector_bytes: rows as u64 * dimension as u64 * 4,
                projected_quantized_bytes: 512 + rows as u64 * bytes_per_row as u64,
                projected_exact_top64_p50_us: predict(exact_line, rows),
                projected_quantized_top64_p50_us: predict(quant_line, rows),
                method: "ordinary least squares over five measured p50 cohorts from 1024 through 100000 rows",
            });
        }
    }
    output
}

fn linear_fit(points: &[(f64, f64)]) -> (f64, f64) {
    let count = points.len() as f64;
    let mean_x = points.iter().map(|point| point.0).sum::<f64>() / count;
    let mean_y = points.iter().map(|point| point.1).sum::<f64>() / count;
    let numerator = points
        .iter()
        .map(|(x, y)| (x - mean_x) * (y - mean_y))
        .sum::<f64>();
    let denominator = points
        .iter()
        .map(|(x, _)| (x - mean_x).powi(2))
        .sum::<f64>();
    let slope = numerator / denominator;
    (mean_y - slope * mean_x, slope)
}

fn predict(line: (f64, f64), rows: usize) -> f64 {
    (line.0 + line.1 * rows as f64).max(0.0)
}

fn percentiles(mut values: Vec<Duration>) -> Percentiles {
    values.sort_unstable();
    Percentiles {
        p50: microseconds(values[(values.len() - 1) / 2]),
        p95: microseconds(values[((values.len() - 1) * 95) / 100]),
    }
}

fn row(vectors: &[f32], dimension: usize, row: usize) -> &[f32] {
    &vectors[row * dimension..(row + 1) * dimension]
}

fn normalize(vector: &mut [f32]) {
    let inverse = vector
        .iter()
        .map(|value| value * value)
        .sum::<f32>()
        .sqrt()
        .recip();
    for value in vector {
        *value *= inverse;
    }
}

fn top_overlap(exact: &[SearchHit], quantized: &[SearchHit], count: usize) -> usize {
    exact
        .iter()
        .take(count)
        .filter(|exact_hit| {
            quantized
                .iter()
                .take(count)
                .any(|hit| hit.subject_id == exact_hit.subject_id)
        })
        .count()
}

fn milliseconds(duration: Duration) -> f64 {
    duration.as_secs_f64() * 1_000.0
}

fn microseconds(duration: Duration) -> f64 {
    duration.as_secs_f64() * 1_000_000.0
}

fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

fn short_hash(hash: [u8; 32]) -> String {
    hex(hash)[..16].to_owned()
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
