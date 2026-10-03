# FAS-R1 Stage 1: Frozen Fabrique Engineering

**Status:** Stage 0 construction is sealed. Stage 1 sensor protocol and pre-model support pass are frozen. LFM extraction is the next authorized gate; no probe fit, proposal/value training, particle/search run, or protected evaluation has occurred.

Stage 1 treats R1 as an engineering line: build the frozen-substrate façade, expose failures, preserve each failed version, repair it, and continue until the planner overhead stops paying. Receipts and hashes establish provenance; they do not prohibit versioned engineering changes.

## Boundaries

- Stage 0 remains sealed at its prior source and artifact roots. Stage 1 additions live only under this directory.
- The model is `LiquidAI/LFM2.5-1.2B-Base` at the exact revision and file hashes in `sensor/R1-STAGE1-SENSOR-QUALIFICATION-MANIFEST-v01.json`.
- Backbone weights stay frozen. External probes, proposal, and value heads may be trained after their support and inputs are fixed.
- Use only the public `InferenceTask` projection for encoder inputs and public incidence. Private typed constraints and exact solver labels may join outputs offline for diagnostics/training labels, never enter model features or inference decisions.
- Do not import feature caches, datasets, heads, or run artifacts from FAS-00, S05, Phoenix, or other experiments.

## Frozen practical manifests

- `sensor/R1-STAGE1-SENSOR-QUALIFICATION-PROTOCOL-v01.md`: frozen family/render/vocabulary split, three ordered sensor rungs, probe shapes, controls, thresholds, and stop labels.
- `sensor/R1-STAGE1-SENSOR-QUALIFICATION-MANIFEST-v01.json`: exact Stage 0, prepared-input, model-snapshot, and implementation hashes.
- `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\sensor-qualification-v01\qualification-data-v02`: prepared public rows, private targets, action examples, split, and passing pre-model support audit.
- `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\sensor-qualification-v01\MODEL-SNAPSHOT-INVENTORY.json`: streaming hash inventory of the pinned local model and tokenizer snapshot.
- `manifests/measured-time-cutoffs-v01.json`: ten log-spaced `C_active` and `C_wall` prefix cutoffs in seconds; all arms run to their full trace maximum before prefix analysis.
- `qterminal/manifest-v01.json` will freeze the selector’s assignment mixture before fitting.

## Work order

1. Verify the local model/tokenizer hashes and environment against the sensor manifest. Extract the frozen corpus once and require repeatable float32 features before probe fitting.
2. Extract one independent representation per rendered clause and one for the whole problem. Retain lossless task/clause row mapping, input/output hashes, token counts, device/dtype, and model/tokenizer identity.
3. Fit and inspect sensor probes in order: clause-kind identity, entity/role binding, then `sign(ΔC)` action relevance. Keep shortcut controls. If a rung misses its threshold, retain the failed output, diagnose which interface component failed, and issue a versioned repair; do not call the sensor qualified until all rungs pass on the declared family support.
4. Fit and freeze `Q_terminal` as the common judge. Then fit the class-balanced one-step reachability proposal, preserving `n_improved_classes` and `Δd_min` telemetry, and fit `V_reach` on continuations under the frozen proposal.
5. Run complete prescribed traces for all arms. Compute `R(B)`, common-selector `S(B)`, and `R(B)-S(B)` from the same closed traces. Report charged-expansion, active-time, and wall-time curves; use the frozen cutoff manifest for time-prefix replay.
6. Broaden generator stress regimes and compare assignment, strict full-dynamic-state, and later state-summary merging as versioned engineering extensions. Preserve prior versions and their failures.

The first 96-family sensor support is a qualification baseline, not broad natural-language coverage: it has two paraphrase templates and `N=6..12`. Dense/sparse interaction regimes, deeper deceptive basins, and longer dependencies are later stress expansions once the first end-to-end machine runs.

## Run artifact placement

Store generated inputs, extracted features, checkpoints, trajectories, timing records, and receipts under:

`D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\`

Each repair increments its own versioned source/support/run directory. Never overwrite a failed run.
