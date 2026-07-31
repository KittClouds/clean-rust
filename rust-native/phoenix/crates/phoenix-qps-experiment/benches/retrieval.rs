use std::hint::black_box;

use bm25_turbo::BM25Builder;
use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use phoenix_qps_experiment::{
    benchmark_corpus, DocumentInput, FieldConfig, QpsBuilder, QpsConfig, SearchScratch,
};

fn retrieval(c: &mut Criterion) {
    let corpus = benchmark_corpus(10_000);
    let borrowed = corpus.iter().map(String::as_str).collect::<Vec<_>>();
    let bm25 = BM25Builder::new().build_from_corpus(&borrowed).unwrap();
    let fields = [FieldConfig::new("body", 1.0, 0.75, 0.0)];
    let mut builder = QpsBuilder::new(fields, QpsConfig::default()).unwrap();
    for (document, text) in corpus.iter().enumerate() {
        let values = [text.as_str()];
        builder
            .insert(DocumentInput {
                external_id: document as u64,
                fields: &values,
            })
            .unwrap();
    }
    let qps = builder.build().unwrap();
    let mut scratch = SearchScratch::with_document_capacity(10_000, 32);
    let mut output = Vec::with_capacity(10);
    let mut group = c.benchmark_group("search_10k_x_96_tokens");
    group.throughput(Throughput::Elements(1));
    group.bench_with_input(BenchmarkId::new("bm25_turbo", 10), &10, |b, &top_k| {
        b.iter(|| {
            bm25.search(black_box("graph memory retrieval"), top_k)
                .unwrap()
        })
    });
    group.bench_with_input(
        BenchmarkId::new("qps_v2_01_fused_positional", 10),
        &10,
        |b, &top_k| {
            b.iter(|| {
                qps.search_into(
                    black_box("graph memory retrieval"),
                    top_k,
                    &mut scratch,
                    &mut output,
                )
                .unwrap()
            })
        },
    );
    group.finish();

    let mut dense_group = c.benchmark_group("dense_multi_token_10k_x_96_tokens");
    dense_group.throughput(Throughput::Elements(1));
    dense_group.bench_with_input(BenchmarkId::new("bm25_turbo", 10), &10, |b, &top_k| {
        b.iter(|| {
            bm25.search(black_box("term17 term203 term411"), top_k)
                .unwrap()
        })
    });
    dense_group.bench_with_input(
        BenchmarkId::new("qps_v2_01_fused_positional", 10),
        &10,
        |b, &top_k| {
            b.iter(|| {
                qps.search_into(
                    black_box("term17 term203 term411"),
                    top_k,
                    &mut scratch,
                    &mut output,
                )
                .unwrap()
            })
        },
    );
    dense_group.finish();
}

criterion_group!(benches, retrieval);
criterion_main!(benches);
