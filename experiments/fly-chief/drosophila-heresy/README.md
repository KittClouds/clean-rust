# Drosophila Heresy — DH-01

**First experiment completed. Anatomical routing did not pass the prespecified
advantage gate in this synthetic model.**

Primary online accuracy was 51.47% with anatomical routing and 51.39% with
degree-preserving shuffled routing: +0.079 percentage points, paired 95%
bootstrap interval [-0.279, +0.452]. The 32-cue/longer-delay task was near chance.
The aggregate hides a phase distinction: anatomical routing reached 63.77%
late-acquisition accuracy (shuffled routing 63.36%, no learning 50.46%), then
finished reversal at 49.92%. Thus associations were learned, but reversal
recovery and harder-task performance were limited. This is evidence about this
particular routing/learner combination, not a rejection of local plasticity or
biological circuit function.

- [Frozen measured report](artifacts/runs/20260912T032529Z/REPORT.md)
- [Protocol](PROTOCOL.md)
- [Run seal](artifacts/runs/20260912T032529Z/seal.json)
- [Completion and raw-output hashes](artifacts/runs/20260912T032529Z/completion.json)
- [Independent replay verification](artifacts/verification/20260912T032529Z/verification.json)
- [Measured process memory](artifacts/runs/20260912T032529Z/resource-receipt.json)
- [Anatomy census and source hashes](artifacts/anatomy/census.json)
- [Result figure](artifacts/figures/20260912T032529Z/routing-effect.png)

## Scope

1,728 arm runs, 884,736 training trials, 24 paired computational seed bundles,
four dynamics settings, three suites, six controls. The slices are selected by
**soma side**, not synapse position; they come from one male specimen. The task
transfer suite is fresh cues in the same delayed-association task family, not an
independent navigation/vision architecture. No backpropagation, learning-rule
search, biological dynamics fitting, or task-driven hyperparameter tuning ran.

Right slice: 343 ALPNs, 2,045 Kenyon cells, 49 MBONs, 170 DANs, plus one APL
recorded in the anatomy audit but replaced by the declared top-k abstraction in
the model. There are 24,091 plastic KC-to-MBON pairs and 840 candidate DAN-to-MBON
routes. Modulating every plastic synapse on a target MBON is an invented coarse
broadcast assumption. DAN-to-KC connections and most recurrence are not simulated.
The audit records all retained layers and boundary connections.

There are more reciprocal MBON-DAN pairs in the right slice than in the coarse
degree nulls (311 versus mean 141.1), but that anatomical regularity did not yield
a reliable task advantage here. These nulls do not preserve exact cell-type-pair
counts or geometry, and repeated motifs are not independent animals.

## Engineering and costs

- Standalone Rust workspace: no edits to other crates or applications.
- Builds live in `D:\drosophila-heresy\target`; local `target` is a C:-side junction.
- Memory-mapped TSV ingestion with memchr, hashbrown construction, compact indices,
  immutable layer arrays, reusable mutable buffers, and wide SIMD weight updates.
- Input-derived sparse features are cached before learning. Lazy eligibility
  decay is algebraically equivalent to explicit local exponential decay.
- Four coarse worker threads; no allocations in the online simulation loop.
- Scientific execution including setup: 24.473 seconds. This excludes downloading,
  extracting, compiling, and report generation. The simulator process peaked at
  25,051,136 bytes working set as observed through Windows process counters.
- Downloads: 1,109,008,094 bytes total; the connectivity download took 302 seconds.
  The full streaming extraction took 221.644 seconds. Full-source counts include
  non-neuronal and unannotated segments and are not neuron counts.
- Right-slice persistent mutable arrays: 195,460 bytes per simulator. This excludes
  immutable graph/cue caches and the temporary initial-weight audit copy.
- 12 Rust unit/smoke tests, two Python analysis tests, an explicit synthetic
  benchmark, release Clippy with warnings denied, and one real-slice six-arm replay
  passed. The replay is bit-identical outside timings and adds no scientific samples.

## Reproduce

Use Rust 1.96.0 and the recorded Cargo.lock. Python preparation
used numpy 2.3.5, pandas 3.0.1 and pyarrow 25.0.1. PyArrow is project-local under
`.deps`; the bundled Python executable on this host is:

```powershell
$py = 'C:\Users\shuga\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
Set-Location 'C:\code land\clean-rust\experiments\drosophila-heresy'
$env:CARGO_TARGET_DIR = 'D:\drosophila-heresy\target'
cargo test --release
cargo clippy --release --all-targets -- -D warnings
cargo test --release benchmark_synthetic_simulator -- --ignored --nocapture
& $py scripts/test_analysis.py
cargo build --release
& $py scripts/seal_run.py
```

The launcher creates a new timestamped run and copies inputs, source and executable
before executing. It refuses to overwrite raw outputs. It verifies frozen hashes
after execution, runs the frozen analysis, and writes a completion receipt. A
repeat run is reproducibility work and should never increase the original study's
sample count.

Raw source data and download receipts remain under `D:\drosophila-heresy\data`.
`scripts/download.py` verifies existing receipts; `scripts/extract.py` rebuilds
the derived anatomy audit. Do not overwrite a frozen run's inputs. The archived
source, executable and extracted inputs in the run's `sealed` directory preserve
the actual first experiment regardless of future changes.

`scripts/plot_results.py` is post-run presentation only: Matplotlib consumes the
hash-verified frozen summary and does not recompute inference. Its optional
dependencies are isolated in `.plot-deps`.

## Attribution

MaleCNS v1.0: FlyEM/HHMI Janelia, University of Cambridge, MRC LMB, Google Research
and collaborators. Data are CC-BY; see https://male-cns.janelia.org/download/.
The annotations, transmitter predictions and full connection table have source
URLs, object metadata and SHA-256 hashes in the anatomy census.
