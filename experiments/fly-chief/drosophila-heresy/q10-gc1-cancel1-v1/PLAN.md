# Q10-GC1-CANCEL1: Bounded Palette Replacement

CANCEL1 tests whether signed geometry/collateral cancellation recovers valid
advantage around the eight saved best-search states failing final geometry.
Cohort is fixed by audited flags before any new replay. V is that case's
historical best-valid output; S is its fixed invalid saved state. S is never
updated after a successful replacement within this identity.

A move replaces one group's existing choice with another legal palette
identity, including ZERO, activation, and deactivation. Prefixes stay relative
to the original frozen baseline B. A pair replaces two distinct groups
simultaneously in S. Same-group alternatives never combine. Conflicts are
revalidated though the parent reports zero coordinate overlap.

Stage A enumerates every legal alternate choice for every group in each of
the eight cases, with exact counts frozen before replay. Deduplicate state
bytes with alias records. Replay every resulting state with full final
geometry; record every score and gate even for harmful moves. No filtering by
readout, geometry, or parent guards. Hard support/bounds/reserve legality
always applies.

Stage B screens at most 32 single-replacement records per case and all
unordered distinct-group pairs among them (at most 496/case, 3,968 total).
Shortlist rule is frozen before Stage A: up to 16 geometry-repair by max gate
ratio then excess sum then Q; up to eight collateral-repair by damaged count
then Q then excess; fill to 32 by round-robin across (group, axis-change
sign, linear-opposition sign) with canonical ties, including harmful records.
Opposition uses full signed linear vector dot products. Commit both
replacements simultaneously from S; do not sum isolated effects.

Principal result is VALID_ADVANTAGE_PRESERVED: all final gates and legality
pass, W differs from T/B, and Q(W) < Q(V) lexicographically. Distinguish
valid tie/worsen, invalid improvements, and exact alternates. Gap retention
is descriptive only. Negatives are domain-bounded: singles rule out only the
one-group neighborhood; screened pairs rule out only the screened domain.
No palette infeasibility or assembly rejection follows alone.

All results preserved with independent reconstruction of claimed successes.
Same-seed development evidence only.
