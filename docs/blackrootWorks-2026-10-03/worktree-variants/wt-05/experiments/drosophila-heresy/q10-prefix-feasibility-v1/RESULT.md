# Q10-PF1 result

Status: `Q10_PF1_STAGE1_VALID__RELAXATION_PARTIAL_NO_EXACT_AUTHORIZATION`

Q10-PF1 completed all eight predeclared engineering events. The independent
reviewer returned `VERIFIED`; source-manifest, coverage, finite-metric, curve,
and firewall checks passed. No scientific seed bundle or behavioral endpoint
was opened, and no DH-08B authorization was issued.

The per-coordinate endpoint hulls were built from committed sequential-f32
effects for zero movement and legal down/up prefixes through 16 ULP steps. A
12-pass block relaxation over the product of those hulls reduced every initial
readout mismatch, but no event reached the preregistered relaxed-fit threshold
of `1e-6`.

| seed | side | tau | initial mismatches | final residual ratio | endpoint count | nonzero endpoints |
|---:|:---:|---:|---:|---:|---:|---:|
| 9651 | L | 4 | 366 | 0.2693 | 150,942 | 49,319 |
| 9651 | L | 16 | 353 | 0.1918 | 152,394 | 49,360 |
| 9651 | R | 4 | 353 | 0.3303 | 148,698 | 46,799 |
| 9651 | R | 16 | 362 | 0.2919 | 149,622 | 46,579 |
| 9652 | L | 4 | 373 | 0.2864 | 182,952 | 59,745 |
| 9652 | L | 16 | 362 | 0.1787 | 182,325 | 58,251 |
| 9652 | R | 4 | 366 | 0.3324 | 166,683 | 54,014 |
| 9652 | R | 16 | 362 | 0.2769 | 167,442 | 54,066 |

The observed final residual-ratio range over all eight events was approximately
`0.1787` to `0.3324`. Curves flattened after the first few passes; additional
passes in this frozen run were not authorized as a new solver qualification.

## Interpretation

This is a valid **partial convex-relaxation result**. It does not establish
that the exact one-prefix-per-coordinate repair problem is infeasible, because
the fixed 12-pass relaxation is not a separating certificate for the convex
product of hulls. It does establish that the current relaxed constructor does
not yet provide the gate required to authorize an exact discrete search.

The DN3 span result therefore does not transfer directly to realizable repair:
the remaining bottleneck is now coordinate coupling plus solver/relaxation
coverage, rather than one-ULP readout authority alone.

The next allowed step is a new engineering identity with a stronger
relaxation/convergence diagnostic or a solver-independent convex feasibility
certificate. An exact prefix search and all scientific work remain gated.
