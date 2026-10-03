# Q10-RMT: Residual Mismatch Topology and Local Repair Authority

Q10-RMT completed as an engineering-only diagnostic over the 28 Q10-DA2
geometry-valid endpoints. The four DA2 geometry failures were retained in the
excluded receipt and were not included in the primary topology.

The independent audit passed:

- 28 endpoints and 7,003 mismatched readout rows mapped.
- 168,071 serialized authority moves and 2,738 helpful row components mapped.
- 1,792 local replay checks passed bitwise.
- No repair was applied, no behavior was measured, and DH08B remains closed.

The residual is strongly scale gated. At one ULP, 3,726 rows (53.2%) were
orphan rows with no helpful move and 2,274 (32.5%) were fragile rows with one
helpful coordinate. Only 1,003 rows (14.3%) had broad one-step authority.
After the predeclared 2, 4, 8, and 16 ULP escalation, 3,277 rows (46.8%) had
an immediate helpful move, 3,400 (48.6%) first became helpful at a larger
prefix, and 326 (4.7%) retained no local authority through 16 ULPs.

The final first-helpful-prefix counts were:

| First helpful prefix | Rows |
| ---: | ---: |
| 1 ULP | 3,277 |
| 2 ULP | 1,128 |
| 4 ULP | 1,172 |
| 8 ULP | 703 |
| 16 ULP | 397 |
| none through 16 ULP | 326 |

The helpful row graph is mostly local: the median component contains one row,
the largest contains 13, and the median component contains five coordinates.
The distribution is not uniformly diffuse: the largest component accounts for
39.3% of one endpoint's squared residual, so component size and residual share
must remain separate diagnostics. The median endpoint has 249 mismatched rows,
332 total ULPs of mismatch, and 5,804.5 serialized move records (the standard
median of the two middle endpoint values).

These results support a narrower engineering conclusion:

> The sequential f32 repair authority is distributed and strongly prefix
> gated. One-ULP authority is an incomplete view of the local action space;
> larger legal prefixes expose new readout directions. A small residual set
> remains locally unreachable through 16 ULPs.

This does not establish that a simultaneous repair exists. The map contains
prefix constraints and exact sequential-f32 interactions, so the next leg must
test feasibility with one final prefix choice per coordinate and exact replay.
The relaxed component projections are bounded diagnostics using the sealed
256-column cap; they are not repair claims.

The next engineering legs are Q10-PF5 and the parallel Q10-NA diagnostic.
Q10-PF5 is the fresh staged, prefix-constrained feasibility qualification. Its
first gate should be a coordinate-group convex relaxation, followed only by
exact replay on groups that pass the relaxation. It must allow bounded
intermediate geometry debt and deterministic explore/exploit search, because
the final geometry contract applies to the completed endpoint rather than to
each partial assignment. Q10-NA separately treats the 326 no-helpful rows as
interaction diagnostics, not impossibility certificates, and tests complete
small raw-support neighborhoods where tractable. No scientific bundle or
behavioral endpoint should open until both engineering protocols are sealed
and audited.
