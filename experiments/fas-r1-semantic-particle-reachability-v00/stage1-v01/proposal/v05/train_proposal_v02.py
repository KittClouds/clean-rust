#!/usr/bin/env python3
"""Train a revised V05 proposal with explicit source/target role identity."""

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
import train_proposal_v01 as BASE  # noqa: E402


N_ENTITIES = 20
N_ROLES = 3
STATE_COUNT = 32
ACTION_COUNT = N_ENTITIES * (N_ROLES - 1)
INPUT_DIM = FM.PROPOSAL_INPUT_DIM + N_ROLES * 2


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


def build_state_action_features(static: np.ndarray, assignment: list[int]) -> tuple[list[tuple[int, int]], np.ndarray]:
    if len(assignment) != N_ENTITIES or any(not 0 <= int(role) < N_ROLES for role in assignment):
        raise ValueError("V05 proposal state must be a valid N=20, K=3 assignment")
    actions, base_features = FM.candidate_features(static, assignment)
    result = np.empty((ACTION_COUNT, INPUT_DIM), dtype=np.float32)
    for index, (entity, new_role) in enumerate(actions):
        old_role = int(assignment[entity])
        old_onehot = np.zeros(N_ROLES, dtype=np.float32)
        new_onehot = np.zeros(N_ROLES, dtype=np.float32)
        old_onehot[old_role] = 1.0
        new_onehot[new_role] = 1.0
        result[index] = np.concatenate((base_features[index], old_onehot, new_onehot))
    if result.shape != (ACTION_COUNT, INPUT_DIM) or not np.isfinite(result).all():
        raise ValueError("V05 proposal action feature tensor failed shape/value checks")
    return actions, result


def fit(features: np.ndarray, targets: np.ndarray, task_ids: list[str], splits: list[str], broadness: np.ndarray,
        *, seed: int, epochs: int, device_name: str, output: Path) -> dict[str, Any]:
    import torch
    from torch import nn

    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)
    device = torch.device(device_name)
    model = nn.Sequential(nn.Linear(INPUT_DIM, 64), nn.Tanh(), nn.Linear(64, 1)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    train = np.asarray([i for i, split in enumerate(splits) if split == "train"], dtype=np.int64)
    validation = np.asarray([i for i, split in enumerate(splits) if split == "validation"], dtype=np.int64)
    if len(train) != 64 * STATE_COUNT or len(validation) != 16 * STATE_COUNT:
        raise ValueError("V05 proposal train/validation state counts differ from the filtered roster")
    best_state = None
    best_score = float("inf")
    best_epoch = 0
    stale = 0
    history = []

    def predict(indices: np.ndarray) -> np.ndarray:
        model.eval()
        batches = []
        with torch.no_grad():
            for start in range(0, len(indices), 64):
                chosen = indices[start:start + 64]
                x = torch.as_tensor(features[chosen], dtype=torch.float32, device=device)
                batches.append(model(x).squeeze(-1).cpu().numpy())
        return np.concatenate(batches, axis=0)

    for epoch in range(1, epochs + 1):
        model.train()
        order = torch.randperm(len(train), generator=generator).numpy()
        for start in range(0, len(order), 64):
            chosen = train[order[start:start + 64]]
            x = torch.as_tensor(features[chosen], dtype=torch.float32, device=device)
            q = torch.as_tensor(targets[chosen], dtype=torch.float32, device=device)
            logits = model(x).squeeze(-1)
            loss = -(q * torch.log_softmax(logits, dim=-1)).sum(dim=-1).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        logits = predict(validation)
        metrics = BASE._prediction_metrics(targets[validation], logits,
                                           [task_ids[i] for i in validation], broadness[validation])
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
        raise RuntimeError("V05 role-aware proposal fit did not select a checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    val_logits = predict(validation)
    validation_metrics = BASE._prediction_metrics(targets[validation], val_logits,
                                                  [task_ids[i] for i in validation], broadness[validation])
    torch.save({"architecture": "tanh_mlp_base_f16_h64_v05_02", "input_dim": INPUT_DIM,
                "hidden_dim": 64, "state_dict": model.cpu().state_dict(),
                "label_semantics": BASE.TARGET_SCHEMA}, output / "proposal-v05-v02.pt")
    probabilities = np.exp(val_logits - np.logaddexp.reduce(val_logits, axis=1, keepdims=True))
    np.savez_compressed(output / "validation-predictions-v05-v02.npz",
                        logits=val_logits.astype(np.float32), probabilities=probabilities.astype(np.float32),
                        teacher_q=targets[validation], teacher_class_fraction=broadness[validation])
    return {"architecture": "tanh_mlp_base_f16_h64_v05_02", "input_dim": INPUT_DIM, "hidden_dim": 64,
            "optimizer": "AdamW", "learning_rate": 1e-3, "weight_decay": 1e-4,
            "batch_size_states": 64, "selected_epoch": best_epoch, "epochs_run": len(history),
            "early_stop_patience": 10, "selection_metric": "validation task-macro teacher cross-entropy",
            "device": str(device), "validation": validation_metrics, "history": history,
            "weights_sha256": sha256_file(output / "proposal-v05-v02.pt")[0],
            "validation_predictions_sha256": sha256_file(output / "validation-predictions-v05-v02.npz")[0]}


def train(view_dir: Path, feature_dir: Path, teacher_path: Path, label_dir: Path, output_dir: Path,
          *, seed: int, epochs: int, device: str) -> dict[str, Any]:
    view = view_dir.resolve(strict=True)
    feature_root = feature_dir.resolve(strict=True)
    teacher_file = teacher_path.resolve(strict=True)
    label_root = label_dir.resolve(strict=True)
    output = output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite V05 proposal-fit v02 {output}")
    view_receipt_path = view / "trainval-view-receipt-v05-v01.json"
    feature_receipt_path = feature_root / "frozen-features-trainval-receipt-v05-v01.json"
    label_receipt_path = label_root / "action-label-receipt-v05-v01.json"
    view_receipt = json.loads(view_receipt_path.read_text(encoding="utf-8"))
    feature_receipt = json.loads(feature_receipt_path.read_text(encoding="utf-8"))
    label_receipt = json.loads(label_receipt_path.read_text(encoding="utf-8"))
    view_hash = sha256_file(view_receipt_path)[0]
    if view_receipt.get("status") != "TRAIN_VALIDATION_VIEW_COMPLETE" or view_receipt.get("qualification_rows_emitted") != 0:
        raise ValueError("V05 task view is not train/validation-only")
    if feature_receipt.get("status") != "V05_TRAINVAL_FEATURES_COMPLETE" or feature_receipt.get("qualification_rows_emitted") != 0:
        raise ValueError("V05 feature view is not train/validation-only")
    if label_receipt.get("status") != "V05_TRAINVAL_ACTION_LABELS_COMPLETE" or label_receipt.get("qualification_rows") != 0:
        raise ValueError("V05 teacher receipt is not train/validation-only")
    receipts = (view_receipt, feature_receipt, label_receipt)
    if any(row.get("qualification_targets_generated") is not False
           or row.get("qualification_target_paths_or_hashes_recorded") is not False for row in receipts):
        raise ValueError("V05 proposal input receipt declares qualification target contact")
    if feature_receipt.get("view_receipt_sha256") != view_hash or label_receipt.get("view_receipt_sha256") != view_hash:
        raise ValueError("V05 receipts do not bind to the supplied train/validation view")

    public_path = view / "public-tasks-trainval-v05.jsonl"
    support_path = view / "stress-support-trainval-v05.json"
    for path in (public_path, support_path):
        verify_recorded_file(path, view_receipt.get("outputs", {}).get(path.name, {}), path.name)
    public_tasks = [json.loads(line) for line in public_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    support = json.loads(support_path.read_text(encoding="utf-8"))
    split_by_task = {row["task_id"]: row["split"] for row in support["family_roster"]}
    task_by_id = {task["id"]: task for task in public_tasks}
    if len(task_by_id) != 80 or set(split_by_task) != set(task_by_id):
        raise ValueError("V05 proposal view/support roster mismatch")
    if feature_receipt.get("trainval_public_tasks_sha256") != sha256_file(public_path)[0]:
        raise ValueError("V05 sliced features bind to another public task roster")
    if label_receipt.get("view_source_support_manifest_sha256") != view_receipt.get("source_support_manifest_sha256"):
        raise ValueError("V05 proposal teacher used a different support manifest")
    private_record = view_receipt.get("outputs", {}).get("private-tasks-trainval-v05.jsonl", {})
    if (label_receipt.get("trainval_private_tasks", {}).get("sha256") != private_record.get("sha256")
            or label_receipt.get("trainval_private_tasks", {}).get("bytes") != private_record.get("bytes")):
        raise ValueError("V05 teacher is not bound to the filtered private training source")

    h_path = feature_root / "constraint_H_trainval.float32.npy"
    global_path = feature_root / "global_h_trainval.float32.npy"
    rows_path = feature_root / "rows_trainval.jsonl"
    for path in (h_path, global_path, rows_path):
        verify_recorded_file(path, feature_receipt.get("outputs", {}).get(path.name, {}), path.name)
    if feature_receipt.get("model_revision") != FM.__dict__.get("MODEL_REVISION", "7453bca97ca1e67754c4035a4b4c584e1c9dd725"):
        raise ValueError("V05 frozen sensor model revision mismatch")
    if (feature_receipt.get("feature_shape", {}).get("global") != [80, FM.HIDDEN_DIM]
            or feature_receipt.get("feature_shape", {}).get("constraints") != [sum(len(t["clauses"]) for t in public_tasks), FM.HIDDEN_DIM]):
        raise ValueError("V05 frozen feature receipt shape mismatch")
    h = np.load(h_path, mmap_mode="r", allow_pickle=False)
    global_h = np.load(global_path, mmap_mode="r", allow_pickle=False)
    if (h.dtype != np.dtype("<f4") or global_h.dtype != np.dtype("<f4")
            or h.shape != tuple(feature_receipt["feature_shape"]["constraints"])
            or global_h.shape != tuple(feature_receipt["feature_shape"]["global"])):
        raise ValueError("V05 frozen features must be little-endian float32")

    global_rows: dict[str, int] = {}
    clauses: dict[str, dict[int, int]] = defaultdict(dict)
    global_seen: set[int] = set()
    clause_seen: set[int] = set()
    for row in (json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()):
        task_id = row["task_id"]
        task = task_by_id.get(task_id)
        index = int(row["row"])
        if task is None or row.get("split") != split_by_task[task_id] or row.get("family_id") != task["family_id"]:
            raise ValueError("V05 feature row has wrong task/family/split")
        if row["kind"] == "global":
            if task_id in global_rows or index in global_seen or not 0 <= index < len(global_h):
                raise ValueError("duplicate/out-of-range V05 global feature row")
            global_rows[task_id] = index
            global_seen.add(index)
        elif row["kind"] == "constraint":
            clause_id = int(row["clause_index"])
            if clause_id in clauses[task_id] or index in clause_seen or not 0 <= index < len(h):
                raise ValueError("duplicate/out-of-range V05 constraint feature row")
            clauses[task_id][clause_id] = index
            clause_seen.add(index)
        else:
            raise ValueError(f"unknown V05 feature row kind {row.get('kind')!r}")
    if global_seen != set(range(len(global_h))) or set(global_rows) != set(task_by_id):
        raise ValueError("V05 global feature rows are incomplete")
    if clause_seen != set(range(len(h))) or sum(len(rows) for rows in clauses.values()) != len(h):
        raise ValueError("V05 constraint feature rows are incomplete")

    static_by_task: dict[str, np.ndarray] = {}
    for task_id, task in task_by_id.items():
        clause_map = clauses[task_id]
        if set(clause_map) != set(range(len(task["clauses"]))):
            raise ValueError(f"V05 clause row map incomplete for {task_id}")
        clause_h = np.asarray(h[np.asarray([clause_map[i] for i in range(len(task["clauses"]))], dtype=np.int64)], dtype=np.float32)
        feature_task = FM.FeatureTask(task_id, task["family_id"], split_by_task[task_id],
                                      np.asarray(global_h[global_rows[task_id]], dtype=np.float32), clause_h,
                                      task["entity_mentions"], task["role_mentions"], task)
        static_by_task[task_id] = FM.build_static_candidate_features(feature_task, N_ENTITIES, N_ROLES)

    teacher_record = label_receipt.get("teacher_targets", {})
    verify_recorded_file(teacher_file, teacher_record, "class-balanced teacher targets")
    sample_features: list[np.ndarray] = []
    sample_q: list[np.ndarray] = []
    sample_g: list[np.ndarray] = []
    task_ids: list[str] = []
    splits: list[str] = []
    state_indices: list[int] = []
    states_seen: dict[str, set[int]] = defaultdict(set)
    with teacher_file.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            teacher = json.loads(line)
            task_id = teacher.get("task_id")
            task = task_by_id.get(task_id)
            if task is None:
                raise ValueError(f"V05 teacher target outside train/validation roster at line {line_number}")
            state_index = int(teacher.get("state_index", -1))
            if not 0 <= state_index < STATE_COUNT or state_index in states_seen[task_id]:
                raise ValueError(f"V05 duplicate/out-of-range teacher state for {task_id}")
            states_seen[task_id].add(state_index)
            assignment = [int(role) for role in teacher.get("assignment", [])]
            if len(assignment) != N_ENTITIES or any(not 0 <= role < N_ROLES for role in assignment):
                raise ValueError(f"V05 teacher assignment invalid for {task_id}")
            actions, features = build_state_action_features(static_by_task[task_id], assignment)
            q, g = BASE.validate_target_row(teacher, task, split_by_task[task_id], actions)
            sample_features.append(features)
            sample_q.append(q)
            sample_g.append(g)
            task_ids.append(task_id)
            splits.append(split_by_task[task_id])
            state_indices.append(state_index)
    if (len(sample_features) != 80 * STATE_COUNT
            or any(states_seen[task_id] != set(range(STATE_COUNT)) for task_id in task_by_id)):
        raise ValueError("V05 teacher targets do not cover 32 states per train/validation task")
    x = np.asarray(sample_features, dtype=np.float32)
    q = np.asarray(sample_q, dtype=np.float32)
    g = np.asarray(sample_g, dtype=np.float32)
    if x.shape != (80 * STATE_COUNT, ACTION_COUNT, INPUT_DIM) or q.shape != (80 * STATE_COUNT, ACTION_COUNT):
        raise ValueError(f"V05 role-aware proposal tensor shape mismatch: {x.shape}/{q.shape}")
    if not np.isfinite(x).all() or not np.isfinite(q).all() or not np.allclose(q.sum(1), 1.0, atol=1e-6, rtol=0):
        raise ValueError("V05 role-aware proposal inputs are invalid")

    output.mkdir(parents=True)
    row_map = output / "proposal-trainval-row-map-v05-v02.jsonl"
    row_map.write_text("".join(json.dumps({"task_id": task_id, "split": split, "state_index": state},
                                            sort_keys=True, separators=(",", ":")) + "\n"
                                for task_id, split, state in zip(task_ids, splits, state_indices, strict=True)),
                       encoding="utf-8")
    tensors = output / "proposal-inputs-trainval-v05-v02.npz"
    np.savez_compressed(tensors, candidate_features=x, teacher_q=q, teacher_class_fraction=g,
                        task_ids=np.asarray(task_ids), splits=np.asarray(splits))
    result = fit(x, q, task_ids, splits, g, seed=seed, epochs=epochs, device_name=device, output=output)
    receipt = {
        "schema": "R1_STAGE1_V05_PROPOSAL_FIT_V02",
        "status": "V05_TRAINVAL_PROPOSAL_FIT_V02_COMPLETE",
        "fit_scope": "class-balanced one-step reachability teacher; validation-selected role-aware candidate policy",
        "analysis_mode": "adaptive engineering; validation used to select checkpoint",
        "qualification_rows": 0,
        "qualification_targets_generated": False,
        "qualification_target_paths_or_hashes_recorded": False,
        "split_usage": {"train": "fit only", "validation": "checkpoint selection only"},
        "run_config": {"seed": seed, "epoch_limit": epochs, "requested_device": device},
        "inputs": {"view_receipt": file_record(view_receipt_path), "feature_receipt": file_record(feature_receipt_path),
                   "teacher_receipt": file_record(label_receipt_path), "public_tasks": file_record(public_path),
                   "support": file_record(support_path), "teacher_targets": file_record(teacher_file),
                   "global_features": file_record(global_path), "constraint_features": file_record(h_path),
                   "feature_rows": file_record(rows_path), "trainer_source": file_record(Path(__file__)),
                   "base_teacher_math_source": file_record(Path(__file__).with_name("train_proposal_v01.py")),
                   "action_feature_source": file_record(Path(__file__).with_name("train_action_relevance_v01.py")),
                   "shared_feature_math_source": file_record(Path(__file__).resolve().parents[1] / "feature_math.py")},
        "teacher_producer": {"command": label_receipt.get("teacher_command"),
                             "sources": label_receipt.get("teacher_sources"),
                             "executable": label_receipt.get("teacher_executable"),
                             "semantics": label_receipt.get("summary", {}).get("teacher_semantics")},
        "contract": {"task_shape": {"n": N_ENTITIES, "k": N_ROLES},
                     "feature_schema": "V02 10 candidate features + source-role and target-role one-hot",
                     "feature_dim": INPUT_DIM, "states": len(task_ids), "states_per_task": STATE_COUNT,
                     "actions_per_state": ACTION_COUNT, "train_states": splits.count("train"),
                     "validation_states": splits.count("validation"), "teacher_target": BASE.TARGET_SCHEMA},
        "fit": result, "training_inputs": file_record(tensors), "row_map": file_record(row_map),
    }
    receipt_path = output / "proposal-fit-receipt-v05-v02.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view-dir", type=Path, required=True)
    parser.add_argument("--feature-dir", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--label-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=71028)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--device", default="cuda" if __import__("torch").cuda.is_available() else "cpu")
    args = parser.parse_args()
    output = args.output.resolve()
    output_existed = output.exists()
    try:
        receipt = train(args.view_dir, args.feature_dir, args.teacher_targets, args.label_dir, output,
                        seed=args.seed, epochs=args.epochs, device=args.device)
    except Exception as error:
        if not output_existed and output.is_dir() and not (output / "proposal-fit-receipt-v05-v02.json").exists() and not (output / "failure.json").exists():
            failure = {"schema": "R1_STAGE1_ATTEMPT_FAILURE_V01", "status": "V05_PROPOSAL_FIT_V02_FAILED",
                       "phase": "trainval_role_aware_proposal_fit", "error_type": type(error).__name__,
                       "error": str(error), "source": file_record(Path(__file__))}
            (output / "failure.json").write_text(json.dumps(failure, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise
    print(f"R1_V05_PROPOSAL_FIT_V02_COMPLETE val_task_macro_ce={receipt['fit']['validation']['task_macro_cross_entropy']:.4f} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
