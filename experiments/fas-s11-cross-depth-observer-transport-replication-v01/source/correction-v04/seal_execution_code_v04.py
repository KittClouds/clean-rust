from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
RUN = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01")
EXECUTION_MANIFEST = RUN / "execution-manifest-v01.json"
OLD_CODE_MANIFEST = RUN / "implementation-code-manifest-v03.json"
NEW_CODE_MANIFEST = RUN / "implementation-code-manifest-v04.json"
SOURCE = PROJECT / "source" / "correction-v04"
SNAPSHOT = RUN / "source-correction-v04"
FILES = ("extract_layers_v04.py", "seal_execution_code_v04.py")


def digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def main() -> int:
    if NEW_CODE_MANIFEST.exists() or SNAPSHOT.exists():
        raise RuntimeError("S11 v04 correction artifacts already exist; preserve and version any further correction")
    old_hash, _ = digest_file(OLD_CODE_MANIFEST)
    execution = json.loads(EXECUTION_MANIFEST.read_text(encoding="utf-8"))
    if old_hash != execution.get("implementation_code_manifest_sha256"):
        raise RuntimeError("S11 v03 implementation manifest no longer matches execution state")
    old_packet = json.loads(OLD_CODE_MANIFEST.read_text(encoding="utf-8"))
    SNAPSHOT.mkdir()
    entries = list(old_packet["entries"])
    for name in FILES:
        source = SOURCE / name
        target = SNAPSHOT / name
        shutil.copyfile(source, target)
        source_digest, source_size = digest_file(source)
        copied_digest, copied_size = digest_file(target)
        if (source_digest, source_size) != (copied_digest, copied_size):
            raise RuntimeError(f"v04 correction source snapshot mismatch: {name}")
        entries.append({"path": target.relative_to(RUN).as_posix(), "bytes": copied_size, "sha256": copied_digest})
    entries.sort(key=lambda row: row["path"])
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    code_root = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    packet = {
        "manifest_id": "FAS_S11_IMPLEMENTATION_CODE_MANIFEST_V04",
        "status": "TOKENIZATION_SEALED_MODEL_ASSET_SCHEMA_CORRECTION",
        "supersedes_manifest_sha256": old_hash,
        "supersedes_code_tree_root_sha256": old_packet["code_tree_root_sha256"],
        "authoritative_s11_ancestry": old_packet["authoritative_s11_ancestry"],
        "frozen_contract_sha256": old_packet["frozen_contract_sha256"],
        "preserved_tokenization_code_manifest_sha256": old_packet["preserved_tokenization_code_manifest_sha256"],
        "correction": "Use the sealed S09 model asset manifest field names asset_manifest_root_sha256 and assets, with model ID and revision checks. The v03 run stopped at this metadata lookup before loading weights or producing features.",
        "code_tree_root_sha256": code_root,
        "entries": entries,
    }
    NEW_CODE_MANIFEST.write_text(json.dumps(packet, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    new_hash, _ = digest_file(NEW_CODE_MANIFEST)
    execution["superseded_implementation_code_manifest_v03_sha256"] = old_hash
    execution["implementation_code_manifest_sha256"] = new_hash
    execution["implementation_code_root_sha256"] = code_root
    execution["implementation_code_manifest_version"] = 4
    execution["status"] = "TOKENIZATION_SEALED_CODE_CORRECTION_V04"
    EXECUTION_MANIFEST.write_text(json.dumps(execution, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S11 code manifest v04 sealed: {new_hash}; code_root={code_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
