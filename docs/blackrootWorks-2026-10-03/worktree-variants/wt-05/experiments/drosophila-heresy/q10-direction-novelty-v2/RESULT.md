# Q10-DN2 result

Status: `Q10_DN2_INVALID__NUMERICAL_SPAN_AUDIT_FAILED`

DN2 completed all 8 engineering bundles and 32 predeclared events. The
independent standard-library reviewer returned `VERIFIED` for hashes, coverage,
finite fields, and the firewall. A post-execution numerical audit then failed
the scientific span claim. No scientific seed bundle, behavioral endpoint,
repair coefficient, or DH-08B authorization was opened.

The provisional Gram curves were:

| step limit | median R(k) |
|-----------:|------------:|
| 1 | 0.453233 |
| 2 | 0.291210 |
| 4 | 0.148804 |
| 8 | 0.058997 |
| 16 | 5.96e-15 |

Those curves cannot be interpreted. Every event reported one-step rank above
one-step row authority, with median excess rank `147.5`, and cumulative curves
were nonmonotone in rank or residual. The Gram eigensolver threshold admitted
roundoff modes, so the reported residual coverage is invalid.

One diagnostic survives the failure: one-step authority covered a median of
432.5 readout rows, while 16-step moves covered 685.0 and newly authorized a
median 253.0 rows (range 209--300). That establishes new row support, but not
coverage of the SR4 unreachable error.

DN2 is closed as invalid for the span conclusion. The independent reviewer did
not check rank bounds, nested-span invariants, or an independent projection, so
its `VERIFIED` receipt does not rescue the numerical claim. The trial key also
omitted `snapshot.trial` from the constructor analysis seed; DN3 restores that
frozen parent rule.

The next justified step is fresh Q10-DN3: direct active-row QR/SVD or stable
streaming orthogonalization, explicit rank and nested-span invariants, an
independent projection audit, and the restored trial-key rule. Do not start
repair feasibility, DH-08B, or infer a behavioral direction effect from DN2.
