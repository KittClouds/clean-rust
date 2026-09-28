from __future__ import annotations

import hashlib
import json
import os
import shutil
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

SOURCE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE_ROOT))
from linear_core import classification_metrics, configure_determinism, predict_probabilities, standardized_tensor  # noqa: E402
from s09_math import effective_geometry, subspace_comparison  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT_ROOT / "contracts" / "s10-transport-contract-v01.json"
S09_PROJECT = Path(r"C:\code land\clean-rust\experiments\fas-s09-depthwise-decision-subspace-emergence-v09")
S09_RUN = Path(r"\\?\D:\codex-runs\fas-s09-depthwise-decision-subspace-emergence-v09")
S09_CACHE = Path(r"\\?\D:\codex-runs\fas-s09-depthwise-decision-subspace-emergence-v02\feature-cache-v02")
S10_RUN = Path(r"\\?\D:\codex-runs\fas-s10-cross-depth-observer-transport")
EVENTS = 106_496
DIMENSION = 2_048
LAYERS = tuple(range(1, 17))
SURFACES = ("M", "F")
CLASSES = np.asarray([0, 1, 2], dtype=np.int64)
BATCH_ROWS = 16_384
EXPECTED_RESULT_ROOT = "664af5b22f071b28d52a67d748e9f6f93ae3e67d587edec80b921dd529945880"
EXPECTED_CACHE_ROOT = "82f9eb6ba0b9c37e58c415b03ec1bc4be00032f73cc43e70b3987ac4108f7653"
EXPECTED_PROTOCOL_ROOT = "c1cf07e8b04ac1a3deff583e10257dcd3c5f3040e48bd4b05738cb3c4d4794b2"
EXPECTED_ANALYSIS_SEAL_SHA256 = "44518d3901bf578a417d8897dda3485e9741262e80a676857d48297736cdcefc"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def sha256_file(path: Path, chunk_bytes: int = 8 * 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def tree_root(entries: list[dict[str, Any]]) -> str:
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(entries, key=lambda x: x["path"]))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def entry_for(path: Path, base: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    return {"path": path.relative_to(base).as_posix(), "bytes": size, "sha256": digest}


def verify_tree(base: Path, seal_path: Path, expected_root: str) -> dict[str, Any]:
    seal = read_json(seal_path)
    if seal.get("root_sha256") != expected_root:
        raise RuntimeError(f"parent seal declares unexpected root: {seal_path}")
    actual = [entry_for(base.joinpath(*row["path"].split("/")), base) for row in seal["entries"]]
    actual.sort(key=lambda x: x["path"])
    expected = sorted(seal["entries"], key=lambda x: x["path"])
    root = tree_root(actual)
    if actual != expected or root != expected_root:
        raise RuntimeError(f"sealed parent tree failed verification: {seal_path}; computed={root}")
    return {"root_sha256": root, "entry_count": len(actual), "bytes": sum(x["bytes"] for x in actual)}


def verify_feature_cache() -> dict[str, Any]:
    seal = read_json(S09_RUN / "recovery-feature-cache-seal-v03.json")
    if seal.get("root_sha256") != EXPECTED_CACHE_ROOT:
        raise RuntimeError("S09 feature-cache seal root differs from the S10 contract")
    entries = [entry_for(S09_CACHE.joinpath(*row["path"].split("/")), S09_CACHE) for row in seal["entries"]]
    entries.sort(key=lambda x: x["path"])
    if entries != seal["entries"] or tree_root(entries) != EXPECTED_CACHE_ROOT:
        raise RuntimeError("S09 feature cache failed full byte-level verification")
    if len(entries) != 32 or any(row["bytes"] != EVENTS * DIMENSION * 4 for row in entries):
        raise RuntimeError("S09 feature cache matrix count or byte length differs from contract")
    return {"root_sha256": EXPECTED_CACHE_ROOT, "matrices_verified": len(entries), "bytes": sum(x["bytes"] for x in entries)}


def load_probe(layer: int, surface: str) -> dict[str, np.ndarray]:
    path = S09_RUN / "analysis-v09" / "probes" / f"layer-{layer:02d}" / surface / "probe-state-v09.npz"
    with np.load(path, allow_pickle=False) as data:
        state = {key: data[key].copy() for key in data.files}
    if not np.array_equal(state["classes"], CLASSES):
        raise RuntimeError(f"sealed class order changed for layer {layer}/{surface}")
    if state["weights"].shape != (3, DIMENSION) or state["bias"].shape != (3,):
        raise RuntimeError(f"sealed probe shape changed for layer {layer}/{surface}")
    if state["scaler_mean"].shape != (DIMENSION,) or state["scaler_scale"].shape != (DIMENSION,):
        raise RuntimeError(f"sealed scaler shape changed for layer {layer}/{surface}")
    return state


def file_digest_for_prediction(prediction: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(prediction, dtype="<i8").tobytes(order="C")).hexdigest()


def expected_native_metrics(metrics: dict[str, Any], layer: int, surface: str) -> dict[str, Any]:
    cell = "M_NATIVE" if surface == "M" else "F_NATIVE"
    return metrics["layers"][layer - 1]["cells"][cell]["metrics"]["ALL_TEST_ROWS"]


def summarize_direction(matrix: np.ndarray, distance: int, forward: bool) -> dict[str, Any]:
    values = []
    pairs = []
    for source in LAYERS:
        target = source + distance if forward else source - distance
        if target not in LAYERS:
            continue
        value = float(matrix[source - 1, target - 1])
        values.append(value)
        pairs.append({"source_layer": source, "target_layer": target, "balanced_accuracy": value})
    return {
        "pairs": pairs,
        "count": len(values),
        "mean_balanced_accuracy": float(np.mean(values)),
        "median_balanced_accuracy": float(np.median(values)),
        "minimum_balanced_accuracy": float(np.min(values)),
        "maximum_balanced_accuracy": float(np.max(values)),
    }


def main() -> int:
    if S10_RUN.exists():
        raise RuntimeError(f"S10 run output already exists; refusing overwrite: {S10_RUN}")
    local_protocol_seal = read_json(PROJECT_ROOT / "seals" / "protocol-seal-v01.json")
    local_protocol = verify_tree(
        PROJECT_ROOT,
        PROJECT_ROOT / "seals" / "protocol-seal-v01.json",
        local_protocol_seal["root_sha256"],
    )
    contract = read_json(CONTRACT_PATH)
    if contract["identity"] != "FAS-S10-CROSS-DEPTH-OBSERVER-TRANSPORT-V01":
        raise RuntimeError("S10 contract identity mismatch")
    if contract["parents"]["s09_result_tree_root_sha256"] != EXPECTED_RESULT_ROOT:
        raise RuntimeError("S09 result-root binding mismatch")
    if contract["parents"]["s09_feature_cache_root_sha256"] != EXPECTED_CACHE_ROOT:
        raise RuntimeError("S09 feature-root binding mismatch")
    if contract["parents"]["s09_protocol_root_sha256"] != EXPECTED_PROTOCOL_ROOT:
        raise RuntimeError("S09 protocol-root binding mismatch")
    analysis_seal_path = S09_RUN / "analysis-v09" / "analysis-seal-v09.json"
    if sha256_file(analysis_seal_path)[0] != EXPECTED_ANALYSIS_SEAL_SHA256:
        raise RuntimeError("S09 analysis seal file identity mismatch")

    protocol_root = verify_tree(
        S09_PROJECT,
        S09_PROJECT / "seals" / "protocol-seal-v09.json",
        EXPECTED_PROTOCOL_ROOT,
    )
    result_root = verify_tree(
        S09_RUN,
        S09_RUN / "result-tree-seal-v09.json",
        EXPECTED_RESULT_ROOT,
    )
    analysis_root = verify_tree(
        S09_RUN / "analysis-v09",
        analysis_seal_path,
        read_json(analysis_seal_path)["root_sha256"],
    )
    feature_root = verify_feature_cache()
    if S09_RUN.joinpath("result-disposition-v09.json").exists():
        disposition = read_json(S09_RUN / "result-disposition-v09.json")
        if disposition.get("disposition") != "COMPLETE_EXPLORATORY_DEPTHWISE_ACCESSIBILITY_AND_SUBSPACE_CARTOGRAPHY":
            raise RuntimeError("S09 disposition is not complete and exploratory")

    metadata_path = S09_RUN / "inputs" / "S01-3" / "event-metadata-v01.npz"
    with np.load(metadata_path, allow_pickle=False) as data:
        metadata = {key: data[key].copy() for key in data.files}
    if len(metadata["target"]) != EVENTS or not np.array_equal(np.unique(metadata["target"]), CLASSES):
        raise RuntimeError("S09 label rows or class set differ from the bound population")
    test_rows = np.flatnonzero(metadata["split_bucket"] == 0).astype(np.int64, copy=False)
    labels = np.asarray(metadata["target"][test_rows], dtype=np.int64)
    if len(test_rows) != 21_272:
        raise RuntimeError(f"test support differs from S09: {len(test_rows)}")
    manifest_path = S09_RUN / "inputs" / "S01-3" / "test-events-v01.jsonl"
    manifest_ids = [json.loads(line)["event_id"].encode("ascii") for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    if not np.array_equal(metadata["event_id"][test_rows], np.asarray(manifest_ids, dtype=metadata["event_id"].dtype)):
        raise RuntimeError("S09 test-event order differs from its sealed manifest")

    receipt = {
        "receipt_id": "FAS_S10_PARENT_PREFLIGHT_V01",
        "s10_protocol_tree": local_protocol,
        "parent_protocol_tree": protocol_root,
        "parent_result_tree": result_root,
        "parent_analysis_tree": analysis_root,
        "parent_feature_cache": feature_root,
        "test_rows": len(test_rows),
        "ordered_test_event_manifest_sha256": sha256_file(manifest_path)[0],
        "all_model_contact": False,
        "all_probe_fitting": False,
    }
    S10_RUN.mkdir(parents=True, exist_ok=False)
    snapshot = S10_RUN / "inputs" / "project-snapshot"
    snapshot.mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "S10-PROTOCOL.md", snapshot / "S10-PROTOCOL.md")
    shutil.copy2(CONTRACT_PATH, snapshot / "s10-transport-contract-v01.json")
    shutil.copy2(PROJECT_ROOT / "seals" / "protocol-seal-v01.json", snapshot / "protocol-seal-v01.json")
    for utility in (SOURCE_ROOT / "linear_core.py", SOURCE_ROOT / "s09_math.py", Path(__file__).resolve()):
        shutil.copy2(utility, snapshot / utility.name)
    write_json(S10_RUN / "parent-verification-receipt-v01.json", receipt)

    device = configure_determinism()
    metric_reference = read_json(S09_RUN / "metrics-v09.json")
    results: dict[str, Any] = {
        "identity": "FAS-S10-CROSS-DEPTH-OBSERVER-TRANSPORT-V01",
        "disposition": "COMPLETE_EXPLORATORY_CROSS_DEPTH_OBSERVER_TRANSPORT",
        "parent_roots": {
            "s09_result_tree": EXPECTED_RESULT_ROOT,
            "s09_feature_cache": EXPECTED_CACHE_ROOT,
            "s09_protocol": EXPECTED_PROTOCOL_ROOT,
            "s09_analysis_tree": analysis_root["root_sha256"],
        },
        "rows": {"test": len(test_rows), "class_support": np.bincount(labels, minlength=3).tolist()},
        "device": {"torch": torch.__version__, "cuda": torch.cuda.get_device_name(0), "tf32": False, "deterministic": True},
        "surface_results": {},
        "adjacent_observer_geometry": {},
        "diagonal_reproduction": {"cells_checked": 0, "probability_arrays_exact": True, "metric_objects_exact": True},
        "interpretation_limits": [
            "The S01 grouped split was already revealed; the S10 transport maps are exploratory.",
            "A fixed linear observer's transport result measures accessibility, not information absence.",
            "Principal angles compare observer normals in shared indexed residual coordinates; they do not identify circuits or semantic features.",
            "Cross-layer cells transport the full source scaler-plus-probe without refitting.",
            "No significance test, categorical layer boundary, layer selection, or FAS-00 analysis was performed.",
        ],
    }
    started = time.perf_counter()

    for surface in SURFACES:
        states = {layer: load_probe(layer, surface) for layer in LAYERS}
        geometries = {}
        for layer, state in states.items():
            geometries[layer] = effective_geometry(
                np.asarray(state["weights"], dtype=np.float32),
                np.asarray(state["bias"], dtype=np.float32),
                np.asarray(state["scaler_mean"], dtype=np.float32).astype(np.float64),
                np.asarray(state["scaler_scale"], dtype=np.float32).astype(np.float64),
            )
            if geometries[layer]["rank"] != 2:
                raise RuntimeError(f"native observer rank differs from 2 at layer {layer}/{surface}")

        ba = np.empty((16, 16), dtype=np.float64)
        accuracy = np.empty((16, 16), dtype=np.float64)
        retention = np.empty((16, 16), dtype=np.float64)
        cell_results: list[dict[str, Any]] = []
        diagonal_checks = []
        for target_layer in LAYERS:
            matrix_path = S09_CACHE / f"layer-{target_layer:02d}-{surface}.f32le"
            matrix = np.memmap(matrix_path, dtype="<f4", mode="r", shape=(EVENTS, DIMENSION), order="C")
            for source_layer in LAYERS:
                state = states[source_layer]
                x = standardized_tensor(matrix, test_rows, state["scaler_mean"], state["scaler_scale"], device)
                probabilities = predict_probabilities(x, state["weights"], state["bias"], batch_rows=BATCH_ROWS)
                metric = classification_metrics(labels, probabilities, CLASSES)
                prediction = probabilities.argmax(axis=1).astype(np.int64, copy=False)
                ba[source_layer - 1, target_layer - 1] = metric["balanced_accuracy"]
                accuracy[source_layer - 1, target_layer - 1] = metric["accuracy"]
                diagonal = source_layer == target_layer
                if diagonal:
                    cell_name = "M_NATIVE" if surface == "M" else "F_NATIVE"
                    expected_probs = np.load(
                        S09_RUN / "analysis-v09" / "predictions" / f"layer-{target_layer:02d}" / cell_name / "probabilities.npy",
                        allow_pickle=False,
                    )
                    probabilities_exact = np.array_equal(probabilities, expected_probs)
                    expected_metric = expected_native_metrics(metric_reference, target_layer, surface)
                    metric_exact = metric == expected_metric
                    if not probabilities_exact or not metric_exact:
                        raise RuntimeError(f"S09 diagonal reproduction failed at layer {target_layer}/{surface}")
                    diagonal_checks.append({
                        "layer": target_layer,
                        "probabilities_exact": probabilities_exact,
                        "metrics_exact": metric_exact,
                        "balanced_accuracy": metric["balanced_accuracy"],
                    })
                    results["diagonal_reproduction"]["cells_checked"] += 1
                cell_results.append({
                    "source_observer_layer": source_layer,
                    "target_representation_layer": target_layer,
                    "diagonal_native": diagonal,
                    "metrics": metric,
                    "prediction_ids_sha256": file_digest_for_prediction(prediction),
                })
                del probabilities, prediction, x
            del matrix

        for target_layer in LAYERS:
            native = float(ba[target_layer - 1, target_layer - 1])
            if native == 0.0:
                retention[:, target_layer - 1] = np.nan
            else:
                retention[:, target_layer - 1] = ba[:, target_layer - 1] / native

        directions = {}
        for distance in range(1, 16):
            directions[str(distance)] = {
                "forward_to_deeper_representation": summarize_direction(ba, distance, True),
                "backward_to_shallower_representation": summarize_direction(ba, distance, False),
            }
        results["surface_results"][surface] = {
            "meaning": "M=mean_full" if surface == "M" else "F=final_position",
            "balanced_accuracy_matrix_rows_source_cols_target": ba.tolist(),
            "accuracy_matrix_rows_source_cols_target": accuracy.tolist(),
            "retention_ratio_matrix_rows_source_cols_target": [
                [None if not np.isfinite(v) else float(v) for v in row] for row in retention
            ],
            "diagonal_native_balanced_accuracy": np.diag(ba).tolist(),
            "adjacent_transport": {
                "observer_i_to_representation_i_plus_1": [float(ba[i, i + 1]) for i in range(15)],
                "observer_i_plus_1_to_representation_i": [float(ba[i + 1, i]) for i in range(15)],
            },
            "transport_by_layer_distance": directions,
            "diagonal_checks": diagonal_checks,
            "cells": cell_results,
        }
        adjacent = []
        for lower in range(1, 16):
            comparison = subspace_comparison(geometries[lower], geometries[lower + 1])
            adjacent.append({"lower_layer": lower, "upper_layer": lower + 1, **comparison})
        results["adjacent_observer_geometry"][surface] = adjacent

    if results["diagonal_reproduction"]["cells_checked"] != 32:
        raise RuntimeError("not all 32 native diagonal cells were reproduced")
    results["execution_seconds"] = round(time.perf_counter() - started, 3)
    results["diagonal_reproduction"]["probability_arrays_exact"] = True
    results["diagonal_reproduction"]["metric_objects_exact"] = True
    write_json(S10_RUN / "S10-TRANSPORT-RESULTS-V01.json", results)
    write_json(S10_RUN / "execution-receipt-v01.json", {
        "receipt_id": "FAS_S10_EXECUTION_RECEIPT_V01",
        "complete": True,
        "transport_cells": 512,
        "diagonal_cells_reproduced_exactly": 32,
        "new_features": False,
        "new_probe_fits": False,
        "model_contact": False,
        "fas00_access": False,
        "execution_seconds": results["execution_seconds"],
    })
    entries = [entry_for(path, S10_RUN) for path in S10_RUN.rglob("*") if path.is_file() and path.name != "result-seal-v01.json"]
    entries.sort(key=lambda x: x["path"])
    write_json(S10_RUN / "result-seal-v01.json", {
        "seal_id": "FAS_S10_RESULT_SEAL_V01",
        "entries": entries,
        "root_sha256": tree_root(entries),
    })
    print(f"S10 complete: 512 cells, 32 exact diagonals, root={tree_root(entries)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
