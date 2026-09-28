from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from common import canonical, jsonl_rows, read_json, sha256_bytes, sha256_file, verify_parent_bundle


MODEL_ID = "LiquidAI/LFM2.5-1.2B-Base"
REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
FEATURE_CONTRACT_SHA = "08ddd42795d71d9b598da5015d5541316c6cf1f2c0761ce3c0890229cda4d5b0"
VIEWS = (
    "V0_MEAN_FULL", "V1_FINAL_POSITION", "V2_FIRST_POSITION",
    "V3_CONTEXT_SPAN_MEAN", "V4_ENTITY_SPAN_MEAN", "V5_RELATION_SPAN_MEAN", "V6_FIXED_SPAN_CONCAT",
)
DIMS = {view: (6144 if view == "V6_FIXED_SPAN_CONCAT" else 2048) for view in VIEWS}


def view_paths(root: Path) -> dict[str, Path]:
    return {view: root / "feature-cache-v01" / f"{view}.f32le" for view in VIEWS}


def validate(root: Path) -> dict[str, Any]:
    binding = read_json(root / "inputs" / "input-binding-v01.json")
    extraction = read_json(root / "feature-extraction-receipt-v01.json")
    backbone = read_json(root / "backbone-identity-receipt-v01.json")
    repeat = read_json(root / "determinism-repeat-receipt-v01.json")
    asset_manifest = read_json(root / "model-asset-manifest-v01.json")
    preflight = read_json(root / "seals" / "preflight-seal-v01.json")
    if preflight.get("root_sha256") != extraction.get("preflight_root_sha256"):
        raise RuntimeError("extraction receipt names a different preflight packet")
    parents = verify_parent_bundle(binding)
    if parent := extraction.get("parent_roots"):
        expected = {key: value["result_tree_root_sha256"] for key, value in binding["parent_roots"].items()}
        if parent != expected:
            raise RuntimeError("extraction receipt parent roots differ")
    else:
        raise RuntimeError("extraction receipt does not bind its parents")
    if extraction.get("model_id") != MODEL_ID or extraction.get("model_revision") != REVISION:
        raise RuntimeError("feature cache names an unexpected LFM identity")
    if extraction.get("events_extracted") != 106496 or extraction.get("quartets") != 26624:
        raise RuntimeError("feature cache does not cover all sealed events and quartets")
    if extraction.get("tokenizer_invoked") is not False or extraction.get("single_row_exact_length_no_padding") is not True:
        raise RuntimeError("feature extraction crossed the frozen input boundary")
    if extraction.get("backbone_parameter_delta") != 0 or extraction.get("model_parameters_frozen") is not True:
        raise RuntimeError("frozen backbone identity gate failed")
    if backbone.get("identical") is not True or backbone.get("parameter_delta") != 0 or backbone.get("before", {}).get("sha256") != backbone.get("after", {}).get("sha256"):
        raise RuntimeError("backbone parameter identity receipt failed")
    if repeat.get("pass") is not True or repeat.get("sample_size") != 256 or len(repeat.get("rows", [])) != 256:
        raise RuntimeError("deterministic repeat receipt failed")
    if not all(all(row.get("feature_bytes_match", {}).get(view) is True for view in VIEWS) for row in repeat["rows"]):
        raise RuntimeError("a repeated view feature differs")
    if asset_manifest.get("resolved_revision") != REVISION or asset_manifest.get("model_id") != MODEL_ID:
        raise RuntimeError("model asset manifest identity differs")
    asset_entries = asset_manifest["assets"]
    if sha256_bytes(canonical(asset_entries)) != asset_manifest.get("asset_manifest_root_sha256"):
        raise RuntimeError("model asset manifest root does not reproduce")
    for item in asset_entries:
        digest, size = sha256_file(root.joinpath(*item["path"].split("/")))
        if digest != item["sha256"] or size != item["bytes"]:
            raise RuntimeError(f"pinned model asset changed: {item['path']}")

    corpus_path = Path(binding["inputs"]["corpus"])
    alignment_path = Path(binding["inputs"]["alignment_records"])
    assignment_path = Path(binding["inputs"]["alignment_assignments"])
    manifest_path = root / "feature-cache-v01" / "feature-rows-v01.jsonl"
    files = view_paths(root)
    streams = {view: path.open("rb") for view, path in files.items()}
    view_digests = {view: hashlib.sha256() for view in VIEWS}
    rows_seen = 0
    quartet_count = 0
    finite_values = 0
    align_iter = iter(jsonl_rows(alignment_path))
    assignment_iter = iter(jsonl_rows(assignment_path))
    manifest_iter = iter(jsonl_rows(manifest_path))

    for quartet in jsonl_rows(corpus_path):
        quartet_count += 1
        variants = quartet.get("variants", [])
        if len(variants) != 4 or [item.get("variant_id") for item in variants] != ["A", "C", "E", "P"]:
            raise RuntimeError(f"sealed corpus quartet order differs: {quartet.get('quartet_id')}")
        for variant in variants:
            alignment = next(align_iter, None)
            assignment = next(assignment_iter, None)
            record = next(manifest_iter, None)
            if alignment is None or assignment is None or record is None:
                raise RuntimeError("feature or parent identity rows ended before the corpus")
            event_id = variant["event_id"]
            for candidate in (alignment, assignment, record):
                if candidate.get("quartet_id") != quartet["quartet_id"] or candidate.get("event_id") != event_id or candidate.get("variant_id") != variant["variant_id"]:
                    raise RuntimeError(f"event ordering or identity mismatch: {event_id}")
            if record.get("row_index") != rows_seen or record.get("input_sha256") != variant.get("input_sha256") or record.get("input_text") != variant.get("input_text"):
                raise RuntimeError(f"feature row input identity mismatch: {event_id}")
            if record.get("token_ids") != alignment.get("token_ids") or record.get("token_ids_sha256") != alignment.get("token_ids_sha256"):
                raise RuntimeError(f"feature row token identity mismatch: {event_id}")
            if record.get("offset_mapping") != alignment.get("offset_mapping") or record.get("special_tokens_mask") != alignment.get("special_tokens_mask"):
                raise RuntimeError(f"feature row tokenizer mapping mismatch: {event_id}")
            if record.get("sequence_length") != alignment.get("sequence_length") or record.get("sequence_length") != assignment.get("sequence_length"):
                raise RuntimeError(f"feature row sequence length mismatch: {event_id}")
            if record.get("view_assignments") != assignment.get("view_assignments") or record.get("span_positions_by_type") != assignment.get("span_positions_by_type"):
                raise RuntimeError(f"feature row changed S01-2C positions: {event_id}")
            if assignment.get("quartet_eligible") is not True:
                raise RuntimeError(f"feature row came from an ineligible S01-2C event: {event_id}")
            if record.get("model_id") != MODEL_ID or record.get("model_revision") != REVISION or record.get("feature_contract_sha256") != FEATURE_CONTRACT_SHA:
                raise RuntimeError(f"feature row model/contract identity mismatch: {event_id}")
            if record.get("offset_mapping_sha256") != sha256_bytes(json.dumps(alignment["offset_mapping"], ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")):
                raise RuntimeError(f"feature row offset hash mismatch: {event_id}")
            for view in VIEWS:
                expected_dim = DIMS[view]
                if record.get("view_shapes", {}).get(view) != [expected_dim]:
                    raise RuntimeError(f"feature row shape mismatch: {event_id} / {view}")
                payload = streams[view].read(expected_dim * 4)
                if len(payload) != expected_dim * 4:
                    raise RuntimeError(f"feature cache ended early: {event_id} / {view}")
                if hashlib.sha256(payload).hexdigest() != record.get("feature_sha256", {}).get(view):
                    raise RuntimeError(f"row feature hash mismatch: {event_id} / {view}")
                vector = np.frombuffer(payload, dtype="<f4")
                if not np.isfinite(vector).all():
                    raise RuntimeError(f"non-finite feature value: {event_id} / {view}")
                finite_values += expected_dim
                view_digests[view].update(payload)
            rows_seen += 1
        if quartet_count % 2048 == 0:
            print(f"feature_rows_verified={rows_seen}/106496", flush=True)

    if rows_seen != 106496 or quartet_count != 26624:
        raise RuntimeError(f"feature corpus coverage mismatch: rows={rows_seen} quartets={quartet_count}")
    if next(align_iter, None) is not None or next(assignment_iter, None) is not None or next(manifest_iter, None) is not None:
        raise RuntimeError("feature or parent identity inputs contain trailing records")
    for stream in streams.values():
        if stream.read(1):
            raise RuntimeError("feature tensor has trailing bytes")
        stream.close()

    file_report = {}
    for view, path in files.items():
        digest = view_digests[view].hexdigest()
        size = rows_seen * DIMS[view] * 4
        expected = extraction["view_files"][view]
        if digest != expected["sha256"] or size != expected["bytes"]:
            raise RuntimeError(f"whole feature tensor checksum mismatch: {view}")
        if size != 106496 * DIMS[view] * 4:
            raise RuntimeError(f"feature tensor byte count differs from shape: {view}")
        file_report[view] = {"path": path.relative_to(root).as_posix(), "shape": [106496, DIMS[view]], "dtype": "<f4", "bytes": size, "sha256": digest}
    row_digest, row_bytes = sha256_file(manifest_path)
    if row_digest != extraction["feature_row_manifest"]["sha256"] or row_bytes != extraction["feature_row_manifest"]["bytes"]:
        raise RuntimeError("feature-row manifest checksum mismatch")

    return {
        "report_id": "FASS01_S01_2_FEATURE_CACHE_VALIDATION_V01",
        "status": "FEATURE_CACHE_VALID",
        "events_verified": rows_seen,
        "quartets_verified": quartet_count,
        "views": file_report,
        "feature_row_manifest": {"path": manifest_path.relative_to(root).as_posix(), "bytes": row_bytes, "sha256": row_digest},
        "finite_float32_values_verified": finite_values,
        "row_feature_hashes_verified": rows_seen * len(VIEWS),
        "deterministic_repeat_pass": repeat["pass"],
        "backbone_parameter_delta": 0,
        "parent_roots_reverified": {key: value["root_sha256"] for key, value in parents.items()},
        "model_loaded": False,
        "probe_training_performed": False,
        "geometry_analysis_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and seal the seven-view S01-2 feature cache")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = args.run_root.resolve()
    seal_path = root / "seals" / "feature-cache-seal-v01.json"
    report = validate(root)
    report_path = root / "feature-cache-validation-report-v01.json"
    if not args.verify_only:
        if seal_path.exists() or report_path.exists():
            raise SystemExit("feature cache is already sealed or has a validation report")
        report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    elif not seal_path.is_file() or not report_path.is_file():
        raise SystemExit("feature-cache report or seal is missing")

    report_hash, report_size = sha256_file(report_path) if report_path.exists() else ("", 0)
    if args.verify_only:
        existing_report = read_json(report_path)
        if existing_report != report:
            raise SystemExit("feature-cache validation report does not reproduce")
    items = []
    fixed_files = [
        root / "model-asset-manifest-v01.json",
        root / "parent-verification-receipt-v01.json",
        root / "backbone-identity-receipt-v01.json",
        root / "determinism-repeat-receipt-v01.json",
        root / "feature-extraction-receipt-v01.json",
        root / "feature-cache-v01" / "feature-rows-v01.jsonl",
        *[root / "feature-cache-v01" / f"{view}.f32le" for view in VIEWS],
        report_path,
    ]
    for path in sorted(fixed_files, key=lambda item: item.relative_to(root).as_posix()):
        if not path.is_file():
            raise SystemExit(f"missing feature-cache seal input: {path}")
        digest, size = sha256_file(path)
        items.append({"path": path.relative_to(root).as_posix(), "bytes": size, "sha256": digest})
    root_hash = sha256_bytes(canonical(items))
    if args.verify_only:
        seal = read_json(seal_path)
        if seal.get("root_sha256") != root_hash or seal.get("entries") != items:
            raise SystemExit("feature-cache seal does not reproduce")
        print(f"verified_feature_cache_root_sha256={root_hash}")
        return 0
    seal = {
        "seal_id": "FASS01_S01_2_FEATURE_CACHE_SEAL_V01",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "S01-2-feature-geometry-v01",
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>",
        "entries": items,
        "root_sha256": root_hash,
        "validation_report_sha256": report_hash,
        "validation_report_bytes": report_size,
        "model_id": MODEL_ID,
        "model_revision": REVISION,
        "backbone_parameter_delta": 0,
        "features_created": True,
        "geometry_analysis_performed": False,
        "probe_training_performed": False,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    with seal_path.open("xb") as target:
        target.write(json.dumps(seal, ensure_ascii=True, indent=2).encode("utf-8") + b"\n")
        target.flush()
    print(f"sealed_feature_cache_root_sha256={root_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
