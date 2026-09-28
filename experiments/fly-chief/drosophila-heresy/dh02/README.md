# Drosophila Heresy — DH-02

**The prespecified distractor-impairment prediction was contradicted.** Starting
from identical acquired states, the right-slice uniform learner finished reversal
at 31.27% after a quiet twelve-step delay and 39.44% after twelve distractors.
The primary quiet-minus-distractor effect was **-8.171 percentage points**, with
a paired 95% bootstrap interval of **[-9.277, -7.080]** across 24 fresh seed
bundles. The effect had the same direction at both frozen eligibility time
constants. Immediate reward reached 56.53%.

Both delayed conditions remained below chance. The result therefore says that
distractor exposure was less damaging than a quiet delay in this synthetic
reversal task; it does not show successful delayed learning or a general benefit
from distraction.

- [Frozen measured report](artifacts/runs/20260912T040045Z/REPORT.md)
- [Prespecified protocol](PROTOCOL.md)
- [Run seal](artifacts/runs/20260912T040045Z/seal.json)
- [Completion and output hashes](artifacts/runs/20260912T040045Z/completion.json)
- [Independent replay verification](artifacts/verification/20260912T040045Z/verification.json)
- [Result figure](artifacts/figures/20260912T040045Z/dh02-results.png)

## Design and result

Every condition received the same 256-trial immediate-reward acquisition phase.
Only the following 256 reversal trials differed: immediate reward, reward after
twelve quiet state updates, or reward after twelve unrelated sensory patterns.
The acquired weights, traces, neural state, and RNG state were hashed and matched
within every seed, side, eligibility setting, and arm before the split.

| Soma slice | Arm | Immediate | Quiet delay | Distractor delay |
| --- | --- | ---: | ---: | ---: |
| R | uniform local learning | 56.53% | 31.27% | 39.44% |
| R | fixed weights | 50.85% | 50.85% | 50.85% |
| L | uniform local learning | 55.06% | 31.26% | 38.13% |
| L | fixed weights | 50.20% | 50.20% | 50.20% |

The observer found no post-cue eligibility contribution during quiet intervals.
With distractors, the cue component averaged 4.09% of the separate cue-plus-
interval L1 mass at reward. This is a pre-clipping trace diagnostic, not a fraction
of realized learning and not evidence that eligibility contamination caused the
behavior. The distractor condition also changed baseline activity, recurrent
state, clipping, and other dynamics. DH-02 did not intervene on those mediators.

## Scope and integrity

The run contains 576 arm runs and 294,912 computed training trials: 24 new seed
bundles, two eligibility constants, two related soma-side slices, three reversal
conditions, and learning/fixed-weight arms. The left and right slices come from
one MaleCNS specimen and are not independent animals. The action mapping and
dynamics are synthetic. No backpropagation, learning-rule search, rescue tuning,
or post-outcome parameter change was performed.

Before execution, 22 Rust tests, three Python analysis tests, an explicit
allocation/performance benchmark, and release Clippy with warnings denied passed.
The scientific run took 7.953 seconds on four workers; the measured process peak
working set was 16,297,984 bytes. The online loop recorded zero allocations.
The frozen seal covers 29 source/input/executable files, and completion hashes
cover all ten outputs. A real-slice replay matched every recorded non-timing
output with the observer enabled and disabled; exact final-weight observer
noninterference is additionally covered by synthetic tests because full final
weight arrays were not persisted.

## Reproduce

The Rust target is `D:\drosophila-heresy\dh02-target`; the local `target`
directory is a junction to it. The launcher creates and seals a fresh timestamped
run before execution, refuses to overwrite raw results, verifies DH-01 lineage,
and analyzes the run with its frozen script.

```powershell
$dh02Python = 'C:\Users\shuga\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
Set-Location 'C:\code land\clean-rust\experiments\drosophila-heresy\dh02'
$env:CARGO_TARGET_DIR = 'D:\drosophila-heresy\dh02-target'
cargo test --release --locked --offline
cargo clippy --release --locked --offline --all-targets -- -D warnings
cargo test --release --locked --offline benchmark_dh02_observer -- --ignored --nocapture
& $dh02Python scripts\test_analysis.py
cargo build --release --locked --offline
& $dh02Python scripts\seal_run.py
```

A repeat is reproducibility work and does not add samples to this completed
study. `scripts/plot_results.py <run-directory>` renders a hash-checked frozen
summary without recomputing statistics.

## Attribution

MaleCNS v1.0: FlyEM/HHMI Janelia, University of Cambridge, MRC LMB, Google
Research, and collaborators. Data are CC-BY; source hashes and the retained
anatomy boundary are inherited unchanged from DH-01's frozen census.
