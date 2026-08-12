# QPS V3 Phase 8 checkpoint — 2026-08-11

This checkpoint is the current fail-closed promotion truth. V2 remains active.

## Canonical checkpoint

- Checkpoint: `865b45f8e732-6295b016f13f`
- Active judgments: `5,080`
- Unique queries: `1,503`
- Independent sources: `3,782`
- Explicit or curator-confirmed judgments: `5,080`
- Release query intersections: `0`
- Training release-evidence intersections: `0`
- Graded release-evidence intersections: `0`

The authoritative pointer is:

`C:\benchmarks\phoenix-qps-v3-20260804\review-checkpoints\current.json`

## Phase status

| Phase | Status | Receipt or artifact |
|---|---|---|
| 4 | verified | `phase4-qualified-ledger.json` |
| 5 | verified | `phase5-corpus-readiness.json` |
| 6 | verified | `phase6-grouped-split-v2.json` |
| 7 | verified | `phase7-linear-model-v2.json` |
| 8 | blocked | `phase8-quality.json` |

All paths above are inside:

`C:\benchmarks\phoenix-qps-v3-20260804\review-checkpoints\865b45f8e732-6295b016f13f`

## Phase 6 proof

- Training/development/blind judgments: `3,389 / 843 / 848`
- Ratios in basis points: `6,671 / 1,659 / 1,669`
- Maximum ratio deviation: `671` bps
- Atomic-component tolerance: `2,474` bps
- Missing major classes: `0 / 0 / 0`
- Query-family, source, near-duplicate, entity-family, and collection-time leaks: all `0`
- Future-time ordering violations: `0`

The split rebalancer now prioritizes complete class coverage inside the already
declared atomic-component ratio tolerance. It does not split components or move
future holdouts.

## Phase 7 proof

- Artifact size: `6,250` bytes
- Artifact SHA-256: `26801db1c4c77de8cf458b1508f072d498554142288ea05c26a4dacff4c8205c`
- Development pairwise accuracy: `0.7698695`
- Training loss: `0.99755335` to `0.760763`
- Deterministic training: pass
- Non-negative monotonic weights: pass
- Primitive 30-feature schema only: pass
- V2 composite features absent: pass

## Phase 8 result

The quality run uses the independent v9 graded suite built from NFCorpus test
and LoCoMo conversations 8–9. The older 100-query suite is release-derived and
is no longer the canonical default.

| Gate | Current | Target | Status |
|---|---:|---:|---|
| LongMemEval hit@10 | `0.984` | `>= 0.984` | pass |
| LongMemEval MRR | `0.898899` | `>= 0.910` | fail |
| Independent stretch MRR | `0.543202` | `>= 0.920` | fail |
| Independent NDCG@10 change | `-0.014278` | `>= +0.020` | fail |
| Held-out top-1 improvement | `+4.184` points | `>= +2` | pass |
| Held-out pairwise accuracy | `0.785377` | `>= 0.80` | fail |
| Every major class accuracy | two classes below target | `>= 0.75` | fail |
| Worst query-shape MRR regression | `0.016345` | `<= 0.005` | fail |
| Mixed suite hit/MRR/top-1 | `1.000 / 1.000 / 1.000` | unchanged | pass |
| Constitutional regressions | `0` | `0` | pass |
| Candidate-pool mismatches | `0` | `0` | pass |
| Oracle recall regressions | `0` | `0` | pass |
| Training/graded release evidence intersections | `0 / 0` | `0 / 0` | pass |

The weakest blind classes are partial-match saturation (`0.35`) and
length-prior failure (`0.411765`). A deterministic reason-balanced 96-model
development grid was tested as a diagnostic and rejected: it worsened release
and graded quality without closing either class. Its code was not retained.

## Boundary and next cut

This is no longer a Phase 5 volume problem. The reviewed semantic judgments
expose a representation/capacity limit in the current non-negative linear model
over the frozen 30 primitive features. More rows from the same distribution are
not evidence that the six remaining gates will close.

Phase 11 is not yet eligible: the linear challenger has not passed Phase 8 and
the ledger has fewer than 10,000 reconciled active pairs. The next justified
cut is a residual-analysis decision: either add a predeclared primitive evidence
signal that distinguishes the failing cases, or revise the Phase 11 eligibility
order and test a small monotonic interaction model as a diagnostic without
calling it promotable.

The checkpoint runner is resumable, writes create-only downstream artifacts,
checks each phase before invoking the next, and records `phase_8_blocked` on a
failed quality receipt.
