from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[2]
RUN = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01")
EXECUTION_MANIFEST = RUN / "execution-manifest-v01.json"
OLD_CODE_MANIFEST = RUN / "implementation-code-manifest-v02.json"
NEW_CODE_MANIFEST = RUN / "implementation-code-manifest-v03.json"
CORRECTION_SOURCE = PROJECT / "source" / "correction-v03"
CORRECTION_SNAPSHOT = RUN / "source-correction-v03"
FILES = (
    "s11_exec_common_v03.py",
    "extract_layers_v03.py",
    "run_transport_v03.py",
    "run_bootstrap_v03.py",
    "verify_s11_v03.py",
    "seal_execution_code_v03.py",
)


def digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def main() -> int:
    if NEW_CODE_MANIFEST.exists() or CORRECTION_SNAPSHOT.exists():
        raise RuntimeError("S11 v03 correction artifacts already exist; preserve and version any further correction")
    old_hash, _ = digest_file(OLD_CODE_MANIFEST)
    execution = json.loads(EXECUTION_MANIFEST.read_text(encoding="utf-8"))
    if old_hash != execution.get("implementation_code_manifest_sha256"):
        raise RuntimeError("S11 v02 implementation manifest no longer matches execution state")
    old_packet = json.loads(OLD_CODE_MANIFEST.read_text(encoding="utf-8"))
    CORRECTION_SNAPSHOT.mkdir()
    entries = list(old_packet["entries"])
    for name in FILES:
        source = CORRECTION_SOURCE / name
        target = CORRECTION_SNAPSHOT / name
        shutil.copyfile(source, target)
        source_digest, source_size = digest_file(source)
        copied_digest, copied_size = digest_file(target)
        if (source_digest, source_size) != (copied_digest, copied_size):
            raise RuntimeError(f"v03 correction source snapshot mismatch: {name}")
        entries.append({"path": target.relative_to(RUN).as_posix(), "bytes": copied_size, "sha256": copied_digest})
    entries.sort(key=lambda row: row["path"])
    tree_payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    code_root = hashlib.sha256(tree_payload.encode("utf-8")).hexdigest()
    packet: dict[str, Any] = {
        "manifest_id": "FAS_S11_IMPLEMENTATION_CODE_MANIFEST_V03",
        "status": "TOKENIZATION_SEALED_CODE_MANIFEST_PATH_CORRECTION",
        "supersedes_manifest_sha256": old_hash,
        "supersedes_code_tree_root_sha256": old_packet["code_tree_root_sha256"],
        "authoritative_s11_ancestry": old_packet["authoritative_s11_ancestry"],
        "frozen_contract_sha256": old_packet["frozen_contract_sha256"],
        "preserved_tokenization_code_manifest_sha256": old_packet["preserved_tokenization_code_manifest_sha256"],
        "correction": "Versioned v03 runners select implementation-code-manifest-vNN from the execution manifest before verifying source hashes. The v02 helper had a fixed v01 manifest path and stopped pre-model before feature output.",
        "code_tree_root_sha256": code_root,
        "entries": entries,
    }
    NEW_CODE_MANIFEST.write_text(json.dumps(packet, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    new_hash, _ = digest_file(NEW_CODE_MANIFEST)
    execution["superseded_implementation_code_manifest_v02_sha256"] = old_hash
    execution["implementation_code_manifest_sha256"] = new_hash
    execution["implementation_code_root_sha256"] = code_root
    execution["implementation_code_manifest_version"] = 3
    execution["status"] = "TOKENIZATION_SEALED_CODE_CORRECTION_V03"
    EXECUTION_MANIFEST.write_text(json.dumps(execution, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S11 code manifest v03 sealed: {new_hash}; code_root={code_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
