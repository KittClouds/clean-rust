# R&D-C / Experiment 010 — Cross-Repository Switchboard Transfer

Run: `e010-20260925-cross-repo-01`

The unchanged E009 v5 thresholds are `850/150`. This E010 bank was selected from two committed repositories and frozen before observer contact. No E010 labels were used to fit thresholds. The bank contains 8 task families and 16 prompt variants across two frozen repositories.

## Lane results

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls | Input tokens | Generated tokens | Model time (s) | Task p50/p95 (s) | Total elapsed (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hand-written | 13/16 | 0 | 3 | 0 | 0 | 0 | 0 | 0.00 | 5.07/40.35 | 136.73 |
| small | 13/16 | 0 | 3 | 0 | 0 | 22776 | 336 | 5.20 | 5.04/11.63 | 97.41 |
| small-then-large-on-abstention | 16/16 | 0 | 0 | 0 | 3 | 27211 | 441 | 21.54 | 8.05/18.23 | 145.17 |
| always-large | 13/16 | 1 | 2 | 0 | 16 | 25783 | 559 | 92.27 | 11.15/60.07 | 242.14 |

## Frozen gate and authority

Carried forward unchanged from E009 development: minimum applicability `850`, maximum abstention `150`.
Hand-written baseline: `evidence-weighted-token-overlap-v2; unique top score >=5 and margin >=2`.
Illegal commits: 0; rejected transitions: 0; duplicate action effects: 0; replay identity: True.

## Family results

### ripgrep-case-insensitive-glob

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 2/2 | 0 | 0 | 0 | 0 |
| small | 2/2 | 0 | 0 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 0 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### ripgrep-gitignore-bom

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 2/2 | 0 | 0 | 0 | 0 |
| small | 2/2 | 0 | 0 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 0 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### ripgrep-literal-separator-glob

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 2/2 | 0 | 0 | 0 | 0 |
| small | 2/2 | 0 | 0 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 0 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### ripgrep-recursive-glob

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 2/2 | 0 | 0 | 0 | 0 |
| small | 2/2 | 0 | 0 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 0 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### turbovec-id-remove-readd

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 1/2 | 0 | 1 | 0 | 0 |
| small | 1/2 | 0 | 1 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 1 |
| always-large | 1/2 | 1 | 0 | 0 | 2 |

### turbovec-id-swap-repair

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 1/2 | 0 | 1 | 0 | 0 |
| small | 1/2 | 0 | 1 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 1 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### turbovec-mask-allowlist

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 1/2 | 0 | 1 | 0 | 0 |
| small | 1/2 | 0 | 1 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 1 |
| always-large | 2/2 | 0 | 0 | 0 | 2 |

### turbovec-rotation-wire-format

| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| hand-written | 2/2 | 0 | 0 | 0 | 0 |
| small | 2/2 | 0 | 0 | 0 | 0 |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 0 | 0 |
| always-large | 0/2 | 0 | 2 | 0 | 2 |

## Limits

This is a bounded cross-repository result on the two named repositories and this frozen bank. Each selected patch was tested in its isolated frozen candidate snapshot with the exact task check; test and authority time are included in lane latency. Local model requests are unbilled; energy and hardware-dollar cost are not measured. The post-hoc coverage/error curve is descriptive and did not change the selected threshold or v5 bundle.
