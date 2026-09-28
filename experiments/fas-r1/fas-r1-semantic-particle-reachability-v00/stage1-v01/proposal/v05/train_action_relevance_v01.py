#!/usr/bin/env python3
"""Fit a V05 train/validation-only exact action-consequence probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

N_ENTITIES = 20
N_ROLES = 3
ACTION_COUNT = N_ENTITIES * (N_ROLES - 1)
HIDDEN = 2048
STATE_INDICES = (0, 4, 8, 12, 16, 20, 24, 28)
COMMON_DIM = N_ENTITIES * N_ROLES + N_ENTITIES * N_ROLES * N_ROLES + N_ENTITIES + N_ROLES + 3
FEATURE_DIM = COMMON_DIM + HIDDEN * 3
LABEL_TO_ID = {-1: 0, 0: 1, 1: 2}
LABEL_NAMES = {0: "worsens", 1: "neutral", 2: "improves"}


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def file_record(path: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    return {"path": str(path.resolve()), "sha256": digest, "bytes": size}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def feature_record(path: Path, receipt: dict[str, Any]) -> None:
    expected = receipt.get("outputs", {}).get(path.name, {})
    observed = file_record(path)
    if observed["sha256"] != expected.get("sha256") or observed["bytes"] != expected.get("bytes"):
        raise ValueError(f"V05 train/validation feature hash mismatch for {path.name}")


def receipt_output_record(receipt: dict[str, Any], name: str) -> dict[str, Any]:
    record = receipt.get("outputs", {}).get(name)
    if not isinstance(record, dict) or not record.get("sha256") or not isinstance(record.get("bytes"), int):
        raise ValueError(f"V05 receipt has no complete output record for {name}")
    return record


def verify_recorded_file(path: Path, record: dict[str, Any], description: str) -> None:
    observed = file_record(path)
    if observed["sha256"] != record["sha256"] or observed["bytes"] != record["bytes"]:
        raise ValueError(f"V05 {description} hash/size differs from its receipt")


def _task_features(
    task: dict[str, Any], global_h: np.ndarray, clause_h: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[list[int]], list[list[int]], np.ndarray]:
    mentions = task["entity_mentions"]
    role_mentions = task["role_mentions"]
    if len(mentions) != len(role_mentions) or len(mentions) != len(task["clauses"]):
        raise ValueError(f"public incidence shape mismatch for {task['id']}")
    h = np.asarray(clause_h, dtype=np.float32)
    if h.shape != (len(mentions), HIDDEN):
        raise ValueError(f"frozen constraint feature shape mismatch for {task['id']}")
    all_mean = (h.mean(axis=0, dtype=np.float64).astype(np.float32)
                if len(h) else np.zeros(HIDDEN, dtype=np.float32))
    by_entity = np.zeros((N_ENTITIES, HIDDEN), dtype=np.float32)
    for entity in range(N_ENTITIES):
        rows = [index for index, values in enumerate(mentions) if entity in values]
        if rows:
            by_entity[entity] = h[np.asarray(rows, dtype=np.int64)].mean(axis=0, dtype=np.float64).astype(np.float32)
    return np.asarray(global_h, dtype=np.float32), all_mean, mentions, role_mentions, by_entity


def action_feature(
    task: dict[str, Any], cached: tuple[np.ndarray, np.ndarray, list[list[int]], list[list[int]], np.ndarray],
    label: dict[str, Any],
) -> np.ndarray:
    global_h, all_mean, mentions, roles, by_entity = cached
    assignment = label["assignment"]
    edit = label["edit"]
    entity, old_role, new_role = int(edit["entity"]), int(edit["from_role"]), int(edit["to_role"])
    if (len(assignment) != N_ENTITIES or task["n"] != N_ENTITIES or task["k"] != N_ROLES
            or any(not 0 <= int(role) < N_ROLES for role in assignment)):
        raise ValueError("V05 action probe contract requires N=20 and K=3")
    if (not 0 <= entity < N_ENTITIES or not 0 <= old_role < N_ROLES
            or not 0 <= new_role < N_ROLES or assignment[entity] != old_role or new_role == old_role):
        raise ValueError("action row does not describe a legal state edit")
    affected = [index for index, entity_ids in enumerate(mentions) if entity in entity_ids]
    entity_counts = np.zeros(N_ENTITIES, dtype=np.float32)
    role_counts = np.zeros(N_ROLES, dtype=np.float32)
    for clause_index in affected:
        for mentioned in mentions[clause_index]:
            entity_counts[int(mentioned)] += 1.0
        for role in roles[clause_index]:
            role_counts[int(role)] += 1.0
    assignment_onehot = np.zeros(N_ENTITIES * N_ROLES, dtype=np.float32)
    for index, role in enumerate(assignment):
        assignment_onehot[index * N_ROLES + int(role)] = 1.0
    edit_onehot = np.zeros(N_ENTITIES * N_ROLES * N_ROLES, dtype=np.float32)
    edit_onehot[(entity * N_ROLES + old_role) * N_ROLES + new_role] = 1.0
    common = np.concatenate((
        assignment_onehot,
        edit_onehot,
        entity_counts / max(1, len(mentions)),
        role_counts / max(1, len(affected)),
        np.asarray((task["n"] / N_ENTITIES, task["k"] / N_ROLES,
                    len(affected) / max(1, len(mentions))), dtype=np.float32),
    ))
    result = np.concatenate((common, global_h, all_mean, by_entity[entity])).astype(np.float32, copy=False)
    if result.shape != (FEATURE_DIM,) or not np.isfinite(result).all():
        raise ValueError("V05 action probe feature shape or finite-value check failed")
    return result


def action_features_for_state(
    task: dict[str, Any], cached: tuple[np.ndarray, np.ndarray, list[list[int]], list[list[int]], np.ndarray],
    assignment: list[int],
) -> tuple[list[tuple[int, int]], np.ndarray]:
    """Build every legal action row while calculating each entity's public context once."""
    global_h, all_mean, mentions, roles, by_entity = cached
    if (len(assignment) != N_ENTITIES or task["n"] != N_ENTITIES or task["k"] != N_ROLES
            or any(not 0 <= int(role) < N_ROLES for role in assignment)):
        raise ValueError("V05 action feature batch requires a valid N=20, K=3 assignment")
    assignment_onehot = np.zeros(N_ENTITIES * N_ROLES, dtype=np.float32)
    for entity, role in enumerate(assignment):
        assignment_onehot[entity * N_ROLES + int(role)] = 1.0
    actions: list[tuple[int, int]] = []
    features = np.empty((ACTION_COUNT, FEATURE_DIM), dtype=np.float32)
    row_index = 0
    for entity, old_role in enumerate(assignment):
        affected = [index for index, entity_ids in enumerate(mentions) if entity in entity_ids]
        entity_counts = np.zeros(N_ENTITIES, dtype=np.float32)
        role_counts = np.zeros(N_ROLES, dtype=np.float32)
        for clause_index in affected:
            for mentioned in mentions[clause_index]:
                entity_counts[int(mentioned)] += 1.0
            for role in roles[clause_index]:
                role_counts[int(role)] += 1.0
        common = np.concatenate((
            assignment_onehot,
            entity_counts / max(1, len(mentions)),
            role_counts / max(1, len(affected)),
            np.asarray((task["n"] / N_ENTITIES, task["k"] / N_ROLES,
                        len(affected) / max(1, len(mentions))), dtype=np.float32),
        ))
        for new_role in range(N_ROLES):
            if new_role == old_role:
                continue
            actions.append((entity, new_role))
            edit_onehot = np.zeros(N_ENTITIES * N_ROLES * N_ROLES, dtype=np.float32)
            edit_onehot[(entity * N_ROLES + int(old_role)) * N_ROLES + new_role] = 1.0
            features[row_index] = np.concatenate((
                common[:N_ENTITIES * N_ROLES],
                edit_onehot,
                common[N_ENTITIES * N_ROLES:],
                global_h,
                all_mean,
                by_entity[entity],
            ))
            row_index += 1
    if row_index != ACTION_COUNT or not np.isfinite(features).all():
        raise ValueError("V05 action feature batch shape/value validation failed")
    return actions, features


def macro_f1(truth: np.ndarray, prediction: np.ndarray, class_count: int = 3) -> float:
    scores = []
    for label in range(class_count):
        tp = int(np.sum((truth == label) & (prediction == label)))
        fp = int(np.sum((truth != label) & (prediction == label)))
        fn = int(np.sum((truth == label) & (prediction != label)))
        denominator = 2 * tp + fp + fn
        scores.append(2 * tp / denominator if denominator else 0.0)
    return float(np.mean(scores))


def exact_delta_label(row: dict[str, Any]) -> int:
    delta = int(row["sign_delta"])
    if delta not in LABEL_TO_ID:
        raise ValueError(f"invalid action consequence label {delta}")
    exact_delta = int(row["satisfied_after"]) - int(row["satisfied_before"])
    if exact_delta != int(row["delta_satisfied"]) or (exact_delta > 0) - (exact_delta < 0) != delta:
        raise ValueError("V05 action consequence fields disagree")
    return delta


def _normalization(matrix: np.memmap, indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    total = np.zeros(FEATURE_DIM, dtype=np.float64)
    square = np.zeros(FEATURE_DIM, dtype=np.float64)
    for start in range(0, len(indices), 256):
        batch = np.asarray(matrix[indices[start:start + 256]], dtype=np.float64)
        total += batch.sum(axis=0)
        square += np.square(batch).sum(axis=0)
    mean = total / len(indices)
    variance = np.maximum(square / len(indices) - mean * mean, 0.0)
    std = np.sqrt(variance)
    std[std < 1e-6] = 1.0
    return mean.astype(np.float32), std.astype(np.float32)


def _fit(matrix: np.memmap, labels: np.ndarray, train: np.ndarray, validation: np.ndarray,
         *, seed: int, epochs: int, device_name: str, output: Path) -> dict[str, Any]:
    import torch
    from torch import nn

    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)
    device = torch.device(device_name)
    mean, std = _normalization(matrix, train)
    train_y = labels[train]
    frequencies = np.bincount(train_y, minlength=3).astype(np.float64)
    if np.any(frequencies == 0):
        raise ValueError(f"V05 training split omits an action consequence class: {frequencies.tolist()}")
    weights = len(train_y) / (3.0 * frequencies)
    class_weights = torch.as_tensor(weights, dtype=torch.float32, device=device)
    model = nn.Sequential(nn.Linear(FEATURE_DIM, 128), nn.ReLU(), nn.Linear(128, 3)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    best_state = None
    best_score = -1.0
    best_epoch = 0
    stale = 0
    history = []

    def logits_for(indices: np.ndarray) -> np.ndarray:
        values = []
        model.eval()
        with torch.no_grad():
            for start in range(0, len(indices), 512):
                index = indices[start:start + 512]
                features = np.asarray(matrix[index], dtype=np.float32)
                features = (features - mean) / std
                tensor = torch.as_tensor(features, dtype=torch.float32, device=device)
                values.append(model(tensor).cpu().numpy())
        return np.concatenate(values, axis=0)

    for epoch in range(1, epochs + 1):
        model.train()
        order = torch.randperm(len(train), generator=generator).numpy()
        for start in range(0, len(order), 512):
            batch_indices = train[order[start:start + 512]]
            features = np.asarray(matrix[batch_indices], dtype=np.float32)
            features = (features - mean) / std
            x = torch.as_tensor(features, dtype=torch.float32, device=device)
            y = torch.as_tensor(labels[batch_indices].astype(np.int64, copy=False), device=device)
            optimizer.zero_grad(set_to_none=True)
            loss = nn.functional.cross_entropy(model(x), y, weight=class_weights)
            loss.backward()
            optimizer.step()
        val_logits = logits_for(validation)
        val_prediction = np.argmax(val_logits, axis=1)
        score = macro_f1(labels[validation], val_prediction)
        history.append({"epoch": epoch, "validation_macro_f1": score})
        if score > best_score + 1e-8:
            best_score = score
            best_epoch = epoch
            best_state = {name: tensor.detach().cpu().clone() for name, tensor in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= 10:
                break
    if best_state is None:
        raise RuntimeError("V05 action relevance fit did not select a checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    validation_logits = logits_for(validation)
    validation_prediction = np.argmax(validation_logits, axis=1)
    validation_truth = labels[validation]
    class_metrics = {}
    for label_id, name in LABEL_NAMES.items():
        selected = validation_truth == label_id
        class_metrics[name] = {
            "support": int(selected.sum()),
            "recall": float(np.mean(validation_prediction[selected] == label_id)) if selected.any() else 0.0,
        }
    weights_path = output / "action-relevance-v05.pt"
    torch.save({
        "state_dict": model.cpu().state_dict(),
        "normalization_mean": mean,
        "normalization_std": std,
        "feature_dim": FEATURE_DIM,
        "label_order": [LABEL_NAMES[i] for i in range(3)],
    }, weights_path)
    np.savez_compressed(output / "validation-predictions-v05.npz",
                        logits=validation_logits.astype(np.float32),
                        truth=validation_truth.astype(np.int8),
                        prediction=validation_prediction.astype(np.int8))
    return {
        "architecture": "linear-6410-to-128-ReLU-to-3",
        "feature_dim": FEATURE_DIM,
        "label_order": [LABEL_NAMES[i] for i in range(3)],
        "class_weighting": {LABEL_NAMES[i]: float(weights[i]) for i in range(3)},
        "selected_epoch": best_epoch,
        "epochs_run": len(history),
        "early_stop_patience": 10,
        "selection_metric": "validation macro F1",
        "validation_macro_f1": float(best_score),
        "validation_accuracy": float(np.mean(validation_prediction == validation_truth)),
        "validation_class_metrics": class_metrics,
        "validation_support": len(validation),
        "device": str(device),
        "history": history,
        "weights_sha256": sha256_file(weights_path)[0],
        "validation_predictions_sha256": sha256_file(output / "validation-predictions-v05.npz")[0],
    }


def train(view_dir: Path, feature_dir: Path, label_dir: Path, output_dir: Path,
          *, seed: int, epochs: int, device: str) -> dict[str, Any]:
    view = view_dir.resolve(strict=True)
    feature_root = feature_dir.resolve(strict=True)
    labels_root = label_dir.resolve(strict=True)
    output = output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite V05 action probe run {output}")
    view_receipt_path = view / "trainval-view-receipt-v05-v01.json"
    view_receipt = json.loads(view_receipt_path.read_text(encoding="utf-8"))
    feature_receipt_path = feature_root / "frozen-features-trainval-receipt-v05-v01.json"
    feature_receipt = json.loads(feature_receipt_path.read_text(encoding="utf-8"))
    label_receipt_path = labels_root / "action-label-receipt-v05-v01.json"
    label_receipt = json.loads(label_receipt_path.read_text(encoding="utf-8"))
    view_hash = sha256_file(view_receipt_path)[0]
    if view_receipt.get("schema") != "R1_STAGE1_TRAIN_VALIDATION_VIEW_RECEIPT_V05_V01" or view_receipt.get("status") != "TRAIN_VALIDATION_VIEW_COMPLETE":
        raise ValueError("V05 task view receipt identity/status mismatch")
    if feature_receipt.get("schema") != "R1_STAGE1_FROZEN_FEATURES_TRAINVAL_V05_V01" or feature_receipt.get("status") != "V05_TRAINVAL_FEATURES_COMPLETE":
        raise ValueError("V05 frozen feature receipt identity/status mismatch")
    if label_receipt.get("schema") != "R1_STAGE1_V05_ACTION_LABEL_RECEIPT_V01" or label_receipt.get("status") != "V05_TRAINVAL_ACTION_LABELS_COMPLETE":
        raise ValueError("V05 action label receipt identity/status mismatch")
    if (view_receipt.get("qualification_rows_emitted") != 0
            or feature_receipt.get("qualification_rows_emitted") != 0
            or label_receipt.get("qualification_rows") != 0):
        raise ValueError("V05 train inputs contain qualification rows")
    if (view_receipt.get("qualification_targets_generated") is not False
            or feature_receipt.get("qualification_targets_generated") is not False
            or label_receipt.get("qualification_targets_generated") is not False
            or view_receipt.get("qualification_target_paths_or_hashes_recorded") is not False
            or feature_receipt.get("qualification_target_paths_or_hashes_recorded") is not False
            or label_receipt.get("qualification_target_paths_or_hashes_recorded") is not False):
        raise ValueError("V05 action labels are not train/validation-only")

    public_path = view / "public-tasks-trainval-v05.jsonl"
    support_path = view / "stress-support-trainval-v05.json"
    verify_recorded_file(public_path, receipt_output_record(view_receipt, public_path.name), "public train/validation task roster")
    verify_recorded_file(support_path, receipt_output_record(view_receipt, support_path.name), "train/validation support map")
    if feature_receipt.get("view_receipt_sha256") != view_hash or label_receipt.get("view_receipt_sha256") != view_hash:
        raise ValueError("V05 feature/action-label receipts do not bind to the supplied task view")
    if feature_receipt.get("trainval_public_tasks_sha256") != sha256_file(public_path)[0]:
        raise ValueError("V05 frozen features were sliced against a different public task roster")
    if label_receipt.get("view_source_support_manifest_sha256") != view_receipt.get("source_support_manifest_sha256"):
        raise ValueError("V05 action labels were derived from a different support manifest")
    public_tasks = read_jsonl(public_path)
    support = json.loads(support_path.read_text(encoding="utf-8"))
    split_by_task = {row["task_id"]: row["split"] for row in support["family_roster"]}
    if len(public_tasks) != 80 or set(split_by_task) != {row["id"] for row in public_tasks}:
        raise ValueError("V05 train/validation public task roster mismatch")
    public_by_id = {row["id"]: row for row in public_tasks}

    features_path = feature_root / "constraint_H_trainval.float32.npy"
    global_path = feature_root / "global_h_trainval.float32.npy"
    rows_path = feature_root / "rows_trainval.jsonl"
    for path in (features_path, global_path, rows_path):
        feature_record(path, feature_receipt)
    h = np.load(features_path, mmap_mode="r", allow_pickle=False)
    global_h = np.load(global_path, mmap_mode="r", allow_pickle=False)
    if h.dtype != np.dtype("<f4") or global_h.dtype != np.dtype("<f4"):
        raise ValueError("V05 train/validation feature arrays must be little-endian float32")
    if (feature_receipt.get("model_revision") != "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
            or feature_receipt.get("feature_shape", {}).get("global") != [80, HIDDEN]
            or feature_receipt.get("feature_shape", {}).get("constraints") != [sum(len(row["clauses"]) for row in public_tasks), HIDDEN]
            or global_h.shape != (80, HIDDEN)
            or h.shape != (sum(len(row["clauses"]) for row in public_tasks), HIDDEN)):
        raise ValueError("V05 frozen feature dimensions or model revision differ from the task view")
    feature_rows = read_jsonl(rows_path)
    global_index: dict[str, int] = {}
    clause_index: dict[str, dict[int, int]] = defaultdict(dict)
    seen_global_rows: set[int] = set()
    seen_constraint_rows: set[int] = set()
    for row in feature_rows:
        task_id = row["task_id"]
        if task_id not in public_by_id or row.get("split") != split_by_task[task_id]:
            raise ValueError("filtered V05 feature row has unknown task or split mismatch")
        feature_row = int(row["row"])
        if row["kind"] == "global":
            if task_id in global_index or feature_row in seen_global_rows or not 0 <= feature_row < len(global_h):
                raise ValueError("duplicate or out-of-range V05 global feature row")
            seen_global_rows.add(feature_row)
            global_index[task_id] = feature_row
        elif row["kind"] == "constraint":
            clause_id = int(row["clause_index"])
            if clause_id in clause_index[task_id] or feature_row in seen_constraint_rows or not 0 <= feature_row < len(h):
                raise ValueError("duplicate or out-of-range V05 constraint feature row")
            seen_constraint_rows.add(feature_row)
            clause_index[task_id][clause_id] = feature_row
        else:
            raise ValueError(f"unknown V05 frozen feature row kind {row['kind']!r}")
    if seen_global_rows != set(range(len(global_h))) or seen_constraint_rows != set(range(len(h))):
        raise ValueError("filtered V05 feature rows do not form a dense complete row map")

    cached: dict[str, Any] = {}
    for task_id, task in public_by_id.items():
        if task_id not in global_index or set(clause_index[task_id]) != set(range(len(task["clauses"]))):
            raise ValueError(f"incomplete V05 feature rows for {task_id}")
        rows = [clause_index[task_id][i] for i in range(len(task["clauses"]))]
        cached[task_id] = _task_features(task, global_h[global_index[task_id]], h[np.asarray(rows, dtype=np.int64)])

    action_path = labels_root / "private-action-relevance-labels-v05-v01.jsonl"
    verify_recorded_file(action_path, label_receipt.get("action_labels", {}), "action label file")
    selected_states = set(STATE_INDICES)
    selected_by_task: Counter[str] = Counter()
    selected_by_state: dict[tuple[str, int], set[tuple[int, int]]] = defaultdict(set)
    assignment_by_state: dict[tuple[str, int], tuple[int, ...]] = {}
    split_counts: Counter[str] = Counter()
    output.mkdir(parents=True)
    matrix_path = output / "action-features-trainval.f32.mmap"
    expected_rows = 80 * len(STATE_INDICES) * N_ENTITIES * (N_ROLES - 1)
    matrix = np.memmap(matrix_path, dtype="<f4", mode="w+", shape=(expected_rows, FEATURE_DIM))
    labels = np.empty(expected_rows, dtype=np.int8)
    metadata: list[dict[str, Any]] = []
    row_index = 0
    with action_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("schema") != "r1-v05-action-relevance-label-v01":
                raise ValueError(f"unsupported V05 action row at line {line_number}")
            task_id = row["task_id"]
            if task_id not in public_by_id or row["family_split"] != split_by_task[task_id]:
                raise ValueError("V05 action label has unknown task or split mismatch")
            state_index = int(row["state_index"])
            if state_index not in selected_states:
                continue
            assignment_key = tuple(int(role) for role in row["assignment"])
            state_key = (task_id, state_index)
            previous_assignment = assignment_by_state.setdefault(state_key, assignment_key)
            if previous_assignment != assignment_key:
                raise ValueError(f"V05 action rows disagree on assignment for {task_id} state {state_index}")
            edit_entity = int(row["edit"]["entity"])
            edit_role = int(row["edit"]["to_role"])
            action_key = (edit_entity, edit_role)
            if action_key in selected_by_state[state_key]:
                raise ValueError(f"duplicate V05 action row for {task_id} state {state_index} edit {action_key}")
            selected_by_state[state_key].add(action_key)
            try:
                delta = exact_delta_label(row)
            except ValueError as error:
                raise ValueError(f"{error} for {task_id} state {state_index}") from error
            matrix[row_index] = action_feature(public_by_id[task_id], cached[task_id], row)
            labels[row_index] = LABEL_TO_ID[delta]
            metadata.append({
                "task_id": task_id,
                "family_id": row["family_id"],
                "family_split": row["family_split"],
                "state_index": state_index,
                "edit": row["edit"],
                "delta_satisfied": row["delta_satisfied"],
                "sign_delta": delta,
            })
            selected_by_task[task_id] += 1
            split_counts[row["family_split"]] += 1
            row_index += 1
    matrix.flush()
    if row_index != expected_rows or len(metadata) != expected_rows:
        raise ValueError(f"selected V05 action row count {row_index} != {expected_rows}")
    if any(count != len(STATE_INDICES) * 40 for count in selected_by_task.values()) or len(selected_by_task) != 80:
        raise ValueError("selected V05 action labels do not cover 8 states × 40 actions per task")
    if len(selected_by_state) != 80 * len(STATE_INDICES):
        raise ValueError("selected V05 action labels do not cover every sampled task/state")
    for (task_id, state_index), observed_actions in selected_by_state.items():
        assignment = assignment_by_state[(task_id, state_index)]
        expected_actions = {
            (entity, role)
            for entity, old_role in enumerate(assignment)
            for role in range(N_ROLES)
            if role != old_role
        }
        if observed_actions != expected_actions:
            raise ValueError(f"selected V05 action set is incomplete for {task_id} state {state_index}")
    expected_split_counts = {"train": 64 * len(STATE_INDICES) * 40,
                             "validation": 16 * len(STATE_INDICES) * 40}
    if dict(split_counts) != expected_split_counts:
        raise ValueError(f"selected V05 train/validation action counts differ: {dict(split_counts)}")
    train_indices = np.asarray([i for i, row in enumerate(metadata) if row["family_split"] == "train"], dtype=np.int64)
    val_indices = np.asarray([i for i, row in enumerate(metadata) if row["family_split"] == "validation"], dtype=np.int64)
    train_label_counts = np.bincount(labels[train_indices], minlength=3)
    validation_label_counts = np.bincount(labels[val_indices], minlength=3)
    if np.any(train_label_counts == 0):
        raise ValueError(f"V05 training split omits an action consequence class: {train_label_counts.tolist()}")
    fit = _fit(matrix, labels, train_indices, val_indices, seed=seed, epochs=epochs,
               device_name=device, output=output)
    prediction_path = output / "validation-predictions-v05.npz"
    # Bind predictions back to the selected validation examples without copying labels into a model input.
    with (output / "validation-row-map-v05.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for index in val_indices:
            stream.write(json.dumps(metadata[int(index)], sort_keys=True, separators=(",", ":")) + "\n")
    receipt = {
        "schema": "R1_STAGE1_V05_ACTION_RELEVANCE_FIT_V01",
        "status": "V05_TRAINVAL_ACTION_RELEVANCE_FIT_COMPLETE",
        "fit_scope": "exact sign of one-step satisfied-constraint delta; validation-selected three-class head",
        "qualification_rows": 0,
        "qualification_targets_generated": False,
        "qualification_target_paths_or_hashes_recorded": False,
        "split_usage": {"train": "fit and normalization", "validation": "checkpoint selection only"},
        "input_hashes": {
            "view_receipt": file_record(view_receipt_path),
            "public_trainval_tasks": file_record(public_path),
            "trainval_support": file_record(view / "stress-support-trainval-v05.json"),
            "frozen_feature_receipt": file_record(feature_receipt_path),
            "teacher_action_label_receipt": file_record(label_receipt_path),
            "action_labels": file_record(action_path),
            "global_features": file_record(global_path),
            "constraint_features": file_record(features_path),
            "feature_row_map": file_record(rows_path),
            "fit_source": file_record(Path(__file__)),
        },
        "contract": {
            "task_shape": {"n": N_ENTITIES, "k": N_ROLES},
            "feature_schema": "V05 assignment/edit/public incidence + h_global + mean(H) + mean(H incident to edited entity)",
            "feature_dim": FEATURE_DIM,
            "states_per_task": len(STATE_INDICES),
            "state_indices": list(STATE_INDICES),
            "action_rows": row_index,
            "split_counts": {"train": expected_split_counts["train"], "validation": expected_split_counts["validation"]},
            "label_counts": {
                "train": {LABEL_NAMES[i]: int(train_label_counts[i]) for i in range(3)},
                "validation": {LABEL_NAMES[i]: int(validation_label_counts[i]) for i in range(3)},
            },
            "teacher_q_used_as_feature_or_label": False,
        },
        "fit": fit,
        "run_config": {"seed": seed, "epoch_limit": epochs, "requested_device": device},
        "validation_row_map": file_record(output / "validation-row-map-v05.jsonl"),
        "training_matrix": file_record(matrix_path),
        "validation_predictions": file_record(prediction_path),
        "analysis_mode": "adaptive engineering; validation used to select checkpoint",
    }
    receipt_path = output / "action-relevance-fit-receipt-v05-v01.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view-dir", type=Path, required=True)
    parser.add_argument("--feature-dir", type=Path, required=True)
    parser.add_argument("--label-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=71026)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--device", default="cuda" if __import__("torch").cuda.is_available() else "cpu")
    args = parser.parse_args()
    output = args.output.resolve()
    output_existed = output.exists()
    try:
        receipt = train(args.view_dir, args.feature_dir, args.label_dir, output,
                        seed=args.seed, epochs=args.epochs, device=args.device)
    except Exception as error:
        receipt_path = output / "action-relevance-fit-receipt-v05-v01.json"
        failure_path = output / "failure.json"
        if not output_existed and output.is_dir() and not receipt_path.exists() and not failure_path.exists():
            failure = {
                "schema": "R1_STAGE1_ATTEMPT_FAILURE_V01",
                "status": "V05_ACTION_RELEVANCE_FIT_FAILED",
                "phase": "trainval_action_relevance_fit",
                "error_type": type(error).__name__,
                "error": str(error),
                "source": file_record(Path(__file__)),
            }
            failure_path.write_text(json.dumps(failure, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise
    print(f"R1_V05_ACTION_RELEVANCE_FIT_COMPLETE val_macro_f1={receipt['fit']['validation_macro_f1']:.4f} output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
