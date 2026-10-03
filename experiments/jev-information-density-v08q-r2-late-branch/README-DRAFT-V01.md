# JEV v0.8Q-R2 — paired late-SHAM-weight branch study

**Status:** `SEALED_AUTHORIZED_FOR_PHASE_EXECUTION`  
**Training authorization:** true under phase packet v01  
**Panel generation authorization:** true under phase packet v01  
**Model contact / inference:** authorized only under the sealed contracts

## Question

After every seed follows the same SHAM-weight-1.0 history through optimizer
step 80, what is the paired effect of changing only the auxiliary SHAM loss
multiplier for steps 81–120 from 1.0 to 0.5?

This is a new late-stage intervention estimand. It is **not** a rerun of Q or
Q-R1's full-course SHAM-LOW arm, where the 0.5 multiplier applied throughout
training. The branch point at step 80 was selected after observing Q-R1; R2
tests this chosen late-training contrast and does not claim step 80 is
universally special.

## Design at a glance

- 24 new deterministic optimizer seeds, paired within seed.
- One common prefix per seed: original SHAM recipe, weight 1.0, steps 1–80.
- Save the complete step-80 head, AdamW state, RNG states, and event cursor.
- Fork that exact state into two continuations, steps 81–120:
  - `LATE_SHAM_1X`: auxiliary multiplier remains 1.0.
  - `LATE_SHAM_HALF`: auxiliary multiplier becomes 0.5.
- The two branches share the same event identities, order, minibatches,
  optimizer state, RNG state, denominator, and all other training settings.
- Save the shared step-80 baseline and both branches at steps 100 and 120.
- 24 shared step-80 cells + 96 branch cells = **120 evaluation cells**.
- Fresh panel: 2,000 neighborhoods, 500 per existing family, four views per
  neighborhood. Expected prediction rows: **960,000**.
- Step 120 is primary; step 100 is intermediate; step 80 is the shared
  pre-branch baseline.

## What this identifies

For each observed step-80 state, the same trained head and optimizer state are
continued under both late weights. The within-seed contrast therefore
isolates the effect of the late multiplier under that common SHAM history,
subject to the frozen implementation and deterministic event stream.

It does not estimate the effect of training at half weight from step 1, does
not establish a universal control law, and does not test novel families or
templates. Step-80 moderator analyses are secondary and remain conditional on
the common SHAM history.

## Primary response vector

Report paired `HALF − 1X` differences separately for:

- continuous fact response and direction;
- actual fact-view new-winner rate (`F_new`) and strict anchor-old to fact-new
  transition;
- anchor old-winner preservation (`A_old`);
- sham and matched-neutral posterior L1 and MAP flips;
- exact-delta error;
- pairwise old/new margins and true multiclass winner gaps.

There is no composite score, operating-point label, checkpoint selection, or
single metric that can hide a loss in another response coordinate. Show all
24 seed-level paired vectors and family breakouts.

## State moderation

The step-80 state is measured once, before either late branch is executed.
The two predeclared moderator relationships are:

1. step-80 fact new-winner gap versus the paired late-weight effect on new
   probability movement;
2. step-80 anchor old-winner gap versus the paired late-weight effect on
   anchor old-winner preservation.

Use simple per-seed, family-stratified slopes and show all 24 estimates. The
other contracted step-80 coordinates remain descriptive. No flexible
predictor, threshold search, or policy training is included. This experiment
can motivate a later prospective policy test; it cannot validate a controller.

## Execution firewall

The panel and its frozen representation cache are constructed and sealed
before training. All 24 common prefixes and all 48 branch continuations run
without evaluation feedback. Seal every training artifact before one panel
opening. Generate the complete prediction matrix before computing any
outcome metric. No NewTight, Phoenix, extra dose, extra steps, rescue branch,
checkpoint substitution, or post-result repair is authorized by this draft.

## Bound ancestry

- Q-R1 run contract: `e5fb3bd147bd5866849266937dc5b060abd8047c13faf2dea48908af518c1317`
- Q-R1 analysis contract: `98d5f781d8f98a9a2e6f3737ddbcb2765bbb1f174c25a01292db1e3e5cc4e81b`
- Q-R1 panel contract: `f81ea3fcb3445434dd2f9bfc92bf3c7aa6118efc605c157475b77d75b8e813b1`
- Q-R1 completion seal: `4e63e379671d7641cb174f1ed3db6ac8395b6c49e4c644392d55996eab1df68c`

Only sealed contracts and the completion receipt inform this design. Q-R1
predictions, per-neighborhood outcomes, or evaluation features are not R2
training inputs or panel-selection criteria.

See the machine-readable draft contracts in `contracts/`. No seal or
authorization receipt has been created.
