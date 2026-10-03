"""Issue a superseding metadata-only seal for the v0.8N Phase-B training tree."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
RECEIPT_PATH = PHASE / "phase-b-training-seal-metadata-correction-v01.json"
SCRIPT_PATH = Path(__file__).resolve()
SEAL_PATH = RUN / "training-seal-manifest.json"
TREE_PATH = RUN / "checkpoint-hash-tree.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + ".metadata-correction.tmp")
    if temp.exists():
        temp.unlink()
    with temp.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def entry_for(path: Path, purpose: str) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "purpose": purpose,
    }


def verify_entries(entries: list[dict[str, Any]]) -> None:
    paths = [item["path"] for item in entries]
    if len(paths) != len(set(paths)):
        raise RuntimeError("hash tree contains duplicate paths")
    for item in entries:
        path = Path(item["path"])
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"hash-tree entry failed verification: {path}")


def main() -> int:
    receipt = read_json(RECEIPT_PATH)
    if receipt.get("status") != "SUPERSEDING_SEAL_METADATA_CORRECTION":
        raise RuntimeError("correction receipt status mismatch")
    if sha256_file(SCRIPT_PATH) != receipt.get("correction_script_sha256"):
        raise RuntimeError("correction script hash differs from sealed receipt")

    old_seal_hash = receipt["superseded_training_seal_sha256"]
    old_tree_hash = receipt["superseded_checkpoint_hash_tree_sha256"]
    preservation = receipt["preservation"]
    backup_seal = Path(preservation["superseded_manifest_backup"])
    backup_tree = Path(preservation["superseded_tree_backup"])
    for backup in (backup_seal, backup_tree):
        if backup.parent != (RUN / "failed-attempts").resolve():
            raise RuntimeError(f"backup path is outside the allowlisted archive: {backup}")
        backup.parent.mkdir(parents=True, exist_ok=True)

    # Preserve the original files byte-for-byte. Existing backups are accepted only
    # when they are exact copies of the already-declared superseded artifacts.
    for source, destination, expected in (
        (SEAL_PATH, backup_seal, old_seal_hash),
        (TREE_PATH, backup_tree, old_tree_hash),
    ):
        if destination.exists():
            if sha256_file(destination) != expected:
                raise RuntimeError(f"existing superseded backup differs: {destination}")
        elif sha256_file(source) == expected:
            destination.write_bytes(source.read_bytes())
            if sha256_file(destination) != expected:
                raise RuntimeError(f"byte-preserving backup verification failed: {destination}")

    if not backup_seal.is_file() or sha256_file(backup_seal) != old_seal_hash:
        raise RuntimeError("authoritative original training-seal backup is unavailable")
    if not backup_tree.is_file() or sha256_file(backup_tree) != old_tree_hash:
        raise RuntimeError("authoritative original checkpoint-tree backup is unavailable")

    old_seal = read_json(backup_seal)
    old_tree = read_json(backup_tree)
    base_entries = old_tree.get("entries", [])
    embedded = old_seal.get("hash_tree_entries", [])
    if len(base_entries) != 77 or len(embedded) != 84:
        raise RuntimeError("superseded artifact cardinalities differ from forensic diagnosis")
    if embedded[: len(base_entries)] != base_entries:
        raise RuntimeError("original seal/tree common prefix differs")
    correction_names = [f"phase-b-implementation-correction-v0{n}.json" for n in range(1, 8)]
    expected_duplicates = [
        item for item in embedded[len(base_entries) :]
    ]
    if [Path(item["path"]).name for item in expected_duplicates] != correction_names:
        raise RuntimeError("superseded duplicate entries are not exactly correction receipts v01-v07")
    if any(item not in base_entries for item in expected_duplicates):
        raise RuntimeError("superseded duplicate entries do not match their valid tree entries")
    verify_entries(base_entries)
    if old_seal.get("run_count") != 9 or old_seal.get("checkpoint_count") != 27:
        raise RuntimeError("superseded seal does not describe the authorized nine-run set")
    if old_seal.get("evaluation_access") is not False or old_seal.get("protected_panel_opened") is not False:
        raise RuntimeError("superseded seal claims protected evaluation access")

    additions = [
        entry_for(RECEIPT_PATH, "superseding seal metadata correction receipt"),
        entry_for(SCRIPT_PATH, "deterministic seal metadata correction utility"),
        entry_for(backup_seal, "byte-identical superseded training seal archive"),
        entry_for(backup_tree, "byte-identical superseded checkpoint hash tree archive"),
    ]
    corrected_entries = [*base_entries, *additions]
    verify_entries(corrected_entries)
    corrected_tree = dict(old_tree)
    corrected_tree["entries"] = corrected_entries
    corrected_tree["entry_count"] = len(corrected_entries)
    corrected_tree["checkpoint_count"] = 27
    tree_data = json_bytes(corrected_tree)
    tree_hash = sha256_bytes(tree_data)

    corrected_seal = dict(old_seal)
    corrected_seal["hash_tree_entries"] = corrected_entries
    corrected_seal["checkpoint_hash_tree_sha256"] = tree_hash
    corrected_seal["seal_metadata_correction_receipt_sha256"] = sha256_file(RECEIPT_PATH)
    corrected_seal["supersedes_training_seal_sha256"] = old_seal_hash
    corrected_seal["seal_metadata_correction_disposition"] = (
        "Supersedes only the duplicate embedded hash-tree receipt entries; all run, "
        "checkpoint, feature, and training-result artifacts remain unchanged."
    )
    seal_data = json_bytes(corrected_seal)

    # A partial prior application is recoverable from the byte-identical backups.
    current_seal_hash = sha256_file(SEAL_PATH)
    current_tree_hash = sha256_file(TREE_PATH)
    allowed_seal_hashes = {old_seal_hash, sha256_bytes(seal_data)}
    allowed_tree_hashes = {old_tree_hash, tree_hash}
    if current_seal_hash not in allowed_seal_hashes or current_tree_hash not in allowed_tree_hashes:
        raise RuntimeError("canonical seal/tree changed outside the expected old or corrected states")

    atomic_write(TREE_PATH, tree_data)
    atomic_write(SEAL_PATH, seal_data)
    if sha256_file(TREE_PATH) != tree_hash or sha256_file(SEAL_PATH) != sha256_bytes(seal_data):
        raise RuntimeError("superseding metadata seal failed post-write hash verification")

    print(json.dumps({
        "status": "SUPERSEDING_METADATA_SEAL_WRITTEN",
        "old_training_seal_sha256": old_seal_hash,
        "new_training_seal_sha256": sha256_file(SEAL_PATH),
        "old_checkpoint_tree_sha256": old_tree_hash,
        "new_checkpoint_tree_sha256": sha256_file(TREE_PATH),
        "tree_entry_count": len(corrected_entries),
        "run_count": 9,
        "checkpoint_count": 27,
        "evaluation_opened": False,
        "training_artifacts_modified": False,
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
