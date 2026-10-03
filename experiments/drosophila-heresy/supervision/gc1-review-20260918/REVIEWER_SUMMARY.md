# Drosophila Heresy: GC1 global constructor review

Prepared 18 September 2026. Post hoc review of Q10-GC1-PAR8 and PAR8-AUDIT1.

**The bounded global constructor produced reproducible partial repairs, but no exact alternative endpoint.** All 14 selected outputs satisfy the declared final numerical geometry gates, improve their baseline global score, and differ in committed weights from both baseline and target. The central construction milestone—different weights with exactly matching target sequential-f32 readout—remains unmet.

The question was whether qualified local candidate palettes could be assembled into a global endpoint satisfying the inherited geometry contract. The input library contained 801 groups and 7,207 palette entries, including 801 ZERO options. The parent reports 800 complete palettes and one preserved shortfall. Its physical-support union covers the baseline mismatch sets; coverage alone does not establish repair feasibility.

PAR8 searched all 801 group rounds across 14 endpoint/set cases, using a maximum beam of 48 (32 exploit, up to 16 explore), exact sequential-f32 readout, and full geometry recomputation for each evaluated candidate. The 323,648 evaluation calls include repeated states/ZERO choices; they are not a count of unique weight configurations. This was a bounded heuristic search, not exhaustive enumeration.

## Verified results

| Quantity | Result |
|---|---:|
| Endpoint/set cases completed | 14/14 |
| Exact global targets | 0/14 |
| Geometry-valid outputs strictly improving baseline | 14/14 |
| Saved selected outputs reconstructed successfully | 14/14 |
| Saved best-search diagnostics also reconstructed | 14/14 |
| Aggregate baseline mismatches | 3,386 |
| Aggregate selected-output mismatches | 2,454 |
| Net mismatch reduction | 932 (27.53%) |
| Initially mismatched rows repaired | 1,050 |
| Previously exact rows newly mismatched | 118 |
| Selected valid mismatch range | 124–222 |
| Saved best-search states failing final geometry | 8/14 |

These sums count rows across endpoint/set cases and are descriptive, not independent observations. All cases use engineering seed **9731**, across four slice/tau endpoint files and 14 set indices. This does not estimate generalization to fresh seeds, specimens, or biological systems.

The best selected valid output is R/tau4, set 3: **215 → 124 mismatches**, with total ULP distance 165. Its 123-mismatch best-search alternative fails final geometry and is not an admissible output.

## What the audit changed

The earlier statement that geometry is “the current bottleneck” was too strong. Eight saved search states fail geometry, with diagnostic gaps of 1–82 mismatches relative to their valid selections. Seven fail the acquisition-axis gate, four fail the linear-drive gate, and three fail both; none fails the norm gate. These are comparisons between saved candidates, not estimates of the causal benefit of removing a constraint.

Even the saved search states that fail geometry retain substantial readout error: best-search mismatch counts range from 123 to 169 across all cases. Geometry balancing therefore deserves investigation alongside palette limitations, contextual collateral damage, and finite search diversity. The results do not identify a unique limiting mechanism.

Collateral must accompany the headline: 1,050 original errors were repaired, but 118 exact rows were disturbed. The reported 932 reduction is the net effect.

## Verification and limitations

Current plan/contract/runner/parent hashes and status-to-artifact hashes match. A fresh reviewer script rebuilt all 28 saved maps from frozen baseline bits and palette choices; independently implemented prefix application, sequential f32 accumulation, global scoring, and numerical geometry reproduced the stored hashes and values. It additionally checked permitted coordinates, bounds, boundary membership, the inherited 16-step prefix reserve, map completeness, candidate distinctness, and strict baseline improvement for selected valid outputs. Parent files remained unchanged.

This verification reuses the frozen state loader and candidate-identity routine. It is stronger than simply rerunning the existing score helper, but it is not an independent simulator, cross-language validation, or replay of the entire historical search. AUDIT1 itself shares PF5 readout/geometry routines with PAR8; its “independent” label means independent reconstruction, not implementation independence.

Code review found reusable success-classification gaps: the exact-success branch does not explicitly require weights to differ from the target; the fallback labels every non-exact result partial without explicitly testing strict improvement and validity. The current saved results pass those omitted conditions in this review. A successor constructor should encode them before execution.

## Decision for the reviewer

The result is suitable to review as **verified partial engineering construction**, with the limitations above. It does not establish exact construction, impossibility, adaptive-state differences, future-learning divergence, or a biological mechanism. Fresh constructor qualification (GC2), adaptive-geometry comparison (AG1), and behavior remain gated.

The narrow next diagnostic should explain the rejected search states' signed axis/linear-drive errors and the 118 collateral rows, while preserving the palette/search-capacity alternative. Any revised search needs a new frozen identity; no gates should be loosened retrospectively.

Supporting files in this packet: [detailed audit](AUDIT.md), [machine-readable verification](evidence.json), and [verification script](verify_review.py). The detailed audit identifies authoritative source files and remaining code-level qualifications.
