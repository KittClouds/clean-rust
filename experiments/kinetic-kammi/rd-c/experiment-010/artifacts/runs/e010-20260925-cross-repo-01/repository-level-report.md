# E010 repository-level switchboard report

Promotion is evaluated independently for each repository. Repo A is ripgrep; Repo B is turbovec. Each has four task families expressed in two prompt variants (eight scored prompts); the repository is the transfer unit, and pooled totals are descriptive.

| Repository | Small coverage | Direct precision | Hybrid | Always large | Large calls avoided | Direct errors | Authority / replay | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Repo A (ripgrep) | 100.0% (8/8) | 100.0% (8/8) | 8/8 | 8/8 | 8 | 0 | True | PASS |
| Repo B (turbovec) | 62.5% (5/8) | 100.0% (5/5) | 8/8 | 5/8 | 5 | 0 | True | PASS |

## Repository-level measured efficiency

Times include the selected candidate test and authority receipt. Tokens include the invoked observer calls.

| Repository | Hybrid / always-large tokens | Hybrid / always-large elapsed (s) |
| --- | ---: | ---: |
| Repo A (ripgrep) | 11,363 / 12,627 | 43.98 / 131.79 |
| Repo B (turbovec) | 16,289 / 13,715 | 101.19 / 110.35 |

## Pooled descriptive totals

Hybrid completion: 16/16 versus always-large 13/16; small direct coverage 81.2%; direct precision 100.0%; large calls avoided 13; tokens hybrid/always-large 27652/26342; elapsed milliseconds hybrid/always-large 145165.9/242136.6.

## Preregistered outcome: PASS

The gate requires, in each repository: hybrid completion at least equal to always-large, at least one displaced large call, zero wrong direct small actions, and zero illegal commits, duplicate effects, or replay mismatches.
