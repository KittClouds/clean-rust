# Q10-LR1-MAT1: Successful-Pair Materialization and Mechanism Audit

This is a derived engineering child of `q10-gc1-cancel1-lr1-v1`. It materializes exactly the 201 LR1 records classified `VALID_ADVANTAGE_PRESERVED` and independently verifies their singleton and joint states.

The protocol is readout and geometry engineering only. It does not search new pairs, enlarge the shortlist, build a global palette, run behavior, or promote any state to a scientific comparison.

For each successful pair, reconstruct from the frozen LR1 parents:

- baseline endpoint state `B`;
- saved invalid search state `S`;
- historical valid comparison state `V`;
- singleton substitutions `S_A` and `S_B`;
- simultaneous pair substitution `S_AB`.

Each materialized state records its canonical selection, nonzero coordinate-to-prefix map, committed changed f32 mapping, readout bits and hash, score, geometry, signed geometry vector, legality, distinctness, and reconstruction provenance.

The signed geometry vector is:

```text
[ final_axis - target_axis,
  final_norm - target_norm,
  final_linear_drive[row] - target_linear_drive[row] ... ]
```

For every pair, the derived interaction records are:

```text
I_W = W_AB - W_A - W_B + W_S
I_R = R_AB - R_A - R_B + R_S
I_L = L_AB - L_A - L_B + L_S
I_A = axis_AB - axis_A - axis_B + axis_S
I_N = norm_AB - norm_A - norm_B + norm_S
```

Norm interaction is treated as a derived nonlinear metric and is not interpreted as evidence of contextual neural computation by itself.

The run fails closed on missing, duplicate, mismatched, or non-reconstructable lineage records. Existing LR1 and all earlier parent files are immutable. The only writable root is this MAT1 directory.

Success requires:

1. exactly 201 source pair records;
2. every source pair has both source singleton receipts;
3. every reconstructed singleton and pair hash, readout, score, and geometry matches its LR1 receipt exactly;
4. every reconstructed state passes finite, bounds, reserve, support, and canonical-selection checks;
5. output and execution receipts are written atomically with no overwrite path.

This identity produces an authoritative materialized-pair library for the later cancellation-augmented palette decision. It does not establish global feasibility or a future-learning state.
