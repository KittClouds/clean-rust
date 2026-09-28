# E011-R2 — Candidate Presentation Factorial

- Run: e011-r2-20260925-presentation-factorial-01
- E009 v5 weights, prompt, output schema, normalization, and thresholds unchanged.
- Same E010 tasks and already-opened labels; shadow-only paired diagnosis.

## Repository-level results

| Condition | Repository | Small coverage | Direct precision | Wrong small actions | Hybrid | Always large | Large calls avoided |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ids-only | ripgrep | 7/8 | 7/7 (100.0%) | 0 | 8/8 | 8/8 | 7 |
| ids-only | turbovec | 5/8 | 5/5 (100.0%) | 0 | 8/8 | 5/8 | 5 |
| order-only | ripgrep | 8/8 | 7/8 (87.5%) | 1 | 7/8 | 8/8 | 8 |
| order-only | turbovec | 7/8 | 5/7 (71.4%) | 2 | 5/8 | 5/8 | 7 |

## Prior conditions

| Repository | E010 full hybrid / small errors | E011 combined permutation hybrid / small errors | E011-R1 canonical hybrid / small errors |
| --- | ---: | ---: | ---: |
| ripgrep | 8/8 / 0 | 7/8 / 1 | 8/8 / 0 |
| turbovec | 8/8 / 0 | 6/8 / 1 | 2/8 / 6 |

## Interpretation boundary

IDs-only preserves E010 option positions while replacing the numeric IDs with the exact fresh IDs from E011's combined permutation. Order-only uses the exact E011 shuffled positions while restoring original E010 IDs. The paired differences localize presentation sensitivity on this bank. They do not establish broad transfer or internal model mechanism.
