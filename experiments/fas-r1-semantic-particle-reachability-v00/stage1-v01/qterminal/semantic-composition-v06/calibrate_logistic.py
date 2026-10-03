#!/usr/bin/env python3
"""Fit one train-only regularized logistic calibration for semantic scores v06."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

HERE = Path(__file__).resolve().parent
V03_SOURCE = HERE.parent / "semantic-composition-v03"
sys.path.insert(0, str(V03_SOURCE))
import score_semantic as base  # noqa: E402

EXPECTED_MANIFEST_SHA256 = "81e35f972c556920b08c9c93ca362af36b7b26ff06228fef174bf6b63a6d1b77"
L2_LAMBDA = 1.0


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require_hash(path: Path, expected: str, label: str) -> str:
    actual = base.sha256(path)
    if actual.lower() != expected.lower():
        raise ValueError(f"{label} hash mismatch: expected {expected}, got {actual}")
    return actual.lower()


def log_scores(rows: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray([-math.inf if row["semantic_log_score"] is None else float(row["semantic_log_score"])
                       for row in rows], dtype=np.float64)


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    result = np.empty_like(values)
    positive = values >= 0
    result[positive] = 1.0 / (1.0 + np.exp(-np.minimum(values[positive], 80.0)))
    negative_exp = np.exp(np.maximum(values[~positive], -80.0))
    result[~positive] = negative_exp / (1.0 + negative_exp)
    return result


def objective(parameters: np.ndarray, x: np.ndarray, y: np.ndarray, regularization: float) -> float:
    slope, intercept = map(float, parameters)
    logits = intercept + slope * x
    return float(np.mean(np.logaddexp(0.0, logits) - y * logits) + 0.5 * regularization * slope * slope)


def fit_logistic(x: np.ndarray, y: np.ndarray, regularization: float = L2_LAMBDA) -> tuple[float, float, dict[str, Any]]:
    """Two-parameter convex logistic fit; ridge-penalize the monotone slope only."""
    if len(x) != len(y) or not len(y) or not np.all(np.isfinite(x)):
        raise ValueError("logistic fit requires finite aligned train-only inputs")
    if np.any((y != 0) & (y != 1)) or not 0.0 < float(np.mean(y)) < 1.0:
        raise ValueError("logistic calibration requires both binary training classes")
    params = np.asarray([1.0, math.log(float(np.mean(y)) / (1.0 - float(np.mean(y))))], dtype=np.float64)
    converged = False
    iterations = 0
    for iteration in range(1, 201):
        slope, intercept = params
        logits = intercept + slope * x
        probability = sigmoid(logits)
        residual = probability - y
        curvature = probability * (1.0 - probability)
        gradient = np.asarray([np.mean(residual * x) + regularization * slope, np.mean(residual)])
        hessian = np.asarray([
            [np.mean(curvature * x * x) + regularization, np.mean(curvature * x)],
            [np.mean(curvature * x), np.mean(curvature)],
        ])
        step = np.linalg.solve(hessian, gradient)
        before = objective(params, x, y, regularization)
        rate = 1.0
        accepted = False
        for _ in range(60):
            proposal = params - rate * step
            proposal[0] = max(0.0, proposal[0])
            if objective(proposal, x, y, regularization) <= before - 1e-4 * rate * float(np.dot(gradient, step)) + 1e-15:
                accepted = True
                break
            rate *= 0.5
        if not accepted:
            if float(np.max(np.abs(gradient))) < 1e-7:
                converged = True
                iterations = iteration
                break
            raise RuntimeError("regularized logistic line search failed")
        change = float(np.max(np.abs(proposal - params)))
        params = proposal
        iterations = iteration
        if change < 1e-10:
            converged = True
            break
    if not converged or params[0] <= 0:
        raise RuntimeError(f"logistic fit failed to converge with positive slope: {params.tolist()}")
    return float(params[0]), float(params[1]), {
        "converged": converged, "iterations": iterations, "regularization_lambda": regularization,
        "slope_standardized": float(params[0]), "intercept": float(params[1]),
        "objective": objective(params, x, y, regularization),
    }


def export_calibration(path: Path, floor: float, center: float, scale: float,
                       slope: float, intercept: float, input_hash: str,
                       training_ids_sha256: str) -> dict[str, Any]:
    coefficients = np.asarray([floor, center, scale, slope, intercept], dtype="<f8")
    path.write_bytes(coefficients.tobytes(order="C"))
    metadata = {
        "schema": "R1_SEMANTIC_LOGISTIC_RUNTIME_EXPORT_V01",
        "binary_file": path.name, "binary_sha256": base.sha256(path), "binary_bytes": path.stat().st_size,
        "coefficient_order": ["negative_infinity_floor", "training_score_center", "training_score_scale",
                              "nonnegative_standardized_slope", "intercept"],
        "dtype": "float64_le", "coefficient_count": 5,
        "formula": "stable_sigmoid(intercept + slope * ((raw_log_score_or_floor - center) / scale))",
        "monotonicity": "nondecreasing; fitted slope is required positive",
        "l2_lambda": L2_LAMBDA,
        "raw_v03_score_sha256": input_hash,
        "training_sample_ids_sha256": training_ids_sha256,
        "calibration_training_split": "train only",
        "validation_or_test_labels_used_for_fit": False,
    }
    path.with_name("logistic-calibration-export.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    restored = np.frombuffer(path.read_bytes(), dtype="<f8", count=5).astype(np.float64)
    if not np.array_equal(restored, coefficients.astype(np.float64)):
        raise ValueError("logistic coefficient export readback failed")
    return metadata


def score_metrics(indices: np.ndarray, rows: list[dict[str, Any]], labels: np.ndarray,
                  probabilities: dict[str, np.ndarray], ranking: dict[str, np.ndarray]) -> dict[str, Any]:
    return {
        "rows": int(len(indices)), "family_count": len({rows[int(i)]["family_id"] for i in indices}),
        "binary_metrics": {name: base.binary_metrics(labels[indices], p[indices], ranking[name][indices])
                           for name, p in probabilities.items()},
        "top1_metrics_by_feature_and_source": base.top1_metrics(indices, rows, labels, ranking),
    }


def make_rust_reference(raw_rows: list[dict[str, Any]], raw_run: Path, run_root: Path,
                        identity_export_path: Path) -> tuple[dict[str, Any], dict[str, float]]:
    """Export one full public candidate as a fixed Python/Rust posterior reference."""
    feature_dir = run_root / "run-v02" / "sensor-extraction-v01"
    feature_arrays, feature_receipt = base.load_feature_bundle(feature_dir)
    public_path = run_root / "run-v02" / "public-tasks.jsonl"
    raw_receipt = load_json(raw_run / "receipt.json")
    for path, key in ((feature_dir / "constraint_H.float32.npy", "constraint_H"),
                      (public_path, "public_tasks"),
                      (run_root / "run-v02" / "sensor-probes-v03" / "identity.pt", "identity_model")):
        if base.sha256(path) != raw_receipt["input_sha256"][key]:
            raise ValueError(f"Rust reference input hash differs from v03 receipt: {key}")
    if feature_receipt["extraction_receipt_sha256"] != raw_receipt["input_sha256"]["extraction_receipt"]:
        raise ValueError("Rust reference feature receipt differs from v03 run")
    public_tasks = base.read_jsonl(public_path)
    feature_by_task = {str(task_id): i for i, task_id in enumerate(feature_arrays["task_ids"])}
    task_by_id = {task["id"]: task for task in public_tasks}
    row = raw_rows[0]
    task_index = feature_by_task[row["task_id"]]
    task = task_by_id[row["task_id"]]
    assignment = list(map(int, row["assignment"])) if "assignment" in row else None
    # candidate-scores.jsonl intentionally omits assignments; recover the same public
    # candidate row from the hash-bound selected-candidates file at the identical index.
    selected = base.read_jsonl(run_root / "run-v03" / "qterminal-data-v02" / "selected-candidates.jsonl")
    candidate = selected[0]
    assignment = list(map(int, candidate["assignment"]))
    identity_checkpoint_path = run_root / "run-v02" / "sensor-probes-v03" / "identity.pt"
    checkpoint = torch.load(identity_checkpoint_path, map_location="cpu", weights_only=False)
    mean = np.asarray(checkpoint["mean"], dtype=np.float32)
    std = np.asarray(checkpoint["std"], dtype=np.float32)
    head = nn.Linear(2048, 6, bias=True)
    head.load_state_dict(checkpoint["state_dict"], strict=True)
    head.eval()
    all_clause_rows = base.read_jsonl(raw_run / "clause-probabilities.jsonl")
    clause_by_key = {(item["sample_id"], int(item["clause_index"])): item for item in all_clause_rows}
    h = np.asarray(feature_arrays["h_constraints"][task_index, :len(task["clauses"])], dtype=np.float32)
    if h.shape != (len(task["clauses"]), 2048):
        raise ValueError("fixed Rust reference H matrix has unexpected shape")
    clauses: list[dict[str, Any]] = []
    p_error = 0.0
    p_sat_error = 0.0
    stored_p_sat_error = 0.0
    p_sat_values: list[float] = []
    for ci in range(len(task["clauses"])):
        raw_h = np.ascontiguousarray(h[ci], dtype=np.float32)
        normalized = np.ascontiguousarray((raw_h - mean) / std, dtype=np.float32)
        with torch.inference_mode():
            logits = head(torch.as_tensor(normalized).reshape(1, -1)).detach().cpu().numpy()[0].astype(np.float64)
        p_kind = torch.softmax(torch.as_tensor(logits, dtype=torch.float32), dim=-1).numpy().astype(np.float64)
        expected = clause_by_key[(candidate["sample_id"], ci)]
        expected_pk = np.asarray([expected["p_kind"][name] for name in base.KINDS], dtype=np.float64)
        p_error = max(p_error, float(np.max(np.abs(p_kind - expected_pk))))
        entities = sorted(set(map(int, task["entity_mentions"][ci])))
        roles = sorted(set(map(int, task["role_mentions"][ci])))
        allowed = base.supported_kinds(entities, roles)
        allowed_ids = [base.KINDS.index(kind) for kind in allowed]
        # The fixed expected posterior is read from the sealed v03 Python output.
        # Use it for the composition target so the Rust vector is stable down to
        # serialized-float precision. Keep the newly recomputed head posterior as
        # an independent parity measurement; tiny posterior errors can be greatly
        # amplified by log(p_sat) when a clause probability is near zero.
        mass = float(np.sum(expected_pk[allowed_ids]))
        conditional = expected_pk[allowed_ids] / mass
        satisfaction_by_kind = {kind: base.satisfaction(kind, entities, roles, assignment) for kind in allowed}
        per_kind = np.asarray([satisfaction_by_kind[kind] for kind in allowed], dtype=np.float64)
        p_sat = float(np.dot(conditional, per_kind))
        recomputed_mass = float(np.sum(p_kind[allowed_ids]))
        recomputed_conditional = p_kind[allowed_ids] / recomputed_mass
        recomputed_p_sat = float(np.dot(recomputed_conditional, per_kind))
        p_sat_error = max(p_sat_error, abs(recomputed_p_sat - float(expected["p_satisfied"])))
        stored_p_sat_error = max(stored_p_sat_error, abs(p_sat - float(expected["p_satisfied"])))
        p_sat_values.append(p_sat)
        clauses.append({
            "clause_index": ci,
            "raw_H_f32": raw_h.tolist(),
            "identity_logits_f64": logits.tolist(),
            "identity_probabilities": {kind: float(expected_pk[j]) for j, kind in enumerate(base.KINDS)},
            "identity_probabilities_recomputed": {kind: float(p_kind[j]) for j, kind in enumerate(base.KINDS)},
            "entity_ids": entities, "role_ids": roles,
            "supported_kinds": allowed,
            "supported_kind_probabilities": {kind: float(conditional[pos]) for pos, kind in enumerate(allowed)},
            "assignment_satisfaction_by_kind": satisfaction_by_kind,
            "expected_satisfaction_probability": p_sat,
        })
    log_score = base.log_product(p_sat_values)
    expected_log = row["semantic_log_score"]
    if expected_log is None:
        if log_score != -math.inf:
            raise ValueError("fixed Rust reference did not reproduce negative-infinity semantic score")
        log_error = 0.0
    else:
        log_error = abs(log_score - float(expected_log))
    if log_error > 1.0e-8:
            raise ValueError(f"fixed Rust reference score differs from v03 output: {log_error}")
    if p_error > 1.0e-10 or p_sat_error > 1.0e-10:
        raise ValueError(f"fixed Rust reference clause parity failed: posterior={p_error}, p_sat={p_sat_error}")
    export_meta = load_json(identity_export_path)
    raw_h_hash = hashlib.sha256(h.astype("<f4", copy=False).tobytes(order="C")).hexdigest()
    first_h_hash = hashlib.sha256(h[0].astype("<f4", copy=False).tobytes(order="C")).hexdigest()
    if first_h_hash != export_meta["parity_sample_raw_H_sha256"]:
        raise ValueError("Rust fixed reference is not the pinned v03 export parity sample")
    reference = {
        "schema": "R1_SEMANTIC_COMPOSITION_REFERENCE_VECTOR_V02",
        "description": "One selected candidate's public H rows, Python identity posterior, public incidence, assignment, and expected semantic composition. IDs are anonymized so no posthoc validity label is disclosed.",
        "reference_id": "fixed-vector-0001", "candidate_index": 0,
        "assignment": assignment, "kind_order": base.KINDS,
        "identity_head_binary_sha256": base.sha256(identity_export_path.with_name("identity-head-f32le.bin")),
        "raw_H_matrix_shape": list(h.shape), "raw_H_matrix_sha256_f32le": raw_h_hash,
        "clauses": clauses,
        "expected_semantic_log_score": log_score if math.isfinite(log_score) else None,
        "expected_semantic_probability": base.probability_from_log(log_score),
        "global_h_used": False,
    }
    return reference, {"max_identity_probability_abs_error": p_error,
                       "max_recomputed_per_clause_p_sat_abs_error": p_sat_error,
                       "max_reference_formula_vs_v03_p_sat_abs_error": stored_p_sat_error,
                       "semantic_log_score_abs_error": log_error,
                       "feature_extraction_receipt_sha256": feature_receipt["extraction_receipt_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=HERE.parents[1])
    parser.add_argument("--run-root", type=Path,
                        default=Path(r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01"))
    parser.add_argument("--manifest", type=Path, default=HERE / "manifest-v06.json")
    parser.add_argument("--raw-run", type=Path,
                        default=Path(r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v03"))
    parser.add_argument("--isotonic-run", type=Path,
                        default=Path(r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v04"))
    parser.add_argument("--output", type=Path,
                        default=Path(r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-semantic-v06"))
    args = parser.parse_args()
    source_root, run_root = args.source_root.resolve(), args.run_root.resolve()
    manifest_path, raw_run, isotonic_run = args.manifest.resolve(), args.raw_run.resolve(), args.isotonic_run.resolve()
    manifest_sha = require_hash(manifest_path, EXPECTED_MANIFEST_SHA256, "v06 calibration manifest")
    manifest = load_json(manifest_path)
    if manifest.get("schema") != "R1_QTERMINAL_SEMANTIC_LOGISTIC_CALIBRATION_V06":
        raise ValueError("unexpected logistic-calibration manifest schema")

    qroot = source_root / "qterminal"
    v03_manifest = qroot / "semantic-composition-v03" / "manifest-v03.json"
    v03_script = qroot / "semantic-composition-v03" / "score_semantic.py"
    v04_manifest = qroot / "semantic-composition-v04" / "manifest-v04.json"
    v04_script = qroot / "semantic-composition-v04" / "calibrate_semantic.py"
    data_dir = run_root / "run-v03" / "qterminal-data-v02"
    support_path = source_root / "manifests" / "sensor-support-manifest-v02.json"
    paths = {
        "v03_manifest": v03_manifest, "v03_script": v03_script,
        "v03_receipt": raw_run / "receipt.json", "v03_report": raw_run / "report.json",
        "v03_scores": raw_run / "candidate-scores.jsonl",
        "v04_manifest": v04_manifest, "v04_script": v04_script,
        "v04_receipt": isotonic_run / "receipt.json", "v04_report": isotonic_run / "report.json",
        "v04_scores": isotonic_run / "candidate-scores-calibrated.jsonl",
        "v04_coefficients": isotonic_run / "isotonic-coefficients.f64f32le.bin",
        "public_tasks": run_root / "run-v02" / "public-tasks.jsonl",
        "extraction_receipt": run_root / "run-v02" / "sensor-extraction-v01" / "receipt.json",
        "constraint_H": run_root / "run-v02" / "sensor-extraction-v01" / "constraint_H.float32.npy",
        "identity_model": run_root / "run-v02" / "sensor-probes-v03" / "identity.pt",
        "q_mix_manifest": qroot / "manifest-v02.json", "support_manifest": support_path,
        "q_dataset_manifest": data_dir / "dataset-manifest.json",
        "selected_candidates": data_dir / "selected-candidates.jsonl",
        "q_checkpoint": run_root / "run-v03" / "qterminal-fit-v02" / "qterminal-v02.pt",
    }
    expected = {
        "v03_manifest": manifest["raw_semantic_source"]["manifest_sha256"],
        "v03_script": manifest["raw_semantic_source"]["source_script_sha256"],
        "v03_receipt": manifest["raw_semantic_source"]["receipt_sha256"],
        "v03_report": manifest["raw_semantic_source"]["report_sha256"],
        "v03_scores": manifest["raw_semantic_source"]["candidate_scores_sha256"],
        "v04_manifest": manifest["isotonic_comparison"]["manifest_sha256"],
        "v04_script": manifest["isotonic_comparison"]["source_script_sha256"],
        "v04_receipt": manifest["isotonic_comparison"]["receipt_sha256"],
        "v04_report": manifest["isotonic_comparison"]["report_sha256"],
        "v04_scores": manifest["isotonic_comparison"]["calibrated_scores_sha256"],
        "v04_coefficients": manifest["isotonic_comparison"]["coefficients_sha256"],
        "public_tasks": manifest["dataset_lineage"]["public_tasks_sha256"],
        "extraction_receipt": manifest["dataset_lineage"]["extraction_receipt_sha256"],
        "constraint_H": manifest["dataset_lineage"]["constraint_H_sha256"],
        "identity_model": manifest["dataset_lineage"]["identity_model_sha256"],
        "q_mix_manifest": manifest["dataset_lineage"]["q_mixture_manifest_sha256"],
        "support_manifest": manifest["dataset_lineage"]["sensor_support_manifest_sha256"],
        "q_dataset_manifest": manifest["dataset_lineage"]["q_dataset_manifest_sha256"],
        "selected_candidates": manifest["dataset_lineage"]["selected_candidates_sha256"],
        "q_checkpoint": manifest["dataset_lineage"]["q_fitted_checkpoint_sha256"],
    }
    hashes = {key: require_hash(paths[key], digest, key) for key, digest in expected.items()}
    v03_receipt, v04_receipt = load_json(paths["v03_receipt"]), load_json(paths["v04_receipt"])
    v03_report, v04_report = load_json(paths["v03_report"]), load_json(paths["v04_report"])
    if v03_receipt.get("status") != "COMPLETE" or v04_receipt.get("status") != "COMPLETE":
        raise ValueError("raw or isotonic semantic run is incomplete")
    if v04_receipt.get("train_only_fit") is not True or v04_receipt.get("validation_or_test_labels_used_for_fit") is not False:
        raise ValueError("v04 isotonic fit receipt violates train-only contract")
    for receipt, paths_to_check in (
        (v03_receipt, ("v03_scores",)),
        (v04_receipt, ("v04_scores", "v04_coefficients")),
    ):
        output_hashes = {item["path"]: item["sha256"] for item in receipt["output_files"]}
        for key in paths_to_check:
            if output_hashes.get(paths[key].name) != base.sha256(paths[key]):
                raise ValueError(f"upstream receipt output hash mismatch for {key}")
    data_manifest = load_json(paths["q_dataset_manifest"])
    if data_manifest.get("selected_candidates_sha256") != hashes["selected_candidates"]:
        raise ValueError("prepared Q data does not bind selected-candidate file")
    if v03_report.get("lineage", {}).get("inputs_sha256", {}).get("q_dataset_manifest") != hashes["q_dataset_manifest"]:
        raise ValueError("v03 semantic report does not bind this Q dataset")
    if v04_report.get("lineage", {}).get("v03_receipt_sha256") != hashes["v03_receipt"]:
        raise ValueError("v04 calibration report does not bind the raw v03 result")
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing logistic-calibration output: {args.output}")

    raw_rows = base.read_jsonl(paths["v03_scores"])
    isotonic_rows = base.read_jsonl(paths["v04_scores"])
    selected_rows = base.read_jsonl(paths["selected_candidates"])
    if len(raw_rows) != 594 or len(isotonic_rows) != len(raw_rows) or len(selected_rows) != len(raw_rows):
        raise ValueError("raw, isotonic, and selected Q candidate row counts differ from frozen dataset")
    for i, (raw, iso, selected) in enumerate(zip(raw_rows, isotonic_rows, selected_rows, strict=True)):
        for name in ("sample_id", "task_id", "feature_id", "family_id", "split", "source_kind"):
            if raw[name] != iso[name] or raw[name] != selected[name]:
                raise ValueError(f"candidate row {i} {name} mismatch across raw/isotonic/Q rows")
        if int(raw["posthoc_valid"]) != int(selected["posthoc_valid"]):
            raise ValueError(f"candidate row {i} validator label mismatch")
    splits = np.asarray([row["split"] for row in raw_rows], dtype="U10")
    labels = np.asarray([int(row["posthoc_valid"]) for row in selected_rows], dtype=np.uint8)
    train_indices = np.flatnonzero(splits == "train")
    train_families = {raw_rows[i]["family_id"] for i in train_indices}
    if len(train_indices) != 520 or int(labels[train_indices].sum()) != 260:
        raise ValueError("frozen Q training split support changed")
    for split in ("validation", "test"):
        if train_families & {row["family_id"] for row in raw_rows if row["split"] == split}:
            raise ValueError(f"family leakage from train into {split}")

    raw_score = log_scores(raw_rows)
    finite_train = raw_score[train_indices][np.isfinite(raw_score[train_indices])]
    if not len(finite_train):
        raise ValueError("no finite semantic training score for logistic calibration")
    finite_scale = max(float(np.std(finite_train, dtype=np.float64)), 1.0)
    floor = float(np.min(finite_train) - finite_scale)
    transformed = raw_score.copy()
    transformed[~np.isfinite(transformed)] = floor
    train_x = transformed[train_indices]
    center = float(np.mean(train_x, dtype=np.float64))
    scale = max(float(np.std(train_x, dtype=np.float64)), 1.0e-12)
    standardized = (transformed - center) / scale
    slope, intercept, fit_info = fit_logistic(standardized[train_indices], labels[train_indices])
    logits = intercept + slope * standardized
    logistic_probability = sigmoid(logits)
    if slope <= 0 or np.any(np.diff(np.sort(logistic_probability)) < 0):
        raise AssertionError("logistic calibration violated monotone ordering")
    isotonic_probability = np.asarray([float(row["calibrated_validity_probability"]) for row in isotonic_rows])
    raw_probability = np.asarray([float(row["raw_semantic_probability"]) for row in isotonic_rows])
    q_probability = np.asarray([float(row["q_v02_probability"]) for row in raw_rows])
    oracle_probability = np.asarray([float(row["private_kind_oracle_probability"]) for row in raw_rows])
    probabilities = {
        "raw_identity_composition": raw_probability,
        "isotonic_confidence_v04": isotonic_probability,
        "logistic_confidence_v06": logistic_probability,
        "q_v02": q_probability,
        "private_kind_oracle": oracle_probability,
    }
    rankings = {
        "raw_identity_composition": raw_score,
        "isotonic_confidence_v04": isotonic_probability,
        "logistic_confidence_v06": logits,
        "q_v02": q_probability,
        "private_kind_oracle": oracle_probability,
    }
    metrics_by_split = {
        split: score_metrics(np.flatnonzero(splits == split), raw_rows, labels, probabilities, rankings)
        for split in ("train", "validation", "test")
    }

    support = load_json(support_path)
    identity_train_families = {row["family_id"] for row in support["family_roster"] if row["split"] == "train"}
    test_families = {row["family_id"] for row in raw_rows if row["split"] == "test"}
    strata = {"overlap_sensor_identity_train": [], "unseen_to_identity_train": []}
    for family in sorted(test_families):
        strata["overlap_sensor_identity_train" if family in identity_train_families else "unseen_to_identity_train"].append(family)
    if {key: len(value) for key, value in strata.items()} != {"overlap_sensor_identity_train": 2, "unseen_to_identity_train": 2}:
        raise ValueError(f"identity-sensor overlap family support changed: {strata}")
    test_strata = {}
    for name, family_ids in strata.items():
        indices = np.asarray([i for i, row in enumerate(raw_rows) if row["split"] == "test" and row["family_id"] in family_ids], dtype=np.int64)
        test_strata[name] = score_metrics(indices, raw_rows, labels, probabilities, rankings)
        test_strata[name]["families"] = family_ids
    if {key: value["rows"] for key, value in test_strata.items()} != {
        "overlap_sensor_identity_train": 11, "unseen_to_identity_train": 13
    }:
        raise ValueError("identity-sensor test row counts changed from raw v03 manifest")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    training_ids = "\n".join(str(raw_rows[i]["sample_id"]) for i in train_indices).encode("utf-8")
    training_ids_sha = hashlib.sha256(training_ids).hexdigest()
    coefficient_path = output / "logistic-calibration-f64le.bin"
    export_info = export_calibration(coefficient_path, floor, center, scale, slope, intercept,
                                     hashes["v03_scores"], training_ids_sha)
    shutil.copyfile(isotonic_run / "identity-head-f32le.bin", output / "identity-head-f32le.bin")
    shutil.copyfile(isotonic_run / "identity-head-export.json", output / "identity-head-export.json")
    reference, reference_parity = make_rust_reference(raw_rows, raw_run, run_root,
                                                       output / "identity-head-export.json")
    reference_path = output / "rust-composition-reference-v01.json"
    reference_path.write_text(json.dumps(base.json_safe(reference), indent=2, sort_keys=True, allow_nan=False) + "\n",
                              encoding="utf-8")
    coeff_rows = np.frombuffer(coefficient_path.read_bytes(), dtype="<f8", count=5)
    restored_floor, restored_center, restored_scale, restored_slope, restored_intercept = map(float, coeff_rows)
    restored_x = raw_score.copy()
    restored_x[~np.isfinite(restored_x)] = restored_floor
    restored_logits = restored_intercept + restored_slope * ((restored_x - restored_center) / restored_scale)
    restored_probability = sigmoid(restored_logits)
    parity_error = float(np.max(np.abs(restored_probability - logistic_probability)))
    if parity_error > 1.0e-12:
        raise ValueError(f"exported logistic coefficients fail Python readback parity: {parity_error}")
    export_info["python_binary_readback_max_abs_probability_error"] = parity_error
    (output / "logistic-calibration-export.json").write_text(
        json.dumps(export_info, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    score_output = output / "candidate-scores-logistic.jsonl"
    rows_out = []
    for i, row in enumerate(raw_rows):
        rows_out.append({
            "sample_id": row["sample_id"], "task_id": row["task_id"], "feature_id": row["feature_id"],
            "family_id": row["family_id"], "split": row["split"], "source_kind": row["source_kind"],
            "posthoc_valid": labels[i], "semantic_log_score": raw_score[i],
            "raw_semantic_probability": raw_probability[i], "isotonic_confidence_v04": isotonic_probability[i],
            "logistic_logit_v06": logits[i], "logistic_confidence_v06": logistic_probability[i],
            "q_v02_probability": q_probability[i],
        })
    base.write_jsonl(score_output, rows_out)
    report = {
        "schema": "R1_QTERMINAL_SEMANTIC_LOGISTIC_REPORT_V06", "status": "TRAIN_ONLY_LOGISTIC_CALIBRATION_COMPLETE",
        "fit": {"fit_split": "train only", "validation_or_test_labels_used_for_fit": False,
                "training_rows": int(len(train_indices)), "training_family_count": len(train_families),
                "positive_count": int(labels[train_indices].sum()), "negative_count": int(len(train_indices) - labels[train_indices].sum()),
                "training_sample_ids_sha256": training_ids_sha, "score_floor": floor,
                "score_center": center, "score_scale": scale, **fit_info},
        "metrics_by_split": metrics_by_split, "test_strata": test_strata,
        "test_group_row_counts": {key: value["rows"] for key, value in test_strata.items()},
        "selection_interpretation": "Keep raw semantic log score as selector score. Logistic confidence is strictly monotone in the raw score and is suitable as a confidence output; v04 isotonic probability alone can tie distinct raw scores.",
        "test_generalization_warning": "four test families split into 11 rows overlapping identity training and 13 unseen to identity training; aggregate test is not unseen generalization",
        "runtime_export": export_info,
        "rust_reference_vector": {"path": reference_path.name, "sha256": base.sha256(reference_path),
                                   "parity": reference_parity},
        "lineage": {"manifest_sha256": manifest_sha, "input_sha256": hashes,
                    "v03_identity_head_sha256": base.sha256(output / "identity-head-f32le.bin"),
                    "v03_identity_head_metadata_sha256": base.sha256(output / "identity-head-export.json")},
        "comparison": {"v03_raw_is_selector_candidate": True, "v04_isotonic_used_as_comparison_only": True,
                       "q_v02_retrained_or_modified": False, "v03_or_v04_modified": False},
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(base.json_safe(report), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    artifacts = [score_output, report_path, reference_path, coefficient_path, output / "logistic-calibration-export.json",
                 output / "identity-head-f32le.bin", output / "identity-head-export.json"]
    receipt = {
        "schema": "R1_QTERMINAL_SEMANTIC_LOGISTIC_RECEIPT_V06", "status": "COMPLETE",
        "manifest_sha256": manifest_sha, "source_script_sha256": base.sha256(Path(__file__).resolve()),
        "source_root": str(source_root), "run_root": str(run_root), "input_sha256": hashes,
        "output_files": [{"path": path.name, "bytes": path.stat().st_size, "sha256": base.sha256(path)} for path in artifacts],
        "report_sha256": base.sha256(report_path), "train_only_fit": True,
        "validation_or_test_labels_used_for_fit": False, "regularization_lambda": L2_LAMBDA,
        "q_v02_modified": False, "v03_raw_result_modified": False, "v04_isotonic_result_modified": False,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "receipt_sha256": base.sha256(output / "receipt.json"),
                      "report_sha256": receipt["report_sha256"], "fit": report["fit"],
                      "validation": metrics_by_split["validation"]["binary_metrics"],
                      "test": metrics_by_split["test"]["binary_metrics"],
                      "test_strata": {key: value["binary_metrics"] for key, value in test_strata.items()},
                      "test_top1": {key: value["top1_metrics_by_feature_and_source"] for key, value in test_strata.items()}},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
