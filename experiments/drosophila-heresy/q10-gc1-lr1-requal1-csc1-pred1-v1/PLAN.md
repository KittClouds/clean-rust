# CSC1-PRED1: held-out geometry routing test

This engineering-only identity consumes VMAT1 constraint vectors and the sealed
CSC1-R1 definitions. It evaluates a deterministic, outcome-blind partner score
on a hash-held-out fold of the existing 4,999 pair domain. It performs no new
replay and does not tune a score after inspecting outcomes.

The evaluated source is an individually geometry-invalid singleton whose
singleton readout score is better than the fresh V score. Candidate partners
are the observed partner actions in the same context. The test fold is selected
by SHA-256 of context, pair index, and direction; only held-out candidates enter
the reported ranking pools. Full constraint-vector alignment is compared with
prespecified readout, magnitude, scalar-axis, and deterministic-random
baselines.
