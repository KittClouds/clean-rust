# Frizz Phase 7A — SetRank-style permutation-equivariant candidate ranker (frozen contract)

**Question (one sentence).** Does letting candidates explicitly see one another (full set self-attention) solve more of
the ranking problem than a matched independent per-candidate scorer?

Independent scoring: `s_j = f(x_j)`. Set scoring: `h_1..h_N = SetAttention(x_1..x_N); s_j = f(h_j)`. Nothing else changes.
No Plackett-Luce, recurrence, LoRA, stochastic transitions, graph inference or access organ. Not an architecture search.

## Data (BANK-v3-core, synthetic-only, release `84f0a7e13032e8cdfcecc862217bb33ca23568fade64fafeef410327eb996f12`)

* TRAIN 12,000 canonical roots; DEV 3,000. Endpoint-eligible EXECUTE roots 1,333 / 333. Exhaustive variable-width candidate
  sets, maximum 171. Same-type selected-vs-alternative pairs 11,883 / 3,180 (332 DEV roots have at least one).
* Canonical primary rendering only (the only rendering with sealed state caches). A root is the statistical unit.
* Protected evaluation is never opened. No LFM / Qwen regeneration. The paired-render nuisance check is **not run**: no sealed
  paired-render state caches exist and the task forbids regenerating them.
* Frozen consumed inputs (verified in `INPUT-IDENTITY.json` against the Phase 6B seal closure, the Phase 6A seal-v02, sidecar
  receipts and the release/handoff chain): `E-trained-{TRAIN,DEV}.pt`, `{TRAIN,DEV}-targets.pt`, bridge `{TRAIN,DEV}-dataset.pt`.

## Candidate token ABI (365 dims)

`x_j = [cs_j (320) ; e_j (32) ; action-type one-hot (9) ; argument-slot presence (4)]`

* `cs_j = [c_j (256) ; s (64)]` — the Phase 6A/6B "cs" surface of the trained-E cache (candidate state + shared root-context state).
* `e_j` — trained-E integrated state (32). The trained-E arrays are bound by name (`c`, `s`, `e`), not re-derived.
* type — canonical action type (observable, from the candidate text). presence — `cand_ent >= 0` per slot. **Entity IDs are
  never features**; candidate IDs and positions are join keys only.
* `cs` and `e` are standardised with TRAIN-only per-dimension statistics, identically for both arms.
* **Never inputs:** gold legality, satisfies-goal, selected/optimal identity, transition distance, simulator state, protected truth.

## Architecture (both arms share everything except the mixing sub-layer)

Input `Linear(365,128)` -> 2 pre-LayerNorm residual blocks (d=128, GELU, FF 256) -> final LayerNorm -> utility head `128->1`
and legality head `128->1`. **No positional or candidate-index encoding.**

* **SetRank:** block = `x + MHSA(LN x)` (4 heads x 32, key-padding mask, no causal mask, dense N^2) then `x + FFN256(LN x)`.
* **Pointwise control:** block = `x + FFN256(LN x)` (candidate-independent, replaces attention) then `x + FFN256(LN x)`.
  Parameters 312,322 vs 312,066 (0.08 %). Same projection, heads, optimizer, batches, supervision, root order and permutation stream.

## Supervision (identical for both arms)

`L = 1.00 L_select + 0.50 L_same_type + 0.25 L_legality`

* `L_select`: softmax CE of the logged selected candidate over **all** valid candidates (eligible TRAIN roots).
* `L_same_type`: CE over candidates sharing the selected candidate's action type (roots with >= 1 alternative).
* `L_legality`: independent legality head, root-normalised balanced BCE (each root's positives and negatives carry equal total
  weight; every root contributes equally regardless of candidate count). Gold legality **never** masks the utility softmax.
* No optimal-set head (selected == optimal singleton on this population; endpoint contracts are evaluated separately).

## Training (fixed; no checkpoint selection)

Seed 0 · 12 epochs · AdamW lr 3e-4, weight decay 0.01 · grad clip 1.0 · cosine to 0 per step, no warmup · root batch 16 ·
FP32 · complete candidate sets per batch (never split) · padding in neither attention nor losses · roots and within-root
candidate order shuffled independently, both arms consume identical streams · **epoch 12 is the scored endpoint**, scored on CPU/FP32
from the checkpoint. Initialisation and every epoch are recorded (checkpoint, DEV/TRAIN monitoring) but never used to choose anything.

## Qualification (before any interpretation)

Permutation equivariance `F(PX) = P F(X)` for utility and legality logits, and unpermuted top-k / selected top1 / legality
decisions, on a stratified sample of TRAIN and DEV roots, 6 permutations each, FP32 (tol 1e-4) and FP64 (tol 1e-9), at
initialisation and epoch 12, both arms. Padding invariance (root alone == root in padded batch; garbage in padded slots inert).
A positional negative-control model must fail the same detector (unit test). Failure here = engineering defect: repair and rerun
before interpreting anything.

## Evaluation (identical 333 eligible DEV roots; DEV never used for any choice)

Selected top1 / MRR / top3 / top5 / mean rank; gold-type-restricted top1 / MRR (diagnostic only, never an input); optimal-set
top1 / MRR (separate contract); same-type selected-vs-alternative pair accuracy (exhaustive); candidate-count bands
1-28 / 29-64 / 65-128 / 129-171; per-action-type values with support counts (only MOVE reaches the 200-root floor; others descriptive).
Legality sidecar: candidate BA / precision / recall / F1, exact legal-set recovery (full and same-type), root mean Jaccard,
false positives / negatives per root, selected-candidate retention. Paired bootstrap (2,000 root resamples, seed 20261003)
SetRank minus control for selected top1, MRR, gold-type top1, legality exact-set recovery (+ MRR gold-type, pair accuracy).
Attention diagnostics (descriptive, not causal): entropy per layer/head, same/different-type mass vs base rate,
selected->legal/illegal mass, candidate-count dependence, representation change `||h^L - h^0||`.

## Survival rule (prospective)

* **STRONG** — gold-type top1 delta >= +0.05 **and** paired 95 % lower bound > 0.
* **PRESERVE** — not STRONG, but gold-type MRR delta >= +0.03 with lower bound > 0 **and** gold-type top1 delta >= 0
  (this operationalises "substantial MRR improvement with non-degrading top1" before any result exists).
* Otherwise **FLAT_OR_NEGATIVE**: finish diagnostics, seal, do not widen (no extra heads, no PL, no search).
* STRONG/PRESERVE only licenses two confirmation seeds under this frozen specification, no redesign.
* A failure means *this SetRank construction did not recover the residual* — not that set attention is useless.
* Training ranking improving while the permutation test fails = engineering defect.

## Deliverable

Sealed experiment: BANK identity, consumed-cache hashes, token ABI, both specifications, training contract, equivariance tests,
all denominators, ranking / gold-type / legality-set metrics, candidate-count slices, paired bootstrap, attention diagnostics,
parameter counts, runtime/memory, checkpoints + hashes, fresh-process replay, final disposition. The next architecture is **not**
started from this fan-out.
