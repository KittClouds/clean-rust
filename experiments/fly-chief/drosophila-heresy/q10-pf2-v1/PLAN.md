# Q10-PF2: prefix-constrained multi-ULP feasibility

Q10-PF2 is an engineering-only qualification following the sealed Q10-RMT
topology. It asks whether a bounded, prefix-constrained choice of f32 weight
endpoints can reduce or exactly close the RMT sequential-readout residual. It
does not apply a repair to a canonical endpoint and it does not open a
scientific bundle, a behavioral measurement, or DH08B.

## Frozen starting point

Use the 28 Q10-RMT valid endpoints. Keep the four DA2 geometry failures in a
separate receipt and exclude them from the primary feasibility set. The RMT
acceptance invariants are:

* 7,003 mismatched readout rows;
* one-step classes: 3,726 orphan, 2,274 fragile, and 1,003 broad;
* first helpful prefix: 3,277 at 1 ULP, 1,128 at 2, 1,172 at 4, 703 at 8,
  397 at 16, and 326 with no local authority through 16 ULPs;
* 2,738 helpful row components, with largest component size 13 rows;
* 168,071 serialized move records and 1,792/1,792 local replay receipts.

These are input invariants, not outcomes that may be recomputed and silently
reinterpreted. Any mismatch fails closed.

## State and prefix contract

For endpoint state (W_B), target sequential readout (g_T), and baseline
readout (g_B), define the residual (e=g_T-g_B) in analysis arithmetic.
Bitwise f32 equality remains the readout authority; f64 residuals are
diagnostics only.

For each legal coordinate (i), the allowed final choices are:

`0, -1, +1, -2, +2, -4, +4, -8, +8, -16, +16` ULP endpoints.

Choosing `+k` means one committed endpoint reached by the ordered positive
`nextafter32` prefix of length `k`; it is not permission to select arbitrary
members of that prefix. The negative direction is separate. A coordinate may
contribute exactly one final choice. Every candidate is formed in a cloned
state, committed to f32, and replayed in the learner's exact sequential order.

RMT moves are the initial measured inventory. A prefix not present in the RMT
receipt must be replayed from the frozen endpoint before it can enter a
candidate domain. An unmeasured prefix is never treated as zero authority.

## Staged qualification

### PF2-0: lineage and replay gate

Verify the Q10-RMT plan, contract, result, status, DA2 contract, and declared
receipt root. Resolve the receipt root as one immutable set; do not mix archived
or failed directories. Reconstruct every primary endpoint and reproduce its
baseline and target readouts bitwise before any feasibility calculation. The
declared RMT receipt path must exist at execution; otherwise PF2 stops with
`PARENT_RECEIPT_UNAVAILABLE`.

### PF2-1: domain and topology gate

Build the raw coordinate-to-mismatched-row graph from RMT. Overlay helpful
edges, one-step orphan/fragile/broad labels, first-helpful-prefix labels, and
the 2/4/8/16-ULP availability. Raw authority defines candidate support;
helpful authority ranks candidates but does not delete raw moves.

Partition only at raw-support-disjoint cuts. A row-disjoint macro-group may
contain coordinates whose raw row sets are pairwise disjoint. Preserve a
sparse shared-row component as one exact-replay group when splitting would hide
a possible sequential-f32 interaction. Distributed raw-authority coordinates
that bridge rows or components remain in the group containing all of their raw
support.

Mark every group and row with prefix coverage:

* `complete`: all legal coordinates in the declared group have all permitted
  prefixes measured or deterministically replayable;
* `partial`: at least one prefix is absent but can be replayed under the
  declared budget;
* `incomplete`: a required prefix cannot be enumerated within the budget.

Only `complete` groups may support a negative feasibility conclusion. The 326
RMT no-authority rows remain explicit blockers. If their mismatch is nonzero
and the complete local domain still has no effect, exact global parity is
`BLOCKED_WITHIN_DECLARED_DOMAIN`; it is not a claim about all possible weight
changes.

### PF2-2: coordinate-group convex screen

For coordinate (i) and prefix (k), obtain the exact committed readout
effect (v_{i,k}=g(W_B	ext{ with }i	ext{ set to }k)-g_B). For each group,
form the coordinate-wise relaxed set

\[
\mathcal C_G=\sum_{i\in G}\operatorname{conv}\{v_{i,k}:k\in D_i\}.
\]

The relaxation permits a convex mixture of mutually exclusive prefixes, so it
is only a screen. Use a deterministic bounded projected simplex/least-squares
routine on the group's mismatched rows, with fixed iteration and memory caps.
Do not run a global optimizer.

For a row-disjoint macro-group, each affected readout row has at most one
candidate coordinate, so the exact readout effect is additive across its
coordinates; an outside-relaxation result can reject that group's declared
readout target, subject to complete coverage. For shared sparse components,
the screen is prioritization only: sequential f32 interactions can enlarge or
alter the joint effect, so an outside result never proves infeasibility there.

Prioritize groups in this order: no-authority diagnostics, threshold-gated
rows by increasing (k^*\), fragile rows, then broad distributed authority.
Retain raw-only candidates in the diagnostic graph even when the relaxed
screen gives them zero helpful weight.

### PF2-3: bounded exact prefix replay

Only groups that pass the applicable screen and coverage gate proceed. Evaluate
joint candidates on cloned f32 states with the actual sequential replay. The
candidate objective is lexicographic and fixed before execution:

1. minimize bitwise mismatch-row count;
2. minimize total row ULP distance;
3. minimize f64 residual L2, then maximum absolute residual;
4. pass the inherited DA2 geometry and 16-ULP reserve gates.

Never add a candidate that worsens an earlier lexicographic component. For a
microgroup whose prefix-domain Cartesian product is at most 4,096, exhaustive
joint replay is allowed. Larger groups use a deterministic bounded beam or
coordinate-block schedule seeded by the convex solution and RMT
helpful/raw-prefix scores. Every proposed joint state is replayed exactly;
no additive or pairwise surrogate is accepted as a result.

The bounded search may find a feasible candidate, but failure to find one in a
large group is `INCONCLUSIVE_BOUNDED_SEARCH`, never infeasibility. A group
that exceeds the declared row, coordinate, replay, or memory budget is
`OVERSIZE_UNTESTED` and is not silently split across shared raw support.

### PF2-4: endpoint audit and classification

Re-read every accepted candidate from its final f32 bytes. Recheck all
sequential readout bits, ULP distances, mismatch counts, prefix legality,
support, bounds, boundary membership, reserve, acquisition-axis tolerance,
displacement-norm tolerance, and linear cue-drive tolerance. The candidate
must pass the DA2 geometry gates: normalized axis error <= 2e-6, normalized
norm error <= 2e-7, and normalized linear cue-drive error <= 2e-6.

Classify each endpoint only as one of:

* `EXACT_TARGET_REACHED`: exact target readout and all geometry gates pass;
* `PARTIAL_FEASIBILITY_FOUND`: an exact-replayed candidate improves the fixed
  lexicographic objective and all geometry gates pass;
* `BLOCKED_WITHIN_DECLARED_DOMAIN`: complete coverage plus unresolved
  no-authority rows prevents exact target parity;
* `RELAXATION_OUTSIDE_ADDITIVE_DOMAIN`: a complete raw-disjoint group is
  rejected by its valid convex screen;
* `INCONCLUSIVE_BOUNDED_SEARCH` or `OVERSIZE_UNTESTED`.

No class authorizes DH08B or promotes a candidate to a scientific endpoint.

## Fail-closed firewall

Stop before candidate construction on any parent hash/path mismatch, missing
receipt, duplicate endpoint identity, baseline replay mismatch, RMT topology
count mismatch, incomplete prefix coverage used for a negative claim, or
non-finite arithmetic. Stop if a candidate would mutate a sealed file or if
the implementation introduces repair coefficients into the canonical model.

The run must use zero scientific seed bundles and emit no accuracy, reward,
action, old-map, reversed-map, behavioral, or DH08B fields. A feasibility
receipt is an engineering diagnostic only. No repair is applied anywhere in
the Q10 lineage.
