"""Apply a metadata-only cache-container adapter before the frozen trainer.

The sealed feature artifact stores its state tensor directly at
``features``; the frozen trainer expected the equivalent nested feature-key
view. This wrapper exposes that same tensor by reference and records this
implementation-only correction in every run/seal receipt.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
CORRECTION_PATH = PHASE / "phase-b-implementation-correction-v01.json"
TRAINER_PATH = PHASE / "train_phase_b_v01.py"
AUTH_PATH = PHASE / "phase-b-authorization-event-v01.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def adapt_state_cache(
    cache: dict[str, Any], feature_key: str, expected_shape: tuple[int, int] = (55_000, 2048)
) -> dict[str, Any]:
    """Add a dictionary view around the original tensor; never copy its data."""
    features = cache.get("features")
    if not isinstance(features, torch.Tensor):
        raise RuntimeError("sealed state cache no longer has the audited direct-tensor layout")
    if cache.get("feature_key") != feature_key:
        raise RuntimeError("sealed state cache feature key differs from the frozen contract")
    if tuple(features.shape) != expected_shape or features.dtype != torch.float32 or not features.is_contiguous():
        raise RuntimeError("sealed state cache tensor differs from its frozen shape/dtype/layout")
    return {**cache, "features": {"state": {feature_key: features}}}


def load_trainer() -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08n_frozen_trainer", TRAINER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen Phase-B trainer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run() -> int:
    correction = read_json(CORRECTION_PATH)
    event = read_json(AUTH_PATH)
    event_sha = sha256_file(AUTH_PATH)
    if correction.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("implementation correction receipt is not sealed")
    if correction.get("parent_authorization_event_sha256") != event_sha:
        raise RuntimeError("correction receipt does not descend from the active authorization")
    if correction.get("corrected_entrypoint_sha256") != sha256_file(Path(__file__)):
        raise RuntimeError("corrected entrypoint hash differs from the correction receipt")
    if correction.get("frozen_trainer_sha256") != sha256_file(TRAINER_PATH):
        raise RuntimeError("frozen trainer source changed")

    run_dirs = {path.name for path in RUN.iterdir() if path.is_dir()}
    if run_dirs - {"feature-cache", "failed-attempts"}:
        raise RuntimeError(f"head/run artifacts exist before corrected trainer entry: {sorted(run_dirs)}")
    forbidden = [RUN / name for name in ("head-templates", "runs", "attempts", "execution-order.json", "training-seal-manifest.json")]
    if any(path.exists() for path in forbidden):
        raise RuntimeError("head initialization or training artifacts exist; correction cannot be applied retroactively")

    trainer = load_trainer()
    correction_sha = sha256_file(CORRECTION_PATH)
    original_load = torch.load
    state_receipt = read_json(Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\shared-feature-cache\shared-feature-cache-receipt.json"))
    state_path = Path(state_receipt["feature_tensor"]["path"]).resolve()

    def load_with_schema_view(source: Any, *args: Any, **kwargs: Any) -> Any:
        loaded = original_load(source, *args, **kwargs)
        try:
            same_path = Path(source).resolve() == state_path
        except (TypeError, OSError):
            same_path = False
        if same_path:
            return adapt_state_cache(loaded, trainer.FEATURE_KEY)
        return loaded

    trainer.torch.load = load_with_schema_view
    base_write_json = trainer.write_json
    correction_entry = {
        "path": str(CORRECTION_PATH.resolve()),
        "sha256": correction_sha,
        "bytes": CORRECTION_PATH.stat().st_size,
        "purpose": "implementation-only cache-container adapter provenance",
    }

    def write_with_correction(path: Path, value: Any) -> None:
        if isinstance(value, dict) and path.name in {"run-config.json", "run-integrity.json"}:
            value["implementation_correction_receipt_sha256"] = correction_sha
            value["corrected_entrypoint_sha256"] = correction["corrected_entrypoint_sha256"]
        if isinstance(value, dict) and path.name == "checkpoint-hash-tree.json":
            value["entries"].append(correction_entry)
            value["entry_count"] = len(value["entries"])
        if isinstance(value, dict) and path.name == "training-seal-manifest.json":
            value["hash_tree_entries"].append(correction_entry)
            value["implementation_correction_receipt_sha256"] = correction_sha
            value["corrected_entrypoint_sha256"] = correction["corrected_entrypoint_sha256"]
        base_write_json(path, value)

    trainer.write_json = write_with_correction
    return trainer.main()


if __name__ == "__main__":
    raise SystemExit(run())
