# Q10-RH1-LA1: Late-Authority Mechanism Audit

Q10-RH1-LA1 is an engineering-only audit of how a sealed RH1-F2 authority
h32 endpoint changes when its committed prefixes are separated into the first
16 authority ranks and the late ranks 17 through 32. It consumes the sealed F2
raw execution and interpretation receipts. It does not change a model, run a
behavioral probe, or promote a scientific finding.

## Selection

The runner reads every primary F2 group from the raw execution receipt. A group
is selected exactly when the F2 `authority__h32` `chosen.D` score is strictly
lexicographically smaller than the same group's `authority__h16` `chosen.D`
score. The score tuple is, in order:

```text
(mismatch_count, total_ulp_distance, residual_l2, maximum_absolute_residual)
```

The selector derives this set from receipts. No group identity is embedded as
a hand-picked list. The F2 interpretation is provenance and scope context; its
descriptive prose is never used to select groups.

## Endpoint reconstruction

For every selected group, the runner loads the matching PF5 cloned endpoint
state through the sealed F2 runtime and checks the F2 group identity, rows,
canonical coordinates, authority order, and baseline. It then reconstructs five
endpoints from the same baseline weight bits:

1. `W0`: the F2 baseline, with zero prefix at every group coordinate.
2. `historical_authority_h16`: the exact committed F2 authority h16 prefix map.
3. `authority_h32_early`: the exact F2 authority h32 winner, retaining choices
   at authority ranks 1 through 16 and setting ranks 17 through 32 to zero.
4. `authority_h32_late_only`: the same h32 winner, retaining only ranks 17
   through 32 and setting ranks 1 through 16 to zero.
5. `authority_h32_full`: the exact committed F2 authority h32 prefix map.

Every prefix map is canonical and sorted by coordinate id. Each endpoint is
replayed in learner row order with sequential binary32 additions and bitwise
readout comparison, including signed-zero identity. Geometry is evaluated from
the committed f32 weight bits. `W0`, `historical_authority_h16`, and
`authority_h32_full` are inherited/actual endpoints and must pass the inherited
PF5 final gates. `authority_h32_early` and `authority_h32_late_only` are
diagnostic counterfactual decompositions: their exact geometry metrics and
normalized debt are recorded with a diagnostic pass flag, but their geometry
flags do not abort LA1.

## Measurements

Each endpoint reports the declared-row (`D`), physical-support (`P`), and
whole-endpoint (`G`) score domains. `D` is the inherited search objective; `P`
and `G` are engineering diagnostics. The row-wise interaction is emitted for
every endpoint row as:

```text
I = (full - base) - (early - base) - (late - base)
```

The interaction is calculated on signed numeric readout values and also records
the exact f32 bit patterns used by the replay. Morphology labels summarize the
descriptive shape of the interaction/readout pattern only. They are not
biological, behavioral, or mechanistic claims.

## Fail-closed gates

Execution stops before emitting a qualified result if any required F2 hash is
missing or drifts, the F2 raw execution is incomplete, a selected pair is
missing or not strictly ordered, the reconstructed baseline or group differs,
an endpoint prefix is illegal, replay is not exact, or an inherited/actual
endpoint fails its final geometry gate. Counterfactual early/late geometry
failure is reported and does not trigger this abort. The output firewall
rejects behavior/science fields and all writes are confined to this LA1
directory.

## Outputs

`qualification/execution/` contains the receipt-backed selector and one
immutable JSON receipt per selected group. `qualification/derived/` contains
`RESULT.md`, `SUMMARY.json`, and `STATUS.json`. Unit, smoke, and full
qualification commands are recorded in the final status receipt.
