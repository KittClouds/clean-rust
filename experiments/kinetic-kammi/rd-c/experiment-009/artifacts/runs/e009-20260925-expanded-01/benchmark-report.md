# E009 expanded observer benchmark

Run: `e009-20260925-expanded-01`

The development bank selected the threshold pair before held-out labels were read. The held-out set contains four new test families from the same frozen product repository; the previously scored pilot families were excluded. Two prompt variants per family are grouped by family for interpretation.

## Lane results

| Lane | Complete | Wrong legal | Abstain | Large calls | Input tokens | Generated tokens | Model time (s) | Total elapsed (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hand-written | 0/8 | 0 | 8 | 0 | 0 | 0 | 0.00 | 0.73 |
| small | 5/8 | 1 | 2 | 0 | 8502 | 184 | 2.72 | 218.04 |
| small-then-large-on-abstention | 7/8 | 1 | 0 | 2 | 10990 | 262 | 9.14 | 74.82 |
| always-large | 8/8 | 0 | 0 | 8 | 9809 | 312 | 24.64 | 101.64 |

## Frozen gate and authority

Selected on development: minimum applicability `50`, maximum abstention `180`.
Illegal commits: 12; duplicate action effects: 0; replay identity: True.

## Family results

### draft-cardinality-transitions

| Lane | Complete | Wrong legal | Abstain | Large calls |
| --- | ---: | ---: | ---: | ---: |
| hand-written | 0/2 | 0 | 2 | 0 |
| small | 1/2 | 1 | 0 | 0 |
| small-then-large-on-abstention | 1/2 | 1 | 0 | 0 |
| always-large | 2/2 | 0 | 0 | 2 |

### fill-clear-intervals

| Lane | Complete | Wrong legal | Abstain | Large calls |
| --- | ---: | ---: | ---: | ---: |
| hand-written | 0/2 | 0 | 2 | 0 |
| small | 1/2 | 0 | 1 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 1 |
| always-large | 2/2 | 0 | 0 | 2 |

### hard-stop-ordering

| Lane | Complete | Wrong legal | Abstain | Large calls |
| --- | ---: | ---: | ---: | ---: |
| hand-written | 0/2 | 0 | 2 | 0 |
| small | 2/2 | 0 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 |
| always-large | 2/2 | 0 | 0 | 2 |

### inherited-style-preservation

| Lane | Complete | Wrong legal | Abstain | Large calls |
| --- | ---: | ---: | ---: | ---: |
| hand-written | 0/2 | 0 | 2 | 0 |
| small | 1/2 | 0 | 1 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 1 |
| always-large | 2/2 | 0 | 0 | 2 |

## Limits

This is task-family transfer within one repository, not a cross-repository result. Local model requests are unbilled; energy and hardware-dollar cost were not measured. The post-hoc coverage/error curve is descriptive and did not change the selected threshold or v3 bundle.
