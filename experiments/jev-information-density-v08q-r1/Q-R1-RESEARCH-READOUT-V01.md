# JEV v0.8Q-R1 — research readout

Status: interpretive companion to the sealed Q-R1 result. This file does not
alter the sealed contracts, predictions, metrics, or analysis. Seed summaries
below are descriptive for the 12 observed paired trajectories; they are not a
seed-population estimate.

## Result in one paragraph

The fixed `0.5 × SHAM` intervention did not produce a reproducible operating
point under the registered same-seed rule. Only **1/12** seeds jointly passed
gain, direction, material locality advantage over DUP, and preservation,
against the registered **8/12** cohort threshold. No seed met the registered
stiff-coupling label (**0/12**). The separate MAP-response label passed in
**4/12**. At the same time, SHAM-LOW's 12-seed arithmetic mean was higher than
SHAM on continuous new-candidate movement and fact MAP response, but those
averages conceal large reversals, boundary crossings, and locality costs in
different seeds. The evidence supports a heterogeneous fixed-dose response,
not a reliable scalar gain/locality control.

## Step-120 descriptive arm means

Means below average the 12 paired seed-level panel summaries. They describe
these runs only; the neighborhood bootstrap intervals in the sealed result
condition on each seed and the fixed panel and do not turn 12 seeds into a
population sample.

| Arm | New-probability movement | Correct direction | `F_new` | Strict transition | `A_old` | Sham L1 | Matched L1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| DUP | 0.13212 | 0.958 | 0.684 | 0.549 | 0.796 | 0.12856 | 0.07608 |
| MATCHED | 0.05833 | 0.917 | 0.166 | 0.166 | 0.831 | 0.04311 | 0.00423 |
| SHAM | 0.05339 | 0.813 | 0.200 | 0.200 | 0.958 | 0.02275 | 0.01229 |
| SHAM-LOW | 0.07828 | 0.908 | 0.339 | 0.310 | 0.930 | 0.04672 | 0.02724 |

The paired SHAM-LOW minus SHAM point means were **+0.02489** for new-candidate
probability movement, **+13.90 percentage points** for `F_new`, and **+10.996
points** for strict transition. Locality moved in the opposite direction on
average: sham L1 rose by **0.02396** and matched L1 by **0.01495**. Anchor
old-winner preservation changed by **−2.80 points** on average. These are
descriptive averages, not a claim that the intervention moves each run along
that vector: the registered same-seed counts show otherwise.

## The joint rule and why the mean is not the answer

| Registered same-seed predicate | Passes |
|---|---:|
| Material continuous gain | 3/12 |
| Direction | 9/12 |
| Material locality advantage over DUP | 9/12 |
| Preservation | 10/12 |
| Full operating-point conjunction | **1/12** |
| Stiff-coupling conjunction | **0/12** |
| Separate MAP-response predicate | 4/12 |

The registered operating-point conjunction is gain + direction + locality +
preservation; it does **not** require MAP crossing. Its sole passing seed,
`534474641`, had SHAM-LOW movement **0.04579** versus SHAM **0.00149**, preserved
the anchor (`A_old = 1.000`), and retained material locality versus DUP, but
`F_new` and strict transition were only **0.0405**. Thus the one registered
operating-point pass is evidence for the exact continuous/locality predicate,
not evidence that the new fact winner was commonly acquired.

No cross-seed assembly is used. The separate counts of gain, direction,
locality, and preservation cannot be combined as though the same seeds passed
each one; only the **1/12** joint count answers the operating-point rule.

## Contrasting trajectories

- Seed `4241626823` is the high-gain/high-crossing case: SHAM-LOW had movement
  **0.28792**, `F_new = 0.985`, and strict transition **0.983**. But sham L1 was
  **0.13082** versus DUP **0.00910**, and matched L1 was **0.07795** versus DUP
  **0.00531**. It gained boundary crossings while losing the required locality
  advantage.
- Seed `4245719435` moved the other way: SHAM had movement **0.06595** and
  `F_new = 0.468`; SHAM-LOW fell to **0.01396** and `F_new = 0`. Lowering the
  weight did not monotonically increase response.
- Seed `949206414` retained high but reduced crossings (`F_new` **0.964 →
  0.9105**, strict **0.964 → 0.814**) and lost anchor preservation (`A_old`
  **1.000 → 0.9035**) while remaining more local than DUP. This separates the
  movement/crossing and preservation coordinates.
- Seed `3972258` had `F_new` **0.7415** but strict transition only **0.491** and
  `A_old = 0.4995`: many fact-view wins coexisted with anchor losses. The
  multiclass winner and the joint old-to-new transition must remain separate.

Across seeds, SHAM-LOW movement was positive relative to SHAM in 7 and negative
in 5; `F_new` was higher in 5, lower in 3, and tied in 4. Sham L1 increased in
8 and decreased in 4. The same half-weight change therefore did not implement
one consistent movement in response space.

## Trajectory and family reading

Across-seed means show little discrete fact response at steps 40–80, followed
by heterogeneous acquisition at 100 and 120. For SHAM-LOW, mean `F_new` was
**0.02**, **0.06**, **0.19**, and **0.34** at steps **40, 80, 100, 120**;
strict transition was **0.00**, **0.02**, **0.16**, and **0.31**. These sparse
checkpoints do not locate an onset within the intervals, and the averages do
not imply a shared transition.

The respiratory-crossing/vibration-preservation pairing did not recur as a
stable signature. For example, seed `4241626823` had broad SHAM-LOW crossings
including vibration while preserving vibration anchors; seed `3972258` had
high crossings in exposure, respiratory, and salinity but none in vibration,
alongside anchor losses in respiratory and vibration; seed `949206414` had
substantial crossings across all four families but its largest preservation
loss in respiratory. These are family-by-trajectory observations, not grounds
for family-specific training changes.

The step-80 analysis is a **post-exposure landmark**: every arm has already
trained through step 80. Its quartiles and associations are descriptive and
cannot establish pre-treatment prediction or causal mediation. The 12 shared
initialization states are reported separately as pre-treatment context; no
predictor was fitted.

## Research direction

1. Close Q-R1 as a failed replication of the **reliable** half-weight operating
   point, while preserving the finding that the intervention can alter the
   response vector in some trajectories.
2. Do not launch another scalar-dose sweep. Q and Q-R1 together do not support
   weight as a universal gain/locality knob; Q-R1's 1/12 joint pass and 0/12
   stiff-coupling count are the decision-relevant results.
3. The sharper follow-up is a **late-stage randomized branch experiment**:
   train a common, prospectively fixed history to step 80, save the optimizer
   state, then fork each seed into exactly two continuations for steps 81–120:
   SHAM weight 1.0 versus 0.5. The step-80 state is then measured before the
   randomized late-phase contrast, unlike Q-R1's four step-80 states, each of
   which already reflects its arm. Test whether the frozen step-80 state
   coordinates modify the paired late-dose effect on gain, actual MAP crossing,
   locality, and preservation. Use a fresh panel and new seeds; set the seed
   count from the desired precision/operational budget before execution, not
   by reusing Q-R1's 12 as if it were a population estimate.
4. Keep the shared initialization state table as context, but do not fit a
   phenotype predictor from these 12 seeds. Do not use Q-R1's held-out panel to
   tune a controller. If the late-branch interaction does not replicate, stop
   promoting state-conditioned control and report the heterogeneity as
   trajectory-specific under the tested recipe.

This is still not an optimizer-basin or mechanism result. The defensible
conclusion is narrower: on this fresh panel and these 12 paired trajectories,
the fixed half-weight intervention produced heterogeneous changes in gain,
multiclass crossing, locality, and preservation; its preregistered joint
operating-point criterion did not replicate at the cohort threshold.

## Provenance

- Panel root: `f90fc1de0ce1e728e4b6c72cbc58756e2278c5932adb77dcf33f2b9dff2b6f53`
- Prediction SHA-256: `380c67afb7d9fac36c2919d76327252f266975eaa4bab5a5ca4e4556b941c4ef`
- Analysis seal SHA-256: `1596b680844fd50fdf4d19721dd612b792711080e4262d247f240b3c6ee877c5`
- Independent replay receipt SHA-256: `44ea260cdb57eb48cc7f266ddab0b334519c8d20aa8e8bff8818da5abb2e4652`
- Completion seal SHA-256: `4e63e379671d7641cb174f1ed3db6ac8395b6c49e4c644392d55996eab1df68c`
- The first evaluation plumbing failure and its one initialization cell were
  retained as provenance; continuation used the same single panel opening,
  repeated no training or first-cell inference, and changed no metric or
  threshold.
