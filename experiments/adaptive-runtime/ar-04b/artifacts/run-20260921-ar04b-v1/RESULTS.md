# AR-04B — Generalization Objective Bridge

**Disposition:** completed diagnostic only. Sentinel scores did not control
training, proposal generation, action selection, or verifier allocation.

## Result in brief

AR-04B confirms the immediate objective mismatch and shows that independently
sampled sentinel evidence recovers part of the held-out action ranking, with
better alignment as panel size increases. It does not recover the full ranking
even at `n=128`, and it does not establish a sufficient operational panel size.

The full-training utility is nearly unrelated to exact immediate utility on the
independent final-measurement set (`Spearman 0.035`, pairwise agreement `0.513`,
top-1 `4.0%`). Exact independent sentinel panels improve all four primary
metrics monotonically over the tested sizes. At `n=128`, mean Spearman reaches
`0.546`, pairwise agreement `0.709`, top-1 agreement `34.3%`, and
candidate-set regret falls to `2.265e-3` from `7.770e-3` for full-training
utility. This is a material bridge, not a full recovery.

## Primary results

All values below are equal-weight means over the 25 crossed dataset ×
initialization cells. Each cell first averages its three frozen stages; each
sentinel comparison also averages the four independent panel replicates within
state. The untouched final-measurement set is the empirical ranking reference.

| Score source | n | Spearman | Pairwise agreement | Top-1 agreement | Candidate-set regret |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full training exact | 96 | 0.035 | 0.513 | 4.0% | 7.770e-3 |
| Sentinel exact | 8 | 0.159 | 0.558 | 8.3% | 6.216e-3 |
| Sentinel exact | 16 | 0.237 | 0.588 | 13.7% | 5.471e-3 |
| Sentinel exact | 32 | 0.358 | 0.634 | 17.3% | 4.573e-3 |
| Sentinel exact | 64 | 0.460 | 0.674 | 27.3% | 2.986e-3 |
| Sentinel exact | 128 | 0.546 | 0.709 | 34.3% | 2.265e-3 |
| Sentinel Taylor | 8 | 0.158 | 0.558 | 8.3% | 6.203e-3 |
| Sentinel Taylor | 16 | 0.236 | 0.588 | 13.3% | 5.472e-3 |
| Sentinel Taylor | 32 | 0.358 | 0.634 | 17.7% | 4.519e-3 |
| Sentinel Taylor | 64 | 0.459 | 0.674 | 27.7% | 3.001e-3 |
| Sentinel Taylor | 128 | 0.545 | 0.709 | 33.7% | 2.292e-3 |

All five dataset marginals and all five initialization marginals had positive
mean Spearman for every exact sentinel size. Full-training utility was near
zero or mixed across those marginals. These are descriptive crossed summaries;
the four panels and three stages are nested measurements, not independent
replication units.

### Exact versus first-order sentinel scoring

On identical panel examples, Taylor utility closely tracked exact sentinel
utility across all panel sizes. Mean Taylor-vs-exact Spearman ranged from
`0.9941` to `0.9965`; pairwise agreement ranged from `0.9859` to `0.9910`.
At `n=128`, mean action-score RMSE was `8.552e-5` and MAE was `4.689e-5`.
Sentinel-Taylor ranking against the independent final-measurement reference
was also close to sentinel-exact ranking in the table above.

This is evidence of first-order fidelity for this frozen action scale and
substrate. It is not a runtime-cost result: the experiment did not measure the
cost of acquiring per-example gradients or authorize Taylor scores to control
evidence or training.

## Frozen run and audit

- Five fresh training datasets × five fresh initializations; 25 crossed cells.
- Three frozen stages per cell (`600`, `2400`, `4200` commits): 75 states.
- `12,750` candidate programs, generated using training/P16 evidence only.
- Four independent, nested-prefix sentinel panels per dataset at each of
  `n={8,16,32,64,128}`; each panel is disjoint from training and final
  measurement rows.
- `510,000` exact/Taylor sentinel score rows; `3,075` state-level ranking rows.
- Runner source commit: `bb8f85e5257a58d2d55f1af2f1510b6bd406a790`.
- Optimized executable SHA-256:
  `a5cc19f3cfa1961729f61c2712453c92c54a541b1c258c409060a96130c9fb26`.
- Integrity receipt reports 175 unique namespaced seeds, 30 hashed data
  artifacts, and 3,520 globally unique training/sentinel/final-measurement
  sample rows. Maximum difference between aggregate-loss utility and the
  independent per-example recomputation was `2.280e-6`.
- Independent artifact validation passed: all 30 data hashes, all 9 derived
  output hashes, sample disjointness, row cardinalities, and all 3,075
  state-level ranking metrics recomputed from raw score tables. See
  `validation-receipt.json`.

The analysis is measurement-only and conditional on the frozen K2 candidate
set. The final-measurement sets are finite empirical references, not the
population objective. Sentinel panels are nested by size and shared across
initializations/stages within each dataset. The five panel sizes therefore
form a paired evidence curve, not five independent samples. The task/model
family and action grammar are unchanged from AR-04A; no portability claim to
other substrates follows.

## Bounded conclusion

On this synthetic substrate, independent sentinel evidence ranks immediate
held-out action effects better than full-training utility, and larger panels
improve the ranking through the largest tested size. First-order Taylor
scoring nearly reproduces exact sentinel scores on the same panel. The
remaining ranking error at `n=128`, the finite final-measurement reference,
and the absence of a cost or closed-loop test prevent claims of sufficiency or
runtime benefit.

AR-04B establishes no controller, no panel-allocation policy, no estimator
promotion, and no return to AR-03 tuning. Any runtime use requires a separate
frozen experiment.
