# Q10-PF5: Prefix-Constrained Residual Feasibility

Q10-PF5 is an engineering-only qualification of whether the residual
sequential-binary32 readout mismatch mapped by sealed Q10-RMT can be reduced
or closed by one final legal prefix choice per coordinate. This is a fresh
protocol identity in the lineage. An earlier prefix-feasibility scaffold is a
design source only; it is not renamed, rewritten, or used as an execution
parent.

No scientific bundle, behavioral endpoint, canonical repair, or DH08B path is
opened by this protocol. Every candidate is evaluated on a cloned f32 state.
The canonical DA2 endpoint and every sealed predecessor remain immutable.

## Frozen parent and starting population

The parent is the current final Q10-RMT artifact set at
`experiments/drosophila-heresy/q10-rmt-v1`. The contract binds the exact
SHA-256 values of its `RESULT.md`, `STATUS.json`, `PLAN.md`, and
`CONTRACT.json`. The historical `next_protocol` text inside the sealed RMT
status/result is not an identity instruction; this protocol is Q10-PF5.

Use the 28 Q10-RMT primary endpoints. Retain the four Q10-DA2 geometry-failed
endpoints in a separate receipt and exclude them from the primary feasibility
set. The following RMT quantities are input invariants and must be checked
before feasibility work:

* 7,003 mismatched readout rows;
* one-step classes: 3,726 orphan, 2,274 fragile, and 1,003 broad;
* first-helpful-prefix counts: 3,277 at 1 ULP, 1,128 at 2, 1,172 at 4,
  703 at 8, 397 at 16, and 326 with no individually helpful move through
  16 ULPs;
* 2,738 helpful row components, with largest component size 13 rows;
* 168,071 serialized authority moves and 1,792/1,792 local replay checks.

These are lineage gates, not outcomes that may be silently recomputed or
reinterpreted.

## Scientific and engineering boundary

This qualification may construct and score cloned candidate f32 states only.
It may not mutate a canonical endpoint, apply a repair to the learner,
measure accuracy, reward, actions, old-map or reversed-map expression, or
open DH08B. It emits only engineering receipts: lineage, topology, prefix
coverage, bounded-search status, exact replay, geometry debt, and final
feasibility class.

The 326 RMT rows with no individually helpful move are **not** blockers at
entry. `no_local_authority_through_16` is a diagnostic label for isolated
authority. A row can be called blocked only after the complete declared joint
domain that can affect it has been covered by exact enumeration or a declared
mathematical certificate. Bounded-search exhaustion, an oversize group, or an
untested higher-order interaction remains inconclusive.

## State, prefixes, and exact readout

For a committed baseline state (W_B), target sequential readout (g_T),
and baseline readout (g_B), define the analysis residual as

\[
e = g_T - g_B.
\]

The authority remains exact learner-order binary32 replay with bitwise output
comparison and signed-zero identity. f64 residuals, ULP distances, mismatch
counts, and norms are diagnostics and ranking signals; they do not replace
bitwise readout authority.

For each legal coordinate (i), the final domain is

`0, -1, +1, -2, +2, -4, +4, -8, +8, -16, +16` ULP endpoints.

Choosing `+k` or `-k` means one committed endpoint reached through the ordered
`nextafter32` prefix of length `k`; arbitrary subsets of a prefix are illegal.
Each coordinate has exactly one final choice. Prefixes missing from the RMT
receipt are replayed from the frozen endpoint before use and are never
assumed to have zero authority.

The raw-authority graph defines candidate support. Helpful authority ranks
choices and exposes threshold-gated rows, but raw moves are not deleted merely
because their isolated effect is harmful or neutral.

## Geometry debt and final validity

Candidate construction tracks a geometry-debt signature after every partial
assignment:

\[
q=(\Delta A,\Delta N,\Delta L),
\]

where the entries are the normalized acquisition-axis, displacement-norm, and
linear cue-drive deviations relative to the DA2 baseline contract. Partial
states may carry nonzero debt. A move is not rejected merely because its own
geometry signature fails the final tolerance; later moves may cancel that
debt.

To prevent unbounded wandering, partial states must remain inside the frozen
intermediate guardrails:

* absolute normalized axis debt ≤ `3.2e-5`;
* absolute normalized norm debt ≤ `3.2e-6`;
* absolute normalized linear cue-drive debt ≤ `3.2e-5`.

These are bounded exploration guards, not endpoint claims. A state outside a
guard is pruned and reported as search pruning, never as a proof of
infeasibility.

Only the final committed candidate is judged against the inherited DA2 gates:

* normalized acquisition-axis error ≤ `2e-6`;
* normalized displacement-norm error ≤ `2e-7`;
* normalized linear cue-drive error ≤ `2e-6`;
* all permitted-support, bounds, boundary-membership, and 16-ULP reserve
  requirements pass.

The final candidate must be reconstructed from its stored f32 bytes before
these gates are evaluated.

## PF5-0: lineage and replay gate

1. Verify the four bound RMT parent hashes and the declared immutable RMT
   receipt root.
2. Verify that the receipt root is a single canonical set; do not substitute
   archived, failed, or probe directories.
3. Reconstruct all 28 primary endpoints from the frozen DA1/DA2 lineage and
   reproduce baseline and target sequential readouts bitwise.
4. Check endpoint identity uniqueness, all RMT topology invariants, finite
   arithmetic, and zero scientific/behavioral/DH08B fields.

Any failure stops the protocol with a fail-closed lineage or replay status.

## PF5-1: prefix domain and topology gate

Build the raw coordinate-to-mismatched-row graph and overlay helpful edges,
one-step orphan/fragile/broad labels, first-helpful-prefix labels, and
2/4/8/16-ULP availability.

Partition only at raw-support-disjoint cuts. Preserve a shared-row component
as one exact-replay group when splitting could hide a sequential-f32
interaction. Coordinates that bridge rows remain with all of their raw
support.

Every row and group receives a coverage state:

* `complete`: every declared legal coordinate choice affecting the group is
  measured or deterministically replayable within the declared budget;
* `partial`: an absent prefix can still be replayed under the budget;
* `incomplete`: a required prefix cannot be enumerated under the budget.

No negative feasibility class is permitted for an incomplete domain. In
particular, the 326 no-helpful rows remain explicit joint-authority
diagnostics until their complete declared affecting domain is exhausted.

## PF5-2: bounded relaxation and prioritization

For coordinate (i) and legal prefix (k), obtain the exact committed
readout effect

\[
v_{i,k}=g(W_B\text{ with coordinate }i\text{ at }k)-g_B.
\]

For a group (G), form the coordinate-wise convex relaxation

\[
\mathcal C_G=\sum_{i\in G}\operatorname{conv}\{v_{i,k}:k\in D_i\}.
\]

The relaxation is a screen and prioritization device. It does not authorize a
convex mixture of mutually exclusive prefixes, and it does not replace exact
joint replay. For a genuinely raw-support-disjoint group, an outside result
may reject the declared additive target only when coverage is complete and
each affected row has at most one candidate coordinate. For shared groups, an
outside result is never an infeasibility proof because sequential interactions
may escape the isolated-effect hull.

Prioritize groups by residual mass and topology together: unresolved
no-helpful-row neighborhoods, high-residual threshold-gated rows, fragile
rows, and distributed broad authority. Component size alone is not a priority
criterion.

## PF5-3: exact prefix replay

The exact solver operates on cloned committed f32 states and uses the real
learner-order sequential replay for every accepted or scored final candidate.
It never treats additive, pairwise, or convex surrogate effects as results.

### Small domains

If the Cartesian product of the group's legal coordinate domains is at most
4,096, enumerate every final prefix tuple exactly. This is the preferred path
for singleton and small components.

### Larger domains

Use a deterministic bounded beam with two explicit lanes:

* `exploit_width = 24`: states ranked by the fixed final objective and
  residual-mass reduction;
* `explore_width = 8`: diverse states selected by stable prefix histogram,
  threshold-class, geometry-debt bucket, and component-coverage signatures.

The total beam width is 32, with a fixed maximum of 8 rounds and 8,192 node
replays per group. Stable hashes determine all ties. The exploration lane is
not allowed to disappear merely because exploit states score better.

The final objective is lexicographic:

1. bitwise mismatch-row count;
2. total row ULP distance;
3. f64 residual L2;
4. maximum absolute residual.

Intermediate search states may worsen an earlier objective component. The
beam may retain bounded nonmonotonic states when they fit the exploration
lane and geometry-debt guards. Monotonic improvement is not a validity rule.
Only the final candidate is required to improve the starting endpoint before
it can receive `PARTIAL_FEASIBILITY_FOUND`.

Groups that exceed row, coordinate, memory, replay, or round budgets receive
`OVERSIZE_UNTESTED`. A bounded beam that completes its budget without proving
exactness receives `INCONCLUSIVE_BOUNDED_SEARCH`. Neither class is an
infeasibility claim.

## PF5-4: final endpoint audit and classification

For every retained candidate, reread the final f32 bytes and independently
recompute:

* sequential readout bits, signed-zero identity, mismatch rows, and ULP
  distances;
* prefix legality, one-final-choice-per-coordinate, support, bounds,
  boundary membership, and reserve;
* final DA2 axis, norm, and linear cue-drive gates;
* source endpoint identity and canonical-state immutability.

The only endpoint classifications are:

* `EXACT_TARGET_REACHED`: exact target readout and all final geometry gates
  pass;
* `PARTIAL_FEASIBILITY_FOUND`: exact replay finds a lexicographically better
  candidate and all final geometry gates pass;
* `BLOCKED_WITHIN_DECLARED_DOMAIN`: complete joint domain coverage or a valid
  additive certificate remains, and exact target parity is still unavailable;
* `RELAXATION_OUTSIDE_ADDITIVE_DOMAIN`: a complete raw-disjoint group is
  rejected by its valid relaxation screen;
* `INCONCLUSIVE_BOUNDED_SEARCH`: declared bounded search completed without a
  proof or valid candidate;
* `OVERSIZE_UNTESTED`: declared group budget was exceeded.

`NO_INDIVIDUAL_HELPFUL_AUTHORITY` is a row diagnostic, never an endpoint
blocker by itself.

## Fail-closed firewall

Stop before candidate construction on any parent hash/path mismatch, missing
or mixed RMT receipt root, duplicate endpoint identity, baseline or target
replay mismatch, RMT topology mismatch, non-finite arithmetic, or forbidden
scientific/behavioral/DH08B field. Stop if any sealed predecessor is written
or if a candidate is applied to the canonical model.

No result from Q10-PF5 authorizes DH08B. The protocol remains an engineering
scaffold until a separate execution receipt passes its own audit.
