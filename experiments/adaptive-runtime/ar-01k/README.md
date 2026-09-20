# AR-01K — Matched-Regret Counterfactual Control

Status: completed diagnostic-only experiment.

Scope: engineering-only, toy-scale, no biological correspondence, no general optimizer claim.

## Question

AR-01J showed that G3 can be worse than the full-96 immediate-best program at the first commit and later overtake it. AR-01K asks whether that reversal is special to the action G3 selected or whether similarly bad first moves recover just as well.

At each fixed G3 trajectory snapshot, the experiment builds the same K2 shortlist universe used by the immediate full-96 reference. It selects two deterministic matched controls from that universe:

- same positive/neutral/harmful immediate-utility stratum as G3;
- immediate full-96 regret within `5e-5` of G3's regret;
- G3's own program excluded;
- closest regret first, with a frozen deterministic hash tie-break.

The branches are:

```text
G3-selected first program
full-96 immediate-best first program
matched control A
matched control B
```

After the first commit, every branch receives the identical future G3 stream: proposal batches, verifier draws, pair schedule, action grammar, and K2 continuation policy. Horizons are 1, 2, 4, 8, 16, 32, and 64 commits. Counterfactual measurement never changes the base trajectory.

For a matched control, the primary comparison is:

```text
G3-vs-control Delta_h = full_train_loss(G3 at h)
                       - full_train_loss(control at h)
```

Negative values mean G3 is better. Reversal analysis is restricted to snapshots where the matched control was immediately better than G3, so the comparison starts with G3 genuinely inferior under the measured reference.

## Result

Matching was successful often enough for a useful control: 250 control-A matches and 202 control-B matches across the three seeds. Mean regret gaps were approximately `9e-6` and `1.2e-5`, respectively, against the frozen `5e-5` tolerance.

Among those matched pairs where the control was initially better, G3 later outperformed the control at h=64:

| control | initially-control-better pairs | mean Delta at h=1 | mean Delta at h=64 | G3-better at h=64 |
| --- | ---: | ---: | ---: | ---: |
| A | 94 | +0.0000087 | **-0.0004052** | **60.6%** |
| B | 100 | +0.0000106 | **-0.0004563** | **63.0%** |

The sign change is not a greedy-reference artifact: these are controls with nearly the same immediate regret as G3, receiving the same continuation stream.

Reversal persistence is mixed rather than universal:

| control | persistent reversal | transient reversal | no reversal |
| --- | ---: | ---: | ---: |
| A | 29 | 60 | 5 |
| B | 35 | 55 | 10 |

At h=64, G3/control parameter distances remain substantial, roughly `0.10–0.14` on average depending on seed and control. The branches can therefore remain parameter-distinct while producing a later loss ordering reversal; this is diagnostic only and is not promoted to a functional-convergence claim.

## Hypothesis updates

**AR-H35 — G3 carries trajectory-relevant selection signal beyond immediate full-support utility:** supported in a bounded toy-scale sense. G3 initially loses to tightly matched controls, yet later wins more often than not and has negative mean G3-minus-control loss deltas at h=64 for both controls.

**AR-H36 — Value inversion is primarily generic trajectory slack:** weakened, not eliminated. Matched controls frequently recover and many reversals are transient, so the runtime is operating in a forgiving nonlinear landscape. But generic tolerance alone does not explain why G3 beats matched controls at the observed h=64 rates.

The narrow conclusion is:

> G3's later advantage is not explained solely by its immediate regret. The selected inferior action contains some trajectory-relevant information—or interacts favorably with the particular continuation—but this run does not identify what that information is.

This is not evidence of planning ahead, preserved authority, optionality, or a better future opportunity landscape.

## Integrity and artifacts

- Three fixed AR-01 seeds; 96 snapshots per seed; matched-control availability is reported per snapshot.
- Controls are selected prospectively by immediate full-96 regret and stratum, not by counterfactual outcome.
- Full-96 remains an immediate-utility reference, not a globally optimal trajectory oracle.
- Validation loss and parameter distance are diagnostic only and never influence a branch decision.
- Source tests: 4/4; all-target smoke: passed; benchmark targets: passed; clippy with `-D warnings`: passed; format check: passed.

Artifacts:

- `artifacts/ar-01k-report.json` — complete machine-readable report, classifications, and per-snapshot horizon records.
- `artifacts/ar-01k-runs.csv` — per-seed/control/horizon summary rows.
- `artifacts/ar-01k-snapshots.csv` — raw matched-control and reversal rows.

AR-01K remains diagnostic. No trajectory predictor, multi-step controller, or new optimization policy was added.
