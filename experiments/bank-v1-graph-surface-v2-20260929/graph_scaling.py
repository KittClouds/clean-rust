"""TRAIN-only normalization and content-addressed scaler cache."""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import numpy as np

from common import (cached_surface_arrays, local_surface_arrays, sha256,
                    write_json)


def calculate_node_scaler(arrays, entity_ids, goal_ids, surface):
    dimensions = 2048 if surface in ("middle_plus_final", "final_plus_mean") else 1024
    total = np.zeros(dimensions, dtype=np.float64)
    squares = np.zeros(dimensions, dtype=np.float64)
    count = 0
    for group, ids in (("entity", entity_ids), ("goal", goal_ids)):
        for start in range(0, len(ids), 4096):
            indexes = ids[start:start + 4096]
            if not len(indexes):
                continue
            block = local_surface_arrays(arrays[group], indexes, surface).astype(np.float64, copy=False)
            total += block.sum(axis=0)
            squares += np.einsum("ij,ij->j", block, block, optimize=True)
            count += len(block)
    if count < 2:
        raise RuntimeError(f"insufficient TRAIN node vectors to standardize {surface}")
    mean = total / count
    scale = np.sqrt(np.maximum(squares / count - mean * mean, 0.0))
    scale[scale == 0] = 1.0
    return mean.astype(np.float32), scale.astype(np.float32)


def calculate_row_scaler(primitives, train_rows, surface):
    dimensions = 1024 if surface in ("layer_m4_final", "full_mean", "first_token") else 2048
    total = np.zeros(dimensions, dtype=np.float64)
    squares = np.zeros(dimensions, dtype=np.float64)
    count = 0
    for start in range(0, len(train_rows), 4096):
        indexes = train_rows[start:start + 4096]
        block = cached_surface_arrays(primitives, indexes, surface).astype(np.float64, copy=False)
        total += block.sum(axis=0)
        squares += np.einsum("ij,ij->j", block, block, optimize=True)
        count += len(block)
    mean = total / max(count, 1)
    scale = np.sqrt(np.maximum(squares / max(count, 1) - mean * mean, 0.0))
    scale[scale == 0] = 1.0
    return mean.astype(np.float32), scale.astype(np.float32)


def make_scalers(local_arrays, row_arrays, train_rows, entity_ids, goal_ids, surfaces):
    local = {surface: calculate_node_scaler(local_arrays, entity_ids, goal_ids, surface)
             for surface in surfaces}
    row = {surface: calculate_row_scaler(row_arrays, train_rows, surface)
           for surface in (*surfaces, "first_token")}
    return {"local": local, "row": row}


def scaler_basis(output, receipt, graph_data_report, train_rows, entity_ids, goal_ids,
                 scaler_code_functions):
    def index_hash(values):
        return hashlib.sha256(np.ascontiguousarray(values).view(np.uint8)).hexdigest()
    code = "\n".join(inspect.getsource(fn) for fn in scaler_code_functions)
    return {"extraction_seal_sha256": sha256(output / "features" / "extraction-seal.json"),
            "graph_task_data_sha256": sha256(output / "graph-task-data-report.json"),
            "rowmap_sha256": sha256(output / "rowmap.jsonl"),
            "train_rows_sha256": index_hash(train_rows),
            "train_entity_indices_sha256": index_hash(entity_ids),
            "train_goal_indices_sha256": index_hash(goal_ids),
            "scaler_code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "r0_feature_seal_sha256": receipt["source"]["r0_feature_seal_sha256"]}


def scaler_files(scaler_dir, surfaces):
    files = {}
    for view, names in (("local", surfaces), ("row", (*surfaces, "first_token"))):
        for name in names:
            path = scaler_dir / f"{view}-{name}.npz"
            if not path.is_file():
                return None
            with np.load(path, allow_pickle=False) as data:
                mean, scale = data["mean"], data["scale"]
                if (mean.ndim != 1 or mean.shape != scale.shape or
                        not np.isfinite(mean).all() or not np.isfinite(scale).all()):
                    return None
            files[path.name] = {"sha256": sha256(path), "shape": list(mean.shape)}
    return files


def load_scaler_cache(scaler_dir, basis, surfaces):
    seal_path = scaler_dir / "scaler-seal.json"
    if not seal_path.is_file():
        return None, None
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("basis") != basis:
        return None, None
    current_files = scaler_files(scaler_dir, surfaces)
    if current_files is None or current_files != seal.get("files"):
        return None, None
    scalers = {"local": {}, "row": {}}
    for view, names in (("local", surfaces), ("row", (*surfaces, "first_token"))):
        for name in names:
            with np.load(scaler_dir / f"{view}-{name}.npz", allow_pickle=False) as data:
                scalers[view][name] = (data["mean"].copy(), data["scale"].copy())
    return scalers, sha256(seal_path)


def seal_scalers(scaler_dir, basis, scalers, surfaces):
    for view, values in scalers.items():
        for name, pair in values.items():
            np.savez(scaler_dir / f"{view}-{name}.npz", mean=pair[0], scale=pair[1])
    files = scaler_files(scaler_dir, surfaces)
    if files is None:
        raise RuntimeError("failed to validate fitted scaler artifacts")
    seal_path = scaler_dir / "scaler-seal.json"
    write_json(seal_path, {"schema": "phoenix.bank-v1.graph-scaler-seal/v1",
                           "basis": basis, "files": files})
    return sha256(seal_path)
