# Q10-RH1-CQ1: Common Runtime Qualification

## Identity and purpose

`Q10-RH1-CQ1` is a qualification-only identity for the common runtime that will precede the RH1 ranking-by-horizon comparison. It creates no measured RH1 factorial evidence and does not modify any parent artifact, scientific seed, or canonical model.

The identity has one engineering question:

> Can both future RH1 ranking arms use the same candidate representation, score domains, exposure semantics, provenance gates, and budget rules without allowing ranking order to change candidate identity?

The sealed PF6-S1 execution remains historical evidence. RH1-CQ1 reads it and the sealed RMT sample; it does not rerun PF6-S1 and does not reinterpret its aggregate reports in place.

## Locked boundaries

- Write only inside `q10-rh1-cq1-v1`.
- Do not modify `q10-pf5-v1`, `q10-pf6-v1`, `q10-pf6-s1-v1`, `q10-rmt-v1`, parent artifacts, or scientific seeds.
- Do not launch RH1-F1, the 32-group primary 2x2, or the 23-group secondary run.
- Do not use NA pair/triple information in the ranking implementation or qualification.
- Keep missing authority observations as explicit `UNKNOWN`; never coerce them to zero.
- Reject any parent/helper/RMT hash mismatch before constructing a qualification report.

## Common runtime contract

The runtime defines a complete candidate as a canonical map:

```text
coordinate_id -> prefix_choice
```

The serialized form is sorted by ascending `coordinate_id`. Unvisited coordinates have legal prefix `0`; visitation order is not part of state identity. The canonical state identity is used by candidate caches, stable tokens, tie keys, and any future beam-state serialization.

The strict objective remains the PF6 tuple:

```text
(mismatch_count, total_ulp_distance, residual_l2, maximum_absolute_residual)
```

Implementation tie-breakers are appended only after this strict tuple and use the canonical state identity. Positional prefixes, ranking position, visitation order, and exploration order never enter candidate identity.

## Ranking arms

The residual ranking arm preserves PF6 semantics: for each coordinate, sum squared residual over mismatched declared rows in that coordinate's physical support, then break ties by mismatched-row count, replayed-prefix count, and ascending coordinate id.

The authority-informed arm uses only RMT records. It ranks measured coordinates by helpful-row count, helpful-row residual burden, smallest observed helpful prefix, raw-support mismatch coverage, and coordinate id. Authority coverage is explicit:

- `MEASURED_COMPLETE`: every declared authority prefix is present;
- `MEASURED_PARTIAL`: the coordinate has RMT observations, but some prefixes are absent and remain unknown;
- `UNKNOWN`: no RMT observation exists for the endpoint-coordinate pair.

Unknown coordinates remain in a deterministic fallback tier ordered by the PF6 residual specification. Missing records are never treated as measured non-helpful authority.

The required CQ1 coverage gate is endpoint-coordinate presence for every selected S1 group coordinate. Prefix-level completeness is not required by the sealed RMT artifact and is reported separately.

## Cohorts

The fixed primary cohort is every selected S1 group with at least 32 coordinates: exactly 32 groups. Its future RH1 comparison is 16 versus 32 rounds.

The fixed secondary cohort is every selected S1 group with 17 through 31 coordinates: exactly 23 groups. Its future long arm may run to its complete coordinate horizon. It is reported separately and cannot alter primary-cohort selection.

The remaining 29 selected S1 groups are outside RH1-CQ1 cohorts. They are retained in provenance counts but cannot be silently sampled into either RH1 arm.

## Spatial score domains

Every future candidate score must be available in three domains:

1. `D` declared group rows: the primary local-search domain;
2. `P` full physical support: the union of rows physically affected by the group's coordinates;
3. `G` whole endpoint: the complete readout, retained for collateral damage and global diagnostics.

Exact whole-endpoint parity is not an isolated-group search target when rows lie outside the group's support.

## Exposure and termination

Exposure to round `r` requires that the runner actually completed round `r`; coordinate availability is checked separately. A padded receipt round is not evidence of exposure. Termination is classified as `NATURAL_COORDINATE_END`, `HORIZON`, `REPLAY_BUDGET`, `NO_EXPANSION`, or `INVALID`.

## Budget and scope

The future RH1 runner must scale the per-group replay allowance with horizon:

```text
B16 = 32768
B32 = 65536 = 2 * B16
```

This CQ1 identity only validates the rule; it does not spend either measured factorial budget.

## Qualification outputs

CQ1 produces:

- `qualification/REPORT.json`: machine-readable provenance, cohort, domain, coverage, and identity-audit results;
- `qualification/REPORT.md`: human-readable qualification report;
- `qualification/SMOKE_REPORT.json`: unit/smoke result receipt.

The report status is `CQ1_SCAFFOLD_QUALIFIED_UNIT_SMOKE_ONLY` only when all binding, cohort, identity, ranking, unknown-authority, domain, exposure, and budget checks pass. It never authorizes RH1-F1.
