# DH-07R result: the feasible alternate direction wins

DH-07R completed once under seal `18508e8fc6b3e86a7f8d56cde0413fd43b436c06de056f7f7a20a155225b060d`. The archive verifier checked 58 frozen files and 18 output files. All 65,536 committed null events passed the frozen realized-geometry gates, all 2,048 result cells were present, acquisition hashes matched, and fixed-weight Z outputs were condition invariant.

The primary result was opposite the directional prediction:

`true endogenous residual - feasible matched null = +0.003990621 old-map margin`

- paired 95% t interval: `[+0.003226578, +0.004754664]`
- paired 95% percentile bootstrap interval: `[+0.003256979, +0.004699068]`
- 31 of 32 paired seed-bundle contrasts were positive

The matched alternate residual direction therefore suppressed old-map expression more strongly than the endogenous residual direction under this adaptive policy comparison.

The effect was consistent across slices and eligibility time constants:

| Subset | Mean true minus null | Paired 95% t interval |
| --- | ---: | ---: |
| Right | +0.003539 | [+0.002593, +0.004485] |
| Left | +0.004442 | [+0.003456, +0.005428] |
| tau 4 | +0.003722 | [+0.003032, +0.004412] |
| tau 16 | +0.004259 | [+0.003231, +0.005287] |

The two parallel contexts differed in their cumulative geometry:

| Context | Final old-margin difference | Final acquisition-coordinate difference |
| --- | ---: | ---: |
| Parallel off | +0.003474 | +0.003369 |
| Parallel on | +0.004507 | +0.086876 |

The post hoc frozen-output trajectory audit found that parallel-on acquisition-axis divergence was already resolved at trial 16, while its old-map-margin difference resolved at trial 32. DH-07R therefore establishes an adaptive direction-replacement policy effect. It does not establish a final behavioral difference at matched cumulative acquisition-axis position.

Both true and null residual policies suppressed old-map expression relative to their no-residual baselines. The feasible alternate did more:

| Context | True residual vs baseline | Matched null vs baseline |
| --- | ---: | ---: |
| Parallel off | -0.004984 | -0.008458 |
| Parallel on | -0.002659 | -0.007166 |

This rules out the intended claim that the endogenous off-axis direction is specially optimized to destabilize the stale map. It leaves two live mechanisms:

1. The endogenous direction is locally conservative or protective, preserving more old-map expression than another feasible direction.
2. Event-local differences alter future clipping, eligibility, actions, rewards, and aligned updates; the cumulative advantage of the null policy is path-mediated.

DH-08A should distinguish those mechanisms with an event-local impulse assay on the cleaner parallel-off endogenous trajectory. At every event it will evaluate old-map margin directly and without mutation at the common base, true endpoint, and Q07-matched null endpoint, discard both shadow endpoints, and commit the ordinary true endpoint. The scientific unit remains the fresh seed bundle; events, sides, and taus are repeated measurements.

## Artifacts

- Measured analysis: `artifacts/runs/20260915T233614Z/analysis/REPORT.md`
- Machine summary: `artifacts/runs/20260915T233614Z/analysis/summary.json`
- Primary figure: `artifacts/runs/20260915T233614Z/analysis/dh07r_direction_effect.svg`
- Post hoc trajectory audit: `posthoc/20260916T051439Z/REPORT.md`
- Post hoc trajectory figure: `posthoc/20260916T051439Z/trajectory.svg`
