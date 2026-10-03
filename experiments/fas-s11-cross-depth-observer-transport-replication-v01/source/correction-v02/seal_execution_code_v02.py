from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[2]
RUN = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01")
EXECUTION_MANIFEST = RUN / "execution-manifest-v01.json"
OLD_CODE_MANIFEST = RUN / "implementation-code-manifest-v01.json"
NEW_CODE_MANIFEST = RUN / "implementation-code-manifest-v02.json"
CORRECTION_SOURCE = PROJECT / "source" / "correction-v02"
CORRECTION_SNAPSHOT = RUN / "source-correction-v02"
FILES = ("extract_layers_v02.py", "run_transport_v02.py", "verify_s11_v02.py", "seal_execution_code_v02.py")


def digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def main() -> int:
    if NEW_CODE_MANIFEST.exists() or CORRECTION_SNAPSHOT.exists():
        raise RuntimeError("S11 v02 correction artifacts already exist; preserve and version any further correction")
    old_hash, _ = digest_file(OLD_CODE_MANIFEST)
    execution = json.loads(EXECUTION_MANIFEST.read_text(encoding="utf-8"))
    if old_hash != execution.get("implementation_code_manifest_sha256"):
        raise RuntimeError("S11 v01 implementation manifest no longer matches the execution state")
    old_packet = json.loads(OLD_CODE_MANIFEST.read_text(encoding="utf-8"))
    CORRECTION_SNAPSHOT.mkdir()
    new_entries = list(old_packet["entries"])
    for name in FILES:
        source = CORRECTION_SOURCE / name
        target = CORRECTION_SNAPSHOT / name
        shutil.copyfile(source, target)
        source_digest, source_size = digest_file(source)
        copied_digest, copied_size = digest_file(target)
        if (source_digest, source_size) != (copied_digest, copied_size):
            raise RuntimeError(f"v02 correction source snapshot mismatch: {name}")
        new_entries.append({"path": target.relative_to(RUN).as_posix(), "bytes": copied_size, "sha256": copied_digest})
    new_entries.sort(key=lambda row: row["path"])
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in new_entries)
    code_root = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    packet = {
        "manifest_id": "FAS_S11_IMPLEMENTATION_CODE_MANIFEST_V02",
        "status": "TOKENIZATION_SEALED_VERSIONED_RUNNER_IMPORT_CORRECTION",
        "supersedes_manifest_sha256": old_hash,
        "supersedes_code_tree_root_sha256": old_packet["code_tree_root_sha256"],
        "authoritative_s11_ancestry": old_packet["authoritative_s11_ancestry"],
        "frozen_contract_sha256": old_packet["frozen_contract_sha256"],
        "preserved_tokenization_code_manifest_sha256": old_hash,
        "correction": "Add run-local source paths for the already-sealed S09 numerical helpers before imports. The failed v01 extractor exited at import before loading model weights or producing feature rows. No inputs or scientific contracts changed.",
        "code_tree_root_sha256": code_root,
        "entries": new_entries,
    }
    NEW_CODE_MANIFEST.write_text(json.dumps(packet, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    new_hash, _ = digest_file(NEW_CODE_MANIFEST)
    execution["superseded_implementation_code_manifest_v01_sha256"] = old_hash
    execution["implementation_code_manifest_sha256"] = new_hash
    execution["implementation_code_root_sha256"] = code_root
    execution["implementation_code_manifest_version"] = 2
    execution["status"] = "TOKENIZATION_SEALED_CODE_CORRECTION_V02"
    EXECUTION_MANIFEST.write_text(json.dumps(execution, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S11 runner correction sealed: v02={new_hash}; code_root={code_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
