# REDLINE Phase 4: transport collapse census

Date: 2026-09-18. Scope: read-only mechanism qualification on the frozen
10,000-document transport-x3 probe. No ranking thresholds or transport
semantics changed.

## Question

Transport expansions already compete inside each query group before their
winning contribution enters the classic cross-group accumulator. Phase 4 asks
whether that existing group-local collapse leaves enough duplicate work to
justify a new traversal kernel.

An opt-in receipt census (enabled with
`PHOENIX_QPS_PHASE4_DIAGNOSTICS=1`) records:

- `A`: raw expansion posting rows consumed;
- `U`: unique group-document winners after expansion competition;
- literal and nonliteral winner-document counts;
- rows belonging to expansions that win at least once (`W_any`);
- rows belonging to expansions that never win;
- rows from expansions that win only outside the final candidate pool;
- touched documents rejected by the coverage floor.

The derived mechanism ratios are:

```text
collapse = A / U
authority = W_any_rows / A
dead = (A - W_any_rows) / A
```

`U` is summed per group, so the same document can contribute once for each
group. This matches the amount of cross-group accumulator work that survives
the group-local competition.

## Frozen probe result

The release `perf_probe` was built into the isolated `D:\phoenix-builds` target
and run on the existing 10k x 96 corpus:

| metric | value |
|---|---:|
| raw expansion rows (`A`) | 10,692 |
| unique group-document winners (`U`) | 9,741 |
| nonliteral winner documents | 9,429 |
| literal winner documents | 312 |
| rows in expansions winning anywhere (`W_any_rows`) | 10,692 |
| rows in expansions never winning | 0 |
| rows from expansions winning only outside pool | 0 |
| touched but uncovered documents | 1,945 |
| collapse (`A/U`) | 1.098x |
| winner authority (`W_any_rows/A`) | 1.00000 |
| dead expansion-row ratio | 0.00000 |

The same release probe measured transport-x3 at 211,469 ns/query with the
census disabled and 487,909 ns/query with the opt-in census enabled. The
diagnostic number is intentionally not a serving result; it demonstrates why
the accounting must stay off the hot path. The normal serving result is below
the sealed 246,823 ns baseline for this probe.

The current semantic collapse is therefore real but small: it removes about
8.9% of duplicate group-document contributions, while every expansion earns a
winner somewhere. There is no measured expansion deadwood to prune, and no
expansion is winner-only outside the final pool on this workload.

## Decision

Phase 4 does **not** earn a new transport traversal kernel on this corpus.
The serving architecture remains:

```text
group-local expansion max
    -> classic cross-group accumulator
    -> Phase 2 lazy evidence
```

The census stays available for later corpora and query families. A future
transport optimization must show materially larger `A/U`, nonzero dead-row
authority, or a measured latency win before changing serving code. The literal
decision remains closed from Phase 3C: classic accumulation is the serving
kernel; WAND and fused literal merge remain exact qualification/oracle arms.

## Verification

- `cargo test -p phoenix-lexical-qps --lib`: 31 passed.
- `cargo check -p phoenix-lexical-qps`: passed.
- Release probe built and executed from the isolated `D:` target.
- Differential transport assertions verify raw-row accounting, `A >= U`,
  winner-row bounds, and mode-invariant receipts.

Normal release serving leaves this census disabled, so the winner scans and
expansion accounting do not become a permanent transport latency tax.
