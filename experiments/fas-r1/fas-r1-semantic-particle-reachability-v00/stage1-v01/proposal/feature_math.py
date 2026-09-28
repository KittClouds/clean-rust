"""Feature artifact checks and shared R1 candidate/value feature builders."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

HIDDEN_DIM = 2048
LATENT_DIM = 128
MAX_ENTITIES = 20
MAX_ROLES = 6
STATIC_CANDIDATE_DIM = 8
PROPOSAL_INPUT_DIM = 10


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"invalid JSON at {path}:{line_number}: {error}") from error
    return rows


@dataclass
class FeatureTask:
    task_id: str
    family_id: str
    split: str
    global_h: np.ndarray
    clause_h: np.ndarray
    entity_mentions: list[list[int]]
    role_mentions: list[list[int]]
    input_row: dict[str, Any]


@dataclass
class FeatureStore:
    sensor_dir: Path
    receipt_sha256: str
    receipt: dict[str, Any]
    tasks: dict[str, FeatureTask]


def load_feature_store(
    sensor_dir: Path,
    public_task_path: Path,
    public_tasks: list[dict[str, Any]],
    support_manifest_path: Path,
) -> FeatureStore:
    sensor_dir = sensor_dir.resolve(strict=True)
    receipt_path = sensor_dir / "receipt.json"
    receipt_sha256, _ = sha256_file(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "R1_SENSOR_EXTRACTION_COMPLETE":
        raise ValueError("sensor receipt is not a completed frozen extraction")
    if receipt.get("schema") != "R1_STAGE1_SENSOR_EXTRACTION_V01":
        raise ValueError(f"unsupported sensor feature schema {receipt.get('schema')!r}")
    input_record = receipt.get("input", {})
    public_sha, _ = sha256_file(public_task_path)
    if input_record.get("sha256") != public_sha:
        raise ValueError("sensor extraction was made from a different public-task JSONL")
    support_sha, _ = sha256_file(support_manifest_path)
    embedded_support = input_record.get("support_manifest") or {}
    if embedded_support.get("sha256") != support_sha:
        raise ValueError("sensor extraction used a different support manifest")
    if input_record.get("public_task_count") != len(public_tasks):
        raise ValueError("sensor feature task count differs from public task count")

    expected_files = {
        row["path"]: row["sha256"] for row in receipt.get("output_files", [])
    }
    arrays = {}
    for filename in ("constraint_H.float32.npy", "global_h.float32.npy", "rows.jsonl"):
        path = sensor_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"sensor extraction is missing {filename}")
        observed, _ = sha256_file(path)
        if expected_files.get(filename) != observed:
            raise ValueError(f"sensor extraction hash mismatch for {filename}")
        if filename.endswith(".npy"):
            array = np.load(path, mmap_mode="r", allow_pickle=False)
            if array.dtype != np.dtype("<f4"):
                raise ValueError(f"{filename} must contain little-endian float32, got {array.dtype}")
            arrays[filename] = array

    global_h = arrays["global_h.float32.npy"]
    constraint_h = arrays["constraint_H.float32.npy"]
    if global_h.shape != (len(public_tasks), HIDDEN_DIM):
        raise ValueError(f"global feature shape is {global_h.shape}, expected {(len(public_tasks), HIDDEN_DIM)}")
    clause_total = sum(len(task.get("clauses", [])) for task in public_tasks)
    if constraint_h.shape != (clause_total, HIDDEN_DIM):
        raise ValueError(f"constraint feature shape is {constraint_h.shape}, expected {(clause_total, HIDDEN_DIM)}")

    index_by_id = {task["id"]: index for index, task in enumerate(public_tasks)}
    if len(index_by_id) != len(public_tasks):
        raise ValueError("public task IDs are not unique")
    feature_rows = read_jsonl(sensor_dir / "rows.jsonl")
    global_rows: dict[str, int] = {}
    clause_rows: dict[str, dict[int, int]] = {}
    for row in feature_rows:
        task_id = row.get("task_id")
        if task_id not in index_by_id:
            raise ValueError(f"sensor feature row names unknown task {task_id!r}")
        task_index = index_by_id[task_id]
        task = public_tasks[task_index]
        if row.get("task_index") != task_index or row.get("family_id") != task["family_id"]:
            raise ValueError(f"task order/family mismatch in sensor rows for {task_id}")
        if row.get("split") not in ("train", "validation", "qualification"):
            raise ValueError(f"invalid family split in sensor row for {task_id}")
        feature_index = int(row["row"])
        if row.get("kind") == "global":
            if task_id in global_rows or feature_index >= global_h.shape[0]:
                raise ValueError(f"duplicate or out-of-range global row for {task_id}")
            vector = np.asarray(global_h[feature_index], dtype="<f4")
            if hashlib.sha256(vector.tobytes(order="C")).hexdigest() != row.get("output_float32_sha256"):
                raise ValueError(f"global embedding row digest mismatch for {task_id}")
            global_rows[task_id] = feature_index
        elif row.get("kind") == "constraint":
            clause_index = int(row["clause_index"])
            if feature_index >= constraint_h.shape[0]:
                raise ValueError(f"constraint row out of range for {task_id}")
            by_clause = clause_rows.setdefault(task_id, {})
            if clause_index in by_clause:
                raise ValueError(f"duplicate constraint feature row for {task_id}:{clause_index}")
            vector = np.asarray(constraint_h[feature_index], dtype="<f4")
            if hashlib.sha256(vector.tobytes(order="C")).hexdigest() != row.get("output_float32_sha256"):
                raise ValueError(f"constraint embedding row digest mismatch for {task_id}:{clause_index}")
            by_clause[clause_index] = feature_index
        else:
            raise ValueError(f"unknown feature row kind in sensor rows: {row.get('kind')!r}")

    split_manifest = json.loads(support_manifest_path.read_text(encoding="utf-8"))
    split_by_id = {
        row["task_id"]: row["split"] for row in split_manifest.get("family_roster", [])
    }
    if set(global_rows) != set(index_by_id):
        raise ValueError("sensor global rows do not cover every public task exactly once")

    result: dict[str, FeatureTask] = {}
    for task_id, task_index in index_by_id.items():
        task = public_tasks[task_index]
        indices_by_clause = clause_rows.get(task_id, {})
        expected_clause_count = len(task.get("clauses", []))
        if set(indices_by_clause) != set(range(expected_clause_count)):
            raise ValueError(f"sensor clause rows are incomplete for {task_id}")
        ordered_rows = [indices_by_clause[index] for index in range(expected_clause_count)]
        clause_vectors = constraint_h[np.asarray(ordered_rows, dtype=np.int64)]
        if not np.isfinite(global_h[global_rows[task_id]]).all() or not np.isfinite(clause_vectors).all():
            raise ValueError(f"non-finite sensor feature for {task_id}")
        split = split_by_id.get(task_id)
        if split not in ("train", "validation", "qualification"):
            raise ValueError(f"task {task_id} absent from support split roster")
        result[task_id] = FeatureTask(
            task_id=task_id,
            family_id=task["family_id"],
            split=split,
            global_h=np.asarray(global_h[global_rows[task_id]], dtype=np.float32),
            clause_h=np.asarray(clause_vectors, dtype=np.float32),
            entity_mentions=task["entity_mentions"],
            role_mentions=task["role_mentions"],
            input_row=task,
        )
    return FeatureStore(sensor_dir, receipt_sha256, receipt, result)


def build_static_candidate_features(task: FeatureTask, n: int, k: int) -> np.ndarray:
    """Return the eight H-only features for every entity/role pair.

    Occupancy features are deliberately excluded here and appended from the
    assignment in both the PyTorch training code and Rust frozen adapter.
    Accumulation uses float64 before a final float32 cast.
    """
    if n < 1 or k < 1 or n > MAX_ENTITIES or k > MAX_ROLES:
        raise ValueError(f"unsupported task dimensions n={n}, k={k}")
    clause_count, hidden_dim = task.clause_h.shape
    if hidden_dim != HIDDEN_DIM:
        raise ValueError(f"unexpected hidden width {hidden_dim}")
    global64 = np.asarray(task.global_h, dtype=np.float64)
    clause64 = np.asarray(task.clause_h, dtype=np.float64)
    entity_sum = np.zeros((n, hidden_dim), dtype=np.float64)
    role_sum = np.zeros((k, hidden_dim), dtype=np.float64)
    entity_count = np.zeros(n, dtype=np.int64)
    role_count = np.zeros(k, dtype=np.int64)
    pair_count = np.zeros((n, k), dtype=np.int64)
    for clause_index, vector in enumerate(clause64):
        entities = task.entity_mentions[clause_index]
        roles = task.role_mentions[clause_index]
        for entity in entities:
            if not 0 <= entity < n:
                raise ValueError(f"entity mention out of range in {task.task_id}")
            entity_sum[entity] += vector
            entity_count[entity] += 1
            for role in roles:
                if not 0 <= role < k:
                    raise ValueError(f"role mention out of range in {task.task_id}")
                pair_count[entity, role] += 1
        for role in roles:
            if not 0 <= role < k:
                raise ValueError(f"role mention out of range in {task.task_id}")
            role_sum[role] += vector
            role_count[role] += 1
    entity_ctx = np.zeros_like(entity_sum)
    role_ctx = np.zeros_like(role_sum)
    for entity in range(n):
        if entity_count[entity]:
            entity_ctx[entity] = entity_sum[entity] / entity_count[entity]
    for role in range(k):
        if role_count[role]:
            role_ctx[role] = role_sum[role] / role_count[role]

    global_norm = float(np.linalg.norm(global64))
    entity_norm = np.linalg.norm(entity_ctx, axis=1)
    role_norm = np.linalg.norm(role_ctx, axis=1)
    rows = np.zeros((n, k, STATIC_CANDIDATE_DIM), dtype=np.float32)
    clause_denominator = max(clause_count, 1)
    dim_scale = math.sqrt(hidden_dim)
    for entity in range(n):
        for role in range(k):
            ev = entity_ctx[entity]
            rv = role_ctx[role]
            en = float(entity_norm[entity])
            rn = float(role_norm[role])
            cosine_global_entity = float(np.dot(global64, ev)) / (global_norm * en + 1e-12)
            cosine_global_role = float(np.dot(global64, rv)) / (global_norm * rn + 1e-12)
            cosine_entity_role = float(np.dot(ev, rv)) / (en * rn + 1e-12)
            rows[entity, role] = (
                cosine_global_entity,
                cosine_global_role,
                cosine_entity_role,
                en / dim_scale,
                rn / dim_scale,
                entity_count[entity] / clause_denominator,
                role_count[role] / clause_denominator,
                pair_count[entity, role] / clause_denominator,
            )
    if not np.isfinite(rows).all():
        raise ValueError(f"non-finite candidate feature for {task.task_id}")
    return rows


def candidate_features(static: np.ndarray, assignment: list[int]) -> tuple[list[tuple[int, int]], np.ndarray]:
    n, k, width = static.shape
    if width != STATIC_CANDIDATE_DIM or len(assignment) != n:
        raise ValueError("candidate feature/static assignment shape mismatch")
    loads = np.bincount(np.asarray(assignment, dtype=np.int64), minlength=k).astype(np.float32)
    actions = []
    rows = []
    for entity, old_role in enumerate(assignment):
        for new_role in range(k):
            if new_role == old_role:
                continue
            actions.append((entity, new_role))
            rows.append(
                np.concatenate(
                    (static[entity, new_role], np.asarray((loads[old_role] / n, loads[new_role] / n), dtype=np.float32))
                )
            )
    return actions, np.asarray(rows, dtype=np.float32)


def value_features(
    task: FeatureTask,
    assignment: list[int],
    latent_state: list[float],
    remaining_budget: int,
    max_budget: int,
) -> np.ndarray:
    n = len(assignment)
    if len(latent_state) != LATENT_DIM:
        raise ValueError(f"V_reach latent width must be {LATENT_DIM}")
    task_k = int(task.input_row["k"])
    if not 1 <= n <= MAX_ENTITIES or any(role < 0 or role >= task_k for role in assignment):
        raise ValueError("V_reach assignment outside the padded feature shape")
    mean_clause = (
        task.clause_h.mean(axis=0, dtype=np.float64).astype(np.float32)
        if task.clause_h.shape[0]
        else np.zeros(HIDDEN_DIM, dtype=np.float32)
    )
    assignment_onehot = np.zeros((MAX_ENTITIES, MAX_ROLES), dtype=np.float32)
    for entity, role in enumerate(assignment):
        assignment_onehot[entity, role] = 1.0
    budget_value = np.asarray([remaining_budget / max(max_budget, 1)], dtype=np.float32)
    return np.concatenate(
        (
            task.global_h.astype(np.float32, copy=False),
            mean_clause,
            assignment_onehot.reshape(-1),
            np.asarray(latent_state, dtype=np.float32),
            budget_value,
        )
    )
