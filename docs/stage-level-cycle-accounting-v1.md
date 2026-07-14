# Stage-Level Cycle Accounting v1

## Decision

The canonical evaluator is no longer an opaque 4.9-second envelope. Its exact
critical path is now measured at the authoritative evaluation boundary without
changing score arithmetic, rank semantics, stream bytes, hashes, or certificates.

The next optimization cut should remain in the scorer, but it should change the
SIMD axis from feature lanes to candidate lanes. The scorer owns 58.59% of the
coherent p50 run. Stream composition is only 9.99%, and the already-overlapped
hash/rank join is 31.33%.

## Accounting contract

The profiled validation surface reports monotonic wall-clock microseconds for:

- scorer execution;
- canonical stream composition and finite-value validation;
- the BLAKE3 branch;
- the exact filtered-ranking branch;
- the concurrent hash/rank join critical path;
- metric accumulation;
- the complete evaluator.

Hashing and ranking run concurrently. Their individual branch times expose
imbalance and contention, but they must not be added together as latency. The
`hashRankJoinMicros` field is the authoritative critical-path cost.

The normal evaluator remains unprofiled. The restart evaluator opts into the
profiled surface and emits schema
`phoenix-canonical-evaluator-restart-report/v5`, so instrumentation does not
become mandatory production overhead.

## Five cold-process gates

The real validation workload contains 1,582 bounded batches. Every run retained
the same model, weights, score digest, validation certificate, ranks, and metrics.

| Gate | Evaluator | Scorer | Compose | Hash | Rank | Hash/rank join |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4.772450 s | 2.811333 s | 0.488746 s | 1.397639 s | 1.059589 s | 1.468005 s |
| 2 | 4.887753 s | 2.867267 s | 0.486626 s | 1.451490 s | 1.106853 s | 1.529284 s |
| 3 | 4.892524 s | 2.866631 s | 0.488533 s | 1.460470 s | 1.106855 s | 1.532937 s |
| 4 | 5.097941 s | 2.952523 s | 0.503904 s | 1.568728 s | 1.183588 s | 1.637057 s |
| 5 | 4.986417 s | 2.908933 s | 0.497563 s | 1.502612 s | 1.136550 s | 1.575245 s |

Outer cold-process evaluation p50 is 4.894295 seconds and p95 is 5.099582
seconds. The nested evaluator differs by only 1.60-1.86 milliseconds of restart
wrapper overhead.

Gate 3 is the coherent p50 run:

| Critical-path stage | Time | Share |
| --- | ---: | ---: |
| Exact tiled scorer | 2.866631 s | 58.59% |
| Stream composition | 0.488533 s | 9.99% |
| Concurrent hash/rank join | 1.532937 s | 31.33% |
| Metric accumulation | 0.000080 s | <0.01% |
| Residual setup/finalization | 0.004343 s | 0.09% |

Within the join, hashing takes 1.460470 seconds and ranking takes 1.106855
seconds. Hashing is 95.27% of join duration and is the longer branch, but the
whole join is still less than one third of total latency.

## Interpretation

The measurements reject three tempting cuts:

- Metric work is immaterial.
- Wrapper and setup work are immaterial.
- Optimizing ranking alone cannot remove its full 1.11 seconds because it is
  hidden behind the longer hash branch.

Eliminating stream composition completely has a hard ceiling of about 0.49
seconds. Eliminating the entire hash/rank join has a hard ceiling of about 1.53
seconds. Scoring is the only stage with a standalone 2.87-second envelope.

Cross-batch double buffering is not selected yet. Scoring, hashing, and ranking
already use the same Rayon pool; overlapping them without isolated pool and CPU
saturation evidence risks converting serial work into contention rather than
reducing wall time.

## Selected next cut

**Exact Candidate-Lane SIMD Scorer v1** was the evidence-backed next ticket and
is now complete. Its design and five-run proof are frozen in
`docs/exact-candidate-lane-simd-scorer-v1.md`.

The current kernel vectorizes the sixteen feature lanes and then performs a
sequential horizontal reduction for each candidate. The proposed spike instead
transposes the bounded encoded candidate matrix into sixteen feature planes and
uses each SIMD lane for a different candidate. Feature products are accumulated
in the original feature order, preserving each candidate's exact scalar
operation sequence while evaluating multiple candidates per instruction.

The cut is accepted only if it proves:

- every score is identical by `f32::to_bits()`;
- score, rank, filter, BLAKE3, and certificate identities remain exact;
- transpose construction is bounded, measured, and paid once per encoded model;
- no frozen sidecar is introduced unless profiling proves restart transpose cost
  material;
- p50 scorer time and total evaluator time both improve materially;
- peak memory and allocation volume remain bounded;
- the locked test partition remains untouched.

If exact candidate-lane accumulation cannot be proven or fails the performance
gate, the fallback cut is composition/hash stream fusion, capped by the measured
0.49-second composition envelope.

## Proof gates

- All 44 `phoenix-graph-research` tests pass from the D: cargo target.
- All 8 Candle trainer/evaluator tests pass from the D: cargo target.
- Strict Clippy passes for the research library and every trainer target.
- The five cold processes reproduce the frozen model ID, weight digest, score
  digest, validation certificate, and metrics.
- Allocation volume remains 114,660,724 bytes with 2,955 allocations.
- Peak working set remains approximately 139.95 MB.
- The real test partition remains unclaimed and unevaluated.

The coherent p50 report is
`target/graph-research-models/stage-level-cycle-accounting-v1-gate-3/b3-9abba80f7760f91e320df7c10d5534e4d76883358e527dde3285ed33c050af57.canonical-evaluator-restart-report.json`.
