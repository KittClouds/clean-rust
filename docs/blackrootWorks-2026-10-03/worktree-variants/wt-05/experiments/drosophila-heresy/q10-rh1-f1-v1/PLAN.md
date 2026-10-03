# Q10-RH1-F1: Ranking-by-Horizon Engineering Factorial

RH1-F1 tests whether PF6 residual ordering and complete AC2 authority ordering
expose useful bounded repair progress at different search horizons.

The primary cohort is the fixed 32 frozen RH1 groups with at least 32
coordinates. It receives the factorial:

```text
                       horizon 16       horizon 32
residual ranking            A                 B
complete authority          C                 D
```

The secondary cohort is the fixed 23 frozen RH1 groups with 17 through 31
coordinates. It receives horizon 16 and its complete available coordinate
horizon, with results reported separately from the primary factorial.

The residual arm preserves the PF6 residual ordering. The authority arm uses
only the complete AC2 feature table, with the frozen order
`helpful_row_count`, `helpful_ulp_burden`, median first-helpful scale,
declared-support count, then coordinate id. No RMT partial features or NA
pair/triple data enter the ranking.

Candidate identity is a canonical `coordinate_id -> prefix_choice` map sorted
by coordinate id. Beam traversal order is never part of identity, caching, tie
hashing, or committed state bytes. The beam objective is the strict tuple over
declared group rows `D`; every candidate also receives exact `P` physical
support and `G` whole-endpoint scores.

This is engineering-only. It consumes no scientific seed bundles, runs no
behavioral probe, and does not authorize DH08B.
