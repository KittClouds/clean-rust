#!/usr/bin/env python3
"""Score Q-v02 candidates with a frozen clause-probability composition."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

Q_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Q_ROOT))
from model import QTerminal  # noqa: E402
from qterminal import family_split, load_feature_bundle, load_manifest, load_sample_arrays, sha256_file  # noqa: E402

EXPECTED_MANIFEST_SHA256 = "2d25d499f9c62e2ed5cb99aacdb60b903361ab941333100a63996c1a9bc3c346"
KINDS = ["different", "exactly_one_role", "fixed_role", "forbidden_role", "implies_not_role", "same"]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha256(path: Path) -> str:
    return sha256_file(path)


def require_hash(path: Path, expected: str, label: str) -> str:
    actual = sha256(path)
    if actual.lower() != expected.lower():
        raise ValueError(f"{label} hash mismatch: expected {expected}, got {actual}")
    return actual.lower()


def sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(values, dtype=np.float64), -80.0, 80.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def roc_auc(labels: np.ndarray, scores: np.ndarray) -> float | None:
    y = np.asarray(labels, dtype=np.uint8)
    values = np.asarray(scores, dtype=np.float64)
    positives = int(np.sum(y == 1))
    negatives = len(y) - positives
    if positives == 0 or negatives == 0:
        return None
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(len(y), dtype=np.float64)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and sorted_values[end] == sorted_values[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    rank_sum = float(ranks[y == 1].sum())
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def binary_metrics(labels: np.ndarray, probabilities: np.ndarray, ranking_score: np.ndarray) -> dict[str, Any]:
    y = np.asarray(labels, dtype=np.uint8)
    raw = np.asarray(probabilities, dtype=np.float64)
    p = np.clip(raw, 1.0e-7, 1.0 - 1.0e-7)
    if not len(y):
        return {"count": 0, "positive_count": 0, "accuracy_at_0.5": None,
                "balanced_accuracy": None, "brier_score": None, "binary_cross_entropy": None,
                "roc_auc": None, "expected_calibration_error_10_bins": None}
    predicted = raw >= 0.5
    positive, negative = y == 1, y == 0
    recall_positive = float(predicted[positive].mean()) if positive.any() else float("nan")
    recall_negative = float((~predicted[negative]).mean()) if negative.any() else float("nan")
    ece = 0.0
    for bin_index in range(10):
        low, high = bin_index / 10.0, (bin_index + 1) / 10.0
        selected = (p >= low) & ((p < high) if bin_index < 9 else (p <= high))
        if selected.any():
            ece += float(selected.mean()) * abs(float(y[selected].mean()) - float(p[selected].mean()))
    return {
        "count": int(len(y)), "positive_count": int(positive.sum()),
        "accuracy_at_0.5": float(np.mean(predicted == positive)),
        "balanced_accuracy": float(np.nanmean([recall_positive, recall_negative])),
        "brier_score": float(np.mean((p - y) ** 2)),
        "binary_cross_entropy": float(np.mean(-(y * np.log(p) + (1 - y) * np.log(1 - p)))),
        "roc_auc": roc_auc(y, ranking_score),
        "expected_calibration_error_10_bins": float(ece),
    }


def satisfaction(kind: str, entities: list[int], roles: list[int], assignment: list[int]) -> float:
    if kind in ("same", "different"):
        if len(entities) != 2:
            raise ValueError(f"{kind} needs two public entity IDs, got {entities}")
        equal = assignment[entities[0]] == assignment[entities[1]]
        return float(equal if kind == "same" else not equal)
    if kind in ("fixed_role", "forbidden_role"):
        if len(entities) != 1 or len(roles) != 1:
            raise ValueError(f"{kind} needs one entity and one role, got {entities}/{roles}")
        equal = assignment[entities[0]] == roles[0]
        return float(equal if kind == "fixed_role" else not equal)
    if kind == "exactly_one_role":
        if not entities or len(roles) != 1:
            raise ValueError(f"exactly_one_role needs an entity set and one role, got {entities}/{roles}")
        return float(sum(assignment[entity] == roles[0] for entity in entities) == 1)
    if kind == "implies_not_role":
        # The frozen generator repeats one entity in the antecedent and consequent.
        # With distinct roles, its implication is a tautology under one-role assignments.
        if len(entities) == 1 and len(roles) == 2:
            return 1.0 if roles[0] != roles[1] else float(assignment[entities[0]] != roles[0])
        # Keep a defined public-incidence approximation for a future two-entity case.
        if len(entities) == 2 and len(roles) == 2:
            pairings = (((entities[0], roles[0]), (entities[1], roles[1])),
                        ((entities[0], roles[1]), (entities[1], roles[0])))
            values = [float(assignment[a] != ar or assignment[b] != br)
                      for (a, ar), (b, br) in pairings]
            return sum(values) / len(values)
        raise ValueError(f"unsupported implies_not_role incidence {entities}/{roles}")
    raise ValueError(f"unknown clause kind {kind!r}")


def supported_kinds(entities: list[int], roles: list[int]) -> list[str]:
    """Return kinds whose argument schema is fully grounded by public mentions."""
    shape = (len(entities), len(roles))
    if shape == (2, 0):
        return ["different", "same"]
    if shape == (1, 1):
        # Exactly one entity in a role is logically identical to fixed_role.
        return ["exactly_one_role", "fixed_role", "forbidden_role"]
    if shape[0] >= 2 and shape[1] == 1:
        return ["exactly_one_role"]
    if shape == (1, 2):
        return ["implies_not_role"]
    raise ValueError(f"public mention incidence does not ground a supported clause kind: {shape}")


def log_product(probabilities: list[float]) -> float:
    if not probabilities:
        return 0.0
    if any(value <= 0.0 for value in probabilities):
        return -math.inf
    return float(sum(math.log(value) for value in probabilities))


def probability_from_log(value: float) -> float:
    if value == -math.inf or value < math.log(np.finfo(np.float64).tiny):
        return 0.0
    return float(math.exp(value))


def metrics_for(indices: np.ndarray, labels: np.ndarray, scores: dict[str, np.ndarray]) -> dict[str, Any]:
    return {name: binary_metrics(labels[indices], scores[name][indices], scores[name][indices])
            for name in scores}


def top1_metrics(indices: np.ndarray, candidates: list[dict[str, Any]], labels: np.ndarray,
                 scores: dict[str, np.ndarray]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[int]] = {}
    for i in indices:
        row = candidates[int(i)]
        groups.setdefault((str(row["feature_id"]), str(row["source_kind"])), []).append(int(i))
    result: dict[str, Any] = {}
    for name, values in scores.items():
        chosen = []
        for rows in groups.values():
            # Stable input-order tie break; labels are never inspected during selection.
            chosen.append(max(rows, key=lambda i: (float(values[i]), -i)))
        result[name] = {"candidate_pools": len(chosen),
                        "top1_valid_rate": float(np.mean(labels[chosen])) if chosen else None,
                        "top1_valid_count": int(np.sum(labels[chosen])) if chosen else 0}
    return result


def verify_inputs(source_root: Path, run_root: Path, manifest_path: Path) -> dict[str, Any]:
    manifest_hash = require_hash(manifest_path, EXPECTED_MANIFEST_SHA256, "composition manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    qroot = source_root / "qterminal"
    paths = {
        "q_mixture_manifest": qroot / "manifest-v02.json",
        "sensor_support_manifest": source_root / "manifests" / "sensor-support-manifest-v02.json",
        "sensor_probe_manifest": source_root / "manifests" / "sensor-probe-fit-manifest-v02.json",
        "public_tasks": run_root / "run-v02" / "public-tasks.jsonl",
        "extraction_receipt": run_root / "run-v02" / "sensor-extraction-v01" / "receipt.json",
        "constraint_H": run_root / "run-v02" / "sensor-extraction-v01" / "constraint_H.float32.npy",
        "global_h": run_root / "run-v02" / "sensor-extraction-v01" / "global_h.float32.npy",
        "extraction_rows": run_root / "run-v02" / "sensor-extraction-v01" / "rows.jsonl",
        "offline_label_summary": run_root / "run-v02" / "offline-labels-v01" / "support-summary.json",
        "private_clause_labels": run_root / "run-v02" / "offline-labels-v01" / "private-clause-labels.jsonl",
        "private_action_labels": run_root / "run-v02" / "offline-labels-v01" / "private-action-labels.jsonl",
        "identity_probe_receipt": run_root / "run-v02" / "sensor-probes-v03" / "run-receipt.json",
        "identity_probe_report": run_root / "run-v02" / "sensor-probes-v03" / "qualification-report.json",
        "identity_model": run_root / "run-v02" / "sensor-probes-v03" / "identity.pt",
        "q_dataset_manifest": run_root / "run-v03" / "qterminal-data-v02" / "dataset-manifest.json",
        "selected_candidates": run_root / "run-v03" / "qterminal-data-v02" / "selected-candidates.jsonl",
        "candidate_generator_receipt": run_root / "run-v03" / "qterminal-candidates-v04" / "candidate-generator-receipt.json",
        "raw_candidate_records": run_root / "run-v03" / "qterminal-candidates-v04" / "candidate-records.jsonl",
        "q_fit_receipt": run_root / "run-v03" / "qterminal-fit-v02" / "fit-receipt.json",
        "q_fitted_checkpoint": run_root / "run-v03" / "qterminal-fit-v02" / "qterminal-v02.pt",
        "qterminal_model_source": qroot / "model.py",
        "qterminal_training_source": qroot / "train_qterminal.py",
        "qterminal_loader_source": qroot / "qterminal.py",
        "candidate_generator_source": source_root / "qterminal" / "candidate-generator" / "src" / "main.rs",
        "identity_probe_source": source_root / "sensor" / "probe_sensor-v03.py",
    }
    expected = {
        "q_mixture_manifest": manifest["q_split"]["manifest_sha256"],
        "sensor_support_manifest": manifest["identity_sensor_split"]["support_manifest_sha256"],
        "sensor_probe_manifest": manifest["identity_sensor_split"]["probe_fit_manifest_sha256"],
        "public_tasks": manifest["features"]["public_tasks_sha256"],
        "extraction_receipt": manifest["features"]["extraction_receipt_sha256"],
        "constraint_H": manifest["features"]["constraint_H_sha256"],
        "global_h": manifest["features"]["global_h_sha256"],
        "extraction_rows": manifest["features"]["rows_jsonl_sha256"],
        "offline_label_summary": manifest["features"]["offline_label_summary_sha256"],
        "private_clause_labels": manifest["features"]["clause_labels_sha256"],
        "private_action_labels": manifest["features"]["action_labels_sha256"],
        "identity_probe_receipt": manifest["identity_sensor_split"]["probe_run_receipt_sha256"],
        "identity_probe_report": manifest["identity_sensor_split"]["probe_report_sha256"],
        "identity_model": manifest["identity_sensor_split"]["identity_model_sha256"],
        "q_dataset_manifest": manifest["q_split"]["dataset_manifest_sha256"],
        "selected_candidates": manifest["q_split"]["selected_candidates_sha256"],
        "candidate_generator_receipt": manifest["q_split"]["candidate_generator_receipt_sha256"],
        "raw_candidate_records": manifest["q_split"]["raw_candidate_records_sha256"],
        "q_fit_receipt": manifest["q_split"]["fit_receipt_sha256"],
        "q_fitted_checkpoint": manifest["q_split"]["fitted_checkpoint_sha256"],
        "qterminal_model_source": manifest["source_code"]["qterminal_model_py_sha256"],
        "qterminal_training_source": manifest["source_code"]["qterminal_training_py_sha256"],
        "qterminal_loader_source": manifest["source_code"]["qterminal_data_loader_py_sha256"],
        "candidate_generator_source": manifest["source_code"]["candidate_generator_rs_sha256"],
        "identity_probe_source": manifest["source_code"]["identity_probe_script_sha256"],
    }
    actual = {key: require_hash(paths[key], digest, key) for key, digest in expected.items()}
    qmix = json.loads(paths["q_mixture_manifest"].read_text(encoding="utf-8"))
    support = json.loads(paths["sensor_support_manifest"].read_text(encoding="utf-8"))
    fit_receipt = json.loads(paths["q_fit_receipt"].read_text(encoding="utf-8"))
    q_checkpoint = torch.load(paths["q_fitted_checkpoint"], map_location="cpu", weights_only=False)
    if qmix.get("schema") != "R1_QTERMINAL_TRAINING_MIXTURE_V02":
        raise ValueError("unexpected Q mixture manifest schema")
    if fit_receipt.get("prepared_dataset_sha256") != expected["q_dataset_manifest"]:
        raise ValueError("Q fit receipt is not bound to the frozen prepared dataset")
    if fit_receipt.get("mixture_manifest_sha256") != expected["q_mixture_manifest"]:
        raise ValueError("Q fit receipt is not bound to the frozen mixture manifest")
    if q_checkpoint.get("mixture_manifest_sha256") != expected["q_mixture_manifest"]:
        raise ValueError("Q checkpoint is not bound to the frozen mixture manifest")
    if q_checkpoint.get("schema") != "R1_QTERMINAL_CHECKPOINT_V02":
        raise ValueError("unexpected Q checkpoint schema")
    if fit_receipt.get("checkpoint_file_sha256") != actual["q_fitted_checkpoint"]:
        raise ValueError("Q fit receipt checkpoint hash does not match the checkpoint bytes")
    if support.get("manifest") != "FAS-R1-SENSOR-SUPPORT-v02":
        raise ValueError("unexpected identity sensor support manifest")
    identity_receipt = json.loads(paths["identity_probe_receipt"].read_text(encoding="utf-8"))
    identity_report = json.loads(paths["identity_probe_report"].read_text(encoding="utf-8"))
    if identity_receipt.get("identity_model_sha256") not in (None, actual["identity_model"]):
        raise ValueError("identity receipt model hash does not match")
    if identity_receipt.get("implementation_sha256") != actual["identity_probe_source"]:
        raise ValueError("identity receipt does not bind the frozen probe implementation")
    if identity_receipt.get("probe_manifest_sha256") != expected["sensor_probe_manifest"]:
        raise ValueError("identity receipt does not bind the frozen probe manifest")
    if identity_receipt.get("support_manifest_sha256") != expected["sensor_support_manifest"]:
        raise ValueError("identity receipt does not bind the frozen support manifest")
    if identity_receipt.get("extraction_receipt_sha256") != expected["extraction_receipt"]:
        raise ValueError("identity receipt does not bind the frozen feature extraction")
    if identity_receipt.get("report_sha256") != actual["identity_probe_report"]:
        raise ValueError("identity receipt report hash does not match report bytes")
    if identity_report.get("manifest") != "FAS-R1-SENSOR-PROBE-FIT-v02":
        raise ValueError("identity qualification report uses unexpected probe manifest")
    return {"manifest_sha256": manifest_hash, "hashes": actual, "paths": paths,
            "manifest": manifest, "q_mixture": qmix, "support": support,
            "q_checkpoint": q_checkpoint, "q_fit_receipt": fit_receipt,
            "identity_report": identity_report}


def validate_rows(paths: dict[str, Path], qmix: dict[str, Any], support: dict[str, Any],
                  feature_arrays: dict[str, np.ndarray], samples: dict[str, np.ndarray],
                  dataset_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    dataset_manifest = json.loads(paths["q_dataset_manifest"].read_text(encoding="utf-8"))
    for name, expected in dataset_manifest["sample_array_sha256"].items():
        array_path = dataset_dir / f"{name}.npy"
        require_hash(array_path, expected, f"prepared array {name}")
    if dataset_manifest.get("schema") != "R1_QTERMINAL_PREPARED_DATASET_V01":
        raise ValueError("unexpected prepared Q dataset schema")
    if dataset_manifest.get("selected_candidates_sha256") != sha256(paths["selected_candidates"]):
        raise ValueError("dataset manifest does not bind selected candidate rows")
    if dataset_manifest.get("candidate_jsonl_sha256") != sha256(paths["raw_candidate_records"]):
        raise ValueError("dataset manifest does not bind the raw candidate records")
    if dataset_manifest.get("mixture_manifest_sha256") != sha256(paths["q_mixture_manifest"]):
        raise ValueError("dataset manifest does not bind Q mixture manifest")
    extraction_receipt = json.loads(paths["extraction_receipt"].read_text(encoding="utf-8"))
    feature_source = dataset_manifest.get("feature_source", {})
    if feature_source.get("extraction_receipt_sha256") != sha256(paths["extraction_receipt"]):
        raise ValueError("prepared Q dataset does not bind sensor extraction receipt")
    if feature_source.get("public_tasks_sha256") != sha256(paths["public_tasks"]):
        raise ValueError("prepared Q dataset does not bind public task JSONL")
    if extraction_receipt.get("output_files") is None:
        raise ValueError("sensor extraction receipt lacks output file inventory")

    public_tasks = read_jsonl(paths["public_tasks"])
    candidates = read_jsonl(paths["selected_candidates"])
    private_clauses = read_jsonl(paths["private_clause_labels"])
    if len(candidates) != len(samples["labels"]):
        raise ValueError("selected candidate rows and prepared arrays differ in length")
    if len(public_tasks) != len(feature_arrays["feature_ids"]):
        raise ValueError("public tasks and feature bank differ in length")
    task_by_id = {task["id"]: task for task in public_tasks}
    task_index_by_id = {task["id"]: i for i, task in enumerate(public_tasks)}
    if len(task_by_id) != len(public_tasks):
        raise ValueError("public task IDs are not unique")
    feature_index_by_id = {str(value): i for i, value in enumerate(feature_arrays["feature_ids"])}
    roster = support["family_roster"]
    sensor_train_families = {row["family_id"] for row in roster if row["split"] == "train"}
    sensor_split_by_family = {row["family_id"]: row["split"] for row in roster}
    if len(sensor_train_families) != int(support["split_counts"]["train"]):
        raise ValueError("identity-sensor training roster count is inconsistent")

    private_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for row in private_clauses:
        key = (str(row["task_id"]), int(row["clause_index"]))
        if key in private_by_key:
            raise ValueError(f"duplicate private clause label {key}")
        private_by_key[key] = row
    expected_clause_count = sum(len(task["clauses"]) for task in public_tasks)
    if len(private_by_key) != expected_clause_count:
        raise ValueError("private clause sidecar does not cover all public clauses")

    for ti, task in enumerate(public_tasks):
        if str(feature_arrays["task_ids"][ti]) != task["id"] or str(feature_arrays["family_ids"][ti]) != task["family_id"]:
            raise ValueError(f"feature row {ti} no longer aligns with public task order")
        if int(feature_arrays["n_by_feature"][ti]) != int(task["n"]) or int(feature_arrays["k_by_feature"][ti]) != int(task["k"]):
            raise ValueError(f"feature row {ti} dimensions differ from public task")
        if len(task["clauses"]) != int(np.sum(feature_arrays["constraint_mask"][ti])):
            raise ValueError(f"feature row {ti} clause count differs from public task")
        for ci, _clause in enumerate(task["clauses"]):
            private = private_by_key[(task["id"], ci)]
            public_entities = sorted(set(map(int, task["entity_mentions"][ci])))
            public_roles = sorted(set(map(int, task["role_mentions"][ci])))
            if sorted(map(int, private["entity_ids"])) != public_entities or sorted(map(int, private["role_ids"])) != public_roles:
                raise ValueError(f"private/public clause incidence mismatch at {task['id']} clause {ci}")
            if private["family_id"] != task["family_id"]:
                raise ValueError("private clause sidecar family differs from public task")

    seen_ids: set[str] = set()
    for i, row in enumerate(candidates):
        if row.get("schema") != "R1_QTERMINAL_SELECTED_CANDIDATE_V01":
            raise ValueError(f"selected candidate {i} has unexpected schema")
        if row["sample_id"] in seen_ids:
            raise ValueError(f"duplicate selected sample_id {row['sample_id']}")
        seen_ids.add(row["sample_id"])
        fi = int(samples["assignment_feature_index"][i])
        task = task_by_id.get(row["task_id"])
        if task is None or feature_index_by_id.get(row["feature_id"]) != fi:
            raise ValueError(f"selected candidate {i} does not resolve to its task feature")
        checks = ((row["sample_id"], str(samples["sample_ids"][i]), "sample_id"),
                  (row["feature_id"], str(samples["feature_ids"][i]), "feature_id"),
                  (row["family_id"], str(samples["family_ids"][i]), "family_id"),
                  (row["source_kind"], str(samples["source_kinds"][i]), "source_kind"),
                  (row["split"], str(samples["splits"][i]), "split"))
        for actual, expected, name in checks:
            if actual != expected:
                raise ValueError(f"selected candidate {i} {name} differs from prepared array")
        if task["family_id"] != row["family_id"] or task["id"] != str(feature_arrays["task_ids"][fi]):
            raise ValueError(f"selected candidate {i} task/family does not match feature bank")
        n = int(task["n"])
        assignment = list(map(int, row["assignment"]))
        if len(assignment) != n or assignment != samples["assignments"][i, :n].astype(int).tolist():
            raise ValueError(f"selected candidate {i} assignment differs from prepared array")
        if np.any(samples["assignments"][i, n:] != 255):
            raise ValueError(f"selected candidate {i} assignment padding is corrupt")
        if bool(row["posthoc_valid"]) != bool(samples["labels"][i]):
            raise ValueError(f"selected candidate {i} offline target differs from prepared label")
        if family_split(row["family_id"], qmix) != row["split"]:
            raise ValueError(f"selected candidate {i} does not follow frozen family split")
        if row["family_id"] not in sensor_split_by_family:
            raise ValueError(f"candidate family {row['family_id']} absent from sensor support roster")
    split_counts = {name: int(np.sum(samples["splits"] == name)) for name in ("train", "validation", "test")}
    if split_counts != dataset_manifest["split_counts"]:
        raise ValueError(f"prepared split counts differ from manifest: {split_counts}")
    for split in ("train", "validation", "test"):
        family_sets = {row["family_id"] for row in candidates if row["split"] == split}
        for other in ("train", "validation", "test"):
            if other <= split:
                continue
            other_families = {row["family_id"] for row in candidates if row["split"] == other}
            if family_sets & other_families:
                raise ValueError(f"Q candidate families overlap between {split} and {other}")

    test_groups: dict[str, dict[str, Any]] = {}
    for i in np.flatnonzero(samples["splits"] == "test"):
        row = candidates[int(i)]
        group = "overlap_sensor_identity_train" if row["family_id"] in sensor_train_families else "unseen_to_identity_train"
        entry = test_groups.setdefault(group, {"rows": 0, "families": set()})
        entry["rows"] += 1
        entry["families"].add(row["family_id"])
    for entry in test_groups.values():
        entry["family_count"] = len(entry["families"])
        entry["families"] = sorted(entry["families"])
    if sum(value["rows"] for value in test_groups.values()) != 24 or any(value["family_count"] != 2 for value in test_groups.values()) or set(test_groups) != {"overlap_sensor_identity_train", "unseen_to_identity_train"}:
        raise ValueError(f"Q-v02 test overlap strata differ from four-family/24-row contract: {test_groups}")
    return public_tasks, candidates, {"dataset_manifest": dataset_manifest,
        "private_clauses": private_by_key, "sensor_train_families": sorted(sensor_train_families),
        "sensor_split_by_family": sensor_split_by_family, "test_groups": test_groups,
        "task_index_by_id": task_index_by_id}


def identity_probabilities(feature_arrays: dict[str, np.ndarray], checkpoint_path: Path,
                           *, device: torch.device) -> tuple[list[np.ndarray], dict[str, Any]]:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    mean = np.asarray(checkpoint["mean"], dtype=np.float32)
    std = np.asarray(checkpoint["std"], dtype=np.float32)
    if mean.shape != (2048,) or std.shape != (2048,) or np.any(std <= 0):
        raise ValueError("identity checkpoint normalization is malformed")
    head = nn.Linear(2048, len(KINDS), bias=True)
    head.load_state_dict(checkpoint["state_dict"], strict=True)
    head.to(device).eval()
    results: list[np.ndarray] = []
    with torch.inference_mode():
        for feature_index in range(len(feature_arrays["feature_ids"])):
            count = int(np.sum(feature_arrays["constraint_mask"][feature_index]))
            h = np.asarray(feature_arrays["h_constraints"][feature_index, :count], dtype=np.float32)
            normalized = np.ascontiguousarray((h - mean) / std, dtype=np.float32)
            logits = head(torch.as_tensor(normalized, device=device))
            probabilities = torch.softmax(logits, dim=-1).cpu().numpy().astype(np.float64)
            if probabilities.shape != (count, len(KINDS)) or not np.all(np.isfinite(probabilities)):
                raise ValueError(f"identity head produced invalid probabilities for feature row {feature_index}")
            results.append(probabilities)
    return results, {"mean_sha256": hashlib.sha256(mean.tobytes(order="C")).hexdigest(),
                     "std_sha256": hashlib.sha256(std.tobytes(order="C")).hexdigest(),
                     "kind_order": KINDS, "inference_device": str(device),
                     "normalization": "identity checkpoint train-family mean/std; componentwise float32"}


def qterminal_logits(feature_arrays: dict[str, np.ndarray], samples: dict[str, np.ndarray],
                     checkpoint: dict[str, Any], *, device: torch.device,
                     batch_size: int = 24) -> np.ndarray:
    model = QTerminal(**checkpoint["model_config"])
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    model.to(device).eval()
    rows_count = len(samples["labels"])
    logits = np.empty(rows_count, dtype=np.float64)
    max_entities = int(samples["assignments"].shape[1])
    max_roles = int(checkpoint["model_config"]["max_roles"])
    with torch.inference_mode():
        for begin in range(0, rows_count, batch_size):
            rows = np.arange(begin, min(begin + batch_size, rows_count), dtype=np.int64)
            feature_rows = np.asarray(samples["assignment_feature_index"][rows], dtype=np.int64)
            n_values = np.asarray(feature_arrays["n_by_feature"][feature_rows], dtype=np.int64)
            k_values = np.asarray(feature_arrays["k_by_feature"][feature_rows], dtype=np.int64)
            assignment_ids = np.asarray(samples["assignments"][rows], dtype=np.uint8)
            assignment = np.zeros((len(rows), max_entities, max_roles), dtype=np.float32)
            entity_mask = np.arange(max_entities)[None, :] < n_values[:, None]
            role_mask = np.arange(max_roles)[None, :] < k_values[:, None]
            for bi, (n, k) in enumerate(zip(n_values, k_values, strict=True)):
                role_ids = assignment_ids[bi, :n].astype(np.int64)
                if np.any(role_ids >= k) or np.any(assignment_ids[bi, n:] != 255):
                    raise ValueError(f"malformed padded assignment at Q sample row {rows[bi]}")
                assignment[bi, np.arange(n), role_ids] = 1.0
            tensor = lambda x: torch.as_tensor(np.asarray(x), device=device)
            H = {
                "constraint_embeddings": tensor(feature_arrays["h_constraints"][feature_rows]),
                "constraint_mask": tensor(feature_arrays["constraint_mask"][feature_rows]),
                "entity_incidence": tensor(feature_arrays["entity_incidence"][feature_rows]),
                "role_incidence": tensor(feature_arrays["role_incidence"][feature_rows]),
                "entity_mask": tensor(entity_mask),
                "role_mask": tensor(role_mask),
            }
            h_global = tensor(feature_arrays["h_global"][feature_rows])
            a = tensor(assignment)
            logits[rows] = model(H, h_global, a).detach().cpu().numpy().astype(np.float64)
    return logits


def candidate_semantic_scores(candidates: list[dict[str, Any]], tasks: list[dict[str, Any]],
                              task_index_by_id: dict[str, int],
                              probabilities_by_feature: list[np.ndarray],
                              private_by_key: dict[tuple[str, int], dict[str, Any]]) -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray, list[dict[str, Any]]]:
    semantic_log = np.empty(len(candidates), dtype=np.float64)
    oracle_log = np.empty(len(candidates), dtype=np.float64)
    candidate_rows: list[dict[str, Any]] = []
    clause_rows: list[dict[str, Any]] = []
    for i, row in enumerate(candidates):
        task_index = task_index_by_id[row["task_id"]]
        task = tasks[task_index]
        assignment = list(map(int, row["assignment"]))
        kind_probs = probabilities_by_feature[task_index]
        predicted_satisfaction: list[float] = []
        oracle_satisfaction: list[float] = []
        for ci, _ in enumerate(task["clauses"]):
            entities = sorted(set(map(int, task["entity_mentions"][ci])))
            roles = sorted(set(map(int, task["role_mentions"][ci])))
            allowed_kinds = supported_kinds(entities, roles)
            allowed_ids = [KINDS.index(kind) for kind in allowed_kinds]
            allowed_mass = float(np.sum(kind_probs[ci, allowed_ids]))
            if not math.isfinite(allowed_mass) or allowed_mass <= 0.0:
                raise ValueError(f"identity posterior has zero mass on incidence-supported kinds for {task['id']} clause {ci}")
            conditional_kind_probs = kind_probs[ci, allowed_ids] / allowed_mass
            per_kind = [satisfaction(kind, entities, roles, assignment) for kind in allowed_kinds]
            p_sat = float(np.dot(conditional_kind_probs, np.asarray(per_kind, dtype=np.float64)))
            private = private_by_key[(task["id"], ci)]
            private_kind = str(private["clause_kind"])
            if private_kind not in allowed_kinds:
                raise ValueError(f"private clause kind {private_kind} is unsupported by public incidence at {task['id']} clause {ci}")
            exact_sat = satisfaction(private_kind, entities, roles, assignment)
            # Current v02 task clauses expose exact incidence; implication clauses are
            # same-entity two-role tautologies under the one-role-per-entity contract.
            if private_kind == "implies_not_role" and (len(entities) != 1 or len(roles) != 2 or roles[0] == roles[1]):
                raise ValueError("private-kind oracle encountered non-current implication semantics")
            predicted_satisfaction.append(p_sat)
            oracle_satisfaction.append(exact_sat)
            clause_rows.append({
                "sample_id": row["sample_id"], "task_id": task["id"], "family_id": task["family_id"],
                "clause_index": ci, "supported_kinds": allowed_kinds,
                "identity_supported_mass": allowed_mass,
                "p_kind": {kind: float(kind_probs[ci, ki]) for ki, kind in enumerate(KINDS)},
                "p_kind_conditioned_on_public_incidence": {kind: float(conditional_kind_probs[pos]) for pos, kind in enumerate(allowed_kinds)},
                "p_satisfied": p_sat, "private_kind_oracle_satisfied": int(exact_sat),
            })
        semantic_log[i] = log_product(predicted_satisfaction)
        oracle_log[i] = log_product(oracle_satisfaction)
        candidate_rows.append({
            "sample_id": row["sample_id"], "task_id": task["id"], "feature_id": row["feature_id"],
            "family_id": row["family_id"], "split": row["split"], "source_kind": row["source_kind"],
            "posthoc_valid": int(row["posthoc_valid"]), "semantic_log_score": semantic_log[i],
            "semantic_probability": probability_from_log(semantic_log[i]),
            "private_kind_oracle_log_score": oracle_log[i],
            "private_kind_oracle_probability": probability_from_log(oracle_log[i]),
        })
    return candidate_rows, semantic_log, oracle_log, clause_rows


def json_safe(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    if isinstance(value, np.ndarray):
        return [json_safe(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return value


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(json_safe(row), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")


def evaluate_group(indices: np.ndarray, candidates: list[dict[str, Any]], labels: np.ndarray,
                   probabilities: dict[str, np.ndarray], ranking: dict[str, np.ndarray]) -> dict[str, Any]:
    return {
        "rows": int(len(indices)),
        "family_count": len({candidates[int(i)]["family_id"] for i in indices}),
        "binary_metrics": {name: binary_metrics(labels[indices], prob[indices], ranking[name][indices])
                           for name, prob in probabilities.items()},
        "top1_metrics_by_feature_and_source": top1_metrics(indices, candidates, labels, ranking),
    }


def comparison_deltas(metrics: dict[str, Any]) -> dict[str, Any]:
    deltas: dict[str, Any] = {}
    for group, result in metrics.items():
        model_metrics = result["binary_metrics"]
        semantic, q_model = model_metrics["identity_composition"], model_metrics["q_v02"]
        diff = {}
        for key in ("accuracy_at_0.5", "balanced_accuracy", "brier_score", "binary_cross_entropy", "roc_auc"):
            left, right = semantic.get(key), q_model.get(key)
            diff[key] = None if left is None or right is None else float(left - right)
        tops = result["top1_metrics_by_feature_and_source"]
        diff["top1_valid_rate"] = (
            None if tops["identity_composition"]["top1_valid_rate"] is None or tops["q_v02"]["top1_valid_rate"] is None
            else float(tops["identity_composition"]["top1_valid_rate"] - tops["q_v02"]["top1_valid_rate"])
        )
        deltas[group] = diff
    return deltas


def export_standardized_identity_head(checkpoint_path: Path, output_dir: Path,
                                      fixed_input: np.ndarray, *, device: torch.device) -> dict[str, Any]:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    mean = np.asarray(checkpoint["mean"], dtype=np.float32)
    std = np.asarray(checkpoint["std"], dtype=np.float32)
    head = nn.Linear(2048, len(KINDS), bias=True)
    head.load_state_dict(checkpoint["state_dict"], strict=True)
    head.to(device).eval()
    weight = head.weight.detach().cpu().numpy().astype(np.float32, copy=True)
    bias = head.bias.detach().cpu().numpy().astype(np.float32, copy=True)
    standardized_weight = np.ascontiguousarray(weight / std[None, :], dtype=np.float32)
    standardized_bias = np.ascontiguousarray(bias - np.sum(weight * (mean / std)[None, :], axis=1, dtype=np.float32), dtype=np.float32)
    arrays = {
        "mean": mean,
        "std": std,
        "standardized_weight": standardized_weight,
        "standardized_bias": standardized_bias,
    }
    field_info: dict[str, Any] = {}
    chunks: list[bytes] = []
    offset = 0
    for name, array in arrays.items():
        little = np.asarray(array, dtype="<f4", order="C")
        payload = little.tobytes(order="C")
        field_info[name] = {"dtype": "float32_le", "shape": list(array.shape), "byte_offset": offset, "byte_length": len(payload)}
        chunks.append(payload)
        offset += len(payload)
    binary_path = output_dir / "identity-head-f32le.bin"
    binary_path.write_bytes(b"".join(chunks))

    raw = np.asarray(fixed_input, dtype=np.float32).reshape(1, 2048)
    normalized = np.ascontiguousarray((raw - mean) / std, dtype=np.float32)
    with torch.inference_mode():
        pytorch_logits = head(torch.as_tensor(normalized, device=device)).detach().cpu().numpy().astype(np.float64)[0]
    exported_logits = raw.astype(np.float64) @ standardized_weight.astype(np.float64).T + standardized_bias.astype(np.float64)
    pytorch_prob = torch.softmax(torch.as_tensor(pytorch_logits), dim=-1).numpy()
    exported_prob = torch.softmax(torch.as_tensor(exported_logits[0]), dim=-1).numpy()
    max_logit_error = float(np.max(np.abs(pytorch_logits - exported_logits[0])))
    max_probability_error = float(np.max(np.abs(pytorch_prob - exported_prob)))
    if max_logit_error > 5.0e-4 or max_probability_error > 1.0e-5:
        raise ValueError(f"standardized identity export parity failed: logits={max_logit_error}, probs={max_probability_error}")
    metadata = {
        "schema": "R1_IDENTITY_LINEAR_STANDARDIZED_F32LE_V01",
        "semantics": "raw float32 H row dot standardized_weight transpose plus standardized_bias; softmax in declared kind order",
        "kind_order": KINDS,
        "input_dim": 2048,
        "output_dim": len(KINDS),
        "binary_file": binary_path.name,
        "binary_sha256": sha256(binary_path),
        "binary_bytes": binary_path.stat().st_size,
        "fields": field_info,
        "source_identity_checkpoint_sha256": sha256(checkpoint_path),
        "parity_sample_raw_H_sha256": hashlib.sha256(raw.astype("<f4", copy=False).tobytes()).hexdigest(),
        "parity_max_abs_logit_error": max_logit_error,
        "parity_max_abs_probability_error": max_probability_error,
        "parity_pass": True,
        "inference_device": str(device),
    }
    metadata_path = output_dir / "identity-head-export.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--run-root", type=Path,
                        default=Path(r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01"))
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("manifest-v01.json"))
    parser.add_argument("--output", type=Path,
                        default=Path(r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v01"))
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing result: {args.output}")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    device = torch.device("cuda" if args.device == "cuda" or (args.device == "auto" and torch.cuda.is_available()) else "cpu")
    source_root, run_root = args.source_root.resolve(), args.run_root.resolve()
    verified = verify_inputs(source_root, run_root, args.manifest.resolve())
    paths = verified["paths"]
    feature_dir = run_root / "run-v02" / "sensor-extraction-v01"
    dataset_dir = run_root / "run-v03" / "qterminal-data-v02"
    feature_arrays, feature_receipt = load_feature_bundle(feature_dir)
    if feature_receipt["extraction_receipt_sha256"] != verified["hashes"]["extraction_receipt"]:
        raise ValueError("feature loader receipt hash differs from frozen manifest")
    samples = load_sample_arrays(dataset_dir)
    public_tasks, candidates, lineage = validate_rows(
        paths, verified["q_mixture"], verified["support"], feature_arrays, samples, dataset_dir
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    identity_probs, identity_info = identity_probabilities(feature_arrays, paths["identity_model"], device=device)
    candidate_rows, semantic_log, oracle_log, clause_rows = candidate_semantic_scores(
        candidates, public_tasks, lineage["task_index_by_id"], identity_probs, lineage["private_clauses"]
    )
    labels = np.asarray(samples["labels"], dtype=np.uint8)
    oracle_prob = np.asarray([probability_from_log(value) for value in oracle_log], dtype=np.float64)
    if not np.array_equal(oracle_prob.astype(np.uint8), labels):
        mismatch = np.flatnonzero(oracle_prob.astype(np.uint8) != labels)
        raise ValueError(f"private-kind oracle disagrees with exact validator on candidate rows {mismatch[:8].tolist()}")

    q_logits = qterminal_logits(feature_arrays, samples, verified["q_checkpoint"], device=device)
    temperature = float(verified["q_checkpoint"]["temperature"])
    q_prob = sigmoid(q_logits / temperature)
    semantic_prob = np.asarray([probability_from_log(value) for value in semantic_log], dtype=np.float64)
    probabilities = {"identity_composition": semantic_prob, "q_v02": q_prob, "private_kind_oracle": oracle_prob}
    rankings = {"identity_composition": semantic_log, "q_v02": q_logits / temperature, "private_kind_oracle": oracle_log}
    for i, row in enumerate(candidate_rows):
        row["q_v02_logit"] = float(q_logits[i])
        row["q_v02_temperature"] = temperature
        row["q_v02_probability"] = float(q_prob[i])
    split_metrics: dict[str, Any] = {}
    for split in ("train", "validation", "test"):
        indices = np.flatnonzero(samples["splits"] == split)
        split_metrics[split] = evaluate_group(indices, candidates, labels, probabilities, rankings)
    test_strata: dict[str, Any] = {}
    for name, cell in lineage["test_groups"].items():
        selected_families = set(cell["families"])
        indices = np.asarray([i for i, row in enumerate(candidates)
                              if row["split"] == "test" and row["family_id"] in selected_families], dtype=np.int64)
        test_strata[name] = evaluate_group(indices, candidates, labels, probabilities, rankings)
        test_strata[name]["identity_sensor_split_counts"] = {
            split: sum(1 for family in selected_families if lineage["sensor_split_by_family"][family] == split)
            for split in ("train", "validation", "qualification")
        }
    if sum(item["rows"] for item in test_strata.values()) != 24:
        raise ValueError("test rows no longer match frozen sensor-train overlap stratification")

    # Confirm our standalone recomputation reproduces the already-fitted Q-v02 test metrics.
    saved_test = verified["q_fit_receipt"]["test_metrics_after_calibration"]["overall"]
    reproduced = split_metrics["test"]["binary_metrics"]["q_v02"]
    baseline_delta = {key: (None if saved_test.get(key) is None or reproduced.get(key) is None
                            else float(reproduced[key] - saved_test[key]))
                      for key in ("accuracy_at_0.5", "balanced_accuracy", "brier_score", "binary_cross_entropy",
                                  "roc_auc", "expected_calibration_error_10_bins")}
    if any(value is not None and abs(value) > 2.0e-5 for value in baseline_delta.values()):
        raise ValueError(f"recomputed Q-v02 test metrics diverge from its fit receipt: {baseline_delta}")

    # Export one fixed raw constraint row for a deterministic Rust/Python posterior parity check.
    first_task_index = lineage["task_index_by_id"][candidates[0]["task_id"]]
    fixed_raw_h = np.asarray(feature_arrays["h_constraints"][first_task_index, 0], dtype=np.float32)
    export_metadata = export_standardized_identity_head(paths["identity_model"], output, fixed_raw_h, device=device)
    score_path, clause_path = output / "candidate-scores.jsonl", output / "clause-probabilities.jsonl"
    write_jsonl(score_path, candidate_rows)
    write_jsonl(clause_path, clause_rows)

    split_deltas = comparison_deltas(split_metrics)
    stratum_deltas = comparison_deltas(test_strata)
    report = {
        "schema": "R1_QTERMINAL_SEMANTIC_COMPOSITION_REPORT_V01",
        "status": "SCORED_NO_FIT_NO_CALIBRATION",
        "candidate_count": len(candidates), "clause_score_count": len(clause_rows),
        "split_counts": {split: int(np.sum(samples["splits"] == split)) for split in ("train", "validation", "test")},
        "test_identity_sensor_overlap": test_strata,
        "metrics_by_split": split_metrics,
        "semantic_minus_q_v02": {"by_split": split_deltas, "test_strata": stratum_deltas},
        "q_v02_baseline_reproduction": {"receipt_metrics": saved_test, "recomputed_metrics": reproduced,
                                         "recomputed_minus_receipt": baseline_delta, "pass": True},
        "selection_definition": "within each (feature_id, source_kind) candidate pool, choose maximum score with stable input-row tie break",
        "composition": {
            "identity_head": "frozen linear six-way identity head on each constraint H_j, with training-family normalization",
            "per_clause": "mask and renormalize P(kind|H_j) over clause kinds fully grounded by public mention incidence, then sum conditional P(kind) * satisfaction(kind, public incidence, assignment)",
            "terminal_probability": "product of per-clause expected satisfaction probabilities; factorized-across-clauses approximation",
            "ranking": "sum_j log(p_satisfied_j), exact -infinity when any p_satisfied_j is zero",
            "calibration_or_fitting": "none",
            "global_h_used": False,
            "private_kind_oracle": "offline one-hot private clause kind through the same incidence/assignment rule; exact candidate validator parity required",
            "implication_note": "all v02 implication clauses are one-entity/two-distinct-role tautologies under one-role-per-entity assignments",
        },
        "identity_head_export": export_metadata,
        "lineage": {
            "manifest_sha256": verified["manifest_sha256"],
            "inputs_sha256": verified["hashes"],
            "sensor_train_family_overlap_count": len(lineage["sensor_train_families"]),
            "q_test_strata": lineage["test_groups"],
            "aggregate_test_warning": "aggregate test includes two families overlapping sensor identity training and two families unseen to that training; use both 12-row strata, not aggregate as unseen generalization",
            "q_v02_validation_temperature": temperature,
            "identity_probability_detail": identity_info,
        },
        "limitations": [
            "This is a frozen-feature engineering diagnostic over the selected Q-v02 candidate rows, not an independent generalization estimate.",
            "The factorized score assumes clause satisfaction events are independent conditional on the candidate; clauses can be dependent.",
            "The frozen identity probe passes its identity rung but the overall sensor ladder has weak binding/action diagnostics; composition tests whether identity plus public incidence helps this candidate set.",
        ],
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(json_safe(report), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    artifacts = [score_path, clause_path, report_path, output / "identity-head-f32le.bin", output / "identity-head-export.json"]
    receipt = {
        "schema": "R1_QTERMINAL_SEMANTIC_COMPOSITION_RECEIPT_V01",
        "status": "COMPLETE",
        "manifest_sha256": verified["manifest_sha256"],
        "source_script_sha256": sha256(Path(__file__).resolve()),
        "source_root": str(source_root), "run_root": str(run_root),
        "device": str(device), "torch_version": torch.__version__, "numpy_version": np.__version__,
        "input_sha256": verified["hashes"],
        "output_files": [{"path": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)} for path in artifacts],
        "report_sha256": sha256(report_path),
        "fitting_performed": False, "calibration_performed": False,
        "private_kind_oracle_used_for_primary_score": False,
        "private_kind_oracle_used_only_for_diagnostic_and_exact_parity_check": True,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "receipt_sha256": sha256(output / "receipt.json"),
                      "report_sha256": receipt["report_sha256"],
                      "q_v02_test": reproduced,
                      "composition_test": split_metrics["test"]["binary_metrics"]["identity_composition"],
                      "test_strata": {key: value["binary_metrics"] for key, value in test_strata.items()},
                      "semantic_minus_q": {"test": split_deltas["test"], "test_strata": stratum_deltas},
                      "identity_export_parity": {"logit_error": export_metadata["parity_max_abs_logit_error"],
                                                  "probability_error": export_metadata["parity_max_abs_probability_error"]}},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


