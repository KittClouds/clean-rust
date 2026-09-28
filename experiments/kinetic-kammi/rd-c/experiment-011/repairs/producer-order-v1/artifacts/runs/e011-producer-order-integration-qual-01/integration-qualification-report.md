# E011 Producer-Order Runtime Integration Qualification

Run: `e011-producer-order-integration-qual-01`; bank: `e011-fresh-integration-bank-v1c`.

This is a small integration qualification on four newly built task frames across two locked Rust repositories. It exercises one new regression target per repository with two prompt/test variants each; the tasks are fresh to the v5 observer, but the result is not a repository-generalization estimate.

The frozen E009 v5 prompt, bundles, normalization, routing rule, and `850/150` thresholds were used without fitting. Every frame was deliberately permuted in the transport adapter, restored by producer ordinal, and checked byte-for-byte at the observer-frame level before model contact.

## Repository results

| Repository | Lane | Coverage | Direct precision | Completion | Large calls avoided | Wrong legal actions |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ripgrep | Small | 2/2 | 2/2 | 2/2 | 2 | 0 |
| ripgrep | Hybrid | 2/2 | — | 2/2 | 2 | 0 |
| ripgrep | Always Large | 2/2 | — | 2/2 | 0 | 0 |
| turbovec | Small | 2/2 | 2/2 | 2/2 | 2 | 0 |
| turbovec | Hybrid | 2/2 | — | 2/2 | 2 | 0 |
| turbovec | Always Large | 2/2 | — | 2/2 | 0 | 0 |

## Pooled descriptive totals

| Lane | Completion | Wrong legal | Large calls | Small calls | Input tokens | Generated tokens | Model time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| small | 4/4 | 0 | 0 | 4 | 4633 | 84 | 2.73 |
| small-then-large-on-abstention | 4/4 | 0 | 0 | 4 | 4633 | 84 | 2.73 |
| always-large | 4/4 | 0 | 4 | 0 | 5094 | 140 | 141.03 |

## Integration gates

- `ripgrep`: `PASS`; hybrid completion ≥ always-large: True; large call displaced: True; small direct coverage nonzero: True; direct small actions all correct: True; authority and replay clean: True.
- `turbovec`: `PASS`; hybrid completion ≥ always-large: True; large call displaced: True; small direct coverage nonzero: True; direct small actions all correct: True; authority and replay clean: True.

Overall repository-level gate: `PASS`.

## Limits

The bank contains four task frames but only two underlying task families, with two variants per family. Results qualify the candidate-order receipt and live authority path on these fixtures; they do not establish new transfer breadth or causal evidence dependence. Model latency is measured locally. Input and generated tokens are reported separately; no token-efficiency claim is made.

Repeated identical task/patch checks across lanes reused a prior live test result. The elapsed time is charged only to the first execution; this test accounting is not a paired end-to-end latency benchmark.

The presentation receipt establishes task/presentation integrity and proposal mapping. It does not prove a selected legal patch is semantically correct; only the isolated completion test records that outcome.
