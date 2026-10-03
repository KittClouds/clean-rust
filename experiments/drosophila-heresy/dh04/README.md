# Drosophila Heresy — DH-04

**The prespecified partial-erasure mechanism passed all four required tests in
this synthetic model.**

Retaining distractor-generated eligibility rather than suppressing it improved
the same-RNG reversed probe by **+6.673 percentage points**, paired 95% interval
**[+5.754, +7.666]**. It shifted final weights by **-0.179** along the acquisition
axis relative to suppression, interval **[-0.193, -0.165]**. Yet retained weights
stopped at coordinate **0.654**, interval **[0.638, 0.672]**, where initial
weights are 0 and acquired weights are 1. Their deterministic old-map margin
remained positive at **+0.0218**, interval **[+0.0193, +0.0243]**.

The behavioral picture is equally direct: eligibility retention improved the
reversed probe from 31.52% to 38.19%, but the old-map probe still won 61.81%.
Immediate reversal crossed to a negative old-map margin and reached 54.05% on
the reversed probe. The distractor trace therefore weakened the stale
association without acquiring the reversed solution.

- [Frozen measured report](artifacts/runs/20260912T044912Z/REPORT.md)
- [Prespecified protocol](PROTOCOL.md)
- [Run seal](artifacts/runs/20260912T044912Z/seal.json)
- [Completion and output hashes](artifacts/runs/20260912T044912Z/completion.json)
- [Independent real-slice replay](artifacts/verification/20260912T044912Z/verification.json)
- [Result figure](artifacts/figures/20260912T044912Z/dh04-results.png)

## Design

All four conditions shared 256 immediate-reward acquisition trials. During
reversal, the two causal cells processed identical twelve-distractor intervals
and consumed identical RNG streams. Both restored all post-cue non-eligibility
state after each interval. One retained distractor-generated eligibility; the
other restored the trace to its post-cue snapshot while preserving cue-trace
decay and elapsed time.

| Right-slice E condition | Old-map probe | Reversed probe | Acquisition-axis q | Old-map margin |
| --- | ---: | ---: | ---: | ---: |
| Immediate | 45.95% | 54.05% | 0.580 | -0.0066 |
| Quiet | 68.20% | 31.80% | 0.655 | +0.0350 |
| Eligibility retained | 61.81% | 38.19% | 0.654 | +0.0218 |
| Eligibility suppressed | 68.48% | 31.52% | 0.833 | +0.0335 |

The retained-minus-suppressed weight contribution had cosine 0.156 with the
successful immediate-reversal delta. Retained weights also ended farther from
the immediate solution than suppressed weights. These reference comparisons
were prespecified as descriptive because successful reversal itself includes
some erasure.

## Scope and integrity

The sealed run contains 768 arm runs and 393,216 computed training trials: 24
fresh seed bundles, two eligibility constants, two related soma-side slices,
four conditions, and learning/fixed-weight arms. The mechanism classification
uses only right-slice E results with taus averaged inside each seed.

Before execution, 31 Rust tests, four Python analysis tests, release Clippy with
warnings denied, the locked offline build, lineage verification, and an explicit
zero-allocation geometry benchmark passed. Execution with diagnostics took
12.877 seconds on four workers; process peak working set was 20,545,536 bytes.
The seal covers 34 frozen files and completion hashes cover all ten outputs.

The post-run real-slice replay matched every recorded non-timing output across
all four conditions and both arms with observers enabled and removed. It added
no scientific samples. DH-01, DH-02, and DH-03 were reverified unchanged.

## Limits

This is model-coordinate evidence from one specimen and synthetic dynamics.
Weight geometry is not a unique decomposition: clipping, bounded positive
weights, sparse overlap, and nonlinear readout can separate geometric and
behavioral effects. The experiment establishes partial erasure under this
intervention; it does not establish a biological forgetting mechanism.

No backpropagation, learning-rule search, endpoint change, extra seed, parameter
rescue, or post-outcome tuning was used.

## Reproduce

The local target directory points to D:\drosophila-heresy\dh04-target. The
launcher seals a fresh run before execution and verifies all three parents.

~~~powershell
$dh04Python = 'C:\Users\shuga\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
Set-Location 'C:\code land\clean-rust\experiments\drosophila-heresy\dh04'
$env:CARGO_TARGET_DIR = 'D:\drosophila-heresy\dh04-target'
cargo test --release --locked --offline
cargo clippy --release --locked --offline --all-targets -- -D warnings
cargo test --release --locked --offline benchmark_dh04_geometry -- --ignored --nocapture
& $dh04Python scripts\test_analysis.py
cargo build --release --locked --offline
& $dh04Python scripts\seal_run.py
~~~

A repeat is reproducibility work and does not enlarge this completed study.

## Attribution

MaleCNS v1.0: FlyEM/HHMI Janelia, University of Cambridge, MRC LMB, Google
Research, and collaborators. Data are CC-BY. Source hashes and extracted anatomy
are inherited unchanged through the frozen DH-03 parent.
