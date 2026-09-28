"""Independent recomputation of the E4-0 contract artifact seal."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any


V06_CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06"
V06_SEAL_ID = "FAS_E4_0_CONTRACT_V06_SEAL"
V05_CONTRACT = {
    "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V05",
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v05-final.json",
    "bytes": 39944,
    "sha256": "ad709bd1496536e6fb1464bd89a06ec0eed552b89ef4159bfc1aa0f406fcc71a",
}
V05_SEAL = {
    "seal_id": "FAS_E4_0_CONTRACT_V05_SEAL",
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v05-seal.json",
    "manifest_bytes": 29668,
    "manifest_sha256": "434e4472275adbd6514e5b6a0e8d905c7a283ea6ea294edc0068c050336cd9eb",
    "root_sha256": "38fa25b9433319fc706a1d7fc1e56f20a267f30d467c42ac75ff0850ec656fd1",
    "contract_member_artifact_id": "E4_0_CONTRACT_V05_FINAL",
}
V05_SEAL_MEMBER_IDS = {
    "contract": "E4_0_CONTRACT_V05_SUPERSEDED",
    "seal": "E4_0_CONTRACT_V05_SEAL_SUPERSEDED",
}


def _digest(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def project_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    try:
        relative = path.relative_to(root) if path.is_absolute() else path
    except ValueError as exc:
        raise ValueError(f"path escapes workspace root: {value}") from exc
    if any(part in ("", ".", "..") for part in relative.parts):
        raise ValueError(f"path is not normalized relative to workspace root: {value}")
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
            raise ValueError(f"path traverses a symlink or junction: {value}")
    resolved = candidate.resolve()
    resolved.relative_to(root.resolve())
    return resolved


def artifact_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["artifact_id"].encode("utf-8")):
        row = f"{entry['artifact_id']}\t{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n"
        digest.update(row.encode("utf-8"))
    return digest.hexdigest()


def recompute_seal(
    root: Path,
    seal_path: Path,
    contract_path: Path,
    source_map_path: Path,
    source_rows: list[dict[str, Any]],
    source_map_tables: list[tuple[list[str], list[dict[str, str]]]],
    schema_path: str,
    expected_predecessors: dict[str, str],
    preseal_receipt_path: str,
    postseal_receipt_path: str,
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    seal = _load_json(seal_path)
    schema = _load_json(project_path(root, schema_path))
    if schema.get("schema") != "FAS_E4_0_ARTIFACT_SEAL_V01" or schema.get("status") != "SEALED":
        issues.append("authoritative artifact-seal schema identity/status mismatch")
    required = set(schema.get("required_fields", []))
    if not required.issubset(seal):
        issues.append(f"seal is missing required schema fields: {sorted(required - set(seal))}")
    if seal.get("schema") != schema.get("schema") or seal.get("status") != "SEALED":
        issues.append("seal schema/status identity mismatch")
    if seal.get("seal_id") != V06_SEAL_ID:
        issues.append(f"seal_id mismatch: expected={V06_SEAL_ID}, actual={seal.get('seal_id')!r}")
    try:
        datetime.fromisoformat(str(seal["created_utc"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        issues.append("seal created_utc is absent or not ISO-8601")
    if seal.get("stage") != "E4_0_CONTRACT" or seal.get("path_root_kind") != "WORKSPACE_ROOT":
        issues.append("contract seal stage/path-root kind must be E4_0_CONTRACT/WORKSPACE_ROOT")
    if seal.get("contract_seal_root_sha256") is not None:
        issues.append("contract-stage seal must have null contract_seal_root_sha256")
    contract_bytes, contract_sha = _digest(contract_path)
    if seal.get("contract_sha256") != contract_sha:
        issues.append(f"seal contract_sha256 mismatch: expected={contract_sha}, actual={seal.get('contract_sha256')!r}")
    if seal.get("exact_predecessor_roots") != expected_predecessors:
        issues.append(f"seal exact_predecessor_roots mismatch: expected={expected_predecessors}, actual={seal.get('exact_predecessor_roots')!r}")
    contract_obj = _load_json(contract_path)
    if contract_obj.get("contract_id") != V06_CONTRACT_ID or contract_obj.get("status") != "SEALED":
        issues.append("v06 final contract identity/status mismatch")
    if contract_obj.get("supersedes") != {"contract": V05_CONTRACT, "seal": V05_SEAL}:
        issues.append("v06 contract supersedes metadata differs from frozen v05 identity")

    entries = seal.get("entries")
    if not isinstance(entries, list) or not entries:
        return {}, issues + ["seal manifest has no nonempty entries list"]
    expected_entry_fields = set(schema.get("entry_fields_exact", []))
    actual_entries: list[dict[str, Any]] = []
    by_path: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != expected_entry_fields:
            issues.append(f"malformed seal entry: {entry!r}")
            continue
        artifact_id, rel = entry.get("artifact_id"), entry.get("path")
        if not isinstance(artifact_id, str) or not isinstance(rel, str):
            issues.append(f"seal artifact_id/path must be strings: {entry!r}")
            continue
        try:
            rel.encode("utf-8")
        except UnicodeEncodeError:
            issues.append(f"seal path is not valid UTF-8: {rel!r}")
            continue
        parts = rel.split("/")
        if (
            not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel)
            or "\\" in rel or any(part in ("", ".", "..") for part in parts)
            or any(ord(char) < 32 for char in rel) or PurePosixPath(rel).as_posix() != rel
        ):
            issues.append(f"unsafe/noncanonical seal member path: {rel!r}")
            continue
        if not artifact_id or any(ord(char) < 32 for char in artifact_id):
            issues.append(f"unsafe seal artifact_id: {artifact_id!r}")
            continue
        if rel in by_path or artifact_id in seen_ids:
            issues.append(f"duplicate seal artifact_id or path: {artifact_id} {rel}")
            continue
        seen_ids.add(artifact_id)
        by_path[rel] = entry
        byte_count, expected_sha = entry.get("bytes"), entry.get("sha256")
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            issues.append(f"invalid seal member byte count: {rel}={byte_count!r}")
            continue
        if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            issues.append(f"seal member SHA-256 must be lowercase hex: {rel}")
            continue
        try:
            member = project_path(root, rel)
            size, sha = _digest(member)
            if size != byte_count:
                issues.append(f"seal member byte-count mismatch {rel}: manifest={byte_count}, actual={size}")
            if sha != expected_sha:
                issues.append(f"seal member SHA-256 mismatch {rel}: manifest={expected_sha}, actual={sha}")
            actual_entries.append({"artifact_id": artifact_id, "path": rel, "bytes": size, "sha256": sha})
        except Exception as exc:
            issues.append(f"cannot read seal member {rel}: {type(exc).__name__}: {exc}")

    if not isinstance(seal.get("entry_count"), int) or isinstance(seal.get("entry_count"), bool) or seal["entry_count"] != len(entries):
        issues.append(f"seal entry_count mismatch: manifest={seal.get('entry_count')!r}, actual={len(entries)}")
    ordered = sorted(entries, key=lambda item: str(item.get("artifact_id", "")).encode("utf-8") if isinstance(item, dict) else b"")
    if entries != ordered:
        issues.append("seal entries are not serialized in UTF-8 artifact_id order")
    expected_lineage = (
        (V05_SEAL_MEMBER_IDS["contract"], V05_CONTRACT["path"], V05_CONTRACT["bytes"], V05_CONTRACT["sha256"]),
        (V05_SEAL_MEMBER_IDS["seal"], V05_SEAL["path"], V05_SEAL["manifest_bytes"], V05_SEAL["manifest_sha256"]),
    )
    for artifact_id, rel, size, sha in expected_lineage:
        member = next((item for item in actual_entries if item["artifact_id"] == artifact_id), None)
        if member is None or (member["path"], member["bytes"], member["sha256"]) != (rel, size, sha):
            issues.append(f"v06 seal omits exact v05 supersession member: {artifact_id}")

    recomputed_root = artifact_root(actual_entries)
    if not isinstance(seal.get("root_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", seal["root_sha256"]):
        issues.append("seal root_sha256 must be lowercase 64-character hex")
    if recomputed_root != seal.get("root_sha256"):
        issues.append(f"seal root mismatch: manifest={seal.get('root_sha256')!r}, recomputed={recomputed_root}")

    contract_rel, map_rel = contract_path.relative_to(root).as_posix(), source_map_path.relative_to(root).as_posix()
    seal_rel = seal_path.relative_to(root).as_posix()
    for rel, label in ((contract_rel, "contract"), (map_rel, "source map"), (preseal_receipt_path, "passing preseal receipt")):
        if rel not in by_path:
            issues.append(f"{label} is not bound in seal: {rel}")
    audit_source = Path(__file__).resolve().relative_to(root).as_posix()
    audit_test = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/test_audit_e4_0_track_e_v06.py"
    for rel in (audit_source, audit_test):
        if rel not in by_path:
            issues.append(f"Track E auditor source/test is not bound in seal: {rel}")
    mapped_paths, mapped_issues = _mapped_workspace_paths(source_map_tables)
    issues.extend(mapped_issues)
    for rel in sorted(mapped_paths):
        if rel not in by_path:
            issues.append(f"workspace-root source-map input/receipt/source is not included in contract seal: {rel}")
    roles = [(row["path"], str(row.get("role", "")).lower()) for row in source_rows]
    builders = [p for p, role in roles if "map" in role and ("build" in role or "generat" in role)]
    sealers = [p for p, role in roles if "seal" in role and ("build" in role or "sealer" in role)]
    if not builders:
        issues.append("source map does not designate a map-builder source role")
    if not sealers:
        issues.append("source map does not designate a seal-builder source role")
    for rel in builders + sealers:
        if rel not in by_path:
            issues.append(f"map-builder/sealer source is not bound in seal: {rel}")
    if postseal_receipt_path in by_path:
        issues.append(f"postseal receipt must remain outside contract seal: {postseal_receipt_path}")
    if seal_rel in by_path:
        issues.append("seal manifest cannot be one of its own sealed members")
    summary = {
        "seal_path": str(seal_path), "seal_sha256": _digest(seal_path)[1],
        "seal_root_sha256": seal.get("root_sha256"), "recomputed_root_sha256": recomputed_root,
        "entry_count": len(entries), "contract_member_path": contract_rel, "source_map_member_path": map_rel,
        "contract_bytes": contract_bytes, "contract_sha256": contract_sha,
    }
    return summary, issues


def _mapped_workspace_paths(tables: list[tuple[list[str], list[dict[str, str]]]]) -> tuple[set[str], list[str]]:
    paths: set[str] = set()
    issues: list[str] = []
    for _headers, records in tables:
        for row in records:
            for header, raw in row.items():
                if "path" not in header:
                    continue
                value = raw.strip().strip("` ").replace("\\", "/")
                if not value or Path(value).is_absolute() or re.match(r"^[A-Za-z]:/", value):
                    continue
                if value.startswith("experiments/"):
                    paths.add(value)
                else:
                    issues.append(f"map table path is not workspace-root-relative: {value}")
    return paths, issues
