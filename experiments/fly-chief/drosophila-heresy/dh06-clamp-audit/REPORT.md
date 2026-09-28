# DH-06 post hoc bounded-geometry implementation audit

This is a non-inferential replay of the frozen DH-06 measured seeds. It adds no
samples, confidence intervals, endpoints, or behavioral claims.

The audit replayed all 512 E-arm causal runs: 32 seeds, both slices, both taus,
and four factorial cells, totaling 131,072 reversal events. Archived behavioral
outputs matched exactly after enabling round-trip f64 JSON parsing. Capture-on
and capture-off final weights and curves also matched exactly.

## Corrected interpretation

DH-06 separated pre-clamp acquisition-aligned and support-masked orthogonal
components. Final bounded storage could add acquisition-axis displacement. The
behavioral contrasts are unchanged; exact delivered orthogonality was not
established by the original intervention.

On the right inferential slice:

| Cell | events with combined-candidate clipping | mean cumulative signed clamp correction in acquisition-coordinate units | mean cumulative absolute correction |
|---|---:|---:|---:|
| Neither | 0.00% | 0 | 0 |
| Parallel only | 54.55% | -0.000338 | 0.000455 |
| Perpendicular only | 99.95% | -0.004774 | 0.006103 |
| Both | 0.00% | 0 | 0 |

The left descriptive slice had the same shape: perpendicular-only clipping in
99.99% of events and mean cumulative signed correction -0.005024.

For `both`, the ordinary retained endpoint is already bounded. A separately
computed common-base clamp term and incremental component term cancel in the
combined endpoint (right means +0.000115 and -0.000115; left +0.000247 and
-0.000247). The final combined candidate therefore needed no further clamp.

The perpendicular-only clamp correction is measurable, not numerical dust. It
does not explain away DH-06's positive perpendicular factorial effect on final
acquisition coordinate: its cumulative signed direction is negative. These
quantities arise on adaptive trajectories and cannot be subtracted to infer a
counterfactual no-clipping behavior. The audit therefore narrows mechanism; it
does not estimate clipping's behavioral effect.

Machine-readable evidence:
`../q07-bounded-null-v1/artifacts/20260915T215754Z/clamp-summary.json`.
