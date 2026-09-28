# Q10-GC1-D1: Saved-State Failure Anatomy

D1 is a saved-state-only engineering diagnostic. It reconstructs the 14 PAR8
`best_valid` and 14 `best_search` saved maps from the sealed PAR8 receipt,
sealed PAR2 palette library, PF0 topology, and frozen RH1/PF5 runtime. No new
endpoint choices, counterfactual states, beam search, candidate generation,
fresh-seed qualification, or behavior are executed.

Cohort: all 14 endpoint/set cases (seed9731, four slice/tau files), each with
baseline, target, selected best-valid, and saved best-search. Duplicate byte
states may share computation; all case/state labels are preserved.

For each state retain committed weight/readout hashes, canonical mapping,
complete group selection, full global score, signed debts, final gate flags,
support/bounds/boundary/reserve validity, and distinctness from baseline and
target.

For each readout row record baseline/target/state bits, bitwise parity, ULP
distance, signed numerical residual, baseline mismatch status,
physical-support incidence, selected active groups, and selected
coordinates/occurrence counts. Signed zero stays explicit: bitwise mismatch
can coexist with zero arithmetic residual under the inherited ordering.

Partition rows relative to baseline: wrong-to-exact, wrong-to-wrong,
exact-to-wrong, exact-to-exact. Split wrong-to-wrong by ULP
improvement/tie/worsening. Reconcile every case and the aggregate:
`final mismatches = baseline mismatches - repaired + newly damaged`.
Report case incidence and cross-case identity counts separately.

Signed geometry uses the correct reference. Let B be repair-baseline weights,
O inherited geometry-origin weights (`state.base_weights`), T target, a stored
acquisition-axis vector, H linear readout operator with
repeated-coordinate multiplicities. For committed W retain `qA = a dot (W-T)`,
`qL = H(W-T)` full signed row vector, `qN = norm(W-O)-norm(T-O)`,
`qS = norm(W-O)^2-norm(T-O)^2` diagnostic. Use inherited target-based
normalizers and 1e-12 floors. Gates: axis <=2e-6, norm <=2e-7, linear-drive
L2 <=2e-6. No per-row substitute for the linear L2 gate.

Coordinate decomposition: axis by `a_i*(W_i-T_i)`, linear drive by H
multiplicity. Norm uses squared terms only. Group increments relative to B
sum to state-minus-baseline debt; preserve the baseline offset. Verify
disjoint coordinate ownership first; if overlap, use explicit coordinate
accounting with cross terms. Reconcile f64 summation against full inherited
geometry; final checks recompute the full state.

Collateral: report selected active-group degree for damaged, repaired,
persistent-wrong, and initially exact undamaged rows with denominators and
exposure frequencies. Support incidence is association, not cause. Do not
label threshold-gated rows from endpoint bits or support alone.

Bucket resolution: PAR8 exploration uses `round(debt*4096)` on normalized
signed axis/norm errors and unsigned linear-error norm. Width ~2.4414e-4.
Record actual guarded ranges and bucket assignments of saved states. Do not
claim historical beam occupancy or diversity collapse for unretained
candidates.

Outputs: STATE_ANATOMY, ROW_TRANSITIONS, SIGNED_GEOMETRY, GROUP_SUPPORT,
BUCKET_RESOLUTION, reconciliation receipt, short interpretation. Pass
requires complete saved-map reconstruction, existing result reproduction,
zero unexplained reconciliation differences, explicit missing-data fields,
and stable parents. D1 ends without recommending a specific beam as proven
necessary. GC2 remains reserved for fresh-engineering-state qualification;
a geometry-aware development successor is GA1, not GC2.
