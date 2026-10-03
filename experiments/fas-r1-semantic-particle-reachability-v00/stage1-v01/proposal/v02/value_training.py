"""V_reach fitting, transfer, and calibration metrics for proposal v02."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


class ValueModel:
    def __init__(self, torch: Any, input_dim: int):
        import torch.nn as nn

        self.network = nn.Sequential(nn.Linear(input_dim, 32), nn.Tanh(), nn.Linear(32, 1))
        self.torch = torch


def load_v01_value(model: ValueModel, path: Path) -> None:
    blob = json.loads(path.read_text(encoding="utf-8"))
    if blob.get("schema") != "r1-v-reach-weights-v01" or int(blob["input_dim"]) != model.network[0].in_features:
        raise ValueError("frozen v01 V_reach architecture does not match v02 value features")
    torch = model.torch
    with torch.no_grad():
        model.network[0].weight.copy_(torch.as_tensor(blob["w1"], dtype=torch.float32))
        model.network[0].bias.copy_(torch.as_tensor(blob["b1"], dtype=torch.float32))
        model.network[2].weight.copy_(torch.as_tensor(blob["w2"], dtype=torch.float32).reshape(1, -1))
        model.network[2].bias.copy_(torch.as_tensor([blob["b2"]], dtype=torch.float32))


def binary_metrics(prob: np.ndarray, target: np.ndarray) -> dict[str, float]:
    epsilon = 1e-7
    clipped = np.clip(prob, epsilon, 1.0 - epsilon)
    order = np.argsort(prob, kind="mergesort")
    sorted_prob = prob[order]
    sorted_target = target[order]
    positive_total = float(sorted_target.sum())
    negative_total = float((1.0 - sorted_target).sum())
    concordance = 0.0
    negatives_before = 0.0
    begin = 0
    while begin < len(order):
        end = begin + 1
        while end < len(order) and sorted_prob[end] == sorted_prob[begin]:
            end += 1
        group_pos = float(sorted_target[begin:end].sum())
        group_neg = float((1.0 - sorted_target[begin:end]).sum())
        concordance += group_pos * (negatives_before + 0.5 * group_neg)
        negatives_before += group_neg
        begin = end
    auc = concordance / (positive_total * negative_total) if positive_total and negative_total else float("nan")
    ece = 0.0
    for indices in np.array_split(np.argsort(prob, kind="mergesort"), min(10, max(1, len(prob)))):
        if len(indices):
            ece += len(indices) / len(prob) * abs(float(prob[indices].mean() - target[indices].mean()))
    return {
        "count": int(len(target)),
        "positive_rate": float(target.mean()),
        "brier": float(np.mean((prob - target) ** 2)),
        "binary_cross_entropy": float(-np.mean(target * np.log(clipped) + (1 - target) * np.log(1 - clipped))),
        "roc_auc_fractional_targets": float(auc),
        "expected_calibration_error_10_equal_mass_bins": float(ece),
        "mean_forecast": float(prob.mean()),
        "accuracy_at_0_5": float(np.mean((prob >= 0.5) == (target >= 0.5))),
    }


def predict_value(model: ValueModel, x: np.ndarray, device: Any) -> np.ndarray:
    torch = model.torch
    model.network.eval()
    with torch.no_grad():
        tensor = torch.as_tensor(x, dtype=torch.float32, device=device)
        return torch.sigmoid(model.network(tensor).squeeze(-1)).cpu().numpy()


def fit_value(
    x: np.ndarray,
    y: np.ndarray,
    splits: np.ndarray,
    v01_path: Path,
    seed: int,
    epochs: int,
    torch: Any,
    device: Any,
) -> tuple[ValueModel, list[dict[str, Any]]]:
    train_ids = np.flatnonzero(splits == "train")
    val_ids = np.flatnonzero(splits == "validation")
    if not len(train_ids) or not len(val_ids):
        raise ValueError("V_reach requires train and validation rows")
    torch.manual_seed(seed + 1)
    model = ValueModel(torch, x.shape[1])
    load_v01_value(model, v01_path)
    model.network.to(device)
    optimizer = torch.optim.AdamW(model.network.parameters(), lr=3e-4, weight_decay=1e-4)
    tensor_x = torch.as_tensor(x, dtype=torch.float32)
    tensor_y = torch.as_tensor(y, dtype=torch.float32)
    generator = torch.Generator(device="cpu").manual_seed(seed + 1)
    best_state = None
    best_loss = float("inf")
    best_epoch = 0
    stale = 0
    history = []
    for epoch in range(1, epochs + 1):
        model.network.train()
        order = torch.randperm(len(train_ids), generator=generator).numpy()
        for start in range(0, len(order), 512):
            batch_ids = train_ids[order[start : start + 512]]
            bx = tensor_x[torch.as_tensor(batch_ids)].to(device)
            by = tensor_y[torch.as_tensor(batch_ids)].to(device)
            logits = model.network(bx).squeeze(-1)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, by)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        val_prob = predict_value(model, x[val_ids], device)
        metrics = binary_metrics(val_prob, y[val_ids])
        history.append({"epoch": epoch, **metrics})
        if metrics["binary_cross_entropy"] < best_loss - 1e-8:
            best_loss = metrics["binary_cross_entropy"]
            best_epoch = epoch
            best_state = {key: value.detach().cpu().clone() for key, value in model.network.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= 7:
                break
    if best_state is None:
        raise RuntimeError("V_reach fitting produced no validation-selected checkpoint")
    model.network.load_state_dict(best_state)
    history.append({"selected_epoch": best_epoch, "early_stopping_patience": 7})
    return model, history


def export_value(model: ValueModel, max_budget: int, output: Path) -> str:
    state = model.network.state_dict()
    blob = {
        "schema": "r1-v-reach-weights-v02",
        "architecture": "tanh_mlp_value_4345_h32_v02",
        "input_dim": int(state["0.weight"].shape[1]),
        "hidden_dim": 32,
        "budget_normalization_max": max_budget,
        "feature_schema": "r1-value-input-h-global-meanH-assignment-latent-budget-v01",
        "initialization": "frozen-v01-checkpoint-then-train-on-short-horizon-proposal-trajectory-states",
        "w1": state["0.weight"].detach().cpu().numpy().astype(np.float32).tolist(),
        "b1": state["0.bias"].detach().cpu().numpy().astype(np.float32).tolist(),
        "w2": state["2.weight"].detach().cpu().numpy().reshape(-1).astype(np.float32).tolist(),
        "b2": float(state["2.bias"].detach().cpu().numpy().reshape(())),
    }
    raw = json.dumps(blob, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    output.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()
