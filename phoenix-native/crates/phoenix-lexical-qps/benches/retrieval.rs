//! Throughput comparison on the LIVE Phoenix lexical crate vs BM25 Turbo.
//! Mirrors `phoenix-qps-experiment/benches/retrieval.rs` (10k docs x 96 tokens)
//! so numbers are directly comparable to the frozen 2026-07-30 baseline
//! (BM25 88.4K q/s, QPS V2 45.3K q/s), plus a transport-fan-out arm that the
//! old bench did not have. AGPL quarantine: bm25_turbo used here only.

use std::hint::black_box;

use bm25_turbo::BM25Builder;
use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use phoenix_lexical_qps::{
    DocumentInput, Expansion, FieldConfig, QpsBuilder, QpsConfig, QueryGroup, SearchScratch,
};

const DOCS: usize = 10_000;
const TOKENS: usize = 96;
const VOCAB: usize = 512;

/// Byte-for-byte replica of phoenix-qps-experiment's benchmark_corpus:
/// xorshift terms over term0..term511, '.' every 24 tokens (segments!),
/// phrase appended to every 97th doc (df~104, NOT every 16th).
fn benchmark_corpus() -> Vec<String> {
    let vocabulary = (0..VOCAB)
        .map(|index| format!("term{index}"))
        .collect::<Vec<_>>();
    (0..DOCS)
        .map(|document| {
            let mut state = (document as u64 + 1).wrapping_mul(0x9E37_79B9_7F4A_7C15);
            let mut text = String::with_capacity(768);
            for token in 0..TOKENS {
                state ^= state >> 12;
                state ^= state << 25;
                state ^= state >> 27;
                let word = &vocabulary[(state as usize) & (vocabulary.len() - 1)];
                text.push_str(word);
                text.push(if token % 24 == 23 { '.' } else { ' ' });
            }
            if document % 97 == 0 {
                text.push_str(" graph memory retrieval.");
            }
            text
        })
        .collect()
}

fn build_qps(corpus: &[String]) -> phoenix_lexical_qps::QpsIndex {
    let fields = [FieldConfig::new("body", 1.0, 0.75, 0.0)];
    let mut builder =
        QpsBuilder::new(Vec::from(fields).into_boxed_slice(), QpsConfig::default()).unwrap();
    for (document, text) in corpus.iter().enumerate() {
        let values = [text.as_str()];
        builder
            .insert(DocumentInput {
                external_id: document as u64,
                fields: &values,
            })
            .unwrap();
    }
    builder.build().unwrap()
}

fn retrieval(c: &mut Criterion) {
    let corpus = benchmark_corpus();
    let borrowed = corpus.iter().map(String::as_str).collect::<Vec<_>>();
    let bm25 = BM25Builder::new().build_from_corpus(&borrowed).unwrap();
    let qps = build_qps(&corpus);
    let mut scratch = SearchScratch::with_document_capacity(DOCS, 32);
    let mut output = Vec::with_capacity(10);

    // Transport arm groups (literal + in-vocabulary expansions).
    let g0 = [
        Expansion {
            term: "graph",
            quality: 1.0,
        },
        Expansion {
            term: "term17",
            quality: 0.6,
        },
        Expansion {
            term: "term18",
            quality: 0.4,
        },
    ];
    let g1 = [
        Expansion {
            term: "memory",
            quality: 1.0,
        },
        Expansion {
            term: "term203",
            quality: 0.6,
        },
        Expansion {
            term: "term204",
            quality: 0.4,
        },
    ];
    let g2 = [
        Expansion {
            term: "retrieval",
            quality: 1.0,
        },
        Expansion {
            term: "term411",
            quality: 0.6,
        },
        Expansion {
            term: "term412",
            quality: 0.4,
        },
    ];
    let transport = [
        QueryGroup { expansions: &g0 },
        QueryGroup { expansions: &g1 },
        QueryGroup { expansions: &g2 },
    ];
    // Transport arm = literal 1.0 + two in-vocabulary expansions per group.
    // Measures group fan-out cost, not transport quality (BEIR track owns that).

    let mut group = c.benchmark_group("search_10k_x_96_tokens");
    group.throughput(Throughput::Elements(1));
    group.bench_with_input(BenchmarkId::new("bm25_turbo", 10), &10, |b, &top_k| {
        b.iter(|| {
            bm25.search(black_box("graph memory retrieval"), top_k)
                .unwrap()
        })
    });
    group.bench_with_input(
        BenchmarkId::new("phoenix_lexical_literal", 10),
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
    group.bench_with_input(
        BenchmarkId::new("phoenix_lexical_transport", 10),
        &10,
        |b, &top_k| {
            b.iter(|| {
                qps.search_groups_into(black_box(&transport), top_k, &mut scratch, &mut output)
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
        BenchmarkId::new("phoenix_lexical_literal", 10),
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
