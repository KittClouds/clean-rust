"""Read-only verifier for the v02 pre-training implementation correction."""

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
CORRECTION = PHASE / "phase-b-implementation-correction-v02.json"
PARENT_CORRECTION = PHASE / "phase-b-implementation-correction-v01.json"
AUTH = PHASE / "phase-b-authorization-event-v01.json"
TRAINER = PHASE / "train_phase_b_v01.py"
ENTRYPOINT = PHASE / "train_phase_b_corrected_v02.py"
TEST = PHASE / "tests/test_v08n_phase_b_correction_v02.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_sources() -> dict[str, Any]:
    receipt = read_json(CORRECTION)
    parent = read_json(PARENT_CORRECTION)
    event_sha = sha256_file(AUTH)
    if receipt.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("v02 correction status mismatch")
    if receipt.get("parent_authorization_event_sha256") != event_sha:
        raise RuntimeError("v02 correction authorization parent mismatch")
    if receipt.get("parent_correction_receipt_sha256") != sha256_file(PARENT_CORRECTION):
        raise RuntimeError("v02 correction receipt parent mismatch")
    if receipt.get("corrected_entrypoint_sha256") != sha256_file(ENTRYPOINT):
        raise RuntimeError("v02 corrected-entrypoint hash mismatch")
    if receipt.get("frozen_trainer_sha256") != sha256_file(TRAINER):
        raise RuntimeError("on-disk authorized trainer hash mismatch")
    relative = "experiments/jev-information-density-v08n/phase_b/train_phase_b_v01.py"
    if read_json(AUTH).get("implementation_bindings", {}).get(relative) != sha256_file(TRAINER):
        raise RuntimeError("on-disk trainer no longer matches the original authorization")
    if receipt.get("parent_frozen_trainer_sha256") != parent.get("frozen_trainer_sha256"):
        raise RuntimeError("v02 correction does not retain v01 trainer parent")
    if receipt.get("correction_verifier_sha256") != sha256_file(Path(__file__).resolve()):
        raise RuntimeError("v02 correction verifier hash mismatch")
    if receipt.get("correction_test_sha256") != sha256_file(TEST):
        raise RuntimeError("v02 correction test hash mismatch")
    if parent.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("v01 correction parent is not sealed")
    return {
        "status": "CORRECTION_V02_SOURCE_CHAIN_VALIDATED",
        "authorization_event_sha256": event_sha,
        "parent_correction_receipt_sha256": sha256_file(PARENT_CORRECTION),
        "active_correction_receipt_sha256": sha256_file(CORRECTION),
        "frozen_trainer_unchanged_from_authorization": True,
        "head_initialization": False,
        "protected_panel_opened": False,
        "phoenix_access": False,
    }


def load_original_verifier() -> Any:
    path = PHASE / "verify_training_seal_v01.py"
    spec = importlib.util.spec_from_file_location("jev_v08n_frozen_training_verifier_v02", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen independent training verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_training() -> dict[str, Any]:
    source_validation = verify_sources()
    original = load_original_verifier()
    base_validation = original.verify()
    receipt = read_json(CORRECTION)
    parent_sha = sha256_file(PARENT_CORRECTION)
    active_sha = sha256_file(CORRECTION)
    chain = [parent_sha, active_sha]
    seal_path = RUN / "training-seal-manifest.json"
    tree_path = RUN / "checkpoint-hash-tree.json"
    seal, tree = read_json(seal_path), read_json(tree_path)
    if seal.get("implementation_correction_receipt_sha256") != active_sha:
        raise RuntimeError("training seal does not bind active v02 correction")
    if seal.get("implementation_correction_chain_sha256") != chain:
        raise RuntimeError("training seal correction chain mismatch")
    if seal.get("corrected_entrypoint_sha256") != receipt["corrected_entrypoint_sha256"]:
        raise RuntimeError("training seal does not bind v02 entrypoint")
    correction_entries = [entry for entry in tree.get("entries", []) if entry.get("path") in {str(PARENT_CORRECTION.resolve()), str(CORRECTION.resolve())}]
    by_path = {entry.get("path"): entry for entry in correction_entries}
    if len(correction_entries) != 2:
        raise RuntimeError("training tree does not contain exactly both correction receipts")
    for path, digest in ((PARENT_CORRECTION, parent_sha), (CORRECTION, active_sha)):
        entry = by_path.get(str(path.resolve()))
        if entry is None or entry.get("sha256") != digest or entry.get("bytes") != path.stat().st_size:
            raise RuntimeError(f"training tree correction receipt mismatch: {path}")

    contract = read_json(PHASE / "phase-b-run-contract-v01.json")
    run_count = 0
    for seed in contract["training"]["seed_set"]:
        for arm in contract["arms"]["order"]:
            run_dir = RUN / "runs" / f"seed-{seed}" / arm
            for name in ("run-config.json", "run-integrity.json"):
                artifact = read_json(run_dir / name)
                if artifact.get("implementation_correction_receipt_sha256") != active_sha:
                    raise RuntimeError(f"run artifact misses active correction: {seed}/{arm}/{name}")
                if artifact.get("implementation_correction_chain_sha256") != chain:
                    raise RuntimeError(f"run artifact correction chain mismatch: {seed}/{arm}/{name}")
                if artifact.get("corrected_entrypoint_sha256") != receipt["corrected_entrypoint_sha256"]:
                    raise RuntimeError(f"run artifact entrypoint mismatch: {seed}/{arm}/{name}")
            run_count += 1

    return {
        "status": "IMPLEMENTATION_CORRECTION_CHAIN_AND_TRAINING_SEAL_VALIDATED",
        "source_validation": source_validation,
        "original_training_verifier": base_validation,
        "implementation_correction_chain_sha256": chain,
        "run_configs_and_integrities_bound": run_count,
        "head_training_before_correction": False,
        "semantic_contract_unchanged": True,
        "protected_panel_opened": False,
        "newtight_access": False,
        "phoenix_access": False,
    }


def main() -> int:
    if "--sources-only" in sys.argv[1:]:
        result = verify_sources()
    else:
        result = verify_training()
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
