#!/usr/bin/env python3
"""Materialize the V05 frozen sensor rows for train/validation tasks only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


HIDDEN = 2048
MODEL_REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _file_record(path: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    return {"sha256": digest, "bytes": size}


def slice_features(extraction_dir: Path, view_dir: Path, output_dir: Path) -> dict[str, Any]:
    extraction = extraction_dir.resolve(strict=True)
    view = view_dir.resolve(strict=True)
    output = output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite V05 train/validation features {output}")

    view_receipt_path = view / "trainval-view-receipt-v05-v01.json"
    view_receipt = json.loads(view_receipt_path.read_text(encoding="utf-8"))
    if view_receipt.get("status") != "TRAIN_VALIDATION_VIEW_COMPLETE" or view_receipt.get("qualification_rows_emitted") != 0:
        raise ValueError("V05 input view is not train/validation-only")
    trainval_public_path = view / "public-tasks-trainval-v05.jsonl"
    public_rows = read_jsonl(trainval_public_path)
    task_ids = [row["id"] for row in public_rows]
    if len(task_ids) != 80 or len(set(task_ids)) != 80:
        raise ValueError("V05 train/validation public view must contain 80 unique tasks")
    task_index = {task_id: index for index, task_id in enumerate(task_ids)}
    view_support = json.loads((view / "stress-support-trainval-v05.json").read_text(encoding="utf-8"))
    split_by_task = {row["task_id"]: row["split"] for row in view_support.get("family_roster", [])}
    if set(split_by_task) != set(task_ids) or set(split_by_task.values()) != {"train", "validation"}:
        raise ValueError("train/validation support roster differs from the public task view")

    extraction_receipt_path = extraction / "receipt.json"
    extraction_receipt = json.loads(extraction_receipt_path.read_text(encoding="utf-8"))
    if (
        extraction_receipt.get("status") != "R1_SENSOR_EXTRACTION_COMPLETE"
        or extraction_receipt.get("schema") != "R1_STAGE1_SENSOR_EXTRACTION_V01"
        or extraction_receipt.get("model", {}).get("revision") != MODEL_REVISION
        or extraction_receipt.get("model", {}).get("repo_id") != "LiquidAI/LFM2.5-1.2B-Base"
    ):
        raise ValueError("frozen V05 sensor extraction identity changed")
    expected_files = {row["path"]: row for row in extraction_receipt.get("output_files", [])}
    source_arrays: dict[str, np.ndarray] = {}
    for name in ("constraint_H.float32.npy", "global_h.float32.npy"):
        path = extraction / name
        observed = _file_record(path)
        expected = expected_files.get(name, {})
        if observed["sha256"] != expected.get("sha256") or observed["bytes"] != expected.get("bytes"):
            raise ValueError(f"frozen V05 sensor array hash mismatch: {name}")
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        if array.dtype != np.dtype("<f4") or array.ndim != 2 or array.shape[1] != HIDDEN:
            raise ValueError(f"unexpected frozen sensor array shape/dtype for {name}: {array.shape}/{array.dtype}")
        source_arrays[name] = array

    rows_path = extraction / "rows.jsonl"
    rows_record = _file_record(rows_path)
    expected_rows = expected_files.get("rows.jsonl", {})
    if rows_record["sha256"] != expected_rows.get("sha256") or rows_record["bytes"] != expected_rows.get("bytes"):
        raise ValueError("frozen sensor row map hash mismatch")
    global_index: dict[str, int] = {}
    clause_indices: dict[str, dict[int, int]] = {}
    for row in read_jsonl(rows_path):
        task_id = row.get("task_id")
        if task_id not in task_index:
            continue
        if row.get("split") not in ("train", "validation"):
            raise ValueError(f"selected sensor feature has forbidden split for {task_id}")
        if row.get("kind") == "global":
            if task_id in global_index:
                raise ValueError(f"duplicate V05 global feature for {task_id}")
            global_index[task_id] = int(row["row"])
        elif row.get("kind") == "constraint":
            clause_index = int(row["clause_index"])
            task_clauses = clause_indices.setdefault(task_id, {})
            if clause_index in task_clauses:
                raise ValueError(f"duplicate V05 constraint feature {task_id}:{clause_index}")
            task_clauses[clause_index] = int(row["row"])
        else:
            raise ValueError(f"unknown frozen sensor row kind {row.get('kind')!r}")
    if set(global_index) != set(task_ids) or set(clause_indices) != set(task_ids):
        raise ValueError("frozen sensor rows do not cover the 80 V05 train/validation tasks")

    n_constraints = sum(len(row.get("clauses", [])) for row in public_rows)
    global_out = np.empty((len(task_ids), HIDDEN), dtype="<f4")
    constraint_out = np.empty((n_constraints, HIDDEN), dtype="<f4")
    new_rows: list[dict[str, Any]] = []
    clause_cursor = 0
    for new_task_index, task in enumerate(public_rows):
        task_id = task["id"]
        old_global_row = global_index[task_id]
        global_vector = np.asarray(source_arrays["global_h.float32.npy"][old_global_row], dtype="<f4")
        global_out[new_task_index] = global_vector
        new_rows.append({
            "kind": "global", "task_index": new_task_index, "task_id": task_id,
            "family_id": task["family_id"], "split": split_by_task[task_id],
            "row": new_task_index,
            "output_float32_sha256": hashlib.sha256(global_vector.tobytes(order="C")).hexdigest(),
        })
        clause_map = clause_indices[task_id]
        if set(clause_map) != set(range(len(task["clauses"]))):
            raise ValueError(f"V05 clause feature coverage differs for {task_id}")
        for clause_id in range(len(task["clauses"])):
            old_row = clause_map[clause_id]
            vector = np.asarray(source_arrays["constraint_H.float32.npy"][old_row], dtype="<f4")
            constraint_out[clause_cursor] = vector
            new_rows.append({
                "kind": "constraint", "task_index": new_task_index, "task_id": task_id,
                "family_id": task["family_id"], "split": split_by_task[task_id],
                "clause_index": clause_id, "row": clause_cursor,
                "output_float32_sha256": hashlib.sha256(vector.tobytes(order="C")).hexdigest(),
            })
            clause_cursor += 1
    if not np.isfinite(global_out).all() or not np.isfinite(constraint_out).all():
        raise ValueError("V05 selected sensor features contain non-finite values")

    output.mkdir(parents=True)
    global_path = output / "global_h_trainval.float32.npy"
    constraints_path = output / "constraint_H_trainval.float32.npy"
    rows_out_path = output / "rows_trainval.jsonl"
    np.save(global_path, global_out, allow_pickle=False)
    np.save(constraints_path, constraint_out, allow_pickle=False)
    rows_out_path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in new_rows),
        encoding="utf-8",
    )
    outputs = {path.name: _file_record(path) for path in (global_path, constraints_path, rows_out_path)}
    receipt = {
        "schema": "R1_STAGE1_FROZEN_FEATURES_TRAINVAL_V05_V01",
        "status": "V05_TRAINVAL_FEATURES_COMPLETE",
        "view_receipt_sha256": sha256_file(view_receipt_path)[0],
        "trainval_public_tasks_sha256": sha256_file(trainval_public_path)[0],
        "source_sensor_receipt_sha256": sha256_file(extraction_receipt_path)[0],
        "source_sensor_array_hashes": {
            name: expected_files[name]["sha256"] for name in ("constraint_H.float32.npy", "global_h.float32.npy", "rows.jsonl")
        },
        "model_revision": MODEL_REVISION,
        "task_rows": 80,
        "train_rows": 64,
        "validation_rows": 16,
        "qualification_rows_emitted": 0,
        "qualification_targets_generated": False,
        "qualification_target_paths_or_hashes_recorded": False,
        "feature_shape": {"global": list(global_out.shape), "constraints": list(constraint_out.shape)},
        "outputs": outputs,
        "row_map_sha256": outputs[rows_out_path.name]["sha256"],
    }
    receipt_path = output / "frozen-features-trainval-receipt-v05-v01.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction-dir", type=Path, required=True)
    parser.add_argument("--view-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = slice_features(args.extraction_dir, args.view_dir, args.output)
    print(f"R1_V05_TRAINVAL_FEATURES_COMPLETE tasks=80 output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
