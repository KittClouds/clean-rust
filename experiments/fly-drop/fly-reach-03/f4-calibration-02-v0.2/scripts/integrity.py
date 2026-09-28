"""Verify the locked D-only calibration panel before scoring held-out truth."""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
STUDY = HERE.parents[1]
sys.path.insert(0, str(STUDY / "f4-symmetry-03" / "scripts"))
sys.path.insert(0, str(STUDY / "scripts"))
from common import (  # noqa: E402
    PRED_MAGIC, REPO, canonical_json, read_json, read_predictors, require,
    runtime_description, sha_bytes, sha_file, write_json,
)
from f4_symmetry_01_model import EPOCHS  # noqa: E402


def _manifest_rows(run: Path) -> tuple[list[dict[str, str]], list[str]]:
    with (run / "FIT-MANIFEST.csv").open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    expected = [
        "fit_id", "arm", "holdout_block", "input_width", "train_rows", "heldout_rows",
        "feature_hash", "training_row_hash", "training_order_hash", "normalization_hash",
        "initial_tensor_hash", "expected_prediction_path",
    ]
    require(fields == expected, "fit-manifest field schema mismatch")
    return rows, expected


def _source_check(run: Path, manifest: dict[str, object]) -> dict[str, object]:
    path = run / "SOURCE-INPUT-MANIFEST.json"
    source = read_json(path)
    require(source.get("schema") == "F4-CALIBRATION-02-v0.2-source-input-manifest-v1", "source manifest schema mismatch")
    entries = source.get("entries")
    require(isinstance(entries, list) and entries, "source manifest entries missing")
    actual = []
    for entry in entries:
        rel = str(entry["path"])
        parts = rel.split("/")
        require(rel and all(part not in ("", ".", "..") for part in parts), "unsafe source path")
        target = REPO.joinpath(*parts)
        require(target.is_file(), f"sealed source missing: {rel}")
        actual.append({"path": rel, "byte_length": target.stat().st_size, "sha256": sha_file(target)})
    actual.sort(key=lambda item: item["path"].encode("utf-8"))
    require(actual == entries, "a sealed source/input artifact changed")
    canonical_sha = sha_bytes(canonical_json(source))
    file_sha = sha_file(path)
    require(canonical_sha == manifest["source_manifest_canonical_sha256"], "canonical source-manifest digest mismatch")
    require(file_sha == manifest["source_manifest_file_sha256"], "source-manifest file digest mismatch")
    return {"canonical_sha256": canonical_sha, "file_sha256": file_sha, "entry_count": len(entries)}


def _prediction(path: Path, holdout: int, expected_keys: list[bytes], row_hash: str) -> int:
    raw = path.read_bytes()
    require(len(raw) >= 72 and raw[:16] == PRED_MAGIC, f"prediction header invalid: {path.name}")
    version, block, arm_id, count = struct.unpack_from("<IQIQ", raw, 16)
    require((version, block, arm_id, count) == (1, holdout, 1, len(expected_keys)), f"prediction identity/count mismatch: {path.name}")
    require(raw[40:72].hex() == row_hash, f"fit-row digest mismatch: {path.name}")
    require(len(raw) == 72 + 22 * count, f"prediction byte length mismatch: {path.name}")
    offset = 72
    for index, key in enumerate(expected_keys):
        require(raw[offset:offset + 18] == key, f"prediction key/order mismatch {path.name}:{index}")
        value = struct.unpack_from("<f", raw, offset + 18)[0]
        require(math.isfinite(value), f"nonfinite locked logit {path.name}:{index}")
        offset += 22
    return count


def verify(run: Path) -> None:
    seal = read_json(run / "PREEXECUTION-SEAL.json")
    require(seal.get("status") == "PASS" and seal.get("qualification_only") is True, "pre-execution seal invalid")
    require(seal.get("measured_reach03_authorized") is False, "unexpected measured authorization")
    manifest_path = run / "EXECUTION-MANIFEST.json"
    require(sha_file(manifest_path) == seal["execution_manifest_file_sha256"], "execution manifest changed after seal")
    manifest = read_json(manifest_path)
    require(manifest["run_id"] == seal["run_id"] and manifest["contract_sha256"] == seal["contract_sha256"], "execution identity mismatch")
    require(runtime_description() == manifest["runtime"], "integrity runtime differs from sealed runtime")
    source_result = _source_check(run, manifest)

    task_manifest = read_json(run / "task-bank/TASK-BANK-MANIFEST.json")
    task_receipt = read_json(run / "task-bank/TASK-BANK-RECEIPT.json")
    blocks = [int(value) for value in manifest["block_ids"]]
    require(blocks == list(range(305012, 305024)), "unexpected v0.2 calibration block list")
    require(task_manifest["accepted_block_ids"] == blocks and task_manifest["structural_pattern_selection"] is False,
            "task bank differs from the frozen ordinary block set")
    require(task_receipt["status"] == "PASS" and task_receipt["outcome_selection"] is False,
            "task bank receipt is not passing")
    require(sha_file(run / "task-bank/training.json") == manifest["task_training_sha256"], "task training bytes changed")

    staging = run / "collection-staging"
    require({item.name for item in staging.iterdir()} == {
        "RAW-PREDICTORS.bin", "RAW-SCORING-TRUTH.bin", "NATIVE-COLLECTION-RECEIPT.json",
    }, "collection staging contains missing or extra artifacts")
    collection = read_json(staging / "NATIVE-COLLECTION-RECEIPT.json")
    require(collection.get("schema") == "F4-CALIBRATION-02-v0.2-native-collection-v1" and collection.get("status") == "PASS",
            "native collection receipt invalid")
    require(collection.get("block_ids") == blocks and collection.get("stream_count") == 216 and
            collection.get("expected_stream_count") == 216, "native collection grid incomplete")
    pred_path = staging / "RAW-PREDICTORS.bin"
    truth_path = staging / "RAW-SCORING-TRUTH.bin"
    require(sha_file(pred_path) == collection["predictor_sha256"], "predictor hash differs from collector receipt")
    require(sha_file(truth_path) == collection["truth_sha256"], "truth hash differs from collector receipt")
    streams = collection.get("streams")
    require(isinstance(streams, list) and len(streams) == 216, "native stream receipts missing")
    expected_streams = {
        (substrate, side, block)
        for substrate in ("fly", *(f"g{i:03d}" for i in range(1, 9)))
        for side in ("L", "R") for block in blocks
    }
    actual_streams = {(item["substrate"], item["side"], int(item["block_id"])) for item in streams}
    require(actual_streams == expected_streams and all(item["status"] == "PASS" for item in streams),
            "native collection has a missing, duplicate, or failed stream")
    require(sum(int(item["rows"]) for item in streams) == int(collection["row_count"]), "stream counts do not reconcile")
    require(collection.get("p_forward_fixture_status") == "PASS" and collection.get("measured_namespace_created") is False,
            "forward reconciliation or namespace status invalid")

    # This reads feature bytes and only the truth header. It does not inspect any target values.
    data = read_predictors(pred_path, truth_path, blocks)
    require(data.count == int(collection["row_count"]), "predictor row count differs from collection receipt")
    observed_blocks = set(int(value) for value in data.blocks)
    require(observed_blocks.issubset(set(blocks)), "U* contains a row outside the frozen block set")
    empty_blocks = [block for block in blocks if block not in observed_blocks]

    prep_gates = read_json(run / "PRE-FIT-GATES.json")
    prep_receipt = read_json(run / "FIT-PREPARATION-RECEIPT.json")
    require(prep_gates.get("schema") == "F4-CALIBRATION-02-v0.2-prefit-gates-v1" and
            prep_gates.get("status") == "PASS" and prep_gates.get("fit_count") == 12 and
            prep_gates.get("heldout_truth_opened") is False, "prefit gate receipt invalid")
    require(prep_receipt.get("schema") == "F4-CALIBRATION-02-v0.2-fit-preparation-v1" and
            prep_receipt.get("status") == "PASS" and prep_receipt.get("heldout_truth_opened") is False and
            prep_receipt.get("truth_values_opened") is False,
            "fit preparation receipt invalid")
    rows, fields = _manifest_rows(run)
    require(len(rows) == 12, "fit manifest does not contain twelve rows")
    require([(row["arm"], int(row["holdout_block"])) for row in rows] == [("D", block) for block in blocks],
            "fit manifest is not the frozen D-only Cartesian panel")
    row_record = read_json(run / "FIT-MANIFEST-ROW-HASHES.json")
    require(row_record["manifest_sha256"] == sha_file(run / "FIT-MANIFEST.csv"), "fit manifest digest mismatch")
    row_hashes: dict[str, str] = {}
    for row in rows:
        output = io.StringIO(newline="")
        csv.writer(output, lineterminator="\n").writerow([row[field] for field in fields])
        row_hashes[row["fit_id"]] = sha_bytes(output.getvalue().encode("utf-8"))
    require(row_hashes == row_record["rows"], "fit manifest row digests mismatch")
    require(row_record["order"] == [row["fit_id"] for row in rows], "fit manifest row order receipt mismatch")

    fit_dir = run / "fit-receipts"
    prediction_dir = run / "heldout-predictions"
    expected_ids = {f"D-H{block}" for block in blocks}
    require({path.stem for path in fit_dir.glob("*.json")} == expected_ids, "fit receipts missing or extra")
    require({path.stem for path in prediction_dir.glob("*.bin")} == expected_ids, "prediction streams missing or extra")
    lock = read_json(run / "PREDICTION-LOCK.json")
    require(lock.get("schema") == "F4-CALIBRATION-02-v0.2-prediction-lock-v1" and
            lock.get("status") == "PASS" and lock.get("prediction_count") == 12 and
            lock.get("heldout_truth_opened") is False and lock.get("comparative_metrics_emitted_during_fit") is False,
            "prediction lock invalid")
    locked = {entry["fit_id"]: entry for entry in lock["prediction_streams"]}
    require(set(locked) == expected_ids, "prediction lock fit identities mismatch")

    verified = []
    for row in rows:
        fit_id = row["fit_id"]
        block = int(row["holdout_block"])
        receipt_path = fit_dir / f"{fit_id}.json"
        receipt = read_json(receipt_path)
        require(receipt.get("schema") == "F4-CALIBRATION-02-v0.2-fit-receipt-v1" and receipt.get("status") == "PASS" and
                receipt.get("finite_status") == "PASS", f"fit receipt status invalid: {fit_id}")
        require(receipt.get("heldout_truth_opened") is False and receipt.get("repeat_prediction_identical") is True,
                f"fit truth/replay audit failed: {fit_id}")
        for field in ("fit_id", "arm", "feature_hash", "training_row_hash", "training_order_hash", "normalization_hash", "initial_tensor_hash"):
            require(str(receipt[field]) == str(row[field]), f"fit receipt mismatch {fit_id}:{field}")
        for field in ("holdout_block", "input_width", "train_rows", "heldout_rows"):
            require(int(receipt[field]) == int(row[field]), f"fit receipt mismatch {fit_id}:{field}")
        require(receipt.get("contract_sha256") == manifest["contract_sha256"] and
                receipt.get("source_manifest_sha256") == manifest["source_manifest_canonical_sha256"] and
                receipt.get("implementation_executable_sha256") == manifest["executor_sha256"] and
                receipt.get("fit_script_sha256") == manifest["script_hashes"]["fit_d.py"], f"fit provenance mismatch: {fit_id}")
        require(receipt.get("prediction_path") == row["expected_prediction_path"], f"prediction path mismatch: {fit_id}")
        require(receipt.get("fit_manifest_row_sha256") == row_hashes[fit_id], f"fit row receipt mismatch: {fit_id}")
        require(int(receipt["update_count"]) == EPOCHS * math.ceil(int(row["train_rows"]) / 2048),
                f"update count mismatch: {fit_id}")
        matrix_path = run / "prepared-inputs" / f"{fit_id}.bin"
        matrix = matrix_path.read_bytes()
        require(sha_bytes(matrix[32:]) == row["feature_hash"], f"prepared D feature changed: {fit_id}")
        norm_path = run / "normalization" / f"NORMALIZATION-{block}.bin"
        require(sha_file(norm_path) == row["normalization_hash"], f"normalization bytes changed: {fit_id}")
        held_keys = [key for key in data.keys if struct.unpack_from("<Q", key, 2)[0] == block]
        prediction_path = run / row["expected_prediction_path"]
        prediction_sha = sha_file(prediction_path)
        require(prediction_sha == receipt["prediction_sha256"] == locked[fit_id]["prediction_sha256"],
                f"prediction hash mismatch: {fit_id}")
        require(sha_file(receipt_path) == locked[fit_id]["receipt_sha256"], f"locked receipt hash mismatch: {fit_id}")
        count = _prediction(prediction_path, block, held_keys, row_hashes[fit_id])
        require(count == int(row["heldout_rows"]), f"prediction coverage mismatch: {fit_id}")
        verified.append({"fit_id": fit_id, "fit_receipt_sha256": sha_file(receipt_path),
                         "prediction_sha256": prediction_sha, "prediction_rows": count})

    forbidden = ("ANALYSIS.json", "FINAL-OUTCOMES.csv", "RESULTS.md", "F4-CALIBRATION-RECEIPT.json")
    require(not any((run / name).exists() for name in forbidden), "analysis/result artifacts exist before integrity")
    receipt = {
        "schema": "F4-CALIBRATION-02-integrity-receipt-v1", "status": "PASS",
        "run_id": manifest["run_id"], "contract_sha256": manifest["contract_sha256"],
        "preexecution_seal_sha256": sha_file(run / "PREEXECUTION-SEAL.json"),
        "source_manifest": source_result, "native_collection_sha256": sha_file(staging / "NATIVE-COLLECTION-RECEIPT.json"),
        "expected_fit_count": 12, "actual_fit_count": len(rows),
        "expected_native_stream_count": 216, "actual_native_stream_count": len(streams),
        "row_count": data.count, "block_ids": blocks, "empty_Ustar_block_ids": empty_blocks,
        "missing_count": 0, "duplicate_count": 0, "extra_count": 0, "nonfinite_count": 0,
        "all_fit_receipts_pass": True, "all_predictions_finite_and_complete": True,
        "heldout_truth_state": "SEALED", "heldout_truth_values_opened": False,
        "verified_fits": verified,
    }
    write_json(run / "INTEGRITY-RECEIPT.json", receipt)
    print(json.dumps({"status": "INTEGRITY_PASS", "fits": 12, "rows": data.count,
                      "empty_blocks": empty_blocks, "truth_state": "SEALED"}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    verify(parser.parse_args().run.resolve())
