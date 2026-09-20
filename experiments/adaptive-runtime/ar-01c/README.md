# AR-01C — Adaptation Bandwidth

AR-01C tests whether the AR-00 pairwise runtime receives enough time to act when new stochastic evidence arrives every minibatch.

This is an engineering-only experiment. It makes no biological claim and does not promote any result beyond the tested spiral classifier.

## Protocol

- Same three-class spiral substrate and 2-8-8-3 MLP as AR-01A.
- 123 parameters, 96 training examples, 48 validation examples.
- Fixed action vocabulary: `{0, ±0.02, ±0.01, ±0.005}`.
- K2 pair runtime: deterministic broad pair coverage, top-2 singleton shortlist per coordinate, exact 2×2 compound verification.
- 600 evidence rounds, minibatch size 16.
- The current minibatch is held fixed during the inner sequential commits.
- Only the number of pair commits per evidence round changes: `m ∈ {1, 2, 4, 8}`.
- Three fixed seeds per runtime arm.

The bandwidth arms are:

| Arm | Commits per evidence round |
|---|---:|
| C0 | 1 |
| C1 | 2 |
| C2 | 4 |
| C3 | 8 |

AdamW and sign descent are retained as controls (C4 and C5).

## Results

| Arm | Mean final validation loss | Mean validation accuracy | Exact compound evaluations | Interpretation |
|---|---:|---:|---:|---|
| C0 | 1.079859 | 49.3% | 147,000 | One pair per minibatch |
| C1 | 0.980325 | 48.6% | 294,000 | Two sequential pair commits |
| C2 | 0.809035 | 53.5% | 588,000 | Four sequential pair commits |
| C3 | 0.671504 | 66.7% | 1,176,000 | Eight sequential pair commits |
| C4 | 0.130896 | 98.6% | — | AdamW control |
| C5 | 0.295511 | 92.4% | — | Sign control |

The AR runtime improves monotonically as the number of sequential commits per evidence round increases, but `m=8` still remains below the sign control. The result supports a bandwidth effect without establishing that bandwidth is the only limiting factor.

## Hypothesis update

### AR-H24 — Evidence-to-adaptation bandwidth

**Strongly supported at this scale, but not sufficient for recovery.** One-pair-per-minibatch AR receives new stochastic evidence before it can perform enough local replanning. Increasing sequential commits while holding the minibatch fixed improves the result consistently.

The experiment does not yet distinguish among all possible causes of the remaining gap. Fixed action scale, pair scheduling, minibatch overfitting, and the one-pair program restriction remain live alternatives.

The key engineering distinction is now:

```text
evidence rate      = how often the observed minibatch changes
adaptation rate    = how many verified local programs can be committed
```

Their ratio is a runtime parameter under stochastic training.

## Validation

- Source-tree release tests passed.
- `D:` target release tests passed.
- Source-tree release smoke run and benchmark passed.
- `D:` target release clippy passed with `-D warnings`.

## Artifacts

- `artifacts/ar-01c-report.json`
- `artifacts/ar-01c-runs.csv`
- `artifacts/ar-01c-curves.csv`

