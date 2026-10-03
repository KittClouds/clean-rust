"""Require a clean-process full feature re-extraction to match, then seal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import torch


RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
PRIMARY = RUN / "features-v01"
REPEAT = RUN / "feature-repeat-v01"
TENSORS = {
    "r3-panel-state-features.pt": (4_000, 2048),
    "r3-candidate-features.pt": (16, 2048),
    "reverse-sham-state-features.pt": (2_500, 2048),
}
MANIFESTS = ("r3-panel-feature-manifest.jsonl", "candidate-feature-manifest.jsonl", "reverse-sham-feature-manifest.jsonl")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_sha(value: torch.Tensor) -> str:
    return sha_bytes(value.detach().cpu().contiguous().numpy().tobytes(order="C"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def load_and_validate(root: Path) -> tuple[dict[str, torch.Tensor], dict[str, Any]]:
    receipt = read_json(root / "feature-extraction-receipt.json")
    require(receipt.get("status") == "R3_V03_FEATURE_EXTRACTION_PASS" and receipt.get("targets_read") is False,
            f"feature extraction receipt invalid: {root.name}")
    tensors: dict[str, torch.Tensor] = {}
    for name, shape in TENSORS.items():
        path = root / name
        require(path.is_file() and sha_file(path) == receipt["features"][name]["sha256"],
                f"feature tensor file binding mismatch: {root.name}/{name}")
        data = torch.load(path, map_location="cpu", weights_only=True)
        tensor = data["features"]
        require(tuple(tensor.shape) == shape and tensor.dtype == torch.float32 and tensor.is_contiguous()
                and bool(torch.isfinite(tensor).all()), f"feature tensor invariant failed: {root.name}/{name}")
        require(tensor_sha(tensor) == receipt["features"][name]["tensor_sha256"]
                and list(tensor.shape) == receipt["features"][name]["shape"],
                f"feature tensor content binding mismatch: {root.name}/{name}")
        tensors[name] = tensor
    for name in MANIFESTS:
        require(sha_file(root / name) == receipt["manifests"][name], f"feature manifest hash mismatch: {root.name}/{name}")
    return tensors, receipt


def main() -> int:
    require(PRIMARY.is_dir() and REPEAT.is_dir(), "primary/repeat feature extraction directory missing")
    primary, primary_receipt = load_and_validate(PRIMARY)
    repeat, repeat_receipt = load_and_validate(REPEAT)
    require(primary_receipt["panel_seal"] == repeat_receipt["panel_seal"], "repeat extraction used a different panel seal")
    require(primary_receipt["runtime"] == repeat_receipt["runtime"], "repeat extraction runtime differs")
    require(primary_receipt["model_parameter_sha256_before"] == repeat_receipt["model_parameter_sha256_before"]
            == primary_receipt["model_parameter_sha256_after"] == repeat_receipt["model_parameter_sha256_after"],
            "repeat LFM parameter identity differs")
    errors = {name: float((primary[name] - repeat[name]).abs().max().item()) for name in TENSORS}
    maximum = max(errors.values())
    require(maximum <= 1e-5, f"independent clean-process feature repeat exceeds tolerance: {maximum}")
    repeat_receipt_out = {
        "status": "R3_V03_INDEPENDENT_FEATURE_REPEAT_PASS",
        "primary_receipt_sha256": sha_file(PRIMARY / "feature-extraction-receipt.json"),
        "repeat_receipt_sha256": sha_file(REPEAT / "feature-extraction-receipt.json"),
        "primary_tensor_sha256": {name: tensor_sha(value) for name, value in primary.items()},
        "repeat_tensor_sha256": {name: tensor_sha(value) for name, value in repeat.items()},
        "max_abs_error_by_tensor": errors, "max_abs_error": maximum, "tolerance": 1e-5,
        "clean_processes": 2, "head_initialized": False, "training": False, "inference": False,
        "targets_read": False,
    }
    repeat_path = PRIMARY / "feature-repeat-receipt.json"
    require(not repeat_path.exists(), "repeat receipt already exists")
    write_json(repeat_path, repeat_receipt_out)
    names = [*TENSORS, *MANIFESTS, "feature-extraction-receipt.json", "feature-repeat-receipt.json"]
    entries = [{"path": name, "bytes": (PRIMARY / name).stat().st_size, "sha256": sha_file(PRIMARY / name)} for name in names]
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(entries, key=lambda item: item["path"]))
    seal = {
        "schema": "jev-r3-feature-cache-seal-v01", "status": "R3_V03_FEATURE_CACHE_SEALED_TRAINING_PENDING",
        "entries": entries, "entry_count": len(entries), "entries_root_sha256": sha_bytes(body.encode()),
        "panel_seal_sha256": primary_receipt["panel_seal"], "repeat_receipt_sha256": sha_file(repeat_path),
        "max_abs_error": maximum, "tolerance": 1e-5, "targets_read": False,
        "head_initialized": False, "training": False, "evaluation": False,
    }
    seal_path = PRIMARY / "feature-cache-seal-v01.json"
    require(not seal_path.exists(), "feature cache seal already exists")
    write_json(seal_path, seal)
    print(json.dumps({"status": seal["status"], "feature_cache_root_sha256": seal["entries_root_sha256"],
        "max_abs_error": maximum, "tolerance": 1e-5, "tensor_errors": errors}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
