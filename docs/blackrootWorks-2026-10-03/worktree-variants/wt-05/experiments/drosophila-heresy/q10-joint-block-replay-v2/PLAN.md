# Q10-JBR2: Jointly Committed Block Replay

Q10-JBR2 is an engineering-only qualification of exact local block replay for
the Q10 sequential-f32 endpoint problem. It starts from the committed true
endpoint produced by the frozen Q10-SM constructor, chooses deterministic
three-coordinate blocks, and evaluates all 125 combinations of the five
declared prefix lengths for the three coordinates. Each candidate is committed
simultaneously into a cloned f32 weight state and read by the actual sequential
f32 operator.

The primary engineering receipt is the minimum directly replayed residual norm
relative to the event baseline mismatch. The receipt is descriptive only. It
does not estimate a scientific effect, authorize DH-08B, or run scientific
seed bundles. Shared-pair blocks and disjoint-row blocks are both required so
the locality of any local residual reduction can be inspected.

The constructor deliberately does not add an additive, pairwise, or third-order
surrogate. The sequential readout is the oracle for every joint candidate.

Frozen design:

- protocol: `Q10-JBR2`
- engineering seeds: `9701`, `9702`
- sides: `R`, `L`
- tau values: `4`, `16`
- trial: `128`
- three shared-pair and three disjoint triples per event
- prefix lengths: `1`, `2`, `4`, `8`, `16`
- 125 simultaneous endpoint combinations per block
- one simulator thread
- zero scientific seed bundles
- no behavioral inference
- DH-08B remains unauthorized

This qualification cannot establish global repair feasibility. It can establish
whether exact small-block replay is executable, whether the declared block
coverage is available, and how much directly replayed local residual reduction
is exposed by the tested blocks.
