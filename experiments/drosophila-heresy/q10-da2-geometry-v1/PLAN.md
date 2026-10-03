# Q10-DA2 geometry-constrained distributed additive qualification

Q10-DA1 established target-readout authority in large support-disjoint
coalitions, but its independently optimized coordinate choices drifted along
the acquisition axis. Q10-DA2 asks whether the same distributed vocabulary
can satisfy the frozen Q10-SM linear geometry contract at the committed f32
endpoint.

This is an engineering qualification only. It replays the eight sealed DA1
engineering fixtures and uses the four fixed DA1 support coalitions per event.
No scientific seed bundle, behavioral endpoint, or DH08B path is opened.

For each selected coordinate, the legal endpoint vocabulary is
`0, +/-1, +/-2, +/-4, +/-8, +/-16` ULP steps with the inherited 16-ULP
reserve. The selector starts from the local mismatch-first choice used by
DA1, then searches deterministic one- and two-coordinate replacements. A
replacement is scored by exact committed f32 replay and must be audited from
the final weight bytes.

The frozen geometry gates are:

* acquisition-axis normalized error <= 2e-6;
* displacement-norm normalized error <= 2e-7;
* linear cue-drive normalized error <= 2e-6;
* no support, boundary, bound, or reserve violation;
* maximum coordinate movement <= 16 ULP.

The legacy total path-length <=64 check remains diagnostic only. Sequential
readout parity and target-readout mismatch are reported separately. A set is
called a valid DA2 endpoint only if all geometry gates pass; no behavioral
interpretation follows from this qualification.

The two-coordinate search is not presented as an exhaustive solver. If the
declared selector cannot find a valid endpoint, the protocol records a
selector failure rather than widening the search after seeing the results.
