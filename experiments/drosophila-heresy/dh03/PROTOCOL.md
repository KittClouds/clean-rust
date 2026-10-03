# DH-03: causal split of interval eligibility and neural-state persistence

Status: pre-execution protocol. The launcher must freeze this file before any
DH-03 anatomy-task outcome is computed. DH-02 supplied the question: distractor
delay outperformed quiet delay despite both conditions remaining below chance.
DH-02 outcomes are discovery evidence and are not DH-03 confirmation samples.

## Question and co-primary endpoints

During twelve distractor events between a cue and reward, does final reversal
performance depend on (1) retaining distractor-generated eligibility and/or
(2) retaining the non-eligibility neural state produced by those events?

The confirmatory design is a 2x2 intervention on every reversal interval:

| Condition | Interval eligibility delivered | Post-interval neural state delivered |
| --- | --- | --- |
| retain_both | Yes | Yes |
| suppress_eligibility | No | Yes |
| restore_state | Yes | No |
| suppress_both | No | No |

All four cells process the same twelve distractor patterns and consume the same
RNG draws. Suppressing eligibility restores the unscaled trace to its post-cue
snapshot after the interval, which preserves normal decay of cue eligibility
while deleting only contributions added by distractor events. Restoring state
copies baseline, MBON activity/probabilities, signed MBON activity, DAN activity,
feedback, and modulation gain back to their post-cue values. It does not restore
weights, eligibility, elapsed trace scale, event/work counters, or RNG.

The two co-primary effects use right-slice uniform learning and final frozen-weight
reversal-probe accuracy. Within each seed, average the two eligibility time
constants before inference:

1. eligibility-retention effect = mean(retain_both, restore_state) minus
   mean(suppress_eligibility, suppress_both);
2. state-retention effect = mean(retain_both, suppress_eligibility) minus
   mean(restore_state, suppress_both).

Bootstrap the 24 paired seed bundles 20,000 times with seed 2026091203. Report
ordinary paired 95% percentile intervals and Bonferroni-compatible 97.5%
intervals for the two-effect family. A 97.5% interval wholly above zero supports
that channel as beneficial in this model; wholly below zero supports it as
harmful; overlap with zero is inconclusive. The factorial interaction and all
left-slice, online, late-window, tau-specific, immediate, and quiet comparisons
are descriptive.

## Frozen design

Use 24 fresh seeds 3000 through 3023, disjoint from DH-01 and DH-02. Keep the
DH-02 graph, task family, input salt 858980352, 16 cues, 256 immediate-reward
acquisition trials, 256 reversal trials, eta 0.05, taus 4 and 16, negative
glutamatergic MBON feedback, fixed readout, bounded positive weights, and local
covariance eligibility rule unchanged.

Every condition begins with the same immediate-reward acquisition phase.
Weights, eligibility, baseline, MBON state, DAN/feedback/gain arrays, and RNG
are hashed at the split and must match within seed, side, tau, and arm. Immediate
and quiet-delay conditions are retained as descriptive anchors. E uses uniform
reward modulation; Z disables plasticity. Anatomical versus degree-preserving
shuffled routing remains observer-only and never reaches the learner.

The state intervention targets persistence beyond an interval. Within-interval
neural dynamics still occur and can shape the eligibility generated during that
interval. Repeating the intervention across reversal can also change eligibility
formation on later trials through its effect on prior baseline state. The
factorial effects are therefore causal effects of retaining these two channels
throughout reversal, not a one-step statistical mediation decomposition.

## Required audits

Before execution, require:

- exact untreated-cell compatibility with the frozen DH-02 distractor engine;
- exact post-cue acquisition-state equality across all six conditions;
- nonzero raw distractor eligibility and neural-state drift in every factorial
  cell on synthetic fixtures;
- zero delivered interval eligibility only in assigned suppression cells;
- bit-exact state restoration only in assigned restoration cells;
- identical cue actions and RNG pairing across all fixed-weight conditions;
- observer-on/off learner equivalence, deterministic replay, SIMD/scalar parity,
  graph-null invariants, and zero online allocations;
- complete analysis-grid and duplicate-cell failure tests.

After the sealed run, replay one real right-slice seed across all six conditions
and both arms with the observer enabled and disabled. This is verification and
does not enlarge the scientific sample.

## Limits

This is one specimen with related left/right soma slices, synthetic task labels,
assumed dynamics, global inhibition, trial resets, and an invented uniform
modulatory arm. State restoration combines several arrays, although only states
with a future causal path can affect uniform learning. Eligibility suppression
removes an aggregate interval trace rather than identifying particular synapses
or distractor events. The experiment can identify whether retaining each channel
helps or harms this model under repeated intervention; it cannot establish a
biological mechanism, universal learning rule, or benefit from distraction.

No parameter rescue, endpoint change, extra seed, model search, or post-outcome
tuning is permitted. Preserve all attempted runs and failures.

Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY:
https://male-cns.janelia.org/download/ . Source hashes and the extracted anatomy
boundary are inherited unchanged from the frozen DH-02 parent.
