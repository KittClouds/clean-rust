"""Run authorized Phase B with a fully bound implementation correction chain.

v05 composes the already audited cache-view, source-order, CUDA-locator, and
event-identity fixes. It explicitly reinstalls the no-copy state-cache adapter
when loading the corrected trainer, then performs an optional no-head preflight.
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
AUTH = PHASE / "phase-b-authorization-event-v01.json"
TRAINER = PHASE / "train_phase_b_v01.py"
CORRECTION = PHASE / "phase-b-implementation-correction-v05.json"
CORRECTION_V04 = PHASE / "phase-b-implementation-correction-v04.json"
PARENT_ENTRYPOINT = PHASE / "train_phase_b_corrected_v04.py"
SHARED_RECEIPT = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\shared-feature-cache\shared-feature-cache-receipt.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_v04() -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08n_corrected_v04_parent", PARENT_ENTRYPOINT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load sealed v04 correction parent")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_chain(parent: Any) -> tuple[dict[str, Any], list[Path]]:
    receipt = read_json(CORRECTION)
    parent_receipt = read_json(CORRECTION_V04)
    event_sha = sha256_file(AUTH)
    if receipt.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("v05 correction receipt is not sealed")
    if receipt.get("parent_authorization_event_sha256") != event_sha:
        raise RuntimeError("v05 authorization parent mismatch")
    if receipt.get("parent_correction_receipt_sha256") != sha256_file(CORRECTION_V04):
        raise RuntimeError("v05 does not bind the v04 correction receipt")
    if receipt.get("parent_entrypoint_sha256") != sha256_file(PARENT_ENTRYPOINT):
        raise RuntimeError("v05 does not bind the v04 entrypoint")
    if receipt.get("corrected_entrypoint_sha256") != sha256_file(Path(__file__)):
        raise RuntimeError("v05 entrypoint hash mismatch")
    if receipt.get("frozen_trainer_sha256") != sha256_file(TRAINER):
        raise RuntimeError("frozen trainer source changed")
    if receipt.get("correction_verifier_sha256") != sha256_file(PHASE / "verify_phase_b_correction_v05.py"):
        raise RuntimeError("v05 verifier hash mismatch")
    if receipt.get("correction_test_sha256") != sha256_file(PHASE / "tests/test_v08n_phase_b_correction_v05.py"):
        raise RuntimeError("v05 test hash mismatch")
    if parent_receipt.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("v04 parent receipt is not sealed")
    _, paths = parent.verify_chain(parent.load_parent_module())
    paths.append(CORRECTION)
    if paths[-2] != CORRECTION_V04:
        raise RuntimeError("v05 correction chain order mismatch")
    return receipt, paths


def verify_retained_attempt(parent: Any) -> dict[str, Any]:
    return parent.failed_attempt_forensic()


def install_receipts(trainer: Any, receipt: dict[str, Any], correction_paths: list[Path], parent: Any) -> list[str]:
    entries = [{
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "purpose": "implementation correction ancestry and execution binding",
    } for path in correction_paths]
    hashes = [entry["sha256"] for entry in entries]
    original_writer = trainer.write_json

    def write_with_receipts(path: Path, value: Any) -> None:
        if isinstance(value, dict) and path.name in {"run-config.json", "run-integrity.json"}:
            value["implementation_correction_receipt_sha256"] = hashes[-1]
            value["implementation_correction_chain_sha256"] = hashes
            value["corrected_entrypoint_sha256"] = receipt["corrected_entrypoint_sha256"]
            value["contract_device_identity"] = "NVIDIA GeForce RTX 3080"
            value["runtime_device_locator"] = "cuda:0"
        if isinstance(value, dict) and path.name == "checkpoint-hash-tree.json":
            value["entries"].extend(entries)
            value["entry_count"] = len(value["entries"])
        if isinstance(value, dict) and path.name == "training-seal-manifest.json":
            value["hash_tree_entries"].extend(entries)
            value["implementation_correction_receipt_sha256"] = hashes[-1]
            value["implementation_correction_chain_sha256"] = hashes
            value["corrected_entrypoint_sha256"] = receipt["corrected_entrypoint_sha256"]
            value["contract_device_identity"] = "NVIDIA GeForce RTX 3080"
            value["runtime_device_locator"] = "cuda:0"
            value["failed_pretraining_attempts"] = [verify_retained_attempt(parent)]
            value["pretraining_implementation_failures"] = [
                read_json(path).get("observed_failure", {}) for path in correction_paths
            ]
        original_writer(path, value)

    trainer.write_json = write_with_receipts
    return hashes


def install_cache_adapter(trainer: Any, parent_v02: Any) -> None:
    receipt = read_json(SHARED_RECEIPT)
    tensor_path = Path(receipt["feature_tensor"]["path"]).resolve()
    original_load = torch.load

    def load_with_adapter(source: Any, *args: Any, **kwargs: Any) -> Any:
        loaded = original_load(source, *args, **kwargs)
        try:
            is_state_cache = Path(source).resolve() == tensor_path
        except (TypeError, OSError):
            is_state_cache = False
        return parent_v02.adapt_state_cache(loaded, trainer.FEATURE_KEY) if is_state_cache else loaded

    trainer.torch.load = load_with_adapter


def run(validate_only: bool = False) -> int:
    parent_v04 = load_v04()
    receipt, correction_paths = verify_chain(parent_v04)
    retained = verify_retained_attempt(parent_v04)
    actual_dirs = {path.name for path in RUN.iterdir() if path.is_dir()}
    allowed_dirs = {"feature-cache", "failed-attempts", "head-templates", "attempts"}
    if actual_dirs - allowed_dirs:
        raise RuntimeError(f"unexpected run-root artifacts before v05 entry: {sorted(actual_dirs - allowed_dirs)}")
    forbidden = [RUN / name for name in ("runs", "execution-order.json", "checkpoint-hash-tree.json", "training-seal-manifest.json")]
    if any(path.exists() for path in forbidden):
        raise RuntimeError("final run artifacts exist; v05 cannot be applied retroactively")

    parent_v03 = parent_v04.load_parent_module()
    parent_v02 = parent_v03.load_parent_module()
    trainer = parent_v02.load_trainer()
    trainer.prepare_event = parent_v04.prepare_event
    install_cache_adapter(trainer, parent_v02)
    parent_v03.runtime_device_mapping(trainer)
    chain_hashes = install_receipts(trainer, receipt, correction_paths, parent_v04)

    if validate_only:
        contract, _analysis, _probe, _components = trainer.frozen_bindings()
        trainer.verify_runtime(contract)
        state, candidates, primary, schedule, arms = trainer.verify_inputs(contract)
        trainer.validate_schedule(primary, schedule, arms)
        primary_count = sum(1 for row in primary if trainer.prepare_event(row))
        auxiliary_counts = {arm: sum(1 for row in rows[10_000:] if trainer.prepare_event(row)) for arm, rows in arms.items()}
        result = {
            "status": "CORRECTED_PHASE_B_INPUT_PREFLIGHT_PASS",
            "implementation_correction_chain_sha256": chain_hashes,
            "primary_occurrences": len(primary),
            "primary_events_materialized_without_training": primary_count,
            "schedule_rows": len(schedule),
            "arm_rows": {arm: len(rows) for arm, rows in arms.items()},
            "auxiliary_events_materialized_without_training": auxiliary_counts,
            "state_tensor_shape": list(state.shape),
            "candidate_tensor_shape": list(candidates.shape),
            "runtime_device_locator": contract["runtime_environment"]["device"],
            "retained_zero_step_attempt": retained,
            "head_initialization_during_preflight": False,
            "optimizer_steps_during_preflight": 0,
            "protected_panel_opened": False,
            "newtight_access": False,
            "phoenix_access": False,
        }
        print(json.dumps(result, separators=(",", ":")))
        return 0
    return trainer.main()


if __name__ == "__main__":
    raise SystemExit(run(validate_only="--validate-only" in sys.argv[1:]))
