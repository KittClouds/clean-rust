# AR-04E — Verifier Size, Reuse, and Refresh Cadence

AR-04E is a fresh engineering research identity descended from sealed AR-04D.
It asks whether the AR-04D exposure result is primarily controlled by
per-decision verifier size, panel reuse, or refresh cadence.

## Frozen protocol

- parent commit: `0055876c`
- branch: `codex/ar-04e-verifier-size-reuse-20260926`
- crossed design: 5 datasets × 5 initializations
- runtime: 4,200 steps, 4,200 commits, P16 proposal stream
- primary endpoint: untouched final V96 loss
- secondary endpoint: untouched 4,096-example population reference
- calibration descriptors: accuracy, fixed-bin ECE, Brier, correct/wrong NLL,
  and wrong-case confidence
- no controller tuning, Taylor approximation, adaptive refresh, noise
  injection, or Phoenix change

## Six size × reuse arms

| arm | verifier size | exposure | scored examples |
| --- | ---: | --- | ---: |
| `fixed_v128` | 128 | one fixed panel | 134,400 |
| `fresh_v128` | 128 | new panel every 4 commits | 134,400 |
| `fixed_v512` | 512 | one fixed panel | 537,600 |
| `fresh_v512` | 512 | new panel every 4 commits | 537,600 |
| `fixed_v2048` | 2,048 | one fixed panel | 2,150,400 |
| `fresh_v2048` | 2,048 | new panel every 4 commits | 2,150,400 |

## Three matched-work cadence arms

| arm | verifier size | refresh interval | scored examples |
| --- | ---: | ---: | ---: |
| `fresh_v512_cadence16` | 512 | every 16 commits | 134,656 |
| `fresh_v2048_cadence64` | 2,048 | every 64 commits | 135,168 |

The final observation covers the remaining partial interval without changing
panel size. Thus every arm executes exactly 4,200 commits. Scored-example
totals are approximately compute matched, not exactly equal.

## Predeclared interpretation

For each verifier size, reuse damage is:

`D(V) = final_loss(fixed V) - final_loss(fresh V)`.

- `D(V) > 0`: reuse damage
- `D(V) ≈ 0`: reuse-neutral
- `D(V) < 0`: fixed-support advantage

The cadence arms test precision versus staleness at approximately equal total
scoring work. Loss and accuracy/calibration disagreement is retained as an
outcome rather than resolved by selecting a preferred endpoint.

## Boundary

AR-04E is descriptive and diagnostic. It does not authorize runtime promotion
or Phoenix changes. Taylor scoring becomes eligible only if larger verifier
panels demonstrate reproducible benefit at a defensible compute frontier.
