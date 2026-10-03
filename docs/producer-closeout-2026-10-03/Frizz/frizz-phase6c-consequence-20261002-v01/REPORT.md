# Frizz Phase 6C — transition-consequence acquisition

Status: completed, exact fresh-process replay verified; protected evaluation unopened.

## Outcome

RETIRE_CONSEQUENCE_ORGAN_AS_CONSTRUCTED

| Response coordinate | Initialization | Epoch8 | Gate |
| --- | --- | --- | --- |
| Legal-category macro recall | 0.1068 | 0.0974 | False |
| Certified conditional MAE | 1.5172 | 1.5931 | False |
| Conditional same-type legal ordering | 0.5135 | 0.6571 | True |
| Same-type selected top1 | 0.1171 | 0.1381 | False |

This is direct planner-supervision acquisition, not a frozen accessibility probe. A positive result would not show the consequence signal was accessible before this training. A negative bounds this one construction and cannot establish a Qwen information ceiling. F remains parked; no new comparator, recurrence, LoRA or adaptation follows.

## Frozen lineage and ABI

- Qwen/Qwen3.5-0.8B-Base revision dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68, frozen BF16 qualified substrate. Existing bridge/E checkpoints and goal heads unchanged.
- BANK-v3-core release 84f0a7e13032e8cdfcecc862217bb33ca23568fade64fafeef410327eb996f12, synthetic-only; conflict diagnostic-only; protected EVAL untouched.
- Same Phase6B endpoint-eligible population: 1,333 TRAIN /333 DEV canonical roots, both renderings grouped. All candidate types and exhaustive menus retained. This does not establish acquisition on the non-EXECUTE part of BANK-v3-core.
- ABI: observable type9, four qualified positional arguments1024 with typed roles/presence, two existing observable goal-role vectors1024 and ambiguity flags, six TRAIN-normalized global surfaces1024, frozen E c256/e32/s64. No gold feature, selected ID, latent binding repair, new token extraction or candidate cap.
- Paired frozen E states replayed on CPU from the same checkpoint; primary alignment against the historical FP16 caches and prospective .02 tolerance appear in support-census.json. Both renderings use a matched CPU path. Sidecar arithmetic is FP32; Qwen and E are not trainable.
- Baseline positional vectors already carry schema order. The sidecar makes consequence structure trainable; it does not claim E was previously devoid of roles.

## Canonical targets and support

Canonical legal apply at tick1 followed by pinned search(depth8,states40,000). Codes0..8=certified SOLVED remaining distance;9=UNSAT_EXHAUSTED;10=CAP/STATE_LIMIT UNKNOWN;11=ILLEGAL. All categories remain explicit. Fresh simulator replay verifies every retained TRAIN/DEV candidate; immutable input/source hashes are in SPECIFICATION.json.

| Code | TRAIN candidates | TRAIN roots | DEV candidates | DEV roots | DEV supported≥200 |
| --- | --- | --- | --- | --- | --- |
| 0 | 339 | 339 | 93 | 93 | False |
| 1 | 1198 | 967 | 298 | 240 | True |
| 2 | 1615 | 1008 | 375 | 252 | True |
| 3 | 907 | 662 | 228 | 170 | False |
| 4 | 411 | 266 | 104 | 73 | False |
| 5 | 106 | 92 | 33 | 27 | False |
| 6 | 11 | 11 | 5 | 5 | False |
| 7 | 6 | 6 | 3 | 3 | False |
| 8 | 1 | 1 | 3 | 3 | False |
| 9 | 78 | 76 | 23 | 23 | False |
| 10 | 18 | 18 | 1 | 1 | False |
| 11 | 79946 | 1333 | 19623 | 333 | True |

Candidates above are canonical, not doubled renderings. Per-class claims below200 DEV roots are descriptive. This census includes every candidate type; its denominators differ from Phase6B selected-type factor probes. Ordering population and rendered counts remain explicit in support-census.json.

## One estimator and fixed training

164859 trainable sidecar parameters; shared entity1024→32/world1024→16 projections, argument×goal product,823→128→64 GELU MLP, separate four-way status head and monotone eight-cutpoint ordinal distance. No setwise interaction.
- Eight fixed epochs, seed0,16 paired canonical-root batches, AdamW .001/.01, clipping1. No interim DEV scoring or endpoint selection. TRAIN-only inverse-square-root status weights and threshold prevalence balancing; solved ordinal BCE +.25 SmoothL1/8 +.25 same-type certified ordering +.05 paired value consistency.
- Ordering examples use any unequal certified same-type candidate consequences, never selected identity; fixed maximum64 TRAIN pairs/root. DEV ordering enumerates all such pairs.
- Inference value = p_solved E[d]+9p_exhausted+10p_unknown+11p_illegal. Special-state penalties are a declared ranking convention, not true ordinal distances or proofs about unknown continuations. Status probabilities and conditional distance remain separately recorded.
- All target weighting, architecture, dose, rendering, ranking and survival rules were frozen before new DEV contact. Initialization and epoch8 are the only scored checkpoints.

## Consequence factor panel

| Phenotype/render | Legal accuracy | Legal macro recall | Certified MAE | Ordinal absolute error | Legal candidates |
| --- | --- | --- | --- | --- | --- |
| init/paired | 0.0703 | 0.1069 | 1.5184 | 2.0911 | 1166 |
| init/primary | 0.0755 | 0.1068 | 1.5172 | 2.0911 | 1166 |
| trained/paired | 0.1346 | 0.0780 | 1.5501 | 1.5893 | 1166 |
| trained/primary | 0.1261 | 0.0974 | 1.5931 | 1.6384 | 1166 |

Full category recalls and root/class supports: results.json → results → phenotype → render → factor. Illegal/exhausted/unknown are not silently relabeled as solved. Conditional distance metrics do not excuse incorrect status predictions.

## Legal-vs-legal consequence ordering

| Phenotype/render | Conditional ordering root mean | Value ordering root mean | Pairs | Roots | Supported≥200 |
| --- | --- | --- | --- | --- | --- |
| init/paired | 0.5059 | 0.5002 | 207 | 136 | False |
| init/primary | 0.5135 | 0.5449 | 207 | 136 | False |
| trained/paired | 0.6336 | 0.6108 | 207 | 136 | False |
| trained/primary | 0.6571 | 0.5909 | 207 | 136 | False |

Own-init paired-root conditional ordering gain: {'bootstrap_roots': 136, 'ci95': [0.04042279411764714, 0.25024509803921563], 'delta': 0.1436274509803922, 'repetitions': 2000, 'seed': 20261002}. Selected-type ordering is separately retained. If this support is below200, interpretation remains a pilot rather than a reliability-level consequence-ordering claim. Improvement due only to illegality filtering cannot pass the ordering gate.

## Ranking induced by consequence value

| Source/universe | Selected top1 | MRR | Top3 | Top5 | Best optimal mean rank | Roots |
| --- | --- | --- | --- | --- | --- | --- |
| init/primary/full | 0.0150 | 0.0723 | 0.0390 | 0.0841 | 34.4174 | 333 |
| init/primary/gold_legal_full | 0.4294 | 0.6550 | 0.8979 | 0.9910 | 2.0150 | 333 |
| init/primary/gold_legal_same_type | 0.7808 | 0.8824 | 1.0000 | 1.0000 | 1.2673 | 333 |
| init/primary/same_type | 0.1171 | 0.3135 | 0.3333 | 0.5405 | 5.5045 | 333 |
| init/paired/full | 0.0120 | 0.0739 | 0.0511 | 0.0871 | 34.0360 | 333 |
| init/paired/gold_legal_full | 0.4625 | 0.6725 | 0.8859 | 0.9940 | 1.9790 | 333 |
| init/paired/gold_legal_same_type | 0.7778 | 0.8796 | 0.9970 | 1.0000 | 1.2793 | 333 |
| init/paired/same_type | 0.0991 | 0.2990 | 0.3273 | 0.5255 | 5.6006 | 333 |
| trained/primary/full | 0.0030 | 0.1845 | 0.2282 | 0.3814 | 11.6036 | 333 |
| trained/primary/gold_legal_full | 0.0030 | 0.4273 | 0.8739 | 0.9910 | 2.5375 | 333 |
| trained/primary/gold_legal_same_type | 0.8198 | 0.9047 | 0.9970 | 1.0000 | 1.2132 | 333 |
| trained/primary/same_type | 0.1381 | 0.3468 | 0.3934 | 0.6246 | 5.0691 | 333 |
| trained/paired/full | 0.0030 | 0.1924 | 0.2432 | 0.3934 | 11.2673 | 333 |
| trained/paired/gold_legal_full | 0.0030 | 0.4273 | 0.8709 | 0.9940 | 2.5345 | 333 |
| trained/paired/gold_legal_same_type | 0.8228 | 0.9054 | 1.0000 | 1.0000 | 1.2132 | 333 |
| trained/paired/same_type | 0.1652 | 0.3625 | 0.4024 | 0.6036 | 5.1291 | 333 |

Gold-legal restrictions are diagnostic truth-assisted slices, not inference inputs. Same-type restriction uses the logged action type for localization; full-set ranking is unrestricted. Stable canonical menu order breaks numeric ties. Logged selection and best optimal-set membership retain separate supports and exclusion counts.

| Frozen/reference universe | Selected top1 | MRR | Top3 | Top5 | Roots |
| --- | --- | --- | --- | --- | --- |
| linear/full | 0.0901 | 0.2407 | 0.2282 | 0.3784 | 333 |
| linear/same_type | 0.1532 | 0.3391 | 0.3694 | 0.5796 | 333 |
| mlp/full | 0.0871 | 0.2399 | 0.2492 | 0.3724 | 333 |
| mlp/same_type | 0.1502 | 0.3381 | 0.3784 | 0.5646 | 333 |
| gold-distance/full | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 333 |
| gold-distance/pure_distance_full | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 333 |
| gold-distance/pure_distance_same_type | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 333 |
| gold-distance/same_type | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 333 |

Primary same-type top1 gain versus prospectively fixed frozen E-linear reference: {'bootstrap_roots': 333, 'ci95': [-0.06306306306306306, 0.030030030030030033], 'delta': -0.01501501501501501, 'repetitions': 2000, 'seed': 20261002}. The frozen linear and TinyMLP references remain distinct. This is a distillation trial against historical scalar references, not a controlled claim isolating every architecture/backend difference. Gold remaining-distance oracle requires expensive canonical planning. No selected target enters training.

The original oracle additionally restricts to canonical permission-qualified candidates. Pure-distance unrestricted gold variants are also shown: distance supervision alone does not encode policy permission, and ties/permission may limit logged-action ranking. The permission field is used for these oracle reports only, never in the estimator or its losses.

Candidate-count full/same-type ranking and denominator slices, renderer factor/ranking panels, and pair disagreement are fully retained in results.json. Only MOVE was reliability-supported in the frozen selected-action panel; other action claims are not promoted.

## Preservation

Qwen/E/goal checkpoints and existing full-bank production logits are byte-invariant before/after. The independent consequence optimizer contains no E or Qwen parameter. Goal BA, TRAIN-defined hard binding/globalization cells and renderer panels are repeated as unchanged metrics in results.json → preservation (3,000 DEV roots, both views). This is isolation/hash preservation, not a new goal-access training measurement.
- Sidecar candidate permutation equivariance passed for initialization and epoch8; candidate IDs are join-only.
- Estimator paired-render top1/value disagreement is reported for both initialization and trained outputs. Goal renderer behavior is untouched, not optimized by the new task.
- Known-solvable ordinal-gradient and full-status decoder controls passed. Input/cache, canonical targets, initialization/epoch8 outputs, metrics, dispositions and frozen-input identities have fresh-process verification.

## Final disposition

{'F': 'PARKED', 'automatic_escalation': False, 'comparator': False, 'conditional_order_gain_vs_init': {'bootstrap_roots': 136, 'ci95': [0.04042279411764714, 0.25024509803921563], 'delta': 0.1436274509803922, 'repetitions': 2000, 'seed': 20261002}, 'disposition': 'RETIRE_CONSEQUENCE_ORGAN_AS_CONSTRUCTED', 'distance_MAE_reduction': -0.07590961456298828, 'factor_qualified': False, 'legal_macro_recall_gain': -0.009469363499771469, 'ordering_qualified': True, 'ordering_support_reliable': False, 'ranking_qualified': False, 'same_type_top1_gain_vs_fixed_linear': {'bootstrap_roots': 333, 'ci95': [-0.06306306306306306, 0.030030030030030033], 'delta': -0.01501501501501501, 'repetitions': 2000, 'seed': 20261002}, 'warning': 'direct planner-supervision acquisition, not prior accessibility or a substrate ceiling'}

Factor acquisition, operational ranking acquisition, and legality-only filtering are kept distinct. No aggregate composite score. No automatic F, comparator, recurrence, LoRA or hidden-state search after failure.

## Costs and artifacts

TRAIN fit 126.85s, 672 optimizer steps, 164859 sidecar parameters, CPU FP32/four threads. Preparation/evaluation timing receipts record frozen-feature replay and per-row/candidate throughput; timings are on a shared host, not isolated microbenchmarks. No Qwen extraction or GPU reset occurred.
Checkpoint, target census, ABI, TRAIN weighting, journal, fixed output, preservation and replay hashes are bound by PHASE6C-SEALED.json. Source-v01 and its preparation failure remain preserved; source-v02 corrects only the comparison of unused padding and the historical permission-qualified oracle reference, without increasing tolerances or changing the estimator. Existing lineage and failed Phase6B engineering attempts remain untouched. Protected evaluation unopened.
