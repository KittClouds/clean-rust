# Q10-SM Result: Safety-Margined Bounded Geometry Qualification

Status: `Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT`

Q10-SM completed its qualification-only Stage 1 under the frozen 32-ULP binary32 reserve. It used 5,120 fresh engineering states across seeds `9401..9405`, with zero scientific seed bundles and no behavioral inference.

## Coverage and review

| Stage | New states | Safe nonidentity | Safety-margin dominated | Independent review |
| --- | ---: | ---: | ---: | --- |
| Stage 1A | 1,024 | 1,003 | 21 | `VERIFIED` by standard-library f32 replay |
| Stage 1B | 4,096 | 4,023 | 73 | `VERIFIED` by standard-library f32 replay |
| Cumulative | 5,120 | 5,026 | 94 | complete |

The two independent stage receipts are `qualification/stage1-a-9401/reviewer-receipt.json` and `qualification/stage1-b-9402-9405/reviewer-receipt.json`. The first pre-fix Stage 1A output is retained under `qualification/stage1-a-9401-quarantined-status-token`; it was rejected for a receipt-token mismatch before the successful rerun and contributed no accepted result.

## Geometry

Among the 5,026 accepted endpoints:

- residual cosine `abs(cos(z_N, z_T))`: min `0.9980241683`, median `0.9999926047`, max `0.9999999899`;
- path rotation angle: min `0.0001418625`, median `0.0038458447` rad, max `0.0628726126` rad;
- continuous safety surplus: median `2.4196626e-12` in absolute weight units;
- accepted committed coordinates retained at least 32 legal `nextafter32` moves toward each bound, as required by the frozen receipt gate.

The accepted endpoint family is therefore nonempty but locally thin. Q10-SM does not search disconnected global feasible regions and does not set a future direction-cosine threshold.

## Integrity

Across all event receipts, the maximum continuous errors were:

| Check | Maximum |
| --- | ---: |
| cue-by-MBON drive error | `1.1102230246251565e-15` |
| acquisition-axis displacement error | `1.071365218763276e-14` |
| null annihilation error | `2.2822022049950874e-14` |
| total-norm error | `5.0182083057607076e-14` |
| reconstruction error | `0` |
| committed f32 safety violations | `0` |
| committed f32 lower/upper boundary differences | `0` |

Q08, Q09, and Q10-BG lineage hashes remained unchanged. The isolated binary was built through the Q10-SM D: target junction. Rust tests, Clippy with `-D warnings`, formatting, and release build passed before measurement.

## Scope boundary

Stage 1 performed only continuous linear-contract qualification plus diagnostic f32 storage and safety-capacity checks. Sequential learner-order f32 readout equality, readout ULP error, repair-capacity analysis, ULP repair, behavior, and DH-08B remain `NOT_RUN`. This result establishes safety-margined endpoint existence and its narrow geometry; it does not establish a direction effect or a behavioral effect.

The reproducible aggregate is in `Q10-SM-SUMMARY.json`.
