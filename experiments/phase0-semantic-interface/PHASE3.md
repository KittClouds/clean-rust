# Phase 3 — bidirectional fabric (Lepori's lane). P3-BALANCED

**Question.** When supervision and checkpoint selection are aligned with the balanced semantic
distinctions we actually care about, can the existing graft learn stronger semantic/candidate
state without changing its architecture?

**Outcome: B — stop loss surgery.** Balanced supervision, unique-source weighting and a correct
selection rule together did **not** wake the global pathway. Already-earned candidate legality
was **preserved and slightly improved** (0.7328 → 0.7509). The one-pass global pathway has had
its fair shot under three successive objectives.

## 0. Target-source identity audit

**6 independent canonical sources, not 13 heads.** Every alias claim was verified numerically,
not by name:

| alias | claim | TRAIN mismatches | DEV |
|---|---|---|---|
| `candidate_applicable` | identical to `candidate_legal` | 0 | 0 |
| `candidate_has_unmet_requirements` | exactly `1 − candidate_legal` | 0 | 0 |
| `number_or_structure_of_missing_requirements` | ch0 identical to `missing_information_present` | 0 | 0 |

```
GLOBAL     SRC-SOLVABILITY  SRC-GOAL-SATISFIED  SRC-MISSING-INFO-PANEL  SRC-CONTRADICTION-PANEL
CANDIDATE  SRC-CANDIDATE-LEGALITY  SRC-CANDIDATE-SATISFIES-GOAL
```

Also confirmed: `solvable` is *not* a restatement of `goal_satisfied` (prevalence 0.433 vs
0.363), `candidate_satisfies_goal` is not derived from legality, and the count channel's observed
range is **[0.0, 1.0]** — BANK-v1 supplies only 0/1, so the "count" carries no count information
beyond the binary panel. Structural channels 1–5 remain unsupervised.

### Identity stop

`solvable` and `candidate_has_unmet_requirements` are derived from the **shared executable
simulator**, so they are AVAILABLE for every substrate. A lane reporting them unavailable has a
mapping discrepancy, not a substrate property. This lane resolved both from the canonical source
and trains them. No derivation was invented; no meaning was changed.

Left **unresolved and UNAVAILABLE** for all lanes — BANK-v1 records no canonical field, and
inventing one is forbidden: `requestable_information_present`, `candidate_supported`,
`candidate_has_counterevidence`, `candidate_requires_missing_information`.

## Supervision geometry as implemented

- **Unique-source weighting.** `L_g = (1/|H_g|) Σ_h L_h`. The 3-head legality source contributes
  **one** unit to the candidate family, so `candidate_applicable` and
  `candidate_has_unmet_requirements` cannot buy weight by existing.
- **Balanced BCE**, `π` from **TRAIN only**: `-½[(y/π) log p + ((1−y)/(1−π)) log(1−p)]`.
  Implemented in the stable softplus form. No DEV weights, no focal tuning, no threshold
  tuning, no prevalence clipping (smallest TRAIN prevalence is 0.079, far from overflow).
- **Family-balanced aggregation.** `L_S^(3)` = mean over 4 global sources, `L_E^(3)` = mean over
  2 candidate sources. A family is one conceptual block regardless of head count.
- **One documented interpretation:** each head's BCE uses *its own* label prevalence, so a
  complement head stays properly calibrated, while the `|H_g|` averaging is what prevents
  double-counting. The grouping is the anti-double-weighting mechanism; the per-head prevalence
  is the anti-miscalibration mechanism.
- `L_pair`, `L_var`, `L_CF` dormancy, `m_cap=28`, substrate, surfaces, graft, `d_s`/`d_e` all
  **unchanged**. `L_var` was kept despite its tiny measured contribution — dropping it would be a
  second intervention.

## Result: global sources did not move

| source | P2 BalAcc | P3 BalAcc | P3 acc | macro-F1 | TRAIN prevalence | beats base |
|---|---|---|---|---|---|---|
| `SRC-SOLVABILITY` | 0.5000 | **0.5000** | 0.5530 | 0.3561 | 0.433 | no |
| `SRC-GOAL-SATISFIED` | 0.5000 | **0.5000** | 0.6430 | 0.3914 | 0.363 | no |
| `SRC-MISSING-INFO-PANEL` | 0.5000 | **0.5000** | 0.8360 | 0.4553 | 0.160 | no |
| `SRC-CONTRADICTION-PANEL` | 0.5000 | 0.5202 | 0.1855 | 0.1842 | 0.079 | no |

Aliases, reported separately and **never** counted as independent wins:
`candidate_applicable` 0.7509, `candidate_has_unmet_requirements` 0.7509, count head exact-count
0.8360 (trivial 0.8360) — all `SAME_CANONICAL_SOURCE`.

**On `SRC-CONTRADICTION-PANEL` = 0.5202:** this is *not* a rise. Ordinary accuracy is 0.1855
against a 0.921 majority rate, because the head predicts almost everything positive. It fails the
pre-registered margin (balanced accuracy must exceed `max(π, 1−π)` by >0.01). Counting it would
have produced a false Outcome A, so it is recorded as a degenerate operating point.

## Already-earned capability: preserved and improved

| source | P2 | P3 | TRAIN prevalence | beats base |
|---|---|---|---|---|
| `SRC-CANDIDATE-LEGALITY` | 0.7328 | **0.7509** | 0.349 | **yes** |
| `SRC-CANDIDATE-SATISFIES-GOAL` | 0.5000 | 0.5118 | 0.336 | no |

The three legality-source heads agree to within 1e-9, which is a live confirmation of the alias
audit. Outcome C is excluded: nothing was harmed.

## Action endpoint — still below chance

| | top-1 | chance | MOVE (n=346) | ACTIVATE (n=150) | NOOP (n=435) |
|---|---|---|---|---|---|
| P2-CONSIST | 0.0279 | 0.0357 | 0.0029 | 0.0000 | 0.0575 |
| P3-BALANCED | 0.0247 | 0.0357 | 0.0000 | 0.0000 | 0.0529 |

Reported separately and never folded into the state score.

## The renderer decomposition earned its place

332 meaning-preserving pairs, per target:

| target | both correct | first only | second only | both wrong | disagreement | paired acc |
|---|---|---|---|---|---|---|
| `solvable` | 162 | 0 | 0 | 170 | **0** | 0.4880 |
| `goal_satisfied` | 232 | 0 | 0 | 100 | **0** | 0.6988 |
| `missing_information_present` | 268 | 0 | 0 | 64 | **0** | 0.8072 |
| `contradiction_present` | 22 | 40 | 39 | 231 | **79** | 0.0663 |
| `candidate_legal` | — | — | — | — | 0 | — |
| action | 2 | 4 | 4 | 142 | **81** | 0.0132 |

This is exactly what the decomposition was added to expose. Three global heads achieve
**perfect renderer stability at zero disagreement** — and their paired accuracy is precisely the
majority-class rate. That stability is *vacuous, earned by predicting one class for everything*.
Meanwhile the one global head that genuinely varies across renderers disagrees on 79 of 332
pairs and scores far **below** trivial (0.0663). Where there is real variation, the predictions
are also unstable. A single "renderer stability" number would have hidden both facts.

## The selection-rule fix changed the measurement, not the outcome

```
J_select  0.6421 0.6431 0.6464 0.6460 0.6477 0.6480 0.6478 0.6478   -> best epoch 1
J_S       0.6961 0.6966 0.6961 0.6955 0.6957 0.6958 0.6957 0.6959
J_E       0.5880 0.5895 0.5968 0.5965 0.5998 0.6002 0.6000 0.5997
```

The new rule **still** selects epoch 1. Two consequences:

1. The prior-dominated selection rule was a real defect and worth fixing — it now measures the
   right thing, with aliases counted once and action/renderer excluded.
2. But it was **not** the cause of the flat trajectory. `J_S` sits at ~0.696 ≈ **ln 2**, the
   balanced-BCE value of a constant predictor, at *every* epoch.

So removing the prior-prediction attractor did not wake anything. **The 0.500 balanced accuracy of
Phases 1–2 was never a class-imbalance artifact — it is genuine non-discrimination.**

`D_s` still climbs to 0.0553 by epoch 8 (floor 0.0558), reproducing Phase 2's result at higher
variance: `D_s > 0` still does not imply semantic discrimination. Candidate conditioning holds
(within/between 6.53, conditioned).

## Exit

```
TARGET_SOURCE_REGISTRY_COMPLETE        true    6 sources from 13 heads, all aliases verified
CANONICAL_SOURCE_ALIASES_RECORDED      true    3 aliases, 0 mismatches, TRAIN+DEV
CANDIDATE_UNIVERSE_EXHAUSTIVE          true    m_cap=28, nothing truncated
BALANCED_TRAIN_WEIGHTS_TRAIN_ONLY      true    pi from TRAIN; no DEV weights, no tuning
P3_BALANCED_RUN_COMPLETE               true    8 epochs x 312 steps
BALANCED_SELECTION_RULE_FROZEN         true    J_select, aliases once, no action/renderer
ALL_AVAILABLE_TARGETS_SCORED           true    6 sources + 3 aliases + endpoint
PAIR_CORRECTNESS_DECOMPOSITION_DONE    true    2x2 per target, 332 pairs
PHASE2_ARCHITECTURE_UNCHANGED          true
PROTECTED_TEST_TRUTH_OPENED            false
BANK_V2_USED                           false
PHASE3_RECEIPT_COMPLETE                true
```

## What Phase 3 has earned

**Outcome B. Stop loss surgery.** Three successive objectives — raw latent invariance, prediction
consistency plus variance floor, and balanced unique-source supervision with a correct selection
rule — have all left the global pathway at chance. Phase 1 already ruled out a broken gradient
path; Phase 2 ruled out collapse as the cause; Phase 3 rules out supervision geometry and the
selection rule as the cause.

For this lane the remaining job is stated cleanly: **turn richly contextual candidate structure
into a usable global state and an action computation.** Candidate legality works (0.7509) and
renderer-stable candidate state works; the global semantic state and the action endpoint do not.

Phase 4 earns shared-weight recurrent latent refinement `H → Z_0 → … → Z_T`. Not a covariance
penalty, not a substrate change, not an interface change. If recurrence then hits a relational
composition wall, IHA-style cross-head mixing waits one rung above it.

## Artifacts

- `D:\codex-runs\encoder-contrast-01\phase3\target-source-registry.json`
- `D:\codex-runs\encoder-contrast-01\phase3\balanced\phase3-balanced-receipt.json` + 8 checkpoints
- `D:\codex-runs\encoder-contrast-01\phase3\phase3-synthesis.json`

No recurrence, no new attention, no new surfaces, no new heads, no larger MLPs, no backbone
adaptation, no new supervision, no focal or class-weight sweep, no threshold tuning, no covariance
penalty, no LoRA, no BANK-v2, no protected TEST. Failure preserved, not rescued.
