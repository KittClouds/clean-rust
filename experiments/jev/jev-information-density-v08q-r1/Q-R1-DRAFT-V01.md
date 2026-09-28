# JEV v0.8Q-R1 — Fixed-Dose Response-Phenotype Replication

**Status: SEALED AND AUTHORIZED FOR ONE PHASE-SIZED EXECUTION.**

## Research question

On fresh worlds under the same four-arm design, how often do the already-registered v0.8Q same-seed response predicates recur, and what decision-state coordinates accompany each trajectory?

The intended claim is a fresh-world replication under the same four families and fixed generator/template semantics. It is not novel-family or novel-template generalization, and 12 observed optimizer seeds do not establish a universal response law.

## Sealed Q evidence motivating this replication

At step 120, the three Q seeds produced distinct joint outcomes under `SHAM-LOW`:

| Seed | `SHAM → LOW` new-probability movement | Fact new-MAP `SHAM → LOW` | Anchor old-MAP `SHAM → LOW` | SHAM L1 `DUP → LOW` | Joint operating-point label |
|---:|---:|---:|---:|---:|:---:|
| 2540205348 | 0.036342 → 0.097117 (+0.060775) | 0.00% → 0.00% | 100.00% → 100.00% | 0.179714 → 0.071095 | Pass |
| 2603246505 | 0.011231 → 0.011453 (+0.000223) | 0.00% → 16.35% | 99.95% → 78.35% | 0.157825 → 0.014400 | Fail |
| 3565067208 | 0.010809 → 0.115439 (+0.104631) | 0.00% → 69.05% | 100.00% → 99.95% | 0.043037 → 0.083123 | Fail |

Thus only **1/3** seeds passed the registered joint operating-point predicate; `q_map_response_seed_pass` was **2/3**, while `q_stiff_coupling_seed` was **0/3**. In seed 2603246505, **327/500 respiratory** neighborhoods crossed to the fact-new MAP, while vibration anchor preservation fell from **99.8% under SHAM to 13.4% under SHAM-LOW**. In seed 3565067208, **219** neighborhoods had a nonnegative new-versus-old pairwise probability margin without the new candidate winning the four-way MAP. These are the concrete reasons R1 measures pairwise relation, true multiclass winner gaps, family outcomes, and locality separately.

The Q-X1 values are motivation only. Its available outputs were probabilities, not logits; its margins are probability differences and must not be described as logit margins. Q-X1 revalidated its reconstructed step-120 summaries against the frozen Q analysis within `1e-6`. The sealed Q and Q-X1 artifacts remain historical references, not R1 training or panel inputs.

## What stays fixed

The concurrent arms remain:

```text
B-DUP
B-MATCHED
B-SHAM
B-SHAM-LOW = 0.5 × SHAM auxiliary event loss weight
```

SHAM-LOW uses the exact SHAM auxiliary identities, event count and positions. Only its multiplier changes, scaling the semantic and Brier terms while retaining the original total-active-event denominator. No dose sweep, event-frequency change, family-specific weighting, head/optimizer change, added steps, or checkpoint selection.

Reuse the sealed Q primary stream, auxiliary manifests, feature sources, and training recipe by hash. Use 12 new paired seeds, derived in the run contract, with a common initialization and schedule across the four arms within each seed. The fixed scientific checkpoints are **40, 80, 100, and 120**; 120 remains primary. The inherited Q 42-checkpoint field is explicitly historical and non-normative: R1 follows the executed four-checkpoint schedule bound by the Q result supplement SHA-256 `387d66bfe0617d721a17de4442a2079ef91dd8a1ba74fe725f1e0d5a7e1786f6`. This precedence rule does not amend Q.

The prospectively derived R1 seeds are:

```text
77720160, 4245719435, 3815947415, 3112928194,
4241626823, 534474641, 3124582801, 4247677041,
811956520, 3972258, 950790373, 949206414
```

This is 48 runs (four arms × 12 seeds), four scientific checkpoints per run (192 trained checkpoints), and 12 shared initialization states. At Q's four-view panel shape the prediction matrix is 1,632,000 rows—four times Q's run count, while retaining the same small frozen head and 120-step budget.

The new held-out panel contains 2,000 neighborhoods, 500 per fixed family, with the same A/fact/sham/radius-matched-neutral measurement surfaces and feature recipe. Each admitted neighborhood must be disjoint on **all five contracted identity fields** from training, E1, P-R2, Q, and already-admitted R1 neighborhoods. Exact identity sources are hash-bound: training (55,000 rows), E1 (22,000 rows; its identity manifest is bound by the R1 terminal disposition and matches the v05 E1 neighborhood-ID hash set), P-R2 (22,000 rows; identity-file digest independently matched to the bound materialization manifest), and Q (22,000 rows). E1’s existing neighborhood-ID denylist remains an additional separate check. Missing any required ancestry set fails closed before candidate generation. Matching remains Q’s radius-only rule and gates. No Q-X1 rows or predictions enter panel construction, training, or evaluation.

## Added geometry measurements

Keep Q’s original response coordinates and same-seed gates unchanged. Add, for every seed × arm × checkpoint × family × neighborhood:

```text
pairwise anchor margin:       P_A(new) - P_A(old)
pairwise fact margin:         P_F(new) - P_F(old)
fact-conditioned margin move: fact margin - anchor margin
new probability movement:     P_F(new) - P_A(new)
old probability movement:     P_F(old) - P_A(old)

anchor old-winner gap:        P_A(old) - max(P_A(c), c != old)
fact new-winner gap:          P_F(new) - max(P_F(c), c != new)
strongest competitor ID      (ties resolved by frozen candidate order)
frozen anchor/fact argmax candidate IDs
F_new, Strict, A_old, locality, and family preservation
```

The probability-space multiclass gap is positive for a unique intended winner, negative when it loses, and zero for a tie. The actual frozen argmax candidate ID remains a separate output; the gap never substitutes for `F_new` or `A_old`. Pairwise old/new margin remains another separate coordinate. No composite score is created.

## Analysis hierarchy

1. **Primary:** step-120 response matrix for all 12 seeds, with the unchanged Q seed predicates and counts out of 12. Preserve the two-thirds cohort threshold (`8/12`) and evaluate every conjunction within the same seed; never combine gain, locality, or preservation passes across seeds.
2. **Secondary:** family-level crossing, winner gaps, anchor preservation, and locality, especially the predeclared descriptive question of whether respiratory fact crossings co-occur with vibration anchor-preservation loss.
3. **Secondary landmark analysis:** relate a fixed set of step-80 coordinates—two pairwise margins, two multiclass gaps, new-candidate probability movement, sham L1, matched L1, plus `A_old`/`F_new` status and actual argmax IDs—to step-120 outcomes. Quartiles are formed only from each continuous step-80 variable, within seed × arm × family, sorted by that value then canonical neighborhood ID; binary statuses are cross-tabulated, not quartiled. This is a post-exposure landmark association, not a pre-treatment adjustment, causal mediation, or proof that state predicts intervention response.
4. **Initialization context:** report the 12 shared initialization states beside the four arm-specific terminal outcomes for each seed. These are descriptive pre-treatment context, not an extra arm, gate, predictor, or causal claim.

Keep the four checkpoints only. No extra epochs, dense step sweep, “best checkpoint,” or adaptation from intermediate outcomes. Report all 12 trajectories; resampling uncertainty is conditional on each seed and the fixed panel, while seed recurrence is descriptive n/12.

## Execution boundary

The run, panel, and analysis contracts are separate machine-readable drafts in `contracts/`. All authority flags remain false. After review and explicit authorization, the intended packet can proceed phase-wise: build and seal the fresh panel; verify the complete run schedule and contracts; train all 48 runs without evaluation feedback; seal all checkpoints and telemetry; open the panel once; produce and seal all predictions; then analyze the complete matrix with the frozen code.

The sealed packet authorizes the single frozen phase through result sealing. It has not yet started panel construction or training. If a contracted invariant fails, preserve the attempt and stop without changing the contract, seeds, thresholds, or panel identity.
