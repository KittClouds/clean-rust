"""Authorized Phase-B entrypoint with four sealed implementation corrections.

v01 adapts the unchanged state tensor's container view; v02 relocates a local
catalog declaration in memory; v03 maps the verified GPU identity to its
PyTorch locator; v04 fixes eager evaluation of a dict.get default in the
event-preparation helper. No bank, target, schedule, loss, or model changes.
"""

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
CORRECTION = PHASE / "phase-b-implementation-correction-v04.json"
CORRECTION_V03 = PHASE / "phase-b-implementation-correction-v03.json"
CORRECTION_V02 = PHASE / "phase-b-implementation-correction-v02.json"
CORRECTION_V01 = PHASE / "phase-b-implementation-correction-v01.json"
AUTH = PHASE / "phase-b-authorization-event-v01.json"
TRAINER = PHASE / "train_phase_b_v01.py"
PARENT_ENTRYPOINT = PHASE / "train_phase_b_corrected_v03.py"
FAILED_ATTEMPT = RUN / "attempts/seed-20260927/B-DUP/attempt-95b914e81caf48b595bedb6f9a203176"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_parent_module() -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08n_corrected_v03_parent", PARENT_ENTRYPOINT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load sealed v03 implementation correction parent")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def prepare_event(row: dict[str, Any]) -> dict[str, Any]:
    """Resolve identity without eagerly evaluating the unused dict branch."""
    group_id = row["group_id"] if "group_id" in row else row["source_episode_id"]
    return {
        "group_id": group_id,
        "state_idx": row["feature_scope_index"],
        "candidate_indices": {"name_definition": row["candidate_indices"]},
        "gold": row["target"],
        "kind": "choice",
        "probability_source": "exact_generative_posterior",
    }


def verify_chain(parent: Any) -> tuple[dict[str, Any], list[Path]]:
    receipt = read_json(CORRECTION)
    if receipt.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("v04 correction is not sealed")
    if receipt.get("parent_authorization_event_sha256") != sha256_file(AUTH):
        raise RuntimeError("v04 correction authorization parent mismatch")
    if receipt.get("parent_correction_receipt_sha256") != sha256_file(CORRECTION_V03):
        raise RuntimeError("v04 correction does not bind v03 receipt")
    if receipt.get("parent_entrypoint_sha256") != sha256_file(PARENT_ENTRYPOINT):
        raise RuntimeError("v04 correction does not bind v03 entrypoint")
    if receipt.get("corrected_entrypoint_sha256") != sha256_file(Path(__file__)):
        raise RuntimeError("v04 entrypoint hash mismatch")
    if receipt.get("frozen_trainer_sha256") != sha256_file(TRAINER):
        raise RuntimeError("on-disk frozen trainer changed")
    if receipt.get("correction_verifier_sha256") != sha256_file(PHASE / "verify_phase_b_correction_v04.py"):
        raise RuntimeError("v04 verifier hash mismatch")
    if receipt.get("correction_test_sha256") != sha256_file(PHASE / "tests/test_v08n_phase_b_correction_v04.py"):
        raise RuntimeError("v04 test hash mismatch")
    _, ancestor_paths = parent.verify_correction_chain(parent.load_parent_module())
    paths = [*ancestor_paths, CORRECTION]
    if paths[:3] != [CORRECTION_V01, CORRECTION_V02, CORRECTION_V03]:
        raise RuntimeError("v04 correction ancestry order mismatch")
    if receipt.get("failed_attempt_forensic") != failed_attempt_forensic():
        raise RuntimeError("v04 failed-attempt forensic details drifted")
    return receipt, paths


def failed_attempt_forensic() -> dict[str, Any]:
    files = {
        path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in sorted(FAILED_ATTEMPT.iterdir()) if path.is_file()
    }
    config = read_json(FAILED_ATTEMPT / "run-config.json")
    initial_digest = (FAILED_ATTEMPT / "initial-head-template.sha256").read_text(encoding="ascii").strip()
    if set(files) != {"initial-head-template.sha256", "run-config.json"}:
        raise RuntimeError("failed attempt contains unexpected files or training outputs")
    if config.get("seed") != 20260927 or config.get("arm") != "B-DUP":
        raise RuntimeError("failed attempt identity changed")
    if config.get("initial_head_sha256") != initial_digest:
        raise RuntimeError("failed attempt initialization digest mismatch")
    return {
        "path": str(FAILED_ATTEMPT),
        "seed": 20260927,
        "arm": "B-DUP",
        "failure_stage": "event materialization before optimizer step 1",
        "optimizer_steps": 0,
        "evaluation_access": False,
        "files": files,
        "initial_head_sha256": initial_digest,
    }


def install_receipts(trainer: Any, receipt: dict[str, Any], paths: list[Path]) -> list[str]:
    entries = [{
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "purpose": "implementation correction ancestry and execution binding",
    } for path in paths]
    hashes = [entry["sha256"] for entry in entries]
    base_write_json = trainer.write_json

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
            value["failed_pretraining_attempts"] = [failed_attempt_forensic()]
        base_write_json(path, value)

    trainer.write_json = write_with_receipts
    return hashes


def run(validate_only: bool = False) -> int:
    parent = load_parent_module()
    receipt, correction_paths = verify_chain(parent)
    allowed_dirs = {"feature-cache", "failed-attempts", "head-templates", "attempts"}
    actual_dirs = {path.name for path in RUN.iterdir() if path.is_dir()}
    if actual_dirs - allowed_dirs:
        raise RuntimeError(f"unexpected run-root artifacts before v04 entry: {sorted(actual_dirs - allowed_dirs)}")
    forbidden = [RUN / name for name in ("runs", "execution-order.json", "checkpoint-hash-tree.json", "training-seal-manifest.json")]
    if any(path.exists() for path in forbidden):
        raise RuntimeError("final run artifacts exist; v04 cannot be applied retroactively")

    trainer = parent.load_parent_module().load_trainer()
    trainer.prepare_event = prepare_event
    parent.runtime_device_mapping(trainer)
    chain_hashes = install_receipts(trainer, receipt, correction_paths)
    if validate_only:
        contract, _analysis, _probe, _components = trainer.frozen_bindings()
        trainer.verify_runtime(contract)
        state, candidates, primary, schedule, arms = trainer.verify_inputs(contract)
        trainer.validate_schedule(primary, schedule, arms)
        prepared_primary = 0
        for row in primary:
            trainer.prepare_event(row)
            prepared_primary += 1
        prepared_auxiliary = {}
        for arm, rows in arms.items():
            count = 0
            for row in rows[10_000:]:
                trainer.prepare_event(row)
                count += 1
            prepared_auxiliary[arm] = count
        primary_prepared = trainer.prepare_event(primary[0])
        auxiliary_prepared = {arm: trainer.prepare_event(rows[10_000]) for arm, rows in arms.items()}
        result = {
            "status": "CORRECTED_PHASE_B_INPUT_PREFLIGHT_PASS",
            "implementation_correction_chain_sha256": chain_hashes,
            "primary_occurrences": len(primary),
            "primary_events_materialized_without_training": prepared_primary,
            "schedule_rows": len(schedule),
            "arm_rows": {arm: len(rows) for arm, rows in arms.items()},
            "auxiliary_events_materialized_without_training": prepared_auxiliary,
            "state_tensor_shape": list(state.shape),
            "candidate_tensor_shape": list(candidates.shape),
            "primary_event_identity": primary_prepared["group_id"],
            "auxiliary_event_identities": {arm: event["group_id"] for arm, event in auxiliary_prepared.items()},
            "runtime_device_locator": contract["runtime_environment"]["device"],
            "retained_zero_step_attempt": failed_attempt_forensic(),
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
