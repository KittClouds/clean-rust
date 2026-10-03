#!/usr/bin/env python3
"""Export the pinned V05 clausewise Q-terminal tensors as a compact f32 blob."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


CHECKPOINT_SHA256 = "00e1654dbd335b9bd7622b8bb65b983a20335f81f226904cc2c808f934d4838c"
TENSORS = (
    ("clause_projection.0.weight", (128, 2048)),
    ("clause_projection.0.bias", (128,)),
    ("clause_projection.1.weight", (128,)),
    ("clause_projection.1.bias", (128,)),
    ("global_projection.0.weight", (128, 2048)),
    ("global_projection.0.bias", (128,)),
    ("global_projection.1.weight", (128,)),
    ("global_projection.1.bias", (128,)),
    ("clause_head.0.weight", (128, 270)),
    ("clause_head.0.bias", (128,)),
    ("clause_head.1.weight", (128,)),
    ("clause_head.1.bias", (128,)),
    ("clause_head.3.weight", (64, 128)),
    ("clause_head.3.bias", (64,)),
    ("clause_head.5.weight", (1, 64)),
    ("clause_head.5.bias", (1,)),
)


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def export(checkpoint: Path, output: Path) -> dict[str, Any]:
    checkpoint = checkpoint.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite Q-terminal export {output}")
    checkpoint_hash, checkpoint_bytes = sha256_file(checkpoint)
    if checkpoint_hash != CHECKPOINT_SHA256:
        raise ValueError("V05 Q-terminal checkpoint differs from the pinned V258 bytes")

    import torch

    loaded = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if loaded.get("schema") != "R1_QTERMINAL_CHECKPOINT_V05_V02":
        raise ValueError("unexpected V05 Q-terminal checkpoint schema")
    state = loaded.get("state_dict")
    if not isinstance(state, dict):
        raise ValueError("Q-terminal checkpoint has no state_dict")

    output.mkdir(parents=True)
    binary_path = output / "qterminal-v05-v02-f32le.bin"
    fields = []
    offset = 0
    with binary_path.open("xb") as stream:
        for name, shape in TENSORS:
            tensor = state.get(name)
            if tensor is None or tuple(tensor.shape) != shape or tensor.dtype != torch.float32:
                raise ValueError(f"Q-terminal tensor {name} has an unexpected shape or dtype")
            values = np.asarray(tensor.contiguous().numpy(), dtype="<f4")
            if not np.isfinite(values).all():
                raise ValueError(f"Q-terminal tensor {name} contains non-finite values")
            payload = values.tobytes(order="C")
            count = int(values.size)
            fields.append({"name": name, "shape": list(shape), "offset_f32": offset, "count_f32": count})
            stream.write(payload)
            offset += count

    weights_hash, weights_bytes = sha256_file(binary_path)
    manifest = {
        "schema": "R1_QTERMINAL_DELTA_V05_WEIGHTS_V01",
        "status": "QTERMINAL_V05_WEIGHTS_EXPORTED",
        "checkpoint": {"path": str(checkpoint), "sha256": checkpoint_hash, "bytes": checkpoint_bytes},
        "binary": {"path": str(binary_path), "sha256": weights_hash, "bytes": weights_bytes},
        "architecture": {"hidden_dim": 2048, "projection_dim": 128, "head_hidden_dim": 64,
                         "max_roles": 6, "layer_norm_epsilon": 1e-5,
                         "gelu": "libm-f64-erf-v01", "dtype": "float32-le",
                         "endianness": "little"},
        "fields": fields,
        "float32_values": offset,
        "qualification_targets_read": False,
    }
    manifest_path = output / "qterminal-v05-v02-weights-manifest-v01.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n",
                             encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = export(args.checkpoint, args.output)
    print(f"QTERMINAL_V05_WEIGHTS_EXPORTED bytes={manifest['binary']['bytes']} output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
