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
    return b"".join(f"{item['path']}\t{item['bytes']}\t{item['sha256']}\n".encode("utf-8") for item in entries)


def compute_entries(root: Path, seal_path: Path) -> list[dict[str, Any]]:
    paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != seal_path
    )
    entries = []
    for relative in paths:
        digest, size = hash_file(root.joinpath(*relative.split("/")))
        entries.append({"path": relative, "bytes": size, "sha256": digest})
    return entries


def validate(root: Path) -> dict[str, Any]:
    report = json.loads((root / "boundary-audit-report-v02.json").read_text(encoding="utf-8"))
    disposition = json.loads((root / "phase-disposition-v02.json").read_text(encoding="utf-8"))
    if report["phase_id"] != "S01-2B-v02" or report["status"] != "BOUNDARY_AUDIT_COMPLETE" or report["complete"] is not True:
        raise RuntimeError("boundary audit is incomplete")
    if report["corpus_sha256"] != "51a55212ba89d55bd6df532673ad4546c95def1f5d75622661f7c17b3e4a7ad1":
        raise RuntimeError("audit report names an unexpected corpus")
    if report["S01_2A_result_tree_root_sha256"] != "aad22fe9487928a016d70c3c91bee8095c2fe8db1a8f4b19df30d9fae4f0a2a0":
        raise RuntimeError("audit report names an unexpected S01-2A parent")
    if report["S01_2A_original_status"] != "TOKENIZER_ALIGNMENT_FAIL_CLOSED" or not report["S01_2A_original_disposition_preserved"]:
        raise RuntimeError("audit does not preserve the failed S01-2A status")
    if report["tokenizer_loaded_during_S01_2B"] or report["LFM_loaded_or_instantiated"] or report["feature_extraction_performed"] or report["probe_training_performed"] or report["geometry_analysis_performed"]:
        raise RuntimeError("audit report exceeds the read-only authorization")
    if report["events_reconciled"] != 106496 or report["quartets_reconciled"] != 26624 or report["span_occurrences_reconciled"] != 638976:
        raise RuntimeError("audit report did not reconcile the complete input corpus")
    audit_path = root / "boundary-span-audit-v02.jsonl"
    digest, size = hash_file(audit_path)
    if digest != report["audit_jsonl_sha256"] or size != report["audit_jsonl_bytes"]:
        raise RuntimeError("span audit JSONL hash differs from the report")
    if report["failure_reconciliation_mismatches"]:
        raise RuntimeError("source failure reasons did not reconcile")
    if disposition["phase_id"] != "S01-2B-v02" or disposition["S01_2A_TOKENIZER_ALIGNMENT_FAIL_CLOSED"] is not True or disposition["S01_2B_BOUNDARY_AUDIT_COMPLETE"] is not True:
        raise RuntimeError("audit disposition does not match the completed read-only audit")
    if disposition["S01_2_FEATURE_EXTRACTION_ELIGIBLE"] is not False or disposition["S01_2_MODEL_CONTACT_AUTHORIZED"] is not False or disposition["S01_3_AUTHORIZED"] is not False:
        raise RuntimeError("audit disposition exceeds the authorized boundary")
    if disposition["rule_adopted"] is not False or disposition["features_created"] is not False:
        raise RuntimeError("audit disposition claims an unauthorized operation")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal or verify the S01-2B audit result tree")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = args.run_root.resolve()
    seal_path = root / "seals" / "result-tree-seal-v02.json"
    report = validate(root)
    entries = compute_entries(root, seal_path)
    root_hash = hashlib.sha256(canonical(entries)).hexdigest()
    if args.verify_only:
        if not seal_path.is_file():
            raise SystemExit("result-tree seal is missing")
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        if seal["root_sha256"] != root_hash or seal["entries"] != entries:
            raise SystemExit("result-tree seal does not reproduce")
        print(f"verified_result_root_sha256={root_hash}")
        return 0
    if seal_path.exists():
        raise SystemExit("result-tree seal already exists; refusing to overwrite")
    seal = {
        "seal_id": "FASS01_S01_2B_RESULT_TREE_SEAL_V02",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "S01-2B-v02",
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>; this seal excluded",
        "entries": entries,
        "root_sha256": root_hash,
        "corpus_sha256": report["corpus_sha256"],
        "S01_2_result_tree_root_sha256": report["S01_2_result_tree_root_sha256"],
        "S01_2A_result_tree_root_sha256": report["S01_2A_result_tree_root_sha256"],
        "tokenizer_loaded": False,
        "model_loaded": False,
        "feature_extraction_performed": False,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    with seal_path.open("xb") as output:
        output.write(json.dumps(seal, ensure_ascii=True, indent=2).encode("utf-8") + b"\n")
        output.flush()
    print(f"sealed_result_root_sha256={root_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
