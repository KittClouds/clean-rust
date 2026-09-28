# AR-01F — Independent Verification Evidence Frontier

AR-01F measures how much independent evidence the K2 runtime needs before its verified pair decisions become reliable enough for stochastic training.

This is engineering-only, toy-scale work. It makes no biological claim and does not alter the Drosophila science branch.

## Protocol

- Same three-class spiral, 2-8-8-3 MLP, action grammar, and three seeds as AR-01D/E.
- Proposal evidence is always a 16-example minibatch.
- K2 is fixed at two singleton candidates per coordinate and exact 2×2 compound verification.
- Eight sequential pair commits occur per verification sample.
- Total pair commits are fixed at 4,800.
- Independent verification sample sizes are `16, 24, 32, 48, 64, 96`.
- The 96-example arm is the full training set.
- AdamW and sign descent use the same 4,800-update budget as controls.

## Results

Mean across three seeds:

| Verification examples | Mean validation loss | Mean validation accuracy | Benchmark ms/run |
|---:|---:|---:|---:|
| 16 | 0.380030 | 86.8% | 7,688.1 |
| 24 | 0.240706 | 94.4% | 8,324.2 |
| 32 | 0.195755 | 95.2% | 9,051.7 |
| 48 | 0.193754 | 96.5% | 10,422.2 |
| 64 | 0.142638 | 97.9% | 11,754.4 |
| 96 | 0.005452 | 100.0% | 13,662.8 |

Controls:

| Arm | Mean validation loss | Mean validation accuracy | Benchmark ms/run |
|---|---:|---:|---:|
| F6 AdamW | 0.002017 | 100.0% | 16.6 |
| F7 sign | 0.182181 | 95.1% | 16.3 |

## Hypothesis update

### AR-H28 — A sub-full independent verification sample can be sufficient

**Supported in a bounded engineering sense.** A 64-example independent verifier beats the sign control on both validation loss and accuracy, and 24–48 examples already provide a substantial improvement over the 16-example verifier.

However, the low-loss regime associated with broad/full evidence appears only at 96 examples in this run. Accuracy saturates earlier than optimization quality, so accuracy alone is not an adequate evidence-reliability metric.

The current frontier is:

```text
16 examples  → usable but noisy
24–48        → materially better, still loss-limited
64           → stronger than sign control
96           → full low-loss regime
```

The evidence budget is therefore a real continuous cost knob, not merely a full-dataset versus minibatch switch.

## Current engineering reading

The best-supported runtime decomposition is now:

```text
16-example proposal minibatch
        ↓
top-2 singleton shortlist
        ↓
independent verifier with an evidence budget
        ↓
exact local pair consequence
        ↓
commit/replan
```

AR-01E did not establish an independent benefit from holding evidence fixed across multiple commits once total commits were equalized. AR-01F establishes that the amount of independent verification evidence materially changes the quality of the resulting opportunity value.

## Validation

- Source release unit tests passed.
- Source release clippy passed with `-D warnings`.
- Source benchmark passed for all eight arms.
- The full frontier run completed for all eight arms and three seeds.
- Final `D:` target release tests, eight-arm smoke matrix, doc tests, and clippy passed against this final source state.

## Artifacts

- `artifacts/ar-01f-report.json`
- `artifacts/ar-01f-runs.csv`
- `artifacts/ar-01f-curves.csv`
