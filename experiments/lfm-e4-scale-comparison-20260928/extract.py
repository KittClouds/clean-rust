"""Frozen V1_FINAL_POSITION extraction for the E4 scale comparison.

The input is label-free JSONL in fixed row order. A partial cache can be resumed
only at an aligned row boundary; the completed cache and input get SHA-256 seals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np


def digest(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while data := stream.read(8 << 20):
            h.update(data)
            size += len(data)
    return h.hexdigest(), size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dimension", type=int, required=True)
    parser.add_argument("--expected-rows", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    import torch
    import transformers

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA:0 is required for the frozen extraction ABI")
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    device = torch.device("cuda:0")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        args.tokenizer, use_fast=True, local_files_only=True, trust_remote_code=False
    )
    if not tokenizer.is_fast:
        raise RuntimeError("the frozen ABI requires a fast tokenizer")
    model = transformers.AutoModel.from_pretrained(
        args.model,
        local_files_only=True,
        trust_remote_code=False,
        torch_dtype=torch.float32,
    )
    model.eval().to(device)
    if model.config.hidden_size != args.dimension:
        raise RuntimeError("model dimension differs from extraction contract")
    row_bytes = args.dimension * 4
    feature_path = args.output / "V1_FINAL_POSITION.f32le"
    receipt_path = args.output / "extraction-receipt.json"
    args.output.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        raise RuntimeError("sealed extraction already exists")
    completed = feature_path.stat().st_size // row_bytes if feature_path.exists() else 0
    if feature_path.exists() and feature_path.stat().st_size != completed * row_bytes:
        raise RuntimeError("partial feature cache has an unaligned byte count")
    if completed > args.expected_rows:
        raise RuntimeError("partial feature cache exceeds declared rows")
    began = time.perf_counter()
    seen = 0
    with args.inputs.open("r", encoding="utf-8") as source, feature_path.open("ab", buffering=0) as output:
        with torch.inference_mode():
            for line in source:
                if seen < completed:
                    seen += 1
                    continue
                row = json.loads(line)
                if set(row) != {"row_id", "quartet_id", "variant_id", "input_text"}:
                    raise RuntimeError(f"unexpected model-input fields at row {seen}")
                ids = tokenizer.encode(row["input_text"], add_special_tokens=True, truncation=False)
                if not ids or len(ids) > 2048:
                    raise RuntimeError(f"invalid sequence length at row {seen}")
                tensor = torch.tensor([ids], dtype=torch.long, device=device)
                mask = torch.ones_like(tensor)
                hidden = model(
                    input_ids=tensor,
                    attention_mask=mask,
                    use_cache=False,
                    return_dict=True,
                ).last_hidden_state
                if hidden.dtype != torch.float32 or tuple(hidden.shape) != (1, len(ids), args.dimension):
                    raise RuntimeError(f"output tensor differs from V1_FINAL_POSITION at row {seen}")
                vector = hidden[0, len(ids) - 1, :].detach().contiguous().cpu().numpy()
                if not np.isfinite(vector).all():
                    raise RuntimeError(f"non-finite feature at row {seen}")
                output.write(np.asarray(vector, dtype="<f4", order="C").tobytes(order="C"))
                seen += 1
                if seen % 1000 == 0:
                    output.flush()
                    os.fsync(output.fileno())
                    print(f"{args.run_id}: {seen}/{args.expected_rows}", flush=True)
        output.flush()
        os.fsync(output.fileno())
    if seen != args.expected_rows:
        raise RuntimeError(f"row count {seen} != {args.expected_rows}")
    input_hash, input_bytes = digest(args.inputs)
    feature_hash, feature_bytes = digest(feature_path)
    if feature_bytes != seen * row_bytes:
        raise RuntimeError("feature byte count mismatch")
    torch.cuda.synchronize(device)
    receipt = {
        "schema": "phoenix.e4-scale-v1-final-position/v1",
        "run_id": args.run_id,
        "surface": "V1_FINAL_POSITION",
        "tensor": "last_hidden_state[0, final_nonpadding_token, :]",
        "dtype": "float32_le",
        "frozen_backbone": True,
        "batch_size": 1,
        "generation": False,
        "row_count": seen,
        "dimension": args.dimension,
        "input_path": str(args.inputs.resolve()),
        "input_sha256": input_hash,
        "input_bytes": input_bytes,
        "feature_path": str(feature_path.resolve()),
        "feature_sha256": feature_hash,
        "feature_bytes": feature_bytes,
        "model_path": str(args.model.resolve()),
        "tokenizer_path": str(args.tokenizer.resolve()),
        "config_sha256": digest(args.model / "config.json")[0],
        "weights_sha256": digest(args.model / "model.safetensors")[0],
        "tokenizer_json_sha256": digest(args.tokenizer / "tokenizer.json")[0],
        "extraction_seconds_this_invocation": time.perf_counter() - began,
        "gpu_peak_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
    }
    with receipt_path.open("x", encoding="utf-8") as output:
        json.dump(receipt, output, indent=2)
        output.write("\n")
    print(json.dumps({"run_id": args.run_id, "rows": seen, "feature_sha256": feature_hash}), flush=True)


if __name__ == "__main__":
    main()
