# Phase 6D — factorized legality acquisition

PRECISE_LEGALITY_ACQUISITION_UNRESOLVED_CANDIDATE_METRICS_ONLY

One legality-only gate; Qwen/E/goal heads and Phase6C consequence scores frozen. Protected evaluation unopened.

| Endpoint (333 canonical DEV roots) | Initialization | Epoch 8 |
|---|---:|---:|
| BA | 0.582293 | 0.778292 |
| precision | 0.100097 | 0.187513 |
| recall | 0.353345 | 0.749571 |
| F1 | 0.156002 | 0.299983 |
| full_exact_set_recovery | 0.000000 | 0.000000 |
| root_mean_Jaccard | 0.139543 | 0.196643 |
| false_positives_per_root | 11.123123 | 11.372373 |
| false_negatives_per_root | 2.264264 | 0.876877 |
| selected_retention | 0.192192 | 0.771772 |

Same-type exact sets: 0.015015.
Root FP/FN decomposition: {'FN_max': 7, 'FN_only': 6, 'FP_and_FN': 185, 'FP_max': 43, 'FP_only': 142, 'perfect': 0}.

| Path | Full top1 | Full MRR | Same-type top1 | Same-type MRR |
|---|---:|---:|---:|---:|
| A_no_filter | 0.003003 | 0.184531 | 0.138138 | 0.346790 |
| B_learned_gate | 0.003003 | 0.174150 | 0.117117 | 0.283466 |
| C_gold_gate | 0.003003 | 0.427327 | 0.819820 | 0.904655 |

Full results.json contains separate selected/optimal denominators, top3/top5, best-optimal ranks, every root FP/FN, both renderings, action-type/candidate-count/renderer slices, support census, and paired bootstrap intervals.

Gate rejection is an error (MRR/top-k zero), not eligibility exclusion. Empty gates abstain. Fixed logit>0 threshold; no threshold or cardinality shopping.

Gold legality is not permission policy. Its 81.98% same-type result does not imply full-set decision sufficiency: gold-gate full-set top1 remains 0.30%. Learned pruning gains on incorrect sets are not evidence of precise legality.

Exactly recovered sets: 0 roots; learned/gold composition is identical on this subset.

Preservation: frozen E production goal/binding/globalization/renderer panel retained exactly; candidate permutation test passed. Consequence legal ordering and distance MAE unchanged; all frozen DEV consequence outputs independently reproduced exactly.

Parameters: 101615; training 96.22s, 672 steps, CPU FP32 four threads. Forward timings/bytes: evaluation-cost.json. No new Qwen extraction or GPU use.

Independent fresh-process gate-logit/metric replay and canonical legality derivation pass. Source, specification, checkpoints, upstream identities, and receipts are hash-bound. Active logs excluded from closure.

Next proposed experiment (not run): raw Qwen legality-access audit. F/comparator/recurrence/LoRA remain unrun.
