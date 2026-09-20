# AR-01L — Counterfactual Continuation Robustness

Status: completed diagnostic-only experiment.

Scope: engineering-only, toy-scale, no biological correspondence, no general optimizer claim.

## Question

AR-01K found that G3 can later outperform controls with nearly matched immediate full-96 regret. AR-01L asks whether that advantage belongs to the first transition itself or depends on the particular future evidence and pair schedule used after it.

The base snapshots and matched controls are inherited from K. Within each paired continuation, G3 and both matched controls receive exactly the same future stream. Across continuation families, only the future stream changes:

| family | evidence stream | pair schedule | replicates |
| --- | --- | --- | ---: |
| L0 original | original | original | 1 |
| L1 new evidence | changed deterministic seed | original | 2 |
| L2 shifted schedule | original | phase-shifted by 17 or 36 | 2 |
| L3 both changed | changed deterministic seed | phase-shifted by 17 or 36 | 2 |

Horizon values use the same sign as K:

```text
Delta_h = full_train_loss(G3 at h) - full_train_loss(matched control at h)
```

Negative values mean G3 is better. Reversal rates are restricted to matched pairs where the control was initially better than G3.

## Result

The original K effect reproduces exactly in L0. At h=64:

| family | control | mean Delta | G3 win rate | reversal rate among initially inferior G3 cases |
| --- | --- | ---: | ---: | ---: |
| L0 original | A | -0.000235 | 50.8% | 60.6% |
| L0 original | B | -0.000403 | 62.4% | 63.0% |
| L1 new evidence | A | -0.000184 | 50.6% | 56.9% |
| L1 new evidence | B | -0.000087 | 56.2% | 57.0% |
| L2 shifted schedule | A | -0.000057 | 45.4% | 54.3% |
| L2 shifted schedule | B | -0.000082 | 55.9% | 52.5% |
| L3 both changed | A | -0.000010 | 44.8% | 51.6% |
| L3 both changed | B | -0.000156 | 52.2% | 51.5% |

The pattern is therefore mixed:

- New evidence alone preserves a small negative mean Delta for both controls.
- Schedule changes weaken G3's advantage, especially for control A.
- Changing both evidence and schedule nearly removes the mean effect for control A, while control B retains a modest negative mean.
- Reversal rates remain above 50% in the initially-control-better stratum, but many reversals are transient.

## Hypothesis updates

**AR-H35a — Fixed-continuation trajectory signal:** supported. This reproduces K under L0.

**AR-H35b — Continuation-robust trajectory signal:** not supported as a uniform claim. The effect survives some changed streams, but its magnitude and win rate depend on the future schedule/control pairing. The narrowest supported statement is:

> G3's matched-regret advantage is partly portable across future evidence streams, but is not independent of the future continuation structure tested here.

This leaves two live interpretations:

1. G3-selected transitions carry some evidence-geometry information that remains useful under changed evidence.
2. The action interacts with future coordinate revisit order, so schedule compatibility contributes materially.

L does not establish either mechanism. It rules out treating the K effect as fully intrinsic and continuation-independent.

## Integrity and artifacts

- Three fixed AR-01 base seeds; 96 snapshots per seed; K matched controls; 7 continuation streams.
- Each paired comparison shares its future stream exactly; stream changes occur only between continuation families.
- No counterfactual branch affects the base G3 trajectory.
- Full-96 remains an immediate-utility reference, not a trajectory oracle.
- Source library tests: 4/4; formatting and clippy: passed. Full all-target and `D:` validation are recorded with the delivered artifact set.

Artifacts:

- `artifacts/ar-01l-report.json` — full per-seed, family, control, snapshot, and horizon report.
- `artifacts/ar-01l-runs.csv` — family/control/horizon summary rows.
- `artifacts/ar-01l-snapshots.csv` — raw continuation rows with reversal classification and parameter distances.

AR-01L remains diagnostic. No continuation-aware controller or trajectory predictor was added.
