# Phase 1B — Goal-Relative Candidate Acquisition

**Question.** Can MiniCPM acquire goal-relative candidate semantics through the interface it
already has?

**Answer: no.** Not at the readout level (stage 1) and not under isolated supervision (stage 2).
Legality was preserved throughout at ~0.75, so the control held. This is now a
**representation-level** finding, and it is the rung at which cross-lane comparison against Lexi
becomes earned.

## Stage 0 — the review correction, which reopened part of the previous conclusion

I had claimed legality-only state "caps MOVE at ~0.37". That was wrong: 0.3699 was the **1-NN
result**, not a MOVE-specific determinism ceiling. Computed by grouping worlds whose true action
is MOVE:

| gold state | MOVE ceiling | MOVE 1-NN | ACTIVATE ceiling | NOOP ceiling |
|---|---|---|---|---|
| L1 legality only | **0.9335** (n=346) | 0.3699 | 0.9733 | 1.0000 |
| L2 + `candidate_satisfies_goal` | **0.9942** | 0.9306 | 0.9867 | 1.0000 |
| L4 + `optimal_next_actions` | 1.0000 | 0.9855 | 1.0000 | 1.0000 |

**MOVE is not information-capped at 0.37.** The gap between 0.9335 and 0.3699 is an **estimation**
gap, not an information gap. What survives from the earlier claim is narrower and honest:
legality-only is not *crudely learnable* (1-NN 0.3699 on MOVE) while legality + the goal channel
is (0.9306). These ceilings are in-sample DEV statistics, so they bound a memorising extractor,
not a generalising learner.

Receipt: `gold-sufficiency-addendum.json`, `CORRECTIONS.md` C11.

## Stage 1 — recoverability, graft and substrate frozen

Prospectively fixed before any result: readout family `{production, Linear, Linear-GELU-Linear}`,
input `{e_j, c_j, [c_j;s], untrained e_j}`, optimisation `AdamW 1e-3 / wd 0.01 / cosine / bs 64 /
4 epochs`, primary metric `DEV balanced accuracy at final epoch`, **no DEV selection among
readouts**, pre-registered margin `0.01`.

| arm | target | DEV bal acc | beats base |
|---|---|---|---|
| `e_j` linear | `candidate_satisfies_goal` | 0.5137 | no |
| `e_j` MLP | `candidate_satisfies_goal` | 0.5222 | no |
| `c_j` linear | `candidate_satisfies_goal` | 0.5259 | no |
| `c_j` MLP | `candidate_satisfies_goal` | 0.5256 | no |
| `[c_j;s]` linear | `candidate_satisfies_goal` | 0.5220 | no |
| `[c_j;s]` MLP | `candidate_satisfies_goal` | 0.5229 | no |
| **production head** | `candidate_satisfies_goal` | **0.5216** | no |
| `e_j` linear | `candidate_legal` | 0.7413 | **yes** |
| **`e_j` MLP** | `candidate_legal` | **0.7479** | **yes** |
| **`c_j` MLP** | `candidate_legal` | **0.7509** | **yes** |
| `untrained e_j` MLP | `candidate_legal` | **0.7608** | **yes** |
| `untrained e_j` MLP | `candidate_satisfies_goal` | 0.5154 | no |

Sensitivity, pre-registered, 12 probe epochs: `e_j` MLP 0.5244, `c_j` MLP 0.5256. No change.

**Three things this settles.**

1. **The readout family is demonstrably capable.** The identical code, optimiser and schedule
   solves `candidate_legal` from `e_j` at 0.7479 and from `c_j` at 0.7509. So the null result on
   the goal channel is not the probe failing.
2. **Legality was never learned — it was already there.** Legality decodes at **0.7608 from the
   untrained graft**, *higher* than from the trained one (0.7479) and higher than the production
   head (0.7495). The candidate-local branch `c_j` linearly encodes legality from
   initialisation, and Phase 1 training was approximately neutral on it, if marginally negative.
   This retro-explains the suspiciously exact cross-substrate match: both lanes inherit the same
   kind of candidate-local access machinery, and neither had to learn it.
3. **Nothing recovers the goal relation at any depth tried.** `e_j`, `c_j` and `[c_j;s]` all sit
   at 0.51–0.53, indistinguishable from the production head and from the untrained floor.

**The mechanism, stated from the architecture rather than guessed:** `c_j` is built from the
entity-span vectors of the action's argument entities plus an action-type embedding. **The goal is
never an input to `c_j`.** Goal context can only reach a candidate through `s`, which is 64-dim and
derived from six pooled surfaces; a linear or one-hidden-layer readout over the concatenation
cannot perform the entity↔goal binding the target requires.

### A bug I hit and fixed, recorded because it nearly became a false finding

The first stage-1 run returned **exactly 0.5000 on every arm including the capability control**.
That is the signature of NaN weights, not of an absent distinction, so I stopped. Cause: padded
slots carry `NaN` labels and the loss was `(l * mask).sum() / mask.sum()`; `NaN * 0` is still
`NaN`, so one padded slot poisoned the gradient and every readout collapsed to a constant. Fixed
with `nan_to_num`. Verified before trusting the rerun with a closed-form ridge solve on the same
frozen `e_j`: legality TRAIN 0.7785 / DEV 0.7509. See `CORRECTIONS.md` C12.

## Stage 2 — supervision isolation

Same architecture, same frozen substrate, same splits, same candidate universe, same
normalisation, same initialisation. Only the supervision changes:

```
candidate_legal            preservation target
candidate_satisfies_goal   primary acquisition target
global heads               OUT
action loss                OUT
action head                NOT reconnected
L_pair, L_var              retained (dropping them would be a second intervention)
```

| target | DEV bal acc | beats base | Phase 1 reference |
|---|---|---|---|
| `candidate_legal` (preservation) | **0.7506** | **yes** | 0.7495 — held, no regression |
| `candidate_satisfies_goal` (primary) | **0.5171** | **no** | 0.5216 — no gain |

Training trace: `primary` loss 0.6964 → 0.5655 on TRAIN, i.e. the model *does* fit the training
channel to a degree, while DEV stays at 0.5171. So it is not a pure optimisation failure either; the
representation moves toward the training signal without generalising to it.

`D_s` rose to 0.805 and candidate conditioning strengthened to 20.4, so the state is healthy and
diverse. It is simply not carrying the goal-relative distinction.

## The verdict

```
goal-relative channel            NOT ACQUIRED
legality preservation            HELD at 0.7506
readout recoverability           NONE at e_j / c_j / [c_j;s], 4 or 12 epochs
objective competition            RULED OUT as the explanation
```

**The two cheap explanations are now both spent.** Objective competition is ruled out by stage 2.
Shallow recoverability is ruled out by stage 1, with a working positive control. What remains is a
representation-level fact: the candidate-local branch has no goal input, and the route from the
global state into a candidate cannot be a shallow readout.

**This is where cross-lane comparison becomes earned.** Not before. The next question is now
precise and answerable:

> Where does Lexi obtain goal-relative candidate structure that MiniCPM's present interface fails
> to acquire?

and it is worth asking, because Lexi has exactly the channel MiniCPM lacks. But the sequencing
rule still holds: a mechanism is last, not first, and the immediate next cheap step is to read
Lexi's graft and identify what its candidate path receives that `c_j` does not.

## What is *not* concluded

- Not that MiniCPM cannot represent the distinction at all. Deeper readouts, longer training, or
  a different candidate-path input were not tried, and saying so would be an overclaim.
- Not that the substrate lacks the information. The stage-1 arms read the *graft's* candidates,
  not raw substrate entity vectors, so the substrate is not yet exonerated or implicated.
- Not that Lexi is better. That comparison has not been run.

## Artifacts

- `gold-sufficiency-addendum.json` — type-conditional ceilings, optimal-set report
- `recoverability.json` — stage 1, all arms, controls, sensitivity
- `phase1b/phase1b-receipt.json` — stage 2
- `CORRECTIONS.md` C11, C12

Protected/test truth unopened, BANK-v2 unused, canonical splits unchanged, backbone frozen, no new
mechanism, no new supervision source.
