# E009 expanded observer benchmark

Run: `e009-20260925-corrected-07`

Thresholds were fit using development labels only. This scoring bank contains fresh task families that were frozen after the v5 observer contract and was not scored in earlier E009 runs. The bank contains 4 task families from one frozen product repository, with two prompt variants per family.

## Lane results

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls | Input tokens | Generated tokens | Model time (s) | Task p50/p95 (s) | Total elapsed (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hand-written | 4/8 | 1 | 3 | 0 | 0 | 0 | 0 | 0.00 | 0.07/0.77 | 1.25 |
| small | 3/8 | 0 | 5 | 0 | 0 | 7842 | 168 | 8.64 | 0.33/5.12 | 9.15 |
| small-then-large-on-abstention | 8/8 | 0 | 0 | 0 | 5 | 13515 | 344 | 37.73 | 3.45/14.31 | 38.28 |
| always-large | 8/8 | 0 | 0 | 0 | 8 | 9021 | 281 | 48.62 | 3.87/14.05 | 49.04 |

## Frozen gate and authority

Selected on development: minimum applicability `850`, maximum abstention `150`.
Hand-written baseline: `evidence-weighted-token-overlap-v2; unique top score >=5 and margin >=2`.
Illegal commits: 0; rejected transitions: 0; duplicate action effects: 0; replay identity: True.

## Family results

### builtin-preset-duration-validation

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 0/2 | 0 | 2 | 0 | 0 |
| small | 1/2 | 0 | 1 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 1 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### explicit-run-boundaries-under-budget

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 1/2 | 1 | 0 | 0 | 0 |
| small | 1/2 | 0 | 1 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 1 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### overlapping-fill-replacement-splits

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 1/2 | 0 | 1 | 0 | 0 |
| small | 0/2 | 0 | 2 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 2 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### preset-json-version-integrity

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 2/2 | 0 | 0 | 0 | 0 |
| small | 1/2 | 0 | 1 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 1 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

## Limits

This is task-family transfer within one repository, not a cross-repository result. Exact completion outcomes were reused from hash-verified bank-build test receipts captured before model contact; their one-time build and test time is excluded from lane task latency. Local model requests are unbilled; energy and hardware-dollar cost are not measured. The post-hoc coverage/error curve is descriptive and did not change the selected threshold or v5 bundle.
