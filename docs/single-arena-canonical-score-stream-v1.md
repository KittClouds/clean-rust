# Single-Arena Canonical Score Stream v1

## Outcome

The canonical Temporal R-GCN evaluator now scores, ranks, and hashes one aligned
arena. It no longer materializes a dense score matrix and then copies all 19.21
GB of validation scores into a second canonical hash arena.

The real 4,802,259,219-score workload falls from 4.218809 seconds p50 to
3.059994 seconds p50. This is a 27.47% complete-evaluator cut and reaches 1.569
billion exact candidate scores per second. The best cold process completes in
2.979313 seconds.

## Single-arena layout

Each query row is stored exactly as the certified byte stream requires:

`observed_at:i64-le || source:u32-le || relation:u32-le || scores:[f32-le]`

The arena uses aligned `f32` storage. The first four words of every row hold the
sixteen raw prefix bytes and are never interpreted as floats. The remaining
47,433 words are ordinary native `f32` scores on the supported little-endian
target.

The scorer receives a constrained `CanonicalScoreMatrixMut`. It can obtain only
the score tail for a row. Prefix storage and the complete backing slice remain
private, preventing scorer code from corrupting canonical authority bytes.

The Temporal R-GCN disjoint matrix adapter now accepts a row stride and score
offset. Its existing Cartesian rectangle ownership proof is unchanged; only the
address calculation becomes:

`row * row_stride + prefix_words + candidate`

## Exact execution

For every bounded batch the evaluator:

1. installs the sixteen canonical prefix bytes per active row;
2. scores directly into the strided score tails;
3. exposes the arena immutably;
4. hashes the complete arena with `Hasher::update_rayon`;
5. concurrently ranks the score tails from the same cache lines;
6. validates score finiteness inside the ranking traversal;
7. discards the concurrent hash and exposes no certificate if ranking or finite
   validation fails;
8. retains the same incremental BLAKE3 hasher across all batches and finalizes
   exactly once.

There is no custom BLAKE3 tree implementation, cryptographic hazmat API,
reassociation, score conversion, changed rank order, or changed metric order.

## Memory contract

The one reusable arena is exactly 12,143,872 bytes at batch size 64. Duplicate
score-arena bytes are zero.

Compared with Exact Candidate-Lane SIMD Scorer v1:

- allocation volume falls from 117,699,128 to 105,556,280 bytes;
- the reduction is exactly 12,142,848 bytes, the removed dense score arena;
- allocation count falls from 2,965 to 2,964;
- the 3,036,160-byte runtime candidate-plane view remains unchanged;
- peak working set remains approximately 139.95 MB because an earlier staging
  or encoding phase still establishes the process peak;
- no frozen artifact, sidecar, cache, or mmap write is added.

Restart reports use `phoenix-canonical-evaluator-restart-report/v7` and expose
`canonicalScoreArenaBytes` and `duplicateScoreArenaBytes` directly. Integrated
trainer reports use `phoenix-canonical-evaluator-throughput-report/v5`.

## Five cold-process gates

| Gate | Evaluation | Prefix | Scorer | Hash | Rank | Join |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.059994 s | 0.048279 s | 1.372299 s | 1.568102 s | 1.224421 s | 1.633997 s |
| 2 | 3.082824 s | 0.047416 s | 1.385224 s | 1.584839 s | 1.228465 s | 1.644456 s |
| 3 | 3.156860 s | 0.045720 s | 1.415115 s | 1.637696 s | 1.263431 s | 1.690302 s |
| 4 | 2.979313 s | 0.047753 s | 1.314888 s | 1.546993 s | 1.213382 s | 1.611170 s |
| 5 | 3.058342 s | 0.046310 s | 1.380897 s | 1.570484 s | 1.213950 s | 1.625211 s |

| Gate | Candidate-lane v1 | Single arena v1 | Delta |
| --- | ---: | ---: | ---: |
| Evaluation p50 | 4.218809 s | 3.059994 s | -27.47% |
| Evaluation p95 | 4.603058 s | 3.156860 s | -31.42% |
| Best of five | 4.123197 s | 2.979313 s | -27.74% |
| Candidate throughput | 1.138B/s | 1.569B/s | +37.87% |
| Stream composition | 0.545679 s | zero | eliminated |
| Allocation volume | 117,699,128 B | 105,556,280 B | -12,142,848 B |

At the coherent p50 gate, prefix installation is 1.58%, scoring is 44.86%, and
the concurrent hash/rank join is 53.42%. Only 4.37 milliseconds remain outside
the measured stages.

The shared arena also improves the formerly separate branches: scorer time falls
15.69%, hash time falls 20.87%, ranking falls 14.78%, and join time falls 19.84%
relative to the prior coherent p50. The cache and memory-bandwidth benefit is
therefore larger than the removed copy alone.

## Identity proof

All five cold processes reproduce:

- model ID `b3-261c2935b5b80b6f999f7cb065c9bd53bab6a7f8436e8a8a08bf38e9de2b7e43`;
- manifest ID `b3-eb3b3b7ca9999403b440a87c1a310a4b08c30f579766bb524c064294781f3049`;
- score BLAKE3 `b3-47405caa0aabcd06c9445f8e0ab190aac9cd7371cb95ae9029cb283b445e9e7f`;
- validation certificate `b3-84cc094b232ee3b0c645436689dd84fb3fa66c73f6b995438c0b855fa65d8519`;
- exact MRR `0.05817527887231176` and unchanged Hits@1/3/10.

## Proof gates

- Serial, composed batched, and canonical single-arena certificates are equal.
- Batch sizes 1, 2, 3, 7, 16, and 64 cross hostile 1,044-byte record and
  1,024-byte BLAKE3 chunk boundaries exactly.
- Candidate-lane score bits and canonical arena bytes remain exact.
- Non-finite scores fail before certificate exposure.
- All 46 graph-research tests and all 8 trainer tests pass from the D: target.
- Strict Clippy passes for the research library and every trainer target.
- Rust formatting, diff, file-size, allocation, identity, and certificate gates
  pass.
- The real test partition remains unclaimed and unevaluated.

The coherent p50 report is
`target/graph-research-models/single-arena-canonical-score-stream-v1-probe-1/b3-41b117c69e1f732190def19dfe148cf0123dd41e85df8e5e9de2868e1dc6864c.canonical-evaluator-restart-report.json`.

## Remaining physics

The evaluator has reached the original acceptable three-second envelope without
weakening certification. Hashing is the longer branch inside a well-overlapped
join, while scoring remains the other material stage. Another cut should begin
with a new controlled audit rather than changing rank semantics or partitioning
the Rayon pool speculatively.
