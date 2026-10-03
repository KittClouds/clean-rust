# C-G1 — score transport and calibration under shift (plan, written before any transform is computed)

Written 2026-09-29. C-G0 left one problem: **ranking survives, calibration does not.** The frozen T1 edge score has real residual information (within the three edge-carrying type pairs AUC 0.938 pooled, 0.861 held), but a threshold fitted on DEV for a 1% edge-loss budget lost 6.65% of edges on pooled TEST, 12.9% on the held renderers and 17% on S9.
The whole edge-score distribution moved (1st percentile of edge scores −0.70 on DEV, −2.5 to −5.1 on TEST renderers), so this is a geometry shift, not a slightly wrong probability. C-G1 therefore asks one narrow question and builds nothing else:

**Can the frozen edge ranking be turned into a pruning threshold whose loss budget transfers to unseen worlds and renderings, using only information the runtime can observe?**
No C0 v2 records, no serving bundle, no new graph capability, no retraining, no controller. If nothing transports, the result is: *T1 supplies robust ranking but not a transportable selective-execution score under the tested shift*, handed to FF as a boundary.

## Frozen inputs

C-G0's evidence, bound by its recorded hashes: the frozen T1 scores for every ordered pair of DEV and TEST (natural universe, 10.1% edges), the TRAIN type-pair counts, and C-G0's integrity gate (Lexi's nine sampled AUCs reproduced). Nothing is re-scored or refit; the scores are used as they are.
**T0** is fixed to its natural form: prune every type pair with **zero edges in TRAIN** (12 of the 15; 76% of TEST non-edges at zero observed edge loss). Everything else is the **residual**, and only residual pairs are transformed and thresholded.

## The transforms (a family of four, zero-training, fixed now — not a sweep)

For each residual pair with frozen raw score `s`, in its **world instance** (one rendered input row; the runtime sees one at a time and knows its candidate set without labels):

1. `raw_logit` — `s` itself. The baseline; expected to reproduce C-G0's failure under the fixed T0.
2. `world_percentile` — the fraction of the row's residual pairs scoring at or below `s`.
3. `typepair_percentile` — the same, within the row **and** its observable ordered type pair (a type pair with a single residual pair gets 1.0, i.e. is never pruned).
4. `robust_world_z` — `(s − median) / IQR` over the row's residual pair scores (IQR floored at 1e-6).

A pair is pruned by T1 when its transformed score is at or below a threshold `t`. All four use only the frozen scores and observable structure; none looks at a label at inference time.
A **shuffled-score control** (raw scores permuted among a row's residual pairs, then each transform) is run to show the transforms are not leaking anything.

## Protocol

For each transform and each DEV budget **ε ∈ {1%, 2%}**: fit one threshold `t` on DEV (the largest `t` whose residual edge loss keeps total DEV edge loss ≤ ε), then apply it **unchanged** to pooled TEST, to the held pool (S7+S8+S9), and to S7, S8, S9 individually.
Report achieved edge loss and pruned share on each, the gain over T0 in points, and, for reference, the transformed-score geometry (1st percentile of edge scores on DEV versus each TEST renderer).

## Gate (fixed now; numbers as approved)

A transform **advances** iff, at **both** operating points:

| | at the 1% target | at the 2% target |
|---|---|---|
| pooled TEST edge loss | ≤ 2% | ≤ 4% |
| held S7/S8/S9 pooled edge loss | ≤ 3% | ≤ 5% |
| pooled TEST gain over T0 (non-edge pruning) | ≥ 5 points | ≥ 5 points |

The looser-than-exact bounds are deliberate: this is still development evidence and the fresh split is the real confirmation. S7, S8 and S9 are **reported individually but not gated**; S9 is expected to be the hard one.
The 5-point gain is measured on pooled TEST at the controlled thresholds (held-pool and per-renderer gains are reported).
If **no** transform advances, C-G1 stops with the boundary result above. If one does, C-G1 earns the graph observer bundle and the C0 v2 operation-argument records — not built here.

## Data status (stated strongly)

DEV fits; TEST and S7/S8/S9 are development-grade: they helped select this operation, **and the transforms were designed after C-G0 showed the TEST-side failure**, so any pass here has been shaped by TEST and is not independent.
The first data with teeth is the **fresh graph split** (sealed, requested separately, untouched by this rung). The four-transform family is small on purpose; no transform is added after seeing results.

## A caution carried into the report

T0's exact transfer is a property of BANK's synthetic schema (twelve type pairs with zero TRAIN edges). It is strong engineering evidence inside BANK and **not** evidence that real Phoenix graphs have equally hard type exclusions.

## Not done here

No C0 v2, no ObserverBundle, no runtime, no new head, no per-renderer guarantees, no use of the fresh split, no additional transforms.
