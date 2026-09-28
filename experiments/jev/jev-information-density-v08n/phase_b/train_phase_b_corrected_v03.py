"""Run authorized Phase B with receipt-bound implementation-only adapters.

The v02 parent preserves the frozen trainer source while correcting one local
declaration-order defect and adapting the sealed cache container by reference.
This v03 wrapper additionally maps the already-verified CUDA device identity
to PyTorch's ``cuda:0`` locator. The mapping is allowed only after the frozen
runtime verifier confirms that device 0's name equals the contract identity.
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
CORRECTION = PHASE / "phase-b-implementation-correction-v03.json"
CORRECTION_V02 = PHASE / "phase-b-implementation-correction-v02.json"
CORRECTION_V01 = PHASE / "phase-b-implementation-correction-v01.json"
AUTH = PHASE / "phase-b-authorization-event-v01.json"
TRAINER = PHASE / "train_phase_b_v01.py"
PARENT_ENTRYPOINT = PHASE / "train_phase_b_corrected_v02.py"
DEVICE_IDENTITY = "NVIDIA GeForce RTX 3080"
DEVICE_LOCATOR = "cuda:0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_parent_module() -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08n_corrected_v02_parent", PARENT_ENTRYPOINT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load sealed v02 implementation correction parent")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_correction_chain(parent: Any) -> tuple[dict[str, Any], list[Path]]:
    receipt = read_json(CORRECTION)
    v02 = read_json(CORRECTION_V02)
    v01 = read_json(CORRECTION_V01)
    if receipt.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("v03 implementation correction is not sealed")
    if receipt.get("parent_authorization_event_sha256") != sha256_file(AUTH):
        raise RuntimeError("v03 correction does not bind the active authorization")
    if receipt.get("parent_correction_receipt_sha256") != sha256_file(CORRECTION_V02):
        raise RuntimeError("v03 correction does not bind v02 receipt")
    if receipt.get("parent_entrypoint_sha256") != sha256_file(PARENT_ENTRYPOINT):
        raise RuntimeError("v03 correction does not bind its v02 implementation parent")
    if receipt.get("corrected_entrypoint_sha256") != sha256_file(Path(__file__)):
        raise RuntimeError("v03 corrected entrypoint hash mismatch")
    if receipt.get("frozen_trainer_sha256") != sha256_file(TRAINER):
        raise RuntimeError("on-disk authorized trainer changed")
    if v02.get("parent_correction_receipt_sha256") != sha256_file(CORRECTION_V01):
        raise RuntimeError("v02 correction parent chain mismatch")
    if v01.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED" or v02.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("an implementation correction ancestor is not sealed")
    if receipt.get("correction_verifier_sha256") != sha256_file(PHASE / "verify_phase_b_correction_v03.py"):
        raise RuntimeError("v03 correction verifier hash mismatch")
    if receipt.get("correction_test_sha256") != sha256_file(PHASE / "tests/test_v08n_phase_b_correction_v03.py"):
        raise RuntimeError("v03 correction test hash mismatch")
    parent.verify_correction_chain()
    return receipt, [CORRECTION_V01, CORRECTION_V02, CORRECTION]


def runtime_device_mapping(trainer: Any) -> None:
    frozen_verifier = trainer.verify_runtime

    def verify_then_resolve(contract: dict[str, Any]) -> None:
        frozen_verifier(contract)
        expected_identity = contract["runtime_environment"]["device"]
        actual_identity = torch.cuda.get_device_name(0)
        if expected_identity != DEVICE_IDENTITY or actual_identity != expected_identity:
            raise RuntimeError(
                f"refusing CUDA locator mapping: contract={expected_identity!r}, actual={actual_identity!r}"
            )
        contract["runtime_environment"]["device"] = DEVICE_LOCATOR

    trainer.verify_runtime = verify_then_resolve


def install_receipt_writer(trainer: Any, correction_paths: list[Path], receipt: dict[str, Any]) -> list[dict[str, Any]]:
    entries = [{
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "purpose": "implementation correction ancestry and execution binding",
    } for path in correction_paths]
    chain_hashes = [entry["sha256"] for entry in entries]
    base_write_json = trainer.write_json

    def write_with_corrections(path: Path, value: Any) -> None:
        if isinstance(value, dict) and path.name in {"run-config.json", "run-integrity.json"}:
            value["implementation_correction_receipt_sha256"] = chain_hashes[-1]
            value["implementation_correction_chain_sha256"] = chain_hashes
            value["corrected_entrypoint_sha256"] = receipt["corrected_entrypoint_sha256"]
            value["contract_device_identity"] = DEVICE_IDENTITY
            value["runtime_device_locator"] = DEVICE_LOCATOR
        if isinstance(value, dict) and path.name == "checkpoint-hash-tree.json":
            value["entries"].extend(entries)
            value["entry_count"] = len(value["entries"])
        if isinstance(value, dict) and path.name == "training-seal-manifest.json":
            value["hash_tree_entries"].extend(entries)
            value["implementation_correction_receipt_sha256"] = chain_hashes[-1]
            value["implementation_correction_chain_sha256"] = chain_hashes
            value["corrected_entrypoint_sha256"] = receipt["corrected_entrypoint_sha256"]
            value["contract_device_identity"] = DEVICE_IDENTITY
            value["runtime_device_locator"] = DEVICE_LOCATOR
        base_write_json(path, value)

    trainer.write_json = write_with_corrections
    return chain_hashes


def run(validate_only: bool = False) -> int:
    parent = load_parent_module()
    receipt, correction_paths = verify_correction_chain(parent)
    allowed_dirs = {"feature-cache", "failed-attempts"}
    run_dirs = {path.name for path in RUN.iterdir() if path.is_dir()}
    if run_dirs - allowed_dirs:
        raise RuntimeError(f"head/run artifacts exist before corrected trainer entry: {sorted(run_dirs)}")
    forbidden = [RUN / name for name in ("head-templates", "runs", "attempts", "execution-order.json", "training-seal-manifest.json")]
    if any(path.exists() for path in forbidden):
        raise RuntimeError("head initialization or training artifacts exist; correction cannot be applied retroactively")

    trainer = parent.load_trainer()
    original_load = torch.load
    shared_receipt_path = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\shared-feature-cache\shared-feature-cache-receipt.json")
    shared_receipt = read_json(shared_receipt_path)
    shared_tensor_path = Path(shared_receipt["feature_tensor"]["path"]).resolve()

    def load_with_schema_view(source: Any, *args: Any, **kwargs: Any) -> Any:
        loaded = original_load(source, *args, **kwargs)
        try:
            is_shared_tensor = Path(source).resolve() == shared_tensor_path
        except (TypeError, OSError):
            is_shared_tensor = False
        return parent.adapt_state_cache(loaded, trainer.FEATURE_KEY) if is_shared_tensor else loaded

    trainer.torch.load = load_with_schema_view
    runtime_device_mapping(trainer)
    chain_hashes = install_receipt_writer(trainer, correction_paths, receipt)

    if validate_only:
        contract, _analysis, _probe, _components = trainer.frozen_bindings()
        trainer.verify_runtime(contract)
        state, candidates, primary, schedule, arm_rows = trainer.verify_inputs(contract)
        trainer.validate_schedule(primary, schedule, arm_rows)
        result = {
            "status": "CORRECTED_PHASE_B_INPUT_PREFLIGHT_PASS",
            "authorization_event_sha256": sha256_file(AUTH),
            "implementation_correction_chain_sha256": chain_hashes,
            "primary_occurrences": len(primary),
            "schedule_rows": len(schedule),
            "arm_rows": {arm: len(rows) for arm, rows in arm_rows.items()},
            "state_tensor_shape": list(state.shape),
            "candidate_tensor_shape": list(candidates.shape),
            "contract_device_identity": DEVICE_IDENTITY,
            "resolved_runtime_device_locator": contract["runtime_environment"]["device"],
            "head_initialization": False,
            "optimizer_steps": 0,
            "protected_panel_opened": False,
            "newtight_access": False,
            "phoenix_access": False,
        }
        print(json.dumps(result, separators=(",", ":")))
        return 0
    return trainer.main()


if __name__ == "__main__":
    raise SystemExit(run(validate_only="--validate-only" in sys.argv[1:]))
