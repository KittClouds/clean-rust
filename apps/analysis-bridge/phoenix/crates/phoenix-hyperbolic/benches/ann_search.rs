use criterion::{black_box, criterion_group, criterion_main, Criterion};
use phoenix_hyperbolic::{
    HnswBuildOptions, HyperbolicDiskHnsw, HyperbolicHnswBuilder, NoFilter, NodeMetadata,
    PoincareMetric, SearchParams, SearchScratch, StableVectorId,
};

fn deterministic_vector(id: u64, dimension: usize) -> Vec<f32> {
    let mut state = id ^ 0x9e37_79b9_7f4a_7c15;
    let mut vector = Vec::with_capacity(dimension);
    for _ in 0..dimension {
        state ^= state >> 12;
        state ^= state << 25;
        state ^= state >> 27;
        let unit = (state.wrapping_mul(0x2545_f491_4f6c_dd1d) >> 40) as f32 / (1_u32 << 24) as f32;
        vector.push((unit - 0.5) * 0.1);
    }
    vector
}

fn ann_search(c: &mut Criterion) {
    const DIMENSION: usize = 32;
    const NODES: u64 = 10_000;
    let metric = PoincareMetric { curvature: 1.0 };
    let mut builder =
        HyperbolicHnswBuilder::try_new(DIMENSION, metric, HnswBuildOptions::default())
            .expect("valid benchmark configuration");
    for raw_id in 1..=NODES {
        builder
            .insert_with_id(
                StableVectorId::new(raw_id).expect("nonzero benchmark ID"),
                deterministic_vector(raw_id, DIMENSION),
                NodeMetadata::default(),
            )
            .expect("valid benchmark vector");
    }
    let frozen = builder.freeze();
    let query = deterministic_vector(9_001, DIMENSION);
    let mut resident_scratch = SearchScratch::new();
    resident_scratch.reserve(frozen.len(), DIMENSION, 128);

    c.bench_function("hnsw_resident_10k_32d_k10_ef128_reused_scratch", |bench| {
        bench.iter(|| {
            black_box(
                frozen
                    .search_with_scratch(
                        &metric,
                        black_box(&query),
                        SearchParams::new(10, 128),
                        &NoFilter,
                        &mut resident_scratch,
                    )
                    .expect("benchmark search"),
            );
        });
    });

    let archive_dir = tempfile::tempdir().expect("temporary benchmark archive directory");
    let archive_path = archive_dir.path().join("benchmark.phxann");
    frozen
        .write_new(&archive_path)
        .expect("write verified benchmark archive");
    let mapped = HyperbolicDiskHnsw::open(&archive_path, metric)
        .expect("open verified mmap benchmark archive");
    let mut mapped_scratch = SearchScratch::new();
    mapped_scratch.reserve(mapped.len(), mapped.dimension(), 128);

    c.bench_function("hnsw_mmap_10k_32d_k10_ef128_reused_scratch", |bench| {
        bench.iter(|| {
            black_box(
                mapped
                    .search_with_scratch(
                        black_box(&query),
                        SearchParams::new(10, 128),
                        &NoFilter,
                        &mut mapped_scratch,
                    )
                    .expect("mmap benchmark search"),
            );
        });
    });
}

criterion_group!(benches, ann_search);
criterion_main!(benches);
