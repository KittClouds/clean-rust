"""Run the frozen C/D leave-one-block-out qualification fits, truth blind."""
from __future__ import annotations

import csv
import json
import math
import os
import struct
import time
from pathlib import Path

import numpy as np

from common import (
    ARMS, PRED_MAGIC, read_matrix, read_predictors, read_json, runtime_description,
    require, sha_bytes, sha_file, training_hashes, training_labels, write_json,
)

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from f4_symmetry_01_model import EPOCHS, Encoder, tensor_hash  # noqa: E402


def _read_fit_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    require(len(rows) == 16, "fit grid is not 16 rows")
    expected = [(arm, block) for block in read_json(path.parent / "TASK-ID-LIST.json")["block_ids"] for arm in ARMS]
    require([(r["arm"], int(r["holdout_block"])) for r in rows] == expected, "fit manifest order/grid mismatch")
    return rows


def _prediction_bytes(arm: str, holdout: int, keys: list[bytes], logits: np.ndarray, row_hash: str) -> bytes:
    arm_id = ARMS.index(arm)
    head = PRED_MAGIC + struct.pack("<IQIQ", 1, holdout, arm_id, len(keys)) + bytes.fromhex(row_hash)
    require(len(head) == 72, "prediction header layout drift")
    body = bytearray(22 * len(keys))
    offset = 0
    for key, logit in zip(keys, logits, strict=True):
        struct.pack_into("<18sf", body, offset, key, float(logit))
        offset += 22
    return head + body


def run(run: Path) -> None:
    seal = read_json(run / "PREEXECUTION-SEAL.json")
    require(seal.get("status") == "PASS", "pre-execution seal missing or not passing")
    gates = read_json(run / "PRE-FIT-GATES.json")
    require(gates.get("status") == "PASS" and gates.get("fit_count") == 16, "prefit gates did not pass")
    require(not (run / "PREDICTION-LOCK.json").exists(), "prediction lock already exists")
    require(not any((run / "fit-receipts").glob("*.json")), "fit receipts already exist; preserve identity")
    manifest = read_json(run / "EXECUTION-MANIFEST.json")
    require(runtime_description() == manifest["runtime"], "fit runtime differs from pre-execution seal")
    blocks = [int(x) for x in manifest["block_ids"]]
    data = read_predictors(run / "RAW-PREDICTORS.bin", run / "RAW-SCORING-TRUTH.bin", blocks)
    fit_rows = _read_fit_rows(run / "FIT-MANIFEST.csv")
    row_hashes = read_json(run / "FIT-MANIFEST-ROW-HASHES.json")["rows"]
    (run / "fit-receipts").mkdir()
    (run / "heldout-predictions").mkdir()
    receipts = []
    source_sha = manifest["source_manifest_canonical_sha256"]
    binary_sha = manifest["executor_sha256"]
    script_sha = manifest["script_hashes"]["analysis.py"]
    for fold_index, holdout in enumerate(blocks):
        train_mask = data.blocks != holdout
        held_mask = ~train_mask
        labels = training_labels(data, holdout)
        training_row_hash, training_order_hash = training_hashes(data.keys, train_mask)
        for arm in ARMS:
            fit_id = f"{arm}-H{holdout}"
            row = next(item for item in fit_rows if item["fit_id"] == fit_id)
            require(row["training_row_hash"] == training_row_hash and row["training_order_hash"] == training_order_hash, f"training row identity mismatch {fit_id}")
            matrix_path = run / "prepared-inputs" / f"{fit_id}.bin"
            matrix = read_matrix(matrix_path, 90, data.count)
            require(sha_bytes(matrix_path.read_bytes()[32:]) == row["feature_hash"], f"feature input drift {fit_id}")
            x_train = matrix[train_mask]
            y_train = labels[train_mask]
            require(len(x_train) == int(row["train_rows"]), f"training row count mismatch {fit_id}")
            require(set(float(x) for x in np.unique(y_train)) == {0.0, 1.0}, f"training labels lack both classes {fit_id}")
            model = Encoder(90, fold_index)
            initial = tensor_hash(model.values)
            require(initial == row["initial_tensor_hash"], f"initial tensor mismatch {fit_id}")
            started = time.perf_counter()
            model.fit(x_train, y_train)
            elapsed = time.perf_counter() - started
            require(all(np.isfinite(t).all() for t in model.values), f"nonfinite trained model {fit_id}")
            held_x = matrix[held_mask]
            logits = model.logits(held_x)
            repeat = model.logits(held_x)
            require(logits.dtype == np.float32 and logits.tobytes() == repeat.tobytes(), f"prediction replay mismatch {fit_id}")
            require(np.isfinite(logits).all(), f"nonfinite prediction {fit_id}")
            held_keys = [key for key, keep in zip(data.keys, held_mask, strict=True) if keep]
            require(len(held_keys) == int(row["heldout_rows"]), f"heldout row count mismatch {fit_id}")
            prediction_rel = row["expected_prediction_path"]
            pred_path = run / prediction_rel
            pred_bytes = _prediction_bytes(arm, holdout, held_keys, logits, row_hashes[fit_id])
            with pred_path.open("xb") as f:
                f.write(pred_bytes)
                f.flush()
                os.fsync(f.fileno())
            pred_sha = sha_bytes(pred_bytes)
            receipt = {
                "schema": "F4-SYMMETRY-03-fit-receipt-v1", "status": "PASS", "fit_id": fit_id,
                "arm": arm, "holdout_block": holdout, "input_width": 90,
                "train_rows": len(x_train), "heldout_rows": len(held_keys),
                "contract_sha256": manifest["contract_sha256"], "source_manifest_sha256": source_sha,
                "implementation_executable_sha256": binary_sha, "analysis_script_sha256": script_sha,
                "fit_script_sha256": manifest["script_hashes"]["fit.py"],
                "feature_hash": row["feature_hash"], "training_row_hash": training_row_hash,
                "training_order_hash": training_order_hash, "normalization_hash": row["normalization_hash"],
                "initial_tensor_hash": initial, "final_tensor_hash": tensor_hash(model.values),
                "update_count": EPOCHS * math.ceil(len(x_train) / 2048),
                "finite_status": "PASS", "repeat_prediction_identical": True,
                "prediction_path": prediction_rel, "prediction_sha256": pred_sha,
                "fit_manifest_row_sha256": row_hashes[fit_id], "runtime_seconds": elapsed,
                "heldout_truth_opened": False,
            }
            receipt_path = run / "fit-receipts" / f"{fit_id}.json"
            receipt_sha = write_json(receipt_path, receipt)
            receipts.append({"fit_id": fit_id, "fit_receipt_sha256": receipt_sha, "prediction_sha256": pred_sha, "prediction_path": prediction_rel})
            print(json.dumps({"event": "fit_complete", "fit_id": fit_id, "updates": receipt["update_count"], "runtime_seconds": elapsed}, sort_keys=True), flush=True)
            del matrix, model, logits, repeat, held_x, x_train, y_train
    lock = {
        "schema": "F4-SYMMETRY-03-prediction-lock-v1", "status": "PASS",
        "prediction_count": len(receipts), "prediction_streams": receipts,
        "heldout_truth_opened": False, "comparative_metrics_emitted_during_fit": False,
    }
    write_json(run / "PREDICTION-LOCK.json", lock)
    print(json.dumps({"status": "PREDICTION_LOCKED", "fits": len(receipts), "truth_opened": False}, sort_keys=True))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True)
    run(p.parse_args().run.resolve())
