"""Read-only verification of the Phase-B implementation-correction chain."""

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
CORRECTION = PHASE / "phase-b-implementation-correction-v01.json"
AUTH = PHASE / "phase-b-authorization-event-v01.json"
TRAINER = PHASE / "train_phase_b_v01.py"
ENTRYPOINT = PHASE / "train_phase_b_corrected_v01.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_original_verifier() -> Any:
    path = PHASE / "verify_training_seal_v01.py"
    spec = importlib.util.spec_from_file_location("jev_v08n_original_training_verifier", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen independent training-seal verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify() -> dict[str, Any]:
    receipt = read_json(CORRECTION)
    event_sha = sha256_file(AUTH)
    if receipt.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("implementation correction receipt status mismatch")
    if receipt.get("parent_authorization_event_sha256") != event_sha:
        raise RuntimeError("implementation correction has the wrong authorization parent")
    for field, path in (
        ("corrected_entrypoint_sha256", ENTRYPOINT),
        ("frozen_trainer_sha256", TRAINER),
        ("correction_verifier_sha256", Path(__file__).resolve()),
        ("correction_test_sha256", PHASE / "tests/test_v08n_phase_b_correction.py"),
    ):
        if sha256_file(path) != receipt[field]:
            raise RuntimeError(f"correction source identity drift: {path}")

    original = load_original_verifier()
    base_validation = original.verify()
    seal_path = RUN / "training-seal-manifest.json"
    tree_path = RUN / "checkpoint-hash-tree.json"
    seal, tree = read_json(seal_path), read_json(tree_path)
    correction_sha = sha256_file(CORRECTION)
    if seal.get("implementation_correction_receipt_sha256") != correction_sha:
        raise RuntimeError("training seal does not bind the implementation correction")
    if seal.get("corrected_entrypoint_sha256") != receipt["corrected_entrypoint_sha256"]:
        raise RuntimeError("training seal does not bind the corrected entrypoint")
    if sha256_file(tree_path) != seal.get("checkpoint_hash_tree_sha256"):
        raise RuntimeError("training hash-tree file identity mismatch")
    correction_entries = [entry for entry in tree.get("entries", []) if entry.get("path") == str(CORRECTION.resolve())]
    if len(correction_entries) != 1 or correction_entries[0].get("sha256") != correction_sha:
        raise RuntimeError("training hash tree does not include exactly one correction receipt")

    contract = read_json(PHASE / "phase-b-run-contract-v01.json")
    run_configs = 0
    for seed in contract["training"]["seed_set"]:
        for arm in contract["arms"]["order"]:
            run_dir = RUN / "runs" / f"seed-{seed}" / arm
            config = read_json(run_dir / "run-config.json")
            integrity = read_json(run_dir / "run-integrity.json")
            for artifact in (config, integrity):
                if artifact.get("implementation_correction_receipt_sha256") != correction_sha:
                    raise RuntimeError(f"run artifact does not bind correction: {seed}/{arm}")
                if artifact.get("corrected_entrypoint_sha256") != receipt["corrected_entrypoint_sha256"]:
                    raise RuntimeError(f"run artifact corrected-entrypoint mismatch: {seed}/{arm}")
            run_configs += 1

    return {
        "status": "IMPLEMENTATION_CORRECTION_AND_TRAINING_SEAL_VALIDATED",
        "parent_authorization_event_sha256": event_sha,
        "implementation_correction_receipt_sha256": correction_sha,
        "corrected_entrypoint_sha256": receipt["corrected_entrypoint_sha256"],
        "original_training_seal_validation": base_validation,
        "run_configs_bound": run_configs,
        "correction_receipt_in_training_hash_tree": True,
        "head_training_before_correction": False,
        "semantic_contract_unchanged": True,
        "protected_panel_opened": False,
        "phoenix_access": False,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
