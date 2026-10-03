# V2-0 RESULTS — the frozen cue screen

**Experiment:** `FF-S15-V2-EVAL-00` **Bank:** BANK-v2 sealed under constitution v0.7
(`ff-s15-bank-02`, freeze `923fb971…03417e`) **Fit:** TRAIN 400,000 **Scored:** DEV 50,000, once
**Receipt:** `results/v2-0-receipt.json` **Elapsed:** 7,913 s

## Instrument

**B0 reproduced every target exactly on all 50,000 DEV rows** (`all_exact: true`). The bank
re-derives its own labels from the record, so the instrument is sound. A miss here would have been
an instrument defect and would have stopped the rung before any score was read.

## Per-baseline macro-F1 on DEV

| target | B1 majority | B2 schema/freq | B3 lexical | B4 surface cue | B5 graph-only | best | headroom | CUE_ACCESSIBLE |
|---|---|---|---|---|---|---|---|---|
| disposition | 0.1082 | 0.3715 | 0.2565 | **0.3805** | 0.2900 | B4 | 0.6195 | no |
| reason | 0.0342 | **0.4533** | 0.0382 | 0.2676 | 0.2562 | B2 | 0.5467 | no |
| missing_cardinality | 0.2763 | **0.6061** | 0.4248 | 0.4906 | 0.5063 | B2 | 0.3939 | no |
| requestability | 0.2763 | 0.4808 | 0.6070 | **0.6609** | 0.4454 | B4 | 0.3391 | no |
| first_action_type | 0.0827 | 0.0839 | 0.0829 | **0.0968** | 0.0872 | B4 | 0.9032 | no |
| **conflict** | 0.4901 | 0.9240 | 0.9618 | **1.0000** | 0.4901 | B4 | **0.0000** | **YES** |

## Decision rule 4 — instrument sanity

B0 = 1.0 on all six targets. **PASS.**

## Decision rule 1/3 — cue dispositions

### `conflict` — CUE_ACCESSIBLE at 1.0000. **DISPOSITION: DIAGNOSTIC-ONLY.**

A four-feature surface-cue tree reaches **perfect** macro-F1. The carrying features are:

```text
phrase_you may ask        2 splits
phrase_nobody can tell    2 splits
phrase_reports that       1 split
phrase_says               1 split
```

and it scores **1.0 in every one of the eight renderer families** (6,250 DEV rows each), so there is
**no stratum in which the cue is absent** and the target cannot be rescued by restriction.

**Ruling:** no later rung may make a model claim on `conflict`. Any such claim would be
indistinguishable from a two-phrase lookup. The target is retained for **diagnostic use only**.

**Root cause, stated so v3 can fix it rather than inherit it:** the bank renders a fact *report*
using the fixed phrasings `reports that` / `says`, and a *non-requestable* fact using
`nobody can tell`, so the surface form of the report channel is deterministically coupled to the
conflict flag. **This is a renderer artifact, not a semantic property.**

**Prescribed remedy for the next bank generation:** decorrelate report phrasing from the conflict
label — vary report surface realizations independently of whether a conflict exists, so that no
fixed phrase set predicts the flag. Until that is done, `conflict` is diagnostic-only.

### `requestability` — 0.6609, **not** cue-accessible but **cue-contaminated**.

The carrying features are temporal and length features, not semantic ones:

```text
phrase_before tick   4 splits      phrase_from tick   3 splits
phrase_until tick    4 splits      length_decile     4 splits
sentence_count       4 splits
```

0.66 is below the 0.80 rule, so it is admissible — but the cue is *rendering geometry*, not
information availability. **Ruling: admissible, flagged `RESTRICTED_TO_STRATA`.** A claim on
`requestability` must be reported within strata and must not be pooled, because a pooled number
would partly measure sentence shape.

### `missing_cardinality` — 0.6061 by **B2, which sees counts only and no content**.

The carrying features are the record's own bookkeeping fields:

```text
hidden_facts   weight 3.00      (dominant)
slot_markers   weight 2.48
reports        weight 1.10
```

`hidden_facts` count is close to a direct proxy for `|M|`. **Ruling: admissible, flagged
`RESTRICTED_TO_STRATA`, with the specific caveat that this target is substantially predictable
from bookkeeping counters rather than from semantics.** A later rung that improves on 0.61 may
have learned the counter, not the concept.

### `first_action_type` — 0.0968, essentially at chance. **The largest headroom in the bank.**

10 classes with `NA` = 35,243 of 50,000, so the majority floor is already ~0.10. **Every baseline
sits at the floor**, and no cue is detectable. Headroom 0.9032.

**This is the MOVE wall appearing as a measurable target.** The bank's own v2 action semantics are
formally decidable from the record — B0 does it exactly — but *no cheap cue recovers it*. That is
the single most valuable number V2-0 produced, because it is the first rung-local evidence that
the operationalization stage is a real wall rather than an artefact of an earlier interface.

**Ruling: fully admissible, and promoted as the primary pressure target for the ladder's Stage 4.**

### `disposition` (0.3805) and `reason` (0.4533) — admissible, unremarkable.

`reason` is reached best by **schema counts alone** at 0.45 across 15 classes. No lexical signal at
all (B3 = 0.0382, *below majority*), which is the strongest available evidence that the reason head
is **not** solvable from surface text. That is a genuinely good property of the bank.

## Strata and power

Strata with fewer than 200 DEV rows are `UNDERPOWERED` and not scored. Two action strata are
underpowered by construction: `TRANSFER` (n=38) and `WAIT` (n=71) on DEV. This is consistent with
v2's own G06 coverage receipt, which required every core action to be non-zero in all six cells —
non-zero, not frequent. **No claim may be made about `TRANSFER` or `WAIT` behaviour.**

## Recorded deviations (in the receipt, with direction of bias)

- **DEV-1** — B3 fitted on a deterministic head subsample of TRAIN (100,000 of 400,000). A
  full-TRAIN sparse L-BFGS measures ~260 min/target with gradient norm still 1.7e-1 after 200
  iterations. **Bias direction: a subsample can only understate B3.** So a CUE_ACCESSIBLE flag
  raised with B3 is conservative; a target clearing nothing here is **not** fully certified against
  a full-TRAIN B3. Targets whose best baseline was *not* B3 (5 of 6) are unaffected in their
  verdict.
- **DEV-2** — the 2^18 hash space is honoured exactly, but only **21,251** buckets are ever
  occupied by the templated renderers. B3 is a far weaker probe than the nominal space suggests.
- **DEV-3** — both logistic regressions fit an intercept (uninterrupted by the constitution;
  after L2 tf-idf normalisation every row sums to zero, so the intercept carries the class prior).

## What V2-0 licenses downstream

**Admissible target set for any later rung:** `disposition`, `reason`, `first_action_type`,
plus `requestability` and `missing_cardinality` under stratum restriction.

**Not admissible:** `conflict` (diagnostic-only; no model claim).

**Primary Stage-4 pressure target:** `first_action_type`, headroom 0.9032, no detectable cue.

**The bank is not cue-solvable.** One target in six is trivially solvable and has been quarantined;
the two highest-scoring remaining targets are cue-contaminated by rendering geometry and by
bookkeeping counters, and both are flagged for stratified reporting only. The most important target
sitting behind a legitimate capability claim is `first_action_type`, at chance.
