# F4 Cross-Distribution Failure Audit

Analysis-only comparison of sealed qualification artifacts. No fits, refits, or prediction scoring were performed.

## Frozen D outcome anchors

| Run | U* rows | D balanced error | D Omega-hat | Task blocks | Structurally screened |
|---|---:|---:|---:|---:|---|
| SYMMETRY03 | 16,342 | 0.076768 | 0.846464 | 8 | True |
| QPROMO2 | 23,486 | 0.349881 | 0.300238 | 12 | False |

## Task-only structure

- **SYMMETRY03:** 8 blocks; 4 cues; 8,192 trials/block; 12 delay steps; 5 distinct balanced cue-label assignments; pooled primary-cue CV 0.0060; pooled delay-token CV 0.0053.
- **QPROMO2:** 12 blocks; 4 cues; 8,192 trials/block; 12 delay steps; 5 distinct balanced cue-label assignments; pooled primary-cue CV 0.0020; pooled delay-token CV 0.0045.

## Scored U* support and labels

- **SYMMETRY03:** class-complete blocks 6/8; rows/block min–median–max 0–2,016.0–3,816; observed positive share 24.972%; IPW positive share 25.000%.
- **QPROMO2:** class-complete blocks 9/12; rows/block min–median–max 69–1,595.5–4,899; observed positive share 37.014%; IPW positive share 37.001%.

## Target-margin and leverage summaries

- **SYMMETRY03:** IPW |g| quantiles p10/p50/p90 = 9.877e-12/3.496e-08/5.672e-05; IPW share |g|≤1e-8 = 44.415%; leverage ESS 312.8/16,342 (1.914%); top-1/5/20% leverage shares 60.912%/93.579%/99.882%.
- **QPROMO2:** IPW |g| quantiles p10/p50/p90 = 5.233e-12/2.293e-09/2.061e-05; IPW share |g|≤1e-8 = 55.085%; leverage ESS 215.5/23,486 (0.917%); top-1/5/20% leverage shares 72.961%/96.256%/99.927%.

## Bounded interpretation

D calibration accessibility differed sharply between these qualification distributions. Both task banks use the same four-cue schedule design, but SYMMETRY-03 task blocks were structure-screened while QPROMO2 blocks were ordinary and unscreened. Differences in scored U* support, target margins, and leverage concentration describe where the sampled populations differ; because block seeds and selection procedures differ, this comparison does not identify structural screening as the sole cause.

This is descriptive archaeology across different frozen block seeds and selection procedures. It cannot isolate structural screening as the sole cause of the calibration gap. No incidence-pattern or correctness-conditioned follow-up was computed.

Audit scope SHA-256: `f7a4baebed1a3d264f325cc9f364daa283305fac3b1289ee59702621e9c8d725`.
