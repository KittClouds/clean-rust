"""Execute the sealed 72-fit D/S qualification matrix without scoring outcomes."""
from __future__ import annotations

import csv
import gc
import json
import math
import os
import platform
import sys
import time
from pathlib import Path


THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

from fit_common import (
    BLOCKS, RUN, DEncoder, SEncoder, d_input, load_raw_inputs, load_training_targets,
    normalized_folds, read_initial_bundle, read_json, sha_file, verify_truth_header,
    validate_source_manifest, write_json_new,
)
from fit_contract import (
    ARMS, expected_update_count, sha256_bytes, validate_fit_grid, encode_prediction_stream,
)
from f4_invariant_01_model import tensor_hash


def _load_manifest() -> tuple[list[dict[str, str]], dict[str, object], dict[str, str]]:
    manifest_path = RUN / "FIT-MANIFEST.csv"
    with manifest_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    validate_fit_grid(rows)
    preflight = read_json(RUN / "FIT-EXECUTION-PREFLIGHT-RECEIPT.json")
    row_hashes = read_json(RUN / "FIT-MANIFEST-ROW-HASHES.json")
    manifest_sha = sha_file(manifest_path)
    if preflight.get("status") != "PASS" or preflight.get("fit_manifest_sha256") != manifest_sha:
        raise RuntimeError("fit manifest preflight mismatch")
    if row_hashes.get("manifest_sha256") != manifest_sha or len(row_hashes.get("rows", {})) != 72:
        raise RuntimeError("fit manifest row-hash receipt mismatch")
    return rows, preflight, row_hashes["rows"]


def _verify_run_inputs(preflight: dict[str, object]) -> dict[str, object]:
    source = validate_source_manifest(
        RUN / "FIT-EXECUTION-SOURCE-MANIFEST.json",
        str(preflight["source_manifest_canonical_sha256"]),
        str(preflight["source_manifest_file_sha256"]),
    )
    collection = read_json(RUN / "COLLECTION-RECEIPT.json")
    bank = RUN.parent / "F4-INVARIANT-01-RUN2" / "task-bank"
    task_manifest = read_json(bank / "TASK-BANK-MANIFEST.json")
    if collection.get("status") != "PASS" or collection.get("row_count") != preflight.get("row_count"):
        raise RuntimeError("collection receipt mismatch")
    frozen_runtime = preflight.get("runtime", {})
    if (
        sys.version != frozen_runtime.get("python_version")
        or np.__version__ != frozen_runtime.get("numpy_version")
        or str(Path(sys.executable).resolve()) != frozen_runtime.get("python_executable")
        or sha_file(Path(sys.executable)) != frozen_runtime.get("python_executable_sha256")
        or any(os.environ.get(key) != "1" for key in THREAD_ENV)
    ):
        raise RuntimeError("fit runtime differs from the frozen tooling runtime")
    if sha_file(RUN / "native-collection" / "RAW-PREDICTORS.bin") != collection.get("predictor_file_sha256"):
        raise RuntimeError("predictor stream changed after collection")
    if sha_file(RUN / "native-collection" / "RAW-SCORING-TRUTH.bin") != collection.get("truth_file_sha256"):
        raise RuntimeError("scoring-truth stream changed after collection")
    if sha_file(bank / "training.json") != task_manifest.get("task_bank_sha256") or task_manifest.get("block_ids") != list(BLOCKS):
        raise RuntimeError("frozen task bank mismatch")
    return source


def _read_fit_cell(row: dict[str, str], data, normalized, row_hash: str, initializer: dict[str, object]) -> dict[str, object]:
    arm = row["arm"]
    holdout = int(row["heldout_block"])
    fold_index = int(row["fold_index"])
    replicate = int(row["replicate_index"])
    fit_id = row["fit_id"]
    train_mask = data.blocks != np.uint64(holdout)
    heldout_mask = ~train_mask
    norm = normalized[fold_index]
    if norm.sha256 != row["normalization_sha256"]:
        raise RuntimeError(f"normalization hash mismatch before {fit_id}")
    train_rows = int(train_mask.sum())
    heldout_rows = int(heldout_mask.sum())
    if train_rows != int(row["train_rows"]) or heldout_rows != int(row["heldout_rows"]):
        raise RuntimeError(f"row count mismatch before {fit_id}")

    labels_full = load_training_targets(data.keys, holdout)
    x_train_base = norm.base[train_mask]
    r_train = norm.tuples[train_mask]
    y_train = labels_full[train_mask]
    if not len(y_train) or set(np.unique(y_train).tolist()) != {0.0, 1.0}:
        raise RuntimeError(f"training support changed before {fit_id}")

    cell = next(
        item for item in initializer["cells"]
        if item["fold_index"] == fold_index and item["replicate_index"] == replicate and item["arm"] == arm
    )
    bundle_path = RUN / "initial-tensors" / f"{fit_id}.bin"
    tensor_values = read_initial_bundle(bundle_path, arm)
    initial_hash = tensor_hash(tensor_values, arm)
    if initial_hash != row["initial_tensor_hash"] or initial_hash != cell["initial_tensor_sha256"]:
        raise RuntimeError(f"initial tensor mismatch before {fit_id}")

    if arm == "D":
        train_x = d_input(x_train_base, r_train)
        model = DEncoder(fold_index, replicate, values=tensor_values)
        if model.fit is None:
            raise RuntimeError("D fit method missing")
        started = time.perf_counter()
        model.fit(train_x, y_train)
        held_x = d_input(norm.base[heldout_mask], norm.tuples[heldout_mask])
        logits = model.logits(held_x)
    else:
        model = SEncoder(fold_index, replicate, values=tensor_values)
        started = time.perf_counter()
        model.fit(x_train_base, r_train, y_train)
        logits = model.logits(norm.base[heldout_mask], norm.tuples[heldout_mask])
    runtime_seconds = time.perf_counter() - started
    repeated = model.logits(held_x) if arm == "D" else model.logits(norm.base[heldout_mask], norm.tuples[heldout_mask])
    if logits.dtype != np.dtype(np.float32) or logits.tobytes() != repeated.tobytes() or not np.isfinite(logits).all():
        raise RuntimeError(f"prediction determinism/finiteness failed for {fit_id}")
    if any(not np.isfinite(value).all() for value in model.values + model.m + model.v):
        raise RuntimeError(f"nonfinite training tensor/state for {fit_id}")
    update_count = int(model.step)
    expected_updates = expected_update_count(train_rows)
    if update_count != expected_updates:
        raise RuntimeError(f"update count mismatch for {fit_id}: {update_count} != {expected_updates}")

    keys = [key for key, keep in zip(data.keys, heldout_mask, strict=True) if keep]
    records = [(key, float(logit)) for key, logit in zip(keys, logits, strict=True)]
    pred_bytes = encode_prediction_stream(
        block=holdout, arm=arm, replicate=replicate,
        manifest_row_sha256=row_hash, records=records,
    )
    pred_rel = row["expected_prediction_path"]
    pred_path = RUN / Path(pred_rel)
    with pred_path.open("xb") as stream:
        stream.write(pred_bytes)
        stream.flush()
        os.fsync(stream.fileno())

    receipt = {
        "schema": "F4-INVARIANT-01-fit-receipt-v1",
        "fit_id": fit_id,
        "arm": arm,
        "fold_index": fold_index,
        "heldout_block": holdout,
        "replicate_index": replicate,
        "architecture_id": cell["architecture_id"],
        "parameter_count": cell["parameter_count"],
        "train_rows": train_rows,
        "heldout_rows": heldout_rows,
        "batch_size": 2048,
        "epoch_count": 200,
        "update_count": update_count,
        "contract_sha256": row["contract_sha256"],
        "source_manifest_sha256": row["source_manifest_sha256"],
        "executable_sha256": row["executable_sha256"],
        "analysis_sha256": row["analysis_sha256"],
        "base_stream_sha256": row["base_stream_sha256"],
        "normalized_tuple_stream_sha256": row["normalized_tuple_stream_sha256"],
        "paired_source_input_sha256": row["paired_source_input_sha256"],
        "normalization_sha256": row["normalization_sha256"],
        "training_row_hash": row["training_row_hash"],
        "training_order_hash": row["training_order_hash"],
        "initializer_seed_manifest_sha256": row["initializer_seed_manifest_sha256"],
        "initial_tensor_hash": initial_hash,
        "final_tensor_hash": tensor_hash(model.values, arm),
        "initial_layer_seeds": cell["layers"],
        "finite_status": "PASS",
        "repeat_prediction_identical": True,
        "prediction_path": pred_rel,
        "prediction_sha256": sha256_bytes(pred_bytes),
        "fit_manifest_row_sha256": row_hash,
        "runtime_seconds": runtime_seconds,
        "runtime": {
            "python": sys.version,
            "python_executable": str(Path(sys.executable).resolve()),
            "numpy": np.__version__,
            "platform": platform.platform(),
            "thread_environment": {name: os.environ.get(name) for name in THREAD_ENV},
        },
        "comparative_metrics_emitted": False,
        "heldout_target_or_reference_read": False,
    }
    receipt_path = RUN / "fit-receipts" / f"{fit_id}.json"
    raw_receipt = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with receipt_path.open("xb") as stream:
        stream.write(raw_receipt)
        stream.flush()
        os.fsync(stream.fileno())

    result = {
        "fit_id": fit_id,
        "fit_receipt_sha256": sha_file(receipt_path),
        "prediction_sha256": sha256_bytes(pred_bytes),
        "prediction_path": pred_rel,
    }
    del model, tensor_values, labels_full, x_train_base, r_train, y_train, logits, repeated
    if arm == "D":
        del train_x, held_x
    gc.collect()
    return result


def run() -> None:
    rows, preflight, row_hashes = _load_manifest()
    if any((RUN / "fit-receipts").glob("*.json")) or any((RUN / "heldout-predictions").glob("*.bin")) or (RUN / "PREDICTION-LOCK.json").exists():
        raise RuntimeError("fit output already exists; preserve this identity and stop")
    _verify_run_inputs(preflight)
    data = load_raw_inputs()
    verify_truth_header(expected_count=len(data.keys))
    normalized = normalized_folds(data)
    reconciled = read_json(RUN / "SHARED-INPUT-RECONCILIATION.json")
    if len(reconciled["folds"]) != 12:
        raise RuntimeError("shared-input reconciliation fold count mismatch")
    for fold_index, norm in normalized.items():
        expected = reconciled["folds"][fold_index]
        hashes = __import__("f4_invariant_01_inputs").shared_stream_hashes(data.keys, norm.base, norm.tuples)
        if norm.sha256 != expected["normalization_sha256"] or hashes["base"] != expected["base_stream_sha256"] or hashes["tuples"] != expected["normalized_tuple_stream_sha256"] or hashes["paired"] != expected["paired_source_input_sha256"]:
            raise RuntimeError(f"shared normalized input drift in fold {fold_index}")
    initializer_path = IMPL / "implementation-artifacts" / "INITIALIZER-SEED-MANIFEST.json"
    initializer = read_json(initializer_path)
    results = []
    for row in rows:
        fit_id = row["fit_id"]
        result = _read_fit_cell(row, data, normalized, row_hashes[fit_id], initializer)
        results.append(result)
        print(json.dumps({"event": "fit_completed", "fit_id": fit_id, "finite_status": "PASS", "prediction_sha256": result["prediction_sha256"]}, sort_keys=True), flush=True)

    lock = {
        "schema": "F4-INVARIANT-01-prediction-lock-v1",
        "status": "PASS",
        "run_id": "F4-INVARIANT-01-COLLECT2",
        "fit_count": len(results),
        "fit_manifest_sha256": sha_file(RUN / "FIT-MANIFEST.csv"),
        "source_manifest_sha256": preflight["source_manifest_canonical_sha256"],
        "prediction_streams": results,
        "comparative_metrics_emitted_during_fitting": False,
        "heldout_truth_opened": False,
    }
    write_json_new(RUN / "PREDICTION-LOCK.json", lock)
    print(json.dumps({"status": "FIT_COLLECTION_COMPLETE", "fit_count": len(results), "scoring_performed": False}, sort_keys=True))


if __name__ == "__main__":
    run()
