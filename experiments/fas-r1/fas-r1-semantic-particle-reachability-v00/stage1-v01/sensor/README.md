# R1 Stage 1 frozen sensor extraction

This directory implements frozen representation extraction for Stage 1. It loads the pinned LiquidAI/LFM2.5-1.2B-Base snapshot, verifies a repeated forward pass, and writes a float32 mean vector per rendered constraint plus one per task's global text. It does not fit probes or train the selector, proposal, or reachability value model.

## Frozen model

The materialized snapshot is pinned to 7453bca97ca1e67754c4035a4b4c584e1c9dd725. Its local config declares lfm2, architecture Lfm2ForCausalLM, hidden size 2048, 16 layers, and BF16 weights. Installed Transformers 5.17.0 maps the config to Lfm2Model through AutoModel. The fast tokenizer loads from the same local snapshot. The harness exposes the base model's final hidden layer, not language-model logits.

Config, tokenizer, and model loading use local_files_only=True and trust_remote_code=False. The explicit local snapshot path is checked against the frozen model-contact manifest. Before model loading, the harness checks the manifest's model ID, revision, path, model.safetensors size and SHA-256, and tokenizer.json SHA-256. It hashes all snapshot files again after extraction and requires byte identity.

## Input and extraction contract

Input is the Stage 0 public public-tasks.jsonl projection. The reader accepts exactly the InferenceTask field set and rejects extra or missing keys, so typed clauses, solver solutions, and generator seeds cannot enter the sensor path. It encodes global_text and each rendered clause independently. Each call uses tokenizer special-token defaults, one sequence, no padding, and no truncation. The final hidden activations at visible positions are cast to float32 before their arithmetic mean is taken.

The frozen v02 support manifest is checked against the exact input file SHA-256 and row count. Each task/family roster entry and all train/validation/qualification counts are checked, and the manifest hash plus split are stored in the receipt and every row. Manifest v01 is preserved as an earlier diagnostic record; Stage 1 fitting uses v02.

## Outputs

Output goes to a new directory; overwriting is refused.

- constraint_H.float32.npy: (total_constraints, 2048) little-endian float32.
- global_h.float32.npy: (task_count, 2048) little-endian float32.
- rows.jsonl: task/clause row mapping, split, token count, input-text SHA-256, per-vector output SHA-256.
- receipt.json: model revision and file hashes, tokenizer/input/output hashes, software/device/dtype, frozen manifest hash, and repeat-verification hashes.
- failure.json: written when a newly created output directory fails before a completion receipt exists.

## Memory and compute

The snapshot contains 2,340,697,936 bytes of BF16 weights (about 2.18 GiB). BF16/FP16 compute needs at least that much device memory for weights, plus framework state and temporary activations. Float32 compute needs roughly twice the weight memory. The manifest policy is CUDA BF16 when supported, else CUDA FP16; CPU FP32 fallback. The harness implements that policy with model-dtype auto. Saved vectors are float32 for every compute dtype. Matrix storage is 4 * 2048 * (total_constraints + task_count) bytes, plus small JSONL receipts.

The implementation processes one text per forward pass, without padding, to keep activation memory bounded. This costs more calls than batching. Deterministic algorithms are enabled. The run first repeats the same public input and requires bitwise-equal float32 features. Snapshot hashing reads the full model weight file and does not change the cache. The Transformers warning that causal_conv1d is unavailable means the reference PyTorch convolution path is used; this affects speed, not the selected model or extraction formula.

## Commands

Frozen manifests:

- experiments/fas-r1-semantic-particle-reachability-v00/stage1-v01/manifests/model-contact-manifest-v01.json
- experiments/fas-r1-semantic-particle-reachability-v00/stage1-v01/manifests/sensor-support-manifest-v02.json

Copy the public Stage 0 JSONL byte-for-byte into a unique D run directory and check its SHA-256 against the sensor-support manifest before extraction. Then run:

$Repo = 'C:\Users\shuga\.codex\worktrees\fas-r1-stage0-20260925\clean-rust'
$Sensor = Join-Path $Repo 'experiments\fas-r1-semantic-particle-reachability-v00\stage1-v01\sensor\run_sensor.py'
$Snapshot = 'D:\r1-models\lfm2.5-1.2b-base-7453bca97ca1e67754c4035a4b4c584e1c9dd725'
$ModelManifest = Join-Path $Repo 'experiments\fas-r1-semantic-particle-reachability-v00\stage1-v01\manifests\model-contact-manifest-v01.json'
$SupportManifest = Join-Path $Repo 'experiments\fas-r1-semantic-particle-reachability-v00\stage1-v01\manifests\sensor-support-manifest-v02.json'
$Input = 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\public-tasks.jsonl'
$Output = 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-extraction-v01'
python $Sensor --snapshot-dir $Snapshot --model-manifest $ModelManifest --support-manifest $SupportManifest --input $Input --output $Output --device auto --model-dtype auto

The command processes every input row. Use a one-record public file and a separate output directory for smoke checks.

