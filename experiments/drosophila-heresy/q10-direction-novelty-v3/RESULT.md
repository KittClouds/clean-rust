# Q10-DN3 result

Status: `Q10_DN3_STAGE2A_VALID__STABLE_ACTIVE_ROW_SVD`

DN3 is the corrected numerical qualification after DN2 failed its post-run
Gram audit. It completed all 8 engineering bundles and 32 predeclared events.
The independent reviewer returned `VERIFIED`, and an independent aggregate
check found zero rank-bound violations and zero cumulative-curve violations.
No scientific seed bundle, behavioral endpoint, repair coefficient, or DH-08B
authorization was opened.

DN3 factors each cumulative multi-step effect matrix directly in active-row
space with f64 SVD. It restores the frozen parent constructor key
`seed ^ tau_bits ^ trial` and applies a conservative one-million relative
singular-value cutoff fixed before execution.

| step limit | median R(k) | median rank | median active rows |
|-----------:|------------:|------------:|-------------------:|
| 1 | 0.635838 | 424.5 | 437.0 |
| 2 | 0.401775 | 576.0 | 583.5 |
| 4 | 0.179423 | 649.0 | 652.0 |
| 8 | 0.055604 | 675.0 | 677.0 |
| 16 | 5.79e-15 | 679.0 | 681.5 |

At 16 steps, 29 of 32 events had residual ratio at most `1e-6`; the maximum
was `0.0391`. Multi-step authority expanded from a median 437 one-step rows to
681.5 rows, with a median 245 newly authorized rows. These are valid diagnostic
span results: multi-ULP committed moves add structured readout directions and
usually cover the one-step residual under the frozen factorization contract.

This still does not prove that a monotone per-coordinate repair path can realize
the relaxed span coefficients. The direct SVD qualification took 2,552 seconds
with one analysis thread and an observed peak working set of about 481 MB. The
next justified step is a compressed multi-step repair-feasibility qualification
that preserves the validated factorization and avoids rerunning the full SVD
bank for every search candidate. Do not open DH-08B or infer a behavioral
direction effect from DN3.
