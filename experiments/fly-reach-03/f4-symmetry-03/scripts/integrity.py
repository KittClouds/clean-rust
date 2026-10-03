"""Independent pre-truth integrity gate for the locked C/D prediction panel."""
from __future__ import annotations

import csv
import json
import math
import struct
from pathlib import Path

import numpy as np

from common import (
    ARMS, PRED_MAGIC, REPO, read_json, read_predictors, require, runtime_description, sha_bytes,
    sha_file, write_json,
)


def _fit_rows(run: Path) -> tuple[list[dict[str, str]], list[str]]:
    with (run / "FIT-MANIFEST.csv").open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    expected_fields = [
        "fit_id", "arm", "holdout_block", "input_width", "train_rows", "heldout_rows",
        "feature_hash", "training_row_hash", "training_order_hash", "normalization_hash",
        "initial_tensor_hash", "expected_prediction_path", "contract_sha256",
        "source_manifest_sha256", "analysis_script_sha256",
    ]
    require(fields == expected_fields, "FIT-MANIFEST schema mismatch")
    return rows, fields


def _source_manifest_check(run: Path, manifest: dict[str, object]) -> dict[str, object]:
    source = read_json(run / "SOURCE-INPUT-MANIFEST.json")
    require(source.get("schema") == "F4-SYMMETRY-03-source-input-manifest-v1", "source manifest schema mismatch")
    entries = source["entries"]
    require(isinstance(entries, list), "source manifest entries malformed")
    actual = []
    for entry in entries:
        rel = str(entry["path"])
        require(".." not in rel.split("/") and "." not in rel.split("/"), "unsafe source manifest path")
        path = REPO / Path(rel)
        actual.append({"path": rel, "byte_length": path.stat().st_size, "sha256": sha_file(path)})
    actual.sort(key=lambda row: row["path"].encode("utf-8"))
    require(actual == entries, "a frozen source/input artifact changed")
    canonical_hash = sha_bytes(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    file_hash = sha_file(run / "SOURCE-INPUT-MANIFEST.json")
    require(canonical_hash == manifest["source_manifest_canonical_sha256"], "canonical source-manifest hash mismatch")
    require(file_hash == manifest["source_manifest_file_sha256"], "source-manifest file hash mismatch")
    return {"canonical_sha256": canonical_hash, "file_sha256": file_hash, "entry_count": len(entries)}


def _prediction(path: Path, row: dict[str, str], expected_keys: list[bytes], row_sha: str) -> np.ndarray:
    raw = path.read_bytes()
    require(len(raw) >= 72 and raw[:16] == PRED_MAGIC, f"prediction header invalid: {path.name}")
    version, block, arm_id, count = struct.unpack_from("<IQIQ", raw, 16)
    require((version, block, arm_id, count) == (1, int(row["holdout_block"]), ARMS.index(row["arm"]), len(expected_keys)), f"prediction identity/count mismatch: {path.name}")
    require(raw[40:72].hex() == row_sha, f"fit-row hash mismatch in prediction: {path.name}")
    require(len(raw) == 72 + 22 * count, f"prediction length mismatch: {path.name}")
    logits = np.empty(count, dtype=np.float32)
    offset = 72
    for i, key in enumerate(expected_keys):
        require(raw[offset:offset + 18] == key, f"prediction row order/key mismatch {path.name}:{i}")
        logits[i] = struct.unpack_from("<f", raw, offset + 18)[0]
        offset += 22
    require(np.isfinite(logits).all(), f"nonfinite prediction logits {path.name}")
    return logits


def run_integrity(run: Path) -> None:
    seal = read_json(run / "PREEXECUTION-SEAL.json")
    require(seal.get("status") == "PASS", "pre-execution seal not passing")
    execution_path = run / "EXECUTION-MANIFEST.json"
    require(sha_file(execution_path) == seal["execution_manifest_file_sha256"], "execution manifest changed after seal")
    manifest = read_json(execution_path)
    require(manifest["contract_sha256"] == seal["contract_sha256"], "contract identity mismatch")
    require(runtime_description() == manifest["runtime"], "integrity runtime differs from pre-execution seal")
    source_details = _source_manifest_check(run, manifest)
    transfer_path = run / "COLLECTION-TRANSFER-RECEIPT.json"
    transfer = read_json(transfer_path)
    require(transfer.get("status") == "PASS" and sha_file(transfer_path) == manifest.get("native_collection_transfer_sha256"), "native collection transfer receipt mismatch")
    require(transfer.get("source_run_id") == manifest.get("native_collection_origin_run_id"), "native collection source identity mismatch")
    transfer_files = {str(x["name"]): x for x in transfer["files"]}
    for name in ("RAW-PREDICTORS.bin", "RAW-SCORING-TRUTH.bin", "NATIVE-COLLECTION-RECEIPT.json"):
        dst = run / name
        item = transfer_files.get(name)
        require(item is not None and sha_file(dst) == item["destination_sha256"] == item["source_sha256"], f"reused collection copy changed: {name}")
        require(dst.stat().st_size == item["source_bytes"] == item["destination_bytes"], f"reused collection size changed: {name}")
    require(sha_file(run / "RAW-PREDICTORS.bin") == read_json(run / "NATIVE-COLLECTION-RECEIPT.json")["predictor_sha256"], "predictor bytes differ from collection receipt")
    collection = read_json(run / "NATIVE-COLLECTION-RECEIPT.json")
    require(collection.get("status") == "PASS" and collection.get("stream_count") == 144, "native collection receipt incomplete")
    require(sha_file(run / "RAW-SCORING-TRUTH.bin") == collection["truth_sha256"], "truth bytes differ from collection receipt")
    blocks = [int(x) for x in manifest["block_ids"]]
    data = read_predictors(run / "RAW-PREDICTORS.bin", run / "RAW-SCORING-TRUTH.bin", blocks)
    empty_blocks = [block for block in blocks if not np.any(data.blocks == block)]
    require(data.count == collection["row_count"], "row count differs from collector receipt")

    rows, fields = _fit_rows(run)
    expected_order = [(arm, block) for block in blocks for arm in ARMS]
    require(len(rows) == 16 and [(r["arm"], int(r["holdout_block"])) for r in rows] == expected_order, "FIT-MANIFEST Cartesian grid/order mismatch")
    row_hash_record = read_json(run / "FIT-MANIFEST-ROW-HASHES.json")
    require(row_hash_record["manifest_sha256"] == sha_file(run / "FIT-MANIFEST.csv"), "FIT-MANIFEST file hash mismatch")
    recomputed_row_hashes = {}
    for row in rows:
        import io
        buf = io.StringIO(newline="")
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow([row[field] for field in fields])
        recomputed_row_hashes[row["fit_id"]] = sha_bytes(buf.getvalue().encode("utf-8"))
        require(row["contract_sha256"] == manifest["contract_sha256"], "fit row contract hash mismatch")
        require(row["source_manifest_sha256"] == manifest["source_manifest_canonical_sha256"], "fit row source-manifest hash mismatch")
        require(row["analysis_script_sha256"] == manifest["script_hashes"]["analysis.py"], "fit row analysis hash mismatch")
    require(recomputed_row_hashes == row_hash_record["rows"], "FIT-MANIFEST row hashes mismatch")

    expected_receipts = {f"{arm}-H{block}.json" for block in blocks for arm in ARMS}
    expected_predictions = {f"{arm}-H{block}.bin" for block in blocks for arm in ARMS}
    receipt_paths = {p.name for p in (run / "fit-receipts").glob("*.json")}
    pred_paths = {p.name for p in (run / "heldout-predictions").glob("*.bin")}
    require(receipt_paths == expected_receipts, "missing, duplicate, or extra fit receipts")
    require(pred_paths == expected_predictions, "missing, duplicate, or extra prediction streams")
    lock = read_json(run / "PREDICTION-LOCK.json")
    require(lock.get("status") == "PASS" and lock.get("prediction_count") == 16, "prediction lock missing/incomplete")
    require(lock.get("heldout_truth_opened") is False and lock.get("comparative_metrics_emitted_during_fit") is False, "truth/comparison firewall receipt mismatch")
    lock_by_id = {x["fit_id"]: x for x in lock["prediction_streams"]}
    require(set(lock_by_id) == {r["fit_id"] for r in rows}, "prediction lock fit identities mismatch")

    init_by_block: dict[int, set[str]] = {b: set() for b in blocks}
    verified_entries = []
    for row in rows:
        fit_id = row["fit_id"]
        holdout = int(row["holdout_block"])
        receipt_path = run / "fit-receipts" / f"{fit_id}.json"
        receipt = read_json(receipt_path)
        require(receipt.get("status") == "PASS" and receipt.get("finite_status") == "PASS", f"fit receipt not passing {fit_id}")
        for key in ("fit_id", "arm", "holdout_block", "input_width", "train_rows", "heldout_rows", "feature_hash", "training_row_hash", "training_order_hash", "normalization_hash", "initial_tensor_hash"):
            expected = row[key]
            actual = receipt.get(key)
            if key in ("holdout_block", "input_width", "train_rows", "heldout_rows"):
                require(int(actual) == int(expected), f"fit receipt field mismatch {fit_id}:{key}")
            else:
                require(str(actual) == str(expected), f"fit receipt field mismatch {fit_id}:{key}")
        require(receipt.get("prediction_path") == row["expected_prediction_path"], f"prediction path mismatch {fit_id}")
        require(receipt["contract_sha256"] == manifest["contract_sha256"], f"fit contract mismatch {fit_id}")
        require(receipt["source_manifest_sha256"] == manifest["source_manifest_canonical_sha256"], f"fit source mismatch {fit_id}")
        require(receipt["implementation_executable_sha256"] == manifest["executor_sha256"], f"fit executable mismatch {fit_id}")
        require(receipt["analysis_script_sha256"] == manifest["script_hashes"]["analysis.py"], f"fit analysis hash mismatch {fit_id}")
        require(receipt["fit_script_sha256"] == manifest["script_hashes"]["fit.py"], f"fit implementation hash mismatch {fit_id}")
        train_n = int(row["train_rows"])
        require(int(receipt["update_count"]) == 200 * math.ceil(train_n / 2048), f"update count mismatch {fit_id}")
        matrix_path = run / "prepared-inputs" / f"{fit_id}.bin"
        raw_matrix = matrix_path.read_bytes()
        require(sha_bytes(raw_matrix[32:]) == row["feature_hash"], f"prepared feature changed {fit_id}")
        norm_path = run / "normalization" / f"NORMALIZATION-{holdout}.bin"
        require(sha_file(norm_path) == row["normalization_hash"], f"normalization artifact changed {fit_id}")
        require(receipt.get("fit_manifest_row_sha256") == recomputed_row_hashes[fit_id], f"fit-row provenance mismatch {fit_id}")
        require(receipt.get("repeat_prediction_identical") is True and receipt.get("heldout_truth_opened") is False, f"fit repeat/firewall mismatch {fit_id}")
        require(len(receipt.get("final_tensor_hash", "")) == 64, f"final tensor hash malformed {fit_id}")
        init_by_block[holdout].add(str(receipt["initial_tensor_hash"]))
        held_keys = [k for k in data.keys if struct.unpack_from("<Q", k, 2)[0] == holdout]
        pred_path = run / row["expected_prediction_path"]
        pred_sha = sha_file(pred_path)
        require(pred_sha == receipt["prediction_sha256"] == lock_by_id[fit_id]["prediction_sha256"], f"prediction digest mismatch {fit_id}")
        require(sha_file(receipt_path) == lock_by_id[fit_id]["fit_receipt_sha256"], f"fit receipt digest mismatch {fit_id}")
        logits = _prediction(pred_path, row, held_keys, recomputed_row_hashes[fit_id])
        verified_entries.append({"fit_id": fit_id, "receipt_sha256": sha_file(receipt_path), "prediction_sha256": pred_sha, "prediction_rows": len(logits)})
    for block, hashes in init_by_block.items():
        require(len(hashes) == 1, f"C/D paired initialization mismatch in block {block}")
    require(not any((run / name).exists() for name in ("final-outcomes.csv", "ANALYSIS.json", "RESULTS.md")), "analysis outputs exist before integrity gate")
    receipt = {
        "schema": "F4-SYMMETRY-03-integrity-receipt-v1", "status": "PASS",
        "run_id": manifest["run_id"], "contract_sha256": manifest["contract_sha256"],
        "source_manifest": source_details, "expected_fits": 16, "actual_fits": len(rows),
        "expected_prediction_streams": 16, "actual_prediction_streams": len(verified_entries),
        "rows": data.count, "block_ids": blocks, "paired_initialization": "PASS",
        "empty_Ustar_block_ids": empty_blocks,
        "missing_count": 0, "duplicate_count": 0, "extra_count": 0, "nonfinite_count": 0,
        "heldout_truth_state": "SEALED", "heldout_truth_values_opened": False,
        "verified_streams": verified_entries,
    }
    write_json(run / "INTEGRITY-RECEIPT.json", receipt)
    print(json.dumps({"status": "INTEGRITY_PASS", "fits": 16, "rows": data.count, "truth_state": "SEALED"}, sort_keys=True))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True)
    run_integrity(p.parse_args().run.resolve())
