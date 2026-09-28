# AR-01E — Equal-Total-Commit Evidence Cadence

AR-01E tests whether the apparent adaptation-bandwidth effect from AR-01C/D survives when every arm receives the same total number of pair commits.

This is engineering-only, toy-scale work. It makes no biological claim and does not alter the Drosophila science branch.

## Protocol

- Same spiral dataset, 2-8-8-3 MLP, K2 pair runtime, action grammar, and three seeds as AR-01D.
- Proposal evidence is always a 16-example minibatch.
- Total pair commits are fixed at `4,800` for every AR arm.
- Evidence refresh cadence is crossed with `m ∈ {1, 2, 4, 8}` sequential commits per evidence sample.
- The pair-coverage schedule advances once per committed program, so all runtime arms receive the same total pair-planning opportunities.
- Same-batch, independent-batch, and full-training-set verification are retained.
- AdamW and sign descent run for the same 4,800 update budget as controls.

## Results

Mean across three seeds:

| Verification | m=1 loss / acc | m=2 loss / acc | m=4 loss / acc | m=8 loss / acc |
|---|---:|---:|---:|---:|
| Same minibatch | 0.713694 / 59.7% | 0.680346 / 61.8% | 0.690072 / 64.6% | 0.701119 / 61.1% |
| Independent minibatch | 0.477790 / 77.1% | 0.416751 / 81.3% | 0.376185 / 88.2% | 0.380030 / 86.8% |
| Full training set | 0.009609 / 100.0% | 0.010048 / 100.0% | 0.009080 / 100.0% | 0.005452 / 100.0% |

Controls:

| Arm | Mean validation loss | Mean validation accuracy |
|---|---:|---:|
| E12 AdamW | 0.002017 | 100.0% |
| E13 sign | 0.182181 | 95.1% |

All AR arms performed exactly `1,176,000` compound evaluations and `4,132,800` singleton proposal evaluations. The large monotonic bandwidth effect in AR-01D did not reproduce after total commits were equalized.

## Hypothesis update

### AR-H27 — Evidence refresh cadence has an effect independent of total commit count

**Not supported in this protocol.** At equal total pair commits, full verification was already saturated at every cadence. Independent verification improved from `m=1` through `m=4`, but `m=8` did not improve further. Same-batch verification remained weak with no reliable cadence trend.

The stronger interpretation of AR-H24 is therefore narrowed:

> The AR-01D bandwidth curve was substantially driven by the amount of local optimization work available before the fixed 600-round horizon. Any independent benefit from holding evidence fixed across multiple commits is small or unresolved here.

This does not invalidate the evidence-quality interaction. It shows that total adaptation work and evidence-refresh cadence must be reported separately.

## Current engineering reading

The most robust result remains:

```text
noisy proposal
→ stronger verification evidence
→ verified pair program
→ commit/replan
```

AR-01E does not justify a controller that grants extra commits merely because evidence is held fixed. The next clean variable is the amount of independent verification evidence used for each fixed K2 decision.

## Validation

- Source release unit tests passed.
- Source release clippy passed with `-D warnings`.
- The full factorial run completed for all 14 arms and three seeds.
- Source artifacts were generated under `artifacts/`.
- `D:` target release unit tests and clippy passed; the 14-arm smoke matrix passed before the final lint-only cleanup.

## Artifacts

- `artifacts/ar-01e-report.json`
- `artifacts/ar-01e-runs.csv`
- `artifacts/ar-01e-curves.csv`
