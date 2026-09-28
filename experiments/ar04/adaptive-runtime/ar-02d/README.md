# AR-02D — Generic source-conditioning null

Status: frozen diagnostic; no runtime/controller change. Engineering-only,
toy-scale, and not a general optimizer claim.

## Question

Is the source-conditioned continuation interaction seen for a runtime-selected
initial program stronger than the same effect for a pair of non-selected,
immediate-utility-matched programs on the same parameter block?

For any ordered pair of first programs `(A, B)`, define
`Delta(P) = L_96(A, P) - L_96(B, P)`, where `P` is a frozen 63-commit
continuation generated from a source state. The source interaction is
`I = Delta(P_A) - Delta(P_B)`. Negative `I` means the path generated from A
shifts the relative outcome toward A compared with the path generated from B;
it does not require A to have lower loss under either path.

The primary comparison is selected/control `(G, C1)` versus non-selected
control/control `(C1, C2)`. Both pairs use the same coordinates and are matched
on full-training immediate utility, utility stratum, and action displacement.

## Frozen protocol

- Use the byte-identical 96-train/48-validation Gaussian-cell dataset from
  `ar-02b-r1/artifacts/gaussian-cells.bin`; the runtime reads training samples
  only. Validation samples do not influence matching, path generation, or
  replay.
- Recreate the frozen cell-weighted P16/V48 K2 snapshots at commits 600, 2400,
  and 4200 for the nine AR-02B-R1 evidence-stream seeds. These share the
  inherited deterministic initialization; they are stream seeds, not
  initialization-seed replications.
- For each selected width-2 program G, reuse the existing full-7x7
  same-block search and strict `5e-5` full-training-utility/stratum matches to
  obtain up to two controls. Select C2 from the same legal 7x7 block, excluding
  G and C1, and require all three utilities to share a stratum and every
  pairwise utility gap to be at most `5e-5`.
- **D1 exact-vector (primary):** require the parameter-action vector
  `G - C1` to equal `C1 - C2` componentwise in integer units of the frozen
  `0.005` action step. No tolerance is used for this equality.
- **D2 magnitude-only (secondary, never pooled with D1):** require a
  nonidentical displacement vector and Euclidean displacement-magnitude error
  no greater than one primitive action unit (`0.005`). It uses the same strict
  utility matching. D2 is a separate fallback domain, not a relaxation of D1.
- Matching is deterministic and frozen before continuations are generated.
  Missing matches remain explicit in the receipts; tolerances are not widened
  after observing outcomes. Duplicate unordered C1/C2 comparisons within a
  domain/checkpoint are recorded but evaluated once.
- Generate `P_G`, `P_C1`, `P_C2`, and the common-ancestor `P_0`. For every path,
  the first future commit is exactly `snapshot + 1`; all use the same evidence
  stream seed and scheduler phase. `P_0` starts at the common pre-action state
  but consumes the same first-decision slot by starting at that same global
  commit clock.
- Freeze each generated path and replay it open-loop into both states in its
  pair. No clamping, replacement, or branch-specific replanning is allowed.
  Bounds-invalid replays are retained as censored receipts and excluded from
  complete-case summaries.
- Primary outputs are seed-level first, then pooled: path divergence
  probability `p_div`, unconditional `E[I]` over complete cases, and
  `E[I | divergent]`. Identical future action vectors contribute their exact
  zero interaction to `E[I]`. Report G/C1 and C1/C2 separately for D1 and D2.
- Also report the three source-specific relative gaps `Delta(P_A)`,
  `Delta(P_0)`, `Delta(P_B)`, and the fraction with strict ordering
  `Delta(P_A) < Delta(P_0) < Delta(P_B)`. Path-distance measures are diagnostic
  only and are not matching variables or primary-estimand conditions.
- Validate each path's telescoping loss identity and the difference-in-
  differences identity to `2e-6`; track parameter-separation drift. Keep all
  censored rows and matching misses.

## Outputs

Each uniquely named run directory contains:

- `ar-02d-report.json`: run counts and integrity maxima.
- `ar-02d-matches.csv`: D1/D2 matches, miss reasons, utility gaps, displacement
  residuals, and duplicate control/control receipts.
- `ar-02d-paths.csv`: all source-generated action rows with the global commit
  index, including censoring markers.
- `ar-02d-crossovers.csv`: per-pair/per-horizon source gaps, interaction,
  divergence, and path diagnostics.
- `ar-02d-checkpoints.csv`: frozen training checkpoint identity.
- `ar-02d-seeds.csv`: each stream seed's domain/pair-kind summary, followed by
  pooled descriptive rows.
- `ar-02d-paired.csv`: paired G/C1 versus C1/C2 comparisons matched by seed,
  checkpoint, domain, and control slot; duplicate control/control pairs without
  a unique evaluated counterpart are excluded from this paired contrast.

The decision rule is descriptive. Similar G/C1 and C1/C2 source interactions
support generic state-conditioned continuation compatibility. A stronger
G/C1 effect after exact displacement matching is evidence for selected-state
excess compatibility. If the seed-level direction is unstable or D1 match
coverage is inadequate, genericity remains unresolved. No post-hoc rescue
interpretation is allowed.

## Results — frozen nine-stream run

Dataset SHA-256: `A83D5DCCE8BD8926CF1D548C58D4A9CBBEF0CA97C72E1FD4331BC5D825A7A14A`,
matching AR-02B-R1. The run reconstructed all 27 checkpoints and found 34
strict selected/control matches. D1 produced 13 exact-vector triplets; D2
produced 23 magnitude-only triplets, of which two repeated unordered C1/C2
pairs were recorded but not counted twice in the control/control comparison.
All evaluated horizon-64 replays completed: 13 G/C1 and 13 C1/C2 in D1; 23
G/C1 and 21 unique C1/C2 in D2. There were no invalid source paths, no invalid
replays, and no incomplete horizon-64 rows. Telescoping and source-identity
residuals were zero; maximum parameter-distance drift was `7.45e-9`.

Seed-level paired means are shown before the pooled rows. `I_GC` and `I_CC`
are mean source interactions for the selected/control and control/control
pairs, respectively; `difference` is `I_GC - I_CC`. `n` counts complete
same-slot paired comparisons, not independent training initializations.

| Evidence stream | D1 n | D1 I_GC | D1 I_CC | D1 difference | D2 n | D2 I_GC | D2 I_CC | D2 difference |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `9f4a7c15d6e8b301` | 1 | `-1.976e-5` | `+1.618e-5` | `-3.594e-5` | 3 | `-2.944e-4` | `-2.159e-4` | `-7.852e-5` |
| `c3a5c85c97cb3127` | 3 | `-1.729e-6` | `+1.371e-6` | `-3.099e-6` | 3 | `0` | `-4.431e-6` | `+4.431e-6` |
| `b492b66fbe98f273` | 3 | `-4.242e-6` | `+1.490e-7` | `-4.391e-6` | 4 | `-3.181e-6` | `-5.215e-8` | `-3.129e-6` |
| `6a09e667f3bcc909` | 1 | `0` | `-1.669e-6` | `+1.669e-6` | 1 | `0` | `+2.563e-6` | `-2.563e-6` |
| `bb67ae8584caa73b` | 1 | `+2.712e-5` | `-1.788e-7` | `+2.730e-5` | 3 | `-2.937e-5` | `-7.512e-5` | `+4.576e-5` |
| `3c6ef372fe94f82b` | 2 | `0` | `0` | `0` | 3 | `-5.265e-7` | `-1.758e-6` | `+1.232e-6` |
| `a54ff53a5f1d36f1` | 2 | `0` | `0` | `0` | 2 | `0` | `0` | `0` |
| `510e527fade682d1` | 0 | — | — | — | 0 | — | — | — |
| `1f83d9abfb41bd6b` | 0 | — | — | — | 2 | `-9.323e-4` | `-9.224e-6` | `-9.231e-4` |
| **Pooled** | **13** | **`-8.115e-7`** | **`+1.453e-6`** | **`-2.265e-6`** | **21** | **`-1.357e-4`** | **`-4.322e-5`** | **`-9.250e-5`** |

For primary D1, the pooled paired difference is small and heterogeneous: G/C1
is more negative in 4 comparisons, C1/C2 in 2, and 7 are ties. Only 13 exact
matches exist across 7 streams; active-path means also point in opposite
directions (`-2.110e-6` for G/C1, `+3.149e-6` for C1/C2). This does not
establish either a generic negative source effect or selected-state excess
compatibility.

D2 has negative pooled means for both pair kinds, but its selected-state
excess is not stable: among 21 paired comparisons G/C1 is more negative in 7,
C1/C2 in 6, and 8 tie. The paired mean difference is heavily influenced by
the `1f83...` stream; seed-level differences have mixed signs. D2 is secondary
and cannot rescue the sparse, mixed D1 result. The common-ancestor path also
rarely lies strictly between the two source paths (1/13 D1 G/C1; 1/23 D2
G/C1), so the proposed monotonic three-path ordering did not emerge.

Paired divergence rates were `0.385/0.462` (G/C1, C1/C2) in D1 and
`0.524/0.571` in D2. There is no large divergence-rate gap in the paired
samples; the interaction estimates themselves remain seed-heterogeneous.

**Conclusion:** the frozen run does not resolve the genericity null. It shows
some source-conditioned interaction in the magnitude-only domain, but exact
translated-displacement coverage is too sparse and its seed-level direction
is heterogeneous. Do not promote selected-state excess compatibility. The
paired summary is `artifacts/run-1789954757/ar-02d-paired.csv`; its rows are a
deterministic post-run aggregation of the saved horizon-64 crossover receipt.

## Build and run

Build artifacts target `D:\adaptive-runtime-targets\ar-02d` (`:G` in the
workspace convention). From the repository root:

```powershell
$env:CARGO_TARGET_DIR = 'D:\adaptive-runtime-targets\ar-02d'
cargo test --manifest-path experiments\adaptive-runtime\ar-02b\Cargo.toml --release ar02d --lib
cargo run --manifest-path experiments\adaptive-runtime\ar-02d\Cargo.toml --release
```
