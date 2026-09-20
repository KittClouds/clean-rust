# AR-02B-R1 — independent-seed path-source crossover

Status: diagnostic replication; no controller or training policy changes.

## Question

On the Gaussian-cell task, how often do same-block matched initial states generate different 63-commit continuations, and what is the source-conditioned loss interaction when they do?

The primary quantities are reported seed-by-seed before the pooled row:

`p_div = P(P_G != P_C)`, `E[I | P_G != P_C]`, and `E[I]`, where `I = Delta_G - Delta_C` at horizon 64. Identical action-vector sequences should have zero source interaction. Incomplete/bounds-censored crossovers are listed but excluded from these quantities.

## Frozen protocol

- Use the exact AR-02A-R2 Gaussian-cell dataset (96 train, 48 validation); validation is not read by the runtime or audit.
- Inherit the cell-weighted P16/V48 K2 runtime, action grammar, bounds, broad pair schedule, same-block full-7x7 control search, utility-stratum rule, and strict `5e-5` utility-match tolerance from AR-02B.
- Use the three frozen commit snapshots 600, 2,400, and 4,200, with up to two controls per snapshot and 63 future commits per source path.
- New stochastic stream seeds, frozen before execution and distinct from AR-02B's original three: `9f4a7c15d6e8b301`, `c3a5c85c97cb3127`, `b492b66fbe98f273`, `6a09e667f3bcc909`, `bb67ae8584caa73b`, `3c6ef372fe94f82b`, `a54ff53a5f1d36f1`, `510e527fade682d1`, `1f83d9abfb41bd6b`.
- The inherited model initializer is deterministic and common across seeds. Independent seeds vary the proposal/verifier streams and therefore the training trajectories; this is not an initialization-seed replication.
- For each matched comparison, generate `P_G` from the selected-state branch and `P_C` from the matched-control branch, then replay both paths open-loop into both initial states. Do not clamp or replace an invalid action.
- Compare actual parameter-indexed action vectors at each future commit. A commit is different when the dense action-vector L1 distance exceeds `1e-9`. Also report the sum of per-commit L1 distances and the L1 distance of the net cumulative displacement difference; these are different quantities and are not conflated.
- A comparison is complete only when both paths are valid through horizon 64 and all 63 future program rows are present. The h64 crossover receipt is authoritative for censoring; incomplete rows remain in the comparison output and are excluded from complete-case estimates.

## Outputs

- `artifacts/ar-02b-r1-report.json`, `*-matches.csv`, `*-crossovers.csv`, `*-paths.csv`, `*-checkpoints.csv`, and `*-seeds.csv`: inherited runtime receipts, under a distinct R1 stem.
- `artifacts/ar-02b-r1-divergence.csv`: per matched-control path divergence and horizon-64 source interaction.
- `artifacts/ar-02b-r1-source-summary.csv`: every frozen seed plus pooled `ALL`, including matched/complete/censored counts, `p_div`, active and overall source interaction, and both all-comparison and divergence-conditional path-distance summaries.
- `artifacts/gaussian-cells.bin`: byte-identical dataset copy.

## Results

The release run completed all nine frozen seeds. Dataset SHA-256 is `A83D5DCCE8BD8926CF1D548C58D4A9CBBEF0CA97C72E1FD4331BC5D825A7A14A`, matching AR-02A/R1/R2. All 27 checkpoints were emitted; every seed reached commits 600, 2,400, and 4,200. There were 34 strict same-block matches, 33 complete horizon-64 crossovers, and one bounds-censored replay. No source path was invalid at generation. The runtime's telescoping and source-identity residuals were zero at saved precision; maximum parameter-distance drift was `7.45e-9`.

| Seed | Complete | Divergent | `p_div` | `E[I | div]` | `E[I]` |
|---|---:|---:|---:|---:|---:|
| `9f4a7c15d6e8b301` | 4 | 4 | 1.00 | `-2.2574e-4` | `-2.2574e-4` |
| `c3a5c85c97cb3127` | 4 | 1 | 0.25 | `-5.1856e-6` | `-1.2964e-6` |
| `b492b66fbe98f273` | 4 | 2 | 0.50 | `-6.3628e-6` | `-3.1814e-6` |
| `6a09e667f3bcc909` | 4 | 3 | 0.75 | `-2.0528e-4` | `-1.5396e-4` |
| `bb67ae8584caa73b` | 4 | 4 | 1.00 | `-1.1951e-5` | `-1.1951e-5` |
| `3c6ef372fe94f82b` | 4 | 2 | 0.50 | `-1.0043e-5` | `-5.0217e-6` |
| `a54ff53a5f1d36f1` | 2 | 0 | 0.00 | n/a | `0` |
| `510e527fade682d1` | 3 | 3 | 1.00 | `-2.3476e-4` | `-2.3476e-4` |
| `1f83d9abfb41bd6b` | 4 | 4 | 1.00 | `-6.6090e-4` | `-6.6090e-4` |
| **Pooled** | **33** | **23** | **0.697** | **`-2.1532e-4`** | **`-1.5007e-4`** |

Here `I = Delta_G - Delta_C`; negative values mean the selected initial state is relatively less disadvantaged under its own generated path than under the control-generated path. The decomposition holds: pooled `E[I] = p_div × E[I | div]` to output precision because identical paths have zero interaction. Eight seeds had at least one divergent path, and all eight seed-level active means were negative. At the individual comparison level, 16 of 23 active interactions were negative and 7 positive. One seed had no divergent paths. This is directionally repeatable across independent stochastic evidence streams, but active counts per seed are only 1–4 and comparisons within a seed share checkpoints and paths.

Across all 33 complete comparisons, mean loss gaps were `Delta_G = -2.0945e-4` and `Delta_C = -5.9371e-5`, so the selected state was better on average under both path sources; this is not a pure own-path-win pattern. The 64-h sign categories were selected better under both paths in 16, selected-only-under-`P_G` in 2, control better under both in 9, and mixed/tied in 6.

The future action sequences differed in 23/33 complete comparisons. Across all complete comparisons, the mean number of differing future programs was 9.24 (13.26 conditional on divergence); mean summed per-commit action-vector L1 distance was `0.5553` (`0.7967` conditional), while mean net cumulative displacement L1 was `0.3295` (`0.4728` conditional). These are separate path-distance measures; the net value permits cancellation across commits.

### Interpretation and gate

This is stronger than the original three-seed AR-02B readout: the **conditional active-path interaction has a consistent negative seed-level mean in 8/8 seeds with any path divergence**, with 23 active comparisons total. The effect is not universal at the comparison level, and the selected-state advantage under both path sources cautions against describing it as a general source-alignment win. The result supports opening the smooth-activation diagnostic as a test of necessity, not a general optimization claim. The shared deterministic initializer, sparse strict matches, one censored comparison, and small per-seed active counts remain important limits.

## Interpretation limits

This is a path-source crossover, not an optimizer comparison. The seeds share the inherited deterministic initialization and differ in stochastic evidence streams. Comparisons within a seed are dependent snapshots/controls; seeds, not individual path pairs, are the more defensible replication units. The pooled decomposition is descriptive. The active interaction is a bounded replicated signal on this substrate, not proof of a universal mechanism.

All results are engineering-only, toy-scale, and have no biological correspondence or general optimizer implication.

## Build

Release and test artifacts target `D:\adaptive-runtime-targets\ar-02b-r1` (`:G` in the supplied workspace convention).
