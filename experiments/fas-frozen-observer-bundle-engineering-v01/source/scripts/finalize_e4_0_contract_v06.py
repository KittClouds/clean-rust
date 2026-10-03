#!/usr/bin/env python3
"""Finalize the E4-0 v06 successor from the immutable v05 science draft and verified map."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
DRAFT_REL = f"{PROJECT_REL}/plans/E4-0-CONTRACT-DRAFT-v05.json"
MAP_REL = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v05.md"
OUTPUT_REL = f"{PROJECT_REL}/contracts/e4-0-contract-v06-final.json"
DRAFT_SHA256 = "e2910965b53313a34c3a7d870075d83dbc9e035a230fc68f3c177c12c71e9fcf"
IMMUTABLE = ("predecessors", "representation_abi", "population", "parity",
             "fresh_qualification", "truth_access", "resources", "phase_gates",
             "stop_rule", "E4_A_dependency")


def sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def parse_tables(path: Path) -> list[tuple[list[str], list[list[str]]]]:
    result = []
    header = None
    rows: list[list[str]] = []

    def close() -> None:
        nonlocal header, rows
        if header is not None and rows:
            result.append((header, rows))
        header, rows = None, []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            close()
            continue
        cells = [part.strip().strip(chr(96) + " ") for part in line.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        if header is None:
            header = cells
        elif len(cells) == len(header):
            rows.append(cells)
    close()
    return result


def workspace_file(workspace: Path, rel: str) -> Path:
    if not rel or rel.startswith("/") or "\\" in rel or "\t" in rel or "\n" in rel or ".." in Path(rel).parts:
        raise RuntimeError(f"unsafe workspace-relative path: {rel!r}")
    path = (workspace / Path(rel)).resolve(strict=True)
    path.relative_to(workspace.resolve())
    return path


def source_rows(map_path: Path, workspace: Path) -> list[dict[str, Any]]:
    matches = [rows for head, rows in parse_tables(map_path)
               if [h.lower().replace("-", "") for h in head] == ["path", "bytes", "sha256", "role"]]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one source closure table, found {len(matches)}")
    result = []
    seen = set()
    for rel, size_text, digest, role in matches[0]:
        if rel in seen or not size_text.isdecimal() or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeError(f"malformed or repeated source row: {rel}")
        size, actual = sha256_file(workspace_file(workspace, rel))
        if size != int(size_text) or actual != digest:
            raise RuntimeError(f"source identity mismatch: {rel}")
        seen.add(rel)
        result.append({"path": rel, "bytes": size, "sha256": actual, "role": role})
    if not result:
        raise RuntimeError("source closure is empty")
    return result


def receipt_rows(map_path: Path, workspace: Path) -> list[dict[str, Any]]:
    matches = [rows for head, rows in parse_tables(map_path)
               if [h.lower().replace("-", "") for h in head] == ["track", "path", "bytes", "sha256", "status"]]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one source receipt table, found {len(matches)}")
    result = []
    for track, rel, size_text, digest, status in matches[0]:
        if not size_text.isdecimal() or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeError(f"malformed receipt row: {rel}")
        path = workspace_file(workspace, rel)
        size, actual = sha256_file(path)
        if size != int(size_text) or actual != digest:
            raise RuntimeError(f"receipt identity mismatch: {rel}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        actual_status = str(payload.get("status", ""))
        if actual_status != status or ("PASS" not in status.upper() and "COMPLETE_PREAUTHORIZATION" not in status.upper()):
            raise RuntimeError(f"receipt status mismatch or failure: {rel}")
        result.append({"track": track, "path": rel, "bytes": size, "sha256": actual, "status": status})
    if not result:
        raise RuntimeError("source map binds no source validation receipts")
    return result


def grouped(rows: list[dict[str, Any]], predicate: Any, label: str) -> dict[str, Any]:
    selected = [row for row in rows if predicate(row["path"])]
    if not selected:
        raise RuntimeError(f"source closure is missing {label}")
    return {"files": selected}


def build_final_contract(workspace: Path) -> dict[str, Any]:
    draft_path = workspace / DRAFT_REL
    draft_bytes, draft_sha = sha256_file(draft_path)
    if draft_sha != DRAFT_SHA256:
        raise RuntimeError("immutable v05 draft hash mismatch")
    baseline = json.loads(draft_path.read_text(encoding="utf-8"))
    map_path = workspace / MAP_REL
    map_bytes, map_sha = sha256_file(map_path)
    sources = source_rows(map_path, workspace)
    receipts = receipt_rows(map_path, workspace)
    final = json.loads(json.dumps(baseline))
    final["contract_id"] = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06"
    final["status"] = "SEALED"
    final["supersedes"] = {
        "contract": {
            "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V05",
            "path": f"{PROJECT_REL}/contracts/e4-0-contract-v05-final.json",
            "bytes": 39944,
            "sha256": "ad709bd1496536e6fb1464bd89a06ec0eed552b89ef4159bfc1aa0f406fcc71a",
        },
        "seal": {
            "seal_id": "FAS_E4_0_CONTRACT_V05_SEAL",
            "path": f"{PROJECT_REL}/seals/e4-0-contract-v05-seal.json",
            "manifest_bytes": 29668,
            "manifest_sha256": "434e4472275adbd6514e5b6a0e8d905c7a283ea6ea294edc0068c050336cd9eb",
            "root_sha256": "38fa25b9433319fc706a1d7fc1e56f20a267f30d467c42ac75ff0850ec656fd1",
            "contract_member_artifact_id": "E4_0_CONTRACT_V05_FINAL",
        },
    }
    final["finalized_utc"] = datetime.now(timezone.utc).isoformat()
    design = final["design_inputs"]
    for key in tuple(design):
        if key.startswith(("implementation_source_map_v03_", "implementation_source_map_v04_", "implementation_source_map_v05_")):
            design.pop(key, None)
    design["implementation_source_map_v05_path"] = MAP_REL
    design["implementation_source_map_v05_sha256"] = map_sha
    design["implementation_source_map_v05_bytes"] = map_bytes
    final.pop("implementation_sources_not_yet_bound", None)
    final.pop("draft_blockers_before_freeze", None)
    final["implementation_sources"] = {
        "source_map": {"path": MAP_REL, "bytes": map_bytes, "sha256": map_sha},
        "e4_population_generator": grouped(
            sources, lambda p: any(x in p for x in ("/source/e4-population-v02/",
            "/source/panel-generator-v04/", "/source/e4-support-plan-v11/")), "population generator"),
        "e4_online_feature_and_parity_runner": grouped(
            sources, lambda p: "/source/scripts/e4_online_parity_v" in p
            or "/source/scripts/e4_runner_" in p or "/source/scripts/e4_gpu_lease_v" in p
            or "/source/tests/test_e4_runner_" in p, "online/parity runner"),
        "e4_fresh_scorer": grouped(
            sources, lambda p: "/source/scripts/e4_fresh_scorer_v02/" in p, "fresh scorer"),
        "e4_stage_authorization_issuer": grouped(
            sources, lambda p: "/source/scripts/issue_e4_stage_authorization_v02.py" in p
            or "/source/tests/test_e4_stage_authorization_v02.py" in p, "stage authorization issuer"),
        "e4_independent_auditor": grouped(
            sources, lambda p: "/source/scripts/e4_independent_audit_v02/" in p
            or p.endswith("/audits/e4-0-track-e/audit_e4_0_track_e_v06.py")
            or p.endswith("/audits/e4-0-track-e/audit_e4_0_track_e_seal_v06.py")
            or p.endswith("/audits/e4-0-track-e/test_audit_e4_0_track_e_v06.py"), "independent auditor"),
    }
    final["source_test_receipts"] = receipts
    final["finalization"] = {
        "immutable_draft_path": DRAFT_REL, "immutable_draft_bytes": draft_bytes,
        "immutable_draft_sha256": draft_sha, "source_map_path": MAP_REL,
        "source_map_bytes": map_bytes, "source_map_sha256": map_sha,
        "source_closure_entry_count": len(sources), "source_test_receipt_count": len(receipts),
        "execution_authorization_conferred": False,
    }
    for key in IMMUTABLE:
        if final[key] != baseline[key]:
            raise RuntimeError(f"frozen scientific section changed: {key}")
    if any(value is not False for value in final["authorization"].values()):
        raise RuntimeError("contract authorization must remain false")
    if any(value is not False for value in final["execution_identity"].values()):
        raise RuntimeError("execution identity must remain false")
    return final


def main() -> int:
    workspace = Path(__file__).resolve().parents[4]
    output = workspace / OUTPUT_REL
    if output.exists():
        raise RuntimeError(f"refusing to overwrite final contract: {output}")
    contract = build_final_contract(workspace)
    encoded = (json.dumps(contract, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
    print(json.dumps({"status": "FINAL_CONTRACT_CREATED_UNAUTHORIZED", "path": OUTPUT_REL,
                      "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest(),
                      "source_receipts": len(contract["source_test_receipts"])}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
