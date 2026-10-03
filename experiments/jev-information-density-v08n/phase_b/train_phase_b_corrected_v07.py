"""Authorized runner composing each validated primary row with its metadata."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
AUTH = PHASE / "phase-b-authorization-event-v01.json"
TRAINER_PATH = PHASE / "train_phase_b_v01.py"
CORRECTION = PHASE / "phase-b-implementation-correction-v07.json"
PARENT_CORRECTION = PHASE / "phase-b-implementation-correction-v06.json"
PARENT_ENTRYPOINT = PHASE / "train_phase_b_corrected_v06.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_v06() -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08n_corrected_v06_parent", PARENT_ENTRYPOINT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load sealed v06 correction parent")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_chain(parent: Any) -> tuple[dict[str, Any], list[Path]]:
    receipt = read_json(CORRECTION)
    if receipt.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("v07 correction is not sealed")
    if receipt.get("parent_authorization_event_sha256") != sha256_file(AUTH):
        raise RuntimeError("v07 authorization parent mismatch")
    if receipt.get("parent_correction_receipt_sha256") != sha256_file(PARENT_CORRECTION):
        raise RuntimeError("v07 correction does not bind v06 receipt")
    if receipt.get("parent_entrypoint_sha256") != sha256_file(PARENT_ENTRYPOINT):
        raise RuntimeError("v07 correction does not bind v06 entrypoint")
    if receipt.get("corrected_entrypoint_sha256") != sha256_file(Path(__file__)):
        raise RuntimeError("v07 entrypoint hash mismatch")
    if receipt.get("frozen_trainer_sha256") != sha256_file(TRAINER_PATH):
        raise RuntimeError("on-disk frozen trainer changed")
    if receipt.get("correction_verifier_sha256") != sha256_file(PHASE / "verify_phase_b_correction_v07.py"):
        raise RuntimeError("v07 verifier hash mismatch")
    if receipt.get("correction_test_sha256") != sha256_file(PHASE / "tests/test_v08n_phase_b_correction_v07.py"):
        raise RuntimeError("v07 test hash mismatch")
    _, paths = parent.verify_chain(parent.load_v05())
    paths.append(CORRECTION)
    if paths[-2] != PARENT_CORRECTION:
        raise RuntimeError("v07 correction chain order mismatch")
    return receipt, paths


def bind_primary_rows(primary: list[dict[str, Any]], arm_rows: list[dict[str, Any]], require: Any) -> list[dict[str, Any]]:
    if len(arm_rows) < len(primary):
        raise RuntimeError("arm primary prefix is shorter than the common occurrence stream")
    output = []
    fields = ("occurrence_index", "group_id", "feature_scope_index", "target_hash", "candidate_order_hash", "candidate_semantic_ids")
    for index, (common, materialized) in enumerate(zip(primary, arm_rows[:len(primary)])):
        for field in fields:
            require(materialized.get(field) == common.get(field), f"primary {field} mismatch at {index}")
        require(materialized.get("source_episode_id") == common.get("episode_id"), f"primary source episode mismatch at {index}")
        enriched = dict(materialized)
        enriched["role"] = common["role"]
        enriched["neighborhood_id"] = common["neighborhood_id"]
        output.append(enriched)
    return output


def install_training_adapter(
    trainer: Any, parent_v04: Any, parent_v05: Any, parent_v03: Any,
    parent_v02: Any, primary_validator: Any,
) -> None:
    frozen_train_one = trainer.train_one

    def train_one(contract: dict[str, Any], loss_components: Any, probe: Any, device: str,
                  seed: int, arm: str, initial_state: dict[str, Any], state_features: Any,
                  candidate_features: Any, primary: list[dict[str, Any]],
                  schedule_rows: list[dict[str, Any]], arm_rows: list[dict[str, Any]]) -> dict[str, Any]:
        enriched = primary_validator(primary, arm_rows, trainer.require)
        return frozen_train_one(
            contract, loss_components, probe, device, seed, arm, initial_state,
            state_features, candidate_features, enriched, schedule_rows, arm_rows,
        )

    trainer.prepare_event = parent_v04.prepare_event
    parent_v05.install_cache_adapter(trainer, parent_v02)
    parent_v03.runtime_device_mapping(trainer)
    trainer.train_one = train_one


def install_receipt_writer(trainer: Any, receipt: dict[str, Any], paths: list[Path]) -> list[str]:
    entries = [{"path": str(path.resolve()), "sha256": sha256_file(path), "bytes": path.stat().st_size,
                "purpose": "implementation correction ancestry and execution binding"} for path in paths]
    hashes = [entry["sha256"] for entry in entries]
    failure = read_json(PHASE / "phase-b-implementation-correction-v04.json")["failed_attempt_forensic"]
    base_write = trainer.write_json

    def write(path: Path, value: Any) -> None:
        if isinstance(value, dict) and path.name in {"run-config.json", "run-integrity.json"}:
            value.update({
                "implementation_correction_receipt_sha256": hashes[-1],
                "implementation_correction_chain_sha256": hashes,
                "corrected_entrypoint_sha256": receipt["corrected_entrypoint_sha256"],
                "contract_device_identity": "NVIDIA GeForce RTX 3080",
                "runtime_device_locator": "cuda:0",
            })
        if isinstance(value, dict) and path.name == "checkpoint-hash-tree.json":
            value["entries"].extend(entries)
            value["entry_count"] = len(value["entries"])
        if isinstance(value, dict) and path.name == "training-seal-manifest.json":
            value["hash_tree_entries"].extend(entries)
            value.update({
                "implementation_correction_receipt_sha256": hashes[-1],
                "implementation_correction_chain_sha256": hashes,
                "corrected_entrypoint_sha256": receipt["corrected_entrypoint_sha256"],
                "contract_device_identity": "NVIDIA GeForce RTX 3080",
                "runtime_device_locator": "cuda:0",
                "failed_pretraining_attempts": [failure],
                "pretraining_implementation_failures": [read_json(item).get("observed_failure", {}) for item in paths],
            })
        base_write(path, value)

    trainer.write_json = write
    return hashes


def run(validate_only: bool = False) -> int:
    parent = load_v06()
    receipt, paths = verify_chain(parent)
    allowed = {"feature-cache", "failed-attempts", "head-templates", "attempts"}
    if {p.name for p in RUN.iterdir() if p.is_dir()} - allowed:
        raise RuntimeError("unexpected Phase-B run-root output exists")
    if any((RUN / name).exists() for name in ("runs", "execution-order.json", "checkpoint-hash-tree.json", "training-seal-manifest.json")):
        raise RuntimeError("final training outputs already exist")

    parent_v05 = parent.load_v05()
    parent_v04 = parent_v05.load_v04()
    parent_v03 = parent_v04.load_parent_module()
    parent_v02 = parent_v03.load_parent_module()
    trainer = parent_v02.load_trainer()
    install_training_adapter(trainer, parent_v04, parent_v05, parent_v03, parent_v02, bind_primary_rows)
    hashes = install_receipt_writer(trainer, receipt, paths)
    if validate_only:
        contract, _analysis, _probe, _components = trainer.frozen_bindings()
        trainer.verify_runtime(contract)
        state, candidates, primary, schedule, arms = trainer.verify_inputs(contract)
        trainer.validate_schedule(primary, schedule, arms)
        counts = {}
        for arm, rows in arms.items():
            enriched = bind_primary_rows(primary, rows, trainer.require)
            for row in enriched:
                trainer.prepare_event(row)
            for row in rows[10_000:]:
                trainer.prepare_event(row)
            counts[arm] = len(enriched)
        result = {
            "status": "CORRECTED_PHASE_B_INPUT_PREFLIGHT_PASS",
            "implementation_correction_chain_sha256": hashes,
            "primary_occurrences": len(primary),
            "enriched_primary_rows_validated_by_arm": counts,
            "schedule_rows": len(schedule),
            "arm_rows": {arm: len(rows) for arm, rows in arms.items()},
            "state_tensor_shape": list(state.shape),
            "candidate_tensor_shape": list(candidates.shape),
            "runtime_device_locator": contract["runtime_environment"]["device"],
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
