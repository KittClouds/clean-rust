#!/usr/bin/env python3
"""Independent E4-0 contract/source-map closure audit (Track E).

This deliberately audits serialized identity and source bindings only. It does
not import or execute population, tokenizer, model, CUDA, scoring, or label code.
The output is create-once so an audit receipt cannot be silently overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from audit_e4_0_track_e_seal_v06 import artifact_root, project_path, recompute_seal


BASELINE_SHA256 = "e2910965b53313a34c3a7d870075d83dbc9e035a230fc68f3c177c12c71e9fcf"
BASELINE_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-CONTRACT-DRAFT-v05.json"
CONTRACT_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v06-final.json"
SOURCE_MAP_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v05.md"
PRESEAL_RECEIPT_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-preseal-receipt-v03.json"
POSTSEAL_RECEIPT_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-postseal-receipt-v02.json"
SEAL_SCHEMA_PATH = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-artifact-seal-schema-v01.json"

FIXED_RECEIPTS = {
    "audits/e4-0-track-a/track-a-receipt-v03.json": "1d992466421569ed1318ed9132c02902eefa9cc3341df150c857a26c69f6d51e",
    "audits/e4-0-track-b-v02/track-b-source-tests-v01.json": "a1e691405e3aea33845aacdf14dbe24617569b64f1a9450c63378d80d304dbbf",
    "audits/e4-0-track-c-v02/track-c-source-tests-v01.json": "04514426de6e72ea0dcc63f2b5f1e72f37620da11ec01f297da1196fa11614a1",
    "audits/e4-0-track-d/track-d-receipt-v06.json": "d53cf6bf67700746875fb1ead3572006bc36a12163156689b9c8287dfa3bfc0a",
    "audits/e4-0-auth-issuer-v02/source-tests-v01.json": "22c4d3137e9adb05f3312be638c02517f39f816bf50bb9711d8498c54c7291ff",
}

IMMUTABLE_SECTIONS = ("predecessors", "representation_abi", "population", "parity", "fresh_qualification", "truth_access", "resources", "phase_gates", "stop_rule", "E4_A_dependency")

PREDECESSOR_SEALS = {
    "e0_v10_root_sha256": (
        "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e0-seal-v10.json",
        "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd",
    ),
    "e1_v04_root_sha256": (
        r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04\e1-seal-v01.json",
        "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03",
    ),
    "e2_v07_root_sha256": (
        r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07\e2-v07-seal.json",
        "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a",
    ),
    "e3_v02_bundle_root_sha256": (
        r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02\e3-v02-seal.json",
        "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1",
    ),
    "e3_v02_score_replay_root_sha256": (
        "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e3-score-v02-seal.json",
        "a104bffedbc3e31268c0f1c0103ad4326add5a9da93816007904b70cdf3c7d1f",
    ),
}


def digest(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_markdown_tables(path: Path) -> list[tuple[list[str], list[dict[str, str]]]]:
    text = path.read_text(encoding="utf-8")
    tables: list[tuple[list[str], list[dict[str, str]]]] = []
    headers: list[str] | None = None
    records: list[dict[str, str]] = []

    def close_table() -> None:
        nonlocal headers, records
        if headers is not None and records:
            tables.append((headers, records))
        headers, records = None, []

    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            close_table()
            continue
        cells = [part.strip().strip("` ") for part in stripped.strip("|").split("|")]
        normalized = [re.sub(r"[^a-z0-9]+", "", cell.lower()) for cell in cells]
        if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        if headers is None and any("path" in cell or cell in ("file", "artifact") for cell in normalized) and any("sha256" in cell or cell == "sha" for cell in normalized):
            headers = normalized
            continue
        if headers is None or len(cells) != len(headers):
            continue
        records.append({header: value for header, value in zip(headers, cells)})
    close_table()
    return tables


def parse_source_map(path: Path) -> tuple[list[dict[str, Any]], list[tuple[list[str], list[dict[str, str]]]]]:
    """Read the uniquely designated source-file table from the v05 Markdown map."""
    tables = parse_markdown_tables(path)
    source_tables = [(headers, records) for headers, records in tables if headers == ["path", "bytes", "sha256", "role"]]
    if len(source_tables) != 1:
        raise ValueError(f"expected exactly one source-file table, found {len(source_tables)}")
    _headers, records = source_tables[0]
    rows: list[dict[str, Any]] = []
    for row_number, record in enumerate(records, 1):
        path_value = record["path"].strip().strip("` ")
        sha_value = record["sha256"].strip().strip("` ").lower()
        size_value = record["bytes"].strip().replace(",", "")
        if not path_value or not re.fullmatch(r"[0-9a-f]{64}", sha_value) or not size_value.isdecimal():
            raise ValueError(f"malformed source-file row {row_number}: {record}")
        if Path(path_value).is_absolute() or ".." in Path(path_value).parts:
            raise ValueError(f"source-file path must be repo-relative and normalized: {path_value}")
        rows.append({"path": path_value, "sha256": sha_value, "bytes": int(size_value), "role": record["role"]})
    if not rows:
        raise ValueError("source-file table has no rows")
    return rows, tables


def verify_map_unique_path_bindings(tables: list[tuple[list[str], list[dict[str, str]]]]) -> list[str]:
    seen: dict[str, str] = {}
    issues: list[str] = []
    for _headers, records in tables:
        for row in records:
            for header, value in row.items():
                if "path" not in header:
                    continue
                normalized = value.strip().strip("` ").replace("\\", "/")
                if not normalized:
                    continue
                if normalized in seen:
                    issues.append(f"source-map path is repeated in Markdown tables: {normalized} ({seen[normalized]} and {row})")
                else:
                    seen[normalized] = str(row)
    return issues


def verify_receipt_bindings(tables: list[tuple[list[str], list[dict[str, str]]]]) -> list[str]:
    issues: list[str] = []
    all_rows = [row for _headers, rows in tables for row in rows]
    for rel, expected_sha in FIXED_RECEIPTS.items():
        matches = []
        for row in all_rows:
            values = list(row.values())
            path_match = any(value.replace("\\", "/").rstrip("` ").endswith(rel) for value in values)
            sha_match = any(value.strip().strip("` ").lower() == expected_sha for value in values)
            if path_match and sha_match:
                matches.append(row)
        if len(matches) != 1:
            issues.append(f"source map must bind {rel} and its fixed SHA exactly once; found {len(matches)}")
    return issues


def mapped_workspace_paths(tables: list[tuple[list[str], list[dict[str, str]]]]) -> tuple[set[str], list[str]]:
    paths: set[str] = set()
    issues: list[str] = []
    for _headers, records in tables:
        for row in records:
            path_values = [value.strip().strip("` ").replace("\\", "/") for header, value in row.items() if "path" in header]
            if not path_values:
                continue
            for value in path_values:
                if not value:
                    continue
                if Path(value).is_absolute() or re.match(r"^[A-Za-z]:/", value):
                    continue  # external predecessor diagnostic path
                if value.startswith("experiments/"):
                    paths.add(value)
                else:
                    issues.append(f"map table path is not workspace-root-relative: {value}")
    return paths, issues


def deep_diffs(left: Any, right: Any, prefix: str = "") -> list[str]:
    if type(left) is not type(right):
        return [prefix or "$"]
    if isinstance(left, dict):
        diffs: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{prefix}.{key}" if prefix else key
            if key not in left or key not in right:
                diffs.append(child)
            else:
                diffs.extend(deep_diffs(left[key], right[key], child))
        return diffs
    if isinstance(left, list):
        if len(left) != len(right):
            return [prefix or "$"]
        return [path for index, (a, b) in enumerate(zip(left, right)) for path in deep_diffs(a, b, f"{prefix}[{index}]")]
    return [] if left == right else [prefix or "$"]


def verify_source_rows(root: Path, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    checked: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: set[str] = set()
    for row in rows:
        rel = row["path"]
        if rel in seen:
            issues.append(f"duplicate source-map path: {rel}")
            continue
        seen.add(rel)
        try:
            file_path = project_path(root, rel)
            size, sha = digest(file_path)
            expected_size = row.get("bytes")
            if expected_size is not None and size != expected_size:
                issues.append(f"byte-count mismatch {rel}: map={expected_size}, actual={size}")
            if sha != row["sha256"]:
                issues.append(f"SHA-256 mismatch {rel}: map={row['sha256']}, actual={sha}")
            checked.append({"path": rel, "bytes": size, "sha256": sha})
        except Exception as exc:  # exact file failure is part of the receipt
            issues.append(f"cannot verify {rel}: {type(exc).__name__}: {exc}")
    expected = expected_source_closure(root)
    actual = {row["path"] for row in rows}
    for missing in sorted(expected - actual):
        issues.append(f"source-map closure omits discovered source/build/test file: {missing}")
    for extra in sorted(actual - expected):
        issues.append(f"source-map closure contains unclassified file: {extra}")
    return checked, issues


def expected_source_closure(root: Path) -> set[str]:
    project = root / "experiments/fas-frozen-observer-bundle-engineering-v01"
    suffixes = {".rs", ".toml", ".lock", ".py", ".md"}
    roots = (
        "source/e4-population-v02", "source/panel-generator-v04",
        "source/e4-support-plan-v11", "source/scripts/e4_fresh_scorer_v02",
        "source/scripts/e4_independent_audit_v02",
    )
    found: set[str] = set()
    for rel_root in roots:
        directory = project / rel_root
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in suffixes:
                found.add(path.relative_to(root).as_posix())
    explicit = (
        "source/scripts/e4_online_parity_v02.py", "source/scripts/e4_runner_common_v02.py",
        "source/scripts/e4_runner_artifacts_v02.py", "source/scripts/e4_gpu_lease_v01.py",
        "source/scripts/e4_runner_modes_v02.py", "source/tests/test_e4_runner_v02.py",
        "source/scripts/issue_e4_stage_authorization_v02.py", "source/tests/test_e4_stage_authorization_v02.py",
        "source/scripts/build_e4_0_contract_draft_v05.py", "source/scripts/audit_e4_0_contract_draft_v05.py",
        "source/scripts/build_e4_0_source_map_v04.py", "source/scripts/build_e4_0_source_map_v05.py",
        "source/scripts/finalize_e4_0_contract_v05.py", "source/scripts/finalize_e4_0_contract_v06.py",
        "source/scripts/seal_e4_0_contract_v05.py", "source/scripts/seal_e4_0_contract_v06.py",
        "audits/e4-0-track-e/audit_e4_0_track_e_v06.py",
        "audits/e4-0-track-e/audit_e4_0_track_e_seal_v06.py",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v06.py",
        "audits/e4-0-track-e/fixtures/sealed-v05-source-map-v04.md",
        "audits/e4-0-track-b-v02/attempt-note-v01.json",
        "audits/e4-0-track-e/history/build_e4_0_source_map_v05-zero-byte-attempt-v01.py",
        "audits/e4-0-track-e/history/build_e4_0_source_map_v05-zero-byte-attempt-v01.json",
    )
    for rel in explicit:
        if (project / rel).is_file():
            found.add((project / rel).relative_to(root).as_posix())
    track_d = project / "source/scripts/e4_independent_audit_v02"
    if track_d.is_dir():
        for path in track_d.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".md"}:
                found.add(path.relative_to(root).as_posix())
    return found


def false_authorization_flags(contract: dict[str, Any]) -> list[str]:
    found: list[str] = []
    def visit(value: Any, prefix: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                path = f"{prefix}.{key}" if prefix else key
                if ("authoriz" in key.lower() or key.endswith("_authorized")) and isinstance(child, bool) and child is not False:
                    found.append(f"{path} must be false; got {child!r}")
                visit(child, path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{prefix}[{index}]")
    visit(contract)
    return found


def validate_contract(root: Path, baseline: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    baseline_projection = json.loads(json.dumps(baseline))
    final_projection = json.loads(json.dumps(contract))
    permitted_top_level = {
        "contract_id", "status", "finalized_utc", "implementation_sources", "supersedes",
        "source_test_receipts", "finalization", "implementation_sources_not_yet_bound",
        "draft_blockers_before_freeze",
    }
    for projection in (baseline_projection, final_projection):
        for key in permitted_top_level:
            projection.pop(key, None)
        for block in (baseline_projection, final_projection):
            design = block.get("design_inputs")
            if isinstance(design, dict):
                for key in tuple(design):
                    if key.startswith("implementation_source_map_v03_") or key.startswith("implementation_source_map_v04_") or key.startswith("implementation_source_map_v05_"):
                        design.pop(key)
    differences = deep_diffs(baseline_projection, final_projection)
    if differences:
        issues.append("non-permitted contract changes versus immutable v05 draft: " + ", ".join(differences[:20]))
    if contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06":
        issues.append("final contract_id must be FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06")
    expected_supersedes = {
        "contract": {
            "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V05",
            "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v05-final.json",
            "bytes": 39944,
            "sha256": "ad709bd1496536e6fb1464bd89a06ec0eed552b89ef4159bfc1aa0f406fcc71a",
        },
        "seal": {
            "seal_id": "FAS_E4_0_CONTRACT_V05_SEAL",
            "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v05-seal.json",
            "manifest_bytes": 29668,
            "manifest_sha256": "434e4472275adbd6514e5b6a0e8d905c7a283ea6ea294edc0068c050336cd9eb",
            "root_sha256": "38fa25b9433319fc706a1d7fc1e56f20a267f30d467c42ac75ff0850ec656fd1",
            "contract_member_artifact_id": "E4_0_CONTRACT_V05_FINAL",
        },
    }
    if contract.get("supersedes") != expected_supersedes:
        issues.append("v06 supersedes metadata differs from the immutable v05 contract and seal")
    if false_authorization_flags(contract):
        issues.extend(false_authorization_flags(contract))
    required_false_flags = {
        "authorization": (
            "population_generation_authorized", "tokenizer_contact_authorized", "model_contact_authorized",
            "feature_extraction_authorized", "evaluation_label_opening_authorized", "scoring_authorized",
            "fitting_authorized", "E4_A_authorized",
        ),
        "execution_identity": (
            "model_contact_authorized", "label_opening_authorized", "scoring_authorized", "E4_A_authorized",
            "population_generation_authorized", "tokenizer_contact_authorized", "feature_extraction_authorized",
        ),
    }
    for section, names in required_false_flags.items():
        block = contract.get(section)
        if not isinstance(block, dict):
            issues.append(f"required closed authorization block missing: {section}")
            continue
        for name in names:
            if block.get(name) is not False:
                issues.append(f"closed authorization flag {section}.{name} must remain false; got {block.get(name)!r}")
    status = str(contract.get("status", "")).upper()
    if status != "SEALED":
        issues.append(f"final contract status must be SEALED: {status!r}")
    sources = contract.get("implementation_sources", contract.get("implementation_source_bindings", {}))
    if isinstance(sources, dict):
        required = ("e4_population_generator", "e4_online_feature_and_parity_runner", "e4_fresh_scorer", "e4_stage_authorization_issuer", "e4_independent_auditor")
        for name in required:
            if not sources.get(name):
                issues.append(f"implementation source is not bound: {name}")
    else:
        issues.append("final contract implementation source bindings are malformed")
    return issues


def validate_final_bindings(
    root: Path,
    baseline: dict[str, Any],
    contract: dict[str, Any],
    source_rows: list[dict[str, Any]],
    tables: list[tuple[list[str], list[dict[str, str]]]],
    map_path: Path,
    map_bytes: int,
    map_sha: str,
    baseline_bytes: int,
) -> list[str]:
    issues: list[str] = []
    expected_path = map_path.relative_to(root).as_posix()
    design = contract.get("design_inputs", {})
    map_binding = {
        "implementation_source_map_v05_path": expected_path,
        "implementation_source_map_v05_sha256": map_sha,
        "implementation_source_map_v05_bytes": map_bytes,
    }
    for key, expected in map_binding.items():
        if design.get(key) != expected:
            issues.append(f"final source-map design binding mismatch {key}: expected={expected!r}, actual={design.get(key)!r}")
    if any(key.startswith(("implementation_source_map_v03_", "implementation_source_map_v04_")) for key in design):
        issues.append("final design_inputs retains an obsolete source-map version binding")
    for blocker_key in ("draft_blockers_before_freeze", "draft_blockers"):
        blockers = contract.get(blocker_key)
        if blockers not in (None, [], {}):
            issues.append(f"final contract retains uncleared blockers in {blocker_key}")
    if "implementation_sources_not_yet_bound" in contract:
        issues.append("final contract retains implementation_sources_not_yet_bound")

    sources = contract.get("implementation_sources")
    expected_sources: dict[str, Any] = {
        "source_map": {"path": expected_path, "bytes": map_bytes, "sha256": map_sha}
    }
    predicates = {
        "e4_population_generator": lambda p: any(token in p for token in (
            "/source/e4-population-v02/", "/source/panel-generator-v04/", "/source/e4-support-plan-v11/")),
        "e4_online_feature_and_parity_runner": lambda p: (
            "/source/scripts/e4_online_parity_v02.py" in p or "/source/scripts/e4_runner_" in p
            or "/source/scripts/e4_gpu_lease_v01.py" in p or "/source/tests/test_e4_runner_v02.py" in p),
        "e4_fresh_scorer": lambda p: "/source/scripts/e4_fresh_scorer_v02/" in p,
        "e4_stage_authorization_issuer": lambda p: (
            "/source/scripts/issue_e4_stage_authorization_v02.py" in p
            or "/source/tests/test_e4_stage_authorization_v02.py" in p),
        "e4_independent_auditor": lambda p: (
            "/source/scripts/e4_independent_audit_v02/" in p
            or p.endswith("/audits/e4-0-track-e/audit_e4_0_track_e_v06.py")
            or p.endswith("/audits/e4-0-track-e/audit_e4_0_track_e_seal_v06.py")
            or p.endswith("/audits/e4-0-track-e/test_audit_e4_0_track_e_v06.py")),
    }
    for name, predicate in predicates.items():
        matched = [row for row in source_rows if predicate(row["path"])]
        if not matched:
            issues.append(f"source closure has no rows for implementation binding {name}")
        expected_sources[name] = {"files": matched}
    if canonical(sources) != canonical(expected_sources):
        issues.append("implementation_sources does not exactly bind the source-map rows by frozen role")

    receipt_tables = [(headers, rows) for headers, rows in tables
                      if headers == ["track", "path", "bytes", "sha256", "status"]]
    if len(receipt_tables) != 1:
        issues.append(f"expected one source validation receipt table, found {len(receipt_tables)}")
        expected_receipts: list[dict[str, Any]] = []
    else:
        expected_receipts = []
        for row in receipt_tables[0][1]:
            try:
                expected_receipts.append({
                    "track": row["track"], "path": row["path"], "bytes": int(row["bytes"].replace(",", "")),
                    "sha256": row["sha256"].lower(), "status": row["status"],
                })
            except (KeyError, ValueError):
                issues.append(f"malformed source validation receipt row: {row!r}")
    if canonical(contract.get("source_test_receipts")) != canonical(expected_receipts):
        issues.append("final source_test_receipts differ from the source-map validation receipt table")

    expected_finalization = {
        "immutable_draft_path": BASELINE_DEFAULT,
        "immutable_draft_bytes": baseline_bytes,
        "immutable_draft_sha256": BASELINE_SHA256,
        "source_map_path": expected_path,
        "source_map_bytes": map_bytes,
        "source_map_sha256": map_sha,
        "source_closure_entry_count": len(source_rows),
        "source_test_receipt_count": len(expected_receipts),
        "execution_authorization_conferred": False,
    }
    finalization = contract.get("finalization")
    if not isinstance(finalization, dict) or any(finalization.get(k) != v for k, v in expected_finalization.items()):
        issues.append("finalization metadata does not match the immutable draft and source-map identities")
    try:
        datetime.fromisoformat(str(contract["finalized_utc"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        issues.append("finalized_utc is absent or not ISO-8601")
    return issues


def validate_design_input_bindings(root: Path, contract: dict[str, Any], tables: list[tuple[list[str], list[dict[str, str]]]]) -> list[str]:
    issues: list[str] = []
    design = contract.get("design_inputs")
    if not isinstance(design, dict):
        return ["contract design_inputs block is missing or malformed"]
    mapped_rows = [row for _headers, rows in tables for row in rows]
    source_map_binding_found = False
    for key, value in design.items():
        if not key.endswith("_path") or not isinstance(value, str):
            continue
        stem = key[:-5]
        sha = design.get(stem + "_sha256")
        byte_count = design.get(stem + "_bytes")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
            issues.append(f"design input path lacks a 64-character SHA-256 binding: design_inputs.{key}")
            continue
        if "source_map" in key and "v05" in key:
            source_map_binding_found = True
        try:
            if value.startswith("experiments/"):
                path = project_path(root, value)
                table_path = value
            elif Path(value).is_absolute():
                path = Path(value)
                table_path = value.replace("\\", "/")
            else:
                path = project_path(root / "experiments/fas-frozen-observer-bundle-engineering-v01", value)
                table_path = ("experiments/fas-frozen-observer-bundle-engineering-v01/" + value.replace("\\", "/"))
            actual_bytes, actual_sha = digest(path)
            if actual_sha.lower() != sha.lower():
                issues.append(f"design input hash mismatch {key}: expected={sha}, actual={actual_sha}")
            if byte_count is not None and actual_bytes != byte_count:
                issues.append(f"design input byte-count mismatch {key}: expected={byte_count}, actual={actual_bytes}")
            # The map cannot list itself in its own inputs; other frozen inputs must appear once.
            if not ("source_map" in key and "v05" in key):
                matches = [row for row in mapped_rows if any(h.endswith("path") for h in row) and row.get("path", row.get("inputpath", "")).replace("\\", "/").rstrip("` ") == table_path]
                if matches:
                    map_hash = next((row.get("sha256", "").strip().strip("` ") for row in matches), "")
                    if map_hash.lower() != sha.lower():
                        issues.append(f"source-map frozen-input hash disagrees with contract for {key}")
                elif not ("source_map" in key and "v05" in key):
                    issues.append(f"design input is absent from the source-map frozen-input table: {table_path}")
        except Exception as exc:
            issues.append(f"cannot verify design input {key}: {type(exc).__name__}: {exc}")
    if not source_map_binding_found:
        issues.append("final contract lacks an implementation source-map v05 path/hash binding")
    return issues


def validate_resource_arithmetic(contract: dict[str, Any], root: Path) -> list[str]:
    issues: list[str] = []
    resources = contract.get("resources")
    abi = contract.get("representation_abi")
    inputs = contract.get("design_inputs")
    if not isinstance(resources, dict) or not isinstance(abi, dict) or not isinstance(inputs, dict):
        return ["resources, representation_abi, or design_inputs block is missing"]
    row_count = resources.get("feature_rows")
    dimension = abi.get("feature_dimension")
    dtype = abi.get("serialization_dtype")
    if not isinstance(row_count, int) or row_count < 1:
        return ["resources.feature_rows is missing or invalid"]
    if not isinstance(dimension, int) or dimension < 1 or dtype != "little-endian float32":
        issues.append("representation ABI feature dimension/dtype is not the frozen float32 form")
        return issues
    bytes_per_row = dimension * 4
    checks = {
        "feature_cache_bytes": row_count * bytes_per_row,
        "feature_cache_atomic_staging_bytes": row_count * bytes_per_row,
        "feature_cache_final_plus_staging_bytes": 2 * row_count * bytes_per_row,
        "panel_input_jsonl_max_bytes": row_count * 1024,
        "label_jsonl_max_bytes": row_count * 1024,
        "row_manifest_jsonl_max_bytes": row_count * 512,
        "row_level_artifact_max_bytes": row_count * (1024 + 1024 + 512),
    }
    for key, expected in checks.items():
        if resources.get(key) != expected:
            issues.append(f"resource arithmetic mismatch {key}: expected={expected}, actual={resources.get(key)!r}")
    peak_fields = (
        "feature_cache_bytes", "feature_cache_atomic_staging_bytes", "panel_input_jsonl_max_bytes",
        "label_jsonl_max_bytes", "row_manifest_jsonl_max_bytes", "other_persistent_artifact_max_bytes",
        "temporary_artifact_max_bytes",
    )
    if all(isinstance(resources.get(key), int) for key in peak_fields):
        peak = sum(resources[key] for key in peak_fields)
        if resources.get("projected_peak_bytes_before_free_space_reserve") != peak:
            issues.append(f"resource peak arithmetic mismatch: expected={peak}, actual={resources.get('projected_peak_bytes_before_free_space_reserve')!r}")
    else:
        issues.append("resource peak fields are incomplete or non-integer")
    if resources.get("minimum_free_space_after_projected_peak_fraction") != 0.1:
        issues.append("free-space reserve fraction changed from the frozen 10 percent")
    if resources.get("feature_cache_bytes_formula") != "8192 * all extracted E4 rows" or resources.get("feature_cache_atomic_staging_bytes_formula") != "8192 * all extracted E4 rows":
        issues.append("feature-cache resource formulas changed from 8,192 bytes per extracted row")
    population = contract.get("population", {})
    support = population.get("support", {}) if isinstance(population, dict) else {}
    if support.get("construction_target_rows_per_required_class") != 250 or support.get("scoring_minimum_rows_per_class") != 200:
        issues.append("population support target/floor differs from frozen v05")
    support_path = inputs.get("symbolic_support_plan_path")
    support_sha = inputs.get("symbolic_support_plan_sha256")
    support_bytes = inputs.get("symbolic_support_plan_bytes")
    try:
        if not isinstance(support_path, str) or not isinstance(support_sha, str):
            raise ValueError("support plan path/hash missing")
        path = project_path(root / "experiments/fas-frozen-observer-bundle-engineering-v01", support_path)
        actual_bytes, actual_sha = digest(path)
        if actual_sha.lower() != support_sha.lower() or (support_bytes is not None and actual_bytes != support_bytes):
            issues.append("bound symbolic support plan bytes/hash mismatch")
        plan = load_json(path)
        plan_expected = {
            "unique_feature_rows_all_materialized_strata": row_count,
            "rows_in_primary_seen_and_lexical_population": row_count // 2,
            "rows_in_heldout_template_population": row_count // 2,
            "feature_bytes_per_row": bytes_per_row,
        }
        for key, expected in plan_expected.items():
            if plan.get(key) != expected:
                issues.append(f"support plan resource binding mismatch {key}: expected={expected}, actual={plan.get(key)!r}")
        values: list[int] = []
        def collect_ints(value: Any) -> None:
            if isinstance(value, int) and not isinstance(value, bool):
                values.append(value)
            elif isinstance(value, list):
                for child in value:
                    collect_ints(child)
            elif isinstance(value, dict):
                for child in value.values():
                    collect_ints(child)
        collect_ints(plan.get("minimum_support_by_endpoint_and_stratum"))
        if not values or min(values) < 250:
            issues.append(f"support plan selected class support is below 250 or absent: minimum={min(values) if values else None}")
        if plan.get("minimum_class_count_at_previous_prefix") != 248 or plan.get("immediately_previous_whole_quartet_prefix_meets_target") is not False:
            issues.append("support plan does not establish the immediately prior prefix failed the 250-row target")
    except Exception as exc:
        issues.append(f"cannot verify support-plan resource binding: {type(exc).__name__}: {exc}")
    return issues


def verify_predecessor_roots(root: Path, contract: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    recorded: dict[str, str] = {}
    issues: list[str] = []
    predecessors = contract.get("predecessors")
    if not isinstance(predecessors, dict):
        return recorded, ["final contract predecessor section is missing or malformed"]
    for key, (path_value, expected_root) in PREDECESSOR_SEALS.items():
        recorded[key] = expected_root
        if predecessors.get(key) != expected_root:
            issues.append(f"contract predecessor mismatch {key}: expected={expected_root}, actual={predecessors.get(key)!r}")
            continue
        try:
            path = project_path(root, path_value) if not Path(path_value).is_absolute() else Path(path_value)
            seal = load_json(path)
            if seal.get("root_sha256") != expected_root:
                issues.append(f"predecessor seal root mismatch {path_value}: expected={expected_root}, actual={seal.get('root_sha256')!r}")
        except Exception as exc:
            issues.append(f"cannot verify predecessor seal {path_value}: {type(exc).__name__}: {exc}")
    return recorded, issues


def check_fixed_receipts(root: Path) -> tuple[list[dict[str, str]], list[str]]:
    checked: list[dict[str, str]] = []
    issues: list[str] = []
    expected_status = {
        "audits/e4-0-track-a/track-a-receipt-v03.json": "TRACK_A_COMPLETE_PREAUTHORIZATION",
        "audits/e4-0-track-b-v02/track-b-source-tests-v01.json": "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
        "audits/e4-0-track-c-v02/track-c-source-tests-v01.json": "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
        "audits/e4-0-track-d/track-d-receipt-v06.json": "TRACK_D_COMPLETE_PREAUTHORIZATION",
        "audits/e4-0-auth-issuer-v02/source-tests-v01.json": "PASS_SYNTHETIC_TESTS",
    }
    for rel, expected in FIXED_RECEIPTS.items():
        try:
            path = project_path(root, "experiments/fas-frozen-observer-bundle-engineering-v01/" + rel)
            size, actual = digest(path)
            if actual != expected:
                issues.append(f"receipt SHA-256 mismatch {rel}: expected={expected}, actual={actual}")
            receipt = load_json(path)
            status = receipt.get("status")
            if status != expected_status[rel]:
                issues.append(f"receipt status mismatch {rel}: expected={expected_status[rel]}, actual={status!r}")
            checked.append({"path": rel, "bytes": str(size), "sha256": actual, "status": str(status)})
        except Exception as exc:
            issues.append(f"cannot verify receipt {rel}: {type(exc).__name__}: {exc}")
    return checked, issues


def check_track_e_unit_receipt(root: Path, tables: list[tuple[list[str], list[dict[str, str]]]]) -> tuple[dict[str, str], list[str]]:
    rel = "audits/e4-0-track-e/track-e-source-tests-v08.json"
    issues: list[str] = []
    try:
        path = project_path(root, "experiments/fas-frozen-observer-bundle-engineering-v01/" + rel)
        size, sha = digest(path)
        receipt = load_json(path)
        if receipt.get("status") != "TRACK_E_SOURCE_TESTS_PASS_PREMAP_UNIT_TESTS":
            issues.append(f"Track E source/unit receipt status mismatch: {receipt.get('status')!r}")
        if receipt.get("tests") != {"discovered": 8, "passed": 6, "skipped": 2, "failed": 0}:
            issues.append(f"Track E pre-map test summary mismatch: {receipt.get('tests')!r}")
        for row in receipt.get("sources", []):
            member = project_path(root, row["path"])
            member_size, member_sha = digest(member)
            if member_size != row.get("bytes") or member_sha != row.get("sha256"):
                issues.append(f"Track E source-test receipt source identity mismatch: {row.get('path')}")
        expected_sources = {
            "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/audit_e4_0_track_e_v06.py",
            "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/audit_e4_0_track_e_seal_v06.py",
            "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/test_audit_e4_0_track_e_v06.py",
            "experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/seal_e4_0_contract_v06.py",
        }
        if {row.get("path") for row in receipt.get("sources", [])} != expected_sources:
            issues.append("Track E source-test receipt does not bind exactly the auditor, seal helper, test file, and final sealer")
        receipt_tables = [(header, rows) for header, rows in tables if header == ["track", "path", "bytes", "sha256", "status"]]
        matching_rows = [row for _header, rows in receipt_tables for row in rows if row.get("path") == "experiments/fas-frozen-observer-bundle-engineering-v01/" + rel]
        if len(matching_rows) != 1:
            issues.append(f"source map must bind Track E source-test receipt exactly once; found {len(matching_rows)}")
        elif (matching_rows[0].get("bytes", "").replace(",", "") != str(size)
              or matching_rows[0].get("sha256", "").lower() != sha
              or matching_rows[0].get("status") != receipt.get("status")):
            issues.append("source-map Track E receipt row differs from the exact source-test receipt")
        return {"path": rel, "bytes": str(size), "sha256": sha, "status": str(receipt.get("status"))}, issues
    except Exception as exc:
        return {}, [f"cannot verify Track E source/unit receipt: {type(exc).__name__}: {exc}"]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[4]
    project_rel = "experiments/fas-frozen-observer-bundle-engineering-v01/"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=project_rel + CONTRACT_DEFAULT.split("engineering-v01/", 1)[1])
    parser.add_argument("--source-map", default=project_rel + SOURCE_MAP_DEFAULT.split("engineering-v01/", 1)[1])
    parser.add_argument("--baseline", default=BASELINE_DEFAULT)
    parser.add_argument("--mode", choices=("preseal", "postseal"), default="preseal")
    parser.add_argument("--output", default=None)
    parser.add_argument("--seal-manifest", default=None, help="required for --mode postseal")
    parser.add_argument("--preseal-receipt", default=PRESEAL_RECEIPT_DEFAULT, help="prior create-once PRESEAL_PASS receipt")
    args = parser.parse_args()
    contract_path = project_path(repo_root, args.contract)
    source_map_path = project_path(repo_root, args.source_map)
    baseline_path = project_path(repo_root, args.baseline)
    default_output = PRESEAL_RECEIPT_DEFAULT if args.mode == "preseal" else POSTSEAL_RECEIPT_DEFAULT
    output_path = project_path(repo_root, args.output or default_output)
    issues: list[str] = []
    try:
        baseline_size, baseline_sha = digest(baseline_path)
        if baseline_sha != BASELINE_SHA256:
            issues.append(f"immutable v05 baseline SHA-256 mismatch: expected={BASELINE_SHA256}, actual={baseline_sha}")
        baseline = load_json(baseline_path)
        contract_size, contract_sha = digest(contract_path)
        contract = load_json(contract_path)
        issues.extend(validate_contract(repo_root, baseline, contract))
        predecessor_roots, predecessor_issues = verify_predecessor_roots(repo_root, contract)
        issues.extend(predecessor_issues)
        source_map_size, source_map_sha = digest(source_map_path)
        source_rows, source_tables = parse_source_map(source_map_path)
        checked_sources, source_issues = verify_source_rows(repo_root, source_rows)
        issues.extend(source_issues)
        issues.extend(verify_map_unique_path_bindings(source_tables))
        issues.extend(validate_design_input_bindings(repo_root, contract, source_tables))
        issues.extend(validate_final_bindings(
            repo_root, baseline, contract, source_rows, source_tables, source_map_path,
            source_map_size, source_map_sha, baseline_size,
        ))
        issues.extend(validate_resource_arithmetic(contract, repo_root))
        issues.extend(verify_receipt_bindings(source_tables))
    except Exception as exc:
        issues.append(f"audit input failure: {type(exc).__name__}: {exc}")
        baseline_size = contract_size = source_map_size = 0
        baseline_sha = contract_sha = source_map_sha = ""
        source_rows = checked_sources = source_tables = []
        predecessor_roots = {}
    checked_receipts, receipt_issues = check_fixed_receipts(repo_root)
    issues.extend(receipt_issues)
    track_e_receipt, track_e_receipt_issues = check_track_e_unit_receipt(repo_root, source_tables)
    issues.extend(track_e_receipt_issues)
    if track_e_receipt:
        checked_receipts.append(track_e_receipt)
    preseal_receipt_info: dict[str, Any] | None = None
    seal_info: dict[str, Any] | None = None
    if args.mode == "postseal":
        if not args.seal_manifest:
            issues.append("--seal-manifest is required for postseal mode")
        try:
            preseal_path = project_path(repo_root, args.preseal_receipt)
            preseal_receipt_info = {"path": args.preseal_receipt, "bytes": digest(preseal_path)[0], "sha256": digest(preseal_path)[1]}
            prior = load_json(preseal_path)
            if prior.get("status") != "E4_0_TRACK_E_PRESEAL_PASS_CONTRACT_AND_SOURCE_MAP_CLOSED" or prior.get("pass") is not True:
                issues.append("postseal mode requires a passing Track E preseal receipt")
            if prior.get("contract", {}).get("sha256") != contract_sha:
                issues.append("final contract bytes differ from the contract bound by the preseal receipt")
            if prior.get("source_map", {}).get("sha256") != source_map_sha:
                issues.append("source map bytes differ from the map bound by the preseal receipt")
        except Exception as exc:
            issues.append(f"cannot verify preseal receipt: {type(exc).__name__}: {exc}")
        if args.seal_manifest:
            try:
                seal_path = project_path(repo_root, args.seal_manifest)
                predecessor_expectations = {
                    name: PREDECESSOR_SEALS[name][1] for name in (
                        "e0_v10_root_sha256", "e1_v04_root_sha256", "e2_v07_root_sha256", "e3_v02_bundle_root_sha256"
                    )
                }
                seal_info, seal_issues = recompute_seal(
                    repo_root, seal_path, contract_path, source_map_path, source_rows, source_tables,
                    SEAL_SCHEMA_PATH, predecessor_expectations, PRESEAL_RECEIPT_DEFAULT, POSTSEAL_RECEIPT_DEFAULT,
                )
                issues.extend(seal_issues)
            except Exception as exc:
                issues.append(f"cannot recompute final contract seal: {type(exc).__name__}: {exc}")
    result = {
        "receipt_id": "FAS_E4_0_TRACK_E_INDEPENDENT_CONTRACT_SOURCE_MAP_AUDIT_V01",
        "status": (
            "E4_0_TRACK_E_PRESEAL_PASS_CONTRACT_AND_SOURCE_MAP_CLOSED" if args.mode == "preseal" and not issues else
            "E4_0_TRACK_E_POSTSEAL_PASS_ROOT_AND_MEMBERS_RECOMPUTED" if args.mode == "postseal" and not issues else
            f"E4_0_TRACK_E_{args.mode.upper()}_STOP_MISMATCHES_RECORDED"
        ),
        "mode": args.mode.upper(),
        "scope": "Independent contract/source-map integrity only; no population, label, tokenizer, model, CUDA, scoring, or runtime behavior access.",
        "contract": {"path": args.contract, "bytes": contract_size, "sha256": contract_sha},
        "immutable_draft_v05": {"path": args.baseline, "bytes": baseline_size, "sha256": baseline_sha, "expected_sha256": BASELINE_SHA256},
        "source_map": {"path": args.source_map, "bytes": source_map_size, "sha256": source_map_sha, "entry_count": len(source_rows)},
        "verified_source_files": checked_sources,
        "verified_upstream_receipts": checked_receipts,
        "verified_predecessor_seal_roots": predecessor_roots,
        "preseal_receipt": preseal_receipt_info,
        "final_seal": seal_info,
        "scientific_sections_compared": list(IMMUTABLE_SECTIONS),
        "issues": issues,
        "pass": not issues,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
    except FileExistsError:
        print(f"refusing to overwrite immutable receipt: {output_path}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "issue_count": len(issues), "receipt": str(output_path)}, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
