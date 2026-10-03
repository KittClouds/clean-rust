# Q10-GC1-CANCEL1-LR1: Checkpointed Bounded Cancellation Replay

LR1 completes the existing bounded cancellation question with a checkpointed
execution identity. It is one logical campaign with one frozen selection
policy, not eight independently tuned experiments. It does not extend the
domain, loosen geometry, regenerate palettes, or move the fixed starting
state S after success.

Cohort: the eight saved best-search states failing final geometry (audited
flags, frozen before any new replay). V is each case's historical best-valid
output; S is its fixed invalid saved state. S is never updated within this
identity. Case order is the canonical order in inventory/cases.json; no
outcome-dependent priority.

A single move replaces one group's choice with another legal palette
identity (ZERO included). A pair replaces two distinct groups simultaneously
from S. Same-group alternatives never combine. Prefixes stay relative to the
original frozen baseline B. Conflicts are revalidated.

Stage A evaluates all 3,696 labeled single replacements around fixed S with
no readout/geometry filtering. Stage B builds the frozen shortlist (at most
32/case, legacy selector order preserved as-coded, documented) and evaluates
the exact distinct-group pair domain (at most 3,968 total). Pairs commit both
replacements simultaneously from S.

Selector continuity: the shortlist uses the sealed CANCEL1-v1 selector
arithmetic and order exactly, including the as-coded collateral sort
(damaged, mismatch, ULP, excess) where the prose said damaged, full Q, then
excess, and the legacy fsum expression order for opposition dots. A full-Q
selector correction is a different future comparison, not a silent amendment.
Receipt, cache-isolation, duplicate-input, and checkpoint changes must not
change candidates or numerical results on valid inputs.

Execution: one worker, foreground invocations of at most 128 new records or
10 minutes, stopping at completed 32-record chunk boundaries. Chunks are
immutable once published with count/hash receipts; resume verifies and fills
only missing predetermined work. No --force path in the measured runner.
Cumulative worker cap 120 minutes; on cap exhaustion retain incomplete
coverage and stop with no silent top-up.

Success is VALID_ADVANTAGE_PRESERVED (all hard legality and final gates, W
distinct from B/T, Q(W) strictly better than Q(V)) or EXACT_ALTERNATIVE
(bitwise full-target match including signed zero plus distinctness and
gates). Negatives are domain-bounded only. Every claimed success is
independently reconstructed before any headline. GC2 stays reserved for
fresh-state qualification; GA1, AG1, behavior stay gated.
