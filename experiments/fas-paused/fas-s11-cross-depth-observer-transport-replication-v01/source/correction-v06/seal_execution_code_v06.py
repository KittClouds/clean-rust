from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
RUN = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01")
EXECUTION_MANIFEST = RUN / "execution-manifest-v01.json"
OLD_CODE_MANIFEST = RUN / "implementation-code-manifest-v05.json"
NEW_CODE_MANIFEST = RUN / "implementation-code-manifest-v06.json"
SOURCE = PROJECT / "source" / "correction-v06"
SNAPSHOT = RUN / "source-correction-v06"
FILES = ("verify_s11_v06.py", "seal_execution_code_v06.py")


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
        raise RuntimeError("S11 v06 correction artifacts already exist; preserve and version any further correction")
    old_hash, _ = digest_file(OLD_CODE_MANIFEST)
    execution = json.loads(EXECUTION_MANIFEST.read_text(encoding="utf-8"))
    if old_hash != execution.get("implementation_code_manifest_sha256"):
        raise RuntimeError("S11 v05 implementation manifest no longer matches execution state")
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
            raise RuntimeError(f"v06 correction source snapshot mismatch: {name}")
        entries.append({"path": target.relative_to(RUN).as_posix(), "bytes": copied_size, "sha256": copied_digest})
    entries.sort(key=lambda row: row["path"])
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    code_root = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    packet = {
        "manifest_id": "FAS_S11_IMPLEMENTATION_CODE_MANIFEST_V06",
        "status": "FEATURES_TRANSPORT_BOOTSTRAP_SEALED_VERIFIER_NUMERICAL_PATH_CORRECTION",
        "supersedes_manifest_sha256": old_hash,
        "supersedes_code_tree_root_sha256": old_packet["code_tree_root_sha256"],
        "authoritative_s11_ancestry": old_packet["authoritative_s11_ancestry"],
        "frozen_contract_sha256": old_packet["frozen_contract_sha256"],
        "preserved_tokenization_code_manifest_sha256": old_packet["preserved_tokenization_code_manifest_sha256"],
        "correction": "The independent verifier computes point estimates through the frozen BA-matrix estimand order, then cross-checks the separately derived quartet contribution form within 1e-12. Bootstrap draws and intervals remain unchanged. This avoids a sub-1e-17 floating-point difference from changing summation order.",
        "code_tree_root_sha256": code_root,
        "entries": entries,
    }
    NEW_CODE_MANIFEST.write_text(json.dumps(packet, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    new_hash, _ = digest_file(NEW_CODE_MANIFEST)
    execution["superseded_implementation_code_manifest_v05_sha256"] = old_hash
    execution["implementation_code_manifest_sha256"] = new_hash
    execution["implementation_code_root_sha256"] = code_root
    execution["implementation_code_manifest_version"] = 6
    execution["status"] = "S11_TRANSPORT_AND_BOOTSTRAP_SEALED_VERIFIER_CORRECTION_V06"
    EXECUTION_MANIFEST.write_text(json.dumps(execution, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S11 verifier code manifest v06 sealed: {new_hash}; code_root={code_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
