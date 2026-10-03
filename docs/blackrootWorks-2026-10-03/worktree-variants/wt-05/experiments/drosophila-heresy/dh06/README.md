# DH-06: Causal geometry of eligibility-driven destabilization

DH-06 tests whether the interval-eligibility effect exposed by DH-05 acts through acquisition-aligned erosion, support-masked off-axis reconfiguration, or both. It applies realized, clipping-aware counterfactual updates to four causal cells while preserving the DH-05 task, state restoration, reward schedule, two trace time constants, fixed-weight negative control, and one MaleCNS v1.0 specimen.

DH-06 passed both co-primary directional gates in this synthetic model. The perpendicular factorial effect on final old-map margin was **-0.004461**, familywise 97.5% interval **[-0.005392, -0.003459]**. The parallel factorial effect on final acquisition-axis coordinate was **-0.202712**, familywise 97.5% interval **[-0.219702, -0.185074]**.

At 256 reversal trials, perpendicular-only retained an acquisition-axis coordinate of **0.848** but reduced old-map margin to **0.0268**. Parallel-only reduced the coordinate to **0.610** and old-map margin to **0.0235**. The both cell reached **0.669** and **0.0200**, respectively. Realized interval update energy was approximately **99.7% perpendicular** in the both cell, so the old-map effect cannot be described as simple acquisition-axis weakening alone.

The interaction was positive for both old-map margin (**+0.001830**, descriptive 95% interval [+0.001238, +0.002440]) and acquisition-axis coordinate (**+0.049225**, descriptive 95% interval [+0.038182, +0.060777]). This is consistent with a non-additive state transition: aligned erosion and off-axis remodeling influence one another. The result remains a synthetic mechanism finding; it does not establish a biological mechanism or a general learning rule. The interpretation gate is frozen in [PROTOCOL.md](PROTOCOL.md).

Files:

- [Protocol](PROTOCOL.md)
- [Measured report](artifacts/runs/20260915T201008Z/REPORT.md)
- [Sealed run](artifacts/runs/20260915T201008Z/seal.json)
- [Verification](artifacts/verification/20260915T201008Z/verification.json)
- [Trajectory figure](artifacts/figures/20260915T201008Z/dh06-results.svg)
- [Qualification](QUALIFICATION.json)
- [Post-run qualification](QUALIFICATION_POSTRUN.json)

Reproduction uses the project-local pinned analysis interpreter recorded in the run seal:

```powershell
cargo test --release --locked --offline
cargo clippy --release --locked --offline --all-targets -- -D warnings
python scripts/test_analysis.py
```

The scientific launcher freezes all source, protocol, qualification, script, anatomy, and binary hashes before executing the declared seed grid. It writes the release target through `D:/drosophila-heresy/dh06-target` and uses the `target` junction in this directory.
