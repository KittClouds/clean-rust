#!/usr/bin/env python3
"""Fit a V05 train/validation-only policy to class-balanced teacher distributions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import feature_math as FM  # noqa: E402


N_ENTITIES = 20
N_ROLES = 3
STATE_COUNT = 32
ACTION_COUNT = N_ENTITIES * (N_ROLES - 1)
MODEL_REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
TARGET_SCHEMA = "r1-class-balanced-one-step-teacher-v01"


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


def verify_recorded_file(path: Path, record: dict[str, Any], description: str) -> None:
    observed = file_record(path)
    if observed["sha256"] != record.get("sha256") or observed["bytes"] != record.get("bytes"):
        raise ValueError(f"V05 {description} hash/size differs from its receipt")


def receipt_output(receipt: dict[str, Any], name: str) -> dict[str, Any]:
    record = receipt.get("outputs", {}).get(name)
    if not isinstance(record, dict) or not record.get("sha256") or not isinstance(record.get("bytes"), int):
        raise ValueError(f"V05 receipt has no complete output record for {name}")
    return record


def validate_target_row(
    teacher: dict[str, Any], task: dict[str, Any], split: str, expected_actions: list[tuple[int, int]],
) -> tuple[np.ndarray, np.ndarray]:
    target = teacher.get("target", {})
    task_id = task["id"]
    if (teacher.get("schema") != "r1-proposal-teacher-sample-v01"
            or target.get("schema") != TARGET_SCHEMA
            or teacher.get("task_id") != task_id
            or teacher.get("family_id") != task["family_id"]
            or teacher.get("family_split") != split):
        raise ValueError(f"V05 teacher identity/split mismatch for {task_id}")
    edits = target.get("edits")
    if not isinstance(edits, list) or len(edits) != len(expected_actions):
        raise ValueError(f"V05 teacher action count mismatch for {task_id}")
    teacher_actions = [(int(row["entity"]), int(row["new_role"])) for row in edits]
    if teacher_actions != expected_actions:
        raise ValueError(f"V05 teacher action order/schema differs from runtime features for {task_id}")
    q = np.asarray([float(row["q_probability"]) for row in edits], dtype=np.float32)
    broadness = np.asarray([float(row["g_fraction"]) for row in edits], dtype=np.float32)
    if (not np.isfinite(q).all() or np.any(q < 0) or not np.isfinite(broadness).all()
            or np.any((broadness < 0) | (broadness > 1))):
        raise ValueError(f"non-finite/out-of-range V05 teacher mass for {task_id}")
    q_sum = float(q.sum(dtype=np.float64))
    outcome = target.get("outcome")
    if outcome == "positive_mass":
        if not np.isclose(q_sum, 1.0, rtol=0.0, atol=1e-6):
            raise ValueError(f"positive V05 teacher distribution sums to {q_sum} for {task_id}")
        q /= q_sum
    elif outcome == "zero_mass":
        if q_sum > 1e-8:
            raise ValueError(f"zero-mass V05 teacher state has nonzero mass for {task_id}")
        raise ValueError("V05 proposal fitting requires positive-mass teacher states")
    else:
        raise ValueError(f"unknown V05 teacher outcome {outcome!r}")
    return q, broadness


def _prediction_metrics(q: np.ndarray, logits: np.ndarray, task_ids: list[str], broadness: np.ndarray) -> dict[str, Any]:
    shifted = logits.astype(np.float64) - logits.max(axis=1, keepdims=True).astype(np.float64)
    log_probs = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
    probs = np.exp(log_probs)
    state_loss = -(q.astype(np.float64) * log_probs).sum(axis=1)
    per_task: dict[str, list[float]] = defaultdict(list)
    for task_id, loss in zip(task_ids, state_loss, strict=True):
        per_task[task_id].append(float(loss))
    top = np.argmax(probs, axis=1)
    rows = np.arange(len(q))
    positive_support = q > 0
    uniform_support_rate = positive_support.mean(axis=1)
    return {
        "task_macro_cross_entropy": float(np.mean([np.mean(values) for values in per_task.values()])),
        "state_mean_cross_entropy": float(state_loss.mean()),
        "uniform_cross_entropy": float(np.log(q.shape[1])),
        "mean_teacher_mass_at_top_action": float(q[rows, top].mean()),
        "top_action_positive_teacher_mass_rate": float(positive_support[rows, top].mean()),
        "mean_teacher_class_fraction_at_top_action": float(broadness[rows, top].mean()),
        "mean_uniform_positive_support_rate": float(uniform_support_rate.mean()),
        "validation_task_count": len(per_task),
    }


def _fit(
    features: np.ndarray, targets: np.ndarray, task_ids: list[str], train: np.ndarray, validation: np.ndarray,
    broadness: np.ndarray, *, seed: int, epochs: int, device_name: str, output: Path,
) -> dict[str, Any]:
    import torch
    from torch import nn

    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)
    device = torch.device(device_name)
    model = nn.Sequential(nn.Linear(10, 16), nn.Tanh(), nn.Linear(16, 1)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    best_state = None
    best_score = float("inf")
    best_epoch = 0
    stale = 0
    history: list[dict[str, Any]] = []

    def predict(indices: np.ndarray) -> np.ndarray:
        model.eval()
        results = []
        with torch.no_grad():
            for start in range(0, len(indices), 64):
                selected = indices[start:start + 64]
                x = torch.as_tensor(features[selected], dtype=torch.float32, device=device)
                results.append(model(x).squeeze(-1).cpu().numpy())
        return np.concatenate(results, axis=0)

    for epoch in range(1, epochs + 1):
        model.train()
        order = torch.randperm(len(train), generator=generator).numpy()
        for start in range(0, len(order), 64):
            batch = train[order[start:start + 64]]
            x = torch.as_tensor(features[batch], dtype=torch.float32, device=device)
            q = torch.as_tensor(targets[batch], dtype=torch.float32, device=device)
            logits = model(x).squeeze(-1)
            loss = -(q * torch.log_softmax(logits, dim=-1)).sum(dim=-1).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        val_logits = predict(validation)
        metrics = _prediction_metrics(targets[validation], val_logits, [task_ids[i] for i in validation], broadness[validation])
        history.append({"epoch": epoch, "validation": metrics})
        score = metrics["task_macro_cross_entropy"]
        if score < best_score - 1e-8:
            best_score = score
            best_epoch = epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= 10:
                break
    if best_state is None:
        raise RuntimeError("V05 proposal fit did not select a checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    val_logits = predict(validation)
    final_metrics = _prediction_metrics(
        targets[validation], val_logits, [task_ids[i] for i in validation], broadness[validation]
    )
    torch.save({
        "architecture": "tanh_mlp_base_f10_h16_v05",
        "input_dim": 10,
        "hidden_dim": 16,
        "state_dict": model.cpu().state_dict(),
        "label_semantics": TARGET_SCHEMA,
    }, output / "proposal-v05.pt")
    np.savez_compressed(
        output / "validation-predictions-v05.npz",
        logits=val_logits.astype(np.float32),
        probabilities=np.exp(val_logits - np.logaddexp.reduce(val_logits, axis=1, keepdims=True)).astype(np.float32),
        teacher_q=targets[validation],
        teacher_class_fraction=broadness[validation],
    )
    return {
        "architecture": "tanh_mlp_base_f10_h16_v05",
        "optimizer": "AdamW",
        "learning_rate": 1e-3,
        "weight_decay": 1e-4,
        "batch_size_states": 64,
        "selected_epoch": best_epoch,
        "epochs_run": len(history),
        "early_stop_patience": 10,
        "selection_metric": "validation task-macro cross-entropy to class-balanced one-step reachability teacher",
        "device": str(device),
        "validation": final_metrics,
        "history": history,
        "weights_sha256": sha256_file(output / "proposal-v05.pt")[0],
        "validation_predictions_sha256": sha256_file(output / "validation-predictions-v05.npz")[0],
    }


def train(view_dir: Path, feature_dir: Path, teacher_path: Path, label_dir: Path, output_dir: Path,
          *, seed: int, epochs: int, device: str) -> dict[str, Any]:
    view = view_dir.resolve(strict=True)
    feature_root = feature_dir.resolve(strict=True)
    teacher_file = teacher_path.resolve(strict=True)
    label_root = label_dir.resolve(strict=True)
    output = output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite V05 proposal fit {output}")
    view_receipt_path = view / "trainval-view-receipt-v05-v01.json"
    feature_receipt_path = feature_root / "frozen-features-trainval-receipt-v05-v01.json"
    label_receipt_path = label_root / "action-label-receipt-v05-v01.json"
    view_receipt = json.loads(view_receipt_path.read_text(encoding="utf-8"))
    feature_receipt = json.loads(feature_receipt_path.read_text(encoding="utf-8"))
    label_receipt = json.loads(label_receipt_path.read_text(encoding="utf-8"))
    view_hash = sha256_file(view_receipt_path)[0]
    if view_receipt.get("status") != "TRAIN_VALIDATION_VIEW_COMPLETE" or view_receipt.get("qualification_rows_emitted") != 0:
        raise ValueError("V05 proposal task view is not train/validation-only")
    if feature_receipt.get("status") != "V05_TRAINVAL_FEATURES_COMPLETE" or feature_receipt.get("qualification_rows_emitted") != 0:
        raise ValueError("V05 proposal feature view is not train/validation-only")
    if label_receipt.get("status") != "V05_TRAINVAL_ACTION_LABELS_COMPLETE" or label_receipt.get("qualification_rows") != 0:
        raise ValueError("V05 teacher receipt is not train/validation-only")
    if (view_receipt.get("qualification_targets_generated") is not False
            or feature_receipt.get("qualification_targets_generated") is not False
            or label_receipt.get("qualification_targets_generated") is not False
            or view_receipt.get("qualification_target_paths_or_hashes_recorded") is not False
            or feature_receipt.get("qualification_target_paths_or_hashes_recorded") is not False
            or label_receipt.get("qualification_target_paths_or_hashes_recorded") is not False):
        raise ValueError("V05 proposal inputs declare qualification target generation/access")
    if (feature_receipt.get("view_receipt_sha256") != view_hash
            or label_receipt.get("view_receipt_sha256") != view_hash):
        raise ValueError("V05 proposal receipts do not bind to the supplied train/validation view")

    public_path = view / "public-tasks-trainval-v05.jsonl"
    support_path = view / "stress-support-trainval-v05.json"
    for path in (public_path, support_path):
        verify_recorded_file(path, receipt_output(view_receipt, path.name), path.name)
    public_tasks = [json.loads(line) for line in public_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    support = json.loads(support_path.read_text(encoding="utf-8"))
    split_by_task = {row["task_id"]: row["split"] for row in support["family_roster"]}
    if len(public_tasks) != 80 or set(split_by_task) != {row["id"] for row in public_tasks}:
        raise ValueError("V05 train/validation public task roster mismatch")
    if label_receipt.get("view_source_support_manifest_sha256") != view_receipt.get("source_support_manifest_sha256"):
        raise ValueError("V05 proposal teacher used a different source support manifest")
    private_record = receipt_output(view_receipt, "private-tasks-trainval-v05.jsonl")
    if (label_receipt.get("trainval_private_tasks", {}).get("sha256") != private_record["sha256"]
            or label_receipt.get("trainval_private_tasks", {}).get("bytes") != private_record["bytes"]):
        raise ValueError("V05 teacher receipt does not bind to the filtered private train/validation task source")

    features_path = feature_root / "constraint_H_trainval.float32.npy"
    global_path = feature_root / "global_h_trainval.float32.npy"
    rows_path = feature_root / "rows_trainval.jsonl"
    for path in (features_path, global_path, rows_path):
        verify_recorded_file(path, receipt_output(feature_receipt, path.name), path.name)
    if feature_receipt.get("model_revision") != MODEL_REVISION:
        raise ValueError("V05 frozen sensor model revision changed")
    if feature_receipt.get("trainval_public_tasks_sha256") != sha256_file(public_path)[0]:
        raise ValueError("V05 frozen sensor slice was built from another public task view")
    clause_h = np.load(features_path, mmap_mode="r", allow_pickle=False)
    global_h = np.load(global_path, mmap_mode="r", allow_pickle=False)
    if clause_h.dtype != np.dtype("<f4") or global_h.dtype != np.dtype("<f4"):
        raise ValueError("V05 candidate features require little-endian float32 sensor arrays")
    if global_h.shape != (80, FM.HIDDEN_DIM):
        raise ValueError("V05 train/validation global feature shape mismatch")

    task_by_id = {task["id"]: task for task in public_tasks}
    global_rows: dict[str, int] = {}
    clause_rows: dict[str, dict[int, int]] = defaultdict(dict)
    seen_global_indices: set[int] = set()
    seen_clause_indices: set[int] = set()
    for row in (json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()):
        task_id = row["task_id"]
        task = task_by_id.get(task_id)
        if task is None or row.get("split") != split_by_task[task_id] or row.get("family_id") != task["family_id"]:
            raise ValueError("V05 filtered feature row has unknown task/family/split")
        index = int(row["row"])
        if row["kind"] == "global":
            if task_id in global_rows or index in seen_global_indices or not 0 <= index < len(global_h):
                raise ValueError("duplicate or out-of-range V05 global feature row")
            seen_global_indices.add(index)
            global_rows[task_id] = index
        elif row["kind"] == "constraint":
            clause_id = int(row["clause_index"])
            if clause_id in clause_rows[task_id] or index in seen_clause_indices or not 0 <= index < len(clause_h):
                raise ValueError("duplicate or out-of-range V05 clause feature row")
            seen_clause_indices.add(index)
            clause_rows[task_id][clause_id] = index
        else:
            raise ValueError(f"unknown V05 feature row kind {row.get('kind')!r}")
    if (set(global_rows) != set(task_by_id) or len(global_rows) != len(global_h)
            or seen_global_indices != set(range(len(global_h)))):
        raise ValueError("V05 global features do not cover the task roster exactly once")
    if (len(clause_rows) != 80 or sum(map(len, clause_rows.values())) != len(clause_h)
            or seen_clause_indices != set(range(len(clause_h)))):
        raise ValueError("V05 clause features do not cover the task roster exactly once")

    feature_by_task: dict[str, np.ndarray] = {}
    for task_id, task in task_by_id.items():
        if task["n"] != N_ENTITIES or task["k"] != N_ROLES:
            raise ValueError("V05 proposal currently requires N=20 and K=3")
        by_clause = clause_rows[task_id]
        if set(by_clause) != set(range(len(task["clauses"]))):
            raise ValueError(f"V05 clause feature map is incomplete for {task_id}")
        h_rows = [by_clause[index] for index in range(len(task["clauses"]))]
        fm_task = FM.FeatureTask(
            task_id=task_id,
            family_id=task["family_id"],
            split=split_by_task[task_id],
            global_h=np.asarray(global_h[global_rows[task_id]], dtype=np.float32),
            clause_h=np.asarray(clause_h[np.asarray(h_rows, dtype=np.int64)], dtype=np.float32),
            entity_mentions=task["entity_mentions"],
            role_mentions=task["role_mentions"],
            input_row=task,
        )
        feature_by_task[task_id] = FM.build_static_candidate_features(fm_task, N_ENTITIES, N_ROLES)

    target_record = label_receipt.get("teacher_targets", {})
    verify_recorded_file(teacher_file, target_record, "class-balanced teacher targets")
    teacher_rows: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    features: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    class_fraction: list[np.ndarray] = []
    task_ids: list[str] = []
    state_indices: list[int] = []
    seen_states: dict[str, set[int]] = defaultdict(set)
    with teacher_file.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            teacher = json.loads(line)
            task_id = teacher.get("task_id")
            task = task_by_id.get(task_id)
            if task is None:
                raise ValueError(f"V05 teacher target contains non-train/validation task at line {line_number}")
            split = split_by_task[task_id]
            state_index = int(teacher.get("state_index", -1))
            if not 0 <= state_index < STATE_COUNT or state_index in seen_states[task_id]:
                raise ValueError(f"V05 duplicate/out-of-range teacher state for {task_id}")
            seen_states[task_id].add(state_index)
            assignment = [int(role) for role in teacher.get("assignment", [])]
            if len(assignment) != N_ENTITIES or any(not 0 <= role < N_ROLES for role in assignment):
                raise ValueError(f"V05 teacher assignment shape/range mismatch for {task_id}")
            actions, action_features = FM.candidate_features(feature_by_task[task_id], assignment)
            q, broadness = validate_target_row(teacher, task, split, actions)
            features.append(action_features)
            targets.append(q)
            class_fraction.append(broadness)
            task_ids.append(task_id)
            state_indices.append(state_index)
            teacher_rows.append({"task_id": task_id, "family_id": task["family_id"],
                                 "family_split": split, "state_index": state_index})
            state_counts[task_id] += 1
    if len(teacher_rows) != 80 * STATE_COUNT or any(state_counts[task_id] != STATE_COUNT for task_id in task_by_id):
        raise ValueError("V05 teacher target roster must contain 32 states for each of 80 train/validation tasks")
    for task_id in task_by_id:
        if seen_states[task_id] != set(range(STATE_COUNT)):
            raise ValueError(f"V05 teacher states are incomplete for {task_id}")

    x = np.asarray(features, dtype=np.float32)
    q = np.asarray(targets, dtype=np.float32)
    g = np.asarray(class_fraction, dtype=np.float32)
    task_ids_array = list(task_ids)
    if x.shape != (80 * STATE_COUNT, ACTION_COUNT, FM.PROPOSAL_INPUT_DIM) or q.shape != (80 * STATE_COUNT, ACTION_COUNT):
        raise ValueError(f"unexpected V05 proposal fit tensor shape {x.shape}/{q.shape}")
    if not np.isfinite(x).all() or not np.isfinite(q).all() or not np.allclose(q.sum(axis=1), 1.0, atol=1e-6, rtol=0.0):
        raise ValueError("V05 proposal training inputs contain invalid features or teacher distributions")
    output.mkdir(parents=True)
    rows_path_out = output / "proposal-trainval-row-map-v05.jsonl"
    rows_path_out.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in teacher_rows), encoding="utf-8")
    tensors_path = output / "proposal-inputs-trainval-v05.npz"
    np.savez_compressed(tensors_path, candidate_features=x, teacher_q=q, teacher_class_fraction=g,
                        task_ids=np.asarray(task_ids_array), state_indices=np.asarray(state_indices, dtype=np.int16))
    train = np.asarray([index for index, task_id in enumerate(task_ids_array) if split_by_task[task_id] == "train"], dtype=np.int64)
    validation = np.asarray([index for index, task_id in enumerate(task_ids_array) if split_by_task[task_id] == "validation"], dtype=np.int64)
    fit = _fit(x, q, task_ids_array, train, validation, g, seed=seed, epochs=epochs,
               device_name=device, output=output)
    receipt = {
        "schema": "R1_STAGE1_V05_PROPOSAL_FIT_V01",
        "status": "V05_TRAINVAL_PROPOSAL_FIT_COMPLETE",
        "fit_scope": "class-balanced one-step reachability teacher; validation-selected 10-to-16-to-1 tanh proposal",
        "analysis_mode": "adaptive engineering; validation used to select checkpoint",
        "qualification_rows": 0,
        "qualification_targets_generated": False,
        "qualification_target_paths_or_hashes_recorded": False,
        "split_usage": {"train": "proposal fit", "validation": "checkpoint selection only"},
        "run_config": {"seed": seed, "epoch_limit": epochs, "requested_device": device},
        "input_hashes": {
            "view_receipt": file_record(view_receipt_path),
            "public_trainval_tasks": file_record(public_path),
            "trainval_support": file_record(support_path),
            "feature_receipt": file_record(feature_receipt_path),
            "teacher_receipt": file_record(label_receipt_path),
            "teacher_targets": file_record(teacher_file),
            "global_features": file_record(global_path),
            "constraint_features": file_record(features_path),
            "feature_row_map": file_record(rows_path),
            "fit_source": file_record(Path(__file__)),
            "shared_feature_math_source": file_record(Path(__file__).resolve().parents[1] / "feature_math.py"),
        },
        "teacher_producer": {
            "command": label_receipt.get("teacher_command"),
            "source_hashes": label_receipt.get("teacher_sources"),
            "executable": label_receipt.get("teacher_executable"),
            "semantics": label_receipt.get("summary", {}).get("teacher_semantics"),
        },
        "contract": {
            "task_shape": {"n": N_ENTITIES, "k": N_ROLES},
            "feature_schema": "V02 shared 8 semantic candidate features plus old-role and new-role occupancy fractions",
            "feature_dim": FM.PROPOSAL_INPUT_DIM,
            "state_count": len(teacher_rows),
            "states_per_task": STATE_COUNT,
            "action_count_per_state": ACTION_COUNT,
            "task_counts": {"train": 64, "validation": 16},
            "state_counts": {"train": len(train), "validation": len(validation)},
            "teacher_outcomes": dict(Counter("positive_mass" for _ in teacher_rows)),
            "q_is_class_balanced_one_step_reachability": True,
        },
        "fit": fit,
        "training_inputs": file_record(tensors_path),
        "row_map": file_record(rows_path_out),
    }
    receipt_path = output / "proposal-fit-receipt-v05-v01.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view-dir", type=Path, required=True)
    parser.add_argument("--feature-dir", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--label-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=71027)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--device", default="cuda" if __import__("torch").cuda.is_available() else "cpu")
    args = parser.parse_args()
    output = args.output.resolve()
    output_existed = output.exists()
    try:
        receipt = train(args.view_dir, args.feature_dir, args.teacher_targets, args.label_dir, output,
                        seed=args.seed, epochs=args.epochs, device=args.device)
    except Exception as error:
        if not output_existed and output.is_dir() and not (output / "proposal-fit-receipt-v05-v01.json").exists() and not (output / "failure.json").exists():
            failure = {"schema": "R1_STAGE1_ATTEMPT_FAILURE_V01", "status": "V05_PROPOSAL_FIT_FAILED",
                       "phase": "trainval_proposal_fit", "error_type": type(error).__name__, "error": str(error),
                       "source": file_record(Path(__file__))}
            (output / "failure.json").write_text(json.dumps(failure, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise
    print(f"R1_V05_PROPOSAL_FIT_COMPLETE val_task_macro_ce={receipt['fit']['validation']['task_macro_cross_entropy']:.4f} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
