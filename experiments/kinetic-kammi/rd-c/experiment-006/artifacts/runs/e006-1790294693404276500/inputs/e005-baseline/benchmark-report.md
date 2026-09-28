# R&D-C Experiment 005 — Value of Information

## Question and boundaries

This benchmark tests whether a paid, on-demand inspection result can improve a legal-but-wrong action. The public frame contains source recommendations, source-reported revisions, age, warnings, confidence, and an inspection-domain key. The inspection payload is absent from that frame. The source state was written to a separate fixture before runtime execution; each selected episode makes one lookup and receives a hash-chained receipt containing the returned result.

The runtime authority remains the E002 compiled state machine. No trusted task revision was added to its contract, the inspection response contains no revision, and the authority has no revision guard. The observation witness and inspection resolver can propose an action; the existing transition schema authorizes only legal transitions.

## Paired benchmark results

| Router lane | Budget | Completed | Wrong legal actions | Wrong→right | Right→wrong | Illegal commits | Queries / resolver calls | p50 / p95 task ms | p50 / p95 query μs | p50 resolver μs | Journal B / task | Query receipt B / call | Query units / completion | Replay |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| e004_combined | 16 | 128/256 (50.0%) | 128 | 0 | 0 | 0 | 16 / 16 | 36.121 / 103.794 | 0.30 / 0.40 | 0.12 | 12235 | 566 | 0.125 | 256/256 |
| e004_combined | 32 | 128/256 (50.0%) | 128 | 0 | 0 | 0 | 32 / 32 | 35.012 / 101.257 | 0.30 / 0.50 | 0.16 | 12234 | 566 | 0.250 | 256/256 |
| e004_combined | 48 | 144/256 (56.2%) | 112 | 16 | 0 | 0 | 48 / 48 | 35.635 / 106.851 | 0.30 / 0.50 | 0.17 | 12396 | 568 | 0.333 | 256/256 |
| e004_combined | 64 | 160/256 (62.5%) | 96 | 32 | 0 | 0 | 64 / 64 | 34.858 / 105.695 | 0.30 / 0.40 | 0.18 | 12549 | 566 | 0.400 | 256/256 |
| development_voi | 16 | 144/256 (56.2%) | 112 | 16 | 0 | 0 | 16 / 16 | 35.671 / 105.980 | 0.30 / 0.70 | 0.18 | 12392 | 567 | 0.111 | 256/256 |
| development_voi | 32 | 160/256 (62.5%) | 96 | 32 | 0 | 0 | 32 / 32 | 36.024 / 105.783 | 0.30 / 0.60 | 0.25 | 12555 | 569 | 0.200 | 256/256 |
| development_voi | 48 | 172/256 (67.2%) | 84 | 44 | 0 | 0 | 48 / 48 | 36.073 / 48.972 | 0.30 / 0.50 | 0.22 | 12674 | 569 | 0.279 | 256/256 |
| development_voi | 64 | 184/256 (71.9%) | 72 | 56 | 0 | 0 | 64 / 64 | 39.249 / 1374.563 | 0.30 / 0.70 | 0.29 | 12791 | 569 | 0.348 | 256/256 |
| matched_random | 16 | 132/256 (51.6%) | 124 | 4 | 0 | 0 | 16 / 16 | 35.519 / 47.841 | 0.40 / 0.50 | 0.22 | 12274 | 563 | 0.121 | 256/256 |
| matched_random | 32 | 131/256 (51.2%) | 125 | 6 | 3 | 0 | 32 / 32 | 35.344 / 107.028 | 0.30 / 0.50 | 0.21 | 12266 | 566 | 0.244 | 256/256 |
| matched_random | 48 | 132/256 (51.6%) | 124 | 9 | 5 | 0 | 48 / 48 | 35.875 / 48.698 | 0.40 / 0.50 | 0.26 | 12276 | 566 | 0.364 | 256/256 |
| matched_random | 64 | 134/256 (52.3%) | 122 | 12 | 6 | 0 | 64 / 64 | 36.652 / 48.222 | 0.40 / 0.50 | 0.24 | 12292 | 568 | 0.478 | 256/256 |
| offline_oracle | 16 | 144/256 (56.2%) | 112 | 16 | 0 | 0 | 16 / 16 | 35.545 / 48.070 | 0.30 / 0.70 | 0.21 | 12393 | 565 | 0.111 | 256/256 |
| offline_oracle | 32 | 160/256 (62.5%) | 96 | 32 | 0 | 0 | 32 / 32 | 36.373 / 103.348 | 0.30 / 0.50 | 0.24 | 12553 | 564 | 0.200 | 256/256 |
| offline_oracle | 48 | 176/256 (68.8%) | 80 | 48 | 0 | 0 | 48 / 48 | 35.846 / 57.539 | 0.30 / 0.50 | 0.23 | 12717 | 567 | 0.273 | 256/256 |
| offline_oracle | 64 | 192/256 (75.0%) | 64 | 64 | 0 | 0 | 64 / 64 | 39.624 / 66.850 | 0.40 / 0.60 | 0.28 | 12872 | 568 | 0.333 | 256/256 |

Task latency includes query, durable E002 journaling, action simulation, close, and replay. Query and resolver timings are local nanosecond measurements and noisy at this workload size. Each tool lookup costs one query unit; no external model is called and external token/API cost is zero. Receipt bytes per call exclude the shared 8-byte file header; the run manifest records whole-file sizes.

## Paired deltas against the E004 combined lane

| Budget | Lane | Completion delta | Paired wins / losses / ties | Wrong-action delta |
|---:|---|---:|---:|---:|
| 16 | development_voi | +16 | 16 / 0 / 240 | -16 |
| 16 | matched_random | +4 | 4 / 0 / 252 | -4 |
| 16 | offline_oracle | +16 | 16 / 0 / 240 | -16 |
| 32 | development_voi | +32 | 32 / 0 / 224 | -32 |
| 32 | matched_random | +3 | 6 / 3 / 247 | -3 |
| 32 | offline_oracle | +32 | 32 / 0 / 224 | -32 |
| 48 | development_voi | +28 | 36 / 8 / 212 | -28 |
| 48 | matched_random | -12 | 9 / 21 / 226 | +12 |
| 48 | offline_oracle | +32 | 43 / 11 / 202 | -32 |
| 64 | development_voi | +24 | 40 / 16 / 200 | -24 |
| 64 | matched_random | -26 | 11 / 37 / 208 | +26 |
| 64 | offline_oracle | +32 | 49 / 17 / 190 | -32 |

## Fresh-looking shared-error pocket

The `fresh_consistent_wrong` stratum has identical observer recommendations, age zero, and no warning bits. Its source-reported revision is one step behind the hidden task state, but the initial frame gives no way to detect that discrepancy. Twenty-four of the 32 separate inspection fixtures return the correct action; eight repeat the wrong action. This tests a fresh-looking shared error that age and warning checks cannot identify.

| Lane | Budget | Routed in stratum | Wrong→right | Right→wrong | Both wrong | Completion in stratum |
|---|---:|---:|---:|---:|---:|---:|
| e004_combined | 16 | 0 | 0 | 0 | 0 | 0/32 |
| e004_combined | 32 | 0 | 0 | 0 | 0 | 0/32 |
| e004_combined | 64 | 0 | 0 | 0 | 0 | 0/32 |
| development_voi | 16 | 0 | 0 | 0 | 0 | 0/32 |
| development_voi | 32 | 0 | 0 | 0 | 0 | 0/32 |
| development_voi | 64 | 32 | 24 | 0 | 8 | 24/32 |
| matched_random | 16 | 2 | 1 | 0 | 1 | 1/32 |
| matched_random | 32 | 3 | 1 | 0 | 2 | 1/32 |
| matched_random | 64 | 6 | 3 | 0 | 3 | 3/32 |
| offline_oracle | 16 | 4 | 4 | 0 | 0 | 4/32 |
| offline_oracle | 32 | 10 | 10 | 0 | 0 | 10/32 |
| offline_oracle | 64 | 22 | 22 | 0 | 0 | 22/32 |

## Development-set expected value table

The development router uses only the public inspection-domain key and the frozen development estimate. It ranks episodes by `(wrong→right − right→wrong) / development examples`, rounded to milli-completions per query. The table is fitted before held-out labels are opened.

| Domain | Development examples | Wrong→right | Right→wrong | Estimated net benefit / query |
|---:|---:|---:|---:|---:|
| 0 | 32 | 0 | 0 | 0 / 1000 |
| 1 | 32 | 24 | 0 | 750 / 1000 |
| 2 | 32 | 16 | 0 | 500 / 1000 |
| 3 | 32 | 32 | 0 | 1000 / 1000 |
| 4 | 32 | 0 | 0 | 0 / 1000 |
| 5 | 32 | 0 | 32 | -1000 / 1000 |
| 6 | 32 | 0 | 0 | 0 / 1000 |
| 7 | 32 | 0 | 0 | 0 / 1000 |

## Replay, budgets, and receipts

| Lane | Budget | Query receipts | Receipt bytes | Final receipt hash | Hash-chain replay |
|---|---:|---:|---:|---|---|
| e004_combined | 16 | 16 | 9068 | `a6ab6ce69da37b08` | PASS |
| e004_combined | 32 | 32 | 18127 | `aad38462d9b6a200` | PASS |
| e004_combined | 48 | 48 | 27279 | `0bd30d8e6796ae8f` | PASS |
| e004_combined | 64 | 64 | 36270 | `9640e508a3c9beef` | PASS |
| development_voi | 16 | 16 | 9086 | `c6a06a710c4ba00c` | PASS |
| development_voi | 32 | 32 | 18220 | `c45b964252110336` | PASS |
| development_voi | 48 | 48 | 27330 | `8239ed36bfe1e522` | PASS |
| development_voi | 64 | 64 | 36444 | `7ba381017bcba972` | PASS |
| matched_random | 16 | 16 | 9024 | `72d4f7acec2e11fe` | PASS |
| matched_random | 32 | 32 | 18131 | `b166b338fc97fa33` | PASS |
| matched_random | 48 | 48 | 27216 | `9ad0737854a794ae` | PASS |
| matched_random | 64 | 64 | 36394 | `7249572d55e7700f` | PASS |
| offline_oracle | 16 | 16 | 9051 | `11968918d9069876` | PASS |
| offline_oracle | 32 | 32 | 18087 | `02380f20dbc9e8bb` | PASS |
| offline_oracle | 48 | 48 | 27265 | `612f33118efcb7f6` | PASS |
| offline_oracle | 64 | 64 | 36373 | `84a0362f153c2cd5` | PASS |

- Exact resolver and tool budgets: **PASS**
- Illegal commits: **0**
- Duplicate actions: **0**
- Missing actions: **0**
- E002 task replay failures: **0**

## Method limits

The workload contains 256 synthetic held-out episodes and a disjoint 256-episode development set. The observers are frozen deterministic proxies. Inspection uses a stored synthetic second-source payload, not a live external tool or human review. The offline oracle sees held-out labels and inspection fixtures; it is a ceiling only and is not a deployable router. The E004 combined lane preserves the E004 selector and frame-only resolver while paying for and receipting the new query; it intentionally discards the returned payload as a control. The other executable lanes use the same signature-and-confidence resolver on inspected results.

A `PASS` on this bank supports the runtime, query-receipt, and replay contracts only. It does not establish a real-world value-of-information estimate. The next promotion test needs independently sourced inspection results and a new held-out workload.

