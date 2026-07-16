# Exact Candidate-Lane SIMD Scorer v1

## Outcome

The frozen Temporal R-GCN evaluator now scores eight candidates per SIMD
instruction while preserving the previous feature-0-through-feature-15
floating-point sequence independently in every lane.

On the real 4,802,259,219-score validation workload, complete cold-process
evaluation falls from 4.894295 seconds p50 to 4.218809 seconds p50. The 13.80%
cut saves 675 milliseconds and raises end-to-end throughput from 981.2 million
to 1.138 billion exact candidate scores per second.

## Exact arithmetic contract

The previous scorer used two `f32x8` vectors for one candidate, materialized
sixteen products, and reduced them sequentially. The new scorer changes only the
independent SIMD axis:

1. query preparation computes the same sixteen source/relation products;
2. each candidate SIMD lane starts at positive zero;
3. feature planes 0 through 15 are visited in ascending order;
4. each lane multiplies the same prepared feature by its candidate value;
5. each product is added to that lane's accumulator before the next feature;
6. the unchanged bias is added;
7. the unchanged residual scale is multiplied;
8. train-only frequency priors are added afterward in the original order.

There is no horizontal SIMD reduction, reassociation, FMA request, approximate
math, quantization, or score-layout change. A dedicated test compares every
valid lane with the old feature-lane implementation by `f32::to_bits()`, across
four queries and a padded partial candidate block.

## Bounded runtime transpose

Model encoding constructs sixteen feature-major planes from the already encoded
node rows. Each plane is padded to eight candidates, allowing one aligned logical
block load at the final partial tail without a branch or out-of-bounds read.

For 47,433 candidates the view is exactly 3,036,160 bytes. It is:

- allocated once per encoded model;
- built in parallel across sixteen independent planes;
- never serialized or included in model identity;
- absent from the frozen model manifest and mmap weights;
- immutable throughout evaluation;
- reused by every validation batch.

Five-run median construction time is 927 microseconds. This is not material, so
no frozen feature-plane sidecar is justified.

## Scheduler and writes

The accepted Q4 x C4096 two-dimensional rectangle scheduler remains unchanged.
Every candidate boundary is divisible by eight. A rectangle loads each candidate
feature vector once per eight candidates, advances four independent query
accumulators, and writes the same disjoint row-major score coordinates through
the existing safety-proven matrix adapter.

The final candidate rectangle writes only its valid lanes. Partial query tiles
reuse the first prepared query in ignored SIMD slots and expose only the actual
rows. Frequency-prior writes still begin after every rectangle joins.

## Five cold-process gates

| Gate | Evaluation | Scorer | Compose | Hash/rank join | Plane build |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 4.603058 s | 1.755483 s | 0.626852 s | 2.213012 s | 0.927 ms |
| 2 | 4.223745 s | 1.633252 s | 0.540997 s | 2.041555 s | 0.998 ms |
| 3 | 4.218809 s | 1.627680 s | 0.545679 s | 2.038333 s | 1.011 ms |
| 4 | 4.164027 s | 1.611269 s | 0.537603 s | 2.008045 s | 0.888 ms |
| 5 | 4.123197 s | 1.592865 s | 0.537462 s | 1.985845 s | 0.813 ms |

| Gate | Tiled feature-lane | Candidate-lane SIMD | Delta |
| --- | ---: | ---: | ---: |
| Evaluation p50 | 4.894295 s | 4.218809 s | -13.80% |
| Evaluation p95 | 5.099582 s | 4.603058 s | -9.74% |
| Best of five | 4.774046 s | 4.123197 s | -13.63% |
| Coherent p50 scorer | 2.866631 s | 1.627680 s | -43.22% |
| Candidate throughput | 981.2M/s | 1.138B/s | +16.00% |
| Allocation volume | 114,660,724 B | 117,699,128 B | +3,038,404 B |
| Allocation count | 2,955 | 2,965 | +10 |
| Peak working set | about 139.95 MB | about 139.95 MB | flat |

All five runs reproduce:

- model ID `b3-261c2935b5b80b6f999f7cb065c9bd53bab6a7f8436e8a8a08bf38e9de2b7e43`;
- manifest ID `b3-eb3b3b7ca9999403b440a87c1a310a4b08c30f579766bb524c064294781f3049`;
- score BLAKE3 `b3-47405caa0aabcd06c9445f8e0ab190aac9cd7371cb95ae9029cb283b445e9e7f`;
- validation certificate `b3-84cc094b232ee3b0c645436689dd84fb3fa66c73f6b995438c0b855fa65d8519`;
- exact MRR `0.05817527887231176` and unchanged Hits@1/3/10.

Restart reports use `phoenix-canonical-evaluator-restart-report/v6` and expose
the plane bytes and construction time independently.

## Proof gates

- Candidate-lane and feature-lane arithmetic match by `f32::to_bits()`.
- Query-major and tiled scoring remain bitwise identical across a partial query
  tile.
- The real workload crosses every full C4096 boundary and a padded final tail.
- All 45 graph-research tests and all 8 trainer tests pass from the D: target.
- Strict Clippy passes for the research library and every trainer target.
- Rust formatting, diff, file-size, model identity, score identity, and
  certificate checks pass.
- The real test partition remains unclaimed and unevaluated.

The coherent p50 report is
`target/graph-research-models/exact-candidate-lane-simd-v1-gate-3/b3-49724f3658828e9284399f76bdb27635dbf4ca6c92de36f46abde781278f6fdc.canonical-evaluator-restart-report.json`.

## New pressure point

The scorer is no longer the majority stage. At the new coherent p50 it consumes
38.60% of evaluator time, stream composition consumes 12.94%, and the concurrent
hash/rank join consumes 48.34%. Hashing remains the longer branch.

The next cut is complete in `docs/single-arena-canonical-score-stream-v1.md`.
Scoring, ranking, and hashing now share one canonical arena, eliminating stream
composition and reducing complete evaluation to 3.059994 seconds p50.
