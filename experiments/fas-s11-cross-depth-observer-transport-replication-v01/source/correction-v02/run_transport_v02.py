from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np

sys.path.insert(0, r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01\source")
sys.path.insert(0, r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01\inputs\parent-sources")

from s11_exec_common_v01 import EVENTS, FEATURES, MANIFEST, OBSERVERS, RESULTS, RUN, canonical_json, entry, jsonl_rows, read_json, sha256_file, tree_root, verify_ancestry, verify_code_binding, write_json
from linear_core import classification_metrics, configure_determinism, predict_probabilities, standardized_raw_tensor
from s09_math import effective_geometry, subspace_comparison


LAYERS = tuple(range(1, 17))
SURFACES = ("M", "F")
CLASSES = np.asarray([0, 1, 2], dtype=np.int64)
EXPECTED_ROWS = 21_272
DIMENSION = 2_048
EXPECTED_ANALYSIS_SEAL = "44518d3901bf578a417d8897dda3485e9741262e80a676857d48297736cdcefc"


def predictions_sha(predicted: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(predicted, dtype="<i8").tobytes(order="C")).hexdigest()


def load_events() -> tuple[list[str], np.ndarray]:
    manifest = read_json(MANIFEST)
    expected_hash = manifest["authoritative_s11_ancestry"]["panel_events_sha256"]
    digest, _ = sha256_file(EVENTS)
    if digest != expected_hash:
        raise RuntimeError("S11 sealed event file hash changed")
    ids: list[str] = []
    targets: list[int] = []
    for _, row in jsonl_rows(EVENTS):
        ids.append(row["event_id"])
        targets.append(int(row["exact_target"]))
    if len(ids) != EXPECTED_ROWS or len(set(ids)) != EXPECTED_ROWS:
        raise RuntimeError("S11 event IDs/count are invalid")
    return ids, np.asarray(targets, dtype=np.int64)


def verify_feature_cache() -> dict[str, object]:
    seal = read_json(FEATURES / "feature-cache-seal-v01.json")
    actual = [entry(FEATURES.joinpath(*row["path"].split("/")), FEATURES) for row in seal["entries"]]
    actual.sort(key=lambda row: row["path"])
    if actual != sorted(seal["entries"], key=lambda row: row["path"]) or tree_root(actual) != seal["root_sha256"]:
        raise RuntimeError("S11 feature cache seal failed verification")
    receipt = read_json(FEATURES / "feature-extraction-receipt-v01.json")
    if receipt["complete"] is not True or receipt["matrix_count"] != 32 or receipt["rows"] != EXPECTED_ROWS:
        raise RuntimeError("S11 feature cache receipt incomplete")
    return {"root_sha256": seal["root_sha256"], "entries_verified": len(actual), "receipt": receipt}


def verify_observer_bank() -> tuple[dict[tuple[int, str], dict[str, np.ndarray]], dict[str, object]]:
    seal_path = OBSERVERS / "analysis-seal-v09.json"
    seal_hash, _ = sha256_file(seal_path)
    if seal_hash != EXPECTED_ANALYSIS_SEAL:
        raise RuntimeError("sealed S09 analysis seal identity mismatch")
    seal = read_json(seal_path)
    entries = {item["path"]: item for item in seal["entries"]}
    states: dict[tuple[int, str], dict[str, np.ndarray]] = {}
    loaded = []
    for layer in LAYERS:
        for surface in SURFACES:
            relative = f"probes/layer-{layer:02d}/{surface}/probe-state-v09.npz"
            path = OBSERVERS / relative.replace("/", os.sep)
            expected = entries.get(relative)
            if expected is None:
                raise RuntimeError(f"S09 seal has no observer entry: {relative}")
            digest, size = sha256_file(path)
            if digest != expected["sha256"] or size != expected["bytes"]:
                raise RuntimeError(f"S09 observer state differs from sealed analysis: {relative}")
            with np.load(path, allow_pickle=False) as data:
                state = {key: np.asarray(data[key]).copy() for key in data.files}
            if not np.array_equal(state["classes"], CLASSES):
                raise RuntimeError(f"observer class order mismatch: {relative}")
            if state["weights"].shape != (3, DIMENSION) or state["bias"].shape != (3,):
                raise RuntimeError(f"observer weight dimensions mismatch: {relative}")
            if state["scaler_mean"].shape != (DIMENSION,) or state["scaler_scale"].shape != (DIMENSION,):
                raise RuntimeError(f"observer scaler dimensions mismatch: {relative}")
            states[(layer, surface)] = state
            loaded.append({"path": relative, "bytes": size, "sha256": digest})
    return states, {"analysis_seal_sha256": seal_hash, "observer_count": len(loaded), "observers": loaded}


def distance_summary(matrix: np.ndarray, distance: int, forward: bool) -> dict[str, object]:
    values = []
    cells = []
    for source in LAYERS:
        target = source + distance if forward else source - distance
        if target < 1 or target > 16:
            continue
        values.append(float(matrix[source - 1, target - 1]))
        cells.append({"source": source, "target": target, "balanced_accuracy": float(matrix[source - 1, target - 1])})
    return {"mean": float(np.mean(values)), "cell_count": len(values), "cells": cells}


def main() -> int:
    started = time.perf_counter()
    manifest = read_json(MANIFEST)
    verify_ancestry(manifest)
    code_binding = verify_code_binding(manifest)
    if RESULTS.exists() or RESULTS.with_name(RESULTS.name + ".tmp").exists():
        raise RuntimeError("transport output already exists; preserve it and use a versioned attempt")
    feature_verification = verify_feature_cache()
    event_ids, labels = load_events()
    if len(labels) != EXPECTED_ROWS or not np.array_equal(np.unique(labels), CLASSES):
        raise RuntimeError("S11 evaluation target support is incomplete")
    device = configure_determinism()

    # Observer states are first opened only after the complete fresh feature-cache seal passes.
    observers, observer_receipt = verify_observer_bank()
    temp = RESULTS.with_name(RESULTS.name + ".tmp")
    pred_dir = temp / "predictions"
    pred_dir.mkdir(parents=True)
    matrices_out: dict[str, object] = {}
    geometries = {
        (layer, surface): effective_geometry(
            observers[(layer, surface)]["weights"], observers[(layer, surface)]["bias"],
            observers[(layer, surface)]["scaler_mean"], observers[(layer, surface)]["scaler_scale"],
        )
        for layer in LAYERS for surface in SURFACES
    }

    for surface in SURFACES:
        ba = np.zeros((16, 16), dtype=np.float64)
        accuracy = np.zeros((16, 16), dtype=np.float64)
        cell_rows = []
        diagonal_rows = []
        for target_layer in LAYERS:
            matrix_path = FEATURES / "matrices" / f"layer-{target_layer:02d}-{surface}.f32le"
            raw_matrix = np.memmap(matrix_path, dtype="<f4", mode="r", shape=(EXPECTED_ROWS, DIMENSION), order="C")
            if not raw_matrix.flags.c_contiguous:
                raise RuntimeError(f"feature view is not contiguous: {matrix_path}")
            raw = np.asarray(raw_matrix)
            if raw.dtype != np.dtype(np.float32):
                raise RuntimeError("S10 numerical path requires native FP32 raw feature arrays")
            for source_layer in LAYERS:
                state = observers[(source_layer, surface)]
                x = standardized_raw_tensor(raw, state["scaler_mean"], state["scaler_scale"], device)
                probabilities = predict_probabilities(x, state["weights"], state["bias"], batch_rows=16_384)
                metrics = classification_metrics(labels, probabilities, state["classes"])
                prediction = np.asarray(state["classes"][probabilities.argmax(axis=1)], dtype="<i8")
                if prediction.shape != (EXPECTED_ROWS,):
                    raise RuntimeError("prediction row count mismatch")
                cell_id = f"{surface}-src-{source_layer:02d}-tgt-{target_layer:02d}"
                pred_path = pred_dir / f"{cell_id}.npy"
                np.save(pred_path, prediction, allow_pickle=False)
                pred_digest = predictions_sha(prediction)
                ba[source_layer - 1, target_layer - 1] = metrics["balanced_accuracy"]
                accuracy[source_layer - 1, target_layer - 1] = metrics["accuracy"]
                cell = {
                    "cell_id": cell_id,
                    "surface": surface,
                    "source_observer_layer": source_layer,
                    "target_representation_layer": target_layer,
                    "diagonal_native": source_layer == target_layer,
                    "metrics": metrics,
                    "prediction_ids_sha256": pred_digest,
                    "prediction_file": pred_path.relative_to(temp).as_posix(),
                    "prediction_file_sha256": sha256_file(pred_path)[0],
                }
                cell_rows.append(cell)
                if source_layer == target_layer:
                    diagonal_rows.append({"layer": source_layer, "balanced_accuracy": metrics["balanced_accuracy"], "accuracy": metrics["accuracy"], "per_class_recall": metrics["per_class_recall"], "confusion_matrix": metrics["confusion_matrix"]})
                if len(cell_rows) % 32 == 0:
                    print(f"S11 replayed {surface} {len(cell_rows)}/256 cells", flush=True)
                del x, probabilities, prediction
            del raw_matrix, raw

        native = np.diag(ba)
        retention = np.full_like(ba, np.nan)
        for target_index, native_score in enumerate(native):
            if native_score != 0.0:
                retention[:, target_index] = ba[:, target_index] / native_score
        by_distance = {}
        for distance in range(1, 16):
            by_distance[str(distance)] = {
                "forward_to_deeper_representation": distance_summary(ba, distance, True),
                "backward_to_shallower_representation": distance_summary(ba, distance, False),
                "equally_weighted_distance_mean": float(np.mean([
                    ba[i - 1, j - 1] for i in LAYERS for j in LAYERS if abs(i - j) == distance
                ])),
            }
        adjacent_geometry = [
            {"lower_layer": layer, "upper_layer": layer + 1, **subspace_comparison(geometries[(layer, surface)], geometries[(layer + 1, surface)])}
            for layer in range(1, 16)
        ]
        matrices_out[surface] = {
            "meaning": "mean_full" if surface == "M" else "final_position",
            "balanced_accuracy_matrix_rows_source_cols_target": ba.tolist(),
            "accuracy_matrix_rows_source_cols_target": accuracy.tolist(),
            "retention_ratio_matrix_rows_source_cols_target": [[None if not np.isfinite(v) else float(v) for v in row] for row in retention],
            "native_diagonal": diagonal_rows,
            "transport_by_distance": by_distance,
            "adjacent_transport": {
                "observer_i_to_representation_i_plus_1": [float(ba[i - 1, i]) for i in range(1, 16)],
                "observer_i_plus_1_to_representation_i": [float(ba[i, i - 1]) for i in range(1, 16)],
            },
            "adjacent_fixed_observer_geometry": adjacent_geometry,
            "cells": cell_rows,
        }

    total_cells = sum(len(matrices_out[s]["cells"]) for s in SURFACES)
    if total_cells != 512:
        raise RuntimeError(f"expected 512 transport cells; found {total_cells}")
    results = {
        "result_id": "FAS_S11_CROSS_DEPTH_TRANSPORT_V01",
        "status": "TRANSPORT_COMPLETE_BOOTSTRAP_PENDING",
        "claim_scope": "fresh generated quartets admitted under the sealed v02 uniqueness-conditioned collision rule; same fixed families/templates; exploratory interpretation only until frozen bootstrap completion",
        "ancestry": {
            "protocol_root_sha256": manifest["authoritative_s11_ancestry"]["protocol_root_sha256"],
            "collision_admission_amendment_json_sha256": manifest["authoritative_s11_ancestry"]["collision_admission_amendment_json_sha256"],
            "panel_tree_root_sha256": manifest["authoritative_s11_ancestry"]["panel_tree_root_sha256"],
            "feature_cache_root_sha256": feature_verification["root_sha256"],
        },
        "implementation_code_manifest_sha256": code_binding["manifest_sha256"],
        "fresh_population_rows": EXPECTED_ROWS,
        "layers": list(LAYERS),
        "surfaces": list(SURFACES),
        "class_order": [0, 1, 2],
        "cell_count": total_cells,
        "feature_cache_verification": {"root_sha256": feature_verification["root_sha256"], "entries_verified": feature_verification["entries_verified"]},
        "observer_bank_verification": observer_receipt,
        "surface_results": matrices_out,
        "execution_seconds": round(time.perf_counter() - started, 3),
        "model_contact_in_this_stage": False,
        "observer_fitting": False,
    }
    write_json(temp / "transport-results-v01.json", results)
    receipt = {
        "receipt_id": "FAS_S11_TRANSPORT_RECEIPT_V01",
        "complete": True,
        "cells": total_cells,
        "predictions_saved": total_cells,
        "new_features": False,
        "new_probe_fits": False,
        "model_contact": False,
        "feature_cache_root_sha256": feature_verification["root_sha256"],
        "implementation_code_manifest_sha256": code_binding["manifest_sha256"],
        "observer_count": 32,
        "elapsed_seconds": results["execution_seconds"],
    }
    write_json(temp / "transport-receipt-v01.json", receipt)
    entries = [entry(path, temp) for path in temp.rglob("*") if path.is_file() and path.name != "transport-seal-v01.json"]
    entries.sort(key=lambda item: item["path"])
    root = tree_root(entries)
    write_json(temp / "transport-seal-v01.json", {"seal_id": "FAS_S11_TRANSPORT_SEAL_V01", "entries": entries, "root_sha256": root})
    temp.replace(RESULTS)
    run_manifest = read_json(MANIFEST)
    run_manifest["observers_loaded"] = True
    run_manifest["transport_cells_complete"] = True
    run_manifest["transport_root_sha256"] = root
    run_manifest["status"] = "TRANSPORT_SEALED_BOOTSTRAP_PENDING"
    write_json(MANIFEST, run_manifest)
    print(f"S11 transport sealed: 512 cells, root={root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
