#!/usr/bin/env python3
"""Independent pre-fit integrity audit for R1 sensor extraction v03.

Reads public extraction inputs and feature outputs only. It never opens the
private target or action-label files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json_new(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def audit(manifest_path: Path, extraction: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_hash, _ = sha256_file(manifest_path)
    sidecar = manifest_path.with_suffix(".sha256").read_text(encoding="ascii").split()[0].lower()
    if manifest_hash != sidecar:
        raise ValueError("frozen manifest SHA-256 sidecar mismatch")
    if manifest.get("identity") != "R1-STAGE1-SENSOR-QUALIFICATION-v03":
        raise ValueError("unexpected sensor manifest identity")
    data_root = Path(manifest["prepared_inputs"]["root"])
    receipt_path = extraction / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "R1_SENSOR_EXTRACTION_COMPLETE":
        raise ValueError("extraction did not complete")
    if receipt.get("fit_performed") or receipt.get("selector_training_performed") or receipt.get("proposal_training_performed"):
        raise ValueError("extraction receipt reports downstream fitting/training")
    if not receipt["model"]["eval_mode"] or not receipt["model"]["inference_mode"]:
        raise ValueError("backbone was not in eval/inference mode")
    if receipt["extraction"]["verification"]["exact_repeat_match"] is not True:
        raise ValueError("repeat inference did not match byte-for-byte")
    if receipt["extraction"]["verification"]["repeat_1_output_float32_sha256"] != receipt["extraction"]["verification"]["repeat_2_output_float32_sha256"]:
        raise ValueError("repeat output hashes differ")

    expected_input = manifest["prepared_inputs"]["public_probe_tasks"]
    expected_names = manifest["prepared_inputs"]["name_queries"]
    for name, expected in (("public-probe-tasks.jsonl", expected_input), ("name-queries.jsonl", expected_names)):
        digest, size = sha256_file(data_root / expected["path"])
        if digest != expected["sha256"] or size != expected["bytes"]:
            raise ValueError(f"frozen {name} changed")
    if receipt["input"]["sha256"] != expected_input["sha256"]:
        raise ValueError("receipt public-input hash mismatch")
    if receipt["input"]["name_query"]["sha256"] != expected_names["sha256"]:
        raise ValueError("receipt name-query hash mismatch")
    if receipt["model"]["revision"] != manifest["model"]["revision"]:
        raise ValueError("receipt model revision mismatch")
    if receipt["model"]["snapshot_inventory_sha256"] != manifest["model"]["inventory_sha256"]:
        raise ValueError("receipt snapshot inventory hash mismatch")

    inventory = json.loads(Path(manifest["model"]["inventory_path"]).read_text(encoding="utf-8"))
    if receipt["model"]["snapshot_files"] != inventory["files"]:
        raise ValueError("loaded snapshot file inventory differs from frozen inventory")
    if receipt["model"]["tokenizer_files"] != inventory["tokenizer_files"]:
        raise ValueError("loaded tokenizer inventory differs from frozen inventory")

    public_tasks = read_jsonl(data_root / expected_input["path"])
    name_queries = read_jsonl(data_root / expected_names["path"])
    constraint_count = sum(len(task["clauses"]) for task in public_tasks)
    hidden = int(manifest["model"]["hidden_size"])
    arrays = {
        "constraint_H.float32.npy": np.load(extraction / "constraint_H.float32.npy", mmap_mode="r"),
        "global_h.float32.npy": np.load(extraction / "global_h.float32.npy", mmap_mode="r"),
        "name_H.float32.npy": np.load(extraction / "name_H.float32.npy", mmap_mode="r"),
    }
    expected_shapes = {
        "constraint_H.float32.npy": (constraint_count, hidden),
        "global_h.float32.npy": (len(public_tasks), hidden),
        "name_H.float32.npy": (len(name_queries), hidden),
    }
    for filename, array in arrays.items():
        if array.shape != expected_shapes[filename] or array.dtype.str != "<f4":
            raise ValueError(f"shape/dtype mismatch for {filename}: {array.shape} {array.dtype}")
        if not np.isfinite(array).all():
            raise ValueError(f"non-finite feature values in {filename}")

    rows = read_jsonl(extraction / "rows.jsonl")
    expected_rows = len(name_queries) + len(public_tasks) + constraint_count
    if len(rows) != expected_rows:
        raise ValueError(f"row count mismatch: {len(rows)} != {expected_rows}")
    seen_names: set[str] = set()
    seen_global: set[str] = set()
    seen_constraints: set[tuple[str, int]] = set()
    row_counts = {"name": 0, "global": 0, "constraint": 0}
    for row in rows:
        kind = row.get("kind")
        if kind == "name":
            index = int(row["row"])
            if row["name_id"] in seen_names or index < 0 or index >= len(name_queries):
                raise ValueError("duplicate or out-of-range name row")
            query = name_queries[index]
            if row["name_id"] != query["name_id"] or row["surface"] != query["surface"]:
                raise ValueError("name row mapping mismatch")
            vector = arrays["name_H.float32.npy"][index]
            seen_names.add(row["name_id"])
        elif kind == "global":
            index = int(row["row"])
            if row["task_id"] in seen_global or index < 0 or index >= len(public_tasks):
                raise ValueError("duplicate or out-of-range global row")
            task = public_tasks[index]
            if row["task_id"] != task["id"] or row["task_index"] != index:
                raise ValueError("global row mapping mismatch")
            vector = arrays["global_h.float32.npy"][index]
            seen_global.add(row["task_id"])
        elif kind == "constraint":
            index = int(row["row"])
            key = (row["task_id"], int(row["clause_index"]))
            if key in seen_constraints or index < 0 or index >= constraint_count:
                raise ValueError("duplicate or out-of-range constraint row")
            vector = arrays["constraint_H.float32.npy"][index]
            seen_constraints.add(key)
        else:
            raise ValueError(f"unknown extracted row kind {kind!r}")
        raw = np.asarray(vector, dtype="<f4").tobytes(order="C")
        if sha256_bytes(raw) != row["output_float32_sha256"]:
            raise ValueError("row vector hash mismatch")
        row_counts[kind] += 1
    if len(seen_names) != len(name_queries) or len(seen_global) != len(public_tasks) or len(seen_constraints) != constraint_count:
        raise ValueError("feature row key coverage is incomplete")

    expected_outputs = {entry["path"]: entry for entry in receipt["output_files"]}
    actual_files = {path.name for path in extraction.iterdir() if path.is_file() and path.name != "receipt.json"}
    if actual_files != set(expected_outputs):
        raise ValueError("extraction output file set differs from receipt")
    for filename, entry in expected_outputs.items():
        digest, size = sha256_file(extraction / filename)
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise ValueError(f"output file hash mismatch: {filename}")

    return {
        "schema": "R1_SENSOR_EXTRACTION_INTEGRITY_V03",
        "status": "PASS",
        "manifest_sha256": manifest_hash,
        "receipt_sha256": sha256_file(receipt_path)[0],
        "public_input_sha256": expected_input["sha256"],
        "name_query_sha256": expected_names["sha256"],
        "model_revision": manifest["model"]["revision"],
        "model_inventory_sha256": manifest["model"]["inventory_sha256"],
        "row_counts": row_counts,
        "array_shapes": {name: list(array.shape) for name, array in arrays.items()},
        "finite_feature_values": True,
        "all_row_hashes_match": True,
        "all_output_hashes_match": True,
        "repeat_inference_byte_identical": True,
        "private_targets_opened": False,
        "action_labels_opened": False,
        "probe_fitting_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--extraction", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = audit(args.manifest.resolve(strict=True), args.extraction.resolve(strict=True))
        path = args.extraction / "EXTRACTION-INTEGRITY-RECEIPT-v03.json"
        write_json_new(path, receipt)
        print(json.dumps(receipt, sort_keys=True, indent=2))
    except Exception as error:
        print(f"R1_SENSOR_EXTRACTION_INTEGRITY_STOP: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
