# QPS V2.01 fused positional cut

V2.01 remains an isolated experiment. It is not registered in Phoenix's
production retrieval path and does not replace BM25 Turbo.

## Frozen architecture

```text
token dictionary
  -> compact term posting ranges
  -> precomputed document-level BM25F impacts
  -> best expansion per query group
  -> coverage-adjusted candidate scores
  -> adaptive top-k selection
       sparse touched-document heap
       or SIMD dense collection + exact quickselect
  -> bounded positional rerank
  -> stable final top-k
```

There is one index. BM25F does not build a second candidate index, and
positional reranking does not reconstruct corpus text.

The builder pays field weighting, length normalization, saturation and IDF
once. The query path retains packed `(term_id, posting_offset)` choices, so the
positional stage opens the chosen posting directly instead of binary-searching
the term directory again.

Exact one-expansion query groups accumulate lexical score, coverage, and their
packed positional handle in one posting walk. Only fuzzy or synonym groups pay
the stamp-and-replay pass needed to choose their best expansion.

The dense selector uses runtime-dispatched `pulp` SIMD to reject all-zero
score-vector blocks, collects the positive `(score, document)` records into a
reused dense buffer, and partitions the exact top K with
`select_nth_unstable_by`. This removes the former `O(matches * log K)` heap
from the dense path. Random posting scatter is not described as SIMD; that
part remains a predictable scalar posting walk. The common squared coverage
penalty is multiplication rather than a generic `powf` call.

## Candidate policy

- One query group: retain `4 * top_k`, bounded by available candidates and the
  hard maximum.
- Multiple query groups: retain at least 64 and normally `16 * top_k`.
- Hard positional pool maximum: 256.
- Sparse selection is used below 35 percent covered-document density.
- Dense SIMD selection is used at or above 35 percent density.
- The exhaustive positional API is an oracle and is not the serving path.

## Frozen statistical protocol

- Both scorers see the same query and immutable corpus state.
- Paired samples alternate `BM25 -> positional` and `positional -> BM25`.
- Warm runs use 32 warmups followed by 3,000 paired observations per bucket.
- The CPU-cache-cold proxy sweeps 128 MiB before each individual scorer and
  records 32 paired observations.
- The cold proxy is not an OS page-cache or fresh-process claim.
- Report p50, p95 and p99 for each scorer.
- Report paired latency-difference p50, p95 and p99.
- Report p99 relative overhead and absolute overhead.
- Report postings visited, positions opened, candidate lane and exhaustive
  recall for each query.
- Run one-token, multi-token, phrase-like, high-frequency, fuzzy-miss and
  no-result buckets.
- Keep adversarial and representative relevance suites separate.
- Hold a 64-document match set fixed while growing the unrelated corpus from
  1,000 to 10,000 to 25,000 documents.

`fuzzy-miss` measures the exact dictionary miss path. Fuzzy expansion is not
implemented inside this scorer; a future fuzzy producer must submit explicit,
quality-weighted query groups.

## Original V2.01 measured truth

Host and build identity remain those frozen in `BENCHMARK.md`. The V2.01 release
run on 2026-07-30 produced:

- Adversarial MRR: positional 1.000, BM25 0.600, delta +0.400.
- Representative MRR: positional 1.000, BM25 0.917, delta +0.083.
- Exhaustive top-10 recall: 1.000 in every query bucket.
- Warm selective phrase p99: positional 25.1 us, BM25 15.0 us.
- Warm selective phrase p99 overhead: 1.67x and +10.1 us.
- Criterion selective phrase estimate:
  - positional: 20.748-21.249 us, center 20.993 us.
  - BM25: 10.943-11.232 us, center 11.083 us.
  - center-estimate overhead: 1.89x and +9.91 us.
- Warm dense multi-token p99: positional 327.7 us, BM25 148.1 us.
- Warm dense multi-token p99 overhead: 2.21x and +179.6 us.
- Fixed 64-document posting-set positional p99:
  - 1,000 corpus documents: 15.7 us.
  - 10,000 corpus documents: 16.1 us.
  - 25,000 corpus documents: 16.5 us.
- Packed index estimate: 27.86 MiB for 10,000 x 96-token documents.
- Warmed scratch/output capacity growth: zero in the regression test.

The dense multi-token result was the active performance warning. The
fixed-posting sensitivity result passed: a 25-fold corpus increase added only
0.8 us to positional p99 while posting and position work remained fixed.

## Dense multi-token tuning result

The exact-group/quickselect cut was measured twice with the unchanged paired
protocol and unchanged 10,000-document corpus:

- Positional warm p99: 199.2 us and 204.7 us, down from 327.7 us.
- BM25 warm p99: 138.9 us and 149.6 us.
- Absolute p99 overhead: +60.3 us and +55.1 us, down from +179.6 us.
- Paired-difference p99: +132.7 us in both confirmation runs.
- Multi-token exhaustive top-10 recall: 1.000 in both runs.
- Reranked candidates remained 160; the speedup did not shrink the relevance
  pool.

The new dedicated dense Criterion group reported:

- Positional: 117.83-119.95 us, center 118.87 us.
- BM25: 44.444-45.955 us, center 45.166 us.
- Center-estimate overhead: 2.63x and +73.70 us.

The existing selective Criterion group also improved by 9.23 percent to a
19.538 us center estimate. Relative overhead remains meaningful for scaling,
but the dense warm absolute and paired p99 deltas now both clear the 150 us
warning band.

Tuned release artifact:

- Binary:
  `C:\phoenix-bin\qps-v2-experiment\qps-v2-01-dense-quickselect.exe`
- Size: 1,878,528 bytes.
- SHA-256:
  `4145B14E3794C4FEBAA3DF5DD297D2BFCBF912840060F2B8863E4A568E7024BC`

## Stop/go gates

V2.01 may continue toward a production-quality cohort only while all of these
remain true:

1. Representative `delta MRR > 0`.
2. Frozen adversarial MRR remains 1.000.
3. Bounded candidate recall at top 10 remains 1.000 against the exhaustive
   positional oracle.
4. Warm searches perform no capacity growth after one warmup.
5. Position payloads are opened for no more than 256 candidates.
6. Fixed-posting positional p99 stays within 20 us through 25,000 corpus
   documents on this host.
7. Warm non-empty-query `positional p99 - BM25 p99` remains below the
   provisional 250 us service budget.
8. A 150 us warm p99 delta is the warning band; both dense multi-token
   confirmation runs are below it.
9. Packed index size does not exceed the current 27.86 MiB fixture result
   without an explained feature addition.
10. No production registration occurs until Phoenix's real frozen qrels and
    query distribution pass the same protocol.

## Next tuning order

1. Add a broader ordinary-query cohort and per-bucket confidence intervals.
2. Add allocation counters rather than capacity fingerprints alone.
3. Add mmap opening only after the packed page format is frozen.
4. Evaluate DiskANN fusion through reciprocal-rank or calibrated score fusion;
   do not mix vector authority into the lexical index.
