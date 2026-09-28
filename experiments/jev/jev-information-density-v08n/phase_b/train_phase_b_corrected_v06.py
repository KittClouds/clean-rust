"""Authorized Phase-B runner with the v01-v06 implementation chain.

The corrected caller supplies each arm's already-validated enriched primary
prefix to the frozen training kernel. It is a view of the same occurrence IDs,
targets and candidate order, not a new or reordered training stream.
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
TRAINER_PATH = PHASE / "train_phase_b_v01.py"
CORRECTION = PHASE / "phase-b-implementation-correction-v06.json"
PARENT_ENTRYPOINT = PHASE / "train_phase_b_corrected_v05.py"
PARENT_CORRECTION = PHASE / "phase-b-implementation-correction-v05.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_v05() -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08n_corrected_v05_parent", PARENT_ENTRYPOINT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load sealed v05 correction parent")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_chain(parent: Any) -> tuple[dict[str, Any], list[Path]]:
    receipt = read_json(CORRECTION)
    if receipt.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("v06 correction receipt is not sealed")
    if receipt.get("parent_authorization_event_sha256") != sha256_file(AUTH):
        raise RuntimeError("v06 authorization parent mismatch")
    if receipt.get("parent_correction_receipt_sha256") != sha256_file(PARENT_CORRECTION):
        raise RuntimeError("v06 correction does not bind v05 receipt")
    if receipt.get("parent_entrypoint_sha256") != sha256_file(PARENT_ENTRYPOINT):
        raise RuntimeError("v06 correction does not bind v05 entrypoint")
    if receipt.get("corrected_entrypoint_sha256") != sha256_file(Path(__file__)):
        raise RuntimeError("v06 entrypoint hash mismatch")
    if receipt.get("frozen_trainer_sha256") != sha256_file(TRAINER_PATH):
        raise RuntimeError("authorized trainer source changed")
    if receipt.get("correction_verifier_sha256") != sha256_file(PHASE / "verify_phase_b_correction_v06.py"):
        raise RuntimeError("v06 verifier hash mismatch")
    if receipt.get("correction_test_sha256") != sha256_file(PHASE / "tests/test_v08n_phase_b_correction_v06.py"):
        raise RuntimeError("v06 test hash mismatch")
    _, paths = parent.verify_chain(parent.load_v04())
    paths.append(CORRECTION)
    if paths[-2] != PARENT_CORRECTION:
        raise RuntimeError("v06 correction chain order mismatch")
    return receipt, paths


def validate_primary_binding(primary: list[dict[str, Any]], arm_rows: list[dict[str, Any]], require: Any) -> list[dict[str, Any]]:
    if len(arm_rows) < len(primary):
        raise RuntimeError("arm manifest is shorter than the common primary occurrence stream")
    enriched = arm_rows[:len(primary)]
    identity_fields = (
        "occurrence_index", "group_id", "neighborhood_id", "role", "source_episode_id", "feature_scope_index",
        "target_hash", "candidate_order_hash", "candidate_semantic_ids",
    )
    for index, (common, materialized) in enumerate(zip(primary, enriched)):
        for field in identity_fields:
            common_field = "episode_id" if field == "source_episode_id" else field
            if field == "source_episode_id":
                require(materialized.get(field) == common.get("episode_id"), f"primary source-episode mismatch at {index}")
            else:
                require(materialized.get(field) == common.get(common_field), f"primary {field} mismatch at {index}")
    return enriched


def install_primary_binding(trainer: Any) -> None:
    frozen_train_one = trainer.train_one

    def train_one_with_materialized_primary(
        contract: dict[str, Any], loss_components: Any, probe: Any, device: str,
        seed: int, arm: str, initial_state: dict[str, Any], state_features: Any,
        candidate_features: Any, primary: list[dict[str, Any]],
        schedule_rows: list[dict[str, Any]], arm_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        enriched = validate_primary_binding(primary, arm_rows, trainer.require)
        return frozen_train_one(
            contract, loss_components, probe, device, seed, arm, initial_state,
            state_features, candidate_features, enriched, schedule_rows, arm_rows,
        )

    trainer.train_one = train_one_with_materialized_primary


def install_receipt_writer(trainer: Any, receipt: dict[str, Any], paths: list[Path]) -> list[str]:
    entries = [{
        "path": str(path.resolve()), "sha256": sha256_file(path),
        "bytes": path.stat().st_size, "purpose": "implementation correction ancestry and execution binding",
    } for path in paths]
    hashes = [entry["sha256"] for entry in entries]
    failed_attempt = read_json(PHASE / "phase-b-implementation-correction-v04.json")["failed_attempt_forensic"]
    base_write = trainer.write_json

    def write(path: Path, value: Any) -> None:
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
            value["failed_pretraining_attempts"] = [failed_attempt]
            value["pretraining_implementation_failures"] = [
                read_json(item).get("observed_failure", {}) for item in paths
            ]
        base_write(path, value)

    trainer.write_json = write
    return hashes


def run(validate_only: bool = False) -> int:
    parent = load_v05()
    receipt, paths = verify_chain(parent)
    allowed = {"feature-cache", "failed-attempts", "head-templates", "attempts"}
    existing_dirs = {path.name for path in RUN.iterdir() if path.is_dir()}
    if existing_dirs - allowed:
        raise RuntimeError(f"unexpected run-root artifact before v06: {sorted(existing_dirs - allowed)}")
    if any((RUN / name).exists() for name in ("runs", "execution-order.json", "checkpoint-hash-tree.json", "training-seal-manifest.json")):
        raise RuntimeError("final training artifacts exist; v06 cannot be applied retroactively")

    parent_v04 = parent.load_v04()
    parent_v03 = parent_v04.load_parent_module()
    parent_v02 = parent_v03.load_parent_module()
    trainer = parent_v02.load_trainer()
    trainer.prepare_event = parent_v04.prepare_event
    parent.install_cache_adapter(trainer, parent_v02)
    parent_v03.runtime_device_mapping(trainer)
    install_primary_binding(trainer)
    chain_hashes = install_receipt_writer(trainer, receipt, paths)

    if validate_only:
        contract, _analysis, _probe, _components = trainer.frozen_bindings()
        trainer.verify_runtime(contract)
        state, candidates, primary, schedule, arms = trainer.verify_inputs(contract)
        trainer.validate_schedule(primary, schedule, arms)
        bound_counts = {}
        for arm, rows in arms.items():
            enriched = validate_primary_binding(primary, rows, trainer.require)
            for row in enriched:
                trainer.prepare_event(row)
            for row in rows[10_000:]:
                trainer.prepare_event(row)
            bound_counts[arm] = len(enriched)
        result = {
            "status": "CORRECTED_PHASE_B_INPUT_PREFLIGHT_PASS",
            "implementation_correction_chain_sha256": chain_hashes,
            "primary_occurrences": len(primary),
            "enriched_primary_bound_by_arm": bound_counts,
            "schedule_rows": len(schedule),
            "arm_rows": {arm: len(rows) for arm, rows in arms.items()},
            "state_tensor_shape": list(state.shape),
            "candidate_tensor_shape": list(candidates.shape),
            "runtime_device_locator": contract["runtime_environment"]["device"],
            "head_initialization_during_preflight": False,
            "optimizer_steps_during_preflight": 0,
            "retained_zero_step_attempt": read_json(PHASE / "phase-b-implementation-correction-v04.json")["failed_attempt_forensic"],
            "protected_panel_opened": False,
            "newtight_access": False,
            "phoenix_access": False,
        }
        print(json.dumps(result, separators=(",", ":")))
        return 0
    return trainer.main()


if __name__ == "__main__":
    raise SystemExit(run(validate_only="--validate-only" in sys.argv[1:]))
