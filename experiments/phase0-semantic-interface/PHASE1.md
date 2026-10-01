# Phase 1 — bidirectional fabric (Lepori's lane)

**Question.** Can the frozen `LFM2.5-Encoder-230M` substrate, through the frozen Phase 0
bidirectional graft, learn a useful explicit semantic state and candidate-conditioned
epistemic state from currently sourceable BANK-v1 supervision?

**Answer, in one line.** The candidate-conditioned epistemic state learned; the global
semantic state collapsed to a constant and did not learn; the action endpoint did not learn.

## What was run

| | |
|---|---|
| population | BANK-v1 TRAIN **20,000** canonical / DEV **2,000** canonical — both met exactly |
| substrate | `LFM2.5-Encoder-230M` @ `0b649ad0`, 229.7M, **frozen** |
| graft | Phase 0 `BidirectionalGraft`, **unchanged** |
| latent dims | `d_s=64`, `d_e=32`, `m_cap=24` — **this lane's Phase 0 choice, preserved** |
| trainable | 3,187,526 parameters (0.0014% of the substrate) |
| training | 8 epochs, 312 steps/epoch = 2,496 steps, AdamW 3e-4 cosine, bs 64 |
| objective | frozen five-term `L = L_S + L_E + 0.5·L_A + 0.5·L_CF + 0.25·L_R` |

The Phase 0 primitive cache only held 16,668 / 1,668 canonical rows inside its export window,
so the 20k/2k contract was unreachable from it. A top-up pass added canonical BANK-v1 rows
through the **same frozen substrate and same six surfaces**, writing new `*-full.pt` files. The
Phase 0 cache was left byte-identical, and the Phase 0 gate path still returns 346 rows exactly
as before.

## The scientific question was not changed

Target ontology, availability decisions, candidate convention, split identity, and the frozen
architecture are all untouched. `d_s=64` vs the sibling lane's geometry is **recorded, not
"fixed."** The comparison object is the shared contract, not matching hidden tensors.

## Per-target DEV results

Scored at the frozen checkpoint. Base rate is the trivial predictor; `beats` is a real margin.

### Global semantic state — did not learn

| target | acc | bal acc | macro-F1 | base rate | support | beats |
|---|---|---|---|---|---|---|
| `solvable` | 0.554 | **0.500** | 0.000 | 0.446 | 892/1108 | no |
| `goal_satisfied` | 0.641 | **0.500** | 0.000 | 0.360 | 719/1281 | no |
| `missing_information_present` | 0.840 | **0.500** | 0.000 | 0.161 | 321/1679 | no |
| `contradiction_present` | 0.919 | **0.500** | 0.000 | 0.081 | 162/1838 | no |
| `number_or_structure_of_missing_requirements` | MAE 0.312, exact-count **0.840** = trivial 0.840, within-one 1.000, observed range **[0.0, 1.0]** | | | mean 0.161 | 2000 | **no** |

Every global target sits at *exactly* 0.500 balanced accuracy at **every one of the 8 epochs**.
That is the signature of a single-class predictor: recall 0, specificity 1. The count channel
matches its trivial baseline exactly, so it is reported as no margin rather than as a success.

### Candidate epistemic state — learned

| target | acc | bal acc | macro-F1 | base rate | valid candidates | beats |
|---|---|---|---|---|---|---|
| `candidate_legal` | 0.762 | **0.7345** | 0.667 | 0.391 | 26,834 | **yes** |
| `candidate_has_unmet_requirements` | 0.761 | **0.7049** | 0.831 | 0.609 | 26,834 | **yes** |
| `candidate_applicable` | 0.761 | 0.7112 | 0.613 | 0.391 | 26,834 | not counted |
| `candidate_satisfies_goal` | 0.672 | **0.500** | 0.000 | 0.328 | 26,834 | no |

These are the epoch-1 frozen-checkpoint values. Both learning targets improve monotonically
across the 8 epochs, reaching 0.754 balanced accuracy at epoch 8.

`candidate_applicable` and `candidate_legal` are **verified byte-identical on all 26,834 valid
candidates** — they are one canonical source under two names. Both heads are kept as frozen.
Their agreement is a consistency check, **not independent evidence**, and is not counted as a
second win.

### Action endpoint — did not learn

```
top-1 accuracy   0.000 – 0.012
chance           0.042   (1 / 24)
endpoint worlds  935 of 2,000 DEV rows (coverage 0.468; abstention worlds masked out)
```

The endpoint head never once beat random choice across 8 epochs.

## The three state-level diagnostics

**1. Global semantic separability — failed.** `s` is near-constant across DEV rows
(`s_row_std` falls 0.0083 → 0.0031 over training), and 1-NN on `s` scores *below* the trivial
baseline for every global target. `s` carries no recoverable global semantic signal.

**2. Candidate conditioning — passed.** Within-world variance of `e_j` exceeds between-world
variance by **19× at epoch 1 rising to 96× at epoch 8**, over 2,000 multi-candidate worlds
(mean 13.4 valid candidates each). `e_j` genuinely varies with candidate identity and is not a
broadcast world vector. This is an implementation sanity check, not a capability claim.

**3. Renderer behaviour — passed.** Over the 2,000 meaning-preserving pairs the Phase 0
construction already supplied, prediction agreement is **0.99–1.00** across epochs, reaching
1.00 from epoch 2. No new renderer study was launched.

## The honest reading

`L_R` fell 4.37 → 0.24 and `L_E` fell steadily, while `L_S` sat at 0.50 from epoch 1 onward.
0.50 is the **mean prior entropy** of the five global targets — the heads learned the marginal
class rates and nothing more.

I checked whether this was a broken gradient path before calling it a result. It is not: the
same heads, from the same checkpoint, fit a 256-row subset to ~1.0 accuracy in 150 steps. The
wiring is live. Global state collapsed for a real reason.

**Leading hypothesis, explicitly not measured in this phase:** `L_R` penalises
`‖s(x) − s(x̃)‖²` directly, and `L_S` is the only term that rewards an informative `s`. Constant
`s` is the cheapest way to satisfy `L_R`. The co-timeline supports it — `s_row_std` decreases
monotonically across the same epochs that `L_R` collapses. Confirming it needs a λ_R ablation,
which is a new training branch and therefore out of Phase 1 scope.

## Engineering interpretation

**Learned strongly.** Renderer invariance (`L_R` 4.37 → 0.24, agreement 1.00). Candidate
conditioning of `e` (96× ratio).

**Learned weakly.** Candidate legality and unmet-requirement structure: 0.7345 and 0.7049
balanced accuracy at the frozen checkpoint, rising to 0.754 by epoch 8, against base rates of
0.391 and 0.609. A real but modest margin.

**Did not learn.** All global semantic targets. The action endpoint. `candidate_satisfies_goal`.

**Blocked by missing supervision.** `L_CF` is dormant *by contract* — `candidate_supported`,
`candidate_has_counterevidence` and `candidate_requires_missing_information` have no admissible
canonical source, and none was invented. Separately, `number_or_structure_of_missing_requirements`
can only be scored on the count channel, and BANK-v1 supplies 0/1 only, so its structure half
is unlearnable this phase.

**Did state stay candidate-conditioned?** Yes.

**Worth carrying to Phase 2.** This frozen substrate plus this graft *does* learn
candidate-level legality from BANK-v1. The 2,000 meaning-preserving DEV pairs are usable
training signal at real scale. The global semantic pathway is the open problem and the
`L_R`-vs-`L_S` tension on `s` is the first thing to test.

**Not proposed:** any new architecture, on the grounds that a target performed poorly. The
charter forbids it and the evidence does not require it.

## A caveat about the selection rule, stated rather than hidden

The frozen checkpoint is selected by lowest DEV semantic+epistemic BCE. BCE on these skewed
targets is minimised by predicting the prior, so **the rule prefers the most underfit
checkpoint** and it picked epoch 1. I did **not** change the rule after seeing that, because
retro-fitting a selection rule to DEV is exactly the thing this phase exists to avoid. The full
per-epoch DEV table is in the receipt so the trajectory is inspectable — the table shows the
global targets are flat at 0.500 for all 8 epochs, so no checkpoint selection rule would have
rescued them.

## Exit

```
FULL_TRAIN_RUN_COMPLETE               true    20,000 canonical rows, 2,496 steps
BEST_CHECKPOINT_FROZEN                true    epoch 1, hashed
ALL_SOURCEABLE_TARGETS_SCORED         true    5 global + 4 candidate + 1 endpoint
CANDIDATE_CONDITIONING_CHECK_COMPLETE true    96x within/between ratio
PHASE0_TARGET_SEMANTICS_UNCHANGED     true
PHASE0_ARCHITECTURE_UNCHANGED         true
PROTECTED_TEST_TRUTH_OPENED           false
BANK_V2_USED                          false
PHASE1_RECEIPT_COMPLETE               true
```

No predetermined accuracy threshold, and none is claimed.

## Artifacts

- `D:\codex-runs\encoder-contrast-01\phase1\phase1-bidirectional-receipt.json`
- `D:\codex-runs\encoder-contrast-01\phase1\artifact-hashes.json` (receipt + 8 checkpoints)
- `D:\codex-runs\encoder-contrast-01\phase1\ckpt-epoch-{1..8}.pt`

No head-to-head verdict is declared. `Δ_lane` for this lane: *the bidirectional graft adds
candidate-level legality and unmet-requirement structure, plus clean renderer invariance, to
this frozen encoder — and adds nothing yet to global semantic state or action selection.*
Cross-lane synthesis waits for both receipts.
