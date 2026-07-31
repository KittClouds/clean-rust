# QPS V2 experiment result

Run date: 2026-07-30

This is an isolated experiment. It is not registered in Phoenix's production
retrieval path and it does not replace BM25.

## Frozen comparison

- Host: AMD Ryzen 7 5800X3D, 31.9 GiB RAM, Windows x86-64 MSVC
- Rust: 1.96.0 (`ac68faa20`)
- Repository base: `abaa35ff`
- Baseline: `bm25_turbo = 0.2.0`, Lucene method defaults
- Candidate: this crate's positional BM25F/QPS V2
- Throughput corpus: 10,000 deterministic documents, 96 ASCII-normalized
  tokens each
- Throughput query: `graph memory retrieval`
- Top K: 10
- Build target: `D:\phoenix-target-qps-v2`
- Executed binary:
  `C:\phoenix-bin\qps-v2-experiment\qps-bm25-compare.exe`
- Binary SHA-256:
  `30ED17B8273DCD1383856EAFCEAFAC7B00BECE6C11B3C8649EC684F4A24004C7`

Both engines receive the same flattened normalized text in the throughput
test. The quality fixture gives QPS its declared title/body fields while BM25
receives those same fields concatenated, because `bm25_turbo` is a
single-field index.

## Result

### Frozen adversarial quality fixture

| Metric | Positional QPS V2 | BM25 Turbo |
|---|---:|---:|
| MRR | 1.000 | 0.600 |
| Recall at 5 | 1.000 | 1.000 |

The five qrels deliberately isolate the claimed behavior: phrase proximity,
query order, sentence concentration, and exact-field matches versus repeated
but scattered terms. This proves the implementation's intended behavior. It
does not prove broad corpus quality or justify production cutover.

### Build and query

One release runner sample:

| Measurement | Positional QPS V2 | BM25 Turbo |
|---|---:|---:|
| Build | 238.520 ms | 242.853 ms |
| Search mean | 18.607 us | 8.930 us |
| Search p95 | 20.600 us | 11.100 us |

Criterion, 100 statistical samples:

| Engine | 95% time interval | Median estimate | Throughput estimate |
|---|---:|---:|---:|
| BM25 Turbo | 11.146-11.476 us | 11.311 us | 88.406 Kquery/s |
| Positional QPS V2 | 21.856-22.332 us | 22.090 us | 45.270 Kquery/s |

QPS is approximately 1.95 times slower at query time on this selective
three-term workload. Its measured packed arrays contain:

- 10,000 documents
- 515 terms
- 876,097 term/document/field posting rows
- 960,312 positions and segment IDs
- 27.86 MiB estimated packed payload

`bm25_turbo` does not expose heap/index byte accounting through its public API,
so no memory-ratio claim is made.

## Decision

The experiment earned a later production-quality evaluation, not a cutover.
The quality behavior is real and the absolute query cost remains tiny, but the
current evidence is synthetic and BM25 is almost twice as fast.

A serious next gate would use Phoenix's frozen query/relevance cohort and
compare three lanes:

1. BM25 Turbo alone.
2. Positional QPS V2 alone.
3. BM25 candidate generation followed by bounded positional reranking.

The third lane is the current favorite: preserve BM25's mature, SIMD-optimized
candidate generation and pay positional coherence only for a small candidate
set.
