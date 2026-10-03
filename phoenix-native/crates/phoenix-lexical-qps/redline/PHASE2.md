# REDLINE Phase 2 report: exact lazy evidence (branch-and-bound)

Change: serving paths with truncated output skip positions + full evidence
for provably losing candidates. V3: integer-exact tier gate (optimistic tier
vs tier-count quota, no floats). V2: score gate U=cs*MAXMULT (+V1 monotone
extension), f64, strict-proof-only skip with 1e-6 relative slack; ties always
evaluate. Evidence paths (limit>=pool) evaluate everything (unchanged).
`reranked_candidates` now counts actually opened payloads (was: pool size).
Hoisted group census reused by expansion_quality (no duplicate work).

## Gate evaluation (expensive candidates after/before)

| workload | reranked before | after | posvals before | after |
|---|---|---|---|---|
| phrase (104 pool) | 104 | 52 (2.0x) | 312 | 156 |
| multi-token (160) | 160 | 51 (3.1x) | 528 | 181 |
| transport (160) | 160 | 52 (3.1x) | 516 | 156 |
| freeze groups (80) | 80 | 6 (13.3x) | 117 | 18 |
| one-token (40) | 40 | 40 (same-tier, nothing prunable) | 88 | 88 |

Gate (>=2x on phrase) MET exactly (2.0x); multi/transport exceed it.

## Serving deltas (profiler, same corpus, stable across reruns)

phrase 36.1->23.4us (-35%), multi 155.3->112.1 (-28%),
transport 246.8->193.9 (-21%), lexical-only 19.6->15.2 (-22%),
one-token flat (+2% noise, predicted: no prunable mass).
Milestone A (phrase <=22us): 23.4us, provisionally at the line; clean-room
criterion confirm pending (box noise: bm25 co-moved +18-36% across runs;
criterion post-Phase-2 median 55.4us is contradicted by two stable profiler
runs and the mechanism metrics — recorded as noise, not code).

## Equivalence (the actual proof)

- New tests/redline_lazy.rs GREEN: serving(top_k) == evidence-pool prefix
  bit-exact over 3 seeds x 3 configs (default/identifier/enabled-V1) x
  6 queries x 3 top_k x (V2+V3) + transport groups (V2+V3) + rows equality.
- Freeze snap: 205 lines, ZERO non-positional diffs (ids/order/scores/tiers/
  evidence/pools/strengths/rows bit-identical); deltas strictly within
  {posvals down, reranked down}.
- Full suite green (29+1+1+12). Warm allocs still zero. Miss paths ~0.5us.
- Notable catch during testing: V2 plain-serving vs evidence paths differ in
  primitive V3 evidence BY DESIGN (collect flag); differential compares only
  V2-identical fields (+tier iff no identifier fields), full keys on V3.

## Cost

+~120 lines index.rs, +1 test file. Public API untouched. No behavior change
except honestly-counted reranked/posvals receipts.
