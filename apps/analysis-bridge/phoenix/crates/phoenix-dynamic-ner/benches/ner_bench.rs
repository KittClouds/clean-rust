use criterion::{criterion_group, criterion_main, Criterion};

pub fn dummy_bench(c: &mut Criterion) {
    c.bench_function("dummy", |b| {
        b.iter(|| {
            let x = 1 + 1;
            criterion::black_box(x);
        })
    });
}

criterion_group!(benches, dummy_bench);
criterion_main!(benches);
