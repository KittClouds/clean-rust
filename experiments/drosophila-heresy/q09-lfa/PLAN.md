# Q09-LFA: Linear Feasibility Audit

Status: `CONSTRUCTOR_QUALIFICATION_ONLY_NO_SCIENTIFIC_SEEDS`

Q09 is an engineering audit of the endpoint-control geometry exposed by Q08. It does not run a measured scientific protocol, inspect task performance as an outcome, or authorize Q10. Q08 remains permanently `BLOCKED_PRESEAL_CONSTRUCTOR_QUALIFICATION`; its source, contract, receipts, and archive are immutable.

## Frozen lineage

- Q08 archive SHA-256: `f0e08a083de067d64e029f72d611d1341236af129324b360dd4280a1b2654a57`
- DH-08A run seal SHA-256: `a21f2e19688181955d5d01180e218a6b66f19f0d560305919aa21c6f579d3a13`
- Q09 engineering seeds: `9201..9205`
- Stage A uses seed `9201`, both left/right slices, taus `4,16`, and all 256 reversal events per slice/tau, for 1,024 audited states.
- Stage B may use only `9202..9205`, after Stage A review, for a total of 5,120 audited states.
- Scientific seed count is zero. No behavioral inference is permitted.

## State and intervention

At each reversal event, read committed f32 states and perform audit arithmetic in f64:

```text
d_T = W_T - W_B
```

`W_B` is the committed base state and `W_T` is the committed true endpoint state. Boundary coordinate memberships are frozen from `W_T`; boundary coordinates and coordinates outside the active interval support are held fixed. The variable interior coordinates are `I_t`.

The acquisition axis is the single global vector `A = W_A - W_0`. Q09 applies no per-MBON, per-group, per-signature, or per-block axis constraints.

## Linear operator

For each event, construct the actual cue-by-MBON drive operator from the learner’s source-coordinate semantics. There are 16 cue rows for each MBON drive, so the operator has `16 * post_len` rows and `|I_t|` columns. Each row must reproduce one exact linear cue/MBON drive from the variable source coordinates; aggregate cue scores are not admissible. Append one global acquisition-axis row restricted to `I_t`:

```text
L = [H_t; A_I^T]
```

Rows are scaled by their f64 Euclidean norm before rank analysis. The implementation must save all `16 * post_len + 1` singular values, numerical rank, nullity, row scales, and rank diagnostics. The frozen rank cutoff is:

```text
sigma_i > sigma_max * max(rows, cols) * f64::EPSILON * 1_000
```

The same rule is used for qualification and measured protocol design; it is not selected from outcomes.

## Projection and diagnostics

Let `x_T` be the interior part of `d_T`, and let `d_F` contain the frozen boundary displacement. With the row-scaled thin SVD, calculate the minimum-norm constrained projection:

```text
x_star = V_r V_r^T x_T
d_star = d_F + E_I x_star
n_T = d_T - d_star
```

Record reconstruction error, row residuals, null annihilation, axis leakage, and the null energy fraction. Decompose `n_T` relative to the acquisition axis and report signed and absolute residual cosine floors. For residual rank `k`, the optimistic unbounded floor is:

```text
k = 0: 1
k = 1: |F-E|/(F+E)
k >= 2: 0 if E >= F, otherwise (F-E)/(F+E)
```

Q09 is an audit of linear freedom. It does not construct a box-feasible null intervention and does not test sequential f32 endpoint equality. Those are explicitly deferred.

## Qualification gates

The qualifier must prove, on engineering states only:

- full cue-by-MBON operator dimensions and direct agreement with the learner’s drive calculation;
- linearity and deterministic construction;
- SVD projection, row annihilation, null annihilation, axis-row agreement, and energy identities;
- all singular values, rank, nullity, and floor cases for residual dimensions 0, 1, and at least 2;
- no mutation or RNG consumption by counterfactual calculations;
- observer on/off invariance, zero hot-loop allocation, finite values, and f32 committed-state parity;
- Q08 source and archive identity unchanged;
- no measured CLI mode and rejection of scientific seeds.

Q09 output status is one of:

- `LINEAR_AUDIT_VALID__FREEDOM_PRESENT`
- `LINEAR_AUDIT_VALID__CONSTRAINT_DOMINATED`
- `LINEAR_AUDIT_VALID__NUMERICALLY_AMBIGUOUS`
- `LINEAR_AUDIT_INVALID`

Q10 is considered only if Q09 is valid and reports usable linear freedom. No Q10 work is authorized by this plan.

## Execution implementation note

The first attempted Stage A process was intentionally quarantined before completion after its single-thread dense-SVD audit exceeded the practical runtime budget; a second attempt was likewise stopped after its fixed four-thread audit remained impractical. The retry keeps simulation and RNG single-threaded, and runs the independent post-simulation linear audits in a fixed eight-thread Rayon pool with ordered collection. This changes execution scheduling only; it does not change the operator, rank rule, audit tolerances, seed scope, or scientific contract.
