use criterion::{black_box, criterion_group, criterion_main, Criterion};
use e013_episode_factory::{candidate_order, hash_bytes, root_hash, SealEntry};

fn hash_and_order(c: &mut Criterion) {
    let ids = (0..256)
        .map(|index| format!("cand-{index:04}"))
        .collect::<Vec<_>>();
    c.bench_function("candidate_order_256", |bench| {
        bench.iter(|| candidate_order(black_box(42), black_box(&ids)))
    });
    let entries = (0..256)
        .map(|index| SealEntry {
            artifact_id: format!("visible/{index:04}.bin"),
            path: format!("visible/{index:04}.bin"),
            byte_len: 4096,
            sha256: hash_bytes(&vec![index as u8; 4096]),
        })
        .collect::<Vec<_>>();
    c.bench_function("episode_root_hash_256x4k", |bench| {
        bench.iter(|| root_hash(black_box(&entries)))
    });
}

criterion_group!(benches, hash_and_order);
criterion_main!(benches);
