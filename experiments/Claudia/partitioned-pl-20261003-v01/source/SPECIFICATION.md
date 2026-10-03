# Claudia - partitioned Plackett-Luce ranking objective (frozen contract)

*Fresh re-run in `experiments/Claudia`; supersedes an earlier run built under the Frizz namespace. Nothing is written into any `frizz-*` directory.*

**Question (one sentence).** Does training the scorer on the actual ordered partition structure
(selected > other legal > illegal) recover more useful candidate ranking than ordinary selected-candidate CE?

Hypothesis under test: the frozen states carry useful candidate signal, but ordinary CE gives the wrong ordering geometry.
This isolates the **ranking likelihood** only: one boring candidate-independent scorer, no attention, recurrence, comparator,
LoRA, access organ or legality head.

## Data (BANK-v3-core synthetic-only, release `84f0a7e13032e8cdfcecc862217bb33ca23568fade64fafeef410327eb996f12`)

TRAIN 12,000 / DEV 3,000 canonical roots; endpoint-eligible EXECUTE roots 1,333 / 333; canonical primary rendering only;
protected evaluation never opened. The frozen trained-E inputs (Phase 6A caches) are consumed read-only and re-verified
(`INPUT-IDENTITY.json`: Phase 6B seal closure, Phase 6A seal-v02, sidecars, release/handoff chain).
**Training and evaluation population = the endpoint-eligible roots only** (1,333 TRAIN, 333 DEV): only they have a selected
candidate, hence a top partition. Every arm trains on exactly these roots.

Facts measured before design (TRAIN/DEV eligible): the selected candidate is always legal; legal-other group P2 has mean size
2.5, **maximum 8** (same-type maximum 3); illegal group P3 mean 60; 777/1,333 TRAIN roots have no same-type legal alternative.

## Candidate ABI (365 dims)

`x_j = [cs_j (320) ; e_j (32) ; action-type one-hot (9) ; argument-slot presence (4)]` with `cs_j = [c_j ; s]`. Presence is
`cand_ent >= 0`; entity/candidate IDs are join keys only. cs and e are standardised with TRAIN-only per-dimension statistics.
Never inputs: gold legality, selected/optimal identity, transition distance, simulator state, candidate position, protected truth.

## Scorer (all arms)

`Linear(365,128) - GELU - Linear(128,64) - GELU - Linear(64,1)` (55,169 parameters). One scalar utility per candidate,
candidate-independent. All arms start from the **same initial weights** (`build(seed)`; initial-weight hash recorded per arm).

## Objectives (L = 1.0 L_full + 0.5 L_same_type, root-mean; same supervision quantity for every arm)

* **A  ce** (control): L_full = softmax CE of the selected candidate over all valid candidates; L_same = CE over the candidates of the selected candidate's action type.
* **B  vanilla_pl**: conventional ListMLE. *Only one total order is legitimately identifiable from the labels (selected first), and ListMLE on it is mathematically identical to CE (unit-tested).* So the vanilla arm is the standard stochastic treatment of a partial order: ListMLE on a **uniformly random linear extension of the partition order, redrawn at every call** (selected first, then the other-legal candidates in random order, then the illegal candidates in random order). No tied candidates are ever sorted by any fixed rule.
* **C  partitioned_pl** (primary): the **exact** grouped Plackett-Luce likelihood of the ordered partition P1 = {selected/optimal} > P2 = other legal candidates > P3 = illegal candidates, marginalising every group's internal ordering exactly (log-space subset DP; the last group is the unordered remainder). L_same uses the same construction inside the selected candidate's action type. Empty partitions yield the valid reduced sequence. Selected and optimal coincide here and are **one** top partition (never double-counted).
* **supplementary vanilla_pl_truncated** (reference only; **not** part of the survival rule): ListMLE on a random linear extension kept only through the legal candidates (illegal tail left as an unordered remainder). Added to separate "random order among legal candidates" from "random order among illegal candidates".
* Gold legality builds the TRAIN partitions (arms B and C) and is never available at inference. **No legality head; no legality BCE.**

## Grouped-loss verification (before any interpretation; `test_pl.py`, `test_arms.py`, `test_partition.py`)

Brute-force enumeration of all orderings on tiny sets, values and autograd gradients: single candidate, two partitions, three
partitions, empty middle partition, all tied, one candidate per partition, group sizes 2/3/1, batched rows of different shapes;
candidate-permutation invariance; padding invariance; finite non-zero gradients; float32 behaviour at large score range; refusal (not
approximation) of oversized groups; last group never enumerated; ListMLE-on-selected-first == CE; vanilla draws are valid orders and
upper-bound the marginal; arm losses vs brute force; shared initial weights. Real-data invariance of every scorer (candidate order, padding).

## Training (fixed; no checkpoint selection)

Seed 0 (primary). 12 epochs, AdamW lr 3e-4, weight decay 0.01, grad clip 1.0, cosine to 0 per step (no warmup), root batch 32,
FP32, complete candidate sets, canonical candidate order, identical root order for all arms (per-epoch seeded permutation), identical
optimizer schedule and dose. Epoch 12 is the scored endpoint, scored on CPU/FP32 from the checkpoint. Every epoch is recorded;
nothing is selected on DEV.

## Evaluation (identical 333 eligible DEV roots; also eligible TRAIN for the generalisation wall)

Selected top1 / MRR / top3 / top5 / mean rank; gold-type top1 / MRR (diagnostic only, never an input); best-optimal rank and optimal
top1 / MRR; same-type selected-vs-alternative pair accuracy; candidate-count bands; per-action-type (support retained).
Partition diagnostics (full universe and same-type): selected > legal-other, selected > illegal, legal-other > illegal (pooled and
root-mean pair rates), legal-vs-illegal AUC, boundary rates P1>P2 and P2>P3, **reduced full ordering** (every existing boundary
holds) and **strict three-partition ordering** (all three non-empty; min/max formulation, identical to "all P1 > all P2 > all P3").
Paired canonical-root bootstrap, 2,000 resamples, seed 20261003: primary partitioned PL minus CE; also partitioned vs vanilla,
vanilla vs CE, and the supplementary reference.

## Pre-declared secondary diagnostic (outside the survival rule)

Because an earlier run showed the PL arms under-fitted on TRAIN at the primary dose, one extra dose is declared **before training** and run regardless of the primary
result: all four arms, lr 3e-3 and 60 epochs, everything else identical (`dose_diagnostic.py`, plan receipt `DOSE-DIAGNOSTIC-PLAN.json`). It answers only whether
TRAIN partition ordering can become strong and whether DEV follows; it never changes the disposition.

## Survival rule (prospective; on partitioned_pl minus ce)

SURVIVES if gold-type top1 delta >= +0.05 with paired 95% lower bound > 0, **or** gold-type MRR delta >= +0.03 with lower bound > 0,
**and** unrestricted selected top1 is not materially degraded (operationalised before any result as point-estimate delta >= -0.02).
If it survives: two confirmation seeds (1 and 2) under this frozen specification, no redesign. If not: finish diagnostics and seal;
**no** new partitions, weights or auxiliary losses afterwards. Failure means *this partitioned-PL construction on these frozen
states did not recover the residual*, not that ranking likelihoods are irrelevant.

## Deliverable

Sealed experiment: BANK identity, frozen-state hashes, candidate ABI, CE / vanilla PL / partitioned PL specifications, grouped-loss
unit tests, training receipts, ranking metrics, partition-order diagnostics, candidate-count slices, paired bootstrap, costs,
checkpoint hashes, fresh-process replay, final disposition. The next architecture is **not** started from this fan-out.
