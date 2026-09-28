#!/usr/bin/env python3
"""Measure whether V05 clausewise Q scores recover train/validation edit effects."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"expected JSON object at {path}:{number}")
                rows.append(row)
    return rows


def verify_file(path: Path, record: dict[str, Any], name: str) -> None:
    if not path.is_file() or path.stat().st_size != int(record.get("bytes", -1)):
        raise ValueError(f"missing or wrong-sized {name}: {path}")
    if sha256_file(path) != str(record.get("sha256", "")).lower():
        raise ValueError(f"{name} hash differs from receipt")


def task_feature_index(public_tasks: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    tasks = {str(task["id"]): task for task in public_tasks}
    if len(tasks) != len(public_tasks) or len(tasks) != 80:
        raise ValueError("expected 80 unique V05 train/validation public tasks")
    result: dict[str, dict[str, Any]] = {}
    for task_id, task in tasks.items():
        clauses: dict[int, int] = {}
        global_row = None
        for row in rows:
            if str(row["task_id"]) != task_id:
                continue
            if row["kind"] == "global":
                if global_row is not None:
                    raise ValueError(f"duplicate global feature row for {task_id}")
                global_row = int(row["row"])
            elif row["kind"] == "constraint":
                clause_index = int(row["clause_index"])
                if clause_index in clauses:
                    raise ValueError(f"duplicate clause feature row for {task_id}/{clause_index}")
                clauses[clause_index] = int(row["row"])
            else:
                raise ValueError(f"unknown feature row kind: {row['kind']}")
        if global_row is None or set(clauses) != set(range(len(task["clauses"]))):
            raise ValueError(f"incomplete public feature rows for {task_id}")
        result[task_id] = {"task": task, "global_row": global_row, "clause_rows": clauses}
    return result


def validate_action_labels(
    action_rows: list[dict[str, Any]], split_by_task: dict[str, str], task_by_id: dict[str, dict[str, Any]],
) -> dict[str, dict[int, list[dict[str, Any]]]]:
    indexed: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(dict)
    for row in action_rows:
        task_id = str(row.get("task_id", ""))
        task = task_by_id.get(task_id)
        split = str(row.get("family_split", ""))
        state_index = row.get("state_index")
        if (task is None or split not in ("train", "validation") or split_by_task.get(task_id) != split
                or row.get("schema") != "r1-v05-action-relevance-label-v01"):
            raise ValueError("V244 contains an unknown task, non-train/validation row, or schema mismatch")
        if type(state_index) is not int or not 0 <= state_index < 32:
            raise ValueError(f"invalid state index for {task_id}")
        assignment = row.get("assignment")
        if (not isinstance(assignment, list) or len(assignment) != 20
                or any(type(role) is not int or not 0 <= role < 3 for role in assignment)):
            raise ValueError(f"invalid assignment for {task_id}/{state_index}")
        edit = row.get("edit", {})
        entity, old_role, new_role = edit.get("entity"), edit.get("from_role"), edit.get("to_role")
        if (type(entity) is not int or not 0 <= entity < 20 or type(old_role) is not int
                or type(new_role) is not int or assignment[entity] != old_role
                or not 0 <= new_role < 3 or new_role == old_role):
            raise ValueError(f"invalid edit row for {task_id}/{state_index}")
        delta = int(row["satisfied_after"]) - int(row["satisfied_before"])
        if delta != int(row["delta_satisfied"]) or (delta > 0) - (delta < 0) != int(row["sign_delta"]):
            raise ValueError(f"inconsistent action consequence fields for {task_id}/{state_index}")
        state_rows = indexed[task_id].setdefault(state_index, [])
        state_rows.append(row)

    if len(indexed) != 80:
        raise ValueError("V244 action labels do not cover the 80-task train/validation roster")
    for task_id, task in task_by_id.items():
        states = indexed.get(task_id, {})
        if set(states) != set(range(32)):
            raise ValueError(f"V244 state roster incomplete for {task_id}")
        for state_index, rows in states.items():
            if len(rows) != 40:
                raise ValueError(f"V244 action count mismatch for {task_id}/{state_index}")
            rows.sort(key=lambda row: (int(row["edit"]["entity"]), int(row["edit"]["to_role"])))
            assignment = rows[0]["assignment"]
            expected = [(entity, new_role) for entity, old_role in enumerate(assignment)
                        for new_role in range(3) if new_role != old_role]
            observed = [(int(row["edit"]["entity"]), int(row["edit"]["to_role"])) for row in rows]
            if observed != expected or any(row["assignment"] != assignment for row in rows):
                raise ValueError(f"V244 actions do not form the complete ordered edit set for {task_id}/{state_index}")
    return indexed


def build_model_inputs(task: dict[str, Any], info: dict[str, Any], clause_h: np.ndarray,
                       global_h: np.ndarray, device):
    import torch

    h = np.asarray(clause_h[[info["clause_rows"][i] for i in range(len(task["clauses"]))]], dtype=np.float32)
    gh = np.asarray(global_h[info["global_row"]].copy(), dtype=np.float32)
    clause_count = len(task["clauses"])
    entity_incidence = np.zeros((clause_count, 20), dtype=np.float32)
    role_incidence = np.zeros((clause_count, 6), dtype=np.float32)
    for index, mentioned in enumerate(task["entity_mentions"]):
        if len(mentioned) != 2 or len(set(mentioned)) != 2:
            raise ValueError(f"V05 clause incidence must identify two entities for {task['id']}")
        entity_incidence[index, np.asarray(mentioned, dtype=np.int64)] = 1.0
    for index, mentioned in enumerate(task["role_mentions"]):
        if mentioned:
            role_incidence[index, np.asarray(mentioned, dtype=np.int64)] = 1.0
    base = {
        "constraint_embeddings": torch.as_tensor(h, device=device).unsqueeze(0),
        "constraint_mask": torch.ones((1, clause_count), dtype=torch.bool, device=device),
        "entity_incidence": torch.as_tensor(entity_incidence, device=device).unsqueeze(0),
        "role_incidence": torch.as_tensor(role_incidence, device=device).unsqueeze(0),
        "entity_mask": torch.ones((1, 20), dtype=torch.bool, device=device),
        "role_mask": torch.tensor([[True, True, True, False, False, False]], device=device),
    }
    return base, torch.as_tensor(gh, device=device).unsqueeze(0)


def assignment_batch(assignments: np.ndarray, device):
    import torch

    batch = len(assignments)
    result = np.zeros((batch, 20, 6), dtype=np.float32)
    result[np.arange(batch)[:, None], np.arange(20)[None, :], assignments] = 1.0
    return torch.as_tensor(result, device=device)


def score_assignments(model, base_h, global_h, assignments: np.ndarray, device,
                      batch_size: int) -> tuple[np.ndarray, int, int]:
    import torch

    scores = np.empty(len(assignments), dtype=np.float32)
    batches = 0
    started = time.perf_counter_ns()
    with torch.inference_mode():
        for start in range(0, len(assignments), batch_size):
            subset = assignments[start:start + batch_size]
            batch = len(subset)
            h = {name: value.expand(batch, *value.shape[1:]) for name, value in base_h.items()}
            gh = global_h.expand(batch, -1)
            a = assignment_batch(subset, device)
            _, clause_logits = model.forward_with_clause_logits(h, gh, a)
            probabilities = torch.sigmoid(clause_logits.float()) * h["constraint_mask"].float()
            scores[start:start + batch] = probabilities.sum(dim=1).cpu().numpy()
            batches += 1
    return scores, batches, time.perf_counter_ns() - started


def softmax_cross_entropy(q: np.ndarray, scores: np.ndarray, beta: float) -> float:
    logits = scores.astype(np.float64) * beta
    maximum = logits.max(axis=1, keepdims=True)
    log_partition = maximum[:, 0] + np.log(np.exp(logits - maximum).sum(axis=1))
    log_probabilities = logits - log_partition[:, None]
    return float(-(q * log_probabilities).sum(axis=1).mean())


def fit_beta(q: np.ndarray, scores: np.ndarray) -> tuple[float, float]:
    positive = q.sum(axis=1) > 0.0
    if not positive.any():
        raise ValueError("train roster has no positive-mass teacher states")
    q = q[positive]
    scores = scores[positive]
    grid = np.geomspace(1e-3, 1e3, 601)
    losses = np.asarray([softmax_cross_entropy(q, scores, float(beta)) for beta in grid])
    index = int(np.argmin(losses))
    return float(grid[index]), float(losses[index])


def macro_f1(truth: np.ndarray, prediction: np.ndarray) -> float:
    values = []
    for label in (-1, 0, 1):
        tp = int(np.sum((truth == label) & (prediction == label)))
        fp = int(np.sum((truth != label) & (prediction == label)))
        fn = int(np.sum((truth == label) & (prediction != label)))
        denominator = 2 * tp + fp + fn
        values.append(2 * tp / denominator if denominator else 0.0)
    return float(np.mean(values))


def evaluate_split(rows_by_task, delta_by_key: dict[tuple[str, int, int, int], float],
                   split_by_task: dict[str, str], split: str, beta: float) -> dict[str, Any]:
    true_delta = []
    predicted_delta = []
    true_sign = []
    predicted_sign = []
    q_rows = []
    score_rows = []
    teacher_argmax_mass = []
    teacher_top_mass = []
    teacher_entropy = []
    positive_mass_states = 0
    total_states = 0
    row_map = []
    for task_id in sorted(rows_by_task):
        if split_by_task[task_id] != split:
            continue
        for state_index in sorted(rows_by_task[task_id]):
            rows = rows_by_task[task_id][state_index]
            q = np.asarray([float(row["teacher_q_probability"]) for row in rows], dtype=np.float64)
            scores = np.asarray([delta_by_key[(task_id, state_index, int(row["edit"]["entity"]), int(row["edit"]["to_role"]))]
                                 for row in rows], dtype=np.float64)
            truth_delta = np.asarray([float(row["delta_satisfied"]) for row in rows], dtype=np.float64)
            predicted = np.where(scores > 0.5, 1, np.where(scores < -0.5, -1, 0))
            true_delta.extend(truth_delta.tolist())
            predicted_delta.extend(scores.tolist())
            true_sign.extend(np.sign(truth_delta).astype(np.int8).tolist())
            predicted_sign.extend(predicted.astype(np.int8).tolist())
            if q.sum() > 0.0:
                positive_mass_states += 1
                p = np.exp(beta * scores - np.max(beta * scores))
                p /= p.sum()
                q_rows.append(q / q.sum())
                score_rows.append(scores)
                teacher_argmax_mass.append(float((q / q.sum())[int(np.argmax(scores))]))
                teacher_top_mass.append(float(np.max(q / q.sum())))
                q_norm = q / q.sum()
                teacher_entropy.append(float(-np.sum(q_norm[q_norm > 0] * np.log(q_norm[q_norm > 0]))))
                row_map.append({"task_id": task_id, "state_index": state_index,
                                "teacher_q": q.tolist(), "predicted_delta_satisfied": scores.tolist(),
                                "predicted_proposal": p.tolist()})
            total_states += 1
    y = np.asarray(true_sign, dtype=np.int8)
    p = np.asarray(predicted_sign, dtype=np.int8)
    dtrue = np.asarray(true_delta, dtype=np.float64)
    dpred = np.asarray(predicted_delta, dtype=np.float64)
    if len(dtrue) == 0:
        raise ValueError(f"no action labels for split {split}")
    positive = np.asarray(q_rows, dtype=np.float64)
    proposal_scores = np.asarray(score_rows, dtype=np.float64)
    teacher_ce = softmax_cross_entropy(positive, proposal_scores, beta) if len(positive) else None
    uniform_ce = float(np.mean(-np.sum(positive * math.log(1.0 / 40.0), axis=1))) if len(positive) else None
    return {
        "split": split,
        "states": total_states,
        "positive_teacher_mass_states": positive_mass_states,
        "zero_mass_teacher_states": total_states - positive_mass_states,
        "action_rows": len(dtrue),
        "action_sign_accuracy": float(np.mean(y == p)),
        "action_sign_macro_f1": macro_f1(y, p),
        "delta_satisfied_mae": float(np.mean(np.abs(dtrue - dpred))),
        "delta_satisfied_rmse": float(np.sqrt(np.mean(np.square(dtrue - dpred)))),
        "teacher_mean_entropy_nats": float(np.mean(teacher_entropy)) if teacher_entropy else None,
        "teacher_mean_top_action_mass": float(np.mean(teacher_top_mass)) if teacher_top_mass else None,
        "q_mass_at_qterminal_delta_argmax": float(np.mean(teacher_argmax_mass)) if teacher_argmax_mass else None,
        "proposal_teacher_cross_entropy_nats": teacher_ce,
        "uniform_teacher_cross_entropy_nats": uniform_ce,
        "predictions": row_map,
    }


def run(args) -> dict[str, Any]:
    import torch

    qterminal_root = Path(__file__).resolve().parents[2] / "qterminal"
    sys.path.insert(0, str(qterminal_root))
    from model_clausewise_v02 import ClausewiseQTerminal

    fit_receipt = read_json(args.fit_receipt)
    if fit_receipt.get("schema") != "R1_QTERMINAL_V05_FIT_RECEIPT_V02" or fit_receipt.get("status") != "QTERMINAL_V05_FITTED_VALIDATION_FROZEN":
        raise ValueError("supplied Q-terminal fit is not a frozen V02 checkpoint")
    if fit_receipt.get("test_labels_read") is not False or fit_receipt.get("qualification_labels_read") is not False:
        raise ValueError("Q-terminal receipt does not preserve its train/validation-only boundary")
    model_source = Path(__file__).resolve().parents[2] / "qterminal" / "model_clausewise_v02.py"
    if fit_receipt.get("source_pins", {}).get("model_source_sha256") != sha256_file(model_source):
        raise ValueError("V02 model source differs from the fitted checkpoint receipt")
    verify_file(args.checkpoint, fit_receipt["checkpoint"], "Q-terminal checkpoint")

    view_receipt = read_json(args.view_receipt)
    feature_receipt = read_json(args.features_receipt)
    label_receipt = read_json(args.label_receipt)
    if view_receipt.get("status") != "TRAIN_VALIDATION_VIEW_COMPLETE" or view_receipt.get("qualification_rows_emitted") != 0:
        raise ValueError("V241 is not a train/validation-only task view")
    if feature_receipt.get("status") != "V05_TRAINVAL_FEATURES_COMPLETE" or feature_receipt.get("qualification_rows_emitted") != 0:
        raise ValueError("V246 is not a train/validation-only feature view")
    if label_receipt.get("status") != "V05_TRAINVAL_ACTION_LABELS_COMPLETE" or label_receipt.get("qualification_rows") != 0:
        raise ValueError("V244 is not a train/validation-only action label set")
    if any(receipt.get("qualification_targets_generated") is not False
           or receipt.get("qualification_target_paths_or_hashes_recorded") is not False
           for receipt in (view_receipt, feature_receipt, label_receipt)):
        raise ValueError("an input receipt declares qualification-target generation or access")
    if (feature_receipt.get("view_receipt_sha256") != sha256_file(args.view_receipt)
            or label_receipt.get("view_receipt_sha256") != sha256_file(args.view_receipt)
            or feature_receipt.get("model_revision") != "7453bca97ca1e67754c4035a4b4c584e1c9dd725"):
        raise ValueError("V241/V244/V246 lineage mismatch")
    if label_receipt.get("view_source_support_manifest_sha256") != view_receipt.get("source_support_manifest_sha256"):
        raise ValueError("V244 action labels use another task support manifest")

    public_path = args.view_dir / "public-tasks-trainval-v05.jsonl"
    support_path = args.view_dir / "stress-support-trainval-v05.json"
    public_pin = view_receipt.get("outputs", {}).get(public_path.name, {})
    support_pin = view_receipt.get("outputs", {}).get(support_path.name, {})
    verify_file(public_path, public_pin, "V241 public tasks")
    verify_file(support_path, support_pin, "V241 support roster")
    if feature_receipt.get("trainval_public_tasks_sha256") != sha256_file(public_path):
        raise ValueError("V246 feature slice was built from different public tasks")
    support = read_json(support_path)
    split_by_task = {str(row["task_id"]): str(row["split"]) for row in support.get("family_roster", [])}
    if len(split_by_task) != 80 or set(split_by_task.values()) != {"train", "validation"}:
        raise ValueError("V241 support roster is not the expected 80-task train/validation roster")

    h_path = args.features_dir / "constraint_H_trainval.float32.npy"
    gh_path = args.features_dir / "global_h_trainval.float32.npy"
    rows_path = args.features_dir / "rows_trainval.jsonl"
    for path in (h_path, gh_path, rows_path):
        verify_file(path, feature_receipt.get("outputs", {}).get(path.name, {}), path.name)
    label_path = args.label_dir / str(label_receipt["action_labels"]["file"])
    verify_file(label_path, label_receipt["action_labels"], "V244 action labels")
    if label_receipt["summary"].get("action_rows") != 102400:
        raise ValueError("V244 action label count differs from the expected 80x32x40 design")

    public_tasks = read_jsonl(public_path)
    feature_rows = read_jsonl(rows_path)
    feature_index = task_feature_index(public_tasks, feature_rows)
    task_by_id = {str(row["id"]): row for row in public_tasks}
    action_rows = read_jsonl(label_path)
    rows_by_task = validate_action_labels(action_rows, split_by_task, task_by_id)

    clause_h = np.load(h_path, mmap_mode="r", allow_pickle=False)
    global_h = np.load(gh_path, mmap_mode="r", allow_pickle=False)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    if checkpoint.get("schema") != "R1_QTERMINAL_CHECKPOINT_V05_V02":
        raise ValueError("checkpoint schema mismatch")
    config = checkpoint["model_config"]
    model = ClausewiseQTerminal(hidden_dim=int(config["hidden_dim"]), hidden_size=int(config["hidden_size"]), max_roles=int(config["max_roles"]))
    model.load_state_dict(checkpoint["state_dict"])
    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available() else "cpu" if args.device == "auto" else args.device)
    model.to(device).eval()

    delta_by_key: dict[tuple[str, int, int, int], float] = {}
    inference_ns = 0
    batch_count = 0
    for task_id in sorted(task_by_id):
        task = task_by_id[task_id]
        base_h, base_global = build_model_inputs(task, feature_index[task_id], clause_h, global_h, device)
        assignments_by_state = np.empty((32, 41, 20), dtype=np.int64)
        for state_index in range(32):
            state_rows = rows_by_task[task_id][state_index]
            assignment = np.asarray(state_rows[0]["assignment"], dtype=np.int64)
            after_assignments = np.repeat(assignment[None, :], 40, axis=0)
            for index, row in enumerate(state_rows):
                after_assignments[index, int(row["edit"]["entity"])] = int(row["edit"]["to_role"])
            assignments_by_state[state_index, 0] = assignment
            assignments_by_state[state_index, 1:] = after_assignments
        counts, batches, elapsed = score_assignments(
            model, base_h, base_global, assignments_by_state.reshape(-1, 20), device, args.batch_size
        )
        counts = counts.reshape(32, 41)
        inference_ns += elapsed
        batch_count += batches
        for state_index in range(32):
            state_rows = rows_by_task[task_id][state_index]
            before = float(counts[state_index, 0])
            for row, after_count in zip(state_rows, counts[state_index, 1:], strict=True):
                key = (task_id, state_index, int(row["edit"]["entity"]), int(row["edit"]["to_role"]))
                delta_by_key[key] = float(after_count) - before

    by_split = {}
    beta, train_ce = None, None
    train_rows = rows_by_task
    train_true, train_scores = [], []
    for task_id, states in train_rows.items():
        if split_by_task[task_id] != "train":
            continue
        for state_index, state_actions in states.items():
            q = np.asarray([float(row["teacher_q_probability"]) for row in state_actions], dtype=np.float64)
            if q.sum() <= 0:
                continue
            scores = np.asarray([delta_by_key[(task_id, state_index, int(row["edit"]["entity"]), int(row["edit"]["to_role"]))]
                                 for row in state_actions], dtype=np.float64)
            train_true.append(q / q.sum())
            train_scores.append(scores)
    if train_true:
        beta, train_ce = fit_beta(np.asarray(train_true), np.asarray(train_scores))
    for split in ("train", "validation"):
        by_split[split] = evaluate_split(rows_by_task, delta_by_key, split_by_task, split, beta or 1.0)
    for record in by_split.values():
        record.pop("predictions")

    prediction_rows = []
    for split in ("train", "validation"):
        for task_id in sorted(rows_by_task):
            if split_by_task[task_id] != split:
                continue
            for state_index in sorted(rows_by_task[task_id]):
                rows = rows_by_task[task_id][state_index]
                q = np.asarray([float(row["teacher_q_probability"]) for row in rows], dtype=np.float64)
                scores = np.asarray([delta_by_key[(task_id, state_index, int(row["edit"]["entity"]), int(row["edit"]["to_role"]))]
                                     for row in rows], dtype=np.float64)
                logits = beta * scores
                probs = np.exp(logits - np.max(logits))
                probs /= probs.sum()
                prediction_rows.append({
                    "task_id": task_id, "family_split": split, "state_index": state_index,
                    "teacher_q": q.tolist(), "predicted_delta_satisfied": scores.tolist(),
                    "qterminal_delta_proposal": probs.tolist(),
                })

    output = {
        "schema": "R1_V05_QTERMINAL_ACTION_DELTA_DIAGNOSTIC_V01",
        "status": "TRAIN_VALIDATION_ACTION_DELTA_DIAGNOSTIC_COMPLETE",
        "analysis_mode": "adaptive engineering; train and validation metrics; beta selected on train positive-mass states only",
        "inputs": {
            "view_receipt_sha256": sha256_file(args.view_receipt),
            "features_receipt_sha256": sha256_file(args.features_receipt),
            "action_label_receipt_sha256": sha256_file(args.label_receipt),
            "qterminal_fit_receipt_sha256": sha256_file(args.fit_receipt),
            "qterminal_checkpoint_sha256": sha256_file(args.checkpoint),
        },
        "source_sha256": sha256_file(Path(__file__)),
        "device": str(device),
        "batch_size": args.batch_size,
        "forward_batches": batch_count,
        "inference_wall_ns": inference_ns,
        "proposal_temperature_inverse_beta": beta,
        "train_proposal_teacher_cross_entropy_nats": train_ce,
        "metrics_by_split": by_split,
        "qualification_labels_read": False,
        "qualification_target_paths_or_hashes_recorded": False,
        "predictions": prediction_rows,
    }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view-dir", type=Path, required=True)
    parser.add_argument("--view-receipt", type=Path, required=True)
    parser.add_argument("--features-dir", type=Path, required=True)
    parser.add_argument("--features-receipt", type=Path, required=True)
    parser.add_argument("--label-dir", type=Path, required=True)
    parser.add_argument("--label-receipt", type=Path, required=True)
    parser.add_argument("--fit-receipt", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    if args.batch_size < 1 or args.output.exists():
        raise SystemExit("batch size must be positive and output directory must be new")
    result = run(args)
    args.output.mkdir(parents=True)
    predictions = args.output / "action-delta-predictions-trainval-v01.jsonl"
    with predictions.open("x", encoding="utf-8", newline="\n") as stream:
        for row in result.pop("predictions"):
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        stream.flush()
    receipt_path = args.output / "action-delta-diagnostic-receipt-v01.json"
    result["outputs"] = {predictions.name: {"path": str(predictions.resolve()), "bytes": predictions.stat().st_size,
                                           "sha256": sha256_file(predictions)}}
    result["status"] = "TRAIN_VALIDATION_ACTION_DELTA_DIAGNOSTIC_COMPLETE"
    receipt_path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{result['status']}: val action F1={result['metrics_by_split']['validation']['action_sign_macro_f1']:.4f} "
          f"teacher CE={result['metrics_by_split']['validation']['proposal_teacher_cross_entropy_nats']:.4f} "
          f"uniform={result['metrics_by_split']['validation']['uniform_teacher_cross_entropy_nats']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
