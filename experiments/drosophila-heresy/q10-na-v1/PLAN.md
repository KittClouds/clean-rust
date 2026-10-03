# Q10-NA: hidden authority in no-helpful rows

Q10-NA is an engineering-only diagnostic that asks whether the 326 Q10-RMT
rows with no individually helpful prefix through 16 ULP have useful authority
only when multiple weight coordinates move together.

The protocol consumes exactly one immutable parent receipt:
`experiments/drosophila-heresy/q10-rmt-v1/qualification/sample-9731-9732`.
It must not resolve an archived, failed, or mixed receipt directory. The
parent's four DA2 geometry-failed endpoints remain excluded exactly as they
were in Q10-RMT.

Q10-NA is a side diagnostic. It does not replace the Q10-RMT next-decision
field, promote a repair design, open DH08B, or authorize a scientific run.
Only cloned f32 candidate states may be constructed in memory. No candidate is
written into a canonical model, a Q10-RMT receipt, or another predecessor.

## Frozen question and unit

For each parent endpoint and mismatch row whose Q10-RMT `k_star` is `none`
and whose final class is `no_local_authority`, construct the complete raw
support neighborhood from the parent `rows.json` and `moves.jsonl`. The unit
of classification is the pair `(endpoint identity, readout row)`.

The target row is improved when an exact sequential-binary32 replay of a
candidate cloned endpoint has a strictly smaller monotonic ULP distance to the
parent target bits than the parent baseline. Signed-zero identity is preserved
by the parent's binary32 ULP ordering. A candidate that changes other rows is
allowed; those effects are recorded and do not turn a row-level diagnostic
into a repair.

The primary classification is the smallest jointly replayed order that shows
row improvement:

* `individual`: a legal one-coordinate prefix improves the row. The parent
  invariant predicts zero instances; any instance is a parent-coverage or
  receipt inconsistency and fails the run closed.
* `pair`: no individual prefix helps, and an exhaustive legal-prefix pair
  replay improves the row.
* `triple`: no individual or pair helps, and an exhaustive legal-prefix triple
  replay improves the row.
* `higher-order-or-untested`: a larger neighborhood remains after complete
  pair/triple work, a pair/triple budget is incomplete, or deterministic
  higher-order escalation is exhausted without a complete domain.
* `no-effect-within-domain`: the complete declared domain for a neighborhood
  of at most three coordinates is exhaustively replayed and no candidate
  improves the row. This is not a global impossibility claim.

The receipt also records `geometry_qualified` separately. Raw row authority
and geometry-qualified row authority must never be conflated.

## Parent verification and raw-support coverage

Before any replay, the runner must verify every parent hash in
`CONTRACT.json`, the exact receipt root, and the parent status and invariant
counts. It must then verify:

1. The target set contains exactly 326 unique endpoint-row identities.
2. Every target row has Q10-RMT `k_star = none`, final class
   `no_local_authority`, and zero one-step helpful coordinates.
3. For every target row, the union of coordinates in all parent move records
   whose `raw_rows` contain that row equals the row's `all_raw_coordinates`.
4. Every raw-support coordinate has a legal prefix domain reconstructed from
   the immutable endpoint fixture and the frozen RMT reserve/bounds rules.
   The moves receipt is a serialized observation stream: a missing serialized
   key may be neutral and is replayed deterministically from the fixture. A
   duplicate or contradictory serialized key still fails closed. The receipt
   records serialized coverage separately from replay coverage.
5. Each endpoint-row key and each endpoint-coordinate-step key is unique.
6. The four excluded DA2 endpoints are not silently folded into the primary
   target set.

The raw-support neighborhood is endpoint-specific. Helpful-authority graphs
and Q10-RMT components may prioritize work, but they may not delete a raw
support coordinate or split a shared neighborhood in order to manufacture
additivity.

## Exact replay domain

The immutable parent endpoint is the replay baseline. Reconstruct it from the
hash-bound source fixture and frozen DA2 `selected_steps`, then apply the
frozen RMT legality rule (permitted/interior support, bounds, and 16-ULP
reserve) to each raw-support coordinate. The legal final choices are zero
plus the legal signed prefixes from `{+/-1, +/-2, +/-4, +/-8, +/-16}`. One
final prefix is selected per coordinate; prefixes are not independently
composable increments. Candidate coordinates are applied simultaneously to a
cloned committed f32 weight vector, then the learner-order sequential f32
readout is executed from scratch. A prefix absent from the serialized RMT
stream is not assumed to have zero effect; it is replayed and recorded.

Pair replay enumerates every legal prefix tuple for every unordered support
pair whenever its complete cost fits the frozen budget. Triple replay follows
the same rule for every unordered support triple after pair work is complete.
The enumeration order is endpoint key, row, coordinate tuple, then prefix tuple
using `[0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16]`. A successful lower-order
classification may stop higher-order work for that row only after the relevant
lower-order domain has been completely audited.

Rows whose complete pair or triple domain exceeds budget receive deterministic
bounded escalation, not an impossibility label. The escalation order is the
same stable coordinate/prefix order, followed by a fixed-width beam over cloned
states. Beam states are allowed to worsen an intermediate objective so that
sequential-f32 threshold crossings are not pruned prematurely. Diversity is
preserved by stable prefix signatures. Exhaustion yields
`higher-order-or-untested`.

The 326 rows are never removed merely because individual authority is absent.
Pair and triple candidates may be individually neutral or harmful and still be
replayed jointly. This is required by the PF2/PF4 interaction findings.

## Geometry is final-only

Every partial assignment records its geometry debt:
`delta_axis`, `delta_norm`, and `delta_linear_cue_drive`. Those quantities may
temporarily violate the final tolerances and may not be used as an
intermediate monotonic pruning rule. Bounds, permitted support, and f32
representability must still hold for every cloned candidate.

Only a complete candidate endpoint is checked against the frozen final gates:

* normalized acquisition-axis error `<= 2e-6`;
* normalized weight-norm error `<= 2e-7`;
* normalized linear cue-drive error `<= 2e-6`;
* minimum final reserve of 16 ULP;
* permitted support, bounds, and declared boundary membership;
* exact sequential-f32 replay from the final committed bytes.

A row may therefore have raw pair/triple authority while having no
geometry-qualified candidate. This is a diagnostic distinction, not a repair
result. The final geometry gates are evaluated only after the full candidate
prefix tuple is formed; a search path is not required to improve mismatch
count or remain inside the final axis/norm/linear tolerances at every step.

## Bounded escalation and budgets

The following limits are fixed before execution:

* 326 target rows maximum; no target-row sampling.
* 131,072 exact pair replays per row and 25,000,000 total pair replays.
* 1,048,576 exact triple replays per row and 50,000,000 total triple replays.
* 4,096 deterministic higher-order seed candidates per row.
* Beam width 32, maximum 8 rounds, and 8,192 visited cloned states per row.
* 2 GiB peak diagnostic output/storage budget for the new protocol root.
* No replay result may be retained without its endpoint, row, coordinate
  tuple, prefix tuple, baseline bits, candidate bits, ULP distances, geometry
  signature, and final-gate receipt.

Budgets are qualification limits, not evidence of infeasibility. A budget
exhaustion, unreplayable raw-support neighborhood, nonfinite value, or failed
receipt check produces a fail-closed engineering status. Serialized-prefix
absence alone is not an incomplete domain when the fixture replay inputs are
hash-verified. It cannot be reported as `no-effect-within-domain` unless the
legal local domain was actually exhausted.

## Stages

`NA-0` verifies parent protocol hashes, canonical receipt resolution, status,
and the 326-row invariant.

`NA-1` independently reconstructs baseline and target sequential-f32 readouts
for every target endpoint-row identity and checks the parent bits and ULP
distances.

`NA-2` builds and audits complete raw-support neighborhoods, legal prefix
domains, endpoint-coordinate-step uniqueness, and coverage receipts.

`NA-3` replays all individual legal prefixes as a consistency check. Any
helpful individual result fails closed against the parent invariant.

`NA-4` exhausts legal prefixes for complete pairs within budget. Pair
authority is recorded only after exact replay, never from additive surrogates.

`NA-5` exhausts tractable triples after pair completion. Oversize domains use
the deterministic bounded escalation and remain `higher-order-or-untested`.

`NA-6` audits final candidate bytes, geometry gates, raw-support coverage,
budget receipts, and the mutually exclusive classification for every target.

`NA-7` writes receipts under `q10-na-v1` only. It must not write scripts,
results, status files, caches, or temporary artifacts into Q10-RMT or any
other directory when the scaffold is being created.

## Fail-closed rules and firewall

The run is invalid if any parent hash, receipt path, source-fixture hash,
DA2-result hash, parent invariant, target identity, raw-support coverage,
reconstructed baseline replay, target replay, or final candidate audit fails.
It is also invalid if a duplicate or mixed receipt is observed, if a budget is
exceeded without an explicit untested classification, or if a candidate is
treated as exact without final-gate validation. Serialized-prefix absence is
reported as coverage metadata and must be resolved by deterministic fixture
replay before pair/triple classification.

No-effect claims are forbidden when any relevant pair/triple domain is
incomplete or when the neighborhood has more than three raw-support
coordinates. Higher-order work may find authority, but failure to find it
within the deterministic budget remains `higher-order-or-untested`.

No field or process may introduce accuracy, reward, action, behavior, old-map,
reversed-map, scientific-seed, biological, connectome, or canonical-repair
claims. Scientific seed bundles used is exactly zero. DH08B remains closed.
Any write outside `experiments/drosophila-heresy/q10-na-v1` is a protocol
failure.
