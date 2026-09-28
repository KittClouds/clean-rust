# FAS-R1: Semantic Particle Reachability

**Status:** `SEALED_FOR_STAGE0_CONSTRUCTION`, 2026-09-25. Amendment 01 seals this detached design packet and authorizes Stage 0 construction only. This seal does not certify construction readiness. Model contact, training, and evaluation are not authorized by this packet.

**Question:** At a fixed inference cost, can organized, learned multi-hypothesis search reach valid assignments that additional single-trajectory depth does not?

The design packet contains these four specification documents and its versioned amendment/seal receipt:

1. [Design audit](DESIGN-AUDIT.md): scientific and algorithmic corrections needed to make the claim testable.
2. [Stage-zero seam inventory](STAGE-ZERO-SEAMS.md): current repository evidence, reuse boundaries, and prerequisites.
3. [Executor directive](EXECUTOR-DIRECTIVE.md): schemas, tensor shapes, training/evaluation schedule, accounting, and first implementation stop boundary.
4. [Amendment 01 and seal receipt](R1-AMENDMENT-01-SEAL.md): the approved surgical amendments and SHA256 manifest for the exact design packet.

The only relationship to FAS-00 is the proposed model family and pinned revision. FAS-00 is terminally closed at `SENSOR_FAIL_NO_SIGNAL`; R1 needs its own sensor qualification and independent authority. R1 does not inherit FAS artifacts, caches, training, or phase permissions.

The GRAM paper supports the stochastic recursive trajectory inspiration: [Generative Recursive Reasoning](https://arxiv.org/abs/2605.19376). The supplied name “Interference Search” does not yet identify a verifiable source in this packet; state merging is specified and evaluated here on its own terms.
