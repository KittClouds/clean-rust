# DH-04: erasure versus reversed acquisition

Status: pre-execution protocol. The launcher freezes this file, source, analysis,
executable, and inherited anatomy before the first DH-04 anatomy-task outcome.

DH-03 found that retaining distractor-generated eligibility improved final
reversal accuracy by 6.836 percentage points while restoring interval neural
state had no detectable effect. Both eligibility-retained cells remained below
chance. DH-04 tests the resulting hypothesis that interval eligibility primarily
erases the acquired mapping rather than acquiring the reversed mapping.

## Causal conditions

All conditions receive the same 256 immediate-reward acquisition trials. Reversal
then uses four branches:

| Condition | Reversal treatment |
| --- | --- |
| immediate | Reward immediately after the cue |
| quiet | Reward after twelve zero-input state updates |
| eligibility_retained | Twelve distractors; retain their eligibility; restore post-cue neural state |
| eligibility_suppressed | Same distractors; delete their eligibility; restore post-cue neural state |

The two causal cells process identical distractors and RNG draws. Both restore
baseline, MBON activity/probabilities, signed MBON activity, DAN activity,
feedback, and gain after every interval. Both preserve elapsed trace scale, RNG,
weights, counters, and cue-trace decay. Eligibility suppression alone restores
the unscaled trace to its post-cue snapshot.

Use 24 fresh seeds 4000 through 4023, disjoint from DH-01 through DH-03. Retain
the same MaleCNS slices, task patterns, input salt, neuron equations, eta, taus,
weight bounds, uniform-learning E arm, and fixed-weight Z control. Immediate and
quiet are descriptive anchors.

## Prespecified measurements

At construction save initial weights W0. At the acquisition/reversal boundary
save acquired weights WA. At completion save final weights WF only long enough
to compute compact geometry; full arrays are not written to scientific outputs.

Define the acquisition-axis coordinate:

    q = dot(WF-W0, WA-W0) / squared_norm(WA-W0)

Thus initial weights have q=0 and acquired weights q=1. A final q between zero
and one is partial movement back toward the initial state. A negative q crosses
the initial point along the acquisition axis. Also record distances normalized
by the acquisition displacement.

For each cue, compute the expected MBON action score directly from frozen weights
without sampling. Multiply by the old target sign and average across cues and
MBON count. Positive old-map margin means the old mapping remains preferred;
negative margin means the reversed mapping is preferred.

Run frozen-weight old- and reversed-map probes with the exact same random draws.
Their accuracies must sum to one. This removes the different-probe-RNG ambiguity
in DH-02 and DH-03.

The immediate branch supplies a within-seed successful-reversal reference.
Record each reversal weight delta's cosine with the immediate delta and normalized
distance to the immediate final weights. For the causal difference
W_retained-W_suppressed, record projection onto the negative acquisition axis,
cosine with the immediate reversal delta, and norm relative to acquisition.
These reference-alignment measures are descriptive because successful reversal
can itself include erasure.

## Primary mechanism rule

Average taus inside each of the 24 right-slice E seed bundles. Use one paired
bootstrap index matrix with 20,000 resamples and seed 2026091204. Report paired
95% percentile intervals.

Classify **PARTIAL_ERASURE_SUPPORTED_IN_MODEL** only if all four conditions hold:

1. retained minus suppressed same-RNG reversed-probe accuracy has CI wholly above
   zero;
2. retained minus suppressed acquisition-axis coordinate has CI wholly below
   zero;
3. retained final acquisition-axis coordinate has CI wholly above zero and
   wholly below one;
4. retained final deterministic old-map margin has CI wholly above zero.

This is an intersection-union claim: every component must pass at the stated
level. If the retained coordinate and old-map margin are wholly below zero while
reversed accuracy improves, classify **REVERSED_ACQUISITION_SUPPORTED_IN_MODEL**.
Otherwise classify **MECHANISM_UNRESOLVED** and report every component.

The paired standard reversal probe, online/late accuracy, quiet/immediate anchors,
left slice, tau-specific effects, weight distances, immediate-reference
alignment, and eligibility-contrast geometry are descriptive.

## Required audits and limits

Before execution require exact compatibility of the two causal cells with DH-03
restore-state and suppress-both, exact shared acquisition hashes, exact state
restoration and assigned eligibility deletion, same-RNG probe complementarity,
fixed-weight action parity, observer noninterference, deterministic replay,
SIMD/scalar parity, graph-null invariants, complete-grid analysis failure, and
zero online allocations.

After sealing, replay one real right-slice bundle across all four conditions and
both arms with observers enabled and removed. This adds no scientific sample.

Weight-axis geometry is model-coordinate evidence, not a unique causal
decomposition. Clipping, positive weight bounds, broad sparse overlap, and
nonlinear readout can make weight and behavior geometry disagree. Old-map margin
uses the model's expected action score, not biological activity. The experiment
uses one specimen, related soma-side slices, synthetic labels and dynamics, trial
resets, and uniform modulation. It cannot establish a biological forgetting
mechanism or a general learning principle.

No endpoint change, parameter rescue, extra seed, new condition, rule search, or
post-outcome tuning is permitted. Preserve all attempts and failures.

Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY:
https://male-cns.janelia.org/download/ . Source hashes and anatomy are inherited
unchanged through the frozen DH-03 parent.
