# Frizz Phase 7A - SetRank-style permutation-equivariant candidate ranker

Status: complete, seed 0 only. **Finding: `SETRANK_SEED0_BELOW_SURVIVAL_RULE_NO_CONFIRMATION_NO_WIDENING`** (frozen rule output: `FLAT_OR_NEGATIVE`). Fresh-process replay: **PASS**. Protected evaluation unopened.

## Answer

> Does letting candidates explicitly see one another solve more of the ranking problem than a matched independent scorer?

**Only marginally, and not by the frozen standard.** The SetRank arm beats its matched pointwise control by **+3.6 pp gold-type top1** (95% root-bootstrap CI [+0.3, +6.9] pp), which is short of the +5 pp threshold; unrestricted top1 (+2.1 pp), MRR (+0.010) and gold-type MRR (+0.020) all have intervals containing 0. Within-type pair accuracy is 0.544 vs 0.536 and the legality sets are unrecovered by both arms. This is a statement about *this SetRank construction on these frozen states*, not about set attention in general. No confirmation seeds, no widening.

Three framing points the headline number hides:

1. **Absolute level is near chance.** Within-type uniform top1 on these 333 roots is 0.114 (MRR 0.310). SetRank gold-type top1 is 0.159 (MRR 0.343); the pointwise control is 0.123 (MRR 0.324) - essentially chance.
2. **SetRank only reaches the level of the older sealed independent scorers; it does not exceed them.** The best Phase 6A independent scorer on the same states (E trained e-linear) has gold-type top1 0.1532 / MRR 0.3391 and unrestricted top1 0.0901 / MRR 0.2407; SetRank is 0.1592 / 0.3431 and 0.1051 / 0.2490. The matched pointwise MLP control is *below* those simple scorers, so part of the paired gap is the control under-performing, not SetRank over-performing.
3. **Both arms memorise TRAIN and do not transfer.** TRAIN selected top1 0.802 (SetRank) / 0.707 (control) vs DEV 0.105 / 0.084; TRAIN same-type pair accuracy 0.950 / 0.930 vs DEV 0.544 / 0.536. A likely mechanism (not tested here): the upstream E states were themselves trained on TRAIN, so TRAIN states may carry TRAIN-specific selection information that DEV states do not. Whatever the cause, this train/DEV gap comes with the frozen-feature design; this experiment did not change it.

## Frozen identities

- BANK-v3-core synthetic-only release `84f0a7e13032e8cdfcecc862217bb33ca23568fade64fafeef410327eb996f12`; corrected handoff `08cab38d366d6a30d32af4b0391cafddb243a8ea9e6a7435ad53290462d41a4b`; release manifest `2033aabd67bce5a018a32ee7417cf2b282c8bb269419ba2458a320b59002524d`.
- Phase 6B seal `7f274c53b7cb5ab6edeaedcae20044c8380d61bcbea28a3157dd272de914ff01` (all 530 sealed artifacts re-hashed; disposition `BOUNDED_FROZEN_SURFACE_ACCESSIBILITY_LIMIT_NO_NEW_ORGAN`); Phase 6A seal-v02 `84b91d45a4f46da122a5b2dae22384b7d2fb07d0fd39cf3c07fba556172db0a8`.
- Consumed (each verified against the Phase 6A seal-v02, the Phase 6B specification inputs where listed, and its sidecar receipt):

| file | sha256 | size | verified against |
|---|---|---|---|
| E-trained-TRAIN.pt | d3aea5fa5cda6427... | 1202 MB | phase6a_seal_v02, phase6b_specification_inputs, sidecar_receipt |
| E-trained-DEV.pt | acecf9b2250cb714... | 301 MB | phase6a_seal_v02, phase6b_specification_inputs, sidecar_receipt |
| TRAIN-targets.pt | 63aeafdcb554e4e9... | 31 MB | phase6a_seal_v02, sidecar_receipt |
| DEV-targets.pt | cb1f474e4e21c4cb... | 8 MB | phase6a_seal_v02, sidecar_receipt |
| TRAIN-dataset.pt | 336a550c1c8ae957... | 1172 MB | sidecar_receipt, phase6a_specification_frozen_inputs |
| DEV-dataset.pt | a56d90e18f4932e5... | 293 MB | sidecar_receipt, phase6a_specification_frozen_inputs |

The trained-E state caches physically live in the Phase 6A directory (the Phase 6B directory holds gold-relation and probe-panel artifacts, none of which are consumed); the Phase 6B specification lists the same cache hashes as its own frozen inputs, which is how the binding to that experiment is checked. Semantic binding: `c` (256) and `s` (64) form the 320-d `cs`; `e` is the 32-d integrated state - exactly the Phase 6A `features(cache, "cs"|"e")` definitions.

Not run: the paired-render nuisance check (no sealed paired-render state caches exist; Qwen is not regenerated). Protected/EVAL files: never opened.

## Specification (frozen before any DEV scoring: `SPECIFICATION.json`/`.md`)

- **Token** (365): `[cs 320; e 32; action-type one-hot 9; argument-slot presence 4]`; presence = `cand_ent >= 0`; entity IDs never features; TRAIN-only standardisation of cs/e.
- **SetRank:** Linear 365->128, 2 pre-LN blocks (4 heads x 32, dense key-padded self-attention, FFN 256 GELU), final LN, utility head 128->1, legality head 128->1; no positional/index encoding.
- **Control:** identical, but each attention sub-layer is replaced by a candidate-independent FFN(128->256->128).
- **Parameters:** SetRank 312,322; control 312,066 (0.08% apart).
- **Loss:** 1.0 full-set selected CE + 0.5 same-type selected CE + 0.25 root-normalised balanced legality BCE; gold legality never masks the softmax.
- **Training:** seed 0, 12 epochs, AdamW 3e-4 / wd 0.01, clip 1.0, cosine per step, root batch 16, FP32, complete candidate sets, within-root permutation augmentation; both arms consume identical root-order and permutation streams; epoch 12 scored on CPU/FP32; no checkpoint selection.

## Permutation-equivariance qualification (passed before interpretation)

| arm:epoch:split:dtype | roots | perm checks | max |d utility| | max |d legality| | top1 mism. | top5 mism. | decision mism. | padding diff | result |
|---|---|---|---|---|---|---|---|---|---|
| set:epoch00:TRAIN:float32 | 200 | 1200 | 7.15e-07 | 8.34e-07 | 0 | 0 | 0 | 1.8e-07 | PASS |
| set:epoch00:TRAIN:float64 | 200 | 1200 | 1.55e-15 | 1.78e-15 | 0 | 0 | 0 | 1.3e-15 | PASS |
| set:epoch00:DEV:float32 | 200 | 1200 | 7.15e-07 | 8.34e-07 | 0 | 0 | 0 | 3.0e-07 | PASS |
| set:epoch00:DEV:float64 | 200 | 1200 | 2.00e-15 | 2.00e-15 | 0 | 0 | 0 | 1.4e-15 | PASS |
| set:epoch12:TRAIN:float32 | 200 | 1200 | 1.76e-05 | 2.86e-06 | 0 | 0 | 0 | 1.9e-06 | PASS |
| set:epoch12:TRAIN:float64 | 200 | 1200 | 4.20e-14 | 5.33e-15 | 0 | 0 | 0 | 1.6e-14 | PASS |
| set:epoch12:DEV:float32 | 200 | 1200 | 2.56e-05 | 2.86e-06 | 0 | 0 | 0 | 1.9e-06 | PASS |
| set:epoch12:DEV:float64 | 200 | 1200 | 6.13e-14 | 1.15e-14 | 0 | 0 | 0 | 3.6e-14 | PASS |
| pointwise:epoch00:TRAIN:float32 | 200 | 1200 | 3.58e-07 | 4.77e-07 | 0 | 0 | 0 | 1.3e-07 | PASS |
| pointwise:epoch00:TRAIN:float64 | 200 | 1200 | 2.22e-15 | 2.55e-15 | 0 | 0 | 0 | 1.8e-15 | PASS |
| pointwise:epoch00:DEV:float32 | 200 | 1200 | 3.58e-07 | 4.77e-07 | 0 | 0 | 0 | 2.1e-07 | PASS |
| pointwise:epoch00:DEV:float64 | 200 | 1200 | 2.03e-15 | 2.55e-15 | 0 | 0 | 0 | 1.9e-15 | PASS |
| pointwise:epoch12:TRAIN:float32 | 200 | 1200 | 5.72e-06 | 1.43e-06 | 0 | 0 | 0 | 3.8e-06 | PASS |
| pointwise:epoch12:TRAIN:float64 | 200 | 1200 | 1.95e-14 | 4.44e-15 | 0 | 0 | 0 | 1.1e-14 | PASS |
| pointwise:epoch12:DEV:float32 | 200 | 1200 | 6.79e-06 | 2.38e-06 | 0 | 0 | 0 | 3.8e-06 | PASS |
| pointwise:epoch12:DEV:float64 | 200 | 1200 | 1.95e-14 | 5.33e-15 | 0 | 0 | 0 | 1.1e-14 | PASS |

200 stratified roots per split (100 eligible), 6 random candidate permutations each; FP32 tolerance 1e-4, FP64 1e-9. A positional negative-control model is detected as non-equivariant in the unit tests, so the detector is not vacuous. Unit tests: 11 passed in 5.60s. The full pipeline was rehearsed twice on TRAIN-only stand-ins with no DEV contact (identical numbers).

## Denominators

| quantity | value |
|---|---|
| TRAIN roots / eligible | 12,000 / 1,333 |
| DEV roots / eligible | 3,000 / 333 |
| same-type selected-vs-alternative pairs TRAIN / DEV | 11,883 / 3,180 (332 DEV roots) |
| max candidates | 171 |
| DEV candidates | 176,168 |
| DEV roots with >=1 gold-legal candidate | 2833 |
| trivial all-illegal DEV roots | 167 (5.57%) |

All match the denominators stated in the task and in Phase 6B.

## Primary ranking comparison (333 eligible DEV roots, epoch 12, CPU/FP32)

| metric | SetRank | pointwise | delta | paired 95% CI (2000 root resamples) | P(delta>0) |
|---|---|---|---|---|---|
| selected top1 | 0.1051 | 0.0841 | +0.0210 | [-0.0060, +0.0480] | 0.928 |
| selected MRR | 0.2490 | 0.2385 | +0.0105 | [-0.0095, +0.0305] | 0.849 |
| gold-type top1 | 0.1592 | 0.1231 | +0.0360 | [+0.0030, +0.0691] | 0.976 |
| gold-type MRR | 0.3431 | 0.3235 | +0.0196 | [-0.0040, +0.0425] | 0.951 |
| optimal-set top1 (separate contract) | 0.1051 | 0.0841 | +0.0210 | [-0.0060, +0.0480] | 0.928 |
| same-type pair accuracy (root mean, 332 roots) | 0.5276 | 0.5222 | +0.0053 | [-0.0193, +0.0307] | 0.661 |

Optimal-set and selected endpoints coincide on this population (singleton equality, Phase 6A); equal numbers are one bank property, not two confirmations.

SetRank does not dominate: its unrestricted top3 (0.210 vs 0.234) and mean rank (11.5 vs 10.6) are slightly worse than the control's, and gold-type mean rank is a tie (5.35 vs 5.44). The gains are concentrated in top-1 hits, not in the bulk of the ordering.

| arm | top1 | top3 | top5 | MRR | mean rank | gold-type top1 | gold-type MRR | gold-type mean rank |
|---|---|---|---|---|---|---|---|---|
| set | 0.1051 | 0.2102 | 0.4024 | 0.2490 | 11.53 | 0.1592 | 0.3431 | 5.35 |
| pointwise | 0.0841 | 0.2342 | 0.3844 | 0.2385 | 10.62 | 0.1231 | 0.3235 | 5.44 |
| init (epoch 0) set / pointwise | 0.0030 / 0.0120 |  |  |  |  |  |  |  |
| uniform chance | 0.0189 |  |  |  |  | 0.1140 | 0.3096 |  |
| Phase 6A best independent scorer (E e-linear) | 0.0901 |  |  | 0.2407 |  | 0.1532 | 0.3391 |  |

Gold-type restriction is diagnostic only (never an input). The "uniform" gold-type row is the restricted-universe chance (mean 10.5 same-type candidates), matching the Phase 6A correction.

## Candidate-count bands (descriptive; only the 29-64 and 65-128 bands exceed ~100 roots, none reaches the 200-root floor)

| candidates | eligible roots | top1 (set / pw) | MRR (set / pw) | gold-type top1 (set / pw) | gold-type MRR (set / pw) |
|---|---|---|---|---|---|
| 1-28 | 17 | 0.176 / 0.059 | 0.285 / 0.228 | 0.235 / 0.059 | 0.367 / 0.283 |
| 29-64 | 187 | 0.123 / 0.091 | 0.275 / 0.256 | 0.160 / 0.123 | 0.355 / 0.333 |
| 65-128 | 128 | 0.070 / 0.078 | 0.208 / 0.216 | 0.148 / 0.133 | 0.324 / 0.314 |
| 129-171 | 1 | 0.000 / 0.000 | 0.022 / 0.038 | 0.000 / 0.000 | 0.143 / 0.333 |

The 1-28 band (17 roots) shows the largest apparent gap and the 129-171 band has 1 root; neither supports a claim. In the two bands with real mass the gold-type top1 gap is +0.037 (29-64) and +0.015 (65-128): no sign that set attention helps more as sets grow.

## Per action type (support retained; only MOVE meets the 200-root reliability floor)

| type | eligible DEV roots | reliable | gold-type top1 set | gold-type top1 pw | top1 set | top1 pw |
|---|---|---|---|---|---|---|
| MOVE | 249 | yes | 0.137 | 0.104 | 0.129 | 0.104 |
| TAKE | 39 | descriptive only | 0.179 | 0.077 | 0.077 | 0.051 |
| DROP | 14 | descriptive only | 0.357 | 0.500 | 0.000 | 0.000 |
| ACTIVATE | 10 | descriptive only | 0.200 | 0.100 | 0.000 | 0.000 |
| DEACTIVATE | 5 | descriptive only | 0.000 | 0.000 | 0.000 | 0.000 |
| OPEN | 11 | descriptive only | 0.364 | 0.273 | 0.000 | 0.000 |
| CLOSE | 4 | descriptive only | 0.000 | 0.000 | 0.000 | 0.000 |
| WAIT | 1 | descriptive only | 1.000 | 1.000 | 0.000 | 0.000 |

MOVE (249 roots): gold-type top1 0.137 vs 0.104. Cells with < 200 roots are not capability claims.

## Legality sidecar (independent head; root-normalised balanced BCE)

| population | arm | cand. BA | precision | recall | F1 | exact legal-set | exact (roots with a legal cand.) | mean Jaccard | FP/root | FN/root |
|---|---|---|---|---|---|---|---|---|---|---|
| all 3,000 DEV roots | set | 0.8014 | 0.2377 | 0.7436 | 0.3602 | 0.0553 | 0.0000 | 0.2731 | 7.80 | 0.84 |
| all 3,000 DEV roots | pointwise | 0.8022 | 0.2406 | 0.7428 | 0.3634 | 0.0563 | 0.0007 | 0.2754 | 7.67 | 0.84 |
| 333 eligible roots | set | 0.7955 | 0.2362 | 0.7316 | 0.3571 | 0.0000 | 0.0000 | 0.2278 | 8.29 | 0.94 |
| 333 eligible roots | pointwise | 0.7977 | 0.2391 | 0.7341 | 0.3607 | 0.0000 | 0.0000 | 0.2273 | 8.18 | 0.93 |

Selected-candidate retention (eligible): 0.754 / 0.754; same-type exact legal-set recovery: 0.006 / 0.009. Candidate BA is ~0.80 for both, but at ~7.8 false positives per root the **root-level sets are useless**: overall exact-set recovery (0.0553 / 0.0563) equals the trivial all-illegal-root fraction (0.0557), i.e. credit comes only from roots with nothing legal; on roots with a legal candidate it is 0.0000 / 0.0007. Paired difference in exact-set recovery: -0.0010 (CI [-0.0023, +0.0000]) - set attention does not help legality grounding.

## Training dynamics (recorded every epoch; never used for selection)

| epoch | set TRAIN top1 | set DEV top1 | set DEV gold-type | pw TRAIN top1 | pw DEV top1 | pw DEV gold-type |
|---|---|---|---|---|---|---|
| 0 | 0.002 | 0.003 | 0.108 | 0.008 | 0.012 | 0.108 |
| 1 | 0.546 | 0.084 | 0.141 | 0.541 | 0.084 | 0.135 |
| 2 | 0.573 | 0.069 | 0.120 | 0.572 | 0.072 | 0.123 |
| 4 | 0.593 | 0.102 | 0.156 | 0.582 | 0.102 | 0.153 |
| 6 | 0.670 | 0.090 | 0.141 | 0.644 | 0.081 | 0.120 |
| 8 | 0.730 | 0.081 | 0.138 | 0.667 | 0.078 | 0.108 |
| 10 | 0.790 | 0.102 | 0.159 | 0.695 | 0.084 | 0.117 |
| 12 | 0.802 | 0.105 | 0.159 | 0.707 | 0.084 | 0.123 |

DEV never improves beyond the first epochs while TRAIN climbs monotonically: the gap is memorisation. (Per-epoch monitoring is GPU; the scored endpoint is the CPU recomputation from the epoch-12 checkpoint.)

## Attention diagnostics (descriptive; not causal explanations)

| layer/head | normalised entropy (init -> trained) | same-type mass (init -> trained) | same-type base rate | selected->legal mass (init -> trained) | legal base rate |
|---|---|---|---|---|---|
| L0H0 | 0.990 -> 0.923 | 0.208 -> 0.265 | 0.207 | 0.039 -> 0.028 | 0.047 |
| L0H1 | 0.992 -> 0.911 | 0.204 -> 0.138 | 0.207 | 0.044 -> 0.055 | 0.047 |
| L0H2 | 0.992 -> 0.941 | 0.191 -> 0.197 | 0.207 | 0.044 -> 0.029 | 0.047 |
| L0H3 | 0.993 -> 0.869 | 0.200 -> 0.135 | 0.207 | 0.049 -> 0.071 | 0.047 |
| L1H0 | 0.993 -> 0.986 | 0.203 -> 0.213 | 0.207 | 0.048 -> 0.066 | 0.047 |
| L1H1 | 0.992 -> 0.916 | 0.214 -> 0.284 | 0.207 | 0.044 -> 0.036 | 0.047 |
| L1H2 | 0.993 -> 0.788 | 0.191 -> 0.220 | 0.207 | 0.045 -> 0.069 | 0.047 |
| L1H3 | 0.992 -> 0.935 | 0.204 -> 0.294 | 0.207 | 0.045 -> 0.049 | 0.047 |


Representation change after each block, `||h^(L) - h^(0)|| / ||h^(0)||` (cosine to the projected input in brackets): SetRank trained 1.40, 2.53 (0.67, 0.39); pointwise trained 1.13, 2.34 (0.68, 0.40); at initialisation both ~0.58/0.84.

Reading (descriptive): at initialisation attention is near uniform (entropy ~0.99) and matches both base rates. After training the heads moved only modestly (entropy 0.79-0.99): some heads shifted toward same-type keys (L1H1/L1H3 ~0.28-0.29 vs 0.207 base) and others toward different-type keys (L0H1/L0H3 same-type mass 0.135, i.e. type contrast), and selected-query mass on legal keys moved from the 0.047 base rate to 0.028-0.071 in both directions. So there is a learned type-contrast structure, but little legality- or selection-specific structure, and the candidate representations changed only a little more than the pointwise control's. Consistent with "almost-pointwise solution plus weak type contrast".

## Cost

| arm | parameters | training s (excl. monitoring) | incl. monitoring s | peak CUDA MB | steps |
|---|---|---|---|---|---|
| set | 312,322 | 174 | 196 | 1722 | 9,000 |
| pointwise | 312,066 | 145 | 161 | 1667 | 9,000 |

Device NVIDIA GeForce RTX 3080; FP32; dense N^2 attention at N<=171 is cheap (SetRank training 1.21x the control). CPU scoring of DEV: seconds.

## Survival rule and the outcome catalogue

Frozen rule output: **FLAT_OR_NEGATIVE**. STRONG needs gold-type top1 delta >= +0.05 with lower bound > 0: observed +0.036, lower bound +0.003 (positive, but the effect is below threshold). PRESERVE needs gold-type MRR delta >= +0.03 with lower bound > 0: observed +0.020, lower bound -0.004. Neither holds, so the experiment is sealed without confirmation seeds or widening. The borderline gold-type-top1 interval is exactly the kind of single-seed signal the rule says not to chase.

| catalogue entry | observed |
|---|---|
| ranking jumps, legality unchanged | no: ranking moved little, legality unchanged |
| legality exact sets jump, ranking also jumps | no: legality sets unrecovered |
| same-type jumps much more than full-set | slightly (+3.6 vs +2.1 pp), within noise; not "much more" |
| different-type improves, same-type weak | attention learned type contrast but same-type comparison stays near chance (pair accuracy 0.54) |
| attention model ~ pointwise control | **closest match**: explicit set interaction adds little on this frozen state |
| training ranking improves but permutation test fails | no: qualification passed everywhere |

## What this does and does not conclude

- Concluded: the implementation is permutation-equivariant and padding-invariant; with this construction, seed 0, fixed contract and these frozen trained-E states, set attention did not recover the within-type residual or the legality sets.
- Not concluded: that set attention is useless; that a different set architecture, loss family (Plackett-Luce was deliberately excluded), pooling, or inputs would fail; anything about other seeds (one seed was run by design); anything about unseen renderings (paired-render check not run).
- Caveats: (a) heavy TRAIN memorisation / train-DEV state shift limits what any head fitted on TRAIN E states can learn; (b) the matched pointwise MLP control under-performs the older simple independent scorers, so the paired gap overstates the advantage over the best independent baseline (SetRank ~ that baseline); (c) only 333 ranking roots (CI half-width ~ +/-3 pp); (d) bands and action types below 200 roots are descriptive; (e) a lower interval bound of +0.003 on one primary metric is not a robust finding.
- The next architecture is **not** started from this fan-out.

## Artifacts

Checkpoints (`arms/<arm>/checkpoints/`, sha256 in `arms/<arm>/checkpoint-hashes.json`):

| arm | checkpoint | sha256 |
|---|---|---|
| set | epoch00 | 871e679adcf7ba79fbb8... |
| pointwise | epoch00 | a748c7c07ca2a5579a60... |
| set | epoch12 (scored) | 54cb9346007e246dbd99... |
| pointwise | epoch12 (scored) | 5303aef803935029e28e... |

`SPECIFICATION.json` (frozen before DEV scoring) · `INPUT-IDENTITY.json` · `ENGINEERING-RECEIPT.json` · `EQUIVARIANCE-QUALIFICATION.json` · `metrics/` · `scores/` · `COMPARISON.json` · `ATTENTION-DIAGNOSTICS.json` · `CONTEXT.json` · `REPLAY.json` · `DISPOSITION.json` · `PHASE7A-SEALED.json`.
