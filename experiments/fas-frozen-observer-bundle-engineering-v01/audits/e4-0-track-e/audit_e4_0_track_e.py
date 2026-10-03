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
from pathlib import Path
from typing import Any


BASELINE_SHA256 = "e2910965b53313a34c3a7d870075d83dbc9e035a230fc68f3c177c12c71e9fcf"
BASELINE_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-CONTRACT-DRAFT-v05.json"
CONTRACT_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v05-final.json"
SOURCE_MAP_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v04.md"
PRESEAL_RECEIPT_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-preseal-receipt-v01.json"
POSTSEAL_RECEIPT_DEFAULT = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-postseal-receipt-v01.json"

FIXED_RECEIPTS = {
    "audits/e4-0-track-a/track-a-receipt-v01.json": "6ff04e3eefae26d419560d30158fb863545f5d348478fdd59cc3013daba867d7",
    "audits/e4-0-track-b/track-b-source-tests-v01.json": "acba272c3eb177e8e15b178343a7fcc87ecc43e0bfb6bc665dda9ddf25e400a3",
    "audits/e4-0-track-c/track-c-source-tests-v01.json": "54f487ef7e2299cb5550b6fc65ce33440ab0f4be3caa923181b85c6bee098744",
    "audits/e4-0-source-integration-tests-v01.json": "5e4648bf91167dad4e0f0e22b791aec62b4d323382c52f60c4574ff6ae8211c4",
}

IMMUTABLE_SECTIONS = (
    "predecessors",
    "representation_abi",
    "population",
    "parity",
    "fresh_qualification",
    "truth_access",
    "resources",
    "phase_gates",
    "stop_rule",
    "E4_A_dependency",
)

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


def artifact_root(entries: list[dict[str, Any]]) -> str:
    digest_builder = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item["artifact_id"]).encode("utf-8")):
        digest_builder.update(
            f"{entry['artifact_id']}\t{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n".encode("utf-8")
        )
    return digest_builder.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def project_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"path escapes project root: {value}") from exc
        return path
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {value}") from exc
    return resolved


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
    """Read the uniquely designated source-file table from the v04 Markdown map."""
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
    return checked, issues


def false_authorization_flags(contract: dict[str, Any]) -> list[str]:
    found: list[str] = []
    def visit(value: Any, prefix: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                path = f"{prefix}.{key}" if prefix else key
                if ("authoriz" in key.lower() or key.endswith("_authorized")) and child is not False:
                    found.append(f"{path} must be false; got {child!r}")
                visit(child, path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{prefix}[{index}]")
    visit(contract)
    return found


def validate_contract(root: Path, baseline: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for section in IMMUTABLE_SECTIONS:
        if section not in baseline or section not in contract:
            issues.append(f"required scientific section absent: {section}")
        elif canonical(baseline[section]) != canonical(contract[section]):
            issues.append(f"scientific section differs from immutable v05 draft: {section}")
    if false_authorization_flags(contract):
        issues.extend(false_authorization_flags(contract))
    status = str(contract.get("status", "")).upper()
    if not status or "FROZEN" not in status and "SEALED" not in status:
        issues.append(f"final contract status is not sealed/frozen: {status!r}")
    sources = contract.get("implementation_sources", contract.get("implementation_source_bindings", {}))
    if isinstance(sources, dict):
        required = ("e4_population_generator", "e4_online_feature_and_parity_runner", "e4_fresh_scorer", "e4_independent_auditor")
        for name in required:
            if not sources.get(name):
                issues.append(f"implementation source is not bound: {name}")
    else:
        issues.append("final contract implementation source bindings are malformed")
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
    for rel, expected in FIXED_RECEIPTS.items():
        try:
            path = project_path(root, "experiments/fas-frozen-observer-bundle-engineering-v01/" + rel)
            size, actual = digest(path)
            if actual != expected:
                issues.append(f"receipt SHA-256 mismatch {rel}: expected={expected}, actual={actual}")
            checked.append({"path": rel, "bytes": str(size), "sha256": actual})
        except Exception as exc:
            issues.append(f"cannot verify receipt {rel}: {type(exc).__name__}: {exc}")
    return checked, issues


def recompute_seal(
    root: Path,
    seal_path: Path,
    contract_path: Path,
    source_map_path: Path,
    source_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    seal = load_json(seal_path)
    entries = seal.get("entries")
    if not isinstance(entries, list) or not entries:
        return {}, ["seal manifest has no nonempty entries list"]
    actual_entries: list[dict[str, Any]] = []
    by_path: dict[str, dict[str, Any]] = {}
    seen_artifact_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not all(key in entry for key in ("artifact_id", "path", "bytes", "sha256")):
            issues.append(f"malformed seal entry: {entry!r}")
            continue
        artifact_id = str(entry["artifact_id"])
        rel = str(entry["path"])
        normalized = Path(rel)
        if normalized.is_absolute() or ".." in normalized.parts or "\\" in rel:
            issues.append(f"unsafe/noncanonical seal member path: {rel}")
            continue
        if rel in by_path or artifact_id in seen_artifact_ids:
            issues.append(f"duplicate seal artifact_id or path: {artifact_id} {rel}")
            continue
        seen_artifact_ids.add(artifact_id)
        by_path[rel] = entry
        try:
            member = project_path(root, rel)
            size, sha = digest(member)
            if size != entry["bytes"]:
                issues.append(f"seal member byte-count mismatch {rel}: manifest={entry['bytes']}, actual={size}")
            if sha != entry["sha256"]:
                issues.append(f"seal member SHA-256 mismatch {rel}: manifest={entry['sha256']}, actual={sha}")
            actual_entries.append({"artifact_id": artifact_id, "path": rel, "bytes": size, "sha256": sha})
        except Exception as exc:
            issues.append(f"cannot read seal member {rel}: {type(exc).__name__}: {exc}")
    if len(entries) != seal.get("entry_count"):
        issues.append(f"seal entry_count mismatch: manifest={seal.get('entry_count')!r}, actual={len(entries)}")
    recomputed_root = artifact_root(actual_entries)
    if recomputed_root != seal.get("root_sha256"):
        issues.append(f"seal root mismatch: manifest={seal.get('root_sha256')!r}, recomputed={recomputed_root}")
    contract_rel = contract_path.relative_to(root).as_posix()
    map_rel = source_map_path.relative_to(root).as_posix()
    if contract_rel not in by_path:
        issues.append(f"contract is not bound in seal: {contract_rel}")
    if map_rel not in by_path:
        issues.append(f"source map is not bound in seal: {map_rel}")
    preseal_rel = PRESEAL_RECEIPT_DEFAULT
    if preseal_rel not in by_path:
        issues.append(f"passing preseal receipt is not bound in seal: {preseal_rel}")
    audit_source_rel = Path(__file__).resolve().relative_to(root).as_posix()
    if audit_source_rel not in by_path:
        issues.append(f"Track E auditor source is not bound in seal: {audit_source_rel}")
    audit_test_rel = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/test_audit_e4_0_track_e.py"
    if audit_test_rel not in by_path:
        issues.append(f"Track E auditor test source is not bound in seal: {audit_test_rel}")
    role_rows = [(row["path"], str(row.get("role", "")).lower()) for row in source_rows]
    builder_rows = [rel for rel, role in role_rows if "map" in role and ("build" in role or "generat" in role)]
    sealer_rows = [rel for rel, role in role_rows if "seal" in role and ("build" in role or "sealer" in role)]
    if not builder_rows:
        issues.append("source map does not designate a map-builder source role")
    if not sealer_rows:
        issues.append("source map does not designate a seal-builder source role")
    for rel in builder_rows + sealer_rows:
        if rel not in by_path:
            issues.append(f"map-builder/sealer source is not bound in seal: {rel}")
    for rel in by_path:
        if rel == POSTSEAL_RECEIPT_DEFAULT:
            issues.append(f"postseal receipt must remain outside contract seal: {rel}")
    summary = {
        "seal_path": str(seal_path),
        "seal_sha256": digest(seal_path)[1],
        "seal_root_sha256": seal.get("root_sha256"),
        "recomputed_root_sha256": recomputed_root,
        "entry_count": len(entries),
        "contract_member_path": contract_rel,
        "source_map_member_path": map_rel,
    }
    return summary, issues


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
        issues.extend(verify_receipt_bindings(source_tables))
    except Exception as exc:
        issues.append(f"audit input failure: {type(exc).__name__}: {exc}")
        baseline_size = contract_size = source_map_size = 0
        baseline_sha = contract_sha = source_map_sha = ""
        source_rows = checked_sources = source_tables = []
        predecessor_roots = {}
    checked_receipts, receipt_issues = check_fixed_receipts(repo_root)
    issues.extend(receipt_issues)
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
                seal_info, seal_issues = recompute_seal(repo_root, seal_path, contract_path, source_map_path, source_rows)
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
