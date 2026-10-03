# Jev-like Zero-Training Recon v0.1

Evaluation-only frozen-model reconnaissance. The program does not import an
optimizer, call a training API, or write model weights.

## Runtime

The isolated Windows environment and model snapshots live outside the
repository under:

`D:\codex-runs\jev-zero-training-recon-v01`

The two snapshots are pinned in `recon.py`. The canonical input is the
validated bridge JSONL at:

`D:\codex-runs\jev-corpus-bridge-v01\pilot-episodes.jsonl`

## Smoke / pilot command

```powershell
$py = 'D:\codex-runs\jev-zero-training-recon-v01\venv\Scripts\python.exe'
& $py experiments/jev-zero-training-recon-v01/recon.py `
  --max-queries 128 `
  --batch-size 8 `
  --profiles name,name_definition,opaque_definition,opaque_only `
  --templates A `
  --candidate-reorder `
  --output D:\codex-runs\jev-zero-training-recon-v01\results
```

The evaluator records direct next-token scores, sequence scores, tokenization
metadata, schema-profile comparisons, candidate-order drift, calibration by
probability source, and a best-effort `past_key_values` shared-prefix test.
Evidence/world interventions are reported unavailable unless verified sibling
episodes with recomputed gold targets are present.

