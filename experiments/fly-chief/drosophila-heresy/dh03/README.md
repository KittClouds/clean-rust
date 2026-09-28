# Drosophila Heresy — DH-03

**Distractor-generated eligibility was beneficial in this synthetic reversal
task; retaining the interval neural state was not detectably beneficial.**

Across 24 fresh paired seed bundles, retaining interval eligibility increased
right-slice final reversal-probe accuracy by **+6.836 percentage points**. Its
paired 95% interval was [+5.770, +7.971], and its prespecified familywise 97.5%
interval was **[+5.627, +8.154]**. Retaining rather than restoring interval
neural state changed accuracy by **-0.065 points**, familywise interval
**[-0.468, +0.370]**. The descriptive factorial interaction was -0.146 points,
95% interval [-1.025, +0.789].

This rejects the proposed “corrupted interval eligibility versus beneficial
state drift” explanation. Removing interval eligibility collapsed performance
to the quiet-delay level; restoring state had almost no effect. Yet both
eligibility-retained cells remained below chance. A broad forgetting or
old-association-erasure account is plausible, but DH-03 did not predeclare
matched old-map probes or weight-projection measurements and therefore does not
establish that mechanism.

- [Frozen measured report](artifacts/runs/20260912T042145Z/REPORT.md)
- [Prespecified protocol](PROTOCOL.md)
- [Run seal](artifacts/runs/20260912T042145Z/seal.json)
- [Completion and output hashes](artifacts/runs/20260912T042145Z/completion.json)
- [Independent real-slice replay](artifacts/verification/20260912T042145Z/verification.json)
- [Result figure](artifacts/figures/20260912T042145Z/dh03-results.png)

## Factorial result

All conditions shared 256 identical immediate-reward acquisition trials. During
the 256 reversal trials, every factorial cell processed the same twelve
distractors and consumed the same RNG stream.

| Right-slice condition | Final reversal probe |
| --- | ---: |
| Immediate anchor | 55.66% |
| Quiet anchor | 33.00% |
| Retain eligibility, retain state | 39.92% |
| Suppress eligibility, retain state | 33.15% |
| Retain eligibility, restore state | 40.06% |
| Suppress eligibility, restore state | 33.15% |

Eligibility suppression restored the trace to its post-cue snapshot after each
interval, preserving cue-trace decay. State restoration copied baseline, MBON,
DAN, feedback, and gain arrays back to their post-cue values while preserving
weights, trace scale, RNG, and the assigned eligibility trace. Exact suppression
and restoration receipts passed on all expected trials.

## Scope and integrity

The run contains 1,152 arm runs and 589,824 computed training trials: 24 seeds,
two eligibility constants, two related soma-side slices, six conditions, and
learning/fixed-weight arms. The two right-slice factorial main effects were the
only co-primary outcomes. Immediate, quiet, left-slice, tau-specific, online,
late-window, and interaction results are descriptive.

The frozen launch followed 27 passing Rust tests, four Python analysis tests,
warnings-as-errors Clippy, a locked offline release build, and an explicit
zero-allocation benchmark. Simulation plus diagnostics took 16.799 seconds on
four workers; measured process peak working set was 18,501,632 bytes. The seal
covers 33 files and all ten scientific outputs remain hash-verified.

The post-run replay reproduced all recorded non-timing outputs for one real
right-slice seed, all six conditions, and both arms, with observers both enabled
and removed. It added no scientific samples. DH-01 and DH-02 seals and outputs
were reverified before and after execution.

## Limits

These interventions identify the effect of retaining two aggregate channels
throughout reversal. They do not constitute biological mediation analysis.
Repeated state restoration can alter later trace formation, although the
factorial interaction was small here. The task labels, neuron dynamics, uniform
modulation, inhibition, and trial boundaries are synthetic modeling choices.
The slices come from one specimen. No backpropagation, model search, parameter
rescue, extra seed, or post-outcome tuning was used.

## Reproduce

The local target directory is a junction to D:\drosophila-heresy\dh03-target.
The launcher verifies both frozen parents, creates a new timestamped run, freezes
the exact source/executable/protocol/analysis/anatomy, then executes and hashes
the outputs.

~~~powershell
$dh03Python = 'C:\Users\shuga\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
Set-Location 'C:\code land\clean-rust\experiments\drosophila-heresy\dh03'
$env:CARGO_TARGET_DIR = 'D:\drosophila-heresy\dh03-target'
cargo test --release --locked --offline
cargo clippy --release --locked --offline --all-targets -- -D warnings
cargo test --release --locked --offline benchmark_dh03_factorial -- --ignored --nocapture
& $dh03Python scripts\test_analysis.py
cargo build --release --locked --offline
& $dh03Python scripts\seal_run.py
~~~

A repeat is reproducibility work and does not enlarge this completed study.

## Attribution

MaleCNS v1.0: FlyEM/HHMI Janelia, University of Cambridge, MRC LMB, Google
Research, and collaborators. Data are CC-BY. Source hashes and the extracted
anatomy boundary are inherited unchanged through the frozen DH-02 parent.
