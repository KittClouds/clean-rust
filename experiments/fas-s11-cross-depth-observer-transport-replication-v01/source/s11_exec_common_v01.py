from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


PROJECT = Path(__file__).resolve().parents[1]
RUN = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01")
CONTRACT = RUN / "inputs" / "protocol" / "s11-confirmatory-contract-v01.json"
MANIFEST = RUN / "execution-manifest-v01.json"
CODE_MANIFEST = RUN / "implementation-code-manifest-v01.json"
EVENTS = RUN / "inputs" / "panel" / "selected-events-v02.jsonl"
QUARTETS = RUN / "inputs" / "panel" / "selected-quartets-v02.jsonl"
TOKEN_INPUTS = RUN / "tokenization-v01" / "token-inputs-v01.jsonl"
TOKEN_ROWS = RUN / "tokenization-v01" / "token-rows-v01.jsonl"
FEATURES = RUN / "feature-cache-v01"
RESULTS = RUN / "transport-v01"
OBSERVERS = Path(r"D:\codex-runs\fas-s09-depthwise-decision-subspace-emergence-v09\analysis-v09")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def sha256_file(path: Path, chunk_bytes: int = 8 * 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def tree_root(entries: Iterable[dict[str, Any]]) -> str:
    rows = sorted(entries, key=lambda row: row["path"])
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def entry(path: Path, base: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    return {"path": path.relative_to(base).as_posix(), "bytes": size, "sha256": digest}


def jsonl_rows(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.endswith("\n"):
                raise RuntimeError(f"non-terminated JSONL row {line_no}: {path}")
            yield line_no, json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[str, int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = size = 0
    with path.open("wb") as stream:
        for row in rows:
            payload = canonical_json(row) + b"\n"
            stream.write(payload)
            digest.update(payload)
            size += len(payload)
            count += 1
    return digest.hexdigest(), size, count


def verify_ancestry(manifest: dict[str, Any]) -> None:
    expected = manifest["authoritative_s11_ancestry"]
    contract = read_json(CONTRACT)
    if contract["contract_id"] != "FAS_S11_CONFIRMATORY_CROSS_DEPTH_OBSERVER_TRANSPORT_V01":
        raise RuntimeError("unexpected S11 contract identity")
    if expected["protocol_root_sha256"] != "9f11fb59d0f01ed12ee9c9f1753ae990ce5bcb20cf4f799d35a11a39079a4598":
        raise RuntimeError("protocol root differs from the authorized S11 tuple")
    if expected["collision_admission_amendment_json_sha256"] != "c53fdd8229c31814908c6c4975ddd6847c0b282136b41dcb5fcfa657a30341d8":
        raise RuntimeError("collision amendment differs from the authorized S11 tuple")
    if expected["panel_tree_root_sha256"] != "9011d425faaac7c6c1bee0f619a696a4469816ebeae1c0df2c6d4f8516fde824":
        raise RuntimeError("panel root differs from the authorized S11 tuple")
    for item in manifest.get("copied_input_files", []):
        path = Path(item["path"])
        digest, size = sha256_file(path)
        if digest != item["sha256"] or size != item["bytes"]:
            raise RuntimeError(f"preflight-copied input changed: {path}")
    amendment_path = RUN / "inputs" / "amendment" / "s11-panel-collision-admission-correction-v01.json"
    panel_seal_path = RUN / "inputs" / "panel" / "panel-tree-seal-v02.json"
    contract_path = RUN / "inputs" / "protocol" / "s11-confirmatory-contract-v01.json"
    if sha256_file(amendment_path)[0] != expected["collision_admission_amendment_json_sha256"]:
        raise RuntimeError("collision-admission amendment bytes differ from the authorized tuple")
    if sha256_file(panel_seal_path)[0] != expected["panel_seal_file_sha256"]:
        raise RuntimeError("v02 panel seal bytes differ from the authorized tuple")
    if sha256_file(contract_path)[0] != manifest["frozen_contract_sha256"]:
        raise RuntimeError("frozen S11 contract bytes changed after preflight")


def verify_code_binding(manifest: dict[str, Any]) -> dict[str, Any]:
    digest, _ = sha256_file(CODE_MANIFEST)
    if digest != manifest.get("implementation_code_manifest_sha256"):
        raise RuntimeError("implementation code manifest identity mismatch")
    code_manifest = read_json(CODE_MANIFEST)
    actual = [entry(RUN.joinpath(*row["path"].split("/")), RUN) for row in code_manifest["entries"]]
    actual.sort(key=lambda row: row["path"])
    expected = sorted(code_manifest["entries"], key=lambda row: row["path"])
    root = tree_root(actual)
    if actual != expected or root != code_manifest["code_tree_root_sha256"]:
        raise RuntimeError("implementation source tree changed after freeze")
    return {"manifest_sha256": digest, "code_tree_root_sha256": root}
