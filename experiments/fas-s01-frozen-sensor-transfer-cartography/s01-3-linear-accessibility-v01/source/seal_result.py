from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import RESULT_ROOT, file_entry, read_json, sha256_file, tree_root, verify_entries, write_json

SEAL_REL = Path("seals") / "result-tree-seal-v01.json"
DISPOSITION_REL = Path("seals") / "phase-disposition-v01.json"
EXCLUDED = {SEAL_REL.as_posix(), DISPOSITION_REL.as_posix()}


def _entries() -> list[dict[str, Any]]:
    result = []
    for path in RESULT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(RESULT_ROOT).as_posix()
        if relative not in EXCLUDED:
            result.append(file_entry(path, RESULT_ROOT))
    result.sort(key=lambda item: item["path"])
    return result


def _validate_complete() -> dict[str, Any]:
    receipt_path = RESULT_ROOT / "run-execution-receipt-v01.json"
    metrics_path = RESULT_ROOT / "metrics-v01.json"
    if not receipt_path.is_file() or not metrics_path.is_file():
        raise RuntimeError("S01-3 execution receipt or full metrics report is missing")
    receipt = read_json(receipt_path)
    metrics = read_json(metrics_path)
    if receipt.get("complete") is not True or receipt.get("model_count") != 35 or len(receipt.get("models", [])) != 35:
        raise RuntimeError("S01-3 execution receipt does not report all 35 frozen probes")
    if metrics.get("disposition") != "COMPLETE_EXPLORATORY_LINEAR_CARTOGRAPHY" or len(metrics.get("metrics", [])) != 35:
        raise RuntimeError("S01-3 metrics report is incomplete")
    if metrics.get("selection_or_promotion") is not False:
        raise RuntimeError("S01-3 metrics report includes a forbidden selection")
    if receipt.get("operations", {}).get("LFM_loaded") is not False or receipt.get("operations", {}).get("feature_extraction") is not False:
        raise RuntimeError("S01-3 execution crossed the frozen sensor boundary")
    if receipt.get("operations", {}).get("online_or_adaptive_mechanisms") is not False:
        raise RuntimeError("S01-3 execution included an unauthorized adaptive mechanism")
    for model in receipt["models"]:
        for path_key, sha_key in (("state_path", "state_sha256"), ("predictions_path", "predictions_sha256")):
            path = RESULT_ROOT.joinpath(*model[path_key].split("/"))
            digest, size = sha256_file(path)
            expected_size_key = "state_bytes" if path_key == "state_path" else "predictions_bytes"
            if digest != model[sha_key] or size != model[expected_size_key]:
                raise RuntimeError(f"probe artifact does not match execution receipt: {model[path_key]}")
    if sha256_file(metrics_path)[0] != receipt.get("metrics_sha256"):
        raise RuntimeError("S01-3 metrics hash differs from execution receipt")
    return receipt


def seal() -> dict[str, Any]:
    seal_path = RESULT_ROOT / SEAL_REL
    disposition_path = RESULT_ROOT / DISPOSITION_REL
    if seal_path.exists() or disposition_path.exists():
        raise RuntimeError("S01-3 result seal already exists; refusing to replace it")
    receipt = _validate_complete()
    entries = _entries()
    root = tree_root(entries)
    result_seal = {
        "seal_id": "FASS01_S01_3_LINEAR_ACCESSIBILITY_RESULT_SEAL_V01",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "s01-3-linear-accessibility-v01",
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>; result seal and disposition excluded",
        "entries": entries,
        "root_sha256": root,
        "preflight_root_sha256": receipt["preflight_root_sha256"],
        "feature_cache_root_sha256": receipt["feature_cache_root_sha256"],
        "probe_count": receipt["model_count"],
    }
    disposition = {
        "disposition_id": "FASS01_S01_3_TERMINAL_DISPOSITION_V01",
        "result_root_sha256": root,
        "disposition": "COMPLETE_EXPLORATORY_LINEAR_ACCESSIBILITY_CARTOGRAPHY",
        "S01_3_COMPLETE": True,
        "S01_3_LINEAR_ACCESSIBILITY_DIAGNOSTIC": "COMPLETE",
        "S01_3_LFM_LOADED": False,
        "S01_3_FEATURE_REEXTRACTION": False,
        "S01_ADAPTIVE_MECHANISMS_AUTHORIZED": False,
        "FAS00_PHASE4_AUTHORIZED": False,
    }
    write_json(seal_path, result_seal)
    write_json(disposition_path, disposition)
    return {"status": disposition["disposition"], "result_root_sha256": root, "files": len(entries)}


def verify() -> dict[str, Any]:
    seal_path = RESULT_ROOT / SEAL_REL
    disposition_path = RESULT_ROOT / DISPOSITION_REL
    seal_doc = read_json(seal_path)
    disposition = read_json(disposition_path)
    actual = verify_entries(RESULT_ROOT, seal_doc["entries"])
    root = tree_root(actual)
    if root != seal_doc["root_sha256"] or root != disposition["result_root_sha256"]:
        raise RuntimeError("S01-3 result tree root mismatch")
    if len(actual) != len(seal_doc["entries"]):
        raise RuntimeError("S01-3 result tree file count mismatch")
    receipt = _validate_complete()
    if seal_doc.get("probe_count") != receipt.get("model_count"):
        raise RuntimeError("S01-3 result seal names a different probe count")
    if disposition.get("S01_3_COMPLETE") is not True or disposition.get("S01_ADAPTIVE_MECHANISMS_AUTHORIZED") is not False:
        raise RuntimeError("S01-3 terminal disposition flags are invalid")
    return {"status": "S01_3_RESULT_VERIFIED", "result_root_sha256": root, "files": len(actual)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    print(seal() if not args.verify else verify())
