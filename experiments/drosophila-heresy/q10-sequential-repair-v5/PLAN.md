# Q10-SR5 Multi-Step Effect Capacity Qualification

## Purpose

Q10-SR5 is a new engineering identity that tests whether the one-ULP effect
bank used by Q10-SR4 was too narrow for the existing repair search. It expands
the capacity diagnostic to the same maximum of 16 committed ULP steps per
coordinate and direction that the frozen sparse search is permitted to use.
It does not open scientific bundles, estimate behavior, or authorize DH-08B.

## Lineage

Q10-SR4 completed 5,120 fresh engineering states under a sparse-effect Gram
factorization. All 5,015 parent-eligible readout mismatches were conservatively
classified as partial, with no search entry. That result is valid, but it does
not prove that the search's 16-step reachable set is partial because SR4's
capacity bank contained only the first ULP effect for each coordinate and
direction.

Q10-SR5 keeps the SR4 factorization and search policies, but constructs the
capacity bank from every legal committed position from one through 16 ULP
steps in each direction, stopping at bounds or the frozen 16-ULP final reserve.
The bank is a necessary linearized effect-space audit of the actual search
budget. It is not a claim that arbitrary bank coefficients are path-realizable.

Fresh engineering seeds are used:

- Stage 1A: seed 9541.
- Stage 1B: seeds 9542, 9543, 9544, and 9545.

## Frozen execution

The producer uses the frozen Q10-SM constructor, canonical sequential f32
readout, exact binary32 committed positions, the multi-step sparse effect bank,
and the existing sparse repair search. Capacity partial, empty, or ambiguous
events remain fail-closed and do not enter search. The independent reviewer
replays committed receipts with the standard library and enforces the same
receipt firewall as Q10-SR4.

Stage 1A must complete and pass independent review before Stage 1B opens. A
producer, reviewer, factorization, memory, or bounded-performance failure
invalidates the protocol and leaves later seeds unopened. A capacity result is
diagnostic engineering evidence only.

## Interpretation matrix

- If multi-step residuals remain large and all events remain partial, the
  one-ULP gate was not the main bottleneck; the legal search effect space is
  structurally incomplete for the observed readout errors.
- If multi-step residuals become near zero for a material fraction of events,
  SR4 was a sufficient-but-too-strong gate and a later protocol may qualify
  bounded search on the expanded bank.
- If the factorization is slow or memory-unstable, stop and report the resource
  boundary; do not silently reduce seeds, steps, or review coverage.

## Frozen constraints

- No scientific seed bundles, behavioral inference, or DH-08B authorization.
- Parent Q10-SM hashes must match at seal and execution.
- Q10-SR4 is a predecessor diagnostic, not a parent science result.
- Two taus (4 and 16), two sides (R and L), four bundles per seed.
- Eight Rayon workers; no simulation hot-loop allocation.
- Sixteen committed capacity steps per coordinate and direction.
- Sixteen-ULP final reserve, rank multiplier 1000, projection tolerance
  2e-10, coefficient resolution 1e-12.
- Beam width 64, branch width 64, maximum 64 moves, maximum 16 steps per
  coordinate.
