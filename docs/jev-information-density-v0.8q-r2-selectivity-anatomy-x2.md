# JEV v0.8Q-R2-X2: Selectivity and anchor-side anatomy

**Status:** post-hoc, read-only exploratory analysis of sealed Q-R2 predictions. X2 does not revise Q-R2 or X1.

## Scope

X2 answers three bounded questions using the already-sealed step-120 prediction matrix: do the selective-response outliers coincide with competitor switching; does the anchor lift vary across semantic roles, output slots, or candidate identities; and what happens to anchor old-target correctness and the fixed old-versus-new margin?

The computation used the sealed `old_candidate_id`/`new_candidate_id`, candidate order, family, and probability vectors. It did not use target rows, checkpoints, telemetry, or metrics; it performed no inference and did not open a new panel. The anchor target is `old_candidate_id` under the frozen R2 analysis contract. The raw artifact contains probabilities, not logits.

## 1. Outlier anatomy

The most positive fact-specific new-candidate probability contrast and the most negative fact-specific residual-other-mass contrast are the **same history**, seed `1091781421`:

| History | Selective `p(new)` | Selective other mass | Fact-view strongest-competitor switch | Residual-other identity switch | Anchor old-MAP change |
|---:|---:|---:|---:|---:|---:|
| 1091781421 | **+0.081056** | **−0.101849** | **84.8%** | 35.9% | −0.15 pp |

This is also the highest competitor-switch history. Removing this one history descriptively changes the mean selective `p(new)` across the other 23 histories to **−0.001144**. Thus the full-cohort mean `+0.002281` is not representative of the typical history; it is carried by one large positive outlier, consistent with the median `−0.000756` and 20/24 negative histories.

High switching alone does not identify the same phenotype. For example, seed `154863765` switches strongest competitors in 50.0% of fact-view pairs but has selective `p(new) = −0.002109` and anchor old-MAP improvement of 50 pp. Seed `3393901947` switches in 49.7%, has selective `p(new) = −0.004559`, and anchor old-MAP improvement of 21 pp. Seed `2742373327` switches in 47.9% and has a smaller positive selective `p(new) = +0.018526`. Competitor switching and selective response co-occur dramatically in one history but are not interchangeable summary coordinates.

## 2. What “new” means on anchors

In this R2 panel, role, output slot, and candidate identity are **not counterbalanced**:

| Semantic role | Frozen candidate-array slot | Count among 2,000 neighborhoods |
|---|---:|---:|
| `new` (candidate intended after fact flip) | 1 | 2,000 |
| `old` (anchor target) | 0 | 2,000 |
| other | 2 | 2,000 |
| other | 3 | 2,000 |

The identities are also fixed within each family: `underexposure` is always new for exposure and `overexposure` old; `slow_breathing` new and `rapid_breathing` old for respiratory; `low_salinity` new and `high_salinity` old for salinity; `low_vibration` new and `excess_vibration` old for vibration. Each of these roles/identities occurs in 500 neighborhoods. Consequently, the anchor lift cannot be attributed separately to the semantic `new` role, output slot, candidate identity, or family in this experiment.

On anchors, HALF−1X `p(new)` increases by **+0.020242** on average (positive in 21/24 histories), while `p(old)` decreases by **−0.012141** (negative in 20/24). The new-candidate anchor lift by family is:

| Family / fixed new identity | Mean anchor `p(new)` lift |
|---|---:|
| Exposure / `underexposure` | +0.019429 |
| Respiratory / `slow_breathing` | +0.013546 |
| Salinity / `low_salinity` | +0.022744 |
| Vibration / `low_vibration` | +0.025249 |

These family rows are also identity-specific rows; the design cannot separate those factors.

## 3. Anchor preservation and the criterion-shift reading

The fixed probability-scale anchor margin is defined as `p(old) − p(new)`, so positive values favor the contracted anchor target. Averaged over the 24 seed-level means:

| Anchor coordinate | 1X | HALF | HALF−1X |
|---|---:|---:|---:|
| `p(old) − p(new)` | 0.137376 | 0.104993 | **−0.032383** |
| Old-target anchor MAP correctness | 90.71% | 94.15% | **+3.44 pp** |

The pairwise probability margin moves toward `new` in 20/24 histories (median change −0.033671), which supports a **criterion-like shift on this fixed probability contrast**. But the anchor MAP result does not show an aggregate preservation cost: mean old-target correctness rises, its median change is zero, and seed changes are heterogeneous (8 improve, 5 worsen, 11 unchanged; range −22.8 to +50 pp). A pairwise old/new shift can coexist with better MAP correctness because probability is also redistributed among the other candidates. Thus X2 does **not** establish that one simple boundary displacement explains both the fact-view gap gain and an anchor-error cost.

The right bounded conclusion is:

> **HALF shifts the anchor old-versus-new probability margin toward `new`, while the anchor old-target MAP rate does not decline on average. The fixed R2 construction cannot distinguish a semantic-role shift from slot, identity, or family effects, and probabilities alone do not establish a logit/criterion mechanism.**

This supports keeping the conceptual distinction **“shifting a decision criterion is not the same as improving discrimination,”** but the criterion-shift interpretation remains a hypothesis to test with counterbalanced roles and score-scale measurements.

## Research direction

Close R2, do not run another dose sweep, and do not fit a controller. A next prospective study should counterbalance role, output slot, and candidate identity across fresh histories, retain anchor and fact views, and save logits (or fixed log-odds contrasts) as well as probabilities. Its primary quantities can then separate an anchor/common criterion shift from a fact-minus-anchor discriminability change. If a semantically clean answer-preserving placebo view exists, it can further distinguish fact selectivity from generic input-change sensitivity; otherwise keep the estimand to fact versus anchor.

## Provenance

- Raw predictions SHA-256: `39c3fd8fccbf0a53897ae780b2ddff0bbbf25df2016230d428ed8dea49c11f2c`.
- Q-R2 completion seal SHA-256: `5e5fd8a6b5d8255c57a480b9da4334307cf195bb07cf9cc6c0b200242f8abac4`.
- X1 result/seal were verified before X2; X2 output-root SHA-256: `c5a1b8eb0f2eebf3280af930a989c942e093a53ece092a97a2edc3c00c70768e`.
- X2 machine report and seal: `D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\evaluation-v03\competitor-anatomy-x2\selectivity-anatomy-x2-v01.md` and `selectivity-anatomy-x2-seal-v01.json`.
- All three files bound by the X2 seal and the computed output root were rehashed and matched.
