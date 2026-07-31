# Phoenix QPS V2 experiment

This crate is an isolated positional lexical-ranking experiment. It does not
replace or register itself beside Phoenix's production `bm25-turbo` indexes.

The experiment compares:

- the repository's pinned `bm25-turbo 0.2.0` implementation; and
- field-aware BM25F with preserved query groups, weighted coverage, minimum
  token span, query order, exact phrase, segment concentration, and exact-field
  evidence.

V2.01 uses one fused index: an exact token dictionary, precomputed BM25F
posting impacts, one-pass exact-group accumulation, adaptive sparse-heap or
SIMD-collect/quickselect candidate selection, and a bounded positional rerank.
The exhaustive positional API is retained only as a candidate-recall oracle.

Fuzzy, prefix, stemming, synonym, mmap persistence, and hybrid ANN fusion are
deliberately outside this experiment. Callers can supply bounded expansion
groups with explicit match qualities, which preserves the ranking contract
without importing Orama or its radix tree.

Run:

```powershell
$env:CARGO_TARGET_DIR='D:\phoenix-target-qps-v2'
cargo test -p phoenix-qps-experiment
cargo run --release -p phoenix-qps-experiment --bin qps-bm25-compare
cargo bench -p phoenix-qps-experiment --bench retrieval
```

Synthetic judged queries prove intended behavior, not general retrieval
superiority. Production adoption requires a frozen Phoenix query/qrels cohort.

The original V2 comparison is recorded in [`BENCHMARK.md`](BENCHMARK.md). The
staked V2.01 architecture, paired statistical protocol, current measurements,
and stop/go gates are frozen in [`V2_01_CUT.md`](V2_01_CUT.md).
