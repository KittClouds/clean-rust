# Lepori Phase 1 — causal baseline on MiniCPM5-1B-Base

**Question.** Can a 1.08B causal substrate, through a deliberately boring six-surface graft,
learn useful explicit semantic state and candidate-conditioned epistemic state from the inherited
causal contract?

**Answer.** Candidate-conditioned epistemic state: **yes**, and it transfers across substrates
(0.7495 balanced accuracy, beating a 0.349 base rate). Global semantic state: **no** — the same
failure the encoder lane hit, under a different fabric and a different substrate. Action endpoint:
**degenerate** — 46.7% is *entirely* the NOOP majority, with MOVE and ACTIVATE at exactly 0.0000.

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

**Candidate legality is the one thing that works, and it works at 0.7495 — essentially identical
to the encoder lane's 0.7509 on a completely different substrate and fabric.** That is a real
cross-substrate result: candidate-level legality is a property of the *interface*, not of the
backbone. Global state is dead on both.

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

## Surface contribution — the graft is not using the depth diversity

Zero one projected `u_i` at inference, no retraining:

| ablated surface | Δ action | Δ candidate_legal mean logit |
|---|---|---|
| `lt@24` | +0.0000 | −0.0002 |
| `mf@24` | +0.0000 | +0.0013 |
| `ms@24` | +0.0000 | +0.0022 |
| `mf@18` | +0.0000 | +0.0033 |
| `mf@12` | +0.0000 | −0.0063 |
| `mf@6` | +0.0000 | −0.0117 |

**Every single surface is individually dispensable.** Removing any one changes action accuracy by
exactly zero and shifts the candidate logit by at most 0.012.

The honest reading: the information the graft uses is **redundant across depth**, not concentrated
in one layer. That is *not* the same as "it ignores depth" — a redundant code is still using all
six. But it does mean **there is no obvious privileged layer to aim surgery at**, which is the
opposite of the outcome the diagnostic was designed to detect. Worth knowing before proposing
micro-LoRA or depth-targeted recurrence: there is no single depth carrying the load.

## Phenotype card

```
MiniCPM5-1B-Base  (causal, 6 surfaces, 0.25% trainable)
  global semantic state   DEAD        bal acc 0.46-0.51, none beats base rate
  candidate state         STRONG      0.7495, and renderer-stable (0 disagreements)
  action                  DEGENERATE  46.7% == the NOOP share exactly
  MOVE                    0.0000
  ACTIVATE                0.0000
  recurrence              not tried; no mechanism earned yet
  depth dependence        REDUNDANT   no single surface is load-bearing
```

Against the target card:

```
LFM2.5-230M (Lexi, per your brief)
  global state   strong | candidate state  strong | action ~75% | MOVE weak
MiniCPM5-1B (this lane)
  global state   DEAD   | candidate state  strong | action 46.7% (all NOOP) | MOVE 0.0000
```

**Two cautions before reading a gap into that.**

1. **Lexi's ~75% action number needs the same de-degeneracy check.** If it is also largely the
   majority action type, the apparent 75-vs-47 substrate gap is an artifact, not a phenotype
   difference. The type breakdown is now a shared reporting requirement.
2. **The honest answer to your scale question.** Does 1.08B MiniCPM arrive with capabilities the
   230M LFM needed graft machinery to expose? **Not so far.** It reproduces the encoder's pattern
   almost exactly — strong candidate-local legality, dead global state — at 4.7× the parameters and
   on a different architecture family. The global-pathway failure therefore looks like a property
   of **this interface + this supervision contract**, not of substrate size. That is a more useful
   finding than a score gap, and it points future work at the global pathway's information path
   rather than at more capacity.

## What is earned for the next rung

- Candidate-local legality is the transferable capability: 0.7495 here, 0.7509 on the encoder.
  Whatever makes that work is not substrate-specific and should be treated as the reusable part.
- The global pathway is dead on two substrates, two fabrics, and two architectures. Per your
  Phase 3 disposition, that is a fair shot. It is now a *shared* structural result.
- `MOVE` at exactly 0.0000 while `candidate_legal` is 0.7495 is the sharpest localisation we have:
  the graft knows **which candidates are legal** and cannot turn that into **which action to take**.
  That is a composition/computation gap, not a perception gap, and it is the natural first target
  for a mechanism chosen on *this* lane's evidence.
- Do **not** copy Lexi's recurrence because it worked there. Nothing here has earned it. If a
  recurrent organ gets first contact on this lane, the question it should answer is the
  candidate-state → action composition question above.

## Phase 0 gate: 9/9, engineering only, no accuracy threshold

Protected/test truth unopened, BANK-v2 unused, canonical splits unchanged, backbone frozen,
cross-agent alignment forbidden and asserted.
