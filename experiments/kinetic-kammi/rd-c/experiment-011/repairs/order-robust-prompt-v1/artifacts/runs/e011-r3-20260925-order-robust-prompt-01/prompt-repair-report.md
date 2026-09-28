# E011-R3 — Candidate Order Prompt Repair

- Run: e011-r3-20260925-order-robust-prompt-01
- Posthoc same-bank diagnostic; E010 labels were already open.
- Frozen E009 v5 small weights, schema, normalization, runtime, and thresholds; prompt has a new wrapper identity.
- Large fallback outputs are reused from sealed runs on identical condition frames.

## Repository-level results

| Condition | Repository | v5 small coverage / precision | Repair coverage / precision | Repair wrong accepted | v5 hybrid | Repair hybrid | Always large | Large calls avoided | Repair hybrid tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full-frame | ripgrep | 8/8 / 8/8 | 4/8 / 4/4 | 0 | 8/8 | 8/8 | 8/8 | 4 | 18595 |
| full-frame | turbovec | 5/8 / 5/5 | 2/8 / 2/2 | 0 | 8/8 | 5/8 | 5/8 | 2 | 23135 |
| order-only | ripgrep | 8/8 / 7/8 | 7/8 / 6/7 | 1 | 7/8 | 7/8 | 8/8 | 7 | 13722 |
| order-only | turbovec | 7/8 / 5/7 | 4/8 / 3/4 | 1 | 5/8 | 4/8 | 5/8 | 4 | 20077 |

## Interpretation boundary

Promotion requires the prompt repair to remove order-induced wrong accepted actions without sacrificing the useful frozen-order completion region. The same opened bank is a repair diagnostic only; no transfer claim follows.
