# AR-01B — Verification Evidence Matrix

AR-01B keeps the AR-01A spiral, model, action grammar, pair schedule, and 3,000-step horizon fixed. It changes only the evidence source used for proposal and verification.

## Result

| Arm | Proposal evidence | Verification evidence | Mean validation loss | Mean validation accuracy | Exact failure regret: shortlist / verification / scheduler |
| --- | --- | --- | ---: | ---: | ---: |
| B0 | minibatch | minibatch | 0.639044 | 63.2% | 0.09790 / 0.13509 / 0.02135 |
| B1 | minibatch | full train | 0.035079 | 100.0% | 0.01036 / 0.00148 / 0.00887 |
| B2 | full train | minibatch | 0.272401 | 92.4% | 0.00078 / 0.04545 / 0.04697 |
| B3 | full train | full train | 0.042160 | 100.0% | 0.00042 / 0.00039 / 0.00003 |
| B4 | AdamW control | — | 0.003731 | 100.0% | — |
| B5 | sign control | — | 0.336934 | 95.1% | — |

The decisive asymmetry is verification. Full-set verification rescues noisy minibatch proposals in B1. Full-set proposals with minibatch verification remain substantially worse in B2. B3 confirms that the full-evidence runtime can optimize this substrate; the failure in B0 is not simply caused by pairwise planning or action interposition.

Event counts are not sufficient: B1 has more scheduler-misorder events than B0 but much lower regret. The regret-weighted taxonomy is therefore the authoritative comparison.

## Cost

Single-seed benchmark times per 3,000-step run were approximately: B0 5.05 s, B1 10.16 s, B2 20.42 s, B3 24.30 s, versus B4 AdamW 12 ms and B5 sign 12 ms. The full-evidence diagnostic is not a practical runtime design; it is an oracle control.

## Hypothesis update

AR-H19 is not supported for minibatch/minibatch verification. AR-H20 is strongly supported in this configuration: separating proposal and verification evidence is beneficial, and the verification evidence must be substantially less noisy. AR-H24 remains open for the next experiment; B3 shows that bandwidth cannot be inferred from the B0 failure alone.

Artifacts are under `artifacts/`: `ar-01b-report.json`, `ar-01b-runs.csv`, and `ar-01b-curves.csv`. The result is engineering-only, toy-scale, and carries no biological correspondence or general optimizer claim.
