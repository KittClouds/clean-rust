"""Run the frozen 36-cell Cphi engineering screen without reading held-out truth."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
PREFIT = STUDY / "f4-invariant-01-prefit-v2"
IMPL = STUDY / "f4-invariant-01-impl-v2"
SCRIPTS = STUDY / "scripts"
for _path in (str(PREFIT), str(IMPL), str(SCRIPTS), str(BRANCH)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import numpy as np  # noqa: E402

from cphi_model import CPhiEncoder, deserialize_tensors, serialize_tensors, tensor_hash  # noqa: E402
from fit_common import (  # noqa: E402
    BLOCKS, RUN as PARENT_RUN, load_raw_inputs, load_training_targets, normalized_folds,
    read_json, sha_file, shared_stream_hashes, validate_source_manifest, write_json_new,
)
from fit_contract import sha256_bytes  # noqa: E402


RUN_ID = "F4-PRESENTATION-02-CPHI-ENG1"
RUN = STUDY / "runs" / RUN_ID
PRED_MAGIC = b"F4PRES02CPHIPRED"
PRED_RECORD_BYTES = 22
TRACE_HEADER = ("epoch", "training_bce", "training_balanced_error") + tuple(
    f"{layer}_gradient_norm_{stat}"
    for layer in ("phi", "rho1", "rho2", "rho3")
    for stat in ("mean", "max")
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _verify_frozen_inputs() -> tuple[dict[str, Any], list[dict[str, Any]], Any, dict[int, Any], Any]:
    freeze_path = RUN / "ENGINEERING-PREFIT-FREEZE.json"
    freeze = read_json(freeze_path)
    if freeze.get("status") != "PASS" or freeze.get("identity") != RUN_ID or freeze.get("fit_count") != 36:
        raise RuntimeError("Cphi prefit freeze missing or invalid")
    source_manifest = read_json(RUN / "SOURCE-MANIFEST.json")
    if sha_file(RUN / "SOURCE-MANIFEST.json") != freeze.get("source_manifest_sha256"):
        raise RuntimeError("Cphi source manifest hash mismatch")
    for item in source_manifest.get("files", []):
        path = REPO / Path(item["path"])
        if not path.is_file() or path.stat().st_size != item["byte_length"] or sha_file(path) != item["sha256"]:
            raise RuntimeError(f"Cphi implementation source drift: {item['path']}")
    parent_manifest_path = RUN / "PARENT-INPUT-MANIFEST.json"
    if sha_file(parent_manifest_path) != freeze.get("parent_input_manifest_sha256"):
        raise RuntimeError("parent input manifest hash mismatch")
    parent_manifest = read_json(parent_manifest_path)
    for item in parent_manifest.get("files", []):
        path = REPO / Path(item["path"])
        if not path.is_file() or path.stat().st_size != item["byte_length"] or sha_file(path) != item["sha256"]:
            raise RuntimeError(f"locked parent input drift: {item['path']}")
    initializer = read_json(RUN / "CPHI-INITIALIZER-MANIFEST.json")
    fit_manifest = read_json(RUN / "FIT-MANIFEST.json")
    if (
        sha_file(RUN / "CPHI-INITIALIZER-MANIFEST.json") != freeze.get("initializer_manifest_sha256")
        or sha_file(RUN / "FIT-MANIFEST.json") != freeze.get("fit_manifest_sha256")
        or len(initializer.get("cells", [])) != 36
        or len(fit_manifest.get("rows", [])) != 36
    ):
        raise RuntimeError("Cphi fit/initializer manifest mismatch")
    data = load_raw_inputs()
    normalized = normalized_folds(data)
    shared = read_json(PARENT_RUN / "SHARED-INPUT-RECONCILIATION.json")
    if len(shared.get("folds", [])) != 12:
        raise RuntimeError("parent shared-input receipt does not cover 12 folds")
    for fold, norm in normalized.items():
        hashes = shared_stream_hashes(data.keys, norm.base, norm.tuples)
        expected = shared["folds"][fold]
        if (
            norm.sha256 != expected["normalization_sha256"]
            or hashes["base"] != expected["base_stream_sha256"]
            or hashes["tuples"] != expected["normalized_tuple_stream_sha256"]
            or hashes["paired"] != expected["paired_source_input_sha256"]
        ):
            raise RuntimeError(f"parent shared-input reconciliation drift in fold {fold}")
    return fit_manifest, initializer["cells"], data, normalized, parent_manifest


def _prediction_bytes(block: int, replicate: int, records: list[tuple[bytes, float]]) -> bytes:
    if len(PRED_MAGIC) != 16:
        raise RuntimeError("Cphi prediction magic must be 16 bytes")
    result = bytearray(PRED_MAGIC)
    result.extend(struct.pack("<IQBQ", 1, block, replicate, len(records)))
    seen: set[bytes] = set()
    for key, logit in records:
        if len(key) != 18 or key in seen or not np.isfinite(logit):
            raise RuntimeError("invalid Cphi prediction record")
        seen.add(key)
        result.extend(key)
        result.extend(struct.pack("<f", float(logit)))
    return bytes(result)


def _trace_bytes(trace: list[dict[str, float]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TRACE_HEADER)
    for record in trace:
        writer.writerow([record[name] for name in TRACE_HEADER])
    return buffer.getvalue().encode("utf-8")


def _fit_one(row: dict[str, Any], fit_source_row: dict[str, Any], data, norm, initializer_cell: dict[str, Any]) -> dict[str, Any]:
    fit_id = row["fit_id"]
    fold = int(row["fold_index"])
    replicate = int(row["replicate_index"])
    block = int(row["heldout_block"])
    train_mask = data.blocks != np.uint64(block)
    held_mask = ~train_mask
    if int(train_mask.sum()) != int(row["train_rows"]) or int(held_mask.sum()) != int(row["heldout_rows"]):
        raise RuntimeError(f"row count drift before {fit_id}")
    if (
        norm.sha256 != row["normalization_sha256"]
        or norm.sha256 != fit_source_row["normalization_sha256"]
        or row["base_stream_sha256"] != fit_source_row["base_stream_sha256"]
        or row["normalized_tuple_stream_sha256"] != fit_source_row["normalized_tuple_stream_sha256"]
        or row["paired_source_input_sha256"] != fit_source_row["paired_source_input_sha256"]
    ):
        raise RuntimeError(f"shared normalized input mismatch before {fit_id}")
    labels = load_training_targets(data.keys, block)
    x_train = norm.base[train_mask]
    r_train = norm.tuples[train_mask]
    y_train = labels[train_mask]
    if set(np.unique(y_train).tolist()) != {0.0, 1.0}:
        raise RuntimeError(f"training support changed before {fit_id}")
    init_path = RUN / row["initial_tensor_path"]
    init_raw = init_path.read_bytes()
    if sha256_bytes(init_raw) != row["initial_tensor_file_sha256"]:
        raise RuntimeError(f"initial Cphi bundle changed before {fit_id}")
    initial_values = deserialize_tensors(init_raw)
    initial_hash = tensor_hash(initial_values)
    if initial_hash != row["initial_tensor_sha256"] or initial_hash != initializer_cell["initial_tensor_sha256"]:
        raise RuntimeError(f"initial Cphi tensor hash mismatch before {fit_id}")
    model = CPhiEncoder(initial_values)
    started = time.perf_counter()
    trace = model.fit_instrumented(x_train, r_train, y_train)
    runtime = time.perf_counter() - started
    if model.step != 200 * ((len(y_train) + 2047) // 2048):
        raise RuntimeError(f"Cphi optimizer update count mismatch at {fit_id}")
    if not all(np.isfinite(value).all() for value in model.values + model.m + model.v):
        raise RuntimeError(f"nonfinite Cphi model state at {fit_id}")

    held_base = norm.base[held_mask]
    held_tuples = norm.tuples[held_mask]
    held_keys = [key for key, keep in zip(data.keys, held_mask, strict=True) if keep]
    state = model.heldout_state(held_base, held_tuples)
    repeated = model.logits(held_base, held_tuples)
    if state["logits"].tobytes() != repeated.tobytes() or not np.isfinite(repeated).all():
        raise RuntimeError(f"heldout prediction determinism/finiteness failure at {fit_id}")
    key_array = np.frombuffer(b"".join(held_keys), dtype=np.uint8).reshape(len(held_keys), 18).copy()
    state_buffer = io.BytesIO()
    np.savez(
        state_buffer,
        row_keys=key_array,
        ordered_tuples=state["ordered_tuples"],
        phi_outputs=state["phi_outputs"],
        relational_concat=state["relational_concat"],
        posthoc_sum=state["posthoc_sum"],
        penultimate_hidden=state["penultimate_hidden"],
        role_separation=state["role_separation"],
        logits=state["logits"],
    )
    state_bytes = state_buffer.getvalue()
    prediction_bytes = _prediction_bytes(block, replicate, list(zip(held_keys, repeated.tolist(), strict=True)))
    final_tensor_bytes = serialize_tensors(model.values)
    trace_bytes = _trace_bytes(trace)
    pred_path = RUN / row["prediction_path"]
    state_path = RUN / row["heldout_state_path"]
    tensor_path = RUN / row["final_tensor_path"]
    trace_path = RUN / row["training_trace_path"]
    _write_new(pred_path, prediction_bytes)
    _write_new(state_path, state_bytes)
    _write_new(tensor_path, final_tensor_bytes)
    _write_new(trace_path, trace_bytes)
    receipt = {
        "schema": "F4-PRESENTATION-02-cphi-fit-receipt-v1",
        "fit_id": fit_id,
        "fold_index": fold,
        "heldout_block": block,
        "replicate_index": replicate,
        "architecture_id": "shared_phi_canonical_concat_130_101_64_1_v1",
        "parameter_count": 19_936,
        "train_rows": int(train_mask.sum()),
        "heldout_rows": int(held_mask.sum()),
        "epoch_count": 200,
        "batch_size": 2048,
        "learning_rate": 0.001,
        "update_count": model.step,
        "normalization_sha256": row["normalization_sha256"],
        "base_stream_sha256": row["base_stream_sha256"],
        "normalized_tuple_stream_sha256": row["normalized_tuple_stream_sha256"],
        "paired_source_input_sha256": row["paired_source_input_sha256"],
        "initial_tensor_sha256": initial_hash,
        "final_tensor_sha256": tensor_hash(model.values),
        "final_tensor_file_sha256": sha256_bytes(final_tensor_bytes),
        "training_trace_path": row["training_trace_path"],
        "training_trace_sha256": sha256_bytes(trace_bytes),
        "heldout_prediction_path": row["prediction_path"],
        "heldout_prediction_sha256": sha256_bytes(prediction_bytes),
        "heldout_state_path": row["heldout_state_path"],
        "heldout_state_sha256": sha256_bytes(state_bytes),
        "heldout_predictions_repeat_identical": True,
        "optimizer_summary": model.optimizer_summary(),
        "runtime_seconds": runtime,
        "finite_status": "PASS",
        "heldout_target_or_reference_read_during_fit": False,
        "comparative_metrics_emitted_during_fit": False,
    }
    receipt_bytes = _json_bytes(receipt)
    receipt_path = RUN / "fit-receipts" / f"{fit_id}.json"
    _write_new(receipt_path, receipt_bytes)
    result = {
        "fit_id": fit_id,
        "prediction_path": row["prediction_path"],
        "prediction_sha256": sha256_bytes(prediction_bytes),
        "fit_receipt_path": f"fit-receipts/{fit_id}.json",
        "fit_receipt_sha256": sha256_bytes(receipt_bytes),
        "final_tensor_sha256": tensor_hash(model.values),
        "heldout_state_sha256": sha256_bytes(state_bytes),
        "training_trace_sha256": sha256_bytes(trace_bytes),
    }
    del model, initial_values, state, trace, labels, x_train, r_train, y_train, repeated
    return result


def run() -> None:
    if (RUN / "PREDICTION-LOCK.json").exists():
        raise RuntimeError("Cphi prediction lock already exists; preserve this identity and stop")
    for directory in ("fit-receipts", "predictions", "heldout-state", "final-tensors", "training-traces"):
        path = RUN / directory
        path.mkdir(exist_ok=True)
        if any(path.iterdir()):
            raise RuntimeError(f"Cphi output directory is not empty before fit 1: {directory}")
    fit_manifest, initializer_cells, data, normalized, _parent_manifest = _verify_frozen_inputs()
    rows = fit_manifest["rows"]
    if len(rows) != 36 or len({row["fit_id"] for row in rows}) != 36:
        raise RuntimeError("Cphi fit manifest is not the frozen 36-cell surface")
    initializer_by_id = {item["fit_id"]: item for item in initializer_cells}
    parent_rows = list(csv.DictReader((PARENT_RUN / "FIT-MANIFEST.csv").open("r", encoding="utf-8", newline="")))
    parent_by_cell = {
        (int(row["fold_index"]), int(row["replicate_index"]), row["arm"]): row
        for row in parent_rows
    }
    results = []
    for row in rows:
        fit_source = parent_by_cell[(int(row["fold_index"]), int(row["replicate_index"]), "S")]
        result = _fit_one(row, fit_source, data, normalized[int(row["fold_index"])], initializer_by_id[row["fit_id"]])
        results.append(result)
        print(json.dumps({"event": "cphi_fit_complete", "fit_id": row["fit_id"], "finite_status": "PASS", "prediction_sha256": result["prediction_sha256"]}, sort_keys=True), flush=True)
    lock = {
        "schema": "F4-PRESENTATION-02-cphi-prediction-lock-v1",
        "identity": RUN_ID,
        "status": "PASS",
        "fit_count": len(results),
        "fit_manifest_sha256": sha_file(RUN / "FIT-MANIFEST.json"),
        "source_manifest_sha256": sha_file(RUN / "SOURCE-MANIFEST.json"),
        "prediction_and_state_files": results,
        "heldout_truth_opened_during_fitting": False,
    }
    write_json_new(RUN / "PREDICTION-LOCK.json", lock)
    print(json.dumps({"status": "CPHI_FIT_SURFACE_COMPLETE", "fit_count": len(results), "truth_read_during_fit": False}, sort_keys=True))


if __name__ == "__main__":
    run()
