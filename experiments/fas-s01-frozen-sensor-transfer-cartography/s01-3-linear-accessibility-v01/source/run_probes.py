from __future__ import annotations

import os
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import gc
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch

from common import (
    BINDING_PATH,
    CONTRACT_PATH,
    PHASE_ROOT,
    PARENT_CACHE_ROOT,
    RESULT_ROOT,
    TASKS,
    TASK_LABEL_FIELDS,
    VIEWS,
    feature_cache_paths,
    file_entry,
    fit_masks,
    load_metadata_npz,
    read_json,
    sha256_file,
    task_classes,
    test_condition_masks,
    tree_root,
    verify_entries,
    write_json,
)
from linear_core import (
    classification_metrics,
    configure_determinism,
    feature_scaler,
    fit_probe,
    predict_probabilities,
    standardized_tensor,
)


def _verify_prefit_seal() -> dict[str, Any]:
    seal_path = RESULT_ROOT / "seals" / "preflight-seal-v01.json"
    disposition_path = RESULT_ROOT / "preflight-disposition-v01.json"
    if not seal_path.is_file() or not disposition_path.is_file():
        raise RuntimeError("sealed S01-3 preflight packet is missing")
    seal = read_json(seal_path)
    disposition = read_json(disposition_path)
    if disposition.get("preflight_root_sha256") != seal.get("root_sha256"):
        raise RuntimeError("S01-3 preflight disposition names a different root")
    actual = verify_entries(RESULT_ROOT, seal["entries"])
    if tree_root(actual) != seal["root_sha256"]:
        raise RuntimeError("S01-3 preflight packet no longer matches its seal")
    for name in ("linear-accessibility-contract-v01.json", "input-binding-v01.json", "authorization-packet-v01.json"):
        project = PHASE_ROOT / "contracts" / name
        snapshot = RESULT_ROOT / "inputs" / "contracts" / name
        if sha256_file(project)[0] != sha256_file(snapshot)[0]:
            raise RuntimeError(f"project and sealed contract snapshot differ: {name}")
    if sha256_file(PHASE_ROOT / "S01-3-PROTOCOL.md")[0] != sha256_file(RESULT_ROOT / "inputs" / "S01-3-PROTOCOL.md")[0]:
        raise RuntimeError("project and sealed protocol snapshot differ")
    for project in sorted((PHASE_ROOT / "source").glob("*.py")):
        snapshot = RESULT_ROOT / "inputs" / "source" / project.name
        if not snapshot.is_file() or sha256_file(project)[0] != sha256_file(snapshot)[0]:
            raise RuntimeError(f"project and sealed source snapshot differ: {project.name}")
    return seal


def _verify_cache_unchanged(binding: dict[str, Any]) -> dict[str, Any]:
    result_root, _, _, _ = feature_cache_paths(binding)
    cache_seal = read_json(result_root / "seals" / "feature-cache-seal-v01.json")
    entries = verify_entries(result_root, cache_seal["entries"])
    root = tree_root(entries)
    if root != binding["parent_roots"]["s01_2_feature_cache_root_sha256"]:
        raise RuntimeError("feature cache changed after sealed preflight")
    return {"feature_cache_root_sha256": root, "feature_cache_entries_verified_before_fit": len(entries)}


def _labels(fields: dict[str, np.ndarray], task: str) -> np.ndarray:
    return {
        "CONTEXT_IDENTITY": fields["context_id"],
        "ENTITY_IDENTITY": fields["entity_id"],
        "RELATION_IDENTITY": fields["relation"],
        "OBSERVED_STATE": fields["state"],
        "EXACT_TARGET": fields["target"],
    }[task]


def _save_probe_state(
    path: Path,
    fit: dict[str, object],
    mean: np.ndarray,
    scale: np.ndarray,
) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        classes=np.asarray(fit["classes"], dtype="<i8"),
        weights=np.asarray(fit["weights"], dtype="<f4"),
        bias=np.asarray(fit["bias"], dtype="<f4"),
        scaler_mean=np.asarray(mean, dtype="<f8"),
        scaler_scale=np.asarray(scale, dtype="<f8"),
    )
    return sha256_file(path)


def _save_probabilities(path: Path, probabilities: np.ndarray) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, np.asarray(probabilities, dtype="<f4"), allow_pickle=False)
    return sha256_file(path)


def _cache_matrix(cache_root: Path, view: str, dimension: int) -> np.memmap:
    path = cache_root / f"{view}.f32le"
    return np.memmap(path, dtype="<f4", mode="r", shape=(106496, dimension), order="C")


def run() -> dict[str, Any]:
    if (RESULT_ROOT / "run-execution-receipt-v01.json").exists():
        raise RuntimeError("S01-3 execution receipt already exists; refusing to overwrite sealed execution")
    if (RESULT_ROOT / "metrics-v01.json").exists() or any(
        path.is_file()
        for folder in ("predictions", "probes")
        for path in (RESULT_ROOT / folder).rglob("*")
    ):
        raise RuntimeError("partial or complete S01-3 model outputs exist; refusing in-place rerun")
    preflight_seal = _verify_prefit_seal()
    contract = read_json(CONTRACT_PATH)
    binding = read_json(BINDING_PATH)
    cache_status = _verify_cache_unchanged(binding)
    device = configure_determinism()
    metadata_path = RESULT_ROOT / "metadata" / "event-metadata-v01.npz"
    metadata = load_metadata_npz(metadata_path)
    test_mask = metadata["split_bucket"] == 0
    test_rows = metadata["row_index"][test_mask].astype(np.int64, copy=False)
    test_fields = {name: values[test_mask] for name, values in metadata.items()}
    identity_mask, _ = fit_masks(metadata, "CONTEXT_IDENTITY")
    transfer_mask, _ = fit_masks(metadata, "EXACT_TARGET")
    identity_rows = np.flatnonzero(identity_mask).astype(np.int64, copy=False)
    transfer_rows = np.flatnonzero(transfer_mask).astype(np.int64, copy=False)
    output_models: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    total_models = len(VIEWS) * len(TASKS)
    completed = 0

    _, cache_root, _, _ = feature_cache_paths(binding)
    for view_index, view in enumerate(VIEWS):
        dimension = int(contract["views"][view_index]["dimension"])
        matrix = _cache_matrix(cache_root, view, dimension)
        identity_mean, identity_scale = feature_scaler(
            matrix, identity_rows, int(contract["fit_protocol"]["standardization_chunk_rows"])
        )
        transfer_mean, transfer_scale = feature_scaler(
            matrix, transfer_rows, int(contract["fit_protocol"]["standardization_chunk_rows"])
        )
        x_test_raw = np.ascontiguousarray(matrix[test_rows], dtype=np.float32)
        if not np.isfinite(x_test_raw).all():
            raise RuntimeError(f"non-finite feature in test rows for {view}")
        x_test_base = torch.from_numpy(x_test_raw).to(device=device, dtype=torch.float32)
        del x_test_raw
        x_test_identity = x_test_base.clone()
        x_test_transfer = x_test_base.clone()
        del x_test_base
        x_test_identity.sub_(torch.as_tensor(identity_mean, dtype=torch.float32, device=device)).div_(
            torch.as_tensor(identity_scale, dtype=torch.float32, device=device)
        )
        x_test_transfer.sub_(torch.as_tensor(transfer_mean, dtype=torch.float32, device=device)).div_(
            torch.as_tensor(transfer_scale, dtype=torch.float32, device=device)
        )

        x_identity_raw = np.ascontiguousarray(matrix[identity_rows], dtype=np.float32)
        x_transfer_raw = np.ascontiguousarray(matrix[transfer_rows], dtype=np.float32)
        x_identity = torch.from_numpy(x_identity_raw).to(device=device, dtype=torch.float32)
        x_transfer = torch.from_numpy(x_transfer_raw).to(device=device, dtype=torch.float32)
        del x_identity_raw, x_transfer_raw
        x_identity.sub_(torch.as_tensor(identity_mean, dtype=torch.float32, device=device)).div_(
            torch.as_tensor(identity_scale, dtype=torch.float32, device=device)
        )
        x_transfer.sub_(torch.as_tensor(transfer_mean, dtype=torch.float32, device=device)).div_(
            torch.as_tensor(transfer_scale, dtype=torch.float32, device=device)
        )
        if (
            not bool(torch.isfinite(x_test_identity).all().item())
            or not bool(torch.isfinite(x_test_transfer).all().item())
            or not bool(torch.isfinite(x_identity).all().item())
            or not bool(torch.isfinite(x_transfer).all().item())
        ):
            raise RuntimeError(f"standardized test features are non-finite for {view}")

        for task in TASKS:
            fit_rows = identity_rows if task in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY") else transfer_rows
            x_fit = x_identity if task in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY") else x_transfer
            x_test = x_test_identity if task in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY") else x_test_transfer
            fit_mean = identity_mean if task in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY") else transfer_mean
            fit_scale = identity_scale if task in ("CONTEXT_IDENTITY", "ENTITY_IDENTITY") else transfer_scale
            labels = _labels(metadata, task)
            y_train = labels[fit_rows]
            solver = contract["fit_protocol"]["optimizer_parameters"]
            fit_state = fit_probe(
                x_fit,
                y_train,
                regularization=float(contract["fit_protocol"]["regularization_l2_coefficient"]),
                max_iter=int(solver["max_iter"]),
                max_eval=int(solver["max_eval"]),
                tolerance_grad=float(solver["tolerance_grad"]),
                tolerance_change=float(solver["tolerance_change"]),
                history_size=int(solver["history_size"]),
            )
            classes = np.asarray(fit_state["classes"], dtype=np.int64)
            if not np.array_equal(classes, task_classes(metadata, task)):
                raise RuntimeError(f"fitted class map differs from frozen class set for {task}")
            probabilities = predict_probabilities(
                x_test,
                fit_state["weights"],
                fit_state["bias"],
                batch_rows=int(contract["fit_protocol"]["prediction_batch_rows"]),
            )
            if probabilities.shape != (len(test_rows), len(classes)) or not np.isfinite(probabilities).all():
                raise RuntimeError(f"prediction shape or probability validity failed for {view}/{task}")
            if not np.allclose(probabilities.sum(axis=1), 1.0, rtol=0, atol=2e-6):
                raise RuntimeError(f"predicted probabilities do not sum to one for {view}/{task}")

            model_dir = RESULT_ROOT / "probes" / view / task
            prediction_path = RESULT_ROOT / "predictions" / view / task / "probabilities.npy"
            state_path = model_dir / "probe-state-v01.npz"
            state_sha, state_bytes = _save_probe_state(state_path, fit_state, fit_mean, fit_scale)
            prediction_sha, prediction_bytes = _save_probabilities(prediction_path, probabilities)
            model_meta = {
                "view": view,
                "task": task,
                "label_field": TASK_LABEL_FIELDS[task],
                "class_ids": [int(value) for value in classes],
                "fit_rows": int(len(fit_rows)),
                "test_rows_all_conditions": int(len(test_rows)),
                "fit_objective": fit_state["objective"],
                "final_gradient_norm": fit_state["gradient_norm"],
                "optimizer_iterations": fit_state["iterations"],
                "optimizer_function_evaluations": fit_state["function_evaluations"],
                "optimizer_iteration_limit_reached": fit_state["iteration_limit_reached"],
                "regularization_l2": float(contract["fit_protocol"]["regularization_l2_coefficient"]),
                "state_path": state_path.relative_to(RESULT_ROOT).as_posix(),
                "state_sha256": state_sha,
                "state_bytes": state_bytes,
                "predictions_path": prediction_path.relative_to(RESULT_ROOT).as_posix(),
                "predictions_sha256": prediction_sha,
                "predictions_bytes": prediction_bytes,
                "prediction_shape": list(probabilities.shape),
                "prediction_dtype": "<f4",
                "prediction_row_order": "metadata/test-events-v01.jsonl",
            }
            write_json(model_dir / "probe-metadata-v01.json", model_meta)
            output_models.append(model_meta)
            task_condition_metrics: dict[str, Any] = {}
            task_test_labels = _labels(test_fields, task)
            condition_masks = test_condition_masks(test_fields, task)
            for condition, condition_mask in condition_masks.items():
                result = classification_metrics(
                    task_test_labels[condition_mask],
                    probabilities[condition_mask],
                    classes,
                    float(contract["metrics"]["probability_floor"]),
                )
                result["interpretation_scope"] = "exploratory grouped holdout; no view selection"
                task_condition_metrics[condition] = result
            metric_rows.append({"view": view, "task": task, "label_field": TASK_LABEL_FIELDS[task], "conditions": task_condition_metrics})
            completed += 1
            print(f"S01-3 probe {completed}/{total_models}: {view} {task} complete")
            del fit_state, probabilities, condition_masks, task_condition_metrics
            gc.collect()

        del x_identity, x_transfer, x_test_identity, x_test_transfer, matrix
        torch.cuda.empty_cache()
        gc.collect()

    metrics_doc = {
        "report_id": "FASS01_S01_3_LINEAR_ACCESSIBILITY_METRICS_V01",
        "disposition": "COMPLETE_EXPLORATORY_LINEAR_CARTOGRAPHY",
        "preflight_root_sha256": preflight_seal["root_sha256"],
        "feature_cache_root_sha256": cache_status["feature_cache_root_sha256"],
        "metrics": metric_rows,
        "model_count": len(output_models),
        "all_views_reported": [item["view"] for item in output_models[:: len(TASKS)]],
        "all_tasks_reported": list(TASKS),
        "selection_or_promotion": False,
    }
    write_json(RESULT_ROOT / "metrics-v01.json", metrics_doc)
    receipt = {
        "receipt_id": "FASS01_S01_3_EXECUTION_RECEIPT_V01",
        "complete": True,
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "s01-3-linear-accessibility-v01",
        "preflight_root_sha256": preflight_seal["root_sha256"],
        "feature_cache_root_sha256": cache_status["feature_cache_root_sha256"],
        "corpus_sha256": read_json(BINDING_PATH)["parent_roots"]["s01_2_corpus_sha256"],
        "model_count": len(output_models),
        "models": output_models,
        "metrics_sha256": sha256_file(RESULT_ROOT / "metrics-v01.json")[0],
        "metadata_sha256": sha256_file(RESULT_ROOT / "metadata" / "event-metadata-v01.npz")[0],
        "test_event_manifest_sha256": sha256_file(RESULT_ROOT / "metadata" / "test-events-v01.jsonl")[0],
        "runtime": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "torch": torch.__version__,
            "cuda_device": torch.cuda.get_device_name(0),
        },
        "operations": {
            "LFM_loaded": False,
            "tokenizer_loaded": False,
            "feature_extraction": False,
            "probe_training": True,
            "online_or_adaptive_mechanisms": False,
            "FAS00_modified": False,
            "view_selection": False,
            "hyperparameter_search": False,
        },
        "S01_3_AUTHORIZED": True,
        "S01_ADAPTIVE_MECHANISMS_AUTHORIZED": False,
        "FAS00_PHASE4_AUTHORIZED": False,
    }
    write_json(RESULT_ROOT / "run-execution-receipt-v01.json", receipt)
    return {"status": "RUN_COMPLETE_UNSEALED", "models": len(output_models), "metrics_sha256": receipt["metrics_sha256"]}


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
