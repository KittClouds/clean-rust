#!/usr/bin/env python3
"""Independent E4-0 v07 contract/source/seal audit.

This audit reads contract, source-map, source/test/receipt, and seal metadata.
It never opens population truth payloads and never imports runtime/model code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any


V06_CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06"
V06_SEAL_ID = "FAS_E4_0_CONTRACT_V06_SEAL"
V07_CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V07"
V07_SEAL_ID = "FAS_E4_0_CONTRACT_V07_SEAL"
TRACK_B_INTEGRATION_PATHS = frozenset({
    "source/scripts/e4_online_parity_v03.py",
    "source/scripts/e4_runner_common_v03.py",
    "source/scripts/e4_runner_artifacts_v03.py",
    "source/scripts/e4_runner_modes_v03.py",
    "source/scripts/e4_gpu_lease_v03.py",
    "source/tests/test_e4_runner_v03.py",
})
TRACK_E_ISSUER_PATHS = frozenset({
    "source/scripts/issue_e4_stage_authorization_v07.py",
    "source/tests/test_e4_stage_authorization_v07.py",
})
PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
REGISTERED_SOURCE_TEST_RECEIPTS = {
    "Predecessor Track A v03": (f"{PROJECT_REL}/audits/e4-0-track-a/track-a-receipt-v03.json", "TRACK_A_COMPLETE_PREAUTHORIZATION"),
    "Predecessor Track A history v02": (f"{PROJECT_REL}/audits/e4-0-track-a/track-a-receipt-v02.json", "TRACK_A_COMPLETE_PREAUTHORIZATION"),
    "Predecessor Track A history v01": (f"{PROJECT_REL}/audits/e4-0-track-a/track-a-receipt-v01.json", "TRACK_A_COMPLETE_PREAUTHORIZATION"),
    "Predecessor Track B v02": (f"{PROJECT_REL}/audits/e4-0-track-b-v02/track-b-source-tests-v01.json", "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS"),
    "Predecessor Track B history v01": (f"{PROJECT_REL}/audits/e4-0-track-b/track-b-source-tests-v01.json", "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS"),
    "Predecessor Track C v02": (f"{PROJECT_REL}/audits/e4-0-track-c-v02/track-c-source-tests-v01.json", "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS"),
    "Predecessor Track C history v01": (f"{PROJECT_REL}/audits/e4-0-track-c/track-c-source-tests-v02.json", "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS"),
    "Predecessor Track D v02": (f"{PROJECT_REL}/audits/e4-0-track-d/track-d-receipt-v06.json", "TRACK_D_COMPLETE_PREAUTHORIZATION"),
    "Predecessor Track D history v05": (f"{PROJECT_REL}/audits/e4-0-track-d/track-d-receipt-v05.json", "TRACK_D_COMPLETE_PREAUTHORIZATION"),
    "Predecessor Track E v06": (f"{PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v08.json", "TRACK_E_SOURCE_TESTS_PASS_PREMAP_UNIT_TESTS"),
    "Predecessor Auth issuer v02": (f"{PROJECT_REL}/audits/e4-0-auth-issuer-v02/source-tests-v01.json", "PASS_SYNTHETIC_TESTS"),
    "Predecessor Auth issuer history v01": (f"{PROJECT_REL}/audits/e4-0-auth-issuer-source-tests-v01.json", "PASS_SYNTHETIC_TESTS"),
    "Track B v03": (f"{PROJECT_REL}/audits/e4-0-track-b-v03/track-b-source-tests-v03.json", "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS"),
    "Track C v03": (f"{PROJECT_REL}/audits/e4-0-track-c-v03/track-c-source-tests-v03.json", "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS"),
    "Track D v03": (f"{PROJECT_REL}/audits/e4-0-track-d-v03/track-d-source-tests-v02.json", "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS"),
    "Track E v07 pre-map": (f"{PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v14.json", "TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR"),
    "Authorization issuer v07": (f"{PROJECT_REL}/audits/e4-0-auth-issuer-v07/source-tests-v02.json", "PASS_SYNTHETIC_TESTS"),
    "Contract tooling v07": (f"{PROJECT_REL}/audits/e4-0-track-e/contract-tooling-source-tests-v04.json", "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS"),
}
V06_CONTRACT = {
    "contract_id": V06_CONTRACT_ID,
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v06-final.json",
    "bytes": 43208,
    "sha256": "ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958",
}
V06_SEAL = {
    "seal_id": V06_SEAL_ID,
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v06-seal.json",
    "manifest_bytes": 35340,
    "manifest_sha256": "799d1535a16ea6fbf2269206443addf96736ef8a70ca5ab3373cdd5e6a44605c",
    "root_sha256": "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64",
    "contract_member_artifact_id": "E4_0_CONTRACT_V06_FINAL",
}
V06_SUPERSESSION_IDS = {
    "contract": "E4_0_CONTRACT_V06_SUPERSEDED",
    "seal": "E4_0_CONTRACT_V06_SEAL_SUPERSEDED",
}
V06_FAILED_PARITY_STOP = {
    "receipt_path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-execution/online-parity-precontact-stop-v01.json",
    "sha256": "69d9e4ab7699c1ac390739a8588a4027c8d862971522391576a51030b066ea33",
    "classification": "PRECONTACT_EXECUTION_PLUMBING_FAILURE",
}
SCIENCE_FIELDS = (
    "purpose", "authorization", "predecessors", "representation_abi", "population",
    "parity", "fresh_qualification", "truth_access", "resources", "phase_gates",
    "stop_rule", "E4_A_dependency", "execution_identity", "identity_collision_correction",
    "design_inputs (excluding implementation_source_map_* bindings)",
)
INHERITED_CONTRACT_ROOT = "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64"
INHERITED_POPULATION = {
    "population_root_sha256": "27731b483b8242aaef15ca22b97796b7b305a79db9bbb235765e13dcd9d08967",
    "audit_receipt_sha256": "7dd3eea3133dbed779071fd14e22df06ff5a0ddce994e4446cf4c6ef7b9cbe5a",
    "contract_root_at_creation_sha256": INHERITED_CONTRACT_ROOT,
}
INHERITED_PARITY_PANEL = {
    "panel_root_sha256": "6ef00306df0df20ada7b7a86b09567ae46e07f112f66d974d7885e8f1e5d4d95",
    "selection_authorization_sha256": "3e3f06bbe12db1bb9608cf56cb1699039d70b6ed79aed757b056e87cc0209d59",
    "contract_root_at_creation_sha256": INHERITED_CONTRACT_ROOT,
}
V07_CONTRACT_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v07-final.json"
V07_MAP_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v06.md"
V07_SEAL_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v07-seal.json"
V07_PRESEAL_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-preseal-receipt-v07.json"
V07_POSTSEAL_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-postseal-receipt-v07.json"
SEAL_SCHEMA_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-artifact-seal-schema-v01.json"


def digest(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def safe_path(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    try:
        relative = candidate.relative_to(root) if candidate.is_absolute() else candidate
    except ValueError as exc:
        raise ValueError(f"path escapes workspace root: {value}") from exc
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise ValueError(f"noncanonical workspace-relative path: {value}")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ValueError(f"path traverses symlink or junction: {value}")
    resolved = current.resolve()
    resolved.relative_to(root.resolve())
    return resolved


def artifact_root(entries: list[dict[str, Any]]) -> str:
    digest_state = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["artifact_id"].encode("utf-8")):
        line = f"{entry['artifact_id']}\t{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n"
        digest_state.update(line.encode("utf-8"))
    return digest_state.hexdigest()


def parse_markdown_tables(path: Path) -> list[tuple[list[str], list[dict[str, str]]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    tables: list[tuple[list[str], list[dict[str, str]]]] = []
    index = 0
    while index + 1 < len(lines):
        if not lines[index].lstrip().startswith("|") or not lines[index + 1].lstrip().startswith("|"):
            index += 1
            continue
        headers = [cell.strip().strip("` ").lower().replace("_", "-").replace(" ", "-") for cell in lines[index].strip().strip("|").split("|")]
        separator = [cell.strip().replace(":", "").replace("-", "") for cell in lines[index + 1].strip().strip("|").split("|")]
        if len(headers) != len(separator) or any(cell for cell in separator):
            index += 1
            continue
        rows: list[dict[str, str]] = []
        index += 2
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            cells = [cell.strip().strip("` ") for cell in lines[index].strip().strip("|").split("|")]
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))
            index += 1
        tables.append((headers, rows))
    return tables


def _field(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        if name in row:
            return row[name]
    return None


def mapped_workspace_paths(tables: list[tuple[list[str], list[dict[str, str]]]]) -> tuple[set[str], list[str]]:
    paths: set[str] = set()
    issues: list[str] = []
    for _headers, rows in tables:
        for row in rows:
            raw = _field(row, "path", "input-path", "receipt-path", "source-path")
            if not raw:
                continue
            value = raw.strip().replace("\\", "/")
            if value.startswith("experiments/"):
                if any(part in ("", ".", "..") for part in value.split("/")):
                    issues.append(f"noncanonical workspace path in source map: {value}")
                else:
                    paths.add(value)
            elif re.match(r"^[A-Za-z]:/", value) or value.startswith("/"):
                continue
            else:
                issues.append(f"source-map path is not workspace-root-relative: {value}")
    return paths, issues


def source_and_receipt_rows(tables: list[tuple[list[str], list[dict[str, str]]]]) -> list[dict[str, str]]:
    rows_out: list[dict[str, str]] = []
    for headers, rows in tables:
        is_source_table = headers == ["path", "bytes", "sha-256", "role"]
        is_receipt_table = headers == ["track", "path", "bytes", "sha-256", "status"]
        if not (is_source_table or is_receipt_table):
            continue
        for row in rows:
            path = _field(row, "path", "input-path", "receipt-path", "source-path")
            size = _field(row, "bytes", "byte-count")
            sha = _field(row, "sha-256", "sha256", "sha-256-hex")
            if path and size and sha:
                rows_out.append({"path": path.replace("\\", "/"), "bytes": size.replace(",", ""), "sha256": sha.lower(), "role": _field(row, "role", "status", "track") or ""})
    return rows_out


def source_rows(tables: list[tuple[list[str], list[dict[str, str]]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    matches = [rows for headers, rows in tables if headers == ["path", "bytes", "sha-256", "role"]]
    if len(matches) != 1:
        return result
    for row in matches[0]:
        try:
            result.append({
                "path": row["path"].replace("\\", "/"),
                "bytes": int(row["bytes"].replace(",", "")),
                "sha256": row["sha-256"].lower(),
                "role": row["role"],
            })
        except (KeyError, ValueError):
            continue
    return result


def resolve_input_path(root: Path, raw_path: str) -> Path:
    value = raw_path.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", value) or value.startswith("/"):
        candidate = Path(raw_path)
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"input artifact is not a regular file: {raw_path}")
        return resolved
    return safe_path(root, value)


def validate_input_bindings(
    root: Path, tables: list[tuple[list[str], list[dict[str, str]]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    checked: list[dict[str, Any]] = []
    issues: list[str] = []
    matches = [rows for headers, rows in tables if headers == ["input-path", "bytes", "sha-256", "role"]]
    if len(matches) != 1:
        return checked, [f"source map must contain exactly one frozen input table, found {len(matches)}"]
    semantic: dict[str, list[dict[str, Any]]] = {
        "population_seal": [], "population_audit": [], "parity_panel_seal": [],
        "panel_selection": [], "panel_authorization": [],
    }
    for row in matches[0]:
        raw = row.get("input-path", "")
        role = row.get("role", "").lower()
        if not raw:
            issues.append("frozen input row has an empty path")
            continue
        if is_truth_payload(raw):
            checked.append({"path": raw, "status": "HASH_BOUND_BY_SOURCE_MAP_NOT_OPENED_TRUTH_PAYLOAD"})
            continue
        try:
            expected_size = int(row["bytes"].replace(",", ""))
            expected_sha = row["sha-256"].lower()
            if expected_size < 0 or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
                raise ValueError("invalid input byte/hash fields")
            path = resolve_input_path(root, raw)
            actual_size, actual_sha = digest(path)
            if (actual_size, actual_sha) != (expected_size, expected_sha):
                issues.append(f"frozen input byte/hash mismatch: {raw}")
                continue
            item: dict[str, Any] = {"path": raw, "bytes": actual_size, "sha256": actual_sha, "role": row.get("role", "")}
            payload: dict[str, Any] | None = None
            if path.suffix.lower() == ".json" and (any(token in role for token in ("stage seal", "stage-seal", "population audit", "parity-panel authorization", "panel authorization", "panel receipt", "selection receipt"))
                    or any(token in role for token in ("seal", "audit", "authorization", "receipt"))):
                payload = load_json(path)
                item["payload"] = payload
            checked.append({key: value for key, value in item.items() if key != "payload"})
            if "population stage seal" in role:
                semantic["population_seal"].append(item)
            elif ("parity panel" in role or "parity-panel" in role) and "seal" in role:
                semantic["parity_panel_seal"].append(item)
            elif raw.replace("\\", "/") == f"{PROJECT_REL}/audits/e4-0-execution/population-independent-audit-receipt-v01.json":
                semantic["population_audit"].append(item)
            elif "parity-panel authorization" in role or "parity panel authorization" in role:
                semantic["panel_authorization"].append(item)
            elif "parity panel receipt" in role or "parity-panel receipt" in role or "selection receipt" in role:
                semantic["panel_selection"].append(item)
        except Exception as exc:
            issues.append(f"cannot verify frozen input {raw}: {type(exc).__name__}: {exc}")

    for key, items in semantic.items():
        if len(items) != 1:
            issues.append(f"source map must bind exactly one inherited {key.replace('_', ' ')} artifact, found {len(items)}")
    def payload(key: str) -> dict[str, Any]:
        return semantic[key][0].get("payload", {}) if len(semantic[key]) == 1 else {}
    pop_seal = payload("population_seal")
    if pop_seal.get("status") != "SEALED" or pop_seal.get("root_sha256") != INHERITED_POPULATION["population_root_sha256"]:
        issues.append("inherited population stage seal status/root mismatch")
    panel_seal = payload("parity_panel_seal")
    if panel_seal.get("status") != "SEALED" or panel_seal.get("root_sha256") != INHERITED_PARITY_PANEL["panel_root_sha256"]:
        issues.append("inherited parity-panel stage seal status/root mismatch")
    pop_audit = payload("population_audit")
    if (pop_audit.get("status") != "PASS_POPULATION_FRESHNESS_SUPPORT"
            or pop_audit.get("population_root_sha256") != INHERITED_POPULATION["population_root_sha256"]
            or pop_audit.get("population_truth_files_opened") is not False):
        issues.append("inherited population audit is not a truth-closed pass for the exact population root")
    if len(semantic["population_audit"]) == 1 and semantic["population_audit"][0].get("sha256") != INHERITED_POPULATION["audit_receipt_sha256"]:
        issues.append("inherited population audit receipt SHA-256 differs from the frozen identity")
    panel_receipt = payload("panel_selection")
    if (panel_receipt.get("status") != "PARITY_PANEL_SEALED"
            or panel_receipt.get("authorization_sha256") != INHERITED_PARITY_PANEL["selection_authorization_sha256"]
            or panel_receipt.get("e4_contract_root_sha256") != INHERITED_CONTRACT_ROOT
            or panel_receipt.get("labels_opened") is not False
            or panel_receipt.get("predictions_emitted") is not False):
        issues.append("inherited parity-panel receipt differs from its frozen authorization/contract identity")
    panel_auth = payload("panel_authorization")
    if (panel_auth.get("status") != "AUTHORIZED"
            or panel_auth.get("stage") != "PARITY_PANEL_MATERIALIZATION"
            or panel_auth.get("contract_seal_root_sha256") != INHERITED_CONTRACT_ROOT):
        issues.append("inherited parity-panel authorization is not bound to the sealed v06 contract")
    if len(semantic["panel_authorization"]) == 1 and semantic["panel_authorization"][0].get("sha256") != INHERITED_PARITY_PANEL["selection_authorization_sha256"]:
        issues.append("inherited parity-panel authorization SHA-256 differs from the frozen identity")
    return checked, issues


def is_truth_payload(path: str) -> bool:
    parts = [part.lower() for part in path.replace("\\", "/").split("/")]
    truth_dirs = {"labels", "truth", "terminal-labels", "predictions", "scores", "truth-escrow", "label-escrow"}
    if any(part in truth_dirs for part in parts[:-1]):
        return True
    name = parts[-1] if parts else ""
    return bool(re.search(r"(^|[-_.])(labels?|truth|predictions?|scores?)([-_.]|$)", name) and Path(name).suffix.lower() in {".jsonl", ".csv", ".tsv", ".parquet", ".npy", ".bin"})


def expected_supersedes() -> dict[str, Any]:
    return {"contract": dict(V06_CONTRACT), "seal": dict(V06_SEAL)}


def validate_v06_lineage(root: Path, v06_contract_path: Path, v06_seal_path: Path) -> list[str]:
    issues: list[str] = []
    for path, expected, label in (
        (v06_contract_path, V06_CONTRACT, "v06 contract"),
        (v06_seal_path, V06_SEAL, "v06 seal"),
    ):
        try:
            size, sha = digest(path)
            expected_size = expected.get("bytes", expected.get("manifest_bytes"))
            expected_sha = expected.get("sha256", expected.get("manifest_sha256"))
            if size != expected_size or sha != expected_sha:
                issues.append(f"{label} exact historical byte identity mismatch: {size}/{sha}")
        except Exception as exc:
            issues.append(f"cannot read {label}: {type(exc).__name__}: {exc}")
    try:
        contract = load_json(v06_contract_path)
        seal = load_json(v06_seal_path)
        if contract.get("contract_id") != V06_CONTRACT_ID or contract.get("status") != "SEALED":
            issues.append("historical v06 contract identity/status mismatch")
        if seal.get("seal_id") != V06_SEAL_ID or seal.get("root_sha256") != V06_SEAL["root_sha256"]:
            issues.append("historical v06 seal identity/root mismatch")
        if seal.get("contract_sha256") != V06_CONTRACT["sha256"]:
            issues.append("historical v06 seal does not bind the exact v06 contract")
        if artifact_root(seal.get("entries", [])) != V06_SEAL["root_sha256"]:
            issues.append("historical v06 seal manifest root does not independently recompute")
    except Exception as exc:
        issues.append(f"cannot validate v06 lineage metadata: {type(exc).__name__}: {exc}")
    return issues


def validate_science_equality(v06: dict[str, Any], v07: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    top_fields = SCIENCE_FIELDS[:-1]
    missing = [key for key in top_fields if key not in v06 or key not in v07]
    if missing:
        return [f"science comparison field missing from v06/v07 contract: {missing}"]
    if not isinstance(v06.get("design_inputs"), dict) or not isinstance(v07.get("design_inputs"), dict):
        return ["science comparison design_inputs block is missing or malformed"]
    for key in top_fields:
        if canonical(v06[key]) != canonical(v07[key]):
            issues.append(f"v07 science field differs from sealed v06: {key}")
    def design_projection(contract: dict[str, Any]) -> dict[str, Any]:
        block = contract.get("design_inputs")
        if not isinstance(block, dict):
            return {}
        return {key: value for key, value in block.items() if not key.startswith("implementation_source_map_")}
    if canonical(design_projection(v06)) != canonical(design_projection(v07)):
        issues.append("v07 science field differs from sealed v06: design_inputs (excluding implementation_source_map_* bindings)")
    return issues


def validate_inherited_roots(contract: dict[str, Any]) -> list[str]:
    amendment = contract.get("engineering_amendment")
    if not isinstance(amendment, dict):
        return ["engineering_amendment block is missing or malformed"]
    issues: list[str] = []
    expected_amendment_identity = {
        "amendment_kind": "VERSIONED_EXECUTION_PLUMBING_REPAIR",
        "baseline_contract_id": V06_CONTRACT_ID,
        "baseline_contract_path": V06_CONTRACT["path"],
        "baseline_contract_sha256": V06_CONTRACT["sha256"],
        "baseline_seal_root_sha256": INHERITED_CONTRACT_ROOT,
        "changed_scientific_fields": [],
        "failed_v06_parity_attempt": V06_FAILED_PARITY_STOP,
    }
    if any(amendment.get(key) != expected for key, expected in expected_amendment_identity.items()):
        issues.append("engineering amendment identity or preserved v06 precontact-stop lineage differs from the frozen values")
    if amendment.get("inherited_population") != INHERITED_POPULATION:
        issues.append("inherited population root/audit/creation-contract identities differ from the frozen v06 run")
    if amendment.get("inherited_parity_panel") != INHERITED_PARITY_PANEL:
        issues.append("inherited parity-panel/authorization/creation-contract identities differ from the frozen v06 run")
    return issues


def validate_source_bindings(root: Path, contract_path: Path, source_map_path: Path) -> tuple[list[dict[str, Any]], list[tuple[list[str], list[dict[str, str]]]], set[str], list[str]]:
    issues: list[str] = []
    checked: list[dict[str, Any]] = []
    try:
        map_size, map_sha = digest(source_map_path)
        contract = load_json(contract_path)
        design = contract.get("design_inputs", {})
        bindings = [(key[:-5], value) for key, value in design.items() if key.startswith("implementation_source_map_") and key.endswith("_path")]
        if len(bindings) != 1:
            issues.append(f"contract must bind exactly one implementation source map path, found {len(bindings)}")
        for stem, path_value in bindings:
            if not isinstance(path_value, str):
                issues.append("implementation source-map path is malformed")
                continue
            expected_path = source_map_path.relative_to(root).as_posix()
            if path_value.replace("\\", "/") != expected_path:
                issues.append(f"contract source-map path mismatch: expected {expected_path}, got {path_value}")
            if design.get(stem + "_sha256") != map_sha or design.get(stem + "_bytes") != map_size:
                issues.append("contract source-map byte/hash binding mismatch")
        source_binding = contract.get("implementation_sources", {}).get("source_map")
        if source_binding != {"path": source_map_path.relative_to(root).as_posix(), "bytes": map_size, "sha256": map_sha}:
            issues.append("implementation_sources.source_map does not bind the exact v07 map")
        tables = parse_markdown_tables(source_map_path)
        map_paths, path_issues = mapped_workspace_paths(tables)
        issues.extend(path_issues)
        rows = source_and_receipt_rows(tables)
        seen: set[str] = set()
        for row in rows:
            rel = row["path"]
            if not rel.startswith("experiments/") or is_truth_payload(rel):
                continue
            if rel in seen:
                issues.append(f"duplicate source/receipt path in source map: {rel}")
                continue
            seen.add(rel)
            try:
                size, sha = digest(safe_path(root, rel))
                if str(size) != row["bytes"] or sha != row["sha256"]:
                    issues.append(f"source-map source/receipt identity mismatch: {rel}")
                checked.append({"path": rel, "bytes": size, "sha256": sha, "role": row["role"]})
            except Exception as exc:
                issues.append(f"cannot verify mapped source/receipt {rel}: {type(exc).__name__}: {exc}")
        return checked, tables, map_paths, issues
    except Exception as exc:
        return checked, [], set(), [f"cannot verify source-map binding: {type(exc).__name__}: {exc}"]


def validate_contract_source_closure(
    root: Path, contract: dict[str, Any], source_map_path: Path,
    tables: list[tuple[list[str], list[dict[str, str]]]],
) -> list[str]:
    issues: list[str] = []
    rows = source_rows(tables)
    sources = contract.get("implementation_sources")
    if not isinstance(sources, dict):
        return ["contract implementation_sources block is missing or malformed"]
    map_size, map_sha = digest(source_map_path)
    map_rel = source_map_path.as_posix()
    if not source_map_path.is_absolute():
        map_rel = source_map_path.as_posix()
    # The caller passes a workspace-rooted absolute path. Prefer the canonical
    # workspace identity already present in the contract's design inputs.
    design = contract.get("design_inputs", {})
    map_path_key = next((key for key in design if key.startswith("implementation_source_map_") and key.endswith("_path")), None)
    expected_map_path = design.get(map_path_key) if map_path_key else map_rel
    expected_source_map = {"path": expected_map_path, "bytes": map_size, "sha256": map_sha}
    if sources.get("source_map") != expected_source_map:
        issues.append("implementation_sources.source_map differs from the exact source-map artifact")

    predicates = {
        "e4_population_generator": lambda p: any(token in p for token in ("/source/e4-population-v02/", "/source/panel-generator-v04/", "/source/e4-support-plan-v11/")),
        "e4_online_feature_and_parity_runner": lambda p: (
            any(p.endswith("/" + rel) for rel in TRACK_B_INTEGRATION_PATHS)),
        "e4_fresh_scorer": lambda p: "/source/scripts/e4_fresh_scorer_v03/" in p,
        "e4_stage_authorization_issuer": lambda p: (
            any(p.endswith("/" + rel) for rel in TRACK_E_ISSUER_PATHS)),
        "e4_independent_auditor": lambda p: (
            "/source/scripts/e4_independent_audit_v03/" in p
            or p.endswith("/audits/e4-0-track-e/audit_e4_0_track_e_v07.py")
            or p.endswith("/audits/e4-0-track-e/test_audit_e4_0_track_e_v07.py")),
        "e4_contract_seal_and_source_map_tooling": lambda p: any(p.endswith("/" + name) for name in (
            "finalize_e4_0_contract_v07.py", "seal_e4_0_contract_v07.py",
            "build_e4_0_source_map_v06.py", "test_e4_0_contract_v07.py")),
    }
    expected_bindings: dict[str, Any] = {"source_map": expected_source_map}
    for name, predicate in predicates.items():
        matched = [row for row in rows if predicate(row["path"])]
        if not matched:
            issues.append(f"source map has no source rows for implementation role {name}")
        expected_bindings[name] = {"files": matched}
    if canonical(sources) != canonical(expected_bindings):
        issues.append("contract implementation_sources does not exactly bind source-map rows by role")

    receipt_tables = [(headers, records) for headers, records in tables if headers == ["track", "path", "bytes", "sha-256", "status"]]
    expected_receipts: list[dict[str, Any]] = []
    if len(receipt_tables) != 1:
        issues.append(f"source map must contain exactly one source-test receipt table, found {len(receipt_tables)}")
    else:
        seen_tracks: set[str] = set()
        for row in receipt_tables[0][1]:
            try:
                track = row["track"]
                path = row["path"]
                status = row["status"]
                expected_receipts.append({
                    "track": track, "path": path,
                    "bytes": int(row["bytes"].replace(",", "")),
                    "sha256": row["sha-256"].lower(), "status": status,
                })
                registered = REGISTERED_SOURCE_TEST_RECEIPTS.get(track)
                if registered is None:
                    issues.append(f"source map includes an unregistered source-test receipt track: {track!r}")
                    continue
                expected_path, expected_status = registered
                if (path, status) != (expected_path, expected_status):
                    issues.append(
                        "source-test receipt track/path/status differs from its registered identity: "
                        f"{track!r}: expected {(expected_path, expected_status)!r}, got {(path, status)!r}"
                    )
                if track in seen_tracks:
                    issues.append(f"source map repeats a registered source-test receipt track: {track!r}")
                seen_tracks.add(track)
                # Open only the exact registered source-test receipt path. This
                # check never follows a source-map-supplied untrusted path.
                if path == expected_path:
                    try:
                        receipt_payload = load_json(safe_path(root, expected_path))
                        if receipt_payload.get("status") != expected_status:
                            issues.append(
                                "source-test receipt payload status differs from its registered identity: "
                                f"{track!r}: expected {expected_status!r}, got {receipt_payload.get('status')!r}"
                            )
                    except Exception as exc:
                        issues.append(f"cannot verify registered source-test receipt {track!r}: {type(exc).__name__}: {exc}")
            except (KeyError, ValueError):
                issues.append(f"malformed source-test receipt row: {row!r}")
        missing_tracks = set(REGISTERED_SOURCE_TEST_RECEIPTS) - seen_tracks
        if missing_tracks:
            issues.append(f"source map omits registered source-test receipt tracks: {sorted(missing_tracks)}")
    if canonical(contract.get("source_test_receipts")) != canonical(expected_receipts):
        issues.append("contract source_test_receipts differ from the exact source-map receipt table")

    finalization = contract.get("finalization", {})
    expected_finalization = {
        "immutable_baseline_contract_path": V06_CONTRACT["path"],
        "immutable_baseline_contract_bytes": V06_CONTRACT["bytes"],
        "immutable_baseline_contract_sha256": V06_CONTRACT["sha256"],
        "source_map_path": expected_map_path,
        "source_map_bytes": map_size,
        "source_map_sha256": map_sha,
        "source_closure_entry_count": len(rows),
        "source_test_receipt_count": len(expected_receipts),
        "execution_authorization_conferred": False,
    }
    if not isinstance(finalization, dict) or any(finalization.get(key) != value for key, value in expected_finalization.items()):
        issues.append("contract finalization metadata differs from the exact v06 baseline and v06 source map")
    return issues


def validate_v07_seal(
    root: Path,
    contract_path: Path,
    source_map_path: Path,
    seal_path: Path,
    schema_path: Path,
    mapped_paths: set[str],
    preseal_receipt_path: str,
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    seal = load_json(seal_path)
    schema = load_json(safe_path(root, schema_path))
    if schema.get("schema") != "FAS_E4_0_ARTIFACT_SEAL_V01" or schema.get("status") != "SEALED":
        issues.append("artifact-seal schema identity/status mismatch")
    schema_required = schema.get("required_fields", [])
    if not isinstance(schema_required, list) or not set(schema_required).issubset(seal):
        issues.append("v07 seal omits fields required by the normative artifact-seal schema")
    if seal.get("schema") != schema.get("schema") or seal.get("status") != "SEALED":
        issues.append("v07 seal schema/status mismatch")
    if seal.get("seal_id") != V07_SEAL_ID or seal.get("stage") != "E4_0_CONTRACT":
        issues.append("v07 seal identity/stage mismatch")
    if seal.get("path_root_kind") != "WORKSPACE_ROOT" or seal.get("contract_seal_root_sha256") is not None:
        issues.append("v07 contract seal root-kind or recursive root field is invalid")
    try:
        datetime.fromisoformat(str(seal["created_utc"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        issues.append("v07 seal created_utc is absent or not ISO-8601")
    contract_size, contract_sha = digest(contract_path)
    if seal.get("contract_sha256") != contract_sha:
        issues.append("v07 seal contract hash mismatch")
    contract = load_json(contract_path)
    if contract.get("contract_id") != V07_CONTRACT_ID or contract.get("status") != "SEALED":
        issues.append("v07 contract identity/status mismatch")
    if contract.get("supersedes") != expected_supersedes():
        issues.append("v07 supersedes metadata is not the exact sealed v06 contract/seal lineage")
    v06_roots = load_json(safe_path(root, V06_SEAL["path"]))
    if seal.get("exact_predecessor_roots") != v06_roots.get("exact_predecessor_roots"):
        issues.append("v07 seal predecessor roots differ from sealed v06 predecessor roots")

    entries = seal.get("entries")
    if not isinstance(entries, list) or not entries:
        return {}, issues + ["v07 seal entries must be a nonempty list"]
    required_fields = set(schema.get("entry_fields_exact", []))
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    valid_entries: list[dict[str, Any]] = []
    by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != required_fields:
            issues.append(f"malformed v07 seal entry: {entry!r}")
            continue
        artifact_id, rel = entry.get("artifact_id"), entry.get("path")
        if not isinstance(artifact_id, str) or not artifact_id or not isinstance(rel, str):
            issues.append(f"v07 seal member identity/path malformed: {entry!r}")
            continue
        if artifact_id in seen_ids or rel in seen_paths:
            issues.append(f"duplicate v07 seal artifact ID or path: {artifact_id} {rel}")
            continue
        seen_ids.add(artifact_id)
        seen_paths.add(rel)
        if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) or "\\" in rel or PurePosixPath(rel).as_posix() != rel or any(part in ("", ".", "..") for part in rel.split("/")):
            issues.append(f"unsafe/noncanonical v07 seal member path: {rel!r}")
            continue
        size, sha = entry.get("bytes"), entry.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            issues.append(f"invalid v07 seal member byte/hash values: {rel}")
            continue
        # Truth payloads remain unopened. Their immutable identity is carried by
        # the sealed map/manifest metadata and included in the independently
        # recomputed manifest root.
        if not is_truth_payload(rel):
            try:
                actual_size, actual_sha = digest(safe_path(root, rel))
                if (actual_size, actual_sha) != (size, sha):
                    issues.append(f"v07 seal member bytes/hash mismatch: {rel}")
            except Exception as exc:
                issues.append(f"cannot verify v07 seal member {rel}: {type(exc).__name__}: {exc}")
        normalized = {"artifact_id": artifact_id, "path": rel, "bytes": size, "sha256": sha}
        valid_entries.append(normalized)
        by_path[rel] = normalized
    if entries != sorted(entries, key=lambda item: str(item.get("artifact_id", "")).encode("utf-8") if isinstance(item, dict) else b""):
        issues.append("v07 seal entries are not in UTF-8 artifact_id order")
    if seal.get("entry_count") != len(entries):
        issues.append("v07 seal entry_count differs from member count")
    recomputed_root = artifact_root(valid_entries)
    if seal.get("root_sha256") != recomputed_root:
        issues.append(f"v07 seal root mismatch: recorded={seal.get('root_sha256')!r}, recomputed={recomputed_root}")

    contract_rel = contract_path.relative_to(root).as_posix()
    map_rel = source_map_path.relative_to(root).as_posix()
    v06_contract_rel, v06_seal_rel = V06_CONTRACT["path"], V06_SEAL["path"]
    must_include = mapped_paths | {contract_rel, map_rel, preseal_receipt_path, v06_contract_rel, v06_seal_rel}
    member_set_exact = seen_paths == must_include
    if not member_set_exact:
        missing, extra = sorted(must_include - seen_paths), sorted(seen_paths - must_include)
        if missing:
            issues.append(f"v07 seal omits required member paths: {missing[:20]}")
        if extra:
            issues.append(f"v07 seal has members outside exact source-map/lineage closure: {extra[:20]}")
    expected_lineage = (
        (V06_SUPERSESSION_IDS["contract"], V06_CONTRACT["path"], V06_CONTRACT["bytes"], V06_CONTRACT["sha256"]),
        (V06_SUPERSESSION_IDS["seal"], V06_SEAL["path"], V06_SEAL["manifest_bytes"], V06_SEAL["manifest_sha256"]),
    )
    for artifact_id, rel, size, sha in expected_lineage:
        entry = next((item for item in valid_entries if item["artifact_id"] == artifact_id), None)
        if entry != {"artifact_id": artifact_id, "path": rel, "bytes": size, "sha256": sha}:
            issues.append(f"v07 seal lacks exact v06 supersession member: {artifact_id}")
    if by_path.get(contract_rel, {}).get("sha256") != contract_sha or by_path.get(contract_rel, {}).get("bytes") != contract_size:
        issues.append("v07 contract is not sealed by its exact byte identity")
    if by_path.get(map_rel, {}).get("sha256") != digest(source_map_path)[1]:
        issues.append("v07 source map is not sealed by its exact byte identity")
    if seal_path.relative_to(root).as_posix() in seen_paths:
        issues.append("v07 seal manifest cannot be a member of itself")
    return {
        "path": seal_path.relative_to(root).as_posix(),
        "bytes": digest(seal_path)[0],
        "sha256": digest(seal_path)[1],
        "root_sha256": seal.get("root_sha256"),
        "recomputed_root_sha256": recomputed_root,
        "root_match": seal.get("root_sha256") == recomputed_root,
        "member_set_exact": member_set_exact,
        "expected_member_count": len(must_include),
        "entry_count": len(entries),
    }, issues


def validate_preseal_receipt(
    root: Path, receipt_path: str, contract_path: Path, source_map_path: Path,
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    try:
        path = safe_path(root, receipt_path)
        size, sha = digest(path)
        receipt = load_json(path)
        if receipt.get("status") != "E4_0_TRACK_E_PRESEAL_PASS_V07_CONTRACT_AND_SOURCE_MAP_CLOSED" or receipt.get("pass") is not True:
            issues.append("postseal audit requires the passing v07 preseal receipt")
        if receipt.get("contract", {}).get("sha256") != digest(contract_path)[1]:
            issues.append("preseal receipt contract hash differs from final contract")
        if receipt.get("source_map", {}).get("sha256") != digest(source_map_path)[1]:
            issues.append("preseal receipt source-map hash differs from final map")
        return {"path": receipt_path, "bytes": size, "sha256": sha}, issues
    except Exception as exc:
        return {}, [f"cannot validate v07 preseal receipt: {type(exc).__name__}: {exc}"]


def audit(
    root: Path,
    contract_path: Path,
    source_map_path: Path,
    seal_path: Path | None = None,
    schema_path: Path | None = None,
    preseal_receipt_path: str = V07_PRESEAL_DEFAULT,
    mode: str = "preseal",
) -> dict[str, Any]:
    issues: list[str] = []
    v06_contract_path = safe_path(root, V06_CONTRACT["path"])
    v06_seal_path = safe_path(root, V06_SEAL["path"])
    issues.extend(validate_v06_lineage(root, v06_contract_path, v06_seal_path))
    v06_contract = load_json(v06_contract_path)
    contract = load_json(contract_path)
    if contract.get("contract_id") != V07_CONTRACT_ID:
        issues.append("v07 contract ID mismatch")
    if contract.get("status") != "SEALED":
        issues.append("v07 contract must have SEALED status")
    if contract.get("supersedes") != expected_supersedes():
        issues.append("v07 contract supersedes metadata differs from exact v06 identities")
    issues.extend(validate_science_equality(v06_contract, contract))
    issues.extend(validate_inherited_roots(contract))
    checked_sources, tables, mapped_paths, source_issues = validate_source_bindings(root, contract_path, source_map_path)
    issues.extend(source_issues)
    issues.extend(validate_contract_source_closure(root, contract, source_map_path, tables))
    verified_inputs, input_issues = validate_input_bindings(root, tables)
    issues.extend(input_issues)
    seal_info = None
    preseal_info = None
    if seal_path is not None:
        if schema_path is None:
            issues.append("seal schema path required when auditing a sealed contract")
        else:
            seal_info, seal_issues = validate_v07_seal(root, contract_path, source_map_path, seal_path, schema_path, mapped_paths, preseal_receipt_path)
            issues.extend(seal_issues)
            preseal_info, preseal_issues = validate_preseal_receipt(root, preseal_receipt_path, contract_path, source_map_path)
            issues.extend(preseal_issues)
    if mode == "preseal" and seal_path is not None:
        issues.append("preseal mode must not consume a contract seal")
    if mode == "postseal" and seal_path is None:
        issues.append("postseal mode requires a contract seal")
    success_status = (
        "E4_0_TRACK_E_PRESEAL_PASS_V07_CONTRACT_AND_SOURCE_MAP_CLOSED" if mode == "preseal"
        else "E4_0_TRACK_E_POSTSEAL_PASS_V07_SEAL_ROOT_AND_MEMBERS_RECOMPUTED"
    )
    return {
        "receipt_id": "FAS_E4_0_TRACK_E_V07_PRESEAL_AUDIT_V01" if mode == "preseal" else "FAS_E4_0_TRACK_E_V07_POSTSEAL_AUDIT_V01",
        "status": success_status if not issues else f"E4_0_TRACK_E_{mode.upper()}_STOP_MISMATCHES_RECORDED_V07",
        "mode": mode.upper(),
        "contract": {"path": contract_path.relative_to(root).as_posix(), "bytes": digest(contract_path)[0], "sha256": digest(contract_path)[1]},
        "source_map": {"path": source_map_path.relative_to(root).as_posix(), "bytes": digest(source_map_path)[0], "sha256": digest(source_map_path)[1]},
        "v06_lineage": {"contract": V06_CONTRACT, "seal": V06_SEAL},
        "science_fields_compared": list(SCIENCE_FIELDS),
        "inherited_roots": {"population": INHERITED_POPULATION, "parity_panel": INHERITED_PARITY_PANEL},
        "verified_sources_and_receipts": checked_sources,
        "verified_nontruth_frozen_inputs": verified_inputs,
        "final_seal": seal_info,
        "preseal_receipt": preseal_info,
        "population_truth_files_opened": False,
        "template_or_joint_truth_opened": False,
        "issues": issues,
        "pass": not issues,
        "scope": "Contract/source/seal integrity only; no truth payload, population labels, tokenizer, model, CUDA, scoring, or runtime behavior access.",
    }


def main() -> int:
    workspace = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=V07_CONTRACT_DEFAULT)
    parser.add_argument("--source-map", default=V07_MAP_DEFAULT)
    parser.add_argument("--mode", choices=("preseal", "postseal"), default="preseal")
    parser.add_argument("--seal", default=None)
    parser.add_argument("--seal-schema", default=SEAL_SCHEMA_DEFAULT)
    parser.add_argument("--preseal-receipt", default=V07_PRESEAL_DEFAULT)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    contract_path = safe_path(workspace, args.contract)
    map_path = safe_path(workspace, args.source_map)
    seal_path = safe_path(workspace, args.seal) if args.seal else None
    schema_path = safe_path(workspace, args.seal_schema) if seal_path else None
    result = audit(workspace, contract_path, map_path, seal_path, schema_path, args.preseal_receipt, args.mode)
    output = args.output or (V07_PRESEAL_DEFAULT if args.mode == "preseal" else V07_POSTSEAL_DEFAULT)
    if output:
        output_path = safe_path(workspace, output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output_path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        except FileExistsError:
            print(f"refusing to overwrite immutable audit receipt: {output_path}", file=sys.stderr)
            return 2
    print(json.dumps({"status": result["status"], "issue_count": len(result["issues"]), "pass": result["pass"]}, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
