#!/usr/bin/env python3
"""Stricter independent pre-fit audit for the frozen R1 extraction v03.

This version adds exact serialized row-order and input-text reconciliation to
the v03 hash/shape/finite checks. It reads no target or action-label file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

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


def expected_rows(
    name_queries: list[dict[str, Any]], public_tasks: list[dict[str, Any]]
) -> Iterator[tuple[str, dict[str, Any]]]:
    for query in name_queries:
        yield "name", {
            "name_id": query["name_id"],
            "surface": query["surface"],
            "input_text_sha256": sha256_bytes(query["surface"].encode("utf-8")),
        }
    for task_index, task in enumerate(public_tasks):
        yield "global", {
            "task_index": task_index,
            "task_id": task["id"],
            "family_id": task["family_id"],
            "input_text_sha256": sha256_bytes(task["global_text"].encode("utf-8")),
        }
        for clause_index, clause in enumerate(task["clauses"]):
            yield "constraint", {
                "task_index": task_index,
                "task_id": task["id"],
                "family_id": task["family_id"],
                "clause_index": clause_index,
                "input_text_sha256": sha256_bytes(clause.encode("utf-8")),
            }


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
    for field in ("fit_performed", "selector_training_performed", "proposal_training_performed", "reach_value_training_performed"):
        if receipt.get(field):
            raise ValueError(f"extraction receipt reports downstream work: {field}")
    if not receipt["model"]["eval_mode"] or not receipt["model"]["inference_mode"]:
        raise ValueError("backbone was not in eval/inference mode")
    verification = receipt["extraction"]["verification"]
    if verification["exact_repeat_match"] is not True or verification["repeat_1_output_float32_sha256"] != verification["repeat_2_output_float32_sha256"]:
        raise ValueError("repeat inference was not byte-identical")

    expected_input = manifest["prepared_inputs"]["public_probe_tasks"]
    expected_names = manifest["prepared_inputs"]["name_queries"]
    for expected in (expected_input, expected_names):
        digest, size = sha256_file(data_root / expected["path"])
        if digest != expected["sha256"] or size != expected["bytes"]:
            raise ValueError(f"frozen public input changed: {expected['path']}")
    if receipt["input"]["sha256"] != expected_input["sha256"] or receipt["input"]["name_query"]["sha256"] != expected_names["sha256"]:
        raise ValueError("extraction receipt input hashes mismatch")
    if receipt["model"]["revision"] != manifest["model"]["revision"]:
        raise ValueError("model revision mismatch")
    inventory_path = Path(manifest["model"]["inventory_path"])
    inventory_hash, _ = sha256_file(inventory_path)
    if inventory_hash != manifest["model"]["inventory_sha256"] or receipt["model"]["snapshot_inventory_sha256"] != inventory_hash:
        raise ValueError("frozen model inventory hash mismatch")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if receipt["model"]["snapshot_files"] != inventory["files"] or receipt["model"]["tokenizer_files"] != inventory["tokenizer_files"]:
        raise ValueError("loaded snapshot file inventories mismatch")

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
    descriptors = list(expected_rows(name_queries, public_tasks))
    if len(rows) != len(descriptors):
        raise ValueError(f"row count mismatch: {len(rows)} != {len(descriptors)}")
    row_indices = {"name": 0, "global": 0, "constraint": 0}
    for ordinal, (row, (kind, expected)) in enumerate(zip(rows, descriptors, strict=True)):
        if row.get("kind") != kind:
            raise ValueError(f"row kind/order mismatch at serialized row {ordinal}")
        for field, value in expected.items():
            if row.get(field) != value:
                raise ValueError(f"row {ordinal} {field} mismatch")
        index = int(row["row"])
        if index != row_indices[kind]:
            raise ValueError(f"array row order mismatch for {kind} at serialized row {ordinal}")
        raw = np.asarray(arrays[
            {"name": "name_H.float32.npy", "global": "global_h.float32.npy", "constraint": "constraint_H.float32.npy"}[kind]
        ][index], dtype="<f4").tobytes(order="C")
        if sha256_bytes(raw) != row["output_float32_sha256"]:
            raise ValueError(f"row vector hash mismatch at serialized row {ordinal}")
        row_indices[kind] += 1
    if row_indices != {"name": len(name_queries), "global": len(public_tasks), "constraint": constraint_count}:
        raise ValueError("feature array row coverage is incomplete")

    expected_outputs = {entry["path"]: entry for entry in receipt["output_files"]}
    actual_files = {path.name for path in extraction.iterdir() if path.is_file() and path.name not in {"receipt.json", "EXTRACTION-INTEGRITY-RECEIPT-v03.json", "EXTRACTION-INTEGRITY-RECEIPT-v04.json"}}
    if actual_files != set(expected_outputs):
        raise ValueError("extraction output file set differs from receipt")
    for filename, entry in expected_outputs.items():
        digest, size = sha256_file(extraction / filename)
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise ValueError(f"output file hash mismatch: {filename}")

    return {
        "schema": "R1_SENSOR_EXTRACTION_INTEGRITY_V04",
        "status": "PASS",
        "validator_source_sha256": sha256_file(Path(__file__))[0],
        "manifest_sha256": manifest_hash,
        "receipt_sha256": sha256_file(receipt_path)[0],
        "public_input_sha256": expected_input["sha256"],
        "name_query_sha256": expected_names["sha256"],
        "model_revision": manifest["model"]["revision"],
        "model_inventory_sha256": inventory_hash,
        "row_counts": row_indices,
        "array_shapes": {name: list(array.shape) for name, array in arrays.items()},
        "finite_feature_values": True,
        "exact_row_order_and_text_mapping": True,
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
        write_json_new(args.extraction / "EXTRACTION-INTEGRITY-RECEIPT-v04.json", receipt)
        print(json.dumps(receipt, sort_keys=True, indent=2))
    except Exception as error:
        print(f"R1_SENSOR_EXTRACTION_INTEGRITY_STOP: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
