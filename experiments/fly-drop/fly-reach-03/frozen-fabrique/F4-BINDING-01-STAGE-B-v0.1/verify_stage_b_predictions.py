"""Independent pre-truth integrity audit of the locked Stage B prediction panel."""
from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

import binding_stage_b_data as data
import stage_b_runtime as runtime

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parents[1]
REPO = STUDY.parents[1]
RUN_ID = "F4-BINDING-01-STAGE-B-PROSP-v0.1"
RUN = STUDY / "runs" / RUN_ID
COLLECTION = RUN / "native-collection"
PREDICTIONS = RUN / "predictions"
FIT_RECEIPTS = RUN / "fit-receipts"
LOCK_PATH = RUN / "PREDICTION-LOCK.json"
INTEGRITY_PATH = RUN / "PRE-TRUTH-INTEGRITY-RECEIPT.json"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: Any) -> None:
    raw = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def verify_frozen_sources(freeze: dict[str, Any]) -> None:
    manifest_path = BRANCH / "SOURCE-INPUT-MANIFEST.json"
    registry_path = REPO / Path(freeze["model_registry_path"])
    if sha_file(manifest_path) != freeze["source_manifest_file_sha256"]:
        raise RuntimeError("Stage B source-input manifest changed")
    if sha_file(registry_path) != freeze["model_registry_sha256"]:
        raise RuntimeError("Stage B model registry changed")
    for entry in [*freeze["source_files"], *freeze["parent_artifacts"]]:
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen Stage B source/input drift: {entry['path']}")


def read_prediction_file(path: Path, expected_keys: tuple[bytes, ...]) -> tuple[int, str]:
    count = data._header(path, data.PRED_MAGIC, data.PRED_WIDTH)
    if count != len(expected_keys):
        raise RuntimeError(f"prediction row count mismatch: {path.name}")
    with path.open("rb") as stream:
        stream.seek(data.HEADER_WIDTH)
        for index, expected in enumerate(expected_keys):
            record = stream.read(data.PRED_WIDTH)
            if len(record) != data.PRED_WIDTH or record[:18] != expected:
                raise RuntimeError(f"prediction row key/order mismatch: {path.name}/{index}")
            logits = np.frombuffer(record, dtype="<f4", count=3, offset=18)
            if not np.isfinite(logits).all():
                raise RuntimeError(f"nonfinite locked logit: {path.name}/{index}")
        if stream.tell() != data.HEADER_WIDTH + count * data.PRED_WIDTH:
            raise RuntimeError(f"prediction file has an unexpected tail: {path.name}")
    return count, sha_file(path)


def audit() -> dict[str, Any]:
    if INTEGRITY_PATH.exists():
        raise RuntimeError("pre-truth integrity receipt already exists; preserve and stop")
    freeze = read_json(BRANCH / "IMPLEMENTATION-FREEZE.json")
    if freeze.get("status") != "PASS" or freeze.get("identity") != RUN_ID:
        raise RuntimeError("Stage B implementation freeze mismatch")
    runtime.require_frozen(freeze["runtime_identity"])
    verify_frozen_sources(freeze)
    collection_receipt = read_json(RUN / "COLLECTION-INTEGRITY-RECEIPT.json")
    if collection_receipt.get("status") != "PASS" or collection_receipt.get("target_values_opened") is not False:
        raise RuntimeError("Stage B collection audit not passed before target access")
    predictor_path = COLLECTION / "RAW-PREDICTORS.bin"
    truth_path = COLLECTION / "RAW-SCORING-TRUTH.bin"
    if sha_file(predictor_path) != collection_receipt["predictor_sha256"] or sha_file(truth_path) != collection_receipt["truth_sha256"]:
        raise RuntimeError("Stage B collection drift after seal")
    panel = data.load_predictors(predictor_path)
    truth_keys = data.audit_truth_keys(truth_path, panel.keys)

    lock = read_json(LOCK_PATH)
    if lock.get("status") != "PASS" or lock.get("identity") != RUN_ID:
        raise RuntimeError("Stage B prediction lock identity/status mismatch")
    if lock.get("implementation_freeze_sha256") != sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"):
        raise RuntimeError("prediction lock does not bind implementation freeze")
    if lock.get("collection_integrity_receipt_sha256") != sha_file(RUN / "COLLECTION-INTEGRITY-RECEIPT.json"):
        raise RuntimeError("prediction lock does not bind collection integrity")
    if lock.get("predictor_sha256") != sha_file(predictor_path):
        raise RuntimeError("prediction lock does not bind predictor input")
    models = lock.get("predictions", [])
    if len(models) != 36 or lock.get("model_count") != 36 or lock.get("row_count_per_model") != len(panel.keys):
        raise RuntimeError("prediction lock model/row grid incomplete")
    model_ids = {row["fit_id"] for row in models}
    if len(model_ids) != 36:
        raise RuntimeError("duplicate fit identity in prediction lock")
    expected_prediction_names = {f"{fit_id}.bin" for fit_id in model_ids}
    expected_receipt_names = {f"{fit_id}.json" for fit_id in model_ids}
    if {path.name for path in PREDICTIONS.iterdir()} != expected_prediction_names:
        raise RuntimeError("prediction directory has missing or extra files")
    if {path.name for path in FIT_RECEIPTS.iterdir()} != expected_receipt_names:
        raise RuntimeError("fit-receipt directory has missing or extra files")

    registry = read_json(REPO / Path(freeze["model_registry_path"]))
    registry_by_id = {row["fit_id"]: row for row in registry["models"]}
    checked = []
    for entry in models:
        fit_id = entry["fit_id"]
        if fit_id not in registry_by_id:
            raise RuntimeError(f"prediction lock includes unknown model: {fit_id}")
        prediction_path = RUN / entry["prediction_path"]
        receipt_path = RUN / entry["fit_receipt_path"]
        if sha_file(prediction_path) != entry["prediction_sha256"] or prediction_path.stat().st_size != entry["prediction_bytes"]:
            raise RuntimeError(f"prediction hash/length mismatch: {fit_id}")
        if sha_file(receipt_path) != entry["fit_receipt_sha256"]:
            raise RuntimeError(f"fit receipt hash mismatch: {fit_id}")
        count, digest = read_prediction_file(prediction_path, panel.keys)
        receipt = read_json(receipt_path)
        model_entry = registry_by_id[fit_id]
        if receipt.get("fit_id") != fit_id or receipt.get("row_count") != count:
            raise RuntimeError(f"fit receipt identity/row count mismatch: {fit_id}")
        if receipt.get("tensor_bundle_sha256") != model_entry["tensor"]["sha256"]:
            raise RuntimeError(f"fit receipt tensor mismatch: {fit_id}")
        if receipt.get("normalization_sha256") != model_entry["normalization"]["sha256"]:
            raise RuntimeError(f"fit receipt normalization mismatch: {fit_id}")
        if receipt.get("optimizer_state_created") is not False or receipt.get("gradient_or_update_called") is not False or receipt.get("phi_recomputed_per_intervention") is not False:
            raise RuntimeError(f"fit receipt records a forbidden operation: {fit_id}")
        if receipt.get("target_values_opened") is not False:
            raise RuntimeError(f"fit receipt reports target access: {fit_id}")
        before = receipt.get("parameter_hashes_before")
        after = receipt.get("parameter_hashes_after")
        if before != after or len(before or {}) != 8:
            raise RuntimeError(f"model parameter mutation or incomplete parameter audit: {fit_id}")
        h_records = receipt.get("h_source_hashes_by_block", [])
        if len(h_records) != 24:
            raise RuntimeError(f"H source audit block count mismatch: {fit_id}")
        for h_entry in h_records:
            if h_entry["h_sha256_before"] != h_entry["h_sha256_after"]:
                raise RuntimeError(f"H changed across intervention evaluation: {fit_id}/{h_entry['block_id']}")
        checked.append({
            "fit_id": fit_id,
            "prediction_sha256": digest,
            "fit_receipt_sha256": entry["fit_receipt_sha256"],
            "row_count": count,
            "parameter_unchanged": True,
            "H_unchanged": True,
        })

    return {
        "schema": "F4-BINDING-01-stage-b-pre-truth-integrity-receipt-v0.1",
        "identity": RUN_ID,
        "status": "PASS",
        "implementation_freeze_sha256": sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"),
        "source_manifest_sha256": sha_file(BRANCH / "SOURCE-INPUT-MANIFEST.json"),
        "model_registry_sha256": sha_file(REPO / Path(freeze["model_registry_path"])),
        "task_bank_manifest_sha256": sha_file(RUN / "task-bank" / "TASK-BANK-MANIFEST.json"),
        "collection_integrity_receipt_sha256": sha_file(RUN / "COLLECTION-INTEGRITY-RECEIPT.json"),
        "predictor_sha256": sha_file(predictor_path),
        "truth_file_sha256": truth_keys["truth_file_sha256"],
        "truth_values_opened": False,
        "truth_key_count": truth_keys["row_count"],
        "prediction_lock_sha256": sha_file(LOCK_PATH),
        "model_count": len(checked),
        "expected_model_counts": {"Cphi": 36},
        "prediction_row_count_per_model": len(panel.keys),
        "all_row_keys_match": True,
        "all_logits_finite": True,
        "all_parameters_unchanged": True,
        "all_H_unchanged_across_conditions": True,
        "all_sources_and_parent_artifacts_unchanged": True,
        "fit_checks": checked,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
    }


def main() -> None:
    write_new(INTEGRITY_PATH, audit())
    print(json.dumps({"status": "PASS", "models": 36, "truth_values_opened": False, "integrity_receipt_sha256": sha_file(INTEGRITY_PATH)}, sort_keys=True))


if __name__ == "__main__":
    main()
