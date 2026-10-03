# Frozen compatibility readout probe

This experiment trains only a dynamic runtime-schema compatibility head over
cached hidden states. The causal backbones remain frozen and Phoenix is out of
scope.

## External inputs

The generator reads the validated decision-world crates and writes external
artifacts to `D:\codex-runs\jev-frozen-readout-v01`. The bridge pilot is read
from `D:\codex-runs\jev-corpus-bridge-v01\pilot-episodes.jsonl`.

```powershell
$env:CARGO_TARGET_DIR = 'D:\codex-runs\jev-corpus-target'
cargo test --manifest-path experiments/jev-frozen-readout-v01/Cargo.toml --all-targets
cargo run --release --manifest-path experiments/jev-frozen-readout-v01/Cargo.toml

$py = 'D:\codex-runs\jev-zero-training-recon-v01\venv\Scripts\python.exe'
& $py experiments/jev-frozen-readout-v01/prepare_bank.py
```

The bank preparation step preserves perturbation families and writes train,
dev, test, external-eval, and a split manifest outside the repository.

## Feature extraction

The local model directory is expected at
`D:\codex-runs\jev-zero-training-recon-v01\models\<model-name>`. Model names
and pinned revisions are in `probe.py`.

```powershell
& $py experiments/jev-frozen-readout-v01/probe.py extract `
  --model-name minicpm5-1b-base --batch-size 8 `
  --output D:\codex-runs\jev-frozen-readout-v01\features

& $py experiments/jev-frozen-readout-v01/probe.py extract `
  --model-name qwen3-0.6b-base --batch-size 8 `
  --output D:\codex-runs\jev-frozen-readout-v01\features

& $py experiments/jev-frozen-readout-v01/probe.py extract `
  --model-name k2-horizon-0.9b --batch-size 8 `
  --output D:\codex-runs\jev-frozen-readout-v01\features
```

K2 requires `trust_remote_code` because its published checkpoint includes a
custom model implementation. The code removes `token_type_ids` only for K2.

## Head-only smoke fit

```powershell
& $py experiments/jev-frozen-readout-v01/probe.py train `
  --cache D:\codex-runs\jev-frozen-readout-v01\features\minicpm5-1b-base-features.pt `
  --head-kind mlp --location mean_full --loss-variant L3 `
  --profile name_definition --train-size 512 --dev-size 256 --eval-size 128 `
  --epochs 1 --augment-reorder `
  --output D:\codex-runs\jev-frozen-readout-v01\runs
```

The same command applies to Qwen and K2 by changing the cache path. The output
records `backbone_frozen: true`, trainable parameter count, exact source
metrics, per-profile metrics, transfer metrics, and per-group rows for later
intervention analysis.

## Required report set

The run directory is external. The planned report names are:

```text
representation-probe.json
readout-ablation.json
training-size-scaling.json
candidate-order-invariance.json
schema-binding.json
hard-sibling-challenge.json
evidence-intervention.json
world-intervention.json
calibration.json
cache-equivalence.json
frozen-readout-comparison.json
```

Do not interpret a smoke fit as a promotion result. Native sequence-likelihood
and proposition baselines must be measured on the same protected episodes.
