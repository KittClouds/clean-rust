# Q10-SR5 result

Status: `Q10_SR5_STAGE2A_INVALID`

Q10-SR5 was designed to test whether Q10-SR4's one-ULP capacity gate was too
narrow for the frozen repair search, which permits up to 16 ULP steps per
coordinate. The new identity expanded the sparse capacity bank to every legal
committed position from one through 16 steps in each direction and retained the
readout-space Gram factorization.

The engineering design was not viable as implemented. Stage 1A seed `9541`
was opened, but after a bounded 10.18-minute observation window it had committed
only the pre-execution receipt and no bundle. The producer was stopped cleanly;
Stage 1B seeds `9542..9545` were never opened. The largest observed working set
was approximately 1.43 GB, and the multi-step bank remained the dominant cost.

This is a performance qualification failure, not a capacity, repair,
impossibility, behavioral, or scientific result. Q10-SR5 may not be resumed or
tuned under the same identity. The result rules out the naive full multi-step
bank construction for the next design. A continuation needs a streamed or
implicit multi-step effect representation, a sampled engineering audit, or a
different necessary-condition formulation before another full qualification is
opened.
