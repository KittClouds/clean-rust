# DH-05: old memory or new memory?

Status: pre-execution protocol. DH-04 was already frozen and measured the final
partial-erasure signature. DH-05 adds only checkpoint trajectories to the same
two causal reversal cells. No intervention, learning rule, or endpoint is changed.

## Question

Does retained distractor eligibility improve reversal by weakening the acquired
mapping, by building the reversed mapping, or by both?

All four conditions share the DH-04 design. They receive identical immediate
reward acquisition, identical task schedules, and identical reversal RNG streams.
The eligibility-retained and eligibility-suppressed cells both process twelve
distractors and restore post-cue neural state. Only distractor-generated
eligibility is retained or replaced by the post-cue trace.

Use fresh seeds 5000 through 5023, taus 4 and 16, both related soma-side slices,
uniform-learning E and fixed-weight Z controls, and checkpoints
0, 16, 32, 64, 128, and 256 reversal trials.

## Co-primary outcomes

At every checkpoint record:

- deterministic old-map margin and its sign-reversed new-map margin;
- same-RNG old and reversed probe accuracy;
- acquisition-axis coordinate q, with initial weights at 0 and acquired weights
  at 1;
- acquisition-axis projection P_A;
- reversal displacement parallel to the acquisition vector and perpendicular
  norm, both normalized by acquisition displacement.

The two co-primary endpoint contrasts are right-slice E, eligibility-retained
minus eligibility-suppressed at the final checkpoint:

1. deterministic old-map margin;
2. acquisition-axis projection P_A.

Average taus inside each seed bundle. Use paired bootstrap over 24 seeds with
20,000 resamples and seed 2026091205. Report 95% paired intervals. Checkpoint
trajectories and reversed-probe accuracy are descriptive.

The trajectory is interpreted as follows:

| Old-map margin | New-map margin | Interpretation |
| --- | --- | --- |
| falls | unchanged | old-memory weakening |
| unchanged | rises | reversed-association formation |
| falls | rises | both processes |

The acquisition vector adds a structural test. Negative movement in
W_t - W_A along the acquisition axis is undoing the acquired mapping; a large
perpendicular component indicates construction away from that axis.

No classification gate is added after DH-04. DH-05 records the time course and
keeps any mechanism statement tied to the declared endpoint contrasts.

## Integrity requirements

Require matched acquisition hashes, exact DH-04 causal-cell compatibility,
same-RNG probe complementarity, deterministic margin parity, exact intervention
receipts, fixed-weight action parity, observer on/off equivalence, complete
checkpoint vectors, deterministic replay, SIMD/scalar parity, graph-null
invariants, and zero online allocations.

After sealing, replay one real right-slice seed across all four conditions and
both arms with observers enabled and removed. This adds no scientific samples.

## Limits

Margins are model readouts and the acquisition axis is one weight-space
projection. Neither proves a biological forgetting mechanism. The transient
distractor trajectory can still be causally important because it creates the
eligibility; DH-05 only records the later persistence of weights and expression.
The task, dynamics, bounds, clipping, readout, trial reset, and one-specimen
left/right structure remain synthetic choices.

No post-outcome tuning, extra seeds, endpoint changes, rule search, or new
conditions are permitted.

Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY:
https://male-cns.janelia.org/download/ . Anatomy and parent lineage inherit the
hash-verified DH-04 seal.
