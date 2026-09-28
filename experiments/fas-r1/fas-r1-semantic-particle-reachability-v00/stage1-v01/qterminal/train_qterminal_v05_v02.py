#!/usr/bin/env python3
"""Fit a validation-frozen V05 Q_terminal selector from filtered train/val artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
from torch import nn

from model_clausewise_v02 import ClausewiseQTerminal


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path(__file__).with_name("manifest-v05-v02.json")
VIEW_RECEIPT_NAME = "trainval-view-receipt-v05-v01.json"
FEATURE_RECEIPT_NAME = "frozen-features-trainval-receipt-v05-v01.json"
CANDIDATE_RECEIPT_NAME = "candidate-receipt-v05-v02.json"
PUBLIC_NAME = "public-tasks-trainval-v05.jsonl"
PRIVATE_NAME = "private-tasks-trainval-v05.jsonl"
SUPPORT_NAME = "stress-support-trainval-v05.json"
FEATURE_NAMES = (
    "constraint_H_trainval.float32.npy",
    "global_h_trainval.float32.npy",
    "rows_trainval.jsonl",
)
LABEL_SOURCE = "independent_typed_validator_v1"
CANDIDATE_SCHEMA = "R1_QTERMINAL_V05_CANDIDATE_V02"


class ContractError(ValueError):
    """An input artifact does not satisfy the V05 selector contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, record: dict[str, Any], name: str) -> None:
    if not path.is_file():
        raise ContractError(f"missing {name}: {path}")
    if path.stat().st_size != int(record.get("bytes", -1)):
        raise ContractError(f"{name} byte count differs from its receipt")
    if sha256_file(path) != str(record.get("sha256", "")).lower():
        raise ContractError(f"{name} hash differs from its receipt")


def verify_pin_match(actual: dict[str, Any], expected: dict[str, Any], name: str) -> None:
    if int(actual.get("bytes", -1)) != int(expected.get("bytes", -2)):
        raise ContractError(f"{name} byte count differs across receipts")
    if str(actual.get("sha256", "")).lower() != str(expected.get("sha256", "")).lower():
        raise ContractError(f"{name} hash differs across receipts")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"expected a JSON object at {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContractError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ContractError(f"expected object at {path}:{line_number}")
            rows.append(row)
    return rows


def verify_inputs(view_dir: Path, feature_dir: Path, candidate_dir: Path, manifest: dict[str, Any]):
    view_path = view_dir / VIEW_RECEIPT_NAME
    view = read_json(view_path)
    if view.get("schema") != "R1_STAGE1_TRAIN_VALIDATION_VIEW_RECEIPT_V05_V01" or view.get("status") != "TRAIN_VALIDATION_VIEW_COMPLETE":
        raise ContractError("V241 view receipt is not a complete V05 train/validation view")
    if view.get("qualification_rows_emitted") != 0 or view.get("qualification_targets_generated") is not False or view.get("qualification_target_paths_or_hashes_recorded") is not False:
        raise ContractError("V241 receipt violates the train/validation-only boundary")
    input_files = {
        PRIVATE_NAME: view_dir / PRIVATE_NAME,
        PUBLIC_NAME: view_dir / PUBLIC_NAME,
        SUPPORT_NAME: view_dir / SUPPORT_NAME,
    }
    for name, path in input_files.items():
        verify_file(path, view["outputs"][name], f"V241 {name}")

    feature_path = feature_dir / FEATURE_RECEIPT_NAME
    feature = read_json(feature_path)
    if feature.get("schema") != "R1_STAGE1_FROZEN_FEATURES_TRAINVAL_V05_V01" or feature.get("status") != "V05_TRAINVAL_FEATURES_COMPLETE":
        raise ContractError("V246 feature receipt is not complete")
    if feature.get("qualification_rows_emitted") != 0 or feature.get("qualification_targets_generated") is not False or feature.get("qualification_target_paths_or_hashes_recorded") is not False:
        raise ContractError("V246 receipt violates the train/validation-only boundary")
    view_hash = sha256_file(view_path)
    if feature.get("view_receipt_sha256") != view_hash:
        raise ContractError("V246 is not bound to the supplied V241 view receipt")
    public_hash = sha256_file(input_files[PUBLIC_NAME])
    if feature.get("trainval_public_tasks_sha256") != public_hash:
        raise ContractError("V246 public-task hash differs from V241")
    feature_files = {}
    for name in FEATURE_NAMES:
        path = feature_dir / name
        verify_file(path, feature["outputs"][name], f"V246 {name}")
        feature_files[name] = path

    candidate_path = candidate_dir / "candidate-records-v05-v02.jsonl"
    candidate_receipt_path = candidate_dir / CANDIDATE_RECEIPT_NAME
    candidate_receipt = read_json(candidate_receipt_path)
    if candidate_receipt.get("schema") != "R1_QTERMINAL_V05_CANDIDATE_RECEIPT_V02" or candidate_receipt.get("status") != "QTERMINAL_V05_CANDIDATES_COMPLETE":
        raise ContractError("V05 candidate receipt is not complete")
    if candidate_receipt.get("view_receipt_sha256") != view_hash:
        raise ContractError("candidate data is not bound to the supplied V241 view")
    if candidate_receipt.get("features_receipt_sha256") != sha256_file(feature_path):
        raise ContractError("candidate receipt is not bound to the supplied V246 features")
    verify_file(candidate_path, candidate_receipt["candidate_file"], "V05 candidate JSONL")
    if candidate_receipt.get("qualification_rows") != 0 or candidate_receipt.get("qualification_targets_generated") is not False or candidate_receipt.get("qualification_target_paths_or_hashes_recorded") is not False:
        raise ContractError("candidate receipt violates the train/validation-only boundary")
    if candidate_receipt.get("validator_agreement_all_candidates") is not True:
        raise ContractError("candidate receipt does not attest dual-validator agreement")
    if candidate_receipt.get("public_private_pair_multiset_match_all_tasks") is not True or candidate_receipt.get("clause_targets_match_validity_all_candidates") is not True:
        raise ContractError("candidate receipt lacks the V02 semantic-alignment checks")
    if candidate_receipt.get("assignments_preserved_from_v01") is not True or candidate_receipt.get("sampler_uniformity_claimed") is not False:
        raise ContractError("candidate receipt has unexpected candidate lineage claims")
    expected_per_class = int(manifest["candidate_sampling"]["requested_per_class_per_task"])
    if candidate_receipt.get("requested_per_class_per_task") != expected_per_class:
        raise ContractError("candidate receipt per-task class count differs from manifest")
    if candidate_receipt.get("candidate_count") != 80 * 2 * expected_per_class or candidate_receipt.get("task_count") != 80:
        raise ContractError("candidate receipt counts differ from the frozen roster/manifest")
    if candidate_receipt.get("task_counts_by_split") != {"train": 64, "validation": 16}:
        raise ContractError("candidate receipt split counts differ from V241")
    support_data = read_json(input_files[SUPPORT_NAME])
    roster_rows = support_data.get("family_roster")
    if not isinstance(roster_rows, list):
        raise ContractError("V241 support manifest lacks its task roster")
    expected_task_counts = {str(row["task_id"]): 2 * expected_per_class for row in roster_rows}
    if candidate_receipt.get("candidate_counts_by_task") != expected_task_counts:
        raise ContractError("candidate receipt per-task counts differ from the V241 roster")
    expected_task_labels = {
        f"{task_id}:valid={label}": expected_per_class
        for task_id in expected_task_counts
        for label in (0, 1)
    }
    if candidate_receipt.get("candidate_counts_by_task_label") != expected_task_labels:
        raise ContractError("candidate receipt per-task class counts differ from the V241 roster")
    for filename, expected in ((PRIVATE_NAME, view["outputs"][PRIVATE_NAME]), (PUBLIC_NAME, view["outputs"][PUBLIC_NAME]), (SUPPORT_NAME, view["outputs"][SUPPORT_NAME])):
        verify_pin_match(candidate_receipt["private_tasks" if filename == PRIVATE_NAME else "public_tasks" if filename == PUBLIC_NAME else "support_manifest"], expected, f"V241 {filename}")
    feature_pin_rows = candidate_receipt.get("feature_files")
    if not isinstance(feature_pin_rows, list) or len(feature_pin_rows) != len(FEATURE_NAMES):
        raise ContractError("candidate receipt feature pins are incomplete")
    candidate_feature_pins = {Path(str(row.get("path", ""))).name: row for row in feature_pin_rows}
    for name in FEATURE_NAMES:
        if name not in candidate_feature_pins:
            raise ContractError(f"candidate receipt omits V246 feature pin {name}")
        verify_pin_match(candidate_feature_pins[name], feature["outputs"][name], f"V246 {name}")
    for key, label in (("source_candidate_receipt", "V01 candidate receipt"), ("source_candidate_file", "V01 candidate rows"), ("generator_source", "V02 generator source"), ("generator_binary", "V02 generator binary")):
        pin = candidate_receipt.get(key)
        if not isinstance(pin, dict) or not pin.get("path"):
            raise ContractError(f"candidate receipt omits {label} pin")
        verify_file(Path(pin["path"]), pin, label)
    return view, feature, candidate_receipt, input_files, feature_files, candidate_path


def _row_hash(array: np.ndarray, row: int) -> str:
    return hashlib.sha256(np.ascontiguousarray(array[row], dtype=np.float32).tobytes()).hexdigest()


def load_feature_bundle(view_dir: Path, feature_dir: Path, view: dict[str, Any], feature_receipt: dict[str, Any]):
    public = read_jsonl(view_dir / PUBLIC_NAME)
    support = read_json(view_dir / SUPPORT_NAME)
    roster_rows = support.get("family_roster")
    if not isinstance(roster_rows, list):
        raise ContractError("V241 support manifest has no family roster")
    roster = {str(row["task_id"]): row for row in roster_rows}
    if len(roster) != len(roster_rows):
        raise ContractError("duplicate task IDs in V241 family roster")
    if len(public) != 80 or len(roster) != 80:
        raise ContractError("V05 selector expects exactly 80 physically filtered tasks")
    for split, count in (("train", 64), ("validation", 16)):
        if sum(row.get("split") == split for row in roster_rows) != count:
            raise ContractError(f"V241 {split} roster count differs from manifest")

    h_path = feature_dir / FEATURE_NAMES[0]
    global_path = feature_dir / FEATURE_NAMES[1]
    rows_path = feature_dir / FEATURE_NAMES[2]
    h_flat = np.load(h_path, mmap_mode="r", allow_pickle=False)
    h_global_flat = np.load(global_path, mmap_mode="r", allow_pickle=False)
    row_map = read_jsonl(rows_path)
    if h_flat.dtype != np.float32 or h_flat.ndim != 2 or h_flat.shape[1] != 2048:
        raise ContractError("V246 constraint array must be float32 [M,2048]")
    if h_global_flat.dtype != np.float32 or h_global_flat.shape != (80, 2048):
        raise ContractError("V246 global array must be float32 [80,2048]")
    if h_flat.shape[0] != 3280 or len(row_map) != 3360:
        raise ContractError("V246 row counts differ from the frozen 80-task view")
    global_rows: dict[str, int] = {}
    global_task_indices: dict[str, int] = {}
    constraint_rows: dict[str, dict[int, int]] = {}
    constraint_task_indices: dict[str, set[int]] = {}
    seen_constraint_rows: set[int] = set()
    seen_global_rows: set[int] = set()
    seen_source_task_indices: set[int] = set()
    for record in row_map:
        task_id = str(record.get("task_id", ""))
        if task_id not in roster:
            raise ContractError("V246 row map contains a task outside V241")
        roster_row = roster[task_id]
        if record.get("split") != roster_row.get("split") or record.get("family_id") != roster_row.get("family_id"):
            raise ContractError("V246 row map split/family differs from V241 roster")
        row = int(record.get("row", -1))
        if record.get("kind") == "global":
            if task_id in global_rows or row < 0 or row >= len(h_global_flat) or row in seen_global_rows:
                raise ContractError("V246 global row map is duplicated or out of bounds")
            source_task_index = int(record.get("task_index", -1))
            if source_task_index < 0 or source_task_index >= 80 or source_task_index in seen_source_task_indices:
                raise ContractError("V246 global task indices are missing, duplicated, or out of bounds")
            if record.get("output_float32_sha256") != _row_hash(h_global_flat, row):
                raise ContractError("V246 global vector row hash mismatch")
            global_rows[task_id] = row
            global_task_indices[task_id] = source_task_index
            seen_source_task_indices.add(source_task_index)
            seen_global_rows.add(row)
        elif record.get("kind") == "constraint":
            clause_index = int(record.get("clause_index", -1))
            if row < 0 or row >= len(h_flat) or row in seen_constraint_rows:
                raise ContractError("V246 constraint row map is duplicated or out of bounds")
            if record.get("output_float32_sha256") != _row_hash(h_flat, row):
                raise ContractError("V246 constraint vector row hash mismatch")
            rows = constraint_rows.setdefault(task_id, {})
            if clause_index in rows:
                raise ContractError("V246 has duplicate task/clause rows")
            rows[clause_index] = row
            constraint_task_indices.setdefault(task_id, set()).add(int(record.get("task_index", -1)))
            seen_constraint_rows.add(row)
        else:
            raise ContractError("V246 row map has an unknown feature kind")
    if len(seen_global_rows) != 80 or len(seen_constraint_rows) != len(h_flat):
        raise ContractError("V246 row map does not cover every frozen feature vector exactly once")
    if seen_source_task_indices != set(range(80)):
        raise ContractError("V246 source task indices do not cover 0..79 exactly")

    max_constraints = max(len(task.get("clauses", [])) for task in public)
    if max_constraints < 1:
        max_constraints = 1
    if max_constraints > 512:
        raise ContractError("V05 task exceeds QTerminal's 512-clause support; refusing truncation")
    features = {
        "feature_ids": [],
        "task_ids": [],
        "family_ids": [],
        "splits": [],
        "scenario_ids": [],
        "n": np.empty(80, dtype=np.int64),
        "k": np.empty(80, dtype=np.int64),
        "h_constraints": np.zeros((80, max_constraints, 2048), dtype=np.float32),
        "constraint_mask": np.zeros((80, max_constraints), dtype=np.bool_),
        "h_global": np.zeros((80, 2048), dtype=np.float32),
        "entity_incidence": np.zeros((80, max_constraints, 20), dtype=np.bool_),
        "role_incidence": np.zeros((80, max_constraints, 6), dtype=np.bool_),
    }
    feature_index: dict[str, int] = {}
    for task_index, task in enumerate(public):
        task_id = str(task["id"])
        roster_row = roster.get(task_id)
        if roster_row is None or roster_row.get("family_id") != task.get("family_id"):
            raise ContractError("V241 public tasks and family roster disagree")
        clauses = task.get("clauses", [])
        mentions = task.get("entity_mentions", [])
        role_mentions = task.get("role_mentions", [])
        if len(clauses) != len(mentions) or len(clauses) != len(role_mentions):
            raise ContractError("public clause text and mention arrays do not align")
        task_rows = constraint_rows.get(task_id, {})
        if set(task_rows) != set(range(len(clauses))):
            raise ContractError(f"V246 does not map every public clause for {task_id}")
        features["feature_ids"].append(task_id)
        features["task_ids"].append(task_id)
        features["family_ids"].append(str(task["family_id"]))
        features["splits"].append(str(roster_row["split"]))
        features["scenario_ids"].append(str(roster_row["scenario_id"]))
        features["n"][task_index] = int(task["n"])
        features["k"][task_index] = int(task["k"])
        if not (1 <= features["n"][task_index] <= 20 and 1 <= features["k"][task_index] <= 6):
            raise ContractError("task shape exceeds frozen QTerminal support")
        global_row = global_rows.get(task_id)
        source_task_index = global_task_indices.get(task_id, -1)
        if global_row is None or source_task_index < 0:
            raise ContractError("V246 global feature row is missing its source task index")
        if source_task_index != task_index:
            raise ContractError("V246 source task index does not match public task enumeration order")
        if constraint_task_indices.get(task_id) != {source_task_index}:
            raise ContractError("V246 global and clause rows disagree on their source task index")
        if source_task_index in {value for key, value in global_task_indices.items() if key != task_id}:
            raise ContractError("V246 source task indices are not unique")
        features["h_global"][task_index] = h_global_flat[global_row]
        for clause_index, row in task_rows.items():
            features["h_constraints"][task_index, clause_index] = h_flat[row]
            features["constraint_mask"][task_index, clause_index] = True
            for entity in mentions[clause_index]:
                entity = int(entity)
                if not 0 <= entity < int(task["n"]):
                    raise ContractError("public entity mention is outside the task shape")
                features["entity_incidence"][task_index, clause_index, entity] = True
            for role in role_mentions[clause_index]:
                role = int(role)
                if not 0 <= role < int(task["k"]):
                    raise ContractError("public role mention is outside the task shape")
                features["role_incidence"][task_index, clause_index, role] = True
        feature_index[task_id] = task_index
    return features, feature_index, public, roster


def load_candidates(candidate_path: Path, feature_index: dict[str, int], roster: dict[str, dict[str, Any]], features, expected_per_class: int):
    rows = read_jsonl(candidate_path)
    if not rows:
        raise ContractError("V05 candidate ledger is empty")
    assignments = np.full((len(rows), 20), 255, dtype=np.uint8)
    labels = np.empty(len(rows), dtype=np.uint8)
    clause_labels = np.zeros((len(rows), features["constraint_mask"].shape[1]), dtype=np.bool_)
    splits: list[str] = []
    task_indices = np.empty(len(rows), dtype=np.int64)
    candidate_ids: set[str] = set()
    unique_assignments: set[tuple[int, bytes]] = set()
    assignment_labels: dict[tuple[int, bytes], int] = {}
    counts: dict[tuple[str, int], int] = {}
    counts_by_task: dict[tuple[str, int], int] = {}
    for index, row in enumerate(rows):
        if row.get("schema") != CANDIDATE_SCHEMA or row.get("label_source") != LABEL_SOURCE:
            raise ContractError("candidate row schema or validator provenance mismatch")
        candidate_id = str(row.get("candidate_id", ""))
        if not candidate_id or candidate_id in candidate_ids:
            raise ContractError("candidate IDs must be nonempty and unique")
        candidate_ids.add(candidate_id)
        task_id = str(row.get("task_id", ""))
        if task_id not in feature_index or task_id not in roster:
            raise ContractError("candidate references a task outside the V241 roster")
        task_row = roster[task_id]
        if row.get("family_id") != task_row.get("family_id") or row.get("split") != task_row.get("split"):
            raise ContractError("candidate family/split disagrees with the V241 roster")
        split = str(row["split"])
        if split not in ("train", "validation"):
            raise ContractError("candidate file contains a non-train/validation row")
        assignment = row.get("assignment")
        if not isinstance(assignment, list) or len(assignment) != 20 or any(type(role) is not int or not 0 <= role < 3 for role in assignment):
            raise ContractError("candidate assignment must contain 20 roles in 0..2")
        label = row.get("posthoc_valid")
        if type(label) is not bool:
            raise ContractError("candidate validity label must be a JSON boolean")
        label_int = int(label)
        encoded = np.asarray(assignment, dtype=np.uint8)
        assignment_labels_key = (feature_index[task_id], encoded.tobytes())
        if assignment_labels_key in unique_assignments:
            raise ContractError("candidate ledger repeats an assignment within a task")
        unique_assignments.add(assignment_labels_key)
        previous = assignment_labels.get(assignment_labels_key)
        if previous is not None and previous != label_int:
            raise ContractError("identical assignment has inconsistent validator labels")
        assignment_labels[assignment_labels_key] = label_int
        assignments[index] = encoded
        labels[index] = label_int
        active_clauses = int(features["constraint_mask"][feature_index[task_id]].sum())
        targets = row.get("clause_satisfied")
        if not isinstance(targets, list) or len(targets) != active_clauses or any(type(value) is not bool for value in targets):
            raise ContractError("clause targets must align with every public clause")
        if all(targets) != bool(label_int):
            raise ContractError("candidate validity label differs from the conjunction of clause targets")
        clause_labels[index, :active_clauses] = np.asarray(targets, dtype=np.bool_)
        splits.append(split)
        task_indices[index] = feature_index[task_id]
        counts[(split, label_int)] = counts.get((split, label_int), 0) + 1
        counts_by_task[(task_id, label_int)] = counts_by_task.get((task_id, label_int), 0) + 1
    if set(splits) != {"train", "validation"}:
        raise ContractError("candidate ledger must contain only train and validation")
    for split in ("train", "validation"):
        if counts.get((split, 0), 0) != counts.get((split, 1), 0) or counts.get((split, 0), 0) == 0:
            raise ContractError(f"{split} candidates are not balanced across validity labels")
    for task_id in roster:
        if counts_by_task.get((task_id, 0), 0) != expected_per_class or counts_by_task.get((task_id, 1), 0) != expected_per_class:
            raise ContractError(f"task {task_id} candidate classes are not balanced")
    if len(rows) != len(roster) * 2 * expected_per_class:
        raise ContractError("candidate count differs from the exact per-task manifest request")
    return assignments, labels, clause_labels, np.asarray(splits), task_indices, rows


def make_batch(features, assignments, task_indices, rows, device):
    feature_rows = task_indices[rows]
    n_values = features["n"][feature_rows]
    k_values = features["k"][feature_rows]
    a = np.zeros((len(rows), 20, 6), dtype=np.float32)
    for batch_index, (n_value, k_value) in enumerate(zip(n_values, k_values, strict=True)):
        roles = assignments[rows[batch_index], :n_value].astype(np.int64)
        if np.any(roles >= k_value):
            raise ContractError("candidate role is outside its task's public role count")
        a[batch_index, np.arange(n_value), roles] = 1.0
    entity_mask = np.arange(20)[None, :] < n_values[:, None]
    role_mask = np.arange(6)[None, :] < k_values[:, None]
    H_np = {
        "constraint_embeddings": features["h_constraints"][feature_rows],
        "constraint_mask": features["constraint_mask"][feature_rows],
        "entity_incidence": features["entity_incidence"][feature_rows],
        "role_incidence": features["role_incidence"][feature_rows],
        "entity_mask": entity_mask,
        "role_mask": role_mask,
    }
    H = {name: torch.as_tensor(value, device=device) for name, value in H_np.items()}
    h_global = torch.as_tensor(features["h_global"][feature_rows], device=device)
    assignment_tensor = torch.as_tensor(a, device=device)
    return H, h_global, assignment_tensor


def score(model, features, assignments, task_indices, rows, device, batch_size):
    output = np.empty(len(rows), dtype=np.float32)
    model.eval()
    with torch.no_grad():
        cursor = 0
        for start in range(0, len(rows), batch_size):
            batch_rows = rows[start : start + batch_size]
            H, h_global, assignment = make_batch(features, assignments, task_indices, batch_rows, device)
            logits = model(H, h_global, assignment).detach().cpu().numpy().astype(np.float32)
            output[cursor : cursor + len(batch_rows)] = logits
            cursor += len(batch_rows)
    return output


def score_clause_logits(model, features, assignments, task_indices, rows, device, batch_size):
    output = np.zeros((len(rows), features["constraint_mask"].shape[1]), dtype=np.float32)
    model.eval()
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            batch_rows = rows[start : start + batch_size]
            H, h_global, assignment = make_batch(features, assignments, task_indices, batch_rows, device)
            _, clause_logits = model.forward_with_clause_logits(H, h_global, assignment)
            output[start : start + len(batch_rows)] = clause_logits.detach().cpu().numpy().astype(np.float32)
    return output


def bce(labels: np.ndarray, logits: np.ndarray) -> float:
    y = labels.astype(np.float64)
    z = logits.astype(np.float64)
    return float(np.mean(np.logaddexp(0.0, z) - y * z))


def sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values.astype(np.float64), -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def choose_temperature(logits: np.ndarray, labels: np.ndarray) -> float:
    candidates = np.logspace(math.log10(0.05), math.log10(20.0), 301)
    best = (float("inf"), 1.0)
    for temperature in candidates:
        loss = bce(labels, logits / temperature)
        if loss < best[0]:
            best = (loss, float(temperature))
    return best[1]


def auc(labels: np.ndarray, scores: np.ndarray) -> float | None:
    positive = labels == 1
    n_pos = int(positive.sum())
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=np.float64)
    sorted_scores = scores[order]
    begin = 0
    while begin < len(order):
        end = begin + 1
        while end < len(order) and sorted_scores[end] == sorted_scores[begin]:
            end += 1
        ranks[order[begin:end]] = (begin + 1 + end) / 2.0
        begin = end
    return float((ranks[positive].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def metrics(labels: np.ndarray, logits: np.ndarray, temperature: float = 1.0) -> dict[str, Any]:
    probability = np.clip(sigmoid(logits / temperature), 1e-7, 1.0 - 1e-7)
    prediction = probability >= 0.5
    positives = labels == 1
    negatives = ~positives
    tpr = float(prediction[positives].mean()) if positives.any() else float("nan")
    tnr = float((~prediction[negatives]).mean()) if negatives.any() else float("nan")
    calibration = 0.0
    for bucket in range(10):
        mask = (probability >= bucket / 10) & ((probability < (bucket + 1) / 10) if bucket < 9 else (probability <= 1))
        if mask.any():
            calibration += float(mask.mean()) * abs(float(labels[mask].mean()) - float(probability[mask].mean()))
    return {
        "count": int(len(labels)),
        "valid_count": int(positives.sum()),
        "invalid_count": int(negatives.sum()),
        "accuracy_at_0_5": float((prediction == positives).mean()),
        "balanced_accuracy": float(np.nanmean([tpr, tnr])),
        "bce": bce(labels, logits / temperature),
        "brier": float(np.mean((probability - labels) ** 2)),
        "roc_auc": auc(labels, probability),
        "ece_10_bins": calibration,
    }


def train(args) -> dict[str, Any]:
    manifest = read_json(args.manifest)
    if manifest.get("schema") != "R1_QTERMINAL_V05_TRAINING_MANIFEST_V02":
        raise ContractError("unexpected Q_terminal V05 manifest schema")
    if args.epochs is not None and not 1 <= args.epochs <= int(manifest["training"]["maximum_epochs"]):
        raise ContractError("--epochs must be in the manifest range")
    if args.batch_size is not None and args.batch_size < 1:
        raise ContractError("--batch-size must be positive")
    if args.output.exists():
        raise ContractError(f"refusing to overwrite existing output directory: {args.output}")

    view, feature_receipt, candidate_receipt, input_files, feature_files, candidate_path = verify_inputs(args.view, args.features, args.candidates, manifest)
    features, feature_index, public_tasks, roster = load_feature_bundle(args.view, args.features, view, feature_receipt)
    expected_per_class = int(manifest["candidate_sampling"]["requested_per_class_per_task"])
    assignments, labels, clause_labels, splits, task_indices, candidate_rows = load_candidates(candidate_path, feature_index, roster, features, expected_per_class)
    train_rows = np.flatnonzero(splits == "train").astype(np.int64)
    validation_rows = np.flatnonzero(splits == "validation").astype(np.int64)
    if not len(train_rows) or not len(validation_rows):
        raise ContractError("V05 Q_terminal requires nonempty train and validation splits")
    if set(np.unique(labels[train_rows]).tolist()) != {0, 1} or set(np.unique(labels[validation_rows]).tolist()) != {0, 1}:
        raise ContractError("train and validation splits must each contain both labels")

    seed = int(manifest["training"]["seed"])
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.set_num_threads(1)
    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available() else "cpu" if args.device == "auto" else args.device)
    hidden_dim = int(features["h_global"].shape[1])
    max_roles = int(features["role_incidence"].shape[2])
    model = ClausewiseQTerminal(hidden_dim=hidden_dim, hidden_size=int(manifest["model"]["hidden_size"]), max_roles=max_roles).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(manifest["training"]["learning_rate"]), weight_decay=float(manifest["training"]["weight_decay"]))
    loss_fn = nn.BCEWithLogitsLoss()
    clause_loss_fn = nn.BCEWithLogitsLoss(reduction="none")
    clause_loss_weight = float(manifest["model"]["clause_loss_weight"])
    requested_batch = int(args.batch_size or manifest["training"]["batch_size"])
    element_limit = int(manifest["compute"]["max_clause_feature_elements_per_batch"])
    per_row = max(1, int(features["h_constraints"].shape[1]) * hidden_dim)
    batch_size = max(1, min(requested_batch, element_limit // per_row))
    max_epochs = int(args.epochs or manifest["training"]["maximum_epochs"])
    patience = int(manifest["training"]["early_stopping_patience"])
    best_loss = float("inf")
    best_epoch = 0
    best_state = None
    stale = 0
    history = []
    rng = np.random.default_rng(seed)

    for epoch in range(1, max_epochs + 1):
        model.train()
        order = rng.permutation(train_rows)
        assignment_loss_total = 0.0
        clause_loss_total = 0.0
        clause_targets_seen = 0
        seen = 0
        for start in range(0, len(order), batch_size):
            rows = order[start : start + batch_size]
            H, h_global, assignment = make_batch(features, assignments, task_indices, rows, device)
            y = torch.as_tensor(labels[rows].astype(np.float32), device=device)
            clause_y = torch.as_tensor(clause_labels[rows].astype(np.float32), device=device)
            optimizer.zero_grad(set_to_none=True)
            logits, clause_logits = model.forward_with_clause_logits(H, h_global, assignment)
            assignment_loss = loss_fn(logits, y)
            active = H["constraint_mask"].to(dtype=clause_logits.dtype)
            clause_loss_values = clause_loss_fn(clause_logits, clause_y)
            clause_loss = (clause_loss_values * active).sum() / active.sum().clamp_min(1.0)
            loss = assignment_loss + clause_loss_weight * clause_loss
            loss.backward()
            optimizer.step()
            active_count = int(active.sum().item())
            assignment_loss_total += float(assignment_loss.detach()) * len(rows)
            clause_loss_total += float(clause_loss.detach()) * active_count
            clause_targets_seen += active_count
            seen += len(rows)
        validation_logits = score(model, features, assignments, task_indices, validation_rows, device, batch_size)
        validation_loss = bce(labels[validation_rows], validation_logits)
        history.append({
            "epoch": epoch,
            "train_assignment_bce": assignment_loss_total / max(seen, 1),
            "train_clause_bce": clause_loss_total / max(clause_targets_seen, 1),
            "validation_assignment_bce": validation_loss,
        })
        if validation_loss < best_loss:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = {key: tensor.detach().cpu().clone() for key, tensor in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
        if stale >= patience:
            break

    if best_state is None:
        raise ContractError("Q_terminal training produced no validation checkpoint")
    model.load_state_dict(best_state)
    model.to(device)
    validation_logits = score(model, features, assignments, task_indices, validation_rows, device, batch_size)
    validation_clause_logits = score_clause_logits(model, features, assignments, task_indices, validation_rows, device, batch_size)
    temperature = choose_temperature(validation_logits, labels[validation_rows])
    validation_metrics_raw = metrics(labels[validation_rows], validation_logits)
    validation_metrics_calibrated = metrics(labels[validation_rows], validation_logits, temperature)
    validation_mask = features["constraint_mask"][task_indices[validation_rows]]
    clause_eval_labels = clause_labels[validation_rows][validation_mask].astype(np.uint8)
    clause_eval_logits = validation_clause_logits[validation_mask]
    validation_clause_metrics = metrics(clause_eval_labels, clause_eval_logits)

    args.output.mkdir(parents=True)
    checkpoint_path = args.output / "qterminal-v05-v02.pt"
    torch.save({
        "schema": manifest["model"]["checkpoint_schema"],
        "model_config": {"architecture": "ClausewiseQTerminal", "hidden_dim": hidden_dim, "hidden_size": int(manifest["model"]["hidden_size"]), "max_roles": max_roles, "clause_loss_weight": clause_loss_weight},
        "state_dict": best_state,
        "temperature": temperature,
        "best_epoch": best_epoch,
        "manifest_sha256": sha256_file(args.manifest),
        "v241_view_receipt_sha256": sha256_file(args.view / VIEW_RECEIPT_NAME),
        "v246_feature_receipt_sha256": sha256_file(args.features / FEATURE_RECEIPT_NAME),
    }, checkpoint_path)
    score_path = args.output / "validation-scores-v05-v02.jsonl"
    with score_path.open("w", encoding="utf-8", newline="\n") as stream:
        for local_index, row_index in enumerate(validation_rows):
            row = candidate_rows[int(row_index)]
            record = {
                "candidate_id": row["candidate_id"],
                "task_id": row["task_id"],
                "scenario_id": roster[row["task_id"]]["scenario_id"],
                "posthoc_valid": bool(labels[row_index]),
                "logit": float(validation_logits[local_index]),
                "probability": float(sigmoid(np.asarray([validation_logits[local_index] / temperature]))[0]),
            }
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    grouped = {}
    val_scenarios = np.asarray([roster[candidate_rows[int(index)]["task_id"]]["scenario_id"] for index in validation_rows])
    for scenario in sorted(set(val_scenarios.tolist())):
        mask = val_scenarios == scenario
        grouped[scenario] = metrics(labels[validation_rows][mask], validation_logits[mask], temperature)
    receipt = {
        "schema": "R1_QTERMINAL_V05_FIT_RECEIPT_V02",
        "status": "QTERMINAL_V05_FITTED_VALIDATION_FROZEN",
        "fit_role": "common terminal selector for V05 engineering search arms",
        "engineering_iteration": True,
        "scientific_confirmation": False,
        "frozen_lfm_training_performed": False,
        "frozen_lfm_contact_performed": False,
        "qterminal_training_performed": True,
        "selector_architecture": "ClausewiseQTerminal",
        "clause_level_supervision": True,
        "clause_loss_weight": clause_loss_weight,
        "conjunction_aggregation": manifest["model"]["conjunction_aggregation"],
        "test_labels_read": False,
        "qualification_labels_read": False,
        "qualification_rows": 0,
        "qualification_targets_generated": False,
        "qualification_target_paths_or_hashes_recorded": False,
        "split_counts": {"train": int(len(train_rows)), "validation": int(len(validation_rows)), "test": 0, "qualification": 0},
        "candidate_label_counts": {
            split: {"valid": int(np.sum(labels[np.flatnonzero(splits == split)] == 1)), "invalid": int(np.sum(labels[np.flatnonzero(splits == split)] == 0))}
            for split in ("train", "validation")
        },
        "feature_counts": {"tasks": 80, "constraints": int(features["constraint_mask"].sum()), "max_constraints_per_task": int(features["constraint_mask"].sum(axis=1).max())},
        "source_pins": {
            "v241_view_receipt_sha256": sha256_file(args.view / VIEW_RECEIPT_NAME),
            "v241_public_tasks_sha256": sha256_file(input_files[PUBLIC_NAME]),
            "v241_private_tasks_sha256": sha256_file(input_files[PRIVATE_NAME]),
            "v241_support_sha256": sha256_file(input_files[SUPPORT_NAME]),
            "v246_features_receipt_sha256": sha256_file(args.features / FEATURE_RECEIPT_NAME),
            "v05_candidate_receipt_sha256": sha256_file(args.candidates / CANDIDATE_RECEIPT_NAME),
            "candidate_file_sha256": sha256_file(candidate_path),
            "manifest_sha256": sha256_file(args.manifest),
            "trainer_source_sha256": sha256_file(Path(__file__)),
            "model_source_sha256": sha256_file(Path(__file__).with_name("model_clausewise_v02.py")),
        },
        "device": str(device),
        "effective_batch_size": batch_size,
        "epochs_completed": len(history),
        "best_epoch": best_epoch,
        "best_validation_bce_uncalibrated": best_loss,
        "validation_temperature": temperature,
        "validation_metrics_uncalibrated": validation_metrics_raw,
        "validation_metrics_calibrated_on_same_validation_split": validation_metrics_calibrated,
        "validation_clause_metrics_uncalibrated": validation_clause_metrics,
        "validation_metrics_by_scenario_calibrated": grouped,
        "training_history": history,
        "checkpoint": {"path": str(checkpoint_path.resolve()), "bytes": checkpoint_path.stat().st_size, "sha256": sha256_file(checkpoint_path)},
        "validation_scores": {"path": str(score_path.resolve()), "bytes": score_path.stat().st_size, "sha256": sha256_file(score_path)},
        "interpretation": "Validation metrics are engineering diagnostics only: checkpoint selection and temperature calibration both use this same train/validation roster; no independent evaluation was performed.",
    }
    (args.output / "fit-receipt-v05-v02.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", type=Path, required=True, help="V241 train/validation view")
    parser.add_argument("--features", type=Path, required=True, help="V246 frozen train/validation features")
    parser.add_argument("--candidates", type=Path, required=True, help="V05 train/validation typed-validator candidates")
    parser.add_argument("--output", type=Path, required=True, help="new fit output directory")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--device", default="auto", help="auto, cpu, or explicit torch device")
    args = parser.parse_args()
    try:
        receipt = train(args)
    except (ContractError, OSError, ValueError, RuntimeError) as exc:
        print(f"QTERMINAL_V05_FIT_FAILED: {exc}")
        return 1
    print(receipt["status"])
    print(f"best epoch={receipt['best_epoch']} val BCE={receipt['best_validation_bce_uncalibrated']:.6f} temperature={receipt['validation_temperature']:.4f}")
    print(f"validation balanced accuracy={receipt['validation_metrics_calibrated_on_same_validation_split']['balanced_accuracy']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
