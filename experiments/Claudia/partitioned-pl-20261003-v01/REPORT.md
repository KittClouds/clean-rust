# Claudia - partitioned Plackett-Luce ranking objective

Status: complete, seed 0 (primary) + one pre-declared secondary dose diagnostic. **Finding: `PARTITIONED_PL_SEED0_DOES_NOT_SURVIVE_LEARNS_COARSE_LEGALITY_ORDER_LOSES_SELECTED_VS_LEGAL_NO_CONFIRMATION`** (frozen rule output: `DOES_NOT_SURVIVE`). Fresh-process replay: **PASS** (primary), **PASS** (dose diagnostic). Protected evaluation unopened.

## Answer

> Does training the scorer on the actual ordered partition structure recover more useful candidate ranking than ordinary selected-candidate CE?

**No.** Under the frozen contract, partitioned PL did not improve gold-type ranking (top1 0.132 vs 0.141, delta -0.009, 95% CI [-0.042, +0.021]; MRR delta -0.003, CI [-0.026, +0.018]) and **materially degraded** unrestricted selected top1 (0.006 vs 0.084, delta -0.078, CI [-0.111, -0.048]). This is a statement about *this partitioned-PL construction on these frozen states and this scorer*, not about ranking likelihoods in general. No confirmation seeds were run and nothing was modified afterwards (the rule was not met).

What each objective actually learned (DEV, root-mean pair rates, 333 eligible roots):

| arm | selected > legal-other | selected > illegal | legal-other > illegal | all-legal > illegal (AUC) |
|---|---|---|---|---|
| A  CE (control) | 0.801 | 0.828 | 0.584 | 0.664 |
| B  vanilla PL | 0.278 | 0.787 | 0.853 | 0.823 |
| C  partitioned PL | 0.283 | 0.823 | 0.874 | 0.851 |
| supp. vanilla PL (truncated) | 0.286 | 0.825 | 0.874 | 0.852 |

Partitioned PL buys a large, **generalising** coarse-legality ordering (legal-other > illegal 0.874 vs CE 0.584; paired delta +0.290, CI [+0.267, +0.314]; TRAIN 0.885 so no wall here) **and pays for it with selected-vs-legal-other**: 0.283 vs 0.801 (delta -0.518, CI [-0.555, -0.482]). A rate well **below 0.5** means the scorer ranks other legal candidates above the selected one more often than not: the legality direction it learned is, on DEV, anti-aligned with the selection preference. Whole-root ordering (all P1 > all P2 > all P3) is essentially never achieved at the frozen dose (DEV 0.000).

## Frozen identities

- BANK-v3-core synthetic-only release `84f0a7e13032e8cdfcecc862217bb33ca23568fade64fafeef410327eb996f12`; corrected handoff `08cab38d366d6a30d32af4b0391cafddb243a8ea9e6a7435ad53290462d41a4b`.
- Frozen trained-E inputs (Phase 6A caches), consumed read-only and re-verified against the Phase 6B seal closure (530 artifacts) and the Phase 6A seal-v02:

| file | sha256 | verified against |
|---|---|---|
| E-trained-TRAIN.pt | d3aea5fa5cda6427... | phase6a_seal_v02, phase6b_specification_inputs, sidecar_receipt |
| E-trained-DEV.pt | acecf9b2250cb714... | phase6a_seal_v02, phase6b_specification_inputs, sidecar_receipt |
| TRAIN-targets.pt | 63aeafdcb554e4e9... | phase6a_seal_v02, sidecar_receipt |
| DEV-targets.pt | cb1f474e4e21c4cb... | phase6a_seal_v02, sidecar_receipt |
| TRAIN-dataset.pt | 336a550c1c8ae957... | sidecar_receipt, phase6a_specification_frozen_inputs |
| DEV-dataset.pt | a56d90e18f4932e5... | sidecar_receipt, phase6a_specification_frozen_inputs |

Canonical primary rendering only. Protected/EVAL files never opened. The standardiser is fitted on TRAIN only (`standardizer.json`).

## Specification (frozen before DEV scoring: `SPECIFICATION.json` / `.md`)

- **Candidate ABI** (365): `[cs 320; e 32; action-type one-hot 9; argument presence 4]`; IDs join-only; no distance/simulator/truth inputs.
- **Scorer** (all arms): `365->128->64->1`, GELU, candidate-independent, 55,169 parameters. **Identical initial weights** for all arms (sha `f609d0aedf094cca...` in every cost receipt).
- **A CE:** selected-candidate softmax CE + 0.5 x same-type CE.
- **B vanilla PL:** only one total order is identifiable from group labels (selected first) and ListMLE on it equals CE (unit-tested), so B is the conventional stochastic treatment: ListMLE on a fresh uniformly random linear extension of selected > legal-other > illegal at every call. No tied candidate is ever sorted by a fixed rule.
- **C partitioned PL:** exact grouped Plackett-Luce likelihood of P1 {selected} > P2 {other legal} > P3 {illegal}, internal orders marginalised exactly (log-space subset DP; |P2| <= 8 on this bank), + 0.5 x the same construction inside the selected candidate's action type. Selected and optimal coincide here and are one top partition.
- **Supplementary (outside the survival rule):** vanilla PL truncated after the legal candidates, to separate random order among legal candidates from random order among the illegal tail.
- **Training:** seed 0, 12 epochs, AdamW 3e-4 / wd 0.01, clip 1.0, cosine, root batch 32, FP32, identical root order and dose, training on the 1,333 endpoint-eligible TRAIN roots (504 steps); epoch 12 scored on CPU/FP32; no checkpoint selection. No legality head or BCE.

## Grouped-loss verification (before any interpretation)

34 passed, 1 warning in 7.87s. Brute-force enumeration of all orderings (values **and** autograd gradients) for: single candidate, two partitions, three partitions, empty middle partition, all tied, one candidate per partition, group sizes 2/3/1, batched rows of different partition shapes; candidate-permutation invariance; padding invariance; finite non-zero gradients; float32 at large score range; oversized groups refused rather than approximated; selected-first ListMLE == CE; vanilla draws are valid total orders that upper-bound the marginal and never reduce to a fixed sort; arm losses vs brute force; shared initial weights; partition metrics on hand-computed cases.

A bug was found and fixed during the pre-freeze rehearsal (the DP was being run on the final 122-member illegal group, which has probability 1 and needs no enumeration); a regression test was added. A second rehearsal check showed partitioned PL can fit a 67-root set perfectly (top1, legal>illegal and full ordering all 1.0) while CE left legal>illegal at 0.64 - the objective and its orientation are right.

Real-data scorer invariance (candidate order, padding; FP32 shown, FP64 also passed; overall: PASS):

| arm:epoch:split:dtype | roots | candidate-permutation diff | alone vs padded batch | padded-slot garbage | result |
|---|---|---|---|---|---|
| ce:epoch00:TRAIN:float32 | 120 | 0.0e+00 | 3.0e-08 | 0.0e+00 | PASS |
| ce:epoch00:DEV:float32 | 120 | 0.0e+00 | 3.0e-08 | 0.0e+00 | PASS |
| ce:epoch12:TRAIN:float32 | 120 | 0.0e+00 | 3.8e-06 | 0.0e+00 | PASS |
| ce:epoch12:DEV:float32 | 120 | 0.0e+00 | 1.9e-06 | 0.0e+00 | PASS |
| vanilla_pl:epoch00:TRAIN:float32 | 120 | 0.0e+00 | 3.0e-08 | 0.0e+00 | PASS |
| vanilla_pl:epoch00:DEV:float32 | 120 | 0.0e+00 | 3.0e-08 | 0.0e+00 | PASS |
| vanilla_pl:epoch12:TRAIN:float32 | 120 | 0.0e+00 | 2.4e-07 | 0.0e+00 | PASS |
| vanilla_pl:epoch12:DEV:float32 | 120 | 0.0e+00 | 3.0e-08 | 0.0e+00 | PASS |
| partitioned_pl:epoch00:TRAIN:float32 | 120 | 0.0e+00 | 3.0e-08 | 0.0e+00 | PASS |
| partitioned_pl:epoch00:DEV:float32 | 120 | 0.0e+00 | 3.0e-08 | 0.0e+00 | PASS |
| partitioned_pl:epoch12:TRAIN:float32 | 120 | 0.0e+00 | 4.8e-07 | 0.0e+00 | PASS |
| partitioned_pl:epoch12:DEV:float32 | 120 | 0.0e+00 | 4.8e-07 | 0.0e+00 | PASS |
| vanilla_pl_truncated:epoch00:TRAIN:float32 | 120 | 0.0e+00 | 3.0e-08 | 0.0e+00 | PASS |
| vanilla_pl_truncated:epoch00:DEV:float32 | 120 | 0.0e+00 | 3.0e-08 | 0.0e+00 | PASS |
| vanilla_pl_truncated:epoch12:TRAIN:float32 | 120 | 0.0e+00 | 7.2e-07 | 0.0e+00 | PASS |
| vanilla_pl_truncated:epoch12:DEV:float32 | 120 | 0.0e+00 | 7.2e-07 | 0.0e+00 | PASS |

## Denominators

| quantity | value |
|---|---|
| TRAIN roots / endpoint-eligible (training population) | 12,000 / 1,333 |
| DEV roots / endpoint-eligible (evaluation population) | 3,000 / 333 |
| same-type selected-vs-alternative pairs DEV | 3,180 (332 roots) |
| legal-other group size (mean / max) | 2.5 / 8 (same-type max 3) |
| roots with no same-type legal alternative (TRAIN) | 777 of 1,333 |

## Primary ranking comparison (333 eligible DEV roots, epoch 12, CPU/FP32)

| arm | top1 | top3 | top5 | MRR | mean rank | gold-type top1 | gold-type MRR | optimal top1 / MRR | same-type pair acc |
|---|---|---|---|---|---|---|---|---|---|
| A  CE (control) | 0.084 | 0.240 | 0.375 | 0.236 | 11.1 | 0.141 | 0.330 | 0.084 / 0.236 | 0.533 |
| B  vanilla PL | 0.003 | 0.153 | 0.324 | 0.164 | 14.6 | 0.132 | 0.326 | 0.003 / 0.164 | 0.536 |
| C  partitioned PL | 0.006 | 0.165 | 0.324 | 0.171 | 12.3 | 0.132 | 0.327 | 0.006 / 0.171 | 0.541 |
| supp. vanilla PL (truncated) | 0.009 | 0.168 | 0.330 | 0.173 | 12.2 | 0.129 | 0.326 | 0.009 / 0.173 | 0.541 |
| uniform chance | 0.019 |  |  |  |  | 0.114 | 0.310 |  | 0.500 |
| context: Phase 6A best independent scorer | 0.090 |  |  | 0.241 |  | 0.153 | 0.339 |  |  |

Gold-type restriction is diagnostic only. Optimal-set and selected endpoints coincide on this population (one bank property, not two confirmations). Gold-type chance is the restricted-universe value (mean 10.5 same-type candidates).

Paired canonical-root bootstrap (2,000 resamples), 333 roots. Primary row: C minus A.

| comparison | selected top1 | selected MRR | gold-type top1 (primary) | gold-type MRR | same-type pair acc |
|---|---|---|---|---|---|
| partitioned_pl - ce | -0.078 [-0.111, -0.048] | -0.065 [-0.087, -0.045] | -0.009 [-0.042, +0.021] | -0.003 [-0.026, +0.018] | +0.005 [-0.020, +0.030] |
| partitioned_pl - vanilla_pl | +0.003 [+0.000, +0.009] | +0.008 [-0.001, +0.017] | +0.000 [-0.033, +0.033] | +0.001 [-0.020, +0.023] | +0.005 [-0.016, +0.027] |
| vanilla_pl - ce | -0.081 [-0.114, -0.051] | -0.073 [-0.095, -0.052] | -0.009 [-0.048, +0.024] | -0.004 [-0.033, +0.021] | +0.000 [-0.030, +0.031] |
| partitioned_pl - vanilla_pl_truncated | -0.003 [-0.009, +0.000] | -0.002 [-0.006, -0.000] | +0.003 [+0.000, +0.009] | +0.001 [-0.003, +0.005] | -0.002 [-0.006, +0.002] |
| vanilla_pl_truncated - ce | -0.075 [-0.108, -0.045] | -0.063 [-0.085, -0.043] | -0.012 [-0.045, +0.018] | -0.004 [-0.027, +0.019] | +0.007 [-0.018, +0.033] |

Partition-order paired deltas (root-mean pair rates):

| comparison | selected>legal-other | selected>illegal | legal-other>illegal | same-type sel>legal-other | same-type legal-other>illegal |
|---|---|---|---|---|---|
| partitioned_pl - ce | -0.518 [-0.555, -0.482] | -0.005 [-0.024, +0.015] | +0.290 [+0.267, +0.314] | +0.019 [-0.029, +0.067] | +0.000 [-0.028, +0.029] |
| partitioned_pl - vanilla_pl | +0.005 [-0.011, +0.021] | +0.036 [+0.020, +0.053] | +0.021 [+0.012, +0.029] | +0.021 [-0.034, +0.081] | -0.016 [-0.049, +0.016] |
| vanilla_pl - ce | -0.523 [-0.561, -0.488] | -0.041 [-0.065, -0.016] | +0.269 [+0.243, +0.294] | -0.002 [-0.070, +0.061] | +0.017 [-0.023, +0.058] |

Survival rule on C - A: gold-type top1 criterion False, gold-type MRR criterion False, selected top1 not materially degraded (point delta >= -0.02) False -> **DOES_NOT_SURVIVE**.

## Partition-order diagnostics (frozen-dose primary run)

**DEV** (eligible roots; roots with the relevant partitions: P1>P2 333, P2>P3 333):

| arm | sel>legal | sel>illeg | legal>illeg | ST sel>legal | ST sel>illeg | ST legal>illeg | P1>P2 boundary | P2>P3 boundary | reduced full order | strict 3-partition |
|---|---|---|---|---|---|---|---|---|---|---|
| A  CE (control) | 0.801 | 0.828 | 0.584 | 0.511 | 0.511 | 0.474 | 0.604 | 0.000 | 0.000 | 0.000 |
| B  vanilla PL | 0.278 | 0.787 | 0.853 | 0.509 | 0.512 | 0.490 | 0.003 | 0.261 | 0.000 | 0.000 |
| C  partitioned PL | 0.283 | 0.823 | 0.874 | 0.530 | 0.516 | 0.474 | 0.012 | 0.249 | 0.000 | 0.000 |
| supp. vanilla PL (truncated) | 0.286 | 0.825 | 0.874 | 0.522 | 0.519 | 0.477 | 0.015 | 0.243 | 0.003 | 0.003 |

**TRAIN** (eligible roots; roots with the relevant partitions: P1>P2 1332, P2>P3 1332):

| arm | sel>legal | sel>illeg | legal>illeg | ST sel>legal | ST sel>illeg | ST legal>illeg | P1>P2 boundary | P2>P3 boundary | reduced full order | strict 3-partition |
|---|---|---|---|---|---|---|---|---|---|---|
| A  CE (control) | 0.973 | 0.983 | 0.627 | 0.844 | 0.884 | 0.633 | 0.926 | 0.000 | 0.001 | 0.000 |
| B  vanilla PL | 0.432 | 0.964 | 0.861 | 0.774 | 0.821 | 0.646 | 0.000 | 0.260 | 0.001 | 0.000 |
| C  partitioned PL | 0.468 | 0.972 | 0.885 | 0.809 | 0.862 | 0.668 | 0.066 | 0.252 | 0.020 | 0.019 |
| supp. vanilla PL (truncated) | 0.477 | 0.972 | 0.885 | 0.810 | 0.862 | 0.665 | 0.086 | 0.252 | 0.024 | 0.023 |

"All P1 > all P2 > all P3" and the min/max formulation (min(P1) > max(P2) and min(P2) > max(P3)) are the same event for sets, so one number is reported; the reduced version applies only the boundaries that exist for a root (empty partitions removed), the strict version needs all three partitions non-empty.

## Candidate-count bands (descriptive; no band reaches the 200-root floor)

| candidates | eligible roots | A  CE (control) top1 / gold-type top1 | B  vanilla PL top1 / gold-type top1 | C  partitioned PL top1 / gold-type top1 | supp. vanilla PL (truncated) top1 / gold-type top1 |
|---|---|---|---|---|---|
| 1-28 | 17 | 0.059 / 0.059 | 0.000 / 0.118 | 0.000 / 0.118 | 0.000 / 0.118 |
| 29-64 | 187 | 0.096 / 0.144 | 0.000 / 0.123 | 0.000 / 0.128 | 0.000 / 0.128 |
| 65-128 | 128 | 0.070 / 0.148 | 0.008 / 0.148 | 0.016 / 0.141 | 0.023 / 0.133 |
| 129-171 | 1 | 0.000 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 |

In the two bands with real mass (29-64, 65-128) the PL arms lose unrestricted top1 (near 0) and are within noise of CE on gold-type top1 (0.128/0.141 vs 0.144/0.148 for partitioned vs CE). The 1-28 band has 17 roots (gold-type top1 0.118 vs 0.059 is 2 vs 1 root) and the 129-171 band 1 root; neither supports a claim.

Per action type (only MOVE, 249 roots, reaches the 200-root floor): gold-type top1 for CE / vanilla / partitioned on MOVE: 0.120 / 0.120 / 0.116. Other types are descriptive only.

## Training dynamics (frozen dose; recorded every epoch, never used for selection)

| epoch | CE loss | CE TRAIN top1 | CE TRAIN full-order | CE DEV top1 | partitioned loss | partitioned TRAIN top1 | partitioned TRAIN full-order | partitioned DEV top1 | vanilla loss | vanilla TRAIN top1 | vanilla TRAIN full-order | vanilla DEV top1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 4.01 | 0.311 | 0.000 | 0.087 | 11.34 | 0.001 | 0.001 | 0.003 | 213.80 | 0.001 | 0.001 | 0.003 |
| 2 | 2.69 | 0.482 | 0.001 | 0.084 | 9.90 | 0.001 | 0.001 | 0.003 | 212.95 | 0.001 | 0.001 | 0.003 |
| 4 | 1.97 | 0.548 | 0.001 | 0.072 | 9.48 | 0.039 | 0.011 | 0.006 | 213.11 | 0.001 | 0.001 | 0.003 |
| 8 | 1.81 | 0.577 | 0.001 | 0.084 | 9.20 | 0.060 | 0.019 | 0.006 | 213.21 | 0.001 | 0.001 | 0.003 |
| 12 | 1.77 | 0.584 | 0.001 | 0.084 | 9.14 | 0.064 | 0.020 | 0.006 | 213.25 | 0.001 | 0.001 | 0.003 |

At the frozen dose the PL arms are **under-fitted on TRAIN itself** (partitioned PL loss plateaus near 9; TRAIN full ordering 0.02) because the objective demands all ~60 illegal candidates fall below every legal one, a coarse legality partition these frozen features express only weakly. CE fits the single selected target quickly (TRAIN top1 0.58).

## Secondary dose-sensitivity diagnostic (pre-declared in the specification; outside the survival rule)

`DOSE-DIAGNOSTIC-PLAN.json` fixed one dose before running: 10x learning rate (3e-3) and 5x epochs (60), everything else identical, all four arms, no tuning, no DEV-based choice. It was triggered by the primary run's TRAIN under-fit, which left the outcome "TRAIN partition ordering strong, DEV weak" unassessable. It does **not** change the disposition.

| arm (lr 3e-3, 60 ep) | TRAIN top1 | TRAIN full-order | TRAIN legal>illeg | DEV top1 | DEV gold-type top1 | DEV MRR | DEV sel>legal | DEV legal>illeg | DEV full-order |
|---|---|---|---|---|---|---|---|---|---|
| A  CE (control) | 0.991 | 0.001 | 0.581 | 0.075 | 0.114 | 0.225 | 0.799 | 0.548 | 0.000 |
| B  vanilla PL | 0.267 | 0.093 | 0.891 | 0.015 | 0.135 | 0.172 | 0.294 | 0.847 | 0.006 |
| C  partitioned PL | 0.962 | 0.954 | 1.000 | 0.024 | 0.099 | 0.145 | 0.303 | 0.836 | 0.006 |
| supp. vanilla PL (truncated) | 0.878 | 0.792 | 0.998 | 0.030 | 0.114 | 0.146 | 0.285 | 0.836 | 0.006 |

With enough dose, partitioned PL **does** learn the partition structure on TRAIN (top1 0.96, full ordering 0.95, legal>illegal 1.00) - and DEV stays at the floor: gold-type top1 -0.015 vs CE (CI [-0.060, +0.027]; PL gold-type top1 is below the 0.114 within-type chance), selected top1 -0.051 (CI [-0.084, -0.021]), DEV full ordering 0.006. The selected-vs-legal-other rate stays near 0.30 on DEV even when TRAIN is 0.97, so the anti-alignment is not a dose artefact. CE at this dose also memorises TRAIN (0.99) and DEV does not move. This is the "TRAIN partition ordering strong, DEV weak - same generalization wall" outcome, here for the ranking head.

## Cost

| arm | parameters | train s (12 ep) | train s (dose diag., 60 ep) | peak CUDA MB | steps |
|---|---|---|---|---|---|
| A  CE (control) | 55,169 | 5 | 23 | 293 | 504 |
| B  vanilla PL | 55,169 | 8 | 39 | 293 | 504 |
| C  partitioned PL | 55,169 | 73 | 353 | 293 | 504 |
| supp. vanilla PL (truncated) | 55,169 | 8 | 37 | 293 | 504 |

Device NVIDIA GeForce RTX 3080; FP32. The exact grouped-PL loss costs 16x the CE arm's training time (a Python-level subset DP over <= 256 states), still under two minutes. CPU scoring: sub-second.

## Outcome catalogue

| pre-listed outcome | observed |
|---|---|
| PL improves selected-vs-legal but not legal-vs-illegal | no - the opposite |
| PL improves legal-vs-illegal strongly but not selected-vs-legal | **yes**, and worse: legal>illegal 0.58 -> 0.87, selected>legal 0.80 -> 0.28 |
| partitioned PL > vanilla PL (ties/partial order matter) | barely: legal>illegal +0.021; top1, MRR, gold-type, pair accuracy indistinguishable |
| vanilla PL ~ partitioned PL (tie structure not limiting) | **mostly yes** (also vs the truncated vanilla: all primary differences <= 0.003) |
| partitioned PL ~ CE (geometry not enough) | gold-type metrics yes; unrestricted top1 no (PL much worse) |
| TRAIN partition ordering strong, DEV weak | **yes** at the secondary dose (TRAIN 0.95, DEV 0.006); not assessable at the frozen dose (TRAIN 0.02) |

## What this does and does not conclude

- Concluded: with a small candidate-independent scorer on the frozen trained-E states, an exact grouped-PL objective teaches a generalising legality ordering but not a within-type or selected-vs-legal preference; the hypothesis "ordinary CE gives the wrong ordering geometry for a signal the model already has" is not supported here. Tie handling (exact marginalisation vs random linear extensions) did not matter.
- Not concluded: that different weights between the partition terms, a larger or interacting scorer, or other ranking likelihoods would fail (the contract fixed the weights and forbids adding auxiliaries); anything about other seeds (none run: the rule was not met); anything about unseen renderings.
- Caveats: (a) 1,333 training roots and 333 evaluation roots (CI half-width ~ +/-3 pp); (b) the partitions use gold legality at TRAIN time only (as specified); (c) the dose diagnostic is a pre-declared secondary check and single-dose; (d) the cause of the below-chance selected-vs-legal-other rate is described, not diagnosed; (e) the vanilla arm's definition is a documented design decision (only the selected-first order is identifiable, and on it vanilla = CE); (f) candidate-count bands and non-MOVE action types are below the 200-root floor.
- The next architecture is **not** started from this fan-out.

## Artifacts

| arm |  | sha256 |  | sha256 |
|---|---|---|---|---|
| A  CE (control) | epoch 0 | bb8d5f8f57e5fae6e819... | epoch 12 (scored) | afbb3b761e1622b59474... |
| B  vanilla PL | epoch 0 | cc79bfb87abdef1ef79c... | epoch 12 (scored) | 39d30a0e463d82288822... |
| C  partitioned PL | epoch 0 | f39a59ffa4f384473bc7... | epoch 12 (scored) | 70f8fbc5895a9a050cf8... |
| supp. vanilla PL (truncated) | epoch 0 | dbe37d838f7adf422954... | epoch 12 (scored) | 59560e3b8c981ed9b881... |

`SPECIFICATION.json` (frozen before DEV scoring) - `INPUT-IDENTITY.json` - `ENGINEERING-RECEIPT.json` - `runs/seed0/` (checkpoints, scores, metrics, `COMPARISON.json`, `INVARIANCE-QUALIFICATION.json`, `REPLAY.json`) - `DOSE-DIAGNOSTIC-PLAN.json` / `DOSE-DIAGNOSTIC.json` / `DOSE-DIAGNOSTIC-REPLAY.json` / `dose-diagnostic/` - `CONTEXT.json` - `DISPOSITION.json` - `ANALYSIS-ADDENDUM.json` - `SEALED.json`.
