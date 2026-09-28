"""Verify the complete Cphi engineering output surface before scoring it."""
from __future__ import annotations

import csv
import io
import json
import os
import struct
import sys
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

from cphi_model import deserialize_tensors, tensor_hash  # noqa: E402
from fit_common import BLOCKS, RUN as PARENT_RUN, load_raw_inputs, read_json, sha_file, write_json_new  # noqa: E402
from fit_contract import sha256_bytes  # noqa: E402
from run_cphi import PRED_MAGIC, RUN, RUN_ID  # noqa: E402


def _decode_prediction(raw: bytes, block: int, replicate: int, expected_keys: list[bytes]) -> list[float]:
    header_bytes = 16 + struct.calcsize("<IQBQ")
    if len(PRED_MAGIC) != 16 or len(raw) < header_bytes or raw[:16] != PRED_MAGIC:
        raise RuntimeError("Cphi prediction header mismatch")
    version, actual_block, actual_replicate, count = struct.unpack_from("<IQBQ", raw, 16)
    if (version, actual_block, actual_replicate, count) != (1, block, replicate, len(expected_keys)):
        raise RuntimeError("Cphi prediction identity/count mismatch")
    if len(raw) != header_bytes + count * 22:
        raise RuntimeError("Cphi prediction byte length mismatch")
    values: list[float] = []
    seen: set[bytes] = set()
    for index in range(count):
        offset = header_bytes + index * 22
        key = raw[offset:offset + 18]
        value = struct.unpack_from("<f", raw, offset + 18)[0]
        if key in seen or key != expected_keys[index] or not np.isfinite(value):
            raise RuntimeError(f"Cphi prediction row mismatch/nonfinite at {block}:{index}")
        seen.add(key)
        values.append(value)
    return values


def verify() -> dict[str, Any]:
    freeze = read_json(RUN / "ENGINEERING-PREFIT-FREEZE.json")
    source_manifest = read_json(RUN / "SOURCE-MANIFEST.json")
    if sha_file(RUN / "SOURCE-MANIFEST.json") != freeze.get("source_manifest_sha256"):
        raise RuntimeError("Cphi source manifest drift")
    for entry in source_manifest["files"]:
        path = REPO / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"Cphi source drift: {entry['path']}")
    parent_manifest_path = RUN / "PARENT-INPUT-MANIFEST.json"
    if sha_file(parent_manifest_path) != freeze.get("parent_input_manifest_sha256"):
        raise RuntimeError("Cphi parent-input manifest drift")
    parent_manifest = read_json(parent_manifest_path)
    for entry in parent_manifest["files"]:
        path = REPO / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"locked parent input drift: {entry['path']}")
    fit_manifest = read_json(RUN / "FIT-MANIFEST.json")
    initializer_manifest = read_json(RUN / "CPHI-INITIALIZER-MANIFEST.json")
    lock_path = RUN / "PREDICTION-LOCK.json"
    lock = read_json(lock_path)
    if (
        fit_manifest.get("fit_count") != 36
        or len(fit_manifest.get("rows", [])) != 36
        or len(initializer_manifest.get("cells", [])) != 36
        or lock.get("status") != "PASS"
        or lock.get("fit_count") != 36
        or len(lock.get("prediction_and_state_files", [])) != 36
        or lock.get("fit_manifest_sha256") != sha_file(RUN / "FIT-MANIFEST.json")
    ):
        raise RuntimeError("Cphi fit surface/prediction lock is incomplete")
    data = load_raw_inputs()
    manifest_by_id = {item["fit_id"]: item for item in fit_manifest["rows"]}
    init_by_id = {item["fit_id"]: item for item in initializer_manifest["cells"]}
    lock_by_id = {item["fit_id"]: item for item in lock["prediction_and_state_files"]}
    expected_ids = {f"CPHI-H{block}-I{rep}" for rep in range(3) for block in BLOCKS}
    if set(manifest_by_id) != expected_ids or set(init_by_id) != expected_ids or set(lock_by_id) != expected_ids:
        raise RuntimeError("Cphi fit identities are missing, duplicated, or extra")
    receipt_hashes = {}
    prediction_hashes = {}
    state_hashes = {}
    trace_hashes = {}
    for fit_id in sorted(expected_ids):
        row = manifest_by_id[fit_id]
        block = int(row["heldout_block"])
        replicate = int(row["replicate_index"])
        expected_keys = [data.keys[int(index)] for index in np.flatnonzero(data.blocks == np.uint64(block))]
        receipt_path = RUN / "fit-receipts" / f"{fit_id}.json"
        receipt = read_json(receipt_path)
        prediction_path = RUN / row["prediction_path"]
        state_path = RUN / row["heldout_state_path"]
        final_path = RUN / row["final_tensor_path"]
        trace_path = RUN / row["training_trace_path"]
        pred_raw = prediction_path.read_bytes()
        if sha256_bytes(pred_raw) != receipt.get("heldout_prediction_sha256"):
            raise RuntimeError(f"Cphi prediction hash mismatch: {fit_id}")
        logits = _decode_prediction(pred_raw, block, replicate, expected_keys)
        if len(logits) != int(row["heldout_rows"]):
            raise RuntimeError(f"Cphi heldout row count mismatch: {fit_id}")
        state_raw = state_path.read_bytes()
        if sha256_bytes(state_raw) != receipt.get("heldout_state_sha256"):
            raise RuntimeError(f"Cphi heldout-state hash mismatch: {fit_id}")
        with np.load(io.BytesIO(state_raw), allow_pickle=False) as state:
            keys = state["row_keys"]
            expected_key_array = np.frombuffer(b"".join(expected_keys), dtype=np.uint8).reshape(len(expected_keys), 18)
            if keys.shape != expected_key_array.shape or keys.tobytes() != expected_key_array.tobytes():
                raise RuntimeError(f"Cphi activation row-key mismatch: {fit_id}")
            required = ("ordered_tuples", "phi_outputs", "relational_concat", "posthoc_sum", "penultimate_hidden", "role_separation", "logits")
            if any(name not in state.files for name in required):
                raise RuntimeError(f"Cphi activation schema incomplete: {fit_id}")
            for name in required:
                array = state[name]
                if not np.isfinite(array).all():
                    raise RuntimeError(f"Cphi activation nonfinite: {fit_id}:{name}")
            if state["phi_outputs"].shape != (len(expected_keys), 4, 16) or state["relational_concat"].shape != (len(expected_keys), 64):
                raise RuntimeError(f"Cphi activation dimensions changed: {fit_id}")
            if state["logits"].astype(np.float32).tobytes() != np.asarray(logits, dtype=np.float32).tobytes():
                raise RuntimeError(f"Cphi prediction/state logits mismatch: {fit_id}")
        final_raw = final_path.read_bytes()
        final_tensors = deserialize_tensors(final_raw)
        if tensor_hash(final_tensors) != receipt.get("final_tensor_sha256"):
            raise RuntimeError(f"Cphi final tensor hash mismatch: {fit_id}")
        with trace_path.open("r", encoding="utf-8", newline="") as stream:
            trace_rows = list(csv.DictReader(stream))
        if len(trace_rows) != 200 or any(not np.isfinite(float(value)) for trace_row in trace_rows for value in trace_row.values()):
            raise RuntimeError(f"Cphi training trace malformed: {fit_id}")
        if receipt.get("finite_status") != "PASS" or receipt.get("update_count") != 200 * ((int(row["train_rows"]) + 2047) // 2048):
            raise RuntimeError(f"Cphi fit receipt failed contract checks: {fit_id}")
        receipt_hashes[fit_id] = sha_file(receipt_path)
        prediction_hashes[fit_id] = sha_file(prediction_path)
        state_hashes[fit_id] = sha_file(state_path)
        trace_hashes[fit_id] = sha_file(trace_path)
    for directory, expected_count in (("fit-receipts", 36), ("predictions", 36), ("heldout-state", 36), ("final-tensors", 36), ("training-traces", 36)):
        actual = list((RUN / directory).glob("*"))
        if len(actual) != expected_count:
            raise RuntimeError(f"unexpected files in Cphi {directory}: {len(actual)}")
    receipt = {
        "schema": "F4-PRESENTATION-02-integrity-receipt-v1",
        "identity": RUN_ID,
        "status": "PASS",
        "fit_count": 36,
        "architecture_parameter_count": 19_936,
        "parent_scientific_disposition": "NOT_EVALUABLE_SUPPORT",
        "parent_truth_previously_opened": True,
        "truth_opened_by_this_run_before_integrity": False,
        "prediction_lock_sha256": sha_file(lock_path),
        "fit_manifest_sha256": sha_file(RUN / "FIT-MANIFEST.json"),
        "source_manifest_sha256": sha_file(RUN / "SOURCE-MANIFEST.json"),
        "parent_input_manifest_sha256": sha_file(parent_manifest_path),
        "fit_receipt_hashes": receipt_hashes,
        "prediction_hashes": prediction_hashes,
        "heldout_state_hashes": state_hashes,
        "training_trace_hashes": trace_hashes,
        "missing_duplicate_extra_nonfinite_count": 0,
        "parent_D_S_bytes_changed": False,
        "qualification_only": True,
        "scientific_promotion": False,
    }
    write_json_new(RUN / "INTEGRITY-RECEIPT.json", receipt)
    return receipt


if __name__ == "__main__":
    result = verify()
    print(json.dumps({"status": result["status"], "fit_count": result["fit_count"], "prediction_lock_sha256": result["prediction_lock_sha256"]}, sort_keys=True))
