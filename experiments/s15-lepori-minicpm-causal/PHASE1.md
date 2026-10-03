# Lepori Phase 1 — causal baseline on MiniCPM5-1B-Base

> Historical reference only: Qwen preparation exposed TRAIN/DEV consistency,
> candidate entity-addressing and padded-action masking defects in the inspected
> harness. Scores below remain unchanged; repaired Qwen is not a fully matched
> substrate-only comparison. See CORRECTIONS.md C13.

**Question.** Can a 1.08B causal substrate, through a deliberately boring six-surface graft,
learn useful explicit semantic state and candidate-conditioned epistemic state from the inherited
causal contract?

**Answer.** Candidate legality is **accessible** (0.7495 balanced accuracy against a 0.349 base
rate), and it **transfers strikingly** across two very different substrates under related
candidate-local interfaces — interface-dominant, or cheaply accessible, though two substrates are
not enough to remove the backbone from the causal story. Global semantic state: **no**, and
1.08B did not rescue it. The action endpoint: **degenerate** — 46.7% is *entirely* the NOOP
majority, with MOVE and ACTIVATE at exactly 0.0000.

**And the candidate state is not yet action-sufficient.** A gold-state sufficiency ladder
(below) gives legality-only state an overall determinism ceiling of **0.7605** and a
MOVE-conditional ceiling of **0.9335**. The **0.3699** MOVE figure is 1-NN accuracy, not a
MOVE-specific ceiling. Adding the already-existing `candidate_satisfies_goal` channel — which this
model has dead at 0.5216 — raises the overall ceiling to **0.9925** and the MOVE ceiling to
**0.9942**; MOVE 1-NN reaches **0.9306**. This is a large estimation gap for the simple 1-NN
readout, not proof that a learner or recurrent workspace cannot solve MOVE. See `PHASE1B.md` and
`CORRECTIONS.md` C11 for the correction.

## What was run

| | |
|---|---|
| substrate | MiniCPM5-1B-Base, 1.0806B, bf16, **frozen** |
| surfaces | 6, depth-diverse: `lt@24 mf@24 ms@24 mf@18 mf@12 mf@6`, `d_h=1536` |
| graft | 6 per-surface projections → `s=rho_s([u_1..u_6])` → `e_j=rho_e([c_j;s])` |
| candidates | exhaustive `m_max=28`; **2,998** TRAIN rows carry 25–28 candidates, 1,445 at the cap |
| population | 20,000 TRAIN / 2,000 DEV canonical, normalisation fitted on TRAIN only |
| trainable | **2,704,015** = **0.25%** of substrate |
| training | 8 epochs × 312 steps, AdamW 3e-4 cosine, bs 64 |
| objective | inherited unchanged; `L_CF` dormant; no raw latent `L_R` |
| selection | `J_select` over 6 unique source groups; best **epoch 2** |
| cost | 491.9 s train, 119.5 ms inference (batch 256, CPU) |

## An inherited bug found and fixed at the source

The action endpoint head was emitting `m × m_cap` logits, and the scorer took an `argmax` over the
flattened `m·m_cap = 784` tensor against a single candidate index. That silently turns the endpoint
into a **784-way classifier in which only 28 classes are ever correct**, and makes the chance rate
`1/784` instead of `1/m`.

The correct endpoint is **one logit per candidate**, `[B, m]`, with masked CE over the candidates a
world actually has, and padded slots masked so they can never be selected. Fixed in the head, the
loss, and the scorer; the Phase 0 init and the Phase 0 receipt were regenerated so no artifact
carries the old shape.

**This changes a conclusion in the parked encoder lane.** Its Phase 4A reported action top-1
"crossing chance" (0.0451 vs 0.0357). Against a correctly-shaped 784-way head, chance is 0.00128,
and against the intended per-candidate endpoint chance is ~0.065. That crossing is an artifact of a
mis-shaped head and should not be read as capability. Chance here is **`1/15.69 = 0.0637`**, not
`1/28`.

## Per-source DEV results

| source | prevalence | bal acc | acc | macro-F1 | pos-F1 | neg-F1 | beats base |
|---|---|---|---|---|---|---|---|
| `SRC-SOLVABILITY` | 0.433 | 0.5068 | 0.5315 | 0.4896 | 0.3434 | 0.6358 | no |
| `SRC-GOAL-SATISFIED` | 0.363 | 0.4973 | 0.4645 | 0.4641 | 0.4494 | 0.4788 | no |
| `SRC-MISSING-INFO-PANEL` | 0.160 | 0.4591 | 0.4235 | 0.3832 | 0.2257 | 0.5408 | no |
| `SRC-CONTRADICTION-PANEL` | 0.079 | 0.5123 | 0.3085 | 0.2830 | 0.1479 | 0.4182 | no |
| `SRC-CANDIDATE-LEGALITY` | 0.349 | **0.7495** | 0.7530 | 0.7378 | 0.6747 | 0.8008 | **yes** |
| `SRC-CANDIDATE-SATISFIES-GOAL` | 0.336 | 0.5216 | 0.5281 | 0.5080 | 0.4085 | 0.6074 | no |

Aliases, reported separately and never counted as independent wins:
`candidate_applicable` 0.7511, `candidate_has_unmet_requirements` 0.7504 (both
`SAME_CANONICAL_SOURCE=candidate_legal`); count head exact-count 0.4090 against a trivial 0.8400.

**Candidate legality transfers strikingly across two very different substrates under related
candidate-local interfaces, which suggests the capability is interface-dominant or cheaply
accessible.** 0.7495 here against the encoder lane's 0.7509, on a different substrate, fabric and
architecture family. Two substrates are enough for a strong engineering clue, not enough to remove
the backbone from the causal story. **And C6 below sharpens it further: on this lane the legality
signal comes from the candidate-local branch `c_j` alone.**

## The action endpoint is a NOOP detector

```
top-1 accuracy   0.4672      chance 0.0637  (1/15.69)
  MOVE     n=346   0.0000
  ACTIVATE n=150   0.0000
  NOOP     n=435   1.0000
```

`0.4672 == 435/931` **exactly**: the head predicts NOOP for every endpoint world. The 46.7% is the
NOOP share of the population, not decision-making. On the action types that require actually
choosing something, accuracy is zero.

This is the clearest instance so far of a lesson the program keeps relearning: **an aggregate
metric can be fully explained by a majority class.** Any endpoint number must be reported with its
action-type breakdown, and "action 46.7%" is meaningless on its own.

## Renderer paired correctness — 188 pairs

| target | both correct | first only | second only | both wrong | disagreement | paired acc |
|---|---|---|---|---|---|---|
| `solvable` | 49 | 40 | 35 | 64 | **75** | 0.2606 |
| `goal_satisfied` | 37 | 40 | 49 | 62 | **89** | 0.1968 |
| `missing_information_present` | 44 | 44 | 45 | 55 | **89** | 0.2340 |
| `contradiction_present` | 13 | 39 | 31 | 105 | **70** | 0.0691 |
| `candidate_legal` | 142 | 0 | 0 | 46 | **0** | **0.7553** |
| action | 4 | 0 | 0 | 81 | 0 | 0.0471 |

A very clean dissociation. The **global** state is both renderer-*unstable* (70–89 disagreements
out of 188, i.e. ~40–47%) and *below trivial* paired accuracy. The **candidate** state is perfectly
stable (zero disagreement) **and** correct at 0.7553. So on this lane the renderer decomposition
does the opposite of what it did on the encoder: there, global stability was vacuous; here, global
*instability* is real and paired with real failure.

## State diagnostics

```
D_s                0.4959     variance floor target 0.2948   -> floor satisfied
candidate conditioning  6.59 within/between, conditioned = True
```

No collapse. And still no global discrimination — the Phase 2/3 finding (`D_s > 0 ⇏ competence`)
reproduces on a new substrate, a new fabric, and a new architecture at a completely different scale.

## Surface contribution — and the correction of my own reading of it

Zero one projected `u_i` at inference, no retraining:

| ablated surface | Δ action | Δ candidate_legal mean logit |
|---|---|---|
| `lt@24` | +0.0000 | −0.0002 |
| `mf@24` | +0.0000 | +0.0013 |
| `ms@24` | +0.0000 | +0.0022 |
| `mf@18` | +0.0000 | +0.0033 |
| `mf@12` | +0.0000 | −0.0063 |
| `mf@6` | +0.0000 | −0.0117 |

**I originally read this as "depth redundancy". That reading was wrong** and is withdrawn. A
single-surface ablation cannot distinguish redundancy from "the global path is barely used at
all". Two **joint** inference-only ablations settle it:

| ablation | candidate_legal bal acc | Δ |
|---|---|---|
| baseline | 0.7495 | — |
| **all six `u_i` → 0** before `rho_s` | 0.7491 | **−0.0004** |
| **`s` → 0 inside `rho_e`**, `c_j` intact | 0.7499 | **−0.0004** |
| `s` → 0 everywhere | 0.7499 | −0.0004 |

**Candidate legality is produced entirely by `c_j`, the candidate/entity branch. Destroying the
entire six-surface global path costs nothing whatsoever.** The information was never spread across
depth; the global path was simply not carrying it. That also explains the cross-substrate match
without needing the global path to be doing transferable work.

Practical consequence: **there is no depth-diversity mechanism to aim at here, and no global-path
mechanism either.** The earned capability lives in one branch.

Receipt: `joint-surface-ablation.json`. Correction: `CORRECTIONS.md` C6.

## Gold action-sufficiency ladder — the audit that decides the next machine

Parameter-free, canonical BANK truth only, no model trained. DEV endpoint worlds, n=931.

The question: is the endpoint limited by the graft, or is the typed state not action-sufficient?

**Determinism ceiling** — do worlds with *identical* gold state ever have different actions? No
learner of any kind can exceed this; it is a property of the label.

**1-NN ceiling** — nearest neighbour in gold-state space, TRAIN → DEV.

| gold state | determinism ceiling | 1-NN overall | MOVE | ACTIVATE | NOOP |
|---|---|---|---|---|---|
| L1 legality only | **0.7605** (116 collisions) | 0.4887 | 0.3699 | 0.4267 | 0.6046 |
| **L2 + `candidate_satisfies_goal`** | **0.9925** (7 collisions) | **0.9624** | **0.9306** | **0.9267** | 1.0000 |
| L3 + global panels | 0.9925 | 0.9549 | 0.9220 | 0.9000 | 1.0000 |
| L4 + `optimal_next_actions`, type one-hot | 1.0000 | 0.9925 | 0.9855 | 0.9867 | 1.0000 |

Trivial baselines on the same rows: majority type (NOOP) **0.4672**, TRAIN index mode 0.1085,
first candidate 0.0806, uniform chance 0.0637.

**This is the branch-saving result.**

1. **The simple extractor struggles with legality-only state.** Its overall determinism ceiling is
   0.7605, its overall 1-NN accuracy is 0.4887, and MOVE 1-NN accuracy is 0.3699. However, the
   MOVE-conditional determinism ceiling is 0.9335, so the 1-NN result is not an information bound.
   Adding the goal-relative channel raises MOVE 1-NN to 0.9306. This supports prioritising the
   existing goal-relative target; it does not establish that legality-only state is inherently
   unable to support a better learner.
2. **The largest tested lift comes from goal-relative candidate information, for which the
   ontology already has a channel.** Adding gold `candidate_satisfies_goal` takes the ceiling from
   0.7605 to 0.9925 and the 1-NN figure from 0.4887 to 0.9624. **This model has that head and it is
   near base at 0.5216** against a 0.336 base rate. The target is present; acquisition was not
   demonstrated.
3. **The global panels add nothing** (L3 is flat, and marginally *worse* for 1-NN because extra
   dimensions dilute Hamming distance). The ontology's global targets are not where the action
   information is.
4. **Only a small further gain comes from a field the ontology lacks.** `optimal_next_actions`
   membership takes 0.9624 → 0.9925. Useful, but it is not the main gap.

So the evidence does **not** identify "composition" as the bottleneck. It shows that this trained
candidate state did not acquire the goal-relative signal, while the gold-state ladder shows that
signal is highly informative under the simple estimator. That makes it the first measured target
to investigate, not a proof that it is the only missing ingredient or that no learner can recover
the action from legality-only state.

A note on the label itself: `selected_action` lies inside the generator's own
`optimal_next_actions` only **53.3%** of the time, and `optimal_next_actions` is a singleton only
39.7% of the time. So the action label is *not* "the optimal action" — it has its own definition,
and the irreducibly ambiguous 7 L2-collisions are real.

Receipt: `gold-action-sufficiency.json`. Correction: `CORRECTIONS.md` C7.

## Phenotype card

```
LFM2.5-230M  (Lexi, causal, LFM2.5-230M)          <- measured, endpoint is correctly shaped
  global state       strong
  candidate state    strong
  action             0.7492  real, not a majority artifact
  MOVE               0.4770  (n=369, trivial 0.1870)
  ACTIVATE           0.8400  (n=150)
  depth dependence   n/a

MiniCPM5-1B-Base  (this lane, causal, 6 surfaces, 0.25% trainable)
  global state       DEAD        bal acc 0.46-0.51, none beats base rate
  candidate legality STRONG      0.7495, from c_j alone (C6)
  candidate goal     DEAD        0.5216  <-- the action-sufficiency gap
  action             DEGENERATE  0.4672 == the NOOP share exactly
  MOVE               0.0000
  ACTIVATE           0.0000
  depth dependence   IRRELEVANT  removing all six surfaces costs 0.0004
```

**On the substrate comparison.** I flagged Lexi's ~75% for the same de-degeneracy check that
caught MiniCPM's, and **it passes**: Lexi's MOVE is 0.4770 against a MOVE trivial baseline of
0.1870, and its endpoint head is correctly shaped. So the 0.7492-vs-0.4672 difference is
**genuine, not an artifact** — this lane's endpoint really is a NOOP detector where Lexi's is
not. (Lexi also never reported an analytic "chance" at all; it reported measured trivial
baselines, which is the more conservative choice.)

**On the scale question.** Increasing substrate size from the encoder/230M regime to 1.08B **did
not rescue global semantics under this interface.** There is currently **no evidence that capacity
alone is the lever** — which preserves exactly what was measured without asserting the converse.

## What is earned for the next rung

The gold ladder converts speculation into a decision, so this list is shorter and sharper than it
was.

- **Do not treat the 1-NN result as a hard limit on legality-only state.** The measured MOVE
  determinism ceiling is 0.9335, while MOVE 1-NN accuracy is 0.3699. The evidence says the simple
  extractor is weak; it does not close the branch by an information bound. The goal-relative
  channel remains the first measured target to investigate because it lifts MOVE 1-NN to 0.9306.
- **The goal-relative channel is the largest tested addition, and Phase 1B has now tested it.**
  The shallow probes over `e_j`, `c_j`, and `[c_j;s]` remained near base; isolated supervision
  reached 0.5171 on DEV while candidate legality held at 0.7506. The signal is valuable in the gold
  ladder, but this acquisition attempt did not generalize. A repeat of the same shallow-readout or
  isolated-loss intervention is not the next experiment.
- **The target asymmetry motivates, but does not prove, a binding hypothesis.** `candidate_legal`
  and `candidate_satisfies_goal` read from the same `e_j`; legality works at 0.7495 while the
  goal-relative head is near base. This is consistent with the latter requiring richer action/goal
  binding, but the experiments do not isolate a specific composition mechanism.
- **The global pathway is not needed for the currently working legality result.** Removing all six
  surfaces costs 0.0004, while the global semantic targets remain dead. A mechanism aimed at the
  global path or depth diversity needs a target-specific rationale; the static Lexi source review
  in `PHASE1B.md` identifies a different candidate-conditioning route but does not explain the
  endpoint gap.
- **`optimal_next_actions` membership is a real but small additional lever** (0.9624 → 0.9925) and
  is the one genuinely missing *field*. It is not the main gap, and it is a target-derivation
  question, which the frozen contract currently forbids — so it needs an explicit decision, not a
  quiet addition.
- **Candidate legality transfers strikingly across substrates** (0.7495 / 0.7509) under related
  candidate-local interfaces, which is a strong clue that the capability is interface-dominant or
  cheaply accessible. It is not enough to exonerate the backbone.
- **Do not copy Lexi's recurrence because it worked there.** Nothing on this lane has earned it,
  and the ladder says what would have. If a recurrent organ gets first contact, its job is
  candidate-semantics composition, not action selection over legality.

## Phase 0 gate: 9/9, engineering only, no accuracy threshold

Protected/test truth unopened, BANK-v2 unused, canonical splits unchanged, backbone frozen,
cross-agent alignment forbidden and asserted.
