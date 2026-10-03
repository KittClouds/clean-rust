from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def canonical(entries: list[dict[str, Any]]) -> bytes:
    return b"".join(
        f"{item['path']}\t{item['bytes']}\t{item['sha256']}\n".encode("utf-8")
        for item in entries
    )


def tree_entries(root: Path, excluded: Path) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise RuntimeError(f"symlink in S01-2C result tree: {path}")
        if path.is_file() and path != excluded:
            digest, size = hash_file(path)
            entries.append({"path": path.relative_to(root).as_posix(), "bytes": size, "sha256": digest})
    return entries


def verify_parent_tree(item: dict[str, Any]) -> dict[str, Any]:
    root = Path(item["path"])
    seal_path = root.joinpath(*item["seal_path"].split("/"))
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("root_sha256") != item["result_tree_root_sha256"]:
        raise RuntimeError(f"parent root identifier changed: {root}")
    actual = tree_entries(root, seal_path)
    if actual != seal.get("entries") or hashlib.sha256(canonical(actual)).hexdigest() != item["result_tree_root_sha256"]:
        raise RuntimeError(f"parent tree changed since input authorization: {root}")
    return seal


def verify_preflight(root: Path) -> dict[str, Any]:
    seal_path = root / "seals" / "preflight-seal-v01.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    actual = []
    for item in seal["entries"]:
        digest, size = hash_file(root.joinpath(*item["path"].split("/")))
        actual.append({"path": item["path"], "bytes": size, "sha256": digest})
    if actual != seal["entries"] or hashlib.sha256(canonical(actual)).hexdigest() != seal["root_sha256"]:
        raise RuntimeError("S01-2C preflight packet changed")
    return seal


def validate_assignments(path: Path, expected_rows: int) -> tuple[str, int]:
    rows = 0
    seen_events: set[str] = set()
    required_views = {
        "V0_MEAN_FULL", "V1_FINAL_POSITION", "V2_FIRST_POSITION",
        "V3_CONTEXT_SPAN_MEAN", "V4_ENTITY_SPAN_MEAN", "V5_RELATION_SPAN_MEAN", "V6_FIXED_SPAN_CONCAT",
    }
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            row = json.loads(line)
            rows += 1
            event_id = row.get("event_id")
            if not event_id or event_id in seen_events:
                raise RuntimeError(f"duplicate or missing event identity at assignment row {line_number}")
            seen_events.add(event_id)
            if row.get("quartet_eligible") is not True:
                raise RuntimeError(f"ineligible event in a passing assignment manifest: {event_id}")
            seq_len = row.get("sequence_length")
            if not isinstance(seq_len, int) or seq_len <= 0:
                raise RuntimeError(f"invalid sequence length in assignment row {line_number}")
            views = row.get("view_assignments", {})
            if set(views) != required_views:
                raise RuntimeError(f"view set differs at assignment row {line_number}")
            if views["V0_MEAN_FULL"].get("position_range_half_open") != [0, seq_len] or views["V0_MEAN_FULL"].get("position_count") != seq_len:
                raise RuntimeError(f"V0 assignment differs at row {line_number}")
            if views["V1_FINAL_POSITION"].get("positions") != [seq_len - 1] or views["V2_FIRST_POSITION"].get("positions") != [0]:
                raise RuntimeError(f"first/final position assignment differs at row {line_number}")
            span_positions = row.get("span_positions_by_type", {})
            for span_type, view_id in (("context", "V3_CONTEXT_SPAN_MEAN"), ("entity", "V4_ENTITY_SPAN_MEAN"), ("relation", "V5_RELATION_SPAN_MEAN")):
                positions = span_positions.get(span_type)
                if not isinstance(positions, list) or positions != sorted(set(positions)) or not positions:
                    raise RuntimeError(f"invalid deduplicated span positions at row {line_number}: {span_type}")
                if views[view_id].get("positions") != positions or views[view_id].get("position_count") != len(positions):
                    raise RuntimeError(f"span view differs from span positions at row {line_number}: {span_type}")
                records = row.get("span_records", {}).get(span_type, [])
                if len(records) != 2 or any(record.get("status") != "PASS" for record in records):
                    raise RuntimeError(f"span occurrence gate failed at row {line_number}: {span_type}")
                union = sorted({position for record in records for position in record["token_positions"]})
                if union != positions:
                    raise RuntimeError(f"span occurrence union differs at row {line_number}: {span_type}")
            segments = views["V6_FIXED_SPAN_CONCAT"].get("ordered_segments")
            expected_segments = [
                {"source_view": "V3_CONTEXT_SPAN_MEAN", "positions": span_positions["context"]},
                {"source_view": "V4_ENTITY_SPAN_MEAN", "positions": span_positions["entity"]},
                {"source_view": "V5_RELATION_SPAN_MEAN", "positions": span_positions["relation"]},
            ]
            if segments != expected_segments:
                raise RuntimeError(f"V6 segment order differs at row {line_number}")
    if rows != expected_rows:
        raise RuntimeError(f"assignment rows differ: {rows} != {expected_rows}")
    return hash_file(path)


def validate(root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    binding = json.loads((root / "inputs" / "alignment-input-binding-v01.json").read_text(encoding="utf-8"))
    contract = json.loads((root / "inputs" / "minimal-cover-alignment-contract-v01.json").read_text(encoding="utf-8"))
    report = json.loads((root / "minimal-cover-alignment-report-v01.json").read_text(encoding="utf-8"))
    disposition = json.loads((root / "phase-disposition-v01.json").read_text(encoding="utf-8"))
    preflight = verify_preflight(root)
    contract_sha, _ = hash_file(root / "inputs" / "minimal-cover-alignment-contract-v01.json")
    if contract_sha != binding.get("S01_2C_contract_sha256") or contract["contract_id"] != "FASS01_S01_2C_MINIMAL_COVER_ALIGNMENT_V01":
        raise RuntimeError("S01-2C contract identity or hash changed")
    if report.get("status") != "MINIMAL_COVER_ALIGNMENT_PASS" or report.get("complete") is not True:
        raise RuntimeError("S01-2C report is not a complete passing result")
    if report.get("preflight_root_sha256") != preflight.get("root_sha256"):
        raise RuntimeError("S01-2C report names a different preflight seal")
    if report.get("parent_roots") != {name: item["result_tree_root_sha256"] for name, item in binding["parent_roots"].items()}:
        raise RuntimeError("S01-2C report parent roots differ from the authorization binding")
    if report.get("events_reconciled") != 106496 or report.get("quartets_reconciled") != 26624 or report.get("span_occurrences_reconciled") != 638976:
        raise RuntimeError("S01-2C report does not cover the full sealed corpus")
    if report.get("span_passes") != 638976 or report.get("span_failures") != 0 or report.get("validation_error_counts"):
        raise RuntimeError("S01-2C report contains a span or validation failure")
    if report.get("source_S01_2A_status_preserved") != "TOKENIZER_ALIGNMENT_FAIL_CLOSED" or report.get("source_S01_2A_repeat_check_pass") is not True:
        raise RuntimeError("S01-2A historical state or repeat-check provenance changed")
    if report.get("support_audit", {}).get("pass") is not True or report.get("boundary_audit_reconciliation", {}).get("pass") is not True:
        raise RuntimeError("S01-2C support or audit reconciliation failed")
    expected_disposition = {
        "S01_2A_TOKEN_ALIGNMENT": "TOKENIZER_ALIGNMENT_FAIL_CLOSED",
        "S01_2B_BOUNDARY_AUDIT_COMPLETE": True,
        "S01_2C_MINIMAL_COVER_ALIGNMENT": "PASS",
        "S01_2_FEATURE_EXTRACTION_ELIGIBLE": True,
        "S01_2_MODEL_CONTACT_AUTHORIZED": False,
        "S01_3_AUTHORIZED": False,
        "tokenizer_loaded_during_S01_2C": False,
        "LFM_loaded_or_instantiated": False,
        "features_created": False,
    }
    if any(disposition.get(key) != value for key, value in expected_disposition.items()):
        raise RuntimeError("S01-2C disposition exceeds its authorized boundary or differs from expected gates")

    for rel, expected in binding["copied_contract_hashes"].items():
        digest, _ = hash_file(root.joinpath(*rel.split("/")))
        if digest != expected:
            raise RuntimeError(f"copied contract changed: {rel}")
    # Recheck all parent result trees at sealing time, after the corpus pass.
    parent_seals = [verify_parent_tree(item) for item in binding["parent_roots"].values()]
    assignment = report["alignment_assignments"]
    assignments_path = root / assignment["path"]
    digest, size = validate_assignments(assignments_path, 106496)
    if digest != assignment.get("sha256") or size != assignment.get("bytes"):
        raise RuntimeError("assignment manifest hash or size differs from report")
    return report, disposition, parent_seals


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal or verify the S01-2C alignment result tree")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = args.run_root.resolve()
    seal_path = root / "seals" / "result-tree-seal-v01.json"
    report, disposition, parent_seals = validate(root)
    entries = tree_entries(root, seal_path)
    root_hash = hashlib.sha256(canonical(entries)).hexdigest()
    if args.verify_only:
        if not seal_path.is_file():
            raise SystemExit("S01-2C result-tree seal is missing")
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        if seal.get("root_sha256") != root_hash or seal.get("entries") != entries:
            raise SystemExit("S01-2C result-tree seal does not reproduce")
        print(f"verified_result_root_sha256={root_hash}")
        print(f"S01_2C_MINIMAL_COVER_ALIGNMENT={disposition['S01_2C_MINIMAL_COVER_ALIGNMENT']}")
        return 0
    if seal_path.exists():
        raise SystemExit("result-tree seal already exists; refusing to overwrite")
    binding = json.loads((root / "inputs" / "alignment-input-binding-v01.json").read_text(encoding="utf-8"))
    seal = {
        "seal_id": "FASS01_S01_2C_RESULT_TREE_SEAL_V01",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "S01-2C-v01",
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>; this seal excluded",
        "entries": entries,
        "root_sha256": root_hash,
        "S01_2C_contract_sha256": binding["S01_2C_contract_sha256"],
        "preflight_root_sha256": report["preflight_root_sha256"],
        "parents": {name: item["result_tree_root_sha256"] for name, item in binding["parent_roots"].items()},
        "parent_trees_reverified_at_seal": len(parent_seals) == 3,
        "tokenizer_loaded": False,
        "model_loaded": False,
        "feature_extraction_performed": False,
        "probe_training_performed": False,
        "geometry_analysis_performed": False,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    with seal_path.open("xb") as output:
        output.write(json.dumps(seal, ensure_ascii=True, indent=2).encode("utf-8") + b"\n")
        output.flush()
    print(f"sealed_result_root_sha256={root_hash}")
    print(f"S01_2C_MINIMAL_COVER_ALIGNMENT={disposition['S01_2C_MINIMAL_COVER_ALIGNMENT']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
