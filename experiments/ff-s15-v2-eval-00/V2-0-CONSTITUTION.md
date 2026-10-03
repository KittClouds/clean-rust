# V2-0 — instrument characterization: evaluation constitution (frozen before any run)

**Experiment:** `FF-S15-V2-EVAL-00`. **Lane:** confirmatory (C-series rules). **Bank:** BANK-v2 sealed under constitution v0.7 (`ff-s15-bank-02`, seal hash in `bank-v2-objects.sha256`).
**Status:** `FROZEN_PRE_RUN`. Nothing in this rung touches a neural model.

## 1. The overarching question of the first campaign

> Which BANK-v2 operations are structurally solvable, cheaply accessible, representation-sensitive, and robust under the explicitly controlled shifts?

This rung (V2-0) answers only the first half of that question's preconditions: **what do cheap non-neural cues already give for free?** It exists to find accidental easy cues, and unreachable or underpowered strata, *before* any model is praised or blamed. Later rungs (V2-1 representation atlas, V2-2 graph interface, V2-3 adaptive prospecting) are outside this document and need their own constitutions.

## 2. What may be read

| allowed | not allowed |
|---|---|
| `out/full/data/TRAIN` and `out/full/data/DEV` (full records, including labels) | `out/full/protected/test-truth/**` (escrowed; `terminal_truth_opened` stays `false`) |
| `out/full/paired/**` (derived from TEST-IID-distribution bases that are **not** rows of the 50,000-world TEST-IID split) | any label, witness or derivation of a TEST-* row |
| `out/full/public/test-inputs/**` for **input-side statistics and baseline predictions only** (no scoring) | scoring on any TEST-* split: that happens once, later, under a separate constitution |

C-G1b is not touched. BANK-v2 is not a confirmation split for it.

## 3. The six baselines (all deterministic, fit on TRAIN, scored once on DEV)

Every baseline is a fixed feature map plus one fixed learner; no hyperparameter is chosen on DEV.

| id | name | features (fixed here) | learner |
|---|---|---|---|
| B0 | oracle | none: re-runs `bank2.algebra.derive` on the record | exact; must score 100% (a sanity check of the instrument, not a baseline) |
| B1 | majority | none | most frequent TRAIN class per target |
| B2 | schema/frequency | counts only, no content: entities per type, number of available actions per type, number of facts per predicate, number of hidden facts, number of reports, number of escalation rules, number of denied permissions, scheduled facts, gates | multinomial logistic regression, L2 = 1.0, 200 L-BFGS iterations |
| B3 | lexical | bag of words over `rendered_text`, lower-cased, 1–2 grams hashed to 2^18 buckets, tf-idf | multinomial logistic regression, L2 = 1.0, 200 iterations |
| B4 | surface cue | the presence or absence of each fixed phrase: `not permitted`, `escalate`, `you may ask`, `nobody can tell`, `also called`/`another name`, `reports that`/`says`/`according to`, `before tick`/`from tick`/`until tick`; plus text length decile and sentence count | decision tree, depth 6, min leaf 50 |
| B5 | graph-only | computed from the **visible canonical facts** (not the text): counts per predicate; number of locations reachable from the actor by `CONNECTED` minus `BLOCKED` edges; whether the goal's entities are reachable; number of conflicting pairs among visible facts; gates and scheduled facts present | decision tree, depth 8, min leaf 50 |

Implementations are written before the first run, tested, and their source hashes go into the receipt.

## 4. Targets in scope

`disposition` (5-way); `reason` (the 16 reason values plus null); `missing_cardinality` (|M| in {0, 1, ≥2}, from the record); `requestability` (for rows with |M| ≥ 1: every unresolved requirement requestable vs some unavailable); `first_action_type` (9-way, EXECUTE rows only); `conflict` (binary).
Targets are read from the record's `TARGETS` and witnesses; none is recomputed by the baselines.

## 5. Reporting strata

For each target and each baseline, on DEV: overall accuracy and macro-F1; and the same by **action type** (of the executed or first action), **reason**, **query source scope**, **slot type** (of the unresolved or consulted requirements), **missing-obligation cardinality**, **renderer family** (V1–V8), and, from the paired panels, **intervention family** (P1–P12).
A stratum with fewer than **200 DEV rows** (or fewer than **200 pairs**) is listed as `UNDERPOWERED` and not scored. Uncertainty: percentile bootstrap, 1,000 resamples, fixed seed `20260930`, 95% intervals.
**Split-axis reporting is deferred.** The OOD axes live only in escrowed splits. V2-0 reports, for each baseline, the distribution of its *predictions* on the public test inputs (per split and per renderer family) and nothing about their correctness.

## 6. Pair analysis (paired panels)

For each family with a declared expected delta (P1 none, P4 missingness family changes, P5 ASK to DECLINE, P6 conflict appears, P10 applicability flips, P11 none, P12 missing and evidence change): the fraction of pairs on which the baseline's prediction changes **exactly when the truth changes**, against the fraction expected by chance given its marginal flip rate. A baseline that flips for the wrong reason on P1 or P11 (the negative controls) is reported as **wording-sensitive**.

## 7. Decision rules (fixed now, applied mechanically)

1. **Cue-accessible target.** A target is flagged `CUE_ACCESSIBLE` if the best of B2–B5 reaches **macro-F1 ≥ 0.80** on DEV. A flagged target needs a written disposition (keep, restrict to strata, or drop) before any later rung may make a model claim on it.
2. **Headroom.** For every target, `headroom = 1 − best non-oracle macro-F1`. Reported, not thresholded.
3. **Cue sources.** When a baseline clears 0.80 on a target, the receipt names the top features (logistic weights or tree splits) that carry it, so the cue can be removed or declared.
4. **Instrument sanity.** B0 must score exactly 100% on every target on DEV and on every pair; any miss is a defect of the instrument and stops the rung.
5. **No rescue.** A flagged or surprising result is reported as found. No baseline is retuned, added or dropped after DEV is scored.

## 8. Procedure and receipt

One script per baseline family under `ff-s15-v2-eval-00/`, a driver that fits on TRAIN and scores DEV once, and `tools/make_results.py` that fills `RESULTS.md` from `results/v2-0-receipt.json` and **guards every prose claim that names a finding**. The receipt records: the freeze hash, the source hashes, TRAIN/DEV row counts and class counts, every stratum's n, and every number in §5–§7.

## 9. Legal boundaries (inherited)

No frozen-LFM features, probe scores, adapters or downstream accuracy. No selecting anything because a model likes it. `terminal_truth_opened=false` throughout. C-G1b remains separate.

## 10. Amendment rule

This document may be amended only **before** the first baseline is scored, by a versioned amendment with a new hash. After the first score, a change is a new experiment, and any post-hoc look is disclosed as exploratory.
