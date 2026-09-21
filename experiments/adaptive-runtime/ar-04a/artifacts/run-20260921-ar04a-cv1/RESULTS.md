# AR-04A — Continuation-Conditioned Action Value

**Disposition:** completed diagnostic. No measured quantity controlled training,
proposal generation, verification allocation, or action selection.

## Result in brief

The future counterfactual is reproducibly measurable under common frozen paths,
but this run does **not** show a general horizon-induced collapse of immediate
action ranking. The answer depends strongly on which immediate objective is
compared with the held-out future objective:

- Full-training immediate utility is nearly unrelated to held-out future action
  effect already at `H=0`, and stays near chance through `H=128`.
- Immediate action effect measured on the same held-out objective is almost
  perfectly ranked at `H=0` and remains strongly aligned with mean future effect
  at `H=128` (mean state Spearman `0.969`, pairwise agreement `0.942`, and mean
  candidate-set regret `8.79e-5`). Its top-1 agreement declines from `100%` at
  `H=0` to `80.3%` at `H=128`.

Thus the dominant rank mismatch is **training-objective versus held-out-objective
mismatch**, not a demonstrated failure of same-objective immediate utility as
the continuation horizon grows. The mean action effect is small relative to
its continuation-to-continuation variability, so mean value and continuation
sensitivity remain distinct measurements.

## Frozen run and support

- Source branch: `codex/ar-04a-continuation-conditioned-action-value-20260921`.
- Frozen source commit: `642b4261227c08d1cc1a1da1dfb154097e1c81d8`.
- Release executable SHA-256:
  `7ca376c3a474769ae71c978254daccef41c31419cde9c1492f88ee5b4e244d03`.
- Five fresh training datasets × five fresh initializations; 75 snapshots at
  steps 600, 2,400, and 4,200; 170 frozen candidate programs per state.
- Eight common frozen continuations per state, with horizons `0, 8, 32, 128`.
- 547/600 state-continuation paths were valid; 53 were censored because at
  least one candidate replay crossed a parameter bound. No baseline path had
  a bound event. Nine states had fewer than six valid paths and were excluded
  from primary state summaries (two at step 2,400; seven at step 4,200).
- Primary ranking summaries therefore use 66 supported states. The 25 crossed
  dataset × initialization cells are the replication units; actions,
  continuations, and checkpoints are nested measurements.

Every candidate and no-op branch received the same frozen additive update
sequence for a given state and continuation. Branch-specific replanning was
disabled. Held-out data was measurement-only. No replacement paths were drawn
for censored cases.

## Immediate-versus-future ranking

The primary target is mean paired
`DeltaQ_H = heldout_loss(no-op path) - heldout_loss(candidate path)` across
valid common continuations. Positive is beneficial. The table gives equal-state
means over the 66 supported states; regret is relative to the best candidate
in the frozen action set.

| H | Immediate score | Spearman | Top-1 | Pairwise | Candidate-set regret |
|---:|---|---:|---:|---:|---:|
| 0 | Full-training utility | 0.042 | 3.0% | 0.516 | 6.37e-3 |
| 8 | Full-training utility | 0.035 | 4.5% | 0.513 | 6.44e-3 |
| 32 | Full-training utility | 0.019 | 4.5% | 0.508 | 6.59e-3 |
| 128 | Full-training utility | -0.003 | 3.0% | 0.500 | 6.95e-3 |
| 0 | Held-out immediate effect | 1.000 | 100.0% | 1.000 | 0 |
| 8 | Held-out immediate effect | 0.997 | 92.4% | 0.984 | 1.05e-5 |
| 32 | Held-out immediate effect | 0.990 | 84.8% | 0.967 | 3.27e-5 |
| 128 | Held-out immediate effect | 0.969 | 80.3% | 0.942 | 8.79e-5 |

The held-out immediate score is the same measurement objective as the future
target, so its `H=0` agreement is an identity check rather than independent
evidence. More informative is that its ranking remains strong through `H=128`:
the held-out-immediate mean Spearman is positive in all 25 crossed cells at
each tested horizon (the `H=0` result is definitional). Conversely, the
full-training score is weak at `H=0` already. Its near-chance ranking at later
horizons therefore cannot be attributed specifically to future path
interaction.

## Mean future effect and continuation sensitivity

| H | Mean per-action `DeltaQ_H` (state-action summaries equally weighted) | Mean per-action SD across continuations | P90 per-action SD |
|---:|---:|---:|---:|
| 0 | -4.79e-5 | 0 | 0 |
| 8 | -4.71e-5 | 1.29e-4 | 3.10e-4 |
| 32 | -4.66e-5 | 1.91e-4 | 4.47e-4 |
| 128 | -5.34e-5 | 2.66e-4 | 5.97e-4 |

The mean is slightly negative at every horizon: over this frozen candidate set,
candidate branches were on average marginally worse than their paired no-op
continuations. Meanwhile, the no-op continuation's mean held-out loss change
from the frozen state was `+1.47e-3` at 8 commits, `+5.23e-3` at 32, and
`+2.34e-2` at 128. These are descriptive averages over nested paths/actions,
not independent-sample uncertainty estimates.

At `H=128`, actions in the second and third equal-count quartiles of
full-training immediate utility had mean within-state immediate-utility widths
of `1.25e-4` and `1.26e-4`, while the within-state SD across their mean future
effects was `1.55e-3` and `1.36e-3`. Their mean within-state future-effect
ranges were `8.62e-3` and `7.74e-3`. Thus similar full-training immediate
utilities can accompany materially different held-out future effects in this
candidate set. This comparison does not control for held-out immediate utility;
it should be read alongside the objective-matched ranking above.

## Existing-geometry sidecars

Diagnostic-only within-state correlations show that held-out immediate effect
and held-out first-order Taylor utility track mean future effect strongly
through `H=128` (mean Spearman about `0.969` at that horizon), whereas their
full-training counterparts do not. The projected-stratum within-utility
variance descriptor has little association with mean future effect, but its
association with continuation SD is about `0.82` for `H=8, 32, 128`. This
descriptor is computed from full-training candidate consequences; it is not a
candidate-independent feature and is not a validated estimator. No predictor,
threshold, or composite score was fit.

## Interpretation and limits

AR-04A demonstrates that no-op-relative counterfactual value and its
continuation sensitivity can be measured with exact common support and
identity checks on this substrate. It does **not** establish that a separate
long-horizon value estimator is needed: the objective-matched immediate
held-out score largely preserves the future action ranking to 128 commits.
The poor ranking of training utility against held-out future value is already
present at horizon zero, identifying an objective/generalization gap rather
than a horizon-specific effect.

This is a forced-continuation diagnostic on one synthetic task/model family,
one hash-control continuation policy, and a K2 shortlist-derived candidate
universe. It does not evaluate branch-specific replanning, terminal training
benefit, other tasks/architectures, or an operational held-out verifier. The
bounds-censored and under-supported states limit late-stage coverage. No result
authorizes a controller, new verifier, training change, AR-03 repair, CF-01
change, or promotion into Phoenix.

## Independent validation

The read-only audit passed: all six required JSON reports parsed; all five
dataset binary hashes matched; all 715 seed values were unique across roles;
all 371,960 action-continuation-horizon rows were unique and supported by a
valid path; common no-op fingerprints/losses matched across actions; the
maximum `H=0` held-out-effect discrepancy was `1.33e-6`; and the exact
`Q_H - DeltaQ_H = J(W) - J(W_H^noop)` identity error was at most `9.53e-13`.
See `validation-receipt.json` and `integrity-receipt.json`.

One nonblocking schema defect was found during audit: the field named
`mean_absolute_q_over_action_rows` in `action-effect-vs-noop.json` is the
**signed arithmetic mean** of `Q_H`, not the mean absolute value. The frozen
collector is not being edited or rerun; this mislabeled field is not used in
the conclusions above. The raw `action-continuation.csv` values remain
available for independent recomputation.
