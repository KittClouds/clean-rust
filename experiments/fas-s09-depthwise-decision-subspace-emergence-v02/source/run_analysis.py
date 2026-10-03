from __future__ import annotations

import gc
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import numpy as np
import torch

from linear_core import classification_metrics, configure_determinism, feature_scaler, fit_probe, predict_probabilities, standardized_tensor
from s01_common_reference import fit_masks, load_metadata_npz, test_condition_masks
from s09_common import DIMENSION, EVENTS, LAYERS, RUN_ROOT, S01_2_ROOT, read_json, sha256_file, tree_root, write_json
from s09_math import effective_geometry, logits_from_standardized, margin_summaries, subspace_comparison, transition_table


CONDITIONS = (
    "IN_DOMAIN_TRAIN_SIDE_TERMS_SEEN_TEMPLATES",
    "CONTEXT_NOVEL_ONLY_SEEN_TEMPLATES",
    "ENTITY_NOVEL_ONLY_SEEN_TEMPLATES",
    "BOTH_TERMS_NOVEL_SEEN_TEMPLATES",
    "OBSERVATION_TEMPLATE_NOVEL_ONLY_TRAIN_SIDE_TERMS",
    "QUERY_TEMPLATE_NOVEL_ONLY_TRAIN_SIDE_TERMS",
    "BOTH_TEMPLATES_NOVEL_TRAIN_SIDE_TERMS",
    "ANY_TEMPLATE_NOVEL_TRAIN_SIDE_TERMS",
    "CONTEXT_NOVEL_X_ANY_TEMPLATE_NOVEL",
    "ENTITY_NOVEL_X_ANY_TEMPLATE_NOVEL",
    "BOTH_TERMS_NOVEL_X_ANY_TEMPLATE_NOVEL",
)
CELL_NAMES = ("M_NATIVE", "F_NATIVE", "M_REP_F_PIPELINE", "F_REP_M_PIPELINE")
SURFACE_FOR_CELL = {"M_NATIVE": "M", "F_NATIVE": "F", "M_REP_F_PIPELINE": "M", "F_REP_M_PIPELINE": "F"}
PIPELINE_FOR_CELL = {"M_NATIVE": "M", "F_NATIVE": "F", "M_REP_F_PIPELINE": "F", "F_REP_M_PIPELINE": "M"}


def verify_feature_cache() -> dict[str, Any]:
    cache_root = RUN_ROOT / "feature-cache-v02"
    seal = read_json(cache_root / "feature-cache-seal-v02.json")
    actual = []
    for item in seal["entries"]:
        path = cache_root.joinpath(*item["path"].split("/"))
        digest, size = sha256_file(path)
        actual.append({"path": item["path"], "bytes": size, "sha256": digest})
    actual.sort(key=lambda item: item["path"])
    if actual != seal["entries"] or tree_root(actual) != seal["root_sha256"]:
        raise RuntimeError("S09 feature cache failed sealed hash verification")
    receipt = read_json(RUN_ROOT / "extraction-receipt-v02.json")
    if receipt.get("backbone_parameter_delta") != 0 or receipt.get("terminal_parent_parity", {}).get("max_abs_error") != 0.0:
        raise RuntimeError("S09 extraction receipt does not establish terminal feature parity and backbone immutability")
    return {"feature_cache_root_sha256": seal["root_sha256"], "matrices_verified": len(actual)}


def load_probe_reference(surface: str) -> dict[str, np.ndarray]:
    path = RUN_ROOT / "inputs" / "S01-3" / "terminal-reference" / f"{surface}-probe-state.npz"
    with np.load(path, allow_pickle=False) as data:
        return {key: data[key].copy() for key in data.files}


def save_probe(path: Path, fit: dict[str, Any], mean: np.ndarray, scale: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        classes=np.asarray(fit["classes"], dtype="<i8"),
        weights=np.asarray(fit["weights"], dtype="<f4"),
        bias=np.asarray(fit["bias"], dtype="<f4"),
        scaler_mean=np.asarray(mean, dtype="<f8"),
        scaler_scale=np.asarray(scale, dtype="<f8"),
    )


def save_array(path: Path, value: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, np.asarray(value, dtype="<f4"), allow_pickle=False)


def load_matrix(layer: int, surface: str) -> np.memmap:
    path = RUN_ROOT / "feature-cache-v02" / f"layer-{layer:02d}-{surface}.f32le"
    return np.memmap(path, dtype="<f4", mode="r", shape=(EVENTS, DIMENSION), order="C")


def metric_bundle(probabilities: np.ndarray, logits: np.ndarray, labels: np.ndarray, conditions: dict[str, np.ndarray]) -> dict[str, Any]:
    metrics: dict[str, Any] = {"ALL_TEST_ROWS": classification_metrics(labels, probabilities, np.array([0, 1, 2], dtype=np.int64))}
    margins: dict[str, Any] = {"ALL_TEST_ROWS": margin_summaries(logits, labels)}
    for name in CONDITIONS:
        mask = conditions[name]
        if not bool(mask.any()):
            raise RuntimeError(f"sealed S01 test condition has no rows: {name}")
        metrics[name] = classification_metrics(labels[mask], probabilities[mask], np.array([0, 1, 2], dtype=np.int64))
        margins[name] = margin_summaries(logits[mask], labels[mask])
    return {"metrics": metrics, "margins": margins}


def fit_one(layer: int, surface: str, metadata: dict[str, np.ndarray], train_rows: np.ndarray, test_rows: np.ndarray, device: torch.device, root: Path) -> dict[str, Any]:
    matrix = load_matrix(layer, surface)
    mean, scale = feature_scaler(matrix, train_rows, chunk_rows=2048)
    x_train = standardized_tensor(matrix, train_rows, mean, scale, device)
    labels = metadata["target"]
    fit_state = fit_probe(
        x_train,
        labels[train_rows],
        regularization=1e-4,
        max_iter=300,
        max_eval=375,
        tolerance_grad=1e-7,
        tolerance_change=1e-9,
        history_size=10,
    )
    classes = np.asarray(fit_state["classes"], dtype=np.int64)
    if not np.array_equal(classes, np.array([0, 1, 2], dtype=np.int64)):
        raise RuntimeError(f"target class ordering differs at layer {layer} surface {surface}: {classes}")
    x_test = standardized_tensor(matrix, test_rows, mean, scale, device)
    probs = predict_probabilities(x_test, fit_state["weights"], fit_state["bias"], batch_rows=16384)
    logits = logits_from_standardized(x_test, fit_state["weights"], fit_state["bias"], batch_rows=16384)
    state_path = root / "probes" / f"layer-{layer:02d}" / surface / "probe-state-v02.npz"
    save_probe(state_path, fit_state, mean, scale)
    for key in ("objective", "gradient_norm", "iterations", "function_evaluations", "iteration_limit_reached"):
        if key == "objective":
            fit_state[key] = float(fit_state[key])
        elif key == "gradient_norm":
            fit_state[key] = float(fit_state[key])
        elif key in ("iterations", "function_evaluations"):
            fit_state[key] = int(fit_state[key])
        else:
            fit_state[key] = bool(fit_state[key])
    fit_state["classes"] = classes
    fit_state["mean"] = mean
    fit_state["scale"] = scale
    fit_state["probabilities"] = probs
    fit_state["logits"] = logits
    fit_state["state_path"] = state_path
    fit_state["fit_rows"] = int(len(train_rows))
    del x_train, x_test, matrix
    gc.collect()
    torch.cuda.empty_cache()
    return fit_state


def compare_terminal(surface: str, fit: dict[str, Any], reference_metrics: dict[str, Any], conditions: dict[str, np.ndarray], labels: np.ndarray, test_rows: np.ndarray) -> dict[str, Any]:
    reference_state = load_probe_reference(surface)
    candidates = {
        "classes": np.asarray(fit["classes"], dtype="<i8"),
        "weights": np.asarray(fit["weights"], dtype="<f4"),
        "bias": np.asarray(fit["bias"], dtype="<f4"),
        "scaler_mean": np.asarray(fit["mean"], dtype="<f8"),
        "scaler_scale": np.asarray(fit["scale"], dtype="<f8"),
    }
    for key, value in candidates.items():
        if not np.array_equal(value, reference_state[key]):
            raise RuntimeError(f"terminal layer {surface} probe state does not exactly reproduce S01-3: {key}")
    expected_prob = np.load(RUN_ROOT / "inputs" / "S01-3" / "terminal-reference" / f"{surface}-probabilities.npy", allow_pickle=False)
    if not np.array_equal(np.asarray(fit["probabilities"], dtype="<f4"), expected_prob):
        delta = float(np.max(np.abs(np.asarray(fit["probabilities"], dtype=np.float64) - expected_prob.astype(np.float64))))
        raise RuntimeError(f"terminal layer {surface} probabilities do not exactly reproduce S01-3; max_abs={delta}")
    calculated = metric_bundle(fit["probabilities"], fit["logits"], labels, conditions)
    expected_rows = [row for row in reference_metrics["metrics"] if row["view"] == ("V0_MEAN_FULL" if surface == "M" else "V1_FINAL_POSITION") and row["task"] == "EXACT_TARGET"]
    if len(expected_rows) != 1:
        raise RuntimeError(f"S01-3 terminal metric row is ambiguous for {surface}")
    if calculated["metrics"] != expected_rows[0]["conditions"]:
        raise RuntimeError(f"terminal layer {surface} metrics differ from S01-3 sealed metrics")
    return {
        "surface": surface,
        "probe_arrays_exact": True,
        "probabilities_exact": True,
        "metric_conditions_exact": True,
        "test_row_count": int(len(test_rows)),
        "fit_rows": int(fit["fit_rows"]),
        "max_probability_abs_delta": 0.0,
    }


def state_for_subspace(fit: dict[str, Any]) -> dict[str, np.ndarray]:
    return {
        "weights": np.asarray(fit["weights"], dtype=np.float32),
        "bias": np.asarray(fit["bias"], dtype=np.float32),
        "mean": np.asarray(fit["mean"], dtype=np.float64),
        "scale": np.asarray(fit["scale"], dtype=np.float64),
    }


def apply_pipeline(surface: str, pipeline: dict[str, Any], test_rows: np.ndarray, device: torch.device) -> tuple[np.ndarray, np.ndarray]:
    matrix = load_matrix(pipeline["layer"], surface)
    x = standardized_tensor(matrix, test_rows, pipeline["mean"], pipeline["scale"], device)
    probabilities = predict_probabilities(x, pipeline["weights"], pipeline["bias"], batch_rows=16384)
    logits = logits_from_standardized(x, pipeline["weights"], pipeline["bias"], batch_rows=16384)
    del matrix, x
    gc.collect()
    torch.cuda.empty_cache()
    return probabilities, logits


def write_cell(root: Path, layer: int, cell: str, probabilities: np.ndarray, logits: np.ndarray, labels: np.ndarray, conditions: dict[str, np.ndarray]) -> dict[str, Any]:
    folder = root / "predictions" / f"layer-{layer:02d}" / cell
    save_array(folder / "probabilities.npy", probabilities)
    save_array(folder / "logits.npy", logits)
    return metric_bundle(probabilities, logits, labels, conditions)


def main() -> int:
    if (RUN_ROOT / "analysis-seal-v02.json").exists() or (RUN_ROOT / "metrics-v02.json").exists():
        raise RuntimeError("S09 analysis already exists; refusing in-place rerun")
    cache_receipt = verify_feature_cache()
    preflight = read_json(RUN_ROOT / "seals" / "preflight-seal-v02.json")
    preflight_receipt = read_json(RUN_ROOT / "parent-verification-receipt-v02.json")
    protocol_seal = read_json(RUN_ROOT / "inputs" / "project-snapshot" / "seals" / "protocol-seal-v02.json")
    if protocol_seal.get("root_sha256") != preflight_receipt.get("project_protocol_root_sha256"):
        raise RuntimeError("S09 project snapshot protocol identity differs from preflight receipt")
    device = configure_determinism()
    metadata = load_metadata_npz(RUN_ROOT / "inputs" / "S01-3" / "event-metadata-v01.npz")
    train_mask, test_mask = fit_masks(metadata, "EXACT_TARGET")
    train_rows = np.flatnonzero(train_mask).astype(np.int64, copy=False)
    test_rows = np.flatnonzero(test_mask).astype(np.int64, copy=False)
    if len(train_rows) != 12769 or len(test_rows) != 21272:
        raise RuntimeError(f"sealed S01 target split counts changed: train={len(train_rows)} test={len(test_rows)}")
    test_meta = {name: values[test_mask] for name, values in metadata.items()}
    condition_masks = test_condition_masks(test_meta, "EXACT_TARGET")
    if tuple(condition_masks) != CONDITIONS:
        raise RuntimeError("S01 exact-target condition set or order differs from the frozen S09 contract")
    labels = np.asarray(metadata["target"][test_rows], dtype=np.int64)
    expected_classes = np.unique(metadata["target"])
    if not np.array_equal(expected_classes, np.array([0, 1, 2], dtype=np.int64)):
        raise RuntimeError("S01 exact-target class order differs from S09 contract")
    event_ids = metadata["event_id"][test_rows]
    test_manifest_path = RUN_ROOT / "inputs" / "S01-3" / "test-events-v01.jsonl"
    manifest_ids = [json.loads(line)["event_id"].encode("ascii") for line in test_manifest_path.read_text(encoding="utf-8").splitlines()]
    if not np.array_equal(event_ids, np.asarray(manifest_ids, dtype=metadata["event_id"].dtype)):
        raise RuntimeError("S01-3 held-out row order differs from frozen test event manifest")
    ref_metrics = read_json(RUN_ROOT / "inputs" / "S01-3" / "metrics-v01.json")
    output_root = RUN_ROOT / "analysis-v02"
    output_root.mkdir(parents=True, exist_ok=False)
    for folder in ("probes", "predictions"):
        (output_root / folder).mkdir()

    started = time.perf_counter()
    fits: dict[tuple[int, str], dict[str, Any]] = {}
    terminal_checks = []
    # The final layer is a hard gate before any earlier-layer fitting or interpretation.
    for surface in ("M", "F"):
        fit = fit_one(16, surface, metadata, train_rows, test_rows, device, output_root)
        terminal_checks.append(compare_terminal(surface, fit, ref_metrics, condition_masks, labels, test_rows))
        fits[(16, surface)] = fit
    s08_file = np.load(RUN_ROOT / "inputs" / "S08" / "s01-native-decision-geometry-v02.npz", allow_pickle=False)
    s08_planes = {
        "M": {"basis": s08_file["M_basis"], "rank": int(s08_file["M_basis"].shape[0])},
        "F": {"basis": s08_file["F_basis"], "rank": int(s08_file["F_basis"].shape[0])},
    }
    terminal_s08_checks = {}
    s08_pair_residuals = {}
    for surface in ("M", "F"):
        geometry = effective_geometry(**state_for_subspace(fits[(16, surface)]))
        comparison = subspace_comparison(geometry, s08_planes[surface])
        stored_pairs = np.asarray(s08_file[f"{surface}_pair_normals"], dtype=np.float64)
        pair_residual = float(np.max(np.abs(geometry["pair_normals"] - stored_pairs)))
        s08_pair_residuals[surface] = pair_residual
        if pair_residual > 1e-12:
            raise RuntimeError(f"layer-16 {surface} effective pair normals fail S08 identity: max_abs={pair_residual}")
        if any(angle > 1e-6 for angle in comparison["principal_angle_degrees"]):
            raise RuntimeError(f"layer-16 {surface} plane fails S08 terminal reproduction: {comparison}")
        terminal_s08_checks[surface] = comparison

    # Earlier layers are fitted only after exact terminal state, prediction, metric, and S08 plane reproduction.
    for layer in range(1, 16):
        for surface in ("M", "F"):
            fits[(layer, surface)] = fit_one(layer, surface, metadata, train_rows, test_rows, device, output_root)
        print(f"fitted_layer={layer}/16 elapsed_seconds={time.perf_counter()-started:.1f}", flush=True)

    layer_rows: list[dict[str, Any]] = []
    full_predictions: dict[tuple[int, str], np.ndarray] = {}
    for layer in LAYERS:
        geometries = {surface: effective_geometry(**state_for_subspace(fits[(layer, surface)])) for surface in ("M", "F")}
        inter_surface = subspace_comparison(geometries["M"], geometries["F"])
        convergences = {
            surface: subspace_comparison(geometries[surface], s08_planes[surface])
            for surface in ("M", "F")
        }
        cell_outputs: dict[str, tuple[np.ndarray, np.ndarray, dict[str, Any]]] = {}
        for cell in CELL_NAMES:
            rep_surface = SURFACE_FOR_CELL[cell]
            pipe_surface = PIPELINE_FOR_CELL[cell]
            pipeline = fits[(layer, pipe_surface)]
            probabilities, logits = apply_pipeline(rep_surface, pipeline, test_rows, device)
            bundle = write_cell(output_root, layer, cell, probabilities, logits, labels, condition_masks)
            cell_outputs[cell] = (probabilities, logits, bundle)
            full_predictions[(layer, cell)] = probabilities.argmax(axis=1).astype(np.int64, copy=False)

        native_transition = transition_table(labels, full_predictions[(layer, "M_NATIVE")], full_predictions[(layer, "F_NATIVE")])
        m_transport = transition_table(labels, full_predictions[(layer, "M_NATIVE")], full_predictions[(layer, "M_REP_F_PIPELINE")])
        f_transport = transition_table(labels, full_predictions[(layer, "F_NATIVE")], full_predictions[(layer, "F_REP_M_PIPELINE")])
        row = {
            "layer": layer,
            "native_M_rank": geometries["M"]["rank"],
            "native_F_rank": geometries["F"]["rank"],
            "native_M_singular_values": np.asarray(geometries["M"]["singular_values"]).tolist(),
            "native_F_singular_values": np.asarray(geometries["F"]["singular_values"]).tolist(),
            "M_vs_F_plane": inter_surface,
            "convergence_to_S08_terminal_plane": convergences,
            "cells": {cell: cell_outputs[cell][2] for cell in CELL_NAMES},
            "paired_prediction_transitions": {
                "M_native_vs_F_native": native_transition,
                "M_native_vs_M_with_F_pipeline": m_transport,
                "F_native_vs_F_with_M_pipeline": f_transport,
            },
            "probe_fit": {
                surface: {
                    "fit_rows": int(len(train_rows)),
                    "fit_objective": fits[(layer, surface)]["objective"],
                    "final_gradient_norm": fits[(layer, surface)]["gradient_norm"],
                    "optimizer_iterations": fits[(layer, surface)]["iterations"],
                    "optimizer_function_evaluations": fits[(layer, surface)]["function_evaluations"],
                    "optimizer_iteration_limit_reached": fits[(layer, surface)]["iteration_limit_reached"],
                }
                for surface in ("M", "F")
            },
        }
        layer_rows.append(row)
        print(f"analyzed_layer={layer}/16 M_BA={row['cells']['M_NATIVE']['metrics']['ALL_TEST_ROWS']['balanced_accuracy']:.6f} F_BA={row['cells']['F_NATIVE']['metrics']['ALL_TEST_ROWS']['balanced_accuracy']:.6f} angle={inter_surface['principal_angle_degrees']}", flush=True)

    metrics = {
        "disposition": "COMPLETE_EXPLORATORY_DEPTHWISE_ACCESSIBILITY_AND_SUBSPACE_CARTOGRAPHY",
        "feature_cache_root_sha256": cache_receipt["feature_cache_root_sha256"],
        "rows": {"fit": len(train_rows), "test": len(test_rows), "test_quartets": len(test_rows) // 4},
        "test_condition_support": {name: int(mask.sum()) for name, mask in condition_masks.items()},
        "terminal_gate": {
            "S01_probe_state_probability_and_metrics_reproduced_exactly": True,
            "S08_terminal_plane_reproduced_within_tolerance": True,
            "S08_plane_comparisons": terminal_s08_checks,
            "S08_pair_normal_max_abs_residuals": s08_pair_residuals,
            "surface_checks": terminal_checks,
        },
        "layers": layer_rows,
        "interpretation_limits": [
            "The S01 grouped test split was already revealed; this depthwise study is exploratory, not confirmatory.",
            "Layerwise probe accessibility is a fixed linear observer result, not evidence of semantic representation absence when a probe is weak.",
            "Subspace comparisons use indexed 2048-dimensional residual coordinates across layer outputs; they describe observer geometry and do not identify transformer circuits.",
            "Cross-surface cells transport the complete donor scaler-plus-probe without refitting.",
            "No categorical emergence threshold, significance test, layer selection, or FAS-00 analysis was performed.",
        ],
        "execution_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(RUN_ROOT / "metrics-v02.json", metrics)
    receipt = {
        "receipt_id": "FAS_S09_ANALYSIS_RECEIPT_V02",
        "complete": True,
        "feature_cache_root_sha256": cache_receipt["feature_cache_root_sha256"],
        "terminal_gate_passed_before_intermediate_fits": True,
        "probe_fits": 32,
        "cells_per_layer": 4,
        "fas00_artifacts_read": False,
        "adaptive_mechanisms_authorized": False,
        "fas00_phase4_authorized": False,
    }
    write_json(RUN_ROOT / "analysis-execution-receipt-v02.json", receipt)
    entries = [entry_for(path, output_root) for path in output_root.rglob("*") if path.is_file()]
    entries.sort(key=lambda item: item["path"])
    write_json(output_root / "analysis-seal-v02.json", {"seal_id": "FAS_S09_ANALYSIS_SEAL_V02", "entries": entries, "root_sha256": tree_root(entries)})
    print(f"analysis_complete layers={len(layer_rows)} fits=32 elapsed_seconds={metrics['execution_seconds']}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        if RUN_ROOT.exists() and not (RUN_ROOT / "analysis-failure-v02.json").exists():
            write_json(RUN_ROOT / "analysis-failure-v02.json", {
                "stage": "ANALYSIS",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "intermediate_layer_fits_authorized": True,
                "result_ready": False,
            })
        raise
