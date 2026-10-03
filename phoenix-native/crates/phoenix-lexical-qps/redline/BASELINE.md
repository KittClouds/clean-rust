# REDLINE Phase 0 baseline (sealed battlefield)

Date: 2026-09-18. Commit: 9a885473. Host: AMD Ryzen 7 5800X3D, 31.9 GiB RAM,
Windows x86-64 MSVC. Rust 1.96.0. Corpus: 10k x 96 replica (xorshift,
`.` segments, phrase every 97th doc). Same-day BM25 Turbo 0.2.0.

## Criterion medians (50 samples, top_k=10)

| Query | BM25 Turbo | Phoenix literal | Transport | V2 snapshot |
|---|---|---|---|---|
| phrase | 10.2us / 97.9K | 42.0us / 23.8K | 263.9us / 3.8K | 19.1us |
| dense 3-term | 36.3us / 27.5K | 163.0us / 6.1K | — | 133.3us |

Live-vs-snapshot: 2.2x phrase, 1.2x dense. Live-vs-BM25 same-run: 4.1-4.5x.
Caveat: BM25 swung 11.3 (Jul) to 10-18 across today runs; frozen comparisons
must stay same-day/same-corpus.

## Receipts (perf_probe, warm, mean ns; run-to-run wobble ~= +-10% on this box)

| bucket | mean | accum | select | coher | order | cand | rows | posvals | selection |
|---|---|---|---|---|---|---|---|---|---|
| one-token | 36186 | 19100 | 5900 | 7500 | 100 | 1761 | 1761 | 88 | Sparse |
| multi-token | 155323 | 52400 | 27500 | 49700 | 6100 | 4401 | 5196 | 528 | Dense |
| phrase-like | 36066 | 2100 | 2300 | 26400 | 100 | 104 | 312 | 312 | Sparse |
| high-frequency | 164090 | 67900 | 26600 | 42700 | 6100 | 5828 | 6649 | 409 | Dense |
| fuzzy-miss | 457 | 0 | 100 | 100 | 0 | 0 | 0 | 0 | Sparse |
| no-result | 458 | 100 | 0 | 0 | 0 | 0 | 0 | 0 | Sparse |
| transport-x3 | 246823 | 170500 | 67800 | 55100 | 4800 | 6876/4931 | 10692 | 516 | Dense |
| lexical-only | 19638 | 2600 | 4100 | 23700 | 300 | 104 | 312 | 0 | Sparse |

allocations_grew=false everywhere warm. sizeof SearchHit = 240 bytes
(snapshot V2: ~48). Index: 516 terms, 881,097 rows, 965,312 positions,
21.05 MiB estimated.

## Attribution (measured, not inferred)

Lexical-only total (19.6us) ~= snapshot total (19.1us): accumulation/selection
are NOT regressed. The entire gap is positional + per-hit V3 evidence
(~107ns/hit: rank_features + 30-wide rank_evidence_v3 + tier) + 240B-hit
sort traffic. Lexical-only still pays per-hit evidence inside the coherence
stage timer (23.7us/104 hits with zero positions opened).

## Phase 0 changes (instrumentation only, zero behavior change)

- Pool-sort moved inside the selection stage timer (was untimed gap).
- tests/redline_freeze.rs + redline/freeze_expected.snap: semantic freeze
  (ids/order/score bits/tiers/evidence/pools/strengths) green; double-dump
  byte-identical.

## Milestones

A (recover): phrase literal <=22us, dense <=110us.
B (structural): phrase <=20us, dense <=80us.
C (stretch): literal within 2x same-day BM25, quality advantage kept.
Transport target: <=2-3x literal (today 6.3x).
