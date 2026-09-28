# AR-02C-TANH — smooth-activation path-source diagnostic

Status: opened after the AR-02B-R1 conditional active-path interaction had a negative seed-level mean in all eight seeds with any path divergence. This is a necessity test for the ReLU-gating explanation, not a new optimizer proposal.

## Question

Does the AR-02B-R1 path-source interaction persist when the hidden activation is smooth, holding the task and pairwise runtime fixed?

## Frozen protocol

- Use the byte-identical AR-02A-R2 Gaussian-cell dataset (96 train, 48 validation); validation is not read by training, matching, or the path audit.
- Use the opt-in `tanh` feature on the shared AR-02B runtime. The only algorithmic change is ReLU to `tanh` in the two hidden layers and the matching derivative `1 - activation^2` in backpropagation; the default feature set remains ReLU. Architecture, deterministic parameter initializer, cross-entropy objective, action grammar, bounds, K2 verifier, pair schedule, strict same-block `5e-5` matching, snapshot commits, 63-commit open-loop crossover, and output precision remain fixed. This directory contains only the experiment harness and its own receipts; it does not vendor a second copy of the runtime.
- Reuse the nine AR-02B-R1 stream seeds as paired stochastic evidence streams: `9f4a7c15d6e8b301`, `c3a5c85c97cb3127`, `b492b66fbe98f273`, `6a09e667f3bcc909`, `bb67ae8584caa73b`, `3c6ef372fe94f82b`, `a54ff53a5f1d36f1`, `510e527fade682d1`, `1f83d9abfb41bd6b`. The inherited initializer is deterministic and common; these are distinct proposal/verifier trajectory seeds, not random initialization seeds.
- Emit checkpoints at 600, 2,400, and 4,200 commits, up to two matched controls per snapshot, and compare `P_G` with `P_C` at horizon 64. Report divergence probability separately from `E[I | div]` and `E[I]`; list but exclude incomplete/bounds-censored crossovers from complete-case estimates.
- The finite-difference gradient test samples parameters from both hidden layers and the output layer. It lives beside the activation kernel and runs with `cargo test --features tanh`. The two frozen ReLU-checkpoint identity tests are intentionally excluded in that feature test command; no checkpoint values are rewritten to hide the activation change.

## Outputs

- `artifacts/ar-02c-tanh-report.json`, `*-matches.csv`, `*-crossovers.csv`, `*-paths.csv`, `*-checkpoints.csv`, and `*-seeds.csv`: inherited crossover receipts with a distinct experiment stem.
- `artifacts/ar-02c-tanh-divergence.csv` and `*-source-summary.csv`: per-comparison and seed-level path divergence/source interaction diagnostics.
- `artifacts/gaussian-cells.bin`: byte-identical dataset copy.

## Results

The paired release run completed nine stochastic evidence-stream seeds. The dataset SHA-256 is `A83D5DCCE8BD8926CF1D548C58D4A9CBBEF0CA97C72E1FD4331BC5D825A7A14A`, identical to AR-02B-R1. The initial isolated activation fork and the final feature-based harness produced byte-identical crossover artifacts. All 27 snapshots were reached. The strict match rule yielded 33 controls; two seeds (`9f4a7c15d6e8b301`, `3c6ef372fe94f82b`) had no matched controls at any snapshot, so 7/9 seeds contribute to the crossover. All 33 crossovers were complete; there were no bounds-invalid source or replay paths. Telescoping and source-identity residuals were zero at saved precision; maximum parameter-distance drift was `1.49e-8`.

| Seed | Complete | Divergent | `p_div` | `E[I | div]` | `E[I]` |
|---|---:|---:|---:|---:|---:|
| `9f4a7c15d6e8b301` | 0 | 0 | n/a | n/a | n/a |
| `c3a5c85c97cb3127` | 6 | 6 | 1.00 | `-1.7963e-4` | `-1.7963e-4` |
| `b492b66fbe98f273` | 3 | 3 | 1.00 | `-2.2650e-6` | `-2.2650e-6` |
| `6a09e667f3bcc909` | 4 | 3 | 0.75 | `-2.9802e-7` | `-2.2352e-7` |
| `bb67ae8584caa73b` | 4 | 4 | 1.00 | `-5.2407e-5` | `-5.2407e-5` |
| `3c6ef372fe94f82b` | 0 | 0 | n/a | n/a | n/a |
| `a54ff53a5f1d36f1` | 6 | 5 | 0.83 | `-8.0037e-5` | `-6.6698e-5` |
| `510e527fade682d1` | 4 | 3 | 0.75 | `-2.6401e-4` | `-1.9801e-4` |
| `1f83d9abfb41bd6b` | 6 | 6 | 1.00 | `-6.2982e-6` | `-6.2982e-6` |
| **Pooled** | **33** | **30** | **0.909** | **`-8.4170e-5`** | **`-7.6518e-5`** |

`I = Delta_G - Delta_C`. All seven seeds with both matched controls and at least one divergent path have a negative active mean; 25/30 individual active comparisons are negative and 5 positive. Thus the path-source interaction persists under smooth `tanh`; piecewise ReLU gating is not necessary for its occurrence in this substrate. The negative interaction does not mean the selected state wins: pooled loss gaps are `Delta_G = +3.9868e-5` and `Delta_C = +1.1639e-4`, so it is worse than the matched state on average under both paths, but less worse under its own-source path. The horizon-64 sign categories are selected better under both paths in 19, selected-only-under-`P_G` in 4, and control better under both in 10.

Across complete comparisons, future paths differ in 30/33 cases (`p_div=0.909`). Mean differing future programs are 8.06 over all complete comparisons (8.87 conditional on divergence); mean summed per-commit action-vector L1 is `0.4473` (`0.4920` conditional), and mean net cumulative displacement L1 is `0.3070` (`0.3377` conditional). The 7/9 seed coverage limit and sparse within-seed active counts constrain the portability claim. The smaller pooled active interaction than in AR-02B-R1 is not a matched effect-size estimate because two seeds have no controls here and the control sets differ.

## Interpretation limits

Persistence under `tanh` would show ReLU gating is not necessary for this measured path-source interaction. Attenuation would be consistent with a gating contribution but would not prove it, because changing activation also changes the learned states and selected programs. This remains a toy-scale path-source diagnostic with a shared deterministic initializer, sparse matched controls, and dependent snapshots; it is not an optimizer comparison or a general mechanism claim.

All claims are engineering-only, with no biological correspondence or general optimizer implication.

## Build

Release and test artifacts target `D:\adaptive-runtime-targets\ar-02c-tanh` (`:G` in the supplied workspace convention).
