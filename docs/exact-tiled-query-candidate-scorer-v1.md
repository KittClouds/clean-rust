# Exact Tiled Query/Candidate Scorer v1

## Outcome

Temporal R-GCN validation now scores a two-dimensional grid of query and candidate tiles instead of assigning one complete candidate-universe traversal to each query.

The accepted shape is four queries by 4,096 candidates. Five cold restart-only processes reduced canonical evaluation from the Exact Parallel BLAKE3 Compositor p50 of 5.544 seconds to 4.916 seconds and p95 from 5.616 seconds to 4.999 seconds. Throughput is 976.8 million candidates per second.

Every `f32` score bit, filtered rank, metric, score BLAKE3, and the complete validation certificate remains identical.

## Pressure-point trace

The encoded candidate matrix contains 47,433 rows of 16 `f32` values: approximately 3.04 MB. It fits in the Ryzen 7 5800X3D's 96 MB shared L3, so the 307.345 GB logical-read figure was not equivalent to 307.345 GB of DRAM traffic.

The old query-major scorer still traversed that matrix independently for all 64 queries in a batch. Candidate vectors were shared through L3, but each worker repeatedly loaded and converted the same two `f32x8` vectors into its private execution path.

Query-only tiling was rejected:

| Probe | Evaluation |
| --- | ---: |
| Eight-query tile | 7.435 s |
| Four-query tile | 5.722 s |
| Two-query tile | 5.652 s |

Those shapes reduced candidate loads but also reduced the batch to 8, 16, or 32 scheduling units and created multiple simultaneous output streams per worker.

The accepted design tiles both axes. A full 64-query, 47,433-candidate batch contains 16 query tiles and 12 candidate tiles, exposing 192 independent rectangles.

## L2-sized rectangle

Each four-by-4,096 rectangle has:

- 262,144 bytes of candidate vectors;
- 65,536 bytes of row-major output;
- 320 KiB total primary footprint.

That fits within a 512 KiB private L2 while leaving room for prepared queries and loop state.

The scorer loads a candidate's low and high `f32x8` vectors once, evaluates four prepared queries against them, and writes four independent row streams. Candidate tile 2,048 was tested and rejected: 5.383 seconds versus 5.376 seconds for 4,096 before final inner-loop optimization, with twice as many rectangles.

## Bit-exact arithmetic contract

Tiling changes traversal only. For every query/candidate pair the scorer retains this exact sequence:

1. multiply source lanes 0-7 by decoder-relation lanes 0-7;
2. multiply source lanes 8-15 by decoder-relation lanes 8-15;
3. multiply the prepared low `f32x8` by candidate lanes 0-7;
4. multiply the prepared high `f32x8` by candidate lanes 8-15;
5. reduce low lanes 0-7, then high lanes 0-7, through the same sequential `sum::<f32>()`;
6. add the relation bias;
7. multiply by the unchanged residual scale;
8. after all base scores complete, add the train-only frequency prior exactly once in the original per-query order.

No reassociation, horizontal SIMD reduction, FMA substitution, approximate math, quantization, or changed score layout is permitted.

The four-query hot path is explicitly unrolled. Query preparation, four row bases, and rectangle bounds are computed once outside the candidate loop. The final partial query tile uses the same arithmetic helper through a bounded generic loop.

## Disjoint-write boundary

The row-major score matrix cannot be split into two-dimensional mutable rectangles with ordinary slice APIs. A single private raw-pointer adapter is therefore used.

Its safety proof is structural:

- scorer input validates `scores.len() == queries.len() * candidates.len()` before pointer creation;
- unique Rayon tile indices map bijectively to one query interval and one candidate interval;
- query intervals partition rows and candidate intervals partition columns;
- two different rectangles therefore cannot own the same `(row, column)`;
- every computed index is bounded by the validated matrix dimensions;
- the backing slice remains exclusively borrowed by the adapter until all rectangle jobs join;
- frequency-prior writes begin only after the adapter is dropped and the rectangle join completes.

No unsafe arithmetic touches model weights, query data, artifacts, hashes, or certificate state.

## Memory and reporting

The scorer adds no application score arena, cache, transpose buffer, or per-batch heap allocation. Prepared queries and row bases are fixed stack arrays.

Compared with the compositor gate:

- allocation volume changes from 114,622,724 to 114,660,724 bytes;
- allocation count changes from 2,930 to 2,955;
- peak working set remains effectively flat at 139,993,088-139,997,184 bytes.

The 38,000-byte process-level delta is bounded Rayon scheduling growth. It does not scale per query or candidate.

Evaluator reports now use `phoenix-canonical-evaluator-restart-report/v4`; integrated trainer reports use `phoenix-canonical-evaluator-throughput-report/v4`. Both certify `queryTile: 4` and `candidateTile: 4096`.

## Certified performance

| Gate | Compositor v1 | Tiled scorer v1 |
| --- | ---: | ---: |
| Evaluation p50 | 5.543666 s | 4.916206 s |
| Evaluation p95 | 5.615697 s | 4.998943 s |
| Best of five | 5.436755 s | 4.883914 s |
| Candidate throughput | 866.3M/s | 976.8M/s |
| Allocation volume | 114,622,724 bytes | 114,660,724 bytes |
| Peak working set | 139.964-139.977 MB | 139.993-139.997 MB |

The p50 cut is 11.32%, saving 627 milliseconds per complete validation.

All five runs reproduced:

- model ID `b3-261c2935b5b80b6f999f7cb065c9bd53bab6a7f8436e8a8a08bf38e9de2b7e43`;
- weight BLAKE3 `b3-f4d14dc5858e86d590fd39647018c6ee4a40c5f23662f9eb381afd30c61bfae3`;
- score BLAKE3 `b3-47405caa0aabcd06c9445f8e0ab190aac9cd7371cb95ae9029cb283b445e9e7f`;
- validation certificate `b3-84cc094b232ee3b0c645436689dd84fb3fa66c73f6b995438c0b855fa65d8519`;
- exact MRR `0.05817527887231176` and identical Hits@1/3/10.

The p50 restart report is `b3-d85588d3e50c60797d97c833041bdaa4383873287a1e0f5d3d5c393fecdc39d9` under `target/graph-research-models/exact-tiled-scorer-v1-final-gate-4`.

## Proof gates

- Direct query-major and tiled score vectors compare every `f32::to_bits()` value across a partial final query tile.
- The real 47,433-candidate workload crosses eleven full candidate boundaries plus a partial tile and reproduces the frozen certificate in five cold processes.
- All 44 graph-research tests and all 8 trainer tests pass.
- Strict Clippy passes for the changed research library and every trainer target.
- Rust formatting, diff, file-size, model identity, weight identity, and report-parity checks pass.
- The real test partition remains unclaimed and unevaluated.

## Remaining physics limit

Stage-level accounting now resolves the 4.9-second envelope: scoring is 58.59%,
stream composition is 9.99%, and the concurrent hash/rank join is 31.33% at the
coherent p50 gate. The audit and next-cut decision are frozen in
`docs/stage-level-cycle-accounting-v1.md`.
