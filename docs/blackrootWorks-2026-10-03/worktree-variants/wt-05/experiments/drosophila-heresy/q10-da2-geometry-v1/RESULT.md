# Q10-DA2 engineering result

Q10-DA2 replayed all eight sealed Q10-DA1 engineering events and all 32
fixed support-disjoint coalitions. The independent audit reconstructed every
final committed f32 endpoint from the selected ULP steps and verified the
reported sequential readout, acquisition-axis, displacement-norm, and linear
cue-drive metrics.

Twenty-eight of 32 coalitions (87.5%) satisfied the Q10-SM geometry contract:
axis normalized error <= 2e-6, norm normalized error <= 2e-7, and linear
cue-drive normalized error <= 2e-6. All 32 also stayed within the 16-ULP
reserve and maximum 16-ULP coordinate movement. The four failures were
selector failures on the axis gate only; their norm and linear-drive metrics
passed. Their axis normalized errors were 4.42e-5, 1.67e-4, 1.90e-4, and
2.60e-4.

The result is a bounded-geometry feasibility result, not a repaired endpoint
result. None of the 32 endpoints achieved bitwise equality with the target
sequential f32 readout; final mismatch counts ranged from 215 to 276. The
distributed selector therefore demonstrates that DA1's readout authority can
usually be made geometrically compatible, but it does not yet satisfy the
full readout contract needed for DH08B.

Decision: keep DH08B closed. The next engineering leg should widen the
deterministic correction policy only for the remaining axis failures while
adding a readout-parity objective or capacity audit. Do not infer that the
four failures are physically infeasible; they are failures of the declared
one/two-coordinate selector.

Receipts:

- `PREEXECUTION.json` — final source and input hashes.
- `qualification/sample-9731-9732/execution.json` — aggregate result.
- `qualification/sample-9731-9732/results.json` — 32 set-level results.
- `scripts/audit_q10_da2.py` — independent endpoint reconstruction audit.
