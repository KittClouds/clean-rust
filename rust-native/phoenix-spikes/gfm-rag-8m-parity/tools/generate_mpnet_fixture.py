#!/usr/bin/env python3
"""Generate pinned, unnormalized MPNet ONNX parity fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from safetensors.numpy import save_file
from tokenizers import Tokenizer

MPNET_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"
ONNX_SHA256 = "74187b16d9c946fea252e120cfd7a12c5779d8b8b86838a2e4c56573c47941bd"
TEXTS = [
    "Which documents explain how relational graph inference preserves asserted truth?",
    "document contains entity",
    "inverse_document contains entity",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    args = parser.parse_args()
    if digest(args.model) != ONNX_SHA256:
        raise RuntimeError("pinned MPNet ONNX checksum mismatch")
    tokenizer = Tokenizer.from_file(str(args.tokenizer))
    tokenizer.enable_truncation(max_length=384)
    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
    rows = []
    token_ids = []
    for text in TEXTS:
        encoding = tokenizer.encode(text, add_special_tokens=True)
        ids = np.asarray([encoding.ids], dtype=np.int64)
        mask = np.asarray([encoding.attention_mask], dtype=np.int64)
        hidden = session.run(None, {"input_ids": ids, "attention_mask": mask})[0]
        pooled = (hidden * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
        rows.append(pooled[0].astype(np.float32))
        token_ids.append(encoding.ids)
    args.fixture_dir.mkdir(parents=True, exist_ok=True)
    save_file({"embeddings": np.stack(rows)}, args.fixture_dir / "mpnet-parity.safetensors")
    metadata = {
        "schema": "phoenix.gfm.mpnet-parity.v1",
        "repository": "sentence-transformers/all-mpnet-base-v2",
        "revision": MPNET_REVISION,
        "onnx_sha256": ONNX_SHA256,
        "tokenizer_sha256": digest(args.tokenizer),
        "normalize": False,
        "pooling": "mean_tokens",
        "max_length": 384,
        "texts": TEXTS,
        "token_ids": token_ids,
    }
    (args.fixture_dir / "mpnet-parity.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
