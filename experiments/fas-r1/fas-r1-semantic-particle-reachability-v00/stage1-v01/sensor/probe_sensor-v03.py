#!/usr/bin/env python3
"""Fit and report the frozen-feature R1 sensor qualification ladder."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn


KINDS = ["different", "exactly_one_role", "fixed_role", "forbidden_role", "implies_not_role", "same"]
KIND_TO_ID = {name: index for index, name in enumerate(KINDS)}
SIGNS = [-1, 0, 1]
SIGN_TO_ID = {name: index for index, name in enumerate(SIGNS)}
EXPECTED_SUPPORT_SHA256 = "b05e99f83cec97342582dbacec0a3c7ba0bf634130f301dd909a886bcbb66e46"
EXPECTED_PROBE_MANIFEST_SHA256 = "58ec8d28565169d2a04816c97ef7406bfd6f30b68eae0d3f10ac65e692a8b811"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def metric_f1(y: np.ndarray, pred: np.ndarray, labels: list[int]) -> dict[str, Any]:
    per_class: dict[str, float] = {}
    for label in labels:
        tp = int(np.sum((y == label) & (pred == label)))
        fp = int(np.sum((y != label) & (pred == label)))
        fn = int(np.sum((y == label) & (pred != label)))
        den = 2 * tp + fp + fn
        per_class[str(label)] = (2.0 * tp / den) if den else 0.0
    return {"macro_f1": float(np.mean(list(per_class.values()))), "per_class_f1": per_class}


def balanced_accuracy(y: np.ndarray, pred: np.ndarray, class_count: int) -> float:
    recalls = []
    for label in range(class_count):
        mask = y == label
        if mask.any():
            recalls.append(float(np.mean(pred[mask] == label)))
    return float(np.mean(recalls)) if recalls else 0.0


def normalization(train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = np.mean(train, axis=0, dtype=np.float64).astype(np.float32)
    std = np.std(train, axis=0, dtype=np.float64).astype(np.float32)
    std[std < 1.0e-6] = 1.0
    return mean, std


def class_weights(y: np.ndarray, count: int, device: torch.device) -> torch.Tensor:
    freq = np.bincount(y, minlength=count).astype(np.float64)
    weights = np.zeros(count, dtype=np.float32)
    present = freq > 0
    weights[present] = float(len(y)) / (int(present.sum()) * freq[present])
    return torch.as_tensor(weights, device=device)


def batch_rows(array: np.ndarray, ids: np.ndarray, device: torch.device) -> torch.Tensor:
    return torch.as_tensor(np.asarray(array[ids], dtype=np.float32), device=device)


def fit_classifier(
    features: np.ndarray,
    targets: np.ndarray,
    train_idx: np.ndarray,
    validation_idx: np.ndarray,
    *,
    classes: int,
    hidden: int,
    batch_size: int,
    max_epochs: int,
    patience: int,
    learning_rate: float,
    weight_decay: float,
    device: torch.device,
    selection: str,
) -> tuple[nn.Module, dict[str, Any]]:
    x_train, x_validation = features[train_idx], features[validation_idx]
    y_train, y_validation = targets[train_idx], targets[validation_idx]
    mean, std = normalization(x_train)
    x_train = ((x_train - mean) / std).astype(np.float32, copy=False)
    x_validation = ((x_validation - mean) / std).astype(np.float32, copy=False)
    if hidden:
        model: nn.Module = nn.Sequential(nn.Linear(features.shape[1], hidden), nn.ReLU(), nn.Linear(hidden, classes)).to(device)
    else:
        model = nn.Linear(features.shape[1], classes).to(device)
    weights = class_weights(y_train, classes, device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    generator = torch.Generator(device="cpu").manual_seed(71026)
    best_score, best_epoch, stale = -math.inf, 0, 0
    best_state: dict[str, torch.Tensor] | None = None
    history: list[dict[str, float]] = []
    for epoch in range(1, max_epochs + 1):
        model.train()
        order = torch.randperm(len(train_idx), generator=generator).numpy()
        for offset in range(0, len(order), batch_size):
            local = order[offset : offset + batch_size]
            xb = torch.as_tensor(x_train[local], device=device)
            yb = torch.as_tensor(y_train[local].astype(np.int64, copy=False), device=device)
            optimizer.zero_grad(set_to_none=True)
            loss = nn.functional.cross_entropy(model(xb), yb, weight=weights)
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            logits = np.concatenate(
                [model(torch.as_tensor(x_validation[i : i + batch_size], device=device)).cpu().numpy()
                 for i in range(0, len(x_validation), batch_size)], axis=0
            )
        pred = np.argmax(logits, axis=1)
        if selection == "balanced_accuracy":
            score = balanced_accuracy(y_validation, pred, classes)
        elif selection == "macro_f1":
            score = metric_f1(y_validation, pred, list(range(classes)))["macro_f1"]
        else:
            raise ValueError(f"unknown selection metric {selection}")
        history.append({"epoch": float(epoch), "validation_score": float(score)})
        if score > best_score + 1.0e-8:
            best_score, best_epoch, stale = score, epoch, 0
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        else:
            stale += 1
            if stale >= patience:
                break
    assert best_state is not None
    model.load_state_dict(best_state)
    return model, {
        "best_epoch": best_epoch,
        "best_validation_score": float(best_score),
        "epochs_run": len(history),
        "history": history,
        "normalization_mean": mean,
        "normalization_std": std,
    }


def predict(model: nn.Module, features: np.ndarray, device: torch.device, batch_size: int = 1024) -> np.ndarray:
    model.eval()
    output: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(features), batch_size):
            batch = torch.as_tensor(features[start : start + batch_size], dtype=torch.float32, device=device)
            output.append(model(batch).cpu().numpy())
    return np.concatenate(output, axis=0)


def tune_binary_threshold(y: np.ndarray, probability: np.ndarray, allowed: np.ndarray) -> float:
    choices = np.arange(0.10, 0.901, 0.05)
    scored = []
    for threshold in choices:
        pred = (probability >= threshold) & allowed
        truth = (y > 0) & allowed
        tp = int(np.sum(pred & truth))
        fp = int(np.sum(pred & ~truth))
        fn = int(np.sum(~pred & truth))
        denom = 2 * tp + fp + fn
        f1 = (2 * tp / denom) if denom else 0.0
        scored.append((f1, -abs(float(threshold) - 0.50), float(threshold)))
    scored.sort(reverse=True)
    return scored[0][2]


def binding_scores(logits: np.ndarray, y: np.ndarray, n_values: np.ndarray, k_values: np.ndarray,
                   thresholds: tuple[float, float] | None = None) -> tuple[dict[str, float], tuple[float, float]]:
    prob = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
    entity_mask = np.arange(16)[None, :] < n_values[:, None]
    entity_mask[:, 12:] = False
    role_mask = np.zeros((len(y), 16), dtype=bool)
    for idx, kval in enumerate(k_values):
        role_mask[idx, 12 : 12 + int(kval)] = True
    if thresholds is None:
        thresholds = (
            tune_binary_threshold(y[:, :12], prob[:, :12], entity_mask[:, :12]),
            tune_binary_threshold(y[:, 12:], prob[:, 12:], role_mask[:, 12:]),
        )
    pred_entity = (prob[:, :12] >= thresholds[0]) & entity_mask[:, :12]
    true_entity = (y[:, :12] > 0) & entity_mask[:, :12]
    pred_role = (prob[:, 12:] >= thresholds[1]) & role_mask[:, 12:]
    true_role = (y[:, 12:] > 0) & role_mask[:, 12:]

    def f1(pred: np.ndarray, truth: np.ndarray) -> float:
        tp = int(np.sum(pred & truth))
        fp = int(np.sum(pred & ~truth))
        fn = int(np.sum(~pred & truth))
        return (2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) else 0.0

    entity = f1(pred_entity, true_entity)
    role = f1(pred_role, true_role)
    return {"entity_micro_f1": entity, "role_micro_f1": role, "combined_f1": (entity + role) / 2}, thresholds


def fit_binding(features: np.ndarray, targets: np.ndarray, ns: np.ndarray, ks: np.ndarray,
                splits: np.ndarray, device: torch.device, output: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    cfg = manifest["binding"]
    train_idx, val_idx, qual_idx = (np.flatnonzero(splits == name) for name in ("train", "validation", "qualification"))
    mean, std = normalization(features[train_idx])
    x = ((features - mean) / std).astype(np.float32, copy=False)
    y_train = targets[train_idx]
    positive = np.sum(y_train > 0, axis=0).astype(np.float64)
    allowed_train = np.zeros_like(y_train, dtype=bool)
    for row, i in enumerate(train_idx):
        allowed_train[row, : int(ns[i])] = True
        allowed_train[row, 12 : 12 + int(ks[i])] = True
    negative = np.sum(allowed_train & (y_train == 0), axis=0).astype(np.float64)
    pos_weight = np.ones(16, dtype=np.float32)
    for col in range(16):
        if positive[col] > 0:
            pos_weight[col] = min(20.0, negative[col] / positive[col])
    model = nn.Linear(features.shape[1], 16).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
    pw = torch.as_tensor(pos_weight, device=device)
    generator = torch.Generator(device="cpu").manual_seed(manifest["seed"])
    best, best_epoch, stale, best_state, best_threshold = -1.0, 0, 0, None, (0.5, 0.5)
    history = []
    for epoch in range(1, cfg["max_epochs"] + 1):
        model.train()
        order = torch.randperm(len(train_idx), generator=generator).numpy()
        for offset in range(0, len(order), cfg["batch_size"]):
            local = order[offset : offset + cfg["batch_size"]]
            actual = train_idx[local]
            xb = torch.as_tensor(x[actual], device=device)
            yb = torch.as_tensor(targets[actual], device=device)
            mask = torch.zeros_like(yb)
            for i, row in enumerate(actual):
                mask[i, : int(ns[row])] = 1.0
                mask[i, 12 : 12 + int(ks[row])] = 1.0
            optimizer.zero_grad(set_to_none=True)
            losses = nn.functional.binary_cross_entropy_with_logits(model(xb), yb, pos_weight=pw, reduction="none")
            loss = (losses * mask).sum() / mask.sum().clamp_min(1.0)
            loss.backward()
            optimizer.step()
        val_logits = predict(model, x[val_idx], device)
        scores, thresholds = binding_scores(val_logits, targets[val_idx], ns[val_idx], ks[val_idx])
        score = scores["combined_f1"]
        history.append({"epoch": epoch, **scores, "entity_threshold": thresholds[0], "role_threshold": thresholds[1]})
        if score > best + 1.0e-8:
            best, best_epoch, stale, best_threshold = score, epoch, 0, thresholds
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        else:
            stale += 1
            if stale >= cfg["early_stop_patience"]:
                break
    assert best_state is not None
    model.load_state_dict(best_state)
    val_result, val_threshold = binding_scores(predict(model, x[val_idx], device), targets[val_idx], ns[val_idx], ks[val_idx])
    qual_result, _ = binding_scores(predict(model, x[qual_idx], device), targets[qual_idx], ns[qual_idx], ks[qual_idx], val_threshold)
    torch.save({"state_dict": model.state_dict(), "mean": mean, "std": std, "thresholds": val_threshold}, output / "binding.pt")
    return {"status": "REPORTED_ONCE", "best_epoch": best_epoch, "epochs_run": len(history),
            "validation": val_result, "qualification": qual_result,
            "validation_thresholds": {"entity": val_threshold[0], "role": val_threshold[1]},
            "history": history, "gate": cfg["qualification_gate"]}


def make_action_features(rows: list[dict[str, Any]], actions: list[dict[str, Any]], tasks: list[dict[str, Any]],
                         h: np.ndarray, global_h: np.ndarray, clauses: list[dict[str, Any]], output: Path,
                         dims: int) -> tuple[np.memmap, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    row_by_task: dict[int, list[int]] = {}
    for row in rows:
        if row["kind"] == "constraint":
            row_by_task.setdefault(int(row["task_index"]), []).append(int(row["row"]))
    label_clause: dict[tuple[int, int], dict[str, Any]] = {(int(c["task_index"]), int(c["clause_index"])): c for c in clauses}
    task_by_index = {i: task for i, task in enumerate(tasks)}
    n_actions = len(actions)
    matrix_path = output / "action_features.f32.mmap"
    matrix = np.memmap(matrix_path, dtype="<f4", mode="w+", shape=(n_actions, dims))
    labels = np.empty(n_actions, dtype=np.int8)
    ns = np.empty(n_actions, dtype=np.int16)
    ks = np.empty(n_actions, dtype=np.int16)
    splits = np.empty(n_actions, dtype="U16")
    cache: dict[int, tuple[np.ndarray, np.ndarray, list[list[int]], list[list[int]], list[int]]] = {}
    for index, action in enumerate(actions):
        ti = int(action["task_index"])
        task = task_by_index[ti]
        n, k = int(task["n"]), int(task["k"])
        if ti not in cache:
            public_rows = row_by_task.get(ti, [])
            all_mean = (np.mean(h[public_rows], axis=0, dtype=np.float64).astype(np.float32)
                        if public_rows else np.zeros(h.shape[1], dtype=np.float32))
            entity_mentions = task["entity_mentions"]
            role_mentions = task["role_mentions"]
            by_entity = np.zeros((12, h.shape[1]), dtype=np.float32)
            entity_clause_rows: list[list[int]] = [[] for _ in range(12)]
            templates: list[int] = []
            for ci, row_id in enumerate(public_rows):
                lab = label_clause[(ti, ci)]
                templates.append(int(lab["template_id"]))
                for entity in entity_mentions[ci]:
                    entity_clause_rows[int(entity)].append(row_id)
            for ent, incident in enumerate(entity_clause_rows):
                if incident:
                    by_entity[ent] = np.mean(h[incident], axis=0, dtype=np.float64).astype(np.float32)
            cache[ti] = (all_mean, by_entity, entity_mentions, role_mentions, templates)
        all_mean, by_entity, entity_mentions, role_mentions, templates = cache[ti]
        assignment = action["assignment"]
        edit = action["edit"]
        entity, old, new = int(edit["entity"]), int(edit["from_role"]), int(edit["to_role"])
        affected = [ci for ci, ids in enumerate(entity_mentions) if entity in ids]
        role_counts = np.zeros(4, dtype=np.float32)
        entity_counts = np.zeros(12, dtype=np.float32)
        for ci in affected:
            for role in role_mentions[ci]:
                role_counts[int(role)] += 1.0
            for ent in entity_mentions[ci]:
                entity_counts[int(ent)] += 1.0
        assignment_onehot = np.zeros(48, dtype=np.float32)
        for ent, role in enumerate(assignment):
            assignment_onehot[ent * 4 + int(role)] = 1.0
        edit_onehot = np.zeros(192, dtype=np.float32)
        edit_onehot[(entity * 4 + old) * 4 + new] = 1.0
        incident_mean = by_entity[entity]
        common = np.concatenate([assignment_onehot, edit_onehot, entity_counts / max(1, len(entity_mentions)),
                                 role_counts / max(1, len(affected)),
                                 np.asarray([n / 12.0, k / 4.0, len(affected) / max(1, len(entity_mentions))], dtype=np.float32)])
        primary = np.concatenate([common, global_h[ti], all_mean, incident_mean])
        if len(primary) != dims:
            raise ValueError(f"action feature length {len(primary)} != manifest {dims}")
        matrix[index] = primary
        labels[index] = int(action["sign_delta"])
        ns[index], ks[index], splits[index] = n, k, action["split"]
    matrix.flush()
    return matrix, labels, ns, ks, splits


def masked_action_control(common: np.ndarray, actions: list[dict[str, Any]], template_ids: np.ndarray,
                          tasks: list[dict[str, Any]], include_templates: bool) -> np.ndarray:
    extra = np.zeros((len(actions), 4), dtype=np.float32) if include_templates else np.zeros((len(actions), 0), dtype=np.float32)
    if include_templates:
        template_ids = template_ids.astype(np.int64)
        for i, action in enumerate(actions):
            ti, entity = int(action["task_index"]), int(action["edit"]["entity"])
            task_templates = template_ids[ti]
            for templ in (0, 1):
                extra[i, templ] = np.sum(task_templates == templ)
                extra[i, 2 + templ] = np.sum((task_templates == templ) & (entity >= 0))
    return np.concatenate([common, extra], axis=1)


def fit_action_matrix(features: np.ndarray, labels: np.ndarray, splits: np.ndarray, cfg: dict[str, Any],
                      device: torch.device, output: Path, stem: str) -> dict[str, Any]:
    train_idx, val_idx, qual_idx = (np.flatnonzero(splits == name) for name in ("train", "validation", "qualification"))
    model, fit = fit_classifier(features, labels, train_idx, val_idx, classes=3, hidden=128,
        batch_size=cfg["batch_size"], max_epochs=cfg["max_epochs"], patience=cfg["early_stop_patience"],
        learning_rate=cfg["learning_rate"], weight_decay=cfg["weight_decay"], device=device, selection="macro_f1")
    mean, std = fit.pop("normalization_mean"), fit.pop("normalization_std")
    val_x = ((features[val_idx] - mean) / std).astype(np.float32, copy=False)
    qual_x = ((features[qual_idx] - mean) / std).astype(np.float32, copy=False)
    val_pred = np.argmax(predict(model, val_x, device), axis=1)
    qual_pred = np.argmax(predict(model, qual_x, device), axis=1)
    val_metrics = metric_f1(labels[val_idx], val_pred, [0, 1, 2])
    qual_metrics = metric_f1(labels[qual_idx], qual_pred, [0, 1, 2])
    val_metrics["per_class_f1"] = {str(SIGNS[int(key)]): value for key, value in val_metrics["per_class_f1"].items()}
    qual_metrics["per_class_f1"] = {str(SIGNS[int(key)]): value for key, value in qual_metrics["per_class_f1"].items()}
    result = {"status": "REPORTED_ONCE", "best_epoch": fit["best_epoch"], "epochs_run": fit["epochs_run"],
              "validation": val_metrics,
              "qualification": qual_metrics,
              "gate": cfg["qualification_gate"]}
    torch.save({"state_dict": model.state_dict(), "mean": mean, "std": std}, output / f"{stem}.pt")
    return result


def run(args: argparse.Namespace) -> None:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    manifest_path = Path(args.probe_manifest)
    support_path = Path(args.support_manifest)
    extraction = Path(args.extraction)
    labels_dir = Path(args.labels)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    support = json.loads(support_path.read_text(encoding="utf-8"))
    if manifest["manifest"] != "FAS-R1-SENSOR-PROBE-FIT-v02":
        raise ValueError("unexpected probe manifest")
    if sha256(manifest_path) != EXPECTED_PROBE_MANIFEST_SHA256:
        raise ValueError("probe manifest digest differs from the frozen v01 artifact")
    if sha256(support_path) != EXPECTED_SUPPORT_SHA256:
        raise ValueError("support manifest digest differs from the frozen v02 artifact")
    torch.set_num_threads(args.torch_threads)
    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available() else args.device)
    if args.device == "auto" and not torch.cuda.is_available():
        device = torch.device("cpu")
    seed_all(manifest["seed"])
    manifest_receipt = {
        "status": "RUNNING", "probe_manifest_sha256": sha256(manifest_path),
        "support_manifest_sha256": sha256(support_path),
        "extraction_receipt_sha256": sha256(extraction / "receipt.json"),
        "input_hashes": {name: sha256(labels_dir / name) for name in
                         ("private-clause-labels.jsonl", "private-action-labels.jsonl")},
        "device": str(device), "torch": torch.__version__, "numpy": np.__version__,
        "implementation_sha256": sha256(Path(__file__)),
        "qualification_evaluation": "adaptive engineering retest; same partition was reported under probe v01",
    }
    (output / "run-receipt.json").write_text(json.dumps(manifest_receipt, indent=2) + "\n", encoding="utf-8")
    tasks = read_jsonl(Path(args.public_tasks))
    rows = read_jsonl(extraction / "rows.jsonl")
    clause_labels = read_jsonl(labels_dir / "private-clause-labels.jsonl")
    action_labels = read_jsonl(labels_dir / "private-action-labels.jsonl")
    h = np.load(extraction / "constraint_H.float32.npy", mmap_mode="r")
    global_h = np.load(extraction / "global_h.float32.npy", mmap_mode="r")
    if h.shape != (872, 2048) or global_h.shape != (96, 2048):
        raise ValueError(f"unexpected frozen feature dimensions {h.shape}, {global_h.shape}")
    expected_public_hash = support["source"]["sha256"]
    if sha256(Path(args.public_tasks)) != expected_public_hash:
        raise ValueError("public input does not match the frozen support manifest")
    extraction_receipt = json.loads((extraction / "receipt.json").read_text(encoding="utf-8"))
    if extraction_receipt["input"]["sha256"] != expected_public_hash:
        raise ValueError("frozen extraction receipt does not identify the support input")
    if extraction_receipt["input"]["support_manifest"]["sha256"] != EXPECTED_SUPPORT_SHA256:
        raise ValueError("extraction receipt does not identify the frozen support manifest")
    for output_file in extraction_receipt["output_files"]:
        output_path = extraction / output_file["path"]
        if output_path.stat().st_size != int(output_file["bytes"]) or sha256(output_path) != output_file["sha256"]:
            raise ValueError(f"extraction output failed receipt validation: {output_file['path']}")
    label_summary = json.loads((labels_dir / "support-summary.json").read_text(encoding="utf-8"))
    if label_summary["support_manifest_sha256"] != EXPECTED_SUPPORT_SHA256:
        raise ValueError("offline labels identify a different support manifest")
    if label_summary["public_input_sha256"] != expected_public_hash:
        raise ValueError("offline labels identify a different public input")
    for name, key in (("private-clause-labels.jsonl", "clause_labels_sha256"),
                      ("private-action-labels.jsonl", "action_labels_sha256")):
        if sha256(labels_dir / name) != label_summary[key]:
            raise ValueError(f"offline label file failed support summary validation: {name}")
    if len(tasks) != 96 or len(clause_labels) != len(h) or len(action_labels) != 55008:
        raise ValueError("support roster mismatch")
    expected_split = {entry["task_id"]: entry["split"] for entry in support["family_roster"]}
    if any(task["id"] not in expected_split for task in tasks):
        raise ValueError("public task roster differs from frozen support roster")
    if any(row["split"] != expected_split[row["task_id"]] for row in rows):
        raise ValueError("extraction rows differ from frozen family split")
    if any(row["split"] != expected_split[row["task_id"]] for row in clause_labels):
        raise ValueError("clause labels differ from frozen family split")
    if any(row["split"] != expected_split[row["task_id"]] for row in action_labels):
        raise ValueError("action labels differ from frozen family split")
    qualifying = [row for row in action_labels if row["split"] == "qualification"]
    minimum = support["action_relevance_support"]["qualification_minimum"]
    for sign in SIGNS:
        selected = [row for row in qualifying if int(row["sign_delta"]) == sign]
        family_count = len({row["family_id"] for row in selected})
        if len(selected) < int(minimum["examples_per_sign_class"]):
            raise ValueError(f"qualification action support below floor for sign {sign}")
        if family_count < int(minimum["distinct_qualification_families_per_sign_class"]):
            raise ValueError(f"qualification family support below floor for sign {sign}")
    splits_clause = np.asarray([row["split"] for row in clause_labels], dtype="U16")

    # Identity rung: one affine head on the constraint vector.
    clause_rows = np.asarray([int(row["constraint_row"]) for row in clause_labels], dtype=np.int64)
    id_x = np.asarray(h[clause_rows], dtype=np.float32)
    id_y = np.asarray([KIND_TO_ID[row["clause_kind"]] for row in clause_labels], dtype=np.int64)
    clause_splits = splits_clause
    id_train, id_val, id_qual = (np.flatnonzero(clause_splits == name) for name in ("train", "validation", "qualification"))
    identity_model, identity_fit = fit_classifier(id_x, id_y, id_train, id_val, classes=6, hidden=0,
        batch_size=128, max_epochs=300, patience=35, learning_rate=0.03, weight_decay=1.0e-4,
        device=device, selection="balanced_accuracy")
    id_mean, id_std = identity_fit.pop("normalization_mean"), identity_fit.pop("normalization_std")
    id_val_pred = np.argmax(predict(identity_model, ((id_x[id_val] - id_mean) / id_std).astype(np.float32), device), axis=1)
    id_qual_pred = np.argmax(predict(identity_model, ((id_x[id_qual] - id_mean) / id_std).astype(np.float32), device), axis=1)
    id_result = {"best_epoch": identity_fit["best_epoch"], "epochs_run": identity_fit["epochs_run"],
        "validation_balanced_accuracy": balanced_accuracy(id_y[id_val], id_val_pred, 6),
        "qualification_balanced_accuracy": balanced_accuracy(id_y[id_qual], id_qual_pred, 6),
        "qualification_gate": manifest["identity"]["qualification_metric"] + " >= 0.90"}
    template_by_clause = np.asarray([int(row["template_id"]) for row in clause_labels], dtype=np.int8)
    class_by_template: dict[int, int] = {}
    for template in (0, 1):
        ids = id_train[template_by_clause[id_train] == template]
        counts = np.bincount(id_y[ids], minlength=6)
        class_by_template[template] = int(np.argmax(counts))
    template_pred = np.asarray([class_by_template[int(template_by_clause[i])] for i in id_qual])
    id_result["template_only_qualification_balanced_accuracy"] = balanced_accuracy(id_y[id_qual], template_pred, 6)
    torch.save({"state_dict": identity_model.state_dict(), "mean": id_mean, "std": id_std}, output / "identity.pt")

    # Binding rung: mention IDs only, with valid-ID masking at loss and scoring.
    binding_x = np.empty((len(clause_labels), 4098), dtype=np.float32)
    binding_y = np.zeros((len(clause_labels), 16), dtype=np.float32)
    clause_task = np.empty(len(clause_labels), dtype=np.int64)
    for i, label in enumerate(clause_labels):
        task = tasks[int(label["task_index"])]
        row = int(label["constraint_row"])
        binding_x[i, :2048] = h[row]
        binding_x[i, 2048:4096] = global_h[int(label["task_index"])]
        binding_x[i, 4096:] = (int(task["n"]) / 12.0, int(task["k"]) / 4.0)
        binding_y[i, np.asarray(label["entity_ids"], dtype=np.int64)] = 1.0
        binding_y[i, 12 + np.asarray(label["role_ids"], dtype=np.int64)] = 1.0
        clause_task[i] = int(label["task_index"])
    # v01 contract is H + h_global + n/12 + k/4: 4098 dimensions.
    ns_clause = np.asarray([int(tasks[i]["n"]) for i in clause_task], dtype=np.int16)
    ks_clause = np.asarray([int(tasks[i]["k"]) for i in clause_task], dtype=np.int16)
    bind_result = fit_binding(binding_x, binding_y, ns_clause, ks_clause, clause_splits, device, output, manifest)

    # Action relevance rung: materialize the 6391-D feature matrix as a disk-backed memmap.
    action_matrix, action_y_sign, ns_action, ks_action, action_splits = make_action_features(
        rows, action_labels, tasks, h, global_h, clause_labels, output, manifest["action_relevance"]["primary_feature_dimensions"])
    action_y = np.asarray([SIGN_TO_ID[int(value)] for value in action_y_sign], dtype=np.int64)
    action_cfg = manifest["action_relevance"]
    action_result = fit_action_matrix(action_matrix, action_y, action_splits, action_cfg, device, output, "action-primary")

    # Shortcut controls: public incidence and assignments only; template metadata is a separate stronger control.
    control_base = np.zeros((len(action_labels), 259), dtype=np.float32)
    template_matrix = np.zeros((len(tasks), max(len(task["clauses"]) for task in tasks)), dtype=np.int8)
    for clause in clause_labels:
        template_matrix[int(clause["task_index"]), int(clause["clause_index"])] = int(clause["template_id"])
    for i, action in enumerate(action_labels):
        task = tasks[int(action["task_index"])]
        entity, old, new = int(action["edit"]["entity"]), int(action["edit"]["from_role"]), int(action["edit"]["to_role"])
        assignment_onehot = np.zeros(48, dtype=np.float32)
        for ent, role in enumerate(action["assignment"]):
            assignment_onehot[ent * 4 + int(role)] = 1.0
        edit_onehot = np.zeros(192, dtype=np.float32)
        edit_onehot[(entity * 4 + old) * 4 + new] = 1.0
        ents = task["entity_mentions"]
        roles = task["role_mentions"]
        affected = [ci for ci, values in enumerate(ents) if entity in values]
        entity_counts = np.zeros(12, dtype=np.float32)
        role_counts = np.zeros(4, dtype=np.float32)
        for ci in affected:
            for ent in ents[ci]: entity_counts[int(ent)] += 1.0
            for role in roles[ci]: role_counts[int(role)] += 1.0
        control_base[i] = np.concatenate([assignment_onehot, edit_onehot, entity_counts / max(1, len(ents)),
            role_counts / max(1, len(affected)), np.asarray([task["n"] / 12, task["k"] / 4,
            len(affected) / max(1, len(ents))], dtype=np.float32)])
    action_common = np.concatenate([control_base, np.zeros((len(action_labels), 4), dtype=np.float32)], axis=1)
    action_template = action_common.copy()
    for i, action in enumerate(action_labels):
        ti, entity = int(action["task_index"]), int(action["edit"]["entity"])
        templates = template_matrix[ti, :len(tasks[ti]["clauses"])]
        action_template[i, 259:261] = [np.sum(templates == t) for t in (0, 1)]
        affected = [ci for ci, mentions in enumerate(tasks[ti]["entity_mentions"]) if entity in mentions]
        action_template[i, 261:263] = [sum(templates[ci] == t for ci in affected) for t in (0, 1)]
    action_controls = {}
    for name, matrix in (("name-incidence-only", action_common[:, :259]), ("template-only", action_template)):
        action_controls[name] = fit_action_matrix(matrix, action_y, action_splits, action_cfg, device, output, name)

    summary = {"manifest": manifest["manifest"], "status": "SENSOR_LADDER_COMPLETE",
        "rungs": {"identity": id_result, "binding": bind_result, "action_relevance": action_result,
                  "action_controls": action_controls},
        "overall_gate_pass": bool(id_result["qualification_balanced_accuracy"] >= 0.90
            and bind_result["qualification"]["combined_f1"] >= 0.90
            and action_result["qualification"]["macro_f1"] >= 0.90),
        "qualification_action_support": {
            str(sign): {"examples": sum(int(row["sign_delta"]) == sign for row in qualifying),
                        "families": len({row["family_id"] for row in qualifying if int(row["sign_delta"]) == sign})}
            for sign in SIGNS
        },
        "elapsed_seconds": time.monotonic() - started,
        "note": "Adaptive engineering retest on a previously reported qualification partition; diagnostic only, not independent confirmation."}
    (output / "qualification-report.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    manifest_receipt["status"] = "R1_SENSOR_PROBES_COMPLETE"
    manifest_receipt["report_sha256"] = sha256(output / "qualification-report.json")
    manifest_receipt["action_feature_matrix_sha256"] = sha256(output / "action_features.f32.mmap")
    (output / "run-receipt.json").write_text(json.dumps(manifest_receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-manifest", required=True)
    parser.add_argument("--support-manifest", required=True)
    parser.add_argument("--extraction", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--public-tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--torch-threads", type=int, default=8)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as error:
        output = Path(args.output)
        if output.exists():
            failure = {"status": "R1_SENSOR_PROBE_FAILED", "error_type": type(error).__name__,
                       "error": str(error), "implementation_sha256": sha256(Path(__file__))}
            (output / "failure.json").write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
