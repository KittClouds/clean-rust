# NLI-UNKNOWN oracle-headroom census (plan, written before anything is computed)

Written 2026-09-29. The ASK rung showed that a dedicated head on the same pooled surfaces adds almost nothing to the existing decision head's `P(ASK)`, and that ASK in BANK is a *negative-evidence*
problem (exactly one requestable fact is missing). The natural independent evidence is a different trained task: NLI (does the premise support the goal?). Before building anything on it, this census computes
the impossible upper bound: **on the ASK rows the existing `P(ASK)` misses, and on the non-ASK rows it wrongly flags, does the frozen NLI head's `P(UNKNOWN)` tell a meaningfully different story?**
No controller, no new model, no new head, no policy change. Read-only on existing Rung 0 heads.

## Data and discipline

BANK-v1 DEV, **CAL half only** (C1's split; the mask is read from C1's verified evidence and the arrays are masked to CAL the moment they load). No HOLD row is selected, used or reported, and no TEST row is read.
The NLI head outputs are rebuilt from cached features and the saved Rung 0 `nli` heads, and must reproduce the sealed Rung 0 NLI predictions on every DEV row (label exact, confidence within 1e-5), or the census stops.
Truth: `labels.policy.decision == ASK`, and the true NLI label of the row (`labels.nli`: ENTAILED, CONTRADICTED, UNKNOWN, or absent).

## What BANK's NLI label looks like (TRAIN-only reading, done before this plan)

`NLI == UNKNOWN` for 85% of ASK rows, but also 43% of ACT rows and 70% of ABSTAIN rows (about 15–17% of rows carry no NLI label). So NLI-UNKNOWN cannot be a standalone ASK detector even when perfect;
its plausible role is a **veto**: a row labelled ENTAILED (all ACT) or CONTRADICTED (all ABSTAIN) is not an ASK row, so a good NLI head could remove false positives of `P(ASK)` without losing true ones.
The census therefore looks at NLI both as the union-style set the plan was first asked about, and as a veto/conjunction.

## Sets and measures (CAL; ASK scorer `A` = existing Rung 0 decision head's `P(ASK)` on the **primary surface `middle_plus_final`**)

- **A, the usable ASK set:** the highest-recall threshold on `P(ASK)` with precision ≥ 0.5 and ≥ 50 rows (the ASK rung's operating region). Its true positives `TP_A`, false positives `FP_A`, recall.
- **N, the NLI-UNKNOWN set:** the same rule on `P(UNKNOWN)` of the **NLI reference head (`layer_m4_final`)**; if no threshold reaches precision 0.5 (expected), N is the top-|A| rows by `P(UNKNOWN)` (size-matched) and its precision is reported instead.
- Intersection `A∩N` and union `A∪N` (true positives, false positives, precision, recall). **Oracle union headroom** `|TP_A ∪ TP_N| / |TP_A| − 1`, and the realizable union's precision.
- **ASK misses recovered by NLI:** truth-ASK rows outside `A` that are inside `N`, and their share of all misses. **ASK false positives shared by NLI:** rows of `FP_A` that are also in `N`, and their share of `FP_A`.
- **Veto/conjunction headroom:** over a grid, the rule `P(ASK) ≥ a AND P(UNKNOWN) ≥ b` (a: 5,000-ppm grid from 50,000; b: 0 to 950,000 in 50,000 steps; b = 0 is `A` itself). The best recall at precision ≥ 0.5 (≥ 50 rows), relative to `A`'s recall.
  This is in-sample on CAL over ~3,800 rules, so it is optimistic; the **noise band** is the same search with `P(UNKNOWN)` shuffled among rows (200 permutations, fixed seed). Real headroom must clear the noise 95th percentile.
- **The ceiling (perfect NLI):** the same conjunction with the *true* NLI label as the veto (keep rows labelled UNKNOWN or unlabelled, veto ENTAILED and CONTRADICTED). No NLI head can beat it. Also the standalone precision of `NLI_true == UNKNOWN` for ASK.
- Sensitivity: the NLI heads of the other three surfaces, paired with the same `A`. A 2-D lift table (deciles of `P(ASK)` × `P(UNKNOWN)` terciles) shows where the information is.

## Rule (fixed now)

The NLI route is **earned** iff, on the primary pairing, **either**
- **(V)** the conjunction headroom is ≥ 25% over `A`'s recall at precision ≥ 0.5, **and** above the noise 95th percentile, **and** the perfect-NLI ceiling is ≥ 25% (a head cannot beat its own ceiling; if the ceiling is below 25% the route is dead whatever the head does); **or**
- **(U)** the realizable union `A ∪ N` reaches precision ≥ 0.5 with ≥ 25% more true ASK rows than `A`.

Otherwise the route is dead and the result says so. The 25% is the C2a bar, chosen there for the same reason. A pass would only *earn* a real experiment (a preregistered NLI-conditioned ASK rule); this census cannot establish that one works.

## Not done here

No policy, no threshold fitting for deployment, no HOLD, no training. Not a rescue of the ASK rung's verdict.
