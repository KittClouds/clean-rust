from __future__ import annotations

import argparse
import csv
import json
import math
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
STUDY = HERE.parents[1]
sys.path.insert(0, str(STUDY / "f4-symmetry-03" / "scripts"))
sys.path.insert(0, str(STUDY / "scripts"))
from common import (  # noqa: E402
    PRED_MAGIC, read_matrix, read_predictors, read_json, runtime_description,
    require, sha_bytes, sha_file, training_hashes, training_labels, write_json,
)
from f4_symmetry_01_model import EPOCHS, Encoder, tensor_hash  # noqa: E402


def _prediction_bytes(holdout: int, keys: list[bytes], logits: np.ndarray, row_hash: str) -> bytes:
    # Arm id 1 is D in the frozen SYMMETRY-03 prediction format.
    header = PRED_MAGIC + struct.pack("<IQIQ", 1, holdout, 1, len(keys)) + bytes.fromhex(row_hash)
    require(len(header) == 72, "prediction header layout drift")
    body = bytearray(22 * len(keys))
    for ix, (key, logit) in enumerate(zip(keys, logits, strict=True)):
        struct.pack_into("<18sf", body, 22 * ix, key, float(logit))
    return header + body


def fit_all(run: Path) -> None:
    seal = read_json(run / "PREEXECUTION-SEAL.json")
    require(seal.get("status") == "PASS", "pre-execution seal missing")
    execution_path = run / "EXECUTION-MANIFEST.json"
    require(sha_file(execution_path) == seal["execution_manifest_file_sha256"], "execution manifest changed after seal")
    prefit = read_json(run / "PRE-FIT-GATES.json")
    preparation = read_json(run / "FIT-PREPARATION-RECEIPT.json")
    require(prefit.get("schema") == "F4-CALIBRATION-02-v0.2-prefit-gates-v1" and
            prefit.get("status") == "PASS" and prefit.get("fit_count") == 12 and
            prefit.get("heldout_truth_opened") is False, "pre-fit gates did not pass")
    require(preparation.get("schema") == "F4-CALIBRATION-02-v0.2-fit-preparation-v1" and
            preparation.get("status") == "PASS" and
            preparation.get("manifest_sha256") == sha_file(run / "FIT-MANIFEST.csv") and
            preparation.get("truth_values_opened") is False, "fit-preparation receipt does not match")
    require(not (run / "PREDICTION-LOCK.json").exists(), "prediction lock already exists")
    require(not any((run / "fit-receipts").glob("*.json")), "fit receipts already exist")
    manifest = read_json(run / "EXECUTION-MANIFEST.json")
    require(runtime_description() == manifest["runtime"], "fit runtime differs from sealed runtime")
    require(manifest["script_hashes"]["fit_d.py"] == sha_file(Path(__file__)), "fit implementation differs from seal")
    blocks = [int(x) for x in manifest["block_ids"]]
    require(len(blocks) == 12 and blocks == sorted(blocks), "sealed holdout list invalid")
    collection = run / "collection-staging"
    data = read_predictors(collection / "RAW-PREDICTORS.bin", collection / "RAW-SCORING-TRUTH.bin", blocks)
    with (run / "FIT-MANIFEST.csv").open("r", encoding="utf-8", newline="") as stream:
        fit_rows = list(csv.DictReader(stream))
    require(len(fit_rows) == 12, "fit grid is not twelve D-only rows")
    expected_ids = [f"D-H{block}" for block in blocks]
    require([row["fit_id"] for row in fit_rows] == expected_ids, "fit grid/order mismatch")
    row_hashes = read_json(run / "FIT-MANIFEST-ROW-HASHES.json")["rows"]
    (run / "fit-receipts").mkdir()
    (run / "heldout-predictions").mkdir()
    receipts = []
    for fold_index, (holdout, row) in enumerate(zip(blocks, fit_rows, strict=True)):
        fit_id = f"D-H{holdout}"
        require(row["fit_id"] == fit_id and row["arm"] == "D", f"fit identity mismatch {fit_id}")
        train_mask = data.blocks != holdout
        held_mask = ~train_mask
        training_row_hash, training_order_hash = training_hashes(data.keys, train_mask)
        require(row["training_row_hash"] == training_row_hash and row["training_order_hash"] == training_order_hash,
                f"training row/order drift {fit_id}")
        matrix_path = run / "prepared-inputs" / f"{fit_id}.bin"
        matrix = read_matrix(matrix_path, 90, data.count)
        require(sha_bytes(matrix_path.read_bytes()[32:]) == row["feature_hash"], f"D input feature hash mismatch {fit_id}")
        x_train = matrix[train_mask]
        y_train = training_labels(data, holdout)[train_mask]
        require(len(x_train) == int(row["train_rows"]), f"training row count mismatch {fit_id}")
        require(set(float(x) for x in np.unique(y_train)) == {0.0, 1.0}, f"training labels lack both classes {fit_id}")
        model = Encoder(90, fold_index)
        initial_hash = tensor_hash(model.values)
        require(initial_hash == row["initial_tensor_hash"], f"initial tensor differs from frozen seed {fit_id}")
        started = time.perf_counter()
        model.fit(x_train, y_train)
        runtime = time.perf_counter() - started
        require(all(np.isfinite(tensor).all() for tensor in model.values), f"nonfinite trained parameters {fit_id}")
        held_x = matrix[held_mask]
        logits = model.logits(held_x)
        repeat = model.logits(held_x)
        require(logits.dtype == np.float32 and logits.tobytes() == repeat.tobytes(), f"prediction replay mismatch {fit_id}")
        require(np.isfinite(logits).all(), f"nonfinite heldout logits {fit_id}")
        held_keys = [key for key, keep in zip(data.keys, held_mask, strict=True) if keep]
        require(len(held_keys) == int(row["heldout_rows"]), f"heldout row count mismatch {fit_id}")
        prediction_rel = f"heldout-predictions/{fit_id}.bin"
        prediction = _prediction_bytes(holdout, held_keys, logits, row_hashes[fit_id])
        prediction_path = run / prediction_rel
        with prediction_path.open("xb") as stream:
            stream.write(prediction)
            stream.flush()
            os.fsync(stream.fileno())
        prediction_hash = sha_bytes(prediction)
        receipt = {
            "schema": "F4-CALIBRATION-02-v0.2-fit-receipt-v1", "status": "PASS", "fit_id": fit_id,
            "arm": "D", "holdout_block": holdout, "input_width": 90,
            "train_rows": len(x_train), "heldout_rows": len(held_keys),
            "contract_sha256": manifest["contract_sha256"],
            "source_manifest_sha256": manifest["source_manifest_canonical_sha256"],
            "implementation_executable_sha256": manifest["executor_sha256"],
            "fit_script_sha256": manifest["script_hashes"]["fit_d.py"],
            "feature_hash": row["feature_hash"], "training_row_hash": training_row_hash,
            "training_order_hash": training_order_hash, "normalization_hash": row["normalization_hash"],
            "initial_tensor_hash": initial_hash, "final_tensor_hash": tensor_hash(model.values),
            "update_count": EPOCHS * math.ceil(len(x_train) / 2048),
            "finite_status": "PASS", "repeat_prediction_identical": True,
            "prediction_path": prediction_rel, "prediction_sha256": prediction_hash,
            "fit_manifest_row_sha256": row_hashes[fit_id], "runtime_seconds": runtime,
            "heldout_truth_opened": False,
        }
        receipt_path = run / "fit-receipts" / f"{fit_id}.json"
        receipt_hash = write_json(receipt_path, receipt)
        receipts.append({"fit_id": fit_id, "receipt_sha256": receipt_hash,
                         "prediction_path": prediction_rel, "prediction_sha256": prediction_hash})
        print(json.dumps({"event": "fit_complete", "fit_id": fit_id,
                          "updates": receipt["update_count"], "runtime_seconds": runtime}, sort_keys=True), flush=True)
        del matrix, model, logits, repeat, held_x, x_train, y_train
    lock = {
        "schema": "F4-CALIBRATION-02-v0.2-prediction-lock-v1", "status": "PASS",
        "prediction_count": len(receipts), "prediction_streams": receipts,
        "heldout_truth_opened": False, "comparative_metrics_emitted_during_fit": False,
    }
    write_json(run / "PREDICTION-LOCK.json", lock)
    print(json.dumps({"status": "PREDICTION_LOCKED", "fits": len(receipts), "truth_opened": False}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    fit_all(parser.parse_args().run.resolve())
