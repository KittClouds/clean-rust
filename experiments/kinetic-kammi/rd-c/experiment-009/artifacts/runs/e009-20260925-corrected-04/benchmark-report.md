# E009 expanded observer benchmark

Run: `e009-20260925-corrected-04`

Thresholds were fit using development labels only. This corrected-v5 replay reuses the held-out bank scored in e009-20260925-expanded-01, so it is a regression diagnostic, not promotion evidence. The bank has four task families from one frozen product repository, with two prompt variants per family.

## Lane results

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls | Input tokens | Generated tokens | Model time (s) | Task p50/p95 (s) | Total elapsed (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hand-written | 6/8 | 2 | 0 | 0 | 0 | 0 | 0 | 0.00 | 7.64/8.07 | 61.71 |
| small | 4/8 | 1 | 3 | 0 | 0 | 8486 | 168 | 2.18 | 7.45/9.17 | 42.56 |
| small-then-large-on-abstention | 7/8 | 1 | 0 | 0 | 3 | 12185 | 273 | 10.88 | 8.27/11.48 | 72.53 |
| always-large | 8/8 | 0 | 0 | 0 | 8 | 9793 | 280 | 23.15 | 10.50/10.94 | 84.63 |

## Frozen gate and authority

Selected on development: minimum applicability `850`, maximum abstention `150`.
Hand-written baseline: `evidence-weighted-token-overlap-v2; unique top score >=5 and margin >=2`.
Illegal commits: 0; rejected transitions: 0; duplicate action effects: 0; replay identity: True.

## Family results

### draft-cardinality-transitions

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 2/2 | 0 | 0 | 0 | 0 |
| small | 1/2 | 1 | 0 | 0 | 0 |
| small-then-large-on-abstention | 1/2 | 1 | 0 | 0 | 0 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### fill-clear-intervals

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 2/2 | 0 | 0 | 0 | 0 |
| small | 1/2 | 0 | 1 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 1 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### hard-stop-ordering

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 2/2 | 0 | 0 | 0 | 0 |
| small | 1/2 | 0 | 1 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 1 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### inherited-style-preservation

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 0/2 | 2 | 0 | 0 | 0 |
| small | 1/2 | 0 | 1 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 1 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

## Limits

This is task-family transfer within one repository, not a cross-repository result. This corrected-v5 replay reuses the held-out bank scored in e009-20260925-expanded-01, so it is a regression diagnostic and not promotion evidence. Local model requests are unbilled; energy and hardware-dollar cost were not measured. The post-hoc coverage/error curve is descriptive and did not change the selected threshold or v5 bundle.
