# AR-01D — Verification Evidence × Adaptation Bandwidth

AR-01D crosses the reliability of transition-verification evidence with the number of sequential pair programs committed before new evidence is sampled.

This is engineering-only, toy-scale work. It makes no biological claim and does not alter the Drosophila science branch.

## Frozen protocol

- Same three-class spiral, 2-8-8-3 MLP, action grammar, seeds, and K2 pair runtime as AR-01A/C.
- 123 parameters, 96 training examples, 48 validation examples.
- Proposal evidence is always the current minibatch for every AR arm.
- Verification evidence is crossed with `m ∈ {1, 2, 4, 8}` sequential commits per evidence round.
- Same-batch verification uses the proposal minibatch.
- Independent verification uses a separately sampled, held-fixed minibatch from the same training set.
- Full verification uses all 96 training examples.
- 600 evidence rounds, minibatch size 16, three fixed seeds.
- AdamW and sign descent are retained as controls.

| Evidence | m=1 | m=2 | m=4 | m=8 |
|---|---:|---:|---:|---:|
| Same minibatch | D0 | D1 | D2 | D3 |
| Independent minibatch | D4 | D5 | D6 | D7 |
| Full training set | D8 | D9 | D10 | D11 |

## Results

Mean across three seeds:

| Evidence | m=1 loss / acc | m=2 loss / acc | m=4 loss / acc | m=8 loss / acc |
|---|---:|---:|---:|---:|
| Same minibatch | 1.079859 / 49.3% | 0.980325 / 48.6% | 0.809035 / 53.5% | 0.671504 / 66.7% |
| Independent minibatch | 0.990721 / 48.6% | 0.883062 / 49.3% | 0.717071 / 56.9% | 0.363361 / 93.1% |
| Full training set | 0.754076 / 56.3% | 0.447605 / 84.0% | 0.092710 / 100.0% | 0.016529 / 100.0% |

Controls:

| Arm | Mean validation loss | Mean validation accuracy |
|---|---:|---:|
| D12 AdamW | 0.130896 | 98.6% |
| D13 sign | 0.295511 | 92.4% |

The interaction is clear:

- Same-batch verification remains weak even when bandwidth rises to `m=8`.
- Independent verification improves substantially with bandwidth and reaches 93.1% at `m=8`.
- Full-train verification reaches 100% by `m=4` and achieves a 0.016529 mean loss at `m=8`.

Thus useful adaptation bandwidth is gated by verification reliability. More commits do not rescue a verifier that is certifying minibatch-specific accidents.

## Hypothesis updates

### AR-H25 — Verification reliability gates adaptation authority

**Strongly supported at this scale.** Increasing commit bandwidth is most useful when verification evidence is sufficiently representative. The full-training verifier benefits sharply from `m=1 → 4`; the same-batch verifier improves only partially.

### AR-H26 — Proposal and commitment evidence have asymmetric reliability requirements

**Strongly supported.** The proposal remains the current minibatch in every AR arm. Full verification therefore demonstrates that noisy proposal evidence can still nominate a useful path, provided final transition valuation uses stronger evidence.

### AR-H21 — Noisy shortlisting is not the primary failure

**Supported in the bounded sense established by AR-01B.** The noisy proposal is imperfect, but reliable verification plus sufficient bandwidth recovers the task. Proposal misses remain telemetry, not the main explanation for collapse.

### AR-H24 — Evidence-to-adaptation bandwidth

**Supported, conditional on verification quality.** Loss improves monotonically with `m` in all three evidence regimes, but the benefit is gated by evidence reliability. This is not an independent additive knob in the tested range.

The current runtime has two budgets:

```text
B_V = verification evidence budget
B_A = adaptation bandwidth before new evidence
```

The measured control law is presently qualitative: higher `B_A` is valuable only when `B_V` is adequate.

## Audit and cost

The regret-weighted audit is retained. Across the matrix, full verification has near-zero verification-noise regret while same- and independent-minibatch verification show materially larger reference regret. Event counts alone are not treated as effect size.

Mean source-tree benchmark time per one-seed run of one arm:

| Arm family | m=1 | m=2 | m=4 | m=8 |
|---|---:|---:|---:|---:|
| Same minibatch | 1080.7 ms | 1861.4 ms | 3784.1 ms | 7154.3 ms |
| Independent minibatch | 1178.2 ms | 2006.5 ms | 3658.2 ms | 7215.1 ms |
| Full training set | 2252.3 ms | 4169.4 ms | 7721.5 ms | 14898.6 ms |

Controls: AdamW 2.28 ms; sign 2.13 ms.

## Validation

- Source release tests passed.
- Source release smoke matrix passed for all 14 arms.
- Source release clippy passed with `-D warnings`.
- Source benchmark passed for all 14 arms.
- Final `D:` target release tests, 14-arm smoke matrix, doc tests, and clippy passed against this final source state.

## Artifacts

- `artifacts/ar-01d-report.json`
- `artifacts/ar-01d-runs.csv`
- `artifacts/ar-01d-curves.csv`
