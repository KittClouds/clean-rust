from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
RUN = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01")
MANIFEST = RUN / "execution-manifest-v01.json"
CODE_MANIFEST = RUN / "implementation-code-manifest-v01.json"
SOURCE_NAMES = (
    "s11_exec_common_v01.py",
    "tokenize_panel_v01.py",
    "extract_layers_v01.py",
    "run_transport_v01.py",
    "run_bootstrap_v01.py",
    "verify_s11_v01.py",
    "prepare_execution_v01.py",
    "seal_execution_code_v01.py",
)
PARENT_SOURCES = {
    "inputs/parent-sources/s09_math.py": "88fb8b771ca0d861ad111c10fefb370e7021b1836655171055762a11057daa92",
    "inputs/parent-sources/linear_core.py": "b44ce0a2f8c31e5aebb2f13dde4e208424a29a98928d18aa31c6aa081aef2b50",
    "inputs/parent-sources/run_s10_transport.py": "c2a294bd38d6df040df82b4d5948062540dbcf9035db68e34c1570d6b47bc68b",
}


def sha_file(path: Path) -> tuple[str, int]:
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
    if CODE_MANIFEST.exists():
        raise RuntimeError("implementation code manifest already exists; preserve and version any correction")
    run_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    pre_manifest_hash, _ = sha_file(MANIFEST)
    expected_tuple = run_manifest["authoritative_s11_ancestry"]
    if expected_tuple["protocol_root_sha256"] != "9f11fb59d0f01ed12ee9c9f1753ae990ce5bcb20cf4f799d35a11a39079a4598" or expected_tuple["collision_admission_amendment_json_sha256"] != "c53fdd8229c31814908c6c4975ddd6847c0b282136b41dcb5fcfa657a30341d8" or expected_tuple["panel_tree_root_sha256"] != "9011d425faaac7c6c1bee0f619a696a4469816ebeae1c0df2c6d4f8516fde824":
        raise RuntimeError("S11 execution manifest has the wrong authorized ancestry tuple")
    snapshot = RUN / "source"
    snapshot.mkdir(exist_ok=False)
    code_entries = []
    for name in SOURCE_NAMES:
        source = PROJECT / "source" / name
        if not source.is_file():
            raise RuntimeError(f"missing execution source: {source}")
        target = snapshot / name
        shutil.copyfile(source, target)
        digest, size = sha_file(target)
        source_digest, source_size = sha_file(source)
        if (digest, size) != (source_digest, source_size):
            raise RuntimeError(f"source snapshot copy mismatch: {name}")
        code_entries.append({"path": target.relative_to(RUN).as_posix(), "bytes": size, "sha256": digest})
    for relative, expected in PARENT_SOURCES.items():
        path = RUN / Path(relative.replace("/", "\\"))
        digest, size = sha_file(path)
        if digest != expected:
            raise RuntimeError(f"sealed parent source hash mismatch: {relative}")
        code_entries.append({"path": relative, "bytes": size, "sha256": digest})
    code_entries.sort(key=lambda row: row["path"])
    tree_payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in code_entries)
    code_root = hashlib.sha256(tree_payload.encode("utf-8")).hexdigest()
    builder_hash = sha_file(PROJECT / "source" / "seal_execution_code_v01.py")[0]
    packet = {
        "manifest_id": "FAS_S11_IMPLEMENTATION_CODE_MANIFEST_V01",
        "status": "IMPLEMENTATION_FROZEN_BEFORE_TOKENIZATION",
        "pre_code_execution_manifest_sha256": pre_manifest_hash,
        "authoritative_s11_ancestry": expected_tuple,
        "frozen_contract_sha256": run_manifest["frozen_contract_sha256"],
        "code_tree_root_sha256": code_root,
        "entries": code_entries,
        "manifest_builder_sha256": builder_hash,
        "execution_started": False,
    }
    CODE_MANIFEST.write_text(json.dumps(packet, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    code_manifest_hash = sha_file(CODE_MANIFEST)[0]
    run_manifest["implementation_code_manifest_sha256"] = code_manifest_hash
    run_manifest["implementation_code_root_sha256"] = code_root
    run_manifest["status"] = "IMPLEMENTATION_FROZEN_BEFORE_TOKENIZATION"
    MANIFEST.write_text(json.dumps(run_manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S11 implementation frozen: manifest={code_manifest_hash}; code_root={code_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
