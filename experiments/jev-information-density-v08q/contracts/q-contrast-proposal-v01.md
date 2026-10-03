# JEV v0.8Q — Single-Dose Gain Intervention

**Status:** `DRAFT_FOR_REVIEW_NOT_SEALED`  
**Execution authority:** none. This document proposes a hard contrast; it does not authorize panel construction, model contact, training, or evaluation.

## Question

Does halving the SHAM auxiliary-event weight increase fact-response gain while retaining materially more local invariance than DUP, without losing response direction or anchor preservation?

The object is a vector, not a score:

```text
direction | gain | boundary crossing | locality | preservation
```

## Arms and the one treatment change

```text
DUP
MATCHED
SHAM
SHAM-LOW = 0.5 × SHAM auxiliary-event weight
```

The R2 per-event objective, optimizer, primary stream, auxiliary identities and event count, event positions, forward schedule, initialization procedure, head, backbone, features, candidate order, 120 optimizer steps, batch boundaries, precision, and training duration remain fixed. SHAM and SHAM-LOW receive byte-identical auxiliary source identities. Only the scalar auxiliary loss multiplier differs.

The R2 loss uses an arithmetic mean over active events. In SHAM-LOW, multiply each SHAM auxiliary event's loss contribution by `0.5` **without changing the reduction denominator**. This avoids normalizing the scalar away. DUP, MATCHED, and full-weight SHAM retain their frozen R2 objective semantics.

Use three new paired seeds, derived prospectively as SHA-256 of UTF-8 `jev-information-density-v08q-run-v01/optimizer-seed/{index}`, first four bytes interpreted unsigned little-endian, indices 0–2:

| Index | Seed | Derivation SHA-256 |
|---:|---:|---|
| 0 | 2540205348 | `2475689706517de6893ca0b09725be8936c56a4a83fd4905cfa2ff60c077bd81` |
| 1 | 2603246505 | `a9632a9b12fb799067c7a224121ea7b1646bd479fde0cc771e1c115a8085502b` |
| 2 | 3565067208 | `c89b7ed4d433bf701bd9c4f4f8dfc3b3772ad6917072e529bc0a5b2f3e8e2af4` |

Within each seed, all four arms start from the same initialization. This is 12 runs; three seeds remain three observed trajectories, not a seed-population estimate.

## Fresh panel and evaluation cadence

Construct a new 2,000-neighborhood panel, 500 in each of the same fixed families (`exposure_control`, `respiratory_monitoring`, `salinity_control`, `vibration_monitoring`) and on the same p0–p3 measurement surfaces. Use the R2 online identity-admission and radius-only matching procedure, with namespace `eval_v08q` and a new Q candidate stream. Consume candidate ordinals 0–699 independently by family, admit exactly 500/family, and stop as `PANEL_ADMISSION_BUDGET_EXHAUSTED` if the fixed budget cannot fill a family; no reseeding or budget expansion. Keep the existing radius gates unchanged: mean relative error ≤0.10, p95 absolute error ≤0.25, and every-family mean relative error ≤0.15. The proposed generator seed is derived from SHA-256 of UTF-8 `jev-information-density-v08q-panel/generator-seed-v01`, first four bytes unsigned little-endian: `90884334` (digest `eec86a05fd812b2b12aa33917d299798babd4a52274de708dcdcc45413a1de4c`). Reuse no P-R2/E1 held-out neighborhood as evaluation data; exclude the sealed training and prior-panel identity sets using the already-frozen identity rules. Do not use evaluation outcomes to select neutral controls.

Train all 12 runs to step 120 without evaluation feedback. Save/evaluate the fixed sparse set `40, 80, 100, 120`; the training path is unchanged. Step 120 is primary; earlier checkpoints are descriptive only. This avoids reopening P's dense timing question. There are 48 trained snapshots plus three shared initialization baselines, or 51 evaluation cells and 408,000 prediction rows at 8,000 rows per cell. No checkpoint selection or promotion.

The panel, feature cache, run schedule, trainer, evaluator, metrics, analysis code, and all hashes must be sealed before training. All trained checkpoints and telemetry must be sealed before the fresh panel is opened. This proposal authorizes neither step.

## Outcomes and estimands

All contrasts are paired within seed and neighborhood. The primary reference is the step-120 checkpoint. Report step 40/80/100 trajectories beside it, but do not use them to select a checkpoint.

### Gain: SHAM-LOW minus SHAM

- Signed mean `new_probability_delta` (`Δp_new`) and its neighborhood distribution.
- `correct_direction` rate, separately; do not treat a positive mean as proof that every response is directionally correct.
- `F_new` and `Strict` rates and counts, separately.
- Exact-delta MAE.

### Locality: SHAM-LOW versus SHAM and DUP

Report sham L1, sham MAP-flip rate, matched-neutral L1, and matched-neutral MAP-flip rate independently. The comparator for the predeclared **material locality advantage over DUP** margin is concurrent DUP, not a historical run. Also report SHAM-LOW minus SHAM locality changes descriptively; the DUP-relative criterion does not imply retention of SHAM-level locality.

### Preservation

Report `A_old`, anchor gold accuracy, the four-cell A/F decomposition, and all of these by each of the four families. The four cells are `(A_old & F_new, A_old & not F_new, not A_old & F_new, not A_old & not F_new)`. No composite capability score.

Use 10,000 family-stratified neighborhood bootstrap replicates, 500 resamples with replacement per family, fixed family order `exposure_control, respiratory_monitoring, salinity_control, vibration_monitoring`, draws materialized family-major, NumPy `method="linear"` quantiles, and one shared resample plan across every arm, seed, and coordinate. Derive the PCG64 seed from SHA-256 of UTF-8 `jev-information-density-v08q-analysis-v01/bootstrap`, first four bytes unsigned little-endian: `3344893480` (digest `28065fc72b4d20e01eae364ce68a4ecc95b6ce04898099388492870da7308bca`). Report the 2.5th and 97.5th percentiles as two-sided 95% paired neighborhood intervals conditional on each seed and the fixed panel. For each preregistered contrast/seed, annotate the practical-margin result and whether its paired interval excludes zero (`YES`/`NO`) side by side; interval status is descriptive and does not replace a practical-margin rule. These intervals do not estimate optimizer-seed variation; no pooled-seed population p-value or universal mechanism claim.

## Frozen effect margins for interpretation

These are prospective classification margins, motivated by P-R2's observed SHAM `Δp_new` range (`0.003175–0.009920`) and by the need to operationalize a **material locality advantage over DUP**. They are not training gates and do not select checkpoints.

P-R2 outcomes are used only to motivate these explicit margins. P-R2 panel rows, features, predictions, or metrics are not Q training or evaluation inputs.

1. **Material continuous gain, per seed:** at step 120, SHAM-LOW minus SHAM `Δp_new` is at least `+0.020`. Report the paired neighborhood interval in every seed and annotate whether it excludes zero; interval status does not replace the practical-margin test. This margin is more than twice the largest P-R2 SHAM endpoint movement.
2. **Direction, per seed:** SHAM-LOW correct-direction rate is at least `99%` and no more than `1` percentage point below concurrent SHAM. If this fails, increased signed movement is not called clean gain restoration.
3. **Boundary response, per seed:** report `F_new` and `Strict` separately. A seed qualifies for the MAP-response label only when **both** improve by at least `10` percentage points versus SHAM in that same seed. Call the MAP response meaningfully increased only if at least two seeds qualify. A continuous-gain result without this criterion is explicitly “movement increased; MAP transition criterion not met.”
4. **Material locality advantage over DUP, per seed:** both SHAM-LOW L1 values (sham and matched-neutral) are at most `0.75 ×` the concurrent DUP values, and both SHAM-LOW MAP-flip rates are no more than the corresponding DUP rates plus `5` percentage points. All four conditions must pass in the same seed. If either DUP L1 is zero, that channel has no demonstrated headroom for a relative improvement and that seed fails this locality criterion. This establishes an advantage over DUP, not SHAM-level locality.
5. **Preservation, per seed:** a seed passes preservation when SHAM-LOW `A_old` is no more than `5` percentage points below SHAM overall and no family is more than `10` points below SHAM. Report every contrast and family cell. A failure is a preservation cost for that seed.

Define `Q_OPERATING_POINT_SEED_PASS` as the conjunction, **within the same seed**, of material continuous gain, direction, material locality advantage over DUP, and preservation. Call a **tunable gain/locality operating point** only if at least two of the three seeds pass this joint rule. Do not assemble the label from different seeds passing different components. MAP boundary response remains an additional, separate label and is not required for the continuous operating-point label.

Define `Q_STIFF_COUPLING_SEED` only when the same seed has material continuous gain and DUP-like locality: for each of sham and matched-neutral L1, `abs(SHAM-LOW - DUP) / DUP <= 0.10`, and both paired MAP-flip-rate differences are within `5` percentage points in absolute value. If a DUP L1 is zero, that L1 ratio is not classifiable and the seed cannot qualify. Call the descriptive stiff-coupling pattern only if at least two seeds qualify jointly. Report all components even when neither summary label is earned.

## Interpretation table

| Observed pattern | Frozen reading |
|---|---|
| At least two `Q_OPERATING_POINT_SEED_PASS` seeds | In those same observed trajectories, the lower weight increased continuous gain, retained direction, preserved a material locality advantage over DUP, and met the preservation limits. It is not proof of a general gain/locality control law or retention of SHAM-level locality. |
| At least two `Q_STIFF_COUPLING_SEED` seeds | In those same observed trajectories, material gain co-occurred with DUP-like locality; consistent with stiff coupling at this dose comparison. If a DUP L1 is zero, that ratio classification is not applicable for that seed. |
| `Δp_new` change is under `0.010` in all seeds and neither `F_new` nor `Strict` improves by 5 points in any seed | No meaningful gain response to this weight change at the frozen resolution. |
| Continuous gain rises but MAP criterion fails | Probability movement increased without establishing useful boundary crossing. |
| Any other combination, including seed/family disagreement | Mixed or heterogeneous response; preserve all coordinates and do not force it into a winner category. |

Vibration remains an observational family slice. No vibration-driven treatment edit, panel reweighting, candidate selection, or threshold change is allowed.

## Scope, sealing, and no-go

Claim scope remains fresh worlds and rendered inputs under the same four families/templates; no novel-family/template generalization. The primary claim concerns which weighted examples train the decision head, not a change to the frozen backbone.

No dose sweep, altered event frequency, extra seed, extended training, intermediate-checkpoint promotion, NewTight, legacy evaluation, Phoenix, or model adaptation. If any threshold or contract field changes after seeing Q outcomes, it requires a new identity.

**This file is a proposal, not a sealed contract or execution authorization.** Before Q can be preregistered, the full run/panel/analysis bundle must bind exact source hashes, training and panel manifests, deterministic implementation identities, restart rules, and the evaluation firewall. No panel or model operation has been performed for Q.
