# DH-02: temporal credit and distractor interference

Status: pre-execution protocol, frozen by the launcher before fresh outcomes.
DH-01 informed this question; DH-01 results are not confirmation data for DH-02.

## Question and primary endpoint

From an IDENTICAL acquired learner state, does activity during a twelve-step
reward delay impair recovery after association reversal, relative to the same
delay without sensory activity?

Primary endpoint: final frozen-weight reversal-probe accuracy, quiet minus
distractor, uniform modulation E, right soma slice. Each probe has sixteen
repetitions per cue (256 presentations). Average the two eligibility time
constants INSIDE each seed bundle; bootstrap the 24 complete bundles 20,000
times with seed 2026091202. A positive 95% lower bound is evidence for the
specified total distractor-exposure effect. This does not isolate eligibility
contamination from other state changes caused by the distractors.

All acquisition, late-window, online reversal, left-slice, and immediate-versus-
delay comparisons are descriptive secondary outcomes. No endpoint selection,
rescue tuning, extra training, or learning-rule search after seeing outcomes.

## Frozen design

24 NEW seeds, 2000 through 2023. Eligibility tau in {4,16}; eta=0.05. Same
16-cue acquisition/reversal family, same 256+256 training trials, same neuron
equations, fixed readout and weight bounds as DH-01. Input salt 858980352 gives
new sensory patterns and labels. Each task schedule includes all twelve
distractor slots even when a condition will ignore them. Every condition and
arm sees exactly the same cue identity schedule and target mapping per bundle.
All conditions first receive 256 COMMON IMMEDIATE-REWARD acquisition trials.
Only the 256 reversal trials use their assigned condition. Thus the experiment
isolates reversal exposure rather than mixing in different acquisition strength.
Pre-reversal weights, traces, baseline, post activity, DAN/feedback/gain arrays
and RNG are hashed and must match across all three conditions within each arm,
seed, side and tau. Acquisition summaries are repeated checkpoints, not extra
independent samples. The predeclared total arm-trial count includes these
repeated acquisition computations; unique acquisition streams are reported too.

| Reversal condition | Reward | Interval activity |
| --- | --- | --- |
| immediate | Immediately after cue/action | No time advances |
| quiet | After 12 steps | Zero sensory KC activity, normal internal dynamics |
| distractor | After 12 steps | 12 unrelated sensory patterns, normal dynamics |

Quiet uses an explicit empty sparse pattern, bypassing top-k selection. It
still updates postsynaptic baseline, MBON activity, DAN state and eligibility
decay. No presynaptic KC activity means no new eligibility contribution.
Immediate discards the RNG draws corresponding to twelve unused events AFTER
reward, without changing neural state or clock. This aligns subsequent cue
random draws across conditions and is tested with the no-learning control.

Only E (uniform reward modulation) and Z (disabled plasticity) are learning
arms. Anatomical versus shuffled routing is an OBSERVATION-ONLY counterfactual
on the same DAN state, not two separately trained arms. All signal topology
is anatomical. Both R and L soma slices run, but they are one specimen; L is
descriptive related-structure replication, not an independent animal.

Glutamatergic MBON feedback is fixed negative. Changing it has no causal path to
uniform E or disabled Z plasticity in this model, so redundant sign arms are
omitted. It does affect shadow DAN/routing diagnostics; no sign-robust conclusion
about routing is made. The four other graph/neuron kernels are inherited byte-
for-byte from DH-01 where possible; the archived DH-01 simulator is compiled only
for compatibility tests. No DH-01 files are edited or overwritten.

## Observation-only diagnostics

Before delayed reward, let c be the cue-generated eligibility component decayed
to the current time; let q be the post-cue component and e=c+q the total.
The observer copies the cue trace after the cue and reads current eligibility
at reward; it never writes the learner's trace, weights, RNG, or neuronal state.
Record mean L1 norms of c, q and e; mean cue component share
||c||1/(||c||1+||q||1), and cancellation 1-||e||1/(||c||1+||q||1).
These are pre-clipping credit proxies, not additive fractions of observed weight
change and not proof that any particular update is causally wrong.

At reward record pre-update weight fractions exactly at 0 and 2 and proposed
out-of-bounds update fraction. Disabled Z has update coefficient zero. Record
cue-only output saturation p<=0.01 or p>=0.99 and mean spike probability.
Record terminal weight-bound fractions after training. Phase labels are observer
metadata only; the learner only gets the environmental scalar reward.

Compute anatomical gain gA, a degree-preserving routing-null gain gB and uniform
gain 1 from the SAME current DAN state. Use the original DH-01 averaging and
global delivered-mass normalization. Weight each target by plastic fan-in and
record relative RMS ||gA-gB||/||gA||, cosine similarity, distances to uniform,
DAN activity coefficient of variation, and fraction of observations with relative
RMS below 1%. The 1% threshold is a descriptive scale marker, not a discovery gate.
No counterfactual gain is ever supplied to E/Z learning. This diagnoses signal
separation on DH-02 states; it does not replay DH-01 trajectories.

## Qualification, lineage and limits

Require exact DH-01 distractor-engine compatibility, observer-on/off equivalence,
no-learning cue-action equivalence across conditions, quiet zero-input semantics,
trace decomposition checks, graph-null invariants, SIMD/scalar parity,
deterministic replay, and zero hot-loop allocations before the first new run.
All tests use synthetic fixtures. A real-slice one-bundle post-run replay compares
all conditions and arms and does not increase scientific sample size.

The seal includes source, executable, lockfile, configuration, analysis code,
qualification logs, and the original hash-verified extracted anatomy. Complete
all 576 arm runs (294,912 training trials). Missing or duplicated cells fail the
analysis rather than being dropped. Preserve attempted runs and failures.

The fixed sparse features, positive bounded weights, stochastic readout, global
top-k inhibition, assumed dynamics and externally reset trial boundaries remain
modelling choices. Time-step delay also changes baseline/internal-state updates;
quiet versus distractor isolates sensory exposure at equal step counts, not a
single internal mechanism. No biological or universal-learning claim follows.

Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY:
https://male-cns.janelia.org/download/ . Source hashes and extraction boundary are
in DH-01's archived census and are reused unchanged.
