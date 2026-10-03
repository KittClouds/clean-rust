# Q10-RMT review-only audit

**Audit date:** 2026-09-17  
**Scope:** sealed Q10-RMT source manifest, protocol/config, archived merged receipts, and JSONL/JSON consistency.  
**Forbidden work:** no scientific bundle, behavioral measurement, repair application, or DH08B execution was run.

## Disposition

The archived topology payload is internally coherent for its main endpoint, row,
component, class, prefix, move-count, and replay-count claims. It is **not
currently a self-contained sealed receipt** because the canonical paths named by
the root status/result and merged execution receipt do not exist, and the merged
row-persistence summary contains a denominator error for a heterogeneous-row
subset. Retain the topology claims as diagnostic evidence, but do not promote
the current root status to a clean sealed handoff until the follow-up checks
below pass.

The audited payload was:

`qualification/failed-pre-final-reseal-merged/`

The root files refer to `qualification/sample-9731-9732/`, which is absent at
this audit snapshot. Fourteen `final14_*` directories were present with only
empty `moves.jsonl` files, and fourteen Python RMT processes were still running;
those partial outputs were not treated as receipts.

## Findings

### [P1] Canonical receipt identity and path are broken

**Evidence:**

- `STATUS.json` names `qualification/sample-9731-9732/execution.json` and
  `authority-summary.json`, but that directory does not exist.
- `RESULT.md` uses the same missing canonical directory.
- The archived merged `execution.json` records shard paths named
  `qualification/shard14_00` through `shard14_13`; the available completed
  payloads are under `qualification/archived-shard14_00` through
  `archived-shard14_13`.
- The current `final14_*` directories are partial live-run outputs, not the
  completed archived shards.

The pre-execution source hashes themselves are sound: every current source
manifest hash, all eight DA1 fixture hashes, and the DA2 result hash match
`PREEXECUTION.json`. This finding is about output identity and traceability,
not source drift.

**Severity:** P1 / blocking for a sealed handoff.

**Recommended follow-up:** finish or quarantine the live `final14_*` run without
mixing it with the archived payload. Then create one canonical merged output
directory, write its exact shard paths and SHA-256 manifest into the receipt,
and update `STATUS.json`/`RESULT.md` only if that is the deliberate new seal.
The merge should fail closed when an input shard is missing.

### [P1] Merged row-persistence denominators are wrong for rows 768–783

The endpoint JSON has two row-widths: 14 endpoints have 768 rows and 14 have
784 rows. Rows 768–783 therefore have an actual availability denominator of 14.
The merged `authority-summary.json` reports `endpoint_count: 28` and divides
every persistence count by 28. For example, row 768 has 11 mismatches:

- receipt persistence: `11 / 28 = 0.392857...`
- correct persistence: `11 / 14 = 0.785714...`

This is caused by `scripts/merge_q10_rmt.py`, which uses `len(endpoints)` for
every row instead of counting endpoints whose `total_rows` includes that row.
The per-endpoint mismatch/class/prefix totals are unaffected, but the affected
row-persistence metrics are not valid as emitted.

**Severity:** P1 for any interpretation using row persistence; P2 for the
other topology claims.

**Recommended follow-up:** recompute merged persistence with per-endpoint row
availability, add a check that `sum(mismatch_count)` equals the flattened row
receipt, and independently verify all rows whose widths differ. Do not use the
current persistence array in a downstream interpretation.

### [P2] Merge and built-in audit do not fail closed on shard identity

`merge_q10_rmt.py` concatenates and sorts shard records but does not assert:

- exact coverage of the 28 DA2 `DA2_GEOMETRY_PASS` endpoint keys,
- no duplicate endpoint keys,
- non-overlapping/contiguous shard slices,
- equality of every shard's excluded receipt,
- shard file hashes in the merged receipt.

It also silently replaces `excluded` with the last shard's file. The fourteen
archived shards happen to have identical excluded receipts and exact DA2
pass/fail coverage in this audit, so no mismatch was observed in this payload.
The implementation is still permissive enough to produce a plausible merged
receipt from an incomplete or mixed shard set.

The existing `audit_q10_rmt.py` checks baseline row bits/ULPs and the aggregate
serialized-move count, but does not perform those exact-set, shard, persistence,
or full topology-receipt checks.

**Severity:** P2.

**Recommended follow-up:** add a post-merge manifest containing each shard's
path, SHA-256, endpoint-key set, slice, row/component/move counts, and excluded
receipt hash. Make the audit compare the merged endpoint set directly with the
DA2 pass set and compare excluded keys with the DA2 non-pass set. Validate move
schema and row/component relationships in the independent audit rather than
only counting lines.

### [P3] One narrative median is underspecified

The JSON supports the stated median mismatch count (249), median total ULP
distance (332), and median component sizes (one row, five coordinates). The
28 endpoint `move_count_serialized` values have a standard median of **5804.5**
(middle values 5803 and 5806). `RESULT.md` reports 5,804 without defining a
lower-middle, rounded, or truncated convention.

**Severity:** P3 / reporting clarity.

**Recommended follow-up:** state the median convention or report 5804.5; keep
the raw per-endpoint values as the authority.

## Independently verified claims

The following checks passed against the archived JSON/JSONL without running any
scientific or behavioral workload:

- 28 unique merged endpoints exactly matched the 28 DA2 geometry-pass keys;
  the four excluded keys exactly matched the four DA2 non-pass keys.
- Archived shard coverage was 14 shards × 2 endpoints, with no duplicate or
  missing endpoint key. Shard sums matched the merged totals: 7,003 rows,
  2,738 components, and 168,071 serialized move records.
- All 1,792 local replay checks were marked passed, and the independent baseline
  audit completed successfully.
- Row classes and first-helpful-prefix counts recomputed exactly:
  3,277 immediate; 1,128 at 2 ULP; 1,172 at 4 ULP; 703 at 8 ULP; 397 at
  16 ULP; 326 with no helpful prefix.
- Component summaries recomputed exactly: median one row/five coordinates,
  largest component 13 rows, and maximum component error share
  `0.39268464158213345`.
- The 168,071 move records parsed with unique move keys. Stage labels were
  valid; helpful rows were a subset of raw rows; helpful and worse rows did not
  overlap; row-effect rows were a subset of raw rows.
- No receipt flag indicated repair, behavioral inference, scientific seed use,
  or DH08B authorization.

## Follow-up gate

The next engineering decision should remain closed until the canonical receipt
identity is repaired and the row-persistence summary is regenerated and
re-audited. The current topology evidence supports choosing a subsequent
engineering qualification, but it does not by itself authorize DH08B.

## Follow-up verification

The blocking findings above were repaired before final handoff. The canonical
`qualification/sample-9731-9732` root now exists; `execution.json` contains
relative shard paths, per-shard endpoint slices, endpoint identities, and
SHA-256 manifests; the merge fails closed on missing, duplicate, or mixed
shards; and row persistence uses the number of endpoints whose declared row
width includes each row. The independent audit re-ran successfully with:

`endpoints=28 rows=7003 moves=168071 components=2738`

and verified `1792/1792` local replay checks, exact DA2 endpoint coverage,
shard hashes, row persistence, and current source-manifest hashes. The
underspecified serialized-move median was corrected in `RESULT.md` to
`5804.5`. Q10-RMT remains diagnostic-only and DH08B remains closed.
