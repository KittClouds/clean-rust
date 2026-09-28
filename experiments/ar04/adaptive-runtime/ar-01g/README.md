# AR-01G — Verification Coverage Geometry

AR-01G separates verifier sample count from verifier composition and coverage.

This is engineering-only, toy-scale work. It makes no biological claim and does not alter the Drosophila science branch.

## Protocol

- Same three-class spiral, 2-8-8-3 MLP, K2 runtime, action grammar, and three seeds as AR-01F.
- Proposal evidence is always a 16-example minibatch.
- Total pair commits are fixed at 4,800.
- Four sequential pair commits share each evidence draw.
- G0/G4 use the full 96-example training set.
- G1 uses one random 64-example verifier.
- G2 uses one class-balanced 64-example verifier.
- G3 uses one class-by-geometry-stratified 64-example verifier.
- G5/G6/G7 aggregate utilities over independent samples totalling 96 observations: `3×32`, `2×48`, and `6×16`.

## Results

Mean across three seeds:

| Verifier construction | Mean validation loss | Mean validation accuracy | Benchmark ms/run |
|---|---:|---:|---:|
| Full 96 | 0.009080 | 100.0% | 14,586.4 |
| Random 64 | 0.213287 | 93.1% | 12,537.0 |
| Class-balanced 64 | 0.145723 | 95.8% | 12,414.1 |
| Geometry-stratified 64 | 0.074789 | 98.6% | 12,496.2 |
| Fixed full 96 parity | 0.009080 | 100.0% | 15,149.9 |
| Aggregate 3×32 | 0.157970 | 95.8% | 15,937.2 |
| Aggregate 2×48 | 0.137755 | 97.9% | 16,129.6 |
| Aggregate 6×16 | 0.140687 | 97.9% | 14,680.1 |

Controls:

| Arm | Mean validation loss | Mean validation accuracy | Benchmark ms/run |
|---|---:|---:|---:|
| G8 AdamW | 0.002017 | 100.0% | 16.4 |
| G9 sign | 0.182181 | 95.1% | 15.9 |

## Hypothesis update

### AR-H29 — Verification coverage matters independently of raw sample count

**Supported at toy scale.** At the same nominal verifier size of 64, random sampling is weakest, class balancing improves the result, and geometry-stratified coverage is substantially better. The stratified 64-example verifier reaches 98.6% mean accuracy and a 0.074789 mean loss, while random 64 reaches 93.1% and 0.213287.

### Aggregation is not equivalent to full support

Three independent 32-example samples, two 48-example samples, and six 16-example samples all total 96 observations and all beat the random 64 control. None matches the full-support verifier's 0.009080 loss. This weakens a pure “more observations reduce variance” explanation and keeps coverage, support, and deterministic consistency live.

### AR-H30 — Utility-estimate uncertainty predicts harmful authorization

**Open.** G compares coverage and aggregation, but does not yet use per-candidate utility variance or signal-to-noise as a controller. No confidence-based authorization policy was introduced.

## Current engineering reading

The verifier requirement is not adequately described by cardinality alone:

```text
proposal shortlist
→ evidence sample
→ representativeness / coverage
→ exact compound consequence on that evidence
→ authorize or reject
```

The next diagnostic should record utility mean and variance across verifier components, then test whether high-variance selected programs carry disproportionate reference regret. That telemetry must remain diagnostic before any confidence-gated commit policy is attempted.

## Validation

- Source release unit tests passed.
- Source release clippy passed with `-D warnings`.
- Source benchmark passed for all ten arms.
- Full G run completed for all ten arms and three seeds.
- Final `D:` target release tests, smoke matrix, doc tests, and clippy are required against this final source state.

## Artifacts

- `artifacts/ar-01g-report.json`
- `artifacts/ar-01g-runs.csv`
- `artifacts/ar-01g-curves.csv`

