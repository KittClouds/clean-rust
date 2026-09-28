# DH-04 measured results

**PARTIAL_ERASURE_SUPPORTED_IN_MODEL**

Retained minus suppressed reversed-probe effect, percentage points: **+6.673**; paired 95% [+5.754, +7.666].

Retained minus suppressed acquisition-axis coordinate: **-0.179**; paired 95% [-0.193, -0.165].

Retained final acquisition-axis coordinate: **+0.654**; paired 95% [+0.638, +0.672].

Retained final deterministic old-map margin: **+0.022**; paired 95% [+0.019, +0.024].

The acquisition axis assigns initial weights coordinate 0 and acquired weights coordinate 1. Positive old-map margin means the acquired target mapping remains preferred.

768 arm runs; 393,216 computed training trials; 192 acquisition streams repeated across four conditions; 24 fresh seed bundles; two taus; one specimen.

## Final same-RNG probes and weight geometry

| Slice | Arm | Condition | Old-map probe | Reversed probe | Acquisition-axis q | Old-map margin |
|---|---|---|---:|---:|---:|---:|
| R | E | immediate | 45.95% | 54.05% | 0.5799 | -0.006602 |
| R | E | quiet | 68.20% | 31.80% | 0.6545 | 0.034973 |
| R | E | eligibility_retained | 61.81% | 38.19% | 0.6541 | 0.021845 |
| R | E | eligibility_suppressed | 68.48% | 31.52% | 0.8333 | 0.033506 |
| R | Z | immediate | 48.76% | 51.24% | n/a | 0.001105 |
| R | Z | quiet | 48.76% | 51.24% | n/a | 0.001105 |
| R | Z | eligibility_retained | 48.76% | 51.24% | n/a | 0.001105 |
| R | Z | eligibility_suppressed | 48.76% | 51.24% | n/a | 0.001105 |
| L | E | immediate | 44.27% | 55.73% | 0.5979 | -0.008504 |
| L | E | quiet | 67.23% | 32.77% | 0.6575 | 0.032836 |
| L | E | eligibility_retained | 61.35% | 38.65% | 0.6468 | 0.019058 |
| L | E | eligibility_suppressed | 67.49% | 32.51% | 0.8311 | 0.031707 |
| L | Z | immediate | 49.71% | 50.29% | n/a | -0.000455 |
| L | Z | quiet | 49.71% | 50.29% | n/a | -0.000455 |
| L | Z | eligibility_retained | 49.71% | 50.29% | n/a | -0.000455 |
| L | Z | eligibility_suppressed | 49.71% | 50.29% | n/a | -0.000455 |

## Descriptive immediate-reference geometry

| Condition | Cosine to immediate reversal delta | Distance to immediate final / immediate delta |
|---|---:|---:|
| immediate | 1.0000 | 0.0000 |
| quiet | 0.4829 | 0.9456 |
| eligibility_retained | 0.3289 | 1.3116 |
| eligibility_suppressed | 0.7409 | 0.8034 |

Retained-minus-suppressed eligibility contribution: negative-acquisition-axis projection 0.1792; cosine to immediate reversal delta 0.1564; norm/acquisition norm 0.9133.

## Integrity and limits

- Complete grid, matching acquisition hashes and margins, fixed-weight action parity, exact intervention receipts, same-RNG probe complements, event counts, and graph-null invariants passed.
- Simulator execution including setup and diagnostics: 12.877 seconds on 4 workers.
- No online-loop allocations. Snapshot and geometry buffers are additional experimental instrumentation.
- Weight geometry and action margins are model-coordinate evidence. They do not identify a biological mechanism.
- One specimen; left/right are related soma slices. Synthetic dynamics, labels, bounds, clipping, and readout remain modelling choices.
- No post-outcome tuning, extra seeds, endpoint changes, or rule search.

Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY. https://male-cns.janelia.org/download/
