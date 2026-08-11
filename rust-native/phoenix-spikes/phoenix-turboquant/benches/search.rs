use std::hint::black_box;

use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion};
use phoenix_turboquant::{
    exact_search_into, write_quantized_artifact_new, ArtifactAuthority, ExactSearchScratch,
    SearchExecution, SearchKernel, SearchScratch, VerifiedQuantizedIndex,
};
use tempfile::tempdir;

const DIMENSION: usize = 768;

fn normalized_vectors(rows: usize) -> Vec<f32> {
    let mut vectors = Vec::with_capacity(rows * DIMENSION);
    for row in 0..rows {
        let start = vectors.len();
        let mut norm = 0.0_f32;
        for column in 0..DIMENSION {
            let value = (((row * 131 + column * 17) % 997) as f32 / 498.5) - 1.0;
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

fn search_benchmark(criterion: &mut Criterion) {
    let rows = 4_096;
    let vectors = normalized_vectors(rows);
    let ids: Vec<u64> = (1..=rows as u64).collect();
    let query = vectors[..DIMENSION].to_vec();
    let directory = tempdir().expect("temporary benchmark directory");
    let authority = ArtifactAuthority::synthetic(b"criterion-search-v1");
    let indexes: Vec<(u8, VerifiedQuantizedIndex)> = [2, 4]
        .into_iter()
        .map(|bits| {
            let path = directory.path().join(format!("bench-{bits}.phxq1"));
            write_quantized_artifact_new(&path, authority, &ids, &vectors, DIMENSION, bits)
                .expect("write benchmark artifact");
            (
                bits,
                VerifiedQuantizedIndex::open(&path).expect("open benchmark artifact"),
            )
        })
        .collect();

    let mut group = criterion.benchmark_group("search_4096x768_top64");
    let mut exact_scratch = ExactSearchScratch::new(64);
    let mut exact_output = Vec::with_capacity(64);
    group.bench_with_input(BenchmarkId::new("exact_f32", rows), &rows, |bencher, _| {
        bencher.iter(|| {
            exact_search_into(
                black_box(&vectors),
                black_box(&ids),
                DIMENSION,
                black_box(&query),
                64,
                &mut exact_scratch,
                &mut exact_output,
            )
            .expect("exact search")
        })
    });
    for (bits, index) in &indexes {
        let mut scratch = SearchScratch::new(DIMENSION, 64);
        let mut output = Vec::with_capacity(64);
        group.bench_with_input(
            BenchmarkId::new(format!("quant_{bits}bit_end_to_end_auto"), rows),
            &rows,
            |bencher, _| {
                bencher.iter(|| {
                    index
                        .search_into(
                            black_box(&query),
                            64,
                            SearchKernel::Auto,
                            &mut scratch,
                            &mut output,
                        )
                        .expect("quantized search")
                })
            },
        );
        let mut serial_scratch = SearchScratch::new(DIMENSION, 64);
        let mut serial_output = Vec::with_capacity(64);
        index.prepare_query(&query, &mut serial_scratch).unwrap();
        group.bench_with_input(
            BenchmarkId::new(format!("quant_{bits}bit_prepared_serial"), rows),
            &rows,
            |bencher, _| {
                bencher.iter(|| {
                    index
                        .search_prepared_with_execution_into(
                            64,
                            SearchKernel::Auto,
                            SearchExecution::Serial,
                            &mut serial_scratch,
                            &mut serial_output,
                        )
                        .expect("serial prepared search")
                })
            },
        );
        let mut rayon_scratch = SearchScratch::new(DIMENSION, 64);
        let mut rayon_output = Vec::with_capacity(64);
        index.prepare_query(&query, &mut rayon_scratch).unwrap();
        group.bench_with_input(
            BenchmarkId::new(format!("quant_{bits}bit_prepared_rayon"), rows),
            &rows,
            |bencher, _| {
                bencher.iter(|| {
                    index
                        .search_prepared_with_execution_into(
                            64,
                            SearchKernel::Auto,
                            SearchExecution::Rayon,
                            &mut rayon_scratch,
                            &mut rayon_output,
                        )
                        .expect("Rayon prepared search")
                })
            },
        );
    }
    group.finish();
}

criterion_group!(benches, search_benchmark);
criterion_main!(benches);
