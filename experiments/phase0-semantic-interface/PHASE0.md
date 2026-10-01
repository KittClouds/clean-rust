# Phase 0 — semantic interface + candidate-conditioned epistemic state

Shared charter. Frozen substrate, trainable graft:

```
F_theta(x) -> H                (released primitive cache; never written to)
G_phi(H, A) -> (s, e_1..e_m)   (trainable)
s   in R^{d_s}   global semantic state
e_j in R^{d_e}   candidate-conditioned epistemic state for candidate a_j
y_hat_j = W e_j
```

`d_s` and `d_e` are free. They are **not** the target count, and the ontology's seven
candidate targets are not assumed to be seven dimensions. The ABI constrains only what must
be linearly readable from the slots.

## Invariants held

- `s` and `e_j` are distinct slots. No single global confidence head exists.
- `e_j` is a function of (world, candidate), not a broadcast copy of a world vector.
- Padded candidates are masked out of every loss.
- No substrate update. No VCS reopening. No new probing program. No System 1.5 redesign.

## Ontology availability — measured, not asserted

Audited against 2,000 released canonical worlds. **9 of 13 targets are sourceable; 4 are not.**

| | target | source |
|---|---|---|
| G | `solvable` | simulator BFS |
| G | `goal_satisfied` | simulator |
| G | `missing_information_present` | `world.missing_information` |
| G | `contradiction_present` | `world.contradictions` |
| G | `requestable_information_present` | **UNAVAILABLE** |
| G | `number_or_structure_of_missing_requirements` | count only (PARTIAL) |
| C | `candidate_legal` | simulator legal set |
| C | `candidate_satisfies_goal` | one-step apply + goal check |
| C | `candidate_supported` | **UNAVAILABLE** |
| C | `candidate_has_counterevidence` | **UNAVAILABLE** |
| C | `candidate_has_unmet_requirements` | legality complement (PARTIAL) |
| C | `candidate_applicable` | same source as `candidate_legal` (PARTIAL) |
| C | `candidate_requires_missing_information` | **UNAVAILABLE** |

The four unavailable targets have **no label array emitted at all**, so no head can be
trained on them by accident. They are not approximated.

### Measured evidence for the exclusions

```
per_candidate_evidence_field_present   false
requestability_field_present          false
missing_information count             0 -> 1672, 1 -> 328     (binary only)
contradiction count                    0 -> 1841, 1 -> 159
legal_action_count                    2..9 per world
```

- `candidate_supported` / `candidate_has_counterevidence`: `evidence_facts` and
  `contradictions` are **global** fact-id lists. There is no per-candidate support or
  counterevidence relation. Deriving one from membership would manufacture a label.
- `requestable_information_present`: `ask_target` exists but is populated only on the ASK
  generator branch and encodes a construction artefact, not a canonical property.
- `candidate_applicable` and `candidate_legal`: identical source and therefore an identical
  label vector in this bank. Kept as separate heads because the ontology distinguishes them,
  flagged so the agreement is not mistaken for independent evidence.

### Declared degradations

- `number_or_structure_of_missing_requirements` has `d_out = 6` (count + structure). Only the
  count is canonically sourceable. The five structure channels are `NaN` in the label tensor,
  so their BCE weight is exactly zero.
- `candidate_has_unmet_requirements` supervises the legality complement. The *count* and
  *structure* of unmet requirements are not separately observable and are not supervised.
- `candidate_applicable` is trained as a declared duplicate of `candidate_legal`.

## Architecture

| | |
|---|---|
| `d_h` | 1024 (frozen surface dim) |
| `d_s` | 64 |
| `d_e` | 32 |
| trainable parameters | 2,396,974 |
| frozen parameters | 0 written (substrate is a read-only cache) |
| candidate cap `m` | 24, with mask |
| argument slots per candidate | 3 |

```
row  : [B, 6, 1024]   six frozen surfaces
ent  : [E, 1024]      per-entity mention-span vectors
cand : [B, 24, 3]     entity index per argument slot, -1 pad
type : [B, 24]        action-type id
mask : [B, 24]        valid-candidate mask

row  -> Linear -> GELU -> LayerNorm -> to_s        -> s   [B, 64]
cand -> arg_proj(cand entity vecs, type emb)      -> c   [B, 24, H]
e    = to_e([c ; s])                               -> e   [B, 24, 32] * mask
```

`e_j` is conditioned on `s` by construction (`to_e` takes `[c, s]`), so the epistemic slot
cannot degenerate into a per-world constant.

## Training harness — executed

`python -m src/train --substrate {causal,encoder}`

Per-target masked BCE, AdamW, cosine schedule, grad clip 1.0. Padded candidates contribute
zero. Run end-to-end at 6,000 train / 2,000 dev rows, 6 epochs, 2.4M trainable parameters.

Dev accuracy after 6 epochs (harness executability check, **not** a science result):

| target | causal | encoder | base rate |
|---|---|---|---|
| `solvable` | 0.818 | 0.785 | 0.471 |
| `goal_satisfied` | 0.841 | 0.799 | 0.369 |
| `missing_information_present` | 0.913 | 0.914 | 0.157 |
| `contradiction_present` | 0.919 | 0.920 | 0.082 |
| `number_or_structure_of_missing_requirements` | 0.152 | 0.151 | 0.157 |
| `candidate_legal` | 0.774 | 0.805 | 0.396 |
| `candidate_applicable` | 0.768 | 0.795 | 0.396 |
| `candidate_satisfies_goal` | 0.813 | 0.782 | 0.347 |
| `candidate_has_unmet_requirements` | 0.772 | 0.806 | 0.604 |

**`number_or_structure_of_missing_requirements` is at base rate (0.15).** That target has
`d_out = 6` and only channel 0 is supervised; the head's remaining five outputs are never
constrained, and the reported accuracy is over all six channels including the five
unconstrained ones. This is a harness artifact of the degradation, not a learning failure.
The Phase 0 evaluation contract must score this target on channel 0 only.

## Evaluation contract

Frozen as `phase0-semantic-interface/eval-contract-v0.1`. Requirements:

1. Score every target against its own base rate, not a shared threshold.
2. Score `number_or_structure_of_missing_requirements` on supervised channels only.
3. Report `candidate_legal` and `candidate_applicable` together as a **declared duplicate**;
   agreement between them is a consistency check, not two results.
4. Report the four unavailable targets as **no head, no score** — never as zero.
5. No global confidence metric. `s` and `e_j` are reported separately.
6. Paired/grouped intervals over canonical world ids if any comparison is run.

## Phase 0 exit criteria — status

| deliverable | status |
|---|---|
| architecture | executable, frozen invariants held |
| supervision contract | frozen; 9/13 mapped, 4 excluded, 3 degraded |
| data construction | executable from released canonical truth |
| training harness | executable end-to-end, both substrates |
| evaluation contract | frozen |
| **frozen enough to begin training** | **YES** |

## Shared supervision mathematics

Both fabrics use the identical loss. Only `H` and the graft geometry differ.

```
L = λ_S·L_S + λ_E·L_E + λ_A·L_A + λ_CF·L_CF + λ_R·L_R

L_S   = Σ_k ℓ(ŝ_k, s*_k)                                    semantic, on s
L_E   = Σ_j Σ_k ℓ(ê_jk, e*_jk)                             candidate epistemic, on e_j
L_A   = CE(â, a*)                                           action ENDPOINT, not the definition of e
L_CF  = max(0, m − y[r(x⁺,a_j) − r(x⁻,a_j)])               truth-changing contrast, hinge
L_R   = ‖s(x) − s(x̃)‖² + (1/m) Σ_j ‖e_j(x) − e_j(x̃)‖²      renderer invariance

λ = (S 1.0, E 1.0, A 0.5, CF 0.5, R 0.25),  margin m = 0.2
```

The intended asymmetry: **semantic change → state changes** (L_S, L_E, L_CF);
**renderer change → state approximately stable** (L_R).

## Phase 0 discipline — enforced in code

`assert_no_alignment_term()` raises if a term whose name contains `align`, `distill`,
`s_c`, `s_b`, `e_c`, `e_b`, `cross_agent` is ever added to the loss. There is **no**
`s_c ≈ s_b` and **no** `e_j^c ≈ e_j^b`. The two fabrics share loss semantics and the typed
output contract `D(·) → Y`. Their internal coordinates may differ arbitrarily.

## Pair construction — orthogonal by construction

| | count (1.5k worlds) | used by | guarantee |
|---|---|---|---|
| renderer pairs `(x, x̃)` | BANK paired rows, S0/S1/S2 | `L_R` | same latent world, different surface family |
| truth-changing pairs `(x⁺, x⁻)` | 1,497 verified | `L_CF` | same world **and same renderer**, legality genuinely flips |

Truth-changing pairs are built by canonical-state mutation and **every one is verified
against the executable simulator**: the candidate's legality must actually differ between
`x⁺` and `x⁻`. Of 3,111 attempted mutations, **1,614 were discarded for flipping nothing**.

```
mutation histogram   flip_switch 895   block_edge 378   remove_edge 224
```

Orthogonality is the point: `L_CF` cannot be satisfied by a renderer shortcut because both
members render identically; `L_R` cannot be satisfied by a truth shortcut because the world
is bit-identical.

## Action endpoint `a*` — partial provenance

`a*` is the index of `world.selected_action` within `available_actions`, defined **only** where
`selected_action is not None`. Measured coverage: **0.509** of canonical worlds. Abstention
worlds contribute nothing to `L_A`; they are masked out, not assigned a default.

## Honest limitation: `L_CF` is DORMANT in this harness

`L_CF` is implemented and unit-tested, but contributes **0.0** in the recorded run. The
mutated renderings of a truth-changing pair are not in the released primitive cache, so
`H(x⁺)` and `H(x⁻)` do not exist. Activating the term requires a substrate pass to extract
features for the mutated texts.

This is recorded rather than hidden. It is **not** faked with a zero that pretends to be
supervision, and it is the one named engineering item outstanding before `L_CF` carries
gradient.

`L_R` is live: both members of a renderer pair are real BANK rows, so their frozen `H` is
already in the cache. Its value falls across the recorded run:

```
epoch        1        2        3        4
L_R      1.1370   0.6077   0.2264   0.2606
L_S      0.6415   0.6200   0.6021   0.5919
L_E      0.6058   0.5859   0.5756   0.5746
L_A      5.9116   5.3158   5.0014   4.9041
```

Renderer invariance is being learned (1.137 → 0.261, a 77% reduction) while the semantic
terms decline slowly. That is the intended direction, but it is a 4-epoch harness trace on
6k rows and is **not** a Phase 0 result — there is no accuracy gate here.

## Exit gate — 9/9, no accuracy gate

```
SUBSTRATE_IDENTITY_FROZEN          True
SURFACE_IDENTITY_FROZEN            True
STATE_ABI_FROZEN                   True
TARGET_PROVENANCE_COMPLETE         True
PAIR_CONSTRUCTION_REPLAYABLE       True
TRAINING_OBJECTIVE_IMPLEMENTED     True
UNTRAINED_FORWARD_TESTS_PASS       True
NO_PROTECTED_TRUTH_CONTACT         True
PHASE1_CONFIG_READY                True

PHASE 0 EXIT: True     accuracy gate present: False
```

Untrained forward test confirms the interface is candidate-conditioned rather than a
broadcast world vector: `e` varies across candidates, `s` varies across rows,
`s: [346, 64]`, `e: [346, 24, 32]`, action logits `[346, 24, 24]`.

## Division of labour

| | fabric | graft | substrate |
|---|---|---|---|
| **Lexi** | causal | late/prefix-integrated | `LFM2.5-230M-Base` |
| **Lepori** | bidirectional | full-context + entity-local (this lane) | `LFM2.5-Encoder-230M` |

Same question, different nervous systems. Same loss code, same ontology, same target
provenance. **No unified latent space and no horse race is imposed.**

Both fabrics are one config switch in `src/train_v2.py` (`--fabric`).

## Files

- `src/ontology.py` — 13-target ABI, action endpoint, empirical availability audit
- `src/objective.py` — the five-term loss + alignment-forbidden assertion
- `src/pairs.py` — renderer and truth-changing pair construction with verification
- `src/graft.py` — `BidirectionalGraft`, `SemanticInterfaceGraft`, `ReadoutHeads`
- `src/data.py` — H, candidate sets A, canonical supervision, action endpoint
- `src/gate.py` — the 9-boolean exit gate
- `src/train_v2.py` — shared training harness, both fabrics
- `src/train.py` — v1 per-target BCE harness (superseded by `train_v2.py`)

Results: `D:\codex-runs\encoder-contrast-01\phase0\{exit-gate,phase0-bidirectional}.json`

No protected/test-truth opened. BANK-v2 unused. VCS not reopened. No System 1.5 changes.