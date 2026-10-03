# JEV v0.8Q-R2-X1: Competitor anatomy of the sealed response

**Status:** post-hoc exploratory analysis of sealed predictions. This report does not revise the registered Q-R2 result.

## Question and boundary

Q-R2 showed a nearly uniform increase in the fact-view multiclass winner gap under the late half-weight branch, despite little or negative change in the registered fact-induced new-candidate probability movement for most seeds. X1 decomposes that gap change into candidate probability redistribution and competitor identity changes.

This is a read-only calculation over the sealed step-120 prediction matrix. It uses candidate IDs and prediction probabilities only; it does not use held-out targets, head checkpoints, training telemetry, or metrics. It performs no inference and does not reopen the panel. Neighborhood summaries are averaged within each of the 24 paired histories before seed-level summaries are reported.

The two quantities below are deliberately distinct:

- **Fact-view HALF−1X probability change:** the difference between branches on fact-view `p(new)` alone.
- **Fact-specific movement effect:** the difference-in-differences `(HALF_fact − HALF_anchor) − (1X_fact − 1X_anchor)`, which is the registered treatment contrast for fact-induced new-candidate probability movement.

Confusing these would make a broad redistribution look like target-specific response.

## Main decomposition: fact-flip view

Across 48,000 paired neighborhoods (2,000 per seed), the HALF−1X winner-gap change was:

| Fact-view quantity | Mean across 24 seed means | Median seed | Positive / negative seeds |
|---|---:|---:|---:|
| Intended new-candidate probability, `Δp_new` | +0.022523 | +0.018219 | 23 / 1 |
| Old-candidate probability, `Δp_old` | −0.009774 | −0.011099 | 4 / 20 |
| Combined probability of the other two candidates | −0.012750 | −0.007217 | 4 / 20 |
| Strongest non-new competitor probability | −0.014007 | −0.013807 | 1 / 23 |
| New candidate minus strongest non-new competitor gap | **+0.036530** | +0.032836 | **23 / 1** |

The pointwise identity is `Δgap = Δp_new − Δp_strongest_competitor`; the calculation verified it for every paired neighborhood. At the cohort-mean level, about 62% of the gap widening is the intended candidate's fact-view probability increase and about 38% is a decrease in the strongest non-new competitor's probability. This is arithmetic gap accounting, not a causal/mechanistic decomposition. The strongest competitor can differ between branches.

HALF raised `p(new)` on the anchor view too: +0.020242 on average (positive in 21/24 seeds). Thus most of the +0.022523 fact-view increase was also present without the fact flip. The registered fact-specific movement contrast is only:

| Difference-in-differences coordinate | Mean | Median seed | Positive / negative seeds | Range |
|---|---:|---:|---:|---:|
| `p(new)` | +0.002281 | −0.000756 | 4 / 20 | [−0.009777, +0.081056] |
| `p(old)` | +0.002367 | +0.001919 | 21 / 3 | [−0.011043, +0.020793] |
| Other-candidate mass | −0.004648 | −0.000550 | 6 / 18 | [−0.101849, +0.006244] |

These three coordinates sum to zero, up to floating-point tolerance. The treatment's new-versus-old probability shift is also almost the same on anchors and fact views: +0.032297 on fact views versus +0.032383 on anchors, a difference-in-differences of −0.000086. In other words, the large positive fact-view winner-gap contrast is not evidence of a comparable increase in fact-specific target movement.

## Probability mass and competitor identity

Mean probability mass on the fact view:

| Branch | New | Old | Other two candidates |
|---|---:|---:|---:|
| Late SHAM 1.0× | 0.272101 | 0.284586 | 0.443313 |
| Late SHAM 0.5× | 0.294624 | 0.274813 | 0.430563 |

The probability mass moves toward `new` and away from both `old` and the residual pair. Yet this does not mean the intended candidate becomes the winner. The registered MAP and strict-transition outcomes remain the authority for actual crossings; a positive numeric gap shift is not interchangeable with a crossing or with fact-specific response.

The strongest non-new competitor changed identity in 7,152/48,000 fact-view pairs (14.9%). In 5,569 pairs (11.6%), the strongest competitor switched between `old` and one of the other candidates. The strongest identity within the residual two-candidate set changed in 7,944/48,000 pairs (16.6%). The 14.9% mean switch rate is highly seed-concentrated: the median seed rate is 0.075%, the range is 0–84.8%, and 13/24 seeds have any switch. It should not be described as a typical per-seed switch rate.

## Family means: fact-view decomposition

| Family | `Δp_new` | `Δp_strongest competitor` | `Δ winner gap` |
|---|---:|---:|---:|
| Exposure | +0.019885 | −0.013328 | +0.033212 |
| Respiratory | +0.013979 | −0.010057 | +0.024036 |
| Salinity | +0.026312 | −0.011713 | +0.038025 |
| Vibration | +0.029917 | −0.020930 | +0.050847 |

These are descriptive family-stratified means over the same 24 histories, not family-specific treatment rules or independent replications.

## Interpretation

The narrow supported statement is:

> **At step 120, the late half-weight branch widened the fact-view new-candidate-versus-strongest-competitor gap in 23/24 paired histories. That widening combined a fact-view increase in `p(new)` with lower probability on the strongest non-new competitor. However, the new-candidate probability increase was almost as large on anchors, so the registered fact-specific `p(new)` movement changed by only +0.002281 on average and was negative in 20/24 histories.**

This is consistent with a broad output redistribution that improves relative competitive standing more uniformly than it increases fact-specific target response. Competitor identity switches show that “competitor suppression” is not always suppression of one fixed candidate. The analysis does not identify a mechanism, prove a universal effect, or establish a useful controller.

It reinforces the measurement distinction:

`target probability ≠ relative winner gap ≠ MAP crossing ≠ locality ≠ preservation/calibration`.

## Reproducibility and provenance

- Raw input: `raw-predictions-v01.jsonl`, SHA-256 `39c3fd8fccbf0a53897ae780b2ddff0bbbf25df2016230d428ed8dea49c11f2c`.
- Q-R2 completion seal: SHA-256 `5e5fd8a6b5d8255c57a480b9da4334307cf195bb07cf9cc6c0b200242f8abac4`.
- X1 output-root SHA-256: `add172480012f9a441806ad76186e312ea3aac031381877ff72dd79f181faf16`.
- Output seal: `D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\evaluation-v03\competitor-anatomy-x1\competitor-anatomy-x1-seal-v01.json`.
- The output seal's three file hashes and root hash were independently rechecked after generation; all matched.
- The exploratory implementation follows the frozen candidate-order tie convention. Synthetic tie and anchor/fact decomposition fixtures passed before the final data pass.
- No Q-R2 registered artifact, prediction, metric, checkpoint, or panel was modified.
