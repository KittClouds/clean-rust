# R1 Q_terminal v2 data and training harness

This package freezes the first practical assignment mixture and implements a compact common binary selector. It never loads the LFM or tokenizer. The sensor ladder must be run first; if a rung misses, preserve that result and label any resulting selector run as interface-repair engineering evidence rather than a sensor qualification pass.

## Frozen mixture

See [`manifest-v02.json`](manifest-v02.json). It supersedes the preserved v01 manifest because Stage 0 requires a positive `latent_dim` even for its uniform-random stub. The amended baseline uses one inert coordinate; the stub policy does not read or update a learned control state. Family splits use a salted SHA-256 bucket before surface rendering: 80% train, 10% validation, 10% test. All renderings and candidate assignments for an isomorphism family inherit that split.

Training rows use four equal cells: random complete assignments labeled valid/invalid by the exact validator, and assignments visited by the frozen Stage 0 baseline trace source labeled valid/invalid. The random pool samples valid assignments uniformly from exact validator solutions and invalid assignments uniformly from the complete assignment space conditioned on invalidity. Sampling is deterministic, without replacement, and capped at four samples per family per source/label cell. Cell totals are matched to the smallest available cell, so the train mixture is exactly 25% per cell. A lack of support in any cell is an error; the builder never fabricates or oversamples states.

The pre-Q baseline trace source is `R1_QTERMINAL_BASELINE_VISITATION_V1`: `RANDOM-WIDTH`, `uniform_random_stub`, width 1, 256 charged expansions, seeded from the family ID and replicate index. It needs no trained proposal. Collect the initial assignment and every complete `assignment_after` state, close and replay-check the trace, then join labels from the independent typed validator. The Stage 0 posthoc sidecar is retained as an agreement diagnostic. Policy-visited rows are accepted only for train families. Validation and test rows use random complete assignments from their held-out families, balanced 50:50 by exact validator label. A task may lack one label class entirely (for example, a world with no constraints has no invalid assignments); such tasks contribute no candidate to that class. The builder never fabricates labels, and split-level balancing still fails if any required cell has no support.

## Frozen feature input

`--features` points to the pinned Stage 1 sensor extraction directory containing `receipt.json`, `constraint_H.float32.npy`, `global_h.float32.npy`, and `rows.jsonl`. The loader verifies the receipt hashes, the public task file hash, each encoded text hash, each vector hash, task/clause alignment, and the support/model-contact manifest hashes. It then maps flattened clause vectors into the following in-memory arrays; no feature values are dropped or truncated:

| File | Shape and dtype |
| --- | --- |
| `feature_ids`, `task_ids`, `family_ids` | string `[T]`, exact public task and family IDs |
| `n_by_feature`, `k_by_feature` | integer `[T]` |
| `h_constraints` | finite float32 `[T,M,2048]`, left-packed clauses, zero padded |
| `constraint_mask` | bool `[T,M]`; empty-constraint worlds use one all-false padded slot |
| `h_global` | finite float32 `[T,2048]` |
| `entity_incidence` | bool `[T,M,20]`, public rendered-clause/entity mentions |
| `role_incidence` | bool `[T,M,6]`, public rendered-clause/role mentions |

`M` may be smaller than 512. Rows are padded only on the right. Inputs beyond the manifest's `M=512`, `N=20`, `K=6`, or `D=2048` support fail closed; no truncation is allowed.

`--candidates` is private offline JSONL. Each record contains `sample_id`, `feature_id`, `task_id`, `family_id`, `source_kind`, a complete zero-based role assignment, `posthoc_valid` (JSON boolean), and `label_source="independent_typed_validator_v1"`. Random rows also pin `random_sampler_id="R1_QTERMINAL_CLASS_CONDITIONED_ASSIGNMENTS_V1"` and an integer `random_replicate_index`. Policy rows require `policy_checkpoint_id="R1_QTERMINAL_BASELINE_VISITATION_V1"`, `policy_training_split="train"`, `policy_trace_id`, and `trace_event_index` (`-1` denotes the initial state). The feature ID must resolve to the same task/family in the feature arrays. The validator label and metadata are kept out of the model call.

## Commands for the authorized Q_terminal fitting phase

First build exact class-conditioned random candidates and training-family baseline traces. The generator verifies the frozen extraction receipt and input hashes, uses only the Stage 0 world/search crates, and performs no model forward or fitting:

```powershell
$env:CARGO_TARGET_DIR = 'D:\cargo-targets\fas-r1-qterminal-stage1'
cargo run --release `
  --manifest-path experiments/fas-r1-semantic-particle-reachability-v00/stage1-v01/qterminal/candidate-generator/Cargo.toml `
  -- `
  --extraction D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-extraction-v01 `
  --private-tasks D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage0-v01\construction-attempt-v02\private-tasks.jsonl `
  --output D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-candidates-v04
```

Then prepare the deterministic mixture into a new output directory:

```powershell
python experiments/fas-r1-semantic-particle-reachability-v00/stage1-v01/qterminal/prepare_dataset.py `
  --candidates D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-candidates-v04\candidate-records.jsonl `
  --features D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-extraction-v01 `
  --output D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-data-v02
```

After the sensor ladder has been run, fit the shared selector. A sensor miss does not prevent engineering iteration; any associated run must preserve and identify the miss and any feature-interface repair:

```powershell
python experiments/fas-r1-semantic-particle-reachability-v00/stage1-v01/qterminal/train_qterminal.py `
  --dataset D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-data-v02 `
  --features D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-extraction-v01 `
  --output D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-fit-v02 `
  --sensor-diagnostic-report D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-probes-v02\qualification-report.json `
  --device auto
```

The generator and prepare commands create data only. The fit command trains one shared selector, chooses the checkpoint by validation BCE, calibrates one scalar temperature on validation labels, freezes both, then reads test labels for held-out metrics. It records accuracy, balanced accuracy, Brier score, BCE, ROC AUC, and 10-bin calibration error overall and by source when that source exists in a split. Existing output directories are refused rather than overwritten.

The model's Python call surface is exactly `forward(H, h_global, a)`. `H` contains constraint vectors, their padding mask, and public entity/role incidence. No latent state, remaining-budget field, task/family identifier, policy source label, or validator metadata enters the selector.

## Construction checks

Run the small data-contract suite without fitting:

```powershell
python -m unittest discover -s experiments/fas-r1-semantic-particle-reachability-v00/stage1-v01/qterminal/tests -v
```
