# AR-04D — Sentinel Exposure Frontier

AR-04D is a fresh engineering research identity descended from the sealed
AR-04C sentinel-reuse result. It asks whether the closed-loop benefit of
independent objective evidence is controlled by unique support, rotation, or
spacing of exposure.

## Frozen protocol

- parent commit: `b932975cca2e792d325a92f53a60f4a41741c6fa`
- branch: `codex/ar-04d-sentinel-exposure-frontier-20260926`
- crossed design: 5 datasets × 5 initializations
- runtime: 4,200 steps, four commits per evidence round, P16 proposal stream
- verifier: exact V128 except the pooled K=16 arm, which uses V2048
- primary endpoint: untouched final V96 loss
- secondary endpoint: untouched 4,096-example population reference
- no controller tuning, Taylor approximation, adaptive refresh, or Phoenix change

The seven exposure arms are:

| arm | unique support | per-decision panel | schedule |
| --- | ---: | ---: | --- |
| `sentinel_k1` | 128 | 128 | one fixed panel |
| `sentinel_k4_cyclic` | 512 | 128 | cyclic |
| `sentinel_k16_cyclic` | 2,048 | 128 | cyclic |
| `sentinel_k16_blocked` | 2,048 | 128 | contiguous blocks |
| `sentinel_k16_pooled` | 2,048 | 2,048 | one pooled panel |
| `sentinel_k64_cyclic` | 8,192 | 128 | cyclic |
| `sentinel_fresh` | 134,400 | 128 | never reused |

The cyclic and blocked K=16 arms use the same 16 panels and exactly the same
per-panel exposure counts: panels 0–9 receive 66 evidence rounds and panels
10–15 receive 65. The blocked arm changes only the spacing of those exposures.

The master panel bank contains one deterministic V128 panel for every evidence
round and cell. Panels are shared across the arms within a cell. The pooled
arm concatenates panels 0–15, so its unique support is matched to K=16 cyclic
without sharing the same per-decision noise.

## Interpretation gates

The K=1 and fresh arms are a built-in replication of the AR-04C fixed and
rotating conditions. Their predeclared historical ordering is reported before
any exposure-curve interpretation. No result is promoted from a pooled mean.

- pooled ≈ cyclic and cyclic ≈ blocked: unique support is the leading account;
- cyclic > pooled: changing V128 evidence itself is protective;
- cyclic > blocked: spacing/consecutive adaptation matters;
- failure of the K=1/fresh historical check: report the replication failure
  separately and do not interpret intermediate arms as a smooth exposure law.

All action-ranking telemetry is secondary. The central outputs are terminal
held-out loss, population loss, operational-to-final gap, exact per-panel
decision/scored-candidate exposure counts, and cell-level contrasts.
