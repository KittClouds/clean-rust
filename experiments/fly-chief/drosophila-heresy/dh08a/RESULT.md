# DH-08A Result

Status: `COMPLETE_VERIFIED_INCONCLUSIVE`

Frozen run: `artifacts/runs/20260916T054825Z`

Seal SHA-256: `a21f2e19688181955d5d01180e218a6b66f19f0d560305919aa21c6f579d3a13`

## Confirmatory result

The seed-bundle mean event-local old-map contrast was:

`M_true - M_Q07-matched-null = +3.88707743319e-06`

- paired t 95% interval: `[-1.04310768247e-07, +7.87846563463e-06]`
- deterministic seed bootstrap 95% interval: `[+2.71169155018e-07, +7.80276022402e-06]`
- positive seed means: `18 / 32`

The intervals disagree under the frozen decision rule, so event-local endpoint sensitivity is unresolved.
The cumulative DH-07R direction effect cannot be attributed to a uniform immediate readout change.

## Descriptive shape

Both endpoints immediately reduced old-map expression relative to the common base:

- endogenous true endpoint: `-1.83423200444e-05`
- matched null endpoint: `-2.22293974776e-05`

The null endpoint was therefore slightly more suppressive on average, matching the cumulative DH-07R
sign, but the difference was small and heterogeneous:

- tau 4: `-1.95215640062e-06`, t95 includes zero
- tau 16: `+9.72631126700e-06`, t95 wholly positive

Exploratory tau-by-window summaries place the tau-16 positive effect mainly after reversal trial 64.
This interaction was not the confirmatory primary and must not be promoted without fresh-seed testing.

## Integrity and scope

- 32 fresh computational seed bundles; one synthetic specimen.
- 128 bundles, 256 cells, and 32,768 ordered E-arm events validated.
- All Q07 committed-geometry gates passed.
- All 128 final true endpoint hashes matched final canonical weight hashes.
- All Z controls had zero events and zero changed weights.
- The archive verifier passed with 53 sealed files and 19 output files.

DH-08A estimates a one-event endpoint substitution on states visited by the endogenous true policy. It
does not estimate the cumulative adaptive-policy effect, and Q07 permits small within-support changes
in realized zero placement.
