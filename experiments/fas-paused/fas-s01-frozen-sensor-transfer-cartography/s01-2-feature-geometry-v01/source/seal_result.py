from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common import canonical, read_json, sha256_bytes, sha256_file, tree_entries


def verify_preflight(root: Path) -> dict[str, Any]:
    seal = read_json(root / "seals" / "preflight-seal-v01.json")
    actual = []
    for item in seal["entries"]:
        digest, size = sha256_file(root.joinpath(*item["path"].split("/")))
        actual.append({"path": item["path"], "bytes": size, "sha256": digest})
    if actual != seal["entries"] or sha256_bytes(canonical(actual)) != seal["root_sha256"]:
        raise RuntimeError("preflight seal failed verification")
    return seal


def verify_feature_seal(root: Path) -> dict[str, Any]:
    seal = read_json(root / "seals" / "feature-cache-seal-v01.json")
    entries = seal.get("entries", [])
    if sha256_bytes(canonical(entries)) != seal.get("root_sha256"):
        raise RuntimeError("feature-cache seal root does not reproduce")
    for item in entries:
        digest, size = sha256_file(root.joinpath(*item["path"].split("/")))
        if digest != item["sha256"] or size != item["bytes"]:
            raise RuntimeError(f"feature-cache seal entry changed: {item['path']}")
    if seal.get("features_created") is not True or seal.get("geometry_analysis_performed") is not False:
        raise RuntimeError("feature-cache seal has an unexpected phase disposition")
    return seal


def validate(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    binding = read_json(root / "inputs" / "input-binding-v01.json")
    preflight = verify_preflight(root)
    feature_seal = verify_feature_seal(root)
    extraction = read_json(root / "feature-extraction-receipt-v01.json")
    repeat = read_json(root / "determinism-repeat-receipt-v01.json")
    backbone = read_json(root / "backbone-identity-receipt-v01.json")
    geometry_report = read_json(root / "geometry-v01" / "geometry-report-v01.json")
    geometry_receipt = read_json(root / "geometry-v01" / "geometry-execution-receipt-v01.json")
    if extraction.get("events_extracted") != 106496 or extraction.get("model_revision") != binding.get("model_revision"):
        raise RuntimeError("feature extraction receipt is incomplete or mismatched")
    if repeat.get("pass") is not True or repeat.get("sample_size") != 256:
        raise RuntimeError("determinism repeat check failed")
    if backbone.get("identical") is not True or backbone.get("parameter_delta") != 0:
        raise RuntimeError("backbone immutability receipt failed")
    if geometry_report.get("status") != "FROZEN_DESCRIPTIVE_GEOMETRY_COMPLETE" or geometry_report.get("scientific_status") != "descriptive_cartography_only":
        raise RuntimeError("frozen geometry report is incomplete")
    if geometry_report.get("input_roots", {}).get("feature_cache_root_sha256") != feature_seal.get("root_sha256"):
        raise RuntimeError("geometry report names a different sealed feature cache")
    if geometry_receipt.get("complete") is not True or geometry_receipt.get("feature_cache_root_sha256") != feature_seal.get("root_sha256"):
        raise RuntimeError("geometry execution receipt failed")
    if geometry_report.get("population", {}).get("events") != 106496 or geometry_report.get("population", {}).get("quartets") != 26624:
        raise RuntimeError("geometry population differs from the sealed S01-2 population")
    if geometry_report.get("support_validation", {}).get("pass") is not True:
        raise RuntimeError("geometry support validation failed")
    for name in ("subgroup_distributions", "cell_consistency", "template_invariance"):
        artifact = geometry_report.get("metric_files", {}).get(name)
        if not artifact:
            raise RuntimeError(f"geometry metric artifact missing: {name}")
        digest, size = sha256_file(root.joinpath(*artifact["path"].split("/")))
        if digest != artifact["sha256"] or size != artifact["bytes"]:
            raise RuntimeError(f"geometry metric artifact changed: {name}")
    forbidden = geometry_report.get("analysis_limits", {})
    expected_false = ("probe_fitting", "nonlinear_diagnostics", "view_selection_or_ranking", "rescue_criterion", "pooling_or_layer_search", "backbone_loaded_for_geometry", "online_adaptation", "S01_3_authorized")
    if any(forbidden.get(key) is not False for key in expected_false):
        raise RuntimeError("geometry report claims an unauthorized analysis")
    if extraction.get("model_id") != binding["model_id"] or extraction.get("model_revision") != binding["model_revision"]:
        raise RuntimeError("extraction model identity differs from binding")
    if preflight.get("parents") != {key: value["result_tree_root_sha256"] for key, value in binding["parent_roots"].items()}:
        raise RuntimeError("preflight parent roots differ")
    return feature_seal, geometry_report, geometry_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal or verify the complete S01-2 feature and geometry result tree")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = args.run_root.resolve()
    seal_path = root / "seals" / "result-tree-seal-v01.json"
    feature_seal, report, receipt = validate(root)
    if args.verify_only:
        if not seal_path.is_file():
            raise SystemExit("result-tree seal is missing")
        entries = tree_entries(root, excluded=seal_path, allow_internal_symlinks=True)
        root_hash = sha256_bytes(canonical(entries))
        existing = read_json(seal_path)
        if existing.get("root_sha256") != root_hash or existing.get("entries") != entries:
            raise SystemExit("result-tree seal does not reproduce")
        print(f"verified_result_root_sha256={root_hash}")
        return 0
    if seal_path.exists():
        raise SystemExit("result-tree seal already exists; refusing to overwrite")
    disposition = {
        "disposition_id": "FASS01_S01_2_FEATURE_GEOMETRY_DISPOSITION_V01",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "S01-2-feature-geometry-v01",
        "S01_2_FEATURE_CACHE_READY": True,
        "S01_2_FEATURE_EXTRACTION_COMPLETE": True,
        "S01_2_GEOMETRY_COMPLETE": True,
        "S01_2_BACKBONE_PARAMETER_DELTA": 0,
        "S01_2_SENSOR_PROBE_AUTHORIZED": False,
        "S01_2_PROBE_TRAINING_PERFORMED": False,
        "S01_2_NONLINEAR_DIAGNOSTICS_PERFORMED": False,
        "S01_2_ADAPTIVE_MECHANISMS_PERFORMED": False,
        "S01_3_AUTHORIZED": False,
        "model_id": "LiquidAI/LFM2.5-1.2B-Base",
        "model_revision": "7453bca97ca1e67754c4035a4b4c584e1c9dd725",
        "feature_cache_root_sha256": feature_seal["root_sha256"],
        "geometry_report_sha256": sha256_file(root / "geometry-v01" / "geometry-report-v01.json")[0],
        "next_boundary": "stop after sealing S01-2 feature extraction and frozen geometry for review",
    }
    disp_path = root / "phase-disposition-v01.json"
    if disp_path.exists():
        raise SystemExit("final disposition already exists")
    disp_path.write_text(json.dumps(disposition, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    entries = tree_entries(root, excluded=seal_path, allow_internal_symlinks=True)
    root_hash = sha256_bytes(canonical(entries))
    binding = read_json(root / "inputs" / "input-binding-v01.json")
    seal = {
        "seal_id": "FASS01_S01_2_FEATURE_GEOMETRY_RESULT_SEAL_V01",
        "project_id": binding["project_id"],
        "phase_id": binding["phase_id"],
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>; this seal excluded",
        "entries": entries,
        "root_sha256": root_hash,
        "preflight_root_sha256": read_json(root / "seals" / "preflight-seal-v01.json")["root_sha256"],
        "feature_cache_root_sha256": feature_seal["root_sha256"],
        "geometry_report_sha256": disposition["geometry_report_sha256"],
        "parent_roots": {key: value["result_tree_root_sha256"] for key, value in binding["parent_roots"].items()},
        "backbone_parameter_delta": 0,
        "model_loaded_for_extraction": True,
        "model_loaded_for_geometry": False,
        "probe_training_performed": False,
        "nonlinear_diagnostics_performed": False,
        "S01_3_authorized": False,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    with seal_path.open("xb") as output:
        output.write(json.dumps(seal, ensure_ascii=True, indent=2).encode("utf-8") + b"\n")
        output.flush()
    print(f"sealed_result_root_sha256={root_hash}")
    print(f"feature_cache_root_sha256={feature_seal['root_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
