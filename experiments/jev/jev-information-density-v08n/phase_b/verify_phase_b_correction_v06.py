"""Read-only verifier for v01-v06 correction chain and the training seal."""

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
CORRECTIONS = [PHASE / f"phase-b-implementation-correction-v0{n}.json" for n in (1, 2, 3, 4, 5, 6)]
ENTRYPOINTS = [PHASE / f"train_phase_b_corrected_v0{n}.py" for n in (1, 2, 3, 4, 5, 6)]
VERIFIERS = [PHASE / f"verify_phase_b_correction_v0{n}.py" for n in (1, 2, 3, 4, 5, 6)]
TESTS = [
    PHASE / "tests/test_v08n_phase_b_correction.py",
    PHASE / "tests/test_v08n_phase_b_correction_v02.py",
    PHASE / "tests/test_v08n_phase_b_correction_v03.py",
    PHASE / "tests/test_v08n_phase_b_correction_v04.py",
    PHASE / "tests/test_v08n_phase_b_correction_v05.py",
    PHASE / "tests/test_v08n_phase_b_correction_v06.py",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_sources() -> dict[str, Any]:
    receipts = [read_json(path) for path in CORRECTIONS]
    event_sha = sha256_file(AUTH)
    for index, (receipt, path, entrypoint, verifier, test) in enumerate(zip(receipts, CORRECTIONS, ENTRYPOINTS, VERIFIERS, TESTS)):
        if receipt.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
            raise RuntimeError(f"correction status mismatch: {path.name}")
        if receipt.get("parent_authorization_event_sha256") != event_sha:
            raise RuntimeError(f"authorization parent mismatch: {path.name}")
        if receipt.get("corrected_entrypoint_sha256") != sha256_file(entrypoint):
            raise RuntimeError(f"entrypoint hash mismatch: {entrypoint.name}")
        if receipt.get("frozen_trainer_sha256") != sha256_file(TRAINER):
            raise RuntimeError(f"trainer hash mismatch: {path.name}")
        if receipt.get("correction_verifier_sha256") != sha256_file(verifier):
            raise RuntimeError(f"verifier hash mismatch: {verifier.name}")
        if receipt.get("correction_test_sha256") != sha256_file(test):
            raise RuntimeError(f"test hash mismatch: {test.name}")
        if index and receipt.get("parent_correction_receipt_sha256") != sha256_file(CORRECTIONS[index - 1]):
            raise RuntimeError(f"receipt ancestry mismatch: {path.name}")
    relative = "experiments/jev-information-density-v08n/phase_b/train_phase_b_v01.py"
    if read_json(AUTH).get("implementation_bindings", {}).get(relative) != sha256_file(TRAINER):
        raise RuntimeError("frozen trainer differs from original authorization")
    parent5 = load_module(ENTRYPOINTS[4], "jev_v08n_v05_source_audit")
    parent4 = parent5.load_v04()
    _, prior_paths = parent5.verify_chain(parent4)
    if prior_paths[-1] != CORRECTIONS[4]:
        raise RuntimeError("v05 parent chain does not terminate at v05 receipt")
    parent5_failure = read_json(CORRECTIONS[4]).get("observed_failure", {})
    if "cache-container adapter" not in parent5_failure.get("root_cause", ""):
        raise RuntimeError("v05 correction does not document the adapter composition failure")
    return {
        "status": "CORRECTION_V01_V06_SOURCE_CHAIN_VALIDATED",
        "authorization_event_sha256": event_sha,
        "correction_receipt_sha256": [sha256_file(path) for path in CORRECTIONS],
        "frozen_trainer_unchanged_from_authorization": True,
        "head_initialization": False,
        "protected_panel_opened": False,
        "phoenix_access": False,
    }


def verify_training() -> dict[str, Any]:
    source_validation = verify_sources()
    original_validation = load_module(PHASE / "verify_training_seal_v01.py", "jev_v08n_original_training_seal_v06").verify()
    hashes = [sha256_file(path) for path in CORRECTIONS]
    receipt = read_json(CORRECTIONS[-1])
    seal = read_json(RUN / "training-seal-manifest.json")
    tree = read_json(RUN / "checkpoint-hash-tree.json")
    if seal.get("implementation_correction_receipt_sha256") != hashes[-1] or seal.get("implementation_correction_chain_sha256") != hashes:
        raise RuntimeError("training seal correction chain mismatch")
    if seal.get("corrected_entrypoint_sha256") != receipt.get("corrected_entrypoint_sha256"):
        raise RuntimeError("training seal active entrypoint mismatch")
    if seal.get("contract_device_identity") != "NVIDIA GeForce RTX 3080" or seal.get("runtime_device_locator") != "cuda:0":
        raise RuntimeError("training seal runtime device mismatch")
    paths = {str(path.resolve()) for path in CORRECTIONS}
    entries = [entry for entry in tree.get("entries", []) if entry.get("path") in paths]
    by_path = {entry["path"]: entry for entry in entries}
    if len(entries) != len(CORRECTIONS):
        raise RuntimeError("training hash tree does not include six unique correction receipts")
    for path, digest in zip(CORRECTIONS, hashes):
        item = by_path.get(str(path.resolve()))
        if item is None or item.get("sha256") != digest or item.get("bytes") != path.stat().st_size:
            raise RuntimeError(f"training hash-tree correction mismatch: {path.name}")
    expected_failed = read_json(CORRECTIONS[3])["failed_attempt_forensic"]
    if seal.get("failed_pretraining_attempts") != [expected_failed]:
        raise RuntimeError("training seal does not retain zero-step attempt forensic")
    contract = read_json(PHASE / "phase-b-run-contract-v01.json")
    count = 0
    for seed in contract["training"]["seed_set"]:
        for arm in contract["arms"]["order"]:
            run_dir = RUN / "runs" / f"seed-{seed}" / arm
            for name in ("run-config.json", "run-integrity.json"):
                artifact = read_json(run_dir / name)
                if artifact.get("implementation_correction_receipt_sha256") != hashes[-1] or artifact.get("implementation_correction_chain_sha256") != hashes:
                    raise RuntimeError(f"run correction chain mismatch: {seed}/{arm}/{name}")
                if artifact.get("contract_device_identity") != "NVIDIA GeForce RTX 3080" or artifact.get("runtime_device_locator") != "cuda:0":
                    raise RuntimeError(f"run device mismatch: {seed}/{arm}/{name}")
            count += 1
    return {
        "status": "CORRECTION_CHAIN_AND_TRAINING_SEAL_VALIDATED",
        "source_validation": source_validation,
        "original_training_verifier": original_validation,
        "implementation_correction_chain_sha256": hashes,
        "run_artifacts_bound": count,
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
