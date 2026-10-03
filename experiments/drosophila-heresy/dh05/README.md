# DH-05: Old memory or new memory?

DH-05 is the frozen trajectory assay following the DH-04 causal split. It asks whether interval eligibility mainly weakens the acquired association or directly constructs the reversed association.

The experiment compares `eligibility_retained` with `eligibility_suppressed` after the same acquisition stream and the same state restoration intervention. It records deterministic old-map and reversed-map margins, acquisition-axis retention, parallel displacement from the acquired weight vector, and perpendicular displacement at reversal trials `0, 16, 32, 64, 128, 256`.

The primary results support partial erasure in this synthetic model:

- Final old-map probe, retained minus suppressed: **-7.837 percentage points**, 95% CI **[-8.683, -6.999]**.
- Final acquisition-axis projection, retained minus suppressed: **-3.180**, 95% CI **[-3.557, -2.800]**.
- At 256 trials, the acquisition-axis coordinate was **0.660** with retained eligibility and **0.828** with eligibility suppressed.
- The retained condition also had greater perpendicular displacement: **0.958** versus **0.202**.

The trajectory therefore shows stronger movement away from the acquired state, with a substantial component outside the acquisition axis. The reversed-map margin remains negative at the final checkpoint in both delayed conditions, so this assay does not establish successful new-map formation. It supports a model of eligibility-assisted destabilization or reconfiguration, not a complete reversal-learning mechanism.

The run contains 768 arm runs, 393,216 computed training trials, 24 fresh seed bundles, two trace time constants, and one MaleCNS v1.0 specimen. The simulator is synthetic; the measurements do not establish a biological mechanism or a general learning rule.

Files:

- [Protocol](PROTOCOL.md)
- [Measured report](artifacts/runs/20260915T184423Z/REPORT.md)
- [Sealed run](artifacts/runs/20260915T184423Z/seal.json)
- [Completion receipt](artifacts/runs/20260915T184423Z/completion.json)
- [Verification](artifacts/verification/20260915T184423Z/verification.json)
- [Trajectory figure](artifacts/figures/20260915T184423Z/dh05-results.svg)
- [Post-run qualification](QUALIFICATION_POSTRUN.json)

Reproduction from this directory:

```powershell
cargo test --release --locked --offline
cargo clippy --release --locked --offline --all-targets -- -D warnings
python scripts/test_analysis.py
python scripts/render_trajectory.py artifacts/runs/20260915T184423Z
```
