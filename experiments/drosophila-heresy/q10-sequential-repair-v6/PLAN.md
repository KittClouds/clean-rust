# Q10-SR6 Streamed Multi-Step Capacity Qualification

## Purpose

Q10-SR6 tests the same 16-step-per-coordinate capacity vocabulary proposed by
Q10-SR5, but streams each sparse effect directly into the readout-space Gram
matrix. It removes the materialized `LegalMove` bank that caused SR5's
performance abort while preserving the frozen capacity tolerance and the
fail-closed search gate. This is engineering qualification only: no scientific
bundles, behavioral inference, or DH-08B authorization.

## Lineage

Q10-SR4 validly qualified a one-ULP sparse Gram gate, but all 5,015 eligible
events were partial. Q10-SR5 tested all 16 steps by materializing every sparse
effect column and failed before its first Stage-1A bundle because the bank was
too memory-heavy. Q10-SR6 keeps the 16-step effect definition and changes only
the representation: it accumulates \(G = A A^T\) in readout space and does not
retain the individual multi-step columns. Since the gate only needs the column
space, this is a bounded necessary-condition audit, not a repair path.

Fresh engineering seeds:

- Stage 1A: seed 9551.
- Stage 1B: seeds 9552, 9553, 9554, and 9555.

## Streamed construction

For each interior coordinate, direction, and legal committed position from one
through 16 ULP steps, Q10-SR6 replays only the affected canonical readout rows.
The sparse effect is accumulated into the symmetric f64 Gram matrix. The
factorization is a deterministic f64 symmetric eigendecomposition of that
784-row matrix. No multi-step effect vectors or signatures are retained.

The streamed path reports legal and nonzero effect counts but deliberately does
not claim duplicate-column counts or relaxed coefficient diagnostics;
`columns_materialized` is false in those receipts. Partial, empty, or
numerically ambiguous events never enter the existing sparse repair search.

## Acceptance and interpretation

Stage 1A must complete and pass the independent standard-library reviewer before
Stage 1B opens. A valid result can show that the 16-step linearized effect space
remains partial, that it spans a material fraction of errors, or that the
streamed implementation itself fails its performance boundary. None of these
outcomes is a behavioral or scientific finding.

If the streamed 16-step audit remains partial with substantial residuals, the
one-ULP gate was not the main bottleneck. If it reaches exact capacity for a
material fraction of events, a later protocol may qualify actual repair search
on a smaller, explicitly gated sample. The streamed Gram result alone does not
establish path realizability because coefficients are not constrained to a
monotone per-coordinate path.

## Frozen constraints

- No scientific seed bundles, behavioral inference, or DH-08B authorization.
- Parent Q10-SM hashes and status must match at seal and execution.
- Two taus (4 and 16), two sides (R and L), four bundles per seed.
- Eight Rayon workers; simulation hot loop remains allocation-free.
- Sixteen committed capacity steps per coordinate and direction.
- Sixteen-ULP final reserve, rank multiplier 1000, projection tolerance
  2e-10, coefficient resolution 1e-12.
- Beam width 64, branch width 64, maximum 64 moves, maximum 16 steps per
  coordinate.
