# Phase 2 — bidirectional fabric (Lepori's lane)

**Question.** Can the existing graft learn renderer-stable semantic and action state when
invariance is enforced without directly rewarding latent collapse?

**Answer.** The collapse was the objective's fault and removing the raw latent term fixed it —
`D_s` rises **82×** and clears the variance floor. But restoring variance did not make `s`
discriminative: **no global semantic target rose above trivial prediction, and the action
endpoint stayed at or below chance.** Renderer stability is therefore *vacuous* here, because
there is no varying state to be stable.

## Candidate preflight — the shared-contract audit

```
m_max  = 28        (measured over 140,000 canonical TRAIN+DEV worlds)
m_min  = ?         mean_m  15.45 TRAIN / 15.57 DEV
Phase 1 cap        24
```

**Phase 1 lost rows, and not by truncation.** `data.build()` *dropped the entire row* whenever
`len(available_actions) > 24`. So the loss was whole-row exclusion:

| | Phase 1 (cap 24) | Phase 2 (cap 28) |
|---|---|---|
| TRAIN rows reachable | 17,002 of 20,000 requested | **20,000** |
| rows with 24 < cand ≤ 28 | structurally impossible | 2,998 |
| rows at the full 28 | impossible | 1,445 |
| candidate pairs (TRAIN) | 228,100 | **308,938** |
| canonical worlds excluded, whole universe | 21,016 (15.0% TRAIN, 14.9% DEV) | 0 |
| candidates never reachable, whole universe | 567,254 | 0 |

Phase 2 retains every canonical candidate with deterministic padding to the measured maximum.
`max_args` was re-measured and is still 3, so that axis is unchanged. This confirms Lexi's
finding and is an **identity audit, not a scientific gate**.

Phase 1 is preserved exactly as run. Its path still returns 20,000/2,000 at cap 24, and its
endpoint limitation — a candidate universe silently missing 15% of worlds — is recorded rather
than retro-fixed.

## Provenance corrections to the Phase 1 closeout

Both are corrections **in provenance only**. The Phase 1 run is untouched.

1. **Trainable fraction was wrong by 1000×.** 3,187,526 / 229.7M = **1.39%**, not 0.0014%. The
   receipt's raw parameter counts were always correct; the prose figure was not.
2. **`macro_f1` was mislabelled.** The frozen Phase 1 receipt's `macro_f1` column is
   **positive-class F1**. A single-class predictor scores 0.000 on positive F1, but true macro-F1
   averages both classes and would be **0.500**. Balanced accuracy 0.500 and every substantive
   conclusion are unaffected. The scorer is corrected for Phase 2 and now reports
   `macro_f1`, `positive_f1` and `negative_f1` separately so the ambiguity cannot recur.

## The two arms

Identical Phase 0 initialization (`phase0-init.pt`), identical exhaustive-candidate input
contract, identical hyperparameters. **The only difference is the objective.** Nothing was tuned
from DEV.

```
P2-BASE      L_S + L_E + 0.5 L_A + 0.5 L_CF + 0.25 L_R          raw latent L_R PRESENT
P2-CONSIST   L_S + L_E + 0.5 L_A + 0.5 L_CF + 0.25 L_pair + 0.05 L_var   L_R REMOVED
```

`L_pair` is Jensen–Shannon on the *predicted* distributions of the supervised heads, for S, E
and A separately. Candidate alignment is verified exactly per pair; when it cannot be, E and A
consistency are **omitted, not guessed**. `L_CF` stayed dormant in both arms — no label invented.

## Representation diversity — the intervention works

`D_s = mean_k sigma_k(s)` on DEV. Untrained reference `sigma0 = 0.1116`, so the variance floor
sits at **0.0558**.

| epoch | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| P2-BASE | 0.00122 | 0.00064 | 0.00062 | 0.00076 | 0.00069 | 0.00070 | 0.00074 | 0.00074 |
| P2-CONSIST | 0.01148 | 0.01415 | 0.01992 | 0.02296 | 0.03662 | 0.04810 | 0.05716 | **0.06054** |

**82× at epoch 8**, and CONSIST **clears the variance floor at epoch 7**. The baseline collapses
harder than Phase 1 did (0.0007 vs 0.0031), because the wider 28-candidate set makes the `e`-term
of `L_R` more destructive.

### Attribution — and it is not the variance floor

At epoch 8, unweighted `L_var = 0.00054`. Its weighted contribution is
`0.05 × 0.00054 = 2.7e-5`, against `L_S ≈ 0.50`. **The explicit variance floor is numerically
almost irrelevant at λ=0.05.** What moved `D_s` is the *removal* of `‖s(x) − s(x̃)‖²`, which was
directly crushing `s`. I did not raise λ_var — the charter forbids tuning it from DEV — so the
finding stands as measured: prediction consistency plus a near-inert floor is enough, because
the destructive term is gone.

`L_pair` did its job cleanly: `L_pair_S` 0.00415 → 0.00077, `L_pair_E` 0.00651 → 0.00099,
`L_pair_A` 0.01850 → 0.00459.

## Global semantic targets — still dead

Balanced accuracy at each arm's frozen checkpoint:

| target | BASE | CONSIST | base rate |
|---|---|---|---|
| `solvable` | 0.5000 | **0.5000** | 0.447 |
| `goal_satisfied` | 0.5000 | **0.5000** | 0.357 |
| `missing_information_present` | 0.5000 | **0.5000** | 0.164 |
| `contradiction_present` | 0.5000 | **0.5000** | 0.080 |
| `number_or_structure...` (count) | MAE 0.305 | MAE 0.260 | trivial-exact 0.840 |

**No global target rose above trivial in either arm.** `s` is now measurably diverse and still
carries no usable global signal.

## Candidate epistemic state — recovered and improved

| target | BASE (cap 28) | CONSIST (cap 28) | Phase 1 (cap 24) | base rate |
|---|---|---|---|---|
| `candidate_legal` | 0.5000 | **0.7328** | 0.7345 | 0.347 |
| `candidate_has_unmet_requirements` | 0.4989 | **0.7283** | 0.7345* | 0.653 |
| `candidate_applicable` | 0.4891 | 0.7409 | 0.7112 | 0.347 |
| `candidate_satisfies_goal` | 0.5000 | 0.5000 | 0.5000 | 0.324 |

\* Phase 1's true macro-F1 correction applies to that receipt; the balanced-accuracy figure is
unaffected.

The baseline arm is what makes this interpretable: under the *same* wider candidate contract,
raw latent invariance drives candidate learning to **0.500 — worse than Phase 1 managed at the
narrower cap**. So CONSIST's recovery to 0.7328 is attributable to the objective, not to the
larger candidate set. Already-learned state was preserved and slightly exceeded.

## Action endpoint — still at or below chance

```
                top-1     chance    MOVE (n=346)   ACTIVATE (n=150)   NOOP (n=435)
P2-BASE        0.0000    0.0357    0.0000         0.0000             0.0000
P2-CONSIST     0.0279    0.0357    0.0029         0.0000             0.0575
```

Coverage 0.466, abstention worlds masked. Still no learning. NOOP is the only type above zero and
it is the majority class.

## Renderer stability — reported separately, and confounded

| | pairs | S disagreement | E disagreement | A disagreement |
|---|---|---|---|---|
| P2-BASE | 332 | 0.0000 | 0.0008 | 0.0004 |
| P2-CONSIST | 332 | 0.0000 | 0.0157 | 0.1373 |

**Read these with `D_s`, never alone.** BASE achieves near-perfect renderer stability *by being
constant* — every global head predicts one class for all 2,000 rows, so `S` disagreement of 0.0
is vacuous, not earned. CONSIST's E and A disagreement are **higher** precisely because its
predictions are less collapsed. On this lane, renderer stability is not a success metric; it is
a collapse detector pointed the wrong way.

## Candidate conditioning

| | within/between | conditioned |
|---|---|---|
| P2-BASE | 33.35 | yes |
| P2-CONSIST | 6.77 | yes |

Survives in both. The ratio falls because CONSIST's `e` is less extremely peaked per candidate.

## A selection-rule problem this phase made visible

The frozen rule — lowest DEV semantic+epistemic BCE, unchanged from Phase 1 and identical across
arms — picked **epoch 5** for BASE and **epoch 1** for CONSIST. BCE on skewed targets is
prior-dominated, so the rule systematically prefers the most collapsed checkpoint. For CONSIST
it selects `D_s=0.0115` over `D_s=0.0605` — **it selects against the very objective it is meant
to evaluate.**

I did not change it. Retro-fitting a selection rule to DEV is the thing this program forbids.
The full per-epoch trajectory is in both receipts.

## Answer to the phase question

| | |
|---|---|
| renderer-stable **semantic** state | **No.** No global target beats trivial in either arm. |
| renderer-stable **action** state | **No.** Endpoint at or below chance; MOVE 0.003. |
| invariance without rewarding collapse | **Yes.** `D_s` 82×, floor cleared at epoch 7. |

**The objective was suppressing the representation, and removing the raw latent term fixed
that.** That is a real, actionable result and it is the phase's main positive finding.

**But it was not the whole bottleneck.** Restored variance did not produce discriminative global
state. So the binding constraint has moved: it is no longer representational collapse, and Phase 1
already showed it is not a broken gradient path. That points Phase 3 at the **global readout
objective** (class-imbalanced BCE on skewed targets, where the prior is near-optimal) and at
**model-internal computation** — explicitly *not* at more anti-collapse machinery, and explicitly
not at substrate or interface structure yet.

For the causal lane's questions, the encoder lane's answers are: `s` **did** stop collapsing, and
**no** global target rose above trivial. MOVE remains at 0.003 here, so if causal MOVE recovers
under the same intervention that is a genuine phenotype difference worth carrying into the
cross-lane synthesis.

## Exit

```
CANDIDATE_UNIVERSE_EXHAUSTIVE      true    m_cap=28 measured, nothing truncated
SAME_INIT_ACROSS_ARMS              true    phase0-init.pt
OBJECTIVE_ONLY_CHANGE              true    substrate/surfaces/graft/dims/targets/splits frozen
NO_WEIGHT_TUNED_FROM_DEV           true
L_CF_DORMANT_NOT_INVENTED          true
COLLAPSE_ARRESTED                  true    D_s 82x, floor cleared epoch 7
GLOBAL_TARGETS_ABOVE_TRIVIAL       false   PRESERVED FAILURE
ACTION_ENDPOINT_ABOVE_CHANCE       false   PRESERVED FAILURE
PROTECTED_TEST_TRUTH_OPENED        false
BANK_V2_USED                       false
```

## Artifacts

- `D:\codex-runs\encoder-contrast-01\phase2\candidate-preflight.json`
- `D:\codex-runs\encoder-contrast-01\phase2\base\phase2-base-receipt.json` + 8 checkpoints
- `D:\codex-runs\encoder-contrast-01\phase2\consist\phase2-consist-receipt.json` + 8 checkpoints
- `D:\codex-runs\encoder-contrast-01\phase2\phase2-synthesis.json`
- `D:\codex-runs\encoder-contrast-01\phase2\phase0-init.pt`, `sigma0-global-state.pt`

No architecture rescue was attempted. No covariance penalty. No extra heads. No new supervision.
No cross-lane numerical gate.
