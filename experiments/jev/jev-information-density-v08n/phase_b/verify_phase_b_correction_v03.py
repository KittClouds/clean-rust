"""Read-only verifier for the v01-v03 correction and training seal chain."""

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
TRAINER = PHASE / "train_phase_b_v01.py"
CORRECTIONS = [PHASE / f"phase-b-implementation-correction-v0{n}.json" for n in (1, 2, 3)]
ENTRYPOINTS = [PHASE / f"train_phase_b_corrected_v0{n}.py" for n in (1, 2, 3)]
VERIFIERS = [PHASE / f"verify_phase_b_correction_v0{n}.py" for n in (1, 2, 3)]
TESTS = [
    PHASE / "tests/test_v08n_phase_b_correction.py",
    PHASE / "tests/test_v08n_phase_b_correction_v02.py",
    PHASE / "tests/test_v08n_phase_b_correction_v03.py",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_sources() -> dict[str, Any]:
    receipts = [read_json(path) for path in CORRECTIONS]
    event_sha = sha256_file(AUTH)
    for index, (receipt, path, entrypoint, verifier, test) in enumerate(zip(receipts, CORRECTIONS, ENTRYPOINTS, VERIFIERS, TESTS)):
        if receipt.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
            raise RuntimeError(f"correction receipt not sealed: {path.name}")
        if receipt.get("parent_authorization_event_sha256") != event_sha:
            raise RuntimeError(f"correction authorization parent mismatch: {path.name}")
        if receipt.get("corrected_entrypoint_sha256") != sha256_file(entrypoint):
            raise RuntimeError(f"corrected entrypoint hash mismatch: {entrypoint.name}")
        if receipt.get("frozen_trainer_sha256") != sha256_file(TRAINER):
            raise RuntimeError(f"frozen trainer hash mismatch: {path.name}")
        if receipt.get("correction_verifier_sha256") != sha256_file(verifier):
            raise RuntimeError(f"correction verifier hash mismatch: {verifier.name}")
        if receipt.get("correction_test_sha256") != sha256_file(test):
            raise RuntimeError(f"correction test hash mismatch: {test.name}")
        if index > 0 and receipt.get("parent_correction_receipt_sha256") != sha256_file(CORRECTIONS[index - 1]):
            raise RuntimeError(f"correction receipt ancestry mismatch: {path.name}")
    relative = "experiments/jev-information-density-v08n/phase_b/train_phase_b_v01.py"
    if read_json(AUTH).get("implementation_bindings", {}).get(relative) != sha256_file(TRAINER):
        raise RuntimeError("on-disk frozen trainer changed from original authorization")
    if receipts[2].get("parent_entrypoint_sha256") != sha256_file(ENTRYPOINTS[1]):
        raise RuntimeError("v03 receipt does not bind its v02 entrypoint")
    expected_device = {
        "contract_device_identity": "NVIDIA GeForce RTX 3080",
        "resolved_torch_device": "cuda:0",
        "mapping_occurs_after_frozen_runtime_verification": True,
        "hardware_substitution": False,
    }
    if receipts[2].get("runtime_device_mapping") != expected_device:
        raise RuntimeError("v03 runtime mapping receipt changed")
    return {
        "status": "CORRECTION_V01_V03_SOURCE_CHAIN_VALIDATED",
        "authorization_event_sha256": event_sha,
        "correction_receipt_sha256": [sha256_file(path) for path in CORRECTIONS],
        "frozen_trainer_unchanged_from_authorization": True,
        "head_initialization": False,
        "protected_panel_opened": False,
        "phoenix_access": False,
    }


def load_original_verifier() -> Any:
    path = PHASE / "verify_training_seal_v01.py"
    spec = importlib.util.spec_from_file_location("jev_v08n_original_training_seal_v03", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load original independent training verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_training() -> dict[str, Any]:
    source = verify_sources()
    original_validation = load_original_verifier().verify()
    chain_hashes = [sha256_file(path) for path in CORRECTIONS]
    seal_path = RUN / "training-seal-manifest.json"
    tree_path = RUN / "checkpoint-hash-tree.json"
    seal, tree = read_json(seal_path), read_json(tree_path)
    if seal.get("implementation_correction_receipt_sha256") != chain_hashes[-1]:
        raise RuntimeError("training seal does not bind active v03 correction")
    if seal.get("implementation_correction_chain_sha256") != chain_hashes:
        raise RuntimeError("training seal correction chain mismatch")
    if seal.get("corrected_entrypoint_sha256") != read_json(CORRECTIONS[-1])["corrected_entrypoint_sha256"]:
        raise RuntimeError("training seal v03 entrypoint binding mismatch")
    if seal.get("contract_device_identity") != "NVIDIA GeForce RTX 3080" or seal.get("runtime_device_locator") != "cuda:0":
        raise RuntimeError("training seal device identity/locator mismatch")
    expected_paths = {str(path.resolve()) for path in CORRECTIONS}
    entries = [entry for entry in tree.get("entries", []) if entry.get("path") in expected_paths]
    by_path = {entry.get("path"): entry for entry in entries}
    if len(entries) != len(CORRECTIONS):
        raise RuntimeError("checkpoint tree does not contain exactly three correction receipts")
    for path, digest in zip(CORRECTIONS, chain_hashes):
        entry = by_path.get(str(path.resolve()))
        if entry is None or entry.get("sha256") != digest or entry.get("bytes") != path.stat().st_size:
            raise RuntimeError(f"checkpoint tree correction receipt mismatch: {path.name}")

    contract = read_json(PHASE / "phase-b-run-contract-v01.json")
    run_count = 0
    for seed in contract["training"]["seed_set"]:
        for arm in contract["arms"]["order"]:
            run_dir = RUN / "runs" / f"seed-{seed}" / arm
            for name in ("run-config.json", "run-integrity.json"):
                artifact = read_json(run_dir / name)
                if artifact.get("implementation_correction_receipt_sha256") != chain_hashes[-1]:
                    raise RuntimeError(f"run artifact active correction mismatch: {seed}/{arm}/{name}")
                if artifact.get("implementation_correction_chain_sha256") != chain_hashes:
                    raise RuntimeError(f"run artifact correction chain mismatch: {seed}/{arm}/{name}")
                if artifact.get("contract_device_identity") != "NVIDIA GeForce RTX 3080" or artifact.get("runtime_device_locator") != "cuda:0":
                    raise RuntimeError(f"run artifact device identity/locator mismatch: {seed}/{arm}/{name}")
            run_count += 1
    return {
        "status": "CORRECTION_CHAIN_AND_TRAINING_SEAL_VALIDATED",
        "source_chain": source,
        "original_training_verifier": original_validation,
        "implementation_correction_chain_sha256": chain_hashes,
        "run_configs_and_integrities_bound": run_count,
        "protected_panel_opened": False,
        "newtight_access": False,
        "phoenix_access": False,
    }


def main() -> int:
    result = verify_sources() if "--sources-only" in sys.argv[1:] else verify_training()
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
