# JEV v0.8Q-R3 Selectivity Protocol v03

**Status:** contract construction in progress; no confirmatory panel, training, or evaluation has started. v01/v02 calibration artifacts remain design-only and are excluded from the confirmatory cohort.

## Decision and measured design evidence

R2/X1/X2 remain closed. R3 is a prospective balanced-polarity successor, not a literal replication of R2. It asks whether a late change from auxiliary SHAM multiplier 1.0 to 0.5, after a common SHAM-1.0 history through step 80, moves the semantic-role criterion coordinate, fact discrimination, or both. The history is the experimental unit; neighborhoods measure each history.

The new outcome-blind step-120 calibration resolves the ratio-floor feasibility question on the 1× side. Forty-eight balanced-training calibration histories, already excluded from R3, continued from their sealed step-80 checkpoints through step 120 at 1× only. The terminal checkpoint tree was sealed before a target-free summary. No HALF branch, confirmatory panel, targets, or treatment comparison was used.

| Calibration quantity | Observed value |
|---|---:|
| S120, 1× minimum / median / maximum | 0.011725 / 0.300142 / 2.163512 |
| Histories with S120, 1× >= 0.01 | 48 / 48 |
| Wilson 95% interval for calibration support | 92.6%–100% |
| Within-history S120 SE, median / maximum | 0.000181 / 0.000987 |
| S_min / maximum observed SE | 10.13× |
| S80–S120, 1× descriptive Pearson r / OLS slope | 0.387 / 2.105 |

Decision: retain `S_min = 0.01` and the fixed joint ratio-eligibility requirement of at least 173 of the registered 192 histories. This calibration supports baseline 1× feasibility; it does not measure or guarantee HALF eligibility. If joint coverage is below 173, R is `NOT_ESTIMABLE_FOR_COHORT`; no floor change or eligible-subset headline is allowed. If the confirmatory median S1X is below 0.01 and the D interval contains zero, describe baseline discrimination as too weak to assess attenuation, not as evidence of no effect.

The first target-free reader stopped before loading a head because its adapter expected `fact_flip` while the panel schema is `fact`. That failed invocation is preserved. A separate v02 reader consumed only the sealed step-120 checkpoints and the panel's `anchor`/`fact` view identities, wrote aggregate history summaries, and read no target field. No training was repeated. The output is design evidence only.

Calibration bindings: step-80 checkpoint tree `0fd972996eaf33a9199deeec3ebdf3cec63f28ad9393c3b76c020c2be23cde97`; step-120 checkpoint tree `2ec37b7f57a039025f62705c9342993d0b61ed7e4c6c76e36422ed5d3fc77caf`; target-free S120 result SHA-256 `cd50ec49d5d2196cc92df0bb18276f2d10643d2cc5dc12b928dc6459bea16fab`, root `a6fd2b857a9b7b42dde965ccf57b7106d44b26c2d0e3b41876b8bedd8913bdea`. Full percentiles and scope are in [the v02 construction record](jev-information-density-v08q-r3-selectivity-protocol-construction-v02.md).

The sealed outcome-blind simulation used the R2 design-only history table crossed with the 48 balanced-training S80 calibration values. It chose N=192 because, in the specified 0.005-log-odds D change across the calibrated S80 10th–90th percentile span, the two-sided HC3 interval excluded zero in about 90% of 5,000 simulated cohorts while null rejection remained near 5%. For the R2-resampling 10%-attenuation scenario, the median-R interval upper bound was below zero in 91.3% at N=24 and 100% at N=48; under the null it was about 1% at both. These are conditional planning scenarios, assume full ratio eligibility, and do not promise R3 HALF coverage.

## Locked scientific design

- 192 fresh balanced-polarity histories; calibration histories do not join this cohort.
- Within each family, training and evaluation include both `high_to_low` and `low_to_high` transitions. `new` and `old` are assigned by the semantic fact transition, not by pole, identity, or row/array order.
- One common SHAM-1.0 history through step 80, then exact paired continuations at 1.0 and 0.5 through step 120. The only branch change is the per-event auxiliary-row multiplier; primary weights, batch composition, active-row denominator, event order, optimizer, schedule, and architecture remain fixed.
- Checkpoints are step 80 (pre-branch), step 100 (descriptive), and step 120 (primary). No other checkpoint evaluation, early stopping, selection, rescue, dose sweep, or feedback.
- The panel is 2,000 fresh neighborhoods: 500 per family, 250 per family × polarity; each has anchor and fact views, giving 4,000 model-visible rows. Four candidate identities remain fixed within each family. Candidate permutation is only a synthetic scorer-equivariance sanity test. No output-slot scientific factor is estimated. Candidate identity remains nested within family/pole; identity attribution is out of scope. No placebo view is added.
- A 24-history high-to-low-only training bridge is selected among the 192 seeds by the frozen hash rank rule before training. It uses the same initialization seed and schedule identity, trains both late branches, and is evaluated on the full balanced panel. Its low-to-high cells are explicitly out of training-polarity distribution. Bridge estimates are secondary paired contrasts, not gates.
- Freshness is checked field-by-field for `world_id`, `root_id`, `episode_id`, `full_rendered_input_hash`, and `selector_input_hash` against training, E1, P-R2, Q-R2, the R3 calibration panel, and already admitted R3 neighborhoods. The E1 neighborhood denylist is separately enforced as an exact hashed identity set. No fuzzy or semantic similarity rule is added.
- Freeze target rows separately from the target-free inference manifest. Seal panel and deterministic LFM feature cache before any head training. Seal every training artifact before one evaluation opening. Produce and seal all raw logits before joining targets or computing treatment metrics.

## Estimands

All score quantities use the frozen head's raw logits. For each candidate (j), preserve ℓ_j - ℓ_old. Equal cell weights are fixed across the four families (exposure, respiratory, salinity, vibration) and two directions.

For each history and direction (d), let (C_d) be the equal-family mean HALF-minus-1× change in anchor ((\ell_{new}-\ell_{old})). Define:

\[
M_C=\tfrac12(C_{H\to L}+C_{L\to H}),\qquad
P_C=\tfrac12(C_{H\to L}-C_{L\to H}).
\]

`M_C` is the role-following coordinate; `P_C` is the low-pole-following coordinate. `M_C` is fixed-sequence step 1; `P_C` is secondary.

For branch (b\), (S_b\) is the equal mean of the eight family × direction means of fact-minus-anchor ((\ell_{new}-\ell_{old})). (D=S_{HALF}-S_{1X}) is signed and reported for every technically completed balanced history. It is universal and fixed-sequence step 2. Direction-specific D values and (M_D/P_D\) are secondary.

\[
R=\log(S_{HALF}/S_{1X})
\]

is reported only when both signed branch separations are positive and at least 0.01. For each of the 192 registered histories report signed S1X, signed SHALF, D, sign reversal, ratio eligibility/reason, and R when eligible. The ratio denominator for coverage is always 192; at least 173 eligible histories are required before a cohort-level conditional-median R claim is estimable. Eligibility never licenses extrapolation to ineligible histories.

`S80` is the role-oriented fact-minus-anchor logit separation at the common fork, before late treatment assignment, with the same equal eight-cell weighting. The confirmatory moderation model is (D_h=\alpha+\beta S80_h+\epsilon_h\), using OLS and a two-sided 95% HC3 interval. β is an association of late response with measured pre-branch state; it is not an attenuation fraction or a controller.

## Confirmatory sequence and interval rules

Use the narrowest symmetric order-statistic/sign-inversion interval with at least 95% binomial coverage for history medians. Use the prevalidated two-sided 95% HC3 interval for β. No method switch after results.

The fixed sequence is:

1. Lower 95% bound for median `M_C` > 0.
2. Upper 95% bound for median `D` < 0.
3. At least 173/192 ratio-eligible histories and upper 95% bound for eligible median `R` < 0.
4. Zero outside the two-sided 95% HC3 interval for β.

Compute and report later quantities even after an earlier failure; they then lose confirmatory status. A permanent technical failure remains in the registered denominator; it is ratio-ineligible and D/C/M/P missing. Report the history by identity. Any affected confirmatory test is `NOT_EVALUABLE`, not a reduced-denominator test. Retry only the identical seed/history under the exact replay rule; never substitute a seed.

For median R, attenuation is supported if the interval's upper endpoint is below zero. Practical equivalence is secondary and requires the complete interval inside `[log(0.9), log(1.1)]`. Report median D with its interval and sign; do not call a D interval containing zero practical equivalence. P_C, bridge contrasts, family/polarity cells, equivalence, and heterogeneity are secondary/descriptive. No population-law claim.

## Bridge, failure, and interpretation locks

The 24 bridge histories are selected by hash rank before any training or S80 measurement. Report paired balanced-minus-high-to-low-only differences in `M_C` and `P_C`, point estimates and intervals only. Because the bridge models see a high-to-low-only training stream, low-to-high evaluation cells are intentionally out of training-polarity distribution; do not read bridge P_C as a pure dose effect.

If technical failure persists after exact same-seed replay, retain the registered row and stop treating the affected confirmatory estimand as evaluable. No seed replacement, hand repair, or post-result imputation.

The analysis does not authorize a dose/controller, family-specific intervention, checkpoint promotion, mechanism claim, or generalization beyond the frozen families/templates and observed histories.

## One-packet execution order

Seal these run, panel, and analysis contracts and the source/test hash bundle together. Then proceed automatically: build and validate the fresh balanced panel; verify exclusions, targets, identity joins, feature repeat, and scorer permutation sanity; seal panel/cache; materialize and hash the 192+24 schedules and bridge seed selection; train all common histories and both late branches; seal checkpoints/telemetry; open the panel once; produce target-free logits for every contracted cell and seal them; only then join targets and run the fixed sequence; independently replay analysis; seal the result and stop. Stop early only for a true invariant failure. No subsequent authorization crumb is needed inside this packet.

## Contract bundle

Machine-readable contracts are `experiments/jev-information-density-v08q-r3-selectivity/contracts/r3-v03-run-contract.json`, `r3-v03-panel-contract.json`, and `r3-v03-analysis-contract.json`. Their status remains `LOCK_CANDIDATE` until implementation and fixture tests are hashed into the final bundle root.
