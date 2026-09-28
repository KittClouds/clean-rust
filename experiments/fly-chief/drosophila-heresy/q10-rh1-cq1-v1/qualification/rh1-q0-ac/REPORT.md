# RH1-Q0 / RH1-AC qualification report

Qualification-only canonical-runtime fixture and authority-coverage audit.

Q0 status: `RH1_Q0_CANONICAL_RUNTIME_QUALIFIED_FIXTURE_ONLY`.
Q0 checks: `{"canonical_bytes_equal": true, "canonical_state_equal": true, "committed_bytes_equal": true, "geometry_metrics_equal": true, "sequential_f32_readout_equal": true, "state_identity_equal": true, "tie_hash_equal": true}`.
AC status: `RH1_AC_AUTHORITY_COVERAGE_AUDIT_COMPLETE`.
Groups: 84; endpoint-coordinate pairs: 2707.
Coverage tiers: `{"MEASURED_PARTIAL": 2707}`.
Ranking-feature completeness: `{"incomplete": 2707}`.
Authority arm ready under strict gate: `False`.
Unknown-coordinate fraction: 0.000000.
Row-authority coverage summary: `{"maximum": 0.9, "mean": 0.27857098879448344, "minimum": 0.1, "records_with_row_coverage": 2707}`.

Q0 uses a synthetic fixture for canonical commit and sequential-f32 invariance; it is not learner replay.
Partial prefix/row authority is not promoted to measured authority; the authority arm is gated pending a revised coverage-qualified identity.
RH1 measured factorial execution, scientific seeds, behavioral probes, and DH08B remain unstarted.
