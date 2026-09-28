"""Post-analysis structural/hash audit for F4-PRECISION-01.

This verifier intentionally emits no comparative performance values. The
receipt records the known sequence deviation: outcome JSON was opened before
this independent integrity pass.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path

import numpy as np


STUDY = Path(__file__).resolve().parents[1]
DATA = STUDY / "runs/qualification-v2/f4-precision-01-attempt-02"
ANALYSIS = STUDY / "runs/qualification-v2/f4-precision-01-analysis-v0.1.8"
CONTRACT = STUDY / "F4-PRECISION-01-CONTRACT-v0.1.8.json"
PARENT = STUDY / "F4-CAPACITY-01-TERMINAL-RECEIPT.json"
BLOCKS = [303000, 303001, 303002, 303003]
WIDTH = 80
MAGIC = {"a": b"FLYREACH3F4\0", "b": b"FLYREACH3P64\0", "c": b"FLYREACH3C64\0"}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_stream(path: Path, arm: str):
    raw = path.read_bytes()
    magic = MAGIC[arm]
    if raw[: len(magic)] != magic:
        raise RuntimeError(f"bad magic: {path}")
    pos = len(magic)
    version, width = struct.unpack_from("<IH", raw, pos)
    pos += 6
    if version != 1 or width != WIDTH:
        raise RuntimeError(f"bad stream version/width: {path}")
    size, = struct.unpack_from("<H", raw, pos)
    pos += 2
    substrate = raw[pos : pos + size].decode("utf-8")
    pos += size
    size, = struct.unpack_from("<H", raw, pos)
    pos += 2
    side = raw[pos : pos + size].decode("utf-8")
    pos += size
    block, = struct.unpack_from("<Q", raw, pos)
    pos += 8
    if arm == "a":
        dtype = np.dtype([("trial", "<u4"), ("coordinate", "<u4"), ("q", "<f8"), ("y", "i1"), ("x", "<f4", (WIDTH,))])
    else:
        dtype = np.dtype([("trial", "<u4"), ("coordinate", "<u4"), ("q", "<f8"), ("y", "i1"), ("abs_g", "<f8"), ("x", "<f8", (WIDTH,))])
    if (len(raw) - pos) % dtype.itemsize:
        raise RuntimeError(f"truncated stream: {path}")
    rows = np.frombuffer(raw, dtype=dtype, offset=pos)
    return (substrate, side, int(block)), rows


def finite_json(value, where="root"):
    if isinstance(value, dict):
        for key, item in value.items():
            finite_json(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            finite_json(item, f"{where}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise RuntimeError(f"nonfinite JSON value: {where}")


def main() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    analysis_path = ANALYSIS / "F4-PRECISION-01-ANALYSIS.json"
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    if sha(CONTRACT) != analysis["contract_sha256"]:
        raise RuntimeError("analysis references a different contract hash")
    for entry in contract["frozen_inputs"]:
        path = STUDY / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha(path) != entry["sha256"]:
            raise RuntimeError(f"frozen input mismatch: {entry['path']}")
    if sha(STUDY / contract["analysis_script"]) != contract["analysis_script_sha256"]:
        raise RuntimeError("analysis source hash mismatch")
    if analysis["status"] != "QUALIFICATION_ANALYSIS_COMPLETE" or analysis["rows"] != 13420:
        raise RuntimeError("analysis completion/row-count mismatch")
    finite_json(analysis)

    a_paths = sorted((STUDY / "runs/qualification-v2/f4-features-v1").glob("*.bin"))
    b_paths = sorted((DATA / "arm-b-f64").glob("*.bin"))
    c_paths = sorted((DATA / "arm-c-f32-features-f64-model").glob("*.bin"))
    if len(a_paths) != 72 or len(b_paths) != 72 or len(c_paths) != 72:
        raise RuntimeError("A/B/C stream cardinality mismatch")
    b_receipt = json.loads((DATA / "arm-b-f64/F64-COLLECTION-RECEIPT.json").read_text(encoding="utf-8"))
    c_receipt = json.loads((ANALYSIS / "C-QUANTIZATION-RECEIPT.json").read_text(encoding="utf-8"))
    if b_receipt["status"] != "COLLECTION_COMPLETE" or b_receipt["rows"] != 13420 or len(b_receipt["streams_manifest"]) != 72:
        raise RuntimeError("Arm B receipt mismatch")
    if c_receipt["status"] != "PASS" or c_receipt["rows"] != 13420 or c_receipt["streams"] != 72:
        raise RuntimeError("Arm C receipt mismatch")
    b_manifest = {item["path"]: item for item in b_receipt["streams_manifest"]}
    c_manifest = {item["path"]: item for item in c_receipt["files"]}
    if len(b_manifest) != 72 or len(c_manifest) != 72:
        raise RuntimeError("duplicate stream entry in B/C receipt")

    total_rows = 0
    cell_checks = []
    for ap, bp, cp in zip(a_paths, b_paths, c_paths):
        cell_a, a = parse_stream(ap, "a")
        cell_b, b = parse_stream(bp, "b")
        cell_c, c = parse_stream(cp, "c")
        if cell_a != cell_b or cell_b != cell_c:
            raise RuntimeError(f"cell key mismatch: {ap.name}")
        if bp.name not in b_manifest or cp.name not in c_manifest:
            raise RuntimeError(f"receipt missing stream: {bp.name}/{cp.name}")
        if sha(bp) != b_manifest[bp.name]["sha256"] or bp.stat().st_size != b_manifest[bp.name]["bytes"]:
            raise RuntimeError(f"B stream hash mismatch: {bp.name}")
        if sha(cp) != c_manifest[cp.name]["sha256"] or cp.stat().st_size != c_manifest[cp.name]["bytes"]:
            raise RuntimeError(f"C stream hash mismatch: {cp.name}")
        for field in ("trial", "coordinate", "q", "y"):
            if not np.array_equal(a[field], b[field]) or not np.array_equal(b[field], c[field]):
                raise RuntimeError(f"paired field mismatch {field}: {bp.name}")
        if not np.array_equal(b["abs_g"], c["abs_g"]):
            raise RuntimeError(f"B/C magnitude sidecar mismatch: {bp.name}")
        if not np.array_equal(b["x"].astype(np.float32).astype(np.float64), c["x"]):
            raise RuntimeError(f"C is not exact f32-quantized B: {cp.name}")
        for rows in (a, b, c):
            if not np.isfinite(rows["x"]).all():
                raise RuntimeError(f"nonfinite feature: {bp.name}")
            packed_ids = rows["trial"].astype(np.uint64) << 32 | rows["coordinate"].astype(np.uint64)
            if len(np.unique(packed_ids)) != len(rows):
                raise RuntimeError(f"duplicate row identity: {bp.name}")
        total_rows += len(a)
        cell_checks.append({"cell": list(cell_a), "rows": len(a)})
    if total_rows != 13420:
        raise RuntimeError(f"paired total rows mismatch: {total_rows}")

    expected_anchor = json.loads(PARENT.read_text(encoding="utf-8"))["findings"]["cross_block_80d"]
    if len(expected_anchor) != 4:
        raise RuntimeError("parent anchor fold count mismatch")
    arms = analysis["arms"]
    if set(arms) != {"A-f32-features-f32-model", "B-f64-features-f64-model", "C-f32-quantized-features-f64-model"}:
        raise RuntimeError("unexpected arm set")
    for name, arm in arms.items():
        folds = arm["folds"]
        if [row["holdout_block"] for row in folds] != BLOCKS:
            raise RuntimeError(f"fold set/order mismatch: {name}")
        if arm["pooled_oof"]["rows"] != 13420:
            raise RuntimeError(f"pooled row count mismatch: {name}")
    for actual, expected in zip(arms["A-f32-features-f32-model"]["folds"], expected_anchor):
        if abs(actual["balanced_error"] - expected["balanced_error"]) > 1e-8:
            raise RuntimeError("Arm A does not reproduce frozen parent anchor")
    if arms["A-f32-features-f32-model"]["folds"][-1]["two_class_supported"]:
        raise RuntimeError("expected class-degenerate final holdout annotation")
    if analysis["measured_namespace_created"] is not False or contract["measured_execution_authorized"] is not False:
        raise RuntimeError("measured boundary changed")
    if any((STUDY / relative).exists() for relative in ("runs/measured", "inputs/measured", "artifacts/measured")):
        raise RuntimeError("measured namespace exists")

    receipt = {
        "schema": "FLY-REACH-03-F4-PRECISION-01-integrity-receipt-v1",
        "identity": "F4-PRECISION-01-ANALYSIS-01",
        "status": "PASS_WITH_OUTCOME_ACCESS_SEQUENCE_DEVIATION",
        "contract_sha256": sha(CONTRACT),
        "integrity_verifier_sha256": sha(Path(__file__).resolve()),
        "frozen_inputs_verified": len(contract["frozen_inputs"]),
        "A_B_C_streams": {"A": len(a_paths), "B": len(b_paths), "C": len(c_paths)},
        "paired_rows": total_rows,
        "duplicate_or_missing_cell_count": 0,
        "duplicate_row_identity_count": 0,
        "nonfinite_feature_or_metric_count": 0,
        "arm_a_parent_anchor_match": True,
        "folds_per_arm": 4,
        "total_fit_cells": 12,
        "C_quantization_exact": True,
        "measured_namespace_created": False,
        "outcome_access_order_deviation": "Analysis JSON was inspected before this independent structural/hash audit receipt was generated. No settings or analysis were changed in response; classify outputs as qualification diagnostics, not blind confirmation.",
        "cells": cell_checks,
        "analysis_sha256": sha(analysis_path),
        "B_collection_receipt_sha256": sha(DATA / "arm-b-f64/F64-COLLECTION-RECEIPT.json"),
        "C_quantization_receipt_sha256": sha(ANALYSIS / "C-QUANTIZATION-RECEIPT.json"),
    }
    output = ANALYSIS / "INTEGRITY-RECEIPT.json"
    if output.exists():
        raise RuntimeError("integrity receipt already exists; preserve and stop")
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "verified_inputs": receipt["frozen_inputs_verified"], "rows": total_rows, "fits": 12, "measured_namespace_created": False}))


if __name__ == "__main__":
    main()
