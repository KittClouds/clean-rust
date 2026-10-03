# OBS-OPEN-03B-P — Frozen Range Representation Tournament

Authority class: scientific protocol freeze and representation-information gate design only.

This gate computes no D_B outcomes, fits no D_B model, reads no D_B score, and reads no D_C
authority. It freezes a later one-shot comparison of `DESIGN_CONTEXT`, `DESIGN_CONTEXT + RAW`,
and `DESIGN_CONTEXT + RANGE_Z` at range-freeze anchors.

## Question and target

The question is whether causal frozen-range snapshot geometry exposes future-process information
beyond the observer's composite design/clock coordinate. Pure scale independent of freeze clock is
not identifiable because `k` is exactly the freeze minute after 09:30.

The only target is `STRICT_ABOVE_FROZEN_MIDPOINT_AT_60M_V1`, mechanically bound to the existing
`OUTCOME_REGISTRY_V1` range-terminal-close record at 60 physical minutes. It is true exactly when
the admitted terminal raw displacement is greater than zero. Equality is false.

## Representations

`RANGE_RAW_SNAPSHOT_V1` contains frozen width plus freeze-bar OHLC minus frozen midpoint in source
price units. `RANGE_Z_SNAPSHOT_V1` contains the same four OHLC offsets divided by frozen half-width
and excludes width. Both use only information available at freeze. Absolute price, pre-freeze path,
candidate history, final multiplicity, and future information are absent.

The algebra audit precedes modeling. Raw deterministically maps to z for positive width. Z cannot
reconstruct raw from `RANGE_DESIGN_CONTEXT_V1`, because context contains only k and clock-offset
regime. Width is the removed positive-scale degree of freedom. Z is therefore a lossy quotient,
conditionally invertible only when width is supplied outside the admitted z representation.

## Probe and inference

All three arms use the same f64 L2-regularized logistic implementation, chronological D_A-only
selection, session weights, convergence law, and failure policy. The primary score is mean
session-level Brier loss. Each representation is tested against design context using a paired
session-level one-sided sign-reflection test with 9,999 randomizations, seed 20260814, plus-one
correction, a 99 percent Wilson decision interval, and Holm control across exactly two tests.

Paying rent requires both familywise evidence and relative Brier skill of at least 0.02.
No direct RAW-versus-Z test and no combined representation are authorized.

## Firewall and stop

D_A may supply algebra, support, fold, and synthetic-probe qualification. D_B target applications,
target values, scores, fitting, transform fitting, and tuning remain zero. D_C remains unopened.
Seal this protocol and stop. A separate authorization is required to execute the tournament.
