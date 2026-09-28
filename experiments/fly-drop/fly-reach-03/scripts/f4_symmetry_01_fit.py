"""Sealed-order qualification fits; held-out truth remains unopened."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import struct
import time
from pathlib import Path

from f4_symmetry_01_common import (
    ARMS, BLOCKS, CONTRACT_SHA, PRED_MAGIC, ROOT, RawData, json_read,
    read_raw, read_training_labels, runtime_description, sha_bytes, sha_file,
    verify_manifest_sources, write_json,
)
from f4_symmetry_01_model import EPOCHS, Encoder, tensor_hash


def _fit_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = [f"{arm}-H{block}" for arm in ARMS for block in BLOCKS]
    if [row["fit_id"] for row in rows] != expected:
        raise RuntimeError("FIT-MANIFEST does not match frozen 16-fit order")
    return rows


def _write_prediction(path: Path, block: int, arm: str, count: int, manifest_row_hash: str, keys: list[bytes], logits) -> bytes:
    arm_id = ARMS.index(arm)
    header = PRED_MAGIC + struct.pack("<IQIQ", 1, block, arm_id, count) + bytes.fromhex(manifest_row_hash)
    if len(header) != 72:
        raise RuntimeError("prediction header is not 72 bytes")
    with path.open("xb") as stream:
        stream.write(header)
        for key, logit in zip(keys, logits, strict=True):
            value = struct.pack("<f", float(logit))
            stream.write(key)
            stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    return path.read_bytes()


def run_fits(out: Path) -> None:
    preflight = json_read(out / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json")
    gates = json_read(out / "PRE-FIT-GATES.json")
    if preflight.get("status") != "PASS" or gates.get("status") != "PASS":
        raise RuntimeError("preflight and all implementation gates must pass before fit 1")
    if any(out.glob("*-STOP-RECEIPT.json")):
        raise RuntimeError("this fit identity contains a prior STOP receipt; preserve it and use a fresh identity")
    if (out / "PREDICTION-LOCK.json").exists() or any((out / "fit-receipts").glob("*.json")):
        raise RuntimeError("fit identity has already started; preserve it and stop")
    sources = verify_manifest_sources(out / "SOURCE-INPUT-MANIFEST.json")
    if sources["canonical_sha256"] != preflight["source_manifest_sha256"] or sources["file_sha256"] != preflight["source_manifest_file_sha256"]:
        raise RuntimeError("source-manifest digest mismatch")
    runtime = runtime_description()
    if runtime != preflight["runtime"]:
        raise RuntimeError("fit runtime differs from frozen preflight runtime")
    data = read_raw(out / "RAW-PREDICTORS.bin", out / "RAW-SCORING-TRUTH.bin")
    manifest_rows = _fit_rows(out / "FIT-MANIFEST.csv")
    linehashes = json_read(out / "FIT-MANIFEST-ROW-HASHES.json")
    fold_index = {block: index for index, block in enumerate(BLOCKS)}
    receipts: list[dict[str, object]] = []
    for row in manifest_rows:
        arm = row["arm"]
        block = int(row["holdout_block"])
        fit_id = row["fit_id"]
        fit_index = fold_index[block]
        training_mask = data.blocks != block
        heldout_mask = ~training_mask
        matrix_path = out / "prepared-inputs" / f"{fit_id}.bin"
        matrix_raw = matrix_path.read_bytes()
        feature_hash = sha_bytes(matrix_raw[32:])
        if feature_hash != row["feature_hash"]:
            raise RuntimeError(f"prepared feature hash mismatch before {fit_id}")
        input_width = int(row["input_width"])
        from f4_symmetry_01_common import binary_matrix
        matrix = binary_matrix(matrix_path, input_width)
        targets = read_training_labels(data, block)
        x_train = matrix[training_mask]
        y_train = targets[training_mask]
        if len(x_train) != int(row["train_rows"]) or np_unique(y_train) != {0.0, 1.0}:
            raise RuntimeError(f"training support mismatch for {fit_id}")
        model = Encoder(input_width, fit_index)
        initial_hash = tensor_hash(model.values)
        if initial_hash != row["initial_tensor_hash"]:
            raise RuntimeError(f"initial tensor hash mismatch for {fit_id}")
        print(json.dumps({"event": "fit_started", "fit_id": fit_id, "train_rows": len(x_train), "heldout_rows": int(heldout_mask.sum())}, sort_keys=True), flush=True)
        started = time.perf_counter()
        model.fit(x_train, y_train)
        runtime_seconds = time.perf_counter() - started
        finite = all(bool(np_isfinite(value)) for value in model.values)
        if not finite:
            raise RuntimeError(f"nonfinite model tensors for {fit_id}")
        logits = model.logits(matrix[heldout_mask])
        repeated = model.logits(matrix[heldout_mask])
        if logits.dtype != np_dtype_f32() or logits.tobytes() != repeated.tobytes() or not np_all_finite(logits):
            raise RuntimeError(f"repeat prediction byte/finiteness check failed for {fit_id}")
        heldout_keys = [key for key, keep in zip(data.keys, heldout_mask, strict=True) if keep]
        prediction_rel = row["expected_prediction_path"]
        prediction_path = out / prediction_rel
        prediction_bytes = _write_prediction(prediction_path, block, arm, len(heldout_keys), linehashes["rows"][fit_id], heldout_keys, logits)
        prediction_hash = sha_bytes(prediction_bytes)
        final_hash = tensor_hash(model.values)
        receipt = {
            "schema": "F4-SYMMETRY-01-fit-receipt-v1",
            "fit_id": fit_id,
            "arm": arm,
            "holdout_block": block,
            "input_width": input_width,
            "train_rows": len(x_train),
            "heldout_rows": len(heldout_keys),
            "contract_sha256": CONTRACT_SHA,
            "source_manifest_sha256": preflight["source_manifest_sha256"],
            "implementation_executable_sha256": row["implementation_executable_sha256"],
            "analysis_script_sha256": row["analysis_script_sha256"],
            "feature_hash": feature_hash,
            "training_row_hash": row["training_row_hash"],
            "training_order_hash": row["training_order_hash"],
            "normalization_hash": row["normalization_hash"],
            "initial_tensor_hash": initial_hash,
            "final_tensor_hash": final_hash,
            "update_count": EPOCHS * math.ceil(len(x_train) / 2048),
            "finite_status": "PASS",
            "repeat_prediction_identical": True,
            "prediction_path": prediction_rel,
            "prediction_sha256": prediction_hash,
            "fit_manifest_row_sha256": linehashes["rows"][fit_id],
            "runtime_seconds": runtime_seconds,
        }
        receipt_path = out / "fit-receipts" / f"{fit_id}.json"
        receipt_bytes = write_json(receipt_path, receipt)
        receipts.append({"fit_id": fit_id, "fit_receipt_sha256": sha_bytes(receipt_bytes), "prediction_sha256": prediction_hash, "prediction_path": prediction_rel})
        del model, matrix, targets, x_train, y_train, logits, repeated
        print(json.dumps({"event": "fit_completed", "fit_id": fit_id, "updates": receipt["update_count"], "finite_status": "PASS", "runtime_seconds": runtime_seconds, "prediction_sha256": prediction_hash}, sort_keys=True), flush=True)
    lock = {
        "schema": "F4-SYMMETRY-01-prediction-lock-v1",
        "status": "PASS",
        "prediction_count": len(receipts),
        "prediction_streams": receipts,
        "comparative_metrics_emitted_during_fit": False,
        "heldout_truth_opened": False,
    }
    write_json(out / "PREDICTION-LOCK.json", lock)
    after = verify_manifest_sources(out / "SOURCE-INPUT-MANIFEST.json")
    if after["canonical_sha256"] != preflight["source_manifest_sha256"] or after["file_sha256"] != preflight["source_manifest_file_sha256"]:
        raise RuntimeError("source drift after fit collection")
    print(json.dumps({"status": "FIT_COLLECTION_COMPLETE", "fit_count": len(receipts), "truth_opened": False}, sort_keys=True))


def np_unique(values):
    import numpy as np
    return set(float(value) for value in np.unique(values))


def np_isfinite(values):
    import numpy as np
    return np.isfinite(values).all()


def np_all_finite(values):
    import numpy as np
    return bool(np.isfinite(values).all())


def np_dtype_f32():
    import numpy as np
    return np.dtype(np.float32)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/f4-symmetry-01")
    args = parser.parse_args()
    run_fits(args.out)


if __name__ == "__main__":
    main()
