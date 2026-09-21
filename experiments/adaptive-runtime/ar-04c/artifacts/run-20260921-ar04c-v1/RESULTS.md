# AR-04C Results

The collection and independent artifact audit are integrity-valid. This report
is descriptive only; AR-04C has no automatic promotion rule.

- crossed cells: 25
- trajectories: 75
- decisions: 315000
- rotating V128 panels: 26250
- mean final measurement loss, training V96: 4.942043199539e+00
- mean final measurement loss, fixed sentinel V128: 3.208658061028e+00
- mean final measurement loss, rotating sentinel V128: 7.680076432228e-01
- fixed minus training: -1.733385138512e+00
- rotating minus training: -4.174035556316e+00

Interpretation must use the full cell contrasts and checkpoint alignment
trajectory in cell-contrasts.csv, ranking-metrics.csv, and
checkpoint-outcomes.csv; no pooled mean alone is a promotion claim.

## Observed arm pattern

The rotating sentinel arm beats the training-objective arm in all 25 crossed
cells and beats the fixed sentinel arm in all 25 cells. The fixed sentinel arm
beats training in 22 of 25 cells. Equal-cell terminal means are:

| arm | final measurement loss | difference vs training |
| --- | ---: | ---: |
| training_full96 | 4.942043199539 | 0 |
| sentinel_fixed128 | 3.208658061028 | -1.733385138512 |
| sentinel_rotating128 | 0.768007643223 | -4.174035556316 |

This is a bounded closed-loop result, not a promotion claim. The rotating arm
also remains near its untouched final-measurement objective at the terminal
checkpoint: mean operational-minus-final loss is about +0.01. In contrast,
fixed reuse drives its operational panel loss to about 0.03 while its final
measurement loss is about 3.21; training drives its training loss to about
0.00 while its final loss is about 4.94. Those gaps are consistent with
objective-specific exposure/overfitting and are the central reuse diagnostic.

The terminal operational-ranking diagnostic does not provide a simple
explanation: mean Spearman alignment with the final-measurement candidate
ranking is approximately -0.15 for fixed, 0.02 for rotating, and -0.08 for
training. Thus the rotating outcome must not be described as “the operational
panel preserved final-action ranking” from this checkpoint telemetry alone.

The collection supports the narrower disposition: independent V128 evidence
can produce a much better terminal held-out trajectory when refreshed every
four-commit evidence round, while reusing one V128 panel produces a strong
panel-specific contamination signature. The effect is bounded to this frozen
synthetic runtime, sample sizes, refresh clock, and 4,200-slot horizon. A
follow-up is required before naming this a general sentinel exposure law or
changing Phoenix.

## Hypothesis disposition

- **AR-H54 — Independent sentinel evidence can remain operationally useful
  under repeated closed-loop use. Supported, bounded.** The rotating V128 arm
  is the strongest result here; it improved terminal final loss in every
  crossed cell, but the mechanism is not isolated from all possible
  distribution-shift or regularization explanations.
- **AR-H55 — Reusing one independent sentinel panel creates adaptive
  generalization contamination under this runtime. Supported, bounded.** Fixed
  reuse made the panel objective improve while the untouched final objective
  deteriorated. This is an exposure/reuse finding, not a universal theorem
  about fixed panels.
- **AR-H56 — Rotating sentinel evidence preserves final-action ranking
  throughout the trajectory. Not supported by the checkpoint ranking
  telemetry.** Rotating produced the favorable learner trajectory without
  terminal rank alignment being strong, so the outcome should not be reduced to
  an action-ranking explanation.
