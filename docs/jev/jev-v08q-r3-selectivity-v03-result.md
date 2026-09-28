# JEV v0.8Q-R3: balanced-polarity selectivity result

**Status: result sealed and independently replayed.** R3 is the post-registered successor study, not a retroactive rewrite of Q, R2, or their exploratory analyses.

## Bottom line

Under the frozen late-branch comparison, HALF (0.5× auxiliary weight) produced both a positive role-oriented shift on the anchor view and a reduction in the fixed old-versus-new fact discrimination contrast. The effects are separate coordinates, not a single improvement score:

> **HALF shifted anchor preference toward the designated new candidate while reducing fact-minus-anchor separation.**

The median proportional separation ratio was about **0.72** (roughly a 28% reduction among ratio-eligible histories). The preregistered step-80 moderation slope did not exclude zero. Thus R3 supports an intervention effect on the measured response geometry, but it does **not** provide a usable rule for selecting the intervention from step-80 state.

## Confirmatory fixed sequence

Histories were the analysis unit. Median intervals use the frozen narrowest symmetric exact order-statistic method. Because order-statistic coverage is discrete, the realized nominal coverage is 96.39% for the 192-history intervals and 95.14% for the 188-history `R` interval. The fixed sequence was evaluated in order; the first three steps passed and the fourth did not.

| Step | Estimand and rule | Result | Decision |
|---|---|---:|---|
| 1 | Median `M_C`; lower interval bound > 0 | 0.03651; exact interval [0.02626, 0.05671]; positive in 177/192 histories | **PASS** |
| 2 | Median `D`; upper interval bound < 0 | −0.07270; exact interval [−0.11272, −0.05181]; negative in 177/192 | **PASS** |
| 3 | Median `R`; at least 173/192 eligible and upper interval bound < 0 | 188/192 eligible; median −0.32963; exact interval [−0.35582, −0.29845]; negative in 173/188 eligible histories | **PASS** |
| 4 | `D ~ S80`; zero outside two-sided HC3 interval | β = 0.14940; SE = 0.18595; 95% interval [−0.21740, 0.51620] | **FAIL** |

`FAIL` at step 4 means the interval includes zero; it is not evidence that moderation is exactly absent. The data do not establish that step-80 separation predicts the late HALF-minus-1× effect under this linear model.

At the common step-80 fork, balanced-history separation had median 0.01044 (range 0.00105–0.32806). This is a landmark after the shared SHAM-1× training history, not an initialization measurement.

### What the estimands mean

- `C` is the HALF-minus-1× change in the anchor-view new-versus-old score contrast, in semantic-role coordinates.
- `M_C = (C_high→low + C_low→high)/2` is the role-oriented component tested at step 1.
- `P_C = (C_high→low − C_low→high)/2` is the polarity-direction component, reported as secondary.
- `S` is the fact-minus-anchor new-versus-old score separation; `D = S_HALF − S_1X` is universal across histories.
- `R = log(S_HALF / S_1X)` is reported only when both branch separations exceed the frozen 0.01 floor. Four histories were ineligible; no history was removed from the denominator for `D` or the fixed-sequence cohort.

The `R` interval corresponds to a HALF/1× separation ratio of approximately **0.701–0.742**, with median ratio **0.719**. It lies outside the registered ±10% practical-equivalence region on the negative side. The median 1× endpoint separation was 0.44638, well above the 0.01 floor; the negative `D` result is not a cohort-wide near-zero-baseline artifact.

## Secondary coordinates and heterogeneity

The secondary median `P_C` was +0.00910 (95% interval [0.00216, 0.01999]); it was positive in 114/192 histories. The direction-specific median `C` was positive in both high→low (+0.03261) and low→high (+0.01462) histories. This is compatible with a role-oriented shift and also leaves a smaller direction/pole-associated component to explain. `P_C` was not in the fixed confirmatory sequence, and candidate identity remains nested within pole/family. Do not identify this secondary component as a causal low-pole prior.

Descriptive step-120 rates averaged equally over the 192 balanced histories were:

| Metric | 1× | HALF | Median paired HALF−1× change |
|---|---:|---:|---:|
| Anchor old-target MAP (`A_old`) | 73.77% | 72.60% | −0.13 pp |
| Fact new-target MAP (`F_new`) | 73.63% | 72.45% | −0.33 pp |
| Strict old→new transition | 53.53% | 52.05% | −0.68 pp |

These endpoint rates are descriptive, not substitutes for `M_C`, `D`, or `R`. Their paired distributions are heterogeneous: mean strict-transition change was −1.47 pp, while the median was −0.68 pp. A scalar accuracy summary would conceal the score-separation result.

Family averages also differed. The table pools the two equally represented flip directions and averages family-cell rates over histories; it is descriptive and has no family-specific pass gate.

| Family | 1× `A_old / F_new / Strict` | HALF `A_old / F_new / Strict` |
|---|---:|---:|
| Exposure | 77.3% / 76.7% / 55.2% | 76.4% / 75.8% / 53.7% |
| Respiratory | 80.2% / 80.4% / 62.2% | 76.0% / 76.2% / 56.3% |
| Salinity | 71.7% / 71.7% / 50.2% | 75.2% / 75.3% / 54.9% |
| Vibration | 65.9% / 65.7% / 46.6% | 62.9% / 62.5% / 43.3% |

The opposing family patterns argue against claiming a uniform MAP effect. They are useful follow-up measurements, not grounds for a family-specific training rule.

## Polarity-training bridge (secondary)

The 24 preselected bridge seeds paired balanced-polarity training with high→low-only training, using the same seed/init pairing and the full balanced evaluation panel. These are point estimates and intervals only, with no pass gate. For high→low-only training, low→high evaluation cells are intentionally out of training distribution.

- Balanced minus high→low-only `M_C`: median **+0.02631**, interval [0.00150, 0.08231], mean +0.04645.
- Balanced minus high→low-only `P_C`: median **−0.07881**, interval [−0.17131, 0.04782], mean −0.03877.

The bridge is consistent with training polarity affecting the role/pole decomposition, but it does not isolate pole from fixed candidate identity and is not confirmatory evidence for a mechanism.

## Execution and verification

- Fresh panel: 2,000 neighborhoods, 4,000 evaluation rows, four fixed families, both flip directions balanced.
- Training: 192 balanced histories plus 24 paired bridge histories; 216 histories total, 432 late continuations, checkpoints at steps 80, 100, and 120.
- Evaluation: one recorded panel opening; 1,080 cells × 4,000 rows × 4 candidates = 4.32 million raw-logit rows. Targets were not read until after the raw prediction tree was sealed.
- Independent replay recomputed the analysis without importing the analyzer. Maximum absolute metric difference was **3.30×10⁻⁷**, below the frozen **3×10⁻⁶** tolerance.
- Seal identities: panel `71dc846a…afa05`; feature cache `e1720bf2…a72ac`; training entries `8ebb5d9c…21674`; prediction root `39a6dafb…e8a4f`; analysis root `d1413769…653eb`; final result root `56c5a267…b3992`.

An account-switch interruption was recovered by reusing 132 verified complete histories, rerunning the one partial history from its original seed, and completing the fixed schedule. The frozen evaluator then exposed a field-name mismatch (`evaluation_checkpoint_cells` versus its expected `evaluation_cells`). A versioned adapter supplied the verified count as a read-only in-memory alias; no sealed training artifact or evaluator source was changed, and the first attempt stopped before panel opening. An append-only note corrects a stale `predictions_created` flag in the adapter's completion receipt; the authoritative prediction seal and opening receipt are unchanged. These are execution-provenance repairs, not scientific amendments.

## Research interpretation and next move

R3 rejects the clean scalar-dial story. HALF did not simply “increase gain”: it shifted the anchor-side old/new contrast and reduced the fact-minus-anchor separation, while the step-80 moderator did not yield a supported linear selection rule. The response is multidimensional, and the observed role-oriented shift is not the same thing as improved fact discrimination.

**Do not fit a controller or launch another dose sweep from this result.** The highest-value next experiment is to cross multiple validated candidate realizations within each pole/family while preserving the balanced flip design and the fixed 1× versus 0.5× contrast. Keep `M_C`, `P_C`, `D`, and `R` separate. That would test whether the secondary direction component follows pole, fixed candidate identity, or neither—without asking the step-80 slope to do work it did not do here.

Claim boundary: these results concern the sealed R3 training recipe and fresh neighborhoods from the fixed task families/templates. They do not establish novel-family or novel-template generalization, a universal training law, or a state-conditioned controller.

## Sealed artifacts

- [Analysis summary](<D:/codex-runs/jev-information-density-v08q-r3-selectivity-v03/evaluation-v01/analysis-v01/analysis-summary.json>)
- [Raw prediction seal](<D:/codex-runs/jev-information-density-v08q-r3-selectivity-v03/evaluation-v01/predictions-v01/prediction-seal-v01.json>)
- [All 216 history-level results](<D:/codex-runs/jev-information-density-v08q-r3-selectivity-v03/evaluation-v01/analysis-v01/history-level-results.jsonl>)
- [Trajectory points](<D:/codex-runs/jev-information-density-v08q-r3-selectivity-v03/evaluation-v01/analysis-v01/trajectory-points.jsonl>)
- [Paired bridge contrasts](<D:/codex-runs/jev-information-density-v08q-r3-selectivity-v03/evaluation-v01/analysis-v01/bridge-paired-differences.jsonl>)
- [Independent replay receipt](<D:/codex-runs/jev-information-density-v08q-r3-selectivity-v03/evaluation-v01/analysis-v01/independent-replay-receipt-v01.json>)
- [Final result seal](<D:/codex-runs/jev-information-density-v08q-r3-selectivity-v03/evaluation-v01/analysis-v01/final-result-seal-v01.json>)
- [Training seal](<D:/codex-runs/jev-information-density-v08q-r3-selectivity-v03/training-v01/account-switch-resume-v01/artifacts-v01/training-seal-v01.json>)
- [Execution-adapter receipt correction](<D:/codex-runs/jev-information-density-v08q-r3-selectivity-v03/evaluation-adapter-resumed-training-v02/completion-receipt-correction-v01.json>)
