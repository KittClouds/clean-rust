# REDLINE quality-cost frontier

Date: 2026-09-18. This is an evaluation artifact; it does not promote a new
serving policy or ranker.

The evaluator is
`apps/phoenix-memory-lock/src/bin/qps_quality_frontier.rs`. It builds an
independent BM25 baseline and separate Phoenix indexes for literal-only,
positional, and V3 lanes. Metrics are macro averages over the judged BEIR
test queries. Latencies are warm release measurements with three repetitions
per query and include retrieval plus top-100 materialization.

The dataset archives were downloaded from the official BEIR distribution and
verified against its published MD5 values. The evaluator records SHA-256
hashes in the receipts under `D:\phoenix-evals\beir\receipts`.

## SciFact

| lane | nDCG@10 | Recall@100 | MRR | MAP | median | p95 |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.66345 | 0.88256 | 0.63473 | 0.62315 | 450.6 us | 801.8 us |
| Phoenix literal | 0.61045 | 0.86639 | 0.58523 | 0.57360 | 183.9 us | 373.4 us |
| Phoenix literal + positional | 0.61972 | 0.86472 | 0.59202 | 0.58117 | 527.5 us | 1,069.8 us |
| Phoenix literal + synthetic V3 | 0.57726 | 0.86972 | 0.55215 | 0.54185 | 507.1 us | 992.3 us |
| Phoenix transport exact control | 0.61972 | 0.86472 | 0.59202 | 0.58117 | 617.6 us | 1,257.9 us |
| Phoenix transport + synthetic V3 control | 0.57726 | 0.86972 | 0.55215 | 0.54185 | 606.0 us | 1,275.9 us |

## FiQA

| lane | nDCG@10 | Recall@100 | MRR | MAP | median | p95 |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.23734 | 0.50899 | 0.30407 | 0.18900 | 5,501.9 us | 9,137.6 us |
| Phoenix literal | 0.18283 | 0.41284 | 0.25223 | 0.14358 | 2,340.5 us | 4,203.5 us |
| Phoenix literal + positional | 0.19077 | 0.42340 | 0.25895 | 0.15037 | 2,939.1 us | 5,318.2 us |
| Phoenix literal + synthetic V3 | 0.14408 | 0.37730 | 0.20064 | 0.11596 | 2,993.8 us | 5,666.5 us |
| Phoenix transport exact control | 0.19077 | 0.42340 | 0.25895 | 0.15037 | 4,154.3 us | 8,249.5 us |
| Phoenix transport + synthetic V3 control | 0.14408 | 0.37730 | 0.20065 | 0.11597 | 4,272.3 us | 8,478.0 us |

## Interpretation

The literal Phoenix lane is substantially faster than this independent BM25
implementation, but it trails BM25 on both datasets in this untrained
configuration. Positional scoring recovers a small amount of quality at a
large latency cost. The synthetic V3 profile is not a qualified model and is
currently worse on both corpora; this is a model-selection result, not a V3
architecture rejection.

The transport lanes are **controls only**. Each query term is duplicated as a
second expansion at quality `0.999`, so their ranking metrics must equal the
positional lanes. Their extra cost measures expansion-group overhead, not the
value of semantic transport. A real transport quality frontier requires a
revision-bound synonym/fuzzy expansion artifact and must be rerun before any
budgeted transport policy is considered.

The immediate quality frontier is therefore clear: do not chase uncovered-doc
accumulation yet, and do not promote the synthetic V3 profile. Freeze these
measurements as the baseline for a trained, revision-bound V3 model and a
qualified expansion policy.

## Reproduction

```powershell
$env:CARGO_TARGET_DIR = 'D:\phoenix-builds\phoenix-qps-quality-frontier'
cargo build --release -p phoenix-memory-lock --bin qps_quality_frontier
& 'D:\phoenix-builds\phoenix-qps-quality-frontier\release\qps_quality_frontier.exe' `
  'D:\phoenix-evals\beir\scifact' 3 'D:\phoenix-evals\beir\receipts\scifact-frontier.json'
& 'D:\phoenix-builds\phoenix-qps-quality-frontier\release\qps_quality_frontier.exe' `
  'D:\phoenix-evals\beir\fiqa' 3 'D:\phoenix-evals\beir\receipts\fiqa-frontier.json'
```

