# Phase 4A — bidirectional fabric (Lepori's lane). R4

**Question.** Can shared-weight recurrent latent refinement turn the state already accessible to
this frozen substrate into better global semantic and action computation?

**Verdict: state motion without useful computation.** The recurrent organ demonstrably moved the
state — `D_s` grew **172.6×**, update magnitude *grew* rather than converged, and the heads
stopped being degenerate. It did **not** make any global semantic source discriminative under the
pre-registered margin, and it cost candidate conditioning and renderer paired accuracy.

## Carry-forward

Seed: **`P3-BALANCED` `ckpt-epoch-1.pt`**, sha256 `cc48bb2af29efa01…`. P2-CONSIST preserved
unmerged as a frozen reference; the two grafts were not combined.

Frozen: the 229.7M backbone, the inherited Phase 3 graft producing `Z_0`, and the typed output
heads. Trained: **`R_φ` only — 136,544 parameters, 4.28% of the 3,187,658 inherited ones.**

**`R0 == seed`, verified to 1e-9 on all six sources plus the action endpoint.** The inherited
baseline is faithfully reproduced, so every depth delta is attributable to the recurrent block.

## Recurrent construction

`Z_0 = [s_0 ; e_1,0 ; … ; e_m,0]` — 1 + 28 = 29 tokens of width 64, padded candidates masked.
Candidate tokens are `e_j` lifted by a trainable input projection; a trainable output projection
returns them to `d_e=32` so the **frozen** heads receive exactly what they were built for. One
shared block, `T=4`:

```
U_t = SelfAttn(LN(Z_t), M);  C_t = CrossAttn(LN(Z_t+U_t), H)
Z_{t+1} = Z_t + FFN(LN(Z_t + U_t + C_t))
```

Cross-attention rereads the **frozen** substrate memory: the 6 pooled surface vectors plus the
row's entity-span vectors. Nothing new was extracted.

`L_recurrent = L(Z_4) + 0.25·(1/3)·Σ_{t=1..3} L(Z_t)`, `Z_0` gets no recurrent loss, and each
`L(Z_t)` is the **frozen Phase 3 objective** — no redesign. Deep-supervision coefficient not tuned
from DEV. No stochastic transitions, adaptive halting, IHA, LoRA, or new surfaces.

## Depth curve 0 → 4 (one run, shared block, no depth selected)

Balanced accuracy; `*` = beats base rate under the pre-registered margin.

| source | prevalence | t=0 | t=1 | t=2 | t=3 | t=4 |
|---|---|---|---|---|---|---|
| `SRC-SOLVABILITY` | 0.433 | 0.5000 | 0.5214 | 0.5137 | 0.5076 | 0.4999 |
| `SRC-GOAL-SATISFIED` | 0.363 | 0.5000 | 0.5699 | 0.5446 | 0.5436 | 0.5510 |
| `SRC-MISSING-INFO-PANEL` | 0.160 | 0.5000 | 0.5030 | 0.4964 | 0.5000 | 0.4977 |
| `SRC-CONTRADICTION-PANEL` | 0.079 | 0.5202 | 0.4872 | 0.4772 | 0.4722 | 0.4754 |
| `SRC-CANDIDATE-LEGALITY` | 0.349 | 0.7509* | 0.7509* | 0.7508* | 0.7508* | 0.7511* |
| `SRC-CANDIDATE-SATISFIES-GOAL` | 0.336 | 0.5118 | 0.5120 | 0.5169 | 0.5240 | 0.5307 |

`J_select` by depth (selected epoch 2): `0.6421, 0.6414, 0.6395, 0.6414, 0.6456` — best at **t=2**,
worse at t=4. The selection rule chose **epoch 2** on `J_select` at t=4.

## Three honest positives, none of which qualify

| | peak | required | why not a win |
|---|---|---|---|
| `goal_satisfied` | 0.5699 (t=1) | 0.6470 | below the pre-registered margin |
| `candidate_satisfies_goal` | 0.5307 (t=4) | 0.6733 | weak, not usable |
| action top-1 | 0.0451 (t=2) | chance 0.0357 | **non-monotone**: 0.0247 → 0.0365 → 0.0451 → 0.0269 → 0.0387 |

Action by type: **MOVE 0.0000 at every single depth.** ACTIVATE 0.0000 → 0.0133, NOOP
0.0529 → 0.0782. The chance crossing is majority-class movement, not action computation.

`SRC-CONTRADICTION-PANEL` **degrades** below its own t=0 value at every depth.

## What the state actually did

```
D_s                  0.01068  0.27161  0.70231  1.23484  1.84359     (172.6x)
candidate conditioning  6.53    6.74    3.19    2.08    1.53
Δ_t (selected epoch)  0.8297  0.8644  0.8805  0.9020                (growing)
Δ_t (final epoch)     1.1056  1.1673  1.1911  1.2195                (still growing)
```

- **Variance exploded without usefulness.** `D_s` grew 172.6× and every global source's macro-F1
  rose sharply (solvable 0.3561 → 0.4958, goal 0.3914 → 0.5609, contradiction 0.1842 → 0.4303).
  That is the heads *ceasing to be degenerate*, not becoming discriminative. Phase 2's lesson
  (`D_s > 0 ⇏ semantic discrimination`) reproduced at 172× the magnitude.
- **Candidate conditioning was destroyed**, 6.53 → 1.53. Self-attention over a global token plus
  28 candidate tokens homogenises them. The one genuinely earned capability in this lane is
  candidate differentiation, and recurrence is what erodes it.
- **Update magnitude grew rather than converged** — 0.83 → 0.90 across depths, 1.11 → 1.22 by the
  final epoch. Recorded as growth. No stabilising machinery was added, per the charter.

## Renderer correctness, t=0 vs t=4 (332 pairs)

| target | t=0 paired acc | t=4 paired acc | t=0 disagreement | t=4 disagreement |
|---|---|---|---|---|
| `solvable` | 0.4880 | 0.4849 | 0 | 4 |
| `goal_satisfied` | 0.6988 | **0.4669** | 0 | 79 |
| `missing_information_present` | 0.8072 | **0.1928** | 0 | 29 |
| `contradiction_present` | 0.0663 | 0.5000 | 79 | 65 |
| `candidate_legal` | 0.7651 | **0.7048** | 0 | 25 |
| action | 0.0132 | 0.0329 | 81 | 69 |

At `t=0` the global heads show **zero** disagreement with paired accuracy at the majority rate —
vacuous stability. At `t=4` predictions genuinely vary, but paired accuracy **collapses** on the
sources that were stable. **Variation was bought with correctness.** Raw agreement is not used as
a success measure anywhere in this report.

## What capability costs

| | |
|---|---|
| trainable recurrent parameters | 136,544 (4.28% of inherited) |
| per-step inference latency | 46.3 ms (batch 256, **CPU**) |
| total T=4 latency | 185.2 ms (batch 256, **CPU**) |
| training time | 999.7 s (6 epochs × 312 steps) |
| peak GPU bytes | 0 — **run executed on CPU** |

Latency figures are CPU latencies and are reported as measured rather than dressed up as GPU
numbers. T=4 costs 4.0× T=1.

## Verdict

**State motion without useful computation.** Not rescued: no depth sweep, no wider block, no
per-depth selection, no stabilising machinery, no additional recurrence.

Preserved: **candidate legality survived intact at every depth (0.7509 → 0.7511)** and is the
only source beating base rate throughout. Nothing already earned was lost — but nothing new was
gained either, and two diagnostics got worse.

## What this earns for the next rung

Shared-weight recurrence over an already-earned state did **not** buy discriminative global
semantics on this lane. If the recurrent organ is tried again it needs a **different job**: the
plausible one is composing the *already-good candidate state* into an action computation, since
candidate legality is the one thing this lane genuinely has and action is the one thing it lacks.
Not more depth, not a bigger block, on the same state.

**IHA-style cross-head mixing remains unearned.** There is no evidence on this lane that richer
state *interaction* is the binding constraint — the state it would interact over is not
discriminative to begin with.

## Scope compliance

No stochastic trajectories, parallel particles, state merging, adaptive halting, micro-LoRA,
IHA / cross-head mixing, sparse expansion, CΦ-style factorization changes, new target
derivations, new renderer generation, BANK-v2, protected TEST, backbone tuning, or self-play.
Ontology reconciliation between lanes was **not** performed, per the charter; this lane's frozen
Phase 3 source contract is preserved as-is. No causal/encoder winner declared.

## Artifacts

- `D:\codex-runs\encoder-contrast-01\phase4a\phase4a-receipt.json` + 6 hashed checkpoints
- `D:\codex-runs\encoder-contrast-01\phase4a\phase4a-synthesis.json`
- `D:\codex-runs\encoder-contrast-01\phase4a\sigma0.pt`
