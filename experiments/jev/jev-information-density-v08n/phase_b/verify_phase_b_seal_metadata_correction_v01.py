"""Read-only verification of the superseding v0.8N training-seal metadata."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
RECEIPT = PHASE / "phase-b-training-seal-metadata-correction-v01.json"
SCRIPT = PHASE / "repair_phase_b_seal_metadata_v01.py"
SEAL_PATH = RUN / "training-seal-manifest.json"
TREE_PATH = RUN / "checkpoint-hash-tree.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify() -> dict[str, Any]:
    receipt = read_json(RECEIPT)
    if receipt.get("status") != "SUPERSEDING_SEAL_METADATA_CORRECTION":
        raise RuntimeError("metadata correction receipt status mismatch")
    if receipt.get("correction_script") != "experiments/jev-information-density-v08n/phase_b/repair_phase_b_seal_metadata_v01.py":
        raise RuntimeError("metadata correction script path mismatch")
    if receipt.get("correction_script_sha256") != sha256_file(SCRIPT):
        raise RuntimeError("metadata correction script hash mismatch")
    preservation = receipt["preservation"]
    backup_seal = Path(preservation["superseded_manifest_backup"])
    backup_tree = Path(preservation["superseded_tree_backup"])
    if sha256_file(backup_seal) != receipt["superseded_training_seal_sha256"]:
        raise RuntimeError("superseded training seal backup hash mismatch")
    if sha256_file(backup_tree) != receipt["superseded_checkpoint_hash_tree_sha256"]:
        raise RuntimeError("superseded checkpoint tree backup hash mismatch")

    old_seal = read_json(backup_seal)
    old_tree = read_json(backup_tree)
    old_entries = old_tree.get("entries", [])
    if len(old_entries) != 77 or len(old_seal.get("hash_tree_entries", [])) != 84:
        raise RuntimeError("superseded cardinality does not match forensic receipt")
    if old_seal["hash_tree_entries"][:77] != old_entries:
        raise RuntimeError("superseded hash-tree common prefix changed")
    duplicate_names = [Path(item["path"]).name for item in old_seal["hash_tree_entries"][77:]]
    if duplicate_names != [f"phase-b-implementation-correction-v0{n}.json" for n in range(1, 8)]:
        raise RuntimeError("superseded duplicate entries differ from recorded diagnosis")

    tree = read_json(TREE_PATH)
    seal = read_json(SEAL_PATH)
    entries = tree.get("entries", [])
    if tree.get("entry_count") != len(entries) or len(entries) != 81:
        raise RuntimeError("corrected hash-tree count mismatch")
    if tree.get("checkpoint_count") != 27 or seal.get("checkpoint_count") != 27 or seal.get("run_count") != 9:
        raise RuntimeError("corrected seal changed training cardinality")
    if len({item["path"] for item in entries}) != len(entries):
        raise RuntimeError("corrected hash tree contains duplicate paths")
    if entries[:77] != old_entries:
        raise RuntimeError("original training tree entries were changed")
    for item in entries:
        path = Path(item["path"])
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"corrected hash-tree entry failed: {path}")

    expected_additions = {
        str(RECEIPT.resolve()): sha256_file(RECEIPT),
        str(SCRIPT.resolve()): sha256_file(SCRIPT),
        str(backup_seal.resolve()): receipt["superseded_training_seal_sha256"],
        str(backup_tree.resolve()): receipt["superseded_checkpoint_hash_tree_sha256"],
    }
    by_path = {item["path"]: item for item in entries}
    for path, digest in expected_additions.items():
        if path not in by_path or by_path[path]["sha256"] != digest:
            raise RuntimeError(f"corrected hash tree missing or mismatching correction artifact: {path}")
    if seal.get("hash_tree_entries") != entries:
        raise RuntimeError("corrected seal and detached tree entries differ")
    if seal.get("checkpoint_hash_tree_sha256") != sha256_file(TREE_PATH):
        raise RuntimeError("corrected seal does not bind detached tree")
    if seal.get("seal_metadata_correction_receipt_sha256") != sha256_file(RECEIPT):
        raise RuntimeError("corrected seal does not bind correction receipt")
    if seal.get("supersedes_training_seal_sha256") != receipt["superseded_training_seal_sha256"]:
        raise RuntimeError("corrected seal does not identify superseded seal")
    if seal.get("status") != "ALL_NINE_RUNS_TRAINED_SEALED_UNEVALUATED":
        raise RuntimeError("training seal status changed")
    for key in ("evaluation_access", "protected_panel_opened", "newtight_access", "phoenix_access"):
        if seal.get(key) is not False:
            raise RuntimeError(f"forbidden access status is not false: {key}")
    if any(preservation.get(key) is not False for key in (
        "checkpoints_modified", "run_artifacts_modified", "feature_cache_modified",
        "evaluation_panel_opened", "newtight_access", "phoenix_access",
    )):
        raise RuntimeError("correction receipt claims a protected mutation/access")

    return {
        "status": "SUPERSEDING_TRAINING_SEAL_METADATA_INDEPENDENTLY_VALIDATED",
        "superseded_training_seal_sha256": receipt["superseded_training_seal_sha256"],
        "training_seal_sha256": sha256_file(SEAL_PATH),
        "checkpoint_hash_tree_sha256": sha256_file(TREE_PATH),
        "original_training_tree_entries_unchanged": 77,
        "correction_artifacts_added": 4,
        "run_count": 9,
        "checkpoint_count": 27,
        "evaluation_opened": False,
        "newtight_access": False,
        "phoenix_access": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), separators=(",", ":")))
