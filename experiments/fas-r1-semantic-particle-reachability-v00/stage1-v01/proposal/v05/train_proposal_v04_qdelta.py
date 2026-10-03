#!/usr/bin/env python3
"""Fit V05 action proposals with a frozen Q-terminal delta skip and residual scorer."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import train_action_relevance_v01 as RF  # noqa: E402
import train_proposal_v01 as BASE  # noqa: E402


N_ENTITIES = 20
N_ROLES = 3
STATE_COUNT = 32
ACTION_COUNT = N_ENTITIES * (N_ROLES - 1)
BASE_INPUT_DIM = RF.FEATURE_DIM
INPUT_DIM = BASE_INPUT_DIM + 1
HIDDEN = 128


class AppendedDeltaFeatures:
    """Read the V03 feature mmap and append one state-action Q-terminal delta."""

    def __init__(self, base: np.memmap, delta: np.ndarray):
        if base.ndim != 2 or base.shape[1] != BASE_INPUT_DIM:
            raise ValueError("V04 base feature matrix shape mismatch")
        flat_delta = np.asarray(delta, dtype=np.float32).reshape(-1)
        if len(flat_delta) != len(base) or not np.isfinite(flat_delta).all():
            raise ValueError("V04 Q-terminal delta feature shape/value mismatch")
        self.base = base
        self.delta = flat_delta
        self.shape = (len(base), INPUT_DIM)

    def __getitem__(self, indices: np.ndarray) -> np.ndarray:
        index = np.asarray(indices, dtype=np.int64)
        base_rows = np.asarray(self.base[index], dtype=np.float32)
        if base_rows.ndim == 1:
            base_rows = base_rows.reshape(1, -1)
        delta_rows = self.delta[index].reshape(-1, 1)
        return np.concatenate((base_rows, delta_rows), axis=1)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"expected JSON objects in {path}")
    return rows


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


def _normalization(matrix: AppendedDeltaFeatures, action_indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    total = np.zeros(INPUT_DIM, dtype=np.float64)
    square = np.zeros(INPUT_DIM, dtype=np.float64)
    for start in range(0, len(action_indices), 256):
        batch = np.asarray(matrix[action_indices[start:start + 256]], dtype=np.float64)
        total += batch.sum(axis=0)
        square += np.square(batch).sum(axis=0)
    mean = total / len(action_indices)
    variance = np.maximum(square / len(action_indices) - mean * mean, 0.0)
    std = np.sqrt(variance)
    std[std < 1e-6] = 1.0
    return mean.astype(np.float32), std.astype(np.float32)


def fit(matrix: AppendedDeltaFeatures, targets: np.ndarray, broadness: np.ndarray, task_ids: list[str],
        splits: list[str], *, seed: int, epochs: int, device_name: str, output: Path,
        baseline_beta: float) -> dict[str, Any]:
    import torch
    from torch import nn

    train = np.asarray([i for i, split in enumerate(splits) if split == "train"], dtype=np.int64)
    validation = np.asarray([i for i, split in enumerate(splits) if split == "validation"], dtype=np.int64)
    if len(train) != 64 * STATE_COUNT or len(validation) != 16 * STATE_COUNT:
        raise ValueError("V05 proposal train/validation state counts do not match the filtered roster")
    train_actions = (train[:, None] * ACTION_COUNT + np.arange(ACTION_COUNT, dtype=np.int64)).reshape(-1)
    mean, std = _normalization(matrix, train_actions)
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)
    device = torch.device(device_name)
    class QDeltaResidual(nn.Module):
        def __init__(self, input_dim: int, initial_gain: float):
            super().__init__()
            self.delta_gain = nn.Parameter(torch.tensor(initial_gain, dtype=torch.float32))
            self.residual = nn.Sequential(nn.Linear(input_dim, HIDDEN), nn.ReLU(), nn.Linear(HIDDEN, 1))
            nn.init.zeros_(self.residual[-1].weight)
            nn.init.zeros_(self.residual[-1].bias)

        def forward(self, features):
            direct = features[..., -1] * self.delta_gain
            return direct + self.residual(features).squeeze(-1)

    initial_gain = float(baseline_beta) * float(std[-1])
    model = QDeltaResidual(INPUT_DIM, initial_gain).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    best_state = {name: tensor.detach().cpu().clone() for name, tensor in model.state_dict().items()}
    baseline_logits = np.asarray(matrix[(validation[:, None] * ACTION_COUNT
                                         + np.arange(ACTION_COUNT, dtype=np.int64)).reshape(-1)], dtype=np.float32)
    baseline_logits = baseline_logits[:, -1].reshape(len(validation), ACTION_COUNT) * baseline_beta
    baseline_metrics = BASE._prediction_metrics(targets[validation], baseline_logits,
                                                [task_ids[i] for i in validation], broadness[validation])
    best_loss = baseline_metrics["task_macro_cross_entropy"]
    best_epoch = 0
    stale = 0
    history: list[dict[str, Any]] = [{"epoch": 0, "validation": baseline_metrics,
                                      "kind": "frozen_qterminal_delta_baseline"}]

    def predict(state_indices: np.ndarray) -> np.ndarray:
        model.eval()
        result = []
        with torch.no_grad():
            for start in range(0, len(state_indices), 16):
                chosen = state_indices[start:start + 16]
                flat = (chosen[:, None] * ACTION_COUNT + np.arange(ACTION_COUNT, dtype=np.int64)).reshape(-1)
                x = np.asarray(matrix[flat], dtype=np.float32).reshape(len(chosen), ACTION_COUNT, INPUT_DIM)
                x = (x - mean) / std
                tensor = torch.as_tensor(x, dtype=torch.float32, device=device)
                result.append(model(tensor).cpu().numpy())
        return np.concatenate(result, axis=0)

    for epoch in range(1, epochs + 1):
        model.train()
        order = torch.randperm(len(train), generator=generator).numpy()
        for start in range(0, len(order), 16):
            chosen = train[order[start:start + 16]]
            flat = (chosen[:, None] * ACTION_COUNT + np.arange(ACTION_COUNT, dtype=np.int64)).reshape(-1)
            x = np.asarray(matrix[flat], dtype=np.float32).reshape(len(chosen), ACTION_COUNT, INPUT_DIM)
            x = (x - mean) / std
            tensor = torch.as_tensor(x, dtype=torch.float32, device=device)
            q = torch.as_tensor(targets[chosen], dtype=torch.float32, device=device)
            logits = model(tensor)
            loss = -(q * torch.log_softmax(logits, dim=-1)).sum(dim=-1).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        logits = predict(validation)
        metrics = BASE._prediction_metrics(targets[validation], logits,
                                           [task_ids[i] for i in validation], broadness[validation])
        history.append({"epoch": epoch, "validation": metrics})
        score = metrics["task_macro_cross_entropy"]
        if score < best_loss - 1e-8:
            best_loss = score
            best_epoch = epoch
            best_state = {name: tensor.detach().cpu().clone() for name, tensor in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= 10:
                break
    model.load_state_dict(best_state)
    model.eval()
    val_logits = predict(validation)
    validation_metrics = BASE._prediction_metrics(targets[validation], val_logits,
                                                  [task_ids[i] for i in validation], broadness[validation])
    torch.save({"architecture": "qdelta_skip_plus_relu_residual_v05_04", "input_dim": INPUT_DIM,
                "hidden_dim": HIDDEN, "normalization_mean": mean, "normalization_std": std,
                "baseline_beta": baseline_beta, "selected_epoch": best_epoch,
                "state_dict": model.cpu().state_dict(), "label_semantics": BASE.TARGET_SCHEMA},
               output / "proposal-v05-v04.pt")
    probabilities = np.exp(val_logits - np.logaddexp.reduce(val_logits, axis=1, keepdims=True))
    np.savez_compressed(output / "validation-predictions-v05-v04.npz",
                        logits=val_logits.astype(np.float32), probabilities=probabilities.astype(np.float32),
                        teacher_q=targets[validation], teacher_class_fraction=broadness[validation])
    return {"architecture": "qdelta_skip_plus_relu_residual_v05_04", "input_dim": INPUT_DIM,
            "base_input_dim": BASE_INPUT_DIM, "hidden_dim": HIDDEN,
            "normalization": "per-feature mean/std over train action rows only; direct qdelta skip",
            "optimizer": "AdamW", "learning_rate": 1e-3, "weight_decay": 1e-4,
            "batch_size_states": 16, "baseline_beta": baseline_beta, "initial_delta_gain": initial_gain,
            "selected_delta_gain": float(model.delta_gain.detach().cpu()),
            "frozen_qdelta_baseline": baseline_metrics,
            "selected_epoch": best_epoch, "epochs_run": len(history) - 1,
            "early_stop_patience": 10, "selection_metric": "validation task-macro teacher cross-entropy",
            "device": str(device), "validation": validation_metrics, "history": history,
            "weights_sha256": sha256_file(output / "proposal-v05-v04.pt")[0],
            "validation_predictions_sha256": sha256_file(output / "validation-predictions-v05-v04.npz")[0]}


def train(base_receipt_path: Path, delta_receipt_path: Path, qterminal_receipt_path: Path,
          qterminal_checkpoint_path: Path, output_dir: Path, *, seed: int, epochs: int,
          device: str) -> dict[str, Any]:
    base_path = base_receipt_path.resolve(strict=True)
    delta_path = delta_receipt_path.resolve(strict=True)
    qterm_path = qterminal_receipt_path.resolve(strict=True)
    checkpoint_path = qterminal_checkpoint_path.resolve(strict=True)
    output = output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite V05 proposal-fit v04 {output}")
    base_receipt = read_json(base_path)
    delta_receipt = read_json(delta_path)
    qterminal_receipt = read_json(qterm_path)
    if base_receipt.get("status") != "V05_TRAINVAL_PROPOSAL_FIT_V03_COMPLETE":
        raise ValueError("V04 requires a complete V03 train/validation proposal fit")
    if delta_receipt.get("status") != "TRAIN_VALIDATION_ACTION_DELTA_DIAGNOSTIC_COMPLETE":
        raise ValueError("V04 requires the completed train/validation Q-terminal delta diagnostic")
    for receipt in (base_receipt, qterminal_receipt):
        if (receipt.get("qualification_targets_generated") is not False
                or receipt.get("qualification_target_paths_or_hashes_recorded") is not False):
            raise ValueError("V04 input receipt declares qualification target contact")
    if (delta_receipt.get("qualification_labels_read") is not False
            or delta_receipt.get("qualification_target_paths_or_hashes_recorded") is not False
            or qterminal_receipt.get("qualification_labels_read") is not False
            or qterminal_receipt.get("qualification_rows") != 0):
        raise ValueError("V04 Q-terminal inputs are not train/validation-only")
    expected_diag_pins = {
        "view_receipt_sha256": base_receipt["inputs"]["view_receipt"]["sha256"],
        "features_receipt_sha256": base_receipt["inputs"]["feature_receipt"]["sha256"],
        "action_label_receipt_sha256": base_receipt["inputs"]["teacher_receipt"]["sha256"],
        "qterminal_fit_receipt_sha256": sha256_file(qterm_path)[0],
        "qterminal_checkpoint_sha256": sha256_file(checkpoint_path)[0],
    }
    for name, expected in expected_diag_pins.items():
        if delta_receipt.get("inputs", {}).get(name) != expected:
            raise ValueError(f"V04 Q-terminal diagnostic pin mismatch: {name}")
    if qterminal_receipt.get("checkpoint", {}).get("sha256") != expected_diag_pins["qterminal_checkpoint_sha256"]:
        raise ValueError("V04 Q-terminal fit receipt does not bind to the supplied checkpoint")
    if qterminal_receipt.get("qualification_targets_generated") is not False:
        raise ValueError("V04 Q-terminal checkpoint receipt declares qualification target generation")

    base_contract = base_receipt.get("contract", {})
    if (base_contract.get("feature_dim") != BASE_INPUT_DIM or base_contract.get("states") != 2560
            or base_contract.get("actions_per_state") != ACTION_COUNT
            or base_contract.get("train_states") != 2048 or base_contract.get("validation_states") != 512):
        raise ValueError("V04 V03 feature/target contract mismatch")
    matrix_record = base_receipt.get("action_feature_matrix", {})
    target_record = base_receipt.get("teacher_q_matrix", {})
    row_record = base_receipt.get("row_map", {})
    matrix_path = Path(matrix_record.get("path", "")).resolve(strict=True)
    target_path = Path(target_record.get("path", "")).resolve(strict=True)
    row_path = Path(row_record.get("path", "")).resolve(strict=True)
    for path, record, name in ((matrix_path, matrix_record, "V03 action features"),
                               (target_path, target_record, "V03 teacher matrix"),
                               (row_path, row_record, "V03 row map")):
        verify_recorded_file(path, record, name)
    if matrix_record["bytes"] != 80 * STATE_COUNT * ACTION_COUNT * BASE_INPUT_DIM * 4:
        raise ValueError("V04 V03 feature matrix byte count mismatch")
    with np.load(target_path, allow_pickle=False) as data:
        targets = np.asarray(data["teacher_q"], dtype=np.float32)
        broadness = np.asarray(data["teacher_class_fraction"], dtype=np.float32)
        task_ids = [str(value) for value in data["task_ids"].tolist()]
        splits = [str(value) for value in data["splits"].tolist()]
    row_map = read_jsonl(row_path)
    if (targets.shape != (2560, ACTION_COUNT) or broadness.shape != targets.shape
            or len(task_ids) != 2560 or len(splits) != 2560 or len(row_map) != 2560):
        raise ValueError("V04 V03 target/row-map shape mismatch")
    for index, row in enumerate(row_map):
        if (row.get("task_id") != task_ids[index] or row.get("split") != splits[index]
                or type(row.get("state_index")) is not int or not 0 <= row["state_index"] < STATE_COUNT):
            raise ValueError("V04 V03 target order differs from its row map")
    if not np.isfinite(targets).all() or not np.allclose(targets.sum(axis=1), 1.0, atol=1e-6, rtol=0.0):
        raise ValueError("V04 teacher target matrix contains invalid probability rows")

    delta_output = delta_receipt.get("outputs", {}).get("action-delta-predictions-trainval-v01.jsonl", {})
    delta_predictions_path = Path(delta_output.get("path", "")).resolve(strict=True)
    verify_recorded_file(delta_predictions_path, delta_output, "V266 action-delta predictions")
    delta_by_state: dict[tuple[str, int], dict[str, Any]] = {}
    for row in read_jsonl(delta_predictions_path):
        key = (str(row.get("task_id", "")), int(row.get("state_index", -1)))
        if key in delta_by_state:
            raise ValueError(f"duplicate V266 action-delta state {key}")
        delta_by_state[key] = row
    beta = float(delta_receipt["proposal_temperature_inverse_beta"])
    if not math.isfinite(beta) or beta <= 0.0:
        raise ValueError("V04 Q-terminal delta temperature is invalid")
    delta_matrix = np.empty((len(row_map), ACTION_COUNT), dtype=np.float32)
    for index, row in enumerate(row_map):
        key = (str(row["task_id"]), int(row["state_index"]))
        predicted = delta_by_state.get(key)
        if predicted is None or predicted.get("family_split") != row["split"]:
            raise ValueError(f"missing or split-mismatched V266 action-delta state {key}")
        q = np.asarray(predicted.get("teacher_q"), dtype=np.float32)
        delta = np.asarray(predicted.get("predicted_delta_satisfied"), dtype=np.float32)
        proposal = np.asarray(predicted.get("qterminal_delta_proposal"), dtype=np.float64)
        if (q.shape != (ACTION_COUNT,) or delta.shape != (ACTION_COUNT,) or proposal.shape != (ACTION_COUNT,)
                or not np.isfinite(delta).all() or not np.isfinite(proposal).all()):
            raise ValueError(f"invalid V266 action-delta row {key}")
        if not np.allclose(q, targets[index], atol=1e-7, rtol=0.0):
            raise ValueError(f"V266 teacher row does not match V03 target row {key}")
        logits = delta.astype(np.float64) * beta
        logits -= logits.max()
        replayed = np.exp(logits) / np.exp(logits).sum()
        if not np.allclose(replayed, proposal, atol=2e-6, rtol=2e-6):
            raise ValueError(f"V266 stored proposal does not replay from Q-delta and beta {key}")
        delta_matrix[index] = delta
    if len(delta_by_state) != len(row_map):
        raise ValueError("V266 action-delta roster contains unexpected states")

    output.mkdir(parents=True)
    delta_feature_path = output / "qterminal-delta-feature-v05-v04.f32.npy"
    np.save(delta_feature_path, delta_matrix, allow_pickle=False)
    base_matrix = np.memmap(matrix_path, dtype="<f4", mode="r",
                            shape=(2560 * ACTION_COUNT, BASE_INPUT_DIM))
    feature_view = AppendedDeltaFeatures(base_matrix, delta_matrix)
    fit_receipt = fit(feature_view, targets, broadness, task_ids, splits, seed=seed,
                      epochs=epochs, device_name=device, output=output, baseline_beta=beta)
    receipt = {
        "schema": "R1_STAGE1_V05_PROPOSAL_FIT_V04_QDELTA",
        "status": "V05_TRAINVAL_PROPOSAL_FIT_V04_QDELTA_COMPLETE",
        "fit_scope": "class-balanced one-step reachability teacher with frozen Q-terminal action-delta skip and learned residual",
        "analysis_mode": "adaptive engineering; validation checkpoint selection; Q-terminal was fit/selected on the same train/validation roster",
        "qualification_rows": 0, "qualification_targets_generated": False,
        "qualification_target_paths_or_hashes_recorded": False,
        "split_usage": {"train": "normalization and fit", "validation": "checkpoint selection only"},
        "run_config": {"seed": seed, "epoch_limit": epochs, "requested_device": device},
        "inputs": {"v03_fit_receipt": file_record(base_path), "v266_delta_receipt": file_record(delta_path),
                   "qterminal_fit_receipt": file_record(qterm_path), "qterminal_checkpoint": file_record(checkpoint_path),
                   "v03_action_features": file_record(matrix_path), "v03_teacher_matrix": file_record(target_path),
                   "v03_row_map": file_record(row_path), "v04_source": file_record(Path(__file__))},
        "contract": {"task_shape": {"n": N_ENTITIES, "k": N_ROLES}, "base_feature_dim": BASE_INPUT_DIM,
                     "feature_dim": INPUT_DIM, "feature_schema": "V03 assignment/edit/public-incidence/frozen-H features plus one Q-terminal predicted delta-satisfaction feature",
                     "states": len(row_map), "states_per_task": STATE_COUNT, "actions_per_state": ACTION_COUNT,
                     "train_states": splits.count("train"), "validation_states": splits.count("validation"),
                     "teacher_target": BASE.TARGET_SCHEMA, "qterminal_skip_beta": beta},
        "fit": fit_receipt, "qterminal_delta_feature": file_record(delta_feature_path),
    }
    receipt_path = output / "proposal-fit-receipt-v05-v04.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v03-receipt", type=Path, required=True)
    parser.add_argument("--delta-receipt", type=Path, required=True)
    parser.add_argument("--qterminal-receipt", type=Path, required=True)
    parser.add_argument("--qterminal-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=71029)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--device", default="cuda" if __import__("torch").cuda.is_available() else "cpu")
    args = parser.parse_args()
    output = args.output.resolve()
    output_existed = output.exists()
    try:
        receipt = train(args.v03_receipt, args.delta_receipt, args.qterminal_receipt,
                        args.qterminal_checkpoint, output, seed=args.seed, epochs=args.epochs,
                        device=args.device)
    except Exception as error:
        if not output_existed:
            output.mkdir(parents=True, exist_ok=True)
        if not output_existed and output.is_dir() and not (output / "proposal-fit-receipt-v05-v04.json").exists() and not (output / "failure.json").exists():
            failure = {"schema": "R1_STAGE1_ATTEMPT_FAILURE_V01", "status": "V05_PROPOSAL_FIT_V04_QDELTA_FAILED",
                       "phase": "trainval_qterminal_delta_residual_fit", "error_type": type(error).__name__,
                       "error": str(error), "source": file_record(Path(__file__))}
            (output / "failure.json").write_text(json.dumps(failure, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise
    print(f"R1_V05_PROPOSAL_FIT_V04_QDELTA_COMPLETE val_task_macro_ce={receipt['fit']['validation']['task_macro_cross_entropy']:.4f} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
