# Q10-SR4 Sparse-Effect Capacity Qualification

## Purpose

Q10-SR4 is an engineering qualification for the sequential-f32 endpoint-repair
path descended from Q10-SM. It does not open scientific bundles, estimate
behavior, or authorize DH-08B. The only question is whether the frozen repair
pipeline can continue to classify readout mismatches and, where capacity is
demonstrably exact, enter the existing bounded sparse repair search.

## Lineage and fresh identity

The parent is the sealed Q10-SM stage-1 artifact. Q10-SR1 was invalidated by a
40-minute full-vector search performance failure. Q10-SR2 was invalidated by an
independent-reviewer signed-zero mismatch after its Stage-1A producer run.
Q10-SR3 corrected the reviewer and verified Stage 1A, then was invalidated
after a Stage-1B capacity-factorization worker exceeded the bounded engineering
window. No scientific seed bundle was opened in any predecessor.

Q10-SR4 is a new protocol identity with fresh engineering seeds:

- Stage 1A: seed 9531.
- Stage 1B: seeds 9532, 9533, 9534, and 9535.

The parent Q10-SM hashes and its fail-closed status are checked at runtime.

## Factorization redesign

The capacity gate receives the sparse one-ULP move bank and the actual-target
sequential readout error. The previous wide SVD factored a matrix with one
column per legal move. Q10-SR4 instead compresses duplicate effect columns and
forms the readout-space Gram matrix

\[
G = A A^T = \sum_j m_j e_j e_j^T,
\]

where \(e_j\) is a unique sparse readout effect and \(m_j\) is its legal-move
multiplicity. A deterministic f64 symmetric eigendecomposition of \(G\) gives
the same retained left singular subspace while bounding the factorization by
the number of readout rows. The rank cutoff, projection tolerance, and
coefficient resolution remain frozen at their Q10-SR3 values.

For exact events only, the implementation computes the minimum-L2 relaxed
full-bank coefficient diagnostics from the retained eigenpairs. Partial,
empty, or numerically ambiguous events remain capacity-gated and do not enter
the repair search.

## Frozen execution

The producer uses the frozen Q10-SM constructor, canonical sequential f32
readout, exact adjacent-binary32 move bank, and the existing sparse beam search.
All ordinary exogenous task inputs and RNG streams remain paired within an
engineering seed. No scientific or behavioral output is read by the producer
or reviewer. The independent reviewer replays committed receipts using only
the Python standard library and matches Rust's f32 iterator-sum identity,
including the empty-row negative-zero result.

Stage 1A must complete and pass independent review before Stage 1B can open.
Any producer, seal, manifest, reviewer, capacity, or performance-integrity
failure invalidates the protocol and leaves later seeds unopened. A capacity
partial result is valid diagnostic evidence, not a repair-capacity claim.

## Acceptance and interpretation

The protocol is valid only if all four Stage-1A bundles commit, the producer
execution counters reconcile, the source manifest and executable identity
match the pre-execution seal, and the independent reviewer verifies every
replay. Stage 1B has the same requirements for its four fresh bundles.

Possible valid engineering outcomes include a capacity-gated mixture, no
repair within the frozen search, or exact repairs. None authorizes DH-08B or
supports a behavioral claim. The old wide-SVD result is not retroactively
reinterpreted; this protocol evaluates the new sparse-effect Gram gate under a
new identity.

## Frozen constraints

- No scientific seed bundles, behavioral inference, or DH-08B authorization.
- Parent Q10-SM hashes and status must match at seal and execution.
- Two taus (4 and 16), two sides (R and L), four bundles per seed.
- Eight Rayon workers; no producer allocations in the simulated hot path.
- Readout capacity tolerance 2e-10.
- Rank multiplier 1000; coefficient resolution 1e-12.
- Beam width 64, branch width 64, maximum 64 moves, maximum 16 steps per
  coordinate, and final reserve of 16 ULPs.
- No search entry for partial, empty, or ambiguous capacity.
