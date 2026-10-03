from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import torch


MODEL_ID = "LiquidAI/LFM2.5-1.2B-Base"
REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
EVENTS = 106496
QUARTETS = 26624
DIMENSION = 2048
LAYERS = tuple(range(1, 17))
SURFACES = ("M", "F")
PAIR_ORDER = ((0, 1), (0, 2), (1, 2))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = Path(r"D:\codex-runs\fas-s09-depthwise-decision-subspace-emergence-v07")
SOURCE_RUN_ROOT = Path(r"D:\codex-runs\fas-s09-depthwise-decision-subspace-emergence-v02")
FEATURE_ROOT = SOURCE_RUN_ROOT / "feature-cache-v02"
MODEL_ROOT = SOURCE_RUN_ROOT / "model-assets" / "snapshot"
S01_ROOT = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography")
S01_2_ROOT = S01_ROOT / "s01-2-feature-geometry-v01"
S01_3_ROOT = S01_ROOT / "s01-3-linear-accessibility-v01"
S08_ROOT = Path(r"D:\codex-runs\fas-s08-exact-decision-surface-attribution-v02")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def sha256_file(path: Path, chunk_bytes: int = 8 * 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def entry_for(path: Path, base: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    return {"path": path.relative_to(base).as_posix(), "bytes": size, "sha256": digest}


def tree_root(entries: list[dict[str, Any]]) -> str:
    ordered = sorted(entries, key=lambda item: item["path"])
    payload = "".join(f"{e['path']}\t{e['bytes']}\t{e['sha256']}\n" for e in ordered)
    return sha256_bytes(payload.encode("utf-8"))


def verify_tree(base: Path, seal_path: Path, expected_root: str) -> dict[str, Any]:
    seal = read_json(seal_path)
    if seal.get("root_sha256") != expected_root:
        raise RuntimeError(f"parent seal declares the wrong root: {seal_path}")
    actual = [entry_for(base.joinpath(*item["path"].split("/")), base) for item in seal["entries"]]
    actual.sort(key=lambda item: item["path"])
    expected = sorted(seal["entries"], key=lambda item: item["path"])
    if actual != expected or tree_root(actual) != expected_root:
        raise RuntimeError(f"parent tree failed verification: {seal_path}")
    return {"root_sha256": expected_root, "entry_count": len(actual), "entries_verified": actual}


def configure_determinism() -> torch.device:
    if torch.__version__ != "2.11.0+cu128" or not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("S09 frozen CUDA runtime is unavailable or changed")
    if torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise RuntimeError("S09 CUDA device identity changed")
    torch.set_num_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_float32_matmul_precision("highest")
    torch.use_deterministic_algorithms(True)
    torch.cuda.manual_seed_all(0)
    return torch.device("cuda:0")


def tensor_state_identity(model: torch.nn.Module) -> dict[str, Any]:
    digest = hashlib.sha256()
    tensors = elements = byte_count = 0
    for name, tensor in sorted(model.state_dict().items(), key=lambda item: item[0]):
        if not isinstance(tensor, torch.Tensor):
            raise RuntimeError(f"non-tensor model state entry: {name}")
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(str(tensor.dtype).encode("ascii") + b"\0")
        digest.update(canonical_json(list(tensor.shape)) + b"\0")
        cpu = tensor.detach().contiguous().reshape(-1).view(torch.uint8).to(device="cpu").numpy()
        view = memoryview(cpu).cast("B")
        for offset in range(0, len(view), 8 * 1024 * 1024):
            chunk = view[offset:offset + 8 * 1024 * 1024]
            digest.update(chunk)
            byte_count += len(chunk)
        tensors += 1
        elements += tensor.numel()
        del cpu, view
    return {"sha256": digest.hexdigest(), "state_tensor_count": tensors, "state_element_count": elements, "serialized_state_bytes": byte_count}


def token_ids_sha256(token_ids: list[int]) -> str:
    import struct

    return hashlib.sha256(struct.pack(f"<{len(token_ids)}I", *token_ids)).hexdigest()
