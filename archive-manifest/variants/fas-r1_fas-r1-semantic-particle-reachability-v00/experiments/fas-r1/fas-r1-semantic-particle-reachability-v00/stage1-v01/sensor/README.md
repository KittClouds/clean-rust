# R1 Stage 1 frozen sensor extraction

This directory implements only the frozen representation extraction surface.
It loads the pinned `LiquidAI/LFM2.5-1.2B-Base` snapshot, verifies one repeated
forward pass, and writes one float32 mean vector for each rendered constraint
and each task's global text. It does not fit probes or train the selector,
proposal, or reachability value model.

## Frozen model facts

The materialized snapshot is pinned to
`7453bca97ca1e67754c4035a4b4c584e1c9dd725`. Its local config declares model
type `lfm2`, architecture `Lfm2ForCausalLM`, hidden size 2048, 16 layers, and
BF16 weights. Installed Transformers 5.17.0 maps the config to `Lfm2Model`
through `AutoModel`; its forward signature accepts `output_hidden_states`,
`attention_mask`, and `use_cache`. The fast tokenizer is supported locally.
The harness uses `AutoModel` to expose the base model's final hidden layer,
not the language-model logits.

## Input and output contract

Input is the public `public-tasks.jsonl` emitted by the Stage 0 runner. The
reader accepts exactly the `InferenceTask` fields and rejects extra or missing
keys, so typed clauses, solver solutions, and generator seeds cannot enter the
sensor path. It encodes `global_text` and each rendered clause independently.
Each call uses tokenizer special-token defaults, one sequence, no padding, and
no truncation. The final hidden activations at visible positions are cast to
float32 before their arithmetic mean is taken.

Outputs are written to a new directory; overwrite is refused:

- `constraint_H.float32.npy`: `(total_constraints, 2048)` little-endian float32.
- `global_h.float32.npy`: `(task_count, 2048)` little-endian float32.
- `rows.jsonl`: stable row-to-task/clause mapping, input-text hash, token count,
  and per-vector output hash.
- `receipt.json`: exact model revision, complete model-file and tokenizer-file
  SHA-256 inventories, input-file hash, software/device/dtype details, and the
  two repeat-verification output hashes.
- `failure.json`: written when a new output directory was created but the run
  failed before a completion receipt could be written.

The model snapshot itself is local. Both `AutoConfig`, `AutoTokenizer`, and
`AutoModel` are loaded with `local_files_only=True` and
`trust_remote_code=False`. The snapshot directory name must equal the pinned
commit hash.

## Memory and compute

The snapshot contains 2,340,697,936 bytes of weights (about 2.18 GiB) in BF16.
BF16/FP16 model compute therefore needs at least that much device memory for
weights, plus framework state and temporary activations. Float32 model compute
needs roughly twice the weight memory. `--model-dtype auto` selects BF16 on a
CUDA device that supports it, otherwise FP16 on CUDA and float32 on CPU. The
saved vectors are float32 regardless of model compute dtype. The output matrix
storage costs `4 * 2048 * (total_constraints + task_count)` bytes, in addition
to small JSONL receipts. CUDA inference can fail if the device cannot fit the
weights and temporary activations together.

Inputs are processed one at a time to avoid padding. This preserves the
declared per-text visible-token mean and bounds activation memory, at the cost
of more forward calls. Hashing the pinned snapshot reads the full weight file;
it does not copy or modify the model cache. The run is deterministic mode and
fails if two identical verification passes produce different float32 bytes.

## Commands

Use the Stage 0 runner output as input. Each output directory must be new.

```powershell
$Repo = 'C:\Users\shuga\.codex\worktrees\fas-r1-stage0-20260925\clean-rust'
$Sensor = Join-Path $Repo 'experiments\fas-r1-semantic-particle-reachability-v00\stage1-v01\sensor\run_sensor.py'
$Snapshot = 'D:\r1-models\lfm2.5-1.2b-base-7453bca97ca1e67754c4035a4b4c584e1c9dd725'
$Input = 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage0-v01\construction-attempt-v02\public-tasks.jsonl'
$Output = 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\sensor-attempt-v01'
python $Sensor --snapshot-dir $Snapshot --input $Input --output $Output --device auto --model-dtype auto
```

For the authorized minimal sanity pass, use a one-record public input file and
a distinct output path. The command above runs every record in its input file;
do not point it at the full 96-world corpus until the experiment owner directs
that sweep.
