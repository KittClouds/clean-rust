# AR-01H — Verification Uncertainty & Authorization Regret

Status: complete, engineering-only, diagnostic-only.

AR-01H audits a fixed AR-01G G3 trajectory. Shadow measurements never affect
the trajectory or authorize commits.

## Frozen protocol

- Three-class spiral: 96 train samples and 48 validation samples.
- K2 runtime: top-2 singleton proposal on each side, then exact 2×2 pair
  verification.
- Proposal evidence: a 16-example minibatch.
- Driving verification: the G3 geometry-stratified 64-example verifier.
- Four sequential pair commits per evidence round; 4,800 total commits.
- 96 snapshots per seed, before commits 0, 50, …, 4,750.
- Seeds: `2b7e151628aed2a6`, `77a19d3c4e280b51`, and `1111222233334444`.
- At each snapshot, shortlisted programs are shadow-evaluated against:
  `6×16`, `3×32`, `2×48` independent random components, and full train-96.

For each family the audit records sign reliability against full-96 utility,
selected-program SNR and standard deviation, positive-utility probability,
reference regret, within-block winner stability, and cross-block opportunity
ordering. The reference regret is relative to the best full-96-valued program
among the audited K2 shortlist candidates at that snapshot.

## Results

The fixed G3 trajectories ended at:

| Seed | Train loss | Validation loss | Train accuracy | Validation accuracy |
| --- | ---: | ---: | ---: | ---: |
| `2b7e…d2a6` | 0.034296 | 0.046837 | 100.0% | 100.0% |
| `77a1…0b51` | 0.054499 | 0.065881 | 100.0% | 100.0% |
| `1111…4444` | 0.090376 | 0.111649 | 97.9% | 95.8% |

Across seeds, mean diagnostic measures were:

| Family | Sign reliability | Mean regret | Stddev/regret correlation | Family block ordering | Component block ordering |
| --- | ---: | ---: | ---: | ---: | ---: |
| 6×16 | 61.1% | 0.000595 | 0.11 | 30.2% | 13.7% |
| 3×32 | 64.9% | 0.000595 | 0.11 | 25.0% | 16.9% |
| 2×48 | 68.0% | 0.000595 | 0.12 | 26.7% | 20.0% |
| full-96 | 100.0% | 0.000595 | 0.00 | 100.0% | 100.0% |

The driving G3 selection matched the full-96 best block only 14.6–27.1% of
the audited snapshots, depending on seed. That is a shadow comparison, not a
claim that G3's training trajectory failed: two seeds reached 100% validation
accuracy and the third remained near the task boundary.

## Interpretation

H30 is **not supported** on AR-01H. The selected-program standard deviation had
weak correlation with full-reference regret across all three independent
families: per-seed correlations ranged from `-0.025` to `0.245`, with no stable
family-specific signal. The full-96 family has one deterministic component, so
its uncertainty correlation is structurally zero.

The stronger surviving result is narrower:

> Small independent verifier families often disagree with full-support
> opportunity ordering; increasing evidence can improve ordering stability, but
> the tested SNR/stddev signal is not yet a reliable per-transition abstention
> rule.

This keeps the next design question open: uncertainty may still be useful as a
diagnostic or as one input to an adaptive evidence policy, but it must first be
tested with a prospective controller and controls for update-frequency effects.

## Validation

- Source release unit tests: passed, 4/4.
- Source release clippy with `-D warnings`: passed.
- `D:` release unit tests: passed, 4/4.
- `D:` release smoke matrix: passed, 1/1 test covering all G arms.
- `D:` release clippy with `-D warnings`: passed.
- Source full three-seed diagnostic run: passed.
- `D:` release diagnostic binary reproduced the corrected three-seed result.
- Report JSON parsed successfully after generation.
- Scope firewall: no Drosophila or AR-00/AR-01G source files were changed.

Artifacts:

- `artifacts/ar-01h-report.json` — complete per-seed/per-family summary.
- `artifacts/ar-01h-runs.csv` — one row per seed and verifier family.

All conclusions remain engineering-only, toy-scale, and carry no biological or
general-optimizer claim.
