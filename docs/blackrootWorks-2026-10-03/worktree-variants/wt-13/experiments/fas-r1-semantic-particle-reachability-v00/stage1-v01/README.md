# FAS-R1 Stage 1: first real machine

## Operating mode

Stage 0 is complete and sealed. Stage 1 is an engineering experiment: build a runnable machine, measure its failures, preserve each version, repair the interface, and continue until the architecture stops paying. A failed gate is a diagnostic result. It does not retire R1.

Model contact is authorized for the exact local snapshot and extraction contract in `manifests/model-contact-manifest-v01.json`. The substrate stays frozen. Stage 0 files are read-only; every Stage 1 source, fit, and run lives outside Stage 0.

The frozen substrate is `LiquidAI/LFM2.5-1.2B-Base`, revision `7453bca97ca1e67754c4035a4b4c584e1c9dd725`. Stage 1 uses the final hidden state mean over visible tokens, stored as float32. Extraction was deterministic on the pinned RTX 3080 BF16 path. The exact input, model files, extraction outputs, and row mappings are hashed in the D-drive receipts.

## Source and run locations

- Stage 0 source: `stage0-v01/`; sealed commit `fb984e362a20c7a6ede2eb66b120859f150477d1`.
- Stage 1 source: this directory, on `codex/fas-r1-stage0-20260925`.
- Run artifacts: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\`.
- Earlier Rust target directories are on `D:`. The V19 sampling-temperature build uses `G:\cargo-targets\fas-r1-stage1-temperature-v19`; Stage 0 was not edited.
- Frozen sensor support: `manifests/sensor-support-manifest-v02.json`.
- Sensor probe v01: `manifests/sensor-probe-fit-manifest-v01.json`.
- Sensor probe v02 adapter repair: `manifests/sensor-probe-fit-manifest-v02.json`.
- Measured-time cutoffs: `manifests/measured-time-cutoffs-v01.json`.
- Q-terminal active contract: `qterminal/manifest-v02.json`.
- Compositional action adapter: `manifests/semantic-action-adapter-manifest-v02.json`.

## Work sequence

1. Extract frozen constraint and task representations; verify model/input/output byte identity.
2. Probe clause identity, pooled-H mention binding, and action relevance. After a miss, inspect the interface and preserve an amended version.
3. Fit the common terminal selector on the same candidate labels across arms. Version the selector when its held-out behavior is weak.
4. Fit the class-balanced one-step proposal and `V_reach` in separate, digest-bound stages.
5. Run depth, sampled depth, random width, learned width, exact merge, assignment merge, canonical merge, particle allocation, and oracle diagnostics under charged-operation, active-time, and wall-time prefixes.
6. Stress generator density, deceptive basins, long dependencies, and assignment-merge continuation loss. Preserve full traces and every engineering attempt.

The qualification family partition is now known to the engineering loop after sensor probe v01. Later use of that partition is adaptive debugging, not independent confirmation. Train and validation remain useful for fitting and iteration. If a later version needs clean evidence, create a fresh task family roster and manifest.

## Current evidence

See `ENGINEERING_LOG.md` for exact D paths, run hashes, failed attempts, and interpretation. Current summary:

- Frozen extraction completed and its three output files match the extraction receipt.
- Identity passed the declared v01 metric (qualification balanced accuracy 0.971); template-only identity control was 0.167.
- Pooled-H slot binding failed (combined qualification F1 0.379). This measures the fixed affine readout over pooled constraint/global vectors, not all possible LFM binding interfaces.
- The original pooled action MLP failed. Its v01 incidence control was not nested because it included 12 co-entity incidence counts omitted from the primary model.
- Probe v02 repairs that comparison by giving the primary the exact public incidence baseline before appending all three H summaries. Its adaptive qualification action macro-F1 remains low (0.390), versus 0.644 for incidence-only.
- A compositional adapter using frozen identity probabilities, public incidence, assignment, and candidate edit predicts the sign of exact `ΔC` at 0.974 qualification macro-F1. The private-kind oracle is 1.000. This is a strong engineering lead, not independent confirmation: the same qualification partition was already reported. Its implication clauses are tautologies, so nontrivial implication grounding remains untested.
- The V04 class-balanced proposal has modest validation fit (cross-entropy 3.6299; top-edit teacher mass 4.54%). On the opened V04 qualification roster, applying `--learned-sample-temperature 0.17864354564164298` at sampling time raises SampledDepth from 1/64 to 55/64 and LearnedWidth from 0/64 to 58/64; Greedy stays 18/64 and RandomWidth stays 0/64. This is an adaptive engineering result, not independent confirmation.
- Width adds only a small margin over calibrated sampled depth on this roster: 5 paired wins, 2 losses, and 57 ties. The larger gain is the learned proposal's sampling calibration. Assignment/canonical merging reduces reachability to 31/64; strict dynamic merge matches LearnedWidth at higher measured cost.
- The `base_only_v03` lesion reaches 0/64 under every tested core arm at both temperatures. This is useful interface diagnosis, but V04's all-`Different` grammar lets public incidence encode exact one-edit deltas, so these runs do not establish that LFM content supplies that action signal.
- V_reach-v07 was fit with the T=1 proposal. Particle runs at temperature 0.17864 are off-policy diagnostics and need a matching train/validation-only V_reach refit before allocation comparisons are pushed further. On the current roster, `R=S` throughout, so the common terminal selector was not the observed bottleneck.

## Runtime label boundary

Private typed clause labels and exact action deltas are offline targets and scoring diagnostics. They never enter the frozen representation extractor, runtime proposal, action adapter, or search scheduler. Public per-clause entity and role mention incidence is part of the declared inference projection and may be used at runtime. Private template IDs are oracle shortcut diagnostics only.

`V_reach(X,b)` is continuation reachability under the frozen learned proposal and is used for allocation. `Q_terminal(a,H)` is trained separately and selects among visited assignments. Oracle reachability remains post-hoc: a branch is credited when the exact validator later finds a valid state, without giving a stop signal to the live controller.

## Reproduction entry points

The source entry points and manifests are versioned under `sensor/`, `qterminal/`, and `proposal/`. Use new output directories for every run. Do not overwrite failed runs or the sealed Stage 0 source. The worktree README and D-drive receipts are the engineering record; a source change does not promote a run to a pass.

The Stage1 pilot accepts `--learned-sample-temperature T` (default `1`). It affects only learned categorical sampling (`SampledDepth`, `LearnedWidth`, merge, and particle arms); Greedy and Uniform arms ignore it. Each pilot manifest records the requested temperature, and each run record stores an effective temperature only when its arm uses learned sampling. Non-default temperatures are part of learned-sampling trace identity and replay configuration.
