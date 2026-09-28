# R&D-C / Experiment 011 — Causal Evidence Dependence

- Run: e011-20260925-causal-evidence-01
- Classification: same-bank diagnostic; treatment execution was shadow-only
- Frozen thresholds: applicability >= 850/1000; abstention <= 150/1000.
- E010 labels were previously opened; E011 is a paired same-bank diagnostic, not independent held-out validation.
- Interventions were shadow-only. E010 remains the execution, authority, and replay control.

## E010 baseline reproduction

| Repository | Tasks | Small coverage | Small precision | Hybrid | Always large | Large calls avoided |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 8 | 8/8 | 8/8 | 8/8 | 8/8 | 8 |
| turbovec | 8 | 5/8 | 5/5 | 8/8 | 5/8 | 5 |

## E010 full-frame error complementarity

| Repository | P(small correct given large wrong) | P(large correct given small abstains or wrong) |
| --- | ---: | ---: |
| turbovec | 100.0% (1/1) | 100.0% (3/3) |
| ripgrep | n/a | n/a |

## evidence-masked

| Repository | Tasks | Small coverage | Direct precision | Wrong small commits | Hybrid | Always large | Large calls avoided | Routed tokens | Routed observer ms | Mean delta applicability | Mean delta abstention |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 8 | 3/8 (37.5%) | 3/3 (100.0%) | 0 | 8/8 | 8/8 | 3 | 13339 | 17660.263 | -625.0 | 625.0 |
| turbovec | 8 | 2/8 (25.0%) | 2/2 (100.0%) | 0 | 4/8 | 4/8 | 2 | 15934 | 24878.372 | -368.75 | 368.75 |

Large-observer behavior by repository:

| Repository | Coverage | Direct precision | Proposal changes vs full | Mean delta applicability | Mean delta abstention |
| --- | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 8/8 (100.0%) | 8/8 (100.0%) | 0 | -42.5 | 42.5 |
| turbovec | 4/8 (50.0%) | 4/4 (100.0%) | 3 | 53.75 | -53.75 |

Small-observer paired diagnostics by repository:
- ripgrep: {"small_abstention_higher": 5, "small_applicability_lower": 5, "small_coverage_higher": 0, "small_coverage_lower": 5}
  State transitions: {"correct_to_correct": 3, "correct_to_relinquished": 5}
- turbovec: {"small_abstention_higher": 4, "small_applicability_lower": 4, "small_coverage_higher": 1, "small_coverage_lower": 4}
  State transitions: {"correct_to_correct": 1, "correct_to_relinquished": 4, "relinquished_to_correct": 1, "relinquished_to_relinquished": 2}

Completion and large-call figures replay the frozen routing rule over shadow proposals; no action ran in E011.

## evidence-swapped

| Repository | Tasks | Small coverage | Direct precision | Wrong small commits | Hybrid | Always large | Large calls avoided | Routed tokens | Routed observer ms | Mean delta applicability | Mean delta abstention |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 8 | 6/8 (75.0%) | 6/6 (100.0%) | 0 | 8/8 | 8/8 | 6 | 14320 | 9342.863 | -250.0 | 250.0 |
| turbovec | 8 | 2/8 (25.0%) | 2/2 (100.0%) | 0 | 6/8 | 5/8 | 2 | 22505 | 27591.490 | -368.75 | 368.75 |

Large-observer behavior by repository:

| Repository | Coverage | Direct precision | Proposal changes vs full | Mean delta applicability | Mean delta abstention |
| --- | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 8/8 (100.0%) | 8/8 (100.0%) | 1 | -30.0 | 30.0 |
| turbovec | 6/8 (75.0%) | 5/6 (83.33%) | 2 | 86.25 | -86.25 |

Small-observer paired diagnostics by repository:
- ripgrep: {"small_correct_to_relinquished": 2, "small_correct_to_wrong": 0, "small_proposal_changed": 2, "small_threshold_acceptance_changed": 2, "small_wrong_to_correct": 0, "small_wrong_to_relinquished": 0}
  State transitions: {"correct_to_correct": 6, "correct_to_relinquished": 2}
- turbovec: {"small_correct_to_relinquished": 3, "small_correct_to_wrong": 0, "small_proposal_changed": 4, "small_threshold_acceptance_changed": 3, "small_wrong_to_correct": 0, "small_wrong_to_relinquished": 0}
  State transitions: {"correct_to_correct": 2, "correct_to_relinquished": 3, "relinquished_to_relinquished": 3}

Completion and large-call figures replay the frozen routing rule over shadow proposals; no action ran in E011.

## repository-neutralized

| Repository | Tasks | Small coverage | Direct precision | Wrong small commits | Hybrid | Always large | Large calls avoided | Routed tokens | Routed observer ms | Mean delta applicability | Mean delta abstention |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 8 | 7/8 (87.5%) | 7/7 (100.0%) | 0 | 8/8 | 8/8 | 7 | 12551 | 5913.599 | -125.0 | 125.0 |
| turbovec | 8 | 6/8 (75.0%) | 6/6 (100.0%) | 0 | 7/8 | 6/8 | 6 | 14990 | 11302.298 | 131.25 | -131.25 |

Large-observer behavior by repository:

| Repository | Coverage | Direct precision | Proposal changes vs full | Mean delta applicability | Mean delta abstention |
| --- | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 8/8 (100.0%) | 8/8 (100.0%) | 0 | 0.0 | 0.0 |
| turbovec | 6/8 (75.0%) | 6/6 (100.0%) | 2 | -21.25 | 21.25 |

Small-observer paired diagnostics by repository:
- ripgrep: {"small_proposal_invariant": 7, "small_threshold_acceptance_invariant": 7}
  State transitions: {"correct_to_correct": 7, "correct_to_relinquished": 1}
- turbovec: {"small_proposal_invariant": 5, "small_threshold_acceptance_invariant": 5}
  State transitions: {"correct_to_correct": 4, "correct_to_relinquished": 1, "relinquished_to_correct": 2, "relinquished_to_relinquished": 1}

Completion and large-call figures replay the frozen routing rule over shadow proposals; no action ran in E011.

## candidate-permuted

| Repository | Tasks | Small coverage | Direct precision | Wrong small commits | Hybrid | Always large | Large calls avoided | Routed tokens | Routed observer ms | Mean delta applicability | Mean delta abstention |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 8 | 7/8 (87.5%) | 6/7 (85.71%) | 1 | 7/8 | 8/8 | 7 | 12860 | 5824.061 | -112.5 | 112.5 |
| turbovec | 8 | 6/8 (75.0%) | 5/6 (83.33%) | 1 | 6/8 | 5/8 | 6 | 14894 | 9730.011 | 187.5 | -187.5 |

Large-observer behavior by repository:

| Repository | Coverage | Direct precision | Proposal changes vs full | Mean delta applicability | Mean delta abstention |
| --- | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 8/8 (100.0%) | 8/8 (100.0%) | 0 | -8.75 | 8.75 |
| turbovec | 6/8 (75.0%) | 5/6 (83.33%) | 1 | 28.75 | -28.75 |

Small-observer paired diagnostics by repository:
- ripgrep: {"small_semantic_proposal_invariant": 4, "small_threshold_acceptance_invariant": 7}
  State transitions: {"correct_to_correct": 6, "correct_to_relinquished": 1, "correct_to_wrong": 1}
- turbovec: {"small_semantic_proposal_invariant": 1, "small_threshold_acceptance_invariant": 3}
  State transitions: {"correct_to_correct": 3, "correct_to_relinquished": 2, "relinquished_to_correct": 2, "relinquished_to_wrong": 1}

Completion and large-call figures replay the frozen routing rule over shadow proposals; no action ran in E011.

## Interpretation

Use repository rows as the transfer units and pooled totals only as descriptive summaries. Evidence masking leaves the task prompt and candidate diffs intact, so a stable proposal does not prove that evidence was ignored. Evidence swapping measures paired proposal and score changes under mismatched evidence; donor truth is not transferred to the recipient candidate set. Repository neutralization removes direct identity tokens and metadata but cannot erase every semantic clue in code or tests. Candidate permutation is scored by patch digest, so this lane isolates numeric IDs and ordering from action content.

E011 is an interface-sensitivity diagnostic for the frozen switchboard. It does not establish a causal mechanism or a new cross-repository generalization result.
